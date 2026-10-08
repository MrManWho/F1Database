"""Post-4.0.0: a submitted round reads as finished in the rail, race times have their own line in the rail (and hold
Sessions open until they're in), and the race times forms autosave."""

import re

import pytest

from f1tracker import ai3, services as S, storage
from test_v400_pace_times import _league, _pace, _payload, _submit

pytestmark = [pytest.mark.engine3, pytest.mark.pacerequired]


def _step(page, key):
    m = re.search(r'data-stage-link="' + key + r'".*?<small>(.*?)</small>', page, re.S)
    return m.group(1)


def test_race_times_in_the_rail_and_a_closed_round_reads_complete(app, master_client):
    token, one, ev = _league(master_client)
    with storage.session(token) as conn:
        payload = _payload(conn, ev)
    master_client.post(f"/api/career/{token}/weekend/{ev['id']}", json=payload, headers={"X-CSRF-Token": "tok"})
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert 'data-rail-times="r"' in page and "1 needed" in page
    assert _step(page, "sessions") == "Race times needed"                    # results in, race times aren't
    _pace(master_client, token, ev, one, race_time="1:32:45.123", bench_race_time="1:32:32.700", laps="58")
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert _step(page, "sessions") == "Complete"
    assert _submit(master_client, token, ev, payload).status_code == 200
    page = master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert [_step(page, k) for k in ("prepare", "sessions", "review", "debrief")] == ["Complete"] * 4
    assert "In progress" not in re.search(r'<nav class="ws-rail".*?</nav>', page, re.S).group(0)
    assert "data-autosave data-no-dirty" not in page                                       # corrections are saved on purpose


def test_race_times_autosave_answers_with_whats_still_needed(app, master_client):
    token, one, ev = _league(master_client)
    with storage.session(token) as conn:
        payload = _payload(conn, ev)
    master_client.post(f"/api/career/{token}/weekend/{ev['id']}", json=payload, headers={"X-CSRF-Token": "tok"})
    assert "data-autosave data-no-dirty" in master_client.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    url = f"/career/{token}/weekend/{ev['id']}/pace"
    half = master_client.post(url, data={"csrf_token": "tok", "driver_id": one, "session": "gp", "race_time": "1:32:45.123"},
                              headers={"X-Requested-With": "fetch"})
    assert half.status_code == 400 and "Enter both race times" in half.get_json()["error"]
    res = master_client.post(url, data={"csrf_token": "tok", "driver_id": one, "session": "gp", "race_time": "1:32:45.123",
                                        "bench_race_time": "1:32:32.700", "laps": "58"},
                             headers={"X-Requested-With": "fetch"})
    assert res.status_code == 200 and res.get_json() == {"ok": True, "missing": []}
    with storage.session(token) as conn:
        assert ai3.pace_input(conn, ev["id"], one)["race_gap"] == pytest.approx(12.423)
