"""Conservative public metadata adapters. No scraped article bodies are published."""
from __future__ import annotations

import json
import html as html_module
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit,urlencode
from urllib.robotparser import RobotFileParser

from .common import UTC,digest,dumps,now,parse_time,redact
from .security import AGENT,FetchError,SafeClient,plain_text,relevant,safe_url

PUBLIC_FEEDS = {
 'src-003': {'hosts':['newsroom.amd.com'],'kind':'general'},
 'src-004': {'hosts':['rocm.blogs.amd.com'],'kind':'rocm'},
 'src-021': {'hosts':['api.github.com','github.com'],'kind':'therock'},
 'src-057': {'hosts':['hn.algolia.com','hacker-news.firebaseio.com'],'kind':'general'},
}
PARSER_VERSION='metadata-v1'
HN_SEARCH_ENDPOINT='https://hn.algolia.com/api/v1/search_by_date'
HN_SEARCH_PROVIDER='Algolia HN Search (third-party Hacker News index)'


def configure_hn_search(store):
    """Upgrade the discovered raw feed in the runtime DB, retaining its prior backlog."""
    row=store.db.execute("SELECT * FROM sources WHERE id='src-057'").fetchone()
    if not row: return
    source=json.loads(row['payload'])
    if source.get('adapter')=='hn-search': return
    if source.get('adapter')!='hn-newstories': return
    source.update({'adapter':'hn-search','fetchEndpoint':HN_SEARCH_ENDPOINT,
                   'discoveryEndpoint':HN_SEARCH_ENDPOINT,'discoveryProvider':HN_SEARCH_PROVIDER,
                   'discoveryQuery':'R9700; tags=story; typoTolerance=false',
                   'previousDiscoveryEndpoint':source.get('fetchEndpoint')})
    with store.db:
        if store.setting('hnSearchConfiguredAt'):
            store.db.execute("UPDATE sources SET payload=? WHERE id='src-057'",(dumps(source),))
            return
        if row['checkpoint'] and not store.setting('hnLegacyCheckpoint'):
            store.set_setting('hnLegacyCheckpoint',{'checkpoint':json.loads(row['checkpoint']),'at':now(),
                 'state':'SUPERSEDED_DISCOVERY','reason':'Full HN newstories backlog replaced by explicit R9700 search; not claimed processed.'})
        store.db.execute("UPDATE sources SET payload=?,checkpoint=NULL,state='READY',automation_verified=0,last_success=NULL,published_revision=NULL,etag=NULL,last_modified=NULL,retry_at=NULL,retry_count=0,policy=? WHERE id='src-057'",
          (dumps(source),dumps({'access':'public-search-api','provider':HN_SEARCH_PROVIDER,'query':'R9700',
                              'publication':'title-link-submission-date-only','checkedAt':now(),
                              'evidence':'https://github.com/algolia/hn-search; live SafeClient JSON probe 2026-10-05'})))
        store.set_setting('hnSearchConfiguredAt',now())
        store.db.execute("UPDATE jobs SET state='SUPERSEDED' WHERE id='retry:src-057'")


def hn_search_url(progress):
    return HN_SEARCH_ENDPOINT+'?'+urlencode({'query':'R9700','tags':'story','hitsPerPage':50,
         'typoTolerance':'false','numericFilters':'created_at_i<='+str(progress['upper']),
         'page':progress['page']})


def hn_search_entries(client,first_response,progress,deadline,candidate_limit):
    """Drain a fixed upper-time search window; persist page/offset separately from checkpoint.

    Every completed window is rescanned next run, so old metadata edits can be found.
    Index omissions and deletions cannot be proved absent and are always disclosed.
    """
    progress=dict(progress); entries=[]; response=first_response; requests=0
    while True:
        data=json.loads(response.body); requests+=1
        if not isinstance(data,dict) or not isinstance(data.get('hits'),list): raise ValueError('HN search response is not a hit page')
        page=data.get('page'); pages=data.get('nbPages'); per_page=data.get('hitsPerPage')
        if any(isinstance(value,bool) or not isinstance(value,int) for value in (page,pages,per_page)) or page!=progress['page'] or pages<0 or not 1<=per_page<=50:
            raise ValueError('invalid HN search pagination')
        hits=data['hits']
        if len(hits)>per_page or progress['offset']>len(hits): raise ValueError('HN search page moved; retain prior checkpoint and retry window')
        progress['approximate']=bool(progress.get('approximate') or data.get('exhaustiveNbHits') is not True)
        progress['reportedHits']=data.get('nbHits'); progress['reportedPages']=pages
        for index in range(progress['offset'],len(hits)):
            if len(entries)>=candidate_limit:
                progress['offset']=index
                return entries,progress,False
            hit=hits[index]
            if not isinstance(hit,dict) or not str(hit.get('objectID','')).isdigit() or 'story' not in hit.get('_tags',[]):
                raise ValueError('invalid HN story identity')
            submitted=date_or_none(hit.get('created_at'))
            if not submitted or int(parse_time(submitted).timestamp())>progress['upper']:
                raise ValueError('HN search returned an invalid date or exceeded its fixed window')
            story_id=str(hit['objectID']); evidence=plain_text(hit.get('story_text') or '')
            # Publication date belongs to the linked HN submission, not its external article.
            entries.append({'title':plain_text(hit.get('title') or '',400),
                            'url':'https://news.ycombinator.com/item?id='+story_id,
                            'publishedAt':submitted,'updatedAt':None,'evidence':evidence,
                            'hnStoryId':story_id,'originUrl':hit.get('url'),'discoveryProvider':HN_SEARCH_PROVIDER})
            progress['offset']=index+1; progress['scanned']=progress.get('scanned',0)+1
        if page+1>=pages:
            progress['offset']=0; progress['completedAt']=now()
            return entries,progress,True
        progress['page']=page+1; progress['offset']=0
        if requests>=4 or len(entries)>=candidate_limit or time.monotonic()+22>deadline:
            return entries,progress,False
        response=client.get(hn_search_url(progress),['hn.algolia.com'],deadline=deadline)


def date_or_none(value):
    if not value: return None
    try: return parse_time(value).isoformat()
    except ValueError:
        try:
            dt=parsedate_to_datetime(value)
            return dt.isoformat() if dt.tzinfo else None
        except (ValueError,TypeError,OverflowError): return None


def parse_feed(body):
    if re.search(br'<!DOCTYPE|<!ENTITY',body,re.I): raise ValueError('DTD and entities are disabled')
    root=ET.fromstring(body)
    entries=root.findall('./channel/item') if root.tag=='rss' else root.findall('{http://www.w3.org/2005/Atom}entry')
    if root.tag not in ('rss','{http://www.w3.org/2005/Atom}feed'): raise ValueError('unsupported feed root')
    result=[]
    for entry in entries:
        def field(name):
            node=entry.find(name)
            if node is None: node=entry.find('{http://www.w3.org/2005/Atom}'+name)
            return ''.join(node.itertext()) if node is not None else ''
        link=field('link')
        if not link:
            links=entry.findall('{http://www.w3.org/2005/Atom}link')
            link=next((node.attrib.get('href','') for node in links if node.attrib.get('rel','alternate')=='alternate'),'')
        result.append({'title':plain_text(field('title'),400),'url':link,
                       'publishedAt':date_or_none(field('pubDate') or field('published')),
                       'updatedAt':date_or_none(field('updated')),
                       'evidence':plain_text(field('description') or field('summary') or field('content'))})
    return result


def as_content(entry,source):
    url=safe_url(entry['url']); key=digest(url)[:20]
    item={'id':'content-'+key,'slug':'source-'+key,'title':entry['title'],
            'summary':'원문 제목과 링크를 수집했습니다. 한국어 요약 검증 대기 중입니다.',
            'kind':'news','tags':['R9700',source['name']], 'sourceUrl':url,'sourceName':source['name'],
            'publishedAt':entry['publishedAt'],'updatedAt':entry.get('updatedAt'),
            'evidenceStatus':'source-metadata; summary-pending',
            'body':'원문에서 대상 GPU, 운영체제, 소프트웨어 버전과 실행 조건을 확인하세요. 이 항목은 수집된 원문 메타데이터이며 자체 실행 결과가 아닙니다.',
            'relatedIds':[], 'sourceContentHash':digest(entry)}
    if entry.get('discoveryProvider'):
        item['discoveryProvider']=entry['discoveryProvider']
        item['evidenceStatus']+='; third-party-index; HN-submission-date'
        item['body']='Algolia HN Search에서 발견한 Hacker News 게시물입니다. 날짜는 HN에 제출된 시각이며 외부 원문의 발행일과 다를 수 있습니다. 원문 주장과 실제 R9700 실행 여부는 별도 확인이 필요합니다.'
        if entry.get('originUrl'):
            try:
                origin=safe_url(entry['originUrl']); item['originalUrl']=origin
                item['body']+='\n\nHN에 연결된 원문: '+origin
            except ValueError: pass
    return item


def retry_due(at,attempt,headers):
    seconds=[300,900,2700][min(attempt,2)]
    retry_after=headers.get('retry-after')
    if retry_after:
        try: seconds=max(seconds,int(retry_after))
        except ValueError:
            try: seconds=max(seconds,int((parsedate_to_datetime(retry_after)-parse_time(at)).total_seconds()))
            except (ValueError,TypeError): pass
    reset=headers.get('x-ratelimit-reset')
    if headers.get('x-ratelimit-remaining')=='0' and reset:
        try: seconds=max(seconds,int(reset)-int(parse_time(at).timestamp()))
        except ValueError: pass
    return (parse_time(at)+timedelta(seconds=seconds)).isoformat()


class JSONLD(HTMLParser):
    def __init__(self): super().__init__(); self.active=False; self.parts=[]; self.items=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type')=='application/ld+json': self.active=True; self.parts=[]
    def handle_data(self,data):
        if self.active: self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.active=False
            try: self.items.append(json.loads(''.join(self.parts)))
            except ValueError: pass


def newegg_price(html,config,event_id):
    """Parse JSON data without executing JavaScript; cross-check the displayed price.

    A standalone read is not approval of unattended retailer collection.
    """
    match=re.search(r'(?:window\.)?__initialState__\s*=\s*',html)
    if not match: raise ValueError('Newegg initial state is absent')
    state,_=json.JSONDecoder().raw_decode(html[match.end():])
    item=state['ItemDetail']; title=item['Description']['Title']
    if not relevant(title) or item['Item'].replace('-','')!=config['sku'].replace('-',''): raise ValueError('Newegg product identity mismatch')
    if item.get('CountryCode')!='USA' or config['currency']!='USD': raise ValueError('Newegg region mismatch')
    price=item.get('FinalPrice')
    visible=re.search(r'class="price-current[^\"]*"[^>]*>.*?\$<strong>([\d,]+)</strong><sup>(\.\d+)</sup>',html,re.S)
    if price is not None and (not visible or float(visible[1].replace(',','')+visible[2])!=float(price)): raise ValueError('Newegg visible and structured prices disagree')
    reported_seller=item.get('Seller',{}).get('SellerName')
    if reported_seller and reported_seller!=config['seller']: raise ValueError('seller changed; a new offer is needed')
    return {**{key:config[key] for key in ('offerId','productId','seller','region','currency','condition','sourceUrl')},
            'id':'price-'+digest([config['offerId'],event_id])[:24],'collectionEventId':event_id,
            'price':float(price) if price is not None else None,'shipping':None,
            'stock':('in_stock' if item.get('Instock') else 'out_of_stock') if isinstance(item.get('Instock'),bool) else 'unknown',
            'observedAt':now(),'sourceBodyHash':digest(html),'observationMethod':'public-page-json-and-visible-price',
            'sellerVerified':bool(reported_seller)}


def compuzone_price(html,config,event_id):
    title=re.search(r'<title>(.*?)</title>',html,re.S|re.I)
    if not title or not relevant(title[1]) or config['sku'] not in html or config.get('distributor','') not in html_module.unescape(title[1]):
        raise ValueError('Compuzone SKU/model/distributor mismatch')
    block=re.search(r'<div class="price_real">(.*?)<span class=[\"\']unit[\"\']>원</span>',html,re.S)
    if not block: raise ValueError('Compuzone visible price field missing')
    visible=re.sub(r'<div[^>]*style=[\"\'][^\"\']*display\s*:\s*none[^\"\']*[\"\'][^>]*>.*?</div>','',block[1],flags=re.S|re.I)
    visible=plain_text(visible).replace(',','').strip()
    regular=re.search(r'\bregularPrice\s*:\s*(\d+)',html)
    if not visible.isdigit() or not regular or int(regular[1])!=int(visible): raise ValueError('Compuzone displayed and structured price disagree')
    return {**{key:config[key] for key in ('offerId','productId','seller','region','currency','condition','sourceUrl')},
            'id':'price-'+digest([config['offerId'],event_id])[:24],'collectionEventId':event_id,
            'price':int(visible),'shipping':None,'stock':'unknown','observedAt':now(),'distributor':config['distributor'],
            'sourceBodyHash':digest(html),'observationMethod':'public-visible-price-and-regularPrice; stock-not-confirmed'}


def aggregate_price(html,config,event_id):
    parser=JSONLD(); parser.feed(html)
    product=next((x for x in parser.items if isinstance(x,dict) and x.get('@type')=='Product' and str(x.get('sku'))==str(config['sku'])),None)
    if not product or not relevant(product.get('name','')): raise ValueError('aggregate product identity missing')
    offer=product.get('offers',{})
    if offer.get('@type')!='AggregateOffer' or offer.get('priceCurrency')!=config['currency']: raise ValueError('not a matching aggregate offer')
    raw=offer.get('lowPrice')
    if not re.fullmatch(r'\d+(?:\.\d+)?',str(raw)): raise ValueError('invalid aggregate price')
    return {**{key:config[key] for key in ('offerId','productId','seller','region','currency','condition','sourceUrl')},
            'id':'price-'+digest([config['offerId'],event_id])[:24],'collectionEventId':event_id,
            'price':float(raw),'shipping':None,'stock':'unknown','observedAt':now(),'distributor':config.get('distributor'),
            'sourceBodyHash':digest(html),'observationMethod':'AggregateOffer.lowPrice','offerCount':int(offer.get('offerCount',0)),
            'aggregation':True,'sellerVerified':False}


def structured_price(html,config,event_id):
    parser=JSONLD(); parser.feed(html)
    def flatten(value):
        if isinstance(value,list):
            for child in value: yield from flatten(child)
        elif isinstance(value,dict):
            yield value
            if '@graph' in value: yield from flatten(value['@graph'])
    product=next((item for root in parser.items for item in flatten(root)
                  if item.get('@type')=='Product' and relevant(item.get('name',''))),None)
    if product is None: raise ValueError('no R9700 Product structured data; no heuristic price guess')
    offers=product.get('offers',[])
    if isinstance(offers,dict): offers=[offers]
    offers=[offer for offer in offers if offer.get('@type') in ('Offer',None)]
    if len(offers)!=1: raise ValueError('ambiguous or aggregate offers cannot identify a seller price')
    offer=offers[0]
    if offer.get('priceCurrency')!=config['currency']: raise ValueError('currency differs from registered offer')
    raw=offer.get('price'); price=None
    if raw is not None:
        if not re.fullmatch(r'\d+(?:\.\d+)?',str(raw)): raise ValueError('unrecognized price format')
        price=float(raw)
    stock={'https://schema.org/InStock':'in_stock','http://schema.org/InStock':'in_stock',
           'https://schema.org/OutOfStock':'out_of_stock','http://schema.org/OutOfStock':'out_of_stock'}.get(offer.get('availability'),'unknown')
    if price is None: stock='price_missing'
    return {**{key:config[key] for key in ('offerId','productId','seller','region','currency','condition','sourceUrl')},
            'id':'price-'+digest([config['offerId'],event_id])[:24],'collectionEventId':event_id,
            'price':price,'shipping':None,'stock':stock,'observedAt':now()}


def configure_public_feeds(store):
    """Explicit bundled scope: published RSS/API metadata and links only, no media/body reuse."""
    with store.db:
        for source_id in PUBLIC_FEEDS:
            store.db.execute("UPDATE sources SET enabled=1,state=CASE WHEN last_success IS NULL THEN 'READY' ELSE state END,policy=? WHERE id=?",
                             (dumps({'access':'public-publisher-feed-or-api','publication':'title-url-date-only',
                                     'checkedAt':now(),'scope':'read-only; no fulltext or media reproduction'}),source_id))
    configure_hn_search(store)


def collect(store,source_id=None,event_id=None,dry_run=False,client=None,budget_seconds=480):
    client=client or SafeClient(); started=time.monotonic(); deadline=started+min(budget_seconds,480)
    event_id=event_id or 'collect-'+digest(now()+str(time.monotonic()))[:20]
    rows=store.rows('SELECT * FROM sources WHERE enabled=1'+(' AND id=?' if source_id else ''),(source_id,) if source_id else ())
    result={'eventId':event_id,'state':'DRY_RUN' if dry_run else 'SUCCESS','sources':[],'new':0,'revised':0,'duplicate':0,'failed':0,'backlog':0}
    if dry_run:
        result['sources']=[{'id':row['id'],'state':row['state']} for row in rows]
        return result
    total_candidates=0
    for row in rows:
        if time.monotonic()+25>deadline:
            result['backlog']+=1; continue
        if row['retry_at'] and parse_time(row['retry_at'])>parse_time(now()):
            result['sources'].append({'id':row['id'],'state':'RETRY_WAIT','dueAt':row['retry_at']}); continue
        if store.db.execute('SELECT 1 FROM source_fetches WHERE source_id=? AND event_id=? AND status IN (\'SUCCESS\',\'NOT_MODIFIED\')',(row['id'],event_id)).fetchone():
            result['sources'].append({'id':row['id'],'state':'ALREADY_COLLECTED'}); continue
        owner=event_id+row['id']
        if not store.acquire('source:'+row['id'],owner):
            result['sources'].append({'id':row['id'],'state':'LOCKED'}); continue
        source=json.loads(row['payload']); at=now(); body_hash=None; http_status=None
        try:
            policy=PUBLIC_FEEDS.get(row['id'])
            prices=store.setting('priceAdapters',[])
            price_config=next((item for item in prices if item['sourceId']==row['id']),None)
            if not policy and not price_config: raise ValueError('no configured adapter')
            endpoint=source.get('fetchEndpoint')
            search_progress=None
            if source['adapter']=='hn-search':
                search_progress=store.setting('hnSearchProgress') or {'upper':int(parse_time(at).timestamp()),'page':0,'offset':0,'scanned':0}
                endpoint=hn_search_url(search_progress)
            if price_config:
                endpoint=price_config['sourceUrl']; hosts=[urlsplit(endpoint).hostname]
                if price_config.get('policyConfirmed') is not True: raise ValueError('price collection policy is not confirmed')
                robots_url='https://'+hosts[0]+'/robots.txt'
                robots_response=client.get(robots_url,hosts,deadline=deadline)
                robots=RobotFileParser(); robots.parse(robots_response.text().splitlines())
                if not robots.can_fetch(AGENT,endpoint): raise ValueError('robots policy blocks this price path')
            else: hosts=policy['hosts']
            headers={}
            if row['etag']: headers['If-None-Match']=row['etag']
            if row['last_modified']: headers['If-Modified-Since']=row['last_modified']
            # Price events always re-observe the offer; an unchanged HTTP document is not a new numeric price.
            if price_config or search_progress: headers={}
            response=client.get(endpoint,hosts,headers,deadline=min(deadline,time.monotonic()+120))
            http_status=response.status; body_hash=digest(response.body)
            entries=[]; gap=None; backlog=False; price_count=0
            if response.status!=304:
                if price_config:
                    parser={'newegg':newegg_price,'compuzone':compuzone_price,'aggregate':aggregate_price}.get(price_config.get('adapter'),structured_price)
                    observation=parser(response.text(),price_config,event_id)
                    with store.db: store.observation(observation)
                    price_count=1
                elif source['adapter'] in ('rss','atom'):
                    entries=parse_feed(response.body)
                elif source['adapter']=='github-releases':
                    releases=json.loads(response.body)
                    if not isinstance(releases,list): raise ValueError('GitHub response is not a release list')
                    entries=[{'title':plain_text(item.get('name') or item['tag_name'],400),'url':item['html_url'],
                              'publishedAt':date_or_none(item.get('published_at')),'updatedAt':None,
                              'evidence':plain_text(item.get('body',''))} for item in releases if not item.get('draft')]
                    gap='Bounded release feed; historical completeness is not verified.'
                elif source['adapter']=='hn-search':
                    entries,search_progress,complete=hn_search_entries(client,response,search_progress,
                         min(deadline,time.monotonic()+100),max(0,200-total_candidates))
                    backlog=not complete
                    gap='Algolia R9700 story query only; unindexed/deleted posts and other terms are outside verified coverage.'
                    if search_progress.get('approximate'): gap+=' Provider reports an approximate hit count.'
                    body_hash=digest({'entries':entries,'progress':search_progress})
                elif source['adapter']=='hn-newstories':
                    ids=json.loads(response.body)
                    if not isinstance(ids,list) or not all(isinstance(item,int) for item in ids): raise ValueError('HN IDs must be integers')
                    cursor=json.loads(row['checkpoint']) if row['checkpoint'] else {}
                    pending=list(dict.fromkeys(cursor.get('pending',[])+[item for item in ids if item not in cursor.get('seen',[])]))
                    batch=pending[:20]; remaining=pending[20:]
                    for item_id in batch:
                        response_item=client.get(f'https://hacker-news.firebaseio.com/v0/item/{item_id}.json',hosts,deadline=min(deadline,started+120))
                        item=json.loads(response_item.body)
                        if item and item.get('type')=='story' and not item.get('dead') and not item.get('deleted'):
                            entries.append({'title':plain_text(item.get('title',''),400),
                              'url':item.get('url') or f'https://news.ycombinator.com/item?id={item_id}',
                              'publishedAt':datetime.fromtimestamp(item['time'],UTC).isoformat() if item.get('time') else None,
                              'updatedAt':None,'evidence':plain_text(item.get('text',''))})
                    cursor={'pending':remaining,'seen':list(dict.fromkeys(batch+cursor.get('seen',[])))[:5000]}
                    backlog=bool(remaining); gap='HN bounded newstories window; older unavailable stories are not claimed complete.'
                else: raise ValueError('unsupported adapter')
                timestamps=[entry['publishedAt'] for entry in entries if entry['publishedAt']]
                if source['adapter']!='hn-search' and row['last_success'] and timestamps and min(timestamps)>row['last_success']:
                    gap='Feed no longer reaches the previous checkpoint; archive backfill unavailable.'
                elif not row['last_success'] and not gap and not price_config:
                    gap='Initial bounded feed; pre-feed archive coverage has not been established.'
            accepted=price_count
            with store.db:
                for entry in entries:
                    if total_candidates>=200:
                        backlog=True; break
                    total_candidates+=1
                    if not relevant(entry['title']+' '+entry['evidence'],policy['kind']): continue
                    try: item=as_content(entry,source)
                    except ValueError: continue
                    cache_key=digest([row['id'],digest(entry),PARSER_VERSION,'no-llm'])
                    state=store.content(item,row['id'],source.get('publisherKey'))
                    store.db.execute('INSERT OR IGNORE INTO processing_cache VALUES(?,?,?)',(cache_key,dumps(item),now()))
                    result[state]+=1; accepted+=1
                checkpoint=row['checkpoint'] if backlog else dumps({'at':at,'bodyHash':body_hash})
                if source['adapter']=='hn-newstories' and response.status!=304: checkpoint=dumps(cursor)
                if source['adapter']=='hn-search' and response.status!=304:
                    store.set_setting('hnSearchProgress',search_progress if backlog else None)
                    if not backlog:
                        checkpoint=dumps({'adapter':'hn-search','provider':HN_SEARCH_PROVIDER,'query':'R9700','typoTolerance':False,
                                          'windowUpper':search_progress['upper'],'scanned':search_progress['scanned'],
                                          'reportedHits':search_progress['reportedHits'],'reportedPages':search_progress['reportedPages'],
                                          'providerExhaustive':not search_progress.get('approximate',False),'completedAt':search_progress['completedAt']})
                successful_prior=store.db.execute("SELECT COUNT(*),COALESCE(SUM(accepted),0) FROM source_fetches WHERE source_id=? AND status IN ('SUCCESS','NOT_MODIFIED')",(row['id'],)).fetchone()
                verified=bool(successful_prior[0]>=1 and successful_prior[1]+accepted>0 and row['published_revision'] and not backlog)
                store.db.execute('UPDATE sources SET state=?,last_attempt=?,last_success=?,checkpoint=?,etag=?,last_modified=?,retry_at=NULL,retry_count=0,coverage_gap=?,automation_verified=? WHERE id=?',
                    ('BACKLOG' if backlog else 'SUCCESS',at,at,checkpoint,response.headers.get('etag') or row['etag'],
                     response.headers.get('last-modified') or row['last_modified'],gap,int(verified),row['id']))
                store.db.execute('INSERT OR REPLACE INTO source_fetches VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (digest([row['id'],event_id]),row['id'],event_id,at,'NOT_MODIFIED' if response.status==304 else 'SUCCESS',http_status,body_hash,len(entries)+price_count,accepted,gap))
                store.db.execute('INSERT INTO source_attempts VALUES(?,?,?,?,?,?,?)',
                    (digest([row['id'],event_id,time.monotonic()]),row['id'],event_id,at,'SUCCESS',http_status,gap))
                store.db.execute("UPDATE jobs SET state='DONE' WHERE id=?",('retry:'+row['id'],))
            result['backlog']+=int(backlog)
            result['sources'].append({'id':row['id'],'state':'BACKLOG' if backlog else 'SUCCESS','discovered':len(entries)+price_count,'accepted':accepted,'coverageGap':gap})
        except (FetchError,ValueError,KeyError,ET.ParseError) as error:
            http_status=getattr(error,'status',None); headers=getattr(error,'headers',{})
            state='BLOCKED_ACCESS' if http_status in (401,403) and headers.get('x-ratelimit-remaining')!='0' else 'FAILED'
            due=retry_due(at,row['retry_count'],headers) if row['retry_count']<3 and state!='BLOCKED_ACCESS' else None
            with store.db:
                store.db.execute('UPDATE sources SET state=?,last_attempt=?,retry_at=?,retry_count=retry_count+1 WHERE id=?',(state,at,due,row['id']))
                store.db.execute('INSERT OR REPLACE INTO source_fetches VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (digest([row['id'],event_id]),row['id'],event_id,at,state,http_status,body_hash,0,0,redact(str(error))))
                store.db.execute('INSERT INTO source_attempts VALUES(?,?,?,?,?,?,?)',
                    (digest([row['id'],event_id,time.monotonic()]),row['id'],event_id,at,state,http_status,redact(str(error))))
                if due: store.db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',('retry:'+row['id'],'source-retry',due,dumps({'sourceId':row['id'],'eventId':event_id}),'WAITING'))
                if price_config:
                    failure={**{key:price_config[key] for key in ('offerId','productId','seller','region','currency','condition','sourceUrl')},
                             'id':'price-'+digest([price_config['offerId'],event_id])[:24],'collectionEventId':event_id,
                             'price':None,'shipping':None,'stock':'fetch_error','observedAt':at,
                             'distributor':price_config.get('distributor'),'quantity':price_config.get('quantity')}
                    store.observation(failure)
            result['failed']+=1; result['sources'].append({'id':row['id'],'state':state,'error':redact(str(error)),'retryAt':due})
        finally: store.release('source:'+row['id'],owner)
    if result['failed']: result['state']='PARTIAL_FAILURE'
    elif result['backlog']: result['state']='BACKLOG'
    result['elapsedSeconds']=round(time.monotonic()-started,3)
    return result
