"""Telemetry import: a league's own upload link takes one session's results from the game, which then wait in the
round's Import dialog. Nothing is saved to the results until someone applies and saves them."""

import json

import pytest

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
    assert "Upload link" in settings and f"/api/telemetry/{token}/{key}" in master_client.get(f"/career/{token}/telemetry-link").get_data(as_text=True)
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


def test_race_master_chooses_what_scorekeepers_may_do(master_client, app):
    from conftest import login
    from f1tracker import auth, roles
    token = _league(master_client)
    key = _turn_on(master_client, token)
    app.test_client().post(f"/api/telemetry/{token}/{key}", json=_summary())
    for name, role in (("kim", "scorekeeper"), ("max", "member")):
        auth.create_user(name, name.title(), "password1")
        with storage.session(token) as conn:
            roles.set_member(conn, name, role)
    kim, mx = app.test_client(), app.test_client()
    login(kim, "kim"); login(mx, "max")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        upload_id = telemetry.recent(conn)[0]["id"]
    rnd = f"/career/{token}/weekend/{ev['id']}"
    # Defaults: Scorekeepers import, but the upload link stays with the Race Master.
    assert f'data-tele-id="{upload_id}"' in kim.get(rnd).get_data(as_text=True)
    assert kim.get(f"/career/{token}/telemetry/{upload_id}").status_code == 200
    assert kim.get(f"/career/{token}/telemetry-link").status_code == 403
    assert kim.post(f"/career/{token}/settings/telemetry", data={"action": "off", "csrf_token": "tok"}).status_code == 403
    assert mx.get(f"/career/{token}/telemetry/{upload_id}").status_code == 403
    assert mx.get(f"/career/{token}/telemetry-link").status_code == 403
    page = master_client.get(f"/career/{token}/settings/roles").get_data(as_text=True)
    assert 'name="perm_scorekeeper_telemetry_import" value="1" checked' in page
    assert 'name="perm_scorekeeper_telemetry_link" value="1" >' in page
    # The Race Master swaps them round.
    master_client.post(f"/career/{token}/settings", data={"section": "roles", "perm_form": "1", "join_mode": "invite",
                                                          "perm_scorekeeper_telemetry_link": "1", "csrf_token": "tok"})
    assert "data-tele-get" not in kim.get(rnd).get_data(as_text=True)
    assert kim.get(f"/career/{token}/telemetry/{upload_id}").status_code == 404
    assert kim.post(f"/career/{token}/telemetry/applied", headers={"X-CSRF-Token": "tok"},
                    json={"event_id": ev["id"], "names": {}}).status_code == 403
    assert key in kim.get(f"/career/{token}/telemetry-link").get_data(as_text=True)
    kim.post(f"/career/{token}/settings/telemetry", data={"action": "new", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert telemetry.upload_key(conn) not in (None, key)
    log = master_client.get(f"/career/{token}/activity").get_data(as_text=True)
    assert "telemetry upload link" in log
    # Saving other settings sections never resets these choices.
    master_client.post(f"/career/{token}/settings", data={"section": "career", "team_life": "1", "feature_telemetry": "1",
                                                          "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert roles.granted(conn, "scorekeeper", "telemetry_link") and not roles.granted(conn, "scorekeeper", "telemetry_import")
        assert not roles.granted(conn, "member", "telemetry_link")


@pytest.mark.engine3
@pytest.mark.pacerequired
def test_fill_a_whole_weekend_from_the_game(master_client, app):
    """Every session of a round's race night is found by circuit; weather and race times fill only blanks."""
    from f1tracker import ai3, weather
    token = _league(master_client)
    key = _turn_on(master_client, token)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
        S.place_players(conn, sid, {S.player_drivers(conn)[0]["id"]: (teams["Williams"], 1)})
        ev = next(e for e in S.events(conn, sid) if "chin" in e["name"].lower())
        rows = S.weekend_rows(conn, ev["id"])
        ana = next(r for r in rows if r["driver"]["name"] == "Ana Silva")
        mate = next(r for r in rows if r["team"]["name"] == ana["team"]["name"] and r["driver_id"] != ana["driver_id"])
        other = next(r for r in rows if r["team"]["name"] != ana["team"]["name"])
    team = ana["team"]["name"]

    def session(type_id, kind, weather_seen, results):
        return {"session": {"track": "Shanghai", "session_type": kind, "session_type_id": type_id, "ai_difficulty": 81,
                            "weather": weather_seen[0], "weather_seen": weather_seen}, "session_uid": str(type_id),
                "results": results, "events": []}
    me = {"name": "Ana Silva", "team": team, "race_number": 7}
    ai = {"name": mate["driver"]["name"].upper(), "team": team, "race_number": 8, "ai": True}
    foe = {"name": other["driver"]["name"].upper(), "team": other["team"]["name"], "race_number": 9, "ai": True}
    uploader = app.test_client()
    uploader.post(f"/api/telemetry/{token}/{key}", json=session(8, "Short Qualifying", ["Clear"], [
        {**ai, "position": 1, "status": "Finished", "best_lap_ms": 91000},
        {**me, "position": 2, "status": "Finished", "best_lap_ms": 91500},
        {**foe, "position": 3, "status": "Finished", "best_lap_ms": 92000}]))
    race_type = 16 if ev["is_sprint"] else 15
    uploader.post(f"/api/telemetry/{token}/{key}", json=session(race_type, "Race", ["Light cloud", "Light rain"], [
        {**me, "position": 1, "status": "Finished", "laps": 56, "race_time_s": 5400.5, "penalty_s": 5, "best_lap_ms": 95000},
        {**ai, "position": 2, "status": "Finished", "laps": 56, "race_time_s": 5410.25, "best_lap_ms": 95200},
        {**foe, "position": 3, "status": "DNF", "laps": 20}]))
    # Another circuit's session never counts for this round.
    uploader.post(f"/api/telemetry/{token}/{key}", json={**session(15, "Race", ["Clear"], [{**foe, "position": 1}]),
                                                         "session": {"track": "Monza", "session_type_id": 15}})
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}?stage=sessions").get_data(as_text=True)
    assert "Fill the whole weekend" in page and "Qualifying <span" in page
    got = master_client.get(f"/career/{token}/weekend/{ev['id']}/telemetry").get_json()
    assert got["ok"] and [q["session"]["session_type_id"] for q in got["sessions"]["qualifying"]] == [8]
    assert got["sessions"]["race"]["results"][0]["race_time_s"] == 5400.5 and got["sessions"]["sprint"] is None
    ids = {"quali": [got["sessions"]["qualifying"][0]["id"]], "race": [got["sessions"]["race"]["id"]]}
    pace = [{"driver_id": ana["driver_id"], "session": "gp", "quali_time": 91.5, "mate_quali_time": 91.0,
             "race_time": 5405.5, "bench_race_time": 5410.25, "laps": 56}]
    res = master_client.post(f"/career/{token}/weekend/{ev['id']}/telemetry/extras", headers={"X-CSRF-Token": "tok"},
                             json={"sessions": ids, "pace": pace, "names": {"Ana Silva|" + team: ana["driver_id"]},
                                   "upload_ids": ids["quali"] + ids["race"]}).get_json()
    assert res["ok"], res
    with storage.session(token) as conn:
        assert weather.get(conn, ev["id"]) == {"quali": "dry", "race": "changing"}
        p = ai3.pace_input(conn, ev["id"], ana["driver_id"], "gp")
        assert (p["quali_time"], p["mate_quali_time"], p["race_time"], p["bench_race_time"], p["laps"]) == \
            (91.5, 91.0, 5405.5, 5410.25, 56)
        assert telemetry.names(conn)["Ana Silva|" + team] == ana["driver_id"]
    # A second fill keeps what's there: weather and times already recorded aren't replaced.
    master_client.post(f"/career/{token}/weekend/{ev['id']}/weather", data={"weather_quali": "overcast",
                                                                           "weather_race": "changing", "csrf_token": "tok"})
    pace[0]["race_time"] = 1.0
    res = master_client.post(f"/career/{token}/weekend/{ev['id']}/telemetry/extras", headers={"X-CSRF-Token": "tok"},
                             json={"sessions": ids, "pace": pace}).get_json()
    assert res["ok"] and res["done"] == []
    with storage.session(token) as conn:
        assert weather.get(conn, ev["id"])["quali"] == "overcast"
        assert ai3.pace_input(conn, ev["id"], ana["driver_id"], "gp")["race_time"] == 5405.5
    # Members can't use it.
    auth_user = "max"
    from f1tracker import auth, roles
    from conftest import login
    auth.create_user(auth_user, "Max", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, auth_user, "member")
    mx = app.test_client(); login(mx, auth_user)
    assert mx.get(f"/career/{token}/weekend/{ev['id']}/telemetry").status_code == 403
    assert mx.post(f"/career/{token}/weekend/{ev['id']}/telemetry/extras", headers={"X-CSRF-Token": "tok"},
                   json={}).status_code == 403


@pytest.mark.engine3
@pytest.mark.pacerequired
def test_fill_weekend_in_a_real_browser(app, master_client, live_server):
    """One click fills a Sprint weekend: qualifying from Q1-Q3, the Sprint, the race, the weather and the player's
    race times against their AI teammate. Nothing is submitted."""
    from conftest import open_browser
    from f1tracker import ai3, weather
    token = _league(master_client)
    key = _turn_on(master_client, token)
    with storage.session(token) as conn:
        storage.set_meta(conn, "timezone", "UTC")
        sid = S.current_season_id(conn)
        teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
        ana = S.player_drivers(conn)[0]["id"]
        S.place_players(conn, sid, {ana: (teams["Williams"], 1)})
        ev = next(e for e in S.events(conn, sid) if "chin" in e["name"].lower())
        entrants = [(r["driver_id"], r["driver"]["name"], r["team"]["name"], r["driver"]["is_player"])
                    for r in S.weekend_rows(conn, ev["id"])]
    game = [{"name": n if p else n.split()[-1].upper(), "team": t, "race_number": i + 1}
            for i, (_d, n, t, p) in enumerate(entrants)]
    mate = next(i for i, e in enumerate(entrants) if e[2] == "Williams" and e[0] != ana)
    me = next(i for i, e in enumerate(entrants) if e[0] == ana)

    def send(type_id, label, order, weather_seen, extra=None):
        res = [{**game[i], "position": p + 1, "status": "Finished", "laps": 19 if type_id == 15 else 56,
                "best_lap_ms": 90000 + p * 10, **(extra or {}).get(i, {})} for p, i in enumerate(order)]
        assert app.test_client().post(f"/api/telemetry/{token}/{key}", json={
            "session": {"track": "Shanghai", "session_type": label, "session_type_id": type_id, "ai_difficulty": 84,
                        "weather": weather_seen[0], "weather_seen": weather_seen},
            "results": res, "session_uid": f"uid{type_id}"}).status_code == 200
    n = len(entrants)
    q1 = list(range(n))
    q2 = list(reversed(q1[:15]))
    q3 = list(reversed(q2[:10]))   # the ten fastest in Q2 go through
    send(5, "Q1", q1, ["Clear"])
    send(6, "Q2", q2, ["Clear"])
    send(7, "Q3", q3, ["Clear"])
    sprint = list(range(n))
    send(15, "Race", sprint, ["Overcast"], {me: {"race_time_s": 1900.0}, mate: {"race_time_s": 1895.5}})
    race = list(reversed(range(n)))
    send(16, "Race 2", race, ["Clear", "Light rain"],
         {me: {"race_time_s": 5500.0, "penalty_s": 5}, mate: {"race_time_s": 5499.0}})
    expected_quali = q3 + [i for i in q2 if i not in q3] + [i for i in q1 if i not in q2]
    pw, browser = open_browser()
    try:
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_server + "/login")
        page.fill("input[name=username]", "devon"); page.fill("input[name=password]", "password1")
        page.press("input[name=password]", "Enter"); page.wait_for_load_state()
        page.goto(f"{live_server}/career/{token}/weekend/{ev['id']}?stage=sessions")
        page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")
        with page.expect_navigation(timeout=15000):
            page.click("button[data-tele-fill] >> visible=true")
        page.wait_for_selector(".toast, [role=status]", timeout=5000)
        assert errors == []
    finally:
        browser.close()
        pw.stop()
    with storage.session(token) as conn:
        rows = {r["driver_id"]: r for r in S.weekend_rows(conn, ev["id"])}
        event = S.get_event(conn, ev["id"])
        wx = weather.get(conn, ev["id"])
        gp = ai3.pace_input(conn, ev["id"], ana, "gp")
        sp = ai3.pace_input(conn, ev["id"], ana, "sprint")
    ids = [e[0] for e in entrants]
    assert [rows[ids[i]]["qualifying_position"] for i in expected_quali] == list(range(1, n + 1))
    assert [rows[ids[i]]["sprint_position"] for i in sprint] == list(range(1, n + 1))
    assert [rows[ids[i]]["race_position"] for i in race] == list(range(1, n + 1))
    assert event["ai_difficulty"] == 84 and event["status"] != "Complete"
    assert wx == {"quali": "dry", "sprint": "overcast", "race": "changing"}
    assert (gp["race_time"], gp["bench_race_time"], gp["laps"]) == (5505.0, 5499.0, 56)
    assert gp["quali_time"] is not None and gp["mate_quali_time"] is not None
    assert (sp["race_time"], sp["bench_race_time"], sp["laps"]) == (1900.0, 1895.5, 19)


def test_game_data_stays_linked_to_its_round(master_client, app):
    """Uploads link to the first unfinished round at their circuit and are kept for good; the Race data page lists
    what each round is missing, and a rebuilt copy sent later replaces the old one without losing its round."""
    token = _league(master_client)
    key = _turn_on(master_client, token)
    with storage.session(token) as conn:
        ev = next(e for e in S.events(conn, S.current_season_id(conn)) if "chin" in e["name"].lower())
    up = app.test_client()

    def send(uid, type_id, track="Shanghai", **row):
        return up.post(f"/api/telemetry/{token}/{key}", json={
            "recorder": "Paddock Legacy Telemetry 0.6", "session_uid": uid, "events": [],
            "session": {"track": track, "session_type": "Race", "session_type_id": type_id, "ai_difficulty": 80},
            "results": [{"position": 1, "name": "NORRIS", "team": "McLaren", "best_lap_ms": 90000, **row}]}).get_json()["id"]
    race = send("r1", 16)
    for i in range(telemetry.KEEP + 3):   # plenty of unlinked practice laps elsewhere
        send(f"x{i}", 15, track="Nowhere")
    with storage.session(token) as conn:
        kept = {r["id"]: r["used_event_id"] for r in conn.execute("SELECT id, used_event_id FROM telemetry_uploads")}
        raw = json.loads(conn.execute("SELECT raw FROM telemetry_uploads WHERE id = ?", (race,)).fetchone()[0])
    assert kept[race] == ev["id"] and len(kept) == telemetry.KEEP + 1
    assert raw["recorder"] == "Paddock Legacy Telemetry 0.6"
    page = master_client.get(f"/career/{token}/telemetry/data").get_data(as_text=True)
    assert "Race data from the game" in page and "Qualifying: not recorded" in page and "Race: race times" in page
    # A newer recorder rebuilds the same session with race times: it replaces the copy and keeps the round.
    assert send("r1", 16, race_time_s=5400.5) == race
    page = master_client.get(f"/career/{token}/telemetry/data").get_data(as_text=True)
    assert "Race: race times" not in page and "Race: weather through the session" in page
    with storage.session(token) as conn:
        assert conn.execute("SELECT used_event_id FROM telemetry_uploads WHERE id = ?", (race,)).fetchone()[0] == ev["id"]
