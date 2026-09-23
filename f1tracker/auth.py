"""Local user accounts shared by every career on this machine.

Accounts live in accounts.db next to the careers folder. A Race Master can enter results and run
the career; player accounts are linked to a player driver inside each career and see their own
garage and offers.
"""

import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

from .constants import LOGIN_LOCK_MINUTES, LOGIN_MAX_FAILURES
from .storage import data_dir, now_iso

IP_MAX_FAILURES = 20          # a single address guessing across many usernames
SIGNUPS_PER_IP_PER_HOUR = 5

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{2,32}$")


class AuthError(ValueError):
    pass


@contextmanager
def accounts():
    conn = sqlite3.connect(str(data_dir() / "accounts.db"), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_master INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS login_failures (
        key TEXT PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 0,
        first_at REAL NOT NULL,
        locked_until REAL NOT NULL DEFAULT 0)""")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def secret_key():
    path = data_dir() / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


def normalise(username):
    return (username or "").strip().lower()


def user_count():
    with accounts() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users():
    with accounts() as conn:
        return [dict(r) for r in conn.execute("SELECT id, username, display_name, is_master, created_at "
                                              "FROM users ORDER BY is_master DESC, username")]


def get_user(username):
    with accounts() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (normalise(username),)).fetchone()
        return dict(row) if row else None


def create_user(username, display_name, password, is_master=False):
    username = normalise(username)
    if not USERNAME_RE.match(username):
        raise AuthError("Usernames are 2-32 characters: letters, numbers, dot, dash or underscore")
    if len(password or "") < 6:
        raise AuthError("Passwords need at least 6 characters")
    display_name = (display_name or "").strip()[:60] or username
    with accounts() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AuthError("That username is taken")
        conn.execute("INSERT INTO users(username, display_name, password_hash, is_master, created_at) "
                     "VALUES(?,?,?,?,?)", (username, display_name, generate_password_hash(password),
                                           int(bool(is_master)), now_iso()))
    return username


def verify(username, password):
    user = get_user(username)
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


def set_password(username, password):
    if len(password or "") < 6:
        raise AuthError("Passwords need at least 6 characters")
    with accounts() as conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                           (generate_password_hash(password), normalise(username)))
        if not cur.rowcount:
            raise AuthError("Unknown user")


def set_master(username, is_master):
    with accounts() as conn:
        if not is_master:
            masters = conn.execute("SELECT COUNT(*) FROM users WHERE is_master = 1 AND username != ?",
                                   (normalise(username),)).fetchone()[0]
            if masters == 0:
                raise AuthError("At least one Race Master account is required")
        conn.execute("UPDATE users SET is_master = ? WHERE username = ?", (int(bool(is_master)), normalise(username)))


def delete_user(username):
    with accounts() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (normalise(username),)).fetchone()
        if not user:
            raise AuthError("Unknown user")
        if user["is_master"] and conn.execute("SELECT COUNT(*) FROM users WHERE is_master = 1").fetchone()[0] <= 1:
            raise AuthError("You cannot delete the last Race Master")
        conn.execute("DELETE FROM users WHERE username = ?", (normalise(username),))


# --------------------------------------------------------------------------- settings

def get_setting(key, default=None):
    with accounts() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with accounts() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (key, str(value)))


def signups_allowed():
    return get_setting("allow_signups", "1") == "1"


# --------------------------------------------------------------------------- login protection

def _keys(username, ip):
    return [f"user:{normalise(username)}", f"ip:{ip or '?'}"]


def lock_remaining(username, ip):
    """Seconds until this username or address may try again (0 = not locked)."""
    now = time.time()
    with accounts() as conn:
        rows = conn.execute("SELECT locked_until FROM login_failures WHERE key IN (?, ?)", _keys(username, ip)).fetchall()
    return max([int(r["locked_until"] - now) for r in rows if r["locked_until"] > now] + [0])


def record_failure(username, ip):
    now = time.time()
    window = LOGIN_LOCK_MINUTES * 60
    with accounts() as conn:
        for key, limit in zip(_keys(username, ip), (LOGIN_MAX_FAILURES, IP_MAX_FAILURES)):
            row = conn.execute("SELECT * FROM login_failures WHERE key = ?", (key,)).fetchone()
            if not row or now - row["first_at"] > window:
                count, first = 1, now
            else:
                count, first = row["count"] + 1, row["first_at"]
            locked = now + window if count >= limit else 0
            conn.execute("""INSERT INTO login_failures(key, count, first_at, locked_until) VALUES(?,?,?,?)
                            ON CONFLICT(key) DO UPDATE SET count=excluded.count, first_at=excluded.first_at,
                            locked_until=excluded.locked_until""", (key, count, first, locked))


def clear_failures(username, ip):
    with accounts() as conn:
        conn.execute("DELETE FROM login_failures WHERE key = ?", (_keys(username, ip)[0],))


def login(username, password, ip):
    """Verify a login with lockout. Returns the user, or raises AuthError with a friendly reason."""
    remaining = lock_remaining(username, ip)
    if remaining:
        raise AuthError(f"Too many wrong passwords. Try again in {max(1, remaining // 60 + 1)} minute(s).")
    user = verify(username, password)
    if not user:
        record_failure(username, ip)
        raise AuthError("Wrong username or password.")
    clear_failures(username, ip)
    return user


def register(username, display_name, password, ip):
    """Self sign-up. New accounts are Drivers and see nothing until a Race Master links them."""
    if not signups_allowed():
        raise AuthError("Sign-ups are turned off. Ask the Race Master to create your login.")
    key = f"signup:{ip or '?'}"
    now = time.time()
    with accounts() as conn:
        row = conn.execute("SELECT * FROM login_failures WHERE key = ?", (key,)).fetchone()
        count = row["count"] if row and now - row["first_at"] < 3600 else 0
        if count >= SIGNUPS_PER_IP_PER_HOUR:
            raise AuthError("Too many sign-ups from this connection. Try again later.")
    name = create_user(username, display_name, password, is_master=False)
    with accounts() as conn:
        first = row["first_at"] if row and count else now
        conn.execute("""INSERT INTO login_failures(key, count, first_at, locked_until) VALUES(?,?,?,0)
                        ON CONFLICT(key) DO UPDATE SET count=excluded.count, first_at=excluded.first_at""",
                     (key, count + 1, first))
    return name
