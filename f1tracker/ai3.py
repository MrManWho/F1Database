"""AI difficulty tracker, Calculation Version 3 (Paddock Legacy 2.5).

Goal: keep each player close to the real AI drivers in their own career, without making the game easy, and notice
when a player "finishes where the car should" but is half a second a lap slower than the comparable AI.

Evidence per player per session (Grand Prix, and the Sprint as its own half-weight sample if Sprints are tracked):

  benchmark, in order: the AI teammate in the same car; AI drivers of the teams one place either side in car
  strength (confidence x0.8); the car's expected finish; the whole field only as a fallback.

  finish     = clamp((E - finish) / 8, -1, 1)          E = expected finish of the car (stored rank for that round)
  quali pos  = clamp((E - qualifying) / 8, -1, 1)      (Grand Prix only)
  teammate   = clamp((benchmark finish - finish) / 10, -1, 1)
  race pace  = clamp(-(race gap / laps) / 0.60, -1, 1) (optional lap-time data; + gap = behind)
  quali pace = clamp(-(my time - benchmark time) / 0.80, -1, 1)

  score = 0.20 finish + 0.10 quali pos + 0.25 teammate + 0.30 race pace + 0.15 quali pace, re-normalised over the
  parts that exist. Championship points are never used.

Sessions are left out for Don't track, not run, cancelled, a DNF, and flags (damage, major penalty, mechanical,
disconnection); weather, safety-car and strategy distortion count 25%, traffic 75%. The Race Master can mark a
left-out session "representative" to keep it at half weight.

The recommendation uses the ten most recent usable sessions (weight 0.5^(age/2.5)), a +/-0.08 dead band, per-player
comfortable levels, a smaller step when players disagree, step limits by how much evidence there is, and damping when
it would reverse direction. Every constant is in constants.py (AI_*).
"""

import json
import math

from . import calc3
from . import constants as C
from . import engine as E
from .storage import now_iso


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def soft(score):
    return math.copysign(max(0.0, abs(score) - C.DIFF_DEADBAND), score)


def parse_time(value):
    """Seconds from "1:23.456", "83.456" or "83,456"; None for blank; ValueError for nonsense."""
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("Times look like 1:23.456")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    if total <= 0 or total > 10000:
        raise ValueError("Times look like 1:23.456")
    return round(total, 3)


def format_time(seconds):
    if seconds is None:
        return ""
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}" if m else f"{s:.3f}"


# --------------------------------------------------------------------------- pace inputs

def pace_input(conn, event_id, driver_id, session="gp"):
    row = conn.execute("SELECT * FROM pace_inputs WHERE event_id = ? AND driver_id = ? AND session = ?",
                       (event_id, driver_id, session)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["flag_list"] = [f for f in (d["flags"] or "").split(",") if f]
    return d


def save_pace_input(conn, event_id, driver_id, session, form, username):
    """Store the optional lap-time evidence for one player and session. Blank fields are simply not used."""
    if session not in ("gp", "sprint"):
        raise ValueError("Unknown session")
    try:
        quali = parse_time(form.get("quali_time"))
        mate_q = parse_time(form.get("mate_quali_time"))
        comp_q = parse_time(form.get("comp_quali_time"))
    except ValueError:
        raise ValueError("Qualifying times look like 1:23.456")
    gap_text = (form.get("race_gap") or "").strip().replace(",", ".")
    try:
        gap = float(gap_text) if gap_text else None
        laps = int(form.get("laps")) if (form.get("laps") or "").strip() else None
    except ValueError:
        raise ValueError("The race gap is seconds (e.g. 12.4, or -3 if you finished ahead) and laps a whole number")
    if laps is not None and not 1 <= laps <= 200:
        raise ValueError("Completed laps must be between 1 and 200")
    if gap is not None and abs(gap) > 600:
        raise ValueError("A race gap over ten minutes isn't a useful comparison")
    comp = form.get("comp_driver_id")
    comp = int(comp) if comp and str(comp).isdigit() else None
    flags = ",".join(f for f in C.AI_FLAGS if form.get(f"flag_{f}"))
    rep = form.get("representative")
    rep = None if rep in (None, "", "auto") else int(rep == "1")
    conn.execute("""INSERT INTO pace_inputs(event_id, driver_id, session, quali_time, mate_quali_time, comp_driver_id,
                    comp_quali_time, race_gap, gap_to, laps, representative, flags, untracked, updated_by, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id, driver_id, session) DO UPDATE SET
                    quali_time = excluded.quali_time, mate_quali_time = excluded.mate_quali_time,
                    comp_driver_id = excluded.comp_driver_id, comp_quali_time = excluded.comp_quali_time,
                    race_gap = excluded.race_gap, gap_to = excluded.gap_to, laps = excluded.laps,
                    representative = excluded.representative, flags = excluded.flags, untracked = excluded.untracked,
                    updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
                 (event_id, driver_id, session, quali, mate_q, comp, comp_q, gap,
                  (form.get("gap_to") or "teammate")[:20], laps, rep, flags, int(bool(form.get("untracked"))),
                  username, now_iso()))


# --------------------------------------------------------------------------- scoring one session

def _session_weight(p, result_ok):
    """(weight, reasons) from the flags and the Race Master's "representative" choice."""
    reasons = []
    weight = 1.0
    if p:
        for f in p["flag_list"]:
            label, w = C.AI_FLAGS.get(f, (f, 1.0))
            if w < weight:
                weight = w
            reasons.append(label.lower())
    if not result_ok:
        weight, reasons = 0.0, reasons + ["didn't finish"]
    if p and p.get("representative") == 0:
        return 0.0, reasons + ["marked unrepresentative by the Race Master"]
    if weight == 0.0 and p and p.get("representative") == 1:
        weight = C.AI_REPRESENTATIVE_WEIGHT          # the Race Master says it shows the level is too hard/easy
    return weight, reasons


def session_evidence(conn, event, r, rows, ranks, session, n_teams):
    """Score one player's session. Returns a dict (score None if the session can't be used)."""
    p = pace_input(conn, event["id"], r["driver_id"], session)
    field = len(rows) or C.GRID_SIZE
    if session == "gp":
        status, pos, quali = r["result_status"], r["race_position"], r["qualifying_position"]
    else:
        status, pos, quali = r["sprint_status"], r["sprint_position"], None
    out = {"driver_id": r["driver_id"], "event_id": event["id"], "session": session, "position": pos,
           "round": event["round_number"], "year": event.get("year"), "difficulty": event["ai_difficulty"],
           "flags": p["flag_list"] if p else [], "excluded": None}
    if p and p["untracked"]:
        out.update(score=None, excluded="marked \"Do not track this session\"")
        return out
    ok = status in C.CLASSIFIED_STATUSES and bool(pos)
    weight, reasons = _session_weight(p, ok)
    if weight == 0.0:
        out.update(score=None, excluded=", ".join(reasons) or "not usable")
        return out
    rank = ranks.get(r["team_id"])
    expected = calc3.expected_finish(rank, field, n_teams) if rank else (field + 1) / 2
    parts = {"finish": _clamp((expected - pos) / C.DIFF_PLACES)}
    if quali:
        parts["quali_pos"] = _clamp((expected - quali) / C.DIFF_PLACES)
    pos_key, status_key = ("race_position", "result_status") if session == "gp" else ("sprint_position", "sprint_status")

    def classified_ai(rr):
        return not rr["is_player"] and rr[status_key] in C.CLASSIFIED_STATUSES and rr[pos_key]
    mate = next((m for m in rows if m["team_id"] == r["team_id"] and m["driver_id"] != r["driver_id"]
                 and classified_ai(m)), None)
    confidence = 1.0
    bench_name = None
    if mate:
        bench = mate[pos_key]
        bench_name = "your AI teammate"
    else:
        near = [t for t, k in ranks.items() if rank and abs(k - rank) == 1]
        others = [m[pos_key] for m in rows if m["team_id"] in near and classified_ai(m)]
        bench = sum(others) / len(others) if others else None
        confidence = C.AI_NO_MATE_CONFIDENCE
        bench_name = "comparable AI cars" if others else None
    if bench is not None:
        parts["teammate"] = _clamp((bench - pos) / 10)
        out["places_vs_benchmark"] = round(bench - pos, 1)
    gap_per_lap = None
    if p and p["race_gap"] is not None and p["laps"]:
        gap_per_lap = p["race_gap"] / p["laps"]
        parts["race_pace"] = _clamp(-gap_per_lap / C.AI_RACE_SCALE)
    q_gap = None
    if p and p["quali_time"]:
        bench_time = p["mate_quali_time"] or p["comp_quali_time"]
        if bench_time:
            q_gap = p["quali_time"] - bench_time
            parts["quali_pace"] = _clamp(-q_gap / C.AI_QUALI_SCALE)
    total_w = sum(C.AI_WEIGHTS[k] for k in parts)
    score = sum(C.AI_WEIGHTS[k] * v for k, v in parts.items()) / total_w
    distorted = bool(reasons)
    extreme = (gap_per_lap is not None and abs(gap_per_lap) > C.AI_EXTREME_GAP and not distorted and any(
        abs(parts.get(k, 0)) >= 0.3 and math.copysign(1, parts[k]) == math.copysign(1, -gap_per_lap)
        for k in ("quali_pace", "teammate", "finish") if k in parts))
    out.update(score=round(score, 3), parts={k: round(v, 3) for k, v in parts.items()}, expected=round(expected, 1),
               weight=weight * confidence * (C.AI_SPRINT_WEIGHT if session == "sprint" else 1.0),
               gap_per_lap=None if gap_per_lap is None else round(gap_per_lap, 3),
               quali_gap=None if q_gap is None else round(q_gap, 3), benchmark=bench_name, extreme=extreme,
               reduced=reasons)
    return out


# --------------------------------------------------------------------------- history

def _sprints_tracked(conn):
    row = conn.execute("SELECT value FROM meta WHERE key = 'difficulty_sprints'").fetchone()
    return (row[0] if row else "1") == "1"


def history(conn, before=None):
    """Every tracked completed round across seasons (oldest first), with each player's session evidence.

    Rounds judged by engine 2 (older seasons, or before a Future-only cutoff) keep their engine 2 score as legacy
    evidence, so the new tracker takes over gradually."""
    from . import services as S
    events = conn.execute("""SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                             WHERE e.status = ? AND e.ai_difficulty IS NOT NULL AND e.cancelled = 0 AND e.postponed = 0
                             ORDER BY s.year, e.round_number""", (C.EVENT_COMPLETE,)).fetchall()
    n_teams = conn.execute("SELECT COUNT(*) FROM teams WHERE active = 1").fetchone()[0] or 11
    sprints = _sprints_tracked(conn)
    out = []
    legacy_ranks = {}
    for e in events:
        e = dict(e)
        if before and (e["year"], e["round_number"]) >= before:
            continue
        if not E.round_v3(conn, e):
            if e["season_id"] not in legacy_ranks:
                legacy_ranks[e["season_id"]] = S.team_strength_ranks(conn, e["season_id"]) \
                    if not E.is_v3(conn, e["season_id"]) else {int(k): v for k, v in (
                        E.frozen(conn, e["season_id"]).get("ranks") or {}).items()} or S.team_strength_ranks(conn, e["season_id"])
            score, details = S.player_event_score(conn, e, legacy_ranks[e["season_id"]])
            sessions = [{"driver_id": d["driver_id"], "event_id": e["id"], "session": "gp", "round": e["round_number"],
                         "year": e["year"], "difficulty": e["ai_difficulty"], "score": d["score"], "weight": 1.0,
                         "legacy": True, "position": d["position"], "excluded": None, "extreme": False,
                         "parts": {}, "gap_per_lap": None, "quali_gap": None, "reduced": []} for d in details]
            out.append({**e, "sessions": sessions, "legacy": True})
            continue
        ranks = calc3.round_ranks(conn, e)
        rows = [dict(r) for r in conn.execute("""SELECT r.*, d.is_player FROM results r JOIN drivers d ON d.id = r.driver_id
                                                 WHERE r.event_id = ?""", (e["id"],))]
        sessions = []
        for r in rows:
            if not r["is_player"]:
                continue
            if r["result_status"] in C.START_STATUSES:
                sessions.append(session_evidence(conn, e, r, rows, ranks, "gp", n_teams))
            if e["is_sprint"] and sprints and r["sprint_status"] in C.START_STATUSES:
                sessions.append(session_evidence(conn, e, r, rows, ranks, "sprint", n_teams))
        out.append({**e, "sessions": sessions, "legacy": False})
    return out


# --------------------------------------------------------------------------- recommendation

def _limit(weekends):
    for up_to, step in C.AI_STEP_LIMITS:
        if weekends <= up_to:
            return step
    return C.AI_STEP_LIMITS[-1][1]


def recommendation(conn, before=None):
    """The engine 3 recommendation (same keys as services.difficulty_recommendation, plus the 2.5 detail)."""
    from . import services as S
    hist = history(conn, before)
    rec = {"current": None, "recommended": None, "direction": None, "average": None, "sample": [], "players": [],
           "sweet_spot": None, "note": None, "history_rounds": len(hist), "engine": 3, "excluded": [], "used": [],
           "recent": [], "band": None, "reason": "", "evidence": "", "confidence": 0.0}
    if not hist:
        rec["reason"] = "Track the AI difficulty on a completed round to establish a baseline."
        return rec
    current = hist[-1]["ai_difficulty"]
    rec["current"] = current
    rec["band"] = S.difficulty_band(current)
    sid = S.current_season_id(conn)
    # Future-only: until a new usable session exists, keep the recommendation frozen at the cutoff.
    if sid and E.mixed(conn, sid):
        fz = E.frozen(conn, sid).get("ai") or {}
        new_usable = any(not h["legacy"] and any(x["score"] is not None for x in h["sessions"]) for h in hist)
        if fz and not new_usable:
            rec.update(recommended=fz.get("recommended", current), direction=fz.get("direction", "hold"),
                       band=S.difficulty_band(fz.get("recommended", current)),
                       reason=f"Kept from before the Calculation Update ({fz.get('recommended', current)}). The new "
                              "tracker takes over from the next tracked round.", frozen=True)
            rec["evidence"] = "Waiting for the first round under Calculation Version 3."
            return rec
    sessions = []
    for h in hist:
        for x in h["sessions"]:
            if x["score"] is None:
                rec["excluded"].append({"label": f"{h['year']} R{h['round_number']} {h['name']}"
                                        + (" Sprint" if x["session"] == "sprint" else ""), "why": x["excluded"],
                                        "driver_id": x["driver_id"]})
            else:
                sessions.append(x)
    untracked = conn.execute("""SELECT e.round_number, e.name, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                                WHERE e.status = ? AND (e.ai_untracked = 1 OR e.cancelled = 1)
                                ORDER BY s.year DESC, e.round_number DESC LIMIT 3""", (C.EVENT_COMPLETE,)).fetchall()
    rec["excluded"] = rec["excluded"][-6:] + [{"label": f"{r['year']} R{r['round_number']} {r['name']}",
                                               "why": "marked \"Don't track this round\""} for r in untracked]
    # the ten most recent usable sessions (a session = one player's Grand Prix or Sprint... grouped per event/session)
    keys = []
    for x in sessions:
        k = (x["year"], x["round"], 0 if x["session"] == "sprint" else 1)
        if k not in keys:
            keys.append(k)
    keys = keys[-10:]
    usable = [x for x in sessions if (x["year"], x["round"], 0 if x["session"] == "sprint" else 1) in keys]
    rec["sample"] = usable
    weekends = len({(x["year"], x["round"]) for x in usable})
    if not usable:
        rec.update(recommended=current, direction="hold",
                   reason=f"No usable sessions yet (a session needs a player driver to finish cleanly). Holding at {current}.")
        rec["evidence"] = _evidence(rec, usable, weekends)
        return rec
    age_of = {k: len(keys) - 1 - i for i, k in enumerate(keys)}
    dmap = S.driver_map(conn)
    per = {}
    for x in usable:
        age = age_of[(x["year"], x["round"], 0 if x["session"] == "sprint" else 1)]
        w = (0.5 ** (age / C.DIFF_RECENT_HALF_LIFE)) * x["weight"]
        shift = max(-C.DIFF_ROUND_CAP, min(C.DIFF_ROUND_CAP, soft(x["score"]) * C.DIFF_SPAN))
        p = per.setdefault(x["driver_id"], {"w": 0.0, "sum": 0.0, "n": 0, "items": []})
        p["w"] += w
        p["sum"] += w * (x["difficulty"] + shift)
        p["n"] += 1
        p["items"].append(x)
    players = []
    for did, p in per.items():
        if p["w"] <= 0:
            continue
        level = p["sum"] / p["w"]
        delta = level - current
        verdict = "struggling" if delta <= -C.DIFF_VERDICT else "comfortable" if delta >= C.DIFF_VERDICT else "about right"
        recent = sorted(p["items"], key=lambda x: (x["year"], x["round"]))[-3:]
        gaps = [x["gap_per_lap"] for x in recent if x.get("gap_per_lap") is not None]
        qgaps = [x["quali_gap"] for x in recent if x.get("quali_gap") is not None]
        places = [x["places_vs_benchmark"] for x in recent if x.get("places_vs_benchmark") is not None]
        players.append({"driver_id": did, "name": dmap[did]["name"] if did in dmap else "A player", "rounds": p["n"],
                        "level": round(level, 1), "delta": round(delta, 1), "verdict": verdict, "weight": p["w"],
                        "sweet_spot": personal_sweet_spot(sessions, did),
                        "race_gap": round(sum(gaps) / len(gaps), 2) if gaps else None,
                        "quali_gap": round(sum(qgaps) / len(qgaps), 2) if qgaps else None,
                        "places": round(sum(places) / len(places), 1) if places else None,
                        "trend": _trend(p["items"])})
    players.sort(key=lambda x: x["delta"])
    rec["players"] = players
    ups = [x for x in players if x["verdict"] == "comfortable"]
    downs = [x for x in players if x["verdict"] == "struggling"]
    mean = sum(x["delta"] for x in players) / len(players)
    weight = sum(x["weight"] for x in players) / len(players)
    confidence = weight / (weight + C.DIFF_CONFIDENCE_K)
    rec["confidence"] = round(confidence, 2)
    mixed = bool(ups and downs)
    raw = mean * (C.DIFF_MIXED if mixed else 1.0) * confidence
    limit = _limit(weekends)
    why_size = [f"at most {limit} with {weekends} usable weekend{'s' if weekends != 1 else ''}"]
    latest = [x for x in usable if (x["year"], x["round"], 0 if x["session"] == "sprint" else 1) == keys[-1]]
    if any(x.get("extreme") for x in latest):
        limit = max(limit, C.AI_EXTREME_STEP)
        why_size.append(f"a clean session more than {C.AI_EXTREME_GAP}s a lap off allows {C.AI_EXTREME_STEP}")
    last3 = keys[-3:]
    ext = [[x for x in usable if (x["year"], x["round"], 0 if x["session"] == "sprint" else 1) == k] for k in last3]
    if len(ext) == 3 and all(any(x.get("extreme") for x in grp) for grp in ext):
        signs = {math.copysign(1, x["score"]) for grp in ext for x in grp if x.get("extreme")}
        if len(signs) == 1:
            limit = max(limit, C.AI_PERSISTENT_STEP)
            why_size.append("three extreme sessions in a row allow up to 8")
    step = int(E.round_half_up(max(-limit, min(limit, raw))))
    if not ups and not downs:
        step = 0
    # Directional hysteresis: a reversal after one opposite session moves at most one level.
    # the recommendation that stood before the latest round in this history (never this round's own)
    prev = previous_direction(conn, (hist[-1]["year"], hist[-1]["round_number"]))
    if step and prev in ("up", "down") and (step > 0) != (prev == "up"):
        streak, strong = _opposite_streak(usable, keys, prev)
        if streak <= 1:
            step = 1 if step > 0 else -1
            why_size.append("only one session points the other way, so a reversal is limited to one level")
            rec["reversal"] = "damped"
        elif streak >= 3 and strong:
            why_size.append("three strong sessions point the other way, so the reversal isn't damped")
            rec["reversal"] = "free"
        else:
            why_size.append(f"{streak} sessions in a row point the other way")
            rec["reversal"] = "normal"
    rec["recommended"] = int(max(C.MIN_DIFFICULTY, min(C.MAX_DIFFICULTY, current + step)))
    step = rec["recommended"] - current
    rec["direction"] = "up" if step > 0 else "down" if step < 0 else "hold"
    rec["band"] = S.difficulty_band(rec["recommended"])
    rec["why_size"] = why_size
    spots = [x["sweet_spot"] for x in players if x["sweet_spot"] is not None]
    rec["sweet_spot"] = {"value": round(sum(spots) / len(spots), 1), "rounds": len(usable),
                         "seasons": len({x["year"] for x in usable}),
                         "confidence": "High" if len(usable) >= 15 else "Medium" if len(usable) >= 8 else "Low"} \
        if spots else None
    rec["average"] = round(sum(x["score"] for x in usable[-5:]) / len(usable[-5:]), 3)
    rec["reason"] = _reason(current, step, players, ups, downs, mixed, rec, weekends)
    rec["evidence"] = _evidence(rec, usable, weekends)
    rec["used"] = [{"label": f"{x['year']} R{x['round']}" + (" Sprint" if x["session"] == "sprint" else ""),
                    "difficulty": x["difficulty"], "score": x["score"], "driver_id": x["driver_id"]} for x in usable]
    rec["recent"] = [{"label": f"R{h['round_number']}", "year": h["year"], "difficulty": h["ai_difficulty"],
                      "score": _event_score(h)} for h in hist[-12:]]
    return rec


def _event_score(h):
    xs = [x["score"] for x in h["sessions"] if x["score"] is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _trend(items):
    xs = sorted(items, key=lambda x: (x["year"], x["round"]))
    if len(xs) < 2:
        return "—"
    a = sum(x["score"] for x in xs[-2:]) / 2
    b = sum(x["score"] for x in xs[:-2]) / len(xs[:-2]) if len(xs) > 2 else xs[0]["score"]
    return "improving" if a - b > 0.1 else "slipping" if b - a > 0.1 else "steady"


def personal_sweet_spot(sessions, driver_id):
    mine = [x for x in sessions if x["driver_id"] == driver_id and x["score"] is not None]
    if not mine:
        return None
    total = wsum = 0.0
    for age, x in enumerate(reversed(mine)):
        w = (0.5 ** (age / C.DIFF_HALF_LIFE)) * x["weight"]
        shift = max(-C.DIFF_SWEETSPOT_SPREAD, min(C.DIFF_SWEETSPOT_SPREAD, x["score"] / C.DIFF_SENSITIVITY))
        total += w * (x["difficulty"] + shift)
        wsum += w
    return round(max(C.MIN_DIFFICULTY, min(C.MAX_DIFFICULTY, total / wsum)), 1) if wsum else None


def _opposite_streak(usable, keys, prev):
    """How many of the most recent sessions (averaged over players) point against the previous direction."""
    want = -1 if prev == "up" else 1
    streak, strong = 0, True
    for k in reversed(keys):
        xs = [x["score"] for x in usable if (x["year"], x["round"], 0 if x["session"] == "sprint" else 1) == k]
        if not xs:
            continue
        avg = sum(xs) / len(xs)
        if abs(avg) <= C.DIFF_DEADBAND or math.copysign(1, avg) != want:
            break
        streak += 1
        strong = strong and abs(avg) >= 0.25
    return streak, strong


def previous_direction(conn, before=None):
    """The direction of the last stored recommendation (before `before` if given)."""
    rows = conn.execute("""SELECT a.direction, e.round_number, s.year FROM ai_recs a JOIN events e ON e.id = a.event_id
                           JOIN seasons s ON s.id = e.season_id ORDER BY s.year DESC, e.round_number DESC""").fetchall()
    for r in rows:
        if before and (r["year"], r["round_number"]) >= before:
            continue
        return r["direction"] if r["direction"] in ("up", "down") else None
    from . import services as S
    sid = S.current_season_id(conn)
    fz = (E.frozen(conn, sid).get("ai") or {}) if sid else {}
    return fz.get("direction") if fz.get("direction") in ("up", "down") else None


def _reason(current, step, players, ups, downs, mixed, rec, weekends):
    who = lambda xs: " and ".join(x["name"] for x in xs)       # noqa: E731
    if step == 0:
        if mixed:
            return (f"{who(downs)} {'is' if len(downs) == 1 else 'are'} finding AI {current} hard while {who(ups)} "
                    f"{'is' if len(ups) == 1 else 'are'} comfortable. Too close to call: hold at {current}.")
        if ups or downs:
            return f"Leaning {'up' if ups else 'down'}, but not enough evidence yet. Hold at {current}."
        return f"Recent sessions say AI {current} is about right. Hold."
    verb = "Raise" if step > 0 else "Reduce"
    text = f"{verb} AI from {current} to {current + step}."
    focus = downs if step < 0 else ups
    focus = focus or players
    details = []
    for x in focus:
        bits = []
        if x["race_gap"] is not None:
            bits.append(f"{abs(x['race_gap']):.2f} seconds per lap {'behind' if x['race_gap'] > 0 else 'ahead of'} "
                        "the benchmark")
        if x["places"] is not None:
            bits.append(f"{abs(x['places']):.1f} finishing positions {'behind' if x['places'] < 0 else 'ahead of'} "
                        "comparable cars")
        if bits:
            details.append(f"{x['name']} averaged " + " and ".join(bits))
    if details:
        text += " Across the last three representative sessions, " + "; ".join(details) + "."
    if mixed:
        text += f" {who(downs)} and {who(ups)} disagree, so the step is smaller."
    excluded = [x for x in rec["excluded"] if x.get("why") and "track" not in x["why"]]
    if excluded:
        text += f" {len(excluded)} session{'s were' if len(excluded) != 1 else ' was'} excluded ({excluded[-1]['why']})."
    return text


def _evidence(rec, usable, weekends):
    n = len(usable)
    parts = [f"{n} usable session{'s' if n != 1 else ''} over {weekends} weekend{'s' if weekends != 1 else ''}",
             "latest weighted most", "judged against the AI teammate, nearby cars and the car's expected finish"]
    if rec["excluded"]:
        parts.append(f"{len(rec['excluded'])} excluded")
    return ", ".join(parts) + "."


def store(conn, event_id):
    """Remember the recommendation after this round (for reversal damping and change notices)."""
    rec = recommendation(conn)
    conn.execute("""INSERT INTO ai_recs(event_id, engine, current, recommended, direction, detail, created_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET engine = excluded.engine,
                    current = excluded.current, recommended = excluded.recommended, direction = excluded.direction,
                    detail = excluded.detail, created_at = excluded.created_at""",
                 (event_id, 3, rec["current"], rec["recommended"], rec["direction"],
                  json.dumps({"players": [{k: p[k] for k in ("driver_id", "level", "sweet_spot", "verdict")}
                                          for p in rec["players"]]}), now_iso()))
    return rec
