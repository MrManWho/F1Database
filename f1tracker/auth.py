"""Local user accounts shared by every career on this machine.

Accounts live in accounts.db next to the careers folder. A Race Master can enter results and run
the career; player accounts are linked to a player driver inside each career and see their own
garage and offers.
"""

import hashlib
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

from .constants import APP_VERSION, LOGIN_LOCK_MINUTES, LOGIN_MAX_FAILURES
from .storage import data_dir, now_iso

IP_MAX_FAILURES = 20          # a single address guessing across many usernames
SIGNUPS_PER_IP_PER_HOUR = 5

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{2,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_MINUTES = 60
RESET_REQUESTS_PER_IP_PER_HOUR = 5


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
    columns = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "is_steward" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_steward INTEGER NOT NULL DEFAULT 0")
    if "email" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "email_results" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email_results INTEGER NOT NULL DEFAULT 1")
    if "is_demo" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")   # v2.0: temporary demo guests
    if "is_owner" not in columns:
        # v2.1.2: the one site owner (made with the host's setup code); everyone else signs up themselves.
        conn.execute("ALTER TABLE users ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")
    if "email_paused" not in columns:
        # v2.0: one switch to stop every email from every league (league choices are kept separately).
        conn.execute("ALTER TABLE users ADD COLUMN email_paused INTEGER NOT NULL DEFAULT 0")
    # v1.19: screenshot import no longer uses a paid AI service, so a previously saved API key is removed.
    conn.execute("DELETE FROM settings WHERE key = 'anthropic_api_key'")
    # v1.18: race-result emails need an address; switch the option off where there's none to send to.
    conn.execute("UPDATE users SET email_results = 0 WHERE email_results = 1 AND (email IS NULL OR trim(email) = '')")
    conn.execute("""CREATE TABLE IF NOT EXISTS pending_signups (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        expires_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        sent_at REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS reserved_usernames (
        username TEXT PRIMARY KEY, email_hash TEXT, reserved_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS password_resets (
        token_hash TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at REAL NOT NULL,
        used INTEGER NOT NULL DEFAULT 0)""")
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
        users = [dict(r) for r in conn.execute("SELECT id, username, display_name, is_master, is_steward, email, "
                                               "email_results, created_at "
                                               "FROM users WHERE is_demo = 0 ORDER BY is_master DESC, is_steward DESC, username")]
    for u in users:
        u["role"] = role_of(u)
    return users


ROLES = {
    "master": "Race Master",     # full admin: logins, saves, every garage and negotiation
    "steward": "Scorekeeper",    # legacy (pre-v1.16): migrated into each league's member role, then cleared
    "driver": "Member",          # league access (driver / Scorekeeper / spectator) is set per league
}


def role_of(user):
    if not user:
        return None
    if user["is_master"]:
        return "master"
    return "steward" if user.get("is_steward") else "driver"


def set_role(username, role):
    if role == "steward":
        raise AuthError("Scorekeeper access is set per league now: open the league's Members & roles page")
    if role not in ROLES:
        raise AuthError("Unknown role")
    with accounts() as conn:
        if role != "master":
            masters = conn.execute("SELECT COUNT(*) FROM users WHERE is_master = 1 AND username != ?",
                                   (normalise(username),)).fetchone()[0]
            if masters == 0:
                raise AuthError("At least one Race Master account is required")
        cur = conn.execute("UPDATE users SET is_master = ?, is_steward = ? WHERE username = ?",
                           (int(role == "master"), int(role == "steward"), normalise(username)))
        if not cur.rowcount:
            raise AuthError("Unknown user")


def get_user(username):
    with accounts() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (normalise(username),)).fetchone()
        return dict(row) if row else None


def clean_email(email, required=False):
    email = (email or "").strip().lower()
    if not email:
        if required:
            raise AuthError("Enter an email address")
        return None
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AuthError("That email address doesn't look right")
    return email


def _whats_new_seen(conn, username):
    """A new account has nothing to catch up on: the current version's What's New counts as seen (they get the
    welcome and onboarding instead). Accounts that existed before an update still see it once."""
    conn.execute("""CREATE TABLE IF NOT EXISTS whats_new_seen (
        username TEXT NOT NULL, version TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY (username, version))""")
    conn.execute("INSERT OR IGNORE INTO whats_new_seen(username, version, seen_at) VALUES(?,?,?)",
                 (username, APP_VERSION, now_iso()))


def create_user(username, display_name, password, is_master=False, is_steward=False, email=None):
    username = normalise(username)
    email = clean_email(email)
    if not USERNAME_RE.match(username):
        raise AuthError("Usernames are 2-32 characters: letters, numbers, dot, dash or underscore")
    if len(password or "") < PASSWORD_MIN:
        raise AuthError(f"Passwords need at least {PASSWORD_MIN} characters")
    display_name = (display_name or "").strip()[:60] or username
    with accounts() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AuthError("That username is taken")
        conn.execute("INSERT INTO users(username, display_name, password_hash, is_master, is_steward, email, created_at) "
                     "VALUES(?,?,?,?,?,?,?)", (username, display_name, generate_password_hash(password),
                                               int(bool(is_master)), int(bool(is_steward) and not is_master), email,
                                               now_iso()))
        _whats_new_seen(conn, username)
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


def delete_user(username, reserve=False):
    """reserve=True keeps the username for its owner (its league memberships are still there)."""
    with accounts() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (normalise(username),)).fetchone()
        if not user:
            raise AuthError("Unknown user")
        if user["is_master"] and conn.execute("SELECT COUNT(*) FROM users WHERE is_master = 1").fetchone()[0] <= 1:
            raise AuthError("You cannot delete the last Race Master")
        conn.execute("DELETE FROM users WHERE username = ?", (normalise(username),))
        if reserve:
            conn.execute("INSERT OR REPLACE INTO reserved_usernames(username, email_hash, reserved_at) VALUES(?,?,?)",
                         (user["username"], _email_hash(user["email"]), now_iso()))


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


SIGNUP_CODE_MINUTES = 15
SIGNUP_CODE_TRIES = 5
SIGNUP_RESEND_SECONDS = 60


def register(username, display_name, password, ip, email=None):
    """Step 1 of self sign-up: check the details and hold them until the emailed code comes back.

    Returns (pending_id, code). Nothing is created until finish_signup() gets the right code.
    New accounts are Drivers and see nothing until a Race Master links them.
    """
    if not signups_allowed():
        raise AuthError("Sign-ups are turned off on this site right now.")
    username = normalise(username)
    if not USERNAME_RE.match(username):
        raise AuthError("Usernames are 2-32 characters: letters, numbers, dot, dash or underscore")
    if len(password or "") < 6:
        raise AuthError("Passwords need at least 6 characters")
    email = clean_email(email, required=True)
    display_name = (display_name or "").strip()[:60] or username
    key, now = f"signup:{ip or '?'}", time.time()
    with accounts() as conn:
        row = conn.execute("SELECT * FROM login_failures WHERE key = ?", (key,)).fetchone()
        count = row["count"] if row and now - row["first_at"] < 3600 else 0
        if count >= SIGNUPS_PER_IP_PER_HOUR:
            raise AuthError("Too many sign-ups from this connection. Try again later.")
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AuthError("That username is taken")
        r = conn.execute("SELECT email_hash FROM reserved_usernames WHERE username = ?", (username,)).fetchone()
        if r and (not r["email_hash"] or _email_hash(email) != r["email_hash"]):
            raise AuthError("That username belonged to someone before the site was reset. If it was yours, sign up "
                            "with the same email you used then, or ask the site owner to release it.")
        conn.execute("DELETE FROM pending_signups WHERE expires_at < ? OR username = ?", (now, username))
        code = f"{secrets.randbelow(10 ** 6):06d}"
        pending_id = conn.execute(
            """INSERT INTO pending_signups(username, display_name, password_hash, email, code_hash, expires_at,
               attempts, sent_at) VALUES(?,?,?,?,?,?,0,?)""",
            (username, display_name, generate_password_hash(password), email, _hash(code),
             now + SIGNUP_CODE_MINUTES * 60, now)).lastrowid
        first = row["first_at"] if row and count else now
        conn.execute("""INSERT INTO login_failures(key, count, first_at, locked_until) VALUES(?,?,?,0)
                        ON CONFLICT(key) DO UPDATE SET count=excluded.count, first_at=excluded.first_at""",
                     (key, count + 1, first))
    return pending_id, code


def pending_signup(pending_id):
    with accounts() as conn:
        row = conn.execute("SELECT * FROM pending_signups WHERE id = ?", (pending_id or 0,)).fetchone()
    return dict(row) if row and row["expires_at"] > time.time() else None


def resend_signup_code(pending_id):
    """A fresh code for the same sign-up (at most once a minute). Returns (email, code)."""
    pending = pending_signup(pending_id)
    if not pending:
        raise AuthError("That sign-up has expired. Please fill in the form again.")
    if time.time() - pending["sent_at"] < SIGNUP_RESEND_SECONDS:
        raise AuthError("A code was sent less than a minute ago. Check your inbox and spam folder.")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    with accounts() as conn:
        conn.execute("UPDATE pending_signups SET code_hash = ?, attempts = 0, sent_at = ?, expires_at = ? WHERE id = ?",
                     (_hash(code), time.time(), time.time() + SIGNUP_CODE_MINUTES * 60, pending_id))
    return pending["email"], code


def finish_signup(pending_id, code):
    """Step 2: the right code creates the account. Wrong codes are limited."""
    pending = pending_signup(pending_id)
    if not pending:
        raise AuthError("That sign-up has expired. Please fill in the form again.")
    if pending["attempts"] >= SIGNUP_CODE_TRIES:
        raise AuthError("Too many wrong codes. Ask for a new code.")
    if not secrets.compare_digest(_hash((code or "").strip().replace(" ", "")), pending["code_hash"]):
        with accounts() as conn:
            conn.execute("UPDATE pending_signups SET attempts = attempts + 1 WHERE id = ?", (pending_id,))
        left = SIGNUP_CODE_TRIES - pending["attempts"] - 1
        raise AuthError(f"That code isn't right. {left} tr{'y' if left == 1 else 'ies'} left."
                        if left else "Too many wrong codes. Ask for a new code.")
    with accounts() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (pending["username"],)).fetchone():
            raise AuthError("That username was taken in the meantime. Please sign up again.")
        conn.execute("""INSERT INTO users(username, display_name, password_hash, is_master, is_steward, email, created_at)
                        VALUES(?,?,?,0,0,?,?)""", (pending["username"], pending["display_name"],
                                                   pending["password_hash"], pending["email"], now_iso()))
        # A verified email that matches a reserved (pre-reset) username: it's theirs again.
        conn.execute("DELETE FROM reserved_usernames WHERE username = ?", (pending["username"],))
        conn.execute("DELETE FROM pending_signups WHERE id = ?", (pending_id,))
        _whats_new_seen(conn, pending["username"])
    return pending["username"]


# --------------------------------------------------------------------------- email & password resets

def set_email_paused(username, paused):
    """Pause (or resume) every email from every league for this account. League choices are kept."""
    with accounts() as conn:
        conn.execute("UPDATE users SET email_paused = ? WHERE username = ?", (int(bool(paused)), normalise(username)))


def set_email(username, email, email_results):
    """Save an address (validated) and the race-results preference, which is only possible with an address."""
    email = clean_email(email)
    with accounts() as conn:
        conn.execute("UPDATE users SET email = ?, email_results = ? WHERE username = ?",
                     (email, int(bool(email_results) and bool(email)), normalise(username)))
    return email


PASSWORD_MIN = 6


def change_password(username, current, new, confirm):
    """Change your own password: the current one is required and the new one must be typed twice."""
    if not verify(username, current):
        raise AuthError("Your current password is wrong")
    if (new or "") != (confirm or ""):
        raise AuthError("The new passwords don't match")
    if new == current:
        raise AuthError("Choose a password that's different from the current one")
    set_password(username, new)


def users_by_login(identifier):
    """Accounts matching a username or an email address (several accounts may share an email)."""
    ident = (identifier or "").strip().lower()
    with accounts() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM users WHERE (username = ? OR lower(email) = ?) AND email IS NOT NULL AND email != ''",
            (ident, ident))]


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def reset_request_allowed(ip):
    key, now = f"reset:{ip or '?'}", time.time()
    with accounts() as conn:
        row = conn.execute("SELECT * FROM login_failures WHERE key = ?", (key,)).fetchone()
        count = row["count"] if row and now - row["first_at"] < 3600 else 0
        if count >= RESET_REQUESTS_PER_IP_PER_HOUR:
            return False
        first = row["first_at"] if row and count else now
        conn.execute("""INSERT INTO login_failures(key, count, first_at, locked_until) VALUES(?,?,?,0)
                        ON CONFLICT(key) DO UPDATE SET count=excluded.count, first_at=excluded.first_at""",
                     (key, count + 1, first))
    return True


def create_reset_token(username):
    token = secrets.token_urlsafe(32)
    with accounts() as conn:
        conn.execute("DELETE FROM password_resets WHERE username = ? OR expires_at < ?", (normalise(username), time.time()))
        conn.execute("INSERT INTO password_resets(token_hash, username, expires_at) VALUES(?,?,?)",
                     (_hash(token), normalise(username), time.time() + RESET_MINUTES * 60))
    return token


def reset_token_user(token):
    with accounts() as conn:
        row = conn.execute("SELECT * FROM password_resets WHERE token_hash = ?", (_hash(token or ""),)).fetchone()
    if not row or row["used"] or row["expires_at"] < time.time():
        return None
    return row["username"]


def use_reset_token(token, password):
    username = reset_token_user(token)
    if not username:
        raise AuthError("That reset link has expired or was already used. Ask for a new one.")
    set_password(username, password)
    with accounts() as conn:
        conn.execute("UPDATE password_resets SET used = 1 WHERE token_hash = ?", (_hash(token),))
        conn.execute("DELETE FROM login_failures WHERE key = ?", (f"user:{username}",))
    return username


# --------------------------------------------------------------------------- v2.1.2: owner model and account reset

# Account tables in accounts.db. League files are never touched here.
ACCOUNT_TABLES = ["users", "user_sessions", "pending_signups", "password_resets", "login_failures", "whats_new_seen",
                  "user_leagues", "league_creations", "rate_hits", "push_subscriptions"]


def owner():
    with accounts() as conn:
        row = conn.execute("SELECT * FROM users WHERE is_owner = 1 ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def _email_hash(email):
    email = (email or "").strip().lower()
    return _hash("email:" + email) if email else None


def reset_all_accounts(backup_dir):
    """v2.1.2, once per site: delete every login so the site starts again with an owner made from the host's setup
    code and people signing up themselves. League files (leagues, drivers, results, memberships) are untouched.
    The old usernames are reserved, so nobody else can take a name that is still a member of a league; the person
    who had it can reclaim it by signing up with the same (verified) email, or the owner can release it.
    A copy of accounts.db is written to backup_dir first. Returns the number of logins removed."""
    import shutil
    from datetime import datetime
    with accounts() as conn:
        if conn.execute("SELECT value FROM settings WHERE key = 'accounts_reset_212'").fetchone():
            return 0
        users = [dict(r) for r in conn.execute("SELECT username, email, is_demo FROM users")]
    if users:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copyfile(data_dir() / "accounts.db", backup_dir / f"accounts-before-2.1.2-reset-{stamp}.db")
    with accounts() as conn:
        for u in users:
            if not u["is_demo"]:
                conn.execute("INSERT OR IGNORE INTO reserved_usernames(username, email_hash, reserved_at) VALUES(?,?,?)",
                             (u["username"], _email_hash(u["email"]), now_iso()))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ACCOUNT_TABLES:
            if table in tables:
                conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO settings(key, value) VALUES('accounts_reset_212', ?)", (now_iso(),))
    return len(users)


def reserved(username):
    with accounts() as conn:
        row = conn.execute("SELECT * FROM reserved_usernames WHERE username = ?", (normalise(username),)).fetchone()
    return dict(row) if row else None


def reserved_count():
    with accounts() as conn:
        return conn.execute("SELECT COUNT(*) FROM reserved_usernames").fetchone()[0]


def release_username(username):
    with accounts() as conn:
        return conn.execute("DELETE FROM reserved_usernames WHERE username = ?", (normalise(username),)).rowcount


def may_claim(username, email, verified):
    """A reserved (pre-2.1.2) username can be taken again only by the same person: a verified sign-up with the email
    that login had. Otherwise the owner has to release it."""
    r = reserved(username)
    if not r:
        return True
    return bool(verified and r["email_hash"] and _email_hash(email) == r["email_hash"])


def find_user(query):
    """Owner's account recovery: one account by exact username or email (never a list)."""
    q = (query or "").strip().lower()
    if not q:
        return None
    with accounts() as conn:
        row = conn.execute("SELECT * FROM users WHERE (username = ? OR lower(email) = ?) AND is_demo = 0 LIMIT 1",
                           (q, q)).fetchone()
    return dict(row) if row else None


def signup_direct(username, display_name, password, ip, email=None):
    """Sign-up when the site can't send email: the account is made straight away (no code). Reserved usernames
    can't be claimed this way, because nobody can prove the email is theirs; the owner can release one."""
    if not signups_allowed():
        raise AuthError("Sign-ups are turned off on this site.")
    username = normalise(username)
    if reserved(username):
        raise AuthError("That username belonged to someone before the site was reset. Choose another, or ask the "
                        "site owner to release it for you.")
    key, now = f"signup:{ip or '?'}", time.time()
    with accounts() as conn:
        row = conn.execute("SELECT * FROM login_failures WHERE key = ?", (key,)).fetchone()
        count = row["count"] if row and now - row["first_at"] < 3600 else 0
        if count >= SIGNUPS_PER_IP_PER_HOUR:
            raise AuthError("Too many sign-ups from this connection. Try again later.")
        first = row["first_at"] if row and count else now
        conn.execute("""INSERT INTO login_failures(key, count, first_at, locked_until) VALUES(?,?,?,0)
                        ON CONFLICT(key) DO UPDATE SET count=excluded.count, first_at=excluded.first_at""",
                     (key, count + 1, first))
    return create_user(username, display_name, password, email=email)
