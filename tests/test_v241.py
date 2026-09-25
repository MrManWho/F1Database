"""v2.4.1: the AI recommendation blends the car reading with the whole-grid reading, holds while anyone is at the
back, and the league can choose how rounds are judged."""

from conftest import login
from f1tracker import auth, impacts, services as S, storage
from f1tracker import constants as C


def _league(master_client):
    if not auth.get_user("ana"):
        auth.create_user("ana", "Ana", "password1")
    res = master_client.post("/careers/new", data={"name": "V241", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", ""], "csrf_token": "tok"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def test_the_league_chooses_how_rounds_are_judged(app, master_client):
    token = _league(master_client)
    with storage.session(token) as conn:
        assert S.difficulty_mode(conn) == "blend"
    page = master_client.get(f"/career/{token}/settings/weekends").get_data(as_text=True)
    assert "How each round is judged" in page and "Blend (half car, half overall) (recommended)" in page
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "section": "weekends", "team_life": "1",
                                                          "difficulty_recs": "1", "difficulty_mode": "car"})
    with storage.session(token) as conn:
        assert S.difficulty_mode(conn) == "car"
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "section": "weekends", "team_life": "1",
                                                          "difficulty_recs": "1", "difficulty_mode": "nonsense"})
    with storage.session(token) as conn:
        assert S.difficulty_mode(conn) == "car"          # unknown values are ignored
    ana = app.test_client()
    login(ana, "ana")
    assert "Against the whole grid" in ana.get("/help").get_data(as_text=True)


def test_upgrading_from_2_4_shows_the_2_4_1_note(app, master_client):
    token = _league(master_client)
    master_client.get(f"/career/{token}/dashboard")
    with storage.session(token) as conn:
        storage.set_meta(conn, "calc_version", "2")
    page = master_client.get(f"/career/{token}/standings").get_data(as_text=True)
    assert impacts.CALC_NOTES[3][0] in page and "never goes up while a player driver is struggling" in page
    with storage.session(token) as conn:
        assert storage.get_meta(conn, "calc_version") == str(C.CALC_VERSION) == "3"


def test_the_worked_example_from_the_proposal():
    """Slowest car (rank 11), qualified and finished P22, AI teammate P20, 22 cars: blend score about -0.37."""
    no_points = lambda pos, sp, ss: S.gp_points(pos, C.STATUS_FINISHED)   # noqa: E731
    args = (22, 22, no_points, False, None, C.STATUS_NOT_RUN, False, (20 - 22) / 10)
    car, overall = S._round_part(21.5, *args), S._round_part(11.5, *args)
    assert round(car, 2) == -0.09 and round(overall, 2) == -0.65
    assert round((1 - C.DIFF_OVERALL_SHARE) * car + C.DIFF_OVERALL_SHARE * overall, 2) == -0.37
