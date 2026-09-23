# F1 Universe Tracker v1.16

A companion website for F1 game career **leagues**. Any number of people can drive. Each player has
their own login, garage, contract talks and relationship with their team. The Race Master or a
Scorekeeper enters the results after every race.

The game handles the racing, and the tracker remembers everything else:
- every result, Sprint and championship;
- transfers and contracts;
- Reputation and Form changes;
- AI difficulty settings.

It keeps all of this across as many seasons as you play.

It's a small Flask + SQLite app. Run it on your own PC, or host it as a website that updates itself
(see **Hosting** below).

**What's new:** see [CHANGELOG.md](CHANGELOG.md), or **account menu → What's new** in the app.

## Quick start (Windows)

1. Install Python 3.11+ from python.org and tick **Add python.exe to PATH**.
2. Double-click **`run.bat`**. On first launch it creates a private `.venv` and installs everything.
3. The browser opens at `http://127.0.0.1:8765`. On your first visit, create the **Race Master** login.
4. Create logins in **Accounts**, or let people sign up themselves (this needs email set up).
5. Click **New league**. Add player drivers (or none), then choose what's on: rookies, open to join and the extras.

To let people on the same home network join, start **`run_lan.bat`** instead. It prints an address
like `http://192.168.1.20:8765`. Only do this on a network you trust.

## Hosting it as a website (Render)

1. Create an account at render.com and connect your GitHub.
2. Choose **New → Blueprint** and pick the `F1Database` repo. `render.yaml` sets up three things:
   - the web service;
   - a persistent disk at `/data`;
   - auto-deploy from the branch, so every update goes live in a couple of minutes.

   Persistent disks need a paid instance (the Starter plan).
3. Open **Environment** on the service and copy **F1_TRACKER_SETUP_CODE**. You need it to create the
   first Race Master, so nobody else can grab the admin account.
4. Optional environment variables:
   - `ANTHROPIC_API_KEY` for screenshot import;
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_FROM` for email.

   You can also enter both in **Accounts → Settings**. For Gmail, use an App password with
   `smtp.gmail.com`, port 587.

Other hosts work too. Use the `Dockerfile` or `Procfile`, and set `F1_TRACKER_DATA_DIR` to a
persistent volume.

## Where your data lives (and why updates don't lose it)

Each league is one SQLite file. Logins and settings live in `accounts.db`, and uploaded driver photos
in `avatars/`. All of these are in the **data folder**, not with the code:

* **On Render:** the persistent disk at `/data`. A deploy replaces only the program files.
* **At home:** `%LOCALAPPDATA%\F1UniverseTracker` on Windows (`~/.f1-universe-tracker` elsewhere).

Automatic backups are made once a day and after every completed race weekend, and the newest 20 are
kept. A league is also copied to `backups/` before an update changes its save format. Now and then,
download a backup to your own computer as well: **Race Master → League & Saves**.

## Updating (at home)

Close the tracker, double-click **`update.bat`**, then start it again. `run.bat` reinstalls packages
when `requirements.txt` changes. On Render there's nothing to do: updates deploy themselves.

## How it works

### Who can do what

Everyone in a league has **one access role**, set on the league's **Players & Logins** page. Having a
driver is separate from the role, so any role except Spectator can also drive.

| Role | Can do |
|---|---|
| **Race Master** | Runs the league: results (including reopening submitted rounds), grid, calendar, seasons, transfer market, members and roles, settings, saves, every garage, the Activity Log. Site Race Masters (set in **Accounts**) are Race Master of every league. |
| **Scorekeeper** | Enters and edits results, statuses, Fastest Lap, Driver of the Day, notes and AI difficulty, and submits a round. After submitting, only the Race Master can change it. Can't change settings, roles, seasons or delete anything. |
| **Member** | Views everything. With a driver: their own garage, contract talks, Team Standing and press pen. |
| **Spectator** | View only. Pages show plain text instead of greyed-out forms, and the server refuses any change. Can't have a driver. |

Possible combinations include Race Master + driver, Scorekeeper + driver, Scorekeeper without a driver
and Spectator without a driver. A league always keeps at least one Race Master, and the last one can't
be demoted or removed.

People ask to join an open league from their League Library and choose a role. The Race Master
accepts as asked, accepts with a different role, or declines.

**Upgrading from 1.15 or earlier:** the old account-wide "Scorekeeper" switch is gone. Anyone who had it
becomes Scorekeeper in every league they belong to (keeping their driver), members without a driver
become Spectators, and everyone else keeps what they had. This happens automatically on first start.

### Race weekends

Enter qualifying, Sprint and race positions, statuses, Fastest Lap and Driver of the Day. Everything
autosaves, and there are three ways to enter results:
- type positions in the table;
- tap drivers in finishing order;
- import screenshots of the game's classification.

A Scorekeeper presses **Submit results** when done.

Points: GP 25-18-15-12-10-8-6-4-2-1, Sprint 8-7-6-5-4-3-2-1. There's no Fastest Lap point, and only a
Finished result scores.

### Form and Reputation

* **Form** is this season's level, rebuilt from results. It covers:
  - average finish and qualifying;
  - wins, podiums, poles, fastest laps and Driver of the Day;
  - DNFs;
  - **racecraft**: places gained from the grid, weighted by where you finish, so P20 → P1 is worth
    far more than P20 → P19.
* **Reputation** is long-term. It builds from points, results, Form and racecraft, is locked at the
  end of each season and carries forward. **Paddock Admin → Recalculate Reputation history** replays
  old seasons if the formula changes.

### Contracts and the transfer market

Teams judge players on a **Driver Value**:

```
Driver Value = 0.5 × Market Score (0.8 × Reputation + 0.2 × Form)
             + 0.3 × Form
             + 0.2 × Car-adjusted rating (finishing ahead of where the car should)
             + teammate head-to-head bonus (±4)
```

Car strength is ranked from AI drivers' points only, so winning in a slow car makes *you* look good.

**Transfer windows:**
* The **Rookie Draft** opens when a league starts with rookies.
* **Silly Season** opens by itself at half-distance.
* The Race Master can open a window any time.

Offers are negotiations. Every deal has three terms:

* **Seat status:** No. 2, Equal Status or No. 1.
* **Length:** 1–5 years.
* **Growth pledge:** how much you promise to improve each season. There's no money involved.

| Pledge | Form target | Reputation target |
|---|---|---|
| Steady | what the car should manage | +0.5 a season |
| Solid | car + 6 | +2 |
| Strong | car + 12 | +4 |
| Breakout | car + 20 | +7 |

Targets are measured against what your car should manage, so a pledge is equally fair at the front
and the back of the grid.

**What each team wants:**
* Each team privately wants a minimum pledge. Keen teams accept Steady, and lukewarm ones want Strong.
* No. 1 status and deals of 3+ years each need one level more.
* Rookies are No. 2 and must pledge at least Solid.
* Promise more than a team needs and you can win an extra year. An experienced driver who pledges
  two levels more can also get one step more status than the team first offered.

**Negotiating:**
* Counter-offers use up the team's patience, and greedy asks use it up twice as fast. When patience
  runs out, the team makes a final offer, and pushing past that ends the talks.
* You can also **approach** up to 3 teams per window.
* If you run out of options, the weakest team with a free seat throws you a last-chance lifeline.

**Contract length matters.** While your deal covers next season, you're off the market: no offers,
and no approaches. The exception is if your team releases you.

### Team Standing: your relationship with your team

Once results come in, your team rates you out of 100:
- the score compares your Form with your target, and your Reputation with where it should be by now;
- your head-to-head against your teammate also counts;
- the team's judgement firms up after about a third of the season.

| Status | What happens |
|---|---|
| Delighted / Happy | You're on or ahead of your pledge. A happy team always offers a renewal. |
| Concerned | A quiet word from the team |
| Unhappy | A formal warning |
| Seat at risk | They openly question your future |

If you're still **at risk** when Silly Season opens, or when the season ends, you're **released**.
The team won't renew you, and without a new deal you start next season as a reserve. Turn it around
and the warning is lifted.

**Team Standing** (My career) shows:
- your relationship and status;
- your targets against your actual Form and Reputation;
- your teammate head-to-head;
- everything the team has said to you;
- how eager every other team is.

### Pledges, goals, the press and team orders

* **Everyone needs a pledge.** If a seated driver has none, they choose it before using the league.
  Pledges are locked for the season. The Race Master can ask a driver, or everyone, for a new one on
  **Team Standings**.
* **Targets re-set after round 3** to the car's real pace in your league (from AI drivers' points).
* **Season goals** from the team:
  - points in a number of races;
  - a championship position;
  - beating your teammate (No. 1 and Equal Status drivers only).

  Each goal that's on track helps the relationship, and each one behind hurts it.
* **Press pen:** after every race you get two questions based on your result. Answers nudge the
  relationship, and some make headlines. It's optional.
* **Team orders:** No. 2 drivers can be told to let their teammate through. Finishing ahead of them
  counts as ignoring the order: −6 relationship and a headline. Following it is +2.
* Press answers and team orders can move the relationship by up to ±15 in total per season.

### Incidents

Anyone driving can report an incident from a race weekend. The Race Master rules on it: no further
action, a reprimand, a warning, or a penalty (for a penalty, they adjust the results themselves).
Rulings go in the news and in the rivalry page between the two drivers.

### Extras (League Settings)

| Extra | Default | What it does |
|---|---|---|
| Race-night check-in | off | Members answer I'm in / Maybe / Can't make it for the next race |
| Comments & reactions | on | Chat and emoji reactions on race weekends and news, and a fans' Driver of the Day vote |
| Predictions game | on | Pick pole (3), winner (5), fastest lap (2) and the top player driver (2). Picks lock at race time. |
| Public results page | off | A read-only link with the standings, calendar and results |
| Discord | off | Paste a channel webhook to post race results and paddock headlines |

**Race night:**
* The Race Master sets a race time in the league's time zone (League Settings; detected from the Race
  Master's browser the first time). Every date and time in the league is shown in that zone, e.g.
  "Lights out Wed, Sep 23 at 11:30 AM" and "Starts in 9h 56m".
* After the race, the page tells the story: podium, biggest movers, pole, fastest lap and DNFs.

### Everything else

* **Driver profiles** with a photo, number, flag, helmet colour, bio, trophy cabinet and contract history.
* **Season review awards and the Hall of Records:** champions, a record book and streaks.
* **Rivalry:** compare any two drivers.
* **Paddock news**, notifications, and optional emails with the race results.
* **Car development each winter.** Edit car ratings in Paddock Admin to match the game.
* **AI difficulty recommender.** Enter the AI level you raced on. It only suggests a change after 3–5
  rounds point the same way, learns across seasons, and ignores DNFs.
* **Install it as an app** (account menu → Install, or Safari → Share → Add to Home Screen) and turn
  on phone alerts (account menu). Alerts need the https website address.
* **Themes:** light, dark or match your device.
* **How it works** (menu) explains every number in the app.
* **Result cards:** share a picture of the podium and your weekend from any completed race.
* **Post-race summary** for every completed round: podium, pole, each player's weekend, Form and
  Reputation changes, championship movement, the rivalry and the next AI difficulty.
* **Player colours:** every human-controlled driver keeps one accent colour (separate from the team
  colour) across tables, charts, the grid and profiles.
* **Change since last round** in My Garage and on driver profiles, with sparklines once there are three
  completed rounds.
* **Density:** Comfortable or Compact (account menu).
* **Restore:** roll a league back to any automatic backup from **League & Saves**. The current state
  is backed up first, so a restore can be undone.

## Security

* Passwords are hashed.
* Login lockout: 5 wrong passwords locks the account for 10 minutes, and addresses that keep
  guessing get locked too.
* Email confirmation at sign-up, and password-reset links that expire.
* CSRF protection on every form, per-league access checks, and a secret key kept in the data folder.
* On Render the site is served over HTTPS.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q          # includes a two-season simulation that crawls every page
.venv/bin/python launcher.py           # or: launcher.py --lan
```

**Code layout.** The program code is in `f1tracker/`:

| Module | What it holds |
|---|---|
| `constants` | Shared settings and constants |
| `schema` | The database schema and migrations |
| `storage` | Saves |
| `services` | Rules, standings and difficulty |
| `market` | Offers and negotiations |
| `relations` | Team relationships, pledges and season goals |
| `teamlife` | The press pen and team orders |
| `discord` | Optional Discord posts |
| `community` | Extras, profiles, incidents and the activity log |
| `feed` | News and notifications |
| `insights` | Charts, rivalry and awards |
| `auth` | Logins |
| `push` | Phone alerts |
| `app` | Routes |

Pages are in `templates/`. `static/` holds the CSS and JS.
