"""4.1.1: before the paddock opens, the Pre-race press card says who it's waiting on, and whoever can open the
paddock gets the button right there."""

import pytest

from test_v230 import _client, _league
from f1tracker import roles, services as S, storage


@pytest.mark.weekends
def test_pre_race_press_says_it_waits_on_the_paddock(app, master_client):
    token, a, b = _league(master_client)
    ana, ben = _client(app, "ana"), _client(app, "ben")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        roles.set_member(conn, "ben", "scorekeeper", driver_id=b)      # a driver who also runs the league
    url = f"/career/{token}/weekend/{ev['id']}"
    page = ana.get(url).get_data(as_text=True)
    assert "Waiting on the Scorekeeper or Race Master to open the paddock" in page
    assert "Nothing to answer yet." in page
    assert f"/weekend/{ev['id']}/paddock\"" not in page          # a driver never gets the button
    staff = ben.get(url).get_data(as_text=True)
    assert "Opens when you open the paddock" in staff
    card = staff.split('id="prerace"', 1)[1].split("</section>", 1)[0]
    assert f"/weekend/{ev['id']}/paddock\"" in card                # the Scorekeeper can open it from the card
    ben.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    page = ana.get(url).get_data(as_text=True)
    assert "Nothing to answer yet." not in page and 'class="press-q"' in page


@pytest.mark.weekends
def test_an_open_round_page_can_tell_the_paddock_opened(app, master_client):
    token, a, b = _league(master_client)
    ana = _client(app, "ana")
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    phase_url = f"/api/career/{token}/weekend/{ev['id']}/phase"
    page = ana.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert 'data-phase="upcoming"' in page and phase_url in page
    assert ana.get(phase_url).get_json() == {"ok": True, "phase": "upcoming"}
    master_client.post(f"/career/{token}/weekend/{ev['id']}/paddock", data={"csrf_token": "tok"})
    assert ana.get(phase_url).get_json()["phase"] == "paddock"
    assert app.test_client().get(phase_url).status_code in (302, 401, 403)     # signed out: nothing
