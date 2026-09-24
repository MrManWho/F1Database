"""The one-time "What's new" screen after a meaningful update, remembered per account (never per browser only).

A version is shown once to each account that hasn't acknowledged it, if its changelog entry has a Highlights
section. "Got it" and "Don't show this version again" both record the acknowledgement; "Later" only hides it
for this browser session. It can always be reopened from Help or the account menu.
"""

from . import auth
from .storage import now_iso


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS whats_new_seen (
        username TEXT NOT NULL, version TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY (username, version))""")


def acknowledged(username, version):
    with auth.accounts() as conn:
        _table(conn)
        return bool(conn.execute("SELECT 1 FROM whats_new_seen WHERE username = ? AND version = ?",
                                 (username, version)).fetchone())


def acknowledge(username, version):
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("INSERT OR IGNORE INTO whats_new_seen(username, version, seen_at) VALUES(?,?,?)",
                     (username, version, now_iso()))
