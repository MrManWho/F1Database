"""v3.2 maintenance mode: middleware enforcement for every role, owner access, API/POST blocking, delivery pause
and resume, the database and environment switches, no caching, and the owner's controls."""

import sqlite3

import pytest

from conftest import login
from f1tracker import auth, maintenance, outbox, roles, storage


def _owner():
    auth.create_user("devon", "Devon", "password1", is_master=True)
    with auth.accounts() as conn:
        conn.execute("UPDATE users SET is_owner = 1 WHERE username = 'devon'")


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


@pytest.fixture
def site(app):
    """The owner, a league with every role, and a site Race Master who isn't the owner."""
    _owner()
    owner = _client(app, "devon")
    res = owner.post("/careers/new", data={"name": "Secret League Name", "year": "2026", "csrf_token": "tok",
                                           "player_name": ["Ana Silva"], "player_login": [""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    for u in ("rm", "sk", "drv", "spec", "siterm"):
        auth.create_user(u, u.title(), "password1", is_master=(u == "siterm"))
    with storage.session(token) as conn:
        roles.set_member(conn, "rm", "race_master")
        roles.set_member(conn, "sk", "scorekeeper")
        roles.set_member(conn, "drv", "member")
        roles.set_member(conn, "spec", "spectator")
    return {"owner": owner, "token": token}


def _enable(owner, message="Upgrading to 4.0", **extra):
    data = {"csrf_token": "tok", "action": "enable", "confirm": "MAINTENANCE", "message": message, **extra}
    return owner.post("/settings/system", data=data)


def _is_closed(res):
    return res.status_code == 503 and res.headers.get("X-Paddock-Maintenance") == "1"


# --------------------------------------------------------------------------- who is blocked

def test_anonymous_visitors_get_the_maintenance_page(app, site):
    _enable(site["owner"], expected_end="2026-10-01T18:00", tz_offset="0")
    anon = app.test_client()
    for path in ("/", f"/career/{site['token']}/dashboard", "/help", "/directory", "/register", "/forgot"):
        res = anon.get(path)
        assert _is_closed(res), path
    page = anon.get("/").get_data(as_text=True)
    assert "The paddock is temporarily closed" in page and "Upgrading to 4.0" in page
    assert "2026-10-01" in page and "Site owner sign in" in page and "Check again" in page
    assert "Secret League Name" not in page and "Devon" not in page


def test_every_non_owner_role_gets_503(app, site):
    _enable(site["owner"])
    for name in ("rm", "sk", "drv", "spec", "siterm"):
        c = _client(app, name)
        assert _is_closed(c.get(f"/career/{site['token']}/dashboard")), name
        assert _is_closed(c.get("/")), name
        assert _is_closed(c.get("/accounts")), name


def test_existing_sessions_are_blocked_immediately(app, site):
    drv = _client(app, "drv")
    assert drv.get(f"/career/{site['token']}/dashboard").status_code == 200
    _enable(site["owner"])
    assert _is_closed(drv.get(f"/career/{site['token']}/dashboard"))


def test_the_site_owner_keeps_full_access(app, site):
    _enable(site["owner"])
    owner = site["owner"]
    res = owner.get(f"/career/{site['token']}/dashboard")
    assert res.status_code == 200 and "Maintenance mode is on." in res.get_data(as_text=True)
    assert owner.get("/settings/system").status_code == 200
    res = owner.post(f"/career/{site['token']}/rename", data={"csrf_token": "tok", "name": "Owner Renamed"})
    assert res.status_code == 302
    with storage.session(site["token"]) as conn:
        assert storage.get_meta(conn, "career_name") == "Owner Renamed"
    assert owner.get(f"/career/{site['token']}/backup").status_code == 200      # backups keep working


def test_api_and_post_requests_are_blocked_server_side(app, site):
    rm = _client(app, "rm")
    _enable(site["owner"])
    res = rm.get(f"/api/career/{site['token']}/notifications")
    assert res.status_code == 503 and res.get_json()["maintenance"] is True and res.get_json()["ok"] is False
    assert res.headers["Retry-After"]
    res = rm.post(f"/career/{site['token']}/rename", data={"csrf_token": "tok", "name": "Hacked"})
    assert _is_closed(res)
    res = rm.post(f"/career/{site['token']}/rename", data={"csrf_token": "tok", "name": "Hacked"},
                  headers={"X-Requested-With": "fetch"})
    assert res.status_code == 503 and res.get_json()["maintenance"]
    with storage.session(site["token"]) as conn:
        assert storage.get_meta(conn, "career_name") == "Secret League Name"


def test_nothing_gets_round_it(app, site):
    """No address, query parameter, cookie or secret URL lets a non-owner in."""
    _enable(site["owner"])
    drv = _client(app, "drv")
    drv.set_cookie("owner", "1")
    drv.set_cookie("maintenance_bypass", "1")
    for path in (f"/career/{site['token']}/dashboard?owner=1&bypass=1&maintenance=0", "/settings/system",
                 "/accounts?admin=1"):
        res = drv.get(path, headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
        assert _is_closed(res) or res.status_code == 403, path
    assert _is_closed(drv.get("/settings/system"))


def test_login_stays_open_and_only_the_owner_gets_in(app, site):
    _enable(site["owner"])
    anon = app.test_client()
    page = anon.get("/login")
    assert page.status_code == 200 and "closed for maintenance" in page.get_data(as_text=True)
    owner = app.test_client()
    res = owner.post("/login", data={"username": "devon", "password": "password1"})
    assert res.status_code == 302
    assert owner.get(f"/career/{site['token']}/dashboard").status_code == 200
    drv = app.test_client()
    res = drv.post("/login", data={"username": "drv", "password": "password1"}, follow_redirects=True)
    assert _is_closed(res)                           # signed in, but still sent to the closed page
    assert _is_closed(drv.get(f"/career/{site['token']}/dashboard"))


def test_open_endpoints_during_maintenance(app, site):
    _enable(site["owner"])
    anon = app.test_client()
    health = anon.get("/healthz")
    assert health.status_code == 200 and health.get_json()["maintenance"] is True
    assert anon.get("/sw.js").status_code == 200
    assert anon.get("/static/css/app.css").status_code == 200
    assert _is_closed(anon.get("/maintenance"))


# --------------------------------------------------------------------------- switches

def test_the_database_switch_and_the_environment_switch_each_activate_it(app, site, monkeypatch):
    anon = app.test_client()
    assert anon.get("/").status_code != 503
    auth.set_setting("maintenance_enabled", "1")
    assert _is_closed(anon.get("/"))
    auth.set_setting("maintenance_enabled", "0")
    assert anon.get("/").status_code != 503
    monkeypatch.setenv("FORCE_MAINTENANCE", "true")
    assert _is_closed(anon.get("/"))


def test_force_maintenance_overrides_the_off_setting_and_cant_be_turned_off_here(app, site, monkeypatch):
    monkeypatch.setenv("FORCE_MAINTENANCE", "true")
    assert not maintenance.settings()["enabled"]
    page = site["owner"].get("/settings/system").get_data(as_text=True)
    assert "The Render override is on" in page
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "disable", "resume_deliveries": "1"})
    assert maintenance.active()
    assert _is_closed(_client(app, "drv").get("/"))
    assert "FORCE_MAINTENANCE" in site["owner"].get("/").get_data(as_text=True)     # the owner's banner says so


def test_turning_it_off_restores_access_without_a_restart(app, site):
    drv = _client(app, "drv")
    _enable(site["owner"])
    assert _is_closed(drv.get(f"/career/{site['token']}/dashboard"))
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "disable", "resume_deliveries": "1"})
    assert drv.get(f"/career/{site['token']}/dashboard").status_code == 200
    assert app.test_client().get("/maintenance").status_code == 302      # nothing to show when it's off


def test_maintenance_responses_are_never_cached(app, site):
    _enable(site["owner"])
    for res in (app.test_client().get("/"), _client(app, "rm").get(f"/api/career/{site['token']}/notifications")):
        assert res.status_code == 503
        assert "no-store" in res.headers["Cache-Control"] and res.headers["Pragma"] == "no-cache"
        assert int(res.headers["Retry-After"]) >= 60
    assert app.test_client().get("/").headers["Clear-Site-Data"] == '"cache"'


def test_retry_after_follows_the_expected_reopening():
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="minutes")
    assert 7000 < maintenance.retry_after(soon) <= 7200
    assert maintenance.retry_after("") == maintenance.DEFAULT_RETRY
    assert maintenance.retry_after("2000-01-01T00:00+00:00") == 60


# --------------------------------------------------------------------------- deliveries

def test_deliveries_pause_and_resume_once_each(app, site, monkeypatch):
    sent = []
    monkeypatch.setattr(outbox, "_send", lambda kind, p: sent.append((kind, p["subject"])))
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "save", "pause_deliveries": "1",
                                                 "message": ""})
    assert maintenance.deliveries_paused() and not maintenance.active()      # a pause without closing the site
    outbox.enqueue("email", {"to": ["a@example.com"], "subject": "Round 1", "text": "t"}, background=False)
    outbox.enqueue("email", {"to": ["b@example.com"], "subject": "Round 2", "text": "t"}, background=False)
    assert outbox.drain(background=False) == 0 and sent == [] and outbox.pending() == 2
    assert not outbox.process(1)                                             # no attempt used while paused
    with auth.accounts() as conn:
        assert all(r["attempts"] == 0 for r in conn.execute("SELECT attempts FROM outbox"))
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "save", "message": ""})
    outbox.drain(background=False)          # (the save already drained in the background in real use)
    import time
    for _ in range(50):
        if outbox.pending() == 0:
            break
        time.sleep(0.05)
    assert sorted(sent) == [("email", "Round 1"), ("email", "Round 2")] and outbox.pending() == 0
    outbox.drain(background=False)
    assert len(sent) == 2                                                    # no duplicates


def test_direct_sends_are_refused_while_paused(app, site):
    from f1tracker import discord, mailer
    auth.set_setting("maintenance_pause_deliveries", "1")
    auth.set_setting("smtp_host", "smtp.example.com")
    auth.set_setting("smtp_from", "site@example.com")
    with pytest.raises(mailer.MailError):
        mailer.send(["a@example.com"], "s", "t")
    assert discord.post("https://discord.com/api/webhooks/1/x", "hi") is False


# --------------------------------------------------------------------------- the owner's controls

def test_turning_it_on_needs_the_typed_word_and_the_owner(app, site):
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "enable", "confirm": "maintenance"})
    assert not maintenance.active()
    assert _client(app, "siterm").get("/settings/system").status_code == 403      # a site Race Master isn't the owner
    assert _client(app, "rm").post("/settings/system", data={"csrf_token": "tok", "action": "enable",
                                                              "confirm": "MAINTENANCE"}).status_code == 403
    assert not maintenance.active()
    _enable(site["owner"])
    st = maintenance.state()
    assert st["enabled"] and st["enabled_by"] == "devon" and st["enabled_at"]


def test_on_edit_and_off_are_recorded_and_the_record_cant_be_changed(app, site):
    _enable(site["owner"])
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "save", "message": "Nearly done"})
    site["owner"].post("/settings/system", data={"csrf_token": "tok", "action": "disable", "resume_deliveries": "1"})
    actions = [h["action"] for h in maintenance.history()]
    assert actions == ["maintenance_off", "maintenance_edit", "maintenance_on"]
    assert "Nearly done" not in str(maintenance.history())                    # the record says what changed, not the text
    with auth.accounts() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM site_audit")
    assert "Recent changes" in site["owner"].get("/settings/system").get_data(as_text=True)


def test_off_by_default_and_nothing_changes(app, site):
    assert not maintenance.active()
    assert _client(app, "drv").get(f"/career/{site['token']}/dashboard").status_code == 200
    assert "Maintenance mode is on" not in site["owner"].get("/").get_data(as_text=True)


def test_a_site_without_an_owner_mark_falls_back_to_the_first_site_race_master(app):
    auth.create_user("first", "First", "password1", is_master=True)
    auth.create_user("second", "Second", "password1", is_master=True)
    assert maintenance.is_owner(auth.get_user("first")) and not maintenance.is_owner(auth.get_user("second"))
