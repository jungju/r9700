import test from 'node:test';
import assert from 'node:assert/strict';
import {buildSearchEntries,matchesSearch,normalizeSearch} from '../src/lib/search.ts';
test('long and Korean GPU aliases normalize consistently; keywords match across fields',()=>{
  assert.equal(normalizeSearch('AMD Radeon AI PRO R9700'),normalizeSearch('라데온 R9700'));
  const entry={kind:'guide',haystack:'R9700 ROCm Windows install'};
  assert.equal(matchesSearch(entry,'Windows ROCm','guide'),true);
  assert.equal(matchesSearch(entry,'9700X',''),false);
  assert.equal(matchesSearch(entry,'ROCm','price'),false);
});
test('unified search keeps product, price, compatibility, artwork and discovery provenance',()=>{
  const data={content:[],products:[{id:'p',name:'Example R9700',model:'m',manufacturer:'maker',specs:{vram:'32GB'}}],compatibility:[{os:'Linux',tool:'ROCm',detail:'Reference only',version:'unspecified',status:'reference'}],prices:[{offerId:'o',seller:'store',price:100,currency:'USD',condition:'unknown shipping',region:'US',stock:'unknown',observedAt:'2026-10-05T00:00:00Z'}],showcase:[{title:'Reference fixture',description:'GPU unverified',provenance:'unverified-reference',rights:'fixture',metadata:{creator:'fixture'}}],sources:[{name:'Candidate publisher',category:'source',url:'https://example.org',status:'candidate',automationVerified:false}]};
  const entries=buildSearchEntries(data,()=> 'date unknown');assert.deepEqual(entries.map(x=>x.kind),['product','compatibility','price','showcase','source']);
  assert.match(entries.find(x=>x.kind==='source').summary,/연결 상태 확인 필요/);
  assert.ok(entries.find(x=>x.kind==='price').summary.includes('unknown shipping'));
});
