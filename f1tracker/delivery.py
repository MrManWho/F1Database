"""Deliver notifications made during a request: phone alerts and emails, per league, per preference.

Called once a request has been saved. For each notification it works out who in that league it is for, keeps
only the people whose preferences in that league want it on each channel, claims a dedupe key in the league's
delivery log (so a retry or a duplicate background job sends nothing twice), then sends in the background.
Nothing here ever looks at another league's members or preferences.
"""

import logging
import threading
from contextlib import closing

from itsdangerous import BadSignature, URLSafeSerializer

from . import auth, mailer, notices, push, storage

log = logging.getLogger(__name__)
_SALT = "paddock-legacy-unsubscribe"


def _serializer():
    return URLSafeSerializer(auth.secret_key(), salt=_SALT)


def unsubscribe_token(username, token):
    return _serializer().dumps({"u": username, "l": token})


def read_unsubscribe(sig):
    try:
        data = _serializer().loads(sig)
        return data["u"], data["l"]
    except (BadSignature, KeyError, TypeError):
        return None, None


def footer(league, base_url, username, token):
    """Every league email names the league and links to that league's own preferences."""
    manage = f"{base_url}/career/{token}/notifications"
    unsub = f"{base_url}/unsubscribe/{unsubscribe_token(username, token)}"
    text = (f"\n\n—\nSent by Paddock Legacy for the league \"{league}\".\n"
            f"Choose what {league} emails you about: {manage}\n"
            f"Stop all emails from {league}: {unsub}\n")
    html = (f"<hr style='border:0;border-top:1px solid #333;margin:18px 0'>"
            f"<p style='color:#8d97a8;font-size:12px'>Sent by Paddock Legacy for the league <b>{_esc(league)}</b>. "
            f"<a href='{_esc(manage)}' style='color:#8d97a8'>Choose what {_esc(league)} emails you about</a> · "
            f"<a href='{_esc(unsub)}' style='color:#8d97a8'>Stop all emails from {_esc(league)}</a></p>")
    return text, html


def _esc(s):
    from html import escape
    return escape(str(s))


def plan(items, exclude=None):
    """Work out and claim deliveries (synchronously, so tests and retries see the same log).
    items: dicts from feed.take_outbox(). Returns a list of sends: (channel, recipients, payload)."""
    sends = []
    by_league = {}
    for it in items:
        by_league.setdefault(it["token"], []).append(it)
    for token, league_items in by_league.items():
        try:
            conn = storage.open_db(token)
        except storage.CareerNotFound:
            continue
        with closing(conn):
            if storage.get_meta(conn, "demo") == "1":
                continue   # demo leagues never email or alert anyone
            league = notices.league_name(conn)
            for it in league_items:
                cat = it.get("category") or "career"
                people = [u for u in notices.audience(conn, cat, it.get("driver_id"), it.get("username")) if u != exclude]
                key = it.get("key") or notices.dedupe_key(cat, it.get("id") or it["text"], it.get("driver_id"),
                                                          it.get("username"))
                label = notices.CATEGORIES.get(cat, (cat,))[0]
                if push.available():
                    names = notices.wanted(conn, people, cat, "push")
                    if names and notices.claim(conn, key, cat, "push", label):
                        notices.record(conn, key, "push", len(names), "sent")
                        sends.append(("push", names, {"token": token, "text": it["text"], "link": it.get("link"),
                                                      "league": league}))
                if it.get("email", True) and mailer.configured():
                    to = notices.email_recipients(conn, people, cat)
                    if to and notices.claim(conn, key, cat, "email", label):
                        notices.record(conn, key, "email", len(to), "sent")
                        sends.append(("email", to, {"token": token, "text": it["text"], "link": it.get("link"),
                                                    "league": league, "category": label}))
            conn.commit()
    return sends


def send_email(conn, token, category, usernames, key, subject, text, html, base_url, label=""):
    """A league email with its own content (e.g. race results): same preference filter, dedupe and log."""
    if not mailer.configured() or storage.get_meta(conn, "demo") == "1":
        return 0
    to = notices.email_recipients(conn, usernames, category)
    if not to or not notices.claim(conn, key, category, "email", label or notices.CATEGORIES[category][0]):
        return 0
    notices.record(conn, key, "email", len(to), "sent")
    league = notices.league_name(conn)
    for username, address in to:
        ft, fh = footer(league, base_url, username, token)
        mailer.send_later([address], subject, text + ft, (html + fh) if html else None)
    return len(to)


def dispatch(items, base_url="", exclude=None, background=True):
    sends = plan(items, exclude)
    if not sends:
        return sends

    def run():
        for channel, names, p in sends:
            try:
                url = f"{base_url}/career/{p['token']}/{p['link']}" if p.get("link") else \
                    f"{base_url}/career/{p['token']}/dashboard"
                if channel == "push":
                    push.send(names, p["league"], p["text"], url)
                else:
                    for username, address in names:
                        ft, fh = footer(p["league"], base_url, username, p["token"])
                        body = f"{p['text']}\n\nOpen it: {url}"
                        mailer.send_later([address], f"[{p['league']}] {p['text'][:90]}", body + ft,
                                          f"<p>{_esc(p['text'])}</p><p><a href='{_esc(url)}'>Open it in Paddock Legacy →</a></p>" + fh)
            except Exception:
                log.exception("notification delivery failed")
    if background:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    return sends
