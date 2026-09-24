"""Career save files: one independent SQLite database per career."""

import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
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


JOIN_MODES = {"requests": "Join requests enabled", "invite": "Invite only", "closed": "Closed to new members"}


def join_mode_from(meta):
    """The league's join mode. Leagues from before v1.18 only had join_open: on = requests, off = invite only."""
    mode = meta.get("join_mode")
    if mode in JOIN_MODES:
        return mode
    return "requests" if meta.get("join_open") == "1" else "invite"


def join_mode(conn):
    return join_mode_from({"join_mode": get_meta(conn, "join_mode"), "join_open": get_meta(conn, "join_open")})


def set_join_mode(conn, mode):
    if mode not in JOIN_MODES:
        raise ValueError("Unknown join mode")
    set_meta(conn, "join_mode", mode)
    set_meta(conn, "join_open", "1" if mode == "requests" else "0")  # older code and exports read this


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
            members, requests, players, invited = [], [], 0, []
            try:
                invited = [r[0] for r in conn.execute("SELECT username FROM invitations WHERE status = 'Pending'")]
            except sqlite3.OperationalError:
                pass
            roles_, muted = {}, []
            try:
                roles_ = {r[0]: {"role": r[1], "driver_id": r[2]}
                          for r in conn.execute("SELECT username, role, driver_id FROM career_members")}
                muted = [r[0] for r in conn.execute("SELECT username FROM member_notify WHERE muted = 1")]
            except sqlite3.OperationalError:
                pass
            try:
                members = [r[0] for r in conn.execute("SELECT username FROM career_members")]
                players = conn.execute("SELECT COUNT(*) FROM drivers WHERE is_player = 1 AND active = 1").fetchone()[0]
                requests = [r[0] for r in conn.execute("SELECT username FROM join_requests WHERE status = 'Pending'")]
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
        "join_open": join_mode_from(meta) == "requests",
        "join_mode": join_mode_from(meta),
        "join_label": JOIN_MODES[join_mode_from(meta)],
        "invited": invited,
        "pending_requests": requests,
        "players": players,
        "roles": roles_,
        "demo": token.startswith("demo-"),
        "muted": muted,
        "visibility": meta.get("visibility", "private"),
        "description": meta.get("league_description", ""),
        "accent": meta.get("accent_color", ""),
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
             "when": datetime.fromtimestamp(p.stat().st_mtime).replace(microsecond=0).isoformat(sep=" ")}
            for p in files]


def auto_backup_path(token, name):
    path = auto_backups_dir(token) / Path(name).name
    if not path.exists() or path.suffix != CAREER_EXT:
        raise CareerNotFound(name)
    return path


SAFETY_BACKUPS_KEPT = 30


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
    label = re.sub(r'[^a-z0-9-]', '', reason.lower())
    target = folder / f"{stamp}-{label}{CAREER_EXT}"
    n = 2
    while target.exists():  # two backups in the same second must never overwrite each other
        target = folder / f"{stamp}-{label}-{n}{CAREER_EXT}"
        n += 1
    src = _connect(source)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    existing.append(target)
    # Safety copies taken before a risky operation ("before-…") are kept apart from the rolling daily/after-race
    # set, so a busy week of race nights can't rotate away the copy from just before a season rollover.
    routine = [p for p in existing if "-before-" not in p.name]
    safety = [p for p in existing if "-before-" in p.name]
    for old in routine[:-AUTO_BACKUPS_KEPT] + safety[:-SAFETY_BACKUPS_KEPT]:
        old.unlink(missing_ok=True)
    return target


def integrity_check(token):
    """SQLite's own check plus the league's basic shape, for the Backups page. Read-only."""
    path = career_path(token)
    out = {"ok": True, "problems": [], "backups": 0}
    conn = _connect(path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            out["problems"].append(f"Database check: {result}")
        missing = REQUIRED_TABLES - {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if missing:
            out["problems"].append("Missing tables: " + ", ".join(sorted(missing)))
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            out["problems"].append(f"{len(fk)} rows point at something that no longer exists")
        out["seasons"] = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
        out["results"] = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    finally:
        conn.close()
    for b in list_auto_backups(token)[:3]:
        try:
            _validate_save(auto_backup_path(token, b["name"]))
            out["backups"] += 1
        except (ValueError, CareerNotFound) as exc:
            out["problems"].append(f"Backup {b['name']} can't be restored: {exc}")
    out["ok"] = not out["problems"]
    return out


# Never in a download: the Discord webhook (anyone holding it can post as the league) and the public-link key.
SECRET_META = {"discord_webhook", "public_key"}
# Not exported: delivery bookkeeping (who was emailed) and per-device read markers.
EXPORT_SKIP = {"deliveries", "notification_reads"}


def export_json(token):
    """The whole league as JSON, one key per table, plus an `_export` header saying what this is. Secrets are left
    out (see SECRET_META); everything else a Race Master can see in the app is included."""
    with session(token) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        data = {"_export": {"format": "paddock-legacy-league", "version": 2, "exported_at": now_iso(),
                            "schema_version": get_meta(conn, "schema_version"),
                            "redacted": sorted(SECRET_META)}}
        for table in EXPORT_TABLES + [t for t in tables if t not in EXPORT_TABLES]:
            if table in EXPORT_SKIP or table not in tables:
                continue
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            if table == "meta":
                rows = [r for r in rows if r["key"] not in SECRET_META]
            data[table] = rows
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def redacted_copy(path):
    """A copy of a save with the secrets blanked, for downloading. The backup on the server keeps them, so a restore
    there loses nothing; someone restoring a downloaded file re-enters the Discord webhook."""
    fd, tmp = tempfile.mkstemp(suffix=CAREER_EXT)
    os.close(fd)
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        dst.execute(f"DELETE FROM meta WHERE key IN ({','.join('?' * len(SECRET_META))})", tuple(SECRET_META))
        dst.commit()
    finally:
        src.close()
        dst.close()
    with open(tmp, "rb") as fh:
        data = fh.read()
    os.unlink(tmp)
    return data


def _validate_save(file_path):
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


def restore(token, file_path):
    """Replace a league with a backup, in place. The current state is backed up first, so it can be undone."""
    _validate_save(file_path)
    target = career_path(token)
    if not target.exists():
        raise CareerNotFound(token)
    safety = auto_backup(token, "before-restore", force=True)
    checkpoint(token)
    src = sqlite3.connect(str(file_path))
    dst = _connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    with session(token) as conn:
        set_meta(conn, "career_id", token)
    return safety


def import_preview(file_path):
    """What's in an uploaded save, read from a throwaway copy (the upload is never changed or registered)."""
    _validate_save(file_path)
    fd, tmp = tempfile.mkstemp(suffix=CAREER_EXT)
    os.close(fd)
    try:
        shutil.copyfile(file_path, tmp)
        conn = _connect(Path(tmp))
        try:
            before = get_meta(conn, "schema_version")
            migrate(conn)
            conn.commit()
            q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
            seasons = [r[0] for r in conn.execute("SELECT year FROM seasons ORDER BY year")]
            return {"name": get_meta(conn, "career_name") or "Imported league", "seasons": seasons,
                    "drivers": q("SELECT COUNT(*) FROM drivers"), "teams": q("SELECT COUNT(*) FROM teams"),
                    "rounds": q("SELECT COUNT(*) FROM events"),
                    "completed": q("SELECT COUNT(*) FROM events WHERE status = 'Complete'"),
                    "members": q("SELECT COUNT(*) FROM career_members"),
                    "upgrade": str(before or "") != str(SCHEMA_VERSION)}
        finally:
            conn.close()
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            if os.path.exists(tmp + suffix):
                os.unlink(tmp + suffix)


def import_career(file_path):
    """Validate an uploaded .f1career file and store it under a fresh token."""
    _validate_save(file_path)
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
    avatars = data_dir() / "avatars" / sanitize_token(token)
    if avatars.is_dir():
        shutil.rmtree(avatars, ignore_errors=True)
