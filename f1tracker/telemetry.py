"""Race results from the game's telemetry (F1 25 UDP), per league.

Off unless the Race Master turns on "Telemetry import" for the league. They then get a private upload link for
that league; a small recorder on someone's PC (or any tool that sends the same JSON) posts one session's results
to it when the game shows the final classification. Uploads wait here, untouched, until a Scorekeeper opens one in
a round's Import dialog, reviews the preview and applies it to the results table. Nothing here ever saves results,
submits a round or runs the post-race steps.

Upload format (JSON, one session):
    {"session": {"track": "Monza", "session_type": "Race", "session_type_id": 15, "ai_difficulty": 87, ...},
     "results": [{"position": 1, "name": "VERSTAPPEN", "team": "Red Bull Racing", "status": "Finished",
                  "best_lap_ms": 81234, "laps": 53, "grid": 2, "penalty_s": 0, "fastest_lap": true, ...}, ...],
     "events": [{"code": "PENA", "driver": "...", "other_driver": "...", "seconds": 5, "lap": 12}, ...],
     "session_uid": "1234..."}
"""

import hmac
import json
import secrets

from . import services as S
from .storage import get_meta, now_iso, set_meta

MAX_BYTES = 256 * 1024     # one session's summary is a few KB; anything far bigger isn't one
KEEP = 40                  # uploads not linked to a round kept per league (oldest are dropped); linked ones stay
MAX_CARS = 24              # 22 in the 2025 format, 24 in the 2026 Season Pack format
MAX_EVENTS = 300
STATUSES = {"Finished", "DNF", "DSQ", "Not Classified", "Retired", "Inactive", "Invalid", "Active"}

# Game session types: what part of a round weekend each one is ("sprint_or_race" is decided by the round).
KINDS = {**{i: "practice" for i in range(1, 5)}, **{i: "qualifying" for i in range(5, 10)},
         **{i: "shootout" for i in range(10, 15)}, 15: "sprint_or_race", 16: "race", 17: "race", 18: "time_trial"}

TABLE = """
CREATE TABLE IF NOT EXISTS telemetry_uploads (
    id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    session_uid TEXT NOT NULL DEFAULT '',
    session_type_id INTEGER,
    track TEXT NOT NULL DEFAULT '',
    session_type TEXT NOT NULL DEFAULT '',
    cars INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    used_event_id INTEGER,
    used_at TEXT
);
"""


def ensure_table(conn):
    conn.execute(TABLE)   # one statement: executescript would commit an open transaction
    cols = {r[1] for r in conn.execute("PRAGMA table_info(telemetry_uploads)")}
    if "raw" not in cols:     # 2026-10-08: the upload as it was sent, kept for features that need more of it later
        conn.execute("ALTER TABLE telemetry_uploads ADD COLUMN raw TEXT")
    if "recorder" not in cols:
        conn.execute("ALTER TABLE telemetry_uploads ADD COLUMN recorder TEXT NOT NULL DEFAULT ''")


def enabled(conn):
    return get_meta(conn, "feature_telemetry") == "1"


def upload_key(conn):
    """The league's upload key, or None when the Race Master hasn't made a link (or turned it off)."""
    return get_meta(conn, "telemetry_key") or None


def new_key(conn):
    key = secrets.token_urlsafe(18)
    set_meta(conn, "telemetry_key", key)
    return key


def revoke_key(conn):
    set_meta(conn, "telemetry_key", "")


def key_ok(conn, key):
    real = upload_key(conn)
    return bool(real and key) and hmac.compare_digest(str(key), real)


# --------------------------------------------------------------------------- reading an upload

def _text(v, limit=48):
    return str(v if v is not None else "").replace("\x00", "").strip()[:limit]


def _int(v, lo=0, hi=10**9):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _seconds(v):
    """A session time in seconds (0 when missing or nonsense)."""
    try:
        v = round(float(v), 3)
    except (TypeError, ValueError):
        return 0
    return v if 0 < v < 36000 else 0


def clean(payload):
    """Check an upload and keep only what the site uses. Raises ValidationError when it isn't a results summary."""
    if not isinstance(payload, dict):
        raise S.ValidationError("Expected one session's results as a JSON object")
    sess = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise S.ValidationError("No results in the upload")
    if len(results) > MAX_CARS:
        raise S.ValidationError(f"Too many cars ({len(results)}); a session has at most {MAX_CARS}")
    type_id = _int(sess.get("session_type_id"), 0, 255)
    out_sess = {"track": _text(sess.get("track")), "session_type": _text(sess.get("session_type")),
                "session_type_id": type_id, "kind": KINDS.get(type_id, "unknown"),
                "ai_difficulty": _int(sess.get("ai_difficulty"), 0, 110),
                "weather": _text(sess.get("weather"), 24), "total_laps": _int(sess.get("total_laps"), 0, 200),
                "weather_seen": [_text(w, 24) for w in (sess.get("weather_seen") or [])[:12] if isinstance(w, str)]}
    rows = []
    for r in results:
        if not isinstance(r, dict):
            continue
        status = _text(r.get("status"), 20)
        rows.append({"position": _int(r.get("position"), 0, MAX_CARS), "name": _text(r.get("name")),
                     "team": _text(r.get("team")), "status": status if status in STATUSES else "Finished",
                     "reason": _text(r.get("reason")), "grid": _int(r.get("grid"), 0, MAX_CARS),
                     "laps": _int(r.get("laps"), 0, 300), "best_lap_ms": _int(r.get("best_lap_ms"), 0, 10**8),
                     "best_lap": _text(r.get("best_lap"), 12), "penalty_s": _int(r.get("penalty_s"), 0, 255),
                     "race_number": _int(r.get("race_number"), 0, 999), "ai": bool(r.get("ai")),
                     "fastest_lap": bool(r.get("fastest_lap")), "race_time_s": _seconds(r.get("race_time_s"))})
    if not any(r["name"] for r in rows):
        raise S.ValidationError("The results have no driver names")
    # The fastest lap, if the sender didn't mark it: the lowest best lap.
    if not any(r["fastest_lap"] for r in rows):
        timed = [r for r in rows if r["best_lap_ms"]]
        if timed:
            min(timed, key=lambda r: r["best_lap_ms"])["fastest_lap"] = True
    rows.sort(key=lambda r: (not r["position"], r["position"] or 0))
    events = []
    for e in (payload.get("events") or [])[:MAX_EVENTS]:
        if isinstance(e, dict) and e.get("code") in ("PENA", "COLL", "RTMT", "FTLP", "DTSV", "SGSV", "RDFL", "SCAR"):
            events.append({"code": e["code"], "driver": _text(e.get("driver")), "other_driver": _text(e.get("other_driver")),
                           "seconds": _int(e.get("seconds"), 0, 255), "lap": _int(e.get("lap"), 0, 300),
                           "penalty_type": _int(e.get("penalty_type"), 0, 255),
                           "infringement": _int(e.get("infringement"), 0, 255),
                           "lap_time": _text(e.get("lap_time"), 12)})
    return {"session": out_sess, "results": rows, "events": events,
            "session_uid": _text(payload.get("session_uid"), 32)}


def store(conn, payload):
    """Keep one uploaded session. The same session sent again replaces the earlier copy. Returns its id."""
    ensure_table(conn)
    data = clean(payload)
    sess = data["session"]
    row = None
    if data["session_uid"]:
        row = conn.execute("SELECT id FROM telemetry_uploads WHERE session_uid = ? AND session_type_id IS ?",
                           (data["session_uid"], sess["session_type_id"])).fetchone()
    values = (now_iso(), data["session_uid"], sess["session_type_id"], sess["track"], sess["session_type"],
              len(data["results"]), json.dumps(data, ensure_ascii=False), json.dumps(payload, ensure_ascii=False),
              _text(payload.get("recorder"), 60))
    if row:   # sent again (say, rebuilt by a newer recorder): the newer copy replaces it and keeps its round
        conn.execute("UPDATE telemetry_uploads SET received_at = ?, session_uid = ?, session_type_id = ?, track = ?, "
                     "session_type = ?, cars = ?, payload = ?, raw = ?, recorder = ? WHERE id = ?", values + (row["id"],))
        upload_id = row["id"]
    else:
        upload_id = conn.execute("INSERT INTO telemetry_uploads(received_at, session_uid, session_type_id, track, "
                                 "session_type, cars, payload, raw, recorder) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 values).lastrowid
    link(conn, upload_id)
    conn.execute("DELETE FROM telemetry_uploads WHERE used_event_id IS NULL AND id NOT IN "
                 "(SELECT id FROM telemetry_uploads WHERE used_event_id IS NULL ORDER BY id DESC LIMIT ?)", (KEEP,))
    return upload_id


def link(conn, upload_id):
    """Link a new upload to its round: the current season's first unfinished round at that circuit. Linked uploads
    are kept for good, so later features can read more out of a round's game data."""
    row = conn.execute("SELECT track, used_event_id FROM telemetry_uploads WHERE id = ?", (upload_id,)).fetchone()
    if not row or row["used_event_id"]:
        return None
    circuit = _circuit(row["track"])
    if not circuit:
        return None
    from . import constants as C
    sid = S.current_season_id(conn)
    for e in S.events(conn, sid) if sid else []:
        if e["status"] != C.EVENT_COMPLETE and _circuit(f"{e['name']} {e.get('location') or ''}") == circuit:
            conn.execute("UPDATE telemetry_uploads SET used_event_id = ?, used_at = ? WHERE id = ?",
                         (e["id"], now_iso(), upload_id))
            return e["id"]
    return None


def recent(conn, limit=12):
    ensure_table(conn)
    rows = conn.execute("""SELECT u.id, u.received_at, u.track, u.session_type, u.session_type_id, u.cars,
                                  u.used_event_id, e.round_number AS used_round
                           FROM telemetry_uploads u LEFT JOIN events e ON e.id = u.used_event_id
                           ORDER BY u.id DESC LIMIT ?""", (limit,)).fetchall()
    return [{**dict(r), "kind": KINDS.get(r["session_type_id"], "unknown")} for r in rows]


def get(conn, upload_id):
    ensure_table(conn)
    row = conn.execute("SELECT * FROM telemetry_uploads WHERE id = ?", (upload_id,)).fetchone()
    if not row:
        return None
    return {**json.loads(row["payload"]), "id": row["id"], "received_at": row["received_at"]}


# --------------------------------------------------------------------------- after an import is applied

def names(conn):
    """Game name + team -> driver id, remembered from earlier imports (so the next one matches straight away)."""
    try:
        data = json.loads(get_meta(conn, "telemetry_names") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def applied(conn, upload_id, event_id, mapping):
    """Remember who was who, and which round an upload went into. mapping: {"NAME|Team": driver_id}."""
    known = {r[0] for r in conn.execute("SELECT id FROM drivers")}
    saved = names(conn)
    for k, v in (mapping or {}).items():
        did = _int(v, 1)
        if isinstance(k, str) and 0 < len(k) <= 100 and did in known:
            saved[k] = did
    if len(saved) > 300:
        saved = dict(list(saved.items())[-300:])
    set_meta(conn, "telemetry_names", json.dumps(saved, ensure_ascii=False))
    if upload_id:
        ensure_table(conn)
        conn.execute("UPDATE telemetry_uploads SET used_event_id = ?, used_at = ? WHERE id = ?",
                     (event_id, now_iso(), upload_id))


# --------------------------------------------------------------------------- a whole round from the game
# The game's weather, per session, as the round's weather record (f1tracker/weather.py CONDITIONS).
WEATHER = {"Clear": "dry", "Light cloud": "dry", "Overcast": "overcast", "Light rain": "light_rain",
           "Heavy rain": "heavy_rain", "Storm": "heavy_rain"}
ROUND_WINDOW_HOURS = 72     # sessions of one race night arrive together; older ones at the same track aren't this round


def weather_key(sess):
    """One condition for a session: "changing" when it was both dry and wet, else what it mostly was."""
    seen = [WEATHER[w] for w in (sess.get("weather_seen") or []) + [sess.get("weather")] if w in WEATHER]
    if not seen:
        return None
    wet = [w for w in seen if w in ("light_rain", "heavy_rain")]
    if wet and len(wet) < len(seen):
        return "changing"
    if wet:
        return "heavy_rain" if "heavy_rain" in wet else "light_rain"
    return "overcast" if seen.count("overcast") > len(seen) / 2 else "dry"


GAME_TRACKS = {"Losail": "Lusail"}   # the game's track names the circuit list spells differently


def _circuit(text):
    from . import circuits
    found = circuits.lookup(GAME_TRACKS.get(text, text) or "")
    return found["circuit"] if found["code"] else None


def for_round(conn, event):
    """The game sessions that belong to this round, newest race night at its circuit:
    {"qualifying": [uploads, Q1 first], "sprint": upload or None, "race": upload or None}. Empty when none match."""
    from datetime import datetime, timedelta
    ensure_table(conn)
    circuit = _circuit(f"{event['name']} {event.get('location') or ''}")
    if not circuit:
        return {}
    rows = [r for r in conn.execute("SELECT id, received_at, track, session_type_id, used_event_id FROM telemetry_uploads "
                                    "WHERE used_event_id = ? OR used_event_id IS NULL ORDER BY id DESC", (event["id"],))
            if r["used_event_id"] == event["id"] or _circuit(r["track"]) == circuit]
    if any(r["used_event_id"] == event["id"] for r in rows):
        rows = [r for r in rows if r["used_event_id"] == event["id"]]   # linked to this round: just those
    if not rows:
        return {}

    def when(r):
        try:
            return datetime.fromisoformat(r["received_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError):
            return None
    newest = when(rows[0])
    rows = [r for r in rows if newest is None or (when(r) and newest - when(r) <= timedelta(hours=ROUND_WINDOW_HOURS))]
    out = {"qualifying": [], "sprint": None, "race": None}
    quali = {}
    for r in rows:   # newest first: the first of each kind wins
        kind = KINDS.get(r["session_type_id"])
        if kind == "sprint_or_race":
            kind = "sprint" if event.get("is_sprint") else "race"
        if kind == "qualifying":
            quali.setdefault(r["session_type_id"], r["id"])
        elif kind in ("sprint", "race") and out[kind] is None:
            out[kind] = r["id"]
    out["qualifying"] = [get(conn, quali[t]) for t in sorted(quali)]
    for kind in ("sprint", "race"):
        out[kind] = get(conn, out[kind]) if out[kind] else None
    if not out["qualifying"] and not out["sprint"] and not out["race"]:
        return {}
    return out


def round_summary(bundle):
    """What a round's game sessions hold, for the round page: [("Qualifying", "Q1, Q2, Q3"), ("Race", "22 cars")]."""
    if not bundle:
        return []
    out = []
    if bundle["qualifying"]:
        out.append(("Qualifying", ", ".join(q["session"]["session_type"] for q in bundle["qualifying"])))
    for kind, label in (("sprint", "Sprint"), ("race", "Race")):
        if bundle[kind]:
            out.append((label, f"{len(bundle[kind]['results'])} cars"))
    return out


# --------------------------------------------------------------------------- what each round's game data holds
# Every piece of data the site can take from the game, and how to tell whether a session's upload has it. When a
# feature needs more, add it here: the Race data page then lists which rounds are missing it, and a newer recorder
# can rebuild old recordings and send them again (the same session replaces its earlier copy and keeps its round).
DATA = [
    ("order", "Finishing order", ("qualifying", "sprint", "race"), lambda u: any(r.get("position") for r in u["results"])),
    ("names", "Driver names", ("qualifying", "sprint", "race"), lambda u: all(r.get("name") for r in u["results"])),
    ("best_laps", "Best laps", ("qualifying", "sprint", "race"), lambda u: any(r.get("best_lap_ms") for r in u["results"])),
    ("race_times", "Race times", ("sprint", "race"), lambda u: any(r.get("race_time_s") for r in u["results"])),
    ("ai_level", "AI level", ("qualifying", "sprint", "race"), lambda u: bool(u["session"].get("ai_difficulty"))),
    ("weather", "Weather through the session", ("qualifying", "sprint", "race"),
     lambda u: bool(u["session"].get("weather_seen"))),
    ("incidents", "Penalties and incidents", ("sprint", "race"), lambda u: "events" in (u.get("raw") or {})),
]


def coverage(conn, season_id):
    """Per round of a season: the game sessions linked to it and what data is missing.
    [{event, sessions: {kind: [{id, label, recorder, received_at}]}, missing: [(session label, data label)]}]"""
    ensure_table(conn)
    rows = conn.execute("SELECT * FROM telemetry_uploads WHERE used_event_id IN "
                        "(SELECT id FROM events WHERE season_id = ?) ORDER BY id", (season_id,)).fetchall()
    by_event = {}
    for r in rows:
        u = json.loads(r["payload"])
        try:
            u["raw"] = json.loads(r["raw"]) if r["raw"] else {}
        except ValueError:
            u["raw"] = {}
        by_event.setdefault(r["used_event_id"], []).append((r, u))
    out = []
    for e in S.events(conn, season_id):
        kinds = {"qualifying": [], "sprint": [], "race": []}
        for r, u in by_event.get(e["id"], []):
            kind = KINDS.get(r["session_type_id"])
            if kind == "sprint_or_race":
                kind = "sprint" if e["is_sprint"] else "race"
            if kind in kinds:
                kinds[kind].append((r, u))
        missing = []
        wanted = ["qualifying"] + (["sprint"] if e["is_sprint"] else []) + ["race"]
        if any(kinds.values()):
            for kind in wanted:
                label = {"qualifying": "Qualifying", "sprint": "Sprint", "race": "Race"}[kind]
                if not kinds[kind]:
                    missing.append((label, "not recorded"))
                    continue
                for key, text, applies, has in DATA:
                    if kind in applies and not any(has(u) for _r, u in kinds[kind]):
                        missing.append((label, text))
        out.append({"event": e, "missing": missing, "recorded": any(kinds.values()),
                    "sessions": {k: [{"id": r["id"], "label": r["session_type"], "recorder": r["recorder"],
                                      "received_at": r["received_at"]} for r, _u in v] for k, v in kinds.items()}})
    return out
