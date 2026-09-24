import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from f1tracker import auth, market, services as S, storage  # noqa: E402
from f1tracker.app import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("F1_TRACKER_DATA_DIR", str(tmp_path))
    return tmp_path


def pytest_configure(config):
    config.addinivalue_line("markers", "gates: run with round gates at their real default (on)")
    config.addinivalue_line("markers", "whatsnew: show the real What's New popup (hidden in other tests)")
    config.addinivalue_line("markers", "weekends: run with race weekends at their real default (on)")


@pytest.fixture(autouse=True)
def hide_whats_new(request, monkeypatch):
    """Every account now sees the current version's What's New once (v2.1.3); tests about something else skip it."""
    if request.node.get_closest_marker("whatsnew"):
        return
    from f1tracker import changelog
    monkeypatch.setattr(changelog, "entry", lambda base, version: None)


@pytest.fixture(autouse=True)
def round_gates_default(request, monkeypatch):
    """Tests written before round gates (v1.20) run with gates off unless marked @pytest.mark.gates."""
    from f1tracker import teamlife
    if not request.node.get_closest_marker("gates"):
        monkeypatch.setitem(teamlife.DEFAULTS, "round_gates", "0")


@pytest.fixture(autouse=True)
def race_weekends_default(request, monkeypatch):
    """Tests written before race weekends (v2.3) enter results straight away; mark @pytest.mark.weekends for the real default."""
    from f1tracker import weekend
    if not request.node.get_closest_marker("weekends"):
        monkeypatch.setitem(weekend.DEFAULTS, "race_weekends", "0")


@pytest.fixture
def career():
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Test Career", 2026, ["David Conley", "Carson Hayes"])
    return token


@pytest.fixture
def db(career):
    with storage.session(career) as conn:
        yield conn


def driver_id(conn, name):
    return conn.execute("SELECT id FROM drivers WHERE name = ?", (name,)).fetchone()["id"]


def players(conn):
    return [p["id"] for p in S.player_drivers(conn)]


def run_event(conn, event, order=None, overrides=None, sprint_order=None, sprint_overrides=None,
              quali=None, difficulty=None, fl=None, dotd=None, complete=True):
    """Enter a full weekend. order: driver ids in finishing order (defaults to grid order)."""
    rows = S.weekend_rows(conn, event["id"])
    ids = [r["driver_id"] for r in rows]
    order = order or ids
    order = order + [d for d in ids if d not in order]
    quali = quali or order
    quali = quali + [d for d in ids if d not in quali]
    sprint_order = sprint_order or order
    overrides, sprint_overrides = overrides or {}, sprint_overrides or {}
    results = []
    for did in ids:
        results.append({
            "driver_id": did,
            "qualifying_position": quali.index(did) + 1,
            "race_position": order.index(did) + 1,
            "status_override": overrides.get(did, "Auto"),
            "sprint_position": (sprint_order.index(did) + 1) if event["is_sprint"] else None,
            "sprint_status_override": sprint_overrides.get(did, "Auto"),
            "fastest_lap": did == fl,
            "driver_of_day": did == dotd,
            "notes": "",
        })
    return S.save_weekend(conn, event["id"], {"results": results, "mark_complete": complete,
                                             "ai_difficulty": difficulty})


def pledge_all(token):
    """Give every seated player driver a (Solid) pledge, as if they'd signed after v1.15."""
    from f1tracker import relations
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        relations.ensure(conn, sid)
        for row in conn.execute("SELECT driver_id FROM team_relations WHERE season_id = ?", (sid,)).fetchall():
            relations.set_pledge(conn, sid, row["driver_id"], 1)


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SECRET_KEY": "test-secret"})


def login(client, username, password="password1"):
    client.post("/login", data={"username": username, "password": password})
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    return "tok"


@pytest.fixture
def master_client(app):
    auth.create_user("david", "David", "password1", is_master=True)
    client = app.test_client()
    login(client, "david")
    return client


@pytest.fixture
def rng():
    return random.Random(7)


__all__ = ["driver_id", "players", "run_event", "login", "market", "pledge_all"]


@pytest.fixture
def live_server(app):
    """The app on a real local port, for browser tests (test files may define their own)."""
    import threading
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def open_browser():
    """(playwright, browser), or skip the test when no browser is available."""
    import os
    sync = pytest.importorskip("playwright.sync_api")
    path = "/opt/pw-browsers/chromium"
    pw = sync.sync_playwright().start()
    try:
        browser = pw.chromium.launch(executable_path=path) if os.path.exists(path) else pw.chromium.launch()
    except Exception as exc:  # pragma: no cover
        pw.stop()
        pytest.skip(f"no browser: {exc}")
    return pw, browser
