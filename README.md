# 강의노트 MVP

강의자료(PDF)를 올리고 iPhone으로 강의를 녹음하면, 교수님 설명이 **해당 페이지의 해당 문단 옆에 필기로 자동으로 붙는** 앱입니다. 강의가 끝나면 요약과 퀴즈를 만듭니다.

```
iPhone 앱 (SwiftUI)                        서버 (FastAPI)
 ├ PDF 보기 + 필기 표시        ── REST ──▶  PDF 분석 (블록 좌표·용어)
 ├ 녹음 (m4a, 기기 저장)                     요약·퀴즈 생성 (Claude)
 └ 한국어 받아쓰기 (iOS 음성 인식) ─ WebSocket ─▶  페이지별로 모아서 필기 생성 (Claude)
                                ◀── 새 필기 ──
```

## 폴더 구성

| 경로 | 내용 |
| --- | --- |
| `server/app/main.py` | REST API와 WebSocket 엔드포인트 |
| `server/app/pdf_parser.py` | PDF를 페이지·텍스트 블록(0~1 좌표)으로 나누고 용어를 뽑음 |
| `server/app/live_session.py` | 받아쓰기를 모았다가 필기를 만드는 실시간 세션 |
| `server/app/llm.py` | Claude 호출 (필기, 요약·퀴즈)과 테스트용 가짜 응답 |
| `server/app/db.py` | SQLite 저장소 |
| `ios/LectureNotes/Services/SpeechRecorder.swift` | 녹음 + 실시간 받아쓰기 (말이 끊기면 문장 단위로 확정) |
| `ios/LectureNotes/Services/LectureSocket.swift` | 서버 WebSocket (끊기면 자동 재연결, 못 보낸 메시지 재전송) |
| `ios/LectureNotes/Lecture/` | 강의 화면: 페이지 + 필기 배지 + 필기 목록 |
| `ios/LectureNotes/Summary/SummaryView.swift` | 요약과 퀴즈 |

## 1. 서버 실행

Python 3.11 이상이 필요합니다.

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# API 키 없이 흐름만 확인 (가짜 필기)
LLM_MODE=fake .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# 실제 Claude로 필기 생성
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

테스트: `.venv/bin/python -m pytest`

### 모델 설정

기본값은 필기·요약 모두 `claude-opus-5-5`입니다. 기획서의 비용 계획처럼 실시간 필기를 더 싼 모델로 돌리려면 환경변수로 바꿉니다.

```bash
export ANNOTATION_MODEL=claude-haiku-5-5   # 실시간 필기 (강의 1시간에 수십~수백 번 호출)
export SUMMARY_MODEL=claude-sonnet-5-5     # 강의 후 요약·퀴즈 (강의당 1번)
```

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ANNOTATION_EFFORT` / `SUMMARY_EFFORT` | `low` / `medium` | 모델의 생각 깊이 |
| `MIN_CHARS_PER_CALL` | `120` | 받아쓰기가 이 글자 수를 넘으면 필기 생성 |
| `MAX_WAIT_SECONDS` | `15` | 글자 수가 모자라도 이 시간이 지나면 필기 생성 |
| `DB_PATH` | `data/lecture_notes.db` | SQLite 파일 위치 |

Opus·Sonnet 모델에는 안전 필터가 요청을 거절할 때 다른 모델로 자동 재시도하는 서버 측 `fallbacks: "default"` 옵션을 켜 두었습니다. 끄려면 `app/llm.py`의 `FALLBACK_MODELS`에서 모델을 빼면 됩니다.

## 2. iPhone 앱 실행

Mac과 Xcode 16 이상이 필요합니다. iOS 17 이상을 지원합니다.

```bash
brew install xcodegen
cd ios
xcodegen            # LectureNotes.xcodeproj 생성
open LectureNotes.xcodeproj
```

1. Xcode에서 Signing & Capabilities의 Team을 내 Apple 계정으로 고릅니다. 번들 ID(`com.example.lecturenotes`)도 내 것으로 바꿉니다.
2. 실행한 뒤 왼쪽 위 톱니바퀴에서 서버 주소를 넣습니다.
   - 시뮬레이터: `http://localhost:8000`
   - 실제 iPhone: 같은 Wi-Fi에 있는 Mac의 IP (예: `http://192.168.0.10:8000`)
3. `+`로 PDF를 올리고, 강의자료를 눌러 "새 강의 녹음하기"를 누릅니다.

> 시뮬레이터는 마이크 입력이 불안정하므로 녹음·받아쓰기는 실제 iPhone에서 확인하세요.

## API 요약

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/documents` | PDF 업로드 (multipart `file`, `title`) → 페이지·블록·용어 |
| GET | `/documents/{id}` | 강의자료 조회 |
| POST | `/sessions` | 강의 세션 시작 (`{"document_id": ...}`) |
| WS | `/sessions/{id}/stream` | 보내기: `page_view`, `transcript_final`, `flush` / 받기: `annotation_added`, `error` |
| POST | `/sessions/{id}/end` | 강의 종료, 요약·퀴즈 생성 시작 |
| GET | `/sessions/{id}/summary` | `{status, summary}` (status: recording, processing, done, failed) |
| GET | `/sessions/{id}/annotations` | 필기 목록 |
| PATCH / DELETE | `/annotations/{id}` | 필기 수정 / 삭제 |

## MVP에서 일부러 뺀 것 (다음 단계)

- 자동 슬라이드 정렬: 지금은 사용자가 보고 있는 페이지에 필기를 붙입니다.
- 서버 측 STT와 강의 후 재변환: 지금은 iPhone 음성 인식만 씁니다.
- 필기를 누르면 그 시점의 녹음 재생 (필기마다 `start_ms`는 이미 저장됨)
- 로그인·사용자 구분, PPTX 업로드, PostgreSQL 이전
