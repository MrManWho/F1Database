"""A league's public identity and visibility: description, region, platform, rules, schedule, links, accent,
and who can see it. Stored in the league's meta table. Nothing here is ever an email, password or secret.

Visibility (who can SEE the league) is separate from the join mode (who can JOIN it, storage.JOIN_MODES):
    private   members only; no public page
    public    anyone with the public link sees submitted results, standings, profiles, records and public news
    listed    as public, and shown in the league directory (only ever by an explicit Race Master choice)
Draft results, notes, emails, roles, backups, settings and admin pages are never public at any level.
Older leagues: the old "Public results page" switch becomes "public"; otherwise "private".
"""

import re
from urllib.parse import urlparse

from .services import ValidationError
from .storage import get_meta, set_meta

VISIBILITY = {
    "private": ("Private", "Only members can see anything in this league."),
    "public": ("Public results", "Anyone with the public link can see submitted results, standings, driver and team pages, "
                                 "records and public news."),
    "listed": ("Publicly discoverable", "Public, and listed in the league directory so people can find it."),
}
# How the five kinds of league people ask for map onto visibility + joining.
NAMED_LEVELS = [
    ("Private", "private", "closed"), ("Invite only", "private", "invite"), ("Public results only", "public", "invite"),
    ("Public and join requests enabled", "public", "requests"), ("Publicly discoverable", "listed", "requests"),
]
FIELDS = {"league_description": 600, "league_region": 60, "league_platform": 80, "league_rules": 1200,
          "league_schedule": 200}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def visibility(conn):
    value = get_meta(conn, "visibility")
    if value in VISIBILITY:
        return value
    return "public" if get_meta(conn, "feature_public") == "1" else "private"


def is_public(conn):
    return visibility(conn) in ("public", "listed")


def profile(conn):
    links = [l for l in (get_meta(conn, "league_links") or "").split("\n") if l.strip()]
    out = {k: get_meta(conn, k, "") for k in FIELDS}
    out.update(links=links, accent=get_meta(conn, "accent_color", "") or "", visibility=visibility(conn),
               public_incidents=get_meta(conn, "public_incidents", "0") == "1", name=get_meta(conn, "career_name", "League"))
    return out


def clean_link(url):
    url = (url or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or len(url) > 300:
        raise ValidationError("Links must be full https:// addresses (e.g. https://discord.gg/yourleague)")
    return url


def save(conn, form):
    """Save identity, branding and visibility fields from a settings form. Returns the fields that changed."""
    before = profile(conn)
    for key, limit in FIELDS.items():
        if key in form:
            set_meta(conn, key, (form.get(key) or "").strip()[:limit])
    if "league_links" in form:
        links = [clean_link(l) for l in form.getlist("league_links")]
        set_meta(conn, "league_links", "\n".join(l for l in links if l)[:1000])
    accent = (form.get("accent_color") or "").strip()
    if accent:
        if not HEX.match(accent):
            raise ValidationError("Choose the accent colour with the colour picker")
        set_meta(conn, "accent_color", accent.lower())
    if form.get("visibility") in VISIBILITY:
        set_meta(conn, "visibility", form.get("visibility"))
        set_meta(conn, "feature_public", "1" if form.get("visibility") != "private" else "0")
    if "visibility" in form:
        set_meta(conn, "public_incidents", "1" if form.get("public_incidents") else "0")
    after = profile(conn)
    return [k for k in after if after[k] != before[k]]


def named_level(vis, join_mode):
    for label, v, j in NAMED_LEVELS:
        if v == vis and j == join_mode:
            return label
    return f"{VISIBILITY[vis][0]}, {'join requests' if join_mode == 'requests' else join_mode.replace('_', ' ')}"
