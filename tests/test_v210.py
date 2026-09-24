"""v2.1 fixes and features from the post-2.0 issue list."""

from conftest import login, pledge_all, players, run_event
from f1tracker import auth, services as S, storage


def _league(master_client, name="Issue League", players_=("Ana Silva", "Ben Okafor"), logins=("ana", "")):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite", "player_name": list(players_),
                                                   "player_login": list(logins)})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


# --------------------------------------------------------------------------- navigation and counts

def test_league_list_counts_only_this_seasons_rounds(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        total = len(S.events(conn, sid))
        for e in S.events(conn, sid):
            run_event(conn, e)
        new = S.create_next_season(conn, sid, 2027)
        storage.set_meta(conn, "current_season_id", str(new))
        S.delete_event(conn, S.events(conn, new)[-1]["id"])
    card = next(c for c in storage.list_careers() if c["token"] == token)
    assert (card["completed"], card["total"]) == (0, total - 1)
    assert f"0/{total - 1} rounds" in master_client.get("/").get_data(as_text=True)


def test_contracts_offers_press_and_progression_have_their_own_pages(app, master_client):
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        a = players(conn)[0]
        S.place_players(conn, S.current_season_id(conn), {a: (1, 1)})
    pledge_all(token)
    ana = _client(app, "ana")
    dash = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert f'href="/career/{token}/offers"' in dash and f'href="/career/{token}/press"' in dash
    offers = ana.get(f"/career/{token}/offers").get_data(as_text=True)
    assert "Negotiations" in offers and "Your trend" not in offers
    garage = ana.get(f"/career/{token}/garage").get_data(as_text=True)
    assert "Negotiations" not in garage and "Contracts &amp; offers" in garage
    press = ana.get(f"/career/{token}/press").get_data(as_text=True)
    assert "No questions waiting" in press and "What you've said" in press
    with storage.session(token) as conn:
        run_event(conn, S.events(conn, S.current_season_id(conn))[0])
    press = ana.get(f"/career/{token}/press").get_data(as_text=True)
    assert 'name="back" value="press"' in press
    profile = ana.get(f"/career/{token}/driver/{a}").get_data(as_text=True)
    assert "My progression" in profile


def test_view_mode_descriptions_do_not_define_a_role_by_itself(app, master_client):
    token = _league(master_client)
    page = master_client.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "like a Scorekeeper" not in page and "what a spectator sees" not in page
    assert "Enter and edit race results; no administration" in page
