"""v1.14: growth pledges, team relationships, warnings, releases and the Team Standing page."""

import random

from conftest import login, players, pledge_all, run_event
from f1tracker import auth, feed, market, relations, services as S, storage
from f1tracker import constants as C


def _seat(conn):
    sid = S.current_season_id(conn)
    david, carson = players(conn)
    cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(conn, sid, {david: (cad, 1), carson: (cad, 2)})
    return sid, david, carson, cad


def _set_pledge(conn, sid, driver_id, growth):
    relations.ensure(conn, sid)
    relations.set_pledge(conn, sid, driver_id, growth)


def test_targets_are_fair_to_every_car():
    assert relations.car_baseline_form(1) > relations.car_baseline_form(6) > relations.car_baseline_form(11)
    assert relations.growth_level(99)["name"] == "Breakout" and relations.growth_level(None)["name"] == "Steady"
    assert [market.growth_needed(1, r, y) for r, y in (("No. 2", 1), ("No. 1", 1), ("No. 1", 3))] == [1, 2, 3]


def test_signing_sets_the_pledge_as_season_targets(db, rng):
    sid = S.current_season_id(db)
    david, _ = players(db)
    market.open_window(db, sid, rng=rng)
    offer = market.offers(db, driver_id=david)[0]
    market.counter_offer(db, offer["id"], "No. 2", 1, 2, rng=rng)
    market.accept_offer(db, offer["id"])
    relations.ensure(db, sid)
    a = relations.assess(db, sid, david)
    assert a["growth"] == 2 and a["team_id"] == offer["team_id"] and a["level"]["name"] == "Strong"
    rank = S.team_strength_ranks(db, sid)[a["team_id"]]
    assert a["finish_base"] == relations.expected_finish(rank)
    assert a["finish_target"] == relations.pledged_finish(rank, 2) < a["finish_base"]
    assert a["status"] == "Happy" and a["score"] == C.RELATION_START  # nothing judged before a race


def test_falling_short_brings_warnings_then_release_and_bench(db):
    sid, david, carson, cad = _seat(db)
    _set_pledge(db, sid, david, 3)   # promised a Breakout season in a slow car
    _set_pledge(db, sid, carson, 0)
    evs = S.events(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, evs[0]["id"])]
    order = [d for d in ids if d != david] + [david]          # David last every time
    for ev in evs[:8]:
        run_event(db, ev, order=order, quali=order)
        relations.review(db, sid)
    a = relations.assess(db, sid, david)
    assert a["status"] == "Seat at risk" and a["warning_level"] == 3
    tones = [n["tone"] for n in relations.notes(db, sid, david)]
    assert "danger" in tones and len(tones) >= 2
    assert any("Formal warning" in n["text"] or "future" in n["text"] for n in feed.notifications_for(db, "x", david)[0])
    # Carson beat an easy Steady pledge.
    assert relations.assess(db, sid, carson)["live_status"] in ("Happy", "Delighted")
    # Silly Season: the team lets David go and won't renew.
    for ev in evs[8:12]:
        run_event(db, ev, order=order, quali=order)
    market.maybe_open_silly_season(db, sid)
    assert relations.is_released(db, sid, david)
    offers = [o for o in market.offers(db, driver_id=david) if o["status"] == C.OFFER_PENDING]
    assert offers and all(o["team_id"] != cad for o in offers)
    _me, interest = market.team_interest(db, sid, david)
    assert next(i for i in interest if i["current"])["label"] == "Letting you go"
    # He signs nothing, so next season he's benched; Carson keeps his seat.
    for o in offers:
        market.decline_offer(db, o["id"])
    for o in market.offers(db, driver_id=david):
        if o["status"] == C.OFFER_PENDING:
            market.decline_offer(db, o["id"])
    new_id = S.create_next_season(db, sid, 2027)
    market.on_new_season(db, new_id, previous_id=sid)
    seats = S.driver_seats(db, new_id)
    assert david not in seats and seats[carson][0] == cad


def test_turnaround_lifts_the_warning(db):
    sid, david, carson, cad = _seat(db)
    _set_pledge(db, sid, david, 3)
    evs = S.events(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, evs[0]["id"])]
    last = [d for d in ids if d != david] + [david]
    first = [david] + [d for d in ids if d != david]
    for ev in evs[:4]:
        run_event(db, ev, order=last, quali=last)
        relations.review(db, sid)
    assert relations.assess(db, sid, david)["warning_level"] >= 2
    for ev in evs[4:16]:
        run_event(db, ev, order=first, quali=first)
        relations.review(db, sid)
    assert relations.assess(db, sid, david)["warning_level"] == 0
    assert any("turnaround" in n["text"] for n in relations.notes(db, sid, david))


def test_team_standing_page_and_admin_menu(app, master_client):
    auth.create_user("carson", "Carson", "password1")
    res = master_client.post("/careers/new", data={"name": "Rel", "year": "2026", "player_name": ["David Conley", "Carson Hayes"],
                                                   "player_login": ["", "carson"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        _seat(conn)
    pledge_all(token)
    carson = app.test_client()
    login(carson, "carson")
    page = carson.get(f"/career/{token}/team-standing").get_data(as_text=True)
    assert "Relationship" in page and "Your targets" in page and "Eagerness around the paddock" in page
    assert "Team Standing" in page and "My Garage" in page
    # The Race Master isn't a driver here: admin menu, no "My career".
    dash = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Player garages" in dash and "Team standings" in dash and "My Garage" not in dash
    assert "Race Master</span>" in dash
    page = master_client.get(f"/career/{token}/team-standing").get_data(as_text=True)
    assert "David Conley" in page and "Carson Hayes" in page
    # Linking the Race Master to a driver turns "My career" on for them.
    with storage.session(token) as conn:
        david = players(conn)[0]
    master_client.post(f"/career/{token}/members", data={f"user_{david}": "david", "csrf_token": "tok"})
    dash = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "My Garage" in dash and "Race Master · Driver" in dash


def test_members_page_is_clear_about_access(app, master_client):
    auth.create_user("kim", "Kim", "password1")
    res = master_client.post("/careers/new", data={"name": "M", "year": "2026", "player_name": ["Ana Silva"],
                                                   "player_login": [""], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    page = master_client.get(f"/career/{token}/members").get_data(as_text=True)
    assert "League members" in page and "What each role can do" in page and "Add someone" in page
    master_client.post(f"/career/{token}/members/add", data={"username": "kim", "role": "scorekeeper", "csrf_token": "tok"})
    with storage.session(token) as conn:
        row = conn.execute("SELECT * FROM career_members WHERE username = 'kim'").fetchone()
    assert row["driver_id"] is None and row["scorekeeper"] == 1
    kim = app.test_client()
    login(kim, "kim")
    assert "Scorekeeper</span>" in kim.get(f"/career/{token}/dashboard").get_data(as_text=True)


def test_random_negotiations_never_crash(db):
    """Throw thousands of random counters and approaches at the market."""
    rng = random.Random(3)
    sid = S.current_season_id(db)
    for _round in range(6):
        window = market.open_window(db, sid, rng=rng) if not market.windows(db) or \
            market.windows(db)[0]["status"] != C.WINDOW_OPEN else market.windows(db)[0]["id"]
        for pid in players(db):
            for _ in range(10):
                pending = [o for o in market.offers(db, driver_id=pid) if o["status"] == C.OFFER_PENDING]
                choice = rng.random()
                try:
                    if pending and choice < 0.6:
                        o = rng.choice(pending)
                        if o["final"]:
                            market.decline_offer(db, o["id"], rng=rng)
                        else:
                            market.counter_offer(db, o["id"], rng.choice(C.CONTRACT_ROLES), rng.randint(1, 5),
                                                 rng.randint(0, 3), rng=rng)
                    elif choice < 0.8:
                        teams = market.approachable_teams(db, window, pid)
                        if teams:
                            market.approach_team(db, window, pid, rng.choice(teams)["id"],
                                                 *((rng.choice(C.CONTRACT_ROLES), rng.randint(1, 5), rng.randint(0, 3))
                                                   if rng.random() < 0.5 else (None, None, None)), rng=rng)
                    elif pending:
                        market.accept_offer(db, rng.choice(pending)["id"])
                except S.ValidationError:
                    pass
        for o in market.offers(db):
            if o["status"] == C.OFFER_PENDING:
                assert o["role"] in C.CONTRACT_ROLES and 0 <= o["growth"] <= 3 and 1 <= o["years"] <= C.MAX_CONTRACT_YEARS
        market.close_window(db, window)
        db.execute("DELETE FROM market_windows")  # let the next loop open a fresh window
    grid = S.grid_map(db, sid)
    seated = [d for d in grid.values() if d]
    assert len(seated) == len(set(seated))


def test_contract_years_keep_you_off_the_market_unless_released(db, rng):
    sid = S.current_season_id(db)
    david, carson = players(db)
    market.open_window(db, sid, rng=rng)
    offer = market.offers(db, driver_id=david)[0]
    assert market.counter_offer(db, offer["id"], "No. 2", 2, 3, rng=rng) == "agreed"
    market.accept_offer(db, offer["id"])          # 2026-2027
    assert market.get_offer(db, offer["id"])["years"] == 2
    relations.ensure(db, sid)                     # keep the team happy whatever happens on track
    db.execute("UPDATE team_relations SET finish_target = 99, rebased = 1 WHERE driver_id = ?", (david,))
    market.close_window(db, market.windows(db)[0]["id"])
    for ev in S.events(db, sid)[:12]:
        run_event(db, ev)
    window = market.maybe_open_silly_season(db, sid)  # for 2027
    assert window and not [o for o in market.offers(db, driver_id=david, window_id=window)]
    assert market.locked_in(db, sid, david, 2027)["end_year"] == 2027
    team = next(t for t in S.teams(db) if t["id"] != offer["team_id"])
    import pytest
    with pytest.raises(S.ValidationError, match="under contract"):
        market.approach_team(db, window, david, team["id"], rng=rng)
    with pytest.raises(S.ValidationError, match="under contract"):
        market.offers_for_player(db, david)
    # Carson had no deal, so he's on the market as normal.
    assert market.offers(db, driver_id=carson, window_id=window)
    # A release tears the contract up.
    relations.ensure(db, sid)
    db.execute("UPDATE team_relations SET released = 1 WHERE season_id = ? AND driver_id = ?", (sid, david))
    assert market.locked_in(db, sid, david, 2027) is None


def test_changelog_page_and_salary_era_saves(app, master_client, career, rng):
    page = master_client.get("/changelog").get_data(as_text=True)
    assert f"v{C.APP_VERSION}" in page and "Current" in page and "Growth pledge" not in page.split("v1.13")[1]
    # A v1.13 save with salary-era offers opens, and the garage shows pledges instead of money.
    with storage.session(career) as conn:
        market.open_window(conn, S.current_season_id(conn), rng=rng)
        david = players(conn)[0]
        conn.execute("INSERT INTO career_members(username, driver_id) VALUES('david', ?)", (david,))
    import sqlite3
    raw = sqlite3.connect(str(storage.career_path(career)))
    raw.execute("UPDATE offers SET growth = NULL, min_growth = NULL, salary = 3.5")
    raw.execute("ALTER TABLE offer_messages DROP COLUMN growth")
    raw.execute("DROP TABLE team_relations")
    raw.execute("UPDATE meta SET value = '10' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()
    garage = master_client.get(f"/career/{career}/garage").get_data(as_text=True)
    assert "Growth pledge" in garage and "$" not in garage.split("Negotiations")[1].split("Who's watching")[0]
    with storage.session(career) as conn:
        offer = [o for o in market.offers(conn, driver_id=david) if o["status"] == C.OFFER_PENDING][0]
        assert market.counter_offer(conn, offer["id"], "No. 2", 1, 3, rng=rng) == "agreed"
