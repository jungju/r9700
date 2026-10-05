const evidenceLabels: Record<string,string> = {
  editorial: '편집 요약',
  'linked-primary-source': '1차 출처 연결',
  'editorial-method': '편집 방식 안내',
  'source-directory': '출처 디렉터리 참고',
  'community-reference': '커뮤니티 참고',
  'not-locally-verified': '로컬 실행 미확인',
  'external-benchmark-reference': '외부 측정 참고',
  'external-review': '외부 리뷰',
  'not-locally-reproduced': '로컬 재현 미확인',
  'no-local-generation': '로컬 생성 기록 없음',
  'source-metadata': '원문 정보 수집',
  'summary-pending': '한국어 요약 확인 대기',
  'third-party-index': '제3자 검색 색인',
  'hn-submission-date': 'HN 게시 날짜',
};
const provenanceLabels: Record<string,string> = {
  'verified-local-run': 'R9700 직접 실행 확인',
  'creator-reported': '제작자 R9700 사용 보고',
  'unverified-reference': 'R9700 근거 미확인 참고 자료',
};
const compatibilityLabels: Record<string,string> = {
  'documentation-reference': '문서 참조',
};
const contentKindLabels: Record<string,string> = {
  news: '소식',
  review: '리뷰·사용기',
  guide: '가이드',
  issue: '문제 해결',
  resource: '자료실',
};

export function formatEvidenceStatus(value: string) {
  return value.split(';').map(part => part.trim()).filter(Boolean).map(part => evidenceLabels[part] || '근거 상태 확인 필요').join(' · ') || '근거 상태 확인 필요';
}
export function formatProvenance(value: string) { return provenanceLabels[value] || value.replaceAll('-', ' '); }
export function formatCompatibilityStatus(value: string) { return compatibilityLabels[value] || value.replaceAll('-', ' '); }
export function formatContentKind(value: string) { return contentKindLabels[value] || value; }
