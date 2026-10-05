import type { APIRoute } from 'astro';
import {loadSiteData,siteUrl} from '../lib/data';
export const GET:APIRoute=()=>{const d=loadSiteData();const routes=['','/news','/guides','/prices','/products','/compatibility','/showcase','/sources','/about',...d.content.map(i=>'/content/'+encodeURIComponent(i.slug))];return new Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+routes.map(r=>'<url><loc>'+siteUrl()+r+'</loc></url>').join('')+'</urlset>',{headers:{'Content-Type':'application/xml; charset=utf-8','X-Release-Id':d.releaseId}});};
