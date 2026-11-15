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
        # 공개는 기본으로 꺼져 있다: 과목을 정하고 그 과목을 공유한다고 골라야 합쳐진다
        for who, d in ((a, doc_a), (b, doc_b)):
            who.patch(f"/documents/{d['id']}", json={"course": "운영체제"})
            who.patch("/friends/settings", json={"share_courses": ["운영체제"], "share_timetable": True})
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
        # 공개는 기본으로 꺼져 있다: 과목을 정하고 그 과목을 공유한다고 골라야 합쳐진다
        for who, d in ((a, doc_a), (b, doc_b)):
            who.patch(f"/documents/{d['id']}", json={"course": "운영체제"})
            who.patch("/friends/settings", json={"share_courses": ["운영체제"], "share_timetable": True})
        a.post("/sessions", json={"document_id": doc_a["id"]})
        sb = b.post("/sessions", json={"document_id": doc_b["id"]}).json()
        b.post(f"/sessions/{sb['id']}/annotations", json={"page_no": 1, "type": "exam", "text": "손실 함수 정의"})
        b.post("/timetable", json={"course": "운영체제", "weekday": 0, "start": "09:00", "end": "10:15", "place": ""})
        jokbo = lambda: a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"]

        # 처음엔 모두 공개 · 합치기
        assert jokbo() == [b_name]
        # 같은 과목 듣는 친구 (띄어쓰기가 달라도 같은 과목)
        a.post("/timetable", json={"course": "운영 체제", "weekday": 1, "start": "09:00", "end": "10:15", "place": ""})
        assert a.get("/friends").json()["friends"][0]["same_courses"] == ["운영체제"]
        # 친구가 아무것도 공개하지 않으면 같은 과목인지도 알 수 없다
        b.patch("/friends/settings", json={"share_courses": [], "share_timetable": False})
        assert a.get("/friends").json()["friends"][0]["same_courses"] == []
        b.patch("/friends/settings", json={"share_courses": ["운영체제"], "share_timetable": True})
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


def test_forgot_password_with_recovery_code_and_owner_reset_code(invite):
    with TestClient(app) as c:
        name = f"잊음{uuid.uuid4().hex[:6]}"
        res = c.post("/auth/signup", json={"name": name, "password": "secret12", "invite": "우리반-2026"}).json()
        code = res["recovery_code"]   # 가입할 때 한 번 보여 준다
        assert len(code) == 14 and res["user"]["name"] == name
        assert c.get("/account/recovery").json() == {"has_code": True}
        c.post("/auth/logout")
    with TestClient(app) as anon:
        assert anon.post("/auth/reset", json={"name": name, "code": "AAAA-BBBB-CCCC", "password": "newpass1"}).status_code == 401
        ok = anon.post("/auth/reset", json={"name": name, "code": code.lower().replace("-", " "), "password": "newpass1"})
        assert ok.status_code == 200 and anon.get("/auth/me").json()["user"]["name"] == name
        # 복구 코드는 한 번 쓰면 끝, 새 비밀번호로 로그인
        assert anon.post("/auth/reset", json={"name": name, "code": code, "password": "again123"}).status_code == 401
        assert anon.post("/auth/login", json={"name": name, "password": "newpass1"}).status_code == 200
        # 로그인한 채로 비밀번호 바꾸기
        assert anon.post("/account/password", json={"current": "wrong", "password": "third123"}).status_code == 401
        assert anon.post("/account/password", json={"current": "newpass1", "password": "third123"}).status_code == 200
        assert anon.post("/auth/login", json={"name": name, "password": "third123"}).status_code == 200
        # 사용자 계정으로는 관리자 일을 못 한다
        assert anon.post("/admin/reset-code", json={"name": name}).status_code == 401


def test_email_verification_and_forgot_password_by_email(invite, tmp_path, monkeypatch):
    import re as _re

    from app import mailer
    from app.db import Database

    sent = []
    monkeypatch.setattr(mailer, "send", lambda db, to, subject, text: sent.append((to, text)))
    code_in = lambda: _re.search(r"\b(\d{6})\b", sent[-1][1]).group(1)
    with TestClient(app) as owner, TestClient(app) as anon, TestClient(app) as admin:
        old = app.state.db
        app.state.db = Database(str(tmp_path / "m.db"))
        try:
            owner.post("/auth/signup", json={"name": "주인", "password": "secret12", "invite": "우리반-2026"})
            # 메일 설정 전에는 이메일 찾기를 못 쓴다
            assert anon.post("/auth/forgot", json={"who": "주인"}).status_code == 503
            assert admin.post("/admin/setup", json={"invite": "우리반-2026", "password": "admin-pass-1"}).status_code == 200
            assert admin.put("/admin/mail", json={"user": "lune.app@gmail.com", "password": "abcd efgh ijkl mnop"}).status_code == 200
            assert admin.get("/admin/mail").json() == {"user": "lune.app@gmail.com"}
            assert owner.put("/admin/mail", json={"user": "x@gmail.com", "password": "abcdefghijklmnop"}).status_code == 401
            # 이메일 등록: 인증번호 → 확인
            assert owner.post("/account/email", json={"email": "나@없는주소"}).status_code == 400
            assert owner.post("/account/email", json={"email": "me@example.com"}).json() == {"sent": "me@example.com"}
            assert sent[-1][0] == "me@example.com"
            assert owner.post("/account/email/verify", json={"code": "000000" if code_in() != "000000" else "111111"}).status_code == 400
            assert owner.post("/account/email/verify", json={"code": code_in()}).json()["email"] == "me@example.com"
            # 비밀번호 찾기: 이메일(또는 이름) → 인증번호 → 새 비밀번호
            assert anon.post("/auth/forgot", json={"who": "없는사람"}).json()["ok"] is True   # 있는지 알려 주지 않는다
            n = len(sent)
            anon.post("/auth/forgot", json={"who": "ME@example.com"})
            assert len(sent) == n + 1 and sent[-1][0] == "me@example.com"
            assert anon.post("/auth/reset", json={"name": "주인", "code": code_in(), "password": "newpass1"}).status_code == 200
            assert anon.post("/auth/login", json={"name": "주인", "password": "newpass1"}).status_code == 200
        finally:
            app.state.db = old



def test_admin_page_separate_from_user_accounts(invite, tmp_path):
    """관리자 페이지: 처음 한 번 초대 코드로 비밀번호를 정하고, 그 뒤로는 관리자 비밀번호로만"""
    import io
    import tarfile

    from app.db import Database

    with TestClient(app) as admin, TestClient(app) as friend, TestClient(app) as anon:
        old = app.state.db
        app.state.db = Database(str(tmp_path / "a.db"))
        try:
            friend.post("/auth/signup", json={"name": "친구", "password": "secret12", "invite": "우리반-2026"})
            assert anon.get("/admin/status").json() == {"set": False, "logged_in": False, "auth": True}
            assert anon.get("/admin/overview").status_code == 401
            assert anon.post("/admin/setup", json={"invite": "틀림", "password": "admin-pass-1"}).status_code == 403
            assert admin.post("/admin/setup", json={"invite": "우리반-2026", "password": "short"}).status_code == 400
            assert admin.post("/admin/setup", json={"invite": "우리반-2026", "password": "admin-pass-1"}).status_code == 200
            # 한 번 정하면 잠긴다
            assert anon.post("/admin/setup", json={"invite": "우리반-2026", "password": "hijack-123"}).status_code == 409
            assert anon.post("/admin/login", json={"password": "wrong-pass"}).status_code == 401
            # 사용자 계정 로그인으로는 관리자 일을 못 한다
            assert friend.get("/admin/overview").status_code == 401
            over = admin.get("/admin/overview").json()
            assert [u["name"] for u in over["users"]] == ["친구"] and "disk_free_gb" in over["server"]
            # 초대 코드 바꾸기
            assert admin.put("/admin/invite", json={"code": "새코드2027"}).status_code == 200
            assert anon.post("/auth/signup", json={"name": "새사람", "password": "secret12", "invite": "우리반-2026"}).status_code == 403
            assert anon.post("/auth/signup", json={"name": "새사람", "password": "secret12", "invite": "새코드2027"}).status_code == 200
            # 비밀번호 초기화 코드 · 로그인 끊기
            code = admin.post("/admin/reset-code", json={"name": "친구"}).json()["code"]
            fid = next(u["id"] for u in admin.get("/admin/overview").json()["users"] if u["name"] == "친구")
            assert admin.post(f"/admin/users/{fid}/logout").status_code == 200
            assert friend.get("/documents").status_code == 401
            assert friend.post("/auth/reset", json={"name": "친구", "code": code, "password": "fresh123"}).status_code == 200
            # 서버 옮기기 코드
            mc = admin.post("/admin/migrate").json()["code"]
            res = anon.get(f"/migrate/export?code={mc}")
            assert res.status_code == 200 and any(n.endswith(".db") for n in tarfile.open(fileobj=io.BytesIO(res.content)).getnames())
            # 관리자 비밀번호 바꾸기 · 로그아웃
            assert admin.post("/admin/password", json={"current": "admin-pass-1", "password": "admin-pass-2"}).status_code == 200
            admin.post("/admin/logout")
            assert admin.get("/admin/overview").status_code == 401
            assert admin.post("/admin/login", json={"password": "admin-pass-2"}).status_code == 200
        finally:
            app.state.db = old


def test_daily_backup_to_private_dataset(invite, tmp_path, monkeypatch):
    """백업: DB 사본 + 새 파일만 올린다 (허깅페이스 대신 가짜로 확인)"""
    import os
    import time as _t

    import huggingface_hub
    from app import backup
    from app.db import Database

    commits = []

    class FakeApi:
        def __init__(self, token=None): pass
        def create_repo(self, *a, **k): pass
        def create_commit(self, repo, repo_type, commit_message, operations):
            commits.append([op.path_in_repo for op in operations])
        def list_repo_files(self, *a, **k): return [f"db/lune-2026-01-{d:02d}.db.gz" for d in range(1, 20)]
        def whoami(self): return {"name": "kimheejin0823"}

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    d = Database(str(tmp_path / "b.db"))
    up = tmp_path / "uploads"; up.mkdir()
    (up / "a.pdf").write_bytes(b"x" * 10)
    (up / "full-s.wav").write_bytes(b"x")
    old = _t.time() - 3600
    os.utime(up / "a.pdf", (old, old))
    d.set_setting("backup_token", "hf_x"); d.set_setting("backup_repo", "me/lune-backup")
    assert backup.due(d)
    r = backup.run(d, str(up))
    assert r["files"] == 1 and ["uploads/a.pdf"] in commits and any("db/latest.db.gz" in c for c in commits)
    assert any(c and c[0].startswith("db/lune-2026-01-01") for c in commits)   # 오래된 사본 정리
    assert not backup.due(d)
    commits.clear()
    backup.run(d, str(up))
    assert not any("uploads/a.pdf" in c for c in commits)   # 이미 올린 파일은 다시 안 올린다


def test_friend_sharing_is_off_until_courses_are_chosen(invite):
    a, _ = person("가람")
    b, b_name = person("나래")
    try:
        b_code = b.get("/friends").json()["me"]["code"]
        a.post("/friends", json={"code": b_code})
        a_id = b.get("/friends").json()["incoming"][0]["id"]
        b.post(f"/friends/{a_id}/accept")
        b_id = a.get("/friends").json()["friends"][0]["id"]
        doc_a, doc_b = upload(a), upload(b)
        for who, d, course in ((a, doc_a, "운영체제"), (b, doc_b, "운영체제")):
            who.patch(f"/documents/{d['id']}", json={"course": course})
        sb = b.post("/sessions", json={"document_id": doc_b["id"]}).json()
        b.post(f"/sessions/{sb['id']}/annotations", json={"page_no": 1, "type": "exam", "text": "손실 함수"})
        b.post("/timetable", json={"course": "운영체제", "weekday": 0, "start": "09:00", "end": "10:15", "place": ""})
        # 기본: 아무것도 공유 안 함
        me_b = b.get("/friends").json()["me"]
        assert me_b["prefs"]["share_jokbo"] is False and me_b["courses"] == ["운영체제"]
        assert a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"] == []
        assert a.get(f"/friends/{b_id}/timetable").status_code == 403
        # 다른 과목만 공유하면 이 자료는 안 합쳐진다
        b.patch("/friends/settings", json={"share_courses": ["데이터베이스"]})
        assert a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"] == []
        # 그 과목을 고르면 합쳐진다
        b.patch("/friends/settings", json={"share_courses": ["운영체제"], "share_timetable": True})
        assert a.get(f"/documents/{doc_a['id']}/jokbo").json()["friends"] == [b_name]
        assert a.get(f"/friends/{b_id}/timetable").status_code == 200
        # 모두 빼면 다시 비공개
        b.patch("/friends/settings", json={"share_courses": []})
        assert b.get("/friends").json()["me"]["prefs"]["share_jokbo"] is False
    finally:
        for x in (a, b):
            x.__exit__(None, None, None)
