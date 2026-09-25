"""Static universe data and rule tables for Paddock Legacy."""

APP_NAME = "Paddock Legacy"
APP_VERSION = "3.0.1"
POLICY_EFFECTIVE = "24 September 2026"
# Bumped whenever a release changes how a driver's numbers are worked out (see impacts.py).
CALC_VERSION = 4
SCHEMA_VERSION = 21

GRID_SIZE = 22
SEATS_PER_TEAM = 2
MAX_POSITION = 22

ROOKIE_REPUTATION = 45.0     # every human player driver starts here
MAX_PLAYERS = 11             # human player drivers per league

# (name, code, colour, driver 1, driver 2) in default team order.
TEAMS = [
    ("McLaren", "MCL", "#ff8700", "Lando Norris", "Oscar Piastri"),
    ("Mercedes", "MER", "#00d2be", "George Russell", "Kimi Antonelli"),
    ("Ferrari", "FER", "#e8002d", "Charles Leclerc", "Lewis Hamilton"),
    ("Red Bull Racing", "RBR", "#3671c6", "Max Verstappen", "Isack Hadjar"),
    ("Racing Bulls", "RB", "#6692ff", "Liam Lawson", "Arvid Lindblad"),
    ("Alpine", "ALP", "#ff87bc", "Pierre Gasly", "Franco Colapinto"),
    ("Haas", "HAS", "#b6babd", "Esteban Ocon", "Oliver Bearman"),
    ("Audi", "AUD", "#f50537", "Nico Hulkenberg", "Gabriel Bortoleto"),
    ("Williams", "WIL", "#64c4ff", "Carlos Sainz", "Alexander Albon"),
    ("Aston Martin", "AMR", "#358c75", "Fernando Alonso", "Lance Stroll"),
    ("Cadillac", "CAD", "#d6b25e", "Sergio Perez", "Valtteri Bottas"),
]

BASELINE_REPUTATION = {
    "Max Verstappen": 97,
    "Lewis Hamilton": 93,
    "Charles Leclerc": 92,
    "Lando Norris": 92,
    "Oscar Piastri": 91,
    "Fernando Alonso": 91,
    "George Russell": 89,
    "Carlos Sainz": 86,
    "Kimi Antonelli": 82,
    "Alexander Albon": 82,
    "Sergio Perez": 82,
    "Valtteri Bottas": 80,
    "Pierre Gasly": 80,
    "Esteban Ocon": 78,
    "Nico Hulkenberg": 78,
    "Isack Hadjar": 76,
    "Oliver Bearman": 75,
    "Liam Lawson": 74,
    "Lance Stroll": 74,
    "Gabriel Bortoleto": 73,
    "Franco Colapinto": 70,
    "Arvid Lindblad": 66,
}

# (round, name, location, sprint)
CALENDAR = [
    (1, "Australian GP", "Melbourne", False),
    (2, "Chinese GP", "Shanghai", True),
    (3, "Japanese GP", "Suzuka", False),
    (4, "Bahrain GP", "Sakhir", False),
    (5, "Saudi Arabian GP", "Jeddah", False),
    (6, "Miami GP", "Miami", True),
    (7, "Canadian GP", "Montreal", True),
    (8, "Monaco GP", "Monaco", False),
    (9, "Barcelona-Catalunya GP", "Barcelona", False),
    (10, "Austrian GP", "Spielberg", False),
    (11, "British GP", "Silverstone", True),
    (12, "Belgian GP", "Spa-Francorchamps", False),
    (13, "Hungarian GP", "Budapest", False),
    (14, "Dutch GP", "Zandvoort", True),
    (15, "Italian GP", "Monza", False),
    (16, "Madrid GP", "Madrid", False),
    (17, "Azerbaijan GP", "Baku", False),
    (18, "Singapore GP", "Marina Bay", True),
    (19, "United States GP", "Austin", False),
    (20, "Mexico City GP", "Mexico City", False),
    (21, "São Paulo GP", "Interlagos", False),
    (22, "Las Vegas GP", "Las Vegas", False),
    (23, "Qatar GP", "Lusail", False),
    (24, "Abu Dhabi GP", "Yas Marina", False),
]

GP_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
SPRINT_POINTS = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}

STATUS_NOT_RUN = "Not Run"
STATUS_FINISHED = "Finished"
STATUS_CLASSIFIED = "Classified"   # v2.5: a classified retirement (retired, but classified on distance: may score)
RESULT_STATUSES = [STATUS_NOT_RUN, STATUS_FINISHED, STATUS_CLASSIFIED, "DNF", "DNS", "DSQ"]
OVERRIDE_STATUSES = ["Auto", STATUS_CLASSIFIED, "DNF", "DNS", "DSQ"]
OVERRIDE_STATUSES_V2 = ["Auto", "DNF", "DNS", "DSQ"]          # what rounds judged by calculation version 2 offer
START_STATUSES = {STATUS_FINISHED, STATUS_CLASSIFIED, "DNF", "DSQ"}
CLASSIFIED_STATUSES = {STATUS_FINISHED, STATUS_CLASSIFIED}   # a classified position: may score points
STATUS_LABELS = {STATUS_FINISHED: "Finished", STATUS_CLASSIFIED: "Classified retirement", "DNF": "DNF (unclassified)",
                 "DNS": "DNS", "DSQ": "DSQ", STATUS_NOT_RUN: "Not run", "Auto": "Auto"}

# v2.5: points for a Grand Prix stopped early, by distance completed (the current F1 scale), plus a manual option.
GP_DISTANCES = {
    "full": ("Full points (75% or more)", GP_POINTS),
    "75": ("50–75% distance", {1: 19, 2: 14, 3: 12, 4: 9, 5: 8, 6: 6, 7: 5, 8: 3, 9: 2, 10: 1}),
    "50": ("25–50% distance", {1: 13, 2: 10, 3: 8, 4: 6, 5: 5, 6: 4, 7: 3, 8: 2, 9: 1}),
    "25": ("Two laps to 25% distance", {1: 6, 2: 4, 3: 3, 4: 2, 5: 1}),
    "none": ("No points (under two laps)", {}),
    "manual": ("Manual points (typed in per driver)", None),
}
SPRINT_MIN_DISTANCE = 50       # % of the Sprint that must be completed for Sprint points (league setting)

EVENT_NOT_RUN = "Not Run"
EVENT_IN_PROGRESS = "In Progress"
EVENT_COMPLETE = "Complete"

SEASON_ACTIVE = "Active"
SEASON_COMPLETE = "Complete"

MIN_YEAR, MAX_YEAR = 2020, 2100
MIN_DIFFICULTY, MAX_DIFFICULTY = 0, 110

NEGOTIATION_STAGES = [
    "Interest", "Initial Contact", "Negotiating", "Offer Made", "Signed", "Rejected", "On Hold",
]
REQUESTED_ROLES = ["No. 1", "No. 2", "Equal Status", "Any Race Seat", "Reserve"]

MARKET_TIERS = [
    (90, "Elite", "Championship-defining status"),
    (82, "Front-runner", "Top-team level"),
    (74, "Established", "Proven F1 value"),
    (64, "Prospect", "High-upside market piece"),
    (0, "Developing", "Building career capital"),
]

# Offers / transfer market
OFFER_PENDING = "Pending"
OFFER_ACCEPTED = "Accepted"
OFFER_DECLINED = "Declined"
OFFER_EXPIRED = "Expired"
OFFER_WITHDRAWN = "Withdrawn"
OFFER_COLLAPSED = "Collapsed"   # the team walked away from talks
OFFER_REJECTED = "Rejected"     # the team turned down a driver's approach
CONTRACT_ROLES = ["No. 2", "Equal Status", "No. 1"]   # lowest to highest status
MAX_CONTRACT_YEARS = 5
APPROACHES_PER_WINDOW = 3
WINDOW_OPEN = "Open"
WINDOW_CLOSED = "Closed"
MAX_OFFERS_PER_WINDOW = 4
ROOKIE_OFFERS = 3

# Difficulty recommender
# v2.1 adaptive recommendation: no round minimum and no fixed one-point step. Each player's recent results are
# turned into the level they'd be comfortable at; agreement between players decides how far it moves.
# v2.2: reacts faster than 2.1 (which moved about 2 levels a round even when a player was clearly on top).
DIFF_SPAN = 25               # levels a perfect weekend (score +1) says you could handle above the level used
DIFF_ROUND_CAP = 15          # the most one round can say about a player's comfortable level
DIFF_DEADBAND = 0.08         # scores this close to 0 mean "about right"
DIFF_RECENT_HALF_LIFE = 2.5  # rounds; recent rounds matter most
DIFF_RECENT_ROUNDS = 10      # usable rounds looked at
DIFF_MAX_STEP = 8            # never recommend a bigger jump than this in one go
DIFF_MIXED = 0.5             # players disagree (one struggling, one fine): move half as far
DIFF_CONFIDENCE_K = 0.75     # evidence weight w gives confidence w / (w + K): one round already moves over half way
DIFF_PLACES = 8              # v2.3.1: places better (or worse) than the car's expected finish for a full +1 (or -1)
DIFF_POINTS_SCALE = 15       # points above (or below) what the car's expected finish would score for a full +1
DIFF_VERDICT = 1.0           # levels away from the current one before a player counts as struggling / comfortable
# v2.4.1: how a round is judged. "car": against the car's expected finish only (2.4). "overall": against the middle
# of the grid, whatever the car. "blend" (default): DIFF_OVERALL_SHARE of each. In every mode the level is never
# raised while any player driver is struggling, on the blended or the overall reading.
DIFF_MODES = {"blend": "Blend (half car, half overall)", "car": "Car only (against the car's expected finish)",
              "overall": "Overall (against the middle of the grid)"}
DIFF_MODE_DEFAULT = "blend"
DIFF_OVERALL_SHARE = 0.5
DIFF_BACK = 5.0             # levels below the one used, against the whole grid, that count as "near the back"
                            # (about P16 or worse on a 22-car grid, qualifying there too): the level won't go up
# Where a level sits for a typical player (the game's own bands; most players are comfortable around 82).
DIFF_BANDS = [(1, 40, "Beginner"), (41, 65, "Casual"), (66, 99, "Intermediate / Advanced"), (100, 110, "Expert")]
DIFF_MIN_ROUNDS = 3
DIFF_MAX_ROUNDS = 5
DIFF_THRESHOLD = 0.35
DIFF_SENSITIVITY = 0.05      # performance score per difficulty point (sweet-spot model)
DIFF_SWEETSPOT_SPREAD = 10   # max distance one round may pull the sweet spot
DIFF_HALF_LIFE = 12          # rounds; older evidence fades but is never discarded

# Login protection
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_MINUTES = 10

# Automatic backups
AUTO_BACKUPS_KEPT = 20
AUTO_BACKUP_EVERY_HOURS = 24

# Car ratings (team development)
CAR_RATING_TOP, CAR_RATING_STEP = 94.0, 2.6   # default: fastest car 94, each rank 2.6 lower
CAR_RATING_MIN, CAR_RATING_MAX = 50.0, 99.0

# Screenshot import
IMPORT_MODEL = "claude-opus-5"

# What someone can ask to be in a league (join requests) and what the Race Master can grant.
LEAGUE_ROLES = {
    "driver": "Driver",
    "driver_scorekeeper": "Driver + Scorekeeper",
    "scorekeeper": "Scorekeeper only",
    "spectator": "Spectator (view only)",
}

# League features the Race Master can switch on or off (League settings, and when creating a league).
# key -> (label, description, default)
FEATURES = {
    "checkin": ("Race-night check-in", "Members say whether they're in for the next race. Handy for bigger leagues.", False),
    "comments": ("Comments & reactions", "Comment and react on race weekends and news, and vote for the fans' Driver of the Day.", True),
    "predictions": ("Predictions game", "Pick pole, winner and fastest lap before each race and climb the predictions table.", True),
}

CHECKIN_CHOICES = {"in": "I'm in", "maybe": "Maybe", "out": "Can't make it"}
REACTIONS = ["🔥", "👏", "😂", "😬", "🏆", "💀"]

# Predictions: points for each correct pick
PREDICTION_POINTS = {"pole": 3, "winner": 5, "fastest_lap": 2, "top_player": 2}

AVATAR_MAX_BYTES = 2 * 1024 * 1024

# Contracts: instead of money, a driver pledges how much they'll grow. Targets are set against what the
# car should manage (a slow car isn't expected to win), so the pledge is fair at every team.
# form: Form above the car's baseline by season end; rep: Reputation gained over the season.
# Growth pledges are judged on average finishing position against the car. "share" is how much of the gap
# between the car's expected finish and P1 the driver promises to close, so every car has the same headroom
# in proportion. "reward" is the Reputation added to next season's start for keeping the pledge.
GROWTH_LEVELS = [
    {"name": "Steady", "share": 0.0, "reward": 0.5, "blurb": "Deliver what the car is capable of"},
    {"name": "Solid", "share": 0.12, "reward": 1.0, "blurb": "Beat the car's expected results"},
    {"name": "Strong", "share": 0.25, "reward": 1.75, "blurb": "Clearly outperform the machinery"},
    {"name": "Breakout", "share": 0.40, "reward": 2.5, "blurb": "A season people talk about"},
]
PLEDGE_DROP_AFTER = 5     # from this many rounds, the worst weekend doesn't count toward the pledge
PLEDGE_UNIT_SHARE = 0.12  # one "step" of pledge performance, as a share of the car's headroom (min 0.6 places)

# Team relationship (0-100) bands, best first: (minimum score, status)
RELATION_BANDS = [(80, "Delighted"), (55, "Happy"), (40, "Concerned"), (25, "Unhappy"), (0, "Seat at risk")]
RELATION_START = 60.0

# Relationship extras: press answers and team orders nudge the score directly (capped).
RELATION_EXTRA_CAP = 15.0
TEAM_ORDER_IGNORED = -6.0
TEAM_ORDER_OBEYED = 2.0
# Team orders: "off" (never issued; the default), "advisory" (shown, but no effect or headlines), "on" (judged).
TEAM_ORDER_MODES = {"off": "Off", "advisory": "Advisory (shown, no effect)", "on": "On (judged, affects your standing)"}
# Weekend targets: one per player driver per round, judged from the results.
TARGET_HIT = 2.0          # a Standard target (and every target set before 2.4)
TARGET_MISSED = -1.5
# v2.4: before each weekend a driver chooses one of three targets and locks it in.
TARGET_TIERS = {
    "safe": {"label": "Safe", "hit": 1.0, "miss": -0.5, "blurb": "An easier finish. Small reward, small risk."},
    "standard": {"label": "Standard", "hit": TARGET_HIT, "miss": TARGET_MISSED, "blurb": "What the team expects."},
    "stretch": {"label": "Stretch", "hit": 3.5, "miss": -2.5, "blurb": "A big ask. Big reward if you pull it off."},
}
TARGET_GAP = 3             # places between Safe, Standard and Stretch finishing targets
TARGET_STREAKS = (3, 5, 8, 10)   # consecutive targets hit that make a headline
GATE_NOTE_MIN = 10               # characters a Race Master's gate bypass note needs
GOAL_WEIGHT = 4.0   # each season goal adds or removes this much (scaled by how far into the season)

INCIDENT_RULINGS = {
    "none": "No further action",
    "reprimand": "Reprimand",
    "warning": "Warning",
    "penalty": "Penalty (results adjusted)",
}

# League access roles: ONE per member, stored on career_members.role. The player driver a member controls is
# stored separately (career_members.driver_id), so any role can be combined with a driver except Spectator.
ACCESS_ROLES = {
    "race_master": "Race Master",
    "scorekeeper": "Scorekeeper",
    "member": "Member",
    "spectator": "Spectator",
}
ACCESS_HELP = {
    "race_master": "Runs this league: results, grid, calendar, seasons, market, members and settings.",
    "scorekeeper": "Enters and edits qualifying, Sprint and race results, statuses, fastest lap, Driver of the Day, "
                   "notes and AI difficulty. Can't change a race after submitting it, or any league settings.",
    "member": "Views the whole league. With an assigned driver: their own garage, contracts and team relationship.",
    "spectator": "View only. Can't be assigned a driver.",
}
RESULT_ROLES = {"race_master", "scorekeeper"}

# Persistent player accent colours (separate from team colours), assigned in order to human-controlled drivers.
# Chosen to stay distinguishable from each other on the dark and light themes, not just by red vs green.
PLAYER_COLORS = ["#4aa3ff", "#ffb020", "#c07cff", "#2ec4b6", "#ff6fae", "#9bd14b", "#ff8a3d", "#6d8bff",
                 "#e8d44d", "#48d1f0", "#f2789a", "#b8b8ff"]


# --------------------------------------------------------------------------- v2.5 calculation engine
# The calculation engine is separate from CALC_VERSION (an update counter that makes leagues refresh once).
# Engine 2: every formula as of 2.4.1. Engine 3: the 2.5 rules. Existing leagues stay on engine 2 until the Race
# Master chooses; new leagues start on engine 3. Completed seasons keep the engine they were played under.
ENGINE_LEGACY = 2
ENGINE_CURRENT = 3
NEW_LEAGUE_ENGINE = ENGINE_CURRENT
ENGINE_BLEND_ROUNDS = 6          # Future-only: rounds after the cutoff before the new numbers fully take over

# Engine 3 constants (see docs/CALCULATION_V3.md for every formula)
V3_RANK_PRIOR = 6                # car-strength: weight of the rating rank, in AI Grand Prix entries
V3_RANK_EVIDENCE_CAP = 12        # at most this many AI entries count as evidence
V3_FORM_WINDOW = 6               # recent started rounds in Form and car-adjusted
V3_FORM_DECAY = 0.82             # weight = 0.82 ^ age
V3_H2H_MIN = 3                   # comparisons needed before head-to-head counts
V3_REP_RATE = 0.25               # share of the gap to the performance rating closed in a full season
V3_ROLLOVER_CAP = 4.0            # pledge + team goal Reputation at rollover, kept within +/-4
V3_PLEDGE_FAIL = {0: 0.0, 1: -0.5, 2: -1.0, 3: -1.5}
V3_TEAM_GOALS = {"safe": (0.5, 0.0), "competitive": (2.0, -1.0), "ambitious": (3.0, -2.0)}
V3_GOAL_EFFECT = {"Met": 2.0, "On track": 0.0, "Behind": -3.0, "Not evaluated": 0.0, "Not started": 0.0}
V3_PRESS_SHARE = 0.5
V3_EXTRA_ROUNDS = 6
V3_EXTRA_CAP = 10.0
# v3.0 balance (engine 3): good press answers add at most +2 over the six-weekend window (bad ones still count in
# full), and weekend targets reward risk rather than the safe choice.
V3_PRESS_POSITIVE_CAP = 2.0
# Chosen by simulation (docs/CALCULATION_V3.md §26): Safe pays only a driver below the car's level, Standard pays a
# driver at or above it, Stretch pays one clearly outperforming the car.
V3_TARGET_TIERS = {"safe": (0.25, -0.75), "standard": (1.5, -1.25), "stretch": (3.0, -2.0)}
# v3.0 (engine 3): a kept Steady pledge ("deliver what the car should") is neutral at rollover, and a met Safe team
# goal adds +0.5, so the lowest-risk choices no longer lift Reputation every year. Pledges and team goals chosen
# before 3.0 keep the terms they were chosen under.
V3_PLEDGE_REWARD = {0: 0.0, 1: 1.0, 2: 1.75, 3: 2.5}
V3_ORDER_OBEYED, V3_ORDER_IGNORED = 1.0, -2.0
V3_INTEREST_DIVISOR, V3_INTEREST_MIN, V3_INTEREST_MAX = 5.0, -8.0, 6.0
V3_EMERGENCY_MARGIN = 8.0        # an emergency offer needs Driver Value >= slowest eligible team bar - 8
V3_MAX_COUNTERS = 3
V3_TALK_CAP = 5.0                # message + interview interest effect, combined
V3_NOFAULT_SHARE = 0.10          # no-fault retirements excluded from pledge pace, at most 10% of the season
# AI tracker (engine 3)
AI_QUALI_SCALE = 0.80            # seconds of qualifying gap for a full -1/+1
AI_RACE_SCALE = 0.60             # seconds per lap of race gap for a full -1/+1
AI_WEIGHTS = {"finish": 0.20, "quali_pos": 0.10, "teammate": 0.25, "race_pace": 0.30, "quali_pace": 0.15}
AI_SPRINT_WEIGHT = 0.5
AI_NO_MATE_CONFIDENCE = 0.8
AI_WIDER_CONFIDENCE = 0.7       # v3.0: AI cars two car-strength places either side
AI_EXPECTED_CONFIDENCE = 0.6     # v3.0: no AI car close by: the car's expected finish
AI_EXTREME_GAP = 0.45            # s/lap: a clean session this far off may move up to AI_EXTREME_STEP at once
AI_EXTREME_STEP = 5
AI_STEP_LIMITS = ((1, 3), (3, 4), (10 ** 6, 6))   # (usable weekends up to, max step)
AI_PERSISTENT_STEP = 8
AI_FLAGS = {
    "damage": ("Damage", 0.0), "penalty": ("Major time penalty", 0.0), "mechanical": ("No-fault mechanical issue", 0.0),
    "disconnect": ("Disconnection", 0.0), "weather": ("Wet or changing conditions", 0.25),
    "safety_car": ("Safety-car distortion", 0.25), "strategy": ("Strategy distortion", 0.25),
    "traffic": ("Traffic distortion", 0.75),
}
AI_REPRESENTATIVE_WEIGHT = 0.5   # an excluded session the Race Master marks representative counts at half weight
