"""Optional Discord posts for a league: race results and paddock headlines, sent to a channel webhook.

Off unless the Race Master pastes a webhook URL in League settings. Private things (garages, offers,
team warnings) are never posted. Sending happens in the background and failures are only logged.
"""

import json
import logging
import re
import threading
import urllib.request

from . import constants as C
from . import services as S
from .storage import get_meta, set_meta

log = logging.getLogger(__name__)
WEBHOOK_RE = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
_outbox = threading.local()


def settings(conn):
    return {"url": get_meta(conn, "discord_webhook") or "",
            "results": get_meta(conn, "discord_results", "1") == "1",
            "news": get_meta(conn, "discord_news", "1") == "1"}


def save_settings(conn, url, results, news):
    url = (url or "").strip()
    if url and not WEBHOOK_RE.match(url):
        raise S.ValidationError("That doesn't look like a Discord webhook URL (Channel settings → Integrations → Webhooks → Copy URL)")
    set_meta(conn, "discord_webhook", url)
    set_meta(conn, "discord_results", "1" if results else "0")
    set_meta(conn, "discord_news", "1" if news else "0")


def post(url, content):
    body = json.dumps({"content": content[:1990], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "PaddockLegacy"})
    with urllib.request.urlopen(req, timeout=10) as res:  # noqa: S310 - URL validated against Discord's host
        return 200 <= res.status < 300


def send_later(url, messages):
    if not url or not messages:
        return

    def run():
        for m in messages:
            try:
                post(url, m)
            except Exception as exc:  # never break the site over Discord
                log.warning("Discord post failed: %s", exc)

    threading.Thread(target=run, daemon=True).start()


def results_message(conn, event_id, league):
    event = S.get_event(conn, event_id)
    rows = S.weekend_rows(conn, event_id)
    finished = sorted((r for r in rows if r["race_position"] and r["result_status"] == C.STATUS_FINISHED),
                      key=lambda r: r["race_position"])
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏁 **{league} · R{event['round_number']} {event['name']}**"]
    for i, r in enumerate(finished[:3]):
        lines.append(f"{medals[i]} {r['driver']['name']} ({r['team']['name']})")
    players = [r for r in rows if r["driver"]["is_player"]]
    if players:
        lines.append("")
        for r in players:
            res = f"P{r['race_position']}" if r["result_status"] == C.STATUS_FINISHED and r["race_position"] else r["result_status"]
            grid = f" from P{r['qualifying_position']}" if r["qualifying_position"] else ""
            lines.append(f"• **{r['driver']['name']}**: {res}{grid}, {r['gp_points'] + r['sprint_pts']} pts")
    table = S.driver_standings(conn, event["season_id"])[:5]
    if table:
        lines.append("")
        lines.append("Championship: " + " · ".join(f"{t['position']}. {t['driver']['name']} {t['points']}" for t in table))
    return "\n".join(lines)


# News headlines made during a request are queued, then sent once the request has saved.
def queue_news(token, headline, body):
    if not hasattr(_outbox, "items"):
        _outbox.items = []
    _outbox.items.append((token, f"📰 **{headline}**" + (f"\n{body}" if body else "")))


def take():
    items = getattr(_outbox, "items", [])
    _outbox.items = []
    return items
