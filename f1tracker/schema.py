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
    notes TEXT NOT NULL DEFAULT '',
    player_color TEXT
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
    race_at TEXT,
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
    max_salary REAL,
    growth INTEGER,
    min_growth INTEGER
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
    created_at TEXT NOT NULL,
    growth INTEGER
);

CREATE TABLE IF NOT EXISTS career_members (
    username TEXT PRIMARY KEY,
    driver_id INTEGER REFERENCES drivers(id),
    scorekeeper INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TEXT,
    last_active TEXT
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
    created_at TEXT NOT NULL,
    ref TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    driver_id INTEGER REFERENCES drivers(id),
    text TEXT NOT NULL,
    link TEXT,
    created_at TEXT NOT NULL,
    ref TEXT
);

CREATE TABLE IF NOT EXISTS notification_reads (
    username TEXT PRIMARY KEY,
    last_seen_id INTEGER NOT NULL DEFAULT 0,
    cleared_id INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS join_requests (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    driver_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'driver',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS checkins (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (event_id, username)
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    username TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reactions (
    target TEXT NOT NULL,
    username TEXT NOT NULL,
    emoji TEXT NOT NULL,
    PRIMARY KEY (target, username, emoji)
);

CREATE TABLE IF NOT EXISTS fan_votes (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, username)
);

CREATE TABLE IF NOT EXISTS driver_profiles (
    driver_id INTEGER PRIMARY KEY REFERENCES drivers(id) ON DELETE CASCADE,
    number INTEGER,
    nationality TEXT NOT NULL DEFAULT '',
    helmet_color TEXT NOT NULL DEFAULT '',
    avatar TEXT,
    bio TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS predictions (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    pole_id INTEGER,
    winner_id INTEGER,
    fastest_lap_id INTEGER,
    top_player_id INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (event_id, username)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_relations (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    offer_id INTEGER,
    growth INTEGER NOT NULL DEFAULT 0,
    form_base REAL NOT NULL,
    form_target REAL NOT NULL,
    rep_start REAL NOT NULL,
    rep_target REAL NOT NULL,
    score REAL NOT NULL DEFAULT 60,
    status TEXT NOT NULL DEFAULT 'Happy',
    warning_level INTEGER NOT NULL DEFAULT 0,
    released INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    pledged INTEGER NOT NULL DEFAULT 0,
    rebased INTEGER NOT NULL DEFAULT 0,
    bonus REAL NOT NULL DEFAULT 0,
    finish_base REAL,
    finish_target REAL,
    outcome TEXT,
    reward REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (season_id, driver_id)
);

CREATE TABLE IF NOT EXISTS team_goals (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    target INTEGER NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS press_answers (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    effect REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, driver_id, question)
);

CREATE TABLE IF NOT EXISTS team_orders (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    beneficiary_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'Issued',
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, driver_id)
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    reporter TEXT NOT NULL,
    reporter_driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    accused_driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    ruling TEXT,
    ruling_note TEXT NOT NULL DEFAULT '',
    decided_by TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS team_notes (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    tone TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_target ON comments(target);
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
    ("growth", "INTEGER"),
    ("min_growth", "INTEGER"),
]

REQUIRED_TABLES = {"meta", "drivers", "teams", "seasons", "events", "results"}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _assign_player_colors(conn):
    """Give every human-controlled driver without one a persistent accent colour, in the order they joined."""
    from .constants import PLAYER_COLORS
    used = [r[0] for r in conn.execute("SELECT player_color FROM drivers WHERE player_color IS NOT NULL")]
    for (driver_id,) in conn.execute("SELECT id FROM drivers WHERE is_player = 1 AND player_color IS NULL ORDER BY id").fetchall():
        free = [c for c in PLAYER_COLORS if c not in used]
        color = free[0] if free else PLAYER_COLORS[len(used) % len(PLAYER_COLORS)]
        conn.execute("UPDATE drivers SET player_color = ? WHERE id = ?", (color, driver_id))
        used.append(color)


def migrate(conn):
    """Bring any older save forward to SCHEMA_VERSION without discarding data.

    v1 -> v2: results.sprint_status (existing Sprint positions become Finished).
    v2 -> v3: events.ai_difficulty (blank for existing rounds).
    v3 -> v4: transfer market tables and career membership (created empty).
    v4 -> v5: negotiation columns on offers plus the offer_messages log. Older offers get their
              team limits filled in the first time someone negotiates on them.
    v5 -> v6: car ratings per team and season, the paddock news feed and notifications. Car
              ratings for existing seasons are seeded from the team order when first needed.
    v6 -> v7: news and notifications remember what created them (e.g. "window:3"), so deleting a
              transfer window can remove its trail.
    v7 -> v8: join requests, so anyone with a login can ask to join a league.
    v8 -> v9: per-league Scorekeepers (career_members.scorekeeper) and the role asked for in a join request.
    v9 -> v10: race times (events.race_at), check-ins, comments, reactions, fan votes, driver profiles,
               predictions and the Race Master's activity log (all created empty).
    v10 -> v11: contracts are about growth instead of money (offers.growth / min_growth, the growth asked
               for in each message), plus team relationships and team notes. Old salaries are kept but unused.
    v11 -> v12: pledges must be chosen (team_relations.pledged), targets re-based after three rounds, press
               answers and team orders (team_relations.bonus), season goals, incidents. Relationships whose
               contract has no growth pledge are marked unpledged so the driver chooses one.
    v12 -> v13: one league access role per member (career_members.role: race_master / scorekeeper / member /
               spectator) kept separate from the assigned driver; old Scorekeeper ticks become the Scorekeeper
               role and members without a driver become Spectators, so nobody loses access. Human drivers get a
               persistent accent colour (drivers.player_color). Members can hide old notifications (cleared_id).
    v13 -> v14: growth pledges are judged on average finishing position against the car
               (team_relations.finish_base / finish_target), with the season's outcome and Reputation reward
               (outcome, reward). Existing relationships get their finish targets on first use.
    """
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "meta" in tables:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row and row[0] == str(SCHEMA_VERSION) and "join_requests" in tables and "finish_target" in _columns(conn, "team_relations"):
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
    member_cols = _columns(conn, "career_members")
    if "role" not in member_cols:
        conn.execute("ALTER TABLE career_members ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
        conn.execute("ALTER TABLE career_members ADD COLUMN joined_at TEXT")
        conn.execute("ALTER TABLE career_members ADD COLUMN last_active TEXT")
        conn.execute("UPDATE career_members SET role = CASE WHEN scorekeeper = 1 THEN 'scorekeeper' "
                     "WHEN driver_id IS NULL THEN 'spectator' ELSE 'member' END")
    if "player_color" not in _columns(conn, "drivers"):
        conn.execute("ALTER TABLE drivers ADD COLUMN player_color TEXT")
    if "cleared_id" not in _columns(conn, "notification_reads"):
        conn.execute("ALTER TABLE notification_reads ADD COLUMN cleared_id INTEGER NOT NULL DEFAULT 0")
    _assign_player_colors(conn)
    rel_cols = _columns(conn, "team_relations")
    if "pledged" not in rel_cols:
        conn.execute("ALTER TABLE team_relations ADD COLUMN pledged INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE team_relations ADD COLUMN rebased INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE team_relations ADD COLUMN bonus REAL NOT NULL DEFAULT 0")
        conn.execute("UPDATE team_relations SET pledged = 1 WHERE offer_id IN "
                     "(SELECT id FROM offers WHERE growth IS NOT NULL)")
    if "finish_target" not in _columns(conn, "team_relations"):
        # v1.17: pledges are judged on average finish against the car; targets are filled in by relations.ensure.
        conn.execute("ALTER TABLE team_relations ADD COLUMN finish_base REAL")
        conn.execute("ALTER TABLE team_relations ADD COLUMN finish_target REAL")
        conn.execute("ALTER TABLE team_relations ADD COLUMN outcome TEXT")
        conn.execute("ALTER TABLE team_relations ADD COLUMN reward REAL NOT NULL DEFAULT 0")
    if "growth" not in _columns(conn, "offer_messages"):
        conn.execute("ALTER TABLE offer_messages ADD COLUMN growth INTEGER")
    if "race_at" not in _columns(conn, "events"):
        conn.execute("ALTER TABLE events ADD COLUMN race_at TEXT")
    if "scorekeeper" not in _columns(conn, "career_members"):
        conn.execute("ALTER TABLE career_members ADD COLUMN scorekeeper INTEGER NOT NULL DEFAULT 0")
    if "role" not in _columns(conn, "join_requests"):
        conn.execute("ALTER TABLE join_requests ADD COLUMN role TEXT NOT NULL DEFAULT 'driver'")
    for table in ("news", "notifications"):
        if "ref" not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN ref TEXT")
    offer_columns = _columns(conn, "offers")
    for name, ddl in OFFER_V5_COLUMNS:
        if name not in offer_columns:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {ddl}")
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
