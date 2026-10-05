from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from .common import atomic_json,digest,inside,next_slot,now,parse_time,read_json
from .validation import validate_site


def snapshot(store):
    def payloads(table,where=''):
        return [json.loads(row['payload']) for row in store.rows(f'SELECT payload FROM {table} {where}')]
    prices=[]
    for row in store.rows('SELECT * FROM price_observations ORDER BY observed_at'):
        correction=store.db.execute('SELECT replacement FROM price_corrections WHERE observation_id=? ORDER BY rowid DESC LIMIT 1',(row['id'],)).fetchone()
        if correction and correction[0] is None: continue
        price=json.loads(correction[0] if correction else row['payload'])
        price['stale']=(parse_time(now())-parse_time(price['observedAt'])).total_seconds()>12*3600
        prices.append(price)
    sources=[]
    for row in store.rows('SELECT * FROM sources ORDER BY id'):
        source=json.loads(row['payload'])
        sources.append({'id':source['id'],'name':source['name'],'url':source['url'],'category':source['category'],
                        'status':row['state'],'resourceKind':source.get('resourceKind'),'automationVerified':bool(row['automation_verified'])})
    last=store.db.execute("SELECT * FROM operation_runs WHERE kind='main' ORDER BY started_at DESC LIMIT 1").fetchone()
    success=store.db.execute("SELECT finished_at FROM operation_runs WHERE kind='main' AND state IN ('SUCCESS','NO_ACTION') ORDER BY started_at DESC LIMIT 1").fetchone()
    data={'schemaVersion':1,'releaseId':'pending','generatedAt':now(),'siteUrl':store.setting('siteUrl','https://r9700.jjgo.io'),
          'content':payloads('content_items','WHERE visible=1 ORDER BY first_seen DESC'),
          'products':payloads('products'),'prices':prices,'compatibility':payloads('compatibility_records'),
          'showcase':payloads('showcase_items','WHERE visible=1'),'sources':sources,
          'operations':{'lastRunAt':last['started_at'] if last else None,'lastSuccessAt':success[0] if success else None,
            'nextRunAt':next_slot(),'activeSources':sum(bool(r['automationVerified']) for r in sources),'sourceCount':len(sources),
            'state':last['state'] if last else 'INITIALIZED','notices':[]}}
    if not data['showcase']: data['operations']['notices'].append('실제 R9700 이미지·영상 제공은 자료 대기 상태입니다.')
    if not data['prices']: data['operations']['notices'].append('실제 가격 관측이 없습니다. 가격·재고 연결을 확인하세요.')
    if any(s['status'] in ('FAILED','BLOCKED_ACCESS','BACKLOG') for s in sources):
        data['operations']['notices'].append('일부 출처의 접근 실패 또는 수집 잔여 작업이 있습니다.')
    data['releaseId']='release-'+digest(data)[:24]
    validate_site(data)
    return data


def export(store,dry_run=False):
    data=snapshot(store)
    if dry_run: return {'state':'DRY_RUN','releaseId':data['releaseId'],'validation':validate_site(data)}
    release=store.local/'releases'/data['releaseId']
    release.mkdir(parents=True,exist_ok=True)
    atomic_json(release/'site-data.json',data)
    manifest={'releaseId':data['releaseId'],'schemaVersion':1,'hash':digest((release/'site-data.json').read_bytes()),
              'generatedAt':data['generatedAt'],'artifacts':['site-data.json'],
              'derivedViews':'Web search/RSS/sitemap consume the same snapshot release.'}
    atomic_json(release/'manifest.json',manifest)
    # A single replace is the commit point; readers see either complete snapshot.
    atomic_json(store.local/'public/site-data.json',data)
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO releases VALUES(?,?,?,?)',(data['releaseId'],now(),manifest['hash'],str(release)))
        store.set_setting('currentRelease',data['releaseId'])
        store.db.execute('UPDATE sources SET published_revision=? WHERE last_success IS NOT NULL',(data['releaseId'],))
    return {'state':'PUBLISHED','releaseId':data['releaseId'],'hash':manifest['hash'],'path':str(store.local/'public/site-data.json')}


def rollback(store,release_id):
    row=store.db.execute('SELECT * FROM releases WHERE id=?',(release_id,)).fetchone()
    if not row: raise ValueError('unknown release')
    release=inside(store.local/'releases',row['path'])
    data=read_json(release/'site-data.json'); validate_site(data)
    if digest((release/'site-data.json').read_bytes())!=row['hash']: raise ValueError('release hash mismatch')
    atomic_json(store.local/'public/site-data.json',data)
    with store.db: store.set_setting('currentRelease',release_id)
    return {'state':'ROLLED_BACK','releaseId':release_id,'operationalDatabasePreserved':True}


def backup(store,output=None):
    started=time.monotonic()
    destination=Path(output).resolve() if output else store.local/'backups'/('backup-'+now().replace(':','-')+'-'+uuid.uuid4().hex[:6])
    destination.mkdir(parents=True,exist_ok=False)
    target=sqlite3.connect(destination/'operations.sqlite3')
    try:
        store.db.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('backup integrity failure')
    finally: target.close()
    manifest={'createdAt':now(),'databaseHash':digest((destination/'operations.sqlite3').read_bytes()),'media':[],
              'sources':{},'counts':{},'offHostVerified':False,'elapsedSeconds':0}
    for table in ('content_items','revisions','price_observations','price_corrections','promotion_posts','generation_jobs'):
        manifest['counts'][table]=store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    for row in store.rows('SELECT * FROM media_assets'):
        item=json.loads(row['payload']); manifest['media'].append({'id':row['id'],'hash':row['hash'],'path':item.get('file'),'revoked':bool(row['revoked'])})
    for name in ('sources.json','data/site-data.json','data/operator-defaults.json','package.json','package-lock.json','INTEGRATION.md','astro.config.mjs','tsconfig.json','Dockerfile','compose.yaml','.dockerignore'):
        file=store.root/name
        if file.is_file():
            path=destination/'source'/name; path.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(file,path)
            manifest['sources'][name]=digest(file.read_bytes())
    for folder in ('ops','src','tests','tests-web','workers','public'):
        if not (store.root/folder).exists(): continue
        for file in (store.root/folder).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and not file.name.startswith('.env'):
                name=file.relative_to(store.root).as_posix(); path=destination/'source'/name
                path.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(file,path); manifest['sources'][name]=digest(file.read_bytes())
    manifest['elapsedSeconds']=round(time.monotonic()-started,3)
    atomic_json(destination/'manifest.json',manifest)
    return {'state':'BACKED_UP','path':str(destination),'integrity':'ok','mediaCopied':False,'offHostVerified':False,'elapsedSeconds':manifest['elapsedSeconds']}


def restore(root,input_path):
    """Disaster restore only into a new location; never rewind the live operational DB."""
    root=Path(root).resolve(); source=Path(input_path).resolve(); manifest=read_json(source/'manifest.json')
    local=root/'.local'
    if (local/'operations.sqlite3').exists(): raise ValueError('restore requires a destination with no existing operational database')
    if digest((source/'operations.sqlite3').read_bytes())!=manifest['databaseHash']: raise ValueError('backup hash mismatch')
    local.mkdir(parents=True,exist_ok=True)
    for name,expected in manifest['sources'].items():
        file=inside(source/'source',name)
        if digest(file.read_bytes())!=expected: raise ValueError('source manifest hash mismatch')
        target=inside(root,name)
        if target.exists() and digest(target.read_bytes())!=expected: raise ValueError('restore would overwrite a different source file')
    for name in manifest['sources']:
        target=inside(root,name); target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(inside(source/'source',name),target)
    shutil.copy2(source/'operations.sqlite3',local/'operations.sqlite3')
    from .store import Store
    store=Store(root)
    try:
        if store.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('restored integrity failure')
        for table,count in manifest['counts'].items():
            if table not in ('content_items','revisions','price_observations','price_corrections','promotion_posts','generation_jobs'): raise ValueError('invalid manifest table')
            if store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]!=count: raise ValueError('restored count mismatch')
        with store.db:
            store.set_setting('promotionDeliveryPaused',True)
            store.db.execute('DELETE FROM locks')
            store.db.execute("UPDATE operation_runs SET state='INTERRUPTED' WHERE state='RUNNING'")
        missing=[]
        for item in manifest['media']:
            if not item['path']: continue
            file=inside(root,item['path'])
            if not file.is_file() or digest(file.read_bytes())!=item['hash']: missing.append(item['id'])
        # Missing media must never become a public broken artifact after restore.
        with store.db:
            for media_id in missing: store.db.execute('UPDATE showcase_items SET visible=0 WHERE id=?',(media_id,))
        release=export(store)
        return {'state':'RESTORED','integrity':'ok','counts':manifest['counts'],'missingMedia':missing,
                'promotionDeliveryPaused':True,'release':release,'sourceBundle':str(source/'source'),'webRebuild':'NOT_RUN'}
    finally: store.close()
