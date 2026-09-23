"""Outgoing email over SMTP: password resets and race-result emails.

Configure with environment variables (best on a host like Render) or in Accounts > Settings:
SMTP_HOST, SMTP_PORT (587 STARTTLS or 465 SSL), SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM.
Emails are sent on a background thread so a slow mail server never holds up a page.
"""

import logging
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr

from . import auth

log = logging.getLogger(__name__)
FIELDS = ["smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from"]


class MailError(RuntimeError):
    pass


def config():
    cfg = {}
    for field in FIELDS:
        cfg[field] = (auth.get_setting(field) or os.environ.get(field.upper()) or "").strip()
    cfg["smtp_port"] = int(cfg["smtp_port"] or 587)
    cfg["smtp_from"] = cfg["smtp_from"] or cfg["smtp_username"]
    return cfg


def configured():
    cfg = config()
    return bool(cfg["smtp_host"] and cfg["smtp_from"])


def send(recipients, subject, text, html=None):
    """Send one message to each recipient (so addresses aren't shared). Raises MailError."""
    recipients = [r for r in dict.fromkeys(recipients) if r]
    if not recipients:
        return 0
    cfg = config()
    if not configured():
        raise MailError("Email isn't set up yet (Accounts > Settings > Email).")
    try:
        if cfg["smtp_port"] == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_host"], 465, context=ssl.create_default_context(), timeout=20)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=20)
            server.starttls(context=ssl.create_default_context())
        with server:
            if cfg["smtp_username"]:
                server.login(cfg["smtp_username"], cfg["smtp_password"])
            for to in recipients:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = formataddr(("F1 Universe Tracker", cfg["smtp_from"]))
                msg["To"] = to
                msg.set_content(text)
                if html:
                    msg.add_alternative(html, subtype="html")
                server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Couldn't send email: {exc}") from exc
    return len(recipients)


def send_later(recipients, subject, text, html=None):
    """Fire-and-forget version for use inside requests."""
    if not recipients or not configured():
        return False

    def run():
        try:
            send(recipients, subject, text, html)
        except MailError:
            log.exception("email failed")
    threading.Thread(target=run, daemon=True).start()
    return True
