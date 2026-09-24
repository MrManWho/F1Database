"""New-league presets and the rules for who may create a league.

A preset only chooses sensible starting settings; every one can be changed later in League settings.
"""

from datetime import datetime, timedelta

from . import auth
from .storage import now_iso

PRESETS = {
    "simple": {
        "label": "Simple results tracker",
        "blurb": "Results, standings, calendar, records and news. No contracts, market, targets or round gates.",
        "enables": ["Results & standings", "Records", "Comments"],
        "features": {"comments"}, "market": False, "targets": False, "gates": False, "orders": "off",
        "team_goals": False,
    },
    "multiplayer": {
        "label": "Multiplayer career league",
        "blurb": "Results plus careers: contracts and the transfer market, weekend targets, teammate battles and round gates.",
        "enables": ["Everything in Simple", "Rookie Draft & transfer market", "Weekend targets", "Round gates", "Predictions"],
        "features": {"comments", "predictions"}, "market": True, "targets": True, "gates": True, "orders": "off",
        "team_goals": False,
    },
    "full": {
        "label": "Full career simulation",
        "blurb": "Every system: market, pledges, press, targets, round gates, selectable team goals, race-night check-in "
                 "and advisory team orders.",
        "enables": ["Everything in Multiplayer", "Selectable team goals", "Race-night check-in", "Advisory team orders"],
        "features": {"comments", "predictions", "checkin"}, "market": True, "targets": True, "gates": True,
        "orders": "advisory", "team_goals": True,
    },
    "custom": {
        "label": "Custom",
        "blurb": "Start from Multiplayer and choose each system yourself on the next step.",
        "enables": ["Your choice"],
        "features": {"comments", "predictions"}, "market": True, "targets": True, "gates": True, "orders": "off",
        "team_goals": False,
    },
}
LEAGUES_PER_DAY = 5


def creation_policy():
    value = auth.get_setting("league_creation")
    return value if value in ("admins", "everyone") else "admins"


def may_create(user):
    if not user or user.get("is_demo"):
        return False
    return bool(user["is_master"]) or creation_policy() == "everyone"


def _table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS league_creations (username TEXT NOT NULL, created_at TEXT NOT NULL)")


def check_rate(username):
    """At most LEAGUES_PER_DAY new leagues per account per day (abuse protection for public sites)."""
    since = (datetime.fromisoformat(now_iso()) - timedelta(days=1)).isoformat(sep=" ")
    with auth.accounts() as conn:
        _table(conn)
        n = conn.execute("SELECT COUNT(*) FROM league_creations WHERE username = ? AND created_at >= ?",
                         (username, since)).fetchone()[0]
    if n >= LEAGUES_PER_DAY:
        raise auth.AuthError(f"You've created {n} leagues today. Try again tomorrow.")


def record_creation(username):
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("INSERT INTO league_creations(username, created_at) VALUES(?, ?)", (username, now_iso()))
