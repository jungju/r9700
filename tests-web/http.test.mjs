import test from 'node:test';
import assert from 'node:assert/strict';

const base=process.env.TEST_BASE_URL;
test('public routes, real 404, feed release, and administration boundary',{skip:!base},async()=>{
  for(const route of ['/','/news','/guides','/prices','/products','/compatibility','/showcase','/sources','/search','/about','/requests']){
    const response=await fetch(base+route);assert.equal(response.status,200,route);const html=await response.text();assert.match(html,/<html[^>]*lang="ko"/);assert.match(html,/r9700\.jjgo\.io/);assert.ok(response.headers.get('content-security-policy'));
  }
  const missing=await fetch(base+'/content/nonexistent-content-id');assert.equal(missing.status,404);
  const health=await (await fetch(base+'/api/health')).json();assert.equal(health.ok,true);
  for(const route of ['/rss.xml','/sitemap.xml']){const response=await fetch(base+route);assert.equal(response.status,200);assert.equal(response.headers.get('x-release-id'),health.contentReleaseId||health.releaseId);assert.match(await response.text(),/r9700\.jjgo\.io/);}
  assert.equal((await fetch(base+'/api/admin/status')).status,401);
  assert.equal((await fetch(base+'/admin',{redirect:'manual'})).status,302);
  const denied=await fetch(base+'/api/submit',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://untrusted.invalid'},body:JSON.stringify({url:'https://example.org'})});assert.equal(denied.status,403);
  const media=await fetch(base+'/media/unregistered.mp4');assert.equal(media.status,404);
});
