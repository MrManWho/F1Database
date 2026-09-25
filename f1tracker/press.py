"""The press pen (v2.3): pre-race questions while the paddock is open, and a larger bank of post-race
questions picked from what actually happened (qualifying to finish, Sprint, fastest lap, pole, DNFs, points
droughts, teammates, the title fight, the transfer window).

Every answer nudges the relationship with the team a little (within the same cap as before: see
relations.add_bonus) and some make headlines. Questions for a driver and a round never change once picked:
they come from the results, the calendar and a fixed seed, not from the clock. Rounds submitted before 2.3
keep the questions they were given then (teamlife.legacy_keys).

Question text and headlines can use {driver}, {team}, {mate}, {rival}, {event}, {pos}, {quali}, {gain},
{sprint}, {target} and {champ}; they're filled in for each driver.
"""

import random

from . import constants as C
from . import services as S

# key: (question, [(answer key, answer, relationship effect, headline or None)])
POST = {
    "win": ("Race winner! What made the difference today?", [
        ("car", "The team gave me a rocket ship. This one's for them", 2, None),
        ("me", "Pure driving. Nobody could touch me", -2, "{driver}: \"Nobody could touch me\""),
        ("strategy", "The pit wall nailed the strategy", 2, None)]),
    "podium": ("P{pos} and a podium. Is this where you belong?", [
        ("every", "Every weekend, if the car lets me", 0, None),
        ("team", "It's a team result. They deserve this", 2, None),
        ("should_win", "Honestly, I should have won", -1, "{driver} frustrated despite a podium at {event}")]),
    "gain": ("You started P{quali} and finished P{pos}: {gain} places gained. How did you do it?", [
        ("attack", "Kept it clean and attacked when it mattered", 1, None),
        ("strategy", "The strategy call was perfect. Credit to the pit wall", 2, None),
        ("quali", "I should never have been that far back. Qualifying let me down", 0, None)]),
    "lost": ("You started P{quali} but finished P{pos}. What happened?", [
        ("tyres", "The tyres fell away. We'll learn from it", 1, None),
        ("strategy", "The strategy cost us today", -2, "{driver} questions {team} strategy after {event}"),
        ("me", "My mistakes, simple as that", 1, None)]),
    "pole": ("Pole position on Saturday. How special was that lap?", [
        ("car", "The car was on rails. Brilliant work from the team", 2, None),
        ("best", "One of the best laps of my life", 0, None),
        ("sunday", "It's only a lap. Sunday is what counts", 1, None)]),
    "fastest": ("You set the fastest lap. Worth the risk?", [
        ("points", "Every tenth matters when you're chasing performance", 1, None),
        ("show", "Just showing what we could have done all race", -1, None),
        ("call", "The team called for it and it was the right call", 2, None)]),
    "sprint_good": ("P{sprint} in the Sprint. Did it set up your weekend?", [
        ("confidence", "It gave us confidence for Sunday", 1, None),
        ("bonus", "Sprint points are a bonus. The Grand Prix is what matters", 0, None),
        ("shows", "It shows what I can do when the car works", -1, None)]),
    "sprint_bad": ("The Sprint didn't go your way. What went wrong?", [
        ("cautious", "I was too cautious. I'll attack more next time", 1, None),
        ("grip", "The car had no grip at all", -2, "{driver} unhappy with the {team} car after the Sprint"),
        ("short", "Short race. One mistake and it's gone", 0, None)]),
    "first_points": ("First points of the season! Relief?", [
        ("thanks", "Huge relief. Thanks to everyone at the team", 2, None),
        ("time", "About time, frankly", -1, None),
        ("start", "It's just the start", 1, None)]),
    "drought": ("Another race without points. How long can this go on?", [
        ("work", "We keep working. It'll turn", 1, None),
        ("change", "Something has to change at this team", -3, "{driver} demands change at {team}"),
        ("me", "I have to find more myself", 1, None)]),
    "dnf_again": ("Another early finish. Is something wrong?", [
        ("luck", "Bad luck comes in waves. It'll pass", 0, None),
        ("reliability", "Reliability is costing us a fortune", -3, "{driver} hits out at {team} reliability again"),
        ("me", "I need to look at my side of it too", 1, None)]),
    "dotd": ("The fans made you Driver of the Day. What does that mean to you?", [
        ("team", "It's for the whole team", 2, None),
        ("results", "Nice, but I want results, not votes", 0, None),
        ("deserved", "The fans know who's doing the work", -1, "{driver}: \"The fans know who's doing the work\"")]),
    "solid": ("Solid points in P{pos}. Happy with that?", [
        ("points", "Points are points. Great job, team", 2, None),
        ("more", "We should be further up the road", -1, None),
        ("build", "It's a building block for the next one", 1, None)]),
    "last": ("You were the last finisher today. Where do you go from here?", [
        ("up", "Only up. We'll go through everything", 1, None),
        ("miles", "The car is miles off", -3, "{driver}: \"The car is miles off\""),
        ("tomorrow", "Tough day. Tomorrow's another one", 0, None)]),
    "title": ("You're {champ} in the championship. Can you win it?", [
        ("one", "One race at a time", 1, None),
        ("year", "Absolutely. This is our year", 0, "{driver} declares title ambitions"),
        ("develop", "Only if the team keeps developing the car", -1, None)]),
    "target_hit": ("You delivered the team's target ({target}). Was the bar too low?", [
        ("raise", "Raise it next time. I'm ready", 1, None),
        ("right", "It was the right target. Job done", 1, None),
        ("more", "They should expect a lot more from me", 0, None)]),
    "target_missed": ("You missed the team's target ({target}). What's the message to them?", [
        ("sorry", "I let them down. I'll make it right", 2, None),
        ("unrealistic", "It wasn't realistic with this car", -2, "{driver} says {team} targets are unrealistic"),
        ("next", "Next race. Move on", 0, None)]),
    "mate_battle": ("{mate} was right with you all race. How close is this rivalry?", [
        ("close", "Close, and it makes us both faster", 2, None),
        ("ahead", "I'm ahead where it matters", -1, "{driver} fires shot at teammate {mate}"),
        ("focus", "I only focus on my own race", 0, None)]),
}

PRE = {
    "pre_expect": ("What's realistic for you at {event}?", [
        ("points", "Points are the target", 1, None),
        ("win", "We're here to win", 0, "{driver}: \"We're here to win\" at {event}"),
        ("struggle", "Honestly, the car will struggle here", -2, "{driver} downplays {team}'s chances at {event}")]),
    "pre_bounce": ("Your last race ended early. Can you bounce back?", [
        ("focus", "It's behind us. Full focus on this one", 2, None),
        ("hold", "I just need the car to hold together", -2, "{driver} questions {team} reliability before {event}"),
        ("incident", "It was a racing incident. Nothing changes", 1, None)]),
    "pre_momentum": ("You were on the podium last time out. Can you do it again?", [
        ("pace", "Why not? We've shown the pace", 1, None),
        ("realistic", "That was special. Let's be realistic", 0, None),
        ("every", "I expect it every week now", -1, "{driver} expects podiums every week")]),
    "pre_mate_ahead": ("You've had the edge over {mate} this season. Who's on top this weekend?", [
        ("me", "Me, and I'll prove it again", -1, "{driver} fires warning at {mate}"),
        ("push", "We push each other and the team wins", 2, None),
        ("self", "I only focus on myself", 1, None)]),
    "pre_mate_behind": ("{mate} has had the edge this season. Is that about to change?", [
        ("now", "Starting this weekend", 1, None),
        ("setup", "They've had the better setup. Let's see it equal", -2, "{driver} hints at unequal treatment at {team}"),
        ("learn", "They've done a great job. I'm learning", 1, None)]),
    "pre_target": ("Your weekend target: \"{target}\". Can you deliver?", [
        ("deliver", "Yes. I'll deliver it", 2, None),
        ("stretch", "It's a stretch with this car", -1, None),
        ("higher", "I'm aiming higher than that", 0, "{driver} aims beyond {team}'s target")]),
    "pre_sprint": ("It's a Sprint weekend. Do you like the format?", [
        ("more", "More racing, more chances to score", 1, None),
        ("lottery", "It punishes anyone who takes a risk", 0, None),
        ("gimmick", "It's a gimmick", -1, "{driver} slams the Sprint format")]),
    "pre_market": ("The transfer window is open. Is your head in the right place?", [
        ("focused", "Fully focused on this team", 2, None),
        ("management", "My management handles all that", 0, None),
        ("rivals", "The big teams know where to find me", -3, "{driver} puts rival teams on alert")]),
    "pre_drought": ("It's been a while since you scored. What has to change?", [
        ("details", "Small details. We're close", 1, None),
        ("upgrades", "The car needs upgrades, simple as that", -2, "{driver} calls for upgrades at {team}"),
        ("me", "Me. I need to execute better", 2, None)]),
    "pre_title": ("You're {champ} in the championship. Feeling the pressure?", [
        ("privilege", "Pressure is a privilege", 1, None),
        ("long", "Not at all. It's a long season", 1, None),
        ("others", "The others should be feeling it", -1, "{driver} turns up the heat in the title fight")]),
    "pre_rival": ("{rival} is right behind you in the standings. Any message?", [
        ("respect", "Respect. May the best driver win", 1, None),
        ("bring", "They'd better bring their A-game", 0, "{driver} sends a message to {rival}"),
        ("ignore", "I don't think about them", 0, None)]),
    "pre_chase": ("You're chasing {rival} in the standings. Can you catch them?", [
        ("yes", "Watch this space", 0, "{driver} vows to catch {rival}"),
        ("own", "I just run my own race", 1, None),
        ("car", "Only if the team gives me the tools", -2, None)]),
    "pre_opener": ("First race of the season. What are the expectations?", [
        ("learn", "Learn the car and build steadily", 1, None),
        ("points", "Hit the ground running. Points from day one", 1, None),
        ("behind", "The car isn't where it should be yet", -2, "{driver} warns {team} is behind at the season opener")]),
    "pre_backmarker": ("The car's been near the back. Is a point possible here?", [
        ("victory", "Every point would feel like a victory", 2, None),
        ("chaos", "Only if the others hit trouble", 0, None),
        ("no", "Not with this car", -3, "{driver} writes off {team}'s chances")]),
    "pre_frontrunner": ("You've got one of the fastest cars. Is anything less than a win a failure?", [
        ("granted", "We take nothing for granted", 1, None),
        ("yes", "Yes. We have to win", 0, "{driver}: \"Anything less than a win is a failure\""),
        ("driver", "It's the driver who makes the difference", -1, None)]),
    "pre_setup": ("How has the team got on with the setup this week?", [
        ("found", "We've found something. I'm excited", 1, None),
        ("balance", "Still searching for the right balance", 0, None),
        ("wrong", "I think we're going in the wrong direction", -2, "{driver} worried by {team}'s setup direction")]),
    "pre_mood": ("How are you feeling going into the race?", [
        ("sharp", "Sharp and ready", 1, None),
        ("race", "Enough talking. Let's race", -1, None),
        ("team", "Confident in the work the team has done", 2, None)]),
    "pre_track": ("What's the key to a good result at {event}?", [
        ("quali", "Qualifying. Track position is everything here", 1, None),
        ("tyres", "Looking after the tyres", 1, None),
        ("brave", "Being braver than everyone else", 0, None)]),
}

ALL = {**POST, **PRE}

# v2.5 (engine 3): a negative effect is for arrogance, blame or damaging the team in public, never for an honest
# assessment. These answers are re-rated (the headlines stay); everything else keeps its effect. Engine 3 then
# counts every press effect at C.V3_PRESS_SHARE (50%).
V3_EFFECTS = {
    ("fastest", "show"): 0, ("first_points", "time"): 0, ("solid", "more"): 0, ("title", "develop"): 0,
    ("pre_expect", "struggle"): 0, ("pre_target", "stretch"): 0, ("pre_mood", "race"): 0,
    ("pre_opener", "behind"): -1, ("pre_setup", "wrong"): -1,
}


def effect_v3(question, answer, stored):
    """The relationship effect of a press answer under engine 3 (re-rated where needed, then halved)."""
    base = V3_EFFECTS.get((question, answer), stored or 0)
    return base * C.V3_PRESS_SHARE
# Stories that can come round again week after week; the big ones (a win, a DNF) are always asked about.
REPEATABLE_LEADS = {"drought", "wrong", "solid", "credit", "last"}
PRE_PER_DRIVER = 2


def is_pre(key):
    return (key or "").startswith("pre_")


class _Facts(dict):
    def __missing__(self, key):
        return ""


def _fill(text, facts):
    try:
        return text.format_map(_Facts(facts))
    except (ValueError, IndexError):
        return text


def _season_rounds(conn, event):
    return [dict(r) for r in conn.execute("SELECT * FROM events WHERE season_id = ? ORDER BY round_number",
                                          (event["season_id"],))]


def _points(conn, row, event):
    if not row:
        return 0
    from . import calc3
    return calc3.Points(conn).total(row)


def _facts(conn, event, driver_id, before=False):
    """Everything the questions can mention, for one driver at one round. before=True uses the standings as they
    were before this round (pre-race), otherwise including it, so the questions never change afterwards."""
    dmap = S.driver_map(conn)
    seat = S.driver_seats(conn, event["season_id"]).get(driver_id)
    team = S.team_map(conn).get(seat[0]) if seat else None
    mate_id = S.grid_map(conn, event["season_id"]).get((seat[0], 2 if seat[1] == 1 else 1)) if seat else None
    facts = {"driver": dmap[driver_id]["name"] if driver_id in dmap else "The driver",
             "team": team["name"] if team else "the team", "event": event["name"],
             "mate": dmap[mate_id]["name"] if mate_id in dmap else "your teammate", "mate_id": mate_id,
             "team_id": team["id"] if team else None, "rival": "", "pos": "", "quali": "", "gain": 0, "sprint": "",
             "target": "", "champ": ""}
    upto = event["round_number"] - 1 if before else event["round_number"]
    standings = S.driver_standings(conn, event["season_id"], upto_round=upto, completed_only=True) if upto > 0 else []
    me = next((r for r in standings if r["driver_id"] == driver_id), None)
    if me and me["points"] > 0:
        facts["champ_pos"] = me["position"]
        facts["champ"] = {1: "leading", 2: "second", 3: "third"}.get(me["position"], f"P{me['position']}")
        players = [r for r in standings if r["driver_id"] != driver_id and dmap.get(r["driver_id"], {}).get("is_player")]
        close = [r for r in players if abs(r["points"] - me["points"]) <= 15]
        if close:
            other = min(close, key=lambda r: abs(r["points"] - me["points"]))
            facts["rival"] = dmap[other["driver_id"]]["name"]
            facts["rival_ahead"] = other["position"] < me["position"]
    return facts


def _recent(conn, event, driver_id, count=3):
    """This driver's results in the season's completed rounds before `event`, newest first."""
    rows = []
    for e in reversed(_season_rounds(conn, event)):
        if e["round_number"] >= event["round_number"] or e["status"] != C.EVENT_COMPLETE:
            continue
        r = conn.execute("SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (e["id"], driver_id)).fetchone()
        if r and r["result_status"] in C.START_STATUSES:
            rows.append((e, r))
        if len(rows) >= count:
            break
    return rows


def _asked_last_round(conn, event, driver_id, pre):
    """Question keys this driver was asked (and answered) at the previous round of the season. Only answers that
    can't change any more count, so a driver's questions never shift while they're open: pre-race answers close
    at that round's lights out; post-race ones count if given before this round was submitted."""
    prev = conn.execute("SELECT id FROM events WHERE season_id = ? AND round_number < ? ORDER BY round_number DESC LIMIT 1",
                        (event["season_id"], event["round_number"])).fetchone()
    if not prev:
        return set()
    if pre:
        rows = conn.execute("SELECT question FROM press_answers WHERE event_id = ? AND driver_id = ? AND question LIKE 'pre_%'",
                            (prev["id"], driver_id))
    else:
        rows = conn.execute("SELECT question FROM press_answers WHERE event_id = ? AND driver_id = ? "
                            "AND question NOT LIKE 'pre_%' AND created_at <= ?",
                            (prev["id"], driver_id, event.get("submitted_at") or "9999"))
    return {r["question"] for r in rows}


def _pick(rng, pool, n):
    pool = list(dict.fromkeys(pool))
    rng.shuffle(pool)
    return pool[:n]


def _mate_record(conn, event, driver_id, mate_id):
    """(ahead, behind) against the teammate in this season's completed rounds before `event`."""
    ahead = behind = 0
    for e, r in _recent(conn, event, driver_id, count=99):
        m = conn.execute("SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (e["id"], mate_id)).fetchone()
        if not (m and r["race_position"] and m["race_position"] and r["result_status"] == C.STATUS_FINISHED
                and m["result_status"] == C.STATUS_FINISHED):
            continue
        ahead += r["race_position"] < m["race_position"]
        behind += r["race_position"] > m["race_position"]
    return ahead, behind


def pre_keys(conn, event, driver_id):
    """The pre-race questions for this driver at this round (always the same two)."""
    from . import teamlife
    facts = _facts(conn, event, driver_id, before=True)
    recent = _recent(conn, event, driver_id)
    rng = random.Random(f"pre-{event['id']}-{driver_id}")
    first, pool = [], ["pre_expect", "pre_setup", "pre_mood", "pre_track"]
    if event["round_number"] == 1 or not recent:
        first.append("pre_opener")
    if recent:
        last_e, last = recent[0]
        if last["result_status"] != C.STATUS_FINISHED:
            first.append("pre_bounce")
        elif last["race_position"] and last["race_position"] <= 3:
            first.append("pre_momentum")
        if len(recent) >= 3 and all(_points(conn, r, e) == 0 for e, r in recent[:3]):
            first.append("pre_drought")
    if facts["mate_id"]:
        ahead, behind = _mate_record(conn, event, driver_id, facts["mate_id"])
        if ahead + behind >= 2:
            pool.append("pre_mate_ahead" if ahead >= behind else "pre_mate_behind")
    if teamlife.settings(conn)["targets"]:
        # Whether it's asked depends only on targets being on, so choosing a target never changes the questions.
        t = teamlife.target_for(conn, event["id"], driver_id) or teamlife.options_for(conn, event["id"], driver_id).get("standard")
        facts["target"] = t["label"] if t else "a strong result"
        pool.append("pre_target")
    if event["is_sprint"]:
        pool.append("pre_sprint")
    if conn.execute("SELECT 1 FROM market_windows WHERE status = ?", (C.WINDOW_OPEN,)).fetchone():
        pool.append("pre_market")
    if facts.get("champ_pos") and facts["champ_pos"] <= 3 and event["round_number"] >= 3:
        pool.append("pre_title")
    if facts["rival"]:
        pool.append("pre_chase" if facts.get("rival_ahead") else "pre_rival")
    ranks = S.team_strength_ranks(conn, event["season_id"])
    if facts["team_id"] in ranks:
        n = len(ranks)
        if ranks[facts["team_id"]] > n - 3:
            pool.append("pre_backmarker")
        elif ranks[facts["team_id"]] <= 3:
            pool.append("pre_frontrunner")
    # The press move on: nothing asked at the last round is asked again straight away (if there's anything else).
    recent_keys = _asked_last_round(conn, event, driver_id, pre=True)
    first = [k for k in first if k not in recent_keys]
    pool = [k for k in pool if k not in recent_keys] or pool
    keys = _pick(rng, first, 1)
    keys += [k for k in _pick(rng, pool + first, PRE_PER_DRIVER + 2) if k not in keys]
    return keys[:PRE_PER_DRIVER], facts


def post_keys(conn, event, driver_id):
    """The two post-race questions for this driver at this round (v2.3 bank)."""
    from . import teamlife
    row = conn.execute("SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (event["id"], driver_id)).fetchone()
    if not row or row["result_status"] not in C.START_STATUSES:
        return [], {}
    facts = _facts(conn, event, driver_id)
    recent = _recent(conn, event, driver_id)
    rng = random.Random(f"post-{event['id']}-{driver_id}")
    finished = row["result_status"] == C.STATUS_FINISHED and row["race_position"]
    pos, quali = row["race_position"], row["qualifying_position"]
    facts.update(pos=pos or "", quali=quali or "", sprint=row["sprint_position"] or "")
    runners = [r["race_position"] for r in conn.execute(
        "SELECT race_position FROM results WHERE event_id = ? AND result_status = ? AND race_position IS NOT NULL",
        (event["id"], C.STATUS_FINISHED))]
    pts_now = _points(conn, row, event)
    earlier_pts = sum(_points(conn, r, e) for e, r in _recent(conn, event, driver_id, count=99))
    # The headline question: the biggest story of this driver's race.
    if not finished:
        lead = "dnf_again" if any(r["result_status"] != C.STATUS_FINISHED for _e, r in recent[:2]) else "dnf"
    elif pos == 1:
        lead = "win"
    elif pos <= 3:
        lead = "podium"
    elif quali and quali - pos >= 5:
        lead = "gain"
    elif quali and pos - quali >= 5:
        lead = "lost"
    elif pts_now and not earlier_pts and event["round_number"] > 1:
        lead = "first_points"
    elif not pts_now and len(recent) >= 2 and all(_points(conn, r, e) == 0 for e, r in recent[:2]):
        lead = "drought"
    elif runners and pos == max(runners) and len(runners) > 5:
        lead = "last"
    elif pos > 10:
        lead = "wrong"
    elif pos >= 7:
        lead = "solid"
    else:
        lead = "credit"
    if quali and pos:
        facts["gain"] = quali - pos
    # A second question from the rest of the weekend.
    pool = ["next"]
    if quali == 1 and lead != "win":
        pool.append("pole")
    if row["fastest_lap"]:
        pool.append("fastest")
    if row["driver_of_day"]:
        pool.append("dotd")
    if event["is_sprint"]:
        if row["sprint_status"] == C.STATUS_FINISHED and row["sprint_position"] and row["sprint_position"] <= 3:
            pool.append("sprint_good")
        elif row["sprint_status"] != C.STATUS_FINISHED or (row["sprint_position"] or 99) > 10:
            pool.append("sprint_bad")
    mate = conn.execute("SELECT * FROM results WHERE event_id = ? AND driver_id = ?", (event["id"], facts["mate_id"])
                        ).fetchone() if facts["mate_id"] else None
    if finished and mate and mate["result_status"] == C.STATUS_FINISHED and mate["race_position"]:
        gap = mate["race_position"] - pos
        pool.append("mate_battle" if abs(gap) == 1 else "beat_mate" if gap > 0 else "lost_mate")
    t = teamlife.target_for(conn, event["id"], driver_id)
    if t and t["status"] in ("Hit", "Missed"):
        facts["target"] = t["label"]
        pool.append("target_hit" if t["status"] == "Hit" else "target_missed")
    if conn.execute("SELECT 1 FROM market_windows WHERE status = ?", (C.WINDOW_OPEN,)).fetchone():
        pool.append("future")
    standings_pos = facts.get("champ_pos")
    if standings_pos and standings_pos <= 3 and event["round_number"] >= 3:
        pool.append("title")
    recent_keys = _asked_last_round(conn, event, driver_id, pre=False)
    pool = [k for k in pool if k not in recent_keys] or ["next"]
    if lead in recent_keys and lead in REPEATABLE_LEADS:
        # Same story as last time (another pointless afternoon, another P12): ask about something else.
        extra = [k for k in ("wrong", "solid", "credit", "last") if k != lead and k not in recent_keys]
        pool += extra[:1]
        lead = None
    second = [k for k in _pick(rng, [k for k in pool if k != lead], 4)]
    specific = [k for k in second if k != "next"]
    if lead is None:
        keys = (specific + ["next"])[:2]
    else:
        keys = [lead] + (specific[:1] or ["next"])
    return keys, facts


def build(keys, facts, bank):
    return [{"key": k, "text": _fill(bank[k][0], facts),
             "answers": [{"key": a, "text": _fill(t, facts), "effect": e} for a, t, e, _h in bank[k][1]]}
            for k in keys]
