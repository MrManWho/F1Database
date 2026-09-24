"""Selectable team goals (v2.0, optional, off unless the league turns it on).

At the start of a season each team with a player driver picks one of three Constructors' Championship goals:

    Safe         a target the car should beat comfortably        small reward, no penalty
    Competitive  what the car is expected to achieve            medium reward, small penalty
    Ambitious    a stretch above the car                          big reward, bigger penalty

A goal is met by finishing at or above the target position OR scoring at least the target points, so one
unlucky tie-break doesn't decide it. Targets come from, and explain, five inputs:

    car strength rank this season (60%) and last season's Constructors' position (40%, if there was one),
    the lineup (average Reputation of the team's drivers against the grid: at most one place either way),
    calendar length and Sprint weekends (for the points target).

Rewards and penalties are Reputation for each player driver in that team, added to next season's starting
Reputation (0-100) when the Race Master starts the next season. Nothing is recalculated for seasons already
settled. The choice can be changed until the season's first round is complete; after that it is locked
(a Race Master can clear it, which is logged).
"""

from . import constants as C
from . import services as S
from .storage import get_meta, now_iso, set_meta

TIERS = {
    "safe": {"label": "Safe", "shift": 2, "points": 0.75, "reward": 1.0, "penalty": 0.0},
    "competitive": {"label": "Competitive", "shift": 0, "points": 1.0, "reward": 3.0, "penalty": -1.0},
    "ambitious": {"label": "Ambitious", "shift": -2, "points": 1.3, "reward": 6.0, "penalty": -3.0},
}

# Typical team points per Grand Prix by Constructors' position (a 10-team grid), and a Sprint's share of that.
POINTS_PER_ROUND = [38, 24, 18, 12, 8, 5, 3, 2, 1, 0.5]
SPRINT_SHARE = 0.2


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS team_goal_choices (
        season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        tier TEXT NOT NULL, target_position INTEGER NOT NULL, target_points INTEGER NOT NULL,
        reward REAL NOT NULL, penalty REAL NOT NULL, why TEXT NOT NULL DEFAULT '',
        chosen_by TEXT, chosen_at TEXT NOT NULL,
        outcome TEXT, final_position INTEGER, final_points INTEGER,
        PRIMARY KEY (season_id, team_id))""")


def enabled(conn):
    return get_meta(conn, "team_goal_choice", "0") == "1"


def set_enabled(conn, on):
    set_meta(conn, "team_goal_choice", "1" if on else "0")


def player_teams(conn, season_id):
    """{team_id: [player driver dicts]} for teams with a player driver seated this season."""
    dmap = S.driver_map(conn)
    out = {}
    for driver_id, (team_id, _slot) in S.driver_seats(conn, season_id).items():
        d = dmap.get(driver_id)
        if d and d["is_player"]:
            out.setdefault(team_id, []).append(d)
    return out


def _previous_position(conn, season_id, team_id):
    season = S.get_season(conn, season_id)
    prev = conn.execute("SELECT id FROM seasons WHERE year < ? ORDER BY year DESC LIMIT 1", (season["year"],)).fetchone()
    if not prev:
        return None
    for row in S.constructor_standings(conn, prev["id"], completed_only=True):
        if row["team"]["id"] == team_id and row["points"] > 0:
            return row["position"]
    return None


def _points_for(position, rounds, sprints, factor):
    idx = max(0, min(len(POINTS_PER_ROUND) - 1, round(position) - 1))
    per = POINTS_PER_ROUND[idx]
    return max(1, round((per * rounds + per * SPRINT_SHARE * sprints) * factor))


def options(conn, season_id, team_id):
    """The three goals for this team, with the reasons behind the numbers."""
    teams = S.teams(conn)
    n = len(teams) or 10
    ranks = S.team_strength_ranks(conn, season_id)
    rank = ranks.get(team_id, n)
    prev = _previous_position(conn, season_id, team_id)
    base = 0.6 * rank + 0.4 * prev if prev else float(rank)
    # Lineup: the team's drivers' starting Reputation against the grid average, worth up to one place.
    seats = S.driver_seats(conn, season_id)
    reps = {d: S.starting_reputation(conn, season_id, d) for d in seats}
    mine = [reps[d] for d, (t, _s) in seats.items() if t == team_id]
    field = sum(reps.values()) / len(reps) if reps else 50.0
    lineup = max(-1.0, min(1.0, -((sum(mine) / len(mine)) - field) / 15)) if mine else 0.0
    expected = max(1, min(n, round(base + lineup)))
    evs = S.events(conn, season_id)
    rounds, sprints = len(evs), sum(1 for e in evs if e["is_sprint"])
    why = [f"car strength: #{rank} of {n}"]
    why.append(f"last season: P{prev} in the Constructors'" if prev else "no previous Constructors' result")
    if abs(lineup) >= 0.25:
        why.append("lineup " + ("stronger" if lineup < 0 else "weaker") + " than the grid average")
    why.append(f"{rounds} round{'s' if rounds != 1 else ''}" + (f", {sprints} Sprint{'s' if sprints != 1 else ''}" if sprints else ""))
    out = {}
    for key, t in TIERS.items():
        wanted = expected + t["shift"]
        pos = max(1, min(n, wanted))
        pts = _points_for(pos, rounds, sprints, t["points"])
        if pos != wanted:
            # The position can't move any further (already P1, or already last): a position route would make this
            # tier no harder (or no easier) than the next, so it's judged on points alone.
            pos = 0
        text = (f"Finish P{pos} or better in the Constructors' or score {pts} points" if pos
                else f"Score {pts} points in the Constructors'")
        out[key] = {"tier": key, "label": t["label"], "target_position": pos, "target_points": pts,
                    "reward": t["reward"], "penalty": t["penalty"], "text": text}
    return {"expected": expected, "why": "; ".join(why), "options": out}


def locked(conn, season_id):
    return conn.execute("SELECT 1 FROM events WHERE season_id = ? AND status = ?",
                        (season_id, C.EVENT_COMPLETE)).fetchone() is not None


def choice(conn, season_id, team_id):
    _table(conn)
    row = conn.execute("SELECT * FROM team_goal_choices WHERE season_id = ? AND team_id = ?",
                       (season_id, team_id)).fetchone()
    return dict(row) if row else None


def choose(conn, season_id, team_id, tier, username):
    if not enabled(conn):
        raise S.ValidationError("Team goals are off in this league")
    if tier not in TIERS:
        raise S.ValidationError("Choose Safe, Competitive or Ambitious")
    if team_id not in player_teams(conn, season_id):
        raise S.ValidationError("Only teams with a player driver choose a goal")
    if locked(conn, season_id):
        raise S.ValidationError("Goals are locked once the season's first round is complete")
    _table(conn)
    info = options(conn, season_id, team_id)
    o = info["options"][tier]
    conn.execute("""INSERT INTO team_goal_choices(season_id, team_id, tier, target_position, target_points, reward,
                    penalty, why, chosen_by, chosen_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(season_id, team_id) DO UPDATE SET tier = excluded.tier,
                    target_position = excluded.target_position, target_points = excluded.target_points,
                    reward = excluded.reward, penalty = excluded.penalty, why = excluded.why,
                    chosen_by = excluded.chosen_by, chosen_at = excluded.chosen_at""",
                 (season_id, team_id, tier, o["target_position"], o["target_points"], o["reward"], o["penalty"],
                  info["why"], username, now_iso()))
    return o


def clear(conn, season_id, team_id):
    _table(conn)
    conn.execute("DELETE FROM team_goal_choices WHERE season_id = ? AND team_id = ? AND outcome IS NULL",
                 (season_id, team_id))


def _standings(conn, season_id):
    """{team_id: (position, points)} for goals. Ties count against the team (worst tied position), so teams level
    on points, including a pack of teams on zero, are never separated by name."""
    rows = S.constructor_standings(conn, season_id, completed_only=True)
    return {r["team"]["id"]: (sum(1 for o in rows if o["points"] >= r["points"]), r["points"]) for r in rows}


def _by_position(goal, position):
    return bool(goal["target_position"]) and position is not None and position <= goal["target_position"]


def describe(goal):
    pos, pts = goal["target_position"], goal["target_points"]
    return (f"Finish P{pos} or better in the Constructors' or score {pts} points" if pos
            else f"Score {pts} points in the Constructors'")


def progress(conn, season_id, standings=None):
    """Every chosen goal this season with where the team stands now: Met / On track / Behind (or the outcome)."""
    _table(conn)
    standings = standings or _standings(conn, season_id)
    evs = S.events(conn, season_id)
    done = sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE)
    frac = done / (len(evs) or 1)
    tmap = S.team_map(conn)
    out = []
    for row in conn.execute("SELECT * FROM team_goal_choices WHERE season_id = ? ORDER BY team_id", (season_id,)):
        g = dict(row)
        g["team"] = tmap.get(g["team_id"])
        g["label"] = TIERS[g["tier"]]["label"]
        g["text"] = describe(g)
        now = standings.get(g["team_id"])
        g["position"], g["points"] = now if now else (None, 0)
        if g["outcome"]:
            g["state"] = g["outcome"]
        elif done == 0:
            g["state"] = "Not started"
        elif g["points"] >= g["target_points"] or (done == len(evs) and _by_position(g, g["position"])):
            g["state"] = "Met"
        elif _by_position(g, g["position"]) or g["points"] >= g["target_points"] * frac - 0.5:
            g["state"] = "On track"
        else:
            g["state"] = "Behind"
        out.append(g)
    return out


def settle(conn, season_id):
    """End of season: record Met/Missed once per goal. Returns {driver_id: reputation change}."""
    _table(conn)
    standings = _standings(conn, season_id)
    lineup = player_teams(conn, season_id)
    changes = {}
    for g in conn.execute("SELECT * FROM team_goal_choices WHERE season_id = ?", (season_id,)).fetchall():
        if g["outcome"]:
            delta = g["reward"] if g["outcome"] == "Met" else g["penalty"]
        else:
            now = standings.get(g["team_id"])
            pos, pts = now if now else (99, 0)
            met = _by_position(g, pos) or pts >= g["target_points"]
            delta = g["reward"] if met else g["penalty"]
            conn.execute("UPDATE team_goal_choices SET outcome = ?, final_position = ?, final_points = ? "
                         "WHERE season_id = ? AND team_id = ?",
                         ("Met" if met else "Missed", pos, pts, season_id, g["team_id"]))
        for d in lineup.get(g["team_id"], []):
            changes[d["id"]] = changes.get(d["id"], 0) + delta
    return changes


def apply_rewards(conn, old_season_id, new_season_id):
    """Add each team goal's reward or penalty to next season's starting Reputation (kept within 0-100)."""
    if not enabled(conn) and not conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'team_goal_choices'").fetchone():
        return {}
    changes = settle(conn, old_season_id)
    for driver_id, delta in changes.items():
        if delta:
            conn.execute("UPDATE season_driver_state SET starting_reputation = MAX(0, MIN(100, starting_reputation + ?)) "
                         "WHERE season_id = ? AND driver_id = ?", (delta, new_season_id, driver_id))
    return changes
