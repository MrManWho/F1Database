"""4.0 Phase 0: golden calculation fixtures, the read-only Engine 2 scan, the inventories and the seed command."""

import json
from pathlib import Path

import pytest

from conftest import login
from f1tracker import auth, golden, phase0, services as S, storage, testsite

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"


# --------------------------------------------------------------------------- golden fixtures

@pytest.mark.parametrize("engine", [3, 2])
def test_golden_season_matches_exactly(engine):
    """The same inputs give exactly the recorded numbers. A difference here is a formula change: it needs approval,
    and only then `python -m f1tracker.golden write tests/golden`."""
    saved = (GOLDEN / f"engine{engine}_season.json").read_text()
    assert golden.dumps(golden.build(engine)) == saved


def test_golden_fixture_covers_the_career_numbers():
    data = json.loads((GOLDEN / "engine3_season.json").read_text())
    assert data["engine"] == 3 and len(data["rounds"]) == golden.ROUNDS
    last = data["rounds"][-1]
    assert {"Player One", "Player Two"} <= set(last["driver_value"])
    assert all(len(v) == golden.ROUNDS for v in data["timeline"].values())
    for table in ("ai_recs", "round_ranks", "team_relations", "weekend_targets", "team_goals", "season_driver_state"):
        assert data["tables"][table], table
    assert json.loads((GOLDEN / "engine2_season.json").read_text())["engine"] == 2


# --------------------------------------------------------------------------- Engine 2 scan

def _league(engine, monkeypatch, name):
    from f1tracker import constants
    monkeypatch.setattr(constants, "NEW_LEAGUE_ENGINE", engine)
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, name, 2026, ["Player One"])
    return token


def test_scan_finds_active_engine2_seasons_and_changes_nothing(monkeypatch):
    old = _league(2, monkeypatch, "Old League")
    with storage.session(old) as conn:   # a league from before 2.5 has never answered the Calculation Update
        conn.execute("DELETE FROM meta WHERE key = 'calc_choice'")
    new = _league(3, monkeypatch, "New League")
    files = lambda: {p.name: p.read_bytes() for p in storage.careers_dir().glob(f"*{storage.CAREER_EXT}")}  # noqa: E731
    before = files()
    result = phase0.scan()
    assert files() == before   # read-only (SQLite's own -wal/-shm helper files aside)
    by_id = {lg["id"]: lg for lg in result["leagues"]}
    assert by_id[old]["seasons"][0]["engine"] == 2 and by_id[old]["seasons"][0]["active"]
    assert by_id[new]["seasons"][0]["engine"] == 3
    assert [lg["id"] for lg, _s in result["v2_active"]] == [old]
    assert [lg["id"] for lg in result["pending_choice"]] == [old]
    assert "keep its calculation code" in result["verdict"]
    assert "Old League" in phase0.scan_text(result)


def test_scan_with_no_engine2_says_it_can_be_retired(monkeypatch):
    _league(3, monkeypatch, "New League")
    assert "can be retired" in phase0.scan()["verdict"]


def test_scan_reports_an_unreadable_file():
    (storage.careers_dir() / f"broken{storage.CAREER_EXT}").write_bytes(b"not a database")
    [lg] = phase0.scan()["leagues"]
    assert lg["error"]


def test_scan_page_is_site_owner_only(app, master_client, monkeypatch):
    _league(2, monkeypatch, "Old League")
    page = master_client.get("/settings/engine-scan").get_data(as_text=True)
    assert "Old League" in page and "Active" in page
    auth.create_user("kim", "Kim", "password1")
    other = app.test_client()
    login(other, "kim")
    assert other.get("/settings/engine-scan").status_code == 403


# --------------------------------------------------------------------------- inventories

def test_route_inventory_lists_every_route(app):
    text = (ROOT / "docs" / "4.0" / "ROUTES.md").read_text()
    missing = [r["endpoint"] for r in phase0.routes(app) if f"| {r['endpoint']} |" not in text]
    assert not missing, "run `python -m f1tracker.phase0 inventory docs/4.0`: " + ", ".join(missing)


def test_every_route_declares_who_may_use_it(app):
    """4.0 Phase 1: no route relies on a check hidden inside the view any more."""
    undeclared = sorted(r["endpoint"] for r in phase0.routes(app) if r["who"].startswith("signed in (checks")
                        or r["who"] == "signed in")
    assert undeclared == []


def test_table_inventory_follows_the_migration_decisions():
    t = phase0.tables()
    for name in ("password_resets", "pending_signups", "login_failures"):
        assert name in t["site"] and phase0.migration_rule(name).startswith("not migrated")
    for name in ("outbox", "rate_hits", "user_sessions", "login_failure_names"):
        assert phase0.migration_rule(name).startswith("not migrated")
    assert phase0.migration_rule("member_notify") == "migrated exactly"      # notification preferences migrate
    assert phase0.migration_rule("notifications").startswith("optional")
    assert "results" in t["league"] and "users" in t["site"]
    text = (ROOT / "docs" / "4.0" / "TABLES.md").read_text()
    assert all(f"| {n} |" in text for n in list(t["site"]) + list(t["league"]))


# --------------------------------------------------------------------------- corrected specification

def test_specification_carries_the_corrected_engine3_rules():
    spec = (ROOT / "docs" / "4.0" / "SPECIFICATION.md").read_text()
    assert "±1 AI" not in spec and "cautiously toward the struggling player" not in spec
    assert "**halved**" in spec and "**3** AI levels" in spec and "up to **8**" in spec
    assert "upcoming round's pre-race press" in spec
    from f1tracker import constants as C
    assert C.AI_STEP_LIMITS == ((1, 3), (3, 4), (10 ** 6, 6)) and C.AI_EXTREME_STEP == 5 and C.AI_PERSISTENT_STEP == 8
    assert C.DIFF_MIXED == 0.5 and C.V3_PRESS_POSITIVE_CAP == 2.0


# --------------------------------------------------------------------------- seed command

def test_seed_only_on_the_test_site(monkeypatch):
    monkeypatch.delenv("F1_TRACKER_TEST_SITE", raising=False)
    with pytest.raises(Exception):
        testsite.seed()
    assert not list(storage.careers_dir().glob(f"*{storage.CAREER_EXT}"))
    monkeypatch.setenv("F1_TRACKER_TEST_SITE", "1")
    token = testsite.seed()
    with storage.session(token) as conn:
        assert storage.get_meta(conn, "career_name") == "Test League (fictional)"
        done = conn.execute("SELECT COUNT(*) FROM events WHERE status = 'Complete'").fetchone()[0]
    assert done == golden.ROUNDS
