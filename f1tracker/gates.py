"""Round gates: what has to happen before results can go in for the next round.

A round that hasn't started yet (Not Run) stays locked for result entry until every linked player driver has
  - answered their post-race press questions from the previous completed round (if that round required them), and
  - accepted their weekend target for this round (if targets and that gate are on).
Only player drivers controlled by a league login count; a driver with no login never blocks anything, and
nor does anyone not seated this season. The server enforces this (the results API refuses to save), not just
the page. Scorekeepers can't get past it; the Race Master can open the round with a note, which is kept on
the round and in the Activity Log. Items still open after a bypass stay open and still count when done late.
A round that already has results (In Progress or Complete) is never gated, so corrections are never blocked.
"""

from . import constants as C
from . import services as S
from . import teamlife, weekend
from .storage import get_meta, now_iso, set_meta


def linked_players(conn, season_id):
    """{driver_id: username} for active, seated player drivers that a league login controls."""
    seats = S.driver_seats(conn, season_id)
    dmap = S.driver_map(conn)
    out = {}
    for r in conn.execute("SELECT username, driver_id FROM career_members WHERE driver_id IS NOT NULL "
                          "AND role != 'spectator' ORDER BY username"):
        d = dmap.get(r["driver_id"])
        if d and d["is_player"] and d["active"] and d["id"] in seats:
            out.setdefault(d["id"], r["username"])
    return out


def press_event_for(conn, event):
    """The previous completed round, if its press questions are required before this one."""
    row = conn.execute("SELECT * FROM events WHERE season_id = ? AND status = ? AND round_number < ? "
                       "ORDER BY round_number DESC LIMIT 1",
                       (event["season_id"], C.EVENT_COMPLETE, event["round_number"])).fetchone()
    return dict(row) if row and row["press_required"] else None


def bypass_for(conn, event_id):
    row = conn.execute("SELECT * FROM gate_bypasses WHERE event_id = ?", (event_id,)).fetchone()
    return dict(row) if row else None


def status(conn, event_id, issue=True):
    """The checklist for a round. blocking is True when result entry is locked."""
    event = S.get_event(conn, event_id)
    out = {"event": event, "active": False, "blocking": False, "players": [], "bypass": None, "press_event": None,
           "waiting": 0}
    if not event:
        return out
    out["bypass"] = bypass_for(conn, event_id)
    s = teamlife.settings(conn)
    if not s["gates"] or event["status"] != C.EVENT_NOT_RUN:
        return out
    nxt = S.next_incomplete_event(conn, event["season_id"])
    if nxt and nxt["id"] != event_id:
        # A round further ahead: its checklist is the press from the round before it (not run yet) and its own
        # weekend target (not set yet). Nothing is due, and it is certainly not "ready".
        out["future"] = {"next": nxt}
        return out
    if issue and s["targets"]:
        teamlife.issue_targets(conn, event_id)
    press_event = press_event_for(conn, event) if s["gate_press"] else None
    out["press_event"] = press_event
    check_targets = teamlife.gate_targets_on(conn)
    prerace = s["gate_press"] and weekend.enabled(conn)          # v2.3: pre-race press before lights out
    out["weekend"] = weekend.enabled(conn)
    dmap = S.driver_map(conn)
    for driver_id, username in linked_players(conn, event["season_id"]).items():
        items = []
        if press_event:
            pen = teamlife._pen(conn, press_event, driver_id)
            if pen:
                answered = len(pen["questions"]) - pen["open"]
                items.append({"kind": "press", "done": pen["open"] == 0, "open": pen["open"],
                              "label": f"Press questions from R{press_event['round_number']} "
                                       f"({answered}/{len(pen['questions'])} answered)"})
        if prerace:
            pen = teamlife.prerace_pen(conn, event, driver_id)
            if pen["questions"]:
                answered = len(pen["questions"]) - pen["open"]
                items.append({"kind": "prerace", "done": pen["open"] == 0, "open": pen["open"],
                              "label": (f"Pre-race press ({answered}/{len(pen['questions'])} answered)"
                                        if weekend.phase(event) == "paddock" else "Pre-race press (opens with the paddock)")})
        if check_targets:
            t = teamlife.target_for(conn, event_id, driver_id)
            if t:
                items.append({"kind": "target", "done": bool(t["acknowledged_at"]),
                              "label": "Weekend target accepted" if t["acknowledged_at"] else "Weekend target not accepted yet"})
        if not items:
            continue
        done = all(i["done"] for i in items)
        out["players"].append({"driver": dmap[driver_id], "username": username, "checks": items, "done": done})
        out["waiting"] += 0 if done else 1
    out["active"] = bool(out["players"])
    out["blocking"] = out["waiting"] > 0 and not out["bypass"]
    return out


def blocking(conn, event_id):
    return status(conn, event_id)["blocking"]


_WORDS = {"press": ("press questions", "answer your post-race press questions"),
          "prerace": ("pre-race press", "answer your pre-race press questions"),
          "target": ("weekend target", "accept your weekend target")}


def waiting_text(gate):
    parts = []
    for p in gate["players"]:
        if not p["done"]:
            todo = [_WORDS[i["kind"]][0] for i in p["checks"] if not i["done"]]
            parts.append(f"{p['driver']['name']} ({', '.join(todo)})")
    return "; ".join(parts)


def bypass(conn, event_id, username, note):
    """Race Master: open a gated round anyway. The note is required and kept."""
    note = (note or "").strip()
    if len(note) < C.GATE_NOTE_MIN:
        raise S.ValidationError(f"Add a note of at least {C.GATE_NOTE_MIN} characters saying why the round is "
                                "being opened early")
    gate = status(conn, event_id)
    if not gate["event"]:
        raise S.ValidationError("Round not found")
    if gate["bypass"]:
        raise S.ValidationError("This round has already been opened")
    if not gate["blocking"]:
        raise S.ValidationError("Nothing is waiting, so the round is already open")
    waiting = waiting_text(gate)
    conn.execute("INSERT INTO gate_bypasses(event_id, username, note, waiting, created_at) VALUES(?,?,?,?,?)",
                 (event_id, username, note[:500], waiting[:500], now_iso()))
    return waiting


def my_todo(conn, season_id, driver_id):
    """What this player still has to do before the next round can start (for the banner on every page)."""
    s = teamlife.settings(conn)
    if not s["gates"] or not driver_id:
        return None
    nxt = S.next_incomplete_event(conn, season_id)
    if not nxt or nxt["status"] != C.EVENT_NOT_RUN or bypass_for(conn, nxt["id"]):
        return None
    gate = status(conn, nxt["id"])
    me = next((p for p in gate["players"] if p["driver"]["id"] == driver_id), None)
    if not me or me["done"]:
        return None
    press = next((i["open"] for i in me["checks"] if i["kind"] == "press" and not i["done"]), 0)
    target = any(i["kind"] == "target" and not i["done"] for i in me["checks"])
    prerace = next((i["open"] for i in me["checks"] if i["kind"] == "prerace" and not i["done"]), 0) \
        if weekend.phase(nxt) == "paddock" else 0
    if not (press or target or prerace):
        return None
    return {"event": nxt, "press": press, "target": target, "prerace": prerace, "press_event": gate["press_event"]}


def remind(conn, event_id):
    """Send one reminder per round to each player the round is waiting on. Returns who was reminded."""
    from . import feed
    key = f"gate_reminded_{event_id}"
    if get_meta(conn, key):
        raise S.ValidationError("A reminder has already been sent for this round")
    gate = status(conn, event_id)
    ev = gate["event"]
    names = []
    for p in gate["players"]:
        if p["done"]:
            continue
        todo = " and ".join(_WORDS[i["kind"]][1] for i in p["checks"] if not i["done"])
        feed.notify(conn, p["driver"]["id"], f"Reminder: R{ev['round_number']} {ev['name']} is waiting on you. "
                    f"Please {todo} so the race can start.", f"weekend/{ev['id']}")
        names.append(p["driver"]["name"])
    if not names:
        raise S.ValidationError("Nobody is holding this round up")
    set_meta(conn, key, now_iso())
    return names


def reminded(conn, event_id):
    return bool(get_meta(conn, f"gate_reminded_{event_id}"))
