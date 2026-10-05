import type { APIRoute } from 'astro';
import {callOps,jsonResponse,readJson,sameOrigin,rateLimit} from '../../lib/server';
export const POST:APIRoute=async({request,clientAddress})=>{
  if(!sameOrigin(request))return jsonResponse({ok:false,error:'잘못된 요청 출처입니다.'},403);
  if(!rateLimit('submit:'+clientAddress,5,60*60*1000))return jsonResponse({ok:false,error:'접수 한도에 도달했습니다.'},429);
  try{
    const body=await readJson(request);
    const keys=['type','url','title','creator','rights','evidence','notes']; const clean:Record<string,string>={};
    for(const key of keys){if(typeof body[key]==='string')clean[key]=(body[key] as string).trim().slice(0,key==='notes'||key==='evidence'?2000:500);}
    if(!['showcase','correction'].includes(clean.type)||!clean.url||!clean.title||!clean.rights)throw new Error('종류·URL·제목·게시 권한을 확인하세요.');
    const url=new URL(clean.url);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error('올바른 공개 URL이 필요합니다.');
    await callOps('submit',['--payload-json',JSON.stringify(clean)]);
    return jsonResponse({ok:true,message:'접수했습니다. 출처와 제작 근거를 확인한 뒤 반영합니다.'},202);
  }catch(error){return jsonResponse({ok:false,error:error instanceof Error&&error.message.startsWith('Command failed')?'접수 기능을 준비 중입니다.':error instanceof Error?error.message:'요청을 확인하세요.'},400);}
};
