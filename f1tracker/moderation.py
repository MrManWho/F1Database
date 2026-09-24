"""Moderation foundations for publicly discoverable leagues: reports from anyone, reviewed by site admins, who
can take a league out of the directory. Reports hold the league's name, a reason and optional details, and the
reporter's username only if they were logged in (never an IP address or email)."""

from . import auth
from .storage import now_iso

REASONS = {
    "spam": "Spam or advertising",
    "offensive": "Offensive or abusive content",
    "privacy": "Shares someone's private information",
    "impersonation": "Pretends to be someone else",
    "other": "Something else",
}


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS league_reports (
        id INTEGER PRIMARY KEY, token TEXT NOT NULL, league_name TEXT NOT NULL, reason TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '', reporter TEXT, status TEXT NOT NULL DEFAULT 'Open',
        created_at TEXT NOT NULL, decided_at TEXT)""")


def report(token, league_name, reason, details, reporter=None):
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("INSERT INTO league_reports(token, league_name, reason, details, reporter, created_at) "
                     "VALUES(?,?,?,?,?,?)", (token, league_name[:80], reason, details.strip()[:1000], reporter, now_iso()))


def reports(status="Open"):
    with auth.accounts() as conn:
        _table(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM league_reports WHERE status = ? ORDER BY id DESC", (status,))]


def decide(report_id, status):
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("UPDATE league_reports SET status = ?, decided_at = ? WHERE id = ?", (status, now_iso(), report_id))


def delisted():
    return set(filter(None, (auth.get_setting("delisted_leagues") or "").split(",")))


def set_delisted(token, on):
    tokens = delisted()
    (tokens.add if on else tokens.discard)(token)
    auth.set_setting("delisted_leagues", ",".join(sorted(tokens)) or None)
