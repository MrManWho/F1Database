# Changelog

Every version of Paddock Legacy, newest first. The same list is in the app under
**account menu → What's new**.

## 2.1.3 · Fixes, a role audit and a fresh start for logins
_Released September 24, 2026_
> Race Master buttons no longer show in a driver's view, choices you have to make now come first, weekend
> targets can be reset on any round, every page and action was checked against each role, and all logins start
> again from scratch.

### Highlights
- **Choices come first.** If your team's goal needs choosing (at the start of a season, or reopened mid-season), you choose it before anything else. Updated targets are shown to you to agree to first.
- **Reset weekend targets on any round** (Race Master), from that round's page.
- **Every page and action checked for every role**, with an automatic check that fails if a new page is ever left open to the wrong people.
- **All logins erased again.** Everyone signs up fresh; nothing carries over from old usernames.

### Fixed
- **Race Master buttons in a driver's view**: in Driver or Spectator preview, Race Master tools (reopen or re-push a team goal, re-issue goals, announcements, dismissal decisions) were still shown. They now follow the view you've chosen. The server always checked the real role, so a real driver could never use them.

### Added
- **Must choose first**: while your team's goal choice is open and not made, every page takes you to Team goals until you choose; then you're back on the Control Room. The Race Master and players without a login are never held up.
- **Re-pushed team goal targets** are shown to each driver of that team (before and after) to agree to before they carry on.
- **Weekend targets per round** (Race Master, on the round page): re-issue one driver's or every target before the race, or remove a target on any round. Removing one on a completed round undoes its effect on the team relationship, and each driver affected sees a change notice. A removed target stays removed (it isn't handed out again or brought back by a results correction).
- **Permission audit**: every league page and action declares who may use it (Race Master, results entry or any member), and an automated test tries every one as a driver, a member without a driver, a Scorekeeper and a Spectator.

### Changed
- **Logins reset again (once, on the first start of 2.1.3)**: every login and every reserved username is removed, and each league's links to those logins (members, pending invitations and join requests, notification choices) are cleared so nobody can sign up with an old name and walk into a league. Drivers, results, seasons, contracts and settings are untouched. Every league and the accounts file are backed up first. The site owner is Race Master of every league and re-links people to their drivers on Members & roles.
- **Everyone sees the changelog**: new accounts get the current version's What's New to agree to as well.

### Tested
- 294 automated tests, including the view-mode fix, choices that must be made first, per-round target reset (effects undone, not re-issued, notices), the full role audit (every league route as four roles), and the reset leaving drivers, results, seasons, contracts and teams exactly as they were.

## 2.1.2 · One site owner, and everyone signs up themselves
_Released September 24, 2026_
> Accounts now work like a normal website: one owner account, made with the host's setup code, and everyone else
> creates their own. There's no list of accounts anywhere. All logins were reset once; no league was touched.

### Highlights
- **Every login was reset once.** Leagues, drivers, results and memberships are exactly as they were. Sign up again with your old username (and the same email) to get your leagues straight back.
- **The site owner** is made on first start with the setup code from the host's settings, and is the only one who can help with a lost account.
- **No more list of accounts.** The owner looks up one account by exact username or email; league pages ask for a username instead of listing everyone.

### Changed
- **Accounts reset (once, on the first start of 2.1.2)**: every login, signed-in device, pending sign-up, password-reset link and account preference is removed. A copy of the accounts file is saved in the backups folder first. League files are not opened or changed; site settings (email, sign-ups, league creation) are kept.
- **Old usernames are reserved**: nobody else can sign up with a name that's still a member of a league. The person who had it reclaims it by signing up with the same email (verified by a code), and their memberships come straight back. The owner can release a reserved name. Members & roles marks reserved members as "Not signed up yet".
- **Site owner**: created on first start with `F1_TRACKER_SETUP_CODE` from the host's environment settings (required on a hosted site, so nobody else can claim it). The owner may take back their old username at setup.
- **Sign-up**: always open to everyone (unless the owner turns it off). With email set up it confirms your address with a code; without it, the account is made straight away.
- **Account recovery** (owner only) replaces the list of logins: find one account by exact username or email, then set a new password (signs them out everywhere), change their email, turn off two-step sign-in, sign them out everywhere, or delete the login (their leagues stay; the name is reserved for them).
- **No account lists**: "Add a login", "All logins" and changing someone's site role are gone. Members & roles, the new-league form and invitations ask for a username.

### Tested
- 287 automated tests, including the reset leaving league files byte-for-byte identical, running only once, owner setup needing the code on a hosted site, reclaiming a name only with the same verified email, account recovery finding exact matches only, and no page listing accounts. A copy of real-shaped data was reset the way the server does it: 2 logins removed, both league files identical, backup written.

## 2.1.1 · Predictions fix
_Released September 24, 2026_

### Fixed
- **Predictions**: picks can be made straight from the Control Room and the Predictions page (not only the round page). A race time saved without a time zone by an older version could break the check that closes picks; it no longer does. When picks are closed, the page says why.

## 2.1 · Fixes from your list, team talks and final warnings
_Released September 24, 2026_
> Fixes and features from the post-2.0 feedback. You'll now be asked to agree to each update, and to any change
> that affects your own driver's numbers.

### Highlights
- **Agree to updates.** This screen now needs a tick before you carry on. If an update or a Race Master action changes your driver's numbers, you'll see what changed, why and by how much, and agree to it too.
- **Smarter AI difficulty.** No more "3 rounds, then 1 point". It learns from every round on the 0–110 scale, moves more when everyone is struggling (or flying) and only a little when results are mixed.
- **Teams listen.** What you write to a team now counts, and you can ask for an interview. A good pitch can win over a team on the fence, but not a team far out of reach.
- **Final warnings.** A team can put a struggling driver on a one-race ultimatum. Miss it and the Race Master decides whether they're dropped mid-season.
- **Team orders really off.** With team orders off, every order is gone, including old ones, and any effect they had is undone.
- **Your own pages.** Contracts & offers, Press and My progression are real pages, and every member has My settings in each league.

### Added
- **Change notices**: points, championship position, Reputation, Form, Driver Value or team relationship changed by an update or an admin action? The driver sees before/after and why, and ticks "I agree" before using the league. Race Masters see who agreed.
- **Team talks**: messages to teams are read for commitment, development, results, teamwork, respect and your record, and for arrogance, blame and shouting (negation understood). Each team has its own taste. At most ±3 interest from a message; a well-received message keeps a team negotiating longer. Nothing is sent to any AI service.
- **Interviews** (Contracts & offers): four questions and a goal you set with the team, checked against your last season. Uses one approach; up to ±5 interest.
- **Final warnings and mid-season dismissals** (League settings → Mid-season dismissals, on): after 4+ rounds at "Seat at risk", a one-race target; met, void (DNF/DNS) or missed. The Race Master confirms or overrules (with a note) on Grid & contracts. A dropped driver keeps all results and Reputation and shows as "Released mid-season".
- **Race Master goal controls**: re-push a team goal's targets, reset a team goal so they choose again (even mid-season), re-issue season goals for one driver or everyone, and re-issue the next weekend target.
- **My settings** in every league for every role: your role and driver, notifications, change notices, pin/hide in your list, account links and leaving the league.
- **Contracts & offers**, **Press** (open questions plus everything you've said) and **My progression** as their own pages.

### Changed
- **AI difficulty recommendation**: every tracked round counts at any level, recent rounds weigh most, each player driver is judged on their own; agreement moves it further, mixed results move it a little toward the struggling player, small steps while evidence is thin, never more than 5 at once. Recorded difficulties are unchanged.
- **Team orders Off** now removes all orders (past ones too), their messages, headlines and alerts, and undoes penalties/credits from orders judged while On. Leagues where they're already off are cleaned up the first time they're opened.
- **What's New** can't be skipped: no "Later" or "Don't show again", Escape doesn't close it.
- **Help** rewritten and regrouped (Getting started, Race weekends, Your driver, Contracts and your team, League extras, Admin and account) with the same page names as the menu everywhere.

### Fixed
- The league list showed rounds from every season (e.g. "24/48" after a rollover); it now counts the current season.
- Rounds further ahead no longer say "ready to start" because an earlier round's press questions were answered.
- "Contracts & offers", "Press" and "Progression" in the menu opened other pages.
- View-mode descriptions no longer describe a role with its own name.
- Old page names ("Players & Logins", "Team Standing", "Paddock Admin", "League Library", "League Settings") replaced with the names in the menu.

### Preserved
- Results, standings, contracts, pledges, Reputation and settings are unchanged, except the team-order effects removed where orders are off (each affected driver gets a change notice).
- No database format change: new tables (change notices, ultimatums) are added when first needed.

### Tested
- 279 automated tests, including change notices (explicit changes, formula changes, stale numbers never blamed on an update), removing team orders (advisory orders undo nothing), future-round gates, the agreement dialog in a real browser, team talks (themes, negation, a good pitch tips a team on the edge but not a hopeless case), interviews, final warnings (met, void, missed, dismissed, overruled), goal controls and My settings. Accessibility scan: 0 issues on the new pages.

## 2.0 · Paddock Legacy 2.0
_Released September 24, 2026_
> A new interface, notifications that stay in their own league, a safer season rollover and admin tools, and a
> lot of polish for phones, keyboards and screen readers. Every league, result, contract and setting carries over unchanged.

### Highlights
- **A new interface.** Grouped sidebar, a league switcher and season picker in the top bar, search (Ctrl+K), a bottom bar on phones and clearer pages throughout.
- **Notifications per league.** Choose email and phone alerts separately in every league, or mute one. Nothing you choose in one league affects another, and every email names its league.
- **View as another role.** Race Masters and Scorekeepers can preview the league as a Scorekeeper, Driver or Spectator without losing their own permissions.
- **Getting started.** A welcome page, a step-by-step league wizard with presets, a try-it demo league and this What's New screen.
- **Safer season rollover.** A review of every player driver's seat and contract before the new season starts, a backup first, and a repair tool for seat problems.
- **Works better everywhere.** Phone layouts, keyboard navigation, screen-reader labels and contrast checked against WCAG 2.2 AA on every main page.
- **Safer admin tools.** Backups page, typed confirmations, rate limits, signed-in devices, optional two-step sign-in and a data export.

### Added
- **Per-league notification settings** (Notifications in each league): quick presets (Everything, Important only, In-app only), email and phone alert per category, mute. A delivery log for Race Masters shows what was sent, when and to how many (never to whom). Dedupe keys stop a retry from sending twice, and loop protection holds a league that suddenly sends too much. Every email has a one-click, league-only unsubscribe link.
- **View modes**: Race Master, Scorekeeper, Driver and Spectator preview. The mode only changes the display; the server always checks the real role.
- **League switcher, pinned and reordered leagues, hidden leagues** (per account), a season picker, and a **command palette** (Ctrl+K / the search button) that searches only the current league.
- **Onboarding**: a welcome page for people who aren't signed in, an 8-step new-league wizard (basics, calendar, scoring preset, players, roles, notifications, visibility, review) with the old quick form still available, and a **demo league** that is private to each visitor, sends nothing and is cleaned up automatically.
- **League visibility**: Private (default), Public (share link) or Listed (also in the new public directory), with a league profile (description, region, platform, schedule, rules, links, accent colour). Public pages for home, calendar (with .ics), standings, rounds, drivers, teams, records, news and incidents, showing submitted rounds only. Anyone can report a listed league; site admins can remove it from the directory.
- **Season rollover review**: every player driver's seat and contract state (confirmed, provisional, temporary, no contract, expired, seated elsewhere, unseated) with a decision for each ending contract (renew, keep provisionally, release), a backup before anything changes, and a seat repair tool.
- **Grid & contracts** lists every contract as current, upcoming, expiring, expired, historical or seated elsewhere.
- **Selectable team goals** (optional, League settings): each team with a player driver picks Safe (+1 / 0 Reputation), Competitive (+3 / −1) or Ambitious (+6 / −3) at the start of the season. Targets come from car strength, last season's Constructors' position, the lineup, calendar length and Sprint weekends, and each option explains itself. Met = target position or target points; teams level on points count as the lower place; a target that would be automatic (last place) or can't move (P1) is judged on points only. Locked after round 1 and settled once when the next season starts.
- **Announcements**: pinned, aimed at roles, scheduled, with an expiry; a live count of who will see it, get a phone alert and get an email; email only to members who want Announcements email from that league.
- **Statistics page**: points progression, finish distribution, qualifying vs race, Sprint results, teammate head-to-heads, reliability and player drivers season over season, with a player-drivers-only filter. Submitted rounds only.
- **"Waiting for you"** on the Control Room: each person's own to-dos (offers, pledge, press, weekend target, team goal, join requests, incidents, seat problems, results pending).
- **Calendar**: month view, warnings for clashes and out-of-order dates, a subscribable .ics file, and locked round numbers for rounds with results (a Race Master can use historical correction mode, which is logged).
- **Results entry**: session tabs (Qualifying, Sprint, Race), driver search, copy the order from another session, and undo (Alt+Z).
- **Backups & data page** with an integrity check, safety backups kept separately from the scheduled ones, and a **standings CSV** export.
- **Account**: signed-in devices (end one or all others), optional **two-step sign-in** with any authenticator app (site admins can reset it), **download my data**, **delete my account**, **leave a league** and **hand a league over**. Privacy and Terms pages.
- **Import preview**: a .f1career file is checked and summarised before anything is added, and always becomes a new league.

### Improved
- **League settings** are grouped into sections with a search box, each saying whether it affects this league or the whole site.
- **Accessibility**: skip link, landmarks, labelled controls, visible focus, larger touch targets on key controls, reduced-motion support and sufficient contrast for every league accent colour (axe WCAG 2.2 AA: 0 violations on every main page).
- **Mobile**: bottom navigation, a drawer sidebar, tables that scroll inside their card and forms that fit a 360 px screen.
- **Offline and unsaved work**: an offline banner, and a warning before leaving a page with unsaved results.
- **Help** gains sections for statuses, scoring, statistics, rivalries, view modes, contracts, team goals, announcements, visibility, backups, account security and your data; every search link now opens a real section.
- **Activity Log** records the new actions (visibility, announcements, team goals, handovers, leaving, historical corrections) as sentences.
- **What's New** shows once to each account that existed before an update; accounts created afterwards get the welcome and onboarding instead.
- Flask 3.1.3 (a dependency audit found a published advisory for 3.1.2).

### Fixed
- **League emails no longer cross leagues.** Before 2.0, choosing results emails applied to every league you were in; a Test league could email people about another league's results. Choices are now stored per league.
- **Site admins who aren't members of a league** no longer get its alerts. Join requests now go to that league's Race Masters only.
- **Season rollover** no longer leaves a player driver with an expired contract in a seat without asking, or with a seat and a contract at different teams.
- **Completed rounds** can no longer be renumbered by accident when the calendar is saved.
- **Search palette**: pressing Enter straight after typing no longer opens a result from the previous search.
- The Activity Log no longer fails on a handover submitted from the form.

### Security
- Every league route re-checked by automated tests: an outsider can open or change nothing in another league, Spectators can make no changes, and Scorekeepers can't reach Race Master tools, in the pages and the API.
- Rate limits on sign-in codes, invitations (20 an hour), join requests (5 an hour), reports, directory search and demo starts.
- Downloaded backups and JSON exports leave out the Discord webhook and the public-link key. The Activity Log and exports never contain passwords, hashes, sessions, codes, OCR text or webhook URLs.
- Changing your password signs out your other devices.

### Migration notes
- Save files move from schema 17 to 18: new tables for notification preferences, deliveries, seat flags, weekend targets and gate bypasses, and new columns on events, notifications, join requests and invitations. Nothing existing is changed or removed. Every league is backed up automatically before it's upgraded.
- **Existing members keep the results emails they had**: each membership starts with the old account-wide choice, now applied to that league only. Everything else uses the Important-only preset.
- The **AI difficulty recommendation still counts Sprint points**, as before. A league can now turn that off ("Count Sprint points", League settings) so only the Grand Prix counts. Recorded difficulties and past recommendations aren't changed.
- **Team goals, announcements and statistics** don't change any stored result or rating. Team goals are off until a league turns them on.
- New leagues are private. Creating leagues is limited to site admins unless the site setting allows everyone. The person who creates a league becomes its Race Master.

### Known limitations
- The league list reads every league file when it loads; very large sites (hundreds of leagues) will notice.
- A race can be Postponed but not Cancelled; a cancelled round has to be removed from the calendar.
- Calendars can be exported as .ics but not imported.
- Two-step sign-in shows a setup key and an authenticator link, not a QR code.
- League logos can't be uploaded yet (an accent colour is used instead).
- Scheduled announcements go out the next time anyone opens the league after their time, not at the exact minute.

### Preserved
- Every account, league, role, season, result, contract, driver, team, record, setting, backup, activity entry, transfer, pledge and relationship. Scoring, Sprint scoring, Form, Reputation, Driver Value, market tiers, contracts, pledges and relationships are calculated exactly as before.
- Manual entry for every automated step, and the free in-browser screenshot importer (images never leave the browser).
- Existing links, save files (.f1career), backups and installed apps keep working.

### Tested
- 261 automated tests, including cross-league isolation for every league route, rollover edge cases, notification scoping and dedupe, public pages never showing drafts, two-step sign-in, device sign-out, account export and deletion, rate limits, redaction, import preview, team goals, announcements and statistics, plus in-browser tests for the shell, palette and offline recovery.
- A three-season league built with 1.20 (1,584 results) was upgraded on a copy: standings, results, records, members, events and players came out identical, and a pre-upgrade backup was written.
- axe-core accessibility scan (WCAG 2.2 AA) on every main page, and screenshots at phone, tablet and desktop sizes.

### Action needed
- Open **Notifications** in each league you're in and check the choices; mute any test league you don't want to hear from.
- Race Masters: review **League settings → Visibility** (leagues start private) and consider turning on **two-step sign-in** in your account.

## 1.20 · Weekend targets, teammate battles and round gates
### New
- **Weekend targets.** Before each race every player driver gets one realistic target from their team (e.g. "Finish P8 or better", "Score points", "Beat both Haas cars", now and then "Finish ahead of your teammate"), pitched from the car's pace, recent form and contract role, so a backmarker is never asked for a podium. Accept it with **Got it** on the Control Room. It's judged from the results: hit +2 team standing, missed -1.5, void if you didn't take part. The Race Master can rule a DNF/DSQ "not the driver's fault". Corrections re-judge it. Three, five, eight or ten in a row makes the news. Switch it off in League Settings.
- **Teammate battle.** A season-long head-to-head with whoever shares your car: qualifying, race (a finisher beats a DNF; skipped if neither finished) and the points gap. It's on driver pages, team pages and the race page after each round, with one battle per teammate if someone changes seat mid-season. Human-vs-human battles are marked 👥. Headlines cover a new leader, five in a row and the season verdict. Beating your teammate is never punished.
- **Round gates.** Results for the next round can't go in until every player with a login has answered both post-race press questions and accepted their weekend target. Players without a login never hold a round up. A banner on every page tells you what's waiting on you, and the round page shows the checklist to everyone. Scorekeepers can't get past it (they can send one reminder per round). The Race Master can open a round early with a note, which is kept on the round and in the Activity Log. Anything still open can be done later and still counts. The server enforces it, not just the page.

### Changed
- **Team orders are now a League Settings choice** and are **off** by default: Off (none issued; any waiting order is cancelled with no penalty), Advisory (shown, no effect, no headlines) or On (as before). Past orders stay in history.
- With press gates on, unanswered press questions no longer lapse when the next race is completed.

### Preserved
- No results, contracts, relationships or past orders were changed. Rounds completed before this version never become a requirement, and a round that already has results is never gated, so corrections are never blocked.

### Tested
- Team-order modes; target planning for fast and slow cars; judging including void, excused DNF and corrections; streak headlines; teammate battle counts with DNFs and a mid-season seat change; linked vs unlinked players; Scorekeepers blocked in the page and the API; the Race Master's bypass needs a note and is logged; late answers after a bypass still count; Spectators see the checklist read-only; migration keeps every result.

## 1.19 · Fixes, safer admin and free screenshot import
### Fixed
- **AI difficulty on a completed round.** A completed round with a tracked difficulty now counts toward the recommendation on its own page (it used to say "Track the AI difficulty on a completed round to establish a baseline"). The message now reads like "1 of 3 usable rounds at AI 80. Waiting for a consistent pattern (2 more needed)", and says when a tracked round didn't count because no player driver finished. "Don't track this round" is remembered explicitly. The recommendation formula is unchanged and never moves more than one step.
- **Completed-round button.** A completed round no longer shows "Mark weekend complete". Race Masters see "Weekend complete", which becomes "Save corrections" after an edit (with a confirmation explaining what's recalculated); Scorekeepers see the locked state.
- **Players & Logins** no longer has its own join switch; it shows the current setting and links to League Settings, the one place to change it.

### Improved
- **New name: Paddock Legacy.** The app, installed-app name, emails, push and Discord notifications and share cards now say Paddock Legacy, with a new logo and app icons. Data folders, backup files (.f1career) and existing installs are unchanged, so nothing needs moving.
- **Drivers page: Everyone else.** Retired drivers, free agents and reserves who aren't in this season's standings are listed with their career stats (seasons, points, wins, podiums, poles, starts, titles, Reputation) and a link to their full profile. Retired drivers get a Retired badge on their profile.
- **Move results to another driver** (Paddock Admin). If the wrong driver was in a seat, move their results for chosen rounds of the current season onto the right driver, and optionally swap their seats. Shows a preview first, needs the right driver's name typed, makes a backup, and keeps constructors' points unchanged.
- **Screenshot import is free and private.** It now runs in your browser with a self-hosted OCR engine (Tesseract.js): no API key, no account, no per-screenshot cost, and the image is never uploaded. Crop, straighten, contrast and brightness tools, several screenshots per session (overlaps merged, disagreements flagged), fuzzy name matching against this round's drivers only (ambiguous names are never guessed), DNF/DNS/DSQ detection, session detection that won't put Sprint results into the Race columns, an editable preview with confidence levels, a comparison before replacing anything, and an explicit "Apply imported results" that only fills the table. The paid Anthropic importer and its API key setting are removed (a saved key is deleted).
- **Final review before completing a weekend** now also blocks gaps in positions and a missing AI difficulty (enter it or choose "Don't track this round"), highlights player drivers with missing results, and says the round will lock for Scorekeepers.
- **Race-time states:** Not scheduled, Scheduled, Starts in…, Starting soon, In progress, Results pending, Completed, and Postponed (Race Master). Times show the league's time-zone abbreviation.
- **Season card:** completed and remaining rounds, current round, Sprint weekends done and left, next event and projected finish date.
- **Activity Log** entries read as sentences ("David scheduled Round 2 — Chinese GP (2026) for Wed, Sep 23 at 11:30 AM EDT", "changed joining from Join requests enabled to Invite only", "changed Chat's league role from Member to Scorekeeper") with links, and never show private values such as webhook URLs. Older entries show names instead of ids.
- **Password forms** (change, create a login, reset, sign-up, first-time setup): confirm field, show/hide, Caps Lock warning, clear rules, matching checked in the browser and on the server, and no double submission.
- **Race Master sidebar tools** are a separate, collapsible, scrollable section that remembers whether you left it open.
- **Confirmations** for high-impact actions explain what changes, whether history is affected, whether a backup is made and whether it can be undone. Deleting a driver's race results needs their name typed. Paddock Admin uses one delete dialog instead of one per driver.
- **Autosave states:** Saving…, Saved, Offline — changes stored on this device, Couldn't save — retry, Restored unsaved changes, Conflict detected.

### Preserved
- Scoring, Sprint scoring, DNF/DNS/DSQ rules, Form, Reputation, Driver Value, market tiers, car-adjusted ratings, contracts, pledges, relationships, the transfer market and the difficulty formula are unchanged.
- Completed rounds stay locked for Scorekeepers; only a Race Master can correct or reopen them.
- Every human driver keeps their own colour and Player badge, however many there are. Provisional awards, empty states and early-season trends work as before.

### Tested
- 165 automated tests, including real in-browser OCR on generated screenshots, OCR failing to load, and a check that no screenshot or request leaves the page.
- A three-season league built with v1.18 was upgraded on a copy: standings, Form, Reputation, market tiers, constructors, all 1,584 results, records, roles and the difficulty recommendation came out identical.

## 1.18 · Usability and data safety
- **Submitted rounds stay locked.** Scorekeepers edit only the open round; once it's submitted only the Race Master can correct it, or **reopen** it for a Scorekeeper. A reopened round doesn't repeat its headlines, team reactions or emails when it's submitted again.
- **Review before submitting.** Submitting now opens a review: pole, winners, podium, DNFs/DNSs/DSQs, Fastest Lap, Driver of the Day, player results and AI difficulty. **Blocking errors** (missing results, half-entered qualifying, DNS with a position, unsaved edits) must be fixed; **warnings** (no Fastest Lap, AI difficulty not tracked) can be accepted. The server enforces the blocking checks too. After submitting you land on the race summary.
- **Autosave that survives a bad connection.** Edits are kept in your browser until the server has them. You'll see Saving, Saved, "Offline — changes waiting to save" or Save failed. Saving resumes when you're back online, unsent edits come back if you return to the page, and you're warned before leaving with edits unsaved.
- **No silent overwrites.** If someone saved the same round while your edits were waiting, you see both values and choose which to keep. If the round was submitted in the meantime, a Scorekeeper's queued edits are stopped and they're told to contact the Race Master.
- **Race-time states:** "Starts in 2h 15m", then "Race window open", then "Scheduled time passed · awaiting results", then "Completed". The window length is in League Settings. Nothing is completed automatically.
- **Control Room season card** now shows completion %, rounds and Sprint weekends done, the WDC and WCC leaders, average AI difficulty and the next milestone.
- **Joining a league:** "Join requests enabled", "Invite only" (invite someone from Players & Logins; they accept from their League Library) or "Closed to new members". Leagues that were open to join keep taking requests; closed ones become invite only. Before joining, people only see a league's name, season and join status.
- **Accounts:** race-result emails can only be switched on with a valid email address (existing accounts without one have it switched off). Changing your password now asks you to type the new one twice, with show/hide buttons and a Caps Lock warning.
- **Help** has search, grouped topics with a sticky list (a dropdown on phones), highlighting of the section you're reading and "Back to top" links. New topics: Scorekeeper, Race Master, assigned drivers, joining, racecraft, entering results, Sprint weekends, race times, notifications, comments, predictions, public results and Discord.
- **Tidier pages:** driver-profile stats sit in balanced rows, the Incidents page explains what to do for your role when there's nothing reported, and AI driver names on the grid, records and reviews are no longer red (players keep their own colour).

## 1.17 · Fair pledges
- **Pledges are fair in every car.** A pledge is now an average finishing position, measured against where your car should finish. Each pledge closes the same share of the gap to P1 (Steady 0%, Solid 12%, Strong 25%, Breakout 40%). Before, the fastest car kept every pledge just by driving normally, and the slowest car couldn't keep anything above Steady however well it drove, because Reputation barely moves without points.
- **DNFs and bad luck.** A DNF or DSQ counts as last place, and from round 5 your single worst weekend is dropped.
- **Keeping your pledge pays.** At the end of the season, a kept pledge adds Reputation to your start for next season: +0.5 Steady, +1 Solid, +1.75 Strong, +2.5 Breakout.
- **Team Standing** shows your average finish against your pledge and the car's expected finish. Form and Reputation are still shown for reference.
- Pledges in progress keep their level; their targets are worked out again the new way, and your team tells you what that means.

## 1.16 · Polish, clearer roles and easier reading
- **One place for roles.** Each league member has one role: Race Master, Scorekeeper, Member or Spectator, set on the league's Players & Logins page. A driver is assigned separately, so a Race Master or Scorekeeper can also drive. The old account-wide Scorekeeper switch is gone; anyone who had it keeps Scorekeeper in every league they belong to. A league always keeps at least one Race Master.
- **Spectator view.** Spectators see plain text instead of greyed-out forms (results, calendar, grid, notes), with a "View only" badge. The server refuses any change from them.
- **Times in your league's time zone.** Every date reads the same way, e.g. "Wed, Sep 23 · 11:30 AM", "Lights out Wed, Sep 23 at 11:30 AM", "Starts in 9h 56m" and "3 hours ago". Set the zone in League Settings.
- **Player colours.** Every human driver gets a persistent accent colour, separate from the team colour, used in tables, charts, the grid, profiles and the rivalry page. Player rows are tinted with a Player badge.
- **Change since last round.** My Garage and driver profiles show how Form, Reputation, Driver Value, Car-Adjusted, points and WDC position moved since the previous round, with sparklines after three rounds. No formulas changed.
- **Post-race summary.** Every completed round has a summary: podium, pole, sprint winner, each player's weekend, Form and Reputation changes, championship movement, the rivalry and the next AI difficulty.
- **Better charts.** Point markers, player lines thicker and in their own colour, AI lines dimmed until you hover, tooltips with round, position and points, and legend buttons to hide lines.
- **Constructors.** Cards line up evenly and open a fuller team profile: current drivers, car rating by season, season-by-season results, everyone who raced for the team, and transfer news.
- **Paddock News story cards** with a category, round badge, driver and team, and a link to the full results.
- **Driver Market overview:** market status, what happens next, player contracts, teams showing interest, available seats, recent signings and paddock whispers. Read-only; it never changes the grid.
- **Notifications:** icons, New / read styling, **Mark all as read** and **Clear read** (hides them for you; nothing is deleted). Opening the panel no longer marks everything read.
- **Clearer early-season pages.** Unfinished-season awards are shown as Current projections (Provisional); records with nothing yet say so; one-round Form/Reputation shows the current value and change instead of a one-point chart; a 0–0 rivalry shows a neutral Tied bar.
- **Easier results entry.** Grouped column headings, filters (players, incomplete, points, DNFs), clear a driver or a whole session (with confirmation), Saving / Saved / Error states, a last-edited marker and keyboard shortcuts (press ?).
- **Tables:** headers stay visible, driver names stay put while scrolling sideways, numbers line up, abbreviations have tooltips, and clicking a driver row opens their profile.
- **Polish:** a new Universe Tracker logo, brighter labels, keyboard focus outlines, gentle hover states, loading placeholders for charts, Comfortable/Compact density, and the season shown in the collapsed menu.

## 1.15 · Life inside the team
- **Everyone has a pledge.** Every seated driver must have a growth pledge. If yours is missing (a contract from before pledges, or a seat given by hand), the app asks you to choose one before anything else. Pledges are locked for the season.
- **Race Master: ask for a new pledge.** On Team Standings there's a button to ask one driver, or everyone, to choose again. They'll be asked next time they open the league.
- **Targets re-set after round 3.** Once three races are done, your targets are re-based on how fast the car really is in your league, using the AI drivers' points. The team tells you what changed.
- **Season goals.** Each team sets goals pitched at its car: points in a number of races, a championship position, and (for No. 1 and Equal Status drivers) beating your teammate. They count toward the relationship.
- **Press pen.** After each race you get two questions based on how it went. Answers nudge your relationship, and some make headlines. It's optional, and questions close when the next race is completed.
- **Team orders.** A No. 2 driver can be told to let their teammate through at the next race. Finishing ahead of them means you ignored it: that costs relationship points and makes the news.
- **Incident reports.** Report an incident from any race weekend. The Race Master rules on it (no further action, reprimand, warning or penalty), and the ruling goes in the news and in the rivalry between the drivers.
- **Driver Value breakdown** in My Garage: what your number is made of, and how far you are from the next team up.
- **How it works** page explaining Form, Reputation, Driver Value, car strength, pledges, relationships, goals, team orders, the press pen and incidents, with ⓘ links from the stats.
- **Discord (optional).** Paste a channel webhook in League Settings to post race results and paddock headlines. It's off unless you set it up, and there's a test button.
- **Result cards.** A shareable picture of the podium and your weekend, from any completed race.
- **Restore backups in the app.** Roll a league back to any automatic backup, or restore from a downloaded file. The current state is backed up first, so a restore can be undone.
- **Fixes:**
  - Two backups made in the same second overwrote each other. This could lose the "before restore" copy.

## 1.14 · Contracts about growth, team relationships
- **No more salaries.** Contracts are now about **seat status**, **length** and a **growth pledge**: how much you promise to improve. The four pledges are Steady, Solid, Strong and Breakout.
- **Pledges are fair at every team.** Targets are measured against what your car should manage. A backmarker isn't expected to win; a Breakout season in a slow car means clearly beating it.
- **Negotiating with pledges.** Better status and longer deals need a bigger pledge. Promise more than a team needs and you can win an extra year, or (for experienced drivers) one step more status than they first offered.
- **Contract length matters.** While your deal covers next season, teams won't talk to you and you can't approach them. The exception is if your team releases you.
- **Team relationships.** As results come in, your team rates you out of 100: Delighted, Happy, Concerned, Unhappy or Seat at risk. Fall behind and they'll have a quiet word, then give a formal warning, then question your future. Turn it around and they say so.
- **Being dropped.** A driver still at risk when Silly Season opens, or at season end, is released. The team won't renew, and without a new deal you start next season as a reserve.
- **Renewals.** A team that's happy with you always offers a renewal when your contract is up.
- **New Team Standing page** (My career): your relationship, targets vs actual Form and Reputation, teammate head-to-head, what the team has said, and how eager every team in the paddock is.
- **Race Master is an admin, not a driver,** unless they're linked to one. Without a driver, their menu shows **Player Garages** and **Team Standings** under Race Master instead of "My career". The sidebar badge shows each person's real role in that league: Race Master, Driver, Scorekeeper or Spectator.
- **Clearer Players & Logins.** Each player driver has a login and a **Can enter results** tick. Everyone else gets one choice: Not in this league, Spectator (view only) or Scorekeeper (enters results).
- **What's new** page (this list) in the account menu.
- **Fixes found by a full-season simulation:**
  - The public results page crashed once any driver had no results.
  - Top teams wouldn't renew a driver they were delighted with.
  - Contract length had no effect on the market.
  - The "Approach a team" form showed the custom-terms fields even when you picked "Ask about a seat".
  - Older wording (salary, Race Steward, fixed player names) is gone from pages and help text.

## 1.13 · Race night, chat, predictions, profiles, installable app
- **League Settings** with switches for extras, also offered when a league is created: race-night check-in, comments & reactions, predictions game and a public results page.
- **Race night:** race times with a live countdown in each viewer's time zone, check-ins, and a *Race story* after the race (podium, movers, pole, fastest lap, DNFs, fans' Driver of the Day vote).
- **Comments and emoji reactions** on race weekends and news.
- **Predictions game:** pole, winner, fastest lap and top player driver. Picks lock at race time, and there's a season table.
- **Driver profiles:** photo, car number, nationality, helmet colour, bio, trophy cabinet and contract history.
- **New awards and records:** Iron man, Qualifying ace, Drive of the season, Fans' choice. The Hall of Records adds a champions list and a record book with streaks and comebacks.
- **Activity Log** for the Race Master.
- **Install it as an app,** with phone and desktop alerts.
- **Light theme.**

## 1.12 · Choose your role when joining
- Join requests include a role: Driver, Driver + Scorekeeper, Scorekeeper only or Spectator.
- The Race Master can accept as asked, accept with a different role, or decline.
- Scorekeeper can be given per league.
- The dashboard says "Last race" / "Last 3 races" correctly.

## 1.11 · Email confirmation at sign-up
- New accounts confirm a 6-digit code sent by email. It works for 15 minutes; you can resend once a minute, and get 5 tries.

## 1.10 · Scorekeeper, cleaner navigation, deleting drivers
- **Race Steward became Scorekeeper.** A Scorekeeper can only enter results, and a submitted weekend is locked for them.
- **Grouped menu with icons** that collapses to a rail.
- **New Control Room:** season progress strip, "Your driver" card, and position-change arrows.
- New drivers start at 45 Reputation.
- Drivers can be deleted permanently.

## 1.9 · Open leagues for any number of players
- Leagues aren't tied to particular people. Add any number of player drivers, or none.
- Open leagues appear in everyone's League Library with an *Ask to join* form.
- Players & Logins: join requests, add a player driver, link logins, send offers.
- Rivalry compares any two drivers.

## 1.8 · Email and password resets
- **Email addresses** on accounts.
- **Forgot password:** a one-time reset link that works for 60 minutes.
- **Race results by email** after each completed weekend.
- The results-entry role can no longer open transfer windows or storylines.
- The Race Master can delete a whole transfer window, headlines and notifications.

## 1.7 · Racecraft and website hosting
- **Racecraft:** places gained from the grid, weighted by where you finish, now count toward Form and Reputation. The Drivers table has a **Gained** column.
- **Recalculate Reputation history** replays past seasons with the current formula.
- **Hosting on Render,** with a persistent disk, auto-deploy on every update, and a setup code for the first Race Master.

## 1.6 · Results-entry role
- A role that can enter results without seeing other players' garages or admin pages. It became *Scorekeeper* in 1.10.

## 1.5 · The big feature update
- **Accounts:** login lockout after repeated wrong passwords, and self sign-up.
- **Results:** screenshot import of classifications (with Claude), and quick tap-to-order entry that also works on phones.
- **Stats:** rivalry page and charts.
- **Paddock:** team development (car ratings that change each winter), season review awards, paddock news, the notification bell, Paddock Admin for drivers and teams, and adding/removing calendar rounds.
- **Automatic backups.**

## 1.4 · Negotiations and safe updates
- Offers became negotiations: counter-offers, a team mood and patience, final offers, and talks that can collapse.
- **Approach teams yourself** (3 per window), with trial offers and a last-chance lifeline when you run out of options.
- `update.bat`, and automatic backups before a save is upgraded.

## 1.3 · Logins, rookie offers and My Garage
- **Race Master and driver logins.** Each player sees their own garage.
- **Rookie Draft:** players start without a seat and choose between offers from backmarker teams.
- **Performance-based offers** from a Driver Value (Reputation, Form, car-adjusted results, teammate head-to-head).
- **Transfer windows:** Rookie Draft, Silly Season at half-distance, or opened by the Race Master.
- **AI difficulty recommender** that moves slowly and learns across seasons.

## 1.2 · The original tracker
- **Saves:** one save file per career with Save As, backups, JSON export and import.
- **Race entry:** Sprints, statuses, Fastest Lap and Driver of the Day.
- **Stats:** driver and constructor standings, Form, Reputation and Market Tier.
- **Grid & calendar:** Grid & Transfers, calendar editor, driver and team profiles, Hall of Records and Driver Market storylines.
