"""News shows only stories that mean something, this season's (plus last season's titles and signings), with
Unread and Read tabs."""

from f1tracker import feed, storage
from f1tracker import services as S

from conftest import login


def _post(conn, sid, kind, headline, body="", ref=None):
    feed.post(conn, sid, kind, headline, body, ref=ref)
    return conn.execute("SELECT MAX(id) FROM news").fetchone()[0]


def test_routine_stories_stay_off_the_news_page(app, career, master_client):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        keep = _post(conn, sid, "result", "Player One wins the 2026 Australian GP")
        _post(conn, sid, "paddock", "The paddock is open for R1 Australian GP")
        _post(conn, sid, "paddock", "Lights out at R1 Australian GP!")
        _post(conn, sid, "paddock", "Player One: \"We're here to win\"", 'Asked "How do you feel?" before R1')
        _post(conn, sid, "rumour", "Paddock whispers: talks break down")
        _post(conn, sid, "paddock", "Player One takes the lead in the Williams battle", ref="battle-lead:1:1:2")
        _post(conn, sid, "paddock", "Player One delivers again: 3 team targets in a row")
        five = _post(conn, sid, "paddock", "Player One delivers again: 5 team targets in a row")
        assert [n["id"] for n in feed.relevant(conn)] == [five, keep]


def test_older_seasons_are_hidden_except_titles_and_signings(app, career):
    with storage.session(career) as conn:
        old = S.current_season_id(conn)
        _post(conn, old, "result", "Old race winner")
        champ = _post(conn, old, "season", "Player One is the 2026 World Champion")
        signing = _post(conn, old, "market", "Official: Player One signs with Ferrari")
        new = S.create_next_season(conn, old, 2027)
        fresh = _post(conn, new, "tech", "Winter testing: Ferrari find big gains")
        assert [n["id"] for n in feed.relevant(conn)] == [fresh, signing, champ]


def test_read_and_unread_tabs(app, career, master_client):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        a = _post(conn, sid, "result", "Story A")
        b = _post(conn, sid, "result", "Story B")
    page = master_client.get(f"/career/{career}/news").get_data(as_text=True)
    assert "Story A" in page and "Story B" in page and "Unread (2)" in page
    master_client.post(f"/career/{career}/news/read", data={"csrf_token": "tok", "news_id": a})
    page = master_client.get(f"/career/{career}/news").get_data(as_text=True)
    assert "Story A" not in page and "Story B" in page and "Read (1)" in page
    read = master_client.get(f"/career/{career}/news?tab=read").get_data(as_text=True)
    assert "Story A" in read and "Story B" not in read and "Mark as unread" in read
    master_client.post(f"/career/{career}/news/{a}/unread", data={"csrf_token": "tok"})
    master_client.post(f"/career/{career}/news/read", data={"csrf_token": "tok"})
    page = master_client.get(f"/career/{career}/news").get_data(as_text=True)
    assert "all caught up" in page and "Read (2)" in page
    with storage.session(career) as conn:
        assert feed.read_ids(conn, "devon") == {a, b}
        assert feed.read_ids(conn, "someone") == set()
