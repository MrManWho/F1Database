"""4.1.2: a race that arrived from the game before the round started doesn't keep saying "the race hasn't started"
once it has: starting the race fills the round in, and a round started or filled in some other way drops the notice."""

import json

from f1tracker import autofill, storage, telemetry, testleagues
from f1tracker import services as S
from f1tracker import weekend as raceweek
from test_v410_autofill import _round, real

WAITING = "can't be filled in yet"


def _waiting_round(token):
    event = _round(token)
    with storage.session(token) as conn:
        conn.execute("UPDATE events SET lights_at = NULL WHERE id = ?", (event["id"],))   # paddock open, not started
        race = json.loads(storage.get_meta(conn, "test_race_payload"))
        info = autofill.after_upload(conn, telemetry.store(conn, race))
        assert info["status"] == "waiting" and "Press Start the race" in info["why"]
    return event["id"]


@real
def test_starting_the_race_fills_in_a_race_that_was_waiting(app, master_client):
    token = testleagues.create("game_round", "devon")
    event_id = _waiting_round(token)
    with storage.session(token) as conn:
        raceweek.start_race(conn, event_id, "devon", True, "Everyone is here, lights out")
        info = autofill.state(conn, event_id)
        assert info["status"] == "ready" and any("race" in f for f in info["filled"])
        assert all(r["race_position"] for r in S.weekend_rows(conn, event_id))
    page = master_client.get(f"/career/{token}/weekend/{event_id}?stage=review").get_data(as_text=True)
    assert WAITING not in page and "Ready to approve" in page


@real
def test_a_round_started_another_way_drops_the_waiting_notice(app, master_client):
    token = testleagues.create("game_round", "devon")
    event_id = _waiting_round(token)
    with storage.session(token) as conn:   # e.g. started before 4.1.2, then filled in by hand
        conn.execute("UPDATE events SET lights_at = ? WHERE id = ?", (storage.now_iso(), event_id))
    page = master_client.get(f"/career/{token}/weekend/{event_id}?stage=review").get_data(as_text=True)
    assert WAITING not in page and "hasn't started yet" not in page
    with storage.session(token) as conn:
        assert autofill.state(conn, event_id)["status"] == "waiting"   # the page only stops showing it
