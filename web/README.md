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
