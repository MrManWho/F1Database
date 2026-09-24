"""v2.0: application shell, view modes, onboarding, directory, demo, What's New, library, search and data pages."""

import pytest

from conftest import login, players, run_event
from f1tracker import (auth, community, demo, library, moderation, notices, onboarding, roles, services as S,
                       storage, whatsnew)
from f1tracker import constants as C


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _league(master_client, name="Shell League", players_=None, logins=None, **extra):
    data = {"name": name, "year": "2026", "csrf_token": "tok", "join_mode": "invite",
            "player_name": players_ or [], "player_login": logins or []}
    data.update(extra)
    res = master_client.post("/careers/new", data=data)
    return res.headers["Location"].split("/career/")[1].split("/")[0]


# --------------------------------------------------------------------------- view modes

def test_race_master_can_view_as_other_roles_without_losing_permissions(app, master_client):
    auth.create_user("rm", "Rita", "password1")
    token = _league(master_client, players_=["Rita Racer"], logins=["rm"])
    with storage.session(token) as conn:
        roles.set_member(conn, "rm", "race_master", players(conn)[0])
    rita = _client(app, "rm")
    dash = rita.get(f"/career/{token}/dashboard").get_data(as_text=True)
    nav = f'href="/career/{token}/settings"'     # the League settings item in the sidebar
    assert nav in dash and "Spectator preview" in dash
    rita.post(f"/career/{token}/mode", data={"mode": "scorekeeper", "csrf_token": "tok"})
    dash = rita.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Viewing <b>Shell League</b> as <b>Scorekeeper</b>" in dash and nav not in dash
    assert "Results entry" in dash and "Back to Race Master" in dash
    # Display only: the real permission still works, and the setting is per league.
    assert rita.get(f"/career/{token}/settings").status_code == 200
    rita.post(f"/career/{token}/mode", data={"mode": "spectator", "csrf_token": "tok"})
    dash = rita.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "My Garage" not in dash and "Results entry" not in dash
    rita.post(f"/career/{token}/mode", data={"mode": "race_master", "csrf_token": "tok"})
    assert "Viewing <b>" not in rita.get(f"/career/{token}/dashboard").get_data(as_text=True)
    with storage.session(token) as conn:     # mode switches aren't league actions, so they aren't logged
        assert not [e for e in community.audit_entries(conn) if "mode" in (e["summary"] or "").lower()]


def test_lower_roles_cannot_pick_a_higher_mode(app, master_client):
    auth.create_user("sam", "Sam", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        roles.set_member(conn, "sam", "spectator")
    sam = _client(app, "sam")
    sam.post(f"/career/{token}/mode", data={"mode": "race_master", "csrf_token": "tok"})
    dash = sam.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert f'href="/career/{token}/settings"' not in dash
    assert sam.get(f"/career/{token}/settings").status_code == 403


# --------------------------------------------------------------------------- onboarding

def test_first_visit_shows_the_welcome_page(app, master_client):
    anon = app.test_client()
    page = anon.get("/").get_data(as_text=True)
    for text in ("Create a league", "Join a league", "Explore the demo", "Browse public leagues", "Race Master",
                 "Scorekeeper", "Spectator", "never uploaded"):
        assert text in page, text


def test_wizard_creates_a_league_with_a_preset_and_no_emails_unless_asked(app, master_client, monkeypatch):
    sent = []
    from f1tracker import mailer
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_later", lambda to, s, t, h=None: sent.append(to) or True)
    auth.set_setting("league_creation", "everyone")
    auth.create_user("ann", "Ann", "password1", email="ann@example.com")
    auth.create_user("bob", "Bob", "password1", email="bob@example.com")
    ann = _client(app, "ann")
    page = ann.get("/leagues/new").get_data(as_text=True)
    for step in ("League identity", "Season and calendar", "Teams and grid", "Scoring and Sprints", "Career systems",
                 "Roles, joining and visibility", "Your notifications", "Review and create"):
        assert step in page
    res = ann.post("/careers/new", data={
        "wizard": "1", "csrf_token": "tok", "name": "Ann's League", "year": "2026", "calendar": "standard", "sprints": "1",
        "player_name": ["Ann Racer", "Bob Racer"], "player_who": ["me", "invite"], "player_invite": ["", "bob"],
        "preset": "simple", "join_mode": "invite", "visibility": "private", "notify_preset": "inapp",
        "invite_username": [""], "invite_role": ["member"], "league_description": "Thursdays", "accent_color": "#3366ff"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        assert roles.effective_role(conn, auth.get_user("ann")) == "race_master"
        ann_driver = conn.execute("SELECT driver_id FROM career_members WHERE username = 'ann'").fetchone()[0]
        assert S.driver_map(conn)[ann_driver]["name"] == "Ann Racer"
        inv = conn.execute("SELECT * FROM invitations WHERE username = 'bob'").fetchone()
        assert inv and S.driver_map(conn)[inv["driver_id"]]["name"] == "Bob Racer"
        assert not community.features(conn)["predictions"]           # Simple preset
        assert conn.execute("SELECT COUNT(*) FROM market_windows").fetchone()[0] == 0
        assert notices.prefs(conn, "ann")["muted"]
        assert storage.get_meta(conn, "accent_color") == "#3366ff"
    assert sent == []                                                  # nobody emailed without the tick
    # Bob accepts and gets exactly the driver he was invited to drive.
    bob = _client(app, "bob")
    bob.post(f"/career/{token}/invitation", data={"decision": "accept", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT driver_id FROM career_members WHERE username = 'bob'").fetchone()[0] == inv["driver_id"]


def test_only_allowed_accounts_create_leagues_and_there_is_a_daily_limit(app, master_client):
    auth.create_user("joe", "Joe", "password1")
    joe = _client(app, "joe")
    assert joe.get("/leagues/new").status_code == 302                 # admins only by default
    assert joe.post("/careers/new", data={"name": "X", "csrf_token": "tok"}).status_code == 403
    auth.set_setting("league_creation", "everyone")
    for i in range(onboarding.LEAGUES_PER_DAY):
        joe.post("/careers/new", data={"name": f"L{i}", "year": "2026", "csrf_token": "tok"})
    before = len(storage.list_careers())
    joe.post("/careers/new", data={"name": "One too many", "year": "2026", "csrf_token": "tok"})
    assert len(storage.list_careers()) == before


# --------------------------------------------------------------------------- directory, reports, visibility

def test_only_leagues_that_opt_in_are_listed_and_reports_reach_admins(app, master_client):
    listed = _league(master_client, "Listed League")
    private = _league(master_client, "Secret Test League")
    master_client.post(f"/career/{listed}/settings", data={"csrf_token": "tok", "visibility": "listed", "join_mode": "requests",
                                                          "league_description": "Open to all"})
    anon = app.test_client()
    page = anon.get("/leagues").get_data(as_text=True)
    assert "Listed League" in page and "Secret Test League" not in page and "Open to all" in page
    with anon.session_transaction() as sess:
        sess["csrf"] = "tok"
    anon.post(f"/leagues/{listed}/report", data={"reason": "spam", "details": "ads", "csrf_token": "tok"})
    assert [r["league_name"] for r in moderation.reports()] == ["Listed League"]
    assert anon.get(f"/leagues/{private}/report").status_code == 404   # private leagues aren't even reportable
    moderation.set_delisted(listed, True)
    assert "Listed League" not in anon.get("/leagues").get_data(as_text=True)


def test_public_page_never_shows_private_data(app, master_client):
    token = _league(master_client, "Pub")
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "visibility": "public"})
    with storage.session(token) as conn:
        key = community.public_key(conn)
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev, complete=False)                          # an in-progress (draft) round
        conn.execute("UPDATE results SET notes = 'private note' WHERE event_id = ?", (ev["id"],))
    page = app.test_client().get(f"/public/{token}/{key}").get_data(as_text=True)
    assert "private note" not in page and "david@" not in page
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "visibility": "private"})
    assert app.test_client().get(f"/public/{token}/{key}").status_code == 404


# --------------------------------------------------------------------------- demo

def test_demo_is_private_temporary_and_sends_nothing(app, master_client, monkeypatch):
    real = _league(master_client, "Real League")
    anon = app.test_client()
    anon.get("/demo")
    with anon.session_transaction() as sess:
        sess["csrf"] = "tok"
    res = anon.post("/demo", data={"csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    assert token.startswith("demo-")
    with anon.session_transaction() as sess:   # starting the demo signs in a fresh session
        sess["csrf"] = "tok"
    dash = anon.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Demo league." in dash and "Real League" not in dash
    with storage.session(token) as conn:
        seasons = S.list_seasons(conn)
        assert [s["status"] for s in seasons] == [C.SEASON_COMPLETE, C.SEASON_ACTIVE]
        assert len(S.player_drivers(conn)) == 3
    assert anon.get(f"/career/{real}/dashboard").status_code == 403    # never a real league
    assert anon.get("/accounts").status_code == 302                       # no account changes
    res = anon.post(f"/career/{token}/members/invite", data={"username": "david", "role": "member", "csrf_token": "tok"},
                    follow_redirects=True)
    assert "That isn&#39;t available in the demo" in res.get_data(as_text=True)
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0
    guest = [u for u in (auth.get_user(n) for n in [anon_user(anon)]) if u][0]
    assert guest["is_demo"] and guest["username"] not in [u["username"] for u in auth.list_users()]
    # Restarting replaces the copy; old copies expire on their own.
    res = anon.post("/demo", data={"csrf_token": "tok"})
    token2 = res.headers["Location"].split("/career/")[1].split("/")[0]
    assert token2 != token and not storage.career_path(token).exists()
    from datetime import datetime, timedelta
    demo.cleanup(now=datetime.now() + timedelta(hours=demo.DEMO_HOURS + 1))
    assert not storage.career_path(token2).exists()


def anon_user(client):
    with client.session_transaction() as sess:
        return sess.get("user")


# --------------------------------------------------------------------------- what's new

def test_whats_new_shows_once_per_account(app, master_client, monkeypatch):
    from f1tracker import changelog
    entry = {"version": C.APP_VERSION, "title": "Big update", "date": "today", "overview": "", "items": [], "sections": [],
             "highlights": [{"text": "New interface", "children": []}], "action": []}
    monkeypatch.setattr(changelog, "entry", lambda base, version: entry)
    # Accounts created before the update see it; accounts created after it start with it seen.
    def from_before_the_update(name):
        with auth.accounts() as conn:
            conn.execute("DELETE FROM whats_new_seen WHERE username = ?", (name,))
    from_before_the_update("david")
    page = master_client.get("/").get_data(as_text=True)
    assert 'id="whats-new"' in page and "New interface" in page
    assert "I agree to them" in page and "Later" not in page.split('id="whats-new"')[1].split("</dialog>")[0]
    master_client.post("/whats-new", data={"choice": "agree", "csrf_token": "tok"})     # v2.1: box not ticked
    assert 'id="whats-new"' in master_client.get("/").get_data(as_text=True)            # still has to agree
    assert not whatsnew.acknowledged("david", C.APP_VERSION)
    master_client.post("/whats-new", data={"choice": "agree", "agree": "1", "csrf_token": "tok"})
    assert whatsnew.acknowledged("david", C.APP_VERSION)
    fresh = app.test_client()
    login(fresh, "david")
    assert 'id="whats-new"' not in fresh.get("/").get_data(as_text=True)          # remembered for the account
    auth.create_user("eve", "Eve", "password1")
    assert 'id="whats-new"' not in _client(app, "eve").get("/").get_data(as_text=True)  # new account: nothing to catch up on
    from_before_the_update("eve")
    assert 'id="whats-new"' in _client(app, "eve").get("/").get_data(as_text=True)  # per account, not global


# --------------------------------------------------------------------------- library, search, data

def test_league_list_pins_order_and_archive_are_personal(app, master_client):
    auth.create_user("ann", "Ann", "password1")
    a = _league(master_client, "Alpha")
    b = _league(master_client, "Bravo")
    for t in (a, b):
        with storage.session(t) as conn:
            roles.set_member(conn, "ann", "member")
    ann = _client(app, "ann")
    ann.post(f"/career/{b}/pin", data={"action": "pin", "csrf_token": "tok"})
    names = [l["name"] for l in library.user_leagues(auth.get_user("ann"))]
    assert names == ["Bravo", "Alpha"]
    ann.post(f"/career/{b}/pin", data={"action": "hide", "csrf_token": "tok"})
    assert [l["name"] for l in library.user_leagues(auth.get_user("ann"))] == ["Alpha"]
    with storage.session(b) as conn:        # hiding never leaves the league
        assert conn.execute("SELECT 1 FROM career_members WHERE username = 'ann'").fetchone()
    assert [l["name"] for l in library.user_leagues(auth.get_user("david"))][:2] != []
    page = ann.get("/").get_data(as_text=True)
    assert "Archived from your list (1)" in page


def test_search_only_covers_this_league(app, master_client):
    a = _league(master_client, "Alpha", players_=["Zed Unique"])
    b = _league(master_client, "Bravo", players_=["Quinn Other"])
    hits = master_client.get(f"/api/career/{a}/search?q=zed").get_json()["items"]
    assert any(h["label"] == "Zed Unique" for h in hits)
    assert master_client.get(f"/api/career/{a}/search?q=quinn").get_json()["items"] == []
    assert any(h["kind"] == "Help" for h in master_client.get(f"/api/career/{a}/search?q=reputation").get_json()["items"])


def test_standings_csv_backups_page_and_typed_delete(app, master_client):
    token = _league(master_client, "Data League")
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
    csv = master_client.get(f"/career/{token}/standings?format=csv&table=drivers").get_data(as_text=True)
    assert csv.splitlines()[0].startswith("Position,Driver,Team,Points")
    page = master_client.get(f"/career/{token}/backups?check=1").get_data(as_text=True)
    assert "All good" in page and "Danger zone" in page
    master_client.post(f"/career/{token}/delete", data={"confirm_name": "wrong", "csrf_token": "tok"})
    assert storage.career_path(token).exists()
    master_client.post(f"/career/{token}/delete", data={"confirm_name": "Data League", "csrf_token": "tok"})
    assert not storage.career_path(token).exists()
    assert any("before-delete" in p.name for p in (storage.backups_dir() / "auto" / token).glob("*"))


def test_permission_matrix_is_shown(app, master_client):
    token = _league(master_client)
    page = master_client.get(f"/career/{token}/settings").get_data(as_text=True)
    assert "What each role can do" in page and "Correct a completed round" in page
