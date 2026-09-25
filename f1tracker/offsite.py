"""Encrypted site backups to keep somewhere else (v3.0).

The automatic backups live on the same disk as the data, so they protect against mistakes but not against losing
the disk or the hosting account. The site owner can download one encrypted file holding every league and the
accounts database and keep it anywhere (a USB stick, a cloud drive, email to themselves). It's encrypted with a
passphrase only the owner knows, so the file is safe to store on a service they don't fully trust.

File format (.plbk): MAGIC, 16-byte salt, 12-byte nonce, then AES-256-GCM ciphertext of a zip. The key comes from
the passphrase with scrypt (n=2^15, r=8, p=1). The zip holds accounts.db, careers/*.f1career and manifest.json
(file names, sizes and SHA-256). secret.key is not included: after a restore everyone just signs in again.

Decrypt on any computer with Python and the `cryptography` package:
    python -m f1tracker.offsite decrypt paddock-legacy-backup.plbk restored.zip
"""

import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .storage import CAREER_EXT, careers_dir, data_dir, now_iso

MAGIC = b"PLBK1\n"
MIN_PASSPHRASE = 12
SETTING = "offsite_backup_at"
REMIND_AFTER_DAYS = 14


class BackupError(Exception):
    pass


def _key(passphrase, salt):
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _copy(path):
    """A consistent copy of a live SQLite file (the backup API, so a write in progress can't tear it)."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src, dst = sqlite3.connect(str(path)), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    with open(tmp, "rb") as fh:
        data = fh.read()
    os.unlink(tmp)
    return data


def build_archive():
    """A zip of accounts.db and every league file, with a manifest."""
    files = {}
    accounts = data_dir() / "accounts.db"
    if accounts.exists():
        files["accounts.db"] = _copy(accounts)
    for p in sorted(careers_dir().glob(f"*{CAREER_EXT}")):
        files[f"careers/{p.name}"] = _copy(p)
    manifest = {"format": "paddock-legacy-site-backup", "version": 1, "created_at": now_iso(),
                "files": [{"name": n, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return out.getvalue(), manifest


def encrypt(data, passphrase):
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise BackupError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters")
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob, passphrase):
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 28 + 16:
        raise BackupError("This isn't a Paddock Legacy encrypted backup")
    body = blob[len(MAGIC):]
    salt, nonce, ct = body[:16], body[16:28], body[28:]
    try:
        return AESGCM(_key(passphrase or "", salt)).decrypt(nonce, ct, MAGIC)
    except Exception:
        raise BackupError("Wrong passphrase, or the file is damaged")


def verify(zip_bytes):
    """Check every file against the manifest. Returns the manifest."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        manifest = json.loads(z.read("manifest.json"))
        for f in manifest["files"]:
            if hashlib.sha256(z.read(f["name"])).hexdigest() != f["sha256"]:
                raise BackupError(f"{f['name']} doesn't match its checksum")
    return manifest


def make(passphrase):
    """(encrypted bytes, manifest) for the site owner to download, and remember when it was made."""
    from . import auth
    archive, manifest = build_archive()
    blob = encrypt(archive, passphrase)
    auth.set_setting(SETTING, now_iso())
    return blob, manifest


def last_made():
    from . import auth
    return auth.get_setting(SETTING)


def overdue():
    from datetime import datetime
    stamp = last_made()
    if not stamp:
        return True
    try:
        return (datetime.fromisoformat(now_iso()) - datetime.fromisoformat(stamp)).days >= REMIND_AFTER_DAYS
    except ValueError:
        return True


def _main(argv):
    import getpass
    if len(argv) != 4 or argv[1] != "decrypt":
        print("usage: python -m f1tracker.offsite decrypt <backup.plbk> <out.zip>")
        return 2
    with open(argv[2], "rb") as fh:
        blob = fh.read()
    data = decrypt(blob, getpass.getpass("Passphrase: "))
    manifest = verify(data)
    with open(argv[3], "wb") as fh:
        fh.write(data)
    print(f"OK: {len(manifest['files'])} files, made {manifest['created_at']}. Unzip it into an empty data folder "
          f"(F1_TRACKER_DATA_DIR) to restore.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
