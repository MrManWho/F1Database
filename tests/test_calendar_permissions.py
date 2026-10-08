"""Calendar permissions: everyone in a league sees the calendar; only the Race Master changes it, unless they let
Scorekeepers set race times or edit the calendar (League settings > Joining & roles > Role permissions)."""

from f1tracker import auth, roles, services as S, storage

from conftest import login


def _league(client):
    res = client.post("/careers/new", data={"name": "Cal", "year": "2026", "player_name": ["Ana Silva"],
                                             "player_login": [""], "csrf_token": "tok"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _people(app, token):
    clients = {}
    for name, role in (("kim", "scorekeeper"), ("max", "member"), ("sam", "spectator")):
        auth.create_user(name, name.title(), "password1")
        with storage.session(token) as conn:
            roles.set_member(conn, name, role)
        clients[name] = app.test_client()
        login(clients[name], name)
    return clients


def _allow(master_client, token, *keys):
    data = {"section": "roles", "perm_form": "1", "join_mode": "invite", "csrf_token": "tok",
            "perm_scorekeeper_telemetry_import": "1"}
    data.update({f"perm_scorekeeper_{k}": "1" for k in keys})
    master_client.post(f"/career/{token}/settings", data=data)


def test_everyone_sees_the_calendar_but_only_allowed_roles_change_it(master_client, app):
    token = _league(master_client)
    people = _people(app, token)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
    time_url = f"/career/{token}/weekend/{ev['id']}/time"
    when = {"race_at": "2026-11-01T19:00", "csrf_token": "tok"}
    for name, c in people.items():
        page = c.get(f"/career/{token}/seasons").get_data(as_text=True)
        assert ev["name"] in page and "View only" in page
        assert "Save calendar" not in page and "Set a time" not in page
        # Nobody but the Race Master changes anything by default, whatever the page shows.
        assert c.post(time_url, data=when).status_code == 403
        assert c.post(f"/career/{token}/calendar/add", data={"name": "Extra GP", "csrf_token": "tok"}).status_code == 403
        assert c.post(f"/career/{token}/calendar/{ev['id']}/delete", data={"csrf_token": "tok"}).status_code == 403
        assert c.post(f"/career/{token}/calendar/save", data={"csrf_token": "tok"}).status_code == 403
    rnd = people["kim"].get(f"/career/{token}/weekend/{ev['id']}?stage=prepare").get_data(as_text=True)
    assert 'id="race-time"' not in rnd

    # The Race Master lets Scorekeepers set race times (and nothing else).
    _allow(master_client, token, "race_times")
    kim = people["kim"]
    page = kim.get(f"/career/{token}/seasons").get_data(as_text=True)
    assert "You can set race times" in page and "Set a time" in page and "Save calendar" not in page
    assert 'id="race-time"' in kim.get(f"/career/{token}/weekend/{ev['id']}?stage=prepare").get_data(as_text=True)
    assert kim.post(time_url, data=when).status_code == 302
    assert kim.post(time_url, data={"postponed": "1", "csrf_token": "tok"}).status_code == 302
    with storage.session(token) as conn:
        assert S.get_event(conn, ev["id"])["postponed"]
    assert kim.post(f"/career/{token}/calendar/add", data={"name": "Extra GP", "csrf_token": "tok"}).status_code == 403
    for name in ("max", "sam"):
        assert people[name].post(time_url, data=when).status_code == 403
    assert "set race times" in master_client.get(f"/career/{token}/activity").get_data(as_text=True)

    # ...and to edit the calendar, but historical corrections stay with the Race Master.
    _allow(master_client, token, "race_times", "calendar_edit")
    page = kim.get(f"/career/{token}/seasons").get_data(as_text=True)
    assert "Save calendar" in page and "View only" not in page and 'name="historical_correction"' not in page
    assert kim.post(f"/career/{token}/calendar/add", data={"name": "Extra GP", "csrf_token": "tok"}).status_code == 302
    with storage.session(token) as conn:
        evs = S.events(conn, S.current_season_id(conn))
    assert evs[-1]["name"] == "Extra GP"
    assert kim.post(f"/career/{token}/calendar/save", data={"historical_correction": "1", "csrf_token": "tok"}).status_code == 403
    assert kim.post(f"/career/{token}/calendar/{evs[-1]['id']}/delete", data={"csrf_token": "tok"}).status_code == 302
    assert people["max"].post(f"/career/{token}/calendar/add", data={"name": "X", "csrf_token": "tok"}).status_code == 403
    with storage.session(token) as conn:
        assert roles.granted(conn, "scorekeeper", "calendar_edit") and not roles.granted(conn, "member", "race_times")
