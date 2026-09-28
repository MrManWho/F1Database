"""The 4.0 test site (release-4.0 branch): a separate copy of the website for trying new features safely.

Switched on with the environment variable F1_TRACKER_TEST_SITE=1 on the test site's hosting only. Then:
  * every page shows a TEST SITE banner;
  * nothing is ever sent: no emails, Discord posts or phone alerts, whatever the settings say (imported leagues
    may carry real Discord webhooks and real players' addresses);
  * the site owner can load an encrypted site backup from the live site (Account -> Settings), to try new features
    on a copy of the real leagues. Nothing flows back to the live site.
"""

import os
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
        return loaded
    finally:
        shutil.rmtree(staging, ignore_errors=True)
