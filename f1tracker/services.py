"""Career rules: seeding, scoring, standings, Form, Reputation, grid, seasons, difficulty."""

import math
import re

from . import constants as C
from .storage import get_meta, now_iso, set_meta


class ValidationError(ValueError):
    pass


# --------------------------------------------------------------------------- helpers

def clamp(value, low, high):
    return max(low, min(high, value))


def _row(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def _rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def parse_position(value, label="Position", max_position=C.MAX_POSITION):
    if value is None or value == "":
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a whole number from 1 to {max_position}")
    if not 1 <= number <= max_position:
        raise ValidationError(f"{label} must be a whole number from 1 to {max_position}")
    return number


def parse_difficulty(value):
    if value is None or value == "":
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"AI difficulty must be a whole number from {C.MIN_DIFFICULTY} to {C.MAX_DIFFICULTY}")
    if not C.MIN_DIFFICULTY <= number <= C.MAX_DIFFICULTY:
        raise ValidationError(f"AI difficulty must be between {C.MIN_DIFFICULTY} and {C.MAX_DIFFICULTY}")
    return number


# --------------------------------------------------------------------------- seeding

def seed_career(conn, token, name, year, player_names=None):
    """Create a league: the default grid and calendar plus any number of human player drivers."""
    year = int(year)
    if not C.MIN_YEAR <= year <= C.MAX_YEAR:
        raise ValidationError(f"Opening year must be between {C.MIN_YEAR} and {C.MAX_YEAR}")
    stamp = now_iso()
    for key, value in (("career_id", token), ("career_name", name), ("created_at", stamp),
                       ("last_opened_at", stamp)):
        set_meta(conn, key, value)

    for team_id, (tname, code, color, _d1, _d2) in enumerate(C.TEAMS, start=1):
        conn.execute("INSERT INTO teams(id, name, abbreviation, color, active) VALUES(?,?,?,?,1)",
                     (team_id, tname, code, color))
    ai_names = [n for team in C.TEAMS for n in team[3:5]]
    for dname in ai_names:
        conn.execute("INSERT INTO drivers(name, baseline_reputation, is_player) VALUES(?,?,0)",
                     (dname, C.BASELINE_REPUTATION[dname]))
    players = [(" ".join(n.split())[:60], C.ROOKIE_REPUTATION) for n in (player_names or []) if n and n.strip()]
    if len(players) > C.MAX_PLAYERS:
        raise ValidationError(f"A league can have up to {C.MAX_PLAYERS} player drivers")
    if len({p[0].lower() for p in players} | {n.lower() for n in ai_names}) != len(players) + len(ai_names):
        raise ValidationError("Every driver needs a different name (and can't share a name with an F1 driver)")
    for pname, rep in players:
        conn.execute("INSERT INTO drivers(name, baseline_reputation, is_player) VALUES(?,?,1)", (pname, rep))
    assign_player_colors(conn)

    cur = conn.execute("INSERT INTO seasons(year, label, status, created_at) VALUES(?,?,?,?)",
                       (year, f"{year} World Championship", C.SEASON_ACTIVE, stamp))
    season_id = cur.lastrowid
    ids = {r["name"]: r["id"] for r in _rows(conn, "SELECT id, name FROM drivers")}
    for team_id, team in enumerate(C.TEAMS, start=1):
        for seat_no, dname in ((1, team[3]), (2, team[4])):
            conn.execute("INSERT INTO season_grid VALUES(?,?,?,?)", (season_id, team_id, seat_no, ids[dname]))
    for driver in _rows(conn, "SELECT id, baseline_reputation FROM drivers"):
        conn.execute("INSERT INTO season_driver_state VALUES(?,?,?,NULL)",
                     (season_id, driver["id"], driver["baseline_reputation"]))
    for rnd, ename, loc, sprint in C.CALENDAR:
        conn.execute("INSERT INTO events(season_id, round_number, name, location, is_sprint) VALUES(?,?,?,?,?)",
                     (season_id, rnd, ename, loc, int(sprint)))
    set_meta(conn, "current_season_id", season_id)
    set_meta(conn, "join_open", "1")
    set_meta(conn, "join_mode", "requests")
    sync_not_run_results(conn, season_id)
    return season_id


# --------------------------------------------------------------------------- lookups

def current_season_id(conn):
    value = get_meta(conn, "current_season_id")
    if value and _row(conn, "SELECT 1 FROM seasons WHERE id = ?", (value,)):
        return int(value)
    row = _row(conn, "SELECT id FROM seasons ORDER BY year DESC LIMIT 1")
    return row["id"] if row else None


def get_season(conn, season_id):
    row = _row(conn, "SELECT * FROM seasons WHERE id = ?", (season_id,))
    return dict(row) if row else None


def list_seasons(conn):
    return [dict(r) for r in _rows(conn, "SELECT * FROM seasons ORDER BY year")]


def teams(conn):
    return [dict(r) for r in _rows(conn, "SELECT * FROM teams WHERE active = 1 ORDER BY id")]


def team_map(conn):
    return {r["id"]: dict(r) for r in _rows(conn, "SELECT * FROM teams")}


def drivers(conn, active_only=False):
    sql = "SELECT * FROM drivers" + (" WHERE active = 1" if active_only else "") + " ORDER BY name"
    return [dict(r) for r in _rows(conn, sql)]


def driver_map(conn):
    return {r["id"]: dict(r) for r in _rows(conn, "SELECT * FROM drivers")}


def player_drivers(conn):
    return [dict(r) for r in _rows(conn, "SELECT * FROM drivers WHERE is_player = 1 ORDER BY id")]


def events(conn, season_id):
    return [dict(r) for r in _rows(conn, "SELECT * FROM events WHERE season_id = ? ORDER BY round_number",
                                   (season_id,))]


def get_event(conn, event_id):
    row = _row(conn, "SELECT * FROM events WHERE id = ?", (event_id,))
    return dict(row) if row else None


def season_started(conn, season_id):
    return bool(_row(conn, "SELECT 1 FROM events WHERE season_id = ? AND status != ?",
                     (season_id, C.EVENT_NOT_RUN)))


# --------------------------------------------------------------------------- scoring

def gp_points(position, status):
    return C.GP_POINTS.get(position, 0) if status == C.STATUS_FINISHED else 0


def sprint_points(position, status, is_sprint=True):
    return C.SPRINT_POINTS.get(position, 0) if is_sprint and status == C.STATUS_FINISHED else 0


def _blank_stats():
    return {
        "points": 0, "gp_points": 0, "sprint_points": 0, "wins": 0, "podiums": 0, "poles": 0,
        "fastest_laps": 0, "dotds": 0, "dnfs": 0, "starts": 0, "best_finish": None,
        "finishes": [], "qualis": [], "has_results": False, "last_team_id": None, "last_round": 0,
        "gained": 0, "racecraft": 0.0, "racecraft_races": 0,
    }


def racecraft_score(quali, finish, field=C.MAX_POSITION):
    """How impressive a finish was compared with the grid slot.

    Places gained count for more the closer to the front they end up: P20 to P1 scores 19.0,
    P20 to P19 only 0.2. Places lost cost 0.4 each (often it's the car, not the driver).
    """
    gained = quali - finish
    if gained > 0:
        return gained * (field + 1 - finish) / field
    return gained * 0.4


def accumulate_result(s, r, is_sprint):
    """Add one weekend's result row to a running stats dict."""
    s["has_results"] = True
    gp = gp_points(r["race_position"], r["result_status"])
    sp = sprint_points(r["sprint_position"], r["sprint_status"], bool(is_sprint))
    s["gp_points"] += gp
    s["sprint_points"] += sp
    s["points"] += gp + sp
    finished = r["result_status"] == C.STATUS_FINISHED
    pos = r["race_position"]
    s["wins"] += int(bool(finished and pos == 1))
    s["podiums"] += int(bool(finished and pos and pos <= 3))
    s["poles"] += int(r["qualifying_position"] == 1)
    s["fastest_laps"] += int(bool(r["fastest_lap"]))
    s["dotds"] += int(bool(r["driver_of_day"]))
    s["dnfs"] += int(r["result_status"] == "DNF")
    s["starts"] += int(r["result_status"] in C.START_STATUSES)
    if finished and pos and (s["best_finish"] is None or pos < s["best_finish"]):
        s["best_finish"] = pos
    if pos:
        s["finishes"].append(pos)
    if r["qualifying_position"]:
        s["qualis"].append(r["qualifying_position"])
    if finished and pos and r["qualifying_position"]:
        s["gained"] += r["qualifying_position"] - pos
        s["racecraft"] += racecraft_score(r["qualifying_position"], pos)
        s["racecraft_races"] += 1


def _finalise(stats):
    stats["avg_finish"] = round(sum(stats["finishes"]) / len(stats["finishes"]), 2) if stats["finishes"] else None
    stats["avg_quali"] = round(sum(stats["qualis"]) / len(stats["qualis"]), 2) if stats["qualis"] else None
    return stats


def _result_has_data(r):
    return any((r["qualifying_position"], r["race_position"], r["sprint_position"], r["fastest_lap"],
                r["driver_of_day"])) or r["result_status"] != C.STATUS_NOT_RUN or \
        r["sprint_status"] != C.STATUS_NOT_RUN


def season_stats(conn, season_id, upto_round=None, completed_only=False):
    """Raw per-driver statistics for one season, keyed by driver id (optionally only up to a round).
    completed_only: leave out rounds that haven't been submitted (public pages never show drafts)."""
    out = {}
    rows = _rows(conn, """
        SELECT r.*, e.is_sprint, e.round_number FROM results r JOIN events e ON e.id = r.event_id
        WHERE e.season_id = ? AND e.round_number <= ?""" + (" AND e.status = 'Complete'" if completed_only else "") +
        " ORDER BY e.round_number", (season_id, upto_round if upto_round is not None else 10 ** 6))
    for r in rows:
        if not _result_has_data(r):
            continue
        s = out.setdefault(r["driver_id"], _blank_stats())
        s["last_team_id"] = r["team_id"]
        s["last_round"] = r["round_number"]
        accumulate_result(s, r, r["is_sprint"])
    return {k: _finalise(v) for k, v in out.items()}


def compute_form(stats):
    if not stats:
        return 50.0
    avg_finish = stats.get("avg_finish") or 12
    avg_quali = stats.get("avg_quali") or 12
    races = stats.get("racecraft_races") or 0
    racecraft = clamp(stats.get("racecraft", 0) / races * 0.6, -6, 12) if races else 0
    value = (50 + (12 - avg_finish) * 2.4 + (12 - avg_quali) * 1.2
             + stats["wins"] * 1.5 + stats["podiums"] * 0.5 + stats["poles"] * 0.6
             + stats["fastest_laps"] * 0.4 + stats["dotds"] * 0.3 - stats["dnfs"] * 1.2
             + racecraft)
    return round(clamp(value, 1, 100), 1)


def compute_reputation(starting, stats, form):
    if not stats or not stats.get("has_results"):
        return round(clamp(starting, 1, 100), 1)
    value = (starting + stats["points"] / 80 + stats["wins"] * 1.3 + stats["podiums"] * 0.45
             + stats["poles"] * 0.25 + stats["fastest_laps"] * 0.15 + stats["dotds"] * 0.10
             + (form - 50) / 20 - stats["dnfs"] * 0.15 + stats.get("racecraft", 0) * 0.08)
    return round(clamp(value, 1, 100), 1)


def market_score(reputation, form):
    return round(0.8 * reputation + 0.2 * form, 1)


def market_tier(score):
    for floor, name, desc in C.MARKET_TIERS:
        if score >= floor:
            return {"name": name, "description": desc, "score": score}
    return {"name": "Developing", "description": "Building career capital", "score": score}


def starting_reputation(conn, season_id, driver_id):
    row = _row(conn, "SELECT starting_reputation FROM season_driver_state WHERE season_id=? AND driver_id=?",
               (season_id, driver_id))
    if row:
        return row["starting_reputation"]
    d = _row(conn, "SELECT baseline_reputation FROM drivers WHERE id = ?", (driver_id,))
    return d["baseline_reputation"] if d else 50.0


# --------------------------------------------------------------------------- grid

def grid_map(conn, season_id):
    return {(r["team_id"], r["seat_no"]): r["driver_id"]
            for r in _rows(conn, "SELECT * FROM season_grid WHERE season_id = ?", (season_id,))}


def driver_seats(conn, season_id):
    return {driver: key for key, driver in grid_map(conn, season_id).items() if driver}


def grid(conn, season_id):
    gmap = grid_map(conn, season_id)
    dmap = driver_map(conn)
    out = []
    for team in teams(conn):
        seats = []
        for seat_no in (1, 2):
            did = gmap.get((team["id"], seat_no))
            seats.append({"seat_no": seat_no, "driver": dmap.get(did)})
        out.append({**team, "seats": seats})
    return out


def _grid_order(conn, season_id):
    order = {}
    for (team_id, seat_no), did in grid_map(conn, season_id).items():
        if did:
            order[did] = (team_id, seat_no)
    return order


def sync_not_run_results(conn, season_id):
    """Regenerate result rows of every Not Run event from the current grid.

    Completed and In Progress events are never touched, keeping historical team snapshots intact.
    """
    seats = driver_seats(conn, season_id)
    for event in _rows(conn, "SELECT id FROM events WHERE season_id = ? AND status = ?",
                       (season_id, C.EVENT_NOT_RUN)):
        existing = {r["driver_id"] for r in _rows(conn, "SELECT driver_id FROM results WHERE event_id = ?",
                                                  (event["id"],))}
        for did in existing - set(seats):
            conn.execute("DELETE FROM results WHERE event_id = ? AND driver_id = ?", (event["id"], did))
        for did, (team_id, _seat) in seats.items():
            if did in existing:
                conn.execute("UPDATE results SET team_id = ? WHERE event_id = ? AND driver_id = ?",
                             (team_id, event["id"], did))
            else:
                conn.execute("INSERT INTO results(event_id, driver_id, team_id) VALUES(?,?,?)",
                             (event["id"], did, team_id))


def write_grid(conn, season_id, mapping):
    """Atomically apply {(team_id, seat): driver_id}; clearing first allows direct swaps."""
    conn.execute("UPDATE season_grid SET driver_id = NULL WHERE season_id = ?", (season_id,))
    for (team_id, seat_no), did in mapping.items():
        conn.execute("UPDATE season_grid SET driver_id = ? WHERE season_id = ? AND team_id = ? AND seat_no = ?",
                     (did, season_id, team_id, seat_no))
    sync_not_run_results(conn, season_id)


def save_full_grid(conn, season_id, submitted):
    """submitted: {(team_id, seat_no): driver_id-or-blank} for all 22 seats."""
    expected = set(grid_map(conn, season_id))
    if set(submitted) != expected or not expected:
        raise ValidationError(f"All {len(expected)} seats must be submitted")
    valid = {d["id"] for d in drivers(conn, active_only=True)}
    mapping, seen = {}, set()
    for key, raw in submitted.items():
        if raw in (None, ""):
            raise ValidationError(f"All {len(expected)} seats must be filled")
        try:
            did = int(raw)
        except (TypeError, ValueError):
            raise ValidationError("Invalid driver selection")
        if did not in valid:
            raise ValidationError("Every seat must hold an active driver")
        if did in seen:
            raise ValidationError("A driver cannot occupy two seats")
        seen.add(did)
        mapping[key] = did
    write_grid(conn, season_id, mapping)


def best_free_ai(conn, season_id, taken, exclude=()):
    free = [d for d in drivers(conn, active_only=True)
            if not d["is_player"] and d["id"] not in taken and d["id"] not in exclude]
    if not free:
        return None
    free.sort(key=lambda d: (-starting_reputation(conn, season_id, d["id"]), d["name"]))
    return free[0]["id"]


def place_players(conn, season_id, targets):
    """targets: {player_driver_id: (team_id, seat_no) or None}.

    A player taking a seat displaces its occupant; the displaced AI driver fills any seat the
    player vacated, and remaining vacancies are filled by the best unseated AI driver.
    """
    gmap = grid_map(conn, season_id)
    players = {d["id"] for d in player_drivers(conn)}
    wanted = [t for t in targets.values() if t]
    if len(wanted) != len(set(wanted)):
        raise ValidationError("Player drivers cannot share the same seat")
    for pid, target in targets.items():
        if pid not in players:
            raise ValidationError("Only player drivers can be placed here")
        if target and target not in gmap:
            raise ValidationError("Unknown seat")
    for key, did in list(gmap.items()):
        if did in targets:
            gmap[key] = None
    displaced = []
    for pid, target in targets.items():
        if target:
            occupant = gmap.get(target)
            if occupant and occupant not in players:
                displaced.append(occupant)
            elif occupant:  # another player not being moved in this request
                raise ValidationError("That seat already belongs to the other player driver")
            gmap[target] = pid
    for key in sorted(k for k, v in gmap.items() if v is None):
        if displaced:
            gmap[key] = displaced.pop(0)
        else:
            gmap[key] = best_free_ai(conn, season_id, set(gmap.values()))
    write_grid(conn, season_id, gmap)


# --------------------------------------------------------------------------- standings

def driver_standings(conn, season_id, upto_round=None, completed_only=False):
    stats = season_stats(conn, season_id, upto_round, completed_only)
    tmap = team_map(conn)
    dmap = driver_map(conn)
    seats = driver_seats(conn, season_id)
    locked = {r["driver_id"]: r for r in _rows(conn, "SELECT * FROM season_driver_state WHERE season_id = ?",
                                               (season_id,))}
    ids = set(seats) | {d for d, s in stats.items() if s["has_results"]}
    rows = []
    for did in ids:
        driver = dmap[did]
        s = stats.get(did) or _finalise(_blank_stats())
        form = compute_form(s) if s["has_results"] else 50.0
        state = locked.get(did)
        start = state["starting_reputation"] if state else driver["baseline_reputation"]
        if state and state["locked_reputation"] is not None:
            rep = state["locked_reputation"]
        else:
            rep = compute_reputation(start, s, form)
        team_id = seats[did][0] if did in seats else s["last_team_id"]
        score = market_score(rep, form)
        rows.append({
            **s, "driver": driver, "driver_id": did, "team": tmap.get(team_id), "seated": did in seats,
            "seat": seats.get(did), "form": form, "reputation": rep, "starting_reputation": start,
            "market": market_tier(score),
        })
    rows.sort(key=lambda r: (-r["points"], -r["wins"], -r["podiums"], r["best_finish"] or 99,
                             r["driver"]["name"]))
    for pos, row in enumerate(rows, start=1):
        row["position"] = pos
    return rows


def constructor_standings(conn, season_id, upto_round=None, completed_only=False):
    tmap = team_map(conn)
    totals = {tid: {"team": t, "points": 0, "wins": 0, "podiums": 0, "fastest_laps": 0, "dnfs": 0}
              for tid, t in tmap.items() if t["active"]}
    rows = _rows(conn, """SELECT r.*, e.is_sprint FROM results r JOIN events e ON e.id = r.event_id
                          WHERE e.season_id = ? AND e.round_number <= ?""" + (" AND e.status = 'Complete'" if completed_only else ""),
                 (season_id, upto_round if upto_round is not None else 10 ** 6))
    for r in rows:
        t = totals.setdefault(r["team_id"], {"team": tmap[r["team_id"]], "points": 0, "wins": 0,
                                             "podiums": 0, "fastest_laps": 0, "dnfs": 0})
        t["points"] += gp_points(r["race_position"], r["result_status"])
        t["points"] += sprint_points(r["sprint_position"], r["sprint_status"], bool(r["is_sprint"]))
        finished = r["result_status"] == C.STATUS_FINISHED
        if finished and r["race_position"] == 1:
            t["wins"] += 1
        if finished and r["race_position"] and r["race_position"] <= 3:
            t["podiums"] += 1
        t["fastest_laps"] += int(bool(r["fastest_lap"]))
        t["dnfs"] += int(r["result_status"] == "DNF")
    out = sorted(totals.values(), key=lambda t: (-t["points"], -t["wins"], -t["podiums"], t["team"]["name"]))
    gmap = grid_map(conn, season_id)
    dmap = driver_map(conn)
    for pos, t in enumerate(out, start=1):
        t["position"] = pos
        t["drivers"] = [dmap.get(gmap.get((t["team"]["id"], s))) for s in (1, 2)]
    return out


def _ai_points_per_entry(conn, season_id):
    """Average points per AI entry for each team: a car-strength read that ignores the players."""
    totals = {}
    rows = _rows(conn, """SELECT r.*, e.is_sprint FROM results r JOIN events e ON e.id = r.event_id
                          JOIN drivers d ON d.id = r.driver_id
                          WHERE e.season_id = ? AND e.status = ? AND d.is_player = 0""",
                 (season_id, C.EVENT_COMPLETE))
    for r in rows:
        pts = gp_points(r["race_position"], r["result_status"]) + \
            sprint_points(r["sprint_position"], r["sprint_status"], bool(r["is_sprint"]))
        t = totals.setdefault(r["team_id"], [0, 0])
        t[0] += pts
        t[1] += 1
    return {tid: p / n for tid, (p, n) in totals.items() if n}


def team_strength_ranks(conn, season_id):
    """Car-strength rank per team (1 = fastest car).

    Once three rounds are complete it comes from AI drivers' points only, so a player winning in a
    slow car doesn't make the car look fast. Before that it follows the season's car ratings, which
    develop over each winter (and which the Race Master can edit to match the game).
    """
    default = [t["id"] for t in teams(conn)]
    ratings = car_ratings(conn, season_id)
    by_rating = sorted(default, key=lambda t: (-ratings.get(t, {"rating": 0})["rating"], default.index(t)))
    done = _row(conn, "SELECT COUNT(*) AS n FROM events WHERE season_id = ? AND status = ?",
                (season_id, C.EVENT_COMPLETE))["n"]
    if done >= 3:
        strength = _ai_points_per_entry(conn, season_id)
        if any(strength.values()):
            order = sorted([t for t in default if t in strength], key=lambda t: (-strength[t], default.index(t)))
            # v2.3.1: a team with no AI driver (e.g. two players in one car) has no AI read. It keeps its place from
            # the car ratings instead of dropping to last.
            for t in sorted((t for t in default if t not in strength), key=by_rating.index):
                order.insert(min(by_rating.index(t), len(order)), t)
            return {tid: pos for pos, tid in enumerate(order, start=1)}
    return {tid: pos for pos, tid in enumerate(by_rating, start=1)}


# --------------------------------------------------------------------------- car ratings & development

def ensure_car_ratings(conn, season_id):
    """Every active team gets a car rating per season: carried from the previous season, else seeded
    from the default team order."""
    have = {r["team_id"] for r in _rows(conn, "SELECT team_id FROM team_seasons WHERE season_id = ?", (season_id,))}
    active = teams(conn)
    missing = [t for t in active if t["id"] not in have]
    if not missing:
        return
    season = get_season(conn, season_id)
    prev = _row(conn, "SELECT id FROM seasons WHERE year < ? ORDER BY year DESC LIMIT 1", (season["year"],)) if season else None
    prev_ratings = {r["team_id"]: r["car_rating"] for r in _rows(
        conn, "SELECT * FROM team_seasons WHERE season_id = ?", (prev["id"],))} if prev else {}
    floor = min(list(prev_ratings.values()) + [C.CAR_RATING_TOP - (len(active) - 1) * C.CAR_RATING_STEP])
    for pos, team in enumerate(active, start=1):
        if team["id"] in have:
            continue
        if team["id"] in prev_ratings:
            rating = prev_ratings[team["id"]]
        elif team["id"] <= len(C.TEAMS):
            rating = C.CAR_RATING_TOP - (pos - 1) * C.CAR_RATING_STEP
        else:
            rating = floor - 2  # a brand-new team starts at the back
        conn.execute("INSERT INTO team_seasons(season_id, team_id, car_rating, change) VALUES(?,?,?,0)",
                     (season_id, team["id"], round(clamp(rating, C.CAR_RATING_MIN, C.CAR_RATING_MAX), 1)))


def car_ratings(conn, season_id):
    ensure_car_ratings(conn, season_id)
    return {r["team_id"]: {"rating": r["car_rating"], "change": r["change"]}
            for r in _rows(conn, "SELECT * FROM team_seasons WHERE season_id = ?", (season_id,))}


def set_car_rating(conn, season_id, team_id, rating):
    try:
        rating = round(float(rating), 1)
    except (TypeError, ValueError):
        raise ValidationError("Car ratings must be numbers")
    if not C.CAR_RATING_MIN <= rating <= C.CAR_RATING_MAX:
        raise ValidationError(f"Car ratings run from {C.CAR_RATING_MIN:.0f} to {C.CAR_RATING_MAX:.0f}")
    ensure_car_ratings(conn, season_id)
    conn.execute("UPDATE team_seasons SET car_rating = ? WHERE season_id = ? AND team_id = ?",
                 (rating, season_id, team_id))


def develop_cars(conn, source_id, new_id, rng):
    """Winter development: every car moves toward the pack (cost cap, wind-tunnel handicaps), results
    bring money (constructors' position), and there is always some luck. Returns the changes."""
    old = car_ratings(conn, source_id)
    table = {t["team"]["id"]: t["position"] for t in constructor_standings(conn, source_id)}
    mean = sum(v["rating"] for v in old.values()) / max(1, len(old))
    field = len(table) or 11
    changes = []
    for team in teams(conn):
        base = old.get(team["id"], {"rating": mean - 2})["rating"]
        pos = table.get(team["id"], field)
        change = (mean - base) * 0.2 + ((field + 1) / 2 - pos) * 0.35 + rng.gauss(0, 2.2)
        change = round(clamp(change, -8, 8), 1)
        rating = round(clamp(base + change, C.CAR_RATING_MIN, C.CAR_RATING_MAX), 1)
        change = round(rating - base, 1)
        conn.execute("""INSERT INTO team_seasons(season_id, team_id, car_rating, change) VALUES(?,?,?,?)
                        ON CONFLICT(season_id, team_id) DO UPDATE SET car_rating = excluded.car_rating,
                        change = excluded.change""", (new_id, team["id"], rating, change))
        changes.append({"team": team, "rating": rating, "change": change})
    changes.sort(key=lambda c: -c["change"])
    return changes


# --------------------------------------------------------------------------- race entry

def weekend_rows(conn, event_id):
    event = get_event(conn, event_id)
    if event["status"] == C.EVENT_NOT_RUN:
        sync_not_run_results(conn, event["season_id"])
    order = _grid_order(conn, event["season_id"])
    tmap = team_map(conn)
    dmap = driver_map(conn)
    rows = []
    for r in _rows(conn, "SELECT * FROM results WHERE event_id = ?", (event_id,)):
        r = dict(r)
        r["driver"] = dmap[r["driver_id"]]
        r["team"] = tmap[r["team_id"]]
        seat = order.get(r["driver_id"])
        r["sort"] = seat if seat and seat[0] == r["team_id"] else (r["team_id"], 3)
        r["gp_points"] = gp_points(r["race_position"], r["result_status"])
        r["sprint_pts"] = sprint_points(r["sprint_position"], r["sprint_status"], bool(event["is_sprint"]))
        rows.append(r)
    rows.sort(key=lambda r: (r["sort"], r["driver"]["name"]))
    return rows


def _resolve(override, position):
    if override and override != "Auto":
        return override
    return C.STATUS_FINISHED if position else C.STATUS_NOT_RUN


def save_weekend(conn, event_id, payload):
    event = get_event(conn, event_id)
    if not event:
        raise ValidationError("Event not found")
    is_sprint = bool(event["is_sprint"])
    existing = {r["driver_id"]: dict(r) for r in _rows(conn, "SELECT * FROM results WHERE event_id = ?",
                                                       (event_id,))}
    entries = payload.get("results") or []
    if not isinstance(entries, list):
        raise ValidationError("Results must be a list")
    final = {did: dict(r) for did, r in existing.items()}
    max_pos = max(C.MAX_POSITION, len(final))
    for item in entries:
        try:
            did = int(item.get("driver_id"))
        except (TypeError, ValueError, AttributeError):
            raise ValidationError("Invalid driver in results")
        if did not in final:
            raise ValidationError("Driver is not entered in this event")
        row = final[did]
        row["qualifying_position"] = parse_position(item.get("qualifying_position"), "Qualifying position", max_pos)
        row["race_position"] = parse_position(item.get("race_position"), "Race position", max_pos)
        override = item.get("status_override") or "Auto"
        s_override = item.get("sprint_status_override") or "Auto"
        if override not in C.OVERRIDE_STATUSES or s_override not in C.OVERRIDE_STATUSES:
            raise ValidationError("Unknown result status")
        row["result_status"] = _resolve(override, row["race_position"])
        if is_sprint:
            row["sprint_position"] = parse_position(item.get("sprint_position"), "Sprint position", max_pos)
            row["sprint_status"] = _resolve(s_override, row["sprint_position"])
        else:
            row["sprint_position"], row["sprint_status"] = None, C.STATUS_NOT_RUN
        row["fastest_lap"] = int(bool(item.get("fastest_lap")))
        row["driver_of_day"] = int(bool(item.get("driver_of_day")))
        notes = str(item.get("notes") or "")
        if len(notes) > 1000:
            raise ValidationError("Driver notes are limited to 1,000 characters")
        row["notes"] = notes

    for field, label in (("qualifying_position", "qualifying"), ("race_position", "race"),
                         ("sprint_position", "Sprint")):
        values = [r[field] for r in final.values() if r[field]]
        if len(values) != len(set(values)):
            raise ValidationError(f"Two drivers cannot share the same {label} position")
    if sum(r["fastest_lap"] for r in final.values()) > 1:
        raise ValidationError("Only one driver can receive Fastest Lap")
    if sum(r["driver_of_day"] for r in final.values()) > 1:
        raise ValidationError("Only one driver can receive Driver of the Day")

    event_notes = str(payload.get("event_notes", event["notes"]) or "")
    if len(event_notes) > 4000:
        raise ValidationError("Weekend notes are limited to 4,000 characters")
    difficulty = parse_difficulty(payload.get("ai_difficulty", event["ai_difficulty"]))
    untracked = bool(payload.get("ai_untracked", event["ai_untracked"])) and difficulty is None

    gp_left = sum(1 for r in final.values() if r["result_status"] == C.STATUS_NOT_RUN)
    sprint_left = sum(1 for r in final.values() if r["sprint_status"] == C.STATUS_NOT_RUN) if is_sprint else 0
    complete_all = bool(final) and gp_left == 0 and sprint_left == 0
    if payload.get("mark_complete") and not complete_all:
        parts = []
        if sprint_left:
            parts.append(f"{sprint_left} Sprint result{'s' if sprint_left != 1 else ''}")
        if gp_left:
            parts.append(f"{gp_left} GP result{'s' if gp_left != 1 else ''}")
        raise ValidationError("Cannot complete yet: " + " and ".join(parts) + " still incomplete")

    stamp = now_iso()
    for did, r in final.items():
        conn.execute("""UPDATE results SET qualifying_position=?, sprint_position=?, sprint_status=?,
                        race_position=?, result_status=?, fastest_lap=?, driver_of_day=?, notes=?, updated_at=?
                        WHERE event_id=? AND driver_id=?""",
                     (r["qualifying_position"], r["sprint_position"], r["sprint_status"], r["race_position"],
                      r["result_status"], r["fastest_lap"], r["driver_of_day"], r["notes"], stamp,
                      event_id, did))
    any_data = any(_result_has_data(r) for r in final.values())
    if complete_all and (payload.get("mark_complete") or event["status"] == C.EVENT_COMPLETE):
        status = C.EVENT_COMPLETE
    elif any_data:
        status = C.EVENT_IN_PROGRESS
    else:
        status = C.EVENT_NOT_RUN
    conn.execute("UPDATE events SET status=?, notes=?, ai_difficulty=?, ai_untracked=?, revision = revision + 1 WHERE id=?",
                 (status, event_notes, difficulty, int(untracked), event_id))
    revision = conn.execute("SELECT revision FROM events WHERE id = ?", (event_id,)).fetchone()[0]
    return {"status": status, "complete": status == C.EVENT_COMPLETE, "ai_difficulty": difficulty,
            "gp_left": gp_left, "sprint_left": sprint_left, "revision": revision}


RESULT_FIELDS = ("qualifying_position", "sprint_position", "sprint_status", "race_position", "result_status",
                 "fastest_lap", "driver_of_day", "notes")


def weekend_snapshot(conn, event_id):
    """The saved state of a round, in the shape the entry page sends, for conflict checks after offline edits."""
    event = get_event(conn, event_id)
    rows = {}
    for r in _rows(conn, "SELECT * FROM results WHERE event_id = ?", (event_id,)):
        rows[str(r["driver_id"])] = {
            "qualifying_position": r["qualifying_position"], "race_position": r["race_position"],
            "sprint_position": r["sprint_position"],
            "status_override": r["result_status"] if r["result_status"] in C.OVERRIDE_STATUSES else "Auto",
            "sprint_status_override": r["sprint_status"] if r["sprint_status"] in C.OVERRIDE_STATUSES else "Auto",
            "fastest_lap": bool(r["fastest_lap"]), "driver_of_day": bool(r["driver_of_day"]), "notes": r["notes"] or ""}
    return {"revision": event["revision"], "status": event["status"], "ai_difficulty": event["ai_difficulty"],
            "ai_untracked": bool(event["ai_untracked"]),
            "event_notes": event["notes"] or "", "results": rows}


def submission_check(conn, event_id):
    """Final review before a round is submitted: blocking errors, warnings and a summary, from the saved data."""
    event = get_event(conn, event_id)
    rows = weekend_rows(conn, event_id)
    sprint = bool(event["is_sprint"])
    blocking, warnings = [], []
    name = lambda r: r["driver"]["name"]
    gp_left = [name(r) for r in rows if r["result_status"] == C.STATUS_NOT_RUN]
    if gp_left:
        blocking.append(f"Grand Prix result missing for {len(gp_left)} driver{'s' if len(gp_left) != 1 else ''}: "
                        + ", ".join(gp_left[:6]) + ("…" if len(gp_left) > 6 else ""))
    if sprint:
        sp_left = [name(r) for r in rows if r["sprint_status"] == C.STATUS_NOT_RUN]
        if sp_left:
            blocking.append(f"Sprint result missing for {len(sp_left)} driver{'s' if len(sp_left) != 1 else ''}: "
                            + ", ".join(sp_left[:6]) + ("…" if len(sp_left) > 6 else ""))
    # Qualifying is required once any is entered (a half-entered session is an error); none at all is only a warning.
    any_quali = any(r["qualifying_position"] for r in rows)
    no_quali = [name(r) for r in rows if r["result_status"] in C.START_STATUSES and not r["qualifying_position"]]
    if not any_quali:
        warnings.append("No qualifying positions entered (pole and racecraft won't count this round)")
    elif no_quali:
        blocking.append(f"Qualifying position missing for {len(no_quali)} driver{'s' if len(no_quali) != 1 else ''} "
                        "who started: " + ", ".join(no_quali[:6]) + ("…" if len(no_quali) > 6 else ""))
    for field, label in (("qualifying_position", "qualifying"), ("race_position", "Grand Prix"), ("sprint_position", "Sprint")):
        values = [r[field] for r in rows if r[field]]
        if len(values) != len(set(values)):
            blocking.append(f"Two drivers share a {label} position")
    for r in rows:
        if r["result_status"] == "DNS" and r["race_position"]:
            blocking.append(f"{name(r)} is DNS but has a Grand Prix position (P{r['race_position']})")
        if sprint and r["sprint_status"] == "DNS" and r["sprint_position"]:
            blocking.append(f"{name(r)} is DNS in the Sprint but has a Sprint position (P{r['sprint_position']})")
    fl = [r for r in rows if r["fastest_lap"]]
    dotd = [r for r in rows if r["driver_of_day"]]
    if len(fl) > 1:
        blocking.append("More than one driver has Fastest Lap")
    elif fl and fl[0]["result_status"] not in C.START_STATUSES:
        blocking.append(f"Fastest Lap is given to {name(fl[0])}, who didn't start the race")
    elif not fl:
        warnings.append("No Fastest Lap selected")
    if len(dotd) > 1:
        blocking.append("More than one driver has Driver of the Day")
    elif not dotd:
        warnings.append("No Driver of the Day selected")
    if event["ai_difficulty"] is None and not event["ai_untracked"]:
        blocking.append("Enter the AI difficulty used, or press \"Don't track this round\"")
    elif event["ai_difficulty"] is None:
        warnings.append("AI difficulty deliberately not tracked for this round (the recommender will skip it)")
    # Positions within a session must run 1, 2, 3… with no holes (a classified gap can't happen).
    for field, label in (("qualifying_position", "Qualifying"), ("race_position", "Grand Prix"), ("sprint_position", "Sprint")):
        if field == "sprint_position" and not sprint:
            continue
        taken = sorted(set(r[field] for r in rows if r[field]))
        if taken:
            missing = [p for p in range(1, taken[-1] + 1) if p not in taken]
            if missing:
                blocking.append(f"{label} positions skip " + ", ".join(f"P{p}" for p in missing[:6])
                                + ("…" if len(missing) > 6 else "") + " (positions must run 1, 2, 3… without gaps)")
    for r in rows:
        if r["result_status"] in ("DNF", "DSQ") and r["race_position"]:
            warnings.append(f"{name(r)} is {r['result_status']} with a position (P{r['race_position']}); they score no points")
    if not (event["notes"] or "").strip():
        warnings.append("No weekend notes")
    # Player drivers' rows are called out on their own so they're never missed.
    player_issues = []
    for r in rows:
        if not r["driver"]["is_player"]:
            continue
        gaps = []
        if r["result_status"] == C.STATUS_NOT_RUN:
            gaps.append("Grand Prix result")
        if sprint and r["sprint_status"] == C.STATUS_NOT_RUN:
            gaps.append("Sprint result")
        if any_quali and not r["qualifying_position"] and r["result_status"] in C.START_STATUSES:
            gaps.append("qualifying position")
        if gaps:
            player_issues.append({"name": name(r), "color": r["driver"]["player_color"], "missing": gaps})

    def finisher(field, status_field, pos):
        return next((r for r in rows if r[field] == pos and r[status_field] == C.STATUS_FINISHED), None)
    order = sorted((r for r in rows if r["result_status"] == C.STATUS_FINISHED and r["race_position"]),
                   key=lambda r: r["race_position"])
    summary = {
        "round": event["round_number"], "event": event["name"], "sprint": sprint,
        "pole": next((name(r) for r in rows if r["qualifying_position"] == 1), None),
        "sprint_winner": name(finisher("sprint_position", "sprint_status", 1)) if sprint and finisher("sprint_position", "sprint_status", 1) else None,
        "winner": name(order[0]) if order else None,
        "podium": [name(r) for r in order[:3]],
        "out": {s: [name(r) for r in rows if r["result_status"] == s] for s in ("DNF", "DNS", "DSQ")},
        "fastest_lap": name(fl[0]) if len(fl) == 1 else None,
        "dotd": name(dotd[0]) if len(dotd) == 1 else None,
        "players": [{"name": name(r), "color": r["driver"]["player_color"],
                     "quali": r["qualifying_position"], "race": (f"P{r['race_position']}" if r["result_status"] == C.STATUS_FINISHED
                                                                 else r["result_status"]),
                     "sprint": (f"P{r['sprint_position']}" if r["sprint_status"] == C.STATUS_FINISHED else r["sprint_status"]) if sprint else None,
                     "points": r["gp_points"] + r["sprint_pts"]}
                    for r in rows if r["driver"]["is_player"]],
        "ai_difficulty": event["ai_difficulty"],
    }
    return {"blocking": blocking, "warnings": warnings, "summary": summary, "revision": event["revision"],
            "status": event["status"], "player_issues": player_issues,
            "lock_notice": "Completing this round locks it for Scorekeepers. Only a Race Master can correct or reopen it afterwards."}


# --------------------------------------------------------------------------- AI difficulty

def _signal(value):
    return clamp(value, -1.0, 1.0)


def difficulty_mode(conn):
    """How the league judges a round for the AI recommendation (v2.4.1): "blend" (default), "car" or "overall"."""
    row = _row(conn, "SELECT value FROM meta WHERE key = 'difficulty_mode'")
    return row["value"] if row and row["value"] in C.DIFF_MODES else C.DIFF_MODE_DEFAULT


def _round_part(expected, pos, quali, points_for, is_sprint, sprint_pos, sprint_status, with_sprint, teammate):
    """One reading of a finish (-1..1) against an expected position: finish, qualifying, points and teammate."""
    finish = _signal((expected - pos) / C.DIFF_PLACES)
    q = _signal((expected - quali) / C.DIFF_PLACES) if quali else 0.0
    par = max(1, round(expected))
    pts = points_for(pos, sprint_pos, sprint_status)
    par_pts = gp_points(par, C.STATUS_FINISHED) + (sprint_points(par, C.STATUS_FINISHED, is_sprint) if with_sprint else 0)
    points = _signal((pts - par_pts) / C.DIFF_POINTS_SCALE)
    if teammate is None:
        # No AI teammate to compare with (two players in one car): the other parts share its weight.
        return (0.40 * finish + 0.20 * q + 0.15 * points) / 0.75
    return 0.40 * finish + 0.20 * q + 0.15 * points + 0.25 * teammate


def player_event_score(conn, event, ranks=None, mode=None):
    """Average performance score of the player drivers who finished this GP, or None.

    v2.4.1: each finish is read two ways. "Car": against where this car should finish (2 x rank - 0.5).
    "Overall": against the middle of the grid, whatever the car, so finishing at the back always reads as
    struggling. The league's mode picks car, overall or a blend (DIFF_OVERALL_SHARE overall)."""
    rows = _rows(conn, """SELECT r.*, d.is_player FROM results r JOIN drivers d ON d.id = r.driver_id
                          WHERE r.event_id = ?""", (event["id"],))
    by_team = {}
    for r in rows:
        by_team.setdefault(r["team_id"], []).append(r)
    mode = mode or difficulty_mode(conn)
    share = {"car": 0.0, "overall": 1.0}.get(mode, C.DIFF_OVERALL_SHARE)
    middle = (len(rows) + 1) / 2 if len(rows) >= 2 else (C.GRID_SIZE + 1) / 2
    scores = []
    details = []
    # v2.0: Sprint points only count when the league explicitly says so (League settings → Career systems).
    with_sprint = (_row(conn, "SELECT value FROM meta WHERE key = 'difficulty_sprints'") or {"value": "1"})["value"] == "1"
    is_sprint = bool(event["is_sprint"])

    def points_for(pos, sprint_pos, sprint_status):
        return gp_points(pos, C.STATUS_FINISHED) + (sprint_points(sprint_pos, sprint_status, is_sprint) if with_sprint else 0)

    for r in rows:
        if not r["is_player"] or r["result_status"] != C.STATUS_FINISHED or not r["race_position"]:
            continue
        pos = r["race_position"]
        expected = 2 * ranks[r["team_id"]] - 0.5 if ranks and r["team_id"] in ranks else middle
        mate = next((m for m in by_team.get(r["team_id"], []) if not m["is_player"] and m["race_position"]
                     and m["result_status"] == C.STATUS_FINISHED), None)
        teammate = _signal((mate["race_position"] - pos) / 10) if mate else None
        args = (pos, r["qualifying_position"], points_for, is_sprint, r["sprint_position"], r["sprint_status"],
                with_sprint, teammate)
        car = _round_part(expected, *args)
        overall = _round_part(middle, *args)
        score = (1 - share) * car + share * overall
        scores.append(score)
        details.append({"driver_id": r["driver_id"], "position": pos, "score": round(score, 3),
                        "car": round(car, 3), "overall": round(overall, 3), "expected": round(expected, 1)})
    if not scores:
        return None, details
    return sum(scores) / len(scores), details


def difficulty_history(conn, before=None):
    """Completed, tracked rounds across every season, oldest first.

    before: optional (year, round) - only rounds strictly earlier are returned.
    """
    out = []
    ranks_cache = {}
    rows = _rows(conn, """SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                          WHERE e.status = ? AND e.ai_difficulty IS NOT NULL
                          ORDER BY s.year, e.round_number""", (C.EVENT_COMPLETE,))
    for e in rows:
        if before and (e["year"], e["round_number"]) >= before:
            continue
        e = dict(e)
        if e["season_id"] not in ranks_cache:
            ranks_cache[e["season_id"]] = team_strength_ranks(conn, e["season_id"])
        score, details = player_event_score(conn, e, ranks_cache[e["season_id"]])
        e["score"] = None if score is None else round(score, 3)
        e["details"] = details
        out.append(e)
    return out


def sweet_spot(history):
    """Recency-weighted estimate of the difficulty where the players score an even 0."""
    usable = [h for h in history if h["score"] is not None]
    if len(usable) < C.DIFF_MIN_ROUNDS:
        return None
    total = weight_sum = 0.0
    for age, h in enumerate(reversed(usable)):
        weight = 0.5 ** (age / C.DIFF_HALF_LIFE)
        shift = clamp(h["score"] / C.DIFF_SENSITIVITY, -C.DIFF_SWEETSPOT_SPREAD, C.DIFF_SWEETSPOT_SPREAD)
        total += weight * (h["ai_difficulty"] + shift)
        weight_sum += weight
    value = clamp(total / weight_sum, C.MIN_DIFFICULTY, C.MAX_DIFFICULTY)
    n = len(usable)
    confidence = "High" if n >= 15 else "Medium" if n >= 8 else "Low"
    seasons = len({h["season_id"] for h in usable})
    return {"value": round(value, 1), "rounds": n, "seasons": seasons, "confidence": confidence}


def difficulty_recommendation(conn, before=None):
    history = difficulty_history(conn, before)
    rec = {"current": None, "recommended": None, "direction": None, "average": None, "sample": [],
           "sweet_spot": sweet_spot(history), "note": None, "history_rounds": len(history)}
    if not history:
        rec["reason"] = "Track the AI difficulty on a completed round to establish a baseline."
        return rec
    current = history[-1]["ai_difficulty"]
    rec["current"] = current
    # Tracked rounds where no player driver finished say nothing about the level (DNFs don't count).
    rec["unusable"] = sum(1 for h in history[-C.DIFF_RECENT_ROUNDS:] if h["score"] is None)
    excluded = []
    for h in reversed(history[-C.DIFF_RECENT_ROUNDS:]):
        if h["score"] is None:
            excluded.append({"label": f"{h['year']} R{h['round_number']} {h['name']}",
                             "why": "no player driver finished (DNFs don't count)"})
    untracked = _rows(conn, """SELECT e.round_number, e.name, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                               WHERE e.status = ? AND e.ai_untracked = 1 ORDER BY s.year DESC, e.round_number DESC LIMIT 3""",
                      (C.EVENT_COMPLETE,))
    excluded += [{"label": f"{r['year']} R{r['round_number']} {r['name']}", "why": "marked \"Don't track this round\""}
                 for r in untracked]
    rec["excluded"] = excluded[:6]
    rec["recent"] = [{"label": f"R{h['round_number']}", "year": h["year"], "difficulty": h["ai_difficulty"],
                      "score": h["score"]} for h in history[-12:]]

    last = next((h for h in reversed(history) if h["score"] is not None), None)
    if last and last["score"] <= -C.DIFF_THRESHOLD:
        rec["note"] = (f"The {last['year']} {last['name']} was a tough one. It counts, weighed against the rounds "
                       "around it, so one bad day only nudges the level.")
    elif last and last["score"] >= C.DIFF_THRESHOLD:
        rec["note"] = (f"The {last['year']} {last['name']} was a strong one. It counts, weighed against the rounds "
                       "around it.")

    _adaptive(conn, rec, history, current)
    return rec


def _soft(score):
    """Scores near zero mean the level is about right; only the part beyond the dead band says to move."""
    return math.copysign(max(0.0, abs(score) - C.DIFF_DEADBAND), score)


def difficulty_band(level):
    """The game's own name for a level (Beginner 1-40, Casual 41-65, Intermediate / Advanced 66-99, Expert 100-110)."""
    if level is None:
        return None
    for lo, hi, name in C.DIFF_BANDS:
        if lo <= level <= hi:
            return name
    return C.DIFF_BANDS[-1][2] if level > C.DIFF_BANDS[-1][1] else C.DIFF_BANDS[0][2]


_NUMBERS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]


def _evidence_line(conn, rec, usable):
    """One readable line: how many rounds count, which don't and why, and whether Sprints were counted (v2.2)."""
    n = len(usable)
    parts = [f"{_NUMBERS[n] if n < len(_NUMBERS) else n} usable round{'s' if n != 1 else ''}"
             + (" (" + ", ".join(f"R{h['round_number']}" for h in usable[-6:]) + ("…" if n > 6 else "") + ")" if n else "")]
    if n > 1:
        parts.append("latest weighted most")
    for x in rec.get("excluded", []):
        short = x["label"].split(" ")[1] if " " in x["label"] else x["label"]
        parts.append(f"{short} " + ("untracked" if "track" in x["why"] else "excluded (no player finished)"))
    sprints = (_row(conn, "SELECT value FROM meta WHERE key = 'difficulty_sprints'") or {"value": "1"})["value"] == "1"
    parts.append({"car": "judged against each car", "overall": "judged against the whole grid"}.get(
        difficulty_mode(conn), "judged half against each car, half against the whole grid"))
    parts.append("Sprint points counted" if sprints else "Sprint points not counted")
    return ", ".join(parts) + "."


def _adaptive(conn, rec, history, current):
    """v2.1: feel out the right level from every tracked round (at any AI level), player by player.

    Each usable round says, for each player driver who finished, "this player could handle about
    difficulty + score x SPAN" (capped per round). Recent rounds weigh more. If the players agree the
    recommendation moves by their average; if one is struggling and another is fine it moves half as far
    (so it goes down a little); with little evidence it only moves a little. Never more than MAX_STEP at once.
    """
    usable = [h for h in history if h["score"] is not None][-C.DIFF_RECENT_ROUNDS:]
    rec["sample"] = usable
    rec["used"] = [{"label": f"{h['year']} R{h['round_number']} {h['name']}", "difficulty": h["ai_difficulty"],
                    "score": h["score"]} for h in usable]
    rec["recommended"], rec["direction"], rec["players"] = current, "hold", []
    rec["band"] = difficulty_band(current)
    rec["evidence"] = _evidence_line(conn, rec, usable)
    if not usable:
        rec["reason"] = (f"No usable rounds yet: a tracked round needs at least one player driver to finish. "
                         f"Holding at {current}.")
        return
    dmap = driver_map(conn)
    per = {}
    for age, h in enumerate(reversed(usable)):
        w = 0.5 ** (age / C.DIFF_RECENT_HALF_LIFE)
        for d in h["details"]:
            shift = clamp(_soft(d["score"]) * C.DIFF_SPAN, -C.DIFF_ROUND_CAP, C.DIFF_ROUND_CAP)
            overall = d.get("overall", d["score"])
            shift_overall = clamp(_soft(overall) * C.DIFF_SPAN, -C.DIFF_ROUND_CAP, C.DIFF_ROUND_CAP)
            p = per.setdefault(d["driver_id"], {"w": 0.0, "sum": 0.0, "overall": 0.0, "rounds": 0})
            p["w"] += w
            p["sum"] += w * (h["ai_difficulty"] + shift)
            p["overall"] += w * shift_overall
            p["rounds"] += 1
    players = []
    for did, p in per.items():
        level = p["sum"] / p["w"]
        delta = level - current
        verdict = ("struggling" if delta <= -C.DIFF_VERDICT else "comfortable" if delta >= C.DIFF_VERDICT
                   else "about right")
        # v2.4.1: how they're doing against the whole grid, whatever the car (levels above/below the one used).
        overall = p["overall"] / p["w"]
        players.append({"driver_id": did, "name": dmap[did]["name"] if did in dmap else "A player", "rounds": p["rounds"],
                        "level": round(level, 1), "delta": round(delta, 1), "verdict": verdict, "weight": p["w"],
                        "overall": round(overall, 1), "at_back": overall <= -C.DIFF_BACK})
    players.sort(key=lambda x: x["delta"])
    rec["players"] = players
    rec["average"] = round(sum(h["score"] for h in usable[-5:]) / len(usable[-5:]), 3)
    ups = [x for x in players if x["verdict"] == "comfortable"]
    downs = [x for x in players if x["verdict"] == "struggling"]
    mean = sum(x["delta"] for x in players) / len(players)
    weight = sum(x["weight"] for x in players) / len(players)
    confidence = weight / (weight + C.DIFF_CONFIDENCE_K)
    rec["confidence"] = round(confidence, 2)
    mixed = bool(ups and downs)
    raw = mean * (C.DIFF_MIXED if mixed else 1.0) * confidence
    step = int(round(clamp(raw, -C.DIFF_MAX_STEP, C.DIFF_MAX_STEP)))
    if not ups and not downs:
        step = 0
    # v2.4.1: never raise the level while anyone is struggling, on the blended reading or against the whole grid
    # (e.g. at the back in a slow car): they need the chance to move up the order first.
    held = [x for x in players if x["verdict"] == "struggling" or x["at_back"]]
    blocked = step > 0 and bool(held)
    if blocked:
        step = 0
    rec["held_by"] = [x["name"] for x in held] if blocked else []
    rec["recommended"] = int(clamp(current + step, C.MIN_DIFFICULTY, C.MAX_DIFFICULTY))
    step = rec["recommended"] - current
    rec["direction"] = "up" if step > 0 else "down" if step < 0 else "hold"
    rec["band"] = difficulty_band(rec["recommended"])

    def who(xs):
        return " and ".join(x["name"] for x in xs)
    n = len(usable)
    evidence = f"{n} recent round{'s' if n != 1 else ''}"
    if step == 0:
        if blocked:
            rec["reason"] = (f"Results say AI {current} could go up, but {who(held)} "
                             f"{'is' if len(held) == 1 else 'are'} still near the back of the grid, so it holds at "
                             f"{current} until {'they move' if len(held) > 1 else 'that changes'}.")
        elif mixed:
            rec["reason"] = (f"{who(downs)} {'is' if len(downs) == 1 else 'are'} finding AI {current} hard while "
                             f"{who(ups)} {'is' if len(ups) == 1 else 'are'} comfortable. Too close to call: hold at {current}.")
        elif ups or downs:
            rec["reason"] = f"Leaning {'up' if ups else 'down'}, but not enough evidence yet ({evidence}). Hold at {current}."
        else:
            rec["reason"] = f"Results over {evidence} say AI {current} is about right. Hold."
        return
    size = abs(step)
    word = ("Raise" if step > 0 else "Lower") + f" by {size}"
    if mixed:
        rec["reason"] = (f"{word}: {who(downs)} {'is' if len(downs) == 1 else 'are'} struggling but {who(ups)} "
                         f"{'is' if len(ups) == 1 else 'are'} doing fine, so only a small change.")
    elif len(players) > 1 and (len(ups) == len(players) or len(downs) == len(players)):
        rec["reason"] = (f"{word}: every player driver is {'on top of' if step > 0 else 'struggling at'} AI {current} "
                         f"({evidence}).")
    else:
        mover = ups or downs
        rec["reason"] = (f"{word}: {who(mover)} {'is' if len(mover) == 1 else 'are'} "
                         f"{'comfortable' if step > 0 else 'struggling'} at AI {current} ({evidence}).")
    if confidence < 0.5:
        rec["reason"] += " Still feeling it out, so the step is small."
    if difficulty_band(current) != rec["band"]:
        rec["reason"] += f" That moves it from {difficulty_band(current)} into {rec['band']}."


# --------------------------------------------------------------------------- seasons & calendar

def next_incomplete_event(conn, season_id):
    row = _row(conn, "SELECT * FROM events WHERE season_id = ? AND status != ? ORDER BY round_number LIMIT 1",
               (season_id, C.EVENT_COMPLETE))
    return dict(row) if row else None


def season_final_reputation(conn, season_id):
    """{driver_id: outgoing Reputation}. Inactive drivers carry their entering value unchanged."""
    standings = {r["driver_id"]: r for r in driver_standings(conn, season_id)}
    out = {}
    for state in _rows(conn, "SELECT * FROM season_driver_state WHERE season_id = ?", (season_id,)):
        did = state["driver_id"]
        if state["locked_reputation"] is not None:
            out[did] = state["locked_reputation"]
        elif did in standings:
            out[did] = standings[did]["reputation"]
        else:
            out[did] = state["starting_reputation"]
    for d in drivers(conn):
        out.setdefault(d["id"], standings[d["id"]]["reputation"] if d["id"] in standings
                       else d["baseline_reputation"])
    return out


def create_next_season(conn, source_id, year):
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise ValidationError("Season year must be a number")
    if not C.MIN_YEAR <= year <= C.MAX_YEAR:
        raise ValidationError(f"Season year must be between {C.MIN_YEAR} and {C.MAX_YEAR}")
    if _row(conn, "SELECT 1 FROM seasons WHERE year = ?", (year,)):
        raise ValidationError(f"A {year} season already exists")
    source = get_season(conn, source_id)
    if not source:
        raise ValidationError("Source season not found")
    final = season_final_reputation(conn, source_id)
    for did, rep in final.items():
        conn.execute("""INSERT INTO season_driver_state(season_id, driver_id, starting_reputation, locked_reputation)
                        VALUES(?,?,?,?) ON CONFLICT(season_id, driver_id)
                        DO UPDATE SET locked_reputation = excluded.locked_reputation""",
                     (source_id, did, rep, rep))
    conn.execute("UPDATE seasons SET status = ? WHERE id = ?", (C.SEASON_COMPLETE, source_id))
    new_id = conn.execute("INSERT INTO seasons(year, label, status, created_at) VALUES(?,?,?,?)",
                          (year, f"{year} World Championship", C.SEASON_ACTIVE, now_iso())).lastrowid
    for (team_id, seat_no), did in grid_map(conn, source_id).items():
        conn.execute("INSERT INTO season_grid VALUES(?,?,?,?)", (new_id, team_id, seat_no, did))
    for did, rep in final.items():
        conn.execute("INSERT INTO season_driver_state VALUES(?,?,?,NULL)", (new_id, did, rep))
    for e in events(conn, source_id):
        conn.execute("INSERT INTO events(season_id, round_number, name, location, is_sprint) VALUES(?,?,?,?,?)",
                     (new_id, e["round_number"], e["name"], e["location"], e["is_sprint"]))
    set_meta(conn, "current_season_id", new_id)
    sync_not_run_results(conn, new_id)
    return new_id


def make_current(conn, season_id):
    if not get_season(conn, season_id):
        raise ValidationError("Season not found")
    set_meta(conn, "current_season_id", season_id)


def save_calendar(conn, season_id, entries, history=False):
    """entries: list of {id, round_number, name, location, is_sprint}. Swaps are applied atomically.

    Rounds that already have results keep their number and Sprint format (so history and points never move)
    unless `history` is set: the Race Master's explicit historical-correction mode."""
    current = {e["id"]: e for e in events(conn, season_id)}
    own = set(current)
    rounds = []
    cleaned = []
    for e in entries:
        try:
            eid = int(e["id"])
            rnd = int(e["round_number"])
        except (TypeError, ValueError, KeyError):
            raise ValidationError("Round numbers must be whole numbers")
        if eid not in own:
            raise ValidationError("Event does not belong to this season")
        name = (e.get("name") or "").strip()
        if not name:
            raise ValidationError("Every event needs a name")
        if rnd < 1:
            raise ValidationError("Round numbers start at 1")
        rounds.append(rnd)
        sprint = int(bool(e.get("is_sprint")))
        before = current[eid]
        if not history and before["status"] != C.EVENT_NOT_RUN and (rnd != before["round_number"] or sprint != before["is_sprint"]):
            raise ValidationError(f"R{before['round_number']} {before['name']} already has results, so its round number and "
                                  "Sprint format are locked. Use historical correction mode if they really are wrong.")
        cleaned.append((eid, rnd, name[:80], (e.get("location") or "").strip()[:80], sprint))
    if len(rounds) != len(set(rounds)):
        raise ValidationError("Round numbers must be unique")
    for eid, *_ in cleaned:
        conn.execute("UPDATE events SET round_number = -id WHERE id = ?", (eid,))
    for eid, rnd, name, loc, sprint in cleaned:
        conn.execute("UPDATE events SET round_number=?, name=?, location=?, is_sprint=? WHERE id=?",
                     (rnd, name, loc, sprint, eid))


# --------------------------------------------------------------------------- driver market narrative

def add_contract(conn, season_id, form):
    try:
        driver_id = int(form.get("driver_id"))
    except (TypeError, ValueError):
        raise ValidationError("Choose a driver")
    if not _row(conn, "SELECT 1 FROM drivers WHERE id = ?", (driver_id,)):
        raise ValidationError("Choose a driver")
    team_id = form.get("team_id") or None
    if team_id is not None:
        team_id = int(team_id)
        if not _row(conn, "SELECT 1 FROM teams WHERE id = ?", (team_id,)):
            raise ValidationError("Unknown team")
    stage = form.get("negotiation_stage")
    role = form.get("requested_role")
    if stage not in C.NEGOTIATION_STAGES:
        raise ValidationError("Unknown negotiation stage")
    if role not in C.REQUESTED_ROLES:
        raise ValidationError("Unknown requested role")
    conn.execute("""INSERT INTO contracts(season_id, driver_id, team_id, negotiation_stage, requested_role,
                    team_response, outcome, conditions, notes, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                 (season_id, driver_id, team_id, stage, role, (form.get("team_response") or "")[:500],
                  (form.get("outcome") or "")[:500], (form.get("conditions") or "")[:1000],
                  (form.get("notes") or "")[:2000], now_iso()))


def contracts(conn, season_id):
    standings = {r["driver_id"]: r for r in driver_standings(conn, season_id)}
    dmap, tmap = driver_map(conn), team_map(conn)
    out = []
    for c in _rows(conn, "SELECT * FROM contracts WHERE season_id = ? ORDER BY updated_at DESC, id DESC",
                   (season_id,)):
        c = dict(c)
        c["driver"] = dmap.get(c["driver_id"])
        c["team"] = tmap.get(c["team_id"])
        s = standings.get(c["driver_id"])
        c["form"] = s["form"] if s else 50.0
        c["reputation"] = s["reputation"] if s else starting_reputation(conn, season_id, c["driver_id"])
        out.append(c)
    return out


# --------------------------------------------------------------------------- careers, profiles, records

def all_season_standings(conn, completed_only=False):
    out = {}
    for s in list_seasons(conn):
        out[s["id"]] = {"season": s, "drivers": driver_standings(conn, s["id"], completed_only=completed_only),
                        "teams": constructor_standings(conn, s["id"], completed_only=completed_only)}
    return out


def driver_timeline(conn, driver_id, cache=None):
    cache = cache or all_season_standings(conn)
    timeline = []
    for sid, data in cache.items():
        row = next((r for r in data["drivers"] if r["driver_id"] == driver_id), None)
        if row:
            timeline.append({"season": data["season"], **row})
    return timeline


def drivers_off_grid(conn, season_id, standings=None):
    """Everyone not in this season's table (retired, released, reserves), with their career numbers."""
    standings = standings if standings is not None else driver_standings(conn, season_id)
    shown = {r["driver_id"] for r in standings}
    cache = all_season_standings(conn)
    tmap = team_map(conn)
    out = []
    for d in drivers(conn):
        if d["id"] in shown:
            continue
        timeline = driver_timeline(conn, d["id"], cache)
        last = timeline[-1] if timeline else None
        out.append({"driver": d, "totals": career_totals(timeline), "seasons": len(timeline),
                    "last_year": last["season"]["year"] if last else None,
                    "last_team": last["team"] if last else None,
                    "reputation": starting_reputation(conn, season_id, d["id"]),
                    "status": "Retired" if not d["active"] else ("Player, no seat" if d["is_player"] else "Free agent")})
    out.sort(key=lambda r: (-r["totals"]["points"], r["driver"]["name"]))
    return out


def career_totals(timeline):
    keys = ["points", "wins", "podiums", "poles", "fastest_laps", "dotds", "starts", "dnfs"]
    totals = {k: sum(t[k] for t in timeline) for k in keys}
    totals["titles"] = sum(1 for t in timeline if t["position"] == 1 and t["points"] > 0
                           and t["season"]["status"] == C.SEASON_COMPLETE)
    totals["best_championship"] = min((t["position"] for t in timeline), default=None)
    weighted = [(t["avg_finish"], t["starts"]) for t in timeline if t["avg_finish"] and t["starts"]]
    weight = sum(w for _, w in weighted)
    totals["avg_finish"] = round(sum(a * w for a, w in weighted) / weight, 2) if weight else None
    totals["seasons"] = len(timeline)
    return totals


def hall_of_records(conn, completed_only=False):
    cache = all_season_standings(conn, completed_only)
    rows = []
    for d in drivers(conn):
        timeline = driver_timeline(conn, d["id"], cache)
        if not timeline:
            continue
        rows.append({"driver": d, **career_totals(timeline)})
    rows.sort(key=lambda r: (-r["points"], -r["wins"], r["driver"]["name"]))
    for pos, r in enumerate(rows, start=1):
        r["rank"] = pos
    return rows


def team_history(conn, team_id, completed_only=False):
    archive = []
    for sid, data in all_season_standings(conn, completed_only).items():
        row = next((t for t in data["teams"] if t["team"]["id"] == team_id), None)
        if row:
            archive.append({"season": data["season"], **row})
    totals = {k: sum(a[k] for a in archive) for k in ("points", "wins", "podiums", "fastest_laps", "dnfs")}
    totals["titles"] = sum(1 for a in archive if a["position"] == 1 and a["season"]["status"] == C.SEASON_COMPLETE
                           and a["points"] > 0)
    return archive, totals


def team_details(conn, team_id, season_id):
    """Extra constructor-profile facts: current lineup, car rating by year, everyone who raced for the team."""
    dmap = driver_map(conn)
    by_driver = {r["driver_id"]: r for r in driver_standings(conn, season_id)}
    gmap = grid_map(conn, season_id)
    current = []
    for seat in (1, 2):
        d = dmap.get(gmap.get((team_id, seat)))
        current.append({"seat": seat, "driver": d, "row": by_driver.get(d["id"]) if d else None})
    ratings = []
    for s in list_seasons(conn):
        ensure_car_ratings(conn, s["id"])
        r = _row(conn, "SELECT * FROM team_seasons WHERE season_id = ? AND team_id = ?", (s["id"], team_id))
        if r:
            ratings.append({"year": s["year"], "rating": r["car_rating"], "change": r["change"]})
    lineups = {}
    for r in _rows(conn, """SELECT s.year, r.driver_id, COUNT(*) AS starts FROM results r
                            JOIN events e ON e.id = r.event_id JOIN seasons s ON s.id = e.season_id
                            WHERE r.team_id = ? AND e.status != ? GROUP BY s.year, r.driver_id
                            ORDER BY s.year DESC, starts DESC""", (team_id, C.EVENT_NOT_RUN)):
        if dmap.get(r["driver_id"]):
            lineups.setdefault(r["year"], []).append({"driver": dmap[r["driver_id"]], "events": r["starts"]})
    moves = [dict(r) for r in _rows(conn, """SELECT * FROM news WHERE team_id = ? AND kind IN ('market', 'rumour')
                                            ORDER BY id DESC LIMIT 12""", (team_id,))]
    for m in moves:
        m["driver"] = dmap.get(m["driver_id"])
    return {"current": current, "ratings": ratings, "lineups": sorted(lineups.items(), reverse=True), "moves": moves}


# --------------------------------------------------------------------------- paddock admin (drivers, teams, calendar)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _unseat(conn, season_id, driver_id):
    """Take a driver out of their seat; an AI replacement fills it (players' seats too)."""
    gmap = grid_map(conn, season_id)
    seat = next((k for k, v in gmap.items() if v == driver_id), None)
    if not seat:
        return
    gmap[seat] = None
    gmap[seat] = best_free_ai(conn, season_id, set(gmap.values()), exclude={driver_id})
    write_grid(conn, season_id, gmap)


def _clean_name(name, label="Name", limit=60):
    name = " ".join((name or "").split())[:limit]
    if len(name) < 2:
        raise ValidationError(f"{label} is too short")
    return name


def _parse_rep(value):
    try:
        rep = round(float(value), 1)
    except (TypeError, ValueError):
        raise ValidationError("Reputation must be a number")
    if not 1 <= rep <= 100:
        raise ValidationError("Reputation runs from 1 to 100")
    return rep


def add_player_driver(conn, name, season_id):
    """A new human player: a rookie without a seat until they sign a contract."""
    return add_driver(conn, name, C.ROOKIE_REPUTATION, season_id, is_player=True)


def add_driver(conn, name, baseline_reputation, season_id, is_player=False):
    name = _clean_name(name, "Driver name")
    if _row(conn, "SELECT 1 FROM drivers WHERE lower(name) = lower(?)", (name,)):
        raise ValidationError("A driver with that name already exists")
    rep = _parse_rep(baseline_reputation)
    if is_player and len(player_drivers(conn)) >= C.MAX_PLAYERS:
        raise ValidationError(f"A league can have up to {C.MAX_PLAYERS} player drivers")
    did = conn.execute("INSERT INTO drivers(name, baseline_reputation, is_player, active) VALUES(?,?,?,1)",
                       (name, rep, int(bool(is_player)))).lastrowid
    conn.execute("INSERT OR IGNORE INTO season_driver_state VALUES(?,?,?,NULL)", (season_id, did, rep))
    if is_player:
        assign_player_colors(conn)
    return did


def assign_player_colors(conn):
    """Every human-controlled driver keeps one accent colour for the life of the league."""
    from .schema import _assign_player_colors
    _assign_player_colors(conn)


def human_driver_ids(conn):
    """Drivers controlled by a real person: marked as player drivers, or assigned to a league member."""
    ids = {r[0] for r in conn.execute("SELECT id FROM drivers WHERE is_player = 1")}
    ids |= {r[0] for r in conn.execute("SELECT driver_id FROM career_members WHERE driver_id IS NOT NULL")}
    return ids


def update_driver(conn, driver_id, season_id, name, baseline_reputation, active):
    driver = _row(conn, "SELECT * FROM drivers WHERE id = ?", (driver_id,))
    if not driver:
        raise ValidationError("Driver not found")
    name = _clean_name(name, "Driver name")
    if _row(conn, "SELECT 1 FROM drivers WHERE lower(name) = lower(?) AND id != ?", (name, driver_id)):
        raise ValidationError("Another driver already has that name")
    rep = _parse_rep(baseline_reputation)
    active = bool(active)
    conn.execute("UPDATE drivers SET name = ?, baseline_reputation = ?, active = ? WHERE id = ?",
                 (name, rep, int(active), driver_id))
    if not active and driver["active"]:
        _unseat(conn, season_id, driver_id)


def add_team(conn, name, code, color, season_id):
    name = _clean_name(name, "Team name", 40)
    code = (code or "").strip().upper()
    if not 2 <= len(code) <= 4 or not code.isalnum():
        raise ValidationError("Team codes are 2-4 letters or numbers")
    if not HEX_RE.match(color or ""):
        raise ValidationError("Pick a team colour")
    if _row(conn, "SELECT 1 FROM teams WHERE lower(name) = lower(?)", (name,)):
        raise ValidationError("A team with that name already exists")
    tid = conn.execute("INSERT INTO teams(name, abbreviation, color, active) VALUES(?,?,?,1)",
                       (name, code, color.lower())).lastrowid
    for seat in (1, 2):
        conn.execute("INSERT INTO season_grid VALUES(?,?,?,NULL)", (season_id, tid, seat))
    ensure_car_ratings(conn, season_id)
    return tid


def update_team(conn, team_id, season_id, name, code, color, active):
    team = _row(conn, "SELECT * FROM teams WHERE id = ?", (team_id,))
    if not team:
        raise ValidationError("Team not found")
    name = _clean_name(name, "Team name", 40)
    code = (code or "").strip().upper()
    if not 2 <= len(code) <= 4 or not code.isalnum():
        raise ValidationError("Team codes are 2-4 letters or numbers")
    if not HEX_RE.match(color or ""):
        raise ValidationError("Pick a team colour")
    if _row(conn, "SELECT 1 FROM teams WHERE lower(name) = lower(?) AND id != ?", (name, team_id)):
        raise ValidationError("Another team already has that name")
    active = bool(active)
    if not active and team["active"] and len(teams(conn)) <= 2:
        raise ValidationError("The grid needs at least two teams")
    conn.execute("UPDATE teams SET name = ?, abbreviation = ?, color = ?, active = ? WHERE id = ?",
                 (name, code, color.lower(), int(active), team_id))
    if not active and team["active"]:
        conn.execute("DELETE FROM season_grid WHERE season_id = ? AND team_id = ?", (season_id, team_id))
        sync_not_run_results(conn, season_id)
    elif active and not team["active"]:
        for seat in (1, 2):
            conn.execute("INSERT OR IGNORE INTO season_grid VALUES(?,?,?,NULL)", (season_id, team_id, seat))
        ensure_car_ratings(conn, season_id)


def add_event(conn, season_id, name, location, is_sprint):
    name = _clean_name(name, "Grand Prix name", 80)
    last = _row(conn, "SELECT MAX(round_number) AS n FROM events WHERE season_id = ?", (season_id,))["n"] or 0
    eid = conn.execute("INSERT INTO events(season_id, round_number, name, location, is_sprint) VALUES(?,?,?,?,?)",
                       (season_id, last + 1, name, (location or "").strip()[:80], int(bool(is_sprint)))).lastrowid
    sync_not_run_results(conn, season_id)
    return eid


def delete_event(conn, event_id):
    event = get_event(conn, event_id)
    if not event:
        raise ValidationError("Round not found")
    if event["status"] != C.EVENT_NOT_RUN:
        raise ValidationError("Only rounds that haven't been run can be removed")
    if _row(conn, "SELECT COUNT(*) AS n FROM events WHERE season_id = ?", (event["season_id"],))["n"] <= 1:
        raise ValidationError("A season needs at least one round")
    conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    later = _rows(conn, "SELECT id, round_number FROM events WHERE season_id = ? AND round_number > ? ORDER BY round_number",
                  (event["season_id"], event["round_number"]))
    for e in later:
        conn.execute("UPDATE events SET round_number = -id WHERE id = ?", (e["id"],))
    for e in later:
        conn.execute("UPDATE events SET round_number = ? WHERE id = ?", (e["round_number"] - 1, e["id"]))



# --------------------------------------------------------------------------- formula changes

def recalculate_reputation_history(conn):
    """Replay every season with the current Form/Reputation formula.

    Completed seasons normally keep the Reputation they were locked with. After a formula change
    this rebuilds the chain: season 1 starts from baseline, each later season starts from the
    previous one's recalculated final value, and every finished season is locked again.
    Returns {driver_id: (before, after)} for the current season.
    """
    seasons = list_seasons(conn)
    if not seasons:
        return {}
    current = seasons[-1]["id"]
    before = {r["driver_id"]: r["reputation"] for r in driver_standings(conn, current)}
    from . import recalc   # v2.4: one chain for everything, including pledge and team-goal rewards
    recalc.reputation_chain(conn)
    after = {r["driver_id"]: r["reputation"] for r in driver_standings(conn, current)}
    return {did: (before.get(did), after[did]) for did in after}



def driver_history(conn, driver_id):
    """How much of the record a driver appears in (to warn before deleting them)."""
    return {
        "races": _row(conn, """SELECT COUNT(*) AS n FROM results r JOIN events e ON e.id = r.event_id
                               WHERE r.driver_id = ? AND e.status != ?""", (driver_id, C.EVENT_NOT_RUN))["n"],
        "offers": _row(conn, "SELECT COUNT(*) AS n FROM offers WHERE driver_id = ?", (driver_id,))["n"],
    }


def results_transfer_preview(conn, from_id, to_id, season_id):
    """What moving from_id's results in this season onto to_id would do. Nothing is changed here."""
    dmap = driver_map(conn)
    src, dst = dmap.get(from_id), dmap.get(to_id)
    if not src or not dst:
        raise ValidationError("Choose both drivers")
    if from_id == to_id:
        raise ValidationError("Choose two different drivers")
    season = get_season(conn, season_id)
    if season["status"] == C.SEASON_COMPLETE:
        raise ValidationError("That season is finished; its Reputation is locked. Only rounds in an unfinished season can be moved.")
    rows = _rows(conn, """SELECT r.*, e.round_number, e.name AS event_name, e.is_sprint, e.status AS event_status
                          FROM results r JOIN events e ON e.id = r.event_id
                          WHERE e.season_id = ? AND r.driver_id = ? ORDER BY e.round_number""", (season_id, from_id))
    tmap = team_map(conn)
    rounds = []
    for r in rows:
        if not _result_has_data(r):
            continue
        clash = _row(conn, "SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (r["event_id"], to_id))
        pts = gp_points(r["race_position"], r["result_status"]) + \
            sprint_points(r["sprint_position"], r["sprint_status"], bool(r["is_sprint"]))
        rounds.append({"event_id": r["event_id"], "round": r["round_number"], "name": r["event_name"],
                       "team": tmap.get(r["team_id"]), "points": pts, "status": r["event_status"],
                       "result": f"P{r['race_position']}" if r["result_status"] == C.STATUS_FINISHED and r["race_position"]
                       else r["result_status"],
                       "clash": bool(clash and _result_has_data(clash))})
    seats = driver_seats(conn, season_id)
    return {"from": src, "to": dst, "season": season, "rounds": rounds,
            "points": sum(r["points"] for r in rounds if not r["clash"]),
            "clashes": [r for r in rounds if r["clash"]],
            "from_seat": seats.get(from_id), "to_seat": seats.get(to_id)}


def transfer_results(conn, from_id, to_id, season_id, event_ids, swap_seats=False):
    """Move one driver's results in the chosen rounds onto another driver (a wrong teammate, say).

    The results keep their team, so constructors' points don't change. Rounds where the other driver already
    has results are refused. Optionally swaps the two drivers' seats for the rounds still to come.
    """
    preview = results_transfer_preview(conn, from_id, to_id, season_id)
    allowed = {r["event_id"]: r for r in preview["rounds"]}
    chosen = [int(e) for e in event_ids if int(e) in allowed]
    if not chosen:
        raise ValidationError("Choose at least one round to move")
    clashes = [allowed[e] for e in chosen if allowed[e]["clash"]]
    if clashes:
        raise ValidationError(f"{preview['to']['name']} already has results in "
                              + ", ".join(f"R{c['round']}" for c in clashes) + ". Untick those rounds.")
    for event_id in chosen:
        # The target driver may have an empty placeholder row (never in a run round, but be safe).
        conn.execute("DELETE FROM results WHERE event_id = ? AND driver_id = ?", (event_id, to_id))
        conn.execute("UPDATE results SET driver_id = ? WHERE event_id = ? AND driver_id = ?", (to_id, event_id, from_id))
    if swap_seats:
        gmap = grid_map(conn, season_id)
        a = next((k for k, v in gmap.items() if v == from_id), None)
        b = next((k for k, v in gmap.items() if v == to_id), None)
        if a:
            gmap[a] = to_id
        if b:
            gmap[b] = from_id
        write_grid(conn, season_id, gmap)
        sync_not_run_results(conn, season_id)
    return {"moved": len(chosen), "points": sum(allowed[e]["points"] for e in chosen), "from": preview["from"],
            "to": preview["to"], "rounds": [allowed[e]["round"] for e in chosen]}


def delete_driver(conn, driver_id, season_id, force=False):
    """Remove a driver completely. Drivers with race results need force=True, and those results go too
    (the other drivers' positions and points are left as entered)."""
    driver = _row(conn, "SELECT * FROM drivers WHERE id = ?", (driver_id,))
    if not driver:
        raise ValidationError("Driver not found")
    history = driver_history(conn, driver_id)
    if history["races"] and not force:
        raise ValidationError(f"{driver['name']} has {history['races']} race result(s). Tick 'also delete their race "
                              "results' to remove them anyway, or untick Active to retire them instead.")
    for sid in [r["season_id"] for r in _rows(conn, "SELECT DISTINCT season_id FROM season_grid WHERE driver_id = ?",
                                              (driver_id,))]:
        gmap = grid_map(conn, sid)
        seat = next(k for k, v in gmap.items() if v == driver_id)
        gmap[seat] = None
        if sid == season_id:
            gmap[seat] = best_free_ai(conn, sid, set(gmap.values()), exclude={driver_id})
        write_grid(conn, sid, gmap)
    conn.execute("DELETE FROM results WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM offer_messages WHERE offer_id IN (SELECT id FROM offers WHERE driver_id = ?)", (driver_id,))
    conn.execute("DELETE FROM offers WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM contracts WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM season_driver_state WHERE driver_id = ?", (driver_id,))
    # The person stays in the league; they just no longer have this driver.
    conn.execute("UPDATE career_members SET driver_id = NULL, role = CASE WHEN role = 'member' THEN 'spectator' "
                 "ELSE role END WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM notifications WHERE driver_id = ?", (driver_id,))
    conn.execute("UPDATE news SET driver_id = NULL WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
    return driver["name"]
