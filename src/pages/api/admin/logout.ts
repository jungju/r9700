import type { APIRoute } from 'astro';
import {jsonResponse,sameOrigin,SESSION_COOKIE} from '../../../lib/server';
export const POST:APIRoute=({request,cookies})=>{
  if(!sameOrigin(request))return jsonResponse({ok:false,error:'잘못된 요청 출처입니다.'},403);
  cookies.delete(SESSION_COOKIE,{path:'/'});return jsonResponse({ok:true});
};
