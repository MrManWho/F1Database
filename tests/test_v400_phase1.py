"""4.0 Phase 1 (foundation): environments, health check, error log, delivery preview, declared access for every
route with a site-wide permission matrix, the append-only change record, the new shell and account preferences."""

import json
import re
import sqlite3

import pytest

from conftest import login
from f1tracker import auth, audit_trail, constants as C, ops, roles, storage, testsite
from f1tracker import services as S


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _league(master_client, name="Phase One League"):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva"], "player_login": [""]})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


# --------------------------------------------------------------------------- environment and health

def test_environment_names(monkeypatch):
    for var in ("F1_TRACKER_ENV", "F1_TRACKER_TEST_SITE", "RENDER"):
        monkeypatch.delenv(var, raising=False)
    assert ops.environment() == "local"
    monkeypatch.setenv("RENDER", "true")
    assert ops.environment() == "production"
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    assert ops.environment() == "test" and ops.environment_label() == "4.0 test"
    monkeypatch.setenv("F1_TRACKER_ENV", "staging")
    assert ops.environment() == "staging"


def test_health_check_is_public_and_private_information_free(app, master_client):
    auth.set_setting("smtp_password", "super-secret-pass")
    res = app.test_client().get("/healthz")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] and data["version"] == C.APP_VERSION and data["schema"] == C.SCHEMA_VERSION
    assert set(data["checks"]) == {"accounts_db", "data_dir"}
    assert "super-secret" not in res.get_data(as_text=True)


def test_environment_badge_shows_except_in_production(app, master_client, monkeypatch):
    monkeypatch.setenv("F1_TRACKER_ENV", "staging")
    assert "env-badge env-staging" in master_client.get("/").get_data(as_text=True)
    monkeypatch.setenv("F1_TRACKER_ENV", "production")
    assert "env-badge" not in master_client.get("/").get_data(as_text=True)


def test_structured_log_lines_are_json_and_scrubbed():
    import logging
    record = logging.LogRecord("f1tracker.requests", logging.INFO, __file__, 1, "sent to someone@example.com", None, None)
    record.endpoint, record.status = "dashboard", 200
    line = json.loads(ops.JsonFormatter().format(record))
    assert line["endpoint"] == "dashboard" and line["status"] == 200 and "[email]" in line["message"]


# --------------------------------------------------------------------------- error log

def test_page_errors_are_recorded_for_the_owner_without_private_details():
    from f1tracker.app import create_app
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "PROPAGATE_EXCEPTIONS": False})

    def explode():
        raise RuntimeError("could not reach alex@example.com at https://example.com/x?t=abcdefghijklmnopqrstuvwxyz123")
    app.add_url_rule("/explode-for-test", "explode_for_test", explode)
    app.view_functions["explode_for_test"].access = "self"
    auth.create_user("devon", "Devon", "password1", is_master=True)
    master_client = _client(app, "devon")
    for _ in range(2):
        res = master_client.get("/explode-for-test")
        assert res.status_code == 500 and "Something went wrong" in res.get_data(as_text=True)
    [err] = ops.errors()
    assert err["kind"] == "RuntimeError" and err["count"] == 2 and "test_v400_phase1.py:explode" in err["place"]
    assert "alex@example.com" not in err["message"] and "https://" not in err["message"] and "[email]" in err["message"]
    page = master_client.get("/settings/errors").get_data(as_text=True)
    assert "RuntimeError" in page
    auth.create_user("kim", "Kim", "password1")
    assert _client(app, "kim").get("/settings/errors").status_code == 403
    master_client.post("/settings/errors", data={"csrf_token": "tok"})
    assert ops.errors() == []


def test_background_errors_reach_the_error_log(app):
    import logging
    try:
        raise ValueError("outbox exploded")
    except ValueError:
        logging.getLogger("f1tracker.outbox").exception("drain failed")
    assert any(e["kind"] == "ValueError" for e in ops.errors())


# --------------------------------------------------------------------------- delivery preview

def test_delivery_preview_page_is_test_site_and_owner_only(app, master_client, monkeypatch):
    assert master_client.get("/settings/delivery-preview").status_code == 404      # not on the live site
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    from f1tracker import mailer
    mailer.send_later(["pat@example.com"], "Round 1 results", "Full text of the email")
    page = master_client.get("/settings/delivery-preview").get_data(as_text=True)
    assert "Round 1 results" in page and "Full text of the email" in page and "pat@example.com" not in page
    auth.create_user("kim", "Kim", "password1")
    assert _client(app, "kim").get("/settings/delivery-preview").status_code == 403
    master_client.post("/settings/delivery-preview", data={"csrf_token": "tok"})
    assert ops.previews() == []


def test_a_real_league_event_on_the_test_site_becomes_previews(app, master_client, monkeypatch):
    """Inviting someone by email on the test site: the invitation appears as a preview, nothing is sent."""
    import smtplib
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    token = _league(master_client)
    auth.create_user("kim", "Kim", "password1")
    with auth.accounts() as conn:
        conn.execute("UPDATE users SET email = 'kim@example.com' WHERE username = 'kim'")
    master_client.post(f"/career/{token}/members/invite", data={"csrf_token": "tok", "username": "kim", "role": "member"})
    assert any("invited" in p["title"].lower() for p in ops.previews())


def test_importing_a_live_backup_removes_the_email_password_and_webhooks(app, master_client, monkeypatch):
    import io
    token = _league(master_client)
    with storage.session(token) as conn:
        storage.set_meta(conn, "discord_webhook", "https://discord.com/api/webhooks/123/real-secret")
    auth.set_setting("smtp_password", "live-mail-password")
    phrase = "correct horse battery staple"
    blob = master_client.post("/settings/offsite-backup", data={"csrf_token": "tok", "passphrase": phrase,
                                                                "passphrase2": phrase}).get_data()
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    master_client.post("/settings/import-site-backup", data={"csrf_token": "tok", "passphrase": phrase, "confirm": "REPLACE",
                                                             "file": (io.BytesIO(blob), "b.plbk")},
                       content_type="multipart/form-data")
    assert auth.get_setting("smtp_password") is None
    with storage.session(token) as conn:
        assert storage.get_meta(conn, "discord_webhook") == testsite.PLACEHOLDER_WEBHOOK


# --------------------------------------------------------------------------- permissions: every site route, every kind of visitor

def _fill(rule):
    return re.sub(r"<int:[a-z_]+>", "1", re.sub(r"<(?!int:)[a-z_]+>", "x", rule.rule))


def test_every_site_route_holds_each_visitor_to_its_access_level(app, master_client):
    """Direct requests (not clicks): anonymous visitors, an ordinary signed-in person and the site owner."""
    from f1tracker import app as app_module
    auth.create_user("kim", "Kim", "password1")
    kim = _client(app, "kim")
    anon = app.test_client()
    checked = 0
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.rule.startswith(("/career/<token>", "/api/career/<token>")):
            continue            # league routes: test_v213's every-route x every-role test
        view = app.view_functions[rule.endpoint]
        access = "public" if rule.endpoint in app_module.PUBLIC_ENDPOINTS else getattr(view, "access", None)
        assert access in ("public", "self", "master"), f"{rule.endpoint} declares no access level"
        path = _fill(rule)
        for method in sorted(rule.methods & {"GET", "POST"}):
            call = lambda c: c.open(path, method=method, data={"csrf_token": "tok"})  # noqa: E731
            if access == "master":
                assert call(kim).status_code == 403, f"{method} {rule.rule} let an ordinary member in"
            if access in ("master", "self"):
                res = call(anon)
                assert res.status_code in (302, 401) and ("/login" in res.headers.get("Location", "") or res.status_code == 401), \
                    f"{method} {rule.rule} let an anonymous visitor in"
            if access == "public" and method == "GET":
                res = call(anon)
                assert "/login?" not in res.headers.get("Location", ""), f"public {rule.rule} asked for a login"
            checked += 1
    assert checked > 60


def test_site_owner_routes_are_not_reachable_by_a_league_race_master(app, master_client):
    """Being Race Master of a league gives no site-owner powers."""
    token = _league(master_client)
    auth.create_user("kim", "Kim", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "kim", "race_master")
    kim = _client(app, "kim")
    for path in ("/settings/errors", "/settings/change-record", "/settings/engine-scan"):
        assert kim.get(path).status_code == 403


# --------------------------------------------------------------------------- change record

def test_member_changes_are_recorded_with_before_and_after(app, master_client):
    token = _league(master_client)
    auth.create_user("kim", "Kim", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "kim", "member")
    master_client.post(f"/career/{token}/members/kim/update", data={"csrf_token": "tok", "role": "scorekeeper"})
    with storage.session(token) as conn:
        [ev] = [e for e in audit_trail.events(conn) if e["action"] == "member_update"]
    assert ev["actor"] == "devon" and ev["before"] == {"kim": "member"} and ev["after"] == {"kim": "scorekeeper"}
    page = master_client.get(f"/career/{token}/activity").get_data(as_text=True)
    assert "Change record" in page and "scorekeeper" in page


def test_settings_changes_record_values_but_never_secrets(app, master_client):
    token = _league(master_client)
    url = "https://discord.com/api/webhooks/123/very-secret-token"
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "section": "privacy",
                                                          "discord_webhook": url, "discord_results": "1"})
    with storage.session(token) as conn:
        evs = audit_trail.events(conn)
        raw = json.dumps([dict(r) for r in conn.execute("SELECT * FROM audit_events")])
    assert "very-secret-token" not in raw
    assert any(e["after"] and e["after"].get("discord_webhook") == "set" for e in evs)


def test_the_change_record_cannot_be_edited_or_deleted(app, master_client):
    token = _league(master_client)
    master_client.post(f"/career/{token}/rename", data={"csrf_token": "tok", "name": "Renamed League"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] >= 1
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE audit_events SET actor = 'someone-else'")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM audit_events")


def test_a_refused_change_leaves_no_record(app, master_client):
    token = _league(master_client)
    master_client.post(f"/career/{token}/rename", data={"csrf_token": "tok", "name": ""})    # refused: blank name
    with storage.session(token) as conn:
        assert not [e for e in audit_trail.events(conn) if e["action"] == "rename"]


def test_site_owner_actions_are_recorded_without_passwords(app, master_client):
    auth.create_user("kim", "Kim", "password1")
    master_client.post("/accounts/kim/password", data={"csrf_token": "tok", "password": "Brand-New-Pass-1",
                                                       "confirm_password": "Brand-New-Pass-1"})
    [ev] = audit_trail.site_events()
    assert ev["action"] == "account_reset" and "kim" in ev["target"] and ev["outcome"] == "done"
    with auth.accounts() as conn:
        raw = json.dumps([dict(r) for r in conn.execute("SELECT * FROM site_audit")])
        assert "Brand-New-Pass" not in raw
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM site_audit")
    assert "account_reset" in master_client.get("/settings/change-record").get_data(as_text=True)


def test_an_older_league_file_gains_an_empty_change_record(app, master_client):
    token = _league(master_client)
    path = storage.career_path(token)
    conn = sqlite3.connect(str(path))
    conn.execute("DROP TRIGGER audit_events_no_update")
    conn.execute("DROP TRIGGER audit_events_no_delete")
    conn.execute("DROP TABLE audit_events")
    conn.execute("UPDATE meta SET value = '21' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
        assert storage.get_meta(conn, "schema_version") == str(C.SCHEMA_VERSION)
    assert list(storage.backups_dir().glob(f"{token}-before-v{C.SCHEMA_VERSION}-upgrade-*"))


# --------------------------------------------------------------------------- shell, design system, preferences

def test_the_shell_has_the_five_destinations_and_manage_league(app, master_client):
    token = _league(master_client)
    page = master_client.get(f"/career/{token}/dashboard", follow_redirects=True).get_data(as_text=True)
    for title in ("Home", "Race Weekend", "Championship", "More", "Manage League", "League administration"):  # 4.0 UI
        assert f">{title}<" in page, title
    auth.create_user("sam", "Sam", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "sam", "spectator")
    spectator = _client(app, "sam").get(f"/career/{token}/dashboard", follow_redirects=True).get_data(as_text=True)
    assert ">Championship<" in spectator and "Manage League" not in spectator


def test_design_system_page_shows_every_state(app, master_client):
    page = master_client.get("/design").get_data(as_text=True)
    for kind in ("loading", "empty", "error", "offline", "locked", "denied"):
        assert f"state state-{kind}" in page
    assert app.test_client().get("/design").status_code == 302


def test_theme_and_density_are_saved_to_the_account(app, master_client):
    assert master_client.post("/account/preferences", data={"csrf_token": "tok", "theme": "light"}).get_json()["ok"]
    assert master_client.post("/account/preferences", data={"csrf_token": "tok", "density": "compact"}).get_json()["ok"]
    user = auth.get_user("devon")
    assert user["theme"] == "light" and user["density"] == "compact"
    assert '"light"' in master_client.get("/").get_data(as_text=True)          # applied on every device
    assert master_client.post("/account/preferences", data={"csrf_token": "tok", "theme": "neon"}).status_code == 400
    assert app.test_client().post("/account/preferences", data={"theme": "light"}).status_code == 302


def test_permission_denied_uses_the_denied_state(app, master_client):
    token = _league(master_client)
    auth.create_user("pat", "Pat", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "pat", "member")
    res = _client(app, "pat").get(f"/career/{token}/settings")
    assert res.status_code == 403 and "state state-denied" in res.get_data(as_text=True)


def test_version_and_changelog_era(app, master_client):
    assert C.APP_VERSION.startswith("4.0.0")
    page = master_client.get("/changelog").get_data(as_text=True)
    assert "THE NEXT GENERATION" in page and "Versions 4.0–4.x" in page and "THE DEFINITIVE RELEASE" in page
    assert page.index("THE NEXT GENERATION") < page.index("THE DEFINITIVE RELEASE")


def test_no_career_numbers_changed(app):
    """Phase 1 is foundation only: the golden seasons still match exactly."""
    from f1tracker import golden
    from pathlib import Path
    root = Path(__file__).resolve().parent / "golden"
    assert golden.dumps(golden.build(3)) == (root / "engine3_season.json").read_text()


def test_new_league_files_have_the_change_record(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"audit_events", "audit_events_no_update", "audit_events_no_delete"} <= names
    assert S.current_season_id  # league opened normally
