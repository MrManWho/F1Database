"""SQLite schema and forward-only save migrations."""

from .constants import SCHEMA_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    abbreviation TEXT NOT NULL,
    color TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    baseline_reputation REAL NOT NULL DEFAULT 50,
    is_player INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY,
    year INTEGER UNIQUE NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS season_grid (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    seat_no INTEGER NOT NULL CHECK (seat_no IN (1, 2)),
    driver_id INTEGER REFERENCES drivers(id),
    PRIMARY KEY (season_id, team_id, seat_no),
    UNIQUE (season_id, driver_id)
);

CREATE TABLE IF NOT EXISTS season_driver_state (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id),
    starting_reputation REAL NOT NULL,
    locked_reputation REAL,
    PRIMARY KEY (season_id, driver_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    is_sprint INTEGER NOT NULL DEFAULT 0,
    ai_difficulty INTEGER,
    status TEXT NOT NULL DEFAULT 'Not Run',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE (season_id, round_number)
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    qualifying_position INTEGER,
    sprint_position INTEGER,
    sprint_status TEXT NOT NULL DEFAULT 'Not Run',
    race_position INTEGER,
    result_status TEXT NOT NULL DEFAULT 'Not Run',
    fastest_lap INTEGER NOT NULL DEFAULT 0,
    driver_of_day INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT,
    UNIQUE (event_id, driver_id)
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id),
    team_id INTEGER REFERENCES teams(id),
    negotiation_stage TEXT NOT NULL,
    requested_role TEXT NOT NULL,
    team_response TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    conditions TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_windows (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    target_year INTEGER NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    opened_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    window_id INTEGER NOT NULL REFERENCES market_windows(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    role TEXT NOT NULL,
    years INTEGER NOT NULL DEFAULT 1,
    interest REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Pending',
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    responded_at TEXT,
    salary REAL,
    origin TEXT NOT NULL DEFAULT 'team',
    stage TEXT NOT NULL DEFAULT 'Offer',
    patience INTEGER,
    final INTEGER NOT NULL DEFAULT 0,
    lifeline INTEGER NOT NULL DEFAULT 0,
    ceiling_role TEXT,
    min_years INTEGER,
    max_years INTEGER,
    max_salary REAL
);

CREATE TABLE IF NOT EXISTS offer_messages (
    id INTEGER PRIMARY KEY,
    offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    action TEXT NOT NULL,
    role TEXT,
    years INTEGER,
    salary REAL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS career_members (
    username TEXT PRIMARY KEY,
    driver_id INTEGER REFERENCES drivers(id)
);

CREATE TABLE IF NOT EXISTS team_seasons (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    car_rating REAL NOT NULL,
    change REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (season_id, team_id)
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY,
    season_id INTEGER REFERENCES seasons(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    headline TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    link TEXT,
    driver_id INTEGER REFERENCES drivers(id),
    team_id INTEGER REFERENCES teams(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    driver_id INTEGER REFERENCES drivers(id),
    text TEXT NOT NULL,
    link TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_reads (
    username TEXT PRIMARY KEY,
    last_seen_id INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_results_event ON results(event_id);
CREATE INDEX IF NOT EXISTS idx_results_driver ON results(driver_id);
CREATE INDEX IF NOT EXISTS idx_events_season ON events(season_id);
CREATE INDEX IF NOT EXISTS idx_offers_driver ON offers(driver_id);
CREATE INDEX IF NOT EXISTS idx_offer_messages ON offer_messages(offer_id);
"""

OFFER_V5_COLUMNS = [
    ("salary", "REAL"),
    ("origin", "TEXT NOT NULL DEFAULT 'team'"),
    ("stage", "TEXT NOT NULL DEFAULT 'Offer'"),
    ("patience", "INTEGER"),
    ("final", "INTEGER NOT NULL DEFAULT 0"),
    ("lifeline", "INTEGER NOT NULL DEFAULT 0"),
    ("ceiling_role", "TEXT"),
    ("min_years", "INTEGER"),
    ("max_years", "INTEGER"),
    ("max_salary", "REAL"),
]

REQUIRED_TABLES = {"meta", "drivers", "teams", "seasons", "events", "results"}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn):
    """Bring any older save forward to SCHEMA_VERSION without discarding data.

    v1 -> v2: results.sprint_status (existing Sprint positions become Finished).
    v2 -> v3: events.ai_difficulty (blank for existing rounds).
    v3 -> v4: transfer market tables and career membership (created empty).
    v4 -> v5: negotiation columns on offers plus the offer_messages log. Older offers get their
              team limits filled in the first time someone negotiates on them.
    v5 -> v6: car ratings per team and season, the paddock news feed and notifications. Car
              ratings for existing seasons are seeded from the team order when first needed.
    """
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "meta" in tables:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row and row[0] == str(SCHEMA_VERSION) and "team_seasons" in tables:
            return
    conn.executescript(SCHEMA)
    if "sprint_status" not in _columns(conn, "results"):
        conn.execute("ALTER TABLE results ADD COLUMN sprint_status TEXT NOT NULL DEFAULT 'Not Run'")
        conn.execute(
            "UPDATE results SET sprint_status = CASE WHEN sprint_position IS NOT NULL "
            "THEN 'Finished' ELSE 'Not Run' END"
        )
    if "ai_difficulty" not in _columns(conn, "events"):
        conn.execute("ALTER TABLE events ADD COLUMN ai_difficulty INTEGER")
    offer_columns = _columns(conn, "offers")
    for name, ddl in OFFER_V5_COLUMNS:
        if name not in offer_columns:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {ddl}")
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
