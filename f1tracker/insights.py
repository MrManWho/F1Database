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


def progression_chart(conn, season_id, top=4, max_series=8):
    """Series for the title-fight chart: the top of the table plus the player drivers (up to 8 lines)."""
    table = S.driver_standings(conn, season_id)
    ids = [r["driver_id"] for r in table[:top]]
    for r in table:
        if r["driver"]["is_player"] and r["driver_id"] not in ids and len(ids) < max_series:
            ids.append(r["driver_id"])
    labels, series = points_progression(conn, season_id, ids)
    everyone = [r["driver_id"] for r in table]
    _, all_series = points_progression(conn, season_id, everyone)
    ranks = {d: [] for d in ids}  # championship position after each round (ties share the better place)
    for i in range(len(labels)):
        col = [all_series[d][i] for d in everyone]
        for d in ids:
            ranks[d].append(1 + sum(1 for v in col if v > series[d][i]))
    dmap = S.driver_map(conn)
    # Colour follows the driver: player drivers keep their own slot (by join order); others fill the rest.
    player_slots = {p["id"]: i + 1 for i, p in enumerate(S.player_drivers(conn)) if i < max_series}
    used = {player_slots[d] for d in ids if d in player_slots}
    free = [n for n in range(1, max_series + 1) if n not in used]
    out = []
    for d in ids:
        slot = player_slots.get(d) or free.pop(0)
        out.append({"name": dmap[d]["name"], "values": series[d], "player": bool(dmap[d]["is_player"]), "slot": slot,
                    "color": dmap[d]["player_color"] if dmap[d]["is_player"] else None, "positions": ranks[d]})
    return {"labels": labels, "yLabel": "Points", "series": out, "markers": len(labels) < 12}


def driver_round_timeline(conn, driver_id):
    """Form and Reputation after every round the driver took part in, across the whole career."""
    labels, form, rep = [], [], []
    start_rep = None
    for season in S.list_seasons(conn):
        start = S.starting_reputation(conn, season["id"], driver_id)
        start_rep = start if start_rep is None or season["id"] == S.current_season_id(conn) else start_rep
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
    return {"labels": labels, "form": form, "reputation": rep, "start_rep": start_rep, "start_form": 50.0}


def _accumulate(s, r):
    S.accumulate_result(s, r, r["is_sprint"])


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
        if pct > 0:
            award("Mr Consistent", r, f"{pct * 100:.0f}%", "of races in the points")
    improved = [(r["reputation"] - r["starting_reputation"], r) for r in table]
    if improved:
        delta, r = max(improved, key=lambda x: x[0])
        if delta > 0:
            award("Most improved", r, f"+{delta:.1f}", "Reputation gained")
    rows_all = _season_rows(conn, season_id)
    iron = [(sum(1 for x in rows_all if x["driver_id"] == r["driver_id"] and x["result_status"] == C.STATUS_FINISHED), r)
            for r in table if r["starts"] >= 3 and r["dnfs"] == 0]
    if iron:
        n, r = max(iron, key=lambda x: (x[0], x[1]["points"]))
        award("Iron man", r, f"{n} finishes", "not a single DNF")
    quali = []
    for r in table:
        qs = [x["qualifying_position"] for x in rows_all if x["driver_id"] == r["driver_id"] and x["qualifying_position"]]
        if len(qs) >= 3:
            quali.append((sum(qs) / len(qs), r))
    if quali:
        q, r = min(quali, key=lambda x: (x[0], -x[1]["points"]))
        award("Qualifying ace", r, f"P{q:.1f}", "average grid slot")
    drives = [x for x in rows_all if x["result_status"] == C.STATUS_FINISHED and x["race_position"]
              and x["qualifying_position"] and x["qualifying_position"] > x["race_position"]]
    if drives:
        best = max(drives, key=lambda x: (x["qualifying_position"] - x["race_position"], -x["race_position"]))
        row = next((r for r in table if r["driver_id"] == best["driver_id"]), None)
        award("Drive of the season", row, f"P{best['qualifying_position']} → P{best['race_position']}",
              f"R{best['round_number']} {best['event_name']}")
    fans = conn.execute("""SELECT v.driver_id, COUNT(*) AS n FROM fan_votes v JOIN events e ON e.id = v.event_id
                           WHERE e.season_id = ? GROUP BY v.driver_id ORDER BY n DESC LIMIT 1""", (season_id,)).fetchone()
    if fans:
        row = next((r for r in table if r["driver_id"] == fans["driver_id"]), None)
        award("Fans' choice", row, f"{fans['n']} vote{'s' if fans['n'] != 1 else ''}", "fan Driver of the Day votes")
    rookies = [r for r in table if _first_season_year(conn, r["driver_id"]) == season["year"]
               and (r["driver"]["is_player"] or season["year"] != first_year)]
    if rookies and rookies[0]["points"] > 0:
        award("Rookie of the year", rookies[0], f"P{rookies[0]['position']}", f"{rookies[0]['points']} pts")

    players = [r for r in table if r["driver"]["is_player"]]
    return {"season": season, "awards": awards, "table": table[:10], "teams": teams[:5], "players": players,
            "champion_team": teams[0] if teams and teams[0]["points"] else None}


def standings_with_changes(conn, season_id, limit=8):
    """Driver standings with places gained/lost since the previous round (by points)."""
    table = S.driver_standings(conn, season_id)
    ids = [r["driver_id"] for r in table]
    labels, series = points_progression(conn, season_id, ids)
    if len(labels) >= 2:
        before = sorted(ids, key=lambda d: (-series[d][-2], next(r["position"] for r in table if r["driver_id"] == d)))
        prev = {d: i + 1 for i, d in enumerate(before)}
        for r in table:
            r["change"] = prev[r["driver_id"]] - r["position"]
    else:
        for r in table:
            r["change"] = 0
    top = table[:limit]
    extra = [r for r in table[limit:] if r["driver"]["is_player"]]
    return top + extra


def driver_card(conn, season_id, driver_id):
    """Everything the dashboard's 'your driver' panel shows."""
    row = next((r for r in S.driver_standings(conn, season_id) if r["driver_id"] == driver_id), None)
    recent = conn.execute("""SELECT r.*, e.round_number, e.name AS event_name, e.is_sprint FROM results r
                             JOIN events e ON e.id = r.event_id WHERE r.driver_id = ? AND e.season_id = ?
                             AND e.status = ? ORDER BY e.round_number DESC LIMIT 5""",
                          (driver_id, season_id, C.EVENT_COMPLETE)).fetchall()
    form = []
    for r in reversed(recent):
        finished = r["result_status"] == C.STATUS_FINISHED and r["race_position"]
        form.append({"round": r["round_number"], "event": r["event_name"],
                     "label": f"P{r['race_position']}" if finished else r["result_status"],
                     "kind": "win" if finished and r["race_position"] == 1 else
                             "points" if finished and r["race_position"] <= 10 else
                             "finish" if finished else "out"})
    return {"row": row, "form": form, "driver": S.driver_map(conn)[driver_id]}


def all_time_records(conn):
    """Single-season and single-race bests, plus streaks, across every season of the league."""
    dmap = S.driver_map(conn)
    records = []

    def add(title, driver_id, value, note=""):
        if driver_id in dmap:
            records.append({"title": title, "driver": dmap[driver_id], "value": value, "note": note})

    cache = S.all_season_standings(conn)
    season_rows = [(data["season"], r) for data in cache.values() for r in data["drivers"] if r.get("has_results", True)]
    for key, title, unit in (("points", "Most points in a season", "pts"), ("wins", "Most wins in a season", "wins"),
                             ("poles", "Most poles in a season", "poles"), ("podiums", "Most podiums in a season", "podiums")):
        best = max(season_rows, key=lambda x: (x[1][key], x[1]["points"]), default=None)
        if best and best[1][key]:
            add(title, best[1]["driver_id"], f"{best[1][key]} {unit}", str(best[0]["year"]))

    rows = conn.execute("""SELECT r.*, e.round_number, e.name AS event_name, s.year FROM results r
                           JOIN events e ON e.id = r.event_id JOIN seasons s ON s.id = e.season_id
                           WHERE e.status = ? ORDER BY s.year, e.round_number""", (C.EVENT_COMPLETE,)).fetchall()
    drives = [r for r in rows if r["result_status"] == C.STATUS_FINISHED and r["race_position"]
              and r["qualifying_position"] and r["qualifying_position"] > r["race_position"]]
    if drives:
        best = max(drives, key=lambda x: (x["qualifying_position"] - x["race_position"], -x["race_position"]))
        add("Biggest comeback", best["driver_id"],
            f"+{best['qualifying_position'] - best['race_position']} places",
            f"P{best['qualifying_position']} → P{best['race_position']}, {best['year']} {best['event_name']}")
    wins_from = [r for r in rows if r["race_position"] == 1 and r["result_status"] == C.STATUS_FINISHED
                 and r["qualifying_position"]]
    if wins_from:
        best = max(wins_from, key=lambda x: x["qualifying_position"])
        if best["qualifying_position"] > 1:
            add("Win from furthest back", best["driver_id"], f"from P{best['qualifying_position']}",
                f"{best['year']} {best['event_name']}")

    def streak(test):
        best, current = {}, {}
        for r in rows:
            d = r["driver_id"]
            current[d] = current.get(d, 0) + 1 if test(r) else 0
            if current[d] > best.get(d, (0,))[0]:
                best[d] = (current[d], r["year"], r["event_name"])
        return max(best.items(), key=lambda x: x[1][0], default=None)

    for title, test, unit in (
            ("Longest winning streak", lambda r: r["race_position"] == 1 and r["result_status"] == C.STATUS_FINISHED, "wins"),
            ("Longest podium streak", lambda r: r["result_status"] == C.STATUS_FINISHED and r["race_position"]
             and r["race_position"] <= 3, "podiums"),
            ("Longest points streak", lambda r: r["result_status"] == C.STATUS_FINISHED and r["race_position"]
             and r["race_position"] <= 10, "races")):
        found = streak(test)
        if found and found[1][0] >= 2:
            add(title, found[0], f"{found[1][0]} {unit} in a row", f"ending {found[1][1]} {found[1][2]}")

    champions = []
    for data in cache.values():
        season = data["season"]
        if season["status"] == C.SEASON_COMPLETE and data["drivers"] and data["drivers"][0]["points"]:
            champions.append({"season": season, "driver": dmap.get(data["drivers"][0]["driver_id"]),
                              "points": data["drivers"][0]["points"]})
    return {"records": records, "champions": sorted(champions, key=lambda c: -c["season"]["year"])}


# --------------------------------------------------------------------------- round-on-round changes

STAT_HELP = {
    "form": "Form: how well the driver is driving right now, from finishes, qualifying and racecraft this season (1-100).",
    "reputation": "Reputation: long-term standing in the paddock. Carries between seasons (1-100).",
    "value": "Driver Value: what teams look at when making offers. Market score, Form and car-adjusted results combined.",
    "car": "Car-Adjusted: results compared with what the car would normally achieve. 50 = exactly what the car is worth.",
    "points": "Championship points this season.",
    "position": "Position in the Drivers' Championship (WDC).",
    "tier": "Market tier: how teams see the driver, from Reputation and Form.",
}


def stat_changes(conn, season_id, driver_id):
    """Each headline number now, after the previous completed round, and round by round for sparklines.

    Uses the normal calculations, just stopped at an earlier round, so nothing here changes a formula.
    """
    from . import market  # market imports this module's siblings; keep the import local
    rounds = [r["round_number"] for r in conn.execute(
        "SELECT round_number FROM events WHERE season_id = ? AND status = ? ORDER BY round_number",
        (season_id, C.EVENT_COMPLETE))]
    ranks = S.team_strength_ranks(conn, season_id)

    def snapshot(upto):
        table = S.driver_standings(conn, season_id, upto)
        by_id = {r["driver_id"]: r for r in table}
        row = by_id.get(driver_id)
        v = market.driver_value(conn, season_id, driver_id, standings=by_id, ranks=ranks, upto_round=upto)
        return {"form": v["form"], "reputation": v["reputation"], "value": v["value"], "car": v["car"],
                "points": row["points"] if row else 0, "position": row["position"] if row else None,
                "tier": row["market"]["name"] if row else None,
                "tier_rank": next((i for i, t in enumerate(C.MARKET_TIERS) if row and t[1] == row["market"]["name"]), None)}

    now = snapshot(None)
    prev = snapshot(rounds[-2]) if len(rounds) >= 2 else None
    series = {k: [] for k in ("form", "reputation", "value", "points", "position")}
    if len(rounds) >= 3:
        for rn in rounds[-12:]:
            snap = now if rn == rounds[-1] else snapshot(rn)
            for k in series:
                series[k].append(snap[k])
    out = {}
    for key in ("form", "reputation", "value", "car", "points", "position", "tier"):
        cur = now[key]
        before = prev[key] if prev else None
        if key == "position":
            change = (before - cur) if before and cur else None  # climbing the table is positive
        elif key == "tier":
            change = None
            if prev and prev["tier_rank"] is not None and now["tier_rank"] is not None:
                change = prev["tier_rank"] - now["tier_rank"]
        else:
            change = round(cur - before, 1) if before is not None and cur is not None else None
        out[key] = {"now": cur, "prev": before, "change": change, "series": series.get(key, []),
                    "help": STAT_HELP[key]}
    out["since"] = f"R{rounds[-2]}" if prev else None
    out["latest"] = f"R{rounds[-1]}" if rounds else None
    return out


# --------------------------------------------------------------------------- post-race summary

def race_summary(conn, event_id):
    """Everything that happened at one completed weekend, from the stored results (scoring untouched)."""
    event = S.get_event(conn, event_id)
    season = S.get_season(conn, event["season_id"])
    sid, rn = season["id"], event["round_number"]
    rows = S.weekend_rows(conn, event_id)
    finished = sorted((r for r in rows if r["result_status"] == C.STATUS_FINISHED and r["race_position"]),
                      key=lambda r: r["race_position"])
    podium = finished[:3]
    pole = next((r for r in rows if r["qualifying_position"] == 1), None)
    sprint_winner = next((r for r in rows if event["is_sprint"] and r["sprint_position"] == 1
                          and r["sprint_status"] == C.STATUS_FINISHED), None)
    fastest = next((r for r in rows if r["fastest_lap"]), None)
    dotd = next((r for r in rows if r["driver_of_day"]), None)
    earlier = [e["round_number"] for e in S.events(conn, sid)
               if e["status"] == C.EVENT_COMPLETE and e["round_number"] < rn]
    prev_rn = earlier[-1] if earlier else None
    after = {r["driver_id"]: r for r in S.driver_standings(conn, sid, rn)}
    before = {r["driver_id"]: r for r in S.driver_standings(conn, sid, prev_rn)} if prev_rn else {}
    wcc_after = S.constructor_standings(conn, sid, rn)
    wcc_before = {t["team"]["id"]: t["position"] for t in S.constructor_standings(conn, sid, prev_rn)} if prev_rn else {}
    humans = []
    for r in rows:
        if not r["driver"]["is_player"]:
            continue
        a, b = after.get(r["driver_id"]), before.get(r["driver_id"])
        done = r["result_status"] == C.STATUS_FINISHED and r["race_position"]
        humans.append({
            "row": r, "driver": r["driver"], "team": r["team"],
            "race": f"P{r['race_position']}" if done else r["result_status"],
            "sprint": (f"P{r['sprint_position']}" if r["sprint_status"] == C.STATUS_FINISHED and r["sprint_position"]
                       else r["sprint_status"]) if event["is_sprint"] else None,
            "quali": f"P{r['qualifying_position']}" if r["qualifying_position"] else "—",
            "gained": (r["qualifying_position"] - r["race_position"]) if done and r["qualifying_position"] else None,
            "points": r["gp_points"] + r["sprint_pts"],
            "form": a["form"] if a else None, "form_change": round(a["form"] - (b["form"] if b else 50.0), 1) if a else None,
            "rep": a["reputation"] if a else None,
            "rep_change": round(a["reputation"] - (b["reputation"] if b else a["starting_reputation"]), 1) if a else None,
            "wdc": a["position"] if a else None,
            "wdc_change": (b["position"] - a["position"]) if a and b else None,
        })
    rivalry = None
    if len(humans) >= 2:
        pairs = []
        for i in range(len(humans)):
            for j in range(i + 1, len(humans)):
                x, y = humans[i], humans[j]
                rx, ry = _race_rank(x["row"]), _race_rank(y["row"])
                ahead = x if rx and (not ry or rx < ry) else y if ry and (not rx or ry < rx) else None
                pairs.append({"a": x["driver"], "b": y["driver"], "ahead": ahead["driver"] if ahead else None,
                              "a_points": x["points"], "b_points": y["points"],
                              "gap": (after[x["driver"]["id"]]["points"] - after[y["driver"]["id"]]["points"])
                              if x["driver"]["id"] in after and y["driver"]["id"] in after else None})
        rivalry = pairs
    top = sorted(after.values(), key=lambda r: r["position"])[:5]
    wdc_top = [{"row": r, "change": (before[r["driver_id"]]["position"] - r["position"]) if r["driver_id"] in before else None}
               for r in top]
    wcc_top = [{"row": t, "change": (wcc_before[t["team"]["id"]] - t["position"]) if t["team"]["id"] in wcc_before else None}
               for t in wcc_after[:5]]
    headlines = [dict(n) for n in conn.execute("SELECT * FROM news WHERE link = ? ORDER BY id", (f"weekend/{event_id}",))]
    milestones = [n for n in headlines if n["kind"] in ("player",)]
    nxt = S.difficulty_recommendation(conn, (season["year"], rn + 1))
    return {"event": event, "season": season, "podium": podium, "pole": pole, "sprint_winner": sprint_winner,
            "fastest": fastest, "dotd": dotd, "humans": humans, "rivalry": rivalry, "wdc": wdc_top, "wcc": wcc_top,
            "milestones": milestones, "headlines": headlines, "rec": nxt, "first_round": prev_rn is None}


# --------------------------------------------------------------------------- season progress card

def season_progress(conn, season_id):
    """Figures for the Control Room's completion card (all read from stored results)."""
    evs = S.events(conn, season_id)
    total = len(evs)
    done = [e for e in evs if e["status"] == C.EVENT_COMPLETE]
    sprints = [e for e in evs if e["is_sprint"]]
    diffs = [e["ai_difficulty"] for e in done if e["ai_difficulty"] is not None]
    table = S.driver_standings(conn, season_id)
    teams = S.constructor_standings(conn, season_id)
    wdc = table[0] if table and table[0]["points"] > 0 else None
    wcc = teams[0] if teams and teams[0]["points"] > 0 else None
    milestone = None
    if total and len(done) < total:
        marks = [(1, "First round"), (5, "Five rounds completed"), (-(-total // 4), "A quarter of the season"),
                 (-(-total // 2), "Halfway"), (-(-total * 3 // 4), "Three-quarters done"), (total, "Final round")]
        upcoming = sorted({(n, label) for n, label in marks if len(done) < n <= total}, key=lambda m: m[0])
        if upcoming:
            n, label = upcoming[0]
            milestone = {"label": label, "round": n, "to_go": n - len(done)}
    left = [e for e in evs if e["status"] != C.EVENT_COMPLETE]
    nxt = left[0] if left else None
    scheduled = [e["race_at"] for e in evs if e["race_at"]]
    unscheduled_left = sum(1 for e in left if not e["race_at"])
    return {"total": total, "completed": len(done), "pct": round(len(done) / total * 100) if total else 0,
            "remaining": len(left), "sprints_left": sum(1 for e in left if e["is_sprint"]),
            "current": nxt, "next_event": nxt,
            # Projected finish: the latest scheduled race, if every remaining round has a date; otherwise say so.
            "finish_at": max(scheduled) if scheduled and not unscheduled_left and left else None,
            "last_scheduled": max(scheduled) if scheduled else None, "unscheduled_left": unscheduled_left,
            "sprints_done": sum(1 for e in done if e["is_sprint"]), "sprints_total": len(sprints),
            "wdc": wdc, "wcc": wcc, "avg_ai": round(sum(diffs) / len(diffs), 1) if diffs else None,
            "ai_rounds": len(diffs), "milestone": milestone}


def pending_actions(conn, ctx):
    """Things waiting for the person looking at the Control Room, most urgent first: (text, link, tone)."""
    from . import gates, relations, seats, teamlife, timefmt
    out = []
    sid = ctx["current_season_id"]
    me = ctx.get("my_driver")
    if me:
        if ctx.get("pending_offers"):
            n = ctx["pending_offers"]
            out.append((f"{n} contract offer{'s' if n != 1 else ''} waiting for your answer", "garage#offers", "hot"))
        if relations.needs_pledge(conn, sid, me["id"]):
            out.append(("Choose your growth pledge for this season", "pledge", "hot"))
        todo = gates.my_todo(conn, sid, me["id"])
        if todo and todo["press"]:
            out.append((f"Answer {todo['press']} press question{'s' if todo['press'] != 1 else ''} before "
                        f"R{todo['event']['round_number']} can start", "dashboard#press", "warn"))
        nxt = S.next_incomplete_event(conn, sid)
        if nxt and ctx["team_life"]["targets"]:
            t = teamlife.target_for(conn, nxt["id"], me["id"])
            if t and not t["acknowledged_at"] and t["status"] == "Set":
                out.append((f"Accept your R{nxt['round_number']} weekend target", "dashboard#target", "warn"))
    if ctx.get("is_master"):
        reqs = conn.execute("SELECT COUNT(*) FROM join_requests WHERE status = 'Pending'").fetchone()[0]
        if reqs:
            out.append((f"{reqs} join request{'s' if reqs != 1 else ''} to answer", "members", "hot"))
        inc = conn.execute("SELECT COUNT(*) FROM incidents WHERE status = 'Open'").fetchone()[0]
        if inc:
            out.append((f"{inc} incident report{'s' if inc != 1 else ''} to rule on", "incidents", "warn"))
        probs = seats.problems(conn, sid)
        if probs:
            out.append((f"{len(probs)} seat/contract problem{'s' if len(probs) != 1 else ''} to resolve", "grid#contracts", "hot"))
    if ctx.get("can_run"):
        window = ctx.get("race_window")
        for e in S.events(conn, sid):
            code, _label = timefmt.race_status(e["race_at"], e["status"], window, postponed=e["postponed"])
            if code == "pending":
                out.append((f"Results pending for R{e['round_number']} {e['name']}", f"weekend/{e['id']}", "warn"))
    return out
