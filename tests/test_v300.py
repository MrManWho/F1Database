"""v3.0: backup scrubbing, relationship and pitch balance, rollover rewards, the AI benchmark fallback, truthful Help
and press history, accessibility names, navigation and What's New eras."""

import sqlite3

import pytest

from conftest import login, run_event
from f1tracker import community, discord, storage, services as S


def _league(master_client, name="Three League"):
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "join_mode": "invite"})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


# --------------------------------------------------------------------------- PL-SEC-01

def _secrets_leaked(raw, values):
    return [v for v in values if v.encode() in raw]


def _no_secure_delete(monkeypatch):
    """Behave like SQLite builds whose secure_delete is off by default (deleted bytes stay in the file)."""
    real = sqlite3.connect

    def connect(*args, **kwargs):
        conn = real(*args, **kwargs)
        conn.execute("PRAGMA secure_delete = OFF")
        return conn
    monkeypatch.setattr(storage.sqlite3, "connect", connect)


def test_downloaded_backups_hold_no_trace_of_any_secret(app, master_client, monkeypatch):
    token = _league(master_client)
    _no_secure_delete(monkeypatch)
    old_hook = "https://discord.com/api/webhooks/111/OLD-" + "a" * 40
    new_hook = "https://discord.com/api/webhooks/222/NEW-" + "b" * 40
    path = storage.career_path(token)
    with storage.session(token) as conn:
        discord.save_settings(conn, old_hook, True, True)
    with storage.session(token) as conn:
        discord.save_settings(conn, new_hook, True, True)     # the old value is left behind in the live file
        key = community.public_key(conn)
        assert set(storage.SECRET_META) <= {r[0] for r in conn.execute("SELECT key FROM meta")}
    values = [old_hook.split("/")[-1], new_hook.split("/")[-1], key]
    current = master_client.get(f"/career/{token}/backup").get_data()
    assert current[:16] == b"SQLite format 3\x00" and not _secrets_leaked(current, values)
    auto = storage.auto_backup(token, "test", force=True)
    listed = master_client.get(f"/career/{token}/autobackup/{auto.name}").get_data()
    assert listed[:16] == b"SQLite format 3\x00" and not _secrets_leaked(listed, values)
    with storage.session(token) as conn:                     # the league itself keeps them
        assert storage.get_meta(conn, "discord_webhook") == new_hook
    tmp = storage.data_dir() / "scrub-check.f1career"
    tmp.write_bytes(storage.redacted_copy(path))
    check = sqlite3.connect(str(tmp))
    assert not check.execute(f"SELECT key FROM meta WHERE key IN ({','.join('?' * len(storage.SECRET_META))})",
                             tuple(storage.SECRET_META)).fetchall()
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()
    tmp.unlink()


# --------------------------------------------------------------------------- PL-BAL-01: relationship extras

from f1tracker import constants as C, impacts, pitch, press, relations, teamlife   # noqa: E402
from test_v250 import _league as _v3_league, _mate, _order   # noqa: E402

v3 = pytest.mark.engine3
BEST_POST = max(((q, a[0]) for q, (_t, ans) in press.POST.items() for a in ans),
                key=lambda qa: press.effect_v3(qa[0], qa[1], next(x[2] for x in press.POST[qa[0]][1] if x[0] == qa[1])))


def _best_press(conn, ev, driver_id, n=4):
    q, a = BEST_POST
    stored = next(x[2] for x in press.POST[q][1] if x[0] == a)
    for i in range(n):          # four answers a weekend, each the most team-friendly one there is
        conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                     "VALUES(?,?,?,?,?,?)", (ev["id"], driver_id, f"{q}" if i == 0 else f"{q}#{i}", a, stored,
                                             storage.now_iso()))


def _weekend(conn, ev, a, finish, mate_finish, tier="safe"):
    teamlife.save_settings(conn, "off", True, False, False, False)
    teamlife.issue_targets(conn, ev["id"])
    teamlife.choose_target(conn, ev["id"], a, tier)
    sid = ev["season_id"]
    run_event(conn, ev, order=_order(conn, ev, {a: finish, _mate(conn, sid, a): mate_finish}))
    from conftest import after_submit
    after_submit(conn, ev)
    _best_press(conn, ev, a)


@v3
def test_good_press_adds_at_most_two_and_bad_press_counts_in_full():
    token = _v3_league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        team = S.driver_seats(conn, sid)[a][0]
        for ev in S.events(conn, sid)[:3]:
            run_event(conn, ev)
            _best_press(conn, ev, a)
        extras, items = relations.extras_v3(conn, sid, a, team)
        assert sum(i[1] for i in items if i[2] == "press") >= 6          # far more was answered...
        assert relations.extras_breakdown(items)["press"] == C.V3_PRESS_POSITIVE_CAP    # ...only +2 counts
        ev = S.events(conn, sid)[3]
        run_event(conn, ev)
        conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                     "VALUES(?,?,?,?,?,?)", (ev["id"], a, "win", "me", -2, storage.now_iso()))
        extras2, items2 = relations.extras_v3(conn, sid, a, team)
        assert relations.extras_breakdown(items2)["press"] == C.V3_PRESS_POSITIVE_CAP - 1.0   # -2 x 50%, in full


def players_ids(conn):
    return [p["id"] for p in S.player_drivers(conn)]


@v3
def test_safe_targets_and_perfect_press_do_not_keep_an_average_driver_delighted():
    token = _v3_league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        relations.set_pledge(conn, sid, a, 0)                  # Steady: deliver what the car should
        evs = S.events(conn, sid)[:6]
        for i, ev in enumerate(evs):                           # at the car's level, teammate battle split
            _weekend(conn, ev, a, 11 if i % 2 else 12, 12 if i % 2 else 11)
        rel = relations.assess(conn, sid, a)
        split = rel["extras_split"]
        assert split["press"] <= C.V3_PRESS_POSITIVE_CAP and split["weekend target"] <= 6 * 0.25
        assert rel["bonus"] <= C.V3_PRESS_POSITIVE_CAP + 6 * C.V3_TARGET_TIERS["safe"][0]
        assert rel["status"] != "Delighted" and rel["score"] < 70


@v3
def test_optimal_off_track_choices_cannot_rescue_a_clear_underperformer():
    token = _v3_league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        relations.set_pledge(conn, sid, a, 0)
        for ev in S.events(conn, sid)[:6]:                     # 3+ places behind the pledge, beaten by the teammate
            _weekend(conn, ev, a, 16, 9)
        rel = relations.assess(conn, sid, a)
        assert rel["status"] in ("Concerned", "Unhappy", "Seat at risk"), rel["score"]


def test_riskier_targets_pay_more_for_a_driver_at_or_above_the_car():
    """Expected relationship change per weekend for a driver whose finishes scatter +/-3.5 places around
    (car level - offset): Safe only wins below the car, Standard at or above it, Stretch well above it."""
    from statistics import NormalDist
    def ev(offset, tier):
        hit, miss = C.V3_TARGET_TIERS[tier]
        gap = {"safe": 3, "standard": 0, "stretch": -3}[tier]
        p = NormalDist(-offset, 3.5).cdf(gap)
        return p * hit + (1 - p) * miss
    best = {o: max(C.V3_TARGET_TIERS, key=lambda t: ev(o, t)) for o in (-3, 0, 1.5, 3, 5)}
    assert best == {-3: "safe", 0: "standard", 1.5: "standard", 3: "standard", 5: "stretch"}
    assert ev(-3, "safe") < 0          # nothing is free for a driver below the car


# --------------------------------------------------------------------------- PL-BAL-02: pitch messages

UNIVERSAL = ("I want to win races, learn from the engineers, stay loyal to this project, help the team, respect your "
             "history, and my last season proved my record.")


def _all_tastes():
    for tier in pitch.TASTES:
        for fav in pitch.THEMES:
            w = dict(pitch.TASTES[tier])
            w[fav] = w.get(fav, 0.3) + 0.6
            yield {"tier": tier, "weights": w, "favourite": fav}


@pytest.mark.parametrize("message", [
    UNIVERSAL,
    "Win win win. I will learn and learn, stay loyal, help the team, I respect your history and last season was good.",
    "I want to help the team, respect your history, learn from the engineers, win races and stay loyal to the project.",
])
def test_a_message_listing_every_theme_is_worth_less_than_half(message):
    reading = pitch.analyse(message)
    assert len(reading["themes"]) > pitch.STUFFING_THEMES
    for t in _all_tastes():
        assert pitch.score(reading, t, v3=True) * pitch.PITCH_MAX <= pitch.PITCH_MAX / 2


def test_a_targeted_message_beats_the_universal_one_for_the_team_it_suits():
    targeted = {"back": "I want to develop with your engineers and I will commit long term to this project.",
                "top": "I want to win races and I will always help the team get the constructors points.",
                "mid": "I want to score points and win, and I will stay loyal to this project for years."}
    universal = pitch.analyse(UNIVERSAL)
    for t in _all_tastes():
        mine = pitch.analyse(targeted[t["tier"]])
        assert pitch.score(mine, t, v3=True) > pitch.score(universal, t, v3=True)
    # the first two reasons you lead with count, not the two the team likes best
    r = pitch.analyse("I respect your history and I am proud to be here. I also want to win.")
    assert r["order"][:2] == ["respect", "results"] or r["order"][0] == "respect"


# --------------------------------------------------------------------------- PL-REL-01: rollover drift

def test_steady_and_safe_no_longer_lift_reputation_every_year():
    assert C.V3_PLEDGE_REWARD[0] == 0.0 and C.V3_TEAM_GOALS["safe"] == (0.5, 0.0)
    annual = C.V3_PLEDGE_REWARD[0] + C.V3_TEAM_GOALS["safe"][0]
    for perf in range(20, 91, 10):                       # 10 seasons at fixed performance, starting at 50
        rep, plain = 50.0, 50.0
        for _ in range(10):
            rep = min(100.0, max(0.0, rep + C.V3_REP_RATE * (perf - rep) + annual))
            plain = plain + C.V3_REP_RATE * (perf - plain)
        assert rep - plain <= annual / C.V3_REP_RATE      # the safest choices lift it by at most +2 (was +6)


@v3
def test_a_pledge_made_before_3_0_keeps_its_reward_and_a_new_one_uses_the_new_terms():
    token = _v3_league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        relations.set_pledge(conn, sid, a, 0)
        storage.set_meta(conn, "calc_version", "3")
        impacts._keep_pledge_terms(conn)                  # what the 3.0 update does on first open
        assert relations.pledge_reward(conn, sid, 0, a) == 0.5
        storage.set_meta(conn, "calc_version", "0")         # a brand-new league: nothing to keep
        conn.execute("DELETE FROM meta WHERE key LIKE 'pledge_terms_%'")
        impacts._keep_pledge_terms(conn)
        assert relations.pledge_reward(conn, sid, 0, a) == 0.0
        storage.set_meta(conn, "calc_version", "3")
        impacts._keep_pledge_terms(conn)
        assert relations.pledge_reward(conn, sid, 0, a) == 0.5
        relations.set_pledge(conn, sid, a, 0)             # choosing again means the new terms
        assert relations.pledge_reward(conn, sid, 0, a) == 0.0


# --------------------------------------------------------------------------- PL-CALC-01: AI benchmark fallback

from f1tracker import ai3   # noqa: E402


def _grid(spec):
    """spec: {team_id: [(driver_id, is_player, status, position), ...]}"""
    rows = []
    for team, cars in spec.items():
        for did, is_player, status, pos in cars:
            rows.append({"team_id": team, "driver_id": did, "is_player": is_player, "result_status": status,
                         "race_position": pos, "qualifying_position": pos, "sprint_status": None,
                         "sprint_position": None})
    return rows


def _evidence(rows, me=1):
    ranks = {t: t for t in {r["team_id"] for r in rows}}        # team id = car-strength rank here
    event = {"id": 999999, "round_number": 1, "year": 2026, "ai_difficulty": 85}
    token = storage.new_token()
    with storage.session(token, create=True) as conn:
        S.seed_career(conn, token, "Bench", 2026, [])
        r = next(x for x in rows if x["driver_id"] == me)
        return ai3.session_evidence(conn, event, r, rows, ranks, "gp", len(ranks))


F, D = C.STATUS_FINISHED, "DNF"


def test_ai_teammate_is_the_first_benchmark():
    ev = _evidence(_grid({5: [(1, 1, F, 12), (2, 0, F, 10)], 4: [(3, 0, F, 8)], 6: [(4, 0, F, 14)]}))
    assert ev["benchmark"] == "your AI teammate" and ev["places_vs_benchmark"] == -2 and "teammate" in ev["parts"]


def test_a_human_teammate_falls_back_to_cars_one_place_either_side():
    ev = _evidence(_grid({5: [(1, 1, F, 12), (2, 1, F, 10)], 4: [(3, 0, F, 8), (5, 0, F, 9)],
                          6: [(4, 0, F, 14), (6, 0, F, 15)]}))
    assert ev["benchmark"].startswith("AI cars one place") and ev["places_vs_benchmark"] == round(11.5 - 12, 1)


def test_human_neighbours_fall_back_two_places_then_to_the_expected_finish():
    rows = _grid({5: [(1, 1, F, 12), (2, 1, F, 10)], 4: [(3, 1, F, 8), (5, 1, F, 9)], 6: [(4, 1, F, 14), (6, 1, F, 15)],
                  3: [(7, 0, F, 6), (8, 0, F, 7)], 7: [(9, 0, F, 16), (10, 0, F, 17)]})
    ev = _evidence(rows)
    assert ev["benchmark"].startswith("AI cars two places") and "teammate" in ev["parts"]
    wider = ev["weight"]
    for r in rows:                                          # nobody nearby classified: the car's expected finish
        if r["team_id"] in (3, 7):
            r["result_status"] = D
    ev2 = _evidence(rows)
    assert ev2["benchmark"].startswith("the car's expected finish") and "teammate" in ev2["parts"]
    assert ev2["weight"] < wider                            # and it counts for less than real AI evidence


def test_the_teammate_benchmark_returns_as_soon_as_an_ai_teammate_is_classified():
    rows = _grid({5: [(1, 1, F, 12), (2, 0, D, 20)], 4: [(3, 0, F, 8)], 6: [(4, 0, F, 14)]})
    assert _evidence(rows)["benchmark"].startswith("AI cars one place")
    rows[1]["result_status"], rows[1]["race_position"] = F, 13
    assert _evidence(rows)["benchmark"] == "your AI teammate"


# --------------------------------------------------------------------------- PL-UX-01 / PL-UX-02

def test_help_teaches_the_version_3_numbers(app, master_client):
    page = master_client.get("/help").get_data(as_text=True)
    for text in ("at most +2 across the last six weekends", "within ±10", "a goal met adds +2",
                 "behind -3", "the Race Master rules whether the order was followed (+1",
                 "ignored (-2", "Safe</b> (+0.5 Reputation", "conditional emergency offer", "Version 3</span>",
                 "only the first two reasons you lead with count", "two places either side"):
        assert text in page, text
    # legacy promises are only ever labelled as Version 2
    for legacy in ("capped at ±15", "offers a last-chance deal", "Ambitious +6 / −3", "finish ahead and you ignored it"):
        i = page.index(legacy)
        assert "Version 2 leagues" in page[max(0, i - 400):i], legacy


@v3
def test_press_history_shows_what_each_answer_actually_counted_for():
    token = _v3_league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        ev = S.events(conn, sid)[0]
        run_event(conn, ev)
        for q, ans, eff in (("win", "car", 2), ("fastest", "show", 1), ("pre_track", "quali", 1)):
            conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                         "VALUES(?,?,?,?,?,?)", (ev["id"], a, q, ans, eff, storage.now_iso()))
        hist = {h["answer"]: h for h in teamlife.press_history(conn, a)}
    halved = next(h for h in hist.values() if h["original_effect"] == 2)
    assert halved["effect"] == 1.0 and halved["engine3"]
    zeroed = [h for h in hist.values() if h["original_effect"] == 1]
    assert len(zeroed) == 2 and all(h["effect"] == 0 for h in zeroed)     # re-rated to nothing under Version 3


def test_press_history_on_version_2_is_unchanged():
    token = _v3_league(engine3=False, teams=(6,))
    with storage.session(token) as conn:
        a = players_ids(conn)[0]
        ev = S.events(conn, S.current_season_id(conn))[0]
        run_event(conn, ev)
        conn.execute("INSERT INTO press_answers(event_id, driver_id, question, answer, effect, created_at) "
                     "VALUES(?,?,?,?,?,?)", (ev["id"], a, "win", "car", 2, storage.now_iso()))
        h = teamlife.press_history(conn, a)[0]
    assert h["effect"] == 2 and not h["engine3"]


# --------------------------------------------------------------------------- off-site encrypted backup

def test_site_owner_downloads_an_encrypted_backup_that_restores(app, master_client):
    from f1tracker import offsite
    token = _league(master_client, "Offsite League")
    res = master_client.post("/settings/offsite-backup", data={"csrf_token": "tok", "passphrase": "short",
                                                               "passphrase2": "short"}, follow_redirects=True)
    assert "at least 12 characters" in res.get_data(as_text=True)
    phrase = "correct horse battery staple"
    res = master_client.post("/settings/offsite-backup", data={"csrf_token": "tok", "passphrase": phrase,
                                                               "passphrase2": phrase})
    blob = res.get_data()
    assert res.status_code == 200 and blob.startswith(offsite.MAGIC)
    assert b"SQLite format 3" not in blob and b"Offsite League" not in blob          # nothing readable
    with pytest.raises(offsite.BackupError):
        offsite.decrypt(blob, "wrong passphrase!!")
    manifest = offsite.verify(offsite.decrypt(blob, phrase))
    names = {f["name"] for f in manifest["files"]}
    assert "accounts.db" in names and f"careers/{token}{storage.CAREER_EXT}" in names
    assert not any("secret.key" in n for n in names)
    assert offsite.last_made() and not offsite.overdue()
    page = master_client.get("/accounts").get_data(as_text=True)
    assert "Encrypted backup to keep somewhere else" in page and "Last downloaded" in page


def test_only_the_site_owner_can_download_the_site_backup(app, master_client):
    from f1tracker import auth
    auth.create_user("zed", "Zed", "password1")
    c = app.test_client()
    login(c, "zed")
    res = c.post("/settings/offsite-backup", data={"csrf_token": "tok", "passphrase": "x" * 20, "passphrase2": "x" * 20})
    assert res.status_code == 403
    assert "Encrypted backup to keep" not in c.get("/accounts").get_data(as_text=True)


def test_a_failed_daily_backup_never_blocks_the_page(app, master_client, monkeypatch):
    token = _league(master_client, "Backup Fails")
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(storage, "auto_backup", boom)
    assert master_client.get(f"/career/{token}/standings").status_code == 200


# --------------------------------------------------------------------------- PL-TEST-01: release + rollover

from f1tracker import seats   # noqa: E402


@v3
def test_a_released_driver_on_a_multi_year_deal_becomes_a_free_agent_not_seatless(app, master_client):
    """Found by the 100-run soak test: a driver released at the end of the season while holding a two-year contract
    was left 'contracted but not seated' after the rollover."""
    token = _v3_league(teams=(6,), rounds=3)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        team = S.driver_seats(conn, sid)[a][0]
        seats.record_contract(conn, a, team, 2026, years=2, note="two-year deal")
        for ev in S.events(conn, sid):
            run_event(conn, ev, order=_order(conn, ev, {a: 22}))       # dead last every time
        relations.decide_releases(conn, sid, final=True)
        assert relations.is_released(conn, sid, a)
        assert seats.covering(seats.contracts(conn, a), 2027) is None       # the release ended the deal after 2026
        deal = seats.contracts(conn, a)[-1]
        assert deal["end_year"] == 2026 and deal["stage"] == "Released"      # kept in the history, cut short
        review = {r["driver"]["id"]: r for r in seats.rollover_review(conn, sid, 2027)["rows"]}
        assert review[a]["kind"] == "released"
        pids = players_ids(conn)
    r = master_client.post(f"/career/{token}/seasons/new", data={"year": 2027, "csrf_token": "tok",
                                                                 **{f"decision_{p}": "provisional" for p in pids}})
    assert r.status_code == 302
    with storage.session(token) as conn:
        new = S.current_season_id(conn)
        assert S.get_season(conn, new)["year"] == 2027
        assert seats.problems(conn, new) == []
        assert a not in S.driver_seats(conn, new)
        assert S.driver_map(conn)[a]["career_status"] == "Free Agent"


@v3
def test_a_release_before_3_0_is_repaired_at_the_rollover(app, master_client):
    token = _v3_league(teams=(6,), rounds=3)
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        team = S.driver_seats(conn, sid)[a][0]
        seats.record_contract(conn, a, team, 2026, years=3)
        for ev in S.events(conn, sid):
            run_event(conn, ev)
        conn.execute("UPDATE team_relations SET released = 1 WHERE season_id = ? AND driver_id = ?", (sid, a))  # 2.5
        pids = players_ids(conn)
    master_client.post(f"/career/{token}/seasons/new", data={"year": 2027, "csrf_token": "tok",
                                                             **{f"decision_{p}": "provisional" for p in pids}})
    with storage.session(token) as conn:
        assert seats.problems(conn, S.current_season_id(conn)) == []


# --------------------------------------------------------------------------- 3.0.1: charts and change notices

from f1tracker import insights, migration   # noqa: E402


def _chart_matches_standings(conn, sid, did):
    t = insights.driver_round_timeline(conn, did)
    row = next(r for r in S.driver_standings(conn, sid) if r["driver_id"] == did)
    return t, (t["form"][-1], t["reputation"][-1]) == (row["form"], row["reputation"])


@v3
def test_form_and_reputation_chart_follows_version_3():
    token = _v3_league(teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        for i, ev in enumerate(S.events(conn, sid)[:5]):
            run_event(conn, ev, order=_order(conn, ev, {a: 3 + i}))
        t, same = _chart_matches_standings(conn, sid, a)
        assert same and len(t["form"]) == 5
        # every point is what the standings showed after that round
        for i in range(5):
            row = next(r for r in S.driver_standings(conn, sid, upto_round=i + 1) if r["driver_id"] == a)
            assert (t["form"][i], t["reputation"][i]) == (row["form"], row["reputation"])


def test_chart_follows_a_full_recalculation_to_version_3():
    token = _v3_league(engine3=False, pending=True, teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        for i, ev in enumerate(S.events(conn, sid)[:4]):
            run_event(conn, ev, order=_order(conn, ev, {a: 2 + 3 * i}))
        before = insights.driver_round_timeline(conn, a)
        migration.apply_full(conn, "tester")
        t, same = _chart_matches_standings(conn, sid, a)
        assert same and len(t["form"]) == 4
        row1 = next(r for r in S.driver_standings(conn, sid, upto_round=1) if r["driver_id"] == a)
        assert (t["form"][0], t["reputation"][0]) == (row1["form"], row1["reputation"])     # earlier rounds follow too
        assert t["form"] != before["form"] or t["reputation"] != before["reputation"]


def test_chart_for_a_future_only_season_keeps_earlier_rounds_and_matches_now():
    token = _v3_league(engine3=False, pending=True, teams=(6,))
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        a = players_ids(conn)[0]
        evs = S.events(conn, sid)
        for i, ev in enumerate(evs[:3]):
            run_event(conn, ev, order=_order(conn, ev, {a: 4 + i}))
        before = insights.driver_round_timeline(conn, a)
        migration.apply_future(conn, "tester")
        for i, ev in enumerate(evs[3:6]):
            run_event(conn, ev, order=_order(conn, ev, {a: 8 + i}))
        t, same = _chart_matches_standings(conn, sid, a)
        assert same and t["form"][:3] == before["form"][:3] and t["reputation"][:3] == before["reputation"][:3]


def test_other_drivers_change_notices_are_race_master_only(app, master_client):
    from f1tracker import auth
    token = _league(master_client, "Notice League")
    with storage.session(token) as conn:
        for _ in range(2):
            conn.execute("UPDATE drivers SET is_player = 1 WHERE id = (SELECT id FROM drivers WHERE is_player = 0 "
                         "ORDER BY id LIMIT 1)")
        one, two = [p["id"] for p in S.player_drivers(conn)][:2]
    auth.create_user("pat", "Pat", "password1")
    with storage.session(token) as conn:
        conn.execute("INSERT INTO career_members(username, role, driver_id) VALUES(?,?,?)", ("pat", "member", one))
        impacts.add_notice(conn, one, "t-1", "Pat's change", "why", [{"label": "Form", "before": 1, "after": 2,
                                                                       "change": 1, "stat": "form"}])
        impacts.add_notice(conn, two, "t-2", "Someone else's change", "why", [])
    pat = app.test_client()
    login(pat, "pat")
    page = pat.get(f"/career/{token}/changes").get_data(as_text=True)
    assert "Pat&#39;s change" in page and "Someone else" not in page and "Race Master only" not in page
    page = master_client.get(f"/career/{token}/changes").get_data(as_text=True)
    assert "Someone else" in page and "Race Master only" in page
    # a Race Master viewing the league as someone else sees only their own notices
    master_client.post(f"/career/{token}/mode", data={"csrf_token": "tok", "mode": "spectator"})
    page = master_client.get(f"/career/{token}/changes").get_data(as_text=True)
    assert "Someone else" not in page and "Race Master only" not in page
