"""4.1.0: a round fills itself in when its race arrives from the game, then waits for one tap to approve; and the
site owner's Test leagues, including a race night played from made-up game data."""

import json

import pytest

from conftest import login
from f1tracker import auth, autofill, feed, storage, telemetry, testleagues
from f1tracker import services as S

REAL = [pytest.mark.engine3, pytest.mark.latest, pytest.mark.pacerequired, pytest.mark.gates, pytest.mark.weekends,
        pytest.mark.trackai]


def real(fn):
    for m in REAL:
        fn = m(fn)
    return fn


def _round(token):
    with storage.session(token) as conn:
        return testleagues._last_round(conn)


def test_match_driver_mirrors_the_round_page():
    grid = [{"id": 1, "name": "Max Verstappen", "team": "Red Bull Racing"},
            {"id": 2, "name": "Lando Norris", "team": "McLaren"},
            {"id": 3, "name": "Player One", "team": "Williams"},
            {"id": 4, "name": "Player Two", "team": "Haas"}]
    assert autofill.match_driver("VERSTAPPEN", grid)["driver_id"] == 1
    assert autofill.match_driver("M. Verstappen", grid)["state"] == "matched"
    assert autofill.match_driver("PLAYER ONE", grid)["driver_id"] == 3
    assert autofill.match_driver("Zzzz", grid)["state"] == "unmatched"
    # a name it knows from an earlier import wins over any guess
    assert autofill.match_row({"name": "Player", "team": "Haas"}, grid, {"Player|Haas": 4}) == (4, "high")
    # the game's team decides between two lookalikes
    assert autofill.match_row({"name": "PLAYER", "team": "Williams"}, grid, {}) == (None, "unmatched")


def test_python_matching_gives_the_same_answers_as_the_browser():
    """autofill.match_driver is a port of static/js/ocr_match.js matchDriver: both must pick the same driver."""
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        pytest.skip("Node isn't installed")
    grid = [{"id": i + 1, "name": n} for i, n in enumerate(
        ["Max Verstappen", "Lando Norris", "Oscar Piastri", "Kimi Antonelli", "Carlos Sainz", "Player One", "Player Two",
         "Nico Hulkenberg", "Gabriel Bortoleto", "Isack Hadjar", "Lewis Hamilton", "Charles Leclerc"])]
    names = ["VERSTAPPEN", "NORRIS", "PIASTRI", "ANTONELLI", "SAINZ", "PLAYER ONE", "PLAYER TWO", "HÜLKENBERG",
             "BORTOLETO", "HADJAR", "HAMILTON", "LECLERC", "L. Hamilton", "C LECLERC", "Player", "Unknown", "SAlNZ"]
    js = Path(__file__).resolve().parent.parent / "static/js/ocr_match.js"
    script = (f"const M = require({json.dumps(str(js))}); const grid = {json.dumps(grid)};"
              f"console.log(JSON.stringify({json.dumps(names)}.map(n => {{ const m = M.matchDriver(n, grid);"
              f" return [m.state, m.driver_id]; }})));")
    out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60).stdout)
    assert [[m["state"], m["driver_id"]] for m in (autofill.match_driver(n, grid) for n in names)] == out


def test_combine_quali_orders_q3_then_q2_then_q1():
    q1 = {"results": [{"position": i + 1, "name": n, "team": "T"} for i, n in enumerate("ABCDE")]}
    q2 = {"results": [{"position": i + 1, "name": n, "team": "T"} for i, n in enumerate("BACD")]}
    q3 = {"results": [{"position": 1, "name": "C", "team": "T"}, {"position": 2, "name": "A", "team": "T"}]}
    assert [r["name"] for r in autofill.combine_quali([q1, q2, q3])] == ["C", "A", "B", "D", "E"]


@real
def test_a_race_from_the_game_fills_the_round_and_one_tap_submits_it(app, master_client):
    page = master_client.get("/settings/tests").get_data(as_text=True)
    assert "Race night from the game" in page and "Season finale" in page
    res = master_client.post("/settings/tests/new", data={"csrf_token": "tok", "scenario": "game_round"})
    assert res.status_code == 302
    league = testleagues.leagues()[0]
    token, event_id = league["token"], league["round_id"]
    assert league["race_waiting"]
    # Before the race: qualifying is in from the game, nothing is filled yet
    with storage.session(token) as conn:
        assert autofill.state(conn, event_id) is None
        assert {u["kind"] for u in telemetry.recent(conn)} == {"qualifying"}
    # The race arrives exactly the way the recorder sends it
    res = master_client.post(f"/settings/tests/{token}/send-race", data={"csrf_token": "tok"})
    assert res.status_code == 302 and "stage=review" in res.headers["Location"]
    with storage.session(token) as conn:
        info = autofill.state(conn, event_id)
        assert info["status"] == "ready" and not info["missing"] and not info["notes"]
        assert any("qualifying" in f for f in info["filled"]) and any("race" in f for f in info["filled"])
        assert any("Player One" in f for f in info["filled"]) and "race winner's time" in info["filled"]
        check = S.submission_check(conn, event_id)
        assert not check["blocking"], check["blocking"]
        rows = S.weekend_rows(conn, event_id)
        assert sorted(r["race_position"] for r in rows) == list(range(1, len(rows) + 1))
        assert [r["result_status"] for r in rows].count("DNF") == 1
        assert sum(r["fastest_lap"] for r in rows) == 1
        assert S.get_event(conn, event_id)["ai_difficulty"] == 85
        alerts = conn.execute("SELECT text, link FROM notifications WHERE text LIKE '%in from the game%'").fetchall()
        assert len(alerts) == 1 and alerts[0]["link"].endswith("stage=review")
        assert S.get_event(conn, event_id)["status"] != "Complete"     # nothing is submitted by itself
    page = master_client.get(f"/career/{token}/weekend/{event_id}?stage=review").get_data(as_text=True)
    assert "Ready to approve" in page and "data-approve" in page and "Test league." in page
    # Sending the same race again (say, a rebuilt recording) changes nothing and doesn't alert twice
    with storage.session(token) as conn:
        upload = telemetry.store(conn, json.loads(storage.get_meta(conn, "test_race_payload")))
        autofill.after_upload(conn, upload)
        assert conn.execute("SELECT COUNT(*) FROM notifications WHERE text LIKE '%in from the game%'").fetchone()[0] == 1
        revision = S.get_event(conn, event_id)["revision"]
    # Approve and submit = the normal submit
    snap = master_client.get(f"/api/career/{token}/weekend/{event_id}/state").get_json()
    res = master_client.post(f"/api/career/{token}/weekend/{event_id}", json={
        "mark_complete": True, "base_revision": revision, "ai_difficulty": snap["ai_difficulty"],
        "event_notes": snap["event_notes"], "results": [{"driver_id": int(k), **v} for k, v in snap["results"].items()]},
        headers={"X-CSRF-Token": "tok"})
    assert res.get_json()["ok"], res.get_json()
    with storage.session(token) as conn:
        assert S.get_event(conn, event_id)["status"] == "Complete"
        assert autofill.state(conn, event_id) is None
    assert not testleagues.leagues()[0]["race_waiting"]
    # and the test league can be deleted from the Test leagues page
    master_client.post(f"/settings/tests/{token}/delete", data={"csrf_token": "tok"})
    assert testleagues.leagues() == []


@real
def test_through_the_real_upload_link(app, master_client):
    """The recorder's own route: the race gets the round ready, and a race that isn't the last session doesn't."""
    token = testleagues.create("game_round", "devon")
    event = _round(token)
    with storage.session(token) as conn:
        key = telemetry.upload_key(conn)
        race = json.loads(storage.get_meta(conn, "test_race_payload"))
    practice = {**race, "session_uid": "p1", "session": {**race["session"], "session_type": "Practice 1", "session_type_id": 1}}
    client = app.test_client()
    assert client.post(f"/api/telemetry/{token}/{key}", json=practice).get_json()["ok"]
    with storage.session(token) as conn:
        assert autofill.state(conn, event["id"]) is None
    assert client.post(f"/api/telemetry/{token}/{key}", json=race).get_json()["ok"]
    with storage.session(token) as conn:
        assert autofill.state(conn, event["id"])["status"] == "ready"
        assert not S.submission_check(conn, event["id"])["blocking"]


@real
def test_kept_entries_waiting_rounds_and_the_setting(app, master_client):
    token = testleagues.create("game_round", "devon")
    event = _round(token)
    with storage.session(token) as conn:
        race = json.loads(storage.get_meta(conn, "test_race_payload"))
        # someone already typed the race in by hand (only P1 so far): the race is kept, qualifying still fills
        rows = S.weekend_rows(conn, event["id"])
        snap = S.weekend_snapshot(conn, event["id"])
        snap["results"][str(rows[0]["driver_id"])]["race_position"] = 1
        S.save_weekend(conn, event["id"], {"results": [{"driver_id": int(k), **v} for k, v in snap["results"].items()]})
        info = autofill.after_upload(conn, telemetry.store(conn, race))
        assert "race (already entered)" in info["kept"] and any("qualifying" in f for f in info["filled"])
        assert [r["race_position"] for r in S.weekend_rows(conn, event["id"]) if r["race_position"]] == [1]
    # a round whose race hasn't started on the site waits instead of filling in
    token = testleagues.create("game_round", "devon")
    event = _round(token)
    with storage.session(token) as conn:
        conn.execute("UPDATE events SET lights_at = NULL, paddock_at = NULL WHERE id = ?", (event["id"],))
        race = json.loads(storage.get_meta(conn, "test_race_payload"))
        info = autofill.after_upload(conn, telemetry.store(conn, race))
        assert info["status"] == "waiting" and "hasn't started" in info["why"]
        assert all(r["race_position"] is None for r in S.weekend_rows(conn, event["id"]))
    # the league can turn it off: then the race just waits in Import results, as before 4.1.0
    master_client.post(f"/career/{token}/settings/telemetry", data={"csrf_token": "tok", "action": "autofill_off"})
    with storage.session(token) as conn:
        assert not autofill.enabled(conn)
        conn.execute("DELETE FROM meta WHERE key = ?", (f"autofill_{event['id']}",))
        assert autofill.after_upload(conn, telemetry.store(conn, race)) is None


def test_test_leagues_are_owner_only_and_never_send_anything(app, master_client, monkeypatch):
    auth.create_user("sam", "Sam", "password1")
    client = app.test_client()
    login(client, "sam")
    assert client.get("/settings/tests").status_code == 403
    assert client.post("/settings/tests/new", data={"csrf_token": "tok", "scenario": "first_round"}).status_code == 403
    assert "Test leagues" in master_client.get("/accounts").get_data(as_text=True)
    token = testleagues.create("first_round", "devon")
    from f1tracker import delivery, mailer, push
    monkeypatch.setattr(push, "available", lambda: True)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    with storage.session(token) as conn:
        feed.notify(conn, None, "hello")
    assert delivery.plan(feed.take_outbox()) == []
    # a real league can't be deleted or sent a race from the Test leagues page
    res = master_client.post("/careers/new", data={"name": "Real", "year": "2026", "csrf_token": "tok", "join_mode": "invite"})
    real_token = res.headers["Location"].split("/career/")[1].split("/")[0]
    master_client.post(f"/settings/tests/{real_token}/delete", data={"csrf_token": "tok"})
    master_client.post(f"/settings/tests/{real_token}/send-race", data={"csrf_token": "tok"})
    assert storage.career_path(real_token).exists()
