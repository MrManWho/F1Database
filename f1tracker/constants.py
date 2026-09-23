"""Static universe data and rule tables for F1 Universe Tracker."""

APP_NAME = "F1 Universe Tracker"
APP_VERSION = "1.6"
SCHEMA_VERSION = 6

GRID_SIZE = 22
SEATS_PER_TEAM = 2
MAX_POSITION = 22

PLAYER_DRIVERS = [("David Conley", 42.0), ("Carson Hayes", 45.0)]

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
RESULT_STATUSES = [STATUS_NOT_RUN, STATUS_FINISHED, "DNF", "DNS", "DSQ"]
OVERRIDE_STATUSES = ["Auto", "DNF", "DNS", "DSQ"]
START_STATUSES = {STATUS_FINISHED, "DNF", "DSQ"}

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
