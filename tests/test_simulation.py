"""End-to-end simulation: play seasons through the real web routes as every kind of user, then crawl
every reachable page looking for server errors."""

import random
import re

from conftest import login
from f1tracker import auth, community, market, relations, services as S, storage, teamlife
from f1tracker import constants as C

LINK = re.compile(r'href="(/(?:career|public)/[^"#]*)"')
FLASHES = []


def _crawl(client, start, limit=400):
    seen, queue, errors = set(), list(start), []
    while queue and len(seen) < limit:
        path = queue.pop(0).replace("&amp;", "&")
        if path in seen or any(x in path for x in ("/backup", "/export", "/autobackup/", "/avatar/", "/logout")):
            continue
        seen.add(path)
        res = client.get(path)
        if res.status_code >= 500:
            errors.append((path, res.status_code))
            continue
        if res.status_code == 200 and "text/html" in res.headers.get("Content-Type", ""):
            for link in LINK.findall(res.get_data(as_text=True)):
                if link not in seen:
                    queue.append(link)
    return seen, errors


def _flashes(client):
    with client.session_transaction() as sess:
        FLASHES.extend(m for cat, m in sess.pop("_flashes", []) if cat == "error")


def _results(conn, event_id, rng):
    rows = S.weekend_rows(conn, event_id)
    ids = [r["driver_id"] for r in rows]
    order = ids[:]
    rng.shuffle(order)
    quali = ids[:]
    rng.shuffle(quali)
    out = []
    for did in ids:
        out.append({"driver_id": did, "qualifying_position": quali.index(did) + 1,
                    "race_position": order.index(did) + 1,
                    "status_override": "DNF" if rng.random() < 0.05 else "Auto",
                    "sprint_position": order.index(did) + 1, "sprint_status_override": "Auto",
                    "fastest_lap": did == order[1], "driver_of_day": did == order[2], "notes": ""})
    return out


def test_two_season_simulation_and_crawl(app, master_client):
    rng = random.Random(11)
    for name in ("ana", "ben", "kim", "viv"):
        auth.create_user(name, name.title(), "password1", email=f"{name}@example.com")
    res = master_client.post("/careers/new", data={
        "name": "Sim League", "year": "2026", "player_name": ["Ana Silva", "Ben Okafor"],
        "player_login": ["ana", "ben"], "rookie_market": "1", "join_open": "1", "csrf_token": "tok",
        **{f"feature_{k}": "1" for k in C.FEATURES}})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    master_client.post(f"/career/{token}/members", data={
        "user_1": "", "member_kim": "scorekeeper", "member_viv": "spectator", "csrf_token": "tok"})
    with storage.session(token) as conn:
        ana_id, ben_id = [p["id"] for p in S.player_drivers(conn)]
    master_client.post(f"/career/{token}/members", data={
        f"user_{ana_id}": "ana", f"user_{ben_id}": "ben", "member_kim": "scorekeeper", "member_viv": "spectator",
        "csrf_token": "tok"})
    clients = {"master": master_client}
    for name in ("ana", "ben", "kim", "viv"):
        clients[name] = app.test_client()
        login(clients[name], name)
    drivers = {"ana": ana_id, "ben": ben_id}

    def negotiate():
        for name, did in drivers.items():
            c = clients[name]
            for _ in range(4):
                with storage.session(token) as conn:
                    pending = [o for o in market.offers(conn, driver_id=did) if o["status"] == C.OFFER_PENDING]
                    windows = [w for w in market.windows(conn) if w["status"] == C.WINDOW_OPEN]
                if not pending:
                    if windows:
                        with storage.session(token) as conn:
                            teams = market.approachable_teams(conn, windows[0]["id"], did)
                        if teams and market_left(windows[0]["id"], did):
                            r = c.post(f"/career/{token}/market/approach", data={
                                "driver_id": did, "window_id": windows[0]["id"], "team_id": rng.choice(teams)["id"],
                                "terms": "custom", "role": rng.choice(C.CONTRACT_ROLES), "years": rng.randint(1, 3),
                                "growth": rng.randint(0, 3), "csrf_token": "tok"})
                            assert r.status_code == 302
                            _flashes(c)
                    continue
                o = rng.choice(pending)
                if o["final"] or rng.random() < 0.35:
                    r = c.post(f"/career/{token}/offers/{o['id']}/accept", data={"csrf_token": "tok"})
                else:
                    r = c.post(f"/career/{token}/offers/{o['id']}/counter", data={
                        "role": rng.choice(C.CONTRACT_ROLES), "years": rng.randint(1, 4), "growth": rng.randint(0, 3),
                        "message": "Let's talk", "csrf_token": "tok"})
                assert r.status_code == 302, r.status_code
                _flashes(c)

    def market_left(window_id, did):
        with storage.session(token) as conn:
            return market.approaches_left(conn, window_id, did) > 0

    negotiate()
    for season in (2026, 2027):
        with storage.session(token) as conn:
            sid = S.current_season_id(conn)
            evs = S.events(conn, sid)[:8]
        for i, ev in enumerate(evs):
            if i == 0:
                master_client.post(f"/career/{token}/weekend/{ev['id']}/time",
                                   data={"race_at": f"{season + 1}-01-0{i + 1}T19:00", "tz": "0", "csrf_token": "tok"})
            for name in ("ana", "ben", "viv"):
                clients[name].post(f"/career/{token}/weekend/{ev['id']}/checkin",
                                   data={"status": rng.choice(list(C.CHECKIN_CHOICES)), "csrf_token": "tok"})
                with storage.session(token) as conn:
                    pool = [r["driver_id"] for r in S.weekend_rows(conn, ev["id"])]
                clients[name].post(f"/career/{token}/weekend/{ev['id']}/predict", data={
                    "pole": rng.choice(pool), "winner": rng.choice(pool), "csrf_token": "tok"})
            with storage.session(token) as conn:
                results = _results(conn, ev["id"], rng)
            who = clients["kim"] if i % 2 else master_client
            r = who.post(f"/api/career/{token}/weekend/{ev['id']}", headers={"X-CSRF-Token": "tok"},
                         json={"results": results, "mark_complete": True, "ai_difficulty": rng.randint(70, 100)})
            assert r.get_json()["ok"], r.get_json()
            clients["ana"].post(f"/career/{token}/comments",
                                data={"target": f"event:{ev['id']}", "body": f"Round {i + 1}!", "csrf_token": "tok"})
            clients["viv"].post(f"/career/{token}/weekend/{ev['id']}/fan-vote",
                                data={"driver_id": ana_id, "csrf_token": "tok"})
            for name, did in drivers.items():
                with storage.session(token) as conn:
                    pen = teamlife.press_pen(conn, sid, did)
                    pledge = relations.needs_pledge(conn, sid, did)
                if pledge:
                    clients[name].post(f"/career/{token}/pledge", data={"growth": rng.randint(0, 3), "csrf_token": "tok"})
                for q in (pen["questions"] if pen else []):
                    clients[name].post(f"/career/{token}/press/{ev['id']}", data={
                        "question": q["key"], "answer": rng.choice(q["answers"])["key"], "csrf_token": "tok"})
            if i % 3 == 1:
                clients["ben"].post(f"/career/{token}/weekend/{ev['id']}/incident", data={
                    "accused_id": ana_id, "description": f"Contact at turn {i}", "csrf_token": "tok"})
                with storage.session(token) as conn:
                    open_ids = [x["id"] for x in community.incidents(conn) if x["status"] == "Open"]
                for iid in open_ids:
                    master_client.post(f"/career/{token}/incidents/{iid}/rule", data={
                        "ruling": rng.choice(list(C.INCIDENT_RULINGS)), "note": "Reviewed", "csrf_token": "tok"})
            for c in clients.values():
                _flashes(c)
        # finish the rest of the season quickly
        with storage.session(token) as conn:
            for ev in S.events(conn, sid)[8:]:
                S.save_weekend(conn, ev["id"], {"results": _results(conn, ev["id"], rng), "mark_complete": True})
                teamlife.after_race(conn, ev["id"])
                market.maybe_open_silly_season(conn, sid)
        negotiate()
        r = master_client.post(f"/career/{token}/seasons/new", data={"year": season + 1, "csrf_token": "tok"})
        assert r.status_code == 302
        negotiate()

    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        grid = [d for d in S.grid_map(conn, sid).values() if d]
        assert len(grid) == len(set(grid))
        key = community.public_key(conn)

    errors = []
    for name, client in clients.items():
        for path in ("/help", "/changelog"):
            assert client.get(path).status_code == 200
        _seen, errs = _crawl(client, [f"/career/{token}/dashboard", "/"])
        print(name, len(_seen))
        errors += [(name,) + e for e in errs]
    print("FLASHED ERRORS:", sorted(set(FLASHES)))
    anon = app.test_client()
    _seen, errs = _crawl(anon, [f"/public/{token}/{key}"])
    errors += [("anon",) + e for e in errs]
    assert not errors, errors
