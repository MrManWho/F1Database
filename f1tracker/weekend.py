"""Race weekends (v2.3): every round goes Upcoming -> Paddock open -> Lights out -> Chequered flag.

    upcoming   the round is on the calendar. Targets, predictions and check-ins as before; no results.
    paddock    opens by itself PADDOCK_LEAD_MINUTES before the scheduled race time (the next time anyone
               opens the league; there's no background timer), or when a Scorekeeper or Race Master presses
               "Open the paddock". Pre-race press questions are asked; everyone can see who's ready.
    live       a Scorekeeper or Race Master pressed "Start the race". This is where the round gate is checked
               (post-race press from the round before, the weekend target and the pre-race press): a
               Scorekeeper can't start while anyone is outstanding, the Race Master can with a note. Predictions
               and pre-race press close. Results can be entered only from here on.
    complete   results submitted: the paddock closes, and the post-race press, summary and headlines follow.

Only the next unplayed round of a season can open. A round that already has results counts as started, so
nothing played before 2.3 is affected. A league can switch race weekends off (League settings); results can
then be entered at any time, as before.
"""

from datetime import datetime, timedelta, timezone

from . import constants as C
from . import feed
from . import services as S
from . import timefmt
from .storage import get_meta, now_iso, set_meta

PADDOCK_LEAD_MINUTES = 60
DEFAULTS = {"race_weekends": "1"}
PHASES = {
    "upcoming": ("Upcoming", "The paddock opens an hour before the race."),
    "paddock": ("Paddock open", "Pre-race press, targets and check-ins. Waiting for lights out."),
    "live": ("Lights out", "The race is on. Results go in once it's over."),
    "complete": ("Chequered flag", "Results are in."),
}


def enabled(conn):
    return get_meta(conn, "race_weekends", DEFAULTS["race_weekends"]) == "1"


def set_enabled(conn, on):
    set_meta(conn, "race_weekends", "1" if on else "0")


def phase(event):
    """The stage a round is at, from what's recorded on it (never from the clock)."""
    if event["status"] == C.EVENT_COMPLETE:
        return "complete"
    if event.get("lights_at") or event["status"] == C.EVENT_IN_PROGRESS:
        return "live"
    if event.get("paddock_at"):
        return "paddock"
    return "upcoming"


def opens_at(event):
    """When the paddock opens by itself (None without a race time)."""
    when = timefmt.parse(event.get("race_at"))
    return when - timedelta(minutes=PADDOCK_LEAD_MINUTES) if when else None


def _next(conn, event):
    nxt = S.next_incomplete_event(conn, event["season_id"])
    return nxt and nxt["id"] == event["id"]


def no_account_ids(conn):
    """Player drivers the Race Master ticked "No account" for (they don't want a login)."""
    return {int(x) for x in (get_meta(conn, "no_account_drivers") or "").split(",") if x}


def set_no_account(conn, driver_id, on):
    ids = no_account_ids(conn)
    ids = ids | {int(driver_id)} if on else ids - {int(driver_id)}
    set_meta(conn, "no_account_drivers", ",".join(str(i) for i in sorted(ids)))


def unlinked_players(conn, season_id):
    """v2.4: seated player drivers with no league login linked and no "No account" tick. While there are any,
    the next round can't be opened."""
    if not season_id:
        return []
    linked = {r["driver_id"] for r in conn.execute(
        "SELECT driver_id FROM career_members WHERE driver_id IS NOT NULL AND role != 'spectator'")}
    seats = S.driver_seats(conn, season_id)
    skip = no_account_ids(conn)
    return [p for p in S.player_drivers(conn) if p["active"] and p["id"] in seats and p["id"] not in linked
            and p["id"] not in skip]


def unlinked_text(players):
    names = ", ".join(p["name"] for p in players)
    return (f"{names} {'has' if len(players) == 1 else 'have'} no login linked. Link one on Members & roles, or tick "
            "\"No account\" there if they don't want one")


def can_open(conn, event):
    """(ok, reason) for opening this round's paddock now."""
    if not enabled(conn):
        return False, "Race weekends are off in this league"
    if phase(event) != "upcoming":
        return False, "The paddock is already open" if phase(event) == "paddock" else "This round has already started"
    if event.get("postponed"):
        return False, "This round is postponed"
    if not _next(conn, event):
        return False, "Only the next round's paddock can open"
    missing = unlinked_players(conn, event["season_id"])
    if missing:
        return False, unlinked_text(missing)
    return True, None


def open_paddock(conn, event_id, username):
    """Open the paddock for the next round. username "auto" when it opened itself before the race."""
    event = S.get_event(conn, event_id)
    if not event:
        raise S.ValidationError("Round not found")
    ok, why = can_open(conn, event)
    if not ok:
        raise S.ValidationError(why)
    conn.execute("UPDATE events SET paddock_at = ?, paddock_by = ? WHERE id = ?", (now_iso(), username, event_id))
    from . import teamlife
    if teamlife.settings(conn)["targets"]:
        teamlife.issue_targets(conn, event_id)
    label = f"R{event['round_number']} {event['name']}"
    when = timefmt.parse(event.get("race_at"))
    feed.post(conn, event["season_id"], "paddock", f"The paddock is open for {label}",
              "Drivers are arriving for pre-race press. " +
              ("Lights out at the scheduled time." if when else "Lights out when the race is started."),
              f"weekend/{event_id}", ref=f"paddock:{event_id}")
    feed.notify(conn, None, f"🏁 The paddock is open for {label}. Answer your pre-race press, accept your weekend "
                f"target and check in.", f"weekend/{event_id}", category="raceday", dedupe=f"paddock:{event_id}")
    return event


def tick(conn, season_id):
    """Open the next round's paddock if its hour has come. Called whenever the league is opened."""
    if not season_id or not enabled(conn):
        return None
    nxt = S.next_incomplete_event(conn, season_id)
    if not nxt or phase(nxt) != "upcoming" or nxt.get("postponed"):
        return None
    start = opens_at(nxt)
    if not start or datetime.now(timezone.utc) < start or not can_open(conn, nxt)[0]:
        return None
    return open_paddock(conn, nxt["id"], "auto")


def start_race(conn, event_id, username, is_master, note=""):
    """Lights out. The round gate is checked here; the Race Master may start anyway with a note."""
    from . import gates
    event = S.get_event(conn, event_id)
    if not event:
        raise S.ValidationError("Round not found")
    if not enabled(conn):
        raise S.ValidationError("Race weekends are off in this league")
    current = phase(event)
    if current == "upcoming":
        raise S.ValidationError("Open the paddock first")
    if current != "paddock":
        raise S.ValidationError("This race has already started")
    gate = gates.status(conn, event_id)
    if gate["blocking"]:
        if not is_master:
            raise S.ValidationError("The race can't start yet. Waiting on: " + gates.waiting_text(gate) +
                                    ". Only the Race Master can start it anyway.")
        gates.bypass(conn, event_id, username, note)
    conn.execute("UPDATE events SET lights_at = ?, lights_by = ? WHERE id = ?", (now_iso(), username, event_id))
    from . import teamlife
    teamlife.lock_unchosen(conn, event_id)          # anyone who didn't choose races for the Standard target
    label = f"R{event['round_number']} {event['name']}"
    feed.post(conn, event["season_id"], "paddock", f"Lights out at {label}!", "The race is under way.",
              f"weekend/{event_id}", ref=f"lights:{event_id}")
    feed.notify(conn, None, f"🚦 Lights out at {label}! Good luck out there.", f"weekend/{event_id}",
                category="raceday", dedupe=f"lights:{event_id}")
    return gate


def results_blocked(conn, event):
    """Why results can't go in yet (None when they can)."""
    if not enabled(conn) or event["status"] != C.EVENT_NOT_RUN or event.get("lights_at"):
        return None
    if phase(event) == "paddock":
        return "The race hasn't started yet. Press Start the race once everyone's ready."
    return "The race hasn't started yet. Open the paddock, then start the race."


def summary(conn, event):
    """What the round page shows about the weekend's stage."""
    key = phase(event)
    label, blurb = PHASES[key]
    out = {"phase": key, "label": label, "blurb": blurb, "on": enabled(conn), "opens_at": None,
           "can_open": False, "why_not": None, "is_next": _next(conn, event),
           "unlinked": unlinked_players(conn, event["season_id"]) if key == "upcoming" else []}
    if key == "upcoming" and out["on"]:
        start = opens_at(event)
        out["opens_at"] = start.isoformat() if start else None
        out["can_open"], out["why_not"] = can_open(conn, event)
    return out


# --------------------------------------------------------------------------- reset (v2.4)

def reset_blocker(conn, event):
    """Why this round can't be reset (None when it can). Only the latest round that has started can be reset."""
    if not event:
        return "Round not found"
    if phase(event) == "upcoming" and not event.get("paddock_at"):
        return "This round hasn't started, so there's nothing to reset"
    if event["season_id"] != S.current_season_id(conn):
        return "Only rounds in the current season can be reset"
    later = conn.execute("""SELECT round_number FROM events WHERE season_id = ? AND round_number > ?
                            AND (status != ? OR paddock_at IS NOT NULL) ORDER BY round_number LIMIT 1""",
                         (event["season_id"], event["round_number"], C.EVENT_NOT_RUN)).fetchone()
    if later:
        return f"R{later['round_number']} is already under way (its paddock opened or it has results). Reset that round first"
    decided = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'ultimatums'").fetchone() and conn.execute(
        "SELECT 1 FROM ultimatums WHERE event_id = ? AND status IN ('Dismissed', 'Overruled')", (event["id"],)).fetchone()
    if decided:
        return "A dismissal decision was made after this round. It can't be reset"
    return None


def reset_preview(conn, event):
    """What a reset would clear, for the confirmation page."""
    eid = event["id"]
    n = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    return {
        "results": n("SELECT COUNT(*) FROM results WHERE event_id = ? AND (race_position IS NOT NULL OR "
                     "qualifying_position IS NOT NULL OR result_status != 'Not Run')", eid),
        "pre_press": n("SELECT COUNT(*) FROM press_answers WHERE event_id = ? AND question LIKE 'pre_%'", eid),
        "post_press": n("SELECT COUNT(*) FROM press_answers WHERE event_id = ? AND question NOT LIKE 'pre_%'", eid),
        "targets": n("SELECT COUNT(*) FROM weekend_targets WHERE event_id = ?", eid),
        "predictions": n("SELECT COUNT(*) FROM predictions WHERE event_id = ?", eid),
        "checkins": n("SELECT COUNT(*) FROM checkins WHERE event_id = ?", eid),
        "fan_votes": n("SELECT COUNT(*) FROM fan_votes WHERE event_id = ?", eid),
        "incidents": n("SELECT COUNT(*) FROM incidents WHERE event_id = ?", eid),
        "orders": n("SELECT COUNT(*) FROM team_orders WHERE event_id = ?", eid),
        "headlines": len(_round_news(conn, event)),
    }


def _round_news(conn, event):
    """News items this round created (results, headlines, press quotes, paddock and lights out)."""
    eid, label = event["id"], f"R{event['round_number']} {event['name']}"
    rows = conn.execute("""SELECT id FROM news WHERE season_id = ? AND (link = ? OR link LIKE ? OR ref IN (?, ?, ?)
                           OR ref LIKE ? OR body LIKE ? OR body LIKE ?)""",
                        (event["season_id"], f"weekend/{eid}", f"weekend/{eid}#%", f"paddock:{eid}", f"lights:{eid}",
                         f"results:{eid}", f"target-streak:%:{eid}", f"% after {label}, %", f"% before {label}, %")).fetchall()
    return [r["id"] for r in rows]


def reset(conn, event_id, username):
    """Race Master: put a round back to Upcoming, as if the weekend never started. Results, pre- and post-race
    press, weekend targets (and their choices), team orders from this round, predictions, check-ins, fan votes,
    incidents, the Race Master override and this round's headlines are removed; every effect they had on team
    relationships is undone. Returns {driver_id: [what changed]} for change notices."""
    from . import recalc, relations, teamlife
    event = S.get_event(conn, event_id)
    why = reset_blocker(conn, event)
    if why:
        raise S.ValidationError(why)
    sid, eid = event["season_id"], event_id
    touched = {}
    for r in conn.execute("SELECT DISTINCT driver_id FROM press_answers WHERE event_id = ?", (eid,)):
        touched.setdefault(r["driver_id"], []).append(f"R{event['round_number']} press answers removed")
    for r in conn.execute("SELECT driver_id FROM weekend_targets WHERE event_id = ?", (eid,)):
        touched.setdefault(r["driver_id"], []).append(f"R{event['round_number']} weekend target removed")
    since = event.get("submitted_at") or event.get("lights_at") or event.get("paddock_at")
    if since:
        # Team messages this round caused (team orders judged, targets hit or missed) came after it was submitted.
        conn.execute("""DELETE FROM team_notes WHERE season_id = ? AND created_at >= ? AND (text LIKE 'You ignored the team order%'
                        OR text LIKE 'Thanks for following the team order%' OR text LIKE ?)""",
                     (sid, since, f"R{event['round_number']} {event['name']} target %"))
    for table in ("press_answers", "weekend_targets", "target_options", "predictions", "checkins", "fan_votes",
                  "incidents", "gate_bypasses", "results"):
        conn.execute(f"DELETE FROM {table} WHERE event_id = ?", (eid,))
    conn.execute("UPDATE team_orders SET status = 'Issued' WHERE event_id = ?", (eid,))
    nxt = conn.execute("SELECT id FROM events WHERE season_id = ? AND round_number > ? ORDER BY round_number LIMIT 1",
                       (sid, event["round_number"])).fetchone()
    if nxt:   # what this round handed out for the next one (targets offered, orders issued) goes too
        for table in ("weekend_targets", "target_options", "team_orders"):
            conn.execute(f"DELETE FROM {table} WHERE event_id = ?", (nxt["id"],))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'ultimatums'").fetchone():
        conn.execute("DELETE FROM ultimatums WHERE event_id = ? AND status IN ('Issued', 'Awaiting decision', 'Met', 'Void')",
                     (eid,))
    for nid in _round_news(conn, event):
        conn.execute("DELETE FROM news WHERE id = ?", (nid,))
    conn.execute("DELETE FROM notifications WHERE link LIKE ? OR ref IN (?, ?)",
                 (f"weekend/{eid}%", f"results:{eid}", f"paddock:{eid}"))
    for key in (f"gate_reminded_{eid}", f"targets_removed_{eid}"):
        conn.execute("DELETE FROM meta WHERE key = ?", (key,))
    conn.execute("""UPDATE events SET status = ?, ai_difficulty = NULL, ai_untracked = 0, submitted_at = NULL,
                    press_required = 0, paddock_at = NULL, paddock_by = NULL, lights_at = NULL, lights_by = NULL,
                    revision = revision + 1 WHERE id = ?""", (C.EVENT_NOT_RUN, eid))
    S.weekend_rows(conn, eid)   # a fresh, empty entry list
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'team_relations'").fetchone():
        recalc.rebuild_bonus(conn, sid)
        relations.review(conn, sid)
    return touched
