# Paddock Legacy: notes for Claude Code

Flask + Jinja + SQLite F1 career league tracker. `accounts.db` holds the site and its accounts; each league is its own
`.f1career` SQLite file. Both live in one data folder (`F1_TRACKER_DATA_DIR`, see `f1tracker/storage.py`).

- **Branches:** `claude/gifted-lovelace-iqzlxy` deploys the live site (render.yaml, auto-deploy). Never push,
  merge or force-push to it. `release-4.0` is the 4.0 line and deploys the 4.0 test site. Never push anywhere
  unless the user asks for that push (.claude/settings.json makes push, merge, rebase, reset and clean ask first).
- **Local run:** `dev.bat` (Windows) or `python dev.py`, at http://127.0.0.1:5050. Local data is in `.devdata/`.
  Never point local runs at another data folder, and don't use `run.bat`/`launcher.py` (the desktop app's own saves).
  See docs/LOCAL_DEV.md.
- **Python 3.11 only.** Calculations drift on 3.12+. Tests: `.venv\Scripts\python -m pytest -q` (several minutes).
- **Don't change formulas** (calc3.py, docs/CALCULATION_V3.md) or golden fixtures (tests/golden) without the user's
  approval. Pre-4.0 leagues must keep migrating (schema.py, migration.py, tracking.py).
- Every released change gets a version (`f1tracker/constants.py` APP_VERSION) and a CHANGELOG.md entry with
  Highlights. Admin details go in docs/ADMIN_GUIDE.md.
- Specs and route maps for 4.0: docs/4.0/.
