"""Seats and contracts: the one place that says what a driver's seat means in a season.

Seats live on the season grid (season_grid). Contracts are signed deals (accepted offers: a team, a first year
and a number of years). Before v2.0 a new season copied the whole grid forward, so a driver whose one-year deal
had ended still showed as seated. Every page now asks state() instead, and a season rollover goes through a
review where each expiring driver gets an explicit decision:

    confirmed     seated, with a contract that covers this season at this team
    provisional   seated, deliberately kept while a new contract is sorted ("Awaiting contract")
    temporary     seated as a stand-in / replacement driver
    no_contract   seated, and this driver has never had a contract (leagues that don't use contracts)
    expired       PROBLEM: seated, but their last contract ended before this season
    wrong_team    PROBLEM: seated at one team while their contract for this season is with another
    unseated      PROBLEM: has a contract for this season but no seat
    free_agent    not seated and no contract for this season (history, stats and identity are all kept)
    ai            an AI driver (the league doesn't give AI drivers contracts)

A problem is never "fixed" by changing results or history: the repair tool only renews (records a new contract,
keeping the old one), marks the seat provisional or temporary, or releases the driver to free agency.
"""

from . import constants as C
from . import services as S
from .storage import now_iso

KINDS = {
    "confirmed": ("Contracted", "good"),
    "provisional": ("Provisional seat · awaiting contract", "warn"),
    "temporary": ("Temporary / replacement", "info"),
    "no_contract": ("Seated (no contract system)", "muted"),
    "expired": ("Contract expired", "bad"),
    "wrong_team": ("Contract is with another team", "bad"),
    "unseated": ("Contracted but not seated", "bad"),
    "free_agent": ("Free agent", "muted"),
    "ai": ("AI driver", "muted"),
}
PROBLEMS = {"expired", "wrong_team", "unseated"}
FLAGS = {"provisional", "temporary"}


def _year(conn, season_id):
    return S.get_season(conn, season_id)["year"]


def contracts(conn, driver_id):
    """Every signed deal for a driver, oldest first, with its years."""
    tmap = S.team_map(conn)
    rows = conn.execute("""SELECT o.*, w.target_year, w.kind AS window_kind FROM offers o
                           JOIN market_windows w ON w.id = o.window_id
                           WHERE o.driver_id = ? AND o.status = ? ORDER BY w.target_year, o.id""",
                        (driver_id, C.OFFER_ACCEPTED)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["team"] = tmap.get(r["team_id"])
        r["end_year"] = r["target_year"] + r["years"] - 1
        out.append(r)
    return out


def covering(deals, year):
    hits = [d for d in deals if d["target_year"] <= year <= d["end_year"]]
    return hits[-1] if hits else None


def flag(conn, season_id, driver_id):
    row = conn.execute("SELECT * FROM seat_flags WHERE season_id = ? AND driver_id = ?", (season_id, driver_id)).fetchone()
    return dict(row) if row else None


def set_flag(conn, season_id, driver_id, status, note="", username=""):
    if status not in FLAGS:
        raise S.ValidationError("Unknown seat status")
    conn.execute("""INSERT INTO seat_flags(season_id, driver_id, status, note, set_by, created_at) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(season_id, driver_id) DO UPDATE SET status = excluded.status, note = excluded.note,
                    set_by = excluded.set_by, created_at = excluded.created_at""",
                 (season_id, driver_id, status, note[:200], username, now_iso()))


def clear_flag(conn, season_id, driver_id):
    conn.execute("DELETE FROM seat_flags WHERE season_id = ? AND driver_id = ?", (season_id, driver_id))


def state(conn, season_id, driver_id, seats=None, driver=None):
    """The authoritative seat/contract state of one driver in one season."""
    driver = driver or S.driver_map(conn).get(driver_id)
    seats = seats if seats is not None else S.driver_seats(conn, season_id)
    seat = seats.get(driver_id)
    tmap = S.team_map(conn)
    year = _year(conn, season_id)
    out = {"driver": driver, "seat": seat, "team": tmap.get(seat[0]) if seat else None, "year": year,
           "contract": None, "last": None, "flag": None, "kind": None}
    if not driver or not driver["is_player"]:
        out["kind"] = "ai" if seat else "free_agent"
        return _label(out)
    deals = contracts(conn, driver_id)
    out["last"] = deals[-1] if deals else None
    deal = covering(deals, year)
    out["contract"] = deal
    fl = flag(conn, season_id, driver_id) if seat else None
    out["flag"] = fl
    if seat:
        if deal and deal["team_id"] == seat[0]:
            out["kind"] = "confirmed"
        elif fl:
            out["kind"] = fl["status"]
        elif deal:
            out["kind"] = "wrong_team"
        elif deals:
            out["kind"] = "expired"
        else:
            out["kind"] = "no_contract"
    else:
        out["kind"] = "unseated" if deal and driver["active"] else "free_agent"
    return _label(out)


def _label(out):
    label, tone = KINDS[out["kind"]]
    out["label"], out["tone"], out["problem"] = label, tone, out["kind"] in PROBLEMS
    c = out.get("contract")
    if out["kind"] == "confirmed" and c:
        out["detail"] = f"{c['team']['name']} {c['target_year']}" + (f"–{c['end_year']}" if c["end_year"] != c["target_year"] else "")
    elif out["kind"] == "expired" and out.get("last"):
        l = out["last"]
        out["detail"] = f"Last contract: {l['team']['name'] if l['team'] else '?'} to {l['end_year']}"
    elif out["kind"] == "wrong_team" and c:
        out["detail"] = f"Contract for {out['year']} is with {c['team']['name']}"
    elif out["kind"] == "unseated" and c:
        out["detail"] = f"Signed with {c['team']['name']} for {out['year']}"
    elif out["kind"] in FLAGS and out.get("flag") and out["flag"].get("note"):
        out["detail"] = out["flag"]["note"]
    else:
        out["detail"] = ""
    return out


def season_states(conn, season_id):
    """state() for every player driver (seated or not) in a season."""
    seats = S.driver_seats(conn, season_id)
    return [state(conn, season_id, d["id"], seats, d) for d in S.player_drivers(conn)]


def problems(conn, season_id):
    return [s for s in season_states(conn, season_id) if s["problem"]]


# --------------------------------------------------------------------------- contracts recorded by the Race Master

def record_contract(conn, driver_id, team_id, year, years=1, role="Equal Status", growth=1, note=""):
    """A contract agreed outside the market (renewal, or a correction). It's stored like any signing, so every
    page reads it the same way; the old contract stays in history."""
    try:
        years = int(years)
        year = int(year)
    except (TypeError, ValueError):
        raise S.ValidationError("Choose how many years")
    if not 1 <= years <= 5:
        raise S.ValidationError("Contracts run for 1 to 5 years")
    if role not in ("No. 1", "No. 2", "Equal Status"):
        raise S.ValidationError("Choose a seat status")
    team = S.team_map(conn).get(team_id)
    driver = S.driver_map(conn).get(driver_id)
    if not team or not driver:
        raise S.ValidationError("Unknown driver or team")
    season = conn.execute("SELECT id FROM seasons WHERE year <= ? ORDER BY year DESC LIMIT 1", (year,)).fetchone() or \
        conn.execute("SELECT id FROM seasons ORDER BY year LIMIT 1").fetchone()
    window_id = conn.execute("INSERT INTO market_windows(season_id, target_year, kind, status, opened_at, closed_at) "
                             "VALUES(?,?,?,?,?,?)", (season["id"], year, "Contract (recorded)", C.WINDOW_CLOSED,
                                                     now_iso(), now_iso())).lastrowid
    offer_id = conn.execute("""INSERT INTO offers(window_id, driver_id, team_id, role, years, growth, interest, reason,
                               status, applied, created_at, responded_at, origin, stage)
                               VALUES(?,?,?,?,?,?,0,?,?,1,?,?,'manual','Signed')""",
                            (window_id, driver_id, team_id, role, years, growth, note or "Recorded by the Race Master",
                             C.OFFER_ACCEPTED, now_iso(), now_iso())).lastrowid
    return offer_id


# --------------------------------------------------------------------------- season rollover review

ACTIONS = {"renew": "Renew with the same team", "provisional": "Keep the seat provisionally (awaiting contract)",
           "release": "Release to free agency (an AI driver takes the seat)"}


def rollover_review(conn, source_id, year):
    """What starting `year` from season source_id would do to every player driver, before anything changes."""
    seats = S.driver_seats(conn, source_id)
    tmap = S.team_map(conn)
    rows = []
    for d in S.player_drivers(conn):
        deals = contracts(conn, d["id"])
        seat = seats.get(d["id"])
        now = covering(deals, year)
        released = bool(conn.execute("SELECT 1 FROM team_relations WHERE season_id = ? AND driver_id = ? AND released = 1",
                                     (source_id, d["id"])).fetchone())
        row = {"driver": d, "seat": seat, "team": tmap.get(seat[0]) if seat else None, "next": now,
               "released": released, "last": deals[-1] if deals else None, "needs_decision": False}
        if not d["active"]:
            row["outcome"], row["kind"] = "Inactive: stays off the grid", "inactive"
        elif now and seat and now["team_id"] == seat[0] and not released:
            multi = now["target_year"] < year
            row["outcome"] = (f"Continues with {now['team']['name']} (multi-year to {now['end_year']})" if multi
                              else f"Renewed with {now['team']['name']} to {now['end_year']}")
            row["kind"] = "continuing" if multi else "renewed"
        elif now:
            row["outcome"], row["kind"] = f"Moves to {now['team']['name']} (signed to {now['end_year']})", "moving"
        elif seat and deals:
            row["outcome"], row["kind"] = f"Contract with {row['team']['name']} ends", "expiring"
            row["needs_decision"] = True
        elif seat:
            row["outcome"], row["kind"] = "Keeps the seat (this league doesn't use contracts for them)", "no_contract"
        else:
            row["outcome"], row["kind"] = "No seat: stays a free agent", "free_agent"
        if released and not now:
            row["outcome"], row["kind"], row["needs_decision"] = "Released by the team: becomes a free agent", "released", False
        rows.append(row)
    # Two signed drivers can't both take the same team's two seats plus a third.
    by_team = {}
    for r in rows:
        if r["kind"] in ("continuing", "renewed", "moving"):
            by_team.setdefault(r["next"]["team_id"], []).append(r)
    conflicts = [{"team": tmap[t], "drivers": [r["driver"] for r in rs]} for t, rs in by_team.items() if len(rs) > 2]
    return {"rows": rows, "conflicts": conflicts, "year": year,
            "counts": {k: sum(1 for r in rows if r["kind"] == k) for k in
                       ("continuing", "renewed", "moving", "expiring", "released", "free_agent", "no_contract")}}


def apply_rollover_decisions(conn, source_id, new_id, decisions, username=""):
    """After the new season exists: carry out each expiring driver's decision. decisions: {driver_id: action}."""
    year = _year(conn, new_id)
    seats = S.driver_seats(conn, new_id)
    old_seats = S.driver_seats(conn, source_id)
    done = []
    for did, action in decisions.items():
        seat = seats.get(did)
        old = old_seats.get(did)
        if action == "renew" and old:
            record_contract(conn, did, old[0], year, 1, note="Renewed at the season rollover")
            if not seat or seat[0] != old[0]:
                S.place_players(conn, new_id, {did: old})
            clear_flag(conn, new_id, did)
        elif action == "provisional" and seat:
            set_flag(conn, new_id, did, "provisional", "Carried over while a new contract is agreed", username)
        elif action == "release" and seat:
            S.place_players(conn, new_id, {did: None})
            clear_flag(conn, new_id, did)
        done.append((did, action))
    return done


def carry_mode(conn):
    from .storage import get_meta
    mode = get_meta(conn, "rollover_default", "provisional")
    return mode if mode in ACTIONS else "provisional"
