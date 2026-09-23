"""v1.18: submitted-round locking, race-time states, autosave safety, submission checklist, joining, accounts."""

import threading
from datetime import datetime, timedelta, timezone

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import auth, insights, roles, schema, services as S, storage, timefmt
from f1tracker import constants as C

CSS = __import__("pathlib").Path(__file__).resolve().parent.parent / "static" / "css" / "app.css"


def _league(master_client):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    res = master_client.post("/careers/new", data={"name": "V18", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"], "join_mode": "requests",
                                                   "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
    pledge_all(token)
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _add(token, username, role, driver_id=None):
    if not auth.get_user(username):
        auth.create_user(username, username.title(), "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, username, role, driver_id)


def _event(token, index=0):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))[index]


def _full(token, event_id, complete=False, **extra):
    with storage.session(token) as conn:
        rows = S.weekend_rows(conn, event_id)
        sprint = S.get_event(conn, event_id)["is_sprint"]
    results = [{"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1,
                "status_override": "Auto", "sprint_position": (i + 1) if sprint else None, "sprint_status_override": "Auto",
                "fastest_lap": i == 0, "driver_of_day": i == 1, "notes": ""} for i, r in enumerate(rows)]
    return {"results": results, "mark_complete": complete, "ai_difficulty": 90, "event_notes": "Good race", **extra}


def _post(client, token, event_id, body):
    return client.post(f"/api/career/{token}/weekend/{event_id}", json=body, headers={"X-CSRF-Token": "tok"})


# --------------------------------------------------------------------------- submitted-round locking (unchanged)

def test_scorekeeper_edits_open_round_but_never_a_submitted_one(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    kim = _client(app, "kim")
    ev = _event(token)
    assert _post(kim, token, ev["id"], _full(token, ev["id"])).get_json()["ok"]            # open round: fine
    res = _post(kim, token, ev["id"], _full(token, ev["id"], complete=True))
    assert res.get_json()["ok"] and res.get_json()["complete"]
    # Locked now, whatever is sent: a normal save, a stale revision from an offline queue, or a direct call.
    for body in (_full(token, ev["id"]), _full(token, ev["id"], base_revision=0), {"results": [], "mark_complete": False}):
        r = _post(kim, token, ev["id"], body)
        assert r.status_code == 403 and r.get_json()["locked"] and "Race Master" in r.get_json()["error"]
    assert kim.post(f"/career/{token}/weekend/{ev['id']}/reopen", data={"csrf_token": "tok"}).status_code == 403
    page = kim.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Submitted and locked" in page and "Only the Race Master can reopen" in page
    # The state endpoint tells a recovering browser it's locked.
    assert kim.get(f"/api/career/{token}/weekend/{ev['id']}/state").get_json()["locked"] is True


def test_race_master_reopens_and_corrects_without_repeating_side_effects(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    kim = _client(app, "kim")
    ev = _event(token)
    _post(kim, token, ev["id"], _full(token, ev["id"], complete=True))
    with storage.session(token) as conn:
        headlines = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    # The Race Master can correct in place...
    assert _post(master_client, token, ev["id"], _full(token, ev["id"])).get_json()["ok"]
    # ...or reopen it for the Scorekeeper, who resubmits.
    master_client.post(f"/career/{token}/weekend/{ev['id']}/reopen", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_IN_PROGRESS
    assert _post(kim, token, ev["id"], _full(token, ev["id"])).get_json()["ok"]
    assert _post(kim, token, ev["id"], _full(token, ev["id"], complete=True)).get_json()["complete"]
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == headlines  # no duplicate headlines
    assert _post(kim, token, ev["id"], _full(token, ev["id"])).status_code == 403


def test_spectators_and_members_cannot_save_results(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "sam", "spectator")
    ev = _event(token)
    for who in ("sam", "ana"):
        assert _post(_client(app, who), token, ev["id"], _full(token, ev["id"])).status_code == 403
        assert _client(app, who).get(f"/api/career/{token}/weekend/{ev['id']}/checklist").status_code == 403


# --------------------------------------------------------------------------- autosave safety

def test_stale_revision_is_refused_with_the_server_values(app, master_client):
    token, a, b = _league(master_client)
    ev = _event(token)
    first = _post(master_client, token, ev["id"], _full(token, ev["id"])).get_json()
    rev = first["revision"]
    newer = _full(token, ev["id"], base_revision=rev)
    newer["results"][0]["qualifying_position"] = 5
    newer["results"][4]["qualifying_position"] = 1
    assert _post(master_client, token, ev["id"], newer).get_json()["revision"] == rev + 1
    offline = _full(token, ev["id"], base_revision=rev)        # queued before the newer save
    offline["results"][0]["notes"] = "typed offline"
    res = _post(master_client, token, ev["id"], offline)
    body = res.get_json()
    assert res.status_code == 409 and body["conflict"]
    first_driver = str(newer["results"][0]["driver_id"])
    assert body["server"]["results"][first_driver]["qualifying_position"] == 5 and body["server"]["revision"] == rev + 1
    with storage.session(token) as conn:  # nothing was overwritten
        assert conn.execute("SELECT notes FROM results WHERE event_id = ? AND driver_id = ?",
                            (ev["id"], int(first_driver))).fetchone()[0] == ""
    offline["base_revision"] = body["server"]["revision"]      # after the person resolves the conflict
    assert _post(master_client, token, ev["id"], offline).get_json()["ok"]


def test_saves_without_a_revision_still_work(app, master_client):
    token, a, b = _league(master_client)
    ev = _event(token)
    assert _post(master_client, token, ev["id"], _full(token, ev["id"])).get_json()["ok"]


# --------------------------------------------------------------------------- submission checklist

def test_checklist_blocking_errors_stop_submission(app, master_client):
    token, a, b = _league(master_client)
    ev = _event(token)
    body = _full(token, ev["id"])
    body["results"][3]["race_position"] = None                     # a driver with no GP result
    body["results"][5]["status_override"] = "DNS"                  # DNS with a finishing position
    body["results"][5]["race_position"] = 6
    body["results"][1]["qualifying_position"] = None               # half-entered qualifying
    _post(master_client, token, ev["id"], body)
    check = master_client.get(f"/api/career/{token}/weekend/{ev['id']}/checklist").get_json()
    text = " ".join(check["blocking"])
    assert "Grand Prix result missing" in text and "DNS but has a Grand Prix position" in text and "Qualifying position missing" in text
    body["mark_complete"] = True
    res = _post(master_client, token, ev["id"], body)
    assert res.status_code in (400, 422)
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] != C.EVENT_COMPLETE


def test_checklist_warnings_can_be_accepted_and_summary_is_complete(app, master_client):
    token, a, b = _league(master_client)
    ev = _event(token)
    body = _full(token, ev["id"], ai_difficulty=None, ai_untracked=True, event_notes="")
    for r in body["results"]:
        r["fastest_lap"] = r["driver_of_day"] = False
    _post(master_client, token, ev["id"], body)
    check = master_client.get(f"/api/career/{token}/weekend/{ev['id']}/checklist").get_json()
    assert check["blocking"] == []
    joined = " ".join(check["warnings"])
    assert "Fastest Lap" in joined and "Driver of the Day" in joined and "deliberately not tracked" in joined and "notes" in joined
    s = check["summary"]
    assert s["winner"] and len(s["podium"]) == 3 and s["pole"] and s["round"] == ev["round_number"]
    assert {p["name"] for p in s["players"]} == {"Ana Silva", "Ben Okafor"}
    res = _post(master_client, token, ev["id"], {**body, "mark_complete": True}).get_json()
    assert res["ok"] and res["complete"] and res["summary_url"].endswith(f"/weekend/{ev['id']}/summary")


def test_sprint_weekend_needs_sprint_results(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        ev = next(e for e in S.events(conn, S.current_season_id(conn)) if e["is_sprint"])
    body = _full(token, ev["id"])
    for r in body["results"]:
        r["sprint_position"] = None
    _post(master_client, token, ev["id"], body)
    check = master_client.get(f"/api/career/{token}/weekend/{ev['id']}/checklist").get_json()
    assert any("Sprint result missing" in b for b in check["blocking"])


def test_successful_submission_locks_and_shows_summary(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    kim = _client(app, "kim")
    ev = _event(token)
    assert _post(kim, token, ev["id"], _full(token, ev["id"], complete=True)).get_json()["complete"]
    page = kim.get(f"/career/{token}/weekend/{ev['id']}/summary?submitted=1").get_data(as_text=True)
    assert "Results submitted" in page and "recalculated" in page
    with storage.session(token) as conn:
        assert S.driver_standings(conn, S.current_season_id(conn))[0]["points"] >= 25
        assert S.get_event(conn, ev["id"])["submitted_at"]


# --------------------------------------------------------------------------- race-time states

def test_race_time_status_transitions():
    start = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    iso = start.isoformat()
    at = lambda **d: start + timedelta(**d)
    assert timefmt.race_status(iso, "Not Run", 180, at(days=-9)) == ("scheduled", "Scheduled")
    assert timefmt.race_status(iso, "Not Run", 180, at(hours=-2, minutes=-15)) == ("upcoming", "Starts in 2h 15m")
    assert timefmt.race_status(iso, "Not Run", 180, at(minutes=-10)) == ("soon", "Starting soon")
    assert timefmt.race_status(iso, "Not Run", 180, at(minutes=5)) == ("live", "In progress")
    assert timefmt.race_status(iso, "In Progress", 180, at(hours=2, minutes=59))[1] == "In progress"
    assert timefmt.race_status(iso, "In Progress", 180, at(hours=3, minutes=1)) == ("pending", "Results pending")
    assert timefmt.race_status(iso, "Not Run", 60, at(minutes=61))[0] == "pending"
    assert timefmt.race_status(iso, "Not Run", 180, at(minutes=5), postponed=True) == ("postponed", "Postponed")
    assert timefmt.race_status(iso, "Complete", 180, at(hours=-5)) == ("complete", "Completed")
    assert timefmt.race_status(None, "Not Run") == ("unscheduled", "Not scheduled")
    assert timefmt.zone_label(iso, "America/New_York") == "EDT"


def test_race_window_setting_and_status_on_pages(app, master_client):
    token, a, b = _league(master_client)
    ev = _event(token)
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    with storage.session(token) as conn:
        conn.execute("UPDATE events SET race_at = ? WHERE id = ?", (past + ":00+00:00", ev["id"]))
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "In progress" in page
    master_client.post(f"/career/{token}/settings", data={"race_window": "60", "csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Results pending" in page
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_NOT_RUN  # never completed by time


# --------------------------------------------------------------------------- dashboard, profile, incidents, grid

def test_dashboard_completion_statistics(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        for ev in evs[:3]:
            run_event(conn, ev, difficulty=80 + ev["round_number"])
        p = insights.season_progress(conn, sid)
    assert p["completed"] == 3 and p["total"] == len(evs) and p["pct"] == round(3 / len(evs) * 100)
    assert p["sprints_done"] == sum(1 for e in evs[:3] if e["is_sprint"])
    assert p["wdc"] and p["wcc"] and p["avg_ai"] == pytest.approx(sum(80 + e["round_number"] for e in evs[:3]) / 3, abs=0.05)
    assert p["milestone"]["label"] == "Five rounds completed" and p["milestone"]["to_go"] == 2
    _add(token, "sam", "spectator")
    page = _client(app, "sam").get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "season-facts" in page and "WDC</abbr> leader" in page and "Projected finish" in page and "Current round" in page


def test_profile_stat_grid_is_balanced(master_client):
    token, a, b = _league(master_client)
    page = master_client.get(f"/career/{token}/driver/{a}").get_data(as_text=True)
    grid = page.split('class="stat-grid profile-stats"')[1].split("\n</div>")[0]
    assert grid.count('class="stat card"') == 9
    css = open(CSS).read()
    for rule in ("(100% - 4 * .8rem) / 5", "(100% - 2 * .8rem) / 3", "(100% - .8rem) / 2", "flex-basis: 100%"):
        assert rule in css


@pytest.mark.parametrize("who,expected", [
    ("ana", "Report an incident from the relevant race-weekend page."),
    ("kim", "Only assigned drivers can submit incident reports."),
    ("sam", "Incident reports and rulings will appear here."),
    ("david", "Submitted reports will appear here for you to review and rule on."),
])
def test_incident_empty_state_is_role_aware(app, master_client, who, expected):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    _add(token, "sam", "spectator")
    client = master_client if who == "david" else _client(app, who)
    page = client.get(f"/career/{token}/incidents").get_data(as_text=True)
    assert "No incidents reported" in page and expected in page and "#incidents" in page
    ev = _event(token)
    for outsider in ("kim", "sam"):
        r = _client(app, outsider).post(f"/career/{token}/weekend/{ev['id']}/incident",
                                        data={"accused_id": str(a), "description": "x", "csrf_token": "tok"})
        assert r.status_code == 403


def test_grid_names_are_neutral_and_players_highlighted(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "sam", "spectator")
    page = _client(app, "sam").get(f"/career/{token}/grid").get_data(as_text=True)
    main = page.split("<main", 1)[1]
    assert 'class="driver-link "' in main or 'class="driver-link"' in main     # AI names: neutral link class
    assert 'driver-link is-player' in main and "player-badge" in main
    css = open(CSS).read()
    assert "a.driver-link:not(.is-player) { color: var(--text); }" in css


# --------------------------------------------------------------------------- accounts

def test_results_email_needs_an_address(app, master_client):
    auth.create_user("pat", "Pat", "password1")
    pat = _client(app, "pat")
    pat.post("/account/email", data={"email": "", "email_results": "1", "csrf_token": "tok"})
    assert not auth.get_user("pat")["email_results"]
    page = pat.get("/accounts").get_data(as_text=True)
    assert "Add an email address to enable race-result emails." in page
    assert 'name="email_results" value="1"  disabled' in page or ('name="email_results"' in page and "disabled aria-describedby" in page)
    res = pat.post("/account/email", data={"email": "not-an-email", "email_results": "1", "csrf_token": "tok"}, follow_redirects=True)
    assert "doesn&#39;t look right" in res.get_data(as_text=True) or "look right" in res.get_data(as_text=True)
    assert auth.get_user("pat")["email"] is None
    pat.post("/account/email", data={"email": "pat@example.com", "email_results": "1", "csrf_token": "tok"})
    u = auth.get_user("pat")
    assert u["email"] == "pat@example.com" and u["email_results"]
    # Other people never see it.
    auth.create_user("other", "Other", "password1")
    assert "pat@example.com" not in _client(app, "other").get("/accounts").get_data(as_text=True)


def test_existing_email_preferences_migrate_safely():
    auth.create_user("valid", "Valid", "password1", email="v@example.com")
    auth.create_user("blank", "Blank", "password1")
    with auth.accounts() as conn:
        conn.execute("UPDATE users SET email_results = 1")
    with auth.accounts() as conn:   # opening the accounts database runs the check again
        pass
    assert auth.get_user("valid")["email_results"] == 1
    assert auth.get_user("blank")["email_results"] == 0


def test_password_change_needs_current_and_matching_passwords(app, master_client):
    auth.create_user("pat", "Pat", "password1")
    pat = _client(app, "pat")
    for form, message in (({"current_password": "wrong", "password": "newpass1", "confirm_password": "newpass1"}, "current password is wrong"),
                          ({"current_password": "password1", "password": "newpass1", "confirm_password": "newpass2"}, "don&#39;t match"),
                          ({"current_password": "password1", "password": "abc", "confirm_password": "abc"}, "at least 6")):
        page = pat.post("/account/password", data={**form, "csrf_token": "tok"}, follow_redirects=True).get_data(as_text=True)
        assert message in page
        assert auth.verify("pat", "password1")
    page = pat.post("/account/password", data={"current_password": "password1", "password": "newpass1",
                                               "confirm_password": "newpass1", "csrf_token": "tok"}, follow_redirects=True)
    assert "Password changed" in page.get_data(as_text=True) and auth.verify("pat", "newpass1")
    accounts = pat.get("/accounts").get_data(as_text=True)
    assert "Confirm new password" in accounts and "data-pw-toggle" in accounts and "Caps Lock" in accounts


# --------------------------------------------------------------------------- joining

def test_join_modes(app, master_client):
    token, a, b = _league(master_client)
    auth.create_user("newbie", "Newbie", "password1")
    newbie = _client(app, "newbie")
    lib = newbie.get("/").get_data(as_text=True)
    assert "V18" in lib and "Join requests enabled" in lib and "Ana Silva" not in lib   # nothing private shown
    # Invite only: no requests, but an invitation works.
    master_client.post(f"/career/{token}/members/settings", data={"join_mode": "invite", "csrf_token": "tok"})
    assert "V18" not in newbie.get("/").get_data(as_text=True)
    newbie.post(f"/career/{token}/join", data={"role": "spectator", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM join_requests WHERE username = 'newbie'").fetchone()[0] == 0
    master_client.post(f"/career/{token}/members/invite", data={"username": "newbie", "role": "spectator", "csrf_token": "tok"})
    assert "You've been invited" in newbie.get("/").get_data(as_text=True)
    # Closed: the invitation can't be accepted and nobody can ask.
    master_client.post(f"/career/{token}/members/settings", data={"join_mode": "closed", "csrf_token": "tok"})
    newbie.post(f"/career/{token}/invitation", data={"decision": "accept", "csrf_token": "tok"})
    assert newbie.get(f"/career/{token}/dashboard").status_code == 403
    assert master_client.post(f"/career/{token}/members/invite", data={"username": "ana", "role": "member",
                                                                        "csrf_token": "tok"}, follow_redirects=True).status_code == 200
    # Back to invite only: now it can be accepted, as the role it was sent with.
    master_client.post(f"/career/{token}/members/settings", data={"join_mode": "invite", "csrf_token": "tok"})
    newbie.post(f"/career/{token}/invitation", data={"decision": "accept", "csrf_token": "tok"})
    assert newbie.get(f"/career/{token}/dashboard").status_code == 200
    with storage.session(token) as conn:
        assert conn.execute("SELECT role FROM career_members WHERE username = 'newbie'").fetchone()[0] == "spectator"
        assert storage.join_mode(conn) == "invite"
    # Existing members are never affected by the mode.
    master_client.post(f"/career/{token}/members/settings", data={"join_mode": "closed", "csrf_token": "tok"})
    assert _client(app, "ana").get(f"/career/{token}/dashboard").status_code == 200
    assert "Closed to new members" in master_client.get("/").get_data(as_text=True)


def test_join_mode_migrates_from_open_to_join(career):
    with storage.session(career) as conn:
        conn.execute("DELETE FROM meta WHERE key = 'join_mode'")
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'join_open'")
        assert storage.join_mode(conn) == "requests"
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'join_open'")
        assert storage.join_mode(conn) == "invite"


# --------------------------------------------------------------------------- existing saves

def test_v117_save_upgrades_without_data_loss(career):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        run_event(conn, evs[0])
        before = [(r["driver_id"], r["points"], r["form"], r["reputation"]) for r in S.driver_standings(conn, sid)]
        conn.execute("ALTER TABLE events DROP COLUMN revision")
        conn.execute("ALTER TABLE events DROP COLUMN submitted_at")
        conn.execute("DROP TABLE invitations")
        conn.execute("DELETE FROM meta WHERE key = 'join_mode'")
        conn.execute("UPDATE meta SET value = '14' WHERE key = 'schema_version'")
        schema.migrate(conn)
        assert [(r["driver_id"], r["points"], r["form"], r["reputation"]) for r in S.driver_standings(conn, sid)] == before
        assert S.get_event(conn, evs[0]["id"])["submitted_at"] == "before-v1.18"   # stays locked, no repeat news
        assert S.get_event(conn, evs[1]["id"])["submitted_at"] is None
        assert storage.join_mode(conn) == "requests"
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(C.SCHEMA_VERSION)


# --------------------------------------------------------------------------- the browser side (skipped without Playwright)

@pytest.fixture
def live_server(app):
    try:
        from werkzeug.serving import make_server
    except ImportError:  # pragma: no cover
        pytest.skip("werkzeug missing")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _browser():
    sync = pytest.importorskip("playwright.sync_api")
    import os
    path = "/opt/pw-browsers/chromium"
    pw = sync.sync_playwright().start()
    try:
        browser = pw.chromium.launch(executable_path=path) if os.path.exists(path) else pw.chromium.launch()
    except Exception as exc:  # no browser available here
        pw.stop()
        pytest.skip(f"no browser: {exc}")
    return pw, browser


def test_browser_offline_queue_recovery_conflict_and_lock(app, master_client, live_server):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    ev = _event(token)
    pw, browser = _browser()
    try:
        ctx = browser.new_context()
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_server + "/login")
        page.fill("input[name=username]", "kim"); page.fill("input[name=password]", "password1")
        page.press("input[name=password]", "Enter"); page.wait_for_load_state()
        url = f"{live_server}/career/{token}/weekend/{ev['id']}"
        q = lambda p: p.locator('input[data-field="qualifying_position"]').first
        page.goto(url)
        # Autosave failure: offline edits wait, are kept locally, and save when the connection returns.
        ctx.set_offline(True)
        q(page).fill("4")
        page.wait_for_timeout(1300)
        assert "Offline" in page.locator("#save-state").inner_text()
        assert page.evaluate("Object.keys(localStorage).some(k => k.startsWith('f1-recovery:kim|'))")
        ctx.set_offline(False)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_timeout(1500)
        assert "Saved" in page.locator("#save-state").inner_text()
        assert not page.evaluate("Object.keys(localStorage).some(k => k.startsWith('f1-recovery'))")
        # Interrupted entry is restored on return.
        ctx.set_offline(True); q(page).fill("6"); page.wait_for_timeout(1300); page.close(); ctx.set_offline(False)
        page = ctx.new_page(); page.goto(url); page.wait_for_timeout(2000)
        assert q(page).input_value() == "6" and "Restored" in page.locator("#recovery-banner").inner_text()
        # Conflict: another save lands first; both values are shown and the person chooses.
        other = ctx.new_page(); other.goto(url); other.wait_for_timeout(600)
        q(other).fill("8"); other.wait_for_timeout(1500)
        q(page).fill("9"); page.wait_for_timeout(2000)
        assert page.evaluate("document.getElementById('conflict-dialog').open")
        listing = page.locator("#conflict-list").inner_text()
        assert "P9" in listing and "P8" in listing
        page.click("#conflict-all-server"); page.click("#conflict-apply"); page.wait_for_timeout(1500)
        assert q(page).input_value() == "8"
        # Queued edits can't touch a round that was submitted meanwhile.
        ctx.set_offline(True); q(page).fill("2"); page.wait_for_timeout(1300)
        _post(master_client, token, ev["id"], _full(token, ev["id"], complete=True))
        ctx.set_offline(False); page.evaluate("window.dispatchEvent(new Event('online'))"); page.wait_for_timeout(1500)
        assert "Locked" in page.locator("#save-state").inner_text()
        assert "Race Master" in page.locator("#recovery-banner").inner_text()
        with storage.session(token) as conn:
            first = S.weekend_rows(conn, ev["id"])[0]   # the first row on the page
        assert first["qualifying_position"] == 1        # the Race Master's result stands; the queued "2" never landed
        assert not errors
    finally:
        browser.close()
        pw.stop()
