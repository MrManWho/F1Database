"""Telemetry import: a league's own upload link takes one session's results from the game, which then wait in the
round's Import dialog. Nothing is saved to the results until someone applies and saves them."""

import json

from f1tracker import services as S, storage, telemetry

from conftest import login  # noqa: F401  (fixtures come from conftest)


def _league(client):
    res = client.post("/careers/new", data={"name": "Tele", "year": "2026", "player_name": ["Ana Silva"],
                                             "player_login": [""], "csrf_token": "tok"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _summary(**session):
    return {"session": {"track": "Monza", "session_type": "Race", "session_type_id": 15, "ai_difficulty": 87, **session},
            "session_uid": "123456789",
            "results": [{"position": 1, "name": "VERSTAPPEN", "team": "Red Bull Racing", "status": "Finished",
                         "best_lap_ms": 81500, "best_lap": "1:21.500"},
                        {"position": 2, "name": "Ana Silva", "team": "Aston Martin", "status": "Finished",
                         "best_lap_ms": 81234, "best_lap": "1:21.234"},
                        {"position": 0, "name": "NORRIS", "team": "McLaren", "status": "DNF", "reason": "Mechanical failure"}],
            "events": [{"code": "PENA", "driver": "VERSTAPPEN", "seconds": 5, "lap": 12}, {"code": "SPTP"}]}


def _turn_on(client, token):
    client.post(f"/career/{token}/settings", data={"section": "career", "team_life": "1", "feature_telemetry": "1",
                                                   "feature_comments": "1", "csrf_token": "tok"})
    client.post(f"/career/{token}/settings/telemetry", data={"action": "new", "csrf_token": "tok"})
    with storage.session(token) as conn:
        return telemetry.upload_key(conn)


def test_upload_needs_the_feature_and_the_leagues_key(master_client, app):
    token = _league(master_client)
    outsider = app.test_client()
    # Off by default: nothing is accepted, and the answer doesn't say why.
    with storage.session(token) as conn:
        assert not telemetry.enabled(conn) and telemetry.upload_key(conn) is None
    assert outsider.post(f"/api/telemetry/{token}/whatever", json=_summary()).status_code == 403
    key = _turn_on(master_client, token)
    assert key
    assert outsider.post(f"/api/telemetry/{token}/wrong-key", json=_summary()).status_code == 403
    assert outsider.post(f"/api/telemetry/nosuchleague/{key}", json=_summary()).status_code == 403
    res = outsider.post(f"/api/telemetry/{token}/{key}", json=_summary())   # no sign-in and no form token needed
    assert res.status_code == 200 and res.get_json()["ok"]
    # The same session sent again replaces the first copy.
    outsider.post(f"/api/telemetry/{token}/{key}", json=_summary())
    with storage.session(token) as conn:
        ups = telemetry.recent(conn)
        assert len(ups) == 1 and ups[0]["track"] == "Monza" and ups[0]["cars"] == 3
        data = telemetry.get(conn, ups[0]["id"])
        assert [e["code"] for e in data["events"]] == ["PENA"]          # unused event types are dropped
        assert [r["fastest_lap"] for r in data["results"]] == [False, True, False]
        assert data["results"][-1]["status"] == "DNF"
        # Nothing reached the results.
        ev = S.events(conn, S.current_season_id(conn))[0]
        assert all(r["race_position"] is None for r in S.weekend_rows(conn, ev["id"]))
    # A new link replaces the old one; turning it off stops uploads.
    master_client.post(f"/career/{token}/settings/telemetry", data={"action": "new", "csrf_token": "tok"})
    assert outsider.post(f"/api/telemetry/{token}/{key}", json=_summary()).status_code == 403
    master_client.post(f"/career/{token}/settings/telemetry", data={"action": "off", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert telemetry.upload_key(conn) is None


def test_bad_uploads_are_refused(master_client, app):
    token = _league(master_client)
    key = _turn_on(master_client, token)
    c = app.test_client()
    assert c.post(f"/api/telemetry/{token}/{key}", json={"results": []}).status_code == 400
    assert c.post(f"/api/telemetry/{token}/{key}", data="not json").status_code == 400
    big = _summary()
    big["results"] = big["results"] * 9
    assert c.post(f"/api/telemetry/{token}/{key}", json=big).status_code == 400
    huge = json.dumps({**_summary(), "pad": "x" * (telemetry.MAX_BYTES + 10)})
    assert c.post(f"/api/telemetry/{token}/{key}", data=huge, content_type="application/json").status_code == 413


def test_round_page_offers_uploads_and_remembers_matches(master_client, app):
    token = _league(master_client)
    key = _turn_on(master_client, token)
    app.test_client().post(f"/api/telemetry/{token}/{key}", json=_summary())
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        upload_id = telemetry.recent(conn)[0]["id"]
        ana = conn.execute("SELECT id FROM drivers WHERE name = 'Ana Silva'").fetchone()["id"]
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Import results" in page and f'data-tele-id="{upload_id}"' in page and "Monza · Race" in page
    got = master_client.get(f"/career/{token}/telemetry/{upload_id}").get_json()
    assert got["ok"] and got["upload"]["session"]["ai_difficulty"] == 87
    res = master_client.post(f"/career/{token}/telemetry/applied", headers={"X-CSRF-Token": "tok"},
                             json={"event_id": ev["id"], "upload_id": upload_id,
                                   "names": {"Ana Silva|Aston Martin": ana, "Ghost|X": 999999}})
    assert res.get_json()["ok"]
    assert master_client.get(f"/career/{token}/telemetry/names").get_json()["names"] == {"Ana Silva|Aston Martin": ana}
    with storage.session(token) as conn:
        assert telemetry.recent(conn)[0]["used_round"] == ev["round_number"]
    # The settings page shows the link; exports leave the key and the uploads out.
    settings = master_client.get(f"/career/{token}/settings/career").get_data(as_text=True)
    assert f"/api/telemetry/{token}/{key}" in settings
    export = json.loads(storage.export_json(token))
    assert "telemetry_uploads" not in export and all(m["key"] != "telemetry_key" for m in export["meta"])


def test_round_page_without_the_feature_is_unchanged(master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "Import screenshot" in page and "data-tele-get" not in page
    assert master_client.get(f"/career/{token}/telemetry/1").status_code == 404


def test_import_in_a_real_browser(app, master_client, live_server):
    """An upload opened in the round's Import dialog fills the results table (positions, a DNF, fastest lap, AI level)
    with game-style names (surnames in capitals), and the next import remembers who was who."""
    from conftest import open_browser
    token = _league(master_client)
    key = _turn_on(master_client, token)
    with storage.session(token) as conn:
        storage.set_meta(conn, "timezone", "UTC")
        ev = S.events(conn, S.current_season_id(conn))[0]
        entrants = [(r["driver_id"], r["driver"]["name"], r["team"]["name"], r["driver"]["is_player"])
                    for r in S.weekend_rows(conn, ev["id"])]
    results = []
    for i, (_did, name, team, is_player) in enumerate(entrants):
        results.append({"position": i + 1, "name": name if is_player else name.split()[-1].upper(), "team": team,
                        "status": "DNF" if i == len(entrants) - 1 else "Finished",
                        "best_lap_ms": 90000 - (500 if i == 3 else 0) + i, "best_lap": "1:30.000"})
    up = app.test_client().post(f"/api/telemetry/{token}/{key}",
                                json={"session": {"track": "Melbourne", "session_type": "Race", "session_type_id": 15,
                                                  "ai_difficulty": 91}, "results": results, "session_uid": "77"})
    assert up.status_code == 200
    pw, browser = open_browser()
    try:
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_server + "/login")
        page.fill("input[name=username]", "devon"); page.fill("input[name=password]", "password1")
        page.press("input[name=password]", "Enter"); page.wait_for_load_state()
        page.goto(f"{live_server}/career/{token}/weekend/{ev['id']}")
        page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")
        page.click('[data-dialog="import-dialog"]')
        page.click("[data-tele-id]")
        page.wait_for_selector("#imp-step-review:not([hidden])", timeout=10000)
        assert page.locator("#imp-session2").input_value() == "race"
        assert "Melbourne" in page.locator("#imp-detected").inner_text()
        picked = page.eval_on_selector_all("#imp-rows tr", "trs => trs.map(t => t.querySelector('select').value)")
        assert [int(p) for p in picked] == [e[0] for e in entrants]      # every driver matched, in order
        assert not page.locator("#imp-blocking").inner_text().strip(), page.locator("#imp-blocking").inner_text()
        page.click("#imp-apply")
        page.wait_for_timeout(2500)
        with storage.session(token) as conn:
            rows = {r["driver_id"]: r for r in S.weekend_rows(conn, ev["id"])}
            event = S.get_event(conn, ev["id"])
        assert [rows[e[0]]["race_position"] for e in entrants] == list(range(1, len(entrants) + 1))
        assert rows[entrants[-1][0]]["result_status"] == "DNF"
        assert rows[entrants[3][0]]["fastest_lap"] == 1
        assert event["ai_difficulty"] == 91 and event["status"] != "Complete"
        assert errors == []
    finally:
        browser.close()
        pw.stop()
    names = master_client.get(f"/career/{token}/telemetry/names").get_json()["names"]
    assert len(names) == len(entrants)
