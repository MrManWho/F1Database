"""3.2.6: a transfer window closes by itself once its last offer is answered and every player driver is sorted,
and windows left open before this version close the next time the league is opened."""

from conftest import players
from f1tracker import constants as C, market, services as S, storage


def _league(master_client):
    res = master_client.post("/careers/new", data={"name": "Window test", "year": "2026",
                                                   "player_name": ["Devon Racer", "Carl Racer"],
                                                   "player_login": ["devon", ""], "csrf_token": "tok",
                                                   "join_mode": "invite"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _pending(conn, driver):
    return [r["id"] for r in conn.execute("SELECT id FROM offers WHERE driver_id = ? AND status = ?",
                                          (driver, C.OFFER_PENDING))]


def _status(conn, window_id):
    return conn.execute("SELECT status FROM market_windows WHERE id = ?", (window_id,)).fetchone()["status"]


def test_signing_the_last_deal_closes_the_window(career):
    with storage.session(career) as conn:
        wid = market.open_window(conn, S.current_season_id(conn), kind="Silly Season")
        a, b = players(conn)
        market.accept_offer(conn, _pending(conn, a)[0])
        assert _status(conn, wid) == C.WINDOW_OPEN          # the other driver still has offers to answer
        market.accept_offer(conn, _pending(conn, b)[0])
        assert _status(conn, wid) == C.WINDOW_CLOSED
        assert conn.execute("SELECT 1 FROM news WHERE ref = ? AND headline LIKE '%closes%'",
                            (f"window:{wid}",)).fetchone()
        # signings made in the window still stand
        assert conn.execute("SELECT COUNT(*) FROM offers WHERE window_id = ? AND status = ?",
                            (wid, C.OFFER_ACCEPTED)).fetchone()[0] == 2


def test_a_driver_who_can_still_approach_teams_keeps_the_window_open(career):
    with storage.session(career) as conn:
        wid = market.open_window(conn, S.current_season_id(conn), kind="Silly Season")
        a, b = players(conn)
        market.accept_offer(conn, _pending(conn, a)[0])
        for offer_id in _pending(conn, b):
            market.decline_offer(conn, offer_id)
        assert market.approaches_left(conn, wid, b) > 0
        assert _status(conn, wid) == C.WINDOW_OPEN


def test_a_driver_with_nothing_left_to_try_doesnt_hold_it_open(career):
    with storage.session(career) as conn:
        wid = market.open_window(conn, S.current_season_id(conn), kind="Silly Season")
        a, b = players(conn)
        market.accept_offer(conn, _pending(conn, a)[0])
        conn.execute("UPDATE offers SET origin = 'driver' WHERE driver_id = ?", (b,))   # approaches all used
        for offer_id in _pending(conn, b):
            market.decline_offer(conn, offer_id)
        while _pending(conn, b):                                                     # and any lifeline turned down
            market.decline_offer(conn, _pending(conn, b)[0])
        assert market.approaches_left(conn, wid, b) == 0
        assert _status(conn, wid) == C.WINDOW_CLOSED


def test_a_window_left_open_before_3_2_6_closes_when_the_league_is_opened(master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        wid = market.open_window(conn, S.current_season_id(conn), kind="Silly Season")
        for d in players(conn):
            market.accept_offer(conn, _pending(conn, d)[0])
        conn.execute("UPDATE market_windows SET status = ?, closed_at = NULL WHERE id = ?", (C.WINDOW_OPEN, wid))
    assert master_client.get(f"/career/{token}/contracts").status_code == 200
    with storage.session(token) as conn:
        assert _status(conn, wid) == C.WINDOW_CLOSED


def test_the_race_master_can_still_close_a_window_early(master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        wid = market.open_window(conn, S.current_season_id(conn), kind="Silly Season")
    assert master_client.get(f"/career/{token}/market").status_code == 200
    with storage.session(token) as conn:
        assert _status(conn, wid) == C.WINDOW_OPEN           # offers are still waiting, so it stays open
    master_client.post(f"/career/{token}/market/{wid}/close", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert _status(conn, wid) == C.WINDOW_CLOSED
        assert not conn.execute("SELECT 1 FROM offers WHERE window_id = ? AND status = ?",
                                (wid, C.OFFER_PENDING)).fetchone()
