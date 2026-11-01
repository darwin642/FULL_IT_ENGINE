"""Password-encrypted, component-selectable Cartman backup manager (format v2)."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

MAGIC = b"CTMBKP02"
FOOTER_SIZE = 32
TAG_SIZE = 16
FORMAT_VERSION = 2
COMPONENTS = ("database", "file_storage", "application", "configuration", "security")
LABELS = {
    "database": "Database",
    "file_storage": "File Storage",
    "application": "Application",
    "configuration": "Configuration",
    "security": "Security & Credentials",
}
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".backups",
    ".cartman-backups", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store",
}
STORAGE_DIR_NAMES = {
    "package_repository", "attachments", "attachment_storage", "ticket_attachments",
    "ticket_files", "uploads", "upload", "file_storage", "media", "storage",
    "software_packages", "package_storage",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".crt", ".cer", ".secret"}
CONFIG_SUFFIXES = {".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_relative(value):
    text = str(value).replace("\\", "/")
    p = PurePosixPath(text)
    if not text or p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise ValueError("Unsafe relative path in backup manifest.")
    if ":" in p.parts[0]:
        raise ValueError("Drive-qualified paths are not permitted in backup manifests.")
    return p.as_posix()


def _is_excluded(path: Path, root: Path):
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def _add_file(result, root: Path, path: Path, component: str):
    try:
        if path.is_symlink() or not path.is_file() or _is_excluded(path, root):
            return
        resolved_root = root.resolve()
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root):
            return
        relative = path.relative_to(root).as_posix()
        _safe_relative(relative)
        result.setdefault(relative, {"path": path, "component": component})
    except (OSError, ValueError):
        return


def _walk_files(directory: Path, root: Path):
    if not directory.exists() or directory.is_symlink() or not directory.is_dir():
        return
    for current, dirs, files in os.walk(directory, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not (current_path / d).is_symlink()]
        for filename in files:
            yield current_path / filename


def collect_component_files(root: Path, database: Path, component: str):
    root = root.resolve()
    database = database.resolve()
    result = {}
    app_dir = root / "app"

    if component == "database":
        if database.is_file() and not database.is_symlink():
            result[database.relative_to(root).as_posix()] = {"path": database, "component": component, "database": True}
        return result

    if component == "application":
        if app_dir.is_dir():
            for current, dirs, files in os.walk(app_dir, topdown=True, followlinks=False):
                current_path = Path(current)
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and d.lower() not in STORAGE_DIR_NAMES and not (current_path / d).is_symlink()]
                for filename in files:
                    path = current_path / filename
                    if path.suffix.lower() == ".py" or "static" in path.relative_to(app_dir).parts:
                        _add_file(result, root, path, component)
        scripts_dir = root / "scripts"
        for path in _walk_files(scripts_dir, root) or ():
            if path.name not in {"cartman_restore.py", "cartman_restore_encrypted.py"}:
                _add_file(result, root, path, component)
        for name in ("README.md",):
            _add_file(result, root, root / name, component)
        return result

    if component == "file_storage":
        candidate_dirs = [
            root / "package_repository", app_dir / "package_repository",
            root / "attachments", root / "uploads", root / "storage", root / "media", root / "data",
            app_dir / "attachments", app_dir / "attachment_storage", app_dir / "ticket_attachments",
            app_dir / "ticket_files", app_dir / "uploads", app_dir / "storage", app_dir / "media",
            app_dir / "data", app_dir / "static" / "uploads",
        ]
        for directory in candidate_dirs:
            for path in _walk_files(directory, root) or ():
                _add_file(result, root, path, component)
        # Discover additional conventional upload/storage folders without traversing excluded trees.
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            rel_depth = len(current_path.relative_to(root).parts)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not (current_path / d).is_symlink()]
            if rel_depth >= 5:
                dirs[:] = []
            for dirname in list(dirs):
                if dirname.lower() in STORAGE_DIR_NAMES:
                    directory = current_path / dirname
                    for path in _walk_files(directory, root) or ():
                        _add_file(result, root, path, component)
        return result

    if component == "configuration":
        for directory in (root / "config", app_dir / "config"):
            for path in _walk_files(directory, root) or ():
                if path.suffix.lower() in CONFIG_SUFFIXES or path.name.lower().endswith(".json"):
                    _add_file(result, root, path, component)
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in CONFIG_SUFFIXES:
                _add_file(result, root, path, component)
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", ".python-version"):
            _add_file(result, root, root / name, component)
        return result

    if component == "security":
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not (current_path / d).is_symlink()]
            rel_depth = len(current_path.relative_to(root).parts)
            if rel_depth >= 6:
                dirs[:] = []
            for filename in files:
                path = current_path / filename
                lower = filename.lower()
                if lower == ".env" or lower.startswith(".env.") or path.suffix.lower() in SECRET_SUFFIXES:
                    _add_file(result, root, path, component)
        return result

    raise ValueError("Unsupported backup component.")


def component_catalog(root: Path, database: Path):
    output = []
    for component in COMPONENTS:
        files = collect_component_files(root, database, component)
        total = 0
        for value in files.values():
            try:
                total += value["path"].stat().st_size
            except OSError:
                pass
        output.append({
            "id": component, "name": LABELS[component], "available": bool(files),
            "file_count": len(files), "bytes": total,
            "description": {
                "database": "Consistent SQLite snapshot of Cartman's operational records.",
                "file_storage": "Detected package repositories, uploads, attachments and storage folders.",
                "application": "Cartman Python source, static HTML/CSS/JS, scripts and project runtime manifests.",
                "configuration": "Detected application configuration files and dependency manifests.",
                "security": "Detected environment secrets, encryption keys and certificate/key files. Handle with care.",
            }[component],
        })
    return output


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _derive_key(password: str, salt: bytes):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def _encrypt_file(plain_path: Path, output_path: Path, password: str, header_data: dict):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    import secrets
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    header = dict(header_data)
    header.update({
        "format_version": FORMAT_VERSION,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt", "scrypt_n": 2 ** 15, "scrypt_r": 8, "scrypt_p": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "payload_size": plain_path.stat().st_size,
    })
    header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(header_bytes) > 65536:
        raise ValueError("Backup header is unexpectedly large.")
    prefix = MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
    key = _derive_key(password, salt)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(prefix)
    digest = hashlib.sha256()
    with output_path.open("wb") as target:
        target.write(prefix); digest.update(prefix)
        with plain_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                encrypted = encryptor.update(chunk)
                if encrypted:
                    target.write(encrypted); digest.update(encrypted)
        final = encryptor.finalize()
        if final:
            target.write(final); digest.update(final)
        target.write(encryptor.tag); digest.update(encryptor.tag)
        target.write(digest.digest())
        target.flush(); os.fsync(target.fileno())


def read_header(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Backup file is missing or unsafe.")
    with path.open("rb") as handle:
        magic = handle.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError("Unknown or unsupported backup format.")
        raw_len = handle.read(4)
        if len(raw_len) != 4:
            raise ValueError("Backup header is incomplete.")
        header_len = struct.unpack(">I", raw_len)[0]
        if not 2 <= header_len <= 65536:
            raise ValueError("Backup header length is invalid.")
        header_bytes = handle.read(header_len)
        if len(header_bytes) != header_len:
            raise ValueError("Backup header is truncated.")
        header = json.loads(header_bytes.decode("utf-8"))
    payload_size = header.get("payload_size")
    if type(payload_size) is not int or payload_size < 1:
        raise ValueError("Backup payload size is invalid.")
    expected_size = len(MAGIC) + 4 + header_len + payload_size + TAG_SIZE + FOOTER_SIZE
    if path.stat().st_size != expected_size:
        raise ValueError("Backup file size does not match its header.")
    if header.get("format_version") != FORMAT_VERSION or header.get("cipher") != "AES-256-GCM" or header.get("kdf") != "scrypt":
        raise ValueError("Unsupported backup cryptography format.")
    if header.get("scrypt_n") != 2 ** 15 or header.get("scrypt_r") != 8 or header.get("scrypt_p") != 1:
        raise ValueError("Unsupported backup password derivation parameters.")
    if not ID_RE.fullmatch(str(header.get("backup_id") or "")):
        raise ValueError("Backup identifier in the header is invalid.")
    return header, MAGIC + raw_len + header_bytes, len(MAGIC) + 4 + header_len


def decrypt_to_zip(path: Path, password: str, temp_dir: Path):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    header, prefix, payload_offset = read_header(path)
    file_size = path.stat().st_size
    footer_offset = file_size - FOOTER_SIZE
    actual_digest = hashlib.sha256()
    with path.open("rb") as handle:
        remaining = footer_offset
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Backup archive ended unexpectedly.")
            actual_digest.update(chunk)
            remaining -= len(chunk)
        stored_digest = handle.read(FOOTER_SIZE)
    if actual_digest.digest() != stored_digest:
        raise ValueError("SHA-256 integrity check failed. The backup may have been changed or damaged.")

    try:
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError("Invalid encryption parameters.")
        key = _derive_key(password, salt)
        with path.open("rb") as handle:
            handle.seek(payload_offset + int(header["payload_size"]))
            tag = handle.read(TAG_SIZE)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(prefix)
        zip_path = temp_dir / "decrypted-payload.zip"
        with path.open("rb") as source, zip_path.open("wb") as target:
            source.seek(payload_offset)
            remaining = int(header["payload_size"])
            while remaining:
                encrypted = source.read(min(1024 * 1024, remaining))
                if not encrypted:
                    raise ValueError("Encrypted backup payload is truncated.")
                plain = decryptor.update(encrypted)
                if plain:
                    target.write(plain)
                remaining -= len(encrypted)
            final = decryptor.finalize()
            if final:
                target.write(final)
    except Exception as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(("SHA-256", "Encrypted backup", "Invalid encryption")):
            raise
        raise ValueError("Incorrect password or AES-256-GCM authentication failed.") from exc
    return zip_path, header


def inspect_zip(zip_path: Path, expected_id: Optional[str] = None):
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Backup contents are missing or contain duplicate file paths.")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > 16 * 1024 * 1024:
            raise ValueError("Backup manifest is too large.")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if manifest.get("format_version") != FORMAT_VERSION or manifest.get("format") != "cartman-encrypted-backup":
            raise ValueError("Backup manifest format is unsupported.")
        if expected_id and manifest.get("backup_id") != expected_id:
            raise ValueError("Backup ID does not match the encrypted header.")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or len(entries) > 100000:
            raise ValueError("Backup manifest entries are invalid.")
        expected_names = {"manifest.json"}
        seen_paths = set()
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("Invalid backup file record.")
            rel = _safe_relative(item.get("path", ""))
            if rel in seen_paths:
                raise ValueError("Duplicate destination path in backup manifest.")
            seen_paths.add(rel)
            archive_name = _safe_relative(item.get("archive_path", ""))
            if not archive_name.startswith("payload/"):
                raise ValueError("Invalid payload path in manifest.")
            if item.get("component") not in COMPONENTS:
                raise ValueError("Invalid component in manifest.")
            info = archive.getinfo(archive_name)
            if info.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("Symbolic links are not permitted in backups.")
            expected_names.add(archive_name)
            digest = hashlib.sha256()
            size = 0
            with archive.open(info, "r") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk); size += len(chunk)
            if size != int(item.get("size", -1)) or digest.hexdigest() != item.get("sha256"):
                raise ValueError("A file checksum failed: " + rel)
        if set(names) != expected_names:
            raise ValueError("Archive contains files that are not listed in its manifest.")
        if archive.testzip() is not None:
            raise ValueError("ZIP archive CRC validation failed.")
        return manifest


@contextlib.contextmanager
def unlocked_backup(path: Path, password: str, temp_parent: Path, expected_id: Optional[str] = None):
    with tempfile.TemporaryDirectory(prefix="cartman-unlock-") as work:
        work_path = Path(work)
        try:
            os.chmod(work, 0o700)
        except OSError:
            pass
        zip_path, header = decrypt_to_zip(path, password, work_path)
        manifest = inspect_zip(zip_path, expected_id=expected_id or header.get("backup_id"))
        yield zip_path, manifest, header



def validate_create_selection(database: Path, components: list[str], root: Path):
    """Require the matching Connector encryption key when backing up encrypted Connector rows."""
    if "database" not in components or not database.is_file():
        return
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "cartman_connectors" not in tables:
            return
        count = connection.execute("SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''").fetchone()[0]
    finally:
        connection.close()
    if not count:
        return
    key_path = root / "app" / ".cartman_connector_fernet.key"
    if not key_path.is_file() or key_path.is_symlink():
        raise ValueError("Encrypted Connector credentials exist, but the local Connector encryption key is missing. Resolve the key before creating a portable backup.")
    security_files = collect_component_files(root, database, "security")
    key_relative = "app/.cartman_connector_fernet.key"
    if key_relative not in security_files:
        raise ValueError("The Connector encryption key could not be added to the Security & Credentials component.")
    if "security" not in components:
        raise ValueError("This database contains encrypted Connector credentials. Select Security & Credentials together with Database so the matching key is included.")

def create_bundle(root: Path, database: Path, backup_dir: Path, name: str,
                  components: list[str], password: str, bundle_type: str = "manual"):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # dependency preflight
    del Cipher, algorithms, modes
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Backup password must contain between 12 and 1024 characters.")
    if not isinstance(components, list) or not components or any(not isinstance(x, str) for x in components) or len(set(components)) != len(components) or any(x not in COMPONENTS for x in components):
        raise ValueError("Select one or more valid backup components.")
    validate_create_selection(database, components, root)
    name = str(name or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Backup name is required and must be at most 120 characters.")
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(backup_dir, 0o700)
    except OSError:
        pass

    files_by_component = {comp: collect_component_files(root, database, comp) for comp in components}
    empty = [LABELS[c] for c, files in files_by_component.items() if not files]
    if empty:
        raise ValueError("No files were found for: " + ", ".join(empty))

    backup_id = uuid.uuid4().hex
    created_at = _now()
    with tempfile.TemporaryDirectory(prefix="cartman-build-") as work:
        work_path = Path(work)
        try:
            os.chmod(work, 0o700)
        except OSError:
            pass
        zip_path = work_path / "payload.zip"
        entries = []
        component_info = {}
        seen_paths = set()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for component in components:
                count = 0
                total = 0
                for relative, value in sorted(files_by_component[component].items()):
                    if relative in seen_paths:
                        continue
                    seen_paths.add(relative)
                    source = value["path"]
                    source_to_zip = source
                    if value.get("database"):
                        snapshot = work_path / "cartman-db-snapshot.sqlite3"
                        src_conn = sqlite3.connect(str(database))
                        dst_conn = sqlite3.connect(str(snapshot))
                        try:
                            src_conn.backup(dst_conn, pages=256, sleep=0.05)
                            dst_conn.commit()
                        finally:
                            dst_conn.close(); src_conn.close()
                        source_to_zip = snapshot
                    before = source_to_zip.stat()
                    digest = sha256_file(source_to_zip)
                    archive_name = "payload/" + relative
                    archive.write(source_to_zip, arcname=archive_name)
                    after = source_to_zip.stat()
                    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                        raise ValueError("A file changed during backup creation: " + relative)
                    size = after.st_size
                    mode = int(before.st_mode & 0o777)
                    entry = {"path": relative, "archive_path": archive_name, "component": component,
                             "size": size, "sha256": digest, "mode": mode}
                    entries.append(entry); count += 1; total += size
                component_info[component] = {"name": LABELS[component], "file_count": count, "bytes": total}
            manifest = {
                "format": "cartman-encrypted-backup", "format_version": FORMAT_VERSION,
                "backup_id": backup_id, "name": name, "bundle_type": bundle_type,
                "created_at": created_at, "components": component_info,
                "entries": entries,
                "excluded": [".venv", "node_modules", "__pycache__", ".git", ".backups", ".cartman-backups", "temporary and cache files"],
                "restore_mode": "overlay; files absent from the backup are not deleted",
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        output = backup_dir / ("cartman-" + backup_id + ".cartmanbackup")
        encrypted_temp = backup_dir / (".cartman-" + backup_id + ".encrypted.tmp")
        try:
            _encrypt_file(zip_path, encrypted_temp, password, {
                "backup_id": backup_id, "created_at": created_at,
            })
            try:
                os.chmod(encrypted_temp, 0o600)
            except OSError:
                pass
            os.replace(encrypted_temp, output)
        except Exception:
            try: encrypted_temp.unlink()
            except OSError: pass
            raise
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass
        return {
            "id": backup_id, "created_at": created_at, "bytes": output.stat().st_size,
            "filename": output.name, "bundle_type": bundle_type,
            "components": component_info, "format_version": FORMAT_VERSION,
        }


def list_bundles(backup_dir: Path):
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    items = []
    for path in backup_dir.glob("cartman-*.cartmanbackup"):
        try:
            header, _, _ = read_header(path)
            items.append({
                "id": str(header.get("backup_id") or ""),
                "created_at": str(header.get("created_at") or ""),
                "bytes": path.stat().st_size,
                "filename": path.name,
                "format_version": header.get("format_version"),
                "encrypted": True,
                "integrity": "not_checked",
            })
        except Exception:
            items.append({"id": path.stem, "created_at": "", "bytes": path.stat().st_size,
                          "filename": path.name, "encrypted": True, "integrity": "invalid_header"})
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    legacy_count = sum(1 for _ in backup_dir.glob("cartman-backup-*.zip"))
    return items, legacy_count



def validate_restore_selection(zip_path: Path, manifest: dict, selected: list[str], root: Path):
    """Prevent restoring connector ciphertext without the matching Fernet key."""
    if "database" not in selected:
        return
    db_entry = next((x for x in manifest.get("entries", []) if x.get("path") == "app/cartman.db" and x.get("component") == "database"), None)
    if not db_entry:
        raise ValueError("The selected backup does not contain the Cartman database.")
    with tempfile.TemporaryDirectory(prefix="cartman-db-check-") as work:
        db_path = Path(work) / "check.sqlite3"
        with zipfile.ZipFile(zip_path, "r") as archive, archive.open(db_entry["archive_path"], "r") as source, db_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "cartman_connectors" not in tables:
                return
            encrypted_count = connection.execute(
                "SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''"
            ).fetchone()[0]
        finally:
            connection.close()
    if not encrypted_count:
        return
    key_entry = next((x for x in manifest.get("entries", []) if x.get("path") == "app/.cartman_connector_fernet.key"), None)
    if not key_entry:
        raise ValueError("This database contains encrypted Connector credentials, but the matching encryption key is not in the backup. Include Security & Credentials before using this database recovery point.")
    if "security" not in selected:
        current_key = root / "app" / ".cartman_connector_fernet.key"
        if not current_key.is_file() or current_key.is_symlink() or sha256_file(current_key) != key_entry.get("sha256"):
            raise ValueError("This restore includes encrypted Connector credentials. Select Security & Credentials together with Database so the matching key is restored.")

def safe_bundle_path(backup_dir: Path, backup_id: str):
    if not ID_RE.fullmatch(str(backup_id or "")):
        raise ValueError("Invalid backup ID.")
    path = backup_dir / ("cartman-" + backup_id + ".cartmanbackup")
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("Encrypted backup was not found.")
    return path


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
    pending_path = backup_dir / "restore-pending-v2.json"

    def ensure_repo():
        if backup_dir.exists() and backup_dir.is_symlink():
            raise HTTPException(status_code=500, detail="Backup repository must not be a symbolic link.")
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(backup_dir, 0o700)
        except OSError:
            pass

    def require_admin(request, write=False):
        user = auth_user(request, write=write, sensitive=True)
        ensure_repo()
        return user

    def http_error(exc):
        if isinstance(exc, HTTPException):
            raise exc
        if isinstance(exc, FileNotFoundError):
            raise HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, PermissionError):
            raise HTTPException(status_code=403, detail=str(exc))
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=422, detail=str(exc))
        raise HTTPException(status_code=500, detail="Backup operation failed: " + str(exc))

    def json_password(payload):
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
            raise HTTPException(status_code=422, detail="A backup password of at least 12 characters is required.")
        return password

    @app.get("/api/admin/backups/v2/catalog")
    def backup_v2_catalog(request: Request):
        require_admin(request, write=False)
        try:
            return {"components": component_catalog(root, database), "encryption": "AES-256-GCM", "integrity": "SHA-256", "kdf": "scrypt"}
        except Exception as exc:
            http_error(exc)

    @app.get("/api/admin/backups/v2")
    def backup_v2_list(request: Request):
        require_admin(request, write=False)
        try:
            items, legacy_count = list_bundles(backup_dir)
            return {"items": items, "total": len(items), "legacy_unencrypted_count": legacy_count,
                    "storage_bytes": sum(int(item.get("bytes", 0)) for item in items),
                    "repository": "app/.cartman-backups"}
        except Exception as exc:
            http_error(exc)

    @app.post("/api/admin/backups/v2", status_code=201)
    async def backup_v2_create(request: Request):
        user = require_admin(request, write=True)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="A JSON request body is required.")
        password = json_password(payload)
        confirmation = payload.get("confirm_password")
        if confirmation != password:
            raise HTTPException(status_code=422, detail="Backup password confirmation does not match.")
        name = str(payload.get("name") or "").strip()
        components = payload.get("components")
        if not isinstance(components, list):
            raise HTTPException(status_code=422, detail="Backup components must be a list.")
        try:
            item = create_bundle(root, database, backup_dir, name, components, password)
            with get_connection() as connection:
                audit(connection, user, "backup.encrypted_created", "backup", item["id"],
                      {"name": name, "components": sorted(components), "format_version": FORMAT_VERSION})
            return {"item": item, "encryption": "AES-256-GCM", "integrity": "SHA-256"}
        except Exception as exc:
            http_error(exc)

    @app.post("/api/admin/backups/v2/{backup_id}/unlock")
    async def backup_v2_unlock(backup_id: str, request: Request):
        require_admin(request, write=False)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="A JSON request body is required.")
        password = json_password(payload)
        try:
            path = safe_bundle_path(backup_dir, backup_id)
            with unlocked_backup(path, password, backup_dir, expected_id=backup_id) as (_, manifest, header):
                return {"backup": {"id": backup_id, "created_at": header.get("created_at"),
                                   "bytes": path.stat().st_size, "name": manifest.get("name"),
                                   "bundle_type": manifest.get("bundle_type"), "encrypted": True,
                                   "integrity": "verified", "encryption": "AES-256-GCM", "hash": "SHA-256"},
                        "manifest": manifest}
        except Exception as exc:
            http_error(exc)

    @app.get("/api/admin/backups/v2/{backup_id}/download")
    def backup_v2_download(backup_id: str, request: Request):
        require_admin(request, write=False)
        try:
            path = safe_bundle_path(backup_dir, backup_id)
            return FileResponse(str(path), media_type="application/octet-stream", filename=path.name)
        except Exception as exc:
            http_error(exc)

    @app.post("/api/admin/backups/v2/{backup_id}/restore-prepare")
    async def backup_v2_restore_prepare(backup_id: str, request: Request):
        user = require_admin(request, write=True)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="A JSON request body is required.")
        password = json_password(payload)
        selected = payload.get("components")
        if not isinstance(selected, list) or not selected or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected) or any(x not in COMPONENTS for x in selected):
            raise HTTPException(status_code=422, detail="Choose one or more valid restore components.")
        try:
            backup_path = safe_bundle_path(backup_dir, backup_id)
            with unlocked_backup(backup_path, password, backup_dir, expected_id=backup_id) as (zip_path, manifest, _header):
                included = set(manifest.get("components", {}).keys())
                if not set(selected).issubset(included):
                    raise ValueError("A selected restore component is not included in this backup.")
                validate_restore_selection(zip_path, manifest, selected, root)
                pending = {
                    "format_version": FORMAT_VERSION, "backup_id": backup_id,
                    "archive_sha256": sha256_file(backup_path), "components": sorted(selected),
                    "prepared_at": _now(), "prepared_by": actor(user),
                }
            backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = pending_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(pending, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            try: os.chmod(temporary, 0o600)
            except OSError: pass
            os.replace(temporary, pending_path)
            with get_connection() as connection:
                audit(connection, user, "backup.restore_prepared", "backup", backup_id,
                      {"components": sorted(selected)})
            return {"prepared": True, "message": "Restore validated and staged. Stop Cartman before applying the offline restore command.",
                    "restore": pending, "command": ".venv/bin/python scripts/cartman_restore_encrypted.py --apply-pending --confirm-server-stopped"}
        except Exception as exc:
            http_error(exc)

    @app.get("/api/admin/backups/v2/restore-pending")
    def backup_v2_pending_get(request: Request):
        require_admin(request, write=False)
        if not pending_path.is_file() or pending_path.is_symlink():
            return {"pending": False, "restore": None}
        try:
            value = json.loads(pending_path.read_text(encoding="utf-8"))
            return {"pending": True, "restore": {**value,
                    "command": ".venv/bin/python scripts/cartman_restore_encrypted.py --apply-pending --confirm-server-stopped"}}
        except Exception:
            raise HTTPException(status_code=500, detail="Pending restore manifest is invalid.")

    @app.delete("/api/admin/backups/v2/restore-pending")
    def backup_v2_pending_delete(request: Request):
        user = require_admin(request, write=True)
        if pending_path.is_symlink():
            raise HTTPException(status_code=500, detail="Pending restore path is unsafe.")
        if pending_path.exists():
            pending_path.unlink()
            with get_connection() as connection:
                audit(connection, user, "backup.restore_cancelled", "backup", "pending", {})
        return {"cancelled": True}
