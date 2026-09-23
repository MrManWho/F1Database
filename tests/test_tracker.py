import random
import sqlite3

import pytest
from markupsafe import escape

from conftest import driver_id, login, players, run_event
from f1tracker import auth, market, services as S, storage
from f1tracker import constants as C


def cadillac(conn):
    return conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]


def seat_players_at_cadillac(conn):
    sid = S.current_season_id(conn)
    david, carson = players(conn)
    cad = cadillac(conn)
    S.place_players(conn, sid, {david: (cad, 1), carson: (cad, 2)})
    return sid, david, carson, cad


# --------------------------------------------------------------------------- universe & grid

def test_new_career_seeds_universe_with_unassigned_players(db):
    assert db.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 11
    assert db.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == 24
    sid = S.current_season_id(db)
    gmap = S.grid_map(db, sid)
    assert len(gmap) == 22 and all(gmap.values())
    assert db.execute("SELECT COUNT(*) FROM events WHERE season_id = ?", (sid,)).fetchone()[0] == 24
    assert db.execute("SELECT COUNT(*) FROM events WHERE is_sprint = 1").fetchone()[0] == 6
    assert db.execute("SELECT COUNT(*) FROM season_driver_state").fetchone()[0] == 24
    seats = S.driver_seats(db, sid)
    for pid in players(db):
        assert pid not in seats


def test_players_replace_cadillac_and_same_seat_is_blocked(db):
    sid, david, carson, cad = seat_players_at_cadillac(db)
    gmap = S.grid_map(db, sid)
    assert gmap[(cad, 1)] == david and gmap[(cad, 2)] == carson
    seats = S.driver_seats(db, sid)
    assert driver_id(db, "Sergio Perez") not in seats and driver_id(db, "Valtteri Bottas") not in seats
    with pytest.raises(S.ValidationError):
        S.place_players(db, sid, {david: (1, 1), carson: (1, 1)})
    # Moving a player out refills the vacancy with the best unseated AI driver.
    S.place_players(db, sid, {david: None, carson: (cad, 2)})
    assert S.grid_map(db, sid)[(cad, 1)] == driver_id(db, "Sergio Perez")


def test_full_grid_swap_and_validation(db):
    sid = S.current_season_id(db)
    gmap = S.grid_map(db, sid)
    submitted = {k: str(v) for k, v in gmap.items()}
    submitted[(1, 1)], submitted[(3, 1)] = submitted[(3, 1)], submitted[(1, 1)]
    S.save_full_grid(db, sid, submitted)
    assert S.grid_map(db, sid)[(1, 1)] == gmap[(3, 1)]
    bad = dict(submitted)
    bad[(2, 1)] = bad[(2, 2)]
    with pytest.raises(S.ValidationError):
        S.save_full_grid(db, sid, bad)
    bad = dict(submitted)
    bad[(2, 1)] = ""
    with pytest.raises(S.ValidationError):
        S.save_full_grid(db, sid, bad)


# --------------------------------------------------------------------------- scoring

def test_race_scoring_statuses_awards_and_standings(db):
    sid = S.current_season_id(db)
    event = S.events(db, sid)[0]
    rows = S.weekend_rows(db, event["id"])
    ids = [r["driver_id"] for r in rows]
    winner, second, dnf_driver = ids[0], ids[1], ids[2]
    res = run_event(db, event, overrides={dnf_driver: "DNF"}, fl=second, dotd=winner)
    assert res["complete"]
    table = {r["driver_id"]: r for r in S.driver_standings(db, sid)}
    assert table[winner]["points"] == 25 and table[winner]["wins"] == 1 and table[winner]["poles"] == 1
    assert table[second]["points"] == 18 and table[second]["fastest_laps"] == 1  # no FL point
    assert table[dnf_driver]["points"] == 0 and table[dnf_driver]["dnfs"] == 1
    assert table[dnf_driver]["podiums"] == 0 and table[dnf_driver]["starts"] == 1
    assert table[winner]["position"] == 1
    teams = S.constructor_standings(db, sid)
    assert sum(t["points"] for t in teams) == sum(C.GP_POINTS.values()) - 15


def test_sprint_points_are_independent_of_gp_status(db):
    sid = S.current_season_id(db)
    sprint = next(e for e in S.events(db, sid) if e["is_sprint"])
    ids = [r["driver_id"] for r in S.weekend_rows(db, sprint["id"])]
    a, b = ids[2], ids[4]  # sprint P3 / GP DNF   and   sprint DNF / GP P5
    run_event(db, sprint, overrides={a: "DNF"}, sprint_overrides={b: "DNF"})
    table = {r["driver_id"]: r for r in S.driver_standings(db, sid)}
    assert table[a]["sprint_points"] == 6 and table[a]["gp_points"] == 0 and table[a]["dnfs"] == 1
    assert table[b]["sprint_points"] == 0 and table[b]["gp_points"] == 10 and table[b]["dnfs"] == 0


def test_duplicates_multiple_awards_and_completion_blocked(db):
    sid = S.current_season_id(db)
    event = S.events(db, sid)[0]
    ids = [r["driver_id"] for r in S.weekend_rows(db, event["id"])]
    with pytest.raises(S.ValidationError, match="same race position"):
        S.save_weekend(db, event["id"], {"results": [
            {"driver_id": ids[0], "race_position": 1}, {"driver_id": ids[1], "race_position": 1}]})
    with pytest.raises(S.ValidationError, match="Fastest Lap"):
        S.save_weekend(db, event["id"], {"results": [
            {"driver_id": ids[0], "fastest_lap": True}, {"driver_id": ids[1], "fastest_lap": True}]})
    with pytest.raises(S.ValidationError):
        S.save_weekend(db, event["id"], {"results": [{"driver_id": ids[0], "race_position": 23}]})
    with pytest.raises(S.ValidationError, match="21 GP results"):
        S.save_weekend(db, event["id"], {"results": [{"driver_id": ids[0], "race_position": 1}],
                                         "mark_complete": True})
    res = S.save_weekend(db, event["id"], {"results": [{"driver_id": ids[0], "race_position": 1}]})
    assert res["status"] == C.EVENT_IN_PROGRESS


def test_old_v1_save_migrates_without_losing_sprint_points(career):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        sprint = next(e for e in S.events(conn, sid) if e["is_sprint"])
        run_event(conn, sprint)
        winner = S.driver_standings(conn, sid)[0]
        before = winner["points"]
    path = storage.career_path(career)
    raw = sqlite3.connect(str(path))
    for table in ("offers", "market_windows", "career_members"):
        raw.execute(f"DROP TABLE {table}")
    raw.execute("ALTER TABLE results DROP COLUMN sprint_status")
    raw.execute("ALTER TABLE events DROP COLUMN ai_difficulty")
    raw.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()
    with storage.session(career) as conn:
        assert storage.get_meta(conn, "schema_version") == str(C.SCHEMA_VERSION)
        after = next(r for r in S.driver_standings(conn, sid) if r["driver_id"] == winner["driver_id"])
        assert after["points"] == before and after["sprint_points"] == 8
        assert conn.execute("SELECT ai_difficulty FROM events LIMIT 1").fetchone()[0] is None


# --------------------------------------------------------------------------- AI difficulty

def _player_rounds(conn, finishes, difficulty, season_id=None, start=0):
    """Run rounds where both players finish at the given positions (tuples)."""
    sid = season_id or S.current_season_id(conn)
    evs = S.events(conn, sid)
    david, carson = players(conn)
    for i, (pd, pc) in enumerate(finishes):
        event = evs[start + i]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, event["id"])]
        others = [d for d in ids if d not in (david, carson)]
        order = list(others)
        for pid, pos in sorted(((david, pd), (carson, pc)), key=lambda x: x[1]):
            order.insert(pos - 1, pid)
        run_event(conn, event, order=order, difficulty=difficulty)
    return start + len(finishes)


def test_difficulty_waits_for_three_rounds_then_moves_one(db):
    seat_players_at_cadillac(db)
    assert S.difficulty_recommendation(db)["recommended"] is None
    nxt = _player_rounds(db, [(1, 2), (1, 3)], 90)
    rec = S.difficulty_recommendation(db)
    assert rec["recommended"] == 90 and rec["direction"] == "hold"
    _player_rounds(db, [(2, 1)], 90, start=nxt)
    rec = S.difficulty_recommendation(db)
    assert rec["recommended"] == 91 and rec["direction"] == "up"


def test_one_bad_round_is_only_noted(db):
    seat_players_at_cadillac(db)
    nxt = _player_rounds(db, [(8, 9), (9, 10), (7, 9)], 95)
    before = S.difficulty_recommendation(db)
    nxt = _player_rounds(db, [(22, 21)], 95, start=nxt)
    rec = S.difficulty_recommendation(db)
    assert rec["recommended"] == 95
    assert rec["note"] and "tough" in rec["note"]
    assert before["recommended"] == 95


def test_double_dnf_rounds_do_not_force_reduction(db):
    sid, david, carson, _ = seat_players_at_cadillac(db)
    evs = S.events(db, sid)
    for event in evs[:4]:
        run_event(db, event, overrides={david: "DNF", carson: "DNF"}, difficulty=100)
    rec = S.difficulty_recommendation(db)
    assert rec["recommended"] == 100 and rec["direction"] == "hold" and not rec["sample"]


def test_mixed_results_hold(db):
    seat_players_at_cadillac(db)
    _player_rounds(db, [(1, 2), (20, 21), (1, 2), (21, 20)], 90)
    rec = S.difficulty_recommendation(db)
    assert rec["recommended"] == 90


def test_difficulty_history_carries_across_seasons(db):
    sid, *_ = seat_players_at_cadillac(db)
    _player_rounds(db, [(1, 2), (2, 1)], 88)
    new_id = S.create_next_season(db, sid, 2027)
    assert all(e["ai_difficulty"] is None for e in S.events(db, new_id))
    _player_rounds(db, [(1, 3)], 88, season_id=new_id)
    rec = S.difficulty_recommendation(db)
    assert len(rec["sample"]) == 3 and rec["recommended"] == 89
    assert rec["sweet_spot"]["seasons"] == 2 and rec["sweet_spot"]["value"] > 88


# --------------------------------------------------------------------------- seasons & reputation

def test_new_season_keeps_results_and_carries_reputation(db):
    sid = S.current_season_id(db)
    run_event(db, S.events(db, sid)[0])
    leader = S.driver_standings(db, sid)[0]
    new_id = S.create_next_season(db, sid, 2027)
    assert S.get_season(db, sid)["status"] == C.SEASON_COMPLETE
    assert S.driver_standings(db, sid)[0]["points"] == leader["points"]
    start = S.starting_reputation(db, new_id, leader["driver_id"])
    assert start == leader["reputation"] > leader["starting_reputation"]
    with pytest.raises(S.ValidationError):
        S.create_next_season(db, new_id, 2027)


def test_inactive_driver_keeps_earned_reputation(db):
    sid = S.current_season_id(db)
    run_event(db, S.events(db, sid)[0])
    perez = driver_id(db, "Sergio Perez")
    earned = next(r for r in S.driver_standings(db, sid) if r["driver_id"] == perez)["reputation"]
    s2 = S.create_next_season(db, sid, 2027)
    david, _ = players(db)
    S.place_players(db, s2, {david: S.driver_seats(db, s2)[perez]})
    assert perez not in S.driver_seats(db, s2)
    s3 = S.create_next_season(db, s2, 2028)
    assert S.starting_reputation(db, s3, perez) == earned != C.BASELINE_REPUTATION["Sergio Perez"]


def test_constructor_points_survive_grid_edits(db):
    sid = S.current_season_id(db)
    event = S.events(db, sid)[0]
    rows = S.weekend_rows(db, event["id"])
    winner = rows[0]
    run_event(db, event)
    before = {t["team"]["id"]: t["points"] for t in S.constructor_standings(db, sid)}
    gmap = S.grid_map(db, sid)
    submitted = {k: str(v) for k, v in gmap.items()}
    submitted[(1, 1)], submitted[(11, 1)] = submitted[(11, 1)], submitted[(1, 1)]
    S.save_full_grid(db, sid, submitted)
    after = {t["team"]["id"]: t["points"] for t in S.constructor_standings(db, sid)}
    assert after == before
    assert db.execute("SELECT team_id FROM results WHERE event_id = ? AND driver_id = ?",
                      (event["id"], winner["driver_id"])).fetchone()[0] == winner["team_id"]
    later = S.events(db, sid)[1]
    assert db.execute("SELECT team_id FROM results WHERE event_id = ? AND driver_id = ?",
                      (later["id"], winner["driver_id"])).fetchone()[0] == 11


def test_calendar_round_swap_is_atomic(db):
    sid = S.current_season_id(db)
    evs = S.events(db, sid)
    entries = [dict(e) for e in evs]
    entries[0]["round_number"], entries[1]["round_number"] = 2, 1
    S.save_calendar(db, sid, entries)
    assert S.events(db, sid)[0]["name"] == "Chinese GP"


def test_save_as_is_independent(career):
    copy = storage.save_as(career, "Copy")
    with storage.session(copy) as conn:
        conn.execute("UPDATE events SET name = 'Changed' WHERE round_number = 1")
    with storage.session(career) as conn:
        assert conn.execute("SELECT name FROM events WHERE round_number = 1").fetchone()[0] == "Australian GP"
        assert storage.get_meta(conn, "career_id") == career


# --------------------------------------------------------------------------- transfer market

def test_rookie_draft_offers_come_from_backmarkers_and_signing_places_player(db, rng):
    sid = S.current_season_id(db)
    window = market.open_window(db, sid, rng=rng)
    assert db.execute("SELECT kind, target_year FROM market_windows WHERE id = ?", (window,)).fetchone()[:] == \
        ("Rookie Draft", 2026)
    david, carson = players(db)
    offers = market.offers(db, driver_id=david)
    assert len(offers) == C.ROOKIE_OFFERS
    assert all(o["team_id"] >= 7 for o in offers)  # bottom five of the default order
    chosen = offers[0]
    market.accept_offer(db, chosen["id"])
    assert S.driver_seats(db, sid)[david][0] == chosen["team_id"]
    statuses = {o["id"]: o["status"] for o in market.offers(db, driver_id=david)}
    assert statuses[chosen["id"]] == C.OFFER_ACCEPTED
    assert all(s == C.OFFER_WITHDRAWN for oid, s in statuses.items() if oid != chosen["id"])
    assert len(S.weekend_rows(db, S.events(db, sid)[0]["id"])) == 22
    with pytest.raises(S.ValidationError):
        market.accept_offer(db, offers[1]["id"])


def test_strong_season_attracts_better_teams_and_applies_next_year(db):
    sid, david, carson, cad = seat_players_at_cadillac(db)
    evs = S.events(db, sid)
    for event in evs[:12]:
        ids = [r["driver_id"] for r in S.weekend_rows(db, event["id"])]
        order = [david] + [d for d in ids if d not in (david, carson)] + [carson]
        run_event(db, event, order=order, difficulty=90)
    window = market.maybe_open_silly_season(db, sid)
    assert window is not None
    assert market.maybe_open_silly_season(db, sid) is None
    david_offers = market.offers(db, driver_id=david, window_id=window)
    carson_offers = market.offers(db, driver_id=carson, window_id=window)
    best_rank = min(S.team_strength_ranks(db, sid)[o["team_id"]] for o in david_offers)
    assert best_rank <= 3
    assert len(carson_offers) >= 1
    _, interest = market.team_interest(db, sid, david)
    assert interest[0]["label"] in ("Keen", "Interested")
    top = min(david_offers, key=lambda o: S.team_strength_ranks(db, sid)[o["team_id"]])
    market.accept_offer(db, top["id"])
    assert S.driver_seats(db, sid)[david][0] == cad  # still racing for Cadillac this year
    new_id = S.create_next_season(db, sid, 2027)
    market.on_new_season(db, new_id)
    assert S.driver_seats(db, new_id)[david][0] == top["team_id"]
    assert market.current_contract(db, david)["team_id"] == top["team_id"]
    assert db.execute("SELECT status FROM market_windows WHERE id = ?", (window,)).fetchone()[0] == C.WINDOW_CLOSED


# --------------------------------------------------------------------------- web

def test_login_is_required_and_setup_runs_first(app):
    client = app.test_client()
    assert client.get("/").headers["Location"].endswith("/setup")
    client.get("/setup")
    with client.session_transaction() as sess:
        csrf = sess["csrf"]
    client.post("/setup", data={"username": "david", "password": "password1", "csrf_token": csrf})
    assert auth.get_user("david")["is_master"] == 1
    other = app.test_client()
    assert "/login" in other.get("/").headers["Location"]


def test_every_major_page_returns_successfully(master_client, data_dir):
    res = master_client.post("/careers/new", data={"name": "Web", "year": "2026", "rookie_market": "1",
                                                   "account1": "david", "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        event = S.events(conn, S.current_season_id(conn))[0]
        team_id, driver = 1, 1
        ids = [r["driver_id"] for r in S.weekend_rows(conn, event["id"])]
    for path in ["/", "/accounts", f"/career/{token}/dashboard", f"/career/{token}/weekend/{event['id']}",
                 f"/career/{token}/drivers", f"/career/{token}/driver/{driver}", f"/career/{token}/teams",
                 f"/career/{token}/team/{team_id}", f"/career/{token}/grid", f"/career/{token}/contracts",
                 f"/career/{token}/records", f"/career/{token}/seasons", f"/career/{token}/garage",
                 f"/career/{token}/market", f"/career/{token}/members", f"/career/{token}/export"]:
        assert master_client.get(path).status_code == 200, path
    assert master_client.get(f"/career/{token}/backup").status_code == 200
    res = master_client.post(f"/api/career/{token}/weekend/{event['id']}",
                             json={"results": [{"driver_id": ids[0], "race_position": 1}], "ai_difficulty": 90},
                             headers={"X-CSRF-Token": "tok"})
    assert res.get_json()["ok"] and res.get_json()["ai_difficulty"] == 90
    bad = master_client.post(f"/api/career/{token}/weekend/{event['id']}", json={"results": []})
    assert bad.status_code == 400  # missing CSRF token


def test_players_only_see_their_own_career_and_offers(app, master_client):
    auth.create_user("carson", "Carson", "password1")
    auth.create_user("stranger", "Nobody", "password1")
    res = master_client.post("/careers/new", data={"name": "Two", "year": "2026", "rookie_market": "1",
                                                   "account1": "david", "account2": "carson", "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        david, carson = players(conn)
        david_offer = market.offers(conn, driver_id=david)[0]
        carson_offer = market.offers(conn, driver_id=carson)[0]
        event = S.events(conn, S.current_season_id(conn))[0]

    carson_client = app.test_client()
    login(carson_client, "carson")
    page = carson_client.get(f"/career/{token}/garage").get_data(as_text=True)
    assert "Carson Hayes" in page and str(escape(carson_offer["reason"])) in page
    assert carson_client.get(f"/career/{token}/garage?driver={david}").get_data(as_text=True).count("David Conley") <= 1
    assert carson_client.post(f"/career/{token}/offers/{david_offer['id']}/accept",
                              data={"csrf_token": "tok"}).status_code == 403
    assert carson_client.post(f"/api/career/{token}/weekend/{event['id']}", json={"results": []},
                              headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert carson_client.post(f"/career/{token}/grid/save", data={"csrf_token": "tok"}).status_code == 403
    assert carson_client.get(f"/career/{token}/weekend/{event['id']}").status_code == 200
    carson_client.post(f"/career/{token}/offers/{carson_offer['id']}/accept", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert S.driver_seats(conn, S.current_season_id(conn))[carson][0] == carson_offer["team_id"]

    stranger = app.test_client()
    login(stranger, "stranger")
    assert stranger.get(f"/career/{token}/dashboard").status_code == 403
    assert token not in stranger.get("/").get_data(as_text=True)
