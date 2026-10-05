import type { APIRoute } from 'astro';
import {jsonResponse,readJson,sameOrigin,startOperation,rateLimit} from '../../../lib/server';
export const POST:APIRoute=async({request,clientAddress})=>{
  if(!sameOrigin(request))return jsonResponse({ok:false,error:'잘못된 요청 출처입니다.'},403);
  if(!rateLimit('action:'+clientAddress,12))return jsonResponse({ok:false,error:'실행 요청이 너무 많습니다.'},429);
  try{const body=await readJson(request);if(typeof body.command!=='string')throw new Error('명령이 필요합니다.');return jsonResponse({ok:true,operation:startOperation(body.command)},202);}
  catch(error){return jsonResponse({ok:false,error:error instanceof Error?error.message:'실행할 수 없습니다.'},400);}
};
