import test from 'node:test';
import assert from 'node:assert/strict';
import {adminConfigured,checkPassword,createSession,validSession,sameOrigin,readJson,rateLimit} from '../src/lib/server.ts';

test('admin disabled without secrets, signed sessions expire and reject alteration',()=>{
  const oldPassword=process.env.ADMIN_PASSWORD,oldSecret=process.env.SESSION_SECRET;
  try{delete process.env.ADMIN_PASSWORD;delete process.env.SESSION_SECRET;assert.equal(adminConfigured(),false);assert.equal(validSession('anything'),false);process.env.ADMIN_PASSWORD='long-private-password-for-test';process.env.SESSION_SECRET='private-session-secret-for-testing-only-32chars';assert.equal(checkPassword('incorrect'),false);assert.equal(checkPassword(process.env.ADMIN_PASSWORD),true);const token=createSession(1000);assert.equal(validSession(token,1001),true);assert.equal(validSession(token+'x',1001),false);assert.equal(validSession(token,1000+8*60*60*1000),false);}finally{if(oldPassword===undefined)delete process.env.ADMIN_PASSWORD;else process.env.ADMIN_PASSWORD=oldPassword;if(oldSecret===undefined)delete process.env.SESSION_SECRET;else process.env.SESSION_SECRET=oldSecret;}
});
test('mutation requires same origin and bounded JSON object',async()=>{
  assert.equal(sameOrigin(new Request('https://r9700.jjgo.io/api/admin/action',{headers:{origin:'https://evil.example'}})),false);
  assert.equal(sameOrigin(new Request('https://r9700.jjgo.io/api/admin/action',{headers:{origin:'https://r9700.jjgo.io'}})),true);
  assert.equal(sameOrigin(new Request('https://r9700.jjgo.io/api/admin/action')),false);
  await assert.rejects(readJson(new Request('https://example.test',{method:'POST',headers:{'content-type':'application/json'},body:'[]'})));
  await assert.rejects(readJson(new Request('https://example.test',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({x:'a'.repeat(200)})}),100));
});
test('rate limits prevent repeated requests',()=>{const key='test-'+Date.now();assert.equal(rateLimit(key,2),true);assert.equal(rateLimit(key,2),true);assert.equal(rateLimit(key,2),false);});
