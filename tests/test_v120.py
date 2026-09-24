"""v1.20: team orders toggle, weekend targets, teammate battle and round gates."""

import random

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import (auth, battle, community, feed, gates, market, relations, roles, schema, services as S,
                       storage, teamlife)
from f1tracker import constants as C


def _league(master_client):
    """David (site Race Master, no driver) runs a league; ana and ben drive for Cadillac with logins."""
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    res = master_client.post("/careers/new", data={"name": "V20", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"], "csrf_token": "tok"})
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


def _events(token):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))


def _payload(token, event_id, complete=False):
    with storage.session(token) as conn:
        rows = S.weekend_rows(conn, event_id)
    return {"results": [{"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1,
                         "status_override": "Auto", "sprint_position": i + 1, "sprint_status_override": "Auto",
                         "fastest_lap": False, "driver_of_day": False, "notes": ""} for i, r in enumerate(rows)],
            "mark_complete": complete, "ai_difficulty": None, "ai_untracked": True}


def _api_save(client, token, event_id, complete=False):
    return client.post(f"/api/career/{token}/weekend/{event_id}", json=_payload(token, event_id, complete),
                       headers={"X-CSRF-Token": "tok"})


def _seat(conn, sid, pairs):
    """pairs: {driver_id: team name, seat}."""
    ids = {n: conn.execute("SELECT id FROM teams WHERE name = ?", (n,)).fetchone()["id"] for n, _s in pairs.values()}
    S.place_players(conn, sid, {d: (ids[n], s) for d, (n, s) in pairs.items()})


# --------------------------------------------------------------------------- team orders

def test_team_orders_off_by_default_advisory_and_on(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    _seat(db, sid, {david: ("Cadillac", 1), carson: ("Cadillac", 2)})
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    market.open_window(db, sid, rng=random.Random(1))
    for did in (david, carson):
        offer = [o for o in market.offers(db, driver_id=did) if o["status"] == C.OFFER_PENDING][0]
        db.execute("UPDATE offers SET team_id = ?, role = ? WHERE id = ?", (cad, "No. 2" if did == carson else "No. 1",
                                                                          offer["id"]))
        market.accept_offer(db, offer["id"])
    _seat(db, sid, {david: ("Cadillac", 1), carson: ("Cadillac", 2)})
    relations.ensure(db, sid)
    assert relations.assess(db, sid, carson)["role"] == "No. 2"

    class Low(random.Random):
        def random(self):
            return 0.0
    assert teamlife.settings(db)["orders"] == "off"
    assert teamlife.issue_orders(db, sid, rng=Low()) == []            # Off: never issued

    storage.set_meta(db, "team_orders", "advisory")
    assert teamlife.issue_orders(db, sid, rng=Low()) == [carson]
    ev = S.next_incomplete_event(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, ev["id"])]
    run_event(db, ev, order=[carson, david] + [d for d in ids if d not in (carson, david)])
    headlines = len(feed.latest(db, 50))
    assert teamlife.resolve_orders(db, ev["id"]) == [(carson, "Ignored")]
    assert relations.assess(db, sid, carson)["bonus"] == 0            # Advisory: no effect
    assert len(feed.latest(db, 50)) == headlines                      # and no headline

    storage.set_meta(db, "team_orders", "on")
    assert teamlife.issue_orders(db, sid, rng=Low()) == [carson]
    # Switching Off cancels the waiting order with no penalty; its history stays.
    teamlife.save_settings(db, "off", True, True, True, True)
    orders = teamlife.orders_for(db, sid, carson)
    assert [o["status"] for o in orders] == ["Cancelled", "Ignored"]
    ev2 = S.next_incomplete_event(db, sid)
    run_event(db, ev2, order=[carson, david] + [d for d in ids if d not in (carson, david)])
    assert teamlife.resolve_orders(db, ev2["id"]) == []
    assert relations.assess(db, sid, carson)["bonus"] == 0


def test_league_settings_change_team_life_and_log_it(app, master_client):
    token, a, b = _league(master_client)
    res = master_client.post(f"/career/{token}/settings", data={
        "csrf_token": "tok", "team_life": "1", "team_orders": "advisory", "weekend_targets": "1", "round_gates": "1",
        "gate_press": "1", "join_mode": "invite", "race_window": "180"})
    assert res.status_code == 302
    with storage.session(token) as conn:
        assert teamlife.settings(conn) == {"orders": "advisory", "targets": True, "gates": True, "gate_press": True,
                                           "gate_targets": False}
        log = community.audit_entries(conn)[0]["summary"]
    assert "changed team orders from Off to Advisory" in log and "turned the weekend-target gate off" in log
    page = master_client.get(f"/career/{token}/settings").get_data(as_text=True)
    assert "Team life" in page and 'value="advisory" selected' in page


# --------------------------------------------------------------------------- weekend targets

def test_targets_are_realistic_for_every_car(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    ranks = S.team_strength_ranks(db, sid)
    fastest = min(ranks, key=ranks.get)
    slowest = max(ranks, key=ranks.get)
    tmap = S.team_map(db)
    _seat(db, sid, {david: (tmap[fastest]["name"], 1), carson: (tmap[slowest]["name"], 1)})
    ev = S.events(db, sid)[0]
    for seed in range(40):
        fast = teamlife.plan_target(db, ev, david, fastest, ranks, random.Random(seed))
        slow = teamlife.plan_target(db, ev, carson, slowest, ranks, random.Random(seed))
        if fast["kind"] == "finish":
            assert fast["target"] <= 4
        if slow["kind"] in ("finish", "points"):
            assert slow["target"] >= 15, slow          # a backmarker is never asked for a podium or points
        assert slow["kind"] != "beat_team"               # nobody slower to beat
        assert fast["label"] and slow["label"]
    kinds = {teamlife.plan_target(db, ev, david, fastest, ranks, random.Random(s))["kind"] for s in range(60)}
    assert {"finish", "beat_team", "teammate"} <= kinds


def test_targets_judged_with_void_and_excused_dnf_and_rejudged_on_correction(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    _seat(db, sid, {david: ("Cadillac", 1), carson: ("Cadillac", 2)})
    relations.ensure(db, sid)
    evs = S.events(db, sid)
    ev = evs[0]
    assert teamlife.issue_targets(db, ev["id"]) == [david, carson]
    assert teamlife.issue_targets(db, ev["id"]) == []                 # never twice
    db.execute("UPDATE weekend_targets SET kind = 'finish', target = 5, label = 'Finish P5 or better' WHERE event_id = ?",
               (ev["id"],))
    ids = [r["driver_id"] for r in S.weekend_rows(db, ev["id"])]
    order = [david] + [d for d in ids if d not in (david, carson)] + [carson]
    run_event(db, ev, order=order, overrides={carson: "DNF"})
    assert dict(teamlife.judge_targets(db, ev["id"])) == {david: "Hit", carson: "Missed"}
    assert relations.assess(db, sid, david)["bonus"] == C.TARGET_HIT
    assert relations.assess(db, sid, carson)["bonus"] == C.TARGET_MISSED
    # Re-judging never counts twice.
    teamlife.judge_targets(db, ev["id"])
    assert relations.assess(db, sid, david)["bonus"] == C.TARGET_HIT
    # The Race Master rules the DNF wasn't Carson's fault: void, and the penalty is taken back.
    assert teamlife.excuse(db, ev["id"], carson, True)["status"] == "Void"
    assert relations.assess(db, sid, carson)["bonus"] == 0
    with pytest.raises(S.ValidationError):
        teamlife.excuse(db, ev["id"], david, True)                      # only a DNF/DSQ can be excused
    # A correction moves David to P9: re-judged as a miss, only the difference applied.
    run_event(db, ev, order=[d for d in ids if d not in (david, carson)][:8] + [david] + [carson], overrides={carson: "DNF"})
    teamlife.judge_targets(db, ev["id"])
    assert teamlife.target_for(db, ev["id"], david)["status"] == "Missed"
    assert relations.assess(db, sid, david)["bonus"] == C.TARGET_MISSED
    # Didn't take part: void.
    ev2 = evs[1]
    teamlife.issue_targets(db, ev2["id"])
    run_event(db, ev2, overrides={carson: "DNS"})
    assert dict(teamlife.judge_targets(db, ev2["id"]))[carson] == "Void"


def test_three_targets_in_a_row_make_one_headline(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    _seat(db, sid, {david: ("Cadillac", 1), carson: ("Cadillac", 2)})
    relations.ensure(db, sid)
    for ev in S.events(db, sid)[:3]:
        teamlife.issue_targets(db, ev["id"])
        db.execute("UPDATE weekend_targets SET kind = 'classified', target = 22 WHERE event_id = ?", (ev["id"],))
        run_event(db, ev)
        teamlife.judge_targets(db, ev["id"])
        teamlife.judge_targets(db, ev["id"])
    assert teamlife.target_streak(db, sid, david, 3) == 3
    streaks = [n for n in feed.latest(db, 50) if "3 team targets in a row" in n["headline"]]
    assert len(streaks) == 2   # one each for David and Carson, not repeated by re-judging


def test_targets_off_issue_nothing(db):
    storage.set_meta(db, "weekend_targets", "0")
    ev = S.events(db, S.current_season_id(db))[0]
    assert teamlife.issue_targets(db, ev["id"]) == []


# --------------------------------------------------------------------------- teammate battle

def test_teammate_battle_counts_dnfs_and_splits_mid_season_seat_changes(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    _seat(db, sid, {david: ("Cadillac", 1), carson: ("Cadillac", 2)})
    evs = S.events(db, sid)
    ids = lambda ev: [r["driver_id"] for r in S.weekend_rows(db, ev["id"])]  # noqa: E731
    rest = lambda ev: [d for d in ids(ev) if d not in (david, carson)]        # noqa: E731
    run_event(db, evs[0], order=[david, carson] + rest(evs[0]), quali=[carson, david] + rest(evs[0]))
    run_event(db, evs[1], order=[carson, david] + rest(evs[1]), overrides={carson: "DNF"})   # finisher beats a DNF
    run_event(db, evs[2], order=[david, carson] + rest(evs[2]), overrides={david: "DNF", carson: "DNF"})  # skipped
    p = battle.pairings(db, sid, david)
    assert len(p) == 1 and p[0]["mate"]["id"] == carson
    assert (p[0]["race_won"], p[0]["race_lost"]) == (2, 0)
    assert (p[0]["quali_won"], p[0]["quali_lost"]) == (1, 2)
    assert p[0]["human"] and p[0]["first_round"] == 1 and p[0]["last_round"] == 3
    assert p[0]["gap"] == p[0]["points"] - p[0]["mate_points"] > 0
    # Carson moves to Haas from round 4: David gets a new pairing with his new teammate.
    _seat(db, sid, {david: ("Cadillac", 1), carson: ("Haas", 1)})
    run_event(db, evs[3])
    p = battle.pairings(db, sid, david)
    assert [x["mate"]["id"] == carson for x in p] == [True, False]
    assert p[1]["first_round"] == 4 and not p[1]["human"]
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    assert len(battle.team_battles(db, sid, cad)) == 2


def test_battle_headlines_and_pages(app, master_client):
    token, a, b = _league(master_client)
    evs = _events(token)
    with storage.session(token) as conn:
        storage.set_meta(conn, "round_gates", "0")
    for i in range(5):
        payload = _payload(token, evs[i]["id"], True)
        ids = [r["driver_id"] for r in payload["results"]]
        order = [b, a] + [d for d in ids if d not in (a, b)]
        for r in payload["results"]:
            r["race_position"] = r["qualifying_position"] = order.index(r["driver_id"]) + 1
            r["sprint_position"] = r["race_position"]
        assert master_client.post(f"/api/career/{token}/weekend/{evs[i]['id']}", json=payload,
                                  headers={"X-CSRF-Token": "tok"}).status_code == 200
    with storage.session(token) as conn:
        heads = [n["headline"] for n in feed.latest(conn, 80)]
    assert any("Ben Okafor takes the lead" in h for h in heads)
    assert any("Ben Okafor beats Ana Silva for the fifth race in a row" in h for h in heads)
    prof = master_client.get(f"/career/{token}/driver/{a}").get_data(as_text=True)
    assert "Teammate battle" in prof and "Race <b>0–5</b>" in prof and "Human vs human" in prof
    week = master_client.get(f"/career/{token}/weekend/{evs[4]['id']}").get_data(as_text=True)
    assert "Teammate battles after R5" in week


# --------------------------------------------------------------------------- round gates

@pytest.mark.gates
def test_gates_block_scorekeepers_until_linked_players_are_ready(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    _add(token, "sam", "spectator")
    kim, ana, ben, sam = (_client(app, n) for n in ("kim", "ana", "ben", "sam"))
    r1 = _events(token)[0]
    # Round 1: no press gate (nothing before it), only the weekend-target gate.
    dash = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Weekend target" in dash and "Got it" in dash and "is waiting on you" in dash
    res = _api_save(kim, token, r1["id"])
    assert res.status_code == 423 and res.get_json()["gated"]
    assert "Ana Silva" in res.get_json()["error"] and "Only the Race Master" in res.get_json()["error"]
    week = kim.get(f"/career/{token}/weekend/{r1['id']}").get_data(as_text=True)
    assert "can't start yet" in week and 'data-readonly="1"' in week and "Open this round early" not in week
    assert "Send a reminder" in week
    # A spectator sees the checklist, read only.
    spec = sam.get(f"/career/{token}/weekend/{r1['id']}").get_data(as_text=True)
    assert "can't start yet" in spec and "Send a reminder" not in spec and "Open this round early" not in spec
    assert sam.post(f"/career/{token}/weekend/{r1['id']}/remind", data={"csrf_token": "tok"}).status_code == 403
    # Scorekeeper sends one reminder, not two.
    kim.post(f"/career/{token}/weekend/{r1['id']}/remind", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert gates.reminded(conn, r1["id"])
        with pytest.raises(S.ValidationError):
            gates.remind(conn, r1["id"])
    ana.post(f"/career/{token}/target/{r1['id']}/accept", data={"csrf_token": "tok"})
    assert _api_save(kim, token, r1["id"]).status_code == 423          # still waiting on Ben
    ben.post(f"/career/{token}/target/{r1['id']}/accept", data={"csrf_token": "tok"})
    assert _api_save(kim, token, r1["id"], complete=True).status_code == 200
    # Round 2 now needs both press answers from round 1 and the round 2 target.
    r2 = _events(token)[1]
    with storage.session(token) as conn:
        gate = gates.status(conn, r2["id"])
        assert gate["blocking"] and {p["driver"]["id"] for p in gate["players"]} == {a, b}
        assert {i["kind"] for i in gate["players"][0]["checks"]} == {"press", "target"}
        pens = teamlife.press_pens(conn, S.current_season_id(conn), a)
    dash = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "2 press questions to answer from R1" in dash and "required" in dash
    for q in pens[-1]["questions"]:
        ana.post(f"/career/{token}/press/{r1['id']}", data={"csrf_token": "tok", "question": q["key"],
                                                              "answer": q["answers"][0]["key"]})
    ana.post(f"/career/{token}/target/{r2['id']}/accept", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert gates.my_todo(conn, S.current_season_id(conn), a) is None
        assert gates.my_todo(conn, S.current_season_id(conn), b)["press"] == 2
    assert _api_save(kim, token, r2["id"]).status_code == 423
    # Unlinking Ben's login takes him off the checklist: players without a login never block.
    with storage.session(token) as conn:
        conn.execute("UPDATE career_members SET driver_id = NULL WHERE username = 'ben'")
    assert _api_save(kim, token, r2["id"]).status_code == 200


@pytest.mark.gates
def test_race_master_bypass_needs_a_note_is_logged_and_late_answers_still_count(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    kim, ana, ben = (_client(app, n) for n in ("kim", "ana", "ben"))
    r1, r2 = _events(token)[:2]
    master_client.get(f"/career/{token}/dashboard")
    # The Race Master is gated too until they open the round.
    assert _api_save(master_client, token, r1["id"]).status_code == 423
    week = master_client.get(f"/career/{token}/weekend/{r1['id']}").get_data(as_text=True)
    assert "Open this round early" in week and 'data-readonly="1"' in week
    # Scorekeepers can't bypass.
    assert kim.post(f"/career/{token}/weekend/{r1['id']}/open-early",
                    data={"csrf_token": "tok", "note": "Carson's away, answering later"}).status_code == 403
    master_client.post(f"/career/{token}/weekend/{r1['id']}/open-early", data={"csrf_token": "tok", "note": "short"})
    assert _api_save(kim, token, r1["id"]).status_code == 423          # a note is required
    master_client.post(f"/career/{token}/weekend/{r1['id']}/open-early",
                       data={"csrf_token": "tok", "note": "Ben's away, answering later"})
    assert _api_save(kim, token, r1["id"], complete=True).status_code == 200
    with storage.session(token) as conn:
        log = [e for e in community.audit_entries(conn) if e["action"] == "Opened a round early"]
        assert log and "Ben's away, answering later" in log[0]["summary"] and "Ana Silva" in log[0]["summary"]
    week = kim.get(f"/career/{token}/weekend/{r1['id']}").get_data(as_text=True)
    assert "Opened by the Race Master" in week and "Ben&#39;s away, answering later" in week
    # Round 2 is bypassed too, and completed, while Ben still hasn't answered round 1's press.
    master_client.post(f"/career/{token}/weekend/{r2['id']}/open-early",
                       data={"csrf_token": "tok", "note": "Still away this week"})
    assert _api_save(kim, token, r2["id"], complete=True).status_code == 200
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        before = relations.assess(conn, sid, b)["bonus"]
        pens = teamlife.press_pens(conn, sid, b)
    assert [p["event"]["id"] for p in pens] == [r1["id"], r2["id"]]    # round 1's questions haven't lapsed
    q = pens[0]["questions"][0]
    ben.post(f"/career/{token}/press/{r1['id']}", data={"csrf_token": "tok", "question": q["key"],
                                                          "answer": q["answers"][0]["key"]})
    with storage.session(token) as conn:
        assert relations.assess(conn, sid, b)["bonus"] == before + q["answers"][0]["effect"]
    # A completed round being corrected by the Race Master is never gated.
    assert _api_save(master_client, token, r2["id"], complete=True).status_code == 200


@pytest.mark.gates
def test_nothing_before_gates_becomes_a_requirement(app, master_client):
    """A round completed before v1.20 (press_required = 0) doesn't gate the next one on press answers."""
    token, a, b = _league(master_client)
    r1, r2 = _events(token)[:2]
    with storage.session(token) as conn:
        run_event(conn, r1)                     # completed the old way: no press requirement recorded
        assert not S.get_event(conn, r1["id"])["press_required"]
        gate = gates.status(conn, r2["id"])
        assert all(i["kind"] == "target" for p in gate["players"] for i in p["checks"])
        # A round already under way when gates arrived has no target and isn't gated.
        storage.set_meta(conn, "weekend_targets", "0")
        conn.execute("UPDATE events SET status = 'In Progress' WHERE id = ?", (r2["id"],))
        assert not gates.status(conn, r2["id"])["blocking"]
        # Gates off: nothing is gated.
        conn.execute("UPDATE events SET status = 'Not Run' WHERE id = ?", (r2["id"],))
        storage.set_meta(conn, "weekend_targets", "1")
        storage.set_meta(conn, "round_gates", "0")
        assert not gates.status(conn, r2["id"])["blocking"]


def test_migration_adds_tables_without_touching_results(tmp_path):
    import sqlite3
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Old", 2026, ["A", "B"])
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
        before = conn.execute("SELECT * FROM results ORDER BY event_id, driver_id").fetchall()
    path = storage.career_path(token) if hasattr(storage, "career_path") else None
    with storage.session(token) as conn:
        conn.execute("DROP TABLE weekend_targets")
        conn.execute("DROP TABLE gate_bypasses")
        conn.execute("ALTER TABLE events DROP COLUMN press_required")
        conn.execute("UPDATE meta SET value = '16' WHERE key = 'schema_version'")
    with storage.session(token) as conn:
        schema.migrate(conn)
        after = conn.execute("SELECT * FROM results ORDER BY event_id, driver_id").fetchall()
        assert [tuple(r) for r in after] == [tuple(r) for r in before]
        assert conn.execute("SELECT COUNT(*) FROM weekend_targets").fetchone()[0] == 0
        assert conn.execute("SELECT SUM(press_required) FROM events").fetchone()[0] == 0
        assert storage.get_meta(conn, "schema_version") == str(C.SCHEMA_VERSION)
    assert path is None or path
