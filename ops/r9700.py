"""python -m ops.r9700 COMMAND --root ROOT. stdout is one JSON value."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import uuid
from pathlib import Path

from .common import current_slot,dumps,next_slot,now,read_json,redact
from .store import Store


def init(store):
    from .collect import configure_public_feeds,configure_hn_search
    from .validation import validate_site
    registry=read_json(store.root/'sources.json'); count=store.register_sources(registry)
    seed=read_json(store.root/'data/site-data.json'); validate_site(seed)
    if not store.setting('initialized'):
        with store.db:
            for item in seed['content']:
                collected=item.get('evidenceStatus','').startswith('source-metadata')
                source=next((s for s in registry['sources'] if s['url']==item['sourceUrl'] or (collected and s['name']==item['sourceName'])),None)
                store.content(item,source['id'] if source else None,source.get('publisherKey') if source else None,
                              canonical_url=item['sourceUrl'] if collected else seed['siteUrl']+'/content/'+item['slug'])
            for table,key in [('products','products'),('compatibility_records','compatibility'),('showcase_items','showcase')]:
                for item in seed[key]:
                    columns='(id,payload)'
                    store.db.execute(f'INSERT OR IGNORE INTO {table}{columns} VALUES(?,?)',(item['id'],dumps(item)))
            for item in seed['prices']: store.observation(item)
            store.set_setting('siteUrl',seed['siteUrl']); store.set_setting('initialized',now())
        configure_public_feeds(store)
        from .workflows import question
        for text,environment,answer_ids in [
            ('구매 전에 제품과 유통 조건을 어떻게 확인하나요?','KR',['product-checklist','price-reading']),
            ('Windows와 Linux의 ROCm 설치 조건은 어디서 확인하나요?','Windows/Linux',['rocm-environment']),
            ('모델 실행 오류를 어떻게 재현해 공유하나요?','ROCm',['troubleshooting-record']),
            ('실제 R9700 작품의 제작 환경과 권한을 확인할 수 있나요?','image/video',[])]:
            question(store,{'question':text,'environment':environment,'signalOrigin':'editorial-seed','answerIds':answer_ids})
    # Registry refresh must not silently revert the runtime discovery adapter.
    # This upgrade preserves configured enablement and completed checkpoints.
    configure_hn_search(store)
    from .publication import export
    defaults=store.root/'data/operator-defaults.json'
    operator_file=store.local/'operator-config.json'
    if defaults.exists() and not operator_file.exists():
        from .common import atomic_json
        atomic_json(operator_file,read_json(defaults))
    local_config(store)
    return {'state':'INITIALIZED','sourceCount':count,'configuredCollectors':len(store.rows('SELECT id FROM sources WHERE enabled=1')),'release':export(store)}


def status(store):
    def sanitized(value):
        if isinstance(value,dict):
            return {key:('[REDACTED]' if any(secret in key.lower() for secret in ('token','secret','password','apikey','credential')) else sanitized(item)) for key,item in value.items()}
        if isinstance(value,list): return [sanitized(item) for item in value]
        return value
    def expanded(table,limit=100):
        result=[]
        for row in store.rows(f'SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?',(limit,)):
            payload=json.loads(row.pop('payload','{}')); result.append(sanitized({**payload,**row}))
        return result
    sources=[]
    for row in store.rows('SELECT * FROM sources ORDER BY id'):
        source=json.loads(row.pop('payload')); row['name']=source['name']; row['category']=source['category']; row['adapter']=source.get('adapter')
        row['automationVerified']=bool(row.pop('automation_verified')); row['enabled']=bool(row['enabled']); sources.append(row)
    summary={'sourceCount':len(sources),'activeSources':sum(s['automationVerified'] for s in sources),'configuredCollectors':sum(s['enabled'] for s in sources),
       'contentCount':store.db.execute('SELECT COUNT(*) FROM content_items WHERE visible=1').fetchone()[0],
       'priceCount':store.db.execute('SELECT COUNT(*) FROM price_observations').fetchone()[0],
       'nextRunAt':next_slot(),'currentRelease':store.setting('currentRelease'),'lastAudit':store.setting('lastAudit'),
       'paidCalls':'BLOCKED_CONFIG' if not store.setting('paidBudget') else 'CONFIGURED',
       'gpu':'DEFERRED' if not store.setting('gpu',{}).get('enabled') else 'CONFIGURED',
       'improvement':'BLOCKED_CONFIG' if not store.setting('improvement') else 'CONFIGURED',
       'promotion':'DRAFT' if not store.setting('promotion') else 'CONFIGURED',
       'promotionDeliveryPaused':bool(store.setting('promotionDeliveryPaused',False)),
       'externalMonitoring':'BLOCKED_CONFIG','offHostBackup':'BLOCKED_CONFIG','publicDeployment':'NOT_VERIFIED'}
    return {'runs':expanded('operation_runs'),'sources':sources,'questions':expanded('questions'),
       'improvements':expanded('improvement_changes'),'promotions':expanded('promotion_posts'),
       'generationJobs':expanded('generation_jobs'),'jobs':expanded('jobs'),'costs':store.rows('SELECT * FROM costs ORDER BY at DESC LIMIT 100'),
       'sourceAttempts':store.rows('SELECT * FROM source_attempts ORDER BY at DESC LIMIT 100'),
       'config':{'siteUrl':store.setting('siteUrl'),'timezone':'Asia/Seoul','slots':['00:00','06:00','12:00','18:00'],
                 'paidBudgetConfigured':bool(store.setting('paidBudget')),'gpuConfigured':bool(store.setting('gpu')),
                 'promotionConfigured':bool(store.setting('promotion')),'improvementConfigured':bool(store.setting('improvement'))},'summary':summary}


def configure(store,payload):
    # No credentials, commands, directories, executable paths, or activation bypasses through web JSON.
    allowed={'siteUrl','sourceEnabled','promotionDeliveryPaused'}
    if set(payload)-allowed: raise ValueError('unsupported configuration key; privileged adapters require local operator configuration')
    from .security import safe_url
    with store.db:
        if 'siteUrl' in payload:
            store.set_setting('siteUrl',safe_url(payload['siteUrl']).rstrip('/'))
        if 'promotionDeliveryPaused' in payload:
            if not isinstance(payload['promotionDeliveryPaused'],bool): raise ValueError('paused must be boolean')
            store.set_setting('promotionDeliveryPaused',payload['promotionDeliveryPaused'])
        for id,enabled in payload.get('sourceEnabled',{}).items():
            if not isinstance(enabled,bool): raise ValueError('enabled must be boolean')
            row=store.db.execute('SELECT policy FROM sources WHERE id=?',(id,)).fetchone()
            if not row or (enabled and not row['policy']): raise ValueError('source needs verified read-only adapter policy')
            store.db.execute('UPDATE sources SET enabled=? WHERE id=?',(int(enabled),id))
    return {'state':'CONFIGURED','updated':list(payload)}


def local_config(store):
    from .collect import configure_hn_search
    configure_hn_search(store)
    file=store.local/'operator-config.json'
    if not file.exists(): return
    config=read_json(file)
    if set(config)-{'priceAdapters','paidBudget','gpu','promotion','improvement','audit'}: raise ValueError('unknown local operator configuration')
    from .security import safe_url
    with store.db:
        for key,value in config.items():
            if key=='improvement' and value.get('baselineRelease') and not store.setting('currentCodeRelease'):
                import re
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',value['baselineRelease']): raise ValueError('invalid known baseline code release')
                store.set_setting('currentCodeRelease',value['baselineRelease'])
            if key=='priceAdapters':
                for adapter in value:
                    safe_url(adapter['sourceUrl'])
                    if adapter.get('policyConfirmed') is not True or not adapter.get('policyEvidence'): raise ValueError('price policy evidence required')
                    source=store.db.execute('SELECT url FROM sources WHERE id=?',(adapter['sourceId'],)).fetchone()
                    if not source or source['url']!=adapter['sourceUrl']: raise ValueError('price endpoint must match registered source')
                    store.db.execute("UPDATE sources SET enabled=CASE WHEN policy IS NULL THEN 1 ELSE enabled END,state=CASE WHEN policy IS NULL THEN 'READY' ELSE state END,policy=? WHERE id=?",(dumps({'policyEvidence':adapter['policyEvidence'],'checkedAt':now()}),adapter['sourceId']))
            store.set_setting(key,value)


def run(store,dry_run=False,slot=None):
    from .collect import collect
    from .publication import export,backup
    from .workflows import audit,choose_improvement
    from .integrations import generation,promote,improve
    if dry_run: return {'state':'DRY_RUN','collection':collect(store,dry_run=True),'stages':['collect','export','audit','improve','generation','promote','backup']}
    run_id='run-'+str(uuid.uuid4()); started=time.monotonic()
    if not store.acquire('main',run_id): return {'state':'LOCKED','reason':'A live pipeline owns the lock'}
    stop=threading.Event()
    def beat():
        while not stop.wait(30):
            heartbeat_store=Store(store.root)
            try: heartbeat_store.heartbeat(run_id)
            finally: heartbeat_store.close()
    thread=threading.Thread(target=beat,daemon=True)
    try:
        if slot and store.db.execute('SELECT 1 FROM operation_runs WHERE slot=?',(slot,)).fetchone(): return {'state':'ALREADY_RUN','slot':slot}
        with store.db: store.db.execute('INSERT INTO operation_runs VALUES(?,?,?,?,?,?,?,?,?)',(run_id,slot,'main','RUNNING',now(),None,now(),os.getpid(),'{}'))
        thread.start()
        result={'id':run_id,'collection':collect(store,event_id=run_id,budget_seconds=480)}
        result['audit']=audit(store)
        result['improvement']=improve(store,{}) if time.monotonic()-started<900 else {'state':'DEFERRED_TIME_BUDGET'}
        if not store.setting('improvement'): result['improvementIntegration']='BLOCKED_CONFIG'
        result['generation']=generation(store,'poll',{})
        result['promotion']=promote(store)
        state='PARTIAL_FAILURE' if result['collection']['failed'] else ('BACKLOG' if result['collection']['backlog'] else 'SUCCESS')
        result['state']=state; result['elapsedSeconds']=round(time.monotonic()-started,3)
        with store.db: store.db.execute('UPDATE operation_runs SET state=?,finished_at=?,payload=? WHERE id=?',(state,now(),dumps(result),run_id))
        result['release']=export(store)
        result['backup']=backup(store)
        with store.db: store.db.execute('UPDATE operation_runs SET payload=? WHERE id=?',(dumps(result),run_id))
        return result
    except Exception as error:
        with store.db: store.db.execute('UPDATE operation_runs SET state=?,finished_at=?,payload=? WHERE id=?',('FAILED',now(),dumps({'error':redact(str(error))}),run_id))
        raise
    finally:
        stop.set()
        if thread.is_alive(): thread.join(timeout=1)
        store.release('main',run_id)


def tick(store):
    from .collect import collect
    from .publication import export
    slot=current_slot(); main=None
    if not store.db.execute('SELECT 1 FROM operation_runs WHERE slot=?',(slot,)).fetchone(): main=run(store,slot=slot)
    retries=[]
    for job in store.rows("SELECT * FROM jobs WHERE kind='source-retry' AND state='WAITING' AND due_at<=?",(now(),)):
        payload=json.loads(job['payload'])
        retries.append(collect(store,source_id=payload['sourceId'],event_id=payload['eventId'],budget_seconds=120))
    if retries: export(store)
    return {'state':'TICK','slot':slot,'main':main,'retries':retries,'nextRunAt':next_slot()}


def parser():
    result=argparse.ArgumentParser(description=__doc__)
    result.add_argument('command',choices=['init','collect','run','status','export','audit','promote','questions','showcase-import','showcase-revoke',
       'submit','feedback','configure','backup','restore','rollback','generation','improve','tick','schedule','price-correct'])
    result.add_argument('--root',type=Path,default=Path.cwd()); result.add_argument('--dry-run',action='store_true')
    result.add_argument('--payload-json'); result.add_argument('--input',type=Path); result.add_argument('--output',type=Path)
    result.add_argument('--source-id'); result.add_argument('--release-id'); result.add_argument('--id'); result.add_argument('--action',default='poll')
    return result


def main(argv=None):
    args=parser().parse_args(argv)
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    store=None
    try:
        payload=json.loads(args.payload_json) if args.payload_json else (read_json(args.input) if args.input and args.command not in ('restore',) else {})
        if not isinstance(payload,dict): raise ValueError('payload must be an object')
        if args.command=='restore':
            from .publication import restore
            value=restore(args.root,args.input)
        else:
            store=Store(args.root)
            if args.command not in ('init','status','configure'): local_config(store)
            if args.command=='init': value=init(store) if not args.dry_run else {'state':'DRY_RUN'}
            elif args.command=='status': value=status(store)
            elif args.command=='configure': value=configure(store,payload)
            elif args.command=='run': value=run(store,args.dry_run)
            elif args.command=='collect':
                from .collect import collect
                value=collect(store,args.source_id,dry_run=args.dry_run)
            elif args.command=='export':
                from .publication import export
                value=export(store,args.dry_run)
            elif args.command=='rollback':
                from .publication import rollback
                value=rollback(store,args.release_id)
            elif args.command=='backup':
                from .publication import backup
                value=backup(store,args.output)
            elif args.command=='audit':
                from .workflows import audit
                value=audit(store)
            elif args.command=='questions':
                from .workflows import question
                value=question(store,payload) if payload else status(store)['questions']
            elif args.command=='submit':
                from .workflows import submit
                value=submit(store,payload)
            elif args.command=='feedback':
                from .workflows import feedback
                value=feedback(store,payload)
            elif args.command=='showcase-import':
                from .workflows import import_showcase
                value=import_showcase(store,payload)
            elif args.command=='showcase-revoke':
                from .workflows import revoke_showcase
                value=revoke_showcase(store,args.id)
            elif args.command=='promote':
                from .integrations import promote
                value=promote(store,dry_run=args.dry_run)
            elif args.command=='generation':
                from .integrations import generation
                value=generation(store,args.action,payload)
            elif args.command=='improve':
                from .integrations import improve
                value=improve(store,payload)
            elif args.command=='price-correct': value={'id':store.correction(args.id,payload.get('replacement'),payload['reason']),'state':'CORRECTED'}
            elif args.command=='tick': value=tick(store)
            elif args.command=='schedule':
                stopping=threading.Event()
                signal.signal(signal.SIGTERM,lambda *_:stopping.set())
                signal.signal(signal.SIGINT,lambda *_:stopping.set())
                while not stopping.is_set():
                    print(dumps(tick(store)),flush=True)
                    stopping.wait(30)
                value={'state':'STOPPED'}
        print(dumps(value))
        return 0
    except Exception as error:
        value={'state':'ERROR','error':redact(str(error)),'type':type(error).__name__}
        print(dumps(value)); print(dumps(value),file=sys.stderr)
        return 1
    finally:
        if store: store.close()


if __name__=='__main__': raise SystemExit(main())
