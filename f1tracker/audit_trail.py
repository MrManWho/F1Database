"""The change record (4.0 Phase 1): who changed what, when, and for sensitive changes the values before and after.

Two stores, both append-only (database triggers refuse any edit or deletion):
  * each league file's audit_events: every change made in the league, with before/after values when the change
    touches members and roles, league settings or a round;
  * accounts.db site_audit: every change the site owner makes to the site (accounts, leagues, settings, backups).

The plain-language Activity Log (community.audit) is unchanged and still merges repeated autosaves; this record
never merges. Secrets are never stored: a Discord webhook or public-link key is recorded only as "set" or "not set".
"""

import json

from . import auth
from .storage import SECRET_META, now_iso

# Meta keys that change on their own (page views, background bookkeeping), so they aren't "changes".
VOLATILE_META = {"last_opened_at", "schema_version"}
VOLATILE_PREFIXES = ("impact", "auto_backup", "last_")
EVENT_FIELDS = ("round_number", "name", "status", "is_sprint", "race_at", "ai_difficulty", "ai_untracked",
                "postponed", "cancelled", "submitted_at", "paddock_at", "lights_at", "gp_distance", "sprint_distance")
MEMBER_WORDS = ("member", "invite", "invitation", "join", "ownership", "role", "league_leave")


def kind(endpoint, kwargs):
    """Which before/after snapshot a change gets: members / settings / event, or None."""
    endpoint = endpoint or ""
    if any(w in endpoint for w in MEMBER_WORDS):
        return "members"
    if "settings" in endpoint or endpoint in ("visibility_save", "league_profile_save", "calc_update_choose"):
        return "settings"
    if "event_id" in (kwargs or {}):
        return "event"
    return None


def snapshot(conn, what, kwargs):
    if what == "members":
        return {r["username"]: f"{r['role']}" + (f", driver {r['driver_id']}" if r["driver_id"] else "")
                for r in conn.execute("SELECT username, role, driver_id FROM career_members")}
    if what == "settings":
        out = {}
        for r in conn.execute("SELECT key, value FROM meta"):
            k = r["key"]
            if k in VOLATILE_META or k.startswith(VOLATILE_PREFIXES):
                continue
            out[k] = ("set" if r["value"] else "not set") if k in SECRET_META else r["value"]
        return out
    if what == "event":
        row = conn.execute("SELECT * FROM events WHERE id = ?", (kwargs.get("event_id"),)).fetchone()
        return {k: row[k] for k in EVENT_FIELDS if row is not None and k in row.keys()}
    return None


def diff(before, after):
    """Only what changed: ({key: old}, {key: new})."""
    if before is None or after is None:
        return None, None
    keys = sorted(set(before) | set(after))
    changed = [k for k in keys if before.get(k) != after.get(k)]
    if not changed:
        return None, None
    return {k: before.get(k) for k in changed}, {k: after.get(k) for k in changed}


def begin(conn, endpoint, kwargs):
    """Call before a change: remembers the snapshot to compare with afterwards."""
    what = kind(endpoint, kwargs)
    return what, (snapshot(conn, what, kwargs) if what else None)


def record(conn, actor, endpoint, label, target, link, started, kwargs):
    what, before = started or (None, None)
    old, new = diff(before, snapshot(conn, what, kwargs)) if what else (None, None)
    conn.execute("""INSERT INTO audit_events(created_at, actor, action, label, target, link, before, after)
                    VALUES(?,?,?,?,?,?,?,?)""",
                 (now_iso(), actor, endpoint, label[:120], (target or "")[:300] or None, link,
                  json.dumps(old, default=str) if old else None, json.dumps(new, default=str) if new else None))


def events(conn, limit=200):
    rows = conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_decoded(r) for r in rows]


def _decoded(row):
    r = dict(row)
    r["before"] = json.loads(r["before"]) if r.get("before") else None
    r["after"] = json.loads(r["after"]) if r.get("after") else None
    r["changes"] = [(k, (r["before"] or {}).get(k), (r["after"] or {}).get(k))
                    for k in sorted(set(r["before"] or {}) | set(r["after"] or {}))]
    return r


# --------------------------------------------------------------------------- site-wide record (accounts.db)

def _site_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS site_audit (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
        target TEXT, outcome TEXT)""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS site_audit_no_update BEFORE UPDATE ON site_audit
                    BEGIN SELECT RAISE(ABORT, 'The change record cannot be edited'); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS site_audit_no_delete BEFORE DELETE ON site_audit
                    BEGIN SELECT RAISE(ABORT, 'The change record cannot be deleted'); END""")


def record_site(actor, action, target, outcome):
    with auth.accounts() as conn:
        _site_table(conn)
        conn.execute("INSERT INTO site_audit(created_at, actor, action, target, outcome) VALUES(?,?,?,?,?)",
                     (now_iso(), actor, action, (target or "")[:200] or None, outcome))


def site_events(limit=300):
    with auth.accounts() as conn:
        _site_table(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM site_audit ORDER BY id DESC LIMIT ?", (limit,))]
