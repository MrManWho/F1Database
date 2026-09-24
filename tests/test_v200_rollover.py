"""v2.0: one authoritative seat/contract state; a season rollover can't leave a seat that contradicts its contract."""

import pytest

from conftest import login, players, run_event
from f1tracker import auth, seats, services as S, storage


def _league(master_client):
    """A league with two player drivers (logins ana, ben) at Cadillac, each on a 2026 one-year contract."""
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    res = master_client.post("/careers/new", data={"name": "Roll", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"], "csrf_token": "tok", "join_mode": "invite"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
        seats.record_contract(conn, a, cad, 2026, 1)
        seats.record_contract(conn, b, cad, 2026, 1)
        run_event(conn, S.events(conn, sid)[0])
    return token, a, b, cad


def _rollover(client, token, year=2027, **decisions):
    data = {"year": str(year), "csrf_token": "tok"}
    data.update({f"decision_{k}": v for k, v in decisions.items()})
    return client.post(f"/career/{token}/seasons/new", data=data)


def _season(token):
    with storage.session(token) as conn:
        return S.get_season(conn, S.current_season_id(conn))


def test_expiring_contract_needs_a_decision_and_never_shows_as_contracted(app, master_client):
    """The reported bug: 2026 contract expired, but the 2027 grid still showed the driver seated at Cadillac."""
    token, a, b, cad = _league(master_client)
    page = master_client.get(f"/career/{token}/seasons/rollover?year=2027").get_data(as_text=True)
    assert "Contract with Cadillac ends" in page and 'name="decision_' in page
    _rollover(master_client, token)                     # no decisions: refused, nothing changes
    assert _season(token)["year"] == 2026
    _rollover(master_client, token, **{str(a): "provisional", str(b): "release"})
    assert _season(token)["year"] == 2027
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        sa, sb = seats.state(conn, sid, a), seats.state(conn, sid, b)
        assert sa["kind"] == "provisional" and sa["team"]["id"] == cad and not sa["problem"]
        assert sb["kind"] == "free_agent" and sb["seat"] is None
        assert seats.problems(conn, sid) == []
        # Releasing never deletes history: Ben's 2026 result and contract are still there.
        assert conn.execute("SELECT COUNT(*) FROM results WHERE driver_id = ?", (b,)).fetchone()[0] >= 1
        assert len(seats.contracts(conn, b)) == 1
        # The seat didn't stay empty: an AI driver took it.
        assert S.grid_map(conn, sid)[(cad, 2)] not in (None, a, b)
    garage = master_client.get(f"/career/{token}/garage?driver={a}").get_data(as_text=True)
    grid = master_client.get(f"/career/{token}/grid").get_data(as_text=True)
    profile = master_client.get(f"/career/{token}/driver/{a}").get_data(as_text=True)
    team = master_client.get(f"/career/{token}/team/{cad}").get_data(as_text=True)
    for html in (garage, grid, profile, team):
        assert "Provisional seat · awaiting contract" in html
        assert "Contracted<" not in html.split("Provisional")[0][-200:]


def test_multi_year_contract_continues_without_a_question(app, master_client):
    token, a, b, cad = _league(master_client)
    with storage.session(token) as conn:
        seats.record_contract(conn, a, cad, 2027, 2)      # signed during 2026 for 2027-2028
    review = master_client.get(f"/career/{token}/seasons/rollover").get_data(as_text=True)
    assert "Renewed with Cadillac to 2028" in review
    _rollover(master_client, token, **{str(b): "renew"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        assert seats.state(conn, sid, a)["kind"] == "confirmed"
        assert seats.state(conn, sid, b)["kind"] == "confirmed"   # renewed at the rollover
        assert [c["target_year"] for c in seats.contracts(conn, b)] == [2026, 2027]   # old one kept
    _rollover(master_client, token, year=2028, **{str(b): "provisional"})
    with storage.session(token) as conn:
        assert seats.state(conn, S.current_season_id(conn), a)["kind"] == "confirmed"   # 2027-2028 still covers it


def test_driver_changing_teams_moves_and_is_confirmed(app, master_client):
    token, a, b, cad = _league(master_client)
    with storage.session(token) as conn:
        haas = conn.execute("SELECT id FROM teams WHERE name = 'Haas'").fetchone()["id"]
        from f1tracker import market
        market.open_window(conn, S.current_season_id(conn))
        offer = conn.execute("SELECT id FROM offers WHERE driver_id = ? AND status = 'Pending' LIMIT 1", (a,)).fetchone()
        conn.execute("UPDATE offers SET team_id = ? WHERE id = ?", (haas, offer["id"]))
        market.accept_offer(conn, offer["id"])
    _rollover(master_client, token, **{str(b): "provisional"})
    with storage.session(token) as conn:
        st = seats.state(conn, S.current_season_id(conn), a)
        assert st["kind"] == "confirmed" and st["team"]["name"] == "Haas"


def test_repair_tool_fixes_a_league_already_in_the_bad_state(app, master_client):
    """Leagues that rolled over before v2.0: the grid copied forward, the contract ended."""
    token, a, b, cad = _league(master_client)
    with storage.session(token) as conn:
        old = S.current_season_id(conn)
        new = S.create_next_season(conn, old, 2027)       # the old rollover, with no review
        assert {s["driver"]["id"]: s["kind"] for s in seats.problems(conn, new)} == {a: "expired", b: "expired"}
        assert "Last contract: Cadillac to 2026" in seats.state(conn, new, a)["detail"]
    grid = master_client.get(f"/career/{token}/grid").get_data(as_text=True)
    assert "2 problems to fix" in grid and "Contract expired" in grid
    master_client.post(f"/career/{token}/seats/{a}", data={"action": "renew", "years": "2", "role": "No. 1", "csrf_token": "tok"})
    master_client.post(f"/career/{token}/seats/{b}", data={"action": "temporary", "note": "Stand-in", "csrf_token": "tok"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        assert seats.state(conn, sid, a)["kind"] == "confirmed"
        assert seats.state(conn, sid, a)["contract"]["end_year"] == 2028
        assert seats.state(conn, sid, b)["kind"] == "temporary"
        assert seats.problems(conn, sid) == []
        from f1tracker import community
        log = [e["summary"] for e in community.audit_entries(conn)]
    assert any("recorded a 2-year contract for Ana Silva with Cadillac from 2027" in s for s in log)
    # Only the Race Master can use it.
    auth.create_user("kim", "Kim", "password1")
    with storage.session(token) as conn:
        from f1tracker import roles
        roles.set_member(conn, "kim", "scorekeeper")
    kim = app.test_client()
    login(kim, "kim")
    assert kim.post(f"/career/{token}/seats/{a}", data={"action": "release", "csrf_token": "tok"}).status_code == 403


def test_driver_missing_a_season_returns_as_the_same_driver(app, master_client):
    token, a, b, cad = _league(master_client)
    _rollover(master_client, token, **{str(a): "release", str(b): "renew"})
    with storage.session(token) as conn:
        before = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]
        points_2026 = conn.execute("SELECT COUNT(*) FROM results WHERE driver_id = ?", (a,)).fetchone()[0]
    _rollover(master_client, token, year=2028, **{str(b): "renew"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        assert seats.state(conn, sid, a)["kind"] == "free_agent"
        haas = conn.execute("SELECT id FROM teams WHERE name = 'Haas'").fetchone()["id"]
        S.place_players(conn, sid, {a: (haas, 1)})
        seats.record_contract(conn, a, haas, 2028, 1)
        assert seats.state(conn, sid, a)["kind"] == "confirmed"
        assert conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == before   # no duplicate driver
        assert conn.execute("SELECT COUNT(*) FROM results WHERE driver_id = ?", (a,)).fetchone()[0] >= points_2026


def test_leagues_without_contracts_are_not_flagged(app, master_client):
    auth.create_user("solo", "Solo", "password1")
    res = master_client.post("/careers/new", data={"name": "Simple", "year": "2026", "player_name": ["Solo Racer"],
                                                   "player_login": ["solo"], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        (p,) = players(conn)
        haas = conn.execute("SELECT id FROM teams WHERE name = 'Haas'").fetchone()["id"]
        S.place_players(conn, sid, {p: (haas, 1)})
    _rollover(master_client, token)
    with storage.session(token) as conn:
        st = seats.state(conn, S.current_season_id(conn), p)
        assert st["kind"] == "no_contract" and not st["problem"]


def test_a_failed_rollover_changes_nothing_and_the_backup_restores(app, master_client, monkeypatch):
    token, a, b, cad = _league(master_client)

    def boom(*args, **kwargs):
        raise S.ValidationError("simulated failure part-way through")
    from f1tracker import market
    with monkeypatch.context() as m:
        m.setattr(market, "on_new_season", boom)
        _rollover(master_client, token, **{str(a): "renew", str(b): "renew"})
    with storage.session(token) as conn:
        assert [s["year"] for s in S.list_seasons(conn)] == [2026]    # rolled back as a whole
        assert len(seats.contracts(conn, a)) == 1
    backups = [b_ for b_ in storage.list_auto_backups(token) if "before-2027-season" in b_["name"]]
    assert backups, "a safety backup is taken before the rollover starts"
    _rollover(master_client, token, **{str(a): "renew", str(b): "renew"})
    assert _season(token)["year"] == 2027
    name = [b_ for b_ in storage.list_auto_backups(token) if "before-2027-season" in b_["name"]][0]["name"]
    master_client.post(f"/career/{token}/autobackup/{name}/restore", data={"csrf_token": "tok", "confirm_name": "Roll"})
    with storage.session(token) as conn:
        assert [s["year"] for s in S.list_seasons(conn)] == [2026]


def test_double_submitted_rollover_only_happens_once(app, master_client):
    token, a, b, cad = _league(master_client)
    _rollover(master_client, token, **{str(a): "renew", str(b): "renew"})
    _rollover(master_client, token, **{str(a): "renew", str(b): "renew"})
    with storage.session(token) as conn:
        assert [s["year"] for s in S.list_seasons(conn)] == [2026, 2027]
        assert len(seats.contracts(conn, a)) == 2
