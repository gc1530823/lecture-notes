"""AI 퀴즈: AI가 강의자료와 강의 내용을 먼저 공부한 뒤, 시험처럼 여러 유형의 문제를 내고 학생의 답을 채점한다.

- 범위: 강의 하나(그 강의의 슬라이드·교수님 설명·필기) 또는 강의자료 전체(모든 쪽 + 그 자료로 들은 모든 강의)
- 유형: 객관식(mcq) · OX(ox) · 빈칸(fill) · 단답(short) · 서술(essay)
- 문제는 "몇 분에 교수님이 한 말"이 아니라 개념·원리·적용을 묻는다. 쪽 번호와 그 쪽 제목을 함께 단다 ("(7장)"처럼)
- 채점: 객관식·OX는 그대로 맞춰 보고, 빈칸·단답은 정답·인정 답과 먼저 맞춰 본 뒤 아니면 AI가, 서술은 AI가 채점 기준으로 채점
"""

import re

TYPES = ["mcq", "ox", "fill", "short", "essay"]
TYPE_LABEL = {"mcq": "객관식", "ox": "OX", "fill": "빈칸", "short": "단답", "essay": "서술"}

QUIZ_SET_SYSTEM = """당신은 이 과목을 가르치는 교수님 대신 시험 문제를 내는 출제자입니다.
먼저 <material>의 강의자료(쪽마다 슬라이드 글)와 수업 내용(교수님 설명 요약·필기, 교수님이 시험에 나온다고 한 것)을 꼼꼼히 공부하세요.
그다음 이 과목 시험에 나올 법한 문제를 냅니다.

원칙:
- 개념·원리·조건·차이·적용을 묻습니다. 교수님이 몇 분에 한 말, 녹음의 어느 부분 같은 것은 묻지 않습니다. "강의에서 말한 것은?" 같은 질문은 금지.
- 질문은 직접 새로 씁니다. 슬라이드 문장을 그대로 옮겨 빈칸만 뚫는 식은 피하고, 핵심 용어·값·조건을 묻습니다.
- 교수님이 시험에 나온다고 한 것, 강조한 것을 먼저 냅니다. 쉬운 문제와 어려운 문제를 섞습니다.
- 유형을 섞습니다: mcq(객관식, 보기 4개, 그럴듯한 오답), ox(맞으면 O 틀리면 X), fill(빈칸 ___ 한두 곳), short(한 단어~한 문장), essay(2~4문장 서술).
- page_no는 그 문제의 근거가 된 쪽. topic은 그 쪽의 짧은 제목(예: "세마포", "7장 교착 상태").
- answer는 모범 답. mcq는 정답 보기의 번호(0~3)를 answer_index에, answer에는 정답 보기 글. ox는 answer에 "O" 또는 "X".
- accept는 정답으로 인정할 다른 표현들(동의어·영어·띄어쓰기 차이 등). fill이 여러 칸이면 answer에 "값1, 값2" 순서대로.
- rubric은 서술·단답 채점 기준: 꼭 들어가야 할 핵심 내용 2~4개.
- explanation은 왜 그 답인지 1~2문장.
- 강의자료에 없는 사실을 지어내지 않습니다. 한국어로 씁니다."""

QUIZ_SET_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": TYPES},
            "page_no": {"type": "integer"},
            "topic": {"type": "string"},
            "question": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}},
            "answer_index": {"type": "integer"},
            "answer": {"type": "string"},
            "accept": {"type": "array", "items": {"type": "string"}},
            "rubric": {"type": "array", "items": {"type": "string"}},
            "explanation": {"type": "string"},
        },
        "required": ["type", "page_no", "topic", "question", "choices", "answer_index", "answer", "accept", "rubric", "explanation"],
        "additionalProperties": False}}},
    "required": ["questions"],
    "additionalProperties": False,
}

GRADE_SYSTEM = """당신은 대학 시험 채점 조교입니다. 문제, 모범 답, 인정 답, 채점 기준, 학생 답을 받아 채점합니다.
- 뜻이 맞으면 표현·맞춤법·띄어쓰기·영어/한국어 차이는 봐줍니다. 핵심이 빠졌거나 틀린 내용이 섞이면 감점합니다.
- verdict: correct(맞음) · partial(일부 맞음) · wrong(틀림). score는 0~1.
- feedback은 학생에게 하는 말로 1~2문장: 맞은 점과 빠진 점을 구체적으로. 반말 말고 존댓말."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["correct", "partial", "wrong"]}, "score": {"type": "number"},
                   "feedback": {"type": "string"}},
    "required": ["verdict", "score", "feedback"],
    "additionalProperties": False,
}


def material(pages: list[dict], sessions: list[dict], limit: int = 14000) -> str:
    """AI가 공부할 자료: 쪽마다 슬라이드 글 + 그 쪽에서 교수님이 한 설명(요약이 있으면 요약) + 필기 + 시험·강조 표시"""
    parts = []
    for p in pages:
        no = p["page_no"]
        slide = (p.get("text") or "").strip()
        summaries = [s for x in sessions for s in x.get("summaries", {}).get(no, [])]
        speech = " ".join(seg["text"] for x in sessions for seg in x.get("segments", []) if seg.get("page_no") == no)
        notes = [a for x in sessions for a in x.get("annotations", []) if a["page_no"] == no and not a.get("pending")]
        key = [a["text"] for a in notes if a["type"] in ("exam", "emphasis")]
        if not (slide or speech or notes):
            continue
        block = [f'<page no="{no}">']
        if slide:
            block.append(f"[슬라이드] {slide[:900]}")
        if summaries:
            block.append("[수업 요약] " + " ".join(summaries)[:600])
        elif speech:
            block.append("[교수님 설명] " + speech[:700])
        if notes:
            block.append("[필기] " + " / ".join(a["text"] for a in notes[:8])[:500])
        if key:
            block.append("[시험에 나온다고 함·강조] " + " / ".join(key)[:300])
        block.append("</page>")
        parts.append("\n".join(block))
    text = "\n".join(parts)
    return text[:limit]


def quiz_prompt(material_text: str, count: int, types: list[str]) -> str:
    kinds = ", ".join(f"{t}({TYPE_LABEL[t]})" for t in types)
    return f"<material>\n{material_text}\n</material>\n\n문제 {count}개를 내세요. 유형은 {kinds}를 골고루 섞으세요."


_NORM = re.compile(r"[\s.,·:;!?'\"()\[\]{}~_-]+")


def _norm(text: str) -> str:
    return _NORM.sub("", (text or "").lower())


def clean_set(items: list, page_nos: set[int]) -> list[dict]:
    """쓸 만한 문제만: 유형에 맞는 모양, 녹음 시각을 묻는 질문 아님, 보기가 진짜"""
    out = []
    for q in items or []:
        t = q.get("type")
        question = (q.get("question") or "").strip()
        if t not in TYPES or len(question) < 6:
            continue
        if re.search(r"\d+\s*분|녹음|강의에서\s*(말한|다룬|언급한)|교수님이\s*(말한|언급한)", question):
            continue
        if t == "mcq":
            choices = [c.strip() for c in q.get("choices") or [] if isinstance(c, str) and c.strip()]
            if len(choices) != 4 or len(set(choices)) != 4 or not 0 <= q.get("answer_index", -1) < 4:
                continue
            q = {**q, "choices": choices, "answer": choices[q["answer_index"]]}
        elif t == "ox":
            ans = _norm(q.get("answer"))
            if ans not in ("o", "x"):
                continue
            q = {**q, "answer": ans.upper(), "choices": ["O", "X"]}
        else:
            if not (q.get("answer") or "").strip():
                continue
            q = {**q, "choices": []}
        if q.get("page_no") not in page_nos:
            q = {**q, "page_no": min(page_nos) if page_nos else 1}
        out.append(q)
    return out


def quick_grade(q: dict, answer: str) -> dict | None:
    """AI 없이 채점할 수 있으면 바로: 객관식·OX, 그리고 정답과 글자가 같은 빈칸·단답"""
    given = _norm(answer)
    if not given:
        return {"verdict": "wrong", "score": 0, "feedback": "답을 적지 않았어요."}
    if q["type"] == "mcq":
        letters = {"a": 0, "b": 1, "c": 2, "d": 3, "1": 0, "2": 1, "3": 2, "4": 3, "①": 0, "②": 1, "③": 2, "④": 3}
        picked = letters.get(given, next((i for i, c in enumerate(q["choices"]) if _norm(c) == given), None))
        ok = picked == q["answer_index"]
        return {"verdict": "correct" if ok else "wrong", "score": 1 if ok else 0, "feedback": "" if ok else f"정답은 {'ABCD'[q['answer_index']]}. {q['answer']}이에요."}
    if q["type"] == "ox":
        mapped = {"o": "O", "x": "X", "맞다": "O", "맞음": "O", "참": "O", "틀리다": "X", "틀림": "X", "거짓": "X", "true": "O", "false": "X"}.get(given)
        ok = mapped == q["answer"]
        return {"verdict": "correct" if ok else "wrong", "score": 1 if ok else 0, "feedback": "" if ok else f"정답은 {q['answer']}예요."}
    accepted = {_norm(q["answer"])} | {_norm(a) for a in q.get("accept") or []}
    if given in accepted:
        return {"verdict": "correct", "score": 1, "feedback": ""}
    if q["type"] == "fill":
        # 빈칸 여러 개: 순서대로 하나씩
        want = [_norm(x) for x in re.split(r"[,/]", q["answer"]) if x.strip()]
        got = [_norm(x) for x in re.split(r"[,/\s]+", answer) if x.strip()]
        if want and len(want) == len(got) and all(w == g for w, g in zip(want, got)):
            return {"verdict": "correct", "score": 1, "feedback": ""}
    return None  # AI가 채점


def grade_prompt(q: dict, answer: str) -> str:
    rubric = "\n".join(f"- {r}" for r in q.get("rubric") or [])
    return (f"<question type=\"{TYPE_LABEL[q['type']]}\">{q['question']}</question>\n<model_answer>{q['answer']}</model_answer>\n"
            f"<also_accept>{', '.join(q.get('accept') or [])}</also_accept>\n<rubric>\n{rubric}\n</rubric>\n<student_answer>{answer}</student_answer>")
