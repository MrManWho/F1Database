# Changelog

Every version of Paddock Legacy, newest first. The same list is in the app under
**account menu → What's new**.

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
