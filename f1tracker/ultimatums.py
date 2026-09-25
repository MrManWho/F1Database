"""Mid-season dismissals (v2.1), the F1 way: a final warning with a clear target, then a decision.

* When a player driver's team relationship has sat at "Seat at risk" (warning level 3) for at least
  MIN_ROUNDS completed rounds and there are still ROUNDS_LEFT rounds to go, the team issues an ultimatum for
  the next race: a must-hit target pitched at the car (e.g. "Finish P14 or better at Monza, or you're out").
* After that race: target met -> the warning eases (level 2). Didn't start / DNF -> void, a fresh one next race.
  Missed -> "awaiting decision": the Race Master confirms the dismissal or overrules it with a note.
* Dismissal: the driver loses the seat for the rest of the season (the best unseated AI driver takes it), keeps
  every result, point and their Reputation, and is free to find a new team. Nothing already raced changes.

League setting "Mid-season dismissals" (on unless the league turns it off). Only one ultimatum per driver at a
time and at most one dismissal decision per driver per season.
"""

from . import calc3, engine
from . import constants as C
from . import feed, relations
from . import services as S
from .storage import get_meta, now_iso, set_meta

MIN_ROUNDS = 4       # completed rounds before a team can issue an ultimatum
ROUNDS_LEFT = 2      # at least this many rounds must remain


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS ultimatums (
        id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL, driver_id INTEGER NOT NULL, team_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL, target INTEGER NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Issued',
        note TEXT, decided_by TEXT, created_at TEXT NOT NULL, decided_at TEXT)""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ultimatums)")}
    if "kind" not in cols:     # v2.5: 'position' (finish P{target} or better) or 'teammate' (beat your teammate)
        conn.execute("ALTER TABLE ultimatums ADD COLUMN kind TEXT NOT NULL DEFAULT 'position'")


def enabled(conn):
    return get_meta(conn, "midseason_sackings", "1") == "1"


def set_enabled(conn, on):
    set_meta(conn, "midseason_sackings", "1" if on else "0")


def for_season(conn, season_id, driver_id=None):
    _table(conn)
    sql = """SELECT u.*, e.round_number, e.name AS event_name FROM ultimatums u JOIN events e ON e.id = u.event_id
             WHERE u.season_id = ?""" + (" AND u.driver_id = ?" if driver_id else "") + " ORDER BY u.id DESC"
    return [dict(r) for r in conn.execute(sql, (season_id, driver_id) if driver_id else (season_id,))]


def active(conn, season_id, driver_id):
    _table(conn)
    row = conn.execute("""SELECT u.*, e.round_number, e.name AS event_name FROM ultimatums u
                          JOIN events e ON e.id = u.event_id WHERE u.season_id = ? AND u.driver_id = ?
                          AND u.status IN ('Issued', 'Awaiting decision') ORDER BY u.id DESC LIMIT 1""",
                       (season_id, driver_id)).fetchone()
    return dict(row) if row else None


def awaiting(conn, season_id):
    return [u for u in for_season(conn, season_id) if u["status"] == "Awaiting decision"]


def _target_for(conn, season_id, team_id):
    ranks = S.team_strength_ranks(conn, season_id)
    rank = ranks.get(team_id, len(ranks) or 11)
    field = 2 * (len(S.teams(conn)) or 11)
    if engine.is_v3(conn, season_id):
        # v2.5: explicit rounding, and never "just finish": the easiest ordinary target is P(field - 2), e.g. P20.
        return int(min(field - 2, engine.round_half_up(relations.expected_finish(rank) + 2)))
    # Where the car should finish, with a little room: demanding, never impossible.
    return int(min(field, round(relations.expected_finish(rank) + 2)))


def _judge_v3(conn, event, u, r):
    """Engine 3 outcome: Met, Failed (-> Race Master decision), Void, or Review (-> Race Master decision)."""
    if event["postponed"] or event.get("cancelled"):
        return "Void", "the round didn't count"
    if not r or r["result_status"] == C.STATUS_NOT_RUN:
        return "Review", "didn't take part"
    if r["result_status"] == "DNS":
        return "Review", "didn't start"
    if r["result_status"] == "DNF" and r["no_fault"]:
        prev = conn.execute("""SELECT status FROM ultimatums WHERE season_id = ? AND driver_id = ? AND id < ?
                               ORDER BY id DESC LIMIT 1""", (u["season_id"], u["driver_id"], u["id"])).fetchone()
        if prev and prev["status"] == "Void":
            return "Review", "a second race in a row that didn't count"
        return "Void", "a retirement that wasn't the driver's fault"
    if u["kind"] == "teammate":
        mate = conn.execute("SELECT * FROM results WHERE event_id = ? AND team_id = ? AND driver_id != ?",
                            (event["id"], r["team_id"], u["driver_id"])).fetchone()
        won = calc3.compare(dict(r), dict(mate)) if mate else None
        if won is None:
            return "Review", "no comparison with the teammate"
        return ("Met", "ahead of the teammate") if won else ("Failed", "behind the teammate")
    if r["result_status"] in C.CLASSIFIED_STATUSES and r["race_position"] and r["race_position"] <= u["target"]:
        return "Met", f"P{r['race_position']}"
    return "Failed", (f"P{r['race_position']}" if r["result_status"] in C.CLASSIFIED_STATUSES else r["result_status"])


def use_teammate_target(conn, ultimatum_id, username):
    """Race Master: turn an issued ultimatum into "finish ahead of your teammate" (engine 3), for when a finishing
    position wouldn't mean much (e.g. the slowest car)."""
    _table(conn)
    u = conn.execute("SELECT * FROM ultimatums WHERE id = ?", (ultimatum_id,)).fetchone()
    if not u or u["status"] != "Issued":
        raise S.ValidationError("Only an ultimatum that hasn't been raced yet can change")
    ev = S.get_event(conn, u["event_id"])
    label = f"Finish ahead of your teammate at R{ev['round_number']} {ev['name']}, or you're out"
    conn.execute("UPDATE ultimatums SET kind = 'teammate', label = ? WHERE id = ?", (label, ultimatum_id))
    relations.note(conn, u["season_id"], u["driver_id"], u["team_id"], "danger", f"Your final warning changed: {label}.")
    return label


def after_race(conn, event_id):
    """Judge any ultimatum for this race, then issue new ones where a team has run out of patience."""
    _table(conn)
    event = S.get_event(conn, event_id)
    sid = event["season_id"]
    tmap, dmap = S.team_map(conn), S.driver_map(conn)
    v3 = engine.round_v3(conn, event)
    for u in conn.execute("SELECT * FROM ultimatums WHERE event_id = ? AND status = 'Issued'", (event_id,)).fetchall():
        r = conn.execute("SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (event_id, u["driver_id"])).fetchone()
        team, name = tmap[u["team_id"]]["name"], dmap[u["driver_id"]]["name"]
        if v3:
            outcome, why = _judge_v3(conn, event, u, r)
            if outcome == "Void":
                conn.execute("UPDATE ultimatums SET status = 'Void', decided_at = ? WHERE id = ?", (now_iso(), u["id"]))
                relations.note(conn, sid, u["driver_id"], u["team_id"], "warning",
                               f"{team}: that race doesn't count ({why}). The same demand stands for the next one.")
            elif outcome == "Met":
                conn.execute("UPDATE ultimatums SET status = 'Met', decided_at = ? WHERE id = ?", (now_iso(), u["id"]))
                conn.execute("UPDATE team_relations SET warning_level = 2 WHERE season_id = ? AND driver_id = ?",
                             (sid, u["driver_id"]))
                relations.note(conn, sid, u["driver_id"], u["team_id"], "good",
                               f"{team}: you answered when it mattered ({why}). Your seat is safe for now, "
                               "but the warning stands.")
                feed.post(conn, sid, "paddock", f"{name} saves their seat at {team}",
                          f"On a final warning, {name} delivered at {event['name']} ({why}).", "news",
                          driver_id=u["driver_id"], team_id=u["team_id"])
            else:
                conn.execute("UPDATE ultimatums SET status = 'Awaiting decision', note = ?, decided_at = ? WHERE id = ?",
                             (("Failed: " if outcome == "Failed" else "Needs review: ") + why, now_iso(), u["id"]))
                relations.note(conn, sid, u["driver_id"], u["team_id"], "danger",
                               f"{team} have made up their minds after {event['name']}. The Race Master will confirm "
                               "whether you keep your seat.")
                feed.notify(conn, None, f"{team} want to drop {name} mid-season ({why}). Confirm or overrule it on "
                            "Grid & contracts.", "grid#dismissals", category="admin")
            continue
        if not r or r["result_status"] in ("DNF", "DNS", C.STATUS_NOT_RUN):
            conn.execute("UPDATE ultimatums SET status = 'Void', decided_at = ? WHERE id = ?", (now_iso(), u["id"]))
            relations.note(conn, sid, u["driver_id"], u["team_id"], "warning",
                           f"{team}: that race doesn't count either way. The same demand stands for the next one.")
        elif r["result_status"] == C.STATUS_FINISHED and r["race_position"] and r["race_position"] <= u["target"]:
            conn.execute("UPDATE ultimatums SET status = 'Met', decided_at = ? WHERE id = ?", (now_iso(), u["id"]))
            conn.execute("UPDATE team_relations SET warning_level = 2 WHERE season_id = ? AND driver_id = ?",
                         (sid, u["driver_id"]))
            relations.note(conn, sid, u["driver_id"], u["team_id"], "good",
                           f"{team}: you answered when it mattered (P{r['race_position']}). Your seat is safe for now, "
                           "but the warning stands.")
            feed.post(conn, sid, "paddock", f"{name} saves their seat at {team}",
                      f"On a final warning, {name} delivered P{r['race_position']} at {event['name']}.", "news",
                      driver_id=u["driver_id"], team_id=u["team_id"])
        else:
            conn.execute("UPDATE ultimatums SET status = 'Awaiting decision', decided_at = ? WHERE id = ?",
                         (now_iso(), u["id"]))
            relations.note(conn, sid, u["driver_id"], u["team_id"], "danger",
                           f"{team} have made up their minds after {event['name']}. The Race Master will confirm "
                           "whether you keep your seat.")
            feed.notify(conn, None, f"{team} want to drop {name} mid-season. Confirm or overrule it on Grid & contracts.",
                        "grid#dismissals", category="admin")
    if enabled(conn):
        _issue(conn, event)


def _issue(conn, event):
    sid = event["season_id"]
    evs = S.events(conn, sid)
    done = sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE)
    nxt = S.next_incomplete_event(conn, sid)
    if not nxt or done < MIN_ROUNDS or len(evs) - done < ROUNDS_LEFT:
        return []
    seats = S.driver_seats(conn, sid)
    tmap, dmap = S.team_map(conn), S.driver_map(conn)
    issued = []
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND released = 0 AND warning_level >= 3",
                            (sid,)).fetchall():
        did = rel["driver_id"]
        if did not in seats or seats[did][0] != rel["team_id"] or active(conn, sid, did):
            continue
        if conn.execute("SELECT 1 FROM ultimatums WHERE season_id = ? AND driver_id = ? AND status IN "
                        "('Dismissed', 'Overruled')", (sid, did)).fetchone():
            continue   # one decision per season
        if relations.assess(conn, sid, did)["live_status"] != "Seat at risk":
            continue
        target = _target_for(conn, sid, rel["team_id"])
        team, name = tmap[rel["team_id"]]["name"], dmap[did]["name"]
        label = f"Finish P{target} or better at R{nxt['round_number']} {nxt['name']}, or you're out"
        conn.execute("""INSERT INTO ultimatums(season_id, driver_id, team_id, event_id, target, label, created_at)
                        VALUES(?,?,?,?,?,?,?)""", (sid, did, rel["team_id"], nxt["id"], target, label, now_iso()))
        relations.note(conn, sid, did, rel["team_id"], "danger", f"Final warning from {team}: {label}.")
        feed.post(conn, sid, "paddock", f"{name} on a final warning at {team}",
                  f"{team} have told {name} to finish P{target} or better at {nxt['name']}, or lose the seat.",
                  "news", driver_id=did, team_id=rel["team_id"])
        issued.append(did)
    return issued


def free_agents(conn, season_id):
    """Player drivers without a seat this season, who can step in for a dismissed driver (v2.5)."""
    seats = S.driver_seats(conn, season_id)
    return [p for p in S.player_drivers(conn) if p["active"] and p["id"] not in seats]


def decide(conn, ultimatum_id, dismiss, username, note="", replacement_id=None):
    """Race Master: confirm the dismissal (the driver loses the seat now) or overrule it (with a note)."""
    _table(conn)
    u = conn.execute("SELECT * FROM ultimatums WHERE id = ?", (ultimatum_id,)).fetchone()
    if not u or u["status"] != "Awaiting decision":
        raise S.ValidationError("Nothing is waiting for a decision there")
    sid, did = u["season_id"], u["driver_id"]
    team, name = S.team_map(conn)[u["team_id"]]["name"], S.driver_map(conn)[did]["name"]
    note = (note or "").strip()
    if not dismiss:
        if len(note) < C.GATE_NOTE_MIN:
            raise S.ValidationError(f"Add a note of at least {C.GATE_NOTE_MIN} characters saying why the driver stays")
        conn.execute("UPDATE ultimatums SET status = 'Overruled', note = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                     (note[:500], username, now_iso(), ultimatum_id))
        conn.execute("UPDATE team_relations SET warning_level = 2 WHERE season_id = ? AND driver_id = ?", (sid, did))
        relations.note(conn, sid, did, u["team_id"], "warning",
                       f"The Race Master overruled {team}: you keep your seat. “{note[:200]}”")
        return "overruled"
    seat = S.driver_seats(conn, sid).get(did)
    replacement_player = None
    if replacement_id:
        replacement_player = next((p for p in free_agents(conn, sid) if p["id"] == int(replacement_id)), None)
        if not replacement_player:
            raise S.ValidationError("Only a player driver without a seat can step in")
    if seat and seat[0] == u["team_id"]:
        if replacement_player:
            # v2.5: a free agent steps in for the rest of the season (Mid-season Replacement)
            S.place_players(conn, sid, {did: None, replacement_player["id"]: seat})
        else:
            S.place_players(conn, sid, {did: None})       # the best unseated AI driver takes the seat
        if replacement_player:
            conn.execute("UPDATE drivers SET career_status = 'Mid-season Replacement' WHERE id = ?",
                         (replacement_player["id"],))
            relations.ensure(conn, sid)
    conn.execute("UPDATE ultimatums SET status = 'Dismissed', note = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                 (note[:500] or None, username, now_iso(), ultimatum_id))
    conn.execute("UPDATE team_relations SET released = 1, status = 'Released', updated_at = ? "
                 "WHERE season_id = ? AND driver_id = ?", (now_iso(), sid, did))
    from . import seats
    seats.end_contracts_on_release(conn, did, u["team_id"], S.get_season(conn, sid)["year"])   # v3.0: a free agent
    replacement = S.grid_map(conn, sid).get(seat) if seat else None
    rname = S.driver_map(conn)[replacement]["name"] if replacement else "a reserve"
    relations.note(conn, sid, did, u["team_id"], "danger",
                   f"{team} have let you go with immediate effect. {rname} takes the seat. Your results and points "
                   "stay yours, and you're free to talk to other teams.")
    feed.post(conn, sid, "market", f"{team} drop {name} mid-season",
              f"{name} missed the target {team} set ({u['label'].lower()}). {rname} steps in for the rest of the season.",
              "news", driver_id=did, team_id=u["team_id"])
    return "dismissed"
