import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const root=process.cwd();
const stage=path.resolve(root,'.local/pages-src');
if(path.dirname(stage)!==path.resolve(root,'.local')||path.basename(stage)!=='pages-src')throw new Error('Unexpected generated directory');
if(fs.existsSync(stage))fs.rmSync(stage,{recursive:true,force:true});
fs.mkdirSync(stage,{recursive:true});
for(const name of ['components','layouts','styles'])fs.cpSync(path.join(root,'src',name),path.join(stage,name),{recursive:true});
fs.mkdirSync(path.join(stage,'lib'));for(const file of ['data.ts','search.ts'])fs.copyFileSync(path.join(root,'src/lib',file),path.join(stage,'lib',file));
const pages=path.join(stage,'pages');fs.mkdirSync(pages);
for(const entry of fs.readdirSync(path.join(root,'src/pages'),{withFileTypes:true})){
  if(['admin','api','media'].includes(entry.name))continue;
  fs.cpSync(path.join(root,'src/pages',entry.name),path.join(pages,entry.name),{recursive:true});
}
const detail=path.join(pages,'content/[slug].astro');let text=fs.readFileSync(detail,'utf8');
text=text.replace('const data=loadSiteData();',"export function getStaticPaths(){return loadSiteData().content.map(item=>({params:{slug:item.slug}}));}\nconst data=loadSiteData();");
text=text.replace(/<div class="section-head"><h2>이 내용이 도움이 되었나요\?<\/h2><\/div><div class="toolbar">[\s\S]*?<\/div>/,'');
text=text.replace(/<script is:inline>[\s\S]*?<\/script>/,'');fs.writeFileSync(detail,text);
const search=path.join(pages,'search/index.astro');text=fs.readFileSync(search,'utf8');
text=text.replace('<button class="button" type="button" id="search-miss">검색 결과 없음을 알려주기</button>','<a class="button" href="https://github.com/jungju/r9700/issues/new" target="_blank" rel="noopener noreferrer">찾는 자료 요청하기 ↗</a>');
text=text.replace(/  document\.querySelector\('#search-miss'\)![\s\S]*?\n  draw\(\);/,'  draw();');fs.writeFileSync(search,text);
fs.writeFileSync(path.join(pages,'requests/index.astro'),`---
import SiteLayout from '../../layouts/SiteLayout.astro';
import PageIntro from '../../components/PageIntro.astro';
---
<SiteLayout title="자료 제보와 정정 요청"><div class="wrap"><PageIntro eyebrow="CONTRIBUTE" title="자료 제보" description="작품·새 자료·정정 요청은 GitHub에서 내용을 확인한 뒤 접수합니다."/><section class="card"><p>자료 URL, 제작자, 게시 권한, R9700 제작 근거 또는 정정할 내용을 함께 적어 주세요. 로그인 후 작성할 수 있으며, 요청 내용은 공개됩니다.</p><a class="button primary" href="https://github.com/jungju/r9700/issues/new/choose" target="_blank" rel="noopener noreferrer">GitHub에서 요청 작성하기 ↗</a><p class="source-link">파일이나 비밀 정보는 요청에 넣지 마세요. 자료는 출처와 권한 확인 후 반영합니다.</p></section></div></SiteLayout>`);
fs.writeFileSync(path.join(pages,'404.astro'),`---\nimport SiteLayout from '../layouts/SiteLayout.astro';\n---\n<SiteLayout title="자료를 찾을 수 없습니다"><div class="wrap empty"><h1>자료를 찾을 수 없습니다.</h1><a href="/search">검색으로 돌아가기 →</a></div></SiteLayout>`);
const siteDataPath=process.env.SITE_DATA_PATH||path.join(root,'.local/public/site-data.json');
const data=JSON.parse(fs.readFileSync(fs.existsSync(siteDataPath)?siteDataPath:path.join(root,'data/site-data.json'),'utf8').replace(/^\uFEFF/,''));
const astroPackage=JSON.parse(fs.readFileSync(path.join(root,'node_modules/astro/package.json'),'utf8'));
const astroCli=path.resolve(root,'node_modules/astro',astroPackage.bin.astro);
const now=Date.now();let next=Infinity;
for(const day of [0,1])for(const hour of [3,9,15,21]){const d=new Date(now);const when=Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()+day,hour,17);if(when>now)next=Math.min(next,when);}
data.operations.nextRunAt=new Date(next).toISOString();
const pagesSnapshot=path.resolve(root,'.local/pages-public-data.json');fs.writeFileSync(pagesSnapshot,JSON.stringify(data));
const result=spawnSync(process.execPath,[astroCli,'build'],{cwd:root,stdio:'inherit',env:{...process.env,GITHUB_PAGES:'true',SITE_DATA_PATH:pagesSnapshot}});
if(result.status!==0)process.exit(result.status||1);
const output=path.join(root,'dist-pages');fs.writeFileSync(path.join(output,'CNAME'),'r9700.jjgo.io\n');fs.writeFileSync(path.join(output,'.nojekyll'),'');
fs.writeFileSync(path.join(output,'deployment.json'),JSON.stringify({siteUrl:'https://r9700.jjgo.io',releaseId:data.releaseId,generatedAt:data.generatedAt,host:'GitHub Pages'},null,2));
// Public files only: never stage SQLite, operator configuration, admin or APIs.
for(const blocked of ['admin','api','.local'])if(fs.existsSync(path.join(output,blocked)))throw new Error('Private route included in Pages artifact');
console.log('Pages artifact ready: '+output);
