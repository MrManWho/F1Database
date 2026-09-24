"""League features around the racing: settings toggles, check-ins, comments, reactions, fan votes,
predictions, driver profiles and the Race Master's activity log."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from . import auth
from . import constants as C
from . import services as S
from .services import ValidationError
from .storage import get_meta, now_iso, set_meta

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------- feature toggles

def features(conn):
    out = {}
    for key, (_label, _desc, default) in C.FEATURES.items():
        value = get_meta(conn, f"feature_{key}")
        out[key] = default if value is None else value == "1"
    from . import league_profile
    out["public"] = league_profile.is_public(conn)   # v2.0: decided by the league's visibility setting
    return out


def set_features(conn, enabled):
    """enabled: the feature keys to switch on; every other feature is switched off."""
    for key in C.FEATURES:
        set_meta(conn, f"feature_{key}", "1" if key in enabled else "0")
    if "public" in enabled:   # older callers: turning the public page on means "public results"
        set_meta(conn, "visibility", "public")
        set_meta(conn, "feature_public", "1")
        public_key(conn)


def public_key(conn, rotate=False):
    key = get_meta(conn, "public_key")
    if not key or rotate:
        key = secrets.token_urlsafe(9)
        set_meta(conn, "public_key", key)
    return key


# --------------------------------------------------------------------------- activity log

def audit(conn, username, action, detail="", summary=None, link=None):
    """Record what someone did. Repeats of the same thing within 10 minutes (autosaves) are merged.

    summary is a readable sentence without the person's name ("scheduled R2 Chinese GP for ..."); link is a path
    inside the league. Never pass passwords, webhook URLs or other private values here.
    """
    last = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    now = now_iso()
    if last and last["username"] == username and last["action"] == action and last["detail"] == detail \
            and (last["summary"] if "summary" in last.keys() else None) == summary:
        try:
            recent = datetime.fromisoformat(now) - datetime.fromisoformat(last["created_at"]) < timedelta(minutes=10)
        except ValueError:
            recent = False
        if recent:
            conn.execute("UPDATE audit_log SET created_at = ? WHERE id = ?", (now, last["id"]))
            return
    conn.execute("INSERT INTO audit_log(username, action, detail, created_at, summary, link) VALUES(?,?,?,?,?,?)",
                 (username, action, detail[:300], now, (summary or "")[:400] or None, link))


def audit_entries(conn, limit=300, username=None):
    sql = "SELECT * FROM audit_log" + (" WHERE username = ?" if username else "") + " ORDER BY id DESC LIMIT ?"
    return [dict(r) for r in conn.execute(sql, ((username, limit) if username else (limit,)))]


# --------------------------------------------------------------------------- race times

def parse_race_at(value, tz_offset_minutes=0):
    """A browser datetime-local value plus the browser's getTimezoneOffset() -> UTC ISO string."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        local = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("That race time isn't a valid date and time") from exc
    try:
        offset = int(tz_offset_minutes or 0)
    except (TypeError, ValueError):
        offset = 0
    return (local + timedelta(minutes=offset)).replace(tzinfo=timezone.utc).isoformat(timespec="minutes")


def race_started(event):
    """True once the scheduled race time has passed. Times saved without a zone (older saves) are read as the
    server's clock instead of crashing the comparison."""
    from . import timefmt
    when = timefmt.parse(event.get("race_at"))
    return bool(when and when <= datetime.now(timezone.utc))


def predictions_closed_reason(event):
    """Why picks can't be made or changed any more (None while they're open)."""
    if event["status"] == C.EVENT_COMPLETE:
        return "This round is complete."
    if event["status"] != C.EVENT_NOT_RUN:
        return "Results have started going in for this round, so picks are closed."
    if event.get("lights_at"):
        return "Picks closed at lights out."
    if race_started(event):
        return "Picks closed when the race started (the scheduled race time)."
    return None


def set_race_at(conn, event_id, race_at):
    conn.execute("UPDATE events SET race_at = ? WHERE id = ?", (race_at, event_id))


# --------------------------------------------------------------------------- people

def _names(usernames):
    out = {}
    for name in set(usernames):
        user = auth.get_user(name)
        out[name] = user["display_name"] if user else name
    return out


def member_driver_ids(conn):
    return {r["username"]: r["driver_id"] for r in conn.execute("SELECT username, driver_id FROM career_members")}


# --------------------------------------------------------------------------- check-ins

def set_checkin(conn, event_id, username, status):
    if status not in C.CHECKIN_CHOICES:
        raise ValidationError("Pick in, maybe or out")
    event = S.get_event(conn, event_id)
    if not event or event["status"] == C.EVENT_COMPLETE:
        raise ValidationError("That race has already happened")
    conn.execute("""INSERT INTO checkins(event_id, username, status, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(event_id, username) DO UPDATE SET status = excluded.status,
                    updated_at = excluded.updated_at""", (event_id, username, status, now_iso()))


def checkins(conn, event_id):
    """Everyone in the league with their answer (None = not answered yet)."""
    answers = {r["username"]: r["status"] for r in conn.execute("SELECT * FROM checkins WHERE event_id = ?", (event_id,))}
    members = member_driver_ids(conn)
    dmap = S.driver_map(conn)
    everyone = list(members) + [u for u in answers if u not in members]
    names = _names(everyone)
    rows = [{"username": u, "name": names[u], "driver": dmap.get(members.get(u)), "status": answers.get(u)}
            for u in everyone]
    order = {"in": 0, "maybe": 1, "out": 2, None: 3}
    rows.sort(key=lambda r: (order[r["status"]], r["name"].lower()))
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in C.CHECKIN_CHOICES}
    return rows, counts


# --------------------------------------------------------------------------- comments & reactions

def _check_target(conn, target):
    kind, _, raw = (target or "").partition(":")
    if kind not in ("event", "news") or not raw.isdigit():
        raise ValidationError("Unknown item")
    table = "events" if kind == "event" else "news"
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (int(raw),)).fetchone():
        raise ValidationError("That item no longer exists")
    return kind, int(raw)


def add_comment(conn, target, username, body):
    _check_target(conn, target)
    body = (body or "").strip()
    if not body:
        raise ValidationError("Write something first")
    if len(body) > 1000:
        raise ValidationError("Comments are limited to 1000 characters")
    cur = conn.execute("INSERT INTO comments(target, username, body, created_at) VALUES(?,?,?,?)",
                       (target, username, body, now_iso()))
    return cur.lastrowid


def delete_comment(conn, comment_id, username, is_master):
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not row:
        raise ValidationError("That comment is already gone")
    if row["username"] != username and not is_master:
        raise ValidationError("You can only delete your own comments")
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    return dict(row)


def comments(conn, target):
    rows = [dict(r) for r in conn.execute("SELECT * FROM comments WHERE target = ? ORDER BY id", (target,))]
    names = _names(r["username"] for r in rows)
    for r in rows:
        r["name"] = names[r["username"]]
    return rows


def comment_counts(conn, targets):
    if not targets:
        return {}
    marks = ",".join("?" * len(targets))
    return {r[0]: r[1] for r in conn.execute(
        f"SELECT target, COUNT(*) FROM comments WHERE target IN ({marks}) GROUP BY target", list(targets))}


def toggle_reaction(conn, target, username, emoji):
    _check_target(conn, target)
    if emoji not in C.REACTIONS:
        raise ValidationError("Unknown reaction")
    if conn.execute("DELETE FROM reactions WHERE target = ? AND username = ? AND emoji = ?",
                    (target, username, emoji)).rowcount == 0:
        conn.execute("INSERT INTO reactions(target, username, emoji) VALUES(?,?,?)", (target, username, emoji))


def reactions(conn, targets, username):
    """{target: [{emoji, count, mine, who}]} with every reaction type listed."""
    out = {t: {e: {"emoji": e, "count": 0, "mine": False, "who": []} for e in C.REACTIONS} for t in targets}
    if not targets:
        return {}
    marks = ",".join("?" * len(targets))
    rows = conn.execute(f"SELECT * FROM reactions WHERE target IN ({marks})", list(targets)).fetchall()
    names = _names(r["username"] for r in rows)
    for r in rows:
        slot = out[r["target"]].get(r["emoji"])
        if slot:
            slot["count"] += 1
            slot["mine"] = slot["mine"] or r["username"] == username
            slot["who"].append(names[r["username"]])
    return {t: list(v.values()) for t, v in out.items()}


# --------------------------------------------------------------------------- fan Driver of the Day

def fan_vote(conn, event_id, username, driver_id):
    event = S.get_event(conn, event_id)
    if not event or event["status"] != C.EVENT_COMPLETE:
        raise ValidationError("Voting opens once the race is complete")
    if not conn.execute("SELECT 1 FROM results WHERE event_id = ? AND driver_id = ?", (event_id, driver_id)).fetchone():
        raise ValidationError("That driver wasn't in this race")
    conn.execute("""INSERT INTO fan_votes(event_id, username, driver_id) VALUES(?,?,?)
                    ON CONFLICT(event_id, username) DO UPDATE SET driver_id = excluded.driver_id""",
                 (event_id, username, driver_id))


def fan_votes(conn, event_id, username):
    dmap = S.driver_map(conn)
    rows = conn.execute("SELECT driver_id, COUNT(*) AS n FROM fan_votes WHERE event_id = ? GROUP BY driver_id "
                        "ORDER BY n DESC", (event_id,)).fetchall()
    mine = conn.execute("SELECT driver_id FROM fan_votes WHERE event_id = ? AND username = ?",
                        (event_id, username)).fetchone()
    total = sum(r["n"] for r in rows)
    return {"tally": [{"driver": dmap.get(r["driver_id"]), "votes": r["n"]} for r in rows if dmap.get(r["driver_id"])],
            "total": total, "mine": mine["driver_id"] if mine else None}


# --------------------------------------------------------------------------- race-day hub

def race_story(conn, event_id):
    """Podium, biggest movers and the results-sheet awards for a completed weekend."""
    rows = [r for r in S.weekend_rows(conn, event_id)]
    finished = sorted((r for r in rows if r["race_position"] and r["result_status"] == C.STATUS_FINISHED),
                      key=lambda r: r["race_position"])
    movers = []
    for r in rows:
        if r["qualifying_position"] and r["race_position"] and r["result_status"] == C.STATUS_FINISHED:
            movers.append({**r, "gained": r["qualifying_position"] - r["race_position"]})
    movers.sort(key=lambda r: -r["gained"])
    return {
        "podium": finished[:3],
        "gainers": [m for m in movers if m["gained"] > 0][:3],
        "losers": sorted([m for m in movers if m["gained"] < 0], key=lambda r: r["gained"])[:2],
        "pole": next((r for r in rows if r["qualifying_position"] == 1), None),
        "fastest_lap": next((r for r in rows if r["fastest_lap"]), None),
        "dotd": next((r for r in rows if r["driver_of_day"]), None),
        "dnfs": [r for r in rows if r["result_status"] in ("DNF", "DSQ")],
    }


# --------------------------------------------------------------------------- predictions

PICKS = ["pole", "winner", "fastest_lap", "top_player"]


def predictions_locked(event):
    return event["status"] != C.EVENT_NOT_RUN or bool(event.get("lights_at")) or race_started(event)


def save_prediction(conn, event_id, username, picks):
    event = S.get_event(conn, event_id)
    if not event:
        raise ValidationError("Unknown race")
    if predictions_locked(event):
        raise ValidationError("Predictions for this race are locked")
    entrants = {r["driver_id"] for r in conn.execute("SELECT driver_id FROM results WHERE event_id = ?", (event_id,))}
    if not entrants:
        entrants = set(S.driver_seats(conn, event["season_id"]))
    players = {d["id"] for d in S.player_drivers(conn)}
    values = {}
    for key in PICKS:
        try:
            value = int(picks.get(key)) if picks.get(key) not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        if value is not None and (value not in entrants or (key == "top_player" and value not in players)):
            raise ValidationError("Pick drivers who are racing this weekend")
        values[key] = value
    if not any(values.values()):
        raise ValidationError("Make at least one pick")
    conn.execute("""INSERT INTO predictions(event_id, username, pole_id, winner_id, fastest_lap_id, top_player_id, updated_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id, username) DO UPDATE SET pole_id = excluded.pole_id,
                    winner_id = excluded.winner_id, fastest_lap_id = excluded.fastest_lap_id,
                    top_player_id = excluded.top_player_id, updated_at = excluded.updated_at""",
                 (event_id, username, values["pole"], values["winner"], values["fastest_lap"], values["top_player"],
                  now_iso()))


def event_outcome(conn, event_id):
    """The correct answer for each pick (None when it can't be known)."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM results WHERE event_id = ?", (event_id,))]
    players = {d["id"] for d in S.player_drivers(conn)}
    pole = next((r["driver_id"] for r in rows if r["qualifying_position"] == 1), None)
    winner = next((r["driver_id"] for r in rows if r["race_position"] == 1 and r["result_status"] == C.STATUS_FINISHED), None)
    fl = next((r["driver_id"] for r in rows if r["fastest_lap"]), None)
    classified = sorted((r for r in rows if r["driver_id"] in players and r["race_position"]
                         and r["result_status"] == C.STATUS_FINISHED), key=lambda r: r["race_position"])
    return {"pole": pole, "winner": winner, "fastest_lap": fl,
            "top_player": classified[0]["driver_id"] if classified else None}


def score(pick, outcome):
    hits = {k: bool(pick.get(f"{k}_id") and pick.get(f"{k}_id") == outcome.get(k)) for k in PICKS}
    return sum(C.PREDICTION_POINTS[k] for k, hit in hits.items() if hit), hits


def event_predictions(conn, event_id):
    event = S.get_event(conn, event_id)
    rows = [dict(r) for r in conn.execute("SELECT * FROM predictions WHERE event_id = ? ORDER BY updated_at", (event_id,))]
    names = _names(r["username"] for r in rows)
    outcome = event_outcome(conn, event_id) if event["status"] == C.EVENT_COMPLETE else None
    dmap = S.driver_map(conn)
    for r in rows:
        r["name"] = names[r["username"]]
        for k in PICKS:
            r[k] = dmap.get(r[f"{k}_id"])
        r["points"], r["hits"] = score(r, outcome) if outcome else (None, {})
    return rows, outcome


def leaderboard(conn, season_id):
    table = {}
    for event in S.events(conn, season_id):
        if event["status"] != C.EVENT_COMPLETE:
            continue
        outcome = event_outcome(conn, event["id"])
        for r in conn.execute("SELECT * FROM predictions WHERE event_id = ?", (event["id"],)):
            pts, hits = score(dict(r), outcome)
            row = table.setdefault(r["username"], {"username": r["username"], "points": 0, "rounds": 0, "exact": 0,
                                                   "correct": 0})
            row["points"] += pts
            row["rounds"] += 1
            row["correct"] += sum(hits.values())
            row["exact"] += all(hits[k] for k in PICKS if outcome.get(k))
    names = _names(table)
    rows = sorted(table.values(), key=lambda r: (-r["points"], -r["correct"], names[r["username"]].lower()))
    for i, r in enumerate(rows, 1):
        r["position"], r["name"] = i, names[r["username"]]
    return rows


# --------------------------------------------------------------------------- driver profiles

NATIONALITIES = [
    ("", "—"), ("AR", "Argentina"), ("AU", "Australia"), ("AT", "Austria"), ("BE", "Belgium"), ("BR", "Brazil"),
    ("CA", "Canada"), ("CN", "China"), ("DK", "Denmark"), ("FI", "Finland"), ("FR", "France"), ("DE", "Germany"),
    ("GB", "Great Britain"), ("IN", "India"), ("IE", "Ireland"), ("IT", "Italy"), ("JP", "Japan"), ("MX", "Mexico"),
    ("MC", "Monaco"), ("NL", "Netherlands"), ("NZ", "New Zealand"), ("NO", "Norway"), ("PL", "Poland"),
    ("PT", "Portugal"), ("RU", "Russia"), ("SA", "Saudi Arabia"), ("ZA", "South Africa"), ("KR", "South Korea"),
    ("ES", "Spain"), ("SE", "Sweden"), ("CH", "Switzerland"), ("TH", "Thailand"), ("AE", "United Arab Emirates"),
    ("US", "United States"),
]
NATIONALITY_NAMES = dict(NATIONALITIES)


def flag(code):
    if not code or len(code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper())


def profiles(conn):
    out = {}
    for r in conn.execute("SELECT * FROM driver_profiles"):
        r = dict(r)
        r["flag"] = flag(r["nationality"])
        r["country"] = NATIONALITY_NAMES.get(r["nationality"], "")
        out[r["driver_id"]] = r
    return out


def profile(conn, driver_id):
    return profiles(conn).get(driver_id) or {"driver_id": driver_id, "number": None, "nationality": "",
                                             "helmet_color": "", "avatar": None, "bio": "", "flag": "", "country": ""}


def save_profile(conn, driver_id, number, nationality, helmet_color, bio):
    if not S.driver_map(conn).get(driver_id):
        raise ValidationError("Unknown driver")
    num = None
    if str(number or "").strip():
        try:
            num = int(number)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Car number must be 0–99") from exc
        if not 0 <= num <= 99:
            raise ValidationError("Car number must be 0–99")
        taken = conn.execute("SELECT d.name FROM driver_profiles p JOIN drivers d ON d.id = p.driver_id "
                             "WHERE p.number = ? AND p.driver_id != ? AND d.active = 1", (num, driver_id)).fetchone()
        if taken:
            raise ValidationError(f"#{num} already belongs to {taken['name']}")
    nationality = (nationality or "").upper()
    if nationality not in NATIONALITY_NAMES:
        nationality = ""
    helmet_color = (helmet_color or "").strip()
    if helmet_color and not HEX_RE.match(helmet_color):
        raise ValidationError("Helmet colour must look like #ff0000")
    conn.execute("""INSERT INTO driver_profiles(driver_id, number, nationality, helmet_color, bio) VALUES(?,?,?,?,?)
                    ON CONFLICT(driver_id) DO UPDATE SET number = excluded.number, nationality = excluded.nationality,
                    helmet_color = excluded.helmet_color, bio = excluded.bio""",
                 (driver_id, num, nationality, helmet_color, (bio or "").strip()[:500]))


def set_avatar(conn, driver_id, filename):
    conn.execute("INSERT INTO driver_profiles(driver_id, avatar) VALUES(?, ?) "
                 "ON CONFLICT(driver_id) DO UPDATE SET avatar = excluded.avatar", (driver_id, filename))


IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"RIFF": "webp"}


def image_kind(data):
    for magic, ext in IMAGE_TYPES.items():
        if data.startswith(magic):
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return None


def contract_history(conn, driver_id):
    """Every deal a driver signed, newest first."""
    tmap = S.team_map(conn)
    rows = conn.execute("""SELECT o.*, w.target_year FROM offers o JOIN market_windows w ON w.id = o.window_id
                           WHERE o.driver_id = ? AND o.status = ? ORDER BY w.target_year DESC, o.id DESC""",
                        (driver_id, C.OFFER_ACCEPTED)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["team"] = tmap.get(r["team_id"])
        r["end_year"] = r["target_year"] + r["years"] - 1
        out.append(r)
    return out


# --------------------------------------------------------------------------- incidents

def report_incident(conn, event_id, username, reporter_driver_id, accused_id, description):
    event = S.get_event(conn, event_id)
    if not event or event["status"] == C.EVENT_NOT_RUN:
        raise ValidationError("You can report incidents once a race has results")
    entrants = {r["driver_id"] for r in conn.execute("SELECT driver_id FROM results WHERE event_id = ?", (event_id,))}
    if accused_id not in entrants:
        raise ValidationError("Pick a driver who was in that race")
    if accused_id == reporter_driver_id:
        raise ValidationError("You can't report yourself")
    description = (description or "").strip()
    if len(description) < 5:
        raise ValidationError("Say what happened (lap, corner, what they did)")
    if len(description) > 1000:
        raise ValidationError("Keep it under 1000 characters")
    cur = conn.execute("""INSERT INTO incidents(event_id, reporter, reporter_driver_id, accused_driver_id, description,
                          status, created_at) VALUES(?,?,?,?,?, 'Open', ?)""",
                       (event_id, username, reporter_driver_id, accused_id, description, now_iso()))
    return cur.lastrowid


def rule_incident(conn, incident_id, ruling, note, username):
    from . import feed
    inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if not inc:
        raise ValidationError("That report no longer exists")
    if ruling not in C.INCIDENT_RULINGS:
        raise ValidationError("Choose a ruling")
    note = (note or "").strip()[:500]
    conn.execute("UPDATE incidents SET status = 'Decided', ruling = ?, ruling_note = ?, decided_by = ?, decided_at = ? "
                 "WHERE id = ?", (ruling, note, username, now_iso(), incident_id))
    event = S.get_event(conn, inc["event_id"])
    dmap = S.driver_map(conn)
    accused = dmap[inc["accused_driver_id"]]["name"]
    where = f"R{event['round_number']} {event['name']}"
    headline = (f"No further action for {accused} after {where} incident" if ruling == "none"
                else f"{accused} given a {C.INCIDENT_RULINGS[ruling].split(' (')[0].lower()} for {where} incident")
    feed.post(conn, event["season_id"], "paddock", headline, note or inc["description"][:200], "incidents",
              driver_id=inc["accused_driver_id"])
    feed.notify(conn, inc["accused_driver_id"], f"Ruling on the {where} incident: {C.INCIDENT_RULINGS[ruling]}.", "incidents")
    if inc["reporter_driver_id"]:
        feed.notify(conn, inc["reporter_driver_id"], f"Your {where} report was decided: {C.INCIDENT_RULINGS[ruling]}.",
                    "incidents")


def incidents(conn, event_id=None, driver_ids=None, season_id=None):
    sql = """SELECT i.*, e.round_number, e.name AS event_name, e.season_id FROM incidents i
             JOIN events e ON e.id = i.event_id WHERE 1=1"""
    params = []
    if event_id:
        sql += " AND i.event_id = ?"
        params.append(event_id)
    if season_id:
        sql += " AND e.season_id = ?"
        params.append(season_id)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY i.id DESC", params)]
    if driver_ids:
        a, b = driver_ids
        rows = [r for r in rows if {r["reporter_driver_id"], r["accused_driver_id"]} == {a, b}]
    dmap = S.driver_map(conn)
    names = _names(r["reporter"] for r in rows)
    for r in rows:
        r["accused"] = dmap.get(r["accused_driver_id"])
        r["reporter_driver"] = dmap.get(r["reporter_driver_id"])
        r["reporter_name"] = names.get(r["reporter"], r["reporter"])
        r["ruling_label"] = C.INCIDENT_RULINGS.get(r["ruling"])
    return rows
