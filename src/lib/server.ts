import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { projectRoot } from './data.ts';

const exec = promisify(execFile);
try { if (fs.existsSync(path.join(projectRoot(), '.env'))) process.loadEnvFile(path.join(projectRoot(), '.env')); } catch { /* deployment environment wins */ }
export const SESSION_COOKIE = 'r9700_admin';
export function adminConfigured() { return (process.env.ADMIN_PASSWORD || '').length >= 16 && (process.env.SESSION_SECRET || '').length >= 32; }
function equal(a: string, b: string) { const aa=crypto.createHash('sha256').update(a).digest(); const bb=crypto.createHash('sha256').update(b).digest(); return crypto.timingSafeEqual(aa,bb); }
export function checkPassword(password: string) { return adminConfigured() && equal(password, process.env.ADMIN_PASSWORD || ''); }
export function createSession(now=Date.now()) {
  if (!adminConfigured()) throw new Error('Admin not configured');
  const body=Buffer.from(JSON.stringify({ exp:now+8*60*60*1000, nonce:crypto.randomBytes(16).toString('hex') })).toString('base64url');
  return body+'.'+crypto.createHmac('sha256',process.env.SESSION_SECRET!).update(body).digest('base64url');
}
export function validSession(token: string|undefined, now=Date.now()) {
  if (!token || !adminConfigured() || token.length>512) return false;
  const parts=token.split('.'); if(parts.length!==2) return false;
  const expected=crypto.createHmac('sha256',process.env.SESSION_SECRET!).update(parts[0]).digest('base64url');
  if (!equal(parts[1],expected)) return false;
  try { const value=JSON.parse(Buffer.from(parts[0],'base64url').toString()); return Number.isFinite(value.exp) && value.exp>now && value.exp<=now+8*60*60*1000; } catch { return false; }
}
export function sameOrigin(request: Request) {
  const origin=request.headers.get('origin');
  if (!origin || request.headers.get('sec-fetch-site')==='cross-site') return false;
  try { return new URL(origin).origin===new URL(request.url).origin; } catch { return false; }
}
export async function readJson(request: Request, limit=8192): Promise<Record<string,unknown>> {
  if (!request.headers.get('content-type')?.includes('application/json')) throw new Error('JSON 요청이 필요합니다.');
  if (Number(request.headers.get('content-length') || 0)>limit) throw new Error('요청이 너무 큽니다.');
  const text=await request.text(); if(Buffer.byteLength(text)>limit) throw new Error('요청이 너무 큽니다.');
  const value=JSON.parse(text); if (!value || Array.isArray(value) || typeof value!=='object') throw new Error('잘못된 요청입니다.'); return value;
}
const attempts=new Map<string,{ count:number; until:number }>();
export function rateLimit(key:string, max=10, windowMs=15*60*1000) {
  const now=Date.now(); for(const [k,v] of attempts) if(v.until<now) attempts.delete(k);
  const item=attempts.get(key); if(!item){ if(attempts.size>=10000) return false; attempts.set(key,{count:1,until:now+windowMs}); return true; }
  item.count++; return item.count<=max;
}
export async function callOps(command:string, args:string[]=[], timeout=20000) {
  const allowed=['status','submit','feedback','configure','questions'];
  if(!allowed.includes(command)) throw new Error('허용되지 않은 명령입니다.');
  const result=await exec(process.env.PYTHON_BIN||'python',['-m','ops.r9700',command,'--root',projectRoot(),...args],{cwd:projectRoot(),timeout,maxBuffer:2*1024*1024,windowsHide:true});
  return JSON.parse(result.stdout.replace(/^\uFEFF/,''));
}
export async function loadOpsStatus() {
  try { return await callOps('status'); }
  catch { return {runs:[],sources:[],questions:[],improvements:[],promotions:[],generationJobs:[],config:{},summary:{state:'NOT_INITIALIZED',message:'python -m ops.r9700 init 으로 운영 DB를 준비하세요.'}}; }
}
export function startOperation(command:string) {
  if(!['init','run','collect','audit','promote','export','backup'].includes(command)) throw new Error('허용되지 않은 명령입니다.');
  const dir=path.join(projectRoot(),'.local'); fs.mkdirSync(dir,{recursive:true});
  const lock=path.join(dir,'web-operation.json');
  if(fs.existsSync(lock)) {
    try { const prior=JSON.parse(fs.readFileSync(lock,'utf8')); if(Number.isInteger(prior.pid)){ try { process.kill(prior.pid,0); throw new Error('이미 운영 작업이 실행 중입니다.'); } catch(error) { if((error as NodeJS.ErrnoException).code!=='ESRCH') throw error; } } }
    catch(error) { if(error instanceof SyntaxError) throw new Error('작업 잠금 상태를 확인하세요.'); throw error; }
    fs.unlinkSync(lock);
  }
  const log=path.join(dir,'web-operation.log');
  const fd=fs.openSync(log,'a');
  let lockFd:number; try{ lockFd=fs.openSync(lock,'wx'); } catch { fs.closeSync(fd); throw new Error('이미 운영 작업이 실행 중입니다.'); }
  try {
    const child=spawn(process.env.PYTHON_BIN||'python',['-m','ops.r9700',command,'--root',projectRoot()],{cwd:projectRoot(),windowsHide:true,stdio:['ignore',fd,fd]});
    fs.writeFileSync(lockFd,JSON.stringify({pid:child.pid,command,startedAt:new Date().toISOString()})); fs.closeSync(lockFd); fs.closeSync(fd);
    const finish=()=>{try{fs.unlinkSync(lock);}catch{/* already cleared */}}; child.once('close',finish); child.once('error',finish);
    child.unref(); return {pid:child.pid,command,state:'QUEUED'};
  } catch(error) { fs.closeSync(lockFd); fs.closeSync(fd); try{fs.unlinkSync(lock);}catch{} throw error; }
}
export function jsonResponse(value:unknown,status=200) { return new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'}}); }
