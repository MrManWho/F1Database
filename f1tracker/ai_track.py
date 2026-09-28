"""Track-aware AI recommendation (Paddock Legacy 4.0).

One AI difficulty for the whole weekend (qualifying, Sprint and race use the same setting):

    recommended AI = F1Laps track baseline + learned league adjustment + personal track history

* **F1Laps track baseline**: the average AI difficulty players use at each circuit in F1 26, from a versioned local
  snapshot (f1tracker/data/ai_baselines). The site never contacts F1Laps. A new snapshot applies to future rounds
  only; every recommendation already made keeps the snapshot version and values it was made with.
* **Learned league adjustment**: starts at 0 in every league on this model and is learned from completed weekends.
  Each player driver is judged separately (against their AI teammate, or AI cars of similar speed, or the car's
  expected finish; the same evidence the v3 tracker uses), then the players are combined: agreement moves it
  further, mixed evidence moves it a little or not at all. It moves at most 2 after one weekend, 3 after two
  aligned weekends in a row and 4 after three or more. Switching circuits is not limited by that cap: the baseline
  simply changes with the track.
* **Personal track history**: after repeated visits to a circuit, part of the baseline is replaced by how this
  league's players actually got on there. It starts at zero influence and is capped at +/-3.

Evidence rules: a DNF, DNS, DSQ, a major incident (a warning or penalty, or one still open) or a verified no-fault
result is never counted against the AI being too hard. Wet or changing weather and disrupted races (safety car,
strategy or traffic distortion) count at reduced weight. Finishing ahead of a teammate is always positive evidence.

The AI actually used each round is the round's recorded difficulty; the recommendation shown before the round is
stored separately (ai_track_recs) the first time the round is submitted and is never recalculated afterwards.
"""

import json
from functools import lru_cache
from pathlib import Path

from . import constants as C
from . import engine as E
from .storage import get_meta, now_iso, set_meta

MODEL = "track-aware-1"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "data" / "ai_baselines"
CURRENT_SNAPSHOT = "f1laps-f126-2026-09-28"

SPAN = 8.0                 # AI levels a perfect weekend (session score +1) says the player could take
DEADBAND = 0.5             # a player's implied change this small counts as "about right"
MIXED_FACTOR = 0.25        # players disagree: move a quarter as far (usually below the dead band, so no change)
SINGLE_FACTOR = 0.6        # one player's evidence (or one agreeing, the rest about right)
CONFIDENCE_K = 0.75        # confidence = weight / (weight + K)
STEP_CAPS = {1: 2.0, 2: 3.0}   # aligned weekends in a row -> most the league adjustment may move; 3+ -> 4
STEP_CAP_MAX = 4.0
ADJUSTMENT_LIMIT = 15.0    # the learned adjustment never drifts further than this from the F1Laps baseline
HISTORY_CAP = 3.0          # personal track history is capped at +/-3
HISTORY_K = 3.0            # influence after n visits = n / (n + 3): 0, 25%, 40%, 50% ...
SPLIT_WARNING = 6          # two players' own recommendations further apart than this: no single AI suits both
WET_WEIGHT = 0.5           # wet or changing race weather
MIXED_CAP = 1.0            # mixed evidence moves the league adjustment by at most 1


# --------------------------------------------------------------------------- the F1Laps snapshot

def snapshot(version=None):
    return _load(str(SNAPSHOT_DIR), version or CURRENT_SNAPSHOT)


@lru_cache(maxsize=8)
def _load(folder, version):
    data = json.loads((Path(folder) / f"{version}.json").read_text(encoding="utf-8"))
    data["by_circuit"] = {c["circuit"]: c for c in data["circuits"]}
    data["average"] = sum(c["ai"] for c in data["circuits"]) / len(data["circuits"])
    return data


def snapshots():
    return sorted(p.stem for p in SNAPSHOT_DIR.glob("*.json"))


def baseline(event, version=None):
    """(value, label, known) for this round's circuit. Unknown circuits use the average of all circuits."""
    from . import circuits
    data = snapshot(version)
    name = circuits.lookup(event["name"], event.get("location") or "")["circuit"]
    row = data["by_circuit"].get(name)
    if row:
        return float(row["ai"]), row["label"], True
    return round(data["average"], 1), "average of all circuits (this circuit isn't in the F1Laps snapshot)", False


def circuit_key(event):
    from . import circuits
    return circuits.lookup(event["name"], event.get("location") or "")["circuit"] or event["name"]


# --------------------------------------------------------------------------- which seasons use this model

def _key(season_id):
    return f"ai_model:{season_id}"


def season_model(conn, season_id):
    return get_meta(conn, _key(season_id)) or "v3"


def uses_track(conn, season_id):
    return bool(season_id) and season_model(conn, season_id) == MODEL and E.is_v3(conn, season_id)


NEW_SEASON_MODEL = MODEL


def start_season(conn, season_id):
    """New seasons (a new league, or the next season after a rollover) use the track-aware model from round 1.
    A season already under way keeps the model it started with (the formula freeze)."""
    set_meta(conn, _key(season_id), NEW_SEASON_MODEL)


def season_for(conn, before=None):
    """The season a recommendation is for: the season of (year, round) = before, else the current one."""
    from . import services as S
    if before:
        row = conn.execute("SELECT id FROM seasons WHERE year = ?", (before[0],)).fetchone()
        if row:
            return row[0]
    return S.current_season_id(conn)


def use_history(conn):
    return get_meta(conn, "ai_track_history", "1") == "1"


# --------------------------------------------------------------------------- one weekend's evidence

def _major_incident(conn, event_id, driver_id):
    return bool(conn.execute("""SELECT 1 FROM incidents WHERE event_id = ?
                                AND (accused_driver_id = ? OR reporter_driver_id = ?)
                                AND (status = 'Open' OR ruling IN ('warning', 'penalty'))""",
                             (event_id, driver_id, driver_id)).fetchone())


def _wet(conn, event_id):
    from . import weather
    return weather.CONDITIONS.get(weather.get(conn, event_id).get("race"), ("", "", False))[2]


def weekend_evidence(conn, event):
    """Each player's evidence for one completed, tracked round: {driver_id: {...}} (implied change in AI levels)."""
    from . import ai3, calc3, services as S
    ranks = calc3.round_ranks(conn, event)
    rows = [dict(r) for r in conn.execute("""SELECT r.*, d.is_player, d.name FROM results r
                                             JOIN drivers d ON d.id = r.driver_id WHERE r.event_id = ?""", (event["id"],))]
    n_teams = conn.execute("SELECT COUNT(*) FROM teams WHERE active = 1").fetchone()[0] or 11
    wet = _wet(conn, event["id"])
    sprints = ai3._sprints_tracked(conn)
    out = {}
    for r in rows:
        if not r["is_player"]:
            continue
        sessions, notes = [], []
        plan = [("gp", r["result_status"])]
        if event["is_sprint"] and sprints:
            plan.append(("sprint", r["sprint_status"]))
        for session, status in plan:
            label = "Sprint" if session == "sprint" else "Grand Prix"
            if status not in C.CLASSIFIED_STATUSES:
                notes.append(f"{label}: {status or 'no result'}, not counted")
                continue
            ev = ai3.session_evidence(conn, dict(event), r, rows, ranks, session, n_teams)
            if ev["score"] is None:
                notes.append(f"{label}: {ev['excluded']}, not counted")
                continue
            score, weight = ev["score"], ev["weight"]          # a Sprint already counts half
            ahead = (ev.get("places_vs_benchmark") or 0) > 0 and ev.get("benchmark") == "your AI teammate"
            if score < 0 and ahead:
                score = 0.0      # beating the teammate is never evidence the AI is too hard
                notes.append(f"{label}: ahead of the AI teammate, so not counted as struggling")
            if score < 0 and session == "gp" and r.get("no_fault"):
                notes.append(f"{label}: a no-fault result, never counted against the AI")
                continue
            if score < 0 and _major_incident(conn, event["id"], r["driver_id"]):
                notes.append(f"{label}: a major incident, never counted against the AI")
                continue
            if wet:
                weight *= WET_WEIGHT
                notes.append(f"{label}: wet race, reduced weight")
            if ev.get("reduced"):
                notes.append(f"{label}: {', '.join(ev['reduced'])}, reduced weight")
            sessions.append({"session": session, "score": score, "weight": round(weight, 3),
                             "benchmark": ev.get("benchmark"), "places": ev.get("places_vs_benchmark")})
        w = sum(s["weight"] for s in sessions)
        if not w:
            out[r["driver_id"]] = {"name": r["name"], "delta": None, "weight": 0.0, "sessions": [], "notes": notes}
            continue
        score = sum(s["score"] * s["weight"] for s in sessions) / w
        delta = ai3.soft(score) * SPAN
        out[r["driver_id"]] = {"name": r["name"], "delta": round(delta, 2), "weight": round(w, 3), "score": round(score, 3),
                               "sessions": sessions, "notes": notes}
    return out


def combine(players):
    """(raw change, verdicts, agreement, confidence) from each player's implied change."""
    usable = {d: p for d, p in players.items() if p["delta"] is not None}
    if not usable:
        return 0.0, "none", 0.0
    up = [p for p in usable.values() if p["delta"] >= DEADBAND]
    down = [p for p in usable.values() if p["delta"] <= -DEADBAND]
    total_w = sum(p["weight"] for p in usable.values())
    mean = sum(p["delta"] * p["weight"] for p in usable.values()) / total_w
    confidence = (total_w / len(usable)) / ((total_w / len(usable)) + CONFIDENCE_K)
    if up and down:
        agreement, factor = "mixed", MIXED_FACTOR
    elif not up and not down:
        agreement, factor = "about right", 0.0
    elif len(usable) >= 2 and len(up or down) == len(usable):
        agreement, factor = "agree", 1.0
    else:
        agreement, factor = "single", SINGLE_FACTOR
    return mean * factor * confidence, agreement, confidence


def _round_half(v):
    return E.round_half_up(v * 2) / 2


# --------------------------------------------------------------------------- learning (replayed in order)

def _track_events(conn, before=None):
    """Completed rounds of track-aware seasons, oldest first (optionally only those before (year, round))."""
    rows = conn.execute("""SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                           WHERE e.status = ? AND e.cancelled = 0 ORDER BY s.year, e.round_number""",
                        (C.EVENT_COMPLETE,)).fetchall()
    out = []
    for e in rows:
        e = dict(e)
        if before and (e["year"], e["round_number"]) >= tuple(before):
            continue
        if uses_track(conn, e["season_id"]):
            out.append(e)
    return out


def learn(conn, before=None):
    """Replay every completed weekend: the league adjustment after each, with its evidence.
    Returns (adjustment, steps, per-player residuals by circuit)."""
    adj, direction, streak = 0.0, 0, 0
    steps, visits = [], {}
    for e in _track_events(conn, before):
        if e["ai_difficulty"] is None:
            steps.append({"event": e, "tracked": False, "before": adj, "step": 0.0, "after": adj})
            continue
        base, label, _known = baseline(e, frozen_version(conn, e["id"]))
        players = weekend_evidence(conn, e)
        raw, agreement, confidence = combine(players)
        # The evidence is about the AI actually used. If that differs from what was recommended, it also tells us
        # how far off the recommendation was: fully when players found it right or agreed, a quarter when mixed.
        shown = frozen(conn, e["id"])
        offset = (e["ai_difficulty"] - shown["recommended"]) if shown else 0.0
        change = raw + (offset * confidence * (MIXED_FACTOR if agreement == "mixed" else 1.0)
                        if agreement != "none" else 0.0)
        sign = (change >= DEADBAND / 2) - (change <= -DEADBAND / 2)
        if sign and sign == direction:
            streak += 1
        elif sign:
            direction, streak = sign, 1
        else:
            direction, streak = 0, 0
        cap = MIXED_CAP if agreement == "mixed" else STEP_CAPS.get(streak, STEP_CAP_MAX) if streak else STEP_CAPS[1]
        step = _round_half(max(-cap, min(cap, change))) if sign else 0.0
        new_adj = max(-ADJUSTMENT_LIMIT, min(ADJUSTMENT_LIMIT, adj + step))
        for did, p in players.items():
            if p["delta"] is None:
                continue
            residual = (e["ai_difficulty"] + p["delta"]) - (base + adj)
            visits.setdefault((did, circuit_key(e)), []).append(residual)
        steps.append({"event": e, "tracked": True, "baseline": base, "baseline_label": label, "before": adj,
                      "step": new_adj - adj, "after": new_adj, "agreement": agreement, "confidence": round(confidence, 2),
                      "players": players, "streak": streak, "cap": cap})
        adj = new_adj
    return adj, steps, visits


def track_history(conn, event, visits, players):
    """Personal track history for this circuit: each current player's past residual here, weighted by how often
    they've raced here (no influence before the first visit), averaged over the players, capped at +/-3."""
    if not use_history(conn):
        return 0.0, []
    key = circuit_key(event)
    parts = []
    for p in players:
        seen = visits.get((p["id"], key), [])
        if not seen:
            parts.append({"name": p["name"], "visits": 0, "value": 0.0})
            continue
        influence = len(seen) / (len(seen) + HISTORY_K)
        value = max(-HISTORY_CAP, min(HISTORY_CAP, influence * sum(seen) / len(seen)))
        parts.append({"name": p["name"], "visits": len(seen), "value": round(value, 1)})
    if not parts:
        return 0.0, []
    total = sum(x["value"] for x in parts) / len(parts)
    return max(-HISTORY_CAP, min(HISTORY_CAP, round(total, 1))), parts


# --------------------------------------------------------------------------- the recommendation

def frozen(conn, event_id):
    row = conn.execute("SELECT * FROM ai_track_recs WHERE event_id = ?", (event_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["explanation"] = json.loads(d["explanation"]) if d["explanation"] else {}
    return d


def frozen_version(conn, event_id):
    row = conn.execute("SELECT dataset_version FROM ai_track_recs WHERE event_id = ?", (event_id,)).fetchone()
    return row[0] if row and row[0] in snapshots() else None


def target_event(conn, before=None):
    """The round a recommendation is for: the round at (year, round) = before, else the next round to run."""
    from . import services as S
    sid = S.current_season_id(conn)
    if before:
        row = conn.execute("""SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                              WHERE s.year = ? AND e.round_number = ?""", tuple(before)).fetchone()
        if row:
            return dict(row)
        if sid:     # after the last round of a season: nothing more this season
            return None
    nxt = S.next_incomplete_event(conn, sid) if sid else None
    if nxt:
        nxt = dict(nxt)
        nxt["year"] = S.get_season(conn, sid)["year"]
    return nxt


def compute(conn, event):
    """The live recommendation for one round, worked out from every weekend before it."""
    from . import services as S
    adj, steps, visits = learn(conn, (event["year"], event["round_number"]))
    base, label, known = baseline(event)
    current_players = [dict(p) for p in S.player_drivers(conn)
                       if p["id"] in S.driver_seats(conn, event["season_id"])]
    history, history_parts = track_history(conn, event, visits, current_players)
    final = int(max(C.MIN_DIFFICULTY, min(C.MAX_DIFFICULTY, E.round_half_up(base + adj + history))))
    tracked = [s for s in steps if s.get("tracked")]
    last = tracked[-1] if tracked else None
    # each player's own recommendation: their recent residual on top of the league's (for the split warning)
    own = []
    for p in current_players:
        recent = [x for s in tracked[-5:] for d, x in s["players"].items() if d == p["id"] and x["delta"] is not None]
        if not recent:
            continue
        offset = sum(x["delta"] for x in recent) / len(recent)
        mine = next((h["value"] for h in history_parts if h["name"] == p["name"]), 0.0)
        own.append({"name": p["name"], "value": int(E.round_half_up(base + adj + offset + mine))})
    spread = (max(o["value"] for o in own) - min(o["value"] for o in own)) if len(own) >= 2 else 0
    return {
        "event_id": event["id"], "circuit": label, "circuit_known": known, "dataset_version": snapshot()["dataset_version"],
        "model_version": MODEL, "baseline": base, "league_adjustment": round(adj, 1), "track_history": history,
        "history_parts": history_parts, "recommended": final, "confidence": last["confidence"] if last else 0.0,
        "weekends": len(tracked), "last": _describe_step(last) if last else None, "players_own": own,
        "split": spread > SPLIT_WARNING, "spread": spread,
    }


def _describe_step(s):
    return {"round": s["event"]["round_number"], "name": s["event"]["name"], "year": s["event"]["year"],
            "ai_used": s["event"]["ai_difficulty"], "agreement": s["agreement"], "step": round(s["step"], 1),
            "cap": s["cap"], "confidence": s["confidence"],
            "players": [{"name": p["name"], "delta": p["delta"], "weight": p["weight"], "notes": p["notes"],
                         "sessions": p["sessions"]} for p in s["players"].values()]}


def recommendation(conn, before=None):
    """Same shape as ai3.recommendation (so every page can show it), plus rec["track"] with the full explanation."""
    from . import services as S
    event = target_event(conn, before)
    rec = {"current": None, "recommended": None, "direction": None, "average": None, "sample": [], "players": [],
           "sweet_spot": None, "note": None, "engine": "track", "model": MODEL, "excluded": [], "used": [],
           "recent": [], "band": None, "reason": "", "evidence": "", "confidence": 0.0, "track": None}
    last_used = conn.execute("""SELECT e.ai_difficulty FROM events e JOIN seasons s ON s.id = e.season_id
                                WHERE e.status = ? AND e.ai_difficulty IS NOT NULL
                                ORDER BY s.year DESC, e.round_number DESC LIMIT 1""", (C.EVENT_COMPLETE,)).fetchone()
    rec["current"] = last_used[0] if last_used else None
    if not event:
        rec["reason"] = "The season's rounds are all complete. The next season starts from what this one learned."
        return rec
    stored = frozen(conn, event["id"]) if event.get("status") == C.EVENT_COMPLETE else None
    t = stored["explanation"] if stored else compute(conn, event)
    rec["track"] = t
    rec["recommended"] = t["recommended"]
    rec["confidence"] = t["confidence"]
    rec["band"] = S.difficulty_band(t["recommended"])
    if rec["current"] is not None:
        rec["direction"] = "up" if t["recommended"] > rec["current"] else "down" if t["recommended"] < rec["current"] else "hold"
    parts = [f"F1Laps baseline for {t['circuit']} {t['baseline']:g}"]
    parts.append(f"league adjustment {t['league_adjustment']:+g}")
    if t["track_history"]:
        parts.append(f"track history {t['track_history']:+g}")
    rec["reason"] = f"AI {t['recommended']} for the whole weekend: " + ", ".join(parts) + "."
    if not t["weekends"]:
        rec["evidence"] = ("No completed weekends yet, so this is the F1Laps average for this circuit. The league "
                           "adjustment is learned from each completed round.")
    elif t["last"]:
        l = t["last"]
        rec["evidence"] = (f"After R{l['round']} {l['name']} (AI {l['ai_used']} used): players "
                           f"{ {'agree': 'agreed', 'single': 'pointed one way', 'mixed': 'disagreed', 'about right': 'found it about right', 'none': 'gave no usable evidence'}[l['agreement']] }, "
                           f"league adjustment {l['step']:+g} (limit {l['cap']:g}), confidence {int(l['confidence'] * 100)}%.")
    if t["split"]:
        rec["note"] = (f"No single AI setting can perfectly balance every driver: their own levels differ by "
                       f"{t['spread']} points (" + ", ".join(f"{o['name']} {o['value']}" for o in t["players_own"]) + ").")
    return rec


def store(conn, event_id):
    """When a round is submitted: freeze the recommendation that was shown for it (first time only), and record the
    recommendation after it in ai_recs (as every engine does, for change notices)."""
    from . import services as S
    event = S.get_event(conn, event_id)
    if not event:
        return None
    ev = dict(event)
    ev["year"] = S.get_season(conn, ev["season_id"])["year"]
    if not conn.execute("SELECT 1 FROM ai_track_recs WHERE event_id = ?", (event_id,)).fetchone():
        t = compute(conn, ev)
        conn.execute("""INSERT INTO ai_track_recs(event_id, season_id, circuit, dataset_version, model_version, baseline,
                        league_adjustment, track_history, recommended, ai_used, confidence, explanation, created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (event_id, ev["season_id"], t["circuit"], t["dataset_version"], t["model_version"], t["baseline"],
                      t["league_adjustment"], t["track_history"], t["recommended"], ev["ai_difficulty"],
                      t["confidence"], json.dumps(t, default=str), now_iso()))
    else:   # a correction: the recommendation stays as it was; only the AI actually used is kept up to date
        conn.execute("UPDATE ai_track_recs SET ai_used = ? WHERE event_id = ?", (ev["ai_difficulty"], event_id))
    rec = recommendation(conn, (ev["year"], ev["round_number"] + 1))
    conn.execute("""INSERT INTO ai_recs(event_id, engine, current, recommended, direction, detail, created_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET engine = excluded.engine,
                    current = excluded.current, recommended = excluded.recommended, direction = excluded.direction,
                    detail = excluded.detail, created_at = excluded.created_at""",
                 (event_id, 3, rec["current"], rec["recommended"], rec["direction"],
                  json.dumps({"model": MODEL, "league_adjustment": (rec["track"] or {}).get("league_adjustment")}),
                  now_iso()))
    return rec


def history_rows(conn, season_id):
    """Every submitted round of a season: the recommendation shown, the AI actually used and the snapshot version."""
    return [dict(r) for r in conn.execute("""SELECT t.*, e.round_number, e.name FROM ai_track_recs t
                                             JOIN events e ON e.id = t.event_id WHERE t.season_id = ?
                                             ORDER BY e.round_number""", (season_id,))]
