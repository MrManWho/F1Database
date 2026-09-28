"""Operations for 4.0 (Phase 1): environment names, the health check, structured logs, the owner's error log and
the test site's delivery preview.

Environments: every copy of the site has a name, shown as a badge so nobody mistakes one for another. It comes from
F1_TRACKER_ENV (local / test / staging / production); without it, the test site (F1_TRACKER_TEST_SITE=1) is "test",
a site on Render is "production" and anything else is "local".

Errors: anything the site logs at ERROR level (an unhandled page error, a failed background send) is kept in
accounts.db for the site owner, grouped by kind and place. Messages are scrubbed of email addresses, links and long
tokens first; no request data, form values or passwords are ever stored.

Delivery preview: on the test site nothing is ever sent. Every email, Discord post and phone alert the site would
have sent is saved as a preview instead, so the site owner can check what would have gone out and to how many
people. Addresses are masked and only the newest PREVIEW_KEEP are kept.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
import traceback

from . import auth
from .storage import now_iso

ENVIRONMENTS = {"local": "Local", "test": "4.0 test", "staging": "Staging", "production": "Production"}
ERROR_KEEP = 200
PREVIEW_KEEP = 300
_guard = threading.local()

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
URL_RE = re.compile(r"https?://\S+")
TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")


# --------------------------------------------------------------------------- environment

def environment():
    name = (os.environ.get("F1_TRACKER_ENV") or "").strip().lower()
    if name in ENVIRONMENTS:
        return name
    from . import testsite
    if testsite.on():
        return "test"
    return "production" if os.environ.get("RENDER") else "local"


def environment_label():
    return ENVIRONMENTS[environment()]


def health():
    """(ok, details) for /healthz. Cheap: opens the accounts database and checks the data folder is writable."""
    from . import constants as C, storage
    checks = {}
    try:
        with auth.accounts() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["accounts_db"] = "ok"
    except Exception as exc:     # pragma: no cover - reported, never raised
        checks["accounts_db"] = f"error: {type(exc).__name__}"
    try:
        probe = storage.data_dir() / ".healthz"
        probe.write_text(str(time.time()))
        probe.unlink()
        checks["data_dir"] = "ok"
    except Exception as exc:     # pragma: no cover
        checks["data_dir"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    from . import maintenance
    return ok, {"ok": ok, "version": C.APP_VERSION, "environment": environment(), "schema": C.SCHEMA_VERSION,
                "maintenance": maintenance.active(), "checks": checks}


# --------------------------------------------------------------------------- structured logs

class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message (scrubbed) and any extra fields given."""

    FIELDS = ("method", "endpoint", "status", "ms", "environment")

    def format(self, record):
        out = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)), "level": record.levelname,
               "logger": record.name, "message": scrub(record.getMessage())}
        for f in self.FIELDS:
            if hasattr(record, f):
                out[f] = getattr(record, f)
        if record.exc_info:
            out["error"] = record.exc_info[0].__name__
        return json.dumps(out)


def configure_logging():
    """For the hosted site (server.py): JSON lines on standard output, which the host collects."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


# --------------------------------------------------------------------------- error log

def scrub(text):
    text = EMAIL_RE.sub("[email]", str(text or ""))
    text = URL_RE.sub("[link]", text)
    return TOKEN_RE.sub("[token]", text)[:300]


def _errors_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS error_log (
        fingerprint TEXT PRIMARY KEY, kind TEXT NOT NULL, place TEXT NOT NULL, message TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, first_at TEXT NOT NULL, last_at TEXT NOT NULL)""")


def record_error(kind, place, message):
    """Keep one row per kind + place + message, counting repeats."""
    if getattr(_guard, "busy", False):
        return
    _guard.busy = True
    try:
        message = scrub(message)
        fp = hashlib.sha256(f"{kind}|{place}|{message}".encode()).hexdigest()[:16]
        now = now_iso()
        with auth.accounts() as conn:
            _errors_table(conn)
            conn.execute("""INSERT INTO error_log(fingerprint, kind, place, message, first_at, last_at) VALUES(?,?,?,?,?,?)
                            ON CONFLICT(fingerprint) DO UPDATE SET count = count + 1, last_at = excluded.last_at""",
                         (fp, kind[:80], place[:120], message, now, now))
            conn.execute("""DELETE FROM error_log WHERE fingerprint NOT IN
                            (SELECT fingerprint FROM error_log ORDER BY last_at DESC LIMIT ?)""", (ERROR_KEEP,))
    except Exception:
        pass            # the error log must never cause an error of its own
    finally:
        _guard.busy = False


def errors():
    with auth.accounts() as conn:
        _errors_table(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM error_log ORDER BY last_at DESC")]


def clear_errors():
    with auth.accounts() as conn:
        _errors_table(conn)
        conn.execute("DELETE FROM error_log")


class ErrorLogHandler(logging.Handler):
    """Sends ERROR records from the site's own loggers to the error log."""

    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            tb = traceback.extract_tb(record.exc_info[2])
            here = next((f for f in reversed(tb) if "f1tracker" in f.filename), tb[-1] if tb else None)
            place = f"{os.path.basename(here.filename)}:{here.name}" if here else record.name
            record_error(type(exc).__name__, place, f"{record.getMessage()}: {exc}")
        else:
            record_error("Logged error", record.name, record.getMessage())


def install_error_log():
    logger = logging.getLogger("f1tracker")
    if not any(isinstance(h, ErrorLogHandler) for h in logger.handlers):
        logger.addHandler(ErrorLogHandler())


# --------------------------------------------------------------------------- delivery preview (test site)

def _previews_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS delivery_previews (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, recipients INTEGER NOT NULL,
        shown_to TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL)""")


def mask(address):
    name, _, domain = str(address).partition("@")
    return (name[:1] + "•••" + ("@" + domain if domain else "")) if name else "•••"


def capture(kind, payload):
    """What the site would have sent, saved instead of sent (test site only)."""
    if kind == "email":
        to = list(payload.get("to") or [])
        shown, title, body = ", ".join(mask(a) for a in to[:5]), payload.get("subject", ""), payload.get("text", "")
        count = len(to)
    elif kind == "discord":
        shown, title, body, count = "Discord channel", "Discord post", payload.get("message", ""), 1
    else:
        names = list(payload.get("names") or [])
        shown, title, body = ", ".join(names[:5]), payload.get("title", ""), payload.get("body", "")
        count = len(names)
    with auth.accounts() as conn:
        _previews_table(conn)
        oid = conn.execute("""INSERT INTO delivery_previews(created_at, kind, recipients, shown_to, title, body)
                              VALUES(?,?,?,?,?,?)""", (now_iso(), kind, count, shown[:300], str(title)[:200],
                                                       str(body)[:4000])).lastrowid
        conn.execute("DELETE FROM delivery_previews WHERE id <= ?", (oid - PREVIEW_KEEP,))
    return oid


def previews(limit=100):
    with auth.accounts() as conn:
        _previews_table(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM delivery_previews ORDER BY id DESC LIMIT ?", (limit,))]


def clear_previews():
    with auth.accounts() as conn:
        _previews_table(conn)
        conn.execute("DELETE FROM delivery_previews")
