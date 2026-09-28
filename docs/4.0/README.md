# Paddock Legacy 4.0: Phase 0 (in progress)

| File | What it is | State |
|---|---|---|
| `SPECIFICATION.md` | The corrected 4.0 specification, with the Phase 0 decisions record (section 15) | done, awaiting review |
| `ROUTES.md`, `TABLES.md`, `PERMISSIONS.md` | Inventories generated from the code by `python -m f1tracker.phase0 inventory docs/4.0` | tool written, not yet run |
| `../../tests/golden/*.json` | Golden calculation fixtures from `python -m f1tracker.golden write tests/golden` | tool written, not yet run |
| Engine 2 scan | `python -m f1tracker.phase0 scan` (read-only), and a site-owner page on the test site | tool written, page to add |
| `PHASE0_REPORT.md` | Test report | to do |

Everything here lives on `release-4.0` (the test site) only. Production is untouched.
