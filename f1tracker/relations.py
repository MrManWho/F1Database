"""Team relationships: every seated player driver has season targets set by their contract's growth pledge.

The targets are measured against what the car should manage, so a pledge means the same at every team:
    Form target       = the car's baseline Form + the pledge's Form step
    Reputation target = starting Reputation + the pledge's Reputation step (+ the car's natural drift)

As results come in the team rates the relationship (0-100). Falling behind brings a quiet word, then a
formal warning, then "seat at risk". A driver still at risk when Silly Season opens, or at the end of the
season, is released: the team won't renew them, and without a new deal they lose the seat for next year.
"""

from . import constants as C
from . import feed
from . import services as S
from .storage import now_iso


def growth_level(index):
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    return C.GROWTH_LEVELS[max(0, min(index, len(C.GROWTH_LEVELS) - 1))]


def car_baseline_form(rank):
    """The Form a driver would score by finishing exactly where the car 'should' (qualifying and race)."""
    expected = 2 * rank - 0.5
    return round(S.clamp(50 + (12 - expected) * 3.6, 5, 95), 1)


def targets_for(conn, season_id, driver_id, team_id, growth, ranks=None):
    ranks = ranks or S.team_strength_ranks(conn, season_id)
    base = car_baseline_form(ranks.get(team_id, len(ranks) or 11))
    level = growth_level(growth)
    rep_start = S.starting_reputation(conn, season_id, driver_id)
    drift = S.clamp((base - 50) / 20, -2.5, 2.5)
    return {
        "form_base": base,
        "form_target": round(min(97.0, base + level["form"]), 1),
        "rep_start": round(rep_start, 1),
        "rep_target": round(max(rep_start - 3, rep_start + drift + level["rep"]), 1),
    }


def band(score):
    return next(name for floor, name in C.RELATION_BANDS if score >= floor)


def _contract_for(conn, year, driver_id, team_id):
    return conn.execute("""SELECT o.* FROM offers o JOIN market_windows w ON w.id = o.window_id
                           WHERE o.driver_id = ? AND o.team_id = ? AND o.status = ?
                           AND w.target_year <= ? AND w.target_year + o.years - 1 >= ?
                           ORDER BY w.target_year DESC, o.id DESC LIMIT 1""",
                        (driver_id, team_id, C.OFFER_ACCEPTED, year, year)).fetchone()


def ensure(conn, season_id):
    """Create (or refresh after a seat change) the relationship row for every seated player driver."""
    season = S.get_season(conn, season_id)
    if not season:
        return
    seats = S.driver_seats(conn, season_id)
    ranks = None
    for player in S.player_drivers(conn):
        seat = seats.get(player["id"])
        row = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ?",
                           (season_id, player["id"])).fetchone()
        if not seat:
            continue
        if row and row["team_id"] == seat[0]:
            continue
        ranks = ranks or S.team_strength_ranks(conn, season_id)
        contract = _contract_for(conn, season["year"], player["id"], seat[0])
        growth = contract["growth"] if contract and contract["growth"] is not None else 0
        t = targets_for(conn, season_id, player["id"], seat[0], growth, ranks)
        conn.execute("""INSERT INTO team_relations(season_id, driver_id, team_id, offer_id, growth, form_base,
                        form_target, rep_start, rep_target, score, status, warning_level, released, updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,?)
                        ON CONFLICT(season_id, driver_id) DO UPDATE SET team_id = excluded.team_id,
                        offer_id = excluded.offer_id, growth = excluded.growth, form_base = excluded.form_base,
                        form_target = excluded.form_target, rep_start = excluded.rep_start,
                        rep_target = excluded.rep_target, score = excluded.score, status = excluded.status,
                        warning_level = 0, released = 0, updated_at = excluded.updated_at""",
                     (season_id, player["id"], seat[0], contract["id"] if contract else None, growth,
                      t["form_base"], t["form_target"], t["rep_start"], t["rep_target"], C.RELATION_START,
                      band(C.RELATION_START), now_iso()))


def assess(conn, season_id, driver_id, standings=None):
    """The live picture: targets, progress and the team's rating. None if the driver has no seat."""
    rel = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ?",
                       (season_id, driver_id)).fetchone()
    if not rel:
        return None
    rel = dict(rel)
    evs = S.events(conn, season_id)
    total = len(evs) or 1
    done = sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE)
    frac = done / total
    standings = standings if standings is not None else {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    row = standings.get(driver_id)
    has = bool(row and row["has_results"])
    form = row["form"] if has else rel["form_base"]
    rep = row["reputation"] if row else rel["rep_start"]
    rep_expected = rel["rep_start"] + (rel["rep_target"] - rel["rep_start"]) * frac
    from .market import head_to_head  # local import: market imports this module
    h2h = head_to_head(conn, season_id, driver_id)
    h2h_bonus = S.clamp((h2h["race_won"] / h2h["race_total"] - 0.5) * 10, -5, 5) if h2h["race_total"] >= 2 else 0.0
    form_gap = form - rel["form_target"]
    rep_gap = rep - rep_expected
    confidence = min(1.0, done / max(3.0, total * 0.3))
    raw = form_gap * 1.2 + rep_gap * 3 + h2h_bonus
    score = round(S.clamp(C.RELATION_START + confidence * raw, 0, 100), 1)
    status = "Released" if rel["released"] else band(score)
    return {**rel, "team": S.team_map(conn).get(rel["team_id"]), "level": growth_level(rel["growth"]),
            "form": form, "rep": rep, "rep_expected": round(rep_expected, 1), "form_gap": round(form_gap, 1),
            "rep_gap": round(rep_gap, 1), "h2h": h2h, "score": score, "status": status, "done": done,
            "total": total, "confidence": confidence, "live_status": band(score)}


WARNINGS = {
    1: ("concerned", "{team} have had a quiet word: results are behind what you promised. They expect a response."),
    2: ("warning", "Formal warning from {team}: you're well short of your targets. Things need to change quickly."),
    3: ("danger", "{team} are openly questioning your future. Your seat is at risk if this carries on."),
}
LEVEL_FOR = {"Concerned": 1, "Unhappy": 2, "Seat at risk": 3}


def note(conn, season_id, driver_id, team_id, tone, text, notify=True):
    conn.execute("INSERT INTO team_notes(season_id, driver_id, team_id, tone, text, created_at) VALUES(?,?,?,?,?,?)",
                 (season_id, driver_id, team_id, tone, text, now_iso()))
    if notify:
        feed.notify(conn, driver_id, text, "team-standing")


def review(conn, season_id):
    """After a completed round: store the latest rating and have teams react to big changes."""
    ensure(conn, season_id)
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    for rel in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?", (season_id,)).fetchall():
        a = assess(conn, season_id, rel["driver_id"], standings)
        if not a:
            continue
        team = a["team"]["name"] if a["team"] else "Your team"
        level = LEVEL_FOR.get(a["live_status"], 0)
        new_level = a["warning_level"]
        if a["done"] >= 3 and not a["released"]:
            if level > a["warning_level"]:
                tone, text = WARNINGS[level]
                note(conn, season_id, a["driver_id"], a["team_id"], tone, text.format(team=team))
                new_level = level
            elif a["warning_level"] >= 2 and a["live_status"] in ("Happy", "Delighted"):
                note(conn, season_id, a["driver_id"], a["team_id"], "good",
                     f"{team} are pleased with the turnaround. The warning is off the table.")
                new_level = 0
            elif a["warning_level"] == 0 and a["live_status"] == "Delighted" and a["done"] >= 4 and not \
                    conn.execute("SELECT 1 FROM team_notes WHERE season_id = ? AND driver_id = ? AND tone = 'good'",
                                 (season_id, a["driver_id"])).fetchone():
                note(conn, season_id, a["driver_id"], a["team_id"], "good",
                     f"{team} are delighted: you're beating every target they set.")
        conn.execute("UPDATE team_relations SET score = ?, status = ?, warning_level = ?, updated_at = ? "
                     "WHERE season_id = ? AND driver_id = ?",
                     (a["score"], a["status"], new_level, now_iso(), season_id, a["driver_id"]))


def decide_releases(conn, season_id, final=False):
    """Teams drop drivers who are still at risk (at Silly Season, or at the end of the season)."""
    ensure(conn, season_id)
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    released = []
    for rel in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ? AND released = 0",
                            (season_id,)).fetchall():
        a = assess(conn, season_id, rel["driver_id"], standings)
        if not a or a["done"] < 3 or a["live_status"] != "Seat at risk":
            continue
        if not final and a["confidence"] < 1:
            continue
        team = a["team"]["name"] if a["team"] else "Your team"
        conn.execute("UPDATE team_relations SET released = 1, status = 'Released', updated_at = ? "
                     "WHERE season_id = ? AND driver_id = ?", (now_iso(), season_id, a["driver_id"]))
        note(conn, season_id, a["driver_id"], a["team_id"], "danger",
             f"{team} have decided to let you go at the end of the season. You'll need a new team.")
        driver = S.driver_map(conn)[a["driver_id"]]["name"]
        feed.post(conn, season_id, "market", f"{team} to drop {driver}",
                  f"{driver} fell well short of the targets agreed with {team}.", "news",
                  driver_id=a["driver_id"], team_id=a["team_id"])
        released.append(a["driver_id"])
    return released


def is_released(conn, season_id, driver_id):
    return bool(conn.execute("SELECT 1 FROM team_relations WHERE season_id = ? AND driver_id = ? AND released = 1",
                             (season_id, driver_id)).fetchone())


def interest_bonus(conn, season_id, driver_id, team_id):
    """How a driver's current team feels when a window opens: -10 (fed up) to +7 (delighted)."""
    rel = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ? AND team_id = ?",
                       (season_id, driver_id, team_id)).fetchone()
    if not rel:
        return 3.0
    if rel["released"]:
        return None
    return round(S.clamp((rel["score"] - C.RELATION_START) / 6 + 3, -10, 7), 1)


def notes(conn, season_id, driver_id):
    return [dict(r) for r in conn.execute("SELECT * FROM team_notes WHERE season_id = ? AND driver_id = ? "
                                          "ORDER BY id DESC", (season_id, driver_id))]
