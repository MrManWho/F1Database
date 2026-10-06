# The 4.0 test site

A separate copy of Paddock Legacy for building and trying 4.0 while the live site keeps running your season.

- **Code:** the `release-4.0` branch. The live site stays on its own branch; fixes made there are copied here too.
- **Hosting:** a second Render web service (Free plan) built from `release-4.0`, with the environment variable
  `F1_TRACKER_TEST_SITE=1`. That switch shows a TEST SITE banner on every page and makes sure nothing is ever sent
  (no emails, Discord posts or phone alerts), whatever the settings or imported data say.
- **Data:** its own, separate from the live site. On the Free plan it's forgotten when the service restarts or sleeps.

## Setting it up in Render (once)

1. Render dashboard → **New** → **Web Service** → this GitHub repository → branch **`release-4.0`**.
2. Language **Python 3**, build command `pip install -r requirements.txt`, start command `python server.py`,
   instance type **Free**. No disk.
3. **Environment**: add `F1_TRACKER_TEST_SITE` = `1`, `F1_TRACKER_SETUP_CODE` = a code you make up, and
   `PYTHON_VERSION` = `3.11.9`. Don't add any mail (SMTP) settings.
4. Create the service. When it's live, open its address, enter the setup code and create a site owner account.

## Trying 4.0 on a copy of your real leagues

1. On the **live** site: Account → Settings → *Encrypted backup to keep somewhere else* → download.
2. On the **test** site: Account → Settings → *Load the live site's leagues* → choose the file, enter its passphrase,
   type REPLACE. Then sign in with your **live** username and password.
3. Nothing goes back to the live site. Load it again whenever the test site has restarted.

## Checking which leagues still use Calculation Version 2 (4.0 Phase 0)

After loading the live backup: Account → Settings → *Calculation engine scan* (`/settings/engine-scan`). It reads every
league file without changing anything and says whether any **active** season still uses Version 2. If one does, the
Version 2 code stays until that season finishes; otherwise Version 2 can be retired from new calculations.

## Trying the end of a season

Account → Settings → *Try a season finale* adds a fictional league with only its last round left, with you as Race
Master driving Player One. Enter that round, then Seasons → start the new season to try the rollover.

## Resetting the test site from a command line

The free service forgets its data on restart. With a shell (locally, or a paid instance), and only when
`F1_TRACKER_TEST_SITE=1` is set:

    python -m f1tracker.testsite seed                  a fictional league with eight played rounds
    python -m f1tracker.testsite final-round [login]   a fictional league with only its last round left
    python -m f1tracker.testsite import backup.plbk    load a live-site backup (passphrase prompt, or
                                                       F1_TRACKER_BACKUP_PASSPHRASE)
    python -m f1tracker.phase0 scan                    the engine scan as text

## Release day

When the season is over, `release-4.0` is merged into the live branch and pushed. The live site updates to 4.0
(with a backup first, and players agree to any change to their numbers). The test site can then be deleted in Render.
