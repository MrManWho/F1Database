"""The 2.5 Calculation Update for leagues that existed before 2.5 (engine 2 -> engine 3).

Nothing happens by itself. The Race Master chooses, on a screen only they see:

  A. "full"   - recalculate the active season from round 1 with Calculation Version 3. A complete backup is written
                first, a preview (worked out and thrown away, nothing saved) shows every driver's before and after,
                and it only happens after an explicit confirmation. Results are never changed.
  B. "future" - keep everything calculated so far; Version 3 applies from the next round. The values at the cutoff
                are frozen and the new numbers blend in over the next rounds (engine.blend_weight), so choosing this
                changes nothing straight away. The next season is fully Version 3.
  C. "later"  - keep Version 2 for now; the Race Master is reminded (dismissible). Drivers never see the choice.

Every migration is stored in calc_migrations (option, versions, cutoff, before/after values, who approved it, the
backup to roll back to) and every affected player driver gets one personalised notice to agree to.
"""

import json

from . import constants as C
from . import engine as E
from . import impacts
from . import services as S
from .storage import now_iso, set_meta

WHY_FULL = ("Your Race Master moved this league to Calculation Version 3 (Paddock Legacy 2.5) and recalculated this "
            "season from round 1 with the new fairness, performance, relationship, market and AI formulas. Race "
            "results didn't change; the numbers worked out from them did. Only this season is affected: earlier "
            "seasons stay as they were.")


def _completed(conn, sid):
    return [e for e in S.events(conn, sid) if e["status"] == C.EVENT_COMPLETE]


# --------------------------------------------------------------------------- applying

def _mark_seasons(conn, active_id, engine_for_active, cutoff_round=0, frozen=None, migration_id=None):
    """Every earlier season stays on engine 2 (explicitly), the active one takes the new engine."""
    for season in S.list_seasons(conn):
        if season["id"] == active_id:
            E.set_season(conn, season["id"], engine_for_active, cutoff_round, frozen, migration_id)
        elif not conn.execute("SELECT 1 FROM season_calc WHERE season_id = ?", (season["id"],)).fetchone():
            E.set_season(conn, season["id"], C.ENGINE_LEGACY)


def rebuild_active_season(conn, sid):
    """Engine 3 from round 1 of the active season: stored car ranks, season goals, weekend targets, team goal
    rewards, relationship reviews and the AI recommendation after each round. Nothing in the results changes."""
    from . import ai3, calc3, relations, teamlife
    conn.execute("DELETE FROM round_ranks WHERE event_id IN (SELECT id FROM events WHERE season_id = ?)", (sid,))
    done = _completed(conn, sid)
    for e in done:
        calc3.store_round_ranks(conn, e)
    # Season goals: set from the car ranks at the designated reset (after round 3), else as the season started.
    relations.ensure(conn, sid)
    reset_round = 4 if len(done) >= 3 else 1
    ranks = calc3.effective_ranks(conn, sid, reset_round)
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ?", (sid,)).fetchall():
        relations.set_goals(conn, sid, rel["driver_id"], rel["team_id"], relations._role(conn, rel), ranks, replace=True)
    # Team goals chosen this season keep their target; their reward and penalty follow the Version 3 table.
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'team_goal_choices'").fetchone():
        for g in conn.execute("SELECT * FROM team_goal_choices WHERE season_id = ?", (sid,)).fetchall():
            reward, penalty = C.V3_TEAM_GOALS.get(g["tier"], (g["reward"], g["penalty"]))
            conn.execute("UPDATE team_goal_choices SET reward = ?, penalty = ? WHERE season_id = ? AND team_id = ?",
                         (reward, penalty, sid, g["team_id"]))
    for e in done:
        teamlife.judge_targets(conn, e["id"])
    # Team orders already judged from positions under Version 2 need a Race Master ruling under Version 3.
    conn.execute("""UPDATE team_orders SET status = 'Awaiting ruling' WHERE status IN ('Obeyed', 'Ignored')
                    AND ruled_by IS NULL AND event_id IN (SELECT id FROM events WHERE season_id = ?)""", (sid,))
    relations.review(conn, sid)
    conn.execute("DELETE FROM ai_recs WHERE event_id IN (SELECT id FROM events WHERE season_id = ?)", (sid,))
    season = S.get_season(conn, sid)
    for e in done:
        rec = ai3.recommendation(conn, (season["year"], e["round_number"] + 1))
        conn.execute("""INSERT OR REPLACE INTO ai_recs(event_id, engine, current, recommended, direction, detail, created_at)
                        VALUES(?,?,?,?,?,?,?)""", (e["id"], 3, rec["current"], rec["recommended"], rec["direction"],
                                                   "{}", now_iso()))
    return len(done)


def _review_items(conn, sid):
    """Drivers the recalculation puts at dismissal level: a Race Master review, never an automatic dismissal."""
    from . import ultimatums
    out = []
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND warning_level >= 3 AND released = 0",
                            (sid,)).fetchall():
        if not ultimatums.active(conn, sid, rel["driver_id"]):
            out.append(rel["driver_id"])
    return out


def apply_full(conn, username, backup=None):
    sid = S.current_season_id(conn)
    old = E.season_engine(conn, sid)
    before = impacts.snapshot(conn, sid)
    E.set_league(conn, C.ENGINE_CURRENT, "full")
    _mark_seasons(conn, sid, C.ENGINE_CURRENT)
    rebuild_active_season(conn, sid)
    after = impacts.snapshot(conn, sid)
    mid = conn.execute("""INSERT INTO calc_migrations(season_id, option, old_engine, new_engine, cutoff_round, before,
                          after, backup, approved_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (sid, "full", old, C.ENGINE_CURRENT, 0, json.dumps(before), json.dumps(after), backup, username,
                        now_iso())).lastrowid
    conn.execute("UPDATE season_calc SET migration_id = ? WHERE season_id = ?", (mid, sid))
    notices = _notify(conn, mid, before, after, WHY_FULL)
    from . import feed
    dmap = S.driver_map(conn)
    for did in _review_items(conn, sid):
        feed.notify(conn, None, f"Calculation Update: {dmap[did]['name']} is now at \"Seat at risk\". Nothing happens "
                    "automatically; review it on Team management.", "team-management", category="admin")
    impacts.refresh(conn)
    return {"migration_id": mid, "notices": notices}


def freeze_values(conn, sid):
    """Everything Future-only keeps as it stands at the cutoff."""
    from . import market, relations, teamgoals
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, sid)}
    ranks = S.team_strength_ranks(conn, sid)
    drivers = {}
    for did, row in standings.items():
        v = market.driver_value(conn, sid, did, standings, ranks)
        d = {"form": row["form"], "reputation": row["reputation"], "value": v["value"]}
        a = relations.assess(conn, sid, did, standings) if row["driver"]["is_player"] else None
        if a:
            d.update(relationship=a["score"], warning=a["warning_level"], goals=[
                {"label": g["label"], "state": g["state"]} for g in a["goals"]])
        if row["driver"]["is_player"] and row.get("seated"):
            _me, teams = market.team_interest(conn, sid, did)
            d["interest"] = {str(t["team"]["id"]): t["interest"] for t in teams}
        drivers[str(did)] = d
    rec = S.difficulty_recommendation(conn)
    team_goals = []
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'team_goal_choices'").fetchone():
        team_goals = [{k: g[k] for k in ("team_id", "tier", "target_points", "target_position")}
                      for g in teamgoals.progress(conn, sid)]
    pledges = [dict(r) for r in conn.execute("SELECT driver_id, growth, finish_target FROM team_relations WHERE season_id = ?",
                                            (sid,))]
    return {"drivers": drivers, "ranks": {str(t): r for t, r in ranks.items()},
            "ai": {"recommended": rec.get("recommended"), "direction": rec.get("direction"), "current": rec.get("current")},
            "team_goals": team_goals, "pledges": pledges, "frozen_at": now_iso()}


def apply_future(conn, username, backup=None):
    sid = S.current_season_id(conn)
    old = E.season_engine(conn, sid)
    done = _completed(conn, sid)
    cut = max((e["round_number"] for e in done), default=0)
    before = impacts.snapshot(conn, sid)
    frozen = freeze_values(conn, sid)
    E.set_league(conn, C.ENGINE_CURRENT, "future")
    _mark_seasons(conn, sid, C.ENGINE_CURRENT, cut, frozen)
    # Rounds already played keep the car ranks they were judged with under Version 2.
    for e in done:
        conn.execute("DELETE FROM round_ranks WHERE event_id = ?", (e["id"],))
        for t, r in frozen["ranks"].items():
            conn.execute("INSERT INTO round_ranks(event_id, team_id, rank, source) VALUES(?,?,?,'frozen')",
                         (e["id"], int(t), r))
    after = impacts.snapshot(conn, sid)
    mid = conn.execute("""INSERT INTO calc_migrations(season_id, option, old_engine, new_engine, cutoff_round, before,
                          after, backup, approved_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (sid, "future", old, C.ENGINE_CURRENT, cut, json.dumps(before), json.dumps(after), backup,
                        username, now_iso())).lastrowid
    conn.execute("UPDATE season_calc SET migration_id = ? WHERE season_id = ?", (mid, sid))
    impacts.refresh(conn)
    return {"migration_id": mid, "cutoff": cut}


def decide_later(conn, username):
    E.set_league(conn, C.ENGINE_LEGACY, "later")
    set_meta(conn, "calc_choice_later_at", now_iso())
    set_meta(conn, "calc_choice_later_by", username)


# --------------------------------------------------------------------------- preview and notices

def preview(conn):
    """What a full recalculation would change, worked out inside a savepoint and thrown away (nothing saved)."""
    sid = S.current_season_id(conn)
    conn.execute("SAVEPOINT calc_update_preview")      # everything below, even lazily-filled defaults, is undone
    try:
        before = impacts.snapshot(conn, sid)
        E.set_league(conn, C.ENGINE_CURRENT, "full")
        _mark_seasons(conn, sid, C.ENGINE_CURRENT)
        rebuild_active_season(conn, sid)
        after = impacts.snapshot(conn, sid)
        reviews = _review_items(conn, sid)
    finally:
        conn.execute("ROLLBACK TO calc_update_preview")
        conn.execute("RELEASE calc_update_preview")
    changes = impacts.diff(before, after)
    dmap = S.driver_map(conn)
    rows = [{"driver": dmap[did], "changes": ch} for did, ch in sorted(changes.items(), key=lambda x: dmap[x[0]]["name"])]
    unchanged = [dmap[int(d)] for d in after if int(d) not in changes]
    standings_moves = [r for r in rows if any(c["stat"] == "position" for c in r["changes"])]
    return {"rows": rows, "unchanged": unchanged, "reviews": [dmap[d] for d in reviews], "before": before,
            "after": after, "standings_moves": len(standings_moves)}


def _notify(conn, migration_id, before, after, why):
    changes = impacts.diff(before, after)
    n = 0
    for did, rows in changes.items():
        details = ["Completed history (earlier seasons) is unchanged; only this season was recalculated.",
                   "Race results were not changed."]
        if impacts.add_notice(conn, did, f"migration-{migration_id}", "Calculation Version 3: your numbers were "
                              "recalculated", why, rows, details):
            n += 1
    return n


def migrations(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM calc_migrations ORDER BY id DESC")]


def notices_for(conn, migration_id):
    """Every notice a migration produced, with who has agreed (for the Race Master)."""
    impacts._tables(conn)
    out = []
    dmap = S.driver_map(conn)
    for r in conn.execute("SELECT * FROM impact_notices WHERE key = ? ORDER BY driver_id", (f"migration-{migration_id}",)):
        n = impacts._row(r)
        n["driver"] = dmap.get(n["driver_id"])
        n["acked"] = [dict(a) for a in conn.execute("SELECT * FROM impact_acks WHERE notice_id = ?", (r["id"],))]
        out.append(n)
    return out


def reminder(conn):
    """Race Master reminder text while the league is still on Version 2 (None once decided)."""
    if not E.needs_choice(conn):
        return None
    return ("This league still uses Calculation Version 2. Paddock Legacy 2.5 brings Calculation Version 3: "
            "choose when to switch.")
