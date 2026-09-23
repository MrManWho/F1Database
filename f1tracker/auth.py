"""Local user accounts shared by every career on this machine.

Accounts live in accounts.db next to the careers folder. A Race Master can enter results and run
the career; player accounts are linked to a player driver inside each career and see their own
garage and offers.
"""

import re
import secrets
import sqlite3
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

from .storage import data_dir, now_iso

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
