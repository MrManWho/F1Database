"""v2.0 announcements: targeting, scheduling, expiry, pinning, league-scoped email and one delivery per send."""

from conftest import login, players
from f1tracker import announcements, auth, community, delivery, feed, mailer, notices, roles, storage


def _league(master_client, name="News League", players_=("Ana Silva",), logins=("ana",)):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite", "player_name": list(players_),
                                                   "player_login": list(logins)})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        storage.set_meta(conn, "timezone", "UTC")
    return token


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _people():
    auth.create_user("ana", "Ana", "password1", email="ana@example.com")
    auth.create_user("sam", "Sam", "password1", email="sam@example.com")


def test_targeted_announcement_reaches_only_that_role(app, master_client):
    _people()
    token = _league(master_client)
    with storage.session(token) as conn:
        roles.set_member(conn, "sam", "spectator")
    master_client.post(f"/career/{token}/announcements", data={"csrf_token": "tok", "title": "Drivers briefing",
                                                               "body": "Track limits at turn 4.", "audience": "drivers"})
    ana, sam = _client(app, "ana"), _client(app, "sam")
    from conftest import pledge_all
    pledge_all(token)
    assert "Drivers briefing" in ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Drivers briefing" not in sam.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Drivers briefing" in master_client.get(f"/career/{token}/announcements").get_data(as_text=True)
    with storage.session(token) as conn:
        rows = {r["username"] for r in conn.execute("SELECT username FROM notifications WHERE category = 'announcements'")}
        assert rows == {"ana"}
        assert "posted an announcement: Drivers briefing (for drivers)" in community.audit_entries(conn)[0]["summary"]
    # Only Race Masters post.
    assert ana.post(f"/career/{token}/announcements", data={"csrf_token": "tok", "title": "Hi all"}).status_code == 403


def test_recipient_preview_counts_by_preference(app, master_client, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    _people()
    token = _league(master_client)
    with storage.session(token) as conn:
        roles.set_member(conn, "sam", "member")
        notices.save(conn, "ana", preset="all")
        notices.save(conn, "sam", preset="inapp")
        assert announcements.preview(conn, "all", exclude="david") == {"app": 2, "push": 1, "email": 1}
        assert announcements.preview(conn, "drivers", exclude="david")["app"] == 1
    got = master_client.get(f"/career/{token}/announcements/preview?audience=drivers").get_json()
    assert got["app"] == 1


def test_scheduled_announcement_goes_out_once_when_due_and_expires(app, master_client):
    _people()
    token = _league(master_client)
    with storage.session(token) as conn:
        future = "2999-01-01T10:00+00:00"
        ann = announcements.create(conn, "david", "Season launch", "", publish_at=future)
        assert not announcements.get(conn, ann)["published_at"]
        assert announcements.publish_due(conn) == 0
        conn.execute("UPDATE announcements SET publish_at = '2020-01-01T10:00+00:00' WHERE id = ?", (ann,))
        feed.take_outbox()
    master_client.get(f"/career/{token}/dashboard")              # opening the league sends due ones
    with storage.session(token) as conn:
        assert announcements.get(conn, ann)["published_at"]
        assert announcements.publish_due(conn) == 0 and not announcements.publish(conn, ann)
        assert conn.execute("SELECT COUNT(*) FROM notifications WHERE ref = ?", (f"announcement:{ann}",)).fetchone()[0] == 2
        conn.execute("UPDATE announcements SET expires_at = '2020-06-01T10:00+00:00' WHERE id = ?", (ann,))
        assert announcements.visible(conn, "ana", "member", 1) == []
        try:
            announcements.create(conn, "david", "Bad dates", "", publish_at="2999-01-02T00:00+00:00",
                                 expires_at="2999-01-01T00:00+00:00")
            raise AssertionError("expected a validation error")
        except announcements.ValidationError:
            pass


def test_pinned_first_and_take_down(app, master_client):
    _people()
    token = _league(master_client)
    with storage.session(token) as conn:
        a = announcements.create(conn, "david", "Older but pinned", "", pinned=True)
        announcements.create(conn, "david", "Newer", "")
        feed.take_outbox()
        assert [x["title"] for x in announcements.visible(conn, "ana", "member", players(conn)[0])] == \
            ["Older but pinned", "Newer"]
    master_client.post(f"/career/{token}/announcements/{a}/end", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert [x["title"] for x in announcements.visible(conn, "ana", "member", players(conn)[0])] == ["Newer"]


def test_email_is_one_league_scoped_delivery(app, master_client, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    _people()
    token = _league(master_client)
    other = _league(master_client, "Other League")
    with storage.session(token) as conn:
        roles.set_member(conn, "sam", "member")
        notices.save(conn, "ana", preset="all")
        notices.save(conn, "sam", preset="all")
    with storage.session(other) as conn:
        notices.save(conn, "ana", preset="inapp")
        feed.take_outbox()
    with storage.session(token) as conn:
        announcements.create(conn, "david", "Rules update", "Read the new rules.", email=True)
    sends = delivery.plan(feed.take_outbox(), exclude="david")
    emails = [s for s in sends if s[0] == "email"]
    assert len(emails) == 1 and sorted(u for u, _ in emails[0][1]) == ["ana", "sam"]
    assert emails[0][2]["league"] == "News League"
    with storage.session(token) as conn:
        log = notices.delivery_log(conn)
        assert {r["key"] for r in log} == {"announcement:1"}
        assert [r["recipients"] for r in log if r["channel"] == "email"] == [2]
    with storage.session(other) as conn:
        assert notices.delivery_log(conn) == [] and not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'announcements'").fetchone()

