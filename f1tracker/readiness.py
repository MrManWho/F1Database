"""League Readiness Check (4.0): a read-only maintenance dashboard for the Race Master.

It answers four separate questions, never one blanket "everything is ready":

    weekend       Ready to submit the current weekend
    season_close  Ready to close the season
    next_season   Ready to start the next season
    transition    League data ready for the 4.0 transition

Every check reuses the rules the league already enforces (the round gate, the weekend submission check, the race-time
requirement, the seat/contract states, the season rollover review, the legacy tracking record, the recalculation
preview). It never adds a requirement: something only blocks an action here if the site already refuses that action.

Read-only, by construction
--------------------------
Several of the reused helpers write as a side effect (filling the entry list from the grid, offering weekend
targets, remembering when the press bank started, a recalculation preview's savepoint). So the checks never run on
the league file: the league is copied into memory in one step (SQLite's backup API, which gives a consistent
snapshot even while others are saving), every check runs on that copy, and the copy is thrown away. Notifications or
Discord posts a helper queues while checking are discarded too. Nothing is recalculated, submitted, closed, marked
read, sent, repaired or deleted.

Fast, and honest about what it saw
----------------------------------
* "quick" checks (the season under way, contracts, the tracking record) run every time the page opens.
* "history" checks (every past round, season-end records, the recalculation preview, the Reputation carried between
  seasons) run only when the Race Master asks; their result is kept with a fingerprint of the league's saved records.
  When the fingerprint no longer matches, those results are shown as out of date ("Changes since last check").
* A fingerprint of the copy is compared with the live league after checking, so a change saved while the check ran
  is reported instead of a misleading clean result.
* Only records saved on the server are visible. Results typed on someone's device and not saved yet can't be seen.

Legacy seasons follow tracking.py: anything a season never tracked is "Not applicable", never missing or zero.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from . import constants as C
from . import services as S
from .storage import data_dir, get_meta, now_iso, sanitize_token

# --------------------------------------------------------------------------- vocabulary

TARGETS = {
    "weekend": ("Ready to submit the current weekend", "Results for the next round can be entered and submitted."),
    "season_close": ("Ready to close the season", "Every round is in and nothing from the season is left open."),
    "next_season": ("Ready to start the next season", "Contracts and the next season's grid are settled."),
    "transition": ("League data ready for the 4.0 transition", "The league's records are complete and consistent "
                                                               "under each season's own rules."),
}

# Order matters: the first one that applies wins.
STATUSES = {
    "failed": ("Check failed", "bad"),
    "blocked": ("Blocked", "bad"),
    "not_checked": ("Not checked", "muted"),
    "attention": ("Needs attention", "warn"),
    "ready": ("Ready", "good"),
    "na": ("Not applicable", "muted"),     # nothing to do for this question right now (never shown as green)
}

SEVERITIES = {
    "blocking": ("Blocking", "An existing rule stops an action until this is done."),
    "warning": ("Warning", "Needs attention, but nothing is stopped."),
    "optional": ("Optional", "Optional information. It never lowers readiness."),
}

CATEGORIES = {
    "members": "Members and drivers",
    "weekends": "Race weekends",
    "career": "Career and contracts",
    "migration": "Migration and tracking",
    "derived": "Derived information",
}

SCORE_ROLES = "the Race Master or a Scorekeeper"
COVERAGE_NOTE = ("Checks cover records saved on the server. Results typed on someone's device that haven't been saved "
                 "yet can't be seen here.")

# Tables whose rows are activity rather than league records (they change when people read or chat), and columns
# that change when someone merely opens the league. Left out of the fingerprint so a page view never looks like a change.
_VOLATILE_TABLES = {"notifications", "notification_reads", "news", "audit_log", "audit_events", "deliveries",
                    "checkins", "comments", "reactions", "fan_votes", "predictions", "member_notify", "sqlite_sequence",
                    "sqlite_stat1"}
_VOLATILE_COLUMNS = {"last_active"}
_VOLATILE_META = ("last_opened_at", "calc_snapshot", "calc_snapshot_stale", "calc_seen_", "calc_announce",
                  "press_bank_since", "gate_reminded_", "discord_webhook", "public_key", "recalculated_at")

# Tests can set this to change the live league while a check is running (see test_v400_readiness).
_after_snapshot = None


# --------------------------------------------------------------------------- snapshot and fingerprint

def snapshot(conn):
    """A private, consistent copy of the league in memory. Every check runs on this, never on the league file."""
    copy = sqlite3.connect(":memory:")
    conn.backup(copy)            # one step: SQLite copies a single consistent state, even mid-save elsewhere
    copy.row_factory = sqlite3.Row
    copy.execute("PRAGMA foreign_keys = ON")
    return copy


def fingerprint(conn):
    """A hash of the league's saved records (not page views, chat or notifications). Equal fingerprints mean the
    records a check depends on haven't changed."""
    digest = hashlib.sha256()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    for table in tables:
        if table in _VOLATILE_TABLES or table.startswith("sqlite_"):
            continue
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] not in _VOLATILE_COLUMNS]
        if not cols:
            continue
        digest.update(f"\x00{table}\x00".encode())
        quoted = ", ".join(f'"{c}"' for c in cols)
        for row in conn.execute(f"SELECT {quoted} FROM {table} ORDER BY {quoted}"):
            if table == "meta" and str(row[0]).startswith(_VOLATILE_META):
                continue
            digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()[:20]


# --------------------------------------------------------------------------- the check context

class _Ctx:
    def __init__(self, conn):
        from . import teamlife, weekend
        self.conn = conn
        self.sid = S.current_season_id(conn)
        self.season = S.get_season(conn, self.sid) if self.sid else None
        self.year = self.season["year"] if self.season else None
        self.events = S.events(conn, self.sid) if self.sid else []
        self.next = S.next_incomplete_event(conn, self.sid) if self.sid else None
        self.dmap = S.driver_map(conn)
        self.tmap = S.team_map(conn)
        self.life = teamlife.settings(conn)
        self.weekends_on = weekend.enabled(conn)

    def round_label(self, event):
        return f"Round {event['round_number']}"

    def driver(self, driver_id):
        d = self.dmap.get(driver_id)
        return d["name"] if d else f"Driver #{driver_id}"


def _finding(check, sev, title, *, subject="", detail="", why="", who="", blocks=(), affects=(), link=None,
             link_label="View", season=None, group=None, items=None):
    """One actionable finding. blocks: targets an existing rule stops; affects: targets it lowers to Needs attention."""
    assert sev in SEVERITIES
    return {"check": check.id, "category": check.category, "audience": check.audience, "severity": sev,
            "title": title, "subject": subject, "detail": detail, "why": why, "who": who,
            "blocks": list(blocks), "affects": sorted(set(affects) | set(blocks)), "link": link,
            "link_label": link_label, "season": season, "group": group or f"{check.id}:{title}",
            "items": list(items or [])}


class _Check:
    def __init__(self, cid, category, title, scope, targets, audience, verifies, fn):
        self.id, self.category, self.title, self.scope = cid, category, title, scope
        self.targets, self.audience, self.verifies, self.fn = targets, audience, verifies, fn


CHECKS = []


def check(cid, category, title, scope="quick", targets=(), audience="master", verifies=""):
    def deco(fn):
        CHECKS.append(_Check(cid, category, title, scope, tuple(targets), audience, verifies, fn))
        return fn
    return deco


class NotApplicable(Exception):
    """Raised by a check that doesn't apply to this league (e.g. something the season's rules never tracked)."""


# --------------------------------------------------------------------------- members and drivers

@check("logins", "members", "Player drivers have a login", targets=("weekend",), audience="ops",
       verifies="Seated player drivers this season have a league login linked, or are marked \"No account\" "
                "(the rule that lets the next round's paddock open).")
def _logins(x, me):
    from . import weekend
    if not x.sid:
        raise NotApplicable("No season yet")
    out = []
    missing = weekend.unlinked_players(x.conn, x.sid)
    for p in missing:
        blocking = x.weekends_on and x.next is not None and weekend.phase(x.next) == "upcoming"
        out.append(_finding(
            me, "blocking" if blocking else "warning", f"{p['name']} has no login linked",
            subject=p["name"], season=x.year,
            detail="This player driver is seated but no league login controls them, and \"No account\" isn't ticked.",
            why=("The next round's paddock can't open until every seated player driver has a login or is marked "
                 "\"No account\"." if blocking else "They can't answer press, choose targets or reply to offers."),
            who="Race Master", blocks=("weekend",) if blocking else (), affects=("weekend",),
            link="members#link-logins", link_label="Link a login"))
    return out


@check("assignments", "members", "Members, drivers and teams point at each other correctly", targets=("transition",),
       verifies="No two logins control the same driver, every linked driver exists and is a player driver, and no "
                "record points at a driver, team, season or round that no longer exists (SQLite's foreign key check).")
def _assignments(x, me):
    out = []
    linked = {}
    for r in x.conn.execute("SELECT username, driver_id FROM career_members WHERE driver_id IS NOT NULL "
                            "AND role != 'spectator' ORDER BY username"):
        linked.setdefault(r["driver_id"], []).append(r["username"])
    for driver_id, users in linked.items():
        d = x.dmap.get(driver_id)
        if not d:
            out.append(_finding(me, "warning", "A login is linked to a driver that no longer exists",
                                detail=f"{len(users)} login{'s' if len(users) != 1 else ''} point at a deleted driver.",
                                why="That person has no driver to play.", who="Race Master",
                                affects=("transition",), link="members", link_label="Open Members & roles"))
        elif not d["is_player"]:
            out.append(_finding(me, "warning", f"A login controls {d['name']}, an AI driver", subject=d["name"],
                                detail="Only player drivers are controlled by a login.",
                                why="Round gates, offers and notices only follow player drivers.", who="Race Master",
                                affects=("transition",), link="members", link_label="Open Members & roles"))
        if len(users) > 1:
            name = d["name"] if d else f"Driver #{driver_id}"
            out.append(_finding(me, "warning", f"{len(users)} logins control {name}", subject=name,
                                detail="More than one login is linked to the same driver.",
                                why="Only one of them is asked for that driver's tasks, so the others' answers can clash.",
                                who="Race Master", affects=("transition",), link="members",
                                link_label="Open Members & roles"))
    broken = {}
    for row in x.conn.execute("PRAGMA foreign_key_check"):
        broken.setdefault((row[0], row[2]), 0)
        broken[(row[0], row[2])] += 1
    for (table, parent), n in sorted(broken.items()):
        out.append(_finding(me, "warning", f"{n} {table.replace('_', ' ')} record{'s' if n != 1 else ''} point at a "
                                           f"missing {parent[:-1] if parent.endswith('s') else parent}",
                            detail=f"Records in {table} refer to {parent} rows that no longer exist.",
                            why="Pages that read these records may skip or mislabel them.", who="Site owner",
                            affects=("transition",), link="backups", link_label="Open Backups & data"))
    return out


@check("seats", "members", "This season's seats match the contracts", targets=("next_season",),
       verifies="Each player driver's seat and contract state for the season under way (the same states as Grid & "
                "contracts). Free agents and released drivers are valid career outcomes, not missing data.")
def _seats(x, me):
    from . import seats
    if not x.sid:
        raise NotApplicable("No season yet")
    out = []
    notes = []
    for st in seats.season_states(x.conn, x.sid):
        d = st["driver"]
        if not d["active"]:
            continue
        if st["problem"]:
            out.append(_finding(
                me, "warning", f"{d['name']}: {st['label'].lower()}", subject=d["name"], season=x.year,
                detail=st.get("detail") or "The seat and the contract on record disagree.",
                why="The season rollover and the transfer market read the contract, the race entry list reads the seat.",
                who="Race Master", affects=("next_season",), link="grid#contracts", link_label="Open Grid & contracts"))
        elif st["kind"] in ("free_agent", "released"):
            notes.append(f"{d['name']}: {st['label'].lower()} (a valid career outcome, not a missing seat)")
    vacant = [(t, s["seat"]) for t in S.grid(x.conn, x.sid) for s in t["seats"] if not s["driver"]]
    for team, seat_no in vacant:
        out.append(_finding(me, "warning", f"{team['name']} seat {seat_no} is empty", subject=team["name"],
                            season=x.year, detail="No driver is placed in this seat this season.",
                            why="That car has no entry in the race results.", who="Race Master",
                            affects=("weekend",), link="grid", link_label="Open the grid"))
    return out, notes


# --------------------------------------------------------------------------- race weekends

def _weekend_link(event, stage=None, anchor=None):
    return f"weekend/{event['id']}" + (f"?stage={stage}" if stage else "") + (f"#{anchor}" if anchor else "")


@check("weekend_start", "weekends", "The next round can start", targets=("weekend",), audience="ops",
       verifies="The race-weekend stage of the next round and its round gate (post-race press from the round before, "
                "the weekend target and pre-race press), read exactly as the results page reads them.")
def _weekend_start(x, me):
    from . import gates, weekend
    ev = x.next
    if not ev:
        raise NotApplicable("Every round of this season has been submitted")
    out = []
    label = x.round_label(ev)
    blocked = weekend.results_blocked(x.conn, ev)
    if blocked:
        out.append(_finding(me, "blocking", f"{label} hasn't started yet", subject=f"{label} · {ev['name']}",
                            season=x.year, detail=blocked,
                            why="Results can only go in once the race has started (race weekends are on).",
                            who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", blocks=("weekend",),
                            link=_weekend_link(ev), link_label=f"Open {label}"))
    gate = gates.status(x.conn, ev["id"], issue=False) if not ev.get("lights_at") else {"blocking": False, "players": []}
    if gate.get("blocking"):
        for p in gate["players"]:
            if p["done"]:
                continue
            todo = [i for i in p["checks"] if not i["done"]]
            out.append(_finding(
                me, "blocking", f"{label}: waiting on {p['driver']['name']}", subject=p["driver"]["name"], season=x.year,
                detail="Still to do: " + "; ".join(i["label"] for i in todo) + ".",
                why="The round gate holds the race until every linked player driver has done these.",
                who=f"{p['driver']['name']} (the Race Master can open the round early with a note)",
                blocks=("weekend",), link=_weekend_link(ev, "prepare"), link_label=f"Open {label}"))
    return out


@check("weekend_results", "weekends", "The next round's results pass the submission check", targets=("weekend",),
       audience="ops",
       verifies="The same final review the Submit weekend button runs: every result in, no shared or skipped "
                "positions, statuses that agree with positions, the AI difficulty (or \"Don't track this round\").")
def _weekend_results(x, me):
    from . import weekend
    ev = x.next
    if not ev:
        raise NotApplicable("Every round of this season has been submitted")
    if weekend.results_blocked(x.conn, ev):
        raise NotApplicable("Results go in once the race has started")
    label = x.round_label(ev)
    link = _weekend_link(ev, "sessions")
    if ev["status"] == C.EVENT_NOT_RUN:
        return [_finding(me, "blocking", f"{label}: no results entered yet", subject=f"{label} · {ev['name']}",
                         season=x.year, detail="Nothing has been saved for this round's sessions.",
                         why="Submit weekend needs every driver's result.",
                         who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", blocks=("weekend",), link=link,
                         link_label=f"Enter {label} results")]
    check_ = S.submission_check(x.conn, ev["id"])
    out = []
    for text in check_["blocking"]:
        if text.startswith("Race times missing"):
            continue                               # reported per driver by weekend_timing, with its own link
        out.append(_finding(me, "blocking", f"{label}: {text.split(':')[0]}", subject=f"{label} · {ev['name']}",
                            season=x.year, detail=text, why="Submit weekend refuses while this is open.",
                            who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", blocks=("weekend",), link=link,
                            link_label=f"Open {label} results"))
    for text in check_["warnings"]:
        out.append(_finding(me, "optional", f"{label}: {text}", subject=f"{label} · {ev['name']}", season=x.year,
                            detail=text, why="Submit weekend asks you to confirm this, but allows it.",
                            who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", link=link,
                            link_label=f"Open {label} results"))
    return out


@check("weekend_timing", "weekends", "Race times for the next round", targets=("weekend",), audience="ops",
       verifies="Each player driver's race gap and laps (or the permitted \"Don't submit times\" opt-out) on a tracked "
                "round, as the submission check requires. Rounds before the league's 4.0 update never ask for them.")
def _weekend_timing(x, me):
    from . import ai3, tracking
    ev = x.next
    if not ev:
        raise NotApplicable("Every round of this season has been submitted")
    if not tracking.round_tracked(x.conn, ev, "race_times"):
        raise NotApplicable(tracking.NOT_TRACKED)
    if not ai3.pace_required(x.conn):
        raise NotApplicable("Race times are optional in this league")
    if ev["ai_untracked"]:
        raise NotApplicable("This round's AI difficulty isn't tracked, so no race times are asked for")
    if ev["ai_difficulty"] is None:
        raise NotApplicable("Race times are asked for once the AI difficulty is entered")
    label = x.round_label(ev)
    out = []
    for name, session in ai3.missing_pace(x.conn, ev):
        out.append(_finding(
            me, "blocking", f"{label}: {name}'s {session.lower()} timing is incomplete", subject=name, season=x.year,
            detail="Enter the race gap and laps, or tick the permitted \"Don't submit times\".",
            why="Race times are required on tracked rounds; Submit weekend refuses without them.",
            who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", blocks=("weekend",),
            link=_weekend_link(ev, "sessions", "pace"), link_label=f"Open {label} timing",
            group=f"timing:{ev['id']}:{name}"))
    return out


@check("weekend_weather", "weekends", "Weather for the next round", targets=(), audience="ops",
       verifies="Weather is a record only (it changes no numbers), so a gap is optional information. Rounds from "
                "before weather was tracked are not applicable.")
def _weekend_weather(x, me):
    from . import tracking, weather
    ev = x.next
    if not ev or ev["status"] == C.EVENT_NOT_RUN:
        raise NotApplicable("Weather is recorded once the round has results")
    if not tracking.round_tracked(x.conn, ev, "weather"):
        raise NotApplicable(tracking.NOT_TRACKED)
    have = weather.get(x.conn, ev["id"])
    missing = [weather.SESSIONS[s] for s in weather.sessions_for(ev) if s not in have]
    if not missing:
        return []
    label = x.round_label(ev)
    return [_finding(me, "optional", f"{label}: weather not recorded for {', '.join(missing).lower()}",
                     subject=f"{label} · {ev['name']}", season=x.year,
                     detail="Weather is optional. It feeds the wet and dry statistics only.",
                     why="Without it, this round won't count in anyone's wet or dry record.",
                     who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", link=_weekend_link(ev, "sessions", "weather"),
                     link_label=f"Open {label} weather")]


@check("drafts", "weekends", "Saved results waiting to be submitted", targets=("weekend",), audience="ops",
       verifies="Rounds of the season under way with results saved on the server but not submitted. " + COVERAGE_NOTE)
def _drafts(x, me):
    if not x.sid:
        raise NotApplicable("No season yet")
    out = []
    for ev in x.events:
        if ev["status"] != C.EVENT_IN_PROGRESS:
            continue
        label = x.round_label(ev)
        is_next = x.next and ev["id"] == x.next["id"]
        out.append(_finding(
            me, "warning", f"{label}: results saved but not submitted", subject=f"{label} · {ev['name']}", season=x.year,
            detail="Some results for this round are saved on the server, but the round hasn't been submitted.",
            why=("Standings, press and headlines only follow a submitted round." if is_next else
                 "This round is ahead of the next round to be played, so it's out of order."),
            who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", affects=("weekend",) if not is_next else (),
            link=_weekend_link(ev, "review"), link_label=f"Review {label}"))
    return out


@check("player_tasks", "weekends", "Player drivers' outstanding tasks", targets=(),
       verifies="Growth pledges, team goals, post-race press that no gate requires, and weekend targets not chosen "
                "yet. Counts only: answers are never shown.")
def _player_tasks(x, me):
    from . import relations, teamgoals, teamlife
    if not x.sid:
        raise NotApplicable("No season yet")
    out = []
    linked = teamlife.community_linked(x.conn)
    seats_ = S.driver_seats(x.conn, x.sid)
    gated_press = x.life["gates"] and x.life["gate_press"]
    has_rel = x.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'team_relations'").fetchone()
    for p in S.player_drivers(x.conn):
        if not p["active"] or p["id"] not in linked or p["id"] not in seats_:
            continue
        name = p["name"]
        if has_rel and relations.needs_pledge(x.conn, x.sid, p["id"]):
            out.append(_finding(me, "warning", f"{name} hasn't chosen a growth pledge", subject=name, season=x.year,
                                detail="Their pledge for this season is still open.",
                                why="They're asked to choose it before anything else the next time they open the league.",
                                who=name, link="team-standing", link_label="Open Relationships"))
        if teamgoals.enabled(x.conn):
            team_id = seats_[p["id"]][0]
            if not teamgoals.choice(x.conn, x.sid, team_id) and not teamgoals.locked(x.conn, x.sid, team_id):
                out.append(_finding(me, "warning", f"{name}'s team goal isn't chosen", subject=name, season=x.year,
                                    detail="Their team's goal for this season hasn't been chosen.",
                                    why="They're asked to choose it the next time they open the league.", who=name,
                                    link="team-goals", link_label="Open Team goals"))
        if not gated_press:
            pens = [pen for pen in teamlife.press_pens(x.conn, x.sid, p["id"]) if pen["open"]]
            if pens:
                rounds = ", ".join(f"R{pen['event']['round_number']}" for pen in pens)
                n = sum(pen["open"] for pen in pens)
                out.append(_finding(me, "optional", f"{name} has {n} press question{'s' if n != 1 else ''} open",
                                    subject=name, season=x.year, detail=f"Unanswered post-race press: {rounds}.",
                                    why="Nothing waits on these in this league (press isn't part of the round gate).",
                                    who=name, link=_weekend_link(pens[-1]["event"], "debrief", "press"),
                                    link_label="Open the press"))
    return out


@check("incidents", "weekends", "Incident reports have a ruling", targets=("season_close",),
       verifies="Incident reports still waiting for the Race Master's ruling. They never block a round under the "
                "current rules, so they're a warning, not a blocker.")
def _incidents(x, me):
    rows = x.conn.execute("""SELECT i.id, e.round_number, e.name, s.year FROM incidents i JOIN events e ON e.id = i.event_id
                             JOIN seasons s ON s.id = e.season_id WHERE i.status = 'Open' ORDER BY s.year, e.round_number"""
                          ).fetchall()
    if not rows:
        return []
    rounds = sorted({(r["year"], r["round_number"]) for r in rows})
    return [_finding(me, "warning", f"{len(rows)} incident report{'s' if len(rows) != 1 else ''} to rule on",
                     detail="Reports waiting for a ruling: " + ", ".join(f"{y} R{n}" for y, n in rounds) + ".",
                     why="Doesn't block any round. Drivers are told the outcome once you rule.", who="Race Master",
                     affects=("season_close",), link="incidents", link_label="Open Incidents",
                     items=[f"{r['year']} R{r['round_number']} {r['name']}" for r in rows])]


def _submitted_findings(x, me, seasons, affects):
    from . import ai3
    out = []
    for season in seasons:
        evs = [e for e in S.events(x.conn, season["id"]) if e["status"] == C.EVENT_COMPLETE]
        for ev in evs:
            label = f"{season['year']} Round {ev['round_number']}"
            rows = x.conn.execute("SELECT COUNT(*) FROM results WHERE event_id = ?", (ev["id"],)).fetchone()[0]
            if not rows:
                out.append(_finding(me, "warning", f"{label}: submitted with no results on record",
                                    subject=f"{label} · {ev['name']}", season=season["year"],
                                    detail="The round is marked submitted but has no result rows.",
                                    why="Standings and statistics treat it as if nobody raced.", who="Race Master",
                                    affects=affects, link=_weekend_link(ev), link_label=f"Open {label}"))
                continue
            chk = S.submission_check(x.conn, ev["id"])
            problems = [b for b in chk["blocking"] if not b.startswith(("Race times missing", "Enter the AI difficulty"))]
            if problems:
                out.append(_finding(me, "warning", f"{label}: submitted records are inconsistent",
                                    subject=f"{label} · {ev['name']}", season=season["year"],
                                    detail="; ".join(problems[:4]) + ("…" if len(problems) > 4 else ""),
                                    why="Points and statistics are worked out from these records. Nothing is changed "
                                        "unless you correct the round.",
                                    who="Race Master (corrections are kept in the change record)", affects=affects,
                                    link=_weekend_link(ev, "sessions"), link_label=f"Open {label}"))
            missing_times = ai3.missing_pace(x.conn, ev) if ev["ai_difficulty"] is not None else []
            if missing_times:
                out.append(_finding(me, "optional", f"{label}: race times not entered for "
                                    + ", ".join(sorted({n for n, _s in missing_times})),
                                    subject=f"{label} · {ev['name']}", season=season["year"],
                                    detail="The round was submitted without them.",
                                    why="The AI recommendation simply has less evidence. Nothing else depends on them.",
                                    who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", link=_weekend_link(ev, None, "pace"),
                                    link_label=f"Open {label} timing"))
    return out


@check("submitted_current", "weekends", "This season's submitted rounds are consistent", targets=("season_close",),
       verifies="Every submitted round of the season under way passes the submission check again (shared or skipped "
                "positions, statuses that disagree with positions). Read only: nothing is corrected.")
def _submitted_current(x, me):
    if not x.season:
        raise NotApplicable("No season yet")
    return _submitted_findings(x, me, [x.season], ("season_close", "transition"))


@check("submitted_history", "weekends", "Earlier seasons' submitted rounds are consistent", scope="history",
       targets=("transition",),
       verifies="The same check for every round of every earlier season. Values a season never tracked are skipped.")
def _submitted_history(x, me):
    seasons = [s for s in S.list_seasons(x.conn) if s["id"] != x.sid]
    if not seasons:
        raise NotApplicable("This is the league's first season")
    return _submitted_findings(x, me, seasons, ("transition",))


# --------------------------------------------------------------------------- career and contracts

@check("unfinished_rounds", "career", "Every round of the season is in", targets=("season_close",),
       verifies="Rounds of the season under way that haven't been submitted. Starting the next season with rounds "
                "unplayed is allowed (the rollover page warns), so this is a warning.")
def _unfinished(x, me):
    if not x.sid:
        raise NotApplicable("No season yet")
    left = [e for e in x.events if e["status"] != C.EVENT_COMPLETE]
    if not left:
        return []
    return [_finding(me, "warning", f"{len(left)} of {len(x.events)} rounds still to submit", season=x.year,
                     detail="Not submitted: " + ", ".join(f"R{e['round_number']}" for e in left[:8])
                            + ("…" if len(left) > 8 else "") + ".",
                     why="Starting the next season leaves these rounds unplayed for good.",
                     who=f"{SCORE_ROLES[0].upper()}{SCORE_ROLES[1:]}", affects=("season_close",),
                     link=_weekend_link(left[0]), link_label=f"Open Round {left[0]['round_number']}")]


@check("dismissals", "career", "Mid-season dismissals are decided", targets=("season_close",),
       verifies="Final warnings that were missed and are waiting for the Race Master to confirm or overrule.")
def _dismissals(x, me):
    from . import ultimatums
    if not x.sid:
        raise NotApplicable("No season yet")
    out = []
    for u in ultimatums.awaiting(x.conn, x.sid):
        name = x.driver(u["driver_id"])
        out.append(_finding(me, "warning", f"Dismissal decision waiting: {name}", subject=name, season=x.year,
                            detail=f"Final warning at R{u['round_number']} {u['event_name']} was missed.",
                            why="Their seat for the rest of the season depends on the decision.", who="Race Master",
                            affects=("season_close",), link="grid#dismissals", link_label="Open dismissals"))
    return out


@check("offers", "career", "Contract offers are answered", targets=("next_season",),
       verifies="Offers still waiting for a player driver's answer. Terms are never shown here.")
def _offers(x, me):
    rows = x.conn.execute("""SELECT o.driver_id, w.target_year, COUNT(*) AS n FROM offers o
                             JOIN market_windows w ON w.id = o.window_id WHERE o.status = ? AND w.status = ?
                             GROUP BY o.driver_id, w.target_year""", (C.OFFER_PENDING, C.WINDOW_OPEN)).fetchall()
    out = []
    for r in rows:
        name = x.driver(r["driver_id"])
        out.append(_finding(me, "warning", f"{name} has {r['n']} offer{'s' if r['n'] != 1 else ''} to answer",
                            subject=name, season=r["target_year"],
                            detail=f"For the {r['target_year']} season.",
                            why="Their seat for next season isn't settled until they answer.", who=name,
                            affects=("next_season",), link="market", link_label="Open the transfer market"))
    return out


@check("windows", "career", "Transfer windows", targets=("next_season",),
       verifies="Open transfer windows, and whether each will close by itself (it does once every offer is answered "
                "and every player driver is sorted, the next time the league is opened). The checker never closes one.")
def _windows(x, me):
    from . import market
    out = []
    for w in x.conn.execute("SELECT * FROM market_windows WHERE status = ? ORDER BY id", (C.WINDOW_OPEN,)).fetchall():
        settled = market._window_settled(x.conn, w)
        out.append(_finding(
            me, "optional" if settled else "warning",
            f"{w['kind']} for {w['target_year']} is " + ("ready to close" if settled else "open"), season=w["target_year"],
            detail=("Every offer is answered and every player driver is sorted. It closes by itself the next time "
                    "the league is opened." if settled else "Offers or approaches are still in play."),
            why="Contracts for that season aren't final while the window is open.",
            who="Player drivers (the Race Master can also close it; unanswered offers then expire)",
            affects=() if settled else ("next_season",), link="market", link_label="Open Market administration"))
    return out


@check("rollover", "career", "Next season's contracts and grid", targets=("next_season",),
       verifies="The season rollover review for next season: teams with more signed drivers than seats (the rollover "
                "refuses these), contracts that end and need a decision, and drivers moving or leaving.")
def _rollover(x, me):
    from . import seats
    if not x.sid:
        raise NotApplicable("No season yet")
    latest = S.list_seasons(x.conn)[-1]
    year = latest["year"] + 1
    review = seats.rollover_review(x.conn, latest["id"], year)
    out, notes = [], []
    for c in review["conflicts"]:
        out.append(_finding(me, "blocking", f"{c['team']['name']} has {len(c['drivers'])} drivers signed for {year}",
                            subject=", ".join(d["name"] for d in c["drivers"]), season=year,
                            detail="A team has two seats.",
                            why="Starting the next season is refused until this is resolved.", who="Race Master",
                            blocks=("next_season",), link="grid#contracts", link_label="Open Grid & contracts"))
    for r in review["rows"]:
        name = r["driver"]["name"]
        if r["needs_decision"]:
            out.append(_finding(me, "warning", f"{name}'s contract ends: decision needed for {year}", subject=name,
                                season=year, detail=r["outcome"] + ".",
                                why="The rollover asks you to renew, keep the seat provisionally, or release them.",
                                who="Race Master (or the driver, by signing a new deal first)",
                                affects=("next_season",), link=f"seasons/rollover?year={year}",
                                link_label="Open Start next season"))
        elif r["kind"] in ("free_agent", "released", "inactive"):
            notes.append(f"{name}: {r['outcome']} (a valid outcome, not missing data)")
        else:
            notes.append(f"{name}: {r['outcome']}")
    return out, notes


@check("season_end", "career", "Season-end processing of earlier seasons", scope="history", targets=("transition",),
       verifies="Every earlier season was closed by the rollover: marked complete, each driver's final Reputation "
                "locked, and each growth pledge settled.")
def _season_end(x, me):
    seasons = [s for s in S.list_seasons(x.conn) if s["id"] != x.sid]
    if not seasons:
        raise NotApplicable("This is the league's first season")
    out = []
    has_rel = x.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'team_relations'").fetchone()
    for s in seasons:
        fix = dict(who="Race Master", affects=("transition",), season=s["year"], link=f"review/{s['id']}",
                   link_label=f"Open the {s['year']} review")
        if s["status"] != C.SEASON_COMPLETE:
            out.append(_finding(me, "warning", f"The {s['year']} season isn't marked complete",
                                detail="An earlier season is still marked active.",
                                why="Pages that treat archived seasons as read-only won't protect it.", **fix))
        unlocked = x.conn.execute("SELECT COUNT(*) FROM season_driver_state WHERE season_id = ? AND locked_reputation "
                                  "IS NULL", (s["id"],)).fetchone()[0]
        if unlocked:
            out.append(_finding(me, "warning", f"{s['year']}: final Reputation not locked for {unlocked} driver"
                                               f"{'s' if unlocked != 1 else ''}",
                                detail="Their end-of-season Reputation isn't stored.",
                                why="The next season's starting Reputation is carried from it.", **fix))
        if has_rel:
            open_pledges = x.conn.execute("SELECT COUNT(*) FROM team_relations WHERE season_id = ? AND pledged = 1 "
                                          "AND outcome IS NULL AND released = 0", (s["id"],)).fetchone()[0]
            if open_pledges:
                out.append(_finding(me, "optional", f"{s['year']}: {open_pledges} growth pledge"
                                                    f"{'s' if open_pledges != 1 else ''} never settled",
                                    detail="The rollover settles pledges that had enough rounds to judge; these had none, "
                                           "or were made before pledges were settled.",
                                    why="No Reputation was carried for them. Nothing needs re-entering.", **fix))
    return out


# --------------------------------------------------------------------------- migration and tracking

@check("schema", "migration", "League file is on the current format", targets=("transition",),
       verifies="The league file's format number and the 4.0 tables (change record, tracking record) exist.")
def _schema(x, me):
    from .constants import SCHEMA_VERSION
    version = int(get_meta(x.conn, "schema_version", 0) or 0)
    out = []
    if version < SCHEMA_VERSION:
        out.append(_finding(me, "warning", f"League file format {version} (current is {SCHEMA_VERSION})",
                            detail="The file hasn't been brought up to the current format.",
                            why="It's updated automatically the next time the league is opened.", who="Site owner",
                            affects=("transition",), link="backups", link_label="Open Backups & data"))
    missing = [t for t in ("audit_events", "ai_track_recs") if not x.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone()]
    if missing:
        out.append(_finding(me, "warning", "4.0 tables are missing: " + ", ".join(missing),
                            detail="Part of the 4.0 update didn't complete.",
                            why="Changes and frozen AI recommendations can't be recorded.", who="Site owner",
                            affects=("transition",), link="backups", link_label="Open Backups & data"))
    return out, [f"League file format {version}"]


@check("calc", "migration", "Calculations are up to date for this version", targets=("transition",),
       verifies="The league has answered the Calculation Update and this version's one-time update steps ran. This "
                "is not a comparison with the newest formulas: finished seasons keep the rules they were played under.")
def _calc(x, me):
    from . import engine
    out = []
    if engine.needs_choice(x.conn):
        out.append(_finding(me, "warning", "The Calculation Update hasn't been answered",
                            detail="This league still uses the older calculations.",
                            why="Results are kept; the choice decides how later numbers are worked out.",
                            who="Race Master", affects=("transition",), link="calculation-update",
                            link_label="Open the Calculation Update"))
    version = int(get_meta(x.conn, "calc_version") or 0)
    if version < C.CALC_VERSION:
        out.append(_finding(me, "warning", "This version's update steps haven't run yet",
                            detail=f"Update step {version} of {C.CALC_VERSION}.",
                            why="They run the next time the league is opened; any change then becomes a notice.",
                            who="Automatic", affects=("transition",)))
    notes = [f"Calculations: {engine.label(x.conn, x.sid)}" if x.sid else "No season yet"]
    return out, notes


@check("tracking_record", "migration", "Historical tracking coverage is recorded", targets=("transition",),
       verifies="For a league upgraded from 3.x: the one-time 4.0 record exists, every season that existed at the "
                "upgrade has what it tracked recorded, and starts first seen part-way through a season are confirmed.")
def _tracking_record(x, me):
    from . import tracking
    mig = tracking.migration(x.conn)
    if not mig:
        raise NotApplicable("Created on Paddock Legacy 4.0: every season tracks everything")
    out = []
    stored = {(r["season_id"], r["feature"]) for r in tracking.all_rows(x.conn)}
    expected = {(sid, f) for sid, f, *_ in tracking._plan(x.conn, mig["start_year"], mig["start_round"])}
    gaps = expected - stored
    if gaps:
        years = {s["id"]: s["year"] for s in S.list_seasons(x.conn)}
        out.append(_finding(me, "warning", f"Tracking availability missing for {len(gaps)} season feature"
                                           f"{'s' if len(gaps) != 1 else ''}",
                            detail="Not recorded: " + ", ".join(sorted(f"{years.get(s, '?')} {tracking.FEATURES[f][0].lower()}"
                                                                       for s, f in gaps)[:6]) + ".",
                            why="Those seasons count the features as tracked, so old rounds may look incomplete.",
                            who="Site owner", affects=("transition",), link="legacy-tracking",
                            link_label="Open What each season tracked"))
    for r in tracking.review_items(x.conn):
        label = tracking.FEATURES.get(r["feature"], (r["feature"],))[0]
        out.append(_finding(me, "warning", f"{r['year']}: confirm when {label.lower()} began", season=r["year"],
                            detail=r["detail"] + ".",
                            why="Until confirmed, earlier rounds count as not tracked, so nothing is penalised.",
                            who="Race Master", affects=("transition",), link="legacy-tracking",
                            link_label="Open What each season tracked"))
    start = (f"Round {mig['start_round']} of {mig['start_year']}" if mig["start_round"] > 1
             else f"the {mig['start_year']} season")
    return out, [f"Upgraded {mig['migrated_at'][:10]}; new tracking from {start}"]


@check("notices", "migration", "Change notices and the upgrade notice", targets=(),
       verifies="Change notices each player still has to agree to (they're asked before using the league, but no "
                "league action waits on them), and who hasn't pressed \"Got it\" on the 4.0 notice (information only).")
def _notices(x, me):
    from . import impacts, tracking
    out = []
    for r in x.conn.execute("SELECT username, driver_id FROM career_members WHERE driver_id IS NOT NULL "
                            "AND role != 'spectator' ORDER BY username").fetchall():
        n = len(impacts.pending(x.conn, r["driver_id"], r["username"]))
        if n:
            name = x.driver(r["driver_id"])
            out.append(_finding(me, "warning", f"{name} has {n} change notice{'s' if n != 1 else ''} to agree to",
                                subject=name, detail="Shown to them before anything else when they next open the league.",
                                why="Their own pages wait for it. No league action does.", who=name,
                                link="changes", link_label="Open Changes"))
    mig = tracking.migration(x.conn)
    if mig:
        acked = {a["username"] for a in tracking.acknowledged(x.conn, mig["id"])}
        waiting = [u for u in mig["audience"] if u not in acked]
        if waiting:
            out.append(_finding(me, "optional", f"{len(waiting)} member{'s' if len(waiting) != 1 else ''} haven't "
                                                "seen the 4.0 upgrade notice",
                                detail="They'll see it once the next time they open the league.",
                                why="Information only. Nothing waits on it.", who="Each member",
                                link="legacy-tracking", link_label="Open What each season tracked"))
    return out


@check("history_records", "migration", "Historical records that should exist", scope="history", targets=("transition",),
       verifies="Every season has its rounds and each driver's season record; every submitted round on the "
                "track-aware model has its frozen AI recommendation. Rounds before a feature was tracked are skipped.")
def _history_records(x, me):
    from . import ai_track, engine, tracking
    out = []
    for s in S.list_seasons(x.conn):
        evs = S.events(x.conn, s["id"])
        if not evs:
            out.append(_finding(me, "warning", f"{s['year']}: the season has no rounds", season=s["year"],
                                detail="No calendar is stored for this season.",
                                why="Its standings and review are empty.", who="Race Master",
                                affects=("transition",), link="seasons", link_label="Open Seasons"))
        raced = {r[0] for r in x.conn.execute("SELECT DISTINCT r.driver_id FROM results r JOIN events e ON e.id = r.event_id "
                                              "WHERE e.season_id = ? AND e.status = ?", (s["id"], C.EVENT_COMPLETE))}
        have = {r[0] for r in x.conn.execute("SELECT driver_id FROM season_driver_state WHERE season_id = ?", (s["id"],))}
        gone = raced - have
        if gone:
            out.append(_finding(me, "warning", f"{s['year']}: {len(gone)} driver season record"
                                               f"{'s' if len(gone) != 1 else ''} missing", season=s["year"],
                                detail="Drivers who raced have no starting Reputation stored for the season: "
                                       + ", ".join(sorted(x.driver(d) for d in gone)[:5]) + ".",
                                why="Their Reputation falls back to the baseline for that season.", who="Race Master",
                                affects=("transition",), link="recalculate", link_label="Open Recalculate everything"))
        if ai_track.uses_track(x.conn, s["id"]):
            frozen = {r[0] for r in x.conn.execute("SELECT event_id FROM ai_track_recs WHERE season_id = ?", (s["id"],))}
            lacking = [e for e in evs if e["status"] == C.EVENT_COMPLETE and e["id"] not in frozen
                       and engine.round_v3(x.conn, e) and tracking.round_tracked(x.conn, e, "track_ai")]
            if lacking:
                out.append(_finding(me, "optional", f"{s['year']}: no frozen AI recommendation for "
                                                    + ", ".join(f"R{e['round_number']}" for e in lacking[:6]),
                                    season=s["year"], detail="These rounds were submitted before the recommendation "
                                                             "was stored with each round.",
                                    why="History shows no \"recommended\" value for them. Nothing else depends on it.",
                                    who="Nobody (it isn't recreated, so history stays as it was)"))
    return out


# --------------------------------------------------------------------------- derived information

@check("standings", "derived", "Standings and statistics", targets=(),
       verifies="Standings, Form, Reputation this season and statistics are worked out from the saved results every "
                "time a page opens, so they can't fall behind the results.")
def _standings(x, me):
    return [], ["Worked out from the saved results on every page"]


@check("recalc", "derived", "Stored career values match their records", scope="history", targets=("transition",),
       verifies="Runs Recalculate everything's own preview for the season under way (on the private copy) under that "
                "season's own rules: weekend targets judged with their own terms, relationship extras added up from "
                "the records. Earlier seasons and frozen recommendations are not recalculated.")
def _recalc(x, me):
    from . import impacts, recalc
    if not x.sid:
        raise NotApplicable("No season yet")
    moved = recalc.preview(x.conn, history=False)
    out = []
    for did, rows in moved.items():
        name = x.driver(did)
        out.append(_finding(me, "warning", f"{name}: stored values differ from their records", subject=name,
                            season=x.year,
                            detail="Recalculating would change " + ", ".join(r["label"].lower() for r in rows) + ".",
                            why="Something was saved without the usual follow-up (for example a manual database edit). "
                                "Recalculating sends the driver a change notice to agree to.",
                            who="Race Master", affects=("transition",), link="recalculate",
                            link_label="Open Recalculate everything"))
    return out, [f"{len(impacts.snapshot(x.conn, x.sid, full=False))} player driver(s) compared"]


@check("reputation_chain", "derived", "Reputation carried between seasons", scope="history", targets=("transition",),
       verifies="Each season's starting Reputation equals the previous season's locked final Reputation plus the "
                "pledge and team-goal rewards on record (stored values only; no formula is re-run).")
def _reputation_chain(x, me):
    from . import recalc
    seasons = S.list_seasons(x.conn)
    if len(seasons) < 2:
        raise NotApplicable("This is the league's first season")
    out = []
    for prev, cur in zip(seasons, seasons[1:]):
        rewards = recalc._carried_rewards(x.conn, prev["id"])
        locked = {r["driver_id"]: r["locked_reputation"] for r in x.conn.execute(
            "SELECT driver_id, locked_reputation FROM season_driver_state WHERE season_id = ?", (prev["id"],))}
        off = []
        for r in x.conn.execute("SELECT driver_id, starting_reputation FROM season_driver_state WHERE season_id = ?",
                                (cur["id"],)):
            base = locked.get(r["driver_id"])
            if base is None:
                continue
            expected = max(0.0, min(100.0, base + rewards.get(r["driver_id"], 0)))
            if abs(expected - r["starting_reputation"]) > 0.15:
                off.append(x.driver(r["driver_id"]))
        if off:
            out.append(_finding(me, "warning", f"{cur['year']}: carried Reputation doesn't add up for {len(off)} driver"
                                               f"{'s' if len(off) != 1 else ''}", season=cur["year"],
                                detail=", ".join(sorted(off)[:5]) + (f" and {len(off) - 5} more" if len(off) > 5 else "")
                                       + f" started {cur['year']} with a Reputation that isn't their {prev['year']} "
                                         "final value plus their rewards.",
                                why="Their Reputation in every later season builds on this.", who="Race Master",
                                affects=("transition",), link="recalculate", link_label="Open Recalculate everything"))
    return out


# --------------------------------------------------------------------------- running

def _run_one(chk, x):
    base = {"id": chk.id, "category": chk.category, "title": chk.title, "scope": chk.scope, "targets": list(chk.targets),
            "audience": chk.audience, "verifies": chk.verifies, "findings": [], "notes": [], "error": None}
    try:
        got = chk.fn(x, chk)
    except NotApplicable as na:
        return {**base, "state": "not_applicable", "notes": [str(na)]}
    except Exception as exc:                    # one broken check never hides the others, or claims "Ready"
        import logging
        logging.getLogger(__name__).exception("readiness check %s failed", chk.id)
        return {**base, "state": "failed", "error": f"This check couldn't finish ({type(exc).__name__})."}
    findings, notes = got if isinstance(got, tuple) else (got, [])
    return {**base, "state": "findings" if findings else "passed", "findings": _group(findings), "notes": notes}


def _group(findings):
    """Duplicate findings (same check and title) become one, listing every case."""
    out = {}
    for f in findings:
        key = f["group"]
        if key in out:
            kept = out[key]
            kept["items"] = kept["items"] or [kept["subject"] or kept["detail"]]
            kept["items"].append(f["subject"] or f["detail"])
            kept["count"] += 1
        else:
            out[key] = {**f, "count": 1}
    return list(out.values())


def _quiet_outboxes():
    from . import discord, feed
    return [(box, list(getattr(box, "items", []))) for box in (feed._outbox, discord._outbox)]


def _restore_outboxes(saved):
    for box, items in saved:
        box.items = items       # anything a reused helper queued while checking is dropped: nothing is sent


def run(conn, history=False):
    """Run the checks on a private copy of the league. Returns the raw report (every finding, unfiltered)."""
    saved = _quiet_outboxes()
    copy = None
    try:
        copy = snapshot(conn)
        fp = fingerprint(copy)
        if _after_snapshot:
            _after_snapshot()
        x = _Ctx(copy)
        checks = [_run_one(c, x) for c in CHECKS if history or c.scope == "quick"]
        report = {"checked_at": now_iso(), "fingerprint": fp, "history": history, "checks": checks, "failed": None,
                  "season_id": x.sid, "year": x.year,
                  "next": ({"id": x.next["id"], "label": f"Round {x.next['round_number']} · {x.next['name']}"}
                           if x.next else None)}
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("readiness snapshot failed")
        report = {"checked_at": now_iso(), "fingerprint": None, "history": history, "checks": [],
                  "failed": f"The league couldn't be copied for checking ({type(exc).__name__}).", "season_id": None,
                  "year": None, "next": None}
    finally:
        if copy is not None:
            copy.close()
        _restore_outboxes(saved)
    try:
        report["changed_during"] = bool(report["fingerprint"]) and fingerprint(conn) != report["fingerprint"]
    except Exception:
        report["changed_during"] = True
    return report


# --------------------------------------------------------------------------- the kept full-history result

def _cache_path(token):
    folder = data_dir() / "readiness"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{sanitize_token(token)}.json"


def save_history(token, report, username):
    """Keep the last full check (outside the league file, so keeping it never changes the league)."""
    data = {"checked_at": report["checked_at"], "fingerprint": report["fingerprint"], "by": username,
            "checks": [c for c in report["checks"] if c["scope"] == "history"]}
    path = _cache_path(token)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def load_history(token):
    try:
        return json.loads(Path(_cache_path(token)).read_text())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- what one person sees

def _visible(item, is_master):
    return is_master or item["audience"] == "ops"


def view(report, kept, is_master):
    """Combine the live quick checks with the kept full-history checks, filtered to what this person may see, and
    work out the status of each readiness target."""
    checks = [c for c in report["checks"] if c["scope"] == "quick"]
    live_fp = report["fingerprint"]
    stale_history = False
    history_at = None
    if report["history"]:
        checks += [c for c in report["checks"] if c["scope"] == "history"]
        history_at = report["checked_at"]
    elif kept:
        stale_history = kept.get("fingerprint") != live_fp
        history_at = kept.get("checked_at")
        checks += [{**c, "stale": stale_history} for c in kept.get("checks", [])]
    ran = {c["id"] for c in checks}
    for chk in CHECKS:                        # history checks never run: shown as not checked
        if chk.id not in ran:
            checks.append({"id": chk.id, "category": chk.category, "title": chk.title, "scope": chk.scope,
                           "targets": list(chk.targets), "audience": chk.audience, "verifies": chk.verifies,
                           "findings": [], "notes": [], "error": None, "state": "not_checked"})
    order = {c.id: i for i, c in enumerate(CHECKS)}
    checks.sort(key=lambda c: order.get(c["id"], 99))
    if report.get("changed_during"):
        checks = [{**c, "stale": True} for c in checks]
    hidden = sum(1 for c in checks if not _visible(c, is_master))
    checks = [c for c in checks if _visible(c, is_master)]

    targets = {}
    for key, (label, means) in TARGETS.items():
        mine = [c for c in checks if key in c["targets"]]
        if not is_master and key != "weekend":
            continue                           # a Scorekeeper only answers for the weekend they can submit
        if report.get("failed"):
            status, why = "failed", report["failed"]
        elif any(c["state"] == "failed" for c in mine):
            status, why = "failed", "A check couldn't finish: " + ", ".join(c["title"] for c in mine if c["state"] == "failed")
        elif key == "weekend" and not report.get("next"):
            status, why = "na", "Every round of this season has been submitted. Start the next season to race again."
        elif mine and all(c["state"] == "not_applicable" for c in mine):
            status, why = "na", mine[0]["notes"][0] if mine[0]["notes"] else "Nothing to check."
        elif any(key in f["blocks"] for c in checks if not c.get("stale") for f in c["findings"]):
            status = "blocked"
            why = "; ".join(f["title"] for c in checks if not c.get("stale") for f in c["findings"] if key in f["blocks"])
        elif any(c["state"] == "not_checked" or c.get("stale") for c in mine):
            status = "not_checked"
            why = ("Changes since last check: run again" if any(c.get("stale") for c in mine)
                   else "Needs the full check (Run full check)")
        elif any(key in f["affects"] and f["severity"] != "optional" for c in checks for f in c["findings"]):
            status = "attention"
            why = "; ".join(f["title"] for c in checks for f in c["findings"]
                            if key in f["affects"] and f["severity"] != "optional")
        else:
            status, why = "ready", "All applicable checks passed."
        targets[key] = {"key": key, "label": label, "means": means, "status": status,
                        "status_label": STATUSES[status][0], "tone": STATUSES[status][1], "why": why}

    worst = next((s for s in STATUSES if s != "na" and any(t["status"] == s for t in targets.values())), "not_checked")
    findings = [f for c in checks if not c.get("stale") for f in c["findings"]]
    stale_findings = [f for c in checks if c.get("stale") for f in c["findings"]]
    counts = {s: sum(f["count"] for f in findings if f["severity"] == s) for s in SEVERITIES}
    seasons = sorted({f["season"] for f in findings + stale_findings if f["season"]})
    return {"checks": checks, "targets": targets, "overall": worst, "overall_label": STATUSES[worst][0],
            "overall_tone": STATUSES[worst][1], "counts": counts, "findings": findings,
            "stale_findings": stale_findings, "history_at": history_at, "stale_history": stale_history,
            "changed_during": report.get("changed_during"), "hidden": hidden, "seasons": seasons,
            "failed": report.get("failed"), "checked_at": report["checked_at"],
            "passed": [c for c in checks if c["state"] in ("passed", "not_applicable")],
            "blockers": [f for f in findings if f["severity"] == "blocking"]}


def transition_view(v, conn):
    """The compact 4.0 transition checklist, from checks already run (nothing extra is worked out here)."""
    from . import tracking
    by_id = {c["id"]: c for c in v["checks"]}

    def line(label, ids, ok_text):
        cs = [by_id[i] for i in ids if i in by_id]
        if any(c["state"] == "failed" for c in cs):
            return {"label": label, "tone": "bad", "state": "Check failed", "text": "A check couldn't finish."}
        if any(c["state"] == "not_checked" or c.get("stale") for c in cs):
            return {"label": label, "tone": "muted", "state": "Not checked", "text": "Run the full check."}
        fs = [f for c in cs for f in c["findings"] if f["severity"] != "optional"]
        if any(f["severity"] == "blocking" for f in fs):
            return {"label": label, "tone": "bad", "state": "Blocked", "text": fs[0]["title"], "link": fs[0]["link"]}
        if fs:
            return {"label": label, "tone": "warn", "state": "Needs attention",
                    "text": f"{len(fs)} item{'s' if len(fs) != 1 else ''}: {fs[0]['title']}", "link": fs[0]["link"]}
        if all(c["state"] == "not_applicable" for c in cs) and cs:
            return {"label": label, "tone": "muted", "state": "Not applicable", "text": cs[0]["notes"][0] if cs[0]["notes"] else ""}
        return {"label": label, "tone": "good", "state": "Done", "text": ok_text}

    mig = tracking.migration(conn)
    sid = S.current_season_id(conn)
    evs = S.events(conn, sid) if sid else []
    done = sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE)
    when = ("between seasons" if evs and done == len(evs) else
            "at the start of a season, before Round 1" if evs and not done else
            f"mid-season ({done} of {len(evs)} rounds played)" if evs else "before the first season")
    if mig:
        how = (f"Upgraded from 3.x mid-season: new tracking began at Round {mig['start_round']} of {mig['start_year']}."
               if mig["start_round"] > 1 else f"Upgraded from 3.x between seasons: new tracking began with "
                                               f"{mig['start_year']}.")
    else:
        how = "Created on 4.0, so there's nothing to migrate."
    return {
        "when": when, "how": how,
        "lines": [
            line("Migration status", ("schema", "calc", "tracking_record"), "League file and calculations are current."),
            line("Historical tracking coverage configured", ("tracking_record",), "Every earlier season says what it tracked."),
            line("Historical records preserved", ("history_records", "submitted_history"),
                 "Earlier records are complete; every change since is in the append-only change record."),
            line("Season-end processing", ("season_end", "unfinished_rounds", "incidents", "dismissals"),
                 "Every season so far was closed properly."),
            line("Next-season contracts and grid", ("rollover", "offers", "windows", "seats"),
                 "Finalised: every player driver's next season is settled."),
        ],
    }
