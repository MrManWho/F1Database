# Feature inventory and 4.0 destinations (v3.1.2 baseline)

Every v3 feature group, where it lives in 4.0 and which phase owns it. The line-by-line checklist follows; each line
starts as *Not started* in 4.0 and is only marked *Verified parity* when a test proves it.

**Legend (v3.1.2 today):** ✅ exists and works · ◐ partly there (gap noted) · ✗ not in v3 (new for 4.0).

## Destinations and owners

| Feature group (spec §4) | 4.0 destination (app map) | Built in phase |
|---|---|---|
| 4.1 Accounts, identity, account safety | Account / Site (outside leagues) | 1 |
| 4.2 Leagues, membership, roles | Manage League → People; League Library; Account / Site | 1–2 |
| 4.3 League setup and configuration | Welcome, league wizard, quick-create; Manage League → League administration | 2 |
| 4.4 Calendar and race-weekend lifecycle | Race Weekend | 2 |
| 4.5 Results entry and correction | Race Weekend → results; Manage League → Race weekends | 2 |
| 4.6 Standings, statistics, records | Championship | 2 |
| 4.7 Career calculations (Engine 3) | Career; Championship (numbers); the Engine 3 modules, reused | 3 |
| 4.8 Relationships, pledges, goals, pressure | Career | 3 |
| 4.9 Contracts and the driver market | Career → Contracts & offers; Manage League → Career management | 3 |
| 4.10 AI difficulty tracker | Race Weekend (round page); Manage League → Race weekends | 3 |
| 4.11 News, incidents, communication | Paddock; notification centre; Manage League → League administration | 4 |
| 4.12 Control Room and navigation | Home; the new shell (sidebar, bottom nav, palette) | 1 (shell), 2–4 (content) |
| 4.13 Administration, audit, recovery | Manage League → League administration; Site (owner) | 1 (audit), 4 |
| 4.14 Installability, offline, accessibility | Everywhere (design system) | 1 onward, checked every phase |
| Weather (3.1, not in the spec's list) | Race Weekend | 2 |

Data entities: see `TABLES.md` (every table with its 4.0 migration rule). Routes: `ROUTES.md`. Permissions: `PERMISSIONS.md`.

### 4.1 Accounts, identity and account safety

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Site-owner bootstrap with setup code | ✅ `/setup`, `F1_TRACKER_SETUP_CODE` | carry over |
| Self sign-up, sign-in/out, persistent sessions | ✅ server-side session records | carry over |
| Email code: expiry, resend, attempt limit | ✅ 15 min, 60 s resend, 5 tries | carry over |
| Forgotten-password link: expiry, single use | ✅ | carry over |
| Password confirm, show/hide, Caps Lock, rules, double-submit guard | ✅ `pw_field` macro + JS | carry over |
| Authenticator two-step sign-in | ✅ TOTP | carry over |
| Device list; end one / all others | ✅ | carry over |
| Lockouts safe on shared IP | ✅ 3.1.2 (address locks only across 3+ usernames) | carry over |
| Owner recovery by exact username/email, no directory | ✅ | carry over |
| Owner reset signs out + forces change | ✅ 3.1.1 | carry over |
| Owner: change email, reset 2FA, unlock, sign out, delete login | ✅ | carry over |
| Reserved usernames + verified reclaim | ✅ | carry over |
| Account deletion, data download, privacy/terms | ✅ | carry over |
| Theme and density preferences | ✅ (stored per browser) | ◐ store per account in 4.0 |
| No login-wiping upgrade routine | ✅ removed in 3.1.2, test guards it | permanent test |

### 4.2 Leagues, membership and roles

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Multiple leagues per account | ✅ | carry over |
| League Library: pin, hide | ✅ | ? reorder: verify; add if missing |
| League switcher, season picker | ✅ | carry over |
| Roles RM / Scorekeeper / Member / Spectator | ✅ | carry over |
| Driver assignment separate from role | ✅ | carry over |
| Always ≥1 Race Master | ✅ | carry over |
| View-as modes | ✅ | carry over |
| Server-side authorization everywhere | ✅ decorators on routes (`career_page`, `master_required`) | ◐ 4.0: add an automated "every route × every role" denial test |
| Join modes requests / invite / closed | ✅ | carry over |
| Join requests with role, approve/change/decline | ✅ | carry over |
| Invitations, ownership handover | ✅ | carry over |
| Leave league; last-RM protection | ✅ | carry over |
| Members & roles; "not signed up yet" | ✅ | carry over |
| Private / Public / Listed | ✅ | carry over |
| League profile + accessible accent | ✅ (text colour auto-contrasts) | ◐ reject/adjust low-contrast accents explicitly |
| Directory, reporting, delisting | ✅ | carry over |
| Public pages submitted-only, no private data | ✅ tested | carry over |

### 4.3 League setup and configuration

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Welcome for signed-out/new users | ✅ | redesign |
| Guided wizard | ✅ Essentials → Players → (More) → Ready | carry over |
| Quick-create for experienced RMs | ◐ site-admin quick form only | open to all RMs |
| Presets + disposable demo league | ✅ | carry over |
| Searchable, grouped settings; league vs site scope | ◐ grouped sub-pages; no settings search | add search |
| Time zone applied everywhere | ✅ | carry over |
| Feature switches (orders, press, targets, dismissals, check-in, comments, predictions, public, team goals, notifications) | ✅ | carry over |
| No history-erasing setting without preview | ◐ team-orders Off and resets preview; audit each switch in Phase 0 | verify all |

### 4.4 Calendar and race-weekend lifecycle

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Editable calendar, GP + Sprint | ✅ | carry over |
| Month view, `.ics` | ✅ | carry over |
| Race-time states | ✅ | carry over |
| League time zone everywhere | ✅ | carry over |
| Clash / out-of-order warnings | ✅ `_calendar_warnings` | carry over |
| Completed-round numbers locked (logged correction mode) | ✅ locked | ◐ logged historical-correction mode: verify |
| Round gates + reminders + logged RM override | ✅ | carry over |
| Race-night check-in, post-race story | ✅ | carry over |
| Comments, reactions | ✅ | carry over |
| Predictions + locking + standings | ✅ | carry over |
| Open actions stay completable when next round opens early | ✅ press stays open | carry over |
| Weather per session (3.1) | ✅ | carry over (not in spec list; keep) |

### 4.5 Results entry and correction

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Qualifying / Sprint / Race tabs | ✅ | carry over |
| FL, DotD, DNF/DNS/DSQ (+ Classified, no-fault) | ✅ | carry over |
| Search, filters, copy order, tap-to-order, keyboard | ✅ | carry over |
| Clear driver / session with confirmation | ✅ | carry over |
| Undo, last-edited | ✅ undo (Alt+Z) | ? last-edited display: verify |
| Autosave states, offline queue, retry, restore | ✅ | carry over |
| Conflict resolution showing both values | ✅ 409 + conflict dialog | carry over |
| Scorekeeper scope | ✅ | carry over |
| Submitted rounds locked; no repeat headlines on correction | ✅ `submitted_at` | carry over |
| Final review with validation | ✅ submission checklist | carry over |
| Server-side validation | ✅ | carry over |
| RM correction with recalculation scope | ✅ | carry over |
| Move results between drivers (preview, typed confirm, backup) | ✅ | carry over |
| Browser OCR (local, crop, multi-image, confidence, apply) | ✅ `importer.js`, `ocr_match.js` | carry over |

### 4.6 Standings, statistics and records

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Driver + constructor standings, Sprint scoring | ✅ | carry over |
| Season progress, submitted-only filter | ✅ | carry over |
| Statistics (progression, distribution, quali vs race, Sprint, H2H, reliability, season-over-season, wet) | ✅ | carry over |
| Player-only filter | ✅ | carry over |
| Rivalries | ✅ | carry over |
| Teammate battles across seat changes; human-vs-human mark | ✅ | carry over |
| Driver profiles (photo, number, nationality, helmet, bio, trophies, contracts, totals, trends) | ✅ | carry over |
| Team profiles | ✅ | carry over |
| Records, champions, streaks, awards | ✅ `records.html` | ? comebacks: verify |
| Provisional labels | ✅ | carry over |
| Player colours distinct from team colours | ✅ | carry over |
| Accessible charts (non-colour cues, keyboard, data tables) | ◐ tooltips/markers; no table equivalents | add table views |
| Share cards | ✅ | carry over |

### 4.7 Career calculations and progression

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Form, Reputation, Racecraft, Car-adjusted, Driver Value, Market Tier | ✅ `calc3.py` | reuse module unchanged |
| Sprints, statuses, teammates, new drivers, partial seasons | ✅ | reuse |
| Per-round breakdowns, sparklines | ✅ | carry over |
| Driver Value breakdown, distance to tiers | ✅ Garage | carry over |
| Recalculation states engine + preview | ✅ | carry over |
| Team development, winter car ratings | ✅ | carry over |
| Season review, career history | ◐ rollover review + history; no "awards night" page | 4.x candidate |
| Continuity for reserves, free agents, retirees | ✅ (3.0 fix for released multi-year) | carry over |
| No progression for elapsed time alone | ✅ (3.0 balance) | adversarial test |

### 4.8 Relationships, pledges, goals, pressure — ✅ all present in Engine 3 as of 3.0

Relationship bands; separate contribution breakdown (3.0 "How this was calculated"; admin adjustments ◐ not a separate line); press +2 cap;
neutral pre-race questions; applied press effect in history; targets +0.25/−0.75, +1.5/−1.25, +3/−2; adaptive targets;
voids / not-at-fault; target streaks; car-adjusted pledges with re-base and dropped worst weekend; Steady neutral; team
goals settle once, Safe +0.5; team orders Off / Advisory / On; warnings, ultimatums, dismissals. **4.0: reuse the Engine 3
code unchanged; add the missing admin-adjustment line.**

### 4.9 Contracts and the driver market — ✅ all present

Windows (Rookie Draft, Silly Season, RM-opened); value-based offers; seat status, length, role, pledge; negotiations,
patience, final offers, collapses; approaches, trial offers, lifelines; multi-year honoured unless released (3.0 fix);
renewals; team-specific pitches (first two themes, stuffing penalty); interviews with prior-season evidence; market
overview read-only; Grid & contracts labels; no contradictory seat/contract states (soak-tested 100 runs); released
drivers keep results and Reputation; reserves recover. **4.0: reuse unchanged.**

### 4.10 AI difficulty tracker — ✅ present, but **the spec's description differs from v3** (see §7, Q4)

Record per round or "do not track" ✅; recency weighting ✅; per-player evaluation ✅; mixed evidence halves the step ✅
(`DIFF_MIXED` 0.5; the spec says "toward the struggling player", which v3 does not do literally); fallback chain
teammate → ±1 rank (0.8) → ±2 ranks (0.7) → expected finish (0.6) ✅; **step limits in v3 are 3 / 4 / 6 by usable
weekends (5 for an extreme clean gap, 8 after three extreme sessions), not ±1 / ±2**; evidence shown ✅; ahead of the
teammate counts as outperforming ✅; RM chooses the real value ✅.

### 4.11 News, incidents and communication

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Paddock News with context | ✅ | carry over |
| Transfer, relationship, streak stories | ✅ | carry over |
| Incidents + rulings + rivalry links | ✅ | carry over |
| Announcements by role, schedule, expiry, counts | ✅ | carry over |
| Notifications: unread, mark all, clear read | ✅ | carry over |
| Per-league preferences and mute; email vs push | ✅ | carry over |
| League named in every message; one-click unsubscribe | ✅ | carry over |
| Discord webhook + test | ✅ | carry over |
| Durable queue, retry, dedupe, loop protection | ✅ 3.1.2 outbox + delivery dedupe | ◐ add dead-letter view |
| Delivery log without recipients/secrets | ✅ | carry over |
| Test mode captures previews | ◐ test site drops messages | add a "Delivery preview" page |

### 4.12 Control Room and navigation

Role-aware Control Room ✅; Waiting-for-you ✅; one primary Next action ✅ (3.0); progress, leaders, AI, Sprints, next
event ✅ (? projected finish: verify); driver card with changes since last round ✅; Contracts & offers, Press,
Progression, My settings ✅; RM groups ✅ (Race / People / Career / System; spec names differ slightly, see §4);
sidebar, bottom nav, drawer ✅; league-scoped palette ✅; labels = titles = Help terms ◐ (audit in Phase 0).

### 4.13 Administration, audit and recovery

| Item | v3.1.2 today | 4.0 note |
|---|---|---|
| Plain-language Activity Log, links, no secrets | ✅ | carry over |
| Immutable actor/time/action/target **and structured before/after** | ◐ sentences only | ✗ add structured before/after |
| Site admin league deletion with typed confirmation | ✅ 3.0.1 | carry over |
| RM repair tools (drivers, teams, seats, contracts, goals, targets, windows, news) | ✅ | carry over |
| High-impact confirmations | ✅ | carry over |
| Automatic, manual, safety backups | ✅ | carry over |
| Encrypted off-site backups + reminder | ✅ 3.0 / 3.1.2 | ◐ automatic upload needs a storage account |
| Restore preview, integrity check, before-restore backup, undoable | ✅ | carry over |
| Scrubbed SQLite downloads | ✅ 3.0 | permanent test |
| JSON export excludes secrets | ✅ | carry over |
| Standings CSV | ✅ | carry over |
| Full-site integrity checker, seat repair | ◐ per-league integrity + seat repair; no site-wide run | add |
| No backup filename collisions | ✅ | carry over |

### 4.14 Installability, offline, accessibility

PWA ✅; offline banner + queued edits ✅; unsaved-work warnings ✅; 360 px ◐ (tested at 390 px; re-test at 360); table
scroll inside cards + keyboard-focusable ✅; WCAG 2.2 AA ◐ (axe 2.1 AA clean on 44 page views; 2.2 target-size and
focus-appearance criteria not yet checked); skip link, landmarks, headings, focus, reduced motion ✅; programmatic names ✅
(3.0); touch targets ◐ verify 24×24 minimum; accent contrast ◐; status not colour-only ◐ (verify pills and charts).

**Counts:** of roughly 150 checklist lines, about 120 already exist in v3.1.2, about 25 are partial, about 5 are new
(structured audit before/after, delivery preview page, chart table equivalents, settings search, site-wide integrity run).
So 4.0 is mainly a **re-platform plus UX reorganisation**, not a feature build.
