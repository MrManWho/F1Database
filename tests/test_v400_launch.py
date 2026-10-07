"""4.0.0 launch fixes: a round from an older season shows its own Legacy banner whichever season is selected, the
Readiness check doesn't call a new season "mid-season (0 of 24)", and the design system page is for site owners only."""

from f1tracker import readiness, storage
from f1tracker import services as S

from conftest import login
from test_v400_legacy_tracking import _as_3x, _play


def test_old_season_round_keeps_its_legacy_banner_after_rollover(app, career, master_client):
    with storage.session(career) as conn:
        old = S.current_season_id(conn)
        _play(conn, len(S.events(conn, old)))
    _as_3x(career)
    with storage.session(career) as conn:
        S.create_next_season(conn, old, 2027)
        old_round = S.events(conn, old)[3]
        new_sid = S.current_season_id(conn)
        assert new_sid != old
        new_round = S.events(conn, new_sid)[0]
    page = master_client.get(f"/career/{career}/weekend/{old_round['id']}").get_data(as_text=True)
    assert "Legacy season" in page
    page = master_client.get(f"/career/{career}/weekend/{new_round['id']}").get_data(as_text=True)
    assert "Legacy season" not in page


def test_readiness_says_start_of_season_before_round_one(career):
    with storage.session(career) as conn:
        v = readiness.view(readiness.run(conn, history=False), None, True)
        tv = readiness.transition_view(v, conn)
    assert tv["when"] == "at the start of a season, before Round 1"


def test_design_page_is_not_for_ordinary_accounts(app, master_client):
    assert master_client.get("/design").status_code == 200
    client = app.test_client()
    from f1tracker import auth
    auth.create_user("guest1", "Guest", "password1")
    login(client, "guest1", "password1")
    assert client.get("/design").status_code in (302, 403)
