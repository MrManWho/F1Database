import random
import sqlite3

import pytest
from markupsafe import escape

from conftest import driver_id, login, players, pledge_all, run_event
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
                                         "mark_complete": True, "ai_untracked": True})
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
    backups = list(storage.backups_dir().glob(f"{career}-before-v{C.SCHEMA_VERSION}-upgrade-*"))
    assert len(backups) == 1
    old = sqlite3.connect(str(backups[0]))
    assert old.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "1"
    old.close()
    with storage.session(career):
        pass
    assert len(list(storage.backups_dir().glob(f"{career}-before-*"))) == 1  # only once


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
    # v2.0: a first-time visitor sees the welcome page; anything inside still needs a login.
    welcome = other.get("/")
    assert welcome.status_code == 200 and "Log in" in welcome.get_data(as_text=True)
    assert "/login" in other.get("/accounts").headers["Location"]


def test_every_major_page_returns_successfully(master_client, data_dir):
    res = master_client.post("/careers/new", data={"name": "Web", "year": "2026", "rookie_market": "1",
                                                   "player_name": ["David Conley", "Carson Hayes"], "player_login": ["david", ""], "csrf_token": "tok"})
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
                                                   "player_name": ["David Conley", "Carson Hayes"], "player_login": ["david", "carson"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        david, carson = players(conn)
        david_offer = market.offers(conn, driver_id=david)[0]
        carson_offer = market.offers(conn, driver_id=carson)[0]
        event = S.events(conn, S.current_season_id(conn))[0]

    carson_client = app.test_client()
    login(carson_client, "carson")
    page = carson_client.get(f"/career/{token}/offers").get_data(as_text=True)
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


# --------------------------------------------------------------------------- negotiations (v1.4)

def _rookie_window(db, rng):
    sid = S.current_season_id(db)
    window = market.open_window(db, sid, rng=rng)
    david, carson = players(db)
    return sid, window, david, carson


def test_reasonable_counter_is_agreed_then_signed(db, rng):
    sid, window, david, _ = _rookie_window(db, rng)
    offer = market.offers(db, driver_id=david)[0]
    assert offer["growth"] is not None and offer["ceiling_role"] == "No. 2" and offer["max_years"] <= 3
    assert offer["min_growth"] >= 1  # teams sign rookies to develop them
    pledge = market.growth_needed(offer["min_growth"], "No. 2", offer["min_years"])  # exactly what they need
    result = market.counter_offer(db, offer["id"], "No. 2", offer["min_years"], pledge, rng=rng)
    assert result == "agreed"
    agreed = market.get_offer(db, offer["id"])
    assert agreed["final"] and agreed["stage"] == "Terms agreed" and agreed["growth"] == pledge
    with pytest.raises(S.ValidationError, match="final offer"):
        market.counter_offer(db, offer["id"], "No. 2", 1, 0, rng=rng)
    market.accept_offer(db, offer["id"])
    assert S.driver_seats(db, sid)[david][0] == offer["team_id"]
    authors = [m["author"] for m in market.offers(db, driver_id=david)[0]["messages"]]
    assert authors[:3] == ["team", "driver", "team"]


def test_rookies_cannot_demand_number_one_and_greed_ends_talks(db, rng):
    _sid, window, david, _ = _rookie_window(db, rng)
    offers = market.offers(db, driver_id=david)
    first = offers[0]
    result = market.counter_offer(db, first["id"], "No. 1", 5, 0, rng=rng)
    assert result == "final"  # a greedy ask burns two rounds of patience at once
    assert market.get_offer(db, first["id"])["role"] == "No. 2"
    with pytest.raises(S.ValidationError, match="final offer"):
        market.counter_offer(db, first["id"], "No. 1", 5, 0, rng=rng)

    second = offers[1]
    result = market.counter_offer(db, second["id"], "Equal Status", 2, 3, rng=rng)
    assert result == "countered"  # even a Breakout pledge can't buy a rookie better status
    countered = market.get_offer(db, second["id"])
    assert countered["role"] == "No. 2" and countered["growth"] == 3
    result = market.counter_offer(db, second["id"], "No. 1", 5, 0, rng=rng)
    assert result == "collapsed" and market.get_offer(db, second["id"])["status"] == C.OFFER_COLLAPSED


def test_low_pledge_is_countered_and_big_pledge_buys_leverage(db, rng):
    sid = S.current_season_id(db)
    david, _ = players(db)
    window = market.open_window(db, sid, rng=rng)
    offer = market.offers(db, driver_id=david)[0]
    # Pretend this is an experienced driver whose team is lukewarm: No. 2 ceiling, 1-2 years, needs a Solid pledge.
    db.execute("UPDATE offers SET ceiling_role = 'No. 2', min_years = 1, max_years = 2, min_growth = 1, patience = 3, "
               "final = 0 WHERE id = ?", (offer["id"],))
    orig = market.experience
    market.experience = lambda conn, did: "Established"
    try:
        assert market.counter_offer(db, offer["id"], "No. 2", 1, 0, rng=rng) == "countered"
        o = market.get_offer(db, offer["id"])
        assert o["growth"] == 1 and "Solid season" in market.offers(db, driver_id=david)[0]["messages"][-1]["message"]
        # Two levels over what Equal Status needs (1) = Breakout: status one step past the ceiling, plus an extra year.
        assert market.counter_offer(db, offer["id"], "Equal Status", 3, 3, rng=rng) == "agreed"
        o = market.get_offer(db, offer["id"])
        assert (o["role"], o["years"], o["growth"]) == ("Equal Status", 3, 3)
    finally:
        market.experience = orig


def test_approaches_are_judged_limited_and_lifeline_when_out_of_options(db, rng):
    sid, window, david, _ = _rookie_window(db, rng)
    mclaren = 1
    offer_id, result = market.approach_team(db, window, david, mclaren, rng=rng)
    assert result == "rejected"
    with pytest.raises(S.ValidationError):
        market.approach_team(db, window, david, mclaren, rng=rng)  # once per team per window
    talked = {o["team_id"] for o in market.offers(db, driver_id=david)}
    backmarker = next(t for t in (7, 8, 9, 10, 11) if t not in talked)
    offer_id, result = market.approach_team(db, window, david, backmarker, rng=rng)
    assert result == "offer" and market.get_offer(db, offer_id)["origin"] == "driver"
    offer_id, result = market.approach_team(db, window, david, 2, rng=rng)
    assert result == "rejected" and market.approaches_left(db, window, david) == 0
    with pytest.raises(S.ValidationError, match="approaches"):
        market.approach_team(db, window, david, 3, rng=rng)
    for o in market.offers(db, driver_id=david):
        if o["status"] == C.OFFER_PENDING and not o["lifeline"]:
            market.decline_offer(db, o["id"], rng=rng)
    lifelines = [o for o in market.offers(db, driver_id=david) if o["lifeline"]]
    assert len(lifelines) == 1 and lifelines[0]["status"] == C.OFFER_PENDING and lifelines[0]["final"]
    market.decline_offer(db, lifelines[0]["id"], rng=rng)
    assert len([o for o in market.offers(db, driver_id=david) if o["lifeline"]]) == 1  # only one lifeline


def test_v4_offers_migrate_and_can_be_negotiated(career, rng):
    with storage.session(career) as conn:
        _sid, _window, david, _ = _rookie_window(conn, rng)
        offer_id = market.offers(conn, driver_id=david)[0]["id"]
    raw = sqlite3.connect(str(storage.career_path(career)))
    raw.execute("DROP TABLE offer_messages")
    for column in ("salary", "origin", "stage", "patience", "final", "lifeline", "ceiling_role", "min_years",
                   "max_years", "max_salary", "growth", "min_growth"):
        raw.execute(f"ALTER TABLE offers DROP COLUMN {column}")
    raw.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()
    with storage.session(career) as conn:
        assert market.get_offer(conn, offer_id)["growth"] is None
        result = market.counter_offer(conn, offer_id, "No. 2", 1, 3, rng=rng)
        assert result == "agreed"
        assert market.get_offer(conn, offer_id)["min_growth"] is not None


def test_garage_negotiation_routes(app, master_client):
    res = master_client.post("/careers/new", data={"name": "Talks", "year": "2026", "rookie_market": "1",
                                                   "player_name": ["David Conley", "Carson Hayes"], "player_login": ["david", ""], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        david, _ = players(conn)
        offer = market.offers(conn, driver_id=david)[0]
        window = offer["window_id"]
    page = master_client.get(f"/career/{token}/offers").get_data(as_text=True)
    assert "Counter-offer" in page and "Approach a team" in page
    res = master_client.post(f"/career/{token}/offers/{offer['id']}/counter",
                             data={"role": "No. 2", "years": "1", "growth": "3", "csrf_token": "tok"})
    assert res.status_code == 302
    with storage.session(token) as conn:
        assert market.get_offer(conn, offer["id"])["stage"] == "Terms agreed"
    res = master_client.post(f"/career/{token}/market/approach",
                             data={"driver_id": david, "window_id": window, "team_id": 1, "terms": "talks",
                                   "csrf_token": "tok"})
    assert res.status_code == 302
    assert "Conversation" in master_client.get(f"/career/{token}/offers").get_data(as_text=True)


# --------------------------------------------------------------------------- v1.5

from f1tracker import feed, insights  # noqa: E402


def _career_token(master_client, rookies=False):
    data = {"name": "V15", "year": "2026", "player_name": ["David Conley", "Carson Hayes"], "player_login": ["david", ""], "csrf_token": "tok"}
    if rookies:
        data["rookie_market"] = "1"
    res = master_client.post("/careers/new", data=data)
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def test_login_locks_after_repeated_wrong_passwords(app):
    auth.create_user("david", "David", "password1", is_master=True)
    client = app.test_client()
    for _ in range(C.LOGIN_MAX_FAILURES):
        client.post("/login", data={"username": "david", "password": "nope"})
    res = client.post("/login", data={"username": "david", "password": "password1"}, follow_redirects=True)
    assert "Too many wrong passwords" in res.get_data(as_text=True)
    with pytest.raises(auth.AuthError, match="Too many"):
        auth.login("david", "password1", "10.0.0.9")  # the account stays locked from any address
    with auth.accounts() as conn:  # ...until the lock expires
        conn.execute("UPDATE login_failures SET locked_until = 0")
    assert auth.login("david", "password1", "10.0.0.9")["username"] == "david"


@pytest.fixture
def codes(monkeypatch):
    """Capture sign-up code emails instead of sending them."""
    from f1tracker import mailer
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.append((to, subject, text)) or len(to))
    return sent


def _sign_up(client, codes, username="carson", email="carson@example.com"):
    client.get("/register")
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    res = client.post("/register", data={"username": username, "display_name": username.title(), "password": "password1",
                                         "confirm": "password1", "csrf_token": "tok", "email": email})
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    return res


def test_players_can_sign_up_but_see_nothing_until_assigned(app, master_client, codes):
    token = _career_token(master_client)
    client = app.test_client()
    res = _sign_up(client, codes)
    assert res.headers["Location"].endswith("/register/verify") and auth.get_user("carson") is None
    code = codes[-1][1].rsplit(" ", 1)[-1]
    assert codes[-1][0] == ["carson@example.com"] and len(code) == 6
    client.post("/register/verify", data={"code": code, "csrf_token": "tok"})
    assert auth.get_user("carson")["is_master"] == 0
    assert token not in client.get("/").get_data(as_text=True)
    assert client.get(f"/career/{token}/dashboard").status_code == 403
    assert "Waiting to be assigned" in master_client.get("/accounts").get_data(as_text=True)
    with storage.session(token) as conn:
        carson = players(conn)[1]
    master_client.post(f"/career/{token}/members", data={f"user_{carson}": "carson", "csrf_token": "tok"})
    assert client.get(f"/career/{token}/garage").status_code == 200
    auth.set_setting("allow_signups", "0")
    with pytest.raises(auth.AuthError, match="turned off"):
        auth.register("someone", "", "password1", "1.2.3.4")


def test_automatic_backups_daily_and_after_each_weekend(career, master_client):
    assert storage.auto_backup(career, "daily")
    assert storage.auto_backup(career, "daily") is None  # once a day
    for i in range(C.AUTO_BACKUPS_KEPT + 3):
        storage.auto_backup(career, f"after-round-{i}", force=True)
    assert len(storage.list_auto_backups(career)) == C.AUTO_BACKUPS_KEPT


def test_weekend_completion_posts_news_notifications_and_backup(master_client):
    token = _career_token(master_client)
    with storage.session(token) as conn:
        event = S.events(conn, S.current_season_id(conn))[0]
        rows = S.weekend_rows(conn, event["id"])
    payload = {"mark_complete": True, "ai_untracked": True, "results": [
        {"driver_id": r["driver_id"], "race_position": i + 1, "qualifying_position": i + 1} for i, r in enumerate(rows)]}
    for _ in range(2):  # saving a completed weekend again must not repeat the headlines
        assert master_client.post(f"/api/career/{token}/weekend/{event['id']}", json=payload,
                                  headers={"X-CSRF-Token": "tok"}).get_json()["ok"]
    with storage.session(token) as conn:
        news = feed.latest(conn)
        assert len([n for n in news if n["kind"] == "result"]) == 1
        assert rows[0]["driver"]["name"] in news[-1]["headline"]
        items, unread = feed.notifications_for(conn, "david", players(conn)[0])
        assert unread == 1 and "Results are in" in items[0]["text"]
        feed.mark_read(conn, "david")
        assert feed.notifications_for(conn, "david", players(conn)[0])[1] == 0
    assert any("after-round-1" in b["name"] for b in storage.list_auto_backups(token))
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "wins the 2026 Australian GP" in page and "data-chart" in page


def test_signing_is_announced_to_the_other_player(db, rng):
    sid = S.current_season_id(db)
    market.open_window(db, sid, rng=rng)
    david, carson = players(db)
    offer = market.offers(db, driver_id=david)[0]
    market.accept_offer(db, offer["id"])
    assert any("signs with" in n["headline"] for n in feed.latest(db))
    items, _ = feed.notifications_for(db, "carson", carson)
    assert any("David Conley just signed" in n["text"] for n in items)
    mine, _ = feed.notifications_for(db, "david", david)
    assert not any("David Conley just signed" in n["text"] for n in mine)


def test_cars_develop_over_winter_and_ratings_drive_early_ranks(db):
    sid = S.current_season_id(db)
    ratings = S.car_ratings(db, sid)
    assert ratings[1]["rating"] > ratings[11]["rating"]
    S.set_car_rating(db, sid, 11, 98)
    assert S.team_strength_ranks(db, sid)[11] == 1
    run_event(db, S.events(db, sid)[0])
    new_id = S.create_next_season(db, sid, 2027)
    changes = S.develop_cars(db, sid, new_id, random.Random(3))
    new = S.car_ratings(db, new_id)
    assert len(changes) == 11 and all(C.CAR_RATING_MIN <= r["rating"] <= C.CAR_RATING_MAX for r in new.values())
    assert any(r["change"] for r in new.values())
    feed.on_new_season(db, sid, new_id, changes, f"review/{sid}")
    assert any(n["kind"] == "tech" for n in feed.latest(db, 20))


def test_rivalry_and_season_review(db):
    sid, david, carson, _ = seat_players_at_cadillac(db)
    _player_rounds(db, [(1, 5), (6, 2), (3, 9)], 90)
    r = insights.rivalry(db, david, carson)
    assert r["race"] == [2, 1] and r["quali"] == [2, 1]
    assert r["streak"][0] == 1 and r["current"] == (0, 1) and r["swing"] == [1, 0, 1]
    assert r["best_margin"][0]["margin"] == 6
    review = insights.season_review(db, sid)
    titles = [a["title"] for a in review["awards"]]
    assert "Championship leader" in titles and "Rookie of the year" in titles
    assert {p["driver_id"] for p in review["players"]} == {david, carson}
    trend = insights.driver_round_timeline(db, david)
    assert len(trend["labels"]) == 3 and trend["form"][0] > 50


def test_paddock_admin_teams_drivers_and_calendar(db):
    sid = S.current_season_id(db)
    new_team = S.add_team(db, "Andretti", "and", "#123abc", sid)
    assert len(S.grid_map(db, sid)) == 24
    rookie = S.add_driver(db, "Test Rookie", 60, sid)
    with pytest.raises(S.ValidationError):
        S.add_driver(db, "test rookie", 60, sid)
    gmap = {k: str(v) if v else "" for k, v in S.grid_map(db, sid).items()}
    gmap[(new_team, 1)], gmap[(new_team, 2)] = str(rookie), str(players(db)[0])
    S.save_full_grid(db, sid, gmap)
    event = S.events(db, sid)[0]
    assert len(S.weekend_rows(db, event["id"])) == 24
    res = run_event(db, event)
    assert res["complete"]  # positions up to 24 are accepted

    verstappen = driver_id(db, "Max Verstappen")
    seat = S.driver_seats(db, sid)[verstappen]
    S.update_driver(db, verstappen, sid, "Max Verstappen", 97, False)
    assert verstappen not in S.driver_seats(db, sid)
    assert S.grid_map(db, sid)[seat] is None  # every AI driver already has a seat, so it waits for the Race Master
    S.update_team(db, new_team, sid, "Andretti", "AND", "#123abc", False)
    assert len(S.grid_map(db, sid)) == 22 and rookie not in S.driver_seats(db, sid)

    count = len(S.events(db, sid))
    added = S.add_event(db, sid, "Portuguese GP", "Portimão", True)
    assert S.get_event(db, added)["round_number"] == count + 1
    S.delete_event(db, S.events(db, sid)[3]["id"])
    rounds = [e["round_number"] for e in S.events(db, sid)]
    assert rounds == list(range(1, count + 1))
    with pytest.raises(S.ValidationError, match="haven't been run"):
        S.delete_event(db, event["id"])


def test_screenshots_are_never_uploaded(master_client):
    """v1.19: screenshots are read in the browser; the old upload endpoint no longer exists."""
    token = _career_token(master_client)
    with storage.session(token) as conn:
        event = S.events(conn, S.current_season_id(conn))[0]
    import io
    res = master_client.post(f"/api/career/{token}/weekend/{event['id']}/import",
                             data={"kind": "race", "screenshots": (io.BytesIO(b"png"), "r.png", "image/png")},
                             headers={"X-CSRF-Token": "tok"}, content_type="multipart/form-data")
    assert res.status_code in (404, 405)


def test_new_v15_pages_render(master_client):
    token = _career_token(master_client, rookies=True)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        david, carson = players(conn)
        S.place_players(conn, sid, {david: (11, 1), carson: (11, 2)})
        _player_rounds(conn, [(2, 4)], 90)
    pledge_all(token)
    for path in ["rivalry", f"review/{sid}", "news", "paddock", "garage", "drivers", f"driver/{david}", "teams",
                 "seasons", "api/notifications"]:
        url = f"/api/career/{token}/notifications" if path.startswith("api") else f"/career/{token}/{path}"
        assert master_client.get(url).status_code == 200, path
    master_client.post(f"/career/{token}/paddock/cars", data={"rating_1": "90.5", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert S.car_ratings(conn, sid)[1]["rating"] == 90.5


# --------------------------------------------------------------------------- v1.6: Race Steward role

def test_race_steward_runs_races_but_cannot_see_private_negotiations(app, master_client):
    auth.create_user("davidd", "David", "password1", is_steward=True)
    auth.create_user("carson", "Carson", "password1")
    assert auth.role_of(auth.get_user("davidd")) == "steward"
    res = master_client.post("/careers/new", data={"name": "Steward", "year": "2026", "rookie_market": "1",
                                                   "player_name": ["David Conley", "Carson Hayes"], "player_login": ["davidd", "carson"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        david, carson = players(conn)
        carson_offer = market.offers(conn, driver_id=carson)[0]
        event = S.events(conn, S.current_season_id(conn))[0]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, event["id"])]

    steward = app.test_client()
    login(steward, "davidd")
    # Can run the race weekend...
    res = steward.post(f"/api/career/{token}/weekend/{event['id']}", headers={"X-CSRF-Token": "tok"},
                       json={"results": [{"driver_id": ids[0], "race_position": 1}], "ai_difficulty": 88})
    assert res.get_json()["ok"]
    page = steward.get(f"/career/{token}/weekend/{event['id']}").get_data(as_text=True)
    assert "Submit results" in page and "View only" not in page
    # Scorekeepers only enter results: no admin pages, calendar or grid changes.
    assert steward.get(f"/career/{token}/paddock").status_code == 403
    assert steward.post(f"/career/{token}/calendar/add", data={"name": "X GP", "csrf_token": "tok"}).status_code == 403
    assert steward.post(f"/career/{token}/grid/save", data={"csrf_token": "tok"}).status_code == 403
    assert steward.post(f"/career/{token}/seasons/new", data={"year": "2027", "csrf_token": "tok"}).status_code == 403
    # Once submitted, the weekend is locked for them (but not for the Race Master).
    full = {"mark_complete": True, "ai_untracked": True, "results": [{"driver_id": d, "race_position": i + 1} for i, d in enumerate(ids)]}
    assert steward.post(f"/api/career/{token}/weekend/{event['id']}", headers={"X-CSRF-Token": "tok"}, json=full).get_json()["ok"]
    again = steward.post(f"/api/career/{token}/weekend/{event['id']}", headers={"X-CSRF-Token": "tok"}, json=full)
    assert again.status_code == 403 and "Race Master" in again.get_json()["error"]
    assert "Submitted and locked" in steward.get(f"/career/{token}/weekend/{event['id']}").get_data(as_text=True)
    assert master_client.post(f"/api/career/{token}/weekend/{event['id']}", headers={"X-CSRF-Token": "tok"},
                              json=full).get_json()["ok"]
    # ...but never sees Carson's side of the market, and can't open windows or write storylines.
    assert steward.get(f"/career/{token}/market").status_code == 302
    assert steward.post(f"/career/{token}/market/open", data={"csrf_token": "tok"}).status_code == 403
    assert steward.post(f"/career/{token}/contracts", data={"csrf_token": "tok"}).status_code == 403
    assert "Carson Hayes" not in steward.get(f"/career/{token}/garage?driver={carson}").get_data(as_text=True).split("<h1>")[1][:40]
    assert steward.post(f"/career/{token}/offers/{carson_offer['id']}/accept", data={"csrf_token": "tok"}).status_code == 403
    with storage.session(token) as conn:
        items, _ = feed.notifications_for(conn, "davidd", david, is_master=False)
        assert not any("made you an offer" in n["text"] and n["driver_id"] == carson for n in items)
    for path in ("/accounts", f"/career/{token}/members", f"/career/{token}/backup", f"/career/{token}/export"):
        res = steward.get(path)
        assert res.status_code == 403 or "All logins" not in res.get_data(as_text=True), path

    # A plain driver still can't enter results.
    driver = app.test_client()
    login(driver, "carson")
    assert driver.post(f"/api/career/{token}/weekend/{event['id']}", headers={"X-CSRF-Token": "tok"},
                       json={"results": []}).status_code == 403
    assert driver.get(f"/career/{token}/paddock").status_code == 403


def test_roles_can_be_changed_but_one_race_master_remains(app):
    auth.create_user("boss", "Boss", "password1", is_master=True)
    auth.create_user("davidd", "David", "password1")
    with pytest.raises(auth.AuthError, match="per league"):  # Scorekeeper is a league role now (v1.16)
        auth.set_role("davidd", "steward")
    auth.set_role("davidd", "master")
    auth.set_role("boss", "driver")
    with pytest.raises(auth.AuthError):
        auth.set_role("davidd", "steward")
    assert [u["role"] for u in auth.list_users()] == ["master", "driver"]


# --------------------------------------------------------------------------- v1.7: racecraft

def test_places_gained_near_the_front_count_far_more(db):
    assert S.racecraft_score(20, 1) == pytest.approx(19.0)
    assert S.racecraft_score(20, 19) < 0.25
    assert S.racecraft_score(3, 8) == pytest.approx(-2.0)
    sid, david, carson, _ = seat_players_at_cadillac(db)
    event = S.events(db, sid)[0]
    ids = [r["driver_id"] for r in S.weekend_rows(db, event["id"])]
    others = [d for d in ids if d not in (david, carson)]
    quali = others[:18] + [carson, david] + others[18:]          # both start at the back (P19, P20)
    order = [david] + others[:17] + [carson] + others[17:]        # David P1, Carson P19
    run_event(db, event, order=order, quali=quali)
    table = {r["driver_id"]: r for r in S.driver_standings(db, sid)}
    comeback = dict(table[david])
    assert comeback["gained"] == 19 and table[carson]["gained"] == 0
    plain = dict(comeback, racecraft=0, racecraft_races=0)
    assert S.compute_form(comeback) - S.compute_form(plain) > 10
    assert S.compute_reputation(42, comeback, comeback["form"]) - S.compute_reputation(42, plain, comeback["form"]) > 1.4


def test_reputation_history_can_be_recalculated(db):
    sid = S.current_season_id(db)
    run_event(db, S.events(db, sid)[0])
    s2 = S.create_next_season(db, sid, 2027)
    winner = S.driver_standings(db, sid)[0]["driver_id"]
    locked = S.starting_reputation(db, s2, winner)
    db.execute("UPDATE season_driver_state SET locked_reputation = 1 WHERE season_id = ?", (sid,))  # e.g. an old formula
    db.execute("UPDATE season_driver_state SET starting_reputation = 1 WHERE season_id = ?", (s2,))
    changes = S.recalculate_reputation_history(db)
    assert S.starting_reputation(db, s2, winner) == locked
    assert changes[winner][1] == locked
    state = db.execute("SELECT locked_reputation FROM season_driver_state WHERE season_id = ? AND driver_id = ?",
                       (s2, winner)).fetchone()
    assert state["locked_reputation"] is None  # the current season stays live


def test_hosted_setup_needs_the_setup_code(app, monkeypatch):
    monkeypatch.setenv("F1_TRACKER_SETUP_CODE", "s3cret")
    client = app.test_client()
    assert "Setup code" in client.get("/setup").get_data(as_text=True)
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    client.post("/setup", data={"username": "intruder", "password": "password1", "csrf_token": "tok", "setup_code": "nope"})
    assert auth.user_count() == 0
    client.post("/setup", data={"username": "admin", "password": "password1", "csrf_token": "tok", "setup_code": "s3cret"})
    assert auth.get_user("admin")["is_master"] == 1


def test_production_server_module_builds_the_app():
    import importlib
    server = importlib.import_module("server")
    assert server.app.config["SESSION_COOKIE_SECURE"] is True
    client = server.app.test_client()
    assert client.get("/login", headers={"X-Forwarded-Proto": "https"}).status_code in (200, 302)



# --------------------------------------------------------------------------- v1.8: email, resets, clean-up

@pytest.fixture
def outbox(monkeypatch):
    sent = []
    from f1tracker import mailer
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_later", lambda to, subject, text, html=None: sent.append((list(to), subject, text)) or True)
    return sent


def test_forgot_password_emails_a_one_time_link(app, outbox):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    auth.create_user("noemail", "No Email", "password1")
    client = app.test_client()
    client.get("/forgot")
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    client.post("/forgot", data={"login": "noemail", "csrf_token": "tok"})
    assert outbox == []
    client.post("/forgot", data={"login": "CARSON@example.com", "csrf_token": "tok"})
    assert outbox[0][0] == ["carson@example.com"]
    link = next(w for w in outbox[0][2].split() if "/reset/" in w)
    path = link.split("localhost", 1)[-1]
    assert "Choose a new password" in client.get(path).get_data(as_text=True)
    client.post(path, data={"password": "newpass99", "confirm": "newpass99", "csrf_token": "tok"})
    assert auth.verify("carson", "newpass99")
    assert client.get(path).status_code == 302  # the link only works once
    for _ in range(10):
        client.post("/forgot", data={"login": "carson", "csrf_token": "tok"})
    assert len(outbox) <= auth.RESET_REQUESTS_PER_IP_PER_HOUR


def test_race_results_are_emailed_to_career_members(app, master_client, outbox):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    auth.create_user("quiet", "Quiet", "password1", email="quiet@example.com")
    auth.set_email("quiet", "quiet@example.com", False)
    res = master_client.post("/careers/new", data={"name": "Mail", "year": "2026", "player_name": ["David Conley", "Carson Hayes"], "player_login": ["david", "carson"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    from f1tracker import notices
    with storage.session(token) as conn:
        conn.execute("INSERT INTO career_members(username, driver_id) VALUES('quiet', NULL)")
        # v2.0: result emails are chosen per league; a new membership doesn't inherit an account-wide switch.
        notices.save(conn, "carson", email={"results"})
        event = S.events(conn, S.current_season_id(conn))[0]
        rows = S.weekend_rows(conn, event["id"])
    payload = {"mark_complete": True, "ai_untracked": True, "results": [
        {"driver_id": r["driver_id"], "race_position": i + 1, "qualifying_position": i + 1} for i, r in enumerate(rows)]}
    master_client.post(f"/api/career/{token}/weekend/{event['id']}", json=payload, headers={"X-CSRF-Token": "tok"})
    assert len(outbox) == 1
    to, subject, text = outbox[0]
    assert to == ["carson@example.com"] and "Australian GP" in subject
    assert rows[0]["driver"]["name"] in text and "Championship" in text
    assert 'for the league "Mail"' in text and f"/career/{token}/notifications" in text


def test_race_master_can_delete_a_transfer_window_and_its_trail(db, rng):
    sid = S.current_season_id(db)
    window = market.open_window(db, sid, rng=rng)
    david, carson = players(db)
    feed.post(db, sid, "result", "An unrelated headline")
    assert db.execute("SELECT COUNT(*) FROM news WHERE ref = ?", (f"window:{window}",)).fetchone()[0] == 1
    # Two offer notices plus (v2.0) the league-wide "market is open" notice.
    assert db.execute("SELECT COUNT(*) FROM notifications WHERE ref = ?", (f"window:{window}",)).fetchone()[0] == 3
    assert market.delete_window(db, window) == 0
    assert market.offers(db) == [] and market.windows(db) == []
    assert db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0
    assert [n["headline"] for n in feed.latest(db)] == ["An unrelated headline"]
    assert db.execute("SELECT COUNT(*) FROM offer_messages").fetchone()[0] == 0


def test_mailer_sends_over_smtp_with_starttls(monkeypatch):
    from f1tracker import mailer
    sent, calls = [], []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self, context=None):
            calls.append(("starttls",))
        def login(self, user, password):
            calls.append(("login", user, password))
        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    auth.set_setting("smtp_host", "smtp.example.com")
    auth.set_setting("smtp_username", "bot@example.com")
    auth.set_setting("smtp_password", "app-pass")
    assert mailer.configured()
    assert mailer.send(["a@example.com", "b@example.com", "a@example.com"], "Hi", "Body", "<p>Body</p>") == 2
    assert calls[:3] == [("connect", "smtp.example.com", 587), ("starttls",), ("login", "bot@example.com", "app-pass")]
    assert [m["To"] for m in sent] == ["a@example.com", "b@example.com"] and "bot@example.com" in sent[0]["From"]


# --------------------------------------------------------------------------- v1.9: open leagues

def _new_league(master_client, names, logins=None, **extra):
    data = {"name": "Open League", "year": "2026", "player_name": names,
            "player_login": logins or [""] * len(names), "csrf_token": "tok", **extra}
    res = master_client.post("/careers/new", data=data)
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def test_leagues_can_have_any_number_of_players(master_client):
    empty = _new_league(master_client, [""], rookie_market="1")
    with storage.session(empty) as conn:
        assert players(conn) == [] and conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == 22
        assert market.windows(conn) == []
    three = _new_league(master_client, ["Ana Silva", "Ben Okafor", "Chloe Park"], rookie_market="1", join_open="1")
    with storage.session(three) as conn:
        assert [p["name"] for p in S.player_drivers(conn)] == ["Ana Silva", "Ben Okafor", "Chloe Park"]
        assert all(p["baseline_reputation"] == C.ROOKIE_REPUTATION for p in S.player_drivers(conn))
        assert len({o["driver_id"] for o in market.offers(conn)}) == 3
        slots = [s["slot"] for s in insights.progression_chart(conn, S.current_season_id(conn))["series"]]
        assert len(slots) == len(set(slots))
    assert master_client.get(f"/career/{three}/rivalry").status_code == 200
    with storage.session(three) as conn:
        a, b = driver_id(conn, "Max Verstappen"), driver_id(conn, "Lando Norris")
    page = master_client.get(f"/career/{three}/rivalry?a={a}&b={b}").get_data(as_text=True)
    assert "Max Verstappen" in page and "Lando Norris" in page


def test_anyone_can_ask_to_join_and_the_race_master_approves(app, master_client):
    token = _new_league(master_client, ["Ana Silva"], rookie_market="1", join_open="1")
    auth.create_user("newbie", "Newbie", "password1", email="newbie@example.com")
    newbie = app.test_client()
    login(newbie, "newbie")
    home = newbie.get("/").get_data(as_text=True)
    assert "Open League" in home and "Ask to join" in home
    newbie.post(f"/career/{token}/join", data={"driver_name": "Max Verstappen", "csrf_token": "tok"})  # taken
    newbie.post(f"/career/{token}/join", data={"driver_name": "Nia Newbie", "message": "hi", "csrf_token": "tok"})
    assert "Request sent" in newbie.get("/").get_data(as_text=True)
    assert newbie.get(f"/career/{token}/dashboard").status_code == 403
    with storage.session(token) as conn:
        req = conn.execute("SELECT * FROM join_requests WHERE status = 'Pending'").fetchall()
        assert len(req) == 1 and req[0]["driver_name"] == "Nia Newbie"
    assert "Join requests" in master_client.get(f"/career/{token}/members").get_data(as_text=True)
    master_client.post(f"/career/{token}/members/request/{req[0]['id']}/approve",
                       data={"driver_name": "Nia Newbie", "send_offers": "1", "csrf_token": "tok"})
    with storage.session(token) as conn:
        nia = driver_id(conn, "Nia Newbie")
        assert conn.execute("SELECT driver_id FROM career_members WHERE username = 'newbie'").fetchone()[0] == nia
        mine = [o for o in market.offers(conn, driver_id=nia) if o["status"] == C.OFFER_PENDING]
        assert mine and len(market.windows(conn)) == 1  # added to the already-open Rookie Draft
        assert len({o["driver_id"] for o in market.offers(conn)}) == 2
    garage = newbie.get(f"/career/{token}/offers").get_data(as_text=True)
    assert "Nia Newbie" in garage and "Counter-offer" in garage
    # Closing the league hides it from people who aren't in it.
    master_client.post(f"/career/{token}/members/settings", data={"csrf_token": "tok"})
    auth.create_user("late", "Late", "password1")
    late = app.test_client()
    login(late, "late")
    assert "Open League" not in late.get("/").get_data(as_text=True)
    assert late.post(f"/career/{token}/join", data={"driver_name": "Late Guy", "csrf_token": "tok"}).status_code == 302
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM join_requests WHERE username = 'late'").fetchone()[0] == 0


def test_race_master_can_add_a_player_mid_season(master_client):
    token = _new_league(master_client, ["Ana Silva"])
    auth.create_user("ben", "Ben", "password1")
    master_client.post(f"/career/{token}/members/player",
                       data={"driver_name": "Ben Okafor", "username": "ben", "send_offers": "1", "csrf_token": "tok"})
    with storage.session(token) as conn:
        ben = driver_id(conn, "Ben Okafor")
        windows = market.windows(conn)
        assert len(windows) == 1 and windows[0]["kind"] == "Rookie Draft"
        assert {o["driver_id"] for o in market.offers(conn)} == {ben}  # Ana doesn't get a surprise second round



# --------------------------------------------------------------------------- v1.10

def test_drivers_can_be_deleted_completely(db):
    sid = S.current_season_id(db)
    spare = S.add_driver(db, "Spare Driver", C.ROOKIE_REPUTATION, sid)
    assert S.delete_driver(db, spare, sid) == "Spare Driver"
    assert db.execute("SELECT COUNT(*) FROM drivers WHERE id = ?", (spare,)).fetchone()[0] == 0
    perez = driver_id(db, "Sergio Perez")
    seat = S.driver_seats(db, sid)[perez]
    run_event(db, S.events(db, sid)[0])
    with pytest.raises(S.ValidationError, match="race result"):
        S.delete_driver(db, perez, sid)
    S.delete_driver(db, perez, sid, force=True)
    assert perez not in S.driver_seats(db, sid)
    assert db.execute("SELECT COUNT(*) FROM results WHERE driver_id = ?", (perez,)).fetchone()[0] == 0
    assert S.grid_map(db, sid)[seat] is None or S.grid_map(db, sid)[seat] != perez



def test_sign_up_needs_the_emailed_code(app, codes):
    auth.create_user("admin", "Admin", "password1", is_master=True)
    client = app.test_client()
    _sign_up(client, codes, "nia", "nia@example.com")
    assert "Check your email" in client.get("/register/verify").get_data(as_text=True)
    real = codes[-1][1].rsplit(" ", 1)[-1]
    wrong = "000000" if real != "000000" else "111111"
    res = client.post("/register/verify", data={"code": wrong, "csrf_token": "tok"}, follow_redirects=True)
    assert "4 tries left" in res.get_data(as_text=True) and auth.get_user("nia") is None
    for _ in range(4):
        client.post("/register/verify", data={"code": wrong, "csrf_token": "tok"})
    res = client.post("/register/verify", data={"code": real, "csrf_token": "tok"}, follow_redirects=True)
    assert "Too many wrong codes" in res.get_data(as_text=True) and auth.get_user("nia") is None
    # A fresh code resets the tries (after the one-minute wait).
    with auth.accounts() as conn:
        conn.execute("UPDATE pending_signups SET sent_at = 0")
    client.post("/register/resend", data={"csrf_token": "tok"})
    fresh = codes[-1][1].rsplit(" ", 1)[-1]
    client.post("/register/verify", data={"code": fresh, "csrf_token": "tok"})
    assert auth.get_user("nia")["email"] == "nia@example.com"
    assert auth.verify("nia", "password1")


def test_sign_up_is_closed_until_email_is_set_up(app):
    auth.create_user("admin", "Admin", "password1", is_master=True)
    client = app.test_client()
    page = client.get("/register").get_data(as_text=True)
    assert "need email to be set up" in page
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    client.post("/register", data={"username": "x1", "password": "password1", "confirm": "password1",
                                   "email": "x@example.com", "csrf_token": "tok"})
    assert auth.get_user("x1") is None


# --------------------------------------------------------------------------- v1.12: join roles

def test_join_requests_carry_a_role_the_race_master_can_change(app, master_client):
    token = _new_league(master_client, ["Ana Silva"], join_open="1")
    with storage.session(token) as conn:
        event = S.events(conn, S.current_season_id(conn))[0]
    clients = {}
    for name in ("kim", "sam", "lee"):
        auth.create_user(name, name.title(), "password1")
        clients[name] = app.test_client()
        login(clients[name], name)
    assert "Scorekeeper only" in clients["kim"].get("/").get_data(as_text=True)
    clients["kim"].post(f"/career/{token}/join", data={"role": "scorekeeper", "csrf_token": "tok"})
    clients["sam"].post(f"/career/{token}/join", data={"role": "driver_scorekeeper", "driver_name": "Sam Driver",
                                                       "csrf_token": "tok"})
    clients["lee"].post(f"/career/{token}/join", data={"role": "driver_scorekeeper", "driver_name": "Lee Racer",
                                                       "csrf_token": "tok"})
    with storage.session(token) as conn:
        reqs = {r["username"]: r for r in conn.execute("SELECT * FROM join_requests")}
    assert reqs["kim"]["role"] == "scorekeeper" and reqs["kim"]["driver_name"] == ""
    assert "Driver + Scorekeeper" in master_client.get(f"/career/{token}/members").get_data(as_text=True)
    # Accept as asked, accept with a different role, and accept as a spectator.
    for user, role in (("kim", "scorekeeper"), ("sam", "driver_scorekeeper"), ("lee", "driver")):
        master_client.post(f"/career/{token}/members/request/{reqs[user]['id']}/approve",
                           data={"role": role, "driver_name": reqs[user]["driver_name"], "csrf_token": "tok"})
    with storage.session(token) as conn:
        members = {r["username"]: r for r in conn.execute("SELECT * FROM career_members")}
        assert members["kim"]["driver_id"] is None and members["kim"]["scorekeeper"] == 1
        assert members["sam"]["driver_id"] == driver_id(conn, "Sam Driver") and members["sam"]["scorekeeper"] == 1
        assert members["lee"]["driver_id"] == driver_id(conn, "Lee Racer") and members["lee"]["scorekeeper"] == 0
        ids = [r["driver_id"] for r in S.weekend_rows(conn, event["id"])]
    body = {"results": [{"driver_id": ids[0], "race_position": 1}]}
    post = lambda c: c.post(f"/api/career/{token}/weekend/{event['id']}", headers={"X-CSRF-Token": "tok"}, json=body)
    assert post(clients["kim"]).get_json()["ok"] and post(clients["sam"]).get_json()["ok"]
    assert post(clients["lee"]).status_code == 403
    assert clients["kim"].get(f"/career/{token}/paddock").status_code == 403
    # Scorekeeper flags survive the links form.
    master_client.post(f"/career/{token}/members", data={
        f"user_{members['sam']['driver_id']}": "sam", f"user_{members['lee']['driver_id']}": "lee",
        f"keeper_{members['lee']['driver_id']}": "1", "member_kim": "spectator", "csrf_token": "tok"})
    with storage.session(token) as conn:
        flags = {r["username"]: r["scorekeeper"] for r in conn.execute("SELECT * FROM career_members")}
    assert flags == {"david": 0, "sam": 0, "lee": 1, "kim": 0}   # david: the creator is a member since v2.0
    # A spectator role needs no driver name; declining still works.
    auth.create_user("viv", "Viv", "password1")
    viv = app.test_client()
    login(viv, "viv")
    viv.post(f"/career/{token}/join", data={"role": "spectator", "csrf_token": "tok"})
    with storage.session(token) as conn:
        rid = conn.execute("SELECT id FROM join_requests WHERE username = 'viv'").fetchone()[0]
    master_client.post(f"/career/{token}/members/request/{rid}/decline", data={"csrf_token": "tok"})
    assert viv.get(f"/career/{token}/dashboard").status_code == 403
