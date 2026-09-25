"""Weather for each race weekend (v3.1).

A Scorekeeper or the Race Master records the conditions of each session as they were in the game: qualifying, the
Sprint (Sprint weekends) and the race. They show on the round page, the calendar, the results list, the race summary
and in Statistics (each driver's record in the wet and in the dry).

Weather is a record only: it never changes points, Form, Reputation, relationships or the AI recommendation. (The AI
tracker has its own "Wet or changing conditions" flag per player under Pace & conditions; the round page reminds the
Race Master of it when a session was wet.)
"""

from . import constants as C
from .storage import now_iso

# key: (label, icon, wet?)
CONDITIONS = {
    "dry": ("Dry", "☀️", False),
    "overcast": ("Overcast", "☁️", False),
    "light_rain": ("Light rain", "🌦️", True),
    "heavy_rain": ("Heavy rain", "🌧️", True),
    "changing": ("Changing (dry and wet)", "🌈", True),
}
SESSIONS = {"quali": "Qualifying", "sprint": "Sprint", "race": "Race"}


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS weather (
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        session TEXT NOT NULL, condition TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY (event_id, session))""")


def sessions_for(event):
    return [k for k in SESSIONS if k != "sprint" or event.get("is_sprint")]


def get(conn, event_id):
    """{session: condition key} recorded for one round."""
    _table(conn)
    return {r["session"]: r["condition"] for r in conn.execute(
        "SELECT session, condition FROM weather WHERE event_id = ?", (event_id,))}


def for_season(conn, season_id):
    """{event_id: {session: condition key}} for every round of a season that has weather recorded."""
    _table(conn)
    out = {}
    for r in conn.execute("""SELECT w.event_id, w.session, w.condition FROM weather w JOIN events e ON e.id = w.event_id
                             WHERE e.season_id = ?""", (season_id,)):
        out.setdefault(r["event_id"], {})[r["session"]] = r["condition"]
    return out


def describe(recorded, event=None):
    """[{session, label, condition, icon, text, wet}] in session order, for display."""
    out = []
    for s in SESSIONS:
        key = recorded.get(s)
        if not key or key not in CONDITIONS or (s == "sprint" and event is not None and not event.get("is_sprint")):
            continue
        label, icon, wet = CONDITIONS[key]
        out.append({"session": s, "session_label": SESSIONS[s], "condition": key, "icon": icon, "text": label, "wet": wet})
    return out


def headline(recorded):
    """The race's weather (or qualifying's if the race has none) as (icon, label), for compact lists."""
    key = recorded.get("race") or recorded.get("quali")
    if key not in CONDITIONS:
        return None
    return CONDITIONS[key][1], CONDITIONS[key][0]


def is_wet(key):
    return bool(key in CONDITIONS and CONDITIONS[key][2])


def save(conn, event, form, username):
    """Record the conditions from a form (weather_quali / weather_sprint / weather_race; blank clears one)."""
    from . import services as S
    _table(conn)
    changed = []
    for s in sessions_for(event):
        value = (form.get(f"weather_{s}") or "").strip()
        if value and value not in CONDITIONS:
            raise S.ValidationError("Choose the conditions from the list")
        if value:
            conn.execute("""INSERT INTO weather(event_id, session, condition, updated_by, updated_at) VALUES(?,?,?,?,?)
                            ON CONFLICT(event_id, session) DO UPDATE SET condition = excluded.condition,
                            updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
                         (event["id"], s, value, username, now_iso()))
            changed.append(f"{SESSIONS[s].lower()} {CONDITIONS[value][0].lower()}")
        else:
            conn.execute("DELETE FROM weather WHERE event_id = ? AND session = ?", (event["id"], s))
    return changed


def clear(conn, event_id):
    """Used when a weekend is reset to Upcoming."""
    _table(conn)
    conn.execute("DELETE FROM weather WHERE event_id = ?", (event_id,))


def driver_splits(conn, season_id, player_only=False):
    """Each driver's Grand Prix record in wet or changing races against dry ones (rounds with the race's weather
    recorded only): races, average finish, wins, podiums and DNFs. Rows sorted by wet races, then average."""
    from . import services as S
    recorded = for_season(conn, season_id)
    race_wx = {eid: w["race"] for eid, w in recorded.items() if w.get("race")}
    if not race_wx:
        return []
    rows = conn.execute("""SELECT r.driver_id, r.race_position, r.result_status, r.event_id FROM results r
                           JOIN events e ON e.id = r.event_id WHERE e.season_id = ? AND e.status = ?""",
                        (season_id, C.EVENT_COMPLETE)).fetchall()
    dmap, stats = S.driver_map(conn), {}
    for r in rows:
        key = race_wx.get(r["event_id"])
        if not key or r["result_status"] == C.STATUS_NOT_RUN:
            continue
        d = dmap.get(r["driver_id"])
        if not d or (player_only and not d["is_player"]):
            continue
        side = "wet" if is_wet(key) else "dry"
        s = stats.setdefault(r["driver_id"], {"driver": d, "wet": _blank(), "dry": _blank()})[side]
        s["races"] += 1
        finished = r["result_status"] in C.CLASSIFIED_STATUSES and r["race_position"]
        if finished:
            s["_finishes"].append(r["race_position"])
            s["wins"] += r["race_position"] == 1
            s["podiums"] += r["race_position"] <= 3
        else:
            s["dnfs"] += 1
    out = []
    for did, s in stats.items():
        for side in ("wet", "dry"):
            f = s[side].pop("_finishes")
            s[side]["avg"] = round(sum(f) / len(f), 1) if f else None
        s["driver_id"] = did
        if s["wet"]["races"]:
            s["gain"] = (round(s["dry"]["avg"] - s["wet"]["avg"], 1)
                         if s["wet"]["avg"] is not None and s["dry"]["avg"] is not None else None)
            out.append(s)
    out.sort(key=lambda s: (-s["wet"]["races"], s["wet"]["avg"] if s["wet"]["avg"] is not None else 99))
    return out


def _blank():
    return {"races": 0, "wins": 0, "podiums": 0, "dnfs": 0, "_finishes": []}
