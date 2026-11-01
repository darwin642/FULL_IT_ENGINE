"""Cartman SSH profile metadata API.

Profiles contain connection metadata only. This module never stores
passwords/private-key contents or opens remote sessions.
"""
from pathlib import Path
import re
import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

DATABASE = Path(__file__).resolve().parent / "cartman.db"
router = APIRouter(tags=["SSH profiles"])


class SSHProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    auth_method: str = Field(default="private_key")
    host_key_fingerprint: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=500)
    enabled: bool = True

    @field_validator("name", "username")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
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

    @field_validator("auth_method")
    @classmethod
    def validate_auth_method(cls, value):
        if value not in {"private_key", "password"}:
            raise ValueError("auth_method must be private_key or password.")
        return value

    @field_validator("host_key_fingerprint", "description")
    @classmethod
    def trim_optional(cls, value):
        return value.strip()


def _connect():
    connection = sqlite3.connect(str(DATABASE), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize_schema():
    connection = _connect()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS ssh_connection_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                host TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 22
                    CHECK (port BETWEEN 1 AND 65535),
                username TEXT NOT NULL,
                auth_method TEXT NOT NULL
                    CHECK (auth_method IN ('private_key', 'password')),
                host_key_fingerprint TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
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
            detail="SSH profile management requires an administrator.",
        )


def _actor(request: Request):
    user = getattr(request.state, "auth_user", None) or {}
    if not isinstance(user, dict):
        return "admin"
    return str(
        user.get("username") or user.get("email") or user.get("id") or "admin"
    )[:128]


def _audit(connection, request, action, profile_id, profile_name):
    connection.execute("""
        INSERT INTO remote_access_audit
            (actor, action, protocol, profile_id, profile_name)
        VALUES (?, ?, 'ssh', ?, ?)
    """, (_actor(request), action, profile_id, profile_name))


def _serialize(row):
    return {
        "id": row["id"],
        "protocol": "ssh",
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "auth_method": row["auth_method"],
        "host_key_fingerprint": row["host_key_fingerprint"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/api/ssh/profiles")
def list_ssh_profiles(request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        rows = connection.execute("""
            SELECT * FROM ssh_connection_profiles
            ORDER BY name COLLATE NOCASE
        """).fetchall()
        return {"items": [_serialize(row) for row in rows]}
    finally:
        connection.close()


@router.post("/api/ssh/profiles", status_code=201)
def create_ssh_profile(payload: SSHProfileInput, request: Request):
    _require_admin(request)
    profile_id = str(uuid.uuid4())
    connection = _connect()
    try:
        connection.execute("""
            INSERT INTO ssh_connection_profiles
                (id, name, host, port, username, auth_method,
                 host_key_fingerprint, description, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id, payload.name, payload.host, payload.port,
            payload.username, payload.auth_method,
            payload.host_key_fingerprint, payload.description,
            int(payload.enabled),
        ))
        _audit(connection, request, "profile.created", profile_id, payload.name)
        connection.commit()
        row = connection.execute(
            "SELECT * FROM ssh_connection_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return _serialize(row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="A profile with that name already exists.",
        ) from exc
    finally:
        connection.close()


@router.put("/api/ssh/profiles/{profile_id}")
def update_ssh_profile(profile_id: str, payload: SSHProfileInput, request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        existing = connection.execute(
            "SELECT id FROM ssh_connection_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="SSH profile not found.")

        connection.execute("""
            UPDATE ssh_connection_profiles
            SET name = ?, host = ?, port = ?, username = ?,
                auth_method = ?, host_key_fingerprint = ?,
                description = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            payload.name, payload.host, payload.port, payload.username,
            payload.auth_method, payload.host_key_fingerprint,
            payload.description, int(payload.enabled), profile_id,
        ))
        _audit(connection, request, "profile.updated", profile_id, payload.name)
        connection.commit()
        row = connection.execute(
            "SELECT * FROM ssh_connection_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return _serialize(row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="A profile with that name already exists.",
        ) from exc
    finally:
        connection.close()


@router.delete("/api/ssh/profiles/{profile_id}")
def delete_ssh_profile(profile_id: str, request: Request):
    _require_admin(request)
    connection = _connect()
    try:
        existing = connection.execute(
            "SELECT id, name FROM ssh_connection_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="SSH profile not found.")

        connection.execute(
            "DELETE FROM ssh_connection_profiles WHERE id = ?",
            (profile_id,),
        )
        _audit(connection, request, "profile.deleted", existing["id"], existing["name"])
        connection.commit()
        return {"deleted": True, "id": profile_id}
    finally:
        connection.close()


_initialize_schema()
