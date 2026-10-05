# 개발 통합 계약

기준 URL은 https://r9700.jjgo.io 이며 DNS는 아직 연결되지 않았다. 개발은 로컬에서 검증하고 배포 구성까지 준비한다. 실제 공개 배포·DNS 변경·외부 홍보 발행·공유 GPU 실행은 수행하지 않는다.

## 소유 범위

- Astra: ops/ Python 패키지, tests/ Python 테스트, data/site-data.json 실제 출처 기반 초기 자료, ops 전용 문서. README.md·sources.json·웹 src/는 수정하지 않는다.
- Luna: src/pages/ 공개 페이지(관리·api·robots·RSS 제외), src/layouts/, src/components/, src/styles/, public/ UI 정적 자산(실제 생성 커버는 부모가 제공). package.json·src/lib/·src/middleware.ts·README.md·sources.json은 수정하지 않는다.
- 부모: package/config, src/lib/, middleware, 관리자·API·RSS·robots, 배포/통합 검증, 계획·진행 문서.

## 공개 데이터 계약

공개 화면은 src/lib/data.ts의 loadSiteData()를 import한다. 동기 함수이며 환경 SITE_DATA_PATH 파일(기본 .local/public/site-data.json)이 있으면 사용하고, 없으면 data/site-data.json을 사용한다. loadSiteData(): SiteData.

SiteData = { schemaVersion:1, releaseId:string, generatedAt:string, siteUrl:string, content:ContentItem[], products:Product[], prices:PriceObservation[], compatibility:Compatibility[], showcase:ShowcaseItem[], sources:SourceSummary[], operations:PublicOperations }.

ContentItem = { id, slug, title, summary, kind:'news'|'review'|'guide'|'issue'|'resource', tags:string[], sourceUrl, sourceName, publishedAt:string|null, updatedAt:string|null, evidenceStatus, body:string, relatedIds:string[], environment?:string[] }. body는 텍스트/제한된 Markdown 데이터이며 외부 MDX를 실행하지 않는다.

Product = { id, name, manufacturer, model, distributor?:string, sourceUrl, specs:Record<string,string> }.

PriceObservation = { id, offerId, productId, seller, region:'KR'|'US'|'EU', currency, price:number|null, shipping:number|null, condition, stock:'in_stock'|'out_of_stock'|'unknown'|'fetch_error'|'price_missing', observedAt, sourceUrl, stale?:boolean, collectionEventId?:string }.

Compatibility = { id, os, tool, version, status, detail, sourceUrl, checkedAt }.

ShowcaseItem = { id, title, type:'image'|'video', url, poster?:string, description, provenance:'verified-local-run'|'creator-reported'|'unverified-reference', model?:string, tool?:string, gpuCount?:number, createdAt?:string, sourceUrl?:string, rights:string, metadata?:Record<string,string> }. 실제 R9700 작품이 없으면 빈 배열이며 생성 장식 이미지는 이 목록에 넣지 않는다.

SourceSummary = { id, name, url, category, status, resourceKind?:string, automationVerified:boolean }.

PublicOperations = { lastRunAt:string|null, lastSuccessAt:string|null, nextRunAt:string|null, activeSources:number, sourceCount:number, state:string, notices:string[] }. 비밀/관리 로그는 공개하지 않는다.

## Python CLI 및 내부 API 계약

작업 폴더 root 기준 python -m ops.r9700 [command] --root <absolute-root>.

필수 command: init, collect, run, status, export, audit, promote, questions, showcase-import. 각 명령은 JSON을 stdout에 출력하고 오류는 stderr에 보내며 실패 시 비0 종료한다. status는 { runs:[], sources:[], questions:[], improvements:[], promotions:[], generationJobs:[], config:{}, summary:{} } 반환. init은 실제 출처 기반 data/site-data.json·sources.json을 등록하고 SQLite를 만든다. collect는 설정된 읽기 전용 공개 경로와 허용된 가격 관측만 수행. run은 6시간 전체 흐름의 수동 실행이다. --dry-run 제공. 재시도/시각·예산·idempotency·권한·비밀 처리에 관한 README 정책을 구현한다.

웹 관리자 작업은 이 CLI를 제한된 인자만으로 실행한다. 자유 셸 또는 임의 경로 인자를 사용자에게 받지 않는다. 관리자 상태 JSON은 loadOpsStatus()로 제공한다. root가 관리자 auth와 Astro routes를 구현한다.

개선 AI·유료 이미지 생성·홍보 계정·GPU 작업자는 미설정 상태를 실제 BLOCKED로 표시한다. 코드 변경은 격리된 runner 계약·fixed validation·hash 검증·release 복구까지 구현하되 미설정 시 실행하지 않는다. 외부 홍보는 초안 및 idempotent delivery 계약을 갖추고 계정 없을 때 보내지 않는다.

## 화면

심플한 한국어 기술 매거진. 소식/가이드/가격 3개 주 메뉴, 검색과 작품 갤러리 항상 발견 가능. home, /news, /guides, /prices, /products, /compatibility, /showcase, /sources, /search, /content/[slug], /about, /requests. 실제 자료/명확한 빈 상태. 가격·작품을 가짜로 채우지 않는다. src/lib/data.ts가 getContentBySlug(slug), formatDate(value), isStale(observation)도 제공한다. price chart는 있는 관측만으로 그리고 null과 공백을 보존한다. canonical/site URL은 import.meta.env.SITE || 'https://r9700.jjgo.io'.

실제 개발 완료·외부 연결·실데이터·DNS/공개 배포는 별도로 보고한다. 같은 워크스페이스에서 병렬 작성하므로 소유 범위를 지킨다.
