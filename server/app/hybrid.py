"""역할 나누기 (LLM_MODE=hybrid): Groq(선생님)와 우리 AI(Ollama)를 함께 써서 한도 때문에 멈추지 않게 한다.

- 수업 중(몇 초 안에 답해야 함): 실시간 필기 · 방금 뭐라고 · 따라잡기 · 주제 제목 · 칠판 사진 · AI 튜터 → Groq
- 강의 뒤(조금 느려도 됨): 요약·퀴즈 · 쪽 정리 · 플래시카드·개념 · 마인드맵 · 예상 문제 · 과제 초안 · 받아쓰기 교정 → 우리 AI
  (HYBRID_LOCAL_FIRST=0 이면 강의 뒤 일도 Groq가 먼저: 우리 AI를 아직 안 깔아 바탕 모델만 있을 때)
- 우리 AI가 실패하거나 답이 비면 Groq로 다시 한다 (사용자는 차이를 모른다)
- Groq가 한도에 걸리면(하루 한도처럼 오래 기다려야 할 때) 기다리지 않고 우리 AI가 대신 한다. 한도가 풀릴 때까지는
  Groq에 묻지도 않는다 → 수업 중 필기가 한도 때문에 멈추지 않는다 (우리 AI는 더 느리고 덜 정확하다)

우리 AI가 만든 답은 학습 데이터에 남아도 다시 가르치는 데 쓰지 않는다 (scripts/export_training.py).
"""

import inspect
import logging
import os
import time

log = logging.getLogger(__name__)

LOCAL_TASKS = {"summarize", "make_quiz", "quiz_set", "study_note", "organize_page", "study_page", "mindmap", "predict_questions", "draft_task", "fix_speech",
               "research_tips"}
TEACHER_MAX_WAIT = 12.0  # Groq가 이보다 오래 기다리라고 하면 우리 AI에게 넘긴다 (분당 한도의 짧은 기다림은 그냥 기다림)


class HybridLLM:
    def __init__(self, teacher, student, local_first: bool | None = None) -> None:
        self.teacher = teacher
        self.student = student
        self.local_first = os.getenv("HYBRID_LOCAL_FIRST", "1") != "0" if local_first is None else local_first
        self.teacher_until = 0.0   # 이 시각까지는 Groq 한도가 안 풀린다
        self.student_calls = 0     # 우리 AI가 대신 한 횟수 (상태 표시·시험용)
        try:
            teacher.max_wait = TEACHER_MAX_WAIT
        except AttributeError:
            pass

    async def warm_up(self) -> None:
        for llm in (self.teacher, self.student):
            try:
                await llm.warm_up()
            except Exception:  # 한쪽이 안 켜져도 서버는 뜬다
                log.warning("AI 준비 실패: %s", type(llm).__name__)

    def limited(self) -> bool:
        return time.monotonic() < self.teacher_until

    def __getattr__(self, name: str):
        teacher_method = getattr(self.teacher, name)
        if not inspect.iscoroutinefunction(teacher_method):
            return teacher_method
        student_method = getattr(self.student, name, None)
        local = name in LOCAL_TASKS and self.local_first and student_method is not None

        async def ask_teacher(*args, **kwargs):
            """Groq에게. 한도면 우리 AI가 대신 (대신할 수 없는 일이면 한도 오류 그대로)."""
            from .groq import GroqLimit

            if not self.limited():
                try:
                    return await teacher_method(*args, **kwargs)
                except GroqLimit as exc:
                    self.teacher_until = time.monotonic() + min(max(exc.wait, 30.0), 3600.0)
                    log.warning("%s → 우리 AI가 대신 합니다: %s", exc, name)
                    if student_method is None:
                        raise
            elif student_method is None:
                return await teacher_method(*args, **kwargs)
            self.student_calls += 1
            return await student_method(*args, **kwargs)

        async def call(*args, **kwargs):
            if not local:
                return await ask_teacher(*args, **kwargs)
            try:
                result = await student_method(*args, **kwargs)
                if result:  # 빈 답(틀만 있는 답을 걸러 낸 결과 포함)이면 선생님에게
                    return result
                log.info("우리 AI 답이 비어 Groq로 다시: %s", name)
            except Exception:
                log.exception("우리 AI 실패, Groq로 다시: %s", name)
            if self.limited():
                from .llm import LLMError

                raise LLMError("Groq 한도가 아직 안 풀렸고 우리 AI도 답하지 못했습니다")
            return await teacher_method(*args, **kwargs)

        return call
