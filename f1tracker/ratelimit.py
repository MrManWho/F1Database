"""A small fixed-window rate limiter stored in accounts.db, for public actions (directory searches, join
requests, reports, invitations). Keys never contain secrets: an action name plus an IP address or username."""

import time

from . import auth


def _table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS rate_hits (key TEXT NOT NULL, at REAL NOT NULL)")


def allow(action, who, limit, per_seconds):
    """Record an attempt; False when `who` has already done `action` `limit` times in the window."""
    key = f"{action}:{who}"
    now = time.time()
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("DELETE FROM rate_hits WHERE at < ?", (now - 86400,))
        n = conn.execute("SELECT COUNT(*) FROM rate_hits WHERE key = ? AND at >= ?", (key, now - per_seconds)).fetchone()[0]
        if n >= limit:
            return False
        conn.execute("INSERT INTO rate_hits(key, at) VALUES(?, ?)", (key, now))
    return True
