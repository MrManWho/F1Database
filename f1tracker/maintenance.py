"""Maintenance mode (v3.2): close the site to everyone except the site owner, for upgrades such as 4.0.

Active when either
  * the site owner turns it on (Account -> System controls; stored in accounts.db settings: maintenance_enabled,
    maintenance_message, maintenance_expected_end, maintenance_pause_deliveries, maintenance_enabled_at,
    maintenance_enabled_by), or
  * the host sets the environment variable FORCE_MAINTENANCE=true (an emergency switch that the website itself
    can't turn off: remove the variable in Render to end it).

While active, a request middleware (app.guard, before any route runs) lets only the real, signed-in site owner
through, judged from the account in the database, never from an address, cookie, query parameter or link. Everyone
else, including Race Masters, Scorekeepers, Drivers, Spectators, visitors and sessions that were already signed in,
gets the maintenance page (HTTP 503, Retry-After, no caching) or, for the JSON API, a structured 503. Only sign-in,
sign-out, static files, the service worker, the maintenance page and the health check stay reachable.

"Pause outgoing deliveries" stops every email, phone alert and Discord post: queued messages stay in the durable
outbox and are sent, once each, when the pause is lifted.
"""

import os
from datetime import datetime, timezone

from . import auth
from .storage import now_iso

KEYS = ("maintenance_enabled", "maintenance_message", "maintenance_expected_end", "maintenance_pause_deliveries",
        "maintenance_enabled_at", "maintenance_enabled_by")
DEFAULT_MESSAGE = "We're making some improvements. Your leagues, results and careers are safe and will be back shortly."
CONFIRM_WORD = "MAINTENANCE"
DEFAULT_RETRY = 600          # seconds, when no reopening time is set
MAX_MESSAGE = 500

# Reachable by anyone during maintenance (endpoints). Everything else needs the site owner.
OPEN_ENDPOINTS = {"static", "login", "login_code", "logout", "maintenance_page", "healthz", "service_worker"}


def forced():
    """The host's emergency switch (FORCE_MAINTENANCE=true in Render). Can't be changed from the website."""
    return (os.environ.get("FORCE_MAINTENANCE") or "").strip().lower() in ("1", "true", "yes", "on")


def settings():
    with auth.accounts() as conn:
        rows = {r["key"]: r["value"] for r in conn.execute(
            f"SELECT key, value FROM settings WHERE key IN ({','.join('?' * len(KEYS))})", KEYS)}
    return {
        "enabled": rows.get("maintenance_enabled") == "1",
        "message": rows.get("maintenance_message") or "",
        "expected_end": rows.get("maintenance_expected_end") or "",
        "pause_deliveries": rows.get("maintenance_pause_deliveries") == "1",
        "enabled_at": rows.get("maintenance_enabled_at") or "",
        "enabled_by": rows.get("maintenance_enabled_by") or "",
    }


def state():
    s = settings()
    s["forced"] = forced()
    s["active"] = s["enabled"] or s["forced"]
    return s


def active():
    return forced() or settings()["enabled"]


def deliveries_paused():
    try:
        return settings()["pause_deliveries"]
    except Exception:       # never let a settings problem stop the site; deliveries simply carry on
        return False


def site_owner():
    """The site owner's account: the one made with the setup code (users.is_owner). Very old sites without that
    mark fall back to the oldest site Race Master, so the real owner can never be locked out."""
    owner = auth.owner()
    if owner:
        return owner
    with auth.accounts() as conn:
        row = conn.execute("SELECT * FROM users WHERE is_master = 1 ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def is_owner(user):
    if not user:
        return False
    owner = site_owner()
    return bool(owner) and owner["username"] == user["username"]


def allowed(user, endpoint):
    """May this request go through while maintenance is active?"""
    return endpoint in OPEN_ENDPOINTS or is_owner(user)


# --------------------------------------------------------------------------- the owner's controls

def parse_expected(value, tz_offset_minutes=0):
    """A datetime-local value from the browser (plus its UTC offset) -> UTC ISO text, or "" when blank."""
    value = (value or "").strip()
    if not value:
        return ""
    from datetime import timedelta
    try:
        local = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("The expected reopening time isn't a valid date and time") from exc
    try:
        offset = int(tz_offset_minutes or 0)
    except (TypeError, ValueError):
        offset = 0
    return (local + timedelta(minutes=offset)).replace(tzinfo=timezone.utc).isoformat(timespec="minutes")


def _save(conn, key, value):
    conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))


def update(actor, *, enabled=None, message=None, expected_end=None, pause=None):
    """Change the settings; returns what changed (for the record). Turning it on needs the caller to have checked
    the typed confirmation."""
    before = settings()
    changes = []
    with auth.accounts() as conn:
        if message is not None:
            message = message.strip()[:MAX_MESSAGE]
            if message != before["message"]:
                _save(conn, "maintenance_message", message)
                changes.append("message")
        if expected_end is not None and expected_end != before["expected_end"]:
            _save(conn, "maintenance_expected_end", expected_end)
            changes.append("expected reopening " + (expected_end or "cleared"))
        if pause is not None and pause != before["pause_deliveries"]:
            _save(conn, "maintenance_pause_deliveries", "1" if pause else "0")
            changes.append("deliveries " + ("paused" if pause else "resumed"))
        if enabled is not None and enabled != before["enabled"]:
            _save(conn, "maintenance_enabled", "1" if enabled else "0")
            if enabled:
                _save(conn, "maintenance_enabled_at", now_iso())
                _save(conn, "maintenance_enabled_by", actor)
            changes.append("maintenance " + ("on" if enabled else "off"))
    if changes:
        record(actor, "maintenance_on" if enabled else "maintenance_off" if enabled is False else "maintenance_edit",
               "; ".join(changes))
    return changes


def retry_after(expected_end=None):
    """Seconds until the expected reopening (at least a minute), or DEFAULT_RETRY."""
    if expected_end:
        try:
            end = datetime.fromisoformat(expected_end)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            return max(60, int((end - datetime.now(timezone.utc)).total_seconds()))
        except ValueError:
            pass
    return DEFAULT_RETRY


# --------------------------------------------------------------------------- the record (site change record)
# Same table and rules as the 4.0 site change record (append-only), so 4.0 simply carries it on.

def _record_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS site_audit (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
        target TEXT, outcome TEXT)""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS site_audit_no_update BEFORE UPDATE ON site_audit
                    BEGIN SELECT RAISE(ABORT, 'The change record cannot be edited'); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS site_audit_no_delete BEFORE DELETE ON site_audit
                    BEGIN SELECT RAISE(ABORT, 'The change record cannot be deleted'); END""")


def record(actor, action, detail):
    with auth.accounts() as conn:
        _record_table(conn)
        conn.execute("INSERT INTO site_audit(created_at, actor, action, target, outcome) VALUES(?,?,?,?,?)",
                     (now_iso(), actor, action, detail[:200], "done"))


def history(limit=30):
    with auth.accounts() as conn:
        _record_table(conn)
        return [dict(r) for r in conn.execute("""SELECT * FROM site_audit WHERE action LIKE 'maintenance%'
                                                 ORDER BY id DESC LIMIT ?""", (limit,))]
