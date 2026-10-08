"""Re-filing run rounds under the drivers now in each car, and swapping two drivers' results in a round."""

from conftest import driver_id, run_event
from f1tracker import services as S, storage


def _team(conn, name):
    return conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()["id"]


def _by_driver(conn, ev):
    return {r["driver_id"]: (r["team_id"], r["race_position"]) for r in
            conn.execute("SELECT * FROM results WHERE event_id = ?", (ev["id"],))}


def test_results_follow_the_fixed_grid(career, master_client):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        wil = _team(conn, "Williams")
        player = S.player_drivers(conn)[0]["id"]
        sainz, albon = driver_id(conn, "Carlos Sainz"), driver_id(conn, "Alexander Albon")
        gmap = S.grid_map(conn, sid)
        S.place_players(conn, sid, {player: next(k for k, v in gmap.items() if v == sainz)})
        # the player took Sainz's seat; Sainz filled whatever seat was left
        evs = S.events(conn, sid)[:2]
        for ev in evs:
            run_event(conn, ev)
        before = [_by_driver(conn, ev) for ev in evs]
        teams_before = [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, sid)]
        gmap = S.grid_map(conn, sid)
        # Now the Race Master fixes the grid: the player should have replaced Albon, so Sainz sits next to them
        # and Albon is out; the driver Sainz pushed out of a seat gets it back.
        albon_seat = next(k for k, v in gmap.items() if v == albon)
        sainz_seat = next((k for k, v in gmap.items() if v == sainz), None)
        gmap[albon_seat] = sainz
        if sainz_seat:
            gmap[sainz_seat] = None
        out = [d["id"] for d in S.drivers(conn, active_only=True) if d["id"] not in gmap.values() and not d["is_player"]]
        if sainz_seat:
            gmap[sainz_seat] = out[0] if out[0] != albon else out[1]
        S.write_grid(conn, sid, gmap)
        preview = S.align_results_preview(conn, sid)
        assert [r["event"]["id"] for r in preview["rounds"]] == [e["id"] for e in evs]
        assert albon in [d["id"] for d in preview["dropped"]]
    page = master_client.get(f"/career/{career}/paddock?align=1").get_data(as_text=True)
    assert "Match results to the grid" in page and "Type <b>MATCH</b>" in page
    master_client.post(f"/career/{career}/paddock/align-results", data={"confirm": "match", "csrf_token": "tok"})
    with storage.session(career) as conn:
        seats = S.driver_seats(conn, sid)
        for ev, old in zip(evs, before):
            now = _by_driver(conn, ev)
            assert albon not in now
            assert now[player] == old[player]
            assert now[sainz] == old[albon]              # Sainz takes the Williams car's result
            for did, (team, _pos) in now.items():
                assert seats[did][0] == team             # everyone's results are in the car they sit in
        assert [(t["team"]["id"], t["points"]) for t in S.constructor_standings(conn, sid)] == teams_before
        assert S.align_results_preview(conn, sid)["rounds"] == []


def test_two_drivers_can_swap_a_round(career):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        ev = S.events(conn, sid)[0]
        run_event(conn, ev)
        a, b = driver_id(conn, "Carlos Sainz"), driver_id(conn, "Lance Stroll")
        old = _by_driver(conn, ev)
        preview = S.results_transfer_preview(conn, a, b, sid)
        assert preview["rounds"][0]["clash"] and preview["rounds"][0]["other"]["result"]
        done = S.transfer_results(conn, a, b, sid, [], swap_event_ids=[ev["id"]])
        assert done["swapped"] == [1]
        now = _by_driver(conn, ev)
        assert now[a] == old[b] and now[b] == old[a]
