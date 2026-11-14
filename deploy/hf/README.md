---
title: LUNE
emoji: 🌙
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: AI 강의 노트 — Listen. Learn. Remember.
---

# LUNE 서버

녹음하면 강의자료 위에 AI 필기가 붙는 LUNE 의 서버예요. 앱과 웹은 이 서버 주소로 접속해요.

비밀값(Settings › Variables and secrets › New secret):

| 이름 | 내용 |
| --- | --- |
| `GROQ_API_KEY` | Groq 키 (받아쓰기·필기) |
| `INVITE_CODE` | 친구들이 가입할 때 넣는 초대 코드 |
| `HF_TOKEN` | 쓰기 권한 허깅페이스 토큰 (자료를 비공개 저장소 `lune-data` 에 5분마다 백업) |
