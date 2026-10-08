"""4.0 track-aware AI recommendation: one AI for the weekend = F1Laps baseline + learned league adjustment + track
history, learned from each player's evidence, with the movement caps, evidence rules and frozen history."""

import json

import pytest

from conftest import after_submit, run_event
from f1tracker import ai_track, constants as C, services as S, storage

pytestmark = [pytest.mark.engine3, pytest.mark.trackai]

F1LAPS = {"Australia": 81, "China": 81, "Japan": 82, "Bahrain": 82, "Saudi Arabia": 82, "Miami": 82, "Canada": 84,
          "Monaco": 80, "Catalunya": 80, "Austria": 83, "Great Britain": 82, "Belgium": 83, "Hungary": 81,
          "Netherlands": 84, "Monza": 82, "Madrid": 80, "Azerbaijan": 79, "Singapore": 82, "Austin": 79, "Mexico": 79,
          "Brazil": 78, "Las Vegas": 76, "Qatar": 78, "Abu Dhabi": 78}


def _league():
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Track League", 2026, ["Player One", "Player Two"])
        sid = S.current_season_id(conn)
        teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
        one, two = [p["id"] for p in S.player_drivers(conn)]
        S.place_players(conn, sid, {one: (teams["Williams"], 1), two: (teams["Haas"], 2)})
    return token, one, two


def _mate(conn, driver_id):
    sid = S.current_season_id(conn)
    team = S.driver_seats(conn, sid)[driver_id][0]
    return next(d for d, s in S.driver_seats(conn, sid).items() if s[0] == team and d != driver_id)


def _play(token, rnd, one_place, two_place, ai=None, overrides=None, one_ahead_of_mate=None):
    """Enter round `rnd`: player one finishes at one_place, player two at two_place (1-based), the rest in grid order."""
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[rnd - 1]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        order = [d for d in ids if d not in (ONE, TWO)]
        for d, place in sorted(((ONE, one_place), (TWO, two_place)), key=lambda x: x[1]):
            order.insert(place - 1, d)
        run_event(conn, ev, order=order, overrides=overrides or {}, difficulty=ai if ai is not None else 81)
    with storage.session(token) as conn:
        after_submit(conn, S.get_event(conn, ev["id"]))
    return ev


@pytest.fixture
def league():
    global ONE, TWO
    token, ONE, TWO = _league()
    return token


def _rec(token, rnd=None):
    with storage.session(token) as conn:
        before = (2026, rnd) if rnd else None
        return S.difficulty_recommendation(conn, before)


# --------------------------------------------------------------------------- dataset

def test_the_f1laps_snapshot_has_every_circuit_and_its_versions():
    data = ai_track.snapshot()
    assert data["game"] == "F1 26" and data["source"] == "F1Laps" and data["source_date"]
    assert data["dataset_version"] == ai_track.CURRENT_SNAPSHOT and data["model_version"] == ai_track.MODEL
    assert {c["label"]: c["ai"] for c in data["circuits"]} == F1LAPS
    for rnd, name, loc, _sprint in C.CALENDAR:           # every round of the default calendar has a baseline
        value, _label, known = ai_track.baseline({"name": name, "location": loc})
        assert known, name


def test_an_unknown_circuit_uses_the_average():
    value, label, known = ai_track.baseline({"name": "Imaginary GP", "location": "Nowhere"})
    assert not known and value == round(sum(F1LAPS.values()) / 24, 1) and "average" in label


# --------------------------------------------------------------------------- the formula

def test_a_new_league_starts_at_the_f1laps_baseline_with_zero_adjustment(league):
    with storage.session(league) as conn:
        assert ai_track.uses_track(conn, S.current_season_id(conn))
    rec = _rec(league)
    t = rec["track"]
    assert t["baseline"] == 81 and t["league_adjustment"] == 0 and t["track_history"] == 0
    assert rec["recommended"] == 81 and t["circuit"] == "Australia" and t["weekends"] == 0
    assert rec["engine"] == "track"


def test_track_to_track_baseline_changes_are_not_capped(league):
    assert _rec(league, 8)["recommended"] == 80           # Monaco
    assert _rec(league, 7)["recommended"] == 84           # Canada
    assert _rec(league, 22)["recommended"] == 76          # Las Vegas: 8 below Canada, no cap


def test_both_players_beating_their_car_raise_the_league_adjustment_within_the_caps(league):
    steps = []
    for rnd in (1, 2, 3, 4):
        _play(league, rnd, 1, 2, ai=_rec(league, rnd)["recommended"])   # a Williams and a Haas 1-2: far too easy
        with storage.session(league) as conn:
            _adj, s, _v = ai_track.learn(conn)
        steps.append(s[-1]["step"])
    assert all(x > 0 for x in steps)
    assert steps[0] <= 2 and steps[1] <= 3 and steps[2] <= 4 and steps[3] <= 4
    assert max(steps) > 2                                  # aligned weekends allow bigger moves
    rec = _rec(league, 5)
    assert rec["recommended"] == 82 + rec["track"]["league_adjustment"] + rec["track"]["track_history"] or \
        abs(rec["recommended"] - (82 + rec["track"]["league_adjustment"] + rec["track"]["track_history"])) <= 0.5
    assert rec["track"]["league_adjustment"] == sum(steps)


def test_mixed_evidence_moves_little_or_not_at_all_and_warns_about_the_split(league):
    _play(league, 1, 1, 22)                               # one far too good, one far too slow
    with storage.session(league) as conn:
        _adj, steps, _v = ai_track.learn(conn)
    assert steps[-1]["agreement"] == "mixed" and abs(steps[-1]["step"]) <= 1
    rec = _rec(league, 2)
    assert rec["track"]["split"] and "No single AI setting can perfectly balance" in rec["note"]


def test_retirements_incidents_and_no_fault_results_never_count_against_the_ai(league):
    ev = _play(league, 1, 22, 21, overrides={ONE: "DNF", TWO: "DNS"})
    with storage.session(league) as conn:
        players = ai_track.weekend_evidence(conn, dict(S.get_event(conn, ev["id"])))
    assert players[ONE]["delta"] is None and players[TWO]["delta"] is None
    with storage.session(league) as conn:
        _adj, steps, _v = ai_track.learn(conn)
    assert steps[-1]["step"] == 0


def test_a_major_incident_removes_negative_evidence(league):
    ev = _play(league, 1, 20, 3)
    with storage.session(league) as conn:
        conn.execute("""INSERT INTO incidents(event_id, reporter, accused_driver_id, description, status, ruling, created_at)
                        VALUES(?, 'devon', ?, 'Collision', 'Decided', 'penalty', '2026-01-01')""", (ev["id"], ONE))
        players = ai_track.weekend_evidence(conn, dict(S.get_event(conn, ev["id"])))
    assert players[ONE]["delta"] is None and any("major incident" in n for n in players[ONE]["notes"])
    assert players[TWO]["delta"] > 0                       # positive evidence still counts


def test_beating_the_teammate_is_never_negative(league):
    with storage.session(league) as conn:
        mate = _mate(conn, ONE)
        ev = S.events(conn, S.current_season_id(conn))[0]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        order = [d for d in ids if d not in (ONE, mate)] + [ONE, mate]     # last but one, ahead of the teammate
        run_event(conn, ev, order=order, difficulty=81)
        players = ai_track.weekend_evidence(conn, dict(S.get_event(conn, ev["id"])))
    assert players[ONE]["delta"] is not None and players[ONE]["delta"] >= 0


def test_a_wet_race_counts_less(league):
    ev = _play(league, 1, 1, 2)
    with storage.session(league) as conn:
        dry = ai_track.weekend_evidence(conn, dict(S.get_event(conn, ev["id"])))
        from f1tracker import weather
        weather.save(conn, dict(S.get_event(conn, ev["id"])), {"weather_race": "heavy_rain"}, "devon")
        wet = ai_track.weekend_evidence(conn, dict(S.get_event(conn, ev["id"])))
    assert wet[ONE]["weight"] == pytest.approx(dry[ONE]["weight"] * ai_track.WET_WEIGHT)


# --------------------------------------------------------------------------- recorded, never recalculated

def test_the_recommendation_and_the_ai_used_are_recorded_separately_and_frozen(league, tmp_path, monkeypatch):
    _play(league, 1, 1, 2, ai=85)                          # the Race Master chose 85 instead of the recommended 81
    with storage.session(league) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        row = ai_track.frozen(conn, ev["id"])
    assert row["recommended"] == 81 and row["ai_used"] == 85 and row["baseline"] == 81
    assert row["dataset_version"] == ai_track.CURRENT_SNAPSHOT and row["model_version"] == ai_track.MODEL
    # a new F1Laps snapshot changes future rounds only
    data = json.loads((ai_track.SNAPSHOT_DIR / f"{ai_track.CURRENT_SNAPSHOT}.json").read_text())
    for c in data["circuits"]:
        c["ai"] += 5
    data["dataset_version"] = "f1laps-f126-test-update"
    monkeypatch.setattr(ai_track, "SNAPSHOT_DIR", tmp_path)
    (tmp_path / "f1laps-f126-test-update.json").write_text(json.dumps(data))
    (tmp_path / f"{ai_track.CURRENT_SNAPSHOT}.json").write_text(
        (ai_track.Path(ai_track.__file__).parent / "data" / "ai_baselines" / f"{ai_track.CURRENT_SNAPSHOT}.json").read_text())
    monkeypatch.setattr(ai_track, "CURRENT_SNAPSHOT", "f1laps-f126-test-update")
    ai_track._load.cache_clear()
    try:
        with storage.session(league) as conn:
            assert ai_track.frozen(conn, ev["id"])["recommended"] == 81        # unchanged
            ai_track.store(conn, ev["id"])                                       # e.g. a correction re-submits it
            assert ai_track.frozen(conn, ev["id"])["recommended"] == 81
        assert _rec(league, 2)["track"]["baseline"] == 86                        # China 81 + 5 from the new snapshot
    finally:
        ai_track._load.cache_clear()


def test_a_completed_round_page_shows_the_recommendation_made_before_it(app, master_client):
    res = master_client.post("/careers/new", data={"name": "Page League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva"], "player_login": [""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        assert ai_track.uses_track(conn, S.current_season_id(conn))
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev, difficulty=83)
    with storage.session(token) as conn:
        after_submit(conn, S.get_event(conn, ev["id"]))
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}", follow_redirects=True).get_data(as_text=True)
    assert "Before this round the recommendation was AI 81" in page and "AI 83 was used" in page
    dash = master_client.get(f"/career/{token}/dashboard", follow_redirects=True).get_data(as_text=True)
    assert "F1Laps community average" in dash and "League adjustment" in dash


# --------------------------------------------------------------------------- track history

def test_track_history_starts_at_zero_and_grows_with_visits_up_to_three():
    players = [{"id": 1, "name": "Player One"}]
    ev = {"name": "Monaco GP", "location": "Monaco"}

    class Conn:           # track_history only reads the league's on/off setting
        def execute(self, *_a):
            class R:
                def fetchone(self):
                    return None
            return R()
    key = ai_track.circuit_key(ev)
    assert ai_track.track_history(Conn(), ev, {}, players)[0] == 0
    one = ai_track.track_history(Conn(), ev, {(1, key): [8.0]}, players)[0]
    assert one == 2.0                                     # 1 visit: a quarter of +8
    many = ai_track.track_history(Conn(), ev, {(1, key): [8.0] * 12}, players)[0]
    assert many == 3.0                                    # capped


# --------------------------------------------------------------------------- which seasons use it

@pytest.mark.parametrize("marker", [None])
def test_a_season_already_under_way_keeps_the_v3_tracker_and_the_next_season_switches(league, marker):
    with storage.session(league) as conn:
        sid = S.current_season_id(conn)
        conn.execute("UPDATE meta SET value = 'v3' WHERE key = ?", (f"ai_model:{sid}",))   # an existing league
        assert not ai_track.uses_track(conn, sid)
        new = S.create_next_season(conn, sid, 2027)
        assert ai_track.uses_track(conn, new) and not ai_track.uses_track(conn, sid)


def test_an_unfinished_round_page_shows_the_recommendation(app, master_client):
    """4.0.0-alpha.3 regression: a round with results entered but not yet submitted crashed the round page."""
    res = master_client.post("/careers/new", data={"name": "Open Round League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva"], "player_login": [""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}")
    assert page.status_code == 200 and "F1Laps community average" in page.get_data(as_text=True)
    with storage.session(token) as conn:
        run_event(conn, S.get_event(conn, ev["id"]), difficulty=82, complete=False)
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}")
    assert page.status_code == 200 and "AI 82 is recorded for this round" in page.get_data(as_text=True)
