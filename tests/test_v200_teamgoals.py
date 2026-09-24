"""v2.0 selectable team goals: fair generation, who can choose, locking, settlement and league separation."""

from conftest import login, pledge_all, players, run_event
from f1tracker import auth, community, roles, services as S, storage, teamgoals


def _league(master_client, name="Goal League", players_=("Ana Silva", "Ben Okafor"), logins=("ana", "")):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite", "player_name": list(players_),
                                                   "player_login": list(logins)})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _seat(conn, placements):
    S.place_players(conn, S.current_season_id(conn), placements)


def test_options_scale_with_car_strength_and_calendar(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        _seat(conn, {a: (1, 1), b: (10, 1)})
        ranks = S.team_strength_ranks(conn, sid)
        fast = min(ranks, key=ranks.get)
        slow = max(ranks, key=ranks.get)
        fo, so = teamgoals.options(conn, sid, fast), teamgoals.options(conn, sid, slow)
        assert fo["expected"] < so["expected"]
        # Each tier is strictly harder than the last, by position or points.
        for info in (fo, so):
            s, c, x = (info["options"][k] for k in ("safe", "competitive", "ambitious"))
            assert s["target_points"] < c["target_points"] < x["target_points"]
            assert s["reward"] < c["reward"] < x["reward"] and s["penalty"] >= c["penalty"] >= x["penalty"]
        # The fastest car can't aim above P1, so its Ambitious goal is judged on points only (no free position route).
        assert fo["options"]["ambitious"]["target_position"] == 0 or fo["expected"] >= 3
        n = len(S.teams(conn))
        assert so["options"]["safe"]["target_position"] == 0 or so["expected"] <= n - 3
        # No tier is ever "finish last or better" (always true).
        assert all(o["target_position"] < n for info in (fo, so) for o in info["options"].values())
        # A longer calendar asks for more points.
        before = fo["options"]["competitive"]["target_points"]
        evs = S.events(conn, sid)
        conn.execute("DELETE FROM events WHERE id = ?", (evs[-1]["id"],))
        assert teamgoals.options(conn, sid, fast)["options"]["competitive"]["target_points"] < before
        assert "car strength" in fo["why"] and "round" in fo["why"]


def test_only_the_teams_players_choose_and_it_locks_after_round_one(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("sam", "Sam", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        _seat(conn, {a: (1, 1), b: (5, 1)})
        roles.set_member(conn, "sam", "spectator")
        ana_team = S.driver_seats(conn, sid)[a][0]
        other = S.driver_seats(conn, sid)[b][0]
    ana = _client(app, "ana")
    assert ana.post(f"/career/{token}/team-goals/{ana_team}", data={"csrf_token": "tok", "tier": "safe"}).status_code == 302
    with storage.session(token) as conn:
        assert teamgoals.choice(conn, sid, ana_team) is None                   # off: nothing chosen
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "team_life": "1", "team_goal_choice": "1",
                                                          "difficulty_recs": "1", "weekend_targets": "1"})
    with storage.session(token) as conn:
        assert teamgoals.enabled(conn)
        assert "turned selectable team goals on" in community.audit_entries(conn)[0]["summary"]
    pledge_all(token)
    res = ana.get(f"/career/{token}/dashboard")                    # v2.1.3: the choice comes first
    assert res.headers["Location"].endswith("/team-goals")
    assert "Choose your team" in ana.get(f"/career/{token}/team-goals").get_data(as_text=True)
    ana.post(f"/career/{token}/team-goals/{ana_team}", data={"csrf_token": "tok", "tier": "ambitious"})
    assert ana.post(f"/career/{token}/team-goals/{other}", data={"csrf_token": "tok", "tier": "safe"}).status_code == 403
    sam = _client(app, "sam")
    assert sam.post(f"/career/{token}/team-goals/{ana_team}", data={"csrf_token": "tok", "tier": "safe"}).status_code == 403
    assert "Ambitious" in sam.get(f"/career/{token}/team-goals").get_data(as_text=True)   # everyone can see
    with storage.session(token) as conn:
        assert teamgoals.choice(conn, sid, ana_team)["tier"] == "ambitious"
        assert teamgoals.choice(conn, sid, other) is None
        run_event(conn, S.events(conn, sid)[0])
    ana.post(f"/career/{token}/team-goals/{ana_team}", data={"csrf_token": "tok", "tier": "safe"})
    with storage.session(token) as conn:
        assert teamgoals.choice(conn, sid, ana_team)["tier"] == "ambitious"    # locked
    page = ana.get(f"/career/{token}/team-goals").get_data(as_text=True)
    assert "locked" in page and "No goal was chosen" in page


def test_settlement_rewards_and_penalises_next_season_once(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        _seat(conn, {a: (1, 1), b: (10, 1)})
        teamgoals.set_enabled(conn, True)
        seats_ = S.driver_seats(conn, sid)
        ta, tb = seats_[a][0], seats_[b][0]
        teamgoals.choose(conn, sid, ta, "safe", "david")
        teamgoals.choose(conn, sid, tb, "ambitious", "david")
        evs = S.events(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        ta_drivers = [d for d, (t, _s) in seats_.items() if t == ta]
        tb_drivers = [d for d, (t, _s) in seats_.items() if t == tb]
        order = ta_drivers + [d for d in ids if d not in ta_drivers + tb_drivers] + tb_drivers   # ta wins, tb last
        for e in evs:
            run_event(conn, e, order=order)
        new = S.create_next_season(conn, sid, 2027)
        conn.execute("UPDATE season_driver_state SET starting_reputation = 50 WHERE season_id = ?", (new,))
        changes = teamgoals.apply_rewards(conn, sid, new)
        assert changes == {a: 1.0, b: -3.0}
        assert S.starting_reputation(conn, new, a) == 51 and S.starting_reputation(conn, new, b) == 47
        got = {g["team_id"]: g for g in teamgoals.progress(conn, sid)}
        assert got[ta]["outcome"] == "Met" and got[tb]["outcome"] == "Missed" and got[tb]["final_position"] == len(S.teams(conn))
        # Settling again returns the same result and never re-scores the season.
        assert teamgoals.settle(conn, sid) == changes
        # Reputation stays within 0-100.
        conn.execute("UPDATE season_driver_state SET starting_reputation = 1 WHERE season_id = ? AND driver_id = ?", (new, b))
        teamgoals.apply_rewards(conn, sid, new)
        assert S.starting_reputation(conn, new, b) == 0


def test_rollover_route_settles_goals(app, master_client):
    token = _league(master_client, players_=("Ana Silva",), logins=("",))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        _seat(conn, {a: (1, 1)})
        teamgoals.set_enabled(conn, True)
        teamgoals.choose(conn, sid, S.driver_seats(conn, sid)[a][0], "competitive", "david")
        for e in S.events(conn, sid):
            run_event(conn, e)
    form = {"year": "2027", "csrf_token": "tok"}
    with storage.session(token) as conn:
        from f1tracker import seats
        for r in seats.rollover_review(conn, sid, 2027)["rows"]:
            if r["needs_decision"]:
                form[f"decision_{r['driver']['id']}"] = "renew"
    master_client.post(f"/career/{token}/seasons/new", data=form)
    with storage.session(token) as conn:
        assert S.current_season_id(conn) != sid
        assert teamgoals.progress(conn, sid)[0]["outcome"] in ("Met", "Missed")


def test_goals_stay_in_their_league(app, master_client):
    t1 = _league(master_client, "League One")
    t2 = _league(master_client, "League Two")
    for t in (t1, t2):
        with storage.session(t) as conn:
            a, b = players(conn)
            _seat(conn, {a: (1, 1), b: (2, 1)})
            teamgoals.set_enabled(conn, True)
    with storage.session(t1) as conn:
        sid = S.current_season_id(conn)
        team = S.driver_seats(conn, sid)[players(conn)[0]][0]
        teamgoals.choose(conn, sid, team, "competitive", "david")
    with storage.session(t2) as conn:
        assert teamgoals.progress(conn, S.current_season_id(conn)) == []
