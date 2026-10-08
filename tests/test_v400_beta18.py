"""4.0.0-beta.18: the league list never shows a stale league after a write, and the race time's Clear button clears."""

import os

from conftest import players, pledge_all
from f1tracker import services as S, storage


def _league(master_client):
    res = master_client.post("/careers/new", data={"name": "Club League", "year": "2026",
                                                   "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["", ""], "csrf_token": "tok"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
    pledge_all(token)
    return token


def _name(token):
    return next(c["name"] for c in storage.list_careers() if c["token"] == token)


def test_a_write_in_the_same_timestamp_tick_still_refreshes_the_league_list(career):
    assert _name(career) == "Test Career"
    path = storage.career_path(career)
    before = os.stat(path)
    with storage.session(career) as conn:
        storage.set_meta(conn, "career_name", "Renamed")
    # a coarse-clock filesystem: the write leaves the file's timestamp (and here its size) as it was
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert _name(career) == "Renamed"


def test_reading_without_writing_keeps_the_kept_summary(career):
    _name(career)
    key = str(storage.career_path(career))
    kept = storage._SUMMARIES[key]
    with storage.session(career) as conn:
        conn.execute("SELECT COUNT(*) FROM events").fetchone()
    assert storage._SUMMARIES.get(key) is kept


def test_a_deleted_league_is_forgotten(career):
    _name(career)
    key = str(storage.career_path(career))
    assert key in storage._SUMMARIES
    storage.delete_career(career)
    assert all(c["token"] != career for c in storage.list_careers())
    assert key not in storage._SUMMARIES


def test_clear_removes_the_race_time(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    url = f"/career/{token}/weekend/{ev['id']}/time"
    master_client.post(url, data={"race_at": "2030-03-01T20:00", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["race_at"]
    # the browser sends the filled time input and the Clear button's own field together
    master_client.post(url, data={"race_at": "2030-03-01T20:00", "clear": "1", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert not S.get_event(conn, ev["id"])["race_at"]
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}?stage=prepare").get_data(as_text=True)
    assert 'name="clear" value="1"' not in page   # nothing to clear any more


def test_submit_summary_carries_the_saved_ai_level(db):
    # Review's "What will be submitted" is refilled from this after saving, so the AI level typed in shows there.
    from conftest import run_event
    ev = S.events(db, S.current_season_id(db))[0]
    run_event(db, ev, complete=False)
    sm = S.submission_check(db, ev["id"])["summary"]
    assert sm["ai_difficulty"] is None and sm["ai_untracked"] is False
    run_event(db, ev, difficulty=87, complete=False)
    sm = S.submission_check(db, ev["id"])["summary"]
    assert sm["ai_difficulty"] == 87 and S.get_event(db, ev["id"])["ai_difficulty"] == 87
