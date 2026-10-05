import type { APIRoute } from 'astro';
import fs from 'node:fs';
import path from 'node:path';
import {Readable} from 'node:stream';
import {DatabaseSync} from 'node:sqlite';
import {projectRoot} from '../../lib/data';
const mime:Record<string,string>={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.avif':'image/avif','.mp4':'video/mp4','.webm':'video/webm'};
export const GET:APIRoute=({params,request})=>{
  const root=path.resolve(projectRoot(),'.local/media');const name=params.file||'';
  if(!name||name.includes('\\')||name.includes('\0'))return new Response(null,{status:404});
  const candidate=path.resolve(root,name); if(!candidate.startsWith(root+path.sep)||!mime[path.extname(candidate).toLowerCase()])return new Response(null,{status:404});
  try{
    const database=new DatabaseSync(path.join(projectRoot(),'.local/operations.sqlite3'),{readOnly:true});
    let asset: {hash:string}|undefined;
    try{asset=database.prepare("SELECT hash FROM media_assets WHERE revoked=0 AND json_extract(payload,'$.url')=? LIMIT 1").get('/media/'+name) as {hash:string}|undefined;}finally{database.close();}
    if(!asset)return new Response(null,{status:404});
    const real=fs.realpathSync(candidate), realRoot=fs.realpathSync(root);if(!real.startsWith(realRoot+path.sep))return new Response(null,{status:404});
    const stat=fs.statSync(real);if(!stat.isFile()||stat.size<=0)return new Response(null,{status:404});
    const headers:Record<string,string>={'Content-Type':mime[path.extname(real).toLowerCase()],'Accept-Ranges':'bytes','Cache-Control':'no-cache, max-age=0, must-revalidate','ETag':'"'+asset.hash+'"'};
    if(!request.headers.get('range')&&request.headers.get('if-none-match')===headers.ETag)return new Response(null,{status:304,headers});
    const range=request.headers.get('range');let start=0,end=stat.size-1,status=200;
    if(range){const match=/^bytes=(\d*)-(\d*)$/.exec(range);if(!match)return new Response(null,{status:416,headers:{'Content-Range':'bytes */'+stat.size}});if(!match[1]){const suffix=Number(match[2]);if(!Number.isSafeInteger(suffix)||suffix<=0)return new Response(null,{status:416});start=Math.max(0,stat.size-suffix);}else{start=Number(match[1]);if(match[2])end=Number(match[2]);}if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=stat.size)return new Response(null,{status:416,headers:{'Content-Range':'bytes */'+stat.size}});end=Math.min(end,stat.size-1);status=206;headers['Content-Range']='bytes '+start+'-'+end+'/'+stat.size;}
    headers['Content-Length']=String(end-start+1);
    return new Response(Readable.toWeb(fs.createReadStream(real,{start,end})) as ReadableStream,{status,headers});
  }catch{return new Response(null,{status:404});}
};
export const HEAD:APIRoute=async context=>{const result=await GET(context);await result.body?.cancel();return new Response(null,{status:result.status,headers:result.headers});};
