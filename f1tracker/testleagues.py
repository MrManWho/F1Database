"""Test leagues (4.1.0): fictional leagues the site owner makes from Account → Test leagues, to try a situation
without touching a real league.

Each scenario is built from the golden-fixture season (f1tracker/golden.py): two player drivers (Player One at
Williams, Player Two at Haas) and the 2026 grid. The owner joins as Race Master driving Player One. Test leagues
are marked (meta test_league) and named "Test · ...": they never email anyone or send phone alerts (the in-app bell
still works), and the Test leagues page can delete them.

Scenarios:
    final_round   every round played except the last: try the season finale and the rollover
    game_round    race night from the game: the last round is live, qualifying has already arrived from the game,
                  and "Send the race from the game" plays the recorder's part, so the round fills itself in
    first_round   a new league with nothing played: try a whole race weekend from the start
"""

import json
import random
import secrets

from . import storage

PREFIX = "Test · "
SCENARIOS = {
    "game_round": ("Race night from the game",
                   "The last round of the season is under way. Qualifying has already arrived from the game, the way the "
                   "recorder sends it. Press Send the race from the game and the round fills itself in, you get the alert, "
                   "and the round waits for you to approve it."),
    "final_round": ("Season finale",
                    "Every round played except the last. Enter the last round, then start the new season from Seasons "
                    "to try the rollover."),
    "first_round": ("First race of a season",
                    "A new league with nothing played yet. Try a whole race weekend from the start: Prepare, Sessions, "
                    "Review & submit and the Debrief."),
}
GAME_TRACK = "Abu Dhabi"          # what the game calls the last round's circuit (Yas Marina)
RACE_LAPS = 58


def is_test(conn):
    return storage.get_meta(conn, "test_league") == "1"


def create(scenario, username):
    """Make one test league for this scenario with username as its Race Master. Returns the league id."""
    if scenario not in SCENARIOS:
        raise ValueError("Unknown test scenario")
    from . import constants as C, golden, roles, services as S
    rounds = {"final_round": -1, "game_round": -1, "first_round": 0}[scenario]
    stamp = storage.now_iso()[:16].replace("T", " ")
    token = golden.play(C.ENGINE_CURRENT, name=f"{PREFIX}{SCENARIOS[scenario][0]} ({stamp})", rounds=rounds)
    with storage.session(token) as conn:
        storage.set_meta(conn, "test_league", "1")
        storage.set_meta(conn, "test_scenario", scenario)
        storage.set_meta(conn, "test_created", storage.now_iso())
        conn.execute("DELETE FROM notifications")   # the made-up season's alerts would bury the ones being tried
        if username:
            roles.set_member(conn, username, "race_master", S.player_drivers(conn)[0]["id"])
        if scenario == "game_round":
            _race_night(conn)
    return token


def _race_night(conn):
    """Telemetry on with an upload link, the last round's lights out, and qualifying received from the game."""
    from . import community, telemetry
    community.set_features(conn, set(k for k, v in community.features(conn).items() if v and k != "public") | {"telemetry"})
    telemetry.new_key(conn)
    event = _last_round(conn)
    now = storage.now_iso()
    conn.execute("UPDATE events SET paddock_at = COALESCE(paddock_at, ?), lights_at = COALESCE(lights_at, ?) WHERE id = ?",
                 (now, now, event["id"]))
    quali, race = sessions(conn, event)
    telemetry.store(conn, quali)
    storage.set_meta(conn, "test_race_payload", json.dumps(race))


def _last_round(conn):
    from . import services as S
    return S.events(conn, S.current_season_id(conn))[-1]


def _game_name(driver):
    """How the game's results screen names a driver: AI drivers by surname in capitals, players by their name."""
    return driver["name"].upper() if driver["is_player"] else driver["name"].split()[-1].upper()


def sessions(conn, event, seed=None):
    """A qualifying and a race session for this round, shaped exactly like the recorder's uploads."""
    from . import services as S
    rng = random.Random(seed if seed is not None else secrets.randbits(32))
    rows = S.weekend_rows(conn, event["id"])
    ranks = S.team_strength_ranks(conn, event["season_id"])
    pace = {r["driver_id"]: ranks.get(r["team_id"], 10) + rng.random() * 5 for r in rows}
    quali = sorted(rows, key=lambda r: pace[r["driver_id"]] + rng.random() * 2)
    race = sorted(rows, key=lambda r: pace[r["driver_id"]] + rng.random() * 4)
    ai_level = 85

    def base(r):
        return {"name": _game_name(r["driver"]), "team": r["team"]["name"], "ai": not r["driver"]["is_player"],
                "race_number": 1 + rows.index(r)}
    q_results, lap = [], 82.4 + rng.random()
    for i, r in enumerate(quali):
        lap += 0.05 + rng.random() * 0.12
        ms = int(lap * 1000)
        q_results.append({**base(r), "position": i + 1, "status": "Finished", "best_lap_ms": ms,
                          "best_lap": f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}", "laps": 3, "grid": 0})
    out_driver = race[-3]          # one AI retirement near the back
    while out_driver["driver"]["is_player"]:
        out_driver = race[race.index(out_driver) - 1]
    penalised = race[len(race) // 2]
    finishers = [r for r in race if r is not out_driver]
    total, r_results, fastest = 5340.0 + rng.random() * 40, [], None
    grid = {r["driver_id"]: i + 1 for i, r in enumerate(quali)}
    for i, r in enumerate(finishers):
        if i:
            total += 0.8 + rng.random() * 6
        best = 86.2 + rng.random() * 1.5
        if fastest is None or best < fastest[1]:
            fastest = (r["driver_id"], best)
        r_results.append({**base(r), "position": i + 1, "status": "Finished", "grid": grid[r["driver_id"]],
                          "laps": RACE_LAPS, "race_time_s": round(total, 3), "best_lap_ms": int(best * 1000),
                          "best_lap": f"1:{best - 60:06.3f}", "penalty_s": 5 if r is penalised else 0})
    r_results.append({**base(out_driver), "position": len(rows), "status": "Retired", "reason": "Power unit",
                      "grid": grid[out_driver["driver_id"]], "laps": 31, "race_time_s": 0,
                      "best_lap_ms": 87400, "best_lap": "1:27.400", "penalty_s": 0})
    fastest_name = _game_name(next(x["driver"] for x in rows if x["driver_id"] == fastest[0]))
    for r in r_results:
        r["fastest_lap"] = r["name"] == fastest_name
    weather = {"weather": "Clear", "weather_seen": ["Clear", "Light cloud"]}
    common = {"recorder": "Paddock Legacy test league", "game": {"packet_format": 2026}}
    q = {**common, "session_uid": secrets.token_hex(8),
         "session": {"track": GAME_TRACK, "session_type": "Short Qualifying", "session_type_id": 8,
                     "ai_difficulty": ai_level, **weather},
         "results": q_results, "events": []}
    pen = next(x for x in r_results if x["penalty_s"])
    rc = {**common, "session_uid": secrets.token_hex(8),
          "session": {"track": GAME_TRACK, "session_type": "Race", "session_type_id": 15, "ai_difficulty": ai_level,
                      "total_laps": RACE_LAPS, **weather},
          "results": r_results,
          "events": [{"code": "PENA", "driver": pen["name"], "seconds": 5, "lap": 23, "penalty_type": 2,
                      "infringement": 7},
                     {"code": "RTMT", "driver": _game_name(out_driver["driver"]), "lap": 31}]}
    return q, rc


def send_race(token):
    """Play the recorder's part at the end of the race: the race session arrives through the same steps as a real
    upload (stored, linked to its round, and the round filled in). Returns the round's id."""
    from . import autofill, telemetry
    with storage.session(token) as conn:
        if not is_test(conn):
            raise ValueError("Only a test league can be sent a made-up race")
        payload = storage.get_meta(conn, "test_race_payload")
        if not payload:
            raise ValueError("This test league has no race waiting to be sent")
        upload_id = telemetry.store(conn, json.loads(payload))
        autofill.after_upload(conn, upload_id)
        storage.set_meta(conn, "test_race_sent", storage.now_iso())
        return _last_round(conn)["id"]


def leagues():
    """Every test league on this site, newest first: [{token, name, scenario, label, created, race_waiting}]."""
    out = []
    for c in storage.list_careers():
        if not c["name"].startswith(PREFIX):
            continue
        try:
            with storage.session(c["token"]) as conn:
                if not is_test(conn):
                    continue
                scenario = storage.get_meta(conn, "test_scenario") or ""
                out.append({"token": c["token"], "name": c["name"], "scenario": scenario,
                            "label": SCENARIOS.get(scenario, ("Test",))[0],
                            "created": storage.get_meta(conn, "test_created") or "",
                            "race_waiting": bool(storage.get_meta(conn, "test_race_payload"))
                            and not storage.get_meta(conn, "test_race_sent"),
                            "round_id": _last_round(conn)["id"]})
        except storage.CareerNotFound:
            continue
    out.sort(key=lambda x: x["created"], reverse=True)
    return out


def delete(token):
    """Delete one test league (never anything else)."""
    with storage.session(token) as conn:
        if not is_test(conn):
            raise ValueError("That isn't a test league")
    storage.delete_career(token)
