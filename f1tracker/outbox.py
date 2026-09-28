"""A small durable outbox for emails, Discord posts and phone alerts (v3.1.2).

Sending happens in the background so a request never waits on a mail server. Before 3.1.2 a message that was still
being sent when the server restarted (every deploy restarts it) was simply lost. Now each message is written to
accounts.db first, sent in the background, and deleted as soon as it's sent. Anything left over (a restart, or a
mail server that was briefly down) is sent again when the site starts and then about once a minute, up to
MAX_ATTEMPTS times with a growing wait.

Rows hold what's needed to send (addresses, text, a Discord webhook URL) only until it's sent or given up, and the
site never shows or exports them. Nothing is kept afterwards: the league delivery logs keep counts, never content.
"""

import json
import logging
import threading
import time

from . import auth

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
STALE_CLAIM = 120          # seconds: a claim older than this was lost with its process, so it's retried
_last_kick = [0.0]
_lock = threading.Lock()


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL, next_at REAL NOT NULL, claimed_at REAL)""")


def enqueue(kind, payload, background=True):
    """Save a message and start sending it. kind: email / discord / push. Returns the row id."""
    now = time.time()
    with auth.accounts() as conn:
        _table(conn)
        oid = conn.execute("INSERT INTO outbox(kind, payload, created_at, next_at) VALUES(?,?,?,?)",
                           (kind, json.dumps(payload), now, now)).lastrowid
    if background:
        threading.Thread(target=process, args=(oid,), daemon=True).start()
    else:
        process(oid)
    return oid


def _claim(oid):
    now = time.time()
    with auth.accounts() as conn:
        _table(conn)
        cur = conn.execute("""UPDATE outbox SET claimed_at = ? WHERE id = ? AND next_at <= ?
                              AND (claimed_at IS NULL OR claimed_at < ?)""", (now, oid, now, now - STALE_CLAIM))
        if not cur.rowcount:
            return None
        row = conn.execute("SELECT * FROM outbox WHERE id = ?", (oid,)).fetchone()
    return dict(row) if row else None


def _send(kind, p):
    from . import testsite
    if testsite.on():
        return              # the 4.0 test site never sends anything (imported rows are just dropped)
    if kind == "email":
        from . import mailer
        mailer.send(p["to"], p["subject"], p["text"], p.get("html"))
    elif kind == "discord":
        from . import discord
        if not discord.post(p["url"], p["message"]):
            raise RuntimeError("Discord refused the post")
    elif kind == "push":
        from . import push
        push.send(p["names"], p["title"], p["body"], p.get("url"))
    else:
        raise ValueError(f"unknown outbox kind {kind}")


def process(oid):
    """Send one message; delete it when sent, or schedule a retry (dropped after MAX_ATTEMPTS)."""
    row = _claim(oid)
    if not row:
        return False
    try:
        _send(row["kind"], json.loads(row["payload"]))
    except Exception as exc:          # a mail server or Discord hiccup: try again later
        attempts = row["attempts"] + 1
        with auth.accounts() as conn:
            if attempts >= MAX_ATTEMPTS:
                conn.execute("DELETE FROM outbox WHERE id = ?", (oid,))
                log.warning("%s gave up after %d attempts: %s", row["kind"], attempts, exc)
            else:
                conn.execute("UPDATE outbox SET attempts = ?, next_at = ?, claimed_at = NULL WHERE id = ?",
                             (attempts, time.time() + 60 * 2 ** attempts, oid))
                log.info("%s failed (attempt %d), will retry: %s", row["kind"], attempts, exc)
        return False
    with auth.accounts() as conn:
        conn.execute("DELETE FROM outbox WHERE id = ?", (oid,))
    return True


def pending():
    with auth.accounts() as conn:
        _table(conn)
        return conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]


def drain(background=True):
    """Send everything that's due (left over from a restart, or waiting for a retry)."""
    now = time.time()
    with auth.accounts() as conn:
        _table(conn)
        ids = [r[0] for r in conn.execute("""SELECT id FROM outbox WHERE next_at <= ?
                                             AND (claimed_at IS NULL OR claimed_at < ?) ORDER BY id""",
                                          (now, now - STALE_CLAIM))]
    if not ids:
        return 0

    def run():
        for oid in ids:
            process(oid)
    if background:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    return len(ids)


def kick(every=60):
    """Called on requests: drain at most once a minute (cheap when there's nothing waiting)."""
    now = time.time()
    with _lock:
        if now - _last_kick[0] < every:
            return 0
        _last_kick[0] = now
    try:
        return drain()
    except Exception:
        log.exception("outbox drain failed")
        return 0
