# R9700 Hub 실행과 도메인 연결

## GitHub Pages 공개 배포

공개 사이트는 https://github.com/jungju/r9700 의 GitHub Actions → Pages로 배포한다. 사용자 지정 도메인은 r9700.jjgo.io, DNS CNAME 대상은 jungju.github.io 이다. `npm run build:pages`가 공개 페이지·검색·가격·갤러리·RSS·사이트맵만 dist-pages에 생성한다. 관리자·서버 API·운영 DB·비밀 설정은 정적 산출물에서 제외한다. 로컬/서버 운영 버전은 기존 `npm run build`로 유지한다.

`.github/workflows/pages.yml`은 main push·수동 실행·UTC 03:17/09:17/15:17/21:17의 6시간 스케줄로 자료를 수집하고 다시 배포한다. KST로는 00:17/06:17/12:17/18:17이며 Actions 혼잡에 따라 시작이 지연될 수 있다. 수집 장부는 매 실행마다 일관된 SQLite artifact로 보존하고 다음 실행에서 복원한다. 이전 artifact 복원이 실패하면 이력을 새로 초기화하지 않고 중단한다.

Pages는 서버 POST·관리자·GPU/AI 작업자를 실행하지 않는다. 공개 사이트의 제보·정정은 GitHub 이슈 작성으로 연결하고, 사용자가 직접 내용을 확인한 뒤 접수한다. 기존 관리자와 민감한 작업은 로컬 또는 별도 운영 서버에서 사용한다. 공개 정적 사이트에서 작동하지 않는 API 버튼을 노출하지 않는다.

로컬 Pages 빌드: `npm run build:pages`. 배포 설정과 실제 HTTPS 결과는 아래 기존 서버 배포 절차와 구분해 기록한다.

사이트 기준 주소는 https://r9700.jjgo.io 이다. 아직 DNS를 연결하지 않았으므로 이 주소에서 공개 접속된다고 보고하지 않는다. 로컬 개발·서버 빌드·운영 엔진 검증과 실제 서버·DNS·외부 계정 연결은 별도 상태다.

## Windows 로컬 실행

Node 24와 Python 3.12를 사용한다. npm 의존성은 package-lock.json으로 고정했다.

```powershell
npm ci
python -m ops.r9700 init
npm run dev
```

http://127.0.0.1:4321 에서 확인한다. 실제 공개 소식 수집과 수동 운영은 다음 명령으로 실행한다.

웹과 6시간 운영 스케줄러를 함께 실행하려면 `npm run local`을 사용한다. 관리자 수집 설정은 `/admin/settings`에서 변경할 수 있다. 이 로컬 명령은 해당 터미널을 닫으면 종료되므로 실제 서비스는 Docker 또는 서버의 서비스 관리자로 실행한다.

```powershell
python -m ops.r9700 collect
python -m ops.r9700 run
python -m ops.r9700 status
```

지속 운영을 시작하려면 웹 서버와 별개 터미널에서 python -m ops.r9700 schedule 을 실행한다. 6시간 정기 운영과 실패 출처 재시도를 처리한다. .local에는 SQLite·공개 스냅샷·작업 기록과 미디어가 저장되며 저장소에 포함하지 않는다.

관리자 사용은 .env.example을 .env로 복사하고 ADMIN_PASSWORD(16자 이상), SESSION_SECRET(32자 이상)을 각각 다른 난수로 설정한 뒤 서버를 다시 시작한다. 기본 관리자 비밀번호는 없다. 키를 공개 스크린샷·로그·저장소에 넣지 않는다. /admin 에서 상태를 보고 제한된 운영 명령을 실행할 수 있다.

## Linux/Docker 배포 준비

```sh
docker compose build
docker compose up -d
docker compose logs --tail=100
curl -f http://127.0.0.1:49700/api/health
```

한 컨테이너 안에서 웹 런타임과 운영 스케줄러를 관리한다. 하나가 종료되면 컨테이너가 재시작된다. 상태는 영속 volume에 보존한다. 운영 비용·외부 채널·GPU 장치 설정이 없는 기능은 비활성 상태로 남긴다. 이 명령은 배포 대상 서버에서 실행한다. 개발 중 다른 프로젝트의 서버·GPU·컨테이너는 변경하지 않는다.

## r9700.jjgo.io 연결 순서

1. 실제 운영 서버와 영속 디스크·외부 백업 위치를 정한다.
2. 해당 서버에서 컨테이너의 내부 상태와 주요 페이지를 확인한다.
3. DNS에 r9700의 A 레코드를 서버 공개 IPv4로 설정한다. IPv6 수신이 확인된 경우에만 AAAA를 추가한다. 프록시 서비스 사용 여부는 실제 서버 환경에 맞춘다.
4. 기존 reverse proxy에 deploy/Caddyfile.example의 해당 호스트 블록을 통합한다. 다른 사이트의 설정을 덮어쓰지 않는다. 호스트 80/443 포트와 인증서 발급 조건을 확인한다.
5. 공개 HTTPS, canonical·RSS·사이트맵, 관리자 쿠키, 모바일 화면, 24시간 4회 운영 기록을 검증한다.

DNS만 연결되어도 운영 데이터·계정·GPU 연결이 자동 완료되는 것은 아니다. DNS와 배포 대상은 아직 미설정이며 이 개발 작업에서 임의 서버에 배포하지 않는다.

자동 코드 배포를 켜기 전 `workers/README.md`의 고정 호스트 컨트롤러와 `ops/README.md`의 격리 수정 작업자를 연결한다. `deploy/Validator.Dockerfile`은 별도로 빌드하고 실제 이미지 digest를 고정해야 한다. 수정 작업자 및 운영 SSR의 권한 분리는 배포 환경에서 확보해야 한다. 고정 배포 명령은 검증된 코드 버전 ID를 `R9700_CODE_RELEASE` 환경에 설정하고 웹을 다시 시작한다. `/api/health`의 releaseId/codeReleaseId는 그 코드 버전, contentReleaseId는 별도의 공개 자료 스냅샷이다. DB 장부는 코드 복구에 포함하지 않는다.

## 외부 설정과 실제 자료

- 홍보: 운영자 소유 계정, 게시·대조 권한, 자동 발행 설정·일일 비용 한도.
- AI·이미지: 실행 공급자·모델·변경 허용 범위·유료 예산·보호된 검증 명령.
- R9700: 명시적 사용권이 있는 장치와 승인된 모델/워크플로·해시·출력 위치·실행 시간 한도.
- 갤러리: 게시 권한과 R9700 제작 근거가 있는 실제 이미지·영상. 장식용 생성 이미지는 작품 제작 증거로 사용하지 않는다.
- 백업·알림: 호스트 밖의 실제 백업 위치와 외부 호스트 상태 감지·운영자 알림 채널.

구현된 기능·실데이터·외부 연결·공개 배포 상태는 ACCEPTANCE.md에서 별도로 기록한다.
