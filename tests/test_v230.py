"""v2.3: race weekends (upcoming -> paddock open -> lights out -> chequered flag), pre-race press and the
larger post-race question bank."""

from datetime import datetime, timedelta, timezone

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import auth, community, feed, gates, press, roles, services as S, storage, teamlife, timefmt, weekend
from f1tracker import constants as C


def _league(master_client):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    auth.create_user("kim", "Kim", "password1")
    res = master_client.post("/careers/new", data={"name": "V23", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
        roles.set_member(conn, "kim", "scorekeeper")
    pledge_all(token)
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _payload(conn, event, complete=True):
    rows = S.weekend_rows(conn, event["id"])
    ids = [r["driver_id"] for r in rows]
    return {"mark_complete": complete, "ai_difficulty": 80, "results": [
        {"driver_id": d, "qualifying_position": i + 1, "race_position": i + 1, "status_override": "Auto",
         "sprint_position": i + 1 if event["is_sprint"] else None, "sprint_status_override": "Auto",
         "fastest_lap": i == 0, "driver_of_day": False, "notes": ""} for i, d in enumerate(ids)]}


def _api(client, token, event, payload):
    return client.post(f"/api/career/{token}/weekend/{event['id']}", json=payload, headers={"X-CSRF-Token": "tok"})


def _do_prerace(client, token, conn_token, event, driver_id):
    with storage.session(conn_token) as conn:
        pen = teamlife.prerace_pen(conn, S.get_event(conn, event["id"]), driver_id)
    for q in pen["questions"]:
        client.post(f"/career/{token}/weekend/{event['id']}/prerace",
                    data={"csrf_token": "tok", "question": q["key"], "answer": q["answers"][0]["key"]})
    return pen


@pytest.mark.weekends
@pytest.mark.gates
def test_a_full_race_weekend_through_the_website(app, master_client):
    token, a, b = _league(master_client)
    ana, ben, kim = _client(app, "ana"), _client(app, "ben"), _client(app, "kim")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        payload = _payload(conn, ev)
    # Upcoming: results can't go in, not even from the Race Master.
    for who in (kim, master_client):
        r = _api(who, token, ev, payload)
        assert r.status_code == 423 and "hasn't started" in r.get_json()["error"]
    page = kim.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Open the paddock" in page and "Opens at lights out" in page
    assert "Open the paddock" not in ana.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert ana.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"}).status_code == 403
    # A Scorekeeper opens the paddock: everyone's told, pre-race press appears.
    kim.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        e = S.get_event(conn, ev["id"])
        assert weekend.phase(e) == "paddock" and e["paddock_by"] == "kim"
        assert any("paddock is open" in n["headline"].lower() for n in feed.latest(conn, 5))
        assert conn.execute("SELECT 1 FROM notifications WHERE category = 'raceday'").fetchone()
    page = ana.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Pre-race press" in page and "2 questions waiting" in page
    assert "paddock is open" in ana.get(f"/career/{token}/standings").get_data(as_text=True).lower()   # banner everywhere
    assert _api(kim, token, ev, payload).status_code == 423                          # still not started
    # The Scorekeeper can't start while anyone's not ready; the checklist names the pre-race press.
    res = kim.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok"}, follow_redirects=True)
    assert "can&#39;t start yet" in res.get_data(as_text=True).lower() or "can't start yet" in res.get_data(as_text=True).lower()
    with storage.session(token) as conn:
        gate = gates.status(conn, ev["id"])
        assert {i["kind"] for i in gate["players"][0]["checks"]} >= {"prerace", "target"}
        assert weekend.phase(S.get_event(conn, ev["id"])) == "paddock"
    for client, did in ((ana, a), (ben, b)):
        pen = _do_prerace(client, token, token, ev, did)
        assert len(pen["questions"]) == 2
        client.post(f"/career/{token}/target/{ev['id']}/accept", data={"csrf_token": "tok"})
    # Answering twice doesn't count twice.
    with storage.session(token) as conn:
        before = conn.execute("SELECT COUNT(*) FROM press_answers WHERE question LIKE 'pre_%'").fetchone()[0]
    q = pen["questions"][0]
    ben.post(f"/career/{token}/weekend/{ev['id']}/prerace", data={"csrf_token": "tok", "question": q["key"],
                                                                   "answer": q["answers"][1]["key"]})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM press_answers WHERE question LIKE 'pre_%'").fetchone()[0] == before == 4
    ana.post(f"/career/{token}/weekend/{ev['id']}/predict", data={"csrf_token": "tok", "pole": a, "winner": a})
    # Lights out.
    kim.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        e = S.get_event(conn, ev["id"])
        assert weekend.phase(e) == "live" and e["lights_by"] == "kim"
        assert community.predictions_locked(e)
        with pytest.raises(S.ValidationError, match="only open while the paddock"):
            teamlife.answer_prerace(conn, ev["id"], a, pen["questions"][0]["key"], "x")
        assert timefmt.race_status(e["race_at"], e["status"], lights=e["lights_at"], paddock=e["paddock_at"])[0] == "live"
    assert "LIVE" in ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    # Results go in now; submitting waves the chequered flag.
    r = _api(kim, token, ev, payload)
    assert r.get_json()["ok"], r.get_json()
    with storage.session(token) as conn:
        e = S.get_event(conn, ev["id"])
        assert weekend.phase(e) == "complete"
        acts = [x["summary"] for x in conn.execute("SELECT summary FROM audit_log ORDER BY id")]
        assert any("opened the paddock" in (s or "") for s in acts) and any("started Round 1" in (s or "") for s in acts)


@pytest.mark.weekends
@pytest.mark.gates
def test_only_the_race_master_can_start_before_everyone_is_ready(app, master_client):
    token, a, b = _league(master_client)
    kim = _client(app, "kim")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    kim.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    kim.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok", "note": "Starting anyway please"})
    with storage.session(token) as conn:
        assert weekend.phase(S.get_event(conn, ev["id"])) == "paddock"
    master_client.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok"})     # no note
    with storage.session(token) as conn:
        assert weekend.phase(S.get_event(conn, ev["id"])) == "paddock"
    master_client.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok", "note": "Ben's away tonight"})
    with storage.session(token) as conn:
        e = S.get_event(conn, ev["id"])
        assert weekend.phase(e) == "live" and gates.bypass_for(conn, ev["id"])["note"] == "Ben's away tonight"
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Race Master override active" in page
    # Starting can't skip the paddock, and only the next round opens.
    with storage.session(token) as conn:
        r3 = S.events(conn, S.current_season_id(conn))[2]
        with pytest.raises(S.ValidationError, match="Open the paddock first"):
            weekend.start_race(conn, r3["id"], "david", True, "note long enough")
        with pytest.raises(S.ValidationError, match="next round"):
            weekend.open_paddock(conn, r3["id"], "david")


@pytest.mark.weekends
def test_the_paddock_opens_itself_an_hour_before_the_race(app, master_client):
    token, a, b = _league(master_client)
    soon = (datetime.now(timezone.utc) + timedelta(minutes=40)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        community.set_race_at(conn, evs[0]["id"], later)
        community.set_race_at(conn, evs[1]["id"], soon)      # a later round due soon doesn't jump the queue
    master_client.get(f"/career/{token}/dashboard")
    with storage.session(token) as conn:
        assert weekend.phase(S.get_event(conn, evs[0]["id"])) == "upcoming"
        assert weekend.phase(S.get_event(conn, evs[1]["id"])) == "upcoming"
        community.set_race_at(conn, evs[0]["id"], soon)
    _client(app, "ana").get(f"/career/{token}/standings")
    with storage.session(token) as conn:
        e = S.get_event(conn, evs[0]["id"])
        assert weekend.phase(e) == "paddock" and e["paddock_by"] == "auto"
        # Opening again (the next page view) changes nothing and tells nobody twice.
        n = conn.execute("SELECT COUNT(*) FROM notifications WHERE category = 'raceday'").fetchone()[0]
    master_client.get(f"/career/{token}/dashboard")
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM notifications WHERE category = 'raceday'").fetchone()[0] == n


def test_race_weekends_off_means_results_any_time(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        assert not weekend.enabled(conn)          # off in older tests; on by default for real (see DEFAULTS)
        ev = S.events(conn, S.current_season_id(conn))[0]
        payload = _payload(conn, ev)
    assert _api(master_client, token, ev, payload).get_json()["ok"]
    assert weekend.DEFAULTS["race_weekends"] == "0"   # (patched by conftest)


@pytest.mark.weekends
def test_race_weekends_are_on_by_default_and_can_be_turned_off(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        assert weekend.enabled(conn)
    assert 'name="race_weekends"' in master_client.get(f"/career/{token}/settings").get_data(as_text=True)
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "team_life": "1", "difficulty_recs": "1"})
    with storage.session(token) as conn:
        assert not weekend.enabled(conn)


def test_post_race_questions_follow_what_happened(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        teamlife._bank_since(conn)
        conn.execute("UPDATE meta SET value = '2000-01-01 00:00:00' WHERE key = 'press_bank_since'")
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        others = [d for d in ids if d not in (a, b)]
        # R1: Ana qualifies P15 and finishes P5 (10 places gained); Ben retires.
        order = others[:4] + [a] + others[4:] + [b]
        quali = others[:14] + [a] + others[14:] + [b]
        run_event(conn, evs[0], order=order, quali=quali, overrides={b: "DNF"})
        conn.execute("UPDATE events SET submitted_at = ? WHERE id = ?", (storage.now_iso(), evs[0]["id"]))
        qa = teamlife.questions_for(conn, evs[0]["id"], a)
        assert qa[0]["key"] == "gain" and "P15" in qa[0]["text"] and "10 places" in qa[0]["text"]
        assert teamlife.questions_for(conn, evs[0]["id"], b)[0]["key"] == "dnf"
        # R2: Ben retires again -> "another early finish"; Ana wins.
        run_event(conn, evs[1], order=[a] + others + [b], overrides={b: "DNF"}, fl=a)
        conn.execute("UPDATE events SET submitted_at = ? WHERE id = ?", (storage.now_iso(), evs[1]["id"]))
        assert teamlife.questions_for(conn, evs[1]["id"], b)[0]["key"] == "dnf_again"
        win = teamlife.questions_for(conn, evs[1]["id"], a)
        assert win[0]["key"] == "win" and len(win) == 2
        # The same questions every time they're asked.
        assert teamlife.questions_for(conn, evs[1]["id"], a) == win
        # Answering works, moves the relationship and can make a headline with the driver's name.
        teamlife.answer(conn, evs[1]["id"], a, "win", "me")
        assert any("Nobody could touch me" in n["headline"] and "Ana Silva" in n["headline"] for n in feed.latest(conn, 5))


def test_rounds_from_before_2_3_keep_their_questions(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        ev = S.events(conn, sid)[0]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        run_event(conn, ev, order=[a] + [d for d in ids if d != a])
        conn.execute("UPDATE events SET submitted_at = '2026-01-01 00:00:00' WHERE id = ?", (ev["id"],))
        teamlife._bank_since(conn)
        keys = [q["key"] for q in teamlife.questions_for(conn, ev["id"], a)]
        assert keys == teamlife.legacy_keys(conn, ev["id"], a) == ["credit", "beat_mate"]


def test_every_question_reads_properly():
    facts = {"driver": "Ana Silva", "team": "Cadillac", "mate": "Ben Okafor", "rival": "Carl Diaz", "event": "Monaco GP",
             "pos": 5, "quali": 15, "gain": 10, "sprint": 3, "target": "Finish P12 or better", "champ": "second"}
    assert len(press.PRE) >= 15 and len(press.POST) >= 15
    for bank in (press.PRE, press.POST, teamlife.QUESTIONS):
        for key, (text, answers) in bank.items():
            built = press.build([key], facts, bank)[0]
            assert "{" not in built["text"] and len(answers) == 3, key
            assert all(-3 <= e <= 3 for _k, _t, e, _h in answers), key
            assert len({k for k, _t, _e, _h in answers}) == 3, key
            for _k, _t, _e, h in answers:
                assert h is None or "{" not in press._fill(h, facts), key


@pytest.mark.weekends
def test_pre_race_questions_fit_the_driver(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        r1 = S.get_event(conn, evs[0]["id"])
        keys = [q["key"] for q in teamlife.prerace_pen(conn, r1, a)["questions"]]
        assert "pre_opener" in keys and len(keys) == 2 and all(k.startswith("pre_") for k in keys)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        run_event(conn, evs[0], order=[d for d in ids if d != a] + [a], overrides={a: "DNF"})
        r2 = S.get_event(conn, evs[1]["id"])
        pen = teamlife.prerace_pen(conn, r2, a)
        assert pen["questions"][0]["key"] == "pre_bounce"
        # Stable: the same two after more results come in.
        run_event(conn, evs[1])
        assert [q["key"] for q in teamlife.prerace_pen(conn, S.get_event(conn, evs[1]["id"]), a)["questions"]] == \
               [q["key"] for q in pen["questions"]]


def test_schema_19_adds_the_weekend_columns(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
        assert {"paddock_at", "paddock_by", "lights_at", "lights_by"} <= cols
        assert storage.get_meta(conn, "schema_version") == "19" == str(C.SCHEMA_VERSION)
