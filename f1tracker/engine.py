"""Which calculation engine applies (v2.5).

Engine 2 is every formula as of 2.4.1; engine 3 is the 2.5 rules (calc3.py). The engine is chosen per season:

  * a league created in 2.5 or later starts on engine 3 (meta calc_engine = 3);
  * a league that existed before 2.5 stays on engine 2 until its Race Master answers the Calculation Update
    (meta calc_choice: pending -> later / full / future). Nothing ever switches by itself;
  * "full" recalculates the active season from round 1 on engine 3; "future" keeps every completed round as it was
    and applies engine 3 from the next round (season_calc.cutoff_round = the last completed round);
  * completed seasons keep the engine they were played under (season_calc rows written at migration);
  * a season with no season_calc row uses the league's engine.

Within a "future" season, a round is judged by engine 3 only if its round number is after the cutoff, and the
season-long numbers (Form, Reputation, Driver Value, relationship, interest, car strength) start from the frozen
values at the cutoff and move toward the engine 3 values over ENGINE_BLEND_ROUNDS rounds (blend_weight).
"""

import json
import math

from . import constants as C


def _meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def league_engine(conn):
    try:
        return int(_meta(conn, "calc_engine", C.ENGINE_LEGACY))
    except (TypeError, ValueError):
        return C.ENGINE_LEGACY


def choice(conn):
    """new (created on engine 3) / pending (never answered) / later / full / future."""
    value = _meta(conn, "calc_choice")
    if value:
        return value
    return "new" if league_engine(conn) >= C.ENGINE_CURRENT else "pending"


def needs_choice(conn):
    return league_engine(conn) < C.ENGINE_CURRENT and choice(conn) in ("pending", "later")


def _row(conn, season_id):
    try:
        return conn.execute("SELECT * FROM season_calc WHERE season_id = ?", (season_id,)).fetchone()
    except Exception:
        return None


def season_engine(conn, season_id):
    row = _row(conn, season_id) if season_id else None
    return int(row["engine"]) if row else league_engine(conn)


def is_v3(conn, season_id):
    return season_engine(conn, season_id) >= C.ENGINE_CURRENT


def cutoff(conn, season_id):
    row = _row(conn, season_id)
    return int(row["cutoff_round"] or 0) if row and int(row["engine"]) >= C.ENGINE_CURRENT else 0


def mixed(conn, season_id):
    return is_v3(conn, season_id) and cutoff(conn, season_id) > 0


def round_v3(conn, event):
    """This round is judged by engine 3 (its season is on engine 3 and it comes after any Future-only cutoff)."""
    if not event:
        return False
    return is_v3(conn, event["season_id"]) and event["round_number"] > cutoff(conn, event["season_id"])


def frozen(conn, season_id):
    row = _row(conn, season_id)
    if not row or not row["frozen"]:
        return {}
    try:
        return json.loads(row["frozen"])
    except ValueError:
        return {}


def rounds_after_cutoff(conn, season_id):
    cut = cutoff(conn, season_id)
    return conn.execute("SELECT COUNT(*) FROM events WHERE season_id = ? AND status = ? AND round_number > ?",
                        (season_id, C.EVENT_COMPLETE, cut)).fetchone()[0]


def blend_weight(conn, season_id):
    """Future-only seasons: how far the engine 3 numbers have taken over from the frozen ones (0..1)."""
    if not mixed(conn, season_id):
        return 1.0
    return min(1.0, rounds_after_cutoff(conn, season_id) / C.ENGINE_BLEND_ROUNDS)


def blend(frozen_value, new_value, weight):
    if frozen_value is None or new_value is None:
        return new_value
    return frozen_value + weight * (new_value - frozen_value)


def set_season(conn, season_id, engine, cutoff_round=0, frozen_values=None, migration_id=None):
    from .storage import now_iso
    conn.execute("""INSERT INTO season_calc(season_id, engine, cutoff_round, frozen, migration_id, updated_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(season_id) DO UPDATE SET engine = excluded.engine,
                    cutoff_round = excluded.cutoff_round, frozen = excluded.frozen, migration_id = excluded.migration_id,
                    updated_at = excluded.updated_at""",
                 (season_id, engine, cutoff_round, json.dumps(frozen_values) if frozen_values else None, migration_id,
                  now_iso()))


def set_league(conn, engine, choice_value):
    for key, value in (("calc_engine", str(engine)), ("calc_choice", choice_value)):
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, value))


def label(conn, season_id):
    """What the league shows: "Calculation Version 3", with the cutoff for a mixed season."""
    engine = season_engine(conn, season_id)
    text = f"Calculation Version {engine}"
    cut = cutoff(conn, season_id)
    if engine >= C.ENGINE_CURRENT and cut:
        text += f" from round {cut + 1} (rounds 1–{cut} as calculated under Version 2)"
    return text


# --------------------------------------------------------------------------- explicit rounding (engine 3)

def round_half_up(value, digits=0):
    """Ordinary rounding with halves always going up (2.5 -> 3, 12.5 -> 13), never Python's round-half-to-even.
    Negative halves go away from zero (-2.5 -> -3), so a penalty is never quietly softened."""
    if value is None:
        return None
    factor = 10 ** digits
    scaled = abs(value) * factor
    rounded = math.floor(scaled + 0.5 + 1e-9)
    result = math.copysign(rounded / factor, value)
    return int(result) if digits == 0 else result


def ceil_int(value):
    """Minimum requirements round up."""
    return int(math.ceil(value - 1e-9))


def floor_int(value):
    """Only where a target is intentionally made easier."""
    return int(math.floor(value + 1e-9))
