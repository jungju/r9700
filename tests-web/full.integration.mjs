// Isolated HTTP acceptance: no production state, external requests or posts.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn,execFileSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';

const repo=process.cwd(), root=fs.mkdtempSync(path.join(os.tmpdir(),'r9700-http-'));
const password=crypto.randomBytes(24).toString('hex'), secret=crypto.randomBytes(32).toString('hex');
const base='http://127.0.0.1:4323';let child;let db;let checks=0;let serverLog='';
const ok=(value,message)=>{assert.ok(value,message);checks++;};
// Keep isolated HTTP assertions independent of idle sockets during the browser phase.
const request=(url,init={})=>fetch(url,{...init,headers:{...init.headers,Connection:'close'}});
const env={...process.env,HOST:'127.0.0.1',PORT:'4323',R9700_ROOT:root,PYTHONPATH:repo,ADMIN_PASSWORD:password,SESSION_SECRET:secret};
try{
  fs.mkdirSync(path.join(root,'data'));fs.copyFileSync('data/site-data.json',path.join(root,'data/site-data.json'));fs.copyFileSync('sources.json',path.join(root,'sources.json'));
  execFileSync(process.env.PYTHON_BIN||'python',['-m','ops.r9700','init','--root',root],{cwd:repo,env,stdio:'pipe'});
  child=spawn(process.execPath,['dist/server/entry.mjs'],{cwd:repo,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
  child.stderr.on('data',data=>{serverLog=(serverLog+data.toString()).slice(-8000);});child.stdout.on('data',()=>{});
  let ready=false;for(let i=0;i<100;i++){try{ready=(await request(base+'/api/health')).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,100));}ok(ready,'production server startup');
  const post=(url,payload,cookie='',origin=base)=>request(base+url,{method:'POST',headers:{'Content-Type':'application/json',Origin:origin,...(cookie?{Cookie:cookie}:{})},body:JSON.stringify(payload)});
  ok((await request(base+'/api/admin/status')).status===401,'unauthenticated status blocked');
  ok((await post('/api/login',{password},'','https://untrusted.invalid')).status===403,'cross origin login blocked');
  ok((await post('/api/login',{password:'incorrect'})).status===401,'incorrect password blocked');
  const login=await post('/api/login',{password});ok(login.status===200,'login');
  const setCookie=login.headers.get('set-cookie')||'';ok(setCookie.includes('HttpOnly')&&setCookie.includes('SameSite=Strict'),'protected session cookie');const cookie=setCookie.split(';')[0];
  const status=await request(base+'/api/admin/status',{headers:{Cookie:cookie}});ok(status.status===200,'authenticated status');const statusJson=await status.json();ok(statusJson.summary.sourceCount===73,'registry count');
  const admin=await request(base+'/admin',{headers:{Cookie:cookie}});ok(admin.status===200&&(await admin.text()).includes('지금 상태와 다음 할 일'),'admin render');
  ok((await post('/api/admin/configure',{promotionDeliveryPaused:true},cookie,'https://untrusted.invalid')).status===403,'CSRF config denied');
  ok((await post('/api/admin/configure',{validationCommand:['arbitrary']},cookie)).status===400,'untrusted command config denied');
  ok((await post('/api/admin/configure',{promotionDeliveryPaused:true},cookie)).status===200,'allowlisted config');
  ok((await post('/api/submit',{type:'showcase',url:'https://127.0.0.1/private',title:'test fixture',creator:'test',rights:'test',evidence:'test'})).status===400,'private URL submission blocked');
  ok((await post('/api/submit',{type:'correction',url:'https://www.amd.com/',title:'test-only correction fixture',creator:'fixture',rights:'link only',evidence:'test fixture not publication',notes:'isolated test'})).status===202,'valid submission queued');
  ok((await post('/api/feedback',{kind:'search-miss',query:'ROCm installation fixture'})).status===202,'feedback accepted');
  db=new DatabaseSync(path.join(root,'.local/operations.sqlite3'));
  const mediaDir=path.join(root,'.local/media');fs.mkdirSync(mediaDir,{recursive:true});const bytes=fs.readFileSync('public/images/editorial-cover.webp');fs.writeFileSync(path.join(mediaDir,'fixture.webp'),bytes);
  db.prepare('INSERT INTO media_assets VALUES(?,?,?,?,0)').run('test-only-media',JSON.stringify({url:'/media/fixture.webp'}),crypto.createHash('sha256').update(bytes).digest('hex'),'fixture-only');
  const range=await request(base+'/media/fixture.webp',{headers:{Range:'bytes=0-99'}});ok(range.status===206,'range response');ok((await range.arrayBuffer()).byteLength===100,'range length');
  const suffix=await request(base+'/media/fixture.webp',{headers:{Range:'bytes=-25'}});ok(suffix.status===206&&(await suffix.arrayBuffer()).byteLength===25,'suffix range');
  ok((await request(base+'/media/fixture.webp',{headers:{Range:'bytes=99999999-'}})).status===416,'invalid range');
  ok((await request(base+'/media/fixture.webp',{method:'HEAD'})).status===200,'media head');
  // CPU-generated test video and a conceptual image are fixtures, never R9700 evidence.
  const videoPath=path.join(mediaDir,'fixture.mp4');
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=c=black:s=320x240:d=1','-an','-c:v','libx264','-pix_fmt','yuv420p',videoPath],{stdio:'pipe',windowsHide:true});
  db.prepare('INSERT INTO media_assets VALUES(?,?,?,?,0)').run('test-only-video',JSON.stringify({url:'/media/fixture.mp4'}),crypto.createHash('sha256').update(fs.readFileSync(videoPath)).digest('hex'),'fixture-only');
  const snapshotPath=path.join(root,'.local/public/site-data.json');const fixture=JSON.parse(fs.readFileSync(snapshotPath,'utf8'));
  const common={description:'test-only non-R9700 fixture',provenance:'unverified-reference',rights:'fixture-only',model:'fixture-model',tool:'fixture-tool',metadata:{creator:'fixture'}};
  fixture.showcase=[{...common,id:'fixture-image',title:'Fixture image',type:'image',url:'/media/fixture.webp'},{...common,id:'fixture-video',title:'Fixture video',type:'video',url:'/media/fixture.mp4',poster:'/media/fixture.webp'}];fs.writeFileSync(snapshotPath,JSON.stringify(fixture));
  const cli=path.join(repo,'node_modules/@playwright/cli/playwright-cli.js'),browser='r9700-fixture-'+process.pid;
  const invoke=args=>execFileSync(process.execPath,[cli,'-s='+browser,...args],{cwd:repo,windowsHide:true,encoding:'utf8',timeout:60000,maxBuffer:2*1024*1024});
  try{
    invoke(['open',base+'/showcase','--browser','chrome','--idle-timeout','60000']);invoke(['snapshot']);
    const output=invoke(['run-code','async page => { const images=await page.locator("#gallery img").count(); const noVideo=await page.locator("video").count(); await page.getByRole("button",{name:"이미지 확대: Fixture image"}).click(); const imageOpen=await page.locator("#viewer").evaluate(x=>x.open); await page.getByRole("button",{name:"닫기",exact:true}).click(); await page.getByRole("button",{name:"▶ 영상 재생"}).click(); await page.locator("#viewer video").evaluate(video=>new Promise((resolve,reject)=>{if(video.readyState>=2)return resolve(true);video.addEventListener("loadeddata",()=>resolve(true),{once:true});video.addEventListener("error",()=>reject(new Error("video decode failed")),{once:true});setTimeout(()=>reject(new Error("video timeout")),10000);})); const duration=await page.locator("#viewer video").evaluate(video=>video.duration); await page.getByRole("button",{name:"닫기",exact:true}).click(); await page.locator("#viewer video").waitFor({state:"detached"}); return {images,noVideo,imageOpen,duration,afterClose:await page.locator("video").count()}; }']);
    const match=/### Result\s*([\s\S]*?)\n###/.exec(output);assert.ok(match);const result=JSON.parse(match[1].trim());ok(result.images===2,'image and video poster rendered');ok(result.noVideo===0,'video not loaded before click');ok(result.imageOpen,'image enlargement');ok(result.duration>0,'video decoded and played');ok(result.afterClose===0,'video removed on close');
  }finally{try{invoke(['close']);}catch{}}
  db.prepare('UPDATE media_assets SET revoked=1 WHERE id=?').run('test-only-media');db.close();
  ok((await request(base+'/media/fixture.webp')).status===404,'revoked media denied');
  ok((await post('/api/admin/logout',{},cookie)).status===200,'logout');
  console.log(JSON.stringify({result:'PASS',checks,scope:'isolated production HTTP and media fixture; no external operations'}));
}catch(error){console.error('Isolated integration failed after checks:',checks,error);if(serverLog)console.error(serverLog);throw error;}
finally{try{db?.close();}catch{}if(child){child.kill();await Promise.race([new Promise(resolve=>child.once('exit',resolve)),new Promise(resolve=>setTimeout(resolve,2000))]);}assert.equal(path.dirname(root),path.resolve(os.tmpdir()));assert.ok(path.basename(root).startsWith('r9700-http-'));try{fs.rmSync(root,{recursive:true,force:true,maxRetries:10,retryDelay:100});}catch(error){console.error('Temporary fixture cleanup failed:',error.code);}}
