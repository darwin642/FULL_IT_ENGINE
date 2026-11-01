# CARTMAN_BACKUP_REQUEST_FLOW_V6_MANAGER
# CARTMAN_BACKUP_V6_REPAIR_HOTFIX: Request annotations are evaluated at route registration
"""Cartman Backup Builder V6: user-selected full/selective encrypted backups."""

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

try:
    from . import cartman_backup_crypto_core as core
except ImportError:
    import sys
    _APP_DIR = str(Path(__file__).resolve().parent)
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)
    import cartman_backup_crypto_core as core

FORMAT_VERSION = core.FORMAT_VERSION

# Stable identifiers. Availability and table membership are discovered from the live Cartman project.
DB_GROUPS = {
    "db:devices": ("Devices & Endpoint Management", ("device", "endpoint", "agent", "hardware", "lifecycle", "connection_request")),
    "db:inventory": ("Inventory & Assets", ("inventory", "asset", "department", "purchase", "warranty")),
    "db:tickets": ("Tickets & Knowledge Base", ("ticket", "knowledge", "comment", "ticket_attachment")),
    "db:identity": ("Identity & Access Management", ("auth", "iam", "account", "session", "role", "permission", "user_group")),
    "db:monitoring": ("Monitoring & Alerts", ("monitor", "service_check", "availability_check", "metric", "alert", "health_check")),
    "db:network": ("Network & Infrastructure", ("network", "subnet", "ip_address", "dns", "dhcp", "firewall", "switch", "router")),
    "db:vpn": ("VPN & Remote Access", ("vpn", "remote_access", "ssh_profile", "remote_session")),
    "db:software": ("Software & Deployment", ("software", "package", "deployment", "install_job", "application_catalog")),
    "db:operations": ("IT Operations & Automation", ("workflow", "automation", "task", "work_item", "project", "runbook", "notification", "schedule")),
    "db:settings": ("System Settings & Policies", ("setting", "preference", "configuration", "policy", "system_option")),
    "db:integrations": ("API & Integrations", ("api_key", "api_keys", "connector", "integration", "webhook")),
    "db:reports": ("Reports & Analytics", ("report", "analytics", "dashboard", "saved_query")),
    "db:audit": ("Audit Logs & Activity", ("audit", "activity", "event_log", "access_log", "history", "_logs")),
}
DB_ALL = "db:all"
OTHER_DB = "db:other"
FILE_GROUPS = {
    "files:packages": ("Software Packages & Repository", ("package_repository", "software_packages", "package_storage", "packages")),
    "files:tickets": ("Ticket Attachments & Documents", ("ticket_attachments", "ticket_files", "attachments", "attachment_storage")),
    "files:uploads": ("Uploads", ("uploads", "upload")),
    "files:media": ("Media & Images", ("media", "images")),
    "files:data": ("Data Folders & Exports", ("data", "exports", "export")),
    "files:documents": ("Documents & Reports", ("files", "documents", "document_storage", "documents_storage", "reports", "report")),
    "files:other": ("Other Detected Storage", ()),
}
APP_GROUPS = {
    "app:backend": "Backend Source (Python)",
    "app:frontend": "Frontend (HTML, CSS & JavaScript)",
    "app:scripts": "Scripts & Utilities",
    "app:dependencies": "Dependencies & Runtime Manifests",
    "config:application": "Application Configuration",
    "security:credentials": "Secrets, Encryption Keys & Certificates",
}
VALID_COMPONENTS = [DB_ALL, *DB_GROUPS.keys(), OTHER_DB, *FILE_GROUPS.keys(), *APP_GROUPS.keys(), "database", "file_storage", "application", "configuration", "security"]
CORE_LABELS = {DB_ALL: "Full Database", OTHER_DB: "Other Database Tables"}
CORE_LABELS.update({k: v[0] for k, v in DB_GROUPS.items()})
CORE_LABELS.update({k: v[0] for k, v in FILE_GROUPS.items()})
CORE_LABELS.update(APP_GROUPS)
CORE_LABELS.update({"database": "Legacy Database", "file_storage": "Legacy File Storage", "application": "Legacy Application", "configuration": "Legacy Configuration", "security": "Legacy Security & Credentials"})
# The legacy crypto parser checks component IDs against this module global.
core.COMPONENTS = tuple(VALID_COMPONENTS)
core.LABELS = CORE_LABELS

EXCLUDED = set(core.EXCLUDED_DIRS) | {".cartman-backups", "cartman_backup_manager.py", "cartman_backup_crypto_core.py"}
STORAGE_NAMES = {x for _label, names in FILE_GROUPS.values() for x in names}
STORAGE_NAMES |= {"storage", "file_storage", "software_package_repository", "artifact_repository", "files", "documents", "documents_storage", "document_storage", "reports", "report", "exports", "export", "data_files"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".crt", ".cer", ".secret"}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [str(r[0]) for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]


def _classify_table(name: str) -> str:
    n = name.lower()
    # Prioritized matching avoids a table being assigned to more than one module.
    for group_id, (_label, tokens) in DB_GROUPS.items():
        if group_id == "db:audit":
            continue
        if any(token in n for token in tokens):
            return group_id
    if any(token in n for token in DB_GROUPS["db:audit"][1]):
        return "db:audit"
    return OTHER_DB


def _database_catalog(database: Path) -> tuple[dict[str, list[str]], list[str]]:
    if not database.is_file() or database.is_symlink():
        return {}, []
    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = _table_names(conn)
        grouped = {k: [] for k in (*DB_GROUPS.keys(), OTHER_DB)}
        for table in tables:
            grouped[_classify_table(table)].append(table)
        return grouped, tables
    finally:
        conn.close()


def _relative_under(root: Path, path: Path) -> Path:
    """Return path relative to root after canonicalizing macOS /var aliases."""
    root_real = os.path.realpath(os.fspath(root))
    path_real = os.path.realpath(os.fspath(path))
    try:
        common = os.path.commonpath((root_real, path_real))
    except ValueError:
        raise ValueError("Path is outside the Cartman project root.")
    if os.path.normcase(common) != os.path.normcase(root_real):
        raise ValueError("Path is outside the Cartman project root.")
    relative = os.path.relpath(path_real, root_real)
    return Path(".") if relative == os.curdir else Path(relative)


def _walk(directory: Path, root: Path):
    if not directory.exists() or directory.is_symlink() or not directory.is_dir():
        return
    for current, dirs, files in os.walk(directory, topdown=True, followlinks=False):
        base = Path(current)
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not (base / d).is_symlink()]
        for filename in files:
            yield base / filename


def _add_path(found: dict[str, Path], root: Path, path: Path):
    """Add a regular file using a canonical, containment-checked path."""
    try:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            return
        relative_path = _relative_under(root, candidate)
        core._safe_relative(relative_path.as_posix())
        canonical_root = Path(os.path.realpath(os.fspath(root)))
        canonical_path = Path(os.path.realpath(os.fspath(candidate)))
        parent = canonical_path.parent
        while parent != canonical_root:
            if canonical_root not in parent.parents or parent.is_symlink():
                return
            parent = parent.parent
        found[relative_path.as_posix()] = candidate
    except (OSError, ValueError):
        return


def _storage_directories(root: Path) -> list[Path]:
    found = set()
    for current, dirs, _files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        try:
            depth = len(_relative_under(root, base).parts)
        except ValueError:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not (base / d).is_symlink()]
        if depth >= 6:
            dirs[:] = []
        for name in list(dirs):
            low = name.lower()
            if low in STORAGE_NAMES or any(w in low for w in ("attachment", "ticket_file", "upload", "package_repository")):
                found.add(base / name)
    return sorted(found, key=lambda p: p.as_posix().lower())


def _files_for(component: str, root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    app = root / "app"
    if component == "app:backend":
        for path in _walk(app, root) or ():
            if path.suffix.lower() == ".py" and "static" not in _relative_under(app, path).parts:
                _add_path(found, root, path)
        return found
    if component == "app:frontend":
        for path in _walk(app / "static", root) or ():
            _add_path(found, root, path)
        return found
    if component == "app:scripts":
        for path in _walk(root / "scripts", root) or ():
            if path.name not in {"cartman_restore.py", "cartman_restore_encrypted.py"}:
                _add_path(found, root, path)
        return found
    if component == "app:dependencies":
        names = {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock", ".python-version"}
        for path in root.iterdir():
            if path.is_file() and path.name in names:
                _add_path(found, root, path)
        return found
    if component == "config:application":
        config_roots = [root / "config", app / "config"]
        for directory in config_roots:
            for path in _walk(directory, root) or ():
                if path.suffix.lower() in {".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".json"}:
                    _add_path(found, root, path)
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in {".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml"}:
                _add_path(found, root, path)
        return found
    if component == "security:credentials":
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            base = Path(current)
            dirs[:] = [d for d in dirs if d not in EXCLUDED and not (base / d).is_symlink()]
            depth = len(_relative_under(root, base).parts)
            if depth >= 7:
                dirs[:] = []
            for filename in files:
                path = base / filename
                low = filename.lower()
                if low == ".env" or low.startswith(".env.") or path.suffix.lower() in SECRET_SUFFIXES:
                    _add_path(found, root, path)
        return found
    if component.startswith("files:"):
        dirs = _storage_directories(root)
        group = component.split(":", 1)[1]
        for directory in dirs:
            name = directory.name.lower()
            path_text = directory.as_posix().lower()
            if group == "packages":
                match = any(x in name for x in FILE_GROUPS[component][1]) or "package_repository" in path_text
            elif group == "tickets":
                match = any(x in name for x in FILE_GROUPS[component][1]) or "ticket" in path_text or "attachment" in path_text
            elif group == "uploads":
                match = any(x in name for x in FILE_GROUPS[component][1]) or "upload" in path_text
            elif group == "media":
                match = any(x in name for x in FILE_GROUPS[component][1]) or "media" in path_text or "images" in path_text
            elif group == "data":
                match = any(x in name for x in FILE_GROUPS[component][1]) or name == "data" or name == "exports"
            elif group == "documents":
                match = any(x in name for x in FILE_GROUPS[component][1]) or "document" in name or "report" in name or name == "files"
            else:
                known = any((x in name or x in path_text) for x in ("package", "attachment", "ticket_file", "upload", "media", "images", "data", "export", "document", "report", "files"))
                match = not known
            if match:
                for path in _walk(directory, root) or ():
                    _add_path(found, root, path)
        return found
    raise ValueError("Unsupported component: " + component)


def _fk_closure(connection: sqlite3.Connection, tables: list[str]) -> list[str]:
    all_tables = set(_table_names(connection))
    keep = set(tables)
    pending = list(tables)
    while pending:
        table = pending.pop()
        try:
            refs = [str(row[2]) for row in connection.execute(f"PRAGMA foreign_key_list({_quote(table)})")]
        except sqlite3.Error:
            refs = []
        for ref in refs:
            if ref in all_tables and ref not in keep:
                keep.add(ref)
                pending.append(ref)
    return sorted(keep)


def _partial_database(source: Path, target: Path, direct_tables: list[str]) -> tuple[list[str], list[str]]:
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst, pages=256, sleep=0.05)
        dst.commit()
    finally:
        src.close()
        dst.close()
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        all_tables = _table_names(conn)
        included = _fk_closure(conn, direct_tables)
        conn.execute("BEGIN IMMEDIATE")
        for view in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall():
            conn.execute(f"DROP VIEW IF EXISTS {_quote(str(view[0]))}")
        for table in all_tables:
            if table not in included:
                conn.execute(f"DROP TABLE IF EXISTS {_quote(table)}")
        conn.commit()
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise ValueError("A partial database snapshot failed SQLite integrity_check.")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise ValueError("A partial database snapshot has unresolved foreign-key dependencies: " + str(len(fk_errors)))
        return included, [t for t in included if t not in direct_tables]
    finally:
        conn.close()


def _database_table_bytes(database: Path) -> dict[str, int]:
    """Estimate database component sizes using SQLite page statistics when available."""
    if not database.is_file() or database.is_symlink():
        return {}
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = _table_names(connection)
        sizes: dict[str, int] = {table: 0 for table in tables}
        try:
            page_sizes = {str(row[0]): int(row[1] or 0) for row in connection.execute(
                "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"
            ).fetchall()}
            for table in tables:
                sizes[table] += page_sizes.get(table, 0)
            for index_name, table_name in connection.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND tbl_name IS NOT NULL"
            ).fetchall():
                if table_name in sizes:
                    sizes[str(table_name)] += page_sizes.get(str(index_name), 0)
            if any(value > 0 for value in sizes.values()):
                return sizes
        except sqlite3.Error:
            pass
        # Fallback for SQLite builds without dbstat: distribute file bytes by observed row counts.
        row_counts = {}
        total_rows = 0
        for table in tables:
            try:
                count = int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
            except sqlite3.Error:
                count = 0
            row_counts[table] = max(1, count)
            total_rows += row_counts[table]
        total_bytes = int(database.stat().st_size)
        if total_rows:
            return {table: max(1, int(total_bytes * count / total_rows)) for table, count in row_counts.items()}
        return sizes
    finally:
        connection.close()


def _catalog(root: Path, database: Path) -> list[dict[str, Any]]:
    grouped, all_tables = _database_catalog(database)
    table_bytes = _database_table_bytes(database)
    database_bytes = int(database.stat().st_size) if database.is_file() and not database.is_symlink() else 0
    output = []
    def add(item_id, name, section, description, files=None, tables=None, dependencies=None, table_rows=None):
        files = files or {}
        tables = tables or []
        file_bytes = 0
        for path in files.values():
            try: file_bytes += path.stat().st_size
            except OSError: pass
        if item_id == DB_ALL:
            estimated_bytes = database_bytes
        elif tables:
            estimated_bytes = sum(table_bytes.get(table, 0) for table in tables)
        else:
            estimated_bytes = file_bytes
        output.append({
            "id": item_id, "name": name, "section": section, "description": description,
            "available": bool(files or tables), "file_count": len(files), "table_count": len(tables),
            "bytes": int(estimated_bytes), "estimated_bytes": int(estimated_bytes),
            "tables": tables[:2000], "table_total": len(tables),
            "dependencies": (dependencies or [])[:100],
            "table_rows": table_rows or {},
            "paths": sorted(files.keys())[:80],
        })
    row_counts = {}
    if all_tables and database.is_file():
        conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for table in all_tables:
                try: row_counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
                except sqlite3.Error: row_counts[table] = None
        finally: conn.close()
    add(DB_ALL, "Full Database (all tables)", "Database", "Consistent SQLite snapshot containing every Cartman database table.", tables=all_tables, table_rows=row_counts)
    for group_id, (label, _tokens) in DB_GROUPS.items():
        tables = grouped.get(group_id, [])
        add(group_id, label, "Database", "Module-specific database records. Linked parent tables are included automatically when required.", tables=tables, table_rows={t: row_counts.get(t) for t in tables})
    add(OTHER_DB, "Other / Unclassified Database Data", "Database", "Database tables not assigned to another Cartman module.", tables=grouped.get(OTHER_DB, []), table_rows={t: row_counts.get(t) for t in grouped.get(OTHER_DB, [])})
    descriptions = {
        "files:packages": "Installers, packages and software repository files.",
        "files:tickets": "Ticket attachments, uploaded documents and ticket-related files.",
        "files:uploads": "General uploads stored on the Cartman server.",
        "files:media": "Images, media and other media-library files.",
        "files:data": "Data folders, exports and local generated data.",
        "files:documents": "Document libraries, reports and shared files folders.",
        "files:other": "Detected storage folders not classified into another file category.",
    }
    for cid, (label, _tokens) in FILE_GROUPS.items():
        add(cid, label, "Files & Data", descriptions[cid], files=_files_for(cid, root))
    for cid, label in APP_GROUPS.items():
        section = "Security" if cid.startswith("security:") else "Configuration" if cid.startswith("config:") else "Application"
        description = {
            "app:backend": "Python backend source files under app/ (excluding database and file stores).",
            "app:frontend": "Cartman HTML, CSS, JavaScript, translations and static UI assets.",
            "app:scripts": "Project maintenance, setup and operational scripts.",
            "app:dependencies": "Python dependency and runtime manifest files.",
            "config:application": "Non-secret application configuration and runtime config files.",
            "security:credentials": "Environment files, encryption keys and certificates. Encrypted in the backup; store the archive carefully.",
        }[cid]
        add(cid, label, section, description, files=_files_for(cid, root))
    return output


def _component_map(root: Path, database: Path) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _catalog(root, database)}


def _db_tables_for_selection(database: Path, selected: list[str]) -> list[str]:
    grouped, all_tables = _database_catalog(database)
    tables = []
    for cid in selected:
        if cid == DB_ALL:
            return all_tables
        if cid.startswith("db:"):
            tables.extend(grouped.get(cid, []))
    return sorted(set(tables))


def _validate_selection(root: Path, database: Path, selected: list[str], catalog: dict[str, dict[str, Any]]):
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
        raise ValueError("Select one or more unique backup items.")
    unknown = [x for x in selected if x not in catalog]
    if unknown:
        raise ValueError("Unsupported backup items: " + ", ".join(unknown))
    missing = [x for x in selected if not catalog[x]["available"]]
    if missing:
        raise ValueError("These items are not present on this Cartman server: " + ", ".join(missing))
    db_selected = [x for x in selected if x.startswith("db:") or x == "database"]
    if (DB_ALL in db_selected or "database" in db_selected) and len(db_selected) > 1:
        raise ValueError("Choose Full Database OR individual database modules, not both.")
    tables = _db_tables_for_selection(database, db_selected)
    if "cartman_connectors" in tables or (DB_ALL in db_selected) or ("database" in db_selected):
        if database.is_file():
            conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            try:
                t = set(_table_names(conn))
                if "cartman_connectors" in t:
                    try:
                        count = conn.execute("SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''").fetchone()[0]
                    except sqlite3.Error:
                        count = 0
                else:
                    count = 0
            finally:
                conn.close()
            if count:
                key = root / "app" / ".cartman_connector_fernet.key"
                key_id = "security:credentials"
                legacy_security = "security" in selected
                if not key.is_file() or key.is_symlink() or (key_id not in selected and not legacy_security) or _relative_under(root, key).as_posix() not in _files_for(key_id, root):
                    raise ValueError("This database contains encrypted Connector credentials. Also select Secrets, Encryption Keys & Certificates so the matching key is included.")
    return tables


def _size_and_hash(path: Path):
    return path.stat().st_size, core.sha256_file(path)


def create_bundle(root: Path, database: Path, backup_dir: Path, name: str, selected: list[str], password: str, bundle_type: str = "manual", created_by: str = "Unknown"):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Backup password must contain between 12 and 1024 characters.")
    name = str(name or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Backup name is required and must be at most 120 characters.")
    catalog = _component_map(root, database)
    direct_tables = _validate_selection(root, database, selected, catalog)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try: os.chmod(backup_dir, 0o700)
    except OSError: pass
    backup_id = uuid.uuid4().hex
    created_at = core._now()

    with tempfile.TemporaryDirectory(prefix="cartman-builder-") as tmp:
        os.chmod(tmp, 0o700)
        temp = Path(tmp)
        full_db_snapshot = None
        if any(x.startswith("db:") for x in selected):
            full_db_snapshot = temp / "cartman-full-snapshot.sqlite3"
            source = sqlite3.connect(str(database))
            target = sqlite3.connect(str(full_db_snapshot))
            try:
                source.backup(target, pages=256, sleep=0.05)
                target.commit()
            finally:
                target.close(); source.close()
        files_by_component: dict[str, dict[str, Path]] = {}
        component_info: dict[str, dict[str, Any]] = {}
        partial_dbs: dict[str, Path] = {}
        for cid in selected:
            item = catalog[cid]
            if cid == DB_ALL:
                component_info[cid] = {"name": item["name"], "section": item["section"], "file_count": 0, "table_count": item["table_count"], "bytes": full_db_snapshot.stat().st_size, "tables": item["tables"], "table_rows": item.get("table_rows", {})}
            elif cid.startswith("db:"):
                tables = item["tables"]
                partial_path = temp / (cid.replace(":", "_") + ".sqlite3")
                included, dependencies = _partial_database(full_db_snapshot, partial_path, tables)
                partial_dbs[cid] = partial_path
                component_info[cid] = {"name": item["name"], "section": item["section"], "file_count": 0, "table_count": len(tables), "bytes": partial_path.stat().st_size, "tables": tables, "table_rows": item.get("table_rows", {}), "included_tables": included, "dependency_tables": dependencies}
            else:
                file_map = _files_for(cid, root)
                files_by_component[cid] = file_map
                component_info[cid] = {"name": item["name"], "section": item["section"], "file_count": len(file_map), "bytes": sum(p.stat().st_size for p in file_map.values() if p.exists()), "directories": sorted({str(Path(rel).parent) for rel in file_map})[:100]}

        zip_path = temp / "payload.zip"
        entries = []
        seen_archive_names = set()
        seen_project_paths = set()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for cid in selected:
                if cid == DB_ALL:
                    sources = [(full_db_snapshot, "app/cartman.db", "payload/app/cartman.db", "database")]
                elif cid.startswith("db:"):
                    rel = "database-snapshots/" + cid.replace(":", "_") + ".sqlite3"
                    sources = [(partial_dbs[cid], rel, "payload/" + rel, "database_snapshot")]
                else:
                    sources = []
                    for rel, path in sorted(files_by_component[cid].items()):
                        if rel in seen_project_paths:
                            continue
                        seen_project_paths.add(rel)
                        sources.append((path, rel, "payload/" + rel, "file"))
                actual_count = 0
                actual_bytes = 0
                for src, rel, archive_name, entry_kind in sources:
                    if archive_name in seen_archive_names:
                        continue
                    seen_archive_names.add(archive_name)
                    before = src.stat()
                    digest = core.sha256_file(src)
                    archive.write(src, arcname=archive_name)
                    after = src.stat()
                    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                        raise ValueError("A backup source changed while being read: " + rel)
                    entries.append({"path": rel, "archive_path": archive_name, "component": cid,
                                    "kind": entry_kind, "size": after.st_size, "sha256": digest,
                                    "mode": int(before.st_mode & 0o777)})
                    if entry_kind == "file":
                        actual_count += 1
                        actual_bytes += after.st_size
                if not cid.startswith("db:"):
                    component_info[cid]["file_count"] = actual_count
                    component_info[cid]["bytes"] = actual_bytes
            manifest = {
                "format": "cartman-encrypted-backup", "format_version": FORMAT_VERSION,
                "backup_id": backup_id, "name": name, "bundle_type": bundle_type,
                "created_at": created_at, "created_by": str(created_by or "Unknown"), "components": component_info, "entries": entries,
                "restore_mode": "selected components; files are overlaid, absent files are not deleted",
                "database_restore_modes": {"db:all": "full SQLite replacement", "db:module": "selected module tables merged transactionally"},
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        output = backup_dir / ("cartman-" + backup_id + ".cartmanbackup")
        encrypted_temp = backup_dir / (".cartman-" + backup_id + ".tmp")
        try:
            core._encrypt_file(zip_path, encrypted_temp, password, {"backup_id": backup_id, "created_at": created_at})
            os.chmod(encrypted_temp, 0o600)
            os.replace(encrypted_temp, output)
        finally:
            try: encrypted_temp.unlink()
            except FileNotFoundError: pass
        try: os.chmod(output, 0o600)
        except OSError: pass
    return {"id": backup_id, "created_at": created_at, "bytes": output.stat().st_size,
            "filename": output.name, "bundle_type": bundle_type, "components": component_info,
            "format_version": FORMAT_VERSION}


def _validate_connector_restore(zip_path: Path, manifest: dict, selected: list[str], root: Path):
    db_ids = [x for x in selected if x.startswith("db:") or x == "database"]
    if not db_ids:
        return
    entries = manifest.get("entries", [])
    if DB_ALL in db_ids or "database" in db_ids:
        full_id = DB_ALL if DB_ALL in db_ids else "database"
        db_entry = next((x for x in entries if x.get("component") == full_id), None)
        if not db_entry:
            return
        with tempfile.TemporaryDirectory(prefix="cartman-connector-check-") as tmp:
            temp_db = Path(tmp) / "check.sqlite3"
            with zipfile.ZipFile(zip_path) as zf, zf.open(db_entry["archive_path"]) as src, temp_db.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            conn = sqlite3.connect(temp_db.as_uri() + "?mode=ro", uri=True)
            try:
                tables = set(_table_names(conn))
                count = conn.execute("SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''").fetchone()[0] if "cartman_connectors" in tables else 0
            finally: conn.close()
    else:
        group_entries = [x for x in entries if x.get("component") in db_ids and x.get("kind") == "database_snapshot"]
        count = 0
        for item in group_entries:
            with tempfile.TemporaryDirectory(prefix="cartman-connector-check-") as tmp:
                temp_db = Path(tmp) / "check.sqlite3"
                with zipfile.ZipFile(zip_path) as zf, zf.open(item["archive_path"]) as src, temp_db.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                conn = sqlite3.connect(temp_db.as_uri() + "?mode=ro", uri=True)
                try:
                    tables = set(_table_names(conn))
                    if "cartman_connectors" in tables:
                        count += conn.execute("SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''").fetchone()[0]
                finally: conn.close()
    if not count:
        return
    key_rel = "app/.cartman_connector_fernet.key"
    key_entry = next((x for x in entries if x.get("path") == key_rel), None)
    if not key_entry:
        raise ValueError("The selected database data contains encrypted Connector credentials, but the matching key is not present in this backup. Include Secrets, Encryption Keys & Certificates.")
    if "security:credentials" not in selected and "security" not in selected:
        current = root / key_rel
        if not current.is_file() or current.is_symlink() or core.sha256_file(current) != key_entry.get("sha256"):
            raise ValueError("The selected database restore needs the matching Connector encryption key. Select Secrets, Encryption Keys & Certificates too.")


def safe_bundle_path(backup_dir: Path, backup_id: str):
    if not core.ID_RE.fullmatch(str(backup_id or "")):
        raise ValueError("Invalid backup ID.")
    path = backup_dir / ("cartman-" + backup_id + ".cartmanbackup")
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("Encrypted backup was not found.")
    return path


def _list_bundles(backup_dir: Path):
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    items=[]
    for path in backup_dir.glob("cartman-*.cartmanbackup"):
        try:
            header, _, _ = core.read_header(path)
            items.append({"id": str(header.get("backup_id") or ""), "created_at": str(header.get("created_at") or ""),
                          "bytes": path.stat().st_size, "filename": path.name, "encrypted": True,
                          "integrity": "locked", "format_version": header.get("format_version")})
        except Exception:
            items.append({"id": path.stem, "created_at": "", "bytes": path.stat().st_size, "filename": path.name, "encrypted": True, "integrity": "invalid_header"})
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items, sum(1 for _ in backup_dir.glob("cartman-backup-*.zip"))


def full_system_selection(root: Path, database: Path) -> list[str]:
    catalog = _component_map(root, database)
    # Choose each database module separately so the manifest is transparent and every checkbox is visibly selected.
    db_modules = [cid for cid, info in catalog.items() if cid.startswith("db:") and cid != DB_ALL and info["available"]]
    others = [cid for cid, info in catalog.items() if not cid.startswith("db:") and info["available"]]
    return db_modules + others if db_modules else ([DB_ALL] + others if catalog.get(DB_ALL, {}).get("available") else others)


def register(app, context):
    Request = context["Request"]
    HTTPException = context["HTTPException"]
    FileResponse = context["FileResponse"]
    root = Path(context["BASE_DIR"]).resolve().parent
    database = Path(context["DATABASE"]).resolve()
    get_connection = context["get_connection"]
    auth_user = context["_cartman_int_user"]
    audit = context["_cartman_int_audit"]
    actor = context["_cartman_int_actor"]
    backup_dir = root / "app" / ".cartman-backups"
    pending_path = backup_dir / "restore-pending-v3.json"
    api = "/api/admin/backups/v3"

    def ensure_repo():
        if backup_dir.exists() and backup_dir.is_symlink():
            raise HTTPException(status_code=500, detail="Backup repository must not be a symbolic link.")
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try: os.chmod(backup_dir, 0o700)
        except OSError: pass

    def require_admin(request: Request, write=False):
        auth_user(request, write=write, sensitive=True)
        ensure_repo()

    def translate(exc):
        if isinstance(exc, HTTPException): raise exc
        if isinstance(exc, FileNotFoundError): raise HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, PermissionError): raise HTTPException(status_code=403, detail=str(exc))
        if isinstance(exc, ValueError): raise HTTPException(status_code=422, detail=str(exc))
        raise HTTPException(status_code=500, detail="Backup operation failed: " + str(exc))

    def password_from(payload):
        pw = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(pw, str) or not 12 <= len(pw) <= 1024:
            raise HTTPException(status_code=422, detail="Backup password must contain 12 to 1024 characters.")
        return pw

    @app.get(api + "/catalog")
    def catalog_endpoint(request: Request):
        require_admin(request)
        try: return {"components": _catalog(root, database), "encryption": "AES-256-GCM", "integrity": "SHA-256", "kdf": "scrypt"}
        except Exception as exc: translate(exc)

    @app.get(api)
    def list_endpoint(request: Request):
        require_admin(request)
        try:
            items, legacy = _list_bundles(backup_dir)
            return {"items": items, "total": len(items), "legacy_unencrypted_count": legacy,
                    "storage_bytes": sum(int(x.get("bytes", 0)) for x in items), "repository": "app/.cartman-backups"}
        except Exception as exc: translate(exc)

    @app.post(api, status_code=201)
    async def create_endpoint(request: Request):
        user = auth_user(request, write=True, sensitive=True)
        ensure_repo()
        try: payload = await request.json()
        except Exception: raise HTTPException(status_code=400, detail="A JSON request body is required.")
        pw = password_from(payload)
        if payload.get("confirm_password") != pw:
            raise HTTPException(status_code=422, detail="Backup password confirmation does not match.")
        try:
            bundle_type = payload.get("bundle_type") or "manual"
            if bundle_type not in {"full", "selective", "manual"}:
                raise HTTPException(status_code=422, detail="Unsupported backup type.")
            item = create_bundle(root, database, backup_dir, payload.get("name"), payload.get("components"), pw, bundle_type=bundle_type, created_by=actor(user))
            with get_connection() as conn:
                audit(conn, user, "backup.builder_created", "backup", item["id"], {"name": payload.get("name"), "components": sorted(payload.get("components") or [])})
            return {"item": item, "encryption": "AES-256-GCM", "integrity": "SHA-256"}
        except Exception as exc: translate(exc)

    @app.post(api + "/import-file")
    async def import_file_and_unlock_endpoint(request: Request):
        """Import a .cartmanbackup from the user's computer and unlock it before retaining it."""
        user = auth_user(request, write=True, sensitive=True)
        ensure_repo()
        password = str(request.headers.get("x-cartman-backup-password") or "")
        if not 12 <= len(password) <= 1024:
            raise HTTPException(status_code=422, detail="Backup password must contain 12 to 1024 characters.")
        max_bytes = 50 * 1024 * 1024 * 1024
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > max_bytes:
            raise HTTPException(status_code=413, detail="The selected backup exceeds the 50 GB import limit.")
        incoming = backup_dir / (".incoming-" + uuid.uuid4().hex + ".part")
        total = 0
        try:
            with incoming.open("xb") as handle:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(status_code=413, detail="The selected backup exceeds the 50 GB import limit.")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if total <= 0:
                raise HTTPException(status_code=400, detail="The selected backup file is empty.")
            header, _prefix, _offset = core.read_header(incoming)
            backup_id = str(header.get("backup_id") or "")
            if not core.ID_RE.fullmatch(backup_id):
                raise ValueError("The selected file is not a valid Cartman backup.")
            # Password, AES-GCM, archive structure and every manifest SHA-256 are checked
            # before the uploaded file is retained in the private server recovery repository.
            with core.unlocked_backup(incoming, password, backup_dir, expected_id=backup_id) as (_zip_path, manifest, verified_header):
                backup_name = str(manifest.get("name") or ("Cartman " + backup_id[:8]))
                created_at = str(verified_header.get("created_at") or manifest.get("created_at") or "")
            destination = backup_dir / ("cartman-" + backup_id + ".cartmanbackup")
            if destination.is_symlink():
                raise ValueError("The matching recovery repository path is unsafe.")
            archive_sha256 = core.sha256_file(incoming)
            if destination.exists():
                if core.sha256_file(destination) != archive_sha256:
                    raise HTTPException(status_code=409, detail="A different backup with this ID already exists in the recovery repository.")
                incoming.unlink()
            else:
                try: os.chmod(incoming, 0o600)
                except OSError: pass
                os.replace(incoming, destination)
            with get_connection() as conn:
                audit(conn, user, "backup.imported_from_client", "backup", backup_id,
                      {"name": backup_name, "bytes": total, "sha256": archive_sha256})
            return {"backup": {"id": backup_id, "name": backup_name, "created_at": created_at,
                                "bytes": destination.stat().st_size, "encrypted": True,
                                "integrity": "verified", "encryption": "AES-256-GCM",
                                "sha256": archive_sha256},
                    "manifest": manifest, "stored": True}
        except HTTPException:
            raise
        except Exception as exc:
            translate(exc)
        finally:
            try: incoming.unlink()
            except FileNotFoundError: pass

    @app.post(api + "/{backup_id}/unlock")
    async def unlock_endpoint(backup_id: str, request: Request):
        require_admin(request)
        try: payload = await request.json()
        except Exception: raise HTTPException(status_code=400, detail="A JSON request body is required.")
        pw = password_from(payload)
        try:
            path = safe_bundle_path(backup_dir, backup_id)
            with core.unlocked_backup(path, pw, backup_dir, expected_id=backup_id) as (_zip, manifest, header):
                return {"backup": {"id": backup_id, "created_at": header.get("created_at"), "bytes": path.stat().st_size,
                                   "name": manifest.get("name"), "bundle_type": manifest.get("bundle_type"),
                                   "encrypted": True, "integrity": "verified", "encryption": "AES-256-GCM", "hash": "SHA-256"},
                        "manifest": manifest}
        except Exception as exc: translate(exc)

    @app.get(api + "/{backup_id}/download")
    def download_endpoint(backup_id: str, request: Request):
        require_admin(request)
        try:
            path = safe_bundle_path(backup_dir, backup_id)
            return FileResponse(str(path), media_type="application/octet-stream", filename=path.name)
        except Exception as exc: translate(exc)

    @app.post(api + "/{backup_id}/restore-prepare")
    async def restore_prepare_endpoint(backup_id: str, request: Request):
        user = auth_user(request, write=True, sensitive=True)
        ensure_repo()
        try: payload = await request.json()
        except Exception: raise HTTPException(status_code=400, detail="A JSON request body is required.")
        pw = password_from(payload)
        selected = payload.get("components")
        if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
            raise HTTPException(status_code=422, detail="Choose one or more unique restore components.")
        try:
            path = safe_bundle_path(backup_dir, backup_id)
            with core.unlocked_backup(path, pw, backup_dir, expected_id=backup_id) as (zip_path, manifest, _header):
                included = set(manifest.get("components", {}).keys())
                if not set(selected).issubset(included):
                    raise ValueError("A selected restore item is not included in this backup.")
                db_ids = [x for x in selected if x.startswith("db:") or x == "database"]
                if (DB_ALL in db_ids or "database" in db_ids) and len(db_ids) > 1:
                    raise ValueError("Choose Full Database OR individual database modules for restore, not both.")
                _validate_connector_restore(zip_path, manifest, selected, root)
                pending = {"format_version": FORMAT_VERSION, "backup_id": backup_id,
                           "archive_sha256": core.sha256_file(path), "components": sorted(selected),
                           "prepared_at": core._now(), "prepared_by": actor(user)}
            temp_path = pending_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(pending, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, pending_path)
            with get_connection() as conn:
                audit(conn, user, "backup.builder_restore_prepared", "backup", backup_id, {"components": sorted(selected)})
            return {"prepared": True, "message": "Restore validated and staged. Stop Cartman before applying the offline restore command.",
                    "restore": pending, "command": ".venv/bin/python scripts/cartman_restore_encrypted.py --apply-pending --confirm-server-stopped"}
        except Exception as exc: translate(exc)

    @app.get(api + "/restore-pending")
    def pending_get_endpoint(request: Request):
        require_admin(request)
        if not pending_path.is_file() or pending_path.is_symlink(): return {"pending": False, "restore": None}
        try:
            value = json.loads(pending_path.read_text(encoding="utf-8"))
            return {"pending": True, "restore": {**value, "command": ".venv/bin/python scripts/cartman_restore_encrypted.py --apply-pending --confirm-server-stopped"}}
        except Exception: raise HTTPException(status_code=500, detail="Pending restore manifest is invalid.")

    @app.delete(api + "/restore-pending")
    def pending_delete_endpoint(request: Request):
        user = auth_user(request, write=True, sensitive=True)
        ensure_repo()
        if pending_path.is_symlink(): raise HTTPException(status_code=500, detail="Pending restore path is unsafe.")
        if pending_path.exists():
            pending_path.unlink()
            with get_connection() as conn: audit(conn, user, "backup.builder_restore_cancelled", "backup", "pending", {})
        return {"cancelled": True}


# CARTMAN_ROOT_UI_API_V1
