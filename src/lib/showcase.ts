import type { ShowcaseItem } from './data.ts';

// Editorial entries persist independently of the scheduled collection snapshot.
export const curatedShowcase: ShowcaseItem[] = [
  {
    "id": "cat-rescue-wan-20261024",
    "title": "고양이 GPU 구조 · Wan 2.2 I2V 14B",
    "type": "video",
    "url": "/showcase/cat-rescue-3models/wan.mp4",
    "poster": "/showcase/cat-rescue-3models/wan.jpg",
    "description": "항해·난파·헬리콥터 구조를 담은 60초 영상. 전체 제작 약 30~45분 · 예상.",
    "provenance": "creator-reported",
    "model": "Wan 2.2 I2V 14B",
    "tool": "ComfyUI",
    "gpuCount": 2,
    "createdAt": "2026-10-23",
    "sourceUrl": "/showcase/cat-rescue-comparison/",
    "rights": "제작자 요청으로 R9700 Hub 게시",
    "metadata": {
      "제작 환경": "Radeon AI PRO R9700 32GB × 2",
      "영상": "60초 · 512×352 · 12fps",
      "전체 제작 시간": "약 30~45분 · 예상",
      "소리": "별도 합성 효과음·음악",
      "생성 방식": "20스텝 · 각 GPU에서 장면 병렬 생성",
      "근거": "제작자 로컬 ComfyUI 실행 기록·최종 영상 확인",
      "sha256": "984dace07a8017dc03480cfcc2ce117ccdec91d496da9699ec12a707ecc243ed"
    }
  },
  {
    "id": "cat-rescue-h3-20261024",
    "title": "고양이 GPU 구조 · MiniMax H3 FL2VA",
    "type": "video",
    "url": "/showcase/cat-rescue-3models/h3.mp4",
    "poster": "/showcase/cat-rescue-3models/h3.jpg",
    "description": "항해·난파·헬리콥터 구조를 담은 60초 영상. 전체 제작 22분 43초 · 실측.",
    "provenance": "creator-reported",
    "model": "MiniMax H3 FL2VA",
    "tool": "ComfyUI",
    "gpuCount": 2,
    "createdAt": "2026-10-23",
    "sourceUrl": "/showcase/cat-rescue-comparison/",
    "rights": "제작자 요청으로 R9700 Hub 게시",
    "metadata": {
      "제작 환경": "Radeon AI PRO R9700 32GB × 2",
      "영상": "60초 · 512×352 · 24fps",
      "전체 제작 시간": "22분 43초 · 실측",
      "소리": "모델 공동 생성 · 32kHz 스테레오",
      "생성 방식": "20스텝 · GPU 0 생성 / GPU 1 인코더·디코딩",
      "근거": "제작자 로컬 ComfyUI 실행 기록·최종 영상 확인",
      "sha256": "155de713501d713a47c0c131d6c24eb830921c7dac9101aa52710673dc4740a1"
    }
  },
  {
    "id": "cat-rescue-ltx25-20261024",
    "title": "고양이 GPU 구조 · LTX-2.5 Distilled 22B",
    "type": "video",
    "url": "/showcase/cat-rescue-3models/ltx25.mp4",
    "poster": "/showcase/cat-rescue-3models/ltx25.jpg",
    "description": "항해·난파·헬리콥터 구조를 담은 60초 영상. 전체 제작 90분 57초 · 실측, 시험·복구 포함.",
    "provenance": "creator-reported",
    "model": "LTX-2.5 Distilled 22B",
    "tool": "ComfyUI",
    "gpuCount": 2,
    "createdAt": "2026-10-23",
    "sourceUrl": "/showcase/cat-rescue-comparison/",
    "rights": "제작자 요청으로 R9700 Hub 게시",
    "metadata": {
      "제작 환경": "Radeon AI PRO R9700 32GB × 2",
      "영상": "60초 · 512×352 · 24fps",
      "전체 제작 시간": "90분 57초 · 실측, 시험·복구 포함",
      "소리": "모델 공동 생성 · 48kHz 스테레오",
      "생성 방식": "8스텝 · GPU 0 생성 / GPU 1 인코더·디코딩",
      "근거": "제작자 로컬 ComfyUI 실행 기록·최종 영상 확인",
      "sha256": "6807389c46db44ca058f946796e2865cb7a65aa48d5e78668abacf5601b1b50d"
    }
  }
];

