"""4.0 Phase 0: inventories and the Engine 2 scan, generated from the code so they can't drift from it.

    python -m f1tracker.phase0 inventory docs/4.0     write the route, table and permission inventories
    python -m f1tracker.phase0 scan                   which leagues and seasons still use Engine 2 (read-only)

The scan opens every league file read-only (no upgrade, no backup, no write), so it is safe to run against a copy
of the live data.
"""

import inspect
import re
import sqlite3
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent

# What 4.0 does with each stored table (owner decisions, Phase 0). Anything not listed is migrated exactly.
NOT_MIGRATED = {
    "user_sessions": "sessions: everyone signs in again",
    "sessions": "sessions: everyone signs in again",
    "password_resets": "temporary security data (expired links)",
    "pending_signups": "temporary security data (unfinished sign-ups)",
    "email_codes": "temporary security data",
    "login_failures": "temporary security data (lockout counters)",
    "login_failure_names": "temporary security data (lockout counters)",
    "rate_hits": "rate-limit history",
    "outbox": "old delivery queue",
}
OPTIONAL = {
    "notifications": "old notification rows may be left behind (preferences migrate)",
    "notification_reads": "old notification rows may be left behind (preferences migrate)",
}


# --------------------------------------------------------------------------- routes

def _who(rule, view, app_module):
    league = "<token>" in rule.rule
    declared = getattr(view, "access", None)
    if rule.endpoint in app_module.PUBLIC_ENDPOINTS:
        return "public"
    if declared == "master":
        return "league Race Master" if league else "site owner"
    if declared == "ops":
        return "Race Master + Scorekeeper"
    if declared == "member":
        return "league member"
    try:
        body = inspect.getsource(view)
    except (OSError, TypeError):
        body = ""
    if re.search(r"is_master|abort\(403\)|_may_enter_results|, 403", body):
        return "signed in (checks inside)"
    return "signed in"


def routes(app):
    from . import app as app_module
    out = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        if rule.endpoint == "static":
            continue
        view = app.view_functions[rule.endpoint]
        out.append({
            "path": rule.rule,
            "methods": ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"})),
            "endpoint": rule.endpoint,
            "who": _who(rule, view, app_module),
            "spectator_post": rule.endpoint in app_module.SPECTATOR_POST_OK,
            "demo_blocked": rule.endpoint in app_module.DEMO_BLOCKED,
        })
    return out


# --------------------------------------------------------------------------- tables

def _tables(conn):
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: [c[1] for c in conn.execute(f"PRAGMA table_info({n})")] for n in names}


def _lazy_tables():
    """Tables a module creates the first time it's used ({name: module})."""
    found = {}
    for path in sorted(SRC.glob("*.py")):
        for name in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", path.read_text(encoding="utf-8")):
            found.setdefault(name, path.stem)
    return found


def tables():
    """{'site': {...}, 'league': {...}, 'lazy': {...}} from a fresh league and site database."""
    import os
    import tempfile
    from . import auth, services as S, storage
    old = os.environ.get("F1_TRACKER_DATA_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["F1_TRACKER_DATA_DIR"] = tmp
        try:
            token = storage.new_token()
            with storage.session(token, create=True) as conn:
                S.seed_career(conn, token, "Inventory", 2026, ["Player One"])
                league = _tables(conn)
            auth.user_count()
            with auth.accounts() as conn:
                site = _tables(conn)
        finally:
            if old is None:
                os.environ.pop("F1_TRACKER_DATA_DIR", None)
            else:
                os.environ["F1_TRACKER_DATA_DIR"] = old
    lazy = {n: m for n, m in _lazy_tables().items() if n not in league and n not in site}
    return {"site": site, "league": league, "lazy": lazy}


def migration_rule(name):
    if name in NOT_MIGRATED:
        return "not migrated: " + NOT_MIGRATED[name]
    if name in OPTIONAL:
        return "optional: " + OPTIONAL[name]
    if name == "settings":
        return "migrated; SMTP/Discord secrets never copied into the test site"
    return "migrated exactly"


# --------------------------------------------------------------------------- Engine 2 scan (read-only)

def _open_ro(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def scan(folder=None):
    """Every league file and season: which engine it's calculated with. Never writes anything."""
    from . import constants as C, engine, storage
    folder = Path(folder) if folder else storage.careers_dir()
    leagues = []
    for path in sorted(folder.glob(f"*{storage.CAREER_EXT}")):
        item = {"id": path.stem, "name": "", "engine": None, "choice": None, "seasons": [], "error": None}
        try:
            conn = _open_ro(path)
            try:
                meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
                item["name"] = meta.get("career_name", "")
                item["demo"] = meta.get("demo") == "1" or path.stem.startswith("demo-")
                item["engine"] = engine.league_engine(conn)
                item["choice"] = engine.choice(conn)
                current = meta.get("current_season_id")
                for s in conn.execute("SELECT * FROM seasons ORDER BY year"):
                    rounds = conn.execute("SELECT COUNT(*) AS n, SUM(status = ?) AS done FROM events WHERE season_id = ?",
                                          (C.EVENT_COMPLETE, s["id"])).fetchone()
                    active = s["status"] == "Active" or str(s["id"]) == str(current)
                    finished = bool(rounds["n"]) and rounds["done"] == rounds["n"]
                    item["seasons"].append({
                        "id": s["id"], "year": s["year"], "label": s["label"], "status": s["status"],
                        "active": active and not finished, "engine": engine.season_engine(conn, s["id"]),
                        "cutoff": engine.cutoff(conn, s["id"]), "rounds": rounds["n"], "done": rounds["done"] or 0,
                    })
            finally:
                conn.close()
        except sqlite3.Error as exc:
            item["error"] = f"can't be read: {exc}"
        leagues.append(item)
    v2_active = [(lg, s) for lg in leagues for s in lg["seasons"] if s["active"] and s["engine"] < 3]
    v2_history = [(lg, s) for lg in leagues for s in lg["seasons"] if not s["active"] and s["engine"] < 3]
    pending = [lg for lg in leagues if lg["engine"] is not None and lg["engine"] < 3
               and lg["choice"] in ("pending", "later")]
    return {"leagues": leagues, "v2_active": v2_active, "v2_history": v2_history, "pending_choice": pending,
            "verdict": ("Engine 2 still runs an active season: keep its calculation code until that season finishes."
                        if v2_active else
                        "No active season uses Engine 2. Keep historical values; Engine 2 can be retired from new "
                        "calculations.")}


def scan_text(result):
    lines = [result["verdict"], ""]
    for lg in result["leagues"]:
        head = f"{lg['id']}  {lg['name'] or '(no name)'}"
        if lg.get("error"):
            lines.append(f"{head}: {lg['error']}")
            continue
        lines.append(f"{head}: league engine {lg['engine']}, choice {lg['choice']}{' (demo)' if lg.get('demo') else ''}")
        for s in lg["seasons"]:
            cut = f", Version 3 from round {s['cutoff'] + 1}" if s["cutoff"] else ""
            state = "ACTIVE" if s["active"] else "finished"
            lines.append(f"    {s['label']} ({s['year']}): engine {s['engine']}{cut}, {s['done']}/{s['rounds']} rounds, {state}")
    lines.append("")
    lines.append(f"Active seasons on Engine 2: {len(result['v2_active'])}. Finished seasons on Engine 2: "
                 f"{len(result['v2_history'])}. Leagues that haven't answered the Calculation Update: "
                 f"{len(result['pending_choice'])}.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- writing the inventories

def _md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(out)


def write_inventories(folder):
    from . import app as app_module, constants as C, roles
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    app = app_module.create_app({"TESTING": True, "SECRET_KEY": "inventory"})
    rs = routes(app)
    note = f"Generated by `python -m f1tracker.phase0 inventory` from v{C.APP_VERSION}. Don't edit by hand."

    counts = {}
    for r in rs:
        counts[r["who"]] = counts.get(r["who"], 0) + 1
    body = ["# Route inventory (v3 baseline)", "", note, "",
            f"{len(rs)} routes. By who may use them: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ".",
            "", "*Spectator POST*: a Spectator may send this (personal settings only). *Demo*: blocked for demo guests.", "",
            _md_table(["Path", "Methods", "Endpoint", "Who", "Spectator POST", "Demo"],
                      [(f"`{r['path']}`", r["methods"], r["endpoint"], r["who"], "yes" if r["spectator_post"] else "",
                        "blocked" if r["demo_blocked"] else "") for r in rs])]
    (folder / "ROUTES.md").write_text("\n".join(body) + "\n")

    t = tables()
    body = ["# Table inventory (v3 baseline)", "", note, ""]
    for label, key in (("Site database (accounts.db)", "site"), ("Each league file (careers/<id>.f1career)", "league")):
        body += [f"## {label}", "", _md_table(["Table", "Columns", "4.0 migration"],
                                               [(n, ", ".join(cols), migration_rule(n)) for n, cols in t[key].items()]), ""]
    body += ["## Created on first use", "", "These appear only once a feature is used.", "",
             _md_table(["Table", "Created by", "4.0 migration"],
                       [(n, f"`{m}.py`", migration_rule(n)) for n, m in sorted(t["lazy"].items())]), "",
             "## Files", "", _md_table(["Files", "4.0 migration"], [
                 ("avatars/ (driver photos)", "migrated"),
                 ("backups/ (automatic and manual league backups)", "not migrated: a fresh 4.0 backup history starts; "
                  "the original migration archive is kept"),
                 ("secret.key", "not migrated: everyone signs in again")])]
    (folder / "TABLES.md").write_text("\n".join(body) + "\n")

    by_who = {}
    for r in rs:
        by_who.setdefault(r["who"], []).append(r["endpoint"])
    body = ["# Permission inventory (v3 baseline)", "", note, "",
            "## League capabilities (shown in the app; each row is enforced on the server)", "",
            _md_table(["Capability", "Race Master", "Scorekeeper", "Member", "Spectator"],
                      [(cap, *("✓" if v is True else "–" if v is False else v for v in vals))
                       for cap, *vals in roles.PERMISSIONS]), "",
            "Site owner: Race Master of every league, plus the site pages below. A Spectator may only POST to: " +
            ", ".join(sorted(app_module.SPECTATOR_POST_OK)) + ".", "", "## Routes by access level", ""]
    for who in sorted(by_who):
        body += [f"### {who} ({len(by_who[who])})", "", ", ".join(f"`{e}`" for e in sorted(set(by_who[who]))), ""]
    body += ["Routes marked *signed in (checks inside)* do their own check in the view (for example the site owner's",
             "Accounts page). Phase 1 turns each into a declared access level so the every-route test covers them."]
    (folder / "PERMISSIONS.md").write_text("\n".join(body) + "\n")
    return folder


def _main(argv):
    if len(argv) == 3 and argv[1] == "inventory":
        print("written to", write_inventories(argv[2]))
        return 0
    if len(argv) in (2, 3) and argv[1] == "scan":
        print(scan_text(scan(argv[2] if len(argv) == 3 else None)))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
