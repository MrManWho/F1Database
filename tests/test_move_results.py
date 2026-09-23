"""Moving results from a wrongly-seated driver onto the right one."""

from conftest import run_event
from f1tracker import services as S, storage
from f1tracker import constants as C


def _setup(master_client):
    res = master_client.post("/careers/new", data={"name": "Move", "year": "2026", "player_name": ["Ana Silva"],
                                                   "player_login": [""], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        amr = conn.execute("SELECT id FROM teams WHERE name = 'Aston Martin'").fetchone()["id"]
        gmap = S.grid_map(conn, sid)
        wrong = gmap[(amr, 2)]
        right = S.add_driver(conn, "Right Teammate", 60.0, sid)
        evs = S.events(conn, sid)
        for ev in evs[:3]:
            run_event(conn, ev, order=[wrong] + [r["driver_id"] for r in S.weekend_rows(conn, ev["id"]) if r["driver_id"] != wrong])
        before = {r["driver_id"]: r["points"] for r in S.driver_standings(conn, sid)}
        teams_before = [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, sid)]
    return token, sid, amr, wrong, right, before, teams_before


def test_results_move_to_the_right_driver(master_client):
    token, sid, amr, wrong, right, before, teams_before = _setup(master_client)
    page = master_client.get(f"/career/{token}/paddock?move_from={wrong}&move_to={right}").get_data(as_text=True)
    assert "points</b> move from" in page and "Type <b>" in page
    with storage.session(token) as conn:
        evs = [e["id"] for e in S.events(conn, sid)[:3]]
        name = S.driver_map(conn)[right]["name"]
    # Wrong confirmation: nothing changes.
    master_client.post(f"/career/{token}/paddock/move-results",
                       data={"from_id": wrong, "to_id": right, "event_id": evs, "confirm_name": "nope", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert {r["driver_id"]: r["points"] for r in S.driver_standings(conn, sid)}[wrong] == before[wrong]
    master_client.post(f"/career/{token}/paddock/move-results",
                       data={"from_id": wrong, "to_id": right, "event_id": evs, "confirm_name": name,
                             "swap_seats": "1", "csrf_token": "tok"})
    with storage.session(token) as conn:
        pts = {r["driver_id"]: r["points"] for r in S.driver_standings(conn, sid)}
        assert pts[right] == before[wrong] >= 3 * C.GP_POINTS[1]   # GP wins plus any Sprint points
        assert pts.get(wrong, 0) == 0
        assert [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, sid)] == teams_before
        assert S.grid_map(conn, sid)[(amr, 2)] == right
        next_ev = S.events(conn, sid)[3]
        assert right in [r["driver_id"] for r in S.weekend_rows(conn, next_ev["id"])]
    assert any("before-moving-results" in b["name"] for b in storage.list_auto_backups(token))
    log = master_client.get(f"/career/{token}/activity").get_data(as_text=True)
    assert f"results in R1, R2, R3" in log


def test_moves_are_refused_when_the_target_already_raced(master_client):
    token, sid, amr, wrong, right, before, _ = _setup(master_client)
    with storage.session(token) as conn:
        other = S.grid_map(conn, sid)[(amr, 1)]    # raced every round too
        name = S.driver_map(conn)[other]["name"]
        evs = [e["id"] for e in S.events(conn, sid)[:3]]
        preview = S.results_transfer_preview(conn, wrong, other, sid)
        assert len(preview["clashes"]) == 3
    master_client.post(f"/career/{token}/paddock/move-results",
                       data={"from_id": wrong, "to_id": other, "event_id": evs, "confirm_name": name, "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert {r["driver_id"]: r["points"] for r in S.driver_standings(conn, sid)}[wrong] == before[wrong]


def test_inactive_and_unseated_drivers_are_listed_with_stats(master_client):
    token, sid, amr, wrong, right, before, _ = _setup(master_client)
    with storage.session(token) as conn:
        new_sid = S.create_next_season(conn, sid, 2027)           # the old season's stats stay in the books
        S._unseat(conn, new_sid, wrong)                            # dropped for 2027
        conn.execute("UPDATE drivers SET active = 0 WHERE id = ?", (wrong,))
        name = S.driver_map(conn)[wrong]["name"]
    page = master_client.get(f"/career/{token}/drivers").get_data(as_text=True)
    other = page.split('id="other-drivers"')[1]
    assert name in other and "Retired" in other and str(before[wrong]) in other
    assert f"/career/{token}/driver/{wrong}" in other
    profile = master_client.get(f"/career/{token}/driver/{wrong}").get_data(as_text=True)
    assert "Retired" in profile and "2026" in profile
