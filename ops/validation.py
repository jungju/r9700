import math
import re
from .common import parse_time
from .security import safe_url


def validate_price(price):
    for key in ('id','offerId','productId','seller','region','currency','condition','stock','observedAt','sourceUrl','collectionEventId'):
        if not isinstance(price.get(key),str) or not price[key]:
            raise ValueError(f'missing price field {key}')
    if price['region'] not in ('KR','US','EU') or price['currency'] not in ('KRW','USD','EUR'):
        raise ValueError('unsupported price region/currency')
    if price['stock'] not in ('in_stock','out_of_stock','unknown','fetch_error','price_missing'):
        raise ValueError('invalid stock state')
    for key in ('price','shipping'):
        value=price.get(key)
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (key=='price' and value==0)):
            raise ValueError('price must be a positive finite amount or null')
    if price['stock'] in ('fetch_error','price_missing') and price.get('price') is not None:
        raise ValueError('failed/missing price must remain null')
    parse_time(price['observedAt']); safe_url(price['sourceUrl'])


def validate_site(data):
    if data.get('schemaVersion') != 1 or not data.get('releaseId'):
        raise ValueError('invalid snapshot schema/release')
    safe_url(data['siteUrl']); parse_time(data['generatedAt'])
    for key in ('content','products','prices','compatibility','showcase','sources'):
        if not isinstance(data.get(key),list):
            raise ValueError(f'{key} must be an array')
        ids=[item.get('id') for item in data[key]]
        if None in ids or len(ids)!=len(set(ids)):
            raise ValueError(f'duplicate or missing {key} IDs')
    product_ids={item['id'] for item in data['products']}
    slugs=set()
    content_ids={item['id'] for item in data['content']}
    for item in data['content']:
        for key in ('id','slug','title','summary','sourceUrl','sourceName','evidenceStatus','body'):
            if not isinstance(item.get(key),str):
                raise ValueError(f'invalid content {key}')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',item['slug']) or item['slug'] in slugs:
            raise ValueError('invalid/duplicate slug')
        slugs.add(item['slug'])
        if item['kind'] not in ('news','review','guide','issue','resource'):
            raise ValueError('invalid content kind')
        safe_url(item['sourceUrl'])
        if re.search(r'<\s*(?:script|iframe|object)|\bon\w+\s*=|javascript:',item['body'],re.I):
            raise ValueError('unsafe external body')
        for key in ('publishedAt','updatedAt'):
            if item.get(key): parse_time(item[key])
        if not isinstance(item.get('tags'),list) or not isinstance(item.get('relatedIds'),list):
            raise ValueError('tags and relatedIds must be arrays')
        if any(value not in content_ids for value in item['relatedIds']):
            raise ValueError('related content is absent')
    for item in data['products']:
        safe_url(item['sourceUrl'])
        if not isinstance(item.get('specs'),dict): raise ValueError('missing product specs')
    for price in data['prices']:
        validate_price(price)
        if price['productId'] not in product_ids: raise ValueError('price refers to unknown product')
    for item in data['showcase']:
        if not item.get('rights') or item.get('provenance') not in ('verified-local-run','creator-reported','unverified-reference'):
            raise ValueError('showcase requires rights and provenance')
        if item.get('type') not in ('image','video'): raise ValueError('invalid showcase type')
        if not item['url'].startswith('/media/'): safe_url(item['url'])
    return {'state':'PASS','content':len(data['content']),'products':len(product_ids),'prices':len(data['prices'])}
