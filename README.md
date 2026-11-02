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
7. 수업 중 **"🙋 방금 뭐라고?"** 버튼으로 바로 묻는다. "쉽게 다시 설명해 줘", "예시 하나만"처럼 고르거나 직접 적으면,
   최근 2분 동안의 설명과 지금 슬라이드를 근거로 답해서 관련 문단 옆에 **질문 포스트잇**(분홍)으로 붙인다.
   교수님 설명에 없는 내용은 "(교수님 설명 외)"로 표시한다. 정리 PDF에도 들어간다.
8. **🎯 시험 예상 지도**: 그 강의자료로 들은 모든 강의를 모아, 페이지마다 시험에 나올 만한 정도를 색으로 보여 준다.
   교수님이 시험에 나온다고 한 말, 시험·강조 필기, 수업 중 질문, 설명한 시간, 여러 강의에서 다시 다룬 페이지를 점수로 매기고
   ("교수님이 시험에 나온다고 함 2번 · 설명 6분"처럼) 이유를 붙인다. 점수가 높은 3쪽은 AI가 예상 문제·모범 답안·출제 이유를 만든다.
9. AI가 놓친 실수는 규칙으로 바로잡는다 (`app/text_fix.py`).
   받아쓰기에서 첫 자음만 잘못 들은 전문용어("유런" → "뉴런")는 강의자료의 용어로 고치고,
   "중간고사에 나온다"는 필기는 AI가 다른 종류로 골랐어도 '시험'으로 맞춘다.
10. 📄 버튼으로 **강의 정리 PDF**를 만든다. 요약이 아니라 전체 정리다. 페이지마다
   - 필기가 붙은 문단에 형광펜과 번호 깃발을 그린 슬라이드
   - 번호에 맞춘 포스트잇 필기
   - AI가 그 페이지에서 교수님이 한 설명을 빠짐없이 항목으로 정리한 **정리 노트** (시험 언급은 ★시험)
   - 교수님 설명 원문(받아쓰기)
   를 넣고, 끝에 보류함 필기와 과제를 붙인다. 한글은 함께 넣은 나눔고딕(OFL)으로 심는다.
   정리는 페이지 하나씩 AI에게 보내므로 작은 무료 모델로도 되고, 받아쓰기·필기가 그대로인 페이지는 다시 만들 때 전에 만든 정리를 쓴다.

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

Python 3.11 이상이 필요합니다. 서버는 네 가지 AI 모드 중 하나로 돕니다.

| `LLM_MODE` | 비용 | 설명 |
| --- | --- | --- |
| `groq` (`GROQ_API_KEY`가 있으면 기본값) | **무료 사용량 안에서 무료** | Groq 클라우드. 받아쓰기(Whisper large-v3-turbo)와 필기·요약(gpt-oss-120b)이 빠르다. 녹음·받아쓰기가 Groq로 간다 |
| `ollama` (키가 없으면 기본값) | **무료** | 내 컴퓨터에서 공개 모델(Qwen 등)을 돌린다. 강의 내용이 밖으로 나가지 않지만, 그래픽카드가 없으면 느리다 |
| `claude` | 유료 | Claude API. 필기 품질이 가장 좋고 웹 검색 추가 자료도 만든다 |
| `fake` | 무료 | 가짜 응답. 화면·기능 개발과 테스트용 |

### Groq 모드 (빠름, 무료 사용량)

1. https://console.groq.com 에 가입하고 API Keys에서 키를 만든다.
2. 키를 넣는다. **채팅·코드에 붙이지 말고** 아래 설정 화면에만 넣는다.
   - Codespaces: GitHub → Settings → Codespaces → Secrets → `GROQ_API_KEY` (저장소 `lecture-notes` 선택)
   - 녹음 정리 워크플로: 저장소 → Settings → Secrets and variables → Actions → `GROQ_API_KEY`
3. 서버를 다시 켜면 받아쓰기와 AI가 모두 Groq로 바뀐다 (`/health`의 `llm_mode`가 `groq`).

무료 등급은 파일 하나에 25MB까지라, 서버가 녹음을 16kHz 모노 mp3로 바꾼 뒤 10분씩 나눠 보낸다.
사용량 한도(분당·하루 요청 수)에 걸리면 Groq가 알려 준 시간만큼 기다렸다가 다시 보낸다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | 필기·요약 모델 |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | 녹음 파일 받아쓰기 모델 (조금 느려도 더 정확) |
| `GROQ_LIVE_WHISPER_MODEL` | `whisper-large-v3-turbo` | 실시간 받아쓰기 모델 (빠름) |

**녹음 하나를 GitHub에서 바로 정리하기**: `inbox/<이름>` 브랜치에 강의자료 PDF와 녹음 파일을 올리고,
Actions → Process recording → Run workflow에 이름을 넣으면 `result/<이름>` 브랜치에
정리 PDF·받아쓰기·필기·요약·퀴즈·과제가 올라온다 (`scripts/process_recording.py`).

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

## 2. 웹앱으로 쓰기 (Mac·앱스토어 없이, 무료)

서버를 켜면 같은 주소에서 웹앱이 열린다: `http://<서버 주소>:8000/app/`

- **iPhone**: Safari로 열고 공유 → "홈 화면에 추가"를 누르면 앱처럼 쓸 수 있다.
- **받아쓰기는 Whisper**: 녹음 중 마이크 소리(16kHz)를 서버로 보내면, 서버가 말이 끊기는 곳(0.7초 침묵, 길어도 10초)마다 잘라
  Whisper로 받아쓰고 바로 페이지 추적·필기로 넘긴다. 소리는 서버에 `세션-n.wav`로도 저장된다.
  마이크를 쓸 수 없는 브라우저에서는 내장 음성 인식으로 바꾼다.
- **안드로이드·PC**: Chrome으로 연다.
- 녹음 중에는 화면 꺼짐 방지(Wake Lock)를 켠다. **iPhone은 화면이 꺼지거나 다른 앱으로 가면 웹페이지의 받아쓰기가 멈춘다** (Apple 제한).
  화면을 다시 켜면 자동으로 이어 받아쓰고, 빠진 시간을 알려 준다.
- **화면을 꺼 둘 수업은 '음성 메모'로 녹음**하고, 끝난 뒤 자료 화면의 "녹음 파일로 정리하기"로 올린다.
  서버가 Whisper(무료)로 받아쓰고, 실시간 강의와 같은 방식으로 페이지 추적·필기·과제·요약·퀴즈를 만든다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `WHISPER_MODEL` | `small` | 녹음 파일 받아쓰기 모델 (`base`는 빠르고 덜 정확, `medium`은 느리고 더 정확) |
| `STT_MODE` | `whisper` | `fake`로 두면 가짜 받아쓰기 (화면 개발용) |
| `UPLOAD_DIR` | `data/uploads` | 올린 PDF·녹음 파일 저장 위치 |

### 자료가 사라지지 않게 (Codespaces)

Codespace는 지워지거나 오래 안 쓰면 없어질 수 있다. 그래서 `.devcontainer/start.sh`가
- 켜질 때 자료(DB)가 없으면 이 저장소의 `data-backup` 브랜치에서 되살리고 (`python scripts/backup.py --restore`),
- 켜져 있는 동안 10분마다 바뀐 자료(DB + 올린 PDF)를 `data-backup` 브랜치에 올린다 (`python scripts/backup.py`).

녹음 파일은 크고 받아쓰기가 이미 DB에 있어 올리지 않는다. 정리 PDF도 언제든 다시 만들 수 있어 올리지 않는다.
**저장소가 공개(public)면 백업도 공개된다.** 강의 내용을 지키려면 저장소를 비공개로 두자.

## 3. iPhone 앱 실행 (Mac이 있을 때)

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

## 사용한 오픈소스 자료

- 아이콘: [Phosphor Icons](https://phosphoricons.com) duotone (MIT) — `server/app/static/icons.svg`, 라이선스는 `server/app/static/vendor/phosphor/LICENSE`
- PDF 보기: pdf.js (Apache-2.0), 한글 글꼴: 나눔고딕 (OFL-1.1)

## API 요약

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/documents` | PDF 업로드 (multipart `file`, `title`) → 페이지·블록·용어 |
| GET | `/documents` | 저장된 강의자료와 강의 목록 |
| GET / DELETE | `/documents/{id}` | 강의자료 조회 / 그 강의·녹음까지 모두 삭제 |
| POST | `/sessions` | 강의 세션 시작 (`{"document_id": ...}`) |
| WS | `/sessions/{id}/stream` | 보내기: `page_view`(`initial`), `transcript_final`, `flush`, 바이너리 16kHz PCM(Whisper) / 받기: `heard`, `page_estimate`, `annotation_preview`, `annotation_added`, `task_added`, `error` |
| POST | `/sessions/{id}/end` | 강의 종료, 요약·퀴즈 생성 시작 |
| GET | `/sessions/{id}/summary` | `{status, summary}` (status: recording, processing, done, failed) |
| GET | `/sessions/{id}/annotations` | 필기 목록 |
| GET | `/documents/{id}/exam-map` | 시험 예상 지도 (페이지별 점수·이유, 상위 페이지 예상 문제) |
| POST | `/documents/{id}/exam-questions` | 상위 페이지 예상 문제 만들기 시작 |
| POST | `/sessions/{id}/ask` | 수업 중 질문 (`{"question", "page_no"}`) → 질문 필기(`type: qa`) |
| PATCH / DELETE | `/annotations/{id}` | 필기 수정(`text`)·페이지에 붙이기(`page_no`) / 삭제 |
| POST | `/sessions/{id}/notes-pdf` | 강의 정리 PDF 만들기 시작 (`{status, done, total}`) |
| GET | `/sessions/{id}/notes-pdf/status` | 만들기 상태 (none, building, ready, failed) |
| GET | `/sessions/{id}/notes-pdf` | 만든 정리 PDF 받기 |

## MVP에서 일부러 뺀 것 (다음 단계)

- 필기를 누르면 그 시점의 녹음 재생 (필기마다 `start_ms`는 이미 저장됨)
- 로그인·사용자 구분, PPTX 업로드, PostgreSQL 이전
