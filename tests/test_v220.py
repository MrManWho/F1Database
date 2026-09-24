"""v2.2: audit fixes. Rollover loop, recovery with shared emails, passwords, fairer team goals, faster AI."""

import pytest

from conftest import login, players, run_event
from f1tracker import auth, constants as C, impacts, onboarding, seats, services as S, storage, teamgoals


def _league(master_client, name="Audit League", players_=("Ana Silva",), logins=("ana",)):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite", "player_name": list(players_),
                                                   "player_login": list(logins)})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _client(app, name, password="password1"):
    c = app.test_client()
    login(c, name, password)
    return c


def test_rollover_with_a_provisional_seat_never_loops(app, master_client):
    """F01: provisional seat + team goals + a pledge to choose + a change notice sent pages round in circles."""
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        S.place_players(conn, sid, {a: (1, 1)})
        teamgoals.set_enabled(conn, True)
        teamgoals.choose(conn, sid, S.driver_seats(conn, sid)[a][0], "competitive", "david")
        for e in S.events(conn, sid):
            run_event(conn, e)
        form = {"year": "2027", "csrf_token": "tok"}
        for r in seats.rollover_review(conn, sid, 2027)["rows"]:
            if r["needs_decision"]:
                form[f"decision_{r['driver']['id']}"] = "provisional"
    master_client.post(f"/career/{token}/seasons/new", data=form)
    with storage.session(token) as conn:
        new = S.current_season_id(conn)
        assert new != sid
        impacts.add_notice(conn, a, "test-notice", "A change", "Because of a test.", season_id=new)
    ana = _client(app, "ana")
    seen, path = [], f"/career/{token}/dashboard"
    for _ in range(6):
        res = ana.get(path)
        if res.status_code != 302:
            break
        path = res.headers["Location"]
        assert path not in seen, f"redirect loop: {seen + [path]}"
        seen.append(path)
    assert res.status_code == 200 and path.endswith("/changes")            # step 1: agree to the change
    ana.post(f"/career/{token}/changes", data={"csrf_token": "tok", "agree": "1"})
    res = ana.get(f"/career/{token}/dashboard")
    assert res.headers["Location"].endswith("/pledge")                        # step 2: the pledge
    assert ana.get(f"/career/{token}/pledge").status_code == 200
    ana.post(f"/career/{token}/pledge", data={"csrf_token": "tok", "growth": "1"})
    res = ana.get(f"/career/{token}/dashboard")
    assert res.headers["Location"].endswith("/team-goals")                    # step 3: the team goal
    assert ana.get(f"/career/{token}/team-goals").status_code == 200
    with storage.session(token) as conn:
        team = S.driver_seats(conn, new)[a][0]
    ana.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "tier": "safe"})
    assert ana.get(f"/career/{token}/dashboard").status_code == 200           # then the league opens


def test_recovery_lists_every_account_sharing_an_email(app, master_client):
    for name in ("sam1", "sam2"):
        auth.create_user(name, name.title(), "password1", email="shared@example.com")
    auth.create_user("other", "Other", "password1", email="other@example.com")
    page = master_client.get("/accounts?find=Shared@Example.com").get_data(as_text=True)
    assert "2 accounts match" in page and "sam1" in page and "sam2" in page and "other" not in page.split('id="recovery"')[1]
    assert page.count('class="recovery-card"') == 2
    page = master_client.get("/accounts?find=sam2").get_data(as_text=True)
    assert page.count('class="recovery-card"') == 1
    assert [u["username"] for u in auth.find_users("shared@example.com")] == ["sam1", "sam2"]
    # Still no list of all accounts.
    assert auth.find_users("") == [] and 'class="recovery-card"' not in master_client.get("/accounts").get_data(as_text=True)


def test_new_passwords_are_long_and_not_common():
    assert auth.PASSWORD_MIN == 8
    for weak in ("abc1234", "password1", "Password123", "qwertyuiop", "11111111", "abababab"):
        assert auth.password_problem(weak), weak
    assert auth.password_problem("tyre-wall-9") is None
    with pytest.raises(auth.AuthError):
        auth.signup_direct("weakling", "W", "password1", "1.1.1.1")
    auth.create_user("keeper", "K", "password1")            # existing passwords (and admin tools) keep working
    assert auth.verify("keeper", "password1")
    with pytest.raises(auth.AuthError):
        auth.set_password("keeper", "letmein1")


def test_team_goals_count_points_already_scored(app, master_client):
    """F04: a back-of-the-grid team that scored well in R1 must not have Safe already met."""
    token = _league(master_client, players_=("Ana Silva",), logins=("",))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        ranks = S.team_strength_ranks(conn, sid)
        slow = max(ranks, key=ranks.get)
        S.place_players(conn, sid, {a: (slow, 1)})
        teamgoals.set_enabled(conn, True)
        before = teamgoals.options(conn, sid, slow)
        ev = S.events(conn, sid)[0]
        ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        run_event(conn, ev, order=[d for d in ids if d != a][:4] + [a])       # P5 in the slowest car
        earned = teamgoals._standings(conn, sid)[slow][1]
        assert earned >= 10
        after = teamgoals.options(conn, sid, slow)
        s, c, x = (after["options"][k]["target_points"] for k in ("safe", "competitive", "ambitious"))
        assert s > earned                                                     # Safe is never already done
        assert c - s >= max(3, 0.25 * (s - earned)) and x - c >= max(3, 0.25 * (c - earned))
        assert s > before["options"]["safe"]["target_points"]                 # the pace counts
        assert "already scored in 1 round" in after["why"]


def test_ai_reacts_faster_with_bands_and_an_evidence_line():
    assert C.DIFF_MAX_STEP == 8 and C.DIFF_CONFIDENCE_K < 1
    assert [S.difficulty_band(v) for v in (1, 40, 41, 65, 66, 82, 99, 100, 110)] == [
        "Beginner", "Beginner", "Casual", "Casual", "Intermediate / Advanced", "Intermediate / Advanced",
        "Intermediate / Advanced", "Expert", "Expert"]


def test_full_preset_turns_team_goals_on(app, master_client):
    assert onboarding.PRESETS["full"]["team_goals"] and "Selectable team goals" in onboarding.PRESETS["full"]["enables"]
    res = master_client.post("/careers/new", data={"name": "Full", "year": "2026", "csrf_token": "tok", "wizard": "1",
                                                   "preset": "full", "join_mode": "invite", "player_name": ["Ana Silva"],
                                                   "player_who": ["me"]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        assert teamgoals.enabled(conn)


def test_legal_pages_have_no_host_placeholder(app, master_client):
    master_client.post("/settings", data={"csrf_token": "tok", "contact_email": "owner@example.com"})
    for path in ("/privacy", "/terms"):
        page = app.test_client().get(path).get_data(as_text=True)
        assert "should replace" not in page and "Whoever runs this copy" not in page
        assert "owner@example.com" in page and "Effective" in page
    assert "How long it's kept" in app.test_client().get("/privacy").get_data(as_text=True)


def test_rollover_summary_counts_provisional_seats(app, master_client):
    token = _league(master_client, players_=("Ana Silva",), logins=("",))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        year = S.get_season(conn, sid)["year"] + 1
    page = master_client.get(f"/career/{token}/seasons/rollover?year={year}").get_data(as_text=True)
    assert "Provisional (awaiting contract)" in page and 'data-ro-count="provisional"' in page


def test_refused_sign_ups_dont_use_up_the_hourly_limit(app):
    """Found by the full-season simulation: a sign-up refused for a weak password still counted toward the
    5-an-hour limit for that connection, so a few typos locked a household out."""
    auth.create_user("admin", "Admin", "password1", is_master=True)
    for _ in range(auth.SIGNUPS_PER_IP_PER_HOUR + 2):
        with pytest.raises(auth.AuthError):
            auth.signup_direct("typo", "T", "short", "9.9.9.9")
    for i in range(auth.SIGNUPS_PER_IP_PER_HOUR):
        auth.signup_direct(f"person{i}", "P", "tyre-wall-9", "9.9.9.9")
    with pytest.raises(auth.AuthError, match="Too many"):
        auth.signup_direct("one-more", "P", "tyre-wall-9", "9.9.9.9")
