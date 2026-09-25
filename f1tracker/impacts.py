"""Change notices (v2.1): whenever an update or an admin change alters a player driver's numbers, the person who
drives them is shown what changed, why and by how much, and has to agree before carrying on in that league.

How a change is caught:

* Explicit changes (e.g. removing team orders) run through `record_change`, which snapshots every player driver
  before and after and writes a notice for each driver whose numbers moved (or who the change touched).
* Formula changes between versions: after every change to a league the latest numbers are kept (`mark_stale` +
  `refresh`). When a newer version first opens the league, its numbers are compared with the ones the previous
  version kept, and any difference is a notice. If the kept numbers might be out of date (something was saved
  after they were taken), the comparison is skipped rather than blaming the update for ordinary results.

Nothing here changes a result, a rating or a formula; it only records and explains.
"""

import json

from . import constants as C
from . import services as S
from .storage import get_meta, now_iso, set_meta

STATS = {"points": ("Championship points", 0), "position": ("Championship position", 0),
         "reputation": ("Reputation", 1), "form": ("Form", 1), "value": ("Driver Value", 1),
         "relationship": ("Team relationship", 1), "warning": ("Warning level", 0),
         "ai": ("AI recommendation", 0), "sweet_spot": ("Your AI sweet spot", 1)}
# v2.5: changes that aren't numbers (shown as "before → now").
TEXT_STATS = {"band": "Relationship", "goals": "Season goals", "team_goal": "Team goal", "interest": "Your team's interest",
              "contract": "Contract and market status", "ultimatum": "Final warning"}

# Formula changes by version: shown as the "why" when numbers differ after an update.
CALC_NOTES = {
    1: ("Paddock Legacy 2.1", "Team orders are removed while they're switched off, and the AI difficulty "
                              "recommendation now adapts from every round."),
    2: ("Paddock Legacy 2.4", "Everything in this league was recalculated with the 2.4 formulas. A car with no AI "
                              "driver (for example two players in the same team) no longer counts as the slowest car "
                              "after three rounds, and the Reputation carried between seasons now includes the pledge "
                              "and team-goal rewards every time it's worked out."),
    3: ("Paddock Legacy 2.4.1", "The AI difficulty recommendation now judges each round half against your car and half "
                                "against the whole grid, and it never goes up while a player driver is struggling or "
                                "near the back. Results, points and ratings are unchanged."),
}


def _tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS impact_notices (
        id INTEGER PRIMARY KEY, driver_id INTEGER NOT NULL, season_id INTEGER, key TEXT NOT NULL,
        title TEXT NOT NULL, why TEXT NOT NULL, changes TEXT NOT NULL DEFAULT '[]', details TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS impact_acks (
        notice_id INTEGER NOT NULL, username TEXT NOT NULL, acked_at TEXT NOT NULL, PRIMARY KEY (notice_id, username))""")


def snapshot(conn, season_id=None, full=True):
    """{driver_id: {stat: value}} for every player driver, this season. full (v2.5): also the relationship band,
    warning level, goal states, team interest, contract status, final warning and the AI recommendation."""
    from . import market, relations
    sid = season_id or S.current_season_id(conn)
    if not sid:
        return {}
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, sid)}
    ranks = S.team_strength_ranks(conn, sid)
    has_rel = conn.execute("SELECT name FROM sqlite_master WHERE name = 'team_relations'").fetchone()
    extra = _extras(conn, sid, standings) if full else {}
    out = {}
    for p in S.player_drivers(conn):
        row = standings.get(p["id"])
        stats = {}
        if row:
            stats["points"] = row["points"]
            if row.get("has_results"):
                stats["position"] = row["position"]
            stats["reputation"] = round(row["reputation"], 1)
            stats["form"] = round(row["form"], 1)
            stats["value"] = round(market.driver_value(conn, sid, p["id"], standings, ranks)["value"], 1)
        if has_rel and conn.execute("SELECT 1 FROM team_relations WHERE season_id = ? AND driver_id = ?",
                                    (sid, p["id"])).fetchone():
            a = relations.assess(conn, sid, p["id"], standings)
            if a:
                stats["relationship"] = a["score"]
                if full:
                    stats["band"] = a["status"]
                    stats["warning"] = a["warning_level"]
                    stats["goals"] = "; ".join(f"{g['label']}: {g['state']}" for g in a["goals"]) or None
        stats.update(extra.get(p["id"], {}))
        out[str(p["id"])] = stats
    return out


def _extras(conn, sid, standings):
    """The league-wide and per-driver extras for a full snapshot (never fails the snapshot)."""
    from . import market, teamgoals, ultimatums
    out = {}
    try:
        rec = S.difficulty_recommendation(conn)
    except Exception:       # a partly set-up league: the AI numbers just aren't compared
        rec = {}
    spots = {p["driver_id"]: p.get("sweet_spot") for p in rec.get("players", []) if p.get("sweet_spot") is not None}
    goals = {}
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'team_goal_choices'").fetchone():
        goals = {g["team_id"]: f"{g['label']}: {g['state']}" for g in teamgoals.progress(conn, sid)}
    seats = S.driver_seats(conn, sid)
    for p in S.player_drivers(conn):
        d = {}
        seat = seats.get(p["id"])
        if rec.get("recommended") is not None and seat:     # the AI level only matters to someone racing
            d["ai"] = rec["recommended"]
        if p["id"] in spots:
            d["sweet_spot"] = spots[p["id"]]
        if seat and seat[0] in goals:
            d["team_goal"] = goals[seat[0]]
        try:
            if seat:
                me, teams = market.team_interest(conn, sid, p["id"])
                mine = next((t for t in teams if t["current"]), None)
                if mine:
                    d["interest"] = mine["label"]
            status = market.career_status(conn, sid, p["id"]) if hasattr(market, "career_status") else None
            deal = market.locked_in(conn, sid, p["id"], S.get_season(conn, sid)["year"] + 1)
            d["contract"] = status or (f"Contracted with {deal['team']['name']} through {deal['end_year']}" if deal
                                        else ("Seated" if seat else "No seat"))
            u = ultimatums.active(conn, sid, p["id"])
            d["ultimatum"] = u["status"] if u else "None"
        except Exception:
            pass
        out[p["id"]] = d
    return out


def diff(before, after):
    """{driver_id: [{stat, label, before, after, change}]} for numbers that moved."""
    out = {}
    for did, now in after.items():
        was = before.get(did, {})
        rows = []
        for key, (label, _dp) in STATS.items():
            a, b = was.get(key), now.get(key)
            if a is None or b is None or abs(float(b) - float(a)) < 0.05:
                continue
            rows.append({"stat": key, "label": label, "before": a, "after": b, "change": round(float(b) - float(a), 1)})
        for key, label in TEXT_STATS.items():
            a, b = was.get(key), now.get(key)
            if a is None or b is None or a == b:
                continue
            rows.append({"stat": key, "label": label, "before": a, "after": b, "change": None})
        if rows:
            out[int(did)] = rows
    return out


def add_notice(conn, driver_id, key, title, why, changes=(), details=(), season_id=None):
    _tables(conn)
    if conn.execute("SELECT 1 FROM impact_notices WHERE driver_id = ? AND key = ?", (driver_id, key)).fetchone():
        return None
    cur = conn.execute("""INSERT INTO impact_notices(driver_id, season_id, key, title, why, changes, details, created_at)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (driver_id, season_id or S.current_season_id(conn), key, title, why,
                        json.dumps(list(changes)), json.dumps(list(details)), now_iso()))
    return cur.lastrowid


def record_change(conn, key, title, why, fn):
    """Run fn(conn) and tell every player driver it changed. fn may return {driver_id: [detail lines]} for
    drivers it touched even if no number moved (e.g. a message removed). Returns the number of notices."""
    before = snapshot(conn)
    touched = fn(conn) or {}
    after = snapshot(conn)
    moved = diff(before, after)
    n = 0
    for did in sorted(set(moved) | set(touched)):
        if add_notice(conn, did, key, title, why, moved.get(did, []), touched.get(did, [])):
            n += 1
    return n


# --------------------------------------------------------------------------- keeping numbers for the next version

def mark_stale(conn):
    set_meta(conn, "calc_snapshot_stale", "1")


def refresh(conn):
    set_meta(conn, "calc_snapshot", json.dumps(snapshot(conn)))
    set_meta(conn, "calc_snapshot_stale", "0")


def on_open(conn, is_api=False):
    """Called whenever a league is opened. Runs the update checks once per version, and keeps the numbers fresh.
    v2.4: when a version changes how things are worked out, the league is recalculated first (recalc.recalculate),
    everyone is told once when they next open the league (announce), and each player driver whose numbers moved
    gets a change notice to agree to."""
    version = int(get_meta(conn, "calc_version") or 0)
    if version < C.CALC_VERSION:
        stored = get_meta(conn, "calc_snapshot")
        fresh = get_meta(conn, "calc_snapshot_stale") != "1"
        for v in range(version + 1, C.CALC_VERSION + 1):
            for step in MIGRATIONS.get(v, []):
                step(conn)
        notes = [CALC_NOTES[v] for v in range(version + 1, C.CALC_VERSION + 1) if v in CALC_NOTES]
        if version and notes:
            from . import recalc
            recalc.recalculate(conn)
            announce(conn, notes[-1][0], " ".join(why for _t, why in notes))
        if stored and fresh and notes:
            moved = diff(json.loads(stored), snapshot(conn))
            for did, rows in moved.items():
                add_notice(conn, did, f"calc-{C.CALC_VERSION}", "How some numbers are worked out has changed",
                           " ".join(why for _t, why in notes), rows)
        set_meta(conn, "calc_version", str(C.CALC_VERSION))
        refresh(conn)
    elif not is_api and get_meta(conn, "calc_snapshot_stale") != "0":
        refresh(conn)


def announce(conn, title, text):
    """A one-off message everyone sees the next time they open this league (until they close it)."""
    set_meta(conn, "calc_announce", json.dumps({"id": now_iso(), "title": title, "text": text}))


def announcement_for(conn, username):
    raw = get_meta(conn, "calc_announce")
    if not raw:
        return None
    note = json.loads(raw)
    if get_meta(conn, f"calc_seen_{username}") == note["id"]:
        return None
    return note


def dismiss_announcement(conn, username):
    raw = get_meta(conn, "calc_announce")
    if raw:
        set_meta(conn, f"calc_seen_{username}", json.loads(raw)["id"])


# --------------------------------------------------------------------------- reading and agreeing

def pending(conn, driver_id, username):
    _tables(conn)
    rows = conn.execute("""SELECT * FROM impact_notices n WHERE driver_id = ? AND NOT EXISTS (
                           SELECT 1 FROM impact_acks a WHERE a.notice_id = n.id AND a.username = ?) ORDER BY id""",
                        (driver_id, username)).fetchall()
    return [_row(r) for r in rows]


def history(conn, driver_id=None, limit=100):
    _tables(conn)
    sql = "SELECT * FROM impact_notices" + (" WHERE driver_id = ?" if driver_id else "") + " ORDER BY id DESC LIMIT ?"
    rows = conn.execute(sql, ((driver_id, limit) if driver_id else (limit,))).fetchall()
    out = []
    for r in rows:
        n = _row(r)
        n["acked"] = [dict(a) for a in conn.execute("SELECT * FROM impact_acks WHERE notice_id = ?", (r["id"],))]
        out.append(n)
    return out


def acknowledge(conn, driver_id, username, notice_ids):
    _tables(conn)
    mine = {r["id"] for r in pending(conn, driver_id, username)}
    done = 0
    for nid in notice_ids:
        if nid in mine:
            conn.execute("INSERT OR IGNORE INTO impact_acks(notice_id, username, acked_at) VALUES(?,?,?)",
                         (nid, username, now_iso()))
            done += 1
    return done


def _row(r):
    n = dict(r)
    n["changes"] = json.loads(n["changes"] or "[]")
    n["details"] = json.loads(n["details"] or "[]")
    return n


# --------------------------------------------------------------------------- version steps

def _void_orders_if_off(conn):
    from . import teamlife
    if teamlife.settings(conn)["orders"] == "off":
        record_change(conn, "orders-removed-v2.1", "Team orders removed",
                      "Team orders are switched off in this league, so every team order has been removed, including "
                      "old ones, and any effect they had on your team relationship has been undone.",
                      teamlife.void_all_orders)


MIGRATIONS = {1: [_void_orders_if_off]}
