"""4.0.0-beta.10: a login can be linked to a player driver that's already in the league, from "Player drivers
without a login", and a join request can take over an existing player driver instead of being refused."""

from conftest import login, players
from f1tracker import auth, storage, weekend as raceweek


def _members(token):
    with storage.session(token) as conn:
        return {r["username"]: dict(r) for r in conn.execute("SELECT * FROM career_members")}


def test_link_a_login_from_drivers_without_a_login(master_client, career):
    auth.create_user("carson", "Carson", "password1")
    with storage.session(career) as conn:
        p1, p2 = players(conn)
        raceweek.set_no_account(conn, p2, True)
    page = master_client.get(f"/career/{career}/members").get_data(as_text=True)
    assert f"/career/{career}/members/link/{p2}" in page and "Link login" in page
    res = master_client.post(f"/career/{career}/members/link/{p2}", data={"csrf_token": "tok", "username": "Carson"},
                             follow_redirects=True)
    assert "Carson now drives Carsten Hale" in res.get_data(as_text=True)
    m = _members(career)["carson"]
    assert m["driver_id"] == p2 and m["role"] == "member"
    with storage.session(career) as conn:
        assert p2 not in raceweek.no_account_ids(conn)            # they have a login now, so the tick goes


def test_link_keeps_a_scorekeeper_and_refuses_a_second_driver(master_client, career):
    auth.create_user("kim", "Kim", "password1")
    master_client.post(f"/career/{career}/members/add", data={"username": "kim", "role": "scorekeeper", "csrf_token": "tok"})
    with storage.session(career) as conn:
        p1, p2 = players(conn)
    master_client.post(f"/career/{career}/members/link/{p1}", data={"csrf_token": "tok", "username": "kim"})
    assert _members(career)["kim"]["role"] == "scorekeeper" and _members(career)["kim"]["driver_id"] == p1
    res = master_client.post(f"/career/{career}/members/link/{p2}", data={"csrf_token": "tok", "username": "kim"},
                             follow_redirects=True)
    assert "already drives Devon Corwin" in res.get_data(as_text=True)
    res = master_client.post(f"/career/{career}/members/link/{p2}", data={"csrf_token": "tok", "username": "nobody"},
                             follow_redirects=True)
    assert "no login called nobody" in res.get_data(as_text=True)
    assert _members(career)["kim"]["driver_id"] == p1


def test_the_site_owner_can_link_themselves(master_client, career):
    with storage.session(career) as conn:
        p1, _ = players(conn)
    master_client.post(f"/career/{career}/members/link/{p1}", data={"csrf_token": "tok", "username": "devon"})
    m = _members(career)["devon"]
    assert m["driver_id"] == p1 and m["role"] == "race_master"


def test_link_is_only_for_player_drivers(master_client, career):
    auth.create_user("carson", "Carson", "password1")
    with storage.session(career) as conn:
        ai = conn.execute("SELECT id FROM drivers WHERE is_player = 0").fetchone()["id"]
    res = master_client.post(f"/career/{career}/members/link/{ai}", data={"csrf_token": "tok", "username": "carson"})
    assert res.status_code == 404


def test_a_join_request_can_take_over_an_existing_player_driver(app, master_client, career):
    auth.create_user("carson", "Carson", "password1")
    carson = app.test_client()
    login(carson, "carson")
    with storage.session(career) as conn:
        _, p2 = players(conn)
    res = carson.post(f"/career/{career}/join", data={"csrf_token": "tok", "role": "driver", "driver_name": "carsten hale"},
                      follow_redirects=True)
    assert "Request sent" in res.get_data(as_text=True)
    page = master_client.get(f"/career/{career}/members").get_data(as_text=True)
    assert f'<option value="{p2}" selected>Carsten Hale</option>' in page
    with storage.session(career) as conn:
        rid = conn.execute("SELECT id FROM join_requests").fetchone()["id"]
        before = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]
    master_client.post(f"/career/{career}/members/request/{rid}/approve",
                       data={"csrf_token": "tok", "role": "driver", "driver_id": str(p2), "driver_name": "Carsten Hale"})
    assert _members(career)["carson"]["driver_id"] == p2
    with storage.session(career) as conn:
        assert conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == before    # no duplicate driver


def test_a_join_request_cannot_claim_a_driven_or_f1_driver(app, master_client, career):
    for u in ("carson", "sam"):
        auth.create_user(u, u.title(), "password1")
    with storage.session(career) as conn:
        p1, _ = players(conn)
        ai = conn.execute("SELECT name FROM drivers WHERE is_player = 0").fetchone()["name"]
    master_client.post(f"/career/{career}/members/link/{p1}", data={"csrf_token": "tok", "username": "carson"})
    sam = app.test_client()
    login(sam, "sam")
    for name in ("Devon Corwin", ai):
        res = sam.post(f"/career/{career}/join", data={"csrf_token": "tok", "role": "driver", "driver_name": name},
                       follow_redirects=True)
        assert "already a driver with that name" in res.get_data(as_text=True)
