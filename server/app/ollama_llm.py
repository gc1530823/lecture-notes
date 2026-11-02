"""무료 모드: 내 컴퓨터에서 도는 Ollama의 공개 모델(Qwen, Gemma 등)로 필기·요약·퀴즈를 만든다.

Ollama의 /api/chat에 JSON 스키마를 format으로 넘기면 그 형식대로 답한다.
프롬프트와 스키마는 Claude 모드와 같은 것을 쓴다.
"""

import json
import logging
import re

import httpx

from .config import settings
from .llm import (
    ANNOTATION_SCHEMA,
    ANNOTATION_SYSTEM,
    ASK_SCHEMA,
    CATCHUP_SCHEMA,
    CATCHUP_SYSTEM,
    ASK_SYSTEM,
    ORGANIZE_SCHEMA,
    ORGANIZE_SYSTEM,
    PREDICT_SCHEMA,
    PREDICT_SYSTEM,
    TASK_SCHEMA,
    TITLE_SCHEMA,
    TITLE_SYSTEM,
    LLMError,
    MINDMAP_SCHEMA,
    MINDMAP_SYSTEM,
    STUDY_KINDS,
    TUTOR_SCHEMA,
    TUTOR_SYSTEM,
    _mindmap_prompt,
    _tutor_prompt,
    clean_predictions,
    clean_study,
    _annotation_prompt,
    _ask_prompt,
    _catchup_prompt,
    _organize_prompt,
    _task_prompt,
)

log = logging.getLogger(__name__)

# 필드 설명을 "필드: 설명" 꼴로 쓰면 작은 모델이 그 설명을 값으로 베끼므로, 할 일만 말로 쓴다
PAGE_SUMMARY_SYSTEM = """대학 강의 한 페이지의 슬라이드 텍스트, 교수님이 한 말(받아쓰기), 필기를 읽고 복습 자료를 만듭니다.

1. 이 페이지에서 배운 내용을 2~3문장으로 요약해 summary에 씁니다. 실제 개념 이름과 설명을 넣어야 합니다.
2. 이 페이지 내용으로 4지선다 퀴즈 한 문항을 만들어 quiz에 씁니다.
   question은 실제 질문, choices는 실제 보기 4개(정답 1개, 그럴듯한 오답 3개), answer_index는 정답 보기의 번호(0~3),
   explanation은 왜 그 답인지 한 문장입니다.

주어진 내용만 사용하고 한국어로 씁니다."""

PAGE_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "quiz": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "choices": {"type": "array", "items": {"type": "string"}},
                "answer_index": {"type": "integer"},
                "explanation": {"type": "string"},
            },
            "required": ["question", "choices", "answer_index", "explanation"],
        },
    },
    "required": ["summary", "quiz"],
}

TASK_DRAFT_SYSTEM = """학생이 수업 중에 받은 과제를 빨리 끝낼 수 있게 돕습니다. 과제 요구사항과 강의 내용(슬라이드, 교수님 말, 필기)을 받습니다.

1. 교수님 요구사항(분량, 형식, 꼭 넣을 내용, 마감)을 하나도 빠뜨리지 않고 나눠 checklist에 한 줄씩 씁니다.
2. 답안이나 레포트를 어떤 순서로 쓸지 outline에 한 줄씩 씁니다.
3. 학생이 바로 고쳐 쓸 수 있는 실제 초안을 draft에 씁니다. 수업 중 과제면 짧게, 레포트면 여러 문단으로 씁니다.
   강의에서 나온 개념·예시·용어를 먼저 쓰고, 강의에 없는 내용은 널리 알려진 사실만 씁니다.
4. 초안이 근거로 삼은 강의자료 페이지 번호를 sources에 넣습니다.

한국어로 씁니다."""

OVERVIEW_SYSTEM = """대학 강의의 페이지별 요약을 읽고, 강의 전체에서 무엇을 배웠는지 3~5문장으로 이어지는 글을 써서 overview에 넣습니다.
실제 개념 이름을 넣고, 한국어로 씁니다."""

OVERVIEW_SCHEMA = {"type": "object", "properties": {"overview": {"type": "string"}}, "required": ["overview"]}

# 지시문·틀을 그대로 베낀 답 ("2~3문장 핵심 요약", "문항 텍스트", "옵션1", "해설 텍스트")
TEMPLATE_TEXT = re.compile(r"\d\s*~\s*\d\s*문장|\d\s*문장\s*이내|핵심\s*요약$|전체\s*요약$|문항\s*텍스트|해설\s*텍스트|"
                           r"^(옵션|보기|선택지)\s*\d+$|^(질문|요약|해설|설명)$")


def _real_text(value) -> bool:
    return isinstance(value, str) and len(value.strip()) >= 8 and not TEMPLATE_TEXT.search(value.strip())


def _quiz_ok(quiz) -> bool:
    if not isinstance(quiz, dict):
        return False
    choices = quiz.get("choices")
    return (_real_text(quiz.get("question")) and isinstance(choices, list) and len(choices) == 4
            and all(isinstance(c, str) and c.strip() and not TEMPLATE_TEXT.search(c.strip()) for c in choices)
            and len({c.strip() for c in choices}) == 4
            and isinstance(quiz.get("answer_index"), int) and 0 <= quiz["answer_index"] < 4
            and isinstance(quiz.get("explanation"), str))


def _task_draft_ok(data: dict) -> bool:
    lists = [data.get("checklist"), data.get("outline")]
    return (_real_text(data.get("draft")) and all(isinstance(items, list) and items for items in lists)
            and not any(TEMPLATE_TEXT.search(str(item)) for items in lists for item in items))


def _page_summary_ok(data: dict) -> bool:
    # 요약이 진짜면 받는다 (퀴즈만 틀이면 그 문항만 뺀다)
    return _real_text(data.get("summary"))


class OllamaLLM:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # 작은 컴퓨터에서는 답이 느릴 수 있어 넉넉하게 기다린다
        self.client = httpx.AsyncClient(base_url=settings.ollama_url, timeout=httpx.Timeout(600, connect=5),
                                        transport=transport)

    async def _chat(self, system: str, prompt: str, schema: dict, context_tokens: int,
                    temperature: float = 0.2) -> dict:
        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            # 생각 모드가 있는 모델(Qwen3 등)도 바로 답하게 해서 실시간 필기를 빠르게 한다
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_ctx": context_tokens},
        }
        try:
            response = await self.client.post("/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMError(f"Ollama에 연결할 수 없습니다 ({settings.ollama_url}). Ollama 앱이 켜져 있는지 확인해 주세요.") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Ollama 응답이 너무 오래 걸립니다. 더 작은 모델을 써 보세요.") from exc
        if response.status_code == 404:
            raise LLMError(f"모델 {settings.ollama_model}이 없습니다. `ollama pull {settings.ollama_model}`을 먼저 실행해 주세요.")
        if response.status_code >= 400:
            raise LLMError(f"Ollama 오류 ({response.status_code}): {response.text[:200]}")
        content = response.json().get("message", {}).get("content", "")
        if not content:
            raise LLMError("Ollama 응답이 비어 있습니다.")
        return json.loads(content)

    async def warm_up(self) -> None:
        """서버를 켤 때 모델을 메모리에 미리 올려, 첫 필기가 늦지 않게 한다."""
        try:
            await self.client.post("/api/generate", json={"model": settings.ollama_model, "keep_alive": "30m"})
            log.info("Ollama 모델 준비됨: %s", settings.ollama_model)
        except httpx.HTTPError:
            log.warning("Ollama 모델을 미리 올리지 못했습니다 (%s)", settings.ollama_url)

    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict]) -> dict:
        data = await self._chat(ANNOTATION_SYSTEM, _annotation_prompt(candidates, transcript, existing_tasks),
                                ANNOTATION_SCHEMA, context_tokens=4096)
        return {"annotations": data.get("annotations", []), "tasks": data.get("tasks", [])}

    async def draft_task(self, task: dict, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        data = await self._chat_checked(TASK_DRAFT_SYSTEM, _task_prompt(task, pages, segments, annotations),
                                        TASK_SCHEMA, 32768, _task_draft_ok)
        if data is None:
            raise LLMError("모델이 초안 대신 빈 틀만 만들었어요. 다시 눌러 주세요.")
        return data

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        """작은 모델은 요약·퀴즈 전체를 한 번에 시키면 지시문을 그대로 베껴 쓴다("2~3문장 핵심 요약", "옵션1").
        그래서 페이지마다 요약 + 퀴즈 한 문항을 따로 받고, 전체 요약은 페이지 요약으로 마지막에 만든다."""
        page_results = []
        for page in pages:
            speech = " ".join(s["text"] for s in segments if s["page_no"] == page["page_no"])
            if not speech:
                continue
            notes = [a for a in annotations if a["page_no"] == page["page_no"] and not a["pending"]]
            data = await self._chat_checked(PAGE_SUMMARY_SYSTEM, _organize_prompt(page, speech, notes),
                                            PAGE_SUMMARY_SCHEMA, 8192, _page_summary_ok)
            if data is None:
                continue
            quiz = data.get("quiz") if _quiz_ok(data.get("quiz")) else None
            weight = 2 if any(a["type"] in ("exam", "emphasis") for a in notes) else 1
            page_results.append((page["page_no"], data["summary"].strip(), quiz, weight))
        if not page_results:
            raise LLMError("페이지 요약을 만들지 못했습니다.")

        lines = "\n".join(f"- {no}쪽: {summary}" for no, summary, _, _ in page_results)
        data = await self._chat_checked(OVERVIEW_SYSTEM, f"<page_summaries>\n{lines}\n</page_summaries>",
                                        OVERVIEW_SCHEMA, 8192, lambda d: _real_text(d.get("overview")))
        overview = data["overview"].strip() if data else " ".join(s for _, s, _, _ in page_results[:3])

        # 시험·강조 필기가 붙은 페이지의 문항을 먼저 내고, 최대 10문항
        ranked = sorted((r for r in page_results if r[2]), key=lambda r: -r[3])[:10]
        quiz = [{"page_no": no, **q} for no, _, q, _ in sorted(ranked, key=lambda r: r[0])]
        return {"overview": overview,
                "pages": [{"page_no": no, "summary": summary} for no, summary, _, _ in page_results],
                "quiz": quiz}

    async def _chat_checked(self, system: str, prompt: str, schema: dict, context_tokens: int, ok) -> dict | None:
        """답이 틀(빈칸·지시문 베끼기)이면 온도를 올려 한 번 더 받고, 그래도 아니면 None."""
        for temperature in (0.2, 0.6):
            try:
                data = await self._chat(system, prompt, schema, context_tokens, temperature)
            except json.JSONDecodeError:
                continue
            if ok(data):
                return data
            log.warning("모델 답이 틀만 있어 다시 받습니다: %s", str(data)[:120])
        return None

    async def research_tips(self, summary: dict) -> list[dict]:
        # 로컬 모델은 웹 검색을 못 해서 링크를 지어낼 수 있으므로, 추가 자료는 만들지 않는다
        return []

    async def organize_page(self, page: dict, speech: str, notes: list[dict]) -> list[str]:
        # 페이지 하나씩 보내므로 작은 모델과 짧은 문맥으로도 된다
        data = await self._chat(ORGANIZE_SYSTEM, _organize_prompt(page, speech, notes), ORGANIZE_SCHEMA,
                                context_tokens=8192)
        return [p for p in data.get("points", []) if isinstance(p, str) and p.strip()]

    async def ask(self, question: str, page: dict, recent_speech: str) -> dict:
        return await self._chat(ASK_SYSTEM, _ask_prompt(question, page, recent_speech), ASK_SCHEMA,
                                context_tokens=4096)

    async def predict_questions(self, page: dict, speech: str, notes: list[dict]) -> list[dict]:
        data = await self._chat_checked(
            PREDICT_SYSTEM, _organize_prompt(page, speech, notes), PREDICT_SCHEMA, 8192,
            lambda d: bool(clean_predictions(d)) and all(_real_text(q["question"]) for q in clean_predictions(d)))
        return clean_predictions(data) if data else []

    async def catch_up(self, slides: list[dict], speech: str) -> list[str]:
        data = await self._chat(CATCHUP_SYSTEM, _catchup_prompt(slides, speech), CATCHUP_SCHEMA, context_tokens=8192)
        return [p for p in data.get("points", []) if isinstance(p, str) and p.strip()]

    async def title_topic(self, speech: str) -> str:
        data = await self._chat(TITLE_SYSTEM, f"<speech>\n{speech[-3000:]}\n</speech>", TITLE_SCHEMA, context_tokens=4096)
        return str(data.get("title", "")).strip()

    async def study_page(self, kind: str, page: dict, speech: str, notes: list[dict]) -> list[dict]:
        system, schema, key = STUDY_KINDS[kind]
        data = await self._chat_checked(system, _organize_prompt(page, speech, notes), schema, 8192,
                                        lambda d: bool(clean_study(kind, d.get(key, [])))
                                        and all(_real_text(" ".join(i.values())) for i in clean_study(kind, d.get(key, []))))
        return clean_study(kind, data.get(key, [])) if data else []

    async def mindmap(self, title: str, pages: list[dict]) -> dict:
        return await self._chat(MINDMAP_SYSTEM, _mindmap_prompt(title, pages), MINDMAP_SCHEMA, context_tokens=8192)

    async def tutor(self, context: str, messages: list[dict]) -> dict:
        return await self._chat(TUTOR_SYSTEM, _tutor_prompt(context, messages), TUTOR_SCHEMA, context_tokens=8192,
                                temperature=0.4)
