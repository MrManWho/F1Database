"""Flask application: pages, mutation routes, logins and access control."""

import hmac
from datetime import timezone
import io
import os
import secrets
import sys
import sqlite3
import tempfile
import time
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   session, url_for)

import random

from . import (auth, community, discord, feed, insights, mailer, market, push, relations, roles,
               services as S, storage, teamlife, timefmt)
from . import (battle, circuits, delivery, demo, gates, league_profile, library, moderation, notices, onboarding,
               ratelimit, seats, security, teamgoals)
from . import announcements, impacts, stats, ultimatums
from . import constants as C
from .auth import AuthError
from .services import ValidationError
from .storage import CareerNotFound


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


PUBLIC_ENDPOINTS = {"login", "setup", "static", "register", "register_verify", "register_resend", "forgot",
                    "reset_password", "login_code", "privacy_page", "terms_page", "public_page", "public_calendar", "public_calendar_ics", "public_standings", "public_round",
                    "public_driver", "public_team", "public_records", "public_news", "public_incidents", "service_worker", "web_manifest", "avatar", "unsubscribe",
                    "home", "directory", "report_league", "help_page", "changelog_page", "demo_start"}

# What the Race Master's activity log calls each action (endpoints not listed are logged by name).
AUDIT_LABELS = {
    "grid_players": "Placed player drivers", "grid_save": "Saved the grid", "contracts_page": "Logged a negotiation",
    "contract_delete": "Deleted a negotiation", "season_switch": "Switched season", "season_new": "Started a new season",
    "calendar_save": "Edited the calendar", "market_open": "Opened a transfer window",
    "market_close": "Closed a transfer window", "market_delete": "Deleted a transfer window",
    "news_delete": "Deleted a news story", "notification_delete": "Deleted a notification",
    "offer_accept": "Accepted an offer", "offer_decline": "Declined an offer", "offer_counter": "Made a counter-offer",
    "market_approach": "Approached a team", "paddock_driver": "Edited a driver", "paddock_driver_delete": "Deleted a driver",
    "paddock_team": "Edited a team", "paddock_cars": "Changed car ratings", "paddock_recalculate": "Recalculated reputation",
    "calendar_add": "Added a race", "calendar_delete": "Removed a race", "members": "Changed league members",
    "members_add_player": "Added a player driver", "member_add": "Added a league member",
    "member_update": "Changed a member's role or driver", "member_remove": "Removed a league member", "members_request": "Answered a join request",
    "member_invite_cancel": "Cancelled an invitation",
    "members_settings": "Changed joining", "offers_send": "Sent offers", "league_settings": "Changed league settings",
    "public_rotate": "Made a new public link", "discord_test": "Sent a Discord test message",
    "incident_report": "Reported an incident", "incident_rule": "Ruled on an incident",
    "incident_delete": "Deleted an incident report", "paddock_move_results": "Moved results between drivers", "weekend_reopen": "Reopened a submitted round", "request_pledge": "Asked for a new growth pledge",
    "pledge_save": "Chose a growth pledge", "press_answer": "Answered the press", "race_time": "Set a race time", "profile_save": "Edited a driver profile",
    "profile_avatar": "Changed a driver photo", "comment_delete": "Deleted a comment",
    "target_ack": "Accepted a weekend target", "gate_bypass": "Opened a round early", "gate_remind": "Sent a round reminder",
    "target_excuse": "Changed a weekend target ruling", "seat_resolve": "Changed a seat or contract",
    "ownership_transfer": "Handed over the league", "league_leave": "Left the league", "notify_prefs": "Changed their notifications",
}
QUIET_ENDPOINTS = {"view_mode", "league_pin", "league_order", "league_leave", "timezone_detect", "notifications_read", "notifications_clear", "checkin", "comment_add", "react", "fan_vote_route", "prediction_save",
                   "save_now"}


def create_app(config=None):
    base = _base_dir()
    app = Flask(__name__, template_folder=str(base / "templates"), static_folder=str(base / "static"))
    app.config.update(
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        CSRF_ENABLED=True,
    )
    if config:
        app.config.update(config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = auth.secret_key()

    register_hooks(app)
    register_routes(app)
    try:
        roles.unify_legacy_scorekeepers()
    except Exception:  # never block start-up; it is retried whenever a legacy Scorekeeper signs in
        app.logger.exception("role migration failed")
    return app


# --------------------------------------------------------------------------- hooks & helpers

INVITE_LIMIT = 20     # invitations a Race Master can send per hour
JOIN_LIMIT = 5        # join requests an account can send per hour (across leagues)


def sign_in(username):
    """Start a signed-in session (registered, so it can be listed and ended from Account)."""
    session.clear()
    session["user"] = username
    session["sid"] = security.start_session(username, request.headers.get("User-Agent", ""))


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def register_hooks(app):
    @app.before_request
    def guard():
        feed.take_outbox()
        discord.take()
        g.user = None
        endpoint = request.endpoint or ""
        if endpoint == "static":
            return None
        if auth.user_count() == 0:
            return None if endpoint == "setup" else redirect(url_for("setup"))
        if session.get("user"):
            g.user = auth.get_user(session["user"])
            if g.user and not session.get("sid"):
                # Signed in before sessions were registered (v2.0): register it rather than signing them out.
                session["sid"] = security.start_session(g.user["username"], request.headers.get("User-Agent", ""))
            elif g.user and not security.check_session(session["sid"], g.user["username"]):
                session.clear()
                g.user = None
                flash("You were signed out of this device from another one.", "info")
            if not g.user:
                session.clear()
            elif g.user["is_steward"]:  # an old account-wide Scorekeeper: move it into their leagues first
                roles.unify_legacy_scorekeepers()
                g.user = auth.get_user(session["user"])
        if g.user and g.user.get("is_demo") and endpoint in DEMO_BLOCKED:
            flash("That isn't available in the demo. Create a free account to use it.", "info")
            return redirect(url_for("dashboard", token=session.get("demo")) if session.get("demo") else url_for("home"))
        if not g.user and endpoint not in PUBLIC_ENDPOINTS:
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Please log in again"), 401
            return redirect(url_for("login", next=request.full_path))
        if request.method == "POST" and app.config.get("CSRF_ENABLED"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
            if not hmac.compare_digest(sent, session.get("csrf", "")):
                if request.path.startswith("/api/"):
                    return jsonify(ok=False, error="Session expired - refresh the page"), 400
                flash("Your session expired. Please try again.", "error")
                return redirect(request.referrer or url_for("home"))
        return None

    @app.after_request
    def vendor_files(response):
        """The self-hosted OCR engine: cache it for a month, and hand the language data over still gzipped
        (Tesseract unpacks it itself)."""
        if request.path.startswith("/static/vendor/"):
            response.headers["Cache-Control"] = "public, max-age=2592000"
            if request.path.endswith(".gz"):
                response.headers.pop("Content-Encoding", None)
                response.headers["Content-Type"] = "application/gzip"
        return response

    @app.after_request
    def send_alerts(response):
        news = discord.take()
        if news and response.status_code < 400 and not app.config.get("TESTING"):
            _discord_news(news)
        items = feed.take_outbox()
        if items and response.status_code < 400:
            try:
                delivery.dispatch(items, request.host_url.rstrip("/"),
                                  exclude=g.user["username"] if g.get("user") else None,
                                  background=not app.config.get("TESTING"))
            except Exception:
                app.logger.exception("notification delivery failed")
        return response

    def _tz():
        return g.get("tz") or timefmt.DEFAULT_TZ

    app.add_template_filter(lambda v: timefmt.race(v, _tz()), "race_time")
    app.add_template_filter(lambda v: timefmt.race_at(v, _tz()), "race_at")
    app.add_template_filter(lambda v: timefmt.stamp(v, _tz()), "stamp")
    app.add_template_filter(lambda v: timefmt.day(v, _tz()), "day")
    app.add_template_filter(lambda v: timefmt.ago(v, _tz()), "ago")
    app.add_template_filter(lambda v: timefmt.countdown(v), "countdown")
    app.add_template_filter(lambda ev: timefmt.race_status(ev["race_at"], ev["status"],
                                                           g.get("race_window") or timefmt.DEFAULT_RACE_WINDOW,
                                                           postponed=bool(ev["postponed"]) if "postponed" in ev.keys() else False),
                            "race_status")
    app.add_template_filter(lambda v: timefmt.zone_label(v, _tz()), "zone_label")
    app.add_template_filter(lambda v: timefmt.input_value(v, _tz()), "time_input")

    @app.context_processor
    def inject():
        key = None
        if g.get("user"):
            try:
                key = push.public_key()
            except Exception:
                app.logger.exception("push keys unavailable")
        return {"csrf_token": csrf_token, "user": g.get("user"), "APP_VERSION": C.APP_VERSION,
                "APP_NAME": C.APP_NAME, "C": C, "push_key": key, "whats_new": _whats_new()}

    def _whats_new():
        """This version's highlights, once per account, on ordinary page views only."""
        user = g.get("user")
        if not user or user.get("is_demo") or request.method != "GET" or request.path.startswith("/api/") \
                or request.endpoint in ("changelog_page", "whats_new_ack"):
            return None
        from . import changelog, whatsnew
        entry = changelog.entry(_base_dir(), C.APP_VERSION)
        if not entry or not entry["highlights"] or whatsnew.acknowledged(user["username"], C.APP_VERSION):
            return None
        return entry

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="That page belongs to the Race Master."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="That league or page could not be found."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413, message="Uploads are limited to 100 MB."), 413


def _discord_news(items):
    by_token = {}
    for token, message in items:
        by_token.setdefault(token, []).append(message)
    for token, messages in by_token.items():
        try:
            with storage.session(token) as conn:
                cfg = discord.settings(conn)
            if cfg["url"] and cfg["news"]:
                discord.send_later(cfg["url"], messages)
        except Exception:
            pass


def is_master():
    """Race Master here: a site Race Master, or this league's Race Master (inside a league request)."""
    return bool(g.user and (g.user["is_master"] or g.get("league_role") == "race_master"))


def can_run(membership=None):
    """May enter race results in this league (Race Master or Scorekeeper role)."""
    return roles.can_enter_results(g.get("league_role"))


def _load_league_role(token):
    """Work out the user's role in this league for routes that don't open it through career_page."""
    g.league_role = None
    if not g.user:
        return None
    try:
        with storage.session(token) as conn:
            g.league_role = roles.effective_role(conn, g.user)
    except CareerNotFound:
        abort(404)
    return g.league_role


def master_required(fn):
    """Site Race Master only; for a league's own pages (token in the URL), that league's Race Master too."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not (g.user and g.user["is_master"]):
            if "token" not in kwargs or _load_league_role(kwargs["token"]) != "race_master":
                abort(403)
        return fn(*args, **kwargs)
    return wrapper


def _member_driver(conn):
    row = conn.execute("SELECT driver_id FROM career_members WHERE username = ?", (g.user["username"],)).fetchone()
    if not row:
        return None
    return S.driver_map(conn).get(row["driver_id"])


def _selected_season(conn, token):
    key = f"season_{token}"
    wanted = request.args.get("season", type=int)
    if wanted and S.get_season(conn, wanted):
        session[key] = wanted
    sid = session.get(key)
    if not sid or not S.get_season(conn, sid):
        sid = S.current_season_id(conn)
    return sid


def career_page(master_only=False, ops_only=False):
    """Open the career, enforce access, and turn ValidationErrors into flashed messages."""
    def deco(fn):
        @wraps(fn)
        def wrapper(token, *args, **kwargs):
            try:
                storage.auto_backup(token, "daily")
            except Exception:  # a backup problem must never block the page
                app.logger.exception("automatic backup failed")
            try:
                with storage.session(token) as conn:
                    g.league_role = roles.effective_role(conn, g.user)
                    if not g.league_role:
                        abort(403)
                    if master_only and not is_master():
                        abort(403)
                    if ops_only and not can_run():
                        abort(403)
                    if g.league_role == "spectator" and request.method == "POST" \
                            and request.endpoint not in SPECTATOR_POST_OK:
                        abort(403)  # spectators are strictly read-only, whatever endpoint is called
                    roles.touch(conn, g.user["username"])
                    season_id = _selected_season(conn, token)
                    g.tz = storage.get_meta(conn, "timezone") or timefmt.DEFAULT_TZ
                    g.race_window = int(storage.get_meta(conn, "race_window") or timefmt.DEFAULT_RACE_WINDOW)
                    g.ctx = {
                        "race_window": g.race_window,
                        "timezone": g.tz,
                        "timezone_set": bool(storage.get_meta(conn, "timezone")),
                        "token": token,
                        "career_name": storage.get_meta(conn, "career_name", "Career"),
                        "season": S.get_season(conn, season_id),
                        "current_season_id": S.current_season_id(conn),
                        "seasons": S.list_seasons(conn),
                        "is_master": is_master(),
                        "can_run": can_run(),
                        "access": g.league_role,
                        "is_spectator": g.league_role == "spectator",
                        "my_driver": _member_driver(conn),
                        "features": community.features(conn),
                        "open_windows": conn.execute("SELECT COUNT(*) FROM market_windows WHERE status = ?",
                                                     (C.WINDOW_OPEN,)).fetchone()[0],
                    }
                    _apply_view_mode(g.ctx, token)
                    mine = g.ctx["my_driver"]
                    g.ctx["role"] = C.ACCESS_ROLES[g.league_role] + (" · Driver" if mine else "")
                    if g.league_role == "member" and mine:
                        g.ctx["role"] = "Driver"
                    master_view = g.ctx["is_master"]
                    g.ctx["pending_offers"] = conn.execute(
                        "SELECT COUNT(*) FROM offers WHERE status = ?" + (" AND driver_id = ?" if mine and not master_view else ""),
                        (C.OFFER_PENDING, mine["id"]) if mine and not master_view else (C.OFFER_PENDING,)).fetchone()[0]
                    g.ctx["notifications"], g.ctx["unread"] = feed.notifications_for(
                        conn, g.user["username"], mine["id"] if mine else None, master_view and not mine)
                    g.ctx["team_life"] = teamlife.settings(conn)
                    g.ctx["team_goals_on"] = teamgoals.enabled(conn)
                    if not request.path.startswith("/api/"):
                        announcements.publish_due(conn)
                    g.ctx["accent"], g.ctx["on_accent"] = _accent(storage.get_meta(conn, "accent_color"))
                    g.ctx["is_demo"] = storage.get_meta(conn, "demo") == "1"
                    g.ctx["my_todo"] = gates.my_todo(conn, g.ctx["current_season_id"], mine["id"]) \
                        if mine and not request.path.startswith("/api/") else None
                    storage.touch_opened(conn)
                    impacts.on_open(conn, is_api=request.path.startswith("/api/"))
                    gate = _impact_gate(conn, g.ctx) or _pledge_gate(conn, g.ctx, master_only)
                    if gate is not None:
                        return gate
                    described = _describe_targets(conn, kwargs) if request.method == "POST" else ("", None)
                    result = fn(conn, g.ctx, *args, **kwargs)
                    if request.method == "POST":
                        impacts.mark_stale(conn)   # numbers may have moved: take a fresh copy on the next page
                    if request.method == "POST" and request.endpoint not in QUIET_ENDPOINTS:
                        label = AUDIT_LABELS.get(request.endpoint, request.endpoint.replace("_", " ").capitalize())
                        what, link = described
                        summary = g.get("audit_summary") or (label[:1].lower() + label[1:] + (": " + what if what else ""))
                        community.audit(conn, g.user["username"], label, what, summary=summary,
                                        link=g.get("audit_link") or link)
                    return result
            except CareerNotFound:
                abort(404)
            except (ValidationError, AuthError) as exc:
                feed.take_outbox()  # nothing was saved, so nothing to alert about
                discord.take()
                if request.method != "POST":
                    raise
                flash(str(exc), "error")
                return redirect(request.referrer or url_for("dashboard", token=token))
        return wrapper
    return deco


# Demo guests can explore their own copy of the demo league but never change an account or reach anyone.
DEMO_BLOCKED = {"accounts_page", "account_email", "account_self_password", "career_join", "invitation_answer",
                "league_new_page", "career_new", "career_import", "push_subscribe", "push_test", "settings_save",
                "member_invite", "discord_test", "restore_upload", "save_as", "export", "backup",
                "account_session_end", "account_sessions_end_others", "account_two_step", "account_export",
                "account_delete_self", "league_leave", "ownership_transfer"}

# Display modes: how a page is shown, never what the account may do. Server checks always use the real role.
VIEW_MODES = {"race_master": "Race Master", "scorekeeper": "Scorekeeper", "driver": "Driver", "spectator": "Spectator preview"}


def available_modes(role, has_driver):
    order = {"race_master": ["race_master", "scorekeeper", "driver", "spectator"],
             "scorekeeper": ["scorekeeper", "driver", "spectator"],
             "member": ["driver", "spectator"] if has_driver else ["spectator"],
             "spectator": ["spectator"]}.get(role, ["spectator"])
    return [m for m in order if m != "driver" or has_driver]


def _accent(value):
    """A league's accent colour and a readable text colour on top of it (never a raw user string in CSS)."""
    import re as _re
    value = value if value and _re.fullmatch(r"#[0-9a-fA-F]{6}", value) else "#e10600"
    r, g_, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = 0.2126 * r + 0.7152 * g_ + 0.0722 * b
    return value, ("#0b0d11" if lum > 0.55 else "#ffffff")


def _apply_view_mode(ctx, token):
    """Lower what the page shows to the chosen display mode. The account keeps every real permission."""
    real_role = g.league_role
    ctx["real"] = {"is_master": ctx["is_master"], "can_run": ctx["can_run"], "role": real_role,
                   "my_driver": ctx["my_driver"]}
    modes = available_modes(real_role, bool(ctx["my_driver"]))
    natural = modes[0]
    mode = session.get(f"mode_{token}")
    if mode not in modes:
        mode = natural
    ctx["modes"] = [(m, VIEW_MODES[m]) for m in modes]
    ctx["mode"], ctx["mode_label"], ctx["mode_lowered"] = mode, VIEW_MODES[mode], mode != natural
    if mode == "scorekeeper":
        ctx.update(is_master=False, can_run=True)
    elif mode == "driver":
        ctx.update(is_master=False, can_run=False, is_spectator=False)
    elif mode == "spectator":
        ctx.update(is_master=False, can_run=False, is_spectator=True, my_driver=None)


HELP_TOPICS = [("roles", "Roles and permissions"), ("results", "Entering results"), ("statuses", "Result statuses"),
               ("scoring", "Scoring and Sprint points"), ("form", "Form"), ("reputation", "Reputation"),
               ("driver-value", "Driver Value"), ("car", "Car strength"), ("market", "Transfer market"),
               ("pledges", "Growth pledges"), ("relationship", "Team relationship"), ("rivalry", "Rivalries"),
               ("incidents", "Incidents"), ("difficulty", "AI difficulty"), ("notifications", "Notifications"),
               ("visibility", "Public visibility"), ("backups", "Backups and recovery"), ("targets", "Weekend targets"),
               ("gates", "Round gates"), ("contracts", "Contracts and seats"), ("modes", "View modes"),
               ("statistics", "Statistics"), ("team-goals", "Team goals"), ("announcements", "Announcements"),
               ("security", "Account security and two-step sign-in"), ("your-data", "Your data and leaving a league"),
               ("talks", "Talking to teams and interviews"), ("dismissals", "Final warnings and mid-season dismissals"),
               ("my-settings", "My settings"), ("updates", "Updates and change notices")]


# The only league POSTs a Spectator may make: marking their own notifications and the time-zone probe.
SPECTATOR_POST_OK = {"notifications_read", "notifications_clear", "timezone_detect", "notify_prefs", "view_mode",
                     "league_pin", "league_order", "league_leave"}

PLEDGE_EXEMPT = {"pledge_page", "pledge_save", "api_notifications", "notifications_read", "notifications_clear",
                 "help_page"}


IMPACT_EXEMPT = {"impact_page", "api_notifications", "notifications_read", "notifications_clear", "help_page",
                 "timezone_detect", "view_mode", "whats_new_ack"}


def _impact_gate(conn, ctx):
    """A driver whose numbers were changed by an update or an admin change must see and agree to it first."""
    mine = ctx.get("real", ctx).get("my_driver")
    if not mine or request.endpoint in IMPACT_EXEMPT or request.path.startswith("/api/"):
        return None
    if not impacts.pending(conn, mine["id"], g.user["username"]):
        return None
    return redirect(url_for("impact_page", token=ctx["token"]))


def _pledge_gate(conn, ctx, master_only):
    """A seated player driver with no growth pledge must choose one before using the league."""
    mine = ctx.get("my_driver")
    if not mine or request.endpoint in PLEDGE_EXEMPT or (master_only and ctx["is_master"]):
        return None
    sid = ctx["current_season_id"]
    relations.ensure(conn, sid)
    if not relations.needs_pledge(conn, sid, mine["id"]):
        return None
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="Choose your growth pledge first"), 409
    if request.method == "POST":
        flash("Choose your growth pledge for this season first.", "error")
    return redirect(url_for("pledge_page", token=ctx["token"]))


def _settings_changes(conn, before):
    """League settings changes as a sentence, e.g. "changed join requests from Off to On". No private values."""
    changes = []
    after = community.features(conn)
    for key, (label, _desc, _default) in C.FEATURES.items():
        if before["features"].get(key) != after.get(key):
            changes.append(f"turned {label} {'on' if after.get(key) else 'off'}")
    join = storage.join_mode(conn)
    if join != before["join"]:
        changes.append(f"changed joining from {storage.JOIN_MODES[before['join']]} to {storage.JOIN_MODES[join]}")
    d = discord.settings(conn)
    if bool(d["url"]) != bool(before["discord"]["url"]):
        changes.append("connected a Discord channel" if d["url"] else "disconnected Discord")
    elif d["url"] != before["discord"]["url"]:
        changes.append("changed the Discord channel")   # the webhook URL itself is private
    window = int(storage.get_meta(conn, "race_window") or timefmt.DEFAULT_RACE_WINDOW)
    if window != before["window"]:
        changes.append(f"changed how long a race shows In progress from {before['window'] // 60} h to {window // 60} h")
    tz = storage.get_meta(conn, "timezone") or timefmt.DEFAULT_TZ
    if tz != before["tz"]:
        changes.append(f"changed the league time zone from {before['tz']} to {tz}")
    life, was = teamlife.settings(conn), before.get("life")
    if was:
        if life["orders"] != was["orders"]:
            changes.append(f"changed team orders from {C.TEAM_ORDER_MODES[was['orders']].split(' (')[0]} to "
                           f"{C.TEAM_ORDER_MODES[life['orders']].split(' (')[0]}")
        for key, label in (("targets", "weekend targets"), ("gates", "round gates"),
                           ("gate_press", "the press-questions gate"), ("gate_targets", "the weekend-target gate")):
            if life[key] != was[key]:
                changes.append(f"turned {label} {'on' if life[key] else 'off'}")
    return "; ".join(changes)


def _ics_response(league, season, evs, base_link):
    """RFC 5545 calendar of the races that have a time. Two-hour events; titles name the league and round."""
    def esc(text):
        return str(text).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    from datetime import datetime as _dt, timedelta as _td
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Paddock Legacy//Calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{esc(league)} {season['year']}"]
    stamp = _dt.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in evs:
        if not e["race_at"]:
            continue
        try:
            start = _dt.fromisoformat(e["race_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        start = start.astimezone(timezone.utc) if start.tzinfo else start
        fmt = "%Y%m%dT%H%M%SZ"
        lines += ["BEGIN:VEVENT", f"UID:pl-{season['id']}-{e['id']}@paddock-legacy", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start.strftime(fmt)}", f"DTEND:{(start + _td(hours=2)).strftime(fmt)}",
                  "SUMMARY:" + esc(f"{league}: R{e['round_number']} {e['name']}" + (" (Sprint weekend)" if e["is_sprint"] else "")),
                  f"LOCATION:{esc(e['location'] or '')}", f"URL:{base_link}/{e['id']}",
                  "STATUS:" + ("CANCELLED" if e["postponed"] else "CONFIRMED"), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    body = "\r\n".join(lines) + "\r\n"
    return app_response(body)


def app_response(body):
    from flask import Response
    return Response(body, mimetype="text/calendar", headers={"Content-Disposition": "attachment; filename=calendar.ics"})


def event_label(event, year=None):
    return f"Round {event['round_number']} — {event['name']}" + (f" ({year})" if year else "")


def _describe_targets(conn, kwargs):
    """Readable names (and a safe in-league link) for what a request acts on, looked up before it changes."""
    parts, link = [], None
    if "event_id" in kwargs:
        ev = conn.execute("SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id WHERE e.id = ?",
                          (kwargs["event_id"],)).fetchone()
        if ev:
            parts.append(event_label(ev, ev["year"])); link = f"weekend/{ev['id']}"
    if "driver_id" in kwargs:
        d = S.driver_map(conn).get(kwargs["driver_id"])
        if d:
            parts.append(d["name"]); link = link or f"driver/{d['id']}"
    if "team_id" in kwargs:
        t = S.team_map(conn).get(kwargs["team_id"])
        if t:
            parts.append(t["name"]); link = link or f"team/{t['id']}"
    if "window_id" in kwargs:
        w = conn.execute("SELECT * FROM market_windows WHERE id = ?", (kwargs["window_id"],)).fetchone()
        if w:
            parts.append(f"the {w['kind']} window for {w['target_year']}"); link = link or "market"
    if "offer_id" in kwargs:
        o = conn.execute("SELECT * FROM offers WHERE id = ?", (kwargs["offer_id"],)).fetchone()
        if o:
            parts.append(f"{S.team_map(conn)[o['team_id']]['name']}'s offer to {S.driver_map(conn)[o['driver_id']]['name']}")
    if kwargs.get("username"):
        u = auth.get_user(kwargs["username"])
        parts.append(u["display_name"] if u else kwargs["username"]); link = link or "members"
    if "season_id" in kwargs:
        s = S.get_season(conn, kwargs["season_id"])
        if s:
            parts.append(f"the {s['year']} season")
    if "request_id" in kwargs:
        r = conn.execute("SELECT username FROM join_requests WHERE id = ?", (kwargs["request_id"],)).fetchone()
        if r:
            parts.append(f"the join request from {r['username']}"); link = link or "members"
    for key, noun in (("incident_id", "an incident report"), ("news_id", "a headline"), ("comment_id", "a comment"),
                      ("notification_id", "a notification"), ("contract_id", "a negotiation storyline")):
        if key in kwargs:
            parts.append(noun)
    return ", ".join(parts), link


def page(template, ctx, **kwargs):
    if ctx.get("is_master"):
        ctx["auto_backups"] = storage.list_auto_backups(ctx["token"])[:8]
    ctx["leagues"] = library.user_leagues(g.user)
    ctx["this_league"] = next((l for l in ctx["leagues"] if l["token"] == ctx["token"]), None)
    return render_template(template, ctx=ctx, **kwargs)


def _form_int(name, default=None):
    try:
        return int(request.form.get(name))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- routes

def register_routes(app):
    # ---------------------------------------------------------------- accounts
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if auth.user_count() > 0:
            return redirect(url_for("login"))
        if request.method == "POST":
            if not hmac.compare_digest(request.form.get("csrf_token", ""), session.get("csrf", "")) \
                    and app.config.get("CSRF_ENABLED"):
                flash("Session expired. Please try again.", "error")
                return redirect(url_for("setup"))
            code = os.environ.get("F1_TRACKER_SETUP_CODE", "")
            if code and not hmac.compare_digest(request.form.get("setup_code", "").strip(), code):
                flash("That setup code is wrong. It's in your host's environment settings (F1_TRACKER_SETUP_CODE).", "error")
                return redirect(url_for("setup"))
            if "confirm_password" in request.form and request.form.get("confirm_password") != request.form.get("password"):
                flash("The two passwords don't match.", "error")
                return redirect(url_for("setup"))
            try:
                username = auth.create_user(request.form.get("username"), request.form.get("display_name"),
                                            request.form.get("password"), is_master=True,
                                            email=request.form.get("email"))
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("setup"))
            sign_in(username)
            flash("Race Master account created. Add logins for the other player in Accounts.", "success")
            return redirect(url_for("home"))
        return render_template("login.html", mode="setup", needs_code=bool(os.environ.get("F1_TRACKER_SETUP_CODE")))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            try:
                user = auth.login(request.form.get("username"), request.form.get("password"), request.remote_addr)
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("login", next=request.args.get("next", "")))
            target = request.args.get("next") or ""
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("home")
            if security.totp_status(user["username"])["enabled"]:
                # Password was right; the second step (a code from their authenticator app) comes next.
                session.clear()
                session["2fa_user"], session["2fa_at"], session["2fa_next"] = user["username"], time.time(), target
                return redirect(url_for("login_code"))
            sign_in(user["username"])
            return redirect(target)
        return render_template("login.html", mode="login", signups=auth.signups_allowed())

    @app.route("/login/code", methods=["GET", "POST"])
    def login_code():
        """Two-step sign-in: the 6-digit code from the person's authenticator app."""
        username = session.get("2fa_user")
        if not username or time.time() - session.get("2fa_at", 0) > 300:
            session.clear()
            flash("Please log in again.", "info")
            return redirect(url_for("login"))
        if request.method == "POST":
            if not ratelimit.allow("2fa", username, 6, 600):
                session.clear()
                flash("Too many wrong codes. Wait a few minutes and log in again.", "error")
                return redirect(url_for("login"))
            if security.verify_code(security.totp_status(username)["secret"], request.form.get("code")):
                target = session.get("2fa_next") or url_for("home")
                sign_in(username)
                return redirect(target)
            flash("That code didn't match. Use the newest code from your authenticator app.", "error")
        return render_template("login.html", mode="code")

    def _send_signup_code(email, code, display_name):
        mailer.send([email], f"Your Paddock Legacy code: {code}",
                    f"Hi {display_name},\n\nYour sign-up code is: {code}\n\nEnter it on the sign-up page within "
                    f"{auth.SIGNUP_CODE_MINUTES} minutes to finish creating your account. If you didn't sign up, "
                    "ignore this email and nothing happens.")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        email_ready = mailer.configured()
        if request.method == "POST":
            if not email_ready:
                flash("Sign-ups need email to be set up first. Ask the Race Master to create your login.", "error")
                return redirect(url_for("register"))
            if request.form.get("password") != request.form.get("confirm"):
                flash("The two passwords don't match.", "error")
                return redirect(url_for("register"))
            try:
                pending_id, code = auth.register(request.form.get("username"), request.form.get("display_name"),
                                                 request.form.get("password"), request.remote_addr,
                                                 request.form.get("email"))
                pending = auth.pending_signup(pending_id)
                _send_signup_code(pending["email"], code, pending["display_name"])
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("register"))
            except mailer.MailError:
                app.logger.exception("sign-up email failed")
                flash("We couldn't send the code email. Check the address, or ask the Race Master.", "error")
                return redirect(url_for("register"))
            session.clear()
            session["signup_id"] = pending_id
            return redirect(url_for("register_verify"))
        return render_template("login.html", mode="register", signups=auth.signups_allowed(), email_ready=email_ready)

    @app.route("/register/verify", methods=["GET", "POST"])
    def register_verify():
        pending = auth.pending_signup(session.get("signup_id"))
        if not pending:
            flash("That sign-up has expired. Please fill in the form again.", "error")
            return redirect(url_for("register"))
        if request.method == "POST":
            try:
                username = auth.finish_signup(pending["id"], request.form.get("code"))
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("register_verify"))
            sign_in(username)
            flash("Email confirmed and account created. Pick an open league below and ask to join.", "success")
            return redirect(url_for("home"))
        email = pending["email"]
        masked = email[0] + "•••" + email[email.index("@") - 1:] if email.index("@") > 1 else email
        return render_template("login.html", mode="verify", masked_email=masked, signups=True)

    @app.route("/register/resend", methods=["POST"])
    def register_resend():
        try:
            email, code = auth.resend_signup_code(session.get("signup_id"))
            _send_signup_code(email, code, auth.pending_signup(session.get("signup_id"))["display_name"])
            flash("A new code is on its way.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        except mailer.MailError:
            flash("We couldn't send the code email. Try again in a minute.", "error")
        return redirect(url_for("register_verify"))

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot():
        if request.method == "POST":
            if not auth.reset_request_allowed(request.remote_addr):
                flash("Too many reset requests from this connection. Try again in an hour.", "error")
                return redirect(url_for("forgot"))
            sent = False
            for user in auth.users_by_login(request.form.get("login")):
                token = auth.create_reset_token(user["username"])
                link = url_for("reset_password", token=token, _external=True)
                text = (f"Hi {user['display_name']},\n\nSomeone asked to reset the password for '{user['username']}' on "
                        f"Paddock Legacy. Open this link within {auth.RESET_MINUTES} minutes to choose a new one:\n\n"
                        f"{link}\n\nIf that wasn't you, ignore this email and nothing changes.")
                sent = mailer.send_later([user["email"]], "Reset your Paddock Legacy password", text) or sent
            flash("If that account has an email address, a reset link is on its way. Check your inbox (and spam)."
                  + ("" if mailer.configured() else " (Email isn't set up on this tracker yet, so ask the Race Master.)"),
                  "success")
            return redirect(url_for("login"))
        return render_template("login.html", mode="forgot", signups=auth.signups_allowed())

    @app.route("/reset/<token>", methods=["GET", "POST"])
    def reset_password(token):
        username = auth.reset_token_user(token)
        if request.method == "POST":
            if request.form.get("password") != request.form.get("confirm"):
                flash("The two passwords don't match.", "error")
                return redirect(url_for("reset_password", token=token))
            try:
                username = auth.use_reset_token(token, request.form.get("password"))
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("forgot"))
            session.clear()
            flash("Password changed. Log in with your new password.", "success")
            return redirect(url_for("login"))
        if not username:
            flash("That reset link has expired or was already used. Ask for a new one.", "error")
            return redirect(url_for("forgot"))
        return render_template("login.html", mode="reset", reset_user=username, signups=False)

    @app.route("/account/email", methods=["POST"])
    def account_email():
        try:
            saved = auth.set_email(g.user["username"], request.form.get("email"), g.user.get("email_results"))
            auth.set_email_paused(g.user["username"], request.form.get("email_paused"))
            if not saved:
                flash("Email address removed. No league can email you until you add one.", "success")
            elif request.form.get("email_paused"):
                flash("Email saved. Every league's emails are paused; your choices in each league are kept.", "success")
            else:
                flash("Email saved. Each league emails you according to its own notification settings.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/accounts/<username>/email", methods=["POST"])
    @master_required
    def account_set_email(username):
        user = auth.get_user(username)
        if not user:
            abort(404)
        try:
            auth.set_email(username, request.form.get("email"), user["email_results"])
            flash("Email updated.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/settings/test-email", methods=["POST"])
    @master_required
    def settings_test_email():
        try:
            mailer.send([g.user["email"]], "Paddock Legacy test email",
                        "Email is working. Password resets and race-result emails will be sent from this address.")
            flash(f"Test email sent to {g.user['email']}.", "success")
        except mailer.MailError as exc:
            flash(str(exc), "error")
        except Exception:
            flash("Add your own email address first (My account).", "error")
        return redirect(url_for("accounts_page"))

    @app.route("/settings", methods=["POST"])
    @master_required
    def settings_save():
        auth.set_setting("allow_signups", "1" if request.form.get("allow_signups") else "0")
        auth.set_setting("league_creation", "everyone" if request.form.get("anyone_creates") else "admins")
        for field in ("smtp_host", "smtp_port", "smtp_username", "smtp_from"):
            if field in request.form:
                auth.set_setting(field, (request.form.get(field) or "").strip() or None)
        if (request.form.get("smtp_password") or "").strip():
            auth.set_setting("smtp_password", request.form.get("smtp_password").strip())
        flash("Settings saved.", "success")
        return redirect(url_for("accounts_page"))

    @app.route("/moderation/<int:report_id>", methods=["POST"])
    @master_required
    def moderation_decide(report_id):
        """Site admins: dismiss a report, or take the league out of the public directory (and put it back)."""
        action = request.form.get("action")
        match = next((r for r in moderation.reports() if r["id"] == report_id), None)
        if not match:
            abort(404)
        if action == "delist":
            moderation.set_delisted(match["token"], True)
            moderation.decide(report_id, "Delisted")
            flash(f"{match['league_name']} is no longer listed in the directory.", "success")
        else:
            moderation.decide(report_id, "Dismissed")
            flash("Report dismissed.", "success")
        return redirect(url_for("accounts_page") + "#moderation")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/accounts")
    def accounts_page():
        me = g.user["username"]
        totp = security.totp_status(me)
        memberships = {}
        if is_master():
            for c in storage.list_careers():
                for username in c["members"]:
                    memberships.setdefault(username, []).append(c["name"])
        mine = []
        for c in storage.list_careers():
            if g.user["username"] in c["members"]:
                try:
                    with storage.session(c["token"]) as conn:
                        mine.append({"token": c["token"], "name": c["name"],
                                     "prefs": notices.summary(notices.prefs(conn, g.user["username"]))})
                except storage.CareerNotFound:
                    continue
        return render_template("accounts.html", users=auth.list_users() if is_master() else [],
                               memberships=memberships, my_leagues=mine,
                               anyone_creates=onboarding.creation_policy() == "everyone",
                               reports=moderation.reports() if is_master() else [], reasons=moderation.REASONS,
                               delisted=moderation.delisted() if is_master() else set(), signups=auth.signups_allowed(),
                               mail=mailer.config(), mail_ready=mailer.configured(),
                               pw_min=auth.PASSWORD_MIN, devices=security.sessions(me),
                               current_sid=session.get("sid"), totp=totp,
                               otpauth=security.otpauth_uri(me, totp["secret"]) if totp["secret"] and not totp["enabled"] else None,
                               two_step_users={u["username"] for u in auth.list_users() if security.totp_status(u["username"])["enabled"]}
                               if is_master() else set())

    @app.route("/accounts/new", methods=["POST"])
    @master_required
    def account_new():
        try:
            if "confirm_password" in request.form and request.form.get("confirm_password") != request.form.get("password"):
                raise AuthError("The two passwords don't match")
            role = request.form.get("role", "driver")
            auth.create_user(request.form.get("username"), request.form.get("display_name"),
                             request.form.get("password"), is_master=role == "master",
                             email=request.form.get("email"))
            flash("Account created.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/accounts/<username>/password", methods=["POST"])
    @master_required
    def account_reset(username):
        try:
            if "confirm_password" in request.form and request.form.get("confirm_password") != request.form.get("password"):
                raise AuthError("The two passwords don't match")
            auth.set_password(username, request.form.get("password"))
            flash("Password updated.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/accounts/<username>/role", methods=["POST"])
    @master_required
    def account_role(username):
        try:
            auth.set_role(username, request.form.get("role"))
            flash("Role updated.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/accounts/<username>/delete", methods=["POST"])
    @master_required
    def account_delete(username):
        try:
            if auth.normalise(username) == g.user["username"]:
                raise AuthError("You cannot delete the account you are using")
            auth.delete_user(username)
            flash("Account deleted.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/account/password", methods=["POST"])
    def account_self_password():
        try:
            auth.change_password(g.user["username"], request.form.get("current_password"),
                                 request.form.get("password"), request.form.get("confirm_password"))
            n = security.end_other_sessions(g.user["username"], session.get("sid"))
            flash("Password changed." + (f" {n} other device{'s were' if n != 1 else ' was'} signed out." if n else ""),
                  "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page") + "#password")

    @app.route("/account/sessions/<sid>/end", methods=["POST"])
    def account_session_end(sid):
        security.end_session(g.user["username"], sid)
        if sid == session.get("sid"):
            session.clear()
            return redirect(url_for("login"))
        flash("That device is signed out.", "success")
        return redirect(url_for("accounts_page") + "#security")

    @app.route("/account/sessions/end-others", methods=["POST"])
    def account_sessions_end_others():
        n = security.end_other_sessions(g.user["username"], session.get("sid"))
        flash(f"Signed out {n} other device{'s' if n != 1 else ''}.", "success")
        return redirect(url_for("accounts_page") + "#security")

    @app.route("/account/two-step", methods=["POST"])
    def account_two_step():
        """Turn two-step sign-in on (scan/enter a key, confirm a code) or off (password and a code)."""
        me = g.user["username"]
        action = request.form.get("action")
        try:
            if action == "start":
                security.begin_totp(me)
                flash("Add the key below to your authenticator app, then enter the code it shows to finish.", "info")
            elif action == "confirm":
                security.enable_totp(me, request.form.get("code"))
                flash("Two-step sign-in is on. You'll be asked for a code each time you log in.", "success")
            elif action == "disable":
                if not auth.verify(me, request.form.get("password") or ""):
                    raise AuthError("That password isn't right")
                if not security.verify_code(security.totp_status(me)["secret"], request.form.get("code")):
                    raise AuthError("That code didn't match")
                security.disable_totp(me)
                flash("Two-step sign-in is off.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page") + "#security")

    @app.route("/accounts/<username>/two-step-reset", methods=["POST"])
    @master_required
    def account_two_step_reset(username):
        """Site admins: switch off two-step sign-in for someone who lost their phone."""
        security.disable_totp(auth.normalise(username))
        security.end_other_sessions(auth.normalise(username))
        flash(f"Two-step sign-in is off for {username}, and their devices were signed out.", "success")
        return redirect(url_for("accounts_page"))

    @app.route("/account/export")
    def account_export():
        """Everything this account holds, as JSON: profile, memberships, notification choices and, per league, the
        driver they control and what they did. Never a password hash, session or other people's details."""
        import json as _json
        me = g.user["username"]
        user = auth.get_user(me)
        out = {"format": "paddock-legacy-account", "version": 1, "exported_at": storage.now_iso(),
               "account": {k: user.get(k) for k in ("username", "display_name", "email", "created_at", "email_paused")},
               "two_step_sign_in": security.totp_status(me)["enabled"],
               "signed_in_devices": [{k: r[k] for k in ("created_at", "last_seen", "agent")} for r in security.sessions(me)],
               "leagues": []}
        for c in storage.list_careers():
            if me not in c["members"]:
                continue
            with storage.session(c["token"]) as conn:
                row = conn.execute("SELECT * FROM career_members WHERE username = ?", (me,)).fetchone()
                driver = S.driver_map(conn).get(row["driver_id"]) if row else None
                entry = {"league": c["name"], "role": row["role"] if row else None, "joined_at": row["joined_at"] if row else None,
                         "notifications": notices.prefs(conn, me),
                         "activity": [{k: a[k] for k in ("created_at", "action", "summary")}
                                      for a in community.audit_entries(conn, 500, username=me)]}
                if driver:
                    tl = S.driver_timeline(conn, driver["id"])
                    entry["driver"] = {"name": driver["name"], "career": S.career_totals(tl),
                                       "seasons": [{"year": t["season"]["year"], "team": t["team"]["name"] if t["team"] else None,
                                                    "position": t["position"], "points": t["points"]} for t in tl]}
                entry["notifications"].pop("stored", None)
                out["leagues"].append(entry)
        body = _json.dumps(out, indent=2, default=str)
        return send_file(io.BytesIO(body.encode("utf-8")), as_attachment=True, mimetype="application/json",
                         download_name=f"paddock-legacy-{me}.json")

    @app.route("/account/delete", methods=["POST"])
    def account_delete_self():
        """Delete this account. Leagues keep their results and drivers; this login just leaves them all."""
        me = g.user["username"]
        if not auth.verify(me, request.form.get("password") or "") or request.form.get("confirm") != me:
            flash("Type your username and password to delete your account. Nothing was deleted.", "error")
            return redirect(url_for("accounts_page") + "#your-data")
        blocking = []
        for c in storage.list_careers():
            if me in c["members"]:
                with storage.session(c["token"]) as conn:
                    row = conn.execute("SELECT role FROM career_members WHERE username = ?", (me,)).fetchone()
                    if row and row["role"] == "race_master" and roles.race_master_count(conn, excluding=me) == 0:
                        blocking.append(c["name"])
        if g.user["is_master"] and sum(1 for u in auth.list_users() if u["is_master"]) <= 1:
            blocking.append("this site (you're its only administrator)")
        if blocking:
            flash("Hand over first: you're the only Race Master of " + ", ".join(blocking) +
                  ". Make someone else Race Master (Members & roles), then delete your account.", "error")
            return redirect(url_for("accounts_page") + "#your-data")
        for c in storage.list_careers():
            if me in c["members"]:
                with storage.session(c["token"]) as conn:
                    roles.remove_member(conn, me)
                    community.audit(conn, me, "Left the league", "", summary="deleted their account and left the league")
        security.end_other_sessions(me)
        auth.delete_user(me)
        session.clear()
        flash("Your account is deleted. Leagues keep their results; nobody can log in as you any more.", "success")
        return redirect(url_for("home"))

    @app.route("/privacy")
    def privacy_page():
        return render_template("legal.html", kind="privacy")

    @app.route("/terms")
    def terms_page():
        return render_template("legal.html", kind="terms")

    # ---------------------------------------------------------------- career library
    @app.route("/")
    def home():
        if not g.user:   # first visit: what Paddock Legacy is, before any login form
            return render_template("welcome.html", signups=auth.signups_allowed(),
                                   listed=len(_listed_leagues()), demo=demo.available())
        everything = storage.list_careers()
        careers = [c for c in everything if not c.get("demo")] if is_master() else \
            [c for c in everything if g.user["username"] in c["members"]]
        me = g.user["username"]
        outside = [c for c in everything if me not in c["members"] and not is_master()]
        joinable = [c for c in outside if c["join_mode"] == "requests" and me not in c["invited"]]
        invited = [c for c in outside if me in c["invited"]]
        return render_template("home.html", careers=careers, joinable=joinable, invited=invited,
                               leagues=library.user_leagues(g.user, everything, include_hidden=True),
                               by_token={c["token"]: c for c in everything}, may_create=onboarding.may_create(g.user),
                               join_modes=storage.JOIN_MODES, notify_presets=notices.PRESETS,
                               users=auth.list_users() if is_master() else [], default_year=2026)

    @app.route("/career/<token>/join", methods=["POST"])
    def career_join(token):
        driver_name = " ".join((request.form.get("driver_name") or "").split())[:60]
        role = request.form.get("role") or "driver"
        if role not in C.LEAGUE_ROLES:
            role = "driver"
        drives = role in ("driver", "driver_scorekeeper")
        if not drives:
            driver_name = ""
        try:
            with storage.session(token) as conn:
                mode = storage.join_mode(conn)
                if mode != "requests":
                    raise ValidationError("This league is invite only" if mode == "invite"
                                          else "This league is closed to new members")
                me = g.user["username"]
                if conn.execute("SELECT 1 FROM career_members WHERE username = ?", (me,)).fetchone():
                    raise ValidationError("You're already in this league")
                if conn.execute("SELECT 1 FROM join_requests WHERE username = ? AND status = 'Pending'", (me,)).fetchone():
                    raise ValidationError("Your request is already waiting for the Race Master")
                if drives:
                    if len(driver_name) < 2:
                        raise ValidationError("Choose a driver name")
                    if conn.execute("SELECT 1 FROM drivers WHERE lower(name) = lower(?)", (driver_name,)).fetchone():
                        raise ValidationError("There's already a driver with that name in this league")
                if not ratelimit.allow("join-request", me, JOIN_LIMIT, 3600):
                    raise ValidationError("You've sent a lot of join requests. Try again in an hour.")
                conn.execute("INSERT INTO join_requests(username, driver_name, message, created_at, role, notify_preset) "
                             "VALUES(?,?,?,?,?,?)", (me, driver_name, (request.form.get("message") or "").strip()[:300],
                                                     storage.now_iso(), role, _preset()))
                what = f"as {driver_name}" if drives else f"as {C.LEAGUE_ROLES[role]}"
                if role == "driver_scorekeeper":
                    what += " (and Scorekeeper)"
                feed.notify(conn, None, f"{g.user['display_name']} asked to join {what}", "members",
                            category="join_requests")
        except CareerNotFound:
            abort(404)
        except ValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("home"))
        flash("Request sent. You'll see the league here once the Race Master approves it.", "success")
        return redirect(url_for("home"))

    def _listed_leagues():
        out = []
        hidden = moderation.delisted()
        for c in storage.list_careers():
            if c.get("visibility") != "listed" or c.get("demo") or c["token"] in hidden:
                continue
            try:
                with storage.session(c["token"]) as conn:
                    prof = league_profile.profile(conn)
                    if prof["visibility"] != "listed":
                        continue
                    out.append({**c, **prof, "public_url": url_for("public_page", token=c["token"],
                                                                     key=community.public_key(conn))})
            except CareerNotFound:
                continue
        return out

    @app.route("/demo", methods=["GET", "POST"])
    def demo_start():
        """Explore a ready-made league. Each visitor gets a private copy that deletes itself; nothing real is touched."""
        if request.method == "GET":
            return render_template("demo.html", hours=demo.DEMO_HOURS)
        if g.get("user") and not g.user.get("is_demo"):
            flash("You're logged in, so the demo would sign you out. Log out first to try it.", "info")
            return redirect(url_for("home"))
        if not ratelimit.allow("demo", request.remote_addr or "?", 10, 3600):
            flash("Several demos were started from here recently. Please try again later.", "error")
            return redirect(url_for("demo_start"))
        if g.get("user") and g.user.get("is_demo"):   # restarting: the old copy and guest go straight away
            demo.discard(g.user["username"], session.get("demo"))
        username, token = demo.start()
        sign_in(username)
        session["demo"] = token
        return redirect(url_for("dashboard", token=token))

    @app.route("/leagues")
    def directory():
        """Leagues whose Race Master chose "Publicly discoverable". Nothing else is ever listed."""
        q = (request.args.get("q") or "").strip().lower()[:60]
        if q and not ratelimit.allow("directory-search", request.remote_addr or "?", 60, 60):
            flash("Too many searches at once. Wait a moment and try again.", "error")
            q = ""
        leagues = [l for l in _listed_leagues()
                   if not q or q in " ".join([l["name"], l["league_description"], l["league_region"],
                                              l["league_platform"]]).lower()]
        return render_template("directory.html", leagues=leagues, q=q)

    @app.route("/leagues/<token>/report", methods=["GET", "POST"])
    def report_league(token):
        """Moderation foundation: anyone can flag a public league for the site administrators to review."""
        listed = {l["token"]: l for l in _listed_leagues()}
        league = listed.get(storage.sanitize_token(token))
        if not league:
            abort(404)
        if request.method == "POST":
            if not ratelimit.allow("report", request.remote_addr or "?", 5, 3600):
                flash("You've sent several reports recently. Please try again later.", "error")
                return redirect(url_for("directory"))
            reason = request.form.get("reason") if request.form.get("reason") in moderation.REASONS else "other"
            moderation.report(league["token"], league["name"], reason, (request.form.get("details") or "")[:1000],
                              g.user["username"] if g.get("user") else None)
            flash("Thanks. The site administrators will review it.", "success")
            return redirect(url_for("directory"))
        return render_template("report.html", league=league, reasons=moderation.REASONS)

    @app.route("/leagues/new")
    def league_new_page():
        """The step-by-step new-league setup."""
        if not onboarding.may_create(g.user):
            flash("On this site only administrators can create leagues. Ask one, or join an existing league.", "info")
            return redirect(url_for("home"))
        return render_template("new_league.html", presets=onboarding.PRESETS, notify_presets=notices.PRESETS,
                               join_modes=storage.JOIN_MODES, visibility=league_profile.VISIBILITY,
                               default_year=2026, features=C.FEATURES, order_modes=C.TEAM_ORDER_MODES,
                               calendar=C.CALENDAR, teams=C.TEAMS)

    @app.route("/careers/new", methods=["POST"])
    def career_new():
        """Create a league. Anyone allowed to create one becomes its Race Master. Nothing is sent to anyone unless
        the creator ticked "send the invitations" on the review step."""
        if not onboarding.may_create(g.user):
            abort(403)
        name = (request.form.get("name") or "").strip()[:80] or "F1 League"
        token = storage.new_token()
        wizard = request.form.get("wizard") == "1"
        invites_to_mail = []
        try:
            if not is_master():
                onboarding.check_rate(g.user["username"])
            names = request.form.getlist("player_name")
            logins = request.form.getlist("player_login")          # site admins' quick form: link existing logins
            who = request.form.getlist("player_who")               # wizard: me / invite / none
            invite_to = request.form.getlist("player_invite")
            rows = []
            for i, n in enumerate(names):
                if not (n or "").strip():
                    continue
                rows.append({"name": n, "login": auth.normalise(logins[i]) if i < len(logins) and is_master() else "",
                             "who": who[i] if i < len(who) else "none",
                             "invite": auth.normalise(invite_to[i]) if i < len(invite_to) else ""})
            if sum(1 for r in rows if r["who"] == "me") > 1:
                raise ValidationError("You can only drive one of the player drivers")
            chosen = [r["login"] for r in rows if r["login"]] + [r["invite"] for r in rows if r["who"] == "invite" and r["invite"]]
            if len(chosen) != len(set(chosen)):
                raise ValidationError("One login can only drive one player driver")
            for r in rows:
                if r["who"] == "invite" and r["invite"] and not auth.get_user(r["invite"]):
                    raise ValidationError(f"There's no login called {r['invite']}. They can sign up first, "
                                          "or you can invite them later.")
            preset = onboarding.PRESETS.get(request.form.get("preset") or "")
            custom = not preset or request.form.get("preset") == "custom"
            with storage.session(token, create=True) as conn:
                S.seed_career(conn, token, name, request.form.get("year") or 2026, [r["name"] for r in rows])
                sid = S.current_season_id(conn)
                if request.form.get("calendar") == "blank":
                    conn.execute("DELETE FROM events WHERE season_id = ?", (sid,))
                elif wizard and not request.form.get("sprints"):
                    conn.execute("UPDATE events SET is_sprint = 0 WHERE season_id = ?", (sid,))
                mode = request.form.get("join_mode") or ("requests" if request.form.get("join_open") else "invite")
                storage.set_join_mode(conn, mode if mode in storage.JOIN_MODES else "requests")
                if custom:
                    feats = {k for k in C.FEATURES if request.form.get(f"feature_{k}")}
                    market_on = bool(request.form.get("rookie_market"))
                    life = (request.form.get("team_orders") or "off", bool(request.form.get("weekend_targets")) or not wizard,
                            bool(request.form.get("round_gates")) or not wizard)
                else:
                    feats, market_on = set(preset["features"]), preset["market"]
                    life = (preset["orders"], preset["targets"], preset["gates"])
                community.set_features(conn, feats)
                if wizard:   # the quick form leaves team-life settings at their defaults
                    teamlife.save_settings(conn, life[0], life[1], life[2], True, True)
                league_profile.save(conn, request.form)
                players = S.player_drivers(conn)
                creator = g.user["username"]
                my_driver = None
                for r, driver in zip(rows, players):
                    if r["who"] == "me":
                        my_driver = driver["id"]
                    elif r["login"]:
                        user = auth.get_user(r["login"])
                        if user:
                            roles.set_member(conn, user["username"], "race_master" if user["is_master"] else "member",
                                             driver["id"])
                    elif r["who"] == "invite" and r["invite"]:
                        conn.execute("INSERT OR REPLACE INTO invitations(username, role, invited_by, status, created_at, driver_id) "
                                     "VALUES(?, 'member', ?, 'Pending', ?, ?)", (r["invite"], creator, storage.now_iso(), driver["id"]))
                        invites_to_mail.append((r["invite"], f"to drive {driver['name']}"))
                mine = conn.execute("SELECT driver_id FROM career_members WHERE username = ?", (creator,)).fetchone()
                roles.set_member(conn, creator, "race_master", my_driver or (mine["driver_id"] if mine else None))
                notices.save(conn, creator, preset=_preset())
                for i, username in enumerate(request.form.getlist("invite_username")):
                    username = auth.normalise(username)
                    role = (request.form.getlist("invite_role") + ["member"] * 10)[i]
                    if not username or role not in ("member", "scorekeeper", "spectator"):
                        continue
                    if not auth.get_user(username):
                        raise ValidationError(f"There's no login called {username}")
                    if username == creator:
                        continue
                    conn.execute("INSERT OR REPLACE INTO invitations(username, role, invited_by, status, created_at) "
                                 "VALUES(?, ?, ?, 'Pending', ?)", (username, role, creator, storage.now_iso()))
                    invites_to_mail.append((username, f"as {C.ACCESS_ROLES[role]}"))
                if market_on and players:
                    market.open_window(conn, sid, kind="Rookie Draft")
                community.audit(conn, creator, "Created the league", name,
                                summary=f"created {name} ({(preset or {}).get('label', 'custom setup')}, {len(players)} player "
                                        f"driver{'s' if len(players) != 1 else ''})")
            if not is_master():
                onboarding.record_creation(g.user["username"])
        except (ValidationError, ValueError, auth.AuthError) as exc:
            try:
                storage.delete_career(token)
            except CareerNotFound:
                pass
            flash(str(exc), "error")
            return redirect(url_for("league_new_page") if wizard else url_for("home"))
        if invites_to_mail and request.form.get("send_invites"):
            for username, what in invites_to_mail:
                user = auth.get_user(username)
                if user and user.get("email") and not user.get("email_paused"):
                    mailer.send_later([user["email"]], f"You're invited to {name}",
                                      f"{g.user['display_name']} invited you to join the league \"{name}\" {what}. "
                                      f"Accept it from your league list:\n\n{url_for('home', _external=True)}\n\n"
                                      f"—\nSent by Paddock Legacy for the league \"{name}\".")
        flash("League created." + (f" {len(invites_to_mail)} invitation(s) are waiting in people's league list"
                                   + (" and were emailed." if request.form.get("send_invites") else ".")
                                   if invites_to_mail else "")
              + (" Rookie offers are waiting in each player's garage." if request.form.get("rookie_market") and rows else ""),
              "success")
        return redirect(url_for("dashboard", token=token))

    @app.route("/careers/import", methods=["POST"])
    @master_required
    def career_import():
        """Two steps: upload (checked and summarised, nothing registered yet), then confirm. It always becomes a new
        league with a new ID, so an import can never overwrite an existing one."""
        staging = storage.data_dir() / "imports"
        staging.mkdir(exist_ok=True)
        for old in staging.glob("*" + storage.CAREER_EXT):        # abandoned previews
            if time.time() - old.stat().st_mtime > 3600:
                old.unlink(missing_ok=True)
        staged_id = session.get("import_id")
        if request.form.get("confirm") and staged_id:
            staged = staging / (storage.sanitize_token(staged_id) + storage.CAREER_EXT)
            session.pop("import_id", None)
            if not staged.exists():
                flash("That upload has expired. Choose the file again.", "error")
                return redirect(url_for("home"))
            try:
                token = storage.import_career(str(staged))
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("home"))
            finally:
                staged.unlink(missing_ok=True)
            flash("League imported as a new league.", "success")
            return redirect(url_for("dashboard", token=token))
        if request.form.get("cancel"):
            if staged_id:
                (staging / (storage.sanitize_token(staged_id) + storage.CAREER_EXT)).unlink(missing_ok=True)
            session.pop("import_id", None)
            flash("Import cancelled. Nothing was added.", "info")
            return redirect(url_for("home"))
        upload = request.files.get("file")
        if not upload or not upload.filename:
            flash("Choose a .f1career file to import.", "error")
            return redirect(url_for("home"))
        if not upload.filename.lower().endswith(storage.CAREER_EXT):
            flash("Only .f1career files can be imported.", "error")
            return redirect(url_for("home"))
        staged_id = secrets.token_urlsafe(12)
        staged = staging / (staged_id + storage.CAREER_EXT)
        upload.save(str(staged))
        try:
            summary = storage.import_preview(str(staged))
        except (ValueError, sqlite3.DatabaseError) as exc:
            staged.unlink(missing_ok=True)
            flash(str(exc) if isinstance(exc, ValueError) else "That file is not a valid .f1career database", "error")
            return redirect(url_for("home"))
        session["import_id"] = staged_id
        return render_template("import_preview.html", summary=summary, filename=upload.filename)

    # ---------------------------------------------------------------- main pages
    @app.route("/career/<token>/dashboard")
    @career_page()
    def dashboard(conn, ctx):
        sid = ctx["season"]["id"]
        evs = S.events(conn, sid)
        nxt = S.next_incomplete_event(conn, sid)
        before = (ctx["season"]["year"], nxt["round_number"]) if nxt else None
        gate = gates.status(conn, nxt["id"]) if nxt and sid == ctx["current_season_id"] else None
        my_target = teamlife.target_for(conn, nxt["id"], ctx["my_driver"]["id"]) \
            if nxt and ctx["my_driver"] and ctx["team_life"]["targets"] else None
        return page("dashboard.html", ctx, events=evs, next_event=nxt,
                    completed=sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE),
                    drivers=insights.standings_with_changes(conn, sid, 8),
                    progress=insights.season_progress(conn, sid),
                    card=insights.driver_card(conn, sid, ctx["my_driver"]["id"]) if ctx["my_driver"] else None,
                    contract=market.current_contract(conn, ctx["my_driver"]["id"]) if ctx["my_driver"] else None,
                    constructors=S.constructor_standings(conn, sid)[:5],
                    rec=_recs_off(conn) or S.difficulty_recommendation(conn, before),
                    windows=[w for w in market.windows(conn) if w["status"] == C.WINDOW_OPEN],
                    news=feed.latest(conn, 6), chart=insights.progression_chart(conn, sid),
                    hub=_hub(conn, ctx, nxt) if nxt else None,
                    circuit=circuits.lookup(nxt["name"], nxt["location"]) if nxt else None,
                    press_pens=teamlife.press_pens(conn, ctx["current_season_id"], ctx["my_driver"]["id"])
                    if ctx["my_driver"] and sid == ctx["current_season_id"] else [],
                    gate=gate, my_target=my_target,
                    pending=insights.pending_actions(conn, ctx) if sid == ctx["current_season_id"] else [],
                    notices_=announcements.visible(conn, g.user["username"], ctx.get("real", ctx).get("role"),
                                                   ctx["my_driver"]["id"] if ctx["my_driver"] else None,
                                                   manager=ctx.get("real", ctx)["is_master"]),
                    can_finish=bool(evs) and all(e["status"] == C.EVENT_COMPLETE for e in evs))

    @app.route("/career/<token>/weekend/<int:event_id>")
    @career_page()
    def weekend(conn, ctx, event_id):
        event = S.get_event(conn, event_id)
        if not event:
            abort(404)
        season = S.get_season(conn, event["season_id"])
        if season["id"] != ctx["season"]["id"]:
            ctx["season"] = season
            session[f"season_{ctx['token']}"] = season["id"]
        evs = S.events(conn, season["id"])
        idx = next(i for i, e in enumerate(evs) if e["id"] == event_id)
        return page("weekend.html", ctx, event=event, rows=S.weekend_rows(conn, event_id),
                    prev_event=evs[idx - 1] if idx > 0 else None,
                    next_event=evs[idx + 1] if idx + 1 < len(evs) else None, index=idx + 1, total=len(evs),
                    rec=_recs_off(conn, event) or _weekend_recommendation(conn, season, event),
                    entrants=_entrants(conn, event_id),
                    gp_points=C.GP_POINTS, sprint_points=C.SPRINT_POINTS, hub=_hub(conn, ctx, event, full=True),
                    incidents=community.incidents(conn, event_id=event_id),
                    share=_share_card(conn, ctx, event) if event["status"] == C.EVENT_COMPLETE else None,
                    gate=gates.status(conn, event_id), reminded=gates.reminded(conn, event_id))

    def _entrants(conn, event_id):
        """The drivers in this round, for the screenshot importer to match against (never anyone else)."""
        return [{"id": r["driver_id"], "name": r["driver"]["name"], "team": r["team"]["name"],
                 "is_player": bool(r["driver"]["is_player"]), "color": r["driver"]["player_color"]}
                for r in S.weekend_rows(conn, event_id)]

    def _recs_off(conn, event=None):
        """A league can switch recommendations off; the difficulty used is still recorded each round."""
        if storage.get_meta(conn, "difficulty_recs", "1") == "1":
            return None
        return {"disabled": True, "recommended": None, "direction": None, "for_next": False, "sample": [], "used": [],
                "excluded": [], "recent": [], "reason": "AI difficulty recommendations are off in this league. "
                "The difficulty used each round is still recorded.", "current": event["ai_difficulty"] if event else None}

    def _weekend_recommendation(conn, season, event):
        """On a completed round the recommendation includes that round (it's the advice for the next one);
        before completion it's the advice for this round, from the rounds before it."""
        if event["status"] == C.EVENT_COMPLETE:
            rec = S.difficulty_recommendation(conn, (season["year"], event["round_number"] + 1))
            rec["for_next"] = True
            if event["ai_difficulty"] is None:
                rec["this_round"] = "This round was marked \"Don't track\", so it isn't part of the history."
            return rec
        rec = S.difficulty_recommendation(conn, (season["year"], event["round_number"]))
        rec["for_next"] = False
        if event["ai_difficulty"] is not None:
            rec["this_round"] = (f"AI {event['ai_difficulty']} is recorded for this round. It counts toward the "
                                 "recommendation once the round is completed.")
            if not rec["history_rounds"]:
                rec["reason"] = rec["this_round"]
        return rec

    @app.route("/career/<token>/weekend/<int:event_id>/reopen", methods=["POST"])
    @career_page(master_only=True)
    def weekend_reopen(conn, ctx, event_id):
        """Race Master only: reopen a submitted round so it can be corrected (Scorekeepers can edit it again)."""
        event = S.get_event(conn, event_id)
        if not event:
            abort(404)
        if event["status"] != C.EVENT_COMPLETE:
            flash("That round isn't submitted, so there's nothing to reopen.", "info")
        else:
            conn.execute("UPDATE events SET status = ?, revision = revision + 1 WHERE id = ?",
                         (C.EVENT_IN_PROGRESS, event_id))
            g.audit_summary = (f"reopened {event_label(event, S.get_season(conn, event['season_id'])['year'])} "
                               "so a Scorekeeper can correct it")
            flash(f"R{event['round_number']} {event['name']} reopened. Standings keep counting its results; submit it "
                  "again when the corrections are done.", "success")
        return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))

    @app.route("/career/<token>/weekend/<int:event_id>/summary")
    @career_page()
    def race_summary(conn, ctx, event_id):
        event = S.get_event(conn, event_id)
        if not event:
            abort(404)
        if event["status"] != C.EVENT_COMPLETE:
            flash("The summary appears once this round is marked complete.", "info")
            return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))
        season = S.get_season(conn, event["season_id"])
        if season["id"] != ctx["season"]["id"]:
            ctx["season"] = season
        evs = S.events(conn, season["id"])
        nxt = next((e for e in evs if e["round_number"] > event["round_number"]), None)
        return page("race_summary.html", ctx, s=insights.race_summary(conn, event_id), next_event=nxt)

    def _share_card(conn, ctx, event):
        """Everything the result card image needs (it's drawn in the browser)."""
        story = community.race_story(conn, event["id"])
        card = {"league": ctx["career_name"], "season": ctx["season"]["year"], "round": event["round_number"],
                "event": event["name"], "location": event["location"],
                "podium": [{"name": r["driver"]["name"], "team": r["team"]["name"], "color": r["team"]["color"]}
                           for r in story["podium"]]}
        if ctx["my_driver"]:
            row = next((r for r in S.weekend_rows(conn, event["id"]) if r["driver_id"] == ctx["my_driver"]["id"]), None)
            if row:
                finished = row["result_status"] == C.STATUS_FINISHED and row["race_position"]
                card["me"] = {"name": row["driver"]["name"], "team": row["team"]["name"], "color": row["team"]["color"],
                              "result": f"P{row['race_position']}" if finished else row["result_status"],
                              "grid": f"P{row['qualifying_position']}" if row["qualifying_position"] else "—",
                              "points": row["gp_points"] + row["sprint_pts"],
                              "gained": (row["qualifying_position"] - row["race_position"])
                              if finished and row["qualifying_position"] else None}
        return card

    @app.route("/career/<token>/weekend")
    @career_page()
    def weekend_next(conn, ctx):
        nxt = S.next_incomplete_event(conn, ctx["season"]["id"]) or (S.events(conn, ctx["season"]["id"]) or [None])[-1]
        if not nxt:
            abort(404)
        return redirect(url_for("weekend", token=ctx["token"], event_id=nxt["id"]))

    @app.route("/career/<token>/drivers")
    @career_page()
    def drivers_page(conn, ctx):
        standings = S.driver_standings(conn, ctx["season"]["id"])
        return page("drivers.html", ctx, standings=standings, others=S.drivers_off_grid(conn, ctx["season"]["id"], standings),
                    teams=S.teams(conn), chart=insights.progression_chart(conn, ctx["season"]["id"], top=6))

    @app.route("/career/<token>/results")
    @career_page()
    def results_index(conn, ctx):
        """Every round of the selected season with its state and headline result."""
        sid = ctx["season"]["id"]
        rounds = []
        dmap = S.driver_map(conn)
        for e in S.events(conn, sid):
            code, label = timefmt.race_status(e["race_at"], e["status"], ctx["race_window"], postponed=e["postponed"])
            r = {"event": e, "state": code, "state_label": label, "winner": None, "pole": None, "players": []}
            if e["status"] != C.EVENT_NOT_RUN:
                rows = S.weekend_rows(conn, e["id"])
                r["winner"] = next((x for x in rows if x["race_position"] == 1 and x["result_status"] == C.STATUS_FINISHED), None)
                r["pole"] = next((x for x in rows if x["qualifying_position"] == 1), None)
                r["players"] = [x for x in rows if x["driver"]["is_player"]]
            rounds.append(r)
        return page("results_index.html", ctx, rounds=rounds, dmap=dmap)

    @app.route("/career/<token>/standings")
    @career_page()
    def standings_page(conn, ctx):
        """Drivers' and Constructors' championships, with CSV export."""
        sid = ctx["season"]["id"]
        drivers = insights.standings_with_changes(conn, sid, limit=10 ** 6)
        teams = S.constructor_standings(conn, sid)
        fmt = request.args.get("format")
        if fmt == "csv":
            import csv
            buf = io.StringIO()
            w = csv.writer(buf)
            if request.args.get("table") == "constructors":
                w.writerow(["Position", "Team", "Points", "Wins", "Podiums"])
                for t in teams:
                    w.writerow([t["position"], t["team"]["name"], t["points"], t.get("wins", 0), t.get("podiums", 0)])
                name = f"constructors-{ctx['season']['year']}.csv"
            else:
                w.writerow(["Position", "Driver", "Team", "Points", "Wins", "Podiums", "Poles", "Fastest laps", "DNFs",
                            "Player driver"])
                for d in drivers:
                    w.writerow([d["position"], d["driver"]["name"], d["team"]["name"] if d["team"] else "", d["points"],
                                d["wins"], d["podiums"], d["poles"], d["fastest_laps"], d["dnfs"],
                                "yes" if d["driver"]["is_player"] else "no"])
                name = f"drivers-{ctx['season']['year']}.csv"
            return send_file(io.BytesIO(buf.getvalue().encode("utf-8")), as_attachment=True, download_name=name,
                             mimetype="text/csv")
        recent = {}
        for r in conn.execute("""SELECT r.driver_id, r.race_position, r.result_status, e.round_number FROM results r
                                 JOIN events e ON e.id = r.event_id WHERE e.season_id = ? AND e.status = ?
                                 ORDER BY e.round_number DESC""", (sid, C.EVENT_COMPLETE)):
            lst = recent.setdefault(r["driver_id"], [])
            if len(lst) < 5:
                lst.append(f"P{r['race_position']}" if r["result_status"] == C.STATUS_FINISHED and r["race_position"]
                           else r["result_status"])
        return page("standings.html", ctx, drivers=drivers, teams=teams, recent=recent,
                    leader=max([t["points"] for t in teams] + [1]))

    @app.route("/career/<token>/stats")
    @career_page()
    def stats_page(conn, ctx):
        """Season statistics from submitted rounds only: progression, finishes, qualifying vs race, Sprints,
        teammates, reliability and season-over-season."""
        sid = ctx["season"]["id"]
        players_only = request.args.get("who") == "players"
        rows = stats.season(conn, sid, players_only)
        standings = S.driver_standings(conn, sid, completed_only=True)
        picked = [r["driver"] for r in standings if r["driver"]["is_player"] or (not players_only and r["position"] <= 6)]
        labels, values = insights.points_progression(conn, sid, [d["id"] for d in picked], completed_only=True) if picked else ([], {})
        chart = {"labels": labels, "yLabel": "Points", "markers": len(labels) < 12,
                 "series": [{"name": d["name"], "values": values.get(d["id"], []), "player": bool(d["is_player"]),
                             "color": d.get("player_color")} for d in picked]} if labels else None
        years, sos = stats.season_over_season(conn, players_only=True)
        pairs = stats.teammates(conn, sid)
        if players_only:
            pairs = [p for p in pairs if p["a"]["is_player"] or p["b"]["is_player"]]
        return page("stats.html", ctx, rows=rows, sprint=stats.sprint_table(rows), chart=chart,
                    reliability=stats.teams_reliability(conn, sid), pairs=pairs, years=years, sos=sos,
                    players_only=players_only)

    @app.route("/api/career/<token>/search")
    @career_page()
    def api_search(conn, ctx):
        """Quick search for the command palette: this league only, never anything the viewer can't open."""
        q = (request.args.get("q") or "").strip().lower()
        t = ctx["token"]
        items = []

        def add(kind, label, url, sub=""):
            items.append({"kind": kind, "label": label, "url": url, "sub": sub})
        pages = [("Home", url_for("dashboard", token=t)), ("Calendar", url_for("seasons_page", token=t)),
                 ("Results", url_for("results_index", token=t)), ("Standings", url_for("standings_page", token=t)),
                 ("Drivers", url_for("drivers_page", token=t)), ("Teams", url_for("teams_page", token=t)),
                 ("Records", url_for("records", token=t)), ("News", url_for("news_page", token=t)),
                 ("Incidents", url_for("incidents_page", token=t)), ("My notifications", url_for("notify_prefs", token=t)),
                 ("Help", url_for("help_page"))]
        if ctx["my_driver"]:
            pages += [("My Garage", url_for("garage", token=t)), ("Relationships", url_for("team_standing", token=t))]
        if ctx["can_run"]:
            pages.append(("Enter results", url_for("weekend_next", token=t)))
        if ctx["is_master"]:
            pages += [("League settings", url_for("league_settings", token=t)), ("Members & roles", url_for("members", token=t)),
                      ("Grid & contracts", url_for("grid_page", token=t)), ("Activity log", url_for("activity_log", token=t)),
                      ("Backups & data", url_for("backups_page", token=t)), ("Market administration", url_for("market_page", token=t)),
                      ("Notification delivery log", url_for("delivery_log_page", token=t)),
                      ("Settings: team life", url_for("league_settings", token=t) + "#team-life"),
                      ("Settings: joining", url_for("league_settings", token=t) + "#joining"),
                      ("Settings: season rollover", url_for("league_settings", token=t) + "#rollover")]
        for label, url in pages:
            add("Page", label, url)
        for d in S.drivers(conn):
            add("Driver", d["name"], url_for("driver_profile", token=t, driver_id=d["id"]),
                "Player driver" if d["is_player"] else ("Retired" if not d["active"] else "AI driver"))
        for tm in S.teams(conn):
            add("Team", tm["name"], url_for("team_profile", token=t, team_id=tm["id"]), tm["abbreviation"])
        for e in S.events(conn, ctx["season"]["id"]):
            add("Round", f"R{e['round_number']} {e['name']}", url_for("weekend", token=t, event_id=e["id"]),
                f"{ctx['season']['year']} · {e['status']}")
        for s_ in ctx["seasons"]:
            add("Season", f"{s_['year']} season", url_for("season_review", token=t, season_id=s_["id"]), s_["status"])
        for anchor, label in HELP_TOPICS:
            add("Help", label, url_for("help_page") + "#" + anchor)
        if q:
            words = q.split()
            items = [i for i in items if all(w in (i["label"] + " " + i["sub"] + " " + i["kind"]).lower() for w in words)]
            items.sort(key=lambda i: (not i["label"].lower().startswith(q), i["kind"] != "Page", i["label"]))
        return jsonify(ok=True, items=items[:40])

    @app.route("/career/<token>/backups")
    @career_page(master_only=True)
    def backups_page(conn, ctx):
        """Backups, restore, export and the danger zone for this league."""
        check = storage.integrity_check(ctx["token"]) if request.args.get("check") else None
        return page("backups.html", ctx, backups=storage.list_auto_backups(ctx["token"]), check=check)

    @app.route("/career/<token>/driver/<int:driver_id>")
    @career_page()
    def driver_profile(conn, ctx, driver_id):
        driver = S.driver_map(conn).get(driver_id)
        if not driver:
            abort(404)
        timeline = S.driver_timeline(conn, driver_id)
        trophies = []
        for t in timeline:
            if t["season"]["status"] == C.SEASON_COMPLETE or t["season"]["id"] == ctx["current_season_id"]:
                for a in insights.season_review(conn, t["season"]["id"])["awards"]:
                    if a["driver"]["id"] == driver_id:
                        trophies.append({"year": t["season"]["year"], "title": a["title"], "value": a["value"],
                                         "live": t["season"]["status"] != C.SEASON_COMPLETE})
        owner = next((u for u, d in community.member_driver_ids(conn).items() if d == driver_id), None)
        return page("driver_profile.html", ctx, driver=driver, timeline=timeline,
                    totals=S.career_totals(timeline), contract=market.current_contract(conn, driver_id),
                    trend=insights.driver_round_timeline(conn, driver_id), profile=community.profile(conn, driver_id),
                    contracts=community.contract_history(conn, driver_id), trophies=trophies,
                    can_edit=_may_edit_profile(ctx, driver_id), nationalities=community.NATIONALITIES,
                    owner=auth.get_user(owner) if owner else None,
                    battles=battle.pairings(conn, ctx["season"]["id"], driver_id),
                    seat_state=seats.state(conn, ctx["season"]["id"], driver_id),
                    changes=insights.stat_changes(conn, ctx["season"]["id"], driver_id)
                    if any(t["season"]["id"] == ctx["season"]["id"] for t in timeline) else None)

    @app.route("/career/<token>/teams")
    @career_page()
    def teams_page(conn, ctx):
        table = S.constructor_standings(conn, ctx["season"]["id"])
        return page("teams.html", ctx, table=table, leader=max([t["points"] for t in table] + [1]),
                    ratings=S.car_ratings(conn, ctx["season"]["id"]))

    @app.route("/career/<token>/team/<int:team_id>")
    @career_page()
    def team_profile(conn, ctx, team_id):
        team = S.team_map(conn).get(team_id)
        if not team:
            abort(404)
        archive, totals = S.team_history(conn, team_id)
        return page("team_profile.html", ctx, team=team, archive=archive, totals=totals,
                    details=S.team_details(conn, team_id, ctx["season"]["id"]),
                    battles=battle.team_battles(conn, ctx["season"]["id"], team_id),
                    seat_states={s["driver"]["id"]: s for s in seats.season_states(conn, ctx["season"]["id"])})

    @app.route("/career/<token>/grid")
    @career_page()
    def grid_page(conn, ctx):
        sid = ctx["season"]["id"]
        seats_ = S.driver_seats(conn, sid)
        return page("grid.html", ctx, grid=S.grid(conn, sid), players=S.player_drivers(conn), seats=seats_,
                    dismissals=[u for u in ultimatums.for_season(conn, sid) if u["status"] != "Void"],
                    dmap=S.driver_map(conn), tmap=S.team_map(conn),
                    all_drivers=S.drivers(conn, active_only=True), states=seats.season_states(conn, sid),
                    contract_rows=seats.contract_list(conn, sid))

    @app.route("/career/<token>/seats/<int:driver_id>", methods=["POST"])
    @career_page(master_only=True)
    def seat_resolve(conn, ctx, driver_id):
        """The repair tool: settle one driver's seat/contract state for the selected season without touching history."""
        sid = ctx["season"]["id"]
        st = seats.state(conn, sid, driver_id)
        if not st["driver"] or not st["driver"]["is_player"]:
            abort(404)
        if S.get_season(conn, sid)["status"] == C.SEASON_COMPLETE:
            raise ValidationError("That season is archived. Switch to the current season to change seats.")
        action, note = request.form.get("action"), (request.form.get("note") or "").strip()
        name, year = st["driver"]["name"], st["year"]
        if action == "renew":
            if not st["seat"]:
                raise ValidationError(f"{name} has no seat to record a contract for")
            years = request.form.get("years", type=int) or 1
            seats.record_contract(conn, driver_id, st["seat"][0], year, years, request.form.get("role") or "Equal Status",
                                  note=note)
            seats.clear_flag(conn, sid, driver_id)
            summary = f"recorded a {years}-year contract for {name} with {st['team']['name']} from {year}"
        elif action in seats.FLAGS:
            if not st["seat"]:
                raise ValidationError(f"{name} has no seat")
            seats.set_flag(conn, sid, driver_id, action, note, g.user["username"])
            summary = f"marked {name}'s {year} seat at {st['team']['name']} as {seats.KINDS[action][0].lower()}"
        elif action == "release":
            S.place_players(conn, sid, {driver_id: None})
            seats.clear_flag(conn, sid, driver_id)
            summary = f"changed {name}'s {year} seat from {st['team']['name'] if st['team'] else 'none'} to Free Agent"
        else:
            raise ValidationError("Choose what should happen")
        g.audit_summary, g.audit_link = summary, "grid#contracts"
        after = seats.state(conn, sid, driver_id)
        flash(f"{name}: {after['label']}.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]) + "#contracts")

    @app.route("/career/<token>/grid/players", methods=["POST"])
    @career_page(master_only=True)
    def grid_players(conn, ctx):
        targets = {}
        for p in S.player_drivers(conn):
            raw = request.form.get(f"seat_{p['id']}", "")
            if raw:
                try:
                    team_id, seat_no = (int(x) for x in raw.split(":"))
                except ValueError:
                    raise ValidationError("Invalid seat selection")
                targets[p["id"]] = (team_id, seat_no)
            else:
                targets[p["id"]] = None
        S.place_players(conn, ctx["season"]["id"], targets)
        flash("Player seats updated.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]))

    @app.route("/career/<token>/grid/save", methods=["POST"])
    @career_page(master_only=True)
    def grid_save(conn, ctx):
        sid = ctx["season"]["id"]
        submitted = {}
        for team_id, seat_no in S.grid_map(conn, sid):
            key = f"seat_{team_id}_{seat_no}"
            if key in request.form:
                submitted[(team_id, seat_no)] = request.form.get(key)
        S.save_full_grid(conn, sid, submitted)
        flash("Grid saved. Future rounds now use this lineup.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]))

    @app.route("/career/<token>/contracts", methods=["GET", "POST"])
    @career_page()
    def contracts_page(conn, ctx):
        if request.method == "POST":
            if not ctx["is_master"]:
                abort(403)
            S.add_contract(conn, ctx["season"]["id"], request.form)
            flash("Negotiation added.", "success")
            return redirect(url_for("contracts_page", token=ctx["token"]))
        return page("contracts.html", ctx, contracts=S.contracts(conn, ctx["season"]["id"]),
                    drivers=S.drivers(conn, active_only=True), teams=S.teams(conn),
                    overview=market.overview(conn, ctx["current_season_id"]))

    @app.route("/career/<token>/contracts/<int:contract_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def contract_delete(conn, ctx, contract_id):
        conn.execute("DELETE FROM contracts WHERE id = ?", (contract_id,))
        flash("Negotiation deleted.", "success")
        return redirect(url_for("contracts_page", token=ctx["token"]))

    @app.route("/career/<token>/records")
    @career_page()
    def records(conn, ctx):
        rows = S.hall_of_records(conn)

        def leader(key):
            """The record holder, or None while nobody has recorded any (no name for a 0-0-0 tie)."""
            best = max(rows, key=lambda r: (r[key], r["points"]), default=None)
            if not best or not best[key]:
                return None
            best = dict(best)
            best["tied"] = sum(1 for r in rows if r[key] == best[key]) - 1
            return best
        return page("records.html", ctx, rows=rows, all_time=insights.all_time_records(conn), leaders={
            "points": leader("points"), "wins": leader("wins"), "poles": leader("poles"), "titles": leader("titles")})

    def _calendar_warnings(evs):
        """Schedule conflicts: two rounds at the same time or within three hours, gaps in round numbers."""
        from datetime import datetime as _dt
        out = []
        timed = sorted((e for e in evs if e["race_at"]), key=lambda e: e["race_at"])
        for a, b in zip(timed, timed[1:]):
            try:
                gap = (_dt.fromisoformat(b["race_at"].replace("Z", "+00:00")) -
                       _dt.fromisoformat(a["race_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            except ValueError:
                continue
            if gap < 3:
                out.append(f"R{a['round_number']} {a['name']} and R{b['round_number']} {b['name']} are scheduled "
                           + ("at the same time." if gap == 0 else f"only {gap:.1f} hours apart."))
        order = [e for e in sorted(evs, key=lambda e: e["round_number"]) if e["race_at"]]
        for a, b in zip(order, order[1:]):
            if b["race_at"] < a["race_at"]:
                out.append(f"R{b['round_number']} {b['name']} is scheduled before R{a['round_number']} {a['name']}.")
        numbers = sorted(e["round_number"] for e in evs)
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            out.append("Round numbers have gaps: " + ", ".join(f"R{n}" for n in numbers) + ".")
        return out

    @app.route("/career/<token>/calendar.ics")
    @career_page()
    def calendar_ics(conn, ctx):
        """The season's scheduled races as a calendar file (Google, Apple, Outlook...)."""
        return _ics_response(ctx["career_name"], ctx["season"], S.events(conn, ctx["season"]["id"]),
                             url_for("weekend", token=ctx["token"], event_id=0, _external=True).rsplit("/", 1)[0])

    @app.route("/career/<token>/seasons")
    @career_page()
    def seasons_page(conn, ctx):
        seasons = S.list_seasons(conn)
        latest = seasons[-1] if seasons else None
        evs_ = S.events(conn, ctx["season"]["id"])
        return page("seasons.html", ctx, seasons_list=seasons, events=evs_, warnings=_calendar_warnings(evs_),
                    months=timefmt.month_grid(evs_, ctx["timezone"]),
                    next_year=(latest["year"] + 1) if latest else 2026, latest=latest,
                    all_complete=all(e["status"] == C.EVENT_COMPLETE for e in S.events(conn, latest["id"])))

    @app.route("/career/<token>/seasons/switch", methods=["POST"])
    @career_page(master_only=True)
    def season_switch(conn, ctx):
        sid = _form_int("season_id")
        S.make_current(conn, sid)
        session[f"season_{ctx['token']}"] = sid
        flash("Current season changed.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    @app.route("/career/<token>/seasons/rollover")
    @career_page(master_only=True)
    def season_rollover(conn, ctx):
        """Step 1 of starting a new season: what happens to every player driver's seat and contract."""
        latest = S.list_seasons(conn)[-1]
        year = request.args.get("year", type=int) or latest["year"] + 1
        evs = S.events(conn, latest["id"])
        return page("rollover.html", ctx, latest=latest, year=year, review=seats.rollover_review(conn, latest["id"], year),
                    actions=seats.ACTIONS, default=seats.carry_mode(conn),
                    unfinished=[e for e in evs if e["status"] != C.EVENT_COMPLETE])

    @app.route("/career/<token>/seasons/new", methods=["POST"])
    @career_page(master_only=True)
    def season_new(conn, ctx):
        latest = S.list_seasons(conn)[-1]
        year = request.form.get("year", type=int) or latest["year"] + 1
        review = seats.rollover_review(conn, latest["id"], year)
        if review["conflicts"]:
            raise ValidationError("Some teams have more signed drivers than seats for " + str(year) + ". Resolve them "
                                  "in Grid & contracts first: " + "; ".join(c["team"]["name"] for c in review["conflicts"]))
        decisions = {}
        for r in review["rows"]:
            if r["needs_decision"]:
                action = request.form.get(f"decision_{r['driver']['id']}")
                if action not in seats.ACTIONS:
                    raise ValidationError(f"Choose what happens to {r['driver']['name']}'s seat (their contract ends) "
                                          "before starting the new season.")
                decisions[r["driver"]["id"]] = action
        try:  # a safety copy before the season changes; failing to write it stops the rollover
            storage.auto_backup(ctx["token"], f"before-{year}-season", force=True)
        except Exception:
            app.logger.exception("backup before rollover failed")
            raise ValidationError("Couldn't make a backup first, so nothing was changed. Try again.")
        released = relations.decide_releases(conn, latest["id"], final=True)
        relations.settle(conn, latest["id"])
        new_id = S.create_next_season(conn, latest["id"], year)
        rewarded = relations.apply_rewards(conn, latest["id"], new_id)
        goal_changes = teamgoals.apply_rewards(conn, latest["id"], new_id)
        changes = S.develop_cars(conn, latest["id"], new_id, random.Random())
        feed.on_new_season(conn, latest["id"], new_id, changes, f"review/{latest['id']}")
        market.on_new_season(conn, new_id, previous_id=latest["id"])
        seats.apply_rollover_decisions(conn, latest["id"], new_id, decisions, g.user["username"])
        dmap = S.driver_map(conn)
        g.audit_summary = (f"started the {year} season" + (": " + "; ".join(
            f"{dmap[d]['name']} {({'renew': 'renewed', 'provisional': 'kept provisionally', 'release': 'released'})[a]}"
            for d, a in decisions.items()) if decisions else ""))
        left = seats.problems(conn, new_id)
        if left:
            flash(f"{len(left)} seat/contract problem(s) still need attention: see Grid & Contracts.", "error")
        if goal_changes:
            met = sum(1 for v in goal_changes.values() if v > 0)
            flash(f"Team goals settled: {met} of {len(goal_changes)} player driver(s) gain Reputation from their "
                  "team's goal.", "success")
        if rewarded:
            flash(f"{len(rewarded)} player driver(s) kept their pledge and start the new season with extra Reputation.",
                  "success")
        if released:
            flash(f"{len(released)} player driver(s) were released by their team at the end of the season.", "success")
        session[f"season_{ctx['token']}"] = new_id
        flash("New season created. A backup of the previous state was saved first. Review the grid.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]))

    @app.route("/career/<token>/calendar/save", methods=["POST"])
    @career_page(master_only=True)
    def calendar_save(conn, ctx):
        sid = ctx["season"]["id"]
        history = request.form.get("historical_correction") == "1"
        if S.get_season(conn, sid)["status"] == C.SEASON_COMPLETE and not history:
            raise ValidationError(f"The {ctx['season']['year']} season is archived. Turn on historical correction mode "
                                  "to change its calendar.")
        entries = []
        for e in S.events(conn, sid):
            entries.append({"id": e["id"], "round_number": request.form.get(f"round_{e['id']}"),
                            "name": request.form.get(f"name_{e['id']}"),
                            "location": request.form.get(f"location_{e['id']}"),
                            "is_sprint": request.form.get(f"sprint_{e['id']}")})
        S.save_calendar(conn, sid, entries, history=history)
        if history:
            g.audit_summary = f"corrected the archived/completed {ctx['season']['year']} calendar (historical correction mode)"
        flash("Calendar saved.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    # ---------------------------------------------------------------- transfer market & garage
    @app.route("/career/<token>/garage")
    @career_page()
    def garage(conn, ctx):
        return _garage_view(conn, ctx, "garage")

    @app.route("/career/<token>/offers")
    @career_page()
    def offers_page(conn, ctx):
        """Contracts & offers: negotiations, approaching teams and offer history, on their own page."""
        return _garage_view(conn, ctx, "offers")

    def _garage_view(conn, ctx, view):
        players = S.player_drivers(conn)
        wanted = request.args.get("driver", type=int)
        driver = None
        if wanted and (ctx["is_master"] or (ctx["my_driver"] and ctx["my_driver"]["id"] == wanted)):
            driver = next((p for p in players if p["id"] == wanted), None)
        driver = driver or ctx["my_driver"] or (players[0] if ctx["is_master"] and players else None)
        if not driver:
            abort(403)
        sid = ctx["season"]["id"]
        me, interest = market.team_interest(conn, sid, driver["id"])
        standings = S.driver_standings(conn, sid)
        row = next((r for r in standings if r["driver_id"] == driver["id"]), None)
        seat = S.driver_seats(conn, sid).get(driver["id"])
        teammate = None
        if seat:
            mate_id = S.grid_map(conn, sid).get((seat[0], 2 if seat[1] == 1 else 1))
            teammate = S.driver_map(conn).get(mate_id)
        by_id = {r["driver_id"]: r for r in standings}
        rivals = [{"driver": p, "row": by_id.get(p["id"])} for p in players if p["id"] != driver["id"]]
        recent = conn.execute("""SELECT r.*, e.name AS event_name, e.round_number, e.is_sprint FROM results r
                                 JOIN events e ON e.id = r.event_id WHERE r.driver_id = ? AND e.season_id = ?
                                 AND e.status != ? ORDER BY e.round_number DESC LIMIT 6""",
                              (driver["id"], sid, C.EVENT_NOT_RUN)).fetchall()
        own = ctx["my_driver"] and ctx["my_driver"]["id"] == driver["id"]
        window = conn.execute("SELECT * FROM market_windows WHERE status = ? ORDER BY target_year DESC, id DESC",
                              (C.WINDOW_OPEN,)).fetchone()
        signed_in_window = bool(window and conn.execute(
            "SELECT 1 FROM offers WHERE window_id = ? AND driver_id = ? AND status = ?",
            (window["id"], driver["id"], C.OFFER_ACCEPTED)).fetchone())
        return page("garage.html", ctx, view=view, driver=driver, me=me, interest=interest, row=row,
                    seat_state=seats.state(conn, sid, driver["id"]),
                    team=S.team_map(conn).get(seat[0]) if seat else None, teammate=teammate,
                    rivals=rivals, recent=recent, players=players,
                    offers=market.offers(conn, driver_id=driver["id"]), can_respond=own or ctx["is_master"],
                    contract=market.current_contract(conn, driver["id"]), own=own,
                    rookie=market.career_starts(conn, driver["id"]) == 0,
                    experience=market.experience(conn, driver["id"]), window=window,
                    approaches=market.approaches_left(conn, window["id"], driver["id"]) if window else 0,
                    approachable=market.approachable_teams(conn, window["id"], driver["id"]) if window else [],
                    signed_in_window=signed_in_window, pledges=_pledge_preview(conn, sid, driver["id"]),
                    value_parts=_value_parts(me, interest),
                    locked=market.locked_in(conn, ctx["current_season_id"], driver["id"],
                                            window["target_year"] if window else ctx["season"]["year"] + 1),
                    trend=insights.driver_round_timeline(conn, driver["id"]),
                    changes=insights.stat_changes(conn, sid, driver["id"]))

    def _value_parts(me, interest):
        """Driver Value split into what it's made of, plus how far the next team up is."""
        parts = [("Reputation", round(0.4 * me["reputation"], 1), f"{me['reputation']} × 0.4"),
                 ("Form", round(0.4 * me["form"], 1), f"{me['form']} × 0.4"),
                 ("Beating the car", round(0.2 * me["car"], 1), f"{me['car']} × 0.2"),
                 ("Teammate head-to-head", me["h2h_bonus"], "±4")]
        cleared = [i for i in interest if i["bar"] <= me["value"] and not i["current"]]
        above = sorted((i for i in interest if i["bar"] > me["value"] and not i["current"]), key=lambda i: i["bar"])
        return {"parts": parts, "cleared": len(cleared), "next": above[0] if above else None,
                "gap": round(above[0]["bar"] - me["value"], 1) if above else 0}

    def _pledge_preview(conn, season_id, driver_id):
        """What each growth pledge would mean at each team, for the offer cards and counter forms."""
        ranks = S.team_strength_ranks(conn, season_id)
        out = {}
        for team in S.teams(conn):
            out[team["id"]] = [relations.targets_for(conn, season_id, driver_id, team["id"], i, ranks)
                               for i in range(len(C.GROWTH_LEVELS))]
        return out

    @app.route("/career/<token>/me")
    @career_page()
    def my_settings(conn, ctx):
        """Settings that belong to you in this league, whatever your role: notifications, your driver, how the
        league appears in your list, change notices, and leaving."""
        me = g.user["username"]
        member = conn.execute("SELECT * FROM career_members WHERE username = ?", (me,)).fetchone()
        mine = ctx.get("real", ctx).get("my_driver")
        lib = next((c for c in library.user_leagues(g.user, include_hidden=True) if c["token"] == ctx["token"]), None)
        return page("my_settings.html", ctx, member=member, mine=mine,
                    notify=notices.summary(notices.prefs(conn, me)) if member else None,
                    pinned=bool(lib and lib.get("pinned")), hidden=bool(lib and lib.get("hidden")),
                    notices_waiting=len(impacts.pending(conn, mine["id"], me)) if mine else 0,
                    notices_total=len(impacts.history(conn, mine["id"])) if mine else 0,
                    access_help=C.ACCESS_HELP.get(g.league_role, ""))

    @app.route("/career/<token>/changes", methods=["GET", "POST"])
    @career_page()
    def impact_page(conn, ctx):
        """What changed for your driver, why and by how much; you agree before carrying on."""
        mine = ctx.get("real", ctx).get("my_driver")
        waiting = impacts.pending(conn, mine["id"], g.user["username"]) if mine else []
        if request.method == "POST":
            if not mine or not request.form.get("agree"):
                raise ValidationError("Tick the box to say you've read and agree to these changes")
            ids = [n["id"] for n in waiting]
            impacts.acknowledge(conn, mine["id"], g.user["username"], ids)
            g.audit_summary = f"agreed to {len(ids)} change notice{'s' if len(ids) != 1 else ''} for {mine['name']}"
            flash("Thanks. You're all caught up.", "success")
            return redirect(url_for("dashboard", token=ctx["token"]))
        return page("changes.html", ctx, waiting=waiting, stats=impacts.STATS,
                    history=impacts.history(conn, None if ctx.get("real", ctx)["is_master"] else (mine["id"] if mine else -1)),
                    dmap=S.driver_map(conn))

    @app.route("/career/<token>/press")
    @career_page()
    def press_page(conn, ctx):
        if not ctx["my_driver"]:
            return redirect(url_for("dashboard", token=ctx["token"]))
        return page("press.html", ctx, press_pens=teamlife.press_pens(conn, ctx["current_season_id"], ctx["my_driver"]["id"]),
                    history=teamlife.press_history(conn, ctx["my_driver"]["id"]))

    @app.route("/career/<token>/press/<int:event_id>", methods=["POST"])
    @career_page()
    def press_answer(conn, ctx, event_id):
        if not ctx["my_driver"]:
            abort(403)
        effect = teamlife.answer(conn, event_id, ctx["my_driver"]["id"], request.form.get("question"),
                                 request.form.get("answer"))
        ev = S.get_event(conn, event_id)
        g.audit_summary = f"answered the Round {ev['round_number']} post-race press questions"
        flash("Answer given. " + ("The team liked that." if effect > 0 else "The team won't love that."
                                  if effect < 0 else "Nobody reads much into it."), "success")
        if request.form.get("back") == "press":
            return redirect(url_for("press_page", token=ctx["token"]))
        return redirect(url_for("dashboard", token=ctx["token"]) + "#press")

    @app.route("/career/<token>/target/<int:event_id>/accept", methods=["POST"])
    @career_page()
    def target_ack(conn, ctx, event_id):
        if not ctx["my_driver"]:
            abort(403)
        t = teamlife.acknowledge(conn, event_id, ctx["my_driver"]["id"])
        ev = S.get_event(conn, event_id)
        g.audit_summary = f"accepted their Round {ev['round_number']} weekend target ({t['label']})"
        flash("Target accepted. Good luck out there.", "success")
        return _back(ctx, "#target")

    @app.route("/career/<token>/weekend/<int:event_id>/open-early", methods=["POST"])
    @career_page(master_only=True)
    def gate_bypass(conn, ctx, event_id):
        waiting = gates.bypass(conn, event_id, g.user["username"], request.form.get("note"))
        ev = S.get_event(conn, event_id)
        note = request.form.get("note", "").strip()
        g.audit_summary = (f"opened {event_label(ev, S.get_season(conn, ev['season_id'])['year'])} before everyone was "
                           f"ready (waiting on {waiting}). Note: {note[:200]}")
        g.audit_link = f"weekend/{event_id}"
        flash("Round opened. Results can go in now; the outstanding items stay open for the players to do later.",
              "success")
        return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))

    @app.route("/career/<token>/weekend/<int:event_id>/remind", methods=["POST"])
    @career_page(ops_only=True)
    def gate_remind(conn, ctx, event_id):
        names = gates.remind(conn, event_id)
        ev = S.get_event(conn, event_id)
        g.audit_summary = f"reminded {', '.join(names)} that Round {ev['round_number']} is waiting on them"
        flash(f"Reminder sent to {', '.join(names)}.", "success")
        return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))

    @app.route("/career/<token>/weekend/<int:event_id>/target/<int:driver_id>/excuse", methods=["POST"])
    @career_page(master_only=True)
    def target_excuse(conn, ctx, event_id, driver_id):
        excused = request.form.get("excused") == "1"
        t = teamlife.excuse(conn, event_id, driver_id, excused)
        ev = S.get_event(conn, event_id)
        name = S.driver_map(conn)[driver_id]["name"]
        g.audit_summary = (f"marked {name}'s Round {ev['round_number']} {'DNF as not their fault' if excused else 'DNF as counting'}"
                           f" (target now {t['status'].lower()})")
        flash(f"{name}'s target is now {t['status'].lower()}.", "success")
        return redirect(url_for("weekend", token=ctx["token"], event_id=event_id) + "#targets")

    @app.route("/career/<token>/weekend/<int:event_id>/incident", methods=["POST"])
    @career_page()
    def incident_report(conn, ctx, event_id):
        if not (ctx["my_driver"] or ctx["is_master"]):
            abort(403)
        mine = ctx["my_driver"]["id"] if ctx["my_driver"] else None
        iid = community.report_incident(conn, event_id, g.user["username"], mine, _form_int("accused_id"),
                                        request.form.get("description"))
        who = next(i for i in community.incidents(conn, event_id=event_id) if i["id"] == iid)
        feed.notify(conn, who["accused_driver_id"], f"You've been reported for an incident at R{who['round_number']} "
                    f"{who['event_name']}. The Race Master will rule on it.", "incidents")
        flash("Incident reported. The Race Master will review it.", "success")
        return redirect(url_for("weekend", token=ctx["token"], event_id=event_id) + "#incidents")

    @app.route("/career/<token>/incidents")
    @career_page()
    def incidents_page(conn, ctx):
        return page("incidents.html", ctx, rows=community.incidents(conn, season_id=ctx["season"]["id"]))

    @app.route("/career/<token>/incidents/<int:incident_id>/rule", methods=["POST"])
    @career_page(master_only=True)
    def incident_rule(conn, ctx, incident_id):
        community.rule_incident(conn, incident_id, request.form.get("ruling"), request.form.get("note"),
                                g.user["username"])
        flash("Ruling published.", "success")
        return redirect(request.referrer or url_for("incidents_page", token=ctx["token"]))

    @app.route("/career/<token>/incidents/<int:incident_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def incident_delete(conn, ctx, incident_id):
        conn.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
        flash("Report deleted.", "success")
        return redirect(request.referrer or url_for("incidents_page", token=ctx["token"]))

    @app.route("/career/<token>/autobackup/<name>/restore", methods=["POST"])
    @master_required
    def auto_backup_restore(token, name):
        try:
            path = storage.auto_backup_path(token, name)
            storage.restore(token, path)
        except CareerNotFound:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard", token=token))
        flash("League restored from the backup. The state just before restoring was saved as a new backup, "
              "so you can undo this.", "success")
        return redirect(url_for("dashboard", token=token))

    @app.route("/career/<token>/restore", methods=["POST"])
    @master_required
    def restore_upload(token):
        upload = request.files.get("file")
        if not upload or not upload.filename.lower().endswith(".f1career"):
            flash("Choose a .f1career backup file.", "error")
            return redirect(url_for("dashboard", token=token))
        fd, tmp = tempfile.mkstemp(suffix=".f1career")
        os.close(fd)
        try:
            upload.save(tmp)
            storage.restore(token, tmp)
        except CareerNotFound:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard", token=token))
        finally:
            os.unlink(tmp)
        flash("League restored from your file. The state just before was saved as a backup.", "success")
        return redirect(url_for("dashboard", token=token))

    @app.route("/career/<token>/pledge")
    @career_page()
    def pledge_page(conn, ctx):
        mine = ctx["my_driver"]
        sid = ctx["current_season_id"]
        relations.ensure(conn, sid)
        rel = relations.assess(conn, sid, mine["id"]) if mine else None
        if not rel:
            return redirect(url_for("dashboard", token=ctx["token"]))
        ranks = S.team_strength_ranks(conn, sid)
        options = [relations.targets_for(conn, sid, mine["id"], rel["team_id"], i, ranks)
                   for i in range(len(C.GROWTH_LEVELS))]
        return page("pledge.html", ctx, rel=rel, options=options, required=relations.needs_pledge(conn, sid, mine["id"]))

    @app.route("/career/<token>/pledge", methods=["POST"])
    @career_page()
    def pledge_save(conn, ctx):
        if not ctx["my_driver"]:
            abort(403)
        if not relations.needs_pledge(conn, ctx["current_season_id"], ctx["my_driver"]["id"]):
            raise ValidationError("Your pledge is locked in for this season. The Race Master can ask you for a new one.")
        t = relations.set_pledge(conn, ctx["current_season_id"], ctx["my_driver"]["id"], request.form.get("growth"))
        g.audit_summary = f"selected the {relations.growth_level(request.form.get('growth'))['name']} growth pledge"
        g.audit_link = "team-standing"
        flash(f"Pledge locked in: average P{t['finish_target']:.1f} or better this season "
              f"(the car's expected finish is P{t['finish_base']:.1f}).", "success")
        return redirect(url_for("team_standing", token=ctx["token"]))

    @app.route("/career/<token>/team-standing/<int:driver_id>/request-pledge", methods=["POST"])
    @career_page(master_only=True)
    def request_pledge(conn, ctx, driver_id):
        if request.form.get("all"):
            relations.ensure(conn, ctx["current_season_id"])
            ids = [r["driver_id"] for r in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?",
                                                        (ctx["current_season_id"],))]
            for did in ids:
                relations.request_pledge(conn, ctx["current_season_id"], did)
            flash(f"Asked {len(ids)} driver(s) for a new pledge. They'll choose it next time they open the league.", "success")
        else:
            relations.request_pledge(conn, ctx["current_season_id"], driver_id)
            flash("Asked for a new pledge. The driver will choose it next time they open the league.", "success")
        return redirect(url_for("team_standing", token=ctx["token"], driver=driver_id))

    @app.route("/career/<token>/team-standing")
    @career_page()
    def team_standing(conn, ctx):
        players = S.player_drivers(conn)
        wanted = request.args.get("driver", type=int)
        if ctx["is_master"]:
            driver = next((p for p in players if p["id"] == wanted), None) or ctx["my_driver"] or \
                (players[0] if players else None)
        else:
            driver = ctx["my_driver"]
        if not driver:
            return page("team_standing.html", ctx, driver=None, players=players, rel=None)
        sid = ctx["season"]["id"]
        relations.ensure(conn, sid)
        rel = relations.assess(conn, sid, driver["id"])
        me, interest = market.team_interest(conn, sid, driver["id"])
        teammate = None
        if rel:
            seat = S.driver_seats(conn, sid).get(driver["id"])
            if seat:
                teammate = S.driver_map(conn).get(S.grid_map(conn, sid).get((seat[0], 2 if seat[1] == 1 else 1)))
        return page("team_standing.html", ctx, driver=driver, players=players, rel=rel, interest=interest, me=me,
                    orders=teamlife.orders_for(conn, sid, driver["id"]),
                    targets=teamlife.targets_history(conn, sid, driver["id"]),
                    needs_pledge=relations.needs_pledge(conn, sid, driver["id"]),
                    notes=relations.notes(conn, sid, driver["id"]), teammate=teammate,
                    contract=market.current_contract(conn, driver["id"]),
                    next_event=S.next_incomplete_event(conn, ctx["current_season_id"]),
                    ultimatum=ultimatums.active(conn, sid, driver["id"]),
                    own=bool(ctx["my_driver"] and ctx["my_driver"]["id"] == driver["id"]))

    @app.route("/career/<token>/team-standing/<int:driver_id>/goals", methods=["POST"])
    @career_page(master_only=True)
    def goals_reissue(conn, ctx, driver_id):
        """Race Master: set season goals (one driver or everyone) or the next weekend target again."""
        sid = ctx["current_season_id"]
        action = request.form.get("action")
        dmap = S.driver_map(conn)
        if action == "retarget":
            nxt = S.next_incomplete_event(conn, sid)
            if not nxt:
                raise ValidationError("There's no upcoming round")
            old, t = teamlife.reissue_target(conn, nxt["id"], driver_id)
            g.audit_summary = (f"re-issued {dmap[driver_id]['name']}'s R{nxt['round_number']} weekend target: {t['label']}"
                               + (f" (was: {old['label']})" if old else ""))
            flash(f"New R{nxt['round_number']} target: {t['label']}.", "success")
        elif action in ("reissue", "reissue_all"):
            relations.ensure(conn, sid)
            rows = conn.execute("SELECT * FROM team_relations WHERE season_id = ?" +
                                ("" if action == "reissue_all" else " AND driver_id = ?"),
                                (sid,) if action == "reissue_all" else (sid, driver_id)).fetchall()
            if not rows:
                raise ValidationError("That driver doesn't have a team this season")

            def redo(c):
                touched = {}
                for r in rows:
                    relations.set_goals(c, sid, r["driver_id"], r["team_id"], relations._role(c, r), replace=True)
                    touched[r["driver_id"]] = ["Season goals set again by the Race Master: " +
                                               "; ".join(x["label"] for x in c.execute(
                                                   "SELECT label FROM team_goals WHERE season_id = ? AND driver_id = ? "
                                                   "ORDER BY id", (sid, r["driver_id"])))]
                    feed.notify(c, r["driver_id"], "The Race Master re-issued your season goals. See Relationships.",
                                "team-standing", category="career")
                return touched
            impacts.record_change(conn, f"goals-reissued-{storage.now_iso()}", "Season goals re-issued",
                                  "The Race Master set your team's season goals again from the latest car strength "
                                  "and your role. Goals on track add to your team relationship; goals behind take away.",
                                  redo)
            who = "every player driver" if action == "reissue_all" else dmap[driver_id]["name"]
            g.audit_summary = f"re-issued season goals for {who}"
            flash(f"Season goals re-issued for {who}.", "success")
        else:
            raise ValidationError("Choose what to re-issue")
        return redirect(url_for("team_standing", token=ctx["token"], driver=driver_id))

    @app.route("/career/<token>/announcements", methods=["GET", "POST"])
    @career_page()
    def announcements_page(conn, ctx):
        real = ctx.get("real", ctx)
        if request.method == "POST":
            if not real["is_master"]:
                abort(403)
            tz = ctx["timezone"]
            try:
                publish_at = timefmt.from_input(request.form.get("publish_at"), tz)
                expires_at = timefmt.from_input(request.form.get("expires_at"), tz)
            except ValueError:
                raise ValidationError("Check the dates")
            audience = announcements.clean_audience(request.form.getlist("audience"))
            ann_id = announcements.create(conn, g.user["username"], request.form.get("title"), request.form.get("body"),
                                          audience, bool(request.form.get("pinned")), bool(request.form.get("email")),
                                          publish_at, expires_at)
            a = announcements.get(conn, ann_id)
            g.audit_summary = (f"{'scheduled' if not a['published_at'] else 'posted'} an announcement: {a['title']}"
                               + ("" if audience == "all" else f" (for {audience.replace(',', ', ').replace('_', ' ')})"))
            flash("Announcement scheduled." if not a["published_at"] else "Announcement posted.", "success")
            return redirect(url_for("announcements_page", token=ctx["token"]))
        mine = ctx.get("my_driver")
        return page("announcements.html", ctx, audiences=announcements.AUDIENCES,
                    items=announcements.all_for_admin(conn) if real["is_master"] else
                    announcements.visible(conn, g.user["username"], real.get("role"), mine["id"] if mine else None),
                    preview=announcements.preview(conn, "all", exclude=g.user["username"]) if real["is_master"] else None,
                    email_ready=mailer.configured())

    @app.route("/career/<token>/announcements/preview")
    @career_page(master_only=True)
    def announcements_preview(conn, ctx):
        audience = announcements.clean_audience(request.args.getlist("audience"))
        return jsonify(announcements.preview(conn, audience, exclude=g.user["username"]))

    @app.route("/career/<token>/announcements/<int:ann_id>/<action>", methods=["POST"])
    @career_page(master_only=True)
    def announcement_action(conn, ctx, ann_id, action):
        a = announcements.get(conn, ann_id)
        if not a or action not in ("pin", "unpin", "end"):
            abort(404)
        if action == "end":
            announcements.end(conn, ann_id)
        else:
            announcements.set_pinned(conn, ann_id, action == "pin")
        g.audit_summary = {"pin": "pinned", "unpin": "unpinned", "end": "took down"}[action] + f" the announcement {a['title']}"
        return redirect(url_for("announcements_page", token=ctx["token"]))

    def _my_goal_teams(conn, ctx, sid):
        """Teams this person may choose a goal for: their driver's team, or every player team for a Race Master."""
        lineup = teamgoals.player_teams(conn, sid)
        real = ctx.get("real", ctx)
        if real["is_master"]:
            return set(lineup)
        mine = real.get("my_driver")
        return {t for t, ds in lineup.items() if mine and any(d["id"] == mine["id"] for d in ds)}

    @app.route("/career/<token>/dismissals/<int:ultimatum_id>", methods=["POST"])
    @career_page(master_only=True)
    def dismissal_decide(conn, ctx, ultimatum_id):
        """Race Master: confirm a team's mid-season dismissal, or overrule it with a note."""
        dismiss = request.form.get("decision") == "dismiss"
        row = conn.execute("SELECT driver_id FROM ultimatums WHERE id = ?", (ultimatum_id,)).fetchone() \
            if conn.execute("SELECT name FROM sqlite_master WHERE name = 'ultimatums'").fetchone() else None
        if not row:
            abort(404)
        name = S.driver_map(conn)[row["driver_id"]]["name"]
        if dismiss:
            result = {}

            def act(c):
                result["r"] = ultimatums.decide(c, ultimatum_id, True, g.user["username"], request.form.get("note"))
                return {row["driver_id"]: ["You lost your race seat mid-season. Your results and points stay yours."]}
            impacts.record_change(conn, f"dismissed-{ultimatum_id}", "Dropped by your team",
                                  "Your team set a final target and it was missed, and the Race Master confirmed the "
                                  "decision. You're free to talk to other teams.", act)
            g.audit_summary = f"confirmed {name}'s mid-season dismissal"
            flash(f"{name} has been dropped. The best available reserve takes the seat.", "success")
        else:
            ultimatums.decide(conn, ultimatum_id, False, g.user["username"], request.form.get("note"))
            g.audit_summary = f"overruled {name}'s mid-season dismissal: {request.form.get('note', '').strip()[:120]}"
            flash(f"{name} keeps the seat.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]) + "#dismissals")

    @app.route("/career/<token>/team-goals")
    @career_page()
    def team_goals_page(conn, ctx):
        sid = ctx["season"]["id"]
        lineup = teamgoals.player_teams(conn, sid)
        tmap = S.team_map(conn)
        can = _my_goal_teams(conn, ctx, sid) if sid == ctx["current_season_id"] else set()
        locked = teamgoals.locked(conn, sid)
        chosen = {g["team_id"]: g for g in teamgoals.progress(conn, sid)}
        teams = []
        for team_id, drivers in sorted(lineup.items(), key=lambda kv: tmap[kv[0]]["name"]):
            open_ = not teamgoals.locked(conn, sid, team_id)
            teams.append({"team": tmap[team_id], "drivers": drivers, "goal": chosen.get(team_id), "reopened": open_ and locked,
                          "info": teamgoals.options(conn, sid, team_id) if open_ else None,
                          "can_choose": team_id in can and open_ and teamgoals.enabled(conn)})
        return page("team_goals.html", ctx, teams=teams, locked=locked, enabled=teamgoals.enabled(conn),
                    tiers=teamgoals.TIERS)

    @app.route("/career/<token>/team-goals/<int:team_id>", methods=["POST"])
    @career_page()
    def team_goal_choose(conn, ctx, team_id):
        sid = ctx["current_season_id"]
        if team_id not in _my_goal_teams(conn, ctx, sid):
            abort(403)
        action = request.form.get("action")
        team_name = S.team_map(conn)[team_id]["name"]
        if action in ("clear", "reopen", "repush"):
            if not ctx.get("real", ctx)["is_master"]:
                abort(403)
            drivers = teamgoals.player_teams(conn, sid).get(team_id, [])
            if action == "repush":
                old, o = teamgoals.repush(conn, sid, team_id)
                g.audit_summary = f"re-pushed {team_name}'s {o['label']} goal: now {o['text']}"
                msg = f"{team_name}'s {o['label']} goal was updated from the latest numbers: {o['text']}."
                flash(f"Targets re-pushed: {o['text']}.", "success")
            else:
                teamgoals.reopen(conn, sid, team_id)
                g.audit_summary = f"reset {team_name}'s team goal and reopened the choice"
                msg = f"The Race Master reset {team_name}'s team goal. Choose a new one on the Team goals page."
                flash(f"{team_name}'s goal was reset. They can choose again.", "success")
            for d in drivers:
                feed.notify(conn, d["id"], msg, "team-goals", category="career")
        else:
            o = teamgoals.choose(conn, sid, team_id, request.form.get("tier"), g.user["username"])
            g.audit_summary = f"chose a {o['label']} goal for {S.team_map(conn)[team_id]['name']}: {o['text']}"
            flash(f"{o['label']} goal set: {o['text']}.", "success")
        return redirect(url_for("team_goals_page", token=ctx["token"]))

    @app.route("/career/<token>/market")
    @career_page()
    def market_page(conn, ctx):
        if not ctx["is_master"]:
            return redirect(url_for("offers_page", token=ctx["token"]))
        offers = market.offers(conn)
        return page("market.html", ctx, windows=market.windows(conn), offers=offers,
                    target=market.target_year(conn, ctx["current_season_id"]))

    @app.route("/career/<token>/market/open", methods=["POST"])
    @career_page(master_only=True)
    def market_open(conn, ctx):
        market.open_window(conn, ctx["current_season_id"])
        flash("Market window opened. Each player can now review their offers in My Garage.", "success")
        return redirect(url_for("market_page", token=ctx["token"]))

    @app.route("/career/<token>/market/<int:window_id>/close", methods=["POST"])
    @career_page(master_only=True)
    def market_close(conn, ctx, window_id):
        market.close_window(conn, window_id)
        flash("Market window closed. Unanswered offers expired.", "success")
        return redirect(url_for("market_page", token=ctx["token"]))

    def _offer_for_user(conn, ctx, offer_id):
        offer = market.get_offer(conn, offer_id)
        if not offer:
            abort(404)
        mine = ctx["my_driver"] and ctx["my_driver"]["id"] == offer["driver_id"]
        if not (mine or ctx["is_master"]):
            abort(403)
        return offer

    @app.route("/career/<token>/market/<int:window_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def market_delete(conn, ctx, window_id):
        applied = market.delete_window(conn, window_id)
        flash("Transfer window deleted, with its offers, talks, news and notifications."
              + (f" {applied} signing(s) had already moved a driver; fix seats in Grid & contracts if needed."
                 if applied else ""), "success")
        return redirect(url_for("market_page", token=ctx["token"]))

    @app.route("/career/<token>/news/<int:news_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def news_delete(conn, ctx, news_id):
        feed.delete_news(conn, news_id)
        flash("Headline deleted.", "success")
        return redirect(request.referrer or url_for("news_page", token=ctx["token"]))

    @app.route("/career/<token>/notifications/<int:notification_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def notification_delete(conn, ctx, notification_id):
        feed.delete_notification(conn, notification_id)
        flash("Notification deleted.", "success")
        return redirect(request.referrer or url_for("dashboard", token=ctx["token"]))

    @app.route("/career/<token>/offers/<int:offer_id>/accept", methods=["POST"])
    @career_page()
    def offer_accept(conn, ctx, offer_id):
        offer = _offer_for_user(conn, ctx, offer_id)
        market.accept_offer(conn, offer_id)
        team = S.team_map(conn)[offer["team_id"]]
        flash(f"Signed with {team['name']} for {offer['target_year']}!", "success")
        return redirect(url_for("offers_page", token=ctx["token"], driver=offer["driver_id"]))

    @app.route("/career/<token>/offers/<int:offer_id>/decline", methods=["POST"])
    @career_page()
    def offer_decline(conn, ctx, offer_id):
        offer = _offer_for_user(conn, ctx, offer_id)
        market.decline_offer(conn, offer_id)
        flash("Offer declined.", "success")
        return redirect(url_for("offers_page", token=ctx["token"], driver=offer["driver_id"]))

    @app.route("/career/<token>/offers/<int:offer_id>/counter", methods=["POST"])
    @career_page()
    def offer_counter(conn, ctx, offer_id):
        offer = _offer_for_user(conn, ctx, offer_id)
        result = market.counter_offer(conn, offer_id, request.form.get("role"), request.form.get("years"),
                                      request.form.get("growth"), request.form.get("message", ""))
        team = S.team_map(conn)[offer["team_id"]]["name"]
        flash({"agreed": f"{team} agreed to your terms. Sign the contract to make it official.",
               "countered": f"{team} came back with a counter-offer.",
               "final": f"{team} have made their final offer.",
               "collapsed": f"{team} walked away from the table."}[result],
              "error" if result == "collapsed" else "success")
        return redirect(url_for("offers_page", token=ctx["token"], driver=offer["driver_id"]) + f"#offer-{offer_id}")

    @app.route("/career/<token>/market/approach", methods=["POST"])
    @career_page()
    def market_approach(conn, ctx):
        driver_id = _form_int("driver_id")
        mine = ctx["my_driver"] and ctx["my_driver"]["id"] == driver_id
        if not (mine or ctx["is_master"]) or driver_id not in {p["id"] for p in S.player_drivers(conn)}:
            abort(403)
        window_id, team_id = _form_int("window_id"), _form_int("team_id")
        terms = request.form.get("terms") == "custom"
        offer_id, result = market.approach_team(
            conn, window_id, driver_id, team_id,
            request.form.get("role") if terms else None, request.form.get("years") if terms else None,
            request.form.get("growth") if terms else None, request.form.get("message", ""))
        team = S.team_map(conn)[team_id]["name"]
        flash({"rejected": f"{team} turned you down.",
               "trial": f"{team} offered a one-year trial.",
               "offer": f"{team} want to talk. Their opening terms are below.",
               "agreed": f"{team} agreed to your terms! Sign to make it official.",
               "countered": f"{team} came back with a counter-offer.",
               "final": f"{team} made a take-it-or-leave-it offer.",
               "collapsed": f"{team} weren't impressed by your demands and ended talks."}[result],
              "error" if result in ("rejected", "collapsed") else "success")
        return redirect(url_for("offers_page", token=ctx["token"], driver=driver_id) + f"#offer-{offer_id}")

    @app.route("/career/<token>/offers/interview/<int:team_id>", methods=["GET", "POST"])
    @career_page()
    def team_interview(conn, ctx, team_id):
        """Sit down with a team: four questions, a goal you set with them, then they decide whether to talk.
        Uses one of the window's approaches, like any approach."""
        from . import pitch
        mine = ctx["my_driver"]
        if not mine:
            abort(403)
        window = conn.execute("SELECT * FROM market_windows WHERE status = ? ORDER BY target_year DESC, id DESC",
                              (C.WINDOW_OPEN,)).fetchone()
        if not window:
            raise ValidationError("The transfer market is closed")
        if team_id not in {t["id"] for t in market.approachable_teams(conn, window["id"], mine["id"])}:
            raise ValidationError("You can't talk to that team right now (already in talks, or no seat for you)")
        if market.approaches_left(conn, window["id"], mine["id"]) <= 0:
            raise ValidationError("You've used all your approaches for this window")
        team = S.team_map(conn)[team_id]
        questions = pitch.interview_questions(conn, window["id"], mine["id"], team_id)
        if request.method == "POST":
            answers = {}
            for q in questions:
                a = request.form.get(f"q{q['id']}", type=int)
                if a is None:
                    raise ValidationError("Answer every question")
                answers[q["id"]] = a
            goal = request.form.get("goal")
            if goal not in pitch.GOALS:
                raise ValidationError("Choose the goal you'd set with them")
            ranks = S.team_strength_ranks(conn, window["season_id"])
            try:
                bonus, score, lines = pitch.interview_score(conn, window["id"], mine["id"], team_id,
                                                            ranks.get(team_id, len(ranks)), len(ranks), answers, goal)
            except ValueError as exc:
                raise ValidationError(str(exc))
            verdict = ("The interview went very well." if score >= 0.5 else "The interview went fine." if score >= 0.15
                       else "The interview didn't land." if score <= -0.15 else "The interview was so-so.")
            summary = " ".join([verdict] + lines[:3])
            offer_id, result = market.approach_team(
                conn, window["id"], mine["id"], team_id, message=f"Interview. My goal with you: {pitch.GOALS[goal]}.",
                interview={"bonus": bonus, "summary": summary})
            g.audit_summary = f"interviewed with {team['name']} ({pitch.GOALS[goal].lower()})"
            flash(f"{team['name']}: {verdict}", "success" if result not in ("rejected", "collapsed") else "error")
            return redirect(url_for("offers_page", token=ctx["token"]) + f"#offer-{offer_id}")
        return page("interview.html", ctx, team=team, questions=questions, goals=pitch.GOALS, window=window,
                    record=pitch.last_season(conn, mine["id"]),
                    approaches=market.approaches_left(conn, window["id"], mine["id"]))

    @app.route("/career/<token>/news")
    @career_page()
    def news_page(conn, ctx):
        news = feed.latest(conn, 100)
        social = _social(conn, ctx, [f"news:{n['id']}" for n in news])
        threads = {t: community.comments(conn, t) for t in social["comment_counts"]}
        return page("news.html", ctx, news=news, threads=threads, **social)

    @app.route("/career/<token>/rivalry")
    @career_page()
    def rivalry_page(conn, ctx):
        sid = ctx["season"]["id"]
        dmap = S.driver_map(conn)
        standings = S.driver_standings(conn, sid)
        options = [r["driver"] for r in standings] + [d for d in S.drivers(conn) if d["id"] not in {r["driver_id"] for r in standings}]
        a = dmap.get(request.args.get("a", type=int))
        b = dmap.get(request.args.get("b", type=int))
        if not a:
            a = ctx["my_driver"] or next((r["driver"] for r in standings if r["driver"]["is_player"]), None) \
                or (standings[0]["driver"] if standings else None)
        if not b and a:
            # default rival: the nearest other player in the table, else the nearest driver
            order = [r["driver"] for r in standings]
            mine = next((i for i, d in enumerate(order) if d["id"] == a["id"]), 0)
            near = sorted((d for d in order if d["id"] != a["id"]), key=lambda d: (not d["is_player"],
                          abs(next(i for i, x in enumerate(order) if x["id"] == d["id"]) - mine)))
            b = near[0] if near else None
        if not a or not b or a["id"] == b["id"]:
            return page("rivalry.html", ctx, a=a, b=None, options=options, r=None, chart=None, season_chart=None)
        data = insights.rivalry(conn, a["id"], b["id"])
        chart = {"labels": data["labels"], "yLabel": "Race head-to-head lead", "zero": True,
                 "series": [{"name": f"{a['name']} ahead ↑ / {b['name']} ahead ↓", "values": data["swing"], "slot": 1}],
                 "markers": len(data["labels"]) < 12}
        progress = insights.points_progression(conn, sid, [a["id"], b["id"]])
        season_chart = {"labels": progress[0], "yLabel": "Points",
                        "series": [{"name": a["name"], "values": progress[1][a["id"]], "player": bool(a["is_player"]),
                                    "slot": 1, "color": a["player_color"]},
                                   {"name": b["name"], "values": progress[1][b["id"]], "player": bool(b["is_player"]),
                                    "slot": 2, "color": b["player_color"]}],
                        "markers": len(progress[0]) < 12}
        return page("rivalry.html", ctx, a=a, b=b, r=data, chart=chart, season_chart=season_chart, options=options,
                    incidents=community.incidents(conn, driver_ids=(a["id"], b["id"])))

    @app.route("/career/<token>/review/<int:season_id>")
    @career_page()
    def season_review(conn, ctx, season_id):
        if not S.get_season(conn, season_id):
            abort(404)
        return page("review.html", ctx, review=insights.season_review(conn, season_id))

    @app.route("/career/<token>/paddock")
    @career_page(master_only=True)
    def paddock_admin(conn, ctx):
        sid = ctx["current_season_id"]
        seats = S.driver_seats(conn, sid)
        tmap = S.team_map(conn)
        all_drivers = S.drivers(conn)
        for d in all_drivers:
            seat = seats.get(d["id"])
            d["team"] = tmap.get(seat[0]) if seat else None
            d["rep_now"] = S.starting_reputation(conn, sid, d["id"])
            d["history"] = S.driver_history(conn, d["id"])
        all_teams = [dict(t) for t in conn.execute("SELECT * FROM teams ORDER BY active DESC, id")]
        move = None
        src, dst = request.args.get("move_from", type=int), request.args.get("move_to", type=int)
        if src and dst:
            try:
                move = S.results_transfer_preview(conn, src, dst, sid)
            except ValidationError as exc:
                flash(str(exc), "error")
        return page("paddock.html", ctx, all_drivers=all_drivers, all_teams=all_teams,
                    ratings=S.car_ratings(conn, sid), season=S.get_season(conn, sid), move=move)

    @app.route("/career/<token>/paddock/move-results", methods=["POST"])
    @career_page(master_only=True)
    def paddock_move_results(conn, ctx):
        src, dst = _form_int("from_id"), _form_int("to_id")
        sid = ctx["current_season_id"]
        preview = S.results_transfer_preview(conn, src, dst, sid)
        if request.form.get("confirm_name", "").strip() != preview["to"]["name"]:
            raise ValidationError(f"Type {preview['to']['name']} exactly to confirm")
        storage.auto_backup(ctx["token"], "before-moving-results", force=True)
        done = S.transfer_results(conn, src, dst, sid, request.form.getlist("event_id"),
                                  swap_seats=bool(request.form.get("swap_seats")))
        g.audit_summary = (f"moved {done['from']['name']}'s results in "
                           + ", ".join(f"R{r}" for r in done["rounds"]) + f" ({done['points']} pts) to {done['to']['name']}"
                           + (" and swapped their seats" if request.form.get("swap_seats") else ""))
        g.audit_link = f"driver/{dst}"
        flash(f"Moved {done['moved']} round(s) and {done['points']} points from {done['from']['name']} to "
              f"{done['to']['name']}. Standings, Form and Reputation are recalculated. A backup was made first "
              "(Backups & data).", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/driver", methods=["POST"])
    @career_page(master_only=True)
    def paddock_driver(conn, ctx):
        sid = ctx["current_season_id"]
        driver_id = _form_int("driver_id")
        if driver_id:
            S.update_driver(conn, driver_id, sid, request.form.get("name"), request.form.get("baseline_reputation"),
                            request.form.get("active"))
            flash("Driver updated.", "success")
        else:
            S.add_driver(conn, request.form.get("name"), C.ROOKIE_REPUTATION, sid)
            feed.post(conn, sid, "paddock", f"New face in the paddock: {request.form.get('name', '').strip()}",
                      "Available to teams from today.", "drivers")
            flash("Driver added. Put them in a seat from Grid & contracts.", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/driver/<int:driver_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def paddock_driver_delete(conn, ctx, driver_id):
        force = bool(request.form.get("force"))
        driver = S.driver_map(conn).get(driver_id)
        if force and driver and "confirm_name" in request.form and \
                request.form.get("confirm_name", "").strip() != driver["name"]:
            raise ValidationError(f"Type {driver['name']} exactly to delete their race results")
        name = S.delete_driver(conn, driver_id, ctx["current_season_id"], force=force)
        flash(f"{name} deleted.", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/team", methods=["POST"])
    @career_page(master_only=True)
    def paddock_team(conn, ctx):
        sid = ctx["current_season_id"]
        team_id = _form_int("team_id")
        if team_id:
            S.update_team(conn, team_id, sid, request.form.get("name"), request.form.get("abbreviation"),
                          request.form.get("color"), request.form.get("active"))
            flash("Team updated.", "success")
        else:
            S.add_team(conn, request.form.get("name"), request.form.get("abbreviation"), request.form.get("color"), sid)
            feed.post(conn, sid, "paddock", f"{request.form.get('name', '').strip()} join the grid",
                      "Two new seats are open.", "teams")
            flash("Team added with two empty seats. Fill them in Grid & contracts.", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/cars", methods=["POST"])
    @career_page(master_only=True)
    def paddock_cars(conn, ctx):
        sid = ctx["current_season_id"]
        for team in S.teams(conn):
            value = request.form.get(f"rating_{team['id']}")
            if value not in (None, ""):
                S.set_car_rating(conn, sid, team["id"], value)
        flash("Car ratings saved.", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/recalculate", methods=["POST"])
    @career_page(master_only=True)
    def paddock_recalculate(conn, ctx):
        storage.auto_backup(ctx["token"], "before-recalculate", force=True)
        changes = S.recalculate_reputation_history(conn)
        dmap = S.driver_map(conn)
        moved = [f"{dmap[d]['name']} {b} → {a}" for d, (b, a) in changes.items()
                 if dmap[d]["is_player"] and b is not None and b != a]
        flash("Reputation history recalculated." + (" " + "; ".join(moved) if moved else ""), "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/calendar/add", methods=["POST"])
    @career_page(master_only=True)
    def calendar_add(conn, ctx):
        S.add_event(conn, ctx["season"]["id"], request.form.get("name"), request.form.get("location"),
                    request.form.get("is_sprint"))
        flash("Round added to the end of the calendar.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    @app.route("/career/<token>/calendar/<int:event_id>/delete", methods=["POST"])
    @career_page(master_only=True)
    def calendar_delete(conn, ctx, event_id):
        event = S.get_event(conn, event_id)
        if not event or event["season_id"] != ctx["season"]["id"]:
            abort(404)
        S.delete_event(conn, event_id)
        flash("Round removed.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    @app.route("/career/<token>/autobackup/<name>")
    @master_required
    def auto_backup_download(token, name):
        try:
            path = storage.auto_backup_path(token, name)
        except CareerNotFound:
            abort(404)
        return send_file(io.BytesIO(storage.redacted_copy(path)), as_attachment=True, download_name=path.name,
                         mimetype="application/octet-stream")

    @app.route("/career/<token>/members", methods=["GET", "POST"])
    @career_page(master_only=True)
    def members(conn, ctx):
        players = S.player_drivers(conn)
        if request.method == "POST":
            # The pre-v1.16 all-in-one form (driver links + Scorekeeper ticks + spectators), mapped onto roles.
            wanted = {}
            for p in players:
                username = auth.normalise(request.form.get(f"user_{p['id']}"))
                if not username:
                    continue
                if not auth.get_user(username):
                    raise ValidationError("Unknown account")
                if username in wanted:
                    raise ValidationError("One login cannot drive two player drivers")
                wanted[username] = ("scorekeeper" if request.form.get(f"keeper_{p['id']}") else "member", p["id"])
            for u in auth.list_users():
                access = request.form.get(f"member_{u['username']}")
                if u["username"] not in wanted and access in ("spectator", "scorekeeper"):
                    wanted[u["username"]] = (access, None)
            current = {m["username"]: m for m in roles.members(conn)}
            for username, (role, did) in wanted.items():
                user = auth.get_user(username)
                if user["is_master"] or (current.get(username) and current[username]["role"] == "race_master"):
                    role = "race_master"
                conn.execute("UPDATE career_members SET driver_id = NULL WHERE driver_id = ? AND username != ?",
                             (did, username)) if did else None
                roles.set_member(conn, username, role, did)
            for username, m in current.items():
                if username not in wanted and m["role"] != "race_master":
                    roles.remove_member(conn, username)
            flash("League members saved.", "success")
            return redirect(url_for("members", token=ctx["token"]))
        requests = [dict(r) for r in conn.execute("SELECT * FROM join_requests WHERE status = 'Pending' ORDER BY id")]
        users = {u["username"]: u for u in auth.list_users()}
        for r in requests:
            r["user"] = users.get(r["username"])
        rows = roles.members(conn)
        assigned = {r["driver_id"] for r in rows if r["driver_id"]}
        in_league = {r["username"] for r in rows}
        return page("members.html", ctx, players=players, rows=rows, requests=requests,
                    free_drivers=[p for p in players if p["id"] not in assigned],
                    outsiders=[u for u in users.values() if u["username"] not in in_league],
                    users=list(users.values()), join_mode=storage.join_mode(conn), join_modes=storage.JOIN_MODES,
                    invitations=[dict(r) for r in conn.execute(
                        "SELECT * FROM invitations WHERE status = 'Pending' ORDER BY created_at")])

    def _driver_from_form():
        raw = request.form.get("driver_id")
        return int(raw) if raw and raw.isdigit() else None

    @app.route("/career/<token>/members/add", methods=["POST"])
    @career_page(master_only=True)
    def member_add(conn, ctx):
        username = auth.normalise(request.form.get("username"))
        if conn.execute("SELECT 1 FROM career_members WHERE username = ?", (username,)).fetchone():
            raise ValidationError("That login is already in this league")
        user = roles.set_member(conn, username, request.form.get("role"), _driver_from_form())
        flash(f"{user['display_name']} added as {C.ACCESS_ROLES[request.form.get('role')]}.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/members/<username>/update", methods=["POST"])
    @career_page(master_only=True)
    def member_update(conn, ctx, username):
        role = request.form.get("role")
        old = conn.execute("SELECT * FROM career_members WHERE username = ?", (auth.normalise(username),)).fetchone()
        user = roles.set_member(conn, username, role, _driver_from_form())
        dmap = S.driver_map(conn)
        changes = []
        if old and old["role"] != role:
            changes.append(f"changed {user['display_name']}'s league role from {C.ACCESS_ROLES.get(old['role'], old['role'])} "
                           f"to {C.ACCESS_ROLES[role]}")
        new_driver = _driver_from_form()
        if old and old["driver_id"] != new_driver:
            name = lambda d: dmap[d]["name"] if d in dmap else "no driver"
            changes.append(f"changed {user['display_name']}'s driver from {name(old['driver_id'])} to {name(new_driver)}")
        g.audit_summary = "; ".join(changes) or f"saved {user['display_name']}'s membership without changes"
        g.audit_link = "members"
        if changes and user["username"] != g.user["username"]:
            feed.notify(conn, None, f"Your role in {ctx['career_name']} is now {C.ACCESS_ROLES[role]}"
                        + (f", driving {dmap[new_driver]['name']}" if new_driver in dmap else ""),
                        "dashboard", category="roles", username=user["username"])
        flash(f"{user['display_name']} is now {C.ACCESS_ROLES[role]}.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/members/<username>/remove", methods=["POST"])
    @career_page(master_only=True)
    def member_remove(conn, ctx, username):
        roles.remove_member(conn, auth.normalise(username))
        flash("Removed from the league. Their login and driver are unchanged.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    def _add_player(conn, ctx, username, driver_name, send_offers, scorekeeper=False):
        user = auth.get_user(username) if username else None
        if username and not user:
            raise ValidationError("Unknown login")
        if user and conn.execute("SELECT 1 FROM career_members WHERE username = ? AND driver_id IS NOT NULL",
                                 (user["username"],)).fetchone():
            raise ValidationError(f"{user['username']} already drives in this league")
        did = S.add_player_driver(conn, driver_name, ctx["current_season_id"])
        if user:
            current = roles.effective_role(conn, user)
            role = "race_master" if current == "race_master" else ("scorekeeper" if scorekeeper or current == "scorekeeper"
                                                                  else "member")
            roles.set_member(conn, user["username"], role, did)
        name = S.driver_map(conn)[did]["name"]
        feed.post(conn, ctx["current_season_id"], "paddock", f"{name} joins the grid as a rookie",
                  "A new player driver has entered the league.", "drivers", driver_id=did)
        if send_offers:
            market.offers_for_player(conn, did)
        return name

    @app.route("/career/<token>/members/player", methods=["POST"])
    @career_page(master_only=True)
    def members_add_player(conn, ctx):
        name = _add_player(conn, ctx, auth.normalise(request.form.get("username")), request.form.get("driver_name"),
                           bool(request.form.get("send_offers")))
        flash(f"{name} added" + (" and teams have sent rookie offers." if request.form.get("send_offers") else
                                 ". Place them in a seat from Grid & contracts or send offers later."), "success")
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/members/request/<int:request_id>/<decision>", methods=["POST"])
    @career_page(master_only=True)
    def members_request(conn, ctx, request_id, decision):
        req = conn.execute("SELECT * FROM join_requests WHERE id = ? AND status = 'Pending'", (request_id,)).fetchone()
        if not req or decision not in ("approve", "decline"):
            abort(404)
        role = request.form.get("role") or req["role"] or "driver"
        if role not in C.LEAGUE_ROLES:
            raise ValidationError("Choose a role")
        if decision == "approve":
            if storage.join_mode(conn) == "closed":
                raise ValidationError("This league is closed to new members. Change the join setting first, or decline.")
            if not auth.get_user(req["username"]):
                raise ValidationError("That login no longer exists")
            keeper = role in ("driver_scorekeeper", "scorekeeper")
            if role in ("driver", "driver_scorekeeper"):
                name = _add_player(conn, ctx, req["username"], request.form.get("driver_name") or req["driver_name"],
                                   bool(request.form.get("send_offers")), scorekeeper=keeper)
                what = f"as {name}" + (" (and Scorekeeper)" if keeper else "")
            else:
                roles.set_member(conn, req["username"], "scorekeeper" if keeper else "spectator", None)
                what = f"as {C.LEAGUE_ROLES[role]}"
            changed = role != (req["role"] or "driver")
            flash(f"{req['username']} joined {what}." + (" (Role changed from their request.)" if changed else ""),
                  "success")
            # The notification choices they made when asking to join apply to this league only.
            notices.save(conn, req["username"], preset=req["notify_preset"] or "important")
            delivery.send_email(conn, ctx["token"], "roles", [req["username"]], f"joined:{req['username']}:{request_id}",
                                f"You're in: {ctx['career_name']}",
                                f"Your request to join {ctx['career_name']} was approved. You joined {what}."
                                + (f" The Race Master changed your role from what you asked for "
                                   f"({C.LEAGUE_ROLES.get(req['role'], 'Driver')})." if changed else "")
                                + f"\n\n{url_for('dashboard', token=ctx['token'], _external=True)}", None,
                                request.host_url.rstrip("/"), "Join request approved")
        else:
            flash(f"Request from {req['username']} declined.", "success")
        conn.execute("UPDATE join_requests SET status = ?, decided_at = ? WHERE id = ?",
                     ("Approved" if decision == "approve" else "Declined", storage.now_iso(), request_id))
        return redirect(url_for("members", token=ctx["token"]))

    INVITE_ROLES = ("member", "scorekeeper", "spectator")

    @app.route("/career/<token>/members/invite", methods=["POST"])
    @career_page(master_only=True)
    def member_invite(conn, ctx):
        if ctx.get("is_demo"):
            raise ValidationError("The demo can't invite real people. Create your own league to invite your group.")
        user = auth.get_user(request.form.get("username"))
        role = request.form.get("role") or "member"
        if not user:
            raise ValidationError("There's no login with that name. They can sign up from the login page first.")
        if role not in INVITE_ROLES:
            raise ValidationError("Choose a role")
        if storage.join_mode(conn) == "closed":
            raise ValidationError("This league is closed to new members. Change the join setting first.")
        if conn.execute("SELECT 1 FROM career_members WHERE username = ?", (user["username"],)).fetchone():
            raise ValidationError(f"{user['display_name']} is already in this league")
        if not ratelimit.allow("invite", g.user["username"], INVITE_LIMIT, 3600):
            raise ValidationError("That's a lot of invitations in one hour. Try again later.")
        conn.execute("""INSERT INTO invitations(username, role, invited_by, status, created_at) VALUES(?,?,?,'Pending',?)
                        ON CONFLICT(username) DO UPDATE SET role = excluded.role, invited_by = excluded.invited_by,
                        status = 'Pending', created_at = excluded.created_at, decided_at = NULL""",
                     (user["username"], role, g.user["username"], storage.now_iso()))
        community.audit(conn, g.user["username"], "Invited", f"{user['username']} as {C.ACCESS_ROLES[role]}",
                        summary=f"invited {user['display_name']} to join as {C.ACCESS_ROLES[role]}", link="members")
        if user["email"] and not user.get("email_paused"):
            # Not a member yet, so no league preferences apply: one invitation email naming the league and role.
            mailer.send_later([user["email"]], f"You're invited to {ctx['career_name']} as {C.ACCESS_ROLES[role]}",
                              f"{g.user['display_name']} invited you to join the league \"{ctx['career_name']}\" as "
                              f"{C.ACCESS_ROLES[role]}. Accept it from your league list, where you'll also choose "
                              f"what this league may notify you about:\n\n{url_for('home', _external=True)}\n\n"
                              f"—\nSent by Paddock Legacy for the league \"{ctx['career_name']}\". You won't get "
                              f"emails from it unless you join and choose to.")
        flash(f"Invitation sent to {user['display_name']}. They'll see it in their league list.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/members/invite/<username>/cancel", methods=["POST"])
    @career_page(master_only=True)
    def member_invite_cancel(conn, ctx, username):
        conn.execute("UPDATE invitations SET status = 'Cancelled', decided_at = ? WHERE username = ? AND status = 'Pending'",
                     (storage.now_iso(), auth.normalise(username)))
        flash("Invitation cancelled.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/invitation", methods=["POST"])
    def invitation_answer(token):
        """Someone invited to a league accepts or declines from their league list."""
        decision = request.form.get("decision")
        try:
            with storage.session(token) as conn:
                me = g.user["username"]
                inv = conn.execute("SELECT * FROM invitations WHERE username = ? AND status = 'Pending'", (me,)).fetchone()
                if not inv or decision not in ("accept", "decline"):
                    raise ValidationError("That invitation is no longer open")
                if decision == "accept":
                    if storage.join_mode(conn) == "closed":
                        raise ValidationError("This league is closed to new members right now, so the invitation can't be accepted")
                    if not conn.execute("SELECT 1 FROM career_members WHERE username = ?", (me,)).fetchone():
                        driver = inv["driver_id"] if "driver_id" in inv.keys() else None
                        if driver and conn.execute("SELECT 1 FROM career_members WHERE driver_id = ?", (driver,)).fetchone():
                            driver = None   # someone else took that driver meanwhile
                        roles.set_member(conn, me, "race_master" if g.user["is_master"] else inv["role"],
                                         None if inv["role"] == "spectator" else driver)
                        notices.save(conn, me, preset=_preset())
                    feed.notify(conn, None, f"{g.user['display_name']} accepted an invitation and joined", "members",
                                category="join_requests")
                conn.execute("UPDATE invitations SET status = ?, decided_at = ? WHERE username = ?",
                             ("Accepted" if decision == "accept" else "Declined", storage.now_iso(), me))
        except CareerNotFound:
            abort(404)
        except ValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("home"))
        if decision == "accept":
            flash("You've joined the league.", "success")
            return redirect(url_for("dashboard", token=token))
        flash("Invitation declined.", "success")
        return redirect(url_for("home"))

    @app.route("/career/<token>/members/settings", methods=["POST"])
    @career_page(master_only=True)
    def members_settings(conn, ctx):
        mode = request.form.get("join_mode")
        if mode is None:  # the pre-v1.18 checkbox form: ticked = requests, unticked = invite only
            mode = "requests" if request.form.get("join_open") else "invite"
        if mode not in storage.JOIN_MODES:
            raise ValidationError("Choose how people can join")
        before = storage.join_mode(conn)
        storage.set_join_mode(conn, mode)
        g.audit_summary = (f"changed joining from {storage.JOIN_MODES[before]} to {storage.JOIN_MODES[mode]}"
                           if before != mode else f"kept joining as {storage.JOIN_MODES[mode]}")
        flash(f"Joining: {storage.JOIN_MODES[mode]}. Existing members aren't affected.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/offers/send/<int:driver_id>", methods=["POST"])
    @career_page(master_only=True)
    def offers_send(conn, ctx, driver_id):
        market.offers_for_player(conn, driver_id)
        flash("Offers sent.", "success")
        return redirect(url_for("members", token=ctx["token"]))

    # ---------------------------------------------------------------- race API
    def _email_results(token, event_id):
        """The results email goes only to members of THIS league whose preferences here want it; the dedupe
        key means a retried or repeated submission never sends it twice."""
        if not mailer.configured():
            return 0
        with storage.session(token) as conn:
            usernames = notices.audience(conn, "results")
            url = url_for("weekend", token=token, event_id=event_id, _external=True)
            subject, text, html = feed.results_email(conn, event_id, url)
            ev = S.get_event(conn, event_id)
            return delivery.send_email(conn, token, "results", usernames, f"results-email:{event_id}", subject, text,
                                       html, request.host_url.rstrip("/"), f"Results: R{ev['round_number']} {ev['name']}")

    def _may_enter_results(token):
        if not g.user:
            return False
        _load_league_role(token)
        return can_run()

    @app.route("/api/career/<token>/weekend/<int:event_id>", methods=["POST"])
    def api_weekend(token, event_id):
        if not _may_enter_results(token):
            return jsonify(ok=False, error="Only the Race Master or a Scorekeeper can enter results"), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(ok=False, error="Invalid request"), 400
        try:
            with storage.session(token) as conn:
                before = S.get_event(conn, event_id)
                if not before:
                    return jsonify(ok=False, error="Event not found"), 404
                if before["status"] == C.EVENT_COMPLETE and not is_master():
                    return jsonify(ok=False, locked=True, error="This weekend has been submitted. Only the Race Master "
                                   "can reopen or change it now."), 403
                gate = gates.status(conn, event_id)
                if gate["blocking"]:
                    why = ("This round can't start yet. Waiting on: " + gates.waiting_text(gate) +
                           (". Open it early from the round page with a note if you need to." if is_master()
                            else ". Only the Race Master can open it early."))
                    return jsonify(ok=False, gated=True, error=why), 423
                base = payload.get("base_revision")
                if base is not None and str(base).lstrip("-").isdigit() and int(base) != before["revision"]:
                    # Someone saved this round after the edits being sent were started (e.g. while offline).
                    return jsonify(ok=False, conflict=True, error="This round changed on the server since your edits.",
                                   server=S.weekend_snapshot(conn, event_id)), 409
                if payload.get("mark_complete") and before["status"] != C.EVENT_COMPLETE:
                    S.save_weekend(conn, event_id, {**payload, "mark_complete": False})
                    check = S.submission_check(conn, event_id)
                    if check["blocking"]:
                        return jsonify(ok=False, blocked=True, error="Fix the blocking problems before submitting.",
                                       checklist=check, revision=check["revision"]), 422
                result = S.save_weekend(conn, event_id, payload)
                newly_complete = result["complete"] and before["status"] != C.EVENT_COMPLETE
                label = event_label(before, S.get_season(conn, before["season_id"])["year"])
                verb = ("submitted the results for" if newly_complete else
                        "saved corrections to" if before["status"] == C.EVENT_COMPLETE else "edited the results for")
                community.audit(conn, g.user["username"],
                                "Submitted results" if newly_complete else "Edited results",
                                f"R{before['round_number']} {before['name']}", summary=f"{verb} {label}",
                                link=f"weekend/{event_id}")
                opened = None
                first_submission = newly_complete and not before["submitted_at"]
                if newly_complete:
                    conn.execute("UPDATE events SET submitted_at = COALESCE(submitted_at, ?) WHERE id = ?",
                                 (storage.now_iso(), event_id))
                if first_submission:  # a reopened round doesn't repeat its headlines, team reactions or emails
                    feed.on_weekend_complete(conn, event_id, f"weekend/{event_id}")
                    teamlife.after_race(conn, event_id)
                    opened = market.maybe_open_silly_season(conn, before["season_id"])
                elif result["complete"]:
                    teamlife.judge_targets(conn, event_id)   # a correction re-judges this round's weekend targets
                result["market_opened"] = bool(opened)
                result["summary_url"] = url_for("race_summary", token=token, event_id=event_id) if result["complete"] else None
        except CareerNotFound:
            return jsonify(ok=False, error="League not found"), 404
        except ValidationError as exc:
            feed.take_outbox()
            discord.take()
            return jsonify(ok=False, error=str(exc)), 400
        if newly_complete:
            try:
                storage.auto_backup(token, f"after-round-{before['round_number']}", force=True)
            except Exception:
                app.logger.exception("automatic backup failed")
        if first_submission:
            try:
                _email_results(token, event_id)
            except Exception:
                app.logger.exception("results email failed")
            try:
                with storage.session(token) as conn:
                    cfg = discord.settings(conn)
                    if cfg["url"] and cfg["results"] and not app.config.get("TESTING"):
                        discord.send_later(cfg["url"], [discord.results_message(
                            conn, event_id, storage.get_meta(conn, "career_name", "League"))])
            except Exception:
                app.logger.exception("Discord results post failed")
        return jsonify(ok=True, **result)

    @app.route("/api/career/<token>/weekend/<int:event_id>/state")
    def api_weekend_state(token, event_id):
        """The saved round, for recovering offline edits: revision, lock state and every value."""
        if not _may_enter_results(token):
            return jsonify(ok=False, error="Only the Race Master or a Scorekeeper can enter results"), 403
        try:
            with storage.session(token) as conn:
                if not S.get_event(conn, event_id):
                    return jsonify(ok=False, error="Event not found"), 404
                snap = S.weekend_snapshot(conn, event_id)
        except CareerNotFound:
            return jsonify(ok=False, error="League not found"), 404
        snap["locked"] = snap["status"] == C.EVENT_COMPLETE and not is_master()
        return jsonify(ok=True, **snap)

    @app.route("/api/career/<token>/weekend/<int:event_id>/checklist")
    def api_weekend_checklist(token, event_id):
        if not _may_enter_results(token):
            return jsonify(ok=False, error="Only the Race Master or a Scorekeeper can enter results"), 403
        try:
            with storage.session(token) as conn:
                if not S.get_event(conn, event_id):
                    return jsonify(ok=False, error="Event not found"), 404
                check = S.submission_check(conn, event_id)
        except CareerNotFound:
            return jsonify(ok=False, error="League not found"), 404
        return jsonify(ok=True, **check)

    @app.route("/api/career/<token>/notifications")
    @career_page()
    def api_notifications(conn, ctx):
        items = [{"id": n["id"], "text": n["text"], "unread": n["unread"], "icon": n["icon"], "category": n["category"],
                  "created_at": timefmt.ago(n["created_at"], g.tz),
                  "when": timefmt.stamp(n["created_at"], g.tz),
                  "link": f"/career/{ctx['token']}/{n['link']}" if n["link"] else None}
                 for n in ctx["notifications"]]
        return jsonify(ok=True, unread=ctx["unread"], items=items)

    @app.route("/career/<token>/notifications/read", methods=["POST"])
    @career_page()
    def notifications_read(conn, ctx):
        feed.mark_read(conn, g.user["username"])
        return jsonify(ok=True)

    @app.route("/career/<token>/notifications/clear", methods=["POST"])
    @career_page()
    def notifications_clear(conn, ctx):
        feed.clear_read(conn, g.user["username"])
        return jsonify(ok=True)


    # ---------------------------------------------------------------- community
    def _social(conn, ctx, targets):
        if not ctx["features"]["comments"]:
            return {"reacts": {}, "comment_counts": {}}
        return {"reacts": community.reactions(conn, targets, g.user["username"]),
                "comment_counts": community.comment_counts(conn, targets)}

    def _hub(conn, ctx, event, full=False):
        """Race-night data for a weekend: countdown, check-ins, picks, and (once run) the story and fan vote."""
        feats = ctx["features"]
        me = g.user["username"]
        hub = {"event": event, "started": community.race_started(event), "complete": event["status"] == C.EVENT_COMPLETE}
        life = ctx["team_life"]
        if ctx["my_driver"] and life["orders"] != "off":
            order = conn.execute("SELECT * FROM team_orders WHERE event_id = ? AND driver_id = ? AND status != 'Cancelled'",
                                 (event["id"], ctx["my_driver"]["id"])).fetchone()
            if order:
                hub["order"] = {**dict(order), "beneficiary": S.driver_map(conn).get(order["beneficiary_id"]),
                                "advisory": life["orders"] == "advisory"}
        if life["targets"] and full:
            hub["targets"] = teamlife.targets_for_event(conn, event["id"])
        if full and hub["complete"]:
            hub["battles"] = battle.player_battles(conn, event)
        if full and ctx["is_master"] and not hub["complete"]:
            people = [u for u in notices.audience(conn, "schedule") if u != g.user["username"]]
            hub["notify_preview"] = {"members": len(people),
                                     "push": len(notices.wanted(conn, people, "schedule", "push")),
                                     "email": len(notices.email_recipients(conn, people, "schedule"))
                                     if mailer.configured() else 0}
        if feats["checkin"] and not hub["complete"]:
            hub["checkins"], hub["checkin_counts"] = community.checkins(conn, event["id"])
            hub["my_checkin"] = next((r["status"] for r in hub["checkins"] if r["username"] == me), None)
        if feats["predictions"]:
            hub["picks_locked"] = community.predictions_locked(event)
            picks, outcome = community.event_predictions(conn, event["id"])
            hub["my_picks"] = next((p for p in picks if p["username"] == me), None)
            hub["picks"] = picks if hub["picks_locked"] else []
            hub["pick_count"] = len(picks)
            hub["outcome"] = outcome
        if full:
            entrants = sorted(S.weekend_rows(conn, event["id"]), key=lambda r: r["driver"]["name"])
            hub["entrants"] = [r["driver"] for r in entrants]
            hub["players"] = [r["driver"] for r in entrants if r["driver"]["is_player"]]
            if hub["complete"]:
                hub["story"] = community.race_story(conn, event["id"])
                if feats["comments"]:
                    hub["fans"] = community.fan_votes(conn, event["id"], me)
            if feats["comments"]:
                target = f"event:{event['id']}"
                hub["target"] = target
                hub["comments"] = community.comments(conn, target)
                hub["reacts"] = community.reactions(conn, [target], me)[target]
        return hub

    @app.route("/career/<token>/mode", methods=["POST"])
    @career_page()
    def view_mode(conn, ctx):
        """Switch how this league is shown on this device. Never changes the account's real role."""
        wanted = request.form.get("mode")
        if wanted not in dict(ctx["modes"]):
            raise ValidationError("That view isn't available for your role")
        session[f"mode_{ctx['token']}"] = wanted
        flash(f"Now showing {ctx['career_name']} as {VIEW_MODES[wanted]}." +
              (" Your real permissions are unchanged." if wanted != ctx["modes"][0][0] else ""), "success")
        nxt = request.form.get("next") or ""
        return redirect(nxt if nxt.startswith(f"/career/{ctx['token']}/") else url_for("dashboard", token=ctx["token"]))

    @app.route("/career/<token>/pin", methods=["POST"])
    @career_page()
    def league_pin(conn, ctx):
        action = request.form.get("action")
        me = g.user["username"]
        if action in ("pin", "unpin"):
            library.pin(me, ctx["token"], action == "pin")
        elif action in ("hide", "unhide"):
            library.hide(me, ctx["token"], action == "hide")
        return _back(ctx)

    @app.route("/career/<token>/leave", methods=["POST"])
    @career_page()
    def league_leave(conn, ctx):
        """Leave this league (the account and every other league are untouched)."""
        me = g.user["username"]
        if not conn.execute("SELECT 1 FROM career_members WHERE username = ?", (me,)).fetchone():
            raise ValidationError("You aren't a member of this league")
        if request.form.get("confirm_name") != ctx["career_name"]:
            raise ValidationError("Type the league's name to confirm you want to leave")
        roles.remove_member(conn, me)   # refuses if you're the last Race Master
        community.audit(conn, me, "Left the league", "", summary="left the league")
        flash(f"You left {ctx['career_name']}. Your driver and results stay in the league.", "success")
        return redirect(url_for("home"))

    @app.route("/career/<token>/members/transfer", methods=["POST"], defaults={"username": None})
    @app.route("/career/<token>/members/<username>/transfer", methods=["POST"])
    @career_page(master_only=True)
    def ownership_transfer(conn, ctx, username):
        """Make another member Race Master and step down to Member yourself, in one confirmed step."""
        target = auth.get_user(username or request.form.get("username") or "")
        me = g.user["username"]
        if not target or not conn.execute("SELECT 1 FROM career_members WHERE username = ?", (target["username"],)).fetchone():
            raise ValidationError("Choose a member of this league")
        if target["username"] == me:
            raise ValidationError("You already run this league")
        if (request.form.get("confirm_name") or "").strip().lower() != target["username"]:
            raise ValidationError(f"Type {target['username']} to confirm the handover")
        row = conn.execute("SELECT driver_id FROM career_members WHERE username = ?", (target["username"],)).fetchone()
        roles.set_member(conn, target["username"], "race_master", row["driver_id"])
        mine = conn.execute("SELECT driver_id FROM career_members WHERE username = ?", (me,)).fetchone()
        if mine and not g.user["is_master"]:
            roles.set_member(conn, me, "member", mine["driver_id"])
        feed.notify(conn, None, f"You're now the Race Master of {ctx['career_name']}", "dashboard", category="roles",
                    username=target["username"])
        g.audit_summary = f"handed {ctx['career_name']} over to {target['display_name']} (now Race Master)" + \
            ("" if g.user["is_master"] else "; stepped down to Member")
        flash(f"{target['display_name']} now runs {ctx['career_name']}.", "success")
        return redirect(url_for("dashboard", token=ctx["token"]))

    @app.route("/career/<token>/order", methods=["POST"])
    @career_page()
    def league_order(conn, ctx):
        library.move(g.user["username"], ctx["token"], request.form.get("dir", type=int) or 1,
                     library.user_leagues(g.user))
        return redirect(url_for("home"))

    @app.route("/career/<token>/notifications", methods=["GET", "POST"])
    @career_page()
    def notify_prefs(conn, ctx):
        """This member's notification choices for THIS league only."""
        me = g.user["username"]
        member = bool(conn.execute("SELECT 1 FROM career_members WHERE username = ?", (me,)).fetchone())
        if request.method == "POST" and not member:
            raise ValidationError("You can open this league as a site admin but aren't a member, so it never notifies "
                                  "you. Add yourself in Members & Roles to choose notifications.")
        if request.method == "POST":
            before = notices.summary(notices.prefs(conn, me))
            if request.form.get("preset") in notices.PRESETS:
                p = notices.save(conn, me, preset=request.form.get("preset"))
            else:
                p = notices.save(conn, me, muted=bool(request.form.get("muted")),
                                 email=set(request.form.getlist("email")), push=set(request.form.getlist("push")))
            g.audit_summary = f"changed their {ctx['career_name']} notifications from {before} to {notices.summary(p)}"
            flash(f"Saved. These settings only apply to {ctx['career_name']}.", "success")
            return redirect(url_for("notify_prefs", token=ctx["token"]))
        role = g.league_role
        cats = {k: v for k, v in notices.CATEGORIES.items() if v[2] == "all" or role == "race_master"}
        return page("notifications.html", ctx, prefs=notices.prefs(conn, me), cats=cats, member=member,
                    presets=notices.PRESETS, email=g.user.get("email"), paused=g.user.get("email_paused"),
                    mail_ready=mailer.configured())

    @app.route("/career/<token>/deliveries")
    @career_page(master_only=True)
    def delivery_log_page(conn, ctx):
        """What this league sent: category, channel, how many people and the outcome. Never content or addresses."""
        return page("deliveries.html", ctx, rows=notices.delivery_log(conn), cats=notices.CATEGORIES)

    @app.route("/unsubscribe/<sig>", methods=["GET", "POST"])
    def unsubscribe(sig):
        """One-click links in league emails. A GET only shows the choice (mail scanners open links); POST acts."""
        username, token = delivery.read_unsubscribe(sig)
        user = auth.get_user(username) if username else None
        if not user:
            return render_template("unsubscribe.html", error=True), 400
        try:
            with storage.session(token) as conn:
                league = notices.league_name(conn)
                done = None
                if request.method == "POST":
                    if request.form.get("scope") == "all":
                        auth.set_email_paused(username, True)
                        done = "all"
                    else:
                        notices.save(conn, username, email=set())
                        done = "league"
                    community.audit(conn, username, "Changed their notifications", "",
                                    summary=("paused every email from every league" if done == "all" else
                                             f"turned off emails from {league} (unsubscribe link)"))
        except CareerNotFound:
            return render_template("unsubscribe.html", error=True), 404
        return render_template("unsubscribe.html", league=league, done=done, sig=sig, user=g.get("user"))

    def _preset():
        """The notification choice made on a create/join/accept form (defaults to Important only)."""
        value = request.form.get("notify_preset")
        return value if value in notices.PRESETS else "important"

    def _need(ctx, feature):
        if not ctx["features"][feature]:
            raise ValidationError("The Race Master has switched that off for this league")

    def _back(ctx, anchor=""):
        return redirect((request.referrer or url_for("dashboard", token=ctx["token"])).split("#")[0] + anchor)

    @app.route("/career/<token>/settings", methods=["GET", "POST"])
    @career_page(master_only=True)
    def league_settings(conn, ctx):
        if request.method == "POST":
            before = {"features": community.features(conn), "join": storage.join_mode(conn),
                      "discord": discord.settings(conn), "window": ctx["race_window"], "tz": ctx["timezone"],
                      "life": teamlife.settings(conn), "name": ctx["career_name"],
                      "vis": league_profile.visibility(conn), "recs": storage.get_meta(conn, "difficulty_recs", "1"),
                      "goals": teamgoals.enabled(conn), "sackings": ultimatums.enabled(conn)}
            community.set_features(conn, {k for k in C.FEATURES if request.form.get(f"feature_{k}")})
            if request.form.get("feature_public") and "visibility" not in request.form:   # older forms
                request_form = request.form.copy()
                request_form["visibility"] = "public"
            else:
                request_form = request.form
            profile_changes = league_profile.save(conn, request_form)
            name = (request.form.get("career_name") or "").strip()[:80]
            if name:
                storage.set_meta(conn, "career_name", name)
            if "team_life" in request.form:
                storage.set_meta(conn, "difficulty_recs", "1" if request.form.get("difficulty_recs") else "0")
                storage.set_meta(conn, "difficulty_sprints", "1" if request.form.get("difficulty_sprints") else "0")
                teamgoals.set_enabled(conn, bool(request.form.get("team_goal_choice")))
                ultimatums.set_enabled(conn, bool(request.form.get("midseason_sackings")))
            if league_profile.is_public(conn):
                community.public_key(conn)
            if request.form.get("team_life") == "1":
                teamlife.save_settings(conn, request.form.get("team_orders"), bool(request.form.get("weekend_targets")),
                                       bool(request.form.get("round_gates")), bool(request.form.get("gate_press")),
                                       bool(request.form.get("gate_targets")))
            if request.form.get("join_mode") in storage.JOIN_MODES:
                storage.set_join_mode(conn, request.form.get("join_mode"))
            if request.form.get("rollover_default") in seats.ACTIONS:
                storage.set_meta(conn, "rollover_default", request.form.get("rollover_default"))
            discord.save_settings(conn, request.form.get("discord_webhook"), request.form.get("discord_results"),
                                  request.form.get("discord_news"))
            window = request.form.get("race_window", type=int)
            if window in timefmt.RACE_WINDOW_CHOICES:
                storage.set_meta(conn, "race_window", str(window))
            zone = (request.form.get("timezone") or "").strip()
            if zone:
                if not timefmt.valid_zone(zone):
                    raise ValidationError("Unknown time zone")
                storage.set_meta(conn, "timezone", zone)
            changes = [c for c in [_settings_changes(conn, before)] if c]
            if name and name != before["name"]:
                changes.append(f"renamed the league from {before['name']} to {name}")
            vis = league_profile.visibility(conn)
            if vis != before["vis"]:
                changes.append(f"changed visibility from {league_profile.VISIBILITY[before['vis']][0]} to "
                               f"{league_profile.VISIBILITY[vis][0]}")
            if ultimatums.enabled(conn) != before["sackings"]:
                changes.append("turned mid-season dismissals " + ("on" if ultimatums.enabled(conn) else "off"))
            if teamgoals.enabled(conn) != before["goals"]:
                changes.append("turned selectable team goals " + ("on" if teamgoals.enabled(conn) else "off"))
            if storage.get_meta(conn, "difficulty_recs", "1") != before["recs"]:
                changes.append("turned AI difficulty recommendations " +
                               ("on" if storage.get_meta(conn, "difficulty_recs", "1") == "1" else "off"))
            other = [f for f in profile_changes if f not in ("visibility", "name")]
            if other:
                changes.append("updated the league's " + ", ".join(sorted(
                    {"league_description": "description", "league_region": "region", "league_platform": "platform",
                     "league_rules": "rules summary", "league_schedule": "schedule", "links": "links",
                     "accent": "accent colour", "public_incidents": "public incidents setting"}.get(f, f) for f in other)))
            g.audit_summary = "; ".join(changes) or "saved League settings without changes"
            flash("League settings saved.", "success")
            return redirect(url_for("league_settings", token=ctx["token"]))
        feats = community.features(conn)
        link = url_for("public_page", token=ctx["token"], key=community.public_key(conn), _external=True) \
            if feats["public"] else None
        prof = league_profile.profile(conn)
        return page("settings.html", ctx, feats=feats, public_link=link, discord=discord.settings(conn),
                    life=teamlife.settings(conn), rollover_actions=seats.ACTIONS, rollover_default=seats.carry_mode(conn),
                    zones=timefmt.COMMON_ZONES, windows=timefmt.RACE_WINDOW_CHOICES,
                    join_mode=storage.join_mode(conn), join_modes=storage.JOIN_MODES, profile=prof,
                    visibility_opts=league_profile.VISIBILITY, permissions=roles.PERMISSIONS,
                    named_level=league_profile.named_level(prof["visibility"], storage.join_mode(conn)),
                    difficulty_recs=storage.get_meta(conn, "difficulty_recs", "1") == "1",
                    difficulty_sprints=storage.get_meta(conn, "difficulty_sprints", "1") == "1",
                    team_goal_choice=teamgoals.enabled(conn), midseason_sackings=ultimatums.enabled(conn),
                    active_season=any(e["status"] != C.EVENT_NOT_RUN for e in S.events(conn, ctx["current_season_id"]))
                    and S.get_season(conn, ctx["current_season_id"])["status"] != C.SEASON_COMPLETE)

    @app.route("/career/<token>/settings/timezone", methods=["POST"])
    @career_page(master_only=True)
    def timezone_detect(conn, ctx):
        """The Race Master's browser reports its time zone the first time, if none is set yet."""
        zone = (request.get_json(silent=True) or {}).get("timezone", "")
        if not ctx["timezone_set"] and timefmt.valid_zone(zone):
            storage.set_meta(conn, "timezone", zone)
            return jsonify(ok=True, timezone=zone)
        return jsonify(ok=False)

    @app.route("/career/<token>/settings/discord-test", methods=["POST"])
    @career_page(master_only=True)
    def discord_test(conn, ctx):
        cfg = discord.settings(conn)
        if not cfg["url"]:
            raise ValidationError("Save a Discord webhook URL first")
        try:
            discord.post(cfg["url"], f"👋 Paddock Legacy is connected to **{ctx['career_name']}**.")
        except Exception as exc:
            raise ValidationError(f"Discord didn't accept the message ({exc}). Check the webhook URL.")
        flash("Test message sent to Discord.", "success")
        return redirect(url_for("league_settings", token=ctx["token"]))

    @app.route("/career/<token>/settings/public-link", methods=["POST"])
    @career_page(master_only=True)
    def public_rotate(conn, ctx):
        community.public_key(conn, rotate=True)
        flash("New public link made. The old one no longer works.", "success")
        return redirect(url_for("league_settings", token=ctx["token"]))

    @app.route("/career/<token>/activity")
    @career_page(master_only=True)
    def activity_log(conn, ctx):
        who = auth.normalise(request.args.get("who")) or None
        rows = community.audit_entries(conn, 400, who)
        import re as _re
        for r in rows:   # entries from before v1.19 said e.g. "event id 2": show names instead where possible
            if not r.get("summary") and r["detail"]:
                pairs = dict((k.replace(" ", "_"), int(v)) for k, v in _re.findall(r"(\w+ id) (\d+)", r["detail"]))
                if pairs:
                    what, link = _describe_targets(conn, pairs)
                    if what:
                        r["summary"] = r["action"][:1].lower() + r["action"][1:] + ": " + what
                        r["link"] = r.get("link") or link
        names = {u["username"]: u["display_name"] for u in auth.list_users()}
        people = sorted({r["username"] for r in community.audit_entries(conn, 2000)})
        return page("activity.html", ctx, rows=rows, names=names, people=people, who=who)

    @app.route("/career/<token>/weekend/<int:event_id>/time", methods=["POST"])
    @career_page(master_only=True)
    def race_time(conn, ctx, event_id):
        if not S.get_event(conn, event_id):
            abort(404)
        try:
            when = timefmt.from_input(request.form.get("race_at"), ctx["timezone"])
        except ValueError:
            raise ValidationError("That race time isn't a valid date and time")
        community.set_race_at(conn, event_id, when)
        conn.execute("UPDATE events SET postponed = ? WHERE id = ?", (int(bool(request.form.get("postponed"))), event_id))
        ev = S.get_event(conn, event_id)
        year = S.get_season(conn, ev["season_id"])["year"]
        g.audit_link = f"weekend/{event_id}"
        g.audit_summary = (f"marked {event_label(ev, year)} as postponed" if request.form.get("postponed") else
                           f"scheduled {event_label(ev, year)} for {timefmt.race_at(when, ctx['timezone'])} "
                           f"{timefmt.zone_label(when, ctx['timezone'])}" if when else
                           f"cleared the race time for {event_label(ev, year)}")
        if request.form.get("postponed"):
            event = S.get_event(conn, event_id)
            feed.notify(conn, None, f"R{event['round_number']} {event['name']} has been postponed", f"weekend/{event_id}",
                        ref=f"racetime:{event_id}", category="schedule")
            flash("Round marked as postponed.", "success")
            return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))
        if when:
            event = S.get_event(conn, event_id)
            feed.notify(conn, None, f"Race night set: R{event['round_number']} {event['name']} · "
                        f"{timefmt.race_at(when, ctx['timezone'])} {timefmt.zone_label(when, ctx['timezone'])}",
                        f"weekend/{event_id}", ref=f"racetime:{event_id}", category="schedule")
        flash("Race time saved." if when else "Race time cleared.", "success")
        return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))

    @app.route("/career/<token>/weekend/<int:event_id>/checkin", methods=["POST"])
    @career_page()
    def checkin(conn, ctx, event_id):
        _need(ctx, "checkin")
        community.set_checkin(conn, event_id, g.user["username"], request.form.get("status"))
        if request.headers.get("X-Requested-With") == "fetch":
            rows, counts = community.checkins(conn, event_id)
            return jsonify(ok=True, counts=counts)
        return _back(ctx, "#race-night")

    @app.route("/career/<token>/comments", methods=["POST"])
    @career_page()
    def comment_add(conn, ctx):
        _need(ctx, "comments")
        target = request.form.get("target", "")
        community.add_comment(conn, target, g.user["username"], request.form.get("body"))
        kind, _, raw = target.partition(":")
        link = f"weekend/{raw}" if kind == "event" else "news"
        if kind == "event":
            ev = S.get_event(conn, int(raw))
            about = f"R{ev['round_number']} {ev['name']}"
        else:
            row = conn.execute("SELECT headline FROM news WHERE id = ?", (int(raw),)).fetchone()
            about = f"“{row['headline'][:60]}”"
        feed.notify(conn, None, f"{g.user['display_name']} commented on {about}", link, ref=f"comment:{target}")
        if kind == "news":
            return redirect(url_for("news_page", token=ctx["token"], open=target) + f"#news-{raw}")
        return _back(ctx, "#comments")

    @app.route("/career/<token>/comments/<int:comment_id>/delete", methods=["POST"])
    @career_page()
    def comment_delete(conn, ctx, comment_id):
        community.delete_comment(conn, comment_id, g.user["username"], is_master())
        return _back(ctx, "#comments")

    @app.route("/career/<token>/react", methods=["POST"])
    @career_page()
    def react(conn, ctx):
        _need(ctx, "comments")
        target = request.form.get("target", "")
        community.toggle_reaction(conn, target, g.user["username"], request.form.get("emoji"))
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=True, reactions=community.reactions(conn, [target], g.user["username"])[target])
        return _back(ctx)

    @app.route("/career/<token>/weekend/<int:event_id>/fan-vote", methods=["POST"])
    @career_page()
    def fan_vote_route(conn, ctx, event_id):
        _need(ctx, "comments")
        community.fan_vote(conn, event_id, g.user["username"], _form_int("driver_id"))
        flash("Vote counted.", "success")
        return _back(ctx, "#race-night")

    @app.route("/career/<token>/weekend/<int:event_id>/predict", methods=["POST"])
    @career_page()
    def prediction_save(conn, ctx, event_id):
        _need(ctx, "predictions")
        community.save_prediction(conn, event_id, g.user["username"],
                                  {k: request.form.get(k) for k in community.PICKS})
        flash("Picks saved. You can change them until the race starts.", "success")
        return _back(ctx, "#race-night")

    @app.route("/career/<token>/predictions")
    @career_page()
    def predictions_page(conn, ctx):
        if not ctx["features"]["predictions"]:
            abort(404)
        sid = ctx["season"]["id"]
        rounds = []
        for ev in S.events(conn, sid):
            if ev["status"] == C.EVENT_COMPLETE:
                picks, outcome = community.event_predictions(conn, ev["id"])
                if picks:
                    rounds.append({"event": ev, "picks": picks, "outcome": outcome})
        return page("predictions.html", ctx, table=community.leaderboard(conn, sid), rounds=list(reversed(rounds)),
                    next_event=S.next_incomplete_event(conn, sid), dmap=S.driver_map(conn))

    # ---------------------------------------------------------------- driver profiles
    def _may_edit_profile(ctx, driver_id):
        return ctx["is_master"] or bool(ctx["my_driver"] and ctx["my_driver"]["id"] == driver_id)

    def _avatar_dir(token):
        path = storage.data_dir() / "avatars" / storage.sanitize_token(token)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @app.route("/career/<token>/driver/<int:driver_id>/profile", methods=["POST"])
    @career_page()
    def profile_save(conn, ctx, driver_id):
        if not _may_edit_profile(ctx, driver_id):
            abort(403)
        community.save_profile(conn, driver_id, request.form.get("number"), request.form.get("nationality"),
                               request.form.get("helmet_color"), request.form.get("bio"))
        flash("Profile saved.", "success")
        return redirect(url_for("driver_profile", token=ctx["token"], driver_id=driver_id))

    @app.route("/career/<token>/driver/<int:driver_id>/avatar", methods=["POST"])
    @career_page()
    def profile_avatar(conn, ctx, driver_id):
        if not _may_edit_profile(ctx, driver_id) or not S.driver_map(conn).get(driver_id):
            abort(403)
        folder = _avatar_dir(ctx["token"])
        old = community.profile(conn, driver_id).get("avatar")
        if request.form.get("remove"):
            filename = None
        else:
            upload = request.files.get("avatar")
            data = upload.read(C.AVATAR_MAX_BYTES + 1) if upload else b""
            if not data:
                raise ValidationError("Choose a picture first")
            if len(data) > C.AVATAR_MAX_BYTES:
                raise ValidationError("Pictures are limited to 2 MB")
            ext = community.image_kind(data)
            if not ext:
                raise ValidationError("Use a PNG, JPG or WebP picture")
            filename = f"{driver_id}-{secrets.token_hex(4)}.{ext}"
            (folder / filename).write_bytes(data)
        community.set_avatar(conn, driver_id, filename)
        if old and old != filename and (folder / old).exists():
            (folder / old).unlink()
        flash("Photo updated." if filename else "Photo removed.", "success")
        return redirect(url_for("driver_profile", token=ctx["token"], driver_id=driver_id))

    @app.route("/career/<token>/avatar/<name>")
    def avatar(token, name):
        if not g.user and not request.args.get("k"):
            abort(404)
        safe = Path(name).name
        path = storage.data_dir() / "avatars" / (storage.sanitize_token(token) or "_") / safe
        if safe != name or not path.is_file():
            abort(404)
        if not g.user or not (is_master() or _is_member(token)):
            try:
                with storage.session(token) as conn:
                    ok = community.features(conn)["public"] and hmac.compare_digest(
                        request.args.get("k", ""), community.public_key(conn))
            except CareerNotFound:
                ok = False
            if not ok:
                abort(404)
        response = send_file(path, max_age=86400)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def _is_member(token):
        try:
            with storage.session(token) as conn:
                return bool(conn.execute("SELECT 1 FROM career_members WHERE username = ?",
                                         (g.user["username"],)).fetchone())
        except CareerNotFound:
            return False

    # ---------------------------------------------------------------- public page
    def public_view(fn):
        """Public pages: only for leagues set to Public or Discoverable, with the right link. Everything shown is
        built from submitted rounds only; drafts, notes, emails, roles and settings are never read here."""
        @wraps(fn)
        def wrapper(token, key, *args, **kwargs):
            try:
                with storage.session(token) as conn:
                    if storage.get_meta(conn, "demo") == "1" or not league_profile.is_public(conn) \
                            or not hmac.compare_digest(str(key), community.public_key(conn)):
                        abort(404)
                    g.tz = storage.get_meta(conn, "timezone") or timefmt.DEFAULT_TZ
                    g.race_window = int(storage.get_meta(conn, "race_window") or timefmt.DEFAULT_RACE_WINDOW)
                    prof = league_profile.profile(conn)
                    accent, on_accent = _accent(prof["accent"])
                    pub = {"token": token, "key": key, "name": prof["name"], "profile": prof, "accent": accent,
                           "on_accent": on_accent, "season": S.get_season(conn, S.current_season_id(conn)),
                           "seasons": S.list_seasons(conn), "public_incidents": prof["public_incidents"],
                           "base": url_for("public_page", token=token, key=key)}
                    return fn(conn, pub, *args, **kwargs)
            except CareerNotFound:
                abort(404)
        return wrapper

    def _public_render(view, pub, **kwargs):
        return render_template("public.html", view=view, pub=pub, token=pub["token"], key=pub["key"], **kwargs)

    @app.route("/public/<token>/<key>")
    @public_view
    def public_page(conn, pub):
        sid = pub["season"]["id"]
        evs = S.events(conn, sid)
        done = [e for e in evs if e["status"] == C.EVENT_COMPLETE]
        last = done[-1] if done else None
        return _public_render("home", pub, drivers=S.driver_standings(conn, sid, completed_only=True),
                              constructors=S.constructor_standings(conn, sid, completed_only=True), events=evs,
                              winners={e["id"]: community.race_story(conn, e["id"])["podium"][:1] for e in done},
                              last=last, story=community.race_story(conn, last["id"]) if last else None,
                              profiles=community.profiles(conn), next_event=S.next_incomplete_event(conn, sid),
                              news=feed.latest(conn, 5))

    @app.route("/public/<token>/<key>/calendar")
    @public_view
    def public_calendar(conn, pub):
        evs = S.events(conn, pub["season"]["id"])
        done = {e["id"] for e in evs if e["status"] == C.EVENT_COMPLETE}
        return _public_render("calendar", pub, events=evs, winners={e: community.race_story(conn, e)["podium"][:1] for e in done})

    @app.route("/public/<token>/<key>/calendar.ics")
    @public_view
    def public_calendar_ics(conn, pub):
        return _ics_response(pub["name"], pub["season"], S.events(conn, pub["season"]["id"]),
                             url_for("public_page", token=pub["token"], key=pub["key"], _external=True) + "/round")

    @app.route("/public/<token>/<key>/standings")
    @app.route("/public/<token>/<key>/season/<int:season_id>")
    @public_view
    def public_standings(conn, pub, season_id=None):
        season = S.get_season(conn, season_id) if season_id else pub["season"]
        if not season:
            abort(404)
        return _public_render("standings", pub, season=season,
                              drivers=S.driver_standings(conn, season["id"], completed_only=True),
                              constructors=S.constructor_standings(conn, season["id"], completed_only=True))

    @app.route("/public/<token>/<key>/round/<int:event_id>")
    @public_view
    def public_round(conn, pub, event_id):
        event = S.get_event(conn, event_id)
        if not event or event["status"] != C.EVENT_COMPLETE:   # never an unsubmitted round
            abort(404)
        rows = sorted(S.weekend_rows(conn, event_id), key=lambda r: (r["result_status"] != C.STATUS_FINISHED,
                                                                     r["race_position"] or 99))
        return _public_render("round", pub, event=event, rows=rows, story=community.race_story(conn, event_id),
                              season=S.get_season(conn, event["season_id"]))

    @app.route("/public/<token>/<key>/driver/<int:driver_id>")
    @public_view
    def public_driver(conn, pub, driver_id):
        driver = S.driver_map(conn).get(driver_id)
        if not driver:
            abort(404)
        timeline = S.driver_timeline(conn, driver_id, S.all_season_standings(conn, completed_only=True))
        return _public_render("driver", pub, driver=driver, timeline=timeline, totals=S.career_totals(timeline),
                              profile=community.profile(conn, driver_id))

    @app.route("/public/<token>/<key>/team/<int:team_id>")
    @public_view
    def public_team(conn, pub, team_id):
        team = S.team_map(conn).get(team_id)
        if not team:
            abort(404)
        archive, totals = S.team_history(conn, team_id, completed_only=True)
        gmap = S.grid_map(conn, pub["season"]["id"])
        dmap = S.driver_map(conn)
        return _public_render("team", pub, team=team, archive=archive, totals=totals,
                              lineup=[dmap.get(gmap.get((team_id, s))) for s in (1, 2)])

    @app.route("/public/<token>/<key>/records")
    @public_view
    def public_records(conn, pub):
        return _public_render("records", pub, rows=S.hall_of_records(conn, completed_only=True),
                              records=insights.all_time_records(conn, completed_only=True))

    @app.route("/public/<token>/<key>/news")
    @public_view
    def public_news(conn, pub):
        return _public_render("news", pub, news=feed.latest(conn, 40))

    @app.route("/public/<token>/<key>/incidents")
    @public_view
    def public_incidents(conn, pub):
        if not pub["public_incidents"]:
            abort(404)
        decided = [i for i in community.incidents(conn) if i["status"] != "Open"]
        return _public_render("incidents", pub, incidents=decided)

    @app.route("/help")
    def help_page():
        return render_template("help.html")

    @app.route("/whats-new", methods=["POST"])
    def whats_new_ack():
        from . import whatsnew
        if not request.form.get("agree"):
            # v2.1: an update has to be agreed to; there's no "later".
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=False, error="Tick the box to agree to the changes"), 400
            flash("Tick the box to agree to the changes.", "error")
            return redirect(request.referrer or url_for("home"))
        whatsnew.acknowledge(g.user["username"], C.APP_VERSION)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=True)
        return redirect(request.referrer or url_for("home"))

    @app.route("/changelog")
    def changelog_page():
        from . import changelog
        return render_template("changelog.html", versions=changelog.versions(_base_dir()))

    # ---------------------------------------------------------------- app install & phone alerts
    @app.route("/sw.js")
    def service_worker():
        response = send_file(Path(app.static_folder) / "sw.js", mimetype="application/javascript", max_age=0)
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.route("/manifest.webmanifest")
    def web_manifest():
        return send_file(Path(app.static_folder) / "manifest.webmanifest", mimetype="application/manifest+json")

    @app.route("/push/subscribe", methods=["POST"])
    def push_subscribe():
        try:
            push.subscribe(g.user["username"], request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True)

    @app.route("/push/unsubscribe", methods=["POST"])
    def push_unsubscribe():
        push.unsubscribe((request.get_json(silent=True) or {}).get("endpoint", ""), g.user["username"])
        return jsonify(ok=True)

    @app.route("/push/test", methods=["POST"])
    def push_test():
        sent = push.send([g.user["username"]], "Paddock Legacy", "Alerts are working 🏁", url_for("home"))
        return jsonify(ok=bool(sent), sent=sent,
                       error=None if sent else "Nothing was delivered. Turn alerts on for this device first.")

    # ---------------------------------------------------------------- saves
    @app.route("/career/<token>/save", methods=["POST"])
    @career_page(master_only=True)
    def save_now(conn, ctx):
        flash("League saved.", "success")
        return redirect(request.referrer or url_for("dashboard", token=ctx["token"]))

    @app.route("/career/<token>/rename", methods=["POST"])
    @career_page(master_only=True)
    def rename(conn, ctx):
        name = (request.form.get("name") or "").strip()[:80]
        if not name:
            raise ValidationError("League name cannot be blank")
        storage.set_meta(conn, "career_name", name)
        flash("League renamed.", "success")
        return redirect(request.referrer or url_for("dashboard", token=ctx["token"]))

    @app.route("/career/<token>/copy", methods=["POST"])
    @master_required
    def save_as(token):
        name = (request.form.get("name") or "").strip()[:80] or "Career copy"
        try:
            storage.checkpoint(token)
            new = storage.save_as(token, name)
        except CareerNotFound:
            abort(404)
        flash("Saved as a new, independent league.", "success")
        return redirect(url_for("dashboard", token=new))

    @app.route("/career/<token>/delete", methods=["POST"])
    @master_required
    def delete(token):
        try:
            with storage.session(token) as conn:
                name = storage.get_meta(conn, "career_name", "")
            if (request.form.get("confirm_name") or "").strip() != name:
                flash("Type the league's exact name to delete it. Nothing was deleted.", "error")
                return redirect(url_for("backups_page", token=token) + "#danger")
            storage.auto_backup(token, "before-delete", force=True)   # kept by the site, so an admin can recover it
            storage.delete_career(token)
        except CareerNotFound:
            abort(404)
        flash("League deleted.", "success")
        return redirect(url_for("home"))

    @app.route("/career/<token>/backup")
    @master_required
    def backup(token):
        try:
            path = storage.make_backup(token)
        except CareerNotFound:
            abort(404)
        return send_file(io.BytesIO(storage.redacted_copy(path)), as_attachment=True, download_name=path.name,
                         mimetype="application/octet-stream")

    @app.route("/career/<token>/export")
    @master_required
    def export(token):
        try:
            data = storage.export_json(token)
        except CareerNotFound:
            abort(404)
        return send_file(io.BytesIO(data.encode("utf-8")), as_attachment=True,
                         download_name=f"career-{storage.sanitize_token(token)}.json", mimetype="application/json")
