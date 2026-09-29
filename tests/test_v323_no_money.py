"""3.2.3: deal terms saved by older versions no longer show salaries (the game has no money)."""

from conftest import players
from f1tracker import app as appmod, storage


def test_money_is_left_out_of_saved_deal_terms(app, master_client):
    res = master_client.post("/careers/new", data={"name": "Money League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Player One"], "player_login": [""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = conn.execute("SELECT id FROM seasons").fetchone()["id"]
        one = players(conn)[0]
        conn.execute("""INSERT INTO contracts(season_id, driver_id, team_id, negotiation_stage, requested_role, team_response,
                        outcome, conditions, notes, updated_at) VALUES(?,?,1,'Signed','No. 2','Offer accepted',
                        'Signed with the team from 2026','1-year deal, $1.3M/yr','A seat for a rookie','2026-09-22')""",
                     (sid, one))
    page = master_client.get(f"/career/{token}/contracts").get_data(as_text=True)
    assert "1-year deal" in page and "$1.3M" not in page and "/yr" not in page


def test_the_money_filter():
    f = appmod._no_money
    assert f("1-year deal, $0.9M/yr") == "1-year deal"
    assert f("2-year deal, Steady growth pledge") == "2-year deal, Steady growth pledge"
    assert f("3-year deal; salary: $1,200,000") == "3-year deal"
    assert f("") == "" and f(None) is None
