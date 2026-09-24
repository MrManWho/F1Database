"""Teammate battle: a season-long head-to-head between the two drivers sharing each car.

Counted over completed rounds only, per pairing (a driver who changes seat mid-season has one battle per
teammate, e.g. "vs Stroll R1-R6, vs Alonso R7+"):
  - Qualifying: who qualified ahead (both need a qualifying position).
  - Race: who finished ahead. A finisher beats a DNF/DSQ; if neither finished the round is skipped.
  - Points: Grand Prix plus Sprint points scored in the rounds they shared.
Beating your teammate is never punished. Headlines: a new leader in the race battle, five in a row, and the
season verdict, only for pairings with at least one player driver, once each.
"""

from . import constants as C
from . import feed
from . import services as S


def _race_order(r):
    if r["result_status"] not in C.START_STATUSES:
        return None
    return r["race_position"] if r["result_status"] == C.STATUS_FINISHED and r["race_position"] else 99


def _points(r, is_sprint):
    return S.gp_points(r["race_position"], r["result_status"]) + \
        S.sprint_points(r["sprint_position"], r["sprint_status"], bool(is_sprint))


def pairings(conn, season_id, driver_id, upto_round=None):
    """Every teammate this driver has shared a car with in completed rounds, oldest pairing first."""
    rows = conn.execute("""SELECT r.*, e.round_number, e.is_sprint FROM results r JOIN events e ON e.id = r.event_id
                           WHERE e.season_id = ? AND r.driver_id = ? AND e.status = ? AND e.round_number <= ?
                           ORDER BY e.round_number""",
                        (season_id, driver_id, C.EVENT_COMPLETE, upto_round if upto_round is not None else 10 ** 6))
    dmap = S.driver_map(conn)
    tmap = S.team_map(conn)
    out, by_mate = [], {}
    for r in rows.fetchall():
        m = conn.execute("SELECT * FROM results WHERE event_id = ? AND team_id = ? AND driver_id != ?",
                         (r["event_id"], r["team_id"], driver_id)).fetchone()
        if not m:
            continue
        key = (m["driver_id"], r["team_id"])
        p = by_mate.get(key)
        if not p:
            p = {"driver": dmap.get(driver_id), "mate": dmap.get(m["driver_id"]), "team": tmap.get(r["team_id"]),
                 "quali_won": 0, "quali_lost": 0, "race_won": 0, "race_lost": 0, "points": 0, "mate_points": 0,
                 "first_round": r["round_number"], "last_round": r["round_number"], "rounds": 0, "races": []}
            by_mate[key] = p
            out.append(p)
        p["last_round"] = r["round_number"]
        p["rounds"] += 1
        if r["qualifying_position"] and m["qualifying_position"]:
            won = r["qualifying_position"] < m["qualifying_position"]
            p["quali_won" if won else "quali_lost"] += 1
        mine, theirs = _race_order(r), _race_order(m)
        if mine is not None and theirs is not None and not (mine == 99 and theirs == 99) and mine != theirs:
            won = mine < theirs
            p["race_won" if won else "race_lost"] += 1
            p["races"].append((r["round_number"], won))
        p["points"] += _points(r, r["is_sprint"])
        p["mate_points"] += _points(m, r["is_sprint"])
    for p in out:
        p["gap"] = p["points"] - p["mate_points"]
        p["human"] = bool(p["driver"] and p["mate"] and p["driver"]["is_player"] and p["mate"]["is_player"])
        streak = 0
        for _rnd, won in reversed(p["races"]):
            if not won:
                break
            streak += 1
        p["streak"] = streak
        p["leading"] = p["race_won"] > p["race_lost"]
    return out


def team_battles(conn, season_id, team_id):
    """Every pairing at a team this season, each listed once (the lower driver id first)."""
    drivers = [r[0] for r in conn.execute("""SELECT DISTINCT r.driver_id FROM results r JOIN events e ON e.id = r.event_id
                                             WHERE e.season_id = ? AND r.team_id = ? AND e.status = ? ORDER BY r.driver_id""",
                                          (season_id, team_id, C.EVENT_COMPLETE))]
    out, seen = [], set()
    for d in drivers:
        for p in pairings(conn, season_id, d):
            if p["team"] and p["team"]["id"] == team_id and p["mate"] and (p["mate"]["id"], d) not in seen:
                seen.add((d, p["mate"]["id"]))
                out.append(p)
    return out


def player_battles(conn, event):
    """After a round: the battle at every team with a player driver, up to and including this round."""
    out, seen = [], set()
    for d in S.player_drivers(conn):
        for p in pairings(conn, event["season_id"], d["id"], event["round_number"]):
            if p["last_round"] != event["round_number"] or not p["mate"]:
                continue
            pair = tuple(sorted((d["id"], p["mate"]["id"])))
            if pair in seen:
                continue
            seen.add(pair)
            out.append(p)
    return out


def after_race(conn, event_id):
    """Headlines for teams with a player driver: a new leader, five in a row, and the season verdict."""
    event = S.get_event(conn, event_id)
    if not event or event["status"] != C.EVENT_COMPLETE:
        return
    season_done = not conn.execute("SELECT 1 FROM events WHERE season_id = ? AND status != ?",
                                   (event["season_id"], C.EVENT_COMPLETE)).fetchone()
    for p in player_battles(conn, event):
        a, b = p["driver"], p["mate"]
        team_id = p["team"]["id"] if p["team"] else None
        before = next((q for q in pairings(conn, event["season_id"], a["id"], event["round_number"] - 1)
                       if q["mate"] and q["mate"]["id"] == b["id"] and q["team"] == p["team"]), None)
        # A lead only counts from two races in, so the first race alone never makes a headline.
        was = (before["race_won"] - before["race_lost"]) if before and before["race_won"] + before["race_lost"] >= 2 else 0
        now = p["race_won"] - p["race_lost"]
        leader, trailer = (a, b) if now > 0 else (b, a)
        if now != 0 and (was == 0 or (was > 0) != (now > 0)) and p["race_won"] + p["race_lost"] >= 2:
            _post(conn, event, f"battle-lead:{event_id}:{min(a['id'], b['id'])}:{max(a['id'], b['id'])}",
                  f"{leader['name']} takes the lead in the {p['team']['name'] if p['team'] else 'team'} battle",
                  f"After R{event['round_number']} {event['name']}, {leader['name']} leads {trailer['name']} "
                  f"{max(p['race_won'], p['race_lost'])}–{min(p['race_won'], p['race_lost'])} in races.",
                  leader["id"], team_id)
        for d, m, q in ((a, b, p), (b, a, _mirror(p))):
            if q["streak"] == 5:
                _post(conn, event, f"battle-five:{event_id}:{d['id']}",
                      f"{d['name']} beats {m['name']} for the fifth race in a row",
                      f"{d['name']} has finished ahead of teammate {m['name']} in five straight races.", d["id"], team_id)
        if season_done:
            if now == 0:
                title = f"Season verdict: {a['name']} and {b['name']} split their races"
            else:
                title = f"Season verdict: {leader['name']} wins the {p['team']['name'] if p['team'] else 'team'} battle"
            _post(conn, event, f"battle-verdict:{event['season_id']}:{min(a['id'], b['id'])}:{max(a['id'], b['id'])}",
                  title, f"{summary(p)} ({a['name']} vs {b['name']}).", leader["id"], team_id)


def _mirror(p):
    races = [(rnd, not won) for rnd, won in p["races"]]
    streak = 0
    for _rnd, won in reversed(races):
        if not won:
            break
        streak += 1
    return {**p, "streak": streak}


def summary(p):
    return (f"Quali {p['quali_won']}–{p['quali_lost']} · Race {p['race_won']}–{p['race_lost']} · "
            f"{'%+d' % p['gap']} pts")


def _post(conn, event, ref, headline, body, driver_id, team_id):
    if conn.execute("SELECT 1 FROM news WHERE ref = ?", (ref,)).fetchone():
        return
    feed.post(conn, event["season_id"], "paddock", headline, body, "news", driver_id=driver_id, team_id=team_id, ref=ref)
