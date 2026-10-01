"""3.2.4: opening Silly Season never swaps a question at an older round, and answers given to swapped-in
questions before this version are taken back (with anything they added to the team relationship)."""

import pytest

from conftest import players, run_event
from f1tracker import market, relations, services as S, storage, teamlife


def _play(conn, rounds):
    """Complete `rounds` rounds a day apart; every player answers both post-race questions each time."""
    sid = S.current_season_id(conn)
    cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    a, b = players(conn)
    S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
    relations.ensure(conn, sid)
    asked = {}
    for i, ev in enumerate(S.events(conn, sid)[:rounds], start=1):
        run_event(conn, ev)
        conn.execute("UPDATE events SET submitted_at = ?, press_required = 1 WHERE id = ?",
                     (f"2099-08-{i:02d} 20:00:00", ev["id"]))
        for d in players(conn):
            qs = teamlife.questions_for(conn, ev["id"], d)
            assert len(qs) == 2
            asked[(ev["id"], d)] = [q["key"] for q in qs]
            for q in qs:
                teamlife.answer(conn, ev["id"], d, q["key"], q["answers"][0]["key"])
            conn.execute("UPDATE press_answers SET created_at = ? WHERE event_id = ? AND driver_id = ?",
                         (f"2099-08-{i:02d} 21:00:00", ev["id"], d))
    return sid, asked


@pytest.mark.gates
def test_opening_silly_season_keeps_every_older_rounds_questions(db):
    sid, asked = _play(db, 12)
    market.open_window(db, sid, kind="Silly Season")
    db.execute("UPDATE market_windows SET opened_at = '2099-08-13 09:00:00'")   # the morning after round 12
    for (event_id, d), keys in asked.items():
        assert [q["key"] for q in teamlife.questions_for(db, event_id, d)] == keys
    for d in players(db):
        pens = teamlife.press_pens(db, sid, d)
        assert [p["open"] for p in pens] == [0]       # only the latest round's pen, already answered


@pytest.mark.gates
def test_the_round_that_opens_silly_season_can_ask_about_the_market(db):
    sid, _asked = _play(db, 3)
    db.execute("INSERT INTO market_windows(season_id, target_year, kind, status, opened_at) "
               "VALUES(?, 2027, 'Silly Season', 'Open', '2099-08-03 20:00:01')", (sid,))
    from f1tracker import press
    evs = S.events(db, sid)
    assert not press.market_open_after(db, S.get_event(db, evs[1]["id"]))   # submitted before the window
    assert press.market_open_after(db, S.get_event(db, evs[2]["id"]))       # its submission opened the window


def test_answers_to_swapped_in_questions_are_taken_back_on_upgrade(career):
    with storage.session(career) as conn:
        sid, asked = _play(conn, 4)
        d = players(conn)[0]
        old = S.events(conn, sid)[0]
        before = relations.assess(conn, sid, d)["bonus"]
        conn.execute("INSERT INTO market_windows(season_id, target_year, kind, status, opened_at) "
                     "VALUES(?, 2027, 'Silly Season', 'Open', '2099-09-30 20:00:00')", (sid,))
        # What 3.2.3 allowed: round 1 asked again about the market, and the answer counted a second time.
        conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                     "VALUES(?, ?, 'future', ?, 3, '2099-09-30 21:00:00')",
                     (old["id"], d, teamlife.QUESTIONS["future"][1][0][0]))
        relations.add_bonus(conn, sid, d)
        assert relations.assess(conn, sid, d)["bonus"] > before
        kept = conn.execute("SELECT COUNT(*) FROM press_answers").fetchone()[0] - 1
        conn.execute("DELETE FROM meta WHERE key = 'press_fix_324'")
    with storage.session(career) as conn:        # the clean-up runs the next time the league opens
        assert conn.execute("SELECT COUNT(*) FROM press_answers").fetchone()[0] == kept
        assert not conn.execute("SELECT 1 FROM press_answers WHERE question = 'future'").fetchone()
        assert relations.assess(conn, sid, d)["bonus"] == before
        note = conn.execute("SELECT text FROM notifications WHERE driver_id = ? AND ref = 'fix-3.2.4-press'",
                            (d,)).fetchone()
        assert note and "R1" in note["text"]


def test_rounds_with_just_their_two_answers_are_never_touched(career):
    """A results correction can change a round's questions afterwards; its two answers still stay."""
    with storage.session(career) as conn:
        sid, _asked = _play(conn, 3)
        conn.execute("INSERT INTO market_windows(season_id, target_year, kind, status, opened_at) "
                     "VALUES(?, 2027, 'Silly Season', 'Open', '2099-08-01 00:00:00')", (sid,))
        conn.execute("UPDATE press_answers SET question = 'drought' WHERE rowid = (SELECT MIN(rowid) FROM press_answers "
                     "WHERE question NOT LIKE 'pre_%')")
        n = conn.execute("SELECT COUNT(*) FROM press_answers").fetchone()[0]
        assert teamlife.remove_reasked_press(conn) == []
        assert conn.execute("SELECT COUNT(*) FROM press_answers").fetchone()[0] == n
