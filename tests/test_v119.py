"""v1.19: difficulty fix, completed-round corrections, final review, race states, season card, activity log,
one join setting, password forms, sidebar, confirmations, free in-browser screenshot import, regression pass."""

import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import auth, community, insights, relations, roles, schema, services as S, storage, timefmt
from f1tracker import constants as C

ROOT = Path(__file__).resolve().parent.parent


def _league(master_client, extra_players=()):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    names = ["Ana Silva", "Ben Okafor", *extra_players]
    logins = ["ana", "ben", *["" for _ in extra_players]]
    res = master_client.post("/careers/new", data={"name": "V19", "year": "2026", "player_name": names,
                                                   "player_login": logins, "join_mode": "requests", "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        ids = players(conn)
        S.place_players(conn, sid, {ids[0]: (cad, 1), ids[1]: (cad, 2)})
    pledge_all(token)
    return token, ids


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _add(token, username, role, driver_id=None):
    if not auth.get_user(username):
        auth.create_user(username, username.title(), "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, username, role, driver_id)


def _events(token):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))


def _order_with(conn, event, first=None, last=None):
    ids = [r["driver_id"] for r in S.weekend_rows(conn, event["id"])]
    if first:
        ids = [first] + [d for d in ids if d != first]
    if last:
        ids = [d for d in ids if d != last] + [last]
    return ids


def _full(token, event_id, **extra):
    with storage.session(token) as conn:
        rows = S.weekend_rows(conn, event_id)
        sprint = S.get_event(conn, event_id)["is_sprint"]
    res = [{"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1, "status_override": "Auto",
            "sprint_position": (i + 1) if sprint else None, "sprint_status_override": "Auto",
            "fastest_lap": i == 0, "driver_of_day": i == 1, "notes": ""} for i, r in enumerate(rows)]
    return {"results": res, "mark_complete": False, "ai_difficulty": 80, "event_notes": "ok", **extra}


def _post(client, token, event_id, body):
    return client.post(f"/api/career/{token}/weekend/{event_id}", json=body, headers={"X-CSRF-Token": "tok"})


# --------------------------------------------------------------------------- 1. AI difficulty on completed rounds

def test_completed_round_with_tracked_difficulty_is_recognised(master_client):
    token, (a, b) = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, ev, order=_order_with(conn, ev, first=a), difficulty=80)
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Track the AI difficulty on a completed round" not in page
    assert "1 of 3 usable rounds at AI 80" in page and "Waiting for a consistent pattern" in page
    assert "Recommended for next round" in page
    # The next round's page and the Control Room agree.
    nxt = master_client.get(f"/career/{token}/weekend/{_events(token)[1]['id']}").get_data(as_text=True)
    assert "1 of 3 usable rounds at AI 80" in nxt
    assert "1 of 3 usable rounds at AI 80" in master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)


def test_tracked_but_unfinished_round_never_asks_to_be_tracked(master_client):
    token, (a, b) = _league(master_client)
    ev = _events(token)[0]
    _post(master_client, token, ev["id"], _full(token, ev["id"], ai_difficulty=85))
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Track the AI difficulty" not in page and "AI 85 is recorded for this round" in page


def test_untracked_and_dnf_rounds(db):
    sid = S.current_season_id(db)
    a, b = players(db)
    evs = S.events(db, sid)
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(db, sid, {a: (cad, 1), b: (cad, 2)})
    run_event(db, evs[0], difficulty=None)                                   # "Don't track this round"
    run_event(db, evs[1], difficulty=80, overrides={a: "DNF", b: "DNF"})      # tracked, but nobody finished
    rec = S.difficulty_recommendation(db, (2026, evs[2]["round_number"]))
    assert rec["history_rounds"] == 1 and rec["current"] == 80 and rec["sample"] == [] and rec["unusable"] == 1
    assert "0 of 3 usable rounds at AI 80" in rec["reason"] and "didn't count" in rec["reason"]


def test_three_rounds_and_one_offs_stay_gradual(db):
    sid = S.current_season_id(db)
    a, b = players(db)
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(db, sid, {a: (cad, 1), b: (cad, 2)})
    evs = S.events(db, sid)
    for ev in evs[:3]:   # players win every time at AI 80
        run_event(db, ev, order=_order_with(db, ev, first=a), difficulty=80)
    rec = S.difficulty_recommendation(db, (2026, evs[3]["round_number"]))
    assert len(rec["sample"]) == 3 and rec["recommended"] in (80, 81) and abs(rec["recommended"] - 80) <= 1
    # One unusually bad round doesn't swing it.
    run_event(db, evs[3], order=_order_with(db, evs[3], last=a), difficulty=80)
    rec2 = S.difficulty_recommendation(db, (2026, evs[4]["round_number"]))
    assert abs(rec2["recommended"] - 80) <= 1 and rec2["note"]


def test_history_spans_seasons(db):
    sid = S.current_season_id(db)
    a, b = players(db)
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(db, sid, {a: (cad, 1), b: (cad, 2)})
    for ev in S.events(db, sid)[:2]:
        run_event(db, ev, difficulty=78)
    new_sid = S.create_next_season(db, sid, 2027)
    run_event(db, S.events(db, new_sid)[0], difficulty=78)
    rec = S.difficulty_recommendation(db, (2027, 2))
    assert rec["history_rounds"] == 3 and {h["year"] for h in S.difficulty_history(db, (2027, 2))} == {2026, 2027}


# --------------------------------------------------------------------------- 2-3. completed-round action and final review

def test_completed_round_actions_by_role(app, master_client):
    token, (a, b) = _league(master_client)
    _add(token, "kim", "scorekeeper")
    kim = _client(app, "kim")
    ev = _events(token)[0]
    open_page = kim.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Review &amp; complete weekend" in open_page
    assert _post(kim, token, ev["id"], _full(token, ev["id"], mark_complete=True)).get_json()["complete"]
    rm = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "✓ Weekend complete" in rm and "Save corrections" in rm and "Mark weekend complete" not in rm
    assert "Recalculated from the corrected results" in rm
    sk = kim.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Submitted and locked" in sk and 'id="save-corrections"' not in sk and 'id="mark-complete"' not in sk
    fixed = _full(token, ev["id"])
    fixed["results"][0]["notes"] = "corrected"
    assert _post(master_client, token, ev["id"], fixed).get_json()["complete"]          # stays complete
    assert _post(kim, token, ev["id"], fixed).status_code == 403                          # still locked for them


def test_review_blocks_gaps_and_missing_difficulty_and_lists_players(master_client):
    token, (a, b) = _league(master_client)
    ev = _events(token)[0]
    body = _full(token, ev["id"], ai_difficulty=None)
    for r in body["results"]:
        if r["race_position"] == 5:
            r["race_position"] = 23 if len(body["results"]) >= 23 else None
            r["status_override"] = "Auto"
    target = next(r for r in body["results"] if r["driver_id"] == a)
    target["race_position"], target["status_override"] = None, "Auto"
    _post(master_client, token, ev["id"], body)
    check = master_client.get(f"/api/career/{token}/weekend/{ev['id']}/checklist").get_json()
    text = " ".join(check["blocking"])
    assert "skip P5" in text and "AI difficulty" in text
    assert any(p["name"] == "Ana Silva" and "Grand Prix result" in p["missing"] for p in check["player_issues"])
    assert "locks it for Scorekeepers" in check["lock_notice"]
    res = _post(master_client, token, ev["id"], {**body, "mark_complete": True})
    assert res.status_code in (400, 422)
    # Fixed, with "Don't track this round" chosen deliberately: it goes through.
    good = _full(token, ev["id"], ai_difficulty=None, ai_untracked=True, mark_complete=True)
    assert _post(master_client, token, ev["id"], good).get_json()["complete"]
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["ai_untracked"] == 1


# --------------------------------------------------------------------------- 4-5. race states and season card

def test_postponed_round(master_client):
    token, _ = _league(master_client)
    ev = _events(token)[0]
    master_client.post(f"/career/{token}/weekend/{ev['id']}/time",
                       data={"race_at": "2030-03-01T20:00", "postponed": "1", "csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Postponed" in page and 'data-postponed="1"' in page
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_NOT_RUN


def test_season_card_summary(master_client):
    token, _ = _league(master_client)
    evs = _events(token)
    with storage.session(token) as conn:
        for ev in evs[:2]:
            run_event(conn, ev)
        for i, ev in enumerate(evs[2:]):
            conn.execute("UPDATE events SET race_at = ? WHERE id = ?", (f"2026-{4 + i // 3:02d}-{1 + (i % 3) * 7:02d}T18:00:00+00:00", ev["id"]))
        p = insights.season_progress(conn, S.current_season_id(conn))
    assert p["completed"] == 2 and p["remaining"] == len(evs) - 2 and p["current"]["round_number"] == 3
    assert p["sprints_left"] == sum(1 for e in evs[2:] if e["is_sprint"])
    assert p["finish_at"] == max(e for e in [f"2026-{4 + i // 3:02d}-{1 + (i % 3) * 7:02d}T18:00:00+00:00" for i in range(len(evs) - 2)])
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    for label in ("Completed", "Remaining", "Current round", "Sprint weekends", "Next event", "Projected finish"):
        assert label in page


# --------------------------------------------------------------------------- 6-7. activity log and the one join setting

def test_activity_log_is_readable_and_private(app, master_client):
    token, (a, b) = _league(master_client)
    ev = _events(token)[1]
    master_client.post(f"/career/{token}/weekend/{ev['id']}/time", data={"race_at": "2026-09-23T11:30", "csrf_token": "tok"})
    master_client.post(f"/career/{token}/settings", data={"join_mode": "invite", "timezone": "UTC", "csrf_token": "tok",
                                                           "discord_webhook": "https://discord.com/api/webhooks/123/secret-token"})
    _add(token, "chat", "member")
    master_client.post(f"/career/{token}/members/chat/update", data={"role": "scorekeeper", "csrf_token": "tok"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        conn.execute("UPDATE team_relations SET pledged = 0 WHERE driver_id = ?", (a,))
    _client(app, "ana").post(f"/career/{token}/pledge", data={"growth": "2", "csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/activity").get_data(as_text=True)
    assert f"scheduled Round {ev['round_number']} — {ev['name']} (2026) for Wed, Sep 23 at 11:30 AM UTC" in page
    assert "changed joining from Join requests enabled to Invite only" in page and "connected a Discord channel" in page
    assert "changed Chat&#39;s league role from Member to Scorekeeper" in page or "changed Chat's league role from Member to Scorekeeper" in page
    assert "selected the Strong growth pledge" in page
    assert "event id" not in page and "secret-token" not in page and "discord.com/api" not in page
    assert f'href="/career/{token}/weekend/{ev["id"]}"' in page


def test_members_page_shows_join_state_but_settings_owns_it(master_client):
    token, _ = _league(master_client)
    page = master_client.get(f"/career/{token}/members").get_data(as_text=True)
    assert "Join requests are currently enabled" in page and "Manage this in League Settings" in page
    assert 'name="join_mode"' not in page
    assert 'name="join_mode"' in master_client.get(f"/career/{token}/settings").get_data(as_text=True)


# --------------------------------------------------------------------------- 8-11. passwords, sidebar, confirmations

def test_password_forms_confirm_and_match(app, master_client):
    page = master_client.get("/accounts").get_data(as_text=True)
    assert page.count("data-password-form") >= 3 and "Confirm password" in page and "Caps Lock" in page
    res = master_client.post("/accounts/new", data={"username": "newp", "display_name": "N", "password": "abcdef",
                                                     "confirm_password": "abcdeX", "role": "driver", "csrf_token": "tok"},
                             follow_redirects=True).get_data(as_text=True)
    assert "match" in res and auth.get_user("newp") is None
    master_client.post("/accounts/new", data={"username": "newp", "display_name": "N", "password": "abcdef",
                                              "confirm_password": "abcdef", "role": "driver", "csrf_token": "tok"})
    assert auth.verify("newp", "abcdef")
    master_client.post("/accounts/newp/password", data={"password": "zzzzzz", "confirm_password": "yyyyyy", "csrf_token": "tok"})
    assert auth.verify("newp", "abcdef")
    master_client.post("/accounts/newp/password", data={"password": "zzzzzz", "confirm_password": "zzzzzz", "csrf_token": "tok"})
    assert auth.verify("newp", "zzzzzz")


def test_race_master_sidebar_is_collapsible_for_race_masters_only(app, master_client):
    token, _ = _league(master_client)
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert 'id="nav-admin-toggle"' in page and 'aria-expanded="true"' in page and 'aria-controls="nav-admin-items"' in page
    assert 'id="nav-admin-toggle"' not in _client(app, "ana").get(f"/career/{token}/dashboard").get_data(as_text=True)


def test_high_impact_actions_explain_themselves(master_client):
    token, (a, b) = _league(master_client)
    market = master_client.get(f"/career/{token}/market").get_data(as_text=True)
    assert market.count("data-confirm") >= 1 and "Open a transfer window" in market
    paddock = master_client.get(f"/career/{token}/paddock").get_data(as_text=True)
    assert "Recalculate Reputation history?" in paddock
    assert paddock.count('<dialog id="del-driver"') == 1 and "del-driver-{{" not in paddock
    assert len(re.findall(r'<dialog id="del-driver-\d+"', paddock)) == 0 and "data-delete-driver" in paddock
    members = master_client.get(f"/career/{token}/members").get_data(as_text=True)
    assert "They lose access to this league straight away" in members
    dash = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert 'id="confirm-dialog"' in dash


def test_deleting_results_needs_the_driver_name(master_client):
    token, (a, b) = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
        victim = next(r["driver_id"] for r in S.weekend_rows(conn, ev["id"]) if not r["driver"]["is_player"])
        name = S.driver_map(conn)[victim]["name"]
    master_client.post(f"/career/{token}/paddock/driver/{victim}/delete",
                       data={"force": "1", "confirm_name": "wrong", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert victim in S.driver_map(conn)
    master_client.post(f"/career/{token}/paddock/driver/{victim}/delete",
                       data={"force": "1", "confirm_name": name, "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert victim not in S.driver_map(conn)


# --------------------------------------------------------------------------- 13. player highlighting (more than two)

def test_every_human_driver_is_highlighted_everywhere(app, master_client):
    token, ids = _league(master_client, extra_players=("Cleo Park",))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        mcl = conn.execute("SELECT id FROM teams WHERE name = 'McLaren'").fetchone()["id"]
        S.place_players(conn, sid, {ids[2]: (mcl, 1)})
        ev = S.events(conn, sid)[0]
        run_event(conn, ev, difficulty=80)
        colors = {d: S.driver_map(conn)[d]["player_color"] for d in ids}
    assert len(set(colors.values())) == 3
    for path in ("drivers", "teams", "grid", f"team/{mcl}", f"weekend/{ev['id']}", f"weekend/{ev['id']}/summary",
                 "contracts", f"driver/{ids[2]}", "dashboard"):
        page = master_client.get(f"/career/{token}/{path}").get_data(as_text=True)
        assert colors[ids[2]] in page, path
    # AI drivers stay neutral: no player colour on them.
    assert "a.driver-link:not(.is-player) { color: var(--text); }" in (ROOT / "static/css/app.css").read_text()


# --------------------------------------------------------------------------- 15. regression and permissions

def test_sprint_and_grand_prix_stay_independent(db):
    sid = S.current_season_id(db)
    ev = next(e for e in S.events(db, sid) if e["is_sprint"])
    ids = [r["driver_id"] for r in S.weekend_rows(db, ev["id"])]
    run_event(db, ev, sprint_overrides={ids[0]: "DNF"})               # Sprint DNF, GP win
    table = {r["driver_id"]: r for r in S.driver_standings(db, sid)}
    assert table[ids[0]]["points"] == C.GP_POINTS[1]
    before = table[ids[1]]["points"]
    ev2 = next(e for e in S.events(db, sid) if e["is_sprint"] and e["id"] != ev["id"])
    run_event(db, ev2, overrides={ids[1]: "DNF"})                      # GP DNF keeps Sprint points (P2 in the Sprint)
    table = {r["driver_id"]: r for r in S.driver_standings(db, sid)}
    assert table[ids[1]]["points"] - before == C.SPRINT_POINTS[2]


def test_members_and_spectators_cannot_enter_results(app, master_client):
    token, (a, b) = _league(master_client)
    _add(token, "sam", "spectator")
    ev = _events(token)[0]
    for who in ("ana", "sam"):
        assert _post(_client(app, who), token, ev["id"], _full(token, ev["id"])).status_code == 403
    assert _client(app, "sam").post(f"/career/{token}/weekend/{ev['id']}/time",
                                    data={"race_at": "", "csrf_token": "tok"}).status_code == 403


def test_returning_and_replaced_drivers_keep_their_history(db):
    sid = S.current_season_id(db)
    a, b = players(db)
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(db, sid, {a: (cad, 1), b: (cad, 2)})
    evs = S.events(db, sid)
    run_event(db, evs[0])
    before = S.career_totals(S.driver_timeline(db, a))
    S._unseat(db, sid, a)                        # replaced mid-season
    run_event(db, evs[1])
    new_sid = S.create_next_season(db, sid, 2027)
    assert a not in S.driver_seats(db, new_sid)  # misses a season...
    newest = S.create_next_season(db, new_sid, 2028)
    S.place_players(db, newest, {a: (cad, 1)})   # ...and returns
    after = S.career_totals(S.driver_timeline(db, a))
    assert after["points"] == before["points"] and after["starts"] == before["starts"]


def test_backups_restore(master_client):
    token, _ = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, ev)
    storage.auto_backup(token, "before-test", force=True)
    with storage.session(token) as conn:
        conn.execute("UPDATE results SET race_position = NULL, result_status = 'Not Run'")
    name = storage.list_auto_backups(token)[0]["name"]
    master_client.post(f"/career/{token}/autobackup/{name}/restore", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM results WHERE race_position IS NOT NULL").fetchone()[0] > 0


def test_upgrade_changes_no_totals(career):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        for ev in S.events(conn, sid)[:3]:
            run_event(conn, ev, difficulty=80)
        before = [(r["driver_id"], r["points"], r["form"], r["reputation"], r["market"]["name"]) for r in S.driver_standings(conn, sid)]
        teams_before = [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, sid)]
        rec_before = S.difficulty_recommendation(conn)["recommended"]
        for table, col in (("events", "ai_untracked"), ("events", "postponed"), ("audit_log", "summary"), ("audit_log", "link")):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        conn.execute("UPDATE meta SET value = '15' WHERE key = 'schema_version'")
        schema.migrate(conn)
        assert [(r["driver_id"], r["points"], r["form"], r["reputation"], r["market"]["name"]) for r in S.driver_standings(conn, sid)] == before
        assert [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, sid)] == teams_before
        assert S.difficulty_recommendation(conn)["recommended"] == rec_before
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(C.SCHEMA_VERSION)


# --------------------------------------------------------------------------- 16. screenshot import: free and local

def test_no_paid_api_anywhere():
    reqs = (ROOT / "requirements.txt").read_text().lower()
    assert "anthropic" not in reqs and "openai" not in reqs
    code = " ".join(p.read_text() for p in (ROOT / "f1tracker").glob("*.py"))
    for word in ("api.anthropic.com", "import anthropic", "openai", "vision.googleapis", "textract", "cognitiveservices"):
        assert word not in code
    assert not (ROOT / "f1tracker" / "importer.py").exists()
    js = (ROOT / "static/js/importer.js").read_text()
    assert "fetch(" not in js and "XMLHttpRequest" not in js      # screenshots are never sent anywhere


def test_saved_api_key_is_removed():
    with auth.accounts() as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES('anthropic_api_key', 'sk-ant-old')")
    with auth.accounts() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key = 'anthropic_api_key'").fetchone() is None


def test_ocr_engine_is_self_hosted_and_lazy(app, master_client):
    token, _ = _league(master_client)
    ev = _events(token)[0]
    for name in ("tesseract.min.js", "worker.min.js", "tesseract-core-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js",
                 "lang/eng.traineddata.gz"):
        assert (ROOT / "static/vendor/tesseract" / name).exists(), name
    res = master_client.get("/static/vendor/tesseract/lang/eng.traineddata.gz")
    assert res.status_code == 200 and "Content-Encoding" not in res.headers and "max-age" in res.headers["Cache-Control"]
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "tesseract.min.js" not in page                       # only loaded when the importer is opened
    assert "not uploaded or sent to an AI provider" in page and "Apply imported results" in page
    assert "js/importer.js" in page
    _add(token, "sam", "spectator")
    assert "js/importer.js" not in _client(app, "sam").get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)


def test_matching_logic_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js isn't installed here")
    out = subprocess.run([node, str(ROOT / "tests/js/ocr_match.test.js")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ok ")


# --------------------------------------------------------------------------- browser: real OCR, and OCR failing to load

@pytest.fixture
def live_server(app):
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _browser():
    sync = pytest.importorskip("playwright.sync_api")
    import os
    pw = sync.sync_playwright().start()
    path = "/opt/pw-browsers/chromium"
    try:
        browser = pw.chromium.launch(executable_path=path) if os.path.exists(path) else pw.chromium.launch()
    except Exception as exc:
        pw.stop()
        pytest.skip(f"no browser: {exc}")
    return pw, browser


def _results_png(page, rows, path, title):
    html = ("<body style='margin:0;background:#15151e;color:#fff;font-family:Arial;width:1100px'>"
            f"<div style='padding:16px 24px;font-size:28px;font-weight:bold'>{title}</div><table style='font-size:24px;margin:0 24px'>")
    for pos, name, team, extra in rows:
        first, last = name.split(" ", 1)
        html += f"<tr style='height:42px'><td style='width:60px'>{pos}</td><td style='width:360px'>{first[0]}. {last.upper()}</td><td style='width:320px;color:#bbb'>{team.upper()}</td><td>{extra}</td></tr>"
    page.set_content(html + "</table></body>")
    page.screenshot(path=path, full_page=True)


def test_browser_screenshot_import_end_to_end(app, master_client, live_server, tmp_path):
    token, ids = _league(master_client, extra_players=("Cleo Park",))
    ev = _events(token)[0]
    with storage.session(token) as conn:
        entrants = [(r["driver"]["name"], r["team"]["name"]) for r in S.weekend_rows(conn, ev["id"])]
    pw, browser = _browser()
    try:
        maker = browser.new_page(viewport={"width": 1100, "height": 700})
        first = [(i + 1, n, t, "+%.3f" % (i * 1.5)) for i, (n, t) in enumerate(entrants[:12])]
        second = [(i + 1, n, t, "+%.3f" % (i * 1.5)) for i, (n, t) in enumerate(entrants) if i >= 10]
        second[-1] = (second[-1][0], second[-1][1], second[-1][2], "DNF")
        _results_png(maker, first, str(tmp_path / "a.png"), "RACE RESULT")
        _results_png(maker, second, str(tmp_path / "b.png"), "RACE RESULT")
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        errors, external, uploads = [], [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: (external.append(r.url) if not r.url.startswith(live_server) and not r.url.startswith(("data:", "blob:")) else None,
                                      uploads.append(r.url) if r.method == "POST" and "import" in r.url else None))
        page.goto(live_server + "/login")
        page.fill("input[name=username]", "david"); page.fill("input[name=password]", "password1")
        page.press("input[name=password]", "Enter"); page.wait_for_load_state()
        page.goto(f"{live_server}/career/{token}/weekend/{ev['id']}")
        page.click('[data-dialog="import-dialog"]')
        page.set_input_files("#imp-file", [str(tmp_path / "a.png"), str(tmp_path / "b.png")])
        page.wait_for_timeout(500)
        page.click("#imp-read")
        page.wait_for_selector("#imp-step-review:not([hidden]), #imp-step-failed:not([hidden])", timeout=180000)
        assert page.locator("#imp-step-review").is_visible(), page.locator("#imp-fail-msg").inner_text()
        assert page.locator("#imp-session2").input_value() == "race"
        picked = page.eval_on_selector_all("#imp-rows tr", "trs => trs.filter(t => t.querySelector('[data-f=include]').checked).map(t => [t.querySelector('select').value, t.querySelector('[data-f=position]').value, t.querySelector('[data-f=status]').value])")
        with storage.session(token) as conn:
            grid_ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        matched = [p for p in picked if p[0]]
        assert len(matched) >= len(grid_ids) - 2                       # nearly all rows read
        assert all(int(p[0]) in grid_ids for p in matched)             # never anyone off the grid
        assert len({p[0] for p in matched}) == len(matched)            # no driver twice
        assert any(p[2] == "DNF" for p in matched)
        # Player rows keep their colours in the preview.
        assert page.locator("#imp-rows tr.player-row").count() >= 2
        # Apply fills the form only: the round isn't submitted or completed.
        for i in range(page.locator("#imp-rows tr").count()):   # fix anything left unresolved by excluding it
            row = page.locator("#imp-rows tr").nth(i)
            if row.locator("[data-f=include]").is_checked() and not row.locator("select[data-f=driver_id]").input_value():
                row.locator("[data-f=include]").uncheck()
        page.wait_for_timeout(200)
        if page.locator("#imp-blocking").inner_text().strip():
            pytest.fail("unexpected blocking findings: " + page.locator("#imp-blocking").inner_text())
        page.click("#imp-apply")
        page.wait_for_timeout(2500)
        with storage.session(token) as conn:
            event = S.get_event(conn, ev["id"])
            assert event["status"] != C.EVENT_COMPLETE
            assert conn.execute("SELECT COUNT(*) FROM results WHERE event_id = ? AND race_position IS NOT NULL",
                                (ev["id"],)).fetchone()[0] >= len(grid_ids) - 2
            assert conn.execute("SELECT COUNT(*) FROM results WHERE event_id = ? AND qualifying_position IS NOT NULL",
                                (ev["id"],)).fetchone()[0] == 0     # Race import never touches Qualifying
        # Importing again: existing values are compared and replacing needs a tick; cancelling changes nothing.
        page.click('[data-dialog="import-dialog"]')
        page.set_input_files("#imp-file", [str(tmp_path / "b.png")]); page.wait_for_timeout(400)
        page.click("#imp-read")
        page.wait_for_selector("#imp-step-review:not([hidden])", timeout=180000)
        first_pos = page.locator("#imp-rows tr").first.locator("input[data-f=position]")
        first_pos.fill("1"); first_pos.dispatch_event("change"); page.wait_for_timeout(200)
        assert "Will be replaced" in page.locator("#imp-compare").inner_text()
        assert page.locator("#imp-apply").is_disabled()
        page.locator("#imp-step-review [data-imp-cancel]").click()
        page.wait_for_timeout(300)
        assert page.locator('input[data-field="race_position"]').nth(10).input_value() == "11"
        assert not external and not uploads and not errors
    finally:
        browser.close()
        pw.stop()


def test_page_keeps_working_if_ocr_cannot_load(app, master_client, live_server, tmp_path):
    token, _ = _league(master_client)
    ev = _events(token)[0]
    pw, browser = _browser()
    try:
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/vendor/tesseract/**", lambda route: route.abort())
        page.goto(live_server + "/login")
        page.fill("input[name=username]", "david"); page.fill("input[name=password]", "password1")
        page.press("input[name=password]", "Enter"); page.wait_for_load_state()
        _results_png(browser.new_page(), [(1, "Lando Norris", "McLaren", "")], str(tmp_path / "x.png"), "RACE")
        page.goto(f"{live_server}/career/{token}/weekend/{ev['id']}")
        page.click('[data-dialog="import-dialog"]')
        page.set_input_files("#imp-file", [str(tmp_path / "x.png")]); page.wait_for_timeout(300)
        page.click("#imp-read")
        page.wait_for_selector("#imp-step-failed:not([hidden])", timeout=30000)
        assert "enter the results in the table as usual" in page.locator("#imp-fail-msg").inner_text()
        page.locator("#imp-step-failed [data-imp-cancel]").click()
        # Manual entry still works and saves.
        box = page.locator('input[data-field="race_position"]').first
        box.fill("1"); page.wait_for_timeout(1800)
        assert "Saved" in page.locator("#save-state").inner_text()
        assert not errors
    finally:
        browser.close()
        pw.stop()
