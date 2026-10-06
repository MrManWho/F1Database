"""4.0.0-beta.13: the League Readiness Check (readiness.py, Manage League -> Readiness check).

The eleven scenarios asked for, plus the read-only guarantee: a clean league, an incomplete weekend, a valid legacy
season, a genuinely missing record, a mid-season migration, a finale with unresolved contracts, a valid seatless
driver, a failed check, stale results after an edit, permissions and a change saved while checking.
"""

import random
import re

import pytest

from f1tracker import ai3, auth, feed, market, readiness, roles, seats, storage, tracking
from f1tracker import constants as C
from f1tracker import services as S

from conftest import login, players, pledge_all, run_event
from test_v400_legacy_tracking import _as_3x, _members, _play


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _league(master_client):
    for u in ("ana", "ben", "kim", "sam", "pat"):
        auth.create_user(u, u.title(), "password1")
    res = master_client.post("/careers/new", data={"name": "Readiness League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        S.place_players(conn, sid, {a: (10, 1), b: (9, 1)})
        roles.set_member(conn, "kim", "scorekeeper")
        roles.set_member(conn, "sam", "spectator")
        roles.set_member(conn, "pat", "member")
        storage.set_meta(conn, "timezone", "UTC")
    pledge_all(token)
    master_client.get(f"/career/{token}/dashboard")         # the league's normal first-open steps
    return token, a, b


def _report(token, history=True, is_master=True):
    with storage.session(token) as conn:
        rep = readiness.run(conn, history=history)
        return rep, readiness.view(rep, None, is_master)


def _titles(v):
    return [f["title"] for f in v["findings"]]


def _complete_round(conn, ev):
    rows = S.weekend_rows(conn, ev["id"])
    first = rows[0]["driver_id"]
    run_event(conn, ev, difficulty=80, fl=first, dotd=first, complete=False)
    conn.execute("UPDATE events SET notes = 'A clean race' WHERE id = ?", (ev["id"],))


def _dump(token):
    with storage.session(token) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tables}


# --------------------------------------------------------------------------- 1. a clean league

def test_a_clean_league_is_ready_to_submit_and_never_green_before_the_full_check(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        run_event(conn, evs[0], difficulty=80, fl=a, dotd=a)
        _complete_round(conn, evs[1])
    rep, v = _report(token, history=False)
    assert v["targets"]["weekend"]["status"] == "ready", v["targets"]["weekend"]
    assert v["counts"]["blocking"] == 0
    assert v["targets"]["transition"]["status"] == "not_checked"         # full-history checks haven't run
    assert v["overall"] != "ready"
    rep, v = _report(token, history=True)
    assert v["targets"]["transition"]["status"] == "ready", v["targets"]["transition"]
    assert v["targets"]["season_close"]["status"] == "attention"           # 22 rounds still to play
    page = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "League Readiness Check" in page and "Ready to submit the current weekend" in page
    assert "Readiness check" in page                                       # in Manage League


# --------------------------------------------------------------------------- 2. an incomplete weekend

@pytest.mark.engine3
@pytest.mark.pacerequired
def test_an_incomplete_weekend_names_the_driver_the_session_and_the_fix(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        ev = next(e for e in evs if not e["is_sprint"])
        for e in evs:
            if e["round_number"] < ev["round_number"]:
                run_event(conn, e, difficulty=80, fl=a, dotd=a)
        run_event(conn, ev, difficulty=80, fl=a, dotd=a, complete=False)
        assert ai3.missing_pace(conn, S.get_event(conn, ev["id"]))
    rep, v = _report(token, history=False)
    timing = [f for f in v["findings"] if "timing is incomplete" in f["title"]]
    assert {f["subject"] for f in timing} == {"Ana Silva", "Ben Okafor"}
    f = timing[0]
    assert f["title"].startswith(f"Round {ev['round_number']}: ") and f["severity"] == "blocking"
    assert f["blocks"] == ["weekend"] and f["link"].endswith("#pace") and "timing" in f["link_label"]
    assert "Don't submit times" in f["detail"]
    assert v["targets"]["weekend"]["status"] == "blocked"
    # The permitted opt-out clears it; nothing new is demanded.
    with storage.session(token) as conn:
        for d in (a, b):
            conn.execute("INSERT INTO pace_inputs(event_id, driver_id, session, untracked) VALUES(?,?,'gp',1)",
                         (ev["id"], d))
    rep, v = _report(token, history=False)
    assert not [f for f in v["findings"] if "timing" in f["title"]]
    assert v["targets"]["weekend"]["status"] == "ready"


# --------------------------------------------------------------------------- 3 and 5. legacy seasons

@pytest.mark.engine3
@pytest.mark.latest
@pytest.mark.trackai
@pytest.mark.pacerequired
def test_a_valid_legacy_season_counts_untracked_information_as_not_applicable(career):
    with storage.session(career) as conn:
        _members(conn, "carson")
        _play(conn, len(S.events(conn, S.current_season_id(conn))))      # the whole season on "3.x"
    _as_3x(career)
    with storage.session(career) as conn:
        mig = tracking.migration(conn)
        assert mig["start_year"] == 2027 and mig["start_round"] == 1
    rep, v = _report(career)
    text = " ".join(_titles(v) + [f["detail"] for f in v["findings"]]).lower()
    assert "race times" not in text and "timing" not in text and "weather" not in text
    assert v["targets"]["weekend"]["status"] == "na"                  # every round is in: nothing to submit
    tr = next(c for c in v["checks"] if c["id"] == "weekend_timing")
    assert tr["state"] == "not_applicable"


@pytest.mark.engine3
@pytest.mark.latest
@pytest.mark.trackai
@pytest.mark.pacerequired
def test_a_midseason_migration_shows_where_tracking_began_and_asks_only_to_confirm(career, app):
    with storage.session(career) as conn:
        _members(conn, "carson", "kim")
        _play(conn, 5, weather_from=3, press_from=1)
    _as_3x(career)
    with storage.session(career) as conn:
        pass
    rep, v = _report(career)
    titles = _titles(v)
    assert any("confirm when weather began" in t for t in titles)
    confirm = next(f for f in v["findings"] if "confirm when weather" in f["title"])
    assert confirm["severity"] == "warning" and not confirm["blocks"] and confirm["link"] == "legacy-tracking"
    assert not any("timing" in t or "race times" in t for t in titles)     # rounds 1-5 never asked for them
    notice = next(f for f in v["findings"] if "upgrade notice" in f["title"])
    assert notice["severity"] == "optional"                                 # information only
    with storage.session(career) as conn:
        tv = readiness.transition_view(v, conn)
    assert tv["when"].startswith("mid-season") and "Round 6 of 2026" in tv["how"]
    rec = next(c for c in v["checks"] if c["id"] == "tracking_record")
    assert any("Round 6 of 2026" in n for n in rec["notes"])


# --------------------------------------------------------------------------- 4. a genuinely missing record

def test_a_genuinely_missing_historical_record_is_reported(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
        run_event(conn, evs[0], difficulty=80, fl=a, dotd=a)
        conn.execute("DELETE FROM results WHERE event_id = ?", (evs[0]["id"],))
    rep, v = _report(token)
    f = next(f for f in v["findings"] if "submitted with no results" in f["title"])
    assert f["severity"] == "warning" and f["link"] == f"weekend/{evs[0]['id']}"
    assert v["targets"]["season_close"]["status"] == "attention"


# --------------------------------------------------------------------------- 6. a finale with unresolved contracts

def test_a_season_finale_shows_unresolved_contracts_and_the_grid_conflict(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        for e in evs[:-1]:
            run_event(conn, e, difficulty=80, fl=a, dotd=a)
        market.open_window(conn, sid, rng=random.Random(3))
        assert conn.execute("SELECT COUNT(*) FROM offers WHERE status = 'Pending'").fetchone()[0]
    rep, v = _report(token)
    offers = [f for f in v["findings"] if "to answer" in f["title"] and f["check"] == "offers"]
    assert offers and v["targets"]["next_season"]["status"] == "attention"
    for f in offers:                         # never the terms of an offer
        assert not re.search(r"No\. ?[12]|Equal Status|year deal|\$", f["title"] + f["detail"])
    with storage.session(token) as conn:
        c = S.add_player_driver(conn, "Cara Diaz", sid)
        for d in (a, b, c):
            seats.record_contract(conn, d, 10, 2027, 1)
    rep, v = _report(token)
    assert v["targets"]["next_season"]["status"] == "blocked"
    clash = next(f for f in v["findings"] if f["check"] == "rollover" and f["severity"] == "blocking")
    assert "3 drivers signed for 2027" in clash["title"] and clash["blocks"] == ["next_season"]
    with storage.session(token) as conn:
        tv = readiness.transition_view(v, conn)
    line = next(l for l in tv["lines"] if l["label"] == "Next-season contracts and grid")
    assert line["state"] == "Blocked"


# --------------------------------------------------------------------------- 7. a valid seatless driver

def test_a_seatless_driver_is_a_valid_outcome_but_a_contract_without_a_seat_is_not(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        S.place_players(conn, sid, {b: None})                          # released to free agency, no contract
    rep, v = _report(token, history=False)
    assert not [f for f in v["findings"] if f["check"] == "seats" and "Ben Okafor" in f["title"]]
    chk = next(c for c in v["checks"] if c["id"] == "seats")
    assert any("Ben Okafor" in n and "valid career outcome" in n for n in chk["notes"])
    with storage.session(token) as conn:
        seats.record_contract(conn, b, 9, 2026, 1)                     # signed for this season, but no seat
    rep, v = _report(token, history=False)
    f = next(f for f in v["findings"] if f["check"] == "seats" and "Ben Okafor" in f["title"])
    assert f["severity"] == "warning" and "contracted but not seated" in f["title"]


# --------------------------------------------------------------------------- 8. a failed check

def test_a_failed_check_is_never_shown_as_ready(app, master_client, monkeypatch):
    token, a, b = _league(master_client)
    def boom(*_a, **_k):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(seats, "season_states", boom)
    rep, v = _report(token)
    chk = next(c for c in v["checks"] if c["id"] == "seats")
    assert chk["state"] == "failed" and "secret" not in chk["error"]
    assert v["targets"]["next_season"]["status"] == "failed" and v["overall"] == "failed"
    monkeypatch.setattr(readiness, "snapshot", boom)                    # the copy itself can't be made
    rep, v = _report(token)
    assert rep["failed"] and all(t["status"] == "failed" for t in v["targets"].values())
    page = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "Check failed" in page and ">Ready<" not in page


# --------------------------------------------------------------------------- 9. stale after an edit

def test_results_are_marked_stale_after_a_relevant_change(app, master_client):
    token, a, b = _league(master_client)
    assert master_client.post(f"/career/{token}/readiness", data={"csrf_token": "tok"}).status_code == 302
    page = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "Changes since last check" not in page and "not run yet" not in page
    master_client.get(f"/career/{token}/standings")                      # only looking: still current
    assert "Changes since last check" not in master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0], difficulty=80, fl=a, dotd=a)
    page = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "Changes since last check: run again" in page
    with storage.session(token) as conn:
        rep = readiness.run(conn)
        v = readiness.view(rep, readiness.load_history(token), True)
    assert v["stale_history"] and v["targets"]["transition"]["status"] == "not_checked"


# --------------------------------------------------------------------------- 10. permissions and privacy

def test_scorekeepers_see_only_their_weekend_and_others_are_refused(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        for e in evs[:13]:
            run_event(conn, e, difficulty=80, fl=a, dotd=a)
        market.open_window(conn, sid, rng=random.Random(3))
        conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                     "VALUES(?,?,?,?,?,?)", (evs[0]["id"], a, "q_private", "MY SECRET ANSWER", 0, "2026-09-25"))
    kim = _client(app, "kim")
    page = kim.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "Ready to submit the current weekend" in page
    assert "Ready to start the next season" not in page and "offer" not in page.split("Findings")[1].lower()
    assert "only shown to the Race Master" in page and "Run full check" not in page
    assert kim.post(f"/career/{token}/readiness", data={"csrf_token": "tok"}).status_code == 403
    for name in ("pat", "sam", "ana"):
        assert _client(app, name).get(f"/career/{token}/readiness").status_code == 403
    rm = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "MY SECRET ANSWER" not in rm and "MY SECRET ANSWER" not in page
    with storage.session(token) as conn:
        rep = readiness.run(conn)
    sk = readiness.view(rep, None, False)
    assert all(f["audience"] == "ops" for f in sk["findings"]) and list(sk["targets"]) == ["weekend"]


# --------------------------------------------------------------------------- 11. a change saved while checking

def test_a_change_saved_while_checking_is_reported_not_hidden(app, master_client, monkeypatch):
    token, a, b = _league(master_client)

    saves = []

    def someone_saves():
        saves.append(1)
        with storage.session(token) as other:
            other.execute("UPDATE drivers SET notes = ? WHERE id = ?", (f"edited meanwhile {len(saves)}", a))
    monkeypatch.setattr(readiness, "_after_snapshot", someone_saves)
    with storage.session(token) as conn:
        rep = readiness.run(conn, history=True)
    v = readiness.view(rep, None, True)
    assert rep["changed_during"] and all(c.get("stale") for c in v["checks"])
    assert all(t["status"] in ("not_checked", "failed", "blocked", "na") for t in v["targets"].values())
    page = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    assert "while it was being checked" in page


# --------------------------------------------------------------------------- read-only

def test_opening_and_running_the_check_changes_nothing(app, master_client):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        for e in evs[:13]:
            run_event(conn, e, difficulty=80, fl=a, dotd=a)
        market.open_window(conn, sid, rng=random.Random(3))
        conn.execute("UPDATE offers SET status = 'Declined'")             # a settled window it could close
    master_client.get(f"/career/{token}/dashboard")
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_windows WHERE status = 'Open'").fetchone()[0] in (0, 1)
        conn.execute("UPDATE market_windows SET status = 'Open', closed_at = NULL")   # left open, as before 3.2.6
    before = _dump(token)
    feed.take_outbox()
    assert master_client.get(f"/career/{token}/readiness").status_code == 200
    assert master_client.post(f"/career/{token}/readiness", data={"csrf_token": "tok"}).status_code == 302
    assert _client(app, "kim").get(f"/career/{token}/readiness").status_code == 200
    assert _dump(token) == before                                           # not one row, not one meta value
    assert feed.take_outbox() == []


def test_the_page_lists_findings_with_filters_and_collapsed_passes(app, master_client):
    token, a, b = _league(master_client)
    master_client.post(f"/career/{token}/readiness", data={"csrf_token": "tok"})
    page = master_client.get(f"/career/{token}/readiness").get_data(as_text=True)
    for bit in ('data-sev="blocking"', 'data-sev="warning"', 'data-sev="optional"', 'id="rd-cat"',
                "Passed or not applicable", "What each check verifies", "4.0 transition", "Site deployment",
                "aren't verified here", "Who can resolve it", "Blocks:"):
        assert bit in page, bit
    assert '<details class="rd-details"><summary>Passed' in page             # collapsed by default
