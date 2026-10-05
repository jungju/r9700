import type { APIRoute } from 'astro';
import {adminConfigured,checkPassword,createSession,jsonResponse,rateLimit,readJson,sameOrigin,SESSION_COOKIE} from '../../lib/server';
export const POST:APIRoute=async({request,cookies,clientAddress})=>{
  if(!sameOrigin(request))return jsonResponse({ok:false,error:'잘못된 요청 출처입니다.'},403);
  if(!adminConfigured())return jsonResponse({ok:false,error:'관리자 환경 설정이 필요합니다.'},503);
  if(!rateLimit('login:'+clientAddress,5))return jsonResponse({ok:false,error:'잠시 후 다시 시도하세요.'},429);
  try{
    const body=await readJson(request);
    if(typeof body.password!=='string'||!checkPassword(body.password))return jsonResponse({ok:false,error:'비밀번호를 확인하세요.'},401);
    cookies.set(SESSION_COOKIE,createSession(),{httpOnly:true,secure:new URL(request.url).protocol==='https:',sameSite:'strict',path:'/',maxAge:8*60*60});
    return jsonResponse({ok:true});
  }catch{return jsonResponse({ok:false,error:'요청을 확인하세요.'},400);}
};
