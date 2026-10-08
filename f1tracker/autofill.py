"""Rounds that fill themselves in from the game (4.1.0).

When the recorder sends a round's race (the last session of the weekend), the site does what "Fill weekend from
the game" does on the round page, on its own: the finishing order of qualifying, the Sprint and the race, DNFs, the
fastest lap and the AI level, each session's weather, the winner's race time and the players' times against their
AI teammates. Only blanks are filled: a session that already has results, or a time already typed in, is kept.

Nothing is submitted. The round is marked "ready to approve", everyone in the league gets an alert, and the round
page's Review step offers one "Approve and submit" button that runs the normal submit. Drivers it can't match with
confidence are left blank and listed, so the normal checks stop the submit until someone fills them in.

The name matching mirrors static/js/ocr_match.js (matchDriver) and static/js/importer.js (teleRow, fillWeekend), so
the button on the round page and this background fill pick the same drivers.
"""

import json
import unicodedata

from . import constants as C
from . import services as S
from . import telemetry
from .storage import get_meta, now_iso, set_meta

GAME_USER = "the game"        # who the activity log and the race-time boxes say filled it in
TELE_STATUS = {"Finished": "Finished", "Active": "Finished", "DSQ": "DSQ", "DNF": "DNF", "Retired": "DNF",
               "Not Classified": "DNF", "Inactive": "DNS", "Invalid": "DNS"}
OUT = ("DNF", "Retired", "DSQ", "Not Classified")


def enabled(conn):
    """League setting (Telemetry upload link page): get a round ready by itself when its race arrives. On by default."""
    return get_meta(conn, "telemetry_autofill", "1") == "1"


# --------------------------------------------------------------------------- name matching (ocr_match.js)

def norm_name(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if not unicodedata.combining(c)).lower()
    for a, b in (("0", "o"), ("1", "l"), ("5", "s"), ("8", "b"), ("|", "l")):
        s = s.replace(a, b)
    s = "".join(c if ("a" <= c <= "z" or c.isspace() or c in "'-") else " " for c in s)
    s = s.replace("'", "").replace("-", "")
    return " ".join(s.split())


def _variants(s):
    return {s, s.replace("rn", "m"), s.replace("m", "rn"), s.replace("vv", "w"), s.replace("cl", "d")}


def _lev(a, b):
    if a == b:
        return 0
    if not a or not b:
        return len(a or b)
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        for j in range(1, len(b) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1])))
        prev = cur
    return prev[-1]


def _ratio(a, b):
    if not a or not b:
        return 0.0
    return 1 - _lev(a, b) / max(len(a), len(b))


def _forms(name):
    n = norm_name(name)
    parts = n.split()
    first, last = (parts[0] if parts else ""), (parts[-1] if parts else "")
    return {"full": n, "surname": last, "initial": f"{first[0]} {last}" if first else last, "first": first,
            "surname2": " ".join(parts[1:]) if len(parts) > 2 else None}


def match_driver(text, grid, high=0.86, low=0.72):
    """One name against the round's drivers: {"state": matched|review|ambiguous|unmatched, "driver_id", "score",
    "candidates"}. grid: [{"id", "name", ...}]."""
    raw = norm_name(text)
    if len(raw.replace(" ", "")) < 2:
        return {"state": "unmatched", "driver_id": None, "score": 0, "candidates": []}
    tokens = raw.split(" ")
    pieces = set()
    for k in range(1, min(4, len(tokens)) + 1):
        head = tokens[:k]
        pieces.add(" ".join(head))
        if k > 1 and len(head[0]) == 1:
            pieces.add(head[0] + " " + "".join(head[1:]))
        if k > 1:
            pieces.add("".join(head))
    tried = [v for p in pieces for v in _variants(p)]
    scored = []
    for d in grid:
        f = _forms(d["name"])
        best = 0.0
        for v in tried:
            vt = v.split(" ")
            vlast = vt[-1]
            best = max(best, _ratio(v, f["full"]), _ratio(v, f["initial"]),
                       _ratio(v, f["surname2"]) if f["surname2"] else 0,
                       _ratio(v, f["surname"]) * 0.97,
                       _ratio(vlast, f["surname"]) * 0.99 if len(vt) > 1 and f["first"] and vt[0][:1] == f["first"][0] else 0,
                       0.9 if len(vt) > 1 and f["surname"] in vt and len(f["surname"]) >= 4 else 0)
        scored.append({"id": d["id"], "name": d["name"], "score": round(best * 1000) / 1000})
    scored.sort(key=lambda c: -c["score"])
    top = scored[0] if scored else {"score": 0}
    second = scored[1] if len(scored) > 1 else {"score": 0}
    cands = [c for c in scored if c["score"] >= low][:4]
    if top["score"] < low:
        return {"state": "unmatched", "driver_id": None, "score": top["score"], "candidates": cands}
    if second["score"] >= low and top["score"] - second["score"] < 0.05:
        return {"state": "ambiguous", "driver_id": None, "score": top["score"], "candidates": cands}
    return {"state": "matched" if top["score"] >= high else "review", "driver_id": top["id"], "score": top["score"],
            "candidates": cands}


def _same_team(a, b):
    words = lambda t: [x for x in norm_name(t).split() if len(x) >= 3 and x not in ("racing", "team", "f1")]
    y = words(b)
    return any(t in y for t in words(a))


def _key(r):
    return f"{r.get('name') or ''}|{r.get('team') or ''}"


def _ident(r):
    return f"{_key(r)}|{r.get('race_number') or ''}"


def match_row(r, grid, known):
    """One row of the game's classification -> (driver_id or None, "high" | "review" | "unmatched")."""
    by_id = {d["id"]: d for d in grid}
    remembered = known.get(_key(r))
    if remembered in by_id:
        return remembered, "high"
    if not r.get("name"):
        return None, "unmatched"
    m = match_driver(r["name"], grid)
    same = [c for c in m["candidates"] if c["id"] in by_id and _same_team(by_id[c["id"]]["team"], r.get("team"))]
    if m["driver_id"] and (not r.get("team") or _same_team(by_id[m["driver_id"]]["team"], r.get("team"))):
        return m["driver_id"], "high" if m["state"] == "matched" else "review"
    if len(same) == 1:
        return same[0]["id"], "review"
    if m["driver_id"]:
        return m["driver_id"], "review"
    return None, "unmatched"


def combine_quali(sessions):
    """Q1, Q2 and Q3 as one order: Q3 first, then those out in Q2, then those out in Q1."""
    seen, out = set(), []
    for q in reversed(sessions):
        for r in sorted((r for r in q.get("results") or [] if r.get("position")), key=lambda r: r["position"]):
            if _ident(r) in seen:
                continue
            seen.add(_ident(r))
            out.append({**r, "position": len(out) + 1})
    return out


# --------------------------------------------------------------------------- the fill itself

def plan(conn, event, bundle, grid=None, known=None):
    """What the game's sessions say about this round, without saving anything:
    {"sessions": {key: [{driver_id, position, status}]}, "fastest": driver_id, "ai": level, "pace": [...],
     "names": {game name|team: driver_id}, "missing": [...], "review": n, "upload_ids": [...], "by_session": {...}}"""
    rows = S.weekend_rows(conn, event["id"])
    grid = grid if grid is not None else [{"id": r["driver_id"], "name": r["driver"]["name"], "team": r["team"]["name"],
                                           "is_player": bool(r["driver"]["is_player"])} for r in rows]
    known = known if known is not None else telemetry.names(conn)
    by_id = {d["id"]: d for d in grid}
    sprint_weekend = bool(event["is_sprint"])
    label = {"qualifying": "qualifying", "sprint": "Sprint", "race": "race"}
    plans = []
    if bundle.get("qualifying"):
        plans.append(("qualifying", combine_quali(bundle["qualifying"]), bundle["qualifying"]))
    if bundle.get("sprint") and sprint_weekend:
        plans.append(("sprint", bundle["sprint"].get("results") or [], [bundle["sprint"]]))
    if bundle.get("race"):
        plans.append(("race", bundle["race"].get("results") or [], [bundle["race"]]))
    out = {"sessions": {}, "fastest": None, "ai": None, "pace": [], "names": {}, "missing": [], "review": 0,
           "upload_ids": [], "by_session": {}}
    driver_of = {}
    for key, results, uploads in plans:
        matched = [(r, *match_row(r, grid, known)) for r in results]
        count = {}
        for _r, did, _s in matched:
            if did:
                count[did] = count.get(did, 0) + 1
        use = []
        for r, did, state in matched:
            raw = (f"P{r['position']} " if r.get("position") else "") + (r.get("name") or "?") + \
                  (f" · {r['team']}" if r.get("team") else "")
            if did and count[did] == 1:
                status = TELE_STATUS.get(r.get("status"), "Finished")
                use.append({"driver_id": did, "position": None if status == "DNS" else (r.get("position") or None),
                            "status": status})
                driver_of[_ident(r)] = did
                out["names"][_key(r)] = did
                out["review"] += state == "review"
            elif f"{label[key]}: {raw}" not in out["missing"]:
                out["missing"].append(f"{label[key]}: {raw}")
        out["sessions"][key] = use
        ids = [u["id"] for u in uploads if u.get("id")]
        out["upload_ids"] += ids
        out["by_session"][{"qualifying": "quali", "sprint": "sprint", "race": "race"}[key]] = ids
    race = bundle.get("race")
    fastest = next((r for r in (race or {}).get("results") or [] if r.get("fastest_lap")), None)
    out["fastest"] = driver_of.get(_ident(fastest)) if fastest else None
    any_sess = race or bundle.get("sprint") or (bundle.get("qualifying") or [None])[0]
    ai = any_sess and any_sess["session"].get("ai_difficulty")
    out["ai"] = ai if isinstance(ai, int) and ai > 0 else None
    # Race times for each player against their AI teammate (same team in the game), and qualifying laps.
    is_player = lambda did: bool(did and did in by_id and by_id[did].get("is_player"))
    best_q = {}
    for q in bundle.get("qualifying") or []:
        for r in q.get("results") or []:
            if r.get("best_lap_ms") and (_ident(r) not in best_q or r["best_lap_ms"] < best_q[_ident(r)]):
                best_q[_ident(r)] = r["best_lap_ms"]
    done = lambda r: bool(r and r.get("status") == "Finished" and (r.get("race_time_s") or 0) > 0)
    total = lambda r: r["race_time_s"] + (r.get("penalty_s") or 0)
    for d in (d for d in grid if d.get("is_player")):
        for sess_key, sess in (("gp", race), ("sprint", bundle.get("sprint") if sprint_weekend else None)):
            entry = {"driver_id": d["id"], "session": sess_key}
            results = (sess or {}).get("results") or []
            me = next((r for r in results if driver_of.get(_ident(r)) == d["id"]), None)
            my_ident = _ident(me) if me else None
            if not me and sess_key == "gp":   # no race: qualifying still gives lap times
                my_ident = next((k for k in best_q if driver_of.get(k) == d["id"]), None)
            if not my_ident:
                continue
            my_team = my_ident.split("|")[1]
            mate = next((r for r in results if _ident(r) != my_ident and r.get("team") == my_team
                         and not is_player(driver_of.get(_ident(r)))), None)
            if sess_key == "gp":
                mate_ident = _ident(mate) if mate else next(
                    (k for k in best_q if k != my_ident and k.split("|")[1] == my_team and not is_player(driver_of.get(k))), None)
                if best_q.get(my_ident) and mate_ident and best_q.get(mate_ident):
                    entry["quali_time"] = best_q[my_ident] / 1000
                    entry["mate_quali_time"] = best_q[mate_ident] / 1000
            if me:
                if me.get("laps"):
                    entry["laps"] = me["laps"]
                if done(me) and done(mate) and me.get("laps") == mate.get("laps"):
                    entry["race_time"], entry["bench_race_time"] = total(me), total(mate)
                else:   # a retirement shows as DNF in the race time boxes (no race gap)
                    if me.get("status") in OUT:
                        entry["race_dnf"] = True
                    if mate and mate.get("status") in OUT:
                        entry["bench_dnf"] = True
                    if entry.get("race_dnf") and not entry.get("bench_dnf") and done(mate):
                        entry["bench_race_time"] = total(mate)
                    if entry.get("bench_dnf") and not entry.get("race_dnf") and done(me):
                        entry["race_time"] = total(me)
            if len(entry) > 2:
                out["pace"].append(entry)
    return out


SESSION_FIELDS = {"qualifying": ("qualifying_position", None), "sprint": ("sprint_position", "sprint_status_override"),
                  "race": ("race_position", "status_override")}


def _blank(snapshot, key):
    pos, status = SESSION_FIELDS[key]
    return not any(r.get(pos) or (status and r.get(status) not in (None, "Auto")) for r in snapshot["results"].values())


def results_payload(conn, event, p):
    """The round's saved results with the game's sessions filled into the blank ones.
    Returns (payload or None when nothing changes, [what was filled], [what was kept])."""
    snap = S.weekend_snapshot(conn, event["id"])
    filled, kept = [], []
    label = {"qualifying": "qualifying", "sprint": "Sprint", "race": "race"}
    changed = False
    for key, use in p["sessions"].items():
        if not use:
            continue
        if not _blank(snap, key):
            kept.append(f"{label[key]} (already entered)")
            continue
        pos_field, status_field = SESSION_FIELDS[key]
        n = 0
        for u in use:
            row = snap["results"].get(str(u["driver_id"]))
            if row is None:
                continue
            row[pos_field] = u["position"]
            if status_field:
                row[status_field] = u["status"] if u["status"] != "Finished" else "Auto"
            n += 1
        if n:
            filled.append(f"{n} {label[key]}")
            changed = True
    if p["fastest"] and not any(r["fastest_lap"] for r in snap["results"].values()) \
            and str(p["fastest"]) in snap["results"]:
        snap["results"][str(p["fastest"])]["fastest_lap"] = True
        filled.append("fastest lap")
        changed = True
    if p["ai"] is not None and snap["ai_difficulty"] is None and not snap["ai_untracked"]:
        snap["ai_difficulty"] = p["ai"]
        filled.append(f"AI level {p['ai']}")
        changed = True
    if not changed:
        return None, filled, kept
    payload = {"mark_complete": False, "ai_difficulty": snap["ai_difficulty"], "ai_untracked": snap["ai_untracked"],
               "event_notes": snap["event_notes"],
               "results": [{"driver_id": int(did), **r} for did, r in snap["results"].items()]}
    return payload, filled, kept


def fill_extras(conn, event, sessions, pace, username):
    """The rest of a weekend from the game: each session's weather, the winner's race time and the players' race
    times. Only blanks are filled. sessions: {"quali"|"sprint"|"race": [upload ids]}; pace: plan()["pace"].
    Returns (done, notes) as short phrases."""
    from . import ai3, engine, weather
    notes, done = [], []
    wx_in = {}   # each session's conditions, from the game sessions used for it
    for key, ids in (sessions or {}).items() if isinstance(sessions, dict) else ():
        ups = [telemetry.get(conn, i) for i in (ids or [])[:6] if isinstance(i, int)]
        seen = [w for u in ups if u for w in (u["session"].get("weather_seen") or []) + [u["session"].get("weather")]]
        wx_in[key] = telemetry.weather_key({"weather_seen": seen}) if seen else None
    have = weather.get(conn, event["id"])
    form = {f"weather_{k}": v for k, v in have.items()}
    added = [k for k in weather.sessions_for(event) if not have.get(k) and wx_in.get(k) in weather.CONDITIONS]
    form.update({f"weather_{k}": wx_in[k] for k in added})
    if added:
        weather.save(conn, event, form, username)
        done.append("weather for " + ", ".join(weather.SESSIONS[k].lower() for k in added))
    if not engine.round_v3(conn, event):
        return done, notes
    # the winner's race time, shared by every player's +gap times: P1's time in the game's race (or sprint)
    for key, sess in (("race", "gp"), ("sprint", "sprint")):
        ids = (sessions or {}).get(key) if isinstance(sessions, dict) else None
        if not ids or ai3.winner_time(conn, event["id"], sess) is not None:
            continue
        ups = [u for u in (telemetry.get(conn, i) for i in ids[:6] if isinstance(i, int)) if u]
        p1 = [r for u in ups if u["session"].get("kind") in ("race", "sprint_or_race") for r in u.get("results") or []
              if r.get("position") == 1 and r.get("status") == "Finished" and r.get("race_time_s")]
        if p1:
            ai3.save_winner_time(conn, event["id"], sess,
                                 ai3.format_time(round(p1[-1]["race_time_s"] + (p1[-1].get("penalty_s") or 0), 3)), username)
            done.append(("sprint" if sess == "sprint" else "race") + " winner's time")
    players = {r[0] for r in conn.execute("SELECT r.driver_id FROM results r JOIN drivers d ON d.id = r.driver_id "
                                          "WHERE r.event_id = ? AND d.is_player = 1", (event["id"],))}
    dmap = S.driver_map(conn)
    for p in (pace or [])[:20]:
        if not isinstance(p, dict) or p.get("driver_id") not in players or p.get("session") not in ("gp", "sprint"):
            continue
        old = ai3.pace_input(conn, event["id"], p["driver_id"], p["session"])
        if old and old["untracked"]:
            continue
        form = {k: ai3.format_time(old[k]) if old and old[k] is not None else ""
                for k in ("quali_time", "mate_quali_time", "comp_quali_time", "race_time", "bench_race_time")}
        form.update(laps=str(old["laps"]) if old and old["laps"] else "",
                    race_gap=str(old["race_gap"]) if old and old["race_gap"] is not None and not old["race_time"] else "",
                    comp_driver_id=str(old["comp_driver_id"] or "") if old else "",
                    representative="" if not old or old["representative"] is None else str(old["representative"]),
                    race_dnf="1" if old and old["race_dnf"] else "", bench_dnf="1" if old and old["bench_dnf"] else "",
                    untracked="", **{f"flag_{f}": "1" for f in (old["flag_list"] if old else [])})
        filled = []
        for key in ("quali_time", "mate_quali_time") if p["session"] == "gp" and not form["comp_quali_time"] else ():
            if not form[key] and isinstance(p.get(key), (int, float)) and p[key] > 0:
                form[key] = ai3.format_time(round(p[key], 3)); filled.append(key)
        if (not form["race_time"] and not form["bench_race_time"] and not form["race_gap"]
                and not form["comp_driver_id"] and all(isinstance(p.get(k), (int, float)) and p[k] > 0
                                                        for k in ("race_time", "bench_race_time"))):
            form["race_time"] = ai3.format_time(round(p["race_time"], 3))
            form["bench_race_time"] = ai3.format_time(round(p["bench_race_time"], 3))
            filled.append("race_time")
        elif (not form["race_time"] and not form["bench_race_time"] and not form["race_gap"] and not form["race_dnf"]
                and not form["bench_dnf"] and not form["comp_driver_id"] and (p.get("race_dnf") or p.get("bench_dnf"))):
            form["race_dnf"], form["bench_dnf"] = ("1" if p.get("race_dnf") else ""), ("1" if p.get("bench_dnf") else "")
            for key in ("race_time", "bench_race_time"):     # the one who finished keeps their time
                if isinstance(p.get(key), (int, float)) and p[key] > 0:
                    form[key] = ai3.format_time(round(p[key], 3))
            filled.append("race_time")
        if not form["laps"] and isinstance(p.get("laps"), int) and 1 <= p["laps"] <= 200:
            form["laps"] = str(p["laps"]); filled.append("laps")
        if not filled:
            continue
        try:
            ai3.save_pace_input(conn, event["id"], p["driver_id"], p["session"], form, username)
        except ValueError as exc:
            notes.append(f"{dmap[p['driver_id']]['name']}'s times weren't saved: {exc}")
            continue
        done.append(f"{dmap[p['driver_id']]['name']}'s {'Sprint' if p['session'] == 'sprint' else 'Grand Prix'} times")
    return done, notes


# --------------------------------------------------------------------------- the round's "ready to approve" state

def _meta_key(event_id):
    return f"autofill_{event_id}"


def state(conn, event_id):
    """The last background fill of a round: {"status": "ready" | "waiting", "at", "filled", "kept", "missing",
    "review", "notes", "why"}, or None."""
    try:
        data = json.loads(get_meta(conn, _meta_key(event_id)) or "null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def clear(conn, event_id):
    conn.execute("DELETE FROM meta WHERE key = ?", (_meta_key(event_id),))


def is_final_session(event, upload):
    """Whether an upload is the race that ends this round's weekend (the Grand Prix, not a Sprint or qualifying)."""
    kind = telemetry.KINDS.get(upload["session"].get("session_type_id"))
    if kind == "sprint_or_race":
        return not event["is_sprint"]
    return kind == "race"


def run(conn, event, username=GAME_USER, notify=True):
    """Fill a round from its game sessions, mark it ready to approve and (once per race) alert the league.
    Returns the saved state, or None when there's nothing from the game for this round."""
    from . import community, feed, gates
    from . import weekend as raceweek
    if event["status"] == C.EVENT_COMPLETE:
        return None
    bundle = telemetry.for_round(conn, event)
    if not bundle:
        return None
    why = raceweek.results_blocked(conn, event)
    if not why and not event.get("lights_at"):
        gate = gates.status(conn, event["id"], issue=False)
        if gate.get("blocking"):
            why = "This round can't start yet. Waiting on: " + gates.waiting_text(gate) + "."
    before = state(conn, event["id"])
    info = {"at": now_iso(), "race_id": (bundle.get("race") or {}).get("id"), "filled": [], "kept": [], "missing": [],
            "review": 0, "notes": [], "why": None}
    if why:
        info.update(status="waiting", why=why)
        set_meta(conn, _meta_key(event["id"]), json.dumps(info))
        return info
    p = plan(conn, event, bundle)
    payload, filled, kept = results_payload(conn, event, p)
    if payload:
        try:
            S.save_weekend(conn, event["id"], payload, allow_no_fault=False)
        except S.ValidationError as exc:
            info["notes"].append(f"The results couldn't be saved: {exc}")
            filled = []
    done, notes = fill_extras(conn, S.get_event(conn, event["id"]), p["by_session"], p["pace"], username)
    for uid in p["upload_ids"][:8] or [None]:
        telemetry.applied(conn, uid, event["id"], p["names"])
    info.update(status="ready", filled=filled + done, kept=kept, missing=p["missing"], review=p["review"],
                notes=info["notes"] + notes)
    set_meta(conn, _meta_key(event["id"]), json.dumps(info))
    year = S.get_season(conn, event["season_id"])["year"]
    if filled or done:
        community.audit(conn, username, "Filled from the game", f"R{event['round_number']} {event['name']}",
                        summary=f"filled {year} R{event['round_number']} {event['name']} from the game's telemetry: "
                        + "; ".join(filled + done), link=f"weekend/{event['id']}")
    if notify and not (before and before.get("status") == "ready" and before.get("race_id") == info["race_id"]):
        what = "check and approve them" if not p["missing"] else "a few drivers still need filling in, then approve"
        feed.notify(conn, None, f"R{event['round_number']} {event['name']}: the results are in from the game. "
                    f"Open the round to {what}.", f"weekend/{event['id']}?stage=review", category="results",
                    email=False, dedupe=f"autofill:{event['id']}:{info['race_id']}")
    return info


def after_upload(conn, upload_id):
    """Called when the recorder sends a session: if it's a round's race, get that round ready to approve."""
    if not enabled(conn):
        return None
    row = conn.execute("SELECT used_event_id FROM telemetry_uploads WHERE id = ?", (upload_id,)).fetchone()
    event = S.get_event(conn, row["used_event_id"]) if row and row["used_event_id"] else None
    upload = telemetry.get(conn, upload_id)
    if not event or not upload or not is_final_session(event, upload):
        return None
    return run(conn, event)
