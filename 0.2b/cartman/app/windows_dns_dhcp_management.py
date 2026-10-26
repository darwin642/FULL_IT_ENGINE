"""Local-only, preview-and-confirm Windows DNS/DHCP management API."""
import datetime as dt
import ipaddress
import json
import re
import secrets
import sqlite3
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter()
get_connection = None
get_live_device_connections = None

CHANGE_MARKER = "windows_dns_dhcp_management_v1"

WRITE_OPS = {
    "dhcp_scope_options", "dhcp_scope_lease",
    "dhcp_reservation_add", "dhcp_reservation_delete",
    "dhcp_exclusion_add", "dhcp_exclusion_delete",
    "dns_a_create", "dns_a_update", "dns_a_delete",
    "dns_cname_create", "dns_cname_update", "dns_cname_delete",
    "dns_zone_create",
}


def _local(request):
    peer = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback:
            raise HTTPException(403, "DNS/DHCP management is local-only.")
    except ValueError as exc:
        raise HTTPException(403, "Cannot verify local operator.") from exc

    origin = request.headers.get("origin")
    if origin and (
        urlparse(origin).hostname or ""
    ).lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "Cross-origin DNS/DHCP changes are blocked.")


def _text(value, label, max_len=253, required=True):
    value = str(value or "").strip()
    if required and not value:
        raise HTTPException(422, f"{label} is required.")
    if len(value) > max_len or any(ord(c) < 32 for c in value):
        raise HTTPException(422, f"{label} is invalid or too long.")
    return value


def _ip(value, label, required=True):
    value = _text(value, label, 15, required)
    if not value:
        return ""
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise HTTPException(422, f"{label} must be IPv4.") from exc


def _dns_name(value, label, relative=False):
    value = _text(value, label, 253)
    if relative and value == "@":
        return value
    if value.endswith("."):
        raise HTTPException(422, f"{label} must not end with a dot.")

    # Write operations deliberately disallow wildcard record names.
    pattern = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if not all(re.fullmatch(pattern, part) for part in value.split(".")):
        raise HTTPException(422, f"{label} is not a valid DNS name.")
    return value.lower()


def _ensure_tables():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS network_dns_dhcp_change_plans (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                confirmation_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Prepared',
                expires_at TEXT NOT NULL,
                task_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at TEXT
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_dns_dhcp_plans_status
            ON network_dns_dhcp_change_plans(status, created_at DESC)
        """)


def _normalize(raw):
    p = dict(raw or {})
    operation = _text(p.get("operation"), "Operation", 50)
    if operation not in WRITE_OPS:
        raise HTTPException(422, "Unsupported DNS/DHCP operation.")

    out = {
        "operation": operation,
        "device_id": _text(p.get("device_id"), "Windows server", 120),
    }

    dhcp_ops = {
        "dhcp_scope_options", "dhcp_scope_lease",
        "dhcp_reservation_add", "dhcp_reservation_delete",
        "dhcp_exclusion_add", "dhcp_exclusion_delete",
    }

    if operation in dhcp_ops:
        scope_id = _ip(p.get("scope_id"), "DHCP scope ID")
        out["scope_id"] = scope_id

        if operation in {"dhcp_exclusion_add", "dhcp_exclusion_delete"}:
            start_ip = _ip(p.get("start_ip"), "Exclusion start IP")
            end_ip = _ip(p.get("end_ip"), "Exclusion end IP")
            if int(ipaddress.IPv4Address(start_ip)) > int(ipaddress.IPv4Address(end_ip)):
                raise HTTPException(422, "Exclusion start IP must be at or before end IP.")
            out.update(start_ip=start_ip, end_ip=end_ip)
            action = "Add" if operation == "dhcp_exclusion_add" else "Delete exact"
            return out, f"{action} DHCP exclusion {start_ip}–{end_ip} in scope {scope_id}."

        if operation == "dhcp_scope_lease":
            try:
                hours = int(p.get("lease_hours"))
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    422, "Lease hours must be a whole number."
                ) from exc
            if not 1 <= hours <= 8760:
                raise HTTPException(422, "Lease hours must be 1–8760.")
            out["lease_hours"] = hours
            return out, (
                f"Set DHCP scope {scope_id} lease duration to {hours} hour(s)."
            )

        if operation == "dhcp_scope_options":
            gateway = _ip(p.get("router"), "Gateway", required=False)
            dns = p.get("dns_servers") or []
            if isinstance(dns, str):
                dns = [x.strip() for x in dns.split(",") if x.strip()]
            if not isinstance(dns, list) or len(dns) > 8:
                raise HTTPException(
                    422, "Provide up to eight DNS IPv4 addresses."
                )
            dns = [_ip(x, "DNS server") for x in dns]
            domain = (
                _dns_name(p.get("dns_domain"), "DHCP DNS domain")
                if p.get("dns_domain") else ""
            )
            raw_before = p.get("expected_before")
            if not isinstance(raw_before, dict):
                raise HTTPException(
                    422, "A fresh live DHCP scope read is required for preview."
                )
            if any(k not in raw_before for k in ("router", "dns_servers", "dns_domain")):
                raise HTTPException(422, "Live DHCP baseline is incomplete.")

            def _option_list(key, label, normalizer):
                values = raw_before.get(key, [])
                if isinstance(values, str):
                    values = [values] if values else []
                if not isinstance(values, list) or len(values) > 8:
                    raise HTTPException(
                        422, f"{label} must be a list of up to eight values."
                    )
                return [normalizer(value, label) for value in values]

            expected_router = _option_list("router", "Current DHCP router", _ip)
            expected_dns = _option_list("dns_servers", "Current DHCP DNS server", _ip)
            expected_domain = _option_list(
                "dns_domain", "Current DHCP DNS domain", _dns_name
            )

            if not (gateway or dns or domain):
                raise HTTPException(
                    422, "Specify a gateway, DNS server, or DNS domain."
                )
            out.update(
                router=gateway,
                dns_servers=dns,
                dns_domain=domain,
                expected_before={
                    "router": expected_router,
                    "dns_servers": expected_dns,
                    "dns_domain": expected_domain,
                },
            )
            parts = (
                (["gateway → " + gateway] if gateway else [])
                + (["DNS → " + ", ".join(dns)] if dns else [])
                + (["domain → " + domain] if domain else [])
            )
            return out, f"Update DHCP scope {scope_id}: " + "; ".join(parts)

        address = _ip(p.get("ip_address"), "Reservation IP")
        out["ip_address"] = address
        mac = _text(
            p.get("mac_address"),
            "Client MAC confirmation" if operation == "dhcp_reservation_delete"
            else "Client MAC",
            40,
        ).upper().replace(":", "-")
        if not re.fullmatch(r"[0-9A-F]{2}(?:-[0-9A-F]{2}){5}", mac):
            raise HTTPException(
                422, "MAC must look like 00-11-22-33-44-55."
            )
        out["mac_address"] = mac

        if operation == "dhcp_reservation_add":
            name = _text(
                p.get("reservation_name"), "Reservation name", 150,
                required=False,
            )
            out["reservation_name"] = name
            return out, (
                f"Add reservation {address} → {mac} in scope {scope_id}."
            )

        return out, (
            f"Delete reservation {address} with MAC {mac} in scope {scope_id}."
        )

    if operation == "dns_zone_create":
        zone = _dns_name(p.get("zone"), "DNS zone")
        out["zone"] = zone
        return out, (
            f"Create a standard primary DNS zone {zone} on the selected Windows DNS server. "
            "This local zone is authoritative for that domain on this DNS server."
        )

    zone = _dns_name(p.get("zone"), "DNS zone")
    name = _dns_name(p.get("record_name"), "Record name", relative=True)
    out.update(zone=zone, record_name=name)

    try:
        ttl = int(p.get("ttl") or 3600)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "TTL must be integer seconds.") from exc
    if not 30 <= ttl <= 604800:
        raise HTTPException(422, "TTL must be 30–604800 seconds.")

    out["ttl"] = ttl
    record_type = "A" if operation.startswith("dns_a_") else "CNAME"
    out["record_type"] = record_type

    if operation.endswith(("_update", "_delete")):
        old_value = (
            _ip(p.get("old_value"), "Current A record value")
            if record_type == "A"
            else _dns_name(p.get("old_value"), "Current CNAME target")
        )
        out["old_value"] = old_value

    if operation.endswith(("_create", "_update")):
        new_value = (
            _ip(p.get("new_value"), "New A record value")
            if record_type == "A"
            else _dns_name(p.get("new_value"), "New CNAME target")
        )
        out["new_value"] = new_value

    # @ means the zone apex; display the bare zone name, not @.zone.
    fqdn = zone if name == "@" else f"{name}.{zone}"

    if operation.endswith("_create"):
        summary = (
            f"Create DNS {record_type} {fqdn} "
            f"→ {out['new_value']} (TTL {ttl})."
        )
    elif operation.endswith("_update"):
        summary = (
            f"Change DNS {record_type} {fqdn}: "
            f"{out['old_value']} → {out['new_value']} (TTL {ttl})."
        )
    else:
        summary = (
            f"Delete only DNS {record_type} {fqdn} "
            f"= {out['old_value']}."
        )
    return out, summary


def _device(device_id, require_ready):
    with get_connection() as db:
        row = db.execute(
            "SELECT id,name,os,ip FROM devices WHERE id=?",
            (device_id,),
        ).fetchone()
        registered = db.execute("""
            SELECT 1 FROM device_agent_credentials
            WHERE device_id=? AND revoked=0
            LIMIT 1
        """, (device_id,)).fetchone()

    if not row:
        raise HTTPException(404, "Windows server device not found.")

    os_name = (row["os"] or "").lower()
    if "windows" not in os_name and not os_name.startswith("win"):
        raise HTTPException(422, "Target must be Windows.")
    if not registered:
        raise HTTPException(
            409, "No registered CartmanClient identity for this device."
        )

    live_connections = (
        get_live_device_connections()
        if callable(get_live_device_connections) else {}
    )
    live = live_connections.get(str(device_id))

    if require_ready:
        if not live or live.get("connected") is not True:
            raise HTTPException(
                409, "Windows server is offline; no change was queued."
            )
        if live.get("windows_dns_dhcp_management_enabled") is not True:
            raise HTTPException(
                409,
                "Restart CartmanClient with "
                "--enable-windows-dns-dhcp-management.",
            )
    return dict(row), live


@router.get("/api/network/dns-dhcp/targets")
def list_targets(request: Request):
    _local(request)
    live_by_device = (
        get_live_device_connections()
        if callable(get_live_device_connections) else {}
    )
    with get_connection() as db:
        rows = db.execute("""
            SELECT d.id,d.name,d.os,d.ip,
              EXISTS(
                SELECT 1 FROM device_agent_credentials c
                WHERE c.device_id=d.id AND c.revoked=0
              ) AS agent_registered
            FROM devices d
            WHERE LOWER(d.os) LIKE '%windows%' OR LOWER(d.os) LIKE 'win%'
            ORDER BY d.name COLLATE NOCASE
        """).fetchall()

    result = []
    for row in rows:
        live = live_by_device.get(str(row["id"]))
        connected = bool(live and live.get("connected") is True)
        enabled = bool(
            live and live.get("windows_dns_dhcp_management_enabled") is True
        )
        result.append({
            "id": row["id"],
            "name": row["name"],
            "os": row["os"],
            "ip": row["ip"],
            "agent_registered": bool(row["agent_registered"]),
            "status": "Online" if connected else "Offline",
            "dns_dhcp_management_enabled": enabled,
            "ready": bool(connected and enabled and row["agent_registered"]),
        })
    return result


@router.post("/api/network/dns-dhcp/connector/read", status_code=202)
def request_read(request: Request, payload: dict = Body(...)):
    _local(request)
    _ensure_tables()
    device_id = _text(payload.get("device_id"), "Windows server", 120)
    subsystem = payload.get("subsystem", "dhcp")
    operation_map = {
        "dhcp": "read_dhcp",
        "dns": "read_dns",
        "dhcp-leases": "read_dhcp_leases",
        "dhcp-reservations": "read_dhcp_reservations",
        "dhcp-exclusions": "read_dhcp_exclusions",
    }
    if subsystem not in operation_map:
        raise HTTPException(
            422,
            "Subsystem must be dhcp, dns, dhcp-leases, dhcp-reservations, or dhcp-exclusions.",
        )

    parameters = {}
    if subsystem in {"dhcp-leases", "dhcp-reservations", "dhcp-exclusions"}:
        parameters["scope_id"] = _ip(payload.get("scope_id"), "DHCP scope ID")
        try:
            offset = int(payload.get("offset", 0))
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "Offset must be a non-negative whole number.") from exc
        if offset < 0 or offset > 100000:
            raise HTTPException(422, "Offset must be between 0 and 100000.")
        parameters["offset"] = offset

    device, _ = _device(device_id, True)
    task_id = "task-" + uuid.uuid4().hex
    task_payload = {
        "connector_action": CHANGE_MARKER,
        "operation": operation_map[subsystem],
        "parameters": parameters,
        "confirmed": True,
    }
    with get_connection() as db:
        db.execute("""
            INSERT INTO device_tasks
                (id,device_id,action,payload,scheduled_at)
            VALUES (?,?,'remote_command',?,NULL)
        """, (task_id, device_id, json.dumps(task_payload)))

    return {
        "task_id": task_id,
        "device_id": device_id,
        "device_name": device["name"],
        "status": "Queued",
        "read_only": True,
    }


@router.post("/api/network/dns-dhcp/changes/preview", status_code=201)
def preview(request: Request, payload: dict = Body(...)):
    _local(request)
    _ensure_tables()
    normalized, summary = _normalize(payload)
    device, _ = _device(normalized["device_id"], False)
    plan_id = "ndcp-" + uuid.uuid4().hex
    code = secrets.token_hex(3).upper()
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)

    with get_connection() as db:
        db.execute("""
            INSERT INTO network_dns_dhcp_change_plans (
                id,device_id,operation,payload_json,summary,
                confirmation_code,status,expires_at
            ) VALUES (?,?,?,?,?,?,'Prepared',?)
        """, (
            plan_id, normalized["device_id"], normalized["operation"],
            json.dumps(normalized), summary, code, expires.isoformat(),
        ))

    return {
        "plan_id": plan_id,
        "target": device["name"],
        "target_ip": device["ip"],
        "operation": normalized["operation"],
        "summary": summary,
        "changes": normalized,
        "confirmation_phrase": f"APPLY {code}",
        "expires_at": expires.isoformat(),
        "status": "Prepared",
        "warning": (
            "Preview only. The Windows agent re-checks the exact current "
            "scope, zone, or record before applying. No configuration has changed."
        ),
    }


@router.post("/api/network/dns-dhcp/changes/{plan_id}/apply", status_code=202)
def apply_plan(plan_id: str, request: Request, payload: dict = Body(...)):
    _local(request)
    _ensure_tables()

    with get_connection() as db:
        row = db.execute(
            "SELECT * FROM network_dns_dhcp_change_plans WHERE id=?",
            (plan_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "Change plan not found.")
    if row["status"] != "Prepared":
        raise HTTPException(
            409, f"Plan is {row['status']} and cannot be applied again."
        )
    if dt.datetime.now(dt.timezone.utc) >= dt.datetime.fromisoformat(
        row["expires_at"]
    ):
        with get_connection() as db:
            db.execute("""
                UPDATE network_dns_dhcp_change_plans
                SET status='Expired'
                WHERE id=? AND status='Prepared'
            """, (plan_id,))
        raise HTTPException(410, "Change plan expired; prepare a new preview.")

    expected = f"APPLY {row['confirmation_code']}"
    if str(payload.get("confirmation") or "").strip() != expected:
        raise HTTPException(
            422, f"Confirmation must exactly match: {expected}"
        )

    device_id = row["device_id"]
    device, _ = _device(device_id, True)
    values = json.loads(row["payload_json"])
    task_id = "task-" + uuid.uuid4().hex
    task_payload = {
        "connector_action": CHANGE_MARKER,
        "operation": values["operation"],
        "parameters": {
            k: v for k, v in values.items()
            if k not in {"device_id", "operation"}
        },
        "plan_id": plan_id,
        "confirmed": True,
    }

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT status FROM network_dns_dhcp_change_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
        if not current or current["status"] != "Prepared":
            raise HTTPException(409, "Plan already used.")
        db.execute("""
            INSERT INTO device_tasks
                (id,device_id,action,payload,scheduled_at)
            VALUES (?,?,'remote_command',?,NULL)
        """, (task_id, device_id, json.dumps(task_payload)))
        db.execute("""
            UPDATE network_dns_dhcp_change_plans
            SET status='Queued',task_id=?,applied_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (task_id, plan_id))

    return {
        "plan_id": plan_id,
        "task_id": task_id,
        "device_id": device_id,
        "device_name": device["name"],
        "status": "Queued",
        "summary": row["summary"],
        "message": (
            "The confirmed allowlisted operation is queued. "
            "The result will be verified from the Windows agent."
        ),
    }


@router.get("/api/network/dns-dhcp/connector/tasks/{task_id}")
def task_status(task_id: str, request: Request):
    _local(request)
    with get_connection() as db:
        row = db.execute("""
            SELECT t.id,t.device_id,d.name AS device_name,t.action,t.payload,
                   t.status,t.result,t.created_at,t.started_at,t.finished_at
            FROM device_tasks t
            JOIN devices d ON d.id=t.device_id
            WHERE t.id=?
        """, (task_id,)).fetchone()

    if not row:
        raise HTTPException(404, "Task not found.")

    try:
        job = json.loads(row["payload"] or "{}")
    except (TypeError, json.JSONDecodeError):
        job = {}

    if (
        row["action"] != "remote_command"
        or job.get("connector_action") != CHANGE_MARKER
    ):
        raise HTTPException(404, "DNS/DHCP task not found.")

    raw = row["result"] or ""
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, json.JSONDecodeError):
        parsed = None

    with get_connection() as db:
        plan = db.execute(
            "SELECT id FROM network_dns_dhcp_change_plans WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if plan and row["status"] in {"Succeeded", "Failed", "Cancelled"}:
            db.execute("""
                UPDATE network_dns_dhcp_change_plans SET status=?
                WHERE task_id=?
            """, (row["status"], task_id))

    return {
        "task_id": row["id"],
        "device_id": row["device_id"],
        "device_name": row["device_name"],
        "status": row["status"],
        "result": parsed,
        "result_text": raw if parsed is None else "",
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
