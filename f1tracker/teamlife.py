"""Life inside a team between races: the post-race press pen and team orders.

Press: after each race every player driver who raced gets two questions picked from how their weekend
went. Each answer nudges the relationship with their team (a small, capped bonus) and some make headlines.
Only the latest completed race has an open press pen; unanswered questions simply lapse.

Team orders: after a race, a player driver on a No. 2 contract may be told to let their teammate through
at the next race. The order is judged from the finishing order: finishing ahead of the teammate means the
order was ignored (unless either of them didn't finish, which voids it).
"""

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
    if not event:
        return None
    questions = questions_for(conn, event["id"], driver_id)
    if not questions:
        return None
    answered = {r["question"]: r["answer"] for r in conn.execute(
        "SELECT * FROM press_answers WHERE event_id = ? AND driver_id = ?", (event["id"], driver_id))}
    for q in questions:
        q["answered"] = answered.get(q["key"])
    return {"event": event, "questions": questions, "open": sum(1 for q in questions if not q["answered"])}


def answer(conn, event_id, driver_id, question, choice):
    event = S.get_event(conn, event_id)
    if not event or event["status"] != C.EVENT_COMPLETE:
        raise S.ValidationError("That press pen isn't open")
    latest = latest_press_event(conn, event["season_id"])
    if not latest or latest["id"] != event_id:
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


# --------------------------------------------------------------------------- team orders

def _teammate(conn, season_id, driver_id):
    seat = S.driver_seats(conn, season_id).get(driver_id)
    if not seat:
        return None, None
    return seat[0], S.grid_map(conn, season_id).get((seat[0], 2 if seat[1] == 1 else 1))


def issue_orders(conn, season_id, rng=None):
    """Before the next race, teams may tell a No. 2 player driver to give way to their teammate."""
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
        relations.note(conn, season_id, rel["driver_id"], team_id, "concerned",
                       f"Team order for R{nxt['round_number']} {nxt['name']}: if you're racing {name}, let them through. "
                       "Finishing ahead of them means you ignored it.")
        issued.append(rel["driver_id"])
    return issued


def resolve_orders(conn, event_id):
    """After the race: was the order followed? Judged from the finishing order."""
    event = S.get_event(conn, event_id)
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
        if rel and status != "Void":
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
    event = S.get_event(conn, event_id)
    resolve_orders(conn, event_id)
    relations.review(conn, event["season_id"])
    issue_orders(conn, event["season_id"])
    for rel in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?", (event["season_id"],)).fetchall():
        if questions_for(conn, event_id, rel["driver_id"]):
            feed.notify(conn, rel["driver_id"], f"The press want a word after R{event['round_number']} {event['name']}.",
                        "dashboard#press")
