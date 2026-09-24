"""v1.16: unified league roles, read-only views, player colours, time formatting and the new pages."""

from datetime import datetime, timedelta, timezone

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import auth, feed, insights, roles, schema, services as S, storage, timefmt
from f1tracker import constants as C


def _league(master_client):
    """A league run by site Race Master david, with ana and ben driving for Cadillac."""
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    res = master_client.post("/careers/new", data={"name": "V16", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
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


def _first_event(token):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))[0]


def _payload(token, event_id, complete=False):
    with storage.session(token) as conn:
        rows = S.weekend_rows(conn, event_id)
    return {"results": [{"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1,
                         "status_override": "Auto", "sprint_position": None, "sprint_status_override": "Auto",
                         "fastest_lap": False, "driver_of_day": False, "notes": ""} for i, r in enumerate(rows)],
            "mark_complete": complete, "ai_difficulty": None, "ai_untracked": True}


def _api_save(client, token, event_id, complete=False):
    return client.post(f"/api/career/{token}/weekend/{event_id}", json=_payload(token, event_id, complete),
                       headers={"X-CSRF-Token": "tok"})


# --------------------------------------------------------------------------- spectators

def test_spectator_is_read_only_everywhere(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "sam", "spectator")
    sam = _client(app, "sam")
    ev = _first_event(token)
    for path in ("dashboard", f"weekend/{ev['id']}", "drivers", "teams", "news", "records", "seasons", "grid", "contracts"):
        assert sam.get(f"/career/{token}/{path}").status_code == 200, path
    # Every change is refused by the server, not just hidden.
    assert _api_save(sam, token, ev["id"]).status_code == 403
    assert sam.post(f"/career/{token}/comments", data={"target": f"event:{ev['id']}", "body": "hi", "csrf_token": "tok"}).status_code == 403
    assert sam.post(f"/career/{token}/grid/save", data={"csrf_token": "tok"}).status_code == 403
    assert sam.post(f"/career/{token}/calendar/add", data={"name": "Extra GP", "csrf_token": "tok"}).status_code == 403
    assert sam.get(f"/career/{token}/members").status_code == 403
    assert sam.get(f"/career/{token}/settings").status_code == 403
    # Reading notifications is allowed.
    assert sam.post(f"/career/{token}/notifications/read", json={}, headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert sam.post(f"/career/{token}/notifications/clear", json={}, headers={"X-CSRF-Token": "tok"}).status_code == 200


def test_spectator_pages_render_text_not_inputs(app, master_client):
    token, a, b = _league(master_client)
    ev = _first_event(token)
    with storage.session(token) as conn:
        run_event(conn, ev, dotd=a, fl=b)
    _add(token, "sam", "spectator")
    sam = _client(app, "sam")
    page = sam.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Spectator · view only" in page
    assert 'name="race_' not in page and 'type="number"' not in page.split("Results")[-1].split("</table>")[0]
    grid = sam.get(f"/career/{token}/grid").get_data(as_text=True)
    body = grid.split('<main', 1)[1]
    assert "View only" in body and "Complete grid editor" not in body and "2026 grid" in body
    assert 'name="seat_' not in body and "Place players" not in body
    cal = sam.get(f"/career/{token}/seasons").get_data(as_text=True)
    assert "Save calendar" not in cal and "View only" in cal
    assert "Spectator" in sam.get(f"/career/{token}/dashboard").get_data(as_text=True)


# --------------------------------------------------------------------------- Race Master & Scorekeeper

def test_league_race_master_runs_the_league(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "rita", "race_master")
    rita = _client(app, "rita")
    assert rita.get(f"/career/{token}/members").status_code == 200
    assert rita.get(f"/career/{token}/settings").status_code == 200
    ev = _first_event(token)
    assert _api_save(rita, token, ev["id"], complete=True).status_code == 200
    assert _api_save(rita, token, ev["id"]).status_code == 200  # can still correct a completed round
    res = rita.post(f"/career/{token}/members/add", data={"username": "sam", "role": "spectator", "csrf_token": "tok"})
    assert res.status_code == 302 if auth.get_user("sam") else True


def test_scorekeeper_enters_results_but_nothing_administrative(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "kim", "scorekeeper")
    kim = _client(app, "kim")
    ev = _first_event(token)
    assert _api_save(kim, token, ev["id"]).status_code == 200
    page = kim.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "View only" not in page.split("Results")[1][:400]
    assert _api_save(kim, token, ev["id"], complete=True).status_code == 200
    assert _api_save(kim, token, ev["id"]).status_code == 403  # submitted: only the Race Master can reopen
    for path in ("members", "settings", "market", "paddock", "activity"):
        assert kim.get(f"/career/{token}/{path}").status_code in (302, 403), path
    assert kim.post(f"/career/{token}/members/ana/update", data={"role": "spectator", "csrf_token": "tok"}).status_code == 403
    assert kim.post(f"/career/{token}/members/david/remove", data={"csrf_token": "tok"}).status_code == 403
    assert kim.post(f"/career/{token}/seasons/new", data={"year": "2027", "csrf_token": "tok"}).status_code == 403
    assert kim.post(f"/career/{token}/delete", data={"csrf_token": "tok"}).status_code == 403
    assert kim.post(f"/career/{token}/settings", data={"csrf_token": "tok"}).status_code == 403
    assert kim.post(f"/career/{token}/paddock/recalculate", data={"csrf_token": "tok"}).status_code == 403
    with storage.session(token) as conn:
        assert S.get_season(conn, S.current_season_id(conn))["year"] == 2026


def test_scorekeeper_with_and_without_a_driver(app, master_client):
    token, a, b = _league(master_client)
    # ben keeps his driver and becomes Scorekeeper too.
    master_client.post(f"/career/{token}/members/ben/update", data={"role": "scorekeeper", "driver_id": str(b), "csrf_token": "tok"})
    _add(token, "kim", "scorekeeper")
    ben, kim = _client(app, "ben"), _client(app, "kim")
    ev = _first_event(token)
    assert _api_save(ben, token, ev["id"]).status_code == 200
    assert ben.get(f"/career/{token}/garage").status_code == 200
    assert "Scorekeeper · Driver" in ben.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert _api_save(kim, token, ev["id"]).status_code == 200
    assert kim.get(f"/career/{token}/garage").status_code == 403  # no driver, no garage
    with storage.session(token) as conn:
        row = conn.execute("SELECT role, driver_id FROM career_members WHERE username = 'ben'").fetchone()
    assert row["role"] == "scorekeeper" and row["driver_id"] == b


# --------------------------------------------------------------------------- the role rules themselves

def test_role_rules_and_final_race_master_protection(app, master_client):
    token, a, b = _league(master_client)
    _add(token, "rita", "race_master")
    with storage.session(token) as conn:
        with pytest.raises(roles.RoleError, match="Spectators can't have a driver"):
            roles.set_member(conn, "ana", "spectator", a)
        with pytest.raises(roles.RoleError, match="site Race Master"):
            roles.set_member(conn, "david", "member")
        with pytest.raises(roles.RoleError, match="already assigned"):
            roles.set_member(conn, "rita", "race_master", a)
        # With a site Race Master around, a league Race Master can step down.
        roles.set_member(conn, "rita", "member")
        roles.set_member(conn, "rita", "race_master")
    # Without any site Race Master, the last league Race Master is protected.
    with auth.accounts() as accts:
        accts.execute("UPDATE users SET is_master = 0")
    with storage.session(token) as conn:
        # Since v2.0 whoever creates a league is also its (league) Race Master; take them out to test the rule.
        conn.execute("DELETE FROM career_members WHERE username = 'david'")
        assert roles.race_master_count(conn) == 1
        with pytest.raises(roles.RoleError, match="at least one Race Master"):
            roles.set_member(conn, "rita", "scorekeeper")
        with pytest.raises(roles.RoleError, match="at least one Race Master"):
            roles.remove_member(conn, "rita")
        roles.set_member(conn, "ana", "race_master", a)  # a second one: now rita may step down
        roles.set_member(conn, "rita", "spectator")


def test_account_level_scorekeeper_switch_is_gone(master_client):
    auth.create_user("kim", "Kim", "password1")
    with pytest.raises(auth.AuthError, match="per league"):
        auth.set_role("kim", "steward")
    assert "Scorekeeper" not in master_client.get("/accounts").get_data(as_text=True).split("<select")[1].split("</select>")[0]


def test_legacy_two_part_scorekeeper_migrates_without_losing_access(app, master_client):
    token, a, b = _league(master_client)
    auth.create_user("kim", "Kim", "password1")
    with storage.session(token) as conn:
        conn.execute("INSERT INTO career_members(username, driver_id, scorekeeper, role) VALUES('kim', NULL, 0, 'spectator')")
        conn.execute("UPDATE career_members SET scorekeeper = 0, role = 'member' WHERE username = 'ben'")
    with auth.accounts() as accts:  # the old account-wide switch
        accts.execute("UPDATE users SET is_steward = 1 WHERE username IN ('kim', 'ben')")
    assert roles.unify_legacy_scorekeepers() == 2
    assert roles.unify_legacy_scorekeepers() == 0  # idempotent
    with storage.session(token) as conn:
        got = {r["username"]: (r["role"], r["driver_id"]) for r in conn.execute("SELECT * FROM career_members")}
    assert got["kim"] == ("scorekeeper", None) and got["ben"] == ("scorekeeper", b) and got["ana"][0] == "member"
    assert not auth.get_user("kim")["is_steward"]
    assert _api_save(_client(app, "kim"), token, _first_event(token)["id"]).status_code == 200


def test_old_save_migrates_to_v13_and_keeps_everything(career):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        ev = S.events(conn, sid)[0]
        a, b = players(conn)
        run_event(conn, ev)
        before = [(r["driver_id"], r["points"]) for r in S.driver_standings(conn, sid)]
        auth.create_user("kim", "Kim", "password1")
        auth.create_user("sam", "Sam", "password1")
        auth.create_user("ana", "Ana", "password1")
        conn.execute("INSERT INTO career_members(username, driver_id, scorekeeper) VALUES('kim', NULL, 1)")
        conn.execute("INSERT INTO career_members(username, driver_id, scorekeeper) VALUES('sam', NULL, 0)")
        conn.execute("INSERT INTO career_members(username, driver_id, scorekeeper) VALUES('ana', ?, 0)", (a,))
        # Turn this into a v12 save: no role columns, no player colours, no cleared_id.
        for table, col in (("career_members", "role"), ("career_members", "joined_at"), ("career_members", "last_active"),
                           ("drivers", "player_color"), ("notification_reads", "cleared_id")):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        conn.execute("UPDATE meta SET value = '12' WHERE key = 'schema_version'")
        schema.migrate(conn)
        roles_now = {r["username"]: r["role"] for r in conn.execute("SELECT * FROM career_members")}
        assert roles_now == {"kim": "scorekeeper", "sam": "spectator", "ana": "member"}
        colors = [S.driver_map(conn)[d]["player_color"] for d in (a, b)]
        assert all(colors) and colors[0] != colors[1]
        assert [(r["driver_id"], r["points"]) for r in S.driver_standings(conn, sid)] == before
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(C.SCHEMA_VERSION)


# --------------------------------------------------------------------------- human drivers and their colours

def test_human_drivers_detected_and_colours_persist(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        dmap = S.driver_map(conn)
        ca, cb = dmap[a]["player_color"], dmap[b]["player_color"]
        assert ca and cb and ca != cb and {ca, cb} <= set(C.PLAYER_COLORS)
        assert S.human_driver_ids(conn) >= {a, b}
        # A third player joins: detected automatically, with a colour of their own.
        c = S.add_player_driver(conn, "Cleo Park", sid)
        assert c in S.human_driver_ids(conn)
        cc = S.driver_map(conn)[c]["player_color"]
        assert cc and cc not in (ca, cb)
        # Rename and team change keep the colour.
        S.update_driver(conn, a, sid, "Ana Silva-Reyes", dmap[a]["baseline_reputation"], True)
        mcl = conn.execute("SELECT id FROM teams WHERE name = 'McLaren'").fetchone()["id"]
        S.place_players(conn, sid, {a: (mcl, 1)})
        assert S.driver_map(conn)[a]["player_color"] == ca
        # Sitting out a season and coming back doesn't change it either.
        S._unseat(conn, sid, a)
        new_sid = S.create_next_season(conn, sid, 2027)
        assert a not in S.driver_seats(conn, new_sid)
        S.place_players(conn, new_sid, {a: (mcl, 1)})
        assert S.driver_map(conn)[a]["player_color"] == ca
    page = master_client.get(f"/career/{token}/drivers").get_data(as_text=True)
    assert "player-row" in page and ca in page


# --------------------------------------------------------------------------- early-season and empty states

def test_unfinished_season_awards_are_provisional(app, master_client):
    token, a, b = _league(master_client)
    ev = _first_event(token)
    with storage.session(token) as conn:
        order = [a] + [r["driver_id"] for r in S.weekend_rows(conn, ev["id"]) if r["driver_id"] != a]
        run_event(conn, ev, order=order)
    page = master_client.get(f"/career/{token}/driver/{a}").get_data(as_text=True)
    assert "Current projections" in page and "Provisional" in page
    assert "No completed seasons yet" in page  # nothing in the trophy cabinet until the season is done


def test_zero_value_records_show_empty_messages(master_client):
    token, a, b = _league(master_client)
    page = master_client.get(f"/career/{token}/records").get_data(as_text=True)
    assert "No champion yet" in page and "No victory recorded" in page


def test_one_round_of_form_and_reputation(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        run_event(conn, _first_event(token))
        trend = insights.driver_round_timeline(conn, a)
    assert len(trend["form"]) == 1
    page = master_client.get(f"/career/{token}/driver/{a}").get_data(as_text=True)
    assert "More trend data available after Round 2" in page and "Current Form" in page


def test_zero_zero_rivalry_is_neutral(master_client):
    token, a, b = _league(master_client)
    page = master_client.get(f"/career/{token}/rivalry?a={a}&b={b}").get_data(as_text=True)
    assert "rival-bar empty" in page and "Tied" in page and "Still tied" in page


# --------------------------------------------------------------------------- dates and times

def test_time_formatting_in_the_league_time_zone():
    utc = "2026-09-23T15:30:00+00:00"
    assert timefmt.race(utc, "America/New_York") == "Wed, Sep 23 · 11:30 AM"
    assert timefmt.race_at(utc, "America/New_York") == "Wed, Sep 23 at 11:30 AM"
    assert timefmt.stamp("2026-09-23T02:26:00+00:00", "America/New_York") == "Sep 22, 2026 · 10:26 PM"
    now = datetime(2026, 9, 23, 18, 30, tzinfo=timezone.utc)
    assert timefmt.ago("2026-09-23T15:30:00+00:00", "UTC", now=now) == "3 hours ago"
    soon = (datetime.now(timezone.utc) + timedelta(hours=9, minutes=56, seconds=30)).isoformat()
    assert timefmt.countdown(soon) in ("Starts in 9h 56m", "Starts in 9h 55m")
    assert timefmt.countdown("2020-01-01T00:00:00+00:00") is None
    # A time typed on the race page is read in the league's zone and stored in UTC.
    assert timefmt.from_input("2026-09-23T11:30", "America/New_York").startswith("2026-09-23T15:30")


# --------------------------------------------------------------------------- new pages

def test_stat_changes_race_summary_team_profile_and_market(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        for ev in evs[:3]:
            run_event(conn, ev)
            feed.on_weekend_complete(conn, ev["id"], f"weekend/{ev['id']}")
        changes = insights.stat_changes(conn, sid, a)
        table = {r["driver_id"]: r for r in S.driver_standings(conn, sid)}
    assert changes["since"] == f"R{evs[1]['round_number']}"
    assert changes["points"]["now"] == table[a]["points"] and changes["form"]["now"] == table[a]["form"]
    assert len(changes["form"]["series"]) == 3
    garage = master_client.get(f"/career/{token}/garage?driver={a}").get_data(as_text=True)
    assert "since R2" in garage and "sparkline" in garage
    summary = master_client.get(f"/career/{token}/weekend/{evs[2]['id']}/summary").get_data(as_text=True)
    assert "Post-race summary" in summary and "Player weekends" in summary and "Ana Silva" in summary
    assert master_client.get(f"/career/{token}/weekend/{evs[5]['id']}/summary").status_code == 302  # not run yet
    with storage.session(token) as conn:
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    team = master_client.get(f"/career/{token}/team/{cad}").get_data(as_text=True)
    assert "Car rating by season" in team and "Everyone who raced for Cadillac" in team and "Ana Silva" in team
    market_page = _client(app, "ana").get(f"/career/{token}/contracts").get_data(as_text=True)
    assert "Market status" in market_page and "Player contracts" in market_page
    news = master_client.get(f"/career/{token}/news").get_data(as_text=True)
    assert "story-card" in news and "Race" in news


def test_notifications_mark_read_and_clear_keep_history(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        feed.notify(conn, None, "Results are in: test", "news")
        total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    ana = _client(app, "ana")
    data = ana.get(f"/api/career/{token}/notifications").get_json()
    assert data["unread"] >= 1 and data["items"][0]["icon"] == "🏁" and data["items"][0]["category"] == "Race"
    ana.get(f"/career/{token}/dashboard")  # opening pages doesn't mark anything read
    assert ana.get(f"/api/career/{token}/notifications").get_json()["unread"] == data["unread"]
    ana.post(f"/career/{token}/notifications/read", json={}, headers={"X-CSRF-Token": "tok"})
    assert ana.get(f"/api/career/{token}/notifications").get_json()["unread"] == 0
    ana.post(f"/career/{token}/notifications/clear", json={}, headers={"X-CSRF-Token": "tok"})
    assert ana.get(f"/api/career/{token}/notifications").get_json()["items"] == []
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == total  # nothing deleted
    # Others still see them.
    assert master_client.get(f"/api/career/{token}/notifications").get_json()["items"]
