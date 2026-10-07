# 4.0 UI and race-weekend overhaul: proposal for approval

**State:** approved (D1–D8) and built in 4.0.0-beta.1. Audited against `release-4.0` at 4.0.0-alpha.3.
The clickable prototype is `prototype/weekend.html` (also published as a private link for review).

---

## 1. Current workflow problems (from the audit)

**What a weekend actually involves today** (standard round, race weekends on):

| # | Action | Who | When it's allowed | Where it lives today |
|---|---|---|---|---|
| 1 | See the round, circuit, race time | everyone | any time | Calendar → round page, Control Room "Next up" |
| 2 | Choose weekend target (Safe / Standard / Stretch) | the driver | before lights out | round page *Weekend* tab, also a banner on every page |
| 3 | Answer post-race press from the **previous** round | the driver | until it's answered | Press page (a separate page), banner |
| 4 | Growth pledge (when asked) | the driver | when requested | Pledge page (a forced gate) |
| 5 | Check in, predictions (pole, winner, FL, top player) | members | until the race starts | round page *Weekend* tab, Predictions page |
| 6 | Open the paddock | Scorekeeper / RM (or automatic 1 h before) | before the race | round page paddock card |
| 7 | Pre-race press | the driver | paddock open → lights out | round page paddock card |
| 8 | Round gate (targets, press, previous press) + reminder / RM override | Scorekeeper / RM | before lights out | round page gate card |
| 9 | Start the race ("lights out") | Scorekeeper / RM | gate clear (RM can override) | round page paddock card |
| 10 | Enter Qualifying, Sprint and Grand Prix results, statuses, FL, DotD, AI difficulty | Scorekeeper / RM | after lights out | round page *Results* tab: **one grid with all sessions at once** |
| 11 | Screenshot import | Scorekeeper / RM | after lights out | dialog in the Results grid |
| 12 | Weather per session | Scorekeeper / RM | any time | Results tab, separate card |
| 13 | Race times vs AI (now required on tracked rounds) | Scorekeeper / RM | before submitting | Results tab, a card **below the grid** |
| 14 | Report an incident / rule on it | members / RM | any time | *Incidents & chat* tab (not tied to a session) |
| 15 | Review and submit | Scorekeeper / RM | after lights out | a dialog opened from the grid |
| 16 | Post-race press | the driver | after submission | Press page |
| 17 | Target outcome, team orders ruling, relationships, Form/Rep changes | driver / RM | after submission | Garage, Relationships, change notices, Team orders on round page |
| 18 | Weekend summary, fan vote, comments, share card | everyone | after submission | Summary page (separate), round page |
| 19 | Correct / reopen / reset a round | RM | after submission | round page, a confirmation page |

**Problems**

1. **No path through the weekend.** Items 2–18 are spread over the Control Room, three tabs of the round page, the
   Press, Pledge, Predictions, Garage, Relationships and Summary pages. Nothing says which comes first.
2. **All sessions at once.** Results entry shows Qualifying, Sprint and Grand Prix as columns of one large grid,
   so there's no "do Qualifying, then the Race".
3. **Required things hide below optional ones.** Race times (now required) sit under the grid; required press sits on
   another page; the target choice is mixed with check-in, predictions and chat.
4. **Too many competing signals.** Up to five banners stack at the top of every page (race now, waiting on you,
   Calculation Update, league notice, backup), plus a long sidebar (about 25 links for a Race Master who drives).
5. **Duplicates.** The AI recommendation appears on three pages; "enter results" has four entry points; targets and
   press are nagged about on every page and done on another.
6. **Personal vs league readiness is blurred.** "The race can't start until everyone's ready" appears to a driver who
   has done their own part.
7. **Incidents float free.** They belong to a round, not a session, and live on a separate tab from the results.
8. **The weekend ends on a different page.** After submitting, the summary, press, target outcome and changes are on
   four other pages.

**Sessions the app really supports:** Qualifying (one grid, used for the Grand Prix; counts for poles and racecraft),
Sprint (Sprint weekends only) and Grand Prix. **There is no separate Sprint Qualifying.** See decision D1.

---

## 2. Feature-to-destination map

**Main navigation (4 + More):** Home · Race Weekend · Championship · Career · More. Account (avatar) and Manage
League (Race Masters only) sit apart. Scorekeepers get an "Enter results" shortcut on Home and in the workspace.

| Today | 4.0 destination |
|---|---|
| Control Room | **Home** (next action, my tasks, waiting-on, next race, compact standings and career) |
| Round page (all tabs), results entry, Weather, Pace & conditions, Paddock / gate / lights out | **Race Weekend** workspace: Prepare · Sessions · Review & Submit · Debrief |
| Weekend target, pre-race press, check-in, predictions (per round) | Race Weekend → **Prepare** (required first, optional collapsed) |
| Post-race press (Press page), target outcome, change notices for this round, race summary, fan vote, share card | Race Weekend → **Debrief** |
| Incidents for a round | inside the **session** they happened in; consolidated in Review; the full list stays under More |
| Team orders ruling, target excuse, reopen, reset, open early | Race Weekend, in a separated **Race Master** strip |
| Calendar, season review | **Championship** → Calendar |
| Standings, Statistics, Drivers, Teams, Records, Rivalries | **Championship** (standings first; the rest as secondary tabs) |
| Garage, Relationships, Contracts & offers, Pledge, Progression, Team goals, Press history | **Career** (team, relationship, contract and decisions first; the rest as sections) |
| News, Announcements, Predictions standings, Incidents list, Transfers, Help | **More** |
| My settings, notifications, theme, account | **Account** (avatar) |
| Members, settings, grid & contracts, market, drivers & teams, team management, backups, activity, notifications log | **Manage League** (grouped by purpose, unchanged tools) |

Old links redirect to their new place (for example `/press` → the current round's Debrief, `/weekend` → the
workspace at the right stage, `/garage` → Career).

---

## 3. Layouts

**Phone (360 px and up):** a top bar (league, round chip, avatar) and a bottom bar with Home, Race Weekend,
Championship, Career, More. In the workspace, the four stages are a compact segmented strip under the round title;
the current stage's content fills the screen; one primary button is fixed at the bottom above the bar.

**Desktop:** a slim left rail with the same five items (Manage League underneath for Race Masters), content in a
single column of about 720 px, and on the workspace a narrow right column for "Your tasks" and "Waiting on".
Nothing requires scrolling past optional content to reach a required action.

Stages and their states: each stage and session shows *done*, *current*, *upcoming* or *needs attention*; progress
comes from the saved league state (for example "Qualifying saved", "Race times missing"), never from the last page
visited.

---

## 4. Prototype

`prototype/weekend.html`: a clickable standard weekend (R5 Saudi Arabian GP) with example data. Use the
"View as" switch to see the Driver, Scorekeeper, Race Master and Spectator versions. It is a design prototype:
nothing is saved and no numbers are calculated.

---

## 5. Decisions that need your approval (functionality, not just layout)

| # | Decision | Recommendation |
|---|---|---|
| D1 | **Sprint Qualifying** isn't a separate session today (one Qualifying sets both grids). Add it? | Keep as is for 4.0: Sprint weekends show Qualifying → Sprint → Race. Adding Sprint Qualifying needs a new stored position and a decision on whether it counts for poles and racecraft (a calculation change), so it belongs to a later version. |
| D2 | **Incidents per session**: store which session an incident happened in. | Yes (a stored field only; rulings and their effects unchanged). Existing incidents show as "Weekend". |
| D3 | **When Sessions open**: today results can only be entered after "lights out". | Keep. The Race Master can still open a round early with a note. |
| D4 | **Weather forecast**: the app records the weather that happened; it has no forecast. | Don't invent one. Prepare shows "Recorded after the session"; add a forecast only if you want a new feature. |
| D5 | **Save & Continue per session**: uses the existing autosave (no submission, no calculations). | Yes, no rule change. |
| D6 | **Double-submit safety**: two submissions arriving at the same moment could both run the post-race steps. | Fix it during the build (a safety fix; nothing changes when it works). |
| D7 | **Home shows one next action** and removes the stacked banners (they move into Home's task list or the relevant stage). | Yes. |
| D8 | **Team orders, target excuses, reopen, reset and open-early** move into a Race Master strip on the workspace. | Yes (same rules, same permissions). |

Nothing in this plan changes a formula, a permission, a gate rule or stored history.
