"""4.0: legacy-season tracking and the one-time upgrade notice (tracking.py).

A "3.x league" here is a league built and played with this code, then put back the way a 3.2.x file looks (no 4.0
tables, schema 22) before it's opened again, which is exactly what happens when 4.0 first opens a live league.
"""

import json

import pytest

from f1tracker import ai3, auth, impacts, roles, storage, tracking, weather
from f1tracker import constants as C
from f1tracker import services as S

from conftest import login, run_event

pytestmark = [pytest.mark.engine3, pytest.mark.latest, pytest.mark.trackai, pytest.mark.pacerequired]


def _seat(conn):
    sid = S.current_season_id(conn)
    teams = {t["name"]: t["id"] for t in conn.execute("SELECT id, name FROM teams")}
    ids = [p["id"] for p in S.player_drivers(conn)]
    S.place_players(conn, sid, {d: (teams[name], 1) for d, name in zip(ids, ("Williams", "Haas"))})


def _play(conn, upto, weather_from=None, press_from=None):
    sid = S.current_season_id(conn)
    if not conn.execute("SELECT 1 FROM season_grid g JOIN drivers d ON d.id = g.driver_id WHERE d.is_player = 1 "
                        "AND g.season_id = ?", (sid,)).fetchone():
        _seat(conn)
    for e in S.events(conn, sid)[:upto]:
        run_event(conn, e, difficulty=80)
        if weather_from and e["round_number"] >= weather_from:
            weather.save(conn, e, {"weather_race": "dry", "weather_quali": "dry"}, "devon")
        if press_from and e["round_number"] >= press_from:
            for p in S.player_drivers(conn):
                conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                             "VALUES(?,?,?,?,?,?)", (e["id"], p["id"], "q_test", "a", 0, "2026-09-25"))


def _as_3x(token):
    """Put the league file back the way a 3.2.x site leaves it: no 4.0 tables, schema 22."""
    path = storage.career_path(token)
    import sqlite3
    conn = sqlite3.connect(str(path))
    for table in ("audit_events", "ai_track_recs", "tracking_migrations", "season_tracking", "tracking_notice_acks"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("UPDATE meta SET value = '22' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()


def _members(conn, *names):
    for n in names:
        if not auth.get_user(n):
            auth.create_user(n, n.title(), "password1")
        roles.set_member(conn, n, "member")


def _outcomes(conn):
    """Everything an upgrade must leave alone: standings, career numbers, contracts, offers, the grids."""
    sid = S.current_season_id(conn)
    return {
        "standings": [(r["driver_id"], r["points"], r["position"]) for r in S.driver_standings(conn, sid)],
        "snapshot": impacts.snapshot(conn, sid),
        "contracts": [tuple(r) for r in conn.execute("SELECT * FROM contracts ORDER BY id")],
        "offers": [tuple(r)[:12] for r in conn.execute("SELECT * FROM offers ORDER BY id")],
        "grid": [tuple(r) for r in conn.execute("SELECT * FROM season_grid ORDER BY season_id, team_id, seat_no")],
        "relations": [tuple(r) for r in conn.execute("SELECT season_id, driver_id, team_id, growth, score, status, "
                                                     "warning_level, outcome FROM team_relations ORDER BY 1, 2")],
        "results": [tuple(r) for r in conn.execute("SELECT * FROM results ORDER BY id")],
    }


@pytest.fixture
def legacy(career):
    """A league played to round 5 on "3.x", weather recorded from round 3 and press from round 1, two members."""
    with storage.session(career) as conn:
        _members(conn, "carson", "kim")
        _play(conn, 5, weather_from=3, press_from=1)
        before = _outcomes(conn)
    _as_3x(career)
    with storage.session(career) as conn:
        pass                                    # 4.0 opens it: the upgrade happens here
    return career, before


def test_upgrade_is_recorded_once_with_the_real_start_round(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        mig = tracking.migration(conn)
        assert mig and mig["from_schema"] == 22 and mig["start_year"] == 2026 and mig["start_round"] == 6
        assert sorted(mig["audience"]) == ["carson", "kim"]
        rows = tracking.all_rows(conn)
        count = len(rows)
    for _ in range(3):                         # opening again never repeats it
        with storage.session(token) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tracking_migrations").fetchone()[0] == 1
            assert len(tracking.all_rows(conn)) == count


def test_new_tracking_starts_at_the_upgrade_round_midseason(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = {e["round_number"]: e for e in S.events(conn, sid)}
        assert not tracking.round_tracked(conn, evs[5], "race_times")
        assert tracking.round_tracked(conn, evs[6], "race_times")
        assert not tracking.round_tracked(conn, evs[1], "incident_sessions")
        # Press was recorded from round 1: tracked the whole season. Weather first recorded at round 3: to confirm.
        assert tracking.round_tracked(conn, evs[1], "press")
        assert not tracking.round_tracked(conn, evs[2], "weather") and tracking.round_tracked(conn, evs[3], "weather")
        assert [r["feature"] for r in tracking.review_items(conn)] == ["weather"]


def test_legacy_rounds_never_ask_for_race_times_but_new_rounds_do(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = {e["round_number"]: e for e in S.events(conn, sid)}
        assert ai3.missing_pace(conn, evs[5]) == []
        # A correction to a legacy round (reopened and saved again) isn't blocked by times it never had.
        run_event(conn, evs[5], difficulty=80, complete=False)
        check = S.submission_check(conn, evs[5]["id"])
        assert not any("Race times" in b for b in check["blocking"])
        run_event(conn, evs[6], difficulty=80, complete=False)
        ev6 = S.get_event(conn, evs[6]["id"])
        assert ai3.missing_pace(conn, ev6), "4.0 rounds still need race times"


def test_missing_entries_stay_distinct_from_untracked(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = {e["round_number"]: e for e in S.events(conn, sid)}
        weather.clear(conn, evs[4]["id"])       # a genuine gap after tracking began
        assert tracking.empty_text(conn, evs[4], "weather") == "Not recorded"
        assert tracking.empty_text(conn, evs[1], "weather") == "Not tracked under this season's rules"
        assert tracking.empty_text(conn, evs[9], "weather") == "Not recorded"     # after the upgrade


def test_untracked_rounds_are_left_out_of_denominators(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        eligible = [e["round_number"] for e in tracking.eligible_rounds(conn, sid, "weather")]
        assert eligible == [3, 4, 5]
        assert tracking.coverage(conn, sid, "weather", 3) == ("Based on 3 eligible rounds · Tracked since Round 3 of "
                                                              "the 2026 season")
        assert tracking.eligible_rounds(conn, sid, "race_times") == []


def test_no_career_outcome_changes(legacy):
    token, before = legacy
    with storage.session(token) as conn:
        assert _outcomes(conn) == before
        assert conn.execute("SELECT COUNT(*) FROM calc_migrations").fetchone()[0] == 0
        assert not conn.execute("SELECT COUNT(*) FROM impact_notices").fetchone()[0] if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'impact_notices'").fetchone() else True
        notice = tracking.notice_for(conn, "carson")
        assert notice["calc"] == "No results, standings or career outcomes were recalculated."


def test_engine2_league_moves_to_latest_from_next_round_without_changing_anything(career, monkeypatch):
    with storage.session(career) as conn:
        _members(conn, "carson")
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'calc_engine'")
        conn.execute("DELETE FROM season_calc")
        _play(conn, 4)
        before = _outcomes(conn)
    _as_3x(career)
    with storage.session(career) as conn:
        assert _outcomes(conn)["standings"] == before["standings"]
        assert _outcomes(conn)["contracts"] == before["contracts"] and _outcomes(conn)["grid"] == before["grid"]
        line = tracking.notice_for(conn, "carson")["calc"]
        assert "latest calculations from round 5" in line and "unchanged" in line


def test_explicit_recalculation_is_explained_separately(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        mig = tracking.migration(conn)
        conn.execute("""INSERT INTO calc_migrations(season_id, option, old_engine, new_engine, created_at)
                        VALUES(?,?,?,?,?)""", (S.current_season_id(conn), "full", 3, 3, mig["migrated_at"]))
        assert "chose to recalculate" in tracking.notice_for(conn, "kim")["calc"]


def test_whole_season_played_starts_tracking_next_season(career):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        _play(conn, len(S.events(conn, sid)))
    _as_3x(career)
    with storage.session(career) as conn:
        mig = tracking.migration(conn)
        assert (mig["start_year"], mig["start_round"]) == (2027, 1)
        summary = tracking.season_summary(conn, S.get_season(conn, sid))
        assert summary["start"] == "the 2027 season"
        assert not tracking.tracked(conn, sid, "race_times")


def test_new_40_league_gets_no_migration_or_notice(career):
    with storage.session(career) as conn:
        _members(conn, "carson")
        _play(conn, 2)
        assert tracking.migration(conn) is None
        assert tracking.notice_for(conn, "carson") is None and tracking.notice_for(conn, "devon", site_owner=True) is None
        assert tracking.season_summary(conn, S.get_season(conn, S.current_season_id(conn))) is None


def test_race_master_confirms_a_start_but_never_hides_recorded_data(legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        with pytest.raises(S.ValidationError):
            tracking.set_start(conn, sid, "weather", 4, "devon")      # round 3 has weather recorded
        with pytest.raises(S.ValidationError):
            tracking.set_start(conn, sid, "race_times", 1, "devon")   # 4.0 tracking can't be moved
        tracking.set_start(conn, sid, "weather", 1, "devon")
        assert tracking.review_items(conn) == []
        evs = {e["round_number"]: e for e in S.events(conn, sid)}
        assert tracking.empty_text(conn, evs[1], "weather") == "Not recorded"


# --------------------------------------------------------------------------- the notice, through the website

def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _dash(client, token):
    return client.get(f"/career/{token}/dashboard").get_data(as_text=True)


TITLE = "Your league has been upgraded to Paddock Legacy 4.0"


def test_notice_once_per_player_per_league_across_devices(app, legacy):
    token, _ = legacy
    phone, laptop = _client(app, "carson"), _client(app, "carson")
    page = _dash(phone, token)
    assert TITLE in page and "Round 6 of the 2026 season" in page and "Got it" in page
    assert "See what&#39;s new in 4.0" in page or "See what's new in 4.0" in page
    with storage.session(token) as conn:
        mid = tracking.migration(conn)["id"]
    # Not now: hidden for this browser session only, never acknowledged.
    phone.post(f"/career/{token}/upgrade-notice/later", data={"csrf_token": "tok", "migration_id": mid})
    assert TITLE not in _dash(phone, token)
    assert TITLE in _dash(laptop, token), "dismissing isn't acknowledging"
    # Got it on the laptop: gone on every device and after signing in again.
    laptop.post(f"/career/{token}/upgrade-notice", data={"csrf_token": "tok", "migration_id": mid})
    assert TITLE not in _dash(laptop, token)
    assert TITLE not in _dash(_client(app, "carson"), token)
    # Another player still has theirs.
    assert TITLE in _dash(_client(app, "kim"), token)
    with storage.session(token) as conn:
        assert [a["username"] for a in tracking.acknowledged(conn, mid)] == ["carson"]


def test_acknowledging_one_league_leaves_the_other(app, legacy, career):
    token, _ = legacy
    other = storage.new_token()
    with storage.session(other, create=True) as conn:
        S.seed_career(conn, other, "Second League", 2026, ["Ann Lee"])
        _members(conn, "carson")
        _play(conn, 1)
    _as_3x(other)
    c = _client(app, "carson")
    assert TITLE in _dash(c, token) and TITLE in _dash(c, other)
    with storage.session(token) as conn:
        mid = tracking.migration(conn)["id"]
    c.post(f"/career/{token}/upgrade-notice", data={"csrf_token": "tok", "migration_id": mid})
    assert TITLE not in _dash(c, token) and TITLE in _dash(c, other)


def test_members_who_join_after_the_upgrade_dont_get_it(app, legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        _members(conn, "newbie")
    assert TITLE not in _dash(_client(app, "newbie"), token)


def test_change_notices_come_first_then_the_upgrade_notice(app, legacy):
    token, _ = legacy
    with storage.session(token) as conn:
        roles.set_member(conn, "carson", "member", S.player_drivers(conn)[1]["id"])
        did = S.player_drivers(conn)[1]["id"]
        impacts.add_notice(conn, did, "test-change", "A test change", "Because", [])
    c = _client(app, "carson")
    res = c.get(f"/career/{token}/dashboard")
    assert res.status_code == 302 and "changes" in res.headers["Location"]
    page = c.get(res.headers["Location"]).get_data(as_text=True)
    assert TITLE not in page, "never stacked on top of the change notice"


def test_legacy_banner_and_pages(app, legacy, master_client):
    token, _ = legacy
    stats = master_client.get(f"/career/{token}/stats").get_data(as_text=True)
    assert "Legacy season" in stats and "Rounds 1–5 of this season used an earlier tracking system" in stats
    assert "from Round 6 of this season" in stats
    home = _dash(master_client, token)
    assert "Legacy season" not in home       # the season under way: the banner stays on the history pages
    with storage.session(token) as conn:
        evs = {e["round_number"]: e for e in S.events(conn, S.current_season_id(conn))}
    old_round = master_client.get(f"/career/{token}/weekend/{evs[2]['id']}").get_data(as_text=True)
    assert "Legacy season" in old_round and "Not tracked under this season" in old_round
    assert "Still needed before this round can be submitted" not in old_round
    new_round = master_client.get(f"/career/{token}/weekend/{evs[7]['id']}").get_data(as_text=True)
    assert "Legacy season" not in new_round
    detail = master_client.get(f"/career/{token}/legacy-tracking").get_data(as_text=True)
    assert "What each season tracked" in detail and "to confirm" in detail
    res = master_client.post(f"/career/{token}/legacy-tracking", data={"csrf_token": "tok", "feature": "weather",
                                                                     "season_id": S_id(token), "from_round": "1"})
    assert res.status_code == 302
    with storage.session(token) as conn:
        assert tracking.review_items(conn) == []


def S_id(token):
    with storage.session(token) as conn:
        return S.current_season_id(conn)


def test_spectators_can_acknowledge(app, legacy):
    token, _ = legacy
    auth.create_user("viewer", "Viewer", "password1")
    with storage.session(token) as conn:
        roles.set_member(conn, "viewer", "spectator")
        mig = tracking.migration(conn)
        conn.execute("UPDATE tracking_migrations SET audience = ? WHERE id = ?",
                     (json.dumps(mig["audience"] + ["viewer"]), mig["id"]))
    c = _client(app, "viewer")
    assert TITLE in _dash(c, token)
    res = c.post(f"/career/{token}/upgrade-notice", data={"csrf_token": "tok", "migration_id": mig["id"]})
    assert res.status_code == 302 and TITLE not in _dash(c, token)
