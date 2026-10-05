"""HN targeted discovery pagination and migration regression tests."""
import json
import unittest
from urllib.parse import parse_qs,urlsplit

import test_ops
from ops.collect import collect,configure_hn_search
from ops.common import dumps,now,read_json
from ops.r9700 import init
from ops.security import FetchError,Response


class SearchClient:
    def __init__(self,pages=1,per_page=2,fail_page=None,exhaustive=True):
        self.pages=pages; self.per_page=per_page; self.fail_page=fail_page; self.exhaustive=exhaustive; self.urls=[]
    def get(self,url,*args,**kwargs):
        self.urls.append(url); query=parse_qs(urlsplit(url).query); page=int(query['page'][0])
        if page==self.fail_page: raise FetchError('fixture unavailable',503)
        data={'page':page,'nbPages':self.pages,'hitsPerPage':self.per_page,'nbHits':self.pages*self.per_page,'exhaustiveNbHits':self.exhaustive,
              'hits':[{'objectID':str(900000+page*self.per_page+n),'title':'AMD R9700 story '+str(n),
                       'url':'https://example.com/reference-'+str(page*self.per_page+n),
                       'created_at':'2025-08-01T00:00:00Z','story_text':None,'_tags':['story']} for n in range(self.per_page)]}
        return Response(200,url,{},json.dumps(data).encode())


class HNSearchCase(unittest.TestCase):
    def setUp(self): test_ops.OpsCase.setUp(self)
    def tearDown(self): test_ops.OpsCase.tearDown(self)

    def test_complete_pages_and_repeat_do_not_duplicate(self):
        client=SearchClient(pages=3,per_page=2)
        first=collect(self.store,'src-057',event_id='first-search',client=client)
        self.assertEqual(first['state'],'SUCCESS'); self.assertEqual(first['new'],6); self.assertEqual(len(client.urls),3)
        queries=[parse_qs(urlsplit(url).query) for url in client.urls]
        self.assertEqual({query['numericFilters'][0] for query in queries},{queries[0]['numericFilters'][0]})
        self.assertTrue(all(query['typoTolerance']==['false'] for query in queries))
        row=self.store.db.execute("SELECT * FROM sources WHERE id='src-057'").fetchone(); checkpoint=json.loads(row['checkpoint'])
        self.assertEqual(checkpoint['scanned'],6); self.assertEqual(checkpoint['reportedPages'],3); self.assertIn('unindexed',row['coverage_gap'])
        repeat=collect(self.store,'src-057',event_id='second-search',client=client)
        self.assertEqual(repeat['new'],0); self.assertEqual(repeat['duplicate'],6)
        payload=json.loads(self.store.db.execute("SELECT payload FROM content_items WHERE canonical_url='https://news.ycombinator.com/item?id=900000'").fetchone()[0])
        self.assertIn('HN-submission-date',payload['evidenceStatus']); self.assertIn('Algolia',payload['discoveryProvider'])

    def test_bound_preserves_checkpoint_and_resumes_without_skipping(self):
        prior=dumps({'previousCompleteWindow':'retained'})
        with self.store.db: self.store.db.execute("UPDATE sources SET checkpoint=? WHERE id='src-057'",(prior,))
        client=SearchClient(pages=5,per_page=50)
        first=collect(self.store,'src-057',event_id='large-first',client=client)
        self.assertEqual(first['state'],'BACKLOG'); self.assertEqual(first['new'],200); self.assertEqual(len(client.urls),4)
        self.assertEqual(self.store.db.execute("SELECT checkpoint FROM sources WHERE id='src-057'").fetchone()[0],prior)
        progress=self.store.setting('hnSearchProgress'); self.assertEqual(progress['page'],4); self.assertEqual(progress['offset'],0)
        second=collect(self.store,'src-057',event_id='large-second',client=client)
        self.assertEqual(second['state'],'SUCCESS'); self.assertEqual(second['new'],50); self.assertIsNone(self.store.setting('hnSearchProgress'))
        checkpoint=json.loads(self.store.db.execute("SELECT checkpoint FROM sources WHERE id='src-057'").fetchone()[0])
        self.assertEqual(checkpoint['windowUpper'],progress['upper']); self.assertEqual(checkpoint['scanned'],250)

    def test_partial_page_offset_and_complete_metadata(self):
        from ops.collect import hn_search_entries,hn_search_url
        from ops.common import parse_time
        import time
        progress={'upper':int(parse_time(now()).timestamp()),'page':0,'offset':0,'scanned':0}
        client=SearchClient(pages=2,per_page=3)
        entries,progress,complete=hn_search_entries(client,client.get(hn_search_url(progress)),progress,time.monotonic()+120,4)
        self.assertFalse(complete); self.assertEqual(len(entries),4); self.assertEqual(progress['page'],1); self.assertEqual(progress['offset'],1)
        entries2,final,complete=hn_search_entries(client,client.get(hn_search_url(progress)),progress,time.monotonic()+120,20)
        self.assertTrue(complete); self.assertEqual(len(entries2),2); self.assertEqual(final['scanned'],6)
        self.assertEqual(len({entry['hnStoryId'] for entry in entries+entries2}),6)

    def test_failed_next_page_never_advances_or_publishes_partial_batch(self):
        prior=dumps({'previous':'complete'})
        with self.store.db: self.store.db.execute("UPDATE sources SET checkpoint=? WHERE id='src-057'",(prior,))
        client=SearchClient(pages=2,fail_page=1)
        result=collect(self.store,'src-057',event_id='failed-pages',client=client)
        self.assertEqual(result['failed'],1); self.assertEqual(result['new'],0)
        self.assertEqual(self.store.db.execute("SELECT checkpoint FROM sources WHERE id='src-057'").fetchone()[0],prior)

    def test_provider_approximation_is_coverage_gap_not_infinite_backlog(self):
        result=collect(self.store,'src-057',client=SearchClient(exhaustive=False))
        self.assertEqual(result['state'],'SUCCESS'); self.assertEqual(result['backlog'],0)
        self.assertIn('approximate',result['sources'][0]['coverageGap'])

    def test_runtime_migration_keeps_old_backlog_and_registry_unchanged(self):
        original=(self.root/'sources.json').read_bytes()
        source=next(item for item in read_json(self.root/'sources.json')['sources'] if item['id']=='src-057')
        legacy={'pending':[1,2,3],'seen':[4]}
        with self.store.db:
            self.store.db.execute("DELETE FROM settings WHERE key IN ('hnSearchConfiguredAt','hnLegacyCheckpoint')")
            self.store.db.execute("UPDATE sources SET payload=?,checkpoint=?,state='BACKLOG' WHERE id='src-057'",(dumps(source),dumps(legacy)))
        configure_hn_search(self.store)
        self.assertEqual(self.store.setting('hnLegacyCheckpoint')['checkpoint'],legacy)
        self.assertEqual(self.store.setting('hnLegacyCheckpoint')['state'],'SUPERSEDED_DISCOVERY')
        collect(self.store,'src-057',client=SearchClient())
        prior=self.store.db.execute("SELECT checkpoint FROM sources WHERE id='src-057'").fetchone()[0]
        init(self.store)
        self.assertEqual(self.store.db.execute("SELECT checkpoint FROM sources WHERE id='src-057'").fetchone()[0],prior)
        after_restart=collect(self.store,'src-057',event_id='after-init',client=SearchClient())
        self.assertEqual(after_restart['state'],'SUCCESS')
        self.assertEqual(after_restart['new'],0)
        self.assertEqual(after_restart['duplicate'],2)
        self.assertEqual((self.root/'sources.json').read_bytes(),original)


if __name__=='__main__': unittest.main()
