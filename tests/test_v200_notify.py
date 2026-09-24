"""v2.0: notification preferences are per league membership; no email ever leaks from one league to another."""

import pytest

from conftest import login, players
from f1tracker import auth, delivery, feed, notices, push, roles, schema, services as S, storage


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    from f1tracker import mailer
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_later",
                        lambda to, subject, text, html=None: sent.append((list(to), subject, text)) or True)
    return sent


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(push, "available", lambda: True)
    monkeypatch.setattr(push, "send", lambda names, title, body, url=None: sent.append((sorted(names), title, body)) or 1)
    return sent


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _new_league(master_client, name, preset="important", players_=None, logins=None):
    data = {"name": name, "year": "2026", "csrf_token": "tok", "notify_preset": preset, "join_mode": "requests",
            "player_name": players_ or [], "player_login": logins or []}
    res = master_client.post("/careers/new", data=data)
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _submit_round(client, token, rnd=0):
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[rnd]
        rows = S.weekend_rows(conn, ev["id"])
    payload = {"mark_complete": True, "ai_untracked": True, "results": [
        {"driver_id": r["driver_id"], "race_position": i + 1, "qualifying_position": i + 1} for i, r in enumerate(rows)]}
    return ev, client.post(f"/api/career/{token}/weekend/{ev['id']}", json=payload, headers={"X-CSRF-Token": "tok"})


def _emails_to(outbox, address):
    return [m for m in outbox if address in m[0]]


# --------------------------------------------------------------------------- the confirmed bug

def test_account_in_two_leagues_only_gets_email_from_the_one_it_chose(app, master_client, outbox):
    """The reported bug: joining a separate Test league made its results email the account too."""
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    main = _new_league(master_client, "Main League", players_=["Carson Hayes"], logins=["carson"])
    test = _new_league(master_client, "Test League", players_=["Carson Test"], logins=["carson"])
    with storage.session(main) as conn:
        notices.save(conn, "carson", email={"results"})           # carson wants Main's results by email...
    with storage.session(test) as conn:
        assert not notices.prefs(conn, "carson")["email"]["results"]   # ...and Test never inherited it
    _submit_round(master_client, test)
    assert _emails_to(outbox, "carson@example.com") == []
    _submit_round(master_client, main)
    mine = _emails_to(outbox, "carson@example.com")
    assert len(mine) == 1 and 'for the league "Main League"' in mine[0][2]
    assert f"/career/{main}/notifications" in mine[0][2] and f"/career/{test}/" not in mine[0][2]


def test_creating_a_league_uses_the_creators_choice_and_nobody_else_is_subscribed(app, master_client):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    token = _new_league(master_client, "Fresh", preset="all", players_=["Carson Hayes"], logins=["carson"])
    with storage.session(token) as conn:
        assert notices.prefs(conn, "david")["email"]["results"]           # the creator chose Everything
        carson = notices.prefs(conn, "carson")
        assert carson["email"] == notices.preset_prefs("important")["email"]   # sensible default, not "all"
        assert not carson["email"]["results"]


def test_joining_applies_the_choice_made_in_the_request(app, master_client):
    auth.create_user("joe", "Joe", "password1", email="joe@example.com")
    token = _new_league(master_client, "Open")
    joe = _client(app, "joe")
    joe.post(f"/career/{token}/join", data={"role": "spectator", "notify_preset": "inapp", "csrf_token": "tok"})
    with storage.session(token) as conn:
        req = conn.execute("SELECT * FROM join_requests WHERE username = 'joe'").fetchone()
        assert req["notify_preset"] == "inapp"
    master_client.post(f"/career/{token}/members/request/{req['id']}/approve", data={"role": "spectator", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert notices.prefs(conn, "joe")["muted"]


def test_accepting_an_invitation_asks_for_this_leagues_notifications(app, master_client):
    auth.create_user("amy", "Amy", "password1", email="amy@example.com")
    token = _new_league(master_client, "Invite League")
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "join_mode": "invite", "race_window": "180",
                                                          "timezone": "UTC"})
    master_client.post(f"/career/{token}/members/invite", data={"username": "amy", "role": "member", "csrf_token": "tok"})
    home = _client(app, "amy").get("/").get_data(as_text=True)
    assert 'name="notify_preset"' in home
    _client(app, "amy").post(f"/career/{token}/invitation", data={"decision": "accept", "notify_preset": "all",
                                                                  "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert all(notices.prefs(conn, "amy")["email"].values())


def test_leaving_a_league_stops_its_email_and_forgets_its_preferences(app, master_client, outbox):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    token = _new_league(master_client, "Leaving", players_=["Carson Hayes"], logins=["carson"])
    with storage.session(token) as conn:
        notices.save(conn, "carson", preset="all")
        roles.remove_member(conn, "carson")
        assert conn.execute("SELECT COUNT(*) FROM member_notify WHERE username = 'carson'").fetchone()[0] == 0
    _submit_round(master_client, token)
    assert _emails_to(outbox, "carson@example.com") == []


def test_muting_one_league_keeps_the_other_fully_on(app, master_client, outbox, pushes):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    a = _new_league(master_client, "League A", players_=["Carson A"], logins=["carson"])
    b = _new_league(master_client, "League B", players_=["Carson B"], logins=["carson"])
    with storage.session(a) as conn:
        notices.save(conn, "carson", preset="all")
    with storage.session(b) as conn:
        notices.save(conn, "carson", preset="all")
    carson = _client(app, "carson")
    carson.post(f"/career/{b}/notifications", data={"muted": "1", "email": ["results"], "push": ["results"], "csrf_token": "tok"})
    with storage.session(b) as conn:
        assert notices.prefs(conn, "carson")["muted"]
        assert conn.execute("SELECT 1 FROM career_members WHERE username = 'carson'").fetchone()   # still in it
    _submit_round(master_client, b)
    _submit_round(master_client, a)
    assert len(_emails_to(outbox, "carson@example.com")) == 1
    assert all("League A" in title for names, title, _ in pushes if "carson" in names)
    page = carson.get(f"/career/{b}/notifications").get_data(as_text=True)
    assert "Mute League B" in page and "this league only" in page


def test_global_pause_and_unsubscribe_links(app, master_client, outbox):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    a = _new_league(master_client, "League A", players_=["Carson A"], logins=["carson"])
    b = _new_league(master_client, "League B", players_=["Carson B"], logins=["carson"])
    for t in (a, b):
        with storage.session(t) as conn:
            notices.save(conn, "carson", preset="all")
    _submit_round(master_client, a)
    link = next(w for w in _emails_to(outbox, "carson@example.com")[0][2].split() if "/unsubscribe/" in w)
    path = link.split("localhost", 1)[-1]
    anon = app.test_client()
    page = anon.get(path).get_data(as_text=True)
    assert "Stop emails from League A?" in page and "other leagues keep emailing you" in page
    with storage.session(a) as conn:
        assert notices.prefs(conn, "carson")["email"]["results"]           # a GET (mail scanners) changes nothing
    with anon.session_transaction() as sess:
        sess["csrf"] = "tok"
    anon.post(path, data={"scope": "league", "csrf_token": "tok"})
    with storage.session(a) as conn:
        assert not any(notices.prefs(conn, "carson")["email"].values())
    with storage.session(b) as conn:
        assert all(notices.prefs(conn, "carson")["email"].values())        # League B untouched
    outbox.clear()
    _submit_round(master_client, b)
    assert len(_emails_to(outbox, "carson@example.com")) == 1
    anon.post(path, data={"scope": "all", "csrf_token": "tok"})
    assert auth.get_user("carson")["email_paused"]
    outbox.clear()
    _submit_round(master_client, b, rnd=1)
    assert _emails_to(outbox, "carson@example.com") == []
    assert anon.get("/unsubscribe/forged-token").status_code == 400


def test_result_retries_and_duplicate_jobs_never_email_twice(app, master_client, outbox):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    token = _new_league(master_client, "Retry", players_=["Carson Hayes"], logins=["carson"])
    with storage.session(token) as conn:
        notices.save(conn, "carson", preset="all")
    ev, res = _submit_round(master_client, token)
    assert res.status_code == 200
    # The Race Master saves the completed round again (as a retry would): no second email.
    _submit_round(master_client, token)
    with app.test_request_context("/", base_url="http://localhost"):
        from f1tracker import mailer  # noqa: F401
        with storage.session(token) as conn:
            again = delivery.send_email(conn, token, "results", ["carson"], f"results-email:{ev['id']}", "s", "t", None,
                                        "http://localhost")
    assert again == 0
    assert len([m for m in _emails_to(outbox, "carson@example.com") if "results are in" in m[1]]) == 1


def test_duplicate_background_jobs_and_season_rollover_notice(career, pushes):
    auth.create_user("carson", "Carson", "password1")
    with storage.session(career) as conn:
        carson = conn.execute("SELECT id FROM drivers WHERE name = 'Carson Hayes'").fetchone()["id"]
        roles.set_member(conn, "carson", "member", carson)
        feed.take_outbox()
        feed.notify(conn, None, "The 2027 season has begun", "dashboard", category="season", dedupe="season-start:9")
        feed.notify(conn, None, "The 2027 season has begun", "dashboard", category="season", dedupe="season-start:9")
    items = feed.take_outbox()
    first = delivery.plan(items)
    assert len(first) == 1                  # the same season start queued twice goes out once
    assert delivery.plan(items) == []       # and a second job over the same items sends nothing


def test_masters_only_notices_never_reach_members(career, pushes):
    auth.create_user("carson", "Carson", "password1")
    auth.create_user("rm", "League RM", "password1")
    with storage.session(career) as conn:
        roles.set_member(conn, "carson", "member", None)
        roles.set_member(conn, "rm", "race_master", None)
        feed.take_outbox()
        feed.notify(conn, None, "Pat asked to join as Pat Racer", "members", category="join_requests")
        rows, _ = feed.notifications_for(conn, "carson", None)
        assert rows == []
        rows, _ = feed.notifications_for(conn, "rm", None, is_master=True)
        assert rows and "asked to join" in rows[0]["text"]
    delivery.plan(feed.take_outbox())
    assert pushes == [] or all("carson" not in n for n, *_ in pushes)
    sends = [s for s in pushes]
    assert all(names == ["rm"] for names, *_ in sends)


def test_rate_limit_holds_a_notification_loop(career):
    with storage.session(career) as conn:
        allowed = [notices.claim(conn, f"k{i}", "announcements", "email") for i in range(40)]
        assert allowed.count(True) == notices.SAME_CATEGORY_PER_10_MIN
        held = conn.execute("SELECT COUNT(*) FROM deliveries WHERE status = 'held'").fetchone()[0]
        assert held == 40 - notices.SAME_CATEGORY_PER_10_MIN


def test_several_leagues_several_people_different_choices(app, master_client, outbox):
    for n in ("ana", "ben", "cy"):
        auth.create_user(n, n.title(), "password1", email=f"{n}@example.com")
    one = _new_league(master_client, "One", players_=["Ana One", "Ben One"], logins=["ana", "ben"])
    two = _new_league(master_client, "Two", players_=["Ben Two", "Cy Two"], logins=["ben", "cy"])
    with storage.session(one) as conn:
        notices.save(conn, "ana", email={"results"})
        notices.save(conn, "ben", preset="inapp")
    with storage.session(two) as conn:
        notices.save(conn, "ben", email={"results"})
        notices.save(conn, "cy", email=set())
    _submit_round(master_client, one)
    got = sorted(a for to, _s, _t in outbox for a in to)
    assert got == ["ana@example.com"]
    outbox.clear()
    _submit_round(master_client, two)
    assert sorted(a for to, _s, _t in outbox for a in to) == ["ben@example.com"]


def test_existing_memberships_keep_what_they_had(tmp_path):
    """Migration: a pre-2.0 membership keeps race-result emails if the account had them on; nothing else."""
    auth.create_user("old", "Old", "password1", email="old@example.com")
    auth.create_user("off", "Off", "password1", email="off@example.com")
    auth.set_email("off", "off@example.com", False)
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Old League", 2026, ["A", "B"])
        conn.execute("INSERT INTO career_members(username, role) VALUES('old', 'member'), ('off', 'member')")
        conn.execute("DROP TABLE member_notify")
        conn.execute("UPDATE meta SET value = '17' WHERE key = 'schema_version'")
    with storage.session(token) as conn:
        old, off = notices.prefs(conn, "old"), notices.prefs(conn, "off")
    assert old["email"]["results"] and sum(old["email"].values()) == 1 and all(old["push"].values())
    assert not any(off["email"].values())


def test_delivery_log_is_race_master_only_and_has_no_content(app, master_client, outbox):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    token = _new_league(master_client, "Logged", players_=["Carson Hayes"], logins=["carson"])
    with storage.session(token) as conn:
        notices.save(conn, "carson", preset="all")
    _submit_round(master_client, token)
    page = master_client.get(f"/career/{token}/deliveries").get_data(as_text=True)
    assert "Results: R1" in page and "carson@example.com" not in page
    assert _client(app, "carson").get(f"/career/{token}/deliveries").status_code == 403
