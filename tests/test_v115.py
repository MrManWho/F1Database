"""v1.15: required pledges, re-based targets, goals, press pen, team orders, incidents, Discord, restore, help."""

import random
import sqlite3

import pytest

from conftest import driver_id, login, players, pledge_all, run_event
from f1tracker import (auth, community, discord, feed, market, relations, services as S, storage, teamlife)
from f1tracker import constants as C


def _league(master_client, **extra):
    auth.create_user("ana", "Ana", "password1")
    auth.create_user("ben", "Ben", "password1")
    res = master_client.post("/careers/new", data={"name": "V15", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
                                                   "player_login": ["ana", "ben"], "csrf_token": "tok", **extra})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        a, b = players(conn)
        S.place_players(conn, sid, {a: (cad, 1), b: (cad, 2)})
    return token, a, b


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def test_seated_drivers_must_pledge_before_carrying_on(app, master_client):
    token, a, b = _league(master_client)
    ana = _client(app, "ana")
    res = ana.get(f"/career/{token}/dashboard")
    assert res.status_code == 302 and res.headers["Location"].endswith(f"/career/{token}/pledge")
    assert ana.post(f"/career/{token}/comments", data={"target": "event:1", "body": "x", "csrf_token": "tok"}).status_code == 302
    page = ana.get(f"/career/{token}/pledge").get_data(as_text=True)
    assert "Choose your growth pledge" in page and "Breakout" in page and "Lock in my pledge" in page
    assert ana.get("/help").status_code == 200  # help is always reachable
    ana.post(f"/career/{token}/pledge", data={"growth": "2", "csrf_token": "tok"})
    assert ana.get(f"/career/{token}/dashboard").status_code == 200
    with storage.session(token) as conn:
        rel = relations.assess(conn, S.current_season_id(conn), a)
    assert rel["pledged"] == 1 and rel["level"]["name"] == "Strong"
    # Locked in: can't quietly lower it.
    ana.post(f"/career/{token}/pledge", data={"growth": "0", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert relations.assess(conn, S.current_season_id(conn), a)["growth"] == 2
    # The Race Master (not a driver here) is never gated, and can ask for a new pledge.
    assert master_client.get(f"/career/{token}/dashboard").status_code == 200
    master_client.post(f"/career/{token}/team-standing/{a}/request-pledge", data={"csrf_token": "tok"})
    assert ana.get(f"/career/{token}/garage").status_code == 302
    ana.post(f"/career/{token}/pledge", data={"growth": "1", "csrf_token": "tok"})
    assert ana.get(f"/career/{token}/garage").status_code == 200
    # "Ask everyone" resets both players.
    master_client.post(f"/career/{token}/team-standing/{a}/request-pledge", data={"all": "1", "csrf_token": "tok"})
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        assert relations.needs_pledge(conn, sid, a) and relations.needs_pledge(conn, sid, b)


def test_v11_relationships_without_a_pledge_are_flagged(career, rng):
    with storage.session(career) as conn:
        sid = S.current_season_id(conn)
        david, carson = players(conn)
        market.open_window(conn, sid, rng=rng)
        offer = market.offers(conn, driver_id=david)[0]
        market.accept_offer(conn, offer["id"])
        cad = conn.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
        S.place_players(conn, sid, {carson: (cad, 1)})
        relations.ensure(conn, sid)
    raw = sqlite3.connect(str(storage.career_path(career)))
    for col in ("pledged", "rebased", "bonus"):
        raw.execute(f"ALTER TABLE team_relations DROP COLUMN {col}")
    raw.execute("DROP TABLE incidents")
    raw.execute("UPDATE meta SET value = '11' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()
    with storage.session(career) as conn:
        assert not relations.needs_pledge(conn, sid, david)   # signed with a pledge
        assert relations.needs_pledge(conn, sid, carson)      # placed by hand, no contract


def test_targets_rebase_after_three_rounds(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(db, sid, {david: (cad, 1), carson: (cad, 2)})
    relations.ensure(db, sid)
    before = relations.assess(db, sid, david)["form_base"]
    evs = S.events(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, evs[0]["id"])]
    # Cadillac's AI... there is none (both players), so make Cadillac's car look quick by points from other teams? Instead
    # use the default: reversing the grid makes the old backmarkers' AI score big.
    order = list(reversed([d for d in ids if d not in (david, carson)])) + [david, carson]
    for ev in evs[:3]:
        run_event(db, ev, order=order)
        relations.review(db, sid)
    a = relations.assess(db, sid, david)
    assert a["rebased"] == 1
    ranks = S.team_strength_ranks(db, sid)
    assert a["form_base"] == relations.car_baseline_form(ranks[cad])
    if abs(a["form_base"] - before) >= 1:
        assert any("re-set your targets" in n["text"] for n in relations.notes(db, sid, david))


def test_goals_track_progress(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    S.place_players(db, sid, {david: (1, 1), carson: (1, 2)})
    relations.ensure(db, sid)
    goals = relations.assess(db, sid, david)["goals"]
    kinds = {g["kind"]: g for g in goals}
    assert {"points", "championship", "teammate"} <= set(kinds)
    assert kinds["championship"]["target"] <= 5  # a top car is expected near the front
    evs = S.events(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, evs[0]["id"])]
    order = [david] + [d for d in ids if d != david]
    for ev in evs[:4]:
        run_event(db, ev, order=order)
    goals = {g["kind"]: g for g in relations.assess(db, sid, david)["goals"]}
    assert goals["points"]["state"] in ("On track", "Met") and goals["teammate"]["state"] == "On track"
    loser = {g["kind"]: g for g in relations.assess(db, sid, carson)["goals"]}
    assert loser["teammate"]["state"] == "Behind"


def test_press_pen_answers_move_the_relationship(app, master_client):
    token, a, b = _league(master_client)
    pledge_all(token)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        evs = S.events(conn, sid)
        ids = [r["driver_id"] for r in S.weekend_rows(conn, evs[0]["id"])]
        order = [a] + [d for d in ids if d not in (a, b)] + [b]
        run_event(conn, evs[0], order=order, quali=list(reversed(order)))
        teamlife.after_race(conn, evs[0]["id"])
        pen = teamlife.press_pen(conn, sid, a)
    assert [q["key"] for q in pen["questions"]] == ["credit", "beat_mate"]
    ana = _client(app, "ana")
    dash = ana.get(f"/career/{token}/dashboard").get_data(as_text=True)
    assert "Press pen" in dash and "Who deserves the credit?" in dash
    ana.post(f"/career/{token}/press/{evs[0]['id']}", data={"question": "credit", "answer": "me", "csrf_token": "tok"})
    ana.post(f"/career/{token}/press/{evs[0]['id']}", data={"question": "credit", "answer": "team", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert relations.assess(conn, sid, a)["bonus"] == -2
        assert any("That was all me" in n["headline"] for n in feed.latest(conn, 5))
        # A new race closes the old press pen.
        run_event(conn, evs[1], order=order)
        teamlife.after_race(conn, evs[1]["id"])
        with pytest.raises(S.ValidationError, match="moved on"):
            teamlife.answer(conn, evs[0]["id"], a, "beat_mate", "push")
        # Ben finished last: a different question.
        assert teamlife.press_pen(conn, sid, b)["questions"][0]["key"] == "wrong"


def test_team_orders_for_number_two_drivers(db):
    sid = S.current_season_id(db)
    david, carson = players(db)
    cad = db.execute("SELECT id FROM teams WHERE name = 'Cadillac'").fetchone()["id"]
    S.place_players(db, sid, {david: (cad, 1), carson: (cad, 2)})
    market.open_window(db, sid, rng=random.Random(1))
    for did in (david, carson):
        offer = [o for o in market.offers(db, driver_id=did) if o["status"] == C.OFFER_PENDING][0]
        db.execute("UPDATE offers SET team_id = ?, role = ? WHERE id = ?", (cad, "No. 2" if did == carson else "No. 1",
                                                                          offer["id"]))
        market.accept_offer(db, offer["id"])
    S.place_players(db, sid, {david: (cad, 1), carson: (cad, 2)})
    relations.ensure(db, sid)
    assert relations.assess(db, sid, carson)["role"] == "No. 2"
    issued = teamlife.issue_orders(db, sid, rng=random.Random(0))  # 0.84 > chance? force with a low roll instead
    if not issued:
        class Low(random.Random):
            def random(self):
                return 0.0
        issued = teamlife.issue_orders(db, sid, rng=Low())
    assert issued == [carson]
    ev = S.next_incomplete_event(db, sid)
    ids = [r["driver_id"] for r in S.weekend_rows(db, ev["id"])]
    order = [carson, david] + [d for d in ids if d not in (carson, david)]
    run_event(db, ev, order=order)
    assert teamlife.resolve_orders(db, ev["id"]) == [(carson, "Ignored")]
    rel = relations.assess(db, sid, carson)
    assert rel["bonus"] == C.TEAM_ORDER_IGNORED
    assert any("defies team orders" in n["headline"] for n in feed.latest(db, 5))
    assert teamlife.orders_for(db, sid, carson)[0]["status"] == "Ignored"


def test_incident_reports_and_rulings(app, master_client):
    token, a, b = _league(master_client)
    pledge_all(token)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
    ana = _client(app, "ana")
    ana.post(f"/career/{token}/weekend/{ev['id']}/incident", data={"accused_id": a, "description": "me", "csrf_token": "tok"})
    ana.post(f"/career/{token}/weekend/{ev['id']}/incident",
             data={"accused_id": b, "description": "Lap 1, Turn 1: divebomb", "csrf_token": "tok"})
    with storage.session(token) as conn:
        rows = community.incidents(conn)
    assert len(rows) == 1 and rows[0]["accused"]["id"] == b and rows[0]["status"] == "Open"
    assert "divebomb" in ana.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert ana.post(f"/career/{token}/incidents/{rows[0]['id']}/rule",
                    data={"ruling": "warning", "csrf_token": "tok"}).status_code == 403
    master_client.post(f"/career/{token}/incidents/{rows[0]['id']}/rule",
                       data={"ruling": "warning", "note": "Avoidable contact", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert community.incidents(conn)[0]["ruling"] == "warning"
        assert any("Ben Okafor given a warning" in n["headline"] for n in feed.latest(conn, 5))
    page = ana.get(f"/career/{token}/rivalry?a={a}&b={b}").get_data(as_text=True)
    assert "Incidents between them" in page and "Avoidable contact" in page
    assert "Incidents" in ana.get(f"/career/{token}/incidents").get_data(as_text=True)


def test_discord_is_optional_and_validated(app, master_client, monkeypatch):
    token, a, b = _league(master_client)
    with storage.session(token) as conn:
        assert discord.settings(conn)["url"] == ""
    master_client.post(f"/career/{token}/settings", data={"discord_webhook": "https://evil.example.com/x", "csrf_token": "tok"})
    with storage.session(token) as conn:
        assert discord.settings(conn)["url"] == ""
    url = "https://discord.com/api/webhooks/123/abc-DEF"
    master_client.post(f"/career/{token}/settings", data={"discord_webhook": url, "discord_results": "1", "csrf_token": "tok"})
    with storage.session(token) as conn:
        cfg = discord.settings(conn)
        assert cfg == {"url": url, "results": True, "news": False}
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
        msg = discord.results_message(conn, ev["id"], "V15")
    assert msg.startswith("🏁 **V15 · R1") and "🥇" in msg and "Ana Silva" in msg
    sent = []
    monkeypatch.setattr(discord, "post", lambda u, content: sent.append((u, content)) or True)
    master_client.post(f"/career/{token}/settings/discord-test", data={"csrf_token": "tok"})
    assert sent and sent[0][0] == url and "connected" in sent[0][1]
    # Headlines are queued per league (race-result stories are left to the summary).
    discord.take()
    with storage.session(token) as conn:
        feed.post(conn, S.current_season_id(conn), "market", "Big signing", "body")
        feed.post(conn, S.current_season_id(conn), "result", "Race won", "")
    queued = discord.take()
    assert [m for _t, m in queued] == ["📰 **Big signing**\nbody"]


def test_restore_rolls_back_and_can_be_undone(master_client, data_dir):
    token, a, b = _league(master_client)
    backup = storage.auto_backup(token, "test", force=True)
    with storage.session(token) as conn:
        conn.execute("UPDATE drivers SET name = 'Changed Name' WHERE id = ?", (a,))
    master_client.post(f"/career/{token}/autobackup/{backup.name}/restore", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert S.driver_map(conn)[a]["name"] == "Ana Silva"
        assert storage.get_meta(conn, "career_id") == token
    names = [b["name"] for b in storage.list_auto_backups(token)]
    assert any("before-restore" in n for n in names)
    undo = next(n for n in names if "before-restore" in n)
    master_client.post(f"/career/{token}/autobackup/{undo}/restore", data={"csrf_token": "tok"})
    with storage.session(token) as conn:
        assert S.driver_map(conn)[a]["name"] == "Changed Name"
    bad = data_dir / "bad.f1career"
    bad.write_bytes(b"not a database")
    with pytest.raises(ValueError):
        storage.restore(token, bad)


def test_help_value_breakdown_and_share_card(app, master_client):
    token, a, b = _league(master_client)
    pledge_all(token)
    with storage.session(token) as conn:
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
    help_page = master_client.get("/help").get_data(as_text=True)
    for anchor in ("driver-value", "pledges", "relationship", "goals", "orders", "press", "incidents"):
        assert f'id="{anchor}"' in help_page
    ana = _client(app, "ana")
    garage = ana.get(f"/career/{token}/garage").get_data(as_text=True)
    assert "Where your Driver Value comes from" in garage and "Next team up" in garage
    week = ana.get(f"/career/{token}/weekend/{ev['id']}").get_data(as_text=True)
    assert 'id="share-card"' in week and "Ana Silva" in week.split("data-card=")[1][:600]
    standing = ana.get(f"/career/{token}/team-standing").get_data(as_text=True)
    assert "Season goals" in standing and "Team orders" in standing
