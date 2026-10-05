// Fixed browser validation using the Playwright CLI, not a visitor A/B test.
import assert from 'node:assert/strict';
import path from 'node:path';
import {spawn,execFileSync} from 'node:child_process';
const root=process.cwd(),cli=path.join(root,'node_modules/@playwright/cli/playwright-cli.js');
const session='r9700-verify-'+process.pid;
const index=process.argv.indexOf('--url');
const base=index>=0?process.argv[index+1]:'http://127.0.0.1:4324';
let child;
const invoke=(args)=>execFileSync(process.execPath,[cli,'-s='+session,...args],{cwd:root,windowsHide:true,encoding:'utf8',timeout:90000,maxBuffer:2*1024*1024});
try{
  if(index<0)child=spawn(process.execPath,['dist/server/entry.mjs'],{cwd:root,env:{...process.env,HOST:'127.0.0.1',PORT:'4324'},stdio:'ignore',windowsHide:true});
  let ready=false;for(let i=0;i<100;i++){try{ready=(await fetch(base+'/api/health')).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,100));}assert.ok(ready,'site health');
  invoke(['open',base,'--browser','chrome','--idle-timeout','90000']);
  const code='async page => { const results=[]; for (const width of [360,390,768,1440]) { await page.setViewportSize({width,height:900}); for (const route of ["/","/news","/guides","/prices","/products","/compatibility","/showcase","/sources","/search","/about","/requests"]) { const response=await page.goto('+JSON.stringify(base)+'+route); const metrics=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,h1:document.querySelectorAll("h1").length})); results.push({width,route,status:response.status(),...metrics}); } } return {checks:results.length,failures:results.filter(x=>x.status!==200||x.scroll>x.width||x.h1!==1)}; }';
  const output=invoke(['run-code',code]);const match=/### Result\s*([\s\S]*?)\n###/.exec(output);assert.ok(match,'browser result missing');const result=JSON.parse(match[1].trim());assert.equal(result.checks,44);assert.equal(result.failures.length,0,JSON.stringify(result.failures));
  const health=await(await fetch(base+'/api/health')).json();console.log(JSON.stringify({result:'PASS',...result,releaseId:health.releaseId,scope:'fixed responsive browser checks'}));
}finally{try{invoke(['close']);}catch{}child?.kill();}
