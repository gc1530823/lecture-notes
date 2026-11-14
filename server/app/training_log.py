"""우리 AI를 만들기 위한 학습 데이터 모으기 (TRAINING_LOG=1 일 때만).

지금 쓰는 큰 모델(Groq gpt-oss-120b 등)에 보낸 요청과 답을 그대로 JSONL로 남긴다.
나중에 scripts/export_training.py가 이것을 사용자가 고친 필기(feedback 표)로 바로잡아 학습 데이터로 만들고,
training/finetune.py가 작은 공개 모델(Qwen2.5-3B 등)을 그 데이터로 미세조정한다 = 큰 모델의 실력을 작은 모델에 옮기기(증류).

- 파일은 서버 안(TRAINING_DIR, 기본 data/training)에만 남고 어디에도 보내지 않는다.
- 어떤 작업(task)인지는 시스템 프롬프트로 알아낸다. 강의 id는 contextvar로 넘겨받는다 (필기 고침과 맞추려고).
"""

import contextvars
import json
import logging
import os
import threading
import time
import uuid

from .config import settings

log = logging.getLogger(__name__)

current_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("training_session", default=None)
_lock = threading.Lock()


def task_name(system: str) -> str:
    """시스템 프롬프트 → 작업 이름. 프롬프트를 바꿔도 이름이 유지되도록 상수와 견준다."""
    from . import llm, note_review, ollama_llm, quiz, study_note

    known = [
        ("annotate", llm.ANNOTATION_SYSTEM), ("summarize", llm.SUMMARY_SYSTEM), ("summarize_page", ollama_llm.PAGE_SUMMARY_SYSTEM),
        ("overview", ollama_llm.OVERVIEW_SYSTEM), ("task_draft", ollama_llm.TASK_DRAFT_SYSTEM), ("task_draft", llm.TASK_SYSTEM),
        ("organize", llm.ORGANIZE_SYSTEM), ("ask", llm.ASK_SYSTEM), ("flashcards", llm.FLASHCARD_SYSTEM),
        ("concepts", llm.CONCEPT_SYSTEM), ("mindmap", llm.MINDMAP_SYSTEM), ("tutor", llm.TUTOR_SYSTEM),
        ("title", llm.TITLE_SYSTEM), ("catch_up", llm.CATCHUP_SYSTEM), ("predict", llm.PREDICT_SYSTEM),
        ("fix_speech", llm.FIX_SPEECH_SYSTEM), ("review_notes", note_review.REVIEW_SYSTEM), ("quiz", ollama_llm.QUIZ_SYSTEM), ("quiz_set", quiz.QUIZ_SET_SYSTEM), ("grade", quiz.GRADE_SYSTEM), ("card_question", quiz.CARD_SYSTEM), ("study_note", study_note.STUDY_NOTE_SYSTEM),
    ]
    for name, prompt in known:
        # 노트 모드 필기처럼 기본 프롬프트 뒤에 규칙을 덧붙인 경우도 같은 작업으로 본다
        if prompt and system.startswith(prompt[:200]):
            return name
    return "other"


def record(system: str, prompt: str, schema: dict, output: dict, model: str) -> None:
    if not settings.training_log:
        return
    entry = {
        "id": uuid.uuid4().hex, "time": time.time(), "task": task_name(system), "model": model,
        "session_id": current_session.get(), "system": system, "prompt": prompt, "schema": schema, "output": output,
    }
    try:
        os.makedirs(settings.training_dir, exist_ok=True)
        path = os.path.join(settings.training_dir, f"raw-{time.strftime('%Y%m')}.jsonl")
        line = json.dumps(entry, ensure_ascii=False)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        # 학습 데이터를 못 남겨도 강의는 계속돼야 한다
        log.exception("학습 데이터를 남기지 못했습니다")
