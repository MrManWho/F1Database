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

from . import auth, market, services as S, storage
from . import constants as C
from .auth import AuthError
from .services import ValidationError
from .storage import CareerNotFound


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


PUBLIC_ENDPOINTS = {"login", "setup", "static"}


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


def career_page(master_only=False):
    """Open the career, enforce access, and turn ValidationErrors into flashed messages."""
    def deco(fn):
        @wraps(fn)
        def wrapper(token, *args, **kwargs):
            try:
                with storage.session(token) as conn:
                    linked = conn.execute("SELECT 1 FROM career_members WHERE username = ?",
                                          (g.user["username"],)).fetchone()
                    if not is_master() and not linked:
                        abort(403)
                    if master_only and not is_master():
                        abort(403)
                    season_id = _selected_season(conn, token)
                    g.ctx = {
                        "token": token,
                        "career_name": storage.get_meta(conn, "career_name", "Career"),
                        "season": S.get_season(conn, season_id),
                        "current_season_id": S.current_season_id(conn),
                        "seasons": S.list_seasons(conn),
                        "is_master": is_master(),
                        "my_driver": _member_driver(conn),
                        "open_windows": conn.execute("SELECT COUNT(*) FROM market_windows WHERE status = ?",
                                                     (C.WINDOW_OPEN,)).fetchone()[0],
                    }
                    mine = g.ctx["my_driver"]
                    g.ctx["pending_offers"] = conn.execute(
                        "SELECT COUNT(*) FROM offers WHERE status = ?" + (" AND driver_id = ?" if mine and not is_master() else ""),
                        (C.OFFER_PENDING, mine["id"]) if mine and not is_master() else (C.OFFER_PENDING,)).fetchone()[0]
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
            try:
                username = auth.create_user(request.form.get("username"), request.form.get("display_name"),
                                            request.form.get("password"), is_master=True)
            except AuthError as exc:
                flash(str(exc), "error")
                return redirect(url_for("setup"))
            session.clear()
            session["user"] = username
            flash("Race Master account created. Add logins for the other player in Accounts.", "success")
            return redirect(url_for("home"))
        return render_template("login.html", mode="setup")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = auth.verify(request.form.get("username"), request.form.get("password"))
            if not user:
                flash("Wrong username or password.", "error")
                return redirect(url_for("login", next=request.args.get("next", "")))
            session.clear()
            session["user"] = user["username"]
            target = request.args.get("next") or ""
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("home")
            return redirect(target)
        return render_template("login.html", mode="login")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/accounts")
    def accounts_page():
        return render_template("accounts.html", users=auth.list_users() if is_master() else [])

    @app.route("/accounts/new", methods=["POST"])
    @master_required
    def account_new():
        try:
            auth.create_user(request.form.get("username"), request.form.get("display_name"),
                             request.form.get("password"), is_master=bool(request.form.get("is_master")))
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
            auth.set_master(username, request.form.get("is_master") == "1")
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
        careers = storage.list_careers()
        if not is_master():
            careers = [c for c in careers if g.user["username"] in c["members"]]
        return render_template("home.html", careers=careers, users=auth.list_users() if is_master() else [],
                               default_year=2026)

    @app.route("/careers/new", methods=["POST"])
    @master_required
    def career_new():
        name = (request.form.get("name") or "").strip()[:80] or "F1 Career"
        token = storage.new_token()
        try:
            with storage.session(token, create=True) as conn:
                S.seed_career(conn, token, name, request.form.get("year") or 2026,
                              [request.form.get("player1"), request.form.get("player2")])
                players = S.player_drivers(conn)
                for field, driver in zip(("account1", "account2"), players):
                    username = auth.normalise(request.form.get(field))
                    if username and auth.get_user(username):
                        conn.execute("INSERT OR REPLACE INTO career_members(username, driver_id) VALUES(?,?)",
                                     (username, driver["id"]))
                if request.form.get("rookie_market"):
                    market.open_window(conn, S.current_season_id(conn), kind="Rookie Draft")
        except (ValidationError, ValueError) as exc:
            try:
                storage.delete_career(token)
            except CareerNotFound:
                pass
            flash(str(exc), "error")
            return redirect(url_for("home"))
        flash("Career created." + (" Rookie offers are waiting in each player's garage."
                                   if request.form.get("rookie_market") else ""), "success")
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
                    windows=[w for w in market.windows(conn) if w["status"] == C.WINDOW_OPEN])

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
                    teams=S.teams(conn))

    @app.route("/career/<token>/driver/<int:driver_id>")
    @career_page()
    def driver_profile(conn, ctx, driver_id):
        driver = S.driver_map(conn).get(driver_id)
        if not driver:
            abort(404)
        timeline = S.driver_timeline(conn, driver_id)
        return page("driver_profile.html", ctx, driver=driver, timeline=timeline,
                    totals=S.career_totals(timeline), contract=market.current_contract(conn, driver_id))

    @app.route("/career/<token>/teams")
    @career_page()
    def teams_page(conn, ctx):
        table = S.constructor_standings(conn, ctx["season"]["id"])
        return page("teams.html", ctx, table=table, leader=max([t["points"] for t in table] + [1]))

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
        new_id = S.create_next_season(conn, latest["id"], request.form.get("year"))
        market.on_new_season(conn, new_id)
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
        rival = next((p for p in players if p["id"] != driver["id"]), None)
        rival_row = next((r for r in standings if rival and r["driver_id"] == rival["id"]), None)
        recent = conn.execute("""SELECT r.*, e.name AS event_name, e.round_number, e.is_sprint FROM results r
                                 JOIN events e ON e.id = r.event_id WHERE r.driver_id = ? AND e.season_id = ?
                                 AND e.status != ? ORDER BY e.round_number DESC LIMIT 6""",
                              (driver["id"], sid, C.EVENT_NOT_RUN)).fetchall()
        own = ctx["my_driver"] and ctx["my_driver"]["id"] == driver["id"]
        return page("garage.html", ctx, driver=driver, me=me, interest=interest, row=row,
                    team=S.team_map(conn).get(seat[0]) if seat else None, teammate=teammate,
                    rival=rival, rival_row=rival_row, recent=recent, players=players,
                    offers=market.offers(conn, driver_id=driver["id"]), can_respond=own or ctx["is_master"],
                    contract=market.current_contract(conn, driver["id"]), own=own,
                    rookie=market.career_starts(conn, driver["id"]) == 0)

    @app.route("/career/<token>/market")
    @career_page()
    def market_page(conn, ctx):
        if not ctx["is_master"]:
            return redirect(url_for("garage", token=ctx["token"]))
        return page("market.html", ctx, windows=market.windows(conn), offers=market.offers(conn),
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
        return page("members.html", ctx, players=players, users=auth.list_users(), links=links)

    # ---------------------------------------------------------------- race API
    @app.route("/api/career/<token>/weekend/<int:event_id>", methods=["POST"])
    def api_weekend(token, event_id):
        if not is_master():
            return jsonify(ok=False, error="Only the Race Master can enter results"), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(ok=False, error="Invalid request"), 400
        try:
            with storage.session(token) as conn:
                if not S.get_event(conn, event_id):
                    return jsonify(ok=False, error="Event not found"), 404
                result = S.save_weekend(conn, event_id, payload)
                opened = None
                if result["complete"]:
                    event = S.get_event(conn, event_id)
                    opened = market.maybe_open_silly_season(conn, event["season_id"])
                result["market_opened"] = bool(opened)
        except CareerNotFound:
            return jsonify(ok=False, error="Career not found"), 404
        except ValidationError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, **result)

    # ---------------------------------------------------------------- saves
    @app.route("/career/<token>/save", methods=["POST"])
    @career_page(master_only=True)
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
