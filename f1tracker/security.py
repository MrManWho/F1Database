"""Account security: a registry of signed-in sessions (so people can see and end them) and optional two-step
sign-in with an authenticator app (TOTP, RFC 6238). Nothing here stores a password, a raw token or a code;
session ids are random and TOTP secrets never leave the account database."""

import base64
import hashlib
import hmac
import secrets
import struct
import time

from . import auth
from .storage import now_iso

SESSION_IDLE_DAYS = 60


def _tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
        sid TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL,
        agent TEXT NOT NULL DEFAULT '')""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "totp_secret" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")


def _agent(ua):
    ua = ua or ""
    browser = next((b for b in ("Edg", "Firefox", "Chrome", "Safari") if b in ua), "Browser")
    browser = {"Edg": "Edge"}.get(browser, browser)
    system = next((s for s in ("iPhone", "iPad", "Android", "Windows", "Mac OS", "Linux") if s in ua), "")
    return (browser + (f" on {system.replace('Mac OS', 'Mac')}" if system else ""))[:60]


def start_session(username, user_agent=""):
    sid = secrets.token_urlsafe(24)
    with auth.accounts() as conn:
        _tables(conn)
        now = now_iso()
        conn.execute("INSERT INTO user_sessions(sid, username, created_at, last_seen, agent) VALUES(?,?,?,?,?)",
                     (sid, username, now, now, _agent(user_agent)))
    return sid


def check_session(sid, username):
    """True if this session is still signed in (and note that it was just used)."""
    if not sid:
        return False
    with auth.accounts() as conn:
        _tables(conn)
        row = conn.execute("SELECT * FROM user_sessions WHERE sid = ? AND username = ?", (sid, username)).fetchone()
        if not row:
            return False
        now = now_iso()
        if row["last_seen"][:15] != now[:15]:   # ten-minute resolution
            conn.execute("UPDATE user_sessions SET last_seen = ? WHERE sid = ?", (now, sid))
    return True


def sessions(username):
    with auth.accounts() as conn:
        _tables(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM user_sessions WHERE username = ? ORDER BY last_seen DESC",
                                              (username,))]


def end_session(username, sid):
    with auth.accounts() as conn:
        _tables(conn)
        conn.execute("DELETE FROM user_sessions WHERE username = ? AND sid = ?", (username, sid))


def end_other_sessions(username, keep_sid=None):
    with auth.accounts() as conn:
        _tables(conn)
        cur = conn.execute("DELETE FROM user_sessions WHERE username = ? AND sid != ?", (username, keep_sid or ""))
        return cur.rowcount


# --------------------------------------------------------------------------- two-step sign-in (TOTP)

def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def totp_now(secret, at=None):
    return _code(secret, int((at or time.time()) // 30))


def verify_code(secret, code, at=None, window=1):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not secret or len(code) != 6:
        return False
    step = int((at or time.time()) // 30)
    return any(hmac.compare_digest(_code(secret, step + d), code) for d in range(-window, window + 1))


def totp_status(username):
    with auth.accounts() as conn:
        _tables(conn)
        row = conn.execute("SELECT totp_secret, totp_enabled FROM users WHERE username = ?", (username,)).fetchone()
    return {"enabled": bool(row and row["totp_enabled"]), "secret": row["totp_secret"] if row else None}


def begin_totp(username):
    secret = new_secret()
    with auth.accounts() as conn:
        _tables(conn)
        conn.execute("UPDATE users SET totp_secret = ?, totp_enabled = 0 WHERE username = ?", (secret, username))
    return secret


def enable_totp(username, code):
    st = totp_status(username)
    if not st["secret"] or not verify_code(st["secret"], code):
        raise auth.AuthError("That code didn't match. Check the time on your phone and try the newest code.")
    with auth.accounts() as conn:
        conn.execute("UPDATE users SET totp_enabled = 1 WHERE username = ?", (username,))


def disable_totp(username):
    with auth.accounts() as conn:
        _tables(conn)
        conn.execute("UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE username = ?", (username,))


def otpauth_uri(username, secret):
    from urllib.parse import quote
    return f"otpauth://totp/{quote('Paddock Legacy:' + username)}?secret={secret}&issuer={quote('Paddock Legacy')}"
