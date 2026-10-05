from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT=Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0,str(REPO_ROOT))

from ops.common import atomic_json,digest,read_json
from workers.host_controller import REQUIRED_CHECKS,process_exchange


class _HealthHandler(BaseHTTPRequestHandler):
    state_file: Path
    def do_GET(self):
        if self.path != '/health':
            self.send_error(404);return
        try:
            release_id=self.state_file.read_text(encoding='utf-8').strip()
        except OSError:
            release_id=''
        body=json.dumps({'releaseId':release_id}).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*_args):
        return


@contextmanager
def health_server(state_file: Path):
    class Handler(_HealthHandler):
        pass
    Handler.state_file=state_file
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/health'
    finally:
        server.shutdown();thread.join(timeout=2);server.server_close()


class HostControllerTests(unittest.TestCase):
    request_id='improvement-test-001'

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'project'
        self.exchange=self.root/'.local'/'host-exchange'
        self.release=self.root/'.local'/'code-releases'/self.request_id
        self.root.mkdir(parents=True)
        (self.root/'src/pages/news').mkdir(parents=True)
        (self.root/'src/pages/news/index.astro').write_text('old public page\n',encoding='utf-8')
        (self.root/'ops').mkdir();(self.root/'ops/common.py').write_text('protected\n',encoding='utf-8')
        (self.root/'tests').mkdir();(self.root/'tests/test_core.py').write_text('protected\n',encoding='utf-8')
        (self.root/'tests-workers').mkdir();(self.root/'tests-workers/test_host_controller.py').write_text('protected\n',encoding='utf-8')
        (self.root/'.local').mkdir(exist_ok=True)
        self.db=self.root/'.local'/'operations.sqlite3';self.db.write_bytes(b'protected-db')
        self.state_file=self.root/'.local'/'active-release.txt';self.state_file.write_text('release-previous',encoding='utf-8')
        self.log_file=self.root/'.local'/'command.log'
        self.fake_command=self.root/'.local'/'fake_operator.py'
        self.fake_command.write_text(self._fake_source(),encoding='utf-8')
        self.exchange.mkdir(parents=True)
        (self.exchange/'requests').mkdir();(self.exchange/'receipts').mkdir()
        (self.exchange/'journals').mkdir();(self.exchange/'locks').mkdir()
        self.config_path=self.root/'.local'/'host-controller.json'
        self._make_release()
        self.db_hash=digest(self.db.read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def _fake_source(self):
        return '''import json,sys,urllib.request
mode,state_file,log_file,*rest=sys.argv[1:]
def record(value):
    with open(log_file,'a',encoding='utf-8') as stream: stream.write(value+'\\n')
if mode=='deploy':
    release=rest[0];open(state_file,'w',encoding='utf-8').write(release);record('deploy:'+release);sys.exit(0)
if mode=='rollback':
    release=rest[0];open(state_file,'w',encoding='utf-8').write(release);record('rollback:'+release);sys.exit(0)
if mode=='http':
    with urllib.request.urlopen(rest[0],timeout=2) as response: print(response.read().decode('utf-8'))
    record('http');sys.exit(0)
if mode=='check':
    name=rest[0];record('check:'+name)
    if name=='search-fail' and open(state_file,encoding='utf-8').read().strip()!='release-previous': sys.exit(3)
    if name=='secret-check' and 'R9700_HOST_SECRET' in __import__('os').environ: sys.exit(4)
    sys.exit(0)
sys.exit(9)
'''

    def _make_release(self):
        self.release.mkdir(parents=True)
        for path in self.root.rglob('*'):
            relative=path.relative_to(self.root)
            if '.local' in relative.parts: continue
            target=self.release/relative
            if path.is_dir():target.mkdir(parents=True,exist_ok=True)
            elif path.is_file():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        candidate=self.release/'src/pages/news/index.astro'
        candidate.write_text('validated public page\n',encoding='utf-8')
        approved={'src/pages/news/index.astro':digest(candidate.read_bytes())}
        manifest={'schemaVersion':1,'id':self.request_id,'changes':{'files':list(approved),'changedLines':2,'hashes':approved},
                  'validation':{'state':'PASS','checks':['python','web-tests','typecheck','build','mobile']},'validatedAt':'2026-10-05T00:00:00+00:00'}
        atomic_json(self.release/'validation-receipt.json',manifest)
        self.manifest_hash=digest(manifest)
        self.request={'id':self.request_id,'releasePath':str(self.release),'manifestHash':self.manifest_hash,
                      'previousRelease':'release-previous','requiredChecks':list(REQUIRED_CHECKS),'rollbackDatabase':False}
        atomic_json(self.exchange/'requests'/f'{self.request_id}.json',self.request)

    def _argv(self,*args):
        return [sys.executable,str(self.fake_command),*args]

    def _write_config(self,url,fail_search=False,secret_check=False):
        config={'schemaVersion':1,'projectRoot':str(self.root),'hostExchangeDirectory':str(self.exchange),
                'commandTimeoutSeconds':5,
                'deployArgv':self._argv('deploy',str(self.state_file),str(self.log_file),'{releaseId}'),
                'rollbackArgv':self._argv('rollback',str(self.state_file),str(self.log_file),'{previousRelease}'),
                'verifyArgv':{'http':self._argv('http',str(self.state_file),str(self.log_file),url),
                              'search':self._argv('check',str(self.state_file),str(self.log_file),'search-fail' if fail_search else ('secret-check' if secret_check else 'search')),
                              'prices':self._argv('check',str(self.state_file),str(self.log_file),'prices'),
                              'mobile':self._argv('check',str(self.state_file),str(self.log_file),'mobile')}}
        atomic_json(self.config_path,config)

    def _run_controller(self,url,**kwargs):
        self._write_config(url,**kwargs)
        return process_exchange(self.root,self.exchange,self.config_path)

    def test_deploy_checks_health_id_and_writes_one_terminal_receipt(self):
        with health_server(self.state_file) as url:
            result=self._run_controller(url)
        self.assertEqual(result[0]['state'],'DEPLOYED')
        self.assertEqual(result[0]['releaseId'],self.request_id)
        self.assertEqual(result[0]['checks'],{name:'PASS' for name in REQUIRED_CHECKS})
        self.assertEqual(digest(self.db.read_bytes()),self.db_hash)
        with health_server(self.state_file) as url:
            second=self._run_controller(url)
        self.assertEqual(second,[{'id':self.request_id,'state':'SKIPPED_RECEIPT_EXISTS'}])
        log=self.log_file.read_text(encoding='utf-8').splitlines()
        self.assertEqual(sum(line.startswith('deploy:') for line in log),1)

    def test_regression_runs_fixed_rollback_and_confirms_previous_release(self):
        with health_server(self.state_file) as url:
            result=self._run_controller(url,fail_search=True)
        self.assertEqual(result[0]['state'],'ROLLED_BACK')
        self.assertEqual(result[0]['releaseId'],'release-previous')
        self.assertEqual(result[0]['checks']['search'],'FAIL')
        self.assertEqual(self.state_file.read_text(encoding='utf-8'),'release-previous')
        self.assertEqual(digest(self.db.read_bytes()),self.db_hash)

    def test_changed_validated_bytes_fail_before_any_deploy(self):
        (self.release/'src/pages/news/index.astro').write_text('tampered\n',encoding='utf-8')
        with health_server(self.state_file) as url:
            result=self._run_controller(url)
        self.assertEqual(result[0]['state'],'FAILED')
        self.assertEqual(self.state_file.read_text(encoding='utf-8'),'release-previous')
        self.assertFalse(self.log_file.exists())

    def test_unconfigured_controller_writes_blocked_receipt(self):
        result=process_exchange(self.root,self.exchange,self.root/'.local'/'missing-config.json')
        self.assertEqual(result[0]['state'],'BLOCKED_CONFIG')
        self.assertTrue((self.exchange/'receipts'/f'{self.request_id}.json').is_file())

    def test_live_controller_lock_blocks_a_second_worker(self):
        with health_server(self.state_file) as url:
            self._write_config(url)
            lock=self.exchange/'locks'/'host-controller.lock'
            atomic_json(lock,{'pid':os.getpid(),'startedAt':'test'})
            result=process_exchange(self.root,self.exchange,self.config_path)
        self.assertEqual(result[0]['state'],'LOCKED')
        self.assertFalse((self.exchange/'receipts'/f'{self.request_id}.json').exists())
        self.assertFalse(self.log_file.exists())

    def test_invalid_operator_command_template_is_blocked_before_execution(self):
        with health_server(self.state_file) as url:
            self._write_config(url)
            config=read_json(self.config_path)
            config['verifyArgv']['search'][-1]='{candidateShellCommand}'
            atomic_json(self.config_path,config)
            result=process_exchange(self.root,self.exchange,self.config_path)
        self.assertEqual(result[0]['state'],'BLOCKED_CONFIG')
        self.assertFalse(self.log_file.exists())

    def test_interrupted_intent_is_terminal_and_never_replayed(self):
        atomic_json(self.exchange/'journals'/f'{self.request_id}.json',{'id':self.request_id,'stage':'DEPLOY_PENDING'})
        with health_server(self.state_file) as url:
            result=self._run_controller(url)
        self.assertEqual(result[0]['state'],'FAILED')
        self.assertIn('replay is suppressed',result[0]['detail'])
        self.assertEqual(self.state_file.read_text(encoding='utf-8'),'release-previous')
        self.assertFalse(self.log_file.exists())

    def test_commands_receive_no_inherited_host_secret(self):
        with patch.dict(os.environ,{'R9700_HOST_SECRET':'must-not-pass'}):
            with health_server(self.state_file) as url:
                result=self._run_controller(url,secret_check=True)
        self.assertEqual(result[0]['state'],'DEPLOYED')

    def test_release_path_escape_is_rejected(self):
        outside=Path(self.temp.name)/'outside';outside.mkdir()
        self.request['releasePath']=str(outside)
        atomic_json(self.exchange/'requests'/f'{self.request_id}.json',self.request)
        with health_server(self.state_file) as url:
            result=self._run_controller(url)
        self.assertEqual(result[0]['state'],'FAILED')
        self.assertFalse(self.log_file.exists())

    def test_protected_operations_code_change_is_rejected(self):
        (self.release/'ops/common.py').write_text('candidate alteration\n',encoding='utf-8')
        with health_server(self.state_file) as url:
            result=self._run_controller(url)
        self.assertEqual(result[0]['state'],'FAILED')
        self.assertFalse(self.log_file.exists())

    def test_candidate_database_is_rejected(self):
        (self.release/'.local').mkdir()
        (self.release/'.local'/'operations.sqlite3').write_bytes(b'fake candidate database')
        with health_server(self.state_file) as url:
            result=self._run_controller(url)
        self.assertEqual(result[0]['state'],'FAILED')
        self.assertFalse(self.log_file.exists())


if __name__=='__main__':
    unittest.main()
