"""4.0 test site: the F1_TRACKER_TEST_SITE switch (banner, nothing ever sent) and loading a live site backup."""

import io

from conftest import login
from f1tracker import auth, discord, mailer, offsite, outbox, push, storage, testsite


def _league(master_client, name):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def test_off_by_default_nothing_changes(app, master_client):
    assert not testsite.on()
    assert "TEST SITE" not in master_client.get("/").get_data(as_text=True)
    assert "Load the live site" not in master_client.get("/accounts").get_data(as_text=True)
    assert master_client.post("/settings/import-site-backup", data={"csrf_token": "tok"}).status_code == 404


def test_the_test_site_shows_a_banner_and_never_sends_anything(app, master_client, monkeypatch):
    """4.0 Phase 1: nothing is sent; every message is kept as a delivery preview instead (addresses masked)."""
    from f1tracker import ops
    import smtplib
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    monkeypatch.setattr(discord.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    assert "TEST SITE" in master_client.get("/").get_data(as_text=True)
    assert mailer.configured() and push.public_key() is None       # no device can subscribe to the test site
    discord.send_later("https://discord.com/api/webhooks/1/abc", ["hello"])
    assert mailer.send_later(["alex@example.com", "sam@example.com"], "Subject", "Text")
    assert mailer.send(["alex@example.com"], "Direct", "Body") == 1
    assert discord.post("https://discord.com/api/webhooks/1/abc", "direct post")
    push.send(["alex"], "League", "Alert")
    assert outbox.pending() == 0                                    # nothing queued to send
    kinds = [p["kind"] for p in ops.previews()]
    assert sorted(kinds) == ["discord", "discord", "email", "email", "push"]
    email = next(p for p in ops.previews() if p["title"] == "Subject")
    assert email["recipients"] == 2 and "alex@example.com" not in email["shown_to"] and "a•••@example.com" in email["shown_to"]
    outbox._send("email", {"to": ["a@example.com"], "subject": "s", "text": "t"})   # an imported leftover: dropped


def test_the_owner_loads_a_live_site_backup_onto_the_test_site(app, master_client, monkeypatch):
    live = _league(master_client, "Live League")
    auth.create_user("racer", "Racer", "Racer-Password-1")
    phrase = "correct horse battery staple"
    blob = master_client.post("/settings/offsite-backup", data={"csrf_token": "tok", "passphrase": phrase,
                                                                "passphrase2": phrase}).get_data()
    # the test site has its own, different data before the import
    auth.delete_user("racer")
    other = _league(master_client, "Test Only League")
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    page = master_client.get("/accounts").get_data(as_text=True)
    assert "Load the live site" in page
    res = master_client.post("/settings/import-site-backup", data={"csrf_token": "tok", "passphrase": phrase,
                                                                   "confirm": "nope", "file": (io.BytesIO(blob), "b.plbk")},
                             content_type="multipart/form-data", follow_redirects=True)
    assert "Nothing was changed" in res.get_data(as_text=True)
    res = master_client.post("/settings/import-site-backup", data={"csrf_token": "tok", "passphrase": "wrong one!!",
                                                                   "confirm": "REPLACE", "file": (io.BytesIO(blob), "b.plbk")},
                             content_type="multipart/form-data", follow_redirects=True)
    assert "Wrong passphrase" in res.get_data(as_text=True)
    res = master_client.post("/settings/import-site-backup", data={"csrf_token": "tok", "passphrase": phrase,
                                                                   "confirm": "REPLACE", "file": (io.BytesIO(blob), "b.plbk")})
    assert res.status_code == 302 and res.headers["Location"].endswith("/login")
    tokens = {c["token"] for c in storage.list_careers()}
    assert live in tokens and other not in tokens                   # exactly the live site's leagues
    assert auth.verify("racer", "Racer-Password-1")                 # and its logins
    c = app.test_client()
    login(c, "racer", "Racer-Password-1")
    assert c.get("/").status_code == 200


def test_a_backup_with_unexpected_files_is_refused(app, monkeypatch, tmp_path):
    import json
    import zipfile
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("accounts.db", b"x")
        z.writestr("../evil.txt", b"x")
        import hashlib
        z.writestr("manifest.json", json.dumps({"created_at": "x", "files": [
            {"name": "accounts.db", "sha256": hashlib.sha256(b"x").hexdigest()},
            {"name": "../evil.txt", "sha256": hashlib.sha256(b"x").hexdigest()}]}))
    blob = offsite.encrypt(buf.getvalue(), "a long passphrase")
    try:
        testsite.import_backup(blob, "a long passphrase")
        raise AssertionError("accepted")
    except offsite.BackupError as exc:
        assert "Unexpected file" in str(exc)


def test_the_owner_adds_a_league_with_one_round_left_and_rolls_it_over(app, master_client, monkeypatch):
    """4.0 test site: a fictional league one round from the end of its season, to try the finale and the rollover."""
    from f1tracker import golden, services as S
    assert master_client.post("/settings/test-final-round", data={"csrf_token": "tok"}).status_code == 404
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    assert "one round left" in master_client.get("/accounts").get_data(as_text=True)
    res = master_client.post("/settings/test-final-round", data={"csrf_token": "tok"})
    assert res.status_code == 302
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    assert master_client.get(f"/career/{token}/dashboard").status_code == 200
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        assert [e["status"] for e in evs].count("Complete") == len(evs) - 1 and evs[-1]["status"] != "Complete"
        member = conn.execute("SELECT * FROM career_members WHERE username = 'devon'").fetchone()
        assert member["role"] == "race_master" and member["driver_id"] == S.player_drivers(conn)[0]["id"]
        golden._enter(conn, evs[-1], __import__("random").Random(1))
    with storage.session(token) as conn:
        golden._submit(conn, S.events(conn, S.current_season_id(conn))[-1])
    assert master_client.get(f"/career/{token}/seasons/rollover").status_code == 200
    with storage.session(token) as conn:
        from f1tracker import seats
        latest = S.list_seasons(conn)[-1]
        review = seats.rollover_review(conn, latest["id"], latest["year"] + 1)
    data = {"year": str(latest["year"] + 1), "csrf_token": "tok"}
    data.update({f"decision_{r['driver']['id']}": "renew" for r in review["rows"] if r["needs_decision"]})
    assert master_client.post(f"/career/{token}/seasons/new", data=data).status_code == 302
    with storage.session(token) as conn:
        assert S.get_season(conn, S.current_season_id(conn))["year"] == latest["year"] + 1
