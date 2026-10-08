"""4.0.0-beta.1: the UI overhaul. One stewards' story per round, incidents per session, a safe double submit, only
the latest calculations, the Race Weekend workspace for every role, and the new navigation."""

import threading

import pytest

from conftest import login, pledge_all, run_event
from f1tracker import auth, community, constants as C, engine, feed, roles, services as S, storage

pytestmark = [pytest.mark.engine3]


def _league(master_client, sprint_first=False):
    """Jordan Vale (Williams) and Sam Ortiz (Haas) drive with logins; the site Race Master runs the league."""
    for u, n in (("jordan", "Jordan Vale"), ("sam", "Sam Ortiz")):
        if not auth.get_user(u):
            auth.create_user(u, n, "password1")
    res = master_client.post("/careers/new", data={"name": "UI League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Jordan Vale", "Sam Ortiz"],
                                                   "player_login": ["jordan", "sam"]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
        a, b = [p["id"] for p in S.player_drivers(conn)]
        S.place_players(conn, sid, {a: (teams["Williams"], 1), b: (teams["Haas"], 1)})
    pledge_all(token)
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _events(token):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))


def _payload(token, ev):
    with storage.session(token) as conn:
        rows = S.weekend_rows(conn, ev["id"])
    return {"results": [{"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1,
                         "status_override": "Auto", "sprint_position": (i + 1) if ev["is_sprint"] else None,
                         "sprint_status_override": "Auto", "fastest_lap": i == 0, "driver_of_day": i == 0, "notes": ""}
                        for i, r in enumerate(rows)], "ai_difficulty": 82, "notes": "Round notes"}


# --------------------------------------------------------------------------- incidents: one story per round

def test_many_rulings_make_one_stewards_story(app, master_client):
    token, a, b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
        entrants = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        before = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        ids = [community.report_incident(conn, ev["id"], "devon", None, d, "Track limits at turn 4", "race")
               for d in entrants[:20]]
        for i in ids:
            community.rule_incident(conn, i, "none", "", "devon")
        stories = conn.execute("SELECT * FROM news WHERE ref = ?", (f"stewards:{ev['id']}",)).fetchall()
        assert len(stories) == 1 and conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == before + 1
        assert "no further action on 20 incidents" in stories[0]["headline"]
        # A real sanction updates the same story and is named in it.
        community.rule_incident(conn, ids[0], "warning", "Repeated", "devon")
        story = conn.execute("SELECT * FROM news WHERE ref = ?", (f"stewards:{ev['id']}",)).fetchone()
        name = S.driver_map(conn)[entrants[0]]["name"]
        assert "1 warning" in story["headline"] and f"{name}: Warning (Race). Repeated" in story["body"]
        assert "No further action on 19 other reports" in story["body"]
        assert conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == before + 1
    # Deleting every report removes the story.
    for i in ids:
        master_client.post(f"/career/{token}/incidents/{i}/delete", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert not conn.execute("SELECT 1 FROM news WHERE ref = ?", (f"stewards:{ev['id']}",)).fetchone()


def test_old_per_ruling_headlines_are_folded_into_one_story(app, master_client):
    token, a, b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
        where = f"R{ev['round_number']} {ev['name']}"
        for d in (a, b):
            iid = community.report_incident(conn, ev["id"], "devon", None, d, "Corner cutting at turn 2")
            conn.execute("UPDATE incidents SET status = 'Decided', ruling = 'none', decided_at = '2026-03-01' WHERE id = ?",
                         (iid,))
            feed.post(conn, ev["season_id"], "paddock", f"No further action for X after {where} incident", "", "incidents")
        community.regroup_incident_news(conn)
        rows = conn.execute("SELECT headline FROM news WHERE link = 'incidents'").fetchall()
    assert len(rows) == 1 and "no further action on 2 incidents" in rows[0]["headline"]


def test_incidents_record_their_session(app, master_client):
    token, a, b = _league(master_client)
    ev = next(e for e in _events(token) if not e["is_sprint"])
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
    jordan = _client(app, "jordan")
    jordan.post(f"/career/{token}/weekend/{ev['id']}/incident",
                data={"csrf_token": "tok", "accused_id": b, "description": "Pushed me wide at turn 1", "session": "qualifying"})
    with storage.session(token) as conn:
        inc = community.incidents(conn, event_id=ev["id"])[0]
        assert inc["session"] == "qualifying" and inc["session_label"] == "Qualifying"
        with pytest.raises(S.ValidationError):      # a standard weekend has no Sprint
            community.report_incident(conn, ev["id"], "jordan", a, b, "Sprint contact", "sprint")


# --------------------------------------------------------------------------- submitting twice is safe

def test_submitting_twice_runs_the_post_race_steps_once(app, master_client):
    token, a, b = _league(master_client)
    auth.create_user("kim", "Kim", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "kim", "scorekeeper")
        storage.set_meta(conn, "pace_required", "0")
    kim = _client(app, "kim")
    ev = _events(token)[0]
    body = {**_payload(token, ev), "mark_complete": True}
    first = kim.post(f"/api/career/{token}/weekend/{ev['id']}", json=body, headers={"X-CSRF-Token": "tok"})
    again = kim.post(f"/api/career/{token}/weekend/{ev['id']}", json=body, headers={"X-CSRF-Token": "tok"})
    assert first.status_code == 200 and again.status_code == 403 and again.get_json()["already_submitted"]
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news WHERE kind = 'result'").fetchone()[0] == 1


def test_two_submissions_at_the_same_moment_complete_once(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        storage.set_meta(conn, "pace_required", "0")
    ev = _events(token)[0]
    body = {**_payload(token, ev), "mark_complete": True}
    clients = [_client(app, "devon"), _client(app, "devon")]
    codes = []
    go = threading.Barrier(2)

    def submit(c):
        go.wait()
        codes.append(c.post(f"/api/career/{token}/weekend/{ev['id']}", json=body, headers={"X-CSRF-Token": "tok"}).status_code)
    threads = [threading.Thread(target=submit, args=(c,)) for c in clients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200, 200]      # the Race Master's second one is just a (no-change) correction
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news WHERE kind = 'result'").fetchone()[0] == 1
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_COMPLETE


# --------------------------------------------------------------------------- only the latest calculations

@pytest.mark.latest
def test_an_older_league_moves_to_the_latest_calculations_without_changing_its_history(app, master_client, monkeypatch):
    monkeypatch.setattr(C, "NEW_LEAGUE_ENGINE", C.ENGINE_LEGACY)
    monkeypatch.setattr(engine, "AUTO_LATEST", False)
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        storage.set_meta(conn, "calc_choice", "later")
        sid = S.current_season_id(conn)
        run_event(conn, S.events(conn, sid)[0], difficulty=82)
        before = [(r["driver_id"], r["points"], r["position"]) for r in S.driver_standings(conn, sid)]
        assert engine.league_engine(conn) == C.ENGINE_LEGACY
    monkeypatch.setattr(engine, "AUTO_LATEST", True)
    with storage.session(token) as conn:            # opening it is enough
        assert engine.league_engine(conn) == C.ENGINE_CURRENT and engine.is_v3(conn, sid)
        assert engine.cutoff(conn, sid) == 1         # round 1 keeps exactly what it was calculated as
        assert [(r["driver_id"], r["points"], r["position"]) for r in S.driver_standings(conn, sid)] == before
        from f1tracker import ai_track
        assert ai_track.season_model(conn, sid) == ai_track.MODEL
    # No choice and no way back.
    res = master_client.get(f"/career/{token}/calculation-update")
    assert res.status_code == 302 and res.headers["Location"].endswith("/dashboard")
    for path in ("settings/weekends", "settings/data", "dashboard", f"weekend/{_events(token)[1]['id']}", "press"):
        page = master_client.get(f"/career/{token}/{path}", follow_redirects=True).get_data(as_text=True)
        for word in ("Calculation Version", "Version 2", "Version 3", "Calculation Update"):
            assert word not in page, (path, word)
    assert "Version 3" not in master_client.get("/help").get_data(as_text=True)


# --------------------------------------------------------------------------- the workspace, by role

@pytest.mark.weekends
def test_workspace_opens_at_the_right_stage_for_each_role(app, master_client):
    token, a, b = _league(master_client)
    auth.create_user("kim", "Kim", "password1")
    auth.create_user("pat", "Pat", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "kim", "scorekeeper")
        roles.set_member(conn, "pat", "spectator")
        storage.set_meta(conn, "pace_required", "0")
    ev = _events(token)[0]
    url = f"/career/{token}/weekend/{ev['id']}"
    jordan, kim, pat = _client(app, "jordan"), _client(app, "kim"), _client(app, "pat")

    def stage(page):
        return page.split('aria-current="step"')[0].rsplit('data-stage-link="', 1)[1].split('"')[0]
    # Before lights out everyone starts in Prepare; the driver sees their own tasks.
    page = jordan.get(url).get_data(as_text=True)
    assert stage(page) == "prepare" and "Your tasks" in page
    assert stage(kim.get(url).get_data(as_text=True)) == "prepare"
    master_client.post(f"{url}/paddock", data={"csrf_token": "tok"})
    master_client.post(f"{url}/start", data={"csrf_token": "tok", "note": "Starting for the test run"})
    # Lights out: the Scorekeeper lands in Sessions at Qualifying.
    page = kim.get(url).get_data(as_text=True)
    assert stage(page) == "sessions" and 'data-session-default="q"' in page and 'id="save-state"' in page
    # A spectator can look, never edit or submit.
    spec = pat.get(url).get_data(as_text=True)
    assert 'id="save-state"' not in spec and 'id="mark-complete"' not in spec and 'data-readonly="1"' in spec
    # Everything entered: Review, with the server's checklist and one Submit button.
    kim.post(f"/api/career/{token}/weekend/{ev['id']}", json=_payload(token, ev), headers={"X-CSRF-Token": "tok"})
    page = kim.get(url).get_data(as_text=True)
    assert stage(page) == "review" and page.count('id="mark-complete"') == 1 and "Before you submit" in page
    # Submitted: everyone opens the Debrief.
    kim.post(f"/api/career/{token}/weekend/{ev['id']}", json={**_payload(token, ev), "mark_complete": True},
             headers={"X-CSRF-Token": "tok"})
    for c in (jordan, kim, pat):
        assert stage(c.get(url).get_data(as_text=True)) == "debrief"
    # Any stage can be reopened directly, without going through the others.
    assert stage(jordan.get(url + "?stage=sessions").get_data(as_text=True)) == "sessions"


def test_review_blocking_items_link_to_the_field(app, master_client):
    token, a, b = _league(master_client)
    ev = _events(token)[0]
    master_client.post(f"/api/career/{token}/weekend/{ev['id']}",
                       json={**_payload(token, ev), "ai_difficulty": None}, headers={"X-CSRF-Token": "tok"})
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}?stage=review").get_data(as_text=True)
    assert "Enter the AI difficulty used" in page and 'data-fix-anchor="ai-difficulty"' in page


def test_sprint_weekends_show_the_sprint_session(app, master_client):
    token, a, b = _league(master_client)
    sprint = next(e for e in _events(token) if e["is_sprint"])
    page = master_client.get(f"/career/{token}/weekend/{sprint['id']}?stage=sessions").get_data(as_text=True)
    cards = page.split('class="session-cards')[1].split("</div>")[0]
    assert cards.index('data-session="q"') < cards.index('data-session="s"') < cards.index('data-session="r"')
    standard = next(e for e in _events(token) if not e["is_sprint"])
    page = master_client.get(f"/career/{token}/weekend/{standard['id']}?stage=sessions").get_data(as_text=True)
    assert 'data-session="s"' not in page.split('class="session-cards')[1].split("</div>")[0]


def test_the_debrief_shows_only_your_own_career_numbers(app, master_client):
    token, a, b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
    page = _client(app, "jordan").get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    mine = page.split('id="my-weekend"')[1].split("</section>")[0]
    assert "Why did this change?" in mine and "Reputation" in mine and "Sam Ortiz" not in mine
    # Someone without a driver gets no personal section at all.
    assert 'id="my-weekend"' not in master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)


# --------------------------------------------------------------------------- navigation and Home

def test_navigation_destinations_and_old_links(app, master_client):
    token, a, b = _league(master_client)
    ev = _events(token)[0]
    res = master_client.get(f"/career/{token}/race-weekend")
    assert res.status_code == 302 and res.headers["Location"].endswith(f"/weekend/{ev['id']}")
    assert master_client.get(f"/career/{token}/race-weekend?stage=review").headers["Location"].endswith("?stage=review")
    assert master_client.get(f"/career/{token}/championship").headers["Location"].endswith("/standings")
    assert master_client.get(f"/career/{token}/my-career").headers["Location"].endswith("/more")
    assert _client(app, "jordan").get(f"/career/{token}/my-career").headers["Location"].endswith("/garage")
    assert master_client.get(f"/career/{token}/weekend").status_code == 302          # the old link still works
    more = master_client.get(f"/career/{token}/more").get_data(as_text=True)
    assert "Incidents &amp; stewards' decisions" in more
    standings = master_client.get(f"/career/{token}/standings").get_data(as_text=True)
    assert 'class="nav-sub-strip" aria-label="Championship"' in standings and "Records</a>" in standings


def test_home_offers_only_what_you_can_do(app, master_client):
    token, a, b = _league(master_client)
    auth.create_user("pat", "Pat", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "pat", "spectator")
    rm = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Next action" in rm and "Run R1" in rm and "Your tasks" in rm
    spec = _client(app, "pat").get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Your tasks" not in spec and "Run R1" not in spec and "Enter R1" not in spec and "Follow R1" in spec
    assert "Manage league" not in spec
