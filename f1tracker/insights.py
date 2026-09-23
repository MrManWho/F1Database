"""Derived views: points progression, form/reputation timelines, the player rivalry and season awards."""

from . import constants as C
from . import services as S


def _season_rows(conn, season_id):
    return conn.execute("""SELECT r.*, e.round_number, e.name AS event_name, e.is_sprint, e.status AS event_status
                           FROM results r JOIN events e ON e.id = r.event_id
                           WHERE e.season_id = ? AND e.status != ? ORDER BY e.round_number""",
                        (season_id, C.EVENT_NOT_RUN)).fetchall()


def _points(r):
    return S.gp_points(r["race_position"], r["result_status"]) + \
        S.sprint_points(r["sprint_position"], r["sprint_status"], bool(r["is_sprint"]))


def points_progression(conn, season_id, driver_ids):
    """Cumulative championship points after every round that has results."""
    rounds = [e for e in S.events(conn, season_id) if e["status"] != C.EVENT_NOT_RUN]
    totals = {d: 0 for d in driver_ids}
    series = {d: [] for d in driver_ids}
    by_event = {}
    for r in _season_rows(conn, season_id):
        by_event.setdefault(r["event_id"], {})[r["driver_id"]] = _points(r)
    for e in rounds:
        for d in driver_ids:
            totals[d] += by_event.get(e["id"], {}).get(d, 0)
            series[d].append(totals[d])
    return [f"R{e['round_number']}" for e in rounds], series


def progression_chart(conn, season_id, top=4):
    """Series for the dashboard chart: the top of the table plus both player drivers."""
    table = S.driver_standings(conn, season_id)
    ids = [r["driver_id"] for r in table[:top]]
    for p in S.player_drivers(conn):
        if p["id"] not in ids and any(r["driver_id"] == p["id"] for r in table):
            ids.append(p["id"])
    labels, series = points_progression(conn, season_id, ids)
    dmap = S.driver_map(conn)
    # Colour follows the driver: players keep slots 1 and 2 everywhere; the others take 3 onwards.
    player_slots = {p["id"]: i + 1 for i, p in enumerate(S.player_drivers(conn)[:2])}
    out, next_slot = [], 3
    for d in ids:
        slot = player_slots.get(d)
        if slot is None:
            slot, next_slot = next_slot, next_slot + 1
        out.append({"name": dmap[d]["name"], "values": series[d], "player": bool(dmap[d]["is_player"]), "slot": slot})
    return {"labels": labels, "yLabel": "Points", "series": out}


def driver_round_timeline(conn, driver_id):
    """Form and Reputation after every round the driver took part in, across the whole career."""
    labels, form, rep = [], [], []
    for season in S.list_seasons(conn):
        start = S.starting_reputation(conn, season["id"], driver_id)
        stats = S._blank_stats()
        state = conn.execute("SELECT locked_reputation FROM season_driver_state WHERE season_id = ? AND driver_id = ?",
                             (season["id"], driver_id)).fetchone()
        rows = [r for r in _season_rows(conn, season["id"]) if r["driver_id"] == driver_id and S._result_has_data(r)]
        for i, r in enumerate(rows):
            _accumulate(stats, r)
            s = S._finalise(dict(stats, finishes=list(stats["finishes"]), qualis=list(stats["qualis"])))
            f = S.compute_form(s)
            value = S.compute_reputation(start, s, f)
            if i == len(rows) - 1 and state and state["locked_reputation"] is not None:
                value = state["locked_reputation"]
            labels.append(f"{str(season['year'])[2:]} R{r['round_number']}")
            form.append(f)
            rep.append(value)
    return {"labels": labels, "form": form, "reputation": rep}


def _accumulate(s, r):
    s["has_results"] = True
    gp = S.gp_points(r["race_position"], r["result_status"])
    sp = S.sprint_points(r["sprint_position"], r["sprint_status"], bool(r["is_sprint"]))
    s["points"] += gp + sp
    s["gp_points"] += gp
    s["sprint_points"] += sp
    finished = r["result_status"] == C.STATUS_FINISHED
    pos = r["race_position"]
    s["wins"] += int(finished and pos == 1)
    s["podiums"] += int(bool(finished and pos and pos <= 3))
    s["poles"] += int(r["qualifying_position"] == 1)
    s["fastest_laps"] += int(bool(r["fastest_lap"]))
    s["dotds"] += int(bool(r["driver_of_day"]))
    s["dnfs"] += int(r["result_status"] == "DNF")
    s["starts"] += int(r["result_status"] in C.START_STATUSES)
    if pos:
        s["finishes"].append(pos)
    if r["qualifying_position"]:
        s["qualis"].append(r["qualifying_position"])


# --------------------------------------------------------------------------- rivalry

def _race_rank(r):
    if r["result_status"] == C.STATUS_FINISHED and r["race_position"]:
        return r["race_position"]
    if r["result_status"] in ("DNF", "DSQ"):
        return 100
    return None


def rivalry(conn, a_id, b_id):
    """All-time head-to-head between two drivers, event by event."""
    rows = conn.execute("""SELECT r.*, e.id AS eid, e.name AS event_name, e.round_number, e.is_sprint,
                           s.year, s.id AS season_id FROM results r JOIN events e ON e.id = r.event_id
                           JOIN seasons s ON s.id = e.season_id
                           WHERE r.driver_id IN (?, ?) AND e.status != ? ORDER BY s.year, e.round_number""",
                        (a_id, b_id, C.EVENT_NOT_RUN)).fetchall()
    events = {}
    for r in rows:
        events.setdefault(r["eid"], {})[r["driver_id"]] = r
    out = {"race": [0, 0], "quali": [0, 0], "points": [0, 0], "wins": [0, 0], "podiums": [0, 0],
           "poles": [0, 0], "best_margin": [None, None], "streak": [0, 0], "current": None,
           "tracks": {}, "timeline": [], "swing": [], "labels": [], "seasons": {}}
    run = [0, 0]
    swing = 0
    for eid, pair in events.items():
        a, b = pair.get(a_id), pair.get(b_id)
        for idx, r in ((0, a), (1, b)):
            if r is None:
                continue
            out["points"][idx] += _points(r)
            finished = r["result_status"] == C.STATUS_FINISHED
            out["wins"][idx] += int(finished and r["race_position"] == 1)
            out["podiums"][idx] += int(bool(finished and r["race_position"] and r["race_position"] <= 3))
            out["poles"][idx] += int(r["qualifying_position"] == 1)
            season = out["seasons"].setdefault(r["year"], {"points": [0, 0], "race": [0, 0], "quali": [0, 0]})
            season["points"][idx] += _points(r)
        if not (a and b):
            continue
        season = out["seasons"][a["year"]]
        if a["qualifying_position"] and b["qualifying_position"]:
            q = 0 if a["qualifying_position"] < b["qualifying_position"] else 1
            out["quali"][q] += 1
            season["quali"][q] += 1
        ra, rb = _race_rank(a), _race_rank(b)
        if ra is None or rb is None or ra == rb:
            continue
        w = 0 if ra < rb else 1
        out["race"][w] += 1
        season["race"][w] += 1
        run[w] += 1
        run[1 - w] = 0
        out["streak"][w] = max(out["streak"][w], run[w])
        out["current"] = (w, run[w])
        if ra < 100 and rb < 100:
            margin = abs(ra - rb)
            if out["best_margin"][w] is None or margin > out["best_margin"][w]["margin"]:
                out["best_margin"][w] = {"margin": margin, "event": f"{a['year']} {a['event_name']}"}
        track = out["tracks"].setdefault(a["event_name"], {"race": [0, 0], "best": [None, None]})
        track["race"][w] += 1
        for idx, r in ((0, a), (1, b)):
            if r["result_status"] == C.STATUS_FINISHED and r["race_position"]:
                best = track["best"][idx]
                track["best"][idx] = r["race_position"] if best is None else min(best, r["race_position"])
        swing += 1 if w == 0 else -1
        out["swing"].append(swing)
        out["labels"].append(f"{str(a['year'])[2:]} R{a['round_number']}")
        out["timeline"].append({"event": f"{a['year']} {a['event_name']}", "a": a, "b": b, "winner": w})
    out["timeline"].reverse()
    out["tracks"] = sorted(out["tracks"].items(), key=lambda kv: -(kv[1]["race"][0] + kv[1]["race"][1]))
    out["seasons"] = sorted(out["seasons"].items())
    return out


# --------------------------------------------------------------------------- season review & awards

def _first_season_year(conn, driver_id):
    row = conn.execute("""SELECT MIN(s.year) FROM results r JOIN events e ON e.id = r.event_id
                          JOIN seasons s ON s.id = e.season_id WHERE r.driver_id = ? AND r.result_status IN (?,?,?)""",
                       (driver_id, *sorted(C.START_STATUSES))).fetchone()
    return row[0]


def season_review(conn, season_id):
    season = S.get_season(conn, season_id)
    table = [r for r in S.driver_standings(conn, season_id) if r["has_results"]]
    teams = S.constructor_standings(conn, season_id)
    first_year = S.list_seasons(conn)[0]["year"]
    awards = []

    def award(title, row, value, note=""):
        if row:
            awards.append({"title": title, "driver": row["driver"], "team": row["team"], "value": value, "note": note})

    if table and table[0]["points"]:
        award("Drivers' Champion" if season["status"] == C.SEASON_COMPLETE else "Championship leader",
              table[0], f"{table[0]['points']} pts", f"{table[0]['wins']} wins")
        if len(table) > 1:
            award("Runner-up", table[1], f"{table[1]['points']} pts",
                  f"{table[0]['points'] - table[1]['points']} behind")

    def top(key, title, unit, minimum=1):
        best = max(table, key=lambda r: (r[key], r["points"]), default=None)
        if best and best[key] >= minimum:
            award(title, best, f"{best[key]} {unit}")

    top("wins", "Most wins", "wins")
    top("poles", "Pole king", "poles")
    top("podiums", "Podium regular", "podiums")
    top("dotds", "Fan favourite", "Driver of the Day awards")

    gains = []
    for r in table:
        rows = [x for x in _season_rows(conn, season_id) if x["driver_id"] == r["driver_id"]
                and x["result_status"] == C.STATUS_FINISHED and x["race_position"] and x["qualifying_position"]]
        if len(rows) >= 3:
            gains.append((sum(x["qualifying_position"] - x["race_position"] for x in rows) / len(rows), r))
    if gains:
        g, r = max(gains, key=lambda x: x[0])
        if g > 0:
            award("Overtaker of the year", r, f"+{g:.1f}", "places gained per race")
    consistent = [(sum(1 for f in r["finishes"] if f <= 10) / max(1, r["starts"]), r) for r in table if r["starts"] >= 3]
    if consistent:
        pct, r = max(consistent, key=lambda x: (x[0], x[1]["points"]))
        award("Mr Consistent", r, f"{pct * 100:.0f}%", "of races in the points")
    improved = [(r["reputation"] - r["starting_reputation"], r) for r in table]
    if improved:
        delta, r = max(improved, key=lambda x: x[0])
        if delta > 0:
            award("Most improved", r, f"+{delta:.1f}", "Reputation gained")
    rookies = [r for r in table if _first_season_year(conn, r["driver_id"]) == season["year"]
               and (r["driver"]["is_player"] or season["year"] != first_year)]
    if rookies:
        award("Rookie of the year", rookies[0], f"P{rookies[0]['position']}", f"{rookies[0]['points']} pts")

    players = [r for r in table if r["driver"]["is_player"]]
    return {"season": season, "awards": awards, "table": table[:10], "teams": teams[:5], "players": players,
            "champion_team": teams[0] if teams and teams[0]["points"] else None}
