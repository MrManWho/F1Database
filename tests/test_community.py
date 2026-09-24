"""v1.13: league settings, race night, comments, predictions, profiles, public page, activity log, records."""

import io

from conftest import driver_id, login, players, pledge_all, run_event
from f1tracker import auth, community, feed, insights, services as S, storage
from f1tracker import constants as C


def _league(master_client, **extra):
    data = {"name": "Club League", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
            "player_login": ["", ""], "csrf_token": "tok", **extra}
    res = master_client.post("/careers/new", data=data)
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
    pledge_all(token)
    return token


def _member(app, master_client, token, username, driver_name=None):
    auth.create_user(username, username.title(), "password1")
    with storage.session(token) as conn:
        did = driver_id(conn, driver_name) if driver_name else None
        conn.execute("INSERT INTO career_members(username, driver_id) VALUES(?,?)", (username, did))
    client = app.test_client()
    login(client, username)
    return client


def _first_event(token):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))[0]


def test_features_are_chosen_at_setup_and_toggled_in_settings(app, master_client):
    token = _league(master_client, feature_comments="1")
    with storage.session(token) as conn:
        assert community.features(conn) == {"checkin": False, "comments": True, "predictions": False, "public": False}
    ana = _member(app, master_client, token, "ana", "Ana Silva")
    assert ana.get(f"/career/{token}/settings").status_code == 403
    assert ana.get(f"/career/{token}/predictions").status_code == 404
    assert "Predictions" not in ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    page = master_client.get(f"/career/{token}/settings").get_data(as_text=True)
    assert "Race-night check-in" in page and "Public results" in page   # v2.0: visibility is its own setting
    master_client.post(f"/career/{token}/settings", data={"feature_checkin": "1", "feature_predictions": "1",
                                                          "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert community.features(conn) == {"checkin": True, "comments": False, "predictions": True, "public": False}
    assert ana.get(f"/career/{token}/predictions").status_code == 200
    ev = _first_event(token)
    res = ana.post(f"/career/{token}/comments", data={"target": f"event:{ev['id']}", "body": "hi", "csrf_token": "tok"})
    assert res.status_code == 302
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0  # comments are off


def test_existing_leagues_get_sensible_defaults(career):
    with storage.session(career) as conn:
        feats = community.features(conn)
    assert feats == {**{k: v[2] for k, v in C.FEATURES.items()}, "public": False}
    assert feats["checkin"] is False and feats["comments"] is True


def test_race_night_time_checkins_and_countdown(app, master_client):
    token = _league(master_client, feature_checkin="1")
    ev = _first_event(token)
    ana = _member(app, master_client, token, "ana", "Ana Silva")
    # The league runs on New York time: 20:00 there (UTC-5 in March) is 01:00 UTC the next day.
    with storage.session(token) as conn:
        storage.set_meta(conn, "timezone", "America/New_York")
    master_client.post(f"/career/{token}/weekend/{ev['id']}/time",
                       data={"race_at": "2030-03-01T20:00", "csrf_token": "tok"})
    assert ana.post(f"/career/{token}/weekend/{ev['id']}/time",
                    data={"race_at": "2030-03-01T20:00", "csrf_token": "tok"}).status_code == 403
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["race_at"] == "2030-03-02T01:00+00:00"
    ana.post(f"/career/{token}/weekend/{ev['id']}/checkin", data={"status": "in", "csrf_token": "tok"})
    master_client.post(f"/career/{token}/weekend/{ev['id']}/checkin", data={"status": "maybe", "csrf_token": "tok"})
    with storage.session(token) as conn:
        rows, counts = community.checkins(conn, ev["id"])
    assert counts == {"in": 1, "maybe": 1, "out": 0}
    assert rows[0]["username"] == "ana" and rows[0]["driver"]["name"] == "Ana Silva"
    page = ana.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Who&#39;s racing?" in page or "Who's racing?" in page
    assert 'data-countdown="2030-03-02T01:00+00:00"' in page and "Fri, Mar 1 at 8:00 PM EST</time>" in page and "Lights out" in page
    dash = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Fri, Mar 1 at 8:00 PM EST" in dash and "Scheduled" in dash and "Who" in dash   # more than a week away
    # Once the race is done, check-ins close.
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
    res = ana.post(f"/career/{token}/weekend/{ev['id']}/checkin", data={"status": "out", "csrf_token": "tok"})
    assert res.status_code == 302
    with storage.session(token) as conn:
        assert conn.execute("SELECT status FROM checkins WHERE username = 'ana'").fetchone()[0] == "in"


def test_comments_reactions_and_fan_vote(app, master_client):
    token = _league(master_client, feature_comments="1")
    ev = _first_event(token)
    ana = _member(app, master_client, token, "ana", "Ana Silva")
    ben = _member(app, master_client, token, "ben", "Ben Okafor")
    target = f"event:{ev['id']}"
    ana.post(f"/career/{token}/comments", data={"target": target, "body": "See you on track <b>", "csrf_token": "tok"})
    page = ben.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "See you on track &lt;b&gt;" in page and "Paddock chat" in page
    res = ben.post(f"/career/{token}/react", data={"target": target, "emoji": "🔥", "csrf_token": "tok"},
                   headers={"X-Requested-With": "fetch"}).get_json()
    fire = next(r for r in res["reactions"] if r["emoji"] == "🔥")
    assert fire["count"] == 1 and fire["mine"] and fire["who"] == ["Ben"]
    ben.post(f"/career/{token}/react", data={"target": target, "emoji": "🔥", "csrf_token": "tok"})  # toggles off
    assert ben.post(f"/career/{token}/react", data={"target": "event:999", "emoji": "🔥", "csrf_token": "tok"},
                    headers={"X-Requested-With": "fetch"}).status_code == 302
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0] == 0
        comment = conn.execute("SELECT id FROM comments").fetchone()[0]
        assert any("Ana commented on R1" in n["text"] for n in feed.notifications_for(conn, "ben", None)[0])
    # Only the author or the Race Master can delete.
    ben.post(f"/career/{token}/comments/{comment}/delete", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1
    master_client.post(f"/career/{token}/comments/{comment}/delete", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0
    # News items take reactions and comments too.
    with storage.session(token) as conn:
        feed.post(conn, S.current_season_id(conn), "paddock", "Big news", "body")
        news_id = conn.execute("SELECT MAX(id) FROM news").fetchone()[0]
    res = ana.post(f"/career/{token}/comments", data={"target": f"news:{news_id}", "body": "wow", "csrf_token": "tok"})
    assert f"#news-{news_id}" in res.headers["Location"]
    news = ana.get(f"/career/{token}/news").get_data(as_text=True)
    assert "wow" in news and "1 comment" in news
    # Fan vote opens after the race.
    with storage.session(token) as conn:
        ana_id = driver_id(conn, "Ana Silva")
    ana.post(f"/career/{token}/weekend/{ev['id']}/fan-vote", data={"driver_id": ana_id, "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fan_votes").fetchone()[0] == 0
        run_event(conn, S.get_event(conn, ev["id"]))
    for c in (ana, ben):
        c.post(f"/career/{token}/weekend/{ev['id']}/fan-vote", data={"driver_id": ana_id, "csrf_token": "tok"})
    with storage.session(token) as conn:
        votes = community.fan_votes(conn, ev["id"], "ana")
        assert votes["total"] == 2 and votes["mine"] == ana_id and votes["tally"][0]["driver"]["name"] == "Ana Silva"
        review = insights.season_review(conn, S.current_season_id(conn))
    assert any(a["title"] == "Fans' choice" and a["driver"]["id"] == ana_id for a in review["awards"])
    page = ben.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Race story" in page and "Fans' Driver of the Day" in page


def test_predictions_lock_score_and_rank(app, master_client):
    token = _league(master_client, feature_predictions="1")
    ev = _first_event(token)
    ana = _member(app, master_client, token, "ana", "Ana Silva")
    ben = _member(app, master_client, token, "ben", "Ben Okafor")
    with storage.session(token) as conn:
        rows = S.weekend_rows(conn, ev["id"])
        order = [r["driver_id"] for r in rows]
        a_id, b_id = driver_id(conn, "Ana Silva"), driver_id(conn, "Ben Okafor")
    winner, second = order[0], order[1]
    ana.post(f"/career/{token}/weekend/{ev['id']}/predict", data={
        "pole": winner, "winner": winner, "fastest_lap": second, "top_player": a_id, "csrf_token": "tok"})
    ben.post(f"/career/{token}/weekend/{ev['id']}/predict", data={
        "pole": second, "winner": second, "top_player": b_id, "csrf_token": "tok"})
    # Invalid pick (not a player) is refused
    ben.post(f"/career/{token}/weekend/{ev['id']}/predict", data={"top_player": winner, "csrf_token": "tok"})
    page = ben.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Update picks" in page and "revealed once the race starts" in page
    finish = [winner, second] + [d for d in order if d not in (winner, second, a_id, b_id)] + [a_id, b_id]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]), order=finish, fl=second)
        table = community.leaderboard(conn, S.current_season_id(conn))
    # Ana: pole 3 + winner 5 + FL 2 + top player 2 = 12, perfect round. Ben: nothing.
    assert [(r["username"], r["points"], r["exact"]) for r in table] == [("ana", 12, 1), ("ben", 0, 0)]
    res = ana.post(f"/career/{token}/weekend/{ev['id']}/predict", data={"pole": second, "csrf_token": "tok"})
    assert res.status_code == 302
    with storage.session(token) as conn:
        assert conn.execute("SELECT pole_id FROM predictions WHERE username = 'ana'").fetchone()[0] == winner
    board = ben.get(f"/career/{token}/predictions").get_data(as_text=True)
    assert "Ana" in board and "12" in board and "pick-hit" in board


def test_predictions_lock_at_race_time(app, master_client):
    token = _league(master_client, feature_predictions="1")
    ev = _first_event(token)
    with storage.session(token) as conn:
        community.set_race_at(conn, ev["id"], "2000-01-01T00:00+00:00")
        assert community.predictions_locked(S.get_event(conn, ev["id"]))


def test_driver_profiles_photos_and_permissions(app, master_client, data_dir):
    token = _league(master_client)
    ana = _member(app, master_client, token, "ana", "Ana Silva")
    with storage.session(token) as conn:
        a_id, b_id = driver_id(conn, "Ana Silva"), driver_id(conn, "Ben Okafor")
    ana.post(f"/career/{token}/driver/{a_id}/profile", data={"number": "27", "nationality": "IE",
             "helmet_color": "#00ff88", "bio": "Fast on Sundays", "csrf_token": "tok"})
    assert ana.post(f"/career/{token}/driver/{b_id}/profile", data={"number": "5", "csrf_token": "tok"}).status_code == 403
    master_client.post(f"/career/{token}/driver/{b_id}/profile", data={"number": "27", "csrf_token": "tok"})  # taken
    with storage.session(token) as conn:
        prof = community.profile(conn, a_id)
        assert (prof["number"], prof["nationality"], prof["helmet_color"], prof["flag"]) == (27, "IE", "#00ff88", "🇮🇪")
        assert community.profile(conn, b_id)["number"] is None
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    ana.post(f"/career/{token}/driver/{a_id}/avatar", data={"avatar": (io.BytesIO(b"<svg/>"), "x.svg"), "csrf_token": "tok"},
             content_type="multipart/form-data")
    with storage.session(token) as conn:
        assert community.profile(conn, a_id)["avatar"] is None
    ana.post(f"/career/{token}/driver/{a_id}/avatar", data={"avatar": (io.BytesIO(png), "me.png"), "csrf_token": "tok"},
             content_type="multipart/form-data")
    with storage.session(token) as conn:
        name = community.profile(conn, a_id)["avatar"]
    assert name.endswith(".png") and (data_dir / "avatars" / token / name).exists()
    assert ana.get(f"/career/{token}/avatar/{name}").data == png
    outsider = app.test_client()
    auth.create_user("zed", "Zed", "password1")
    login(outsider, "zed")
    assert outsider.get(f"/career/{token}/avatar/{name}").status_code == 404
    assert ana.get(f"/career/{token}/avatar/..%2Faccounts.db").status_code == 404
    page = ana.get(f"/career/{token}/driver/{a_id}").get_data(as_text=True)
    assert "#27" in page and "Fast on Sundays" in page and "Edit profile" in page
    assert "Edit profile" not in ana.get(f"/career/{token}/driver/{b_id}").get_data(as_text=True)
    storage.delete_career(token)
    assert not (data_dir / "avatars" / token).exists()


def test_public_page_needs_the_feature_and_the_key(app, master_client):
    token = _league(master_client)
    ev = _first_event(token)
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
        key = community.public_key(conn)
    anon = app.test_client()
    assert anon.get(f"/public/{token}/{key}").status_code == 404
    master_client.post(f"/career/{token}/settings", data={"visibility": "public", "csrf_token": "tok"})
    settings = master_client.get(f"/career/{token}/settings").get_data(as_text=True)
    assert f"/public/{token}/{key}" in settings
    page = anon.get(f"/public/{token}/{key}").get_data(as_text=True)
    assert "Club League" in page and "Constructors" in page and "Latest: " in page and "Garage" not in page
    assert "🏆" in anon.get(f"/public/{token}/{key}/calendar").get_data(as_text=True)   # v2.0: its own page
    assert anon.get(f"/public/{token}/wrong").status_code == 404
    master_client.post(f"/career/{token}/settings/public-link", data={"csrf_token": "tok"})
    assert anon.get(f"/public/{token}/{key}").status_code == 404
    assert anon.get(f"/career/{token}/dashboard").status_code == 302  # the rest still needs a login


def test_activity_log_records_changes_for_the_race_master_only(app, master_client):
    token = _league(master_client)
    ev = _first_event(token)
    auth.create_user("kim", "Kim", "password1")
    with storage.session(token) as conn:
        conn.execute("INSERT INTO career_members(username, driver_id, scorekeeper, role) VALUES('kim', NULL, 1, 'scorekeeper')")
        ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
    kim = app.test_client()
    login(kim, "kim")
    for _ in range(3):  # autosaves merge into one line
        kim.post(f"/api/career/{token}/weekend/{ev['id']}", headers={"X-CSRF-Token": "tok"},
                 json={"results": [{"driver_id": ids[0], "race_position": 1}]})
    master_client.post(f"/career/{token}/calendar/add", data={"name": "Extra GP", "location": "X", "csrf_token": "tok"})
    with storage.session(token) as conn:
        log = community.audit_entries(conn)
    assert [(r["username"], r["action"]) for r in log][:2] == [("david", "Added a race"), ("kim", "Edited results")]
    assert sum(1 for r in log if r["action"] == "Edited results") == 1
    assert kim.get(f"/career/{token}/activity").status_code == 403
    page = master_client.get(f"/career/{token}/activity").get_data(as_text=True)
    assert "edited the results for Round 1 — " in page and "Kim" in page and "event id" not in page


def test_records_and_awards(master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        a_id = driver_id(conn, "Ana Silva")
        back = [d for d in ids if d != a_id]
        for ev in evs[:3]:
            run_event(conn, ev, order=[a_id] + back, quali=back + [a_id])
        data = insights.all_time_records(conn)
        review = insights.season_review(conn, sid)
    titles = {r["title"]: r for r in data["records"]}
    assert titles["Longest winning streak"]["driver"]["id"] == a_id
    assert titles["Longest winning streak"]["value"] == "3 wins in a row"
    assert titles["Win from furthest back"]["value"] == f"from P{len(ids)}"
    assert any(a["title"] == "Drive of the season" and a["driver"]["id"] == a_id for a in review["awards"])
    page = master_client.get(f"/career/{token}/records").get_data(as_text=True)
    assert "Record book" in page and "Longest winning streak" in page
    profile = master_client.get(f"/career/{token}/driver/{a_id}").get_data(as_text=True)
    assert "Trophy cabinet" in profile


def test_install_files_and_push_subscriptions(app, master_client):
    anon = app.test_client()
    assert anon.get("/manifest.webmanifest").get_json()["short_name"] == "Paddock Legacy"
    sw = anon.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Service-Worker-Allowed"] == "/"
    home = master_client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in home and 'name="push-key"' in home
    bad = master_client.post("/push/subscribe", json={"endpoint": "http://x"}, headers={"X-CSRF-Token": "tok"})
    assert bad.status_code == 400
    sub = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "k", "auth": "a"}}
    assert master_client.post("/push/subscribe", json=sub, headers={"X-CSRF-Token": "tok"}).get_json()["ok"]
    from f1tracker import push
    assert push.device_count("david") == 1
    master_client.post("/push/unsubscribe", json={"endpoint": sub["endpoint"]}, headers={"X-CSRF-Token": "tok"})
    assert push.device_count("david") == 0


def test_notifications_are_queued_for_phone_alerts(career, monkeypatch):
    """Alerts go to members of this league only (a site admin who isn't a member no longer gets them: v2.0)."""
    from f1tracker import delivery, push
    monkeypatch.setattr(push, "available", lambda: True)
    auth.create_user("boss", "Boss", "password1", is_master=True)
    auth.create_user("carson", "Carson", "password1")
    with storage.session(career) as conn:
        carson = driver_id(conn, "Carson Hayes")
        conn.execute("INSERT INTO career_members(username, driver_id) VALUES('carson', ?)", (carson,))
        feed.take_outbox()
        feed.notify(conn, carson, "New offer from Cadillac", "garage")
        feed.notify(conn, None, "Round 1 results are in")
    items = feed.take_outbox()
    assert [(i["token"], i["driver_id"]) for i in items] == [(career, carson), (career, None)]
    sends = delivery.plan(items)
    assert [(c, sorted(n), p["text"]) for c, n, p in sends] == [
        ("push", ["carson"], "New offer from Cadillac"), ("push", ["carson"], "Round 1 results are in")]
    assert delivery.plan(items) == []      # the same notifications are never delivered twice