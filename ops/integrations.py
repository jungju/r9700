"""Explicit adapters for account delivery, isolated changes, and a leased GPU worker.

Unconfigured adapters do not issue commands, contact accounts, or inspect GPUs.
"""
from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from .common import KST,atomic_json,digest,dumps,inside,now,parse_time,read_json


class PromotionAdapter(Protocol):
    def reconcile(self,idempotency_key: str) -> dict: ...
    def send(self,payload: dict,idempotency_key: str) -> dict: ...


class FakePromotionAdapter:
    """In-memory acceptance adapter. It cannot create an external post."""
    def __init__(self,lose_response=False): self.posts={}; self.lose_response=lose_response; self.send_count=0
    def reconcile(self,key): return self.posts.get(key,{'state':'NOT_FOUND'})
    def send(self,payload,key):
        if key in self.posts: return self.posts[key]
        self.send_count+=1
        result={'state':'SENT','remoteId':'fake:'+key,'sentAt':now(),'simulation':True}; self.posts[key]=result
        if self.lose_response: raise TimeoutError('simulated response loss')
        return result


class FileDeliveryAdapter:
    """Configured account worker contract; receipt exchange avoids shell/credential inheritance.

    A worker delivers each request id once and records SENT/NOT_FOUND/BLOCKED_AUTH.
    UNKNOWN cannot be resent until the worker authoritatively reconciles the key.
    """
    def __init__(self,directory): self.directory=Path(directory).resolve()
    def reconcile(self,key):
        path=inside(self.directory/'receipts',key+'.json')
        if not path.exists(): return {'state':'UNKNOWN'}
        result=read_json(path)
        if result.get('idempotencyKey')!=key: raise ValueError('delivery receipt identity mismatch')
        return result
    def send(self,payload,key):
        path=inside(self.directory/'requests',key+'.json')
        if not path.exists(): atomic_json(path,{'idempotencyKey':key,'payload':payload,'requestedAt':now()})
        return self.reconcile(key)


def promote(store,adapter=None,channel=None,account=None,dry_run=False,public_check=None):
    config=store.setting('promotion',{})
    channel=channel or config.get('channel','unconfigured'); account=account or config.get('accountId','unconfigured')
    if not dry_run:
        with store.db:
            for row in store.rows('SELECT * FROM content_items WHERE visible=1'):
                item=json.loads(row['payload'])
                # Useful authored guides qualify, stale announcements/metadata-only candidates do not.
                if item['kind'] not in ('guide','news') or 'summary-pending' in item['evidenceStatus']: continue
                if item['kind']=='news' and (not item.get('publishedAt') or parse_time(item['publishedAt'])<parse_time(now())-timedelta(days=7)): continue
                key=digest([channel,account,row['id'],row['material_revision']])
                payload={'contentId':row['id'],'materialRevision':row['material_revision'],'title':item['title'],
                         'text':item['summary'],'audience':'R9700 구매·설치 조건을 확인하려는 사용자',
                         'url':store.setting('siteUrl','https://r9700.jjgo.io')+'/content/'+item['slug'],
                         'sourceUrl':item['sourceUrl'],'evidenceStatus':item['evidenceStatus']}
                store.db.execute('INSERT OR IGNORE INTO promotion_posts VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (key,channel,account,row['id'],row['material_revision'],'DRAFT',dumps(payload),now(),None,None))
    if dry_run: return {'state':'DRY_RUN','externalCalls':0}
    if store.setting('promotionDeliveryPaused',False): return {'state':'BLOCKED_RECONCILIATION','externalCalls':0}
    if not adapter:
        if config.get('enabled') and config.get('workerDirectory') and config.get('accountVerified'):
            adapter=FileDeliveryAdapter(config['workerDirectory'])
        else: return {'state':'DRAFT','reason':'Account delivery is unconfigured','externalCalls':0,'draftCount':store.db.execute("SELECT COUNT(*) FROM promotion_posts WHERE state='DRAFT'").fetchone()[0]}
    owner='promotion-'+str(uuid.uuid4())
    if not store.acquire('promotion:'+channel+':'+account,owner): return {'state':'LOCKED'}
    try:
        pending=store.rows("SELECT * FROM promotion_posts WHERE channel=? AND account_id=? AND state IN ('UNKNOWN','SENDING') ORDER BY at",(channel,account))
        for row in pending:
            receipt=adapter.reconcile(row['id'])
            state=receipt.get('state','UNKNOWN')
            with store.db:
                if state=='SENT' and receipt.get('remoteId'):
                    store.db.execute('UPDATE promotion_posts SET state=?,sent_at=?,remote_id=? WHERE id=?',('SENT',receipt.get('sentAt',now()),receipt['remoteId'],row['id']))
                elif state=='NOT_FOUND': store.db.execute("UPDATE promotion_posts SET state='READY' WHERE id=?",(row['id'],))
                else: return {'state':'UNKNOWN','id':row['id'],'externalCalls':0}
        sent=store.rows("SELECT sent_at FROM promotion_posts WHERE channel=? AND account_id=? AND state='SENT' ORDER BY sent_at DESC LIMIT 1",(channel,account))
        if sent:
            last=parse_time(sent[0]['sent_at']); current=parse_time(now())
            if current-last<timedelta(hours=20) or current.astimezone(KST).date()==last.astimezone(KST).date(): return {'state':'RATE_LIMITED','externalCalls':0}
        row=store.db.execute("SELECT * FROM promotion_posts WHERE channel=? AND account_id=? AND state IN ('DRAFT','READY') ORDER BY at LIMIT 1",(channel,account)).fetchone()
        if not row: return {'state':'NO_ACTION','externalCalls':0}
        payload=json.loads(row['payload'])
        current=store.db.execute('SELECT material_revision,visible FROM content_items WHERE id=?',(row['content_id'],)).fetchone()
        if not current or not current['visible'] or current['material_revision']!=row['material_revision']: return {'state':'BLOCKED_STALE_CONTENT'}
        if public_check is None:
            from .security import SafeClient
            from urllib.parse import urlsplit
            def public_check(url):
                try:
                    return SafeClient().get(url,[urlsplit(store.setting('siteUrl','https://r9700.jjgo.io')).hostname]).status==200
                except Exception:
                    return False
        if not public_check(payload['url']): return {'state':'BLOCKED_PUBLIC_CHECK','externalCalls':0}
        reservation=None
        if isinstance(adapter,FileDeliveryAdapter) and config.get('costFree') is not True:
            from .workflows import reserve_cost
            if config.get('estimatedMaximumCost') is None or not config.get('currency'):
                return {'state':'BLOCKED_CONFIG','reason':'Delivery API cost is unconfigured'}
            reservation=reserve_cost(store,'promotion',config['estimatedMaximumCost'],config['currency'])
            if reservation['state']!='RESERVED': return reservation
            payload['costReservationId']=reservation['id']
            with store.db: store.db.execute('UPDATE promotion_posts SET payload=? WHERE id=?',(dumps(payload),row['id']))
        with store.db: store.db.execute("UPDATE promotion_posts SET state='SENDING' WHERE id=?",(row['id'],))
        try: receipt=adapter.send(payload,row['id'])
        except (TimeoutError,OSError): receipt={'state':'UNKNOWN'}
        state=receipt.get('state','UNKNOWN')
        if state not in ('SENT','UNKNOWN','BLOCKED_AUTH','FAILED'): state='UNKNOWN'
        if state=='SENT' and not receipt.get('remoteId'): state='UNKNOWN'
        if reservation:
            from .workflows import settle_cost
            settle_cost(store,reservation['id'],receipt.get('actualCost'))
        with store.db:
            store.db.execute('UPDATE promotion_posts SET state=?,sent_at=?,remote_id=? WHERE id=?',
                             (state,receipt.get('sentAt',now()) if state=='SENT' else None,receipt.get('remoteId'),row['id']))
        return {'state':state,'id':row['id'],'externalCalls':1,'simulation':bool(receipt.get('simulation'))}
    finally: store.release('promotion:'+channel+':'+account,owner)


ALLOWED_PREFIXES=('src/components/','src/layouts/','src/styles/','src/pages/news','src/pages/guides','src/pages/search','src/pages/prices','src/pages/products','src/pages/showcase','src/pages/content/')
PROTECTED=('ops','tests','tests-web','workers','src/middleware.ts','src/lib','src/pages/api','src/pages/admin','package.json','package-lock.json','sources.json','INTEGRATION.md')


def verify_changes(base: Path,candidate: Path):
    def files(root):
        result={}
        for p in root.rglob('*'):
            if any(part in ('node_modules','.git','.local','__pycache__','dist','.astro') for part in p.relative_to(root).parts): continue
            if p.is_symlink(): raise ValueError('candidate/source symbolic links are not accepted')
            if p.is_file(): result[p.relative_to(root).as_posix()]=p
        return result
    before=files(base); after=files(candidate); changed=[]; line_count=0
    for name in sorted(set(before)|set(after)):
        left=before[name].read_bytes() if name in before else b''; right=after[name].read_bytes() if name in after else b''
        if left==right: continue
        if name not in after: raise ValueError('automatic deletion is not allowed')
        if any(name==prefix or name.startswith(prefix+'/') for prefix in PROTECTED) or not any(name.startswith(prefix) for prefix in ALLOWED_PREFIXES): raise ValueError('protected path change: '+name)
        if after[name].is_symlink() or not after[name].resolve().is_relative_to(candidate.resolve()): raise ValueError('candidate link escapes staging')
        changed.append(name)
        diff=difflib.unified_diff(left.decode('utf-8').splitlines(),right.decode('utf-8').splitlines())
        line_count+=sum(1 for line in diff if line[:1] in ('+','-') and not line.startswith(('+++','---')))
    if not changed or len(changed)>5 or line_count>200: raise ValueError('change exceeds 5-file/200-line scope or has no changes')
    return {'files':changed,'changedLines':line_count,'hashes':{name:digest(after[name].read_bytes()) for name in changed}}


def improve(store,payload):
    """Queue isolated work; only a pinned container can validate its candidate."""
    config=store.setting('improvement',{})
    from .workflows import choose_improvement
    configured=all(config.get(key) for key in ('runnerDirectory','validationImage','hostExchangeDirectory'))
    if not configured:
        return {'state':'BLOCKED_CONFIG','reason':'Isolated runner, pinned validation image and host controller are unconfigured'}
    image=config['validationImage']
    import re
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',image):
        raise ValueError('validationImage must be pinned by sha256 digest')
    runner=Path(config['runnerDirectory']).resolve(); host=Path(config['hostExchangeDirectory']).resolve()
    pending=store.rows("SELECT * FROM improvement_changes WHERE state IN ('RUNNING','VALIDATED_AWAITING_HOST') ORDER BY at LIMIT 1")
    if pending:
        row=pending[0]; request_id=row['id']; record=json.loads(row['payload'])
        if row['state']=='VALIDATED_AWAITING_HOST':
            receipt_file=host/'receipts'/f'{request_id}.json'
            if not receipt_file.exists(): return {'state':'VALIDATED_AWAITING_HOST','id':request_id}
            receipt=read_json(receipt_file)
            if receipt.get('id')!=request_id or receipt.get('manifestHash')!=record['manifestHash']:
                raise ValueError('host receipt identity or manifest mismatch')
            state=receipt.get('state')
            if state=='BLOCKED_CONFIG':
                record['hostReceipt']=receipt
                with store.db: store.db.execute('UPDATE improvement_changes SET payload=? WHERE id=?',(dumps(record),request_id))
                return {'state':'BLOCKED_CONFIG','id':request_id,'reason':'Host controller configuration is incomplete'}
            if state not in ('DEPLOYED','ROLLED_BACK','FAILED'): raise ValueError('unknown host outcome')
            if state=='DEPLOYED' and any(receipt.get('checks',{}).get(key)!='PASS' for key in ('http','search','prices','mobile')):
                raise ValueError('deployment receipt lacks required postchecks')
            if state=='ROLLED_BACK' and receipt.get('releaseId')!=record.get('previousRelease'):
                raise ValueError('rollback receipt does not restore previous code release')
            record['hostReceipt']=receipt; record['visitorEffect']='UNMEASURED'
            with store.db:
                store.db.execute('UPDATE improvement_changes SET state=?,payload=? WHERE id=?',('CLOSED' if state=='DEPLOYED' else 'FAILED',dumps(record),request_id))
                if state=='DEPLOYED': store.set_setting('currentCodeRelease',receipt['releaseId'])
            return {'state':state,'id':request_id,'operationalDatabasePreserved':True}
        receipt_file=runner/'receipts'/f'{request_id}.json'
        if not receipt_file.exists(): return {'state':'RUNNING','id':request_id,'reason':'Waiting for isolated runner candidate'}
        receipt=read_json(receipt_file)
        if receipt.get('requestId')!=request_id: raise ValueError('runner receipt identity mismatch')
        if record.get('costReservationId'):
            from .workflows import settle_cost
            settle_cost(store,record['costReservationId'],receipt.get('actualCost'))
        candidate_id=receipt.get('candidateId','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',candidate_id): raise ValueError('invalid candidate ID')
        candidate=inside(store.local/'improvement-inbox',candidate_id)
        try:
            changes=verify_changes(store.root,candidate)
            if not shutil.which('docker'): return {'state':'BLOCKED_CONFIG','id':request_id,'reason':'Docker sandbox runtime is unavailable'}
            # Reconstruct from trusted source, then copy only reviewed public changes.
            stage=store.local/'validation-staging'/request_id
            if stage.exists(): raise ValueError('staging directory already exists; inspect prior validation')
            stage.mkdir(parents=True)
            for file in store.root.rglob('*'):
                name=file.relative_to(store.root)
                if any(part in ('node_modules','.git','.local','__pycache__','dist','.astro') for part in name.parts): continue
                if file.is_file() and not file.name.startswith('.env') and not file.is_symlink():
                    destination=stage/name; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(file,destination)
            for name in changes['files']: shutil.copy2(candidate/name,stage/name)
            command=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
                     '--security-opt','no-new-privileges','--user','10001:10001','--cpus','2','--memory','2g','--pids-limit','256',
                     '--tmpfs','/work:rw,nosuid,size=1g,mode=1777','--tmpfs','/tmp:rw,nosuid,size=256m,mode=1777',
                     '--mount',f'type=bind,src={stage},dst=/candidate,readonly',
                     '--mount',f'type=bind,src={store.root / "ops"},dst=/trusted-ops,readonly',
                     '--entrypoint','python',image,'/trusted-ops/validate_candidate.py']
            validation=subprocess.run(command,capture_output=True,text=True,timeout=360)
            if validation.returncode: raise ValueError('sandbox fixed validation failed')
            if changes!=verify_changes(store.root,candidate): raise ValueError('candidate changed during validation')
            result=json.loads(validation.stdout.strip().splitlines()[-1])
            if result.get('state')!='PASS' or result.get('checks')!=['python','web-tests','typecheck','build','mobile']:
                raise ValueError('fixed validator receipt is incomplete')
            release=store.local/'code-releases'/request_id
            shutil.copytree(stage,release)
            manifest={'id':request_id,'changes':changes,'validation':result,'validatedAt':now(),'schemaVersion':1}
            atomic_json(release/'validation-receipt.json',manifest)
            record.update({'releasePath':str(release),'manifestHash':digest(manifest),'changes':changes,
                           'previousRelease':store.setting('currentCodeRelease'),'validation':'PASS','visitorEffect':'UNMEASURED'})
            with store.db: store.db.execute('UPDATE improvement_changes SET state=?,payload=? WHERE id=?',('VALIDATED_AWAITING_HOST',dumps(record),request_id))
            atomic_json(host/'requests'/f'{request_id}.json',{'id':request_id,'releasePath':str(release),'manifestHash':record['manifestHash'],
                        'previousRelease':record['previousRelease'],'requiredChecks':['http','search','prices','mobile'],'rollbackDatabase':False})
            return {'state':'VALIDATED_AWAITING_HOST','id':request_id,'manifestHash':record['manifestHash']}
        except (ValueError,subprocess.TimeoutExpired,OSError) as error:
            record['error']=str(error); record['resumeCondition']='New evidence; at most two attempts per problem'
            with store.db: store.db.execute('UPDATE improvement_changes SET state=?,payload=? WHERE id=?',('FAILED',dumps(record),request_id))
            return {'state':'FAILED','id':request_id,'error':str(error)}
    chosen=choose_improvement(store,True)
    if chosen['state']!='READY': return chosen
    reservation=None
    if config.get('runnerCostMode')!='free':
        from .workflows import reserve_cost
        if config.get('estimatedMaximumCost') is None or not config.get('currency'):
            return {'state':'BLOCKED_CONFIG','reason':'Runner cost mode or paid reservation settings are missing'}
        reservation=reserve_cost(store,'improvement',config['estimatedMaximumCost'],config['currency'])
        if reservation['state']!='RESERVED': return reservation
    request_id='improvement-'+str(uuid.uuid4())
    baseline={p.relative_to(store.root).as_posix():digest(p.read_bytes()) for p in store.root.rglob('*')
              if p.is_file() and not p.is_symlink() and not any(part in ('.local','node_modules','.git','dist','.astro','__pycache__') for part in p.relative_to(store.root).parts) and not p.name.startswith('.env')}
    request={'id':request_id,'problemKey':chosen['problemKey'],'evidenceHash':chosen['evidenceHash'],'question':chosen['question'],
             'target':chosen['target'],'proposedChange':chosen['proposedChange'],'verification':chosen['verification'],
             'allowedPrefixes':list(ALLOWED_PREFIXES),'maxFiles':5,'maxChangedLines':200,'baselineManifest':baseline,
             'costReservationId':reservation['id'] if reservation else None,
             'sourceInputsAreUntrusted':True,'allowedOutput':'candidate files only; no instructions to controller'}
    input_directory=runner/'inputs'/request_id
    input_directory.mkdir(parents=True)
    for name in baseline:
        destination=inside(input_directory,name); destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(store.root/name,destination)
    request['inputDirectory']=str(input_directory)
    with store.db: store.db.execute('INSERT INTO improvement_changes VALUES(?,?,?,?,?,?)',
        (request_id,chosen['problemKey'],chosen['evidenceHash'],'RUNNING',dumps(request),now()))
    atomic_json(runner/'requests'/f'{request_id}.json',request)
    return {'state':'RUNNING','id':request_id,'reason':'Isolated runner request queued'}


def generation(store,action,payload):
    owner='gpu-queue-'+str(uuid.uuid4())
    if not store.acquire('gpu-queue',owner): return {'state':'DEFERRED','reason':'Another queue owner is active','gpuProbes':0}
    try: return _generation(store,action,payload)
    finally: store.release('gpu-queue',owner)


def _generation(store,action,payload):
    config=store.setting('gpu',{})
    if action=='enqueue':
        if not payload.get('workflowId'): raise ValueError('workflowId is required')
        id='generation-'+digest(payload)[:24]
        with store.db: store.db.execute('INSERT OR IGNORE INTO generation_jobs VALUES(?,?,?,?)',(id,'WAITING',dumps(payload),now()))
    if not config.get('enabled') or not config.get('workerDirectory'):
        with store.db: store.db.execute("UPDATE generation_jobs SET state='DEFERRED' WHERE state='WAITING'")
        return {'state':'DEFERRED','reason':'GPU worker and explicit device lease are unconfigured','gpuProbes':0}
    worker=Path(config['workerDirectory']).resolve()
    jobs=store.rows("SELECT * FROM generation_jobs WHERE state NOT IN ('COMPLETED','FAILED') ORDER BY at")
    for row in jobs:
        job=json.loads(row['payload']); receipt_path=worker/'receipts'/f"{row['id']}.json"
        if receipt_path.exists():
            receipt=read_json(receipt_path)
            required={'jobId':row['id'],'attemptId':job.get('attemptId'),'leaseToken':job.get('leaseToken'),
                      'deviceIds':job.get('deviceIds'),'workflowHash':job.get('workflowHash'),'modelHash':job.get('modelHash')}
            if any(receipt.get(key)!=value for key,value in required.items()) or not all(required.values()): raise ValueError('worker completion identity mismatch')
            if receipt.get('state')=='COMPLETED':
                output=inside(store.local/'media',receipt.get('output',''))
                if not output.is_file() or digest(output.read_bytes())!=receipt.get('outputHash') or not receipt.get('completionLogHash'): raise ValueError('worker output is partial or mismatched')
                job.update(receipt)
                with store.db: store.db.execute('UPDATE generation_jobs SET state=?,payload=? WHERE id=?',('COMPLETED',dumps(job),row['id']))
                atomic_json(worker/'requests'/f"release-{row['id']}.json",{'action':'release-owned-lease',**required})
                if job.get('showcase'):
                    from .workflows import import_showcase
                    import_showcase(store,{**job['showcase'],'url':'/media/'+receipt['output'],'sha256':receipt['outputHash'],
                       'provenance':'verified-local-run','runEvidence':{**required,'completionLogHash':receipt['completionLogHash']}})
                continue
        if row['state']=='TIMEOUT_AWAITING_RELEASE':
            return {'state':'DEFERRED','reason':'Own timed-out attempt awaits confirmed release','gpuProbes':0}
        if row['state']=='RUNNING':
            if parse_time(job['startedAt'])+timedelta(seconds=config.get('timeoutSeconds',0))<parse_time(now()):
                atomic_json(worker/'requests'/f"cancel-{row['id']}.json",{'action':'cancel-owned-attempt','jobId':row['id'],'attemptId':job['attemptId'],'leaseToken':job['leaseToken']})
                with store.db: store.db.execute("UPDATE generation_jobs SET state='TIMEOUT_AWAITING_RELEASE' WHERE id=?",(row['id'],))
            return {'state':'RUNNING','jobId':row['id'],'gpuProbes':0}
        lease_path=worker/'lease.json'
        lease=read_json(lease_path) if lease_path.exists() else {}
        if lease.get('state')!='OWNED_IDLE' or lease.get('owner')!='r9700-hub' or not lease.get('leaseToken') or not lease.get('expiresAt') or parse_time(lease['expiresAt'])<=parse_time(now()):
            with store.db: store.db.execute("UPDATE generation_jobs SET state='DEFERRED' WHERE id=?",(row['id'],))
            return {'state':'DEFERRED','reason':'Busy or unknown device ownership','gpuProbes':0}
        if not config.get('devices') or set(lease.get('deviceIds',[]))!=set(config['devices']) or job['workflowId'] not in config.get('workflows',{}) or not config.get('timeoutSeconds'):
            return {'state':'DEFERRED','reason':'Device/workflow/timeout configuration mismatch','gpuProbes':0}
        usage=shutil.disk_usage(store.local)
        if usage.free<int(config.get('minimumFreeBytes',10*1024**3)): return {'state':'DEFERRED','reason':'Media free-space floor reached'}
        media=store.local/'media'; media.mkdir(exist_ok=True)
        if sum(file.stat().st_size for file in media.rglob('*') if file.is_file())>=int(config.get('mediaLimitBytes',50*1024**3)): return {'state':'DEFERRED','reason':'Media capacity reached'}
        workflow=config['workflows'][job['workflowId']]
        if not workflow.get('modelHash') or not workflow.get('workflowHash'): return {'state':'DEFERRED','reason':'Pinned model/workflow hashes absent'}
        job.update({'jobId':row['id'],'attemptId':str(uuid.uuid4()),'leaseToken':lease['leaseToken'],'deviceIds':lease['deviceIds'],
                    'startedAt':now(),**workflow})
        with store.db: store.db.execute('UPDATE generation_jobs SET state=?,payload=? WHERE id=?',('RUNNING',dumps(job),row['id']))
        atomic_json(worker/'requests'/f"{row['id']}.json",job)
        return {'state':'RUNNING','jobId':row['id'],'gpuProbes':0}
    return {'state':'NO_ACTION','gpuProbes':0}
