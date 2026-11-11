"""역할 나누기 (LLM_MODE=hybrid): 빨라야 하는 수업 중 일은 Groq(선생님), 강의가 끝난 뒤 일은 우리 AI(Ollama).

- 수업 중(몇 초 안에 답해야 함): 실시간 필기 · 방금 뭐라고 · 따라잡기 · 주제 제목 · 칠판 사진 · AI 튜터 → Groq
- 강의 뒤(조금 느려도 됨): 요약·퀴즈 · 쪽 정리 · 플래시카드·개념 · 마인드맵 · 예상 문제 · 과제 초안 · 받아쓰기 교정 → 우리 AI
- 우리 AI가 실패하거나 답이 비면 Groq로 다시 한다 (사용자는 차이를 모른다)

Groq 하루 한도를 강의 뒤 일에 쓰지 않으니, 그만큼 더 많은 강의를 처리하고 학습 데이터도 더 모을 수 있다.
우리 AI가 만든 답은 학습 데이터에 남아도 다시 가르치는 데 쓰지 않는다 (scripts/export_training.py).
"""

import logging

log = logging.getLogger(__name__)

LOCAL_TASKS = {"summarize", "organize_page", "study_page", "mindmap", "predict_questions", "draft_task", "fix_speech",
               "research_tips"}


class HybridLLM:
    def __init__(self, teacher, student) -> None:
        self.teacher = teacher
        self.student = student

    async def warm_up(self) -> None:
        for llm in (self.teacher, self.student):
            try:
                await llm.warm_up()
            except Exception:  # 한쪽이 안 켜져도 서버는 뜬다
                log.warning("AI 준비 실패: %s", type(llm).__name__)

    def __getattr__(self, name: str):
        teacher_method = getattr(self.teacher, name)
        if name not in LOCAL_TASKS or not callable(teacher_method):
            return teacher_method
        student_method = getattr(self.student, name)

        async def call(*args, **kwargs):
            try:
                result = await student_method(*args, **kwargs)
                if result:  # 빈 답(틀만 있는 답을 걸러 낸 결과 포함)이면 선생님에게
                    return result
                log.info("우리 AI 답이 비어 Groq로 다시: %s", name)
            except Exception:
                log.exception("우리 AI 실패, Groq로 다시: %s", name)
            return await teacher_method(*args, **kwargs)

        return call
