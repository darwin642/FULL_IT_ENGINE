"""Cartman Remote Access profile, session-contract, and audit APIs.

This build ships the API contract and profile management only.
A real connection engine must be injected before any remote session starts.
No password or private-key contents are persisted.
"""
from pathlib import Path
from typing import Optional
import re
import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, SecretStr, field_validator

DATABASE = Path(__file__).resolve().parent / "cartman.db"
router = APIRouter(prefix="/api/remote-access", tags=["Remote Access"])

PROFILE_PROTOCOLS = {"rdp", "vnc", "screen_sharing"}
LIST_PROTOCOLS = PROFILE_PROTOCOLS | {"ssh"}
DEFAULT_PORTS = {"ssh": 22, "rdp": 3389, "vnc": 5900, "screen_sharing": 5900}
AUTH_METHODS = {"password", "system"}


class RemoteAccessProfileInput(BaseModel):
    protocol: str
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=253)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: str = Field(default="", max_length=128)
    auth_method: str = Field(default="password")
    description: str = Field(default="", max_length=500)
    enabled: bool = True

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value):
        if value not in PROFILE_PROTOCOLS:
            raise ValueError("protocol must be rdp, vnc, or screen_sharing.")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Profile name cannot be empty.")
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("Control characters are not allowed.")
        return value

    @field_validator("host")
    @classmethod
    def validate_host(cls, value):
        value = value.strip()
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("Enter a hostname or IP address, not a URL.")
        if "://" in value or "/" in value or "@" in value:
            raise ValueError("Enter a hostname or IP address, not a URL.")
        if not re.fullmatch(r"[A-Za-z0-9._:%-]+", value):
            raise ValueError("Hostname contains unsupported characters.")
        return value

    @field_validator("username", "description")
    @classmethod
    def trim_optional(cls, value):
        value = value.strip()
        if any(ord(ch) < 32 and ch != "\t" for ch in value):
            raise ValueError("Control characters are not allowed.")
        return value

    @field_validator("auth_method")
    @classmethod
    def validate_auth_method(cls, value):
        if value not in AUTH_METHODS:
            raise ValueError("auth_method must be password or system.")
        return value


class StartSessionInput(BaseModel):
    protocol: str
    profile_id: str = Field(min_length=1, max_length=100)
    username_override: str = Field(default="", max_length=128)
    credential_ref: Optional[str] = Field(default=None, max_length=256)
    # Transient input for a future engine adapter. Never persisted or audited.
    password: Optional[SecretStr] = None

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value):
        if value not in LIST_PROTOCOLS:
            raise ValueError("Unsupported connection protocol.")
        return value

    @field_validator("username_override")
    @classmethod
    def validate_username_override(cls, value):
        value = value.strip()
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("Control characters are not allowed.")
        return value


def _connect():
    connection = sqlite3.connect(str(DATABASE), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize_schema():
    connection = _connect()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS remote_access_profiles (
                id TEXT PRIMARY KEY,
                protocol TEXT NOT NULL
                    CHECK (protocol IN ('rdp', 'vnc', 'screen_sharing')),
                name TEXT NOT NULL COLLATE NOCASE,
                host TEXT NOT NULL,
                port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
                username TEXT NOT NULL DEFAULT '',
                auth_method TEXT NOT NULL
                    CHECK (auth_method IN ('password', 'system')),
                description TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (protocol, name)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS remote_access_sessions (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                protocol TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                host TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                error_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS remote_access_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                protocol TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.commit()
    finally:
        connection.close()


def _require_admin(request: Request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if not isinstance(user, dict) or user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Remote Access management requires an administrator.",
        )


def _actor(request: Request):
    user = getattr(request.state, "auth_user", None) or {}
    if not isinstance(user, dict):
        return "admin"
    return str(
        user.get("username") or user.get("email") or user.get("id") or "admin"
    )[:128]


def _audit(connection, request, action, protocol, profile_id, profile_name):
    connection.execute("""
        INSERT INTO remote_access_audit
            (actor, action, protocol, profile_id, profile_name)
        VALUES (?, ?, ?, ?, ?)
    """, (_actor(request), action, protocol, profile_id, profile_name))


def _serialize_profile(row):
    return {
        "id": row["id"],
        "protocol": row["protocol"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "auth_method": row["auth_method"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _lookup_profile(connection, protocol, profile_id):
    if protocol == "ssh":
        row = connection.execute(
            "SELECT * FROM ssh_connection_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if row:
            item = dict(row)
            item["protocol"] = "ssh"
            item["enabled"] = bool(item["enabled"])
            return item
        return None

    row = connection.execute(
        "SELECT * FROM remote_access_profiles WHERE id = ? AND protocol = ?",
        (profile_id, protocol),
    ).fetchone()
    return dict(row) if row else None


def _engine_adapter():
    """Return the future engine adapter.

    Replace None with the engine implementation in the engine build.
    The API shape and profile records are already established.
    """
    return None


@router.get("/capabilities")
def remote_access_capabilities(request: Request):
    _require_admin(request)
    return {
        "connection_engine_available": _engine_adapter() is not None,
        "client_agent_available": False,
        "credential_storage_available": False,
        "items": [
            {"protocol": "ssh", "label": "SSH", "profile_api_available": True},
            {"protocol": "rdp", "label": "Windows Remote Desktop", "profile_api_available": True},
            {"protocol": "vnc", "label": "VNC / RFB", "profile_api_available": True},
            {"protocol": "screen_sharing", "label": "macOS Screen Sharing", "profile_api_available": True},
        ],
    }


@router.get("/profiles")
def list_profiles(
    request: Request,
    protocol: Optional[str] = Query(default=None),
):
    _require_admin(request)
    if protocol is not None and protocol not in LIST_PROTOCOLS:
        raise HTTPException(status_code=422, detail="Unsupported protocol.")

    connection = _connect()
    try:
        if protocol == "ssh":
            rows = connection.execute("""
                SELECT * FROM ssh_connection_profiles
                ORDER BY name COLLATE NOCASE
            """).fetchall()
            return {"items": [{
                "id": row["id"], "protocol": "ssh", "name": row["name"],
                "host": row["host"], "port": row["port"], "username": row["username"],
                "auth_method": row["auth_method"], "description": row["description"],
                "enabled": bool(row["enabled"]), "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            } for row in rows]}

        if protocol:
            rows = connection.execute("""
                SELECT * FROM remote_access_profiles
                WHERE protocol = ? ORDER BY name COLLATE NOCASE
            """, (protocol,)).fetchall()
        else:
            rows = connection.execute("""
                SELECT * FROM remote_access_profiles
                ORDER BY protocol, name COLLATE NOCASE
            """).fetchall()
        items = [_serialize_profile(row) for row in rows]

        if protocol is None:
            ssh_rows = connection.execute("""
                SELECT * FROM ssh_connection_profiles
                ORDER BY name COLLATE NOCASE
            """).fetchall()
            items.extend({
                "id": row["id"], "protocol": "ssh", "name": row["name"],
                "host": row["host"], "port": row["port"], "username": row["username"],
                "auth_method": row["auth_method"], "description": row["description"],
                "enabled": bool(row["enabled"]), "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            } for row in ssh_rows)

        return {"items": items}
    finally:
        connection.close()


@router.post("/profiles", status_code=201)
def create_profile(payload: RemoteAccessProfileInput, request: Request):
    _require_admin(request)
    profile_id = str(uuid.uuid4())
    port = payload.port or DEFAULT_PORTS[payload.protocol]
    connection = _connect()
    try:
        connection.execute("""
            INSERT INTO remote_access_profiles
                (id, protocol, name, host, port, username,
                 auth_method, description, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id, payload.protocol, payload.name, payload.host, port,
            payload.username, payload.auth_method, payload.description,
            int(payload.enabled),
        ))
        _audit(connection, request, "profile.created", payload.protocol, profile_id, payload.name)
        connection.commit()
        row = connection.execute(
            "SELECT * FROM remote_access_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return _serialize_profile(row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="A profile with that name already exists for this protocol.",
        ) from exc
    finally:
        connection.close()


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, payload: RemoteAccessProfileInput, request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        existing = connection.execute(
            "SELECT * FROM remote_access_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Remote Access profile not found.")

        port = payload.port or DEFAULT_PORTS[payload.protocol]
        connection.execute("""
            UPDATE remote_access_profiles
            SET protocol = ?, name = ?, host = ?, port = ?, username = ?,
                auth_method = ?, description = ?, enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            payload.protocol, payload.name, payload.host, port, payload.username,
            payload.auth_method, payload.description, int(payload.enabled), profile_id,
        ))
        _audit(connection, request, "profile.updated", payload.protocol, profile_id, payload.name)
        connection.commit()
        row = connection.execute(
            "SELECT * FROM remote_access_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return _serialize_profile(row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="A profile with that name already exists for this protocol.",
        ) from exc
    finally:
        connection.close()


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str, request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        existing = connection.execute(
            "SELECT * FROM remote_access_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Remote Access profile not found.")

        _audit(
            connection, request, "profile.deleted",
            existing["protocol"], existing["id"], existing["name"],
        )
        connection.execute("DELETE FROM remote_access_profiles WHERE id = ?", (profile_id,))
        connection.commit()
        return {"deleted": True, "id": profile_id}
    finally:
        connection.close()


@router.get("/sessions")
def list_sessions(request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        rows = connection.execute("""
            SELECT id, profile_id, protocol, profile_name, host, username,
                   status, started_at, ended_at, error_code, created_at, updated_at
            FROM remote_access_sessions
            ORDER BY created_at DESC
            LIMIT 200
        """).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "engine_available": _engine_adapter() is not None,
            "client_agent_available": False,
        }
    finally:
        connection.close()


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        row = connection.execute("""
            SELECT id, profile_id, protocol, profile_name, host, username,
                   status, started_at, ended_at, error_code, created_at, updated_at
            FROM remote_access_sessions WHERE id = ?
        """, (session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Remote session not found.")
        return dict(row)
    finally:
        connection.close()


@router.post("/sessions", status_code=201)
def start_session(payload: StartSessionInput, request: Request):
    _require_admin(request)

    connection = _connect()
    try:
        profile = _lookup_profile(connection, payload.protocol, payload.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Connection profile not found.")
        if not profile["enabled"]:
            raise HTTPException(status_code=409, detail="This profile is disabled.")

        auth_method = profile["auth_method"]
        if auth_method == "password" and not payload.password and not payload.credential_ref:
            raise HTTPException(
                status_code=422,
                detail="A password or credential reference is required for this profile.",
            )

        # Password is a SecretStr in memory only. Never insert it into SQLite or audit logs.
        engine = _engine_adapter()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CONNECTION_ENGINE_UNAVAILABLE",
                    "message": "The session API is ready, but the connection engine is not included in this build. No session was created.",
                },
            )

        # The future engine adapter will own session lifecycle and credential hand-off.
        # Do not add persistent session creation here until that adapter is implemented.
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CONNECTION_ENGINE_ADAPTER_REQUIRED",
                "message": "No compatible connection engine adapter is registered.",
            },
        )
    finally:
        connection.close()


@router.delete("/sessions/{session_id}")
def disconnect_session(session_id: str, request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT id FROM remote_access_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Remote session not found.")

        engine = _engine_adapter()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CONNECTION_ENGINE_UNAVAILABLE",
                    "message": "The connection engine is not available; this session cannot be disconnected by Cartman in this build.",
                },
            )
        raise HTTPException(
            status_code=503,
            detail={"code": "CONNECTION_ENGINE_ADAPTER_REQUIRED", "message": "No engine adapter is registered."},
        )
    finally:
        connection.close()


@router.get("/audit")
def list_audit(request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        rows = connection.execute("""
            SELECT id, actor, action, protocol, profile_id, profile_name, occurred_at
            FROM remote_access_audit
            ORDER BY id DESC
            LIMIT 200
        """).fetchall()
        return {"items": [dict(row) for row in rows]}
    finally:
        connection.close()


_initialize_schema()
