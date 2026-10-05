import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
if(fs.existsSync('.env'))process.loadEnvFile('.env');
const root=process.cwd(),python=process.env.PYTHON_BIN||'python';
const astroPackage=JSON.parse(fs.readFileSync(path.join(root,'node_modules/astro/package.json'),'utf8'));
const astroCli=path.resolve(root,'node_modules/astro',astroPackage.bin.astro);
const init=spawnSync(python,['-m','ops.r9700','init','--root',root],{cwd:root,windowsHide:true,encoding:'utf8'});
if(init.status!==0){console.error('운영 DB를 준비할 수 없습니다.');console.error(init.stderr);process.exit(1);}
const processes=[
  spawn(process.execPath,[astroCli,'dev','--host','127.0.0.1'],{cwd:root,stdio:'inherit',windowsHide:true}),
  spawn(python,['-m','ops.r9700','schedule','--root',root],{cwd:root,stdio:'inherit',windowsHide:true}),
];
let stopping=false;
function stop(code=0){if(stopping)return;stopping=true;for(const child of processes)if(!child.killed)child.kill();setTimeout(()=>process.exit(code),300).unref();}
process.on('SIGINT',()=>stop());process.on('SIGTERM',()=>stop());
for(const child of processes){child.once('error',()=>stop(1));child.once('exit',code=>{if(!stopping)stop(code||1);});}
console.log('R9700 Hub 로컬 웹과 6시간 운영 스케줄러를 시작했습니다.');
