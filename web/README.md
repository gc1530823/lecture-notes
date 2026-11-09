# 강의노트 웹 프론트 (새 버전)

React + TypeScript + Vite. Figma 디자인(`design/`)을 바탕으로 만들고, 서버(`server/`)의 API와 연동합니다.
지금 서버에 붙어 있는 웹앱(`server/app/static/`)은 기능 확인용 시제품이고, 이 프론트가 완성되면 바꿉니다.

```bash
npm install
npm run dev          # http://localhost:5173 (API 요청은 localhost:8000 서버로 넘어간다, API_SERVER로 바꿀 수 있다)
npm run build
npm run api:sync     # 서버 API가 바뀌면: OpenAPI 명세를 다시 뽑고 TypeScript 타입(src/api/schema.d.ts)을 만든다
```

API는 `src/api/client.ts`의 `api`로 부른다. 경로·요청 모양이 서버와 다르면 타입 검사에서 걸린다.

## 화면

| 주소 | 화면 | Figma |
| --- | --- | --- |
| `#/` | 자료 목록 · PDF 올리기 · 노트 수업 만들기 | 03 디자인 / 1 |
| `#/doc/:id` | 자료 상세 · 지난 강의 | — |
| `#/doc/:id/session/:sid/notes` | 필기 다시 보기 (슬라이드는 쪽별 포스트잇, 노트 수업은 모눈 노트) | 2, 3 |
| `#/doc/:id/session/:sid/study` | 공부하기: 요약 · 퀴즈 · 플래시카드 · 개념 · 마인드맵 · 암기 · AI 튜터 | 4 |
| `#/doc/:id/session/:sid/glossary` | 용어 사전 | 6 |
| `#/doc/:id/exam` | 시험 예상 지도 | 5 |
| `#/doc/:id/lecture[/:sid]` | 강의 화면: 녹음 · 실시간 필기(형광펜·깃발·포스트잇) · 노트 수업 · 방금 뭐라고 · 따라잡기 · 용어 카드 · 보류함 | 2, 3 |

서버에서 바로 쓰기: `npm run build` 후 서버를 켜면 `http://localhost:8000/web/` 에서 열립니다 (기존 웹앱은 `/app/`).
아직 기존 웹앱에만 있는 것: 정리 PDF 만들기, 필기 눌러 녹음 듣기, 자막 모드, 과제 상세·초안. 옮기면 `/` 를 새 앱으로 바꿉니다.
색·간격·글자는 `src/styles/tokens.css`(Figma 변수와 같은 이름), 부품은 `src/components/ui.tsx`에 있습니다.
