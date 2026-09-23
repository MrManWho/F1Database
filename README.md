# F1 Universe Tracker v1.5

A companion database and "career control room" for a two-player F1 26 career (David Conley and
Carson Hayes). The game handles the racing. This app remembers everything else: every result,
Sprint, championship, transfer, Reputation change, contract offer and AI difficulty setting,
across as many seasons as you play.

It runs on your own computer with Flask, Waitress and SQLite. No accounts or data leave the machine.

## Quick start (Windows)

1. Install Python 3.11+ from python.org and tick **Add python.exe to PATH**.
2. Double-click **`run.bat`**. On first launch it creates a private `.venv` and installs Flask and Waitress.
3. The browser opens at `http://127.0.0.1:8765`. On first visit, create the **Race Master** login.
4. In **Accounts**, create a **Driver** login for your teammate.
5. **New career**: pick each player's login and leave **Start as rookies** ticked.

Keep the command window open while you play. Closing it stops the server. Your saves are not affected.

### Playing on two devices

`run.bat` only accepts connections from the same PC. To let the other player log in from their own
laptop or phone on the same home network, start **`run_lan.bat`** instead. The window prints an
address like `http://192.168.1.20:8765` for the other device. Windows may ask you to allow Python
through the firewall. Only do this on a network you trust, and use real passwords.

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
