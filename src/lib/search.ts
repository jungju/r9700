import type {SiteData} from './data.ts';
export interface SearchEntry {title:string;summary:string;url:string;kind:string;kindLabel:string;sourceName:string;date:string;haystack:string;}
const aliases=[['amd radeon ai pro r9700','r9700'],['radeon ai pro r9700','r9700'],['radeon pro ai r9700','r9700'],['ai pro 9700','r9700'],['라데온 ai 프로 r9700','r9700'],['라데온 r9700','r9700'],['gfx 1201','gfx1201'],['rdna 4','rdna4']].sort((a,b)=>b[0].length-a[0].length);
export function normalizeSearch(value:string){let text=value.toLocaleLowerCase('ko').normalize('NFKC');for(const [from,to] of aliases)text=text.split(from).join(to);return text.replace(/\s+/g,' ').trim();}
export function matchesSearch(entry:SearchEntry,query:string,kind:string){return (!kind||entry.kind===kind)&&normalizeSearch(query).split(' ').filter(Boolean).every(token=>normalizeSearch(entry.haystack).includes(token));}
export function buildSearchEntries(data:SiteData,date:(value:string|null|undefined)=>string):SearchEntry[]{
  const labels:Record<string,string>={news:'소식',review:'리뷰·사용기',guide:'가이드',issue:'문제 해결',resource:'자료실'};
  const make=(title:string,summary:string,url:string,kind:string,kindLabel:string,sourceName:string,when:string|null|undefined,extra:string[])=>({title,summary,url,kind,kindLabel,sourceName,date:date(when),haystack:[title,summary,sourceName,...extra].join(' ')});
  const rows=data.content.map(x=>make(x.title,x.summary,'/content/'+encodeURIComponent(x.slug),x.kind,labels[x.kind]||'자료',x.sourceName,x.publishedAt,[x.body,...x.tags]));
  for(const p of data.products)rows.push(make(p.name,p.model+' · '+p.manufacturer,'/products#'+encodeURIComponent(p.id),'product','제품',p.manufacturer,null,[...Object.values(p.specs),'R9700',p.distributor||'']));
  for(const c of data.compatibility)rows.push(make(c.os+' · '+c.tool,c.detail+' · '+c.version,'/compatibility','compatibility','호환성','공식 문서 참고',c.checkedAt,['R9700',c.status]));
  const latest=new Map<string,SiteData['prices'][number]>();for(const p of [...data.prices].sort((a,b)=>Date.parse(b.observedAt)-Date.parse(a.observedAt)))if(!latest.has(p.offerId))latest.set(p.offerId,p);
  for(const p of latest.values())rows.push(make(p.seller+' 가격 관측',(p.price===null?'가격 미확인':p.currency+' '+p.price)+' · '+p.condition,'/prices','price','가격 관측',p.seller,p.observedAt,['R9700',p.region,p.stock]));
  for(const s of data.showcase)rows.push(make(s.title,s.description,'/showcase','showcase','작품',s.metadata?.creator||'제작자 자료',s.createdAt,['R9700',s.model||'',s.tool||'',s.provenance,s.rights]));
  for(const s of data.sources)rows.push(make(s.name,s.category+' · '+(s.automationVerified?'반복 수집 검증':'등록 자료·연결 상태 확인 필요'),'/sources','source','출처',s.name,null,['R9700',s.url,s.status]));
  return rows;
}
