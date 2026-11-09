# 우리 AI 만들기 (완전 무료 · 완전 자동)

지금은 필기·요약·퀴즈를 큰 AI(Groq의 gpt-oss-120b)가 만듭니다. 무료 사용량 안에서는 공짜지만, 한도가 있고 인터넷과 외부 서비스가 필요합니다.
여기서는 **큰 AI가 실제 강의에서 한 일을 모아, 작은 공개 모델에게 똑같이 하도록 가르칩니다** (지식 증류 + 미세조정).
다 만든 모델은 내 컴퓨터의 Ollama로 돌아가서, 키도 한도도 인터넷도 필요 없습니다.

```
강의 녹음 ─▶ 서버 ─▶ 큰 AI(선생님) ─▶ 필기          ① 모으기  TRAINING_LOG=1
                         │                │
                         ▼                ▼ 학생이 고치거나 지움 (feedback 표)
                  data/training/raw-*.jsonl
                         │
                         ▼                               ② 데이터 만들기  scripts/export_training.py
                  training/data/train.jsonl · val.jsonl  (고친 대로 바로잡고, 강의 단위로 나눔)
                         │
                         ▼                               ③ 가르치기  training/finetune.py (Colab 무료 GPU)
                  lecture-notes.gguf (약 2.5GB)
                         │
                         ▼                               ④ 재기  scripts/eval_model.py
                  ollama create lecture-notes ─▶ LLM_MODE=ollama OLLAMA_MODEL=lecture-notes   ⑤ 바꾸기
```

## ⓪ 바로 시작: 연습 강의로 첫 데이터 만들기 (진짜 녹음 없이)

GitHub → Actions → **Make training data** → Run workflow (강의 수 입력, 기본 5).
Groq가 여러 과목의 연습 강의(슬라이드 + 교수님 말투 받아쓰기, 시험 언급·과제·전문용어 포함)를 만들고,
서버에 실시간 강의처럼 흘려보내 필기·요약·플래시카드·예상 문제·튜터 등 모든 작업의 요청·답을 모읍니다.

- 실행할 때마다 `training-data` 브랜치에 쌓입니다 (연습 강의라 개인정보 없음). 하루 10~20개씩 며칠 돌리면 수백 개가 됩니다.
- 실행 결과 페이지 아래 **Artifacts → lecture-notes-training.zip** 에 학습 묶음(train/val + finetune.py + Modelfile + 노트북)이 있습니다.
- 그 zip을 [Colab 노트북](finetune.ipynb)에 올리고 위에서부터 ▶ 를 누르면 ③이 끝납니다.
- 연습 강의만으로 배운 모델은 진짜 수업 말투에 약할 수 있어서, 진짜 강의(①)를 모아 다시 가르치는 것이 다음 단계입니다.

## ① 모으기

서버를 켤 때 `TRAINING_LOG=1`을 넣으면, AI에 보낸 요청과 답이 `server/data/training/raw-YYYYMM.jsonl`에 쌓입니다.
Codespaces라면 저장소 Settings → Secrets and variables → Codespaces에 `TRAINING_LOG` = `1`을 넣거나, 실행할 때 앞에 붙입니다.

```bash
cd server && TRAINING_LOG=1 uvicorn app.main:app --port 8000
```

- 파일은 **서버 안에만** 남고 어디에도 보내지 않습니다. 강의 내용이 들어 있으니 저장소에 올리지 마세요 (`server/data/`는 git에서 빠져 있음).
- 앱에서 필기를 **고치거나, 지우거나, 보류함에서 쪽을 옮기면** 그 기록이 함께 남아 정답을 바로잡는 데 쓰입니다. 틀린 필기를 그냥 두지 말고 고쳐 주는 것이 곧 AI를 가르치는 일입니다.
- 얼마나 모아야 하나: 필기 작업(annotate)만 따지면 **강의 10~20개(요청 수백 개)** 부터 효과가 보이고, 50개 이상이면 안정적입니다.

## ② 데이터 만들기

```bash
cd server && python scripts/export_training.py            # 전부
python scripts/export_training.py --tasks annotate        # 실시간 필기만
```

`training/data/train.jsonl`, `val.jsonl`이 생깁니다. 검증용은 학습에 안 쓴 강의에서 뽑습니다.

## ③ 가르치기 (Google Colab 무료 T4, 1~2시간)

가장 쉬운 방법: [finetune.ipynb](finetune.ipynb)를 Colab에서 열고(파일 → 노트 업로드) 위에서부터 실행. 직접 하려면:

1. [colab.research.google.com](https://colab.research.google.com) → 새 노트 → 런타임 → 런타임 유형 변경 → **T4 GPU**
2. 왼쪽 파일 칸에 `train.jsonl`, `val.jsonl`, `finetune.py`를 올립니다.
3. 셀에서 실행:
   ```
   !pip install -q unsloth
   !python finetune.py --train train.jsonl --val val.jsonl
   ```
   실시간 필기만 먼저 배우게 하려면 `--only annotate`. 바탕 모델은 `--base`로 바꿉니다 (기본 Qwen3-4B-Instruct-2507, Apache-2.0).
4. 끝나면 `lecture-notes-gguf/` 안의 `.gguf` 파일을 내려받습니다 (Google Drive에 복사하면 빠름).

Kaggle Notebooks(무료 GPU 주 30시간)에서도 똑같이 됩니다.

## ④ 재기 → ⑤ 바꾸기

```bash
# 내 컴퓨터 (Ollama 설치: https://ollama.com)
cd training && ollama create lecture-notes -f Modelfile   # Modelfile의 FROM 경로를 받은 .gguf에 맞추기

# 선생님(Groq)과 우리 AI를 같은 검증 데이터로 비교
cd ../server
python scripts/eval_model.py                                         # 지금 설정 (Groq)
LLM_MODE=ollama OLLAMA_MODEL=lecture-notes python scripts/eval_model.py
```

점수(JSON 성공률, 붙인 문단·종류 정확도, 글 비슷함, 필기가 없을 때 조용히 있는지)가 선생님에 가까우면 서버를 이렇게 켭니다:

```bash
LLM_MODE=ollama OLLAMA_MODEL=lecture-notes uvicorn app.main:app --port 8000
```

이후에도 `TRAINING_LOG=1`을 켜 두고 강의가 쌓이면 ②~⑤를 반복해 계속 똑똑해지게 할 수 있습니다.
(우리 AI로 돌리는 동안 모은 데이터는 선생님 답이 아니므로, 다시 가르칠 때는 `model`이 `groq:`인 것만 쓰는 편이 좋습니다.)

## 받아쓰기(Whisper)도?

받아쓰기는 이미 공개 모델(Whisper)이고, 서버에서 `STT_MODE=whisper`로 돌릴 수 있습니다. 강의 용어를 더 잘 알아듣게 하려면
같은 방식으로 녹음 + 고친 받아쓰기를 모아 Whisper를 미세조정할 수 있습니다 (다음 단계).
