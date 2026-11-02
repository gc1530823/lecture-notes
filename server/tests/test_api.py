import dataclasses
import os
import tempfile
import time

os.environ["LLM_MODE"] = "fake"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
os.environ["MIN_CHARS_PER_CALL"] = "20"

import pymupdf  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.llm import ClaudeLLM, _annotation_prompt  # noqa: E402
from app.main import app  # noqa: E402
from app.pdf_parser import extract_keywords, parse_pdf  # noqa: E402


def make_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Gradient Descent")
    page.insert_text((72, 300), "learning rate controls step size")
    page = doc.new_page()
    page.insert_text((72, 72), "Backpropagation")
    return doc.tobytes()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def receive(ws, kind: str = "annotation_added") -> dict:
    """page_estimate 같은 다른 이벤트는 건너뛰고 원하는 이벤트를 받는다."""
    while True:
        event = ws.receive_json()
        assert event["type"] in ("page_estimate", "annotation_added", "task_added", "annotation_preview",
                                 "previews_resolved", "heard", "spoken", "page_added", "page_title"), event
        if event["type"] == kind:
            return event


def receive_annotation(ws) -> dict:
    return receive(ws)["annotation"]


def upload(client) -> dict:
    res = client.post("/documents", files={"file": ("ml.pdf", make_pdf(), "application/pdf")})
    assert res.status_code == 200, res.text
    return res.json()


def test_parse_pdf_normalizes_blocks():
    pages = parse_pdf(make_pdf())
    assert [p["page_no"] for p in pages] == [1, 2]
    first = pages[0]["blocks"][0]
    assert first["text"] == "Gradient Descent"
    assert 0 < first["x"] < 1 and 0 < first["y"] < 0.2
    assert "Gradient" in extract_keywords(pages)


def test_upload_rejects_non_pdf(client):
    res = client.post("/documents", files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
    assert res.status_code == 400


def test_live_session_annotation_edit_and_summary(client):
    doc = upload(client)
    assert doc["title"] == "ml"
    assert len(doc["pages"]) == 2
    block_id = doc["pages"][0]["blocks"][0]["id"]

    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "이 부분은 시험에 꼭 나옵니다. 학습률이 너무 크면 발산해요.",
                      "start_ms": 1000, "end_ms": 4000})
        ann = receive_annotation(ws)
    assert ann["page_no"] == 1 and ann["block_id"] == block_id and ann["type"] == "exam"
    assert ann["pending"] is False
    assert ann["start_ms"] == 1000

    res = client.patch(f"/annotations/{ann['id']}", json={"text": "학습률이 크면 발산"})
    assert res.json()["edited_by_user"] is True

    res = client.post(f"/sessions/{session['id']}/end")
    assert res.json()["status"] in ("processing", "done")
    for _ in range(50):
        summary = client.get(f"/sessions/{session['id']}/summary").json()
        if summary["status"] == "done":
            break
        time.sleep(0.05)
    assert summary["status"] == "done"
    assert summary["summary"]["quiz"][0]["page_no"] == 1
    assert summary["summary"]["tips"][0]["url"].startswith("https://")

    assert client.delete(f"/annotations/{ann['id']}").status_code == 204
    assert client.get(f"/sessions/{session['id']}/annotations").json() == []


def test_unknown_page_reports_error(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 99})
        assert ws.receive_json()["type"] == "error"


def test_claude_request_shape():
    params = ClaudeLLM._request("claude-opus-5-5", "low", "sys", "prompt", {"type": "object"}, 100)
    assert params["fallbacks"] == "default"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in ClaudeLLM._request("claude-haiku-5-5", "low", "s", "p", {}, 100)
    prompt = _annotation_prompt([{"page_no": 2, "blocks": [{"id": 3, "text": "Gradient"}], "existing": []}], "설명",
                                [{"title": "과제 1"}])
    assert '<slide page_no="2">' in prompt and "[3] Gradient" in prompt and "- 과제 1" in prompt


def test_uncertain_page_goes_to_pending_and_can_be_placed(client, monkeypatch):
    import app.live_session as live

    # 추정 확신을 늘 낮게 만들어 후보 페이지 모드로 보낸다
    monkeypatch.setattr(live, "settings", dataclasses.replace(live.settings, page_confidence=1.01))
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "transcript_final", "text": "이건 좀 애매한 이야기인데 여러 군데 다 해당돼요",
                      "start_ms": 0, "end_ms": 3000})
        ann = receive_annotation(ws)
    assert ann["pending"] is True and ann["block_id"] is None

    placed = client.patch(f"/annotations/{ann['id']}", json={"page_no": 2}).json()
    assert placed["pending"] is False and placed["page_no"] == 2
    assert client.patch(f"/annotations/{ann['id']}", json={"page_no": 9}).status_code == 400


def test_parse_tips_keeps_only_linked_items():
    from app.llm import parse_tips

    text = '찾았어요.\n```json\n{"tips": [{"page_no": 1, "title": "a", "text": "b", "url": "https://x.org"},' \
           ' {"page_no": 2, "title": "c", "text": "d", "url": "없음"}]}\n```'
    assert parse_tips(text) == [{"page_no": 1, "title": "a", "text": "b", "url": "https://x.org"}]



def test_task_is_detected_and_drafted(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "transcript_final", "text": "과제는 경사하강법을 직접 구현해서 다음 주 금요일까지 내세요.",
                      "start_ms": 0, "end_ms": 3000})
        task = receive(ws, "task_added")["task"]
    assert task["kind"] == "homework" and task["due_text"] == "다음 주 금요일까지" and task["done"] is False

    drafted = client.post(f"/tasks/{task['id']}/draft").json()
    assert drafted["draft"]["outline"] == ["서론", "본론", "결론"]
    assert client.patch(f"/tasks/{task['id']}", json={"done": True}).json()["done"] is True
    assert len(client.get(f"/sessions/{session['id']}/tasks").json()) == 1
    assert client.post("/tasks/9999/draft").status_code == 404


def test_instant_preview_arrives_before_ai_note_and_is_resolved(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "transcript_final", "text": "이 부분은 시험에 꼭 나옵니다. 학습률이 너무 크면 발산해요.",
                      "start_ms": 0, "end_ms": 3000})
        order = []
        while "previews_resolved" not in order:
            event = ws.receive_json()
            order.append(event["type"])
            if event["type"] == "annotation_preview":
                assert event["preview"]["type"] == "exam" and event["preview"]["id"].startswith("p")
    assert order.index("annotation_preview") < order.index("annotation_added") < order.index("previews_resolved")


def test_task_without_directive_is_dropped(client, monkeypatch):
    import app.llm as llm_module

    async def eager(self, candidates, transcript, existing_tasks):
        # 작은 모델처럼 "시험에 나온다"를 과제로 잘못 뽑는 경우
        return {"annotations": [], "tasks": [{"kind": "exam_prep", "title": "시험 준비", "instructions": "학습률",
                                              "due_text": ""}]}

    monkeypatch.setattr(llm_module.FakeLLM, "annotate", eager)
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "transcript_final", "text": "이거 중간고사에 꼭 나와요. 학습률 차이 기억하세요.",
                      "start_ms": 0, "end_ms": 3000})
        receive(ws, "previews_resolved")
    assert client.get(f"/sessions/{session['id']}/tasks").json() == []


def test_audio_file_becomes_a_lecture_with_notes_and_summary(client):
    from app.main import app as fastapi_app
    from app.stt import Segment

    class FakeTranscriber:
        def transcribe(self, path, hint="", on_progress=None):
            assert open(path, "rb").read() == b"fake-audio"
            on_progress(1.0)
            return [Segment(0, 4000, "경사하강법은 기울기 반대 방향으로 이동해요. 이거 시험에 꼭 나와요."),
                    Segment(5000, 9000, "다음 장, 역전파입니다. 과제는 역전파 계산을 다음 주까지 제출하세요.")]

    fastapi_app.state.transcriber = FakeTranscriber()
    doc = upload(client)
    res = client.post("/sessions/from-audio", data={"document_id": doc["id"]},
                      files={"file": ("memo.m4a", b"fake-audio", "audio/mp4")})
    assert res.status_code == 200, res.text
    session = res.json()
    for _ in range(100):
        summary = client.get(f"/sessions/{session['id']}/summary").json()
        if summary["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert summary["status"] == "done"
    notes = client.get(f"/sessions/{session['id']}/annotations").json()
    assert {n["page_no"] for n in notes} == {1, 2}
    assert len(client.get(f"/sessions/{session['id']}/tasks").json()) == 1


def test_document_list_and_delete(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    listed = {d["id"]: d for d in client.get("/documents").json()}
    assert listed[doc["id"]]["sessions"][0]["id"] == session["id"]
    assert client.get(f"/documents/{doc['id']}/pdf").status_code == 200
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    assert doc["id"] not in {d["id"] for d in client.get("/documents").json()}
    assert client.get(f"/documents/{doc['id']}/pdf").status_code == 404


def test_live_audio_is_transcribed_by_whisper_and_annotated(client):
    import numpy as np

    from app.main import app as fastapi_app
    from app.stt import Segment

    heard_lengths = []

    class FakeWhisper:
        def transcribe(self, audio, hint="", on_progress=None):
            heard_lengths.append(len(audio))
            return [Segment(0, 1000, "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.")]

    fastapi_app.state.transcriber = FakeWhisper()
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    t = np.arange(16000 * 2) / 16000
    speech = (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16)   # 2초 동안 "말소리"
    silence = np.zeros(16000, dtype=np.int16)                         # 1초 침묵 → 문장 끝
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1, "initial": True})
        for chunk in np.array_split(np.concatenate([silence, speech, silence]), 20):
            ws.send_bytes(chunk.tobytes())
        heard = receive(ws, "heard")
        ann = receive_annotation(ws)
    assert heard["text"].startswith("학습률이")
    assert ann["type"] == "exam" and ann["page_no"] == 1
    # 앞 침묵은 0.3초만 남기고 버렸다: 0.3초 + 말 2초 + 문장 끝 침묵 0.7초
    assert 16000 * 2.9 <= heard_lengths[0] <= 16000 * 3.2
    wavs = [n for n in os.listdir(os.environ["UPLOAD_DIR"]) if n.startswith(session["id"]) and n.endswith(".wav")]
    assert wavs, "수업 녹음이 남아야 한다"


def test_notes_pdf_has_annotated_slides_full_notes_and_reuses_cache(client):
    from app.main import app as fastapi_app

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.",
                      "start_ms": 1000, "end_ms": 4000})
        receive_annotation(ws)

    calls = []
    original = fastapi_app.state.llm.organize_page

    async def counting(page, speech, notes):
        calls.append(page["page_no"])
        return await original(page, speech, notes)

    fastapi_app.state.llm.organize_page = counting
    try:
        assert client.get(f"/sessions/{session['id']}/notes-pdf").status_code == 404
        res = client.post(f"/sessions/{session['id']}/notes-pdf")
        assert res.status_code == 202
        assert client.get(f"/sessions/{session['id']}/notes-pdf/status").json()["status"] == "ready"
        pdf = client.get(f"/sessions/{session['id']}/notes-pdf")
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
        text = "".join(p.get_text() for p in pymupdf.open("pdf", pdf.content)).replace("\xa0", " ")
        assert "1쪽" in text and "정리 노트" in text and "시험" in text and "발산" in text
        assert calls == [1]

        # 받아쓰기·필기가 그대로면 다시 만들어도 AI를 부르지 않는다
        client.post(f"/sessions/{session['id']}/notes-pdf")
        assert calls == [1]
    finally:
        fastapi_app.state.llm.organize_page = original

    client.delete(f"/documents/{doc['id']}")
    assert client.get(f"/sessions/{session['id']}/notes-pdf").status_code == 404


def test_notes_pdf_drops_exam_mark_on_pages_without_exam_talk(client):
    from app.main import app as fastapi_app

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률은 이동 크기를 정하는 값이에요. 너무 크면 발산합니다.",
                      "start_ms": 1000, "end_ms": 4000})
        receive_annotation(ws)

    original = fastapi_app.state.llm.organize_page

    async def marks_everything(page, speech, notes):
        return ["학습률: 이동 크기를 정한다 (★시험)"]

    fastapi_app.state.llm.organize_page = marks_everything
    try:
        client.post(f"/sessions/{session['id']}/notes-pdf")
    finally:
        fastapi_app.state.llm.organize_page = original
    pdf = client.get(f"/sessions/{session['id']}/notes-pdf")
    text = "".join(p.get_text() for p in pymupdf.open("pdf", pdf.content)).replace("\xa0", " ")
    assert "학습률: 이동 크기를 정한다" in text and "★" not in text


def test_notes_pdf_uses_fixed_speech_when_llm_offers_it(client):
    from app.main import app as fastapi_app

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습할 때 유런 일부를 무작위로 꺼버리는 거예요.",
                      "start_ms": 1000, "end_ms": 4000})
        receive_annotation(ws)

    async def fix_speech(page, speech):
        return speech.replace("유런", "뉴런")

    fastapi_app.state.llm.fix_speech = fix_speech
    try:
        client.post(f"/sessions/{session['id']}/notes-pdf")
    finally:
        del fastapi_app.state.llm.fix_speech
    pdf = client.get(f"/sessions/{session['id']}/notes-pdf")
    text = "".join(p.get_text() for p in pymupdf.open("pdf", pdf.content)).replace("\xa0", " ")
    explained = text.split("교수님 설명 (받아쓰기)")[1]
    assert "뉴런 일부를" in explained and "유런" not in explained


def test_ask_answers_from_recent_speech_and_sticks_a_question_note(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 최솟값을 지나쳐서 발산해요.",
                      "start_ms": 1000, "end_ms": 4000})
        receive_annotation(ws)

    res = client.post(f"/sessions/{session['id']}/ask", json={"question": "발산이 뭐예요?", "page_no": 1})
    assert res.status_code == 200, res.text
    note = res.json()
    assert note["type"] == "qa" and note["page_no"] == 1
    assert note["text"].startswith("Q. 발산이 뭐예요?\nA. ") and "발산해요" in note["text"]
    assert note["block_id"] == doc["pages"][0]["blocks"][0]["id"]

    # 질문 없이 누르면 "방금 설명 다시"로 묻는다
    quick = client.post(f"/sessions/{session['id']}/ask", json={"page_no": 1}).json()
    assert "쉽게 다시 설명" in quick["text"]
    assert client.post(f"/sessions/{session['id']}/ask", json={"page_no": 9}).status_code == 404
    assert any(a["type"] == "qa" for a in client.get(f"/sessions/{session['id']}/annotations").json())


def test_exam_map_scores_pages_and_predicts_questions(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.",
                      "start_ms": 1000, "end_ms": 4000})
        receive_annotation(ws)

    result = client.get(f"/documents/{doc['id']}/exam-map").json()
    assert result["lectures"] == 1 and result["top"] == [1] and result["questions"] == []
    first = result["pages"][0]
    assert first["level"] == "high" and "교수님이 시험에 나온다고 함 1번" in first["reasons"]
    assert result["pages"][1]["level"] == "low"

    assert client.post(f"/documents/{doc['id']}/exam-questions").status_code == 202
    result = client.get(f"/documents/{doc['id']}/exam-map").json()
    assert result["job"]["status"] == "idle"
    assert result["questions"][0]["page_no"] == 1 and result["questions"][0]["stale"] is False
    assert "1쪽 내용을 설명하시오." == result["questions"][0]["questions"][0]["question"]
    assert client.get("/documents/nope/exam-map").status_code == 404


def test_reconnect_continues_timeline_and_audio_plays_from_any_point(client):
    import io
    import wave

    import numpy as np

    from app.main import app as fastapi_app
    from app.stt import Segment

    class FakeWhisper:
        def transcribe(self, audio, hint="", on_progress=None):
            return [Segment(0, 1000, "학습률이 너무 크면 발산해요.")]

    fastapi_app.state.transcriber = FakeWhisper()
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    assert client.get(f"/sessions/{session['id']}/audio").status_code == 404
    t = np.arange(16000 * 2) / 16000
    clip = np.concatenate([np.zeros(16000, np.int16), (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16),
                           np.zeros(16000, np.int16)])                        # 4초
    for _ in range(2):  # 끊겼다가 다시 연결
        with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
            ws.send_json({"type": "page_view", "page": 1, "initial": True})
            for chunk in np.array_split(clip, 10):
                ws.send_bytes(chunk.tobytes())
            receive(ws, "heard")
    starts = [s["start_ms"] for s in client.get(f"/sessions/{session['id']}/transcript").json()]
    assert len(starts) == 2 and starts[1] >= 4000 > starts[0]  # 두 번째 연결은 4초 뒤부터 이어진다

    res = client.get(f"/sessions/{session['id']}/audio")
    assert res.status_code == 200 and res.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(res.content)) as w:
        assert w.getnframes() == 16000 * 8  # 두 조각을 이어 붙인 8초
    part = client.get(f"/sessions/{session['id']}/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100


def test_spoken_event_points_at_the_paragraph_being_explained(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "the learning rate controls step size", "start_ms": 0,
                      "end_ms": 2000})
        spoken = receive(ws, "spoken")
    second = doc["pages"][0]["blocks"][1]
    assert spoken["page"] == 1 and spoken["block_id"] == second["id"]
    assert spoken["text"] == "the learning rate controls step size"


def test_catch_up_summarizes_recent_minutes_and_beyond_slides_counts_extra_talk(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Gradient Descent", "start_ms": 0, "end_ms": 2000})
        ws.send_json({"type": "transcript_final", "text": "산에서 눈을 감고 가장 가파른 쪽으로 내려간다고 생각하면 돼요.",
                      "start_ms": 300_000, "end_ms": 304_000})
        receive_annotation(ws)

    res = client.post(f"/sessions/{session['id']}/catch-up", json={"minutes": 1}).json()
    assert res["pages"] == [1] and res["to_ms"] == 304_000
    assert len(res["points"]) == 1 and "산에서" in res["points"][0]  # 5분 전 문장은 빼고 최근 1분만

    beyond = client.get(f"/sessions/{session['id']}/beyond-slides").json()
    assert 0.5 < beyond["ratio"] < 0.8  # 슬라이드 제목은 있고, 비유 문장은 슬라이드에 없다
    assert beyond["pages"][0]["page_no"] == 1
    assert len(beyond["annotation_ids"]) >= 1


def test_notebook_mode_writes_notes_and_opens_titled_pages_per_topic(client):
    doc = client.post("/documents/notebook", json={"title": "철학 개론"}).json()
    assert doc["kind"] == "notebook" and len(doc["pages"]) == 1
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "transcript_final", "text": "플라톤은 이데아가 참된 실재라고 봤어요. 이거 시험에 나와요.",
                      "start_ms": 0, "end_ms": 3000})
        first = receive_annotation(ws)
        ws.send_json({"type": "transcript_final", "text": "자 이제 아리스토텔레스 이야기를 해 볼게요. 그는 경험을 중시했어요.",
                      "start_ms": 5000, "end_ms": 8000})
        added = receive(ws, "page_added")
        title = receive(ws, "page_title")
        second = receive_annotation(ws)
    assert first["page_no"] == 1 and first["type"] == "exam"
    assert added["page"]["page_no"] == 2 and second["page_no"] == 2
    assert title["page"] == 1 and title["title"].startswith("플라톤은")
    pages = client.get(f"/documents/{doc['id']}").json()["pages"]
    assert len(pages) == 2
    assert {d["id"]: d for d in client.get("/documents").json()}[doc["id"]]["kind"] == "notebook"

    client.post(f"/sessions/{session['id']}/end")
    assert client.post(f"/sessions/{session['id']}/notes-pdf").status_code == 202
    pdf = client.get(f"/sessions/{session['id']}/notes-pdf")
    text = "".join(p.get_text() for p in pymupdf.open("pdf", pdf.content)).replace("\xa0", " ")
    assert "1. 플라톤은" in text and "아리스토텔레스" in text
