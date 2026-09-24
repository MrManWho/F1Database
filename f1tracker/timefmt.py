"""Friendly, consistent dates and times in the league's own time zone.

Two kinds of stored times exist:
  * race times (events.race_at) are UTC with an offset, e.g. "2026-09-23T15:30+00:00";
  * everything else (now_iso) is the server's local time without an offset, e.g. "2026-09-23 15:30:00".
Both are converted to the league's configured time zone (League Settings) before display.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "UTC"

# The zones offered in League Settings (any valid IANA name also works).
COMMON_ZONES = [
    "Pacific/Honolulu", "America/Anchorage", "America/Los_Angeles", "America/Denver", "America/Phoenix",
    "America/Chicago", "America/New_York", "America/Halifax", "America/Sao_Paulo", "UTC", "Europe/London",
    "Europe/Dublin", "Europe/Lisbon", "Europe/Paris", "Europe/Berlin", "Europe/Madrid", "Europe/Rome",
    "Europe/Amsterdam", "Europe/Warsaw", "Europe/Athens", "Europe/Helsinki", "Europe/Istanbul", "Africa/Johannesburg",
    "Asia/Dubai", "Asia/Kolkata", "Asia/Singapore", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
    "Australia/Perth", "Australia/Adelaide", "Australia/Sydney", "Pacific/Auckland",
]


def zone(name):
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def valid_zone(name):
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def parse(value):
    """A stored time (either kind) as an aware datetime, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = the server's local clock
    return dt


def local(value, tz):
    dt = parse(value)
    return dt.astimezone(zone(tz) if isinstance(tz, (str, type(None))) else tz) if dt else None


def _clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def race(value, tz):
    """Wed, Sep 23 · 11:30 AM"""
    dt = local(value, tz)
    return f"{dt:%a}, {dt:%b} {dt.day} · {_clock(dt)}" if dt else ""


def race_at(value, tz):
    """Wed, Sep 23 at 11:30 AM (for "Lights out ..." sentences)"""
    dt = local(value, tz)
    return f"{dt:%a}, {dt:%b} {dt.day} at {_clock(dt)}" if dt else ""


def stamp(value, tz):
    """Sep 22, 2026 · 10:26 PM"""
    dt = local(value, tz)
    return f"{dt:%b} {dt.day}, {dt.year} · {_clock(dt)}" if dt else ""


def day(value, tz):
    """Sep 22, 2026"""
    dt = local(value, tz)
    return f"{dt:%b} {dt.day}, {dt.year}" if dt else ""


def ago(value, tz, now=None):
    """3 hours ago; older than a week falls back to the date and time."""
    dt = parse(value)
    if not dt:
        return ""
    now = now or datetime.now(timezone.utc)
    seconds = (now - dt).total_seconds()
    if seconds < 0:
        return stamp(value, tz)
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = int(seconds // size)
            if unit == "day" and n > 7:
                return stamp(value, tz)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def countdown(value, now=None):
    """Starts in 9h 56m (whole minutes, no seconds); None once the time has passed."""
    dt = parse(value)
    if not dt:
        return None
    left = int((dt - (now or datetime.now(timezone.utc))).total_seconds())
    if left <= 0:
        return None
    days, rem = divmod(left, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"Starts in {days}d {hours}h"
    if hours:
        return f"Starts in {hours}h {minutes}m"
    return f"Starts in {max(minutes, 1)}m"


DEFAULT_RACE_WINDOW = 180  # minutes after the scheduled start that count as "race window open"
RACE_WINDOW_CHOICES = [60, 120, 180, 240, 360]


STARTING_SOON = 30        # minutes before the start that count as "Starting soon"
SCHEDULED_AHEAD = 7 * 24 * 60   # further away than this is just "Scheduled"


def race_status(value, event_status, window=DEFAULT_RACE_WINDOW, now=None, postponed=False):
    """(code, label) for a round, from its scheduled time and real status. Never completes anything by itself.

    unscheduled "Not scheduled"      no race time yet
    postponed   "Postponed"          the Race Master marked it postponed
    scheduled   "Scheduled"          more than a week away
    upcoming    "Starts in 2h 15m"   within a week
    soon        "Starting soon"      within 30 minutes
    live        "In progress"        from the start until `window` minutes later
    pending     "Results pending"    after that, until the round is submitted
    complete    "Completed"          only once the round has been submitted
    """
    if event_status == "Complete":
        return "complete", "Completed"
    if postponed:
        return "postponed", "Postponed"
    dt = parse(value)
    if not dt:
        return "unscheduled", "Not scheduled"
    now = now or datetime.now(timezone.utc)
    minutes = (dt - now).total_seconds() / 60
    if minutes > SCHEDULED_AHEAD:
        return "scheduled", "Scheduled"
    if minutes > STARTING_SOON:
        return "upcoming", countdown(value, now)
    if minutes > 0:
        return "soon", "Starting soon"
    if -minutes <= (window or DEFAULT_RACE_WINDOW):
        return "live", "In progress"
    return "pending", "Results pending"


def zone_label(value, tz):
    """Short time-zone name at that moment, e.g. EDT (falls back to the zone's name)."""
    dt = local(value, tz)
    if not dt:
        return ""
    abbr = dt.strftime("%Z")
    return abbr if abbr and not abbr.startswith(("+", "-")) else str(tz).replace("_", " ")


def input_value(value, tz):
    """The value for a datetime-local input, in the league's time zone."""
    dt = local(value, tz)
    return dt.strftime("%Y-%m-%dT%H:%M") if dt else ""


def from_input(value, tz):
    """A datetime-local value typed in the league's time zone -> stored UTC string."""
    value = (value or "").strip()
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone(tz))
    return dt.astimezone(timezone.utc).isoformat(timespec="minutes")


def month_grid(events, tz):
    """Months that contain scheduled races, as week rows (Monday first) of day cells with that day's races."""
    import calendar
    by_day = {}
    for e in events:
        dt = local(e.get("race_at"), tz)
        if dt:
            by_day.setdefault(dt.date(), []).append({**e, "local": dt})
    months = sorted({(d.year, d.month) for d in by_day})
    out = []
    for year, month in months:
        weeks = []
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
            weeks.append([{"date": d, "in_month": d.month == month, "races": by_day.get(d, [])} for d in week])
        out.append({"label": datetime(year, month, 1).strftime("%B %Y"), "weeks": weeks})
    return out
