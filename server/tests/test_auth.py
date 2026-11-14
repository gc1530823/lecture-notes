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


def test_friends_by_code_and_jokbo_merges_automatically(invite):
    a, a_name = person("하린")
    b, b_name = person("도윤")
    c, _ = person("서준")
    try:
        code_b = b.get("/friends").json()["me"]["code"]
        assert len(code_b) == 6
        assert a.post("/friends", json={"code": "ZZZZZZ"}).status_code == 404
        assert a.post("/friends", json={"code": a.get("/friends").json()["me"]["code"]}).status_code == 400
        assert a.post("/friends", json={"code": code_b.lower()}).json() == {"status": "pending", "name": b_name}
        assert [r["name"] for r in b.get("/friends").json()["incoming"]] == [a_name]
        assert a.get("/friends").json()["friends"] == []

        # 같은 강의자료(같은 PDF)로 각자 들은 강의: 친구가 되기 전에는 섞이지 않는다
        doc_a, doc_b = upload(a), upload(b)
        sa = a.post("/sessions", json={"document_id": doc_a["id"]}).json()
        sb = b.post("/sessions", json={"document_id": doc_b["id"]}).json()
        b.post(f"/sessions/{sb['id']}/annotations", json={"page_no": 1, "type": "exam", "text": "경사하강법 업데이트 식"})
        assert a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"] == []

        a_id = [r for r in b.get("/friends").json()["incoming"]][0]["id"]
        friends = b.post(f"/friends/{a_id}/accept").json()["friends"]
        assert [f["name"] for f in friends] == [a_name]
        sheet = a.get(f"/documents/{doc_a['id']}/jokbo").json()
        assert sheet["friends"] == [b_name]
        assert any(n["who"] == b_name for c_ in sheet["crowd"] for n in c_["notes"])
        assert sa["id"]
        # 친구가 아닌 사람은 친구 목록·족보에 안 나온다
        assert c.get("/friends").json()["friends"] == []
        # 끊으면 다시 섞이지 않는다
        assert b.delete(f"/friends/{a_id}").status_code == 204
        assert a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"] == []
    finally:
        for x in (a, b, c):
            x.__exit__(None, None, None)


def test_friend_privacy_settings(invite):
    a, a_name = person("유나")
    b, b_name = person("시우")
    try:
        b_code = b.get("/friends").json()["me"]["code"]
        a.post("/friends", json={"code": b_code})
        b_id = a.get("/friends").json()["outgoing"][0]["id"]
        a_id = b.get("/friends").json()["incoming"][0]["id"]
        b.post(f"/friends/{a_id}/accept")
        doc_a, doc_b = upload(a), upload(b)
        a.post("/sessions", json={"document_id": doc_a["id"]})
        sb = b.post("/sessions", json={"document_id": doc_b["id"]}).json()
        b.post(f"/sessions/{sb['id']}/annotations", json={"page_no": 1, "type": "exam", "text": "손실 함수 정의"})
        b.post("/timetable", json={"course": "운영체제", "weekday": 0, "start": "09:00", "end": "10:15", "place": ""})
        jokbo = lambda: a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"]

        # 처음엔 모두 공개 · 합치기
        assert jokbo() == [b_name]
        assert a.get(f"/friends/{b_id}/timetable").json()["classes"][0]["course"] == "운영체제"
        assert a.get("/friends/jokbo").json()["docs"][0]["friends"] == [b_name]

        # 친구(B)가 시간표 비공개 → 못 봄 / 족보 항목에서 시험 표시를 빼면 합쳐도 시험 표시는 안 옴
        b.patch("/friends/settings", json={"share_timetable": False, "items": ["terms"]})
        assert a.get(f"/friends/{b_id}/timetable").status_code == 403
        sheet = a.get(f"/documents/{doc_a['id']}/jokbo").json()
        assert not any(n["who"] == b_name for c in sheet["crowd"] for n in c["notes"])
        b.patch("/friends/settings", json={"share_timetable": True, "items": ["exam", "terms"]})

        # B 가 그 강의자료만 비공개 → 안 합쳐짐, 다시 공개 → 합쳐짐
        b.patch(f"/documents/{doc_b['id']}/friends", json={"share": False})
        assert jokbo() == []
        b.patch(f"/documents/{doc_b['id']}/friends", json={"share": True})
        # B 가 A 에게만 숨기기
        b.patch(f"/friends/{a_id}/settings", json={"share": False})
        assert jokbo() == [] and a.get(f"/friends/{b_id}/timetable").status_code == 403
        b.patch(f"/friends/{a_id}/settings", json={"share": True})
        # A 가 합치기 끄기: 전체 · 이 친구 · 이 자료
        for off, on in ((("/friends/settings", {"merge_jokbo": False}), ("/friends/settings", {"merge_jokbo": True})),
                        ((f"/friends/{b_id}/settings", {"merge": False}), (f"/friends/{b_id}/settings", {"merge": True})),
                        ((f"/documents/{doc_a['id']}/friends", {"merge": False}), (f"/documents/{doc_a['id']}/friends", {"merge": True}))):
            a.patch(off[0], json=off[1])
            assert jokbo() == []
            a.patch(on[0], json=on[1])
            assert jokbo() == [b_name]

        # 친구 신청 받지 않기
        c, _ = person("하준")
        b.patch("/friends/settings", json={"allow_requests": False})
        assert c.post("/friends", json={"code": b_code}).status_code == 403
        c.__exit__(None, None, None)
        me = a.get("/friends").json()
        assert me["me"]["prefs"]["share_jokbo"] is True and me["friends"][0]["their_timetable"] is True
    finally:
        for x in (a, b):
            x.__exit__(None, None, None)
