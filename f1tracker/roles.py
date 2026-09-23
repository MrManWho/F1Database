"""League access roles: the one authoritative place a person's permissions in a league come from.

Every league member has exactly one access role (career_members.role) and, separately, an optional player
driver (career_members.driver_id):

    race_master  runs this league (results, grid, calendar, seasons, market, members, settings)
    scorekeeper  enters and edits results until a round is submitted; nothing administrative
    member       views everything; with a driver, their own garage, contracts and team standing
    spectator    view only; can't have a driver

Site Race Masters (users.is_master, managed in Accounts) are Race Master of every league, as before.
Older versions also had an account-wide "Scorekeeper" switch (users.is_steward). It is migrated once into
the league role of every league that person belongs to, then cleared, so the two can never disagree.
"""

from contextlib import closing

from . import auth
from . import constants as C
from . import services as S
from . import storage
from .storage import now_iso


class RoleError(S.ValidationError):
    pass


def effective_role(conn, user):
    """This user's role in this league, or None if they aren't in it."""
    if not user:
        return None
    if user["is_master"]:
        return "race_master"
    row = conn.execute("SELECT role FROM career_members WHERE username = ?", (user["username"],)).fetchone()
    if not row:
        return None
    return row["role"] if row["role"] in C.ACCESS_ROLES else "member"


def can_enter_results(role):
    return role in C.RESULT_ROLES


def members(conn):
    """Everyone in the league, with their login details, role and driver."""
    users = {u["username"]: u for u in auth.list_users()}
    dmap = S.driver_map(conn)
    out = []
    for r in conn.execute("SELECT * FROM career_members ORDER BY username"):
        r = dict(r)
        u = users.get(r["username"])
        r["user"] = u
        r["display_name"] = u["display_name"] if u else r["username"]
        r["site_master"] = bool(u and u["is_master"])
        r["role"] = "race_master" if r["site_master"] else (r["role"] if r["role"] in C.ACCESS_ROLES else "member")
        r["driver"] = dmap.get(r["driver_id"])
        out.append(r)
    order = list(C.ACCESS_ROLES)
    out.sort(key=lambda r: (order.index(r["role"]), r["display_name"].lower()))
    return out


def race_master_count(conn, excluding=None):
    """Race Masters who can run this league: every site Race Master plus league Race Masters."""
    site = {u["username"] for u in auth.list_users() if u["is_master"]}
    league = {r["username"] for r in conn.execute("SELECT username FROM career_members WHERE role = 'race_master'")}
    return len((site | league) - {excluding})


def _check_driver(conn, username, driver_id):
    if driver_id is None:
        return None
    driver = S.driver_map(conn).get(driver_id)
    if not driver or not driver["is_player"]:
        raise RoleError("Only player drivers can be assigned to a member")
    taken = conn.execute("SELECT username FROM career_members WHERE driver_id = ? AND username != ?",
                         (driver_id, username)).fetchone()
    if taken:
        raise RoleError(f"{driver['name']} is already assigned to {taken['username']}")
    return driver_id


def set_member(conn, username, role, driver_id=None):
    """Add someone to the league or change their role/driver. Validates everything; applies at once."""
    user = auth.get_user(username)
    if not user:
        raise RoleError("Unknown login")
    if role not in C.ACCESS_ROLES:
        raise RoleError("Choose a role")
    if role == "spectator" and driver_id is not None:
        raise RoleError("Spectators can't have a driver. Make them a Member (or Scorekeeper) to assign one.")
    if user["is_master"] and role != "race_master":
        raise RoleError(f"{user['display_name']} is a site Race Master. Change that in Accounts.")
    current = conn.execute("SELECT * FROM career_members WHERE username = ?", (user["username"],)).fetchone()
    if current and current["role"] == "race_master" and role != "race_master" and \
            race_master_count(conn, excluding=user["username"]) == 0:
        raise RoleError("A league needs at least one Race Master")
    driver_id = _check_driver(conn, user["username"], driver_id)
    if current:
        conn.execute("UPDATE career_members SET role = ?, driver_id = ?, scorekeeper = ? WHERE username = ?",
                     (role, driver_id, int(role == "scorekeeper"), user["username"]))
    else:
        conn.execute("INSERT INTO career_members(username, driver_id, scorekeeper, role, joined_at) VALUES(?,?,?,?,?)",
                     (user["username"], driver_id, int(role == "scorekeeper"), role, now_iso()))
    return user


def remove_member(conn, username):
    row = conn.execute("SELECT * FROM career_members WHERE username = ?", (username,)).fetchone()
    if not row:
        raise RoleError("That person isn't in this league")
    if row["role"] == "race_master" and race_master_count(conn, excluding=username) == 0:
        raise RoleError("A league needs at least one Race Master")
    conn.execute("DELETE FROM career_members WHERE username = ?", (username,))


def touch(conn, username):
    """Record when a member last opened the league (at most every few minutes)."""
    row = conn.execute("SELECT last_active FROM career_members WHERE username = ?", (username,)).fetchone()
    now = now_iso()
    if row and (not row["last_active"] or row["last_active"][:15] != now[:15]):  # ten-minute resolution
        conn.execute("UPDATE career_members SET last_active = ? WHERE username = ?", (now, username))


def join_role(requested):
    """A join request's role (see C.LEAGUE_ROLES) as an access role plus whether it comes with a driver."""
    return {"driver": ("member", True), "driver_scorekeeper": ("scorekeeper", True),
            "scorekeeper": ("scorekeeper", False), "spectator": ("spectator", False)}.get(requested, ("member", True))


# --------------------------------------------------------------------------- one-off migration

def unify_legacy_scorekeepers():
    """Move the old account-wide Scorekeeper switch into each league the person belongs to, then clear it.

    Nobody loses access: every league membership of a legacy Scorekeeper becomes the Scorekeeper role
    (their assigned driver is kept). Safe to run any number of times.
    """
    with auth.accounts() as conn:
        legacy = [r["username"] for r in conn.execute("SELECT username FROM users WHERE is_steward = 1 AND is_master = 0")]
    if not legacy:
        return 0
    moved = 0
    for career in storage.list_careers():
        try:
            with storage.session(career["token"]) as conn:
                for username in legacy:
                    cur = conn.execute("UPDATE career_members SET role = 'scorekeeper', scorekeeper = 1 "
                                       "WHERE username = ? AND role IN ('member', 'spectator')", (username,))
                    moved += cur.rowcount
        except storage.CareerNotFound:
            continue
    with auth.accounts() as conn:
        conn.execute("UPDATE users SET is_steward = 0 WHERE is_steward = 1")
    return moved
