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


__all__ = ["driver_id", "players", "run_event", "login", "market"]
