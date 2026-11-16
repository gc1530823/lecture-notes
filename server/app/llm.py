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
- 필기 하나는 한국어 두 줄(약 60자) 이내로, 학생 노트처럼 간결하게 씁니다 ("~함", "~임", 명사로 끝내기, 화살표·콜론 활용).
- 필기 글에는 '내용'만 씁니다. "시험에 꼭 나온다", "꼭 기억하세요", "중요하다", "교수님이 강조" 같은 말은 쓰지 않습니다.
  시험·강조라는 사실은 type(exam·emphasis)이 꼬리표로 보여 줍니다.
  예) 발언 "네 가지 조건, 이거 시험에 꼭 나와요" → type exam, text "교착 상태 4조건: 상호 배제·점유와 대기·비선점·순환 대기"
  예) 발언 "이 단원 중간고사 범위예요" → type exam, text "중간고사 범위: 교착 상태"
- block_id에는 그 필기와 가장 관련 있는 블록 번호를 넣고, 맞는 블록이 없으면 -1을 넣습니다.
- type은 다음 중 하나입니다.
  - explanation: 슬라이드에 없는 보충 설명이나 풀이 과정
  - example: 교수님이 든 예시나 사례
  - emphasis: 교수님이 "중요하다", "꼭 기억하라"며 강조한 내용 (글에는 그 내용만)
  - exam: 교수님이 "시험에 나온다", "출제한다"고 한 내용 (글에는 그 내용만. "이거 시험에 나와요"처럼 가리키는 말이면 무엇을 가리키는지 앞 발언·슬라이드에서 찾아 그 내용을 씁니다)
  - notice: 과제, 일정, 공지, 질문과 답변
  - tip: 교수님이 짧게 언급하고 지나간 개념에 대해, 학생이 이해하는 데 꼭 도움이 되는 배경지식이나 공부 팁.
    교수님 발언이 아니라 당신이 덧붙이는 내용입니다. 확실히 맞는 내용일 때만, 한 번에 최대 1개만 씁니다.
- 잡담, 인사, 필기할 가치가 없는 발언뿐이면 빈 목록을 반환합니다.

과제 뽑기 (tasks):
- 교수님이 학생에게 무언가를 하라고 분명히 요구할 때만 tasks에 넣습니다: 수업 중 활동("지금 5분 동안 써 보세요"), 숙제, 레포트, 발표.
- "시험에 나온다", "꼭 기억하세요"처럼 중요하다고만 말한 것은 과제가 아닙니다 (exam·emphasis 필기로만 씁니다).
  exam_prep은 "다음 시간까지 3장 읽어 오세요", "퀴즈 보니까 공부해 오세요"처럼 준비할 것을 시켰을 때만 씁니다.
- 이미 뽑은 과제(existing_tasks)와 같은 것은 다시 넣지 않습니다. 요구사항이 추가되면 새 과제로 넣지 말고 무시합니다.
- kind: in_class(수업 시간 안에 하는 것) | homework | report | exam_prep
- title: 한 줄 제목. instructions: 교수님이 말한 요구사항(주제, 분량, 형식, 제출 방법)을 빠짐없이.
- due_text: 마감을 교수님이 말한 그대로("다음 주 금요일까지", "수업 끝나기 전"). 말하지 않았으면 빈 문자열.
- 과제를 뽑아도 notice 필기는 그대로 함께 씁니다.

용어 사전 (terms):
- 새 발언에 나온 전문용어(학문·업무 용어, 약어, 고유한 개념 이름) 가운데 학생이 뜻을 모를 만한 것을 최대 3개 넣습니다.
  "학생", "문제", "오늘"처럼 흔한 말은 넣지 않습니다. 이미 정의한 용어(known_terms)는 다시 넣지 않습니다.
- term: 용어 (영어 약어면 "SGD (확률적 경사하강법)"처럼 풀어서). definition: 한 문장 뜻.
  교수님 설명을 먼저 근거로 쓰고, 발언에 뜻이 없어 일반 지식으로 쓰면 끝에 "(강의 밖)"을 붙입니다."""

# 노트 모드(강의자료 없는 수업): 슬라이드가 없으므로 학생이 공책에 정리하듯 쓰게 한다
NOTEBOOK_RULES = """

이 수업에는 강의자료가 없습니다. 슬라이드 대신 학생의 공책에 정리 노트를 씁니다:
- block_id는 항상 -1입니다. 페이지(page_no)는 후보에 주어진 것을 씁니다.
- 필기 하나는 "개념: 설명" 꼴로 씁니다 (예: "이데아: 감각 너머의 참된 실재"). 개념 없이 설명만 있으면 짧은 한 문장으로.
- 세부 내용은 마침표로 끊어 한두 문장 덧붙입니다 (화면에서 → 로 들여 써진다).
- 교수님이 말한 핵심 용어·정의·순서·비교를 빠뜨리지 않고, 군말은 뺍니다."""


# 회의 모드: 같은 필기 종류를 회의록의 뜻으로 바꿔 쓴다 (화면도 이 이름으로 보여 준다)
MEETING_RULES = """

이것은 수업이 아니라 회의 녹음입니다. 회의록을 씁니다 (교수님 대신 참석자들의 발언):
- type의 뜻을 바꿔 씁니다: emphasis = 결정된 것("결정: ..."), explanation = 논의 요점, example = 근거·자료·숫자,
  notice = 일정·공지, qa = 아직 안 정해진 것·물어볼 것. exam과 tip은 쓰지 않습니다.
- tasks는 회의에서 맡은 할 일입니다: kind는 "in_class", title은 "[담당자] 할 일" (담당자를 모르면 "[미정]"),
  instructions는 무엇을 어떻게, due_text는 말한 기한 (없으면 빈 문자열).
- terms에는 회의에 나온 전문용어·약어만 넣습니다."""

# 영어 강의와 목소리 강조: 수업·회의 모두에 붙는 규칙
SPEECH_RULES = """

받아쓰기 읽는 법:
- 문장 앞의 "(목소리 높임)"은 말하는 사람이 앞뒤보다 크게 말한 곳입니다. 강조나 시험 언급일 가능성이 높으니 놓치지 마세요.
- 발언이 영어이면 필기는 한국어로 쓰고, 핵심 용어와 정의는 영어 원문을 괄호로 함께 씁니다 (예: "과적합 (overfitting): ...")."""


def annotation_system(notebook: bool, meeting: bool = False) -> str:
    return ANNOTATION_SYSTEM + (NOTEBOOK_RULES if notebook else "") + (MEETING_RULES if meeting else "") + SPEECH_RULES


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
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "definition": {"type": "string"}},
                "required": ["term", "definition"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["annotations", "tasks", "terms"],
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
- quiz: 복습 퀴즈 5~8문항. 강의 내용을 바탕으로 이해를 묻는 문제를 새로 냅니다 (외운 문장을 찾는 문제가 아님).
  - 개념을 새 상황에 적용하기, 원인·이유, 두 개념 비교, 예시가 어느 개념인지, 틀린 설명 고르기, 간단한 계산·추론.
  - 질문과 보기는 새로 쓰고 슬라이드·받아쓰기 문장을 그대로 옮기지 않습니다. "몇 쪽에서 다룬 내용은?" 같은 질문은 내지 않습니다.
  - 오답 3개는 그럴듯한 오개념으로, 정답 위치는 골고루. 시험(exam)·강조(emphasis) 필기가 붙은 내용을 먼저 출제합니다.
  - 각 문항은 보기 4개(choices), 정답 번호(answer_index, 0부터 시작), 해설(explanation: 왜 맞고 다른 보기는 왜 틀린지), 근거 페이지(page_no)를 가집니다.

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

ORGANIZE_SYSTEM = """당신은 대학 강의를 듣지 못한 친구에게 빌려줄 노트를 쓰는 조교입니다.
강의자료 한 페이지의 텍스트, 그 페이지에서 교수님이 한 말(받아쓰기), 강의 중 붙인 필기를 받습니다.

- 요약이 아니라 전체 정리입니다. 교수님이 설명한 내용을 빠짐없이, 순서대로 노트 항목(points)으로 씁니다.
- 슬라이드에 없지만 교수님이 덧붙인 설명·예시·주의사항을 반드시 넣습니다. 받아쓰기의 군말(자, 음, 그러니까)은 뺍니다.
- 항목 하나는 1~2문장. "개념: 설명" 꼴을 쓰면 좋습니다. 시험에 나온다고 한 것은 끝에 (★시험)을 붙입니다.
- 받아쓰기가 잘못 들린 듯한 단어는 슬라이드의 용어로 고쳐 씁니다.
- 주어진 내용만 쓰고, 지어내지 않습니다. 한국어로 씁니다."""

ORGANIZE_SCHEMA = {
    "type": "object",
    "properties": {"points": {"type": "array", "items": {"type": "string"}}},
    "required": ["points"],
    "additionalProperties": False,
}

ASK_SYSTEM = """당신은 수업을 같이 듣는 친절한 조교입니다. 학생이 수업 중에 방금 들은 내용을 묻습니다.
지금 보는 슬라이드(문단마다 [번호]), 최근 2분 동안 교수님이 한 말(받아쓰기), 학생의 질문을 받습니다.

- answer: 질문에 2~4문장으로 쉽게 답합니다. 교수님이 방금 한 설명을 먼저 근거로 삼고, 쉬운 말과 짧은 예시로 풀어 줍니다.
  교수님 설명에 없는 내용을 덧붙일 때는 "(교수님 설명 외)"라고 표시합니다. 모르면 지어내지 말고 모른다고 합니다.
- block_id: 답과 가장 관련 있는 슬라이드 문단 번호. 맞는 문단이 없으면 -1.
한국어로 씁니다."""

ASK_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "block_id": {"type": "integer"}},
    "required": ["answer", "block_id"],
    "additionalProperties": False,
}

FLASHCARD_SYSTEM = """강의 한 페이지(슬라이드, 교수님 말, 필기)로 복습용 플래시카드를 만듭니다.
- 2~4장을 cards에 넣습니다. front에는 짧은 질문이나 용어, back에는 1~2문장 답을 씁니다.
- 교수님이 강조하거나 시험에 나온다고 한 내용을 먼저 만듭니다. 주어진 내용만 쓰고 한국어로 씁니다."""

FLASHCARD_SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object", "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
        "required": ["front", "back"], "additionalProperties": False}}},
    "required": ["cards"],
    "additionalProperties": False,
}

CONCEPT_SYSTEM = """강의 한 페이지(슬라이드, 교수님 말, 필기)에서 꼭 알아야 할 개념을 골라 용어집을 만듭니다.
- 1~4개를 concepts에 넣습니다. term은 용어, definition은 교수님 설명을 바탕으로 한 1~2문장 뜻,
  example은 교수님이 든 예시(없으면 빈 문자열)입니다. 주어진 내용만 쓰고 한국어로 씁니다."""

CONCEPT_SCHEMA = {
    "type": "object",
    "properties": {"concepts": {"type": "array", "items": {
        "type": "object",
        "properties": {"term": {"type": "string"}, "definition": {"type": "string"}, "example": {"type": "string"}},
        "required": ["term", "definition", "example"], "additionalProperties": False}}},
    "required": ["concepts"],
    "additionalProperties": False,
}

MINDMAP_SYSTEM = """강의의 페이지별 요약을 받아 마인드맵을 만듭니다.
- root에는 강의 전체 주제(15자 이내)를 씁니다.
- branches에는 큰 주제 3~6개를 넣고, 주제마다 label(12자 이내)과 page_no(가장 관련 있는 쪽), 세부 항목 leaves(2~4개, 각 15자 이내)를 씁니다.
- 짧은 명사구로 씁니다. 한국어로 씁니다."""

MINDMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "root": {"type": "string"},
        "branches": {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "page_no": {"type": "integer"},
                           "leaves": {"type": "array", "items": {"type": "string"}}},
            "required": ["label", "page_no", "leaves"], "additionalProperties": False}},
    },
    "required": ["root", "branches"],
    "additionalProperties": False,
}

TUTOR_SYSTEM = """당신은 이 강의를 함께 공부하는 친절한 AI 튜터입니다. 강의 자료(슬라이드·교수님 설명·필기) 일부와 대화 기록을 받습니다.
- 학생 눈높이에서 쉽게, 3~6문장으로 답합니다. 교수님의 설명과 예시를 먼저 근거로 삼고, 근거가 된 쪽을 pages에 넣습니다.
- 강의에 없는 내용을 덧붙일 때는 "(강의 밖 내용)"이라고 표시합니다. 모르면 지어내지 않습니다.
- 학생이 문제를 내 달라고 하면 강의 내용으로 한 문제를 내고, 답은 학생이 답한 뒤에 알려 줍니다.
- 학생이 답을 말하면 맞았는지 알려 주고 왜 그런지 짧게 설명합니다. 한국어로 씁니다."""

TUTOR_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "pages": {"type": "array", "items": {"type": "integer"}}},
    "required": ["answer", "pages"],
    "additionalProperties": False,
}


def _tutor_prompt(context: str, messages: list[dict]) -> str:
    history = "\n".join(f"<{'student' if m['role'] == 'user' else 'tutor'}>{m['content']}</{'student' if m['role'] == 'user' else 'tutor'}>"
                        for m in messages[-10:])
    return f"<lecture>\n{context}\n</lecture>\n\n<conversation>\n{history}\n</conversation>"


def _mindmap_prompt(title: str, pages: list[dict]) -> str:
    lines = "\n".join(f"- {p['page_no']}쪽: {p['summary']}" for p in pages)
    return f"<lecture_title>{title}</lecture_title>\n<page_summaries>\n{lines}\n</page_summaries>"


TITLE_SYSTEM = """강의의 한 부분에서 교수님이 한 말(받아쓰기)을 받습니다. 이 부분의 주제를 노트 제목으로 씁니다.
title에 20자 이내의 짧은 명사구로 씁니다 (예: "경사하강법과 학습률"). 한국어로 씁니다."""

TITLE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

CATCHUP_SYSTEM = """학생이 수업 중에 잠깐 딴생각을 해서 최근 몇 분을 놓쳤습니다. 그동안 교수님이 한 말(받아쓰기)과 그때의 슬라이드를 받습니다.

- 놓친 내용을 3~5개 항목(points)으로, 수업 흐름 순서대로 짧게 정리합니다. 항목 하나는 한 문장입니다.
- 시험·과제·공지처럼 놓치면 안 되는 말이 있으면 맨 앞에 "⚠" 없이 "[중요]"로 시작하는 항목으로 씁니다.
- 받아쓰기에 있는 내용만 씁니다. 한국어로 씁니다."""

CATCHUP_SCHEMA = {
    "type": "object",
    "properties": {"points": {"type": "array", "items": {"type": "string"}}},
    "required": ["points"],
    "additionalProperties": False,
}


def _catchup_prompt(slides: list[dict], speech: str) -> str:
    slide_text = "\n".join(f'<slide page_no="{p["page_no"]}">\n{p["text"]}\n</slide>' for p in slides)
    return f"{slide_text}\n<missed_speech>\n{speech}\n</missed_speech>"


PREDICT_SYSTEM = """당신은 이 과목 교수님이 낼 시험 문제를 예상하는 조교입니다.
강의자료 한 페이지의 텍스트, 그 페이지에서 교수님이 한 말(여러 강의의 받아쓰기), 필기를 받습니다.

1. 교수님이 시험에 나온다고 한 것, 강조한 것, 오래 설명한 것을 중심으로 예상 문제 2개를 만들어 questions에 넣습니다.
2. 문제마다 실제 질문(question), 채점 기준이 될 모범 답안 2~3문장(answer), 이 문제가 나올 것 같은 이유 한 문장(reason)을 씁니다.
   reason에는 근거가 된 교수님 말을 짧게 인용합니다.
3. 서술형·단답형·계산형 중 이 내용에 맞는 형식을 고릅니다.

주어진 내용만 사용하고 한국어로 씁니다."""

PREDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "answer": {"type": "string"},
                               "reason": {"type": "string"}},
                "required": ["question", "answer", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}


BILINGUAL_SYSTEM = """영어 강의 한 페이지의 받아쓰기(교수님 말)를 받아, 문장마다 영어 원문과 한국어 번역을 나란히 놓습니다.
- pairs에 말한 순서대로 넣습니다. en은 받아쓰기 문장을 그대로 (군말 "um", "you know"만 지움), ko는 자연스러운 한국어 번역.
- 전문용어는 한국어 번역 뒤에 영어를 괄호로 씁니다 (예: "과적합(overfitting)"). 최대 30문장."""

BILINGUAL_SCHEMA = {
    "type": "object",
    "properties": {"pairs": {"type": "array", "items": {
        "type": "object", "properties": {"en": {"type": "string"}, "ko": {"type": "string"}},
        "required": ["en", "ko"], "additionalProperties": False}}},
    "required": ["pairs"],
    "additionalProperties": False,
}

STUDY_KINDS = {
    "flashcards": (FLASHCARD_SYSTEM, FLASHCARD_SCHEMA, "cards"),
    "concepts": (CONCEPT_SYSTEM, CONCEPT_SCHEMA, "concepts"),
    "bilingual": (BILINGUAL_SYSTEM, BILINGUAL_SCHEMA, "pairs"),
}
STUDY_KEYS = {"flashcards": ("front", "back"), "concepts": ("term", "definition"), "bilingual": ("en", "ko")}
STUDY_LIMIT = {"bilingual": 30}

# 칠판·화이트보드 사진 읽기 (사진을 읽는 모델이 있을 때)
BOARD_SYSTEM = """수업 중 학생이 찍은 칠판·화이트보드·화면 사진입니다. 사진에 적힌 것을 필기로 옮깁니다.
- text: 사진에 적힌 글·수식·도표 내용을 그대로 옮겨 적습니다 (수식은 읽을 수 있게, 도표는 "A → B"처럼). 못 읽는 곳은 [?].
- summary: 무엇에 대한 판서인지 한두 문장으로. JSON으로만 답합니다: {"text": "...", "summary": "..."}"""


BOARD_OCR_SYSTEM = """수업 중 학생이 찍은 칠판·화이트보드·화면 사진을 글자 인식(OCR)으로 읽은 줄들입니다(<ocr>). 이것을 필기로 다듬습니다.
- 글자 인식은 영어 낱말 사이에 빈칸을 잘못 넣습니다("SE L E C T n a me" → "SELECT name"). 띄어쓰기와 뻔한 오타만 바로잡고, 없는 내용은 지어내지 않습니다.
- <speech>가 있으면 그때 교수님 말을 참고해 용어를 맞춥니다.
- text: 사진의 내용을 줄 순서대로 정리합니다 (수식·코드는 그대로). 알아볼 수 없는 줄은 뺍니다.
- summary: 무엇에 대한 판서인지 한두 문장. JSON으로만 답합니다: {"text": "...", "summary": "..."}"""
BOARD_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}, "summary": {"type": "string"}}, "required": ["text", "summary"]}


# 시간표 사진 읽기 (에브리타임 캡처 · 학교 포털 시간표 캡처 · 종이 시간표 사진)
TIMETABLE_SYSTEM = """대학생의 주간 시간표 사진(에브리타임 캡처, 학교 포털 시간표, 종이 시간표)입니다. 수업을 하나도 빠짐없이 옮깁니다.
- 표의 세로줄은 요일(월~일), 가로줄은 시각입니다. 왼쪽 시각 눈금(9, 10, 11… 또는 1교시, 2교시…)과 칸의 위·아래 위치로 시작·끝 시각을 셉니다.
  교시만 있으면 1교시=09:00 부터 한 교시 1시간으로 셉니다 (표에 교시별 시각이 적혀 있으면 그것을 따릅니다).
- 같은 과목이 여러 요일에 있으면 요일마다 따로 적습니다. 한 칸이 두 요일에 걸치지 않습니다.
- course: 과목 이름만 (교수 이름·학수번호는 빼고), place: 강의실 (없으면 빈 문자열),
  weekday: 0=월 1=화 2=수 3=목 4=금 5=토 6=일, start/end: "HH:MM" 24시간 (오후 1시 = 13:00).
- 시간표가 아니면 classes 를 비웁니다. JSON으로만 답합니다:
{"classes": [{"course": "운영체제", "weekday": 0, "start": "10:30", "end": "11:45", "place": "공학관 301"}]}"""


def clean_timetable(data: dict) -> list[dict]:
    """AI가 읽은 시간표에서 이상한 줄은 버린다 (시각 형식 · 요일 범위 · 겹치는 같은 수업)"""
    import re as _re

    def clock(v) -> str | None:
        m = _re.match(r"^\s*(\d{1,2})\s*[:시.]\s*(\d{2})?", str(v or ""))
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        return f"{h:02d}:{mi:02d}" if 0 <= h < 24 and 0 <= mi < 60 else None

    out, seen = [], set()
    for c in (data or {}).get("classes") or []:
        if not isinstance(c, dict):
            continue
        course = str(c.get("course", "")).strip()[:40]
        try:
            day = int(c.get("weekday"))
        except (TypeError, ValueError):
            continue
        start, end = clock(c.get("start")), clock(c.get("end"))
        if not course or not 0 <= day <= 6 or not start or not end or start >= end or (course, day, start) in seen:
            continue
        seen.add((course, day, start))
        out.append({"course": course, "weekday": day, "start": start, "end": end, "place": str(c.get("place", "")).strip()[:40]})
    return sorted(out, key=lambda c: (c["weekday"], c["start"]))


def clean_study(kind: str, items: list) -> list[dict]:
    required = STUDY_KEYS[kind]
    return [{k: str(v).strip() for k, v in item.items()} for item in items
            if isinstance(item, dict) and all(str(item.get(k, "")).strip() for k in required)][:STUDY_LIMIT.get(kind, 5)]


def clean_predictions(data: dict) -> list[dict]:
    keys = ("question", "answer", "reason")
    return [{k: str(q[k]).strip() for k in keys} for q in data.get("questions", [])
            if isinstance(q, dict) and all(str(q.get(k, "")).strip() for k in keys)][:3]


FIX_SPEECH_SYSTEM = """강의 받아쓰기를 교정합니다. 슬라이드 텍스트와 받아쓰기 한 페이지 분량을 받습니다.

- 잘못 들린 단어만 고칩니다: 비슷한 소리로 잘못 적힌 전문용어("유런" → "뉴런"), 띄어쓰기가 틀린 용어.
- 나머지는 한 글자도 바꾸지 않습니다. 문장을 다듬거나, 줄이거나, 덧붙이지 않습니다.
- 고친 전체 받아쓰기를 speech에 씁니다."""

FIX_SPEECH_SCHEMA = {
    "type": "object",
    "properties": {"speech": {"type": "string"}},
    "required": ["speech"],
    "additionalProperties": False,
}


def accept_fixed_speech(original: str, fixed: str) -> bool:
    """교정이 원문을 다시 쓰거나 줄이지 않았을 때만 받는다 (글자 85% 이상 같고 길이가 비슷해야 한다)."""
    import difflib

    if not fixed or not original:
        return False
    if not 0.9 <= len(fixed) / len(original) <= 1.1:
        return False
    return difflib.SequenceMatcher(None, original, fixed).ratio() >= 0.85


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
    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict],
                       notebook: bool = False, known_terms: list[str] | None = None, meeting: bool = False) -> dict: ...

    async def draft_task(self, task: dict, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict: ...

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict: ...

    async def research_tips(self, summary: dict) -> list[dict]: ...

    async def organize_page(self, page: dict, speech: str, notes: list[dict]) -> list[str]: ...

    async def ask(self, question: str, page: dict, recent_speech: str) -> dict: ...

    async def predict_questions(self, page: dict, speech: str, notes: list[dict]) -> list[dict]: ...

    async def catch_up(self, slides: list[dict], speech: str) -> list[str]: ...

    async def title_topic(self, speech: str) -> str: ...

    async def study_page(self, kind: str, page: dict, speech: str, notes: list[dict]) -> list[dict]: ...

    async def mindmap(self, title: str, pages: list[dict]) -> dict: ...

    async def tutor(self, context: str, messages: list[dict]) -> dict: ...

    async def read_board(self, image: bytes, mime: str) -> dict: ...

    async def read_timetable(self, image: bytes, mime: str) -> dict: ...


def _organize_prompt(page: dict, speech: str, notes: list[dict]) -> str:
    lines = "\n".join(f"- ({a['type']}) {a['text']}" for a in notes) or "(없음)"
    return (f'<page no="{page["page_no"]}">\n<slide>\n{page["text"] or "(텍스트 없음)"}\n</slide>\n'
            f"<speech>\n{speech or '(없음)'}\n</speech>\n<notes>\n{lines}\n</notes>\n</page>")


def _ask_prompt(question: str, page: dict, recent_speech: str) -> str:
    blocks = "\n".join(f"[{b['id']}] {b['text']}" for b in page.get("blocks", [])) or "(텍스트 없음)"
    return (f'<slide page_no="{page["page_no"]}">\n{blocks}\n</slide>\n'
            f"<recent_speech>\n{recent_speech or '(아직 받아쓰기 없음)'}\n</recent_speech>\n"
            f"<question>\n{question}\n</question>")


def _fix_speech_prompt(page: dict, speech: str) -> str:
    return f"<slide>\n{page['text'] or '(텍스트 없음)'}\n</slide>\n<speech>\n{speech}\n</speech>"


def _annotation_prompt(candidates: list[dict], transcript: str, existing_tasks: list[dict] | None = None,
                       known_terms: list[str] | None = None) -> str:
    """candidates: [{"page_no", "blocks": [{id, text}], "existing": [{type, text}]}]"""
    parts = []
    for page in candidates:
        block_lines = "\n".join(f"[{b['id']}] {b['text']}" for b in page["blocks"]) or "(텍스트 없음)"
        # 이미 쓴 필기는 최근 10개 · 100자까지만 (한 쪽에 필기가 많을 때 매번 전부 보내 한도를 빨리 쓰지 않게)
        existing_lines = "\n".join(f"- ({a['type']}) {a['text'][:100]}" for a in page["existing"][-10:]) or "(없음)"
        parts.append(
            f'<slide page_no="{page["page_no"]}">\n<blocks>\n{block_lines}\n</blocks>\n'
            f"<existing_notes>\n{existing_lines}\n</existing_notes>\n</slide>"
        )
    tasks = "\n".join(f"- {t['title']}" for t in existing_tasks or []) or "(없음)"
    terms = ", ".join((known_terms or [])[-60:]) or "(없음)"
    return ("\n\n".join(parts) + f"\n\n<existing_tasks>\n{tasks}\n</existing_tasks>\n\n<known_terms>\n{terms}\n</known_terms>"
            f"\n\n<new_speech>\n{transcript}\n</new_speech>")


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

    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict],
                       notebook: bool = False, known_terms: list[str] | None = None, meeting: bool = False) -> dict:
        params = self._request(
            settings.annotation_model,
            settings.annotation_effort,
            annotation_system(notebook, meeting),
            _annotation_prompt(candidates, transcript, existing_tasks, known_terms),
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

    async def organize_page(self, page: dict, speech: str, notes: list[dict]) -> list[str]:
        params = self._request(settings.summary_model, settings.summary_effort, ORGANIZE_SYSTEM,
                               _organize_prompt(page, speech, notes), ORGANIZE_SCHEMA, max_tokens=16000)
        async with self.client.beta.messages.stream(**params) as stream:
            response = await stream.get_final_message()
        return [p for p in _response_json(response).get("points", []) if isinstance(p, str) and p.strip()]

    async def ask(self, question: str, page: dict, recent_speech: str) -> dict:
        params = self._request(settings.annotation_model, settings.annotation_effort, ASK_SYSTEM,
                               _ask_prompt(question, page, recent_speech), ASK_SCHEMA, max_tokens=4000)
        return _response_json(await self.client.beta.messages.create(**params))

    async def quiz_set(self, prompt: str) -> list[dict]:
        from .quiz import QUIZ_SET_SCHEMA, QUIZ_SET_SYSTEM

        params = self._request(settings.summary_model, settings.summary_effort, QUIZ_SET_SYSTEM, prompt, QUIZ_SET_SCHEMA, max_tokens=16000)
        return _response_json(await self.client.beta.messages.create(**params)).get("questions", [])

    async def study_note(self, prompt: str) -> dict:
        from .study_note import STUDY_NOTE_SCHEMA, STUDY_NOTE_SYSTEM

        params = self._request(settings.summary_model, settings.summary_effort, STUDY_NOTE_SYSTEM, prompt, STUDY_NOTE_SCHEMA, max_tokens=16000)
        return _response_json(await self.client.beta.messages.create(**params))

    async def card_question(self, prompt: str) -> str:
        from .quiz import CARD_SCHEMA, CARD_SYSTEM

        params = self._request(settings.annotation_model, settings.annotation_effort, CARD_SYSTEM, prompt, CARD_SCHEMA, max_tokens=1000)
        return str(_response_json(await self.client.beta.messages.create(**params)).get("question", "")).strip()

    async def grade_answer(self, prompt: str) -> dict:
        from .quiz import GRADE_SCHEMA, GRADE_SYSTEM

        params = self._request(settings.annotation_model, settings.annotation_effort, GRADE_SYSTEM, prompt, GRADE_SCHEMA, max_tokens=2000)
        return _response_json(await self.client.beta.messages.create(**params))

    async def study_page(self, kind: str, page: dict, speech: str, notes: list[dict]) -> list[dict]:
        system, schema, key = STUDY_KINDS[kind]
        params = self._request(settings.summary_model, "low", system, _organize_prompt(page, speech, notes), schema,
                               max_tokens=8000)
        return clean_study(kind, _response_json(await self.client.beta.messages.create(**params)).get(key, []))

    async def mindmap(self, title: str, pages: list[dict]) -> dict:
        params = self._request(settings.summary_model, "low", MINDMAP_SYSTEM, _mindmap_prompt(title, pages),
                               MINDMAP_SCHEMA, max_tokens=8000)
        return _response_json(await self.client.beta.messages.create(**params))

    async def read_board(self, image: bytes, mime: str) -> dict:
        return await self._vision(BOARD_SYSTEM, "이 사진을 필기로 옮겨 주세요.", image, mime)

    async def read_timetable(self, image: bytes, mime: str) -> dict:
        return await self._vision(TIMETABLE_SYSTEM, "이 시간표의 수업을 모두 옮겨 주세요.", image, mime, 4000)

    async def _vision(self, system: str, ask: str, image: bytes, mime: str, max_tokens: int = 2000) -> dict:
        import base64

        response = await self.client.messages.create(
            model=settings.annotation_model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(image).decode()}},
                {"type": "text", "text": ask}]}])
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        return json.loads(text[text.find("{"): text.rfind("}") + 1])

    async def tutor(self, context: str, messages: list[dict]) -> dict:
        params = self._request(settings.annotation_model, settings.annotation_effort, TUTOR_SYSTEM,
                               _tutor_prompt(context, messages), TUTOR_SCHEMA, max_tokens=4000)
        return _response_json(await self.client.beta.messages.create(**params))

    async def title_topic(self, speech: str) -> str:
        params = self._request(settings.annotation_model, "low", TITLE_SYSTEM, f"<speech>\n{speech}\n</speech>",
                               TITLE_SCHEMA, max_tokens=1000)
        return str(_response_json(await self.client.beta.messages.create(**params)).get("title", "")).strip()

    async def catch_up(self, slides: list[dict], speech: str) -> list[str]:
        params = self._request(settings.annotation_model, settings.annotation_effort, CATCHUP_SYSTEM,
                               _catchup_prompt(slides, speech), CATCHUP_SCHEMA, max_tokens=4000)
        data = _response_json(await self.client.beta.messages.create(**params))
        return [p for p in data.get("points", []) if isinstance(p, str) and p.strip()]

    async def predict_questions(self, page: dict, speech: str, notes: list[dict]) -> list[dict]:
        params = self._request(settings.summary_model, settings.summary_effort, PREDICT_SYSTEM,
                               _organize_prompt(page, speech, notes), PREDICT_SCHEMA, max_tokens=16000)
        async with self.client.beta.messages.stream(**params) as stream:
            response = await stream.get_final_message()
        return clean_predictions(_response_json(response))

    async def fix_speech(self, page: dict, speech: str) -> str:
        params = self._request(settings.summary_model, "low", FIX_SPEECH_SYSTEM, _fix_speech_prompt(page, speech),
                               FIX_SPEECH_SCHEMA, max_tokens=16000)
        async with self.client.beta.messages.stream(**params) as stream:
            response = await stream.get_final_message()
        return str(_response_json(response).get("speech", ""))


class FakeLLM:
    """API 키 없이 앱 흐름을 확인하기 위한 가짜 응답."""

    async def annotate(self, candidates: list[dict], transcript: str, existing_tasks: list[dict],
                       notebook: bool = False, known_terms: list[str] | None = None, meeting: bool = False) -> dict:
        transcript = transcript.replace("(목소리 높임) ", "")
        if len(candidates) > 1 and "애매" in transcript:
            return {"annotations": [{"page_no": -1, "block_id": -1, "type": "explanation", "text": transcript[:60]}],
                    "tasks": []}
        page = candidates[0]
        block_id = page["blocks"][0]["id"] if page["blocks"] else -1
        type_ = "exam" if "시험" in transcript else "emphasis" if "중요" in transcript else "explanation"
        tasks = []
        if "과제" in transcript and not existing_tasks:
            tasks = [{"kind": "homework", "title": "과제", "instructions": transcript, "due_text": "다음 주 금요일까지"}]
        if meeting and "하기로" in transcript:
            type_ = "emphasis"
            tasks = [{"kind": "in_class", "title": "[민수] 자료 정리", "instructions": transcript, "due_text": "금요일까지"}]
        # 용어 사전: 대문자로 시작하는 영어 낱말을 용어로 본다
        known = {t.lower() for t in known_terms or []}
        terms = [{"term": w, "definition": f"{w}의 뜻 (가짜 응답)"}
                 for w in dict.fromkeys(re.findall(r"(?<![A-Za-z])[A-Z][A-Za-z]{3,}(?![A-Za-z])", transcript)) if w.lower() not in known][:3]
        return {"annotations": [{"page_no": page["page_no"], "block_id": block_id, "type": type_,
                                 "text": transcript[:60]}], "tasks": tasks, "terms": terms}

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
                    "question": f"다음 중 '{(p['text'] or '이 개념').splitlines()[0][:24]}'을 가장 잘 설명한 것은?",
                    "choices": ["핵심 조건이 모두 갖춰져야 일어난다", "조건 하나만 있어도 항상 일어난다",
                                "운영체제가 자동으로 막아 주므로 신경 쓸 필요 없다", "프로그램을 다시 켜면 영원히 사라진다"],
                    "answer_index": 0,
                    "explanation": "가짜 응답입니다. 실제 앱에서는 강의 내용을 바탕으로 AI가 이해를 묻는 문제를 새로 냅니다.",
                }
                for p in spoken[:5]
            ],
        }

    async def quiz_set(self, prompt: str) -> list[dict]:
        pages = [int(n) for n in re.findall(r'<page no="(\d+)">', prompt)] or [1]
        return [
            {"type": "mcq", "page_no": pages[0], "topic": "핵심 개념", "question": "다음 중 이 개념이 성립하는 조건으로 옳은 것은?",
             "choices": ["조건이 모두 갖춰져야 한다", "조건 하나만 있어도 된다", "조건과 상관없다", "항상 성립하지 않는다"], "answer_index": 0,
             "answer": "", "accept": [], "rubric": [], "explanation": "가짜 응답입니다."},
            {"type": "ox", "page_no": pages[-1], "topic": "핵심 개념", "question": "조건 하나만 깨져도 이 현상은 일어나지 않는다.",
             "choices": [], "answer_index": 0, "answer": "O", "accept": [], "rubric": [], "explanation": "가짜 응답입니다."},
            {"type": "short", "page_no": pages[0], "topic": "용어", "question": "상호 배제용 세마포의 초기값은?",
             "choices": [], "answer_index": 0, "answer": "1", "accept": ["일"], "rubric": ["초기값 1"], "explanation": "한 번에 하나만 들어가게 1로 시작합니다."},
            {"type": "essay", "page_no": pages[-1], "topic": "적용", "question": "이 개념을 실제 상황에 적용하는 예를 들고 이유를 설명하세요.",
             "choices": [], "answer_index": 0, "answer": "조건을 확인하고 하나를 깨는 방식으로 예방한다", "accept": [],
             "rubric": ["예시를 든다", "이유를 조건과 연결한다"], "explanation": "가짜 응답입니다."},
        ]

    async def study_note(self, prompt: str) -> dict:
        pages = [int(n) for n in re.findall(r'<page no="(\d+)">', prompt)] or [1]
        return {"title": "정리 노트", "one_line": "가짜 응답으로 만든 정리 노트예요.",
                "sections": [{"heading": f"{n}쪽 내용", "pages": [n], "points": ["핵심 하나", "핵심 둘"], "explain": "설명이에요.",
                              "example": "예시예요." if n == pages[0] else "", "exam": "시험에 나와요." if n == pages[-1] else ""} for n in pages],
                "terms": [{"term": "용어", "meaning": "뜻"}], "exam_focus": ["시험 포인트"], "check": [{"q": "확인 문제?", "a": "답"}]}

    async def card_question(self, prompt: str) -> str:
        return "이 개념이 왜 그렇게 동작하는지 설명해 보세요"

    async def grade_answer(self, prompt: str) -> dict:
        student = re.search(r"<student_answer>(.*)</student_answer>", prompt, re.S)
        good = student and len(student.group(1).strip()) >= 10
        return {"verdict": "partial" if good else "wrong", "score": 0.5 if good else 0, "feedback": "가짜 채점입니다."}

    async def make_quiz(self, pages: list[dict], segments: list[dict], annotations: list[dict], page_results=None) -> list[dict]:
        return [{"page_no": p["page_no"], "question": f"'{(p.get('text') or '이 개념').splitlines()[0][:20]}'을 실제 상황에 쓴다면 가장 알맞은 것은?",
                 "choices": ["핵심 조건을 먼저 확인한다", "조건과 상관없이 항상 쓴다", "쓰지 않는 것이 낫다", "다음 강의까지 미룬다"],
                 "answer_index": 0, "explanation": "가짜 응답입니다."} for p in pages[:3]]

    async def research_tips(self, summary: dict) -> list[dict]:
        return [
            {"page_no": p["page_no"], "title": f"{p['page_no']}쪽 더 알아보기", "text": "가짜 응답입니다.",
             "url": "https://example.com"}
            for p in summary.get("pages", [])[:2]
        ]

    async def organize_page(self, page: dict, speech: str, notes: list[dict]) -> list[str]:
        return [f"{page['page_no']}쪽 정리: {s}" for s in speech.split(". ") if s][:5]

    async def title_topic(self, speech: str) -> str:
        return speech.split(".")[0][:20]

    async def study_page(self, kind: str, page: dict, speech: str, notes: list[dict]) -> list[dict]:
        first = speech.split(".")[0][:40]
        if kind == "bilingual":
            return [{"en": sentence.strip(), "ko": f"(가짜 번역) {sentence.strip()[:30]}"} for sentence in speech.split(". ") if sentence.strip()][:5]
        if kind == "flashcards":
            return [{"front": f"{page['page_no']}쪽의 핵심은?", "back": first}]
        return [{"term": f"{page['page_no']}쪽 개념", "definition": first, "example": ""}]

    async def mindmap(self, title: str, pages: list[dict]) -> dict:
        return {"root": title, "branches": [{"label": f"{p['page_no']}쪽", "page_no": p["page_no"],
                                             "leaves": [p["summary"][:15]]} for p in pages]}

    async def tutor(self, context: str, messages: list[dict]) -> dict:
        return {"answer": f"'{messages[-1]['content']}'에 대한 튜터 답 (가짜 응답)", "pages": []}

    async def read_board(self, image: bytes, mime: str) -> dict:
        return {"text": "f(x) = wx + b → 손실 L(w)", "summary": f"칠판 사진 {len(image)}바이트 (가짜 응답)"}

    async def read_timetable(self, image: bytes, mime: str) -> dict:
        return {"classes": [{"course": "운영체제", "weekday": 0, "start": "10:30", "end": "11:45", "place": "공학관 301"},
                            {"course": "운영체제", "weekday": 2, "start": "10:30", "end": "11:45", "place": "공학관 301"},
                            {"course": "인공지능개론", "weekday": 1, "start": "13시", "end": "14:15", "place": ""},
                            {"course": "", "weekday": 3, "start": "09:00", "end": "10:00"},
                            {"course": "이상한 줄", "weekday": 9, "start": "09:00", "end": "08:00"}]}

    async def catch_up(self, slides: list[dict], speech: str) -> list[str]:
        return [f"놓친 내용: {s}" for s in speech.split(". ") if s][:4]

    async def predict_questions(self, page: dict, speech: str, notes: list[dict]) -> list[dict]:
        return [{"question": f"{page['page_no']}쪽 내용을 설명하시오.", "answer": speech[:80],
                 "reason": "교수님이 강조한 부분입니다. (가짜 응답)"}]

    async def ask(self, question: str, page: dict, recent_speech: str) -> dict:
        block_id = page["blocks"][0]["id"] if page.get("blocks") else -1
        return {"answer": f"'{question}'에 대한 답: {recent_speech[-60:]}", "block_id": block_id}


def make_llm() -> LLM:
    if settings.llm_mode == "fake":
        return FakeLLM()
    if settings.llm_mode == "claude":
        return ClaudeLLM()
    if settings.llm_mode == "groq":
        from .groq import GroqLLM

        return GroqLLM()
    if settings.llm_mode == "hybrid":
        # 수업 중 일은 Groq, 강의 뒤 일은 우리 AI(OLLAMA_MODEL, 보통 lecture-notes) — app/hybrid.py
        from .groq import GroqLLM
        from .hybrid import HybridLLM
        from .ollama_llm import OllamaLLM

        return HybridLLM(GroqLLM(), OllamaLLM())
    from .ollama_llm import OllamaLLM

    return OllamaLLM()
