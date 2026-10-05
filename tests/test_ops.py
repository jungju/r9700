"""Fixed controller acceptance tests. Fixtures never enter the public seed."""
import copy
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from ops.collect import as_content,collect,configure_public_feeds,date_or_none,parse_feed,retry_due,structured_price
from ops.common import atomic_json,digest,dumps,next_slot,now,parse_time,read_json
from ops.integrations import FakePromotionAdapter,generation,improve,promote,verify_changes
from ops.publication import backup,export,restore,rollback,snapshot
from ops.r9700 import configure,init,status,tick
from ops.security import FetchError,Response,SafeClient,plain_text,public_addresses,relevant,safe_url
from ops.store import Store
from ops.validation import validate_price,validate_site
from ops.workflows import audit,choose_improvement,feedback,import_showcase,question,reserve_cost,settle_cost,submit

ROOT=Path(__file__).resolve().parents[1]


class OpsCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        shutil.copy2(ROOT/'sources.json',self.root/'sources.json')
        (self.root/'data').mkdir()
        seed=read_json(ROOT/'data/site-data.json'); seed['prices']=[]
        atomic_json(self.root/'data/site-data.json',seed)
        self.store=Store(self.root); init(self.store)
    def tearDown(self):
        self.store.close(); self.tmp.cleanup()
    def price(self,event='event-1',price=1000,**kwargs):
        value={'id':'price-'+event,'offerId':'offer-fixture','productId':'asus-r9700','seller':'Fixture retailer',
               'region':'US','currency':'USD','price':price,'shipping':None,'condition':'new / one card / tax unknown',
               'stock':'in_stock','observedAt':now(),'sourceUrl':'https://example.com/product','collectionEventId':event}
        return {**value,**kwargs}
    def add_price(self,**kwargs):
        with self.store.db: return self.store.observation(self.price(**kwargs))

    def test_A01_registry_validation_and_truthful_activation(self):
        data=read_json(self.root/'sources.json'); count=len(data['sources'])
        self.assertEqual(len(status(self.store)['sources']),count)
        self.assertEqual(status(self.store)['summary']['activeSources'],0)
        self.assertLess(status(self.store)['summary']['configuredCollectors'],count)
        data['sources'].append(copy.deepcopy(data['sources'][0]))
        with self.assertRaises(ValueError): self.store.register_sources(data)
        with self.assertRaises(ValueError): configure(self.store,{'sourceEnabled':{'src-073':True}})

    def test_A02_same_content_revision_idempotence_and_shared_origin(self):
        item=as_content({'title':'R9700 test','url':'https://example.com/article','publishedAt':None,'evidence':'32 GB'}, {'name':'Fixture'})
        with self.store.db:
            self.assertEqual(self.store.content(item,'src-003','publisher'),'new')
            self.assertEqual(self.store.content(item,'src-003','publisher'),'duplicate')
            revised={**item,'title':'R9700 corrected title'}
            self.assertEqual(self.store.content(revised,'src-003','publisher'),'revised')
            self.assertEqual(self.store.content(revised,'src-004','publisher'),'duplicate')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM revisions WHERE entity_id=?',(item['id'],)).fetchone()[0],2)

    def test_A03_old_discovery_and_coverage_gap(self):
        body=b'<rss><channel><item><title>R9700 old newly discovered</title><link>https://example.com/old</link><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item></channel></rss>'
        class Client:
            def get(self,*args,**kwargs): return Response(200,args[0],{},body)
        result=collect(self.store,'src-003',event_id='old',client=Client())
        self.assertEqual(result['new'],1)
        self.assertTrue(result['sources'][0]['coverageGap'])
        repeated=collect(self.store,'src-003',event_id='new-event',client=Client())
        self.assertEqual(repeated['duplicate'],1)

    def test_A04_retry_after_and_checkpoint_preservation(self):
        with self.store.db: self.store.db.execute("UPDATE sources SET checkpoint='previous' WHERE id='src-003'")
        class Client:
            def get(self,*args,**kwargs): raise FetchError('HTTP 429',429,{'retry-after':'7200'})
        result=collect(self.store,'src-003',event_id='failure',client=Client())
        self.assertEqual(result['failed'],1)
        row=self.store.rows("SELECT * FROM sources WHERE id='src-003'")[0]
        self.assertEqual(row['checkpoint'],'previous')
        self.assertGreaterEqual((parse_time(row['retry_at'])-parse_time(row['last_attempt'])).total_seconds(),7200)
        self.assertEqual(collect(self.store,'src-003',client=Client())['sources'][0]['state'],'RETRY_WAIT')
        self.assertEqual(len(self.store.rows("SELECT * FROM jobs WHERE kind='source-retry'")),1)

    def test_A04_access_block_does_not_reschedule(self):
        class Client:
            def get(self,*args,**kwargs): raise FetchError('HTTP 403',403,{})
        result=collect(self.store,'src-003',client=Client())
        self.assertEqual(result['sources'][0]['state'],'BLOCKED_ACCESS')
        self.assertIsNone(result['sources'][0]['retryAt'])

    def test_A05_fixed_kst_slots_and_live_lock(self):
        for hour in (0,6,12,18):
            value=f'2026-10-05T{hour:02}:00:00+09:00'
            self.assertEqual((parse_time(next_slot(value))-parse_time(value)).total_seconds(),6*3600)
        self.assertTrue(self.store.acquire('test','a'))
        with self.store.db: self.store.db.execute("UPDATE locks SET heartbeat='2000-01-01T00:00:00+00:00' WHERE name='test'")
        self.assertFalse(self.store.acquire('test','b'))
        self.store.release('test','a'); self.assertTrue(self.store.acquire('test','b'))

    def test_A05_slot_only_once_on_repeated_tick(self):
        with patch('ops.r9700.run') as mocked:
            def fake(store,slot=None,**kwargs):
                with store.db: store.db.execute('INSERT INTO operation_runs VALUES(?,?,?,?,?,?,?,?,?)',('test-run',slot,'main','SUCCESS',now(),now(),now(),os.getpid(),'{}'))
                return {'state':'SUCCESS'}
            mocked.side_effect=fake
            tick(self.store); tick(self.store)
            self.assertEqual(mocked.call_count,1)

    def test_A06_price_events_append_and_correction_preserves_original(self):
        self.assertEqual(self.add_price(),1); self.assertEqual(self.add_price(),0); self.assertEqual(self.add_price(event='event-2'),1)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db: self.store.db.execute('DELETE FROM price_observations')
        corrected=self.price(price=900)
        self.store.correction('price-event-1',corrected,'parser corrected after source verification')
        self.assertEqual(json.loads(self.store.db.execute("SELECT payload FROM price_observations WHERE id='price-event-1'").fetchone()[0])['price'],1000)
        self.assertEqual(next(p for p in snapshot(self.store)['prices'] if p['id']=='price-event-1')['price'],900)
        self.store.correction('price-event-1',None,'source withdrawn')
        self.assertEqual(len(snapshot(self.store)['prices']),1)

    def test_A06_price_conditions_and_null_not_zero(self):
        self.add_price()
        with self.assertRaises(ValueError):
            with self.store.db: self.store.observation(self.price(event='other',currency='EUR'))
        for value in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError): validate_price(self.price(price=value))
        validate_price(self.price(price=None,stock='price_missing'))
        with self.assertRaises(ValueError): validate_price(self.price(price=5,stock='fetch_error'))

    def test_A06_structured_product_single_offer_only(self):
        config={k:self.price()[k] for k in ('offerId','productId','seller','region','currency','condition','sourceUrl')}
        data={'@type':'Product','name':'Radeon AI PRO R9700','offers':{'@type':'Offer','price':'1250.50','priceCurrency':'USD','availability':'https://schema.org/OutOfStock'}}
        html='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        actual=structured_price(html,config,'e')
        self.assertEqual(actual['price'],1250.5); self.assertEqual(actual['stock'],'out_of_stock'); self.assertIsNone(actual['shipping'])
        data['offers']['@type']='AggregateOffer'
        with self.assertRaises(ValueError): structured_price('<script type="application/ld+json">'+json.dumps(data)+'</script>',config,'e')

    def test_A07_no_unvalidated_summary_or_inferred_date(self):
        item=as_content({'title':'R9700 32GB','url':'https://example.com/item','publishedAt':None,'evidence':'Not supported on this Windows version'}, {'name':'Source'})
        self.assertIsNone(item['publishedAt']); self.assertIn('summary-pending',item['evidenceStatus'])
        self.assertNotIn('64GB',item['body']); self.assertNotIn('지원합니다',item['summary'])
        self.assertIsNone(date_or_none('unknown'))

    def test_A08_html_xml_and_url_defenses(self):
        self.assertEqual(plain_text('<script>steal()</script><p>safe</p><iframe>bad</iframe>'),'safe')
        with self.assertRaises(ValueError): parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///secret">]><rss/>')
        for url in ('http://example.com','https://localhost/a','https://127.0.0.1','https://[::1]/','https://x:secret@example.com','https://example.com:444/a','https://metadata.google.internal'):
            with self.assertRaises(ValueError,msg=url): safe_url(url)
        for address in ('127.0.0.1','10.1.2.3','169.254.169.254','::1','fe80::1','100.64.0.1'):
            with self.assertRaises(ValueError): public_addresses('example.com',lambda *a,**k:[(2,1,6,'',(address,443))])

    def test_A08_redirect_private_target_is_never_connected(self):
        connected=[]
        class Reply:
            status=302
            def getheaders(self): return [('Location','https://127.0.0.1/secret')]
        class Connection:
            def __init__(self,host,ip,timeout): connected.append(host)
            def request(self,*args,**kwargs): pass
            def getresponse(self): return Reply()
            def close(self): pass
        client=SafeClient(min_interval=0,resolver=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))],connector=Connection)
        with self.assertRaises(ValueError): client.get('https://example.com/',['example.com','127.0.0.1'])
        self.assertEqual(connected,['example.com'])

    def test_A09_protected_changes_and_line_budget(self):
        baseline=self.root/'base'; candidate=self.root/'candidate'
        for root in (baseline,candidate):
            (root/'src/styles').mkdir(parents=True); (root/'tests').mkdir()
            (root/'tests/fixed.py').write_text('assert True'); (root/'src/styles/site.css').write_text('body {margin:1px;}')
        (candidate/'src/styles/site.css').write_text('body {margin:0;}')
        self.assertEqual(verify_changes(baseline,candidate)['changedLines'],2)
        (candidate/'tests/fixed.py').write_text('pass')
        with self.assertRaises(ValueError): verify_changes(baseline,candidate)

    def test_A09_question_priority_requires_evidence_and_new_retry(self):
        payload={'question':'설치 페이지가 잘못된 링크로 이동합니다','signalOrigin':'reproduced-task-failure','evidence':'repro-1','target':'link',
                 'proposedChange':'repair documented URL','verification':'fixed URL task','priorityClass':1,'impact':3,'evidenceStrength':3,'effort':1}
        q=question(self.store,payload)
        selected=choose_improvement(self.store,True)
        self.assertEqual(selected['questionId'],q['id']); self.assertEqual(selected['state'],'READY')
        with self.store.db: self.store.db.execute('INSERT INTO improvement_changes VALUES(?,?,?,?,?,?)',('failed',selected['problemKey'],selected['evidenceHash'],'FAILED','{}',now()))
        self.assertEqual(choose_improvement(self.store,True)['state'],'NO_ACTION')
        question(self.store,{**payload,'evidence':'repro-2'})
        self.assertEqual(choose_improvement(self.store,True)['state'],'READY')

    def test_A09_configured_runner_queues_once_and_protected_candidate_fails(self):
        question(self.store,{'question':'재현한 모바일 화면 넘침을 고칠 수 있나요?','signalOrigin':'reproduced-task-failure',
                 'evidence':'mobile task failed at width 390','target':'src/styles/site.css','proposedChange':'constrain intrinsic width',
                 'verification':'same viewport task and fixed checks','priorityClass':1,'evidenceStrength':3,'effort':1})
        runner=self.root/'runner'; host=self.root/'host'
        with self.store.db: self.store.set_setting('improvement',{'runnerDirectory':str(runner),'hostExchangeDirectory':str(host),
                 'validationImage':'validator@sha256:'+'a'*64,'runnerCostMode':'free'})
        first=improve(self.store,{})
        self.assertEqual(first['state'],'RUNNING')
        second=improve(self.store,{})
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(list((runner/'requests').glob('*.json'))),1)
        candidate=self.store.local/'improvement-inbox'/'bad'; candidate.mkdir(parents=True)
        (candidate/'ops').mkdir(); (candidate/'ops/unsafe.py').write_text('print(1)')
        atomic_json(runner/'receipts'/f"{first['id']}.json",{'requestId':first['id'],'candidateId':'bad'})
        with patch('ops.integrations.subprocess.run') as execute:
            result=improve(self.store,{})
            self.assertEqual(result['state'],'FAILED'); execute.assert_not_called()

    def test_A09_host_receipt_must_match_manifest_and_pass_all_checks(self):
        host=self.root/'host'; runner=self.root/'runner'
        with self.store.db:
            self.store.set_setting('improvement',{'runnerDirectory':str(runner),'hostExchangeDirectory':str(host),
                 'validationImage':'validator@sha256:'+'a'*64,'runnerCostMode':'free'})
            self.store.db.execute('INSERT INTO improvement_changes VALUES(?,?,?,?,?,?)',('candidate','p','e','VALIDATED_AWAITING_HOST',dumps({'manifestHash':'expected','previousRelease':'old'}),now()))
        receipt={'id':'candidate','manifestHash':'wrong','state':'DEPLOYED','releaseId':'new','checks':dict.fromkeys(('http','search','prices','mobile'),'PASS')}
        atomic_json(host/'receipts/candidate.json',receipt)
        with self.assertRaises(ValueError): improve(self.store,{})
        receipt['manifestHash']='expected'; receipt['checks']['mobile']='FAIL'
        atomic_json(host/'receipts/candidate.json',receipt)
        with self.assertRaises(ValueError): improve(self.store,{})
        receipt['checks']['mobile']='PASS'; atomic_json(host/'receipts/candidate.json',receipt)
        self.assertEqual(improve(self.store,{})['state'],'DEPLOYED')

    def test_A10_snapshot_rollback_preserves_new_prices_and_ledger(self):
        first=export(self.store); self.add_price(); second=export(self.store)
        self.assertNotEqual(first['releaseId'],second['releaseId'])
        rollback(self.store,first['releaseId'])
        self.assertEqual(read_json(self.store.local/'public/site-data.json')['releaseId'],first['releaseId'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM price_observations').fetchone()[0],1)
        release=self.store.local/'releases'/second['releaseId']/'site-data.json'
        release.write_text('{}')
        with self.assertRaises(ValueError): rollback(self.store,second['releaseId'])

    def test_A11_untrusted_submission_queued_and_query_redacted(self):
        result=submit(self.store,{'type':'showcase','url':'https://example.com/art','title':'Artwork','creator':'Artist','rights':'permission claimed','notes':'<script>alert(1)</script>'})
        self.assertFalse(result['published']); self.assertEqual(snapshot(self.store)['showcase'],[])
        feedback(self.store,{'query':'ROCm token=supersecret x@y.com C:\\Users\\private','kind':'search-miss'})
        value=dumps(status(self.store)['questions'])
        self.assertNotIn('supersecret',value); self.assertNotIn('x@y.com',value)

    def test_A12_response_loss_reconcile_no_duplicate_and_cooldown(self):
        adapter=FakePromotionAdapter(lose_response=True)
        first=promote(self.store,adapter,'fake','test-account',public_check=lambda _:True)
        self.assertEqual(first['state'],'UNKNOWN'); self.assertEqual(adapter.send_count,1)
        second=promote(self.store,adapter,'fake','test-account',public_check=lambda _:True)
        self.assertEqual(second['state'],'RATE_LIMITED'); self.assertEqual(adapter.send_count,1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM promotion_posts WHERE state='SENT'").fetchone()[0],1)

    def test_A12_unconfigured_channel_only_drafts(self):
        result=promote(self.store)
        self.assertEqual(result['state'],'DRAFT'); self.assertEqual(result['externalCalls'],0)

    def test_A12_cosmetic_revision_does_not_create_new_promotion(self):
        promote(self.store)
        before=self.store.db.execute('SELECT COUNT(*) FROM promotion_posts').fetchone()[0]
        row=self.store.db.execute("SELECT * FROM content_items WHERE json_extract(payload,'$.kind')='guide' LIMIT 1").fetchone()
        item=json.loads(row['payload']); item['summary']+=' 편집 문구 다듬기.'
        with self.store.db: self.store.content(item,canonical_url=row['canonical_url'])
        self.assertEqual(self.store.db.execute('SELECT material_revision FROM content_items WHERE id=?',(row['id'],)).fetchone()[0],row['material_revision'])
        promote(self.store)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM promotion_posts').fetchone()[0],before)

    def test_A01_default_price_config_copies_once_without_overwriting_operator(self):
        defaults=read_json(ROOT/'data/operator-defaults.json')
        atomic_json(self.root/'data/operator-defaults.json',defaults)
        init(self.store)
        self.assertEqual(read_json(self.store.local/'operator-config.json'),defaults)
        atomic_json(self.store.local/'operator-config.json',{})
        init(self.store)
        self.assertEqual(read_json(self.store.local/'operator-config.json'),{})

    def test_A13_busy_or_unknown_gpu_no_probe_or_request(self):
        worker=self.root/'worker'; worker.mkdir()
        with self.store.db: self.store.set_setting('gpu',{'enabled':True,'workerDirectory':str(worker),'devices':['gpu0'],'workflows':{'safe':{}},'timeoutSeconds':60})
        result=generation(self.store,'enqueue',{'workflowId':'safe'})
        self.assertEqual(result['state'],'DEFERRED'); self.assertEqual(result['gpuProbes'],0)
        self.assertFalse((worker/'requests').exists())
        atomic_json(worker/'lease.json',{'state':'BUSY','owner':'somebody-else'})
        self.assertEqual(generation(self.store,'poll',{})['state'],'DEFERRED')

    def test_A13_owned_queue_completion_checks_attempt_and_output(self):
        worker=self.root/'gpu-worker'; worker.mkdir()
        with self.store.db: self.store.set_setting('gpu',{'enabled':True,'workerDirectory':str(worker),'devices':['gpu0'],
             'workflows':{'safe':{'modelHash':'model-sha','workflowHash':'workflow-sha'}},'timeoutSeconds':600,'minimumFreeBytes':0})
        atomic_json(worker/'lease.json',{'state':'OWNED_IDLE','owner':'r9700-hub','leaseToken':'lease-one','deviceIds':['gpu0'],
                    'expiresAt':(parse_time(now())+timedelta(hours=1)).isoformat()})
        first=generation(self.store,'enqueue',{'workflowId':'safe'})
        self.assertEqual(first['state'],'RUNNING')
        job=read_json(worker/'requests'/f"{first['jobId']}.json")
        output=self.store.local/'media/result.png'; output.write_bytes(b'partial-test-file')
        receipt={**{key:job[key] for key in ('jobId','attemptId','leaseToken','deviceIds','workflowHash','modelHash')},
                 'state':'COMPLETED','output':'result.png','outputHash':'wrong','completionLogHash':'log'}
        atomic_json(worker/'receipts'/f"{first['jobId']}.json",receipt)
        with self.assertRaises(ValueError): generation(self.store,'poll',{})
        self.assertEqual(snapshot(self.store)['showcase'],[])
        receipt['outputHash']=digest(output.read_bytes()); atomic_json(worker/'receipts'/f"{first['jobId']}.json",receipt)
        generation(self.store,'poll',{})
        self.assertEqual(self.store.db.execute('SELECT state FROM generation_jobs WHERE id=?',(first['jobId'],)).fetchone()[0],'COMPLETED')
        self.assertTrue((worker/'requests'/f"release-{first['jobId']}.json").exists())
        self.assertEqual(snapshot(self.store)['showcase'],[])  # decoding/rights still required for publication

    def test_A16_media_disk_floor_defers_owned_generation(self):
        worker=self.root/'gpu-worker'; worker.mkdir()
        with self.store.db: self.store.set_setting('gpu',{'enabled':True,'workerDirectory':str(worker),'devices':['gpu0'],
             'workflows':{'safe':{'modelHash':'model','workflowHash':'workflow'}},'timeoutSeconds':60,'minimumFreeBytes':10**30})
        atomic_json(worker/'lease.json',{'state':'OWNED_IDLE','owner':'r9700-hub','leaseToken':'one','deviceIds':['gpu0'],
                 'expiresAt':(parse_time(now())+timedelta(hours=1)).isoformat()})
        result=generation(self.store,'enqueue',{'workflowId':'safe'})
        self.assertEqual(result['state'],'DEFERRED'); self.assertIn('free-space',result['reason']); self.assertFalse((worker/'requests').exists())

    def test_A14_rights_required_and_local_provenance_cannot_be_claimed(self):
        base={'id':'art','title':'Art','type':'image','url':'https://example.com/art.png','description':'Art','provenance':'creator-reported','rights':'permission','creator':'Artist','sourceUrl':'https://example.com/post'}
        with self.assertRaises(ValueError): import_showcase(self.store,base)
        with self.assertRaises(ValueError): import_showcase(self.store,{**base,'rightsConfirmed':True,'remoteVerified':True,'provenance':'verified-local-run'})
        self.assertEqual(snapshot(self.store)['showcase'],[])

    def test_A15_relevance_excludes_other_products(self):
        for text in ('Ryzen 7 9700X launch','ATI Radeon 9700 Pro review','R9700S details','random ROCm unrelated Instinct news'):
            self.assertFalse(relevant(text))
        for text in ('Radeon AI PRO R9700 review','AMD R9700 firmware','라데온 AI 프로 R9700'):
            self.assertTrue(relevant(text))
        self.assertTrue(relevant('gfx1201 on TheRock','therock'))
        self.assertFalse(relevant('gfx1201 on unknown forum','general'))

    def test_A16_budget_reservations_hold_unknown_and_null_disables(self):
        self.assertEqual(reserve_cost(self.store,'image',1,'USD')['state'],'BLOCKED_CONFIG')
        with self.store.db: self.store.set_setting('paidBudget',{'provider':'fake','currency':'USD','daily':2,'monthly':10,'perRequest':2})
        first=reserve_cost(self.store,'image',1.5,'USD'); self.assertEqual(first['state'],'RESERVED')
        self.assertEqual(reserve_cost(self.store,'image',1,'USD')['state'],'BLOCKED_BUDGET')
        settle_cost(self.store,first['id'],None)
        self.assertEqual(reserve_cost(self.store,'image',0.1,'USD')['state'],'BLOCKED_USAGE_UNKNOWN')

    def test_A17_backup_restore_integrity_counts_and_delivery_pause(self):
        self.add_price(); result=backup(self.store,self.root/'backup')
        restored=restore(self.root/'restored',result['path'])
        self.assertEqual(restored['integrity'],'ok'); self.assertEqual(restored['counts']['price_observations'],1)
        self.assertTrue(restored['promotionDeliveryPaused'])
        self.assertTrue((self.root/'restored/data/site-data.json').exists())
        with self.assertRaises(ValueError): restore(self.root,result['path'])

    def test_A18_seed_is_source_backed_and_empty_evidence_not_passed(self):
        data=read_json(self.root/'data/site-data.json'); validate_site(data)
        self.assertTrue(data['content']); self.assertTrue(data['products'])
        report=audit(self.store)
        self.assertEqual(report['mobileAndPlayback'],'BLOCKED_CONFIG')
        self.assertEqual(report['visitorEffect'],'UNAVAILABLE')
        self.assertTrue(any(item['key']=='showcase-video' for item in report['findings']))

    def test_A09_audit_worker_checks_release_and_complete_denominator(self):
        worker=self.root/'audit-worker'
        with self.store.db: self.store.set_setting('audit',{'workerDirectory':str(worker)})
        first=audit(self.store); self.assertEqual(first['mobileAndPlayback'],'QUEUED')
        request=read_json(next((worker/'requests').glob('*.json')))
        receipt={'id':request['id'],'releaseId':request['releaseId'],'checks':{'mobile':'PASS'},'checkedAt':now()}
        atomic_json(worker/'receipts'/f"{request['id']}.json",receipt)
        self.assertEqual(audit(self.store)['mobileAndPlayback'],'FAIL')
        receipt['checks']=dict.fromkeys(request['requiredChecks'],'PASS'); atomic_json(worker/'receipts'/f"{request['id']}.json",receipt)
        self.assertEqual(audit(self.store)['mobileAndPlayback'],'PASS')


if __name__=='__main__': unittest.main()
