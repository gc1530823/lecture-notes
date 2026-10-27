# 강의노트 MVP

강의자료(PDF)를 올리고 iPhone으로 강의를 녹음하면, 교수님 설명이 **해당 페이지의 해당 문단 옆에 필기로 자동으로 붙는** 앱입니다. 강의가 끝나면 요약과 퀴즈를 만듭니다.

```
iPhone 앱 (SwiftUI)                        서버 (FastAPI)
 ├ PDF 보기 + 필기 표시        ── REST ──▶  PDF 분석 (블록 좌표·용어)
 ├ 녹음 (m4a, 기기 저장)                     요약·퀴즈 생성 (Claude)
 └ 한국어 받아쓰기 (iOS 음성 인식) ─ WebSocket ─▶  페이지별로 모아서 필기 생성 (Claude)
                                ◀── 새 필기 ──
```

## 수업 중에 일어나는 일

1. 녹음을 시작하면 교수님 말이 자막으로 흐른다 (iOS 음성 인식, 전문용어 힌트 적용).
2. 서버가 받아쓰기로 **지금 설명 중인 페이지를 추적**하고, 화면이 그 페이지로 자동으로 넘어간다.
   - 신호 A: 사용자가 직접 넘긴 페이지 (넘긴 뒤 20초는 가장 크게 믿고, 앱은 그동안 자동 넘김을 멈춘다)
   - 신호 B: 최근 30초 받아쓰기와 페이지 텍스트의 유사도 (글자 2-gram TF-IDF)
   - 신호 C: "다음 장", "앞에서 본 것처럼", "5페이지" 같은 전환 발언
   - 세 신호를 HMM 전방 알고리즘으로 합치고, "강의는 대체로 앞으로 진행된다"는 전이 확률로 튀지 않게 한다.
3. 받아쓰기가 들어오는 즉시 규칙으로 고른 핵심 문장이 **임시 포스트잇**(점선, "AI가 정리 중")으로 바로 뜬다. 80자 또는 8초마다 AI가 정리한 필기가 도착하면 임시 포스트잇을 대신한다 (AI가 실패하면 임시 필기를 그대로 남긴다).
   AI 필기도 **새 필기는 해당 문단 바로 옆에 포스트잇으로 5초간 펼쳐진 뒤** 깃발로 접힌다. 아래 보드에도 쌓인다.
4. 페이지 확신이 낮으면(0.6 미만) 후보 3쪽을 Claude에게 보여 주고 고르게 한다. Claude도 확신하지 못하면 **보류함**에 넣고, 사용자가 한 번 눌러 원하는 페이지에 붙인다.
5. 교수님이 짧게 짚고 지나간 개념에는 **AI 팁** 포스트잇(하늘색, "AI가 덧붙인 내용" 표시)이 붙는다.
6. 강의가 끝나면 요약·퀴즈를 만들고, **웹 검색으로 찾은 추가 자료**("더 알아보기", 출처 링크)를 붙인다.

## 폴더 구성

| 경로 | 내용 |
| --- | --- |
| `server/app/main.py` | REST API와 WebSocket 엔드포인트 |
| `server/app/pdf_parser.py` | PDF를 페이지·텍스트 블록(0~1 좌표)으로 나누고 용어를 뽑음 |
| `server/app/alignment.py` | 자동 슬라이드 정렬 (신호 A·B·C + HMM) |
| `server/app/live_session.py` | 페이지를 추정하며 받아쓰기를 모았다가 필기를 만드는 실시간 세션 |
| `server/scripts/simulate_lecture.py` | iPhone 없이 강의 한 번을 흉내 내는 테스트 클라이언트 |
| `server/app/llm.py` | Claude 호출 (필기, 요약·퀴즈)과 테스트용 가짜 응답 |
| `server/app/db.py` | SQLite 저장소 |
| `ios/LectureNotes/Services/SpeechRecorder.swift` | 녹음 + 실시간 받아쓰기 (말이 끊기면 문장 단위로 확정) |
| `ios/LectureNotes/Services/LectureSocket.swift` | 서버 WebSocket (끊기면 자동 재연결, 못 보낸 메시지 재전송) |
| `ios/LectureNotes/Lecture/` | 강의 화면: 페이지 + 필기 배지 + 필기 목록 |
| `ios/LectureNotes/Summary/SummaryView.swift` | 요약, 퀴즈, 더 알아보기 |
| `ios/LectureNotes/Design/` | 색·포스트잇 디자인 |
| `ios/LectureNotes/Demo/` | 서버 없이 화면을 띄우는 데모 모드 (`-demoScreen lecture` 등) |

## 1. 서버 실행

Python 3.11 이상이 필요합니다. 서버는 세 가지 AI 모드 중 하나로 돕니다.

| `LLM_MODE` | 비용 | 설명 |
| --- | --- | --- |
| `ollama` (기본값) | **무료** | 내 컴퓨터에서 공개 모델(Qwen 등)을 돌린다. 강의 내용이 밖으로 나가지 않는다 |
| `claude` | 유료 | Claude API. 필기 품질이 가장 좋고 웹 검색 추가 자료도 만든다 |
| `fake` | 무료 | 가짜 응답. 화면·기능 개발과 테스트용 |

### 무료 모드 (Ollama)

1. [ollama.com](https://ollama.com)에서 Ollama를 설치하고 실행합니다 (Windows·Mac·Linux).
2. 컴퓨터 메모리에 맞는 모델을 받습니다.

   | 메모리(RAM) | 모델 | 받기 |
   | --- | --- | --- |
   | 8GB | `qwen3:4b` (약 2.5GB) | `ollama pull qwen3:4b` |
   | 16GB 이상 (추천) | `qwen3:8b` (약 5GB) | `ollama pull qwen3:8b` |
   | 그래픽카드 VRAM 16GB 이상 | `qwen3:14b` | `ollama pull qwen3:14b` |

3. 서버를 켭니다.

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip install -r requirements.txt
OLLAMA_MODEL=qwen3:8b .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`http://localhost:8000/health`에 `"llm_mode": "ollama"`가 보이면 준비 완료입니다.

무료 모드의 한계:
- 필기 품질과 속도가 Claude보다 떨어집니다. 그래픽카드가 없으면 필기 하나에 수십 초가 걸릴 수 있습니다.
- 웹 검색을 못 해서 "더 알아보기" 추가 자료는 만들지 않습니다 (링크를 지어내지 않도록).
- AI 팁은 모델 지식으로 만들기 때문에 작은 모델일수록 틀릴 수 있습니다.

### 다른 모드

```bash
LLM_MODE=fake .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000      # 가짜 응답
LLM_MODE=claude ANTHROPIC_API_KEY=sk-ant-... .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

테스트: `.venv/bin/python -m pytest` · 강의 흉내 내기: `.venv/bin/python scripts/simulate_lecture.py`

### Claude 모드 모델 설정

Claude 모드의 기본값은 필기·요약 모두 `claude-opus-5-5`입니다. 기획서의 비용 계획처럼 실시간 필기를 더 싼 모델로 돌리려면 환경변수로 바꿉니다.

```bash
export ANNOTATION_MODEL=claude-haiku-5-5   # 실시간 필기 (강의 1시간에 수십~수백 번 호출)
export SUMMARY_MODEL=claude-sonnet-5-5     # 강의 후 요약·퀴즈 (강의당 1번)
```

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ANNOTATION_EFFORT` / `SUMMARY_EFFORT` | `low` / `medium` | 모델의 생각 깊이 |
| `MIN_CHARS_PER_CALL` | `80` | 받아쓰기가 이 글자 수를 넘으면 필기 생성 |
| `MAX_WAIT_SECONDS` | `8` | 글자 수가 모자라도 이 시간이 지나면 필기 생성 |
| `PAGE_CONFIDENCE` | `0.6` | 페이지 추정 확신이 이보다 낮으면 후보 페이지를 Claude가 고름 |
| `ENABLE_WEB_TIPS` | `1` | 강의 후 웹 검색으로 추가 자료 찾기 (`0`이면 끔) |
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

### Mac 없이 화면 확인하기

push할 때마다 GitHub Actions(macOS)가 앱을 빌드하고, 데모 모드로 화면마다 시뮬레이터 스크린샷과
실시간 필기 동영상(`live.mp4`)을 찍어 `screenshots` 브랜치에 올린다. 빌드 경고·오류는 Actions 주석으로 남는다.

## API 요약

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/documents` | PDF 업로드 (multipart `file`, `title`) → 페이지·블록·용어 |
| GET | `/documents/{id}` | 강의자료 조회 |
| POST | `/sessions` | 강의 세션 시작 (`{"document_id": ...}`) |
| WS | `/sessions/{id}/stream` | 보내기: `page_view`(`initial`), `transcript_final`, `flush` / 받기: `page_estimate`, `annotation_added`, `error` |
| POST | `/sessions/{id}/end` | 강의 종료, 요약·퀴즈 생성 시작 |
| GET | `/sessions/{id}/summary` | `{status, summary}` (status: recording, processing, done, failed) |
| GET | `/sessions/{id}/annotations` | 필기 목록 |
| PATCH / DELETE | `/annotations/{id}` | 필기 수정(`text`)·페이지에 붙이기(`page_no`) / 삭제 |

## MVP에서 일부러 뺀 것 (다음 단계)

- 서버 측 STT와 강의 후 재변환: 지금은 iPhone 음성 인식만 씁니다.
- 필기를 누르면 그 시점의 녹음 재생 (필기마다 `start_ms`는 이미 저장됨)
- 로그인·사용자 구분, PPTX 업로드, PostgreSQL 이전
