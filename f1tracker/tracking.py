"""Legacy-season tracking (4.0): what each season could record, so older seasons look complete under their own rules.

A league played on 3.x and opened by 4.0 keeps every result and career outcome exactly as it was. What 4.0 adds is
more tracking (race times, incidents by session, the stored pre-round AI recommendation), and 3.x itself added
features part-way through (weather, weekend targets, press). This module records, per season and feature, from which
round that feature was tracked, so pages can tell three cases apart:

* tracked and entered      -> show the value;
* tracked but never entered -> "Not recorded" (a genuine gap; it can still count as missing);
* not tracked at the time   -> hidden, or "Not tracked under this season's rules". Never a zero, a failure or an
                               incomplete task, and never part of an average's denominator.

How the start of each feature is found (`record_upgrade`, run once inside schema.migrate when a league last written
by 3.x is first opened by 4.0):

* 4.0 features start at the league's upgrade: the first round of the season under way with no results entered (a
  round already in progress finishes under the old rules), or round 1 of the next season if every round is played.
* Features added during 3.x are read from what's stored in each season, never from release dates. A feature first
  recorded at round 1 is tracked for the whole season; first recorded later than round 1 is flagged for the Race
  Master to confirm (until then the earlier rounds count as not tracked, so nothing is penalised); never recorded in a
  season is not tracked there (there is nothing to hide). Stored values are always shown, whatever the record says.

This is separate from the calculation engine (season_calc / calc_migrations): recording tracking never recalculates
anything. Seasons with no row (every season of a league created on 4.0, and seasons started after an upgrade) are
fully tracked.

Every migrated league also gets one notice per member (`notice_for` / `acknowledge`): stored in the league file per
username and migration, so another device, a refresh or a later sign-in never shows it again once "Got it" is
pressed, acknowledging one league never touches another, and a later distinct migration has its own notice.
"""

import json

from . import constants as C
from .storage import now_iso

KIND_40 = "4.0"

# key: (label, introduced in, how its start is found: "upgrade" = the league's 4.0 update, "records" = stored data)
FEATURES = {
    "race_times": ("Race times against the AI", "4.0", "upgrade"),
    "incident_sessions": ("Incidents by session", "4.0", "upgrade"),
    "track_ai": ("The AI recommendation shown before each round", "4.0", "upgrade"),
    "weather": ("Weather", "3.1", "records"),
    "targets": ("Weekend targets", "1.20", "records"),
    "prerace_press": ("Pre-race press", "2.3", "records"),
    "press": ("Post-race press", "1.15", "records"),
}

NOT_TRACKED = "Not tracked under this season's rules"
NOT_RECORDED = "Not recorded"


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS tracking_migrations (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL UNIQUE, from_schema INTEGER, migrated_at TEXT NOT NULL,
        start_year INTEGER, start_round INTEGER NOT NULL DEFAULT 1, audience TEXT NOT NULL DEFAULT '[]',
        note TEXT NOT NULL DEFAULT '')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS season_tracking (
        season_id INTEGER NOT NULL, feature TEXT NOT NULL, from_round INTEGER, review INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL, migration_id INTEGER, detail TEXT NOT NULL DEFAULT '', updated_by TEXT,
        updated_at TEXT NOT NULL, PRIMARY KEY (season_id, feature))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tracking_notice_acks (
        migration_id INTEGER NOT NULL, username TEXT NOT NULL, acked_at TEXT NOT NULL,
        PRIMARY KEY (migration_id, username))""")


def _has_table(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def is_pre_40(tables, schema_version):
    """A league file last written by 3.x: it has league data but not 4.0's change record. (Live 3.2.4-3.2.6 files say
    schema 22, the same number 4.0 started at, so the number alone can't tell.)"""
    return {"meta", "seasons", "events"} <= set(tables) and ("audit_events" not in tables or schema_version < 22)


# --------------------------------------------------------------------------- recording an upgrade

def _start_point(conn):
    """(year, round) where 4.0 tracking begins: the first round of the season under way with nothing entered yet,
    else round 1 of the next season."""
    from . import services as S
    sid = S.current_season_id(conn)
    if not sid:
        return None, 1
    season = S.get_season(conn, sid)
    row = conn.execute("""SELECT e.round_number FROM events e WHERE e.season_id = ? AND e.status = ?
                          AND NOT EXISTS (SELECT 1 FROM results r WHERE r.event_id = e.id
                                          AND (r.result_status != 'Not Run' OR r.qualifying_position IS NOT NULL
                                               OR r.sprint_status != 'Not Run'))
                          ORDER BY e.round_number LIMIT 1""", (sid, C.EVENT_NOT_RUN)).fetchone()
    if row:
        return season["year"], row[0]
    return season["year"] + 1, 1


def _recorded_rounds(conn, season_id, feature):
    """Round numbers of this season where a 3.x-era feature was demonstrably in use: something stored for it, or the
    round itself showing it was on (press required before the next round, targets offered, the paddock opened)."""
    pre = "p.question LIKE 'pre\\_%' ESCAPE '\\'"
    queries = {
        "weather": [("weather", "SELECT e.round_number FROM weather w JOIN events e ON e.id = w.event_id "
                                "WHERE e.season_id = ?")],
        "targets": [("weekend_targets", "SELECT e.round_number FROM weekend_targets t JOIN events e "
                                        "ON e.id = t.event_id WHERE e.season_id = ?"),
                    ("target_options", "SELECT e.round_number FROM target_options t JOIN events e "
                                       "ON e.id = t.event_id WHERE e.season_id = ?")],
        "prerace_press": [("press_answers", "SELECT e.round_number FROM press_answers p JOIN events e "
                                            f"ON e.id = p.event_id WHERE e.season_id = ? AND {pre}"),
                          ("events", "SELECT round_number FROM events WHERE season_id = ? AND paddock_at IS NOT NULL")],
        "press": [("press_answers", "SELECT e.round_number FROM press_answers p JOIN events e "
                                    f"ON e.id = p.event_id WHERE e.season_id = ? AND NOT {pre}"),
                  ("events", "SELECT round_number FROM events WHERE season_id = ? AND press_required = 1")],
    }
    found = set()
    for table, sql in queries[feature]:
        if _has_table(conn, table):
            found |= {r[0] for r in conn.execute(sql, (season_id,))}
    played = {r[0] for r in conn.execute("SELECT round_number FROM events WHERE season_id = ? AND status != ?",
                                         (season_id, C.EVENT_NOT_RUN))}
    return sorted(found & played)


def _plan(conn, start_year, start_round):
    """[(season_id, feature, from_round, review, detail)] for every season that existed at the upgrade."""
    out = []
    for s in conn.execute("SELECT id, year FROM seasons ORDER BY year").fetchall():
        sid, year = s["id"], s["year"]
        if start_year is not None and year > start_year:
            continue                      # (can't happen at an upgrade; later seasons have no row = fully tracked)
        upgrade_round = start_round if year == start_year else None     # None: the whole season was before 4.0
        for feature, (_label, _since, how) in FEATURES.items():
            if how == "upgrade":
                if upgrade_round == 1:
                    continue              # the season hadn't started: nothing to record, fully tracked
                out.append((sid, feature, upgrade_round, 0,
                            f"Began with the 4.0 update at round {upgrade_round}" if upgrade_round
                            else "Before the 4.0 update"))
                continue
            rounds = [r for r in _recorded_rounds(conn, sid, feature) if upgrade_round is None or r < upgrade_round]
            if upgrade_round == 1 and not rounds:
                continue
            if not rounds:
                out.append((sid, feature, upgrade_round, 0,
                            "Nothing recorded before the 4.0 update" if upgrade_round
                            else "Nothing recorded this season"))
            elif rounds[0] == 1:
                out.append((sid, feature, 1, 0, f"In use from round 1 ({len(rounds)} rounds)"))
            else:
                out.append((sid, feature, rounds[0], 1,
                            f"First in use at round {rounds[0]} ({len(rounds)} rounds): confirm when tracking began"))
    return out


def record_upgrade(conn, from_schema):
    """The one-time 4.0 record for a league last written by 3.x. Safe to call again: it never duplicates the
    migration, its season rows or its notice."""
    ensure_tables(conn)
    existing = conn.execute("SELECT * FROM tracking_migrations WHERE kind = ?", (KIND_40,)).fetchone()
    if existing:
        return existing["id"]
    year, rnd = _start_point(conn)
    audience = [r[0] for r in conn.execute("SELECT username FROM career_members ORDER BY username")] \
        if _has_table(conn, "career_members") else []
    stamp = now_iso()
    mid = conn.execute("""INSERT INTO tracking_migrations(kind, from_schema, migrated_at, start_year, start_round,
                          audience) VALUES(?,?,?,?,?,?)""",
                       (KIND_40, from_schema, stamp, year, rnd, json.dumps(audience))).lastrowid
    for sid, feature, from_round, review, detail in _plan(conn, year, rnd):
        conn.execute("""INSERT OR IGNORE INTO season_tracking(season_id, feature, from_round, review, source,
                        migration_id, detail, updated_at) VALUES(?,?,?,?,?,?,?,?)""",
                     (sid, feature, from_round, review, "upgrade" if FEATURES[feature][2] == "upgrade" else "records",
                      mid, detail, stamp))
    return mid


def migration(conn, kind=KIND_40):
    if not _has_table(conn, "tracking_migrations"):
        return None
    row = conn.execute("SELECT * FROM tracking_migrations WHERE kind = ?", (kind,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["audience"] = json.loads(out["audience"] or "[]")
    return out


# --------------------------------------------------------------------------- reading what was tracked

def _rows(conn, season_id):
    if not season_id or not _has_table(conn, "season_tracking"):
        return {}
    return {r["feature"]: dict(r) for r in conn.execute("SELECT * FROM season_tracking WHERE season_id = ?",
                                                         (season_id,))}


def tracked(conn, season_id, feature, round_number=None):
    """Was this feature tracked at that round (or, with no round, at any point in the season)?"""
    row = _rows(conn, season_id).get(feature)
    if not row:
        return True
    if row["from_round"] is None:
        return False
    return True if round_number is None else round_number >= row["from_round"]


def round_tracked(conn, event, feature):
    if not event:
        return True
    return tracked(conn, event["season_id"], feature, event["round_number"])


def empty_text(conn, event, feature):
    """What to show where a value is missing: a genuine gap, or something the season's rules never asked for."""
    return NOT_RECORDED if round_tracked(conn, event, feature) else NOT_TRACKED


def _season_name(year):
    return f"the {year} season"


def season_summary(conn, season):
    """None for a fully tracked season, else what a historical season page explains once (the banner)."""
    if not season:
        return None
    rows = _rows(conn, season["id"])
    if not rows:
        return None
    mig = migration(conn)
    started = []
    for feature, row in rows.items():
        label = FEATURES.get(feature, (feature,))[0]
        started.append({"feature": feature, "label": label, "from_round": row["from_round"],
                        "review": bool(row["review"]), "detail": row["detail"]})
    start = None
    if mig and mig["start_year"] is not None:
        if mig["start_year"] == season["year"] and mig["start_round"] > 1:
            start = f"Round {mig['start_round']} of this season"
        elif mig["start_year"] > season["year"]:
            start = _season_name(mig["start_year"])
    return {"features": started, "start": start, "migration": mig, "season": season,
            "review": [f for f in started if f["review"]]}


def tracked_since(conn, feature):
    """'Tracked since the 2027 season' / '... since Round 7 of the 2026 season', or None when always tracked."""
    if not _has_table(conn, "season_tracking"):
        return None
    late = conn.execute("""SELECT t.from_round, s.year FROM season_tracking t JOIN seasons s ON s.id = t.season_id
                           WHERE t.feature = ? AND (t.from_round IS NULL OR t.from_round > 1)
                           ORDER BY s.year DESC LIMIT 1""", (feature,)).fetchone()
    if not late:
        return None
    if late["from_round"] is not None:
        return f"Tracked since Round {late['from_round']} of {_season_name(late['year'])}"
    nxt = conn.execute("SELECT year FROM seasons WHERE year > ? ORDER BY year LIMIT 1", (late["year"],)).fetchone()
    mig = migration(conn)
    year = nxt["year"] if nxt else (mig["start_year"] if mig else None)
    return f"Tracked since {_season_name(year)}" if year else None


def eligible_rounds(conn, season_id, feature, completed_only=True):
    """Played rounds of a season where the feature was tracked (the denominator for any average or rate)."""
    rows = conn.execute("SELECT * FROM events WHERE season_id = ?" + (" AND status = ?" if completed_only else ""),
                        (season_id, C.EVENT_COMPLETE) if completed_only else (season_id,)).fetchall()
    return [dict(e) for e in rows if tracked(conn, season_id, feature, e["round_number"])]


def coverage(conn, season_id, feature, used_rounds):
    """A coverage line for a statistic: 'Based on 12 eligible rounds' (plus 'Tracked since ...' when it started late).
    used_rounds = how many rounds actually contributed a value."""
    parts = [f"Based on {used_rounds} eligible round{'s' if used_rounds != 1 else ''}"]
    since = tracked_since(conn, feature)
    if since:
        parts.append(since)
    return " · ".join(parts)


# --------------------------------------------------------------------------- the Race Master's review

def review_items(conn):
    if not _has_table(conn, "season_tracking"):
        return []
    return [dict(r) for r in conn.execute("""SELECT t.*, s.year, s.label FROM season_tracking t
                                             JOIN seasons s ON s.id = t.season_id WHERE t.review = 1
                                             ORDER BY s.year, t.feature""")]


def all_rows(conn):
    if not _has_table(conn, "season_tracking"):
        return []
    out = []
    for r in conn.execute("""SELECT t.*, s.year, s.label FROM season_tracking t JOIN seasons s ON s.id = t.season_id
                             ORDER BY s.year, t.feature"""):
        d = dict(r)
        d["label_feature"], d["since"], d["how"] = FEATURES.get(d["feature"], (d["feature"], "", ""))
        d["rounds"] = conn.execute("SELECT COUNT(*) FROM events WHERE season_id = ?", (d["season_id"],)).fetchone()[0]
        d["recorded"] = (_recorded_rounds(conn, d["season_id"], d["feature"]) if d["how"] == "records" else [])
        out.append(d)
    return out


def set_start(conn, season_id, feature, from_round, username):
    """Race Master: confirm when a feature was tracked in a season (None = not tracked that season). Only the
    tracking record changes; no result, number or stored value does. A start can't be put after a round that has
    data stored, so a recorded value is never relabelled as untracked."""
    from . import services as S
    if feature not in FEATURES:
        raise S.ValidationError("Unknown feature")
    if FEATURES[feature][2] != "records":
        raise S.ValidationError("4.0 tracking starts at the league's update and can't be moved earlier")
    row = _rows(conn, season_id).get(feature)
    if not row:
        raise S.ValidationError("That season has no legacy tracking record for this feature")
    rounds = conn.execute("SELECT MAX(round_number) FROM events WHERE season_id = ?", (season_id,)).fetchone()[0] or 0
    if from_round is not None and not 1 <= from_round <= max(rounds, 1):
        raise S.ValidationError(f"Choose a round from 1 to {rounds}")
    if FEATURES[feature][2] == "records":
        recorded = _recorded_rounds(conn, season_id, feature)
        if recorded and (from_round is None or from_round > recorded[0]):
            raise S.ValidationError(f"Round {recorded[0]} already has {FEATURES[feature][0].lower()} recorded, so "
                                    f"tracking began at round {recorded[0]} or earlier")
    conn.execute("""UPDATE season_tracking SET from_round = ?, review = 0, source = 'owner', updated_by = ?,
                    updated_at = ?, detail = ? WHERE season_id = ? AND feature = ?""",
                 (from_round, username, now_iso(),
                  f"Confirmed by the Race Master: {'from round ' + str(from_round) if from_round else 'not tracked'}",
                  season_id, feature))


# --------------------------------------------------------------------------- the one-time notice

def _calc_line(conn, mig):
    """A separate sentence about calculations, true to what happened at (or since) the upgrade."""
    if not _has_table(conn, "calc_migrations"):
        return None
    rows = conn.execute("""SELECT * FROM calc_migrations WHERE created_at >= ? AND rolled_back_at IS NULL
                           ORDER BY id""", (mig["migrated_at"],)).fetchall()
    if any(r["option"] == "full" for r in rows):
        return ("Separately, your Race Master chose to recalculate the current season with the latest calculations. "
                "What changed for your driver, with the numbers before and after, is on Changes to your driver.")
    future = [r for r in rows if r["option"] == "future"]
    if future:
        return (f"Your league also uses the latest calculations from round {future[-1]['cutoff_round'] + 1}. Everything "
                "calculated before that, including standings, contracts and next season's grid, is unchanged.")
    return "No results, standings or career outcomes were recalculated."


def _in_audience(mig, username, site_owner=False):
    """Members of the league at the upgrade, plus the site owner (Race Master of every league without a membership)."""
    return bool(username) and (site_owner or username in mig["audience"])


def notice_for(conn, username, site_owner=False):
    """The 4.0 notice this person hasn't acknowledged yet, or None. Only members of the league at the upgrade see
    it (a league created on 4.0 has no migration, so never shows it)."""
    mig = migration(conn)
    if not mig or not _in_audience(mig, username, site_owner):
        return None
    if conn.execute("SELECT 1 FROM tracking_notice_acks WHERE migration_id = ? AND username = ?",
                    (mig["id"], username)).fetchone():
        return None
    if mig["start_year"] is None:
        start = None
    elif mig["start_round"] > 1:
        start = f"Round {mig['start_round']} of {_season_name(mig['start_year'])}"
    else:
        start = _season_name(mig["start_year"])
    return {"migration": mig, "start": start, "calc": _calc_line(conn, mig), "review": len(review_items(conn))}


def acknowledge(conn, username, migration_id, site_owner=False):
    """Store "Got it" for this person and this migration. Returns False if there's nothing of theirs to acknowledge."""
    mig = migration(conn)
    if not mig or mig["id"] != migration_id or not _in_audience(mig, username, site_owner):
        return False
    conn.execute("INSERT OR IGNORE INTO tracking_notice_acks(migration_id, username, acked_at) VALUES(?,?,?)",
                 (migration_id, username, now_iso()))
    return True


def acknowledged(conn, migration_id):
    if not _has_table(conn, "tracking_notice_acks"):
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM tracking_notice_acks WHERE migration_id = ? ORDER BY acked_at",
                                          (migration_id,))]
