"""A safe demo: every visitor gets their own temporary copy of a ready-made league.

The template league is built once (a completed season and an active one, three player drivers, AI grid,
contracts and transfers) and copied for each visitor, who is signed in as a throwaway guest who is Race Master
of that copy only. Demo leagues are marked demo (meta demo=1): they never send email, phone or Discord alerts,
can't invite anyone, and are deleted with their guest after DEMO_HOURS. Real leagues are never touched or shown.
"""

import random
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta

from . import auth, market, relations, roles, seats, storage, teamlife
from . import constants as C
from . import services as S

DEMO_HOURS = 2
PLAYERS = ["Alex Rivera", "Sam Okafor", "Jordan Lee"]


def available():
    return True


def is_demo(conn):
    return storage.get_meta(conn, "demo") == "1"


def _template_path():
    return storage.data_dir() / "demo-template.f1career"


def _results(conn, event, rng, order_bias):
    rows = S.weekend_rows(conn, event["id"])
    ids = [r["driver_id"] for r in rows]
    ranks = S.team_strength_ranks(conn, event["season_id"])
    team_of = {r["driver_id"]: r["team_id"] for r in rows}
    score = {d: ranks.get(team_of[d], 10) * 2 + rng.random() * 7 + order_bias.get(d, 0) for d in ids}
    order = sorted(ids, key=lambda d: score[d])
    quali = sorted(ids, key=lambda d: score[d] + rng.random() * 3)
    dnf = {rng.choice(ids)} if rng.random() < 0.7 else set()
    out = []
    for d in ids:
        out.append({"driver_id": d, "qualifying_position": quali.index(d) + 1, "race_position": order.index(d) + 1,
                    "status_override": "DNF" if d in dnf else "Auto",
                    "sprint_position": (order.index(d) + 1) if event["is_sprint"] else None, "sprint_status_override": "Auto",
                    "fastest_lap": d == order[1], "driver_of_day": d == order[2], "notes": ""})
    return out


def build_template():
    """Build the shared demo league from scratch (a few seconds). Deterministic, so every copy tells one story."""
    path = _template_path()
    tmp = storage.careers_dir() / "demo-template-build.f1career"
    for p in (tmp,):
        if p.exists():
            p.unlink()
    token = "demo-template-build"
    rng = random.Random(2026)
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Paddock Legacy Demo", 2026, PLAYERS)
        storage.set_meta(conn, "demo", "1")
        storage.set_meta(conn, "league_description", "A sample league: explore anything, change anything. It resets on its own.")
        storage.set_meta(conn, "timezone", "UTC")
        teamlife.save_settings(conn, "off", True, False, True, True)   # no gates, so the demo never stalls
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        for e in evs[10:]:
            conn.execute("DELETE FROM events WHERE id = ?", (e["id"],))
        ids = {d["name"]: d["id"] for d in S.player_drivers(conn)}
        teams = {t["name"]: t["id"] for t in S.teams(conn)}
        S.place_players(conn, sid, {ids["Alex Rivera"]: (teams["Williams"], 1), ids["Sam Okafor"]: (teams["Haas"], 1),
                                    ids["Jordan Lee"]: (teams["Alpine"], 2)})
        for name, team in (("Alex Rivera", "Williams"), ("Sam Okafor", "Haas"), ("Jordan Lee", "Alpine")):
            seats.record_contract(conn, ids[name], teams[team], 2026, 1 if name != "Sam Okafor" else 2)
        relations.ensure(conn, sid)
        for rel in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?", (sid,)).fetchall():
            relations.set_pledge(conn, sid, rel["driver_id"], 1)
        bias = {ids["Alex Rivera"]: -3, ids["Sam Okafor"]: -1, ids["Jordan Lee"]: 1}
        for e in S.events(conn, sid):
            S.save_weekend(conn, e["id"], {"results": _results(conn, e, rng, bias), "mark_complete": True,
                                          "ai_difficulty": rng.choice([84, 85, 85, 86])})
            conn.execute("UPDATE events SET submitted_at = ?, press_required = 0 WHERE id = ?", (storage.now_iso(), e["id"]))
            teamlife.after_race(conn, e["id"])
        # Alex moves to Aston Martin for 2027; Jordan re-signs; Sam is mid-contract.
        seats.record_contract(conn, ids["Alex Rivera"], teams["Aston Martin"], 2027, 2, role="No. 1")
        seats.record_contract(conn, ids["Jordan Lee"], teams["Alpine"], 2027, 1)
        relations.settle(conn, sid)
        new_id = S.create_next_season(conn, sid, 2027)
        relations.apply_rewards(conn, sid, new_id)
        S.develop_cars(conn, sid, new_id, random.Random(7))
        S.place_players(conn, new_id, {ids["Alex Rivera"]: (teams["Aston Martin"], 1)})
        relations.ensure(conn, new_id)
        for e in S.events(conn, new_id)[:4]:
            S.save_weekend(conn, e["id"], {"results": _results(conn, e, rng, bias), "mark_complete": True,
                                          "ai_difficulty": 85})
            conn.execute("UPDATE events SET submitted_at = ?, press_required = 0 WHERE id = ?", (storage.now_iso(), e["id"]))
            teamlife.after_race(conn, e["id"])
        conn.execute("DELETE FROM notifications")
    storage.checkpoint(token)
    shutil.move(str(storage.career_path(token)), str(path))
    return path


def _template_ok():
    path = _template_path()
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            return bool(row) and int(row[0]) == C.SCHEMA_VERSION
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return False


def start():
    """A fresh private demo league and a guest login for it. Returns (username, token)."""
    cleanup()
    if not _template_ok():
        build_template()
    token = "demo-" + secrets.token_hex(5)
    shutil.copyfile(_template_path(), storage.career_path(token))
    username = "demo-guest-" + secrets.token_hex(4)
    auth.create_user(username, "Demo guest", secrets.token_urlsafe(24))
    with auth.accounts() as conn:
        conn.execute("UPDATE users SET is_demo = 1, created_at = ? WHERE username = ?", (storage.now_iso(), username))
    with storage.session(token) as conn:
        storage.set_meta(conn, "career_id", token)
        storage.set_meta(conn, "demo", "1")
        storage.set_meta(conn, "demo_created", storage.now_iso())
        ids = {d["name"]: d["id"] for d in S.player_drivers(conn)}
        roles.set_member(conn, username, "race_master", ids.get("Alex Rivera"))
    return username, token


def cleanup(now=None):
    """Delete demo leagues and guests older than DEMO_HOURS."""
    now = now or datetime.now()
    cutoff = (now - timedelta(hours=DEMO_HOURS)).replace(microsecond=0).isoformat(sep=" ")
    for path in storage.careers_dir().glob("demo-*" + storage.CAREER_EXT):
        # v3.0.1: the builder's work file is skipped only while fresh; one left behind by an interrupted build
        # used to stay in the league list forever
        if datetime.fromtimestamp(path.stat().st_mtime) < now - timedelta(hours=DEMO_HOURS):
            try:
                storage.delete_career(path.stem)
            except storage.CareerNotFound:
                pass
    with auth.accounts() as conn:
        conn.execute("DELETE FROM users WHERE is_demo = 1 AND created_at < ?", (cutoff,))


def discard(username, token):
    """Remove one visitor's demo copy and guest login (only ever demo ones)."""
    if token and token.startswith("demo-") and token != "demo-template-build":
        try:
            storage.delete_career(token)
        except storage.CareerNotFound:
            pass
    if username and username.startswith("demo-guest-"):
        with auth.accounts() as conn:
            conn.execute("DELETE FROM users WHERE username = ? AND is_demo = 1", (username,))
