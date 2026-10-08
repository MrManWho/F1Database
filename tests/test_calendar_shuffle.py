"""Calendar shuffle: races sit out a season and others come in from the full circuit catalogue. Rounds with results
never change, the preview is what gets applied, and every game circuit has its own outline."""

import pytest

from conftest import run_event
from f1tracker import calendar_shuffle as CS, circuits, constants as C, services as S, storage


def _league(master_client, run=1):
    res = master_client.post("/careers/new", data={"name": "Shuffle", "year": "2026", "player_name": ["Ana Silva"],
                                                   "csrf_token": "tok", "join_mode": "invite"})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        sid = S.current_season_id(conn)
        for ev in S.events(conn, sid)[:run]:
            run_event(conn, ev)
    return token, sid


def _events(token, sid):
    with storage.session(token) as conn:
        return S.events(conn, sid)


def test_every_catalogue_circuit_has_its_own_outline():
    cat = circuits.catalogue()
    assert len({c["circuit"] for c in cat}) == len(cat)
    for c in cat:
        found = circuits.lookup(c["gp"], c["location"])
        assert found["circuit"] == c["circuit"] and found["path"] != circuits.GENERIC and found["code"]
    names = {c["circuit"] for c in cat}
    assert {"Imola", "Silverstone (Reverse)", "Red Bull Ring (Reverse)", "Zandvoort (Reverse)", "Madring",
            "Algarve International Circuit", "Circuit Paul Ricard"} <= names
    for _, name, loc, _ in C.CALENDAR:      # the default calendar is all catalogue circuits
        assert circuits.circuit_of({"name": name, "location": loc}) in names


def test_qatar_is_no_longer_mistaken_for_austin():
    assert circuits.lookup("Qatar GP", "Lusail")["circuit"] == "Lusail International Circuit"
    assert circuits.lookup("United States GP", "Austin")["circuit"] == "Circuit of the Americas"


@pytest.mark.parametrize("reorder", [True, False])
def test_plan_swaps_races_and_never_touches_run_rounds(app, master_client, reorder):
    token, sid = _league(master_client, run=2)
    before = _events(token, sid)
    with storage.session(token) as conn:
        p = CS.plan(conn, sid, swaps=4, reorder=reorder, seed=11)
    assert p["swaps"] == 4 and len(p["out"]) == 4 and len(p["incoming"]) == 4
    rows = {r["event"]["id"]: r for r in p["rows"]}
    for e in before[:2]:                       # run rounds: unchanged
        assert rows[e["id"]]["name"] == e["name"] and rows[e["id"]]["change"] == "locked"
    assert rows[before[-1]["id"]]["name"] == before[-1]["name"]      # finale kept in place by default
    new_names = [r["name"] for r in p["rows"]]
    assert len(new_names) == len(before) and len(set(new_names)) == len(new_names)
    for e in p["out"]:
        assert e["name"] not in new_names
    for c in p["incoming"]:
        assert c["gp"] in new_names and c["where"] == "game"
    bases = [CS._base(circuits.circuit_of({"name": r["name"], "location": r["location"]})) for r in p["rows"]]
    assert len(bases) == len(set(bases))     # a layout and its reverse never share a calendar
    if not reorder:
        stayed = {e["id"] for e in before} - {e["id"] for e in p["out"]}
        assert all(rows[i]["name"] == e["name"] for e in before for i in [e["id"]] if i in stayed)


def test_same_seed_same_plan_and_apply_saves_it(app, master_client):
    token, sid = _league(master_client)
    with storage.session(token) as conn:
        a = CS.plan(conn, sid, seed=5)
        b = CS.plan(conn, sid, seed=5)
        fp = CS.options(conn, sid)["fingerprint"]
    assert [r["name"] for r in a["rows"]] == [r["name"] for r in b["rows"]]
    res = master_client.post(f"/career/{token}/calendar/shuffle", data={
        "csrf_token": "tok", "set": "1", "seed": "5", "swaps": "3", "reorder": "1", "keep_ends": "1",
        "fingerprint": fp, "pool": [c["key"] for c in circuits.catalogue() if c["where"] == "game"]})
    assert res.status_code == 302
    after = _events(token, sid)
    assert [e["name"] for e in after] == [r["name"] for r in a["rows"]]
    assert [e["round_number"] for e in after] == list(range(1, len(after) + 1))
    # The calendar changed, so the old preview can't be applied again.
    with storage.session(token) as conn:
        with pytest.raises(S.ValidationError):
            CS.apply(conn, sid, fp, seed=5)


def test_older_game_circuits_only_when_ticked(app, master_client):
    token, sid = _league(master_client)
    older = {c["key"] for c in circuits.catalogue() if c["where"] == "older"}
    with storage.session(token) as conn:
        for seed in range(20):
            assert not {c["key"] for c in CS.plan(conn, sid, swaps=5, seed=seed)["incoming"]} & older
        p = CS.plan(conn, sid, swaps=2, pool_keys=older, seed=1)
    assert {c["key"] for c in p["incoming"]} == older


def test_pinned_races_stay(app, master_client):
    token, sid = _league(master_client)
    evs = _events(token, sid)
    keep = [e["id"] for e in evs[1:12]]
    with storage.session(token) as conn:
        for seed in range(10):
            p = CS.plan(conn, sid, swaps=6, keep_ids=keep, seed=seed)
            assert not {e["id"] for e in p["out"]} & set(keep)


def test_page_shows_preview_and_every_circuit(app, master_client):
    token, sid = _league(master_client)
    html = master_client.get(f"/career/{token}/calendar/shuffle").get_data(as_text=True)
    assert "Use this calendar" in html and "Comes in" in html and "Circuit Paul Ricard" in html
    assert "Shuffle calendar" in master_client.get(f"/career/{token}/seasons").get_data(as_text=True)
