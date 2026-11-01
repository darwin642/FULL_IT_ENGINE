#!/usr/bin/env python3
"""Apply a fine-grained encrypted Cartman restore while the server is stopped."""
from __future__ import annotations
import argparse
import getpass
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DB = APP / "cartman.db"
BACKUPS = APP / ".cartman-backups"
PENDING = BACKUPS / "restore-pending-v3.json"
sys.path.insert(0, str(APP))
import cartman_backup_manager as bm  # noqa: E402


def fail(message: str):
    raise RuntimeError(message)


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def contained_target(relative: str):
    relative = bm.core._safe_relative(relative)
    target = ROOT.joinpath(*relative.split("/"))
    if target.is_symlink():
        fail("Refusing to replace a symbolic link: " + relative)
    cursor = target.parent
    while cursor != ROOT and cursor != cursor.parent:
        if cursor.is_symlink():
            fail("Restore path contains a symbolic-link directory: " + relative)
        cursor = cursor.parent
    if not target.parent.resolve().is_relative_to(ROOT.resolve()):
        fail("Restore path escapes the Cartman project: " + relative)
    return target


def connect_ro(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def validate_database(path: Path, require_cartman: bool = True):
    conn = connect_ro(path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            fail("SQLite integrity_check failed.")
        if require_cartman:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "devices" not in names:
                fail("This backup does not contain a valid Cartman database.")
    finally:
        conn.close()


def table_names(conn):
    return [str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def foreign_key_errors(conn):
    try:
        return {tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()}
    except sqlite3.Error:
        return set()


def merge_database_snapshots(target_db: Path, snapshot_paths: list[Path]):
    """Transactionally replace only tables present in the selected module snapshots."""
    sources = []
    table_schema = {}
    table_source = {}
    index_sql = {}
    trigger_sql = {}
    for source_spec in snapshot_paths:
        allowed = None
        if isinstance(source_spec, dict):
            allowed = set(source_spec.get("tables") or [])
            path = Path(source_spec["path"])
        else:
            path = Path(source_spec)
        conn = connect_ro(path)
        sources.append(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            fail("A selected module database snapshot failed integrity_check.")
        if allowed is not None and not allowed:
            continue
        for table in table_names(conn):
            if allowed is not None and table not in allowed:
                continue
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not ddl or not ddl[0]:
                fail("A selected database table has no recoverable schema: " + table)
            if table in table_schema and table_schema[table] != ddl[0]:
                fail("Selected snapshots contain conflicting table schemas: " + table)
            if table not in table_schema:
                table_schema[table] = ddl[0]
                table_source[table] = conn
            for kind, bucket in (("index", index_sql), ("trigger", trigger_sql)):
                rows = conn.execute("SELECT name,sql FROM sqlite_master WHERE type=? AND tbl_name=? AND sql IS NOT NULL", (kind, table)).fetchall()
                for name, sql in rows:
                    bucket[str(name)] = str(sql)
    if not table_schema:
        fail("The selected backup contains no database tables to restore.")

    live = sqlite3.connect(str(target_db), timeout=30)
    live.row_factory = sqlite3.Row
    try:
        before_fk = foreign_key_errors(live)
        live.execute("PRAGMA foreign_keys=OFF")
        live.execute("BEGIN IMMEDIATE")
        for table in sorted(table_schema, reverse=True):
            live.execute(f"DROP TABLE IF EXISTS {quote(table)}")
        for table in sorted(table_schema):
            live.execute(table_schema[table])
        for table in sorted(table_schema):
            src = table_source[table]
            columns_info = src.execute(f"PRAGMA table_xinfo({quote(table)})").fetchall()
            columns = [str(r[1]) for r in columns_info if int(r[6] or 0) == 0]
            if not columns:
                continue
            col_sql = ",".join(quote(c) for c in columns)
            placeholders = ",".join("?" for _ in columns)
            rows = src.execute(f"SELECT {col_sql} FROM {quote(table)}")
            insert_sql = f"INSERT INTO {quote(table)} ({col_sql}) VALUES ({placeholders})"
            batch = rows.fetchmany(500)
            while batch:
                live.executemany(insert_sql, [tuple(row) for row in batch])
                batch = rows.fetchmany(500)
        for sql in index_sql.values():
            live.execute(sql)
        for sql in trigger_sql.values():
            live.execute(sql)
        integrity = live.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            fail("The merged Cartman database failed integrity_check; no changes were committed.")
        after_fk = foreign_key_errors(live)
        new_fk = after_fk - before_fk
        if new_fk:
            sample = next(iter(new_fk))
            fail("The selected module restore would introduce foreign-key errors (example: " + str(sample) + "). No changes were committed.")
        live.commit()
        live.execute("PRAGMA foreign_keys=ON")
    except Exception:
        live.rollback()
        raise
    finally:
        live.close()
        for conn in sources:
            conn.close()


def checkpoint_live_database():
    if not DB.is_file() or DB.is_symlink():
        fail("Current Cartman database is missing or unsafe.")
    conn = sqlite3.connect(str(DB), timeout=2)
    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result and int(result[0]) != 0:
            fail("SQLite WAL checkpoint is busy. Ensure every Cartman process is stopped.")
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(DB) + suffix)
        if sidecar.exists() and sidecar.stat().st_size > 0:
            fail("SQLite sidecar remains active: " + sidecar.name + ". Stop Cartman completely and retry.")
        if sidecar.exists():
            try: sidecar.unlink()
            except OSError: pass


def copy_database(source: Path, target: Path):
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst, pages=256, sleep=0.05)
        dst.commit()
    finally:
        dst.close(); src.close()


def main():
    parser = argparse.ArgumentParser(description="Apply a staged encrypted Cartman restore.")
    parser.add_argument("--apply-pending", action="store_true")
    parser.add_argument("--confirm-server-stopped", action="store_true")
    args = parser.parse_args()
    if not args.apply_pending or not args.confirm_server_stopped:
        parser.error("Both --apply-pending and --confirm-server-stopped are required.")
    if not PENDING.is_file() or PENDING.is_symlink():
        fail("No staged encrypted restore was found.")
    if BACKUPS.is_symlink():
        fail("Backup repository path is unsafe.")

    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    backup_id = str(pending.get("backup_id") or "")
    selected = pending.get("components")
    if not isinstance(selected, list) or not selected or any(c not in bm.VALID_COMPONENTS for c in selected):
        fail("Staged restore component selection is invalid.")
    db_ids = [x for x in selected if x.startswith("db:") or x == "database"]
    if (bm.DB_ALL in db_ids or "database" in db_ids) and len(db_ids) > 1:
        fail("Full Database and individual database modules cannot be restored together.")
    backup_path = bm.safe_bundle_path(BACKUPS, backup_id)
    if bm.core.sha256_file(backup_path) != pending.get("archive_sha256"):
        fail("Encrypted backup changed after restore preparation.")
    password = getpass.getpass("Cartman backup password: ")
    if len(password) < 12:
        fail("A password of at least 12 characters is required.")

    with tempfile.TemporaryDirectory(prefix="cartman-restore-v3-") as work:
        work_root = Path(work)
        try: os.chmod(work, 0o700)
        except OSError: pass
        with bm.core.unlocked_backup(backup_path, password, BACKUPS, expected_id=backup_id) as (zip_path, manifest, _header):
            included = set(manifest.get("components", {}).keys())
            if not set(selected).issubset(included):
                fail("A selected restore item is not present in this recovery point.")
            bm._validate_connector_restore(zip_path, manifest, selected, ROOT)
            stage = work_root / "staged"
            stage.mkdir(mode=0o700)
            file_items = []
            db_full = None
            db_groups = []
            with zipfile.ZipFile(zip_path, "r") as archive:
                for item in manifest.get("entries", []):
                    if item.get("component") not in selected:
                        continue
                    arcname = bm.core._safe_relative(item.get("archive_path", ""))
                    if item.get("kind") == "database_snapshot":
                        component_id = item["component"]
                        staged_db = stage / (component_id.replace(":", "_") + ".sqlite3")
                        with archive.open(arcname, "r") as src, staged_db.open("xb") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                        validate_database(staged_db, require_cartman=False)
                        component_info = manifest.get("components", {}).get(component_id, {})
                        direct_tables = component_info.get("tables") or []
                        if not direct_tables:
                            fail("A selected database module has no direct table list: " + component_id)
                        db_groups.append({"path": staged_db, "tables": direct_tables})
                    else:
                        relative = bm.core._safe_relative(item.get("path", ""))
                        target = stage.joinpath(*relative.split("/"))
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.is_symlink():
                            fail("Staged restore path is unsafe.")
                        with archive.open(arcname, "r") as src, target.open("xb") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                        staged = {"relative": relative, "path": target, "mode": int(item.get("mode", 0o600)), "component": item.get("component")}
                        if item.get("component") in {bm.DB_ALL, "database"} and relative == "app/cartman.db":
                            validate_database(target, require_cartman=True)
                            db_full = target
                        else:
                            file_items.append(staged)

            if (bm.DB_ALL in selected or "database" in selected) and db_full is None:
                fail("Full Database was selected but app/cartman.db is missing from the backup.")
            if any(x.startswith("db:") and x != bm.DB_ALL for x in selected) and not db_groups:
                fail("Database module items were selected but no partial database snapshots were found.")

            # Capture a full, encrypted, pre-restore safety point before replacing any live data.
            safety_selection = bm.full_system_selection(ROOT, DB)
            safety = bm.create_bundle(ROOT, DB, BACKUPS, "Pre-restore safety " + uuid.uuid4().hex[:8], safety_selection, password, bundle_type="pre_restore_safety")
            print("Encrypted full-system safety backup created:", safety["id"])

            new_db = None
            db_old_copy = None
            if db_full is not None or db_groups:
                checkpoint_live_database()
                db_old_copy = work_root / "cartman-before-restore.sqlite3"
                copy_database(DB, db_old_copy)
                new_db = work_root / "cartman-after-restore.sqlite3"
                if db_full is not None:
                    copy_database(db_full, new_db)
                else:
                    copy_database(DB, new_db)
                    merge_database_snapshots(new_db, db_groups)
                validate_database(new_db, require_cartman=True)

            rollback_root = work_root / "rollback"
            rollback_root.mkdir(mode=0o700)
            applied_files = []
            db_replaced = False
            try:
                # Replace selected files as an overlay. Items not included in the backup remain untouched.
                for index, item in enumerate(file_items):
                    target = contained_target(item["relative"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and (target.is_dir() or target.is_symlink()):
                        fail("Restore target is not a regular file: " + item["relative"])
                    old = None
                    if target.exists():
                        old = rollback_root / (str(index) + ".old")
                        shutil.copy2(target, old)
                    applied_files.append((target, old))
                    replacement = target.with_name("." + target.name + ".cartman-restore-" + uuid.uuid4().hex + ".tmp")
                    try:
                        shutil.copy2(item["path"], replacement)
                        os.replace(replacement, target)
                    finally:
                        try: replacement.unlink()
                        except FileNotFoundError: pass
                    try:
                        os.chmod(target, item["mode"] & 0o700 if item["component"] in {"security:credentials", "security"} else item["mode"] & 0o755)
                    except OSError: pass
                # Database switch is last and atomic, after the selected files are in place.
                if new_db is not None:
                    replacement_db = DB.with_name(".cartman.db.restore-" + uuid.uuid4().hex + ".tmp")
                    try:
                        shutil.copy2(new_db, replacement_db)
                        os.replace(replacement_db, DB)
                        db_replaced = True
                    finally:
                        try: replacement_db.unlink()
                        except FileNotFoundError: pass
            except Exception:
                if db_replaced and db_old_copy and db_old_copy.exists():
                    rollback_db = DB.with_name(".cartman.db.rollback-" + uuid.uuid4().hex + ".tmp")
                    try:
                        shutil.copy2(db_old_copy, rollback_db)
                        os.replace(rollback_db, DB)
                    finally:
                        try: rollback_db.unlink()
                        except FileNotFoundError: pass
                for target, old in reversed(applied_files):
                    try:
                        if old and old.exists():
                            rollback_file = target.with_name("." + target.name + ".rollback-" + uuid.uuid4().hex + ".tmp")
                            try:
                                shutil.copy2(old, rollback_file)
                                os.replace(rollback_file, target)
                            finally:
                                try: rollback_file.unlink()
                                except FileNotFoundError: pass
                        elif target.exists():
                            target.unlink()
                    except OSError:
                        pass
                raise

    # CARTMAN_ROOT_UI_API_V1: record who prepared and who executed the offline restore.
    try:
        import datetime as _cartman_restore_datetime
        import getpass as _cartman_restore_getpass
        audit_now = _cartman_restore_datetime.datetime.now(_cartman_restore_datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        executing_os_user = _cartman_restore_getpass.getuser()
        audit_details = json.dumps({
            "components": selected,
            "prepared_by": pending.get("prepared_by", "Unknown"),
            "prepared_at": pending.get("prepared_at"),
            "executed_by_os_account": executing_os_user,
            "restored_at": audit_now,
            "safety_backup_id": safety.get("id") if isinstance(safety, dict) else None,
        }, ensure_ascii=False)
        audit_conn = sqlite3.connect(str(DB))
        try:
            audit_conn.execute("CREATE TABLE IF NOT EXISTS iam_audit_events (id TEXT PRIMARY KEY, actor TEXT NOT NULL DEFAULT 'Unattributed', action TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}', occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            audit_conn.execute("INSERT INTO iam_audit_events (id,actor,action,resource_type,resource_id,details_json,occurred_at) VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex, "OS account:" + executing_os_user, "backup.restore_completed", "backup", backup_id, audit_details, audit_now))
            audit_conn.commit()
        finally:
            audit_conn.close()
    except Exception as audit_exc:
        print("WARNING: restore completed but the completion audit could not be written:", audit_exc, file=sys.stderr)
    PENDING.unlink()
    print("\nCARTMAN RESTORE COMPLETED")
    print("Source backup:", backup_id)
    print("Restored selections:", ", ".join(selected))
    print("Safety backup:", safety["id"])
    print("Database restore mode:", "full SQLite replacement" if (bm.DB_ALL in selected or "database" in selected) else "transactional selected-table merge" if db_groups else "not selected")
    print("File restore mode: overlay; files absent from the backup were not deleted.")
    print("Restart Cartman: .venv/bin/python -m uvicorn app.main:app --reload")


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print("RESTORE ABORTED:", str(exc), file=sys.stderr)
        raise SystemExit(1)

# CARTMAN_ROOT_UI_API_V1
