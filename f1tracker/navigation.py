"""4.0.0-beta.13: where a form goes back to after it's sent.

A form can say where it was sent from (the hidden `return_to` field the page script adds, or an older `next`
field), and the browser also reports the page it came from (the Referer header). Neither is trusted as it is:
a destination is only used when it's a page of this site that can be opened with GET, never the API, a file,
the service worker, signing in or out, and never a page of a different league from the one the form changed.
When nothing usable was sent, each action falls back to a page that fits it (the round, the standalone page),
never to an unrelated Home.
"""

from urllib.parse import urlsplit

from flask import current_app, request

# Endpoints that are never somewhere to "go back" to: files, sign-in screens, one-off links and the API.
NEVER = {"static", "service_worker", "web_manifest", "healthz", "login", "login_code", "logout", "setup", "register",
         "register_verify", "register_resend", "forgot", "reset_password", "unsubscribe", "avatar",
         "must_change_password", "demo_start", "public_calendar_ics"}
MAX_LENGTH = 2000


def safe(target, token=None):
    """`target` as an internal path (with its query and #fragment) when it's somewhere safe to send this person
    back to; otherwise None. token: the league the action belonged to; pages of another league are refused."""
    if not target or not isinstance(target, str) or len(target) > MAX_LENGTH:
        return None
    target = target.strip()
    if "\\" in target or any(ord(ch) < 32 for ch in target):
        return None
    try:
        parts = urlsplit(target)
    except ValueError:
        return None
    if parts.scheme or parts.netloc:
        # The Referer header is a full address: only this site's own address is accepted.
        if parts.scheme not in ("http", "https") or parts.netloc != request.host:
            return None
    path = parts.path
    if not path.startswith("/") or path.startswith("//"):
        return None
    if path.startswith(("/api/", "/static/")):
        return None
    try:
        endpoint, args = current_app.url_map.bind(request.host).match(path, method="GET")
    except Exception:       # not a page (404), POST-only (405) or a redirect rule
        return None
    if endpoint in NEVER:
        return None
    if token is not None and "token" in args and args["token"] != token:
        return None
    out = path
    if parts.query:
        out += "?" + parts.query
    if parts.fragment:
        out += "#" + parts.fragment
    return out


def candidates():
    """What the request says about where it came from, most specific first."""
    form = request.form if request.method == "POST" else {}
    return [form.get("return_to"), form.get("next"), request.referrer]


def back(default, token=None, anchor=None, prefer=None):
    """Where to send someone after a form: `prefer` (an explicit destination the route chose), then the page the
    form was sent from, then `default`. anchor (e.g. "#target") replaces any #fragment on the page sent from."""
    for target in ([prefer] if prefer else []) + candidates():
        ok = safe(target, token)
        if ok:
            if anchor is not None:
                ok = ok.split("#")[0] + anchor
            return ok
    return default


def fallback(token=None, event_id=None):
    """A page that fits the action when the request says nothing usable about where it came from: the page the
    form posts to when that is also a page (e.g. an interview), the round for a race-weekend action, else the
    league's Home (or the site's Home outside a league)."""
    from flask import url_for
    args = request.view_args or {}
    token = token or args.get("token")
    event_id = event_id or args.get("event_id")
    same = safe(request.path, token)
    if same:
        return same
    if token and event_id:
        return url_for("weekend", token=token, event_id=event_id)
    if token:
        return url_for("dashboard", token=token)
    return url_for("home")
