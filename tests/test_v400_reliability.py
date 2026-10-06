"""4.0.0-beta.13: forms go back to where they were sent from, failures say why and keep what was typed, retries and
double presses save once, and per-request reuse of worked-out numbers never shows stale values."""

import re
import threading

import pytest

from conftest import login, players, pledge_all, run_event
from f1tracker import auth, navigation, relations, roles, services as S, storage, teamlife


def _league(master_client):
    for name in ("ana", "ben", "kim"):
        auth.create_user(name, name.title(), "password1")
    res = master_client.post("/careers/new", data={"name": "Reliability", "year": "2026",
                                                   "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
        roles.set_member(conn, "kim", "scorekeeper")
    pledge_all(token)
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _events(token):
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))


def _open_paddock(client, token, ev):
    client.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})


def _prerace_question(token, ev, driver):
    with storage.session(token) as conn:
        return teamlife.prerace_pen(conn, S.get_event(conn, ev["id"]), driver)["questions"][0]


def _flashes(client):
    with client.session_transaction() as s:
        return [m for _cat, m in s.get("_flashes", [])]


# --------------------------------------------------------------------------- where a form goes back to

@pytest.mark.weekends
def test_prerace_press_from_prepare_returns_to_that_rounds_prepare(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    _open_paddock(master_client, token, ev)
    ana = _client(app, "ana")
    q = _prerace_question(token, ev, a)
    r = ana.post(f"/career/{token}/weekend/{ev['id']}/prerace",
                 data={"csrf_token": "tok", "question": q["key"], "answer": q["answers"][0]["key"],
                       "return_to": f"/career/{token}/weekend/{ev['id']}?stage=prepare"})
    assert r.status_code == 302
    assert r.headers["Location"] == f"/career/{token}/weekend/{ev['id']}?stage=prepare#prerace"
    assert any(m.startswith("Answer saved.") for m in _flashes(ana))


@pytest.mark.weekends
def test_prerace_press_without_any_origin_still_lands_on_the_round(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    _open_paddock(master_client, token, ev)
    ana = _client(app, "ana")
    q = _prerace_question(token, ev, a)
    r = ana.post(f"/career/{token}/weekend/{ev['id']}/prerace",
                 data={"csrf_token": "tok", "question": q["key"], "answer": q["answers"][0]["key"]})
    assert r.headers["Location"].startswith(f"/career/{token}/weekend/{ev['id']}?stage=prepare")


def test_post_race_press_returns_to_debrief_or_the_standalone_page(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
    ana = _client(app, "ana")
    page = ana.get(f"/career/{token}/weekend/{ev['id']}?stage=debrief").get_data(as_text=True)
    forms = re.findall(r'action="(/career/[^"]+/press/[^"]+)"[^>]*>(.*?)</form>', page, re.S)
    assert forms, "the Debrief offers post-race press"
    action, body = forms[0]
    fields = dict(re.findall(r'name="(question)" value="([^"]+)"', body))
    answer = re.search(r'name="answer" value="([^"]+)"', body).group(1)
    r = ana.post(action, data={"csrf_token": "tok", **fields, "answer": answer,
                               "return_to": f"/career/{token}/weekend/{ev['id']}?stage=debrief"})
    assert r.headers["Location"].startswith(f"/career/{token}/weekend/{ev['id']}?stage=debrief")
    r = ana.post(action, data={"csrf_token": "tok", **fields, "answer": answer, "back": "press"})
    assert r.headers["Location"] == f"/career/{token}/press#press"


def test_a_return_address_is_only_used_when_its_this_leagues_own_page(app, master_client):
    token, _a, _b = _league(master_client)
    with app.test_request_context("/", base_url="http://localhost"):
        ok = f"/career/{token}/standings?season=1#top"
        assert navigation.safe(ok, token) == ok
        assert navigation.safe(f"http://localhost/career/{token}/standings", token) == f"/career/{token}/standings"
        for bad in ("https://evil.example/career", "//evil.example/x", "/\\evil.example", "javascript:alert(1)",
                    f"/api/career/{token}/weekend/1", "/login", "/logout", "/static/js/app.js",
                    "/career/aaaaaaaaaaaa/standings", "/no-such-page", "/x" * 2000, "/career/\n"):
            assert navigation.safe(bad, token) is None, bad


# --------------------------------------------------------------------------- failures say why and keep the input

@pytest.mark.weekends
def test_a_validation_failure_goes_back_with_the_reason_and_marks_the_form_to_restore(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
    ana = _client(app, "ana")
    origin = f"/career/{token}/weekend/{ev['id']}?stage=sessions#incidents"
    r = ana.post(f"/career/{token}/weekend/{ev['id']}/incident",
                 data={"csrf_token": "tok", "accused_id": "999999", "description": "x", "return_to": origin})
    assert r.status_code == 302 and r.headers["Location"] == origin
    assert any("Pick a driver" in m for m in _flashes(ana))
    page = ana.get(origin.split("#")[0]).get_data(as_text=True)
    assert f'<meta name="form-failed" content="/career/{token}/weekend/{ev["id"]}/incident">' in page
    assert 'name="form-failed"' not in ana.get(origin.split("#")[0]).get_data(as_text=True)   # once only


def test_an_expired_form_explains_itself_and_stays_in_the_league(app, master_client):
    token, _a, _b = _league(master_client)
    ev = _events(token)[0]
    ana = _client(app, "ana")
    r = ana.post(f"/career/{token}/weekend/{ev['id']}/prerace", data={"csrf_token": "stale", "question": "q", "answer": "a"})
    assert r.status_code == 302 and r.headers["Location"] != "/"
    assert r.headers["Location"].startswith(f"/career/{token}/")
    assert any("wasn't saved" in m for m in _flashes(ana))
    r = ana.post(f"/api/career/{token}/weekend/{ev['id']}", json={}, headers={"X-CSRF-Token": "stale"})
    assert r.status_code == 400 and r.get_json()["expired"]


def test_a_signed_out_form_goes_to_sign_in_and_then_back(app, master_client):
    token, _a, _b = _league(master_client)
    ev = _events(token)[0]
    anon = app.test_client()
    r = anon.post(f"/career/{token}/weekend/{ev['id']}/prerace", data={"question": "q", "answer": "a",
                  "return_to": f"/career/{token}/weekend/{ev['id']}?stage=prepare"})
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")
    assert "next=" in r.headers["Location"] and "weekend" in r.headers["Location"]
    assert any("signed out" in m for m in _flashes(anon))


def test_a_denied_action_says_who_can_do_it_and_offers_a_way_back(app, master_client):
    token, _a, _b = _league(master_client)
    ev = _events(token)[0]
    ana = _client(app, "ana")
    r = ana.post(f"/career/{token}/weekend/{ev['id']}/time", data={"race_at": "2030-03-01T20:00", "csrf_token": "tok"},
                 headers={"Referer": f"http://localhost/career/{token}/weekend/{ev['id']}"})
    body = r.get_data(as_text=True)
    assert r.status_code == 403
    assert "Race Master" in body and "Nothing was changed" in body and "Back to where you were" in body


# --------------------------------------------------------------------------- sent twice, saved once

@pytest.mark.weekends
def test_the_same_answer_sent_twice_counts_once_and_says_so(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    _open_paddock(master_client, token, ev)
    ana = _client(app, "ana")
    q = _prerace_question(token, ev, a)
    data = {"csrf_token": "tok", "question": q["key"], "answer": q["answers"][0]["key"]}
    ana.post(f"/career/{token}/weekend/{ev['id']}/prerace", data=data)
    _flashes(ana)
    with storage.session(token) as conn:
        effects = conn.execute("SELECT COUNT(*) FROM press_answers").fetchone()[0]
        audits = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    ana.post(f"/career/{token}/weekend/{ev['id']}/prerace", data=data)    # the retry after a lost response
    assert any(m.startswith("Already saved") for m in _flashes(ana))
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM press_answers").fetchone()[0] == effects
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == audits
    other = dict(data, answer=q["answers"][1]["key"])
    ana.post(f"/career/{token}/weekend/{ev['id']}/prerace", data=other)     # a different answer is refused
    assert any("already answered" in m for m in _flashes(ana))


@pytest.mark.weekends
def test_two_presses_at_the_same_moment_save_one_answer(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    _open_paddock(master_client, token, ev)
    q = _prerace_question(token, ev, a)
    data = {"csrf_token": "tok", "question": q["key"], "answer": q["answers"][0]["key"]}
    clients = [_client(app, "ana"), _client(app, "ana")]
    codes = []
    go = threading.Barrier(2)

    def press(c):
        go.wait()
        codes.append(c.post(f"/career/{token}/weekend/{ev['id']}/prerace", data=data).status_code)
    threads = [threading.Thread(target=press, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [302, 302]
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM press_answers WHERE driver_id = ? AND question = ?",
                            (a, q["key"])).fetchone()[0] == 1


@pytest.mark.weekends
def test_a_weekend_target_chosen_twice_is_locked_in_once(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    _open_paddock(master_client, token, ev)
    ana = _client(app, "ana")
    for _ in range(2):
        r = ana.post(f"/career/{token}/target/{ev['id']}/accept", data={"csrf_token": "tok", "tier": "standard"})
        assert r.status_code == 302
    assert any(m.startswith("Already locked in") for m in _flashes(ana))
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM weekend_targets WHERE driver_id = ?", (a,)).fetchone()[0] == 1


def test_an_incident_report_sent_twice_is_filed_and_notified_once(app, master_client):
    token, a, b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]))
        before = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    ana = _client(app, "ana")
    data = {"csrf_token": "tok", "accused_id": str(b), "description": "Divebombed me at turn 1", "session": "race"}
    for _ in range(2):
        ana.post(f"/career/{token}/weekend/{ev['id']}/incident", data=data)
    assert any(m.startswith("Already reported") for m in _flashes(ana))
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == before + 1


def test_the_same_pledge_twice_changes_nothing_the_second_time(app, master_client):
    token, a, _b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        notes = conn.execute("SELECT COUNT(*) FROM relation_notes").fetchone()[0] \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'relation_notes'").fetchone() else None
        total = conn.total_changes
        relations.set_pledge(conn, sid, a, 1)        # pledge_all already chose Solid (1)
        assert conn.total_changes == total
        if notes is not None:
            assert conn.execute("SELECT COUNT(*) FROM relation_notes").fetchone()[0] == notes


# --------------------------------------------------------------------------- reused numbers are never stale

def test_numbers_worked_out_inside_a_preview_are_forgotten_when_it_is_undone(app, master_client):
    token, a, _b = _league(master_client)
    ev = _events(token)[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        before = [dict(r) for r in S.driver_standings(conn, sid)]
        conn.execute("SAVEPOINT p")
        run_event(conn, S.get_event(conn, ev["id"]))
        assert S.driver_standings(conn, sid) != before
        conn.execute("ROLLBACK TO p")
        conn.execute("RELEASE p")
        assert [dict(r) for r in S.driver_standings(conn, sid)] == before


def test_a_copy_returned_from_the_cache_can_be_changed_without_affecting_the_next(app, master_client):
    token, _a, _b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        rows = S.driver_standings(conn, sid)
        rows[0]["points"] = 12345
        assert S.driver_standings(conn, sid)[0]["points"] != 12345


# --------------------------------------------------------------------------- Review & submit, AI explanation

@pytest.mark.weekends
@pytest.mark.trackai
@pytest.mark.engine3
def test_fix_links_on_review_lead_back_to_review(app, master_client):
    token, _a, _b = _league(master_client)
    ev = _events(token)[0]
    _open_paddock(master_client, token, ev)
    master_client.post(f"/career/{token}/weekend/{ev['id']}/start", data={"csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}?stage=review").get_data(as_text=True)
    assert "data-fix-session" in page and "from=review" in page


@pytest.mark.trackai
@pytest.mark.engine3
def test_the_ai_explanation_calls_the_f1laps_average_a_starting_reference(app, master_client):
    token, _a, _b = _league(master_client)
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "How this was worked out" in page
    assert "Community starting reference" in page and "not proof" in page
