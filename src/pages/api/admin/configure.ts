import type { APIRoute } from 'astro';
import {callOps,jsonResponse,readJson,sameOrigin,rateLimit} from '../../../lib/server';
export const POST:APIRoute=async({request,clientAddress})=>{
  if(!sameOrigin(request))return jsonResponse({ok:false,error:'잘못된 요청 출처입니다.'},403);
  if(!rateLimit('configure:'+clientAddress,12))return jsonResponse({ok:false,error:'설정 요청이 너무 많습니다.'},429);
  try{const body=await readJson(request);if(Object.keys(body).some(k=>!['siteUrl','sourceEnabled','promotionDeliveryPaused'].includes(k)))throw new Error('허용된 운영 설정만 변경할 수 있습니다.');const result=await callOps('configure',['--payload-json',JSON.stringify(body)]);return jsonResponse({ok:true,result});}
  catch{return jsonResponse({ok:false,error:'등록된 출처와 허용된 설정을 확인하세요.'},400);}
};
