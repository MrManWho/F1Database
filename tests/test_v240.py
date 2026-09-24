"""v2.4: chosen weekend targets, weekend reset, recalculating everything, linked logins, settings sub-pages,
Team management and the round page."""

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import (auth, community, gates, impacts, recalc, relations, roles, services as S, storage, teamgoals,
                       teamlife, weekend)
from f1tracker import constants as C


def _league(master_client, logins=("ana", "ben")):
    for n in ("ana", "ben", "kim"):
        if not auth.get_user(n):
            auth.create_user(n, n.title(), "password1")
    res = master_client.post("/careers/new", data={"name": "V24", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": list(logins), "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        wil = conn.execute("SELECT id FROM teams WHERE name = 'Williams'").fetchone()["id"]
        S.place_players(conn, sid, {a: (wil, 1), b: (wil, 2)})
        roles.set_member(conn, "kim", "scorekeeper")
    pledge_all(token)
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _payload(conn, event, order=None):
    ids = [r["driver_id"] for r in S.weekend_rows(conn, event["id"])]
    order = order or ids
    return {"mark_complete": True, "ai_difficulty": 80, "results": [
        {"driver_id": d, "qualifying_position": order.index(d) + 1, "race_position": order.index(d) + 1,
         "status_override": "Auto", "sprint_position": order.index(d) + 1 if event["is_sprint"] else None,
         "sprint_status_override": "Auto", "fastest_lap": False, "driver_of_day": False, "notes": ""} for d in ids]}


# --------------------------------------------------------------------------- weekend targets: choose one of three

def test_three_targets_each_harder_than_the_last(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        teamlife.issue_targets(conn, ev["id"])
        opts = teamlife.options_for(conn, ev["id"], a)
        assert list(opts) == ["safe", "standard", "stretch"]
        assert opts["safe"]["hit"] < opts["standard"]["hit"] < opts["stretch"]["hit"]
        assert opts["safe"]["miss"] > opts["standard"]["miss"] > opts["stretch"]["miss"]
        pos = {k: o["target"] for k, o in opts.items() if o["kind"] in ("finish", "points", "classified")}
        if "safe" in pos and "standard" in pos:
            assert pos["safe"] > pos["standard"]
        if "stretch" in pos and "standard" in pos:
            assert pos["stretch"] < pos["standard"]
        assert len({o["label"] for o in opts.values()}) == 3
        # Stable: asking again gives the same three.
        assert teamlife.options_for(conn, ev["id"], a) == opts


@pytest.mark.gates
def test_choosing_locks_in_and_counts_its_own_reward(app, master_client):
    token, a, b = _league(master_client)
    ana, ben = _client(app, "ana"), _client(app, "ben")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    page = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Lock in Safe" in page and "Lock in Stretch" in page
    ana.post(f"/career/{token}/target/{ev['id']}/accept", data={"csrf_token": "tok", "tier": "stretch"})
    ana.post(f"/career/{token}/target/{ev['id']}/accept", data={"csrf_token": "tok", "tier": "safe"})   # can't change
    with storage.session(token) as conn:
        t = teamlife.target_for(conn, ev["id"], a)
        assert t["tier"] == "stretch" and t["hit"] == 3.5 and t["acknowledged_at"]
        gate = gates.status(conn, ev["id"])
        assert [i for p in gate["players"] if p["driver"]["id"] == b for i in p["checks"] if i["kind"] == "target"][0]["done"] is False
        # Ben never chooses: when the round is judged he raced for the Standard target.
        conn.execute("UPDATE target_options SET kind = 'classified', target = 22, label = 'Bring the car home' WHERE event_id = ?",
                     (ev["id"],))
        conn.execute("UPDATE weekend_targets SET kind = 'classified', target = 22 WHERE event_id = ?", (ev["id"],))
        run_event(conn, ev)
        teamlife.judge_targets(conn, ev["id"])
        tb = teamlife.target_for(conn, ev["id"], b)
        assert tb["tier"] == "standard" and tb["acknowledged_at"] is None and tb["status"] == "Hit"
        assert teamlife.target_for(conn, ev["id"], a)["effect"] == 3.5
        assert relations.assess(conn, S.current_season_id(conn), a)["bonus"] == 3.5


# --------------------------------------------------------------------------- reset a weekend

@pytest.mark.weekends
@pytest.mark.gates
def test_reset_weekend_puts_everything_back(app, master_client):
    token, a, b = _league(master_client)
    ana, ben, kim = _client(app, "ana"), _client(app, "ben"), _client(app, "kim")
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        ev = S.events(conn, sid)[0]
        before = {d: relations.assess(conn, sid, d)["bonus"] for d in (a, b)}
        before_standings = {r["driver_id"]: r["points"] for r in S.driver_standings(conn, sid)}
    kim.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    for client, did in ((ana, a), (ben, b)):
        with storage.session(token) as conn:
            pen = teamlife.prerace_pen(conn, S.get_event(conn, ev["id"]), did)
        for q in pen["questions"]:
            client.post(f"/career/{token}/weekend/{ev['id']}/prerace",
                        data={"csrf_token": "tok", "question": q["key"], "answer": q["answers"][0]["key"]})
        client.post(f"/career/{token}/target/{ev['id']}/accept", data={"csrf_token": "tok", "tier": "stretch"})
        client.post(f"/career/{token}/weekend/{ev['id']}/predict", data={"csrf_token": "tok", "pole": a, "winner": a})
    kim.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        order = [a, b] + [d for d in [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])] if d not in (a, b)]
        payload = _payload(conn, S.get_event(conn, ev["id"]), order)
    assert kim.post(f"/api/career/{token}/weekend/{ev['id']}", json=payload, headers={"X-CSRF-Token": "tok"}).get_json()["ok"]
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_COMPLETE
        assert relations.assess(conn, sid, a)["bonus"] != before[a]
        pens = teamlife.press_pens(conn, sid, a)
    for q in pens[-1]["questions"]:
        ana.post(f"/career/{token}/press/{ev['id']}", data={"csrf_token": "tok", "question": q["key"],
                                                              "answer": q["answers"][0]["key"]})
    # Only the Race Master, with a confirmation page, and typing the round.
    assert kim.get(f"/career/{token}/weekend/{ev['id']}/reset").status_code == 403
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}/reset").get_data(as_text=True)
    assert "What will be removed" in page and "Type <b>R1</b>" in page and "backup is saved first" in page
    master_client.post(f"/career/{token}/weekend/{ev['id']}/reset", data={"csrf_token": "tok", "confirm": "yes"})
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_COMPLETE             # not confirmed: nothing happened
    master_client.post(f"/career/{token}/weekend/{ev['id']}/reset", data={"csrf_token": "tok", "confirm": "R1"})
    with storage.session(token) as conn:
        e = S.get_event(conn, ev["id"])
        assert weekend.phase(e) == "upcoming" and e["paddock_at"] is None and e["ai_difficulty"] is None
        for table in ("press_answers", "weekend_targets", "target_options", "predictions"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE event_id = ?", (ev["id"],)).fetchone()[0] == 0, table
        assert {d: relations.assess(conn, sid, d)["bonus"] for d in (a, b)} == before
        assert {r["driver_id"]: r["points"] for r in S.driver_standings(conn, sid)} == before_standings
        assert not any(f"R1 " in (n["headline"] or "") and "paddock" in n["headline"].lower() for n in
                       conn.execute("SELECT headline FROM news").fetchall())
        assert any(n["title"] == "R1 was reset" for n in impacts.pending(conn, a, "ana"))
        assert "reset Round 1" in community.audit_entries(conn)[0]["summary"]
    assert any("before-reset-r1" in p.name for p in (storage.backups_dir() / "auto" / token).glob("*"))
    # And it runs again like new.
    kim.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert weekend.phase(S.get_event(conn, ev["id"])) == "paddock"
        assert len(teamlife.options_for(conn, ev["id"], a)) == 3


def test_only_the_latest_started_round_can_be_reset(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        run_event(conn, evs[0])
        run_event(conn, evs[1])
        assert "Reset that round first" in weekend.reset_blocker(conn, S.get_event(conn, evs[0]["id"]))
        assert weekend.reset_blocker(conn, S.get_event(conn, evs[1]["id"])) is None
        assert "hasn't started" in weekend.reset_blocker(conn, S.get_event(conn, evs[2]["id"]))
    page = master_client.get(f"/career/{token}/weekend/{evs[0]['id']}/reset").get_data(as_text=True)
    assert "can't be reset" in page


# --------------------------------------------------------------------------- recalculating

def test_recalculate_rebuilds_stored_numbers_and_changes_nothing_when_they_match(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        relations.ensure(conn, sid)
        for ev in S.events(conn, sid)[:3]:
            teamlife.issue_targets(conn, ev["id"])
            run_event(conn, ev)
            teamlife.after_race(conn, ev["id"])
        assert recalc.preview(conn) == {}                          # everything already matches
        right = relations.assess(conn, sid, a)["bonus"]
        conn.execute("UPDATE team_relations SET bonus = bonus + 7 WHERE driver_id = ?", (a,))   # out of step
        moved = recalc.preview(conn)
        assert a in moved and any(r["stat"] == "relationship" for r in moved[a])
        assert relations.assess(conn, sid, a)["bonus"] == right + 7   # preview kept nothing
    page = master_client.get(f"/career/{token}/recalculate").get_data(as_text=True)
    assert "What would change" in page and "Ana Silva" in page
    assert _client(app, "ana").get(f"/career/{token}/recalculate").status_code == 403
    master_client.post(f"/career/{token}/recalculate", data={"csrf_token": "tok", "history": "1"})
    with storage.session(token) as conn:
        assert relations.assess(conn, sid, a)["bonus"] == right
        assert any(n["title"] == "Numbers recalculated" for n in impacts.pending(conn, a, "ana"))
        assert storage.get_meta(conn, "recalculated_at")
    assert "League recalculated" in _client(app, "ben").get(f"/career/{token}/standings").get_data(as_text=True)


def test_reputation_chain_keeps_pledge_and_team_goal_rewards(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        teamgoals.set_enabled(conn, True)
        team = S.driver_seats(conn, sid)[a][0]
        teamgoals.choose(conn, sid, team, "safe", "david")
        for ev in S.events(conn, sid):
            run_event(conn, ev)
        new = S.create_next_season(conn, sid, 2027)
        changes = teamgoals.apply_rewards(conn, sid, new)
        relations.apply_rewards(conn, sid, new)
        start = S.starting_reputation(conn, new, a)
        recalc.reputation_chain(conn)
        assert S.starting_reputation(conn, new, a) == pytest.approx(start)
        assert changes    # the goal was settled and its reward is part of the chain


def test_a_formula_update_recalculates_the_league_and_tells_everyone(app, master_client, monkeypatch):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
    master_client.get(f"/career/{token}/dashboard")
    monkeypatch.setattr(C, "CALC_VERSION", C.CALC_VERSION + 1)
    monkeypatch.setitem(impacts.CALC_NOTES, C.CALC_VERSION, ("Test update", "Something is worked out differently."))
    page = _client(app, "ben").get(f"/career/{token}/standings").get_data(as_text=True)
    assert "Test update" in page and "Something is worked out differently." in page
    with storage.session(token) as conn:
        assert storage.get_meta(conn, "recalculated_at")
    ben = _client(app, "ben")
    ben.post(f"/career/{token}/league-notice", data={"csrf_token": "tok"})
    assert "Test update" not in ben.get(f"/career/{token}/standings").get_data(as_text=True)


# --------------------------------------------------------------------------- every player driver needs a login

@pytest.mark.weekends
def test_a_round_cant_open_until_every_player_driver_has_a_login_or_the_tick(app, master_client):
    token, a, b = _league(master_client, logins=("ana", ""))
    kim = _client(app, "kim")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        assert [p["id"] for p in weekend.unlinked_players(conn, S.current_season_id(conn))] == [b]
    res = kim.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"}, follow_redirects=True)
    assert "Ben Okafor has no login linked" in res.get_data(as_text=True)
    page = master_client.get(f"/career/{token}/members").get_data(as_text=True)
    assert "Needs a login" in page and "No account" in page
    assert kim.post(f"/career/{token}/members/no-account/{b}", data={"csrf_token": "tok", "on": "1"}).status_code == 403
    master_client.post(f"/career/{token}/members/no-account/{b}", data={"csrf_token": "tok", "on": "1"})
    kim.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert weekend.phase(S.get_event(conn, ev["id"])) == "paddock"


# --------------------------------------------------------------------------- pages

def test_settings_hub_and_pages_save_only_their_own_section(app, master_client):
    token, a, b = _league(master_client)
    hub = master_client.get(f"/career/{token}/settings").get_data(as_text=True)
    for title in ("Race weekends", "Career &amp; team", "Privacy &amp; sharing", "Data &amp; tools", "Team management"):
        assert title in hub
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "section": "privacy", "visibility": "private",
                                                          "discord_webhook": "https://discord.com/api/webhooks/1/abc",
                                                          "discord_results": "1"})
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "section": "career", "team_life": "1",
                                                          "feature_predictions": "1", "team_orders": "advisory"})
    res = master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "section": "weekends", "team_life": "1",
                                                                "round_gates": "1", "weekend_targets": "1"})
    assert res.headers["Location"].endswith("/settings/weekends")
    with storage.session(token) as conn:
        assert storage.get_meta(conn, "discord_webhook")                 # other pages' settings untouched
        assert community.features(conn)["predictions"]
        assert teamlife.settings(conn)["orders"] == "advisory"
        assert teamlife.settings(conn)["gates"] and not teamlife.settings(conn)["gate_press"]
    for sec in ("general", "weekends", "career", "roles", "privacy", "notifications", "data"):
        assert master_client.get(f"/career/{token}/settings/{sec}").status_code == 200
    assert master_client.get(f"/career/{token}/settings/nope").status_code == 404
    assert _client(app, "ana").get(f"/career/{token}/settings/weekends").status_code == 403


def test_team_management_holds_the_race_master_tools(app, master_client):
    token, a, b = _league(master_client)
    page = master_client.get(f"/career/{token}/team-management").get_data(as_text=True)
    assert "Pledges and season goals" in page and "Weekend targets" in page and "Team goals" in page
    assert _client(app, "ana").get(f"/career/{token}/team-management").status_code == 403
    standing = master_client.get(f"/career/{token}/team-standing?driver={a}").get_data(as_text=True)
    assert "Re-issue season goals" not in standing and "Team management" in standing
    master_client.post(f"/career/{token}/team-standing/{a}/goals", data={"csrf_token": "tok", "action": "reissue",
                                                                        "back": "admin", "anchor": "#drivers"})


def test_round_page_is_its_own_round(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert 'class="round-badge"' in page and 'data-tab="results"' in page and "Reset weekend" in page
    assert "Reset weekend" not in _client(app, "kim").get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)


# --------------------------------------------------------------------------- calculations check

def test_standings_add_up_from_the_raw_results(db, rng):
    """Every point in the driver and constructor standings comes from the published points tables, with DNFs,
    DNS, DSQs, Sprints and fastest laps mixed in (fastest lap scores nothing)."""
    sid = S.current_season_id(db)
    evs = S.events(db, sid)
    for ev in evs[:10]:
        ids = [r["driver_id"] for r in S.weekend_rows(db, ev["id"])]
        order = ids[:]
        rng.shuffle(order)
        over = {d: rng.choice(["DNF", "DNS", "DSQ"]) for d in rng.sample(ids, 3)}
        run_event(db, ev, order=order, overrides=over, sprint_order=list(reversed(order)),
                  sprint_overrides={order[-1]: "DNF"}, fl=order[0], dotd=order[1])
    drivers, teams = {}, {}
    for r in db.execute("""SELECT r.*, e.is_sprint FROM results r JOIN events e ON e.id = r.event_id
                           WHERE e.season_id = ?""", (sid,)):
        pts = S.gp_points(r["race_position"], r["result_status"]) + \
            S.sprint_points(r["sprint_position"], r["sprint_status"], bool(r["is_sprint"]))
        drivers[r["driver_id"]] = drivers.get(r["driver_id"], 0) + pts
        teams[r["team_id"]] = teams.get(r["team_id"], 0) + pts
    for row in S.driver_standings(db, sid):
        assert row["points"] == drivers.get(row["driver_id"], 0), row["driver_id"]
    for row in S.constructor_standings(db, sid):
        assert row["points"] == teams.get(row["team"]["id"], 0), row["team"]["name"]
    positions = [r["position"] for r in S.driver_standings(db, sid)]
    assert positions == sorted(positions)
    assert sum(drivers.values()) == sum(teams.values())
    assert S.gp_points(1, C.STATUS_FINISHED) == 25 and S.gp_points(1, "DNF") == 0
