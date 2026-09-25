"""v2.0 core workflows: calendar, results edge cases, difficulty explanations, contracts, pending actions."""

import pytest

from conftest import login, players, run_event
from f1tracker import auth, notices, roles, seats, services as S, storage
from f1tracker import constants as C


def _league(master_client, name="Flow League", players_=("Ana Silva",), logins=("",)):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "player_name": list(players_), "player_login": list(logins)})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        storage.set_meta(conn, "timezone", "UTC")
    return token


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


# --------------------------------------------------------------------------- calendar

def test_completed_rounds_keep_their_number_unless_correcting_history(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        run_event(conn, evs[0])
    form = {"csrf_token": "tok"}
    for e in evs:
        form.update({f"round_{e['id']}": e["round_number"], f"name_{e['id']}": e["name"], f"location_{e['id']}": e["location"]})
        if e["is_sprint"]:
            form[f"sprint_{e['id']}"] = "1"
    swapped = dict(form, **{f"round_{evs[0]['id']}": 2, f"round_{evs[1]['id']}": 1})
    res = master_client.post(f"/career/{token}/calendar/save", data=swapped, follow_redirects=True)
    assert "locked" in res.get_data(as_text=True)
    with storage.session(token) as conn:
        assert S.get_event(conn, evs[0]["id"])["round_number"] == 1
    master_client.post(f"/career/{token}/calendar/save", data=dict(swapped, historical_correction="1"))
    with storage.session(token) as conn:
        assert S.get_event(conn, evs[0]["id"])["round_number"] == 2
        from f1tracker import community
        assert "historical correction mode" in community.audit_entries(conn)[0]["summary"]
    # Future rounds can be reordered freely.
    fwd = dict(form, **{f"round_{evs[0]['id']}": 2, f"round_{evs[1]['id']}": 1,
                        f"round_{evs[2]['id']}": 4, f"round_{evs[3]['id']}": 3})
    master_client.post(f"/career/{token}/calendar/save", data=fwd)
    with storage.session(token) as conn:
        assert S.get_event(conn, evs[2]["id"])["round_number"] == 4


def test_archived_season_calendar_needs_correction_mode(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        e = S.events(conn, sid)[0]
        S.create_next_season(conn, sid, 2027)
    master_client.get(f"/career/{token}/dashboard?season={sid}")
    res = master_client.post(f"/career/{token}/calendar/save", data={
        "csrf_token": "tok", f"round_{e['id']}": 1, f"name_{e['id']}": "Renamed GP", f"location_{e['id']}": "x"},
        follow_redirects=True)
    assert "archived" in res.get_data(as_text=True)
    with storage.session(token) as conn:
        assert S.get_event(conn, e["id"])["name"] != "Renamed GP"


def test_calendar_file_warnings_and_month_view(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        conn.execute("UPDATE events SET race_at = '2026-03-08T05:00+00:00' WHERE id IN (?, ?)", (evs[0]["id"], evs[1]["id"]))
        conn.execute("UPDATE events SET race_at = '2026-03-01T05:00+00:00' WHERE id = ?", (evs[2]["id"],))
    ics = master_client.get(f"/career/{token}/calendar.ics")
    body = ics.get_data(as_text=True)
    assert ics.mimetype == "text/calendar" and body.startswith("BEGIN:VCALENDAR") and body.count("BEGIN:VEVENT") == 3
    assert "SUMMARY:Flow League: R1" in body and "DTSTART:20260308T050000Z" in body
    page = master_client.get(f"/career/{token}/seasons").get_data(as_text=True)
    assert "are scheduled at the same time" in page and "is scheduled before" in page
    assert "March 2026" in page and "mg-race" in page
    anon = app.test_client()
    assert anon.get(f"/career/{token}/calendar.ics").status_code == 302      # members only


def test_race_time_form_previews_who_will_be_told(app, master_client, monkeypatch):
    from f1tracker import mailer
    monkeypatch.setattr(mailer, "configured", lambda: True)
    auth.create_user("ana", "Ana", "password1", email="ana@example.com")
    auth.create_user("bo", "Bo", "password1", email="bo@example.com")
    token = _league(master_client)
    with storage.session(token) as conn:
        roles.set_member(conn, "ana", "member")
        roles.set_member(conn, "bo", "member")
        notices.save(conn, "ana", preset="all")
        notices.save(conn, "bo", preset="inapp")
        ev = S.events(conn, S.current_season_id(conn))[0]
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert "2 members see it in the app, 1 get a phone alert and 1 an email" in page


# --------------------------------------------------------------------------- results edge cases

def _payload(rows, over=None):
    over = over or {}
    out = []
    for i, r in enumerate(rows):
        item = {"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1,
                "sprint_position": i + 1, "status_override": "Auto", "sprint_status_override": "Auto",
                "fastest_lap": False, "driver_of_day": False, "notes": ""}
        item.update(over.get(r["driver_id"], {}))
        out.append(item)
    return out


def test_sessions_and_statuses_score_correctly(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sprint = next(e for e in S.events(conn, S.current_season_id(conn)) if e["is_sprint"])
        rows = S.weekend_rows(conn, sprint["id"])
        a, b, c, d, e = (r["driver_id"] for r in rows[:5])
        S.save_weekend(conn, sprint["id"], {"results": _payload(rows, {
            a: {"sprint_status_override": "DNF"},           # Sprint DNF: no Sprint points, Grand Prix untouched
            b: {"status_override": "DNF"},                   # GP DNF
            c: {"status_override": "DNS"}, d: {"status_override": "DSQ"}}), "mark_complete": True})
        pts = {r["driver_id"]: (r["sprint_pts"], r["gp_points"], r["result_status"]) for r in S.weekend_rows(conn, sprint["id"])}
    assert pts[a][0] == 0 and pts[a][1] == C.GP_POINTS[1]
    assert pts[b][1] == 0 and pts[b][0] == C.SPRINT_POINTS[2]
    assert pts[c][1] == 0 and pts[c][2] == "DNS" and pts[d][1] == 0 and pts[d][2] == "DSQ"
    assert pts[e][1] == C.GP_POINTS[5]


def test_duplicate_positions_and_not_run_rounds(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        rows = S.weekend_rows(conn, ev["id"])
    bad = _payload(rows, {rows[1]["driver_id"]: {"race_position": 1}})
    res = master_client.post(f"/api/career/{token}/weekend/{ev['id']}", json={"results": bad, "mark_complete": True},
                             headers={"X-CSRF-Token": "tok"})
    assert res.status_code in (400, 422)
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == C.EVENT_NOT_RUN
        assert all(r["result_status"] == "Not Run" for r in S.weekend_rows(conn, ev["id"]))


# --------------------------------------------------------------------------- AI difficulty

def test_difficulty_explains_rounds_and_can_be_switched_off(app, master_client):
    token = _league(master_client, players_=("Ana Silva",))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        S.place_players(conn, sid, {players(conn)[0]: (1, 1)})
        evs = S.events(conn, sid)
        for e in evs[:3]:
            run_event(conn, e, difficulty=85)
        run_event(conn, evs[3], difficulty=None)
        conn.execute("UPDATE events SET ai_untracked = 1 WHERE id = ?", (evs[3]["id"],))
        rec = S.difficulty_recommendation(conn)
    assert len(rec["used"]) == 3 and rec["used"][0]["label"].endswith(evs[0]["name"])
    assert any("Don't track" in x["why"] for x in rec["excluded"])
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "The rounds behind this" in page and "diff-spark" in page
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "team_life": "1"})   # recs box unticked
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "recommendations are off in this league" in page
    with storage.session(token) as conn:     # still recorded
        assert S.get_event(conn, evs[0]["id"])["ai_difficulty"] == 85


def test_sprint_points_count_unless_the_league_turns_them_off(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        p = players(conn)[0]
        S.place_players(conn, sid, {p: (1, 1)})
        sprint = next(e for e in S.events(conn, sid) if e["is_sprint"])
        ids = [r["driver_id"] for r in S.weekend_rows(conn, sprint["id"])]
        run_event(conn, sprint, order=[d for d in ids if d != p][:9] + [p],
                  sprint_order=[p] + [d for d in ids if d != p], difficulty=85)
        with_sprint, _ = S.player_event_score(conn, S.get_event(conn, sprint["id"]))     # default: Sprints count
        storage.set_meta(conn, "difficulty_sprints", "0")
        without, _ = S.player_event_score(conn, S.get_event(conn, sprint["id"]))
    assert with_sprint > without


# --------------------------------------------------------------------------- contracts, pending actions

def test_contract_list_states(app, master_client):
    token = _league(master_client, players_=("Ana Silva", "Ben Okafor"), logins=("", ""))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        S.place_players(conn, sid, {a: (1, 1), b: (2, 1)})
        seats.record_contract(conn, a, 1, 2024, 1)       # historical
        seats.record_contract(conn, a, 1, 2025, 1)       # expired
        seats.record_contract(conn, a, 1, 2026, 1)       # current, ends this season
        seats.record_contract(conn, a, 3, 2027, 2)       # upcoming
        seats.record_contract(conn, b, 5, 2026, 1)       # current but seated elsewhere
        rows = seats.contract_list(conn, sid)
    states = {(r["driver"]["id"], r["target_year"]): (r["state"], r["expiring"]) for r in rows}
    assert states[(a, 2024)][0] == "historical" and states[(a, 2025)][0] == "expired"
    assert states[(a, 2026)] == ("current", True) and states[(a, 2027)][0] == "upcoming"
    assert states[(b, 2026)][0] == "mismatch"
    page = master_client.get(f"/career/{token}/grid").get_data(as_text=True)
    assert "Current, but seated elsewhere" in page and "Upcoming" in page


def test_waiting_for_you_lists_each_roles_actions(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("joe", "Joe", "password1")
    token = _league(master_client, players_=("Ana Silva",), logins=("ana",))
    with storage.session(token) as conn:
        conn.execute("INSERT INTO join_requests(username, driver_name, created_at) VALUES('joe', 'Joe Racer', '2026-01-01')")
        conn.execute("UPDATE events SET race_at = '2020-01-01T10:00+00:00' WHERE round_number = 1")
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Next action" in page and "Also waiting for you" in page and "1 join request to answer" in page and "Results pending for R1" in page
    ana = _client(app, "ana")
    page = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "join request" not in page
