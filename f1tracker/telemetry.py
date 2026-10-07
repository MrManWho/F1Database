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
KEEP = 40                  # uploads kept per league (oldest are dropped)
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
                "weather": _text(sess.get("weather"), 24), "total_laps": _int(sess.get("total_laps"), 0, 200)}
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
                     "fastest_lap": bool(r.get("fastest_lap"))})
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
              len(data["results"]), json.dumps(data, ensure_ascii=False))
    if row:
        conn.execute("UPDATE telemetry_uploads SET received_at = ?, session_uid = ?, session_type_id = ?, track = ?, "
                     "session_type = ?, cars = ?, payload = ? WHERE id = ?", values + (row["id"],))
        upload_id = row["id"]
    else:
        upload_id = conn.execute("INSERT INTO telemetry_uploads(received_at, session_uid, session_type_id, track, "
                                 "session_type, cars, payload) VALUES(?, ?, ?, ?, ?, ?, ?)", values).lastrowid
    conn.execute("DELETE FROM telemetry_uploads WHERE id NOT IN "
                 "(SELECT id FROM telemetry_uploads ORDER BY id DESC LIMIT ?)", (KEEP,))
    return upload_id


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
