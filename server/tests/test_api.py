import dataclasses
import os
import tempfile
import time

os.environ["LLM_MODE"] = "fake"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
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
                                 "previews_resolved"), event
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
