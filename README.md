# Paddock Legacy 3.2.3

A companion website for F1 game career **leagues**. Any number of people can drive. Each player has their own
login, garage, contract talks and relationship with their team, and the Race Master or a Scorekeeper enters the
results after every race.

The game handles the racing, and Paddock Legacy remembers everything else, across as many seasons as you play:
- every result, Sprint and championship, with the weather for each session;
- race weekends, from the paddock opening to the chequered flag;
- contracts, transfers, pledges and team goals;
- Form, Reputation and how your team rates you;
- a recommended AI difficulty for the next race.

It's a small Flask + SQLite app. Host it as a website that updates itself (see **Hosting** below), or run it on
your own PC.

- **What's new:** [CHANGELOG.md](CHANGELOG.md), or **account menu → What's new** in the app.
- **Every rule and number:** **Help** in the app. The formulas are in [docs/CALCULATION_V3.md](docs/CALCULATION_V3.md).
- **Running the site:** [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md), for the site owner and Race Masters.

## Hosting it as a website (Render)

1. Create an account at render.com and connect your GitHub.
2. Choose **New → Blueprint** and pick this repo. `render.yaml` sets up:
   - the web service, on the **Starter** plan (persistent disks need a paid instance);
   - a 1 GB persistent disk at `/data`, where every league and login is kept;
   - auto-deploy from the branch named in `render.yaml`, so every push to it goes live in a couple of minutes.
3. Open **Environment** on the service and copy **F1_TRACKER_SETUP_CODE**. On your first visit, enter it to create
   the **site owner** account. Nobody can claim the site without it.
4. Everyone else creates their own account from the sign-in page. Add them to a league from **Members & roles**,
   invite them, or let them ask to join.

Optional environment variables:

| Variable | What it does |
|---|---|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Email (sign-up codes, password resets, results). You can also enter these in **Account → Settings**. For Gmail, use an App password with `smtp.gmail.com`, port 587. |
| `FORCE_MAINTENANCE=true` | Emergency switch that closes the site to everyone but the owner. Remove it and redeploy to reopen. |

Other hosts work too. Use the `Dockerfile` or `Procfile`, and set `F1_TRACKER_DATA_DIR` to a persistent volume.
`/healthz` answers for uptime monitors.

## Running it on your own PC (Windows)

1. Install Python 3.11+ from python.org and tick **Add python.exe to PATH**.
2. Double-click **`run.bat`**. On first launch it creates a private `.venv` and installs everything.
3. The browser opens at `http://127.0.0.1:8765`. Create the site owner account (no setup code is needed on your
   own PC).
4. Click **New league** and follow the setup: Essentials → Players → (optional) More options → Ready.

To let people on the same home network join, start **`run_lan.bat`** instead. It prints the address others should
open. Only do this on a network you trust.

**Updating at home:** close the tracker, double-click **`update.bat`**, then start it again (see `UPDATING.txt`).
On Render there's nothing to do: updates deploy themselves.

## Where your data lives

Each league is one SQLite file (`careers/*.f1career`). Logins and site settings live in `accounts.db`. All of it is
in the **data folder**, never with the code, so an update can't lose it:

* **On Render:** the persistent disk at `/data`.
* **At home:** `%LOCALAPPDATA%\F1UniverseTracker` on Windows (`~/.f1-universe-tracker` elsewhere).

Backups:
* Automatic backups once a day and after every completed race weekend, plus safety backups before an upgrade,
  a season rollover, a restore, a recalculation or a delete.
* **Backups & data** (Race Master) can restore any of them. The current state is backed up first, so a restore can be
  undone. It also has an integrity check, a JSON export and a standings CSV.
* The site owner can download one **encrypted backup of the whole site** (Account → Settings) to keep somewhere
  else, and gets a reminder when one is due.

## How it works

### Roles

Everyone in a league has one role, set on **Members & roles**. Having a driver is separate from the role, so any
role except Spectator can also drive.

| Role | Can do |
|---|---|
| **Race Master** | Runs the league: results (including reopening submitted rounds), grid, calendar, seasons, transfer market, team management, members, settings, backups and the Activity log. The site owner is Race Master of every league. |
| **Scorekeeper** | Opens the paddock, starts the race, and enters results, weather and AI difficulty. After submitting, only the Race Master can change a round. |
| **Member** | Views everything. With a driver: their own garage, contracts & offers, team relationship and press. |
| **Spectator** | View only, and can't have a driver. |

Race Masters and Scorekeepers can preview the league as another role. Joining can be by request, invite only, or
closed. Leagues are private unless the Race Master makes them Public (a share link) or Listed (in the directory).

### Race weekends

1. **The paddock opens** an hour before the scheduled race time, or when a Scorekeeper or the Race Master opens it.
2. **Before the race** each driver answers pre-race press and picks a **weekend target**: Safe, Standard or Stretch.
3. **Lights out.** A Scorekeeper or the Race Master starts the race once everyone's ready. Only the Race Master can
   start with someone outstanding, and must leave a note.
4. **Chequered flag.** Results go in (typed, tapped in finishing order, or imported from screenshots with free
   in-browser OCR that you check row by row), then **Review and submit** locks the round. After the race there's
   post-race press and a race summary.

Every player driver needs a linked login, or the Race Master marks them **No account**. Edits autosave and survive a
dropped connection. The Race Master can **reset** the latest weekend as if it never happened.

**Points:** Grand Prix 25-18-15-12-10-8-6-4-2-1 (reduced for shortened races), Sprint 8-7-6-5-4-3-2-1. There are no
points for fastest lap. Ties are split by full countback. Each session's weather (dry, overcast, light rain, heavy
rain, changing) is recorded too, and never changes anyone's numbers.

### Your driver

* **Form** is how you're driving now (your last six races). **Reputation** is long-term: it builds over seasons
  and can fall after a bad one.
* **Contracts** have no money. A deal is a seat status (No. 2, Equal Status or No. 1), a length of 1–5 years, and a
  **growth pledge**: an average finish you promise, measured against where your car should finish, so it's equally
  hard in any car. Offers are negotiations, and what you write to a team counts.
* **Your team relationship** (out of 100) follows your pace against your pledge, your teammate head-to-head, season
  goals, press answers and weekend targets. Struggle for long enough and you get a **final warning**. Miss it and the
  Race Master decides whether you're dropped.
* **Team goals** (optional): each team picks Safe, Competitive or Ambitious at the start of a season.
* **Change notices:** whenever an update or a Race Master action changes your driver's numbers, you see the before
  and after and agree to it before carrying on.

### AI difficulty

Enter the AI level you raced on and the tracker recommends the next one, on the game's 0–110 scale. It compares each
player with their AI teammate and cars of similar speed (and lap times, if you enter them), learns from every round,
and ignores DNFs, damage and other unrepresentative sessions. It never raises the level while someone is struggling.

### Everything else

* A **Control Room** with your next action and everything waiting for you.
* Driver profiles, rivalries, statistics (including wet vs dry), season awards and the Hall of Records.
* Paddock news, announcements, comments, predictions, race-night check-in and optional Discord posts.
* Per-league notifications by email and phone alert. It installs as an app on phones and computers.
* Light and dark themes, and pages checked for keyboard and screen-reader use.
* **Maintenance mode** (site owner): closes the site with a "we'll be right back" page and holds emails and alerts
  until it reopens.

## Security

* Hashed passwords, with 8+ characters and no common ones.
* Optional two-step sign-in with any authenticator app, and a list of signed-in devices.
* Login lockout per account after too many wrong passwords. A shared connection is only blocked when it guesses at
  several accounts.
* Email confirmation at sign-up, and password-reset links that expire.
* CSRF protection on every form, a server-side role check on every page, and rate limits on sign-ups, invitations
  and codes.
* Emails, alerts and Discord posts go through an outbox, so a restart never loses one. Secrets, images and OCR text
  are never logged.
* No paid services: screenshot import runs in your browser, and nothing is sent to an AI service.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q          # includes full-season simulations that crawl every page
.venv/bin/python launcher.py           # or: launcher.py --lan
```

Program code is in `f1tracker/`, pages in `templates/`, and CSS and JS in `static/`. The main modules:

| Module | What it holds |
|---|---|
| `app` | Routes |
| `schema`, `storage` | Database schema, upgrades and league files |
| `services`, `calc3`, `engine`, `migration`, `recalc` | Standings, Form, Reputation, the calculation engines and recalculating |
| `weekend`, `gates`, `press`, `weather` | Race weekends, round gates, the press room and weather |
| `market`, `pitch`, `seats` | Offers, negotiations, team talks and seats |
| `relations`, `teamgoals`, `teamlife`, `ultimatums` | Team relationships, goals, weekend targets, team orders and final warnings |
| `ai3` | The AI difficulty tracker |
| `impacts` | Change notices |
| `auth`, `security`, `ratelimit` | Accounts, two-step sign-in and rate limits |
| `feed`, `notices`, `delivery`, `outbox`, `mailer`, `push`, `discord` | News, notifications and sending |
| `maintenance`, `offsite` | Maintenance mode and the encrypted site backup |
