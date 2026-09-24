"""Team relationships: every seated player driver has season targets set by their contract's growth pledge.

A pledge is a promise about average finishing position, measured against the car so it means the same at
every team:
    expected finish = where the car should finish (2 x car rank - 0.5: P1.5 in the fastest car, P21.5 in the slowest)
    pledged finish  = expected finish - share x (expected finish - 1)
Each pledge closes the same share of the gap to P1 in any car (Steady 0, Solid 12%, Strong 25%, Breakout 40%),
so the fastest car can't meet everything by default and the slowest car can still keep a big promise.
A DNF or DSQ counts as last place; from round 5 the single worst weekend is dropped. Form and Reputation
are still shown, but they aren't the test: they depend too much on the car (points, wins) to be fair.
Keeping the pledge at season end adds a little Reputation to next season's start (see C.GROWTH_LEVELS).

As results come in the team rates the relationship (0-100). Falling behind brings a quiet word, then a
formal warning, then "seat at risk". A driver still at risk when Silly Season opens, or at the end of the
season, is released: the team won't renew them, and without a new deal they lose the seat for next year.

Every seated player must have chosen a pledge (pledged = 1). Contracts from before pledges existed, and
seats with no contract, start unpledged, and the app asks the driver to choose before anything else.
After three rounds the targets are re-based on how the car is really performing (AI drivers' points).
The team also sets season goals, and press answers and team orders add a small bonus (+/-15).
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


def expected_finish(rank):
    return 2 * rank - 0.5


def pledged_finish(rank, growth):
    expected = expected_finish(rank)
    return round(expected - growth_level(growth)["share"] * (expected - 1), 1)


def pace_unit(finish_base):
    """One step of pledge performance in places: a share of the car's headroom, never under 0.6 places."""
    return max(0.6, C.PLEDGE_UNIT_SHARE * ((finish_base or 1.5) - 1))


def targets_for(conn, season_id, driver_id, team_id, growth, ranks=None):
    ranks = ranks or S.team_strength_ranks(conn, season_id)
    rank = ranks.get(team_id, len(ranks) or 11)
    base = car_baseline_form(rank)
    rep_start = S.starting_reputation(conn, season_id, driver_id)
    return {
        "rank": rank,
        "finish_base": expected_finish(rank),
        "finish_target": pledged_finish(rank, growth),
        "reward": growth_level(growth)["reward"],
        # Kept for older screens and saves; not used to judge the pledge.
        "form_base": base, "form_target": base,
        "rep_start": round(rep_start, 1), "rep_target": round(rep_start, 1),
    }


def pace(conn, season_id, driver_id, team_id=None):
    """Average finishing position in completed rounds (DNF/DSQ = last; worst weekend dropped from round 5)."""
    field = max(2, 2 * len(S.teams(conn)))
    sql = """SELECT r.race_position, r.result_status FROM results r JOIN events e ON e.id = r.event_id
             WHERE e.season_id = ? AND e.status = ? AND r.driver_id = ?"""
    params = [season_id, C.EVENT_COMPLETE, driver_id]
    if team_id is not None:
        sql += " AND r.team_id = ?"
        params.append(team_id)
    finishes = []
    for r in conn.execute(sql, params):
        if r["result_status"] == C.STATUS_FINISHED and r["race_position"]:
            finishes.append(r["race_position"])
        elif r["result_status"] in ("DNF", "DSQ"):
            finishes.append(field)
    counted = sorted(finishes)[:-1] if len(finishes) >= C.PLEDGE_DROP_AFTER else finishes
    return {"average": round(sum(counted) / len(counted), 2) if counted else None, "rounds": len(finishes),
            "dropped": len(finishes) - len(counted), "field": field}


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
            if row["finish_target"] is None:  # relationships from before v1.17
                ranks = ranks or S.team_strength_ranks(conn, season_id)
                t = targets_for(conn, season_id, player["id"], seat[0], row["growth"], ranks)
                conn.execute("UPDATE team_relations SET finish_base = ?, finish_target = ? WHERE season_id = ? "
                             "AND driver_id = ?", (t["finish_base"], t["finish_target"], season_id, player["id"]))
                if row["pledged"]:
                    note(conn, season_id, player["id"], seat[0], "good",
                         f"Pledges are now judged on average finish against the car. Your "
                         f"{growth_level(row['growth'])['name']} pledge means averaging P{t['finish_target']:.1f} "
                         f"or better (the car's expected finish is P{t['finish_base']:.1f}).", notify=False)
            if not conn.execute("SELECT 1 FROM team_goals WHERE season_id = ? AND driver_id = ?",
                                (season_id, player["id"])).fetchone():  # rows from before goals existed
                set_goals(conn, season_id, player["id"], seat[0], _role(conn, row))
            continue
        ranks = ranks or S.team_strength_ranks(conn, season_id)
        contract = _contract_for(conn, season["year"], player["id"], seat[0])
        pledged = bool(contract and contract["growth"] is not None)
        growth = contract["growth"] if pledged else 0
        t = targets_for(conn, season_id, player["id"], seat[0], growth, ranks)
        conn.execute("""INSERT INTO team_relations(season_id, driver_id, team_id, offer_id, growth, form_base,
                        form_target, rep_start, rep_target, score, status, warning_level, released, updated_at,
                        pledged, rebased, bonus, finish_base, finish_target, outcome, reward)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,0,0,?,?,NULL,0)
                        ON CONFLICT(season_id, driver_id) DO UPDATE SET team_id = excluded.team_id,
                        offer_id = excluded.offer_id, growth = excluded.growth, form_base = excluded.form_base,
                        form_target = excluded.form_target, rep_start = excluded.rep_start,
                        rep_target = excluded.rep_target, score = excluded.score, status = excluded.status,
                        warning_level = 0, released = 0, updated_at = excluded.updated_at,
                        pledged = excluded.pledged, rebased = 0, bonus = 0, finish_base = excluded.finish_base,
                        finish_target = excluded.finish_target, outcome = NULL, reward = 0""",
                     (season_id, player["id"], seat[0], contract["id"] if contract else None, growth,
                      t["form_base"], t["form_target"], t["rep_start"], t["rep_target"], C.RELATION_START,
                      band(C.RELATION_START), now_iso(), int(pledged), t["finish_base"], t["finish_target"]))
        # v2.4: the extras (press, targets, orders) start again from here; recalculating replays only what's after.
        from .storage import set_meta as _set_meta
        _set_meta(conn, f"bonus_since_{season_id}_{player['id']}", now_iso())
        set_goals(conn, season_id, player["id"], seat[0], contract["role"] if contract else "Equal Status", ranks,
                  replace=True)
    rebase(conn, season_id)  # leagues already past round 3 get their targets re-based straight away


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
    from .market import head_to_head  # local import: market imports this module
    h2h = head_to_head(conn, season_id, driver_id)
    h2h_bonus = S.clamp((h2h["race_won"] / h2h["race_total"] - 0.5) * 10, -5, 5) if h2h["race_total"] >= 2 else 0.0
    if rel["finish_target"] is None:
        t = targets_for(conn, season_id, driver_id, rel["team_id"], rel["growth"])
        rel["finish_base"], rel["finish_target"] = t["finish_base"], t["finish_target"]
    p = pace(conn, season_id, driver_id, rel["team_id"])
    # Positive = finishing ahead of the pledge. Measured in steps of the car's headroom, so it weighs the same
    # at every team.
    pace_gap = (rel["finish_target"] - p["average"]) if p["average"] is not None else 0.0
    pace_part = S.clamp(pace_gap / pace_unit(rel["finish_base"]) * 6, -30, 30)
    confidence = min(1.0, done / max(3.0, total * 0.3))
    goals = goal_progress(conn, season_id, driver_id, row, h2h, done, total)
    goal_part = sum(C.GOAL_WEIGHT if g["state"] in ("Met", "On track") else -C.GOAL_WEIGHT for g in goals)
    raw = pace_part + h2h_bonus + goal_part
    score = round(S.clamp(C.RELATION_START + confidence * raw + (rel["bonus"] or 0), 0, 100), 1)
    status = "Released" if rel["released"] else band(score)
    return {**rel, "team": S.team_map(conn).get(rel["team_id"]), "level": growth_level(rel["growth"]),
            "form": form, "rep": rep, "rep_change": round(rep - rel["rep_start"], 1), "pace": p["average"],
            "pace_rounds": p["rounds"], "pace_dropped": p["dropped"], "field": p["field"], "pace_gap": round(pace_gap, 2),
            "on_pledge": p["average"] is not None and p["average"] <= rel["finish_target"] + 1e-9,
            "reward_if_kept": growth_level(rel["growth"])["reward"], "h2h": h2h, "score": score, "status": status, "done": done,
            "total": total, "confidence": confidence, "live_status": band(score), "goals": goals,
            "role": _role(conn, rel)}


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
        feed.notify(conn, driver_id, text, "team-standing", category="career")


def review(conn, season_id):
    """After a completed round: store the latest rating and have teams react to big changes."""
    ensure(conn, season_id)
    rebase(conn, season_id)
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


# --------------------------------------------------------------------------- pledges

def needs_pledge(conn, season_id, driver_id):
    row = conn.execute("SELECT pledged, released FROM team_relations WHERE season_id = ? AND driver_id = ?",
                       (season_id, driver_id)).fetchone()
    return bool(row and not row["pledged"] and not row["released"])


def set_pledge(conn, season_id, driver_id, growth):
    """The driver chooses (or re-chooses) their pledge for this season; targets are worked out again."""
    try:
        growth = int(growth)
    except (TypeError, ValueError):
        raise S.ValidationError("Choose a growth pledge")
    if not 0 <= growth < len(C.GROWTH_LEVELS):
        raise S.ValidationError("Choose a growth pledge")
    level = C.GROWTH_LEVELS[growth]
    rel = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ?",
                       (season_id, driver_id)).fetchone()
    if not rel:
        raise S.ValidationError("You don't have a race seat this season")
    t = targets_for(conn, season_id, driver_id, rel["team_id"], growth)
    conn.execute("""UPDATE team_relations SET growth = ?, form_base = ?, form_target = ?, rep_target = ?,
                    finish_base = ?, finish_target = ?, pledged = 1, updated_at = ? WHERE season_id = ? AND driver_id = ?""",
                 (growth, t["form_base"], t["form_target"], t["rep_target"], t["finish_base"], t["finish_target"],
                  now_iso(), season_id, driver_id))
    if rel["offer_id"]:
        conn.execute("UPDATE offers SET growth = ? WHERE id = ?", (growth, rel["offer_id"]))
    team = S.team_map(conn)[rel["team_id"]]["name"]
    note(conn, season_id, driver_id, rel["team_id"], "good",
         f"You've pledged a {level['name']} season to {team}: an average finish of P{t['finish_target']:.1f} or "
         f"better (the car's expected finish is P{t['finish_base']:.1f}). Keep it and you start next season with "
         f"+{level['reward']} Reputation.", notify=False)
    return t


def request_pledge(conn, season_id, driver_id):
    """Race Master: make a driver choose their pledge again before they carry on."""
    rel = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ?",
                       (season_id, driver_id)).fetchone()
    if not rel:
        raise S.ValidationError("That driver has no race seat this season")
    conn.execute("UPDATE team_relations SET pledged = 0 WHERE season_id = ? AND driver_id = ?", (season_id, driver_id))
    feed.notify(conn, driver_id, "Your team wants your growth pledge for this season. Choose it to carry on.", "pledge")


def rebase(conn, season_id):
    """After three rounds, reset the Form baseline to the car's real pace (from AI drivers' points)."""
    evs = S.events(conn, season_id)
    if sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE) < 3:
        return
    ranks = None
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND rebased = 0",
                            (season_id,)).fetchall():
        ranks = ranks or S.team_strength_ranks(conn, season_id)
        rank = ranks.get(rel["team_id"], len(ranks))
        base = car_baseline_form(rank)
        finish_base, target = expected_finish(rank), pledged_finish(rank, rel["growth"])
        conn.execute("UPDATE team_relations SET rebased = 1, form_base = ?, form_target = ?, finish_base = ?, "
                     "finish_target = ? WHERE season_id = ? AND driver_id = ?",
                     (base, base, finish_base, target, season_id, rel["driver_id"]))
        old = rel["finish_target"]
        if old is not None and abs(target - old) >= 0.5:
            team = S.team_map(conn)[rel["team_id"]]["name"]
            quicker = target < old
            note(conn, season_id, rel["driver_id"], rel["team_id"], "concerned" if quicker else "good",
                 f"After three rounds {team} have re-set your targets to match the car's real pace. It's "
                 f"{'quicker' if quicker else 'slower'} than expected, so your pledge now means averaging "
                 f"P{target:.1f} or better (was P{old:.1f}).")
        set_goals(conn, season_id, rel["driver_id"], rel["team_id"], _role(conn, rel), ranks, replace=True)


def add_bonus(conn, season_id, driver_id, delta=None):
    """The relationship extras (press answers, weekend targets, team orders) changed for this driver: work the
    total out again from the records (v2.4). It's the plain sum of every one since the relationship started, kept
    within +/-RELATION_EXTRA_CAP, so it never depends on the order things happened and a recalculation always
    agrees with it. Callers save the record first; `delta` is kept for readability only."""
    from . import recalc
    recalc.rebuild_bonus(conn, season_id, [driver_id])


# --------------------------------------------------------------------------- season goals

def _role(conn, rel):
    if rel["offer_id"]:
        row = conn.execute("SELECT role FROM offers WHERE id = ?", (rel["offer_id"],)).fetchone()
        if row:
            return row["role"]
    return "Equal Status"


def set_goals(conn, season_id, driver_id, team_id, role, ranks=None, replace=False):
    """The team's goals for the season, pitched at what the car can do."""
    if not replace and conn.execute("SELECT 1 FROM team_goals WHERE season_id = ? AND driver_id = ?",
                                    (season_id, driver_id)).fetchone():
        return
    conn.execute("DELETE FROM team_goals WHERE season_id = ? AND driver_id = ?", (season_id, driver_id))
    ranks = ranks or S.team_strength_ranks(conn, season_id)
    rank = ranks.get(team_id, len(ranks) or 11)
    total = len(S.events(conn, season_id)) or 1
    share = 0.85 if rank <= 2 else 0.7 if rank <= 4 else 0.5 if rank <= 6 else 0.3 if rank <= 8 else 0.15
    points = max(1, round(total * share))
    wdc = min(20, 2 * rank + 1)
    goals = [("points", points, f"Score points in {points} race{'s' if points != 1 else ''}"),
             ("championship", wdc, f"Finish P{wdc} or better in the championship")]
    if role == "No. 1":
        goals.append(("teammate", 1, "Beat your teammate in most races (you're the No. 1)"))
    elif role == "Equal Status":
        goals.append(("teammate", 1, "Beat your teammate in at least half the races"))
    for kind, target, label in goals:
        conn.execute("INSERT INTO team_goals(season_id, driver_id, kind, target, label) VALUES(?,?,?,?,?)",
                     (season_id, driver_id, kind, target, label))


def goal_progress(conn, season_id, driver_id, row, h2h, done, total):
    frac = done / (total or 1)
    out = []
    for g in conn.execute("SELECT * FROM team_goals WHERE season_id = ? AND driver_id = ? ORDER BY id",
                          (season_id, driver_id)).fetchall():
        g = dict(g)
        if g["kind"] == "points":
            count = conn.execute("""SELECT COUNT(*) FROM results r JOIN events e ON e.id = r.event_id
                                    WHERE e.season_id = ? AND r.driver_id = ? AND e.status = ?
                                    AND r.result_status = ? AND r.race_position <= 10""",
                                 (season_id, driver_id, C.EVENT_COMPLETE, C.STATUS_FINISHED)).fetchone()[0]
            g["now"] = f"{count} of {g['target']}"
            g["state"] = "Met" if count >= g["target"] else \
                "On track" if count >= g["target"] * frac - 0.5 else "Behind"
        elif g["kind"] == "championship":
            pos = row["position"] if row and row["has_results"] else None
            g["now"] = f"P{pos}" if pos else "—"
            g["state"] = "On track" if not pos or pos <= g["target"] else "Behind"
            if pos and pos <= g["target"] and done == total:
                g["state"] = "Met"
        else:
            won, raced = h2h["race_won"], h2h["race_total"]
            g["now"] = f"{won}–{raced - won}"
            g["state"] = "On track" if raced == 0 or won * 2 >= raced else "Behind"
            if raced and done == total and won * 2 >= raced:
                g["state"] = "Met"
        out.append(g)
    return out


def settle(conn, season_id):
    """End of season: record whether each pledge was kept. Returns {driver_id: reward} for kept pledges."""
    ensure(conn, season_id)
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    rewards = {}
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ?", (season_id,)).fetchall():
        if rel["outcome"]:
            if rel["outcome"] == "Kept":
                rewards[rel["driver_id"]] = rel["reward"]
            continue
        a = assess(conn, season_id, rel["driver_id"], standings)
        if not a or not a["pace_rounds"] or not rel["pledged"]:
            continue
        kept = a["on_pledge"]
        reward = a["reward_if_kept"] if kept else 0.0
        conn.execute("UPDATE team_relations SET outcome = ?, reward = ? WHERE season_id = ? AND driver_id = ?",
                     ("Kept" if kept else "Missed", reward, season_id, rel["driver_id"]))
        team = a["team"]["name"] if a["team"] else "Your team"
        level = a["level"]["name"]
        if kept:
            rewards[rel["driver_id"]] = reward
            note(conn, season_id, rel["driver_id"], rel["team_id"], "good",
                 f"Pledge kept: you averaged P{a['pace']:.1f} against a {level} target of P{a['finish_target']:.1f}. "
                 f"{team} are telling everyone: +{reward} Reputation to start next season.")
        else:
            note(conn, season_id, rel["driver_id"], rel["team_id"], "concerned",
                 f"Pledge missed: you averaged P{a['pace']:.1f} against a {level} target of P{a['finish_target']:.1f}.")
    return rewards


def apply_rewards(conn, old_season_id, new_season_id):
    """Add kept-pledge Reputation to next season's starting Reputation (capped at 100)."""
    rewards = settle(conn, old_season_id)
    for driver_id, reward in rewards.items():
        conn.execute("UPDATE season_driver_state SET starting_reputation = MIN(100, starting_reputation + ?) "
                     "WHERE season_id = ? AND driver_id = ?", (reward, new_season_id, driver_id))
    return rewards
