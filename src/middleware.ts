import { defineMiddleware } from 'astro:middleware';
import { validSession, SESSION_COOKIE } from './lib/server';

export const onRequest=defineMiddleware(async(context,next)=>{
  const route=context.url.pathname;
  if((route.startsWith('/admin') && route!=='/admin/login') || route.startsWith('/api/admin/')){
    if(!validSession(context.cookies.get(SESSION_COOKIE)?.value)){
      if(route.startsWith('/api/'))return new Response(JSON.stringify({ok:false,error:'인증이 필요합니다.'}),{status:401,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
      return context.redirect('/admin/login',302);
    }
  }
  const response=await next();
  response.headers.set('X-Content-Type-Options','nosniff');
  response.headers.set('Referrer-Policy','strict-origin-when-cross-origin');
  response.headers.set('X-Frame-Options','DENY');
  response.headers.set('Permissions-Policy','camera=(), microphone=(), geolocation=()');
  response.headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; media-src 'self' https:; connect-src 'self'; frame-src https://www.youtube-nocookie.com https://www.youtube.com https://player.vimeo.com; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'");
  if(route.startsWith('/admin')||route.startsWith('/api/'))response.headers.set('Cache-Control','no-store');
  return response;
});
