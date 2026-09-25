"""Statistics views (v2.0). Everything here reads submitted (Complete) rounds only and never changes stored data,
so the numbers match the standings and nothing historical is recalculated."""

from . import calc3, engine
from . import constants as C
from . import services as S

BUCKETS = [("win", "Wins", lambda p: p == 1), ("podium", "P2–P3", lambda p: 2 <= p <= 3),
           ("points", "P4–P10", lambda p: 4 <= p <= 10), ("outside", "P11+", lambda p: p >= 11)]


def _rows(conn, season_id):
    return [dict(r) for r in conn.execute(
        """SELECT r.*, e.round_number, e.is_sprint FROM results r JOIN events e ON e.id = r.event_id
           WHERE e.season_id = ? AND e.status = ? ORDER BY e.round_number""", (season_id, C.EVENT_COMPLETE))]


def _started(r):
    return r["result_status"] not in (C.STATUS_NOT_RUN, "DNS")


def season(conn, season_id, players_only=False):
    """Per-driver breakdowns for one season: finishes, qualifying vs race, Sprint points, reliability."""
    dmap, tmap = S.driver_map(conn), S.team_map(conn)
    out = {}
    pts = calc3.Points(conn)
    for r in _rows(conn, season_id):
        d = dmap.get(r["driver_id"])
        if not d or (players_only and not d["is_player"]):
            continue
        s = out.setdefault(d["id"], {"driver": d, "team": tmap.get(r["team_id"]), "starts": 0, "finished": 0,
                                     "dnf": 0, "dns": 0, "dsq": 0, "classified": 0, "quali": [], "race": [], "gained": [],
                                     "sprint_points": 0, "sprints": 0, "sprint_best": None,
                                     **{k: 0 for k, _l, _f in BUCKETS}})
        s["team"] = tmap.get(r["team_id"]) or s["team"]
        status = r["result_status"]
        if status == "DNS":
            s["dns"] += 1
        elif status != C.STATUS_NOT_RUN:
            s["starts"] += 1
        if status in C.CLASSIFIED_STATUSES and r["race_position"]:
            # v2.5: a classified retirement keeps its classified position (and any points) but isn't a finish
            s["finished" if status == C.STATUS_FINISHED else "classified"] += 1
            s["race"].append(r["race_position"])
            for key, _label, test in BUCKETS:
                if test(r["race_position"]):
                    s[key] += 1
            if r["qualifying_position"]:
                s["gained"].append(r["qualifying_position"] - r["race_position"])
        elif status == "DNF":
            s["dnf"] += 1
        elif status == "DSQ":
            s["dsq"] += 1
        if r["qualifying_position"]:
            s["quali"].append(r["qualifying_position"])
        if r["is_sprint"] and r["sprint_status"] != C.STATUS_NOT_RUN:
            s["sprints"] += 1
            s["sprint_points"] += pts.sprint(r)
            if r["sprint_status"] in C.CLASSIFIED_STATUSES and r["sprint_position"]:
                s["sprint_best"] = min(s["sprint_best"] or 99, r["sprint_position"])
    for s in out.values():
        avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
        s["avg_quali"], s["avg_race"] = avg(s["quali"]), avg(s["race"])
        s["avg_gained"] = avg(s["gained"])
        s["finish_rate"] = round(100 * s["finished"] / s["starts"]) if s["starts"] else None
        total = s["finished"] + s["classified"] + s["dnf"] + s["dns"] + s["dsq"]
        s["distribution"] = [(key, label, s[key], round(100 * s[key] / total) if total else 0) for key, label, _f in BUCKETS] + \
            [("retired", "DNF / DNS / DSQ", s["dnf"] + s["dns"] + s["dsq"],
              round(100 * (s["dnf"] + s["dns"] + s["dsq"]) / total) if total else 0)]
    return sorted(out.values(), key=lambda s: (s["avg_race"] is None, -(s["win"] * 100 + s["podium"] * 10 + s["points"]),
                                              s["avg_race"] or 99))


def sprint_table(rows):
    return sorted([s for s in rows if s["sprints"]], key=lambda s: (-s["sprint_points"], s["sprint_best"] or 99))


def teams_reliability(conn, season_id):
    tmap = S.team_map(conn)
    out = {}
    for r in _rows(conn, season_id):
        if r["result_status"] == C.STATUS_NOT_RUN:
            continue
        t = out.setdefault(r["team_id"], {"team": tmap.get(r["team_id"]), "entries": 0, "finished": 0, "dnf": 0})
        t["entries"] += 1
        t["finished"] += r["result_status"] == C.STATUS_FINISHED
        t["dnf"] += r["result_status"] == "DNF"
    for t in out.values():
        t["rate"] = round(100 * t["finished"] / t["entries"]) if t["entries"] else None
    return sorted(out.values(), key=lambda t: (-(t["rate"] or 0), t["team"]["name"] if t["team"] else ""))


def teammates(conn, season_id):
    """Teammate head-to-heads (qualifying and race) for pairs who raced together this season."""
    by_event = {}
    for r in _rows(conn, season_id):
        by_event.setdefault((r["event_id"], r["team_id"]), []).append(r)
    dmap, tmap = S.driver_map(conn), S.team_map(conn)
    pairs = {}
    pts = calc3.Points(conn)
    v3 = engine.is_v3(conn, season_id)
    for (_e, team_id), rs in by_event.items():
        if len(rs) != 2:
            continue
        a, b = sorted(rs, key=lambda r: r["driver_id"])
        p = pairs.setdefault((team_id, a["driver_id"], b["driver_id"]),
                             {"team": tmap.get(team_id), "a": dmap[a["driver_id"]], "b": dmap[b["driver_id"]],
                              "quali": [0, 0], "race": [0, 0], "points": [0, 0]})
        if a["qualifying_position"] and b["qualifying_position"]:
            p["quali"][0 if a["qualifying_position"] < b["qualifying_position"] else 1] += 1
        if v3:
            won = calc3.compare(a, b)      # v2.5: shared rules; a DNS is never a teammate loss
            if won is not None:
                p["race"][0 if won else 1] += 1
        else:
            ra = a["race_position"] if a["result_status"] == C.STATUS_FINISHED else None
            rb = b["race_position"] if b["result_status"] == C.STATUS_FINISHED else None
            if ra or rb:
                p["race"][0 if (ra and (not rb or ra < rb)) else 1] += 1
        for i, r in enumerate((a, b)):
            p["points"][i] += pts.total(r)
    return sorted(pairs.values(), key=lambda p: (not (p["a"]["is_player"] or p["b"]["is_player"]),
                                                 p["team"]["name"] if p["team"] else ""))


def season_over_season(conn, players_only=True):
    """Championship position and points per season for each (player) driver who raced in more than one season."""
    seasons = S.list_seasons(conn)
    table = {}
    for s in seasons:
        for row in S.driver_standings(conn, s["id"], completed_only=True):
            d = row["driver"]
            if players_only and not d["is_player"]:
                continue
            if not row.get("has_results", True):
                continue
            table.setdefault(d["id"], {"driver": d, "seasons": {}})["seasons"][s["year"]] = \
                {"position": row["position"], "points": row["points"]}
    rows = [r for r in table.values() if len(r["seasons"]) > 1 or len(seasons) == 1]
    return [s["year"] for s in seasons], sorted(rows, key=lambda r: r["driver"]["name"])
