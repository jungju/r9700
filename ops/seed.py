"""Editorial starting material checked against the linked publishers on 2026-10-05.

This is a reproducible authored seed, not inferred current software compatibility.
"""
from pathlib import Path
from .common import atomic_json,now,read_json


def build(root):
    registry=read_json(Path(root)/'sources.json')['sources']
    sources={source['id']:source for source in registry}
    def product(id,name,manufacturer,model,source_id,specs):
        return {'id':id,'name':name,'manufacturer':manufacturer,'model':model,'sourceUrl':sources[source_id]['url'],'specs':specs}
    products=[
      product('amd-r9700','AMD Radeon AI PRO R9700','AMD','Radeon AI PRO R9700','src-001',{'아키텍처':'RDNA 4','메모리':'32 GB GDDR6','메모리 인터페이스':'256-bit','메모리 대역폭':'640 GB/s','컴퓨트 유닛':'64','TBP':'300 W','전원':'12V-2x6','버스':'PCIe 5.0 x16','ECC':'Linux에서 지원 (AMD 공식 표기)','보증':'실제 제조사·유통사 조건 확인'}),
      product('gigabyte-r9700','GIGABYTE Radeon AI PRO R9700 AI TOP 32G','GIGABYTE','GV-R9700AI TOP-32GD rev. 1.0','src-011',{'메모리':'32 GB GDDR6','리비전':'1.0','국내 유통':'피씨디렉트 / 제이씨현 상품을 구분하여 확인','보증':'구매처와 유통사 정책 확인'}),
      product('asus-r9700','ASUS Turbo Radeon AI PRO R9700','ASUS','TURBO-AI-PRO-R9700-32G','src-012',{'메모리':'32 GB GDDR6','크기':'266.7 × 111.1 × 40 mm','두께':'2 슬롯','출력':'HDMI 2.1b ×1, DisplayPort 2.1a ×3','권장 PSU':'750 W','보증':'지역별 ASUS 정책 확인'}),
      product('asrock-r9700','ASRock Radeon AI PRO R9700 Creator 32GB','ASRock','R9700 CT 32G','src-014',{'메모리':'32 GB GDDR6','크기':'271 × 112 × 39 mm','두께':'2 슬롯','냉각':'블로어','출력':'DisplayPort 2.1a ×4','설치 여유':'전원 케이블을 위해 길이 방향 30 mm 추가 권장'}),
      product('sapphire-r9700','SAPPHIRE Radeon AI PRO R9700 32GB','SAPPHIRE','Radeon AI PRO R9700 32GB','src-015',{'메모리':'32 GB GDDR6','제품 확인':'공식 제품 페이지 확인','보증':'유통 지역과 판매처 조건 확인'}),
      product('powercolor-r9700','PowerColor Radeon AI PRO R9700','PowerColor','AI PRO R9700 32G-B','src-016',{'메모리':'32 GB GDDR6','제품 확인':'등록된 제조사 링크와 판매처 모델명을 대조','상세 사양':'제조사 페이지 재확인 필요'}),
      product('xfx-r9700','XFX Radeon AI PRO R9700 32GB','XFX','RX-97XPROAIY','src-017',{'메모리':'32 GB GDDR6','냉각':'블로어, 듀얼 슬롯','출력':'DisplayPort 2.1a ×4','크기':'26.7 × 9.9 × 3.5 cm (제조사 estimated)','제품명 주의':'공식 페이지 일부 R9070 오기 존재; 모델 번호·설명 대조'})]
    content=[]
    def article(id,title,summary,kind,tags,source_id,body,related=(),date=None,url=None,status='editorial; linked-primary-source'):
        source=sources[source_id]
        content.append({'id':id,'slug':id,'title':title,'summary':summary,'kind':kind,'tags':tags,'sourceUrl':url or source['url'],
          'sourceName':source['name'],'publishedAt':date,'updatedAt':None,'evidenceStatus':status,'body':body,'relatedIds':list(related)})
    article('r9700-start','R9700 시작하기: 32GB보다 먼저 확인할 것','제품 사양, 운영체제, 실행 도구를 차례로 확인하는 구매·설치 안내.','guide',['입문','R9700','구매 판단'],'src-001',
      'R9700은 RDNA 4 기반의 로컬 AI용 워크스테이션 그래픽 카드입니다. AMD는 32 GB GDDR6와 300 W TBP를 명시합니다. ECC는 Linux 전용으로 표기되어 있으므로 모든 운영체제에서 같다고 가정하지 마세요.\n\n먼저 실행하려는 모델과 프로그램을 정하고 해당 프로그램의 GPU·운영체제 지원표를 확인하세요. 이어서 케이스 길이, 슬롯 간격, 전원 커넥터와 PSU 조건을 대조합니다. 마지막으로 실제 판매 상품의 모델 번호와 유통사, 보증을 확인합니다.\n\n두 장의 합계 메모리와 한 장의 메모리는 구분해서 읽어야 합니다. 분할 지원 여부는 실행 도구와 모델 조건을 따로 확인하세요.',('rocm-environment','product-checklist'))
    article('rocm-environment','ROCm 설치 전 환경 조합 기록하기','Windows·Linux·WSL을 구분하고 버전별 공식 지원표로 이동합니다.','guide',['ROCm','Windows','Linux','WSL','설치'],'src-006',
      'AMD의 Radeon·Ryzen ROCm 문서는 운영체제별 경로와 지원 매트릭스를 제공합니다. 같은 GPU라도 Windows 네이티브, WSL, Linux의 설치 경로와 지원 프레임워크가 같다고 단정할 수 없습니다.\n\n설치 전 OS 빌드, GPU 모델, 드라이버, ROCm, Python, 프레임워크 버전을 한 묶음으로 기록하세요. 문서의 latest 주소는 바뀔 수 있으므로 확인일과 실제 문서 버전도 남겨 두면 문제를 재현하기 쉽습니다.\n\n공식 문서가 설치를 설명한다는 사실과 이 사이트에서 그 조합을 직접 실행했다는 사실은 다릅니다. 현재 표는 공식 문서 진입점이며 자체 GPU 검증 결과가 아닙니다.',('pytorch-guide','llama-cpp-notes'))
    article('product-checklist','제조사 제품 비교: 포트·크기·유통사를 함께 보기','같은 GPU 이름이어도 카드 길이와 출력 구성은 다릅니다.','guide',['구매 판단','ASUS','ASRock','GIGABYTE'],'src-012',
      'ASUS 공식 사양은 Turbo의 크기를 266.7 × 111.1 × 40 mm, 두께를 2 슬롯으로 안내합니다. 출력은 HDMI 1개와 DisplayPort 3개입니다. 구매하려는 카드의 정확한 모델 번호를 공식 사양과 대조하세요.\n\n제품 비교에서는 냉각 방식, 크기, 출력, 전원, 리비전과 국내 유통사를 함께 봅니다. 보증 기간과 배송 조건은 판매 국가와 유통사에 따라 달라질 수 있어 현재 확인한 판매 조건을 우선합니다.\n\n제품 페이지의 권장 PSU 숫자만으로 다중 GPU 시스템의 전원 구성이 충분하다고 판단하지 마세요.',('r9700-start','price-reading'))
    article('price-reading','가격표 읽는 법: 관측 시각과 조건','실제 관측만 누적하고 배송비·재고 미확인은 빈칸으로 남깁니다.','guide',['가격','KR','US','EU','관측'],'src-058',
      '가격 비교의 단위는 GPU 이름만이 아니라 제조사 모델, 판매처, 유통사, 상품 상태, 수량과 통화가 같은 판매 조건입니다. 국내 상품은 피씨디렉트와 제이씨현 같은 유통 차이를 따로 확인하세요.\n\n이 사이트는 수집 시점의 값만 이력에 추가합니다. 과거 가격을 추정해 그리지 않으며 관측 누락을 0원으로 채우지 않습니다. 배송비가 확인되지 않으면 총 구매 비용도 확정할 수 없습니다.\n\n관측 후 12시간을 넘긴 값은 오래된 자료로 표시합니다. 품절과 가격 누락, 접근 실패는 서로 다른 상태입니다. 구매 직전 원 판매 페이지에서 결제 조건과 실제 재고를 확인하세요.',('product-checklist',),status='editorial-method; source-directory')
    article('pytorch-guide','AMD PyTorch 시작 가이드 찾아보기','공식 PDF와 운영체제별 문서를 함께 확인하는 자료 안내.','resource',['PyTorch','ROCm','설치','PDF'],'src-008',
      'AMD가 제공하는 R9700·ROCm·PyTorch 시작 가이드 PDF입니다. 다운로드 전에 공식 배포 도메인과 문서 버전을 확인하세요.\n\n문서의 명령을 적용할 때에는 지원 OS, Python 버전, 드라이버, 패키지 배포 경로를 함께 확인해야 합니다. 기존 환경에 설치하기보다 의존성을 분리한 환경에서 적용 조건을 기록하면 재현에 도움이 됩니다. 이 항목은 공식 자료로 가는 안내이며 현재 호스트의 설치나 추론 성공을 증명하지 않습니다.',('rocm-environment',))
    article('llama-cpp-notes','llama.cpp에서 R9700 실험 기록 읽기','커뮤니티 실행 기록을 모델·빌드·GPU 분할 조건과 함께 읽습니다.','resource',['llama.cpp','LLM','다중 GPU','커뮤니티'],'src-026',
      'llama.cpp 저장소의 R9700 실험 토론을 연결합니다. 사용자 기록은 빌드 커밋, 백엔드, 모델 파일과 양자화, 컨텍스트 길이, GPU 수와 분할 방식에 따라 달라질 수 있습니다.\n\n속도를 비교할 때에는 입력 처리와 토큰 생성, 첫 응답 시간을 구분하고 실패한 실행도 함께 확인하세요. 하나의 성공 사례를 모든 모델 또는 운영체제의 지원으로 확대하지 않습니다. 이 사이트는 연결된 토론을 직접 측정 결과로 표시하지 않습니다.',('benchmark-reading',),status='community-reference; not-locally-verified')
    article('benchmark-reading','벤치마크 비교 전에 맞출 조건','모델·정밀도·컨텍스트·GPU 수가 다른 결과는 그대로 순위를 매기기 어렵습니다.','guide',['벤치마크','vLLM','Linux','다중 GPU'],'src-034',
      'Phoronix는 R9700의 Linux 단일·듀얼 GPU 성능을 다룬 리뷰를 공개했습니다. 이 사이트에서는 해당 자료를 외부 측정으로 구분하며 원문 그래프와 조건을 먼저 확인하도록 안내합니다.\n\n모델 ID와 버전, 정밀도, 컨텍스트, 배치, 엔진, OS와 드라이버를 기록해 비교 조건을 맞추세요. 처리량과 지연시간은 서로 다른 지표입니다. 메모리 부족이나 지원되지 않은 실행을 결과 표에서 빼면 비교가 왜곡될 수 있습니다.\n\n전력을 직접 측정하지 않은 실행은 전력 효율이 개선됐다고 결론내리지 않습니다.',('llama-cpp-notes',),status='editorial; external-benchmark-reference')
    article('phoronix-r9700-review','Phoronix: R9700 Linux 단일·듀얼 GPU 리뷰','vLLM을 포함한 외부 테스트의 조건과 한계를 원문에서 확인하세요.','review',['외부 리뷰','Linux','vLLM','벤치마크'],'src-034',
      'Linux 환경의 R9700 단일·듀얼 GPU를 다룬 Phoronix 리뷰입니다. 페이지별 모델과 비교 대상, 실행 조건을 원문에서 확인할 수 있습니다.\n\n이는 외부 작성자의 측정이며 이 사이트의 자체 재현 결과가 아닙니다. 조건이 다른 리뷰 수치를 하나의 종합 순위로 합치지 않습니다.',('benchmark-reading',),status='external-review; not-locally-reproduced')
    article('therock-releases','TheRock 릴리스에서 확인할 내용','ROCm 빌드 프로젝트의 릴리스와 지원 대상 변경을 추적합니다.','resource',['TheRock','ROCm','릴리스'],'src-021',
      'TheRock은 ROCm의 빌드와 배포 개발을 다루는 공식 저장소입니다. 릴리스 이름만으로 R9700 지원을 단정하지 말고 릴리스 노트의 대상 플랫폼과 GPU 아키텍처를 확인하세요.\n\n이 사이트의 수집기는 Radeon·RDNA 4·gfx1201 관련 단서가 있는 메타데이터를 선별합니다. 릴리스 발견과 실제 설치·추론 검증은 별도로 기록됩니다.',('rocm-environment',))
    article('troubleshooting-record','문제 해결에 필요한 최소 실행 기록','오류 원문과 환경, 마지막 정상 실행을 함께 남기는 방법.','issue',['오류','재현','ROCm','문제 해결'],'src-007',
      '문제가 발생하면 오류 문자열, 발생 단계, 운영체제, 드라이버·ROCm·프레임워크 버전, GPU 모델, 실행 명령을 기록하세요. 비밀 키와 개인 경로는 공유 전에 제거합니다.\n\nGPU가 목록에 보이는 것과 실제 모델이 GPU에서 실행되는 것은 구분해야 합니다. 설치 확인, 장치 검색, 모델 로드, 실제 입력 처리의 어느 단계에서 실패했는지 나누면 원인을 좁히기 쉽습니다.\n\n지원표에 없는 조합을 해결됐다고 표시하지 않습니다. 공식 문서나 동일 조건의 재현 근거가 없는 해결책은 확인 대기로 남깁니다.',('rocm-environment',))
    article('showcase-evidence','R9700 작품의 제작 근거를 확인하는 법','이미지·영상의 모델과 GPU 실행 근거, 게시 권한을 함께 기록합니다.','guide',['작품','ComfyUI','이미지','영상'],'src-030',
      '작품을 재현하려면 결과 이미지 하나 외에도 모델 ID와 버전, 도구·워크플로, 시드, 해상도와 제작 환경이 필요합니다. 영상은 길이·프레임·생성 및 후처리 단계를 구분해서 기록하세요.\n\n자체 제작 확인에는 완료 로그, GPU 식별, 결과 파일 해시를 연결합니다. 제작자가 R9700 사용을 보고한 외부 작품은 제작자 보고로 표시하며, 근거가 없는 참고 결과는 별도로 구분합니다.\n\n현재 제공받은 실제 R9700 결과물은 없습니다. 갤러리의 빈 상태는 구현 오류가 아니며 사이트용 AI 일러스트를 실행 증거 대신 넣지 않습니다.',status='editorial-method; no-local-generation')
    article('r9700-announcement','AMD, COMPUTEX 2025에서 Radeon AI PRO R9700 발표','공식 발표에 담긴 로컬 AI용 제품의 출발점을 확인합니다.','news',['공식 발표','R9700','COMPUTEX'],'src-003',
      'AMD는 COMPUTEX 2025 공식 발표에서 Radeon AI PRO R9700을 공개했습니다. 이 항목은 당시 발표를 보존하는 자료로, 현재 재고나 오늘의 새 출시를 뜻하지 않습니다.\n\n현재 제품 사양은 별도의 공식 제품 페이지에서 확인하고, 지역별 구매 조건은 최신 판매처 관측과 구분해 읽으세요.',('r9700-start',),date='2025-05-20T00:00:00+00:00',url='https://ir.amd.com/news-events/press-releases/detail/1253/amd-introduces-new-radeon-graphics-cards-and-ryzen-threadripper-processors-at-computex-2025')
    checked=now()
    compatibility=[{'id':key,'os':os,'tool':tool,'version':'공식 지원표에서 조합 확인','status':'documentation-reference',
      'detail':detail,'sourceUrl':sources[source_id]['url'],'checkedAt':checked} for key,os,tool,source_id,detail in [
      ('linux-rocm','Linux','ROCm / PyTorch','src-007','GPU·OS·커널·프레임워크 버전별 지원표 확인. 이 사이트의 직접 실행 검증은 미수행.'),
      ('windows-pytorch','Windows','PyTorch / ROCm','src-006','Windows 전용 설치 경로와 지원 매트릭스를 확인하세요. Linux wheel과 혼용하지 않습니다.'),
      ('wsl-rocm','WSL','ROCm','src-006','WSL 호스트 드라이버와 게스트 환경 조건을 함께 확인해야 합니다.'),
      ('llama-reference','OS별 확인','llama.cpp','src-025','빌드 커밋과 GPU 백엔드, 대상 아키텍처 조건을 확인하세요.'),
      ('comfy-reference','OS별 확인','ComfyUI','src-030','PyTorch 환경과 사용한 custom node별 조건을 따로 확인하세요.')]]
    data={'schemaVersion':1,'releaseId':'editorial-seed-20261005','generatedAt':checked,'siteUrl':'https://r9700.jjgo.io','content':content,
      'products':products,'prices':[],'compatibility':compatibility,'showcase':[],
      'sources':[{'id':s['id'],'name':s['name'],'url':s['url'],'category':s['category'],'status':s['evidenceStatus'],'resourceKind':s.get('resourceKind'),'automationVerified':False} for s in registry],
      'operations':{'lastRunAt':None,'lastSuccessAt':None,'nextRunAt':None,'activeSources':0,'sourceCount':len(registry),'state':'SEEDED',
       'notices':['실제 R9700 이미지·영상은 아직 제공되지 않았습니다.','자동 수집 운영 및 공개 배포 상태는 관리자 실행 기록과 구분합니다.']}}
    # Editorial guides may cite the same URL; use explicit source links without cloning source identity in DB.
    from .validation import validate_site
    validate_site(data)
    atomic_json(Path(root)/'data/site-data.json',data)
    return data


if __name__=='__main__':
    build(Path(__file__).resolve().parents[1])
