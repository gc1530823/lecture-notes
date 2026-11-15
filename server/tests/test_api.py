import dataclasses
import uuid
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
                                 "previews_resolved", "heard", "spoken", "page_added", "page_title", "term"), event
        if event["type"] == kind:
            return event


def receive_annotation(ws) -> dict:
    return receive(ws)["annotation"]


def upload(client) -> dict:
    # 같은 파일을 다시 올리면 있던 자료가 열리므로, 시험마다 내용이 조금씩 다른 파일을 올린다
    data = make_pdf() + f"\n% {uuid.uuid4().hex}".encode()
    res = client.post("/documents", files={"file": ("mlnotes.pdf", data, "application/pdf")})
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
    assert doc["title"] == "mlnotes"
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
    home = client.get("/tasks").json()[0]
    assert home["due_date"] and len(home["due_date"]) == 10  # '다음 주 금요일까지' → 날짜
    assert client.patch(f"/tasks/{task['id']}", json={"done": True}).json()["done"] is True
    # 잘못 체크했으면 되돌린다, 마감일은 직접 고칠 수 있다
    assert client.patch(f"/tasks/{task['id']}", json={"done": False}).json()["done"] is False
    assert client.patch(f"/tasks/{task['id']}", json={"due_on": "2030-01-02"}).json()["due_on"] == "2030-01-02"
    assert client.get("/tasks").json()[0]["due_date"] == "2030-01-02"
    assert client.patch(f"/tasks/{task['id']}", json={"due_on": "내일"}).status_code == 422
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

    async def eager(self, candidates, transcript, existing_tasks, **kwargs):
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

    # 녹음부터 다시 받아쓰기: 내가 쓴 필기는 남고 다시 정리된다
    mine = client.post(f"/sessions/{session['id']}/annotations", json={"page_no": 1, "text": "내 메모"}).json()
    again = client.post(f"/sessions/{session['id']}/retranscribe")
    assert again.status_code == 200 and again.json()["status"] == "transcribing"
    for _ in range(100):
        summary = client.get(f"/sessions/{session['id']}/summary").json()
        if summary["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert summary["status"] == "done"
    texts = [n["text"] for n in client.get(f"/sessions/{session['id']}/annotations").json()]
    assert "내 메모" in texts and mine["id"]
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


def test_study_tools_flashcards_concepts_mindmap_cloze_and_tutor(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    sid = session["id"]
    assert client.post(f"/sessions/{sid}/study/flashcards").status_code == 400  # 아직 강의 내용이 없다
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Gradient Descent moves against the gradient. 시험에 꼭 나와요.",
                      "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)

    for kind in ("flashcards", "concepts", "mindmap"):
        assert client.post(f"/sessions/{sid}/study/{kind}").status_code == 202
        res = client.get(f"/sessions/{sid}/study/{kind}").json()
        assert res["status"] == "ready" and res["stale"] is False, kind
    cards = client.get(f"/sessions/{sid}/study/flashcards").json()["body"]
    assert cards[0]["page_no"] == 1 and cards[0]["front"] and cards[0]["back"]
    mindmap = client.get(f"/sessions/{sid}/study/mindmap").json()["body"]
    assert mindmap["label"] and mindmap["children"][0]["page_no"] == 1

    cloze = client.get(f"/sessions/{sid}/study/cloze").json()["body"]
    assert cloze and "____" in cloze[0]["text"] and cloze[0]["answer"] in ("Gradient", "Descent")

    res = client.post(f"/sessions/{sid}/tutor", json={"messages": [{"role": "user", "content": "경사하강법이 뭐야?"}]})
    assert res.status_code == 200 and res.json()["answer"] and res.json()["pages"] == [1]
    assert client.get(f"/sessions/{sid}/study/nope").status_code == 404
    # 범위 넓히기: 이 과목 · 학기 전체 (한 채팅창에서)
    for scope in ("course", "all"):
        wide = client.post(f"/sessions/{sid}/tutor", json={"scope": scope, "messages": [{"role": "user", "content": "경사하강법이 뭐야?"}]})
        assert wide.status_code == 200, wide.text
        assert wide.json()["answer"] and "sources" in wide.json()


def test_live_glossary_pops_new_terms_once(client):
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Backpropagation은 연쇄 법칙을 반복해서 쓰는 거예요.",
                      "start_ms": 0, "end_ms": 3000})
        term = receive(ws, "term")["term"]
        ws.send_json({"type": "transcript_final", "text": "다시 말하지만 Backpropagation이 핵심이고 Gradient도 봅시다.",
                      "start_ms": 4000, "end_ms": 7000})
        second = receive(ws, "term")["term"]
    assert term["term"] == "Backpropagation" and term["page_no"] == 2 and term["definition"]  # 역전파 슬라이드로 넘어간다
    assert second["term"] == "Gradient"  # 이미 띄운 용어는 다시 띄우지 않는다
    terms = client.get(f"/sessions/{session['id']}/glossary").json()
    assert [t["term"] for t in terms] == ["Backpropagation", "Gradient"]


def test_confused_mark_jokbo_and_spaced_review(client):
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.",
                      "start_ms": 1000, "end_ms": 4000})
        receive_annotation(ws)

    # 모르겠다: 누르는 순간에는 표시만 (AI 없이 바로)
    mark = client.post(f"/sessions/{sid}/confused", json={"page_no": 1}).json()
    assert mark["page_no"] == 1 and mark["at_ms"] == 4000 and "발산" in mark["speech"] and mark["explanation"] is None
    explained = client.post(f"/marks/{mark['id']}/explain").json()
    assert explained["explanation"]
    assert [m["id"] for m in client.get(f"/sessions/{sid}/marks").json()] == [mark["id"]]

    # 족보: 시험 필기·유력한 쪽·모르겠다가 모인다
    assert client.post(f"/documents/{doc['id']}/exam-questions").status_code == 202
    sheet = client.get(f"/documents/{doc['id']}/jokbo").json()
    assert sheet["lectures"] == 1 and sheet["exam"] and sheet["exam"][0]["page_no"] == 1
    assert sheet["top_pages"][0]["page_no"] == 1 and sheet["top_pages"][0]["reasons"]
    assert sheet["confused"][0]["explanation"] == explained["explanation"]
    assert sheet["predicted"][0]["question"]

    # 복습: 플래시카드·예상 문제·모르겠다 설명이 카드가 되고, 답하면 다음 날짜가 정해진다
    client.post(f"/sessions/{sid}/study/flashcards")
    today = client.get("/review/today", params={"document_id": doc["id"]}).json()
    sources = [c["source"] for c in today["cards"]]
    assert sources[0] == "confused" and "exam" in sources and "flashcard" in sources and today["new"] == len(sources)
    first = today["cards"][0]
    # 모르겠다 카드의 앞면은 교수님 말 그대로가 아니라 AI가 만든 질문, 그때 들은 말은 뒷면 참고로
    assert first["front"] == "이 개념이 왜 그렇게 동작하는지 설명해 보세요" and "발산" not in first["front"]
    assert "수업 중 헷갈렸던 말" in first["back"] and "발산" in first["back"]
    assert first["next"] == {"again": "오늘 다시", "hard": "1일 뒤", "good": "1일 뒤", "easy": "4일 뒤"}
    after = client.post(f"/review/{first['card_key']}", json={"grade": "good"}).json()
    assert after["reps"] == 1 and after["interval"] == 1.0 and after["due_at"] > time.time() + 80000
    again = client.post(f"/review/{today['cards'][1]['card_key']}", json={"grade": "again"}).json()
    assert again["lapses"] == 1 and again["due_at"] < time.time() + 700
    left = client.get("/review/today", params={"document_id": doc["id"]}).json()
    assert first["card_key"] not in [c["card_key"] for c in left["cards"]]
    assert client.post(f"/review/{first['card_key']}", json={"grade": "meh"}).status_code == 400

    info = client.get("/privacy").json()
    assert "밖으로 안 나감" in info["ai"] and info["training"] is False


def test_semester_concepts_tutor_exam_plan_and_exports(client):
    import datetime as dt

    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Gradient Descent는 Learning Rate 만큼 움직여요. 이거 시험에 꼭 나와요.",
                      "start_ms": 0, "end_ms": 3000})
        receive(ws, "term")
    client.post(f"/sessions/{sid}/end")

    graph = client.get("/semester/concepts").json()
    terms = {n["term"] for n in graph["nodes"]}
    assert terms and all(n["occurrences"] for n in graph["nodes"])
    occ = graph["nodes"][0]["occurrences"][0]
    assert {"doc_id", "session_id", "page_no", "doc_title"} <= set(occ)

    res = client.post("/semester/tutor", json={"messages": [{"role": "user", "content": "경사하강법이 뭐야?"}]}).json()
    assert res["answer"] and res["sources"][0]["doc_id"] and res["sources"][0]["page_no"]

    today = dt.date(2026, 11, 9)
    exam = client.post("/exams", json={"title": "중간고사", "exam_date": "2026-11-13", "doc_ids": [doc["id"], "nope"]}).json()
    assert exam["doc_ids"] == [doc["id"]]
    assert client.post("/exams", json={"title": "x", "exam_date": "내일", "doc_ids": [doc["id"]]}).status_code == 400
    plan = client.get(f"/exams/{exam['id']}/plan", params={"today": today.isoformat()}).json()
    assert plan["days_left"] == 4 and len(plan["days"]) == 4 and plan["days"][0]["d"] == 4
    assert plan["days"][0]["pages"][0]["page_no"] == 1  # 시험 언급이 있던 쪽이 첫날
    assert "족보 노트" in plan["days"][-1]["todo"][-1]
    assert exam["id"] in [e["id"] for e in client.get("/exams").json()]
    assert client.delete(f"/exams/{exam['id']}").status_code == 204

    md = client.get(f"/sessions/{sid}/export.md")
    assert md.status_code == 200 and md.text.startswith("# mlnotes") and "## 1쪽" in md.text and "**시험**" in md.text
    assert "## 용어 사전" in md.text
    client.post(f"/sessions/{sid}/study/flashcards")
    anki = client.get(f"/documents/{doc['id']}/anki.txt").text.splitlines()
    assert anki[0] == "#separator:tab" and all(len(line.split("\t")) == 3 for line in anki[3:]) and len(anki) > 3


def test_meeting_mode_minutes_with_decisions_and_owners(client):
    doc = client.post("/documents/notebook", json={"title": "캡스톤 회의", "kind": "meeting"}).json()
    assert doc["kind"] == "meeting"
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "발표 자료는 민수 씨가 금요일까지 정리하기로 했습니다. 그렇게 결정합시다.",
                      "start_ms": 0, "end_ms": 4000})
        receive(ws, "task_added")
    m = client.get(f"/sessions/{sid}/minutes").json()
    assert m["title"] == "캡스톤 회의" and m["decisions"] and m["actions"][0]["owner"] == "민수"
    assert m["actions"][0]["title"] == "자료 정리" and m["actions"][0]["due"] == "금요일까지"


def test_loud_voice_is_kept_and_counts_on_the_exam_map(client):
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Gradient Descent 학습률 정말 중요합니다 꼭 기억하세요.",
                      "start_ms": 0, "end_ms": 3000, "loud": True})
        receive_annotation(ws)
    segments = client.get(f"/sessions/{sid}/transcript").json()
    assert segments[0]["loud"] == 1
    page = client.get(f"/documents/{doc['id']}/exam-map").json()["pages"][0]
    assert "목소리 높여 말함 1번" in page["reasons"]


def test_board_photo_becomes_a_note_with_the_picture(client):
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    res = client.post(f"/sessions/{sid}/photo", data={"page_no": "2"}, files={"file": ("board.jpg", b"\xff\xd8fakejpeg", "image/jpeg")})
    note = res.json()
    assert res.status_code == 200 and note["page_no"] == 2 and note["text"].startswith("칠판:") and note["photo_id"]
    assert client.get(f"/photos/{note['photo_id']}").content == b"\xff\xd8fakejpeg"
    listed = client.get(f"/sessions/{sid}/annotations").json()
    assert listed[0]["photo_id"] == note["photo_id"]


def test_english_lecture_gets_bilingual_pairs(client, monkeypatch):
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Gradient descent moves against the gradient to minimize the loss.",
                      "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)
    assert client.get(f"/sessions/{sid}/language").json()["english"] is True

    async def fake_page(self, kind, page, speech, notes):
        return [{"en": speech, "ko": "경사하강법은 손실을 줄이려고 기울기 반대로 움직인다."}]

    monkeypatch.setattr(type(client.app.state.llm), "study_page", fake_page)
    assert client.post(f"/sessions/{sid}/study/bilingual").status_code == 202
    body = client.get(f"/sessions/{sid}/study/bilingual").json()["body"]
    assert body[0]["page_no"] == 1 and body[0]["en"].startswith("Gradient") and body[0]["ko"]


def test_shared_jokbo_merges_friends_and_counts_people(client):
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 크면 발산해요. 이거 시험에 꼭 나와요.", "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)
    share = client.get(f"/documents/{doc['id']}/share", params={"nickname": "지수"}).json()
    assert share["format"] == "lecture-notes-share/1" and share["exam"]
    # 같은 PDF를 올린 친구의 서버라고 치고, 친구가 2쪽에도 시험 표시를 했다
    friend = {**share, "exam": share["exam"] + [{"page_no": 2, "text": "역전파 유도 시험", "lecture": 1}],
              "terms": [{"term": "Backpropagation", "definition": "오차를 거꾸로", "page_no": 2}]}
    assert client.post(f"/documents/{doc['id']}/shared", json={"nickname": "지수", "share": friend}).status_code == 200
    other = upload(client)
    bad = client.post(f"/documents/{doc['id']}/shared", json={"share": {**friend, "fingerprint": "x"}})
    assert bad.status_code == 400 and other
    sheet = client.get(f"/documents/{doc['id']}/jokbo").json()
    assert sheet["friends"] == ["지수"]
    assert sheet["crowd"][0]["page_no"] == 1 and sheet["crowd"][0]["people"] == ["나", "지수"]
    assert any(c["page_no"] == 2 and c["people"] == ["지수"] for c in sheet["crowd"])
    assert "Backpropagation" in [t["term"] for t in sheet["terms"]]
    [entry] = client.get(f"/documents/{doc['id']}/shared").json()
    assert client.delete(f"/shared/{entry['id']}").status_code == 204


def test_courses_my_notes_and_star(client):
    doc = client.post("/documents", files={"file": ("ml.pdf", make_pdf(), "application/pdf")}, data={"course": "인공지능개론"}).json()
    listed = next(d for d in client.get("/documents").json() if d["id"] == doc["id"])
    assert listed["course"] == "인공지능개론"
    moved = client.patch(f"/documents/{doc['id']}", json={"course": "머신러닝", "title": "3주차"}).json()
    assert moved["course"] == "머신러닝" and moved["title"] == "3주차"

    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률은 걸음 크기예요. 꼭 기억하세요.", "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)
    mine = client.post(f"/sessions/{sid}/annotations", json={"page_no": 2, "text": "내가 쓴 필기", "type": "example"}).json()
    assert mine["page_no"] == 2 and mine["edited_by_user"] is True and mine["type"] == "example"
    assert client.post(f"/sessions/{sid}/annotations", json={"page_no": 2, "text": " "}).status_code == 400
    starred = client.post(f"/sessions/{sid}/star", json={"page_no": 1}).json()
    assert starred["type"] == "emphasis" and starred["text"].startswith("⭐ 중요 표시") and "학습률" in starred["text"]
    page = client.get(f"/documents/{doc['id']}/exam-map").json()["pages"][0]
    assert "강조 1번" in page["reasons"]


def test_scanned_pdf_pages_are_read_so_tracking_works(client):
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 400, 300), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))  # 글자 없는 그림 쪽 (스캔본)
    res = client.post("/documents", files={"file": ("scan.pdf", doc.tobytes(), "application/pdf")})
    assert res.status_code == 200
    did = res.json()["id"]
    assert client.get(f"/documents/{did}/ocr").json()["status"] == "done"
    read = client.get(f"/documents/{did}").json()["pages"][0]
    assert "f(x) = wx + b" in read["text"] and read["blocks"]


def test_pptx_is_converted_or_explained(client):
    import shutil

    res = client.post("/documents", files={"file": ("slides.pptx", b"PPT slide text", "application/vnd.ms-powerpoint")})
    if shutil.which("soffice") or shutil.which("libreoffice"):
        assert res.status_code == 200 and res.json()["page_count"] >= 1  # LibreOffice가 PDF로 바꿔 받는다
    else:
        assert res.status_code == 400 and "PDF로 저장" in res.json()["detail"]


def test_search_everywhere_and_confirm_low_confidence_note(client):
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "Gradient Descent에서 학습률이 너무 크면 발산해요.", "start_ms": 0, "end_ms": 3000})
        note = receive_annotation(ws)
    assert 0 <= note["confidence"] <= 1
    found = client.get("/search", params={"q": "발산"}).json()["results"]
    kinds = {r["kind"] for r in found}
    mine = {r["kind"] for r in found if r["doc_id"] == doc["id"]}
    assert {"note", "speech"} <= kinds and {"note", "speech"} <= mine
    assert "slide" in {r["kind"] for r in client.get("/search", params={"q": "Backpropagation"}).json()["results"]}
    assert client.get("/search", params={"q": "a"}).json()["results"] == []
    confirmed = client.patch(f"/annotations/{note['id']}", json={"confirm": True}).json()
    assert confirmed["confidence"] == 1


def test_phone_transcribed_lecture_is_rewritten_from_the_recording_after_class(client):
    """폰이 받아쓴 강의: 수업 중엔 서버가 받아쓰지 않고(녹음만), 끝나면 녹음을 다시 받아써서 글을 바로잡는다."""
    import numpy as np

    from app.main import app as fastapi_app
    from app.stt import Segment

    calls = []

    class Accurate:
        def transcribe(self, audio, hint="", on_progress=None):
            calls.append("file" if isinstance(audio, str) else "live")
            return [Segment(0, 2000, "경사하강법은 learning rate가 중요해요."), Segment(2000, 4000, "다음은 역전파입니다.")]

    fastapi_app.state.transcriber = Accurate()
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    tone = (np.sin(2 * np.pi * 220 * np.arange(16000 * 2) / 16000) * 8000).astype(np.int16)
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1, "initial": True})
        ws.send_json({"type": "device_stt"})
        ws.send_bytes(tone.tobytes())
        ws.send_json({"type": "transcript_final", "text": "경사 하강법은 러닝 레이트가 중요해요", "start_ms": 100, "end_ms": 1900})
        receive(ws, "spoken")
    assert calls == [], "수업 중에는 서버가 받아쓰지 않는다"
    client.post(f"/sessions/{session['id']}/end")
    for _ in range(50):
        if client.get(f"/sessions/{session['id']}/summary").json()["status"] == "done":
            break
        time.sleep(0.1)
    assert calls == ["file"]
    lines = client.get(f"/sessions/{session['id']}/transcript").json()
    texts = [s["text"] for s in (lines if isinstance(lines, list) else lines["segments"])]
    assert texts == ["경사하강법은 learning rate가 중요해요.", "다음은 역전파입니다."]


def test_timetable_add_list_delete_and_rejects_bad_times(client):
    assert client.post("/timetable", json={"course": "운영체제", "weekday": 1, "start": "13:00", "end": "12:00"}).status_code == 400
    assert client.post("/timetable", json={"course": " ", "weekday": 1, "start": "10:30", "end": "11:45"}).status_code == 400
    made = client.post("/timetable", json={"course": "운영체제", "weekday": 1, "start": "10:30", "end": "11:45", "place": "공학관 301"}).json()
    client.post("/timetable", json={"course": "미시경제", "weekday": 0, "start": "09:00", "end": "10:15"})
    rows = client.get("/timetable").json()
    assert [r["course"] for r in rows if r["course"] in ("미시경제", "운영체제")] == ["미시경제", "운영체제"]  # 요일·시간 순
    assert client.delete(f"/timetable/{made['id']}").status_code == 204
    assert client.delete(f"/timetable/{made['id']}").status_code == 404


def test_story_flow_and_streak_are_built_from_notes_without_ai(client):
    from app.story import build_streak

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1, "initial": True})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.", "start_ms": 65_000, "end_ms": 70_000})
        ws.send_json({"type": "flush"})
        receive_annotation(ws)
    story = client.get(f"/sessions/{session['id']}/story").json()
    kinds = [c["kind"] for c in story["cards"]]
    assert kinds[0] == "cover" and kinds[-1] == "end" and "exam" in kinds
    exam = next(c for c in story["cards"] if c["kind"] == "exam")
    assert exam["page_no"] == 1 and exam["at_ms"] == 65_000
    minutes = story["flow"]["minutes"]
    assert len(minutes) == 2 and minutes[1]["exam"] == 1 and minutes[1]["weight"] > minutes[0]["weight"]
    assert client.get("/streak").json()["streak"] >= 1

    day = 86400
    now = 1_700_000_000.0
    s = build_streak([now, now - day, now - 2 * day, now - 5 * day], 540, now)
    assert (s["streak"], s["best"], s["today"]) == (3, 3, True) and [d["done"] for d in s["week"]][-3:] == [True] * 3
    assert build_streak([now - day], 540, now)["streak"] == 1 and build_streak([now - 3 * day], 540, now)["streak"] == 0


def test_notes_are_checked_again_after_class_and_user_notes_are_left_alone(client):
    """필기 두 번 쓰기: 끝난 뒤 AI가 틀린 필기를 고치고·옮기고·지우고, 놓친 시험 언급을 더한다. 내가 고친 필기는 그대로."""
    from app.main import app as fastapi_app

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1, "initial": True})
        for i, text in enumerate(["학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.", "예를 들어 학습률 0.1로 시작해 보세요. 정말 중요합니다.",
                                  "역전파는 연쇄 법칙으로 기울기를 구해요. 이것도 중요해요.", "다음 주까지 과제를 제출하세요. 공지입니다."]):
            ws.send_json({"type": "transcript_final", "text": text, "start_ms": 10_000 + i * 20_000, "end_ms": 15_000 + i * 20_000})
            ws.send_json({"type": "flush"})
            receive_annotation(ws)
    notes = client.get(f"/sessions/{session['id']}/annotations").json()
    assert len(notes) >= 4
    mine, wrong, misplaced, dup = notes[0], notes[1], notes[2], notes[3]
    client.patch(f"/annotations/{mine['id']}", json={"text": "내가 고친 필기"})
    seen = []

    class Reviewer:
        def __getattr__(self, name):
            return getattr(fastapi_app.state.llm_real, name)

        async def review_notes(self, prompt):
            seen.append(prompt)
            return {"notes": [
                {"id": mine["id"], "action": "delete", "text": "", "page_no": 1},        # 내 필기: 보여 주지도 않았으니 무시된다
                {"id": wrong["id"], "action": "fix", "text": "학습률은 0.1로 시작", "page_no": 1},
                {"id": misplaced["id"], "action": "move", "text": "", "page_no": 2},
                {"id": dup["id"], "action": "delete", "text": "", "page_no": 1},
            ], "missed": [{"type": "exam", "text": "발산 조건은 시험에 나옴", "page_no": 1, "at": "0:12"},
                          {"type": "exam", "text": "없는 쪽", "page_no": 99, "at": "0:12"}]}

    fastapi_app.state.llm_real = fastapi_app.state.llm
    fastapi_app.state.llm = Reviewer()
    try:
        client.post(f"/sessions/{session['id']}/end")
        for _ in range(50):
            state = client.get(f"/sessions/{session['id']}/summary").json()
            if state["status"] == "done":
                break
            time.sleep(0.1)
    finally:
        fastapi_app.state.llm = fastapi_app.state.llm_real
    assert f'id="{mine["id"]}"' not in seen[0] and f'id="{wrong["id"]}"' in seen[0] and "<speech>" in seen[0]
    after = {n["id"]: n for n in client.get(f"/sessions/{session['id']}/annotations").json()}
    assert after[mine["id"]]["text"] == "내가 고친 필기"
    assert after[wrong["id"]]["text"] == "학습률은 0.1로 시작" and not after[wrong["id"]]["edited_by_user"]
    assert after[misplaced["id"]]["page_no"] == 2
    assert dup["id"] not in after
    added = [n for n in after.values() if n["text"] == "발산 조건"]
    assert added and added[0]["type"] == "exam" and added[0]["start_ms"] == 12_000
    assert not any(n["text"] == "없는 쪽" for n in after.values())
    assert state["review"]["fixed"] == 1 and state["review"]["moved"] == 1 and state["review"]["deleted"] == 1 and state["review"]["added"] == 1


def test_note_review_ignores_mass_deletes():
    from app.note_review import apply

    class Db:
        deleted = []

        def review_annotation(self, ann_id, **kw):
            if kw.get("delete"):
                self.deleted.append(ann_id)

        def set_confidence(self, *a):
            pass

    notes = [{"id": i, "page_no": 1, "text": f"필기 {i}", "start_ms": i * 1000, "confidence": 0.5} for i in range(4)]
    result = {"notes": [{"id": i, "action": "delete", "text": "", "page_no": 1} for i in range(3)], "missed": []}
    done = apply(Db(), "s", notes, result, {1}, [{"page_no": 1, "id": 1}])
    assert done["deleted"] == 0 and Db.deleted == []


def test_each_lecture_gets_its_own_wave_shape(client):
    from app.story import wave

    segs = [{"start_ms": i * 60_000, "end_ms": i * 60_000 + 50_000, "text": "말" * (10 + 40 * (i % 3)), "page_no": 1, "loud": 0} for i in range(56)]
    notes = [{"start_ms": 20 * 60_000, "type": "exam", "page_no": 1}]
    w = wave(notes, segs, [])
    assert len(w["w"]) == 28 and w["x"] == [10] and w["w"][10] == "9" and len(set(w["w"])) > 1
    assert wave([], [], []) == {"w": "", "x": []}
    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    assert session["id"] in client.get("/waves").json()


def test_home_tasks_exam_eve_story_and_carrot_levels(client):
    from app.story import level

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    with client.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1, "initial": True})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.", "start_ms": 5_000, "end_ms": 9_000})
        ws.send_json({"type": "flush"})
        receive_annotation(ws)
    story = client.get(f"/documents/{doc['id']}/exam-story").json()
    kinds = [c["kind"] for c in story["cards"]]
    assert kinds[0] == "cover" and kinds[-1] == "end" and "exam" in kinds
    exam = next(c for c in story["cards"] if c["kind"] == "exam")
    assert exam["session_id"] == session["id"] and exam["label"].startswith("1번째 강의")
    assert client.get("/documents/nope/exam-story").status_code == 404
    tasks = client.get("/tasks").json()
    assert isinstance(tasks, list) and all({"doc_id", "doc_title", "course"} <= set(t) for t in tasks)
    assert [t["done"] for t in tasks] == sorted(t["done"] for t in tasks)
    assert level(0)["level_name"] == "첫걸음" and level(7) == {"carrots": 7, "level": 3, "level_name": "모범생", "level_from": 7, "next_at": 14}
    assert level(500)["next_at"] is None
    assert client.get("/streak").json()["level"] >= 1


def test_same_file_opens_existing_document_and_meaningless_names_use_first_slide_title(client):
    from app.main import _document_title

    pdf = make_pdf() + b"\n% unique-for-this-test"
    first = client.post("/documents", files={"file": ("os.pdf", pdf, "application/pdf")}).json()
    assert first["title"] == "Gradient Descent"            # "os"는 뜻 없는 이름 → 첫 쪽 제목
    again = client.post("/documents", files={"file": ("다른이름.pdf", pdf, "application/pdf")}, data={"course": "인공지능"}).json()
    assert again["id"] == first["id"] and again["duplicate"] is True and again["course"] == "인공지능"
    pages = [{"text": "운영체제 7주차\n교착 상태"}]
    assert _document_title("운영체제 7주차 강의.pdf", pages) == "운영체제 7주차 강의"
    assert _document_title("slides (3).pdf", pages) == "운영체제 7주차"
    assert _document_title("20261113.pdf", pages) == "운영체제 7주차"


def test_recording_only_upload_becomes_a_notebook_lecture_with_topics_and_summary(client):
    """강의자료 없이 녹음만 올려도: 노트 수업이 생기고, 받아쓰기·주제별 필기·요약까지 된다."""
    from app.main import app as fastapi_app
    from app.stt import Segment

    class Speech:
        def transcribe(self, audio, hint="", on_progress=None):
            return [Segment(0, 4000, "오늘은 경사하강법을 볼게요. 학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요."),
                    Segment(5000, 9000, "자 이제 역전파 얘기를 해 봅시다. 연쇄 법칙으로 기울기를 구해요.")]

    fastapi_app.state.transcriber = Speech()
    res = client.post("/documents/from-audio", files={"file": ("새로운 녹음 3.m4a", b"fake audio", "audio/mp4")}, data={"course": "인공지능"})
    assert res.status_code == 200, res.text
    made = res.json()
    assert "녹음 수업" in made["title"]                              # 뜻 없는 파일 이름 → 날짜 이름
    for _ in range(60):
        state = client.get(f"/sessions/{made['session_id']}/summary").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert state["status"] == "done"
    doc = client.get(f"/documents/{made['document_id']}").json()
    assert doc["kind"] == "notebook" and doc["course"] == "인공지능" and len(doc["pages"]) >= 2   # 주제가 바뀌어 쪽이 나뉨
    notes = client.get(f"/sessions/{made['session_id']}/annotations").json()
    assert any(n["type"] == "exam" for n in notes)
    named = client.post("/documents/from-audio", files={"file": ("운영체제 7주차.m4a", b"x", "audio/mp4")}).json()
    assert named["title"] == "운영체제 7주차"


def test_old_copied_quiz_is_remade_by_ai_and_can_be_asked_again(client):
    """예전 방식 퀴즈("몇 쪽에서 다룬 내용은?")가 저장된 강의는 열 때 AI가 새로 낸 문제로 바뀐다. 다시 받기도 된다."""
    from app.main import app as fastapi_app

    doc = upload(client)
    session = client.post("/sessions", json={"document_id": doc["id"]}).json()
    fastapi_app.state.db.save_summary(session["id"], {"overview": "요약", "pages": [{"page_no": 1, "summary": "경사하강법"}],
        "quiz": [{"page_no": 1, "question": "1페이지에서 다룬 내용은?", "choices": ["가", "나", "다", "라"], "answer_index": 0, "explanation": "x"}]})
    fastapi_app.state.db.set_session_status(session["id"], "done")
    first = client.get(f"/sessions/{session['id']}/summary").json()
    assert first["quiz_status"] == "making"
    for _ in range(30):
        state = client.get(f"/sessions/{session['id']}/summary").json()
        if state["quiz_status"] == "ready" and "다룬 내용" not in state["summary"]["quiz"][0]["question"]:
            break
        time.sleep(0.1)
    assert "다룬 내용" not in state["summary"]["quiz"][0]["question"] and len(state["summary"]["quiz"]) >= 1
    assert client.post(f"/sessions/{session['id']}/quiz").json()["quiz_status"] == "making"


def test_ai_quiz_set_asks_and_grades(client):
    doc = upload(client)
    made = client.post(f"/documents/{doc['id']}/quiz-set", json={"count": 6})
    assert made.status_code == 200, made.text
    qs = made.json()
    types = [q["type"] for q in qs["questions"]]
    assert {"mcq", "ox", "short", "essay"} <= set(types)
    assert all("answer" not in q for q in qs["questions"])  # 정답은 풀기 전에 안 보낸다
    answers = {"mcq": "A", "ox": "X", "short": "일", "essay": "조건 하나를 깨면 예방할 수 있기 때문입니다"}
    verdicts = []
    for q in qs["questions"]:
        res = client.post(f"/quiz-sets/{qs['id']}/grade", json={"index": q["index"], "answer": answers[q["type"]]})
        assert res.status_code == 200, res.text
        verdicts.append(res.json()["result"]["verdict"])
        assert res.json()["answer"]
    assert verdicts[types.index("mcq")] == "correct"
    assert verdicts[types.index("ox")] == "wrong"
    assert verdicts[types.index("short")] == "correct"
    assert verdicts[types.index("essay")] == "partial"
    again = client.post(f"/quiz-sets/{qs['id']}/grade", json={"index": 0, "answer": "A"})
    assert again.status_code == 409
    state = client.get(f"/quiz-sets/{qs['id']}").json()
    assert state["answered"] == len(types) and state["score"] == 2.5
    # 오답 노트: 틀린 문제(OX)와 반만 맞은 문제(서술)는 바로 복습 카드가 되고 약점 노트에 모인다
    weak = client.get(f"/documents/{doc['id']}/weak").json()
    quiz_cards = [w for w in weak if w["source"] == "quiz"]
    assert len(quiz_cards) == 2 and all("정답:" in w["back"] and "내가 쓴 답:" in w["back"] for w in quiz_cards)
    today = client.get("/review/today", params={"document_id": doc["id"]}).json()
    assert {c["front"] for c in today["cards"] if c["source"] == "quiz" and not c["new"]} == {w["front"] for w in quiz_cards}


def test_retry_failed_session(client):
    """정리에 실패한 강의는 '다시 정리하기'로: 받아쓴 글이 있으면 필기·요약만 다시"""
    from app.main import app as the_app

    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    assert client.post(f"/sessions/{sid}/retry").status_code == 409   # 실패한 강의만
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.", "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)
    the_app.state.db.set_session_status(sid, "failed")
    assert client.post(f"/sessions/{sid}/retry").status_code == 200
    for _ in range(50):
        if client.get(f"/sessions/{sid}/summary").json()["status"] == "done":
            break
        time.sleep(0.1)
    assert client.get(f"/sessions/{sid}/summary").json()["status"] == "done"


def test_study_note_pdf_and_delete_session(client):
    """AI 정리 노트 PDF: 배운 내용을 주제별로 새로 정리한 PDF. 강의 지우기: 그 강의만 지우고 강의자료는 그대로"""
    import pymupdf as _pdf

    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.", "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)
    assert client.get(f"/sessions/{sid}/study-pdf/status").json()["status"] == "none"
    assert client.post(f"/sessions/{sid}/study-pdf").status_code == 202
    for _ in range(50):
        if client.get(f"/sessions/{sid}/study-pdf/status").json()["status"] == "ready":
            break
        time.sleep(0.1)
    res = client.get(f"/sessions/{sid}/study-pdf")
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    text = "".join(p.get_text() for p in _pdf.open("pdf", res.content)).replace("\xa0", " ")
    assert "AI 정리 노트" in text and "핵심 용어" in text and "스스로 확인하기" in text

    assert client.delete(f"/sessions/{sid}").status_code == 204
    assert client.get(f"/sessions/{sid}/summary").status_code == 404
    assert client.get(f"/documents/{doc['id']}").status_code == 200   # 강의자료는 그대로
    assert client.get(f"/sessions/{sid}/study-pdf").status_code == 404


def test_renote_rebuilds_ai_notes_and_keeps_mine(client):
    """필기 다시 만들기: AI 필기만 새로 쓰고, 내가 쓴 필기는 그대로"""
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"type": "page_view", "page": 1})
        ws.send_json({"type": "transcript_final", "text": "학습률이 너무 크면 발산해요. 이거 시험에 꼭 나와요.", "start_ms": 0, "end_ms": 3000})
        receive_annotation(ws)
    client.post(f"/sessions/{sid}/end")
    for _ in range(50):
        if client.get(f"/sessions/{sid}/summary").json()["status"] == "done":
            break
        time.sleep(0.1)
    mine = client.post(f"/sessions/{sid}/annotations", json={"page_no": 1, "text": "내가 쓴 필기"}).json()
    before = client.get(f"/sessions/{sid}/annotations").json()
    assert client.post(f"/sessions/{sid}/renote").status_code == 200
    for _ in range(80):
        if client.get(f"/sessions/{sid}/summary").json()["status"] == "done":
            break
        time.sleep(0.1)
    after = client.get(f"/sessions/{sid}/annotations").json()
    assert any(n["id"] == mine["id"] and n["text"] == "내가 쓴 필기" for n in after)
    ai_before = {n["id"] for n in before if n["id"] != mine["id"]}
    ai_after = [n for n in after if n["id"] != mine["id"]]
    assert ai_after and not ai_before & {n["id"] for n in ai_after}   # AI 필기는 새로 썼다
    assert len(client.get(f"/sessions/{sid}/transcript").json()) >= 1  # 받아쓰기는 그대로 남는다
    # 되돌리기: 다시 만들기 전 AI 필기로, 내가 쓴 필기는 그대로
    snap = client.get(f"/sessions/{sid}/snapshot").json()
    assert snap["notes"] == len(ai_before) and snap["now"] == len(ai_after)
    assert client.post(f"/sessions/{sid}/undo-renote").status_code == 200
    back = client.get(f"/sessions/{sid}/annotations").json()
    assert {n["id"] for n in back if n["id"] != mine["id"]} == ai_before
    assert any(n["id"] == mine["id"] for n in back)
    assert client.get(f"/sessions/{sid}/snapshot").json() is None
    assert client.post(f"/sessions/{sid}/undo-renote").status_code == 404


def test_timetable_from_screenshot_then_confirm(client):
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2400, 1200), False)
    pix.clear_with(230)
    shot = pix.tobytes("png")
    for old in client.get("/timetable").json():
        client.delete(f"/timetable/{old['id']}")
    read = client.post("/timetable/from-image", files={"file": ("everytime.png", shot, "image/png")})
    assert read.status_code == 200, read.text
    rows = read.json()["classes"]
    # 빈 과목 · 이상한 요일 · 끝이 시작보다 이른 줄은 버리고, "13시" 는 13:00 으로
    assert [(r["course"], r["weekday"], r["start"]) for r in rows] == [
        ("운영체제", 0, "10:30"), ("인공지능개론", 1, "13:00"), ("운영체제", 2, "10:30")]
    assert client.get("/timetable").json() == []  # 확인 전에는 저장하지 않는다

    saved = client.post("/timetable/bulk", json={"classes": rows}).json()
    assert len(saved) == 3
    assert len(client.post("/timetable/bulk", json={"classes": rows}).json()) == 3  # 두 번 넣어도 겹치지 않는다
    one = client.post("/timetable/bulk", json={"classes": rows[:1], "replace": True}).json()
    assert [c["course"] for c in one] == ["운영체제"]
    assert client.post("/timetable/from-image", files={"file": ("x.png", b"", "image/png")}).status_code == 400


def test_timetable_screenshot_times_come_from_the_grid(client):
    """에타 캡처: 시각은 칸 위치로 정확히 (AI 는 이름만). 가짜 AI 는 이 시간표를 모르므로 이름은 비고 시간만 맞는다"""
    import os

    for old in client.get("/timetable").json():
        client.delete(f"/timetable/{old['id']}")
    shot = open(os.path.join(os.path.dirname(__file__), "everytime-dark.png"), "rb").read()
    res = client.post("/timetable/from-image", files={"file": ("et.png", shot, "image/png")}).json()
    times = [(r["weekday"], r["start"], r["end"]) for r in res["classes"]]
    assert times == [(0, "15:30", "18:30"), (0, "18:30", "19:30"), (1, "11:00", "15:30"),
                     (2, "09:30", "12:30"), (3, "13:30", "16:30"), (4, "09:30", "12:30")]



def test_english_lecture_checkbox_fixes_language(client):
    """처음에 '영어 강의'를 체크하면 받아쓰기를 영어로 고정, 안 하면 목소리로"""
    from app.main import app as the_app
    from app.stt import Segment

    seen = []

    class Recorder:
        def transcribe(self, path, hint, on_progress=None, language=None):
            seen.append(language)
            return [Segment(0, 3000, "Today we talk about gradient descent.")]

    the_app.state.transcriber = Recorder()
    doc = upload(client)
    assert client.post("/sessions", json={"document_id": doc["id"], "language": "en"}).json()["language"] == "en"
    assert client.post("/sessions", json={"document_id": doc["id"]}).json()["language"] == ""
    for lang in ("en", ""):
        s = client.post("/sessions/from-audio", data={"document_id": doc["id"], "language": lang},
                        files={"file": ("a.m4a", b"x", "audio/mp4")}).json()
        for _ in range(100):
            if client.get(f"/sessions/{s['id']}/summary").json()["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
    assert seen == ["en", None]


def test_full_recording_replaces_gappy_live_audio(client):
    """녹음 오프라인 저장: 서버가 받은 길이를 알려 주고, 폰의 전체 녹음을 올리면 처음부터 다시 정리 (내 필기는 그대로)"""
    import io
    import wave

    from app.main import app as the_app
    from app.stt import Segment

    class Fake:
        def transcribe(self, path, hint, on_progress=None):
            return [Segment(0, 3000, "경사하강법은 기울기 반대 방향으로 이동해요.")]

    the_app.state.transcriber = Fake()
    doc = upload(client)
    s = client.post("/sessions", json={"document_id": doc["id"]}).json()
    assert client.get(f"/sessions/{s['id']}/received").json() == {"ms": 0, "live": False}
    # 녹음 연결이 열려 있는 동안은 '다른 기기에서 녹음 중'으로 보인다 (이어 녹음이 겹치지 않게)
    with client.websocket_connect(f"/sessions/{s['id']}/stream"):
        assert client.get(f"/sessions/{s['id']}/received").json()["live"] is True
    for _ in range(50):
        if not client.get(f"/sessions/{s['id']}/received").json()["live"]:
            break
        time.sleep(0.05)
    assert client.get(f"/sessions/{s['id']}/received").json()["live"] is False
    mine = client.post(f"/sessions/{s['id']}/annotations", json={"page_no": 1, "text": "내 메모"}).json()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000)
    res = client.post(f"/sessions/{s['id']}/full-audio", files={"file": ("full.wav", buf.getvalue(), "audio/wav")})
    assert res.status_code == 200 and res.json()["status"] == "transcribing"
    for _ in range(100):
        if client.get(f"/sessions/{s['id']}/summary").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert any(n["text"] == "내 메모" for n in client.get(f"/sessions/{s['id']}/annotations").json()) and mine["id"]
    assert client.get(f"/sessions/{s['id']}/audio").status_code == 200
    assert client.post(f"/sessions/{s['id']}/full-audio", files={"file": ("x.wav", b"x", "audio/wav")}).status_code == 400


def test_timetable_next_doc_auto_and_picked(client):
    client.post("/timetable", json={"course": "자료구조", "weekday": 2, "start": "10:30", "end": "11:45"})
    old, new = upload(client), upload(client)
    for d in (old, new):
        client.patch(f"/documents/{d['id']}", json={"course": "자료구조"})
    # 고르지 않으면 아직 녹음 안 한 가장 새 자료
    nxt = client.get("/timetable/next").json()["자료구조"]
    assert nxt["auto"] is True and nxt["doc_id"] in (old["id"], new["id"])
    picked = client.put("/timetable/next", json={"course": "자료구조", "doc_id": old["id"]}).json()["자료구조"]
    assert picked == {"doc_id": old["id"], "title": old["title"], "auto": False}
    assert client.put("/timetable/next", json={"course": "자료구조", "doc_id": "nope"}).status_code == 404
    # 연결을 풀면 다시 자동, 둘 다 녹음하면 연결할 자료가 없다
    client.put("/timetable/next", json={"course": "자료구조", "doc_id": None})
    for d in (old, new):
        client.post("/sessions", json={"document_id": d["id"]})
    assert "자료구조" not in client.get("/timetable/next").json()


def test_board_photo_falls_back_to_ocr_and_tidies_it(client, monkeypatch):
    """사진 읽는 AI 가 없으면: 서버 글자 인식으로 줄을 읽고, 글 모델이 띄어쓰기를 다듬어 필기로 남긴다"""
    from app import main as m
    from app import ocr

    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]

    async def no_vision(data, mime):
        raise RuntimeError("사진 읽는 모델 없음")

    async def tidy(lines, speech=""):
        return {"summary": "정규화 판서", "text": "\n".join(l.replace("SE L E C T", "SELECT") for l in lines)}

    monkeypatch.setattr(m.app.state.llm, "read_board", no_vision, raising=False)
    monkeypatch.setattr(m.app.state.llm, "tidy_board", tidy, raising=False)
    monkeypatch.setattr(ocr, "read_photo", lambda data: ["1NF: 원자값", "SE L E C T name"])
    note = client.post(f"/sessions/{sid}/photo", data={"page_no": "1"}, files={"file": ("b.jpg", b"\xff\xd8x", "image/jpeg")}).json()
    assert note["text"] == "칠판: 정규화 판서\n1NF: 원자값\nSELECT name"
    # 다듬기도 실패하면 읽은 줄 그대로
    async def broken(lines, speech=""):
        raise RuntimeError("x")
    monkeypatch.setattr(m.app.state.llm, "tidy_board", broken, raising=False)
    note = client.post(f"/sessions/{sid}/photo", data={"page_no": "1"}, files={"file": ("b.jpg", b"\xff\xd8x", "image/jpeg")}).json()
    assert note["text"].endswith("1NF: 원자값\nSE L E C T name")


def test_photo_ocr_helpers():
    import numpy as np

    from app import ocr
    m = np.zeros((10, 20), bool); m[1:3, 2:8] = 1; m[2:5, 6:9] = 1; m[7:9, 12:18] = 1
    assert sorted(ocr.components(m)) == [(2, 1, 9, 5, 19), (12, 7, 18, 9, 12)]
    assert ocr.reading_order([(50, 10, 90, 20), (0, 12, 40, 22), (0, 40, 30, 50)]) == [(0, 12, 40, 22), (50, 10, 90, 20), (0, 40, 30, 50)]


def test_trash_keeps_deleted_documents_for_seven_days(client):
    """지우면 휴지통으로: 목록·강의에서 사라지고, 되살리면 그대로, 7일이 지나거나 완전히 지우면 끝"""
    from app import main as m
    doc = upload(client)
    sid = client.post("/sessions", json={"document_id": doc["id"]}).json()["id"]
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    assert doc["id"] not in {d["id"] for d in client.get("/documents").json()}
    assert client.get(f"/sessions/{sid}/annotations").status_code == 404
    trash = {t["id"]: t for t in client.get("/trash").json()}
    assert trash[doc["id"]]["days_left"] == 7
    assert client.post(f"/trash/{doc['id']}/restore").status_code == 200
    assert doc["id"] in {d["id"] for d in client.get("/documents").json()}
    assert client.get(f"/sessions/{sid}/annotations").status_code == 200
    # 완전히 지우기 (휴지통에서) · 바로 지우기(purge)
    client.delete(f"/documents/{doc['id']}")
    assert client.delete(f"/trash/{doc['id']}").status_code == 204
    assert doc["id"] not in {t["id"] for t in client.get("/trash").json()}
    other = upload(client)
    client.delete(f"/documents/{other['id']}?purge=true")
    assert other["id"] not in {t["id"] for t in client.get("/trash").json()}
    # 7일 지난 것은 휴지통을 볼 때 지워진다
    old = upload(client)
    client.delete(f"/documents/{old['id']}")
    m.db().trash_document(old["id"])
    m.db()._write("UPDATE documents SET deleted_at = ? WHERE id = ?", (time.time() - 8 * 86400, old["id"]))
    assert old["id"] not in {t["id"] for t in client.get("/trash").json()}
