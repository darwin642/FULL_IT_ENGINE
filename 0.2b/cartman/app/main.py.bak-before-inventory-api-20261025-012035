from pathlib import Path
import json
import secrets
import base64
import sqlite3
import uuid
import ipaddress
import socket
import socketserver
import threading
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from typing import Optional


app = FastAPI(title="Cartman")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
FRONTEND = STATIC_DIR / "index.html"
DATABASE = BASE_DIR / "cartman.db"


app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)

VALID_STATUSES = {"Online", "Warning", "Offline"}


def get_connection():
    connection = sqlite3.connect(str(DATABASE))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                os TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Online',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        device_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(devices)")
        }
        for column, definition in {
            "public_ip": "TEXT NOT NULL DEFAULT ''",
            "local_ip": "TEXT NOT NULL DEFAULT ''",
            "username": "TEXT NOT NULL DEFAULT ''",
            "model": "TEXT NOT NULL DEFAULT ''",
            "manufacturer": "TEXT NOT NULL DEFAULT ''",
            "device_type": "TEXT NOT NULL DEFAULT 'Workstation'",
            "cpu": "TEXT NOT NULL DEFAULT ''",
            "ram": "TEXT NOT NULL DEFAULT ''",
            "disk": "TEXT NOT NULL DEFAULT ''",
            "gpu": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in device_columns:
                connection.execute(
                    f"ALTER TABLE devices ADD COLUMN {column} {definition}"
                )

        connection.executescript("""
            CREATE TABLE IF NOT EXISTS device_connection_requests (
                id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                os TEXT NOT NULL,
                client_ip TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending'
                    CHECK (status IN ('Pending', 'Approved', 'Rejected')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                device_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_device_requests_status_time
            ON device_connection_requests(status, created_at DESC);
        """)

        request_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(device_connection_requests)"
            ).fetchall()
        }
        if "metadata_json" not in request_columns:
            connection.execute(
                "ALTER TABLE device_connection_requests "
                "ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
            )

        connection.execute("""
            CREATE TABLE IF NOT EXISTS software_catalog (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                publisher TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT 'Unknown',
                target_os TEXT NOT NULL DEFAULT 'Any',
                category TEXT NOT NULL DEFAULT 'General',
                package_type TEXT NOT NULL DEFAULT 'Other',
                install_command TEXT NOT NULL DEFAULT '',
                uninstall_command TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, version, target_os)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS software_audit_history (
                id TEXT PRIMARY KEY,
                software_id TEXT NOT NULL,
                software_name TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                details_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_software_audit_time
            ON software_audit_history(occurred_at DESC)
        """)


        connection.executescript("""
            CREATE TABLE IF NOT EXISTS monitoring_metrics (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'unknown',
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_monitoring_metrics_device_time
            ON monitoring_metrics(device_id, collected_at DESC);

            CREATE TABLE IF NOT EXISTS monitoring_events (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'Info',
                message TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_monitoring_events_time
            ON monitoring_events(occurred_at DESC);

            CREATE TABLE IF NOT EXISTS monitoring_alerts (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'Warning',
                status TEXT NOT NULL DEFAULT 'Open',
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                acknowledged_at TEXT,
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_status
            ON monitoring_alerts(status, created_at DESC);

            CREATE TABLE IF NOT EXISTS availability_checks (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                response_ms REAL,
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_availability_checks_device_time
            ON availability_checks(device_id, checked_at DESC);

            CREATE TABLE IF NOT EXISTS service_checks (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                status TEXT NOT NULL,
                response_ms REAL,
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_service_checks_device_time
            ON service_checks(device_id, checked_at DESC);
        """)

        existing_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(software_catalog)"
            ).fetchall()
        }
        if "created_by" not in existing_columns:
            connection.execute(
                "ALTER TABLE software_catalog ADD COLUMN "
                "created_by TEXT NOT NULL DEFAULT 'Unknown operator'"
            )
        if "updated_by" not in existing_columns:
            connection.execute(
                "ALTER TABLE software_catalog ADD COLUMN "
                "updated_by TEXT NOT NULL DEFAULT 'Unknown operator'"
            )



initialize_database()


class DeviceInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    os: str = Field(..., min_length=1, max_length=150)
    ip: str = Field(default="", max_length=100)
    public_ip: str = Field(default="", max_length=100)
    local_ip: str = Field(default="", max_length=100)
    username: str = Field(default="", max_length=150)
    model: str = Field(default="", max_length=180)
    manufacturer: str = Field(default="", max_length=180)
    device_type: str = Field(default="Workstation", max_length=60)
    cpu: str = Field(default="", max_length=180)
    ram: str = Field(default="", max_length=80)
    disk: str = Field(default="", max_length=80)
    gpu: str = Field(default="", max_length=180)
    status: str = "Online"
    tags: list[str] = Field(default_factory=list)

    @validator(
        "name", "os", "ip", "public_ip", "local_ip", "username",
        "model", "manufacturer", "device_type", "cpu", "ram", "disk", "gpu"
    )
    def strip_text(cls, value):
        return value.strip()

    @validator("name", "os")
    def required_text(cls, value):
        if not value:
            raise ValueError("This field cannot be empty")
        return value

    @validator("status")
    def validate_status(cls, value):
        if value not in VALID_STATUSES:
            raise ValueError("Status must be Online, Warning or Offline")
        return value

    @validator("tags")
    def validate_tags(cls, value):
        if len(value) > 100:
            raise ValueError("Too many tags")
        cleaned = []
        for tag in value:
            if not isinstance(tag, str) or not tag.strip():
                continue
            tag = tag.strip()
            if len(tag) > 100:
                raise ValueError("Tag is too long")
            if tag not in cleaned:
                cleaned.append(tag)
        return cleaned


class SoftwareInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=180)
    publisher: str = Field(default="", max_length=180)
    version: str = Field(default="Unknown", max_length=80)
    target_os: str = Field(default="Any", max_length=40)
    category: str = Field(default="General", max_length=80)
    package_type: str = Field(default="Other", max_length=40)
    install_command: str = Field(default="", max_length=2000)
    uninstall_command: str = Field(default="", max_length=2000)
    source_url: str = Field(default="", max_length=1000)
    status: str = "Active"
    notes: str = Field(default="", max_length=5000)

    @validator(
        "name", "publisher", "version", "target_os", "category",
        "package_type", "install_command", "uninstall_command",
        "source_url", "notes"
    )
    def strip_software_text(cls, value):
        return value.strip()

    @validator("name")
    def require_software_name(cls, value):
        if not value:
            raise ValueError("Software name cannot be empty")
        return value

    @validator("status")
    def validate_software_status(cls, value):
        if value not in {"Active", "Draft", "Deprecated"}:
            raise ValueError("Status must be Active, Draft or Deprecated")
        return value


def serialize_software(row):
    return dict(row)


def serialize_device(row):
    device = dict(row)
    device["tags"] = json.loads(device["tags"])
    device.setdefault("model", "")
    device.setdefault("manufacturer", "")
    device.setdefault("device_type", "Workstation")
    device["type"] = device.get("device_type") or "Workstation"
    device.setdefault("cpu", "")
    device.setdefault("ram", "")
    device.setdefault("disk", "")
    device.setdefault("gpu", "")
    return device




@app.get("/", response_class=HTMLResponse)
def home():
    return FRONTEND.read_text(encoding="utf-8")


@app.get("/pages/inventory/", response_class=HTMLResponse)
def inventory_page():
    return (STATIC_DIR / "pages" / "inventory.html").read_text(
        encoding="utf-8"
    )


@app.get("/pages/{slug}/", response_class=HTMLResponse)
def standalone_module_page(slug: str):
    if not slug or any(
        not (character.islower() or character.isdigit() or character == "-")
        for character in slug
    ):
        raise HTTPException(status_code=404, detail="Page not found")

    page_file = STATIC_DIR / "pages" / slug / "index.html"

    if not page_file.is_file():
        raise HTTPException(status_code=404, detail="Page not found")

    return page_file.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1")
        return {
            "app": "Cartman",
            "status": "online",
            "database": "connected",
        }
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )



def normalize_operator(value):
    value = (value or "").strip()
    if not value:
        return "Unidentified operator"
    return value[:120]


def write_software_audit(connection, software_id, software_name,
                         action, actor, details):
    connection.execute(
        "INSERT INTO software_audit_history "
        "(id, software_id, software_name, action, actor, details_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "audit-" + uuid.uuid4().hex,
            software_id,
            software_name,
            action,
            actor,
            json.dumps(details, ensure_ascii=False),
        ),
    )


def serialize_audit(row):
    result = dict(row)
    raw = result.pop("details_json", "{}")
    try:
        result["details"] = json.loads(raw)
    except (TypeError, ValueError):
        result["details"] = {}
    return result


@app.get("/api/software")
def list_software():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM software_catalog "
            "ORDER BY name COLLATE NOCASE, version COLLATE NOCASE"
        ).fetchall()
    return [serialize_software(row) for row in rows]


@app.get("/api/software/{software_id}")
def get_software(software_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM software_catalog WHERE id = ?",
            (software_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Software not found")
    return serialize_software(row)


@app.post("/api/software", status_code=201)
def create_software(
    software: SoftwareInput,
    x_operator: str = Header(default="Unidentified operator", alias="X-Operator"),
):
    software_id = "software-" + uuid.uuid4().hex
    actor = normalize_operator(x_operator)
    values = software.dict()

    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO software_catalog "
                "(id, name, publisher, version, target_os, category, "
                "package_type, install_command, uninstall_command, source_url, "
                "status, notes, created_by, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    software_id, values["name"], values["publisher"],
                    values["version"], values["target_os"], values["category"],
                    values["package_type"], values["install_command"],
                    values["uninstall_command"], values["source_url"],
                    values["status"], values["notes"], actor, actor,
                ),
            )
            write_software_audit(
                connection, software_id, values["name"],
                "Created", actor, {"values": values},
            )
            row = connection.execute(
                "SELECT * FROM software_catalog WHERE id = ?",
                (software_id,),
            ).fetchone()
        return serialize_software(row)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Software with this name, version and OS already exists",
        )


@app.put("/api/software/{software_id}")
def update_software(
    software_id: str,
    software: SoftwareInput,
    x_operator: str = Header(default="Unidentified operator", alias="X-Operator"),
):
    actor = normalize_operator(x_operator)
    values = software.dict()

    try:
        with get_connection() as connection:
            old = connection.execute(
                "SELECT * FROM software_catalog WHERE id = ?",
                (software_id,),
            ).fetchone()

            if old is None:
                raise HTTPException(status_code=404, detail="Software not found")

            old_values = dict(old)
            changed = {
                key: {"old": old_values.get(key), "new": value}
                for key, value in values.items()
                if old_values.get(key) != value
            }

            connection.execute(
                "UPDATE software_catalog SET "
                "name = ?, publisher = ?, version = ?, target_os = ?, "
                "category = ?, package_type = ?, install_command = ?, "
                "uninstall_command = ?, source_url = ?, status = ?, notes = ?, "
                "updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (
                    values["name"], values["publisher"], values["version"],
                    values["target_os"], values["category"],
                    values["package_type"], values["install_command"],
                    values["uninstall_command"], values["source_url"],
                    values["status"], values["notes"], actor, software_id,
                ),
            )

            if changed:
                write_software_audit(
                    connection, software_id, values["name"],
                    "Updated", actor, {"changes": changed},
                )

            row = connection.execute(
                "SELECT * FROM software_catalog WHERE id = ?",
                (software_id,),
            ).fetchone()
        return serialize_software(row)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Software with this name, version and OS already exists",
        )


@app.delete("/api/software/{software_id}")
def delete_software(
    software_id: str,
    x_operator: str = Header(default="Unidentified operator", alias="X-Operator"),
):
    actor = normalize_operator(x_operator)

    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM software_catalog WHERE id = ?",
            (software_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Software not found")

        snapshot = dict(row)
        write_software_audit(
            connection,
            software_id,
            snapshot["name"],
            "Deleted",
            actor,
            {"values": snapshot},
        )
        connection.execute(
            "DELETE FROM software_catalog WHERE id = ?",
            (software_id,),
        )

    return {"deleted": True, "id": software_id}


@app.get("/api/software-audit")
def list_software_audit(
    limit: int = 100,
    software_id: str = "",
    action: str = "",
    q: str = "",
):
    limit = max(1, min(limit, 500))
    clauses = []
    params = []

    if software_id:
        clauses.append("software_id = ?")
        params.append(software_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if q.strip():
        clauses.append("(software_name LIKE ? OR actor LIKE ?)")
        needle = "%" + q.strip()[:120] + "%"
        params.extend([needle, needle])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT id, software_id, software_name, action, actor, "
        "occurred_at, details_json FROM software_audit_history"
        + where
        + " ORDER BY occurred_at DESC, rowid DESC LIMIT ?"
    )
    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()

    return [serialize_audit(row) for row in rows]




class DeviceConnectionRequestInput(BaseModel):
    device_name: str = Field(..., min_length=1, max_length=150)
    os: str = Field(..., min_length=1, max_length=150)
    client_ip: str = Field(default="", max_length=100)
    username: str = Field(default="", max_length=150)

    @validator("device_name", "os", "client_ip", "username")
    def strip_request_text(cls, value):
        return value.strip()

    @validator("device_name", "os")
    def require_request_text(cls, value):
        if not value:
            raise ValueError("This field cannot be empty")
        return value


class DeviceConnectionDecisionInput(BaseModel):
    decision: str

    @validator("decision")
    def validate_decision(cls, value):
        if value not in {"Approved", "Rejected"}:
            raise ValueError("Decision must be Approved or Rejected")
        return value





# Persistent, allowlisted endpoint task queue.
with get_connection() as connection:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS device_tasks (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (
                action IN (
                    'package_deployment',
                    'shutdown',
                    'network_disconnect',
                    'vpn_action',
                    'self_test'
                )
            ),
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'Queued' CHECK (
                status IN (
                    'Queued', 'Dispatched', 'Running',
                    'Succeeded', 'Failed', 'Cancelled'
                )
            ),
            result TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_device_tasks_status_created
        ON device_tasks(status, created_at)
    """)



# Migrate the existing task queue to allow the safe agent self-test.
# Existing task records and results are copied without modification.
with get_connection() as connection:
    task_table = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='device_tasks'"
    ).fetchone()

    task_schema_sql = (task_table["sql"] or "") if task_table else ""

    if "'self_test'" not in task_schema_sql:
        connection.execute("""
            CREATE TABLE device_tasks_new (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (
                    action IN (
                        'package_deployment',
                        'shutdown',
                        'network_disconnect',
                        'vpn_action',
                        'self_test'
                    )
                ),
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'Queued' CHECK (
                    status IN (
                        'Queued', 'Dispatched', 'Running',
                        'Succeeded', 'Failed', 'Cancelled'
                    )
                ),
                result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT
            )
        """)

        connection.execute("""
            INSERT INTO device_tasks_new (
                id, device_id, action, payload, status, result,
                created_at, started_at, finished_at
            )
            SELECT
                id, device_id, action, payload, status, result,
                created_at, started_at, finished_at
            FROM device_tasks
        """)

        connection.execute("DROP TABLE device_tasks")
        connection.execute(
            "ALTER TABLE device_tasks_new RENAME TO device_tasks"
        )

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_device_tasks_status_created
            ON device_tasks(status, created_at)
        """)


with get_connection() as connection:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS device_agent_credentials (
            client_instance TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            public_key TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_device_agent_credentials_device
        ON device_agent_credentials(device_id)
    """)


def normalize_os_family(value):
    value = str(value or "").strip().lower()
    if value in {"any", "*"}:
        return "Any"
    if "windows" in value or value.startswith("win"):
        return "Windows"
    if any(term in value for term in ("macos", "mac os", "darwin", "os x")):
        return "macOS"
    if any(term in value for term in (
        "linux", "ubuntu", "debian", "fedora", "centos", "rhel",
        "red hat", "suse", "arch", "mint"
    )):
        return "Linux"
    return "Unknown"


class DeviceTaskInput(BaseModel):
    action: str
    payload: dict = Field(default_factory=dict)

    @validator("action")
    def validate_action(cls, value):
        allowed = {
            "package_deployment",
            "shutdown",
            "network_disconnect",
            "vpn_action",
            "self_test",
        }
        if value not in allowed:
            raise ValueError("Unsupported device task action")
        return value


# CartmanClient TCP listener.
# It accepts device metadata only; it never executes remote commands.
DEVICE_CONNECTION_PORT = 50101
_connection_listener_server = None
_connection_listener_thread = None
_connection_listener_mode = None
_connection_listener_lock = threading.Lock()
_connection_clients = {}
_connection_clients_lock = threading.Lock()


def _cartman_local_ip():
    """Return the local IPv4 address used for outbound network routing."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects a route; it does not send application data.
        probe.connect(("192.0.2.1", 80))
        address = probe.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        probe.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                return address
    except OSError:
        pass
    return ""


def _cartman_public_ip():
    """Resolve the outward-facing IP only for display; failure is non-fatal."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=2) as response:
            value = response.read(64).decode("ascii").strip()
        ipaddress.ip_address(value)
        return value
    except Exception:
        return ""


class _CartmanConnectionHandler(socketserver.StreamRequestHandler):
    def _reply(self, value):
        try:
            self.wfile.write((json.dumps(value) + "\n").encode("utf-8"))
            self.wfile.flush()
        except OSError:
            pass

    def _utc_now(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _claim_task(self, device_id):
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, action, payload
                FROM device_tasks
                WHERE device_id = ? AND status = 'Queued'
                ORDER BY created_at, rowid
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()

            if row is None:
                return None

            cursor = connection.execute(
                """
                UPDATE device_tasks
                SET status = 'Running', started_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'Queued'
                """,
                (row["id"],),
            )
            if cursor.rowcount != 1:
                return None

            try:
                payload = json.loads(row["payload"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}

            execution = {}
            if row["action"] == "package_deployment":
                package = connection.execute(
                    """
                    SELECT install_command, name, version
                    FROM software_catalog WHERE id = ?
                    """,
                    (payload.get("software_id"),),
                ).fetchone()
                if package:
                    execution = {
                        "install_command": package["install_command"] or "",
                        "package_name": package["name"],
                        "package_version": package["version"],
                    }

            return {
                "id": row["id"],
                "action": row["action"],
                "payload": payload,
                "execution": execution,
            }

    def _save_task_result(self, request_id, message):
        status = message.get("result_status")
        task_id = message.get("task_id")
        result = message.get("result", "")

        if status not in {"Succeeded", "Failed"}:
            self._reply({"status": "error", "message": "Invalid task result status."})
            return

        if not isinstance(task_id, str) or not task_id:
            self._reply({"status": "error", "message": "Missing task_id."})
            return

        if not isinstance(result, str):
            result = str(result)
        result = result[:5000]

        with get_connection() as connection:
            enrollment = connection.execute(
                """
                SELECT status, device_id
                FROM device_connection_requests WHERE id = ?
                """,
                (request_id,),
            ).fetchone()

            if (
                enrollment is None
                or enrollment["status"] != "Approved"
                or not enrollment["device_id"]
            ):
                self._reply({"status": "error", "message": "Device enrollment is not approved."})
                return

            cursor = connection.execute(
                """
                UPDATE device_tasks
                SET status = ?, result = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ? AND device_id = ? AND status = 'Running'
                """,
                (status, result, task_id, enrollment["device_id"]),
            )

        if cursor.rowcount != 1:
            self._reply({
                "status": "error",
                "message": "Task was not found, was already completed, or belongs to another device.",
            })
            return

        with _connection_clients_lock:
            for item in _connection_clients.values():
                if item.get("request_id") == request_id:
                    item["last_task_id"] = task_id
                    item["last_task_status"] = status
                    item["last_task_result"] = result[:500]

        self._reply({"status": "task_result_accepted", "task_id": task_id})

    def handle(self):
        self.request.settimeout(75)
        request_id = None
        connection_id = None

        try:
            raw = self.rfile.readline(8193)
            if not raw or len(raw) > 8192 or not raw.endswith(b"\n"):
                self._reply({"status": "error", "message": "Expected one JSON line (maximum 8192 bytes)."})
                return

            try:
                hello = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._reply({"status": "error", "message": "Invalid JSON."})
                return

            if not isinstance(hello, dict) or hello.get("type", "hello") != "hello":
                self._reply({"status": "error", "message": "First message must be a hello."})
                return

            name = hello.get("device_name")
            os_name = hello.get("os")
            username = hello.get("username", "")

            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                self._reply({"status": "error", "message": "device_name is required (maximum 120 characters)."})
                return
            if not isinstance(os_name, str) or not os_name.strip() or len(os_name.strip()) > 120:
                self._reply({"status": "error", "message": "os is required (maximum 120 characters)."})
                return
            if not isinstance(username, str) or len(username) > 120:
                username = ""

            task_execution_enabled = hello.get("task_execution_enabled") is True

            client_instance = hello.get("client_instance")
            public_key_text = hello.get("public_key")

            try:
                if not isinstance(client_instance, str):
                    raise ValueError("Missing persistent client ID.")
                client_instance = str(uuid.UUID(client_instance))
                if not isinstance(public_key_text, str):
                    raise ValueError("Missing client public key.")
                public_key_bytes = base64.b64decode(
                    public_key_text, validate=True
                )
                if len(public_key_bytes) != 32:
                    raise ValueError("Invalid public key length.")
            except (ValueError, TypeError, AttributeError):
                self._reply({
                    "status": "error",
                    "message": (
                        "This CartmanClient version has no valid persistent identity. "
                        "Update the client before connecting."
                    ),
                })
                return

            hardware = {}
            for key in ("model", "manufacturer", "device_type", "cpu", "ram", "disk", "gpu"):
                value = hello.get(key, "")
                hardware[key] = value.strip()[:180] if isinstance(value, str) else ""

            identity_metadata = dict(hardware)
            identity_metadata["client_instance"] = client_instance
            identity_metadata["public_key"] = public_key_text

            connection_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            client_ip = str(self.client_address[0])[:64]

            with get_connection() as connection:
                trusted = connection.execute(
                    """
                    SELECT device_id, public_key, revoked
                    FROM device_agent_credentials
                    WHERE client_instance = ?
                    """,
                    (client_instance,),
                ).fetchone()

            device_id = None
            approval = "Pending"

            if trusted is not None:
                if trusted["revoked"]:
                    self._reply({
                        "status": "error",
                        "message": "This CartmanClient identity has been revoked.",
                    })
                    return

                if trusted["public_key"] != public_key_text:
                    self._reply({
                        "status": "error",
                        "message": "Client identity key mismatch. Connection refused.",
                    })
                    return

                challenge = secrets.token_bytes(32)
                self._reply({
                    "status": "challenge",
                    "nonce": base64.b64encode(challenge).decode("ascii"),
                })

                raw_auth = self.rfile.readline(8193)
                if not raw_auth or len(raw_auth) > 8192 or not raw_auth.endswith(b"\n"):
                    self._reply({
                        "status": "error",
                        "message": "Missing or invalid identity proof.",
                    })
                    return

                try:
                    auth_message = json.loads(raw_auth.decode("utf-8"))
                    if not isinstance(auth_message, dict) or auth_message.get("type") != "authenticate":
                        raise ValueError("Invalid authentication message.")
                    signature = base64.b64decode(
                        auth_message.get("signature", ""), validate=True
                    )
                    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                    Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                        signature, challenge
                    )
                except Exception:
                    self._reply({
                        "status": "error",
                        "message": "Client identity verification failed.",
                    })
                    return

                device_id = trusted["device_id"]
                with get_connection() as connection:
                    device = connection.execute(
                        "SELECT id FROM devices WHERE id = ?",
                        (device_id,),
                    ).fetchone()

                    if device is None:
                        self._reply({
                            "status": "error",
                            "message": (
                                "The registered inventory device no longer exists. "
                                "Administrator re-enrollment is required."
                            ),
                        })
                        return

                    connection.execute(
                        """
                        UPDATE devices
                        SET os = ?, ip = ?, local_ip = ?, username = ?,
                            status = 'Online', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (os_name.strip(), client_ip, client_ip, username.strip(), device_id),
                    )
                    connection.execute(
                        """
                        UPDATE device_agent_credentials
                        SET last_seen = CURRENT_TIMESTAMP
                        WHERE client_instance = ?
                        """,
                        (client_instance,),
                    )
                    connection.execute(
                        """
                        INSERT INTO device_connection_requests
                            (id, device_name, os, client_ip, username,
                             status, reviewed_at, device_id, metadata_json)
                        VALUES (?, ?, ?, ?, ?, 'Approved', CURRENT_TIMESTAMP, ?, ?)
                        """,
                        (
                            request_id, name.strip(), os_name.strip(), client_ip,
                            username.strip(), device_id,
                            json.dumps(identity_metadata, ensure_ascii=False),
                        ),
                    )

                approval = "Approved"

            else:
                with get_connection() as connection:
                    connection.execute(
                        """
                        INSERT INTO device_connection_requests
                            (id, device_name, os, client_ip, username, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            request_id, name.strip(), os_name.strip(), client_ip,
                            username.strip(),
                            json.dumps(identity_metadata, ensure_ascii=False),
                        ),
                    )

            now = self._utc_now()

            with _connection_clients_lock:
                _connection_clients[connection_id] = {
                    "connection_id": connection_id,
                    "request_id": request_id,
                    "device_id": device_id,
                    "client_instance": client_instance,
                    "device_name": name.strip(),
                    "os": os_name.strip(),
                    "username": username.strip(),
                    "client_ip": client_ip,
                    "connected": True,
                    "state": "Connected" if approval == "Approved"
                        else "Connected · awaiting approval",
                    "approval_status": approval,
                    "task_execution_enabled": task_execution_enabled,
                    "connected_at": now,
                    "last_seen": now,
                }

            self._reply({
                "status": "connected",
                "approval_status": approval,
                "request_id": request_id,
                "device_id": device_id,
                "message": (
                    "Authenticated existing device session."
                    if approval == "Approved"
                    else "New client identity; awaiting administrator approval."
                ),
            })

            # Allow long-running approved tasks to report their final result.
            self.request.settimeout(None)

            while True:
                raw = self.rfile.readline(8193)
                if not raw:
                    break
                if len(raw) > 8192 or not raw.endswith(b"\n"):
                    self._reply({"status": "error", "message": "Invalid message size or line ending."})
                    break

                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._reply({"status": "error", "message": "Invalid JSON."})
                    break

                if not isinstance(message, dict):
                    self._reply({"status": "error", "message": "Expected a JSON object."})
                    break

                message_type = message.get("type")

                if message_type == "heartbeat":
                    with get_connection() as connection:
                        enrollment = connection.execute(
                            """
                            SELECT status, device_id
                            FROM device_connection_requests WHERE id = ?
                            """,
                            (request_id,),
                        ).fetchone()

                    if enrollment is None or enrollment["status"] == "Rejected":
                        self._reply({
                            "status": "rejected",
                            "message": "Cartman administrator rejected this device request.",
                        })
                        break

                    approval = enrollment["status"]
                    device_id = enrollment["device_id"]
                    now = self._utc_now()

                    with _connection_clients_lock:
                        current = _connection_clients.get(connection_id)
                        if current:
                            current["last_seen"] = now
                            current["approval_status"] = approval
                            current["state"] = (
                                "Connected · awaiting approval"
                                if approval == "Pending"
                                else "Connected"
                            )

                    task = None
                    if approval == "Approved" and device_id and task_execution_enabled:
                        try:
                            task = self._claim_task(device_id)
                        except Exception as exc:
                            print("Could not dispatch a device task:", type(exc).__name__, str(exc))

                    self._reply({
                        "status": "connected",
                        "approval_status": approval,
                        "last_seen": now,
                        "task": task,
                    })

                elif message_type == "task_result":
                    self._save_task_result(request_id, message)

                elif message_type == "disconnect":
                    self._reply({"status": "disconnected"})
                    break

                else:
                    self._reply({
                        "status": "error",
                        "message": "Supported messages: heartbeat, task_result, disconnect.",
                    })

        except (OSError, TimeoutError):
            pass
        except Exception as exc:
            print("CartmanClient connection error:", type(exc).__name__, str(exc))
        finally:
            if connection_id:
                with _connection_clients_lock:
                    current = _connection_clients.get(connection_id)
                    if current:
                        current["connected"] = False
                        current["state"] = (
                            "Rejected · disconnected"
                            if current.get("approval_status") == "Rejected"
                            else "Disconnected"
                        )
                        current["last_seen"] = self._utc_now()


class _CartmanTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


class DeviceListenerStartInput(BaseModel):
    address_mode: str = "local"


@app.get("/api/device-connection-listener/status")
def device_connection_listener_status():
    server = _connection_listener_server
    thread = _connection_listener_thread
    return {
        "running": bool(server and thread and thread.is_alive()),
        "port": DEVICE_CONNECTION_PORT,
        "mode": _connection_listener_mode,
        "listen_address": str(server.server_address[0]) if server else "",
        "local_ip": _cartman_local_ip(),
        "public_ip": _cartman_public_ip(),
        "public_listening_enabled": False,
    }


@app.post("/api/device-connection-listener/start")
def start_device_connection_listener(payload: DeviceListenerStartInput):
    global _connection_listener_server
    global _connection_listener_thread
    global _connection_listener_mode

    if payload.address_mode != "local":
        raise HTTPException(
            status_code=409,
            detail=(
                "Public listening is disabled until authenticated, encrypted "
                "client connections are implemented. The public IP is shown "
                "for planning only; port forwarding would also be required."
            ),
        )

    local_ip = _cartman_local_ip()
    if not local_ip:
        raise HTTPException(
            status_code=503,
            detail="Could not detect a local network IPv4 address.",
        )

    with _connection_listener_lock:
        if (
            _connection_listener_server is not None
            and _connection_listener_thread is not None
            and _connection_listener_thread.is_alive()
        ):
            server = _connection_listener_server
            return {
                "running": True,
                "mode": _connection_listener_mode,
                "listen_address": str(server.server_address[0]),
                "port": DEVICE_CONNECTION_PORT,
            }

        try:
            server = _CartmanTCPServer(
                (local_ip, DEVICE_CONNECTION_PORT),
                _CartmanConnectionHandler,
            )
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Could not listen on {local_ip}:{DEVICE_CONNECTION_PORT}. "
                    f"The port may already be in use, or macOS may be blocking it. "
                    f"Details: {exc}"
                ),
            )

        thread = threading.Thread(
            target=server.serve_forever,
            name="cartman-device-listener",
            daemon=True,
        )
        _connection_listener_server = server
        _connection_listener_thread = thread
        _connection_listener_mode = "local"
        thread.start()

    return {
        "running": True,
        "mode": "local",
        "listen_address": local_ip,
        "port": DEVICE_CONNECTION_PORT,
    }


@app.post("/api/device-connection-listener/stop")
def stop_device_connection_listener():
    global _connection_listener_server
    global _connection_listener_thread
    global _connection_listener_mode

    with _connection_listener_lock:
        server = _connection_listener_server
        _connection_listener_server = None
        _connection_listener_thread = None
        _connection_listener_mode = None

    if server is not None:
        server.shutdown()
        server.server_close()

    return {"running": False, "port": DEVICE_CONNECTION_PORT}




@app.get("/api/device-connection-clients")
def list_device_connection_clients():
    with _connection_clients_lock:
        clients = [dict(item) for item in _connection_clients.values()]
    clients.sort(key=lambda item: item.get("connected_at", ""), reverse=True)
    return clients
@app.post("/api/device-connection-requests/{request_id}/decision")
def decide_device_connection_request(
    request_id: str,
    decision: DeviceConnectionDecisionInput,
    request: Request,
):
    # Development safeguard: without administrator authentication, only
    # the local Cartman machine may approve or reject enrollment requests.
    peer = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback:
            raise HTTPException(
                status_code=403,
                detail="Device approvals are currently restricted to the local Cartman machine.",
            )
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Could not verify that this approval request originated locally.",
        )

    with _connection_clients_lock:
        live_connection = any(
            client.get("request_id") == request_id and client.get("connected")
            for client in _connection_clients.values()
        )

    device_id = None
    device_name = None
    device_status = None

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT id, device_name, os, client_ip, username, status,
                   metadata_json
            FROM device_connection_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Connection request not found.")

        if row["status"] != "Pending":
            raise HTTPException(
                status_code=409,
                detail="This connection request has already been reviewed.",
            )

        device_name = row["device_name"]
        try:
            hardware = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError):
            hardware = {}
        if not isinstance(hardware, dict):
            hardware = {}
        for key in ("model", "manufacturer", "device_type", "cpu", "ram", "disk", "gpu"):
            value = hardware.get(key, "")
            hardware[key] = value.strip()[:180] if isinstance(value, str) else ""
        hardware["device_type"] = hardware["device_type"] or "Workstation"

        if decision.decision == "Approved":
            remote_ip = (row["client_ip"] or "").strip()
            local_ip = ""
            public_ip = ""

            if remote_ip:
                try:
                    parsed_ip = ipaddress.ip_address(remote_ip.split("%", 1)[0])
                    if parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local:
                        local_ip = remote_ip
                    else:
                        public_ip = remote_ip
                except ValueError:
                    pass

            existing = connection.execute(
                "SELECT id FROM devices WHERE name = ? COLLATE NOCASE",
                (device_name,),
            ).fetchone()

            if existing:
                # Reuse the existing record; preserve its tags and other metadata.
                device_id = existing["id"]
                connection.execute(
                    """
                    UPDATE devices
                    SET os = ?,
                        model = CASE WHEN ? != '' THEN ? ELSE model END,
                        manufacturer = CASE WHEN ? != '' THEN ? ELSE manufacturer END,
                        device_type = CASE WHEN ? != '' THEN ? ELSE device_type END,
                        cpu = CASE WHEN ? != '' THEN ? ELSE cpu END,
                        ram = CASE WHEN ? != '' THEN ? ELSE ram END,
                        disk = CASE WHEN ? != '' THEN ? ELSE disk END,
                        gpu = CASE WHEN ? != '' THEN ? ELSE gpu END,
                        ip = CASE WHEN ? != '' THEN ? ELSE ip END,
                        local_ip = CASE WHEN ? != '' THEN ? ELSE local_ip END,
                        public_ip = CASE WHEN ? != '' THEN ? ELSE public_ip END,
                        username = CASE WHEN ? != '' THEN ? ELSE username END,
                        status = CASE WHEN ? THEN 'Online' ELSE status END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        row["os"],
                        hardware["model"], hardware["model"],
                        hardware["manufacturer"], hardware["manufacturer"],
                        hardware["device_type"], hardware["device_type"],
                        hardware["cpu"], hardware["cpu"],
                        hardware["ram"], hardware["ram"],
                        hardware["disk"], hardware["disk"],
                        hardware["gpu"], hardware["gpu"],
                        remote_ip, remote_ip,
                        local_ip, local_ip,
                        public_ip, public_ip,
                        row["username"] or "", row["username"] or "",
                        int(live_connection),
                        device_id,
                    ),
                )
                existing_status = connection.execute(
                    "SELECT status FROM devices WHERE id = ?",
                    (device_id,),
                ).fetchone()
                device_status = existing_status["status"]
            else:
                device_id = "device-" + uuid.uuid4().hex
                device_status = "Online" if live_connection else "Offline"
                connection.execute(
                    """
                    INSERT INTO devices (
                        id, name, os, ip, status, tags,
                        public_ip, local_ip, username, model, manufacturer,
                        device_type, cpu, ram, disk, gpu
                    )
                    VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id,
                        device_name,
                        row["os"],
                        remote_ip,
                        device_status,
                        public_ip,
                        local_ip,
                        row["username"] or "",
                        hardware["model"],
                        hardware["manufacturer"],
                        hardware["device_type"],
                        hardware["cpu"],
                        hardware["ram"],
                        hardware["disk"],
                        hardware["gpu"],
                    ),
                )

        if decision.decision == "Approved":
            client_instance = hardware.get("client_instance")
            public_key_text = hardware.get("public_key")

            if client_instance or public_key_text:
                try:
                    client_instance = str(uuid.UUID(client_instance))
                    public_key_bytes = base64.b64decode(
                        public_key_text, validate=True
                    )
                    if len(public_key_bytes) != 32:
                        raise ValueError("Invalid public key length.")
                except (ValueError, TypeError, AttributeError):
                    raise HTTPException(
                        status_code=422,
                        detail="The client identity key is invalid.",
                    )

                prior = connection.execute(
                    """
                    SELECT device_id, public_key
                    FROM device_agent_credentials
                    WHERE client_instance = ?
                    """,
                    (client_instance,),
                ).fetchone()

                if prior and (
                    prior["device_id"] != device_id
                    or prior["public_key"] != public_key_text
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="This client identity is already bound to another device.",
                    )

                connection.execute(
                    """
                    INSERT INTO device_agent_credentials
                        (client_instance, device_id, public_key, last_seen)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(client_instance) DO UPDATE SET
                        device_id = excluded.device_id,
                        public_key = excluded.public_key,
                        revoked = 0,
                        last_seen = CURRENT_TIMESTAMP
                    """,
                    (client_instance, device_id, public_key_text),
                )

        connection.execute(
            """
            UPDATE device_connection_requests
            SET status = ?, reviewed_at = CURRENT_TIMESTAMP, device_id = ?
            WHERE id = ? AND status = 'Pending'
            """,
            (decision.decision, device_id, request_id),
        )

    # Update the live session state for the next UI refresh and heartbeat.
    with _connection_clients_lock:
        for client in _connection_clients.values():
            if client.get("request_id") == request_id:
                client["approval_status"] = decision.decision
                if decision.decision == "Approved":
                    client["state"] = (
                        "Connected" if client.get("connected")
                        else "Approved · disconnected"
                    )
                else:
                    client["state"] = (
                        "Rejected · disconnecting" if client.get("connected")
                        else "Rejected"
                    )

    return {
        "request_id": request_id,
        "decision": decision.decision,
        "device_id": device_id,
        "device_name": device_name,
        "device_status": device_status,
        "message": (
            "Device approved and added to inventory."
            if decision.decision == "Approved"
            else "Device request rejected."
        ),
    }


@app.post("/api/device-connection-requests", status_code=201)
def create_device_connection_request(request: DeviceConnectionRequestInput):
    request_id = "request-" + uuid.uuid4().hex

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO device_connection_requests
                (id, device_name, os, client_ip, username)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                request_id,
                request.device_name,
                request.os,
                request.client_ip,
                request.username,
            ),
        )
        row = connection.execute(
            """
            SELECT id, device_name, os, client_ip, username,
                   status, created_at, reviewed_at, device_id
            FROM device_connection_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()

    return dict(row)


@app.get("/api/device-connection-requests")
def list_device_connection_requests():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, device_name, os, client_ip, username,
                   status, created_at, reviewed_at, device_id
            FROM device_connection_requests
            WHERE status = 'Pending'
            ORDER BY created_at DESC, rowid DESC
            LIMIT 200
        """).fetchall()

    return [dict(row) for row in rows]


def _get_live_device_connections():
    """Return the newest connected, approved CartmanClient session per device."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, device_id
            FROM device_connection_requests
            WHERE status = 'Approved' AND device_id IS NOT NULL
            """
        ).fetchall()

    approved_device_by_request = {
        str(row["id"]): str(row["device_id"])
        for row in rows
        if row["id"] and row["device_id"]
    }

    with _connection_clients_lock:
        clients = [
            dict(client)
            for client in _connection_clients.values()
            if client.get("connected") is True
        ]

    live_by_device = {}
    for client in clients:
        device_id = approved_device_by_request.get(
            str(client.get("request_id") or "")
        )
        if not device_id:
            continue

        previous = live_by_device.get(device_id)
        if (
            previous is None
            or str(client.get("last_seen") or "")
            > str(previous.get("last_seen") or "")
        ):
            live_by_device[device_id] = client

    return live_by_device


def _apply_live_device_state(device, live_connections):
    """Expose connection liveness without persisting transient status to SQLite."""
    client = live_connections.get(str(device.get("id") or ""))
    live = client is not None

    device["status"] = "Online" if live else "Offline"
    device["connection_status"] = "Online" if live else "Offline"
    device["connection_state"] = (
        (client.get("state") or "Connected")
        if live else "Disconnected"
    )
    device["last_seen"] = (
        (client.get("last_seen") or None) if live else None
    )
    device["lastSeen"] = device["last_seen"]

    return device


@app.get("/api/devices")
def list_devices():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT *
            FROM devices
            ORDER BY name COLLATE NOCASE
        """).fetchall()

    live_connections = _get_live_device_connections()
    return [
        _apply_live_device_state(serialize_device(row), live_connections)
        for row in rows
    ]


@app.get("/api/devices/{device_id}")
def get_device(device_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")

    return _apply_live_device_state(
        serialize_device(row), _get_live_device_connections()
    )


@app.post("/api/devices", status_code=201)
def create_device(device: DeviceInput):
    device_id = "device-" + uuid.uuid4().hex

    try:
        with get_connection() as connection:
            connection.execute("""
                INSERT INTO devices (
                    id, name, os, ip, status, tags,
                    public_ip, local_ip, username, model, manufacturer,
                    device_type, cpu, ram, disk, gpu
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device_id,
                device.name,
                device.os,
                device.local_ip or device.ip or device.public_ip,
                device.status,
                json.dumps(device.tags),
                device.public_ip,
                device.local_ip,
                device.username,
                device.model,
                device.manufacturer,
                device.device_type,
                device.cpu,
                device.ram,
                device.disk,
                device.gpu,
            ))

            row = connection.execute(
                "SELECT * FROM devices WHERE id = ?",
                (device_id,),
            ).fetchone()

        return serialize_device(row)

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A device with that name already exists",
        )


@app.put("/api/devices/{device_id}")
def update_device(device_id: str, device: DeviceInput):
    try:
        with get_connection() as connection:
            cursor = connection.execute("""
                UPDATE devices
                SET name = ?, os = ?,
                    model = CASE WHEN ? != '' THEN ? ELSE model END,
                    manufacturer = CASE WHEN ? != '' THEN ? ELSE manufacturer END,
                    device_type = CASE WHEN ? != '' THEN ? ELSE device_type END,
                    cpu = CASE WHEN ? != '' THEN ? ELSE cpu END,
                    ram = CASE WHEN ? != '' THEN ? ELSE ram END,
                    disk = CASE WHEN ? != '' THEN ? ELSE disk END,
                    gpu = CASE WHEN ? != '' THEN ? ELSE gpu END,
                    ip = CASE
                        WHEN ? != '' THEN ?
                        WHEN ? != '' THEN ?
                        ELSE ip
                    END,
                    status = ?, tags = ?,
                    public_ip = CASE WHEN ? != '' THEN ? ELSE public_ip END,
                    local_ip = CASE WHEN ? != '' THEN ? ELSE local_ip END,
                    username = CASE WHEN ? != '' THEN ? ELSE username END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                device.name,
                device.os,
                device.model, device.model,
                device.manufacturer, device.manufacturer,
                device.device_type, device.device_type,
                device.cpu, device.cpu,
                device.ram, device.ram,
                device.disk, device.disk,
                device.gpu, device.gpu,
                device.local_ip, device.local_ip,
                device.ip, device.ip,
                device.status,
                json.dumps(device.tags),
                device.public_ip, device.public_ip,
                device.local_ip, device.local_ip,
                device.username, device.username,
                device_id,
            ))

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Device not found",
                )

            row = connection.execute(
                "SELECT * FROM devices WHERE id = ?",
                (device_id,),
            ).fetchone()

        return serialize_device(row)

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A device with that name already exists",
        )


@app.delete("/api/devices/{device_id}")
def delete_device(device_id: str):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM devices WHERE id = ?",
            (device_id,),
        )

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Device not found")

    return {"deleted": True, "id": device_id}




# CARTMAN_DEVICE_GROUPS_API_V1
# Persistent Device Groups API backed by the existing Cartman SQLite database.

def initialize_device_groups_schema():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS device_groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS device_group_members (
                group_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                member_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (group_id, device_id),
                FOREIGN KEY (group_id) REFERENCES device_groups(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (device_id) REFERENCES devices(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_device_group_members_device
            ON device_group_members(device_id);
        """)


initialize_device_groups_schema()


class DeviceGroupInput(BaseModel):
    id: Optional[str] = Field(default=None, max_length=120)
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    member_ids: list[str] = Field(
        default_factory=list,
        alias="memberIds",
        max_length=2000,
    )

    @validator("name")
    def validate_group_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Group name cannot be empty.")
        return value


def serialize_device_group(connection, row):
    members = connection.execute("""
        SELECT device_id
        FROM device_group_members
        WHERE group_id = ?
        ORDER BY member_order, device_id COLLATE NOCASE
    """, (row["id"],)).fetchall()

    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "memberIds": [item["device_id"] for item in members],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def validate_device_group_members(connection, member_ids):
    ids = list(dict.fromkeys(member_ids))

    if any(not item.strip() for item in ids):
        raise HTTPException(
            status_code=400,
            detail="Device group member IDs cannot be empty.",
        )

    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"SELECT id FROM devices WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()

    existing = {row["id"] for row in rows}
    missing = [item for item in ids if item not in existing]

    if missing:
        raise HTTPException(
            status_code=400,
            detail="Some group members do not exist in the device inventory: "
                   + ", ".join(missing[:5]),
        )

    return ids


def replace_device_group_members(connection, group_id, member_ids):
    connection.execute(
        "DELETE FROM device_group_members WHERE group_id = ?",
        (group_id,),
    )
    connection.executemany("""
        INSERT INTO device_group_members (group_id, device_id, member_order)
        VALUES (?, ?, ?)
    """, [
        (group_id, device_id, index)
        for index, device_id in enumerate(member_ids)
    ])


def read_device_groups(connection):
    rows = connection.execute("""
        SELECT *
        FROM device_groups
        ORDER BY name COLLATE NOCASE
    """).fetchall()
    return [serialize_device_group(connection, row) for row in rows]


@app.get("/api/device-groups")
def list_device_groups():
    with get_connection() as connection:
        return read_device_groups(connection)


@app.get("/api/device-groups/{group_id}")
def get_device_group(group_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM device_groups WHERE id = ?",
            (group_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Device group not found")

        return serialize_device_group(connection, row)


@app.post("/api/device-groups", status_code=201)
def create_device_group(group: DeviceGroupInput):
    group_id = (
        group.id.strip()
        if group.id and group.id.strip()
        else "group-" + uuid.uuid4().hex
    )

    try:
        with get_connection() as connection:
            members = validate_device_group_members(
                connection, group.member_ids
            )
            connection.execute("""
                INSERT INTO device_groups (id, name, description)
                VALUES (?, ?, ?)
            """, (group_id, group.name, group.description.strip()))

            replace_device_group_members(connection, group_id, members)
            row = connection.execute(
                "SELECT * FROM device_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
            result = serialize_device_group(connection, row)

        return result

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A device group with that ID or name already exists.",
        )


@app.post("/api/device-groups/import", status_code=201)
def import_device_groups(groups: list[DeviceGroupInput]):
    if len(groups) > 500:
        raise HTTPException(
            status_code=400,
            detail="A maximum of 500 groups can be imported at once.",
        )

    prepared = []
    seen_ids = set()
    seen_names = set()

    try:
        with get_connection() as connection:
            existing_rows = connection.execute(
                "SELECT id, name FROM device_groups"
            ).fetchall()
            existing_ids = {row["id"] for row in existing_rows}
            existing_names = {
                row["name"].casefold() for row in existing_rows
            }

            # Validate the complete batch before inserting any group.
            for group in groups:
                group_id = (
                    group.id.strip()
                    if group.id and group.id.strip()
                    else "group-" + uuid.uuid4().hex
                )
                name_key = group.name.casefold()

                if group_id in seen_ids or group_id in existing_ids:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Device group ID already exists: {group_id}",
                    )
                if name_key in seen_names or name_key in existing_names:
                    raise HTTPException(
                        status_code=409,
                        detail=f"A device group named '{group.name}' already exists.",
                    )

                members = validate_device_group_members(
                    connection, group.member_ids
                )
                prepared.append((
                    group_id,
                    group.name,
                    group.description.strip(),
                    members,
                ))
                seen_ids.add(group_id)
                seen_names.add(name_key)

            for group_id, name, description, members in prepared:
                connection.execute("""
                    INSERT INTO device_groups (id, name, description)
                    VALUES (?, ?, ?)
                """, (group_id, name, description))
                replace_device_group_members(connection, group_id, members)

            return read_device_groups(connection)

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Group import conflicted with existing group data.",
        )


@app.put("/api/device-groups/{group_id}")
def update_device_group(group_id: str, group: DeviceGroupInput):
    try:
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM device_groups WHERE id = ?",
                (group_id,),
            ).fetchone()

            if existing is None:
                raise HTTPException(
                    status_code=404,
                    detail="Device group not found",
                )

            members = validate_device_group_members(
                connection, group.member_ids
            )
            connection.execute("""
                UPDATE device_groups
                SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (group.name, group.description.strip(), group_id))

            replace_device_group_members(connection, group_id, members)
            row = connection.execute(
                "SELECT * FROM device_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
            result = serialize_device_group(connection, row)

        return result

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A device group with that name already exists.",
        )


@app.delete("/api/device-groups/{group_id}")
def delete_device_group(group_id: str):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM device_groups WHERE id = ?",
            (group_id,),
        )
        deleted = cursor.rowcount > 0

    if not deleted:
        raise HTTPException(status_code=404, detail="Device group not found")

    return {"deleted": True, "id": group_id}




def require_local_task_operator(request: Request):
    peer = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback:
            raise HTTPException(
                status_code=403,
                detail="Task management is restricted to the local Cartman machine.",
            )
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Could not verify the local operator connection.",
        )


@app.post("/api/devices/{device_id}/tasks", status_code=201)
def create_device_task(
    device_id: str,
    task: DeviceTaskInput,
    request: Request,
):
    require_local_task_operator(request)
    payload = dict(task.payload or {})

    with get_connection() as connection:
        device = connection.execute(
            "SELECT id, name, os FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()

        if device is None:
            raise HTTPException(status_code=404, detail="Device not found.")

        if task.action == "package_deployment":
            software_id = payload.get("software_id")
            if not isinstance(software_id, str) or not software_id:
                raise HTTPException(
                    status_code=422,
                    detail="Choose a software catalog package.",
                )

            package = connection.execute(
                """
                SELECT id, name, version, status, install_command, target_os
                FROM software_catalog WHERE id = ?
                """,
                (software_id,),
            ).fetchone()

            if package is None or package["status"] != "Active":
                raise HTTPException(
                    status_code=404,
                    detail="Active software package not found.",
                )

            if not (package["install_command"] or "").strip():
                raise HTTPException(
                    status_code=409,
                    detail="This software package has no install command configured.",
                )

            target_family = normalize_os_family(package["target_os"])
            device_family = normalize_os_family(device["os"])
            if target_family != "Any" and (
                target_family == "Unknown" or device_family != target_family
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"This package targets {package['target_os']}, but this "
                        f"device runs {device['os']}. The package was not queued."
                    ),
                )

        if task.action in {"shutdown", "network_disconnect"}:
            if payload.get("confirmed") is not True:
                raise HTTPException(
                    status_code=422,
                    detail="An explicit confirmation is required for this disruptive task.",
                )

        if task.action == "shutdown":
            delay_seconds = payload.get("delay_seconds", 60)
            if (
                type(delay_seconds) is not int
                or not 1 <= delay_seconds <= 86400
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Shutdown countdown must be a whole number from 1 to 86400 seconds.",
                )
            payload["delay_seconds"] = delay_seconds

        if task.action == "network_disconnect":
            interface_name = payload.get("interface_name")
            if not isinstance(interface_name, str) or not interface_name.strip() or len(interface_name) > 150:
                raise HTTPException(
                    status_code=422,
                    detail="Enter the exact network interface/service name to disconnect.",
                )
            payload["interface_name"] = interface_name.strip()

        if task.action == "vpn_action":
            mode = payload.get("mode")
            profile = payload.get("profile_name")
            if mode not in {"connect", "disconnect"}:
                raise HTTPException(
                    status_code=422,
                    detail="VPN mode must be connect or disconnect.",
                )
            if not isinstance(profile, str) or not profile.strip() or len(profile) > 150:
                raise HTTPException(
                    status_code=422,
                    detail="A configured VPN profile name is required.",
                )
            payload["profile_name"] = profile.strip()

    # Only approved, currently connected enrollment sessions may receive work.
    with get_connection() as connection:
        approved_requests = connection.execute(
            """
            SELECT id FROM device_connection_requests
            WHERE device_id = ? AND status = 'Approved'
            """,
            (device_id,),
        ).fetchall()

    approved_ids = {row["id"] for row in approved_requests}
    with _connection_clients_lock:
        connected = any(
            client.get("request_id") in approved_ids
            and client.get("connected")
            and client.get("task_execution_enabled") is True
            for client in _connection_clients.values()
        )

    if not connected:
        raise HTTPException(
            status_code=409,
            detail=(
                "This device must have an approved, connected CartmanClient "
                "with task execution enabled before queuing a task."
            ),
        )

    task_id = "task-" + uuid.uuid4().hex
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO device_tasks (id, device_id, action, payload)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, device_id, task.action, json.dumps(payload)),
        )

    return {
        "id": task_id,
        "device_id": device_id,
        "action": task.action,
        "payload": payload,
        "status": "Queued",
        "message": "Task queued. A connected, approved CartmanClient with task execution enabled can receive it.",
    }


@app.get("/api/devices/{device_id}/tasks")
def list_device_tasks(device_id: str, request: Request):
    require_local_task_operator(request)

    with get_connection() as connection:
        device = connection.execute(
            "SELECT id FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found.")

        rows = connection.execute(
            """
            SELECT id, device_id, action, payload, status, result,
                   created_at, started_at, finished_at
            FROM device_tasks
            WHERE device_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 100
            """,
            (device_id,),
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"] or "{}")
        except (TypeError, json.JSONDecodeError):
            item["payload"] = {}
        results.append(item)

    return results


@app.post("/api/devices/import")
def import_devices(devices: list[DeviceInput]):
    if len(devices) > 5000:
        raise HTTPException(
            status_code=413,
            detail="Maximum 5000 devices per import",
        )

    imported = 0
    skipped = 0

    with get_connection() as connection:
        for device in devices:
            device_id = "device-" + uuid.uuid4().hex

            try:
                connection.execute("""
                    INSERT INTO devices (
                        id, name, os, ip, status, tags,
                        public_ip, local_ip, username
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    device_id,
                    device.name,
                    device.os,
                    device.local_ip or device.ip or device.public_ip,
                    device.status,
                    json.dumps(device.tags),
                    device.public_ip,
                    device.local_ip,
                    device.username,
                ))
                imported += 1
            except sqlite3.IntegrityError:
                skipped += 1

    return {"imported": imported, "skipped": skipped}




@app.get("/api/overview")
def overview():
    """Aggregate persisted device and monitoring data for the dashboard."""
    with get_connection() as connection:
        device_rows = connection.execute("""
            SELECT id, name, os, ip, status, tags, created_at, updated_at
            FROM devices
            ORDER BY updated_at DESC, name COLLATE NOCASE
        """).fetchall()

        alert_rows = connection.execute("""
            SELECT id, device_id, title, severity, status, details, created_at
            FROM monitoring_alerts
            WHERE LOWER(status) NOT IN ('resolved', 'closed')
            ORDER BY created_at DESC
            LIMIT 5
        """).fetchall()

        event_rows = connection.execute("""
            SELECT id, device_id, event_type, severity, message, occurred_at
            FROM monitoring_events
            ORDER BY occurred_at DESC
            LIMIT 10
        """).fetchall()

        check_rows = connection.execute("""
            SELECT a.id, a.device_id, a.target, a.status,
                   a.response_ms, a.checked_at
            FROM availability_checks AS a
            INNER JOIN (
                SELECT device_id, MAX(checked_at) AS latest
                FROM availability_checks
                GROUP BY device_id
            ) AS latest
              ON latest.device_id = a.device_id
             AND latest.latest = a.checked_at
            ORDER BY a.checked_at DESC
            LIMIT 1000
        """).fetchall()

        metric_count = connection.execute(
            "SELECT COUNT(*) FROM monitoring_metrics"
        ).fetchone()[0]

        service_check_count = connection.execute(
            "SELECT COUNT(*) FROM service_checks"
        ).fetchone()[0]

        event_count = connection.execute(
            "SELECT COUNT(*) FROM monitoring_events"
        ).fetchone()[0]

        alert_count = connection.execute("""
            SELECT COUNT(*) FROM monitoring_alerts
            WHERE LOWER(status) NOT IN ('resolved', 'closed')
        """).fetchone()[0]

    # Dashboard status comes from live CartmanClient connections,
    # not stale status values stored in SQLite.
    live_connections = _get_live_device_connections()
    devices = [
        _apply_live_device_state(serialize_device(row), live_connections)
        for row in device_rows
    ]

    status_counts = {}
    for device in devices:
        status = str(device.get("status") or "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    # Availability results are real checks, separate from stored device status.
    latest_checks = [dict(row) for row in check_rows]
    check_status_counts = {}
    for check in latest_checks:
        key = str(check.get("status") or "Unknown")
        check_status_counts[key] = check_status_counts.get(key, 0) + 1

    activities = []
    for event in event_rows:
        activities.append({
            "id": f'event-{event["id"]}',
            "kind": "event",
            "title": event["message"] or event["event_type"] or "Monitoring event",
            "detail": (
                f'{event["event_type"] or "Event"}'
                + (f' · {event["severity"]}' if event["severity"] else "")
                + (f' · {event["device_id"]}' if event["device_id"] else "")
            ),
            "timestamp": event["occurred_at"],
        })

    for alert in alert_rows:
        activities.append({
            "id": f'alert-{alert["id"]}',
            "kind": "alert",
            "title": alert["title"] or "Monitoring alert",
            "detail": (
                f'{alert["severity"] or "Unspecified severity"}'
                + (f' · {alert["device_id"]}' if alert["device_id"] else "")
                + f' · {alert["status"]}'
            ),
            "timestamp": alert["created_at"],
        })

    activities.sort(
        key=lambda item: item["timestamp"] or "",
        reverse=True,
    )

    return {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "devices": {
            "total": len(devices),
            "status_counts": status_counts,
            "items": devices[:5],
        },
        "monitoring": {
            "metric_samples": metric_count,
            "service_checks": service_check_count,
            "availability_checks": sum(check_status_counts.values()),
            "latest_check_status_counts": check_status_counts,
            "open_alerts": alert_count,
            "events_total": event_count,
            "alerts": [dict(row) for row in alert_rows],
        },
        "activity": activities[:6],
        "tickets": {"configured": False, "reason": "Ticketing API is not implemented."},
        "tasks": {"configured": False, "reason": "Task API is not implemented."},
    }


# Monitoring read APIs. Empty tables mean no telemetry/checks have been collected yet.
@app.get("/api/monitoring/summary")
def monitoring_summary():
    with get_connection() as connection:
        devices = connection.execute(
            "SELECT status, COUNT(*) AS total FROM devices GROUP BY status"
        ).fetchall()
        metric_count = connection.execute(
            "SELECT COUNT(*) FROM monitoring_metrics"
        ).fetchone()[0]
        open_alerts = connection.execute(
            "SELECT COUNT(*) FROM monitoring_alerts WHERE status = 'Open'"
        ).fetchone()[0]
        checks = connection.execute(
            "SELECT COUNT(*) FROM availability_checks"
        ).fetchone()[0]
        services = connection.execute(
            "SELECT COUNT(*) FROM service_checks"
        ).fetchone()[0]
    return {
        "device_status_counts": {row["status"]: row["total"] for row in devices},
        "metric_samples": metric_count,
        "open_alerts": open_alerts,
        "availability_checks": checks,
        "service_checks": services,
        "telemetry_configured": metric_count > 0,
    }


@app.get("/api/monitoring/metrics")
def monitoring_metrics(device_id: Optional[str] = None, limit: int = 200):
    limit = max(1, min(limit, 1000))
    sql = """SELECT id, device_id, metric_name, value, unit, source, collected_at
             FROM monitoring_metrics"""
    params = []
    if device_id:
        sql += " WHERE device_id = ?"
        params.append(device_id)
    sql += " ORDER BY collected_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


@app.get("/api/monitoring/alerts")
def monitoring_alerts(status: Optional[str] = None, limit: int = 200):
    limit = max(1, min(limit, 1000))
    sql = """SELECT id, device_id, title, severity, status, details,
                    created_at, acknowledged_at, resolved_at
             FROM monitoring_alerts"""
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


@app.get("/api/monitoring/events")
def monitoring_events(device_id: Optional[str] = None, limit: int = 200):
    limit = max(1, min(limit, 1000))
    sql = """SELECT id, device_id, event_type, severity, message,
                    details_json, occurred_at
             FROM monitoring_events"""
    params = []
    if device_id:
        sql += " WHERE device_id = ?"
        params.append(device_id)
    sql += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


@app.get("/api/monitoring/availability")
def monitoring_availability(device_id: Optional[str] = None, limit: int = 200):
    limit = max(1, min(limit, 1000))
    sql = """SELECT id, device_id, target, status, response_ms, checked_at
             FROM availability_checks"""
    params = []
    if device_id:
        sql += " WHERE device_id = ?"
        params.append(device_id)
    sql += " ORDER BY checked_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


@app.get("/api/monitoring/services")
def monitoring_services(device_id: Optional[str] = None, limit: int = 200):
    limit = max(1, min(limit, 1000))
    sql = """SELECT id, device_id, service_name, status, response_ms, checked_at
             FROM service_checks"""
    params = []
    if device_id:
        sql += " WHERE device_id = ?"
        params.append(device_id)
    sql += " ORDER BY checked_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


