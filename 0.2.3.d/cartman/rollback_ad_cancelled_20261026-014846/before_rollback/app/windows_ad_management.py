"""Local, authenticated, read-only Windows Active Directory connector API."""

import ipaddress
import json
import sqlite3
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter()

get_connection = None
get_live_device_connections = None

CONNECTOR_MARKER = "windows_ad_management_v1"

PULL_PAGE_OPERATIONS = {
    "pull_ous_page",
    "pull_users_page",
    "pull_groups_page",
    "pull_computers_page",
}

READ_OPERATIONS = {
    "read_domain",
    "read_ous",
    "read_users",
    "read_groups",
    "read_computers",
    *PULL_PAGE_OPERATIONS,
}

AD_OBJECT_TYPES = {"ou", "user", "group", "computer"}
MAX_PULL_RECORDS = 5000


def _local_only(request: Request):
    peer = request.client.host if request.client else ""

    try:
        if not ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback:
            raise HTTPException(
                403,
                "Active Directory connector is restricted to local Cartman access.",
            )
    except ValueError as exc:
        raise HTTPException(403, "Cannot verify local Cartman operator.") from exc

    origin = request.headers.get("origin")
    if origin:
        hostname = (urlparse(origin).hostname or "").lower()
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "Cross-origin Active Directory requests are blocked.")


def _audit(request, action, resource_id, details):
    user = getattr(request.state, "auth_user", None)
    actor = user.get("username", "Unattributed") if isinstance(user, dict) else "Unattributed"

    with get_connection() as db:
        db.execute("""
            INSERT INTO iam_audit_events
                (id, actor, action, resource_type, resource_id, details_json)
            VALUES (?, ?, ?, 'active_directory', ?, ?)
        """, (
            str(uuid.uuid4()),
            actor,
            action,
            str(resource_id or ""),
            json.dumps(details or {}, ensure_ascii=False),
        ))


def _target(device_id, require_ready):
    with get_connection() as db:
        row = db.execute("""
            SELECT id, name, os, ip
            FROM devices
            WHERE id = ?
        """, (device_id,)).fetchone()

        registered = db.execute("""
            SELECT 1
            FROM device_agent_credentials
            WHERE device_id = ? AND revoked = 0
            LIMIT 1
        """, (device_id,)).fetchone()

    if row is None:
        raise HTTPException(404, "Windows server device not found.")

    os_name = str(row["os"] or "").lower()
    if "windows" not in os_name and not os_name.startswith("win"):
        raise HTTPException(422, "Active Directory target must be a Windows device.")

    live_connections = (
        get_live_device_connections()
        if callable(get_live_device_connections) else {}
    )
    live = live_connections.get(str(device_id))

    if require_ready:
        if not registered:
            raise HTTPException(409, "This device has no registered CartmanClient identity.")
        if not live or live.get("connected") is not True:
            raise HTTPException(409, "Windows server is offline; no AD query was queued.")
        if live.get("approval_status") != "Approved":
            raise HTTPException(409, "The CartmanClient session is not approved.")
        if live.get("windows_ad_management_enabled") is not True:
            raise HTTPException(
                409,
                "AD capability is not enabled. Start the approved client with "
                "--enable-windows-ad-management.",
            )

    return dict(row), bool(registered), live


@router.get("/api/network/ad/targets")
def list_targets(request: Request):
    _local_only(request)

    with get_connection() as db:
        rows = db.execute("""
            SELECT id, name, os, ip
            FROM devices
            WHERE LOWER(os) LIKE '%windows%' OR LOWER(os) LIKE 'win%'
            ORDER BY name COLLATE NOCASE
        """).fetchall()

        registered_ids = {
            str(row["device_id"])
            for row in db.execute("""
                SELECT DISTINCT device_id
                FROM device_agent_credentials
                WHERE revoked = 0
            """).fetchall()
        }

    live_connections = (
        get_live_device_connections()
        if callable(get_live_device_connections) else {}
    )

    result = []
    for row in rows:
        device_id = str(row["id"])
        live = live_connections.get(device_id)
        connected = bool(live and live.get("connected") is True)
        approved = bool(live and live.get("approval_status") == "Approved")
        capability = bool(
            live and live.get("windows_ad_management_enabled") is True
        )
        registered = device_id in registered_ids

        result.append({
            "id": device_id,
            "name": row["name"],
            "os": row["os"],
            "ip": row["ip"],
            "agent_registered": registered,
            "status": "Online" if connected else "Offline",
            "approved": approved,
            "ad_management_enabled": capability,
            "ready": bool(registered and connected and approved and capability),
            "read_only": True,
            "operations": sorted(READ_OPERATIONS),
        })

    return result


@router.post("/api/network/ad/connector/read", status_code=202)
def request_read(request: Request, payload: dict = Body(...)):
    _local_only(request)

    if not isinstance(payload, dict):
        raise HTTPException(422, "Expected an AD read request.")

    device_id = payload.get("device_id")
    operation = payload.get("operation")

    if not isinstance(device_id, str) or not device_id.strip() or len(device_id) > 120:
        raise HTTPException(422, "A valid device_id is required.")

    if operation not in READ_OPERATIONS:
        raise HTTPException(422, "Unsupported Active Directory read operation.")

    offset = payload.get("offset", 0)
    if operation in PULL_PAGE_OPERATIONS:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 500000:
            raise HTTPException(422, "Invalid AD page offset.")
    else:
        offset = 0

    device, registered, live = _target(device_id.strip(), require_ready=True)

    task_id = "task-" + uuid.uuid4().hex
    task_payload = {
        "connector_action": CONNECTOR_MARKER,
        "operation": operation,
        "confirmed": True,
        "target_os": "Windows",
    }
    if operation in PULL_PAGE_OPERATIONS:
        task_payload["offset"] = offset

    try:
        with get_connection() as db:
            db.execute("""
                INSERT INTO device_tasks
                    (id, device_id, action, payload, scheduled_at)
                VALUES (?, ?, 'remote_command', ?, NULL)
            """, (
                task_id,
                device["id"],
                json.dumps(task_payload, ensure_ascii=False),
            ))
    except sqlite3.Error as exc:
        raise HTTPException(500, "Could not queue the Active Directory read.") from exc

    _audit(request, "active_directory.read.queued", task_id, {
        "device_id": device["id"],
        "device_name": device["name"],
        "operation": operation,
        "read_only": True,
    })

    return {
        "task_id": task_id,
        "device_id": device["id"],
        "device_name": device["name"],
        "operation": operation,
        "status": "Queued",
        "read_only": True,
        "message": "Allowlisted Active Directory read queued.",
    }


@router.get("/api/network/ad/connector/tasks/{task_id}")
def task_status(task_id: str, request: Request):
    _local_only(request)

    with get_connection() as db:
        row = db.execute("""
            SELECT
                t.id, t.device_id, d.name AS device_name, t.action,
                t.payload, t.status, t.result, t.created_at,
                t.started_at, t.finished_at
            FROM device_tasks t
            JOIN devices d ON d.id = t.device_id
            WHERE t.id = ?
        """, (task_id,)).fetchone()

    if row is None:
        raise HTTPException(404, "Active Directory task not found.")

    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}

    if (
        row["action"] != "remote_command"
        or payload.get("connector_action") != CONNECTOR_MARKER
        or payload.get("operation") not in READ_OPERATIONS
    ):
        raise HTTPException(404, "Active Directory task not found.")

    raw = row["result"] or ""
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, json.JSONDecodeError):
        parsed = None

    return {
        "task_id": row["id"],
        "device_id": row["device_id"],
        "device_name": row["device_name"],
        "operation": payload.get("operation"),
        "status": row["status"],
        "result": parsed,
        "result_text": raw if parsed is None else "",
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "read_only": True,
    }


def _ensure_ad_sync_tables():
    """Create the AD mirror separately from Cartman's native IAM tables."""
    if not callable(get_connection):
        raise HTTPException(503, "Cartman database connection is unavailable.")
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS ad_directory_objects (
                domain_dns TEXT NOT NULL COLLATE NOCASE,
                object_guid TEXT NOT NULL,
                object_type TEXT NOT NULL CHECK (object_type IN ('ou','user','group','computer')),
                name TEXT NOT NULL DEFAULT '',
                distinguished_name TEXT NOT NULL DEFAULT '',
                enabled INTEGER,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_sync_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (domain_dns, object_guid)
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ad_directory_type_name
            ON ad_directory_objects(domain_dns, object_type, name COLLATE NOCASE)
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS ad_sync_runs (
                id TEXT PRIMARY KEY,
                domain_dns TEXT NOT NULL COLLATE NOCASE,
                domain_dn TEXT NOT NULL DEFAULT '',
                device_id TEXT NOT NULL,
                device_name TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                counts_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()


def _ad_text(value, maximum=500):
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        raise HTTPException(422, "AD record fields must be scalar values.")
    result = str(value)
    if len(result) > maximum:
        raise HTTPException(422, "An AD record field exceeded the allowed length.")
    return result


@router.post("/api/network/ad/sync/pull/commit")
def commit_pull_from_ad(request: Request, payload: dict = Body(...)):
    """Atomically persist a user-confirmed, fully-read AD snapshot as a separate mirror."""
    _local_only(request)
    _ensure_ad_sync_tables()

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip() or len(device_id) > 120:
        raise HTTPException(422, "A valid Windows target device_id is required.")
    device, registered, live = _target(device_id.strip(), require_ready=True)

    metadata = payload.get("domain_metadata")
    if not isinstance(metadata, dict):
        raise HTTPException(422, "Domain metadata is required for a Pull from AD.")
    domain_dns = _ad_text(metadata.get("domain"), 180).strip().lower()
    if not domain_dns:
        raise HTTPException(422, "AD returned no DNS domain name; nothing was imported.")
    domain_dn = _ad_text(metadata.get("domain_dn"), 240).strip()
    safe_metadata = {
        key: metadata.get(key)
        for key in (
            "domain", "domain_dn", "netbios_name", "forest", "domain_mode",
            "forest_mode", "domain_controllers", "controllers_truncated"
        )
        if key in metadata
    }
    if len(json.dumps(safe_metadata, ensure_ascii=False, default=str)) > 12000:
        raise HTTPException(422, "AD domain metadata is unexpectedly large.")

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise HTTPException(422, "The pull contains no directory records.")
    if len(records) > MAX_PULL_RECORDS:
        raise HTTPException(413, f"This first Pull implementation is limited to {MAX_PULL_RECORDS} objects per run.")

    normalized = []
    seen_guids = set()
    for item in records:
        if not isinstance(item, dict):
            raise HTTPException(422, "Invalid AD record format.")
        object_type = item.get("object_type")
        if object_type not in AD_OBJECT_TYPES:
            raise HTTPException(422, "Unsupported AD object type in pull data.")
        raw_guid = _ad_text(item.get("object_guid"), 80).strip().strip("{}")
        try:
            object_guid = str(uuid.UUID(raw_guid))
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(422, "An AD record has a missing or invalid objectGUID.") from exc
        if object_guid in seen_guids:
            raise HTTPException(422, "Duplicate objectGUID found in the pull; nothing was imported.")
        seen_guids.add(object_guid)

        dn = _ad_text(item.get("distinguished_name"), 500).strip()
        name_value = item.get("name")
        if object_type == "user":
            name_value = item.get("username") or item.get("display_name") or name_value
        name = _ad_text(name_value, 200).strip()
        if not name or not dn:
            raise HTTPException(422, "An AD record is missing its name or distinguished name.")

        attributes = {}
        for key, value in item.items():
            if key == "object_type":
                continue
            if not isinstance(key, str) or len(key) > 80:
                raise HTTPException(422, "Invalid AD attribute name.")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise HTTPException(422, "Nested AD attributes are not accepted.")
            if isinstance(value, str) and len(value) > 500:
                raise HTTPException(422, "An AD attribute exceeded the allowed length.")
            attributes[key] = value
        attributes["object_guid"] = object_guid
        attributes["object_type"] = object_type
        encoded_attributes = json.dumps(attributes, ensure_ascii=False, separators=(",", ":"))
        if len(encoded_attributes) > 8000:
            raise HTTPException(422, "An AD object exceeded the allowed attribute payload size.")

        enabled_raw = item.get("enabled")
        enabled = 1 if enabled_raw is True else 0 if enabled_raw is False else None
        normalized.append({
            "object_type": object_type,
            "object_guid": object_guid,
            "name": name,
            "dn": dn,
            "enabled": enabled,
            "attributes_json": encoded_attributes,
        })

    actor_data = getattr(request.state, "auth_user", None)
    actor = actor_data.get("username", "Unattributed") if isinstance(actor_data, dict) else "Unattributed"
    sync_id = "adsync-" + uuid.uuid4().hex
    counts = {
        kind: {"total": 0, "new": 0, "updated": 0}
        for kind in sorted(AD_OBJECT_TYPES)
    }
    metadata_json = json.dumps(safe_metadata, ensure_ascii=False, separators=(",", ":"), default=str)

    try:
        with get_connection() as db:
            for obj in normalized:
                exists = db.execute("""
                    SELECT 1 FROM ad_directory_objects
                    WHERE domain_dns = ? AND object_guid = ?
                """, (domain_dns, obj["object_guid"])).fetchone()
                bucket = counts[obj["object_type"]]
                bucket["total"] += 1
                bucket["updated" if exists else "new"] += 1
                db.execute("""
                    INSERT INTO ad_directory_objects
                        (domain_dns, object_guid, object_type, name, distinguished_name,
                         enabled, attributes_json, last_sync_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain_dns, object_guid) DO UPDATE SET
                        object_type = excluded.object_type,
                        name = excluded.name,
                        distinguished_name = excluded.distinguished_name,
                        enabled = excluded.enabled,
                        attributes_json = excluded.attributes_json,
                        last_synced_at = CURRENT_TIMESTAMP,
                        last_sync_id = excluded.last_sync_id
                """, (
                    domain_dns, obj["object_guid"], obj["object_type"], obj["name"],
                    obj["dn"], obj["enabled"], obj["attributes_json"], sync_id
                ))

            new_count = sum(value["new"] for value in counts.values())
            updated_count = sum(value["updated"] for value in counts.values())
            summary = {
                "total": len(normalized),
                "new": new_count,
                "updated": updated_count,
                "deleted": 0,
                "counts_by_type": counts,
                "note": "Objects absent from this pull are not deleted from the Cartman mirror.",
            }
            db.execute("""
                INSERT INTO ad_sync_runs
                    (id, domain_dns, domain_dn, device_id, device_name, actor,
                     status, counts_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, 'Succeeded', ?, ?)
            """, (
                sync_id, domain_dns, domain_dn, device["id"], device["name"], actor,
                json.dumps(summary, ensure_ascii=False), metadata_json
            ))
            db.execute("""
                INSERT INTO iam_audit_events
                    (id, actor, action, resource_type, resource_id, details_json)
                VALUES (?, ?, 'active_directory.pull.completed', 'active_directory', ?, ?)
            """, (
                str(uuid.uuid4()), actor, sync_id,
                json.dumps({
                    "device_id": device["id"], "device_name": device["name"],
                    "domain_dns": domain_dns, "total": len(normalized),
                    "new": new_count, "updated": updated_count, "deleted": 0,
                }, ensure_ascii=False)
            ))
            db.commit()
    except sqlite3.Error as exc:
        raise HTTPException(500, "The AD pull could not be saved. The database transaction was rolled back.") from exc

    return {
        "status": "Succeeded",
        "sync_id": sync_id,
        "domain_dns": domain_dns,
        "device_id": device["id"],
        "device_name": device["name"],
        **summary,
    }

