# Paddock Legacy 2.x: admin guide

This is for site admins and Race Masters. The What's New screen and Help cover everyday use.

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
- **AI difficulty**: recommendations on/off; *Count Sprint points* (on by default, as before 2.0).
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
