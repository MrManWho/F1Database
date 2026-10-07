"""4.0.0-alpha.3: race times against the AI are required on tracked rounds (unless "Don't submit times" is ticked),
and players type the two race times while the site works out the gap."""

import pytest

from conftest import run_event
from f1tracker import ai3, services as S, storage

pytestmark = [pytest.mark.engine3, pytest.mark.pacerequired]


def _league(master_client, sprint=False):
    res = master_client.post("/careers/new", data={"name": "Pace League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Player One"], "player_login": [""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
        [one] = [p["id"] for p in S.player_drivers(conn)]
        S.place_players(conn, sid, {one: (teams["Williams"], 1)})
        ev = [e for e in S.events(conn, sid) if bool(e["is_sprint"]) == sprint][0]
    return token, one, ev


def _payload(conn, ev, difficulty=82, overrides=None):
    rows = S.weekend_rows(conn, ev["id"])
    return {"results": [{"driver_id": r["driver_id"], "qualifying_position": i + 1, "race_position": i + 1,
                         "status_override": (overrides or {}).get(r["driver_id"], "Auto"),
                         "sprint_position": (i + 1) if ev["is_sprint"] else None, "sprint_status_override": "Auto",
                         "fastest_lap": i == 0, "driver_of_day": i == 0, "notes": ""} for i, r in enumerate(rows)],
            "ai_difficulty": difficulty, "notes": "Round notes"}


def _submit(master_client, token, ev, payload):
    return master_client.post(f"/api/career/{token}/weekend/{ev['id']}", json={**payload, "mark_complete": True},
                              headers={"X-CSRF-Token": "tok"})


def _pace(master_client, token, ev, driver, **fields):
    return master_client.post(f"/career/{token}/weekend/{ev['id']}/pace",
                              data={"csrf_token": "tok", "driver_id": driver, "session": "gp", **fields})


# --------------------------------------------------------------------------- the gap from two race times

def test_two_race_times_give_the_gap(app, master_client):
    token, one, ev = _league(master_client)
    _pace(master_client, token, ev, one, race_time="1:32:45.123", bench_race_time="1:32:32.700", laps="58")
    with storage.session(token) as conn:
        p = ai3.pace_input(conn, ev["id"], one)
    assert p["race_gap"] == pytest.approx(12.423) and p["race_time"] == pytest.approx(5565.123)
    assert p["bench_race_time"] == pytest.approx(5552.7) and p["gap_to"] == "teammate" and p["laps"] == 58
    _pace(master_client, token, ev, one, race_time="92:30.000", bench_race_time="92:35.500", laps="58",
          comp_driver_id="1")
    with storage.session(token) as conn:
        p = ai3.pace_input(conn, ev["id"], one)
    assert p["race_gap"] == pytest.approx(-5.5) and p["gap_to"] == "comparison"      # ahead: negative


def test_one_race_time_alone_is_refused_and_a_typed_gap_still_works(app, master_client):
    token, one, ev = _league(master_client)
    res = _pace(master_client, token, ev, one, race_time="1:32:45.123", laps="58")
    assert res.status_code == 302
    assert "Enter both race times" in master_client.get(res.headers["Location"]).get_data(as_text=True)
    with storage.session(token) as conn:
        assert ai3.pace_input(conn, ev["id"], one) is None                         # nothing saved
    _pace(master_client, token, ev, one, race_gap="7.5", laps="58")
    with storage.session(token) as conn:
        p = ai3.pace_input(conn, ev["id"], one)
    assert p["race_gap"] == 7.5 and p["race_time"] is None


def test_the_evidence_uses_the_worked_out_gap(app, master_client):
    token, one, ev = _league(master_client)
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]), difficulty=82)
    _pace(master_client, token, ev, one, race_time="1:30:58.000", bench_race_time="1:30:00.000", laps="58")
    with storage.session(token) as conn:
        e = dict(S.get_event(conn, ev["id"]))
        rows = [dict(r) for r in conn.execute("SELECT r.*, d.is_player FROM results r JOIN drivers d ON d.id = r.driver_id "
                                              "WHERE r.event_id = ?", (ev["id"],))]
        r = next(x for x in rows if x["driver_id"] == one)
        from f1tracker import calc3
        evidence = ai3.session_evidence(conn, e, r, rows, calc3.round_ranks(conn, e), "gp", 11)
    assert evidence["gap_per_lap"] == pytest.approx(1.0)          # 58 s over 58 laps: a second a lap slower


# --------------------------------------------------------------------------- required before submitting

def test_a_tracked_round_cant_be_submitted_without_race_times(app, master_client):
    token, one, ev = _league(master_client)
    with storage.session(token) as conn:
        payload = _payload(conn, ev)
    res = _submit(master_client, token, ev, payload)
    assert res.status_code == 422
    assert any("Race times missing for Player One (Grand Prix)" in b for b in res.get_json()["checklist"]["blocking"])
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    # 4.0 redesign: Review & submit lists it under Must fix, with the race time fields under Sessions → Race times
    assert "Must fix (1)" in page and "Race times missing for Player One (Grand Prix)" in page and 'name="race_time"' in page
    _pace(master_client, token, ev, one, race_time="1:32:45.123", bench_race_time="1:32:32.700", laps="58")
    assert _submit(master_client, token, ev, payload).status_code == 200
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["status"] == "Complete"


def test_dont_submit_times_lets_the_round_through(app, master_client):
    token, one, ev = _league(master_client)
    with storage.session(token) as conn:
        payload = _payload(conn, ev)
    _pace(master_client, token, ev, one, untracked="1")
    assert _submit(master_client, token, ev, payload).status_code == 200


def test_not_required_when_not_tracked_not_finished_or_switched_off(app, master_client):
    token, one, ev = _league(master_client)
    with storage.session(token) as conn:
        event = dict(S.get_event(conn, ev["id"]))
        run_event(conn, S.get_event(conn, ev["id"]), difficulty=82, complete=False)
        assert ai3.missing_pace(conn, dict(S.get_event(conn, ev["id"]))) == [("Player One", "Grand Prix")]
        conn.execute("UPDATE events SET ai_untracked = 1, ai_difficulty = NULL WHERE id = ?", (ev["id"],))
        assert ai3.missing_pace(conn, dict(S.get_event(conn, ev["id"]))) == []        # "Don't track this round"
        conn.execute("UPDATE events SET ai_untracked = 0, ai_difficulty = 82 WHERE id = ?", (ev["id"],))
        run_event(conn, S.get_event(conn, ev["id"]), difficulty=82, overrides={one: "DNF"}, complete=False)
        assert ai3.missing_pace(conn, dict(S.get_event(conn, ev["id"]))) == []        # didn't finish
        run_event(conn, S.get_event(conn, ev["id"]), difficulty=82, complete=False)
        storage.set_meta(conn, "pace_required", "0")
        assert ai3.missing_pace(conn, dict(S.get_event(conn, ev["id"]))) == []        # the league switched it off
    assert event


def test_sprint_weekends_need_the_sprint_times_too(app, master_client):
    token, one, ev = _league(master_client, sprint=True)
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]), difficulty=82, complete=False)
    _pace(master_client, token, ev, one, race_time="1:32:45.123", bench_race_time="1:32:32.700", laps="58")
    with storage.session(token) as conn:
        assert ai3.missing_pace(conn, dict(S.get_event(conn, ev["id"]))) == [("Player One", "Sprint")]


def test_the_league_setting(app, master_client):
    token, one, ev = _league(master_client)
    page = master_client.get(f"/career/{token}/settings/weekends").get_data(as_text=True)
    assert 'name="pace_required"' in page and "checked" in page.split('name="pace_required"')[1][:40]
