"""Transfer market: rookie offers and performance-based team offers for the player drivers.

Teams judge a player on a Driver Value built from:
    0.5 x Market Score (long-term Reputation + Form)
  + 0.3 x Form (this season's raw results)
  + 0.2 x Car-Adjusted Rating (finishing ahead of where the car "should" finish)
  + teammate head-to-head bonus (up to +/-4)

Each team has an entry bar that rises with its constructor rank. A team makes an offer when a
player's value clears its bar (plus a little human unpredictability). Offers never move a driver on
their own: the player accepts one from their own login, and the signing is then applied to the grid.
"""

import math
import random

from . import constants as C
from . import feed
from . import services as S
from .storage import now_iso

TEAM_BAR_TOP = 86.0      # bar for the constructor-rank-1 team
TEAM_BAR_STEP = 4.2      # each lower-ranked team asks for this much less
JITTER = 3.0


def team_bar(rank):
    return TEAM_BAR_TOP - (rank - 1) * TEAM_BAR_STEP


def interest_label(interest):
    if interest >= 6:
        return "Keen"
    if interest >= 0:
        return "Interested"
    if interest >= -6:
        return "Watching"
    return "Cold"


def _season_results(conn, season_id, driver_id):
    return conn.execute("""SELECT r.*, e.round_number, e.name AS event_name FROM results r
                           JOIN events e ON e.id = r.event_id
                           WHERE e.season_id = ? AND r.driver_id = ? ORDER BY e.round_number""",
                        (season_id, driver_id)).fetchall()


def head_to_head(conn, season_id, driver_id):
    """Race and qualifying head-to-heads against whoever shared the car in each event."""
    h2h = {"race_won": 0, "race_total": 0, "quali_won": 0, "quali_total": 0}
    for r in _season_results(conn, season_id, driver_id):
        mates = conn.execute("SELECT * FROM results WHERE event_id = ? AND team_id = ? AND driver_id != ?",
                             (r["event_id"], r["team_id"], driver_id)).fetchall()
        for m in mates:
            if r["race_position"] and m["race_position"] and r["result_status"] in C.START_STATUSES \
                    and m["result_status"] in C.START_STATUSES:
                mine = r["race_position"] if r["result_status"] == C.STATUS_FINISHED else 99
                theirs = m["race_position"] if m["result_status"] == C.STATUS_FINISHED else 99
                if mine != theirs:
                    h2h["race_total"] += 1
                    h2h["race_won"] += int(mine < theirs)
            if r["qualifying_position"] and m["qualifying_position"]:
                h2h["quali_total"] += 1
                h2h["quali_won"] += int(r["qualifying_position"] < m["qualifying_position"])
    return h2h


def car_adjusted_rating(conn, season_id, driver_id, ranks):
    deltas = []
    for r in _season_results(conn, season_id, driver_id):
        if r["result_status"] == C.STATUS_FINISHED and r["race_position"] and r["team_id"] in ranks:
            deltas.append((2 * ranks[r["team_id"]] - 0.5) - r["race_position"])
    if not deltas:
        return 50.0
    return round(S.clamp(50 + 5 * sum(deltas) / len(deltas), 1, 100), 1)


def driver_value(conn, season_id, driver_id, standings=None, ranks=None):
    standings = standings if standings is not None else {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    ranks = ranks or S.team_strength_ranks(conn, season_id)
    row = standings.get(driver_id)
    if row:
        rep, form, stats = row["reputation"], row["form"], row
    else:
        rep, form, stats = S.starting_reputation(conn, season_id, driver_id), 50.0, None
    market = S.market_score(rep, form)
    car = car_adjusted_rating(conn, season_id, driver_id, ranks)
    h2h = head_to_head(conn, season_id, driver_id)
    bonus = 0.0
    if h2h["race_total"] >= 2:
        bonus = S.clamp((h2h["race_won"] / h2h["race_total"] - 0.5) * 8, -4, 4)
    value = 0.5 * market + 0.3 * form + 0.2 * car + bonus
    return {
        "value": round(value, 1), "market": market, "reputation": rep, "form": form, "car": car,
        "h2h": h2h, "h2h_bonus": round(bonus, 1), "stats": stats,
    }


def career_starts(conn, driver_id):
    return conn.execute("SELECT COUNT(*) FROM results WHERE driver_id = ? AND result_status IN (?,?,?)",
                        (driver_id, *sorted(C.START_STATUSES))).fetchone()[0]


def team_interest(conn, season_id, driver_id):
    """Live, jitter-free read of how every team currently rates this driver."""
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    ranks = S.team_strength_ranks(conn, season_id)
    me = driver_value(conn, season_id, driver_id, standings, ranks)
    seats = S.driver_seats(conn, season_id)
    my_team = seats.get(driver_id, (None,))[0]
    rookie = career_starts(conn, driver_id) == 0
    out = []
    for team in S.teams(conn):
        rank = ranks.get(team["id"], len(ranks))
        interest = me["value"] - team_bar(rank) + (3 if team["id"] == my_team else 0)
        if rookie and rank > len(ranks) - 5:
            interest = max(interest, 1.0 + (rank - (len(ranks) - 5)))
        out.append({"team": team, "rank": rank, "bar": round(team_bar(rank), 1), "interest": round(interest, 1),
                    "label": interest_label(interest), "current": team["id"] == my_team})
    out.sort(key=lambda t: -t["interest"])
    return me, out


def _team_lineup_values(conn, season_id, team_id, standings, ranks, exclude):
    gmap = S.grid_map(conn, season_id)
    values = []
    for seat in (1, 2):
        did = gmap.get((team_id, seat))
        if did and did != exclude:
            values.append(driver_value(conn, season_id, did, standings, ranks)["value"])
    return values


def _role_for(value, lineup):
    if not lineup:
        return "Equal Status"
    best = max(lineup)
    if value >= best + 3:
        return "No. 1"
    if value >= best - 3:
        return "Equal Status"
    return "No. 2"


def _reason(rng, team, me, rank, rookie, renewal):
    if rookie:
        return rng.choice([
            f"{team['name']} want to develop young talent and see you as a long-term project.",
            f"{team['name']} were impressed in the junior categories and have a seat for a rookie.",
            f"{team['name']}'s team principal wants fresh blood on the grid.",
        ])
    bits = []
    s = me["stats"]
    if s and s.get("wins"):
        bits.append(f"{s['wins']} win{'s' if s['wins'] != 1 else ''}")
    if s and s.get("podiums"):
        bits.append(f"{s['podiums']} podium{'s' if s['podiums'] != 1 else ''}")
    if s and s.get("points"):
        bits.append(f"{s['points']} points")
    h2h = me["h2h"]
    if h2h["race_total"]:
        bits.append(f"{h2h['race_won']}-{h2h['race_total'] - h2h['race_won']} against your teammate")
    if me["car"] >= 60:
        bits.append("consistently beating the car's expected finish")
    summary = ", ".join(bits) if bits else "your steady progress"
    if renewal:
        return f"{team['name']} want to keep you after {summary}."
    if rank <= 3:
        return f"A top team is calling: {team['name']} noticed {summary}."
    return f"{team['name']} like what they see: {summary}."


def _full_of_players(conn, season_id, team_id, signed_teams):
    players = {d["id"] for d in S.player_drivers(conn)}
    gmap = S.grid_map(conn, season_id)
    seated = sum(1 for s in (1, 2) if gmap.get((team_id, s)) in players)
    return seated + signed_teams.count(team_id) >= 2


def target_year(conn, season_id):
    season = S.get_season(conn, season_id)
    return season["year"] if not S.season_started(conn, season_id) else season["year"] + 1


def open_window(conn, season_id, kind=None, rng=None):
    """Open a market window and generate offers for every player driver."""
    rng = rng or random.Random()
    year = target_year(conn, season_id)
    existing = conn.execute("SELECT id FROM market_windows WHERE status = ? AND target_year = ?",
                            (C.WINDOW_OPEN, year)).fetchone()
    if existing:
        raise S.ValidationError(f"A market window for {year} is already open")
    if kind is None:
        kind = "Rookie Draft" if all(career_starts(conn, p["id"]) == 0 for p in S.player_drivers(conn)) \
            else ("Pre-season" if year == S.get_season(conn, season_id)["year"] else "Silly Season")
    window_id = conn.execute("INSERT INTO market_windows(season_id, target_year, kind, status, opened_at) "
                             "VALUES(?,?,?,?,?)", (season_id, year, kind, C.WINDOW_OPEN, now_iso())).lastrowid
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    ranks = S.team_strength_ranks(conn, season_id)
    seats = S.driver_seats(conn, season_id)
    signed = signed_team_ids(conn, year)
    for player in S.player_drivers(conn):
        if not player["active"]:
            continue
        _generate_for(conn, window_id, season_id, player, standings, ranks, seats, signed, rng)
    feed.on_window_opened(conn, window_id, "garage")
    return window_id


def signed_team_ids(conn, year):
    return [r["team_id"] for r in conn.execute(
        """SELECT o.team_id FROM offers o JOIN market_windows w ON w.id = o.window_id
           WHERE o.status = ? AND w.target_year = ?""", (C.OFFER_ACCEPTED, year))]


def experience(conn, driver_id):
    """Experience tier, from career Grand Prix starts."""
    starts = career_starts(conn, driver_id)
    if starts == 0:
        return "Rookie"
    if starts <= 30:
        return "Young driver"
    if starts <= 100:
        return "Established"
    return "Veteran"


def team_wealth(rank):
    """How much a team can spend relative to the midfield (fastest car 1.8x, slowest 0.7x)."""
    return round(1.8 - (rank - 1) * 0.11, 2)


def market_salary(value):
    """A driver's going rate in $M a year, before team wealth and interest."""
    return round(max(0.4, ((max(value, 40) - 40) / 10) ** 2 * 1.2 + 0.5), 1)


def _role_index(role):
    return C.CONTRACT_ROLES.index(role) if role in C.CONTRACT_ROLES else 0


def team_limits(conn, season_id, driver_id, team_id, interest, standings=None, ranks=None):
    """What a team is privately willing to give. Players never see these numbers directly.

    - Role ceiling: compared with the team's best other driver. Rookies are No. 2 unless a
      backmarker genuinely rates them; young drivers only get No. 1 status if they are clearly faster.
    - Years: rookies get 1-2 years (3 only if a team is very keen); everyone else 1-3.
    - Salary ceiling: going rate x team wealth, nudged up by interest. Rookies are capped.
    - Patience: how many rounds of haggling before the team issues a final offer or walks.
    """
    standings = standings if standings is not None else {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    ranks = ranks or S.team_strength_ranks(conn, season_id)
    me = driver_value(conn, season_id, driver_id, standings, ranks)
    exp = experience(conn, driver_id)
    rank = ranks.get(team_id, len(ranks))
    lineup = _team_lineup_values(conn, season_id, team_id, standings, ranks, driver_id)
    best = max(lineup) if lineup else 0
    ceiling = _role_for(me["value"], lineup)
    if exp == "Rookie":
        ceiling = "Equal Status" if rank >= 8 and me["value"] >= best and interest >= 4 else "No. 2"
    elif exp == "Young driver" and ceiling == "No. 1" and me["value"] < best + 8:
        ceiling = "Equal Status"
    wealth = team_wealth(rank)
    max_salary = market_salary(me["value"]) * wealth * (1 + S.clamp(interest, -5, 15) / 50)
    if exp == "Rookie":
        max_salary = min(max_salary, 2.0 * wealth)
    max_salary = round(max(0.3, max_salary), 1)
    if exp == "Rookie":
        min_years, max_years = 1, (3 if interest >= 10 else 2)
    else:
        min_years, max_years = 1, 3
    patience = 1 + int(interest >= 0) + int(interest >= 6) + int(interest >= 12)
    if exp == "Rookie" and patience > 2:
        patience -= 1  # rookies have less leverage, but always get a couple of rounds

    return {"ceiling_role": ceiling, "min_years": min_years, "max_years": max_years,
            "max_salary": max_salary, "patience": patience, "value": me, "experience": exp}


def _opening_terms(limits, interest, rookie, rng):
    ceiling = _role_index(limits["ceiling_role"])
    role = C.CONTRACT_ROLES[ceiling if interest >= 6 else max(0, ceiling - 1)]
    if rookie:
        years = rng.choice([1, 2])
    else:
        years = 1 + int(interest >= 6) + int(interest >= 12)
    years = int(S.clamp(years, limits["min_years"], limits["max_years"]))
    salary = round(max(0.3, limits["max_salary"] * 0.8), 1)
    return role, years, salary


def _log(conn, offer_id, author, action, message, role=None, years=None, salary=None):
    conn.execute("""INSERT INTO offer_messages(offer_id, author, action, role, years, salary, message, created_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (offer_id, author, action, role, years, salary, message, now_iso()))


def _create_offer(conn, window_id, season_id, driver_id, team_id, interest, reason, rng, standings, ranks,
                  origin="team", rookie=False, stage="Offer", final=False, lifeline=False, terms=None):
    limits = team_limits(conn, season_id, driver_id, team_id, interest, standings, ranks)
    role, years, salary = terms or _opening_terms(limits, interest, rookie, rng)
    offer_id = conn.execute(
        """INSERT INTO offers(window_id, driver_id, team_id, role, years, salary, interest, reason, status,
           created_at, origin, stage, patience, final, lifeline, ceiling_role, min_years, max_years, max_salary)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (window_id, driver_id, team_id, role, years, salary, round(interest, 1), reason, C.OFFER_PENDING,
         now_iso(), origin, stage, 0 if final else limits["patience"], int(final), int(lifeline),
         limits["ceiling_role"], limits["min_years"], limits["max_years"], limits["max_salary"])).lastrowid
    return offer_id


def _generate_for(conn, window_id, season_id, player, standings, ranks, seats, signed, rng):
    me = driver_value(conn, season_id, player["id"], standings, ranks)
    rookie = career_starts(conn, player["id"]) == 0
    my_team = seats.get(player["id"], (None,))[0]
    order = sorted(ranks, key=lambda t: ranks[t])
    candidates = []
    if rookie:
        pool = [t for t in order[-5:] if not _full_of_players(conn, season_id, t, signed)]
        weights = [ranks[t] for t in pool]  # weaker teams are likelier to gamble on a rookie
        while pool and len(candidates) < C.ROOKIE_OFFERS:
            pick = rng.choices(pool, weights=weights)[0]
            i = pool.index(pick)
            pool.pop(i)
            weights.pop(i)
            candidates.append((pick, 1.0 + rng.uniform(0, 4), False))
    else:
        for tid in order:
            if _full_of_players(conn, season_id, tid, signed) and tid != my_team:
                continue
            interest = me["value"] - team_bar(ranks[tid]) + rng.uniform(-JITTER, JITTER)
            if tid == my_team:
                interest += 3
            if interest >= 0:
                candidates.append((tid, interest, False))
        # Players hear from the best cars that want them; a renewal offer is always kept.
        candidates.sort(key=lambda c: ranks[c[0]])
        renewal = [c for c in candidates if c[0] == my_team]
        candidates = candidates[:C.MAX_OFFERS_PER_WINDOW]
        if renewal and renewal[0] not in candidates:
            candidates[-1] = renewal[0]
        if not candidates:
            fallback = my_team or order[-1]
            candidates.append((fallback, 0.0, True))
    tmap = S.team_map(conn)
    for tid, interest, last_chance in candidates:
        reason = _reason(rng, tmap[tid], me, ranks[tid], rookie, tid == my_team)
        if last_chance:
            reason = f"{tmap[tid]['name']} will give you one more chance to prove yourself."
            offer_id = _create_offer(conn, window_id, season_id, player["id"], tid, interest, reason, rng,
                                     standings, ranks, rookie=rookie, stage="Last-chance offer", final=True,
                                     lifeline=True, terms=("No. 2", 1, _floor_salary(ranks[tid])))
        else:
            offer_id = _create_offer(conn, window_id, season_id, player["id"], tid, interest, reason, rng,
                                     standings, ranks, rookie=rookie)
        o = get_offer(conn, offer_id)
        _log(conn, offer_id, "team", "offer", reason, o["role"], o["years"], o["salary"])


def _floor_salary(rank):
    return round(0.5 * team_wealth(rank), 1)


def close_window(conn, window_id):
    conn.execute("UPDATE offers SET status = ?, responded_at = ? WHERE window_id = ? AND status = ?",
                 (C.OFFER_EXPIRED, now_iso(), window_id, C.OFFER_PENDING))
    conn.execute("UPDATE market_windows SET status = ?, closed_at = ? WHERE id = ?",
                 (C.WINDOW_CLOSED, now_iso(), window_id))


def get_offer(conn, offer_id):
    row = conn.execute("""SELECT o.*, w.target_year, w.status AS window_status, w.season_id AS window_season
                          FROM offers o JOIN market_windows w ON w.id = o.window_id WHERE o.id = ?""",
                       (offer_id,)).fetchone()
    return dict(row) if row else None


def _ensure_limits(conn, offer):
    """Offers made before v1.4 have no stored limits; work them out on first use."""
    if offer["ceiling_role"] and offer["max_salary"] is not None and offer["patience"] is not None:
        return offer
    limits = team_limits(conn, offer["window_season"], offer["driver_id"], offer["team_id"], offer["interest"])
    salary = offer["salary"] if offer["salary"] is not None else round(limits["max_salary"] * 0.8, 1)
    conn.execute("""UPDATE offers SET ceiling_role=?, min_years=?, max_years=?, max_salary=?, patience=?, salary=?
                    WHERE id=?""", (limits["ceiling_role"], limits["min_years"], limits["max_years"],
                                    limits["max_salary"], limits["patience"], salary, offer["id"]))
    return get_offer(conn, offer["id"])


def _open_offer(conn, offer_id):
    offer = get_offer(conn, offer_id)
    if not offer or offer["status"] != C.OFFER_PENDING or offer["window_status"] != C.WINDOW_OPEN:
        raise S.ValidationError("That offer is no longer available")
    return _ensure_limits(conn, offer)


def parse_terms(role, years, salary):
    if role not in C.CONTRACT_ROLES:
        raise S.ValidationError("Choose No. 1, Equal Status or No. 2")
    try:
        years = int(years)
    except (TypeError, ValueError):
        raise S.ValidationError("Contract length must be a whole number of years")
    if not 1 <= years <= C.MAX_CONTRACT_YEARS:
        raise S.ValidationError(f"Contracts run from 1 to {C.MAX_CONTRACT_YEARS} years")
    try:
        salary = round(float(salary), 1)
    except (TypeError, ValueError):
        raise S.ValidationError("Salary must be a number (in $ millions)")
    if not 0.1 <= salary <= 100:
        raise S.ValidationError("Salary must be between $0.1M and $100M")
    return role, years, salary


def _money(value):
    return f"${value:.1f}M"


def _evaluate(conn, offer, role, years, salary, rng):
    """The team's response to the driver's proposed terms."""
    team = S.team_map(conn)[offer["team_id"]]["name"]
    ceiling = offer["ceiling_role"]
    role_gap = _role_index(role) - _role_index(ceiling)
    lo, hi = offer["min_years"], offer["max_years"]
    max_salary = offer["max_salary"]
    years_ok = lo <= years <= hi
    if role_gap <= 0 and years_ok and salary <= max_salary:
        conn.execute("UPDATE offers SET role=?, years=?, salary=?, final=1, stage=? WHERE id=?",
                     (role, years, salary, "Terms agreed", offer["id"]))
        _log(conn, offer["id"], "team", "agree",
             rng.choice([f"{team} can work with that. Terms agreed. Sign when you're ready.",
                         f"Deal. {team} accept your terms. The contract is on the table.",
                         f"{team} are happy with that. Put pen to paper and it's done."]),
             role, years, salary)
        return "agreed"

    greedy = salary > max_salary * 1.4 or role_gap >= 2 or years < lo - 1 or years > hi + 1
    patience = (offer["patience"] or 0) - (2 if greedy else 1)
    if patience < 0:
        conn.execute("UPDATE offers SET status=?, stage=?, patience=0, responded_at=? WHERE id=?",
                     (C.OFFER_COLLAPSED, "Talks collapsed", now_iso(), offer["id"]))
        _log(conn, offer["id"], "team", "walk",
             f"{team} have walked away. " + ("They felt the demands were unrealistic." if greedy
                                              else "They weren't prepared to keep haggling."))
        return "collapsed"

    new_role = C.CONTRACT_ROLES[min(_role_index(role), _role_index(ceiling))]
    new_years = int(S.clamp(years, lo, hi))
    current = offer["salary"] or 0
    if salary <= max_salary:
        new_salary = salary
    else:
        new_salary = round(max(current, current + (max_salary - current) * 0.6), 1)
    notes = []
    if role_gap > 0:
        notes.append(f"{ceiling} is as far as we can go on status" if ceiling != "No. 2"
                     else "we can't promise more than a No. 2 role")
    if years < lo or years > hi:
        notes.append(f"we're only comfortable with {lo}-{hi} year{'s' if hi != 1 else ''}"
                     if lo != hi else f"it has to be a {lo}-year deal")
    if salary > max_salary:
        notes.append(f"we can stretch to {_money(new_salary)}")
    final = patience == 0
    stage = "Final offer" if final else "Counter-offer"
    lead = "That's a big ask. " if greedy else ""
    body = "; ".join(notes)
    message = lead + f"{team}: " + body[:1].upper() + body[1:] + "."
    if final:
        message += " This is our final offer."
    conn.execute("UPDATE offers SET role=?, years=?, salary=?, patience=?, final=?, stage=? WHERE id=?",
                 (new_role, new_years, new_salary, patience, int(final), stage, offer["id"]))
    _log(conn, offer["id"], "team", "counter", message, new_role, new_years, new_salary)
    return "final" if final else "countered"


def counter_offer(conn, offer_id, role, years, salary, message="", rng=None):
    rng = rng or random.Random()
    offer = _open_offer(conn, offer_id)
    if offer["final"]:
        raise S.ValidationError("This is a final offer. You can sign it or walk away, but not counter.")
    role, years, salary = parse_terms(role, years, salary)
    _log(conn, offer_id, "driver", "counter", (message or "").strip()[:500], role, years, salary)
    conn.execute("UPDATE offers SET stage = ? WHERE id = ?", ("Negotiating", offer_id))
    result = _evaluate(conn, get_offer(conn, offer_id), role, years, salary, rng)
    if result == "collapsed":
        feed.on_talks_collapsed(conn, offer_id, "news")
        ensure_lifeline(conn, offer["window_id"], offer["driver_id"], rng)
    return result


def approaches_left(conn, window_id, driver_id):
    used = conn.execute("SELECT COUNT(*) FROM offers WHERE window_id = ? AND driver_id = ? AND origin = 'driver'",
                        (window_id, driver_id)).fetchone()[0]
    return max(0, C.APPROACHES_PER_WINDOW - used)


def approachable_teams(conn, window_id, driver_id):
    """Teams this driver hasn't already dealt with in this window."""
    window = conn.execute("SELECT * FROM market_windows WHERE id = ?", (window_id,)).fetchone()
    talked = {r[0] for r in conn.execute("SELECT team_id FROM offers WHERE window_id = ? AND driver_id = ?",
                                         (window_id, driver_id))}
    signed = signed_team_ids(conn, window["target_year"])
    return [t for t in S.teams(conn) if t["id"] not in talked
            and not _full_of_players(conn, window["season_id"], t["id"], signed)]


def approach_team(conn, window_id, driver_id, team_id, role=None, years=None, salary=None, message="", rng=None):
    """A player driver contacts a team. The team decides whether to talk, and on what terms."""
    rng = rng or random.Random()
    window = conn.execute("SELECT * FROM market_windows WHERE id = ?", (window_id,)).fetchone()
    if not window or window["status"] != C.WINDOW_OPEN:
        raise S.ValidationError("The transfer window is closed")
    if conn.execute("SELECT 1 FROM offers WHERE window_id = ? AND driver_id = ? AND status = ?",
                    (window_id, driver_id, C.OFFER_ACCEPTED)).fetchone():
        raise S.ValidationError("You've already signed a deal in this window")
    if approaches_left(conn, window_id, driver_id) <= 0:
        raise S.ValidationError(f"You've used all {C.APPROACHES_PER_WINDOW} approaches for this window")
    if team_id not in {t["id"] for t in approachable_teams(conn, window_id, driver_id)}:
        raise S.ValidationError("You can't approach that team right now (already in talks, or no seat for you)")
    has_terms = role not in (None, "")
    if has_terms:
        role, years, salary = parse_terms(role, years, salary)

    season_id = window["season_id"]
    standings = {r["driver_id"]: r for r in S.driver_standings(conn, season_id)}
    ranks = S.team_strength_ranks(conn, season_id)
    me = driver_value(conn, season_id, driver_id, standings, ranks)
    exp = experience(conn, driver_id)
    rank = ranks[team_id]
    my_team = S.driver_seats(conn, season_id).get(driver_id, (None,))[0]
    interest = me["value"] - team_bar(rank) + rng.uniform(-JITTER, JITTER) + (3 if team_id == my_team else 0)
    if exp == "Rookie" and rank > len(ranks) - 5:
        interest = max(interest, 1.0 + rng.uniform(0, 3))  # backmarkers will talk to any rookie
    team = S.team_map(conn)[team_id]["name"]
    note = (message or "").strip()[:500] or "Is there a seat for me?"

    if exp == "Rookie" and rank <= 3:
        verdict = f"{team} don't sign rookies straight into a race seat. Come back with a season under your belt."
    elif interest < -6:
        verdict = rng.choice([f"{team} thank you for reaching out, but you're not on their list.",
                              f"{team} are going in a different direction.",
                              f"{team} say it's not the right time."])
    else:
        verdict = None
    if verdict:
        offer_id = conn.execute(
            """INSERT INTO offers(window_id, driver_id, team_id, role, years, salary, interest, reason, status,
               created_at, responded_at, origin, stage, patience, final) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (window_id, driver_id, team_id, role or "No. 2", years or 1, salary, round(interest, 1), verdict,
             C.OFFER_REJECTED, now_iso(), now_iso(), "driver", "Not interested", 0, 1)).lastrowid
        _log(conn, offer_id, "driver", "approach", note, role if has_terms else None,
             years if has_terms else None, salary if has_terms else None)
        _log(conn, offer_id, "team", "reject", verdict)
        ensure_lifeline(conn, window_id, driver_id, rng)
        return offer_id, "rejected"

    if interest < 0:
        reason = f"{team} weren't planning to add anyone, but they'll offer a one-year trial."
        offer_id = _create_offer(conn, window_id, season_id, driver_id, team_id, interest, reason, rng, standings,
                                 ranks, origin="driver", stage="Trial offer", final=True,
                                 terms=("No. 2", 1, _floor_salary(rank)))
        _log(conn, offer_id, "driver", "approach", note, role if has_terms else None,
             years if has_terms else None, salary if has_terms else None)
        o = get_offer(conn, offer_id)
        _log(conn, offer_id, "team", "offer", reason + " Take it or leave it.", o["role"], o["years"], o["salary"])
        return offer_id, "trial"

    reason = f"{team} are interested and open to talks."
    offer_id = _create_offer(conn, window_id, season_id, driver_id, team_id, interest, reason, rng, standings,
                             ranks, origin="driver", rookie=exp == "Rookie", stage="Talks")
    _log(conn, offer_id, "driver", "approach", note, role if has_terms else None,
         years if has_terms else None, salary if has_terms else None)
    if has_terms:
        result = _evaluate(conn, get_offer(conn, offer_id), role, years, salary, rng)
        if result == "collapsed":
            ensure_lifeline(conn, window_id, driver_id, rng)
        return offer_id, result
    o = get_offer(conn, offer_id)
    _log(conn, offer_id, "team", "offer", f"{team} would like to open talks. Here's where they'd start.",
         o["role"], o["years"], o["salary"])
    return offer_id, "offer"


def ensure_lifeline(conn, window_id, driver_id, rng=None):
    """When a driver has run out of options, the weakest team with room offers one final seat.

    Out of options = nothing pending, nothing signed and no approaches left. Only one lifeline per
    window; if that is turned down too, the driver keeps their current seat (or sits out as a reserve,
    keeping their Reputation) and the Race Master can still place them by hand.
    """
    rng = rng or random.Random()
    busy = conn.execute("SELECT 1 FROM offers WHERE window_id = ? AND driver_id = ? AND status IN (?, ?)",
                        (window_id, driver_id, C.OFFER_PENDING, C.OFFER_ACCEPTED)).fetchone()
    if busy or approaches_left(conn, window_id, driver_id) > 0:
        return None
    if conn.execute("SELECT 1 FROM offers WHERE window_id = ? AND driver_id = ? AND lifeline = 1",
                    (window_id, driver_id)).fetchone():
        return None
    window = conn.execute("SELECT * FROM market_windows WHERE id = ?", (window_id,)).fetchone()
    season_id = window["season_id"]
    ranks = S.team_strength_ranks(conn, season_id)
    signed = signed_team_ids(conn, window["target_year"])
    burned = {r[0] for r in conn.execute(
        "SELECT team_id FROM offers WHERE window_id = ? AND driver_id = ? AND status IN (?, ?)",
        (window_id, driver_id, C.OFFER_COLLAPSED, C.OFFER_REJECTED))}
    options = [t for t in sorted(ranks, key=lambda t: -ranks[t])
               if not _full_of_players(conn, season_id, t, signed)]
    if not options:
        return None
    team_id = next((t for t in options if t not in burned), options[0])
    team = S.team_map(conn)[team_id]["name"]
    reason = f"Word travels fast. {team} have heard you're still looking and offer one last lifeline."
    offer_id = _create_offer(conn, window_id, season_id, driver_id, team_id, 0.0, reason, rng, None, ranks,
                             stage="Last-chance offer", final=True, lifeline=True,
                             terms=("No. 2", 1, _floor_salary(ranks[team_id])))
    o = get_offer(conn, offer_id)
    _log(conn, offer_id, "team", "offer", reason, o["role"], o["years"], o["salary"])
    feed.notify(conn, driver_id, f"Last-chance offer: {team} have a seat if you want it", "garage")
    return offer_id


def decline_offer(conn, offer_id, rng=None):
    offer = get_offer(conn, offer_id)
    if not offer or offer["status"] != C.OFFER_PENDING:
        raise S.ValidationError("That offer is no longer available")
    conn.execute("UPDATE offers SET status = ?, stage = ?, responded_at = ? WHERE id = ?",
                 (C.OFFER_DECLINED, "Declined", now_iso(), offer_id))
    _log(conn, offer_id, "driver", "decline", "Thanks, but no thanks.")
    ensure_lifeline(conn, offer["window_id"], offer["driver_id"], rng)


def accept_offer(conn, offer_id):
    offer = _open_offer(conn, offer_id)
    stamp = now_iso()
    conn.execute("UPDATE offers SET status = ?, stage = ?, responded_at = ? WHERE id = ?",
                 (C.OFFER_ACCEPTED, "Signed", stamp, offer_id))
    _log(conn, offer_id, "driver", "sign", "Signed.", offer["role"], offer["years"], offer["salary"])
    for other in conn.execute("SELECT id FROM offers WHERE window_id = ? AND driver_id = ? AND status = ?",
                              (offer["window_id"], offer["driver_id"], C.OFFER_PENDING)).fetchall():
        _log(conn, other["id"], "system", "withdrawn", "Signed elsewhere.")
    conn.execute("""UPDATE offers SET status = ?, stage = ?, responded_at = ? WHERE window_id = ? AND driver_id = ?
                    AND status = ?""", (C.OFFER_WITHDRAWN, "Signed elsewhere", stamp, offer["window_id"],
                                        offer["driver_id"], C.OFFER_PENDING))
    signed = signed_team_ids(conn, offer["target_year"])
    if signed.count(offer["team_id"]) >= 2:
        conn.execute("""UPDATE offers SET status = ?, stage = ?, responded_at = ? WHERE window_id = ? AND team_id = ?
                        AND status = ?""", (C.OFFER_WITHDRAWN, "Seats filled", stamp, offer["window_id"],
                                            offer["team_id"], C.OFFER_PENDING))
    team = S.team_map(conn)[offer["team_id"]]
    salary = f", {_money(offer['salary'])}/yr" if offer["salary"] is not None else ""
    conn.execute("""INSERT INTO contracts(season_id, driver_id, team_id, negotiation_stage, requested_role,
                    team_response, outcome, conditions, notes, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                 (offer["window_season"], offer["driver_id"], offer["team_id"], "Signed", offer["role"],
                  "Offer accepted", f"Signed with {team['name']} from {offer['target_year']}",
                  f"{offer['years']}-year deal{salary}", offer["reason"], stamp))
    feed.on_signed(conn, offer, "news")
    apply_signings(conn)
    return offer


def _season_for_year(conn, year):
    row = conn.execute("SELECT id FROM seasons WHERE year = ?", (year,)).fetchone()
    return row["id"] if row else None


def apply_signings(conn):
    """Move accepted players into their new seats once their target season exists."""
    pending = conn.execute("""SELECT o.*, w.target_year FROM offers o JOIN market_windows w ON w.id = o.window_id
                              WHERE o.status = ? AND o.applied = 0 ORDER BY o.responded_at, o.id""",
                           (C.OFFER_ACCEPTED,)).fetchall()
    for offer in pending:
        season_id = _season_for_year(conn, offer["target_year"])
        if not season_id:
            continue
        seats = S.driver_seats(conn, season_id)
        current = seats.get(offer["driver_id"])
        if not current or current[0] != offer["team_id"]:
            target = _seat_to_take(conn, season_id, offer["team_id"], offer["driver_id"])
            others = {pid: seats.get(pid) for pid in (p["id"] for p in S.player_drivers(conn))
                      if pid != offer["driver_id"]}
            targets = {offer["driver_id"]: target}
            targets.update({pid: seat for pid, seat in others.items()})
            S.place_players(conn, season_id, targets)
        conn.execute("UPDATE offers SET applied = 1 WHERE id = ?", (offer["id"],))


def _seat_to_take(conn, season_id, team_id, driver_id):
    """The seat of the team's lower-valued AI driver."""
    gmap = S.grid_map(conn, season_id)
    players = {d["id"] for d in S.player_drivers(conn)}
    options = []
    for seat in (1, 2):
        did = gmap.get((team_id, seat))
        if did in players and did != driver_id:
            continue
        rep = S.starting_reputation(conn, season_id, did) if did else -1
        options.append((rep, seat))
    if not options:
        raise S.ValidationError("That team has no seat available")
    options.sort()
    return (team_id, options[0][1])


def on_new_season(conn, season_id):
    """Close windows aimed at earlier years and apply signings for the new season."""
    year = S.get_season(conn, season_id)["year"]
    for w in conn.execute("SELECT id FROM market_windows WHERE status = ? AND target_year <= ?",
                          (C.WINDOW_OPEN, year)).fetchall():
        close_window(conn, w["id"])
    apply_signings(conn)


def maybe_open_silly_season(conn, season_id):
    """Auto-open the next-year market once half the calendar is complete."""
    evs = S.events(conn, season_id)
    done = sum(1 for e in evs if e["status"] == C.EVENT_COMPLETE)
    if not evs or done < math.ceil(len(evs) / 2):
        return None
    year = S.get_season(conn, season_id)["year"] + 1
    if conn.execute("SELECT 1 FROM market_windows WHERE target_year = ?", (year,)).fetchone():
        return None
    if target_year(conn, season_id) != year:
        return None
    return open_window(conn, season_id, kind="Silly Season")


def windows(conn):
    return [dict(r) for r in conn.execute("""SELECT w.*, s.year AS season_year FROM market_windows w
                                             JOIN seasons s ON s.id = w.season_id ORDER BY w.id DESC""")]


def offers(conn, driver_id=None, window_id=None):
    sql = """SELECT o.*, w.target_year, w.kind, w.status AS window_status FROM offers o
             JOIN market_windows w ON w.id = o.window_id WHERE 1=1"""
    params = []
    if driver_id is not None:
        sql += " AND o.driver_id = ?"
        params.append(driver_id)
    if window_id is not None:
        sql += " AND o.window_id = ?"
        params.append(window_id)
    sql += " ORDER BY o.window_id DESC, o.status = 'Pending' DESC, o.id"
    tmap, dmap = S.team_map(conn), S.driver_map(conn)
    out = []
    for r in conn.execute(sql, params):
        r = dict(r)
        r["team"] = tmap[r["team_id"]]
        r["driver"] = dmap[r["driver_id"]]
        r["end_year"] = r["target_year"] + r["years"] - 1
        r["messages"] = [dict(m) for m in conn.execute(
            "SELECT * FROM offer_messages WHERE offer_id = ? ORDER BY id", (r["id"],))]
        r["mood"] = mood(r)
        out.append(r)
    return out


def mood(offer):
    if offer["status"] != C.OFFER_PENDING:
        return None
    if offer["stage"] == "Terms agreed":
        return "Terms agreed"
    if offer["final"]:
        return "Final offer"
    if offer["patience"] is None or offer["patience"] >= 2:
        return "Open to talks"
    return "Losing patience"


def current_contract(conn, driver_id):
    row = conn.execute("""SELECT o.*, w.target_year FROM offers o JOIN market_windows w ON w.id = o.window_id
                          WHERE o.driver_id = ? AND o.status = ? ORDER BY w.target_year DESC, o.id DESC LIMIT 1""",
                       (driver_id, C.OFFER_ACCEPTED)).fetchone()
    if not row:
        return None
    row = dict(row)
    row["team"] = S.team_map(conn)[row["team_id"]]
    row["end_year"] = row["target_year"] + row["years"] - 1
    return row
