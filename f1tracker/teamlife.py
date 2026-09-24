"""Life inside a team between races: the post-race press pen and team orders.

Press: after each race every player driver who raced gets two questions picked from how their weekend
went. Each answer nudges the relationship with their team (a small, capped bonus) and some make headlines.
Only the latest completed race has an open press pen; unanswered questions simply lapse.

Team orders (League Settings, off by default): after a race, a player driver on a No. 2 contract may be told
to let their teammate through at the next race. "On" judges it from the finishing order (finishing ahead of
the teammate means the order was ignored, unless either of them didn't finish); "Advisory" shows the order
but it has no effect and makes no headlines; "Off" issues none and cancels any still waiting, without penalty.

Weekend targets: before each race every seated player driver gets one realistic target from their team
(finish P8 or better, score points, beat both cars of the team just behind, occasionally beat your teammate),
pitched from the car's expected finish, recent form and their contract role. It's judged automatically from
the results: hit +2, missed -1.5 on the team relationship; void if they didn't take part. A DNF or DSQ is a
miss unless the Race Master marks it "not the driver's fault". Corrections re-judge it.
"""

import math
import random

from . import constants as C
from . import feed
from . import relations
from . import services as S
from .storage import now_iso

# key: (question, [(answer key, answer, relationship effect, headline or None)])
QUESTIONS = {
    "credit": ("Great result today. Who deserves the credit?", [
        ("team", "The team gave me a brilliant car", 2, None),
        ("me", "Honestly? That was all me", -2, "{driver}: \"That was all me\""),
        ("job", "Just doing my job. On to the next one", 1, None)]),
    "wrong": ("A tough afternoon. What went wrong?", [
        ("car", "The car just wasn't there today", -3, "{driver} points the finger at the {team} car"),
        ("me", "That's on me. I have to be better", 1, None),
        ("together", "We'll go through it together and come back stronger", 2, None)]),
    "dnf": ("Your race ended early. How frustrated are you?", [
        ("incident", "Racing incident. We move on", 1, None),
        ("them", "Someone else ruined my race", 0, "{driver} fumes after early exit"),
        ("reliability", "The reliability isn't good enough", -3, "{driver} hits out at {team} reliability")]),
    "beat_mate": ("You beat your teammate again. Who leads this team?", [
        ("me", "The results speak for themselves: me", -1, "{driver} stakes claim to lead {team}"),
        ("push", "We push each other, and that's good for the team", 2, None),
        ("nothing", "It's one race. Nothing's decided", 0, None)]),
    "lost_mate": ("Your teammate had the upper hand. Are you worried?", [
        ("setup", "They had the better setup this weekend", -1, None),
        ("next", "I'll be ahead next time, count on it", 1, None),
        ("fine", "Fair play to them. I'm learning every race", 1, None)]),
    "future": ("The transfer window is open. Are you staying?", [
        ("committed", "I'm fully committed to this team", 3, None),
        ("listening", "I'm listening to every offer", -3, "{driver} keeps options open as {team} wait"),
        ("nocomment", "No comment", 0, None)]),
    "next": ("What's the target for the next race?", [
        ("points", "Bring home points for the team", 1, None),
        ("podium", "The podium. Nothing less", 0, None),
        ("learn", "Keep learning and build momentum", 1, None)]),
}


def _result(conn, event_id, driver_id):
    return conn.execute("SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (event_id, driver_id)).fetchone()


def _teammate_result(conn, event_id, row):
    return conn.execute("SELECT * FROM results WHERE event_id = ? AND team_id = ? AND driver_id != ?",
                        (event_id, row["team_id"], row["driver_id"])).fetchone()


def questions_for(conn, event_id, driver_id):
    """The two questions for this driver after this race (always the same two for the same weekend)."""
    row = _result(conn, event_id, driver_id)
    if not row or row["result_status"] not in C.START_STATUSES:
        return []
    keys = []
    finished = row["result_status"] == C.STATUS_FINISHED and row["race_position"]
    if not finished:
        keys.append("dnf")
    elif row["race_position"] <= 3 or (row["qualifying_position"] and
                                        row["qualifying_position"] - row["race_position"] >= 5):
        keys.append("credit")
    elif row["race_position"] > 10:
        keys.append("wrong")
    mate = _teammate_result(conn, event_id, row)
    if finished and mate and mate["result_status"] == C.STATUS_FINISHED and mate["race_position"]:
        keys.append("beat_mate" if row["race_position"] < mate["race_position"] else "lost_mate")
    if conn.execute("SELECT 1 FROM market_windows WHERE status = ?", (C.WINDOW_OPEN,)).fetchone():
        keys.insert(1, "future")
    keys.append("next")
    seen = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    return [{"key": k, "text": QUESTIONS[k][0],
             "answers": [{"key": a, "text": t, "effect": e} for a, t, e, _h in QUESTIONS[k][1]]} for k in seen[:2]]


def latest_press_event(conn, season_id):
    row = conn.execute("SELECT * FROM events WHERE season_id = ? AND status = ? ORDER BY round_number DESC LIMIT 1",
                       (season_id, C.EVENT_COMPLETE)).fetchone()
    return dict(row) if row else None


def press_pen(conn, season_id, driver_id):
    """The open press pen for a driver: the latest race's questions and what's been answered."""
    event = latest_press_event(conn, season_id)
    return _pen(conn, event, driver_id) if event else None


def press_pens(conn, season_id, driver_id):
    """Every open press pen for a driver: the latest race's, plus older ones still waiting for answers when
    press questions are required (they don't lapse then)."""
    pens = []
    latest = press_pen(conn, season_id, driver_id)
    if press_stays_open(conn):
        for e in conn.execute("SELECT * FROM events WHERE season_id = ? AND status = ? AND press_required = 1 "
                              "ORDER BY round_number", (season_id, C.EVENT_COMPLETE)).fetchall():
            if latest and e["id"] == latest["event"]["id"]:
                continue
            pen = _pen(conn, dict(e), driver_id)
            if pen and pen["open"]:
                pens.append(pen)
    if latest:
        pens.append(latest)
    return pens


def _pen(conn, event, driver_id):
    questions = questions_for(conn, event["id"], driver_id)
    if not questions:
        return None
    answered = {r["question"]: r["answer"] for r in conn.execute(
        "SELECT * FROM press_answers WHERE event_id = ? AND driver_id = ?", (event["id"], driver_id))}
    for q in questions:
        q["answered"] = answered.get(q["key"])
    return {"event": event, "questions": questions, "open": sum(1 for q in questions if not q["answered"])}


def press_history(conn, driver_id, limit=40):
    """Everything this driver has said to the press, newest first, with how the team took it."""
    out = []
    for r in conn.execute("""SELECT p.*, e.round_number, e.name AS event_name, s.year FROM press_answers p
                             JOIN events e ON e.id = p.event_id JOIN seasons s ON s.id = e.season_id
                             WHERE p.driver_id = ? ORDER BY s.year DESC, e.round_number DESC LIMIT ?""",
                          (driver_id, limit)):
        q = QUESTIONS.get(r["question"])
        said = next((t for k, t, _e, _h in q[1] if k == r["answer"]), r["answer"]) if q else r["answer"]
        out.append({"label": f"{r['year']} R{r['round_number']} {r['event_name']}", "question": q[0] if q else r["question"],
                    "answer": said, "effect": r["effect"]})
    return out


def answer(conn, event_id, driver_id, question, choice):
    event = S.get_event(conn, event_id)
    if not event or event["status"] != C.EVENT_COMPLETE:
        raise S.ValidationError("That press pen isn't open")
    latest = latest_press_event(conn, event["season_id"])
    still_open = event["press_required"] and press_stays_open(conn)
    if (not latest or latest["id"] != event_id) and not still_open:
        raise S.ValidationError("The press have moved on to the next race")
    q = next((q for q in questions_for(conn, event_id, driver_id) if q["key"] == question), None)
    if not q:
        raise S.ValidationError("That question wasn't asked")
    if conn.execute("SELECT 1 FROM press_answers WHERE event_id = ? AND driver_id = ? AND question = ?",
                    (event_id, driver_id, question)).fetchone():
        raise S.ValidationError("You've already answered that one")
    pick = next((a for a in QUESTIONS[question][1] if a[0] == choice), None)
    if not pick:
        raise S.ValidationError("Pick one of the answers")
    _key, text, effect, headline = pick
    conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) VALUES(?,?,?,?,?,?)",
                 (event_id, driver_id, question, choice, effect, now_iso()))
    relations.ensure(conn, event["season_id"])
    relations.add_bonus(conn, event["season_id"], driver_id, effect)
    if headline:
        driver = S.driver_map(conn)[driver_id]
        seat = S.driver_seats(conn, event["season_id"]).get(driver_id)
        team = S.team_map(conn).get(seat[0]) if seat else None
        feed.post(conn, event["season_id"], "paddock",
                  headline.format(driver=driver["name"], team=team["name"] if team else "the team"),
                  f"Asked \"{q['text']}\" after R{event['round_number']} {event['name']}, {driver['name']} said: \"{text}\"",
                  "news", driver_id=driver_id, team_id=team["id"] if team else None)
    return effect


# --------------------------------------------------------------------------- league settings

# Used when a league has never saved the setting: team orders off, targets and round gates on.
DEFAULTS = {"team_orders": "off", "weekend_targets": "1", "round_gates": "1", "gate_press": "1", "gate_targets": "1"}


def settings(conn):
    """Team-life switches for this league (League Settings). Missing values are the defaults."""
    from .storage import get_meta
    val = {k: get_meta(conn, k, d) for k, d in DEFAULTS.items()}
    return {"orders": val["team_orders"] if val["team_orders"] in C.TEAM_ORDER_MODES else "off",
            "targets": val["weekend_targets"] == "1", "gates": val["round_gates"] == "1",
            "gate_press": val["gate_press"] == "1", "gate_targets": val["gate_targets"] == "1"}


def save_settings(conn, orders, targets, gates, gate_press, gate_targets):
    from .storage import set_meta
    if orders in C.TEAM_ORDER_MODES:
        set_meta(conn, "team_orders", orders)
    for key, on in (("weekend_targets", targets), ("round_gates", gates), ("gate_press", gate_press),
                    ("gate_targets", gate_targets)):
        set_meta(conn, key, "1" if on else "0")
    if settings(conn)["orders"] == "off":
        cancel_open_orders(conn)


def press_stays_open(conn):
    """With press gates on, unanswered questions don't lapse when the next race is completed."""
    s = settings(conn)
    return s["gates"] and s["gate_press"]


# --------------------------------------------------------------------------- team orders

def cancel_open_orders(conn):
    """Team orders switched off: orders still waiting are cancelled, with no effect on anyone."""
    conn.execute("UPDATE team_orders SET status = 'Cancelled' WHERE status = 'Issued'")

def _teammate(conn, season_id, driver_id):
    seat = S.driver_seats(conn, season_id).get(driver_id)
    if not seat:
        return None, None
    return seat[0], S.grid_map(conn, season_id).get((seat[0], 2 if seat[1] == 1 else 1))


def issue_orders(conn, season_id, rng=None):
    """Before the next race, teams may tell a No. 2 player driver to give way to their teammate."""
    mode = settings(conn)["orders"]
    if mode == "off":
        return []
    nxt = S.next_incomplete_event(conn, season_id)
    if not nxt or nxt["status"] != C.EVENT_NOT_RUN:
        return []
    relations.ensure(conn, season_id)
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    issued = []
    for rel in conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND released = 0", (season_id,)).fetchall():
        if relations._role(conn, rel) != "No. 2":
            continue
        if conn.execute("SELECT 1 FROM team_orders WHERE event_id = ? AND driver_id = ?",
                        (nxt["id"], rel["driver_id"])).fetchone():
            continue
        team_id, mate = _teammate(conn, season_id, rel["driver_id"])
        if not mate:
            continue
        mine, theirs = standings.get(rel["driver_id"]), standings.get(mate)
        ahead = bool(theirs and mine and theirs["points"] > mine["points"])
        chance = 0.4 if ahead else 0.2
        roll = (rng or random.Random(nxt["id"] * 7919 + rel["driver_id"])).random()
        if roll >= chance:
            continue
        conn.execute("INSERT INTO team_orders(event_id, driver_id, beneficiary_id, status, created_at) VALUES(?,?,?,?,?)",
                     (nxt["id"], rel["driver_id"], mate, "Issued", now_iso()))
        name = S.driver_map(conn)[mate]["name"]
        if mode == "advisory":
            relations.note(conn, season_id, rel["driver_id"], team_id, "concerned",
                           f"Team suggestion for R{nxt['round_number']} {nxt['name']}: if you're racing {name}, the team "
                           "would like you to let them through. It's advisory: it won't affect your standing.")
        else:
            relations.note(conn, season_id, rel["driver_id"], team_id, "concerned",
                           f"Team order for R{nxt['round_number']} {nxt['name']}: if you're racing {name}, let them "
                           "through. Finishing ahead of them means you ignored it.")
        issued.append(rel["driver_id"])
    return issued


def resolve_orders(conn, event_id):
    """After the race: was the order followed? Judged from the finishing order."""
    event = S.get_event(conn, event_id)
    mode = settings(conn)["orders"]
    if mode == "off":
        cancel_open_orders(conn)
        return []
    out = []
    for o in conn.execute("SELECT * FROM team_orders WHERE event_id = ? AND status = 'Issued'", (event_id,)).fetchall():
        me, them = _result(conn, event_id, o["driver_id"]), _result(conn, event_id, o["beneficiary_id"])
        both = me and them and me["result_status"] == C.STATUS_FINISHED and them["result_status"] == C.STATUS_FINISHED \
            and me["race_position"] and them["race_position"]
        status = "Void" if not both else ("Ignored" if me["race_position"] < them["race_position"] else "Obeyed")
        conn.execute("UPDATE team_orders SET status = ? WHERE event_id = ? AND driver_id = ?",
                     (status, event_id, o["driver_id"]))
        rel = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ?",
                           (event["season_id"], o["driver_id"])).fetchone()
        if rel and status != "Void" and mode == "on":
            name = S.driver_map(conn)[o["beneficiary_id"]]["name"]
            if status == "Ignored":
                relations.add_bonus(conn, event["season_id"], o["driver_id"], C.TEAM_ORDER_IGNORED)
                relations.note(conn, event["season_id"], o["driver_id"], rel["team_id"], "warning",
                               f"You ignored the team order and finished ahead of {name}. The team won't forget it.")
                driver = S.driver_map(conn)[o["driver_id"]]["name"]
                feed.post(conn, event["season_id"], "paddock", f"{driver} defies team orders",
                          f"{driver} was told to let {name} through at {event['name']} and didn't.", "news",
                          driver_id=o["driver_id"], team_id=rel["team_id"])
            else:
                relations.add_bonus(conn, event["season_id"], o["driver_id"], C.TEAM_ORDER_OBEYED)
                relations.note(conn, event["season_id"], o["driver_id"], rel["team_id"], "good",
                               f"Thanks for following the team order with {name}. That's noted.", notify=False)
        out.append((o["driver_id"], status))
    return out


def orders_for(conn, season_id, driver_id):
    dmap = S.driver_map(conn)
    rows = conn.execute("""SELECT o.*, e.round_number, e.name AS event_name FROM team_orders o
                           JOIN events e ON e.id = o.event_id WHERE e.season_id = ? AND o.driver_id = ?
                           ORDER BY e.round_number DESC""", (season_id, driver_id)).fetchall()
    return [{**dict(r), "beneficiary": dmap.get(r["beneficiary_id"])} for r in rows]


def after_race(conn, event_id):
    """Run everything that follows a completed race (called once, when a weekend is first completed)."""
    from . import battle
    event = S.get_event(conn, event_id)
    conn.execute("UPDATE events SET press_required = 1 WHERE id = ?", (event_id,))
    resolve_orders(conn, event_id)
    judge_targets(conn, event_id)
    battle.after_race(conn, event_id)
    relations.review(conn, event["season_id"])
    issue_orders(conn, event["season_id"])
    required = press_stays_open(conn)
    for rel in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?", (event["season_id"],)).fetchall():
        if questions_for(conn, event_id, rel["driver_id"]):
            feed.notify(conn, rel["driver_id"], f"The press want a word after R{event['round_number']} {event['name']}."
                        + (" Answer both questions before the next round can start." if required else ""),
                        "dashboard#press")
    nxt = S.next_incomplete_event(conn, event["season_id"])
    if nxt:
        issue_targets(conn, nxt["id"], notify=True)


# --------------------------------------------------------------------------- weekend targets

TARGET_KINDS = {"finish": "Finish P{n} or better", "points": "Score points (finish in the top 10)",
                "classified": "Bring the car home (finish the race)", "beat_team": "Beat both {team} cars",
                "teammate": "Finish ahead of your teammate"}


def _recent_finishes(conn, season_id, driver_id, before_round, field, count=3):
    rows = conn.execute("""SELECT r.race_position, r.result_status FROM results r JOIN events e ON e.id = r.event_id
                           WHERE e.season_id = ? AND e.status = ? AND r.driver_id = ? AND e.round_number < ?
                           ORDER BY e.round_number DESC LIMIT ?""",
                        (season_id, C.EVENT_COMPLETE, driver_id, before_round, count)).fetchall()
    out = []
    for r in rows:
        if r["result_status"] == C.STATUS_FINISHED and r["race_position"]:
            out.append(r["race_position"])
        elif r["result_status"] in ("DNF", "DSQ"):
            out.append(field)
    return out


def plan_target(conn, event, driver_id, team_id, ranks=None, rng=None):
    """The team's target for one driver at one race: pitched at the car, recent form and contract role."""
    season_id = event["season_id"]
    ranks = ranks or S.team_strength_ranks(conn, season_id)
    field = max(2, conn.execute("SELECT COUNT(*) FROM results WHERE event_id = ?", (event["id"],)).fetchone()[0]
                or 2 * len(S.teams(conn)))
    rank = ranks.get(team_id, len(ranks) or 11)
    base = relations.expected_finish(rank)
    recent = _recent_finishes(conn, season_id, driver_id, event["round_number"], field)
    if len(recent) >= 2:
        base = (base + sum(recent) / len(recent)) / 2
    rel = conn.execute("SELECT * FROM team_relations WHERE season_id = ? AND driver_id = ?",
                       (season_id, driver_id)).fetchone()
    role = relations._role(conn, rel) if rel else "Equal Status"
    base += {"No. 1": -1.0, "No. 2": 1.0}.get(role, 0.0)
    pos = int(max(1, min(field, math.ceil(base + 1.5))))
    rng = rng or random.Random(event["id"] * 104729 + driver_id)
    roll = rng.random()
    gmap = S.grid_map(conn, season_id)
    seat = S.driver_seats(conn, season_id).get(driver_id)
    mate = gmap.get((team_id, 2 if seat and seat[1] == 1 else 1)) if seat else None
    if roll < 0.10 and mate:
        return {"kind": "teammate", "target": None, "rival_team_id": None, "label": TARGET_KINDS["teammate"]}
    slower = next((t for t, r in ranks.items() if r == rank + 1), None)
    if roll < 0.35 and slower and gmap.get((slower, 1)) and gmap.get((slower, 2)):
        team = S.team_map(conn)[slower]["name"]
        return {"kind": "beat_team", "target": None, "rival_team_id": slower,
                "label": TARGET_KINDS["beat_team"].format(team=team)}
    if pos >= field - 1:
        return {"kind": "classified", "target": field, "rival_team_id": None, "label": TARGET_KINDS["classified"]}
    if pos == 10:
        return {"kind": "points", "target": 10, "rival_team_id": None, "label": TARGET_KINDS["points"]}
    return {"kind": "finish", "target": pos, "rival_team_id": None, "label": TARGET_KINDS["finish"].format(n=pos)}


def issue_targets(conn, event_id, notify=False):
    """Set the weekend target for every seated player driver who doesn't have one yet (only before the round
    has results, so a round already under way when targets were switched on is never given one)."""
    if not settings(conn)["targets"]:
        return []
    event = S.get_event(conn, event_id)
    if not event or event["status"] != C.EVENT_NOT_RUN:
        return []
    seats = S.driver_seats(conn, event["season_id"])
    have = {r["driver_id"] for r in conn.execute("SELECT driver_id FROM weekend_targets WHERE event_id = ?", (event_id,))}
    todo = [p for p in S.player_drivers(conn) if p["active"] and p["id"] in seats and p["id"] not in have]
    if not todo:
        return []
    ranks = S.team_strength_ranks(conn, event["season_id"])
    S.weekend_rows(conn, event_id)  # make sure the entry list matches the grid
    linked = {d for d in community_linked(conn)}
    out = []
    for p in todo:
        team_id = seats[p["id"]][0]
        t = plan_target(conn, event, p["id"], team_id, ranks)
        conn.execute("""INSERT INTO weekend_targets(event_id, driver_id, team_id, kind, target, rival_team_id, label,
                        created_at) VALUES(?,?,?,?,?,?,?,?)""",
                     (event_id, p["id"], team_id, t["kind"], t["target"], t["rival_team_id"], t["label"], now_iso()))
        if notify and p["id"] in linked:
            feed.notify(conn, p["id"], f"Your weekend target for R{event['round_number']} {event['name']}: "
                        f"{t['label']}. Accept it on the Control Room"
                        + (" before results can go in." if gate_targets_on(conn) else "."), "dashboard#target")
        out.append(p["id"])
    return out


def community_linked(conn):
    """Player drivers controlled by a league login."""
    return {r["driver_id"] for r in conn.execute(
        "SELECT driver_id FROM career_members WHERE driver_id IS NOT NULL AND role != 'spectator'")}


def gate_targets_on(conn):
    s = settings(conn)
    return s["gates"] and s["gate_targets"] and s["targets"]


def target_for(conn, event_id, driver_id):
    row = conn.execute("SELECT * FROM weekend_targets WHERE event_id = ? AND driver_id = ?",
                       (event_id, driver_id)).fetchone()
    return dict(row) if row else None


def targets_for_event(conn, event_id):
    dmap, tmap = S.driver_map(conn), S.team_map(conn)
    out = []
    for r in conn.execute("SELECT * FROM weekend_targets WHERE event_id = ? ORDER BY driver_id", (event_id,)).fetchall():
        res = _result(conn, event_id, r["driver_id"])
        out.append({**dict(r), "driver": dmap.get(r["driver_id"]), "team": tmap.get(r["team_id"]),
                    "result_status": res["result_status"] if res else None})
    return out


def targets_history(conn, season_id, driver_id):
    rows = conn.execute("""SELECT t.*, e.round_number, e.name AS event_name FROM weekend_targets t
                           JOIN events e ON e.id = t.event_id WHERE e.season_id = ? AND t.driver_id = ?
                           ORDER BY e.round_number DESC""", (season_id, driver_id)).fetchall()
    return [dict(r) for r in rows]


def acknowledge(conn, event_id, driver_id):
    row = target_for(conn, event_id, driver_id)
    if not row:
        raise S.ValidationError("There's no weekend target for you at that round")
    event = S.get_event(conn, event_id)
    if event["status"] == C.EVENT_COMPLETE:
        raise S.ValidationError("That round is already complete")
    if not row["acknowledged_at"]:
        conn.execute("UPDATE weekend_targets SET acknowledged_at = ? WHERE event_id = ? AND driver_id = ?",
                     (now_iso(), event_id, driver_id))
    return row


def _position(r):
    """Finishing order for comparisons: a finisher's position, anyone who started but didn't finish is behind."""
    if not r or r["result_status"] not in C.START_STATUSES:
        return None
    return r["race_position"] if r["result_status"] == C.STATUS_FINISHED and r["race_position"] else 99


def _judge(conn, event, t):
    row = _result(conn, event["id"], t["driver_id"])
    if event["postponed"] or not row or row["result_status"] not in C.START_STATUSES:
        return "Void", "didn't take part"
    if row["result_status"] != C.STATUS_FINISHED or not row["race_position"]:
        return ("Void", "not the driver's fault") if t["excused"] else ("Missed", row["result_status"])
    mine = row["race_position"]
    kind = t["kind"]
    if kind in ("finish", "points", "classified"):
        return ("Hit" if mine <= (t["target"] or 99) else "Missed"), f"P{mine}"
    if kind == "beat_team":
        rivals = [r for r in conn.execute("SELECT * FROM results WHERE event_id = ? AND team_id = ?",
                                          (event["id"], t["rival_team_id"])).fetchall() if r["driver_id"] != t["driver_id"]]
        raced = [_position(r) for r in rivals if _position(r) is not None]
        if not raced:
            return "Void", "they didn't race"
        return ("Hit" if all(mine < p for p in raced) else "Missed"), f"P{mine}"
    mate = _teammate_result(conn, event["id"], row)
    theirs = _position(mate)
    if theirs is None:
        return "Void", "no teammate raced"
    return ("Hit" if mine < theirs else "Missed"), f"P{mine}"


def judge_targets(conn, event_id):
    """Judge (or re-judge after a correction) every weekend target for a completed round. Only the change in
    effect is applied to the relationship, so re-judging never counts a target twice."""
    event = S.get_event(conn, event_id)
    if not event or event["status"] != C.EVENT_COMPLETE:
        return []
    enabled = settings(conn)["targets"]
    out = []
    for t in conn.execute("SELECT * FROM weekend_targets WHERE event_id = ?", (event_id,)).fetchall():
        t = dict(t)
        status, why = _judge(conn, event, t) if enabled else ("Void", "targets switched off")
        effect = {"Hit": C.TARGET_HIT, "Missed": C.TARGET_MISSED}.get(status, 0.0)
        delta = effect - (t["effect"] or 0)
        if delta and conn.execute("SELECT 1 FROM team_relations WHERE season_id = ? AND driver_id = ?",
                                  (event["season_id"], t["driver_id"])).fetchone():
            relations.add_bonus(conn, event["season_id"], t["driver_id"], delta)
        elif delta:
            effect = t["effect"] or 0   # no relationship to move (no seat); keep what was recorded
        conn.execute("UPDATE weekend_targets SET status = ?, effect = ?, judged_at = ? WHERE event_id = ? AND driver_id = ?",
                     (status, effect, now_iso(), event_id, t["driver_id"]))
        if not t["judged_at"] and status in ("Hit", "Missed") and t["team_id"]:
            label = t["label"][:1].lower() + t["label"][1:]
            relations.note(conn, event["season_id"], t["driver_id"], t["team_id"], "good" if status == "Hit" else "concerned",
                           f"R{event['round_number']} {event['name']} target {'hit' if status == 'Hit' else 'missed'} "
                           f"({why}): you were asked to {label}.", notify=False)
        if status != t["status"] or not t["judged_at"]:
            _streak_headline(conn, event, t["driver_id"])
        out.append((t["driver_id"], status))
    return out


def target_streak(conn, season_id, driver_id, upto_round):
    rows = conn.execute("""SELECT t.status FROM weekend_targets t JOIN events e ON e.id = t.event_id
                           WHERE e.season_id = ? AND t.driver_id = ? AND e.round_number <= ? AND e.status = ?
                           ORDER BY e.round_number DESC""", (season_id, driver_id, upto_round, C.EVENT_COMPLETE))
    streak = 0
    for r in rows:
        if r["status"] == "Void":
            continue
        if r["status"] != "Hit":
            break
        streak += 1
    return streak


def _streak_headline(conn, event, driver_id):
    streak = target_streak(conn, event["season_id"], driver_id, event["round_number"])
    if streak not in C.TARGET_STREAKS:
        return
    ref = f"target-streak:{driver_id}:{event['id']}"
    if conn.execute("SELECT 1 FROM news WHERE ref = ?", (ref,)).fetchone():
        return
    name = S.driver_map(conn)[driver_id]["name"]
    seat = S.driver_seats(conn, event["season_id"]).get(driver_id)
    feed.post(conn, event["season_id"], "paddock", f"{name} delivers again: {streak} team targets in a row",
              f"After R{event['round_number']} {event['name']}, {name} has hit every weekend target their team set "
              f"for {streak} straight races.", "news", driver_id=driver_id, team_id=seat[0] if seat else None, ref=ref)


def excuse(conn, event_id, driver_id, excused):
    """Race Master: a DNF/DSQ wasn't the driver's fault (voids the target instead of a miss), or undo that."""
    row = target_for(conn, event_id, driver_id)
    if not row:
        raise S.ValidationError("That driver had no target at this round")
    res = _result(conn, event_id, driver_id)
    if excused and (not res or res["result_status"] not in ("DNF", "DSQ")):
        raise S.ValidationError("Only a DNF or DSQ can be marked as not the driver's fault")
    conn.execute("UPDATE weekend_targets SET excused = ? WHERE event_id = ? AND driver_id = ?",
                 (1 if excused else 0, event_id, driver_id))
    judge_targets(conn, event_id)
    return target_for(conn, event_id, driver_id)
