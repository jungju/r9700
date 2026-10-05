"""Reproduce the specifically recorded 2026-10-05 one-shot public observations.

Requires raw local evidence already fetched by a human-authorized read-only check.
Does not activate automatic retailer collection or fabricate unavailable regions.
"""
from pathlib import Path
from .collect import aggregate_price,compuzone_price,newegg_price
from .common import atomic_json,digest,dumps,now,read_json
from .publication import export
from .store import Store


def import_evidence(root):
    root=Path(root); registry={x['id']:x for x in read_json(root/'sources.json')['sources']}; event='read-only-price-check-20261005'
    configs=[
      ('src-065','newegg-product.html','utf-8',newegg_price,{'offerId':'newegg-N82E16814131885-us','productId':'powercolor-r9700','seller':'Newegg 상품 페이지 (판매자명 미확인)','region':'US','currency':'USD','sku':'14-131-885','condition':'단일 카드 표시가. 개별 판매자명·배송·세금 미확인. 결제 조건 확인 필요.'}),
      ('src-058','src-058-product.html','utf-8',aggregate_price,{'offerId':'danawa-99714743-aggregate-kr','productId':'gigabyte-r9700','seller':'다나와 가격비교 집계','region':'KR','currency':'KRW','sku':'99714743','distributor':'피씨디렉트','condition':'AggregateOffer 최저가 집계 (관측 시 110개 offer). 개별 판매처 미확인, 판매처 구성 변동 가능. 단일 판매자 가격 추이가 아닙니다.'}),
      ('src-062','src-062-product.html','cp949',compuzone_price,{'offerId':'compuzone-1291984-jchyun-kr','productId':'gigabyte-r9700','seller':'컴퓨존','region':'KR','currency':'KRW','sku':'1291984','distributor':'제이씨현','condition':'제이씨현 단일 카드 일반 판매가. 카드·간편결제 조건부 할인 미적용. 배송·실재고 미확인.'})]
    observations=[]; store=Store(root)
    try:
        for source_id,name,encoding,parser,config in configs:
            path=root/'.local/evidence'/name
            body=path.read_bytes(); observation=parser(body.decode(encoding,errors='strict'),{**config,'sourceUrl':registry[source_id]['url']},event)
            # File mtime is recorded immediately after receipt, not the later import time.
            from datetime import datetime,timezone
            observation['observedAt']=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(timespec='seconds')
            observation['rawBodyHash']=digest(body); observations.append(observation)
            with store.db:
                store.observation(observation)
                store.db.execute('INSERT OR IGNORE INTO source_fetches VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (digest([source_id,event]),source_id,event,observation['observedAt'],'MANUAL_OBSERVATION',200,digest(body),1,1,
                     'Single public read; robots path allowed; unattended automation policy not enabled.'))
        seed=read_json(root/'data/site-data.json')
        existing={x['id']:x for x in seed['prices']}; existing.update({x['id']:x for x in observations}); seed['prices']=list(existing.values())
        atomic_json(root/'data/site-data.json',seed)
        receipt={'observedAt':now(),'observations':observations,'unavailable':[
          {'sourceId':'src-064','stage':'robots','httpStatus':503},
          {'sourceId':'src-068','stage':'robots','httpStatus':403},
          {'sourceId':'src-069','stage':'robots','httpStatus':403}],
          'automaticPriceCollectorsEnabled':0}
        atomic_json(root/'.local/evidence/price-observation-receipt.json',receipt)
        return {'state':'IMPORTED','count':len(observations),'release':export(store),'EU':'BLOCKED_ACCESS'}
    finally: store.close()


if __name__=='__main__': print(dumps(import_evidence(Path(__file__).resolve().parents[1])))
