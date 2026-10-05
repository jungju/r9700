import type { APIRoute } from 'astro';
import {loadSiteData} from '../../lib/data';
import {jsonResponse} from '../../lib/server';
export const GET:APIRoute=()=>{try{const data=loadSiteData();const codeReleaseId=process.env.R9700_CODE_RELEASE||null;return jsonResponse({ok:true,releaseId:codeReleaseId||data.releaseId,contentReleaseId:data.releaseId,codeReleaseId,generatedAt:data.generatedAt});}catch{return jsonResponse({ok:false},503);}};
