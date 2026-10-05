import type { APIRoute } from 'astro';
import {callOps,jsonResponse,readJson,sameOrigin,rateLimit} from '../../lib/server';
export const POST:APIRoute=async({request,clientAddress})=>{
  if(!sameOrigin(request))return jsonResponse({ok:false},403);
  if(!rateLimit('feedback:'+clientAddress,20,60*60*1000))return jsonResponse({ok:false},429);
  try{const body=await readJson(request,1024);if(typeof body.query!=='string'||!['search-miss','helpful','missing-context'].includes(String(body.kind)))throw new Error('Invalid feedback'); await callOps('feedback',['--payload-json',JSON.stringify({query:body.query.slice(0,200),kind:body.kind})]);return jsonResponse({ok:true},202);}catch{return jsonResponse({ok:false,error:'피드백을 저장할 수 없습니다.'},400);}
};
