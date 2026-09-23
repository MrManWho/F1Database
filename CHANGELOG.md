# Changelog

Every version of F1 Universe Tracker, newest first. The same list is in the app under
**account menu → What's new**.

## 1.16 · Polish, clearer roles and easier reading
- **One place for roles.** Each league member has one role: Race Master, Scorekeeper, Member or Spectator, set on the league's Players & Logins page. The old account-wide Scorekeeper switch is gone; anyone who had it keeps Scorekeeper in every league they belong to.

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
