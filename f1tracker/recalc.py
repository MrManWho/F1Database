"""Recalculating a league (v2.4).

Most numbers (standings, Form, Reputation this season, Driver Value, the AI recommendation, team goal progress)
are worked out fresh from the results every time. A few things are stored when they happen, and those are what
`recalculate` rebuilds with the current formulas:

  * weekend targets of completed rounds are judged again (with each target's own reward and penalty);
  * each team relationship's extras (press answers, weekend targets, team orders) are added up again from the
    records and kept within the usual limit, so the total always matches what's on record;
  * the team relationship ratings are reviewed again;
  * the Reputation chain across seasons: each finished season's final Reputation is worked out again and carried
    into the next season, together with the pledge and team-goal rewards that season earned.

`recalculate` is what the Race Master's "Recalculate everything" button runs, and it runs by itself when a new
version changes a formula (impacts.on_open). Anything that moves for a player driver becomes a change notice.
Nothing here changes a result.
"""

from . import constants as C
from . import services as S
from .storage import get_meta, now_iso, set_meta


def bonus_since_key(season_id, driver_id):
    return f"bonus_since_{season_id}_{driver_id}"


def contributions(conn, season_id, driver_id, team_id):
    """Everything that has added to this relationship's extras, oldest first: (when, effect, what)."""
    since = get_meta(conn, bonus_since_key(season_id, driver_id)) or ""
    seat = S.driver_seats(conn, season_id).get(driver_id)
    current_team = seat[0] if seat else None
    out = []
    for r in conn.execute("""SELECT p.created_at, p.effect, p.question, e.round_number, r.team_id AS raced_for
                             FROM press_answers p JOIN events e ON e.id = p.event_id
                             LEFT JOIN results r ON r.event_id = p.event_id AND r.driver_id = p.driver_id
                             WHERE e.season_id = ? AND p.driver_id = ?""", (season_id, driver_id)):
        if (r["raced_for"] or current_team) == team_id and r["effect"]:
            out.append((r["created_at"], r["effect"], f"R{r['round_number']} press"))
    for r in conn.execute("""SELECT t.judged_at, t.effect, e.round_number FROM weekend_targets t
                             JOIN events e ON e.id = t.event_id
                             WHERE e.season_id = ? AND t.driver_id = ? AND t.team_id = ? AND t.effect != 0""",
                          (season_id, driver_id, team_id)):
        out.append((r["judged_at"] or "", r["effect"], f"R{r['round_number']} weekend target"))
    for r in conn.execute("""SELECT created_at, text FROM team_notes WHERE season_id = ? AND driver_id = ? AND team_id = ?
                             AND (text LIKE 'You ignored the team order%' OR text LIKE 'Thanks for following the team order%')""",
                          (season_id, driver_id, team_id)):
        effect = C.TEAM_ORDER_IGNORED if r["text"].startswith("You ignored") else C.TEAM_ORDER_OBEYED
        out.append((r["created_at"], effect, "team order"))
    return sorted((c for c in out if c[0] >= since), key=lambda c: c[0])


def replay_bonus(conn, season_id, driver_id, team_id):
    """The sum of every contribution, kept within +/-RELATION_EXTRA_CAP (order never matters)."""
    total = sum(effect for _when, effect, _what in contributions(conn, season_id, driver_id, team_id))
    return round(max(-C.RELATION_EXTRA_CAP, min(C.RELATION_EXTRA_CAP, total)), 3)


def rebuild_bonus(conn, season_id, driver_ids=None):
    """Set each relationship's extras to the replayed total. Returns {driver_id: (before, after)} for those that moved."""
    moved = {}
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ?", (season_id,)).fetchall():
        if driver_ids is not None and rel["driver_id"] not in driver_ids:
            continue
        after = replay_bonus(conn, season_id, rel["driver_id"], rel["team_id"])
        if abs(after - (rel["bonus"] or 0)) > 1e-6:
            moved[rel["driver_id"]] = (rel["bonus"], after)
            conn.execute("UPDATE team_relations SET bonus = ? WHERE season_id = ? AND driver_id = ?",
                         (after, season_id, rel["driver_id"]))
    return moved


def _carried_rewards(conn, season_id):
    """{driver_id: Reputation added at the start of the next season} from pledges and team goals of season_id."""
    out = {}
    for r in conn.execute("SELECT driver_id, reward FROM team_relations WHERE season_id = ? AND outcome IS NOT NULL",
                          (season_id,)):
        if r["reward"]:     # a kept pledge's reward, or (engine 3) a missed pledge's penalty
            out[r["driver_id"]] = out.get(r["driver_id"], 0) + r["reward"]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'team_goal_choices'").fetchone():
        from . import teamgoals
        lineup = teamgoals.player_teams(conn, season_id)
        for g in conn.execute("SELECT * FROM team_goal_choices WHERE season_id = ? AND outcome IS NOT NULL", (season_id,)):
            delta = g["reward"] if g["outcome"] == "Met" else g["penalty"]
            for d in lineup.get(g["team_id"], []):
                out[d["id"]] = out.get(d["id"], 0) + delta
    from . import engine
    if engine.is_v3(conn, season_id) and not engine.mixed(conn, season_id):
        out = {d: max(-C.V3_ROLLOVER_CAP, min(C.V3_ROLLOVER_CAP, v)) for d, v in out.items()}
    return out


def reputation_chain(conn):
    """Replay every season's Reputation with the current formulas: season 1 starts from each driver's baseline,
    each later season from the previous one's final Reputation plus the pledge and team-goal rewards it earned
    (kept between 0 and 100), and every finished season is locked again."""
    seasons = S.list_seasons(conn)
    prev_final, prev_sid = None, None
    for idx, season in enumerate(seasons):
        sid = season["id"]
        if prev_final is None:
            starts = {d["id"]: d["baseline_reputation"] for d in S.drivers(conn)}
        else:
            rewards = _carried_rewards(conn, prev_sid)
            starts = {did: max(0.0, min(100.0, rep + rewards.get(did, 0))) for did, rep in prev_final.items()}
        for did, rep in starts.items():
            conn.execute("""INSERT INTO season_driver_state(season_id, driver_id, starting_reputation) VALUES(?,?,?)
                            ON CONFLICT(season_id, driver_id) DO UPDATE SET starting_reputation = excluded.starting_reputation""",
                         (sid, did, rep))
        conn.execute("UPDATE season_driver_state SET locked_reputation = NULL WHERE season_id = ?", (sid,))
        final = S.season_final_reputation(conn, sid)
        if idx < len(seasons) - 1:
            for did, rep in final.items():
                conn.execute("UPDATE season_driver_state SET locked_reputation = ? WHERE season_id = ? AND driver_id = ?",
                             (rep, sid, did))
        prev_final, prev_sid = final, sid


def recalculate(conn, history=True):
    """Rebuild everything stored from the current formulas (see the module notes). Returns a short summary."""
    from . import relations, teamlife
    sid = S.current_season_id(conn)
    summary = {"rounds": 0, "relationships": 0, "seasons": 0}
    if not sid:
        return summary
    for e in S.events(conn, sid):
        if e["status"] == C.EVENT_COMPLETE:
            teamlife.judge_targets(conn, e["id"])
            summary["rounds"] += 1
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'team_relations'").fetchone():
        summary["relationships"] = len(rebuild_bonus(conn, sid))
        relations.review(conn, sid)
    from . import engine
    if engine.is_v3(conn, sid):
        # v2.5: engine 3 rounds keep the car ranks they were judged with (only missing ones are filled in), and the
        # AI recommendation after each round is worked out again in order.
        from . import ai3, calc3
        season = S.get_season(conn, sid)
        for e in S.events(conn, sid):
            if e["status"] != C.EVENT_COMPLETE or not engine.round_v3(conn, e):
                continue
            if not conn.execute("SELECT 1 FROM round_ranks WHERE event_id = ?", (e["id"],)).fetchone():
                calc3.store_round_ranks(conn, e)
            rec = ai3.recommendation(conn, (season["year"], e["round_number"] + 1))
            conn.execute("""INSERT OR REPLACE INTO ai_recs(event_id, engine, current, recommended, direction, detail,
                            created_at) VALUES(?,?,?,?,?,?,?)""", (e["id"], 3, rec["current"], rec["recommended"],
                                                                   rec["direction"], "{}", now_iso()))
    if history:
        reputation_chain(conn)
        summary["seasons"] = len(S.list_seasons(conn))
    set_meta(conn, "recalculated_at", now_iso())
    return summary


def preview(conn, history=True):
    """What recalculate would change for each player driver, without keeping anything."""
    from . import impacts
    before = impacts.snapshot(conn)
    conn.execute("SAVEPOINT recalc_preview")
    try:
        recalculate(conn, history)
        after = impacts.snapshot(conn)
    finally:
        conn.execute("ROLLBACK TO recalc_preview")
        conn.execute("RELEASE recalc_preview")
    return impacts.diff(before, after)
