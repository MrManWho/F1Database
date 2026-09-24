"""v2.1.3: view modes hide admin tools, choices that must be made first, per-round target reset, a full role
audit, and a second login reset."""

import re

import pytest

from conftest import login, pledge_all, players, run_event
from f1tracker import auth, impacts, roles, services as S, storage, teamgoals, teamlife
from f1tracker import app as appmod


def _league(master_client, name="Audit League"):
    for u in ("ana", "kim", "sam", "pat"):
        auth.create_user(u, u.title(), "password1")
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva", "Ben Okafor"], "player_login": ["ana", ""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        S.place_players(conn, sid, {a: (10, 1), b: (9, 1)})
        roles.set_member(conn, "kim", "scorekeeper")
        roles.set_member(conn, "sam", "spectator")
        roles.set_member(conn, "pat", "member")
        storage.set_meta(conn, "timezone", "UTC")
    pledge_all(token)
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


# --------------------------------------------------------------------------- view modes and team goals

def test_race_master_tools_follow_the_view_mode(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        teamgoals.set_enabled(conn, True)
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
    # v2.4: the tools live on Team management (Race Master only); the team goals page just links there.
    assert "Reopen the choice" in master_client.get(f"/career/{token}/team-management").get_data(as_text=True)
    assert "Reopen the choice" not in master_client.get(f"/career/{token}/team-goals").get_data(as_text=True)
    master_client.post(f"/career/{token}/mode", data={"mode": "spectator", "csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/team-goals").get_data(as_text=True)
    assert "Reopen the choice" not in page and "Re-push" not in page
    ana = _client(app, "ana")
    assert "Reopen the choice" not in ana.get(f"/career/{token}/team-goals").get_data(as_text=True)
    with storage.session(token) as conn:
        team = S.driver_seats(conn, S.current_season_id(conn))[a][0]
    assert ana.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "action": "reopen"}).status_code == 403


def test_an_open_team_goal_must_be_chosen_before_anything_else(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        teamgoals.set_enabled(conn, True)
        team = S.driver_seats(conn, sid)[a][0]
    ana = _client(app, "ana")
    res = ana.get(f"/career/{token}/dashboard")
    assert res.status_code == 302 and res.headers["Location"].endswith("/team-goals")
    assert "Choose your team" in ana.get(f"/career/{token}/team-goals").get_data(as_text=True)
    ana.post(f"/career/{token}/weekend/1/predict", data={"csrf_token": "tok", "winner": str(a)})   # blocked
    res = ana.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "tier": "safe"})
    assert res.headers["Location"].endswith("/dashboard")
    assert ana.get(f"/career/{token}/dashboard").status_code == 200
    # Reopened mid-season: the driver has to choose again first.
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, sid)[0])
    assert ana.get(f"/career/{token}/dashboard").status_code == 200    # locked: nothing to choose
    master_client.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "action": "reopen"})
    assert ana.get(f"/career/{token}/dashboard").headers["Location"].endswith("/team-goals")
    ana.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "tier": "ambitious"})
    assert ana.get(f"/career/{token}/dashboard").status_code == 200
    # Re-pushed targets are shown to agree to before anything else.
    master_client.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "action": "repush"})
    res = ana.get(f"/career/{token}/dashboard")
    assert res.headers["Location"].endswith("/changes")
    page = ana.get(f"/career/{token}/changes").get_data(as_text=True)
    assert "Your team goal was updated" in page and "Before:" in page and "Now:" in page
    # Players with no login and the Race Master are never held up.
    assert master_client.get(f"/career/{token}/dashboard").status_code == 200


# --------------------------------------------------------------------------- weekend targets per round

def test_race_master_resets_targets_on_a_chosen_round(app, master_client):
    from f1tracker import relations
    from f1tracker import constants as C
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        relations.ensure(conn, sid)
        evs = S.events(conn, sid)
        teamlife.issue_targets(conn, evs[0]["id"])
        t = teamlife.options_for(conn, evs[0]["id"], a)        # v2.4: three to choose from
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        run_event(conn, evs[0], order=[a] + [d for d in ids if d != a])
        teamlife.judge_targets(conn, evs[0]["id"])
        assert teamlife.target_for(conn, evs[0]["id"], a)["status"] == "Hit"
        bonus_before = relations.assess(conn, sid, a)["bonus"]
        teamlife.issue_targets(conn, evs[1]["id"])
    page = master_client.get(f"/career/{token}/team-management").get_data(as_text=True)   # v2.4: its own page
    assert f"Last round · R{evs[0]['round_number']}" in page and "Remove" in page
    ana = _client(app, "ana")
    assert ana.post(f"/career/{token}/weekend/{evs[0]['id']}/targets",
                    data={"csrf_token": "tok", "action": "remove", "driver_id": a}).status_code == 403
    master_client.post(f"/career/{token}/weekend/{evs[0]['id']}/targets",
                       data={"csrf_token": "tok", "action": "remove", "driver_id": a})
    with storage.session(token) as conn:
        assert teamlife.target_for(conn, evs[0]["id"], a) is None
        assert relations.assess(conn, sid, a)["bonus"] == bonus_before - C.TARGET_HIT      # its effect undone
        assert any(n["title"] == "Weekend target removed" for n in impacts.pending(conn, a, "ana"))
        teamlife.judge_targets(conn, evs[0]["id"])                   # a correction doesn't bring it back
        assert teamlife.target_for(conn, evs[0]["id"], a) is None
    # Before the race: re-issue for everyone, or remove (and it stays removed).
    master_client.post(f"/career/{token}/weekend/{evs[1]['id']}/targets", data={"csrf_token": "tok", "action": "remove"})
    with storage.session(token) as conn:
        teamlife.issue_targets(conn, evs[1]["id"])
        assert teamlife.targets_for_event(conn, evs[1]["id"]) == []
        assert not teamlife.options_for(conn, evs[1]["id"], a)
    master_client.post(f"/career/{token}/weekend/{evs[1]['id']}/targets", data={"csrf_token": "tok", "action": "reissue"})
    with storage.session(token) as conn:
        assert all(len(teamlife.options_for(conn, evs[1]["id"], d)) == 3 for d in (a, b))
    assert t


# --------------------------------------------------------------------------- permission audit

def _fill(rule, token, ev):
    path = rule.rule.replace("<token>", token)
    return re.sub(r"<int:[a-z_]+>", str(ev), re.sub(r"<(?!int:)[a-z_]+>", "x", path))


def test_every_league_route_declares_its_access_and_each_role_is_held_to_it(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[1]["id"]
    clients = {name: _client(app, name) for name in ("ana", "kim", "sam", "pat")}
    checked = 0
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/career/<token>"):
            continue
        view = app.view_functions[rule.endpoint]
        # Open to any signed-in person on purpose, with their own checks: asking to join, answering an invitation,
        # and a driver photo (members, or the public page's key).
        if rule.endpoint in ("career_join", "invitation_answer", "avatar"):
            continue
        access = getattr(view, "access", None)
        assert access in ("master", "ops", "member"), f"{rule.endpoint} declares no access level"
        path = _fill(rule, token, ev)
        for method in rule.methods & {"GET", "POST"}:
            for name, c in clients.items():
                if access == "master" or (access == "ops" and name not in ("kim",)):
                    res = c.open(path, method=method, data={"csrf_token": "tok"}, headers={"X-CSRF-Token": "tok"})
                    assert res.status_code in (403, 404, 405), (rule.endpoint, method, name, res.status_code)
                    checked += 1
    assert checked > 150


def test_drivers_only_act_for_their_own_driver(app, master_client):
    token, a, b = _league(master_client)
    ana = _client(app, "ana")
    assert ana.post(f"/career/{token}/driver/{b}/profile", data={"csrf_token": "tok", "bio": "hacked"}).status_code == 403
    for path in (f"garage?driver={b}", f"offers?driver={b}", f"team-standing?driver={b}"):
        assert "Ben Okafor" not in ana.get(f"/career/{token}/{path}").get_data(as_text=True).split("<h1>")[1][:80]
    pat = _client(app, "pat")                                          # a member with no driver
    assert pat.get(f"/career/{token}/garage").status_code == 403
    assert pat.get(f"/career/{token}/offers").status_code == 403


# --------------------------------------------------------------------------- 2.1.3 login reset

def _league_data(token):
    with storage.session(token) as conn:
        return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
                for t in ("drivers", "results", "events", "seasons", "season_grid", "teams", "contracts", "offers")}


def test_2_1_3_reset_erases_every_login_and_the_links_to_them_but_no_league_data(app, master_client):
    from f1tracker.app import create_app, reset_league_logins
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
        conn.execute("INSERT INTO invitations(username, role, invited_by, status, created_at) "
                     "VALUES('ghost', 'member', 'david', 'Pending', 'x')")
    before = _league_data(token)
    with auth.accounts() as conn:
        conn.execute("INSERT INTO reserved_usernames(username, email_hash, reserved_at) VALUES('old', 'h', 'x')")
    create_app({"SECRET_KEY": "x"})                                    # what the server does on start
    assert auth.user_count() == 0 and auth.reserved_count() == 0
    assert list(storage.backups_dir().glob("accounts-before-2.1.3-reset-*.db"))
    assert any("before-213-login-reset" in b["name"] for b in storage.list_auto_backups(token))
    assert _league_data(token) == before                               # drivers, results, seasons... untouched
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM career_members").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM invitations WHERE status = 'Pending'").fetchone()[0] == 0
    # A newcomer who picks an old username gets nothing from the old league.
    auth.create_user("ana", "Someone Else", "password1")
    stranger = _client(app, "ana")
    assert stranger.get(f"/career/{token}/dashboard").status_code == 403
    # Only once: a second start leaves the new accounts alone.
    create_app({"SECRET_KEY": "x"})
    assert auth.get_user("ana")
    assert reset_league_logins("x") >= 1


@pytest.mark.whatsnew
def test_new_accounts_see_the_changelog_to_agree_to(app, master_client):
    auth.create_user("fresh", "Fresh", "password1")
    page = _client(app, "fresh").get("/").get_data(as_text=True)
    assert 'id="whats-new"' in page and "I agree to them" in page
