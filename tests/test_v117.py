"""v1.17: growth pledges judged on average finish against the car, with a season-end Reputation reward."""

import pytest

from conftest import players, run_event
from f1tracker import relations, services as S, storage
from f1tracker import constants as C


def _seat_at(conn, rank):
    sid = S.current_season_id(conn)
    me, other = players(conn)
    team = S.teams(conn)[rank - 1]["id"]
    S.place_players(conn, sid, {me: (team, 1)})
    return sid, me, team


def _run_at(conn, sid, me, average, rounds=None):
    """Complete rounds with the driver finishing so their average is exactly `average`."""
    evs = S.events(conn, sid)[:rounds] if rounds else S.events(conn, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"]) if r["driver_id"] != me]
    for i, ev in enumerate(evs):
        pos = max(1, int(round((i + 1) * average) - round(i * average)))
        order = ids[:pos - 1] + [me] + ids[pos - 1:]
        run_event(conn, ev, order=order, quali=order)


def test_every_pledge_closes_the_same_share_of_the_gap_in_any_car():
    for rank in range(1, 12):
        expected = relations.expected_finish(rank)
        assert relations.pledged_finish(rank, 0) == expected  # Steady = deliver the car
        for g, level in enumerate(C.GROWTH_LEVELS):
            closed = (expected - relations.pledged_finish(rank, g)) / (expected - 1)
            assert closed == pytest.approx(level["share"], abs=0.1 / (expected - 1) + 1e-9)
    # A bigger pledge is always harder, and it's always possible (never better than P1).
    for rank in range(1, 12):
        targets = [relations.pledged_finish(rank, g) for g in range(4)]
        assert targets == sorted(targets, reverse=True) and targets[-1] >= 1


@pytest.mark.parametrize("rank", [1, 4, 11])
def test_matching_the_car_keeps_steady_but_not_breakout(rank):
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Fair", 2026, ["Test Driver", "Other Player"])
        sid, me, team = _seat_at(conn, rank)
        relations.ensure(conn, sid)
        relations.set_pledge(conn, sid, me, 3)
        _run_at(conn, sid, me, relations.expected_finish(rank), rounds=6)
        a = relations.assess(conn, sid, me)
        r = S.team_strength_ranks(conn, sid)[team]
        assert a["pace"] <= relations.pledged_finish(r, 0) + 0.6   # about what the car should do
        assert not a["on_pledge"]                                   # Breakout needs much more, even in the best car


def test_slowest_car_can_keep_a_big_pledge():
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Fair", 2026, ["Test Driver", "Other Player"])
        sid, me, team = _seat_at(conn, 11)
        relations.ensure(conn, sid)
        relations.set_pledge(conn, sid, me, 2)   # Strong
        _run_at(conn, sid, me, relations.pledged_finish(11, 3), rounds=6)  # drive to a Breakout level
        a = relations.assess(conn, sid, me)
        assert a["on_pledge"] and a["live_status"] in ("Happy", "Delighted")


def test_dnf_counts_as_last_and_the_worst_weekend_is_dropped(db):
    sid, me, team = _seat_at(db, 6)
    relations.ensure(db, sid)
    evs = S.events(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, evs[0]["id"]) if r["driver_id"] != me]
    order = ids[:4] + [me] + ids[4:]          # P5
    run_event(db, evs[0], order=order, overrides={me: "DNF"})
    assert relations.pace(db, sid, me)["average"] == 2 * len(S.teams(db))
    for ev in evs[1:5]:
        run_event(db, ev, order=order)
    p = relations.pace(db, sid, me)
    assert p["rounds"] == 5 and p["dropped"] == 1 and p["average"] == 5.0


def test_kept_pledge_adds_reputation_to_next_season(db):
    sid, me, team = _seat_at(db, 6)
    relations.ensure(db, sid)
    relations.set_pledge(db, sid, me, 1)   # Solid
    _run_at(db, sid, me, relations.pledged_finish(6, 2))
    rewards = relations.settle(db, sid)
    assert rewards == {me: C.GROWTH_LEVELS[1]["reward"]}
    assert relations.settle(db, sid) == rewards  # settling twice changes nothing
    final = S.season_final_reputation(db, sid)[me]
    new_id = S.create_next_season(db, sid, 2027)
    relations.apply_rewards(db, sid, new_id)
    assert S.starting_reputation(db, new_id, me) == pytest.approx(min(100, final + C.GROWTH_LEVELS[1]["reward"]))
    notes = [n["text"] for n in relations.notes(db, sid, me)]
    assert any(t.startswith("Pledge kept") for t in notes)


def test_missed_pledge_gets_no_reward(db):
    sid, me, team = _seat_at(db, 6)
    relations.ensure(db, sid)
    relations.set_pledge(db, sid, me, 3)
    _run_at(db, sid, me, relations.expected_finish(6))
    assert relations.settle(db, sid) == {}
    row = db.execute("SELECT outcome, reward FROM team_relations WHERE driver_id = ?", (me,)).fetchone()
    assert row["outcome"] == "Missed" and row["reward"] == 0


def test_existing_relationships_get_finish_targets(db):
    sid, me, team = _seat_at(db, 6)
    relations.ensure(db, sid)
    relations.set_pledge(db, sid, me, 2)
    db.execute("UPDATE team_relations SET finish_base = NULL, finish_target = NULL")  # as saved by v1.16
    relations.ensure(db, sid)
    row = db.execute("SELECT * FROM team_relations WHERE driver_id = ?", (me,)).fetchone()
    rank = S.team_strength_ranks(db, sid)[team]
    assert row["finish_target"] == relations.pledged_finish(rank, 2)
    assert any("average finish" in n["text"] for n in relations.notes(db, sid, me))
