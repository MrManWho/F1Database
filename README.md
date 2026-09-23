# F1 Universe Tracker v1.11

A companion website for F1 game career **leagues**. Any number of people can drive: each player
has their own login, garage and contract negotiations, and a Race Master or Race Steward enters the
results after every race. The game handles the racing. The tracker remembers everything else:
every result, Sprint, championship, transfer, Reputation change, contract offer and AI difficulty
setting, across as many seasons as you play.

It runs on your own computer with Flask, Waitress and SQLite. No accounts or data leave the machine.

## Quick start (Windows)

1. Install Python 3.11+ from python.org and tick **Add python.exe to PATH**.
2. Double-click **`run.bat`**. On first launch it creates a private `.venv` and installs Flask and Waitress.
3. The browser opens at `http://127.0.0.1:8765`. On first visit, create the **Race Master** login.
4. Create logins in **Accounts**, or let people sign up themselves.
5. **New league**: add player drivers (or none), leave **Start as rookies** and **open to join** ticked.

Keep the command window open while you play. Closing it stops the server. Your saves are not affected.

### Playing on two devices

`run.bat` only accepts connections from the same PC. To let the other player log in from their own
laptop or phone on the same home network, start **`run_lan.bat`** instead. The window prints an
address like `http://192.168.1.20:8765` for the other device. Windows may ask you to allow Python
through the firewall. Only do this on a network you trust, and use real passwords.

## v1.11: email confirmation at sign-up

Signing up now takes two steps. Fill in the form, then enter the **6-digit code** emailed to you.
The account is only created once the code is right.

* Codes work for 15 minutes. **Send a new code** is available once a minute. After 5 wrong tries
  you need a new code.
* Only a hash of the code is stored, and the password is hashed before the account exists.
* Self sign-up needs email set up (**Accounts → Settings → Email**). Until then the sign-up page
  says so, and the Race Master can still create logins by hand in Accounts. Those don't need a code.

## v1.10: Scorekeeper role, cleaner navigation, deleting drivers

* **Scorekeeper** (was Race Steward) can do exactly one thing: enter qualifying, Sprint and race results,
  plus the AI difficulty. The button says **Submit results**. After a weekend is submitted it's locked
  for them, and only the Race Master can change it. Scorekeepers can't touch the grid, calendar,
  seasons, Paddock Admin, the transfer market or saves.
* **Navigation** is grouped (Race weekend · My career · Championship · Season · Race Master) with icons,
  and it can collapse to an icon rail (the **Collapse** button; the choice is remembered).
* **Control Room** has a season progress strip (one dot per round, with the next race and Sprint
  weekends marked), a **Your driver** card (position, points, Form and Reputation bars, last five
  results) and position-change arrows in the standings.
* **New drivers** always start at 45 Reputation, like every rookie.
* **Delete drivers** permanently from Paddock Admin. Drivers with race results need an extra tick,
  and their results go too. To keep someone for a future season, untick **Active** instead.

## Where your data lives (and why updates don't lose it)

Everything a league contains (drivers, results, seasons, offers, news) is one SQLite file per league,
plus `accounts.db` for logins and settings. These live in the **data folder**, not with the code:

* **On Render:** the persistent disk mounted at `/data` (set in `render.yaml`). A deploy replaces
  only the program files. The disk stays attached to the service, so every league, login and backup
  survives. Automatic backups are on the same disk under `/data/backups`.
* **At home:** `%LOCALAPPDATA%\F1UniverseTracker` on Windows.

When an update changes the save format, each league is copied to `backups/` before it's upgraded.
Download a backup to your own computer now and then too (Race Master → League & Saves).

## v1.9: open leagues for any number of players

* **No built-in players.** A new league starts with the real F1 grid and as many player drivers as
  you list (none is fine). Every player driver starts as a rookie on 45 Reputation without a seat.
* **Anyone can join.** People sign up from the login page. Leagues marked *open* appear in their
  **League Library** with an **Ask to join** form (they choose their driver name). The Race Master
  approves or declines in **Players & Logins**, optionally sending rookie offers straight away.
  New players' offers go into the transfer window that's already open, or a window opened just for
  them, so nobody else gets a surprise round of offers.
* **Players & Logins** (Race Master): join requests, **Add a player driver**, link logins, **Send
  offers** to any player, and the open/closed switch.
* **Rivalry** compares any two drivers (players or AI). It defaults to you vs the nearest player in
  the table. **My Garage** shows your points against every other player.
* Charts give each player driver their own colour (up to 8 lines).

## v1.8: email, password resets, tighter Steward

* **Email addresses.** Sign-up asks for an email address. Anyone can add or change theirs in
  **Accounts → My email**, and the Race Master can set anyone's in the logins table.
* **Forgot password?** is on the login page. It emails a one-time link that works for 60 minutes.
  Requests are rate-limited, and the page never reveals whether an account exists. Accounts
  without an email can still be reset by the Race Master.
* **Race results by email.** When a weekend is marked complete, every career member with an email
  gets the top 10, both players' weekends and the championship. Turn it off per person in
  **My email**.
* **Setting up email:** **Accounts → Settings → Email**, or environment variables on Render
  (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`). Gmail works with an
  App password (`smtp.gmail.com`, port 587). **Send me a test email** checks the setup.
* **Race Stewards can no longer** open or close transfer windows or add or delete Driver Market
  storylines. Silly Season still opens by itself at half-distance.
* **Race Master clean-up.** Delete a whole transfer window from **Transfer Market**: its offers,
  talks, headlines and notifications go with it. Seats already changed by a signing stay as they
  are. Individual headlines and notifications have a ✕ for the Race Master.

## Hosting it as a website (Render)

The tracker can live on a website, so your PC doesn't need to stay on. Every time new code is pushed
to GitHub, the site updates itself in a couple of minutes.

1. Create an account at render.com and connect your GitHub.
2. Choose **New → Blueprint** and pick the `F1Database` repo. Render reads `render.yaml` and sets up:
   a web service, a 1 GB persistent disk at `/data` for the careers, and auto-deploy from the branch.
   Persistent disks need a paid instance (the Starter plan).
3. When it's live, open **Environment** on the service and copy **F1_TRACKER_SETUP_CODE**.
4. Visit your site (e.g. `https://f1-universe-tracker.onrender.com`). Create your Race Master with that
   code. Without the code, nobody else can grab the admin account.
5. Move your career: on your PC, **Career & Saves → Download backup**; on the website, **Import .f1career**.
   Re-create the same usernames in **Accounts**. Player links are stored inside the career, so they
   reconnect automatically.
6. Optional: add `ANTHROPIC_API_KEY` under **Environment** for screenshot import (or paste it in Settings).

Notes:
* Updates restart the site for a few seconds; saves on the disk are untouched.
* Automatic backups are kept on the same disk. Now and then, download one to your PC as well.
* Other hosts work too: `Dockerfile` (Railway, Fly.io, any VPS) or `Procfile`. Set `F1_TRACKER_DATA_DIR`
  to a persistent volume and optionally `F1_TRACKER_SETUP_CODE`. `server.py` is the production entry
  point; `run.bat` / `launcher.py` stay the way to run it at home.

## v1.7: racecraft (qualifying vs finish)

Form and Reputation now reward places gained from the grid, weighted by where you end up:

```
racecraft per finished race = places gained × (23 − finish) / 22      (places lost: −0.4 each)
Form       += average racecraft × 0.6   (capped between −6 and +12)
Reputation += total racecraft × 0.08
```

P20 → P1 is worth 19.0 racecraft (about +11 Form for that weekend and +1.5 Reputation on top of the
win), while P20 → P19 is worth 0.2. The Drivers table has a **Gained** column.

**Do formula changes apply to the past?** Form is always recalculated from results, so yes, straight
away, for every season. Reputation from finished seasons is locked when the next season starts, so
it only changes when a Race Master or Steward presses **Paddock Admin → Recalculate Reputation
history**. That replays every season with the current formula and makes a backup first.

## v1.6: the Race Steward role

There are three roles, set per login in **Accounts**:

| Role | Can do | Can't see |
|---|---|---|
| **Race Master** | Everything: logins, player links, saves, backups and export, every garage, every offer and negotiation thread | nothing is hidden |
| **Scorekeeper** | Enter results (including screenshot import and AI difficulty) until the weekend is submitted | Other players' garages, offers and notifications; every admin page |
| **Driver** | Their own garage and offers; everything else read-only | same as Steward |

To keep the career honest, give the person entering results (e.g. David) the **Race Steward** role
linked to their driver, and keep a separate **Race Master** login (e.g. `admin`) for setup and
emergencies. At least one Race Master always exists. Paddock rumours about collapsed talks are
public on purpose. Everything else about a player's negotiations stays private to that player.

## v1.5: what's new

* **Login protection.** After 5 wrong passwords an account locks for 10 minutes; any single address
  that keeps guessing gets locked too.
* **Self sign-up.** Players can make their own login from the login page (**Create a login**). New
  logins see nothing until the Race Master links them to a driver in **Player Logins**. Accounts shows
  "Waiting to be assigned" for them. Sign-ups can be turned off in **Accounts → Settings**.
* **Screenshot import.** On a race weekend, **📷 Import from screenshot** reads the game's qualifying,
  Sprint or race classification (up to 4 screenshots) with Claude, fills the positions and statuses,
  and highlights them for you to check. Needs an Anthropic API key in **Accounts → Settings**; each
  import costs a few cents. Refused or unreadable screenshots show a message and nothing changes.
* **Quick order.** On race entry, tap **Qualifying / Sprint / Race**, then tap drivers in finishing
  order. Undo and Clear are there. On phones the table turns into one card per driver.
* **Rivalry page.** David vs Carson all time: races, qualifying, points, wins, podiums and poles
  head-to-head; streaks; biggest beatings; season-by-season and track-by-track records; every battle.
* **Charts.** Title-fight points progression (dashboard and Drivers), Form and Reputation after
  every round (driver profiles and My Garage), and the rivalry swing. Hover or tap a chart for values,
  or open **Show data** for a table.
* **Automatic backups.** One a day and one after every completed race weekend. The newest 20 are
  kept in `backups/auto/<career>`. Download them from **Career & Saves**.
* **Team development.** Every team has a car rating. Each winter cars converge toward the pack,
  better constructors' finishers gain money, and there's some luck. Ratings drive the market's
  "fast car" order until three rounds are done. Edit them in **Paddock Admin** to match the game.
* **Season review.** Awards for every season: champion, runner-up, most wins, pole king, podium
  regular, fan favourite, overtaker of the year, Mr Consistent, most improved, rookie of the year,
  plus a player spotlight.
* **Paddock news.** Headlines for wins (and where they started), maiden points, podiums and
  wins, poles, big charges, DNFs, signings, collapsed talks, transfer windows, champions and winter
  testing.
* **Notifications.** The 🔔 shows new offers, signings, results and new seasons. It checks every
  minute, updates the tab title, and can play an optional chime.
* **Paddock Admin.** Add or retire drivers, edit names and baseline Reputation, add a team (a 12th
  team adds two seats and positions up to 24), rename or recolour or retire teams, and set car
  ratings.
* **Calendar.** Add rounds to the end and remove rounds that haven't been run. The next season
  copies the edited calendar.

## v1.3: logins, rookie offers and My Garage

### Roles

| Role | Can do |
|------|--------|
| **Race Master** | Enter qualifying, Sprint and race results. Edit the grid and calendar, create seasons, open and close transfer windows, manage saves and logins. Can view every garage. |
| **Driver** | View every page in careers they're linked to (race pages are read-only). See **their own** garage and offers, and accept or decline their own offers. |

A person can be both: give David's login the Race Master role and link it to David Conley.
Link logins to player drivers in each career's **Player Logins** page, or when creating the career.

### Starting as rookies: finding your first team

Both players start without a seat. When the career is created with **Start as rookies**, the
**Rookie Draft** window opens. Three teams from the bottom five of the car-strength order each send
each player an offer (usually No. 2, for 1–2 years). Each player logs in, opens **My Garage** and
accepts one. They're placed in that team straight away, replacing the lower-rated AI driver. Their
other offers are withdrawn. If both players pick the same team, they become teammates.

### Offers based on performance

After that, teams judge each player on a **Driver Value**:

```
Driver Value = 0.5 × Market Score  (0.8 × Reputation + 0.2 × Form)
             + 0.3 × Form
             + 0.2 × Car-Adjusted Rating   (50 + 5 × avg places finished ahead of the car's expected finish)
             + teammate head-to-head bonus (±4)
```

Each team has an entry bar that depends on its car-strength rank: 86 for the fastest car, 4.2 lower
for each rank down, so 44 for the slowest. When a window opens, a team offers a contract if your
value clears its bar, plus or minus a small random factor. You hear from up to four of the best
teams that want you. Your current team adds +3 loyalty, and its renewal offer is always kept. Role
(No. 1, Equal Status or No. 2) depends on how you compare with the team's current drivers. Term
length (1–3 years) depends on how keen they are. If nobody clears the bar, you still get a
last-chance renewal from your current team.

**Car strength is ranked from AI drivers' points only.** Winning races in a Cadillac makes you look
brilliant, not the Cadillac. It uses the current season once three rounds are complete, otherwise
the previous season, otherwise the default team order.

### Transfer windows

* **Rookie Draft**: opens when a career is created with rookies ticked. Offers are for this season.
* **Silly Season**: opens automatically when half the calendar is complete. Offers are for next season.
* The Race Master can open a window at any time from **Transfer Market**. Before round 1, offers
  are for the current season. After that, they're for next season.
* Deals signed for next season are applied to the grid when the Race Master creates that season.
  Closing a window expires any unanswered offers.

### Contract negotiations (v1.4)

An offer is the start of a negotiation, not a take-it-or-leave-it choice. Every offer has a
**seat status** (No. 2, Equal Status or No. 1), a **length** (1–5 years) and a **salary** ($M a
year). On each offer you can:

* **Sign contract**: accept the terms currently on the table.
* **Counter-offer**: ask for different status, years or salary, and add a message. The team
  replies straight away in the conversation thread: it agrees, meets you partway, or refuses.
* **Walk away**: end the talks. You can't reopen talks with that team in this window.

Each team has private limits that you never see directly:

| Limit | How it's set |
|---|---|
| Top seat status | Compared with the team's best other driver. **Rookies are No. 2**, unless a backmarker rates them at least as highly (then Equal Status). Young drivers (under 30 starts) only get No. 1 if they're clearly better. |
| Contract length | Rookies 1–2 years (3 if a team is very keen). Everyone else 1–3 years. |
| Salary ceiling | Your going rate × team budget (the fastest car pays 1.8×, the slowest 0.7×), nudged up by interest. Rookies are capped around $1–4M. |
| Patience | 1–4 rounds of haggling, depending on how keen the team is. Rookies get one fewer round, but always at least two. |

If you ask for something within their limits, they **agree**, and you still have to sign. A modest
ask above their limits gets a **counter-offer** that meets you partway and uses up one round of
patience. A **greedy** ask uses up two: more than 40% over their salary ceiling, two status levels
too high, or years well outside their range. When patience reaches zero, the team makes a
**final offer**. If you push past that point, they **walk away**. The badge on each offer card
shows the team's mood: Open to talks, Losing patience, Final offer or Terms agreed.

**Approaching teams.** You can contact up to **3 teams per window** yourself. You can either ask
about a seat or propose your own terms.
* Teams that rate you will open talks.
* Top-3 teams won't sign rookies.
* Teams that aren't interested turn you down.
* A team that's on the fence offers a one-year trial on a take-it-or-leave-it basis.

**Running out of offers.** If you have nothing pending, nothing signed and no approaches left, the
weakest team with a free seat makes one **last-chance offer** (No. 2, one year). If you turn that
down too, you keep your current seat if you have one. Otherwise you sit out as a reserve, and your
Reputation carries over unchanged. The Race Master can still place you by hand.

**My Garage** also shows a live **Who's watching you** board: each team's current interest
(Keen, Interested, Watching or Cold), so you can see which teams you're getting closer to before
a window opens. It also shows teammate and David-vs-Carson head-to-heads, recent weekends,
current contract and offer history.

## AI difficulty: slow, career-long recommendations

Enter the AI difficulty you used (0–110) on each weekend's race page, or leave it blank to skip
that round. The recommender is built to move slowly:

* **One bad or great round is only noted.** The weekend page says "Noted: … One bad round won't
  move the setting."
* It compares **3 to 5 completed rounds at the same setting**. Untracked rounds are skipped.
  Changing the setting starts a fresh sample.
* **The sample and history carry across seasons.** A new season doesn't reset what it has learned.
* GP DNF, DNS and DSQ results are ignored, so crashes never push the difficulty down. If one
  player finishes, only that player counts.
* Each finished player gets a score:
  `0.35 finish + 0.15 qualifying + 0.15 weekend points + 0.15 vs AI teammate + 0.20 vs the car's expected finish`.
  The "vs car" part means a rookie in a backmarker isn't punished for the car being slow.
* It recommends a change only when:
  1. the average is at least **±0.35**,
  2. at least **two thirds** of the rounds point the same way, and
  3. the **career sweet spot** doesn't disagree.
* The **sweet spot** is a recency-weighted estimate (half-life 12 rounds) across your whole career
  of the difficulty where you'd score an even 0. Its confidence is shown as Low (<8 rounds),
  Medium or High (15+ rounds).
* A recommendation never moves more than **±1**, and the app never changes the game for you.

## Everything else (from v1.2)

* A separate `.f1career` SQLite save per career, stored outside the program folder
  (`%LOCALAPPDATA%\F1UniverseTracker`, `~/.f1-universe-tracker`, or `F1_TRACKER_DATA_DIR`).
* Save now, Rename, Save As (an independent copy), backup download, JSON export, import, delete.
* Autosaving race entry: 850 ms debounce, duplicate-position highlighting, Up/Down/Enter keyboard
  movement, a single Fastest Lap and DOTD, separate Sprint and GP statuses, per-driver and
  weekend notes.
* Scoring:
  * GP points 25-18-15-12-10-8-6-4-2-1, Sprint points 8-7-6-5-4-3-2-1. No Fastest Lap point.
  * Only a Finished result scores.
  * Sprint DNFs don't count toward career DNF totals.
* Form, Reputation (locked at season end and carried forward, including for drivers without a
  seat), Market Tier.
* Driver and constructor standings. Constructor points follow the team each driver represented at
  each event.
* Driver and team profiles, Hall of Records, Grid & Transfers (atomic swaps), Driver Market
  storylines, and the seasons and calendar editor. Round swaps are now atomic too.
* Saves from v1.0–v1.3 upgrade to schema v5 automatically when opened.

## Updating

Your careers, logins and the secret key live in the data folder, not the program folder:

1. Close the tracker window.
2. Double-click **`update.bat`**. It downloads the latest version from GitHub and installs it over
   the program folder. You can also do it by hand: download the ZIP and drag its files over the
   old folder, choosing **Replace** and keeping `.venv`.
3. Start `run_lan.bat` / `run.bat` again. Logged-in players stay logged in.

`run.bat` reinstalls packages automatically if `requirements.txt` changed. When an update bumps
the save format, each career is copied to `backups/<id>-before-vN-upgrade-<time>.f1career` before
its first upgrade. See `UPDATING.txt`.

## Security

This is meant for a home network. v1.3 adds hashed passwords, per-career access checks, CSRF
tokens on every form and API call, and a random secret key stored in the data folder. There is no
HTTPS or rate limiting, so don't expose it to the internet.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q
.venv/bin/python launcher.py          # or: launcher.py --lan
```

`build_exe.bat` builds a single-file `F1 Universe Tracker.exe` with PyInstaller.

Layout: `f1tracker/` holds `constants`, `schema` (migrations), `storage` (saves), `services`
(rules, standings, difficulty), `market` (offers), `auth` (logins) and `app` (routes).
Pages are in `templates/`, and `static/` holds the vanilla CSS and JS.
