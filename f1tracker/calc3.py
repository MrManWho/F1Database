"""Calculation Version 3 (Paddock Legacy 2.5): standings, countback, car strength, Form, car-adjusted performance,
head-to-head, Reputation, Driver Value and current-team interest.

Every formula is written out in docs/CALCULATION_V3.md. Engine 2 (services.py and friends) is left exactly as it
was, so seasons played under it stay reproducible; engine.py decides which one applies.
"""


from . import constants as C
from . import engine as E


def clamp(value, low, high):
    return max(low, min(high, value))


# --------------------------------------------------------------------------- results and statuses

def classified(r):
    """A classified finish with a position: Finished or Classified retirement."""
    return r["result_status"] in C.CLASSIFIED_STATUSES and bool(r["race_position"])


def started(r):
    return r["result_status"] in C.START_STATUSES


class Points:
    """Grand Prix and Sprint points for result rows, knowing each round's distance rules (looked up once)."""

    def __init__(self, conn):
        self.conn = conn
        self._events = {}
        row = conn.execute("SELECT value FROM meta WHERE key = 'sprint_min_distance'").fetchone()
        try:
            self.sprint_min = int(row[0]) if row else C.SPRINT_MIN_DISTANCE
        except (TypeError, ValueError):
            self.sprint_min = C.SPRINT_MIN_DISTANCE

    def event(self, event_id):
        if event_id not in self._events:
            e = self.conn.execute("SELECT is_sprint, gp_distance, sprint_distance FROM events WHERE id = ?",
                                  (event_id,)).fetchone()
            self._events[event_id] = dict(e) if e else {"is_sprint": 0, "gp_distance": "full", "sprint_distance": 100}
        return self._events[event_id]

    def gp(self, r):
        e = self.event(r["event_id"])
        return gp_points(r["race_position"], r["result_status"], e.get("gp_distance") or "full",
                         _get(r, "points_override"))

    def sprint(self, r):
        e = self.event(r["event_id"])
        if not e.get("is_sprint"):
            return 0
        if (e.get("sprint_distance") or 100) < self.sprint_min:
            return 0
        override = _get(r, "sprint_points_override")
        if override is not None and r["sprint_status"] in C.CLASSIFIED_STATUSES:
            return override
        if r["sprint_status"] not in C.CLASSIFIED_STATUSES or not r["sprint_position"]:
            return 0
        return C.SPRINT_POINTS.get(r["sprint_position"], 0)

    def total(self, r):
        return self.gp(r) + self.sprint(r)


def _get(r, key):
    try:
        return r[key]
    except (KeyError, IndexError):
        return None


def gp_points(position, status, distance="full", override=None):
    """Grand Prix points: only a classified finish scores (Finished or Classified retirement). A shortened race uses
    the reduced scale for its distance; "manual" uses the points typed in for that driver."""
    if status not in C.CLASSIFIED_STATUSES:
        return 0
    if distance == "manual":
        return override or 0
    table = C.GP_DISTANCES.get(distance, C.GP_DISTANCES["full"])[1] or {}
    return table.get(position, 0) if position else 0


# --------------------------------------------------------------------------- season rows

def season_rows(conn, season_id, upto_round=None, completed_only=True):
    """Every result row of the season (with round number, Sprint flag and the round's field size), oldest first."""
    sql = """SELECT r.*, e.round_number, e.is_sprint, e.status AS event_status, e.postponed, e.cancelled,
                    d.is_player FROM results r JOIN events e ON e.id = r.event_id JOIN drivers d ON d.id = r.driver_id
             WHERE e.season_id = ? AND e.round_number <= ?"""
    if completed_only:
        sql += " AND e.status = 'Complete'"
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY e.round_number",
                                          (season_id, upto_round if upto_round is not None else 10 ** 6))]
    fields = {}
    for r in rows:
        fields[r["event_id"]] = fields.get(r["event_id"], 0) + 1
    for r in rows:
        r["field"] = max(2, fields[r["event_id"]])
        r["season_id_"] = season_id
    return rows


def _has_data(r):
    return any((r["qualifying_position"], r["race_position"], r["sprint_position"], r["fastest_lap"],
                r["driver_of_day"])) or r["result_status"] != C.STATUS_NOT_RUN or r["sprint_status"] != C.STATUS_NOT_RUN


# --------------------------------------------------------------------------- car strength

def _teams(conn):
    return [dict(t) for t in conn.execute("SELECT * FROM teams WHERE active = 1 ORDER BY id")]


def rating_ranks(conn, season_id):
    from . import services as S
    default = [t["id"] for t in _teams(conn)]
    ratings = S.car_ratings(conn, season_id)
    order = sorted(default, key=lambda t: (-ratings.get(t, {"rating": 0})["rating"], default.index(t)))
    return {tid: pos for pos, tid in enumerate(order, start=1)}


def _ai_evidence(conn, season_id, before_round):
    """{team_id: [finishing percentile per AI Grand Prix entry]} from completed rounds before `before_round`.
    Classified: position / field; DNF or DSQ: 1.0 (last place); DNS and Not Run don't count. Sprints never count."""
    rows = conn.execute("""SELECT r.team_id, r.race_position, r.result_status, r.event_id FROM results r
                           JOIN events e ON e.id = r.event_id JOIN drivers d ON d.id = r.driver_id
                           WHERE e.season_id = ? AND e.status = ? AND d.is_player = 0 AND e.round_number < ?""",
                        (season_id, C.EVENT_COMPLETE, before_round)).fetchall()
    fields = {}
    for r in conn.execute("""SELECT r.event_id, COUNT(*) FROM results r JOIN events e ON e.id = r.event_id
                             WHERE e.season_id = ? GROUP BY r.event_id""", (season_id,)):
        fields[r[0]] = max(2, r[1])
    out = {}
    for r in rows:
        if r["result_status"] not in C.START_STATUSES:
            continue
        field = fields.get(r["event_id"], C.GRID_SIZE)
        pct = (r["race_position"] / field) if classified(r) else 1.0
        out.setdefault(r["team_id"], []).append(min(1.0, pct))
    return out


def rank_scores(conn, season_id, before_round=None):
    """{team_id: effective rank score} = (6 x rating rank + m x observed AI rank) / (6 + m), m = min(12, AI entries).
    A team with no AI driver (e.g. two players) has m = 0 and keeps its rating rank."""
    rr = rating_ranks(conn, season_id)
    evidence = _ai_evidence(conn, season_id, before_round if before_round is not None else 10 ** 6)
    avg = {t: sum(v) / len(v) for t, v in evidence.items() if v and t in rr}
    by_rating = sorted(rr, key=rr.get)
    observed_order = sorted(avg, key=lambda t: (avg[t], rr[t]))
    # Teams without evidence keep their rating position; the rest fill the other places in observed order.
    order = list(observed_order)
    for t in [t for t in by_rating if t not in avg]:
        order.insert(min(rr[t] - 1, len(order)), t)
    observed = {t: pos for pos, t in enumerate(order, start=1)}
    scores = {}
    for t in rr:
        m = min(C.V3_RANK_EVIDENCE_CAP, len(evidence.get(t, [])))
        scores[t] = (C.V3_RANK_PRIOR * rr[t] + m * observed[t]) / (C.V3_RANK_PRIOR + m)
    return scores, rr


def effective_ranks(conn, season_id, before_round=None):
    """Car-strength rank per team (1 = fastest), engine 3. In a Future-only season the frozen ranks at the cutoff
    blend into these as rounds are completed."""
    scores, rr = rank_scores(conn, season_id, before_round)
    if E.mixed(conn, season_id):
        frozen = {int(k): v for k, v in (E.frozen(conn, season_id).get("ranks") or {}).items()}
        cut = E.cutoff(conn, season_id)
        done_after = conn.execute("SELECT COUNT(*) FROM events WHERE season_id = ? AND status = ? AND round_number > ? "
                                  "AND round_number < ?", (season_id, C.EVENT_COMPLETE, cut,
                                                           before_round if before_round is not None else 10 ** 6)).fetchone()[0]
        w = min(1.0, done_after / C.ENGINE_BLEND_ROUNDS)
        scores = {t: E.blend(frozen.get(t), s, w) for t, s in scores.items()}
    order = sorted(scores, key=lambda t: (scores[t], rr[t]))
    return {t: pos for pos, t in enumerate(order, start=1)}


def store_round_ranks(conn, event):
    """Remember the car ranks this round is judged with (evidence from the rounds before it only)."""
    ranks = effective_ranks(conn, event["season_id"], event["round_number"])
    conn.execute("DELETE FROM round_ranks WHERE event_id = ?", (event["id"],))
    for t, r in ranks.items():
        conn.execute("INSERT INTO round_ranks(event_id, team_id, rank, source) VALUES(?,?,?,'v3')", (event["id"], t, r))
    return ranks


def round_ranks(conn, event):
    """The ranks this round was (or will be) judged with: stored when it was completed, else worked out now."""
    stored = {r["team_id"]: r["rank"] for r in conn.execute("SELECT team_id, rank FROM round_ranks WHERE event_id = ?",
                                                           (event["id"],))}
    if stored:
        return stored
    return effective_ranks(conn, event["season_id"], event["round_number"])


def expected_finish(rank, field=None, teams=None):
    """E = 2r - 0.5, scaled to the round's field when it isn't two cars per team."""
    base = 2 * rank - 0.5
    if field and teams and field != 2 * teams:
        return base * field / (2 * teams)
    return base


def racecraft(quali, finish, field):
    g = quali - finish
    if g > 0:
        return g * (field + 1 - finish) / field
    return g * 0.4


# --------------------------------------------------------------------------- per-driver metrics

def _window(rows):
    """The six most recent started rounds, newest first, with their weights 0.82^age."""
    done = [r for r in rows if started(r)]
    done.sort(key=lambda r: -r["round_number"])
    return [(r, C.V3_FORM_DECAY ** age) for age, r in enumerate(done[:C.V3_FORM_WINDOW])]


def race_perf_position(r):
    if classified(r):
        return r["race_position"]
    if r["result_status"] == "DNF" and r.get("no_fault"):
        return r["field"]
    return r["field"] + 1       # unexcused DNF or DSQ


def form(rows):
    """Form (1-100) from the six most recent started rounds, recent weighted most. 50 with nothing usable."""
    window = _window(rows)
    if not window:
        return 50.0
    wsum = sum(w for _r, w in window)
    f_part = sum(w * ((r["field"] + 2) / 2 - race_perf_position(r)) for r, w in window) / wsum
    q_rows = [(r, w) for r, w in window if r["qualifying_position"]]
    q_part = (sum(w * ((r["field"] + 2) / 2 - r["qualifying_position"]) for r, w in q_rows)
              / sum(w for _r, w in q_rows)) if q_rows else 0.0

    def rate(test):
        return sum(w for r, w in window if test(r)) / wsum
    rc_rows = [(racecraft(r["qualifying_position"], r["race_position"], r["field"]), w) for r, w in window
               if classified(r) and r["qualifying_position"]]
    rc = clamp(0.6 * sum(v * w for v, w in rc_rows) / sum(w for _v, w in rc_rows), -6, 12) if rc_rows else 0.0
    value = (50 + 2.0 * f_part + 1.0 * q_part
             + 8.0 * rate(lambda r: classified(r) and r["race_position"] == 1)
             + 4.0 * rate(lambda r: classified(r) and r["race_position"] <= 3)
             + 2.0 * rate(lambda r: r["qualifying_position"] == 1)
             + 1.0 * rate(lambda r: bool(r["fastest_lap"]))
             + 1.0 * rate(lambda r: bool(r["driver_of_day"]))
             - 5.0 * rate(lambda r: r["result_status"] == "DSQ")
             + rc)
    return E.round_half_up(clamp(value, 1, 100), 1)


def car_adjusted(conn, rows, n_teams):
    """50 + 4 x (recency-weighted average of expected finish - classified finish), 1-100. 50 with no finishes."""
    window = [(r, w) for r, w in _window(rows) if classified(r)]
    if not window:
        return 50.0
    ranks_cache = {}
    total = wsum = 0.0
    for r, w in window:
        if r["event_id"] not in ranks_cache:
            ranks_cache[r["event_id"]] = round_ranks(conn, {"id": r["event_id"], "season_id": r["season_id_"],
                                                            "round_number": r["round_number"]})
        rank = ranks_cache[r["event_id"]].get(r["team_id"], n_teams)
        total += w * (expected_finish(rank, r["field"], n_teams) - r["race_position"])
        wsum += w
    return E.round_half_up(clamp(50 + 4 * total / wsum, 1, 100), 1)


def compare(mine, theirs):
    """One head-to-head: True (won), False (lost) or None (no comparison). Both must have started; a classified
    finisher beats a non-finisher; two non-finishers, DNS and equal positions don't count."""
    if not mine or not theirs or not started(mine) or not started(theirs):
        return None
    a, b = classified(mine), classified(theirs)
    if a and b:
        if mine["race_position"] == theirs["race_position"]:
            return None
        return mine["race_position"] < theirs["race_position"]
    if a != b:
        return a
    return None


def head_to_head(conn, season_id, driver_id, upto_round=None, rows=None):
    """Race and qualifying head-to-heads against whoever shared the car at each round (engine 3 rules)."""
    rows = rows if rows is not None else season_rows(conn, season_id, upto_round, completed_only=False)
    by_event = {}
    for r in rows:
        by_event.setdefault((r["event_id"], r["team_id"]), []).append(r)
    h = {"race_won": 0, "race_total": 0, "quali_won": 0, "quali_total": 0}
    for r in rows:
        if r["driver_id"] != driver_id:
            continue
        for m in by_event.get((r["event_id"], r["team_id"]), []):
            if m["driver_id"] == driver_id:
                continue
            result = compare(r, m)
            if result is not None:
                h["race_total"] += 1
                h["race_won"] += int(result)
            if r["qualifying_position"] and m["qualifying_position"] and started(r) and started(m):
                h["quali_total"] += 1
                h["quali_won"] += int(r["qualifying_position"] < m["qualifying_position"])
    return h


def h2h_rating(h):
    if h["race_total"] < C.V3_H2H_MIN:
        return 50.0
    return clamp(50 + (h["race_won"] / h["race_total"] - 0.5) * 20, 40, 60)


def h2h_bonus(h):
    if h["race_total"] < C.V3_H2H_MIN:
        return 0.0
    return clamp((h["race_won"] / h["race_total"] - 0.5) * 8, -4, 4)


def reputation(start, form_value, car_value, h, starts, season_rounds):
    if not starts:
        return E.round_half_up(clamp(start, 1, 100), 1)
    performance = 0.55 * form_value + 0.35 * car_value + 0.10 * h2h_rating(h)
    confidence = min(1.0, starts / max(5.0, 0.35 * season_rounds))
    value = start + confidence * C.V3_REP_RATE * (performance - start)
    return E.round_half_up(clamp(value, 1, 100), 1)


# --------------------------------------------------------------------------- standings

def _countback_vector(rows, size):
    """Counts of classified P1, P2, ... then qualifying P1, P2, ... (negated so a plain sort puts more first)."""
    finishes = [0] * size
    quali = [0] * size
    for r in rows:
        if classified(r) and r["race_position"] <= size:
            finishes[r["race_position"] - 1] += 1
        if r["qualifying_position"] and r["qualifying_position"] <= size and started(r):
            quali[r["qualifying_position"] - 1] += 1
    return tuple(-x for x in finishes + quali)


def countback_used(conn, season_id):
    """Full-position countback decides ties on engine 3; in a Future-only season it starts once a new round is in."""
    if not E.is_v3(conn, season_id):
        return False
    return not E.mixed(conn, season_id) or E.rounds_after_cutoff(conn, season_id) > 0


def driver_standings(conn, season_id, upto_round=None, completed_only=False):
    """Same shape as services.driver_standings (engine 2), worked out with engine 3."""
    from . import services as S
    rows = season_rows(conn, season_id, upto_round, completed_only=completed_only)
    tmap, dmap = S.team_map(conn), S.driver_map(conn)
    seats = S.driver_seats(conn, season_id)
    n_teams = len(_teams(conn)) or 11
    season_rounds = conn.execute("SELECT COUNT(*) FROM events WHERE season_id = ?", (season_id,)).fetchone()[0] or 1
    states = {r["driver_id"]: r for r in conn.execute("SELECT * FROM season_driver_state WHERE season_id = ?",
                                                        (season_id,))}
    pts = Points(conn)
    by_driver = {}
    for r in rows:
        if _has_data(r):
            by_driver.setdefault(r["driver_id"], []).append(r)
    size = max([C.MAX_POSITION] + [r["field"] for r in rows])
    frozen = E.frozen(conn, season_id).get("drivers", {}) if E.mixed(conn, season_id) else {}
    w = E.blend_weight(conn, season_id)
    out = []
    for did in set(seats) | set(by_driver):
        driver = dmap.get(did)
        if not driver:
            continue
        mine = by_driver.get(did, [])
        s = _stats(mine, pts)
        state = states.get(did)
        start = state["starting_reputation"] if state else driver["baseline_reputation"]
        f = form(mine) if s["has_results"] else 50.0
        car = car_adjusted(conn, mine, n_teams)
        h = head_to_head(conn, season_id, did, rows=rows)
        if state and state["locked_reputation"] is not None:
            rep = state["locked_reputation"]
        else:
            rep = reputation(start, f, car, h, s["starts"], season_rounds) if s["has_results"] else \
                E.round_half_up(clamp(start, 1, 100), 1)
        fz = frozen.get(str(did))
        if fz:
            f = E.round_half_up(E.blend(fz.get("form"), f, w), 1)
            if not (state and state["locked_reputation"] is not None):
                rep = E.round_half_up(E.blend(fz.get("reputation"), rep, w), 1)
        team_id = seats[did][0] if did in seats else s["last_team_id"]
        score = E.round_half_up(0.8 * rep + 0.2 * f, 1)
        out.append({**s, "driver": driver, "driver_id": did, "team": tmap.get(team_id), "seated": did in seats,
                    "seat": seats.get(did), "form": f, "reputation": rep, "starting_reputation": start,
                    "market": S.market_tier(score), "car_adjusted": car, "h2h": h,
                    "_countback": _countback_vector(mine, size)})
    if countback_used(conn, season_id):
        out.sort(key=lambda r: (-r["points"], r["_countback"], r["driver"]["name"]))
    else:
        out.sort(key=lambda r: (-r["points"], -r["wins"], -r["podiums"], r["best_finish"] or 99, r["driver"]["name"]))
    for pos, row in enumerate(out, start=1):
        row["position"] = pos
    return out


def _stats(rows, pts):
    s = {"points": 0, "gp_points": 0, "sprint_points": 0, "wins": 0, "podiums": 0, "poles": 0, "fastest_laps": 0,
         "dotds": 0, "dnfs": 0, "dns": 0, "dsqs": 0, "classified_retirements": 0, "no_fault_dnfs": 0, "starts": 0,
         "best_finish": None, "finishes": [], "qualis": [], "has_results": bool(rows), "last_team_id": None,
         "last_round": 0, "gained": 0, "racecraft": 0.0, "racecraft_races": 0}
    for r in rows:
        s["last_team_id"], s["last_round"] = r["team_id"], r["round_number"]
        gp, sp = pts.gp(r), pts.sprint(r)
        s["gp_points"] += gp
        s["sprint_points"] += sp
        s["points"] += gp + sp
        c = classified(r)
        pos = r["race_position"]
        s["wins"] += int(c and pos == 1)
        s["podiums"] += int(c and pos <= 3)
        s["poles"] += int(r["qualifying_position"] == 1 and started(r))
        s["fastest_laps"] += int(bool(r["fastest_lap"]))
        s["dotds"] += int(bool(r["driver_of_day"]))
        st = r["result_status"]
        s["dnfs"] += int(st == "DNF")
        s["no_fault_dnfs"] += int(st == "DNF" and bool(r.get("no_fault")))
        s["dns"] += int(st == "DNS")
        s["dsqs"] += int(st == "DSQ")
        s["classified_retirements"] += int(st == C.STATUS_CLASSIFIED)
        s["starts"] += int(started(r))
        if c and (s["best_finish"] is None or pos < s["best_finish"]):
            s["best_finish"] = pos
        if c:
            s["finishes"].append(pos)
        if r["qualifying_position"]:
            s["qualis"].append(r["qualifying_position"])
        if c and r["qualifying_position"]:
            s["gained"] += r["qualifying_position"] - pos
            s["racecraft"] += racecraft(r["qualifying_position"], pos, r["field"])
            s["racecraft_races"] += 1
    s["avg_finish"] = E.round_half_up(sum(s["finishes"]) / len(s["finishes"]), 2) if s["finishes"] else None
    s["avg_quali"] = E.round_half_up(sum(s["qualis"]) / len(s["qualis"]), 2) if s["qualis"] else None
    return s


def constructor_standings(conn, season_id, upto_round=None, completed_only=False):
    from . import services as S
    tmap = S.team_map(conn)
    rows = season_rows(conn, season_id, upto_round, completed_only=completed_only)
    pts = Points(conn)
    size = max([C.MAX_POSITION] + [r["field"] for r in rows])
    totals = {tid: {"team": t, "points": 0, "wins": 0, "podiums": 0, "fastest_laps": 0, "dnfs": 0, "_rows": []}
              for tid, t in tmap.items() if t["active"]}
    for r in rows:
        t = totals.setdefault(r["team_id"], {"team": tmap[r["team_id"]], "points": 0, "wins": 0, "podiums": 0,
                                             "fastest_laps": 0, "dnfs": 0, "_rows": []})
        t["points"] += pts.total(r)
        c = classified(r)
        t["wins"] += int(c and r["race_position"] == 1)
        t["podiums"] += int(c and r["race_position"] <= 3)
        t["fastest_laps"] += int(bool(r["fastest_lap"]))
        t["dnfs"] += int(r["result_status"] == "DNF")
        t["_rows"].append(r)
    if countback_used(conn, season_id):
        out = sorted(totals.values(), key=lambda t: (-t["points"], _countback_vector(t["_rows"], size), t["team"]["name"]))
    else:
        out = sorted(totals.values(), key=lambda t: (-t["points"], -t["wins"], -t["podiums"], t["team"]["name"]))
    gmap = S.grid_map(conn, season_id)
    dmap = S.driver_map(conn)
    for pos, t in enumerate(out, start=1):
        t.pop("_rows", None)
        t["position"] = pos
        t["drivers"] = [dmap.get(gmap.get((t["team"]["id"], s))) for s in (1, 2)]
    return out


# --------------------------------------------------------------------------- value and interest

def driver_value(conn, season_id, driver_id, standings=None, ranks=None, upto_round=None):
    """0.5 x market score + 0.3 x Form + 0.2 x car-adjusted + head-to-head bonus (3+ comparisons, +/-4)."""
    from . import services as S
    standings = standings if standings is not None else \
        {r["driver_id"]: r for r in S.driver_standings(conn, season_id, upto_round)}
    row = standings.get(driver_id)
    if row:
        rep, f = row["reputation"], row["form"]
        car = row.get("car_adjusted", 50.0)
        h = row.get("h2h") or head_to_head(conn, season_id, driver_id, upto_round)
    else:
        rep, f, car = S.starting_reputation(conn, season_id, driver_id), 50.0, 50.0
        h = {"race_won": 0, "race_total": 0, "quali_won": 0, "quali_total": 0}
    market = E.round_half_up(0.8 * rep + 0.2 * f, 1)
    bonus = h2h_bonus(h)
    value = 0.5 * market + 0.3 * f + 0.2 * car + bonus
    fz = (E.frozen(conn, season_id).get("drivers", {}).get(str(driver_id)) or {}) if E.mixed(conn, season_id) else {}
    if fz.get("value") is not None:
        value = E.blend(fz["value"], value, E.blend_weight(conn, season_id))
    return {"value": E.round_half_up(value, 1), "market": market, "reputation": rep, "form": f, "car": car,
            "h2h": h, "h2h_bonus": E.round_half_up(bonus, 1), "stats": row}


def interest_bonus(score):
    """Current team: clamp((relationship - 60) / 5, -8, +6). A relationship of exactly 60 adds nothing."""
    return E.round_half_up(clamp((score - C.RELATION_START) / C.V3_INTEREST_DIVISOR, C.V3_INTEREST_MIN,
                                 C.V3_INTEREST_MAX), 1)
