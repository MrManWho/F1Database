# 4.0 redesign: design, navigation and where every feature lives

4.0.0-beta.17. This is a new look and layout for the features the site already has. Nothing was added that changes
a career rule, a formula or a permission, and nothing was removed. Pre-race weather was never shown before the race
and still isn't: weather is recorded per session once that session has run.

## The look

- **Navy, white and orange.** A navy app bar, white pages and cards, and orange for the one main action on a screen.
  - Orange buttons use `#cf4a0b` with white text (4.5:1).
  - Orange text uses `#c2410c`.
  - Decorative orange (track maps, underlines) uses `#f4581c`.
- **Type.** Barlow for text and Barlow Semi Condensed for headings and numbers. Both are served from the site, so
  there's no third-party request.
- **Light and dark themes.** Light is now the default for anyone who never picked one. Anyone who picked a theme
  keeps it. Both themes use the same tokens (`static/css/pl.css`), and the dark theme was checked page by page.
- **Status is never colour alone.** Every state has an icon and a word: a check and "Saved", "!" and "Needs input",
  a lock and "Closed", "i" and "Optional".
- **Team and league colours** are only used as stripes, dots and badges next to text, never as the text colour.
  A league's own colour (League settings) colours its badge in the league switcher, on Your leagues and on its
  public page. Buttons and highlights are always the site orange, so they stay readable whatever colour a league
  picks.

## Navigation

- **Top bar (navy).** Home · Race Weekend · Championship · Career (only for someone with a driver) · More, then
  notifications and the account menu. An orange underline marks where you are.
- **League bar (white).** The league switcher, the season picker with its status, the view-as switch, Search
  (Ctrl K), Save now (Race Master) and **Manage league**.
  - Manage league is the only place for administration.
  - A Scorekeeper sees it as **Results entry**, with only the race-weekend items.
  - Members and Spectators don't see it.
- **One row of sub-pages per destination** (Championship, Career, More). Switches inside a page, like Drivers and
  Constructors, are segmented controls, not a second tab bar.
- **On a phone** the five destinations are the bottom bar and the league bar is one row.
- **Redirects.** No address changed in this version. The round page's old anchors still work:
  - `#pace`, `#weather`, `#incidents`, `#press`, `#target` and `#race-time` open the right step and session.
  - The calendar's "Set a time" now opens Prepare → Race time.
- **Search** goes to the exact page or round, as before.

## The round page (Race Weekend)

The concept's layout, filled with the features the round page already had.

- **Header:** the flag, "Round 05 / Race weekend", the Grand Prix name, a status pill, the circuit and city, the
  season and round count, the track map band, and the previous and next round.
- **Left rail (navy):**
  - 1 Prepare
  - 2 Sessions, with the round's own sessions nested (Qualifying, Sprint, Race)
  - 3 Review & submit
  - 4 Debrief
  - "View all round details" (the whole grid at once)

  Each step and session shows its state in words. On a tablet or phone the rail becomes a step strip, with the
  sessions as a second row while you're in Sessions.
- **Centre:** labelled sections. Each one shows its purpose, Required or Optional, who it's for, whether it's saved,
  and what to do next. Finished sections fold away, and a required section that isn't finished is never folded.
- **Right:**
  - **Weekend overview:** AI difficulty, format, the race clock (time and countdown), and each session's state.
  - **Waiting on:** who the round is waiting for, by name and job.
  - **View weekend target.**
  - The drivers this weekend.
- **Bottom bar:**
  - Back.
  - The save state: "Saving…", "Saved", "Saved on this device — waiting to sync" or "Couldn't save — retry".
  - **Save & continue**, which names the next step ("Next: Race"). It saves and moves on. It never submits.
  - On the Review step, whoever can submit doesn't get this button: the only way on from there is **Submit weekend**.
- **Where it opens:** the step comes from the round's saved state and your role (Debrief once submitted, Sessions
  or Review while results go in, otherwise Prepare). A link to a step, session or section always wins.

| Step | What's in it (all existing features) |
|---|---|
| Prepare | Your tasks, required first, with Done / Closed / Required / Optional. Three separate lines: "Your preparation is complete", "The league is ready", "Waiting on Name: task". Then Weekend target, Pre-race press, last round's post-race press when it blocks the start, Paddock & lights out (or the Round checklist when race weekends are off), the AI recommendation with its evidence folded, Race night (check-in, predictions, everyone's targets) and Race time (Race Master). |
| Sessions | One session at a time, in running order. Each has its Classification (the results table with player drivers highlighted, filters, quick order, copy an order, screenshot import, undo, clear, shortcuts), then the parts that belong to that session: Race AI difficulty and distance, Sprint distance, Race times, Weather (only once results can go in), Incidents & penalties and Weekend notes. |
| Review & submit | One screen: **Must fix**, **Warnings** and **Optional, not entered**. Each has Fix or Add, which opens the exact field and comes back to Review. Then "What will be submitted" (pole, winners, podium, DNF/DNS/DSQ, fastest lap, Driver of the Day, AI used, player results, incidents) and one **Submit weekend**. |
| Debrief | Three separate lines: "Weekend submitted", "Your post-race tasks", and "League ready for the next round" (or who it's waiting on, or that the season is over). Then the podium and facts, your weekend and target with "Why did this change?", post-race press, race story and fan vote, championship and next AI, the full race summary, press history and all results, and the share card. It says plainly that opening it changes nothing. |

## Feature-to-destination map

| Feature (before) | Where it is now |
|---|---|
| Round results table | Race Weekend → Sessions → each session's Classification |
| "Pace & conditions" card | Split by session: Sessions → Race → Race times; Sessions → Sprint → Race times; Weather in each session |
| AI difficulty used, GP distance | Sessions → Race → AI difficulty & race distance |
| AI recommendation and evidence | Prepare → AI difficulty for this race (evidence folded); Debrief → AI for the next round |
| Incident reporting and rulings | Sessions → each session → Incidents & penalties; More → Incidents |
| Weekend notes | Sessions → Race → Weekend notes |
| Submit dialog | Review & submit (the checklist and the summary are on the page; no dialog) |
| Paddock open / lights out | Prepare → Paddock & lights out |
| Round gate checklist | Prepare → Round checklist (or the paddock board when race weekends are on) |
| Weekend target | Prepare → Weekend target; Debrief → the target result; "View weekend target" on the right |
| Pre-race press | Prepare → Pre-race press |
| Post-race press | Debrief → Press pen (Home's next action links straight to it) |
| Race night: check-in, predictions, targets | Prepare → Race night |
| Race time and postponing | Prepare → Race time (Race Master); the overview shows the race clock |
| Race story, fan vote, teammate battles | Debrief |
| Corrections to a submitted round | Sessions (Race Master), with Save corrections |
| Reopen, reset, team orders | Race Master tools (bottom of every step) |
| Paddock chat and reactions | Paddock chat (bottom of every step) |
| Home "Control Room" | Home: one Next action, the current weekend, your tasks, what the league waits on, the last race, the championship top ten, your career card, news |
| Standings, calendar, results, statistics, drivers, teams, rivalries, records | Championship (one sub-page row) |
| Garage, relationships, contracts & offers, progression, press, team goals | Career |
| News, announcements, incidents, predictions, transfers, everything else, help | More |
| Results entry, Readiness check, calendar | Manage league → Race weekends |
| Grid & contracts, market, drivers & teams, team management | Manage league → Career management |
| Members & roles, league settings, notifications, activity log, backups | Manage league → League administration |
| Your leagues, accounts, sign in, new league, errors | Same pages, in the navy header |

## Pre-4.0 leagues

- Nothing about stored data, calculations or the AI policy changed in this version.
- Legacy seasons keep their "Not tracked" states: a section that wasn't part of a season's rules says so instead of
  showing zero.
- The first-open upgrade notice and its per-member "Got it" are unchanged.
