# R9700 운영 컨트롤러

Python 3.11 이상 표준 라이브러리로 수집·운영 장부·발행을 수행한다. 저장소 루트에서 실행한다. 명령은 JSON을 stdout에, 실패 설명은 stderr에 출력하며 실패 종료 코드는 1이다. `schedule`만 실행마다 JSON 한 줄을 출력한다.

```powershell
python -m ops.r9700 init --root C:/Users/jeong/my/Projects/r9700
python -m ops.r9700 collect --root C:/Users/jeong/my/Projects/r9700
python -m ops.r9700 run --root C:/Users/jeong/my/Projects/r9700 --dry-run
python -m ops.r9700 run --root C:/Users/jeong/my/Projects/r9700
python -m ops.r9700 status --root C:/Users/jeong/my/Projects/r9700
python -m unittest discover -s tests -p test_ops.py
```

`init`은 73개 출처를 등록하고 최초 한 번만 편집 초기 자료를 넣는다. 재초기화가 기존 관측·개정·홍보 장부를 지우지 않는다. 로컬 설정이 없으면 비밀이 없는 `data/operator-defaults.json`을 `.local/operator-config.json`에 최초 복사한다. 기본 설정은 공개 읽기와 robots 경로 확인을 통과한 Newegg·다나와 집계·컴퓨존 가격 어댑터 3개다. 기존 운영자 설정은 덮어쓰지 않는다. 자동화 검증 수는 이 설정 수와 구분하며, 서버의 매 요청에서도 robots와 응답을 다시 확인한다.

## 명령과 저장소

| 명령 | 동작 |
| --- | --- |
| `collect [--source-id ID] [--dry-run]` | 허용된 공개 metadata/RSS/API/가격 어댑터만 수집 |
| `run [--dry-run]` | 수집, 점검, 개선/작품 큐, 홍보, 검증 발행, 온라인 백업 |
| `tick` | 현재 KST 6시간 슬롯을 최대 한 번 실행하고 만기 재시도 처리 |
| `schedule` | 동일 컨트롤러를 30초마다 깨우는 서버용 반복 루프 |
| `export [--dry-run]` | 전체 스키마 검사 후 공개 snapshot 원자적 교체 |
| `audit` | 근거·자료 공백, 개정된 의존 근거 검사; 브라우저 실측과 구분 |
| `questions [--payload-json JSON]` | 질문 목록 또는 근거를 포함한 질문 등록 |
| `promote [--dry-run]` | 유용한 자료의 초안 생성과 명시 설정된 계정 작업자 교환 |
| `submit --payload-json JSON` | 작품/정정 제보를 검토 대기로 등록; 자동 공개 없음 |
| `feedback --payload-json JSON` | 민감 문자열을 제거한 질문 신호 등록 |
| `configure --payload-json JSON` | `siteUrl`, `sourceEnabled`, `promotionDeliveryPaused`만 변경 |
| `showcase-import --input metadata.json` | 권한·실행 근거·디코딩·해시 검증 후 등록 |
| `showcase-revoke --id ID` | 공개 참조 제거와 즉시 snapshot 재발행; 원본 삭제 없음 |
| `generation --action enqueue --payload-json JSON` | 명시적 GPU 작업자 큐 등록 |
| `generation --action poll` | 완료/대기/본인 작업 시간 초과 응답 대조 |
| `improve` | 설정된 격리 수정 작업자의 요청·후보·호스트 응답 처리 |
| `backup [--output 새폴더]` | 온라인 SQLite 백업·고정 소스·미디어 manifest |
| `restore --input 백업폴더 --root 새폴더` | 기존 DB가 없는 별도 폴더에서 복원 |
| `rollback --release-id ID` | 공개 데이터만 이전 정상 release로 교체 |
| `price-correct --id ID --payload-json JSON` | `replacement` 또는 null, `reason`을 정정 장부에 추가 |

`.local/operations.sqlite3`가 운영 DB다. `.local/releases/<releaseId>`에 완전한 공개 JSON과 해시 manifest를 보존하고 `.local/public/site-data.json`을 단일 원자적 교체 지점으로 사용한다. 검색/RSS/사이트맵은 웹이 이 snapshot을 읽어 생성한다. 정상 수집의 `checkpoint`와 `published_revision`을 따로 기록한다. 공개 rollback은 가격·작품 작업·홍보 발송 장부를 되돌리지 않는다.

## 수집 계약

공식 AMD Newsroom RSS, ROCm Atom, TheRock GitHub 릴리스 API, Algolia HN Search의 R9700 검색 API가 기본 read-only 설정이다. HN 검색은 Algolia의 제3자 색인이며 HN 공식 Firebase 원본 API와 구분한다. 기사 본문과 미디어는 복제하지 않는다. 신규 항목은 원문 제목·링크·날짜와 `summary-pending` 상태만 발행한다. 한국어 요약을 실행 사실로 꾸미는 LLM 호출은 없다. 외부 HTML은 텍스트로 제한하고 XML DTD/외부 엔티티를 거부한다.

HTTPS, 허용 도메인, 공개 DNS 주소만 허용한다. DNS의 모든 반환 주소를 검사하고 검사된 IP로 직접 연결하여 DNS 재조회 우회를 막으며 TLS 인증서는 원래 호스트명으로 확인한다. 프록시를 사용하지 않는다. 매 redirect도 재검사하고 최대 3회로 제한한다. 요청 20초, 응답 5 MiB, origin 간 최소 2초, source 시도 120초, main 수집 8분, 신규 후보 최대 200개를 적용한다. 현재 순차 수집으로 글로벌/동일 origin 동시성은 각각 1이다(상한 4/1 이내). source/전체 실행 락은 살아 있는 PID를 heartbeat가 오래됐다는 이유만으로 빼앗지 않는다.

재시도는 실패 뒤 5/15/45분, 최대 3회 추가한다. `Retry-After`와 GitHub reset이 더 길면 우선한다. 재시도 이벤트는 기존 price event ID를 재사용하며 정상 source checkpoint를 변경하지 않는다. retry는 점검/개선/홍보 전체를 재실행하지 않는다. `source_attempts`에 개별 성공/실패를 보존하고 `source_fetches`는 이벤트 최종 결과를 표시한다.

피드 이전 이력은 확인하지 않았다고 `coverage_gap`에 남긴다. 오래된 게시일의 새 URL도 수용하고 원문 데이터 해시가 달라지면 개정을 만든다. HN은 `search_by_date?query=R9700&tags=story&hitsPerPage=50&typoTolerance=false`를 사용하고 고정된 제출 시각 상한으로 페이지를 순회한다. 한 회차 최대 4페이지 및 전체 신규 후보 예산 안에서 처리하며 page/offset/시각 상한을 영속화한다. 미완료 window는 완료 checkpoint를 전진시키지 않고 다음 회차에 이어간다. 완료 후에는 검색 범위를 다시 확인해 오래된 글의 메타데이터 변경도 찾는다. HN 전체 글, 색인 누락·삭제된 글, 다른 검색어까지 수집했다고 주장하지 않으며 provider의 approximate hit count도 coverageGap에 남긴다. HN 게시물의 날짜와 외부 원문의 발행일을 구분한다. 이전 Firebase newstories 대기는 `hnLegacyCheckpoint`에 SUPERSEDED_DISCOVERY로 보존하고 처리 완료로 위장하지 않는다. sources.json의 최초 조사 이력은 유지하고 runtime SQLite adapter만 변경한다. 본문 관련성 없는 R9700S·ATI Radeon 9700 Pro·Ryzen 9700X를 제외한다. `automationVerified`는 반복 수집 2회 이상, 관련 항목 수용 1회 이상, 실제 발행 revision, backlog 없음이 확인된 연결에만 true다. HTTP 200이나 네트워크 연결 수는 이 숫자와 다르다.

## 가격

offer는 제품·판매처·지역·통화·상품 조건·유통사·수량으로 고정한다. 같은 event 재처리는 한 행이며 다음 이벤트는 가격이 같아도 한 행을 추가한다. trigger가 원관측 UPDATE/DELETE를 차단한다. 정정도 append-only이며 같은 offer/event의 수치·상태만 정정한다. 실패는 null/fetch_error로 보존하고 0원으로 바꾸지 않는다. 최근 관측 12시간 경과는 stale다.

가격 어댑터는 매 요청 robots를 확인한다. JSON-LD는 단일 Product/Offer만 일반 판매 조건으로 처리한다. 다나와는 별도 AggregateOffer 어댑터와 명시된 집계 조건을 사용한다. 집계의 판매자 구성이 바뀌는 것을 단일 판매자 가격 변동으로 해석하지 않는다. 컴퓨존은 해당 SKU·유통사·화면 판매가와 regularPrice를 대조하며 숨김 요소/조건부 할인 값을 가격으로 사용하지 않는다. Newegg은 해당 SKU, 미국 region, JSON FinalPrice와 화면 금액을 대조한다. 배송·세금·판매자·재고 미확인은 추정하지 않는다.

2026-10-05 실제 단발 증거는 `.local/evidence/price-observation-receipt.json`에 관측 시각·body hash·수집 방식을 보존했다. 이후 동일 어댑터로 재수집 3곳 성공. EU Geizhals/idealo robots 403, Gprice robots 503은 중단하여 미확인 영역으로 남겼다. 서버를 자동 예약하거나 공개 배포한 증거는 아니다.

## 실제 사이트 점검 연결

데이터 audit의 PASS는 스키마 점검만 뜻한다. 실제 HTTP/브라우저 연동 미설정은 `runtimeChecks`와 `mobileAndPlayback`에 BLOCKED_CONFIG로 표시한다. `audit.httpEnabled=true`일 때 공개 siteUrl의 홈·소식·가이드·가격·검색·작품 경로를 SafeClient로 확인한다. `audit.workerDirectory`가 설정되면 고정 브라우저 작업자에게 현재 releaseId와 http/search/prices/mobile/links/media 6개 점검을 요청한다. 응답의 releaseId와 전체 분모가 일치해야 PASS다. 일부 키 누락을 통과로 처리하지 않는다. 현재 로컬 웹 브라우저 시험 결과는 부모의 별도 검증 기록이며 이 설정을 자동 활성화하지 않는다.

## 미설정 외부 연동

운영자만 `.local/operator-config.json`의 고급 설정을 작성한다. 웹 configure는 자유 명령, 경로, 자격 증명을 받지 않는다. `paidBudget`은 provider/currency/daily/monthly/perRequest를 모두 요구하며 예상 최대액 예약 후 실행한다. 사용량 미확인은 예약을 유지하고 후속 유료 호출을 중지한다. 기본값 null은 무제한이 아니다.

홍보 `promotion`은 enabled, accountVerified, channel, accountId, workerDirectory와 비용 설정을 요구한다. workerDirectory/requests에 idempotencyKey가 고정된 작업을 쓰고 receipts에서 SENT/UNKNOWN/BLOCKED_AUTH와 remoteId를 받는다. UNKNOWN/SENDING은 remote 대조 전 재전송하지 않는다. KST 하루 1건 및 최소 20시간 간격을 동시에 적용한다. 공개 도착 URL 확인 실패, 만료 계정, 비용 미설정은 발송을 막는다. 실제 계정 게시 작업자는 현재 연결하지 않았다. FakePromotionAdapter는 테스트 전용이며 외부 발송이 없다.

GPU `gpu`는 enabled, workerDirectory, devices, workflows, timeoutSeconds를 요구한다. workflows의 각 workflowId에는 modelHash/workflowHash가 필요하다. workerDirectory/lease.json의 owner=`r9700-hub`, state=`OWNED_IDLE`, 유효한 만료 시각·leaseToken·장치 목록을 확인한 뒤 한 건을 비동기 요청한다. busy/소유권 불명은 DEFERRED이며 GPU 자체를 조회하지 않는다. receipt의 jobId/attemptId/leaseToken/deviceIds/modelHash/workflowHash/파일 해시/완료 로그를 대조한다. timeout은 본인 attempt 취소 요청만 남기고 반환 확인 전 재시작하지 않는다. 실제 GPU 실행은 미수행이다.

자체 미디어는 `.local/media` 아래 두며 ffprobe로 실제 디코딩과 크기·영상 길이를 검사한다. 권한 확인, 원작자, 제작 근거가 필요하다. `verified-local-run`은 완료 job과 결과 해시가 일치해야 한다. 미디어 파일 존재만으로 공개하지 않으며 웹은 유효한 권한 manifest를 확인해야 한다. 외부 작품은 명시적인 게시 권한 및 remoteVerified 확인이 필요하다. 초기 실제 작품은 0개다.

## 자동 개선과 검증 경계

근거·대상·수정 가설·검증 방법이 갖춰진 질문을 중요도와 `3×impact+2×evidence+recurrence+age-effort`로 정렬한다. 약한 신호는 변경 근거가 아니며, 같은 실패를 새 근거 없이 재시도하지 않는다. 문제당 2시도, 비긴급 성공 후 14일 유예, 회차당 한 문제를 적용한다. 방문 표본이 없으면 UNMEASURED/UNAVAILABLE이며 기술 통과를 방문 효과로 바꾸지 않는다.

`improvement` 설정은 runnerDirectory, validationImage(`@sha256:` 필수), hostExchangeDirectory, 최초 배포 때 확인한 baselineRelease, runnerCostMode=`free` 또는 유료 비용 예약값을 요구한다. 요청은 runnerDirectory/requests/<id>.json으로 전달하며 보호 경로 해시·허용 경로·문제와 검증 조건만 포함한다. 수정 작업자는 별도의 실제 격리 실행 환경이어야 한다. controller는 해당 작업자를 직접 실행하거나 “격리됨”이라는 boolean을 신뢰하지 않는다. worker receipt `{requestId,candidateId}`가 도착하면 `.local/improvement-inbox/<candidateId>`의 변경을 검사한다.

허용된 공개 UI 파일 최대 5개·변경 200행만 수용한다. ops/tests/tests-web/workers/lib/인증/API/의존성/잠금파일/정책 변경과 삭제·symlink는 거부한다. 신뢰하는 원본에서 stage를 다시 구성하고 확인된 수정만 복사한다. `.local`, `.env*`, node_modules, Git 데이터는 작업 입력에서 제외한다.

검증은 Docker network=none/read-only/cap-drop=ALL/no-new-privileges/비root/자원 한도 안에서만 수행한다. 고정된 `ops/validate_candidate.py`는 Python 테스트·웹 테스트·타입 검사·빌드·고정 mobile 검사 모두를 요구한다. 검증 image에는 보호 lockfile에 맞는 `/opt/node_modules`와 Python, Node, Playwright 브라우저가 있어야 한다. image 미설정 또는 mobile checker 부재는 BLOCKED/FAIL이며 테스트를 생략하지 않는다. 자동 코드 후보를 호스트의 native subprocess로 실행하지 않는다.

검증 완료 artifact는 code-releases에 고정하고 hash와 requiredChecks를 hostExchangeDirectory/requests로 넘긴다. 별도 호스트 컨트롤러가 DEPLOYED/ROLLED_BACK/FAILED receipt와 HTTP/search/prices/mobile 점검을 반환해야 CLOSED가 된다. host controller는 immutable manifest를 확인하고 운영 DB를 rollback하지 않아야 한다. production SSR 프로세스의 비root/권한 분리·운영 비밀/DB 접근 제한은 별도 필수 배포 경계다. 검증 컨테이너나 파일 경로 검사만으로 production SSR을 sandbox했다고 주장하지 않는다.

## 복원과 인수

온라인 SQLite backup, integrity_check, 원관측·개정·홍보·생성 행 수, source/미디어 hash manifest를 저장한다. backup은 미디어 원본을 복제하지 않으므로 별도 매체 보관과 manifest 대조가 필요하다. restore는 새 폴더에만 수행하고 누락 미디어를 비공개로 남기며 모든 홍보를 재대조 대기로 정지한다. source bundle은 복원하지만 웹 재빌드 검증은 호스트의 고정 Node 환경에서 별도로 수행한다. off-host 백업 목적지는 미설정이다. RTO/RPO 목표 달성이나 24시간 4회 운영은 현재 인수하지 않았다.

`tests/test_ops.py`는 A01–A18의 controller 계약을 고정 fixture로 검증한다. 웹 인증·모바일·Range 재생과 실제 외부 계정·GPU·공개 배포는 별도 인수 결과를 따른다. 테스트 fixture는 공개 초기 자료에 섞이지 않는다.
