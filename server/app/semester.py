"""학기 전체 보기 (여러 강의자료·여러 강의를 잇는다), 시험 D-day 계획, 내보내기.

- 개념 지도: 강의 중 잡힌 용어(용어 사전)를 학기 전체에서 모아, 같은 쪽·이웃 쪽에서 함께 나왔거나
  한 용어의 뜻에 다른 용어가 들어 있으면 잇는다. 3D가 아니라 폰에서 읽히는 2D 지도로 그린다.
- 학기 튜터: 모든 강의의 쪽 중에서 질문과 가까운 쪽 몇 개만 골라 근거로 넘긴다 (강의 이름과 쪽을 함께).
- 시험 D-day: 시험 범위 자료의 유력한 쪽을 남은 날에 나눠 담고, 마지막 날은 족보 노트 전체 복습.
- 내보내기: Markdown(노션에 그대로 붙여 넣으면 제목·목록이 살아남), Anki(탭으로 나눈 앞면·뒷면 텍스트).
"""

import datetime as dt
import re

from .alignment import _grams
from .study import _cosine

TYPE_LABEL = {"explanation": "보충설명", "example": "예시", "emphasis": "강조", "exam": "시험", "notice": "공지",
              "tip": "AI 팁", "qa": "질문"}


MEETING_LABEL = {"emphasis": "결정", "explanation": "논의", "example": "근거", "notice": "일정", "qa": "미결"}


def term_key(term: str) -> str:
    return re.sub(r"[\s\W_]+", "", term.lower())


def concept_map(lectures: list[dict]) -> dict:
    """lectures: [{doc_id, doc_title, session_id, started_at, terms: [...]}] → {nodes, edges}"""
    nodes: dict[str, dict] = {}
    for lec in lectures:
        for t in lec["terms"]:
            key = term_key(t["term"])
            if len(key) < 2:
                continue
            node = nodes.setdefault(key, {"id": key, "term": t["term"], "definition": t["definition"], "occurrences": [],
                                          "docs": []})
            node["occurrences"].append({"doc_id": lec["doc_id"], "doc_title": lec["doc_title"], "session_id": lec["session_id"],
                                        "page_no": t["page_no"], "start_ms": t["start_ms"], "started_at": lec["started_at"]})
            if lec["doc_id"] not in node["docs"]:
                node["docs"].append(lec["doc_id"])

    edges: dict[tuple[str, str], dict] = {}

    def link(a: str, b: str, why: str) -> None:
        if a == b:
            return
        k = tuple(sorted((a, b)))
        e = edges.setdefault(k, {"source": k[0], "target": k[1], "weight": 0, "reasons": []})
        e["weight"] += 1
        if why not in e["reasons"]:
            e["reasons"].append(why)

    # 같은 강의에서 같은 쪽이거나 바로 이웃한 쪽에서 나온 용어
    for lec in lectures:
        found = [(term_key(t["term"]), t["page_no"]) for t in lec["terms"] if len(term_key(t["term"])) >= 2]
        for i, (a, pa) in enumerate(found):
            for b, pb in found[i + 1:]:
                if pa is not None and pb is not None and abs(pa - pb) <= 1:
                    link(a, b, "같은 부분에서 설명")
    # 뜻풀이에 다른 용어가 들어 있음
    for a, node in nodes.items():
        definition = term_key(node["definition"])
        for b, other in nodes.items():
            if b != a and len(b) >= 2 and b in definition:
                link(a, b, f"'{node['term']}' 뜻에 '{other['term']}'이 나옴")

    for node in nodes.values():
        node["count"] = len(node["occurrences"])
        node["links"] = sum(1 for e in edges.values() if node["id"] in (e["source"], e["target"]))
    return {"nodes": sorted(nodes.values(), key=lambda n: (-n["count"], -n["links"], n["term"])),
            "edges": sorted(edges.values(), key=lambda e: -e["weight"])}


def semester_context(chunks: list[dict], question: str, limit: int = 4) -> tuple[str, list[dict]]:
    """chunks: [{doc_title, doc_id, session_id, page_no, slide, speech, notes}] → 튜터 문맥, 고른 쪽들(번호 1부터)"""
    query = _grams(question)
    ranked = sorted(chunks, key=lambda c: -_cosine(query, _grams(f"{c['doc_title']} {c['slide']} {c['speech']}")))
    chosen = ranked[:limit]
    parts = []
    for i, c in enumerate(chosen, start=1):
        notes = "\n".join(f"- ({n['type']}) {n['text']}" for n in c["notes"]) or "(없음)"
        parts.append(f'<page no="{i}">\n<lecture>{c["doc_title"]} {c["page_no"]}쪽</lecture>\n<slide>\n{c["slide"] or "(없음)"}\n</slide>\n'
                     f"<speech>\n{c['speech'][:2500]}\n</speech>\n<notes>\n{notes}\n</notes>\n</page>")
    return "\n\n".join(parts), chosen


def exam_plan(title: str, exam_date: str, today: dt.date, pages: list[dict], due_cards: int, confused_open: int) -> dict:
    """pages: [{doc_id, doc_title, page_no, title, score, reasons}] 점수 높은 순. → 날마다 할 일"""
    exam = dt.date.fromisoformat(exam_date)
    days_left = (exam - today).days
    if days_left < 0:
        return {"title": title, "exam_date": exam_date, "days_left": days_left, "days": []}
    study_days = max(days_left, 1)  # 시험 전날까지 (오늘이 시험날이면 오늘 하루)
    plan_days = [{"date": (today + dt.timedelta(days=i)).isoformat(), "d": days_left - i, "pages": [], "todo": []}
                 for i in range(study_days)]
    learn_days = plan_days[:-1] if len(plan_days) > 1 else plan_days
    for i, page in enumerate(p for p in pages if p["score"] > 0):
        learn_days[i % len(learn_days)]["pages"].append(page)

    for i, day in enumerate(plan_days):
        if due_cards and i == 0:
            day["todo"].append(f"오늘의 복습 카드 {due_cards}장")
        elif i > 0:
            day["todo"].append("오늘의 복습 카드 (어제 틀린 것 포함)")
        if i == 0 and confused_open:
            day["todo"].append(f"헷갈렸던 곳 {confused_open}개 설명 보기 (공부하기 › 모르겠다)")
        if day["pages"]:
            day["todo"].append(f"유력한 쪽 {len(day['pages'])}개 다시 보기 · 플래시카드 만들기")
    plan_days[-1]["todo"].append("족보 노트 처음부터 끝까지 · 예상 문제 답 가리고 풀기")
    return {"title": title, "exam_date": exam_date, "days_left": days_left, "days": plan_days}


def session_markdown(doc: dict, started_at: float, pages: list[dict], notes: list[dict], summary: dict | None,
                     terms: list[dict], tasks: list[dict], marks: list[dict]) -> str:
    when = dt.datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M")
    out = [f"# {doc['title']}", "", f"{when} 강의 · 필기 {sum(1 for n in notes if not n['pending'])}개", ""]
    if summary and summary.get("overview"):
        out += ["## 한눈에 보는 강의", "", summary["overview"], ""]
    page_summary = {p["page_no"]: p["summary"] for p in (summary or {}).get("pages", [])}
    for page in pages:
        mine = [n for n in notes if n["page_no"] == page["page_no"] and not n["pending"]]
        if not mine and page["page_no"] not in page_summary:
            continue
        heading = (page.get("text") or "").strip().split("\n")[0][:60]
        out.append(f"## {page['page_no']}쪽{f' · {heading}' if heading else ''}")
        out.append("")
        if page["page_no"] in page_summary:
            out += ["> " + " ".join(page_summary[page["page_no"]].split()), ""]
        for n in mine:
            text = n["text"].replace("\n", " ")
            labels = MEETING_LABEL if doc.get("kind") == "meeting" else TYPE_LABEL
            out.append(f"- **{labels.get(n['type'], TYPE_LABEL.get(n['type'], n['type']))}** {text}")
        out.append("")
    if marks:
        out += ["## 헷갈렸던 곳", ""]
        out += [f"- {m['page_no']}쪽: {m['explanation'] or m['speech'][-120:]}" for m in marks]
        out.append("")
    if terms:
        out += ["## 용어 사전", ""]
        out += [f"- **{t['term']}** — {t['definition']}" for t in terms]
        out.append("")
    if tasks:
        out += ["## 할 일" if doc.get("kind") == "meeting" else "## 과제", ""]
        out += [f"- [{'x' if t['done'] else ' '}] {t['title']}{f' ({t['due_text']})' if t['due_text'] else ''} — {t['instructions']}" for t in tasks]
        out.append("")
    if summary and summary.get("quiz"):
        out += ["## 복습 퀴즈", ""]
        for i, q in enumerate(summary["quiz"], start=1):
            out.append(f"{i}. {q['question']}")
            out += [f"   - {c}" for c in q["choices"]]
            out.append(f"   - 정답: {q['choices'][q['answer_index']] if 0 <= q['answer_index'] < len(q['choices']) else '?'} — {q['explanation']}")
        out.append("")
    return "\n".join(out)


def anki_text(title: str, cards: list[tuple[str, str, str]]) -> str:
    """Anki '텍스트 파일 가져오기' 형식: 앞면<TAB>뒷면<TAB>태그"""
    tag = re.sub(r"\s+", "_", title.strip())[:40] or "강의노트"
    lines = ["#separator:tab", "#html:false", "#tags column:3"]
    for front, back, kind in cards:
        clean = [re.sub(r"[\t\r\n]+", " ", x).strip() for x in (front, back)]
        if clean[0] and clean[1]:
            lines.append(f"{clean[0]}\t{clean[1]}\t{tag} {kind}")
    return "\n".join(lines) + "\n"
