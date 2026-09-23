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

from . import auth, feed, importer, insights, mailer, market, services as S, storage
from . import constants as C
from .auth import AuthError
from .services import ValidationError
from .storage import CareerNotFound


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


PUBLIC_ENDPOINTS = {"login", "setup", "static", "register", "forgot", "reset_password"}


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
    return app


# --------------------------------------------------------------------------- hooks & helpers

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def register_hooks(app):
    @app.before_request
    def guard():
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

    @app.context_processor
    def inject():
        return {"csrf_token": csrf_token, "user": g.get("user"), "APP_VERSION": C.APP_VERSION,
                "APP_NAME": C.APP_NAME, "C": C}

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="That page belongs to the Race Master."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="That career or page could not be found."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413, message="Uploads are limited to 100 MB."), 413


def is_master():
    return bool(g.user and g.user["is_master"])


def can_run():
    """Race Master or Race Steward: may run race weekends and seasons."""
    return bool(g.user and (g.user["is_master"] or g.user.get("is_steward")))


def master_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_master():
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
                    linked = conn.execute("SELECT 1 FROM career_members WHERE username = ?",
                                          (g.user["username"],)).fetchone()
                    if not is_master() and not linked:
                        abort(403)
                    if master_only and not is_master():
                        abort(403)
                    if ops_only and not can_run():
                        abort(403)
                    season_id = _selected_season(conn, token)
                    g.ctx = {
                        "token": token,
                        "career_name": storage.get_meta(conn, "career_name", "Career"),
                        "season": S.get_season(conn, season_id),
                        "current_season_id": S.current_season_id(conn),
                        "seasons": S.list_seasons(conn),
                        "is_master": is_master(),
                        "can_run": can_run(),
                        "role": auth.ROLES[auth.role_of(g.user)],
                        "my_driver": _member_driver(conn),
                        "open_windows": conn.execute("SELECT COUNT(*) FROM market_windows WHERE status = ?",
                                                     (C.WINDOW_OPEN,)).fetchone()[0],
                    }
                    mine = g.ctx["my_driver"]
                    g.ctx["pending_offers"] = conn.execute(
                        "SELECT COUNT(*) FROM offers WHERE status = ?" + (" AND driver_id = ?" if mine and not is_master() else ""),
                        (C.OFFER_PENDING, mine["id"]) if mine and not is_master() else (C.OFFER_PENDING,)).fetchone()[0]
                    g.ctx["notifications"], g.ctx["unread"] = feed.notifications_for(
                        conn, g.user["username"], mine["id"] if mine else None, is_master() and not mine)
                    storage.touch_opened(conn)
                    return fn(conn, g.ctx, *args, **kwargs)
            except CareerNotFound:
                abort(404)
            except (ValidationError, AuthError) as exc:
                if request.method != "POST":
                    raise
                flash(str(exc), "error")
                return redirect(request.referrer or url_for("dashboard", token=token))
        return wrapper
    return deco


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

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            if request.form.get("password") != request.form.get("confirm"):
                flash("The two passwords don't match.", "error")
                return redirect(url_for("register"))
            try:
                username = auth.register(request.form.get("username"), request.form.get("display_name"),
                                         request.form.get("password"), request.remote_addr, request.form.get("email"))
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("register"))
            session.clear()
            session["user"] = username
            flash("Account created. Pick an open league below and ask to join, or wait for a Race Master to add you.", "success")
            return redirect(url_for("home"))
        return render_template("login.html", mode="register", signups=auth.signups_allowed())

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
            auth.set_email(g.user["username"], request.form.get("email"), request.form.get("email_results"))
            flash("Email settings saved.", "success")
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
        key = (request.form.get("anthropic_api_key") or "").strip()
        if request.form.get("clear_key"):
            auth.set_setting("anthropic_api_key", None)
        elif key:
            auth.set_setting("anthropic_api_key", key)
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
                               key_set=importer.configured(), mail=mailer.config(), mail_ready=mailer.configured())

    @app.route("/accounts/new", methods=["POST"])
    @master_required
    def account_new():
        try:
            role = request.form.get("role", "driver")
            auth.create_user(request.form.get("username"), request.form.get("display_name"),
                             request.form.get("password"), is_master=role == "master", is_steward=role == "steward",
                             email=request.form.get("email"))
            flash("Account created.", "success")
        except AuthError as exc:
            flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    @app.route("/accounts/<username>/password", methods=["POST"])
    @master_required
    def account_reset(username):
        try:
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
        if not auth.verify(g.user["username"], request.form.get("current_password")):
            flash("Current password is wrong.", "error")
        else:
            try:
                auth.set_password(g.user["username"], request.form.get("password"))
                flash("Password changed.", "success")
            except AuthError as exc:
                flash(str(exc), "error")
        return redirect(url_for("accounts_page"))

    # ---------------------------------------------------------------- career library
    @app.route("/")
    def home():
        everything = storage.list_careers()
        careers = everything if is_master() else [c for c in everything if g.user["username"] in c["members"]]
        joinable = [c for c in everything if c["join_open"] and g.user["username"] not in c["members"]
                    and not is_master()]
        return render_template("home.html", careers=careers, joinable=joinable,
                               users=auth.list_users() if is_master() else [], default_year=2026)

    @app.route("/career/<token>/join", methods=["POST"])
    def career_join(token):
        driver_name = " ".join((request.form.get("driver_name") or "").split())[:60]
        try:
            with storage.session(token) as conn:
                if storage.get_meta(conn, "join_open") != "1":
                    raise ValidationError("This league isn't taking new drivers right now")
                me = g.user["username"]
                if conn.execute("SELECT 1 FROM career_members WHERE username = ?", (me,)).fetchone():
                    raise ValidationError("You're already in this league")
                if conn.execute("SELECT 1 FROM join_requests WHERE username = ? AND status = 'Pending'", (me,)).fetchone():
                    raise ValidationError("Your request is already waiting for the Race Master")
                if len(driver_name) < 2:
                    raise ValidationError("Choose a driver name")
                if conn.execute("SELECT 1 FROM drivers WHERE lower(name) = lower(?)", (driver_name,)).fetchone():
                    raise ValidationError("There's already a driver with that name in this league")
                conn.execute("INSERT INTO join_requests(username, driver_name, message, created_at) VALUES(?,?,?,?)",
                             (me, driver_name, (request.form.get("message") or "").strip()[:300], storage.now_iso()))
                feed.notify(conn, None, f"{g.user['display_name']} asked to join as {driver_name}", "members")
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
                storage.set_meta(conn, "join_open", "1" if request.form.get("join_open") else "0")
                players = S.player_drivers(conn)
                for (_, login), driver in zip(rows, players):
                    username = auth.normalise(login)
                    if username and auth.get_user(username):
                        conn.execute("INSERT OR REPLACE INTO career_members(username, driver_id) VALUES(?,?)",
                                     (username, driver["id"]))
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
              + (" Other people can now ask to join from the league library." if request.form.get("join_open") else ""),
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
        flash("Career imported.", "success")
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
                    drivers=S.driver_standings(conn, sid)[:6],
                    constructors=S.constructor_standings(conn, sid)[:5],
                    rec=S.difficulty_recommendation(conn, before),
                    windows=[w for w in market.windows(conn) if w["status"] == C.WINDOW_OPEN],
                    news=feed.latest(conn, 6), chart=insights.progression_chart(conn, sid))

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
                    rec=S.difficulty_recommendation(conn, (season["year"], event["round_number"])),
                    importer_ready=importer.configured(),
                    gp_points=C.GP_POINTS, sprint_points=C.SPRINT_POINTS)

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
        return page("driver_profile.html", ctx, driver=driver, timeline=timeline,
                    totals=S.career_totals(timeline), contract=market.current_contract(conn, driver_id),
                    trend=insights.driver_round_timeline(conn, driver_id))

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
        return page("team_profile.html", ctx, team=team, archive=archive, totals=totals)

    @app.route("/career/<token>/grid")
    @career_page()
    def grid_page(conn, ctx):
        sid = ctx["season"]["id"]
        seats = S.driver_seats(conn, sid)
        return page("grid.html", ctx, grid=S.grid(conn, sid), players=S.player_drivers(conn), seats=seats,
                    all_drivers=S.drivers(conn, active_only=True))

    @app.route("/career/<token>/grid/players", methods=["POST"])
    @career_page(ops_only=True)
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
    @career_page(ops_only=True)
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
                    drivers=S.drivers(conn, active_only=True), teams=S.teams(conn))

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
            return max(rows, key=lambda r: (r[key], r["points"]), default=None)
        return page("records.html", ctx, rows=rows, leaders={
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
    @career_page(ops_only=True)
    def season_switch(conn, ctx):
        sid = _form_int("season_id")
        S.make_current(conn, sid)
        session[f"season_{ctx['token']}"] = sid
        flash("Current season changed.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    @app.route("/career/<token>/seasons/new", methods=["POST"])
    @career_page(ops_only=True)
    def season_new(conn, ctx):
        latest = S.list_seasons(conn)[-1]
        new_id = S.create_next_season(conn, latest["id"], request.form.get("year"))
        changes = S.develop_cars(conn, latest["id"], new_id, random.Random())
        feed.on_new_season(conn, latest["id"], new_id, changes, f"review/{latest['id']}")
        market.on_new_season(conn, new_id)
        session[f"season_{ctx['token']}"] = new_id
        flash("New season created. Signed contracts have been applied; review the grid.", "success")
        return redirect(url_for("grid_page", token=ctx["token"]))

    @app.route("/career/<token>/calendar/save", methods=["POST"])
    @career_page(ops_only=True)
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
                    signed_in_window=signed_in_window, going_rate=market.market_salary(me["value"]),
                    trend=insights.driver_round_timeline(conn, driver["id"]))

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
                                      request.form.get("salary"), request.form.get("message", ""))
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
            request.form.get("salary") if terms else None, request.form.get("message", ""))
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
        return page("news.html", ctx, news=feed.latest(conn, 100))

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
                 "series": [{"name": f"{a['name']} ahead ↑ / {b['name']} ahead ↓", "values": data["swing"], "slot": 1}]}
        progress = insights.points_progression(conn, sid, [a["id"], b["id"]])
        season_chart = {"labels": progress[0], "yLabel": "Points",
                        "series": [{"name": a["name"], "values": progress[1][a["id"]], "player": True, "slot": 1},
                                   {"name": b["name"], "values": progress[1][b["id"]], "player": True, "slot": 2}]}
        return page("rivalry.html", ctx, a=a, b=b, r=data, chart=chart, season_chart=season_chart, options=options)

    @app.route("/career/<token>/review/<int:season_id>")
    @career_page()
    def season_review(conn, ctx, season_id):
        if not S.get_season(conn, season_id):
            abort(404)
        return page("review.html", ctx, review=insights.season_review(conn, season_id))

    @app.route("/career/<token>/paddock")
    @career_page(ops_only=True)
    def paddock_admin(conn, ctx):
        sid = ctx["current_season_id"]
        seats = S.driver_seats(conn, sid)
        tmap = S.team_map(conn)
        all_drivers = S.drivers(conn)
        for d in all_drivers:
            seat = seats.get(d["id"])
            d["team"] = tmap.get(seat[0]) if seat else None
            d["rep_now"] = S.starting_reputation(conn, sid, d["id"])
        all_teams = [dict(t) for t in conn.execute("SELECT * FROM teams ORDER BY active DESC, id")]
        return page("paddock.html", ctx, all_drivers=all_drivers, all_teams=all_teams,
                    ratings=S.car_ratings(conn, sid), season=S.get_season(conn, sid))

    @app.route("/career/<token>/paddock/driver", methods=["POST"])
    @career_page(ops_only=True)
    def paddock_driver(conn, ctx):
        sid = ctx["current_season_id"]
        driver_id = _form_int("driver_id")
        if driver_id:
            S.update_driver(conn, driver_id, sid, request.form.get("name"), request.form.get("baseline_reputation"),
                            request.form.get("active"))
            flash("Driver updated.", "success")
        else:
            S.add_driver(conn, request.form.get("name"), request.form.get("baseline_reputation"), sid)
            feed.post(conn, sid, "paddock", f"New face in the paddock: {request.form.get('name', '').strip()}",
                      "Available to teams from today.", "drivers")
            flash("Driver added. Put them in a seat from Grid & Transfers.", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/team", methods=["POST"])
    @career_page(ops_only=True)
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
    @career_page(ops_only=True)
    def paddock_cars(conn, ctx):
        sid = ctx["current_season_id"]
        for team in S.teams(conn):
            value = request.form.get(f"rating_{team['id']}")
            if value not in (None, ""):
                S.set_car_rating(conn, sid, team["id"], value)
        flash("Car ratings saved.", "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/paddock/recalculate", methods=["POST"])
    @career_page(ops_only=True)
    def paddock_recalculate(conn, ctx):
        storage.auto_backup(ctx["token"], "before-recalculate", force=True)
        changes = S.recalculate_reputation_history(conn)
        dmap = S.driver_map(conn)
        moved = [f"{dmap[d]['name']} {b} → {a}" for d, (b, a) in changes.items()
                 if dmap[d]["is_player"] and b is not None and b != a]
        flash("Reputation history recalculated." + (" " + "; ".join(moved) if moved else ""), "success")
        return redirect(url_for("paddock_admin", token=ctx["token"]))

    @app.route("/career/<token>/calendar/add", methods=["POST"])
    @career_page(ops_only=True)
    def calendar_add(conn, ctx):
        S.add_event(conn, ctx["season"]["id"], request.form.get("name"), request.form.get("location"),
                    request.form.get("is_sprint"))
        flash("Round added to the end of the calendar.", "success")
        return redirect(url_for("seasons_page", token=ctx["token"]))

    @app.route("/career/<token>/calendar/<int:event_id>/delete", methods=["POST"])
    @career_page(ops_only=True)
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
            conn.execute("DELETE FROM career_members")
            chosen = set()
            for p in players:
                username = auth.normalise(request.form.get(f"user_{p['id']}"))
                if not username:
                    continue
                if not auth.get_user(username):
                    raise ValidationError("Unknown account")
                if username in chosen:
                    raise ValidationError("One login cannot drive two player drivers")
                chosen.add(username)
                conn.execute("INSERT INTO career_members(username, driver_id) VALUES(?,?)", (username, p["id"]))
            for username in request.form.getlist("viewers"):
                username = auth.normalise(username)
                if username and username not in chosen and auth.get_user(username):
                    conn.execute("INSERT INTO career_members(username, driver_id) VALUES(?, NULL)", (username,))
            flash("Player logins saved.", "success")
            return redirect(url_for("members", token=ctx["token"]))
        links = {r["username"]: r["driver_id"] for r in conn.execute("SELECT * FROM career_members")}
        requests = [dict(r) for r in conn.execute("SELECT * FROM join_requests WHERE status = 'Pending' ORDER BY id")]
        users = {u["username"]: u for u in auth.list_users()}
        for r in requests:
            r["user"] = users.get(r["username"])
        return page("members.html", ctx, players=players, users=list(users.values()), links=links, requests=requests,
                    join_open=storage.get_meta(conn, "join_open") == "1")

    def _add_player(conn, ctx, username, driver_name, send_offers):
        user = auth.get_user(username) if username else None
        if username and not user:
            raise ValidationError("Unknown login")
        if user and conn.execute("SELECT 1 FROM career_members WHERE username = ? AND driver_id IS NOT NULL",
                                 (user["username"],)).fetchone():
            raise ValidationError(f"{user['username']} already drives in this league")
        did = S.add_player_driver(conn, driver_name, ctx["current_season_id"])
        if user:
            conn.execute("INSERT OR REPLACE INTO career_members(username, driver_id) VALUES(?,?)", (user["username"], did))
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
        if decision == "approve":
            name = _add_player(conn, ctx, req["username"], request.form.get("driver_name") or req["driver_name"],
                               bool(request.form.get("send_offers")))
            flash(f"{req['username']} joined as {name}.", "success")
        else:
            flash(f"Request from {req['username']} declined.", "success")
        conn.execute("UPDATE join_requests SET status = ?, decided_at = ? WHERE id = ?",
                     ("Approved" if decision == "approve" else "Declined", storage.now_iso(), request_id))
        return redirect(url_for("members", token=ctx["token"]))

    @app.route("/career/<token>/members/settings", methods=["POST"])
    @career_page(master_only=True)
    def members_settings(conn, ctx):
        storage.set_meta(conn, "join_open", "1" if request.form.get("join_open") else "0")
        flash("Join requests are " + ("open." if request.form.get("join_open") else "closed."), "success")
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
        if is_master():
            return True
        if not can_run():
            return False
        try:
            with storage.session(token) as conn:
                return bool(conn.execute("SELECT 1 FROM career_members WHERE username = ?",
                                         (g.user["username"],)).fetchone())
        except CareerNotFound:
            return False

    @app.route("/api/career/<token>/weekend/<int:event_id>", methods=["POST"])
    def api_weekend(token, event_id):
        if not _may_enter_results(token):
            return jsonify(ok=False, error="Only the Race Master or a Race Steward can enter results"), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(ok=False, error="Invalid request"), 400
        try:
            with storage.session(token) as conn:
                before = S.get_event(conn, event_id)
                if not before:
                    return jsonify(ok=False, error="Event not found"), 404
                result = S.save_weekend(conn, event_id, payload)
                opened = None
                newly_complete = result["complete"] and before["status"] != C.EVENT_COMPLETE
                if newly_complete:
                    feed.on_weekend_complete(conn, event_id, f"weekend/{event_id}")
                    opened = market.maybe_open_silly_season(conn, before["season_id"])
                result["market_opened"] = bool(opened)
        except CareerNotFound:
            return jsonify(ok=False, error="Career not found"), 404
        except ValidationError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        if newly_complete:
            try:
                storage.auto_backup(token, f"after-round-{before['round_number']}", force=True)
            except Exception:
                app.logger.exception("automatic backup failed")
            try:
                _email_results(token, event_id)
            except Exception:
                app.logger.exception("results email failed")
        return jsonify(ok=True, **result)

    @app.route("/api/career/<token>/weekend/<int:event_id>/import", methods=["POST"])
    def api_weekend_import(token, event_id):
        if not _may_enter_results(token):
            return jsonify(ok=False, error="Only the Race Master or a Race Steward can enter results"), 403
        kind = request.form.get("kind", "race")
        images = []
        for f in request.files.getlist("screenshots"):
            if f and f.filename:
                images.append((f.read(), f.mimetype))
        try:
            with storage.session(token) as conn:
                if not S.get_event(conn, event_id):
                    return jsonify(ok=False, error="Event not found"), 404
                entrants = [{"id": r["driver_id"], "name": r["driver"]["name"], "team": r["team"]["name"]}
                            for r in S.weekend_rows(conn, event_id)]
        except CareerNotFound:
            return jsonify(ok=False, error="Career not found"), 404
        try:
            result = importer.read_screenshots(images, kind, entrants)
        except importer.ScreenshotError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, kind=kind, **result)

    @app.route("/api/career/<token>/notifications")
    @career_page()
    def api_notifications(conn, ctx):
        items = [{"id": n["id"], "text": n["text"], "unread": n["unread"], "created_at": n["created_at"],
                  "link": f"/career/{ctx['token']}/{n['link']}" if n["link"] else None}
                 for n in ctx["notifications"]]
        return jsonify(ok=True, unread=ctx["unread"], items=items)

    @app.route("/career/<token>/notifications/read", methods=["POST"])
    @career_page()
    def notifications_read(conn, ctx):
        feed.mark_read(conn, g.user["username"])
        return jsonify(ok=True)

    # ---------------------------------------------------------------- saves
    @app.route("/career/<token>/save", methods=["POST"])
    @career_page(ops_only=True)
    def save_now(conn, ctx):
        flash("Career saved.", "success")
        return redirect(request.referrer or url_for("dashboard", token=ctx["token"]))

    @app.route("/career/<token>/rename", methods=["POST"])
    @career_page(master_only=True)
    def rename(conn, ctx):
        name = (request.form.get("name") or "").strip()[:80]
        if not name:
            raise ValidationError("Career name cannot be blank")
        storage.set_meta(conn, "career_name", name)
        flash("Career renamed.", "success")
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
        flash("Saved as a new, independent career.", "success")
        return redirect(url_for("dashboard", token=new))

    @app.route("/career/<token>/delete", methods=["POST"])
    @master_required
    def delete(token):
        try:
            storage.delete_career(token)
        except CareerNotFound:
            abort(404)
        flash("Career deleted.", "success")
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
