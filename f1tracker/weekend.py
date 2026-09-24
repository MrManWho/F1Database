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
    if not start or datetime.now(timezone.utc) < start:
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
           "can_open": False, "why_not": None, "is_next": _next(conn, event)}
    if key == "upcoming" and out["on"]:
        start = opens_at(event)
        out["opens_at"] = start.isoformat() if start else None
        out["can_open"], out["why_not"] = can_open(conn, event)
    return out
