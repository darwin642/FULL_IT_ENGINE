"""Cartman Network & Infrastructure API routes.

The router uses Cartman's shared SQLite connection provider configured by main.py.
External DNS/DHCP systems and network hardware are not mutated by registry CRUD.
"""
import datetime as _datetime
import ipaddress
import json
import socket
import subprocess
import sys
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, validator

router = APIRouter()
get_connection = None  # Injected by main.py before database initialization.
get_live_device_connections = None  # Injected by main.py.

# ============================================================
# CARTMAN NETWORK & INFRASTRUCTURE API V1
# Persistent management APIs for the ten Network & Infrastructure pages.
# Network discovery is deliberately limited to explicitly confirmed private
# IPv4 ranges (/24 or smaller) and a fixed list of common TCP service ports.
# DNS/DHCP objects are Cartman-managed records until a provider connector is
# configured; creating records here does not mutate an external DNS/DHCP server.
# ============================================================



NETWORK_DEVICE_STATUSES = {"Online", "Warning", "Offline", "Unknown"}
NETWORK_CAPACITY_METRICS = {
    "cpu_percent": "%", "memory_percent": "%", "disk_percent": "%",
    "network_mbps": "Mbps", "cpu_cores": "cores", "memory_gb": "GB",
    "storage_gb": "GB",
}
NETWORK_DISCOVERY_PORTS = (22, 53, 80, 443, 445, 3389, 8080, 8443)


def initialize_network_infrastructure_database():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS network_devices (
                id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL COLLATE NOCASE UNIQUE,
                device_type TEXT NOT NULL DEFAULT 'Switch',
                management_ip TEXT NOT NULL DEFAULT '',
                vendor TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                firmware TEXT NOT NULL DEFAULT '',
                serial_number TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Unknown',
                notes TEXT NOT NULL DEFAULT '',
                last_seen TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_network_devices_status
                ON network_devices(status, hostname);
            CREATE INDEX IF NOT EXISTS idx_network_devices_ip
                ON network_devices(management_ip);

            CREATE TABLE IF NOT EXISTS network_discovery_jobs (
                id TEXT PRIMARY KEY,
                cidr TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                hosts_found INTEGER NOT NULL DEFAULT 0,
                results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_network_discovery_jobs_created
                ON network_discovery_jobs(created_at DESC);

            CREATE TABLE IF NOT EXISTS network_topology_links (
                id TEXT PRIMARY KEY,
                source_device_id TEXT NOT NULL REFERENCES network_devices(id) ON DELETE CASCADE,
                target_device_id TEXT NOT NULL REFERENCES network_devices(id) ON DELETE CASCADE,
                source_interface TEXT NOT NULL DEFAULT '',
                target_interface TEXT NOT NULL DEFAULT '',
                link_type TEXT NOT NULL DEFAULT 'Ethernet',
                status TEXT NOT NULL DEFAULT 'Unknown',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_device_id, target_device_id, source_interface, target_interface)
            );

            CREATE TABLE IF NOT EXISTS network_subnets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                cidr TEXT NOT NULL UNIQUE,
                vlan INTEGER,
                gateway TEXT NOT NULL DEFAULT '',
                dns_servers_json TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS network_ip_addresses (
                id TEXT PRIMARY KEY,
                subnet_id TEXT NOT NULL REFERENCES network_subnets(id) ON DELETE RESTRICT,
                address TEXT NOT NULL UNIQUE,
                hostname TEXT NOT NULL DEFAULT '',
                mac_address TEXT NOT NULL DEFAULT '',
                device_id TEXT REFERENCES network_devices(id) ON DELETE SET NULL,
                assignment_type TEXT NOT NULL DEFAULT 'Static',
                status TEXT NOT NULL DEFAULT 'Assigned',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_network_ip_subnet
                ON network_ip_addresses(subnet_id, address);

            CREATE TABLE IF NOT EXISTS network_dns_records (
                id TEXT PRIMARY KEY,
                zone TEXT NOT NULL,
                name TEXT NOT NULL,
                record_type TEXT NOT NULL,
                value TEXT NOT NULL,
                ttl INTEGER NOT NULL DEFAULT 3600,
                status TEXT NOT NULL DEFAULT 'Active',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(zone, name, record_type, value)
            );

            CREATE TABLE IF NOT EXISTS network_dhcp_scopes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                cidr TEXT NOT NULL,
                start_ip TEXT NOT NULL,
                end_ip TEXT NOT NULL,
                gateway TEXT NOT NULL DEFAULT '',
                dns_servers_json TEXT NOT NULL DEFAULT '[]',
                lease_duration INTEGER NOT NULL DEFAULT 86400,
                status TEXT NOT NULL DEFAULT 'Active',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS network_dhcp_leases (
                id TEXT PRIMARY KEY,
                scope_id TEXT NOT NULL REFERENCES network_dhcp_scopes(id) ON DELETE RESTRICT,
                address TEXT NOT NULL,
                mac_address TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scope_id, address)
            );

            CREATE TABLE IF NOT EXISTS network_diagnostic_runs (
                id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                test_type TEXT NOT NULL,
                port INTEGER,
                status TEXT NOT NULL,
                resolved_addresses_json TEXT NOT NULL DEFAULT '[]',
                response_ms REAL,
                result_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_network_diagnostics_created
                ON network_diagnostic_runs(created_at DESC);

            CREATE TABLE IF NOT EXISTS network_server_profiles (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
                server_role TEXT NOT NULL DEFAULT 'General purpose',
                environment TEXT NOT NULL DEFAULT 'Unspecified',
                criticality TEXT NOT NULL DEFAULT 'Medium',
                location TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS network_server_dependencies (
                id TEXT PRIMARY KEY,
                source_device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                target_device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                relationship TEXT NOT NULL DEFAULT 'Depends on',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_device_id, target_device_id, relationship)
            );

            CREATE TABLE IF NOT EXISTS network_capacity_records (
                id TEXT PRIMARY KEY,
                device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual-entry',
                notes TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_network_capacity_device_time
                ON network_capacity_records(device_id, recorded_at DESC);

            CREATE TABLE IF NOT EXISTS network_capacity_plans (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                current_value REAL NOT NULL DEFAULT 0,
                target_value REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                target_date TEXT NOT NULL DEFAULT '',
                owner TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Planned',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)



def _ni_id(prefix):
    return prefix + "-" + uuid.uuid4().hex


def _ni_clean(value, max_length=500, required=False, field_name="Value"):
    result = str(value or "").strip()
    if required and not result:
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    if len(result) > max_length:
        raise HTTPException(status_code=422, detail=f"{field_name} is too long")
    if any(ord(ch) < 32 for ch in result):
        raise HTTPException(status_code=422, detail=f"{field_name} contains invalid characters")
    return result


def _ni_ip(value, field_name="IP address", allow_blank=False):
    text = _ni_clean(value, 64, required=not allow_blank, field_name=field_name)
    if not text and allow_blank:
        return ""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field_name} is not a valid IP address")


def _ni_parse_cidr(value, ipv4_only=False):
    try:
        network = ipaddress.ip_network(_ni_clean(value, 100, required=True, field_name="CIDR"), strict=False)
    except ValueError:
        raise HTTPException(status_code=422, detail="CIDR is not valid")
    if ipv4_only and network.version != 4:
        raise HTTPException(status_code=422, detail="This operation requires an IPv4 network")
    return network


def _ni_dict(row):
    return dict(row) if row is not None else None


def _ni_rows(rows):
    return [dict(row) for row in rows]


def _ni_json(row, field, output_name=None, fallback=None):
    result = dict(row)
    output_name = output_name or field.removesuffix("_json")
    try:
        result[output_name] = json.loads(result.pop(field) or "null")
    except (TypeError, json.JSONDecodeError):
        result[output_name] = fallback if fallback is not None else []
    return result


class NetworkDeviceInput(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=150)
    device_type: str = Field(default="Switch", max_length=80)
    management_ip: str = Field(default="", max_length=64)
    vendor: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=120)
    firmware: str = Field(default="", max_length=120)
    serial_number: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=180)
    status: str = Field(default="Unknown", max_length=30)
    notes: str = Field(default="", max_length=2000)

    @validator("hostname", "device_type")
    def _network_required_text(cls, value):
        if not value or not value.strip():
            raise ValueError("This field is required")
        return value.strip()


class NetworkDiscoveryInput(BaseModel):
    cidr: str = Field(..., min_length=1, max_length=100)
    confirm_authorized: bool = False


class NetworkDiscoveryImportInput(BaseModel):
    addresses: list = Field(...)


class NetworkTopologyLinkInput(BaseModel):
    source_device_id: str = Field(..., min_length=1, max_length=100)
    target_device_id: str = Field(..., min_length=1, max_length=100)
    source_interface: str = Field(default="", max_length=120)
    target_interface: str = Field(default="", max_length=120)
    link_type: str = Field(default="Ethernet", max_length=50)
    status: str = Field(default="Unknown", max_length=30)
    notes: str = Field(default="", max_length=1000)


class NetworkSubnetInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    cidr: str = Field(..., min_length=1, max_length=100)
    vlan: Optional[int] = Field(default=None, ge=1, le=4094)
    gateway: str = Field(default="", max_length=64)
    dns_servers: list = Field(default_factory=list)
    description: str = Field(default="", max_length=1000)
    status: str = Field(default="Active", max_length=30)


class NetworkIPAddressInput(BaseModel):
    subnet_id: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., min_length=1, max_length=64)
    hostname: str = Field(default="", max_length=150)
    mac_address: str = Field(default="", max_length=40)
    device_id: str = Field(default="", max_length=100)
    assignment_type: str = Field(default="Static", max_length=40)
    status: str = Field(default="Assigned", max_length=30)
    notes: str = Field(default="", max_length=1000)


class NetworkDNSRecordInput(BaseModel):
    zone: str = Field(..., min_length=1, max_length=253)
    name: str = Field(..., min_length=1, max_length=253)
    record_type: str = Field(default="A", max_length=10)
    value: str = Field(..., min_length=1, max_length=1000)
    ttl: int = Field(default=3600, ge=30, le=604800)
    status: str = Field(default="Active", max_length=30)
    notes: str = Field(default="", max_length=1000)


class NetworkDHCPScopeInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    cidr: str = Field(..., min_length=1, max_length=100)
    start_ip: str = Field(..., min_length=1, max_length=64)
    end_ip: str = Field(..., min_length=1, max_length=64)
    gateway: str = Field(default="", max_length=64)
    dns_servers: list = Field(default_factory=list)
    lease_duration: int = Field(default=86400, ge=60, le=31536000)
    status: str = Field(default="Active", max_length=30)
    notes: str = Field(default="", max_length=1000)


class NetworkDHCPLeaseInput(BaseModel):
    scope_id: str = Field(..., min_length=1, max_length=100)
    address: str = Field(..., min_length=1, max_length=64)
    mac_address: str = Field(default="", max_length=40)
    hostname: str = Field(default="", max_length=150)
    expires_at: str = Field(default="", max_length=80)
    status: str = Field(default="Active", max_length=30)


class NetworkDiagnosticInput(BaseModel):
    target: str = Field(..., min_length=1, max_length=253)
    test_type: str = Field(default="dns", max_length=20)
    port: Optional[int] = Field(default=None, ge=1, le=65535)


class NetworkServerProfileInput(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=100)
    server_role: str = Field(default="General purpose", max_length=100)
    environment: str = Field(default="Unspecified", max_length=80)
    criticality: str = Field(default="Medium", max_length=30)
    location: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=1000)


class NetworkServerDependencyInput(BaseModel):
    source_device_id: str = Field(..., min_length=1, max_length=100)
    target_device_id: str = Field(..., min_length=1, max_length=100)
    relationship: str = Field(default="Depends on", max_length=100)
    notes: str = Field(default="", max_length=1000)


class NetworkCapacityRecordInput(BaseModel):
    device_id: str = Field(default="", max_length=100)
    metric_name: str = Field(..., min_length=1, max_length=50)
    value: float
    unit: str = Field(default="", max_length=20)
    notes: str = Field(default="", max_length=500)


class NetworkCapacityPlanInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=180)
    resource_type: str = Field(..., min_length=1, max_length=50)
    current_value: float = Field(default=0, ge=0)
    target_value: float = Field(..., ge=0)
    unit: str = Field(default="", max_length=20)
    target_date: str = Field(default="", max_length=40)
    owner: str = Field(default="", max_length=120)
    status: str = Field(default="Planned", max_length=30)
    notes: str = Field(default="", max_length=1000)


def _ni_validate_device_payload(payload):
    hostname = _ni_clean(payload.hostname, 150, True, "Hostname")
    device_type = _ni_clean(payload.device_type, 80, True, "Device type")
    management_ip = _ni_ip(payload.management_ip, "Management IP", allow_blank=True)
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in NETWORK_DEVICE_STATUSES:
        raise HTTPException(status_code=422, detail="Status must be Online, Warning, Offline, or Unknown")
    return {
        "hostname": hostname,
        "device_type": device_type,
        "management_ip": management_ip,
        "vendor": _ni_clean(payload.vendor, 120),
        "model": _ni_clean(payload.model, 120),
        "firmware": _ni_clean(payload.firmware, 120),
        "serial_number": _ni_clean(payload.serial_number, 120),
        "location": _ni_clean(payload.location, 180),
        "status": status,
        "notes": _ni_clean(payload.notes, 2000),
    }


def _ni_server_exists(connection, device_id):
    return connection.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone() is not None


@router.get("/api/network/health")
def network_api_health():
    with get_connection() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "module": "network-infrastructure", "storage": "sqlite", "generated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat()}


@router.get("/api/network/overview")
def network_overview():
    with get_connection() as connection:
        count_devices = connection.execute("SELECT COUNT(*) FROM network_devices").fetchone()[0]
        online_devices = connection.execute("SELECT COUNT(*) FROM network_devices WHERE status = 'Online'").fetchone()[0]
        subnets = connection.execute("SELECT COUNT(*) FROM network_subnets").fetchone()[0]
        ip_addresses = connection.execute("SELECT COUNT(*) FROM network_ip_addresses").fetchone()[0]
        dns_records = connection.execute("SELECT COUNT(*) FROM network_dns_records WHERE status = 'Active'").fetchone()[0]
        dhcp_scopes = connection.execute("SELECT COUNT(*) FROM network_dhcp_scopes WHERE status = 'Active'").fetchone()[0]
        discovery_jobs = connection.execute("SELECT COUNT(*) FROM network_discovery_jobs").fetchone()[0]
        discovery_running = connection.execute("SELECT COUNT(*) FROM network_discovery_jobs WHERE status IN ('Pending','Running')").fetchone()[0]
        diagnostic_runs = connection.execute("SELECT COUNT(*) FROM network_diagnostic_runs").fetchone()[0]
        failed_diagnostics = connection.execute("SELECT COUNT(*) FROM network_diagnostic_runs WHERE status = 'Failed'").fetchone()[0]
        topology_links = connection.execute("SELECT COUNT(*) FROM network_topology_links").fetchone()[0]
        server_profiles = connection.execute("SELECT COUNT(*) FROM network_server_profiles").fetchone()[0]
        capacity_manual_count = connection.execute("SELECT COUNT(*) FROM network_capacity_records").fetchone()[0]
        capacity_telemetry_count = connection.execute("SELECT COUNT(*) FROM monitoring_metrics").fetchone()[0]
        capacity_records = capacity_manual_count + capacity_telemetry_count
        recent_devices = _ni_rows(connection.execute("SELECT id, hostname, device_type, management_ip, vendor, model, status, location, last_seen, created_at FROM network_devices ORDER BY updated_at DESC LIMIT 6").fetchall())
        recent_jobs = _ni_rows(connection.execute("SELECT id, cidr, status, hosts_found, error, started_at, completed_at, created_at FROM network_discovery_jobs ORDER BY created_at DESC LIMIT 5").fetchall())
    return {
        "generated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "devices": {"total": count_devices, "online": online_devices, "items": recent_devices},
        "ipam": {"subnets": subnets, "addresses": ip_addresses},
        "dns_dhcp": {"dns_records": dns_records, "dhcp_scopes": dhcp_scopes},
        "discovery": {"jobs": discovery_jobs, "running": discovery_running, "recent": recent_jobs},
        "topology": {"links": topology_links},
        "diagnostics": {"runs": diagnostic_runs, "failed": failed_diagnostics},
        "infrastructure": {"server_profiles": server_profiles, "capacity_records": capacity_records,
                            "capacity_manual_count": capacity_manual_count,
                            "capacity_telemetry_count": capacity_telemetry_count},
    }


@router.get("/api/network/devices")
def list_network_devices(status: Optional[str] = None, device_type: Optional[str] = None, limit: int = 500):
    limit = max(1, min(limit, 1000))
    sql = "SELECT * FROM network_devices"
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if device_type:
        clauses.append("device_type = ?")
        params.append(device_type)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY hostname COLLATE NOCASE LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return _ni_rows(connection.execute(sql, params).fetchall())


@router.get("/api/network/devices/{device_id}")
def get_network_device(device_id: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM network_devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Network device not found")
    return dict(row)


@router.post("/api/network/devices", status_code=201)
def create_network_device(payload: NetworkDeviceInput):
    values = _ni_validate_device_payload(payload)
    device_id = _ni_id("netdev")
    try:
        with get_connection() as connection:
            connection.execute("""INSERT INTO network_devices
                (id, hostname, device_type, management_ip, vendor, model, firmware, serial_number, location, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (device_id, values["hostname"], values["device_type"], values["management_ip"], values["vendor"], values["model"], values["firmware"], values["serial_number"], values["location"], values["status"], values["notes"]))
            return dict(connection.execute("SELECT * FROM network_devices WHERE id = ?", (device_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A network device with this hostname already exists") from exc


@router.put("/api/network/devices/{device_id}")
def update_network_device(device_id: str, payload: NetworkDeviceInput):
    values = _ni_validate_device_payload(payload)
    try:
        with get_connection() as connection:
            current = connection.execute("SELECT id FROM network_devices WHERE id = ?", (device_id,)).fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="Network device not found")
            connection.execute("""UPDATE network_devices SET hostname=?, device_type=?, management_ip=?, vendor=?, model=?, firmware=?, serial_number=?, location=?, status=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (values["hostname"], values["device_type"], values["management_ip"], values["vendor"], values["model"], values["firmware"], values["serial_number"], values["location"], values["status"], values["notes"], device_id))
            return dict(connection.execute("SELECT * FROM network_devices WHERE id = ?", (device_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A network device with this hostname already exists") from exc


@router.delete("/api/network/devices/{device_id}")
def delete_network_device(device_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_devices WHERE id = ?", (device_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Network device not found")
    return {"deleted": True, "id": device_id}


# NETWORK_DISCOVERY_ICMP_V1
def _ni_discovery_ping(address):
    """Try one ICMP echo request with a bounded timeout."""
    if sys.platform.startswith("win"):
        command = ["ping", "-n", "1", "-w", "1000", address]
    elif sys.platform == "darwin":
        command = ["ping", "-n", "-c", "1", "-W", "1000", address]
    else:
        command = ["ping", "-n", "-c", "1", "-W", "1", address]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # TCP discovery must continue even if ping is unavailable.
        return False


def _ni_run_discovery_job(job_id):
    with get_connection() as connection:
        job = connection.execute("SELECT cidr FROM network_discovery_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return
        cidr = job["cidr"]
        connection.execute("UPDATE network_discovery_jobs SET status='Running', started_at=CURRENT_TIMESTAMP, error='' WHERE id=?", (job_id,))
    try:
        network = ipaddress.ip_network(cidr, strict=False)
        addresses = list(network.hosts())
        def probe_host(address):
            ip = str(address)
            open_ports = []

            for port in NETWORK_DISCOVERY_PORTS:
                try:
                    with socket.create_connection((ip, port), timeout=0.25):
                        open_ports.append(port)
                except (OSError, TimeoutError):
                    pass

            icmp_ok = _ni_discovery_ping(ip)

            if not open_ports and not icmp_ok:
                return None

            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except (OSError, TimeoutError):
                hostname = ""

            methods = []
            if icmp_ok:
                methods.append("ICMP")
            if open_ports:
                methods.append("TCP")

            return {
                "ip": ip,
                "hostname": hostname,
                "open_ports": open_ports,
                "methods": methods,
                "status": "Reachable",
            }

        results = []
        with ThreadPoolExecutor(max_workers=32) as executor:
            futures = [executor.submit(probe_host, address) for address in addresses]
            for future in as_completed(futures):
                found = future.result()
                if found:
                    results.append(found)
        results.sort(key=lambda item: ipaddress.ip_address(item["ip"]))
        with get_connection() as connection:
            connection.execute("UPDATE network_discovery_jobs SET status='Completed', hosts_found=?, results_json=?, completed_at=CURRENT_TIMESTAMP, error='' WHERE id=?",
                (len(results), json.dumps(results), job_id))
    except Exception as exc:
        with get_connection() as connection:
            connection.execute("UPDATE network_discovery_jobs SET status='Failed', error=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (_ni_clean(str(exc), 500), job_id))


@router.post("/api/network/discovery/jobs", status_code=202)
def start_network_discovery(payload: NetworkDiscoveryInput, background_tasks: BackgroundTasks):
    if not payload.confirm_authorized:
        raise HTTPException(status_code=400, detail="Confirm that you are authorized to scan this network")
    network = _ni_parse_cidr(payload.cidr, ipv4_only=True)
    if not network.is_private or network.is_multicast or network.is_link_local or network.is_unspecified:
        raise HTTPException(status_code=422, detail="Discovery is limited to private IPv4 ranges")
    if network.num_addresses > 256:
        raise HTTPException(status_code=422, detail="The largest permitted discovery range is 256 IPv4 addresses (/24)")
    if network.network_address.is_loopback or network.broadcast_address.is_loopback:
        raise HTTPException(status_code=422, detail="Loopback ranges are not supported")
    cidr = str(network)
    job_id = _ni_id("discovery")
    with get_connection() as connection:
        connection.execute("INSERT INTO network_discovery_jobs (id, cidr, status) VALUES (?, ?, 'Pending')", (job_id, cidr))
    background_tasks.add_task(_ni_run_discovery_job, job_id)
    return {"id": job_id, "cidr": cidr, "status": "Pending", "message": "Discovery queued. Only common TCP ports are tested; silent hosts may not appear."}


@router.get("/api/network/discovery/jobs")
def list_network_discovery_jobs(limit: int = 100):
    limit = max(1, min(limit, 250))
    with get_connection() as connection:
        rows = connection.execute("SELECT id, cidr, status, hosts_found, error, started_at, completed_at, created_at FROM network_discovery_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return _ni_rows(rows)


@router.get("/api/network/discovery/jobs/{job_id}")
def get_network_discovery_job(job_id: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM network_discovery_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    result = dict(row)
    try:
        result["results"] = json.loads(result.pop("results_json") or "[]")
    except json.JSONDecodeError:
        result["results"] = []

    # Cross-reference discovered IPs against both Cartman inventories.
    with get_connection() as connection:
        for item in result["results"]:
            address = str(item.get("ip") or "")
            match = None

            if address:
                endpoint = connection.execute(
                    "SELECT id, name, status FROM devices WHERE ip = ? LIMIT 1",
                    (address,),
                ).fetchone()

                if endpoint:
                    match = {
                        "kind": "endpoint",
                        "id": endpoint["id"],
                        "name": endpoint["name"],
                        "status": endpoint["status"],
                    }
                else:
                    network_device = connection.execute(
                        """SELECT id, hostname, status
                           FROM network_devices
                           WHERE management_ip = ? LIMIT 1""",
                        (address,),
                    ).fetchone()

                    if network_device:
                        match = {
                            "kind": "network",
                            "id": network_device["id"],
                            "name": network_device["hostname"],
                            "status": network_device["status"],
                        }

            item["inventory_match"] = match

    return result


@router.post("/api/network/discovery/jobs/{job_id}/import")
def import_network_discovery_results(job_id: str, payload: NetworkDiscoveryImportInput):
    if not payload.addresses or len(payload.addresses) > 256:
        raise HTTPException(status_code=422, detail="Select between 1 and 256 discovered addresses")
    requested = {_ni_ip(address, "Discovered IP") for address in payload.addresses}
    imported, skipped, not_found = [], [], []
    with get_connection() as connection:
        job = connection.execute("SELECT status, results_json FROM network_discovery_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Discovery job not found")
        if job["status"] != "Completed":
            raise HTTPException(status_code=409, detail="Wait for the discovery job to complete before importing results")
        try:
            results = json.loads(job["results_json"] or "[]")
        except json.JSONDecodeError:
            results = []
        result_by_ip = {item.get("ip"): item for item in results if item.get("ip")}
        for address in sorted(requested, key=lambda item: ipaddress.ip_address(item)):
            found = result_by_ip.get(address)
            if not found:
                not_found.append(address)
                continue
            existing_ip = connection.execute(
                "SELECT id, hostname, status FROM network_devices WHERE management_ip=? LIMIT 1",
                (address,),
            ).fetchone()
            if existing_ip:
                skipped.append({
                    "ip": address,
                    "reason": "Already in Network Devices inventory",
                    "kind": "network",
                    "existing_id": existing_ip["id"],
                    "existing_name": existing_ip["hostname"],
                    "status": existing_ip["status"],
                })
                continue

            endpoint_match = connection.execute(
                "SELECT id, name, status FROM devices WHERE ip=? LIMIT 1",
                (address,),
            ).fetchone()
            if endpoint_match:
                skipped.append({
                    "ip": address,
                    "reason": "Already managed in Cartman endpoint inventory",
                    "kind": "endpoint",
                    "existing_id": endpoint_match["id"],
                    "existing_name": endpoint_match["name"],
                    "status": endpoint_match["status"],
                })
                continue
            candidate = _ni_clean(found.get("hostname"), 150) or "discovered-" + address.replace(".", "-")
            existing_name = connection.execute("SELECT id FROM network_devices WHERE hostname=? COLLATE NOCASE", (candidate,)).fetchone()
            if existing_name:
                candidate = "discovered-" + address.replace(".", "-")
                existing_name = connection.execute("SELECT id FROM network_devices WHERE hostname=? COLLATE NOCASE", (candidate,)).fetchone()
            if existing_name:
                skipped.append({"ip": address, "reason": "Hostname already exists in network inventory"})
                continue
            device_id = _ni_id("netdev")
            connection.execute("""INSERT INTO network_devices
                (id,hostname,device_type,management_ip,vendor,model,firmware,serial_number,location,status,notes,last_seen)
                VALUES (?,?, 'Unclassified', ?, '', '', '', '', '', 'Online', 'Imported from confirmed discovery result', CURRENT_TIMESTAMP)""",
                (device_id, candidate, address))
            imported.append({"id": device_id, "hostname": candidate, "management_ip": address, "status": "Online"})
    return {"job_id": job_id, "imported_count": len(imported), "skipped_count": len(skipped), "not_found": not_found, "imported": imported, "skipped": skipped}


@router.get("/api/network/topology/links")
def list_network_topology_links():
    with get_connection() as connection:
        rows = connection.execute("""SELECT l.*, s.hostname AS source_hostname, s.management_ip AS source_ip,
                t.hostname AS target_hostname, t.management_ip AS target_ip
            FROM network_topology_links l
            JOIN network_devices s ON s.id=l.source_device_id
            JOIN network_devices t ON t.id=l.target_device_id
            ORDER BY s.hostname COLLATE NOCASE, t.hostname COLLATE NOCASE""").fetchall()
        devices = connection.execute("SELECT id, hostname, management_ip, device_type, status FROM network_devices ORDER BY hostname COLLATE NOCASE").fetchall()
    return {"links": _ni_rows(rows), "devices": _ni_rows(devices)}


def _ni_validate_topology(payload):
    if payload.source_device_id == payload.target_device_id:
        raise HTTPException(status_code=422, detail="A topology link must connect two different devices")
    values = payload.dict()
    for field, limit in (("source_interface", 120), ("target_interface", 120), ("link_type", 50), ("status", 30), ("notes", 1000)):
        values[field] = _ni_clean(values.get(field), limit, field_name=field)
    if values["status"] not in {"Up", "Down", "Unknown", "Planned"}:
        raise HTTPException(status_code=422, detail="Link status must be Up, Down, Unknown, or Planned")
    with get_connection() as connection:
        for field in ("source_device_id", "target_device_id"):
            if not connection.execute("SELECT id FROM network_devices WHERE id=?", (values[field],)).fetchone():
                raise HTTPException(status_code=422, detail=f"{field} does not identify a network device")
    return values


@router.post("/api/network/topology/links", status_code=201)
def create_network_topology_link(payload: NetworkTopologyLinkInput):
    values = _ni_validate_topology(payload)
    link_id = _ni_id("netlink")
    try:
        with get_connection() as connection:
            connection.execute("INSERT INTO network_topology_links (id,source_device_id,target_device_id,source_interface,target_interface,link_type,status,notes) VALUES (?,?,?,?,?,?,?,?)",
                (link_id, values["source_device_id"], values["target_device_id"], values["source_interface"], values["target_interface"], values["link_type"], values["status"], values["notes"]))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This topology link already exists or references a missing device") from exc
    with get_connection() as connection:
        return dict(connection.execute("SELECT * FROM network_topology_links WHERE id=?", (link_id,)).fetchone())


@router.put("/api/network/topology/links/{link_id}")
def update_network_topology_link(link_id: str, payload: NetworkTopologyLinkInput):
    values = _ni_validate_topology(payload)
    try:
        with get_connection() as connection:
            if not connection.execute("SELECT id FROM network_topology_links WHERE id=?", (link_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Topology link not found")
            connection.execute("UPDATE network_topology_links SET source_device_id=?,target_device_id=?,source_interface=?,target_interface=?,link_type=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["source_device_id"], values["target_device_id"], values["source_interface"], values["target_interface"], values["link_type"], values["status"], values["notes"], link_id))
            return dict(connection.execute("SELECT * FROM network_topology_links WHERE id=?", (link_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This topology link already exists or references a missing device") from exc


@router.delete("/api/network/topology/links/{link_id}")
def delete_network_topology_link(link_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_topology_links WHERE id=?", (link_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Topology link not found")
    return {"deleted": True, "id": link_id}


def _ni_subnet_dict(row, connection=None):
    item = dict(row)
    try:
        item["dns_servers"] = json.loads(item.pop("dns_servers_json") or "[]")
    except json.JSONDecodeError:
        item["dns_servers"] = []
    if connection is not None:
        count = connection.execute("SELECT COUNT(*) FROM network_ip_addresses WHERE subnet_id=?", (item["id"],)).fetchone()[0]
        item["address_count"] = count
    return item


@router.get("/api/network/ipam")
def get_network_ipam():
    with get_connection() as connection:
        subnets = connection.execute("SELECT * FROM network_subnets ORDER BY name COLLATE NOCASE").fetchall()
        addresses = connection.execute("""SELECT a.*, s.name AS subnet_name, s.cidr AS subnet_cidr,
                nd.hostname AS device_hostname
            FROM network_ip_addresses a JOIN network_subnets s ON s.id=a.subnet_id
            LEFT JOIN network_devices nd ON nd.id=a.device_id
            ORDER BY a.address""").fetchall()
        subnet_items = [_ni_subnet_dict(row, connection) for row in subnets]
        devices = connection.execute("SELECT id, hostname, management_ip, device_type, status FROM network_devices ORDER BY hostname COLLATE NOCASE").fetchall()
    return {"subnets": subnet_items, "addresses": _ni_rows(addresses), "devices": _ni_rows(devices)}


@router.get("/api/network/ipam/subnets")
def list_network_subnets():
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM network_subnets ORDER BY name COLLATE NOCASE").fetchall()
        return [_ni_subnet_dict(row, connection) for row in rows]


def _ni_validate_subnet(payload):
    name = _ni_clean(payload.name, 150, True, "Subnet name")
    network = _ni_parse_cidr(payload.cidr)
    gateway = _ni_ip(payload.gateway, "Gateway", allow_blank=True)
    if gateway and ipaddress.ip_address(gateway) not in network:
        raise HTTPException(status_code=422, detail="Gateway must belong to this subnet")
    dns_servers = []
    for dns in payload.dns_servers:
        dns_servers.append(_ni_ip(dns, "DNS server"))
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in {"Active", "Planned", "Retired"}:
        raise HTTPException(status_code=422, detail="Subnet status must be Active, Planned, or Retired")
    return {"name": name, "cidr": str(network), "vlan": payload.vlan, "gateway": gateway, "dns_servers_json": json.dumps(dns_servers), "description": _ni_clean(payload.description, 1000), "status": status}


@router.post("/api/network/ipam/subnets", status_code=201)
def create_network_subnet(payload: NetworkSubnetInput):
    values = _ni_validate_subnet(payload)
    subnet_id = _ni_id("subnet")
    try:
        with get_connection() as connection:
            connection.execute("INSERT INTO network_subnets (id,name,cidr,vlan,gateway,dns_servers_json,description,status) VALUES (?,?,?,?,?,?,?,?)",
                (subnet_id, values["name"], values["cidr"], values["vlan"], values["gateway"], values["dns_servers_json"], values["description"], values["status"]))
            row = connection.execute("SELECT * FROM network_subnets WHERE id=?", (subnet_id,)).fetchone()
            return _ni_subnet_dict(row, connection)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Subnet name or CIDR already exists") from exc


@router.put("/api/network/ipam/subnets/{subnet_id}")
def update_network_subnet(subnet_id: str, payload: NetworkSubnetInput):
    values = _ni_validate_subnet(payload)
    try:
        with get_connection() as connection:
            if not connection.execute("SELECT id FROM network_subnets WHERE id=?", (subnet_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Subnet not found")
            connection.execute("UPDATE network_subnets SET name=?,cidr=?,vlan=?,gateway=?,dns_servers_json=?,description=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["name"], values["cidr"], values["vlan"], values["gateway"], values["dns_servers_json"], values["description"], values["status"], subnet_id))
            row = connection.execute("SELECT * FROM network_subnets WHERE id=?", (subnet_id,)).fetchone()
            return _ni_subnet_dict(row, connection)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Subnet name or CIDR already exists") from exc


@router.delete("/api/network/ipam/subnets/{subnet_id}")
def delete_network_subnet(subnet_id: str):
    with get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM network_ip_addresses WHERE subnet_id=?", (subnet_id,)).fetchone()[0]
        if count:
            raise HTTPException(status_code=409, detail="Remove the subnet's IP addresses before deleting it")
        cursor = connection.execute("DELETE FROM network_subnets WHERE id=?", (subnet_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Subnet not found")
    return {"deleted": True, "id": subnet_id}


@router.post("/api/network/ipam/addresses", status_code=201)
def create_network_ip_address(payload: NetworkIPAddressInput):
    address = _ni_ip(payload.address)
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in {"Available", "Assigned", "Reserved", "Excluded", "Conflict"}:
        raise HTTPException(status_code=422, detail="Invalid IP address status")
    assignment_type = _ni_clean(payload.assignment_type, 40, True, "Assignment type")
    if assignment_type not in {"Static", "DHCP", "Reservation", "Infrastructure", "Unknown"}:
        raise HTTPException(status_code=422, detail="Invalid assignment type")
    with get_connection() as connection:
        subnet_row = connection.execute("SELECT * FROM network_subnets WHERE id=?", (payload.subnet_id,)).fetchone()
        if not subnet_row:
            raise HTTPException(status_code=404, detail="Subnet not found")
        network = ipaddress.ip_network(subnet_row["cidr"], strict=False)
        ip_obj = ipaddress.ip_address(address)
        if ip_obj.version != network.version or ip_obj not in network:
            raise HTTPException(status_code=422, detail="IP address must belong to the selected subnet")
        device_id = _ni_clean(payload.device_id, 100)
        if device_id and not connection.execute("SELECT id FROM network_devices WHERE id=?", (device_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Linked network device not found")
        item_id = _ni_id("ipaddr")
        try:
            connection.execute("INSERT INTO network_ip_addresses (id,subnet_id,address,hostname,mac_address,device_id,assignment_type,status,notes) VALUES (?,?,?,?,?,?,?,?,?)",
                (item_id, payload.subnet_id, address, _ni_clean(payload.hostname, 150), _ni_clean(payload.mac_address, 40), device_id or None, assignment_type, status, _ni_clean(payload.notes, 1000)))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This IP address is already recorded") from exc
        return dict(connection.execute("SELECT * FROM network_ip_addresses WHERE id=?", (item_id,)).fetchone())


@router.put("/api/network/ipam/addresses/{address_id}")
def update_network_ip_address(address_id: str, payload: NetworkIPAddressInput):
    address = _ni_ip(payload.address)
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in {"Available", "Assigned", "Reserved", "Excluded", "Conflict"}:
        raise HTTPException(status_code=422, detail="Invalid IP address status")
    assignment_type = _ni_clean(payload.assignment_type, 40, True, "Assignment type")
    if assignment_type not in {"Static", "DHCP", "Reservation", "Infrastructure", "Unknown"}:
        raise HTTPException(status_code=422, detail="Invalid assignment type")
    with get_connection() as connection:
        if not connection.execute("SELECT id FROM network_ip_addresses WHERE id=?", (address_id,)).fetchone():
            raise HTTPException(status_code=404, detail="IP address record not found")
        subnet_row = connection.execute("SELECT * FROM network_subnets WHERE id=?", (payload.subnet_id,)).fetchone()
        if not subnet_row:
            raise HTTPException(status_code=404, detail="Subnet not found")
        network = ipaddress.ip_network(subnet_row["cidr"], strict=False)
        ip_obj = ipaddress.ip_address(address)
        if ip_obj.version != network.version or ip_obj not in network:
            raise HTTPException(status_code=422, detail="IP address must belong to the selected subnet")
        device_id = _ni_clean(payload.device_id, 100)
        if device_id and not connection.execute("SELECT id FROM network_devices WHERE id=?", (device_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Linked network device not found")
        try:
            connection.execute("UPDATE network_ip_addresses SET subnet_id=?,address=?,hostname=?,mac_address=?,device_id=?,assignment_type=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (payload.subnet_id, address, _ni_clean(payload.hostname, 150), _ni_clean(payload.mac_address, 40), device_id or None, assignment_type, status, _ni_clean(payload.notes, 1000), address_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This IP address is already recorded") from exc
        return dict(connection.execute("SELECT * FROM network_ip_addresses WHERE id=?", (address_id,)).fetchone())


@router.delete("/api/network/ipam/addresses/{address_id}")
def delete_network_ip_address(address_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_ip_addresses WHERE id=?", (address_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="IP address record not found")
    return {"deleted": True, "id": address_id}


def _ni_validate_dns(payload):
    zone = _ni_clean(payload.zone, 253, True, "DNS zone").rstrip(".").lower()
    name = _ni_clean(payload.name, 253, True, "Record name").rstrip(".")
    record_type = _ni_clean(payload.record_type, 10, True, "Record type").upper()
    value = _ni_clean(payload.value, 1000, True, "Record value")
    if record_type not in {"A", "AAAA", "CNAME", "MX", "TXT", "PTR", "NS", "SRV"}:
        raise HTTPException(status_code=422, detail="Unsupported DNS record type")
    if record_type == "A":
        value = _ni_ip(value, "A record value")
        if ipaddress.ip_address(value).version != 4:
            raise HTTPException(status_code=422, detail="A records require an IPv4 address")
    elif record_type == "AAAA":
        value = _ni_ip(value, "AAAA record value")
        if ipaddress.ip_address(value).version != 6:
            raise HTTPException(status_code=422, detail="AAAA records require an IPv6 address")
    if record_type in {"CNAME", "PTR", "NS"} and any(ch.isspace() for ch in value):
        raise HTTPException(status_code=422, detail="This DNS record value must not contain spaces")
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in {"Active", "Disabled"}:
        raise HTTPException(status_code=422, detail="DNS record status must be Active or Disabled")
    return {"zone": zone, "name": name, "record_type": record_type, "value": value, "ttl": payload.ttl, "status": status, "notes": _ni_clean(payload.notes, 1000)}


@router.get("/api/network/dns/records")
def list_network_dns_records(limit: int = 500):
    limit = max(1, min(limit, 1000))
    with get_connection() as connection:
        return _ni_rows(connection.execute("SELECT * FROM network_dns_records ORDER BY zone COLLATE NOCASE, name COLLATE NOCASE LIMIT ?", (limit,)).fetchall())


@router.post("/api/network/dns/records", status_code=201)
def create_network_dns_record(payload: NetworkDNSRecordInput):
    values = _ni_validate_dns(payload)
    item_id = _ni_id("dns")
    try:
        with get_connection() as connection:
            connection.execute("INSERT INTO network_dns_records (id,zone,name,record_type,value,ttl,status,notes) VALUES (?,?,?,?,?,?,?,?)",
                (item_id, values["zone"], values["name"], values["record_type"], values["value"], values["ttl"], values["status"], values["notes"]))
            return dict(connection.execute("SELECT * FROM network_dns_records WHERE id=?", (item_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This DNS record already exists") from exc


@router.put("/api/network/dns/records/{record_id}")
def update_network_dns_record(record_id: str, payload: NetworkDNSRecordInput):
    values = _ni_validate_dns(payload)
    try:
        with get_connection() as connection:
            if not connection.execute("SELECT id FROM network_dns_records WHERE id=?", (record_id,)).fetchone():
                raise HTTPException(status_code=404, detail="DNS record not found")
            connection.execute("UPDATE network_dns_records SET zone=?,name=?,record_type=?,value=?,ttl=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["zone"], values["name"], values["record_type"], values["value"], values["ttl"], values["status"], values["notes"], record_id))
            return dict(connection.execute("SELECT * FROM network_dns_records WHERE id=?", (record_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This DNS record already exists") from exc


@router.delete("/api/network/dns/records/{record_id}")
def delete_network_dns_record(record_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_dns_records WHERE id=?", (record_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="DNS record not found")
    return {"deleted": True, "id": record_id}


def _ni_validate_dhcp_scope(payload):
    name = _ni_clean(payload.name, 150, True, "Scope name")
    network = _ni_parse_cidr(payload.cidr, ipv4_only=True)
    start_ip = _ni_ip(payload.start_ip, "Range start")
    end_ip = _ni_ip(payload.end_ip, "Range end")
    start_obj, end_obj = ipaddress.ip_address(start_ip), ipaddress.ip_address(end_ip)
    if start_obj.version != 4 or end_obj.version != 4 or start_obj not in network or end_obj not in network or int(start_obj) > int(end_obj):
        raise HTTPException(status_code=422, detail="DHCP range must be an ordered IPv4 range inside the scope CIDR")
    if start_obj in {network.network_address, network.broadcast_address} or end_obj in {network.network_address, network.broadcast_address}:
        raise HTTPException(status_code=422, detail="DHCP range cannot include the network or broadcast address")
    gateway = _ni_ip(payload.gateway, "Gateway", allow_blank=True)
    if gateway and (ipaddress.ip_address(gateway).version != 4 or ipaddress.ip_address(gateway) not in network):
        raise HTTPException(status_code=422, detail="Gateway must be an IPv4 address inside the DHCP scope")
    dns_servers = [_ni_ip(item, "DNS server") for item in payload.dns_servers]
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in {"Active", "Disabled", "Planned"}:
        raise HTTPException(status_code=422, detail="DHCP status must be Active, Disabled, or Planned")
    return {"name": name, "cidr": str(network), "start_ip": start_ip, "end_ip": end_ip, "gateway": gateway, "dns_servers_json": json.dumps(dns_servers), "lease_duration": payload.lease_duration, "status": status, "notes": _ni_clean(payload.notes, 1000)}


@router.get("/api/network/dhcp/scopes")
def list_network_dhcp_scopes():
    with get_connection() as connection:
        rows = connection.execute("""SELECT s.*, COUNT(l.id) AS lease_count
            FROM network_dhcp_scopes s LEFT JOIN network_dhcp_leases l ON l.scope_id=s.id
            GROUP BY s.id ORDER BY s.name COLLATE NOCASE""").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["dns_servers"] = json.loads(item.pop("dns_servers_json") or "[]")
        except json.JSONDecodeError:
            item["dns_servers"] = []
        result.append(item)
    return result


@router.post("/api/network/dhcp/scopes", status_code=201)
def create_network_dhcp_scope(payload: NetworkDHCPScopeInput):
    values = _ni_validate_dhcp_scope(payload)
    scope_id = _ni_id("dhcpscope")
    try:
        with get_connection() as connection:
            connection.execute("INSERT INTO network_dhcp_scopes (id,name,cidr,start_ip,end_ip,gateway,dns_servers_json,lease_duration,status,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (scope_id, values["name"], values["cidr"], values["start_ip"], values["end_ip"], values["gateway"], values["dns_servers_json"], values["lease_duration"], values["status"], values["notes"]))
            return dict(connection.execute("SELECT * FROM network_dhcp_scopes WHERE id=?", (scope_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A DHCP scope with this name already exists") from exc


@router.put("/api/network/dhcp/scopes/{scope_id}")
def update_network_dhcp_scope(scope_id: str, payload: NetworkDHCPScopeInput):
    values = _ni_validate_dhcp_scope(payload)
    try:
        with get_connection() as connection:
            if not connection.execute("SELECT id FROM network_dhcp_scopes WHERE id=?", (scope_id,)).fetchone():
                raise HTTPException(status_code=404, detail="DHCP scope not found")
            connection.execute("UPDATE network_dhcp_scopes SET name=?,cidr=?,start_ip=?,end_ip=?,gateway=?,dns_servers_json=?,lease_duration=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["name"], values["cidr"], values["start_ip"], values["end_ip"], values["gateway"], values["dns_servers_json"], values["lease_duration"], values["status"], values["notes"], scope_id))
            return dict(connection.execute("SELECT * FROM network_dhcp_scopes WHERE id=?", (scope_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A DHCP scope with this name already exists") from exc


@router.delete("/api/network/dhcp/scopes/{scope_id}")
def delete_network_dhcp_scope(scope_id: str):
    with get_connection() as connection:
        lease_count = connection.execute("SELECT COUNT(*) FROM network_dhcp_leases WHERE scope_id=?", (scope_id,)).fetchone()[0]
        if lease_count:
            raise HTTPException(status_code=409, detail="Remove DHCP leases before deleting this scope")
        cursor = connection.execute("DELETE FROM network_dhcp_scopes WHERE id=?", (scope_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="DHCP scope not found")
    return {"deleted": True, "id": scope_id}


@router.get("/api/network/dhcp/leases")
def list_network_dhcp_leases(scope_id: Optional[str] = None, limit: int = 500):
    limit = max(1, min(limit, 1000))
    sql = "SELECT l.*, s.name AS scope_name, s.cidr AS scope_cidr FROM network_dhcp_leases l JOIN network_dhcp_scopes s ON s.id=l.scope_id"
    params = []
    if scope_id:
        sql += " WHERE l.scope_id=?"
        params.append(scope_id)
    sql += " ORDER BY l.updated_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        return _ni_rows(connection.execute(sql, params).fetchall())


@router.post("/api/network/dhcp/leases", status_code=201)
def create_network_dhcp_lease(payload: NetworkDHCPLeaseInput):
    address = _ni_ip(payload.address, "Lease IP")
    status = _ni_clean(payload.status, 30, True, "Status")
    if status not in {"Active", "Reserved", "Expired", "Declined"}:
        raise HTTPException(status_code=422, detail="Invalid lease status")
    with get_connection() as connection:
        scope = connection.execute("SELECT * FROM network_dhcp_scopes WHERE id=?", (payload.scope_id,)).fetchone()
        if not scope:
            raise HTTPException(status_code=404, detail="DHCP scope not found")
        address_obj = ipaddress.ip_address(address)
        start_obj, end_obj = ipaddress.ip_address(scope["start_ip"]), ipaddress.ip_address(scope["end_ip"])
        if address_obj.version != 4 or int(address_obj) < int(start_obj) or int(address_obj) > int(end_obj):
            raise HTTPException(status_code=422, detail="Lease address must be inside the configured DHCP range")
        lease_id = _ni_id("lease")
        try:
            connection.execute("INSERT INTO network_dhcp_leases (id,scope_id,address,mac_address,hostname,expires_at,status) VALUES (?,?,?,?,?,?,?)",
                (lease_id, payload.scope_id, address, _ni_clean(payload.mac_address, 40), _ni_clean(payload.hostname, 150), _ni_clean(payload.expires_at, 80), status))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This address already has a lease in the selected scope") from exc
        return dict(connection.execute("SELECT * FROM network_dhcp_leases WHERE id=?", (lease_id,)).fetchone())


@router.delete("/api/network/dhcp/leases/{lease_id}")
def delete_network_dhcp_lease(lease_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_dhcp_leases WHERE id=?", (lease_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="DHCP lease not found")
    return {"deleted": True, "id": lease_id}


@router.get("/api/network/diagnostics/history")
def list_network_diagnostics(limit: int = 100):
    limit = max(1, min(limit, 250))
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM network_diagnostic_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["resolved_addresses"] = json.loads(item.pop("resolved_addresses_json") or "[]")
        except json.JSONDecodeError:
            item["resolved_addresses"] = []
        result.append(item)
    return result


@router.post("/api/network/diagnostics/run", status_code=201)
def run_network_diagnostic(payload: NetworkDiagnosticInput):
    target = _ni_clean(payload.target, 253, True, "Target")
    # Prevent command-line and URL payloads; diagnostics use stdlib sockets only.
    if any(ch.isspace() for ch in target) or any(ch in target for ch in "/\\?#@"):
        raise HTTPException(status_code=422, detail="Target must be a hostname or IP address")
    test_type = _ni_clean(payload.test_type, 20, True, "Test type").lower()
    if test_type not in {"dns", "tcp"}:
        raise HTTPException(status_code=422, detail="Supported diagnostics are DNS resolution and a single TCP connection test")
    if test_type == "tcp" and payload.port is None:
        raise HTTPException(status_code=422, detail="A TCP test requires a port")
    resolved = []
    response_ms = None
    started = time.perf_counter()
    status = "Succeeded"
    message = ""
    try:
        if test_type == "dns":
            infos = socket.getaddrinfo(target, None, type=socket.SOCK_STREAM)
            resolved = sorted({info[4][0] for info in infos})
            if not resolved:
                raise socket.gaierror("No addresses returned")
            message = f"Resolved to {len(resolved)} address(es)"
        else:
            with socket.create_connection((target, payload.port), timeout=2.0):
                pass
            # Include resolver output where available, but the TCP result is authoritative.
            try:
                resolved = sorted({info[4][0] for info in socket.getaddrinfo(target, payload.port, type=socket.SOCK_STREAM)})
            except OSError:
                resolved = []
            message = f"TCP connection to port {payload.port} succeeded"
    except (OSError, TimeoutError) as exc:
        status = "Failed"
        message = _ni_clean(str(exc) or exc.__class__.__name__, 300)
    response_ms = round((time.perf_counter() - started) * 1000, 2)
    run_id = _ni_id("diag")
    with get_connection() as connection:
        connection.execute("INSERT INTO network_diagnostic_runs (id,target,test_type,port,status,resolved_addresses_json,response_ms,result_message) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, target, test_type.upper(), payload.port if test_type == "tcp" else None, status, json.dumps(resolved), response_ms, message))
        row = connection.execute("SELECT * FROM network_diagnostic_runs WHERE id=?", (run_id,)).fetchone()
    result = dict(row)
    result["resolved_addresses"] = json.loads(result.pop("resolved_addresses_json") or "[]")
    return result


@router.get("/api/network/servers")
def list_network_servers():
    with get_connection() as connection:
        rows = connection.execute("""SELECT p.id AS profile_id, d.id AS device_id, d.name, d.os, d.ip,
                d.status, d.device_type, d.cpu, d.ram, d.disk, d.manufacturer, d.model,
                p.server_role, p.environment, p.criticality, p.location, p.notes,
                p.created_at AS profile_created_at, p.updated_at AS profile_updated_at
            FROM network_server_profiles p JOIN devices d ON d.id=p.device_id
            ORDER BY d.name COLLATE NOCASE""").fetchall()
        candidate_rows = connection.execute("SELECT id,name,os,ip,status,device_type,cpu,ram,disk FROM devices ORDER BY name COLLATE NOCASE").fetchall()
        dependencies = connection.execute("""SELECT dep.*, s.name AS source_name, t.name AS target_name
            FROM network_server_dependencies dep JOIN devices s ON s.id=dep.source_device_id
            JOIN devices t ON t.id=dep.target_device_id ORDER BY s.name COLLATE NOCASE""").fetchall()
    server_items = _ni_rows(rows)
    candidate_items = _ni_rows(candidate_rows)

    # Use the same live CartmanClient connection state as /api/devices.
    live_connections = (
        get_live_device_connections()
        if callable(get_live_device_connections)
        else {}
    )

    for item in server_items:
        live = live_connections.get(str(item.get("device_id") or ""))
        item["status"] = "Online" if live else "Offline"
        item["connection_status"] = item["status"]
        item["connection_state"] = (
            (live.get("state") or "Connected")
            if live else "Disconnected"
        )
        item["last_seen"] = (
            (live.get("last_seen") or None) if live else None
        )

    for item in candidate_items:
        live = live_connections.get(str(item.get("id") or ""))
        item["status"] = "Online" if live else "Offline"
        item["connection_status"] = item["status"]
        item["connection_state"] = (
            (live.get("state") or "Connected")
            if live else "Disconnected"
        )
        item["last_seen"] = (
            (live.get("last_seen") or None) if live else None
        )

    return {
        "servers": server_items,
        "candidates": candidate_items,
        "dependencies": _ni_rows(dependencies),
    }


@router.post("/api/network/servers", status_code=201)
def create_network_server_profile(payload: NetworkServerProfileInput):
    values = payload.dict()
    for field, limit in (("server_role", 100), ("environment", 80), ("criticality", 30), ("location", 180), ("notes", 1000)):
        values[field] = _ni_clean(values.get(field), limit, required=(field in {"server_role", "environment", "criticality"}), field_name=field)
    if values["criticality"] not in {"Low", "Medium", "High", "Critical"}:
        raise HTTPException(status_code=422, detail="Criticality must be Low, Medium, High, or Critical")
    with get_connection() as connection:
        if not _ni_server_exists(connection, values["device_id"]):
            raise HTTPException(status_code=404, detail="Select an existing Cartman device first")
        profile_id = _ni_id("serverprofile")
        try:
            connection.execute("INSERT INTO network_server_profiles (id,device_id,server_role,environment,criticality,location,notes) VALUES (?,?,?,?,?,?,?)",
                (profile_id, values["device_id"], values["server_role"], values["environment"], values["criticality"], values["location"], values["notes"]))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This device already has a server profile") from exc
        return dict(connection.execute("SELECT * FROM network_server_profiles WHERE id=?", (profile_id,)).fetchone())


@router.put("/api/network/servers/{profile_id}")
def update_network_server_profile(profile_id: str, payload: NetworkServerProfileInput):
    values = payload.dict()
    for field, limit in (("server_role", 100), ("environment", 80), ("criticality", 30), ("location", 180), ("notes", 1000)):
        values[field] = _ni_clean(values.get(field), limit, required=(field in {"server_role", "environment", "criticality"}), field_name=field)
    if values["criticality"] not in {"Low", "Medium", "High", "Critical"}:
        raise HTTPException(status_code=422, detail="Criticality must be Low, Medium, High, or Critical")
    with get_connection() as connection:
        if not connection.execute("SELECT id FROM network_server_profiles WHERE id=?", (profile_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Server profile not found")
        if not _ni_server_exists(connection, values["device_id"]):
            raise HTTPException(status_code=404, detail="Select an existing Cartman device first")
        try:
            connection.execute("UPDATE network_server_profiles SET device_id=?,server_role=?,environment=?,criticality=?,location=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["device_id"], values["server_role"], values["environment"], values["criticality"], values["location"], values["notes"], profile_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This device already has a server profile") from exc
        return dict(connection.execute("SELECT * FROM network_server_profiles WHERE id=?", (profile_id,)).fetchone())


@router.delete("/api/network/servers/{profile_id}")
def delete_network_server_profile(profile_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_server_profiles WHERE id=?", (profile_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Server profile not found")
    return {"deleted": True, "id": profile_id, "device_deleted": False}


@router.post("/api/network/servers/dependencies", status_code=201)
def create_network_server_dependency(payload: NetworkServerDependencyInput):
    if payload.source_device_id == payload.target_device_id:
        raise HTTPException(status_code=422, detail="A server cannot depend on itself")
    values = payload.dict()
    values["relationship"] = _ni_clean(values["relationship"], 100, True, "Relationship")
    values["notes"] = _ni_clean(values["notes"], 1000)
    with get_connection() as connection:
        for field in ("source_device_id", "target_device_id"):
            if not _ni_server_exists(connection, values[field]):
                raise HTTPException(status_code=404, detail=f"{field} does not identify an existing Cartman device")
        item_id = _ni_id("dependency")
        try:
            connection.execute("INSERT INTO network_server_dependencies (id,source_device_id,target_device_id,relationship,notes) VALUES (?,?,?,?,?)",
                (item_id, values["source_device_id"], values["target_device_id"], values["relationship"], values["notes"]))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This dependency already exists") from exc
        return dict(connection.execute("SELECT * FROM network_server_dependencies WHERE id=?", (item_id,)).fetchone())


@router.delete("/api/network/servers/dependencies/{dependency_id}")
def delete_network_server_dependency(dependency_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_server_dependencies WHERE id=?", (dependency_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Dependency not found")
    return {"deleted": True, "id": dependency_id}


@router.get("/api/network/capacity")
def get_network_capacity(limit: int = 300):
    limit = max(1, min(limit, 1000))
    with get_connection() as connection:
        manual = connection.execute("""SELECT c.id, c.device_id, d.name AS device_name, c.metric_name,
                c.value, c.unit, c.source, c.notes, c.recorded_at AS collected_at
            FROM network_capacity_records c LEFT JOIN devices d ON d.id=c.device_id
            ORDER BY c.recorded_at DESC LIMIT ?""", (limit,)).fetchall()
        telemetry = connection.execute("""SELECT m.id, m.device_id, d.name AS device_name,
                m.metric_name, m.value, m.unit, m.source, '' AS notes, m.collected_at
            FROM monitoring_metrics m LEFT JOIN devices d ON d.id=m.device_id
            ORDER BY m.collected_at DESC LIMIT ?""", (limit,)).fetchall()
        manual_total = connection.execute("SELECT COUNT(*) FROM network_capacity_records").fetchone()[0]
        telemetry_total = connection.execute("SELECT COUNT(*) FROM monitoring_metrics").fetchone()[0]
        plans = connection.execute("SELECT * FROM network_capacity_plans ORDER BY target_date, created_at DESC").fetchall()
    items = [dict(row) for row in manual] + [dict(row) for row in telemetry]
    items.sort(key=lambda item: item.get("collected_at") or "", reverse=True)
    return {"records": items[:limit], "record_count": manual_total + telemetry_total, "telemetry_count": telemetry_total, "manual_count": manual_total, "plans": _ni_rows(plans), "telemetry_available": telemetry_total > 0}


@router.post("/api/network/capacity/records", status_code=201)
def create_network_capacity_record(payload: NetworkCapacityRecordInput):
    metric_name = _ni_clean(payload.metric_name, 50, True, "Metric name").lower()
    if metric_name not in NETWORK_CAPACITY_METRICS:
        raise HTTPException(status_code=422, detail="Unsupported metric. Use cpu_percent, memory_percent, disk_percent, network_mbps, cpu_cores, memory_gb, or storage_gb")
    value = float(payload.value)
    if value < 0 or value != value or value in (float("inf"), float("-inf")):
        raise HTTPException(status_code=422, detail="Metric value must be a finite non-negative number")
    if metric_name.endswith("_percent") and value > 100:
        raise HTTPException(status_code=422, detail="Percentage metrics must be between 0 and 100")
    device_id = _ni_clean(payload.device_id, 100)
    with get_connection() as connection:
        if device_id and not _ni_server_exists(connection, device_id):
            raise HTTPException(status_code=404, detail="Cartman device not found")
        record_id = _ni_id("capacity")
        unit = _ni_clean(payload.unit, 20) or NETWORK_CAPACITY_METRICS[metric_name]
        connection.execute("INSERT INTO network_capacity_records (id,device_id,metric_name,value,unit,source,notes) VALUES (?,?,?,?,?,'manual-entry',?)",
            (record_id, device_id or None, metric_name, value, unit, _ni_clean(payload.notes, 500)))
        return dict(connection.execute("SELECT * FROM network_capacity_records WHERE id=?", (record_id,)).fetchone())


@router.get("/api/network/capacity/plans")
def list_network_capacity_plans():
    with get_connection() as connection:
        return _ni_rows(connection.execute("SELECT * FROM network_capacity_plans ORDER BY target_date, created_at DESC").fetchall())


@router.post("/api/network/capacity/plans", status_code=201)
def create_network_capacity_plan(payload: NetworkCapacityPlanInput):
    values = payload.dict()
    for field, limit in (("title", 180), ("resource_type", 50), ("unit", 20), ("target_date", 40), ("owner", 120), ("status", 30), ("notes", 1000)):
        values[field] = _ni_clean(values.get(field), limit, required=(field in {"title", "resource_type"}), field_name=field)
    if values["status"] not in {"Planned", "In progress", "Completed", "On hold"}:
        raise HTTPException(status_code=422, detail="Invalid capacity plan status")
    plan_id = _ni_id("capacityplan")
    with get_connection() as connection:
        connection.execute("INSERT INTO network_capacity_plans (id,title,resource_type,current_value,target_value,unit,target_date,owner,status,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (plan_id, values["title"], values["resource_type"], values["current_value"], values["target_value"], values["unit"], values["target_date"], values["owner"], values["status"], values["notes"]))
        return dict(connection.execute("SELECT * FROM network_capacity_plans WHERE id=?", (plan_id,)).fetchone())


@router.put("/api/network/capacity/plans/{plan_id}")
def update_network_capacity_plan(plan_id: str, payload: NetworkCapacityPlanInput):
    values = payload.dict()
    for field, limit in (("title", 180), ("resource_type", 50), ("unit", 20), ("target_date", 40), ("owner", 120), ("status", 30), ("notes", 1000)):
        values[field] = _ni_clean(values.get(field), limit, required=(field in {"title", "resource_type"}), field_name=field)
    if values["status"] not in {"Planned", "In progress", "Completed", "On hold"}:
        raise HTTPException(status_code=422, detail="Invalid capacity plan status")
    with get_connection() as connection:
        if not connection.execute("SELECT id FROM network_capacity_plans WHERE id=?", (plan_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Capacity plan not found")
        connection.execute("UPDATE network_capacity_plans SET title=?,resource_type=?,current_value=?,target_value=?,unit=?,target_date=?,owner=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (values["title"], values["resource_type"], values["current_value"], values["target_value"], values["unit"], values["target_date"], values["owner"], values["status"], values["notes"], plan_id))
        return dict(connection.execute("SELECT * FROM network_capacity_plans WHERE id=?", (plan_id,)).fetchone())


@router.delete("/api/network/capacity/plans/{plan_id}")
def delete_network_capacity_plan(plan_id: str):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM network_capacity_plans WHERE id=?", (plan_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Capacity plan not found")
    return {"deleted": True, "id": plan_id}

