"""v2.5: Calculation Version 3 and the Calculation Update for existing leagues (section 24 of the 2.5 brief)."""

import json
import math

import pytest

from conftest import after_submit, login, pledge_all, players, run_event
from f1tracker import (ai3, auth, calc3, engine, impacts, market, migration, relations, services as S, storage,
                       teamgoals, teamlife, ultimatums)
from f1tracker import constants as C

v3 = pytest.mark.engine3


# --------------------------------------------------------------------------- helpers

def _league(engine3=True, players_=("David Conley", "Carson Hayes"), teams=None, pending=False, rounds=None):
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "V25", 2026, list(players_))
        if not engine3:
            engine.set_league(conn, C.ENGINE_LEGACY, "pending" if pending else "new")
        sid = S.current_season_id(conn)
        ids = players(conn)
        if teams:
            seats, used = {}, set()
            for pid, t in zip(ids, teams):
                seat = (t, 1) if (t, 1) not in used else (t, 2)
                used.add(seat)
                seats[pid] = seat
            S.place_players(conn, sid, seats)
        if rounds is not None:
            for e in S.events(conn, sid)[rounds:]:
                S.delete_event(conn, e["id"])
    pledge_all(token)
    return token


def _team(conn, name):
    return conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()[0]


def _order(conn, ev, placed):
    """Finishing order with the given {driver_id: position}; everyone else fills the gaps in grid order."""
    ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
    rest = [d for d in ids if d not in placed]
    order = [None] * len(ids)
    for d, p in placed.items():
        order[p - 1] = d
    it = iter(rest)
    return [d if d else next(it) for d in order]


def _mate(conn, sid, did):
    seat = S.driver_seats(conn, sid)[did]
    return S.grid_map(conn, sid).get((seat[0], 2 if seat[1] == 1 else 1))


def _dump(conn):
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        out[t] = [tuple(r) for r in conn.execute(f"SELECT * FROM {t}")]
    return out


def _play(conn, sid, n, difficulty=84, seed=1, placed=None, start=0):
    import random
    rng = random.Random(seed)
    evs = S.events(conn, sid)
    for ev in evs[start:start + n]:
        if placed:
            order = _order(conn, ev, placed(ev) if callable(placed) else placed)
        else:
            order = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
            rng.shuffle(order)
        run_event(conn, ev, order=order, difficulty=difficulty)
        after_submit(conn, ev)
    return S.events(conn, sid)


# --------------------------------------------------------------------------- migration: never automatic

def test_existing_leagues_are_never_migrated_automatically(app, master_client):
    token = _league(engine3=False, pending=True)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        _play(conn, sid, 2)
        before = S.driver_standings(conn, sid)
    res = master_client.get(f"/career/{token}/dashboard")
    assert res.status_code == 302 and res.headers["Location"].endswith("/calculation-update")   # the Race Master chooses
    page = master_client.get(f"/career/{token}/calculation-update").get_data(as_text=True)
    assert "Recalculate this season" in page and "Use Version 3 from the next round" in page and "Decide later" in page
    with storage.session(token) as conn:
        assert engine.league_engine(conn) == C.ENGINE_LEGACY and engine.choice(conn) == "pending"
        assert not engine.is_v3(conn, sid)
        assert [r["form"] for r in S.driver_standings(conn, sid)] == [r["form"] for r in before]
    # Drivers never see the choice.
    auth.create_user("carson", "Carson", "password1")
    with storage.session(token) as conn:
        conn.execute("INSERT INTO career_members(username, driver_id, role) VALUES('carson', ?, 'member')",
                     (players(conn)[1],))
    c = app.test_client()
    login(c, "carson")
    assert "calculation-update" not in (c.get(f"/career/{token}/dashboard").headers.get("Location") or "")
    # Decide later: stays on Version 2 with a reminder the Race Master can hide.
    master_client.post(f"/career/{token}/calculation-update/later", data={"csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/standings").get_data(as_text=True)
    assert "Calculation Update waiting" in page
    with storage.session(token) as conn:
        assert engine.choice(conn) == "later" and engine.league_engine(conn) == C.ENGINE_LEGACY


@v3
def test_new_leagues_start_on_calculation_version_3():
    token = _league()
    with storage.session(token) as conn:
        assert engine.league_engine(conn) == 3 and engine.choice(conn) == "new" and not engine.needs_choice(conn)
        assert engine.is_v3(conn, S.current_season_id(conn))


# --------------------------------------------------------------------------- migration: full recalculation

def test_preview_changes_nothing_and_a_backup_exists_before_the_update(app, master_client):
    token = _league(engine3=False, pending=True, teams=(11, 6))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        _play(conn, sid, 5)
        dump = _dump(conn)
        result = migration.preview(conn)
        assert _dump(conn) == dump                    # previewing mutates nothing
        assert result["rows"]
    assert not any("before-calc-v3" in b["name"] for b in storage.list_auto_backups(token))
    page = master_client.post(f"/career/{token}/calculation-update/preview", data={"csrf_token": "tok"}).get_data(as_text=True)
    assert "Preview: recalculate this season" in page and "Backup saved first" in page
    backup = next(b["name"] for b in storage.list_auto_backups(token) if "before-calc-v3" in b["name"])
    with storage.session(token) as conn:
        assert engine.league_engine(conn) == C.ENGINE_LEGACY   # still nothing changed
    master_client.post(f"/career/{token}/calculation-update/full", data={"csrf_token": "tok", "confirm": "1",
                                                                         "backup": backup})
    with storage.session(token) as conn:
        m = migration.migrations(conn)[0]
        assert m["option"] == "full" and m["backup"] == backup and m["approved_by"] == "david"
        assert m["old_engine"] == 2 and m["new_engine"] == 3 and json.loads(m["before"]) and json.loads(m["after"])


def test_full_recalculation_rebuilds_the_season_and_tells_only_affected_drivers():
    token = _league(engine3=False, pending=True, players_=("David Conley", "Carson Hayes", "Pat Reserve"),
                    teams=(11, 6))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b, reserve = players(conn)
        S.place_players(conn, sid, {reserve: None})
        _play(conn, sid, 6)
        before = impacts.snapshot(conn)
        preview = migration.preview(conn)
        result = migration.apply_full(conn, "david", "x.f1career")
        assert engine.is_v3(conn, sid) and engine.cutoff(conn, sid) == 0 and engine.choice(conn) == "full"
        done = [e for e in S.events(conn, sid) if e["status"] == C.EVENT_COMPLETE]
        assert all(conn.execute("SELECT 1 FROM round_ranks WHERE event_id = ?", (e["id"],)).fetchone() for e in done)
        assert conn.execute("SELECT COUNT(*) FROM ai_recs").fetchone()[0] == len(done)
        kinds = {g["kind"] for g in conn.execute("SELECT kind FROM team_goals WHERE season_id = ?", (sid,))}
        assert kinds & {"finish", "points"}
        after = impacts.snapshot(conn)
        notices = migration.notices_for(conn, result["migration_id"])
        affected = {n["driver_id"] for n in notices}
        assert affected == set(impacts.diff(before, after)) and reserve not in affected   # nothing changed for them
        for n in notices:                                  # accurate before -> after, same as the preview showed
            shown = {c["stat"]: (c["before"], c["after"]) for c in n["changes"]}
            prev = next(r for r in preview["rows"] if r["driver"]["id"] == n["driver_id"])
            assert shown == {c["stat"]: (c["before"], c["after"]) for c in prev["changes"]}
            for stat, (was, now) in shown.items():
                assert before[str(n["driver_id"])].get(stat) == was and after[str(n["driver_id"])].get(stat) == now
        assert impacts.pending(conn, a, "someone")
        assert not impacts.pending(conn, reserve, "someone")


def test_personal_notice_shows_arrows_and_must_be_agreed(app, master_client):
    token = _league(engine3=False, pending=True, teams=(11, 6))
    auth.create_user("carson", "Carson", "password1")
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        conn.execute("INSERT INTO career_members(username, driver_id, role) VALUES('carson', ?, 'member')", (b,))
        _play(conn, sid, 5)
        migration.apply_full(conn, "david", None)
    c = app.test_client()
    login(c, "carson")
    res = c.get(f"/career/{token}/dashboard")
    assert res.headers["Location"].endswith("/changes")
    page = c.get(f"/career/{token}/changes").get_data(as_text=True)
    assert "Calculation Version 3: your numbers were recalculated" in page and "→" in page
    assert "Race results were not changed." in page
    c.post(f"/career/{token}/changes", data={"csrf_token": "tok", "agree": "1"})
    assert c.get(f"/career/{token}/dashboard").status_code == 200


def test_version_2_history_stays_reproducible_after_a_migration():
    token = _league(engine3=False, pending=True, teams=(11, 6))
    with storage.session(token) as conn:
        old = S.current_season_id(conn)
        _play(conn, old, 24)
        relations.settle(conn, old)
        new = S.create_next_season(conn, old, 2027)
        relations.carry_rewards(conn, old, new)
        _play(conn, new, 3, seed=2)
        history = [(r["driver_id"], r["points"], r["position"], r["form"], r["reputation"])
                   for r in S.driver_standings(conn, old)]
        cons = [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, old)]
        migration.apply_full(conn, "david", None)
        assert not engine.is_v3(conn, old) and engine.is_v3(conn, new)
        assert [(r["driver_id"], r["points"], r["position"], r["form"], r["reputation"])
                for r in S.driver_standings(conn, old)] == history
        assert [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, old)] == cons


def test_rollback_restores_the_league_from_the_update_backup(app, master_client):
    token = _league(engine3=False, pending=True)
    with storage.session(token) as conn:
        _play(conn, S.current_season_id(conn), 3)
    page = master_client.post(f"/career/{token}/calculation-update/preview", data={"csrf_token": "tok"}).get_data(as_text=True)
    backup = page.split("Backup saved first:</b> <code>")[1].split("</code>")[0]
    master_client.post(f"/career/{token}/calculation-update/full", data={"csrf_token": "tok", "confirm": "1", "backup": backup})
    with storage.session(token) as conn:
        assert engine.league_engine(conn) == 3
        mid = migration.migrations(conn)[0]["id"]
    master_client.post(f"/career/{token}/calculation-update/rollback/{mid}", data={"csrf_token": "tok", "confirm": "1"})
    with storage.session(token) as conn:
        assert engine.league_engine(conn) == 2 and engine.choice(conn) == "pending"
        assert not conn.execute("SELECT COUNT(*) FROM calc_migrations").fetchone()[0]


# --------------------------------------------------------------------------- migration: future only

def test_future_only_keeps_everything_until_new_evidence_arrives():
    token = _league(engine3=False, pending=True, teams=(11, 6))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        _play(conn, sid, 6)
        before = impacts.snapshot(conn)
        goals_before = [tuple(r) for r in conn.execute("SELECT * FROM team_goals WHERE season_id = ?", (sid,))]
        rel_before = [tuple(r) for r in conn.execute("SELECT growth, finish_target FROM team_relations")]
        result = migration.apply_future(conn, "david", None)
        assert result["cutoff"] == 6 and engine.cutoff(conn, sid) == 6 and engine.mixed(conn, sid)
        frozen = engine.frozen(conn, sid)
        for key in ("drivers", "ranks", "ai", "team_goals", "pledges"):
            assert key in frozen
        assert impacts.diff(before, impacts.snapshot(conn)) == {}      # nothing moves by choosing it
        assert "from round 7" in engine.label(conn, sid)
        rec = S.difficulty_recommendation(conn)
        assert rec["recommended"] == frozen["ai"]["recommended"] and rec.get("frozen")
        # a new round: engine 3 starts, blended in gradually
        _play(conn, sid, 1, start=6, seed=9)
        assert engine.blend_weight(conn, sid) == pytest.approx(1 / C.ENGINE_BLEND_ROUNDS)
        assert impacts.diff(before, impacts.snapshot(conn))          # now numbers may move
        assert [tuple(r) for r in conn.execute("SELECT * FROM team_goals WHERE season_id = ?", (sid,))] == goals_before
        assert [tuple(r) for r in conn.execute("SELECT growth, finish_target FROM team_relations")] == rel_before
        # rounds before the cutoff keep the ranks they were judged with
        first = S.events(conn, sid)[0]
        assert {r["source"] for r in conn.execute("SELECT source FROM round_ranks WHERE event_id = ?", (first["id"],))} == {"frozen"}
        new = S.create_next_season(conn, sid, 2027)
        assert engine.is_v3(conn, new) and not engine.mixed(conn, new)   # next season is fully Version 3


# --------------------------------------------------------------------------- results, points, countback

@v3
def test_classified_retirement_scores_and_reduced_distance_points():
    token = _league()
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        ev = S.events(conn, sid)[0]
        rows = S.weekend_rows(conn, ev["id"])
        order = [r["driver_id"] for r in rows]
        run_event(conn, ev, order=order, overrides={order[1]: "Classified", order[2]: "DNF"}, complete=False)
        pts = calc3.Points(conn)
        r = {x["driver_id"]: x for x in S.weekend_rows(conn, ev["id"])}
        assert pts.gp(r[order[1]]) == 18 and pts.gp(r[order[2]]) == 0        # classified keeps P2's points
        payload = {"gp_distance": "75", "results": []}
        S.save_weekend(conn, ev["id"], payload)
        r = {x["driver_id"]: x for x in S.weekend_rows(conn, ev["id"])}
        assert r[order[0]]["gp_points"] == 19 and r[order[1]]["gp_points"] == 14
        S.save_weekend(conn, ev["id"], {"gp_distance": "25", "results": []})
        assert S.weekend_rows(conn, ev["id"])[0]["gp_points"] in (6, 0)
        S.save_weekend(conn, ev["id"], {"gp_distance": "none", "results": []})
        assert sum(x["gp_points"] for x in S.weekend_rows(conn, ev["id"])) == 0
        S.save_weekend(conn, ev["id"], {"gp_distance": "manual",
                                        "results": [{"driver_id": order[0], "race_position": 1, "qualifying_position": 1,
                                                     "points_override": "7.5", "status_override": "Auto"}]})
        assert {x["driver_id"]: x["gp_points"] for x in S.weekend_rows(conn, ev["id"])}[order[0]] == 7.5
        # Sprint points need the minimum distance
        sprint = next(e for e in S.events(conn, sid) if e["is_sprint"])
        run_event(conn, sprint, complete=False)
        top = S.weekend_rows(conn, sprint["id"])
        assert max(x["sprint_pts"] for x in top) == 8
        S.save_weekend(conn, sprint["id"], {"sprint_distance": 40, "results": []})
        assert max(x["sprint_pts"] for x in S.weekend_rows(conn, sprint["id"])) == 0
        with pytest.raises(S.ValidationError):
            S.save_weekend(conn, ev["id"], {"gp_distance": "half", "results": []})


def test_version_2_rounds_do_not_offer_classified_retirements():
    token = _league(engine3=False)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        did = S.weekend_rows(conn, ev["id"])[0]["driver_id"]
        with pytest.raises(S.ValidationError):
            S.save_weekend(conn, ev["id"], {"results": [{"driver_id": did, "race_position": 1,
                                                         "status_override": "Classified"}]})


@v3
def test_full_position_countback_decides_ties():
    token = _league()
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = [e for e in S.events(conn, sid) if not e["is_sprint"]]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        x, y = ids[0], ids[1]
        # x: P2 + P2 (36 pts); y: P1 + P10 + P? -> make y 25 + 11? use P1 and P9 (25 + 2) and then P10 (1) ... equal
        run_event(conn, evs[0], order=_order(conn, evs[0], {x: 2, y: 1}))                    # x 18, y 25
        run_event(conn, evs[1], order=_order(conn, evs[1], {x: 2, y: 5}))                    # x 36, y 35
        run_event(conn, evs[2], order=_order(conn, evs[2], {x: 22, y: 10}))                  # x 36, y 36
        rows = {r["driver_id"]: r for r in S.driver_standings(conn, sid)}
        assert rows[x]["points"] == rows[y]["points"] == 36
        assert rows[y]["position"] < rows[x]["position"]      # y has a win: more P1 finishes decides it
        # Equal wins: next position decides, never the name
        assert calc3._countback_vector([{"result_status": "Finished", "race_position": 2, "qualifying_position": None}], 22) < \
            calc3._countback_vector([{"result_status": "Finished", "race_position": 3, "qualifying_position": None}], 22)


def test_explicit_rounding_at_every_half():
    for value, expected in ((0.5, 1), (1.5, 2), (2.5, 3), (12.5, 13), (13.5, 14), (-2.5, -3), (2.4999, 2)):
        assert engine.round_half_up(value) == expected
    assert engine.round_half_up(2.25, 1) == 2.3 and engine.round_half_up(2.35, 1) == 2.4
    assert engine.ceil_int(2.1) == 3 and engine.ceil_int(3.0) == 3 and engine.floor_int(12.5) == 12
    # ultimatum targets: E + 2 lands on .5 for every rank and must round up
    assert [min(20, engine.round_half_up(2 * r - 0.5 + 2)) for r in range(1, 12)] == [4, 6, 8, 10, 12, 14, 16, 18, 20, 20, 20]
    # season goals: ceil for "points in N races", floor only where a target is meant to be easier
    assert relations.goals_v3(1, 5, 22)[0][1] == 4           # ceil(5 x 0.75 = 3.75)
    assert relations.goals_v3(4, 5, 22)[0][1] == 3           # ceil(2.5) = 3, not banker's 2
    assert relations.goals_v3(7, 24, 22)[0][2] == 12         # floor(13.5 - 1) = 12


# --------------------------------------------------------------------------- car strength

@v3
def test_car_strength_blends_ratings_with_ai_evidence_and_old_rounds_keep_their_ranks():
    token = _league(teams=(11, 11))                            # both players at Cadillac: no AI driver there
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = _team(conn, "Cadillac")
        rr = calc3.rating_ranks(conn, sid)
        assert S.team_strength_ranks(conn, sid) == rr           # no evidence yet: rating rank
        evs = _play(conn, sid, 2)
        first = {r["team_id"]: r["rank"] for r in conn.execute("SELECT * FROM round_ranks WHERE event_id = ?",
                                                                 (evs[0]["id"],))}
        assert first == rr                                      # judged with what was known before it
        _play(conn, sid, 6, seed=5, start=2)
        scores, _ = calc3.rank_scores(conn, sid)
        assert scores[cad] == rr[cad]                           # a two-player team keeps its rating rank
        again = {r["team_id"]: r["rank"] for r in conn.execute("SELECT * FROM round_ranks WHERE event_id = ?",
                                                                 (evs[0]["id"],))}
        assert again == first                                   # later evidence never re-judges an old round


# --------------------------------------------------------------------------- Form, Reputation, value

@v3
def test_calendar_length_does_not_inflate_form():
    def form_after(rounds):
        token = _league(rounds=rounds, teams=(6, 6))
        with storage.session(token) as conn:
            sid = S.current_season_id(conn)
            a = players(conn)[0]
            _play(conn, sid, rounds, placed={a: 5})
            return {r["driver_id"]: r for r in S.driver_standings(conn, sid)}[a]["form"]
    assert form_after(6) == form_after(24)


@v3
def test_reputation_rises_with_a_good_season_and_falls_with_a_bad_one():
    token = _league(teams=(6, 6))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        _play(conn, sid, 8, placed={a: 2, b: 22})
        rows = {r["driver_id"]: r for r in S.driver_standings(conn, sid)}
        assert rows[a]["reputation"] > rows[a]["starting_reputation"]
        assert rows[b]["reputation"] < rows[b]["starting_reputation"]


@v3
def test_dns_is_never_a_teammate_loss_and_zero_comparisons_never_complete_a_goal():
    token = _league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        mate = _mate(conn, sid, a)
        evs = S.events(conn, sid)
        for ev in evs[:2]:
            run_event(conn, ev, order=_order(conn, ev, {mate: 1, a: 22}), overrides={a: "DNS"})
            after_submit(conn, ev)
        h = calc3.head_to_head(conn, sid, a)
        assert h["race_total"] == 0
        assert calc3.compare({"result_status": "DNS", "race_position": None}, {"result_status": "Finished", "race_position": 3}) is None
        goals = relations.assess(conn, sid, a)["goals"]
        mate_goal = next(g for g in goals if g["kind"] == "teammate")
        assert mate_goal["state"] == "Not evaluated"


# --------------------------------------------------------------------------- relationship and interest

@v3
def test_relationship_of_60_gives_no_bonus_and_on_track_goals_do_not_inflate_it():
    assert calc3.interest_bonus(60) == 0
    assert calc3.interest_bonus(90) == 6 and calc3.interest_bonus(0) == -8
    token = _league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        rel = conn.execute("SELECT * FROM team_relations WHERE driver_id = ?", (a,)).fetchone()
        assert relations.interest_bonus(conn, sid, a, rel["team_id"]) == 0
        assert relations.assess(conn, sid, a)["score"] == 60     # nothing raced: exactly neutral
        assert C.V3_GOAL_EFFECT["On track"] == 0


# --------------------------------------------------------------------------- goals

@v3
def test_lower_team_season_goals_are_achievable():
    field = 22
    expect = {5: 10, 6: 10, 7: 12, 8: 14, 9: 16, 10: 18, 11: 20}
    for rank, pos in expect.items():
        kind, n, position, _label = relations.goals_v3(rank, 24, field)[0]
        assert kind == "finish" and position == pos and n == math.ceil(24 * 0.3)
    for rank in (1, 2, 3, 4):
        assert relations.goals_v3(rank, 24, field)[0][0] == "points"


@v3
def test_team_goals_never_exceed_the_points_available_and_top_teams_can_reach_ambitious():
    token = _league(teams=(1, 2))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        teamgoals.set_enabled(conn, True)
        ranks = S.team_strength_ranks(conn, sid)
        top = min(ranks, key=ranks.get)
        second = sorted(ranks, key=ranks.get)[1]
        for team in (top, second):
            opts = teamgoals.options(conn, sid, team)
            amb = opts["options"]["ambitious"]
            max_left = sum(43 + (15 if e["is_sprint"] else 0) for e in S.events(conn, sid))
            assert amb["target_points"] <= math.floor(0.9 * max_left)
            assert amb["target_position"] in (1, 0) or amb["target_position"] >= 1
        amb_top = teamgoals.options(conn, sid, top)["options"]["ambitious"]
        assert amb_top["target_position"] == 1                   # clamped to P1, and P1 still completes it
        _play(conn, sid, 20)
        for team in ranks:
            for o in teamgoals.options(conn, sid, team)["options"].values():
                left = sum(43 + (15 if e["is_sprint"] else 0) for e in S.events(conn, sid) if e["status"] != C.EVENT_COMPLETE)
                earned = {t["team"]["id"]: t["points"] for t in S.constructor_standings(conn, sid)}[team]
                assert o["target_points"] <= earned + left


@v3
def test_weekend_target_difficulty_is_always_ordered():
    token = _league(teams=(6, 9))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        for ev in S.events(conn, sid)[:12]:
            for did in players(conn):
                seat = S.driver_seats(conn, sid)[did]
                opts = teamlife.target_options(conn, ev, did, seat[0])
                def need(t):
                    if t["kind"] == "teammate":
                        return relations.expected_finish(S.team_strength_ranks(conn, sid)[seat[0]])
                    if t["kind"] == "beat_team":
                        return relations.expected_finish(S.team_strength_ranks(conn, sid)[seat[0]] + 1) - 1.5
                    return t["target"]
                assert need(opts["stretch"]) <= need(opts["standard"]) <= need(opts["safe"])


# --------------------------------------------------------------------------- ultimatums, orders, press

@v3
def test_back_of_grid_ultimatums_need_p20_or_better():
    token = _league(teams=(10, 11))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        for name in ("Aston Martin", "Cadillac"):
            assert ultimatums._target_for(conn, sid, _team(conn, name)) == 20


@v3
def test_no_fault_dnf_voids_once_then_goes_to_the_race_master():
    token = _league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        evs = S.events(conn, sid)
        team = S.driver_seats(conn, sid)[a][0]
        ultimatums._table(conn)
        for i, ev in enumerate(evs[:2]):
            conn.execute("""INSERT INTO ultimatums(season_id, driver_id, team_id, event_id, target, label, created_at)
                            VALUES(?,?,?,?,?,?,?)""", (sid, a, team, ev["id"], 14, "Finish P14", "x"))
            run_event(conn, ev, order=_order(conn, ev, {a: 22}), overrides={a: "DNF"})
            conn.execute("UPDATE results SET no_fault = 1 WHERE event_id = ? AND driver_id = ?", (ev["id"], a))
            ultimatums.after_race(conn, ev["id"])
        states = [u["status"] for u in reversed(ultimatums.for_season(conn, sid, a))]
        assert states == ["Void", "Awaiting decision"]


@v3
def test_team_orders_are_ruled_never_inferred_and_press_counts_half():
    token = _league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        mate = _mate(conn, sid, a)
        teamlife.save_settings(conn, "on", True, False, False, False)
        ev = S.events(conn, sid)[0]
        conn.execute("INSERT INTO team_orders(event_id, driver_id, beneficiary_id, status, created_at) VALUES(?,?,?,?,?)",
                     (ev["id"], a, mate, "Issued", "x"))
        run_event(conn, ev, order=_order(conn, ev, {a: 3, mate: 8}))
        teamlife.resolve_orders(conn, ev["id"])
        assert conn.execute("SELECT status FROM team_orders").fetchone()[0] == "Awaiting ruling"
        extras, items = relations.extras_v3(conn, sid, a, S.driver_seats(conn, sid)[a][0])
        assert not any(i[2] == "team order" for i in items)            # finishing ahead proves nothing
        teamlife.rule_order(conn, ev["id"], a, "Ignored", "david")
        extras, items = relations.extras_v3(conn, sid, a, S.driver_seats(conn, sid)[a][0])
        assert ("team order" in [i[2] for i in items]) and C.V3_ORDER_IGNORED in [i[1] for i in items]
        from f1tracker import press
        assert press.effect_v3("win", "car", 2) == 1.0 and press.effect_v3("pre_expect", "struggle", -2) == 0
        assert "Every tenth matters when you're chasing performance" in [a_[1] for a_ in press.POST["fastest"][1]]


# --------------------------------------------------------------------------- market

@v3
def test_experienced_drivers_can_end_unsigned_and_rookies_can_start():
    token = _league(teams=(1, 11))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        wid = market.open_window(conn, sid, kind="Rookie Draft")
        assert conn.execute("SELECT COUNT(*) FROM offers WHERE window_id = ? AND driver_id = ?", (wid, a)).fetchone()[0] >= 1
        market.close_window(conn, wid)
        _play(conn, sid, 12, placed={a: 22, b: 21})
        for p in (a, b):                                         # make them clearly unwanted
            conn.execute("UPDATE season_driver_state SET starting_reputation = 5 WHERE driver_id = ?", (p,))
        wid = conn.execute("SELECT id FROM market_windows WHERE status = 'Open'").fetchone()
        wid = wid[0] if wid else market.open_window(conn, sid)
        for t in S.teams(conn):
            if not conn.execute("SELECT 1 FROM offers WHERE window_id = ? AND driver_id = ? AND team_id = ?",
                                (wid, a, t["id"])).fetchone() and market.approaches_left(conn, wid, a):
                market.approach_team(conn, wid, a, t["id"])
        offers = conn.execute("SELECT * FROM offers WHERE window_id = ? AND driver_id = ? AND status = ?",
                              (wid, a, C.OFFER_PENDING)).fetchall()
        assert not any(o["lifeline"] and o["stage"] == "Last-chance offer" for o in offers)
        assert not offers and market.career_status(conn, sid, a) == "Unsigned"


@v3
def test_negotiation_limits_and_message_rules():
    from f1tracker import pitch
    reading = pitch.analyse("win podium points loyal learn develop respect honoured")
    assert not reading["meaningful"]
    t = {"weights": {k: 1.0 for k in pitch.THEMES}, "tier": "top", "favourite": "results"}
    assert pitch.score(reading, t, v3=True) == 0.0
    full = pitch.analyse("I want to win races and I will learn from the engineers, and I'm loyal to this project.")
    assert full["meaningful"] and pitch.score(full, t, v3=True) <= round(2 / 2.2, 2)    # two themes at most
    token = _league(teams=(6, 9))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        _play(conn, sid, 13, placed={a: 3})                     # a driver teams want
        import random
        wid = market.open_window(conn, sid, rng=random.Random(4))
        offer = conn.execute("SELECT * FROM offers WHERE window_id = ? AND driver_id = ? AND status = ? AND final = 0",
                             (wid, a, C.OFFER_PENDING)).fetchone()
        assert offer
        if offer:
            conn.execute("UPDATE offers SET patience = 10 WHERE id = ?", (offer["id"],))
            for _ in range(C.V3_MAX_COUNTERS):
                o = market.get_offer(conn, offer["id"])
                if o["status"] != C.OFFER_PENDING or o["final"]:
                    break
                market.counter_offer(conn, offer["id"], "No. 1", 5, 0, "Give me everything")
            o = market.get_offer(conn, offer["id"])
            assert o["status"] == C.OFFER_PENDING and not o["final"]
            with pytest.raises(S.ValidationError):              # a fourth counter isn't allowed
                market.counter_offer(conn, offer["id"], "No. 1", 5, 0)
            assert o["patience"] < 10                            # every counter cost patience


# --------------------------------------------------------------------------- AI tracker

def _ai_league(mate_gap_s=None, player_pos=22, mate_pos=21, rounds=3, difficulty=86, flags=(), laps=50,
               single=True, second_pos=None):
    token = _league(players_=("David Conley",) if single else ("David Conley", "Carson Hayes"),
                    teams=(11,) if single else (11, 6))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        mate = _mate(conn, sid, a)
        evs = S.events(conn, sid)
        for ev in evs[:rounds]:
            placed = {a: player_pos, mate: mate_pos}
            if not single:
                b = players(conn)[1]
                placed[b] = second_pos
            run_event(conn, ev, order=_order(conn, ev, placed), difficulty=difficulty)
            if mate_gap_s is not None:
                form = {"race_gap": str(mate_gap_s), "laps": str(laps), "gap_to": "teammate"}
                for f in flags:
                    form[f"flag_{f}"] = "1"
                for session in ("gp", "sprint") if ev["is_sprint"] else ("gp",):
                    ai3.save_pace_input(conn, ev["id"], a, session, form, "david")
            after_submit(conn, ev)
        return token, sid, a


@v3
def test_ai_close_to_the_teammate_at_the_back_is_about_right():
    token, sid, a = _ai_league(mate_gap_s=2, player_pos=22, mate_pos=21, rounds=3)
    with storage.session(token) as conn:
        rec = S.difficulty_recommendation(conn)
        assert rec["engine"] == 3 and rec["recommended"] == 86 and rec["direction"] == "hold"


@v3
def test_ai_a_clean_thirty_second_deficit_is_a_meaningful_decrease():
    token, sid, a = _ai_league(mate_gap_s=30, player_pos=22, mate_pos=17, rounds=3)
    with storage.session(token) as conn:
        rec = S.difficulty_recommendation(conn)
        assert rec["recommended"] <= 86 - 3 and "seconds per lap" in rec["reason"]


@v3
def test_ai_moves_after_one_representative_weekend():
    token, sid, a = _ai_league(mate_gap_s=30, player_pos=22, mate_pos=15, rounds=1)
    with storage.session(token) as conn:
        rec = S.difficulty_recommendation(conn)
        assert rec["direction"] == "down" and 1 <= 86 - rec["recommended"] <= C.AI_EXTREME_STEP


@v3
def test_ai_ahead_of_the_teammate_in_the_slowest_car_is_an_increase():
    token, sid, a = _ai_league(mate_gap_s=-25, player_pos=15, mate_pos=21, rounds=3)
    with storage.session(token) as conn:
        assert S.difficulty_recommendation(conn)["direction"] == "up"


@v3
def test_ai_damage_and_mechanical_sessions_are_excluded():
    token, sid, a = _ai_league(mate_gap_s=60, player_pos=22, mate_pos=10, rounds=3, flags=("damage",))
    with storage.session(token) as conn:
        rec = S.difficulty_recommendation(conn)
        assert rec["recommended"] == 86 and not rec["sample"]
        assert any("damage" in (x["why"] or "") for x in rec["excluded"])
    token, sid, a = _ai_league(mate_gap_s=60, player_pos=22, mate_pos=10, rounds=2, flags=("mechanical",))
    with storage.session(token) as conn:
        assert not S.difficulty_recommendation(conn)["sample"]


@v3
def test_ai_one_ordinary_outlier_does_not_cause_a_large_reversal():
    token, sid, a = _ai_league(mate_gap_s=-20, player_pos=14, mate_pos=21, rounds=4)
    with storage.session(token) as conn:
        assert S.difficulty_recommendation(conn)["direction"] == "up"
        mate = _mate(conn, sid, a)
        ev = S.events(conn, sid)[4]
        run_event(conn, ev, order=_order(conn, ev, {a: 22, mate: 12}), difficulty=86)
        ai3.save_pace_input(conn, ev["id"], a, "gp", {"race_gap": "20", "laps": "50"}, "david")
        after_submit(conn, ev)
        rec = S.difficulty_recommendation(conn)
        assert rec["recommended"] >= 86 - 1 and rec.get("reversal") in (None, "damped")


@v3
def test_ai_personal_sweet_spots_stay_separate_for_each_player():
    token, sid, a = _ai_league(mate_gap_s=None, player_pos=22, mate_pos=12, rounds=3, single=False, second_pos=2)
    with storage.session(token) as conn:
        rec = S.difficulty_recommendation(conn)
        spots = {p["name"]: p["sweet_spot"] for p in rec["players"]}
        assert len(spots) == 2 and spots["David Conley"] < spots["Carson Hayes"]
        assert {p["verdict"] for p in rec["players"]} == {"struggling", "comfortable"}


@v3
def test_ai_sprints_are_their_own_half_weight_sample():
    token = _league(players_=("David Conley",), teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        sprint = next(e for e in S.events(conn, sid) if e["is_sprint"])
        run_event(conn, sprint, difficulty=80)
        after_submit(conn, sprint)
        sessions = ai3.history(conn)[-1]["sessions"]
        kinds = {x["session"]: x for x in sessions}
        assert set(kinds) == {"gp", "sprint"} and kinds["sprint"]["weight"] == pytest.approx(kinds["gp"]["weight"] * 0.5)


def test_pace_input_times_parse():
    assert ai3.parse_time("1:23.456") == 83.456 and ai3.parse_time("83,4") == 83.4 and ai3.parse_time("") is None
    with pytest.raises(ValueError):
        ai3.parse_time("fast")


# --------------------------------------------------------------------------- pages render on Version 3

@v3
def test_every_league_page_renders_on_a_version_3_league(app, master_client):
    for u in ("ana", "kim"):
        auth.create_user(u, u.title(), "password1")
    res = master_client.post("/careers/new", data={"name": "V3 pages", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva", "Ben Okafor"], "player_login": ["ana", ""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        S.place_players(conn, sid, {a: (11, 1), b: (6, 1)})
        from f1tracker import roles
        roles.set_member(conn, "kim", "scorekeeper")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('no_account_drivers', ?)", (str(b),))
    pledge_all(token)
    with storage.session(token) as conn:
        evs = _play(conn, sid, 4)
        ev = evs[0]
        ai3.save_pace_input(conn, ev["id"], a, "gp", {"quali_time": "1:30.100", "mate_quali_time": "1:29.800",
                                                      "race_gap": "12", "laps": "50", "flag_traffic": "1"}, "david")
    import re as _re
    checked = 0
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/career/<token>") or "GET" not in rule.methods or "<name>" in rule.rule:
            continue
        for filler in (evs[0]["id"], a):
            path = _re.sub(r"<int:[a-z_]+>", str(filler), rule.rule.replace("<token>", token))
            path = _re.sub(r"<(?!int:)[a-z_]+>", "x", path)
            r = master_client.get(path)
            assert r.status_code < 500, (path, r.status_code)
            checked += 1
    assert checked > 60
    page = master_client.get(f"/career/{token}/weekend/{evs[0]['id']}").get_data(as_text=True)
    assert "Pace &amp; conditions" in page and "Grand Prix distance" in page and "Classified retirement" in page
    kim = app.test_client()
    login(kim, "kim")
    r = kim.post(f"/career/{token}/weekend/{evs[0]['id']}/pace", data={"csrf_token": "tok", "driver_id": a, "session": "gp",
                                                                        "race_gap": "3", "laps": "40", "representative": "1"})
    assert r.status_code == 302
    with storage.session(token) as conn:
        p = ai3.pace_input(conn, evs[0]["id"], a, "gp")
        assert p["race_gap"] == 3 and p["representative"] is None      # only the Race Master decides that


@v3
def test_a_chaotic_wet_win_barely_moves_the_ai():
    clean, sid, a = _ai_league(mate_gap_s=-40, player_pos=1, mate_pos=21, rounds=1)
    wet, sid2, a2 = _ai_league(mate_gap_s=-40, player_pos=1, mate_pos=21, rounds=1, flags=("weather",))
    with storage.session(clean) as conn:
        up_clean = S.difficulty_recommendation(conn)["recommended"] - 86
    with storage.session(wet) as conn:
        up_wet = S.difficulty_recommendation(conn)["recommended"] - 86
    assert 0 <= up_wet < up_clean


@v3
def test_iron_man_needs_no_unexcused_dnf_and_no_dsq():
    from f1tracker import insights
    token = _league(teams=(6, 9))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        evs = S.events(conn, sid)
        for i, ev in enumerate(evs[:4]):
            over = {a: "DNF"} if i == 0 else ({b: "DSQ"} if i == 1 else {})
            run_event(conn, ev, order=_order(conn, ev, {a: 1, b: 2}), overrides=over)
        conn.execute("UPDATE results SET no_fault = 1 WHERE event_id = ? AND driver_id = ?", (evs[0]["id"], a))
        iron = next((x for x in insights.season_review(conn, sid)["awards"] if x["title"] == "Iron man"), None)
        assert iron is None or iron["driver"]["id"] not in (b,)
        names = {x["driver"]["id"] for x in insights.season_review(conn, sid)["awards"] if x["title"] == "Iron man"}
        assert b not in names
