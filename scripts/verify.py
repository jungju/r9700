"""Fixed local integration gate. Does not collect, deploy, post, or use GPUs."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    npm=['cmd.exe','/d','/c','npm'] if os.name=='nt' else ['npm']
    checks=[]; server=None
    def run(name,command,env=None,timeout=180):
        result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        item={'name':name,'state':'PASS' if result.returncode==0 else 'FAIL','exitCode':result.returncode}
        if result.returncode: item['diagnostic']=(result.stdout+'\n'+result.stderr)[-10000:]
        checks.append(item); print(json.dumps(item,ensure_ascii=False),flush=True)
        if result.returncode: raise RuntimeError(name+' failed')
    try:
        run('typecheck',npm+['run','check'])
        run('production-build',npm+['run','build'])
        run('python-operations',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'])
        run('host-controller',[sys.executable,'-m','unittest','discover','-s','tests-workers','-p','test_*.py'])
        env={**os.environ,'HOST':'127.0.0.1','PORT':'4325'}
        server=subprocess.Popen(['node','dist/server/entry.mjs'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        base='http://127.0.0.1:4325'; ready=False
        for _ in range(100):
            try:
                with urllib.request.urlopen(base+'/api/health',timeout=1) as response: ready=response.status==200
                if ready: break
            except Exception: time.sleep(.1)
        if not ready: raise RuntimeError('Production verification server failed to start')
        run('web-unit-and-production-http',['node','--test','tests-web/auth.test.mjs','tests-web/http.test.mjs','tests-web/search.test.mjs'],{**os.environ,'TEST_BASE_URL':base})
        run('isolated-auth-media-browser',['node','tests-web/full.integration.mjs'],timeout=180)
        run('responsive-browser',['node','tests-web/mobile-check.mjs','--url',base],timeout=180)
        if shutil.which('docker'): run('compose-config',['docker','compose','config','--quiet'])
        report={'state':'PASS','checkedAt':datetime.now(timezone.utc).isoformat(),'checks':checks,
                'scope':'local implementation and fixed fixtures; no live deployment/social/GPU',
                'domain':'https://r9700.jjgo.io','publicDeploymentVerified':False}
        output=ROOT/'output/verification.json';output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'state':'PASS','stages':len(checks),'report':str(output)},ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'state':'FAIL','error':str(error),'checks':checks},ensure_ascii=False));return 1
    finally:
        if server:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired: server.kill();server.wait()

if __name__=='__main__': raise SystemExit(main())
