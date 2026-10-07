# 4.0 Phase 1 report: foundation

**Branch:** `release-4.0` (test site only) · **Version:** 4.0.0-alpha.1 · **League schema:** 22 · **Production:** untouched.
**Exit criterion (spec §9):** security tests pass; no career calculations change. Both met (see Tests).

## Delivered

| Area | What | Where |
|---|---|---|
| Environments | Named environments with a badge (local / 4.0 test / staging / production) | `ops.environment()`, header badge |
| Health | `GET /healthz`: version, environment, schema, database and disk checks; 503 on failure | `ops.health()` |
| Monitoring (S4) | JSON log lines per request; owner **Site errors** page (grouped, scrubbed, counted) fed by every ERROR the site logs, including background sends | `ops.py`, `/settings/errors` |
| Test-mode delivery | Every email, Discord post and phone alert captured as a **Delivery preview** instead of dropped; no device can subscribe to the test site; imported live backups lose the SMTP password and Discord webhooks | `ops.capture`, `/settings/delivery-preview`, `testsite.scrub_secrets` |
| Authorization | Every one of the 215 routes declares its access level; the 7 routes that checked inside the view now declare it | `ROUTE_ACCESS`, inventory |
| Permission tests | Every site route called directly as anonymous, ordinary member and owner; a league Race Master gets no site powers; league routes stay covered by the every-route × every-role test | `test_v400_phase1.py`, `test_v213.py` |
| Audit | Append-only **change record** per league (before/after for members, settings, rounds; secrets masked) and for the site owner; database triggers refuse edits and deletions; a refused change leaves no record | `audit_trail.py`, schema 22 |
| Design system | Tokens (spacing, type, radius, elevation, motion, breakpoints), one **state** component for loading / empty / error / offline / locked / permission-denied, reference page `/design`; error pages use it | `app.css`, `_macros.state`, `design.html` |
| Shell | Five destinations (Home, Race Weekend, Championship, Career, Paddock) plus **Manage League** (Race weekends, Career management, League administration); bottom bar matches | `base.html` |
| Accounts | Theme and density saved to the account and applied on every device | `auth.set_preferences`, `/account/preferences` |
| Versioning | 4.0.0-alpha.1, changelog entry under the new era separator *THE NEXT GENERATION* | `CHANGELOG.md` |

Screenshots (desktop, 360 px phone, phone menu, design system) were checked; the phone page has no sideways scroll.
One layout fix came out of it: the TEST SITE banner no longer covers the top of the desktop sidebar.

## Tests

- Full suite: **449 passed**, 0 failed (425 from before plus 24 new Phase 1 tests), 8 min 38 s, browser tests included.
- `tests/test_v400_phase1.py` (24): environment names; public health check with no private data; badge hidden in
  production; JSON log lines scrubbed; page and background errors recorded, scrubbed, counted, owner-only, clearable;
  delivery preview captures every channel, masks addresses, owner- and test-site-only; a real invitation on the test
  site becomes a preview; imported backups lose the SMTP password and webhooks; **every site route × anonymous /
  ordinary member / owner**; a league Race Master gets no site powers; member changes recorded with before/after;
  settings changes recorded with secrets masked; change record can't be edited or deleted (league and site); a
  refused change leaves no record; site-owner actions recorded without passwords; an older schema 21 file upgrades
  with a backup; the five destinations and Manage League (hidden from Spectators); every design-system state
  renders; theme and density saved and applied; the permission-denied state; the version and changelog era;
  **golden Engine 3 season unchanged** (no career numbers moved).
- `tests/test_v400_testsite.py` updated: the test site now captures instead of dropping.

## Not in Phase 1 (planned)

- Idempotency keys for repeated requests, and the outbox dead-letter view: Phase 4 (operations), per the plan.
- Labels = titles = Help terms audit across every page, and WCAG 2.2 target-size / focus-appearance checks: each
  phase for the pages it rebuilds; full sweep in Phase 6.
- Settings search and the Race Master quick-create flow: Phase 2 (league setup).

## Open items for you

1. The Engine 2 scan verdict from Phase 0 (load a live backup on the test site → Account → Settings → Calculation
   engine scan) is still needed before Phase 3.
2. Try the new menu on the test site after it redeploys; tell me anything that feels misplaced.

**Stopped here for your review before Phase 2.**
