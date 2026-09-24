"""v2.0 statistics: numbers come from submitted rounds only, filters work, and nothing stored changes."""

from conftest import players, run_event
from f1tracker import services as S, stats, storage


def _league(master_client, name="Stats League"):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite", "player_name": ["Ana Silva"],
                                                   "player_login": [""]})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def test_breakdowns_count_only_submitted_rounds(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        p = players(conn)[0]
        S.place_players(conn, sid, {p: (1, 1)})
        evs = S.events(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        rest = [d for d in ids if d != p]
        run_event(conn, evs[0], order=[p] + rest, quali=rest[:4] + [p])          # P5 -> P1
        run_event(conn, evs[1], order=rest[:2] + [p] + rest[2:], overrides={rest[0]: "DNF"})
        run_event(conn, evs[2], order=[p] + rest, complete=False)                 # draft: ignored
        before = [dict(r) for r in conn.execute("SELECT * FROM results ORDER BY id")]
        rows = {s["driver"]["id"]: s for s in stats.season(conn, sid)}
        me = rows[p]
        assert me["win"] == 1 and me["podium"] == 1 and me["finished"] == 2
        assert me["gained"][0] == 4 and me["avg_quali"] is not None
        assert rows[rest[0]]["dnf"] == 1 and rows[rest[0]]["finish_rate"] == 50
        assert [s["driver"]["id"] for s in stats.season(conn, sid, players_only=True)] == [p]
        pair = next(x for x in stats.teammates(conn, sid) if p in (x["a"]["id"], x["b"]["id"]))
        assert sum(pair["race"]) == 2
        assert [dict(r) for r in conn.execute("SELECT * FROM results ORDER BY id")] == before


def test_stats_page_renders_filters_and_empty_state(app, master_client):
    token = _league(master_client)
    page = master_client.get(f"/career/{token}/stats").get_data(as_text=True)
    assert "No statistics yet" in page
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        S.place_players(conn, sid, {players(conn)[0]: (1, 1)})
        for e in S.events(conn, sid)[:3]:
            run_event(conn, e)
    page = master_client.get(f"/career/{token}/stats").get_data(as_text=True)
    for heading in ("Points progression", "Finish distribution", "Qualifying vs race", "Teammate head-to-heads",
                    "Reliability"):
        assert heading in page
    players_page = master_client.get(f"/career/{token}/stats?who=players").get_data(as_text=True)
    assert "Ana Silva" in players_page and players_page.count('class="dist-row"') == 1


def test_season_over_season_lists_players_across_seasons(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        p = players(conn)[0]
        S.place_players(conn, sid, {p: (1, 1)})
        run_event(conn, S.events(conn, sid)[0])
        new = S.create_next_season(conn, sid, 2027)
        S.place_players(conn, new, {p: (1, 1)})
        run_event(conn, S.events(conn, new)[0])
        years, rows = stats.season_over_season(conn)
    assert years == [2026, 2027] and rows[0]["driver"]["id"] == p and set(rows[0]["seasons"]) == {2026, 2027}
