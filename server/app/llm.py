"""Claude 호출: 실시간 필기, 강의 후 요약·퀴즈, 웹 검색으로 찾은 추가 자료."""

import json
import logging
import re
from typing import Protocol

import anthropic

from .config import settings

log = logging.getLogger(__name__)

# tip = 강의에 직접 나오지 않은, AI가 덧붙이는 배경지식·공부 팁
ANNOTATION_TYPES = ["explanation", "example", "emphasis", "exam", "notice", "tip"]
# in_class = 수업 시간 안에 하는 것, homework = 숙제, report = 레포트·에세이, exam_prep = 시험 준비
TASK_KINDS = ["in_class", "homework", "report", "exam_prep"]

# 서버 측 fallbacks를 받는 모델. 다른 모델(예: Haiku)로 바꾸면 이 옵션을 보내지 않는다.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

ANNOTATION_SYSTEM = """당신은 대학 강의를 듣는 학생 대신 강의자료 위에 필기를 해 주는 조교입니다.

입력으로 후보 슬라이드들(페이지 번호, 텍스트 블록 번호와 내용, 이미 쓴 필기)과 교수님의 새 발언(음성 인식 결과)을 받습니다.
새 발언에서 학생이 슬라이드 옆에 적어 둘 만한 내용만 골라 필기로 만드세요.

페이지 고르기:
- 후보가 하나면 그 페이지에 씁니다.
- 후보가 여럿이면 발언이 설명하는 내용과 가장 맞는 페이지를 page_no에 넣습니다.
- 어느 페이지 이야기인지 확실하지 않으면 page_no에 -1을 넣습니다. 억지로 고르지 마세요.

필기 규칙:
- 슬라이드에 이미 적혀 있는 내용, 이미 쓴 필기와 같은 내용은 쓰지 않습니다.
- 발언에 없는 내용을 지어내지 않습니다. 음성 인식 오류로 보이는 단어는 슬라이드의 용어로 바로잡습니다.
- 필기 하나는 한국어 두 줄(약 60자) 이내로, 학생 노트처럼 간결하게 씁니다.
- block_id에는 그 필기와 가장 관련 있는 블록 번호를 넣고, 맞는 블록이 없으면 -1을 넣습니다.
- type은 다음 중 하나입니다.
  - explanation: 슬라이드에 없는 보충 설명이나 풀이 과정
  - example: 교수님이 든 예시나 사례
  - emphasis: "중요하다", "꼭 기억하라" 같은 강조
  - exam: "시험에 나온다", "출제한다" 같은 시험 관련 발언
  - notice: 과제, 일정, 공지, 질문과 답변
  - tip: 교수님이 짧게 언급하고 지나간 개념에 대해, 학생이 이해하는 데 꼭 도움이 되는 배경지식이나 공부 팁.
    교수님 발언이 아니라 당신이 덧붙이는 내용입니다. 확실히 맞는 내용일 때만, 한 번에 최대 1개만 씁니다.
- 잡담, 인사, 필기할 가치가 없는 발언뿐이면 빈 목록을 반환합니다.

과제 뽑기 (tasks):
- 교수님이 학생에게 무언가를 하라고 요구하면 tasks에 넣습니다: 수업 중 활동("지금 5분 동안 써 보세요"), 숙제, 레포트, 발표, 시험 준비.
- 이미 뽑은 과제(existing_tasks)와 같은 것은 다시 넣지 않습니다. 요구사항이 추가되면 새 과제로 넣지 말고 무시합니다.
- kind: in_class(수업 시간 안에 하는 것) | homework | report | exam_prep
- title: 한 줄 제목. instructions: 교수님이 말한 요구사항(주제, 분량, 형식, 제출 방법)을 빠짐없이.
- due_text: 마감을 교수님이 말한 그대로("다음 주 금요일까지", "수업 끝나기 전"). 말하지 않았으면 빈 문자열.
- 과제를 뽑아도 notice 필기는 그대로 함께 씁니다."""

ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_no": {"type": "integer"},
                    "block_id": {"type": "integer"},
                    "type": {"type": "string", "enum": ANNOTATION_TYPES},
                    "text": {"type": "string"},
                },
                "required": ["page_no", "block_id", "type", "text"],
                "additionalProperties": False,
            },
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": TASK_KINDS},
                    "title": {"type": "string"},
                    "instructions": {"type": "string"},
                    "due_text": {"type": "string"},
                },
                "required": ["kind", "title", "instructions", "due_text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["annotations", "tasks"],
    "additionalProperties": False,
}

TASK_SYSTEM = """당신은 수업 중에 받은 과제를 빨리 끝낼 수 있게 돕는 조교입니다.
과제 요구사항, 강의자료 페이지 텍스트, 받아쓰기, 필기를 받습니다.

만들 것:
- checklist: 교수님 요구사항을 빠짐없이 나눈 확인 목록 (분량, 형식, 포함할 내용, 마감)
- outline: 답안·레포트의 구성 (각 항목 한 줄)
- draft: 바로 고쳐 쓸 수 있는 초안. 수업 중 과제면 짧게, 레포트면 요구 분량에 맞춰 문단으로.
  강의에서 나온 개념·예시·용어를 우선 쓰고, 강의에 없는 내용은 일반적으로 알려진 사실만 씁니다.
- sources: 초안이 근거로 삼은 강의자료 페이지 번호들

학생이 본인 말로 고쳐 제출할 초안이므로, 핵심 논리가 분명하고 고치기 쉬운 문장으로 씁니다. 한국어로 씁니다."""

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "checklist": {"type": "array", "items": {"type": "string"}},
        "outline": {"type": "array", "items": {"type": "string"}},
        "draft": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["checklist", "outline", "draft", "sources"],
    "additionalProperties": False,
}

SUMMARY_SYSTEM = """당신은 대학 강의를 복습용으로 정리하는 조교입니다.
강의자료의 페이지별 텍스트, 페이지별 받아쓰기, 강의 중 만든 필기를 받습니다.

만들 것:
- overview: 강의 전체 요약 (5문장 이내)
- pages: 내용이 있는 페이지마다 핵심 요약 (2~3문장)
- quiz: 복습 퀴즈 5~10문항. 시험(exam)·강조(emphasis) 필기가 붙은 페이지를 우선 출제합니다.
  - 각 문항은 보기 4개(choices), 정답 번호(answer_index, 0부터 시작), 해설(explanation), 출처 페이지(page_no)를 가집니다.

강의자료와 받아쓰기에 있는 내용만 사용하고, 한국어로 씁니다."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"page_no": {"type": "integer"}, "summary": {"type": "string"}},
                "required": ["page_no", "summary"],
                "additionalProperties": False,
            },
        },
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_no": {"type": "integer"},
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["page_no", "question", "choices", "answer_index", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "pages", "quiz"],
    "additionalProperties": False,
}

TIPS_SYSTEM = """당신은 대학생의 복습을 돕는 조교입니다. 강의 요약을 보고 웹 검색으로 믿을 만한 추가 자료를 찾아 주세요.

- 강의의 핵심 개념 2~4개를 골라, 개념마다 학생에게 도움이 될 자료(공식 문서, 대학 강의 노트, 교과서, 위키백과 등) 1개를 찾습니다.
- 각 자료에 대해 한국어로 2문장 이내의 설명(text)을 씁니다: 무엇을 더 알 수 있는지, 강의 내용과 어떻게 이어지는지.
- 실제로 검색해서 열어 본 페이지의 URL만 씁니다. URL을 지어내지 마세요.
- 마지막 답변은 아래 형식의 JSON 하나만 ```json 코드 블록으로 씁니다.

```json
{"tips": [{"page_no": 1, "title": "자료 제목", "text": "설명", "url": "https://..."}]}
```"""

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict]) -> dict: ...

    async def draft_task(self, task: dict, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict: ...

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict: ...

    async def research_tips(self, summary: dict) -> list[dict]: ...


def _annotation_prompt(candidates: list[dict], transcript: str, existing_tasks: list[dict] | None = None) -> str:
    """candidates: [{"page_no", "blocks": [{id, text}], "existing": [{type, text}]}]"""
    parts = []
    for page in candidates:
        block_lines = "\n".join(f"[{b['id']}] {b['text']}" for b in page["blocks"]) or "(텍스트 없음)"
        existing_lines = "\n".join(f"- ({a['type']}) {a['text']}" for a in page["existing"]) or "(없음)"
        parts.append(
            f'<slide page_no="{page["page_no"]}">\n<blocks>\n{block_lines}\n</blocks>\n'
            f"<existing_notes>\n{existing_lines}\n</existing_notes>\n</slide>"
        )
    tasks = "\n".join(f"- {t['title']}" for t in existing_tasks or []) or "(없음)"
    return "\n\n".join(parts) + f"\n\n<existing_tasks>\n{tasks}\n</existing_tasks>\n\n<new_speech>\n{transcript}\n</new_speech>"


def _summary_prompt(pages: list[dict], segments: list[dict], annotations: list[dict]) -> str:
    parts = []
    for page in pages:
        no = page["page_no"]
        speech = " ".join(s["text"] for s in segments if s["page_no"] == no)
        notes = "\n".join(f"- ({a['type']}) {a['text']}" for a in annotations if a["page_no"] == no)
        parts.append(
            f'<page no="{no}">\n<slide>\n{page["text"]}\n</slide>\n'
            f"<speech>\n{speech or '(없음)'}\n</speech>\n<notes>\n{notes or '(없음)'}\n</notes>\n</page>"
        )
    unmatched = " ".join(s["text"] for s in segments if s["page_no"] is None)
    if unmatched:
        parts.append(f"<speech_without_page>\n{unmatched}\n</speech_without_page>")
    return "\n\n".join(parts)


def _task_prompt(task: dict, pages: list[dict], segments: list[dict], annotations: list[dict]) -> str:
    request = (f"<task kind=\"{task['kind']}\" due=\"{task['due_text']}\">\n{task['title']}\n"
               f"{task['instructions']}\n</task>")
    return request + "\n\n" + _summary_prompt(pages, segments, annotations)


def _tips_prompt(summary: dict) -> str:
    pages = "\n".join(f"- {p['page_no']}쪽: {p['summary']}" for p in summary.get("pages", []))
    return f"<overview>\n{summary.get('overview', '')}\n</overview>\n<pages>\n{pages}\n</pages>"


def _check_stop(response) -> None:
    if response.stop_reason == "refusal":
        raise LLMError("모델이 요청을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise LLMError("응답이 max_tokens에서 잘렸습니다.")


def _response_json(response) -> dict:
    _check_stop(response)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise LLMError("응답에 텍스트가 없습니다.")
    return json.loads(text)


def parse_tips(text: str) -> list[dict]:
    """답변 끝의 ```json 블록에서 tips를 꺼내고, http(s) URL이 있는 항목만 남긴다."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    if not blocks:
        raise LLMError("추가 자료 응답에 JSON이 없습니다.")
    tips = json.loads(blocks[-1]).get("tips", [])
    keys = ("page_no", "title", "text", "url")
    return [
        {k: t[k] for k in keys}
        for t in tips
        if isinstance(t, dict) and all(k in t for k in keys) and str(t["url"]).startswith(("http://", "https://"))
    ]


class ClaudeLLM:
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic()

    @staticmethod
    def _request(model: str, effort: str, system: str, prompt: str, schema: dict | None, max_tokens: int) -> dict:
        output_config: dict = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        params = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": output_config,
        }
        if model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict]) -> dict:
        params = self._request(
            settings.annotation_model,
            settings.annotation_effort,
            ANNOTATION_SYSTEM,
            _annotation_prompt(candidates, transcript, existing_tasks),
            ANNOTATION_SCHEMA,
            max_tokens=8000,
        )
        response = await self.client.beta.messages.create(**params)
        return _response_json(response)

    async def draft_task(self, task: dict, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        params = self._request(settings.summary_model, settings.summary_effort, TASK_SYSTEM,
                               _task_prompt(task, pages, segments, annotations), TASK_SCHEMA, max_tokens=32000)
        async with self.client.beta.messages.stream(**params) as stream:
            response = await stream.get_final_message()
        return _response_json(response)

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        params = self._request(
            settings.summary_model,
            settings.summary_effort,
            SUMMARY_SYSTEM,
            _summary_prompt(pages, segments, annotations),
            SUMMARY_SCHEMA,
            max_tokens=64000,
        )
        # 긴 강의는 출력이 길어서 스트리밍으로 받는다 (HTTP 타임아웃 방지)
        async with self.client.beta.messages.stream(**params) as stream:
            response = await stream.get_final_message()
        return _response_json(response)

    async def research_tips(self, summary: dict) -> list[dict]:
        # 웹 검색 결과에는 인용이 붙어 structured output과 함께 쓸 수 없으므로, JSON은 답변 텍스트에서 꺼낸다
        params = self._request(settings.summary_model, settings.summary_effort, TIPS_SYSTEM,
                               _tips_prompt(summary), None, max_tokens=32000)
        params["tools"] = [WEB_SEARCH_TOOL]
        messages = params["messages"]
        for _ in range(4):
            async with self.client.beta.messages.stream(**params) as stream:
                response = await stream.get_final_message()
            if response.stop_reason != "pause_turn":
                break
            # 서버 쪽 검색 반복이 한도에 걸리면, 지금까지의 답변을 붙여 다시 보내 이어서 하게 한다
            messages.append({"role": "assistant", "content": response.content})
        _check_stop(response)
        text = "".join(b.text for b in response.content if b.type == "text")
        return parse_tips(text)


class FakeLLM:
    """API 키 없이 앱 흐름을 확인하기 위한 가짜 응답."""

    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict]) -> dict:
        if len(candidates) > 1 and "애매" in transcript:
            return {"annotations": [{"page_no": -1, "block_id": -1, "type": "explanation", "text": transcript[:60]}],
                    "tasks": []}
        page = candidates[0]
        block_id = page["blocks"][0]["id"] if page["blocks"] else -1
        type_ = "exam" if "시험" in transcript else "emphasis" if "중요" in transcript else "explanation"
        tasks = []
        if "과제" in transcript and not existing_tasks:
            tasks = [{"kind": "homework", "title": "과제", "instructions": transcript, "due_text": "다음 주 금요일까지"}]
        return {"annotations": [{"page_no": page["page_no"], "block_id": block_id, "type": type_,
                                 "text": transcript[:60]}], "tasks": tasks}

    async def draft_task(self, task: dict, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        return {"checklist": [task["instructions"][:40], "마감 확인"], "outline": ["서론", "본론", "결론"],
                "draft": f"{task['title']} 초안입니다. (가짜 응답)", "sources": [p["page_no"] for p in pages[:1]]}

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        spoken = [p for p in pages if any(s["page_no"] == p["page_no"] for s in segments)]
        return {
            "overview": f"받아쓰기 {len(segments)}문장, 필기 {len(annotations)}개로 정리한 강의입니다.",
            "pages": [{"page_no": p["page_no"], "summary": p["text"][:100]} for p in spoken],
            "quiz": [
                {
                    "page_no": p["page_no"],
                    "question": f"{p['page_no']}페이지에서 다룬 내용은?",
                    "choices": [p["text"][:30] or "(내용)", "보기 2", "보기 3", "보기 4"],
                    "answer_index": 0,
                    "explanation": "가짜 응답입니다.",
                }
                for p in spoken[:5]
            ],
        }

    async def research_tips(self, summary: dict) -> list[dict]:
        return [
            {"page_no": p["page_no"], "title": f"{p['page_no']}쪽 더 알아보기", "text": "가짜 응답입니다.",
             "url": "https://example.com"}
            for p in summary.get("pages", [])[:2]
        ]


def make_llm() -> LLM:
    if settings.llm_mode == "fake":
        return FakeLLM()
    if settings.llm_mode == "claude":
        return ClaudeLLM()
    from .ollama_llm import OllamaLLM

    return OllamaLLM()
