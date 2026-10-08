"""Calendar shuffle: some races sit out a season, others come in from the full circuit catalogue.

Only rounds that haven't been run change. Rounds with results keep their round number, name and Sprint format, and
every round number stays where it is, so race times already set stay with their round. The Race Master sees a
preview first; applying recomputes the same plan from its seed and refuses if the calendar changed in between.

Circuits that have been away from the league longest are likelier to come back, so races that sat out return in
later seasons rather than vanishing for good.
"""

import hashlib
import random

from . import circuits
from . import constants as C
from . import services as S
from .services import ValidationError

DEFAULT_SWAPS = 3


def fingerprint(evs):
    raw = "|".join(f"{e['id']}:{e['round_number']}:{e['name']}:{e['location']}:{e['is_sprint']}:{e['status']}"
                   for e in sorted(evs, key=lambda e: e["id"]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _last_raced(conn, season):
    """circuit -> how many seasons since this league last had it on a calendar (None: never)."""
    last = {}
    for s in S.list_seasons(conn):
        if s["year"] >= season["year"]:
            continue
        for e in S.events(conn, s["id"]):
            key = circuits.circuit_of(e)
            if key:
                last[key] = max(last.get(key, 0), s["year"])
    return {k: season["year"] - y for k, y in last.items()}


def _base(circuit):
    return circuit.replace(" (Reverse)", "")


def options(conn, season_id):
    """What the shuffle form offers: the open rounds and every circuit that could come in."""
    season = S.get_season(conn, season_id)
    evs = S.events(conn, season_id)
    on = {circuits.circuit_of(e) for e in evs} - {""}
    away = _last_raced(conn, season)
    pool = []
    for c in circuits.catalogue():
        if c["key"] in on:
            continue
        gap = away.get(c["key"])
        c["away"] = ("never raced in this league" if gap is None
                     else "last raced last season" if gap == 1 else f"last raced {gap} seasons ago")
        pool.append(c)
    return {"season": season, "events": evs, "open": [e for e in evs if e["status"] == C.EVENT_NOT_RUN],
            "pool": pool, "fingerprint": fingerprint(evs)}


def plan(conn, season_id, swaps=DEFAULT_SWAPS, reorder=True, keep_ends=True, pool_keys=None, keep_ids=(), seed=None):
    """The proposed calendar. pool_keys: circuits allowed to come in (default: every one in the current game);
    keep_ids: rounds that must stay on the calendar. Returns rows in round order plus what sits out and comes in."""
    season = S.get_season(conn, season_id)
    if not season:
        raise ValidationError("Season not found")
    if season["status"] == C.SEASON_COMPLETE:
        raise ValidationError(f"The {season['year']} season is archived, so its calendar can't be shuffled.")
    opts = options(conn, season_id)
    evs = sorted(opts["events"], key=lambda e: e["round_number"])
    open_ = sorted(opts["open"], key=lambda e: e["round_number"])
    if not open_:
        raise ValidationError("Every round of this season has been run, so there's nothing left to shuffle.")
    seed = int(seed) if seed not in (None, "") else random.SystemRandom().randrange(1, 10 ** 9)
    rng = random.Random(seed)
    try:
        swaps = max(0, int(swaps))
    except (TypeError, ValueError):
        raise ValidationError("The number of races to swap must be a whole number")

    pinned = {int(i) for i in keep_ids}
    if keep_ends:
        for e in (evs[0], evs[-1]):
            if e["status"] == C.EVENT_NOT_RUN:
                pinned.add(e["id"])
    allowed = [c for c in opts["pool"] if (c["where"] == "game" if pool_keys is None else c["key"] in pool_keys)]

    movable = [e for e in open_ if e["id"] not in pinned]
    swaps = min(swaps, len(movable), len(allowed))
    # A layout and its reverse never share a calendar: bringing one in sends the other (if still open) to sit out.
    venue = {}
    for e in evs:
        key = circuits.circuit_of(e)
        if key:
            venue.setdefault(_base(key), e)
    movable_ids = {e["id"] for e in movable}
    away = _last_raced(conn, season)
    out, incoming, choices, sprint_of = [], [], list(allowed), {}
    while len(incoming) < swaps:
        options_ = [c for c in choices if _base(c["key"]) not in venue or
                    (venue[_base(c["key"])]["id"] in movable_ids and venue[_base(c["key"])] not in out)]
        if not options_:
            break
        weights = [min(away.get(c["key"], 2), 4) for c in options_]   # away longest, likelier to return
        pick = rng.choices(options_, weights=weights)[0]
        choices.remove(pick)
        incoming.append(pick)
        partner = venue.get(_base(pick["key"]))
        if partner:
            out.append(partner)
            sprint_of[pick["key"]] = partner["is_sprint"]   # its other layout's weekend format carries over
    rest = [e for e in movable if e not in out and not any(_base(c["key"]) == _base(circuits.circuit_of(e))
                                                            for c in incoming)]
    out += rng.sample(rest, len(incoming) - len(out))
    out.sort(key=lambda e: e["round_number"])
    swaps = len(incoming)

    out_ids = {e["id"] for e in out}
    staying = [e for e in movable if e["id"] not in out_ids]
    slots = list(movable)                     # the unpinned open rounds, in round order
    entries = [{"name": e["name"], "location": e["location"], "is_sprint": e["is_sprint"], "from": e}
               for e in staying]
    entries += [{"name": c["gp"], "location": c["location"], "is_sprint": sprint_of.get(c["key"], 0), "from": None,
                 "circuit": c}
                for c in incoming]
    if reorder:
        rng.shuffle(entries)
    else:   # each newcomer takes the round of a race that sits out (its own other layout's, if that's the one)
        newcomers = entries[len(staying):]
        by_slot = {}
        for e in out:
            same = [x for x in newcomers if _base(x["circuit"]["key"]) == _base(circuits.circuit_of(e))]
            by_slot[e["id"]] = same[0] if same else next(x for x in newcomers if not any(
                _base(x["circuit"]["key"]) == _base(circuits.circuit_of(o)) for o in out))
            newcomers.remove(by_slot[e["id"]])
        for x in entries[:len(staying)]:
            by_slot[x["from"]["id"]] = x
        entries = [by_slot[e["id"]] for e in slots]

    assigned = dict(zip((e["id"] for e in slots), entries))
    rows = []
    for e in evs:
        if e["id"] in assigned:
            new = assigned[e["id"]]
            before = new["from"]
            change = "new" if before is None else ("same" if before["id"] == e["id"] else "moved")
            if change == "moved" and before["round_number"] < e["round_number"]:
                change = "later"
            elif change == "moved":
                change = "earlier"
            rows.append({"event": e, "name": new["name"], "location": new["location"], "is_sprint": int(new["is_sprint"]),
                         "change": change, "was_round": before["round_number"] if before else None,
                         "circuit": circuits.lookup(new["name"], new["location"])})
        else:
            rows.append({"event": e, "name": e["name"], "location": e["location"], "is_sprint": e["is_sprint"],
                         "change": "locked" if e["status"] != C.EVENT_NOT_RUN else "kept",
                         "was_round": None, "circuit": circuits.lookup(e["name"], e["location"])})
    return {"seed": seed, "rows": rows, "out": out, "incoming": incoming, "fingerprint": opts["fingerprint"],
            "swaps": swaps, "season": season}


def apply(conn, season_id, expected_fingerprint, **kw):
    """Recompute the previewed plan and save it. Refuses if the calendar changed since the preview."""
    if fingerprint(S.events(conn, season_id)) != expected_fingerprint:
        raise ValidationError("The calendar changed since this preview was made. Make a new preview and check it first.")
    result = plan(conn, season_id, **kw)
    S.save_calendar(conn, season_id, [{"id": r["event"]["id"], "round_number": r["event"]["round_number"],
                                       "name": r["name"], "location": r["location"], "is_sprint": r["is_sprint"]}
                                      for r in result["rows"]])
    return result
