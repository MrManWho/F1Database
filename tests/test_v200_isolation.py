"""v2.0: every league route is protected on the server, and nothing crosses from one league to another."""

import re

import pytest

from conftest import login, players, run_event
from f1tracker import auth, community, notices, roles, services as S, storage


def _league(master_client, name, login_name):
    auth.create_user(login_name, login_name.title(), "password1", email=f"{login_name}@example.com")
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "player_name": [f"{login_name.title()} Racer"],
                                                   "player_login": [login_name], "csrf_token": "tok", "join_mode": "invite"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _fill(rule):
    """A concrete path for a URL rule, with plausible values for every variable."""
    def value(m):
        conv, var = m.group(1), m.group(2)
        if var == "token":
            return "{token}"
        return "1" if conv == "int" else {"decision": "approve", "username": "outsider", "name": "x.f1career",
                                          "key": "nokey", "sig": "x"}.get(var, "x")
    return re.sub(r"<(?:(\w+):)?(\w+)>", value, rule)


LEAGUE_OPEN_TO_ANY_LOGIN = {"career_join", "invitation_answer"}   # they check the league's own rules themselves
PUBLIC = {"public_page", "avatar"}


def _league_rules(app):
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith(("/career/<token>", "/api/career/<token>")) or rule.endpoint in PUBLIC:
            continue
        yield rule


def test_an_outsider_can_open_or_change_nothing_in_another_league(app, master_client):
    a = _league(master_client, "League A", "alice")
    b = _league(master_client, "League B", "bob")
    bob = _client(app, "bob")
    checked = 0
    for rule in _league_rules(app):
        if rule.endpoint in LEAGUE_OPEN_TO_ANY_LOGIN:
            continue
        path = _fill(rule.rule).replace("{token}", a)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            if method == "GET":
                res = bob.get(path)
            else:
                res = bob.open(path, method=method, data={"csrf_token": "tok"}, json=None if method != "POST" else None,
                               headers={"X-CSRF-Token": "tok"})
            assert res.status_code in (401, 403, 404), (rule.endpoint, method, path, res.status_code)
            checked += 1
    assert checked > 80
    # Bob's own league still works.
    assert bob.get(f"/career/{b}/dashboard").status_code == 200


def test_spectators_are_read_only_on_every_route(app, master_client):
    a = _league(master_client, "League A", "alice")
    auth.create_user("sam", "Sam", "password1")
    with storage.session(a) as conn:
        roles.set_member(conn, "sam", "spectator")
    sam = _client(app, "sam")
    # Personal, harmless actions: their own notifications, their own league list, how the league is shown, and leaving.
    allowed = {"notifications_read", "notifications_clear", "timezone_detect", "notify_prefs", "career_join",
               "invitation_answer", "view_mode", "league_pin", "league_order", "league_leave"}
    for rule in _league_rules(app):
        if rule.endpoint in allowed:
            continue
        path = _fill(rule.rule).replace("{token}", a)
        for method in rule.methods - {"HEAD", "OPTIONS", "GET"}:
            res = sam.open(path, method=method, data={"csrf_token": "tok"}, headers={"X-CSRF-Token": "tok"})
            assert res.status_code in (401, 403, 404, 405), (rule.endpoint, method, res.status_code)


MASTER_ONLY = {"season_new", "season_rollover", "seat_resolve", "league_settings", "members", "member_update", "member_remove",
               "paddock_admin", "paddock_move_results", "paddock_driver", "paddock_driver_delete", "market_open",
               "market_close", "market_delete", "calendar_save", "calendar_add", "calendar_delete", "weekend_reopen",
               "gate_bypass", "target_excuse", "delivery_log_page", "activity", "grid_players", "grid_save"}


def test_scorekeepers_cannot_reach_race_master_tools(app, master_client):
    a = _league(master_client, "League A", "alice")
    auth.create_user("kim", "Kim", "password1")
    with storage.session(a) as conn:
        roles.set_member(conn, "kim", "scorekeeper")
    kim = _client(app, "kim")
    seen = set()
    for rule in _league_rules(app):
        if rule.endpoint not in MASTER_ONLY:
            continue
        seen.add(rule.endpoint)
        path = _fill(rule.rule).replace("{token}", a)
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            res = kim.open(path, method=method, data={"csrf_token": "tok"}, headers={"X-CSRF-Token": "tok"})
            assert res.status_code in (403, 404, 405), (rule.endpoint, method, res.status_code)
    assert seen >= MASTER_ONLY - {"activity", "paddock_admin", "members"} or len(seen) > 15


def test_the_same_ids_in_two_leagues_never_mix(app, master_client):
    """Driver 1 / round 1 exist in both leagues: each URL only ever reads its own league's database."""
    a = _league(master_client, "League A", "alice")
    b = _league(master_client, "League B", "bob")
    with storage.session(a) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
        conn.execute("UPDATE drivers SET name = 'Only In A' WHERE id = 1")
    page_b = master_client.get(f"/career/{b}/driver/1").get_data(as_text=True)
    assert "Only In A" not in page_b
    week_b = master_client.get(f"/career/{b}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Not Run" in week_b or "NOT RUN" in week_b.upper()
    # The selected season is remembered per league, never carried into another.
    with storage.session(a) as conn:
        sid_a = S.current_season_id(conn)
    master_client.get(f"/career/{a}/dashboard?season={sid_a}")
    with master_client.session_transaction() as sess:
        assert sess.get(f"season_{a}") == sid_a
        assert f"season_{b}" not in sess          # choosing a season in A never sets one for B


def test_notifications_and_activity_stay_in_their_league(app, master_client):
    a = _league(master_client, "League A", "alice")
    b = _league(master_client, "League B", "bob")
    with storage.session(a) as conn:
        from f1tracker import feed
        feed.notify(conn, None, "Secret news from A", "dashboard")
        community.audit(conn, "david", "Test", "", summary="did something private in A")
    bob = _client(app, "bob")
    assert "Secret news from A" not in bob.get(f"/api/career/{b}/notifications").get_data(as_text=True)
    assert "private in A" not in master_client.get(f"/career/{b}/activity").get_data(as_text=True)
    with storage.session(b) as conn:
        assert notices.prefs(conn, "alice")["stored"] is False    # alice isn't in B: B has no preferences for her


def test_results_api_rejects_other_leagues_and_non_entry_roles(app, master_client):
    a = _league(master_client, "League A", "alice")
    b = _league(master_client, "League B", "bob")
    bob = _client(app, "bob")
    with storage.session(a) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    body = {"results": [], "mark_complete": False}
    assert bob.post(f"/api/career/{a}/weekend/{ev['id']}", json=body, headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert bob.get(f"/api/career/{a}/weekend/{ev['id']}/state").status_code == 403
    assert bob.get(f"/api/career/{a}/weekend/{ev['id']}/checklist").status_code == 403
    alice = _client(app, "alice")   # a Member (driver) in A, not a results role
    assert alice.post(f"/api/career/{a}/weekend/{ev['id']}", json=body, headers={"X-CSRF-Token": "tok"}).status_code == 403
