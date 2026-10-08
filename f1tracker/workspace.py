"""4.0 Race Weekend workspace: one place for a round, in four stages (Prepare, Sessions, Review & submit, Debrief).

Everything here is worked out from what's saved on the round (results, the weekend stage, gates, targets, press),
never from which page someone last visited, so the workspace always opens at the right place and shows the same
progress to everyone. Nothing in this module changes a number: it only reads.
"""

from . import constants as C
from . import services as S

STAGES = (("prepare", "Prepare"), ("sessions", "Sessions"), ("review", "Review & submit"), ("debrief", "Debrief"))
SESSION_LABELS = {"q": "Qualifying", "s": "Sprint", "r": "Race"}
INCIDENT_SESSION = {"q": "qualifying", "s": "sprint", "r": "race"}


def sessions(event, rows):
    """Qualifying, [Sprint], Race: how much of each is entered (from the saved results)."""
    total = len(rows)
    out = []
    keys = ["q"] + (["s"] if event["is_sprint"] else []) + ["r"]
    for key in keys:
        if key == "q":
            entered = sum(1 for r in rows if r["qualifying_position"])
        elif key == "s":
            entered = sum(1 for r in rows if r["sprint_status"] != C.STATUS_NOT_RUN)
        else:
            entered = sum(1 for r in rows if r["result_status"] != C.STATUS_NOT_RUN)
        done = bool(total) and entered >= total
        out.append({"key": key, "label": SESSION_LABELS[key], "entered": entered, "total": total, "done": done,
                    "incident_session": INCIDENT_SESSION[key],
                    "state": "done" if done or event["status"] == C.EVENT_COMPLETE else
                             "current" if entered else "upcoming"})
    return out


def fix_target(message):
    """Where to fix a checklist message: (session key or None, element id or None)."""
    m = message.lower()
    if "race times" in m:
        # 4.0: each race session has its own Race times section; Sprint-only gaps go to the Sprint's
        return ("s", "pace-sprint") if "(sprint)" in m and "(grand prix)" not in m else ("r", "pace")
    if "ai difficulty" in m:
        return "r", "ai-difficulty"
    if "weekend notes" in m:
        return "r", "event-notes"
    if "sprint" in m:
        return "s", "entry-table"
    if "qualifying" in m:
        return "q", "entry-table"
    return "r", "entry-table"


def checklist(conn, event):
    """The server's own pre-submission check with a "Fix" target on each line."""
    check = S.submission_check(conn, event["id"])
    for key in ("blocking", "warnings"):
        check[key] = [{"text": t, "session": fix_target(t)[0], "anchor": fix_target(t)[1]} for t in check[key]]
    return check


def my_tasks(conn, ctx, event, wk, gate, my_target, hub):
    """This driver's own jobs for the round, required ones first. Each has the stage and anchor to do it at."""
    from . import gates, teamlife
    me = ctx.get("my_driver")
    if not me or ctx.get("is_spectator"):
        return []
    life = ctx["team_life"]
    tasks = []
    open_ = event["status"] == C.EVENT_NOT_RUN and not event.get("lights_at")
    if my_target:
        chosen = my_target.get("chosen")
        needs = my_target["open"] and not chosen
        tasks.append({"key": "target", "text": "Choose your weekend target", "stage": "prepare", "anchor": "target",
                      "done": not needs, "required": bool(life.get("gates") and life.get("gate_targets")),
                      "closed": not my_target["open"] and not chosen})
    pen = (wk or {}).get("pen") if wk else None
    if pen and not _legacy_ok(conn, event, "prerace_press", pen):
        pen = None                                # pre-race press wasn't part of this round's rules
    if pen and pen.get("questions"):
        waiting = (wk or {}).get("phase") == "paddock" and pen.get("open")
        tasks.append({"key": "prerace", "text": "Answer your pre-race press", "stage": "prepare", "anchor": "prerace",
                      "done": not waiting, "required": bool(life.get("gates") and life.get("gate_press")),
                      "closed": (wk or {}).get("phase") != "paddock" and bool(pen.get("open"))})
    if open_:
        todo = gates.my_todo(conn, event["season_id"], me["id"])
        if todo and todo["press"] and todo["event"]["id"] == event["id"] and todo.get("press_event"):
            pe = todo["press_event"]
            tasks.append({"key": "press", "text": f"Answer your R{pe['round_number']} post-race press",
                          "event_id": pe["id"], "stage": "debrief", "anchor": "press", "done": False, "required": True})
    if hub and hub.get("checkins") is not None and open_:
        tasks.append({"key": "checkin", "text": "Check in for the race", "stage": "prepare", "anchor": "race-night",
                      "done": bool(hub.get("my_checkin")), "required": False})
    if hub and hub.get("picks_locked") is False and hub.get("entrants"):
        tasks.append({"key": "picks", "text": "Make your predictions", "stage": "prepare", "anchor": "race-night",
                      "done": bool(hub.get("my_picks")), "required": False})
    if event["status"] == C.EVENT_COMPLETE:
        pen = press_pen_for(conn, event, me["id"])
        if pen and not _legacy_ok(conn, event, "press", pen):
            pen = None                            # post-race press wasn't part of this round's rules
        if pen and pen["questions"]:
            tasks.append({"key": "postpress", "text": "Answer your post-race press", "stage": "debrief",
                          "anchor": "press", "done": not pen["open"], "required": bool(event.get("press_required"))
                          and bool(life.get("gates") and life.get("gate_press"))})
    tasks.sort(key=lambda t: (t["done"], not t["required"]))
    return tasks


def _legacy_ok(conn, event, feature, pen):
    """A press pen belongs on this round: the feature was tracked then, or something was answered anyway (stored
    answers always show)."""
    from . import tracking
    if tracking.round_tracked(conn, event, feature):
        return True
    return any(q.get("answered") for q in pen.get("questions") or [])


def press_pen_for(conn, event, driver_id):
    """This round's post-race press for one driver (answered or not), or None."""
    from . import teamlife
    return teamlife._pen(conn, dict(event), driver_id)


def readiness(ctx, tasks, gate):
    mine = [t for t in tasks if t["required"] and t["stage"] == "prepare" and not t.get("closed")]
    personal = {"has_tasks": bool(mine), "ready": all(t["done"] for t in mine), "left": [t for t in mine if not t["done"]]}
    league = None
    if gate and gate.get("active"):
        players = gate["players"]
        league = {"ready": sum(1 for p in players if p["done"]), "total": len(players),
                  "waiting": [p["driver"]["name"] for p in players if not p["done"]],
                  "bypass": bool(gate.get("bypass"))}
    return {"personal": personal, "league": league}


def build(conn, ctx, event, rows, wk, gate, my_target, hub, requested=None, requested_session=None, pace_missing=None):
    """Everything the workspace needs to decide where it opens and what state each stage is in. pace_missing: the
    players' race times still needed (ai3.missing_pace), which keep Sessions open until they're in."""
    phase = wk["phase"] if wk and wk.get("on") else (
        "complete" if event["status"] == C.EVENT_COMPLETE else "live" if event["status"] == C.EVENT_IN_PROGRESS
        or any(r["result_status"] != C.STATUS_NOT_RUN for r in rows) else "upcoming")
    complete = event["status"] == C.EVENT_COMPLETE
    weekends_on = bool(wk and wk.get("on"))
    results_open = complete or phase == "live" or not weekends_on
    gated = bool(gate and gate.get("blocking")) and not event.get("lights_at")
    sess = sessions(event, rows)
    all_entered = all(s["done"] for s in sess)
    tasks = my_tasks(conn, ctx, event, wk, gate, my_target, hub)
    check = checklist(conn, event) if ctx["can_run"] and not complete and results_open else None

    states = {}
    prepare_left = [t for t in tasks if t["stage"] == "prepare" and t["required"] and not t["done"] and not t.get("closed")]
    states["prepare"] = ("done" if phase in ("live", "complete") and not prepare_left else
                         "attention" if prepare_left else "current" if phase in ("upcoming", "paddock") else "done")
    if complete or (all_entered and not pace_missing):
        states["sessions"] = "done"
    elif all_entered:
        states["sessions"] = "attention"          # results are in, race times aren't
    elif results_open and not gated:
        states["sessions"] = "current"
    else:
        states["sessions"] = "upcoming"
    if complete:
        states["review"] = "done"
    elif all_entered and check is not None:
        states["review"] = "attention" if check["blocking"] else "current"
    else:
        states["review"] = "upcoming"
    press_left = [t for t in tasks if t["stage"] == "debrief" and not t["done"] and t["required"]]
    # a submitted round is finished: Debrief reads Complete (or flags press still owed), never "In progress"
    states["debrief"] = ("attention" if complete and press_left else "done" if complete else "upcoming")

    if complete:
        default = "debrief"
    elif results_open and not gated and (phase == "live" or not weekends_on) and (
            ctx["can_run"] or any(s["entered"] for s in sess)):
        default = "review" if all_entered and ctx["can_run"] else "sessions"
    else:
        default = "prepare"
    stage = requested if requested in dict(STAGES) else default

    active_session = requested_session if requested_session in [s["key"] for s in sess] else \
        next((s["key"] for s in sess if not s["done"]), sess[-1]["key"])
    for s in sess:
        s["active"] = s["key"] == active_session

    return {"stages": [{"key": k, "label": label, "number": i + 1, "state": states[k], "on": k == stage}
                       for i, (k, label) in enumerate(STAGES)],
            "stage": stage, "default": default, "phase": phase, "complete": complete, "results_open": results_open,
            "gated": gated, "sessions": sess, "active_session": active_session, "all_entered": all_entered,
            "tasks": tasks, "readiness": readiness(ctx, tasks, gate), "check": check,
            "next_stage": _neighbour(stage, 1), "prev_stage": _neighbour(stage, -1)}


def _neighbour(stage, step):
    keys = [k for k, _ in STAGES]
    i = keys.index(stage) + step
    return keys[i] if 0 <= i < len(keys) else None


def debrief(conn, ctx, event):
    """The finished round from this driver's point of view (only their own career numbers)."""
    from . import insights
    if event["status"] != C.EVENT_COMPLETE:
        return None
    summary = insights.race_summary(conn, event["id"])
    me = ctx.get("my_driver")
    mine = next((h for h in summary["humans"] if me and h["driver"]["id"] == me["id"]), None)
    pen = press_pen_for(conn, event, me["id"]) if me and not ctx.get("is_spectator") else None
    if pen and not _legacy_ok(conn, event, "press", pen):
        pen = None
    wdc_me = next((w for w in summary["wdc"] if me and w["row"]["driver"]["id"] == me["id"]), None)
    return {"summary": summary, "mine": mine, "pen": pen, "wdc_me": wdc_me}
