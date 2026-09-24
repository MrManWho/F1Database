"""Team talks (v2.1): teams read what you write to them, and can interview you.

Everything runs locally: no AI service, no network. A message is read for themes (commitment, development,
results, teamwork, respect, pointing to your record) and tone (arrogance, blaming others, shouting). Each team has
its own taste, from where its car is plus one thing it cares about most (the same all season in a league), so
drivers have to learn what each team likes. What you say can tip a team that's on the fence, but it can never
make a team sign someone far below their bar: the effect is small and capped, and hard rules (top teams don't
sign rookies) still apply.
"""

import random
import re

THEMES = {
    "commitment": ("Commitment", ["long term", "long-term", "commit", "loyal", "stay", "multi-year", "multi year",
                                  "years with", "build with", "project", "future with", "invest in", "home"]),
    "development": ("Development", ["learn", "improve", "develop", "grow", "potential", "feedback", "simulator",
                                    "sim work", "engineers", "setup", "set-up", "data", "work hard", "hard work",
                                    "young", "progress"]),
    "results": ("Results", ["win", "wins", "podium", "points", "championship", "title", "fastest", "pole",
                            "quick", "pace", "results", "beat", "top ten", "top 10", "front"]),
    "teamwork": ("Teamwork", ["team player", "support", "help the team", "for the team", "teammate", "together",
                              "number two", "no. 2", "no 2", "wingman", "whatever the team", "team first",
                              "constructors"]),
    "respect": ("Respect", ["respect", "honoured", "honored", "privilege", "grateful", "thank", "admire",
                            "history", "legacy", "proud", "opportunity"]),
    "record": ("Your record", ["last season", "this season", "scored", "finished", "average", "consistent",
                               "consistency", "beat my teammate", "outqualified", "qualified", "improved"]),
}
ARROGANT = ["best driver", "deserve", "better than", "carry", "greatest", "obviously", "must give", "demand",
            "or else", "you need me", "i'm the best", "im the best", "too good", "waste of", "only reason"]
BLAME = ["car was rubbish", "car is rubbish", "car was slow", "slow car", "terrible car", "bad car", "team's fault",
         "teams fault", "team was bad", "useless team", "awful team", "not my fault", "blame"]
NEGATIONS = {"not", "never", "don't", "dont", "no", "won't", "wont", "can't", "cant", "nothing", "isn't", "isnt"}

# What teams care about by where their car is: top teams want results and teamwork, the midfield wants
# results and commitment, the back of the grid wants people who'll develop and stay.
TASTES = {
    "top": {"results": 1.0, "teamwork": 0.8, "respect": 0.5, "record": 0.7, "development": 0.2, "commitment": 0.3},
    "mid": {"results": 0.8, "commitment": 0.7, "record": 0.6, "development": 0.5, "teamwork": 0.4, "respect": 0.4},
    "back": {"development": 1.0, "commitment": 0.9, "teamwork": 0.6, "respect": 0.5, "record": 0.4, "results": 0.3},
}
PITCH_MAX = 3.0          # interest points a message can add or take away
INTERVIEW_MAX = 5.0      # an interview is more work, so it can matter a little more


def _has(text, phrase):
    """The phrase is there, as whole words, and not negated in the five words before it (same sentence)."""
    for m in re.finditer(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text):
        sentence = re.split(r"[.!?;]", text[:m.start()])[-1]
        before = re.sub(r"[^a-z' ]", " ", sentence).split()[-5:]
        if not NEGATIONS.intersection(before):
            return True
    return False


def analyse(message):
    """What a message says: themes found, tone problems, and a plain summary of what the team heard."""
    raw = (message or "").strip()
    text = " " + re.sub(r"\s+", " ", raw.lower()) + " "
    found = {key for key, (_label, words) in THEMES.items() if any(_has(text, w) for w in words)}
    arrogant = sum(1 for w in ARROGANT if w in text)
    blame = sum(1 for w in BLAME if w in text)
    letters = [c for c in raw if c.isalpha()]
    shouting = len(letters) >= 12 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.6 or "!!!" in raw
    words = len(raw.split())
    return {"themes": sorted(found), "arrogant": arrogant, "blame": blame, "shouting": bool(shouting),
            "words": words, "empty": words < 4}


def taste(conn, team_id, rank, teams_total):
    """This team's preferences: by car position, plus one favourite theme (fixed per team in this league)."""
    from .storage import get_meta
    tier = "top" if rank <= 3 else "back" if rank > teams_total - 4 else "mid"
    weights = dict(TASTES[tier])
    seed = f"{get_meta(conn, 'career_id') or ''}-{team_id}"
    favourite = random.Random(seed).choice(sorted(THEMES))
    weights[favourite] = weights.get(favourite, 0.3) + 0.6
    return {"tier": tier, "weights": weights, "favourite": favourite}


def score(reading, team_taste):
    """-1..1: how well the message landed with this team."""
    if reading["empty"]:
        return 0.0
    w = team_taste["weights"]
    good = sum(w.get(t, 0.2) for t in reading["themes"])
    s = min(1.0, good / 2.2)
    s -= 0.45 * min(2, reading["arrogant"]) + 0.35 * min(2, reading["blame"]) + (0.25 if reading["shouting"] else 0)
    if not reading["themes"] and not (reading["arrogant"] or reading["blame"]):
        s = 0.0
    return max(-1.0, min(1.0, round(s, 2)))


def reaction(team, reading, s, team_taste):
    """What the team says back about your message (one sentence)."""
    if reading["empty"]:
        return ""
    labels = [THEMES[t][0].lower() for t in reading["themes"]]
    if reading["arrogant"]:
        return f"{team} didn't enjoy the attitude in your message."
    if reading["blame"]:
        return f"{team} noticed you blaming others. Teams want drivers who own their results."
    if s >= 0.5:
        fav = THEMES[team_taste["favourite"]][0].lower()
        extra = f" {fav.capitalize()} is exactly what they're looking for." if team_taste["favourite"] in reading["themes"] else ""
        return f"{team} liked what you said about {', '.join(labels)}.{extra}"
    if s > 0:
        return f"{team} took note of what you said about {', '.join(labels)}."
    if labels:
        return f"{team} heard you on {', '.join(labels)}, but it isn't what they're after."
    return ""


def message_effect(conn, team_id, rank, teams_total, message, team_name):
    """(interest change, score, reaction sentence, reading) for a message sent to a team."""
    reading = analyse(message)
    t = taste(conn, team_id, rank, teams_total)
    s = score(reading, t)
    return round(s * PITCH_MAX, 2), s, reaction(team_name, reading, s, t), reading


# --------------------------------------------------------------------------- interviews

QUESTIONS = [
    ("Why do you want to drive for us?", [
        ("I want to build something long term with this team", "commitment"),
        ("I want to fight for wins and podiums", "results"),
        ("This team can help me become a better driver", "development"),
        ("Honestly, you're the best seat available", None)]),
    ("How do you handle a bad weekend?", [
        ("I go through the data with my engineers and fix it", "development"),
        ("I own it, and I bounce back at the next race", "record"),
        ("It's usually the car's fault", "blame"),
        ("I focus on getting the team its points", "teamwork")]),
    ("Your teammate is faster at the next race. What do you do?", [
        ("Learn from their data and close the gap", "development"),
        ("Help the team get the best result for both cars", "teamwork"),
        ("Beat them next time, whatever it takes", "results"),
        ("Ask for their setup and complain if I don't get it", "arrogant")]),
    ("What would you bring to this team?", [
        ("Consistent points every weekend", "record"),
        ("Raw speed", "results"),
        ("Loyalty: I'll stay and grow with you", "commitment"),
        ("A big name for your sponsors", None)]),
    ("How would you describe your last season?", [
        ("I learned a lot and kept improving", "development"),
        ("Better than people think: look at the numbers", "record"),
        ("I deserved a much better car", "arrogant"),
        ("I always put the team first", "teamwork")]),
    ("What does this team mean to you?", [
        ("It's an honour to be considered", "respect"),
        ("A place to win", "results"),
        ("A home for the next few years", "commitment"),
        ("Just another seat", None)]),
    ("Would you accept a No. 2 role?", [
        ("Yes, if it helps the team", "teamwork"),
        ("For now, while I prove myself", "development"),
        ("Only if I get a shot at No. 1 later", "results"),
        ("No, I'm too good for that", "arrogant")]),
]

GOALS = {
    "points": "Score points regularly",
    "beat_mate": "Beat my teammate over the season",
    "top_half": "Average a top-ten finish",
    "podiums": "Fight for podiums",
    "develop": "Develop the car and learn",
}


def interview_questions(conn, window_id, driver_id, team_id, n=4):
    """The questions this team asks this driver in this window (always the same four, so a refresh doesn't
    reshuffle them)."""
    rng = random.Random(f"{window_id}-{driver_id}-{team_id}")
    picks = rng.sample(range(len(QUESTIONS)), n)
    out = []
    for qi in picks:
        text, answers = QUESTIONS[qi]
        order = list(range(len(answers)))
        rng.shuffle(order)
        out.append({"id": qi, "text": text, "answers": [{"id": ai, "text": answers[ai][0]} for ai in order]})
    return out


def last_season(conn, driver_id):
    """This driver's most recent season with results: average finish, points share and teammate record."""
    from . import services as S
    for season in reversed(S.list_seasons(conn)):
        rows = [dict(r) for r in conn.execute(
            """SELECT r.* FROM results r JOIN events e ON e.id = r.event_id WHERE e.season_id = ? AND r.driver_id = ?
               AND e.status = 'Complete' AND r.result_status != 'Not Run'""", (season["id"], driver_id))]
        if len(rows) < 3:
            continue
        finishes = [r["race_position"] for r in rows if r["result_status"] == "Finished" and r["race_position"]]
        return {"year": season["year"], "rounds": len(rows),
                "avg": round(sum(finishes) / len(finishes), 1) if finishes else None,
                "points_rate": round(sum(1 for f in finishes if f <= 10) / len(rows), 2),
                "podiums": sum(1 for f in finishes if f <= 3)}
    return None


def _goal_realism(goal, record):
    """+1 a goal the record backs up, 0 unknown/modest, -1 a goal the record says is a bluff."""
    if not record or record["avg"] is None:
        return 0
    avg, rate, podiums = record["avg"], record["points_rate"], record["podiums"]
    if goal == "podiums":
        return 1 if podiums >= 2 or avg <= 6 else -1 if avg > 12 else 0
    if goal == "top_half":
        return 1 if avg <= 10 else -1 if avg > 15 else 0
    if goal == "points":
        return 1 if rate >= 0.4 else -1 if rate < 0.1 and avg > 16 else 0
    return 0


def interview_score(conn, window_id, driver_id, team_id, rank, teams_total, answers, goal):
    """(interest change, score -1..1, feedback lines) for a finished interview."""
    t = taste(conn, team_id, rank, teams_total)
    qs = {q["id"]: q for q in interview_questions(conn, window_id, driver_id, team_id)}
    if set(answers) != set(qs):
        raise ValueError("Answer every question")
    total, lines = 0.0, []
    for qi, ai in answers.items():
        text, options = QUESTIONS[qi]
        if not 0 <= ai < len(options):
            raise ValueError("Answer every question")
        theme = options[ai][1]
        if theme in ("arrogant", "blame"):
            total -= 0.8
            lines.append(f"“{options[ai][0]}” went down badly.")
        elif theme:
            v = t["weights"].get(theme, 0.2)
            total += v
            if v >= 1.0:
                lines.append(f"They loved “{options[ai][0]}”.")
    s = total / (len(answers) * 1.1)
    record = last_season(conn, driver_id)
    realism = _goal_realism(goal, record)
    if goal == "develop" and t["tier"] == "back" or goal == "beat_mate" and t["tier"] == "top":
        s += 0.15
    if realism > 0:
        s += 0.2
        lines.append(f"Your {record['year']} season backs up your goal.")
    elif realism < 0:
        s -= 0.3
        lines.append(f"Your {record['year']} season (average P{record['avg']}) doesn't back up that goal.")
    s = max(-1.0, min(1.0, round(s, 2)))
    return round(s * INTERVIEW_MAX, 2), s, lines
