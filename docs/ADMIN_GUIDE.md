# Paddock Legacy 4.0: admin guide

This is for site admins and Race Masters. The What's New screen and Help cover everyday use.

## 4.0.1: Remember me, and the final 4.0.0 audit (October 8, 2026)

The first version after the 4.0.0 changelog pause. Anything after it gets its own version and What's New entry.

- **Remember me** on the sign-in page (ticked by default) makes the sign-in cookie last 60 days
  (`PERMANENT_SESSION_LIFETIME`, the same as `security.SESSION_IDLE_DAYS`); unticked, it ends when the browser
  closes, as before. Signing out, or ending the session from Account → Sessions, still ends it straight away. Two-step
  sign-in carries the choice through the code step.

- **Faster pages.** A league's *last opened* time is now saved at most every ten minutes instead of on every page
  view, the "you still have to…" banner only checks the person viewing, and clicks that can't change any number
  (marking news read, reactions, pins, the view mode) no longer make the next page recalculate. Notification checks
  pause while a tab is hidden. Fonts are cached for a week.
- **Layout fixes.** Table headers no longer cover the first rows on phones; the Manage league and league menus stay
  on screen; the phone menu opens above the top and bottom bars; settings pages don't scroll sideways; light-theme
  team codes, player names and avatar initials are readable; What's New opens at the top.
- **One vocabulary.** Sign in / Sign out, Your leagues, Manage league, site owner, My garage, Activity log,
  Transfers, News and Delivery log are used the same way everywhere.
- Nothing about calculations, saved data or league files changed.

## Calendar permissions (after 4.0.0)

Everyone in a league (Race Master, Scorekeepers, members and spectators) can see the calendar under Seasons &
Calendar, and anyone can download the .ics file. Only the Race Master changes it by default. Under League settings →
Joining & roles → **Role permissions** the Race Master can let Scorekeepers:

- **Set race times and mark rounds postponed** (the Race time step on a round, and the "Set a time" links on the
  calendar). Saving a time still tells the league, as before.
- **Edit the calendar**: rename rounds, change round order and Sprint weekends, add rounds, and remove rounds that
  haven't run.

Both are off by default. Historical correction mode, switching the current season and starting a new season stay
with the Race Master. Members and spectators are always view only. The server checks each of these (`roles.GRANTS`
keys `race_times` and `calendar_edit`), and changes show in the Activity Log.

## Telemetry import (after 4.0.0)

Off by default, per league. Results can come straight from F1 25's UDP telemetry instead of being typed in.

- **Turning it on:** League settings → Career & team → Extras → **Telemetry import**. Then open **Upload link →**
  (also under More, and in a round's Import results) and **Make an upload link**. The link holds a private key for
  that league only; **Make a new link** replaces it (the old one stops working at once) and **Turn the link off**
  removes it. The key is left out of exports and downloaded backups, like the Discord webhook.
- **Who may use it:** League settings → Joining & roles → **Role permissions**. Scorekeepers may import telemetry
  by default; the Race Master can stop that, and can let Scorekeepers see and manage the upload link (off by
  default). Race Masters can always do both. The server checks these on every request, and changes show in the
  Activity Log. More permissions can be added to the same list (`roles.GRANTS`).
- **Recording:** someone in the league runs a recorder on the PC the game sends telemetry to (the Paddock Legacy
  telemetry recorder, or any tool that posts the same JSON; the format is described at the top of
  `f1tracker/telemetry.py`). When the game shows a session's final classification, the recorder posts that session
  to the link. Uploads don't need a sign-in; they're accepted only while the feature is on and the key matches,
  are limited to 256 KB and 120 per hour per address, and the last 40 per league are kept.
- **Filling a whole weekend:** when the game's sessions for a round have arrived (matched by the round's circuit, and
  only sessions sent within 72 hours of the newest one), the round shows **Fill weekend from the game** (also at the
  top of Import results). One click fills qualifying (Q1, Q2 and Q3 combined into the final order), the Sprint and the
  race into the results table, the Grand Prix fastest lap, the AI level, each session's weather (dry, overcast, light
  or heavy rain, or "changing" when it was both) and each player's race times, laps and qualifying laps against
  their AI teammate (the other car of their team in the game; penalties added to race times). Weather and times
  already entered are kept. Drivers that don't match confidently are left out and listed. Nothing is submitted; the
  results are the usual draft. Routes: GET `/career/<token>/weekend/<id>/telemetry`, POST `.../telemetry/extras`.
- **Kept with each round:** an upload is linked when it arrives to the current season's first unfinished round at
  its circuit (or to the round it's imported into), and linked uploads are never dropped; only unlinked ones are
  trimmed to the newest 40. Each keeps the summary as sent (`raw`) and the recorder version, so a later feature can
  read more from races already run. **Race data from the game** (More, or Import results → Race data;
  `/career/<token>/telemetry/data`) lists each round's linked sessions and what's missing, checked against
  `telemetry.DATA` (add a row there when a feature needs more). The recorder's **Rebuild results...** with an
  upload link sends old recordings again; the same session replaces its copy and keeps its round.
- **Importing:** on a round, **Import results** lists the sessions received. Opening one fills the usual import
  preview (driver matching, checks, compare with what's entered); **Apply** fills the results table, the fastest lap
  (Grand Prix only) and the AI level if none is entered yet. Nothing is saved or submitted until the normal save and
  submit. A `.json` file saved by the recorder can be opened the same way without an upload link. Each applied
  import remembers which game name is which driver, so the next one matches straight away.
- Sessions: qualifying (any Q format) goes to Qualifying; on a Sprint weekend the game's "Race" is the Sprint and
  "Race 2" the Grand Prix. Practice, Sprint Shootout and Time Trial aren't imported unless you choose a session.
- Uploads are drafts in the league file (`telemetry_uploads`), not exported, and never change results by themselves.

## 4.0.0: launch

The first public 4.0. Compared with beta.19, only launch tidying:
- **What's New** has one 4.0.0 entry for everyone instead of the 21 test-site builds (those are kept in
  `docs/4.0/BETA_CHANGELOG.md`), and the 3.2.4–3.2.6 entries from the live site are back in the list.
- **Visitor-facing wording:** Help no longer names the hosting setup code, the Readiness check's last card is
  "Version and backups" (no deployment notes), the Calculation Update page says Version 3 throughout, and a few
  leftover version labels are gone ("Before v1.16" now reads "Not recorded").
- **Design system page** (`/design`) is for site Race Masters only. It was reachable by any signed-in account.
- **Legacy banner** shows on a round from an older season even while the new season is selected.
- **Readiness check** says "at the start of a season, before Round 1" right after a rollover, not "mid-season (0 of 24)".

Test-site-only things stay off on the live site by themselves: the TEST SITE banner, live backup import, Try a season
finale and Delivery preview all need `F1_TRACKER_TEST_SITE=1`, the environment badge is hidden on Render
(production), and live reload only exists in `dev.py`.

### Switch day
1. Account → Settings → turn **maintenance** on, then take a backup (Backups & data, and the encrypted site backup).
2. Merge `release-4.0` into the live branch (`git merge --no-ff -X theirs origin/release-4.0`); `git diff
   origin/release-4.0` should be empty. Push, and Render deploys.
3. Open each league once: it backs itself up (`before-v26-upgrade`) and upgrades on first open.
4. Turn maintenance off. Everyone sees What's New for 4.0.0, then their league's one-time upgrade note.
5. Rollback if needed: redeploy 3.2.6 (commit `12e99b7`). It opens 4.0 data, and the pre-upgrade backups are in
   `backups/`.

### Shutting down the 4.0 test site
On render.com, open the test service (the one with `F1_TRACKER_TEST_SITE=1`) → **Settings** → **Suspend Web
Service** to pause it, or **Delete Web Service** to remove it. It has no disk, so nothing is kept either way. The
`release-4.0` branch can stay for the next round of testing.

## 4.0.0-beta.19: local development

- **`dev.py` / `dev.bat`** (docs/LOCAL_DEV.md) run the Flask dev server on 127.0.0.1:5050 with `F1_TRACKER_DATA_DIR`
  = `.devdata/`, `F1_TRACKER_ENV=local` and `F1_TRACKER_TEST_SITE=1` (so every send becomes a delivery preview,
  including an imported outbox). It refuses to start on Python other than 3.11, with `RENDER`, `SMTP_*` or
  `F1_TRACKER_BACKUP_PASSPHRASE` set, or with a data folder outside the project (the desktop app's
  `%LOCALAPPDATA%\F1UniverseTracker` and `/data` by name). `dev.bat seed|finale LOGIN` reuse `testsite.seed()` and
  `seed_final_round()`. `reset` renames `.devdata`, and never deletes it.
- **Live reload** is development only: a `/__dev/events` stream (answered before the site's own request hooks) and a
  small injected script. `create_app` accepts `STATIC_FINGERPRINT_FRESH`, which recomputes the `?v=` fingerprint on
  every page so edited CSS/JS gets a new address. Nothing in `server.py`, `render.yaml` or `launcher.py` changed.
- **CLAUDE.md** and **.claude/settings.json** are for Claude Code on a local PC. Push, merge, rebase, reset and clean
  always ask first. `/ship-4-0` (.claude/skills/ship-4-0) releases the next 4.0 beta the
  usual way: version, CHANGELOG, admin guide, tests, then a confirmed push to `release-4.0` (never the live branch).

## 4.0.0-beta.18: league list cache and race time Clear

- **League list cache** (`storage.list_careers`, added in beta.17). It was keyed only on the league file's and its
  `-wal` file's modification time and size. On a filesystem with coarse timestamps, two writes in the same tick could
  leave a summary stale until the next write. That would have mattered to account deletion and export, which pick
  leagues by membership. Now `storage.session()` drops a league's kept summary after any write it commits
  (`conn.total_changes`). A summary that was written to while it was being read isn't kept. Entries for deleted or
  expired leagues are dropped when the list is next read. Writes from another process still show up through the
  file stamp, as before.
- **Race time Clear.** The Clear button posted `race_at=""` after the filled time input, and the route read the first
  value, so nothing was cleared. The button now sends `clear=1`, and `race_time` treats that as an empty time. Old
  forms that send only `race_at` work as before.
- **Checked before pushing beta.17:** pre-4.0 leagues upgraded and rolled over with identical data on beta.16 and
  beta.17. This covered three fictional 3.x leagues (planned end-of-season switch, mid-season switch, accepted and
  pending Silly Season offers), with 0 differing rows across 52 tables, plus a browser run of the rollover.

## 4.0.0-beta.17: the 4.0 redesign

- **What it is.** A new look and layout for the existing features. The feature-to-destination map, the navigation and
  the round page's layout are in `docs/4.0/REDESIGN_MAP.md`. No route, schema, formula or permission changed.
- **Styles.** `static/css/pl.css` is the design system: tokens for both themes, the app bar, buttons, pills and
  links. `static/css/pl-pages.css` holds page layouts (round page, Home, Championship, pages outside a league). Both
  load after `app.css`. `race.css`, `race-pages.css`, `fonts-rc.css` and the Saira and IBM Plex fonts were deleted;
  Barlow is served from `static/fonts` (OFL licence alongside). A base rule written as `.x, html[data-theme] .x`
  outranks a plain `.x.is-on` or `.x:hover`, so its state rules carry the same `html[data-theme]` prefix.
- **League colour.** `base.html` now puts the league's accent on `<body>` as `--league` / `--on-league` instead of
  `--accent`. `--accent` (and the old `--red`) is the site orange everywhere, so older `app.css` rules that used them
  turn orange rather than red or the league's colour. The league badge (`.league-mark`) still gets the league's
  colour inline. Where `app.css` used red to mean a problem (Readiness blockers, missed targets, danger banners),
  `pl.css` keeps it on the red `--bad` tokens.
- **Round page.** `templates/weekend.html` is built from one `sec()` macro: a `<details class="ws-sec">` with a state,
  a Required/Optional tag, who it's for and a summary. Sections that belong to one session carry
  `data-session-only="q|s|r"` plus `data-session-strict`. `static/js/workspace.js` switches steps and sessions and
  renders the Review checklist. `static/js/weekend.js` saves the table and submits. Submitting first re-reads the
  checklist; a warning the user hasn't seen yet stops it once. The server's own once-only guard is unchanged.
- **Debrief readiness** (`app.weekend`). `next_gate` is the next round's gate status, read with `issue=False`, so
  opening the Debrief never issues targets or press. It's only read while that round hasn't started.
- **League list cache** (`storage.list_careers`). Each league's summary is kept, keyed by the league file's and its
  `-wal` file's modification time and size. Any write to a league, from any process, changes the key and the summary
  is read again. Callers get their own copy. Speed, repeat loads of each page on the same server (median ms), base
  beta.16 vs beta.17:
  - one league: about the same (Home 52.7 → 52.4, round 48.8 → 44.1, Standings 30.6 → 32.9);
  - 33 leagues: Home 92.0 → 49.5, round 93.1 → 49.0, Standings 61.7 → 33.0, Statistics 91.8 → 37.4, News 52.8 → 18.8.
  - The first visit to the round page downloads about 100 KB more (the fonts, now actually used, and the new CSS).
    It's all cached for a year after that.
- **Home's lists.** `insights.pending_actions` now counts a weekend target as done once it has a tier (chosen, or
  locked in as Standard at lights out), the same rule as the round gate (`gates.py`). Only a pre-2.4 target without a
  tier still asks to be accepted. Home's Waiting for also names results still to enter while a round is live, for
  Race Masters as well.
- **Theme default.** A browser with no saved theme gets light (it was dark). Saved choices are kept.
- **Static fingerprint and folders.** `_version_static_files` only adds `?v=` to files. Since beta.13 it also stamped
  the screenshot reader's folder address (`vendor/tesseract/`), so every file the reader added to it 404'd and
  screenshot import always failed.
- **Tests updated for the new page:** "Submit weekend", "Race times" and "Must fix" replace the old dialog and card
  wording. `test_v230` now checks a driver has no paddock button (its form action), since Waiting on names the
  "Open the paddock" job for everyone. The permission checks are unchanged.

## 4.0.0-beta.16: failed pop-up forms

- `shell.js` form restore: when the restored form sits in a closed `<dialog>`, it calls `showModal()` and repeats the
  flashed error inside the form as `p.form-error` (the dialog covers the toast). `.form-error` is `#b3261e` in the light
  theme. New test: each saved weekend step names the next one and who the round waits on. No schema change.

## 4.0.0-beta.15: League Readiness Check

- **Where.** `GET/POST /career/<league>/readiness` (`readiness_page`, access `ops`), linked from Manage League. GET runs
  the quick checks. POST (Race Master only, 403 otherwise) also runs the full-history checks and keeps that result in
  `<data dir>/readiness/<league>.json`, outside the league file. The page uses `career_page(read_only=True)`, which
  skips everything opening a page normally does to a league: `roles.touch`, closing settled windows, publishing
  announcements, the paddock tick, `touch_opened`, `impacts.on_open`/`refresh_if_stale`, `gates.my_todo` (it can offer
  targets), the change record and `mark_stale`. A test compares every table before and after a visit and a run.
- **How checks stay read-only.** `readiness.run` copies the league into memory with SQLite's backup API (one consistent
  snapshot) and runs every check on the copy. Reused helpers that write as a side effect (`weekend_rows` syncing the
  entry list, `teamlife._bank_since`, `recalc.preview`'s savepoint) only touch the copy. Anything they queue for
  notifications or Discord is dropped.
- **Fingerprint and staleness.** `readiness.fingerprint` hashes every league table except activity
  (notifications, news, logs, chat, check-ins, predictions), `career_members.last_active` and volatile meta keys. A kept
  full check whose fingerprint differs from the live league shows as out of date and counts as *Not checked*. The
  fingerprint is taken again after checking, so a save that lands mid-check marks everything out of date.
- **Checks** (26, in `readiness.CHECKS`, each with what it verifies, shown under *What each check verifies*):
  - Members and drivers: logins (`weekend.unlinked_players`), assignments (duplicate logins, AI or deleted drivers,
    `PRAGMA foreign_key_check`), seats (`seats.season_states`; free agents and released drivers are valid outcomes).
  - Race weekends: weekend start (`weekend.results_blocked`, `gates.status(issue=False)`), results
    (`S.submission_check`), timing (`ai3.missing_pace`, legacy-aware), weather (optional), saved-but-unsubmitted rounds,
    player tasks (pledges, team goals, press that no gate requires), incidents (never blocking), submitted rounds of
    this season (quick) and earlier seasons (full).
  - Career and contracts: rounds left, dismissals awaiting a decision, pending offers (counts only, never terms),
    transfer windows (never closed by the checker), and `seats.rollover_review` for next season (team conflicts are
    blocking because `season_new` refuses them). Season-end processing for earlier seasons is a full check.
  - Migration and tracking: file format and 4.0 tables, the Calculation Update and `calc_version`, the tracking record
    compared with `tracking._plan`, review items, pending change notices, upgrade-notice acknowledgements (optional),
    and historical records (full).
  - Derived: standings are live; `recalc.preview(history=False)` for the season under way under its own rules; stored
    Reputation carried between seasons compared without re-running any formula (full).
- **Severity.** *Blocking* only when an existing rule refuses an action, and it names that action. *Warning* needs
  attention. *Optional* never changes a status. Target statuses, worst first: Check failed, Blocked, Not checked, Needs
  attention, Ready (plus Not applicable, for example no round left to submit). A check that raises is *Check failed*
  with only the exception type, never its message.
- **Permissions.** Each check has an audience. Scorekeepers get `ops` checks only (race weekends) and only the weekend
  target. Findings carry names and counts, never press answers or offer terms.
- **Speed.** Quick checks took about 0.04 s, and the full check about 0.1 s, on a two-season test league.

## 4.0.0-beta.14: Python version pinned
- `.python-version` (3.11) fixes the Python version Render uses, on the test site and, after the switch merge, on the
  live site. The live site already runs 3.11 (its build installs `cp311` packages).
- Why: Python 3.12 changed how `sum()` adds floating-point numbers. The calculations are tuned on 3.11; on 3.12/3.13
  the golden-season tests fail (Driver Value ±0.5, car-adjusted rating ±2.6, AI recommendation ±3, one car-rank swap).
- Don't remove or raise it without re-running `tests/test_v400_phase0.py` and `tests/test_v400_phase1.py` on the new
  version and treating any difference as a calculation change (approval and change notices).

## 4.0.0-beta.13: reliability and speed

- **Where forms go back to** (`f1tracker/navigation.py`). `shell.js` adds a hidden `return_to` (path, query and
  #fragment) to every POST form. `navigation.back(default, token, anchor, prefer)` uses, in order: a destination the
  route chose, `return_to`, an older `next` field, then the Referer, but only after `navigation.safe` has matched it to
  a GET page of this site (never `/api/`, `/static/`, sign-in or sign-out pages, other hosts, or another league's
  pages). Otherwise each route has its own fallback (the round's stage, the standalone page), never the site Home.
- **Failures.** A CSRF failure or signed-out POST flashes why and returns to the page (signed out: sign in with `next`).
  `fetch` callers get JSON (`400 {expired: true}` / `401`). A failed form stores `session["_form_failed"]`; the next page
  prints `<meta name="form-failed">` and `shell.js` restores the typed values from `sessionStorage` (never passwords).
  POST 403s now render an explanation and a back link (status stays 403). GET pages that raise `ValidationError` flash it
  and return to the referring page.
- **Once-only writes.** Every league POST starts with `BEGIN IMMEDIATE`, so concurrent requests run one at a time. A
  repeated identical press answer, target choice, pledge, offer accept/decline or incident report returns "Already …"
  without writing, notifying or adding an Activity Log entry (`g.repeat`). A different answer to an answered question is
  still refused.
- **Speed** (measured with the test client on a 3-season, 72-round league; repeat-load server time and SQL statements):
  League Home 295 ms / 7,334 → 101 ms / 1,804; Home after a save 418 / 9,188 → 119 / 2,041; Race Weekend 171 / 5,071 →
  77 / 1,693; Debrief 179 / 3,664 → 91 / 1,557; Career 196 / 3,562 → 102 / 1,140; Standings 64 / 1,102 → 41 / 383;
  historical Home 168 / 2,828 → 85 / 1,411. Causes fixed: `services.sync_not_run_results` rewrote every upcoming
  lineup (300+ UPDATEs) on each page; standings, round ranks, the AI tracker replay and the difficulty recommendation
  were recomputed many times per request (now remembered per connection by `f1tracker/memo.py`, dropped automatically on
  any write or `ROLLBACK`); `teamlife.press_pens` rebuilt questions for every past round; the change-notice snapshot was
  refreshed before the page instead of after. Static files carry `?v=<mtime>` and are cached for a year.
- **AI tracker policy (needs a decision).** The 4.0.0-alpha.2 notes say a season under way keeps the tracker it started
  with; 4.0.0-beta.1 says the season under way switches to the track-aware recommendation when the league first opens
  on 4.0. The code does the beta.1 thing (`engine.ensure_latest`); the schema notes were corrected to match. Stored
  recommendations for finished rounds are never recalculated.
- **Python version matters for calculations.** `test_golden_season_matches_exactly[3]` and
  `test_no_career_numbers_changed` pass on Python 3.11 (what the live site runs) and fail on 3.12+, whose `sum()`
  adds floats with extra precision (e.g. two teams with exactly equal results at round 7 swap car rank; AI
  recommendations move by up to 3). Run the tests, and the site, on 3.11.

## 4.0.0-beta.12: legacy seasons and the upgrade notice

- **What counts as an upgrade.** `schema.migrate` calls `tracking.record_upgrade` once when it opens a league file with league data but no `audit_events` table (or a schema below 22). Live 3.2.4–3.2.6 files say schema 22 too, which is why the table is the test and not the number. It covers both ways in: opening a copied live file and *Import a league*. New 4.0 leagues and the test-site leagues earlier betas already opened get no record and no notice. Re-import a fresh live copy to try it.
- **Tables (format 26).**
  - `tracking_migrations`: one row per kind (`4.0`), with from_schema, migrated_at, start_year/start_round and the audience (usernames in the league at the upgrade).
  - `season_tracking`: per season and feature, `from_round` (NULL = not tracked that season), `review`, `source` (`upgrade` / `records` / `owner`) and a detail line.
  - `tracking_notice_acks`: (migration_id, username, acked_at).
  - A season with no rows is fully tracked.
- **Where tracking starts.** 4.0 features (race times, incidents by session, the stored pre-round AI recommendation) start at the first round of the season under way with no results entered. A round already in progress finishes under the old rules. If every round is played, they start at round 1 of the next season.
- **3.x features are read from the data.** Weather, weekend targets, pre-race press and post-race press come from what each season actually holds: stored entries, targets offered, `press_required`, the paddock opened. Release dates are never used.
  - First used at round 1: tracked all season.
  - First used later: tracked from that round and flagged `review`.
  - Never used: not tracked that season.
- **Owner review.** `GET/POST /career/<league>/legacy-tracking` shows the record to every member. The Race Master can confirm or change the start round of a 3.x feature. They can't move a start past a round that has data, and can't move 4.0 starts. Only the record changes.
- **Display rules.**
  - `tracking.round_tracked` / `empty_text` decide "Not recorded" against "Not tracked under this season's rules".
  - `ai3.missing_pace` never asks for race times on an untracked round.
  - Press pens and tasks are hidden on rounds where press wasn't tracked and nothing was answered.
  - `tracking.coverage` gives the "Based on N eligible rounds · Tracked since …" line.
  - Stored values always show.
- **The notice.**
  - Who sees it: members of the league at the upgrade, plus the site owner.
  - When: after any mandatory step (change notices, pledge, team goal) and never on the same page as the site-wide What's New pop-up. The one-off league banner waits a page.
  - *Got it* (`POST /career/<league>/upgrade-notice`) is stored in the league file per username and migration. *Not now* or Esc (`POST …/upgrade-notice/later`) only sets a flag in that browser session.
  - The calculation line is chosen from `calc_migrations` made since the upgrade:
    - `full`: a separate recalculation sentence, pointing to Changes to your driver.
    - `future`: "latest calculations from round N; everything before is unchanged".
    - Otherwise: "No results, standings or career outcomes were recalculated."
- **Nothing is recalculated.** Recording tracking never touches `season_calc`, results or career numbers. Calculation changes still go through `engine` / `migration` and the change notices.

## 4.0.0-beta.11: a league one round from the end (test site)

- **Account → Settings → Try a season finale** (site owner, test site only, `POST /settings/test-final-round`) runs
  `testsite.seed_final_round(username)`: the golden-fixture league (`golden.play(..., rounds=-1)`, same seed, two player
  drivers at Williams and Haas) with every round but the last played and submitted, named "Final Round Test
  (fictional)". The signed-in owner is linked as Race Master driving Player One. The last round uses the site's
  normal defaults (round gates and race weekends as for any new league).
- Command line: `python -m f1tracker.testsite final-round [login]`. Both refuse to run without `F1_TRACKER_TEST_SITE=1`.
- The free test service forgets its data on restart; click the button again to get a fresh one.

## 4.0.0-beta.10: linking a login to an existing player driver

- **The bug:** a player driver that already existed (created with the league, added without a username, or loaded from a backup) could only get a login from the members table, and only once that person was already a league member. A join request naming that driver was refused as a duplicate name, and approving a request always created a new driver.
- **The fix:** `POST /career/<league>/members/link/<driver_id>` (Race Master only, audited as "Linked a login to a player driver") links a username to a player driver nobody drives, adding them as Member if needed, keeping a Race Master or Scorekeeper role, and clearing that driver's *No account* tick. `career_join` accepts the name of a player driver nobody drives; `members_request` approval links the chosen (or same-named) free player driver instead of calling `add_player_driver`. F1 drivers and driven player drivers are still refused. No schema change.

## 4.0.0-beta.9 / 3.2.6: transfer windows close by themselves

- **The bug:** nothing closed a market window except the Race Master's *Close window* button (Market administration) or the season rollover, so a Silly Season with every deal done stayed open indefinitely.
- **The fix:** `market.close_if_settled` closes a window when no offer in it is Pending and every active player driver has an Accepted offer in it, a contract covering its target year, or no approach left (or no team left to approach). It runs after each signing and decline, and `market.close_settled_windows` runs on every league page load, which also closes windows left open before this version. Closing posts a paddock headline and one notification (dedupe `window:<id>:closed`). No schema change.
- A driver who still has approaches left keeps the window open; close it by hand if they're done.

## New in 4.0.0-beta.1: the UI overhaul (test site)

- **Navigation.** Home, Race Weekend, Championship, Career (drivers only) and More; Manage League is separate and shows
  only for Race Masters (Scorekeepers get "Results entry"). New addresses: `/career/<league>/race-weekend` (the current
  round's workspace; `?stage=prepare|sessions|review|debrief` and `&session=q|s|r` open a step directly),
  `/championship` (→ Standings), `/my-career` (→ Garage, or More without a driver) and `/more`. Every old address
  still works; `/weekend/<id>` is now the workspace.
- **Where the workspace opens** is worked out from the saved round (`f1tracker/workspace.py`), never from the last
  page someone visited: Prepare before lights out, Sessions once results can go in (at the first session that isn't
  complete), Review when every session is entered (Scorekeepers and the Race Master), Debrief once submitted.
- **Race Master tools** on the workspace (reopen, reset, team orders, targets and excuses) are in a separate
  "Race Master tools" strip at the bottom. Opening a round early stays next to the ready board in Prepare.
- **Double submit.** Result saves take the database write lock before reading the round, so two submissions arriving
  together run one after the other; the post-race steps (headlines, emails, relationship changes) run once. A
  Scorekeeper's repeated submit gets `already_submitted` and the page simply moves to the Debrief.
- **Incidents.** `incidents.session` (qualifying / sprint / race / weekend). Rulings update one news item per round
  (`news.ref = stewards:<event id>`) instead of posting a headline each; Discord gets one post when the story first
  appears. Deleting reports updates or removes the story. On the first open under format 25, older one-per-ruling
  headlines are folded into the round's story.
- **Latest calculations only.** `engine.ensure_latest` runs when a league is opened: a league still on engine 2 is moved
  with the non-destructive "from the next round" path (completed rounds keep their numbers; a Calculation Update
  record is written with the actor "Paddock Legacy 4.0"), and the current season uses the track-aware AI model. The
  Calculation Update pages now redirect to Home, and the engine scan is no longer linked from System controls (the
  command `python -m f1tracker.phase0 scan` still works). The engine 2 code stays for the history it calculated.

## New in 4.0.0-alpha.2: the track-aware AI recommendation

- **Model:** `f1tracker/ai_track.py` (`track-aware-1`). New leagues and each new season use it (meta
  `ai_model:<season id>`); seasons already under way keep the v3 tracker until they finish.
- **Baselines:** `f1tracker/data/ai_baselines/<version>.json` holds the F1Laps F1 26 averages per circuit with game,
  source, source date, dataset and model versions. The site never contacts F1Laps.
- **Updating the baselines** when F1 26 gets meaningful AI changes: copy the current file to a new name (for example
  `f1laps-f126-2027-03-01.json`), change the values, `source_date` and `dataset_version`, then set
  `CURRENT_SNAPSHOT` in `ai_track.py` to the new name. Keep old files: rounds already played name the snapshot they
  used. Only future rounds change.
- **Stored per round** (schema 23, `ai_track_recs`): the recommendation shown before the round (baseline, league
  adjustment, track history, final, confidence, full explanation, snapshot and model versions), frozen at the first
  submission, and the AI actually used. A correction updates only the AI used.
- **Circuits not in the snapshot** (a custom round) use the average of all circuits and say so.
- **League setting:** Race weekends → "Use each circuit's history in this league" (on by default).

## New in 4.0.0-alpha.1 (test site only, Phase 1)

- **Environment badge.** `F1_TRACKER_ENV` = local / test / staging / production names each copy of the site. Without
  it: the test site (`F1_TRACKER_TEST_SITE=1`) is *test*, a site on Render is *production*, anything else *local*. A
  badge next to the version shows every name except production.
- **Health check:** `GET /healthz` (public) returns JSON: ok, version, environment, schema and two checks (accounts
  database, writable data folder); HTTP 503 if either fails. Point Render's health check path at it.
- **Structured logs.** `server.py` logs JSON lines (time, level, logger, message, and per request: method, endpoint,
  status, ms). Messages are scrubbed of email addresses, links and long tokens. No paths, names or form values.
- **Site errors** (Account → Settings → Site health): errors grouped by kind and place, with a count; the newest 200.
  Scrubbed the same way. Clear it when you've looked.
- **Delivery preview** (test site): nothing is ever sent; each email, Discord post and phone alert is saved instead
  (addresses masked, newest 300). An imported live backup has its SMTP password removed and every league's Discord
  webhook replaced with a placeholder.
- **Change record.** League files move to schema 22: `audit_events` (actor, time, action, target, before/after for
  members and roles, league settings and rounds), protected by triggers so rows can't be edited or deleted. Race
  Masters see it under Activity log → Change record. Site-owner actions go to `site_audit` in accounts.db (Account →
  Settings → Site change record). Secrets are recorded only as "set" / "not set"; passwords never.
- **Every route declares its access** (`public`, `self`, `member`, `ops`, `master`); tests call every site route
  anonymously, as an ordinary member and as the owner, and every league route as each role.
- **Theme and density** are stored on the account (`users.theme`, `users.density`).
- **Rollback:** the schema 22 change only adds a table and two triggers. A v3 build opens a schema 22 file normally
  (it ignores the extra table); the pre-upgrade backup is in `backups/` as usual.

## New in 3.2: maintenance mode

- **Where:** Account → Settings → System controls (the site owner only: the account made with the setup code, not
  every site Race Master). Turning it on needs MAINTENANCE typed; turning it off asks for confirmation. Every change
  (on, edit, off) is recorded in the site change record (`site_audit` in accounts.db, append-only; 4.0 keeps it).
- **Settings** (accounts.db `settings`): `maintenance_enabled`, `maintenance_message`, `maintenance_expected_end`
  (UTC), `maintenance_pause_deliveries`, `maintenance_enabled_at`, `maintenance_enabled_by`.
- **What happens:** a check before every request lets only the signed-in site owner through, judged from the
  account in the database (no address, cookie, parameter or secret link can get round it). Everyone else, including
  sessions already signed in, gets the maintenance page: HTTP 503, `Retry-After` (seconds to the expected reopening,
  or 600), `Cache-Control: no-store` and `Clear-Site-Data: "cache"`; the JSON API gets
  `{"ok": false, "maintenance": true, ...}` with 503. Reachable by anyone: sign-in (and its two-step code), sign-out,
  static files, the service worker, `/maintenance` and `/healthz`. A non-owner can sign in but still sees the closed
  page.
- **Open pages:** the service worker never serves pages from a cache and empties any cache on a maintenance answer;
  an open page reloads to the closed page on its next request, when the tab is shown again, or within two minutes.
- **Deliveries:** with *Pause outgoing deliveries* on, emails, phone alerts and Discord posts are saved in the outbox
  and not sent (direct test sends are refused). Turning it off (or turning maintenance off with *Also resume*) sends
  them, once each. The pause is its own switch: it can be used without closing the site.
- **Emergency switch:** set `FORCE_MAINTENANCE=true` in Render (service → Environment). Maintenance is on while
  either the setting or the variable is on; the website can't turn the variable off, and the owner's pages say when
  it's set. Remove it and let Render redeploy to reopen.
- **Still works for the owner:** backups, upgrades (league files upgrade when opened), integrity checks, restore and
  every admin page.
- **Controlled test after deploying (it's off by default):** open System controls, set a message, type MAINTENANCE and
  turn it on; open the site in a private window (you should see the closed page) and check your own window still
  works; turn it off and check the private window works again.

## Before and after the upgrade

- **Nothing to do to upgrade.** Each league upgrades itself (schema 17 → 18) the first time it's opened, after writing
  `backups/<league>-before-v18-upgrade-<time>.f1career`. Nothing existing is changed or removed.
- **Check notifications.** Every membership keeps its old results-email choice for that league only; everything else
  starts on *Important only*. Ask members to open **Notifications** in each league, and mute any test league.
- **Check visibility.** Leagues are private unless you choose Public or Listed (League settings → Visibility).

## Site settings (Account → Settings)

| Setting | Default | Notes |
|---|---|---|
| Let people create their own login | as before | Sign-up needs email set up. |
| Anyone can create a league | **off** (admins only) | Creators become that league's Race Master. 5 new leagues a day per account. |
| Email (SMTP) | as before | Or the SMTP_* environment variables on Render. |

## Per-league settings (League settings)

All of these affect one league only.

- **Visibility**: Private, Public (a share link) or Listed (also in the directory). Public pages only show submitted
  rounds, names, standings, records and news; never emails, usernames, notes, garages, offers, drafts or rounds in progress.
- **Selectable team goals**: off by default. See Help → Team goals. Rewards: Safe +1/0, Competitive +3/−1, Ambitious +6/−3
  Reputation, settled once at the next season rollover.
- **AI difficulty**: recommendations on/off; *Count Sprint points* (on by default, as before 2.0); *How each round is
  judged* (2.4.1, meta `difficulty_mode`): `blend` (default), `car` or `overall`.
- **Team orders, weekend targets, round gates**: as in 1.20.
- **Joining**: requests, invite only or closed. **Rollover default** for ending contracts.
- **Discord webhook**: kept private; never shown in the Activity Log, exports or downloaded backups.

## Everyday admin tools

- **Members & roles**: roles, invitations (20 an hour per Race Master), join requests (5 an hour per account),
  **Hand the league over** (type the new Race Master's username).
- **Announcements**: pinned, targeted by role, scheduled, with expiry. The form shows who will see it, get a phone
  alert and get an email. Scheduled ones go out the next time anyone opens the league.
- **Grid & contracts**: contract states and seat problems; the **seat repair tool** fixes a mismatch in one step.
- **Season rollover** (Calendar → *Start the next season…*): shows each player driver's seat and contract, asks what happens
  to ending contracts, makes a backup, then settles pledges and team goals and starts the season.
- **Calendar**: rounds with results keep their number. Use *historical correction mode* only to fix a past mistake (logged).
- **Notifications (Manage)**: the delivery log (what, when, how many; never who). Deliveries are held and logged if a
  league suddenly sends too much.
- **Backups & data**: scheduled backups, safety backups (before rollover, restore, upgrade and delete), an integrity check,
  restore (backs up the current state first), JSON export and standings CSV. Downloads leave out the Discord webhook
  and public-link key.
- **Import** (League library → *Import .f1career*, site admins): a file is checked and summarised first and always becomes a new league.
- **Activity log**: every league action as a sentence. It never records passwords, codes, sessions, OCR text or webhooks.

## New in 2.1

- **Change notices.** Anything that changes a player driver's numbers (an update, switching team orders off, re-issuing
  season goals, a dismissal) is shown to that driver with before/after and a reason, and they must agree before using
  the league. You can see every notice and who agreed on *Changes to your driver* (linked from My settings).
- **Mid-season dismissals** (League settings, on by default). Decisions appear on the Control Room and in *Grid &
  contracts → Final warnings & dismissals*. Overruling needs a note.
- **Goal controls.** Team goals page: *Re-push targets* and *Reset and let them choose again*. Relationships page:
  *Re-issue season goals*, *Re-issue for everyone*, *Re-issue R{n} target*.
- **AI difficulty** recommendations now adapt from every round (see Help → AI difficulty).
- **Team orders Off** removes all orders and undoes their effects (with change notices).
- New tables, created when first needed: `impact_notices`, `impact_acks`, `ultimatums`. New meta keys: `calc_version`,
  `calc_snapshot`, `calc_snapshot_stale`, `midseason_sackings`, `team_goal_reopen_*`. No schema version change.

## Accounts: one owner, everyone signs up (2.1.2–2.1.3)

- **First start after 2.1.3**: every login and reserved username is removed once, and each league's links to those
  logins (members, pending invitations/join requests, notification choices) are cleared. Drivers, results, seasons,
  contracts and settings are untouched. Copies are saved first: `accounts-before-2.1.3-reset-*.db` in the backups
  folder, and a `before-213-login-reset` backup of each league. The site then shows **Create the site owner**.
- **Making the owner**: on Render open your service → **Environment**, copy `F1_TRACKER_SETUP_CODE`, and enter it on the
  setup page with a username and password. (If the variable is missing, add one with any long random value.) The owner
  is Race Master of every league.
- **Everyone else** signs up from the login page. Then add them to a league on **Members & roles** (type their
  username, pick their role and their driver), or invite them, or let them ask to join.
- **Account recovery** (owner only, My account): type an exact username or email. Every account with that username or
  email is listed (several accounts can share an email, from 2.2); for each one you can set a new password,
  change the email, turn off two-step sign-in, sign out everywhere, or delete the login.
- **Rolling back**: with the site stopped, put `accounts-before-2.1.3-reset-*.db` back as `accounts.db` and restore
  each league's `before-213-login-reset` backup, then deploy the earlier version.

## Race Master tools added in 2.1.3

- **Weekend targets on a round**: open the round → Weekend targets → *Re-issue* (before the race) or *Remove* (any
  round; on a completed round its effect is undone and the driver sees a change notice).
- **Team goals**: reopening a team's choice sends that team's drivers to choose before anything else; re-pushing
  shows them the new targets to agree to.
- Race Master tools follow the view mode (Driver / Spectator preview show what those roles see).

## 3.1.2: safer logins and messages

- **Outbox** (`f1tracker/outbox.py`): emails, Discord posts (one row per message) and phone alerts are written to an
  `outbox` table in `accounts.db`, sent in the background and deleted once sent. On failure they're retried with a
  growing wait (up to 5 attempts, then dropped with a log line). Anything left by a restart is sent when the site
  starts, and then at most once a minute on requests. Rows hold addresses, text or the Discord webhook only until
  sent; they're never shown or exported.
- **Login lockout:** a username is still locked after too many wrong passwords. An address is locked only after
  `IP_MAX_FAILURES` wrong passwords across at least `IP_MIN_USERNAMES` (3) different usernames in the lock window, so
  a shared home or mobile connection isn't locked by one person's typos.
- **Backup reminder:** site owners see a Control Room banner when the encrypted backup is overdue (14 days); "Remind
  me in a week" snoozes it (`settings.offsite_snooze_until`).
- **Removed:** the 2.1.3 start-up login reset (`reset_all_logins_213`) and its league-link cleanup. A start-up never
  changes logins now.
- **Names:** placeholder text and test data use fictional names only. Older commits in the Git history still contain
  them; rewriting history is possible but needs a one-off forced push.

## 3.1.1: unlocking accounts

- **Account recovery** (Account → Settings, find the person) now shows their sign-in state: locked (with minutes left
  and the number of wrong passwords), locked by too many wrong two-step codes, or not locked.
- **Unlock sign-in** clears the username's wrong-password lock and its two-step code limit. Tick *Also clear locked-out
  internet addresses* if they're still blocked. That clears the temporary per-address locks, since you can't know which
  address they used.
- **Set password** now also unlocks the account and sets `users.must_change_password`. At their next sign-in the person
  is sent to *Choose your own password* (every page and the API wait until they do; they need the password you gave
  them), and it's cleared when they choose their own.

## New in 3.1: weather

- Each session's weather (quali / Sprint / race: dry, overcast, light rain, heavy rain, changing) is stored in a
  `weather` table inside the league file, created on first use (no schema version change, no upgrade backup). It's
  included in exports and backups like every other table.
- Scorekeepers and Race Masters record it (`POST /career/<id>/weekend/<round>/weather`, logged in the Activity log).
  It's a record only: no formula reads it. Resetting a weekend clears it.

## 3.0.1

- **Change notices:** a driver's page lists only their own notices. Race Masters see other drivers' notices in a
  separate section, and only while viewing the league as Race Master (not in Driver or Spectator view).
- **Leagues on this site (site admin, Account → Settings):** every league file with its ID, members and last opened,
  flagged Demo, Demo builder file or Can't be opened. *Delete a league* takes the ID typed twice; a copy goes to that
  league's automatic backups (`backups/auto/<id>/…-before-delete…`) first where the file can be read.
- **Stuck demo league:** `demo-template-build` is the demo builder's work file. An interrupted build used to leave it in
  the league list forever (every cleanup skipped it); it's now removed by the normal demo cleanup once it's older than the
  demo lifetime, and it can be deleted by ID.
- **Race Master menu:** the tools list no longer has its own scroll box (it could shrink to nothing); the sidebar scrolls.
- **Form/Reputation chart:** Version 3 seasons are charted with `calc3.round_timeline`, the same numbers the
  standings show at each round (Future-only seasons keep Version 2 values up to the cutoff and blend in after, like the
  standings). No data changes and no recalculation: it's how the chart is drawn.

## New in 3.0: The Definitive Release

**What happens on upgrade.** Nothing to do. Each league on Calculation Version 3 is recalculated once the next time
someone opens it (a backup is written first, as with every calculation update). Everyone sees a one-off note, and each
player driver whose numbers moved gets a change notice to agree to before carrying on. Leagues still on Version 2 are not
affected. Pledges, team goals and weekend targets already chosen keep their terms. The formulas and the before/after
tables are in `docs/CALCULATION_V3.md` §26.

**Encrypted off-site backup (site owner).** Account → Settings → *Encrypted backup to keep somewhere else*. Choose a
passphrase (12+ characters; keep it in a password manager: it can't be recovered) and download `paddock-legacy-backup-
<date>.plbk`. It holds `accounts.db` and every `careers/*.f1career`, encrypted with AES-256-GCM (scrypt key). The page
shows when you last made one and flags it as due after 14 days. To restore on a new host:

1. On any computer with Python 3 and `pip install cryptography`, from a copy of the code:
   `python -m f1tracker.offsite decrypt paddock-legacy-backup-<date>.plbk restored.zip` (asks for the passphrase and
   checks every file against its checksum).
2. Stop the site, unzip `restored.zip` into the empty data folder (`/data` on Render: `accounts.db` at the top,
   league files in `careers/`), and start it again. Everyone signs in again (sessions aren't in the backup).

**Other admin-visible changes.** The Race Master menu is grouped into Race, People, Career and System; the new-league
setup is Essentials → Players → (optional) More options → Ready; downloaded league backups are rebuilt without any
trace of the Discord webhook (the copies on the server are unchanged); a failing daily backup is logged instead of
stopping the page.

**Season Two freeze.** After 3.0 goes live, career formulas stay as they are for the whole season. Only security,
data-loss and serious bug fixes go out; other requests wait for 3.1, and balance is reviewed after the season with
its real data.

## New in 2.5: Calculation Version 3

- **Upgrade**: leagues move to schema 21 when first opened (a `before-v21-upgrade` backup is written). Nothing is
  recalculated: an existing league stays on calculation engine 2 until its Race Master answers the Calculation
  Update (the Race Master is sent to it first; drivers never see it). New leagues start on engine 3.
- **Calculation Update** (`/career/<token>/calculation-update`): A = recalculate the active season (backup
  `before-calc-v3`, a savepoint preview that is rolled back, explicit confirmation, one personalised notice per
  affected player driver); B = Future only (cutoff = last completed round, frozen values in `season_calc.frozen`,
  engine 3 from the next round, blended in over 6 rounds); C = later (reminder banner, hideable per session).
  Every update is a `calc_migrations` row with before/after values, approver and backup; the page lists each
  notice and who agreed. **Rollback** restores that update's backup (the state just before is backed up too).
- **Engine selection**: `meta.calc_engine` / `meta.calc_choice`, `season_calc(season_id, engine, cutoff_round,
  frozen)`. Completed seasons keep their engine. `engine.round_v3(event)` decides per round.
- **Formulas**: all in `docs/CALCULATION_V3.md`; code in `calc3.py` (standings, ranks, Form, Reputation, value),
  `relations.py` (`_assess_v3`, `goals_v3`, `_pace_v3`, `carry_rewards`), `teamgoals.py`, `teamlife.py`
  (targets, `rule_order`), `ultimatums.py`, `market.py` (emergency offer, negotiation), `pitch.py`, `ai3.py`.
- **New data**: `results.no_fault`, `points_override`; `events.gp_distance`, `sprint_distance`, `cancelled`;
  `drivers.career_status`; `team_orders.ruled_by/ruled_at/reason`; `team_goals.position`; `ultimatums.kind`;
  tables `round_ranks`, `pace_inputs`, `ai_recs`, `season_calc`, `calc_migrations`. League setting
  `sprint_min_distance` (default 50).
- **Race Master jobs on engine 3**: tick *No fault* on a mechanical DNF (results page); rule team orders (Team
  management); optionally switch a final warning to a teammate target and pick a free agent as replacement (Grid &
  contracts); mark AI sessions representative or not (round page → Pace & conditions).

## New in 2.4.1: AI difficulty blend

- **Formula** (`services.player_event_score`): each finishing player driver gets a car reading (expected finish
  2 × car rank − 0.5) and an overall reading (expected finish = middle of the grid, (cars entered + 1) ÷ 2), each
  0.40 finish + 0.20 qualifying + 0.15 points + 0.25 AI teammate as before. Round score =
  (1 − s) × car + s × overall, with s = `DIFF_OVERALL_SHARE` (0.5) in Blend, 0 in Car only, 1 in Overall.
- **No raise while struggling** (`services._adaptive`): if the step would be up and any player is "struggling" on the
  round score, or their weighted overall reading is `DIFF_BACK` (5) levels or more below the level used, the
  recommendation holds and says who it's waiting on. Applies in every mode.
- **Calculation version 3**: each league recalculates once when first opened and shows the 2.4.1 note. Nothing
  stored changes (the recommendation is worked out fresh), so there are no per-driver change notices.

## New in 2.4

- **Upgrade**: leagues move to schema 20 on first open (a `before-v20-upgrade` backup first). New table
  `target_options` (three offered targets per driver per round) and `weekend_targets.tier / hit / miss` (the choice and
  its reward/penalty; older targets have no tier and keep +2 / −1.5). `CALC_VERSION` is 2, so each league also runs
  **Recalculate everything** once on first open and everyone sees a one-off note (meta `calc_announce`,
  `calc_seen_<username>`).
- **Recalculate everything** (League settings → Data & tools, or `/career/<token>/recalculate`): re-judges weekend targets
  of completed rounds, replays each team relationship's extras (press, targets, team orders) from `bonus_since_*`
  (set whenever a relationship starts again) and rebuilds the Reputation chain across seasons including pledge and
  team-goal rewards. It previews the difference, saves a `before-recalculate` backup, and writes change notices.
- **Reset weekend** (round page → Reset weekend, Race Master): only the latest started round of the current season, and
  not after a dismissal decision on that round. Saves a `before-reset-r<n>` backup, then removes results, press
  answers, targets and their options, predictions, check-ins, fan votes, incidents, gate overrides, this round's news
  and the targets/orders handed out for the next round; relationship extras are replayed. Comments stay.
- **Login requirement**: with race weekends on, the paddock can't open (by hand or automatically) while a seated player
  driver has no league login linked. *Members & roles → No account* marks a driver as deliberately login-free
  (meta `no_account_drivers`).
- **Car strength fix**: a team with no AI driver keeps its place from the car ratings instead of dropping to last after
  three rounds.
- **AI difficulty**: each round is scored against the car's expected finish (2 × car rank − 0.5), its points at that
  finish (`DIFF_PLACES` = 8 places, `DIFF_POINTS_SCALE` = 15 points for a full ±1) and the AI teammate.
- **Settings**: `/career/<token>/settings` is a hub; each page (`/settings/<section>`) posts `section=` and saves only
  its own fields. Posting without `section` still saves the whole form as before.
- **Team management** (`/career/<token>/team-management`): all Race Master goal/target tools; the old POST routes are
  unchanged and return there when posted with `back=admin`.

## New in 2.3: race weekends

- **Upgrade**: leagues move to schema 19 the first time they're opened (a `before-v19-upgrade` backup is written
  first). New columns on `events`: `paddock_at`, `paddock_by` (a username, or `auto`), `lights_at`, `lights_by`.
  New meta keys: `race_weekends` (default on) and `press_bank_since` (rounds submitted before it keep their old
  post-race questions).
- **How a round runs**: Open the paddock (Scorekeeper / Race Master, or automatically an hour before the scheduled
  race time; there's no background timer, so it happens on the next page view) → drivers do pre-race press, target and
  check-in → Start the race (the round gate is checked here; the Race Master can override with a note) → enter and
  submit results.
- **Strict**: the results API refuses a round that hasn't started (HTTP 423), for every role. Rounds with results
  (In Progress or Complete) are never blocked, so corrections work as before.
- **Turning it off**: League settings → Race weekends. Results then go in at any time, as in 2.2.
- **Rolling back to 2.2.1**: works as is; 2.2.1 ignores the new columns. Pre-race answers stay in `press_answers`
  (their keys start with `pre_`).

## New in 2.2

- **Do-this-first steps** (change notices, then the growth pledge, then the team goal) come from one ordered list, so a
  driver is walked through them in turn. This fixes the loop after a rollover with a provisional seat.
- **Team goal targets** count points already scored and the rounds left, blend in observed pace (done ÷ (done + 4))
  and last season's scoring, and keep each tier at least 3 points (or 25%) above the one below. Existing choices keep
  their numbers; use *Re-push targets* on the Team goals page to recalculate one (the drivers see the change first).
- **AI difficulty** reacts faster (see Help → AI difficulty for the numbers), shows the level band and a one-line
  evidence summary, and says whether Sprint points counted (still on by default).
- **Passwords**: new passwords need 8+ characters and can't be a common one. Existing passwords still work.
- **Contact email** (Account → Settings) is shown on the Privacy and Terms pages, which now carry an effective date.
- **Full career simulation** preset turns on selectable team goals.
- New site setting: `contact_email`. No league schema change.

## Accounts and security

- **Signed-in devices** and **two-step sign-in** are in each person's account page. To help someone who lost their
  phone: Accounts → All logins → **Reset two-step** (also signs out their devices).
- **Delete account**: people can delete their own login. Leagues keep their results. The last site admin can't delete
  themselves, and the only Race Master of a league has to hand over first.
- **Reports**: listed leagues can be reported; open reports are under Accounts → Reports. *Remove from the directory*
  hides the league from the directory (its share link still works for people who have it).
- **Rate limits**: sign-in codes (6 per 10 min), invitations, join requests, reports, directory search and demo starts.

## Database changes in 2.0

League files (`careers/*.f1career`), schema 18:

- New tables: `member_notify` (notification choices per member), `deliveries` (delivery log and dedupe keys),
  `seat_flags`, `weekend_targets`, `gate_bypasses`; created on first use: `announcements`, `team_goal_choices`.
- New columns: `events.press_required`, `notifications.category`, `notifications.username`,
  `join_requests.notify_preset`, `invitations.driver_id`.
- New meta keys: `visibility` and league profile fields, `difficulty_sprints`, `team_goal_choice`, `rollover_default`.

Shared `accounts.db` (created on first use): `user_sessions`, `user_leagues`, `rate_hits`, `whats_new_seen`,
`league_reports`, `league_creations`; new `users` columns `email_paused`, `is_demo`, `totp_secret`, `totp_enabled`.

## Rollback plan

Tested: a league upgraded by 2.0 and then opened by 1.20 works, and opening it again in 2.0 kept every result,
member, notification choice and team goal unchanged.

1. **Code only (normal case).** Redeploy the 1.20 commit (`037d0eb`) on the Render branch. 1.20 ignores the new
   tables and columns, so leagues keep working; 2.0-only features (notification choices, announcements, team goals,
   two-step sign-in, device list) are simply unused. Note: while on 1.20, email preferences go back to the old
   account-wide behaviour. Redeploying 2.0 later picks everything up again.
2. **Data (only if a league's data is wrong).** In that league's Backups page, restore the
   `before-v18-upgrade` backup (or any later one). A restore always backs up the current state first, so it can be
   undone. On Render the files are in `/data/backups`; locally in `%LOCALAPPDATA%\F1UniverseTracker\backups`.
3. **Two-step sign-in during a rollback.** 1.20 doesn't ask for codes, so accounts with two-step sign-in can log in
   with their password alone until 2.0 is back.

## Known limitations

- The league list reads every league file; very large sites will notice.
- Rounds can be Postponed but not Cancelled (remove a cancelled round from the calendar).
- Calendars export to .ics but can't be imported.
- Two-step setup shows a key and an authenticator link, not a QR code.
- No league logo upload yet (accent colour only).
- Scheduled announcements go out when the league is next opened, not at the exact minute.
