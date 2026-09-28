"""Golden fixtures: the calculation results 4.0 must reproduce exactly (4.0 Phase 0).

A fixed, seeded league plays a season through the same code the site uses (results saved, the round submitted,
then the follow-up: targets, press, relationships and the AI recommendation). Every number a player sees is then
recorded: driver and constructor standings after every round, Driver Value, the Form and Reputation timeline, and
the stored per-round tables (relationships, targets, ultimatums, car ranks, AI recommendations).

The same season is played once on Engine 3 and once on Engine 2, because historical Engine 2 seasons must keep
showing the same numbers. tests/test_v400_phase0.py rebuilds both and compares them with the saved JSON; any
difference fails. Only rebuild the JSON when a formula change has been approved:

    python -m f1tracker.golden write tests/golden
"""

import json
import os
import random
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROUNDS = 8
SEED = 4000
PLAYERS = ["Player One", "Player Two"]
# Stored tables that hold calculated values. Time stamps and free text are left out: they aren't calculations.
TABLES = ["season_driver_state", "team_relations", "weekend_targets", "ultimatums", "round_ranks", "ai_recs",
          "team_goals", "team_orders", "press_answers"]
SKIP_COLUMNS = ("_at", "text", "notes", "message", "answer", "question", "evidence", "detail", "summary", "reason")


@contextmanager
def _defaults(engine):
    """New leagues on the chosen engine, round gates and race weekends off (results go in straight away)."""
    from . import constants as C, teamlife, weekend
    saved = (C.NEW_LEAGUE_ENGINE, teamlife.DEFAULTS.get("round_gates"), weekend.DEFAULTS.get("race_weekends"))
    C.NEW_LEAGUE_ENGINE = engine
    teamlife.DEFAULTS["round_gates"] = "0"
    weekend.DEFAULTS["race_weekends"] = "0"
    try:
        yield
    finally:
        C.NEW_LEAGUE_ENGINE = saved[0]
        teamlife.DEFAULTS["round_gates"] = saved[1]
        weekend.DEFAULTS["race_weekends"] = saved[2]


def _enter(conn, event, rng):
    from . import services as S
    rows = S.weekend_rows(conn, event["id"])
    ids = [r["driver_id"] for r in rows]
    order = ids[:]
    # Mostly grid order with some shuffling, so standings, head-to-heads and car-adjusted numbers all move.
    for i in range(len(order) - 1):
        if rng.random() < 0.35:
            order[i], order[i + 1] = order[i + 1], order[i]
    quali = ids[:]
    rng.shuffle(quali)
    overrides = {}
    if rng.random() < 0.6:
        overrides[rng.choice(ids)] = "DNF"
    if rng.random() < 0.15:
        overrides[rng.choice(ids)] = "DNS"
    results = [{"driver_id": did, "qualifying_position": quali.index(did) + 1, "race_position": order.index(did) + 1,
                "status_override": overrides.get(did, "Auto"),
                "sprint_position": (order.index(did) + 1) if event["is_sprint"] else None,
                "sprint_status_override": "Auto", "fastest_lap": did == order[min(2, len(order) - 1)],
                "driver_of_day": did == order[0], "notes": ""} for did in ids]
    S.save_weekend(conn, event["id"], {"results": results, "mark_complete": True,
                                       "ai_difficulty": 80 + rng.randint(-6, 6)})


def _submit(conn, event):
    from . import ai3, calc3, engine, services as S, teamlife
    ev = S.get_event(conn, event["id"])
    if engine.round_v3(conn, ev) and not conn.execute("SELECT 1 FROM round_ranks WHERE event_id = ?",
                                                      (ev["id"],)).fetchone():
        calc3.store_round_ranks(conn, ev)
    teamlife.after_race(conn, ev["id"])
    if engine.round_v3(conn, ev):
        ai3.store(conn, ev["id"])


def _num(v):
    return round(v, 6) if isinstance(v, float) else v


def _standing(r):
    keep = ("position", "points", "gp_points", "sprint_points", "wins", "podiums", "poles", "fastest_laps", "dotds",
            "dnfs", "dns", "starts", "best_finish", "avg_finish", "form", "reputation", "car_adjusted", "seated")
    out = {k: _num(r.get(k)) for k in keep if k in r}
    out["driver"] = r["driver"]["name"]
    out["team"] = r["team"]["name"] if r.get("team") else None
    if isinstance(r.get("market"), dict):
        out["tier"] = r["market"]["name"]
    return out


def _table(conn, name):
    try:
        rows = conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
    except Exception:
        return None
    return [{k: _num(row[k]) for k in row.keys() if not k.endswith(SKIP_COLUMNS)} for row in rows]


def snapshot(conn):
    from . import market, services as S
    sid = S.current_season_id(conn)
    done = [e for e in S.events(conn, sid) if e["status"] == "Complete"]
    out = {"engine": None, "rounds": []}
    from . import engine
    out["engine"] = engine.season_engine(conn, sid)
    for ev in done:
        rn = ev["round_number"]
        standings = S.driver_standings(conn, sid, upto_round=rn)
        by_id = {r["driver_id"]: r for r in standings}
        values = {}
        for r in standings:
            v = market.driver_value(conn, sid, r["driver_id"], standings=by_id, upto_round=rn)
            values[r["driver"]["name"]] = _num(v["value"])
        out["rounds"].append({"round": rn,
                              "drivers": [_standing(r) for r in standings],
                              "constructors": [{"position": t["position"], "team": t["team"]["name"],
                                                "points": t["points"], "wins": t["wins"]}
                                               for t in S.constructor_standings(conn, sid, upto_round=rn)],
                              "driver_value": values})
    if out["engine"] >= 3:
        from . import calc3
        out["timeline"] = {p["name"]: {str(k): [_num(x) for x in v]
                                       for k, v in calc3.round_timeline(conn, sid, p["id"]).items()}
                           for p in S.player_drivers(conn)}
    out["tables"] = {t: rows for t in TABLES if (rows := _table(conn, t)) is not None}
    return out


def play(engine, name="Golden League"):
    """Create the fixed league in the current data folder and play its season. Returns the league id."""
    from . import relations, services as S, storage
    rng = random.Random(SEED)
    token = storage.new_token()
    with _defaults(engine):
        with storage.session(token, create=True) as conn:
            S.seed_career(conn, token, name, 2026, PLAYERS)
        with storage.session(token) as conn:
            sid = S.current_season_id(conn)
            teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
            one, two = [p["id"] for p in S.player_drivers(conn)]
            # One player in a midfield car, one in a backmarker, each with an AI teammate.
            S.place_players(conn, sid, {one: (teams["Williams"], 1), two: (teams["Haas"], 2)})
            conn.execute("UPDATE meta SET value = 'v3' WHERE key = ?", (f"ai_model:{sid}",))  # the v3.1.2 reference
            relations.ensure(conn, sid)
            for row in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?", (sid,)).fetchall():
                relations.set_pledge(conn, sid, row["driver_id"], 1)
        for ev in S_events(token)[:ROUNDS]:
            with storage.session(token) as conn:
                _enter(conn, ev, rng)
            with storage.session(token) as conn:
                _submit(conn, ev)
    return token


def build(engine):
    """Play the fixed season on this engine in a throwaway data folder and return its snapshot."""
    from . import storage
    old = os.environ.get("F1_TRACKER_DATA_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["F1_TRACKER_DATA_DIR"] = tmp
        try:
            token = play(engine)
            with storage.session(token) as conn:
                return snapshot(conn)
        finally:
            if old is None:
                os.environ.pop("F1_TRACKER_DATA_DIR", None)
            else:
                os.environ["F1_TRACKER_DATA_DIR"] = old


def S_events(token):
    from . import services as S, storage
    with storage.session(token) as conn:
        return S.events(conn, S.current_season_id(conn))


def dumps(data):
    return json.dumps(data, indent=1, sort_keys=True, default=str) + "\n"


def write(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for engine in (3, 2):
        (folder / f"engine{engine}_season.json").write_text(dumps(build(engine)))
    return folder


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "write":
        print("usage: python -m f1tracker.golden write <folder>")
        sys.exit(2)
    print("written to", write(sys.argv[2]))
