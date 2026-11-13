"""친구들과 함께 쓸 때: 초대 코드로 가입, 각자 자기 자료만 (app/auth.py)"""
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_api import upload
from app.main import app


@pytest.fixture()
def invite(monkeypatch):
    monkeypatch.setenv("INVITE_CODE", "우리반-2026")


def person(name_prefix: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    client.__enter__()
    name = f"{name_prefix}{uuid.uuid4().hex[:6]}"
    res = client.post("/auth/signup", json={"name": name, "password": "secret12", "invite": "우리반-2026"})
    assert res.status_code == 200, res.text
    return client, name


def test_login_required_and_people_do_not_see_each_other(invite):
    with TestClient(app) as anon:
        assert anon.get("/health").status_code == 200
        assert anon.get("/auth/me").json() == {"auth": True, "user": None}
        assert anon.get("/documents").status_code == 401
        assert anon.post("/auth/signup", json={"name": "몰래", "password": "secret12", "invite": "틀림"}).status_code == 403

    a, a_name = person("민지")
    b, _ = person("지수")
    try:
        assert a.get("/auth/me").json()["user"]["name"] == a_name
        doc = upload(a)
        session = a.post("/sessions", json={"document_id": doc["id"]}).json()
        a.post("/timetable", json={"course": "운영체제", "weekday": 0, "start": "09:00", "end": "10:15", "place": ""})

        # 지수에게는 민지 자료가 안 보이고, 주소를 알아도 404
        assert doc["id"] not in [d["id"] for d in b.get("/documents").json()]
        assert b.get(f"/documents/{doc['id']}").status_code == 404
        assert b.get(f"/sessions/{session['id']}/summary").status_code == 404
        assert b.post("/sessions", json={"document_id": doc["id"]}).status_code == 404
        assert b.get("/search", params={"q": "Gradient"}).json()["results"] == []
        assert all(c["course"] != "운영체제" for c in b.get("/timetable").json())
        with pytest.raises(WebSocketDisconnect):
            with b.websocket_connect(f"/sessions/{session['id']}/stream") as ws:
                ws.receive_json()

        # 민지는 자기 자료를 그대로
        assert doc["id"] in [d["id"] for d in a.get("/documents").json()]
        assert a.get(f"/documents/{doc['id']}").status_code == 200
        assert any(r["doc_id"] == doc["id"] for r in a.get("/search", params={"q": "Gradient"}).json()["results"])

        # 비밀번호가 틀리면 안 되고, 로그아웃하면 다시 401
        assert a.post("/auth/login", json={"name": a_name, "password": "wrong!!"}).status_code == 401
        assert a.post("/auth/login", json={"name": a_name, "password": "secret12"}).status_code == 200
        a.post("/auth/logout")
        assert a.get("/documents").status_code == 401
    finally:
        a.__exit__(None, None, None)
        b.__exit__(None, None, None)


def test_without_invite_code_no_login(monkeypatch):
    monkeypatch.delenv("INVITE_CODE", raising=False)
    with TestClient(app) as c:
        assert c.get("/auth/me").json() == {"auth": False, "user": None}
        assert c.get("/documents").status_code == 200
