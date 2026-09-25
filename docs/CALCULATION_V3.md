# Paddock Legacy 2.5: Calculation Version 3

Application 2.5 · calculation engine 3 · database schema 21. Every formula below is the code as shipped
(`f1tracker/calc3.py`, `ai3.py`, `relations.py`, `teamgoals.py`, `teamlife.py`, `ultimatums.py`, `market.py`,
`pitch.py`, `migration.py`, `engine.py`). Worked examples were produced by running that code.

Notation: `r` = car-strength rank (1 = fastest), `n` = teams (11), `field` = cars in the round (22),
`clamp(x, lo, hi)`. **Rounding:** `round_half_up` (2.5 → 3, −2.5 → −3) for ordinary rounding, `ceil` for
minimum requirements, `floor` only where a target is meant to be easier. Python's round-half-to-even is never used
by engine 3.

---

## 0. Engines, versions and who uses what

| Thing | Where | Meaning |
|---|---|---|
| Calculation engine | `meta.calc_engine`, `season_calc.engine` | 2 = every formula as of 2.4.1; 3 = this document |
| League choice | `meta.calc_choice` | `new` (created on 3), `pending`, `later`, `full`, `future` |
| Future-only cutoff | `season_calc.cutoff_round` | rounds ≤ cutoff keep their Version 2 results; Version 3 after |
| Update counter | `C.CALC_VERSION` (still 3) | unrelated: 2.4.1 used it for the AI blend note. 2.5 doesn't bump it, so nothing recalculates by itself |

* New leagues start on engine 3. Existing leagues stay on engine 2 until the Race Master chooses.
* Completed seasons keep their engine forever unless a full recalculation of *that* active season was approved.
* A season without a `season_calc` row uses the league engine.

---

## 1. Result classification and points

### Status truth table

| Status | Stored value | Counts as a start | Classified (can score) | GP points | Race perf. position (Form) | Head-to-head | Pledge pace | Weekend target | Ultimatum |
|---|---|---|---|---|---|---|---|---|---|
| Finished | `Finished` | yes | yes | by position/distance | its position | its position | its position | judged | Met / Failed |
| Classified retirement | `Classified` | yes | yes | by position/distance | its position | its position | its position | judged | Met / Failed |
| Unclassified DNF | `DNF` | yes | no | 0 | field + 1 | loses to any classified car | last place | Missed | Failed |
| Verified no-fault DNF | `DNF` + `no_fault` | yes | no | 0 | field | loses to any classified car | left out (≤ 10% of rounds) | **Void** | Void once, then Race Master review |
| DSQ | `DSQ` | yes | no | 0 | field + 1 (and the DSQ rate) | loses to any classified car | last place | Missed | Failed |
| DNS | `DNS` | no | no | 0 | not counted | **never a comparison** | not counted | Void | Race Master review |
| Not run | `Not Run` | no | no | 0 | not counted | not counted | not counted | Void | Race Master review |

* **Auto** suggests Finished (a position was entered) or Not run; an explicit choice is never overwritten.
* Only the Race Master can tick **No fault** (and only on a DNF).
* Engine 2 rounds don't offer *Classified*.

### Grand Prix distance (per round)

| Setting | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 | P10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Full points (75%+) | 25 | 18 | 15 | 12 | 10 | 8 | 6 | 4 | 2 | 1 |
| 50–75% | 19 | 14 | 12 | 9 | 8 | 6 | 5 | 3 | 2 | 1 |
| 25–50% | 13 | 10 | 8 | 6 | 5 | 4 | 3 | 2 | 1 | – |
| Two laps–25% | 6 | 4 | 3 | 2 | 1 | – | – | – | – | – |
| No points | – | | | | | | | | | |
| Manual | points typed per driver (0–50) | | | | | | | | | |

Sprint: 8-7-6-5-4-3-2-1 for a classified Sprint finish, only if `sprint_distance ≥ sprint_min_distance`
(league setting, default 50%). Fastest lap and Driver of the Day: 0 points.

---

## 2. Championship countback

Drivers **and** constructors: most points → most classified P1 → most P2 → … every position → most qualifying P1 →
P2 → … → name (visual fallback only). In a Future-only season countback applies once a Version 3 round is complete
(choosing Future-only never reorders the table on its own).

---

## 3. Car strength

```
rating rank  = order of the season's car ratings (ties: default team order)
AI evidence  = every AI Grand Prix entry before the round: classified -> position / field; DNF/DSQ -> 1.0;
               DNS / not run excluded; Sprints and players never count
observed rank= teams ordered by average percentile (teams with no evidence keep their rating place)
m            = min(12, the team's AI entries)
score        = (6 x rating rank + m x observed rank) / (6 + m)
effective rank = teams ordered by score (ties: rating rank)
```
* A team with two human drivers has no AI evidence: m = 0, it keeps its rating rank.
* **Stored per round** (`round_ranks`) from the rounds *before* it, when the round is first completed; later
  evidence never re-judges an old round.
* Expected finish `E = 2r − 0.5`, scaled by `field / (2n)` when the round's field isn't two cars a team.
* New-team ratings are clamped 50–99.

---

## 4. Racecraft

`g = qualifying − finish`; `g > 0: g × (field + 1 − finish) / field`; otherwise `g × 0.4`.
Only classified results with both positions.

---

## 5. Form (1–100)

Window: the six most recent **started** rounds, weight `0.82^age` (age 0 = newest).
```
midpoint = (field + 2) / 2
F = weighted mean(midpoint − race perf. position)       (see the truth table)
Q = weighted mean(midpoint − qualifying position)        (rounds with a qualifying position)
rates = weighted share of the window: win, podium, pole, fastest lap, DOTD, DSQ
RC = clamp(0.6 × weighted mean racecraft, −6, +12)

Form = 50 + 2.0 F + 1.0 Q + 8 win + 4 podium + 2 pole + 1 FL + 1 DOTD − 5 DSQ + RC   (clamp 1–100, 1 dp)
```
No usable results: 50. Same driving gives the same Form whatever the calendar length (tested: P5/Q5 every round →
71.0 with 5, 10 or 24 rounds; P22/Q22 → 20.0; P1/Q1 → 97.0).

## 6. Car-adjusted and head-to-head

`car-adjusted = clamp(50 + 4 × weighted mean(E_round − classified finish), 1, 100)` over the same window, with each
round's stored rank. One shared head-to-head engine: both must have started; classified beats unclassified; both
classified → lower position wins; two non-finishers, DNS and equal positions don't count. Three comparisons are
needed before it's used anywhere.

## 7. Reputation

```
h2h rating   = 50 (fewer than 3) else clamp(50 + (win% − 0.5) × 20, 40, 60)
performance  = 0.55 Form + 0.35 car-adjusted + 0.10 h2h rating
confidence   = min(1, starts / max(5, 0.35 × season rounds))
Reputation   = clamp(start + confidence × 0.25 × (performance − start), 1, 100)
```
Drivers who don't race keep their entering Reputation. At rollover (full Version 3 seasons) pledge + team goal
modifiers are added together and kept within ±4:

| | Met / kept | Missed |
|---|---|---|
| Team goal Safe / Competitive / Ambitious | +1 / +2 / +3 | 0 / −1 / −2 |
| Pledge Steady / Solid / Strong / Breakout | +0.5 / +1 / +1.75 / +2.5 | 0 / −0.5 / −1 / −1.5 |

Up to 10% of a season's rounds (rounded down) of verified no-fault retirements are left out of pledge pace.

## 8. Market score, Driver Value, interest

```
market score = 0.8 Reputation + 0.2 Form
Driver Value = 0.5 market + 0.3 Form + 0.2 car-adjusted + clamp((win% − 0.5) × 8, −4, 4)  [3+ comparisons]
team bar     = 86 − 4.2 (r − 1)
interest     = Driver Value − bar      (+ current team: clamp((relationship − 60) / 5, −8, +6))
```
No automatic +3, no "happy team always wants you". Relationship 60 → +0; 30 → −6; 80 → +4; 90+ → +6; 20 → −8.

## 9. Transfer market

* Rookies: up to 3 guaranteed offers from the 5 slowest eligible teams (unchanged).
* Experienced drivers: teams with interest ≥ 0 (with ±3 jitter) make offers; **no unconditional last chance or
  lifeline**. One *emergency offer* (No. 2, 1 year, Strong pledge, final) only when Driver Value ≥ slowest eligible
  team's bar − 8, the team has an open seat, hasn't released the driver / walked out / rejected them this window,
  and interest ≥ −6. Otherwise the driver can finish the window **Unsigned** and becomes a **Free Agent**
  (keeps Reputation); signing again → **Returning Driver**; stepping in for a dismissed driver → **Mid-season
  Replacement** (the Race Master picks them on Grid & contracts).

## 10. Negotiation and messages

* Every counter costs ≥ 1 patience (greedy 2; a poor message +1). A message that lands well (score ≥ 0.35) adds
  one patience point once per offer. At most 3 counters per offer. Patience never resets.
* Messages: only the two strongest themes count; repeated keywords don't stack; a bare keyword list (no sentence
  of 5+ words with 2+ ordinary words) scores 0. Message + interview effect together: ±5.

## 11. Relationship (0–100)

```
pace part  = clamp((pledged finish − pace) / max(0.6, 0.12 (E − 1)) × 6, −30, +30)
h2h part   = clamp((win% − 0.5) × 10, −5, +5)          [3+ comparisons]
goal part  = Σ Met +2 · On track 0 · Behind −3 · Not evaluated 0
extras     = clamp(Σ last six weekends: press × 50% (re-rated) + weekend targets + ruled team orders, −10, +10)
confidence = min(1, completed / max(3, 0.3 × rounds))
score      = clamp(60 + confidence × (pace + h2h + goals) + extras, 0, 100)
```
Bands 80 Delighted · 55 Happy · 40 Concerned · 25 Unhappy · below Seat at risk. Meeting expectations exactly → 60.

## 12. Season goals (set at the start, reset once after round 3, then frozen)

* Ranks 1–4: points in `ceil(rounds × 0.75 / 0.70 / 0.60 / 0.50)` races.
* Rank 5+: finish `P clamp(floor(E − 1), 10, field − 2)` or better in `ceil(rounds × 0.30)` races
  (22 cars: r5 P10, r6 P10, r7 P12, r8 P14, r9 P16, r10 P18, r11 P20).
* Championship: P`min(20, 2r + 1)` or better.
* Teammate (No. 1: > 50%; Equal: ≥ 50%) needs 3+ comparisons, else *Not evaluated*; zero never counts as Met.
* Future-only seasons keep their existing goals.

## 13. Team goals

Chosen target frozen when chosen. Cap: `target ≤ earned + floor(0.90 × max remaining)` where max remaining =
Σ remaining (25 + 18) + remaining Sprints (8 + 7). A position target past P1 is clamped to P1 and kept as a route.
Progress: points still needed, per remaining weekend, **Secured** (points reached), **Impossible** (points out of
reach and no position route); position routes are decided at the end of the season.

## 14. Weekend targets

Safe ≥ Standard ≥ Stretch in difficulty, always. Teammate targets are read as `E`, "beat both <slower team>" as
`E(r+1) − 1.5`; if the order can't be guaranteed the three become positional (Standard `p`, Safe `p+3`, Stretch
`p−3`). Effects: Safe +1/−0.5, Standard +2/−1.5, Stretch +3.5/−2.5. No-fault DNF → Void.

## 15. Ultimatums

`target = min(field − 2, round_half_up(E + 2))` (never "just finish"; ranks 9–11 → P20). Met / Failed as in the
truth table; failed and review outcomes go to the Race Master (no automatic dismissal). The Race Master may switch
an issued ultimatum to "finish ahead of your teammate".

## 16. Team orders

Issued only from half-way, to a No. 2 whose teammate leads by 10+ points and is top 5 or has an open team goal
(40% chance if those hold). Never inferred from the finishing order: the Race Master rules Obeyed (+1), Ignored
(−2), Not actionable (0) or Void (0).

## 17. Press

Effects count 50%. Honest assessments are re-rated to 0 ("the car will struggle here", "it's a stretch with this
car", "enough talking, let's race", "just showing what we could have done", "about time, frankly", "we should be
further up the road", "only if the team keeps developing the car"); two public criticisms go −2 → −1. The
fastest-lap answer is now "Every tenth matters when you're chasing performance."

## 18. AI difficulty tracker

Per player per session (Grand Prix; Sprint as its own half-weight sample):
```
finish     = clamp((E − finish) / 8)            quali pos = clamp((E − qualifying) / 8)
teammate   = clamp((benchmark finish − finish) / 10)   benchmark: AI teammate, else AI cars one rank either
             side (confidence × 0.8), else the car's E
race pace  = clamp(−(gap / laps) / 0.60)        quali pace = clamp(−(my time − benchmark time) / 0.80)
score      = 0.20 finish + 0.10 quali pos + 0.25 teammate + 0.30 race pace + 0.15 quali pace
             (re-normalised over the parts that exist; championship points never used)
```
Session weights: excluded for Do not track, not run, cancelled/postponed, DNF, damage, major penalty, mechanical,
disconnection (the Race Master can keep one at 50% by marking it representative, or exclude any session);
weather / safety car / strategy 25%; traffic 75%; Sprint 50%.

Recommendation: last 10 usable sessions, weight `0.5^(age/2.5)`, dead band ±0.08, per-player level
`AI used + clamp(soft(score) × 25, ±15)`, verdict ±1 level, mean × 0.5 when players disagree, × confidence
`w/(w+0.75)`. Step limits: 1 weekend ±3; 2–3 ±4; 4+ ±6; a clean session > 0.45 s/lap off (with qualifying or
finishing agreeing) allows 5; three extreme sessions in a row allow 8. **Reversal:** after one opposite session at
most 1 level; two in a row normal; three strong (|score| ≥ 0.25) normal with no damping. Each player gets a
personal sweet spot (half-life 12 sessions); the shared value is their average. Constants: `AI_*` in
`constants.py` (0.80 s and 0.60 s/lap are tunable once real data is in).

### AI examples (slowest car, E = P21.5)

| Situation | finish | quali | teammate | race pace | score | one session says |
|---|---|---|---|---|---|---|
| P22, Bottas P21, 2 s behind over 50 laps | −0.06 | −0.06 | −0.10 | −0.07 | **−0.075** | inside the dead band → hold |
| P22, Bottas P17, 30 s behind over 50 laps | −0.06 | −0.06 | −0.50 | −1.00 | **−0.52** | −11 levels (step capped: 3 → up to 5 clean) |
| P15, 20 s ahead of Bottas (P21) | +0.81 | +0.69 | +0.60 | +0.67 | **+0.68** | +15 levels (capped by the step limit) |
| P22, positions only, Bottas P21 | −0.06 | −0.06 | −0.10 | – | −0.08 | hold |
| Wet-race win (flagged weather) | | | | | | counts 25%: much smaller rise than a clean win |

P22 alone is never proof: what matters is the gap to the teammate and comparable cars.

---

## 19. Worked examples by car rank (22 cars, 24 rounds, 6 Sprints)

| | Rank 1 | Rank 6 | Rank 11 |
|---|---|---|---|
| Expected finish E | P1.5 | P11.5 | P21.5 |
| Team bar | 86.0 | 65.0 | 44.0 |
| Season goal | points in 18 races | P10 or better in 8 races | P20 or better in 8 races |
| Championship goal | P3 | P13 | P20 |
| Solid pledge target | P1.4 | P10.2 | P19.0 |
| Pledge "unit" | 0.60 | 1.26 | 2.46 |
| Ultimatum target | P4 | P14 | P20 |
| Team goal cap (from 0) | 1009 of 1122 points available | same | same |

## 20. Calendar length (5 / 10 / 24 rounds)

| | 5 rounds | 10 rounds | 24 rounds |
|---|---|---|---|
| Points goal, ranks 1–4 | 4, 4, 3, 3 | 8, 7, 6, 5 | 18, 17, 15, 12 |
| Finishing goal races (rank 5+) | 2 | 3 | 8 |
| Relationship confidence reaches 1 after | 3 rounds | 3 rounds | 7.2 rounds |
| Reputation confidence reaches 1 after | 5 starts | 5 starts | 8.4 starts |
| Form, P5/Q5 every round | 71.0 | 71.0 | 71.0 |
| Reputation from 45 with performance 64.8 (Form 70, car 60, 4–2 h2h) | 50.0 | 50.0 | 50.0 |

---

## 21. Database changes (schema 20 → 21)

New tables: `season_calc`, `calc_migrations`, `round_ranks`, `pace_inputs`, `ai_recs`.
New columns: `results.no_fault`, `results.points_override`, `results.sprint_points_override`,
`events.gp_distance` (default `full`), `events.sprint_distance` (default 100), `events.cancelled`,
`drivers.career_status`, `team_orders.ruled_by / ruled_at / reason`, `team_goals.position`, `ultimatums.kind`
(default `position`). All defaults are neutral: an upgraded league calculates exactly as before. A
`before-v21-upgrade` backup is written automatically.

## 22. Migration design

* **Mandatory screen** for the Race Master of any league still on engine 2 (`calc_choice = pending`); drivers never
  see it.
* **A. Full recalculation:** backup (`before-calc-v3`) → preview inside a SQLite savepoint that is rolled back
  (tested: the database is byte-for-byte unchanged) → before/after for every player driver (points, position,
  Form, Reputation, Driver Value, relationship and band, warning level, season goals, team goal, team interest,
  contract/market status, final warning, AI recommendation, personal AI sweet spot) → explicit confirmation →
  engine 3 for the active season: stored ranks rebuilt round by round, season goals re-set at the designated reset,
  team-goal rewards to the Version 3 table, targets re-judged, relationship reviews, team orders already judged from
  positions go to "Awaiting ruling", AI recommendation rebuilt round by round. Contracts and completed transfers stay.
  Nobody is dismissed: a driver at "Seat at risk" becomes a Race Master review. One personalised notice per affected
  driver (none for unaffected drivers), which they must agree to.
* **B. Future only:** cutoff = last completed round; frozen values (Form, Reputation, Driver Value, relationship,
  warning, interest per team, car ranks, AI recommendation, season goals, team goals, pledges); rounds ≤ cutoff keep
  the Version 2 car ranks. Nothing changes on choosing. After each new round the numbers move from the frozen value
  toward the Version 3 value by `completed rounds after cutoff / 6`. The AI recommendation stays frozen until the
  first usable Version 3 session; older sessions keep their Version 2 score as legacy evidence. Next season is
  fully Version 3.
* **C. Later:** stays on engine 2; a hideable reminder for the Race Master.
* Stored for each update: versions, option, cutoff, before and after values, approver, time, backup name;
  acknowledgements (with time) are in `impact_acks`.

## 23. Rollback

1. Calculation Update page → the update → tick the box → **Roll back this update**. The league is restored from that
   update's own backup; the state just before rolling back is backed up too (`before-restore`).
2. Or: League settings → Data & tools → Backups & data → restore the `…-before-calc-v3` backup.
3. Whole release: redeploy the previous commit (2.4.1, `7db863e`). Older code ignores the new tables and columns, but
   to get each league back exactly as it was, restore its `…-before-v21-upgrade-…` backup.

## 24. Test results

369 automated tests pass (full suite, including the browser tests). Every test written before 2.5 runs on
engine 2 and still passes unchanged, which is the proof that Version 2 seasons are reproducible. 37 new tests in
`tests/test_v250.py` cover section 24 of the brief:

never auto-migrated · new leagues on Version 3 · preview mutates nothing · backup before commit · full
recalculation rebuilds the season · only affected drivers notified, with accurate values matching the preview ·
notice shows arrows and must be agreed · Version 2 history reproducible after a migration · rollback · Future-only
preserves cutoff values and waits for new evidence · classified retirement keeps points · reduced distance, manual
points, Sprint minimum · Version 2 rounds don't offer Classified · full countback · every .5 boundary · car-strength
blend, two-player teams stable, old rounds keep their ranks · calendar length doesn't inflate Form · Reputation
rises and falls · DNS never a teammate loss · zero comparisons never complete a goal · relationship 60 → no bonus,
On track doesn't inflate · lower-team goals achievable · team goals never exceed available points, rank 1–2
Ambitious reachable · target difficulty ordered · rank 10–11 ultimatums need P20 · no-fault Void once then review ·
team orders ruled not inferred, press halved · experienced drivers can end unsigned, rookies start · negotiation
limits and message rules · AI: close P22/P21 holds, 30 s deficit a meaningful decrease, moves after one weekend,
ahead of the teammate in the slowest car goes up, damage/mechanical excluded, one outlier can't reverse it far,
personal sweet spots separate, Sprints half weight, wet win barely moves it · Iron Man rule · every league page
renders on a Version 3 league.

Also run: the full-season, multi-account simulation (24 + rollover, every role) with 0 issues; a league built with
the deployed 2.4.1 code opened with 2.5 (schema 21, backup written, standings/relationships/AI identical, Race Master
sent to the choice).

## 25. Screenshots

`docs/v2.5/`: `migration_choice.png`, `recalculation_preview.png`, `migration_done.png`, `driver_change_notice.png`
(and `_phone`), `round_v3_results.png`.
