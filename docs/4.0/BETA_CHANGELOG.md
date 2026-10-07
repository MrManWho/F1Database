# 4.0 test-site changelog

The alpha and beta builds of 4.0 as they were released on the test site, newest first. Kept for the record;
the public changelog has one 4.0.0 entry instead.

## 4.0.0-beta.19 · Running 4.0 on your own computer (test site)
_Released October 6, 2026_
> A safe way to run and edit 4.0 on a Windows PC, with the browser updating as files change. The site itself is unchanged.

### Highlights
- **dev.bat runs a private local copy** at http://127.0.0.1:5050, with its own data in the project's `.devdata` folder. It never sends emails, Discord posts or phone alerts, and it won't start if anything would point it at the live site or the desktop app's saves.
- **The open page updates as you edit.** Page and script changes reload it, and style changes apply in place. If you've typed into a form, a Reload bar appears instead, so nothing you typed is lost.
- **Fictional test leagues in one command:** a league with eight rounds played, and one with only its last round left for trying the finale and rollover.
- **/ship-4-0 in Claude Code** releases the next beta the usual way: version number, changelog, admin notes and tests, then it asks before pushing to the test site.

### Nothing changed in
- Formulas, standings, career numbers, the AI recommendation policy, permissions, league data and how the live and test sites start.

## 4.0.0-beta.18 · Two small fixes after the redesign (test site)
_Released October 6, 2026_
> The race time's Clear button works, and the league list can't fall behind a change.

### Highlights
- **Clear** next to a round's race time now clears it. Before, the time you'd set stayed put.
- **Your leagues are always up to date.** The league switcher, Your leagues, account export and account deletion always reflect a change made a moment earlier, even on servers whose clocks only tick once a second.

### Nothing changed in
- Formulas, standings, career numbers, the AI recommendation policy, permissions and league data.

## 4.0.0-beta.17 · The 4.0 redesign (test site)
_Released October 6, 2026_
> A new look for the whole site in navy, white and orange, and a race weekend page with a clear place for every job.
> Every feature is still here, and no numbers or rules changed.

### Highlights
- **Each race weekend is one page with four steps.** Prepare, Sessions, Review & submit and Debrief run down the left, with the round's sessions (Qualifying, Sprint, Race) under Sessions. The page opens on the step you need. A link to a step or a section still goes straight there.
- **Each session is its own workspace.** Its results table comes first, then everything that belongs to that session: race times, weather (once the session has run), incidents and penalties, and the AI level and distance for the race. Finished parts fold away. Anything required that isn't done stays open and says who it's for.
- **Save & continue never submits.** The bar at the bottom shows whether your changes are saved ("Saving…", "Saved", "Saved on this device — waiting to sync", "Couldn't save — retry") and names the next step.
- **Review & submit is one screen.** It lists what must be fixed, the warnings and any optional details nobody entered, then a summary of what will be submitted. **Fix** takes you to the exact field and brings you back. There's one **Submit weekend** button with no extra pop-up, and pressing it twice still submits once.
- **The Debrief keeps three things apart:** the weekend is submitted, your own post-race tasks, and whether the league is ready for the next round.
- **Weekend overview and Waiting on**, on the right of every step. They show the AI level, the format, the race clock, each session's state, and who the round is waiting for, by name.
- **Home starts with one next action.** Below it are the current weekend, your tasks, what the league is waiting on, the last race, the championship and your career.
- **No weather before the race.** Weather only appears once a session has run, as a record of that session.
- **Light theme by default** for anyone who hasn't picked one. Dark is still in your settings, and both themes were checked page by page.
- **Sign-in, Your leagues, new-league setup and the error pages** have the same navy header as the rest of the site.
- **Your league's colour** marks your league: its badge in the league switcher, on Your leagues and on its public page. Buttons and highlights are the site's orange everywhere, so they're always readable.
- **Faster on sites with many leagues.** Every page used to re-read every league on the server to build the league switcher. On a test server with 33 leagues, pages now load 40–50% faster (Home 92 → 50 ms, a race weekend 93 → 49 ms).

### Fixed
- In leagues with race weekends switched on, the round page left out the race story's facts, the fan vote, the list of who's checked in and everyone's predictions. They're shown again.
- If saving one player's race times failed, what you typed came back in every player's form. It now comes back only in that player's form, for the right session.
- Home no longer asks you to accept a weekend target that was already locked in for you at lights out.
- While a round's results are being entered, Home's **Waiting for** says so for Race Masters too, the same as the round page.
- Screenshot import works again. Since beta.13 it couldn't load its reading engine, so every import failed.

### Nothing changed in
- Formulas, standings, career numbers, the AI recommendation policy, permissions and league data. No league file format change.

## 4.0.0-beta.16 · A failed report reopens where you left it (test site)
_Released October 6, 2026_
> Small fixes from checking beta.13 on a phone in both themes.

### Highlights
- **A report that didn't send reopens with what you typed.** If an incident report (or any form in a pop-up) couldn't be saved, its pop-up now opens again with your text and the reason at the top, instead of the text sitting hidden in a closed pop-up.
- **Error messages are easier to read in the light theme.**

## 4.0.0-beta.15 · League Readiness Check (test site)
_Released October 6, 2026_
> One page that tells the Race Master what needs attention in the league and where to fix it, without changing anything.

### Highlights
- **Manage League → Readiness check.** A summary at the top: the league and season, an overall status, how many blocking issues, warnings and optional items there are, when it last checked, and *Run check again*.
- **Four separate answers, never one "everything is ready".** Ready to submit the current weekend; ready to close the season; ready to start the next season; league data ready for the 4.0 transition. Each one says *Ready*, *Needs attention*, *Blocked*, *Not checked* or *Check failed*. It is never green when a check failed or hasn't run.
- **Every finding says what to do.** For example: "Round 8: Carson's grand prix timing is incomplete. Enter the race gap and laps, or tick Don't submit times. Blocks: Submit weekend. [Open Round 8 timing]". Each one also says why it matters and who can fix it. Filter by blocking, warnings, optional, category or season. Passed checks stay folded away.
- **Only the rules the site already has.** Something only counts as blocking if the site already refuses that action, like the round gate, Submit weekend, required race times or two drivers signed for one seat. Weather, notes and Driver of the Day are optional and never lower readiness.
- **Earlier seasons stay as they were.** Anything a season never tracked is *Not applicable*, not missing. Missing upgrade-notice acknowledgements are information only. A driver without a seat is a valid outcome, not an error. A contract without a seat is still flagged.
- **4.0 transition checklist.** Migration status, tracking coverage of earlier seasons, historical records, season-end processing, and whether next season's contracts and grid are finalised. Blockers link straight to the fix. It works for a league moving to 4.0 mid-season or between seasons. Site deployment (Render, restore tests) is kept separate and isn't claimed.
- **Read-only.** Checking never recalculates, submits, closes a window, marks anything read, sends anything or repairs a record. The quick checks run each time the page opens. *Run full check* also reads every earlier season, and its result is kept until the league changes ("Changes since last check: run again").
- **Scorekeepers** see only the race-weekend findings they can act on. Private press answers and contract terms are never shown.

### Nothing changed in
- Formulas, standings, career numbers, permissions of existing pages and league data. No league file format change.

## 4.0.0-beta.14 · Same numbers on every server (test site)
_Released October 6, 2026_
> The site now always runs on the same version of Python as the live site, so every career number comes out exactly
> the same wherever it's worked out.

### Highlights
- **No hidden number drift.** Newer versions of Python add up decimals in a slightly different way, which could move a Driver Value by half a point or the recommended AI by a few levels. The site is now fixed to Python 3.11, the version the live site has always used, so moving to 4.0 can't change anyone's numbers this way.

### Nothing changed in
- Formulas, standings, career numbers, permissions and league data. No league file format change.

## 4.0.0-beta.13 · Faster pages, and forms that bring you back (test site)
_Released October 6, 2026_
> Saving something now takes you back to where you were, says clearly whether it saved, and never saves twice.
> League pages do far less work, so Home and Race Weekend open two to four times faster.

### Highlights
- **No more surprise trips to Home.** Answering pre-race press from Prepare brings you back to that round's Prepare; post-race press from the Debrief goes back to the Debrief; the standalone Press page stays on the Press page. Every other form goes back to the page, step and section it was sent from.
- **When something doesn't save, you're told why, on the same page.** A mistake in a form keeps what you typed and shows the reason. A page left open too long, or being signed out, says so plainly ("that wasn't saved") instead of silently dropping you on Home. Signing back in returns you to where you were. Something only the Race Master can do now says so, with a button back to where you were.
- **Saved means saved.** Buttons show "Saving…" while a form is on its way. Results entry shows *Saving…*, *Saved* (only once the site has confirmed it), *Saved on this device — waiting to sync* when the connection drops, or *Couldn't save* with a Retry button. A form sent while offline isn't lost: you're told, and what you typed stays.
- **Pressing twice, or retrying after a lost connection, never counts twice.** Interview answers, weekend targets, pledges, signing or declining a contract, and incident reports are each saved once; the second press just says "Already saved". Two people (or two tabs) acting at the same moment are handled one after the other.
- **"Fix" on Review & submit leads back to Review.** After fixing something from the checklist, the button reads *Save & return to Review* instead of carrying on through the remaining sessions.
- **Faster pages.** League Home went from about 0.3–0.4 s to about 0.1 s of server time in a three-season test league, Race Weekend from about 0.17 s to 0.08 s, Career and Standings about twice as fast. Stylesheets and scripts are now kept by your browser between visits instead of being checked on every page.
- **Clearer AI recommendation.** The F1Laps figure is now called the *community starting reference*, a starting point and not proof of what suits your league. The breakdown says when track history is turned off, describes how much evidence is behind the confidence, and, for a finished round, shows the AI actually used next to the one recommended. The calculation itself is unchanged.

### Nothing changed in
- Formulas, standings, career numbers, permissions and league data. No league file format change.

## 4.0.0-beta.12 · Earlier seasons look complete under their own rules (test site)
_Released October 6, 2026_
> When a league moves up from 3.x, its earlier seasons are shown under the rules they were played with, and everyone
> gets one short note about the upgrade.

### Highlights
- **Nothing to re-enter.** Things the old website never collected (race times, incidents by session, the AI recommendation shown before each round) are hidden or marked "Not tracked under this season's rules" on older rounds. They never count as missing, incomplete or zero, and older rounds never ask for race times before they can be saved again.
- **Gaps are still gaps.** Something the season did track but that was never entered shows "Not recorded", so a real gap isn't mistaken for an old rule.
- **A small "Legacy season" note** on the history pages of an older season, saying where your league's new tracking begins (for example "from Round 7 of this season"). It appears once per page, not on every card.
- **Fair statistics.** Statistics that rely on tracking only count rounds where it was tracked, and say so: "Based on 3 eligible rounds · Tracked since Round 3 of the 2026 season".
- **"Your league has been upgraded to Paddock Legacy 4.0".** The first time each member opens an upgraded league, a short note explains what changed and where new tracking begins. *Got it* is remembered for your account in that league, on every device. *Not now* only hides it until next time. Leagues created on 4.0 never show it.
- **Your history is untouched.** Results, standings, Form, Reputation, relationships, contracts, offers and next season's grid stay exactly as they were. If a league also recalculates, that is explained separately and still goes through *Changes to your driver*.
- **What each season tracked** (League → the note's *What was tracked* link) lists, season by season, when each feature began. If something was first used part-way through a season, the Race Master confirms the real start round there.

### Migration notes
- League files move to format 26 (the upgrade record, what each season tracked, and who has seen the upgrade note). A league last saved by 3.x records this once, the first time 4.0 opens it. Nothing existing changes.

## 4.0.0-beta.11 · Try a season finale (test site)
_Released October 6, 2026_
> A practice league for trying the end of a season and the start of the next one.

### Highlights
- **A league with one round left, on demand.** Account → Settings → *Try a season finale* adds a fictional league with 23 of its 24 rounds already played, with you as Race Master driving Player One. Enter the last round, then start the new season from Seasons to see the rollover from start to finish. Test site only.

## 4.0.0-beta.10 · Link a login to any player driver (test site)
_Released October 6, 2026_
> Fixes player logins that couldn't be linked to a player driver already in the league.

### Highlights
- **Link login, right where it's needed.** Every driver under *Members & roles → Player drivers without a login* now has a username box and a **Link login** button. The person is added to the league as a Member if they aren't in it yet; a Race Master or Scorekeeper keeps their role.
- **Joining as a driver who's already on the grid works.** Asking to join with the name of a player driver nobody drives yet used to be refused ("There's already a driver with that name"). Now the request goes through, and approving it hands them that driver instead of making a duplicate. The Race Master can also pick the driver from a list when approving.
- Real F1 drivers and drivers someone already drives still can't be claimed.

## 4.0.0-beta.9 · Silly Season closes by itself (test site)
_Released October 6, 2026_
> The 3.2.6 fix from the live site, plus the 3.2.5 note that beta.8 carried.

### Highlights
- **Silly Season no longer stays open forever.** A transfer window now closes the moment its last offer is signed or turned down and every player driver is sorted: signed with a team, already under contract, or out of offers and approaches. Everyone gets a notification and a paddock headline when it closes.
- **Windows already stuck open close on their own** the next time anyone opens the league. Signings made in them stand as they are. The Race Master can still close a window early from Market administration.
- **The press fix shows on "Changes to your driver"** (from beta.8): if a repeat press answer was removed from your league, your Changes page lists it with the round and what it did to your numbers.

## 4.0.0-beta.7 · Press questions stay put when Silly Season opens (test site)
_Released October 1, 2026_
> The 3.2.4 fix from the live site.

### Highlights
- **Older rounds no longer ask their press questions again.** Each round's questions are now fixed when the round is submitted, so opening (or closing) a market window never swaps a question at an older round.
- **Answers given to those repeat questions are removed** the first time a league opens on this version, along with anything they added to the team relationship. Anyone affected gets a note naming the round.

## 4.0.0-beta.6 · Race Control: a brand-new website (test site)
_Released September 29, 2026_
> Paddock Legacy is rebuilt as "Race Control": a website that looks and reads like a timing screen, from the first
> page to the last.

### Highlights
- **A completely new look.** Carbon panels, flat instrument-style cards, bold condensed headlines and every number in a timing-screen font, so positions, gaps and points line up. Your league's colour is the one loud colour. Green means better or done, amber means it needs you, coral means worse or missed. A light "paper" version is in My settings → Theme.
- **A new Home: Race Control.**
  - **The championship as a timing tower** down the left: team colours, three-letter codes, gaps to the leader, who moved up or down, and every player highlighted.
  - **The next race** in big letters with its countdown, the recommended AI and the circuit outline, plus start lights showing how many players are ready.
  - **One "next action" bar**, your tasks, what the league is waiting on, and your last race (grid, finish, points and whether you hit your target).
  - **Your season** on the right: your championship position, a line of every finish this season, and your stats.
- **The Race Weekend, redrawn.** A race-programme header with the round number, a step bar drawn like timing sectors, target cards that lead with the real target and what it's worth, and a pit board with the AI level, weather, sessions and every player's target.
- **Standings.** The top three lead the page, and every table reads like a timing screen.
- **A new top bar and status strip.** Home, Race Weekend, Championship, Career and More across the top; your league, season, view and search in a thin strip underneath.
- **Fixed:** the view-mode and league menus could open underneath the Race Weekend step bar.

## 4.0.0-beta.5 · The new look on every page (test site)
_Released September 29, 2026_
> The rest of the site catches up with the Race Weekend's new design.

### Highlights
- **Every page gets the race-programme header.** Home, Championship, Career, More and the admin pages open with the same bold banner as the Race Weekend: big condensed title, a fine grid and a wash of your league's colour (your team's colour on Career pages).
- **A podium on the standings.** The top three drivers sit above the table with their gap to the leader, and a player in the top three is outlined in their colour.
- **Home, restyled.** The next action is one big button, the next race opens like a programme with the round number and circuit outline, and your driver card leads with your championship position.
- **Career stat tiles.** Driver Value, Reputation, Form and the rest are clear tiles with their change since the last round.
- **Section tabs and tables** use the new type throughout, in both the dark and light themes.

## 4.0.0-beta.4 · Creating a league keeps your answers (test site)
_Released September 29, 2026_
> A fix for the new-league setup.

### Highlights
- **Fixed:** if creating a league failed (for example a username that doesn't exist), the setup page started again from empty. It now keeps everything you typed, including extra player drivers and invitations, and opens at the step with the problem, with the reason shown at the top.

## 4.0.0-beta.3 · A whole new look (test site)
_Released September 29, 2026_
> Paddock Legacy gets a new design: a top bar with the five destinations, a race weekend that opens like a race
> programme, and two themes.

### Highlights
- **A new look everywhere.** New type (a bold condensed face for headlines), new colours, new cards, buttons and tables on every page.
- **Two themes.** Dark "Pit Wall" and light "Paddock Paper", both in your league's accent colour. Switch in My settings → Theme.
- **Top navigation.** Home, Race Weekend, Championship, Career and More sit across the top, with Manage league (or Results entry for Scorekeepers) on the right. Your league, season and search are in the bar just below. Phones keep the bottom bar.
- **A race weekend header worth looking at.** The round number, the Grand Prix in big letters, the circuit and its outline, and a step bar that says what each step is for.
- **Weekend target cards.** Safe, Standard and Stretch each get an icon, the real target and what it's worth if you hit it or miss it.
- **Weekend at a glance.** The AI level, the weather as recorded, the next session and the race time, plus every player driving this weekend and the target they chose.
- **Pre-race interview.** It shows whether it's open, waiting for your answers or done, with a button straight to the questions.

### Added
- The live site's fix that leaves money out of old deal terms (3.2.3).

## 4.0.0-beta.2 · Results table fix (test site)
_Released September 29, 2026_
> The results table is tidy again when you enter one session at a time.

### Highlights
- **Fixed:** the results table's header could slide down over the first driver.
- **Fixed:** entering a single session showed a stretched Driver column and a tiny position box. Each session now shows a compact table with just its own columns.
- **Tidier tools:** each session only offers its own quick order, and "Copy an order" only appears for the Sprint and the Race.

## 4.0.0-beta.1 · A new look and one place for each race weekend (test site)
_Released September 28, 2026_
> A redesigned site built around the race weekend: Home tells you what to do next, and every round has one
> workspace that takes you from getting ready to the debrief. A busy race's incidents now make one news story.

### Highlights
- **One workspace for each race weekend.** Race Weekend walks through four steps: Prepare (your target, press, check-in and predictions, required things first), Sessions (Qualifying, the Sprint on Sprint weekends, then the Race, one at a time), Review & submit, and Debrief. The page always opens at the step the round has reached, and you can jump back to any step.
- **Enter one session at a time.** Each session has its own results, weather and incidents. "Save & continue" saves and moves to the next session; it never submits. Your changes still save by themselves and are kept on your device if the connection drops.
- **Review before you submit.** One list of everything that must be fixed, with a Fix button that takes you straight to the right session and box, then a summary of what will be submitted and a single Submit weekend button. Pressing it twice (or on two devices at once) only ever submits once.
- **A Debrief for every round.** The podium, your weekend (with your Form, Reputation and championship changes and why they changed), your post-race press, your weekend target and the AI for the next round, all in one place. Only your own career numbers are shown.
- **One stewards' story per race.** Ruling on incidents no longer posts a headline for each one. Each round has one news story that counts the decisions and names only real penalties, and it updates as rulings come in. Stories from before are combined the first time the league opens.
- **Incidents belong to a session.** Report an incident from the session it happened in (Qualifying, Sprint or Race). Older reports show as "Weekend".
- **Simpler navigation.** Home, Race Weekend, Championship, Career and More. Manage League sits apart and only appears for the people who can use it. Championship, Career and More have tabs for everything inside them. Old links still work.
- **A clearer Home.** Where the league is, one next action, your own tasks, what the league is waiting on from others, and short summaries. The stacked banners are gone.
- **Always the latest calculations.** There are no calculation versions to choose between any more. A league that was still on older calculations moves over the first time it's opened: everything already calculated stays exactly as it was and the latest rules apply from the next round. The season under way also switches to the track-aware AI recommendation.

### Changed
- Help no longer describes older calculation rules.
- The weekend summary page is still there (Debrief → Full race summary) and the Press page keeps your full press history under Career.

### Migration notes
- League files move to format 25 (incidents record their session). Incident headlines from earlier versions are combined into one story per round.

## 4.0.0-alpha.3 · Race times made easy (test site)
_Released September 28, 2026_
> Type two race times instead of working out a gap, and every tracked round now includes them. Also brings over the
> live site's maintenance mode and its fixes.

### Highlights
- **Just type the two race times.** Under Pace & conditions, enter your race time and your AI teammate's (or the driver you choose to compare with) straight from the game's results screen. The site works out the gap, and shows it as you type.
- **Race times are part of every tracked round.** Before a round with a tracked AI level can be submitted, each player who finished enters their race times and laps, or ticks "Don't submit times" for that session. The final check says exactly who's missing. The Race Master can switch this off in League settings → Race weekends.
- **Fixed:** the round page could fail to open for a round that had results entered but wasn't submitted yet.

### Added
- Maintenance mode, the sign-in fix and the fix for links landing on a page of code, from the live site (3.2–3.2.2).

### Migration notes
- League files move to format 24 (the two race times are stored alongside the gap). Existing lap-time entries keep the gap they were given.

## 4.0.0-alpha.2 · A track-aware AI recommendation (test site)
_Released September 28, 2026_
> One AI level for the whole weekend, starting from what players really use at each circuit in F1 26 and learning
> from how your league races. Seasons already under way keep their current recommendation until they finish.

### Highlights
- **One AI setting for the weekend.** The recommendation covers qualifying, the Sprint and the race together. No Time Trials or personal baseline needed.
- **Starts from each circuit's real average.** Every round begins from the F1Laps average AI for that circuit in F1 26 (for example Monaco 80, Canada 84, Las Vegas 76), so the level changes sensibly from track to track.
- **Learns your league.** After each weekend it compares every player with their AI teammate (or cars of similar speed, or where the car should finish). If everyone agrees it moves further, up to 2 after one weekend, 3 after two in a row and 4 after three; mixed results move it little or not at all.
- **Fair to bad luck.** DNFs, DNS, DSQ, major incidents and no-fault results never count as "too hard"; wet or disrupted races count less; beating your teammate is never a bad sign.
- **Everything explained.** Each recommendation shows the F1Laps baseline, the league adjustment, track history, the evidence and the confidence, and warns when the drivers are so far apart that no single AI suits everyone.

### Added
- Track history: after repeated visits to a circuit, part of the baseline is replaced by how your league's players did there (up to ±3). Race Masters can switch it off in League settings → Race weekends.
- Each round keeps the recommendation made before it next to the AI actually used, and never recalculates it later.

### Changed
- New leagues and every new season use the track-aware recommendation. A season already under way keeps the tracker it started with.

### Migration notes
- League files move to format 23 (a new, empty table for the saved recommendations). A backup is taken first; nothing else changes.

## 4.0.0-alpha.1 · The foundation for 4.0 (test site)
_Released September 28, 2026_
> The first 4.0 build, on the test site only. Your career numbers, results and rules are exactly the same; this build
> reorganises the menu and adds the safety groundwork the rest of 4.0 builds on.

### Highlights
- **A clearer menu.** Every league now has five places: **Home**, **Race Weekend**, **Championship**, **Career** (your driver) and **Paddock** (news and the community), with the Race Master's tools in their own **Manage League** area. Every page is where it was, just grouped more simply. The phone bar at the bottom matches.
- **Your theme and density follow you.** Dark, light or match-my-device, and comfortable or compact, are now saved to your account, so every phone and computer you sign in on looks the same.
- **A change record for every league.** Activity log → Change record lists every change exactly as it happened, with the values before and after for members and roles, league settings and rounds. Entries can never be edited or deleted.
- **Nothing is sent from the test site.** Every email, Discord post and phone alert it would have sent is kept as a preview for the site owner to check instead.

### Added
- Site owner: Site errors (what went wrong recently, with private details removed), Site change record, Delivery preview (test site), Design system and a health check, all under Account → Settings → Site health.
- An environment badge next to the version number (for example "4.0 test"), so a copy of the site is never mistaken for another.
- A clearer message on pages you can't open, pages that don't exist and unexpected errors.

### Changed
- Menu groups renamed: League → Home, Race Weekend, Championship and Paddock; Manage → Manage League (Race weekends, Career management, League administration). Rivalries moved to Championship; Transfers to Paddock.
- An imported live backup no longer keeps the live site's email password, and each league's Discord webhook is replaced with a placeholder on the test site.

### Migration notes
- League files move to format 22 (a new, empty change record). A backup is taken automatically before the upgrade, as always. Nothing else changes and no numbers are recalculated.
