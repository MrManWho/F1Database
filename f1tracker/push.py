"""Phone and desktop alerts (Web Push). Optional: without the pywebpush package, or on a site that isn't
served over HTTPS, everything here quietly does nothing and the in-app bell still works."""

import base64
import json
import logging
import threading
import time
from contextlib import closing

from . import auth, storage

log = logging.getLogger(__name__)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def available():
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False
    return True


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
        endpoint TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        created_at TEXT NOT NULL)""")


def vapid_keys():
    """(private, public) — made once and kept in the site settings."""
    private, public = auth.get_setting("vapid_private"), auth.get_setting("vapid_public")
    if private and public:
        return private, public
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint))
    auth.set_setting("vapid_private", private)
    auth.set_setting("vapid_public", public)
    return private, public


def public_key():
    return vapid_keys()[1] if available() else None


def subscribe(username, sub):
    try:
        endpoint = sub["endpoint"]
        p256dh, secret = sub["keys"]["p256dh"], sub["keys"]["auth"]
    except (KeyError, TypeError) as exc:
        raise ValueError("That browser sent an incomplete subscription") from exc
    if not str(endpoint).startswith("https://"):
        raise ValueError("That browser sent an invalid subscription")
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("""INSERT INTO push_subscriptions(endpoint, username, p256dh, auth, created_at) VALUES(?,?,?,?,?)
                        ON CONFLICT(endpoint) DO UPDATE SET username = excluded.username, p256dh = excluded.p256dh,
                        auth = excluded.auth""", (endpoint, username, p256dh, secret, storage.now_iso()))


def unsubscribe(endpoint, username=None):
    with auth.accounts() as conn:
        _table(conn)
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?" + (" AND username = ?" if username else ""),
                     (endpoint, username) if username else (endpoint,))


def subscriptions(usernames):
    if not usernames:
        return []
    with auth.accounts() as conn:
        _table(conn)
        marks = ",".join("?" * len(usernames))
        return [dict(r) for r in conn.execute(f"SELECT * FROM push_subscriptions WHERE username IN ({marks})",
                                              list(usernames))]


def device_count(username):
    return len(subscriptions([username]))


def send(usernames, title, body, url=None):
    """Deliver to every device these people turned alerts on for. Returns how many were delivered."""
    if not available():
        return 0
    from pywebpush import WebPushException, webpush
    private, _ = vapid_keys()
    from . import mailer
    contact = mailer.config()["smtp_from"] or "admin@example.com"
    if "@" in contact and not contact.startswith("mailto:"):
        contact = "mailto:" + contact.split("<")[-1].strip(" >")
    sent = 0
    payload = json.dumps({"title": title, "body": body, "url": url or "/"})
    for sub in subscriptions(sorted(set(usernames))):
        try:
            webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    payload, vapid_private_key=private, vapid_claims={"sub": contact}, ttl=12 * 3600, timeout=10)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):  # the browser dropped this subscription
                unsubscribe(sub["endpoint"])
            else:
                log.warning("push failed: %s", exc)
        except Exception:  # never let one bad endpoint stop the rest
            log.exception("push failed")
    return sent


def recipients(token, driver_id):
    """Who should hear about a notification: that driver's login, or everyone in the league."""
    with closing(storage.open_db(token)) as conn:
        rows = conn.execute("SELECT username, driver_id FROM career_members").fetchall()
    if driver_id is None:
        names = {r["username"] for r in rows}
        names |= {u["username"] for u in auth.list_users() if u["is_master"]}
    else:
        names = {r["username"] for r in rows if r["driver_id"] == driver_id}
    return names


def dispatch(items, base_url="", exclude=None):
    """Send queued notifications in the background: items are (token, driver_id, text, link)."""
    if not items or not available():
        return

    def run():
        time.sleep(0.2)  # let the request's own commit settle
        for token, driver_id, text, link in items:
            try:
                names = recipients(token, driver_id) - {exclude}
                url = f"{base_url}/career/{token}/{link}" if link else f"{base_url}/career/{token}/dashboard"
                send(names, "Paddock Legacy", text, url)
            except Exception:
                log.exception("push dispatch failed")

    threading.Thread(target=run, daemon=True).start()
