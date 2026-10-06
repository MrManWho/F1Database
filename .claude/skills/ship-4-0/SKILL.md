---
name: ship-4-0
description: Release the current local work as the next 4.0 beta - version bump, CHANGELOG and admin guide entries, tests, commit, and (after the user confirms) push to release-4.0. Use when the user says ship, push, release or "make it a beta".
---

# Ship the next 4.0 beta

Pushing `release-4.0` redeploys the 4.0 test site (its data resets). Never push to `claude/gifted-lovelace-iqzlxy`,
the live site, whatever the user says here: live releases are done separately.

1. **Check the state.** Run `git status`. Commit or set aside nothing yet. If the work is on another local branch,
   tell the user and ask whether to bring it into `release-4.0` (`git switch release-4.0`, then `git merge <branch>`).
2. **Bring in work pushed from elsewhere.** `git pull origin release-4.0`. Cloud Claude sessions push here too. If it
   conflicts, resolve it keeping both sides' intent, and explain what you did.
3. **Stop for formulas.** If the changes alter calculations, standings, career numbers or golden fixtures
   (`calc3.py`, `tests/golden`, docs/CALCULATION_V3.md), stop and ask the user to approve that change first.
4. **Version.** In `f1tracker/constants.py`, bump `APP_VERSION` to the next beta (4.0.0-beta.N+1).
5. **CHANGELOG.md**, a new entry at the top in the same shape as the entries below it:
   `## 4.0.0-beta.N · <short title> (test site)`, `_Released <Month D, YYYY>_`, a one- or two-line `>` summary,
   `### Highlights` (plain-language bullets about what players and Race Masters will notice, bold lead words), and
   `### Nothing changed in` (formulas, standings, career numbers, permissions, league data, as true).
6. **docs/ADMIN_GUIDE.md**: a `## 4.0.0-beta.N: <title>` section at the top with the technical detail (files,
   settings, migrations).
7. **Test on Python 3.11.** `.venv\Scripts\python -m pytest -q` takes several minutes. Everything must pass. Fix
   failures, but never skip or weaken a test.
8. **Show the user** the version, the Highlights and `git diff --stat`, and ask: "Push 4.0.0-beta.N to release-4.0?
   This redeploys the 4.0 test site."
9. **Commit**, staging only code and docs (`.devdata`, `.venv`, backups and `.plbk` files are ignored; check
   `git status` shows nothing unexpected). Message: `4.0.0-beta.N: <title>`.
10. **Push only after the user says yes:** `git push origin release-4.0`. Report the commit hash, and say the test site
    rebuilds in a few minutes and needs its test data added again.
