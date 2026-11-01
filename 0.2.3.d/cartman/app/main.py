from pathlib import Path
import json
import math
import secrets
import base64
import hashlib
import mimetypes
import os
import re
import sqlite3
import uuid
import ipaddress
import socket
import socketserver
import threading
import time
import datetime as _datetime
import urllib.request
import urllib.parse

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from typing import Optional


app = FastAPI(title="Cartman")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
FRONTEND = STATIC_DIR / "index.html"
DATABASE = BASE_DIR / "cartman.db"
PACKAGE_REPOSITORY = BASE_DIR / "package_repository"
MAX_SOFTWARE_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_PACKAGE_CHUNK_BYTES = 96 * 1024
SUPPORTED_PACKAGE_TYPES = {
    "EXE": (".exe", "Windows"),
    "MSI": (".msi", "Windows"),
    "PKG": (".pkg", "macOS"),
    "DEB": (".deb", "Linux"),
    "RPM": (".rpm", "Linux"),
}


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


with get_connection() as connection:
    package_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(software_catalog)"
        ).fetchall()
    }
    package_migrations = {
        "install_args": "TEXT NOT NULL DEFAULT ''",
        "package_storage_key": "TEXT NOT NULL DEFAULT ''",
        "package_filename": "TEXT NOT NULL DEFAULT ''",
        "package_size": "INTEGER NOT NULL DEFAULT 0",
        "package_sha256": "TEXT NOT NULL DEFAULT ''",
        "package_uploaded_at": "TEXT NOT NULL DEFAULT ''",
        "package_uploaded_by": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in package_migrations.items():
        if column not in package_columns:
            connection.execute(
                f"ALTER TABLE software_catalog ADD COLUMN {column} {definition}"
            )


class DeviceInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    display_name: Optional[str] = Field(default=None, max_length=180)
    assigned_user_id: Optional[str] = Field(default=None, max_length=120)
    department_id: Optional[str] = Field(default=None, max_length=120)
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
        "name", "display_name", "assigned_user_id", "department_id",
        "os", "ip", "public_ip", "local_ip", "username",
        "model", "manufacturer", "device_type", "cpu", "ram", "disk", "gpu"
    )
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

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
    install_args: str = Field(default="", max_length=2000)
    uninstall_command: str = Field(default="", max_length=2000)
    source_url: str = Field(default="", max_length=1000)
    status: str = "Active"
    notes: str = Field(default="", max_length=5000)

    @validator(
        "name", "publisher", "version", "target_os", "category",
        "package_type", "install_command", "install_args", "uninstall_command",
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
    item = dict(row)
    item.pop("package_storage_key", None)
    return item


def serialize_device(row):
    device = dict(row)
    device["tags"] = json.loads(device.get("tags") or "[]")
    device.setdefault("model", "")
    device.setdefault("manufacturer", "")
    device.setdefault("device_type", "Workstation")
    device["type"] = device.get("device_type") or "Workstation"
    device.setdefault("cpu", "")
    device.setdefault("ram", "")
    device.setdefault("disk", "")
    device.setdefault("gpu", "")
    device["display_name"] = device.get("display_name") or ""
    device["assigned_user_id"] = device.get("assigned_user_id") or ""
    device["department_id"] = device.get("department_id") or ""
    device["department_name"] = device.get("department_name") or ""
    assigned_id = device["assigned_user_id"]
    assigned_name = device.get("assigned_user_name") or ""
    assigned_username = device.get("assigned_user_username") or ""
    if assigned_id:
        device["assignedUser"] = {
            "id": assigned_id,
            "name": assigned_name or assigned_username or "Assigned user",
            "username": assigned_username,
            "email": device.get("assigned_user_email") or "",
        }
    else:
        device["assignedUser"] = None
    return device




@app.get("/", response_class=HTMLResponse)
def home():
    return FRONTEND.read_text(encoding="utf-8")



# CARTMAN_KNOWLEDGE_ARTICLE_PAGE_ROUTE_V1
@app.get("/pages/knowledge/article/{article_key}/", response_class=HTMLResponse)
def standalone_knowledge_article_page(article_key: str):
    if not re.fullmatch(r"KB-\d{4,}", article_key, flags=re.IGNORECASE):
        raise HTTPException(status_code=404, detail="Article page not found.")

    page_file = STATIC_DIR / "pages" / "knowledge" / "article.html"
    if not page_file.is_file():
        raise HTTPException(status_code=404, detail="Article page not found.")

    return page_file.read_text(encoding="utf-8")


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




# ============================================================
# CARTMAN INVENTORY + DEPARTMENTS API
# ============================================================

def initialize_inventory_database():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS departments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS inventory_assets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                brand TEXT NOT NULL DEFAULT '',
                purchase_date TEXT NOT NULL DEFAULT '',
                serial_no TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                assigned_to TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                special_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_inventory_name
                ON inventory_assets(name COLLATE NOCASE);

            CREATE INDEX IF NOT EXISTS idx_inventory_department
                ON inventory_assets(department COLLATE NOCASE);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_serial_unique
                ON inventory_assets(serial_no COLLATE NOCASE)
                WHERE serial_no <> '';
        """)

        # Existing Inventory department names become managed departments.
        existing_departments = connection.execute("""
            SELECT DISTINCT TRIM(department) AS name
            FROM inventory_assets
            WHERE TRIM(department) <> ''
        """).fetchall()

        for row in existing_departments:
            connection.execute(
                """
                INSERT OR IGNORE INTO departments (id, name)
                VALUES (?, ?)
                """,
                (str(uuid.uuid4()), row["name"]),
            )


initialize_inventory_database()


def initialize_inventory_relationships():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                email TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active'
                    CHECK (status IN ('Active', 'Inactive')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(inventory_assets)")
        }
        if "source_device_id" not in columns:
            connection.execute(
                "ALTER TABLE inventory_assets ADD COLUMN source_device_id TEXT"
            )

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_source_device
            ON inventory_assets(source_device_id)
            WHERE source_device_id IS NOT NULL
        """)

        # Preserve and register existing Assigned To values as people.
        assigned_people = connection.execute("""
            SELECT DISTINCT TRIM(assigned_to) AS name
            FROM inventory_assets
            WHERE TRIM(assigned_to) <> ''
        """).fetchall()

        for person in assigned_people:
            connection.execute("""
                INSERT OR IGNORE INTO people (id, name)
                VALUES (?, ?)
            """, (str(uuid.uuid4()), person["name"]))

        # Keep the existing Inventory row if its name already matches a device.
        # Otherwise create one linked inventory asset for each existing device.
        devices = connection.execute("SELECT * FROM devices").fetchall()
        for device in devices:
            linked = connection.execute("""
                SELECT id FROM inventory_assets WHERE source_device_id = ?
            """, (device["id"],)).fetchone()

            if linked is None:
                matching = connection.execute("""
                    SELECT id FROM inventory_assets
                    WHERE source_device_id IS NULL
                      AND name = ? COLLATE NOCASE
                    ORDER BY created_at
                    LIMIT 1
                """, (device["name"],)).fetchone()

                if matching:
                    connection.execute("""
                        UPDATE inventory_assets
                        SET source_device_id = ?,
                            type = ?,
                            brand = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        device["id"],
                        device["device_type"] or "Workstation",
                        device["manufacturer"] or "",
                        matching["id"],
                    ))
                else:
                    connection.execute("""
                        INSERT OR IGNORE INTO inventory_assets (
                            id, source_device_id, name, type, brand,
                            purchase_date, serial_no, department, assigned_to,
                            tags_json, special_notes
                        )
                        VALUES (?, ?, ?, ?, ?, '', '', '', '', ?, '')
                    """, (
                        "device-" + device["id"],
                        device["id"],
                        device["name"],
                        device["device_type"] or "Workstation",
                        device["manufacturer"] or "",
                        device["tags"] or "[]",
                    ))

        # Keep fields owned by Devices synchronized without overwriting
        # inventory-specific values such as purchase date, serial, owner or notes.
        connection.executescript("""
            CREATE TRIGGER IF NOT EXISTS trg_devices_inventory_insert
            AFTER INSERT ON devices
            BEGIN
                UPDATE inventory_assets
                SET name = NEW.name,
                    type = COALESCE(NULLIF(NEW.device_type, ''), 'Workstation'),
                    brand = COALESCE(NEW.manufacturer, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE source_device_id = NEW.id;

                UPDATE inventory_assets
                SET source_device_id = NEW.id,
                    type = COALESCE(NULLIF(NEW.device_type, ''), 'Workstation'),
                    brand = COALESCE(NEW.manufacturer, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM inventory_assets
                    WHERE source_device_id IS NULL
                      AND name = NEW.name COLLATE NOCASE
                    ORDER BY created_at
                    LIMIT 1
                )
                AND NOT EXISTS (
                    SELECT 1 FROM inventory_assets WHERE source_device_id = NEW.id
                );

                INSERT OR IGNORE INTO inventory_assets (
                    id, source_device_id, name, type, brand,
                    purchase_date, serial_no, department, assigned_to,
                    tags_json, special_notes
                )
                SELECT
                    'device-' || NEW.id,
                    NEW.id,
                    NEW.name,
                    COALESCE(NULLIF(NEW.device_type, ''), 'Workstation'),
                    COALESCE(NEW.manufacturer, ''),
                    '', '', '', '', COALESCE(NEW.tags, '[]'), ''
                WHERE NOT EXISTS (
                    SELECT 1 FROM inventory_assets WHERE source_device_id = NEW.id
                );
            END;

            CREATE TRIGGER IF NOT EXISTS trg_devices_inventory_update
            AFTER UPDATE ON devices
            BEGIN
                UPDATE inventory_assets
                SET name = NEW.name,
                    type = COALESCE(NULLIF(NEW.device_type, ''), 'Workstation'),
                    brand = COALESCE(NEW.manufacturer, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE source_device_id = NEW.id;

                UPDATE inventory_assets
                SET source_device_id = NEW.id,
                    type = COALESCE(NULLIF(NEW.device_type, ''), 'Workstation'),
                    brand = COALESCE(NEW.manufacturer, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM inventory_assets
                    WHERE source_device_id IS NULL
                      AND name = NEW.name COLLATE NOCASE
                    ORDER BY created_at
                    LIMIT 1
                )
                AND NOT EXISTS (
                    SELECT 1 FROM inventory_assets WHERE source_device_id = NEW.id
                );

                INSERT OR IGNORE INTO inventory_assets (
                    id, source_device_id, name, type, brand,
                    purchase_date, serial_no, department, assigned_to,
                    tags_json, special_notes
                )
                SELECT
                    'device-' || NEW.id,
                    NEW.id,
                    NEW.name,
                    COALESCE(NULLIF(NEW.device_type, ''), 'Workstation'),
                    COALESCE(NEW.manufacturer, ''),
                    '', '', '', '', COALESCE(NEW.tags, '[]'), ''
                WHERE NOT EXISTS (
                    SELECT 1 FROM inventory_assets WHERE source_device_id = NEW.id
                );
            END;

            CREATE TRIGGER IF NOT EXISTS trg_devices_inventory_delete
            AFTER DELETE ON devices
            BEGIN
                UPDATE inventory_assets
                SET source_device_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source_device_id = OLD.id;
            END;
        """)


def initialize_device_purchase_date_triggers():
    import sqlite3

    conn = sqlite3.connect(str(DATABASE))
    try:
        conn.executescript("""
        -- CARTMAN_DEVICE_FIRST_SEEN_TIMESTAMP_V1

        DROP TRIGGER IF EXISTS trg_inventory_purchase_datetime_insert;
        CREATE TRIGGER trg_inventory_purchase_datetime_insert
        AFTER INSERT ON inventory_assets
        WHEN NEW.source_device_id IS NOT NULL
         AND (
             NEW.purchase_date IS NULL
             OR TRIM(NEW.purchase_date) = ''
         )
        BEGIN
            UPDATE inventory_assets
            SET purchase_date = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id
              AND (
                  purchase_date IS NULL
                  OR TRIM(purchase_date) = ''
              );
        END;

        DROP TRIGGER IF EXISTS trg_inventory_purchase_datetime_link;
        CREATE TRIGGER trg_inventory_purchase_datetime_link
        AFTER UPDATE OF source_device_id ON inventory_assets
        WHEN NEW.source_device_id IS NOT NULL
         AND (
             OLD.source_device_id IS NULL
             OR OLD.source_device_id <> NEW.source_device_id
         )
         AND (
             NEW.purchase_date IS NULL
             OR TRIM(NEW.purchase_date) = ''
         )
        BEGIN
            UPDATE inventory_assets
            SET purchase_date = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id
              AND (
                  purchase_date IS NULL
                  OR TRIM(purchase_date) = ''
              );
        END;
        """)
        conn.commit()
    finally:
        conn.close()


initialize_inventory_relationships()
initialize_device_purchase_date_triggers()

# Persistent lifecycle metadata kept separate from Inventory asset fields.
def initialize_device_lifecycle_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS device_lifecycle (
                asset_id TEXT PRIMARY KEY,
                stage TEXT NOT NULL DEFAULT 'Unspecified',
                warranty_end_date TEXT NOT NULL DEFAULT '',
                refresh_due_date TEXT NOT NULL DEFAULT '',
                retirement_date TEXT NOT NULL DEFAULT '',
                lifecycle_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


initialize_device_lifecycle_database()



def _inventory_row_to_dict(row):
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        tags = []

    if not isinstance(tags, list):
        tags = []

    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "brand": row["brand"],
        "purchaseDate": row["purchase_date"],
        "serialNo": row["serial_no"],
        "department": row["department"],
        "assignedTo": row["assigned_to"],
        "tags": tags,
        "specialNotes": row["special_notes"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "sourceDeviceId": row["source_device_id"],
    }


def _inventory_clean_asset(payload, forced_id=None):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Asset must be a JSON object.")

    name = str(payload.get("name") or "").strip()
    asset_type = str(payload.get("type") or "").strip()

    if not name:
        raise HTTPException(status_code=422, detail="Asset name is required.")
    if not asset_type:
        raise HTTPException(status_code=422, detail="Asset type is required.")
    if len(name) > 160 or len(asset_type) > 120:
        raise HTTPException(status_code=422, detail="Asset name or type is too long.")

    raw_tags = payload.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [part.strip() for part in raw_tags.split(",") if part.strip()]
    elif isinstance(raw_tags, list):
        tags = list(dict.fromkeys(
            str(part).strip() for part in raw_tags if str(part).strip()
        ))
    else:
        raise HTTPException(status_code=422, detail="Tags must be a list or string.")

    asset = {
        "id": str(forced_id or payload.get("id") or uuid.uuid4()).strip(),
        "name": name,
        "type": asset_type,
        "brand": str(payload.get("brand") or "").strip(),
        "purchaseDate": str(payload.get("purchaseDate") or "").strip(),
        "serialNo": str(payload.get("serialNo") or "").strip(),
        "department": str(payload.get("department") or "").strip(),
        "assignedTo": str(payload.get("assignedTo") or "").strip(),
        "tags": tags,
        "specialNotes": str(payload.get("specialNotes") or "").strip(),
    }

    if not asset["id"] or len(asset["id"]) > 160:
        raise HTTPException(status_code=422, detail="Invalid asset ID.")
    if len(asset["brand"]) > 120 or len(asset["serialNo"]) > 180:
        raise HTTPException(status_code=422, detail="Brand or serial number is too long.")
    if len(asset["department"]) > 120 or len(asset["assignedTo"]) > 160:
        raise HTTPException(status_code=422, detail="Department or assignee is too long.")
    if len(asset["specialNotes"]) > 4000 or len(tags) > 100:
        raise HTTPException(status_code=422, detail="Notes or tag count exceeds the limit.")

    return asset


def _inventory_upsert(connection, asset):
    department = asset["department"]
    if department:
        connection.execute(
            "INSERT OR IGNORE INTO departments (id, name) VALUES (?, ?)",
            (str(uuid.uuid4()), department),
        )

    connection.execute("""
        INSERT INTO inventory_assets (
            id, name, type, brand, purchase_date, serial_no,
            department, assigned_to, tags_json, special_notes, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            type = excluded.type,
            brand = excluded.brand,
            purchase_date = excluded.purchase_date,
            serial_no = excluded.serial_no,
            department = excluded.department,
            assigned_to = excluded.assigned_to,
            tags_json = excluded.tags_json,
            special_notes = excluded.special_notes,
            updated_at = CURRENT_TIMESTAMP
    """, (
        asset["id"], asset["name"], asset["type"], asset["brand"],
        asset["purchaseDate"], asset["serialNo"], asset["department"],
        asset["assignedTo"], json.dumps(asset["tags"], ensure_ascii=False),
        asset["specialNotes"],
    ))




# CARTMAN_OS_IMAGE_CATALOG_API_V1
OS_IMAGE_REPOSITORY = BASE_DIR / "os_image_repository"
MAX_OS_IMAGE_BYTES = 32 * 1024 * 1024 * 1024

OS_IMAGE_ALLOWED_EXTENSIONS_BY_OS = {
    "Windows": {".iso", ".wim", ".esd", ".swm"},
    "Linux": {".iso", ".img", ".raw"},
    "macOS": {".dmg", ".pkg", ".ipsw", ".zip"},
}

with get_connection() as connection:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS os_images (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            operating_system TEXT NOT NULL
                CHECK (operating_system IN ('Windows', 'macOS', 'Linux')),
            version TEXT NOT NULL,
            size_gb REAL,
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock IN (0, 1)),
            details TEXT NOT NULL DEFAULT '',
            added_by TEXT NOT NULL DEFAULT 'Unidentified operator',
            file_storage_key TEXT NOT NULL DEFAULT '',
            file_filename TEXT NOT NULL DEFAULT '',
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            file_sha256 TEXT NOT NULL DEFAULT '',
            file_uploaded_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _os_image_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(os_images)").fetchall()
    }
    for column, definition in {
        "file_storage_key": "TEXT NOT NULL DEFAULT ''",
        "file_filename": "TEXT NOT NULL DEFAULT ''",
        "file_size_bytes": "INTEGER NOT NULL DEFAULT 0",
        "file_sha256": "TEXT NOT NULL DEFAULT ''",
        "file_uploaded_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in _os_image_columns:
            connection.execute(
                f"ALTER TABLE os_images ADD COLUMN {column} {definition}"
            )
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_os_images_name
        ON os_images(name COLLATE NOCASE)
    """)


def _os_image_fields(payload, existing=None):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Image data must be an object.")

    data = dict(existing or {})
    for key in ("name", "operating_system", "version", "size_gb", "stock", "details"):
        if key in payload:
            data[key] = payload[key]

    name = str(data.get("name") or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail="Image name is required (max 120 characters).")

    operating_system = str(data.get("operating_system") or "").strip()
    if operating_system not in OS_IMAGE_ALLOWED_EXTENSIONS_BY_OS:
        raise HTTPException(
            status_code=422,
            detail="Operating system must be Windows, macOS, or Linux.",
        )

    version = str(data.get("version") or "").strip()
    if not version or len(version) > 120:
        raise HTTPException(status_code=422, detail="Image version is required (max 120 characters).")

    raw_size = data.get("size_gb")
    if raw_size is None or raw_size == "":
        size_gb = None
    else:
        try:
            size_gb = float(raw_size)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Size must be a number in GB.")
        if not math.isfinite(size_gb) or not 0 <= size_gb <= 1000000:
            raise HTTPException(status_code=422, detail="Size must be between 0 and 1,000,000 GB.")

    raw_stock = data.get("stock", False)
    if isinstance(raw_stock, bool):
        stock = raw_stock
    elif isinstance(raw_stock, (int, float)) and raw_stock in (0, 1):
        stock = bool(raw_stock)
    elif isinstance(raw_stock, str) and raw_stock.strip().lower() in {
        "yes", "no", "true", "false", "1", "0"
    }:
        stock = raw_stock.strip().lower() in {"yes", "true", "1"}
    else:
        raise HTTPException(status_code=422, detail="Stock must be Yes or No.")

    details = str(data.get("details") or "").strip()
    if len(details) > 5000:
        raise HTTPException(status_code=422, detail="Details must be 5,000 characters or fewer.")

    return {
        "name": name,
        "operating_system": operating_system,
        "version": version,
        "size_gb": size_gb,
        "stock": stock,
        "details": details,
    }


def _os_image_path(storage_key):
    if not isinstance(storage_key, str) or not re.fullmatch(r"[a-f0-9]{32}\.blob", storage_key):
        return None
    return OS_IMAGE_REPOSITORY / storage_key


def _safe_os_image_filename(filename, operating_system):
    value = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not value or len(value) > 255 or "\x00" in value:
        raise HTTPException(status_code=422, detail="Invalid image filename.")

    allowed = OS_IMAGE_ALLOWED_EXTENSIONS_BY_OS.get(operating_system)
    if not allowed:
        raise HTTPException(status_code=422, detail="Invalid image operating system.")

    extension = Path(value).suffix.lower()
    if extension not in allowed:
        raise HTTPException(
            status_code=415,
            detail=(
                f"{extension or '(no extension)'} is not supported for {operating_system}. "
                f"Allowed extensions: {', '.join(sorted(allowed))}."
            ),
        )
    return value


def _serialize_os_image(row):
    result = dict(row)
    result.pop("file_storage_key", None)
    result["stock"] = bool(result.get("stock"))
    result["has_file"] = bool(
        result.get("file_filename")
        and int(result.get("file_size_bytes") or 0) > 0
        and result.get("file_sha256")
    )
    return result


@app.get("/api/os-images")
def list_os_images():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT * FROM os_images
            ORDER BY name COLLATE NOCASE
        """).fetchall()
    return [_serialize_os_image(row) for row in rows]


@app.post("/api/os-images", status_code=201)
def create_os_image(
    payload: dict,
    x_operator: str = Header(default="Unidentified operator", alias="X-Operator"),
):
    fields = _os_image_fields(payload)
    image_id = "os-image-" + uuid.uuid4().hex
    actor = normalize_operator(x_operator)

    try:
        with get_connection() as connection:
            connection.execute("""
                INSERT INTO os_images
                    (id, name, operating_system, version, size_gb, stock, details, added_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                image_id, fields["name"], fields["operating_system"], fields["version"],
                fields["size_gb"], int(fields["stock"]), fields["details"], actor,
            ))
            row = connection.execute(
                "SELECT * FROM os_images WHERE id = ?", (image_id,)
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An image with this name already exists.") from exc

    return _serialize_os_image(row)


@app.put("/api/os-images/{image_id}")
def update_os_image(image_id: str, payload: dict):
    try:
        with get_connection() as connection:
            current = connection.execute(
                "SELECT * FROM os_images WHERE id = ?", (image_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Image not found.")

            fields = _os_image_fields(payload, dict(current))
            old_filename = str(current["file_filename"] or "")
            if old_filename:
                old_ext = Path(old_filename).suffix.lower()
                if old_ext not in OS_IMAGE_ALLOWED_EXTENSIONS_BY_OS[fields["operating_system"]]:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"The current file ({old_ext}) is not valid for "
                            f"{fields['operating_system']}. Upload a compatible replacement."
                        ),
                    )

            connection.execute("""
                UPDATE os_images
                SET name = ?, operating_system = ?, version = ?, size_gb = ?,
                    stock = ?, details = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                fields["name"], fields["operating_system"], fields["version"],
                fields["size_gb"], int(fields["stock"]), fields["details"], image_id,
            ))
            row = connection.execute(
                "SELECT * FROM os_images WHERE id = ?", (image_id,)
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An image with this name already exists.") from exc

    return _serialize_os_image(row)


@app.post("/api/os-images/{image_id}/file")
async def upload_os_image_file(
    image_id: str,
    request: Request,
    filename: str,
    operating_system: Optional[str] = None,
):
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id, operating_system FROM os_images WHERE id = ?", (image_id,)
        ).fetchone()

    if existing is None:
        raise HTTPException(status_code=404, detail="Image record not found.")

    target_os = str(operating_system or existing["operating_system"]).strip()
    safe_name = _safe_os_image_filename(filename, target_os)

    content_length = request.headers.get("content-length", "")
    try:
        if content_length and int(content_length) > MAX_OS_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image exceeds the 32 GB upload limit.")
    except ValueError:
        pass

    OS_IMAGE_REPOSITORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    storage_key = uuid.uuid4().hex + ".blob"
    temporary_path = OS_IMAGE_REPOSITORY / (storage_key + ".tmp")
    final_path = OS_IMAGE_REPOSITORY / storage_key
    hasher = hashlib.sha256()
    total = 0
    old_key = ""

    try:
        with temporary_path.open("wb") as output:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_OS_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Image exceeds the 32 GB upload limit.")
                output.write(chunk)
                hasher.update(chunk)

        if total <= 0:
            raise HTTPException(status_code=400, detail="The uploaded image is empty.")

        digest = hasher.hexdigest()
        temporary_path.replace(final_path)

        with get_connection() as connection:
            current = connection.execute(
                "SELECT file_storage_key FROM os_images WHERE id = ?", (image_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Image record not found.")

            old_key = current["file_storage_key"] or ""
            connection.execute("""
                UPDATE os_images
                SET operating_system = ?, file_storage_key = ?, file_filename = ?,
                    file_size_bytes = ?, file_sha256 = ?,
                    file_uploaded_at = CURRENT_TIMESTAMP, size_gb = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                target_os, storage_key, safe_name, total, digest,
                total / (1024 ** 3), image_id,
            ))
            row = connection.execute(
                "SELECT * FROM os_images WHERE id = ?", (image_id,)
            ).fetchone()

    except HTTPException:
        temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"Image upload failed ({type(exc).__name__}).",
        ) from exc

    if old_key and old_key != storage_key:
        old_path = _os_image_path(old_key)
        if old_path and old_path.is_file():
            old_path.unlink(missing_ok=True)

    return _serialize_os_image(row)


@app.get("/api/os-images/{image_id}/file")
def download_os_image_file(image_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT file_storage_key, file_filename, file_size_bytes "
            "FROM os_images WHERE id = ?", (image_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Image not found.")

    path = _os_image_path(row["file_storage_key"])
    if (
        not path or not path.is_file()
        or int(row["file_size_bytes"] or 0) <= 0
        or path.stat().st_size != int(row["file_size_bytes"])
    ):
        raise HTTPException(status_code=404, detail="Image file is not available.")

    return FileResponse(
        path=str(path),
        filename=row["file_filename"] or "os-image",
        media_type="application/octet-stream",
    )


@app.delete("/api/os-images/{image_id}")
def delete_os_image(image_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT file_storage_key FROM os_images WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        storage_key = row["file_storage_key"] or ""
        connection.execute("DELETE FROM os_images WHERE id = ?", (image_id,))

    path = _os_image_path(storage_key)
    if path and path.is_file():
        path.unlink(missing_ok=True)

    return {"deleted": True, "id": image_id}


@app.post("/api/os-images/{image_id}/deploy-pxe")
def deploy_os_image_pxe(image_id: str, request: Request):
    require_local_task_operator(request)

    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM os_images WHERE id = ?", (image_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Image not found.")

    image = _serialize_os_image(row)
    if image["operating_system"] == "macOS":
        raise HTTPException(
            status_code=409,
            detail="Mac images cannot be installed via PXE. No PXE request was sent.",
        )

    path = _os_image_path(row["file_storage_key"])
    if (
        not path or not path.is_file()
        or int(row["file_size_bytes"] or 0) <= 0
        or path.stat().st_size != int(row["file_size_bytes"])
    ):
        raise HTTPException(
            status_code=409,
            detail="Upload a valid image file before requesting PXE deployment.",
        )

    pxe_url = os.environ.get("CARTMAN_PXE_API_URL", "").strip()
    if not pxe_url:
        raise HTTPException(
            status_code=503,
            detail="PXE API is not configured. No deployment was started.",
        )

    from urllib.parse import urlparse
    from urllib.error import HTTPError, URLError

    parsed = urlparse(pxe_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=503, detail="CARTMAN_PXE_API_URL must be an HTTP(S) URL.")

    file_path = f"/api/os-images/{image_id}/file"
    base_url = os.environ.get("CARTMAN_BASE_URL", "").strip().rstrip("/")
    payload = {
        "action": "deploy_image_pxe",
        "image": image,
        "file": {
            "filename": image["file_filename"],
            "size_bytes": image["file_size_bytes"],
            "sha256": image["file_sha256"],
            "download_path": file_path,
            "download_url": f"{base_url}{file_path}" if base_url else None,
        },
    }
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("CARTMAN_PXE_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token

    outgoing = urllib.request.Request(
        pxe_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(outgoing, timeout=15) as response:
            raw = response.read(65536).decode("utf-8", errors="replace")
            try:
                result = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                result = {"text": raw}
            return {
                "status": "forwarded",
                "message": "PXE API accepted the request; verify boot/deployment status on the PXE service.",
                "pxe_response": result,
            }
    except HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"PXE API HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach PXE API: {exc}") from exc


@app.get("/api/departments")
def list_departments():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT d.id, d.name, d.created_at, d.updated_at,
                   COUNT(g.id) AS group_count
            FROM departments d
            LEFT JOIN iam_groups g ON g.department_id=d.id
            GROUP BY d.id
            ORDER BY d.name COLLATE NOCASE
        """).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/departments", status_code=201)
def create_department(payload: dict, request: Request):
    _iam_directory_admin(request)
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(
            status_code=422,
            detail="Department name is required and must be 120 characters or fewer.",
        )

    department_id = str(uuid.uuid4())
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO departments (id, name) VALUES (?, ?)",
                (department_id, name),
            )
            row = connection.execute(
                "SELECT id, name, created_at, updated_at FROM departments WHERE id = ?",
                (department_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="A department with this name already exists."
        ) from exc

    return dict(row)


@app.put("/api/departments/{department_id}")
def rename_department(department_id: str, payload: dict, request: Request):
    _iam_directory_admin(request)
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(
            status_code=422,
            detail="Department name is required and must be 120 characters or fewer.",
        )

    try:
        with get_connection() as connection:
            current = connection.execute(
                "SELECT name FROM departments WHERE id = ?", (department_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Department not found.")

            old_name = current["name"]
            connection.execute("""
                UPDATE departments
                SET name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, department_id))

            # Keep existing assets assigned when a department is renamed.
            connection.execute("""
                UPDATE inventory_assets
                SET department = ?, updated_at = CURRENT_TIMESTAMP
                WHERE department = ? COLLATE NOCASE
            """, (name, old_name))

            row = connection.execute("""
                SELECT id, name, created_at, updated_at
                FROM departments WHERE id = ?
            """, (department_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="A department with this name already exists."
        ) from exc

    return dict(row)


@app.delete("/api/departments/{department_id}")
def delete_department(department_id: str, request: Request):
    _iam_directory_admin(request)

    with get_connection() as connection:
        department = connection.execute(
            "SELECT id, name FROM departments WHERE id = ?",
            (department_id,)
        ).fetchone()

        if department is None:
            raise HTTPException(status_code=404, detail="Department not found.")

        # Inventory assets are directly assigned to departments.
        # This relationship is independent of IAM users and groups.
        assets = connection.execute("""
            SELECT id, name, type, brand, serial_no, assigned_to, department
            FROM inventory_assets
            WHERE department = ? COLLATE NOCASE
            ORDER BY name COLLATE NOCASE
        """, (department["name"],)).fetchall()

        groups = connection.execute("""
            SELECT id, name, status
            FROM iam_groups
            WHERE department_id = ?
            ORDER BY name COLLATE NOCASE
        """, (department_id,)).fetchall()

        asset_items = [dict(row) for row in assets]
        group_items = [dict(row) for row in groups]

        if asset_items or group_items:
            asset_count = len(asset_items)
            group_count = len(group_items)

            raise HTTPException(
                status_code=409,
                detail={
                    "code": "department_in_use",
                    "message": (
                        f'Department "{department["name"]}" cannot be deleted. '
                        f"{asset_count} Inventory asset(s) and "
                        f"{group_count} IAM group(s) are still connected."
                    ),
                    "department": department["name"],
                    "assets": asset_items,
                    "groups": group_items,
                }
            )

        connection.execute(
            "DELETE FROM departments WHERE id = ?",
            (department_id,)
        )

    return {"deleted": True, "id": department_id}



@app.get("/api/people")
def list_people():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, name, email, username, department, status,
                   created_at, updated_at
            FROM people
            ORDER BY name COLLATE NOCASE
        """).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/people", status_code=201)
def create_person(payload: dict):
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip()
    username = str(payload.get("username") or "").strip()
    department = str(payload.get("department") or "").strip()
    status = str(payload.get("status") or "Active").strip()

    if not name or len(name) > 160:
        raise HTTPException(status_code=422, detail="Person name is required (maximum 160 characters).")
    if len(email) > 254 or len(username) > 120 or len(department) > 120:
        raise HTTPException(status_code=422, detail="A person field exceeds its maximum length.")
    if status not in {"Active", "Inactive"}:
        raise HTTPException(status_code=422, detail="Status must be Active or Inactive.")

    person_id = str(uuid.uuid4())
    try:
        with get_connection() as connection:
            if department:
                connection.execute("""
                    INSERT OR IGNORE INTO departments (id, name) VALUES (?, ?)
                """, (str(uuid.uuid4()), department))

            connection.execute("""
                INSERT INTO people (id, name, email, username, department, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (person_id, name, email, username, department, status))

            row = connection.execute("""
                SELECT id, name, email, username, department, status,
                       created_at, updated_at
                FROM people WHERE id = ?
            """, (person_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A person with this name already exists.") from exc

    return dict(row)


@app.put("/api/people/{person_id}")
def update_person(person_id: str, payload: dict):
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip()
    username = str(payload.get("username") or "").strip()
    department = str(payload.get("department") or "").strip()
    status = str(payload.get("status") or "Active").strip()

    if not name or len(name) > 160:
        raise HTTPException(status_code=422, detail="Person name is required (maximum 160 characters).")
    if len(email) > 254 or len(username) > 120 or len(department) > 120:
        raise HTTPException(status_code=422, detail="A person field exceeds its maximum length.")
    if status not in {"Active", "Inactive"}:
        raise HTTPException(status_code=422, detail="Status must be Active or Inactive.")

    try:
        with get_connection() as connection:
            current = connection.execute(
                "SELECT name FROM people WHERE id = ?", (person_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Person not found.")

            old_name = current["name"]
            if department:
                connection.execute("""
                    INSERT OR IGNORE INTO departments (id, name) VALUES (?, ?)
                """, (str(uuid.uuid4()), department))

            connection.execute("""
                UPDATE people
                SET name = ?, email = ?, username = ?, department = ?,
                    status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, email, username, department, status, person_id))

            # Keep existing inventory assignments intact when a person is renamed.
            connection.execute("""
                UPDATE inventory_assets
                SET assigned_to = ?, updated_at = CURRENT_TIMESTAMP
                WHERE assigned_to = ? COLLATE NOCASE
            """, (name, old_name))

            row = connection.execute("""
                SELECT id, name, email, username, department, status,
                       created_at, updated_at
                FROM people WHERE id = ?
            """, (person_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A person with this name already exists.") from exc

    return dict(row)


@app.delete("/api/people/{person_id}")
def delete_person(person_id: str):
    with get_connection() as connection:
        person = connection.execute(
            "SELECT name FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        if person is None:
            raise HTTPException(status_code=404, detail="Person not found.")

        usage = connection.execute("""
            SELECT COUNT(*) AS total
            FROM inventory_assets
            WHERE assigned_to = ? COLLATE NOCASE
        """, (person["name"],)).fetchone()["total"]

        if usage:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete this person while {usage} asset(s) are assigned to them.",
            )

        connection.execute("DELETE FROM people WHERE id = ?", (person_id,))

    return {"deleted": True, "id": person_id}


@app.get("/api/inventory")
def list_inventory_assets():
    """Return stored assets plus read-only network-device projections."""
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT * FROM inventory_assets
            ORDER BY created_at DESC, name COLLATE NOCASE
        """).fetchall()
        assets = [_inventory_row_to_dict(row) for row in rows]

        network_rows = connection.execute("""
            SELECT id, hostname, device_type, management_ip, vendor, model,
                   firmware, serial_number, location, status, notes,
                   created_at, updated_at
            FROM network_devices
            ORDER BY hostname COLLATE NOCASE
        """).fetchall()

        for row in network_rows:
            details = []
            if row["management_ip"]:
                details.append("Management IP: " + row["management_ip"])
            if row["firmware"]:
                details.append("Firmware: " + row["firmware"])
            if row["location"]:
                details.append("Location: " + row["location"])
            if row["status"]:
                details.append("Status: " + row["status"])
            if row["notes"]:
                details.append(row["notes"])

            tags = ["Network"]
            if row["device_type"]:
                tags.append(row["device_type"])
            if row["status"]:
                tags.append(row["status"])

            assets.append({
                "id": "network-device:" + row["id"],
                "name": row["hostname"],
                "type": "Network Device",
                "brand": row["vendor"] or "",
                "purchaseDate": "",
                "serialNo": row["serial_number"] or "",
                "department": "",
                "assignedTo": "",
                "tags": tags,
                "specialNotes": " · ".join(details),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "sourceDeviceId": None,
                "sourceType": "network_device",
                "sourceNetworkDeviceId": row["id"],
                "managementIp": row["management_ip"] or "",
                "model": row["model"] or "",
                "readOnly": True,
            })

        return assets

@app.put("/api/inventory/sync")
def sync_inventory_assets(payload: dict):
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise HTTPException(status_code=422, detail='Expected an "assets" array.')
    if len(raw_assets) > 5000:
        raise HTTPException(status_code=422, detail="Maximum 5000 assets per request.")

    assets = [_inventory_clean_asset(item) for item in raw_assets]
    ids = [a["id"] for a in assets]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=409, detail="Duplicate asset IDs in request.")

    serials = [a["serialNo"].casefold() for a in assets if a["serialNo"]]
    if len(serials) != len(set(serials)):
        raise HTTPException(status_code=409, detail="Duplicate serial numbers in request.")

    imported = 0
    skipped = 0
    with get_connection() as connection:
        existing_ids = {
            row["id"] for row in connection.execute(
                "SELECT id FROM inventory_assets"
            ).fetchall()
        }
        existing_serials = {
            row["serial_no"].casefold()
            for row in connection.execute(
                "SELECT serial_no FROM inventory_assets WHERE serial_no <> ''"
            ).fetchall()
        }

        for asset in assets:
            serial = asset["serialNo"].casefold()
            if asset["id"] in existing_ids or (serial and serial in existing_serials):
                skipped += 1
                continue
            try:
                _inventory_upsert(connection, asset)
            except sqlite3.IntegrityError:
                skipped += 1
                continue

            imported += 1
            existing_ids.add(asset["id"])
            if serial:
                existing_serials.add(serial)

    return {"synced": imported, "skipped": skipped, "mode": "merge"}

@app.get("/api/inventory/{asset_id}")
def get_inventory_asset(asset_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM inventory_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Inventory asset not found.")
    return _inventory_row_to_dict(row)


@app.post("/api/inventory", status_code=201)
def create_inventory_asset(payload: dict):
    asset = _inventory_clean_asset(payload)
    try:
        with get_connection() as connection:
            _inventory_upsert(connection, asset)
            row = connection.execute(
                "SELECT * FROM inventory_assets WHERE id = ?", (asset["id"],)
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Asset ID or serial number already exists."
        ) from exc
    return _inventory_row_to_dict(row)


@app.put("/api/inventory/{asset_id}")
def update_inventory_asset(asset_id: str, payload: dict):
    asset = _inventory_clean_asset(payload, forced_id=asset_id)
    with get_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM inventory_assets WHERE id = ?", (asset_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Inventory asset not found.")
        try:
            _inventory_upsert(connection, asset)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail="Serial number already exists on another asset."
            ) from exc
        row = connection.execute(
            "SELECT * FROM inventory_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    return _inventory_row_to_dict(row)


@app.delete("/api/inventory/{asset_id}")
def delete_inventory_asset(asset_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT source_device_id FROM inventory_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Inventory asset not found.")

        if row["source_device_id"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This asset is linked to a managed device. "
                    "Remove the device from Devices to remove its Inventory link."
                ),
            )

        connection.execute(
            "DELETE FROM inventory_assets WHERE id = ?", (asset_id,)
        )

    return {"deleted": True, "id": asset_id}




# ============================================================
# DEVICE LIFECYCLE API
# Lifecycle data is stored separately to preserve Inventory records.
# ============================================================

_DEVICE_LIFECYCLE_STAGES = {
    "Unspecified", "Planning", "Deployment", "Active", "Refresh", "Retired"
}


def _device_lifecycle_row_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "brand": row["brand"],
        "purchaseDate": row["purchase_date"],
        "serialNo": row["serial_no"],
        "department": row["department"],
        "assignedTo": row["assigned_to"],
        "lifecycleStage": row["lifecycle_stage"],
        "warrantyEndDate": row["warranty_end_date"],
        "refreshDueDate": row["refresh_due_date"],
        "retirementDate": row["retirement_date"],
        "lifecycleNotes": row["lifecycle_notes"],
        "lifecycleUpdatedAt": row["lifecycle_updated_at"],
    }


@app.get("/api/device-lifecycle")
def list_device_lifecycle_assets():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT
                a.id,
                a.name,
                a.type,
                a.brand,
                a.purchase_date,
                a.serial_no,
                a.department,
                a.assigned_to,
                COALESCE(l.stage, 'Unspecified') AS lifecycle_stage,
                COALESCE(l.warranty_end_date, '') AS warranty_end_date,
                COALESCE(l.refresh_due_date, '') AS refresh_due_date,
                COALESCE(l.retirement_date, '') AS retirement_date,
                COALESCE(l.lifecycle_notes, '') AS lifecycle_notes,
                l.updated_at AS lifecycle_updated_at
            FROM inventory_assets AS a
            LEFT JOIN device_lifecycle AS l ON l.asset_id = a.id
            ORDER BY a.name COLLATE NOCASE
        """).fetchall()

    return [_device_lifecycle_row_to_dict(row) for row in rows]


@app.put("/api/device-lifecycle/{asset_id}")
def update_device_lifecycle(asset_id: str, payload: dict):
    from datetime import date

    asset_id = str(asset_id or "").strip()
    if not asset_id or len(asset_id) > 160:
        raise HTTPException(status_code=422, detail="Invalid asset ID.")

    stage = str(payload.get("lifecycleStage", payload.get("stage", "Unspecified")) or "Unspecified").strip()
    if stage not in _DEVICE_LIFECYCLE_STAGES:
        raise HTTPException(
            status_code=422,
            detail="Lifecycle stage must be Unspecified, Planning, Deployment, Active, Refresh or Retired.",
        )

    def clean_date(field, label):
        value = str(payload.get(field) or "").strip()
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} must be a valid ISO date (YYYY-MM-DD).",
                )
        return value

    warranty_end_date = clean_date("warrantyEndDate", "Warranty end date")
    refresh_due_date = clean_date("refreshDueDate", "Refresh due date")
    retirement_date = clean_date("retirementDate", "Retirement date")
    notes = str(payload.get("lifecycleNotes", payload.get("notes", "")) or "").strip()

    if len(notes) > 4000:
        raise HTTPException(
            status_code=422,
            detail="Lifecycle notes may not exceed 4000 characters.",
        )

    with get_connection() as connection:
        asset = connection.execute(
            "SELECT id FROM inventory_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()

        if asset is None:
            raise HTTPException(status_code=404, detail="Inventory asset not found.")

        connection.execute("""
            INSERT INTO device_lifecycle (
                asset_id, stage, warranty_end_date, refresh_due_date,
                retirement_date, lifecycle_notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(asset_id) DO UPDATE SET
                stage = excluded.stage,
                warranty_end_date = excluded.warranty_end_date,
                refresh_due_date = excluded.refresh_due_date,
                retirement_date = excluded.retirement_date,
                lifecycle_notes = excluded.lifecycle_notes,
                updated_at = CURRENT_TIMESTAMP
        """, (
            asset_id, stage, warranty_end_date, refresh_due_date,
            retirement_date, notes,
        ))

        row = connection.execute("""
            SELECT
                a.id,
                a.name,
                a.type,
                a.brand,
                a.purchase_date,
                a.serial_no,
                a.department,
                a.assigned_to,
                l.stage AS lifecycle_stage,
                l.warranty_end_date AS warranty_end_date,
                l.refresh_due_date AS refresh_due_date,
                l.retirement_date AS retirement_date,
                l.lifecycle_notes AS lifecycle_notes,
                l.updated_at AS lifecycle_updated_at
            FROM inventory_assets AS a
            JOIN device_lifecycle AS l ON l.asset_id = a.id
            WHERE a.id = ?
        """, (asset_id,)).fetchone()

    return _device_lifecycle_row_to_dict(row)



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
                "package_type, install_command, install_args, uninstall_command, source_url, "
                "status, notes, created_by, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    software_id, values["name"], values["publisher"],
                    values["version"], values["target_os"], values["category"],
                    values["package_type"], values["install_command"],
                    values["install_args"], values["uninstall_command"],
                    values["source_url"],
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
                "category = ?, package_type = ?, install_command = ?, install_args = ?, "
                "uninstall_command = ?, source_url = ?, status = ?, notes = ?, "
                "updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (
                    values["name"], values["publisher"], values["version"],
                    values["target_os"], values["category"],
                    values["package_type"], values["install_command"],
                    values["install_args"], values["uninstall_command"],
                    values["source_url"],
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



def _package_storage_path(storage_key):
    if not isinstance(storage_key, str):
        return None
    if not re.fullmatch(r"[0-9a-f]{32}\.blob", storage_key):
        return None
    return PACKAGE_REPOSITORY / storage_key


@app.post("/api/software/{software_id}/package")
async def upload_software_package(
    software_id: str,
    request: Request,
    filename: str = "",
):
    """Store a private installer file and record its size and SHA-256."""
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only a Cartman administrator can upload installer packages.",
        )

    actor = normalize_operator(
        user.get("username") or user.get("display_name") or "Cartman administrator"
    )
    filename = filename.strip()

    if (
        not filename
        or len(filename) > 200
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 for char in filename)
        or Path(filename).name != filename
    ):
        raise HTTPException(status_code=422, detail="Invalid package filename.")

    with get_connection() as connection:
        software = connection.execute(
            """
            SELECT id, name, target_os, package_type, package_storage_key
            FROM software_catalog WHERE id = ?
            """,
            (software_id,),
        ).fetchone()

    if software is None:
        raise HTTPException(status_code=404, detail="Software not found.")

    package_type = (software["package_type"] or "").strip().upper()
    supported = SUPPORTED_PACKAGE_TYPES.get(package_type)
    if supported is None:
        raise HTTPException(
            status_code=422,
            detail="Supported installer types: EXE, MSI, PKG, DEB and RPM.",
        )

    expected_extension, expected_os = supported
    if Path(filename).suffix.lower() != expected_extension:
        raise HTTPException(
            status_code=422,
            detail=f"{package_type} packages must use the {expected_extension} extension.",
        )

    target_family = normalize_os_family(software["target_os"])
    if target_family != expected_os:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{package_type} installers require target OS {expected_os}; "
                f"this catalog entry targets {software['target_os']}."
            ),
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            announced_size = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length.")
        if not 0 <= announced_size <= MAX_SOFTWARE_PACKAGE_BYTES:
            raise HTTPException(status_code=413, detail="Package exceeds the 1 GiB limit.")

    PACKAGE_REPOSITORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(PACKAGE_REPOSITORY, 0o700)
    except OSError:
        pass

    temp_path = PACKAGE_REPOSITORY / (".upload-" + uuid.uuid4().hex + ".part")
    storage_key = uuid.uuid4().hex + ".blob"
    final_path = PACKAGE_REPOSITORY / storage_key
    digest = hashlib.sha256()
    total_size = 0
    committed = False

    try:
        with temp_path.open("xb") as destination:
            async for block in request.stream():
                if not block:
                    continue
                total_size += len(block)
                if total_size > MAX_SOFTWARE_PACKAGE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Package exceeds the 1 GiB limit.",
                    )
                destination.write(block)
                digest.update(block)

        if total_size == 0:
            raise HTTPException(status_code=422, detail="Uploaded package is empty.")

        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, final_path)

        sha256 = digest.hexdigest()
        old_storage_key = software["package_storage_key"] or ""

        with get_connection() as connection:
            current = connection.execute(
                "SELECT id, name FROM software_catalog WHERE id = ?",
                (software_id,),
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Software not found.")

            connection.execute(
                """
                UPDATE software_catalog
                SET package_storage_key = ?,
                    package_filename = ?,
                    package_size = ?,
                    package_sha256 = ?,
                    package_uploaded_at = CURRENT_TIMESTAMP,
                    package_uploaded_by = ?,
                    updated_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    storage_key, filename, total_size, sha256,
                    actor, actor, software_id,
                ),
            )
            write_software_audit(
                connection,
                software_id,
                current["name"],
                "Package uploaded",
                actor,
                {
                    "filename": filename,
                    "size": total_size,
                    "sha256": sha256,
                    "package_type": package_type,
                },
            )
            row = connection.execute(
                "SELECT * FROM software_catalog WHERE id = ?",
                (software_id,),
            ).fetchone()

        committed = True

        if old_storage_key and old_storage_key != storage_key:
            old_path = _package_storage_path(old_storage_key)
            if old_path and old_path.is_file():
                try:
                    old_path.unlink()
                except OSError:
                    pass

        return serialize_software(row)

    except BaseException:
        if not committed:
            for path in (temp_path, final_path):
                try:
                    path.unlink()
                except OSError:
                    pass
        raise


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
                    'self_test',
                    'remote_command'
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

    if "'remote_command'" not in task_schema_sql:
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
                        'self_test',
                    'remote_command'
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
                created_at, started_at, finished_at, scheduled_at
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
    _task_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(device_tasks)").fetchall()
    }
    if "scheduled_at" not in _task_columns:
        connection.execute("ALTER TABLE device_tasks ADD COLUMN scheduled_at TEXT")


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



# CARTMAN_HWID_BAN_V1
_HWID_HASH_KEYS = (
    "system_uuid_hash", "board_serial_hash",
    "product_serial_hash", "fingerprint",
)


def _ensure_hwid_schema():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS device_agent_hardware (
                client_instance TEXT PRIMARY KEY,
                device_id TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                fingerprint TEXT NOT NULL DEFAULT '',
                system_uuid_hash TEXT NOT NULL DEFAULT '',
                board_serial_hash TEXT NOT NULL DEFAULT '',
                product_serial_hash TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS device_hwid_bans (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'Active'
                    CHECK (status IN ('Active', 'Revoked')),
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at TEXT,
                device_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                os TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT '',
                manufacturer TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                device_type TEXT NOT NULL DEFAULT '',
                client_instance TEXT NOT NULL DEFAULT '',
                device_id TEXT NOT NULL DEFAULT '',
                hardware_fingerprint TEXT NOT NULL DEFAULT '',
                identity_snapshot_json TEXT NOT NULL DEFAULT '{}',
                notes TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_device_hwid_bans_status_created
                ON device_hwid_bans(status, created_at DESC);

            CREATE TABLE IF NOT EXISTS device_hwid_ban_identifiers (
                id TEXT PRIMARY KEY,
                ban_id TEXT NOT NULL,
                identifier_type TEXT NOT NULL,
                identifier_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ban_id) REFERENCES device_hwid_bans(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_hwid_ban_identifier_lookup
                ON device_hwid_ban_identifiers(identifier_type, identifier_hash);

            CREATE INDEX IF NOT EXISTS idx_agent_hardware_device
                ON device_agent_hardware(device_id);
        """)


def _sanitize_hardware_identity(value):
    if not isinstance(value, dict):
        return {}

    result = {}
    for key in _HWID_HASH_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str):
            candidate = candidate.strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", candidate):
                result[key] = candidate

    if result:
        platform_name = value.get("platform", "")
        if isinstance(platform_name, str):
            platform_name = platform_name.strip()
            if platform_name in {"Windows", "Darwin", "Linux"}:
                result["platform"] = platform_name

    return result


def _hwid_identifier_values(hardware_identity=None, client_instance=None,
                            public_key_text=None):
    identity = _sanitize_hardware_identity(hardware_identity)
    result = []

    for key in _HWID_HASH_KEYS:
        value = identity.get(key)
        if value:
            material = "cartman-hwid-ban-v1|{}|{}".format(key, value)
            result.append((
                key, hashlib.sha256(material.encode("utf-8")).hexdigest()
            ))

    if isinstance(client_instance, str) and client_instance.strip():
        try:
            normalized = str(uuid.UUID(client_instance.strip()))
            material = "cartman-hwid-ban-v1|client_instance|{}".format(normalized)
            result.append((
                "client_instance",
                hashlib.sha256(material.encode("utf-8")).hexdigest()
            ))
        except (ValueError, TypeError, AttributeError):
            pass

    if isinstance(public_key_text, str) and 1 <= len(public_key_text) <= 512:
        material = "cartman-hwid-ban-v1|public_key|{}".format(public_key_text)
        result.append((
            "public_key",
            hashlib.sha256(material.encode("utf-8")).hexdigest()
        ))

    return list(dict.fromkeys(result))


def _find_active_hwid_ban(connection, hardware_identity=None,
                          client_instance=None, public_key_text=None):
    for kind, digest in _hwid_identifier_values(
        hardware_identity, client_instance, public_key_text
    ):
        row = connection.execute(
            """
            SELECT b.id, b.reason
            FROM device_hwid_ban_identifiers i
            JOIN device_hwid_bans b ON b.id = i.ban_id
            WHERE b.status = 'Active'
              AND i.identifier_type = ? AND i.identifier_hash = ?
            ORDER BY b.created_at DESC LIMIT 1
            """,
            (kind, digest),
        ).fetchone()
        if row is not None:
            return dict(row)
    return None


def _save_agent_hardware(connection, device_id, client_instance, value):
    identity = _sanitize_hardware_identity(value)
    if not identity:
        return

    try:
        instance = str(uuid.UUID(str(client_instance)))
    except (ValueError, TypeError, AttributeError):
        return

    connection.execute(
        """
        INSERT INTO device_agent_hardware (
            client_instance, device_id, platform, fingerprint,
            system_uuid_hash, board_serial_hash, product_serial_hash,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(client_instance) DO UPDATE SET
            device_id = excluded.device_id,
            platform = CASE WHEN excluded.platform <> '' THEN excluded.platform
                ELSE device_agent_hardware.platform END,
            fingerprint = CASE WHEN excluded.fingerprint <> ''
                THEN excluded.fingerprint
                ELSE device_agent_hardware.fingerprint END,
            system_uuid_hash = CASE WHEN excluded.system_uuid_hash <> ''
                THEN excluded.system_uuid_hash
                ELSE device_agent_hardware.system_uuid_hash END,
            board_serial_hash = CASE WHEN excluded.board_serial_hash <> ''
                THEN excluded.board_serial_hash
                ELSE device_agent_hardware.board_serial_hash END,
            product_serial_hash = CASE WHEN excluded.product_serial_hash <> ''
                THEN excluded.product_serial_hash
                ELSE device_agent_hardware.product_serial_hash END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            instance, str(device_id or ""), identity.get("platform", ""),
            identity.get("fingerprint", ""),
            identity.get("system_uuid_hash", ""),
            identity.get("board_serial_hash", ""),
            identity.get("product_serial_hash", ""),
        ),
    )


def _require_hwid_admin(request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only a Cartman administrator can manage HWID bans.",
        )
    return user


_ensure_hwid_schema()
# END CARTMAN_HWID_BAN_V1


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
            "remote_command",
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
_connection_client_sockets = {}
_connection_listener_tls_fingerprint = None


DEVICE_AUTHENTICATED_PORT = 50102
_authenticated_listener_server = None
_authenticated_listener_thread = None
_authenticated_listener_tls_fingerprint = None
_authenticated_listener_lock = threading.Lock()

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
            sql = """
                SELECT id, action, payload
                FROM device_tasks
                WHERE device_id = ? AND status = 'Queued'
                  AND (scheduled_at IS NULL OR scheduled_at <= CURRENT_TIMESTAMP)
                ORDER BY created_at, rowid
                LIMIT 100
            """
            rows = connection.execute(sql, (device_id,)).fetchall()
            row = None
            for candidate in rows:
                try:
                    candidate_payload = json.loads(candidate["payload"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    candidate_payload = {}
                is_dns_dhcp = (
                    candidate["action"] == "remote_command"
                    and candidate_payload.get("connector_action")
                    == "windows_dns_dhcp_management_v1"
                )
                if getattr(self, "_claim_dns_dhcp_only", False) and not is_dns_dhcp:
                    continue
                if getattr(self, "_claim_exclude_dns_dhcp", False) and is_dns_dhcp:
                    continue
                row = candidate
                break

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
                    SELECT install_command, name, version, install_args,
                           package_type, package_storage_key, package_filename,
                           package_size, package_sha256
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

                    storage_key = package["package_storage_key"] or ""
                    filename = package["package_filename"] or ""
                    size = int(package["package_size"] or 0)
                    package_hash = package["package_sha256"] or ""
                    storage_path = _package_storage_path(storage_key)

                    if storage_key:
                        if (
                            storage_path
                            and storage_path.is_file()
                            and filename
                            and size > 0
                            and storage_path.stat().st_size == size
                            and len(package_hash) == 64
                        ):
                            execution.update({
                                "package_available": True,
                                "package_filename": filename,
                                "package_size": size,
                                "package_sha256": package_hash,
                                "package_type": package["package_type"],
                                "install_args": package["install_args"] or "",
                            })
                        else:
                            execution["package_error"] = (
                                "Uploaded installer is missing or its metadata is invalid."
                            )

            return {
                "id": row["id"],
                "action": row["action"],
                "payload": payload,
                "execution": execution,
            }


    def _send_package_chunk(self, request_id, message):
        task_id = message.get("task_id")
        offset = message.get("offset")
        requested_size = message.get("size")

        if (
            not isinstance(task_id, str)
            or not task_id
            or type(offset) is not int
            or offset < 0
            or type(requested_size) is not int
            or not 1 <= requested_size <= MAX_PACKAGE_CHUNK_BYTES
        ):
            self._reply({"status": "error", "message": "Invalid package chunk request."})
            return

        with get_connection() as connection:
            enrollment = connection.execute(
                """
                SELECT status, device_id
                FROM device_connection_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()

            if (
                enrollment is None
                or enrollment["status"] != "Approved"
                or not enrollment["device_id"]
            ):
                self._reply({
                    "status": "error",
                    "message": "An approved device identity is required.",
                })
                return

            task_row = connection.execute(
                """
                SELECT id, device_id, action, payload, status
                FROM device_tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()

            if (
                task_row is None
                or task_row["device_id"] != enrollment["device_id"]
                or task_row["action"] != "package_deployment"
                or task_row["status"] != "Running"
            ):
                self._reply({
                    "status": "error",
                    "message": "This task is not available to the connected device.",
                })
                return

            try:
                task_payload = json.loads(task_row["payload"] or "{}")
            except (TypeError, json.JSONDecodeError):
                task_payload = {}

            package = connection.execute(
                """
                SELECT package_storage_key, package_filename,
                       package_size, package_sha256
                FROM software_catalog WHERE id = ?
                """,
                (task_payload.get("software_id"),),
            ).fetchone()

            if package is None:
                self._reply({
                    "status": "error",
                    "message": "Software package record not found.",
                })
                return

            storage_path = _package_storage_path(package["package_storage_key"])
            total_size = int(package["package_size"] or 0)
            expected_hash = package["package_sha256"] or ""

        if (
            not storage_path
            or not storage_path.is_file()
            or total_size < 1
            or total_size > MAX_SOFTWARE_PACKAGE_BYTES
            or offset >= total_size
            or len(expected_hash) != 64
        ):
            self._reply({
                "status": "error",
                "message": "Package file or metadata is invalid.",
            })
            return

        try:
            with storage_path.open("rb") as package_file:
                package_file.seek(offset)
                block = package_file.read(
                    min(requested_size, total_size - offset)
                )
        except OSError:
            self._reply({
                "status": "error",
                "message": "Package file could not be read.",
            })
            return

        if not block:
            self._reply({
                "status": "error",
                "message": "Package file returned an empty chunk unexpectedly.",
            })
            return

        self._reply({
            "status": "package_chunk",
            "task_id": task_id,
            "offset": offset,
            "total_size": total_size,
            "sha256": expected_hash,
            "data": base64.b64encode(block).decode("ascii"),
        })


    def _save_task_result(self, request_id, message):
        status = message.get("result_status")
        task_id = message.get("task_id")
        result = message.get("result", "")

        if status not in {"Succeeded", "Failed", "Cancelled"}:
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


    def _record_client_telemetry(self, request_id, telemetry):
        """Persist bounded metrics only for this connection's approved device."""
        allowed_metrics = {
            "cpu_percent": "%",
            "memory_percent": "%",
            "disk_percent": "%",
        }

        if not isinstance(telemetry, list) or len(telemetry) > 3:
            return 0, "Invalid telemetry payload."
        if not telemetry:
            return 0, None

        validated = []
        seen = set()
        for item in telemetry:
            if not isinstance(item, dict):
                return 0, "Invalid telemetry sample."
            name = item.get("metric_name")
            value = item.get("value")

            if name not in allowed_metrics or name in seen:
                return 0, "Unsupported or duplicate telemetry metric."
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return 0, "Telemetry value must be numeric."
            if not math.isfinite(float(value)):
                return 0, "Telemetry value must be finite."
            value = float(value)
            if value < 0 or (name.endswith("_percent") and value > 100):
                return 0, "Telemetry value is outside its allowed range."

            seen.add(name)
            validated.append((name, value, allowed_metrics[name]))

        try:
            with get_connection() as connection:
                enrollment = connection.execute(
                    """
                    SELECT status, device_id
                    FROM device_connection_requests
                    WHERE id = ?
                    """,
                    (request_id,),
                ).fetchone()

                if (
                    enrollment is None
                    or enrollment["status"] != "Approved"
                    or not enrollment["device_id"]
                ):
                    return 0, "Device enrollment is not approved."

                device_id = enrollment["device_id"]
                if not connection.execute(
                    "SELECT id FROM devices WHERE id = ?", (device_id,)
                ).fetchone():
                    return 0, "Registered device no longer exists."

                for name, value, unit in validated:
                    connection.execute(
                        """
                        INSERT INTO monitoring_metrics
                            (id, device_id, metric_name, value, unit, source, collected_at)
                        VALUES (?, ?, ?, ?, ?, 'cartman-client', CURRENT_TIMESTAMP)
                        """,
                        (str(uuid.uuid4()), device_id, name, value, unit),
                    )
        except sqlite3.Error as exc:
            print("Could not persist CartmanClient telemetry:", type(exc).__name__)
            return 0, "Telemetry storage failed."

        return len(validated), None


    def setup(self):
        tls_context = getattr(self.server, "tls_context", None)
        if tls_context is not None:
            raw_socket = self.request
            raw_socket.settimeout(10)
            try:
                self.request = tls_context.wrap_socket(
                    raw_socket, server_side=True
                )
                self.request.settimeout(75)
            except Exception:
                raw_socket.close()
                raise
        super().setup()

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
            windows_dns_dhcp_management_enabled = hello.get("windows_dns_dhcp_management_enabled") is True

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
            hardware_identity = _sanitize_hardware_identity(
                hello.get("hardware_identity")
            )
            identity_metadata["hardware_identity"] = hardware_identity

            connection_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            client_ip = str(self.client_address[0])[:64]

            with get_connection() as connection:
                active_hwid_ban = _find_active_hwid_ban(
                    connection, hardware_identity, client_instance, public_key_text
                )
                trusted = connection.execute(
                    """
                    SELECT device_id, public_key, revoked
                    FROM device_agent_credentials
                    WHERE client_instance = ?
                    """,
                    (client_instance,),
                ).fetchone()

            if active_hwid_ban is not None:
                self._reply({
                    "status": "error",
                    "message": (
                        "This device matches an active Cartman hardware "
                        "identity ban. Contact a Cartman administrator."
                    ),
                })
                return

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

                    _save_agent_hardware(
                        connection, device_id, client_instance, hardware_identity
                    )
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
                if getattr(self.server, "require_existing_identity", False):
                    self._reply({
                        "status": "error",
                        "message": (
                            "Unknown client identity. Port 50102 only accepts "
                            "previously registered and approved CartmanClient identities."
                        ),
                    })
                    return

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
                _connection_client_sockets[connection_id] = self.request
                _connection_clients[connection_id] = {
                    "connection_id": connection_id,
                    "request_id": request_id,
                    "device_id": device_id,
                    "client_instance": client_instance,
                    "public_key": public_key_text,
                    "hardware_identity": hardware_identity,
                    "device_name": name.strip(),
                    "os": os_name.strip(),
                    "username": username.strip(),
                    "client_ip": client_ip,
                    "connected": True,
                    "state": "Connected" if approval == "Approved"
                        else "Connected · awaiting approval",
                    "approval_status": approval,
                    "task_execution_enabled": task_execution_enabled,
                    "windows_dns_dhcp_management_enabled": windows_dns_dhcp_management_enabled,
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

                # Re-check revocation before processing any message from an
                # approved agent. Pending enrollment has no credential yet.
                if approval == "Approved":
                    with get_connection() as connection:
                        active_hwid_ban = _find_active_hwid_ban(
                            connection, hardware_identity,
                            client_instance, public_key_text
                        )
                        credential = connection.execute(
                            """
                            SELECT device_id, public_key, revoked
                            FROM device_agent_credentials
                            WHERE client_instance = ?
                            """,
                            (client_instance,),
                        ).fetchone()

                    if active_hwid_ban is not None:
                        self._reply({
                            "status": "rejected",
                            "message": (
                                "This device matches an active Cartman "
                                "hardware identity ban."
                            ),
                        })
                        break

                    if (
                        credential is None
                        or credential["revoked"]
                        or credential["device_id"] != device_id
                        or credential["public_key"] != public_key_text
                    ):
                        self._reply({
                            "status": "revoked",
                            "message": (
                                "This CartmanClient identity is no longer trusted. "
                                "Disconnect and contact a Cartman administrator."
                            ),
                        })
                        break

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
                    telemetry_accepted, telemetry_error = (0, None)
                    if "telemetry" in message:
                        telemetry_accepted, telemetry_error = self._record_client_telemetry(
                            request_id, message.get("telemetry")
                        )
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
                    if approval == "Approved" and device_id and (
                        task_execution_enabled or windows_dns_dhcp_management_enabled
                    ):
                        try:
                            self._claim_dns_dhcp_only = bool(
                                windows_dns_dhcp_management_enabled and not task_execution_enabled
                            )
                            self._claim_exclude_dns_dhcp = bool(
                                task_execution_enabled and not windows_dns_dhcp_management_enabled
                            )
                            task = self._claim_task(device_id)
                        except Exception as exc:
                            print("Could not dispatch a device task:", type(exc).__name__, str(exc))
                        finally:
                            self._claim_dns_dhcp_only = False
                            self._claim_exclude_dns_dhcp = False

                    self._reply({
                        "status": "connected",
                        "approval_status": approval,
                        "last_seen": now,
                        "task": task,
                        "telemetry_accepted": telemetry_accepted,
                        "telemetry_error": telemetry_error,
                    })

                elif message_type == "package_chunk_request":
                    self._send_package_chunk(request_id, message)


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
                    _connection_client_sockets.pop(connection_id, None)
                    current = _connection_clients.get(connection_id)
                    if current:
                        current["connected"] = False
                        current["state"] = (
                            "Revoked · disconnected"
                            if current.get("revoked")
                            else (
                                "Rejected · disconnected"
                                if current.get("approval_status") == "Rejected"
                                else "Disconnected"
                            )
                        )
                        current["last_seen"] = self._utc_now()


class _CartmanTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        tls_context=None,
        require_existing_identity=False,
    ):
        self.tls_context = tls_context
        self.require_existing_identity = bool(require_existing_identity)
        super().__init__(server_address, RequestHandlerClass)

class DeviceListenerStartInput(BaseModel):
    address_mode: str = "local"


@app.get("/api/device-connection-listener/status")
def device_connection_listener_status():
    server = _connection_listener_server
    thread = _connection_listener_thread
    auth_server = _authenticated_listener_server
    auth_thread = _authenticated_listener_thread

    legacy_running = bool(server and thread and thread.is_alive())
    auth_running = bool(auth_server and auth_thread and auth_thread.is_alive())

    return {
        "running": legacy_running,
        "port": DEVICE_CONNECTION_PORT,
        "mode": _connection_listener_mode,
        "listen_address": str(server.server_address[0]) if server else "",
        "local_ip": _cartman_local_ip(),
        "public_ip": _cartman_public_ip(),
        "public_listening_enabled": False,

        # Legacy enrollment port: retain its original unencrypted protocol.
        "tls_required": False,
        "tls_enabled": False,
        "tls_minimum_version": None,
        "tls_fingerprint_sha256": None,

        # Persistent, authenticated agent channel.
        "authenticated_port": DEVICE_AUTHENTICATED_PORT,
        "authenticated_listener_running": auth_running,
        "authenticated_listener_listen_address": (
            str(auth_server.server_address[0]) if auth_server else ""
        ),
        "authenticated_listener_tls_required": True,
        "authenticated_listener_tls_enabled": auth_running,
        "authenticated_listener_tls_minimum_version": "TLS 1.2",
        "authenticated_listener_tls_fingerprint_sha256": (
            _authenticated_listener_tls_fingerprint if auth_running else None
        ),
        "authenticated_listener_identity_policy": "registered-approved-identities-only",
        "authenticated_listener_public_listening_enabled": False,
    }

@app.post("/api/device-connection-listener/start")
def start_device_connection_listener(payload: DeviceListenerStartInput):
    global _connection_listener_server
    global _connection_listener_thread
    global _connection_listener_mode
    global _connection_listener_tls_fingerprint

    if payload.address_mode != "local":
        raise HTTPException(
            status_code=409,
            detail=(
                "Public listening is disabled for the legacy enrollment listener. "
                "Use the authenticated local-network listener on port 50102 "
                "for previously registered agents."
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
                "tls_enabled": False,
                "authenticated_port": DEVICE_AUTHENTICATED_PORT,
            }

        try:
            # Deliberately no TLS context on port 50101: preserve its legacy
            # enrollment/approval protocol for existing clients.
            server = _CartmanTCPServer(
                (local_ip, DEVICE_CONNECTION_PORT),
                _CartmanConnectionHandler,
                tls_context=None,
                require_existing_identity=False,
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
            name="cartman-device-enrollment-listener",
            daemon=True,
        )
        _connection_listener_server = server
        _connection_listener_thread = thread
        _connection_listener_mode = "local"
        _connection_listener_tls_fingerprint = None
        thread.start()

    return {
        "running": True,
        "mode": "local",
        "listen_address": local_ip,
        "port": DEVICE_CONNECTION_PORT,
        "tls_enabled": False,
        "authenticated_port": DEVICE_AUTHENTICATED_PORT,
    }

@app.post("/api/device-connection-listener/stop")
def stop_device_connection_listener():
    global _connection_listener_server
    global _connection_listener_thread
    global _connection_listener_mode
    global _connection_listener_tls_fingerprint

    with _connection_listener_lock:
        server = _connection_listener_server
        thread = _connection_listener_thread
        _connection_listener_server = None
        _connection_listener_thread = None
        _connection_listener_mode = None
        _connection_listener_tls_fingerprint = None

    if server is not None:
        if thread is not None and thread.is_alive():
            server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    return {
        "running": False,
        "port": DEVICE_CONNECTION_PORT,
        "tls_enabled": False,
        "authenticated_port": DEVICE_AUTHENTICATED_PORT,
        "authenticated_listener_stopped": False,
    }


def _start_authenticated_agent_listener():
    global _authenticated_listener_server
    global _authenticated_listener_thread
    global _authenticated_listener_tls_fingerprint

    with _authenticated_listener_lock:
        if (
            _authenticated_listener_server is not None
            and _authenticated_listener_thread is not None
            and _authenticated_listener_thread.is_alive()
        ):
            return

        local_ip = _cartman_local_ip()
        if not local_ip:
            raise RuntimeError(
                "Cannot start authenticated CartmanClient listener: "
                "could not determine the local network IPv4 address."
            )

        try:
            try:
                from .agent_tls import create_agent_tls_server_context
            except ImportError:
                from agent_tls import create_agent_tls_server_context

            tls_context, fingerprint = create_agent_tls_server_context()
            server = _CartmanTCPServer(
                (local_ip, DEVICE_AUTHENTICATED_PORT),
                _CartmanConnectionHandler,
                tls_context=tls_context,
                require_existing_identity=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not start authenticated listener on "
                f"{local_ip}:{DEVICE_AUTHENTICATED_PORT}: {exc}"
            ) from exc

        thread = threading.Thread(
            target=server.serve_forever,
            name="cartman-authenticated-agent-listener",
            daemon=True,
        )
        _authenticated_listener_server = server
        _authenticated_listener_thread = thread
        _authenticated_listener_tls_fingerprint = fingerprint
        thread.start()

    print(
        "Cartman authenticated agent listener running on "
        f"{local_ip}:{DEVICE_AUTHENTICATED_PORT} (TLS 1.2+)."
    )
    print("CartmanClient TLS SHA-256 certificate fingerprint:", fingerprint)


@app.on_event("startup")
def _cartman_start_authenticated_agent_listener():
    # Port 50102 starts with Cartman and is independent of the 50101 UI control.
    _start_authenticated_agent_listener()


@app.on_event("shutdown")
def _cartman_stop_authenticated_agent_listener():
    global _authenticated_listener_server
    global _authenticated_listener_thread
    global _authenticated_listener_tls_fingerprint

    with _authenticated_listener_lock:
        server = _authenticated_listener_server
        thread = _authenticated_listener_thread
        _authenticated_listener_server = None
        _authenticated_listener_thread = None
        _authenticated_listener_tls_fingerprint = None

    if server is not None:
        if thread is not None and thread.is_alive():
            server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

# CARTMAN_ENDPOINT_AGENTS_API_V1
@app.get("/api/endpoint-agents")
def list_endpoint_agents():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT
                c.client_instance,
                c.device_id,
                c.created_at,
                c.last_seen AS credential_last_seen,
                d.name AS device_name,
                d.os AS device_os,
                d.status AS device_status,
                d.ip AS device_ip,
                d.username AS device_username,
                d.manufacturer,
                d.model,
                d.device_type,
                h.platform AS hardware_platform,
                h.fingerprint AS hardware_fingerprint,
                h.system_uuid_hash,
                h.board_serial_hash,
                h.product_serial_hash
            FROM device_agent_credentials c
            JOIN devices d ON d.id = c.device_id
            LEFT JOIN device_agent_hardware h ON h.client_instance = c.client_instance
            WHERE c.revoked = 0
            ORDER BY COALESCE(c.last_seen, c.created_at) DESC
            LIMIT 2000
        """).fetchall()

    with _connection_clients_lock:
        live_clients = [
            dict(client)
            for client in _connection_clients.values()
            if client.get("connected") is True
            and client.get("approval_status") == "Approved"
        ]

    live_by_instance = {}
    for client in live_clients:
        instance = client.get("client_instance")
        if instance:
            live_by_instance[instance] = client

    items = []
    for row in rows:
        item = dict(row)
        instance = item["client_instance"]
        live = live_by_instance.get(instance)

        item["agent_id"] = instance
        stored_identity = _sanitize_hardware_identity({
            "platform": item.get("hardware_platform", ""),
            "fingerprint": item.get("hardware_fingerprint", ""),
            "system_uuid_hash": item.get("system_uuid_hash", ""),
            "board_serial_hash": item.get("board_serial_hash", ""),
            "product_serial_hash": item.get("product_serial_hash", ""),
        })
        live_identity = _sanitize_hardware_identity((live or {}).get("hardware_identity"))
        item["hardware_identity"] = live_identity or stored_identity
        item["hwid_available"] = bool(item["hardware_identity"])
        item["device_name"] = (
            item.get("device_name")
            or (live or {}).get("device_name")
            or "Missing device record"
        )
        item["device_os"] = (
            item.get("device_os")
            or (live or {}).get("os")
            or "Unknown"
        )
        item["status"] = "Online" if live else "Offline"
        item["last_seen"] = (
            (live or {}).get("last_seen")
            or item.get("credential_last_seen")
        )
        item["client_ip"] = (
            (live or {}).get("client_ip") or item.get("device_ip") or ""
        )
        item["username"] = (
            (live or {}).get("username") or item.get("device_username") or ""
        )
        item["agent_version"] = "Unknown"
        item["collectors"] = "Not reported"
        items.append(item)

    online = sum(1 for item in items if item["status"] == "Online")

    return {
        "items": items,
        "stats": {
            "total": len(items),
            "online": online,
            "offline": len(items) - online,
        },
    }

@app.post("/api/endpoint-agents/{client_instance}/revoke")
def revoke_endpoint_agent(client_instance: str, request: Request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only a Cartman administrator can revoke an agent.",
        )

    try:
        normalized_id = str(uuid.UUID(client_instance))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail="Invalid agent identity.")

    actor = (
        user.get("username")
        or user.get("display_name")
        or "Cartman administrator"
    )

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        credential = connection.execute(
            """
            SELECT client_instance, device_id, revoked
            FROM device_agent_credentials
            WHERE client_instance = ?
            """,
            (normalized_id,),
        ).fetchone()

        if credential is None:
            raise HTTPException(status_code=404, detail="Agent identity not found.")

        already_revoked = bool(credential["revoked"])
        if not already_revoked:
            connection.execute(
                """
                UPDATE device_agent_credentials
                SET revoked = 1
                WHERE client_instance = ?
                """,
                (normalized_id,),
            )
            _auth_security._write_audit(
                connection,
                actor,
                "agent.revoked",
                "device_agent",
                normalized_id,
                {"device_id": credential["device_id"]},
            )

        device_id = credential["device_id"]

    sockets = []
    with _connection_clients_lock:
        for connection_id, client in _connection_clients.items():
            if client.get("client_instance") != normalized_id:
                continue

            client["revoked"] = True
            client["connected"] = False
            client["state"] = "Revoked · disconnecting"

            live_socket = _connection_client_sockets.get(connection_id)
            if live_socket is not None:
                sockets.append(live_socket)

    connections_closed = 0
    for live_socket in sockets:
        try:
            # SHUT_RDWR: stop receiving and sending on this TCP socket.
            live_socket.shutdown(2)
            connections_closed += 1
        except OSError:
            pass

    return {
        "revoked": True,
        "already_revoked": already_revoked,
        "client_instance": normalized_id,
        "device_id": device_id,
        "active_connections_closed": connections_closed,
    }



# CARTMAN_HWID_BAN_API_V1
@app.get("/api/hwid-bans")
def list_hwid_bans(request: Request):
    _require_hwid_admin(request)
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT b.*,
                (SELECT COUNT(*) FROM device_hwid_ban_identifiers i
                 WHERE i.ban_id = b.id) AS identifier_count
            FROM device_hwid_bans b
            ORDER BY CASE WHEN b.status = 'Active' THEN 0 ELSE 1 END,
                     b.created_at DESC
            LIMIT 500
        """).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        try:
            snapshot = json.loads(item.pop("identity_snapshot_json") or "{}")
        except (ValueError, TypeError):
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        item["hardware_identity"] = _sanitize_hardware_identity(
            snapshot.get("hardware_identity")
        )
        result.append(item)
    return {"items": result, "count": len(result)}


@app.post("/api/hwid-bans", status_code=201)
def create_hwid_ban(payload: dict, request: Request):
    user = _require_hwid_admin(request)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Expected a JSON object.")

    def field(key, limit=180, default=""):
        value = payload.get(key, default)
        return value.strip()[:limit] if isinstance(value, str) else default

    reason = field("reason", 500)
    if not reason:
        raise HTTPException(status_code=422, detail="A ban reason is required.")

    device_name = field("device_name", 120, "Unknown endpoint") or "Unknown endpoint"
    username = field("username", 120)
    os_name = field("os", 120, "Unknown") or "Unknown"
    client_ip = field("client_ip", 64)
    manufacturer = field("manufacturer", 120)
    model = field("model", 180)
    device_type = field("device_type", 80)
    notes = field("notes", 1000)
    client_instance = field("client_instance", 64)
    device_id = field("device_id", 100)
    identity = _sanitize_hardware_identity(payload.get("hardware_identity"))

    if client_instance:
        try:
            client_instance = str(uuid.UUID(client_instance))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status_code=422, detail="Invalid agent identity.")

    public_key = ""
    with get_connection() as connection:
        if client_instance:
            credential = connection.execute(
                "SELECT device_id, public_key FROM device_agent_credentials "
                "WHERE client_instance = ?",
                (client_instance,),
            ).fetchone()
            if credential is not None:
                device_id = device_id or credential["device_id"]
                public_key = credential["public_key"]

    supplied_key = field("public_key", 512)
    if not public_key and supplied_key:
        try:
            if len(base64.b64decode(supplied_key, validate=True)) != 32:
                raise ValueError("Invalid key length.")
            public_key = supplied_key
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid public key.")

    identifiers = _hwid_identifier_values(identity, client_instance, public_key)
    if not identifiers:
        raise HTTPException(
            status_code=422,
            detail="Provide a valid hardware identity or agent identity. IP, username and model alone are insufficient.",
        )

    ban_id = str(uuid.uuid4())
    actor = user.get("username") or user.get("display_name") or "Cartman administrator"
    snapshot = {
        "hardware_identity": identity,
        "identifier_types": [kind for kind, _ in identifiers],
    }

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = _find_active_hwid_ban(
            connection, identity, client_instance, public_key
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="An active ban already matches ID {}.".format(existing["id"]),
            )

        connection.execute(
            """
            INSERT INTO device_hwid_bans (
                id, status, reason, actor, device_name, username, os, client_ip,
                manufacturer, model, device_type, client_instance, device_id,
                hardware_fingerprint, identity_snapshot_json, notes
            ) VALUES (?, 'Active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ban_id, reason, actor, device_name, username, os_name, client_ip,
                manufacturer, model, device_type, client_instance, device_id,
                identity.get("fingerprint", ""),
                json.dumps(snapshot, ensure_ascii=False), notes,
            ),
        )
        for kind, digest in identifiers:
            connection.execute(
                """
                INSERT INTO device_hwid_ban_identifiers
                    (id, ban_id, identifier_type, identifier_hash)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), ban_id, kind, digest),
            )

        _auth_security._write_audit(
            connection, actor, "device.hwid_banned", "device_hwid_ban", ban_id,
            {
                "device_name": device_name, "username": username,
                "os": os_name, "reason": reason,
                "identifier_types": [kind for kind, _ in identifiers],
            },
        )

    identifiers_set = set(identifiers)
    sockets = []
    with _connection_clients_lock:
        for connection_id, client in _connection_clients.items():
            live_ids = set(_hwid_identifier_values(
                client.get("hardware_identity"),
                client.get("client_instance"),
                client.get("public_key"),
            ))
            if identifiers_set.intersection(live_ids):
                client["revoked"] = True
                client["connected"] = False
                client["state"] = "Banned · disconnecting"
                sock = _connection_client_sockets.get(connection_id)
                if sock is not None:
                    sockets.append(sock)

    closed = 0
    for sock in sockets:
        try:
            sock.shutdown(2)
            closed += 1
        except OSError:
            pass

    return {
        "id": ban_id, "status": "Active", "device_name": device_name,
        "reason": reason, "identifier_types": [kind for kind, _ in identifiers],
        "active_connections_closed": closed,
    }


@app.post("/api/hwid-bans/{ban_id}/revoke")
def revoke_hwid_ban(ban_id: str, request: Request):
    user = _require_hwid_admin(request)
    try:
        ban_id = str(uuid.UUID(ban_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail="Invalid HWID ban ID.")

    actor = user.get("username") or user.get("display_name") or "Cartman administrator"
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id, status, device_name FROM device_hwid_bans WHERE id = ?",
            (ban_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="HWID ban not found.")

        changed = row["status"] == "Active"
        if changed:
            connection.execute(
                "UPDATE device_hwid_bans SET status='Revoked', "
                "revoked_at=CURRENT_TIMESTAMP WHERE id = ?",
                (ban_id,),
            )
            _auth_security._write_audit(
                connection, actor, "device.hwid_ban_revoked",
                "device_hwid_ban", ban_id, {"device_name": row["device_name"]},
            )
    return {"id": ban_id, "status": "Revoked", "already_revoked": not changed}
# END CARTMAN_HWID_BAN_API_V1


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

        if decision.decision == "Approved":
            approved_instance = hardware.get("client_instance")
            if approved_instance:
                try:
                    approved_instance = str(uuid.UUID(approved_instance))
                except (ValueError, TypeError, AttributeError):
                    approved_instance = ""
                if approved_instance:
                    _save_agent_hardware(
                        connection, device_id, approved_instance,
                        hardware.get("hardware_identity"),
                    )

        connection.execute(
            """
            UPDATE device_connection_requests
            SET status = ?, reviewed_at = CURRENT_TIMESTAMP, device_id = ?
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
            SELECT d.*,
                   u.name AS assigned_user_name,
                   u.username AS assigned_user_username,
                   u.email AS assigned_user_email,
                   dep.name AS department_name
            FROM devices AS d
            LEFT JOIN iam_users AS u ON u.id = d.assigned_user_id
            LEFT JOIN departments AS dep ON dep.id = d.department_id
            ORDER BY COALESCE(NULLIF(d.display_name, ''), d.name) COLLATE NOCASE
        """).fetchall()

    live_connections = _get_live_device_connections()
    return [
        _apply_live_device_state(serialize_device(row), live_connections)
        for row in rows
    ]


@app.get("/api/devices/{device_id}")
def get_device(device_id: str):
    with get_connection() as connection:
        row = connection.execute("""
            SELECT d.*,
                   u.name AS assigned_user_name,
                   u.username AS assigned_user_username,
                   u.email AS assigned_user_email,
                   dep.name AS department_name
            FROM devices AS d
            LEFT JOIN iam_users AS u ON u.id = d.assigned_user_id
            LEFT JOIN departments AS dep ON dep.id = d.department_id
            WHERE d.id = ?
        """, (device_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")

    return _apply_live_device_state(
        serialize_device(row), _get_live_device_connections()
    )



def validate_device_assignment(device):
    """Reject unknown user or department IDs instead of storing free text."""
    assigned_user_id = device.assigned_user_id or ""
    department_id = device.department_id or ""
    with get_connection() as connection:
        if assigned_user_id:
            user = connection.execute(
                "SELECT id FROM iam_users WHERE id = ?", (assigned_user_id,)
            ).fetchone()
            if user is None:
                raise HTTPException(status_code=422, detail="Assigned user does not exist in Cartman IAM.")
        if department_id:
            department = connection.execute(
                "SELECT id FROM departments WHERE id = ?", (department_id,)
            ).fetchone()
            if department is None:
                raise HTTPException(status_code=422, detail="Department does not exist in Cartman.")


@app.post("/api/devices", status_code=201)
def create_device(device: DeviceInput):
    validate_device_assignment(device)
    device_id = "device-" + uuid.uuid4().hex

    try:
        with get_connection() as connection:
            connection.execute("""
                INSERT INTO devices (
                    id, name, os, ip, status, tags,
                    public_ip, local_ip, username, model, manufacturer,
                    device_type, cpu, ram, disk, gpu,
                    display_name, assigned_user_id, department_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                device.display_name or "",
                device.assigned_user_id or "",
                device.department_id or "",
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
    validate_device_assignment(device)
    try:
        with get_connection() as connection:
            cursor = connection.execute("""
                UPDATE devices
                SET name = ?, os = ?,
                    display_name = COALESCE(?, display_name),
                    assigned_user_id = COALESCE(?, assigned_user_id),
                    department_id = COALESCE(?, department_id),
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
                device.display_name,
                device.assigned_user_id,
                device.department_id,
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

# CARTMAN_REAL_DEVICE_ASSIGNMENT_DEPARTMENTS_V1
def initialize_device_assignment_schema():
    """Add persistent display name, IAM assignment and department links."""
    with get_connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(devices)").fetchall()}
        additions = (
            ("display_name", "TEXT NOT NULL DEFAULT ''"),
            ("assigned_user_id", "TEXT NOT NULL DEFAULT ''"),
            ("department_id", "TEXT NOT NULL DEFAULT ''"),
        )
        for column, sql_type in additions:
            if column not in columns:
                connection.execute(f"ALTER TABLE devices ADD COLUMN {column} {sql_type}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_assigned_user_id ON devices(assigned_user_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_department_id ON devices(department_id)")


initialize_device_assignment_schema()


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
    schedule_input = payload.pop("scheduled_at", None)
    scheduled_at = None

    if schedule_input is not None:
        if not isinstance(schedule_input, str):
            raise HTTPException(status_code=422, detail="Scheduled time must be a date/time string.")
        try:
            parsed_schedule = _datetime.datetime.fromisoformat(
                schedule_input.replace("Z", "+00:00")
            )
            if parsed_schedule.tzinfo is None:
                parsed_schedule = parsed_schedule.astimezone()
            parsed_schedule = parsed_schedule.astimezone(_datetime.timezone.utc)
        except (ValueError, OverflowError):
            raise HTTPException(status_code=422, detail="Invalid scheduled date/time.")

        if parsed_schedule.timestamp() <= time.time():
            raise HTTPException(status_code=422, detail="Scheduled time must be in the future.")

        scheduled_at = parsed_schedule.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as connection:
        device = connection.execute(
            "SELECT id, name, os FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()

        if device is None:
            raise HTTPException(status_code=404, detail="Device not found.")

        if task.action == "package_deployment":
            if payload.get("confirmed") is not True:
                raise HTTPException(
                    status_code=422,
                    detail="Explicit confirmation is required for package deployment.",
                )
            software_id = payload.get("software_id")
            if not isinstance(software_id, str) or not software_id:
                raise HTTPException(
                    status_code=422,
                    detail="Choose a software catalog package.",
                )

            package = connection.execute(
                """
                SELECT id, name, version, status, install_command, target_os,
                       install_args, package_type, package_storage_key,
                       package_filename, package_size, package_sha256
                FROM software_catalog WHERE id = ?
                """,
                (software_id,),
            ).fetchone()

            if package is None or package["status"] != "Active":
                raise HTTPException(
                    status_code=404,
                    detail="Active software package not found.",
                )

            storage_key = package["package_storage_key"] or ""
            filename = package["package_filename"] or ""
            size = int(package["package_size"] or 0)
            package_hash = package["package_sha256"] or ""
            has_any_file_metadata = bool(
                storage_key or filename or size or package_hash
            )
            has_uploaded_file = bool(
                storage_key and filename and size > 0
                and len(package_hash) == 64
            )

            if has_any_file_metadata and not has_uploaded_file:
                raise HTTPException(
                    status_code=409,
                    detail="Uploaded package metadata is incomplete. Re-upload the installer.",
                )

            if has_uploaded_file:
                package_type = (package["package_type"] or "").strip().upper()
                type_info = SUPPORTED_PACKAGE_TYPES.get(package_type)
                stored_path = _package_storage_path(storage_key)

                if (
                    type_info is None
                    or Path(filename).suffix.lower() != type_info[0]
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Package type and installer filename do not match.",
                    )

                if not stored_path or not stored_path.is_file():
                    raise HTTPException(
                        status_code=409,
                        detail="Uploaded installer is missing from the private repository.",
                    )

                if stored_path.stat().st_size != size:
                    raise HTTPException(
                        status_code=409,
                        detail="Uploaded installer size no longer matches its metadata.",
                    )

                if (
                    package_type == "EXE"
                    and not (package["install_args"] or "").strip()
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Configure the vendor-documented silent install arguments for this EXE first.",
                    )

            elif not (package["install_command"] or "").strip():
                raise HTTPException(
                    status_code=409,
                    detail="Upload an installer file or configure an install command first.",
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


        if task.action == "remote_command":
            command = payload.get("command")
            if not isinstance(command, str) or not command.strip():
                raise HTTPException(
                    status_code=422,
                    detail="Enter a command before queueing the task.",
                )
            if len(command) > 6000:
                raise HTTPException(
                    status_code=422,
                    detail="Commands may contain at most 6000 characters.",
                )
            if payload.get("confirmed") is not True:
                raise HTTPException(
                    status_code=422,
                    detail="Explicit confirmation is required for a remote command.",
                )

            target_os = payload.get("target_os", "Any")
            if target_os not in {"Any", "Windows", "macOS", "Linux"}:
                raise HTTPException(
                    status_code=422,
                    detail="Target OS must be Any, Windows, macOS or Linux.",
                )

            target_family = normalize_os_family(target_os)
            device_family = normalize_os_family(device["os"])
            if target_family != "Any" and (
                target_family == "Unknown" or device_family != target_family
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"This command targets {target_os}, but the selected "
                        f"device runs {device['os']}. The task was not queued."
                    ),
                )

            payload["command"] = command
            payload["target_os"] = target_os

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

    # Allow offline queueing only for devices with a registered, non-revoked agent.
    with get_connection() as connection:
        registered_agent = connection.execute(
            """
            SELECT 1 FROM device_agent_credentials
            WHERE device_id = ? AND revoked = 0
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()

        approved_requests = connection.execute(
            """
            SELECT id FROM device_connection_requests
            WHERE device_id = ? AND status = 'Approved'
            """,
            (device_id,),
        ).fetchall()

    if registered_agent is None:
        raise HTTPException(
            status_code=409,
            detail="This device has no registered CartmanClient identity. Enroll and approve an agent first.",
        )

    approved_ids = {row["id"] for row in approved_requests}
    with _connection_clients_lock:
        approved_live = any(
            client.get("request_id") in approved_ids
            and client.get("connected") is True
            for client in _connection_clients.values()
        )
        execution_ready = any(
            client.get("request_id") in approved_ids
            and client.get("connected") is True
            and client.get("task_execution_enabled") is True
            for client in _connection_clients.values()
        )

    if approved_live and not execution_ready:
        raise HTTPException(
            status_code=409,
            detail="CartmanClient is connected, but task execution is disabled. Restart it with --enable-task-execution.",
        )

    # If there is no live session, persist the task and wait for reconnection.
    queued_while_offline = not execution_ready

    task_id = "task-" + uuid.uuid4().hex
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO device_tasks (id, device_id, action, payload, scheduled_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, device_id, task.action, json.dumps(payload), scheduled_at),
        )

    return {
        "id": task_id,
        "device_id": device_id,
        "action": task.action,
        "payload": payload,
        "status": "Queued",
        "message": (
            "Device is offline. Task is queued and will execute when its approved CartmanClient reconnects with task execution enabled."
            if queued_while_offline else
            "Task queued for the connected, approved CartmanClient."
        ),
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



@app.get("/api/deployment-jobs")
def list_deployment_jobs(request: Request):
    """Return real package-deployment task records without exposing install commands."""
    require_local_task_operator(request)

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                t.id,
                t.device_id,
                d.name AS device_name,
                d.os AS device_os,
                t.action,
                t.payload,
                t.status,
                t.result,
                t.created_at,
                t.started_at,
                t.finished_at,
                t.scheduled_at
            FROM device_tasks AS t
            LEFT JOIN devices AS d ON d.id = t.device_id
            WHERE t.action = 'package_deployment'
            ORDER BY t.created_at DESC, t.rowid DESC
            LIMIT 500
            """
        ).fetchall()

        package_rows = connection.execute(
            """
            SELECT id, name, version, target_os, status
            FROM software_catalog
            """
        ).fetchall()

    packages = {str(row["id"]): dict(row) for row in package_rows}
    output = []

    for row in rows:
        item = dict(row)

        try:
            payload = json.loads(item.pop("payload", None) or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except (TypeError, json.JSONDecodeError):
            payload = {}

        software_id = payload.get("software_id")
        package = packages.get(str(software_id)) if software_id is not None else None

        try:
            result = json.loads(item.get("result") or "null")
        except (TypeError, json.JSONDecodeError):
            result = item.get("result")

        item.update({
            "software_id": software_id,
            "software_name": package["name"] if package else "Package unavailable",
            "software_version": package["version"] if package else "Unknown",
            "software_target_os": package["target_os"] if package else "Unknown",
            "software_status": package["status"] if package else "Unknown",
            "result": result,
        })
        output.append(item)

    return output


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
    """Use the same live device state as the Devices API."""
    with get_connection() as connection:
        device_rows = connection.execute("""
            SELECT * FROM devices
            ORDER BY name COLLATE NOCASE
        """).fetchall()

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

    # Match /api/devices: an approved, connected CartmanClient session
    # determines whether a device is currently Online or Offline.
    live_connections = _get_live_device_connections()
    devices = [
        _apply_live_device_state(serialize_device(row), live_connections)
        for row in device_rows
    ]

    status_counts = {}
    for device in devices:
        status = device.get("status") or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "device_status_counts": status_counts,
        "total_devices": len(devices),
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


# CARTMAN_SERVICE_CHECK_DEFINITIONS_API_V1
# Persistent configuration only. Actual remote checks require the future CartmanClient collector.
import json as _cartman_scd_json
import uuid as _cartman_scd_uuid
from datetime import datetime as _cartman_scd_datetime, timezone as _cartman_scd_timezone

_CARTMAN_SCD_PLATFORMS = {"Windows"}
_CARTMAN_SCD_TYPES = {"windows_service", "http", "tcp", "dns_query"}
_CARTMAN_SCD_INTERVALS = {30, 60, 300, 900}


def _cartman_scd_ensure_schema(connection=None):
    close_after = connection is None
    conn = connection or get_connection()
    try:
        def create_table(table_name):
            # table_name is an internal constant at each call site below.
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    platform TEXT NOT NULL CHECK(platform IN ('Windows','Linux','Application')),
                    service_identifier TEXT NOT NULL,
                    check_type TEXT NOT NULL CHECK(check_type IN ('windows_service','systemd_service','http','tcp','dns_query')),
                    dns_server TEXT NOT NULL DEFAULT '',
                    dns_record_type TEXT NOT NULL DEFAULT 'A' CHECK(dns_record_type IN ('A','AAAA','CNAME','MX','SRV')),
                    dns_expected_answer TEXT NOT NULL DEFAULT '',
                    dns_timeout_seconds INTEGER NOT NULL DEFAULT 3 CHECK(dns_timeout_seconds IN (1,2,3,5,10)),
                    interval_seconds INTEGER NOT NULL DEFAULT 60 CHECK(interval_seconds IN (30,60,300,900)),
                    failure_threshold INTEGER NOT NULL DEFAULT 3 CHECK(failure_threshold BETWEEN 1 AND 10),
                    alert_on_failure INTEGER NOT NULL DEFAULT 1 CHECK(alert_on_failure IN (0,1)),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    notes TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

        create_table("service_check_definitions")
        schema_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='service_check_definitions'"
        ).fetchone()
        schema_sql = str(schema_row[0] or "").lower() if schema_row else ""
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(service_check_definitions)").fetchall()
        }
        dns_columns = {"dns_server", "dns_record_type", "dns_expected_answer", "dns_timeout_seconds"}

        # Existing SQLite CHECK constraints cannot be expanded with ALTER TABLE.
        # Rebuild once, copying every existing definition and adding DNS defaults.
        if "'dns_query'" not in schema_sql or not dns_columns.issubset(existing_columns):
            savepoint = "cartman_scd_dns_query_migration"
            conn.execute("SAVEPOINT " + savepoint)
            try:
                conn.execute("DROP TABLE IF EXISTS service_check_definitions__new")
                create_table("service_check_definitions__new")
                columns = [
                    "id", "device_id", "service_name", "platform", "service_identifier", "check_type",
                    "dns_server", "dns_record_type", "dns_expected_answer", "dns_timeout_seconds",
                    "interval_seconds", "failure_threshold", "alert_on_failure", "enabled", "notes",
                    "created_by", "created_at", "updated_at",
                ]
                defaults = {
                    "id": "''", "device_id": "''", "service_name": "''", "platform": "'Windows'",
                    "service_identifier": "''", "check_type": "'windows_service'", "dns_server": "''",
                    "dns_record_type": "'A'", "dns_expected_answer": "''", "dns_timeout_seconds": "3",
                    "interval_seconds": "60", "failure_threshold": "3", "alert_on_failure": "1",
                    "enabled": "1", "notes": "''", "created_by": "''",
                    "created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP",
                }
                select_exprs = [
                    ('"' + column + '"') if column in existing_columns else defaults[column]
                    for column in columns
                ]
                column_sql = ",".join('"' + column + '"' for column in columns)
                conn.execute(
                    "INSERT INTO service_check_definitions__new (" + column_sql + ") SELECT "
                    + ",".join(select_exprs) + " FROM service_check_definitions"
                )
                conn.execute("DROP TABLE service_check_definitions")
                conn.execute(
                    "ALTER TABLE service_check_definitions__new RENAME TO service_check_definitions"
                )
                conn.execute("RELEASE SAVEPOINT " + savepoint)
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT " + savepoint)
                conn.execute("RELEASE SAVEPOINT " + savepoint)
                raise

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_service_check_defs_device_enabled "
            "ON service_check_definitions(device_id, enabled, service_name COLLATE NOCASE)"
        )
        if connection is None:
            conn.commit()
    finally:
        if close_after:
            conn.close()


def _cartman_scd_current_user(request, write=False):
    raw = getattr(getattr(request, "state", None), "auth_user", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if isinstance(raw, dict):
        user = raw
    else:
        try:
            user = dict(raw)
        except Exception:
            user = {"username": getattr(raw, "username", ""), "role": getattr(raw, "role", "")}
    username = str(user.get("username") or user.get("email") or "").strip()
    role = str(user.get("role") or user.get("role_name") or "").strip().lower().replace("-", "_").replace(" ", "_")
    reader_roles = {"admin", "administrator", "network_admin", "support_agent", "read_only", "viewer", "analyst", "it_admin", "it_administrator"}
    writer_roles = {"admin", "administrator", "network_admin", "it_admin", "it_administrator"}
    allowed = writer_roles if write else reader_roles
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is unavailable.")
    if role not in allowed:
        raise HTTPException(status_code=403, detail="Your IAM role may not manage service-check definitions." if write else "Your IAM role may not view service-check definitions.")
    return user


def _cartman_scd_clean_text(value, label, maximum, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=label + " must be text.")
    value = value.strip()
    if required and not value:
        raise HTTPException(status_code=422, detail=label + " is required.")
    if len(value) > maximum or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise HTTPException(status_code=422, detail=label + " contains invalid characters or is too long.")
    return value


def _cartman_scd_normalize(payload, existing=None):
    payload = payload if isinstance(payload, dict) else {}
    base = dict(existing or {})

    def getv(key, default=""):
        return payload[key] if key in payload else base.get(key, default)

    service_name = _cartman_scd_clean_text(getv("service_name"), "Service name", 120, True)
    device_id = _cartman_scd_clean_text(str(getv("device_id") or ""), "Device", 120, True)
    platform = _cartman_scd_clean_text(getv("platform", "Windows"), "Platform", 32, True)
    identifier = _cartman_scd_clean_text(getv("service_identifier"), "Service identifier / DNS query name", 300, True)
    check_type = _cartman_scd_clean_text(getv("check_type", "windows_service"), "Check type", 32, True)
    notes = _cartman_scd_clean_text(getv("notes"), "Notes", 1000, False)
    dns_server = _cartman_scd_clean_text(
        getv("dns_server"), "DNS server address", 253, check_type == "dns_query"
    )
    dns_record_type = _cartman_scd_clean_text(getv("dns_record_type", "A"), "DNS record type", 8, True).upper()
    dns_expected_answer = _cartman_scd_clean_text(
        getv("dns_expected_answer"), "Expected DNS answer", 512, False
    )

    if platform not in _CARTMAN_SCD_PLATFORMS:
        raise HTTPException(status_code=422, detail="Unsupported platform.")
    if check_type not in _CARTMAN_SCD_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported check type.")
    if check_type == "dns_query":
        if platform != "Windows":
            raise HTTPException(status_code=422, detail="DNS query checks currently require the Windows platform.")
        if len(identifier) > 253 or any(ch.isspace() for ch in identifier):
            raise HTTPException(status_code=422, detail="DNS query name must be a valid name of at most 253 characters, without whitespace.")
        if any(ch.isspace() for ch in dns_server):
            raise HTTPException(status_code=422, detail="DNS server address must not contain whitespace.")
    if dns_record_type not in {"A", "AAAA", "CNAME", "MX", "SRV"}:
        raise HTTPException(status_code=422, detail="DNS record type must be A, AAAA, CNAME, MX or SRV.")

    try:
        interval = int(getv("interval_seconds", 60))
        threshold = int(getv("failure_threshold", 3))
        dns_timeout_seconds = int(getv("dns_timeout_seconds", 3))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Interval, failure threshold and DNS timeout must be integers.")

    if interval not in _CARTMAN_SCD_INTERVALS:
        raise HTTPException(status_code=422, detail="Interval must be 30, 60, 300 or 900 seconds.")
    if threshold < 1 or threshold > 10:
        raise HTTPException(status_code=422, detail="Failure threshold must be between 1 and 10.")
    if dns_timeout_seconds not in {1, 2, 3, 5, 10}:
        raise HTTPException(status_code=422, detail="DNS timeout must be 1, 2, 3, 5 or 10 seconds.")

    enabled = getv("enabled", True)
    alert_on_failure = getv("alert_on_failure", True)

    def bool_value(value, label):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int) and value in (0, 1):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0"}:
            return int(value.strip().lower() in {"true", "1"})
        raise HTTPException(status_code=422, detail=label + " must be a boolean.")

    return {
        "device_id": device_id, "service_name": service_name, "platform": platform,
        "service_identifier": identifier, "check_type": check_type,
        "dns_server": dns_server, "dns_record_type": dns_record_type,
        "dns_expected_answer": dns_expected_answer, "dns_timeout_seconds": dns_timeout_seconds,
        "interval_seconds": interval, "failure_threshold": threshold,
        "alert_on_failure": bool_value(alert_on_failure, "Alert on failure"),
        "enabled": bool_value(enabled, "Enabled"), "notes": notes,
    }


def _cartman_scd_public(row, connection):
    item = dict(row)
    device = connection.execute("SELECT name, os FROM devices WHERE CAST(id AS TEXT)=? LIMIT 1", (str(item.get("device_id") or ""),)).fetchone()
    item["device_name"] = str(device["name"]) if device else str(item.get("device_id") or "Unknown device")
    item["device_os"] = str(device["os"]) if device else "Unknown OS"
    item["alert_on_failure"] = bool(item.get("alert_on_failure"))
    item["enabled"] = bool(item.get("enabled"))
    item["collector_status"] = "Configuration only; collector required"
    return item


def _cartman_scd_validate_windows_server_device(connection, values):
    device = connection.execute(
        "SELECT name, os, tags FROM devices WHERE CAST(id AS TEXT)=? LIMIT 1",
        (str(values.get("device_id") or ""),),
    ).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail="Selected device was not found.")

    operating_system = str(device["os"] or "").strip().lower()
    if "windows" not in operating_system:
        raise HTTPException(status_code=422, detail="This Cartman build supports Windows Server devices only.")

    is_server = "server" in operating_system
    if not is_server:
        raw_tags = device["tags"] if "tags" in device.keys() else "[]"
        try:
            tags = _cartman_scd_json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
        except (TypeError, ValueError):
            tags = [part.strip() for part in str(raw_tags or "").replace(";", ",").split(",")]
        if not isinstance(tags, (list, tuple, set)):
            tags = [tags]
        for tag in tags:
            tag_name = tag.get("name", tag.get("label", tag.get("value", ""))) if isinstance(tag, dict) else tag
            if str(tag_name or "").strip().lower() in {"server", "windows server"}:
                is_server = True
                break

    if not is_server:
        raise HTTPException(
            status_code=422,
            detail="Select a Windows Server device. Its OS must identify Windows Server or it must have the Server tag.",
        )


def _cartman_scd_stamp():
    return _cartman_scd_datetime.now(_cartman_scd_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# CARTMAN_SERVICE_CHECK_AUDIT_API_V1
_CARTMAN_SCD_AUDIT_FIELDS = (
    "service_name", "device_id", "platform", "service_identifier", "check_type",
    "dns_server", "dns_record_type", "dns_expected_answer", "dns_timeout_seconds",
    "interval_seconds", "failure_threshold", "alert_on_failure", "enabled", "notes",
)


def _cartman_scd_ensure_audit_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS iam_audit_events (
            id TEXT PRIMARY KEY,
            actor TEXT NOT NULL DEFAULT 'Unattributed',
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_iam_audit_time ON iam_audit_events(occurred_at DESC)"
    )


def _cartman_scd_audit_snapshot(connection, row):
    if row is None:
        return None
    source = dict(row)
    snapshot = {key: source.get(key) for key in _CARTMAN_SCD_AUDIT_FIELDS}
    snapshot["id"] = str(source.get("id") or "")
    device = connection.execute(
        "SELECT name, os FROM devices WHERE CAST(id AS TEXT)=? LIMIT 1",
        (str(source.get("device_id") or ""),),
    ).fetchone()
    snapshot["device_name"] = str(device["name"]) if device else str(source.get("device_id") or "Unknown device")
    snapshot["device_os"] = str(device["os"]) if device else "Unknown OS"
    snapshot["alert_on_failure"] = bool(snapshot.get("alert_on_failure"))
    snapshot["enabled"] = bool(snapshot.get("enabled"))
    return snapshot


def _cartman_scd_write_audit(connection, user, action, before_row=None, after_row=None):
    _cartman_scd_ensure_audit_schema(connection)
    before = _cartman_scd_audit_snapshot(connection, before_row)
    after = _cartman_scd_audit_snapshot(connection, after_row)
    target = after or before or {}
    changed_fields = []
    if before is None and after is not None:
        changed_fields = list(_CARTMAN_SCD_AUDIT_FIELDS)
    elif after is None and before is not None:
        changed_fields = list(_CARTMAN_SCD_AUDIT_FIELDS)
    elif before is not None and after is not None:
        changed_fields = [
            key for key in _CARTMAN_SCD_AUDIT_FIELDS
            if before.get(key) != after.get(key)
        ]
    actor = str((user or {}).get("username") or (user or {}).get("email") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated username is unavailable for audit logging.")
    details = {
        "schema_version": 1,
        "service_name": target.get("service_name", ""),
        "device_id": target.get("device_id", ""),
        "device_name": target.get("device_name", ""),
        "platform": target.get("platform", ""),
        "check_type": target.get("check_type", ""),
        "service_identifier": target.get("service_identifier", ""),
        "changed_fields": changed_fields,
        "before": before,
        "after": after,
    }
    connection.execute("""
        INSERT INTO iam_audit_events
            (id, actor, action, resource_type, resource_id, details_json)
        VALUES (?, ?, ?, 'service_check_definition', ?, ?)
    """, (
        str(_cartman_scd_uuid.uuid4()), actor, str(action),
        str(target.get("id") or ""),
        _cartman_scd_json.dumps(details, ensure_ascii=False, separators=(",", ":")),
    ))


def _cartman_scd_audit_date(value, label):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        _cartman_scd_datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=label + " must use YYYY-MM-DD format.")
    return value



@app.get("/api/monitoring/service-check-definitions")
async def cartman_service_check_definitions_list(request: Request, limit: int = 500):
    _cartman_scd_current_user(request, write=False)
    limit = max(1, min(int(limit or 500), 1000))
    with get_connection() as connection:
        _cartman_scd_ensure_schema(connection)
        rows = connection.execute("""
            SELECT * FROM service_check_definitions
            ORDER BY enabled DESC, updated_at DESC, service_name COLLATE NOCASE
            LIMIT ?
        """, (limit,)).fetchall()
        return {"items": [_cartman_scd_public(row, connection) for row in rows], "source": "database", "collector_connected": False}


@app.post("/api/monitoring/service-check-definitions", status_code=201)
async def cartman_service_check_definitions_create(request: Request):
    user = _cartman_scd_current_user(request, write=True)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="A JSON request body is required.")
    values = _cartman_scd_normalize(payload)
    with get_connection() as connection:
        _cartman_scd_ensure_schema(connection)
        device = connection.execute("SELECT id FROM devices WHERE CAST(id AS TEXT)=? LIMIT 1", (values["device_id"],)).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Selected device was not found.")
        _cartman_scd_validate_windows_server_device(connection, values)
        definition_id = str(_cartman_scd_uuid.uuid4())
        now = _cartman_scd_stamp()
        connection.execute("""
            INSERT INTO service_check_definitions
            (id,device_id,service_name,platform,service_identifier,check_type,
             dns_server,dns_record_type,dns_expected_answer,dns_timeout_seconds,
             interval_seconds,failure_threshold,alert_on_failure,enabled,notes,
             created_by,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            definition_id, values["device_id"], values["service_name"],
            values["platform"], values["service_identifier"], values["check_type"],
            values["dns_server"], values["dns_record_type"], values["dns_expected_answer"],
            values["dns_timeout_seconds"], values["interval_seconds"], values["failure_threshold"],
            values["alert_on_failure"], values["enabled"], values["notes"],
            str(user.get("username") or user.get("email") or ""), now, now
        ))
        row = connection.execute("SELECT * FROM service_check_definitions WHERE id=?", (definition_id,)).fetchone()
        _cartman_scd_write_audit(connection, user, "created", None, row)
        return {"item": _cartman_scd_public(row, connection), "source": "database", "collector_connected": False}


@app.put("/api/monitoring/service-check-definitions/{definition_id}")
async def cartman_service_check_definitions_update(definition_id: str, request: Request):
    user = _cartman_scd_current_user(request, write=True)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="A JSON request body is required.")
    with get_connection() as connection:
        _cartman_scd_ensure_schema(connection)
        row = connection.execute("SELECT * FROM service_check_definitions WHERE id=?", (definition_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Service-check definition not found.")
        values = _cartman_scd_normalize(payload, dict(row))
        _cartman_scd_validate_windows_server_device(connection, values)
        if "enabled" not in payload:
            values["enabled"] = int(row["enabled"])
        connection.execute("""
            UPDATE service_check_definitions
            SET device_id=?,service_name=?,platform=?,service_identifier=?,check_type=?,
                dns_server=?,dns_record_type=?,dns_expected_answer=?,dns_timeout_seconds=?,
                interval_seconds=?,failure_threshold=?,alert_on_failure=?,enabled=?,notes=?,updated_at=?
            WHERE id=?
        """, (
            values["device_id"], values["service_name"], values["platform"],
            values["service_identifier"], values["check_type"], values["dns_server"],
            values["dns_record_type"], values["dns_expected_answer"], values["dns_timeout_seconds"],
            values["interval_seconds"], values["failure_threshold"], values["alert_on_failure"],
            values["enabled"], values["notes"], _cartman_scd_stamp(), definition_id
        ))
        updated = connection.execute("SELECT * FROM service_check_definitions WHERE id=?", (definition_id,)).fetchone()
        before_snapshot = _cartman_scd_audit_snapshot(connection, row)
        after_snapshot = _cartman_scd_audit_snapshot(connection, updated)
        changed_fields = [key for key in _CARTMAN_SCD_AUDIT_FIELDS if before_snapshot.get(key) != after_snapshot.get(key)]
        audit_action = "updated"
        if changed_fields == ["enabled"]:
            audit_action = "enabled" if after_snapshot["enabled"] else "disabled"
        _cartman_scd_write_audit(connection, user, audit_action, row, updated)
        return {"item": _cartman_scd_public(updated, connection), "source": "database", "collector_connected": False, "updated_by": str(user.get("username") or "")}


@app.delete("/api/monitoring/service-check-definitions/{definition_id}")
async def cartman_service_check_definitions_delete(definition_id: str, request: Request):
    user = _cartman_scd_current_user(request, write=True)
    with get_connection() as connection:
        _cartman_scd_ensure_schema(connection)
        existing = connection.execute("SELECT * FROM service_check_definitions WHERE id=?", (definition_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Service-check definition not found.")
        cursor = connection.execute("DELETE FROM service_check_definitions WHERE id=?", (definition_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service-check definition not found.")
        _cartman_scd_write_audit(connection, user, "deleted", existing, None)
        return {"deleted": True, "id": definition_id}


@app.get("/api/monitoring/service-check-audit")
def cartman_service_check_audit_list(
    request: Request,
    limit: int = 500,
    offset: int = 0,
    actor: str = "",
    action: str = "",
    device_id: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    sort: str = "newest",
):
    _cartman_scd_current_user(request, write=False)
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, min(int(offset or 0), 10000))
    date_from = _cartman_scd_audit_date(date_from, "Start date")
    date_to = _cartman_scd_audit_date(date_to, "End date")
    allowed_actions = {"created", "updated", "enabled", "disabled", "deleted"}
    action = str(action or "").strip().lower()
    if action and action not in allowed_actions:
        raise HTTPException(status_code=422, detail="Unsupported service audit action.")
    where = ["resource_type = 'service_check_definition'"]
    params = []
    if actor.strip():
        where.append("actor LIKE ?")
        params.append("%" + actor.strip() + "%")
    if action:
        where.append("action = ?")
        params.append(action)
    if device_id.strip():
        where.append("details_json LIKE ?")
        params.append('%"device_id":"' + device_id.strip().replace("%", "\%").replace("_", "\_") + '"%')
    if date_from:
        where.append("date(occurred_at) >= date(?)")
        params.append(date_from)
    if date_to:
        where.append("date(occurred_at) <= date(?)")
        params.append(date_to)
    if q.strip():
        pattern = "%" + q.strip() + "%"
        where.append("(actor LIKE ? OR action LIKE ? OR resource_id LIKE ? OR details_json LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    order = "ASC" if str(sort).lower() == "oldest" else "DESC"
    sql_where = " AND ".join(where)
    with get_connection() as connection:
        _cartman_scd_ensure_audit_schema(connection)
        total = connection.execute(
            "SELECT COUNT(*) FROM iam_audit_events WHERE " + sql_where,
            tuple(params),
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT rowid AS sequence, id, actor, action, resource_type, resource_id, details_json, occurred_at "
            "FROM iam_audit_events WHERE " + sql_where +
            " ORDER BY occurred_at " + order + ", sequence " + order + " LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = _cartman_scd_json.loads(item.pop("details_json") or "{}")
        except (TypeError, ValueError):
            item["details"] = {}
            item.pop("details_json", None)
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset, "source": "iam_audit_events"}


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



# CARTMAN_IAM_DIRECTORY_API_V1
# Dedicated IAM directory records. These are intentionally separate from
# Inventory people and endpoint/device groups.
def initialize_iam_directory_database():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS iam_users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                username TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Invited'
                    CHECK (status IN ('Active', 'Invited', 'Suspended')),
                mfa_status TEXT NOT NULL DEFAULT 'Not configured',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_iam_users_username
            ON iam_users(username COLLATE NOCASE)
            WHERE TRIM(username) <> '';

            CREATE TABLE IF NOT EXISTS iam_groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                scope TEXT NOT NULL DEFAULT 'General',
                description TEXT NOT NULL DEFAULT '',
                department_id TEXT REFERENCES departments(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Active'
                    CHECK (status IN ('Active', 'Review', 'Disabled')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS iam_group_members (
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id),
                FOREIGN KEY (group_id) REFERENCES iam_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES iam_users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_iam_group_members_user
            ON iam_group_members(user_id);

            CREATE TABLE IF NOT EXISTS iam_audit_events (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL DEFAULT 'Unattributed',
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_iam_audit_time
            ON iam_audit_events(occurred_at DESC);
        """)
        # Additive migration. Existing groups and memberships are preserved.
        iam_group_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(iam_groups)").fetchall()
        }
        if "department_id" not in iam_group_columns:
            connection.execute(
                "ALTER TABLE iam_groups ADD COLUMN department_id TEXT "
                "REFERENCES departments(id) ON DELETE SET NULL"
            )

        iam_user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(iam_users)").fetchall()
        }
        if "support_level" not in iam_user_columns:
            connection.execute("ALTER TABLE iam_users ADD COLUMN support_level TEXT NOT NULL DEFAULT 'None'")
        if "support_online" not in iam_user_columns:
            connection.execute("ALTER TABLE iam_users ADD COLUMN support_online INTEGER NOT NULL DEFAULT 0 CHECK (support_online IN (0, 1))")

def _iam_audit(connection, action, resource_type, resource_id, details=None):
    connection.execute("""
        INSERT INTO iam_audit_events
            (id, actor, action, resource_type, resource_id, details_json)
        VALUES (?, 'Unattributed (no authenticated session)', ?, ?, ?, ?)
    """, (
        str(uuid.uuid4()),
        action,
        resource_type,
        str(resource_id or ""),
        json.dumps(details or {}, ensure_ascii=False),
    ))


def _iam_user_dict(connection, row):
    item = dict(row)
    memberships = connection.execute("""
        SELECT g.id, g.name
        FROM iam_group_members m
        JOIN iam_groups g ON g.id = m.group_id
        WHERE m.user_id = ?
        ORDER BY g.name COLLATE NOCASE
    """, (item["id"],)).fetchall()

    item["groups"] = [dict(group) for group in memberships]
    item["groupNames"] = [group["name"] for group in memberships]
    item["group"] = ", ".join(item["groupNames"]) or "Unassigned"
    item["role"] = "Unassigned"
    item["mfa"] = item.get("mfa_status") or "Not configured"
    return item


def _iam_group_dict(connection, row):
    item = dict(row)
    members = connection.execute("""
        SELECT u.id, u.name, u.email
        FROM iam_group_members m
        JOIN iam_users u ON u.id = m.user_id
        WHERE m.group_id = ?
        ORDER BY u.name COLLATE NOCASE
    """, (item["id"],)).fetchall()

    item["memberIds"] = [member["id"] for member in members]
    item["memberNames"] = [member["name"] for member in members]
    item["members"] = len(members)

    department_id = item.get("department_id")
    department = None
    if department_id:
        department = connection.execute(
            "SELECT id, name FROM departments WHERE id=?",
            (department_id,)
        ).fetchone()

    item["department_name"] = department["name"] if department else ""
    return item


def _iam_directory_admin(request):
    actor = getattr(request.state, "auth_user", None)
    if not actor:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if actor.get("_cartman_api_key") or str(actor.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Cartman administrator access required.")
    return actor


def _iam_clean_user(payload, current=None):
    current = current or {}

    name = str(payload.get("name", current.get("name", "")) or "").strip()
    email = str(payload.get("email", current.get("email", "")) or "").strip()
    username = str(payload.get("username", current.get("username", "")) or "").strip()
    department = str(payload.get("department", current.get("department", "")) or "").strip()
    status = str(payload.get("status", current.get("status", "Invited")) or "").strip()

    if not name or len(name) > 160:
        raise HTTPException(
            status_code=422,
            detail="Name is required and must be at most 160 characters."
        )
    if (
        not email or len(email) > 254 or "@" not in email
        or email.startswith("@") or email.endswith("@")
        or any(character.isspace() for character in email)
    ):
        raise HTTPException(status_code=422, detail="A valid email address is required.")
    if len(username) > 120 or len(department) > 120:
        raise HTTPException(status_code=422, detail="Username or department is too long.")
    if status not in {"Active", "Invited", "Suspended"}:
        raise HTTPException(
            status_code=422,
            detail="Status must be Active, Invited, or Suspended."
        )

    return {
        "name": name,
        "email": email,
        "username": username,
        "department": department,
        "status": status,
    }


def _iam_clean_group(payload, current=None):
    current = current or {}

    name = str(payload.get("name", current.get("name", "")) or "").strip()
    scope = str(payload.get("scope", current.get("scope", "General")) or "").strip()
    description = str(
        payload.get("description", current.get("description", "")) or ""
    ).strip()
    status = str(payload.get("status", current.get("status", "Active")) or "").strip()
    department_id = str(payload.get("department_id", current.get("department_id")) or "").strip() or None

    if not name or len(name) > 160:
        raise HTTPException(
            status_code=422,
            detail="Group name is required and must be at most 160 characters."
        )
    if len(scope) > 120 or len(description) > 1000:
        raise HTTPException(status_code=422, detail="A group field is too long.")
    if status not in {"Active", "Review", "Disabled"}:
        raise HTTPException(
            status_code=422,
            detail="Group status must be Active, Review, or Disabled."
        )

    return {
        "name": name,
        "scope": scope or "General",
        "description": description,
        "status": status,
        "department_id": department_id,
    }


initialize_iam_directory_database()



    # CARTMAN_IAM_SUPPORT_ROUTING_ENDPOINTS_V1

def _support_routing_admin(request: Request):
    actor = getattr(request.state, "auth_user", None)
    if not actor:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if actor.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only a Cartman administrator can configure support routing.",
        )
    return actor


def _iam_support_item(connection, row):
    item = dict(row)
    username = str(item.get("username") or "").strip()
    account = None

    if username:
        account = connection.execute(
            """
            SELECT id, username, role, is_active
            FROM auth_accounts
            WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()

    item["account_linked"] = bool(account and account["is_active"])
    item["login_role"] = account["role"] if account else None
    item["support_level"] = str(item.get("support_level") or "None")
    item["support_online"] = bool(item.get("support_online"))
    return item


def _support_routing_audit(connection, actor, action, user_id, details):
    connection.execute(
        """
        INSERT INTO iam_audit_events
            (id, actor, action, resource_type, resource_id, details_json)
        VALUES (?, ?, ?, 'iam_user', ?, ?)
        """,
        (
            str(uuid.uuid4()),
            actor.get("username") or "Cartman Administrator",
            action,
            str(user_id),
            json.dumps(details, ensure_ascii=False),
        ),
    )


@app.get("/api/iam/support-routing")
def list_iam_support_routing(request: Request):
    _support_routing_admin(request)

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM iam_users ORDER BY name COLLATE NOCASE"
        ).fetchall()
        items = [_iam_support_item(connection, row) for row in rows]

    eligible_online = [
        item for item in items
        if item["status"] == "Active"
        and item["account_linked"]
        and item["support_level"] in {"L1", "L2", "L3"}
        and item["support_online"]
    ]

    return {
        "items": items,
        "summary": {
            "total_users": len(items),
            "online_agents": len(eligible_online),
            "l1_online": sum(
                item["support_level"] == "L1" for item in eligible_online
            ),
            "l2_l3_online": sum(
                item["support_level"] in {"L2", "L3"}
                for item in eligible_online
            ),
        },
    }


@app.put("/api/iam/users/{user_id}/support-routing")
def update_iam_user_support_routing(
    user_id: str,
    payload: dict,
    request: Request,
):
    actor = _support_routing_admin(request)
    level = payload.get("support_level")

    if level not in {"None", "L1", "L2", "L3"}:
        raise HTTPException(
            status_code=422,
            detail="support_level must be None, L1, L2, or L3.",
        )

    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM iam_users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="IAM user not found.")

        # A user removed from support must not remain marked Online.
        if level == "None":
            connection.execute(
                """
                UPDATE iam_users
                SET support_level = 'None',
                    support_online = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (user_id,),
            )
        else:
            connection.execute(
                """
                UPDATE iam_users
                SET support_level = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (level, user_id),
            )

        _support_routing_audit(
            connection,
            actor,
            "iam.support_routing.updated",
            user_id,
            {"support_level": level},
        )

        updated = connection.execute(
            "SELECT * FROM iam_users WHERE id = ?",
            (user_id,),
        ).fetchone()

        return _iam_support_item(connection, updated)


@app.get("/api/iam/me/support-availability")
def get_my_support_availability(request: Request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    username = str(user.get("username") or "").strip()

    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM iam_users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="No IAM user record matches this Cartman login username.",
            )

        account = connection.execute(
            """
            SELECT id, username, is_active
            FROM auth_accounts
            WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()

        linked = bool(
            account
            and account["is_active"]
            and account["id"] == user.get("id")
            and row["username"].strip().casefold() == username.casefold()
        )

        level = str(row["support_level"] or "None")
        eligible = bool(
            linked
            and row["status"] == "Active"
            and level in {"L1", "L2", "L3"}
        )

        return {
            "username": username,
            "display_name": user.get("display_name") or row["name"],
            "account_linked": linked,
            "status": row["status"],
            "support_level": level,
            "eligible": eligible,
            "support_online": bool(row["support_online"]),
        }


@app.put("/api/iam/me/support-availability")
def update_my_support_availability(payload: dict, request: Request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    requested = payload.get("support_online")
    if not isinstance(requested, bool):
        raise HTTPException(
            status_code=422,
            detail="support_online must be true or false.",
        )

    username = str(user.get("username") or "").strip()

    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM iam_users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="No IAM user record matches this Cartman login username.",
            )

        account = connection.execute(
            """
            SELECT id, username, is_active
            FROM auth_accounts
            WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()

        linked = bool(
            account
            and account["is_active"]
            and account["id"] == user.get("id")
            and row["username"].strip().casefold() == username.casefold()
        )
        level = str(row["support_level"] or "None")

        if not linked:
            raise HTTPException(
                status_code=409,
                detail="This login is not linked to the matching active IAM user.",
            )
        if row["status"] != "Active":
            raise HTTPException(
                status_code=409,
                detail="The IAM account must be Active to receive support tickets.",
            )
        if level not in {"L1", "L2", "L3"}:
            raise HTTPException(
                status_code=409,
                detail="An administrator must assign an L1, L2, or L3 support tier first.",
            )

        connection.execute(
            """
            UPDATE iam_users
            SET support_online = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(requested), row["id"]),
        )

        _support_routing_audit(
            connection,
            user,
            "iam.support_availability.changed",
            row["id"],
            {"support_online": requested, "support_level": level},
        )

        # # CARTMAN_TICKET_QUEUE_ASSIGN_ON_ONLINE_V1
        # When a support agent comes online, assign eligible queued tickets.
        if requested:
            _ticket_assign_waiting_queue(connection, level)

        return {
            "username": username,
            "display_name": user.get("display_name") or row["name"],
            "account_linked": True,
            "status": row["status"],
            "support_level": level,
            "eligible": True,
            "support_online": requested,
        }


@app.get("/api/iam/users")
def list_iam_users():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT * FROM iam_users ORDER BY name COLLATE NOCASE
        """).fetchall()
        return [_iam_user_dict(connection, row) for row in rows]


@app.get("/api/iam/users/{user_id}")
def get_iam_user(user_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM iam_users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="IAM user not found.")
        return _iam_user_dict(connection, row)


@app.post("/api/iam/users", status_code=201)
def create_iam_user(payload: dict, request: Request):
    actor = getattr(request.state, "auth_user", None)
    if not actor or actor.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only a Cartman administrator can create IAM users.",
        )

    clean = _iam_clean_user(payload)
    username = clean["username"].strip()

    if not re.fullmatch(r"[A-Za-z0-9._@+-]{3,80}", username):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3-80 valid login characters.",
        )

    password = payload.get("password", "")
    password_confirm = payload.get("password_confirm", "")
    force_value = payload.get("force_password_change", False)

    if not isinstance(force_value, bool):
        raise HTTPException(
            status_code=422,
            detail="force_password_change must be true or false.",
        )

    # Passwords are optional only when linking an existing Cartman login.
    if password and not isinstance(password, str):
        raise HTTPException(status_code=422, detail="Invalid password.")
    if password_confirm and not isinstance(password_confirm, str):
        raise HTTPException(status_code=422, detail="Invalid password confirmation.")

    user_id = str(uuid.uuid4())
    actor_name = actor.get("username") or "Cartman Administrator"
    account_active = 1 if clean["status"] == "Active" else 0

    try:
        with get_connection() as connection:
            # Insert the IAM record first; any later error rolls back both records.
            connection.execute("""
                INSERT INTO iam_users
                    (id, name, email, username, department, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                clean["name"],
                clean["email"],
                username,
                clean["department"],
                clean["status"],
            ))

            existing_account = connection.execute(
                "SELECT id, role, must_change_password "
                "FROM auth_accounts WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()

            if existing_account:
                # Link the existing login without silently resetting its password.
                if password or password_confirm:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "A Cartman login already uses this username. "
                            "Clear both password fields to link it without "
                            "changing its credentials."
                        ),
                    )

                login_id = existing_account["id"]
                must_change = (
                    1 if force_value
                    else int(existing_account["must_change_password"])
                )

                connection.execute("""
                    UPDATE auth_accounts
                    SET display_name = ?,
                        is_active = ?,
                        must_change_password = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    clean["name"], account_active, must_change, login_id,
                ))

                login_action = "linked_existing"
            else:
                if (
                    not isinstance(password, str)
                    or not 14 <= len(password) <= 128
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "For a new login account, password must be "
                            "14-128 characters."
                        ),
                    )

                if password != password_confirm:
                    raise HTTPException(
                        status_code=422,
                        detail="The password fields do not match.",
                    )

                login_id = str(uuid.uuid4())
                password_hash = _auth_security._password_hash(password)

                # Least privilege: new login accounts begin as read_only.
                # Existing account roles are preserved when linking.
                connection.execute("""
                    INSERT INTO auth_accounts
                        (id, username, display_name, password_hash,
                         role, is_active, must_change_password)
                    VALUES (?, ?, ?, ?, 'read_only', ?, ?)
                """, (
                    login_id,
                    username,
                    clean["name"],
                    password_hash,
                    account_active,
                    int(force_value),
                ))

                login_action = "created"

            _iam_audit(connection, "iam.user.created", "user", user_id, {
                "name": clean["name"],
                "email": clean["email"],
                "status": clean["status"],
                "login_action": login_action,
            })

            _auth_security._write_audit(
                connection,
                actor_name,
                "auth.account.provisioned_via_iam",
                "auth_account",
                login_id,
                {
                    "login_action": login_action,
                    "force_password_change": bool(force_value),
                },
            )

            row = connection.execute(
                "SELECT * FROM iam_users WHERE id = ?", (user_id,)
            ).fetchone()
            result = _iam_user_dict(connection, row)
            result["login_account_action"] = login_action
            return result

    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A user with this email or username already exists.",
        ) from exc


@app.put("/api/iam/users/{user_id}")
def update_iam_user(user_id: str, payload: dict, request: Request):
    _iam_directory_admin(request)
    with get_connection() as connection:
        current = connection.execute(
            "SELECT * FROM iam_users WHERE id = ?", (user_id,)
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="IAM user not found.")

        clean = _iam_clean_user(payload, dict(current))

        try:
            connection.execute("""
                UPDATE iam_users
                SET name = ?, email = ?, username = ?, department = ?,
                    status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                clean["name"], clean["email"], clean["username"],
                clean["department"], clean["status"], user_id
            ))

            # Keep the corresponding login's identity and enabled state in sync.
            linked = connection.execute(
                "SELECT id FROM auth_accounts "
                "WHERE username = ? COLLATE NOCASE",
                (current["username"],),
            ).fetchone()

            if linked:
                if not re.fullmatch(
                    r"[A-Za-z0-9._@+-]{3,80}", clean["username"]
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "A linked login requires a valid 3-80 character "
                            "username."
                        ),
                    )

                connection.execute("""
                    UPDATE auth_accounts
                    SET username = ?,
                        display_name = ?,
                        is_active = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    clean["username"],
                    clean["name"],
                    1 if clean["status"] == "Active" else 0,
                    linked["id"],
                ))

        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="A user with this email or username already exists."
            ) from exc

        _iam_audit(connection, "iam.user.updated", "user", user_id, {
            "name": clean["name"], "status": clean["status"]
        })

        row = connection.execute(
            "SELECT * FROM iam_users WHERE id = ?", (user_id,)
        ).fetchone()
        return _iam_user_dict(connection, row)


@app.delete("/api/iam/users/{user_id}")
def delete_iam_user(user_id: str, request: Request):
    _iam_directory_admin(request)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, name, email, username FROM iam_users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="IAM user not found.")

        _iam_audit(connection, "iam.user.deleted", "user", user_id, {
            "name": row["name"], "email": row["email"]
        })

        # Prevent a deleted IAM identity from leaving an active orphaned login.
        linked = connection.execute(
            "SELECT id FROM auth_accounts WHERE username = ? COLLATE NOCASE",
            (row["username"],),
        ).fetchone()
        if linked:
            connection.execute(
                "UPDATE auth_accounts SET is_active = 0, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (linked["id"],),
            )
            connection.execute(
                "UPDATE auth_sessions SET revoked = 1 WHERE account_id = ?",
                (linked["id"],),
            )

        connection.execute("DELETE FROM iam_users WHERE id = ?", (user_id,))

    return {"deleted": True, "id": user_id}


@app.get("/api/iam/groups")
def list_iam_groups():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT * FROM iam_groups ORDER BY name COLLATE NOCASE
        """).fetchall()
        return [_iam_group_dict(connection, row) for row in rows]


@app.get("/api/iam/groups/{group_id}")
def get_iam_group(group_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM iam_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="IAM group not found.")
        return _iam_group_dict(connection, row)


@app.post("/api/iam/groups", status_code=201)
def create_iam_group(payload: dict, request: Request):
    _iam_directory_admin(request)
    clean = _iam_clean_group(payload)
    group_id = str(uuid.uuid4())

    try:
        with get_connection() as connection:
            if clean["department_id"] and not connection.execute(
                "SELECT 1 FROM departments WHERE id=?",
                (clean["department_id"],)
            ).fetchone():
                raise HTTPException(status_code=422, detail="Selected department does not exist.")

            connection.execute("""
                INSERT INTO iam_groups
                    (id, name, scope, description, department_id, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                group_id, clean["name"], clean["scope"],
                clean["description"], clean["department_id"], clean["status"]
            ))
            _iam_audit(connection, "iam.group.created", "group", group_id, {
                "name": clean["name"], "scope": clean["scope"]
            })
            row = connection.execute(
                "SELECT * FROM iam_groups WHERE id = ?", (group_id,)
            ).fetchone()
            return _iam_group_dict(connection, row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="A group with this name already exists."
        ) from exc


@app.put("/api/iam/groups/{group_id}")
def update_iam_group(group_id: str, payload: dict, request: Request):
    _iam_directory_admin(request)
    with get_connection() as connection:
        current = connection.execute(
            "SELECT * FROM iam_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="IAM group not found.")

        clean = _iam_clean_group(payload, dict(current))

        if clean["department_id"] and not connection.execute(
            "SELECT 1 FROM departments WHERE id=?",
            (clean["department_id"],)
        ).fetchone():
            raise HTTPException(status_code=422, detail="Selected department does not exist.")

        try:
            connection.execute("""
                UPDATE iam_groups
                SET name = ?, scope = ?, description = ?, department_id = ?,
                    status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                clean["name"], clean["scope"], clean["description"],
                clean["department_id"], clean["status"], group_id
            ))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail="A group with this name already exists."
            ) from exc

        _iam_audit(connection, "iam.group.updated", "group", group_id, {
            "name": clean["name"], "scope": clean["scope"],
            "status": clean["status"]
        })
        row = connection.execute(
            "SELECT * FROM iam_groups WHERE id = ?", (group_id,)
        ).fetchone()
        return _iam_group_dict(connection, row)


@app.delete("/api/iam/groups/{group_id}")
def delete_iam_group(group_id: str, request: Request):
    _iam_directory_admin(request)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, name FROM iam_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="IAM group not found.")

        members = connection.execute("""
            SELECT COUNT(*) AS total FROM iam_group_members WHERE group_id = ?
        """, (group_id,)).fetchone()["total"]
        if members:
            raise HTTPException(
                status_code=409,
                detail=f"Remove the {members} member(s) before deleting this group."
            )

        # Group roles must be removed before the group itself can be deleted.
        role_table = connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'cartman_rbac_group_roles'
        """).fetchone()

        if role_table:
            assigned_roles = connection.execute(
                "SELECT COUNT(*) FROM cartman_rbac_group_roles WHERE group_id=?",
                (group_id,)
            ).fetchone()[0]

            if assigned_roles:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Remove the {assigned_roles} RBAC role assignment(s) "
                        "before deleting this group."
                    )
                )

        _iam_audit(connection, "iam.group.deleted", "group", group_id, {
            "name": row["name"]
        })
        connection.execute("DELETE FROM iam_groups WHERE id = ?", (group_id,))

    return {"deleted": True, "id": group_id}


@app.put("/api/iam/groups/{group_id}/members")
def set_iam_group_members(group_id: str, payload: dict, request: Request):
    _iam_directory_admin(request)
    member_ids = payload.get("userIds", payload.get("user_ids", []))
    if not isinstance(member_ids, list) or len(member_ids) > 1000:
        raise HTTPException(
            status_code=422,
            detail="userIds must be a list containing at most 1000 users."
        )
    if any(not isinstance(item, str) for item in member_ids):
        raise HTTPException(status_code=422, detail="Every member ID must be a string.")

    member_ids = list(dict.fromkeys(item.strip() for item in member_ids if item.strip()))

    with get_connection() as connection:
        group = connection.execute(
            "SELECT * FROM iam_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if group is None:
            raise HTTPException(status_code=404, detail="IAM group not found.")

        if member_ids:
            placeholders = ",".join("?" for _ in member_ids)
            found = connection.execute(
                f"SELECT id FROM iam_users WHERE id IN ({placeholders})",
                member_ids
            ).fetchall()
            if len(found) != len(member_ids):
                raise HTTPException(
                    status_code=422,
                    detail="One or more selected users do not exist."
                )

        connection.execute(
            "DELETE FROM iam_group_members WHERE group_id = ?", (group_id,)
        )
        connection.executemany("""
            INSERT INTO iam_group_members (group_id, user_id)
            VALUES (?, ?)
        """, [(group_id, user_id) for user_id in member_ids])

        _iam_audit(connection, "iam.group.members_replaced", "group", group_id, {
            "memberCount": len(member_ids)
        })
        row = connection.execute(
            "SELECT * FROM iam_groups WHERE id = ?", (group_id,)
        ).fetchone()
        return _iam_group_dict(connection, row)


@app.put("/api/iam/groups/{group_id}/department")
def set_iam_group_department(group_id: str, payload: dict, request: Request):
    _iam_directory_admin(request)

    raw_department_id = payload.get("department_id")
    department_id = str(raw_department_id or "").strip() or None

    with get_connection() as connection:
        group = connection.execute(
            "SELECT id, name FROM iam_groups WHERE id=?",
            (group_id,)
        ).fetchone()

        if not group:
            raise HTTPException(status_code=404, detail="IAM group not found.")

        if department_id and not connection.execute(
            "SELECT 1 FROM departments WHERE id=?",
            (department_id,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="Department not found.")

        connection.execute("""
            UPDATE iam_groups
            SET department_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (department_id, group_id))

        _iam_audit(
            connection,
            "iam.group.department_changed",
            "group",
            group_id,
            {"name": group["name"], "department_id": department_id}
        )

        row = connection.execute(
            "SELECT * FROM iam_groups WHERE id=?",
            (group_id,)
        ).fetchone()

        return _iam_group_dict(connection, row)


@app.get("/api/iam/audit")
def list_iam_audit(limit: int = 100):
    limit = max(1, min(int(limit), 500))
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, actor, action, resource_type, resource_id,
                   details_json, occurred_at
            FROM iam_audit_events
            ORDER BY occurred_at DESC, rowid DESC
            LIMIT ?
        """, (limit,)).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item.pop("details_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["details"] = {}
        result.append(item)
    return result

# END CARTMAN_IAM_DIRECTORY_API_V1



# CARTMAN_USER_DEFINED_API_CONNECTORS_LIVE_V1
# Provider-independent API key and outbound connector configuration management.
import hashlib as _cartman_int_hashlib
import json as _cartman_int_json
import os as _cartman_int_os
import secrets as _cartman_int_secrets
import uuid as _cartman_int_uuid
from datetime import datetime as _cartman_int_datetime, timedelta as _cartman_int_timedelta, timezone as _cartman_int_timezone
from urllib.parse import urlsplit as _cartman_int_urlsplit

_CARTMAN_INT_SCOPES = {
    "devices:read", "devices:write", "inventory:read", "inventory:write",
    "monitoring:read", "monitoring:write", "alerts:read", "alerts:write",
    "tickets:read", "tickets:write", "network:read", "network:write",
    "vpn:read", "vpn:write", "software:read", "software:write",
}
_CARTMAN_INT_AUTH_TYPES = {"none", "bearer_token", "basic", "api_key_header", "custom_header", "oauth2_client_credentials"}
_CARTMAN_INT_CONNECTION_TYPES = {"rest", "graphql", "soap", "custom_http"}
_CARTMAN_INT_SYNC_DIRECTIONS = {"manual", "import", "export", "bidirectional"}
_CARTMAN_INT_SYNC_INTERVALS = {"manual", "5m", "15m", "1h", "1d"}


def _cartman_int_now():
    return _cartman_int_datetime.now(_cartman_int_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cartman_int_ensure_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_api_keys (
            id TEXT PRIMARY KEY,
            owner_username TEXT NOT NULL,
            name TEXT NOT NULL,
            key_prefix TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            scopes_json TEXT NOT NULL DEFAULT '[]',
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Revoked')),
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            last_used_ip TEXT NOT NULL DEFAULT ''
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_api_keys_owner ON cartman_api_keys(owner_username, created_at DESC)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_api_key_access_logs (
            id TEXT PRIMARY KEY,
            api_key_id TEXT NOT NULL,
            api_key_name TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            client_ip TEXT NOT NULL DEFAULT '',
            status_code INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_api_key_logs_time ON cartman_api_key_access_logs(created_at DESC)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_connectors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            connection_type TEXT NOT NULL,
            base_url TEXT NOT NULL,
            auth_type TEXT NOT NULL DEFAULT 'none',
            auth_username TEXT NOT NULL DEFAULT '',
            auth_header_name TEXT NOT NULL DEFAULT 'Authorization',
            credential_ciphertext TEXT NOT NULL DEFAULT '',
            headers_json TEXT NOT NULL DEFAULT '{}',
            endpoints_json TEXT NOT NULL DEFAULT '[]',
            mapping_json TEXT NOT NULL DEFAULT '{}',
            verify_ssl INTEGER NOT NULL DEFAULT 1 CHECK(verify_ssl IN (0,1)),
            timeout_seconds INTEGER NOT NULL DEFAULT 15,
            retry_count INTEGER NOT NULL DEFAULT 2,
            sync_direction TEXT NOT NULL DEFAULT 'manual',
            sync_interval TEXT NOT NULL DEFAULT 'manual',
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_validated_at TEXT
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_connectors_owner ON cartman_connectors(created_by, updated_at DESC)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_connector_logs (
            id TEXT PRIMARY KEY,
            connector_id TEXT NOT NULL DEFAULT '',
            connector_name TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT 'Recorded',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_connector_logs_time ON cartman_connector_logs(created_at DESC)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS iam_audit_events (
            id TEXT PRIMARY KEY,
            actor TEXT NOT NULL DEFAULT 'Unattributed',
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_iam_audit_time ON iam_audit_events(occurred_at DESC)")


def _cartman_int_user(request, write=False, sensitive=False):
    raw = getattr(getattr(request, "state", None), "auth_user", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if isinstance(raw, dict):
        user = raw
    else:
        try:
            user = dict(raw)
        except Exception:
            user = {"username": getattr(raw, "username", ""), "role": getattr(raw, "role", "")}
    username = str(user.get("username") or user.get("email") or "").strip()
    role = str(user.get("role") or user.get("role_name") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is unavailable.")
    if sensitive and role not in {"admin", "administrator"}:
        raise HTTPException(status_code=403, detail="Only administrators may manage API keys.")
    allowed = {"admin", "administrator", "network_admin", "it_admin", "it_administrator"} if write else {"admin", "administrator", "network_admin", "it_admin", "it_administrator", "read_only", "support_agent", "viewer", "analyst"}
    if role not in allowed:
        raise HTTPException(status_code=403, detail="Your IAM role may not access this administration resource.")
    return user


def _cartman_int_actor(user):
    return str((user or {}).get("username") or (user or {}).get("email") or "").strip()


def _cartman_int_audit(connection, user, action, resource_type, resource_id, details=None):
    connection.execute("""
        INSERT INTO iam_audit_events (id, actor, action, resource_type, resource_id, details_json, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        str(_cartman_int_uuid.uuid4()), _cartman_int_actor(user), str(action),
        str(resource_type), str(resource_id or ""),
        _cartman_int_json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
        _cartman_int_now(),
    ))


def _cartman_int_clean(value, label, maximum=500, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=label + " must be text.")
    value = value.strip()
    if required and not value:
        raise HTTPException(status_code=422, detail=label + " is required.")
    if len(value) > maximum or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise HTTPException(status_code=422, detail=label + " is invalid or too long.")
    return value


def _cartman_int_json_value(value, label, expected_type, default):
    if value is None or value == "":
        return default
    try:
        parsed = _cartman_int_json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=label + " must contain valid JSON.")
    if not isinstance(parsed, expected_type):
        raise HTTPException(status_code=422, detail=label + " has an invalid JSON structure.")
    return parsed


def _cartman_int_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise HTTPException(status_code=503, detail="The cryptography package is required for encrypted connector credentials.")
    key_path = BASE_DIR / ".cartman_connector_fernet.key"
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        fd = _cartman_int_os.open(str(key_path), _cartman_int_os.O_WRONLY | _cartman_int_os.O_CREAT | _cartman_int_os.O_EXCL, 0o600)
        with _cartman_int_os.fdopen(fd, "wb") as handle:
            handle.write(key)
    try:
        _cartman_int_os.chmod(str(key_path), 0o600)
        key = key_path.read_bytes()
        return Fernet(key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Connector encryption key could not be loaded: " + str(exc))


def _cartman_int_encrypt_secret(secret):
    if not secret:
        return ""
    return _cartman_int_fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def _cartman_int_key_public(row):
    item = dict(row)
    try:
        item["scopes"] = _cartman_int_json.loads(item.pop("scopes_json") or "[]")
    except Exception:
        item["scopes"] = []
        item.pop("scopes_json", None)
    item.pop("token_hash", None)
    if item.get("status") == "Active" and item.get("expires_at"):
        try:
            expires = _cartman_int_datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
            if expires <= _cartman_int_datetime.now(_cartman_int_timezone.utc):
                item["status"] = "Expired"
        except ValueError:
            item["status"] = "Expired"
    return item


def _cartman_int_connector_public(row):
    item = dict(row)
    for field, default in (("headers_json", {}), ("endpoints_json", []), ("mapping_json", {})):
        try:
            item[field.replace("_json", "")] = _cartman_int_json.loads(item.pop(field) or "{}")
        except Exception:
            item[field.replace("_json", "")] = default
            item.pop(field, None)
    item["enabled"] = bool(item.get("enabled"))
    item["verify_ssl"] = bool(item.get("verify_ssl"))
    item["credential_configured"] = bool(item.get("credential_ciphertext"))
    item.pop("credential_ciphertext", None)
    return item


def _cartman_int_connector_log(connection, user, connector_id, connector_name, action, result="Recorded", details=None):
    connection.execute("""
        INSERT INTO cartman_connector_logs
            (id, connector_id, connector_name, actor, action, result, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(_cartman_int_uuid.uuid4()), str(connector_id or ""), str(connector_name or ""),
        _cartman_int_actor(user), str(action), str(result),
        _cartman_int_json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")), _cartman_int_now(),
    ))


def _cartman_int_connector_normalize(payload, existing=None, creating=False):
    payload = payload if isinstance(payload, dict) else {}
    old = dict(existing or {})
    def getv(key, default=""):
        return payload[key] if key in payload else old.get(key, default)
    name = _cartman_int_clean(getv("name"), "Connector name", 120, True)
    description = _cartman_int_clean(getv("description"), "Description", 1000)
    base_url = _cartman_int_clean(getv("base_url"), "Base URL", 1000, True)
    parsed = _cartman_int_urlsplit(base_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Base URL must be an HTTP or HTTPS URL without embedded credentials.")
    connection_type = _cartman_int_clean(getv("connection_type", "rest"), "Connection type", 30, True)
    if connection_type not in _CARTMAN_INT_CONNECTION_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported connection type.")
    auth_type = _cartman_int_clean(getv("auth_type", "none"), "Authentication type", 40, True)
    if auth_type not in _CARTMAN_INT_AUTH_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported authentication type.")
    auth_username = _cartman_int_clean(getv("auth_username"), "Authentication username", 200)
    auth_header_name = _cartman_int_clean(getv("auth_header_name", "Authorization"), "Authentication header", 100, True)
    headers = _cartman_int_json_value(getv("headers", {}), "Custom headers", dict, {})
    endpoints = _cartman_int_json_value(getv("endpoints", []), "Endpoint definitions", list, [])
    mapping = _cartman_int_json_value(getv("mapping", {}), "Field mapping", dict, {})
    if len(endpoints) > 100:
        raise HTTPException(status_code=422, detail="A connector may define up to 100 endpoints.")
    cleaned_endpoints = []
    for index, endpoint in enumerate(endpoints):
        if not isinstance(endpoint, dict):
            raise HTTPException(status_code=422, detail=f"Endpoint {index + 1} must be an object.")
        method = str(endpoint.get("method") or "GET").upper().strip()
        path = _cartman_int_clean(str(endpoint.get("path") or ""), f"Endpoint {index + 1} path", 500, True)
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not path.startswith("/") or path.startswith("//"):
            raise HTTPException(status_code=422, detail=f"Endpoint {index + 1} must use GET/POST/PUT/PATCH/DELETE and a relative path beginning with one slash.")
        cleaned_endpoints.append({"name": _cartman_int_clean(str(endpoint.get("name") or f"Endpoint {index + 1}"), "Endpoint name", 120, True), "method": method, "path": path})
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
            raise HTTPException(status_code=422, detail="Custom headers must be a JSON object of text-compatible values.")
        lowered_header = key.strip().lower().replace("_", "-")
        if any(term in lowered_header for term in ("auth", "token", "secret", "password", "api-key", "apikey", "credential")):
            raise HTTPException(status_code=422, detail="Sensitive header values must use the encrypted Authentication fields, not Custom headers.")
    try:
        timeout = int(getv("timeout_seconds", 15))
        retries = int(getv("retry_count", 2))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Timeout and retry count must be integers.")
    if not 1 <= timeout <= 120 or not 0 <= retries <= 10:
        raise HTTPException(status_code=422, detail="Timeout must be 1-120 seconds and retries 0-10.")
    direction = _cartman_int_clean(getv("sync_direction", "manual"), "Sync direction", 30, True)
    interval = _cartman_int_clean(getv("sync_interval", "manual"), "Sync interval", 20, True)
    if direction not in _CARTMAN_INT_SYNC_DIRECTIONS or interval not in _CARTMAN_INT_SYNC_INTERVALS:
        raise HTTPException(status_code=422, detail="Unsupported synchronization setting.")
    def boolean(key, default):
        value = getv(key, default)
        if isinstance(value, bool): return int(value)
        if isinstance(value, int) and value in (0, 1): return value
        if isinstance(value, str) and value.lower() in {"true", "false", "1", "0"}: return int(value.lower() in {"true", "1"})
        raise HTTPException(status_code=422, detail=key + " must be a boolean.")
    secret = _cartman_int_clean(payload.get("credential_secret", ""), "Credential", 4000)
    old_cipher = str(old.get("credential_ciphertext") or "")
    if auth_type == "none":
        ciphertext = ""
    elif secret:
        ciphertext = _cartman_int_encrypt_secret(secret)
    elif not creating and old_cipher and auth_type == old.get("auth_type"):
        ciphertext = old_cipher
    else:
        raise HTTPException(status_code=422, detail="This authentication method requires a credential. Enter the secret value.")
    return {
        "name": name, "description": description, "base_url": base_url, "connection_type": connection_type,
        "auth_type": auth_type, "auth_username": auth_username, "auth_header_name": auth_header_name,
        "credential_ciphertext": ciphertext,
        "headers_json": _cartman_int_json.dumps(headers, ensure_ascii=False, separators=(",", ":")),
        "endpoints_json": _cartman_int_json.dumps(cleaned_endpoints, ensure_ascii=False, separators=(",", ":")),
        "mapping_json": _cartman_int_json.dumps(mapping, ensure_ascii=False, separators=(",", ":")),
        "verify_ssl": boolean("verify_ssl", True), "timeout_seconds": timeout, "retry_count": retries,
        "sync_direction": direction, "sync_interval": interval, "enabled": boolean("enabled", True),
    }


@app.get("/api/admin/api-directory")
def cartman_admin_api_directory(request: Request):
    _cartman_int_user(request, write=False)
    items = []
    seen = set()
    for route in app.routes:
        path = str(getattr(route, "path", "") or "")
        if not path.startswith("/api/") or path.startswith("/api/admin/"):
            continue
        methods = getattr(route, "methods", None) or set()
        for method in sorted(methods):
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            key = (method, path)
            if key in seen: continue
            seen.add(key)
            parts = path.strip("/").split("/")
            category = parts[1] if len(parts) > 1 else "other"
            scope_category = {
                "devices": "devices", "inventory": "inventory", "monitoring": "monitoring",
                "alerts": "alerts", "alerts-management": "alerts", "tickets": "tickets",
                "network": "network", "vpn": "vpn", "software": "software",
            }.get(category)
            required_scope = (scope_category + (":read" if method == "GET" else ":write")) if scope_category else "session-authenticated"
            items.append({"method": method, "path": path, "name": str(getattr(route, "name", "API endpoint") or "API endpoint"), "summary": str(getattr(route, "summary", "") or getattr(route, "description", "") or "").split("\n", 1)[0][:180], "scope": required_scope})
    items.sort(key=lambda item: (item["path"], item["method"]))
    return {"items": items, "total": len(items), "source": "FastAPI route registry"}


@app.get("/api/admin/api-keys")
def cartman_admin_api_keys_list(request: Request):
    _cartman_int_user(request, write=False, sensitive=True)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        rows = connection.execute("SELECT id,owner_username,name,key_prefix,scopes_json,expires_at,status,created_at,last_used_at,last_used_ip FROM cartman_api_keys ORDER BY created_at DESC").fetchall()
        return {"items": [_cartman_int_key_public(row) for row in rows], "total": len(rows)}


@app.post("/api/admin/api-keys", status_code=201)
async def cartman_admin_api_key_create(request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    try: payload = await request.json()
    except Exception: raise HTTPException(status_code=400, detail="A JSON request body is required.")
    name = _cartman_int_clean(payload.get("name"), "Key name", 120, True)
    scopes = payload.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise HTTPException(status_code=422, detail="Select at least one API scope.")
    scopes = sorted(set(str(scope) for scope in scopes))
    if any(scope not in _CARTMAN_INT_SCOPES for scope in scopes):
        raise HTTPException(status_code=422, detail="One or more API scopes are unsupported.")
    try: days = int(payload.get("expires_in_days", 90))
    except (TypeError, ValueError): raise HTTPException(status_code=422, detail="Expiration must be a number of days.")
    if days not in {0, 30, 90, 365}:
        raise HTTPException(status_code=422, detail="Expiration must be Never, 30, 90 or 365 days.")
    token = "cm_live_" + _cartman_int_secrets.token_urlsafe(36)
    key_id = str(_cartman_int_uuid.uuid4())
    now = _cartman_int_now()
    expires = (_cartman_int_datetime.now(_cartman_int_timezone.utc) + _cartman_int_timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z") if days else None
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        connection.execute("INSERT INTO cartman_api_keys (id,owner_username,name,key_prefix,token_hash,scopes_json,expires_at,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (key_id,_cartman_int_actor(user),name,token[:20],_cartman_int_hashlib.sha256(token.encode()).hexdigest(),_cartman_int_json.dumps(scopes),expires,"Active",now))
        _cartman_int_audit(connection,user,"api_key.created","api_key",key_id,{"name":name,"scopes":scopes,"expires_at":expires})
        row = connection.execute("SELECT id,owner_username,name,key_prefix,scopes_json,expires_at,status,created_at,last_used_at,last_used_ip FROM cartman_api_keys WHERE id=?", (key_id,)).fetchone()
        item = _cartman_int_key_public(row)
    return {"item": item, "token": token, "shown_once": True}


@app.post("/api/admin/api-keys/{key_id}/revoke")
def cartman_admin_api_key_revoke(key_id: str, request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        row = connection.execute("SELECT * FROM cartman_api_keys WHERE id=?", (key_id,)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="API key not found.")
        if row["status"] == "Revoked": return {"revoked": True, "id": key_id, "already_revoked": True}
        connection.execute("UPDATE cartman_api_keys SET status='Revoked' WHERE id=?", (key_id,))
        _cartman_int_audit(connection,user,"api_key.revoked","api_key",key_id,{"name":row["name"],"key_prefix":row["key_prefix"]})
        return {"revoked": True, "id": key_id}


@app.get("/api/admin/api-key-logs")
def cartman_admin_api_key_logs(request: Request, limit: int = 200, q: str = ""):
    _cartman_int_user(request, write=False, sensitive=True)
    limit = max(1, min(int(limit or 200), 500))
    q = _cartman_int_clean(q, "Search", 160)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        sql = "SELECT * FROM cartman_api_key_access_logs"
        params = []
        if q:
            sql += " WHERE api_key_name LIKE ? OR path LIKE ? OR method LIKE ? OR client_ip LIKE ?"
            params.extend(["%"+q+"%"]*4)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = connection.execute(sql, params).fetchall()
        return {"items": [dict(row) for row in rows], "total": len(rows)}


@app.get("/api/connectors")
def cartman_connectors_list(request: Request, q: str = "", status: str = "all"):
    _cartman_int_user(request, write=False)
    q = _cartman_int_clean(q, "Search", 160)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        sql = "SELECT * FROM cartman_connectors"
        clauses, params = [], []
        if q:
            clauses.append("(name LIKE ? OR description LIKE ? OR base_url LIKE ?)")
            params.extend(["%"+q+"%"]*3)
        if status.lower() in {"enabled", "disabled"}:
            clauses.append("enabled=?")
            params.append(1 if status.lower() == "enabled" else 0)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        rows = connection.execute(sql, params).fetchall()
        return {"items": [_cartman_int_connector_public(row) for row in rows], "total": len(rows), "execution_enabled": False}


@app.post("/api/connectors", status_code=201)
async def cartman_connectors_create(request: Request):
    user = _cartman_int_user(request, write=True)
    try: payload = await request.json()
    except Exception: raise HTTPException(status_code=400, detail="A JSON request body is required.")
    values = _cartman_int_connector_normalize(payload, creating=True)
    connector_id = str(_cartman_int_uuid.uuid4())
    now = _cartman_int_now()
    fields = list(values.keys())
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        placeholders = ",".join("?" for _ in range(len(fields)+4))
        connection.execute("INSERT INTO cartman_connectors (id,"+",".join(fields)+",created_by,created_at,updated_at) VALUES ("+placeholders+")", [connector_id]+[values[field] for field in fields]+[_cartman_int_actor(user),now,now])
        row = connection.execute("SELECT * FROM cartman_connectors WHERE id=?", (connector_id,)).fetchone()
        public = _cartman_int_connector_public(row)
        _cartman_int_connector_log(connection,user,connector_id,values["name"],"created","Configuration saved",{"connection_type":values["connection_type"],"base_url":values["base_url"]})
        _cartman_int_audit(connection,user,"connector.created","connector",connector_id,{"name":values["name"],"connection_type":values["connection_type"],"base_url":values["base_url"]})
    return {"item": public, "execution_enabled": False}


@app.put("/api/connectors/{connector_id}")
async def cartman_connectors_update(connector_id: str, request: Request):
    user = _cartman_int_user(request, write=True)
    try: payload = await request.json()
    except Exception: raise HTTPException(status_code=400, detail="A JSON request body is required.")
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        old = connection.execute("SELECT * FROM cartman_connectors WHERE id=?", (connector_id,)).fetchone()
        if not old: raise HTTPException(status_code=404, detail="Connector not found.")
        before = _cartman_int_connector_public(old)
        values = _cartman_int_connector_normalize(payload, dict(old), creating=False)
        values["updated_at"] = _cartman_int_now()
        assignments = ",".join(key+"=?" for key in values)
        connection.execute("UPDATE cartman_connectors SET "+assignments+" WHERE id=?", [values[key] for key in values]+[connector_id])
        updated = connection.execute("SELECT * FROM cartman_connectors WHERE id=?", (connector_id,)).fetchone()
        after = _cartman_int_connector_public(updated)
        changed = [key for key in ("name","description","base_url","connection_type","auth_type","auth_username","auth_header_name","credential_configured","headers","endpoints","mapping","verify_ssl","timeout_seconds","retry_count","sync_direction","sync_interval","enabled") if before.get(key) != after.get(key)]
        if payload.get("credential_secret"):
            changed.append("credential_secret")
        action = "updated" if changed else "saved"
        _cartman_int_connector_log(connection,user,connector_id,after["name"],action,"Configuration saved",{"changed_fields":changed,"before":{k:before.get(k) for k in changed},"after":{k:after.get(k) for k in changed}})
        _cartman_int_audit(connection,user,"connector."+action,"connector",connector_id,{"name":after["name"],"changed_fields":changed,"before":{k:before.get(k) for k in changed},"after":{k:after.get(k) for k in changed}})
        return {"item": after, "execution_enabled": False}


@app.post("/api/connectors/{connector_id}/validate")
def cartman_connectors_validate(connector_id: str, request: Request):
    user = _cartman_int_user(request, write=True)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        row = connection.execute("SELECT * FROM cartman_connectors WHERE id=?", (connector_id,)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Connector not found.")
        now = _cartman_int_now()
        parsed = _cartman_int_urlsplit(str(row["base_url"] or ""))
        valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        try:
            _cartman_int_json.loads(row["headers_json"] or "{}")
            _cartman_int_json.loads(row["endpoints_json"] or "[]")
            _cartman_int_json.loads(row["mapping_json"] or "{}")
        except Exception:
            valid = False
        result = "Configuration valid" if valid else "Configuration invalid"
        message = "Local configuration validation passed. No outbound network request was made; live connection testing is reserved for the 0.3 connector engine." if valid else "One or more saved connection settings are invalid."
        connection.execute("UPDATE cartman_connectors SET last_validated_at=? WHERE id=?", (now,connector_id))
        _cartman_int_connector_log(connection,user,connector_id,row["name"],"configuration_validated" if valid else "configuration_validation_failed",result,{"message":message,"network_request_performed":False})
        _cartman_int_audit(connection,user,"connector.configuration_validated" if valid else "connector.configuration_validation_failed","connector",connector_id,{"name":row["name"],"valid":valid,"network_request_performed":False})
        return {"valid":valid,"connection_tested":False,"message":message,"validated_at":now}


@app.delete("/api/connectors/{connector_id}", status_code=200)
def cartman_connectors_delete(connector_id: str, request: Request):
    user = _cartman_int_user(request, write=True)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        row = connection.execute("SELECT * FROM cartman_connectors WHERE id=?", (connector_id,)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Connector not found.")
        name = str(row["name"])
        connection.execute("DELETE FROM cartman_connectors WHERE id=?", (connector_id,))
        _cartman_int_connector_log(connection,user,connector_id,name,"deleted","Connector removed",{"name":name})
        _cartman_int_audit(connection,user,"connector.deleted","connector",connector_id,{"name":name})
        return {"deleted":True,"id":connector_id}


@app.get("/api/connectors/logs")
def cartman_connectors_logs(request: Request, limit: int = 200, q: str = "", connector_id: str = ""):
    _cartman_int_user(request, write=False)
    limit = max(1,min(int(limit or 200),500))
    q = _cartman_int_clean(q,"Search",160)
    connector_id = _cartman_int_clean(connector_id,"Connector ID",80)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        clauses, params = [], []
        if connector_id: clauses.append("connector_id=?"); params.append(connector_id)
        if q:
            clauses.append("(connector_name LIKE ? OR actor LIKE ? OR action LIKE ? OR details_json LIKE ?)")
            params.extend(["%"+q+"%"]*4)
        sql = "SELECT * FROM cartman_connector_logs"
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = connection.execute(sql,params).fetchall()
        items=[]
        for row in rows:
            item=dict(row)
            try: item["details"]=_cartman_int_json.loads(item.pop("details_json") or "{}")
            except Exception: item["details"]={}
            items.append(item)
        return {"items":items,"total":len(items)}

# END CARTMAN_USER_DEFINED_API_CONNECTORS_LIVE_V1


# CARTMAN_AUTHENTICATION_V1
try:
    from . import auth_security as _auth_security
except ImportError:  # Supports direct imports when running inside app/.
    import auth_security as _auth_security

_auth_security.get_connection = get_connection
_auth_security.initialize_auth_database()

# CARTMAN_RBAC_FOUNDATION_V1
try:
    from . import rbac_api as _rbac_api
except ImportError:  # Supports direct imports from app/.
    import rbac_api as _rbac_api
_rbac_api.get_connection = get_connection
_rbac_api.initialize_rbac_database()
app.include_router(_rbac_api.router)
app.middleware("http")(_rbac_api.wrap_auth_middleware(_auth_security.auth_middleware))
from app.ssh_profiles import router as ssh_profiles_router
from app.remote_access_api import router as remote_access_router
app.include_router(_auth_security.router)
app.include_router(ssh_profiles_router)
app.include_router(remote_access_router)
# END CARTMAN_AUTHENTICATION_V1

# CARTMAN_NETWORK_INFRASTRUCTURE_API_V1
try:
    from . import network_infrastructure_api as _network_infrastructure_api
except ImportError:  # Supports direct imports when running inside app/.
    import network_infrastructure_api as _network_infrastructure_api

_network_infrastructure_api.get_connection = get_connection
_network_infrastructure_api.get_live_device_connections = _get_live_device_connections
_network_infrastructure_api.initialize_network_infrastructure_database()
app.include_router(_network_infrastructure_api.router)
# CARTMAN_WINDOWS_DHCP_CONNECTOR_ROUTER_V1
try:
    from . import windows_dhcp_connector as _windows_dhcp_connector
except ImportError:
    import windows_dhcp_connector as _windows_dhcp_connector

_windows_dhcp_connector.get_connection = get_connection
_windows_dhcp_connector.get_live_device_connections = _get_live_device_connections
app.include_router(_windows_dhcp_connector.router)

# CARTMAN_WINDOWS_DNS_DHCP_MANAGEMENT_V1
try:
    from . import windows_dns_dhcp_management as _windows_dns_dhcp_management
except ImportError:
    import windows_dns_dhcp_management as _windows_dns_dhcp_management

_windows_dns_dhcp_management.get_connection = get_connection
_windows_dns_dhcp_management.get_live_device_connections = _get_live_device_connections
app.include_router(_windows_dns_dhcp_management.router)

# CARTMAN_REPORTS_API_V1
try:
    from . import reports_api as _reports_api
except ImportError:
    import reports_api as _reports_api

_reports_api.DATABASE = DATABASE
app.include_router(_reports_api.router)
# END CARTMAN_REPORTS_API_V1


# END CARTMAN_NETWORK_INFRASTRUCTURE_API_V1


# CARTMAN_VPN_CONTROL_PLANE_V1
# Persistent VPN management plane.
# This is configuration/state storage only; it does not establish VPN tunnels.

import ipaddress as _vpn_ipaddress
import json as _vpn_json
import re as _vpn_re
import uuid as _vpn_uuid
from fastapi import Body as _VPNBody
from fastapi import Request as _VPNRequest
from fastapi import HTTPException as _VPNHTTPException


_VPN_ENGINE_STATE = "Not implemented"
_VPN_ENGINE_NOTE = (
    "The Cartman VPN engine has not been implemented yet. Saved gateway, "
    "peer and policy records do not establish tunnels or enforce network traffic rules."
)
_VPN_AUTH_STATES = {"Pending", "Quarantined", "Approved", "Blocked"}
_VPN_POLICY_ACTIONS = {"Allow", "Deny"}
_VPN_SUBJECT_TYPES = {"All", "User", "Device", "Department", "Group"}


def _vpn_initialize_schema():
    with get_connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS vpn_networks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                cidr TEXT NOT NULL UNIQUE,
                network_type TEXT NOT NULL CHECK (
                    network_type IN ('Quarantine', 'Department', 'Site-to-Site')
                ),
                department TEXT NOT NULL DEFAULT '',
                gateway_ip TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vpn_gateways (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                endpoint TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                protocol TEXT NOT NULL DEFAULT 'Cartman VPN',
                listen_port INTEGER NOT NULL DEFAULT 0
                    CHECK (listen_port BETWEEN 0 AND 65535),
                public_key TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Not installed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vpn_peers (
                id TEXT PRIMARY KEY,
                cartman_id TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                device_name TEXT NOT NULL,
                device_os TEXT NOT NULL DEFAULT 'Unknown',
                source_ip TEXT NOT NULL DEFAULT '',
                public_key TEXT NOT NULL DEFAULT '',
                assigned_ip TEXT UNIQUE,
                assigned_network_id TEXT REFERENCES vpn_networks(id)
                    ON DELETE SET NULL,
                gateway_id TEXT REFERENCES vpn_gateways(id)
                    ON DELETE SET NULL,
                authorization_status TEXT NOT NULL DEFAULT 'Quarantined'
                    CHECK (authorization_status IN (
                        'Pending', 'Quarantined', 'Approved', 'Blocked'
                    )),
                tunnel_status TEXT NOT NULL DEFAULT 'Not installed',
                enforcement_state TEXT NOT NULL DEFAULT 'Not applied',
                last_seen_at TEXT,
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_vpn_peers_status
                ON vpn_peers(authorization_status, created_at);

            CREATE TABLE IF NOT EXISTS vpn_access_policies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                subject_type TEXT NOT NULL DEFAULT 'All'
                    CHECK (subject_type IN (
                        'All', 'User', 'Device', 'Department', 'Group'
                    )),
                subject_value TEXT NOT NULL DEFAULT '',
                source_network_id TEXT REFERENCES vpn_networks(id)
                    ON DELETE SET NULL,
                destination TEXT NOT NULL DEFAULT '',
                protocol TEXT NOT NULL DEFAULT 'Any',
                ports TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT 'Deny'
                    CHECK (action IN ('Allow', 'Deny')),
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
                description TEXT NOT NULL DEFAULT '',
                enforcement_state TEXT NOT NULL DEFAULT 'Not applied',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vpn_site_links (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                gateway_a_id TEXT REFERENCES vpn_gateways(id)
                    ON DELETE SET NULL,
                gateway_b_id TEXT REFERENCES vpn_gateways(id)
                    ON DELETE SET NULL,
                local_subnet TEXT NOT NULL,
                remote_subnet TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft',
                enforcement_state TEXT NOT NULL DEFAULT 'Not applied',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vpn_audit_logs (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL DEFAULT 'Local operator',
                event TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL DEFAULT '',
                source_ip TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT 'Recorded',
                severity TEXT NOT NULL DEFAULT 'Info',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_vpn_audit_created
                ON vpn_audit_logs(created_at DESC);
        """)

        network_columns = {
            row[1] for row in db.execute("PRAGMA table_info(vpn_networks)").fetchall()
        }
        if "gateway_ip" not in network_columns:
            db.execute(
                "ALTER TABLE vpn_networks "
                "ADD COLUMN gateway_ip TEXT NOT NULL DEFAULT ''"
            )
            db.commit()


def _vpn_require_operator(request):
    # Reuse Cartman's existing loopback-only task-management guard.
    # Remote/admin session authentication must be added before exposing these
    # management routes to non-local browsers.
    require_local_task_operator(request)


def _vpn_actor(request):
    value = request.headers.get("X-Operator", "Local operator")
    value = _vpn_re.sub(r"[\x00-\x1f\x7f]", "", str(value)).strip()
    return value[:120] or "Local operator"


def _vpn_new_id(prefix):
    return prefix + "-" + _vpn_uuid.uuid4().hex


def _vpn_text(value, field, maximum=500, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _VPNHTTPException(422, detail=field + " must be text.")
    value = value.strip()
    if required and not value:
        raise _VPNHTTPException(422, detail=field + " is required.")
    if len(value) > maximum:
        raise _VPNHTTPException(422, detail=field + " is too long.")
    if any(ord(ch) < 32 for ch in value):
        raise _VPNHTTPException(422, detail=field + " contains control characters.")
    return value


def _vpn_cidr(value, field="CIDR"):
    try:
        network = _vpn_ipaddress.ip_network(
            _vpn_text(value, field, 80, required=True),
            strict=True
        )
    except ValueError as exc:
        raise _VPNHTTPException(
            422, detail=field + " must be a valid network CIDR."
        ) from exc
    if network.version != 4 or network.prefixlen > 30:
        raise _VPNHTTPException(
            422, detail=field + " must be an IPv4 network with at least two usable host addresses."
        )
    return network


def _vpn_validate_gateway_ip(value, network, field="VPN gateway/interface IP"):
    value = _vpn_text(value, field, 80)
    if not value:
        return ""

    try:
        address = _vpn_ipaddress.ip_address(value)
    except ValueError as exc:
        raise _VPNHTTPException(422, detail=field + " must be a valid IP address.") from exc

    if (
        address.version != 4
        or address not in network
        or address == network.network_address
        or address == network.broadcast_address
    ):
        raise _VPNHTTPException(
            422,
            detail=field + " must be a usable IPv4 host address inside the configured CIDR."
        )

    return str(address)


def _vpn_bool(value, field, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise _VPNHTTPException(422, detail=field + " must be true or false.")


def _vpn_log(db, request, event, target_type, target_id="",
             outcome="Recorded", severity="Info", details=None):
    source_ip = ""
    if request.client:
        source_ip = str(request.client.host or "")[:80]

    db.execute("""
        INSERT INTO vpn_audit_logs
            (id, actor, event, target_type, target_id, source_ip,
             outcome, severity, details_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        _vpn_new_id("vpn-audit"),
        _vpn_actor(request),
        _vpn_text(event, "Event", 150, required=True),
        _vpn_text(target_type, "Target type", 80, required=True),
        _vpn_text(target_id, "Target ID", 180),
        source_ip,
        _vpn_text(outcome, "Outcome", 180),
        severity,
        _vpn_json.dumps(details or {}, ensure_ascii=False),
    ))


def _vpn_decorate(row, kind="record"):
    item = dict(row)
    # Never label a DB record as an active tunnel until an engine reports it.
    item["engine_status"] = _VPN_ENGINE_STATE
    item["enforcement_state"] = _VPN_ENGINE_NOTE
    if kind == "peer":
        item["tunnel_status"] = "Not installed"
    return item


def _vpn_get_network(db, network_id):
    row = db.execute(
        "SELECT * FROM vpn_networks WHERE id = ?", (network_id,)
    ).fetchone()
    if row is None:
        raise _VPNHTTPException(404, detail="VPN network not found.")
    return row


def _vpn_get_quarantine_network(db):
    rows = db.execute("""
        SELECT * FROM vpn_networks
        WHERE network_type = 'Quarantine' AND enabled = 1
        ORDER BY name COLLATE NOCASE
    """).fetchall()

    if not rows:
        raise _VPNHTTPException(
            409,
            detail="No enabled Quarantine network is configured. "
                   "Create a quarantine pool with its own CIDR and gateway/interface IP first."
        )
    if len(rows) > 1:
        raise _VPNHTTPException(
            409,
            detail="Multiple enabled Quarantine networks exist. "
                   "Enable exactly one quarantine pool before enrolling peers."
        )
    return rows[0]


def _vpn_network_overlap_check(db, network, exclude_id=None):
    rows = db.execute(
        "SELECT id, cidr FROM vpn_networks WHERE enabled = 1"
    ).fetchall()
    for row in rows:
        if exclude_id and row["id"] == exclude_id:
            continue
        try:
            existing = _vpn_ipaddress.ip_network(row["cidr"], strict=True)
        except ValueError:
            continue
        if network.overlaps(existing):
            raise _VPNHTTPException(
                409,
                detail="VPN network overlaps with the enabled network "
                       + str(row["cidr"]) + "."
            )


def _vpn_allocate_ip(db, network_id):
    row = _vpn_get_network(db, network_id)
    if not row["enabled"]:
        raise _VPNHTTPException(409, detail="The selected VPN network is disabled.")

    network = _vpn_cidr(row["cidr"])
    gateway_ip = _vpn_validate_gateway_ip(
        row["gateway_ip"], network
    )
    if not gateway_ip:
        raise _VPNHTTPException(
            409,
            detail="Configure the VPN gateway/interface IP for this network "
                   "before assigning peer addresses."
        )

    used = {
        item["assigned_ip"]
        for item in db.execute(
            "SELECT assigned_ip FROM vpn_peers WHERE assigned_ip IS NOT NULL"
        ).fetchall()
    }
    used.add(gateway_ip)

    # Allocate from actual usable host addresses; do not assume a fixed subnet
    # or silently reserve the first 2/10 addresses.
    for address in network.hosts():
        candidate = str(address)
        if candidate not in used:
            return candidate

    raise _VPNHTTPException(409, detail="No available IP addresses in this VPN network.")


def _vpn_network_type(db, network_id):
    return _vpn_get_network(db, network_id)["network_type"]


# ---------- Overview ----------

@app.get("/api/vpn/overview")
def vpn_overview(request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        def count(sql, params=()):
            return db.execute(sql, params).fetchone()[0]

        recent = db.execute("""
            SELECT id, actor, event, target_type, target_id,
                   source_ip, outcome, severity, created_at
            FROM vpn_audit_logs
            ORDER BY created_at DESC, rowid DESC
            LIMIT 10
        """).fetchall()

        return {
            "engine": {
                "status": _VPN_ENGINE_STATE,
                "available": False,
                "message": _VPN_ENGINE_NOTE,
            },
            "counts": {
                "gateways": count("SELECT COUNT(*) FROM vpn_gateways"),
                "networks": count("SELECT COUNT(*) FROM vpn_networks WHERE enabled = 1"),
                "peers": count("SELECT COUNT(*) FROM vpn_peers"),
                "quarantined": count(
                    "SELECT COUNT(*) FROM vpn_peers WHERE authorization_status = 'Quarantined'"
                ),
                "pending": count(
                    "SELECT COUNT(*) FROM vpn_peers WHERE authorization_status = 'Pending'"
                ),
                "approved": count(
                    "SELECT COUNT(*) FROM vpn_peers WHERE authorization_status = 'Approved'"
                ),
                "blocked": count(
                    "SELECT COUNT(*) FROM vpn_peers WHERE authorization_status = 'Blocked'"
                ),
                "policies": count("SELECT COUNT(*) FROM vpn_access_policies"),
                "enabled_policies": count(
                    "SELECT COUNT(*) FROM vpn_access_policies WHERE enabled = 1"
                ),
                "site_to_site": count("SELECT COUNT(*) FROM vpn_site_links"),
                "connected_tunnels": 0,
            },
            "recent_audit": [dict(row) for row in recent],
        }


# ---------- Network pools ----------

@app.get("/api/vpn/networks")
def vpn_list_networks(request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        rows = db.execute("""
            SELECT * FROM vpn_networks ORDER BY network_type, name COLLATE NOCASE
        """).fetchall()
        return [_vpn_decorate(row) for row in rows]


@app.post("/api/vpn/networks", status_code=201)
def vpn_create_network(request: _VPNRequest, payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    name = _vpn_text(payload.get("name"), "Name", 120, True)
    cidr = _vpn_cidr(payload.get("cidr"))
    network_type = payload.get("network_type", "Department")
    if network_type not in {"Department", "Site-to-Site", "Quarantine"}:
        raise _VPNHTTPException(
            422,
            detail="Network type must be Department, Quarantine or Site-to-Site."
        )

    department = _vpn_text(payload.get("department"), "Department", 120)
    description = _vpn_text(payload.get("description"), "Description", 1200)
    gateway_ip = _vpn_validate_gateway_ip(payload.get("gateway_ip"), cidr)
    network_id = _vpn_new_id("vpn-network")

    try:
        with get_connection() as db:
            if network_type == "Quarantine":
                existing_quarantine = db.execute("""
                    SELECT id FROM vpn_networks
                    WHERE network_type = 'Quarantine' AND enabled = 1
                    LIMIT 1
                """).fetchone()
                if existing_quarantine:
                    raise _VPNHTTPException(
                        409,
                        detail="An enabled Quarantine network already exists. "
                               "Configure or disable it before creating another."
                    )

            _vpn_network_overlap_check(db, cidr)

            if gateway_ip and db.execute(
                "SELECT 1 FROM vpn_peers WHERE assigned_ip = ? LIMIT 1",
                (gateway_ip,)
            ).fetchone():
                raise _VPNHTTPException(
                    409,
                    detail="The selected gateway/interface IP is already assigned to a peer."
                )

            db.execute("""
                INSERT INTO vpn_networks
                    (id, name, cidr, network_type, department,
                     gateway_ip, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                network_id, name, str(cidr), network_type,
                department, gateway_ip, description
            ))

            _vpn_log(
                db, request, "VPN network created", "network", network_id,
                details={
                    "name": name,
                    "cidr": str(cidr),
                    "type": network_type,
                    "gateway_ip": gateway_ip
                }
            )
            row = db.execute(
                "SELECT * FROM vpn_networks WHERE id = ?", (network_id,)
            ).fetchone()

        result = _vpn_decorate(row)
        result["engine_status"] = _VPN_ENGINE_STATE
        result["message"] = (
            "Network configuration saved. No tunnel or firewall change was applied."
        )
        return result

    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(
            409, detail="A VPN network with this name or CIDR already exists."
        ) from exc


@app.put("/api/vpn/networks/{network_id}")
def vpn_update_network(network_id: str, request: _VPNRequest,
                       payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    allowed = {"name", "cidr", "department", "gateway_ip", "description", "enabled"}
    if not payload or set(payload) - allowed:
        raise _VPNHTTPException(
            422,
            detail="Only name, CIDR, department, gateway_ip, description and enabled can be updated."
        )

    try:
        with get_connection() as db:
            current = _vpn_get_network(db, network_id)
            updates = {}

            if "name" in payload:
                updates["name"] = _vpn_text(payload["name"], "Name", 120, True)
            if "department" in payload:
                updates["department"] = _vpn_text(payload["department"], "Department", 120)
            if "description" in payload:
                updates["description"] = _vpn_text(payload["description"], "Description", 1200)

            if "enabled" in payload:
                enabled_value = _vpn_bool(payload["enabled"], "enabled")
                if enabled_value and current["network_type"] == "Quarantine":
                    other = db.execute("""
                        SELECT id FROM vpn_networks
                        WHERE network_type = 'Quarantine' AND enabled = 1 AND id != ?
                        LIMIT 1
                    """, (network_id,)).fetchone()
                    if other:
                        raise _VPNHTTPException(
                            409, detail="Another Quarantine network is already enabled."
                        )

                if not enabled_value:
                    assigned = db.execute("""
                        SELECT COUNT(*) FROM vpn_peers WHERE assigned_network_id = ?
                    """, (network_id,)).fetchone()[0]
                    if assigned:
                        raise _VPNHTTPException(
                            409,
                            detail="Move peer assignments before disabling this network."
                        )
                updates["enabled"] = int(enabled_value)

            new_network = (
                _vpn_cidr(payload["cidr"])
                if "cidr" in payload
                else _vpn_cidr(current["cidr"])
            )

            if "cidr" in payload and new_network.with_prefixlen != current["cidr"]:
                assigned = db.execute("""
                    SELECT COUNT(*) FROM vpn_peers WHERE assigned_network_id = ?
                """, (network_id,)).fetchone()[0]
                if assigned:
                    raise _VPNHTTPException(
                        409, detail="Move peer assignments before changing this network CIDR."
                    )
                updates["cidr"] = str(new_network)

            final_enabled = updates.get("enabled", current["enabled"])
            if final_enabled and (
                "cidr" in updates
                or (not current["enabled"] and final_enabled)
            ):
                _vpn_network_overlap_check(db, new_network, exclude_id=network_id)

            if "gateway_ip" in payload or "cidr" in payload:
                raw_gateway_ip = payload.get(
                    "gateway_ip", current["gateway_ip"] or ""
                )
                new_gateway_ip = _vpn_validate_gateway_ip(raw_gateway_ip, new_network)
                old_gateway_ip = current["gateway_ip"] or ""

                if new_gateway_ip != old_gateway_ip:
                    if new_gateway_ip and db.execute(
                        "SELECT 1 FROM vpn_peers WHERE assigned_ip = ? LIMIT 1",
                        (new_gateway_ip,)
                    ).fetchone():
                        raise _VPNHTTPException(
                            409,
                            detail="The selected gateway/interface IP is already assigned to a peer."
                        )
                    updates["gateway_ip"] = new_gateway_ip

            if not updates:
                return _vpn_decorate(current)

            assignments = ", ".join(name + " = ?" for name in updates)
            values = list(updates.values()) + [network_id]
            db.execute(
                "UPDATE vpn_networks SET " + assignments
                + ", updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values
            )

            _vpn_log(
                db, request, "VPN network updated", "network", network_id,
                details={"fields": sorted(updates)}
            )
            row = db.execute(
                "SELECT * FROM vpn_networks WHERE id = ?", (network_id,)
            ).fetchone()
            return _vpn_decorate(row)

    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(
            409, detail="Network name or CIDR conflicts with an existing record."
        ) from exc


@app.delete("/api/vpn/networks/{network_id}")
def vpn_delete_network(network_id: str, request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        _vpn_get_network(db, network_id)
        refs = db.execute("""
            SELECT
                (SELECT COUNT(*) FROM vpn_peers WHERE assigned_network_id = ?) +
                (SELECT COUNT(*) FROM vpn_access_policies WHERE source_network_id = ?)
        """, (network_id, network_id)).fetchone()[0]
        if refs:
            raise _VPNHTTPException(409, detail="Move peer/policy references before deleting this network.")
        db.execute("DELETE FROM vpn_networks WHERE id = ?", (network_id,))
        _vpn_log(db, request, "VPN network deleted", "network", network_id)
    return {"deleted": True, "id": network_id,
            "message": "Network record deleted; no firewall change was applied."}


# ---------- Gateways ----------

@app.get("/api/vpn/gateways")
def vpn_list_gateways(request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        rows = db.execute("""
            SELECT * FROM vpn_gateways ORDER BY name COLLATE NOCASE
        """).fetchall()
        return [_vpn_decorate(row) for row in rows]


@app.post("/api/vpn/gateways", status_code=201)
def vpn_create_gateway(request: _VPNRequest, payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    name = _vpn_text(payload.get("name"), "Name", 120, True)
    protocol = "Cartman VPN"
    endpoint = _vpn_text(payload.get("endpoint"), "Endpoint", 255)
    region = _vpn_text(payload.get("region"), "Region", 120)
    description = _vpn_text(payload.get("description"), "Description", 1200)
    public_key = _vpn_text(payload.get("public_key"), "Public key", 128)
    port = payload.get("listen_port", 0)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise _VPNHTTPException(
                422,
                detail="Listen port must be 0 (not configured) or between 1 and 65535."
            )

    gateway_id = _vpn_new_id("vpn-gateway")
    try:
        with get_connection() as db:
            db.execute("""
                INSERT INTO vpn_gateways
                    (id, name, endpoint, region, protocol, listen_port,
                     public_key, description)
                VALUES (?, ?, ?, ?, 'Cartman VPN', ?, ?, ?)
            """, (gateway_id, name, endpoint, region, port, public_key, description))
            _vpn_log(db, request, "VPN gateway registered", "gateway", gateway_id,
                     details={"name": name, "protocol": protocol, "endpoint": endpoint})
            row = db.execute("SELECT * FROM vpn_gateways WHERE id = ?", (gateway_id,)).fetchone()
        return _vpn_decorate(row)
    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(409, detail="A gateway with this name already exists.") from exc


@app.put("/api/vpn/gateways/{gateway_id}")
def vpn_update_gateway(gateway_id: str, request: _VPNRequest,
                       payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    allowed = {"name", "endpoint", "region", "listen_port", "public_key", "description"}
    if not payload or set(payload) - allowed:
        raise _VPNHTTPException(422, detail="Unsupported gateway fields.")
    updates = {}
    for field, max_len in (("name", 120), ("endpoint", 255), ("region", 120),
                           ("public_key", 128), ("description", 1200)):
        if field in payload:
            updates[field] = _vpn_text(payload[field], field, max_len, field == "name")
    if "listen_port" in payload:
        port = payload["listen_port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise _VPNHTTPException(422, detail="Listen port must be between 1 and 65535.")
        updates["listen_port"] = port

    try:
        with get_connection() as db:
            if db.execute("SELECT 1 FROM vpn_gateways WHERE id = ?", (gateway_id,)).fetchone() is None:
                raise _VPNHTTPException(404, detail="Gateway not found.")
            assignments = ", ".join(field + " = ?" for field in updates)
            db.execute("UPDATE vpn_gateways SET " + assignments +
                       ", updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                       list(updates.values()) + [gateway_id])
            _vpn_log(db, request, "VPN gateway updated", "gateway", gateway_id,
                     details={"fields": sorted(updates)})
            return _vpn_decorate(db.execute(
                "SELECT * FROM vpn_gateways WHERE id = ?", (gateway_id,)
            ).fetchone())
    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(409, detail="Gateway name already exists.") from exc


@app.delete("/api/vpn/gateways/{gateway_id}")
def vpn_delete_gateway(gateway_id: str, request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        if db.execute("SELECT 1 FROM vpn_gateways WHERE id = ?", (gateway_id,)).fetchone() is None:
            raise _VPNHTTPException(404, detail="Gateway not found.")
        refs = db.execute("""
            SELECT
                (SELECT COUNT(*) FROM vpn_peers WHERE gateway_id = ?) +
                (SELECT COUNT(*) FROM vpn_site_links WHERE gateway_a_id = ? OR gateway_b_id = ?)
        """, (gateway_id, gateway_id, gateway_id)).fetchone()[0]
        if refs:
            raise _VPNHTTPException(409, detail="Move peer/site-to-site references before deleting this gateway.")
        db.execute("DELETE FROM vpn_gateways WHERE id = ?", (gateway_id,))
        _vpn_log(db, request, "VPN gateway deleted", "gateway", gateway_id)
    return {"deleted": True, "id": gateway_id,
            "message": "Gateway record deleted; no remote tunnel was changed."}


# ---------- Peers and managed clients ----------

@app.get("/api/vpn/peers")
def vpn_list_peers(request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        rows = db.execute("""
            SELECT p.*, n.name AS network_name, n.cidr AS network_cidr,
                   g.name AS gateway_name
            FROM vpn_peers AS p
            LEFT JOIN vpn_networks AS n ON n.id = p.assigned_network_id
            LEFT JOIN vpn_gateways AS g ON g.id = p.gateway_id
            ORDER BY p.created_at DESC, p.rowid DESC
            LIMIT 1000
        """).fetchall()
        return [_vpn_decorate(row, "peer") for row in rows]


@app.post("/api/vpn/peers", status_code=201)
def vpn_create_peer(request: _VPNRequest, payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    device_name = _vpn_text(payload.get("device_name"), "Device name", 180, True)
    cartman_id = _vpn_text(payload.get("cartman_id"), "Cartman ID", 255)
    username = _vpn_text(payload.get("username"), "Username", 180)
    display_name = _vpn_text(payload.get("display_name"), "Display name", 180)
    device_os = _vpn_text(payload.get("device_os", "Unknown"), "Operating system", 120)
    source_ip = _vpn_text(payload.get("source_ip"), "Source IP", 80)
    public_key = _vpn_text(payload.get("public_key"), "Public key", 128)
    notes = _vpn_text(payload.get("notes"), "Notes", 1200)
    if not cartman_id and not username:
        raise _VPNHTTPException(422, detail="A Cartman ID or username is required.")
    if source_ip:
        try:
            _vpn_ipaddress.ip_address(source_ip)
        except ValueError as exc:
            raise _VPNHTTPException(422, detail="Source IP is invalid.") from exc

    gateway_id = payload.get("gateway_id") or None
    peer_id = _vpn_new_id("vpn-peer")
    with get_connection() as db:
        if gateway_id and db.execute(
            "SELECT 1 FROM vpn_gateways WHERE id = ?", (gateway_id,)
        ).fetchone() is None:
            raise _VPNHTTPException(404, detail="Gateway not found.")

        quarantine_network = _vpn_get_quarantine_network(db)
        network_id = quarantine_network["id"]
        assigned_ip = _vpn_allocate_ip(db, network_id)

        db.execute("""
            INSERT INTO vpn_peers
                (id, cartman_id, username, display_name, device_name, device_os,
                 source_ip, public_key, assigned_ip, assigned_network_id, gateway_id,
                 authorization_status, tunnel_status, enforcement_state, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Quarantined',
                    'Not installed', 'Not applied', ?)
        """, (
            peer_id, cartman_id, username, display_name, device_name, device_os,
            source_ip, public_key, assigned_ip, network_id, gateway_id, notes,
        ))
        _vpn_log(db, request, "VPN peer placed in quarantine", "peer", peer_id,
                 outcome="Recorded; tunnel not configured", severity="Warning",
                 details={"device_name": device_name, "assigned_ip": assigned_ip})
        row = db.execute("SELECT * FROM vpn_peers WHERE id = ?", (peer_id,)).fetchone()

    result = _vpn_decorate(row, "peer")
    result["message"] = (
        "Peer record saved and assigned to the quarantine pool. "
        "No VPN tunnel or firewall rule has been applied."
    )
    return result


@app.put("/api/vpn/peers/{peer_id}")
def vpn_update_peer(peer_id: str, request: _VPNRequest,
                    payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    allowed = {"cartman_id", "username", "display_name", "device_name",
               "device_os", "source_ip", "public_key", "gateway_id", "notes"}
    if not payload or set(payload) - allowed:
        raise _VPNHTTPException(
            422,
            detail="Peer updates can change identity/metadata only. Use the decision endpoint for authorization or network assignment."
        )
    updates = {}
    limits = {
        "cartman_id": 255, "username": 180, "display_name": 180,
        "device_name": 180, "device_os": 120, "source_ip": 80,
        "public_key": 128, "notes": 1200
    }
    for field, maximum in limits.items():
        if field in payload:
            updates[field] = _vpn_text(payload[field], field, maximum)
    if "source_ip" in updates and updates["source_ip"]:
        try:
            _vpn_ipaddress.ip_address(updates["source_ip"])
        except ValueError as exc:
            raise _VPNHTTPException(422, detail="Source IP is invalid.") from exc
    if "gateway_id" in payload:
        gateway_id = payload["gateway_id"] or None
        if gateway_id and not isinstance(gateway_id, str):
            raise _VPNHTTPException(422, detail="Gateway ID is invalid.")
        if gateway_id:
            with get_connection() as db:
                if db.execute("SELECT 1 FROM vpn_gateways WHERE id = ?", (gateway_id,)).fetchone() is None:
                    raise _VPNHTTPException(404, detail="Gateway not found.")
        updates["gateway_id"] = gateway_id

    with get_connection() as db:
        if db.execute("SELECT 1 FROM vpn_peers WHERE id = ?", (peer_id,)).fetchone() is None:
            raise _VPNHTTPException(404, detail="Peer not found.")
        assignments = ", ".join(field + " = ?" for field in updates)
        db.execute("UPDATE vpn_peers SET " + assignments +
                   ", updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   list(updates.values()) + [peer_id])
        _vpn_log(db, request, "VPN peer metadata updated", "peer", peer_id,
                 details={"fields": sorted(updates)})
        row = db.execute("SELECT * FROM vpn_peers WHERE id = ?", (peer_id,)).fetchone()
    return _vpn_decorate(row, "peer")


@app.post("/api/vpn/peers/{peer_id}/decision")
def vpn_peer_decision(peer_id: str, request: _VPNRequest,
                      payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    decision = payload.get("decision")
    if decision not in {"approve", "quarantine", "block"}:
        raise _VPNHTTPException(422, detail="Decision must be approve, quarantine or block.")

    with get_connection() as db:
        peer = db.execute("SELECT * FROM vpn_peers WHERE id = ?", (peer_id,)).fetchone()
        if peer is None:
            raise _VPNHTTPException(404, detail="Peer not found.")

        if decision == "approve":
            network_id = payload.get("network_id")
            if not isinstance(network_id, str) or not network_id:
                raise _VPNHTTPException(422, detail="Choose a department network before approving this peer.")
            network = _vpn_get_network(db, network_id)
            if network["network_type"] != "Department" or not network["enabled"]:
                raise _VPNHTTPException(422, detail="Approved peers must be assigned to an enabled Department network.")
            if peer["assigned_network_id"] != network_id:
                assigned_ip = _vpn_allocate_ip(db, network_id)
            else:
                assigned_ip = peer["assigned_ip"]
            status = "Approved"
            approved_by = _vpn_actor(request)
            approved_at_sql = "CURRENT_TIMESTAMP"
            db.execute("""
                UPDATE vpn_peers
                SET authorization_status = ?, assigned_network_id = ?,
                    assigned_ip = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP, enforcement_state = 'Not applied'
                WHERE id = ?
            """, (status, network_id, assigned_ip, approved_by, peer_id))
        elif decision == "quarantine":
            quarantine_network = _vpn_get_quarantine_network(db)
            network_id = quarantine_network["id"]
            assigned_ip = (
                peer["assigned_ip"]
                if peer["assigned_network_id"] == network_id and peer["assigned_ip"]
                else _vpn_allocate_ip(db, network_id)
            )
            status = "Quarantined"
            db.execute("""
                UPDATE vpn_peers
                SET authorization_status = ?, assigned_network_id = ?,
                    assigned_ip = ?, approved_by = '', approved_at = NULL,
                    updated_at = CURRENT_TIMESTAMP, enforcement_state = 'Not applied'
                WHERE id = ?
            """, (status, network_id, assigned_ip, peer_id))
        else:
            status = "Blocked"
            assigned_ip = peer["assigned_ip"]
            db.execute("""
                UPDATE vpn_peers
                SET authorization_status = 'Blocked',
                    updated_at = CURRENT_TIMESTAMP, enforcement_state = 'Not applied'
                WHERE id = ?
            """, (peer_id,))

        _vpn_log(db, request, "VPN peer decision: " + decision, "peer", peer_id,
                 outcome="Recorded; VPN engine not installed", severity="Warning",
                 details={"status": status, "assigned_ip": assigned_ip,
                          "network_id": payload.get("network_id")})
        row = db.execute("""
            SELECT p.*, n.name AS network_name, n.cidr AS network_cidr
            FROM vpn_peers p
            LEFT JOIN vpn_networks n ON n.id = p.assigned_network_id
            WHERE p.id = ?
        """, (peer_id,)).fetchone()

    result = _vpn_decorate(row, "peer")
    result["message"] = (
        "Authorization decision saved. It has NOT been applied to live VPN/firewall traffic "
        "because the VPN engine is not installed."
    )
    return result


# ---------- Access policies ----------

@app.get("/api/vpn/access-policies")
def vpn_list_policies(request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        rows = db.execute("""
            SELECT p.*, n.name AS source_network_name, n.cidr AS source_network_cidr
            FROM vpn_access_policies p
            LEFT JOIN vpn_networks n ON n.id = p.source_network_id
            ORDER BY p.priority ASC, p.name COLLATE NOCASE
        """).fetchall()
        return [_vpn_decorate(row) for row in rows]


def _vpn_policy_values(payload, current=None):
    current = current or {}
    def get(key, default=""):
        return payload[key] if key in payload else current.get(key, default)

    name = _vpn_text(get("name"), "Name", 120, True)
    subject_type = get("subject_type", "All")
    if subject_type not in _VPN_SUBJECT_TYPES:
        raise _VPNHTTPException(422, detail="Unsupported policy subject type.")
    action = get("action", "Deny")
    if action not in _VPN_POLICY_ACTIONS:
        raise _VPNHTTPException(422, detail="Policy action must be Allow or Deny.")
    enabled = _vpn_bool(get("enabled", False), "enabled")
    priority = get("priority", 100)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 100000:
        raise _VPNHTTPException(422, detail="Priority must be between 1 and 100000.")
    source_network_id = get("source_network_id") or None
    destination = _vpn_text(get("destination"), "Destination", 255)
    protocol = _vpn_text(get("protocol", "Any"), "Protocol", 24)
    if protocol not in {"Any", "TCP", "UDP", "ICMP"}:
        raise _VPNHTTPException(422, detail="Protocol must be Any, TCP, UDP or ICMP.")
    ports = _vpn_text(get("ports"), "Ports", 300)
    if ports and not _vpn_re.fullmatch(r"[0-9,\-\s]+", ports):
        raise _VPNHTTPException(422, detail="Ports may contain only numbers, commas, spaces and hyphens.")
    description = _vpn_text(get("description"), "Description", 1200)
    return (name, subject_type,
            _vpn_text(get("subject_value"), "Subject", 255),
            source_network_id, destination, protocol, ports, action, priority,
            int(enabled), description)


@app.post("/api/vpn/access-policies", status_code=201)
def vpn_create_policy(request: _VPNRequest, payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    policy_id = _vpn_new_id("vpn-policy")
    values = _vpn_policy_values(payload)
    try:
        with get_connection() as db:
            if values[3]:
                _vpn_get_network(db, values[3])
            db.execute("""
                INSERT INTO vpn_access_policies
                    (id, name, subject_type, subject_value, source_network_id,
                     destination, protocol, ports, action, priority, enabled,
                     description, enforcement_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Not applied')
            """, (policy_id,) + values)
            _vpn_log(db, request, "VPN access policy created", "policy", policy_id,
                     outcome="Saved; not enforced", details={"name": values[0], "action": values[7]})
            row = db.execute("SELECT * FROM vpn_access_policies WHERE id = ?", (policy_id,)).fetchone()
        result = _vpn_decorate(row)
        result["message"] = "Policy saved but not enforced: the VPN engine is not installed."
        return result
    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(409, detail="Policy name already exists or a referenced network is invalid.") from exc


@app.put("/api/vpn/access-policies/{policy_id}")
def vpn_update_policy(policy_id: str, request: _VPNRequest,
                      payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    allowed = {"name", "subject_type", "subject_value", "source_network_id",
               "destination", "protocol", "ports", "action", "priority",
               "enabled", "description"}
    if not payload or set(payload) - allowed:
        raise _VPNHTTPException(422, detail="Unsupported policy fields.")
    try:
        with get_connection() as db:
            current = db.execute("SELECT * FROM vpn_access_policies WHERE id = ?", (policy_id,)).fetchone()
            if current is None:
                raise _VPNHTTPException(404, detail="Policy not found.")
            values = _vpn_policy_values(payload, dict(current))
            if values[3]:
                _vpn_get_network(db, values[3])
            db.execute("""
                UPDATE vpn_access_policies
                SET name=?, subject_type=?, subject_value=?, source_network_id=?,
                    destination=?, protocol=?, ports=?, action=?, priority=?,
                    enabled=?, description=?, enforcement_state='Not applied',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, values + (policy_id,))
            _vpn_log(db, request, "VPN access policy updated", "policy", policy_id,
                     outcome="Saved; not enforced", details={"fields": sorted(payload)})
            row = db.execute("SELECT * FROM vpn_access_policies WHERE id = ?", (policy_id,)).fetchone()
            result = _vpn_decorate(row)
            result["message"] = "Policy saved but not enforced: the VPN engine is not installed."
            return result
    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(409, detail="Policy name or network reference conflicts with an existing record.") from exc


@app.delete("/api/vpn/access-policies/{policy_id}")
def vpn_delete_policy(policy_id: str, request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        if db.execute("SELECT 1 FROM vpn_access_policies WHERE id = ?", (policy_id,)).fetchone() is None:
            raise _VPNHTTPException(404, detail="Policy not found.")
        db.execute("DELETE FROM vpn_access_policies WHERE id = ?", (policy_id,))
        _vpn_log(db, request, "VPN access policy deleted", "policy", policy_id)
    return {"deleted": True, "id": policy_id,
            "message": "Policy record deleted; no live firewall rule was changed."}


# ---------- Site-to-site definitions ----------

@app.get("/api/vpn/site-to-site")
def vpn_list_site_links(request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        rows = db.execute("""
            SELECT s.*, a.name AS gateway_a_name, b.name AS gateway_b_name
            FROM vpn_site_links s
            LEFT JOIN vpn_gateways a ON a.id = s.gateway_a_id
            LEFT JOIN vpn_gateways b ON b.id = s.gateway_b_id
            ORDER BY s.created_at DESC, s.rowid DESC
        """).fetchall()
        return [_vpn_decorate(row) for row in rows]


@app.post("/api/vpn/site-to-site", status_code=201)
def vpn_create_site_link(request: _VPNRequest, payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    name = _vpn_text(payload.get("name"), "Name", 120, True)
    gateway_a_id = payload.get("gateway_a_id")
    gateway_b_id = payload.get("gateway_b_id")
    local_subnet = _vpn_cidr(payload.get("local_subnet"), "Local subnet")
    remote_subnet = _vpn_cidr(payload.get("remote_subnet"), "Remote subnet")
    if local_subnet.overlaps(remote_subnet):
        raise _VPNHTTPException(422, detail="Local and remote subnets must not overlap.")
    description = _vpn_text(payload.get("description"), "Description", 1200)
    link_id = _vpn_new_id("vpn-site-link")

    try:
        with get_connection() as db:
            if not gateway_a_id or not gateway_b_id or gateway_a_id == gateway_b_id:
                raise _VPNHTTPException(422, detail="Choose two different gateways.")
            for gateway_id in (gateway_a_id, gateway_b_id):
                if db.execute("SELECT 1 FROM vpn_gateways WHERE id = ?", (gateway_id,)).fetchone() is None:
                    raise _VPNHTTPException(404, detail="A selected gateway was not found.")
            db.execute("""
                INSERT INTO vpn_site_links
                    (id, name, gateway_a_id, gateway_b_id,
                     local_subnet, remote_subnet, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (link_id, name, gateway_a_id, gateway_b_id,
                  str(local_subnet), str(remote_subnet), description))
            _vpn_log(db, request, "VPN site-to-site definition created", "site-to-site", link_id,
                     outcome="Draft saved; tunnel not configured",
                     details={"local_subnet": str(local_subnet), "remote_subnet": str(remote_subnet)})
            row = db.execute("SELECT * FROM vpn_site_links WHERE id = ?", (link_id,)).fetchone()
        result = _vpn_decorate(row)
        result["message"] = "Site-to-site definition saved as Draft; no tunnel was established."
        return result
    except sqlite3.IntegrityError as exc:
        raise _VPNHTTPException(409, detail="A site-to-site definition with this name already exists.") from exc


@app.put("/api/vpn/site-to-site/{link_id}")
def vpn_update_site_link(link_id: str, request: _VPNRequest,
                         payload: dict = _VPNBody(...)):
    _vpn_require_operator(request)
    allowed = {"name", "gateway_a_id", "gateway_b_id",
               "local_subnet", "remote_subnet", "description"}
    if not payload or set(payload) - allowed:
        raise _VPNHTTPException(422, detail="Unsupported site-to-site fields.")
    with get_connection() as db:
        current = db.execute("SELECT * FROM vpn_site_links WHERE id = ?", (link_id,)).fetchone()
        if current is None:
            raise _VPNHTTPException(404, detail="Site-to-site definition not found.")
        current = dict(current)
        data = dict(current)
        data.update(payload)
        name = _vpn_text(data["name"], "Name", 120, True)
        ga, gb = data["gateway_a_id"], data["gateway_b_id"]
        if not ga or not gb or ga == gb:
            raise _VPNHTTPException(422, detail="Choose two different gateways.")
        for gateway_id in (ga, gb):
            if db.execute("SELECT 1 FROM vpn_gateways WHERE id = ?", (gateway_id,)).fetchone() is None:
                raise _VPNHTTPException(404, detail="A selected gateway was not found.")
        local_subnet = _vpn_cidr(data["local_subnet"], "Local subnet")
        remote_subnet = _vpn_cidr(data["remote_subnet"], "Remote subnet")
        if local_subnet.overlaps(remote_subnet):
            raise _VPNHTTPException(422, detail="Local and remote subnets must not overlap.")
        description = _vpn_text(data["description"], "Description", 1200)
        db.execute("""
            UPDATE vpn_site_links SET name=?, gateway_a_id=?, gateway_b_id=?,
                local_subnet=?, remote_subnet=?, description=?,
                status='Draft', enforcement_state='Not applied',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (name, ga, gb, str(local_subnet), str(remote_subnet), description, link_id))
        _vpn_log(db, request, "VPN site-to-site definition updated", "site-to-site", link_id,
                 outcome="Draft saved; tunnel not configured",
                 details={"fields": sorted(payload)})
        row = db.execute("SELECT * FROM vpn_site_links WHERE id = ?", (link_id,)).fetchone()
        result = _vpn_decorate(row)
        result["message"] = "Site-to-site definition saved as Draft; no tunnel was established."
        return result


@app.delete("/api/vpn/site-to-site/{link_id}")
def vpn_delete_site_link(link_id: str, request: _VPNRequest):
    _vpn_require_operator(request)
    with get_connection() as db:
        if db.execute("SELECT 1 FROM vpn_site_links WHERE id = ?", (link_id,)).fetchone() is None:
            raise _VPNHTTPException(404, detail="Site-to-site definition not found.")
        db.execute("DELETE FROM vpn_site_links WHERE id = ?", (link_id,))
        _vpn_log(db, request, "VPN site-to-site definition deleted", "site-to-site", link_id)
    return {"deleted": True, "id": link_id,
            "message": "Definition removed; no live tunnel was changed."}


# ---------- Audit ----------

@app.get("/api/vpn/audit-logs")
def vpn_list_audit_logs(request: _VPNRequest, limit: int = 200):
    _vpn_require_operator(request)
    if not 1 <= limit <= 500:
        raise _VPNHTTPException(422, detail="Limit must be between 1 and 500.")
    with get_connection() as db:
        rows = db.execute("""
            SELECT * FROM vpn_audit_logs
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
        """, (limit,)).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = _vpn_json.loads(item.pop("details_json") or "{}")
        except (TypeError, ValueError):
            item["details"] = {}
        result.append(item)
    return result


_vpn_initialize_schema()
# END CARTMAN_VPN_CONTROL_PLANE_V1
# ---------------------------------------------------------------------------
# Ticketing API (Cartman 0.2e groundwork)
# Kept separate from the existing device-task subsystem.
# ---------------------------------------------------------------------------

TICKET_TYPES = {"Incident", "Request", "Problem", "Change"}
TICKET_PRIORITIES = {"Critical", "High", "Normal", "Low"}
TICKET_STATUSES = {"Open", "In progress", "Pending", "Waiting for requester", "Resolved", "Closed"}
TICKET_PREFIXES = {"Incident": "INC", "Request": "REQ", "Problem": "PRB", "Change": "CHG"}



# CARTMAN_KNOWLEDGE_BASE_API_V1
import json as _kb_json
import uuid as _kb_uuid


def _ensure_knowledge_base_schema():
    """Create persistent Knowledge Base tables and seed starter articles once."""
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'General',
                summary TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'Draft'
                    CHECK (status IN ('Draft', 'Published', 'Archived')),
                author_username TEXT NOT NULL DEFAULT '',
                drafted_by_username TEXT NOT NULL DEFAULT '',
                draft_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                published_at TEXT,
                deleted_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_status_category
                ON knowledge_articles(status, category, deleted_at);

            CREATE INDEX IF NOT EXISTS idx_knowledge_updated
                ON knowledge_articles(updated_at);

            CREATE TABLE IF NOT EXISTS knowledge_article_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                article_key TEXT NOT NULL,
                actor_username TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_audit_article
                ON knowledge_article_audit(article_id, id);
        """)

        # CARTMAN_KB_DRAFT_REASON_STORAGE_V1
        # Additive migration; existing article records are preserved.
        article_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(knowledge_articles)"
            ).fetchall()
        }

        if "drafted_by_username" not in article_columns:
            connection.execute(
                "ALTER TABLE knowledge_articles "
                "ADD COLUMN drafted_by_username TEXT NOT NULL DEFAULT ''"
            )

        if "draft_reason" not in article_columns:
            connection.execute(
                "ALTER TABLE knowledge_articles "
                "ADD COLUMN draft_reason TEXT NOT NULL DEFAULT ''"
            )

        connection.execute("""
            UPDATE knowledge_articles
            SET draft_reason = 'No reason recorded for this existing draft.'
            WHERE status = 'Draft' AND trim(draft_reason) = ''
        """)

        connection.execute("""
            UPDATE knowledge_articles
            SET drafted_by_username = author_username
            WHERE status = 'Draft' AND trim(drafted_by_username) = ''
        """)

        count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_articles"
        ).fetchone()[0]

        # Seed only a genuinely empty Knowledge Base; never overwrite user data.
        if count == 0:
            starter_articles = [
                (
                    "Troubleshoot VPN authentication failures",
                    "Networking",
                    "A practical checklist for client, gateway, DNS and identity-provider issues.",
                    [
                        "Confirm the user account is active and not locked.",
                        "Check device time and certificate validity.",
                        "Resolve the VPN gateway hostname and verify connectivity.",
                        "Review authentication logs and MFA challenges.",
                        "Capture timestamps and escalate with relevant logs if unresolved.",
                    ],
                    ["VPN", "Authentication"],
                ),
                (
                    "Investigate high disk usage on Windows servers",
                    "Windows",
                    "Find large directories, inspect event logs and reduce disk pressure safely.",
                    [
                        "Confirm the affected volume and current free space.",
                        "Use approved tools to identify large directories and files.",
                        "Check application logs, temporary files and retention settings.",
                        "Do not delete system or application data without owner approval.",
                        "Document the cleanup and monitor free space.",
                    ],
                    ["Storage", "Windows Server"],
                ),
                (
                    "DNS resolution troubleshooting",
                    "Networking",
                    "Check resolver configuration, records, cache and network reachability.",
                    [
                        "Verify the configured DNS servers.",
                        "Query the hostname against the configured resolver.",
                        "Compare with an authoritative or known-good resolver.",
                        "Check record TTL, suffix search list and client cache.",
                        "Record the failing hostname, resolver and timestamps.",
                    ],
                    ["DNS", "Networking"],
                ),
                (
                    "Account lockout investigation",
                    "Identity",
                    "Trace repeated lockouts across endpoints, services and saved credentials.",
                    [
                        "Confirm the account and lockout timestamp.",
                        "Review identity-provider or domain controller security logs.",
                        "Check scheduled tasks, services and stored credentials.",
                        "Validate the user's active sessions and enrolled devices.",
                        "Document the source before resetting credentials.",
                    ],
                    ["Identity", "Account"],
                ),
                (
                    "Diagnose a Linux service that will not start",
                    "Linux",
                    "A systemd-focused checklist for failed units and dependency issues.",
                    [
                        "Inspect the unit state and recent journal entries.",
                        "Check configuration syntax and file permissions.",
                        "Verify required ports, paths and dependent services.",
                        "Apply the smallest safe correction and restart the unit.",
                        "Confirm service health and capture the root cause.",
                    ],
                    ["Linux", "systemd"],
                ),
            ]

            for title, category, summary, steps, tags in starter_articles:
                temporary_key = "TMP-" + _kb_uuid.uuid4().hex
                content = "\n".join(
                    "{}. {}".format(index, step)
                    for index, step in enumerate(steps, 1)
                )

                cursor = connection.execute("""
                    INSERT INTO knowledge_articles (
                        article_key, title, category, summary, content,
                        tags_json, status, author_username, published_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'Published', 'system',
                            CURRENT_TIMESTAMP)
                """, (
                    temporary_key, title, category, summary, content,
                    _kb_json.dumps(tags, ensure_ascii=False),
                ))

                article_id = cursor.lastrowid
                connection.execute("""
                    UPDATE knowledge_articles
                    SET article_key = ?
                    WHERE id = ?
                """, ("KB-{:04d}".format(article_id), article_id))


def _knowledge_article_dict(row):
    item = dict(row)
    raw_tags = item.pop("tags_json", "[]")
    try:
        tags = _kb_json.loads(raw_tags or "[]")
    except (TypeError, ValueError):
        tags = []
    item["tags"] = tags if isinstance(tags, list) else []
    return item


def _knowledge_current_user(request):
    return getattr(request.state, "auth_user", {}) or {}


def _knowledge_require_admin(request):
    user = _knowledge_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only Cartman administrators may manage Knowledge Base articles.",
        )
    return user


def _knowledge_audit(connection, article_id, article_key, actor, action, details=None):
    connection.execute("""
        INSERT INTO knowledge_article_audit (
            article_id, article_key, actor_username, action, details_json
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        article_id,
        article_key,
        str(actor or ""),
        action,
        _kb_json.dumps(details or {}, ensure_ascii=False),
    ))


def _knowledge_validate_payload(payload, current=None):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Article data must be an object.")

    allowed = {"title", "category", "summary", "content", "tags", "status", "draft_reason"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(
            status_code=422,
            detail="Unsupported article fields: " + ", ".join(sorted(unknown)),
        )

    current = current or {}
    values = {
        "title": current.get("title", ""),
        "category": current.get("category", "General"),
        "summary": current.get("summary", ""),
        "content": current.get("content", ""),
        "tags": current.get("tags", []),
        "status": current.get("status", "Published"),
        "draft_reason": current.get("draft_reason", ""),
    }
    for key in allowed:
        if key in payload:
            values[key] = payload[key]

    values["title"] = str(values["title"] or "").strip()
    values["category"] = str(values["category"] or "").strip()
    values["summary"] = str(values["summary"] or "").strip()
    values["content"] = str(values["content"] or "").strip()
    values["status"] = str(values["status"] or "Published").strip()
    values["draft_reason"] = str(values["draft_reason"] or "").strip()

    if not 3 <= len(values["title"]) <= 180:
        raise HTTPException(status_code=422, detail="Title must be 3-180 characters.")
    if not 1 <= len(values["category"]) <= 80:
        raise HTTPException(status_code=422, detail="Category must be 1-80 characters.")
    if len(values["summary"]) > 600:
        raise HTTPException(status_code=422, detail="Summary cannot exceed 600 characters.")
    if not values["content"] or len(values["content"]) > 50000:
        raise HTTPException(
            status_code=422,
            detail="Article content must be 1-50000 characters.",
        )
    if values["status"] not in {"Draft", "Published", "Archived"}:
        raise HTTPException(
            status_code=422,
            detail="Status must be Draft, Published, or Archived.",
        )

    if len(values["draft_reason"]) > 1000:
        raise HTTPException(
            status_code=422,
            detail="Draft reason cannot exceed 1000 characters.",
        )

    if values["status"] == "Draft" and not values["draft_reason"]:
        raise HTTPException(
            status_code=422,
            detail="A reason is required when moving an article to Draft.",
        )

    raw_tags = values["tags"]
    if isinstance(raw_tags, str):
        tags = raw_tags.split(",")
    elif isinstance(raw_tags, list):
        tags = raw_tags
    else:
        raise HTTPException(status_code=422, detail="Tags must be text or a list.")

    cleaned_tags = []
    for tag in tags:
        tag = str(tag or "").strip()
        if tag and tag.casefold() not in {item.casefold() for item in cleaned_tags}:
            if len(tag) > 40:
                raise HTTPException(status_code=422, detail="Each tag must be 40 characters or fewer.")
            cleaned_tags.append(tag)

    if len(cleaned_tags) > 20:
        raise HTTPException(status_code=422, detail="An article may have at most 20 tags.")

    values["tags"] = cleaned_tags
    return values


_ensure_knowledge_base_schema()


@app.get("/api/knowledge/articles")
def list_knowledge_articles(
    request: Request,
    q: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    user = _knowledge_current_user(request)
    can_manage = user.get("role") == "admin"
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    if status and status not in {"Draft", "Published", "Archived"}:
        raise HTTPException(status_code=422, detail="Invalid article status.")

    conditions = ["deleted_at IS NULL"]
    params = []

    # Non-admin users can discover published content only.
    if not can_manage:
        conditions.append("status = 'Published'")

    if category and category.strip() and category.casefold() != "all":
        conditions.append("category = ? COLLATE NOCASE")
        params.append(category.strip())

    if can_manage and status:
        conditions.append("status = ?")
        params.append(status)

    if q and q.strip():
        needle = "%" + q.strip() + "%"
        conditions.append("""
            (article_key LIKE ? OR title LIKE ? OR category LIKE ?
             OR summary LIKE ? OR content LIKE ? OR tags_json LIKE ?)
        """)
        params.extend([needle] * 6)

    where_sql = " WHERE " + " AND ".join(conditions)

    visibility_conditions = ["deleted_at IS NULL"]
    if not can_manage:
        visibility_conditions.append("status = 'Published'")
    visibility_where = " WHERE " + " AND ".join(visibility_conditions)

    with get_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM knowledge_articles" + where_sql,
            params,
        ).fetchone()[0]

        rows = connection.execute(
            # CARTMAN_KB_CREATED_BY_COLUMN_V1
            "SELECT knowledge_articles.*, "
            "COALESCE((SELECT display_name FROM auth_accounts "
            "WHERE lower(username) = lower(knowledge_articles.author_username) "
            "LIMIT 1), knowledge_articles.author_username) AS author_name "
            "FROM knowledge_articles"
            + where_sql
            + " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        summary_row = connection.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status='Published' THEN 1 ELSE 0 END), 0) AS published,
                COALESCE(SUM(CASE WHEN status='Draft' THEN 1 ELSE 0 END), 0) AS draft,
                COALESCE(SUM(CASE WHEN status='Archived' THEN 1 ELSE 0 END), 0) AS archived
            FROM knowledge_articles
        """ + visibility_where).fetchone()

        categories = [
            row["category"]
            for row in connection.execute("""
                SELECT DISTINCT category FROM knowledge_articles
            """ + visibility_where + " ORDER BY category COLLATE NOCASE").fetchall()
        ]

    return {
        "items": [_knowledge_article_dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "categories": categories,
        "summary": dict(summary_row),
        "can_manage": can_manage,
    }


@app.get("/api/knowledge/articles/{article_key}")
def get_knowledge_article(article_key: str, request: Request):
    user = _knowledge_current_user(request)
    with get_connection() as connection:
        row = connection.execute("""
            SELECT * FROM knowledge_articles
            WHERE article_key = ? AND deleted_at IS NULL
        """, (article_key,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Article not found.")

        if user.get("role") != "admin" and row["status"] != "Published":
            raise HTTPException(status_code=404, detail="Article not found.")

        article = _knowledge_article_dict(row)
        article["attachments"] = _cartman_attachment_list("knowledge", article_key)
        return article


@app.post("/api/knowledge/articles", status_code=201)
def create_knowledge_article(payload: dict, request: Request):
    user = _knowledge_require_admin(request)
    create_payload = dict(payload)
    create_payload.pop("status", None)
    create_payload.pop("draft_reason", None)
    values = _knowledge_validate_payload(create_payload)
    values["status"] = "Published"
    values["draft_reason"] = ""

    with get_connection() as connection:
        temporary_key = "TMP-" + _kb_uuid.uuid4().hex
        cursor = connection.execute("""
            INSERT INTO knowledge_articles (
                article_key, title, category, summary, content, tags_json,
                status, author_username, published_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ?='Published' THEN CURRENT_TIMESTAMP ELSE NULL END)
        """, (
            temporary_key,
            values["title"],
            values["category"],
            values["summary"],
            values["content"],
            _kb_json.dumps(values["tags"], ensure_ascii=False),
            values["status"],
            user.get("username", ""),
            values["status"],
        ))

        article_id = cursor.lastrowid
        article_key = "KB-{:04d}".format(article_id)

        connection.execute("""
            UPDATE knowledge_articles
            SET article_key = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (article_key, article_id))

        _knowledge_audit(
            connection, article_id, article_key, user.get("username"),
            "Created", {"status": values["status"]},
        )
        row = connection.execute(
            "SELECT * FROM knowledge_articles WHERE id = ?", (article_id,)
        ).fetchone()

    return _knowledge_article_dict(row)


@app.put("/api/knowledge/articles/{article_key}")
def update_knowledge_article(article_key: str, payload: dict, request: Request):
    user = _knowledge_require_admin(request)

    with get_connection() as connection:
        existing = connection.execute("""
            SELECT * FROM knowledge_articles
            WHERE article_key = ? AND deleted_at IS NULL
        """, (article_key,)).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="Article not found.")

        current = _knowledge_article_dict(existing)
        values = _knowledge_validate_payload(payload, current)

        drafted_by_username = str(
            existing["drafted_by_username"] or existing["author_username"] or ""
        )

        if values["status"] == "Draft" and (
            existing["status"] != "Draft" or "draft_reason" in payload
        ):
            drafted_by_username = str(user.get("username") or "")

        connection.execute("""
            UPDATE knowledge_articles
            SET title = ?,
                category = ?,
                summary = ?,
                content = ?,
                tags_json = ?,
                draft_reason = ?,
                drafted_by_username = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP,
                published_at = CASE
                    WHEN ? = 'Published'
                    THEN COALESCE(published_at, CURRENT_TIMESTAMP)
                    ELSE published_at
                END
            WHERE id = ?
        """, (
            values["title"],
            values["category"],
            values["summary"],
            values["content"],
            _kb_json.dumps(values["tags"], ensure_ascii=False),
            values["draft_reason"],
            drafted_by_username,
            values["status"],
            values["status"],
            existing["id"],
        ))

        _knowledge_audit(
            connection, existing["id"], article_key, user.get("username"),
            "Updated", {"fields": sorted(payload.keys()), "status": values["status"], "draft_reason": values["draft_reason"] if values["status"] == "Draft" else ""},
        )
        row = connection.execute(
            "SELECT * FROM knowledge_articles WHERE id = ?", (existing["id"],)
        ).fetchone()

    return _knowledge_article_dict(row)


@app.delete("/api/knowledge/articles/{article_key}", status_code=204)
def delete_knowledge_article(article_key: str, request: Request):
    user = _knowledge_require_admin(request)

    with get_connection() as connection:
        row = connection.execute("""
            SELECT id, article_key FROM knowledge_articles
            WHERE article_key = ? AND deleted_at IS NULL
        """, (article_key,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Article not found.")

        connection.execute("""
            UPDATE knowledge_articles
            SET deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (row["id"],))

        _knowledge_audit(
            connection, row["id"], article_key, user.get("username"),
            "Soft deleted", {},
        )
    return None


def _ensure_ticketing_schema():
    """Create and safely migrate Cartman Ticketing tables."""
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_key TEXT UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                ticket_type TEXT NOT NULL DEFAULT 'Incident',
                priority TEXT NOT NULL DEFAULT 'Normal',
                status TEXT NOT NULL DEFAULT 'Open',
                requester TEXT NOT NULL DEFAULT 'Unspecified',
                requester_username TEXT NOT NULL DEFAULT '',
                requester_account_id TEXT NOT NULL DEFAULT '',
                created_by_username TEXT NOT NULL DEFAULT '',
                assigned_to TEXT NOT NULL DEFAULT 'Unassigned',
                assigned_to_username TEXT NOT NULL DEFAULT '',
                team TEXT NOT NULL DEFAULT 'L1 Queue',
                escalation_level TEXT NOT NULL DEFAULT 'L1',
                resolution TEXT NOT NULL DEFAULT '',
                awaiting_requester_since TEXT,
                requester_reply_due_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_status_priority
                ON tickets(status, priority);
            CREATE INDEX IF NOT EXISTS idx_tickets_created_at
                ON tickets(created_at DESC);
            CREATE TABLE IF NOT EXISTS ticket_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                author TEXT NOT NULL DEFAULT 'Cartman Administrator',
                author_username TEXT NOT NULL DEFAULT '',
                author_role TEXT NOT NULL DEFAULT 'support',
                body TEXT NOT NULL,
                is_internal INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_comments_ticket
                ON ticket_comments(ticket_id, created_at);
            CREATE TABLE IF NOT EXISTS ticket_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                field_name TEXT NOT NULL DEFAULT '',
                old_value TEXT NOT NULL DEFAULT '',
                new_value TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT 'Cartman Administrator',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_audit_ticket
                ON ticket_audit_events(ticket_id, created_at DESC);
        """)

        ticket_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(tickets)").fetchall()
        }
        ticket_migrations = {
            "escalation_level": "TEXT NOT NULL DEFAULT 'L1'",
            "requester_username": "TEXT NOT NULL DEFAULT ''",
            "requester_account_id": "TEXT NOT NULL DEFAULT ''",
            "created_by_username": "TEXT NOT NULL DEFAULT ''",
            "assigned_to_username": "TEXT NOT NULL DEFAULT ''",
            "awaiting_requester_since": "TEXT",
            "requester_reply_due_at": "TEXT",
        }
        for column, definition in ticket_migrations.items():
            if column not in ticket_columns:
                connection.execute(f"ALTER TABLE tickets ADD COLUMN {column} {definition}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_tickets_assignee_status ON tickets(assigned_to_username, status, deleted_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_tickets_requester_username ON tickets(requester_username, created_at DESC)")

        comment_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(ticket_comments)").fetchall()
        }
        comment_migrations = {
            "is_internal": "INTEGER NOT NULL DEFAULT 0",
            "author_username": "TEXT NOT NULL DEFAULT ''",
            "author_role": "TEXT NOT NULL DEFAULT 'support'",
        }
        for column, definition in comment_migrations.items():
            if column not in comment_columns:
                connection.execute(f"ALTER TABLE ticket_comments ADD COLUMN {column} {definition}")

        # Stable, type-independent public IDs: #1, #2, #1000, ...
        # Use each row's existing AUTOINCREMENT id, including soft-deleted rows;
        # IDs are intentionally never reused because audit history may refer to them.
        for item in connection.execute("SELECT id, ticket_key FROM tickets ORDER BY id").fetchall():
            expected_key = f"#{item['id']}"
            if item["ticket_key"] != expected_key:
                collision = connection.execute(
                    "SELECT id FROM tickets WHERE ticket_key = ? AND id <> ?",
                    (expected_key, item["id"]),
                ).fetchone()
                if collision:
                    raise RuntimeError(
                        f"Ticket ID migration collision for {expected_key}; no ticket rows were deleted."
                    )
                connection.execute(
                    "UPDATE tickets SET ticket_key = ? WHERE id = ?",
                    (expected_key, item["id"]),
                )

        # Backfill stable account names for earlier tickets when a match is available.
        connection.execute("""
            UPDATE tickets
            SET requester_username = COALESCE((
                SELECT a.username FROM auth_accounts a
                WHERE lower(a.username) = lower(tickets.requester)
                   OR lower(a.display_name) = lower(tickets.requester)
                ORDER BY CASE WHEN lower(a.username) = lower(tickets.requester) THEN 0 ELSE 1 END
                LIMIT 1
            ), requester_username)
            WHERE trim(requester_username) = ''
        """)
        connection.execute("""
            UPDATE tickets
            SET requester_account_id = COALESCE((
                SELECT a.id FROM auth_accounts a
                WHERE lower(a.username) = lower(tickets.requester_username)
                LIMIT 1
            ), requester_account_id)
            WHERE trim(requester_account_id) = '' AND trim(requester_username) <> ''
        """)
        connection.execute("""
            UPDATE tickets
            SET assigned_to_username = (
                SELECT u.username FROM iam_users u
                WHERE trim(u.username) <> ''
                  AND (lower(u.username) = lower(tickets.assigned_to)
                       OR lower(u.name) = lower(tickets.assigned_to))
                LIMIT 1
            )
            WHERE trim(assigned_to_username) = ''
              AND trim(assigned_to) <> '' AND lower(assigned_to) <> 'unassigned'
        """)



def _ticket_to_dict(row):
    item = dict(row)
    item["id"] = item.get("ticket_key") or str(item.get("id", ""))
    item["type"] = item.pop("ticket_type", "Incident")
    return item


def _ticket_audit(connection, ticket_id, action, field_name="", old_value="", new_value="", actor="Cartman Administrator"):
    connection.execute(
        """INSERT INTO ticket_audit_events
           (ticket_id, action, field_name, old_value, new_value, actor)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ticket_id, action, field_name, str(old_value or ""), str(new_value or ""), str(actor or "Cartman Administrator")),
    )


def _get_ticket_row(connection, ticket_key):
    return connection.execute(
        "SELECT * FROM tickets WHERE ticket_key = ? AND deleted_at IS NULL", (ticket_key,)
    ).fetchone()


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=10000)
    type: str = "Incident"
    priority: str = "Normal"
    requester: str = Field(default="Unspecified", max_length=160)
    assigned_to: str = Field(default="Unassigned", max_length=160)
    team: str = Field(default="Service Desk", max_length=160)


class TicketUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10000)
    type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    requester: Optional[str] = Field(default=None, max_length=160)
    assigned_to: Optional[str] = Field(default=None, max_length=160)
    team: Optional[str] = Field(default=None, max_length=160)
    escalation_level: Optional[str] = None
    resolution: Optional[str] = Field(default=None, max_length=10000)


class TicketCommentCreate(BaseModel):
    author: str = Field(default="Cartman Administrator", max_length=160)
    body: str = Field(..., min_length=1, max_length=10000)
    is_internal: bool = False


# Create the new tables at application import/startup; existing tables and rows are untouched.
_ensure_ticketing_schema()

# Persistent requester-response workflow. Deadlines live in SQLite, not browser timers.
_ticket_deadline_worker_lock = threading.Lock()
_ticket_deadline_worker_started = False
_ticket_deadline_worker_stop = threading.Event()


def _ticket_team_for_level(level):
    return {"L1": "L1 Support", "L2": "L2 Support", "L3": "L3 Engineering"}.get(level, f"{level} Queue")


def _ticket_select_agent(connection, level):
    """Choose the least-loaded online, active IAM agent with a matching login account."""
    return connection.execute("""
        SELECT u.id, u.name, u.username, u.email, u.department, u.support_level
        FROM iam_users u
        JOIN auth_accounts a
          ON lower(trim(a.username)) = lower(trim(u.username))
         AND a.is_active = 1
        WHERE u.status = 'Active'
          AND u.support_level = ?
          AND u.support_online = 1
          AND trim(u.username) <> ''
        ORDER BY (
            SELECT COUNT(*) FROM tickets t
            WHERE lower(t.assigned_to_username) = lower(u.username)
              AND t.deleted_at IS NULL
              AND t.status NOT IN ('Resolved', 'Closed', 'Waiting for requester', 'Pending')
        ) ASC,
        u.updated_at ASC, u.name COLLATE NOCASE ASC
        LIMIT 1
    """, (level,)).fetchone()


def _ticket_assign_waiting_queue(connection, level=None):
    """Assign queued tickets when an eligible support person comes online."""
    params = []
    sql = """SELECT id, ticket_key, escalation_level FROM tickets
             WHERE deleted_at IS NULL AND status = 'Pending'
               AND trim(assigned_to_username) = ''
               AND team = escalation_level || ' Queue'"""
    if level:
        sql += " AND escalation_level = ?"
        params.append(level)
    sql += " ORDER BY priority = 'Critical' DESC, priority = 'High' DESC, created_at ASC, id ASC"
    rows = connection.execute(sql, params).fetchall()
    assigned = 0
    for queued in rows:
        agent = _ticket_select_agent(connection, queued["escalation_level"])
        if agent is None:
            continue
        team = _ticket_team_for_level(queued["escalation_level"])
        connection.execute("""
            UPDATE tickets
            SET assigned_to = ?, assigned_to_username = ?, team = ?, status = 'Open',
                updated_at = CURRENT_TIMESTAMP, awaiting_requester_since = NULL,
                requester_reply_due_at = NULL
            WHERE id = ? AND deleted_at IS NULL AND status = 'Pending'
              AND trim(assigned_to_username) = ''
        """, (agent["name"], agent["username"], team, queued["id"]))
        _ticket_audit(
            connection, queued["id"], "Assigned from queue", "assigned_to",
            "Unassigned", agent["name"], "Cartman routing service"
        )
        _ticket_audit(
            connection, queued["id"], "Routing level", "escalation_level",
            "Queue", queued["escalation_level"], "Cartman routing service"
        )
        assigned += 1
    return assigned


def _ticket_assign_queued_for_level(level):
    with get_connection() as connection:
        return _ticket_assign_waiting_queue(connection, level)


def _ticket_process_due_reopens():
    """Reopen tickets after 24 hours without requester response; keep the same assignee."""
    with get_connection() as connection:
        due = connection.execute("""
            SELECT id, ticket_key, assigned_to, assigned_to_username
            FROM tickets
            WHERE deleted_at IS NULL
              AND status = 'Waiting for requester'
              AND requester_reply_due_at IS NOT NULL
              AND requester_reply_due_at <= CURRENT_TIMESTAMP
            ORDER BY requester_reply_due_at ASC
            LIMIT 500
        """).fetchall()
        for ticket in due:
            connection.execute("""
                UPDATE tickets
                SET status = 'Open', awaiting_requester_since = NULL,
                    requester_reply_due_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'Waiting for requester'
                  AND requester_reply_due_at <= CURRENT_TIMESTAMP
            """, (ticket["id"],))
            if connection.execute("SELECT changes() AS n").fetchone()["n"]:
                _ticket_audit(
                    connection, ticket["id"],
                    "Auto-reopened after 24 hours without requester response",
                    "status", "Waiting for requester", "Open",
                    "Cartman routing service"
                )


def _ticket_deadline_worker():
    while not _ticket_deadline_worker_stop.wait(30):
        try:
            _ticket_process_due_reopens()
        except Exception as exc:
            # Keep the app running; the next loop retries after transient DB issues.
            print(f"[Cartman Ticketing] deadline worker error: {exc}")


def _start_ticket_deadline_worker():
    global _ticket_deadline_worker_started
    with _ticket_deadline_worker_lock:
        if _ticket_deadline_worker_started:
            return
        _ticket_deadline_worker_started = True
        thread = threading.Thread(
            target=_ticket_deadline_worker,
            name="cartman-ticket-deadlines",
            daemon=True,
        )
        thread.start()


app.add_event_handler("startup", _start_ticket_deadline_worker)

# CARTMAN_PRIVATE_ATTACHMENTS_V1
ATTACHMENT_DIR = BASE_DIR / "private_attachments"
MAX_CARTMAN_ATTACHMENT_BYTES = 12 * 1024 * 1024
CARTMAN_ATTACHMENT_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".pdf", ".txt", ".log", ".csv", ".md", ".json",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
}


def _cartman_attachment_ensure_schema():
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(ATTACHMENT_DIR, 0o700)
    except OSError:
        pass
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cartman_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('ticket', 'knowledge')),
                entity_key TEXT NOT NULL,
                original_name TEXT NOT NULL,
                storage_name TEXT NOT NULL UNIQUE,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                uploaded_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at TEXT
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_cartman_attachments_entity
            ON cartman_attachments(entity_type, entity_key, deleted_at, id)
        """)


def _cartman_attachment_authorize(entity_type, entity_key, request, manage=False, write=False):
    _cartman_attachment_ensure_schema()
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    role = str(user.get("role") or "")
    username = str(user.get("username") or "").strip().casefold()

    if entity_type == "knowledge":
        if manage and role != "admin":
            raise HTTPException(status_code=403, detail="Only Cartman administrators may manage article attachments.")
        with get_connection() as connection:
            article = connection.execute("""
                SELECT article_key, status FROM knowledge_articles
                WHERE article_key = ? AND deleted_at IS NULL
            """, (entity_key,)).fetchone()
        if not article or (role != "admin" and article["status"] != "Published"):
            raise HTTPException(status_code=404, detail="Knowledge article not found.")
        return user

    if entity_type == "ticket":
        with get_connection() as connection:
            ticket = _get_ticket_row(connection, entity_key)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found.")
        if role == "admin":
            return user
        if role == "support_agent":
            assigned = str(ticket["assigned_to_username"] or "").strip().casefold()
            requester = str(ticket["requester_username"] or "").strip().casefold()
            if not username or username not in {assigned, requester}:
                raise HTTPException(status_code=404, detail="Ticket not found.")
        elif role == "read_only" and not write:
            requester = str(ticket["requester_username"] or "").strip().casefold()
            if not username or username != requester:
                raise HTTPException(status_code=404, detail="Ticket not found.")
        else:
            # Roles without ticket access must not gain it through an attachment URL.
            raise HTTPException(
                status_code=403 if write else 404,
                detail="Your role cannot access attachments for this ticket.",
            )
        if write and role not in {"admin", "support_agent"}:
            raise HTTPException(status_code=403, detail="Your role cannot upload or remove ticket attachments.")
        return user

    raise HTTPException(status_code=422, detail="Unsupported attachment target.")


def _cartman_attachment_list(entity_type, entity_key):
    _cartman_attachment_ensure_schema()
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, entity_type, entity_key, original_name, content_type,
                   size_bytes, uploaded_by, created_at
            FROM cartman_attachments
            WHERE entity_type = ? AND entity_key = ? AND deleted_at IS NULL
            ORDER BY id ASC
        """, (entity_type, entity_key)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["is_image"] = item["content_type"] in {
            "image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"
        }
        item["download_url"] = f"/api/attachments/file/{item['id']}"
        items.append(item)
    return items


def _cartman_attachment_filename(raw_name):
    decoded = urllib.parse.unquote(str(raw_name or ""))
    decoded = decoded.replace("\\", "/").split("/")[-1]
    decoded = "".join(ch for ch in decoded if ch >= " " and ch not in '\x7f"<>|')
    decoded = decoded.strip().strip(".")[:180]
    return decoded or "attachment"


@app.get("/api/attachments")
def cartman_list_attachments(entity_type: str, entity_key: str, request: Request):
    _cartman_attachment_authorize(entity_type, entity_key, request)
    return {"items": _cartman_attachment_list(entity_type, entity_key)}


@app.post("/api/attachments", status_code=201)
async def cartman_upload_attachment(entity_type: str, entity_key: str, request: Request):
    user = _cartman_attachment_authorize(entity_type, entity_key, request, manage=(entity_type == "knowledge"), write=True)
    filename = _cartman_attachment_filename(request.headers.get("x-filename"))
    suffix = Path(filename).suffix.lower()
    if suffix not in CARTMAN_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload a document, log, PDF, ZIP, or common image format.")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_CARTMAN_ATTACHMENT_BYTES:
                raise HTTPException(status_code=413, detail="Each attachment must be 12 MB or smaller.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.")

    storage_name = uuid.uuid4().hex
    temp_path = ATTACHMENT_DIR / (".upload-" + storage_name + ".part")
    final_path = ATTACHMENT_DIR / storage_name
    total = 0
    prefix = bytearray()
    try:
        with temp_path.open("wb") as output:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_CARTMAN_ATTACHMENT_BYTES:
                    raise HTTPException(status_code=413, detail="Each attachment must be 12 MB or smaller.")
                if len(prefix) < 32:
                    prefix.extend(chunk[:32 - len(prefix)])
                output.write(chunk)
        if total == 0:
            raise HTTPException(status_code=422, detail="The uploaded file is empty.")

        signatures = {
            ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
            ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
            ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
            ".webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
            ".gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
            ".bmp": lambda b: b.startswith(b"BM"),
            ".pdf": lambda b: b.startswith(b"%PDF-"),
        }
        if suffix in signatures and not signatures[suffix](bytes(prefix)):
            raise HTTPException(status_code=415, detail="The file contents do not match the filename type.")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, final_path)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with get_connection() as connection:
            cursor = connection.execute("""
                INSERT INTO cartman_attachments
                    (entity_type, entity_key, original_name, storage_name, content_type, size_bytes, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entity_type, entity_key, filename, storage_name, content_type,
                total, str(user.get("username") or ""),
            ))
            attachment_id = cursor.lastrowid
        return {
            "id": attachment_id, "entity_type": entity_type, "entity_key": entity_key,
            "original_name": filename, "content_type": content_type, "size_bytes": total,
            "uploaded_by": str(user.get("username") or ""),
            "is_image": content_type in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"},
            "download_url": f"/api/attachments/file/{attachment_id}",
        }
    except Exception:
        for path in (temp_path, final_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


@app.get("/api/attachments/file/{attachment_id}")
def cartman_download_attachment(attachment_id: int, request: Request, inline: bool = False):
    _cartman_attachment_ensure_schema()
    with get_connection() as connection:
        row = connection.execute("""
            SELECT * FROM cartman_attachments WHERE id = ? AND deleted_at IS NULL
        """, (attachment_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    _cartman_attachment_authorize(row["entity_type"], row["entity_key"], request)
    image_types = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}
    use_inline = bool(inline and row["content_type"] in image_types)
    disposition = "inline" if use_inline else "attachment"
    safe_name = urllib.parse.quote(row["original_name"], safe="")
    path = ATTACHMENT_DIR / row["storage_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored attachment file is missing.")
    return FileResponse(
        path,
        media_type=row["content_type"],
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{safe_name}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@app.delete("/api/attachments/{attachment_id}", status_code=204)
def cartman_delete_attachment(attachment_id: int, request: Request):
    _cartman_attachment_ensure_schema()
    with get_connection() as connection:
        row = connection.execute("""
            SELECT * FROM cartman_attachments WHERE id = ? AND deleted_at IS NULL
        """, (attachment_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    user = _cartman_attachment_authorize(row["entity_type"], row["entity_key"], request, manage=(row["entity_type"] == "knowledge"), write=True)
    if user.get("role") != "admin" and str(user.get("username") or "").casefold() != str(row["uploaded_by"] or "").casefold():
        raise HTTPException(status_code=403, detail="Only the uploader or an administrator may delete this attachment.")
    with get_connection() as connection:
        connection.execute("UPDATE cartman_attachments SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (attachment_id,))
    try:
        (ATTACHMENT_DIR / row["storage_name"]).unlink(missing_ok=True)
    except OSError:
        pass
    return None


# CARTMAN_WORK_ITEMS_API_V1
# General work-management tasks are intentionally separate from device command queues.
_WORK_ITEM_STATUSES = {"To do", "In progress", "Done"}
_WORK_ITEM_PRIORITIES = {"Low", "Normal", "High", "Critical"}


# CARTMAN_WORK_ITEM_AUTH_HELPERS_RECOVERY_V1

def _wm_user(request: Request) -> dict:
    """Return the authenticated Cartman account for this request.

    The work-management routes use the same existing /api/auth/me resolver as the UI.
    This intentionally does not infer identity from user-supplied headers.
    """
    import asyncio
    import inspect
    import json

    state = getattr(request, "state", None)
    for state_name in ("user", "current_user", "auth_user", "auth_account", "session_user"):
        candidate = getattr(state, state_name, None) if state is not None else None
        if isinstance(candidate, dict) and candidate.get("role") and candidate.get("username"):
            return candidate

    auth_route = next((
        route for route in app.routes
        if getattr(route, "path", None) == "/api/auth/me"
        and "GET" in (getattr(route, "methods", set()) or set())
    ), None)
    endpoint = getattr(auth_route, "endpoint", None) if auth_route else None
    if endpoint is None:
        raise HTTPException(status_code=401, detail="Authentication resolver unavailable.")

    try:
        signature = inspect.signature(endpoint)
        kwargs = {}
        for name, parameter in signature.parameters.items():
            if name in ("request", "req"):
                kwargs[name] = request
            elif parameter.default is inspect.Parameter.empty and parameter.kind not in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
            ):
                raise RuntimeError("Unsupported required parameter in /api/auth/me endpoint")
        result = endpoint(**kwargs)
        if inspect.isawaitable(result):
            result = asyncio.run(result)

        if hasattr(result, "status_code") and hasattr(result, "body"):
            if int(getattr(result, "status_code", 200)) >= 400:
                raise HTTPException(status_code=401, detail="Authentication required.")
            body = result.body
            if isinstance(body, bytes):
                result = json.loads(body.decode("utf-8"))
            elif isinstance(body, str):
                result = json.loads(body)

        if hasattr(result, "model_dump"):
            result = result.model_dump()
        elif hasattr(result, "dict") and not isinstance(result, dict):
            result = result.dict()

        if isinstance(result, dict):
            candidates = [result.get("user"), result.get("account"), result.get("current_user"), result]
            for candidate in candidates:
                if hasattr(candidate, "model_dump"):
                    candidate = candidate.model_dump()
                if isinstance(candidate, dict) and candidate.get("role") and candidate.get("username"):
                    return candidate
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Could not resolve the authenticated account.") from exc

    raise HTTPException(status_code=401, detail="Authentication required.")


def _wm_require_admin(request: Request) -> dict:
    """Require an authenticated administrator for work-management administration APIs."""
    user = _wm_user(request)
    if str(user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user

def _ensure_work_items_schema():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS work_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT 'Operations',
                owner TEXT NOT NULL DEFAULT 'Unassigned',
                due TEXT NOT NULL DEFAULT 'Unscheduled',
                status TEXT NOT NULL DEFAULT 'To do'
                    CHECK (status IN ('To do', 'In progress', 'Review', 'Done')),
                priority TEXT NOT NULL DEFAULT 'Normal'
                    CHECK (priority IN ('Low', 'Normal', 'High', 'Critical')),
                created_by_username TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(work_items)"
            ).fetchall()
        }
        for column, definition in (
            ("assigned_user_id", "TEXT NOT NULL DEFAULT ''"),
            ("completed_at", "TEXT"),
            ("completed_by_username", "TEXT NOT NULL DEFAULT ''"),
            ("completion_description", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE work_items ADD COLUMN {column} {definition}"
                )
                columns.add(column)

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_items_status_updated "
            "ON work_items(status, updated_at DESC)"
        )
        # Preserve the existing starter board when the new persistent table is first created.
        existing = connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0]
        if existing == 0:
            starter_items = [
                ("TSK-021", "Review server patch compliance", "", "Infrastructure", "Alex Morgan", "Today", "In progress", "High"),
                ("TSK-022", "Validate backup restore procedure", "", "Resilience", "Sam Rivera", "Tomorrow", "To do", "High"),
                ("TSK-023", "Update VPN troubleshooting runbook", "", "Knowledge", "Jordan Lee", "Oct 26", "To do", "Normal"),
                ("TSK-024", "Audit inactive endpoint agents", "", "Endpoints", "Taylor Kim", "Oct 27", "Review", "Normal"),
                ("TSK-025", "Document DNS change window", "", "Network", "Alex Morgan", "Oct 24", "Done", "Low"),
                ("TSK-026", "Check disk alerts on file servers", "", "Infrastructure", "Sam Rivera", "Today", "In progress", "High"),
            ]
            connection.executemany("""
                INSERT INTO work_items
                    (task_key, title, description, project, owner, due, status, priority, created_by_username)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'system')
            """, starter_items)


def _work_item_dict(row):
    item = dict(row)
    database_id = item.get("id")
    item["display_key"] = (
        "T{}".format(database_id)
        if database_id is not None
        else str(item.get("task_key") or "")
    )
    # Preserve the existing identifier used by API routes and related records.
    item["id"] = item["task_key"]
    return item


def _work_item_text(payload, field, default, maximum, required=False):
    value = payload.get(field, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise HTTPException(status_code=422, detail=f"{field} is required.")
    if len(value) > maximum:
        raise HTTPException(status_code=422, detail=f"{field} must be at most {maximum} characters.")
    return value



def _wm_find_online_work_item_assignee(connection, target_type, target_id):
    """Pick one active target user with a recently active Cartman session."""
    target_id = str(target_id or "").strip()
    if not target_id:
        return None

    extra_condition = ""
    params = []

    if target_type == "user":
        extra_condition = " AND CAST(u.id AS TEXT) = ?"
        params.append(target_id)

    elif target_type == "department":
        department = connection.execute(
            "SELECT name FROM departments WHERE CAST(id AS TEXT) = ?",
            (target_id,),
        ).fetchone()
        if not department:
            return None
        extra_condition = (
            " AND lower(trim(u.department)) = lower(trim(?))"
        )
        params.append(department["name"])

    elif target_type == "group":
        extra_condition = """
            AND EXISTS (
                SELECT 1
                FROM iam_group_members gm
                JOIN iam_groups ig ON ig.id = gm.group_id
                WHERE gm.user_id = u.id
                  AND CAST(ig.id AS TEXT) = ?
                  AND ig.status = 'Active'
            )
        """
        params.append(target_id)

    else:
        return None

    sql = """
        SELECT u.id, u.name, u.username
        FROM iam_users u
        JOIN auth_accounts a
          ON lower(trim(a.username)) = lower(trim(u.username))
         AND a.is_active = 1
        WHERE u.status = 'Active'
          AND trim(u.username) <> ''
          AND EXISTS (
              SELECT 1
              FROM auth_sessions s
              WHERE s.account_id = a.id
                AND COALESCE(s.revoked, 0) = 0
                AND CAST(s.expires_at AS INTEGER) > CAST(strftime('%s', 'now') AS INTEGER)
                AND CAST(s.last_seen AS INTEGER) >= CAST(strftime('%s', 'now') AS INTEGER) - 300
          )
    """ + extra_condition + """
        ORDER BY (
            SELECT COUNT(*)
            FROM work_items wi
            WHERE wi.assigned_user_id = CAST(u.id AS TEXT)
              AND wi.status = 'In progress'
        ) ASC,
        u.updated_at ASC,
        u.name COLLATE NOCASE ASC
        LIMIT 1
    """

    return connection.execute(sql, params).fetchone()


def _wm_reconcile_work_item_assignments(connection, task_key=None):
    """Reconcile open target-based work items against recent live sessions."""

    # Older starter-board items without an IAM target cannot claim to be
    # actively assigned. Preserve the records, but return them to the queue.
    connection.execute("""
        UPDATE work_items
        SET status = 'To do',
            owner = 'Unassigned',
            assigned_user_id = '',
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('In progress', 'Review')
          AND task_key NOT IN (
              SELECT task_key FROM work_item_targets
          )
    """)

    # Preserve old completed records and backfill their missing close time.
    connection.execute("""
        UPDATE work_items
        SET completed_at = COALESCE(
            completed_at, updated_at, created_at, CURRENT_TIMESTAMP
        )
        WHERE status = 'Done'
          AND (completed_at IS NULL OR trim(completed_at) = '')
    """)

    sql = """
        SELECT
            wi.task_key, wi.status, wi.owner, wi.assigned_user_id,
            wt.target_type, wt.target_id
        FROM work_items wi
        JOIN work_item_targets wt ON wt.task_key = wi.task_key
        WHERE wi.status <> 'Done'
    """
    params = []
    if task_key:
        sql += " AND wi.task_key = ?"
        params.append(task_key)

    rows = connection.execute(sql, params).fetchall()

    for item in rows:
        candidate = _wm_find_online_work_item_assignee(
            connection, item["target_type"], item["target_id"]
        )

        if candidate:
            assigned_id = str(candidate["id"])
            assigned_name = str(
                candidate["name"] or candidate["username"] or "Unassigned"
            )[:120]

            if (
                item["status"] != "In progress"
                or str(item["assigned_user_id"] or "") != assigned_id
                or item["owner"] != assigned_name
            ):
                connection.execute("""
                    UPDATE work_items
                    SET status = 'In progress',
                        owner = ?,
                        assigned_user_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE task_key = ? AND status <> 'Done'
                """, (assigned_name, assigned_id, item["task_key"]))

        else:
            # A direct user target stays queued for that user while offline.
            # The task remains To do, but is still visible in that user's list.
            if item["target_type"] == "user":
                queued_user = connection.execute("""
                    SELECT u.id, u.name, u.username
                    FROM iam_users u
                    JOIN auth_accounts a
                      ON lower(trim(a.username)) = lower(trim(u.username))
                     AND a.is_active = 1
                    WHERE CAST(u.id AS TEXT) = ?
                      AND u.status = 'Active'
                    LIMIT 1
                """, (str(item["target_id"]),)).fetchone()

                if queued_user:
                    queued_id = str(queued_user["id"])
                    queued_owner = str(
                        queued_user["name"] or queued_user["username"] or "Unassigned"
                    )[:120]

                    if (
                        item["status"] != "To do"
                        or item["owner"] != queued_owner
                        or str(item["assigned_user_id"] or "") != queued_id
                    ):
                        connection.execute("""
                            UPDATE work_items
                            SET status = 'To do',
                                owner = ?,
                                assigned_user_id = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE task_key = ? AND status <> 'Done'
                        """, (queued_owner, queued_id, item["task_key"]))

                    continue

            # Department/group targets without an eligible online user stay
            # in the unassigned queue until a suitable member comes online.
            if (
                item["status"] != "To do"
                or item["owner"] != "Unassigned"
                or str(item["assigned_user_id"] or "")
            ):
                connection.execute("""
                    UPDATE work_items
                    SET status = 'To do',
                        owner = 'Unassigned',
                        assigned_user_id = '',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE task_key = ? AND status <> 'Done'
                """, (item["task_key"],))




_ensure_work_items_schema()


@app.get("/api/work-items")
def list_work_items(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
):
    user = _wm_user(request)
    role = str(user.get("role") or "").strip().lower()
    if role not in ("admin", "support_agent"):
        raise HTTPException(status_code=403, detail="You may not access work items.")

    limit = max(1, min(int(limit or 500), 500))
    offset = max(0, int(offset or 0))
    clauses = []
    params = []
    assigned_iam_id = ""

    with get_connection() as connection:
        # Keep assignment status synchronized with authenticated session presence.
        _wm_reconcile_work_item_assignments(connection)

        if role == "support_agent":
            username = str(user.get("username") or "").strip()
            account_id = str(user.get("id") or "").strip()
            iam_user = connection.execute("""
                SELECT u.id
                FROM iam_users u
                JOIN auth_accounts a
                  ON lower(trim(a.username)) = lower(trim(u.username))
                WHERE lower(trim(u.username)) = lower(trim(?))
                  AND CAST(a.id AS TEXT) = ?
                  AND a.is_active = 1
                  AND u.status = 'Active'
                LIMIT 1
            """, (username, account_id)).fetchone()
            if not iam_user:
                # Never fall back to demo/starter tasks if identity linking is missing.
                return {"items": [], "total": 0, "limit": limit, "offset": offset}
            assigned_iam_id = str(iam_user["id"])
            clauses.append("COALESCE(CAST(w.assigned_user_id AS TEXT), '') = ?")
            params.append(assigned_iam_id)

        query = str(q or "").strip().lower()
        if query:
            clauses.append("(" + " OR ".join(
                "lower(COALESCE(w." + column + ", '')) LIKE ?"
                for column in ("task_key", "title", "description", "project", "owner", "priority", "status", "due")
            ) + ")")
            params.extend([f"%{query}%"] * 8)
        if status:
            clauses.append("w.status = ?")
            params.append(str(status).strip())
        if priority:
            clauses.append("w.priority = ?")
            params.append(str(priority).strip())

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = int(connection.execute(
            "SELECT COUNT(*) FROM work_items w" + where_sql, params
        ).fetchone()[0])
        rows = connection.execute(
            "SELECT w.* FROM work_items w" + where_sql +
            " ORDER BY w.updated_at DESC, w.id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        items = []
        for row in rows:
            item = _work_item_dict(row)
            if role == "support_agent":
                # Defense in depth: only the concrete assignment is visible/completable.
                if str(item.get("assigned_user_id") or "") != assigned_iam_id:
                    continue
                item["can_complete"] = item.get("status") == "In progress"
            else:
                item["can_complete"] = item.get("status") != "Done"
            items.append(item)

    # Return the data envelope used by the Tasks UI. total counts only permitted rows.
    if role == "support_agent":
        total = len(items) if offset == 0 and total < limit else total
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.post("/api/work-items", status_code=201)
def create_work_item(payload: dict, request: Request):
    user = _wm_require_admin(request)
    title = _work_item_text(payload, "title", "", 200, required=True)
    if len(title) < 3:
        raise HTTPException(status_code=422, detail="title must be at least 3 characters.")
    description = _work_item_text(payload, "description", "", 5000)
    project = _work_item_text(payload, "project", "Operations", 80) or "Operations"
    owner = "Unassigned"
    due = _work_item_text(payload, "due", "Unscheduled", 40) or "Unscheduled"
    if "status" in payload:
        raise HTTPException(
            status_code=400,
            detail="Task status is controlled by Cartman; use Complete to close a task.",
        )
    status = "To do"
    priority = _work_item_text(payload, "priority", "Normal", 20) or "Normal"
    if priority not in _WORK_ITEM_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid work-item priority.")
    if not payload.get("target_type") or not payload.get("target_id"):
        raise HTTPException(
            status_code=422,
            detail="Choose a User, Department, or Group target.",
        )
    with get_connection() as connection:
        target = _wm_resolve_automation_target(
            connection, payload.get("target_type"), payload.get("target_id")
        )
        cursor = connection.execute("""
            INSERT INTO work_items
                (task_key, title, description, project, owner, due, status, priority, created_by_username)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "TMP-" + uuid.uuid4().hex, title, description, project, owner, due,
            status, priority, str(user.get("username") or ""),
        ))
        item_id = cursor.lastrowid
        task_key = "T{}".format(item_id)
        connection.execute("UPDATE work_items SET task_key = ? WHERE id = ?", (task_key, item_id))
        if target:
            connection.execute(
                "INSERT OR REPLACE INTO work_item_targets (task_key, target_type, target_id, target_name) VALUES (?, ?, ?, ?)",
                (task_key, target["target_type"], target["target_id"], target["target_name"]),
            )
        _wm_reconcile_work_item_assignments(connection, task_key)
        row = connection.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
    result = _work_item_dict(row)
    if target:
        result.update({"target_type": target["target_type"], "target_id": target["target_id"], "target_name": target["target_name"]})
    return result


@app.put("/api/work-items/{task_key}")
def update_work_item(task_key: str, payload: dict, request: Request):
    _wm_require_admin(request)
    allowed_fields = {"title", "description", "project", "due", "priority"}
    supplied = set(payload.keys())
    if not supplied or not supplied.issubset(allowed_fields):
        raise HTTPException(status_code=400, detail="Provide one or more supported work-item fields.")
    with get_connection() as connection:
        current = connection.execute("SELECT * FROM work_items WHERE task_key = ?", (task_key,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Work item not found.")
        values = {key: current[key] for key in allowed_fields}
        limits = {"title": 200, "description": 5000, "project": 80, "due": 40, "priority": 20}
        for key in supplied:
            values[key] = _work_item_text(payload, key, values[key], limits[key], required=(key == "title"))
        if len(values["title"]) < 3:
            raise HTTPException(status_code=422, detail="title must be at least 3 characters.")
        if values["priority"] not in _WORK_ITEM_PRIORITIES:
            raise HTTPException(status_code=422, detail="Invalid work-item priority.")
        columns = sorted(supplied)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        connection.execute(
            f"UPDATE work_items SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[column] for column in columns] + [current["id"]],
        )
        row = connection.execute("SELECT * FROM work_items WHERE id = ?", (current["id"],)).fetchone()
    return _work_item_dict(row)


@app.post("/api/work-items/{task_key}/complete")
def complete_work_item(task_key: str, payload: dict, request: Request):
    user = _wm_user(request)
    is_admin = user.get("role") == "admin"
    if not is_admin and user.get("role") != "support_agent":
        raise HTTPException(status_code=403, detail="You may not complete this task.")

    completion_description = str(payload.get("completion_description") or "").strip()
    if len(completion_description) < 3:
        raise HTTPException(
            status_code=422,
            detail="Describe your actions in at least 3 characters.",
        )
    if len(completion_description) > 3000:
        raise HTTPException(
            status_code=422,
            detail="Completion description must be 3000 characters or fewer.",
        )

    with get_connection() as connection:
        current = connection.execute(
            "SELECT * FROM work_items WHERE task_key = ?", (task_key,)
        ).fetchone()

        if not current:
            raise HTTPException(status_code=404, detail="Work item not found.")

        if not is_admin:
            username = str(user.get("username") or "").strip()
            own = connection.execute("""
                SELECT u.id
                FROM iam_users u
                JOIN auth_accounts a
                  ON lower(trim(a.username)) = lower(trim(u.username))
                WHERE lower(trim(u.username)) = lower(trim(?))
                  AND a.id = ? AND a.is_active = 1
                  AND u.status = 'Active'
                LIMIT 1
            """, (username, user.get("id"))).fetchone()

            if (
                not own
                or str(current["assigned_user_id"] or "") != str(own["id"])
            ):
                raise HTTPException(
                    status_code=403,
                    detail="You may complete only a task assigned to your account.",
                )

            if current["status"] != "In progress":
                raise HTTPException(
                    status_code=409,
                    detail="Only an assigned task in progress can be completed.",
                )

        if current["status"] != "Done":
            connection.execute("""
                UPDATE work_items
                SET status = 'Done',
                    completed_at = CURRENT_TIMESTAMP,
                    completed_by_username = ?,
                    completion_description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_key = ? AND status <> 'Done'
            """, (str(user.get("username") or ""), completion_description, task_key))

        row = connection.execute(
            "SELECT * FROM work_items WHERE task_key = ?", (task_key,)
        ).fetchone()

    return _work_item_dict(row)


# CARTMAN_WORKFLOWS_REAL_API_V1
# Persistent, allow-listed workflow engine. It never evaluates arbitrary code.
import json as _cartman_wf_json
import uuid as _cartman_wf_uuid
import time as _cartman_wf_time
import threading as _cartman_wf_threading

_CARTMAN_WF_TRIGGERS = {"manual", "interval", "event"}
_CARTMAN_WF_EVENTS = {"monitoring.new_alert", "monitoring.critical_alert"}
_CARTMAN_WF_ACTIONS = {"condition", "create_task", "notify_user"}
_CARTMAN_WF_PRIORITIES = {"Low", "Normal", "High", "Critical"}
_CARTMAN_WF_SEVERITIES = {"info", "success", "warning", "critical"}
_CARTMAN_WF_STATUSES = {"To do", "In progress", "Review", "Done"}


def _cartman_wf_ensure_schema():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cartman_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL DEFAULT 'manual',
                trigger_event TEXT NOT NULL DEFAULT '',
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                enabled INTEGER NOT NULL DEFAULT 0,
                steps_json TEXT NOT NULL DEFAULT '[]',
                event_cursor_id INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT,
                created_by_username TEXT NOT NULL DEFAULT '',
                updated_by_username TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_archived INTEGER NOT NULL DEFAULT 0
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cartman_workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                workflow_name TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Running',
                input_json TEXT NOT NULL DEFAULT '{}',
                steps_json TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                started_by_username TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                UNIQUE(workflow_id, trigger_key)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cartman_workflow_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_username TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info',
                source TEXT NOT NULL DEFAULT 'Workflows',
                action_url TEXT NOT NULL DEFAULT '/pages/notifications/',
                workflow_id INTEGER,
                workflow_run_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_workflows_enabled ON cartman_workflows(enabled, trigger_type, is_archived)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_wf_runs_recent ON cartman_workflow_runs(workflow_id, started_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_wf_notifications_recipient ON cartman_workflow_notifications(recipient_username, id DESC)")
        # Idempotent forward migration in case an early version of these tables exists.
        wf_columns = {row["name"] for row in connection.execute("PRAGMA table_info(cartman_workflows)").fetchall()}
        for column, definition in (("event_cursor_id", "INTEGER NOT NULL DEFAULT 0"), ("next_run_at", "TEXT"), ("is_archived", "INTEGER NOT NULL DEFAULT 0")):
            if column not in wf_columns:
                connection.execute("ALTER TABLE cartman_workflows ADD COLUMN " + column + " " + definition)


def _cartman_wf_require_user(request):
    user = getattr(request.state, "auth_user", None) or {}
    if not user or not user.get("username"):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _cartman_wf_require_admin(request):
    user = _cartman_wf_require_user(request)
    if str(user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only an administrator may manage workflows.")
    return user


def _cartman_wf_load_json(value, fallback):
    try:
        return _cartman_wf_json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _cartman_wf_public_workflow(row):
    item = dict(row)
    item["steps"] = _cartman_wf_load_json(item.pop("steps_json", "[]"), [])
    item["enabled"] = bool(item.get("enabled"))
    item["is_archived"] = bool(item.get("is_archived"))
    return item


def _cartman_wf_public_run(row):
    item = dict(row)
    item["steps"] = _cartman_wf_load_json(item.pop("steps_json", "[]"), [])
    item["input"] = _cartman_wf_load_json(item.pop("input_json", "{}"), {})
    return item


def _cartman_wf_text(value, field, maximum, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=field + " must be text.")
    value = value.strip()
    if required and not value:
        raise HTTPException(status_code=422, detail=field + " is required.")
    if len(value) > maximum:
        raise HTTPException(status_code=422, detail=field + " must be at most " + str(maximum) + " characters.")
    return value


def _cartman_wf_normalize_steps(raw_steps):
    if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > 20:
        raise HTTPException(status_code=422, detail="A workflow must contain 1 to 20 steps.")
    result = []
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="Step " + str(index) + " must be an object.")
        kind = str(raw.get("type") or "").strip().lower()
        if kind not in _CARTMAN_WF_ACTIONS:
            raise HTTPException(status_code=422, detail="Unsupported action on step " + str(index) + ".")
        step = {"type": kind}
        if kind == "condition":
            step["field"] = _cartman_wf_text(raw.get("field", "alert.severity"), "Condition field", 120, True)
            if any(not part or part.startswith("_") for part in step["field"].split(".")):
                raise HTTPException(status_code=422, detail="Condition field path is invalid.")
            operator = str(raw.get("operator") or "equals").strip().lower()
            if operator not in {"equals", "not_equals", "contains", "greater_than", "less_than", "exists"}:
                raise HTTPException(status_code=422, detail="Unsupported condition operator.")
            step["operator"] = operator
            step["value"] = _cartman_wf_text(str(raw.get("value") or ""), "Condition value", 300)
        elif kind == "create_task":
            step["title"] = _cartman_wf_text(raw.get("title"), "Task title", 200, True)
            if len(step["title"]) < 3:
                raise HTTPException(status_code=422, detail="Task title must be at least 3 characters.")
            step["description"] = _cartman_wf_text(raw.get("description"), "Task description", 5000)
            step["project"] = _cartman_wf_text(raw.get("project") or "Operations", "Project", 80) or "Operations"
            step["due"] = _cartman_wf_text(raw.get("due") or "Unscheduled", "Due date", 40) or "Unscheduled"
            step["priority"] = str(raw.get("priority") or "Normal").strip()
            if step["priority"] not in _CARTMAN_WF_PRIORITIES:
                raise HTTPException(status_code=422, detail="Task priority is invalid.")
            step["assigned_username"] = _cartman_wf_text(raw.get("assigned_username"), "Assigned username", 120)
        elif kind == "notify_user":
            step["recipient_username"] = _cartman_wf_text(raw.get("recipient_username"), "Notification recipient username", 120, True)
            step["title"] = _cartman_wf_text(raw.get("title"), "Notification title", 180, True)
            step["message"] = _cartman_wf_text(raw.get("message"), "Notification message", 1200, True)
            step["severity"] = str(raw.get("severity") or "info").strip().lower()
            if step["severity"] not in _CARTMAN_WF_SEVERITIES:
                raise HTTPException(status_code=422, detail="Notification severity is invalid.")
            action_url = _cartman_wf_text(raw.get("action_url") or "/pages/notifications/", "Notification link", 300)
            if not action_url.startswith("/") or action_url.startswith("//"):
                raise HTTPException(status_code=422, detail="Notification link must be a local Cartman path.")
            step["action_url"] = action_url
        result.append(step)
    return result


def _cartman_wf_normalize_payload(payload, existing=None):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Workflow payload must be an object.")
    existing = existing or {}
    name = _cartman_wf_text(payload.get("name", existing.get("name", "")), "Name", 120, True)
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="Workflow name must be at least 3 characters.")
    description = _cartman_wf_text(payload.get("description", existing.get("description", "")), "Description", 2000)
    trigger_type = str(payload.get("trigger_type", existing.get("trigger_type", "manual")) or "manual").strip().lower()
    if trigger_type not in _CARTMAN_WF_TRIGGERS:
        raise HTTPException(status_code=422, detail="Trigger must be manual, interval, or event.")
    trigger_event = str(payload.get("trigger_event", existing.get("trigger_event", "")) or "").strip()
    if trigger_type == "event" and trigger_event not in _CARTMAN_WF_EVENTS:
        raise HTTPException(status_code=422, detail="Choose a supported Monitoring event.")
    interval = payload.get("interval_minutes", existing.get("interval_minutes", 60))
    try:
        interval = int(interval or 60)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Interval must be a whole number of minutes.")
    if trigger_type == "interval" and not 1 <= interval <= 10080:
        raise HTTPException(status_code=422, detail="Interval must be between 1 minute and 7 days.")
    raw_steps = payload.get("steps", existing.get("steps", []))
    steps = _cartman_wf_normalize_steps(raw_steps)
    enabled = bool(payload.get("enabled", existing.get("enabled", False)))
    return {"name": name, "description": description, "trigger_type": trigger_type,
            "trigger_event": trigger_event if trigger_type == "event" else "",
            "interval_minutes": interval, "steps": steps, "enabled": enabled}


def _cartman_wf_get_path(value, field):
    current = value
    for part in str(field or "").split("."):
        if not part or part.startswith("_"):
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _cartman_wf_condition_passes(step, event_data):
    actual = _cartman_wf_get_path(event_data, step.get("field", ""))
    expected = str(step.get("value") or "")
    operator = step.get("operator") or "equals"
    if operator == "exists":
        return actual is not None and str(actual) != ""
    if operator == "equals":
        return str(actual if actual is not None else "").casefold() == expected.casefold()
    if operator == "not_equals":
        return str(actual if actual is not None else "").casefold() != expected.casefold()
    if operator == "contains":
        return expected.casefold() in str(actual if actual is not None else "").casefold()
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    return left > right if operator == "greater_than" else left < right if operator == "less_than" else False


def _cartman_wf_execute_step(connection, workflow, run_id, step, event_data, actor):
    kind = step["type"]
    if kind == "condition":
        passed = _cartman_wf_condition_passes(step, event_data)
        return {"passed": passed, "message": "Condition passed." if passed else "Condition did not match; remaining steps were skipped."}, passed
    if kind == "create_task":
        assigned_id = ""
        owner = "Unassigned"
        assigned_username = str(step.get("assigned_username") or "").strip()
        if assigned_username:
            assigned = connection.execute("""
                SELECT a.username, a.display_name, u.id AS iam_user_id, u.display_name AS iam_display_name
                FROM auth_accounts a
                LEFT JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username)) AND u.status='Active'
                WHERE lower(trim(a.username))=lower(trim(?)) AND a.is_active=1
                LIMIT 1
            """, (assigned_username,)).fetchone()
            if not assigned or not assigned["iam_user_id"]:
                raise ValueError("Assigned username must have an active, linked IAM user.")
            assigned_id = str(assigned["iam_user_id"])
            owner = str(assigned["iam_display_name"] or assigned["display_name"] or assigned["username"])
        task_key = "WF-" + _cartman_wf_uuid.uuid4().hex[:10].upper()
        connection.execute("""
            INSERT INTO work_items (task_key, title, description, project, owner, due, status, priority,
                                   created_by_username, assigned_user_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'To do', ?, ?, ?, CURRENT_TIMESTAMP)
        """, (task_key, step["title"], step.get("description", ""), step.get("project", "Operations"),
              owner, step.get("due", "Unscheduled"), step.get("priority", "Normal"),
              actor or ("workflow:" + str(workflow["id"])), assigned_id))
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_item_targets'").fetchone()
        if assigned_id and table:
            connection.execute("INSERT OR REPLACE INTO work_item_targets (task_key, target_type, target_id, target_name) VALUES (?, 'user', ?, ?)",
                               (task_key, assigned_id, owner))
        return {"task_key": task_key, "title": step["title"], "assigned_username": assigned_username or None}, True
    if kind == "notify_user":
        recipient = str(step.get("recipient_username") or "").strip()
        account = connection.execute("SELECT username FROM auth_accounts WHERE lower(trim(username))=lower(trim(?)) AND is_active=1 LIMIT 1", (recipient,)).fetchone()
        if not account:
            raise ValueError("Notification recipient is not an active Cartman account.")
        connection.execute("""
            INSERT INTO cartman_workflow_notifications
                (recipient_username, title, message, severity, source, action_url, workflow_id, workflow_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (account["username"], step["title"], step["message"], step.get("severity", "info"),
              "Workflow · " + str(workflow["name"]), step.get("action_url", "/pages/notifications/"),
              workflow["id"], run_id))
        notification_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"notification_id": notification_id, "recipient_username": account["username"], "title": step["title"]}, True
    raise ValueError("Unsupported workflow step action.")


def _cartman_wf_execute(workflow_id, trigger_source, trigger_key, event_data=None, actor_username=""):
    event_data = event_data if isinstance(event_data, dict) else {}
    with get_connection() as connection:
        workflow = connection.execute("SELECT * FROM cartman_workflows WHERE id=? AND is_archived=0", (int(workflow_id),)).fetchone()
        if not workflow:
            raise ValueError("Workflow not found or archived.")
        try:
            cursor = connection.execute("""
                INSERT INTO cartman_workflow_runs
                    (workflow_id, workflow_name, trigger_source, trigger_key, status, input_json, started_by_username)
                VALUES (?, ?, ?, ?, 'Running', ?, ?)
            """, (workflow["id"], workflow["name"], str(trigger_source), str(trigger_key),
                  _cartman_wf_json.dumps(event_data, ensure_ascii=False), str(actor_username or "")))
            run_id = cursor.lastrowid
        except Exception as exc:
            existing = connection.execute("SELECT * FROM cartman_workflow_runs WHERE workflow_id=? AND trigger_key=?", (workflow_id, str(trigger_key))).fetchone()
            if existing:
                return _cartman_wf_public_run(existing)
            raise exc
        steps = _cartman_wf_load_json(workflow["steps_json"], [])
        results = []
        status = "Succeeded"
        summary = "All workflow steps completed."
        error_message = ""
        for index, step in enumerate(steps, 1):
            record = {"index": index, "type": step.get("type", "unknown"), "status": "Running", "result": None, "error": ""}
            try:
                result, passed = _cartman_wf_execute_step(connection, workflow, run_id, step, event_data, actor_username)
                record["result"] = result
                record["status"] = "Succeeded" if passed else "Condition not met"
                results.append(record)
                if step.get("type") == "condition" and not passed:
                    status = "Skipped"
                    summary = "A condition did not match; remaining steps were skipped."
                    break
            except Exception as exc:
                record["status"] = "Failed"
                record["error"] = str(exc)[:1000]
                results.append(record)
                status = "Failed"
                summary = "Workflow stopped because a step failed."
                error_message = "Step " + str(index) + " (" + str(step.get("type", "unknown")) + "): " + str(exc)[:1000]
                break
        if not steps:
            status = "Failed"
            summary = "Workflow contains no steps."
            error_message = summary
        connection.execute("""
            UPDATE cartman_workflow_runs SET status=?, steps_json=?, summary=?, error_message=?, finished_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (status, _cartman_wf_json.dumps(results, ensure_ascii=False), summary, error_message, run_id))
        connection.execute("UPDATE cartman_workflows SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (workflow["id"],))
        result_row = connection.execute("SELECT * FROM cartman_workflow_runs WHERE id=?", (run_id,)).fetchone()
        return _cartman_wf_public_run(result_row)


def _cartman_wf_scheduler_tick():
    jobs = []
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM cartman_workflows WHERE enabled=1 AND is_archived=0 AND trigger_type IN ('interval','event') ORDER BY id").fetchall()
        for workflow in rows:
            if workflow["trigger_type"] == "interval":
                next_run = workflow["next_run_at"]
                due = connection.execute("SELECT CASE WHEN ? IS NULL OR ? <= CURRENT_TIMESTAMP THEN 1 ELSE 0 END", (next_run, next_run)).fetchone()[0]
                if due:
                    trigger_key = "interval:" + str(next_run or workflow["created_at"] or "first")
                    minutes = max(1, min(int(workflow["interval_minutes"] or 60), 10080))
                    connection.execute("UPDATE cartman_workflows SET next_run_at=datetime('now', ?), updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                       ("+" + str(minutes) + " minutes", workflow["id"]))
                    jobs.append((workflow["id"], "interval", trigger_key, {"trigger": {"type": "interval", "workflow_id": workflow["id"]}}))
            elif workflow["trigger_type"] == "event":
                try:
                    alerts = connection.execute("""
                        SELECT id, device_id, title, severity, status, details, created_at, acknowledged_at, resolved_at
                        FROM monitoring_alerts WHERE id > ? ORDER BY id ASC LIMIT 200
                    """, (int(workflow["event_cursor_id"] or 0),)).fetchall()
                except Exception:
                    alerts = []
                if alerts:
                    max_id = max(int(row["id"]) for row in alerts)
                    connection.execute("UPDATE cartman_workflows SET event_cursor_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (max_id, workflow["id"]))
                    for alert_row in alerts:
                        alert = dict(alert_row)
                        severity = str(alert.get("severity") or "").lower()
                        if workflow["trigger_event"] == "monitoring.critical_alert" and severity not in {"critical", "error"}:
                            continue
                        jobs.append((workflow["id"], "event", "monitoring-alert:" + str(alert["id"]),
                                     {"event_type": workflow["trigger_event"], "alert": alert}))
    for workflow_id, trigger_source, trigger_key, payload in jobs:
        try:
            _cartman_wf_execute(workflow_id, trigger_source, trigger_key, payload, "workflow-scheduler")
        except Exception as exc:
            print("[CARTMAN WORKFLOWS] scheduler execution failed:", str(exc)[:500], flush=True)


def _cartman_wf_scheduler_loop():
    while True:
        try:
            _cartman_wf_scheduler_tick()
        except Exception as exc:
            print("[CARTMAN WORKFLOWS] scheduler tick failed:", str(exc)[:500], flush=True)
        _cartman_wf_time.sleep(15)


def _cartman_wf_start_scheduler():
    thread = globals().get("_CARTMAN_WF_SCHEDULER_THREAD")
    if thread is None or not thread.is_alive():
        thread = _cartman_wf_threading.Thread(target=_cartman_wf_scheduler_loop, name="cartman-workflow-scheduler", daemon=True)
        thread.start()
        globals()["_CARTMAN_WF_SCHEDULER_THREAD"] = thread


_cartman_wf_ensure_schema()


@app.get("/api/workflows")
def cartman_list_workflows(request: Request):
    user = _cartman_wf_require_user(request)
    role = str(user.get("role") or "").lower()
    if role not in {"admin", "network_admin", "support_agent", "read_only"}:
        raise HTTPException(status_code=403, detail="Your role may not view workflows.")
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT w.*,
                (SELECT COUNT(*) FROM cartman_workflow_runs r WHERE r.workflow_id=w.id) AS run_count,
                (SELECT COUNT(*) FROM cartman_workflow_runs r WHERE r.workflow_id=w.id AND r.started_at >= datetime('now','-1 day')) AS runs_24h,
                (SELECT COUNT(*) FROM cartman_workflow_runs r WHERE r.workflow_id=w.id AND r.started_at >= datetime('now','-1 day') AND r.status='Failed') AS failures_24h,
                (SELECT r.status FROM cartman_workflow_runs r WHERE r.workflow_id=w.id ORDER BY r.id DESC LIMIT 1) AS last_run_status,
                (SELECT r.started_at FROM cartman_workflow_runs r WHERE r.workflow_id=w.id ORDER BY r.id DESC LIMIT 1) AS last_run_at
            FROM cartman_workflows w WHERE w.is_archived=0 ORDER BY w.updated_at DESC, w.id DESC
        """).fetchall()
    items = [_cartman_wf_public_workflow(row) for row in rows]
    return {"items": items, "total": len(items), "can_manage": role == "admin", "source": "database"}


@app.post("/api/workflows", status_code=201)
def cartman_create_workflow(payload: dict, request: Request):
    user = _cartman_wf_require_admin(request)
    data = _cartman_wf_normalize_payload(payload)
    with get_connection() as connection:
        cursor_id = 0
        if data["trigger_type"] == "event":
            try:
                cursor_id = int(connection.execute("SELECT COALESCE(MAX(id),0) FROM monitoring_alerts").fetchone()[0])
            except Exception:
                cursor_id = 0
        next_run = None
        if data["enabled"] and data["trigger_type"] == "interval":
            next_run = "+" + str(data["interval_minutes"]) + " minutes"
        cursor = connection.execute("""
            INSERT INTO cartman_workflows
                (name, description, trigger_type, trigger_event, interval_minutes, enabled, steps_json,
                 event_cursor_id, next_run_at, created_by_username, updated_by_username)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IS NULL THEN NULL ELSE datetime('now', ?) END, ?, ?)
        """, (data["name"], data["description"], data["trigger_type"], data["trigger_event"], data["interval_minutes"],
              int(data["enabled"]), _cartman_wf_json.dumps(data["steps"], ensure_ascii=False), cursor_id,
              next_run, next_run or "+1 minutes", str(user.get("username") or ""), str(user.get("username") or "")))
        row = connection.execute("SELECT * FROM cartman_workflows WHERE id=?", (cursor.lastrowid,)).fetchone()
    return _cartman_wf_public_workflow(row)


@app.get("/api/workflows/{workflow_id}")
def cartman_get_workflow(workflow_id: int, request: Request):
    _cartman_wf_require_user(request)
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM cartman_workflows WHERE id=? AND is_archived=0", (workflow_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return _cartman_wf_public_workflow(row)


@app.put("/api/workflows/{workflow_id}")
def cartman_update_workflow(workflow_id: int, payload: dict, request: Request):
    user = _cartman_wf_require_admin(request)
    with get_connection() as connection:
        current_row = connection.execute("SELECT * FROM cartman_workflows WHERE id=? AND is_archived=0", (workflow_id,)).fetchone()
        if not current_row:
            raise HTTPException(status_code=404, detail="Workflow not found.")
        current = _cartman_wf_public_workflow(current_row)
        data = _cartman_wf_normalize_payload(payload, current)
        cursor_id = int(current_row["event_cursor_id"] or 0)
        if data["trigger_type"] == "event" and (current.get("trigger_type") != "event" or current.get("trigger_event") != data["trigger_event"] or not current.get("enabled")):
            try:
                cursor_id = int(connection.execute("SELECT COALESCE(MAX(id),0) FROM monitoring_alerts").fetchone()[0])
            except Exception:
                cursor_id = 0
        next_run = None
        if data["enabled"] and data["trigger_type"] == "interval":
            next_run = connection.execute("SELECT datetime('now', ?)", ("+" + str(data["interval_minutes"]) + " minutes",)).fetchone()[0]
        connection.execute("""
            UPDATE cartman_workflows SET name=?, description=?, trigger_type=?, trigger_event=?, interval_minutes=?,
                enabled=?, steps_json=?, event_cursor_id=?, next_run_at=?, updated_by_username=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (data["name"], data["description"], data["trigger_type"], data["trigger_event"], data["interval_minutes"],
              int(data["enabled"]), _cartman_wf_json.dumps(data["steps"], ensure_ascii=False), cursor_id, next_run,
              str(user.get("username") or ""), workflow_id))
        row = connection.execute("SELECT * FROM cartman_workflows WHERE id=?", (workflow_id,)).fetchone()
    return _cartman_wf_public_workflow(row)


@app.post("/api/workflows/{workflow_id}/toggle")
def cartman_toggle_workflow(workflow_id: int, payload: dict, request: Request):
    user = _cartman_wf_require_admin(request)
    enabled = bool(payload.get("enabled"))
    with get_connection() as connection:
        current = connection.execute("SELECT * FROM cartman_workflows WHERE id=? AND is_archived=0", (workflow_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Workflow not found.")
        cursor_id = int(current["event_cursor_id"] or 0)
        if enabled and current["trigger_type"] == "event":
            try:
                cursor_id = int(connection.execute("SELECT COALESCE(MAX(id),0) FROM monitoring_alerts").fetchone()[0])
            except Exception:
                cursor_id = 0
        next_run = None
        if enabled and current["trigger_type"] == "interval":
            next_run = connection.execute("SELECT datetime('now', ?)", ("+" + str(max(1, min(int(current["interval_minutes"] or 60), 10080))) + " minutes",)).fetchone()[0]
        connection.execute("UPDATE cartman_workflows SET enabled=?, event_cursor_id=?, next_run_at=?, updated_by_username=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (int(enabled), cursor_id, next_run, str(user.get("username") or ""), workflow_id))
        row = connection.execute("SELECT * FROM cartman_workflows WHERE id=?", (workflow_id,)).fetchone()
    return _cartman_wf_public_workflow(row)


@app.delete("/api/workflows/{workflow_id}")
def cartman_archive_workflow(workflow_id: int, request: Request):
    user = _cartman_wf_require_admin(request)
    with get_connection() as connection:
        current = connection.execute("SELECT id FROM cartman_workflows WHERE id=? AND is_archived=0", (workflow_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Workflow not found.")
        connection.execute("UPDATE cartman_workflows SET is_archived=1, enabled=0, next_run_at=NULL, updated_by_username=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (str(user.get("username") or ""), workflow_id))
    return {"ok": True, "archived": True, "workflow_id": workflow_id, "history_preserved": True}


@app.get("/api/workflows/{workflow_id}/runs")
def cartman_list_workflow_runs(workflow_id: int, request: Request, limit: int = 50):
    _cartman_wf_require_user(request)
    limit = max(1, min(int(limit or 50), 200))
    with get_connection() as connection:
        exists = connection.execute("SELECT id FROM cartman_workflows WHERE id=?", (workflow_id,)).fetchone()
        runs = connection.execute("SELECT * FROM cartman_workflow_runs WHERE workflow_id=? ORDER BY id DESC LIMIT ?", (workflow_id, limit)).fetchall()
    if not exists and not runs:
        raise HTTPException(status_code=404, detail="Workflow and execution history not found.")
    return {"items": [_cartman_wf_public_run(row) for row in runs], "total": len(runs)}


@app.post("/api/workflows/{workflow_id}/run")
def cartman_run_workflow(workflow_id: int, payload: dict, request: Request):
    user = _cartman_wf_require_admin(request)
    event_data = payload.get("input") if isinstance(payload, dict) else {}
    if not isinstance(event_data, dict):
        raise HTTPException(status_code=422, detail="Workflow input must be an object.")
    trigger_key = "manual:" + _cartman_wf_uuid.uuid4().hex
    try:
        return _cartman_wf_execute(workflow_id, "manual", trigger_key, event_data, str(user.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/workflow-notifications")
def cartman_list_workflow_notifications(request: Request, limit: int = 100):
    user = _cartman_wf_require_user(request)
    limit = max(1, min(int(limit or 100), 200))
    username = str(user.get("username") or "").strip()
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, recipient_username, title, message, severity, source, action_url, workflow_id, workflow_run_id, created_at
            FROM cartman_workflow_notifications
            WHERE lower(trim(recipient_username))=lower(trim(?))
            ORDER BY id DESC LIMIT ?
        """, (username, limit)).fetchall()
    return [dict(row) for row in rows]


_cartman_wf_start_scheduler()
# END CARTMAN_WORKFLOWS_REAL_API_V1



# CARTMAN_NOTIFICATION_INBOX_API_V1
# User-scoped persistent notification inbox shared by the topbar bell and Notifications page.
def _cartman_notification_inbox_ensure_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_user_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_username TEXT NOT NULL,
            event_key TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'info',
            source TEXT NOT NULL DEFAULT 'Cartman',
            action_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            read_at TEXT,
            UNIQUE(recipient_username, event_key)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_user_notifications_unread ON cartman_user_notifications(recipient_username, read_at, id DESC)")


@app.get("/api/notifications/inbox")
def cartman_get_notification_inbox(request: Request, limit: int = 100, unread_only: bool = False):
    user = _cartman_wf_require_user(request)
    username = str(user.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is required.")
    limit = max(1, min(int(limit or 100), 200))
    with get_connection() as connection:
        _cartman_notification_inbox_ensure_schema(connection)
        unread_count = connection.execute(
            "SELECT COUNT(*) FROM cartman_user_notifications WHERE lower(trim(recipient_username))=lower(trim(?)) AND read_at IS NULL",
            (username,),
        ).fetchone()[0]
        where = " AND read_at IS NULL" if unread_only else ""
        rows = connection.execute(
            "SELECT id, title, message, severity, source, action_url, created_at, read_at "
            "FROM cartman_user_notifications WHERE lower(trim(recipient_username))=lower(trim(?))" + where +
            " ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "unread_count": int(unread_count), "source": "database"}


@app.post("/api/notifications/inbox")
def cartman_store_notification_inbox_item(payload: dict, request: Request):
    user = _cartman_wf_require_user(request)
    username = str(user.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is required.")
    payload = payload if isinstance(payload, dict) else {}
    event_key = str(payload.get("event_key") or payload.get("id") or "").strip()[:240]
    title = str(payload.get("title") or "Cartman notification").strip()[:180]
    message = str(payload.get("message") or "").strip()[:1200]
    source = str(payload.get("source") or "Cartman").strip()[:100] or "Cartman"
    severity = str(payload.get("severity") or "info").strip().lower()
    if severity not in {"critical", "error", "warning", "info", "success"}:
        severity = "info"
    action_url = str(payload.get("action_url") or payload.get("actionUrl") or "").strip()[:300]
    if action_url and (not action_url.startswith("/") or action_url.startswith("//")):
        raise HTTPException(status_code=422, detail="Notification action URL must be a local Cartman path.")
    if not event_key:
        event_key = (source + ":" + title + ":" + message)[:240]
    if not title:
        raise HTTPException(status_code=422, detail="Notification title is required.")
    with get_connection() as connection:
        _cartman_notification_inbox_ensure_schema(connection)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO cartman_user_notifications "
            "(recipient_username, event_key, title, message, severity, source, action_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, event_key, title, message, severity, source, action_url),
        )
        inserted = cursor.rowcount > 0
        row = connection.execute(
            "SELECT id FROM cartman_user_notifications WHERE lower(trim(recipient_username))=lower(trim(?)) AND event_key=?",
            (username, event_key),
        ).fetchone()
    return {"saved": True, "inserted": inserted, "id": int(row[0]) if row else None}


@app.post("/api/notifications/inbox/read")
def cartman_mark_notification_inbox_read(payload: dict, request: Request):
    user = _cartman_wf_require_user(request)
    username = str(user.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is required.")
    payload = payload if isinstance(payload, dict) else {}
    with get_connection() as connection:
        _cartman_notification_inbox_ensure_schema(connection)
        if payload.get("all") is True:
            connection.execute(
                "UPDATE cartman_user_notifications SET read_at=CURRENT_TIMESTAMP "
                "WHERE lower(trim(recipient_username))=lower(trim(?)) AND read_at IS NULL",
                (username,),
            )
        else:
            try:
                notification_id = int(payload.get("id"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="A valid notification ID is required.")
            connection.execute(
                "UPDATE cartman_user_notifications SET read_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND lower(trim(recipient_username))=lower(trim(?)) AND read_at IS NULL",
                (notification_id, username),
            )
        remaining = connection.execute(
            "SELECT COUNT(*) FROM cartman_user_notifications WHERE lower(trim(recipient_username))=lower(trim(?)) AND read_at IS NULL",
            (username,),
        ).fetchone()[0]
    return {"saved": True, "unread_count": int(remaining)}
# END CARTMAN_NOTIFICATION_INBOX_API_V1


# CARTMAN WORK MANAGEMENT UTC TIMESTAMP HELPER
def _wm_now():
    return _datetime.datetime.now(_datetime.timezone.utc).replace(
        tzinfo=None
    ).strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/operations/projects")
def list_work_projects(request: Request):
    user = _wm_require_admin(request)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, is_active, created_by_username, updated_by_username, created_at, updated_at "
            "FROM work_projects WHERE is_active=1 ORDER BY lower(name)"
        ).fetchall()
    return {"items": [dict(row) for row in rows], "can_manage": user.get("role") == "admin", "source": "database"}


@app.post("/api/operations/projects", status_code=201)
def create_work_project(payload: dict, request: Request):
    user = _wm_require_admin(request)
    name = _wm_text(payload, "name", "", 80, required=True)
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Project name must be at least 2 characters.")
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO work_projects (name, created_by_username, updated_by_username) VALUES (?, ?, ?)",
                (name, str(user.get("username") or ""), str(user.get("username") or "")),
            )
            row = connection.execute("SELECT * FROM work_projects WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="A project with this name already exists.")
        raise
    return dict(row)


@app.put("/api/operations/projects/{project_id}")
def update_work_project(project_id: int, payload: dict, request: Request):
    user = _wm_require_admin(request)
    if set(payload) - {"name", "is_active"} or not payload:
        raise HTTPException(status_code=422, detail="Supported fields are name and is_active.")
    updates = {}
    if "name" in payload:
        name = _wm_text(payload, "name", "", 80, required=True)
        if len(name) < 2:
            raise HTTPException(status_code=422, detail="Project name must be at least 2 characters.")
        updates["name"] = name
    if "is_active" in payload:
        if not isinstance(payload["is_active"], bool):
            raise HTTPException(status_code=422, detail="is_active must be true or false.")
        updates["is_active"] = int(payload["is_active"])
    updates["updated_by_username"] = str(user.get("username") or "")
    updates["updated_at"] = _wm_now()
    with get_connection() as connection:
        if not connection.execute("SELECT 1 FROM work_projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Project not found.")
        columns = list(updates)
        connection.execute(
            "UPDATE work_projects SET " + ", ".join(f"{key}=?" for key in columns) + " WHERE id=?",
            [updates[key] for key in columns] + [project_id],
        )
        row = connection.execute("SELECT * FROM work_projects WHERE id=?", (project_id,)).fetchone()
    return dict(row)


@app.delete("/api/operations/projects/{project_id}")
def delete_work_project(project_id: int, request: Request):
    _wm_require_admin(request)
    with get_connection() as connection:
        row = connection.execute("SELECT name FROM work_projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found.")
        name = row["name"]
        used_task = connection.execute("SELECT 1 FROM work_items WHERE lower(project)=lower(?) LIMIT 1", (name,)).fetchone()
        used_rule = connection.execute("SELECT 1 FROM automation_rules WHERE lower(task_project)=lower(?) LIMIT 1", (name,)).fetchone()
        if used_task or used_rule:
            connection.execute("UPDATE work_projects SET is_active=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            return {"deleted": False, "archived": True, "name": name, "detail": "Project is in use; it has been archived and existing records were preserved."}
        connection.execute("DELETE FROM work_projects WHERE id=?", (project_id,))
    return {"deleted": True, "name": name}


# CARTMAN_TASK_AUTOMATION_ENGINE_V1
# CARTMAN_WORK_ITEM_TARGET_ASSIGNMENT_V1
# CARTMAN_PYTHON_AUTOMATION_V1
# CARTMAN_AUTOMATION_TARGET_SELECTOR_V1
# All automation actions are allowlisted application-level actions. No shell or arbitrary code execution.
def _wm_automation_dict(row):
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
    item["skip_if_open"] = bool(item.get("skip_if_open"))
    item["runs"] = int(item.get("run_count") or 0)
    item["last_status"] = item.get("last_status") or "Never run"
    item["action_type"] = item.get("configured_action_type") or "create_task"
    item["script_filename"] = item.get("script_filename") or ""
    item["target_type"] = item.get("target_type") or "all"
    item["target_id"] = item.get("target_id") or ""
    item["target_name"] = item.get("target_name") or "Not configured (legacy automation)"
    item.pop("configured_action_type", None)
    return item


def _wm_validate_automation(payload):
    name = _wm_text(payload, "name", "", 120, required=True)
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="Automation name must be at least 3 characters.")
    description = _wm_text(payload, "description", "", 1000)
    trigger_type = _wm_text(payload, "trigger_type", "manual", 20)
    if trigger_type not in {"manual", "interval"}:
        raise HTTPException(status_code=422, detail="Trigger must be manual or interval.")
    interval_minutes = None
    if trigger_type == "interval":
        try:
            interval_minutes = int(payload.get("interval_minutes", 1440))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Interval must be a whole number of minutes.")
        if not 1 <= interval_minutes <= 10080:
            raise HTTPException(status_code=422, detail="Interval must be between 1 minute and 7 days.")
    skip_if_open = payload.get("skip_if_open", True)
    if not isinstance(skip_if_open, bool):
        raise HTTPException(status_code=422, detail="skip_if_open must be true or false.")

    action_type = _wm_text(payload, "action_type", "create_task", 30)
    if action_type not in {"create_task", "run_python"}:
        raise HTTPException(status_code=422, detail="Action must be create_task or run_python.")

    script_filename = ""
    script_content = ""
    if action_type == "run_python":
        raw_filename = payload.get("script_filename")
        if not isinstance(raw_filename, str) or not raw_filename.strip():
            raise HTTPException(status_code=422, detail="Choose a Python (.py) script file.")
        # Keep only the basename; never use a user-supplied path on the server.
        script_filename = raw_filename.strip().replace("\\", "/").split("/")[-1]
        if len(script_filename) > 120 or not script_filename.lower().endswith(".py"):
            raise HTTPException(status_code=422, detail="Only .py scripts up to 120 characters are supported.")
        script_content = payload.get("script_content")
        if not isinstance(script_content, str) or not script_content.strip():
            raise HTTPException(status_code=422, detail="The selected Python script is empty or unreadable.")
        try:
            script_size = len(script_content.encode("utf-8"))
        except UnicodeError:
            raise HTTPException(status_code=422, detail="The Python script must be valid UTF-8 text.")
        if script_size > 131072:
            raise HTTPException(status_code=413, detail="Python scripts are limited to 128 KiB.")
        if "\x00" in script_content:
            raise HTTPException(status_code=422, detail="The Python script contains an invalid null byte.")
        try:
            compile(script_content, script_filename, "exec")
        except SyntaxError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Python syntax error on line {exc.lineno}: {exc.msg}",
            )

    task_title = _wm_text(payload, "task_title", "", 200)
    if action_type == "create_task" and len(task_title) < 3:
        raise HTTPException(status_code=422, detail="Task title must be at least 3 characters.")
    if action_type == "run_python" and len(task_title) < 3:
        task_title = ("Run Python script: " + script_filename)[:200]

    task_priority = _wm_text(payload, "task_priority", "Normal", 20)
    if task_priority not in _WORK_ITEM_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid task priority.")
    return {
        "name": name,
        "description": description,
        "trigger_type": trigger_type,
        "interval_minutes": interval_minutes,
        "skip_if_open": skip_if_open,
        "action_type": action_type,
        "script_filename": script_filename,
        "script_content": script_content,
        "task_title": task_title,
        "task_description": _wm_text(payload, "task_description", "", 5000),
        "task_project": _wm_text(payload, "task_project", "Operations", 80) or "Operations",
        "task_owner": _wm_text(payload, "task_owner", "Unassigned", 120) or "Unassigned",
        "task_due": _wm_text(payload, "task_due", "Unscheduled", 40) or "Unscheduled",
        "task_priority": task_priority,
    }



def _wm_resolve_automation_target(connection, target_type, target_id):
    if not isinstance(target_type, str) or target_type not in {"user", "department", "group"}:
        raise HTTPException(status_code=422, detail="Choose a User, Department, or Group target.")
    target_id = str(target_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=422, detail="Choose a target before saving the automation.")
    if target_type == "user":
        row = connection.execute(
            "SELECT id, name, username, department, status FROM iam_users WHERE CAST(id AS TEXT)=?",
            (target_id,),
        ).fetchone()
        if row:
            name = str(row["name"] or row["username"] or row["id"])
            username = str(row["username"] or "").strip()
            target_name = name + (f" (@{username})" if username and username.lower() != name.lower() else "")
    elif target_type == "department":
        row = connection.execute(
            "SELECT id, name FROM departments WHERE CAST(id AS TEXT)=?", (target_id,)
        ).fetchone()
        if row:
            target_name = str(row["name"] or row["id"])
    else:
        row = connection.execute(
            "SELECT id, name, scope, status FROM iam_groups WHERE CAST(id AS TEXT)=?", (target_id,)
        ).fetchone()
        if row:
            target_name = str(row["name"] or row["id"])
    if not row:
        raise HTTPException(status_code=422, detail="The selected target no longer exists. Refresh the target list and try again.")
    return {"target_type": target_type, "target_id": str(row["id"]), "target_name": target_name}


@app.get("/api/operations/automation-targets")
def list_operation_automation_targets(request: Request):
    target_user = _wm_require_admin(request)
    if target_user.get("role") not in {"admin", "support_agent"}:
        raise HTTPException(status_code=403, detail="Your role may not view assignment targets.")
    with get_connection() as connection:
        users = connection.execute(
            "SELECT id, name, username, department, status FROM iam_users ORDER BY lower(name), lower(username)"
        ).fetchall()
        departments = connection.execute(
            "SELECT id, name FROM departments ORDER BY lower(name)"
        ).fetchall()
        groups = connection.execute(
            "SELECT id, name, scope, status FROM iam_groups ORDER BY lower(name)"
        ).fetchall()
    return {
        "users": [dict(id=str(row["id"]), name=str(row["name"] or row["username"] or row["id"]),
                       username=str(row["username"] or ""), department=str(row["department"] or ""),
                       status=str(row["status"] or "")) for row in users],
        "departments": [dict(id=str(row["id"]), name=str(row["name"] or row["id"])) for row in departments],
        "groups": [dict(id=str(row["id"]), name=str(row["name"] or row["id"]),
                        scope=str(row["scope"] or ""), status=str(row["status"] or "")) for row in groups],
    }


@app.get("/api/operations/automations")
def list_operation_automations(request: Request, limit: int = 200):
    user = _wm_require_admin(request)
    limit = max(1, min(int(limit), 500))
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT r.*,
                CASE WHEN s.automation_id IS NOT NULL THEN 'run_python' ELSE 'create_task' END AS configured_action_type,
                s.filename AS script_filename,
                s.created_by_username AS script_created_by_username,
                s.updated_by_username AS script_updated_by_username,
                t.target_type AS target_type,
                t.target_id AS target_id,
                t.target_name AS target_name,
                (SELECT COUNT(*) FROM automation_executions e WHERE e.automation_id=r.automation_id) AS run_count,
                (SELECT e.status FROM automation_executions e WHERE e.automation_id=r.automation_id
                    ORDER BY e.started_at DESC LIMIT 1) AS last_status
            FROM automation_rules r
            LEFT JOIN automation_scripts s ON s.automation_id=r.automation_id
            LEFT JOIN automation_targets t ON t.automation_id=r.automation_id
            ORDER BY r.created_at DESC, r.automation_id
            LIMIT ?
        """, (limit,)).fetchall()
    return {"items": [_wm_automation_dict(row) for row in rows],
            "can_manage": user.get("role") == "admin",
            "can_run": user.get("role") in {"admin", "support_agent"},
            "source": "database"}



@app.post("/api/operations/automations", status_code=201)
def create_operation_automation(payload: dict, request: Request):
    user = _wm_require_admin(request)
    values = _wm_validate_automation(payload)
    automation_id = "AUT-" + uuid.uuid4().hex[:10].upper()
    import hashlib
    with get_connection() as connection:
        target = _wm_resolve_automation_target(connection, payload.get("target_type"), payload.get("target_id"))
        # Keep legacy action_type='create_task' unchanged; the companion table
        # safely adds new action types without rebuilding the existing SQLite table.
        connection.execute("""
            INSERT INTO automation_rules (
                automation_id, name, description, trigger_type, interval_minutes,
                enabled, skip_if_open, action_type, task_title, task_description,
                task_project, task_owner, task_due, task_priority, created_by_username
            ) VALUES (?, ?, ?, ?, ?, 0, ?, 'create_task', ?, ?, ?, ?, ?, ?, ?)
        """, (
            automation_id, values["name"], values["description"], values["trigger_type"],
            values["interval_minutes"], int(values["skip_if_open"]), values["task_title"],
            values["task_description"], values["task_project"], values["task_owner"],
            values["task_due"], values["task_priority"], str(user.get("username") or ""),
        ))
        connection.execute(
            "INSERT INTO automation_targets (automation_id, target_type, target_id, target_name) VALUES (?, ?, ?, ?)",
            (automation_id, target["target_type"], target["target_id"], target["target_name"]),
        )
        if values["action_type"] == "run_python":
            connection.execute("""
                INSERT INTO automation_scripts
                    (automation_id, filename, content, sha256, created_by_username)
                VALUES (?, ?, ?, ?, ?)
            """, (
                automation_id,
                values["script_filename"],
                values["script_content"],
                hashlib.sha256(values["script_content"].encode("utf-8")).hexdigest(),
                str(user.get("username") or ""),
            ))
        row = connection.execute("""
            SELECT r.*,
                CASE WHEN s.automation_id IS NOT NULL THEN 'run_python' ELSE 'create_task' END AS configured_action_type,
                s.filename AS script_filename,
                t.target_type AS target_type,
                t.target_id AS target_id,
                t.target_name AS target_name
            FROM automation_rules r
            LEFT JOIN automation_scripts s ON s.automation_id=r.automation_id
            LEFT JOIN automation_targets t ON t.automation_id=r.automation_id
            WHERE r.automation_id=?
        """, (automation_id,)).fetchone()
    return _wm_automation_dict(row)



@app.put("/api/operations/automations/{automation_id}")
def update_operation_automation(automation_id: str, payload: dict, request: Request):
    user = _wm_require_admin(request)
    import os
    with get_connection() as connection:
        current = connection.execute("SELECT * FROM automation_rules WHERE automation_id=?", (automation_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Automation not found.")
        current_script = connection.execute(
            "SELECT filename, content, created_by_username FROM automation_scripts WHERE automation_id=?",
            (automation_id,),
        ).fetchone()
        # Preserve the existing one-field toggle API used by the card switch.
        if set(payload) == {"enabled"} and isinstance(payload.get("enabled"), bool):
            enabled = payload["enabled"]
            has_script = current_script is not None
            if enabled and has_script and os.environ.get("CARTMAN_ENABLE_TRUSTED_AUTOMATION_SCRIPTS") != "1":
                raise HTTPException(status_code=409, detail="Trusted Python execution is disabled. Enable it on the Cartman server after reviewing the script.")
            next_run = None
            if enabled and current["trigger_type"] == "interval":
                next_run = (_datetime.datetime.now(_datetime.timezone.utc).replace(tzinfo=None) +
                            _datetime.timedelta(minutes=int(current["interval_minutes"] or 1440))).strftime("%Y-%m-%d %H:%M:%S")
            connection.execute(
                "UPDATE automation_rules SET enabled=?, next_run_at=?, updated_by_username=?, updated_at=CURRENT_TIMESTAMP WHERE automation_id=?",
                (int(enabled), next_run, str(user.get("username") or ""), automation_id),
            )
            updated = connection.execute("SELECT * FROM automation_rules WHERE automation_id=?", (automation_id,)).fetchone()
            return _wm_automation_dict(updated)

        # Full form save. Editing any rule disables it pending review, avoiding an
        # unnoticed changed script/target being run by the scheduler.
        candidate = dict(payload)
        action_type = str(candidate.get("action_type") or ("run_python" if current_script else "create_task"))
        if action_type == "run_python" and current_script:
            candidate.setdefault("script_filename", current_script["filename"])
            if not candidate.get("script_content"):
                candidate["script_content"] = current_script["content"]
        values = _wm_validate_automation(candidate)
        target = _wm_resolve_automation_target(connection, candidate.get("target_type"), candidate.get("target_id"))
        connection.execute("""
            UPDATE automation_rules SET
                name=?, description=?, trigger_type=?, interval_minutes=?, enabled=0,
                skip_if_open=?, task_title=?, task_description=?, task_project=?, task_owner=?,
                task_due=?, task_priority=?, next_run_at=NULL, updated_by_username=?, updated_at=CURRENT_TIMESTAMP
            WHERE automation_id=?
        """, (
            values["name"], values["description"], values["trigger_type"], values["interval_minutes"],
            int(values["skip_if_open"] if values["action_type"] == "create_task" else False),
            values["task_title"], values["task_description"], values["task_project"], values["task_owner"],
            values["task_due"], values["task_priority"], str(user.get("username") or ""), automation_id,
        ))
        if values["action_type"] == "run_python":
            import hashlib
            prior_author = str(current_script["created_by_username"] or "") if current_script else str(user.get("username") or "")
            connection.execute("""
                INSERT INTO automation_scripts (automation_id, filename, content, sha256, created_by_username, updated_by_username)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(automation_id) DO UPDATE SET
                    filename=excluded.filename, content=excluded.content, sha256=excluded.sha256,
                    updated_by_username=excluded.updated_by_username
            """, (
                automation_id, values["script_filename"], values["script_content"],
                hashlib.sha256(values["script_content"].encode("utf-8")).hexdigest(),
                prior_author, str(user.get("username") or ""),
            ))
        else:
            connection.execute("DELETE FROM automation_scripts WHERE automation_id=?", (automation_id,))
        connection.execute("""
            INSERT INTO automation_targets (automation_id, target_type, target_id, target_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(automation_id) DO UPDATE SET
                target_type=excluded.target_type, target_id=excluded.target_id,
                target_name=excluded.target_name
        """, (automation_id, target["target_type"], target["target_id"], target["target_name"]))
        updated = connection.execute("""
            SELECT r.*,
                CASE WHEN s.automation_id IS NOT NULL THEN 'run_python' ELSE 'create_task' END AS configured_action_type,
                s.filename AS script_filename, s.created_by_username AS script_created_by_username,
                s.updated_by_username AS script_updated_by_username,
                t.target_type AS target_type, t.target_id AS target_id, t.target_name AS target_name
            FROM automation_rules r
            LEFT JOIN automation_scripts s ON s.automation_id=r.automation_id
            LEFT JOIN automation_targets t ON t.automation_id=r.automation_id
            WHERE r.automation_id=?
        """, (automation_id,)).fetchone()
    return _wm_automation_dict(updated)


@app.delete("/api/operations/automations/{automation_id}")
def delete_operation_automation(automation_id: str, request: Request):
    user = _wm_require_admin(request)
    with get_connection() as connection:
        row = connection.execute("SELECT automation_id, name FROM automation_rules WHERE automation_id=?", (automation_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Automation not found.")
        # Preserve execution history as an audit record; delete only the live rule and
        # its script/target configuration.
        connection.execute("DELETE FROM automation_rules WHERE automation_id=?", (automation_id,))
        connection.execute("DELETE FROM automation_scripts WHERE automation_id=?", (automation_id,))
        connection.execute("DELETE FROM automation_targets WHERE automation_id=?", (automation_id,))
    return {"deleted": True, "automation_id": automation_id, "name": row["name"], "deleted_by": str(user.get("username") or ""), "history_preserved": True}



def _wm_run_trusted_python_script(script_filename, source, target=None):
    """Run an administrator-trusted Python script on the Cartman server.

    This is resource-limited on POSIX, but is NOT a filesystem/network sandbox.
    Only execute code the administrator trusts. Remote endpoint execution is separate.
    """
    import os
    import sys
    import signal
    import tempfile
    import subprocess
    from pathlib import Path

    if os.environ.get("CARTMAN_ENABLE_TRUSTED_AUTOMATION_SCRIPTS") != "1":
        raise RuntimeError(
            "Trusted Python execution is disabled. Restart Cartman with "
            "CARTMAN_ENABLE_TRUSTED_AUTOMATION_SCRIPTS=1 after reviewing the script."
        )
    if os.name != "posix":
        raise RuntimeError(
            "The initial trusted Python runner currently requires a POSIX Cartman server. "
            "Windows server support and remote endpoint execution are not implemented yet."
        )
    if not isinstance(source, str) or len(source.encode("utf-8")) > 131072:
        raise RuntimeError("Python script is invalid or exceeds the 128 KiB limit.")

    with tempfile.TemporaryDirectory(prefix="cartman-automation-") as temp_dir:
        run_dir = Path(temp_dir)
        script_path = run_dir / "automation.py"
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        script_path.write_text(source, encoding="utf-8")
        # A short bootstrap limits CPU, address space, output-file size, open-file
        # count and core dumps before replacing itself with the user's script.
        bootstrap = r"""import os, sys
try:
 import resource
 limits = [
  (resource.RLIMIT_CPU, (55, 60)),
  (resource.RLIMIT_FSIZE, (1048576, 1048576)),
  (resource.RLIMIT_CORE, (0, 0)),
 ]
 if hasattr(resource, "RLIMIT_AS"):
  limits.append((resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024)))
 if hasattr(resource, "RLIMIT_NOFILE"):
  limits.append((resource.RLIMIT_NOFILE, (64, 64)))
 for kind, value in limits:
  try: resource.setrlimit(kind, value)
  except Exception: pass
except Exception: pass
os.execv(sys.executable, [sys.executable, "-I", sys.argv[1]])
"""
        import json
        target = target or {}
        child_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(run_dir),
            "TMPDIR": str(run_dir),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "CARTMAN_TARGET_TYPE": str(target.get("target_type") or "all"),
            "CARTMAN_TARGET_ID": str(target.get("target_id") or ""),
            "CARTMAN_TARGET_NAME": str(target.get("target_name") or "Not configured (legacy automation)"),
            "CARTMAN_TARGET_JSON": json.dumps(target, ensure_ascii=False, separators=(",", ":")),
        }
        with stdout_path.open("wb") as out_file, stderr_path.open("wb") as err_file:
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", bootstrap, str(script_path)],
                cwd=str(run_dir), env=child_env, stdout=out_file, stderr=err_file,
                close_fds=True, start_new_session=True,
            )
            try:
                return_code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise RuntimeError("Python script exceeded the 60-second execution timeout.")
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")[:1500].strip()
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")[:1200].strip()
        if return_code != 0:
            detail = stderr or stdout or f"Script exited with code {return_code}."
            raise RuntimeError(detail[:1000])
        summary = f"Python script {Path(script_filename).name} completed successfully (exit code 0)."
        if stdout:
            summary += " Output: " + stdout
        return summary[:2000]


def _wm_execute_automation(automation_id, trigger_source):
    started_at = _wm_now()
    execution_id = "EXE-" + uuid.uuid4().hex[:12].upper()
    with get_connection() as connection:
        row = connection.execute("""
            SELECT r.*, s.filename AS _script_filename, s.content AS _script_content,
                   t.target_type AS _target_type, t.target_id AS _target_id, t.target_name AS _target_name
            FROM automation_rules r
            LEFT JOIN automation_scripts s ON s.automation_id=r.automation_id
            LEFT JOIN automation_targets t ON t.automation_id=r.automation_id
            WHERE r.automation_id=?
        """, (automation_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Automation not found.")
    rule = dict(row)
    script_content = rule.pop("_script_content", None)
    script_filename = rule.pop("_script_filename", "")
    target = {
        "target_type": rule.pop("_target_type", None) or "all",
        "target_id": rule.pop("_target_id", None) or "",
        "target_name": rule.pop("_target_name", None) or "Not configured (legacy automation)",
    }
    is_python_action = script_content is not None
    status = "Succeeded"
    summary = ""
    task_key = ""
    error_message = ""
    try:
        with get_connection() as connection:
            if trigger_source == "schedule" and (not rule["enabled"] or rule["trigger_type"] != "interval"):
                status = "Skipped"
                summary = "Rule was disabled or is not scheduled; no action was taken."
            elif is_python_action:
                summary = _wm_run_trusted_python_script(script_filename, script_content, target)
                connection.execute("""
                    INSERT INTO ops_notifications (notification_type, title, body, source, priority)
                    VALUES ('Workflow', ?, ?, 'Tasks & Automation', 'Normal')
                """, (
                    "Automation script succeeded: " + rule["name"],
                    rule["name"] + " completed. " + summary[:1500],
                ))
            else:
                existing = None
                if rule["skip_if_open"]:
                    existing = connection.execute("""
                        SELECT task_key, status FROM work_items
                        WHERE lower(title)=lower(?) AND status != 'Done'
                        ORDER BY id DESC LIMIT 1
                    """, (rule["task_title"],)).fetchone()
                if existing:
                    status = "Skipped"
                    task_key = existing["task_key"]
                    summary = "An open task with the configured title already exists; duplicate creation was skipped."
                else:
                    created = _wm_create_work_item(connection, {
                        "title": rule["task_title"],
                        "description": rule["task_description"],
                        "project": rule["task_project"],
                        "owner": rule["task_owner"],
                        "due": rule["task_due"],
                        "status": "To do",
                        "priority": rule["task_priority"],
                    }, "automation:" + automation_id, target=target)
                    task_key = created["task_key"]
                    summary = "Created task " + task_key + "."
                    connection.execute("""
                        INSERT INTO ops_notifications (notification_type, title, body, source, priority)
                        VALUES ('Workflow', ?, ?, 'Tasks & Automation', ?)
                    """, (
                        "Automation created a task: " + rule["name"],
                        rule["name"] + " created " + task_key + ": " + rule["task_title"],
                        rule["task_priority"],
                    ))
            finished_at = _wm_now()
            connection.execute("""
                INSERT INTO automation_executions (
                    execution_id, automation_id, automation_name, trigger_source, status,
                    summary, task_key, started_at, finished_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')
            """, (execution_id, automation_id, rule["name"], trigger_source, status, summary,
                  task_key, started_at, finished_at))
            connection.execute(
                "UPDATE automation_rules SET last_run_at=?, updated_at=CURRENT_TIMESTAMP WHERE automation_id=?",
                (finished_at, automation_id),
            )
    except Exception as exc:
        finished_at = _wm_now()
        error_message = str(exc)[:1000]
        status = "Failed"
        summary = "Automation failed. See error details."
        try:
            with get_connection() as connection:
                connection.execute("""
                    INSERT INTO automation_executions (
                        execution_id, automation_id, automation_name, trigger_source, status,
                        summary, task_key, started_at, finished_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """, (execution_id, automation_id, rule["name"], trigger_source, status,
                      summary, started_at, finished_at, error_message))
                connection.execute(
                    "UPDATE automation_rules SET last_run_at=?, updated_at=CURRENT_TIMESTAMP WHERE automation_id=?",
                    (finished_at, automation_id),
                )
        except Exception as log_exc:
            print("[CARTMAN AUTOMATION] failed to persist execution error:", log_exc, flush=True)
    return {"execution_id": execution_id, "automation_id": automation_id,
            "automation_name": rule["name"], "trigger_source": trigger_source,
            "status": status, "summary": summary, "task_key": task_key,
            "started_at": started_at, "finished_at": finished_at, "error_message": error_message}



@app.post("/api/operations/automations/{automation_id}/run")
def run_operation_automation(automation_id: str, request: Request):
    _wm_require_admin(request)
    return _wm_execute_automation(automation_id, "manual")


@app.get("/api/operations/executions")
def list_operation_executions(request: Request, limit: int = 200, automation_id: Optional[str] = None):
    _wm_require_admin(request)
    limit = max(1, min(int(limit), 500))
    with get_connection() as connection:
        common = """
            SELECT e.*,
                t.target_type AS target_type, t.target_id AS target_id, t.target_name AS target_name,
                (SELECT r.created_by_username FROM automation_rules r WHERE r.automation_id=e.automation_id) AS automation_created_by_username,
                (SELECT s.created_by_username FROM automation_scripts s WHERE s.automation_id=e.automation_id) AS script_created_by_username,
                COALESCE(
                    NULLIF((SELECT s.created_by_username FROM automation_scripts s WHERE s.automation_id=e.automation_id), ''),
                    NULLIF((SELECT r.created_by_username FROM automation_rules r WHERE r.automation_id=e.automation_id), ''),
                    'system'
                ) AS action_created_by_username,
                COALESCE(
                    NULLIF((SELECT s.updated_by_username FROM automation_scripts s WHERE s.automation_id=e.automation_id), ''),
                    NULLIF((SELECT r.updated_by_username FROM automation_rules r WHERE r.automation_id=e.automation_id), ''),
                    '—'
                ) AS last_edited_by_username
            FROM automation_executions e
            LEFT JOIN automation_targets t ON t.automation_id=e.automation_id
        """
        if automation_id:
            rows = connection.execute(
                common + " WHERE e.automation_id=? ORDER BY e.started_at DESC LIMIT ?",
                (automation_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(common + " ORDER BY e.started_at DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(row) for row in rows], "source": "database"}



def _wm_claim_due_automations():
    now = _wm_now()
    claimed = []
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("""
            SELECT automation_id, interval_minutes, next_run_at
            FROM automation_rules
            WHERE enabled=1 AND trigger_type='interval' AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at ASC LIMIT 50
        """, (now,)).fetchall()
        for row in rows:
            minutes = max(1, min(int(row["interval_minutes"] or 1440), 10080))
            next_run = (_datetime.datetime.now(_datetime.timezone.utc).replace(tzinfo=None) +
                        _datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
            cursor = connection.execute("""
                UPDATE automation_rules SET next_run_at=?, updated_at=CURRENT_TIMESTAMP
                WHERE automation_id=? AND enabled=1 AND next_run_at=?
            """, (next_run, row["automation_id"], row["next_run_at"]))
            if cursor.rowcount == 1:
                claimed.append(row["automation_id"])
    return claimed


def _wm_scheduler_loop():
    while True:
        time.sleep(10)
        try:
            for automation_id in _wm_claim_due_automations():
                result = _wm_execute_automation(automation_id, "schedule")
                if result["status"] == "Failed":
                    print("[CARTMAN AUTOMATION] scheduled run failed:", result["automation_id"], result["error_message"], flush=True)
        except Exception as exc:
            print("[CARTMAN AUTOMATION] scheduler cycle failed:", exc, flush=True)


_WM_SCHEDULER_THREAD = None


@app.on_event("startup")
def _wm_start_automation_scheduler():
    global _WM_SCHEDULER_THREAD
    if _WM_SCHEDULER_THREAD is None or not _WM_SCHEDULER_THREAD.is_alive():
        _WM_SCHEDULER_THREAD = threading.Thread(
            target=_wm_scheduler_loop, name="cartman-automation-scheduler", daemon=True
        )
        _WM_SCHEDULER_THREAD.start()

@app.get("/api/tickets")
def list_tickets(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    type: Optional[str] = None,
    scope: str = "all",
    limit: int = 100,
    offset: int = 0,
):
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    if scope not in {"all", "mine"}:
        raise HTTPException(status_code=422, detail="scope must be 'all' or 'mine'.")
    conditions = ["deleted_at IS NULL"]
    # CARTMAN_HIDE_CLOSED_TICKETS_V1
    # Hide closed tickets by default; show them when a search query is provided.
    if not (q and q.strip()):
        conditions.append("status NOT IN ('Closed', 'Resolved')")
    params = []
    user = getattr(request.state, "auth_user", {}) or {}
    if user.get("role") in {"support_agent", "read_only"}:
        actor = str(user.get("username") or "").strip()
        if not actor:
            raise HTTPException(status_code=401, detail="Authenticated username is unavailable.")
        if user.get("role") == "support_agent":
            conditions.append("(lower(assigned_to_username) = lower(?) OR lower(requester_username) = lower(?))")
            params.extend([actor, actor])
        else:
            conditions.append("lower(requester_username) = lower(?)")
            params.append(actor)
    if scope == "mine":
        user = getattr(request.state, "auth_user", {}) or {}
        username = str(user.get("username") or "").strip()
        if not username:
            raise HTTPException(status_code=401, detail="Authenticated username is unavailable.")
        conditions.append("lower(assigned_to_username) = lower(?)")
        params.append(username)
        conditions.append("status NOT IN ('Waiting for requester', 'Resolved', 'Closed')")
    if q and q.strip():
        needle = f"%{q.strip()}%"
        conditions.append("(ticket_key LIKE ? OR title LIKE ? OR description LIKE ? OR requester LIKE ? OR requester_username LIKE ? OR assigned_to LIKE ? OR assigned_to_username LIKE ? OR team LIKE ?)")
        params.extend([needle] * 8)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if type:
        conditions.append("ticket_type = ?")
        params.append(type)
    where_sql = " WHERE " + " AND ".join(conditions)
    with get_connection() as connection:
        total = connection.execute("SELECT COUNT(*) FROM tickets" + where_sql, params).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM tickets" + where_sql + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        summary = {
            "open": connection.execute("SELECT COUNT(*) FROM tickets WHERE deleted_at IS NULL AND status NOT IN ('Resolved','Closed','Waiting for requester')").fetchone()[0],
            "critical": connection.execute("SELECT COUNT(*) FROM tickets WHERE deleted_at IS NULL AND priority='Critical' AND status NOT IN ('Resolved','Closed','Waiting for requester')").fetchone()[0],
            "pending": connection.execute("SELECT COUNT(*) FROM tickets WHERE deleted_at IS NULL AND status IN ('Pending','Waiting for requester')").fetchone()[0],
            "resolved": connection.execute("SELECT COUNT(*) FROM tickets WHERE deleted_at IS NULL AND status IN ('Resolved','Closed')").fetchone()[0],
        }
    return {"items": [_ticket_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset, "summary": summary}



@app.post("/api/tickets", status_code=201)
def create_ticket(payload: TicketCreate, request: Request):
    data = payload.model_dump()
    if data["type"] not in TICKET_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of: {', '.join(sorted(TICKET_TYPES))}")
    if data["priority"] not in TICKET_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of: {', '.join(sorted(TICKET_PRIORITIES))}")
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    username = str(user.get("username") or "").strip()
    display_name = str(user.get("display_name") or username or "Cartman user").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is unavailable.")

    with get_connection() as connection:
        level = "L1"
        agent = _ticket_select_agent(connection, level)
        if agent:
            assigned_to = agent["name"]
            assigned_username = agent["username"]
            team = _ticket_team_for_level(level)
            status = "Open"
        else:
            assigned_to = "Unassigned"
            assigned_username = ""
            team = f"{level} Queue"
            status = "Pending"

        cursor = connection.execute("""
            INSERT INTO tickets (
                title, description, ticket_type, priority, status,
                requester, requester_username, requester_account_id, created_by_username,
                assigned_to, assigned_to_username, team, escalation_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["title"].strip(), data["description"], data["type"], data["priority"],
            status, display_name, username, str(user.get("id") or ""), username,
            assigned_to, assigned_username, team, level,
        ))
        numeric_id = cursor.lastrowid
        ticket_key = f"#{numeric_id}"
        connection.execute("UPDATE tickets SET ticket_key = ? WHERE id = ?", (ticket_key, numeric_id))
        _ticket_audit(connection, numeric_id, "Created", "", "", ticket_key, display_name)
        _ticket_audit(connection, numeric_id, "Requester", "requester", "", display_name, display_name)
        if agent:
            _ticket_audit(connection, numeric_id, "Auto-assigned to online L1", "assigned_to", "Unassigned", assigned_to, "Cartman routing service")
        else:
            _ticket_audit(connection, numeric_id, "Queued - no online L1 agent", "team", "", team, "Cartman routing service")
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (numeric_id,)).fetchone()
    return _ticket_to_dict(row)



@app.get("/api/tickets/{ticket_key}")
def get_ticket(ticket_key: str, request: Request):
    with get_connection() as connection:
        row = _get_ticket_row(connection, ticket_key)
        if not row:
            raise HTTPException(status_code=404, detail="Ticket not found")
        user = getattr(request.state, "auth_user", {}) or {}
        role = user.get("role")
        can_see_internal = role == "admin"
        if role in {"support_agent", "read_only"}:
            actor = str(user.get("username") or "").strip().casefold()
            assigned = str(row["assigned_to_username"] or "").strip().casefold()
            requester = str(row["requester_username"] or "").strip().casefold()
            allowed = actor in ({assigned, requester} if role == "support_agent" else {requester})
            if not actor or not allowed:
                raise HTTPException(status_code=404, detail="Ticket not found")
            can_see_internal = role == "support_agent" and actor == assigned
        ticket = _ticket_to_dict(row)
        ticket["comments"] = [dict(item) for item in connection.execute(
            """SELECT id, author, author_username, author_role, body, created_at, is_internal FROM ticket_comments
               WHERE ticket_id=? ORDER BY id ASC""", (row["id"],)
        ).fetchall()]
        ticket["history"] = [dict(item) for item in connection.execute(
            """SELECT action, field_name, old_value, new_value, actor, created_at
               FROM ticket_audit_events WHERE ticket_id=? ORDER BY id DESC""", (row["id"],)
        ).fetchall()]
    if not can_see_internal:
        ticket["comments"] = [item for item in ticket["comments"] if not item.get("is_internal")]
        ticket["history"] = [item for item in ticket["history"] if item.get("action") != "Internal note added"]
    ticket["attachments"] = _cartman_attachment_list("ticket", ticket_key)
    return ticket


@app.put("/api/tickets/{ticket_key}")
def update_ticket(ticket_key: str, payload: TicketUpdate, request: Request):
    updates = {
        key: value for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No ticket fields were provided")
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    actor = str(user.get("display_name") or user.get("username") or "Cartman user")

    if "type" in updates and updates["type"] not in TICKET_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of: {', '.join(sorted(TICKET_TYPES))}")
    if "priority" in updates and updates["priority"] not in TICKET_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of: {', '.join(sorted(TICKET_PRIORITIES))}")
    if "status" in updates and updates["status"] not in TICKET_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(sorted(TICKET_STATUSES))}")
    if "escalation_level" in updates and updates["escalation_level"] not in {"L1", "L2", "L3"}:
        raise HTTPException(status_code=422, detail="escalation_level must be L1, L2, or L3")

    # Assignment and requester identity are server-controlled. On escalation, ignore
    # client-supplied assigned_to/team and recalculate from online IAM agents.
    if "requester" in updates:
        raise HTTPException(status_code=422, detail="Requester identity is set at creation and cannot be changed through ticket updates.")
    if "escalation_level" in updates:
        updates.pop("assigned_to", None)
        updates.pop("team", None)
    elif any(field in updates for field in ("assigned_to", "team")):
        raise HTTPException(
            status_code=422,
            detail="Requester and assignment fields are managed by the authenticated session and IAM routing.",
        )

    db_names = {
        "title": "title", "description": "description", "type": "ticket_type",
        "priority": "priority", "status": "status", "requester": "requester",
        "assigned_to": "assigned_to", "assigned_to_username": "assigned_to_username",
        "team": "team", "escalation_level": "escalation_level", "resolution": "resolution",
    }
    with get_connection() as connection:
        existing = _get_ticket_row(connection, ticket_key)
        if not existing:
            raise HTTPException(status_code=404, detail="Ticket not found")

        # CARTMAN_SUPPORT_AGENT_OWNERSHIP_V1
        if user.get("role") == "support_agent":
            actor = str(user.get("username") or "").strip().casefold()
            assigned = str(existing["assigned_to_username"] or "").strip().casefold()
            if not actor or actor != assigned:
                raise HTTPException(status_code=403, detail="Support agents may update only tickets assigned to them.")
            if not set(updates).issubset({"status", "escalation_level"}):
                raise HTTPException(status_code=403, detail="Support agents may change only ticket status or escalation level.")
        
        if "escalation_level" in updates:
            level = updates["escalation_level"]
            agent = _ticket_select_agent(connection, level)
            if agent:
                updates["assigned_to"] = agent["name"]
                updates["assigned_to_username"] = agent["username"]
                updates["team"] = _ticket_team_for_level(level)
                if existing["status"] not in {"Closed", "Resolved"}:
                    updates["status"] = "Open"
            else:
                updates["assigned_to"] = "Unassigned"
                updates["assigned_to_username"] = ""
                updates["team"] = f"{level} Queue"
                if existing["status"] not in {"Closed", "Resolved"}:
                    updates["status"] = "Pending"

        for field_name, new_value in updates.items():
            column = db_names[field_name]
            old_value = existing[column]
            if field_name in {"title", "assigned_to", "team"} and isinstance(new_value, str):
                new_value = new_value.strip()
            connection.execute(
                f"UPDATE tickets SET {column} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_value, existing["id"]),
            )
            if str(old_value or "") != str(new_value or ""):
                _ticket_audit(connection, existing["id"], "Updated", field_name, old_value, new_value, actor)

        if updates.get("status") in {"Resolved", "Closed"}:
            connection.execute(
                "UPDATE tickets SET resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP), awaiting_requester_since = NULL, requester_reply_due_at = NULL WHERE id = ?",
                (existing["id"],),
            )
        elif updates.get("status") and updates["status"] != "Waiting for requester":
            connection.execute(
                "UPDATE tickets SET resolved_at = NULL, awaiting_requester_since = NULL, requester_reply_due_at = NULL WHERE id = ?",
                (existing["id"],),
            )
        row = _get_ticket_row(connection, ticket_key)
    return _ticket_to_dict(row)



@app.post("/api/tickets/{ticket_key}/comments", status_code=201)
def add_ticket_comment(ticket_key: str, payload: TicketCommentCreate, request: Request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    username = str(user.get("username") or "").strip()
    display_name = str(user.get("display_name") or username or "Cartman user").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authenticated username is unavailable.")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Comment body cannot be blank.")

    with get_connection() as connection:
        ticket = _get_ticket_row(connection, ticket_key)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        # CARTMAN_SUPPORT_AGENT_OWNERSHIP_V1
        if user.get("role") == "support_agent":
            actor = str(username or "").strip().casefold()
            assigned = str(ticket["assigned_to_username"] or "").strip().casefold()
            requester = str(ticket["requester_username"] or "").strip().casefold()
            if not actor or actor not in {assigned, requester}:
                raise HTTPException(status_code=403, detail="You may comment only on tickets assigned to you or requested by you.")
            if payload.is_internal and actor != assigned:
                raise HTTPException(status_code=403, detail="Only the assigned support agent may add an internal note.")
        if ticket["status"] in {"Closed", "Resolved"}:
            raise HTTPException(status_code=409, detail="This ticket is closed. Reopen it before adding a message.")

        requester_username = str(ticket["requester_username"] or "").strip().lower()
        assigned_username = str(ticket["assigned_to_username"] or "").strip().lower()
        user_key = username.lower()
        if requester_username and user_key == requester_username:
            author_role = "requester"
        elif assigned_username and user_key == assigned_username:
            author_role = "agent"
        else:
            author_role = "support"

        cursor = connection.execute("""
            INSERT INTO ticket_comments
                (ticket_id, author, author_username, author_role, body, is_internal)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ticket["id"], display_name, username, author_role, body, int(payload.is_internal)))
        action = "Internal note added" if payload.is_internal else "Reply added"
        _ticket_audit(connection, ticket["id"], action, "comment", "", body, display_name)

        if not payload.is_internal:
            if author_role == "requester":
                if ticket["status"] == "Waiting for requester":
                    connection.execute("""
                        UPDATE tickets
                        SET status = 'Open', awaiting_requester_since = NULL,
                            requester_reply_due_at = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (ticket["id"],))
                    _ticket_audit(
                        connection, ticket["id"], "Requester replied - returned to assignee",
                        "status", "Waiting for requester", "Open", display_name
                    )
                else:
                    connection.execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (ticket["id"],))
            else:
                connection.execute("""
                    UPDATE tickets
                    SET status = 'Waiting for requester',
                        awaiting_requester_since = CURRENT_TIMESTAMP,
                        requester_reply_due_at = datetime('now', '+24 hours'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (ticket["id"],))
                _ticket_audit(
                    connection, ticket["id"], "Waiting for requester response (24h)",
                    "status", ticket["status"], "Waiting for requester", display_name
                )
        else:
            connection.execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (ticket["id"],))

        row = connection.execute(
            "SELECT id, author, author_username, author_role, body, created_at, is_internal FROM ticket_comments WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)



@app.delete("/api/tickets/{ticket_key}", status_code=204)
def delete_ticket(ticket_key: str, request: Request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    actor = str(user.get("display_name") or user.get("username") or "Cartman user")
    with get_connection() as connection:
        row = _get_ticket_row(connection, ticket_key)
        if not row:
            raise HTTPException(status_code=404, detail="Ticket not found")
        # Soft-delete keeps comments and audit history intact.
        connection.execute(
            "UPDATE tickets SET deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (row["id"],),
        )
        _ticket_audit(connection, row["id"], "Deleted", "deleted_at", "", "deleted", actor)
    return None


# CARTMAN_USER_METRICS_REAL_API_V2
# Read-only User Metrics APIs over existing Cartman IAM/auth/device/audit data.
import asyncio as _cartman_um_asyncio
import inspect as _cartman_um_inspect
import json as _cartman_um_json
import re as _cartman_um_re
import time as _cartman_um_time
from datetime import datetime as _cartman_um_datetime, timedelta as _cartman_um_timedelta, timezone as _cartman_um_timezone
from fastapi import Request as _CartmanUserMetricsRequest, HTTPException as _CartmanUserMetricsHTTPException


def _cartman_um_epoch(value):
    """Parse Unix seconds/milliseconds or ISO/SQLite timestamps into epoch seconds."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
        else:
            raw = str(value).strip()
            if not raw:
                return None
            if _cartman_um_re.fullmatch(r"\d+(?:\.\d+)?", raw):
                number = float(raw)
            else:
                parsed = _cartman_um_datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_cartman_um_timezone.utc)
                return parsed.timestamp()
        if number > 100000000000:
            number /= 1000.0
        if number < 1:
            return None
        return number
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _cartman_um_iso(value):
    stamp = _cartman_um_epoch(value)
    if stamp is None:
        return None
    try:
        return _cartman_um_datetime.fromtimestamp(stamp, _cartman_um_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _cartman_um_truthy(value):
    return str(value if value is not None else "").strip().lower() in {"1", "true", "yes", "y", "revoked", "disabled", "inactive"}


def _cartman_um_table_map(connection):
    cur = connection.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')")
    return {str(row[0]): str(row[1]) for row in cur.fetchall()}


def _cartman_um_quote_identifier(value):
    return '"' + str(value).replace('"', '""') + '"'


def _cartman_um_columns(connection, table):
    if table not in _cartman_um_table_map(connection):
        return set()
    cur = connection.execute("PRAGMA table_info(" + _cartman_um_quote_identifier(table) + ")")
    return {str(row[1]) for row in cur.fetchall()}


def _cartman_um_rows(connection, table, limit=20000, order_by=None):
    if table not in _cartman_um_table_map(connection):
        return []
    sql = "SELECT * FROM " + _cartman_um_quote_identifier(table)
    if order_by and order_by in _cartman_um_columns(connection, table):
        sql += " ORDER BY " + _cartman_um_quote_identifier(order_by) + " DESC"
    cur = connection.execute(sql + " LIMIT ?", (int(limit),))
    columns = [str(item[0]) for item in (cur.description or [])]
    result = []
    for row in cur.fetchall():
        if hasattr(row, "keys"):
            result.append(dict(row))
        else:
            result.append(dict(zip(columns, row)))
    return result


def _cartman_um_pick(row, names, default=None):
    if not isinstance(row, dict):
        return default
    for name in names:
        if name in row and row.get(name) is not None and str(row.get(name)).strip() != "":
            return row.get(name)
    return default


def _cartman_um_range(value):
    raw = str(value or "7d").strip().lower()
    if raw in {"1d", "24h"}:
        return "24h"
    if raw in {"7d", "15d", "30d"}:
        return raw
    if raw.endswith("h") and raw[:-1].isdigit():
        hours = int(raw[:-1])
        if 1 <= hours <= 720:
            return f"{hours}h"
    return "7d"


def _cartman_um_range_hours(value):
    normalized = _cartman_um_range(value)
    if normalized.endswith("h"):
        return int(normalized[:-1])
    return {"24h": 24, "7d": 168, "15d": 360, "30d": 720}[normalized]


def _cartman_um_datetime_bounds(start_value=None, end_value=None, selected_range="7d", now=None):
    """Return inclusive epoch window [start, end]; custom values are ISO timestamps."""
    current = float(now if now is not None else _cartman_um_time.time())
    has_start = str(start_value or "").strip() != ""
    has_end = str(end_value or "").strip() != ""
    if has_start or has_end:
        if not (has_start and has_end):
            raise _CartmanUserMetricsHTTPException(status_code=422, detail="Custom range requires both start and end date/time values.")
        lower = _cartman_um_epoch(start_value)
        upper = _cartman_um_epoch(end_value)
        if lower is None or upper is None:
            raise _CartmanUserMetricsHTTPException(status_code=422, detail="Custom start/end must be valid ISO date/time values.")
        if upper <= lower:
            raise _CartmanUserMetricsHTTPException(status_code=422, detail="Custom end date/time must be later than start date/time.")
        if upper > current + 60:
            raise _CartmanUserMetricsHTTPException(status_code=422, detail="Custom end date/time cannot be in the future.")
        return lower, upper, True
    lower = current - _cartman_um_range_hours(selected_range) * 3600
    return lower, current, False


def _cartman_um_trend_config(selected_range, now_dt, window_start=None, window_end=None):
    normalized = _cartman_um_range(selected_range)
    if window_start is not None and window_end is not None:
        span = max(1.0, float(window_end) - float(window_start))
        unit = 3600.0 if span <= 48 * 3600 else 86400.0
        count = max(1, min(48, int((span + unit - 1) // unit)))
        seconds = span / count
        first = _cartman_um_datetime.fromtimestamp(float(window_start), _cartman_um_timezone.utc)
        if span <= 24 * 3600:
            label_format = "%H:%M"
        elif span <= 3 * 86400:
            label_format = "%d %b %H:%M"
        else:
            label_format = "%d %b"
        return count, seconds, first, label_format
    hours = _cartman_um_range_hours(normalized)
    if normalized == "24h":
        count = 24
        seconds = 3600
        first = now_dt.replace(minute=0, second=0, microsecond=0) - _cartman_um_timedelta(hours=23)
        return count, seconds, first, "%H:%M"
    if normalized.endswith("h"):
        count = max(1, min(hours, 48))
        seconds = hours * 3600 / count
        first = _cartman_um_datetime.fromtimestamp(_cartman_um_time.time() - hours * 3600, _cartman_um_timezone.utc)
        return count, seconds, first, ("%H:%M" if hours <= 24 else "%d %b %H:%M")
    count = {"7d": 7, "15d": 15, "30d": 30}[normalized]
    first = now_dt.replace(hour=0, minute=0, second=0, microsecond=0) - _cartman_um_timedelta(days=count - 1)
    return count, 86400, first, ("%a" if count == 7 else "%d %b")


def _cartman_um_user(request):
    """Resolve identity using Cartman's existing authentication resolver; never trust request headers."""
    state = getattr(request, "state", None)
    for name in ("user", "current_user", "auth_user", "auth_account", "session_user"):
        candidate = getattr(state, name, None) if state is not None else None
        if hasattr(candidate, "model_dump"):
            candidate = candidate.model_dump()
        elif hasattr(candidate, "dict") and not isinstance(candidate, dict):
            candidate = candidate.dict()
        if isinstance(candidate, dict) and candidate.get("username") and candidate.get("role"):
            return candidate

    resolver = globals().get("_wm_user")
    if callable(resolver):
        try:
            return resolver(request)
        except Exception as exc:
            raise _CartmanUserMetricsHTTPException(status_code=401, detail="Authentication required.") from exc

    route = next((r for r in app.routes if getattr(r, "path", None) == "/api/auth/me" and "GET" in (getattr(r, "methods", set()) or set())), None)
    endpoint = getattr(route, "endpoint", None) if route else None
    if endpoint is None:
        raise _CartmanUserMetricsHTTPException(status_code=401, detail="Authentication resolver unavailable.")
    try:
        kwargs = {}
        for name, parameter in _cartman_um_inspect.signature(endpoint).parameters.items():
            if name in ("request", "req"):
                kwargs[name] = request
            elif parameter.default is _cartman_um_inspect.Parameter.empty and parameter.kind not in (_cartman_um_inspect.Parameter.VAR_POSITIONAL, _cartman_um_inspect.Parameter.VAR_KEYWORD):
                raise RuntimeError("Unsupported required authentication resolver parameter")
        result = endpoint(**kwargs)
        if _cartman_um_inspect.isawaitable(result):
            result = _cartman_um_asyncio.run(result)
        if hasattr(result, "body") and hasattr(result, "status_code"):
            if int(result.status_code) >= 400:
                raise _CartmanUserMetricsHTTPException(status_code=401, detail="Authentication required.")
            body = result.body
            if isinstance(body, bytes):
                result = _cartman_um_json.loads(body.decode("utf-8"))
            elif isinstance(body, str):
                result = _cartman_um_json.loads(body)
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        elif hasattr(result, "dict") and not isinstance(result, dict):
            result = result.dict()
        if isinstance(result, dict):
            for candidate in (result.get("user"), result.get("account"), result.get("current_user"), result):
                if hasattr(candidate, "model_dump"):
                    candidate = candidate.model_dump()
                if isinstance(candidate, dict) and candidate.get("username") and candidate.get("role"):
                    return candidate
    except _CartmanUserMetricsHTTPException:
        raise
    except Exception as exc:
        raise _CartmanUserMetricsHTTPException(status_code=401, detail="Could not resolve authenticated Cartman account.") from exc
    raise _CartmanUserMetricsHTTPException(status_code=401, detail="Authentication required.")


def _cartman_um_require_admin(request):
    user = _cartman_um_user(request)
    role = str(user.get("role") or user.get("role_name") or "").strip().lower().replace("_", " ").replace("-", " ")
    if role not in {"admin", "administrator", "super admin", "superadmin", "system administrator", "it administrator"}:
        raise _CartmanUserMetricsHTTPException(status_code=403, detail="Administrator access is required to view organization-wide user metrics.")
    return user


def _cartman_um_audit_source(connection):
    """Find a suitable existing audit/event table without assuming a table name or schema."""
    tables = _cartman_um_table_map(connection)
    preferred = ["iam_audit_logs", "iam_audit_events", "iam_audit_log", "audit_logs", "audit_events", "auth_audit_logs", "auth_events", "login_attempts", "security_audit_logs", "cartman_audit_logs"]
    candidates = [name for name in preferred if name in tables]
    candidates.extend(name for name in sorted(tables) if name not in candidates and _cartman_um_re.search(r"audit|activity|auth.*(event|log|attempt)|(event|log|attempt).*auth|login.*attempt", name, _cartman_um_re.I))
    time_names = ("created_at", "occurred_at", "event_at", "timestamp", "event_timestamp", "logged_at", "created", "time", "date", "recorded_at")
    action_names = ("action", "action_type", "event", "event_type", "operation", "activity", "message", "description", "details", "title", "event_name")
    actor_names = ("actor_username", "username", "user_name", "account_username", "created_by_username", "performed_by", "actor", "user_id", "account_id", "actor_id", "iam_user_id", "user")
    for table in candidates:
        cols = _cartman_um_columns(connection, table)
        stamp = next((c for c in time_names if c in cols), None)
        action = next((c for c in action_names if c in cols), None)
        actor = next((c for c in actor_names if c in cols), None)
        if stamp and action and actor:
            return {"table": table, "time": stamp, "action": action, "actor": actor, "columns": cols}
    return None


def _cartman_um_ensure_activity_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_user_activity_minutes (
            username TEXT NOT NULL,
            bucket_start INTEGER NOT NULL,
            active_seconds INTEGER NOT NULL DEFAULT 0 CHECK(active_seconds BETWEEN 0 AND 60),
            page_path TEXT NOT NULL DEFAULT '',
            recorded_at INTEGER NOT NULL,
            PRIMARY KEY(username, bucket_start)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_user_activity_minutes_bucket ON cartman_user_activity_minutes(bucket_start)")


def _cartman_um_snapshot(connection, selected_range="7d", start_at=None, end_at=None):
    now = _cartman_um_time.time()
    cutoff, period_end, custom_window = _cartman_um_datetime_bounds(start_at, end_at, selected_range, now)
    # This is first-party Cartman in-app usage telemetry, not desktop-wide monitoring.
    _cartman_um_ensure_activity_table(connection)
    tables = _cartman_um_table_map(connection)
    activity_rows = _cartman_um_rows(connection, "cartman_user_activity_minutes", 200000, "bucket_start")
    accounts = _cartman_um_rows(connection, "auth_accounts") if "auth_accounts" in tables else []
    iam_users = _cartman_um_rows(connection, "iam_users") if "iam_users" in tables else []
    sessions = _cartman_um_rows(connection, "auth_sessions", 50000, "last_seen") if "auth_sessions" in tables and "last_seen" in _cartman_um_columns(connection, "auth_sessions") else (_cartman_um_rows(connection, "auth_sessions", 50000) if "auth_sessions" in tables else [])
    devices = _cartman_um_rows(connection, "devices", 50000) if "devices" in tables else []
    audit_info = _cartman_um_audit_source(connection)
    audit_rows = _cartman_um_rows(connection, audit_info["table"], 50000, audit_info["time"]) if audit_info else []

    def norm(value):
        return str(value or "").strip().casefold()

    accounts_by_username = {}
    accounts_by_id = {}
    for row in accounts:
        username = str(_cartman_um_pick(row, ("username", "user_name", "login"), "") or "").strip()
        aid = str(_cartman_um_pick(row, ("id", "account_id"), "") or "")
        if username:
            accounts_by_username[norm(username)] = row
        if aid:
            accounts_by_id[aid] = row

    iam_by_username = {}
    iam_by_id = {}
    for row in iam_users:
        username = str(_cartman_um_pick(row, ("username", "user_name", "login"), "") or "").strip()
        uid = str(_cartman_um_pick(row, ("id", "user_id"), "") or "")
        if username:
            iam_by_username[norm(username)] = row
        if uid:
            iam_by_id[uid] = row

    # Create one combined identity per username, preferring the real IAM record where present.
    identities = {}
    for row in iam_users:
        username = str(_cartman_um_pick(row, ("username", "user_name", "login"), "") or "").strip()
        if not username:
            continue
        account = accounts_by_username.get(norm(username))
        uid = str(_cartman_um_pick(row, ("id", "user_id"), "") or "")
        aid = str(_cartman_um_pick(account or {}, ("id", "account_id"), "") or "")
        key = ("iam:" + uid) if uid else (("account:" + aid) if aid else ("username:" + username))
        identities[norm(username)] = {"user_key": key, "iam": row, "account": account, "username": username, "iam_user_id": uid, "account_id": aid}
    for row in accounts:
        username = str(_cartman_um_pick(row, ("username", "user_name", "login"), "") or "").strip()
        if not username or norm(username) in identities:
            continue
        aid = str(_cartman_um_pick(row, ("id", "account_id"), "") or "")
        key = ("account:" + aid) if aid else ("username:" + username)
        identities[norm(username)] = {"user_key": key, "iam": None, "account": row, "username": username, "iam_user_id": "", "account_id": aid}

    usage_seconds_by_username = {}
    usage_latest_by_username = {}
    usage_rows_by_username = {}
    for usage in activity_rows:
        username_norm = norm(_cartman_um_pick(usage, ("username", "user_name"), ""))
        if not username_norm or username_norm not in identities:
            continue
        stamp = _cartman_um_epoch(_cartman_um_pick(usage, ("bucket_start",)))
        if stamp is None or stamp < cutoff or stamp > period_end:
            continue
        try:
            seconds = max(0, min(60, int(usage.get("active_seconds") or 0)))
        except (TypeError, ValueError):
            seconds = 0
        usage_seconds_by_username[username_norm] = usage_seconds_by_username.get(username_norm, 0) + seconds
        usage_latest_by_username[username_norm] = max(stamp, usage_latest_by_username.get(username_norm, 0))
        usage_rows_by_username.setdefault(username_norm, []).append({
            "username_key": username_norm,
            "username": identities[username_norm]["username"],
            "_epoch": stamp,
            "occurred_at": _cartman_um_iso(stamp),
            "active_seconds": seconds,
            "page_path": str(usage.get("page_path") or "")[:240],
        })

    account_id_to_username = {aid: norm(row.get("username")) for aid, row in accounts_by_id.items()}
    iam_id_to_username = {uid: norm(row.get("username")) for uid, row in iam_by_id.items()}
    device_counts = {}
    device_tracking = False
    if "devices" in tables:
        device_columns = _cartman_um_columns(connection, "devices")
        assigned_column = next((c for c in ("assigned_user_id", "iam_user_id", "user_id") if c in device_columns), None)
        if assigned_column:
            device_tracking = True
            for device in devices:
                assigned = str(device.get(assigned_column) or "").strip()
                if assigned:
                    device_counts[assigned] = device_counts.get(assigned, 0) + 1

    session_rows_by_username = {}
    valid_sessions_by_username = {}
    active_sessions_by_username = {}
    session_activity_users = set()
    for session in sessions:
        account_id = str(_cartman_um_pick(session, ("account_id", "auth_account_id", "user_account_id"), "") or "")
        username_norm = account_id_to_username.get(account_id, "")
        if not username_norm:
            direct = _cartman_um_pick(session, ("username", "user_name"), "")
            username_norm = norm(direct)
        if not username_norm or username_norm not in identities:
            continue
        last_seen_raw = _cartman_um_pick(session, ("last_seen", "last_seen_at", "updated_at", "last_activity_at"))
        last_seen = _cartman_um_epoch(last_seen_raw)
        expires_raw = _cartman_um_pick(session, ("expires_at", "expires", "expiry"))
        expires = _cartman_um_epoch(expires_raw)
        revoked = _cartman_um_truthy(_cartman_um_pick(session, ("revoked", "is_revoked", "disabled"), 0))
        not_expired = expires is None or expires > now
        valid = (not revoked) and not_expired
        is_recent = last_seen is not None and last_seen >= now - 300
        if last_seen is not None and cutoff <= last_seen <= period_end:
            session_activity_users.add(username_norm)
        session_rows_by_username.setdefault(username_norm, []).append({"row": session, "last_seen": last_seen, "last_seen_at": _cartman_um_iso(last_seen_raw), "expires_at": _cartman_um_iso(expires_raw), "revoked": revoked, "valid": valid, "active": valid and is_recent})
        if valid:
            valid_sessions_by_username.setdefault(username_norm, []).append(session)
        if valid and is_recent:
            active_sessions_by_username.setdefault(username_norm, []).append(session)

    audit_events = []
    failed_supported = False
    audit_tracking = audit_info is not None
    failed_patterns = ("login failed", "failed login", "sign in failed", "signin failed", "authentication failed", "invalid password", "bad credentials", "auth failed", "login failure", "sign in failure", "signin failure", "access denied")
    failed_rows = []
    audit_action_values = []
    if audit_info:
        cols = audit_info["columns"]
        actor_col = audit_info["actor"]
        action_col = audit_info["action"]
        stamp_col = audit_info["time"]
        for row in audit_rows:
            stamp = _cartman_um_epoch(row.get(stamp_col))
            if stamp is None:
                continue
            action_value = str(row.get(action_col) or "").strip()
            action_lower = action_value.casefold()
            audit_action_values.append(action_lower)
            actor_value = str(row.get(actor_col) or "").strip()
            actor_field = actor_col.casefold()
            if actor_field in {"account_id", "actor_id", "auth_account_id"}:
                actor_norm = account_id_to_username.get(actor_value, "")
            elif actor_field in {"user_id", "iam_user_id"}:
                actor_norm = iam_id_to_username.get(actor_value, "") or account_id_to_username.get(actor_value, "")
            else:
                actor_norm = norm(actor_value)
                if actor_norm not in identities:
                    # Some audit schemas store a display name instead of a username.
                    match = next((key for key, identity in identities.items() if norm(_cartman_um_pick(identity.get("iam") or {}, ("name", "display_name", "full_name"), "")) == actor_norm or norm(_cartman_um_pick(identity.get("account") or {}, ("display_name", "name"), "")) == actor_norm), "")
                    actor_norm = match
            normalized_action = _cartman_um_re.sub(r"[_-]+", " ", action_lower)
            if cutoff <= stamp <= period_end:
                if any(pattern in normalized_action for pattern in failed_patterns) or (("login" in normalized_action or "sign in" in normalized_action or "signin" in normalized_action or "auth" in normalized_action) and any(token in normalized_action for token in ("fail", "denied", "invalid"))):
                    failed_rows.append(row)
                if actor_norm and actor_norm in identities:
                    detail = str(_cartman_um_pick(row, ("details", "description", "message", "summary", "resource", "target"), "") or "")
                    audit_events.append({"username_key": actor_norm, "username": identities[actor_norm]["username"], "occurred_at": _cartman_um_iso(stamp), "_epoch": stamp, "action": action_value or "Recorded event", "details": detail[:600], "source": audit_info["table"]})
        table_name_lower = audit_info["table"].lower()
        has_failed_auth_event = any(any(term in _cartman_um_re.sub(r"[_-]+", " ", action) for term in failed_patterns) for action in audit_action_values)
        has_auth_event_type = any(any(term in action for term in ("login", "sign in", "signin", "auth")) for action in audit_action_values)
        has_result_column = bool({"success", "result", "outcome"} & {column.casefold() for column in cols})
        failed_supported = bool(_cartman_um_re.search(r"auth|login|sign.?in|security", table_name_lower)) or has_failed_auth_event or (has_auth_event_type and has_result_column)

    # Merge real session/audit observations into each user row. Missing data remains null/unknown.
    users_out = []
    for username_key, identity in identities.items():
        iam = identity["iam"] or {}
        account = identity["account"] or {}
        name = str(_cartman_um_pick(iam, ("display_name", "name", "full_name", "fullName"), _cartman_um_pick(account, ("display_name", "name", "full_name"), identity["username"])) or identity["username"])
        email = _cartman_um_pick(iam, ("email", "email_address"), _cartman_um_pick(account, ("email", "email_address")))
        department = str(_cartman_um_pick(iam, ("department", "department_name"), _cartman_um_pick(account, ("department",), "")) or "")
        account_active = _cartman_um_pick(account, ("is_active", "active", "enabled"), 1)
        iam_status = str(_cartman_um_pick(iam, ("status", "state"), "") or "").strip().lower()
        disabled = str(account_active).strip().lower() in {"0", "false", "no", "disabled", "inactive"}
        if iam_status in {"inactive", "disabled", "deactivated", "suspended"}:
            disabled = True
        sessions_for_user = session_rows_by_username.get(username_key, [])
        active_for_user = active_sessions_by_username.get(username_key, [])
        valid_for_user = valid_sessions_by_username.get(username_key, [])
        # "Active" means foreground Cartman use observed by the first-party tracker,
        # not merely a session kept alive by periodic API polling.
        usage_last_seen = usage_latest_by_username.get(username_key)
        is_active_now = usage_last_seen is not None and usage_last_seen >= now - 300 and not disabled
        is_idle = bool(valid_for_user) and not is_active_now and not disabled
        if disabled:
            status = "Disabled"
        elif is_active_now:
            status = "Active"
        elif is_idle:
            status = "Idle"
        else:
            status = "Offline"
        last_session_epoch = max((item["last_seen"] for item in sessions_for_user if item["last_seen"] is not None), default=None)
        user_events = [event for event in audit_events if event["username_key"] == username_key]
        last_audit_epoch = max((event["_epoch"] for event in user_events), default=None)
        last_usage_epoch = usage_latest_by_username.get(username_key)
        last_epoch = max((v for v in (last_session_epoch, last_audit_epoch, last_usage_epoch) if v is not None), default=None)
        initials = "".join(part[:1] for part in name.split()[:2]).upper() or str(identity["username"][:2]).upper()
        users_out.append({
            "user_key": identity["user_key"], "name": name, "username": identity["username"],
            "email": str(email) if email else None, "department": department or None, "initials": initials,
            "status": status, "is_enabled": not disabled, "last_activity_at": _cartman_um_iso(last_epoch),
            "live_sessions": len(active_for_user), "valid_sessions": len(valid_for_user),
            "sessions_seen_in_period": sum(1 for item in sessions_for_user if item["last_seen"] is not None and cutoff <= item["last_seen"] <= period_end),
            "audit_events_in_period": len(user_events) if audit_tracking else None,
            "assigned_devices": device_counts.get(identity["iam_user_id"], 0) if device_tracking and identity["iam_user_id"] else (0 if device_tracking else None),
            "active_seconds": usage_seconds_by_username.get(username_key),
        })
    users_out.sort(key=lambda u: (0 if u["status"] == "Active" else 1 if u["status"] == "Idle" else 2 if u["status"] == "Offline" else 3, (u["name"] or "").casefold()))

    # Prefer measured in-app active minutes; if none are recorded, fall back to actual audit history.
    trend = []
    trend_source = "none"
    usage_rows_in_period = [row for rows in usage_rows_by_username.values() for row in rows]
    now_dt = _cartman_um_datetime.fromtimestamp(now, _cartman_um_timezone.utc)
    if usage_rows_in_period:
        trend_source = "usage"
        bucket_count, bucket_seconds, first_dt, label_format = _cartman_um_trend_config(selected_range, now_dt, cutoff if custom_window else None, period_end if custom_window else None)
        for index in range(bucket_count):
            bucket_start = first_dt.timestamp() + index * bucket_seconds
            bucket_end = bucket_start + bucket_seconds
            in_bucket = [row for row in usage_rows_in_period if bucket_start <= row["_epoch"] < bucket_end]
            active_users = {row["username_key"] for row in in_bucket if row["active_seconds"] > 0}
            label = _cartman_um_datetime.fromtimestamp(bucket_start, _cartman_um_timezone.utc).strftime(label_format)
            trend.append({"label": label, "active_users": len(active_users), "events": len(in_bucket), "bucket_start": _cartman_um_iso(bucket_start)})
    elif audit_tracking and audit_events:
        trend_source = "audit"
        bucket_count, bucket_seconds, first_dt, label_format = _cartman_um_trend_config(selected_range, now_dt, cutoff if custom_window else None, period_end if custom_window else None)
        for index in range(bucket_count):
            bucket_start = first_dt.timestamp() + index * bucket_seconds
            bucket_end = bucket_start + bucket_seconds
            event_users = {e["username_key"] for e in audit_events if bucket_start <= e["_epoch"] < bucket_end}
            event_count = sum(1 for e in audit_events if bucket_start <= e["_epoch"] < bucket_end)
            label = _cartman_um_datetime.fromtimestamp(bucket_start, _cartman_um_timezone.utc).strftime(label_format)
            trend.append({"label": label, "active_users": len(event_users), "events": event_count, "bucket_start": _cartman_um_iso(bucket_start)})

    users_with_audit = {event["username_key"] for event in audit_events}
    users_with_usage = {key for key, seconds in usage_seconds_by_username.items() if seconds > 0}
    users_with_activity = users_with_audit | users_with_usage
    active_user_now_count = sum(1 for user in users_out if user["status"] == "Active")
    live_session_count = sum(len(items) for items in active_sessions_by_username.values())
    valid_session_count = sum(len(items) for items in valid_sessions_by_username.values())
    total_active_seconds = sum(usage_seconds_by_username.values())
    observed_usage_seconds = [seconds for seconds in usage_seconds_by_username.values() if seconds > 0]
    tracking = {
        "iam": "iam_users" in tables or "auth_accounts" in tables,
        "sessions": "auth_sessions" in tables and "auth_accounts" in tables,
        "audit": audit_tracking,
        "failed_sign_ins": failed_supported,
        "active_time": "cartman_user_activity_minutes" in tables,
        "devices": device_tracking,
        "trend": bool(trend),
        "trend_source": trend_source,
        "usage_samples": len(usage_rows_in_period),
    }
    summary = {
        "total_users": len(users_out),
        "active_users_now": active_user_now_count,
        "live_sessions": live_session_count,
        "valid_sessions": valid_session_count,
        "active_users_in_period": len(users_with_activity) if (audit_tracking or usage_rows_in_period) else None,
        "users_with_usage": len(users_with_usage),
        "audit_events_in_period": len(audit_events) if audit_tracking else None,
        "failed_sign_ins": len(failed_rows) if failed_supported else None,
        "total_active_seconds": total_active_seconds if "cartman_user_activity_minutes" in tables else None,
        "average_active_seconds": (sum(observed_usage_seconds) / len(observed_usage_seconds)) if observed_usage_seconds else (0 if "cartman_user_activity_minutes" in tables else None),
    }
    activities_by_user = {}
    for event in sorted(audit_events, key=lambda item: item["_epoch"], reverse=True):
        key = event["username_key"]
        activities_by_user.setdefault(key, []).append({"occurred_at": event["occurred_at"], "action": event["action"], "details": event["details"], "source": event["source"]})
    for username_key, usage_for_user in usage_rows_by_username.items():
        for usage in usage_for_user:
            activities_by_user.setdefault(username_key, []).append({
                "occurred_at": usage["occurred_at"],
                "action": "Cartman active usage recorded",
                "details": f'{usage["active_seconds"]} active seconds · {usage["page_path"] or "/"}',
                "source": "Cartman activity tracker",
                "_epoch": usage["_epoch"],
            })
    for username_key in activities_by_user:
        activities_by_user[username_key].sort(key=lambda item: _cartman_um_epoch(item.get("occurred_at")) or 0, reverse=True)
    sessions_by_user_out = {}
    for username_key, identity in identities.items():
        rows = sorted(session_rows_by_username.get(username_key, []), key=lambda item: item["last_seen"] or 0, reverse=True)
        session_out = []
        for index, item in enumerate(rows[:25], start=1):
            if item["revoked"]:
                session_state = "Revoked"
            elif not item["valid"]:
                session_state = "Expired"
            elif item["active"]:
                session_state = "Active"
            else:
                session_state = "Valid / idle"
            session_out.append({"label": "Session " + str(index), "last_seen_at": item["last_seen_at"], "expires_at": item["expires_at"], "state": session_state})
        sessions_by_user_out[username_key] = session_out
    capabilities = {**tracking, "duration_note": "Active use is approximated from visible Cartman pages when recent interaction was observed (5-minute idle cutoff), in 1-minute buckets. No keystroke contents or desktop-wide activity are collected."}
    return {"range": "custom" if custom_window else _cartman_um_range(selected_range), "window_start": _cartman_um_iso(cutoff), "window_end": _cartman_um_iso(period_end), "generated_at": _cartman_um_iso(now), "summary": summary, "tracking": capabilities, "trend": trend, "users": users_out, "activities_by_user": activities_by_user, "sessions_by_user": sessions_by_user_out}


@app.post("/api/user-metrics/heartbeat")
def cartman_user_metrics_heartbeat(request: _CartmanUserMetricsRequest, payload: dict):
    # Any authenticated Cartman user can record only their own in-app active minute.
    user = _cartman_um_user(request)
    username = str(user.get("username") or user.get("user_name") or "").strip()
    if not username:
        raise _CartmanUserMetricsHTTPException(status_code=401, detail="Authenticated username unavailable.")
    try:
        active_seconds = int(payload.get("active_seconds", 0))
        bucket_start = int(payload.get("bucket_start", 0))
    except (TypeError, ValueError):
        raise _CartmanUserMetricsHTTPException(status_code=422, detail="Valid active_seconds and bucket_start are required.")
    if active_seconds < 1 or active_seconds > 60:
        raise _CartmanUserMetricsHTTPException(status_code=422, detail="active_seconds must be between 1 and 60.")
    now = int(_cartman_um_time.time())
    current_bucket = (now // 60) * 60
    if bucket_start < current_bucket - 60 or bucket_start > current_bucket + 30:
        raise _CartmanUserMetricsHTTPException(status_code=422, detail="bucket_start is outside the accepted current activity window.")
    bucket_start = (bucket_start // 60) * 60
    page_path = str(payload.get("page_path") or "/")[:500]
    if not page_path.startswith("/") or page_path.startswith("//"):
        page_path = "/"
    page_path = page_path.split("?", 1)[0].split("#", 1)[0][:240] or "/"
    with get_connection() as connection:
        _cartman_um_ensure_activity_table(connection)
        # Keep the minute-level history bounded; cleanup is attempted at most once per hour window.
        if now % 3600 < 30:
            connection.execute("DELETE FROM cartman_user_activity_minutes WHERE bucket_start < ?", (now - 90 * 86400,))
        connection.execute("""
            INSERT INTO cartman_user_activity_minutes(username,bucket_start,active_seconds,page_path,recorded_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(username,bucket_start) DO UPDATE SET
              active_seconds=MAX(cartman_user_activity_minutes.active_seconds, excluded.active_seconds),
              page_path=CASE WHEN excluded.active_seconds >= cartman_user_activity_minutes.active_seconds THEN excluded.page_path ELSE cartman_user_activity_minutes.page_path END,
              recorded_at=MAX(cartman_user_activity_minutes.recorded_at, excluded.recorded_at)
        """, (username, bucket_start, active_seconds, page_path, now))
    return {"ok": True, "bucket_start": bucket_start, "active_seconds": active_seconds}


@app.get("/api/user-metrics/summary")
def cartman_user_metrics_summary(request: _CartmanUserMetricsRequest, range: str = "7d", start: str = "", end: str = ""):
    _cartman_um_require_admin(request)
    with get_connection() as connection:
        snap = _cartman_um_snapshot(connection, range, start, end)
    return {"ok": True, "range": snap["range"], "generated_at": snap["generated_at"], "summary": snap["summary"], "tracking": snap["tracking"], "trend": snap["trend"]}


@app.get("/api/user-metrics/users")
def cartman_user_metrics_users(request: _CartmanUserMetricsRequest, range: str = "7d", start: str = "", end: str = "", q: str = "", status: str = "all", limit: int = 500):
    _cartman_um_require_admin(request)
    search = str(q or "").strip().casefold()
    state = str(status or "all").strip().casefold()
    limit = max(1, min(int(limit or 500), 1000))
    with get_connection() as connection:
        snap = _cartman_um_snapshot(connection, range, start, end)
    items = snap["users"]
    if search:
        items = [u for u in items if search in " ".join(str(u.get(k) or "") for k in ("name", "username", "email", "department")).casefold()]
    if state != "all":
        items = [u for u in items if str(u.get("status") or "").casefold() == state]
    total = len(items)
    return {"ok": True, "range": snap["range"], "generated_at": snap["generated_at"], "total": total, "items": items[:limit], "tracking": snap["tracking"]}


@app.get("/api/user-metrics/users/{user_key}")
def cartman_user_metrics_user_detail(request: _CartmanUserMetricsRequest, user_key: str, range: str = "7d", start: str = "", end: str = ""):
    _cartman_um_require_admin(request)
    with get_connection() as connection:
        snap = _cartman_um_snapshot(connection, range, start, end)
    user = next((item for item in snap["users"] if str(item.get("user_key")) == str(user_key)), None)
    if user is None:
        raise _CartmanUserMetricsHTTPException(status_code=404, detail="User not found in Cartman IAM/auth accounts.")
    username_key = str(user.get("username") or "").casefold()
    return {"ok": True, "range": snap["range"], "generated_at": snap["generated_at"], "user": user, "activity": snap["activities_by_user"].get(username_key, [])[:100], "sessions": snap["sessions_by_user"].get(username_key, [])[:25], "tracking": snap["tracking"]}

# END CARTMAN_USER_METRICS_REAL_API_V2


# CARTMAN_USER_METRICS_WORK_TIMELINE_V1
# Read-only selected-user ticket/task timelines. Table and column names are discovered
# from this Cartman's own SQLite schema; missing data is returned as unavailable.
def _cartman_um_work_norm(value):
    return str(value if value is not None else '').strip().casefold()


def _cartman_um_work_first(columns, candidates):
    by_lower = {str(col).casefold(): str(col) for col in columns}
    for name in candidates:
        if name.casefold() in by_lower:
            return by_lower[name.casefold()]
    return None


def _cartman_um_work_identity(connection, user):
    username = str(user.get('username') or '').strip()
    username_norm = _cartman_um_work_norm(username)
    name = str(user.get('name') or '').strip()
    email = str(user.get('email') or '').strip()
    user_key = str(user.get('user_key') or '')
    key_prefix, _, key_id = user_key.partition(':')
    text_ids = {x for x in (key_id, user_key) if x}
    names = {x for x in (username_norm, _cartman_um_work_norm(name), _cartman_um_work_norm(email)) if x}
    iam_id = key_id if key_prefix == 'iam' else ''
    account_id = key_id if key_prefix == 'account' else ''
    tables = _cartman_um_table_map(connection)
    for table, preferred in (('iam_users', ('id','user_id')), ('auth_accounts', ('id','account_id'))):
        if table not in tables:
            continue
        for row in _cartman_um_rows(connection, table, 20000):
            row_name = str(_cartman_um_pick(row, ('username','user_name','login'), '') or '').strip()
            if _cartman_um_work_norm(row_name) != username_norm:
                continue
            rid = str(_cartman_um_pick(row, preferred, '') or '').strip()
            if rid:
                text_ids.add(rid)
                if table == 'iam_users': iam_id = rid
                else: account_id = rid
            names.add(_cartman_um_work_norm(_cartman_um_pick(row, ('name','display_name','full_name'), '')))
            names.add(_cartman_um_work_norm(_cartman_um_pick(row, ('email','email_address'), '')))
    names.discard('')
    for val in (iam_id, account_id):
        if val: text_ids.add(val)
    return {'username': username, 'names': names, 'ids': text_ids, 'iam_id': iam_id, 'account_id': account_id, 'user_key': user_key}


def _cartman_um_work_value_matches(column, value, identity):
    if value is None or str(value).strip() == '':
        return False
    value_norm = _cartman_um_work_norm(value)
    col = str(column).casefold()
    if col.endswith('_id') or col in {'id','actor_id','user_id','account_id','owner_id','assignee_id','requester_id','assigned_to_id','completed_by_user_id'}:
        return str(value).strip() in identity['ids']
    return value_norm in identity['names']


def _cartman_um_work_related(row, identity, text_fields, id_fields):
    for col in text_fields:
        if col in row and _cartman_um_work_value_matches(col, row.get(col), identity):
            return True
    for col in id_fields:
        if col in row and _cartman_um_work_value_matches(col, row.get(col), identity):
            return True
    return False


def _cartman_um_work_cutoff(selected_range, start_at=None, end_at=None):
    lower, _, _ = _cartman_um_datetime_bounds(start_at, end_at, selected_range)
    return lower

def _cartman_um_work_table_events(connection, user, selected_range, start_at=None, end_at=None):
    tables = _cartman_um_table_map(connection)
    identity = _cartman_um_work_identity(connection, user)
    cutoff, period_end, _custom_window = _cartman_um_datetime_bounds(start_at, end_at, selected_range)
    text_actor_fields = (
        'username','user_name','actor_username','created_by_username','created_by','creator',
        'requester_username','requester','requested_by','opened_by_username','opened_by',
        'assigned_to_username','assigned_to','assignee_username','assignee','owner_username','owner',
        'updated_by_username','updated_by','resolved_by_username','resolved_by','closed_by_username',
        'closed_by','completed_by_username','completed_by','performed_by','actor','assigned_user'
    )
    id_actor_fields = (
        'user_id','iam_user_id','account_id','actor_id','created_by_user_id','requester_user_id',
        'assigned_user_id','assigned_to_id','assignee_id','owner_id','completed_by_user_id',
        'resolved_by_user_id','closed_by_user_id','updated_by_user_id'
    )

    # Map explicit user targets for work_items if this table is present.
    task_targets = {}
    if 'work_item_targets' in tables:
        target_cols = _cartman_um_columns(connection, 'work_item_targets')
        task_col = _cartman_um_work_first(target_cols, ('task_key','work_item_key','task_id'))
        type_col = _cartman_um_work_first(target_cols, ('target_type','type'))
        id_col = _cartman_um_work_first(target_cols, ('target_id','user_id','iam_user_id'))
        name_col = _cartman_um_work_first(target_cols, ('target_name','username','user_name','name'))
        if task_col:
            for target in _cartman_um_rows(connection, 'work_item_targets', 50000, 'assigned_at' if 'assigned_at' in target_cols else None):
                if type_col and str(target.get(type_col) or '').casefold() not in {'user','iam_user','account','person'}:
                    continue
                matched = False
                if id_col and target.get(id_col) is not None:
                    matched = _cartman_um_work_value_matches(id_col, target.get(id_col), identity)
                    # Some target_id fields are text identifiers, so compare without assuming a numeric DB type.
                    matched = matched or str(target.get(id_col)).strip() in identity['ids']
                if name_col and target.get(name_col) is not None:
                    matched = matched or _cartman_um_work_norm(target.get(name_col)) in identity['names']
                if matched:
                    task_targets.setdefault(str(target.get(task_col) or ''), []).append(target)

    task_rows = []
    task_tracking = {'available': 'work_items' in tables, 'source': 'work_items' if 'work_items' in tables else None}
    if 'work_items' in tables:
        task_cols = _cartman_um_columns(connection, 'work_items')
        task_key_col = _cartman_um_work_first(task_cols, ('task_key','work_item_key','id'))
        task_title_col = _cartman_um_work_first(task_cols, ('title','name','summary'))
        task_created_col = _cartman_um_work_first(task_cols, ('created_at','created','created_on'))
        task_updated_col = _cartman_um_work_first(task_cols, ('updated_at','updated','modified_at','last_updated_at'))
        task_completed_col = _cartman_um_work_first(task_cols, ('completed_at','finished_at','done_at','closed_at'))
        task_status_col = _cartman_um_work_first(task_cols, ('status','state'))
        task_completed_by_col = _cartman_um_work_first(task_cols, ('completed_by_username','completed_by','completed_by_user_id'))
        for row in _cartman_um_rows(connection, 'work_items', 50000, task_created_col):
            key = str(row.get(task_key_col) or '') if task_key_col else ''
            assigned = _cartman_um_work_related(row, identity,
                ('owner','assigned_to','assigned_to_username','assigned_username','assignee','assignee_username','assigned_user'),
                ('assigned_user_id','assigned_to_id','assignee_id','owner_id','user_id','iam_user_id'))
            created_by = _cartman_um_work_related(row, identity,
                ('created_by_username','created_by','creator','created_by_display_name'),
                ('created_by_user_id','created_by_id'))
            completed_by = False
            if task_completed_by_col:
                completed_by = _cartman_um_work_value_matches(task_completed_by_col, row.get(task_completed_by_col), identity)
                if not completed_by and not task_completed_by_col.endswith('_id'):
                    completed_by = _cartman_um_work_norm(row.get(task_completed_by_col)) in identity['names']
            assigned = assigned or bool(task_targets.get(key))
            if not (assigned or created_by or completed_by):
                continue
            created_raw = row.get(task_created_col) if task_created_col else None
            updated_raw = row.get(task_updated_col) if task_updated_col else None
            completed_raw = row.get(task_completed_col) if task_completed_col else None
            time_values = [v for v in (created_raw, updated_raw, completed_raw) if _cartman_um_epoch(v) is not None]
            in_range = any(_cartman_um_epoch(v) is not None and cutoff <= _cartman_um_epoch(v) <= period_end for v in time_values)
            status_value = str(row.get(task_status_col) or '') if task_status_col else ''
            if not in_range:
                continue
            task_rows.append({
                'key': key or 'Task', 'title': str(row.get(task_title_col) or 'Untitled task') if task_title_col else 'Untitled task',
                'status': status_value or 'Unknown',
                'created_at': _cartman_um_iso(created_raw), 'updated_at': _cartman_um_iso(updated_raw),
                'completed_at': _cartman_um_iso(completed_raw),
                'completed_by': str(row.get(task_completed_by_col) or '') if task_completed_by_col else '',
                'completed_by_user': completed_by, 'assigned_to_user': assigned,
                'completed_at_in_range': bool(_cartman_um_epoch(completed_raw) is not None and cutoff <= _cartman_um_epoch(completed_raw) <= period_end),
                'created_by_user': created_by, '_sort': max((_cartman_um_epoch(v) or 0 for v in time_values), default=0)
            })
    task_rows.sort(key=lambda row: row['_sort'], reverse=True)
    for row in task_rows:
        row.pop('_sort', None)

    # Ticket data is discovered only from ticket-shaped tables with timestamps and identity columns.
    ticket_rows = []
    ticket_tables = []
    ticket_event_tables = []
    exclusions = ('attachment','comment','note','watcher','category','tag','sla','lookup','setting')
    ticket_actor_candidates = set(text_actor_fields + id_actor_fields)
    for table in sorted(tables):
        lower_table = table.casefold()
        if 'ticket' not in lower_table:
            continue
        cols = _cartman_um_columns(connection, table)
        if any(term in lower_table for term in ('event','history','activity','timeline','audit','comment','note')):
            stamp_col = _cartman_um_work_first(cols, ('occurred_at','event_at','created_at','timestamp','logged_at','recorded_at','updated_at'))
            action_col = _cartman_um_work_first(cols, ('action','action_type','event','event_type','operation','status','message','description','title'))
            actor_col = _cartman_um_work_first(cols, ('actor_username','username','user_name','created_by_username','performed_by','actor','user_id','account_id','actor_id','iam_user_id'))
            if stamp_col and action_col and actor_col:
                ticket_event_tables.append((table, cols, stamp_col, action_col, actor_col))
            continue
        if any(term in lower_table for term in exclusions):
            continue
        key_col = _cartman_um_work_first(cols, ('ticket_key','ticket_number','ticket_no','number','reference','id'))
        title_col = _cartman_um_work_first(cols, ('title','subject','summary','ticket_title','name'))
        stamp_cols = {
            'created_at': _cartman_um_work_first(cols, ('created_at','created','opened_at','submitted_at','requested_at')),
            'updated_at': _cartman_um_work_first(cols, ('updated_at','updated','modified_at','last_updated_at')),
            'resolved_at': _cartman_um_work_first(cols, ('resolved_at','resolved_on')),
            'closed_at': _cartman_um_work_first(cols, ('closed_at','closed_on','completed_at')),
        }
        actor_cols = [col for col in (text_actor_fields + id_actor_fields) if col in cols]
        if key_col and title_col and any(stamp_cols.values()) and actor_cols:
            ticket_tables.append((table, cols, key_col, title_col, stamp_cols, actor_cols))

    table_availability = bool(ticket_tables or ticket_event_tables)
    ticket_tracking = {'available': table_availability, 'sources': [entry[0] for entry in ticket_tables] + [entry[0] for entry in ticket_event_tables]}
    for table, cols, key_col, title_col, stamp_cols, actor_cols in ticket_tables:
        status_col = _cartman_um_work_first(cols, ('status','state','ticket_status'))
        priority_col = _cartman_um_work_first(cols, ('priority','severity'))
        for row in _cartman_um_rows(connection, table, 50000):
            if not _cartman_um_work_related(row, identity, text_actor_fields, id_actor_fields):
                continue
            raw_dates = {kind: (row.get(col) if col else None) for kind, col in stamp_cols.items()}
            epochs = [_cartman_um_epoch(v) for v in raw_dates.values()]
            epochs = [v for v in epochs if v is not None]
            if not epochs or not any(cutoff <= value <= period_end for value in epochs):
                continue
            ticket_rows.append({
                'key': str(row.get(key_col) or row.get('id') or 'Ticket'), 'title': str(row.get(title_col) or 'Untitled ticket'),
                'status': str(row.get(status_col) or 'Unknown') if status_col else 'Unknown',
                'priority': str(row.get(priority_col) or '') if priority_col else '',
                **{kind: _cartman_um_iso(value) for kind, value in raw_dates.items()},
                'source': table, '_sort': max(epochs)
            })

    # A ticket audit/history table can supply event timestamps even when no main ticket table exists.
    ticket_event_count = 0
    if not ticket_tables:
        for table, cols, stamp_col, action_col, actor_col in ticket_event_tables:
            for row in _cartman_um_rows(connection, table, 50000, stamp_col):
                actor_value = row.get(actor_col)
                if not _cartman_um_work_value_matches(actor_col, actor_value, identity):
                    continue
                stamp = _cartman_um_epoch(row.get(stamp_col))
                if stamp is None or stamp < cutoff or stamp > period_end:
                    continue
                action = str(row.get(action_col) or 'Ticket activity')
                key_col = _cartman_um_work_first(cols, ('ticket_key','ticket_number','ticket_id','ticket_no','resource_id','subject'))
                title_col = _cartman_um_work_first(cols, ('title','subject','summary','message','description'))
                ticket_rows.append({
                    'key': str(row.get(key_col) or 'Ticket event') if key_col else 'Ticket event',
                    'title': str(row.get(title_col) or action) if title_col else action,
                    'status': action, 'priority': '', 'created_at': _cartman_um_iso(row.get(stamp_col)),
                    'updated_at': None, 'resolved_at': None, 'closed_at': None, 'source': table, '_sort': stamp,
                    'event_action': action
                })
                ticket_event_count += 1

    # Fall back to ticket-related events from the established audit source if the schema has no ticket table.
    if not ticket_tables and not ticket_event_tables:
        audit_info = _cartman_um_audit_source(connection)
        if audit_info:
            for row in _cartman_um_rows(connection, audit_info['table'], 50000, audit_info['time']):
                action = str(row.get(audit_info['action']) or '').strip()
                normalized = _cartman_um_re.sub(r'[_-]+', ' ', action.casefold())
                if 'ticket' not in normalized:
                    continue
                stamp = _cartman_um_epoch(row.get(audit_info['time']))
                if stamp is None or stamp < cutoff or stamp > period_end:
                    continue
                if not _cartman_um_work_value_matches(audit_info['actor'], row.get(audit_info['actor']), identity):
                    # Reuse the canonical name/ID matching for the audit actor column.
                    actor_col = audit_info['actor']
                    actor_val = row.get(actor_col)
                    actor_norm = _cartman_um_work_norm(actor_val)
                    if actor_norm not in identity['names'] and str(actor_val or '').strip() not in identity['ids']:
                        continue
                details_col = _cartman_um_work_first(_cartman_um_columns(connection, audit_info['table']), ('details','description','message','resource','target'))
                ticket_rows.append({'key':'Ticket event','title':str(row.get(details_col) or action) if details_col else action,
                    'status': action, 'priority':'', 'created_at':_cartman_um_iso(row.get(audit_info['time'])),
                    'updated_at':None,'resolved_at':None,'closed_at':None,'source':audit_info['table'],'_sort':stamp,'event_action':action})

    # Deduplicate and sort records by latest known event.
    seen = set(); deduped = []
    for row in sorted(ticket_rows, key=lambda item: item.get('_sort', 0), reverse=True):
        sig = (row.get('source'), row.get('key'), row.get('title'), row.get('created_at'), row.get('updated_at'), row.get('resolved_at'), row.get('closed_at'), row.get('event_action'))
        if sig in seen: continue
        seen.add(sig); deduped.append(row)
    for row in deduped: row.pop('_sort', None)
    return {
        'range': _cartman_um_range(selected_range), 'tickets': deduped[:100], 'ticket_tracking': ticket_tracking,
        'tasks': task_rows[:100], 'task_tracking': task_tracking,
        'notes': {'ticket': 'Ticket history is sourced from ticket-shaped database tables or recorded ticket audit events. An empty list is not treated as proof that no ticket system exists.',
                  'task': 'Task completion time is shown only when work_items.completed_at is recorded; update time is not silently substituted.'}
    }


@app.get('/api/user-metrics/users/{user_key}/work-timeline')
def cartman_user_metrics_work_timeline(request: _CartmanUserMetricsRequest, user_key: str, range: str = '7d', start: str = "", end: str = ""):
    _cartman_um_require_admin(request)
    with get_connection() as connection:
        snap = _cartman_um_snapshot(connection, range, start, end)
        user = next((item for item in snap['users'] if str(item.get('user_key')) == str(user_key)), None)
        if user is None:
            raise _CartmanUserMetricsHTTPException(status_code=404, detail='User not found in Cartman IAM/auth accounts.')
        activity = _cartman_um_work_table_events(connection, user, range, start, end)
    return {'ok': True, 'user_key': user_key, **activity}

# CARTMAN_USER_METRICS_SELECTED_CHART_API_V1
@app.get('/api/user-metrics/users/{user_key}/chart-timeline')
def cartman_user_metrics_selected_chart_timeline(request: _CartmanUserMetricsRequest, user_key: str, range: str = '7d', start: str = "", end: str = ""):
    """Return real usage-minute buckets for one user; never synthesize history."""
    _cartman_um_require_admin(request)
    with get_connection() as connection:
        snap = _cartman_um_snapshot(connection, range, start, end)
        user = next((item for item in snap['users'] if str(item.get('user_key')) == str(user_key)), None)
        if user is None:
            raise _CartmanUserMetricsHTTPException(status_code=404, detail='User not found in Cartman IAM/auth accounts.')
        table = 'cartman_user_activity_minutes'
        tables = _cartman_um_table_map(connection)
        available = table in tables
        usage = []
        if available:
            columns = _cartman_um_columns(connection, table)
            username_col = _cartman_um_work_first(columns, ('username', 'user_name', 'login'))
            bucket_col = _cartman_um_work_first(columns, ('bucket_start', 'started_at', 'minute_start', 'occurred_at'))
            seconds_col = _cartman_um_work_first(columns, ('active_seconds', 'seconds', 'duration_seconds'))
            page_col = _cartman_um_work_first(columns, ('page_path', 'path', 'route'))
            if not (username_col and bucket_col and seconds_col):
                available = False
            else:
                sql = 'SELECT * FROM ' + _cartman_um_quote_identifier(table)
                sql += ' WHERE lower(CAST(' + _cartman_um_quote_identifier(username_col) + ' AS TEXT)) = lower(?)'
                sql += ' ORDER BY ' + _cartman_um_quote_identifier(bucket_col) + ' DESC LIMIT ?'
                cursor = connection.execute(sql, (str(user.get('username') or ''), 50000))
                names = [str(col[0]) for col in (cursor.description or [])]
                cutoff, period_end, _custom_window = _cartman_um_datetime_bounds(start, end, range)
                for raw in cursor.fetchall():
                    row = dict(raw) if hasattr(raw, 'keys') else dict(zip(names, raw))
                    stamp = _cartman_um_epoch(row.get(bucket_col))
                    seconds = max(0, min(60, int(row.get(seconds_col) or 0)))
                    if stamp is None or stamp < cutoff or stamp > period_end or seconds <= 0:
                        continue
                    usage.append({
                        'bucket_start': _cartman_um_iso(stamp),
                        'active_seconds': seconds,
                        'page_path': str(row.get(page_col) or '') if page_col else ''
                    })
        usage.sort(key=lambda item: item.get('bucket_start') or '')
    return {
        'ok': True, 'user_key': user_key, 'range': 'custom' if _custom_window else _cartman_um_range(range), 'window_start': _cartman_um_iso(cutoff), 'window_end': _cartman_um_iso(period_end),
        'usage_available': bool(available), 'usage': usage,
        'generated_at': _cartman_um_iso(_cartman_um_time.time())
    }
# END CARTMAN_USER_METRICS_SELECTED_CHART_API_V1

# END CARTMAN_USER_METRICS_WORK_TIMELINE_V1


# CARTMAN_USER_METRICS_TIME_FILTER_V1


# CARTMAN_USER_METRICS_DATETIME_RANGE_V1

# CARTMAN_ALERTS_MANAGEMENT_API_V1
# Real Alerts workflow backed by existing monitoring_alerts records.
import inspect as _cartman_am_inspect
import json as _cartman_am_json
import re as _cartman_am_re
from datetime import datetime as _cartman_am_datetime, timezone as _cartman_am_timezone
from fastapi import Request as _CartmanAlertsRequest, HTTPException as _CartmanAlertsHTTPException


def _cartman_am_rowdict(row, description=None):
    if row is None:
        return None
    try:
        return dict(row)
    except Exception:
        cols = [item[0] for item in (description or [])]
        return dict(zip(cols, row))


def _cartman_am_tables(conn):
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}


def _cartman_am_columns(conn, table):
    if table not in _cartman_am_tables(conn):
        return set()
    safe = '"' + str(table).replace('"', '""') + '"'
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(" + safe + ")").fetchall()}


def _cartman_am_ensure_schema(conn):
    tables = _cartman_am_tables(conn)
    if "monitoring_alerts" not in tables:
        raise _CartmanAlertsHTTPException(status_code=503, detail="The monitoring_alerts table is not initialized yet. Start Cartman and check monitoring setup.")
    cols = _cartman_am_columns(conn, "monitoring_alerts")
    required = {"id", "status"}
    missing = required - cols
    if missing:
        raise _CartmanAlertsHTTPException(status_code=503, detail="monitoring_alerts is missing required columns: " + ", ".join(sorted(missing)))
    additions = {
        "alert_code": "TEXT",
        "completed_at": "TEXT",
        "completed_by": "TEXT",
        "completion_note": "TEXT",
    }
    for name, kind in additions.items():
        if name not in cols:
            conn.execute('ALTER TABLE monitoring_alerts ADD COLUMN "' + name + '" ' + kind)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cartman_alert_action_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            alert_code TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS cartman_alert_code_after_insert
        AFTER INSERT ON monitoring_alerts
        WHEN NEW.alert_code IS NULL OR TRIM(NEW.alert_code) = ''
        BEGIN
            UPDATE monitoring_alerts SET alert_code = 'AL' || printf('%03d', NEW.id) WHERE id = NEW.id;
        END
    """)
    # Stable code for historic alerts; the code follows the durable numeric row ID.
    conn.execute("UPDATE monitoring_alerts SET alert_code = 'AL' || printf('%03d', id) WHERE alert_code IS NULL OR TRIM(alert_code) = ''")
    return _cartman_am_columns(conn, "monitoring_alerts")


def _cartman_am_as_user(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict") and not isinstance(value, dict):
        value = value.dict()
    if not isinstance(value, dict):
        return None
    for key in ("user", "current_user", "account", "currentUser"):
        nested = value.get(key)
        if hasattr(nested, "model_dump"):
            nested = nested.model_dump()
        elif hasattr(nested, "dict") and not isinstance(nested, dict):
            nested = nested.dict()
        if isinstance(nested, dict) and (nested.get("username") or nested.get("email") or nested.get("id")):
            value = nested
            break
    if not (value.get("username") or value.get("email") or value.get("id")):
        return None
    return value


async def _cartman_am_current_user(request):
    state = getattr(request, "state", None)
    if state is not None:
        for attr in ("user", "current_user", "auth_user", "auth_account", "session_user"):
            candidate = _cartman_am_as_user(getattr(state, attr, None))
            if candidate:
                return candidate
    # Prefer the shared User Metrics auth resolver when it exists, then Cartman's older resolver.
    for resolver_name in ("_cartman_um_user", "_wm_user", "get_current_user", "resolve_current_user"):
        resolver = globals().get(resolver_name)
        if not callable(resolver):
            continue
        try:
            result = resolver(request)
            if _cartman_am_inspect.isawaitable(result):
                result = await result
            candidate = _cartman_am_as_user(result)
            if candidate:
                return candidate
        except _CartmanAlertsHTTPException:
            raise
        except Exception:
            continue
    raise _CartmanAlertsHTTPException(status_code=401, detail="Authentication required.")


def _cartman_am_role(user):
    role = user.get("role") or user.get("role_name") or user.get("roleName") or ""
    if isinstance(role, dict):
        role = role.get("name") or role.get("key") or ""
    return str(role).strip().casefold().replace("_", " ").replace("-", " ")


async def _cartman_am_authorize(request, complete=False):
    user = await _cartman_am_current_user(request)
    role = _cartman_am_role(user)
    view_roles = {"admin", "administrator", "super admin", "superadmin", "network admin", "support agent", "security admin", "it administrator", "read only", "viewer", "analyst"}
    action_roles = {"admin", "administrator", "super admin", "superadmin", "network admin", "support agent", "security admin", "it administrator"}
    allowed = action_roles if complete else view_roles
    if role not in allowed:
        raise _CartmanAlertsHTTPException(status_code=403, detail="Your Cartman role may not perform this alert action." if complete else "Your Cartman role may not view organization-wide alerts.")
    return user, (role in action_roles)


def _cartman_am_completed(row):
    status = str(row.get("status") or "").strip().casefold()
    return status in {"resolved", "complete", "completed", "closed", "cleared", "done"} or bool(row.get("completed_at") or row.get("resolved_at"))


def _cartman_am_parse_time(value):
    if not value:
        return None
    try:
        raw = str(value).strip().replace("Z", "+00:00")
        parsed = _cartman_am_datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_cartman_am_timezone.utc)
        return parsed.timestamp()
    except Exception:
        return None


def _cartman_am_item(row, device_names):
    alert_id = row.get("id")
    code = str(row.get("alert_code") or ("AL" + (f"{int(alert_id):03d}" if str(alert_id).isdigit() else str(alert_id))))
    device_id = row.get("device_id") or row.get("resource_id") or row.get("host_id")
    status = str(row.get("status") or "open")
    completed = _cartman_am_completed(row)
    created = row.get("created_at") or row.get("triggered_at") or row.get("first_seen_at")
    completed_at = row.get("completed_at") or row.get("resolved_at")
    severity = str(row.get("severity") or row.get("level") or "warning").strip().casefold()
    return {
        "id": alert_id,
        "alert_code": code,
        "title": str(row.get("title") or row.get("name") or "Monitoring alert"),
        "severity": severity,
        "status": "completed" if completed else ("acknowledged" if status.casefold() in {"acknowledged", "acknowledge", "in_progress", "in progress"} else "open"),
        "raw_status": status,
        "details": str(row.get("details") or row.get("message") or row.get("description") or ""),
        "device_id": device_id,
        "device_name": device_names.get(str(device_id), str(row.get("device_name") or row.get("hostname") or device_id or "Unknown device")),
        "created_at": created,
        "completed_at": completed_at,
        "completed_by": row.get("completed_by") or row.get("resolved_by") or "",
        "completion_note": row.get("completion_note") or "",
        "is_completed": completed,
    }


def _cartman_am_load_items(conn):
    columns = _cartman_am_ensure_schema(conn)
    safe_cols = _cartman_am_columns(conn, "monitoring_alerts")
    raw_rows = conn.execute("SELECT * FROM monitoring_alerts ORDER BY id DESC LIMIT 20000").fetchall()
    rows = []
    for row in raw_rows:
        try:
            rows.append(dict(row))
        except Exception:
            rows.append({str(desc[0]): value for desc, value in zip(conn.execute("SELECT * FROM monitoring_alerts LIMIT 0").description or [], row)})
    device_names = {}
    if "devices" in _cartman_am_tables(conn):
        dev_cols = _cartman_am_columns(conn, "devices")
        if "id" in dev_cols and "name" in dev_cols:
            for device_row in conn.execute("SELECT id, name FROM devices").fetchall():
                try:
                    device_names[str(device_row["id"])] = str(device_row["name"])
                except Exception:
                    device_names[str(device_row[0])] = str(device_row[1])
    items = [_cartman_am_item(row, device_names) for row in rows]
    return items


@app.get("/api/alerts-management")
async def cartman_alerts_management_list(request: _CartmanAlertsRequest, view: str = "live", q: str = "", severity: str = "all", status: str = "all", sort_by: str = "created_at", sort_dir: str = "desc", limit: int = 8, offset: int = 0):
    _, can_complete = await _cartman_am_authorize(request, complete=False)
    view = "completed" if str(view).casefold() == "completed" else "live"
    severity_filter = str(severity or "all").casefold()
    status_filter = str(status or "all").casefold()
    query = str(q or "").strip().casefold()[:200]
    allowed_sorts = {"created_at", "completed_at", "severity", "device_name", "title", "alert_code", "status"}
    sort_by = sort_by if sort_by in allowed_sorts else "created_at"
    sort_dir = "asc" if str(sort_dir).casefold() == "asc" else "desc"
    limit = max(1, min(int(limit or 8), 50)); offset = max(0, min(int(offset or 0), 1000000))
    with get_connection() as connection:
        items = _cartman_am_load_items(connection)
    live_count = sum(1 for item in items if not item["is_completed"])
    completed_count = len(items) - live_count
    critical_open_count = sum(1 for item in items if not item["is_completed"] and item["severity"] in {"critical", "error", "high"})
    items = [item for item in items if item["is_completed"] == (view == "completed")]
    if severity_filter in {"critical", "high", "warning", "error", "info", "low"}:
        items = [item for item in items if item["severity"] == severity_filter]
    if status_filter in {"open", "acknowledged"}:
        items = [item for item in items if item["status"] == status_filter]
    if query:
        items = [item for item in items if query in " ".join(str(item.get(key) or "") for key in ("alert_code", "title", "severity", "status", "details", "device_id", "device_name")).casefold()]
    severity_order = {"critical": 0, "error": 1, "high": 2, "warning": 3, "medium": 4, "low": 5, "info": 6}
    if sort_by == "severity":
        items.sort(key=lambda item: severity_order.get(item["severity"], 99), reverse=(sort_dir == "desc"))
    elif sort_by in {"created_at", "completed_at"}:
        items.sort(key=lambda item: _cartman_am_parse_time(item.get(sort_by)) or 0, reverse=(sort_dir == "desc"))
    else:
        items.sort(key=lambda item: str(item.get(sort_by) or "").casefold(), reverse=(sort_dir == "desc"))
    total = len(items)
    return {"ok": True, "view": view, "items": items[offset:offset + limit], "total": total, "offset": offset, "limit": limit, "counts": {"live": live_count, "completed": completed_count, "critical_open": critical_open_count}, "can_complete": can_complete, "source": "monitoring_alerts"}


@app.get("/api/alerts-management/{alert_id}")
async def cartman_alerts_management_detail(alert_id: int, request: _CartmanAlertsRequest):
    await _cartman_am_authorize(request, complete=False)
    with get_connection() as connection:
        items = _cartman_am_load_items(connection)
    item = next((candidate for candidate in items if str(candidate["id"]) == str(alert_id)), None)
    if not item:
        raise _CartmanAlertsHTTPException(status_code=404, detail="Alert not found.")
    return {"ok": True, "item": item}


@app.post("/api/alerts-management/{alert_id}/complete")
async def cartman_alerts_management_complete(alert_id: int, payload: dict, request: _CartmanAlertsRequest):
    user, _ = await _cartman_am_authorize(request, complete=True)
    explanation = str((payload or {}).get("explanation") or "").strip()
    if len(explanation) < 5:
        raise _CartmanAlertsHTTPException(status_code=422, detail="Add a completion explanation of at least 5 characters.")
    if len(explanation) > 4000:
        raise _CartmanAlertsHTTPException(status_code=422, detail="Completion explanation must be 4000 characters or fewer.")
    actor = str(user.get("username") or user.get("email") or user.get("id") or "unknown")[:160]
    now = _cartman_am_datetime.now(_cartman_am_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with get_connection() as connection:
        _cartman_am_ensure_schema(connection)
        row = connection.execute("SELECT * FROM monitoring_alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            raise _CartmanAlertsHTTPException(status_code=404, detail="Alert not found.")
        try:
            current = dict(row)
        except Exception:
            current = {}
        if _cartman_am_completed(current):
            raise _CartmanAlertsHTTPException(status_code=409, detail="This alert is already completed.")
        columns = _cartman_am_columns(connection, "monitoring_alerts")
        code = str(current.get("alert_code") or ("AL" + f"{int(alert_id):03d}"))
        updates = {"alert_code": code, "completed_at": now, "completed_by": actor, "completion_note": explanation}
        if "status" in columns: updates["status"] = "resolved"
        if "resolved_at" in columns: updates["resolved_at"] = now
        if "resolved_by" in columns: updates["resolved_by"] = actor
        if "updated_at" in columns: updates["updated_at"] = now
        assignments = ", ".join('"' + key + '"=?' for key in updates)
        connection.execute("UPDATE monitoring_alerts SET " + assignments + " WHERE id=?", (*updates.values(), alert_id))
        connection.execute("INSERT INTO cartman_alert_action_history (alert_id, alert_code, action, actor_username, description, occurred_at) VALUES (?, ?, 'complete', ?, ?, ?)", (alert_id, code, actor, explanation, now))
        updated = connection.execute("SELECT * FROM monitoring_alerts WHERE id=?", (alert_id,)).fetchone()
        try: updated = dict(updated)
        except Exception: updated = current | updates
    with get_connection() as connection:
        items = _cartman_am_load_items(connection)
        item = next((candidate for candidate in items if str(candidate["id"]) == str(alert_id)), None)
    return {"ok": True, "item": item, "message": "Alert completed."}

# END CARTMAN_ALERTS_MANAGEMENT_API_V1

# CARTMAN_AUTOMATED_TRIGGERS_API_V1
# Persistent trigger-rule configuration. This API stores rules; it does not fire them until the Monitoring evaluator is connected.
import json as _cartman_at_json
import re as _cartman_at_re
from datetime import datetime as _cartman_at_datetime, timezone as _cartman_at_timezone
from fastapi import Request as _CartmanATRequest, HTTPException as _CartmanATHTTPException


def _cartman_at_tables(conn):
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}


def _cartman_at_cols(conn, table):
    if table not in _cartman_at_tables(conn):
        return set()
    safe = '"' + str(table).replace('"', '""') + '"'
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(" + safe + ")").fetchall()}


def _cartman_at_dict(row):
    if row is None:
        return None
    try:
        return dict(row)
    except Exception:
        return {}


def _cartman_at_ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cartman_automated_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_code TEXT,
            name TEXT NOT NULL,
            target_type TEXT NOT NULL CHECK(target_type IN ('computer','department_computers')),
            target_id TEXT NOT NULL,
            target_label TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            threshold_percent INTEGER NOT NULL CHECK(threshold_percent BETWEEN 1 AND 100),
            notify_group_id TEXT NOT NULL DEFAULT '',
            notify_group_label TEXT NOT NULL DEFAULT '',
            send_email INTEGER NOT NULL DEFAULT 0,
            email TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cols = _cartman_at_cols(conn, "cartman_automated_triggers")
    if "trigger_code" not in cols:
        conn.execute("ALTER TABLE cartman_automated_triggers ADD COLUMN trigger_code TEXT")
    missing_codes = conn.execute("SELECT id FROM cartman_automated_triggers WHERE trigger_code IS NULL OR TRIM(trigger_code)=''").fetchall()
    for item in missing_codes:
        trigger_id = int(item[0])
        conn.execute("UPDATE cartman_automated_triggers SET trigger_code=? WHERE id=?", (f"ALT{trigger_id}", trigger_id))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cartman_automated_triggers_code ON cartman_automated_triggers(trigger_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cartman_automated_triggers_updated ON cartman_automated_triggers(updated_at)")


def _cartman_at_stamp():
    return _cartman_at_datetime.now(_cartman_at_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cartman_at_authorize(request, mutate=False):
    resolver = globals().get("_cartman_am_authorize")
    if not callable(resolver):
        raise _CartmanATHTTPException(status_code=503, detail="Alerts authorization integration is unavailable.")
    # A sync/async bridge is handled at the route because this helper may be awaitable.
    return resolver(request, complete=mutate)


async def _cartman_at_auth(request, mutate=False):
    import inspect as _cartman_at_inspect
    result = _cartman_at_authorize(request, mutate)
    if _cartman_at_inspect.isawaitable(result):
        result = await result
    return result


def _cartman_at_options(conn):
    tables = _cartman_at_tables(conn)
    devices, departments, groups = [], [], []
    if "devices" in tables:
        cols = _cartman_at_cols(conn, "devices")
        if {"id", "name"}.issubset(cols):
            for raw in conn.execute("SELECT * FROM devices ORDER BY name COLLATE NOCASE").fetchall():
                row = _cartman_at_dict(raw) or {}
                devices.append({"id": str(row.get("id", "")), "name": str(row.get("display_name") or row.get("name") or row.get("hostname") or row.get("id") or ""), "department_id": str(row.get("department_id") or ""), "status": str(row.get("status") or "")})
    if "departments" in tables:
        cols = _cartman_at_cols(conn, "departments")
        if "id" in cols and ("name" in cols or "display_name" in cols):
            name_col = "name" if "name" in cols else "display_name"
            for raw in conn.execute('SELECT id, "' + name_col + '" AS name FROM departments ORDER BY "' + name_col + '" COLLATE NOCASE').fetchall():
                row = _cartman_at_dict(raw) or {}
                departments.append({"id": str(row.get("id", "")), "name": str(row.get("name") or "")})
    if "iam_groups" in tables:
        cols = _cartman_at_cols(conn, "iam_groups")
        if "id" in cols:
            name_col = next((col for col in ("name", "display_name", "group_name", "title") if col in cols), None)
            if name_col:
                for raw in conn.execute("SELECT * FROM iam_groups ORDER BY " + ('"' + name_col + '"') + " COLLATE NOCASE").fetchall():
                    row = _cartman_at_dict(raw) or {}
                    status = str(row.get("status") or "Active").strip().casefold()
                    if status in {"inactive", "disabled", "deleted", "archived"}:
                        continue
                    groups.append({"id": str(row.get("id", "")), "name": str(row.get(name_col) or ""), "status": str(row.get("status") or "Active")})
    return {"devices": devices, "departments": departments, "groups": groups, "metrics": ["CPU", "RAM", "DISK", "NETWORK"]}


def _cartman_at_rule(raw):
    row = _cartman_at_dict(raw) or {}
    try:
        metrics = _cartman_at_json.loads(row.get("metrics_json") or "[]")
        if not isinstance(metrics, list): metrics = []
    except Exception:
        metrics = []
    return {
        "id": row.get("id"), "trigger_code": str(row.get("trigger_code") or ("ALT" + str(row.get("id") or ""))), "name": str(row.get("name") or "Automated trigger"),
        "target_type": str(row.get("target_type") or "computer"), "target_id": str(row.get("target_id") or ""),
        "target_label": str(row.get("target_label") or ""), "metrics": [str(m).upper() for m in metrics],
        "threshold_percent": int(row.get("threshold_percent") or 80),
        "notify_group_id": str(row.get("notify_group_id") or ""), "notify_group_label": str(row.get("notify_group_label") or ""),
        "send_email": bool(row.get("send_email")), "email": str(row.get("email") or ""),
        "enabled": bool(row.get("enabled", 1)), "created_by": str(row.get("created_by") or ""),
        "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        "execution_status": "configured_pending_monitoring_evaluator"
    }


@app.get("/api/automated-triggers/meta")
async def cartman_automated_triggers_meta(request: _CartmanATRequest):
    _, can_manage = await _cartman_at_auth(request, mutate=False)
    with get_connection() as conn:
        _cartman_at_ensure_schema(conn)
        options = _cartman_at_options(conn)
    return {"ok": True, "can_manage": bool(can_manage), **options}


@app.get("/api/automated-triggers")
async def cartman_automated_triggers_list(request: _CartmanATRequest):
    await _cartman_at_auth(request, mutate=False)
    with get_connection() as conn:
        _cartman_at_ensure_schema(conn)
        rows = conn.execute("SELECT * FROM cartman_automated_triggers ORDER BY updated_at DESC, id DESC").fetchall()
    items = [_cartman_at_rule(row) for row in rows]
    return {"ok": True, "items": items, "total": len(items), "enabled": sum(1 for item in items if item["enabled"]), "execution": "configuration_only_until_monitoring_evaluator_is_connected"}


@app.post("/api/automated-triggers", status_code=201)
async def cartman_automated_triggers_create(payload: dict, request: _CartmanATRequest):
    user, _ = await _cartman_at_auth(request, mutate=True)
    payload = payload or {}
    target_type = str(payload.get("target_type") or "").strip().casefold()
    if target_type not in {"computer", "department_computers"}:
        raise _CartmanATHTTPException(status_code=422, detail="Target must be Computer or Department Computers.")
    target_id = str(payload.get("target_id") or "").strip()[:120]
    if not target_id:
        raise _CartmanATHTTPException(status_code=422, detail="Select a target computer or department.")
    incoming_metrics = payload.get("metrics")
    allowed = {"CPU", "RAM", "DISK", "NETWORK"}
    if not isinstance(incoming_metrics, list): incoming_metrics = []
    metrics = list(dict.fromkeys(str(item).strip().upper() for item in incoming_metrics if str(item).strip().upper() in allowed))
    if not metrics:
        raise _CartmanATHTTPException(status_code=422, detail="Select at least one metric.")
    try:
        threshold = int(payload.get("threshold_percent"))
    except (TypeError, ValueError):
        raise _CartmanATHTTPException(status_code=422, detail="Threshold must be a percentage from 1 to 100.")
    if threshold < 1 or threshold > 100:
        raise _CartmanATHTTPException(status_code=422, detail="Threshold must be a percentage from 1 to 100.")
    group_id = str(payload.get("notify_group_id") or "").strip()[:120]
    send_email = bool(payload.get("send_email"))
    email = str(payload.get("email") or "").strip()[:254]
    if not group_id and not send_email:
        raise _CartmanATHTTPException(status_code=422, detail="Choose at least one alert method.")
    if group_id and send_email is False and email:
        email = ""
    if send_email and (not email or not _cartman_at_re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
        raise _CartmanATHTTPException(status_code=422, detail="Enter a valid email address for the email notification.")
    actor = str(user.get("username") or user.get("email") or user.get("id") or "unknown")[:160]
    with get_connection() as conn:
        _cartman_at_ensure_schema(conn)
        options = _cartman_at_options(conn)
        if target_type == "computer":
            target = next((item for item in options["devices"] if item["id"] == target_id), None)
            if target is None:
                raise _CartmanATHTTPException(status_code=422, detail="The selected computer no longer exists in Devices.")
            target_label = target["name"]
        else:
            target = next((item for item in options["departments"] if item["id"] == target_id), None)
            if target is None:
                raise _CartmanATHTTPException(status_code=422, detail="The selected department does not exist in Cartman.")
            target_label = target["name"]
        group_label = ""
        if group_id:
            group = next((item for item in options["groups"] if item["id"] == group_id), None)
            if group is None:
                raise _CartmanATHTTPException(status_code=422, detail="The selected IT group/support level no longer exists.")
            group_label = group["name"]
        auto_name = str(payload.get("name") or "").strip()[:120]
        if not auto_name:
            auto_name = f"{target_label} · {', '.join(metrics)} ≥ {threshold}%"
        now = _cartman_at_stamp()
        cur = conn.execute("""INSERT INTO cartman_automated_triggers
            (name,target_type,target_id,target_label,metrics_json,threshold_percent,notify_group_id,notify_group_label,send_email,email,enabled,created_by,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
            (auto_name,target_type,target_id,target_label,_cartman_at_json.dumps(metrics),threshold,group_id,group_label,1 if send_email else 0,email,actor,now,now))
        new_id = cur.lastrowid
        conn.execute("UPDATE cartman_automated_triggers SET trigger_code=? WHERE id=?", (f"ALT{new_id}", new_id))
        row = conn.execute("SELECT * FROM cartman_automated_triggers WHERE id=?", (new_id,)).fetchone()
    return {"ok": True, "item": _cartman_at_rule(row), "message": "Trigger rule saved. Monitoring metric evaluation must be connected before it can fire automatically."}


@app.patch("/api/automated-triggers/{trigger_id}")
async def cartman_automated_triggers_update(trigger_id: int, payload: dict, request: _CartmanATRequest):
    user, _ = await _cartman_at_auth(request, mutate=True)
    payload = payload or {}
    now = _cartman_at_stamp()
    with get_connection() as conn:
        _cartman_at_ensure_schema(conn)
        current = conn.execute("SELECT * FROM cartman_automated_triggers WHERE id=?", (trigger_id,)).fetchone()
        if current is None:
            raise _CartmanATHTTPException(status_code=404, detail="Automated trigger not found.")
        current_dict = _cartman_at_dict(current) or {}
        # The list's Enabled checkbox sends only this field; keep that narrow update path.
        if set(payload.keys()) == {"enabled"}:
            if not isinstance(payload.get("enabled"), bool):
                raise _CartmanATHTTPException(status_code=422, detail="Provide enabled as true or false.")
            conn.execute("UPDATE cartman_automated_triggers SET enabled=?,updated_at=? WHERE id=?", (1 if payload["enabled"] else 0, now, trigger_id))
            updated = conn.execute("SELECT * FROM cartman_automated_triggers WHERE id=?", (trigger_id,)).fetchone()
            return {"ok": True, "item": _cartman_at_rule(updated)}

        target_type = str(payload.get("target_type") or "").strip().casefold()
        if target_type not in {"computer", "department_computers"}:
            raise _CartmanATHTTPException(status_code=422, detail="Target must be Computer or Department Computers.")
        target_id = str(payload.get("target_id") or "").strip()[:120]
        if not target_id:
            raise _CartmanATHTTPException(status_code=422, detail="Select a target computer or department.")
        incoming_metrics = payload.get("metrics")
        allowed = {"CPU", "RAM", "DISK", "NETWORK"}
        if not isinstance(incoming_metrics, list): incoming_metrics = []
        metrics = list(dict.fromkeys(str(item).strip().upper() for item in incoming_metrics if str(item).strip().upper() in allowed))
        if not metrics:
            raise _CartmanATHTTPException(status_code=422, detail="Select at least one metric.")
        try:
            threshold = int(payload.get("threshold_percent"))
        except (TypeError, ValueError):
            raise _CartmanATHTTPException(status_code=422, detail="Threshold must be a percentage from 1 to 100.")
        if threshold < 1 or threshold > 100:
            raise _CartmanATHTTPException(status_code=422, detail="Threshold must be a percentage from 1 to 100.")
        group_id = str(payload.get("notify_group_id") or "").strip()[:120]
        send_email = bool(payload.get("send_email"))
        email = str(payload.get("email") or "").strip()[:254]
        if not group_id and not send_email:
            raise _CartmanATHTTPException(status_code=422, detail="Choose at least one alert method.")
        if send_email and (not email or not _cartman_at_re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
            raise _CartmanATHTTPException(status_code=422, detail="Enter a valid email address for the email notification.")
        actor = str(user.get("username") or user.get("email") or user.get("id") or "unknown")[:160]
        options = _cartman_at_options(conn)
        if target_type == "computer":
            target = next((item for item in options["devices"] if item["id"] == target_id), None)
            if target is None:
                raise _CartmanATHTTPException(status_code=422, detail="The selected computer no longer exists in Devices.")
        else:
            target = next((item for item in options["departments"] if item["id"] == target_id), None)
            if target is None:
                raise _CartmanATHTTPException(status_code=422, detail="The selected department does not exist in Cartman.")
        group_label = ""
        if group_id:
            group = next((item for item in options["groups"] if item["id"] == group_id), None)
            if group is None:
                raise _CartmanATHTTPException(status_code=422, detail="The selected IT group/support level no longer exists.")
            group_label = group["name"]
        name = str(payload.get("name") or "").strip()[:120]
        if not name:
            name = f"{target['name']} · {', '.join(metrics)} ≥ {threshold}%"
        enabled = payload.get("enabled", bool(current_dict.get("enabled", 1)))
        if not isinstance(enabled, bool):
            raise _CartmanATHTTPException(status_code=422, detail="Enabled must be true or false.")
        conn.execute("""UPDATE cartman_automated_triggers
            SET name=?, target_type=?, target_id=?, target_label=?, metrics_json=?, threshold_percent=?,
                notify_group_id=?, notify_group_label=?, send_email=?, email=?, enabled=?, updated_at=?
            WHERE id=?""",
            (name, target_type, target_id, target["name"], _cartman_at_json.dumps(metrics), threshold,
             group_id, group_label, 1 if send_email else 0, email if send_email else "", 1 if enabled else 0, now, trigger_id))
        updated = conn.execute("SELECT * FROM cartman_automated_triggers WHERE id=?", (trigger_id,)).fetchone()
    return {"ok": True, "item": _cartman_at_rule(updated), "updated_by": actor}


@app.delete("/api/automated-triggers/{trigger_id}")
async def cartman_automated_triggers_delete(trigger_id: int, request: _CartmanATRequest):
    await _cartman_at_auth(request, mutate=True)
    with get_connection() as conn:
        _cartman_at_ensure_schema(conn)
        cur = conn.execute("DELETE FROM cartman_automated_triggers WHERE id=?", (trigger_id,))
        if cur.rowcount <= 0:
            raise _CartmanATHTTPException(status_code=404, detail="Automated trigger not found.")
    return {"ok": True, "deleted_id": trigger_id}

# END CARTMAN_AUTOMATED_TRIGGERS_API_V1

# CARTMAN_PROCESS_USAGE_API_V1
# Process-level samples are reported by a local CartmanClient/collector. No synthetic measurements are produced.
import json as _cartman_process_json
from datetime import datetime as _cartman_process_datetime, timezone as _cartman_process_timezone, timedelta as _cartman_process_timedelta
from fastapi import Request as _CartmanProcessRequest, HTTPException as _CartmanProcessHTTPException


def _cartman_process_tables(conn):
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _cartman_process_cols(conn, table):
    if table not in _cartman_process_tables(conn):
        return set()
    safe = '"' + str(table).replace('"', '""') + '"'
    return {str(row[1]) for row in conn.execute('PRAGMA table_info(' + safe + ')').fetchall()}


def _cartman_process_rowdict(row):
    try:
        return dict(row)
    except Exception:
        return {}


def _cartman_process_ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cartman_process_metric_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            process_name TEXT NOT NULL,
            pid INTEGER,
            cpu_percent REAL,
            memory_percent REAL,
            memory_bytes INTEGER,
            disk_read_bytes_per_sec REAL,
            disk_write_bytes_per_sec REAL,
            network_rx_bytes_per_sec REAL,
            network_tx_bytes_per_sec REAL,
            collected_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'CartmanClient'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cartman_process_samples_device_time ON cartman_process_metric_samples(device_id, collected_at DESC)")


def _cartman_process_stamp():
    return _cartman_process_datetime.now(_cartman_process_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cartman_process_num(value, name, low=0, high=None):
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise _CartmanProcessHTTPException(status_code=422, detail=f"{name} must be numeric or null.")
    if n < low or (high is not None and n > high):
        raise _CartmanProcessHTTPException(status_code=422, detail=f"{name} is outside its supported range.")
    return n


def _cartman_process_device_exists(conn, device_id):
    tables = _cartman_process_tables(conn)
    if "devices" not in tables:
        return False
    cols = _cartman_process_cols(conn, "devices")
    if "id" not in cols:
        return False
    return conn.execute("SELECT 1 FROM devices WHERE CAST(id AS TEXT)=? LIMIT 1", (str(device_id),)).fetchone() is not None


@app.get("/api/monitoring/processes")
async def cartman_process_usage_get(request: _CartmanProcessRequest, device_id: str, limit: int = 25, minutes: int = 60):
    # The app's existing session/auth middleware protects /api routes.
    if not device_id or len(device_id) > 160:
        raise _CartmanProcessHTTPException(status_code=422, detail="A valid device_id is required.")
    limit = max(1, min(int(limit or 25), 100))
    minutes = max(1, min(int(minutes or 60), 10080))
    with get_connection() as conn:
        _cartman_process_ensure_schema(conn)
        if not _cartman_process_device_exists(conn, device_id):
            raise _CartmanProcessHTTPException(status_code=404, detail="Device not found.")
        latest = conn.execute("SELECT MAX(collected_at) FROM cartman_process_metric_samples WHERE device_id=? AND collected_at >= ?", (str(device_id), (_cartman_process_datetime.now(_cartman_process_timezone.utc)-_cartman_process_timedelta(minutes=minutes)).isoformat(timespec="seconds").replace("+00:00", "Z"))).fetchone()
        latest_at = latest[0] if latest else None
        rows = []
        if latest_at:
            rows = conn.execute("""
                SELECT process_name, pid, cpu_percent, memory_percent, memory_bytes,
                       disk_read_bytes_per_sec, disk_write_bytes_per_sec,
                       network_rx_bytes_per_sec, network_tx_bytes_per_sec, collected_at, source
                FROM cartman_process_metric_samples
                WHERE device_id=? AND collected_at=?
                ORDER BY COALESCE(cpu_percent,0) DESC, COALESCE(memory_bytes,0) DESC
                LIMIT ?
            """, (str(device_id), latest_at, limit)).fetchall()
    items = [_cartman_process_rowdict(row) for row in rows]
    return {"ok": True, "device_id": str(device_id), "collected_at": latest_at, "window_minutes": minutes,
            "items": items, "total": len(items), "available": bool(items),
            "message": "" if items else "No process-level telemetry has been reported for this device in the selected window."}


@app.post("/api/monitoring/processes/report", status_code=201)
async def cartman_process_usage_report(payload: dict, request: _CartmanProcessRequest):
    # Report endpoint relies on Cartman's existing /api authentication middleware.
    payload = payload or {}
    device_id = str(payload.get("device_id") or "").strip()[:160]
    processes = payload.get("processes")
    if not device_id:
        raise _CartmanProcessHTTPException(status_code=422, detail="device_id is required.")
    if not isinstance(processes, list) or len(processes) > 250:
        raise _CartmanProcessHTTPException(status_code=422, detail="processes must be a list containing at most 250 entries.")
    collected_at = str(payload.get("collected_at") or _cartman_process_stamp()).strip()[:64]
    # Validate timestamp format so time-window filters remain deterministic.
    try:
        parsed_collected_at = _cartman_process_datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
        if parsed_collected_at.tzinfo is None:
            parsed_collected_at = parsed_collected_at.replace(tzinfo=_cartman_process_timezone.utc)
        collected_at = parsed_collected_at.astimezone(_cartman_process_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
        raise _CartmanProcessHTTPException(status_code=422, detail="collected_at must be an ISO timestamp.")
    clean = []
    for process in processes:
        if not isinstance(process, dict):
            continue
        name = str(process.get("process_name") or process.get("name") or "").strip()[:256]
        if not name:
            continue
        try:
            pid = int(process.get("pid")) if process.get("pid") not in (None, "") else None
        except (TypeError, ValueError):
            raise _CartmanProcessHTTPException(status_code=422, detail="pid must be an integer or null.")
        if pid is not None and pid < 0:
            raise _CartmanProcessHTTPException(status_code=422, detail="pid cannot be negative.")
        cpu = _cartman_process_num(process.get("cpu_percent"), "cpu_percent", 0, 1000)
        mem_pct = _cartman_process_num(process.get("memory_percent"), "memory_percent", 0, 100)
        mem_bytes = process.get("memory_bytes")
        if mem_bytes not in (None, ""):
            try: mem_bytes = int(mem_bytes)
            except (TypeError, ValueError): raise _CartmanProcessHTTPException(status_code=422, detail="memory_bytes must be an integer or null.")
            if mem_bytes < 0: raise _CartmanProcessHTTPException(status_code=422, detail="memory_bytes cannot be negative.")
        else:
            mem_bytes = None
        values = [_cartman_process_num(process.get(key), key, 0, 1e15) for key in (
            "disk_read_bytes_per_sec", "disk_write_bytes_per_sec", "network_rx_bytes_per_sec", "network_tx_bytes_per_sec")]
        clean.append((device_id, name, pid, cpu, mem_pct, mem_bytes, *values, collected_at, str(payload.get("source") or "CartmanClient")[:80]))
    with get_connection() as conn:
        _cartman_process_ensure_schema(conn)
        if not _cartman_process_device_exists(conn, device_id):
            raise _CartmanProcessHTTPException(status_code=404, detail="Device not found.")
        conn.executemany("""
            INSERT INTO cartman_process_metric_samples
            (device_id,process_name,pid,cpu_percent,memory_percent,memory_bytes,
             disk_read_bytes_per_sec,disk_write_bytes_per_sec,network_rx_bytes_per_sec,network_tx_bytes_per_sec,collected_at,source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, clean)
        cutoff = (_cartman_process_datetime.now(_cartman_process_timezone.utc)-_cartman_process_timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
        conn.execute("DELETE FROM cartman_process_metric_samples WHERE collected_at < ?", (cutoff,))
    return {"ok": True, "device_id": device_id, "collected_at": collected_at, "accepted": len(clean)}
# END CARTMAN_PROCESS_USAGE_API_V1



# CARTMAN_SETTINGS_AND_BACKUP_LIVE_V1
# Server-persisted system settings and safe SQLite backup bundles.
import hashlib as _cartman_backup_hashlib
import json as _cartman_backup_json
import os as _cartman_backup_os
import re as _cartman_backup_re
import shutil as _cartman_backup_shutil
import sqlite3 as _cartman_backup_sqlite3
import threading as _cartman_backup_threading
import uuid as _cartman_backup_uuid
import zipfile as _cartman_backup_zipfile
from datetime import datetime as _cartman_backup_datetime, timezone as _cartman_backup_timezone
from pathlib import Path as _cartman_backup_Path

_CARTMAN_SETTINGS_DEFAULTS = {
    "workspace_name": "Cartman",
    "timezone": "Europe/Istanbul",
    "default_refresh_seconds": 30,
    "maintenance_mode": False,
    "admin_notifications": True,
    "usage_analytics": False,
    "audit_retention_days": 365,
}
_CARTMAN_SETTINGS_TIMEZONES = {
    "UTC", "Europe/Istanbul", "Europe/London", "Europe/Berlin",
    "Europe/Paris", "America/New_York", "America/Los_Angeles", "Asia/Dubai",
}
_CARTMAN_BACKUP_DIR = BASE_DIR / ".cartman-backups"
_CARTMAN_BACKUP_PENDING = _CARTMAN_BACKUP_DIR / "restore-pending.json"
_CARTMAN_BACKUP_LOCK = _cartman_backup_threading.Lock()
_CARTMAN_BACKUP_ID_RE = _cartman_backup_re.compile(r"^[0-9a-f]{32}$")


def _cartman_backup_now():
    return _cartman_backup_datetime.now(_cartman_backup_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cartman_settings_ensure_schema(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS cartman_system_settings ("
        "setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, "
        "updated_by TEXT NOT NULL DEFAULT 'system', updated_at TEXT NOT NULL)"
    )
    now = _cartman_backup_now()
    for key, value in _CARTMAN_SETTINGS_DEFAULTS.items():
        connection.execute(
            "INSERT OR IGNORE INTO cartman_system_settings "
            "(setting_key,value_json,updated_by,updated_at) VALUES (?,?,?,?)",
            (key, _cartman_backup_json.dumps(value, ensure_ascii=False), "system", now),
        )


def _cartman_settings_read(connection):
    _cartman_settings_ensure_schema(connection)
    rows = connection.execute(
        "SELECT setting_key,value_json,updated_by,updated_at FROM cartman_system_settings"
    ).fetchall()
    values = dict(_CARTMAN_SETTINGS_DEFAULTS)
    updated_at = None
    updated_by = None
    for row in rows:
        try:
            values[row["setting_key"]] = _cartman_backup_json.loads(row["value_json"])
        except Exception:
            continue
        if updated_at is None or str(row["updated_at"]) > str(updated_at):
            updated_at = row["updated_at"]
            updated_by = row["updated_by"]
    return values, updated_at, updated_by


def _cartman_settings_validate(payload, current):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Settings must be sent as a JSON object.")
    unknown = set(payload) - set(_CARTMAN_SETTINGS_DEFAULTS)
    if unknown:
        raise HTTPException(status_code=422, detail="Unsupported settings: " + ", ".join(sorted(unknown)))
    result = dict(current)
    for key, value in payload.items():
        if key == "workspace_name":
            value = _cartman_int_clean(value, "Workspace name", 80, True)
        elif key == "timezone":
            value = _cartman_int_clean(value, "Timezone", 80, True)
            if not re.fullmatch(r"(?:UTC|[A-Za-z_][A-Za-z0-9_+.-]*(?:/[A-Za-z0-9_+.-]+)+)", str(value)):
                raise HTTPException(status_code=422, detail="Unsupported timezone.")
        elif key == "default_refresh_seconds":
            if type(value) is not int or value not in {15, 30, 60, 120}:
                raise HTTPException(status_code=422, detail="Refresh interval must be 15, 30, 60 or 120 seconds.")
        elif key in {"maintenance_mode", "admin_notifications", "usage_analytics"}:
            if type(value) is not bool:
                raise HTTPException(status_code=422, detail=key + " must be a boolean.")
        elif key == "audit_retention_days":
            if type(value) is not int or value not in {30, 90, 180, 365, 730}:
                raise HTTPException(status_code=422, detail="Audit retention must be 30, 90, 180, 365 or 730 days.")
        result[key] = value
    return result


@app.get("/api/admin/system-settings")
def cartman_admin_system_settings_get(request: Request):
    user = _cartman_int_user(request, write=False, sensitive=True)
    with get_connection() as connection:
        values, updated_at, updated_by = _cartman_settings_read(connection)
        return {"settings": values, "updated_at": updated_at, "updated_by": updated_by}


@app.put("/api/admin/system-settings")
async def cartman_admin_system_settings_put(request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="A JSON request body is required.")
    incoming = payload.get("settings") if isinstance(payload, dict) else None
    now = _cartman_backup_now()
    with get_connection() as connection:
        current, _, _ = _cartman_settings_read(connection)
        values = _cartman_settings_validate(incoming, current)
        actor = _cartman_int_actor(user)
        for key in incoming:
            connection.execute(
                "INSERT INTO cartman_system_settings (setting_key,value_json,updated_by,updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(setting_key) DO UPDATE SET "
                "value_json=excluded.value_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                (key, _cartman_backup_json.dumps(values[key], ensure_ascii=False), actor, now),
            )
        _cartman_int_audit(connection, user, "system_settings.updated", "system_settings", "global",
                           {"changed_keys": sorted(incoming)})
    return {"settings": values, "updated_at": now, "updated_by": actor}


def _cartman_backup_ensure_dir():
    if _CARTMAN_BACKUP_DIR.exists() and _CARTMAN_BACKUP_DIR.is_symlink():
        raise HTTPException(status_code=500, detail="Backup repository must not be a symbolic link.")
    _CARTMAN_BACKUP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        _cartman_backup_os.chmod(str(_CARTMAN_BACKUP_DIR), 0o700)
    except OSError:
        pass
    return _CARTMAN_BACKUP_DIR


def _cartman_backup_hash_file(path):
    digest = _cartman_backup_hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cartman_backup_check_database(path, connector_key_present=False):
    connection = None
    try:
        connection = _cartman_backup_sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise ValueError("SQLite integrity_check did not return ok.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "devices" not in tables:
            raise ValueError("The database does not contain the Cartman devices table.")
        if "cartman_connectors" in tables:
            row = connection.execute(
                "SELECT COUNT(*) FROM cartman_connectors WHERE COALESCE(credential_ciphertext,'')<>''"
            ).fetchone()
            if row and int(row[0]) > 0 and not connector_key_present:
                raise ValueError("Connector credentials exist but the encryption key is missing from this backup.")
        return {"integrity": "ok", "tables": len(tables)}
    finally:
        if connection is not None:
            connection.close()


def _cartman_backup_create_bundle(bundle_type="manual"):
    directory = _cartman_backup_ensure_dir()
    backup_id = _cartman_backup_uuid.uuid4().hex
    database_temp = directory / (".database-" + backup_id + ".tmp")
    archive_temp = directory / (".archive-" + backup_id + ".tmp")
    archive_path = directory / ("cartman-backup-" + backup_id + ".zip")
    source = None
    target = None
    try:
        if not DATABASE.is_file() or DATABASE.is_symlink():
            raise HTTPException(status_code=503, detail="Cartman database is missing or is not a regular file.")
        source = get_connection()
        target = _cartman_backup_sqlite3.connect(str(database_temp))
        source.backup(target, pages=256, sleep=0.05)
        target.commit()
        target.close()
        target = None
        source.close()
        source = None
        try:
            _cartman_backup_os.chmod(str(database_temp), 0o600)
        except OSError:
            pass
        key_path = BASE_DIR / ".cartman_connector_fernet.key"
        key_data = None
        if key_path.exists():
            if key_path.is_symlink() or not key_path.is_file() or key_path.stat().st_size > 4096:
                raise HTTPException(status_code=500, detail="Connector encryption key file is not safe to back up.")
            key_data = key_path.read_bytes()
            try:
                from cryptography.fernet import Fernet
                Fernet(key_data)
            except Exception:
                raise HTTPException(status_code=500, detail="Connector encryption key is invalid; backup was stopped.")
        db_check = _cartman_backup_check_database(database_temp, connector_key_present=bool(key_data))
        created_at = _cartman_backup_now()
        manifest = {
            "format_version": 1, "backup_id": backup_id, "bundle_type": bundle_type,
            "created_at": created_at, "database_member": "cartman.db",
            "database_sha256": _cartman_backup_hash_file(database_temp),
            "database_bytes": database_temp.stat().st_size,
            "connector_key_included": bool(key_data),
            "connector_key_sha256": _cartman_backup_hashlib.sha256(key_data).hexdigest() if key_data else None,
            "integrity_check": db_check["integrity"], "table_count": db_check["tables"],
            "scope": ["Cartman SQLite database", "Connector encryption key when present"],
            "excluded": ["Software package repository", "External attachment/file storage", "Application source code"],
        }
        with _cartman_backup_zipfile.ZipFile(archive_temp, "w", compression=_cartman_backup_zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(database_temp, arcname="cartman.db")
            if key_data is not None:
                info = _cartman_backup_zipfile.ZipInfo("connector_fernet.key")
                info.compress_type = _cartman_backup_zipfile.ZIP_DEFLATED
                info.external_attr = (0o600 & 0xFFFF) << 16
                archive.writestr(info, key_data)
            info = _cartman_backup_zipfile.ZipInfo("manifest.json")
            info.compress_type = _cartman_backup_zipfile.ZIP_DEFLATED
            info.external_attr = (0o600 & 0xFFFF) << 16
            archive.writestr(info, _cartman_backup_json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        try:
            _cartman_backup_os.chmod(str(archive_temp), 0o600)
        except OSError:
            pass
        _cartman_backup_os.replace(str(archive_temp), str(archive_path))
        return {
            "id": backup_id, "filename": archive_path.name, "created_at": created_at,
            "bytes": archive_path.stat().st_size, "sha256": _cartman_backup_hash_file(archive_path),
            "bundle_type": bundle_type, "connector_key_included": bool(key_data),
            "integrity": "Passed", "database_bytes": manifest["database_bytes"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Backup creation failed: " + str(exc))
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()
        for temporary in (database_temp, archive_temp):
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _cartman_backup_path(backup_id):
    if not isinstance(backup_id, str) or not _CARTMAN_BACKUP_ID_RE.fullmatch(backup_id):
        raise HTTPException(status_code=400, detail="Invalid backup ID.")
    directory = _cartman_backup_ensure_dir()
    path = directory / ("cartman-backup-" + backup_id + ".zip")
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found.")
    return path


def _cartman_backup_verify_archive(path, expected_id=None):
    directory = _cartman_backup_ensure_dir()
    temporary = directory / (".verify-" + _cartman_backup_uuid.uuid4().hex + ".sqlite3")
    try:
        with _cartman_backup_zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            allowed = {"manifest.json", "cartman.db", "connector_fernet.key"}
            if len(names) != len(set(names)) or set(names) - allowed or not {"manifest.json", "cartman.db"}.issubset(set(names)):
                raise ValueError("Backup archive contains unexpected or duplicate files.")
            by_name = {item.filename: item for item in infos}
            if by_name["manifest.json"].file_size > 1024 * 1024 or by_name["cartman.db"].file_size > 20 * 1024 * 1024 * 1024:
                raise ValueError("Backup archive member exceeds the permitted size.")
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError("ZIP checksum failed for " + bad_member)
            manifest = _cartman_backup_json.loads(archive.read("manifest.json").decode("utf-8"))
            backup_id = str(manifest.get("backup_id") or "")
            if not _CARTMAN_BACKUP_ID_RE.fullmatch(backup_id) or (expected_id and backup_id != expected_id):
                raise ValueError("Backup identity does not match its filename.")
            if manifest.get("format_version") != 1 or manifest.get("database_member") != "cartman.db":
                raise ValueError("Unsupported Cartman backup format.")
            digest = _cartman_backup_hashlib.sha256()
            with archive.open("cartman.db", "r") as source, open(temporary, "wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != manifest.get("database_sha256"):
                raise ValueError("Database SHA-256 does not match the backup manifest.")
            key_present = "connector_fernet.key" in by_name
            if bool(manifest.get("connector_key_included")) != key_present:
                raise ValueError("Connector encryption-key metadata does not match the archive.")
            if key_present:
                key_data = archive.read("connector_fernet.key")
                if len(key_data) > 4096 or _cartman_backup_hashlib.sha256(key_data).hexdigest() != manifest.get("connector_key_sha256"):
                    raise ValueError("Connector encryption key checksum is invalid.")
                try:
                    from cryptography.fernet import Fernet
                    Fernet(key_data)
                except Exception:
                    raise ValueError("Connector encryption key is not a valid Fernet key.")
            db_check = _cartman_backup_check_database(temporary, connector_key_present=key_present)
            return {
                "backup_id": backup_id, "created_at": manifest.get("created_at"),
                "database_bytes": int(manifest.get("database_bytes") or temporary.stat().st_size),
                "connector_key_included": key_present, "integrity": db_check["integrity"],
                "table_count": db_check["tables"], "sha256": _cartman_backup_hash_file(path),
                "manifest": manifest,
            }
    except (ValueError, KeyError, OSError, _cartman_backup_zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=422, detail="Backup verification failed: " + str(exc))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _cartman_backup_list_items():
    directory = _cartman_backup_ensure_dir()
    items = []
    for path in directory.glob("cartman-backup-*.zip"):
        match = _cartman_backup_re.fullmatch(r"cartman-backup-([0-9a-f]{32})\.zip", path.name)
        if not match or path.is_symlink() or not path.is_file():
            continue
        try:
            with _cartman_backup_zipfile.ZipFile(path, "r") as archive:
                manifest = _cartman_backup_json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("backup_id") != match.group(1):
                continue
            items.append({
                "id": match.group(1), "filename": path.name,
                "created_at": manifest.get("created_at") or _cartman_backup_datetime.fromtimestamp(path.stat().st_mtime, _cartman_backup_timezone.utc).isoformat(),
                "bytes": path.stat().st_size, "database_bytes": int(manifest.get("database_bytes") or 0),
                "bundle_type": manifest.get("bundle_type", "manual"),
                "connector_key_included": bool(manifest.get("connector_key_included")),
                "integrity": manifest.get("integrity_check", "Not verified"),
                "sha256": _cartman_backup_hash_file(path),
            })
        except Exception:
            continue
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


@app.get("/api/admin/backups")
def cartman_admin_backups_list(request: Request):
    _cartman_int_user(request, write=False, sensitive=True)
    items = _cartman_backup_list_items()
    return {"items": items, "total": len(items), "storage_bytes": sum(item["bytes"] for item in items),
            "repository": "app/.cartman-backups", "scope": "SQLite database and connector encryption key when present"}


@app.post("/api/admin/backups", status_code=201)
def cartman_admin_backups_create(request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    with _CARTMAN_BACKUP_LOCK:
        item = _cartman_backup_create_bundle("manual")
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        _cartman_int_audit(connection, user, "backup.created", "backup", item["id"],
                           {"filename": item["filename"], "bytes": item["bytes"], "connector_key_included": item["connector_key_included"]})
    return {"item": item}


@app.get("/api/admin/backups/{backup_id}/download")
def cartman_admin_backups_download(backup_id: str, request: Request):
    _cartman_int_user(request, write=False, sensitive=True)
    path = _cartman_backup_path(backup_id)
    return FileResponse(str(path), media_type="application/zip", filename=path.name)


@app.post("/api/admin/backups/{backup_id}/verify")
def cartman_admin_backups_verify(backup_id: str, request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    path = _cartman_backup_path(backup_id)
    result = _cartman_backup_verify_archive(path, backup_id)
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        _cartman_int_audit(connection, user, "backup.verified", "backup", backup_id,
                           {"integrity": result["integrity"], "connector_key_included": result["connector_key_included"]})
    return {"verified": True, "backup": {key: value for key, value in result.items() if key != "manifest"}}


@app.get("/api/admin/backups/restore-pending")
def cartman_admin_backups_pending_get(request: Request):
    _cartman_int_user(request, write=False, sensitive=True)
    _cartman_backup_ensure_dir()
    if not _CARTMAN_BACKUP_PENDING.is_file():
        return {"pending": False}
    try:
        data = _cartman_backup_json.loads(_CARTMAN_BACKUP_PENDING.read_text(encoding="utf-8"))
        return {"pending": True, "restore": {
            "backup_id": data.get("source_backup_id"), "created_at": data.get("created_at"),
            "safety_backup_id": data.get("safety_backup_id"),
            "command": ".venv/bin/python scripts/cartman_restore.py --apply-pending --confirm-stop",
        }}
    except Exception:
        raise HTTPException(status_code=500, detail="Pending restore metadata is unreadable; do not remove files manually.")


@app.post("/api/admin/backups/{backup_id}/restore-prepare")
def cartman_admin_backups_restore_prepare(backup_id: str, request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    with _CARTMAN_BACKUP_LOCK:
        _cartman_backup_ensure_dir()
        if _CARTMAN_BACKUP_PENDING.exists():
            raise HTTPException(status_code=409, detail="A restore is already pending. Cancel it before preparing another restore.")
        source_path = _cartman_backup_path(backup_id)
        verified = _cartman_backup_verify_archive(source_path, backup_id)
        safety = _cartman_backup_create_bundle("pre_restore_safety")
        staged_id = _cartman_backup_uuid.uuid4().hex
        staged_name = "cartman-restore-pending-" + staged_id + ".zip"
        staged_path = _CARTMAN_BACKUP_DIR / staged_name
        try:
            _cartman_backup_shutil.copyfile(str(source_path), str(staged_path))
            _cartman_backup_os.chmod(str(staged_path), 0o600)
            if _cartman_backup_hash_file(staged_path) != verified["sha256"]:
                raise ValueError("Staged restore package checksum mismatch.")
            live_snapshot = _CARTMAN_BACKUP_DIR / (".live-check-" + staged_id + ".sqlite3")
            source = get_connection()
            target = _cartman_backup_sqlite3.connect(str(live_snapshot))
            try:
                source.backup(target, pages=256, sleep=0.05)
                target.commit()
            finally:
                target.close()
                source.close()
            key_path = BASE_DIR / ".cartman_connector_fernet.key"
            pending = {
                "source_backup_id": backup_id, "staged_filename": staged_name,
                "safety_backup_id": safety["id"], "created_at": _cartman_backup_now(),
                "staged_sha256": verified["sha256"],
                "live_database_sha256": _cartman_backup_hash_file(live_snapshot),
                "live_connector_key_sha256": _cartman_backup_hash_file(key_path) if key_path.is_file() else None,
                "connector_key_included": verified["connector_key_included"],
            }
            live_snapshot.unlink()
            pending_temp = _CARTMAN_BACKUP_DIR / (".restore-pending-" + staged_id + ".tmp")
            pending_temp.write_text(_cartman_backup_json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
            _cartman_backup_os.chmod(str(pending_temp), 0o600)
            _cartman_backup_os.replace(str(pending_temp), str(_CARTMAN_BACKUP_PENDING))
        except Exception as exc:
            try:
                staged_path.unlink()
            except FileNotFoundError:
                pass
            try:
                live_snapshot.unlink()
            except (FileNotFoundError, UnboundLocalError):
                pass
            raise HTTPException(status_code=500, detail="Restore preparation failed: " + str(exc))
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        _cartman_int_audit(connection, user, "backup.restore_prepared", "backup", backup_id,
                           {"safety_backup_id": safety["id"], "staged_filename": staged_name})
    return {"pending": True, "backup_id": backup_id, "safety_backup_id": safety["id"],
            "created_at": pending["created_at"],
            "command": ".venv/bin/python scripts/cartman_restore.py --apply-pending --confirm-stop",
            "message": "Restore package verified and staged. Stop Cartman before running the command in Terminal."}


@app.delete("/api/admin/backups/restore-pending")
def cartman_admin_backups_pending_delete(request: Request):
    user = _cartman_int_user(request, write=True, sensitive=True)
    _cartman_backup_ensure_dir()
    if not _CARTMAN_BACKUP_PENDING.is_file():
        return {"cancelled": True, "already_clear": True}
    try:
        pending = _cartman_backup_json.loads(_CARTMAN_BACKUP_PENDING.read_text(encoding="utf-8"))
        staged_name = str(pending.get("staged_filename") or "")
        if not _cartman_backup_re.fullmatch(r"cartman-restore-pending-[0-9a-f]{32}\.zip", staged_name):
            raise ValueError("Unexpected staged filename.")
        staged = _CARTMAN_BACKUP_DIR / staged_name
        if staged.is_symlink():
            raise ValueError("Staged restore file is a symbolic link.")
        if staged.exists():
            staged.unlink()
        _CARTMAN_BACKUP_PENDING.unlink()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not cancel pending restore: " + str(exc))
    with get_connection() as connection:
        _cartman_int_ensure_schema(connection)
        _cartman_int_audit(connection, user, "backup.restore_cancelled", "backup", pending.get("source_backup_id", ""), {})
    return {"cancelled": True}

# END CARTMAN_SETTINGS_AND_BACKUP_LIVE_V1

# CARTMAN_ENCRYPTED_BACKUP_MANAGER_V2_REGISTER
# Register the selectable, password-encrypted backup API without changing Connectors.
import importlib.util as _cartman_bkp2_importlib_util
import sys as _cartman_bkp2_sys
_cartman_bkp2_module_name = "_cartman_backup_manager_v2_runtime"
_cartman_bkp2_module_path = BASE_DIR / "cartman_backup_manager.py"
_cartman_bkp2_spec = _cartman_bkp2_importlib_util.spec_from_file_location(
    _cartman_bkp2_module_name, str(_cartman_bkp2_module_path)
)
if _cartman_bkp2_spec is None or _cartman_bkp2_spec.loader is None:
    raise RuntimeError("Cartman encrypted backup manager could not be loaded.")
_cartman_bkp2_module = _cartman_bkp2_importlib_util.module_from_spec(_cartman_bkp2_spec)
_cartman_bkp2_sys.modules[_cartman_bkp2_module_name] = _cartman_bkp2_module
_cartman_bkp2_spec.loader.exec_module(_cartman_bkp2_module)
_cartman_bkp2_module.register(app, globals())
# END CARTMAN_ENCRYPTED_BACKUP_MANAGER_V2_REGISTER

# CARTMAN_ROOT_UI_API_V1: UI capability discovery only; grants are managed from the local console.
@app.get("/api/admin/root-access")
def cartman_admin_root_access(request: Request):
    user = _cartman_int_user(request, write=False, sensitive=True)
    username = _cartman_int_actor(user)
    is_root = False
    granted_at = None
    granted_by = None
    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT granted_at, granted_by FROM cartman_root_principals WHERE username=? COLLATE NOCASE AND enabled=1",
                (username,),
            ).fetchone()
            if row:
                is_root = True
                granted_at = row["granted_at"]
                granted_by = row["granted_by"]
    except sqlite3.Error:
        pass
    return {"is_root": is_root, "granted_at": granted_at, "granted_by": granted_by}


