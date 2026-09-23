"""Flask application: pages, mutation routes, logins and access control."""

import hmac
import io
import os
import secrets
import sys
import tempfile
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   session, url_for)

import random

from . import (auth, community, discord, feed, insights, mailer, market, push, relations, roles,
               services as S, storage, teamlife, timefmt)
from . import circuits
from . import constants as C
from .auth import AuthError
from .services import ValidationError
from .storage import CareerNotFound


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


PUBLIC_ENDPOINTS = {"login", "setup", "static", "register", "register_verify", "register_resend", "forgot",
                    "reset_password", "public_page", "service_worker", "web_manifest", "avatar"}

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
}
QUIET_ENDPOINTS = {"timezone_detect", "notifications_read", "notifications_clear", "checkin", "comment_add", "react", "fan_vote_route", "prediction_save",
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
            if not g.user:
                session.clear()
            elif g.user["is_steward"]:  # an old account-wide Scorekeeper: move it into their leagues first
                roles.unify_legacy_scorekeepers()
                g.user = auth.get_user(session["user"])
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
        if items and response.status_code < 400 and not app.config.get("TESTING"):
            try:
                push.dispatch(items, request.host_url.rstrip("/"), exclude=g.user["username"] if g.get("user") else None)
            except Exception:
                app.logger.exception("push alerts failed")
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
                "APP_NAME": C.APP_NAME, "C": C, "push_key": key}

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
                    mine = g.ctx["my_driver"]
                    g.ctx["role"] = C.ACCESS_ROLES[g.league_role] + (" · Driver" if mine else "")
                    if g.league_role == "member" and mine:
                        g.ctx["role"] = "Driver"
                    g.ctx["pending_offers"] = conn.execute(
                        "SELECT COUNT(*) FROM offers WHERE status = ?" + (" AND driver_id = ?" if mine and not is_master() else ""),
                        (C.OFFER_PENDING, mine["id"]) if mine and not is_master() else (C.OFFER_PENDING,)).fetchone()[0]
                    g.ctx["notifications"], g.ctx["unread"] = feed.notifications_for(
                        conn, g.user["username"], mine["id"] if mine else None, is_master() and not mine)
                    storage.touch_opened(conn)
                    gate = _pledge_gate(conn, g.ctx, master_only)
                    if gate is not None:
                        return gate
                    described = _describe_targets(conn, kwargs) if request.method == "POST" else ("", None)
                    result = fn(conn, g.ctx, *args, **kwargs)
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


# The only league POSTs a Spectator may make: marking their own notifications and the time-zone probe.
SPECTATOR_POST_OK = {"notifications_read", "notifications_clear", "timezone_detect"}

PLEDGE_EXEMPT = {"pledge_page", "pledge_save", "api_notifications", "notifications_read", "notifications_clear",
                 "help_page"}


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
    """League Settings changes as a sentence, e.g. "changed join requests from Off to On". No private values."""
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
    return "; ".join(changes)


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
    if "username" in kwargs:
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
            session.clear()
            session["user"] = username
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
            session.clear()
            session["user"] = user["username"]
            target = request.args.get("next") or ""
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("home")
            return redirect(target)
        return render_template("login.html", mode="login", signups=auth.signups_allowed())

    def _send_signup_code(email, code, display_name):
        mailer.send([email], f"Your F1 Universe Tracker code: {code}",
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
            session.clear()
            session["user"] = username
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
                        f"F1 Universe Tracker. Open this link within {auth.RESET_MINUTES} minutes to choose a new one:\n\n"
                        f"{link}\n\nIf that wasn't you, ignore this email and nothing changes.")
                sent = mailer.send_later([user["email"]], "Reset your F1 Universe Tracker password", text) or sent
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
            saved = auth.set_email(g.user["username"], request.form.get("email"), request.form.get("email_results"))
            if saved:
                flash("Email settings saved." + (" Race results will be emailed to you." if request.form.get("email_results")
                                                 else ""), "success")
            else:
                flash("Email address removed. Race-result emails are off until you add one.", "success")
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
            mailer.send([g.user["email"]], "F1 Universe Tracker test email",
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
        for field in ("smtp_host", "smtp_port", "smtp_username", "smtp_from"):
            if field in request.form:
                auth.set_setting(field, (request.form.get(field) or "").strip() or None)
        if (request.form.get("smtp_password") or "").strip():
            auth.set_setting("smtp_password", request.form.get("smtp_password").strip())
        flash("Settings saved.", "success")
        return redirect(url_for("accounts_page"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/accounts")
    def accounts_page():
        memberships = {}
        if is_master():
            for c in storage.list_careers():
                for username in c["members"]:
                    memberships.setdefault(username, []).append(c["name"])
        return render_template("accounts.html", users=auth.list_users() if is_master() else [],
                               memberships=memberships, signups=auth.signups_allowed(),
                               mail=mailer.config(), mail_ready=mailer.configured(),
                               pw_min=auth.PASSWORD_MIN)

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
            flash("Password changed. Use your new password next time you log in.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page") + "#password")

    # ---------------------------------------------------------------- career library
    @app.route("/")
    def home():
        everything = storage.list_careers()
        careers = everything if is_master() else [c for c in everything if g.user["username"] in c["members"]]
        me = g.user["username"]
        outside = [c for c in everything if me not in c["members"] and not is_master()]
        joinable = [c for c in outside if c["join_mode"] == "requests" and me not in c["invited"]]
        invited = [c for c in outside if me in c["invited"]]
        return render_template("home.html", careers=careers, joinable=joinable, invited=invited,
                               join_modes=storage.JOIN_MODES,
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
                conn.execute("INSERT INTO join_requests(username, driver_name, message, created_at, role) VALUES(?,?,?,?,?)",
                             (me, driver_name, (request.form.get("message") or "").strip()[:300], storage.now_iso(), role))
                what = f"as {driver_name}" if drives else f"as {C.LEAGUE_ROLES[role]}"
                if role == "driver_scorekeeper":
                    what += " (and Scorekeeper)"
                feed.notify(conn, None, f"{g.user['display_name']} asked to join {what}", "members")
        except CareerNotFound:
            abort(404)
        except ValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("home"))
        flash("Request sent. You'll see the league here once the Race Master approves it.", "success")
        return redirect(url_for("home"))

    @app.route("/careers/new", methods=["POST"])
    @master_required
    def career_new():
        name = (request.form.get("name") or "").strip()[:80] or "F1 Career"
        token = storage.new_token()
        try:
            names = request.form.getlist("player_name")
            logins = request.form.getlist("player_login")
            rows = [(n, logins[i] if i < len(logins) else "") for i, n in enumerate(names) if (n or "").strip()]
            chosen = [auth.normalise(l) for _, l in rows if l]
            if len(chosen) != len(set(chosen)):
                raise ValidationError("One login can only drive one player driver")
            with storage.session(token, create=True) as conn:
                S.seed_career(conn, token, name, request.form.get("year") or 2026, [n for n, _ in rows])
                mode = request.form.get("join_mode") or ("requests" if request.form.get("join_open") else "invite")
                storage.set_join_mode(conn, mode if mode in storage.JOIN_MODES else "requests")
                community.set_features(conn, {k for k in C.FEATURES if request.form.get(f"feature_{k}")})
                players = S.player_drivers(conn)
                for (_, login), driver in zip(rows, players):
                    username = auth.normalise(login)
                    user = auth.get_user(username) if username else None
                    if user:
                        roles.set_member(conn, username, "race_master" if user["is_master"] else "member", driver["id"])
                if request.form.get("rookie_market") and players:
                    market.open_window(conn, S.current_season_id(conn), kind="Rookie Draft")
        except (ValidationError, ValueError) as exc:
            try:
                storage.delete_career(token)
            except CareerNotFound:
                pass
            flash(str(exc), "error")
            return redirect(url_for("home"))
        flash("League created." + (" Rookie offers are waiting in each player's garage."
                                   if request.form.get("rookie_market") and rows else "")
              + (" Other people can now ask to join from the league library."
                 if (request.form.get("join_mode") or ("requests" if request.form.get("join_open") else "")) == "requests"
                 else ""),
              "success")
        return redirect(url_for("dashboard", token=token))

    @app.route("/careers/import", methods=["POST"])
    @master_required
    def career_import():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            flash("Choose a .f1career file to import.", "error")
            return redirect(url_for("home"))
        if not upload.filename.lower().endswith(storage.CAREER_EXT):
            flash("Only .f1career files can be imported.", "error")
            return redirect(url_for("home"))
        fd, tmp = tempfile.mkstemp(suffix=storage.CAREER_EXT)
        os.close(fd)
        try:
            upload.save(tmp)
            token = storage.import_career(tmp)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("home"))
        finally:
            os.unlink(tmp)
        flash("League imported.", "success")
        return redirect(url_for("dashboard", token=token))

    # ---------------------------------------------------------------- main pages
    @app.route("/career/<token>/dashboard")
    @career_page()
    def dashboard(conn, ctx):
        sid = ctx["season"]["id"]
        evs = S.events(conn, sid)
        nxt = S.next_incomplete_event(conn, sid)
        before = (ctx["season"]["year"], nxt["round_number"]) if nxt else None
        return page("dashboard.html", ctx, events=evs, next_event=nxt,
                    completed=sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE),
                    drivers=insights.standings_with_changes(conn, sid, 8),
                    progress=insights.season_progress(conn, sid),
                    card=insights.driver_card(conn, sid, ctx["my_driver"]["id"]) if ctx["my_driver"] else None,
                    contract=market.current_contract(conn, ctx["my_driver"]["id"]) if ctx["my_driver"] else None,
                    constructors=S.constructor_standings(conn, sid)[:5],
                    rec=S.difficulty_recommendation(conn, before),
                    windows=[w for w in market.windows(conn) if w["status"] == C.WINDOW_OPEN],
                    news=feed.latest(conn, 6), chart=insights.progression_chart(conn, sid),
                    hub=_hub(conn, ctx, nxt) if nxt else None,
                    circuit=circuits.lookup(nxt["name"], nxt["location"]) if nxt else None,
                    press=teamlife.press_pen(conn, ctx["current_season_id"], ctx["my_driver"]["id"])
                    if ctx["my_driver"] and sid == ctx["current_season_id"] else None)

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
                    rec=_weekend_recommendation(conn, season, event),
                    entrants=_entrants(conn, event_id),
                    gp_points=C.GP_POINTS, sprint_points=C.SPRINT_POINTS, hub=_hub(conn, ctx, event, full=True),
                    incidents=community.incidents(conn, event_id=event_id),
                    share=_share_card(conn, ctx, event) if event["status"] == C.EVENT_COMPLETE else None)

    def _entrants(conn, event_id):
        """The drivers in this round, for the screenshot importer to match against (never anyone else)."""
        return [{"id": r["driver_id"], "name": r["driver"]["name"], "team": r["team"]["name"],
                 "is_player": bool(r["driver"]["is_player"]), "color": r["driver"]["player_color"]}
                for r in S.weekend_rows(conn, event_id)]

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
        return page("drivers.html", ctx, standings=S.driver_standings(conn, ctx["season"]["id"]),
                    teams=S.teams(conn), chart=insights.progression_chart(conn, ctx["season"]["id"], top=6))

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
                    details=S.team_details(conn, team_id, ctx["season"]["id"]))

    @app.route("/career/<token>/grid")
    @career_page()
    def grid_page(conn, ctx):
        sid = ctx["season"]["id"]
        seats = S.driver_seats(conn, sid)
        return page("grid.html", ctx, grid=S.grid(conn, sid), players=S.player_drivers(conn), seats=seats,
                    all_drivers=S.drivers(conn, active_only=True))

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

    @app.route("/career/<token>/seasons")
    @career_page()
    def seasons_page(conn, ctx):
        seasons = S.list_seasons(conn)
        latest = seasons[-1] if seasons else None
        return page("seasons.html", ctx, seasons_list=seasons, events=S.events(conn, ctx["season"]["id"]),
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

    @app.route("/career/<token>/seasons/new", methods=["POST"])
    @career_page(master_only=True)
    def season_new(conn, ctx):
        latest = S.list_seasons(conn)[-1]
        released = relations.decide_releases(conn, latest["id"], final=True)
        relations.settle(conn, latest["id"])
        new_id = S.create_next_season(conn, latest["id"], request.form.get("year"))
        rewarded = relations.apply_rewards(conn, latest["id"], new_id)
        changes = S.develop_cars(conn, latest["id"], new_id, random.Random())
        feed.on_new_season(conn, latest["id"], new_id, changes, f"review/{latest['id']}")
        market.on_new_season(conn, new_id, previous_id=latest["id"])
        if rewarded:
            flash(f"{len(rewarded)} player driver(s) kept their pledge and start the new season with extra Reputation.",
                  "success")
        if released:
            flash(f"{len(released)} player driver(s) were released by their team at the end of the season.", "success")
        session[f"season_{ctx['token']}"] = new_id
        flash("New season created. Signed contracts have been applied; review the grid.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]))

    @app.route("/career/<token>/calendar/save", methods=["POST"])
    @career_page(master_only=True)
    def calendar_save(conn, ctx):
        sid = ctx["season"]["id"]
        entries = []
        for e in S.events(conn, sid):
            entries.append({"id": e["id"], "round_number": request.form.get(f"round_{e['id']}"),
                            "name": request.form.get(f"name_{e['id']}"),
                            "location": request.form.get(f"location_{e['id']}"),
                            "is_sprint": request.form.get(f"sprint_{e['id']}")})
        S.save_calendar(conn, sid, entries)
        flash("Calendar saved.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    # ---------------------------------------------------------------- transfer market & garage
    @app.route("/career/<token>/garage")
    @career_page()
    def garage(conn, ctx):
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
        return page("garage.html", ctx, driver=driver, me=me, interest=interest, row=row,
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
        return redirect(url_for("dashboard", token=ctx["token"]) + "#press")

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
                    needs_pledge=relations.needs_pledge(conn, sid, driver["id"]),
                    notes=relations.notes(conn, sid, driver["id"]), teammate=teammate,
                    contract=market.current_contract(conn, driver["id"]),
                    own=bool(ctx["my_driver"] and ctx["my_driver"]["id"] == driver["id"]))

    @app.route("/career/<token>/market")
    @career_page()
    def market_page(conn, ctx):
        if not ctx["is_master"]:
            return redirect(url_for("garage", token=ctx["token"]))
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
              + (f" {applied} signing(s) had already moved a driver; fix seats in Grid & Transfers if needed."
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
        return redirect(url_for("garage", token=ctx["token"], driver=offer["driver_id"]))

    @app.route("/career/<token>/offers/<int:offer_id>/decline", methods=["POST"])
    @career_page()
    def offer_decline(conn, ctx, offer_id):
        offer = _offer_for_user(conn, ctx, offer_id)
        market.decline_offer(conn, offer_id)
        flash("Offer declined.", "success")
        return redirect(url_for("garage", token=ctx["token"], driver=offer["driver_id"]))

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
        return redirect(url_for("garage", token=ctx["token"], driver=offer["driver_id"]) + f"#offer-{offer_id}")

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
               "offer": f"{team} want to talk. Their opening terms are in your garage.",
               "agreed": f"{team} agreed to your terms! Sign to make it official.",
               "countered": f"{team} came back with a counter-offer.",
               "final": f"{team} made a take-it-or-leave-it offer.",
               "collapsed": f"{team} weren't impressed by your demands and ended talks."}[result],
              "error" if result in ("rejected", "collapsed") else "success")
        return redirect(url_for("garage", token=ctx["token"], driver=driver_id) + f"#offer-{offer_id}")

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
              "(League & Saves → automatic backups).", "success")
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
            flash("Driver added. Put them in a seat from Grid & Transfers.", "success")
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
            flash("Team added with two empty seats. Fill them in Grid & Transfers.", "success")
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
        return send_file(path, as_attachment=True, download_name=path.name)

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
                                 ". Place them in a seat from Grid & Transfers or send offers later."), "success")
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
            user = auth.get_user(req["username"])
            if user["email"]:
                mailer.send_later([user["email"]], f"You're in: {ctx['career_name']}",
                                  f"Your request to join {ctx['career_name']} was approved. You joined {what}."
                                  + (f" The Race Master changed your role from what you asked for "
                                     f"({C.LEAGUE_ROLES.get(req['role'], 'Driver')})." if changed else "")
                                  + f"\n\n{url_for('dashboard', token=ctx['token'], _external=True)}")
        else:
            flash(f"Request from {req['username']} declined.", "success")
        conn.execute("UPDATE join_requests SET status = ?, decided_at = ? WHERE id = ?",
                     ("Approved" if decision == "approve" else "Declined", storage.now_iso(), request_id))
        return redirect(url_for("members", token=ctx["token"]))

    INVITE_ROLES = ("member", "scorekeeper", "spectator")

    @app.route("/career/<token>/members/invite", methods=["POST"])
    @career_page(master_only=True)
    def member_invite(conn, ctx):
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
        conn.execute("""INSERT INTO invitations(username, role, invited_by, status, created_at) VALUES(?,?,?,'Pending',?)
                        ON CONFLICT(username) DO UPDATE SET role = excluded.role, invited_by = excluded.invited_by,
                        status = 'Pending', created_at = excluded.created_at, decided_at = NULL""",
                     (user["username"], role, g.user["username"], storage.now_iso()))
        community.audit(conn, g.user["username"], "Invited", f"{user['username']} as {C.ACCESS_ROLES[role]}",
                        summary=f"invited {user['display_name']} to join as {C.ACCESS_ROLES[role]}", link="members")
        if user["email"]:
            mailer.send_later([user["email"]], f"You're invited to {ctx['career_name']}",
                              f"{g.user['display_name']} invited you to join {ctx['career_name']} as "
                              f"{C.ACCESS_ROLES[role]}. Accept it from your League Library:\n\n"
                              f"{url_for('home', _external=True)}")
        flash(f"Invitation sent to {user['display_name']}. They'll see it in their League Library.", "success")
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
        """Someone invited to a league accepts or declines from their League Library."""
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
                        roles.set_member(conn, me, "race_master" if g.user["is_master"] else inv["role"], None)
                    feed.notify(conn, None, f"{g.user['display_name']} accepted an invitation and joined", "members")
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
        if not mailer.configured():
            return
        with storage.session(token) as conn:
            usernames = [r["username"] for r in conn.execute("SELECT username FROM career_members")]
            url = url_for("weekend", token=token, event_id=event_id, _external=True)
            subject, text, html = feed.results_email(conn, event_id, url)
        recipients = [u["email"] for u in (auth.get_user(n) for n in usernames)
                      if u and u["email"] and u["email_results"]]
        mailer.send_later(recipients, subject, text, html)

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
        if ctx["my_driver"]:
            order = conn.execute("SELECT * FROM team_orders WHERE event_id = ? AND driver_id = ?",
                                 (event["id"], ctx["my_driver"]["id"])).fetchone()
            if order:
                hub["order"] = {**dict(order), "beneficiary": S.driver_map(conn).get(order["beneficiary_id"])}
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
                      "discord": discord.settings(conn), "window": ctx["race_window"], "tz": ctx["timezone"]}
            community.set_features(conn, {k for k in C.FEATURES if request.form.get(f"feature_{k}")})
            if request.form.get("join_mode") in storage.JOIN_MODES:
                storage.set_join_mode(conn, request.form.get("join_mode"))
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
            g.audit_summary = _settings_changes(conn, before) or "saved League Settings without changes"
            flash("League settings saved.", "success")
            return redirect(url_for("league_settings", token=ctx["token"]))
        feats = community.features(conn)
        link = url_for("public_page", token=ctx["token"], key=community.public_key(conn), _external=True) \
            if feats["public"] else None
        return page("settings.html", ctx, feats=feats, public_link=link, discord=discord.settings(conn),
                    zones=timefmt.COMMON_ZONES, windows=timefmt.RACE_WINDOW_CHOICES,
                    join_mode=storage.join_mode(conn), join_modes=storage.JOIN_MODES)

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
            discord.post(cfg["url"], f"👋 F1 Universe Tracker is connected to **{ctx['career_name']}**.")
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
                        ref=f"racetime:{event_id}")
            flash("Round marked as postponed.", "success")
            return redirect(url_for("weekend", token=ctx["token"], event_id=event_id))
        if when:
            event = S.get_event(conn, event_id)
            feed.notify(conn, None, f"Race night set: R{event['round_number']} {event['name']}", f"weekend/{event_id}",
                        ref=f"racetime:{event_id}")
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
    @app.route("/public/<token>/<key>")
    def public_page(token, key):
        try:
            with storage.session(token) as conn:
                if not community.features(conn)["public"] or not hmac.compare_digest(key, community.public_key(conn)):
                    abort(404)
                g.tz = storage.get_meta(conn, "timezone") or timefmt.DEFAULT_TZ
                g.race_window = int(storage.get_meta(conn, "race_window") or timefmt.DEFAULT_RACE_WINDOW)
                sid = S.current_season_id(conn)
                evs = S.events(conn, sid)
                done = [e for e in evs if e["status"] == C.EVENT_COMPLETE]
                last = done[-1] if done else None
                return render_template(
                    "public.html", name=storage.get_meta(conn, "career_name", "F1 League"), season=S.get_season(conn, sid),
                    drivers=S.driver_standings(conn, sid), constructors=S.constructor_standings(conn, sid), events=evs,
                    winners={e["id"]: community.race_story(conn, e["id"])["podium"][:1] for e in done},
                    last=last, story=community.race_story(conn, last["id"]) if last else None,
                    profiles=community.profiles(conn), token=token, key=key,
                    next_event=S.next_incomplete_event(conn, sid))
        except CareerNotFound:
            abort(404)

    @app.route("/help")
    def help_page():
        return render_template("help.html")

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
        sent = push.send([g.user["username"]], "F1 Universe Tracker", "Alerts are working 🏁", url_for("home"))
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
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/career/<token>/export")
    @master_required
    def export(token):
        try:
            data = storage.export_json(token)
        except CareerNotFound:
            abort(404)
        return send_file(io.BytesIO(data.encode("utf-8")), as_attachment=True,
                         download_name=f"career-{storage.sanitize_token(token)}.json", mimetype="application/json")
