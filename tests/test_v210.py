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


# --------------------------------------------------------------------------- team orders removed + change notices

def _orders_league(master_client):
    import random
    from f1tracker import market, relations, teamlife
    from f1tracker import constants as C
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        S.place_players(conn, sid, {a: (cad, 2), b: (cad, 1)})
        market.open_window(conn, sid, rng=random.Random(1))
        for did, role in ((a, "No. 2"), (b, "No. 1")):
            offer = [o for o in market.offers(conn, driver_id=did) if o["status"] == C.OFFER_PENDING][0]
            conn.execute("UPDATE offers SET team_id = ?, role = ? WHERE id = ?", (cad, role, offer["id"]))
            market.accept_offer(conn, offer["id"])
        S.place_players(conn, sid, {a: (cad, 2), b: (cad, 1)})
        relations.ensure(conn, sid)
        storage.set_meta(conn, "team_orders", "on")

        class Low(random.Random):
            def random(self):
                return 0.0
        assert teamlife.issue_orders(conn, sid, rng=Low()) == [a]
        ev = S.next_incomplete_event(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
        run_event(conn, ev, order=[a, b] + [d for d in ids if d not in (a, b)])
        assert teamlife.resolve_orders(conn, ev["id"]) == [(a, "Ignored")]
        assert relations.assess(conn, sid, a)["bonus"] == C.TEAM_ORDER_IGNORED
    pledge_all(token)
    return token, a, b


def test_switching_orders_off_removes_them_undoes_the_penalty_and_asks_the_driver(app, master_client):
    from f1tracker import impacts, relations, teamlife
    token, a, b = _orders_league(master_client)
    ana = _client(app, "ana")
    assert ana.get(f"/career/{token}/dashboard").status_code == 200          # nothing to agree to yet
    master_client.post(f"/career/{token}/settings", data={"csrf_token": "tok", "team_life": "1", "team_orders": "off",
                                                          "weekend_targets": "1", "difficulty_recs": "1"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        assert teamlife.orders_for(conn, sid, a) == [] and relations.assess(conn, sid, a)["bonus"] == 0
        assert not conn.execute("SELECT 1 FROM team_notes WHERE text LIKE '%team order%'").fetchone()
        notice = impacts.pending(conn, a, "ana")[0]
        rel = next(c for c in notice["changes"] if c["stat"] == "relationship")
        assert rel["change"] > 0 and any("Penalty for ignoring 1 team order undone" in d for d in notice["details"])
    # The driver can't use the league until they agree; the Race Master isn't held up.
    res = ana.get(f"/career/{token}/dashboard")
    assert res.status_code == 302 and res.headers["Location"].endswith(f"/career/{token}/changes")
    page = ana.get(f"/career/{token}/changes").get_data(as_text=True)
    assert "Team orders removed" in page and "Team relationship" in page and "I agree" in page
    assert master_client.get(f"/career/{token}/dashboard").status_code == 200
    ana.post(f"/career/{token}/changes", data={"csrf_token": "tok"})              # box not ticked
    assert ana.get(f"/career/{token}/dashboard").status_code == 302
    ana.post(f"/career/{token}/changes", data={"csrf_token": "tok", "agree": "1"})
    assert ana.get(f"/career/{token}/dashboard").status_code == 200
    assert "Agreed by: ana" in master_client.get(f"/career/{token}/changes").get_data(as_text=True)


def test_updating_to_2_1_removes_old_orders_in_leagues_where_they_are_off(app, master_client):
    from f1tracker import impacts
    token, a, b = _orders_league(master_client)
    with storage.session(token) as conn:
        storage.set_meta(conn, "team_orders", "off")            # an old league: orders off, but old ones still there
        storage.set_meta(conn, "calc_version", "0")
        conn.execute("DELETE FROM impact_notices") if conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'impact_notices'").fetchone() else None
        assert conn.execute("SELECT COUNT(*) FROM team_orders").fetchone()[0] == 1
    master_client.get(f"/career/{token}/dashboard")                  # the first visit after the update
    with storage.session(token) as conn:
        assert conn.execute("SELECT COUNT(*) FROM team_orders").fetchone()[0] == 0
        assert [n["title"] for n in impacts.pending(conn, a, "ana")] == ["Team orders removed"]
        assert storage.get_meta(conn, "calc_version") == "1"


def test_formula_changes_are_explained_only_when_the_old_numbers_are_trustworthy(app, master_client, monkeypatch):
    import json
    from f1tracker import impacts
    from f1tracker import constants as C
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        S.place_players(conn, sid, {a: (1, 1)})
        run_event(conn, S.events(conn, sid)[0])
    master_client.get(f"/career/{token}/dashboard")                  # kept numbers are fresh now
    monkeypatch.setattr(C, "CALC_VERSION", 2)
    monkeypatch.setitem(impacts.CALC_NOTES, 2, ("Test", "Reputation is now worked out differently."))
    with storage.session(token) as conn:
        kept = json.loads(storage.get_meta(conn, "calc_snapshot"))
        kept[str(a)]["reputation"] = kept[str(a)]["reputation"] - 3         # what the old version said
        storage.set_meta(conn, "calc_snapshot", json.dumps(kept))
    master_client.get(f"/career/{token}/dashboard")
    with storage.session(token) as conn:
        n = impacts.pending(conn, a, "ana")
        assert n and n[0]["why"] == "Reputation is now worked out differently."
        assert [c["stat"] for c in n[0]["changes"]] == ["reputation"] and n[0]["changes"][0]["change"] == 3
    # Stale numbers (something was saved after they were taken) are never blamed on an update.
    monkeypatch.setattr(C, "CALC_VERSION", 3)
    monkeypatch.setitem(impacts.CALC_NOTES, 3, ("Test", "Another change."))
    with storage.session(token) as conn:
        kept = json.loads(storage.get_meta(conn, "calc_snapshot"))
        kept[str(a)]["form"] = kept[str(a)]["form"] - 5
        storage.set_meta(conn, "calc_snapshot", json.dumps(kept))
        impacts.mark_stale(conn)
    master_client.get(f"/career/{token}/dashboard")
    with storage.session(token) as conn:
        assert len(impacts.pending(conn, a, "ana")) == 1


# --------------------------------------------------------------------------- round gates on later rounds

import pytest  # noqa: E402


@pytest.mark.gates
def test_a_round_further_ahead_is_never_shown_as_ready(app, master_client):
    from f1tracker import gates, teamlife
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        S.place_players(conn, sid, {a: (1, 1)})
        evs = S.events(conn, sid)
        run_event(conn, evs[0])
        for q in teamlife.questions_for(conn, evs[0]["id"], a):          # R1 press answered
            teamlife.answer(conn, evs[0]["id"], a, q["key"], q["answers"][0]["key"])
        later = gates.status(conn, evs[3]["id"])
        assert later.get("future") and not later["active"] and not later["blocking"]
        assert later["future"]["next"]["id"] == evs[1]["id"]
    page = master_client.get(f"/career/{token}/weekend/{evs[3]['id']}").get_data(as_text=True)
    assert "isn&#39;t next yet" in page or "isn't next yet" in page
    assert "is ready to start" not in page


# --------------------------------------------------------------------------- changelog agreement

def test_whats_new_must_be_agreed_to_in_the_browser(app, master_client, live_server):
    from conftest import open_browser
    from f1tracker import whatsnew
    from f1tracker import constants as C
    with auth.accounts() as conn:                        # an account from before the update
        conn.execute("DELETE FROM whats_new_seen WHERE username = 'david'")
    pw, browser = open_browser()
    try:
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.goto(live_server + "/login")
        page.fill("input[name=username]", "david")
        page.fill("input[name=password]", "password1")
        page.press("input[name=password]", "Enter")
        page.wait_for_load_state()
        dialog = page.locator("#whats-new")
        assert dialog.is_visible()
        go = page.locator("[data-wn-continue]")
        assert go.is_disabled()
        page.keyboard.press("Escape")
        assert dialog.is_visible()                      # can't be dismissed without agreeing
        page.check("[data-wn-agree]")
        assert go.is_enabled()
        go.click()
        page.wait_for_function("!document.getElementById('whats-new').open")
        assert whatsnew.acknowledged("david", C.APP_VERSION)
    finally:
        browser.close()
        pw.stop()


# --------------------------------------------------------------------------- Race Master goal controls

def test_race_master_can_reset_reopen_and_repush_team_goals(app, master_client):
    from f1tracker import teamgoals
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        S.place_players(conn, sid, {a: (1, 1)})
        teamgoals.set_enabled(conn, True)
        team = S.driver_seats(conn, sid)[a][0]
        teamgoals.choose(conn, sid, team, "competitive", "ana")
        run_event(conn, S.events(conn, sid)[0])                           # now locked
        conn.execute("UPDATE team_goal_choices SET target_points = 1")      # stale numbers
    pledge_all(token)
    ana = _client(app, "ana")
    assert ana.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "action": "reopen"}).status_code == 403
    master_client.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "action": "repush"})
    with storage.session(token) as conn:
        g = teamgoals.choice(conn, sid, team)
        assert g["tier"] == "competitive" and g["target_points"] > 1
    master_client.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "action": "reopen"})
    with storage.session(token) as conn:
        assert teamgoals.choice(conn, sid, team) is None and not teamgoals.locked(conn, sid, team)
        assert conn.execute("SELECT 1 FROM notifications WHERE text LIKE '%reset%team goal%'").fetchone()
    ana.post(f"/career/{token}/team-goals/{team}", data={"csrf_token": "tok", "tier": "safe"})   # mid-season, reopened
    with storage.session(token) as conn:
        assert teamgoals.choice(conn, sid, team)["tier"] == "safe"
        assert teamgoals.locked(conn, sid, team)                            # locks again once chosen


def test_race_master_can_reissue_season_goals_and_the_next_target(app, master_client):
    from f1tracker import impacts, relations, teamlife
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a, b = players(conn)
        S.place_players(conn, sid, {a: (1, 1), b: (2, 1)})
        relations.ensure(conn, sid)
        conn.execute("UPDATE team_goals SET label = 'old goal', target = 99 WHERE driver_id = ?", (a,))
        ev = S.next_incomplete_event(conn, sid)
        teamlife.issue_targets(conn, ev["id"])
        teamlife.acknowledge(conn, ev["id"], a)
    pledge_all(token)
    ana = _client(app, "ana")
    assert ana.post(f"/career/{token}/team-standing/{a}/goals", data={"csrf_token": "tok", "action": "reissue"}).status_code == 403
    master_client.post(f"/career/{token}/team-standing/{a}/goals", data={"csrf_token": "tok", "action": "reissue"})
    with storage.session(token) as conn:
        labels = [r["label"] for r in conn.execute("SELECT label FROM team_goals WHERE driver_id = ?", (a,))]
        assert "old goal" not in labels and labels
        n = impacts.pending(conn, a, "ana")
        assert n and n[0]["title"] == "Season goals re-issued"
        assert not impacts.pending(conn, b, "anyone")                      # only the driver it was for
    master_client.post(f"/career/{token}/team-standing/{a}/goals", data={"csrf_token": "tok", "action": "retarget"})
    with storage.session(token) as conn:
        t = teamlife.target_for(conn, ev["id"], a)
        assert t and t["acknowledged_at"] is None                          # has to be accepted again
    page = master_client.get(f"/career/{token}/team-standing?driver={a}").get_data(as_text=True)
    assert "Re-issue season goals" in page and "Re-issue for everyone" in page


# --------------------------------------------------------------------------- team talks

def test_messages_are_read_for_themes_tone_and_negation():
    from f1tracker import pitch
    r = pitch.analyse("I'd love to build a long-term project with you and keep learning from your engineers. "
                      "Last season I scored points consistently.")
    assert {"commitment", "development", "record"} <= set(r["themes"]) and not r["arrogant"]
    assert "commitment" not in pitch.analyse("I don't want to stay long term anywhere")["themes"]
    rude = pitch.analyse("I'm the best driver on the grid and I deserve your seat. My car was rubbish!!!")
    assert rude["arrogant"] and rude["blame"] and rude["shouting"]
    taste = {"tier": "back", "weights": pitch.TASTES["back"], "favourite": "development"}
    assert pitch.score(r, taste) > 0.5 > pitch.score(rude, taste)
    assert pitch.score(pitch.analyse("hi"), taste) == 0.0             # too short to mean anything


def _approach_at(conn, mp, value_gap, message, interview=None):
    """Approach a mid-grid team with the driver's value set so interest = value_gap before the message."""
    import random
    from f1tracker import market
    sid = S.current_season_id(conn)
    a = players(conn)[0]
    ranks = S.team_strength_ranks(conn, sid)
    team = next(t for t, r in ranks.items() if r == 6)
    wid = market.open_window(conn, sid, rng=random.Random(2))
    conn.execute("DELETE FROM offers WHERE driver_id = ? AND team_id = ?", (a, team))
    mp.setattr(market, "JITTER", 0.0)
    mp.setattr(market, "experience", lambda c, d: "Experienced")
    real = market.driver_value
    mp.setattr(market, "driver_value", lambda *args: {**real(*args), "value": market.team_bar(6) + value_gap})
    return market.approach_team(conn, wid, a, team, message=message, rng=random.Random(3), interview=interview)


def test_a_good_pitch_tips_a_team_on_the_edge_but_never_a_hopeless_case(app, master_client, monkeypatch):
    from f1tracker import pitch
    good = ("It would be an honour. I want to commit long term, keep developing with your engineers and put the "
            "team first. Last season I scored points consistently and beat my teammate.")
    results = {}
    for label, gap, msg in (("edge_quiet", -7, ""), ("edge_good", -7, good), ("hopeless", -15, good)):
        token = _league(master_client, name=f"Talks {label}")
        with storage.session(token) as conn, monkeypatch.context() as mp:
            S.place_players(conn, S.current_season_id(conn), {players(conn)[0]: (11, 1)})
            iv = {"bonus": pitch.INTERVIEW_MAX, "summary": "Great interview."} if label == "hopeless" else None
            results[label] = _approach_at(conn, mp, gap, msg, iv)[1]
    assert results["edge_quiet"] == "rejected"
    assert results["edge_good"] in ("trial", "offer")
    assert results["hopeless"] == "rejected"                        # even with the best message and interview


def test_interview_page_uses_an_approach_and_weighs_the_record(app, master_client):
    import random
    from f1tracker import market, pitch
    auth.create_user("ana", "Ana", "password1")
    token = _league(master_client)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players(conn)[0]
        S.place_players(conn, sid, {a: (11, 1)})
        wid = market.open_window(conn, sid, rng=random.Random(5))
        team = market.approachable_teams(conn, wid, a)[-1]["id"]
        before = market.approaches_left(conn, wid, a)
        qs = pitch.interview_questions(conn, wid, a, team)
        assert qs == pitch.interview_questions(conn, wid, a, team) and len(qs) == 4   # stable on refresh
    pledge_all(token)
    ana = _client(app, "ana")
    page = ana.get(f"/career/{token}/offers/interview/{team}").get_data(as_text=True)
    assert qs[0]["text"] in page and "The goal you" in page
    form = {"csrf_token": "tok", "goal": "develop", **{f"q{q['id']}": q["answers"][0]["id"] for q in qs}}
    ana.post(f"/career/{token}/offers/interview/{team}", data=form)
    with storage.session(token) as conn:
        assert market.approaches_left(conn, wid, a) == before - 1
        msgs = [m["message"] for m in conn.execute(
            "SELECT m.message FROM offer_messages m JOIN offers o ON o.id = m.offer_id WHERE o.team_id = ? AND o.driver_id = ?",
            (team, a))]
        assert any("Interview" in m for m in msgs) and any("interview" in m.lower() for m in msgs[1:])
    # A bluff: a podium goal that the record doesn't back up counts against you.
    record = {"year": 2026, "rounds": 10, "avg": 18.0, "points_rate": 0.0, "podiums": 0}
    assert pitch._goal_realism("podiums", record) == -1 and pitch._goal_realism("top_half", {**record, "avg": 7}) == 1
