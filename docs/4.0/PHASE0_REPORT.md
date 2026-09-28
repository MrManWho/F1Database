# 4.0 Phase 0 report: freeze and map

**Branch:** `release-4.0` (test site only) · **Baseline frozen:** v3.1.2, league schema 21, Calculation Engine 3
(`CALC_VERSION` 4) · **Production:** untouched.

## Delivered

| Deliverable | Where | How it stays true |
|---|---|---|
| Feature inventory with 4.0 destination and owning phase | `FEATURES.md` | reviewed each phase |
| Route inventory (every route, who may use it) | `ROUTES.md` | generated from the code; a test fails if a route is missing |
| Table inventory (every table, its columns and 4.0 migration rule) | `TABLES.md` | generated; a test checks every table is listed |
| Permission inventory (league capabilities + routes by access level) | `PERMISSIONS.md` | generated; a test fails if a new route has no access check |
| Golden fixtures (Engine 3 and Engine 2) | `tests/golden/*.json` | `test_v400_phase0.py` rebuilds and compares exactly |
| Engine 2 scan | `/settings/engine-scan` (site owner), `python -m f1tracker.phase0 scan` | read-only; tested |
| Corrected specification with the decisions record | `SPECIFICATION.md` | a test checks the corrected Engine 3 rules against the constants |
| Repeatable seed/import for the test site | `python -m f1tracker.testsite seed` / `import` | test-site only; tested |

Regenerate the inventories after any route or table change: `python -m f1tracker.phase0 inventory docs/4.0`.

## Findings

- **208 routes.** Race Master 76 · league member 61 · public 31 · site owner 15 · self-service (signed in, own
  account only) 14 · signed in with the check inside the view 7 · Race Master + Scorekeeper 4. No route is open to
  a signed-in person without a check except the 14 self-service pages, which the test now pins.
  *Phase 1:* turn the 7 "check inside" routes into declared access levels so the every-route × every-role test
  covers them directly.
- **Tables.** Every table has a migration rule. Not migrated (owner decision): sessions, password links, pending
  sign-ups, lockout counters, rate-limit history, the outbox. Optional: old notification rows (preferences migrate).
  Files: driver photos migrate; old backups don't (fresh history, the migration archive is kept).
- **Golden fixtures.** A fixed, seeded eight-round season (two player drivers in different cars, Sprints,
  retirements, AI difficulty recorded every round) is played through the site's own code on Engine 3 and on Engine 2. It
  records the standings, constructor standings and Driver Value after every round, the Form/Reputation timeline, and
  the stored relationships, weekend targets, team goals, car ranks and AI recommendations. The two runs are
  byte-for-byte identical, so the fixtures are deterministic.
  *Not yet covered (Phase 3, when the engine is wired into 4.0):* press answers, team orders, ultimatums, the
  transfer market, rollover and corrections. Those have their own v3 tests today; golden versions come with Phase 3.
- **Engine 2 scan.** Built and tested; it can't see the live leagues from here. **Action for you:** load a live
  backup on the test site, open Account → Settings → *Calculation engine scan*, and tell me the verdict. That decides
  whether Engine 2 code must stay until an active season ends.
- **Specification corrections** (documentation only): AI step limits 3 / 4 / 6 (5 extreme, 8 persistent); mixed
  evidence halves the step; the press window includes the upcoming pre-race press.

## Tests

- Full suite: **425 passed**, 0 failed (the 413 existing v3 tests plus 12 new Phase 0 tests), 8 min 51 s.
- `tests/test_v400_phase0.py` (12): golden Engine 3 and Engine 2 seasons match exactly; fixture coverage; the scan
  finds an active Version 2 season, reports a pending Calculation Update, handles an unreadable file and changes no
  league file; the scan page is site-owner only; every route is in the inventory; no route is open without a check
  beyond the pinned self-service list; every table has a migration rule and is listed; the corrected specification
  matches the Engine 3 constants; seeding refuses to run outside the test site.
- Determinism: the golden fixtures were generated twice and compared byte for byte (identical).

## Open risks and questions for Phase 1

1. The Engine 2 scan verdict (above) is still needed.
2. Versioning on the test branch: the site still reports v3.1.2. I suggest keeping it until the first 4.0 build
   with visible changes (Phase 1), which would then be 4.0.0-alpha builds with changelog entries.
3. The free test site loses its data on restart; after each restart, load the live backup again (or seed).

**Stopped here for your review before Phase 1.**
