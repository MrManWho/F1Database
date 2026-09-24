"""v2.0 security, privacy and account controls: public pages, two-step sign-in, devices, export, account deletion,
leaving and handing over a league, rate limits, secret redaction and the import preview."""

import io
import json

from conftest import login, players, run_event
from f1tracker import app as appmod
from f1tracker import auth, community, discord, ratelimit, roles, security, services as S, storage


def _league(master_client, name="Safe League", players_=None, logins=None):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite", "player_name": players_ or [],
                                                   "player_login": logins or []})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _client(app, name, password="password1"):
    c = app.test_client()
    login(c, name, password)
    return c


# --------------------------------------------------------------------------- public pages

def test_public_pages_only_count_submitted_rounds(app, master_client):
    token = _league(master_client, "Open League")
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "visibility": "public"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        run_event(conn, evs[0], order=ids)
        run_event(conn, evs[1], order=list(reversed(ids)), complete=False)       # a draft
        key = community.public_key(conn)
        leader = S.driver_standings(conn, sid, completed_only=True)[0]
        draft_winner = S.driver_map(conn)[ids[-1]]["name"]
    anon = app.test_client()
    standings = anon.get(f"/public/{token}/{key}/standings").get_data(as_text=True)
    assert leader["driver"]["name"] in standings
    assert anon.get(f"/public/{token}/{key}/round/{evs[0]['id']}").status_code == 200
    assert anon.get(f"/public/{token}/{key}/round/{evs[1]['id']}").status_code == 404
    assert f"/round/{evs[1]['id']}" not in anon.get(f"/public/{token}/{key}").get_data(as_text=True)
    assert draft_winner
    assert anon.get(f"/public/{token}/wrong-key").status_code == 404


# --------------------------------------------------------------------------- two-step sign-in and devices

def test_two_step_sign_in_needs_the_code(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    ana = _client(app, "ana")
    ana.post("/account/two-step", data={"csrf_token": "tok", "action": "start"})
    secret = security.totp_status("ana")["secret"]
    assert secret and not security.totp_status("ana")["enabled"]
    page = ana.get("/accounts").get_data(as_text=True)
    assert secret in page and "otpauth://" in page
    wrong = "111111" if security.totp_now(secret) != "111111" else "222222"
    ana.post("/account/two-step", data={"csrf_token": "tok", "action": "confirm", "code": wrong})
    assert not security.totp_status("ana")["enabled"]
    ana.post("/account/two-step", data={"csrf_token": "tok", "action": "confirm", "code": security.totp_now(secret)})
    assert security.totp_status("ana")["enabled"]

    fresh = app.test_client()
    res = fresh.post("/login", data={"username": "ana", "password": "password1"})
    assert res.headers["Location"].endswith("/login/code")
    assert fresh.get("/accounts").status_code == 302                         # not signed in yet
    with fresh.session_transaction() as s:
        s["csrf"] = "tok"
    fresh.post("/login/code", data={"csrf_token": "tok", "code": wrong})
    assert fresh.get("/accounts").status_code == 302
    fresh.post("/login/code", data={"csrf_token": "tok", "code": security.totp_now(secret)})
    assert fresh.get("/accounts").status_code == 200
    # A site admin can switch it off for someone who lost their phone.
    master_client.post("/accounts/ana/two-step-reset", data={"csrf_token": "tok"})
    assert not security.totp_status("ana")["enabled"]


def test_totp_matches_the_rfc_test_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"     # "12345678901234567890"
    assert security.totp_now(secret, at=59) == "287082"
    assert security.verify_code(secret, "287 082", at=59)


def test_signing_out_other_devices_ends_their_sessions(app):
    auth.create_user("ana", "Ana", "password1")
    phone, laptop = _client(app, "ana"), _client(app, "ana")
    assert phone.get("/accounts").status_code == 200 and laptop.get("/accounts").status_code == 200
    assert len(security.sessions("ana")) == 2
    laptop.post("/account/sessions/end-others", data={"csrf_token": "tok"})
    assert laptop.get("/accounts").status_code == 200
    assert phone.get("/accounts").status_code == 302
    assert len(security.sessions("ana")) == 1


def test_changing_the_password_signs_out_other_devices(app):
    auth.create_user("ana", "Ana", "password1")
    phone, laptop = _client(app, "ana"), _client(app, "ana")
    laptop.post("/account/password", data={"csrf_token": "tok", "current_password": "password1",
                                           "password": "newpassword9", "confirm_password": "newpassword9"})
    assert phone.get("/accounts").status_code == 302 and laptop.get("/accounts").status_code == 200


# --------------------------------------------------------------------------- export, deletion, leaving

def test_account_export_has_my_data_and_no_secrets(app, master_client):
    auth.create_user("ana", "Ana", "password1", email="ana@example.com")
    token = _league(master_client, players_=["Ana Silva"], logins=["ana"])
    ana = _client(app, "ana")
    res = ana.get("/account/export")
    body = res.get_data(as_text=True)
    data = json.loads(body)
    assert data["format"] == "paddock-legacy-account" and data["account"]["email"] == "ana@example.com"
    assert data["leagues"][0]["league"] == "Safe League" and data["leagues"][0]["driver"]["name"] == "Ana Silva"
    assert "password" not in body and "sid" not in json.dumps(data["signed_in_devices"])
    assert "david" not in body.lower()                                      # nobody else's account
    assert token


def test_deleting_my_account_keeps_league_results(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client, players_=["Ana Silva"], logins=["ana"])
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
        before = [dict(r) for r in conn.execute("SELECT * FROM results ORDER BY id")]
    ana = _client(app, "ana")
    ana.post("/account/delete", data={"csrf_token": "tok", "confirm": "wrong", "password": "password1"})
    assert auth.get_user("ana")
    ana.post("/account/delete", data={"csrf_token": "tok", "confirm": "ana", "password": "password1"})
    assert not auth.get_user("ana")
    with storage.session(token) as conn:
        assert [dict(r) for r in conn.execute("SELECT * FROM results ORDER BY id")] == before
        assert not conn.execute("SELECT 1 FROM career_members WHERE username = 'ana'").fetchone()
        assert any(p["name"] == "Ana Silva" for p in S.player_drivers(conn))
    # The only site admin can't delete themselves.
    master_client.post("/account/delete", data={"csrf_token": "tok", "confirm": "david", "password": "password1"})
    assert auth.get_user("david")


def test_leaving_one_league_leaves_the_others_alone(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    a = _league(master_client, "League A", players_=["Ana Silva"], logins=["ana"])
    b = _league(master_client, "League B", players_=["Ana Two"], logins=["ana"])
    ana = _client(app, "ana")
    ana.post(f"/career/{a}/leave", data={"csrf_token": "tok", "confirm_name": "League"})
    with storage.session(a) as conn:
        assert conn.execute("SELECT 1 FROM career_members WHERE username = 'ana'").fetchone()
    ana.post(f"/career/{a}/leave", data={"csrf_token": "tok", "confirm_name": "League A"})
    with storage.session(a) as conn:
        assert not conn.execute("SELECT 1 FROM career_members WHERE username = 'ana'").fetchone()
        assert "left the league" in community.audit_entries(conn)[0]["summary"]
    with storage.session(b) as conn:
        assert conn.execute("SELECT 1 FROM career_members WHERE username = 'ana'").fetchone()
    assert "Leave League B" in ana.get(f"/career/{b}/me").get_data(as_text=True)


def test_handing_a_league_over(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("bo", "Bo", "password1")
    token = _league(master_client, players_=["Ana Silva"], logins=["ana"])
    with storage.session(token) as conn:
        roles.set_member(conn, "ana", "race_master", players(conn)[0])
        roles.set_member(conn, "bo", "member")
    ana = _client(app, "ana")
    assert "Hand the league over" in ana.get(f"/career/{token}/members").get_data(as_text=True)
    ana.post(f"/career/{token}/members/transfer", data={"csrf_token": "tok", "username": "bo", "confirm_name": "nope"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT role FROM career_members WHERE username = 'bo'").fetchone()["role"] == "member"
    ana.post(f"/career/{token}/members/transfer", data={"csrf_token": "tok", "username": "bo", "confirm_name": "bo"})
    with storage.session(token) as conn:
        got = {r["username"]: r["role"] for r in conn.execute("SELECT username, role FROM career_members")}
        assert got["bo"] == "race_master" and got["ana"] == "member"
        assert conn.execute("SELECT driver_id FROM career_members WHERE username = 'ana'").fetchone()["driver_id"]


# --------------------------------------------------------------------------- rate limits

def test_invitations_and_join_requests_are_rate_limited(app, master_client, monkeypatch):
    monkeypatch.setattr(appmod, "INVITE_LIMIT", 2)
    for name in ("u1", "u2", "u3"):
        auth.create_user(name, name.upper(), "password1")
    token = _league(master_client)
    for name in ("u1", "u2", "u3"):
        master_client.post(f"/career/{token}/members/invite", data={"csrf_token": "tok", "username": name,
                                                                     "role": "member"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 2

    monkeypatch.setattr(appmod, "JOIN_LIMIT", 1)
    leagues = [_league(master_client, f"Open {i}") for i in range(2)]
    for t in leagues:
        master_client.post(f"/career/{t}/members/settings", data={"csrf_token": "tok", "join_mode": "requests"})
        with storage.session(t) as conn:
            storage.set_meta(conn, "join_mode", "requests")
    joe = _client(app, "u1")
    for t in leagues:
        joe.post(f"/career/{t}/join", data={"csrf_token": "tok", "role": "spectator"})
    counts = []
    for t in leagues:
        with storage.session(t) as conn:
            counts.append(conn.execute("SELECT COUNT(*) FROM join_requests").fetchone()[0])
    assert counts == [1, 0]


def test_rate_limiter_windows():
    assert all(ratelimit.allow("t", "x", 3, 60) for _ in range(3))
    assert not ratelimit.allow("t", "x", 3, 60)
    assert ratelimit.allow("t", "y", 3, 60)          # per person


# --------------------------------------------------------------------------- redaction and import

def test_downloads_never_include_the_discord_webhook_or_public_key(app, master_client):
    token = _league(master_client)
    hook = "https://discord.com/api/webhooks/123/secret-part"
    with storage.session(token) as conn:
        discord.save_settings(conn, hook, True, True)
        key = community.public_key(conn)
    body = master_client.get(f"/career/{token}/export").get_data(as_text=True)
    data = json.loads(body)
    assert "secret-part" not in body and key not in body
    assert data["_export"]["format"] == "paddock-legacy-league" and data["drivers"] and "activity" not in data
    assert "audit_log" in data
    raw = master_client.get(f"/career/{token}/backup").get_data()
    assert b"secret-part" not in raw
    with storage.session(token) as conn:          # the league itself keeps them
        assert storage.get_meta(conn, "discord_webhook") == hook and community.public_key(conn) == key


def test_import_is_previewed_then_added_as_a_new_league(app, master_client, tmp_path):
    token = _league(master_client, "Original")
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
    raw = master_client.get(f"/career/{token}/backup").get_data()
    before = {c["token"] for c in storage.list_careers()}
    res = master_client.post("/careers/import", data={"csrf_token": "tok", "file": (io.BytesIO(raw), "x.f1career")},
                             content_type="multipart/form-data")
    page = res.get_data(as_text=True)
    assert res.status_code == 200 and "Original" in page and "1 with results" in page
    assert {c["token"] for c in storage.list_careers()} == before              # nothing added yet
    res = master_client.post("/careers/import", data={"csrf_token": "tok", "confirm": "1"})
    after = {c["token"] for c in storage.list_careers()}
    assert len(after - before) == 1 and token in after
    # A bad file is refused before anything is staged.
    res = master_client.post("/careers/import", data={"csrf_token": "tok", "file": (io.BytesIO(b"nope"), "y.f1career")},
                             content_type="multipart/form-data", follow_redirects=True)
    assert "not a valid" in res.get_data(as_text=True)
    assert not list((storage.data_dir() / "imports").glob("*.f1career"))
    # Cancelling leaves nothing behind.
    master_client.post("/careers/import", data={"csrf_token": "tok", "file": (io.BytesIO(raw), "x.f1career")},
                       content_type="multipart/form-data")
    master_client.post("/careers/import", data={"csrf_token": "tok", "cancel": "1"})
    assert {c["token"] for c in storage.list_careers()} == after
    assert not list((storage.data_dir() / "imports").glob("*.f1career"))
