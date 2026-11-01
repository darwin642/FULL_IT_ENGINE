#!/usr/bin/env python3
"""Apply a Cartman staged restore. Stop the Cartman server before running."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DB = APP / "cartman.db"
KEY = APP / ".cartman_connector_fernet.key"
BACKUPS = APP / ".cartman-backups"
PENDING = BACKUPS / "restore-pending.json"
ID_RE = re.compile(r"^[0-9a-f]{32}$")


def fail(message):
    raise RuntimeError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_database(destination):
    source = sqlite3.connect(str(DB))
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target, pages=256, sleep=0.05)
        target.commit()
    finally:
        target.close()
        source.close()


def validate_database(path, key_present):
    connection = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            fail("SQLite integrity_check failed.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "devices" not in tables:
            fail("This is not a valid Cartman database (devices table missing).")
        if "cartman_connectors" in tables:
            count = connection.execute("SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''").fetchone()[0]
            if count and not key_present:
                fail("Encrypted connector credentials exist but the backup has no matching encryption key.")
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Apply the pending Cartman database restore.")
    parser.add_argument("--apply-pending", action="store_true", help="Apply the prepared restore package.")
    parser.add_argument("--confirm-stop", action="store_true", help="Confirm that the Cartman/Uvicorn server is stopped.")
    args = parser.parse_args()
    if not args.apply_pending or not args.confirm_stop:
        parser.error("Both --apply-pending and --confirm-stop are required.")
    if not PENDING.is_file() or PENDING.is_symlink():
        fail("No safe pending restore manifest exists.")
    if DB.is_symlink() or (KEY.exists() and KEY.is_symlink()) or BACKUPS.is_symlink():
        fail("Refusing to operate on symbolic-link paths.")
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    source_id = str(pending.get("source_backup_id") or "")
    safety_id = str(pending.get("safety_backup_id") or "")
    staged_name = str(pending.get("staged_filename") or "")
    if not ID_RE.fullmatch(source_id) or not ID_RE.fullmatch(safety_id):
        fail("Pending restore IDs are invalid.")
    if not re.fullmatch(r"cartman-restore-pending-[0-9a-f]{32}\.zip", staged_name):
        fail("Pending restore filename is invalid.")
    staged = BACKUPS / staged_name
    if not staged.is_file() or staged.is_symlink() or sha256_file(staged) != pending.get("staged_sha256"):
        fail("Staged archive is missing or its checksum changed.")
    if not DB.is_file():
        fail("Current Cartman database is missing.")
    safety_archive = BACKUPS / ("cartman-backup-" + safety_id + ".zip")
    if not safety_archive.is_file() or safety_archive.is_symlink():
        fail("The pre-restore safety backup is missing; restore was not applied.")

    with tempfile.TemporaryDirectory(prefix="cartman-restore-", dir=str(BACKUPS)) as temporary_dir:
        temp = Path(temporary_dir)
        current_snapshot = temp / "current.sqlite3"
        snapshot_database(current_snapshot)
        if sha256_file(current_snapshot) != pending.get("live_database_sha256"):
            fail("The live database changed after restore preparation. Cancel and prepare the restore again.")
        current_key_hash = sha256_file(KEY) if KEY.is_file() else None
        if current_key_hash != pending.get("live_connector_key_sha256"):
            fail("The connector encryption key changed after restore preparation. Prepare the restore again.")

        restored_db = temp / "restored.sqlite3"
        restored_key = temp / "connector_fernet.key"
        key_present = False
        with zipfile.ZipFile(staged, "r") as archive:
            names = archive.namelist()
            allowed = {"manifest.json", "cartman.db", "connector_fernet.key"}
            if len(names) != len(set(names)) or set(names) - allowed or not {"manifest.json", "cartman.db"}.issubset(set(names)):
                fail("Backup archive contains unexpected or duplicate entries.")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("backup_id") != source_id or manifest.get("format_version") != 1:
                fail("Backup manifest identity or version mismatch.")
            digest = hashlib.sha256()
            with archive.open("cartman.db") as source, open(restored_db, "wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != manifest.get("database_sha256"):
                fail("Database checksum does not match the backup manifest.")
            key_present = "connector_fernet.key" in names
            if bool(manifest.get("connector_key_included")) != key_present:
                fail("Connector-key manifest mismatch.")
            if key_present:
                key_data = archive.read("connector_fernet.key")
                if hashlib.sha256(key_data).hexdigest() != manifest.get("connector_key_sha256"):
                    fail("Connector encryption-key checksum mismatch.")
                try:
                    from cryptography.fernet import Fernet
                    Fernet(key_data)
                except Exception:
                    fail("Connector encryption key is invalid.")
                restored_key.write_bytes(key_data)
        validate_database(restored_db, key_present)

        # The service must be stopped; checkpoint any remaining WAL before swapping.
        connection = sqlite3.connect(str(DB))
        try:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and int(checkpoint[0]) != 0:
                fail("SQLite WAL checkpoint is busy; ensure Cartman is fully stopped and retry.")
        finally:
            connection.close()
        wal = Path(str(DB) + "-wal")
        shm = Path(str(DB) + "-shm")
        if (wal.exists() and wal.stat().st_size > 0) or (shm.exists() and shm.stat().st_size > 0):
            fail("SQLite WAL/SHM sidecar is still active. Stop Cartman completely and retry.")

        guard_id = uuid.uuid4().hex
        guard_db = BACKUPS / (".restore-rollback-" + guard_id + ".sqlite3")
        guard_key = BACKUPS / (".restore-rollback-" + guard_id + ".key")
        moved_db = moved_key = installed_db = installed_key = False
        try:
            os.replace(str(DB), str(guard_db)); moved_db = True
            if key_present and KEY.exists():
                os.replace(str(KEY), str(guard_key)); moved_key = True
            os.replace(str(restored_db), str(DB)); installed_db = True
            if key_present:
                os.replace(str(restored_key), str(KEY)); installed_key = True
                try: os.chmod(str(KEY), 0o600)
                except OSError: pass
        except Exception:
            if installed_key and KEY.exists(): KEY.unlink()
            if installed_db and DB.exists(): DB.unlink()
            if moved_db and guard_db.exists(): os.replace(str(guard_db), str(DB))
            if moved_key and guard_key.exists(): os.replace(str(guard_key), str(KEY))
            raise
        else:
            if guard_db.exists(): guard_db.unlink()
            if guard_key.exists(): guard_key.unlink()

    # Keep the pre-restore safety bundle; remove only the staged copy and manifest.
    staged.unlink()
    PENDING.unlink()
    print("Cartman restore applied successfully.")
    print("Restored backup:", source_id)
    print("Pre-restore safety backup:", safety_id)
    print("Restart Cartman to load the restored database.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("RESTORE ABORTED:", str(exc), file=__import__("sys").stderr)
        raise SystemExit(1)
