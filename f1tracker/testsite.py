"""The 4.0 test site (release-4.0 branch): a separate copy of the website for trying new features safely.

Switched on with the environment variable F1_TRACKER_TEST_SITE=1 on the test site's hosting only. Then:
  * every page shows a TEST SITE banner;
  * nothing is ever sent: no emails, Discord posts or phone alerts, whatever the settings say (imported leagues
    may carry real Discord webhooks and real players' addresses);
  * the site owner can load an encrypted site backup from the live site (Account -> Settings), to try new features
    on a copy of the real leagues. Nothing flows back to the live site.

The free test service forgets its data when it restarts. To set it up again (4.0 Phase 0):
    python -m f1tracker.testsite seed                 add a fictional league with a played season
    python -m f1tracker.testsite final-round [login]  add a fictional league with only its last round left
    python -m f1tracker.testsite import backup.plbk   load a live-site backup (asks for its passphrase, or reads
                                                      F1_TRACKER_BACKUP_PASSPHRASE)
Both refuse to run unless F1_TRACKER_TEST_SITE=1, so they can never touch the live site. On the hosted test site,
the same import is on Account -> Settings.
"""

import os
import sys
import shutil
import tempfile
import zipfile
import io

from . import offsite, storage


def on():
    return os.environ.get("F1_TRACKER_TEST_SITE") == "1"


def import_backup(blob, passphrase):
    """Replace this test site's accounts and leagues with the contents of an encrypted site backup (.plbk).
    Returns the number of leagues loaded. Raises offsite.BackupError for a wrong passphrase or damaged file."""
    if not on():
        raise offsite.BackupError("Importing a site backup is only possible on the test site")
    data = offsite.decrypt(blob, passphrase)
    manifest = offsite.verify(data)
    names = [f["name"] for f in manifest["files"]]
    if "accounts.db" not in names:
        raise offsite.BackupError("That backup has no accounts in it")
    for n in names:                     # only the files a site backup contains, never a path outside the data folder
        if n != "accounts.db" and not (n.startswith("careers/") and n.count("/") == 1 and n.endswith(storage.CAREER_EXT)):
            raise offsite.BackupError(f"Unexpected file in the backup: {n}")
    base = storage.data_dir()
    staging = tempfile.mkdtemp(dir=str(base))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in names:
                target = os.path.join(staging, n)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as fh:
                    fh.write(z.read(n))
        careers = storage.careers_dir()
        for old in careers.glob(f"*{storage.CAREER_EXT}*"):
            old.unlink()
        loaded = 0
        for p in sorted(os.listdir(os.path.join(staging, "careers"))) if os.path.isdir(os.path.join(staging, "careers")) else []:
            shutil.move(os.path.join(staging, "careers", p), str(careers / p))
            loaded += 1
        for suffix in ("-wal", "-shm"):
            extra = base / f"accounts.db{suffix}"
            if extra.exists():
                extra.unlink()
        os.replace(os.path.join(staging, "accounts.db"), str(base / "accounts.db"))
        scrub_secrets()
        return loaded
    finally:
        shutil.rmtree(staging, ignore_errors=True)


PLACEHOLDER_WEBHOOK = "https://discord.com/api/webhooks/0/removed-on-the-test-site"


def scrub_secrets():
    """4.0 Phase 1: an imported live backup brings the site's email password and each league's Discord webhook.
    The test site never sends anything, so it doesn't need them: the password is removed and each webhook is
    replaced with a placeholder (so the league still counts as "Discord on" and its posts appear as previews)."""
    import sqlite3
    from . import auth
    with auth.accounts() as conn:
        conn.execute("DELETE FROM settings WHERE key = 'smtp_password'")
    for path in storage.careers_dir().glob(f"*{storage.CAREER_EXT}"):
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("UPDATE meta SET value = ? WHERE key = 'discord_webhook' AND value != ''", (PLACEHOLDER_WEBHOOK,))
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()


def seed():
    """A fictional league with two player drivers and eight played rounds (the golden-fixture season)."""
    if not on():
        raise offsite.BackupError("Seeding is only possible on the test site (F1_TRACKER_TEST_SITE=1)")
    from . import constants as C, golden
    return golden.play(C.ENGINE_CURRENT, name="Test League (fictional)")


FINAL_ROUND_NAME = "Final Round Test (fictional)"


def seed_final_round(username=None):
    """A fictional league whose season has every round played except the last, for trying the season finale and
    the new-season rollover. username (optional) is linked as Race Master driving Player One. Returns the league id."""
    if not on():
        raise offsite.BackupError("Seeding is only possible on the test site (F1_TRACKER_TEST_SITE=1)")
    from . import auth, constants as C, golden, roles
    token = golden.play(C.ENGINE_CURRENT, name=FINAL_ROUND_NAME, rounds=-1)
    user = auth.get_user(username) if username else None
    if user:
        from . import services as S
        with storage.session(token) as conn:
            driver = S.player_drivers(conn)[0]
            roles.set_member(conn, user["username"], "race_master", driver["id"])
    return token


def _main(argv):
    import getpass
    try:
        if len(argv) == 2 and argv[1] == "seed":
            print("Added league", seed())
            return 0
        if len(argv) in (2, 3) and argv[1] == "final-round":
            print("Added league", seed_final_round(argv[2] if len(argv) == 3 else None))
            return 0
        if len(argv) == 3 and argv[1] == "import":
            with open(argv[2], "rb") as fh:
                blob = fh.read()
            phrase = os.environ.get("F1_TRACKER_BACKUP_PASSPHRASE") or getpass.getpass("Passphrase: ")
            print(f"Loaded {import_backup(blob, phrase)} leagues and every login.")
            return 0
    except offsite.BackupError as exc:
        print(exc)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
