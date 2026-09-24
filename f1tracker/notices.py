"""Per-league notification preferences and delivery (email and phone alerts).

Every league keeps its own preferences for each member (league DB table member_notify), so being in two
leagues never means one league's settings decide what the other sends. A member can mute a league (no email
or phone alerts from it; they stay in the league and still see in-app notifications) or choose per category.
Accounts can also pause every email from every league (users.email_paused), which is separate from a single
league's choices.

Every delivery goes through deliver(): it is deduplicated with a key (a retried save or a second background
job can't send the same thing twice), rate-limited per league, and logged in the league's delivery log with
the category, channel, how many people it reached and the outcome, never the message itself or addresses.

Memberships that existed before v2.0 are marked legacy by the migration: the first time their preferences are
read they get what they had before (race-result emails if their account had them on; phone alerts on) and are
then stored like everyone else's. New memberships never inherit anything from another league or the account.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta

from . import auth
from .storage import get_meta, now_iso

log = logging.getLogger(__name__)

# key: (label, description, audience) where audience is "all" (anyone in the league) or "masters".
CATEGORIES = {
    "schedule": ("Race scheduled or rescheduled", "A race time is set, changed or postponed.", "all"),
    "raceday": ("Race day", "The paddock opens and the lights go out for a round.", "all"),
    "results": ("Results submitted", "A round's results go in (the full results email).", "all"),
    "market": ("Market opened or closing", "Transfer windows opening and closing.", "all"),
    "contracts": ("Contracts and seats", "Offers for your driver, signings and seat changes.", "all"),
    "career": ("Your driver", "Press questions, weekend targets, team messages, pledges and rulings about you.", "all"),
    "announcements": ("Announcements and mentions", "Race Master announcements and comments on the league.", "all"),
    "roles": ("Your role or permissions", "When your role or driver in this league changes.", "all"),
    "season": ("Season started or completed", "The end of a season and the start of the next.", "all"),
    "join_requests": ("Join requests", "Someone asks to join or accepts an invitation (Race Masters only).", "masters"),
    "admin": ("Administrative alerts", "Incident reports and things that need a Race Master (Race Masters only).", "masters"),
}
CHANNELS = ("email", "push")

# Presets offered when creating or joining a league. "important" is the default: nothing noisy by email.
PRESETS = {
    "all": ("Everything", "Email and phone alerts for everything in this league."),
    "important": ("Important only", "Email for your role, contracts, announcements and seasons; phone alerts for the rest."),
    "inapp": ("In-app only (muted)", "No emails or phone alerts from this league. You'll still see them here."),
}
IMPORTANT_EMAIL = {"contracts", "announcements", "roles", "season", "join_requests", "admin"}

EMAILS_PER_LEAGUE_PER_HOUR = 60     # beyond this a league's emails are held back and logged (loop protection)
SAME_CATEGORY_PER_10_MIN = 12       # the same kind of message more often than this is almost certainly a loop


def preset_prefs(name):
    name = name if name in PRESETS else "important"
    if name == "all":
        return {"muted": False, "email": {k: True for k in CATEGORIES}, "push": {k: True for k in CATEGORIES}}
    if name == "inapp":
        return {"muted": True, "email": {k: False for k in CATEGORIES}, "push": {k: False for k in CATEGORIES}}
    return {"muted": False, "email": {k: k in IMPORTANT_EMAIL for k in CATEGORIES},
            "push": {k: True for k in CATEGORIES}}


def _row(conn, username):
    return conn.execute("SELECT * FROM member_notify WHERE username = ?", (username,)).fetchone()


def _store(conn, username, prefs, legacy=0):
    conn.execute("""INSERT INTO member_notify(username, muted, email, push, legacy, updated_at) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(username) DO UPDATE SET muted = excluded.muted, email = excluded.email,
                    push = excluded.push, legacy = excluded.legacy, updated_at = excluded.updated_at""",
                 (username, int(bool(prefs["muted"])), json.dumps(prefs["email"]), json.dumps(prefs["push"]),
                  legacy, now_iso()))


def prefs(conn, username):
    """This member's preferences in this league (resolving a pre-2.0 membership the first time)."""
    row = _row(conn, username)
    if row and not row["legacy"] and row["email"] is not None:
        email, push = json.loads(row["email"]), json.loads(row["push"] or "{}")
        return {"muted": bool(row["muted"]), "email": {k: bool(email.get(k, False)) for k in CATEGORIES},
                "push": {k: bool(push.get(k, True)) for k in CATEGORIES}, "stored": True}
    out = preset_prefs("important")
    if row and row["legacy"]:
        # Before 2.0 the only league email was race results, controlled by one account-wide switch, and phone
        # alerts went out for everything. Keep exactly that for memberships that already existed.
        user = auth.get_user(username)
        out["email"] = {k: False for k in CATEGORIES}
        out["email"]["results"] = bool(user and user.get("email_results"))
        out["push"] = {k: True for k in CATEGORIES}
        _store(conn, username, out)
        out["stored"] = True
        return out
    out["stored"] = False
    return out


def save(conn, username, muted=None, email=None, push=None, preset=None):
    """Save a member's preferences (whole categories, or a preset)."""
    cur = preset_prefs(preset) if preset else prefs(conn, username)
    if muted is not None:
        cur["muted"] = bool(muted)
    if email is not None:
        cur["email"] = {k: k in email for k in CATEGORIES}
    if push is not None:
        cur["push"] = {k: k in push for k in CATEGORIES}
    _store(conn, username, cur)
    return cur


def ensure_member(conn, username, preset="important"):
    """A new membership gets its own preferences (never inherited from another league or the account)."""
    if not _row(conn, username):
        _store(conn, username, preset_prefs(preset))


def forget_member(conn, username):
    conn.execute("DELETE FROM member_notify WHERE username = ?", (username,))


def summary(p):
    if p["muted"]:
        return "Muted"
    on = sum(p["email"].values())
    return "Everything" if on == len(CATEGORIES) and all(p["push"].values()) else \
        ("Phone and in-app only" if on == 0 else f"Email for {on} of {len(CATEGORIES)} kinds")


# --------------------------------------------------------------------------- recipients

def _members(conn):
    return [dict(r) for r in conn.execute("SELECT username, driver_id, role FROM career_members")]


def audience(conn, category, driver_id=None, username=None):
    """League members a notification is about: one login, one driver's login, or everyone allowed to see it.
    Site admins who aren't members of this league are never included."""
    rows = _members(conn)
    if username:
        rows = [r for r in rows if r["username"] == username]
    elif driver_id is not None:
        rows = [r for r in rows if r["driver_id"] == driver_id]
    if CATEGORIES.get(category, ("", "", "all"))[2] == "masters":
        site = {u["username"] for u in auth.list_users() if u["is_master"]}
        rows = [r for r in rows if r["role"] == "race_master" or r["username"] in site]
    return [r["username"] for r in rows]


def wanted(conn, usernames, category, channel):
    """The subset of these members who want this category on this channel in this league."""
    out = []
    for name in usernames:
        p = prefs(conn, name)
        if p["muted"] or not p[channel].get(category, False):
            continue
        out.append(name)
    return out


def email_recipients(conn, usernames, category):
    """(username, address) pairs: wants it in this league, has an address, hasn't paused all email."""
    out = []
    for name in wanted(conn, usernames, category, "email"):
        user = auth.get_user(name)
        if user and user.get("email") and not user.get("email_paused"):
            out.append((name, user["email"]))
    return out


# --------------------------------------------------------------------------- delivery log

def dedupe_key(category, *parts):
    raw = "|".join(str(p) for p in parts)
    return f"{category}:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


def claim(conn, key, category, channel, label=""):
    """Reserve a delivery. False if this exact delivery was already made (retries, duplicate jobs) or the
    league is sending suspiciously often (loop protection), which is logged instead of sent."""
    if conn.execute("SELECT 1 FROM deliveries WHERE key = ? AND channel = ?", (key, channel)).fetchone():
        return False
    now = datetime.fromisoformat(now_iso())
    hour = (now - timedelta(hours=1)).isoformat(sep=" ")
    ten = (now - timedelta(minutes=10)).isoformat(sep=" ")
    status = "queued"
    if channel == "email":
        sent = conn.execute("SELECT COUNT(*) FROM deliveries WHERE channel = 'email' AND status != 'held' "
                            "AND created_at >= ?", (hour,)).fetchone()[0]
        same = conn.execute("SELECT COUNT(*) FROM deliveries WHERE channel = 'email' AND category = ? AND status != 'held' "
                            "AND created_at >= ?", (category, ten)).fetchone()[0]
        if sent >= EMAILS_PER_LEAGUE_PER_HOUR or same >= SAME_CATEGORY_PER_10_MIN:
            status = "held"
    conn.execute("INSERT INTO deliveries(key, category, channel, label, recipients, status, created_at) "
                 "VALUES(?,?,?,?,0,?,?)", (key, category, channel, label[:120], status, now_iso()))
    return status == "queued"


def record(conn, key, channel, recipients, status):
    conn.execute("UPDATE deliveries SET recipients = ?, status = ? WHERE key = ? AND channel = ?",
                 (recipients, status, key, channel))


def delivery_log(conn, limit=200):
    return [dict(r) for r in conn.execute("SELECT * FROM deliveries ORDER BY id DESC LIMIT ?", (limit,))]


def league_name(conn):
    return get_meta(conn, "career_name", "League")
