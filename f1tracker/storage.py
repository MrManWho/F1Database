"""Career save files: one independent SQLite database per career."""

import json
import os
import re
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .constants import AUTO_BACKUP_EVERY_HOURS, AUTO_BACKUPS_KEPT, SCHEMA_VERSION
from .schema import REQUIRED_TABLES, migrate

CAREER_EXT = ".f1career"
EXPORT_TABLES = [
    "meta", "teams", "drivers", "seasons", "season_grid", "season_driver_state",
    "events", "results", "contracts", "market_windows", "offers", "offer_messages", "career_members",
    "team_seasons", "news", "notifications",
]


class CareerNotFound(Exception):
    pass


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def data_dir():
    custom = os.environ.get("F1_TRACKER_DATA_DIR")
    if custom:
        base = Path(custom)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "F1UniverseTracker"
    else:
        base = Path.home() / ".f1-universe-tracker"
    base.mkdir(parents=True, exist_ok=True)
    return base


def careers_dir():
    path = data_dir() / "careers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir():
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_token(token):
    return re.sub(r"[^A-Za-z0-9_-]", "", token or "")


def new_token():
    return secrets.token_hex(6)


def career_path(token):
    token = sanitize_token(token)
    if not token:
        raise CareerNotFound(token)
    return careers_dir() / f"{token}{CAREER_EXT}"


def _connect(path):
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_db(token, create=False):
    path = career_path(token)
    if not create and not path.exists():
        raise CareerNotFound(token)
    conn = _connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    if not create:
        _backup_before_upgrade(conn, token)
    migrate(conn)
    conn.commit()
    return conn


def _schema_version(conn):
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return int(row[0]) if row else 1
    except (sqlite3.Error, ValueError, TypeError):
        return 1


def _backup_before_upgrade(conn, token):
    """Copy a save to the backups folder before a newer version changes its format."""
    version = _schema_version(conn)
    if version >= SCHEMA_VERSION:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir() / f"{sanitize_token(token)}-before-v{SCHEMA_VERSION}-upgrade-{stamp}{CAREER_EXT}"
    dst = sqlite3.connect(str(target))
    try:
        conn.backup(dst)
    finally:
        dst.close()
    return target


@contextmanager
def session(token, create=False):
    """Every action inside is committed on success and rolled back on error."""
    conn = open_db(token, create=create)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _summary(path):
    token = path.stem
    try:
        conn = _connect(path)
        try:
            meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
            season = conn.execute(
                "SELECT year FROM seasons WHERE id = ?", (meta.get("current_season_id"),)
            ).fetchone()
            done = conn.execute("SELECT COUNT(*) FROM events WHERE status = 'Complete'").fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            members = []
            try:
                members = [r[0] for r in conn.execute("SELECT username FROM career_members")]
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None
    return {
        "token": token,
        "name": meta.get("career_name", "Unnamed career"),
        "year": season["year"] if season else None,
        "completed": done,
        "total": total,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "last_opened": meta.get("last_opened_at", ""),
        "members": members,
    }


def list_careers():
    items = [s for s in (_summary(p) for p in careers_dir().glob(f"*{CAREER_EXT}")) if s]
    items.sort(key=lambda c: c["last_opened"] or "", reverse=True)
    return items


def touch_opened(conn):
    set_meta(conn, "last_opened_at", now_iso())


def checkpoint(token):
    with session(token) as conn:
        touch_opened(conn)
    conn = _connect(career_path(token))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "career"


def save_as(token, new_name):
    src_path = career_path(token)
    if not src_path.exists():
        raise CareerNotFound(token)
    new = new_token()
    src = _connect(src_path)
    dst = _connect(career_path(new))
    try:
        src.backup(dst)
        stamp = now_iso()
        set_meta(dst, "career_id", new)
        set_meta(dst, "career_name", new_name)
        set_meta(dst, "created_at", stamp)
        set_meta(dst, "last_opened_at", stamp)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return new


def make_backup(token):
    with session(token) as conn:
        name = get_meta(conn, "career_name", "career")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir() / f"{_slug(name)}-{stamp}{CAREER_EXT}"
    src = _connect(career_path(token))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return target


def auto_backups_dir(token):
    path = backups_dir() / "auto" / sanitize_token(token)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_auto_backups(token):
    files = sorted(auto_backups_dir(token).glob(f"*{CAREER_EXT}"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1),
             "when": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")} for p in files]


def auto_backup_path(token, name):
    path = auto_backups_dir(token) / Path(name).name
    if not path.exists() or path.suffix != CAREER_EXT:
        raise CareerNotFound(name)
    return path


def auto_backup(token, reason="daily", force=False):
    """Keep a rolling set of automatic backups: daily, and after every completed race weekend."""
    source = career_path(token)
    if not source.exists():
        return None
    folder = auto_backups_dir(token)
    existing = sorted(folder.glob(f"*{CAREER_EXT}"), key=lambda p: p.stat().st_mtime)
    if not force and existing:
        age_hours = (datetime.now().timestamp() - existing[-1].stat().st_mtime) / 3600
        if age_hours < AUTO_BACKUP_EVERY_HOURS:
            return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{stamp}-{re.sub(r'[^a-z0-9-]', '', reason.lower())}{CAREER_EXT}"
    src = _connect(source)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    existing.append(target)
    for old in existing[:-AUTO_BACKUPS_KEPT]:
        old.unlink(missing_ok=True)
    return target


def export_json(token):
    with session(token) as conn:
        data = {}
        for table in EXPORT_TABLES:
            data[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def import_career(file_path):
    """Validate an uploaded .f1career file and store it under a fresh token."""
    try:
        conn = sqlite3.connect(str(file_path))
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError("That file is not a valid .f1career database") from exc
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError("Save is missing required tables: " + ", ".join(sorted(missing)))
    token = new_token()
    shutil.copyfile(file_path, career_path(token))
    with session(token) as conn:
        set_meta(conn, "career_id", token)
        touch_opened(conn)
    return token


def delete_career(token):
    path = career_path(token)
    if not path.exists():
        raise CareerNotFound(token)
    path.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            extra.unlink()
