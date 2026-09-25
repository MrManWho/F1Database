# Changelog

Every version of Paddock Legacy, newest first: what changed for the people using it. The same list is in the app under
**account menu → What's new**. Hosting and admin notes are in the admin guide.

## 2.4.1 · A fairer AI recommendation
_Released September 25, 2026_
> The AI difficulty recommendation no longer raises the level on drivers who are finishing at the back.

### Highlights
- **Half the car, half the grid.** Each round is judged half against what your car should manage and half against the whole grid. A slow car still counts, but finishing near the back now brings the level down, so there's room for a breakout season.
- **Never up while someone is struggling.** The level holds instead of going up while any player driver is struggling or finishing near the back of the grid (about P16 or worse).

### Changed
- **Formula change (approved):** AI difficulty uses a 50/50 blend of the car-relative reading (2.4) and a whole-grid reading, and it can't go up while anyone is struggling. The one-line summary under the recommendation says how rounds are judged.
- **League setting** (League settings → Race weekends → *How each round is judged*): Blend (the default), Car only (as in 2.4) or Overall.

## 2.4 · Choose your target, reset a weekend, and a tidier league
_Released September 24, 2026_
> Weekend targets are now a choice, the Race Master can reset a round as if it never happened, each round has its own
> page with tabs, League settings is split into clear pages, and the AI recommendation judges the driver, not the car.

### Highlights
- **Choose your weekend target.** Before each race your team offers three: **Safe** (+1 / −0.5), **Standard** (+2 / −1.5) or **Stretch** (+3.5 / −2.5). Pick one and lock it in. If you don't choose by lights out, you race for the Standard one.
- **The AI recommendation judges the driver, not the car.** Finishing where your car should is now "about right" in any car. Before, a slow car made you look like you were struggling and a fast one made you look too good.
- **Each round is its own page.** A round header with its number, stage and previous/next, and three tabs: Weekend, Results, and Incidents & chat.
- **Reset a weekend** (Race Master). Puts the latest round back to Upcoming, as if it never started: results, press answers, targets, predictions and headlines are removed, and any effect on team relationships is undone. You see everything it will remove first.
- **Every player driver needs a login.** A round can't open while a player driver has no login linked, unless the Race Master marks them **No account**.

### Added
- **Team management** (Race Master, Manage menu): pledges, season goals, team goals and weekend targets for every driver in one place. Re-issue goals, ask for a new pledge, let a driver choose their target again, offer new targets, remove a target, re-push or reset a team goal. These buttons no longer sit on the pages drivers use.
- **Recalculate everything** (Race Master, League settings → Data & tools): works every stored number out again with the current formulas. It shows exactly what would change for each driver before anything is saved, and each driver affected gets a change notice.
- **Automatic recalculation after updates.** When an update changes how something is worked out, each league recalculates itself the first time it's opened, and everyone sees a short note at the top of the league.

### Changed
- **League settings is split into pages**: League, Race weekends, Career & team, Joining & roles, Privacy & sharing, Notifications, and Data & tools. The front page shows each one's current settings at a glance.
- The home page is called **Control Room** everywhere, and "team relationship" is the one name for how your team rates you.
- **Formula changes (approved):** AI difficulty compares each result with the car's expected finish and points; weekend targets use the reward and penalty of the level you chose.

### Fixed
- **A car with no AI driver** (for example two players in the same team) counted as the slowest car after three rounds. It now keeps its place from the car ratings, which also corrects weekend targets, pledges and Driver Value for that team.
- **Reputation carried between seasons**, when worked out again, now always includes the pledge and team-goal rewards.
- **Pre-race questions** no longer change after you choose your weekend target.
- **Team relationship extras add up the same every time.** Press answers, weekend targets and team orders are added together and kept within ±15. Before, the total could come out differently depending on the order things happened in. Drivers whose number moves see a change notice.

## 2.3 · Race weekends
_Released September 24, 2026_
> Every round is now a proper race weekend: the paddock opens, drivers face the press, the lights go out, and
> the chequered flag falls when the results go in. The press also has far more to ask, before and after the race.

### Highlights
- **The paddock opens an hour before the race.** It opens by itself an hour before the scheduled race time, or when a Scorekeeper or the Race Master presses *Open the paddock*. Everyone gets an alert (Race day, in your notification settings) and a banner on every page.
- **Pre-race press.** While the paddock is open each driver gets two questions picked from their situation: last result, teammate battle, weekend target, Sprint weekend, points drought, title fight, a rival close in the standings, the transfer window and more. Answers count toward your team relationship and some make headlines.
- **Lights out.** A Scorekeeper or the Race Master presses *Start the race* once everyone's ready (pre-race press, weekend target, last race's press). Only the Race Master can start with someone outstanding, with a note. The round shows **LIVE** everywhere.
- **Results only after lights out.** No results can go in for a round until its race has started. Submitting them waves the chequered flag.
- **A much bigger post-race press room.** Questions now follow what happened: wins, podiums, places gained or lost from qualifying, pole, fastest lap, Driver of the Day, good or bad Sprints, first points, points droughts, repeated retirements, close teammate battles, hitting or missing your target, the title fight.

### Added
- **Race weekend panel** on each round page: the four stages (Upcoming, Paddock open, Lights out, Chequered flag), a countdown, a "who's ready" board, the Open and Start buttons, and your pre-race press.
- **Race day alerts**: a new notification category for the paddock opening and lights out (phone alerts on, email off by default; change it in Notifications).
- **League setting: Race weekends** (on by default). Off: results can go in at any time, as before.
- Press page history says whether each answer was before or after the race.

### Changed
- **Round gates are checked at lights out** instead of when results are saved, and include the pre-race press when press is part of the gate.
- **Predictions close at lights out** (or at the scheduled race time, whichever comes first).
- **Formula (approved): pre-race press answers** nudge the team relationship like post-race answers (between −3 and +3 each), within the same overall limit on extras.
- Rounds submitted before 2.3 keep the post-race questions they already had, so nothing half-answered changes.

## 2.2.1 · Sign-up fix from a full-season test
_Released September 24, 2026_
> A full simulated season (every role, real settings) found one small sign-up problem, fixed here.

### Highlights
- **Typos no longer lock people out of signing up.** Only sign-ups that succeed count toward the limit of 5 an hour per connection.

### Fixed
- **Refused sign-ups used up the hourly limit**: a sign-up turned down for a weak password, a bad username or a taken name still counted toward the 5-an-hour limit for that connection, so a household on one Wi-Fi could be locked out by a few mistakes. Now only successful sign-ups count.

## 2.2 · Audit fixes, fairer team goals and a quicker AI recommendation
_Released September 24, 2026_
> Fixes from an outside audit (including a page loop after starting a new season), team goals that take the
> season so far into account, an AI difficulty recommendation that reacts faster and names the game's level
> bands, and account recovery that finds every account sharing an email.

### Highlights
- **No more page loop after a new season.** If you had several things to do first (agree to changes, choose a pledge, choose your team's goal), you're now taken through them one at a time, in order.
- **Team goals are harder to game.** Goals count the points your team already has, the rounds left and how you've actually been scoring, and each level asks for clearly more than the one below. Safe is never already done.
- **The AI recommendation reacts faster.** One clear round now moves it several levels (up to 8 at once) instead of creeping by 2, and it shows the level band: Beginner (1–40), Casual (41–65), Intermediate / Advanced (66–99) or Expert (100–110).
- **A one-line summary of the evidence** under each AI recommendation, e.g. "Five usable rounds (R1, R2, R3, R5, R6), latest weighted most, R4 excluded (no player finished), R7 untracked, Sprint points counted."
- **Stronger passwords for new passwords**: at least 8 characters and not a common one. Existing passwords keep working.

### Fixed
- **Redirect loop after a season rollover**: with a provisional seat, team goals on and a pledge still to choose, pages bounced between Team goals and the pledge page forever. All "do this first" steps now come from one ordered list, and the pages for those steps never send you elsewhere.
- **What's New could be closed with Escape** in some browsers (a second press closed it). It now stays open until you agree.
- **A round opened early by the Race Master** said "0 of 1 ready" and "Everyone's done their part" together. It now says "Race Master override active. Outstanding player actions can still be completed later."

### Added
- **Account recovery (site owner) finds every account** with that exact username or email. Several people can share an email, so every match is listed with its own controls.
- **Contact email** (Account → Settings) for the Privacy and Terms pages.
- **Rollover summary updates live** as you choose what happens to each ending contract, and counts provisional seats.
- **Offers explained**: Contracts & offers says how many are concrete contracts you can sign now (by status, and how many are from a top-third car), shows each team's car rank, and points to the interest board for teams that are only interested.

### Changed
- **Team goal targets (formula change)**: points target = points already scored + a projection for the rounds left. The projection blends the car's expected haul (and last season's scoring, if any) with the team's pace so far, which counts for rounds done ÷ (rounds done + 4). Competitive needs at least 3 points (or 25% of what's still to score) more than Safe, and Ambitious the same again above Competitive. Goals already chosen are unchanged; a Race Master can re-push them.
- **AI difficulty (formula change)**: a perfect weekend now suggests 25 levels of headroom (was 20), one round can say up to 15 (was 12), the "about right" band is ±0.08 (was ±0.12), recent rounds fade faster (half-life 2.5 rounds, was 4), confidence builds faster, and a step can be up to 8 (was 5). Sprint points still count by default; the recommendation now says whether they did.
- **Full career simulation preset** now turns on selectable team goals, and each preset lists its systems in the setup review.
- **Privacy and Terms** no longer carry placeholder text for hosts. They say who runs the site, how to contact them, how long things are kept and when the pages took effect.

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

### Changed
- **Logins reset again (once, on the first start of 2.1.3)**: every login and every reserved username is removed, and each league's links to those logins (members, pending invitations and join requests, notification choices) are cleared so nobody can sign up with an old name and walk into a league. Drivers, results, seasons, contracts and settings are untouched. Every league and the accounts file are backed up first. The site owner is Race Master of every league and re-links people to their drivers on Members & roles.
- **Everyone sees the changelog**: new accounts get the current version's What's New to agree to as well.

## 2.1.2 · One site owner, and everyone signs up themselves
_Released September 24, 2026_
> Accounts now work like a normal website: one owner account, made with the host's setup code, and everyone else
> creates their own. There's no list of accounts anywhere. All logins were reset once; no league was touched.

### Highlights
- **Every login was reset once.** Leagues, drivers, results and memberships are exactly as they were. Sign up again with your old username (and the same email) to get your leagues straight back.
- **No more list of accounts.** The owner looks up one account by exact username or email; league pages ask for a username instead of listing everyone.

### Changed
- **Accounts reset (once, on the first start of 2.1.2)**: every login, signed-in device, pending sign-up, password-reset link and account preference is removed. A copy of the accounts file is saved in the backups folder first. League files are not opened or changed; site settings (email, sign-ups, league creation) are kept.
- **Old usernames are reserved**: nobody else can sign up with a name that's still a member of a league. The person who had it reclaims it by signing up with the same email (verified by a code), and their memberships come straight back. The owner can release a reserved name. Members & roles marks reserved members as "Not signed up yet".
- **Sign-up**: always open to everyone (unless the owner turns it off). With email set up it confirms your address with a code; without it, the account is made straight away.
- **Account recovery** (owner only) replaces the list of logins: find one account by exact username or email, then set a new password (signs them out everywhere), change their email, turn off two-step sign-in, sign them out everywhere, or delete the login (their leagues stay; the name is reserved for them).
- **No account lists**: "Add a login", "All logins" and changing someone's site role are gone. Members & roles, the new-league form and invitations ask for a username.

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
- **Season rollover** no longer leaves a player driver with an expired contract in a seat without asking, or with a seat and a contract at different teams.
- **Completed rounds** can no longer be renumbered by accident when the calendar is saved.
- **Search palette**: pressing Enter straight after typing no longer opens a result from the previous search.
- The Activity Log no longer fails on a handover submitted from the form.

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
