"""Each account's own list of leagues: which they belong to, pinned favourites, order, and ones hidden from their
list. This is personal (accounts.db table user_leagues) and never changes anything inside a league."""

from . import auth, storage
from . import constants as C


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS user_leagues (
        username TEXT NOT NULL,
        token TEXT NOT NULL,
        pinned INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0,
        hidden INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (username, token))""")


def _prefs(username):
    with auth.accounts() as conn:
        _table(conn)
        return {r["token"]: dict(r) for r in conn.execute("SELECT * FROM user_leagues WHERE username = ?", (username,))}


def _set(username, token, **values):
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("INSERT OR IGNORE INTO user_leagues(username, token) VALUES(?, ?)", (username, token))
        for key, value in values.items():
            if key in ("pinned", "position", "hidden"):
                conn.execute(f"UPDATE user_leagues SET {key} = ? WHERE username = ? AND token = ?", (value, username, token))


def initials(name):
    words = [w for w in (name or "?").replace("-", " ").split() if w[:1].isalnum()]
    return ("".join(w[0] for w in words[:2]) or (name or "?")[:2]).upper()


def user_leagues(user, careers=None, include_hidden=False):
    """The leagues this person is a member of, favourites first. Site admins also see leagues they aren't in,
    marked as such, at the end (they can open them but get no notifications from them)."""
    if not user:
        return []
    careers = careers if careers is not None else storage.list_careers()
    prefs = _prefs(user["username"])
    out = []
    for c in careers:
        member = c["roles"].get(user["username"])
        if not member and (not user["is_master"] or c.get("demo")):
            continue
        p = prefs.get(c["token"], {})
        role = "race_master" if user["is_master"] and not member else (member or {}).get("role", "member")
        out.append({"token": c["token"], "name": c["name"], "initials": initials(c["name"]), "year": c["year"],
                    "role": role, "role_label": C.ACCESS_ROLES.get(role, "Member"), "member": bool(member),
                    "muted": user["username"] in c.get("muted", []), "pinned": bool(p.get("pinned")),
                    "hidden": bool(p.get("hidden")), "position": p.get("position", 0),
                    "pending": len(c.get("pending_requests", [])) if role == "race_master" else 0,
                    "accent": c.get("accent") or "", "last_opened": c.get("last_opened") or ""})
    if not include_hidden:
        out = [l for l in out if not l["hidden"]]
    out.sort(key=lambda l: (not l["member"], not l["pinned"], l["position"], l["name"].lower()))
    return out


def pin(username, token, on=True):
    _set(username, token, pinned=int(bool(on)))


def hide(username, token, on=True):
    """Archive a league from this person's own list. The league and their membership are unchanged."""
    _set(username, token, hidden=int(bool(on)))


def move(username, token, direction, leagues):
    """Swap a league with its neighbour in this person's list (direction -1 up, +1 down)."""
    order = [l["token"] for l in leagues]
    if token not in order:
        return
    i = order.index(token)
    j = i + (1 if direction > 0 else -1)
    if not 0 <= j < len(order):
        return
    order[i], order[j] = order[j], order[i]
    for pos, t in enumerate(order):
        _set(username, t, position=pos)
