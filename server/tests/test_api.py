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
                                 "previews_resolved", "heard"), event
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
