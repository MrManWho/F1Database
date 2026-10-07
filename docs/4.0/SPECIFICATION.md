# Paddock Legacy 4.0 — Test Website Rebuild Specification (corrected)

**Recommended era name:** **THE NEXT GENERATION**  
**Versions:** 4.0–4.x  
**Era line:** *The same career universe, rebuilt to be clearer, safer and ready to last.*

**Status:** Controlling specification for the private test website, corrected in Phase 0  
**Source baseline:** Paddock Legacy v3.1.2  
**Calculation baseline:** Calculation Engine 3  
**Production rule:** The existing v3 site remains the authoritative live website until every 4.0 release gate in this document passes.

> **Phase 0 corrections.** This copy replaces the original planning specification. The changes are listed in
> section 15: the owner's decisions (platform, database, substitutions, retirements, testing, browsers, timing) and
> three places where the original text described Engine 3 incorrectly. Those three are corrections to the
> *description*, not formula changes: 4.0 keeps Engine 3 exactly as v3.1.2 calculates it.

---

## 1. What 4.0 should be

Paddock Legacy 4.0 should be a genuine platform and usability release, not another pile of features. It should preserve the career simulation that already works while rebuilding the experience around four promises:

1. **Nothing important is lost.** Every meaningful feature from v1.2 through v3.1.2 either has full parity or is deliberately retired with written approval.
2. **The simulation remains trustworthy.** Calculation Engine 3 produces the same results from the same inputs. Website version 4.0 must not silently become Calculation Engine 4.
3. **The site feels simpler despite its depth.** A new driver can always tell what to do next; an experienced Race Master can still reach every advanced control.
4. **Operations become production-grade.** Migrations, queues, backups, audit trails, permissions and recovery are designed into the new platform rather than added later.

### What 4.0 is not

- It is not an excuse to rewrite formulas while rebuilding screens.
- It is not a public replacement for v3 during early development.
- It is not complete because the pages look similar.
- It is not complete if only the happy path works.
- It is not a new league with manually recreated data.
- It is not permission-safe if controls are merely hidden in the interface; every permission must be enforced by the server or platform data rules.

### Where it is built (decided in Phase 0)

4.0 is built inside the existing Python codebase on the `release-4.0` branch, deployed only to the separate test
service. It reuses the Engine 3 modules and the existing automated tests. It is not rebuilt on another platform.

---

## 2. Non-negotiable test-site rules

### P0 — Required from the first build

- [ ] Create 4.0 as a **separate, private test application** with its own database, file storage, secrets and URL.
- [ ] Do not connect it to the live v3 production database.
- [ ] Do not send real email, push notifications or Discord messages in test mode. Route them to a delivery preview or approved test recipients.
- [ ] Do not change, deploy, push to or write into the current production site as part of the rebuild.
- [ ] Use fictional/demo data first. Import a sanitized production snapshot only after the importer is ready and approved.
- [ ] Display a permanent **TEST WEBSITE** banner and environment badge.
- [ ] Give every environment a unique name: local, 4.0 test, staging and production.
- [ ] Keep all secrets server-side. Never put database service keys, encryption keys, webhook values or email credentials in browser code.
- [ ] Record the exact v3 source version and schema version used for every migration test.
- [ ] Keep an export path back to a documented neutral format until 4.0 has proven itself.
- [ ] The free test service loses its data when it restarts. Keep a repeatable seed/import command so the test environment can be restored quickly (section 15, S5).

---

## 3. Formula freeze and versioning

The **formula freeze** means that a season which starts on one calculation engine finishes on that engine. UI changes and bug fixes may ship, but Formula, Reputation, Driver Value, relationships, offers, targets, goals, contract interest, team development and AI recommendations do not change underneath the players.

### Required 4.0 behavior

- [ ] Store a `calculation_engine_version` on every league season.
- [ ] Import existing v3 leagues as Engine 3 without recalculating them.
- [ ] Make Engine 3 a named, isolated calculation module rather than formulas scattered across pages and actions.
- [ ] Given identical league state and identical actions, 4.0 Engine 3 must match v3.1.2 outputs exactly, including rounding.
- [ ] Never recalculate historic seasons automatically because the application was upgraded.
- [ ] If a future Engine 4 is designed, offer Race Masters two explicit options:
  - **Future only:** current history stays unchanged; the new engine begins at a chosen future boundary.
  - **Recalculate:** preview every affected driver and team value, back up first, require typed confirmation, apply atomically, and issue private before/after notices to affected drivers.
- [ ] Log engine changes with actor, date, old version, new version, scope and reason.
- [ ] A mid-season engine change should be blocked by default. If an exceptional migration is allowed, it requires a preview, league-wide warning and acknowledgement.

### Engine 2 (decided in Phase 0)

- [ ] Phase 0 scans every live league and season for the engine it uses.
- [ ] Historical Engine 2 seasons continue to display exactly as they do today.
- [ ] If an active season still uses Engine 2, its calculation code stays until that season finishes.
- [ ] No new season may begin on Engine 2.
- [ ] Once no active season uses Engine 2, historical values are kept but Engine 2 is retired from new calculations.

### Engine 3 balance rules that must remain true

- Racing performance is the main driver of career outcomes.
- Sustained underperformance has meaningful consequences even if the player chooses safe targets and polite answers.
- Players can fail, lose a seat and enter a season as a reserve.
- One poor season does not make an experienced driver permanently unemployable.
- Beating a teammate is never punished.
- There is no universally best press-answer pattern or contract pitch.
- Low-risk choices prevent unnecessary damage but cannot steadily manufacture elite status.
- AI difficulty can move in both directions, moves cautiously on mixed evidence and never jumps wildly.

---

## 4. Complete feature-parity inventory

Every item below requires one of four recorded statuses in the build tracker: **Not started, In progress, Verified parity, Approved retirement**. “We forgot it” is not an acceptable status.

### 4.1 Accounts, identity and account safety

- [ ] One site-owner bootstrap flow using a setup code.
- [ ] Self sign-up, sign-in, sign-out and persistent sessions.
- [ ] Email confirmation code with expiry, resend limit and attempt limit.
- [ ] Forgotten-password links with expiry and single use.
- [ ] Password confirmation, show/hide, Caps Lock warning, clear requirements and double-submit protection.
- [ ] Optional authenticator-app two-step sign-in.
- [ ] Signed-in device list; end one session or all other sessions.
- [ ] Login lockouts that protect an account without letting one user on a shared IP lock everyone out.
- [ ] Site-owner account recovery by exact username or email without displaying a global account directory.
- [ ] Owner password reset that signs out existing sessions and forces a password change on next login.
- [ ] Owner ability to change an email, reset two-step sign-in, unlock an account, sign it out or delete only the login.
- [ ] Reserved legacy usernames and verified reclaim behavior.
- [ ] Account deletion, personal-data download and privacy/terms pages.
- [ ] Account preferences including light/dark theme and comfortable/compact density.
- [ ] No dangerous upgrade routine that wipes all logins.

### 4.2 Leagues, membership and roles

- [ ] Multiple leagues per account.
- [ ] League Library with pin, reorder and hide preferences.
- [ ] League switcher and season picker.
- [ ] Roles: Race Master, Scorekeeper, Member/Driver and Spectator.
- [ ] Driver assignment remains separate from role assignment.
- [ ] A league always retains at least one Race Master.
- [ ] View-as modes for authorized previews without changing actual permissions.
- [ ] Server-side authorization for every route/action regardless of visible UI.
- [ ] Join modes: requests enabled, invite only and closed.
- [ ] Join requests with desired role and Race Master approval/change/decline.
- [ ] Invitations and ownership handover.
- [ ] Leave-league behavior with safe handling of the final Race Master.
- [ ] Members & roles using exact usernames and showing “not signed up yet” for reserved members.
- [ ] Private, Public and Listed visibility.
- [ ] League profile: description, region, platform, schedule, rules, links and accessible accent color.
- [ ] Public directory, reporting and site-admin delisting.
- [ ] Public pages expose submitted information only and never private career or account data.

### 4.3 League setup and configuration

- [ ] Welcome experience for signed-out and new users.
- [ ] Guided league wizard covering basics, calendar, scoring, players, roles, notifications, visibility and review.
- [ ] Quick-create flow for experienced Race Masters (the v3 site-admin quick form becomes this flow; it is not deleted).
- [ ] Presets and a private disposable demo league.
- [ ] Searchable, grouped settings with clear league-wide versus site-wide scope.
- [ ] Time-zone setting applied consistently to dates, race windows, calendars and notifications.
- [ ] Feature switches for team orders, press, weekend targets, mid-season dismissals, race-night check-in, comments, predictions, public results, team goals and notifications.
- [ ] No setting should erase history without a preview and explicit confirmation.

### 4.4 Calendar and race-weekend lifecycle

- [ ] Editable calendar with Grands Prix and Sprint weekends.
- [ ] Month view and `.ics` subscription/export.
- [ ] Race-time states: not scheduled, scheduled, countdown, starting soon/in progress, results pending, completed and postponed.
- [ ] Consistent display in the league’s time zone.
- [ ] Clash and out-of-order warnings.
- [ ] Completed-round numbers locked except for logged historical-correction mode.
- [ ] Round gates for required press answers and accepted targets, with reminders and a logged Race Master override.
- [ ] Race-night check-in and post-race story.
- [ ] Race comments and reactions.
- [ ] Predictions for pole, winner, fastest lap and top player driver, with correct race-time locking and season standings.
- [ ] Open actions remain completable when a Race Master legitimately opens the next round early.
- [ ] Weather per session (added in v3.1) and its statistics.

### 4.5 Results entry and correction

- [ ] Qualifying, Sprint and Race session tabs.
- [ ] Fastest Lap, Driver of the Day and DNF/DNS/DSQ states.
- [ ] Search, filters, copy order, quick tap-to-order and keyboard operation.
- [ ] Clear one driver or a whole session with confirmation.
- [ ] Undo and a visible last-edited state.
- [ ] Autosave with Saving, Saved, Offline queued, retry, restore and conflict states.
- [ ] Conflict resolution showing both values; never silently overwrite another editor.
- [ ] Scorekeepers can edit only permitted open/reopened rounds.
- [ ] Submitted rounds remain locked and do not repeat reactions, headlines or notifications when corrected.
- [ ] Final review showing podium, player outcomes, statuses, AI difficulty and blocking/warning validation.
- [ ] Server-side validation for position gaps, missing required results, invalid status/position combinations and AI tracking choice.
- [ ] Race Master correction mode with clear recalculation scope.
- [ ] Move results between drivers with preview, typed confirmation, backup and unchanged constructor attribution where intended.
- [ ] Browser-based screenshot OCR: images remain local; crop/straighten/contrast; multi-image merge; confidence; ambiguous-name handling; session and status detection; editable comparison; explicit apply.

### 4.6 Standings, statistics and records

- [ ] Driver and constructor standings, including custom scoring and Sprint scoring.
- [ ] Current-season progress and submitted-round filtering.
- [ ] Statistics: points progression, finishing distribution, qualifying versus race, Sprint results, teammate head-to-heads, reliability and season-over-season player results.
- [ ] Player-only filtering.
- [ ] Rivalry comparison between any two drivers.
- [ ] Season-long teammate battles across seat changes, with qualifying, race and points views.
- [ ] Human-versus-human teammate indicator.
- [ ] Driver profiles: photo, number, nationality, helmet color, bio, trophy cabinet, contract history, career totals and trends.
- [ ] Team profiles: current drivers, seasonal car ratings/results, historic drivers and transfer news.
- [ ] Hall of Records, champions, streaks, comebacks and awards.
- [ ] Provisional labels before a season is complete.
- [ ] Persistent player colors distinct from team colors.
- [ ] Accessible charts with non-color cues, readable tooltips, keyboard access and data-table equivalents.
- [ ] Shareable result cards without exposing private details.

### 4.7 Career calculations and progression

- [ ] Form, Reputation, Racecraft, Car-Adjusted performance, Driver Value and Market Tier.
- [ ] Correct handling of Sprints, statuses, teammate comparisons, new drivers and partial seasons.
- [ ] Per-round change breakdowns and sparklines.
- [ ] Driver Value breakdown and distance to market tiers.
- [ ] Recalculation tools must state which engine is being used and show a preview.
- [ ] Team development and winter car-rating changes.
- [ ] Season review awards and career history.
- [ ] Multi-season continuity for retired drivers, reserves, free agents and drivers without current standings.
- [ ] No progression merely for elapsed seasons; opportunities must respond to performance, value, team need, contract state and history.

### 4.8 Team relationships, pledges, goals and pressure

- [ ] Team relationship out of 100 with understandable status bands.
- [ ] Separate display of performance contribution, goals/targets, press, orders and admin adjustments.
- [ ] Relationship press bonus cap: favourable press answers add no more than +2 in total across the window of the latest six completed rounds **plus the upcoming round's pre-race press**. Unfavourable answers count in full. *(Corrected in Phase 0: the window includes the upcoming pre-race press, as Engine 3 has always calculated it.)*
- [ ] Some press questions have no positive answer; preferred responses may depend on context.
- [ ] Applied v3 press effect—not a legacy raw value—appears in history.
- [ ] Weekend target choices retain the v3 trade-offs: Safe +0.25/−0.75, Standard +1.5/−1.25, Stretch +3/−2.
- [ ] Targets adapt to car pace, recent form and role; unrealistic backmarker targets are prevented.
- [ ] Voids and not-at-fault rulings work correctly and corrections re-judge outcomes.
- [ ] Target streak headlines remain supported.
- [ ] Growth pledges remain car-adjusted, re-base after early evidence and drop the worst weekend where applicable.
- [ ] Steady pledge rollover reward remains neutral under v3.
- [ ] Selectable team goals and season goals remain understandable and settle exactly once.
- [ ] Safe team-goal reward remains +0.5 under v3.
- [ ] Team orders modes Off, Advisory and On behave exactly as documented; Off removes/undoes relevant effects without corrupting unrelated history.
- [ ] Warnings, final one-race ultimatums, Race Master adjudication and mid-season release remain available when enabled.
- [ ] Consistent underperformance can outweigh safe off-track choices and eventually put a seat at risk.

### 4.9 Contracts and the driver market

- [ ] Rookie Draft, Silly Season and Race Master-opened transfer windows.
- [ ] Driver Value-based offers with car strength, form, reputation, car-adjusted results and teammate evidence.
- [ ] Seat status, contract duration, role/status and growth pledge.
- [ ] Negotiations, counters, team mood, patience, final offers and collapsed talks.
- [ ] Approaching teams with limits, trial offers and last-chance lifelines.
- [ ] Teams honor active multi-year contracts unless the driver is released.
- [ ] Renewal behavior responds to relationship and performance.
- [ ] Team-specific preferences in pitches and interviews; no universal keyword-stuffing strategy.
- [ ] Only the first two detected positive pitch themes count; stuffing incurs a penalty.
- [ ] Interview questions and goals use prior-season evidence.
- [ ] Market overview stays informational and does not mutate the grid.
- [ ] Grid & contracts correctly labels current, upcoming, expiring, expired, historical and seated-elsewhere states.
- [ ] No driver can simultaneously have contradictory seat/contract states.
- [ ] Released drivers retain results and Reputation and are labeled correctly.
- [ ] A driver can become a reserve, recover later and remain employable after a difficult year.

### 4.10 AI difficulty tracker

- [ ] Record difficulty per round or an explicit “do not track” decision.
- [ ] Every usable tracked round contributes; recent rounds weigh more.
- [ ] Evaluate each player driver independently before combining league evidence.
- [ ] Strong player agreement moves the recommendation more. When the evidence is mixed (at least one player struggling and at least one comfortable), the calculated adjustment is **halved**. *(Corrected in Phase 0: Engine 3 halves the step; it does not specifically move toward the struggling player.)*
- [ ] Benchmarks in order: the teammate; otherwise AI cars one car-strength place either side (0.8 confidence); otherwise two places either side (0.7); otherwise the car's expected finish (0.6).
- [ ] Step limits exactly as Engine 3: at most **3** AI levels with one usable weekend of evidence, **4** with two or three, **6** with four or more; up to **5** when the latest session was a clean session more than 0.45 s a lap off; up to **8** after three extreme sessions in a row in the same direction. A reversal after only one opposite session moves at most one level. The step is also scaled by evidence confidence (weight ÷ (weight + 0.75)). *(Corrected in Phase 0: the original text said ±1, or ±2 at confidence 0.7 or higher. That was never Engine 3's rule; the 0.8/0.7/0.6 figures are benchmark confidences, not step caps. Any change to AI movement is an Engine 4 balance decision and must be simulated separately.)*
- [ ] No recommendation should make a large unexplained jump.
- [ ] Show evidence, sample size, confidence, fallback reason and each relevant driver’s signal.
- [ ] Being ahead of a teammate must be represented as evidence that the player may be outperforming the car; it is never treated as a failure.
- [ ] Allow the Race Master to accept, modify or ignore a recommendation while recording the actual chosen value.

### 4.11 News, incidents and communication

- [ ] Paddock News with category, round, driver/team context and links.
- [ ] Transfer stories, relationship messages, target streaks and relevant career events.
- [ ] Incident reports with Race Master rulings and linked rivalry/history effects.
- [ ] Announcements by role with schedule, expiry and recipient-count previews.
- [ ] In-app notifications with unread state, mark all read and hide cleared/read items per user.
- [ ] Per-league notification preferences and mute.
- [ ] Separate email and push category choices.
- [ ] Every outgoing message identifies its league.
- [ ] One-click league-only unsubscribe.
- [ ] Discord webhook configuration and safe test action.
- [ ] Durable delivery queue for email, Discord and push.
- [ ] Retry with deduplication and loop/rate protection.
- [ ] Delivery log records type, time, state and count without exposing recipients or secret values.
- [ ] Test mode captures delivery previews instead of sending externally.

### 4.12 Control Room, personal pages and navigation

- [ ] Role-aware Control Room.
- [ ] “Waiting for you” list for offers, pledges, press, targets, goals, join requests, incidents, seat problems and pending results.
- [ ] One clear primary next action; secondary tasks remain visible without competing for attention.
- [ ] Season progress, leaders, average AI, Sprint count, next event and projected finish.
- [ ] Driver card with relevant changes since the last submitted round.
- [ ] Dedicated Contracts & offers, Press, My progression and My settings pages.
- [ ] Race Master groups for Race weekends, Career management and League administration.
- [ ] Desktop sidebar, mobile bottom navigation and drawer.
- [ ] Search/command palette scoped to the current league.
- [ ] Every navigation label matches the page title and Help terminology.

### 4.13 Administration, audit and recovery

- [ ] Activity Log written in plain-language sentences with links and no private values.
- [ ] Immutable actor, timestamp, action, target and before/after metadata for sensitive operations.
- [ ] Site admin can manage listed leagues and delete a league only through a protected, typed-confirmation flow.
- [ ] Race Master tools for drivers, teams, seats, contracts, team goals, targets, transfer windows, news and repairs.
- [ ] High-impact confirmations explain scope, history effects, backup behavior and reversibility.
- [ ] Automatic, manual and safety backups.
- [ ] Encrypted off-site full-site backups.
- [ ] Backup reminders and last-success status.
- [ ] Restore preview, integrity validation and automatic before-restore backup.
- [ ] Restore can itself be undone.
- [ ] Downloaded SQLite-compatible backups, if still offered, are rebuilt/compacted so removed secret bytes cannot remain in unused pages.
- [ ] JSON/neutral export excludes secrets by construction.
- [ ] Standings CSV export.
- [ ] Full-site integrity checker and seat/contract repair tools.
- [ ] No two backups overwrite one another because of filename timing.

### 4.14 Installability, offline behavior and accessibility

- [ ] Installable PWA behavior and icons.
- [ ] Offline banner and safe queued result edits.
- [ ] Unsaved-work warnings.
- [ ] Responsive operation at 360 px without page-level sideways scrolling.
- [ ] Scrollable tables within their cards, with sticky headers and names where helpful.
- [ ] WCAG 2.2 AA target for core pages.
- [ ] Skip link, landmarks, logical headings, visible focus, keyboard operation and reduced motion.
- [ ] Programmatic names for every icon-only button, comment field, repeated action and color control.
- [ ] Touch targets large enough for phones.
- [ ] League accent colors automatically adjusted or rejected when contrast is insufficient.
- [ ] Accessible status communication that does not depend only on color.

---

## 5. The actual 4.0 improvements

Parity recreates Paddock Legacy. The following improvements justify calling the rebuild 4.0.

### 5.1 A clearer information architecture

Build around five player-facing destinations:

1. **Home** — next action, next race, current standing and urgent notices.
2. **Race Weekend** — schedule, check-in, predictions, target, results and summary.
3. **Career** — progression, team relationship, contracts, press and goals.
4. **Championship** — standings, statistics, drivers, teams and records.
5. **Paddock** — news, incidents, announcements and community features.

Race Masters gain a clearly separated **Manage League** area. Scorekeepers receive only the results tools and context they need. Spectators see clean read-only pages rather than disabled forms.

### 5.2 A real design system

- [ ] Define reusable tokens for color, type, spacing, radius, elevation, motion and breakpoints.
- [ ] Define standard components for cards, tables, tabs, forms, banners, toasts, dialogs, stat changes, empty states and status pills.
- [ ] Use one vocabulary for statuses and actions across every page.
- [ ] Create loading, empty, error, offline, locked and permission-denied states for every core component.
- [ ] Use progressive disclosure: essential action first, explanation next, calculation details expandable.
- [ ] Keep destructive controls visually and spatially distinct from routine actions.
- [ ] Add a consistent “Why did this change?” panel for calculated values.
- [ ] Validate every component in light and dark themes, compact and comfortable density, desktop and mobile.

### 5.3 Guided complexity for new players

- [ ] Replace the old general tour with a three-stage onboarding: account/league, first race, first career decision.
- [ ] Give each role a short checklist that disappears as tasks are learned.
- [ ] Explain terms at the point of use, not only in Help.
- [ ] Show advanced settings only when requested.
- [ ] Provide recommended defaults with a one-sentence consequence.
- [ ] Make the Control Room usable without understanding every career formula.
- [ ] Add a demo story that lets a user complete one race-weekend loop safely.

### 5.4 Explainable simulation

Every calculated number should answer four questions:

- What changed?
- Why did it change?
- Which rules/version were used?
- What can the player influence next?

The explanation layer must use the actual calculation output, not reimplement formulas in template text. It should expose inputs and applied effects without revealing private choices belonging to other drivers.

### 5.5 Production-grade data behavior

- [ ] Use a transactional database: **one SQLite database per league plus the site database** (S1). The service layer is kept clean enough that a managed relational database (for example Postgres) remains possible later.
- [ ] League isolation: each league is its own database file, and every route checks the league role on the server.
- [ ] Wrap weekend submission, rollover, recalculation, transfer completion and restore in transactions.
- [ ] Give repeated requests idempotency keys so retries cannot double-apply points, notices or messages.
- [ ] Scheduled/background work runs through the **durable outbox with an in-process scheduler** (S2): deliveries, cleanup, reminders and backups.
- [ ] Keep durable job state, retry counts and dead-letter/error inspection.
- [ ] Store uploaded assets on the service's **persistent disk** with authorization and safe file types, with encrypted off-site backups kept (S3).
- [ ] Use schema migrations with forward and rollback plans.
- [ ] Add health checks, structured logs and an **owner error dashboard** (S4). A free hosted error tracker may be added later; no paid service.
- [ ] Add rate limits to sign-in, confirmation, password reset, public reports, invitations and message-producing actions.

---

## 6. Answers to the four career-design questions for 4.0

### Can players still manipulate relationships?

Under v3 rules, obvious farming is substantially reduced, but 4.0 must prove it with simulation rather than assumption. Safe targets and polite answers may stabilize a borderline relationship; they must not override months of poor results. Build automated adversarial strategies—always-safe, always-team-friendly, pitch keyword stuffing and conservative pledge selection—and verify that persistent underperformance can still lead to warnings, release and a lost seat.

### Is career progression too predictable?

It should not be. Time served alone must not create a ladder to the fastest team. Offers need to depend on current and historic performance, Driver Value, car-adjusted results, team fit, openings, contract state and recent trajectory. At the other extreme, prior achievement and recoverable form must keep a veteran’s path back open after one bad season. Test both “average driver plays forever” and “champion has one terrible year” scenarios.

### Are there meaningful decisions outside the races?

Each decision needs a genuine trade-off rather than a correct button:

- Safer targets offer protection but limited upside.
- Ambitious targets offer meaningful upside and meaningful miss cost.
- Press responses should sometimes trade team approval against honesty, confidence or public perception.
- Pledges should influence the contract package and future expectation.
- Contract choices should trade team pace, role, security and required growth.
- Interviews and pitches should depend on team identity and career evidence.

The UI should preview the nature of a risk without revealing every hidden threshold.

### Does the website remain manageable for new players?

It can, if depth is layered. A new driver’s first screen should show no more than the next required action, next race and essential career status. Detailed breakdowns, historic charts and admin tools stay one level deeper. The usability test is simple: a first-time driver should be able to join, understand their role, accept a target, make a prediction, answer press and find the race result without reading the full Help system.

---

## 7. Migration design

### Required importer behavior

- [ ] Accept the documented v3.1.2 full-site/league export format (the encrypted `.plbk` site backup).
- [ ] Validate file type, checksum, schema version and required tables before writing anything.
- [ ] Show a dry-run report: accounts, leagues, seasons, rounds, drivers, results, contracts, notifications, assets and warnings.
- [ ] Map every source identifier to a new identifier deterministically and retain a migration map.
- [ ] Preserve timestamps, season boundaries, result status and calculation-engine version.
- [ ] Never send notifications as a side effect of importing history.
- [ ] Never recalculate imported history unless explicitly selected after import.
- [ ] Import into a new empty target or an isolated migration workspace.
- [ ] Make the final commit atomic: all required data imports, or none of it does.
- [ ] Produce reconciliation counts and critical totals before and after.
- [ ] Preserve a read-only copy of the source export and the migration report.

### Not migrated (decided in Phase 0)

- Expired password links, sessions, rate-limit history, old delivery queues and other temporary security data.
- Old backup files: 4.0 starts a fresh backup history, and the original migration archive is kept.
- Old notification rows may be left behind; **notification preferences do migrate**.
- No player-facing career, race, statistics, community or administration feature is retired without separate approval.

### Reconciliation checks

- League/member/role counts.
- Seasons, calendar rounds and submitted-round counts.
- Every qualifying, Sprint and Race classification.
- Driver and constructor points by round and season.
- Form, Reputation, Driver Value and relationship histories.
- Seats, contracts, offers, transfer windows and team goals.
- Press, weekend targets, pledges, team orders and incidents.
- News, announcements and activity entries.
- Notification preferences—not necessarily old ephemeral notification rows if deliberately retired.
- Public/private/listed visibility and public sharing identifiers.
- Avatars and permitted assets.

### Driver-facing migration notices

If a migration changes no calculations, say so plainly. If a separately approved recalculation changes values, each driver receives a private notice containing old value, new value, reason, engine version and acknowledgement. Never show one driver another driver’s private notice.

---

## 8. Verification plan and release gates

### 8.1 Golden-master formula parity

Create fixed v3.1.2 fixtures and run the same actions in v3 and 4.0. Compare exact outputs for:

- standings and scoring;
- Form, Reputation, Racecraft and Driver Value;
- market tier, interest, offers and contract outcomes;
- relationships, press caps, targets, goals, pledges and team orders;
- AI difficulty evidence, confidence, fallback and recommendation;
- corrections and recalculation;
- rollover and multi-year contract/seat state.

No unexplained numeric difference passes.

### 8.2 Simulation and adversarial balance tests

- [ ] Run at least 1,000 deterministic multi-season simulations across car strengths, player skill levels, statuses and strategic choices.
- [ ] Include always-safe, always-aggressive, always-positive-press and keyword-stuffing strategies.
- [ ] Verify that a severely underperforming driver can fail despite optimal off-track choices.
- [ ] Verify that a high performer in a weak car can progress.
- [ ] Verify that grinding seasons with average/poor performance does not guarantee a top seat.
- [ ] Verify that a strong veteran can recover after one difficult season.
- [ ] Verify that relationships do not trivially converge to 100.
- [ ] Verify that target and contract choices produce more than one viable strategy.
- [ ] Record distributions, not just individual examples.

### 8.3 Workflow tests

- [ ] Sign-up, email verification, recovery, two-step sign-in, lockout and owner recovery.
- [ ] All roles and every unauthorized-action denial.
- [ ] League creation, joining, invitation, handover and leaving.
- [ ] Full race weekend with Sprint and without Sprint.
- [ ] Offline save, conflict, reconnect, submit, reopen and correct.
- [ ] Round gate and Race Master override.
- [ ] Transfer windows, negotiations, interview, pitch, signing and release.
- [ ] Final warning and mid-season dismissal.
- [ ] Season rollover with every seat/contract state.
- [ ] Restore, undo restore, import and export.
- [ ] Queue retry, deduplication, failure inspection and safe replay.

### 8.4 Nonfunctional gates

- [ ] Automated accessibility scan has zero serious/critical violations on every core page.
- [ ] Entire core workflow is keyboard-operable and screen-reader reviewed.
- [ ] 360 px phone, tablet and desktop layouts pass visual review.
- [ ] Supported browser matrix passes: Chrome and Edge on Windows, Safari on iPhone, Chrome on Android, Firefox on Windows (secondary), and the installed app (PWA) on iPhone, Android and Windows. Core functionality works from 360 px to desktop widths.
- [ ] No secrets appear in client bundles, logs, exports or downloaded backups.
- [ ] Permission tests attempt direct API access, not only UI clicks.
- [ ] Concurrency tests cover simultaneous result edits and submissions.
- [ ] Load tests cover expected league/user volume with stated headroom.
- [ ] Backup restore is demonstrated from a fresh environment.
- [ ] The old rollover instability test passes at least 100 fresh-process repetitions; the new system also completes a longer soak.
- [ ] Error reporting (owner error dashboard) and operational alerts are proven in the test environment.

### 8.5 Human acceptance gates

- [ ] A new driver completes the first-race journey without coaching (someone who has never used Paddock Legacy).
- [ ] A returning driver finds every regular v3 task (existing players test the normal driver and Race Master workflows).
- [ ] A Scorekeeper enters and submits results efficiently on a phone.
- [ ] A Race Master creates a season, fixes a result, runs a transfer window, previews rollover and restores a backup.
- [ ] Existing league data is reconciled and signed off by the Race Master.
- [ ] A documented NVDA/VoiceOver walkthrough is completed (a real screen-reader user if one is available).
- [ ] No P0 or P1 issue remains open.
- [ ] Production cutover and rollback have both been rehearsed.

---

## 9. Recommended build order

### Phase 0 — Freeze and map

- Freeze v3.1.2 as the behavioral reference.
- Create a route, feature, data-table and permission inventory.
- Create golden fixtures and expected calculation outputs.
- Scan every league and season for the calculation engine it uses.
- Decide which platform services own database, authentication, storage, jobs and email (decided: section 15).

**Exit:** Every v3 feature and source data entity has an owner and intended 4.0 destination.

### Phase 1 — Foundation

- Environments, secrets, database migrations, authentication, authorization, league isolation, audit log and design-system shell.

**Exit:** Security tests pass; no career calculations yet.

### Phase 2 — Championship core

- Leagues, seasons, calendar, drivers, teams, results, scoring, standings, corrections and exports.

**Exit:** Golden scoring parity and full race-weekend workflow pass.

### Phase 3 — Career engine

- Engine 3 module, Formula, Reputation, Driver Value, relationships, targets, pledges, goals, contracts, market, team development and AI tracker.

**Exit:** Golden calculation parity and adversarial simulations pass.

### Phase 4 — Community and operations

- News, incidents, announcements, comments, predictions, notifications, durable jobs, backups, restores, public pages and administration.

**Exit:** Delivery, security, restore and role tests pass.

### Phase 5 — Migration and shadow season

- Importer, reconciliation reports, sanitized production rehearsal and parallel shadow operation.

**Exit:** Several real weekends can be entered into both sites with matching outputs and acceptable usability.

### Phase 6 — Release candidate

- Bug-only stabilization, accessibility review, load/security testing, support documentation, cutover rehearsal and rollback rehearsal.

**Exit:** All release gates signed off. Only then may the site be considered for production after the chosen season boundary.

---

## 10. Priority list

### P0 — 4.0 cannot launch without it

- Full scoring and Calculation Engine 3 parity.
- Correct accounts, roles, league isolation and server-side permissions.
- Full race-entry, correction and rollover safety.
- Contracts, seats, relationships, goals, targets and AI tracker parity.
- Validated migration with reconciliation and rollback.
- Durable delivery queue, off-site encrypted backups and tested restore.
- Mobile core workflow and WCAG 2.2 AA core-page compliance.
- No secret leakage and no production writes from test.
- Automated test coverage plus human acceptance.

### P1 — Expected in the complete 4.0 experience

- Full public/listed league experience.
- Complete statistics, records, rivalries and rich profiles.
- Screenshot OCR parity.
- PWA/offline queueing and robust edit conflicts.
- Guided onboarding, command palette and new information architecture.
- Polished notification center, delivery log and announcements.
- Full activity/audit views and advanced repair tools.

### P2 — May follow in 4.x without delaying a safe cutover

- New cosmetic themes beyond existing light/dark behavior.
- Additional share-card styles.
- Deeper optional analytics that do not affect calculations.
- Nonessential animations and personalization.
- Entirely new simulation systems not present in v3.1.2.

---

## 11. Specific non-regression list from the v2.5 audit

The earlier audit findings are mostly fixed in v3.0–3.1.2. They become permanent 4.0 tests:

- [ ] Downloaded backups cannot contain deleted webhook or secret text in raw bytes.
- [ ] Press gains are capped and safe off-track choices cannot overwhelm underperformance.
- [ ] Contract pitches are team-specific and stuffing is penalized.
- [ ] AI fallback reaches the documented car-performance benchmark with the documented confidence.
- [ ] Help and in-context explanations match the actual engine.
- [ ] Press history displays the applied Engine 3 effect.
- [ ] Repeated controls have proper accessible names.
- [ ] Steady pledge and Safe team-goal rewards cannot create excessive low-risk Reputation drift.
- [ ] Rollover cannot leave a player without a valid intended seat because of timing or order-dependent behavior.
- [ ] Multi-year released drivers cannot end in contradictory contract and seat states.
- [ ] Driver change notices are visible only to that driver and authorized administrators.
- [ ] Queued deliveries survive process restarts and do not double-send.
- [ ] Login lockouts behave safely for shared networks.

---

## 12. Changelog presentation for 4.0

Add this separator above the first 4.0 entry:

> **THE NEXT GENERATION**  
> **Versions 4.0–4.x**  
> *The same career universe, rebuilt to be clearer, safer and ready to last.*

The 4.0 release entry should not claim “everything is new.” It should explain continuity:

- the existing career and Engine 3 rules are preserved;
- the interface and platform are rebuilt;
- leagues can be migrated with a preview and reconciliation report;
- v3 remains available during the controlled transition;
- the release focuses on trust, usability, accessibility and long-term reliability.

---

## 13. Master brief (corrected)

```text
Build Paddock Legacy 4.0 as a separate private test application from the existing Python
codebase, on the release-4.0 branch, using the corrected "Paddock Legacy 4.0 — Test
Website Rebuild Specification" as the controlling document.

The current production baseline is Paddock Legacy v3.1.2. Do not edit, deploy to, write
to, or connect the test application to production. Use a separate database, storage,
secrets, URL and delivery configuration. Display a permanent TEST WEBSITE banner.

This is a parity-first platform and UX rebuild. It is not permission to redesign the
career formulas. Website v4.0 must use Calculation Engine 3, reusing its modules. Store
the engine version per season and reproduce v3.1.2 outputs exactly from the same inputs,
including rounding, correction and rollover behavior. Never recalculate imported history
by default. Any future Calculation Engine 4 must be a separate, explicit project with a
preview, version boundary and migration choice.

Platform (approved substitutions): one SQLite database per league plus the site database;
the durable outbox with an in-process scheduler for background work; files on the
persistent disk with encrypted off-site backups; structured logs, health checks and an
owner error dashboard. No new paid services.

Implementation rules:
- Enforce permissions and league isolation on the server/data layer, not only by hiding UI.
- Keep secrets out of client code, logs, exports and downloaded backups.
- Use transactions for weekend submission, recalculation, transfers, rollover and restore.
- Use idempotency and a durable queue so retries cannot double-apply effects or messages.
- Use schema migrations; do not make untracked manual production data changes.
- Give every calculated value a "Why did this change?" explanation generated from actual
  engine output.
- Build mobile-first at 360 px and meet WCAG 2.2 AA on all core workflows.
- Use progressive disclosure so a new driver sees the next required action before advanced
  statistics or formulas.
- Create complete loading, empty, offline, error, locked and permission-denied states.
- Capture all email, push and Discord deliveries in a test preview; send nothing real.

Preserve the v3.0 balance protections as regression requirements:
- favourable press effects capped at +2 across the latest six completed rounds plus the
  upcoming round's pre-race press; unfavourable answers count in full;
- not every question has a positive answer and preferences may be contextual;
- weekend targets: Safe +0.25/-0.75, Standard +1.5/-1.25, Stretch +3/-2;
- contract pitch uses only the first two positive themes and penalizes stuffing;
- Steady pledge rollover reward is neutral;
- Safe team-goal reward is +0.5;
- AI tracker exactly as Engine 3: mixed evidence halves the adjustment; step limits 3 / 4 / 6
  by usable weekends (1 / 2-3 / 4+), 5 after an extreme clean session, 8 after three extreme
  sessions in a row in one direction; one-session reversals move one level; benchmarks
  teammate, then AI cars one place either side (0.8), two places (0.7), then the car's
  expected finish (0.6).

Work in the six phases in section 9. At the end of every phase, update the parity matrix,
list tests run and results, show screenshots of the affected mobile and desktop workflows,
identify unresolved risks, and stop for approval before the next phase.

Definition of done:
- all P0 items are verified;
- every legacy feature is marked Verified parity or Approved retirement;
- golden-master Engine 3 results match exactly;
- migration reconciliation matches critical counts and totals;
- adversarial and multi-season simulations pass;
- permissions, secrets, accessibility, mobile, concurrency, delivery and restore tests pass;
- production cutover and rollback are rehearsed;
- no P0 or P1 defect remains open.
```

---

## 14. Final recommendation

Call this 4.0 only if it delivers the rebuilt foundation, exact Engine 3 compatibility, controlled migration, clearer role-based interface and proven operational safety. A visual redesign on its own is 3.x. A few new career systems on the current architecture are also 3.x. The combination of full parity, a durable new platform, explainable calculations and a significantly simpler experience earns **Paddock Legacy 4.0 — The Next Generation**.

After production launch, freeze new features for at least one complete championship cycle. During that period, ship only security fixes, data-loss prevention, severe correctness fixes and small usability corrections that do not alter career balance. Collect larger ideas for 4.1 or a separately designed Calculation Engine 4.

---

## 15. Phase 0 decisions record

### Approved substitutions

| # | Area | Decision |
|---|---|---|
| S1 | Database | One SQLite database per league plus the site database. The service layer stays clean enough for a later move to Postgres. |
| S2 | Background jobs | The durable outbox with the in-process scheduler. |
| S3 | Files | Files stay on the service's persistent disk; encrypted off-site backups are kept. |
| S4 | Monitoring | Structured logs, health checks and an owner error dashboard. A free hosted error tracker can be added later. |
| S5 | Test persistence | The free test site; re-import after restarts during early development, with a repeatable seed/import command. A paid persistent disk is reconsidered only at the final migration rehearsal, or if resets materially slow development. |

### Decisions

1. **Where to build:** the existing Python codebase, `release-4.0` branch. Not rebuilt elsewhere.
2. **Database:** per-league SQLite (Option A).
3. **AI tracker:** (superseded for new seasons by the owner's later decision below: the track-aware recommendation) the real v3 limits, exactly; the specification text is corrected (4.10). Any change is an Engine 4 decision with its own simulation.
4. **Engine 2:** see section 3, "Engine 2".
5. **Timing:** production cutover at the start of Season Two, never mid-season. No calendar deadline: if 4.0 hasn't passed every P0 release gate by the Season Two boundary, v3 stays in use and migration waits.
6. **Human testing:** two existing players test the normal driver and Race Master workflows; a third person who has never used Paddock Legacy does the first-time-driver test without coaching; a documented NVDA/VoiceOver walkthrough (a real screen-reader user if available).
7. **Browsers and devices:** section 8.4.
8. **Retirements:** section 7, "Not migrated"; the site-admin quick form becomes the Race Master quick-create flow (4.3); Engine 2 is not offered for new seasons (section 3).
9. **Test-site persistence:** S5.

### Owner decision after Phase 1: the track-aware AI recommendation (approved change)

The owner replaced the AI tracker for 4.0 with a simpler, track-aware model (`f1tracker/ai_track.py`, model
`track-aware-1`). It applies to **new leagues and to each new season**; a season already under way keeps the v3
tracker until it finishes (formula freeze). Section 4.10's v3 rules stay true for those seasons and for the golden
fixtures, which remain the v3.1.2 reference.

- One recommended AI for the whole weekend; no separate qualifying/Sprint/race settings; no Time Trials or personal
  baseline.
- `recommended_ai = F1Laps track baseline + learned league adjustment + optional personal track history`.
- Baselines: a versioned local snapshot of F1Laps' F1 26 averages (game, source, source date, dataset and model
  versions, a value per circuit). No live connection; updated by adding a snapshot. Historic recommendations are
  frozen with the snapshot they used.
- League adjustment starts at 0, learned from completed weekends (each player judged separately against teammate,
  car and realistic finish, then combined; agreement moves more, mixed little or none). Caps: ±2 after one weekend,
  ±3 after two aligned weekends, ±4 after three or more. Track-to-track baseline changes are not capped.
- DNF, DNS, DSQ, major incidents and no-fault results give no negative evidence; wet and disrupted races count less;
  beating a teammate is never negative.
- Personal track history: zero influence before a visit, growing with repeated visits, capped at ±3.
- The AI actually used is recorded separately from the recommendation. A warning shows when two players' own levels
  differ by more than six.

### Corrections to the original text (documentation only, not formula changes)

- **4.10 AI step limits:** the original said ±1, or ±2 at confidence ≥ 0.7. Engine 3 uses 3 / 4 / 6 by usable weekends, 5 for an extreme clean session and 8 after three extreme sessions in a row.
- **4.10 mixed evidence:** the original said it moves "toward the struggling player". Engine 3 halves the calculated adjustment.
- **4.8 and 13, press cap window:** the window is the latest six completed rounds **plus** the upcoming round's pre-race press.
