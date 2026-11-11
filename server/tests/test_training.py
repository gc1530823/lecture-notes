"""우리 AI 학습 데이터: 모으기(training_log) → 고친 기록(feedback) → 내보내기(export_training) → 채점(eval_model)"""

import asyncio
import dataclasses
import importlib.util
import json
import os

os.environ.setdefault("LLM_MODE", "fake")

import httpx  # noqa: E402

from app import training_log  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.ollama_llm import OllamaLLM  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_records_requests_only_when_enabled(tmp_path, monkeypatch):
    reply = {"annotations": [{"page_no": 1, "block_id": 7, "type": "exam", "text": "시험 출제"}], "tasks": [], "terms": []}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": json.dumps(reply, ensure_ascii=False)}})

    llm = OllamaLLM(transport=httpx.MockTransport(handler))
    candidates = [{"page_no": 1, "page_id": 1, "blocks": [{"id": 7, "text": "경사하강법"}], "existing": []}]

    monkeypatch.setattr(training_log, "settings", dataclasses.replace(settings, training_log=False, training_dir=str(tmp_path)))
    asyncio.run(llm.annotate(candidates, "이거 시험에 나와요", []))
    assert not list(tmp_path.iterdir())

    monkeypatch.setattr(training_log, "settings", dataclasses.replace(settings, training_log=True, training_dir=str(tmp_path)))

    async def in_session():
        training_log.current_session.set("s1")
        await llm.annotate(candidates, "이거 시험에 나와요", [], notebook=True)

    asyncio.run(in_session())
    [path] = tmp_path.iterdir()
    [entry] = [json.loads(line) for line in path.read_text().splitlines()]
    assert entry["task"] == "annotate"  # 노트 모드 프롬프트도 같은 작업
    assert entry["session_id"] == "s1"
    assert entry["output"] == reply
    assert "이거 시험에 나와요" in entry["prompt"]


def test_feedback_keeps_first_ai_text(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    doc = db.create_document("강의", [{"page_no": 1, "width": 1, "height": 1, "text": "a", "blocks": [{"x": 0, "y": 0, "w": 1, "h": 1, "text": "a"}]},
                                       {"page_no": 2, "width": 1, "height": 1, "text": "b", "blocks": []}], [])
    pages = db.get_document(doc)["pages"]
    sid = db.create_session(doc)
    a = db.add_annotation(sid, pages[0]["id"], None, "explanation", "AI가 쓴 글", 0)
    b = db.add_annotation(sid, pages[0]["id"], None, "tip", "틀린 필기", 0)
    c = db.add_annotation(sid, pages[0]["id"], None, "example", "쪽이 틀린 필기", 0, pending=True)
    db.update_annotation(a["id"], "한 번 고침")
    db.update_annotation(a["id"], "두 번 고침")
    db.delete_annotation(b["id"])
    db.move_annotation(c["id"], pages[1]["id"])

    export = load_script("export_training")
    fixes = export.corrections(db.list_feedback())
    assert fixes[(sid, "AI가 쓴 글")] == {"deleted": False, "text": "두 번 고침", "page_no": None}
    assert fixes[(sid, "틀린 필기")]["deleted"] is True
    assert fixes[(sid, "쪽이 틀린 필기")]["page_no"] == 2

    record = {"session_id": sid, "output": {"annotations": [
        {"page_no": 1, "block_id": 1, "type": "explanation", "text": "AI가 쓴 글"},
        {"page_no": 1, "block_id": 1, "type": "tip", "text": "틀린 필기"},
        {"page_no": 1, "block_id": 1, "type": "example", "text": "쪽이 틀린 필기"},
        {"page_no": 1, "block_id": 2, "type": "exam", "text": "그대로 둔 필기"},
    ], "tasks": []}}
    output, changed = export.apply_corrections(record, fixes)
    assert changed == 3
    assert [n["text"] for n in output["annotations"]] == ["두 번 고침", "쪽이 틀린 필기", "그대로 둔 필기"]
    assert output["annotations"][1]["page_no"] == 2


def test_export_dedupes_and_splits_by_lecture(tmp_path, monkeypatch, capsys):
    export = load_script("export_training")
    raw = tmp_path / "raw-202611.jsonl"
    lines = []
    for i in range(40):
        lines.append({"id": f"r{i}", "task": "annotate", "session_id": f"s{i % 8}", "system": "S", "prompt": f"P{i}",
                      "schema": {"type": "object"}, "output": {"annotations": [], "tasks": []}, "model": "groq:x"})
    lines.append(dict(lines[0], id="dup"))  # 같은 요청 한 번 더
    raw.write_text("\n".join(json.dumps(x) for x in lines) + "\n" + '{"깨진 줄', encoding="utf-8")
    monkeypatch.setattr(export, "settings", dataclasses.replace(settings, training_dir=str(tmp_path), db_path=str(tmp_path / "none.db")))
    out = tmp_path / "out"
    export.main(str(out), None, 0.25)

    train = [json.loads(x) for x in (out / "train.jsonl").read_text().splitlines()]
    val = [json.loads(x) for x in (out / "val.jsonl").read_text().splitlines()]
    assert len(train) + len(val) == 40
    assert train[0]["messages"][0] == {"role": "system", "content": "S"}
    assert json.loads(train[0]["messages"][2]["content"]) == {"annotations": [], "tasks": []}
    # 같은 강의의 요청은 한쪽에만
    sessions_train = {int(r["messages"][1]["content"][1:]) % 8 for r in train}
    sessions_val = {int(r["messages"][1]["content"][1:]) % 8 for r in val}
    assert not sessions_train & sessions_val


def test_eval_scores_annotations():
    ev = load_script("eval_model")
    gold = {"annotations": [{"block_id": 3, "type": "exam", "text": "경사하강법은 시험에 나온다"}]}
    good = {"annotations": [{"block_id": 3, "type": "exam", "text": "경사하강법 시험에 나옴"}]}
    bad = {"annotations": [{"block_id": 9, "type": "tip", "text": "전혀 다른 말"}, {"block_id": 1, "type": "tip", "text": "또 다른 말"}]}
    g = ev.score_annotate(good, gold)
    b = ev.score_annotate(bad, gold)
    assert g["block_ok"] == 1 and g["type_ok"] == 1 and g["count_ok"] == 1 and g["text_f1"] > 0.5
    assert b["block_ok"] == 0 and b["count_ok"] == 0 and b["text_f1"] < 0.2
    assert ev.score_annotate({"annotations": []}, {"annotations": []})["silent_ok"] == 1


def test_spaced_repetition_intervals_grow_and_lapses_reset():
    from app.review import schedule

    card = {"ease": 2.5, "interval": 0.0, "reps": 0, "lapses": 0}
    c1 = schedule(card, 2, now=0)
    c2 = schedule(c1, 2, now=0)
    c3 = schedule(c2, 2, now=0)
    assert (c1["interval"], c2["interval"]) == (1.0, 3.0) and c3["interval"] == 7.5
    easy = schedule(c2, 3, now=0)
    assert easy["interval"] > c3["interval"] and easy["ease"] > c2["ease"]
    lapse = schedule(c3, 0, now=0)
    assert lapse["reps"] == 0 and lapse["lapses"] == 1 and lapse["due_at"] == 600 and lapse["ease"] == 2.3
    worst = card
    for _ in range(20):
        worst = schedule(worst, 0, now=0)
    assert worst["ease"] == 1.3  # 너무 낮아지지 않는다


def test_live_audio_flags_a_chunk_spoken_louder_than_usual():
    from app.live_stt import LiveAudio

    async def run():
        audio = LiveAudio(None, "", None)
        audio.levels = [1000.0] * 8
        audio.speech_energy, audio.speech_frames = 1150.0, 1
        normal = audio._loud()
        audio.speech_energy, audio.speech_frames = 2000.0, 1
        loud = audio._loud()
        audio._queue.put_nowait(None)
        await audio._worker
        return normal, loud

    assert asyncio.run(run()) == (False, True)


def test_export_prefers_hindsight_answer_and_skips_student_outputs(tmp_path, monkeypatch):
    export = load_script("export_training")
    base = {"task": "annotate", "session_id": "s1", "system": "S", "schema": {"type": "object"}, "model": "groq:x"}
    rows = [
        {**base, "id": "a", "prompt": "P1", "output": {"annotations": [{"text": "실시간 답"}], "tasks": []}},
        {**base, "id": "h", "prompt": "P1", "output": {"annotations": [{"text": "다 보고 쓴 답"}], "tasks": []}, "hindsight_of": "a"},
        {**base, "id": "b", "prompt": "P2", "output": {"annotations": [], "tasks": []}, "model": "ollama:lecture-notes"},
    ]
    (tmp_path / "raw-202611.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    monkeypatch.setattr(export, "settings", dataclasses.replace(settings, training_dir=str(tmp_path), db_path=str(tmp_path / "x.db")))
    export.main(str(tmp_path / "out"), None, 0.0)
    [row] = [json.loads(x) for x in (tmp_path / "out" / "train.jsonl").read_text().splitlines()]
    assert row["messages"][1]["content"] == "P1"  # 입력은 실시간 요청 그대로
    assert json.loads(row["messages"][2]["content"])["annotations"][0]["text"] == "다 보고 쓴 답"


def test_hindsight_context_adds_what_came_next_and_the_summary(tmp_path):
    relabel = load_script("relabel_hindsight")
    db = Database(str(tmp_path / "t.db"))
    doc = db.create_document("강의", [{"page_no": 1, "width": 1, "height": 1, "text": "a", "blocks": []}], [])
    sid = db.create_session(doc)
    page = db.get_document(doc)["pages"][0]["id"]
    for i, text in enumerate(["자 오늘은 경사하강법입니다.", "학습률이 크면 발산해요.", "그래서 작게 잡는 게 중요합니다.", "다음은 역전파예요."]):
        db.add_segment(sid, page, i * 1000, i * 1000 + 900, text)
    db.save_summary(sid, {"overview": "경사하강법과 역전파", "pages": [{"page_no": 1, "summary": "학습률 설명"}]})
    record = {"session_id": sid, "prompt": "<slide/>\n\n<new_speech>\n자 오늘은 경사하강법입니다. 학습률이 크면 발산해요.\n</new_speech>"}
    extra = relabel.context_for(record, db)
    assert "그래서 작게 잡는 게 중요합니다." in extra and "다음은 역전파예요." in extra
    assert "학습률이 크면 발산해요." not in extra.split("<after_speech>")[1].split("</after_speech>")[0]
    assert "경사하강법과 역전파" in extra
    assert relabel.context_for({**record, "session_id": "없는 강의"}, db) is None


def test_slide_truth_matches_video_frames_to_pages_and_scores_tracking():
    import numpy as np

    st = load_script("slide_truth")
    rng = np.random.default_rng(0)
    base = np.full((st.H, st.W), 250.0)
    base[:6] = 60  # 모든 쪽에 같은 제목 띠 (공통 바탕은 빼고 비교해야 한다)
    pages = []
    for i in range(5):
        page = base.copy()
        page[10 + i * 6: 14 + i * 6, 8: 8 + 10 * (i + 1)] = 30  # 쪽마다 다른 글 덩어리
        pages.append(page)
    pages = np.stack(pages)
    camera = rng.uniform(40, 200, (st.H, st.W))
    # 화면비가 달라 위아래에 검은 띠가 생긴 영상: 쪽 전체를 줄여 가운데에 넣는다
    letterbox = lambda img: np.vstack([np.full((6, st.W), 16.0), img[np.linspace(0, st.H - 1, st.H - 12).astype(int)], np.full((6, st.W), 16.0)])
    frames = np.stack([pages[0], pages[0], letterbox(pages[2]), pages[2] + rng.normal(0, 8, pages[2].shape), camera, pages[1]])
    truth = st.match(frames, pages)
    assert truth[:4] == [1, 1, 3, 3] and truth[4] is None and truth[5] == 2
    transcript = "[00:00] (1쪽) 가\n[00:06] (3쪽) 나\n[00:10] (4쪽) 다 (틀린 쪽)\n"
    s = st.score(truth, transcript)
    assert s["sentences"] == 3 and abs(s["exact"] - 2 / 3) < 1e-6


def test_hybrid_sends_live_work_to_teacher_and_after_lecture_work_to_our_ai():
    from app.hybrid import HybridLLM

    calls = []

    class Teacher:
        async def annotate(self, *a, **k):
            calls.append("teacher.annotate"); return {"annotations": []}
        async def study_page(self, *a, **k):
            calls.append("teacher.study_page"); return [{"front": "선생님", "back": "답"}]
        async def summarize(self, *a, **k):
            calls.append("teacher.summarize"); return {"overview": "선생님 요약"}
        async def warm_up(self):
            pass

    class Student:
        async def annotate(self, *a, **k):
            raise AssertionError("수업 중 필기는 우리 AI가 하지 않는다")
        async def study_page(self, *a, **k):
            calls.append("student.study_page"); return [{"front": "우리 AI", "back": "답"}]
        async def summarize(self, *a, **k):
            calls.append("student.summarize"); raise RuntimeError("Ollama 꺼짐")
        async def warm_up(self):
            raise RuntimeError("꺼짐")

    llm = HybridLLM(Teacher(), Student())

    async def run():
        await llm.warm_up()
        await llm.annotate([], "", [])
        cards = await llm.study_page("flashcards", {}, "", [])
        summary = await llm.summarize([], [], [])
        return cards, summary

    cards, summary = asyncio.run(run())
    assert cards[0]["front"] == "우리 AI" and summary["overview"] == "선생님 요약"
    assert calls == ["teacher.annotate", "student.study_page", "student.summarize", "teacher.summarize"]
