"""League announcements (v2.0): written by a Race Master, shown at the top of the Control Room.

Each one can be pinned, aimed at some roles only, scheduled for later and given an expiry. Publishing sends one
in-app notification per recipient and, if the author ticks it, emails the members who want Announcements email
from THIS league (their per-league preferences, the delivery log and its dedupe/loop protection all apply).
Scheduled announcements go out the next time anyone opens the league after their time, so no background
service is needed.
"""

from . import feed, notices, timefmt
from .services import ValidationError
from .storage import now_iso

AUDIENCES = {
    "all": "Everyone in the league",
    "drivers": "Drivers (members who control a player driver)",
    "scorekeepers": "Scorekeepers",
    "race_masters": "Race Masters",
    "spectators": "Spectators",
}


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
        audience TEXT NOT NULL DEFAULT 'all', pinned INTEGER NOT NULL DEFAULT 0, email INTEGER NOT NULL DEFAULT 0,
        publish_at TEXT, expires_at TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, published_at TEXT)""")


def _now():
    return timefmt.parse(now_iso())


def _members(conn):
    return [dict(r) for r in conn.execute("SELECT username, role, driver_id FROM career_members")]


def _matches(member, audience):
    wanted = set((audience or "all").split(","))
    if "all" in wanted:
        return True
    return (("drivers" in wanted and member.get("driver_id")) or
            ("scorekeepers" in wanted and member.get("role") == "scorekeeper") or
            ("race_masters" in wanted and member.get("role") == "race_master") or
            ("spectators" in wanted and member.get("role") == "spectator"))


def recipients(conn, audience):
    return [m["username"] for m in _members(conn) if _matches(m, audience)]


def preview(conn, audience, exclude=None):
    """How many members would see it, get a phone alert and get an email (for the form)."""
    people = [u for u in recipients(conn, audience) if u != exclude]
    return {"app": len(people), "push": len(notices.wanted(conn, people, "announcements", "push")),
            "email": len(notices.email_recipients(conn, people, "announcements"))}


def clean_audience(values):
    picked = [v for v in values if v in AUDIENCES]
    if not picked or "all" in picked:
        return "all"
    return ",".join(sorted(set(picked)))


def create(conn, username, title, body, audience="all", pinned=False, email=False, publish_at=None, expires_at=None):
    title = " ".join((title or "").split())[:120]
    body = (body or "").strip()[:4000]
    if len(title) < 3:
        raise ValidationError("Give the announcement a title")
    if expires_at and timefmt.parse(expires_at) <= (timefmt.parse(publish_at) if publish_at else _now()):
        raise ValidationError("The expiry has to be after the announcement goes out")
    _table(conn)
    cur = conn.execute("""INSERT INTO announcements(title, body, audience, pinned, email, publish_at, expires_at,
                          created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                       (title, body, audience, int(bool(pinned)), int(bool(email)), publish_at, expires_at,
                        username, now_iso()))
    ann_id = cur.lastrowid
    if not publish_at or timefmt.parse(publish_at) <= _now():
        publish(conn, ann_id)
    return ann_id


def get(conn, ann_id):
    _table(conn)
    row = conn.execute("SELECT * FROM announcements WHERE id = ?", (ann_id,)).fetchone()
    return dict(row) if row else None


def publish(conn, ann_id):
    """Send it once (a second call does nothing)."""
    a = get(conn, ann_id)
    if not a or a["published_at"]:
        return False
    conn.execute("UPDATE announcements SET published_at = ? WHERE id = ?", (now_iso(), ann_id))
    text = f"📣 {a['title']}" + (f": {a['body'][:240]}" + ("…" if len(a["body"]) > 240 else "") if a["body"] else "")
    feed.notify(conn, None, text, "dashboard#announcements", ref=f"announcement:{ann_id}", category="announcements",
                email=bool(a["email"]), dedupe=f"announcement:{ann_id}", usernames=recipients(conn, a["audience"]))
    return True


def publish_due(conn):
    """Publish scheduled announcements whose time has come. Cheap when there are none."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'announcements'").fetchone():
        return 0
    now, n = _now(), 0
    for row in conn.execute("SELECT id, publish_at FROM announcements WHERE published_at IS NULL").fetchall():
        if row["publish_at"] and timefmt.parse(row["publish_at"]) <= now:
            n += publish(conn, row["id"])
    return n


def _active(a, now):
    return bool(a["published_at"]) and not (a["expires_at"] and timefmt.parse(a["expires_at"]) <= now)


def visible(conn, username, role, driver_id, manager=False):
    """Announcements this person sees now: pinned first, newest first. Managers also see ones aimed at others."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'announcements'").fetchone():
        return []
    now = _now()
    me = {"username": username, "role": role, "driver_id": driver_id}
    rows = [dict(r) for r in conn.execute("SELECT * FROM announcements ORDER BY pinned DESC, id DESC")]
    return [a for a in rows if _active(a, now) and (manager or _matches(me, a["audience"]))][:10]


def all_for_admin(conn):
    _table(conn)
    now = _now()
    out = []
    for a in conn.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 100"):
        a = dict(a)
        a["state"] = ("Scheduled" if not a["published_at"] else
                      "Expired" if a["expires_at"] and timefmt.parse(a["expires_at"]) <= now else "Live")
        a["audience_label"] = ", ".join(AUDIENCES[x].split(" (")[0] for x in a["audience"].split(",") if x in AUDIENCES)
        out.append(a)
    return out


def set_pinned(conn, ann_id, pinned):
    _table(conn)
    conn.execute("UPDATE announcements SET pinned = ? WHERE id = ?", (int(bool(pinned)), ann_id))


def end(conn, ann_id):
    """Take it down now (kept in the list as Expired; a scheduled one is cancelled)."""
    _table(conn)
    a = get(conn, ann_id)
    if not a:
        return
    if not a["published_at"]:
        conn.execute("DELETE FROM announcements WHERE id = ?", (ann_id,))
    else:
        conn.execute("UPDATE announcements SET expires_at = ? WHERE id = ?",
                     (_now().astimezone(timefmt.timezone.utc).isoformat(timespec="minutes"), ann_id))
