from __future__ import annotations

import json
import math
import re
import shutil
import struct
import uuid
from datetime import timedelta
from pathlib import Path

from .common import digest,dumps,inside,now,parse_time,redact
from .security import plain_text,safe_url


def question(store,payload):
    allowed={'question','environment','signalOrigin','failureType','evidence','answerIds','target','proposedChange','verification','impact','evidenceStrength','recurrence','effort','priorityClass'}
    if set(payload)-allowed: raise ValueError('unknown question fields')
    text=redact(plain_text(payload.get('question',''),240))
    if len(text)<3: raise ValueError('question must contain 3-240 characters')
    origin=payload.get('signalOrigin','user-feedback')
    if origin not in ('editorial-seed','observed-search','user-feedback','reproduced-task-failure'): raise ValueError('invalid signal origin')
    environment=redact(str(payload.get('environment','unspecified')))[:240]
    problem_key=digest([text.casefold(),environment,payload.get('failureType','answer-gap')])
    evidence=redact(plain_text(payload.get('evidence',''),2000)); evidence_hash=digest(evidence)
    data={**payload,'question':text,'environment':environment,'signalOrigin':origin,'evidence':evidence,'problemKey':problem_key,
          'visitorEffect':'UNMEASURED','recurrence':min(int(payload.get('recurrence',0)),2)}
    state='OBSERVED' if evidence else 'WAITING_EVIDENCE'; qid='question-'+problem_key[:20]
    with store.db:
        store.db.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?) ON CONFLICT(problem_key) DO UPDATE SET payload=excluded.payload,evidence_hash=excluded.evidence_hash,last_seen=excluded.last_seen',
                         (qid,problem_key,dumps(data),state,evidence_hash,now(),now()))
    return {'id':qid,'state':state,'signalOrigin':origin}


def feedback(store,payload):
    if set(payload)-{'query','kind'}: raise ValueError('unknown feedback fields')
    kind=payload.get('kind')
    if kind not in ('search-miss','helpful','missing-context'): raise ValueError('invalid feedback kind')
    # No unique-visitor claim is derived from anonymous public submissions.
    return question(store,{'question':payload.get('query',''),'signalOrigin':'observed-search' if kind=='search-miss' else 'user-feedback',
                          'failureType':kind,'evidenceStrength':1,'recurrence':0})


def submit(store,payload):
    if set(payload)-{'type','url','title','creator','rights','evidence','notes'}: raise ValueError('unknown submission fields')
    if payload.get('type','showcase') not in ('showcase','correction'): raise ValueError('invalid submission type')
    url=safe_url(payload.get('url',''))
    data={key:redact(plain_text(str(value),1000)) for key,value in payload.items() if key!='url'}
    if not data.get('title'): raise ValueError('title is required')
    if payload.get('type','showcase')=='showcase' and (not data.get('rights') or not data.get('creator')): raise ValueError('creator and rights declaration required')
    data['url']=url; key='submission-'+digest(data)[:24]
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?)',(key,'submission',now(),dumps(data),'WAITING_EVIDENCE'))
    return {'id':key,'state':'WAITING_EVIDENCE','published':False}


def audit(store):
    from .publication import snapshot
    data=snapshot(store); findings=[]
    def finding(key,detail,classification='evidence-gap',evidence=1):
        findings.append({'key':key,'detail':detail,'classification':classification})
        question(store,{'question':detail,'signalOrigin':'editorial-seed','failureType':classification,
                        'evidence':key,'evidenceStrength':evidence,'priorityClass':3,'target':key,'effort':1})
    for region in ('KR','US','EU'):
        if not any(price['region']==region and price['price'] is not None for price in data['prices']): finding('price-'+region,region+' 지역의 실제 판매 조건과 가격 근거가 필요합니다.')
    for media_type in ('image','video'):
        if not any(item['type']==media_type and item['provenance']!='unverified-reference' for item in data['showcase']): finding('showcase-'+media_type,'R9700 제작 근거와 게시 권한이 있는 '+media_type+' 자료가 필요합니다.')
    for row in store.rows('SELECT content_id,source_id,claim_key,evidence_hash FROM content_sources WHERE changed=1'):
        finding('evidence:'+row['content_id'],'연결된 원문 개정이 '+row['content_id']+' 설명에 미치는 영향을 확인하세요.','evidence-change',3)
    runtime={'state':'BLOCKED_CONFIG','reason':'Public HTTP audit is not enabled'}
    browser={'state':'BLOCKED_CONFIG','reason':'Fixed browser/media audit worker is unconfigured'}
    config=store.setting('audit',{})
    if config.get('httpEnabled') is True:
        from .security import SafeClient
        from urllib.parse import urlsplit
        import time
        client=SafeClient(); deadline=time.monotonic()+120; checks=[]
        for path in ('/','/news','/guides','/prices','/search','/showcase'):
            url=data['siteUrl'].rstrip('/')+path
            try:
                response=client.get(url,[urlsplit(data['siteUrl']).hostname],deadline=deadline)
                checks.append({'path':path,'state':'PASS' if response.status==200 else 'FAIL'})
            except Exception as error:
                checks.append({'path':path,'state':'FAIL','error':redact(str(error))})
        runtime={'state':'PASS' if all(item['state']=='PASS' for item in checks) else 'FAIL','checks':checks,'scope':'HTTP availability only'}
    if config.get('workerDirectory'):
        worker=Path(config['workerDirectory']).resolve(); release=store.setting('currentRelease')
        request_id='audit-'+digest(release or 'unpublished')[:24]
        request={'id':request_id,'releaseId':release,'siteUrl':data['siteUrl'],'requiredChecks':['http','search','prices','mobile','links','media'],'budgetSeconds':240}
        receipt_path=worker/'receipts'/f'{request_id}.json'
        if receipt_path.exists():
            from .common import read_json
            receipt=read_json(receipt_path)
            if receipt.get('id')!=request_id or receipt.get('releaseId')!=release:
                browser={'state':'FAIL','reason':'Audit receipt identity/release mismatch'}
            elif not all(key in receipt.get('checks',{}) for key in request['requiredChecks']):
                browser={'state':'FAIL','reason':'Audit receipt lacks required checks'}
            else:
                browser={'state':'PASS' if all(value=='PASS' for value in receipt['checks'].values()) else 'FAIL','checks':receipt['checks'],'checkedAt':receipt.get('checkedAt'),'evidence':'configured fixed audit worker'}
        else:
            from .common import atomic_json
            atomic_json(worker/'requests'/f'{request_id}.json',request)
            browser={'state':'QUEUED','id':request_id,'reason':'Awaiting real browser/media audit receipt'}
        with store.db: store.db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',(request_id,'site-audit',now(),dumps(request),browser['state']))
    summary={'state':'PASS' if not findings and runtime['state']=='PASS' and browser['state']=='PASS' else 'ACTION_REQUIRED','findings':findings,
             'schema':'PASS','scope':'Data checks plus explicitly configured HTTP/browser adapters','contentCount':len(data['content']),
             'runtimeChecks':runtime['state'],'httpAudit':runtime,'mobileAndPlayback':browser['state'],'browserAudit':browser,'visitorEffect':'UNAVAILABLE'}
    with store.db: store.set_setting('lastAudit',summary)
    return summary


def choose_improvement(store,runner_configured=False,remaining_seconds=1800):
    candidates=[]
    for row in store.rows("SELECT * FROM questions WHERE state NOT IN ('CLOSED')"):
        payload=json.loads(row['payload']); evidence=int(payload.get('evidenceStrength',1)); effort=int(payload.get('effort',2))
        attempts=store.rows("SELECT * FROM improvement_changes WHERE problem_key=? AND state IN ('FAILED','CLOSED','OBSERVING') ORDER BY at DESC",(row['problem_key'],))
        if attempts and attempts[0]['state']=='FAILED' and attempts[0]['evidence_hash']==row['evidence_hash']: continue
        if len(attempts)>=2: continue
        if attempts and attempts[0]['state'] in ('CLOSED','OBSERVING') and parse_time(attempts[0]['at'])>parse_time(now())-timedelta(days=14) and payload.get('priorityClass',3)!=1: continue
        if evidence<2 or effort>=3 or not all(payload.get(key) for key in ('target','evidence','proposedChange','verification')): continue
        age=min((parse_time(now())-parse_time(row['first_seen'])).days//7,2)
        score=3*min(int(payload.get('impact',1)),3)+2*min(evidence,3)+min(int(payload.get('recurrence',0)),2)+age-effort
        candidates.append((int(payload.get('priorityClass',3)),-score,row['first_seen'],row,payload))
    if not candidates: return {'state':'NO_ACTION','reason':'No evidence-complete eligible problem bundle'}
    candidates.sort(key=lambda item:item[:3]); _,score,_,row,payload=candidates[0]
    state='READY' if runner_configured and remaining_seconds>=15*60 else 'BLOCKED_CONFIG'
    result={'state':state,'questionId':row['id'],'problemKey':row['problem_key'],'evidenceHash':row['evidence_hash'],'priorityScore':-score,
            'visitorEffect':'UNMEASURED','reason':'Configured isolated runner and validation are required' if state!='READY' else 'Evidence-backed candidate',**payload}
    with store.db:
        store.db.execute('UPDATE questions SET state=? WHERE id=?',(state,row['id']))
    return result


def reserve_cost(store,category,maximum,currency):
    config=store.setting('paidBudget',{})
    if not all(config.get(key) is not None for key in ('provider','currency','daily','monthly','perRequest')): return {'state':'BLOCKED_CONFIG','reason':'Paid budget is not configured'}
    if isinstance(maximum,bool) or not isinstance(maximum,(int,float)) or not math.isfinite(maximum) or maximum<0: raise ValueError('invalid reservation amount')
    if currency!=config['currency'] or maximum>config['perRequest']: return {'state':'BLOCKED_BUDGET'}
    with store.transaction():
        if store.db.execute("SELECT 1 FROM costs WHERE state='UNKNOWN' LIMIT 1").fetchone(): return {'state':'BLOCKED_USAGE_UNKNOWN'}
        month=now()[:7]; day=now()[:10]
        month_total=store.db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM costs WHERE at LIKE ?",(month+'%',)).fetchone()[0]
        day_total=store.db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM costs WHERE at LIKE ?",(day+'%',)).fetchone()[0]
        if day_total+maximum>config['daily'] or month_total+maximum>config['monthly']: return {'state':'BLOCKED_BUDGET'}
        id=str(uuid.uuid4()); store.db.execute('INSERT INTO costs VALUES(?,?,?,?,?,?,?)',(id,category,'RESERVED',maximum,None,currency,now()))
    return {'state':'RESERVED','id':id}


def settle_cost(store,id,actual):
    if actual is not None and (not isinstance(actual,(int,float)) or not math.isfinite(actual) or actual<0): raise ValueError('invalid actual cost')
    with store.db: store.db.execute('UPDATE costs SET actual=?,state=? WHERE id=?',(actual,'SETTLED' if actual is not None else 'UNKNOWN',id))


def import_showcase(store,payload):
    from .validation import validate_site
    from .publication import snapshot
    required=('id','title','type','url','description','provenance','rights','creator')
    if any(not payload.get(key) for key in required): raise ValueError('showcase metadata is incomplete')
    if payload.get('rightsConfirmed') is not True: raise ValueError('publication rights must be confirmed')
    if payload['provenance']=='creator-reported' and not payload.get('sourceUrl'): raise ValueError('creator report requires a source URL')
    if payload.get('sourceUrl'): safe_url(payload['sourceUrl'])
    file_hash=None
    if payload['url'].startswith('/media/'):
        path=inside(store.local/'media',payload['url'][len('/media/'):])
        if not path.is_file(): raise ValueError('media file is missing')
        file_hash=digest(path.read_bytes())
        if payload.get('sha256')!=file_hash: raise ValueError('media hash mismatch')
        if path.stat().st_size==0: raise ValueError('media file is empty')
        payload['file']=str(path.relative_to(store.root))
        # Use ffprobe configured by the operator for actual decoding, never trust declared MIME alone.
        import subprocess
        probe=shutil.which('ffprobe')
        if not probe: raise ValueError('ffprobe is required to verify local image/video decoding')
        run=subprocess.run([probe,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=20)
        if run.returncode: raise ValueError('media decoding failed')
        metadata=json.loads(run.stdout); streams=metadata.get('streams',[])
        video=next((stream for stream in streams if stream.get('codec_type')=='video'),None)
        if not video or not video.get('width') or not video.get('height'): raise ValueError('no decodable visual stream')
        if payload['type']=='video' and float(metadata.get('format',{}).get('duration',0))<=0: raise ValueError('video duration unavailable')
        payload['metadata']={**payload.get('metadata',{}),'width':str(video['width']),'height':str(video['height']),'sha256':file_hash}
    else:
        safe_url(payload['url'])
        if payload.get('remoteVerified') is not True: raise ValueError('remote media requires explicit verification and rights evidence')
    if payload['provenance']=='verified-local-run':
        receipt=payload.get('runEvidence',{})
        if not all(receipt.get(key) for key in ('jobId','attemptId','deviceIds','workflowHash','completionLogHash','modelHash')): raise ValueError('local run evidence incomplete')
        row=store.db.execute("SELECT payload FROM generation_jobs WHERE id=? AND state='COMPLETED'",(receipt['jobId'],)).fetchone()
        if not row: raise ValueError('completed generation job does not exist')
        job=json.loads(row[0])
        if job.get('attemptId')!=receipt['attemptId'] or job.get('outputHash')!=file_hash: raise ValueError('job/output evidence mismatch')
    public={key:value for key,value in payload.items() if key in ('id','title','type','url','poster','description','provenance','model','tool','gpuCount','createdAt','sourceUrl','rights','metadata')}
    public['metadata']={**public.get('metadata',{}),'creator':payload['creator']}
    data=snapshot(store); data['showcase']=[item for item in data['showcase'] if item['id']!=public['id']]+[public]; validate_site(data)
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO media_assets VALUES(?,?,?,?,0)',(public['id'],dumps(payload),file_hash,payload['rights']))
        store.db.execute('INSERT OR REPLACE INTO showcase_items VALUES(?,?,1)',(public['id'],dumps(public)))
    return {'state':'IMPORTED','id':public['id'],'provenance':public['provenance']}


def revoke_showcase(store,id):
    with store.db:
        store.db.execute('UPDATE media_assets SET revoked=1 WHERE id=?',(id,))
        store.db.execute('UPDATE showcase_items SET visible=0 WHERE id=?',(id,))
    from .publication import export
    release=export(store)
    return {'state':'REVOKED','id':id,'release':release,'originFilesPreserved':True,'externalCachePurge':'REQUIRES_CONFIGURED_HOST'}
