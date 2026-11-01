"""Cartman RBAC foundation API with a platform-wide Overview admission gate.

Normal page/action permission enforcement remains a later rollout. The Overview
page permission is already enforced as the mandatory Cartman platform entry gate.
ROOT remains a separate principal in cartman_root_principals, never an RBAC grant.
"""

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

try:
    from . import rbac_catalog
except ImportError:  # direct import when running from app/ as the working directory
    import rbac_catalog

router = APIRouter()
get_connection = None


def _db_required():
    if not callable(get_connection):
        raise RuntimeError("Cartman RBAC database connection has not been configured")


@contextmanager
def _connection():
    _db_required()
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _audit(connection, actor, action, resource_type, resource_id="", details=None):
    connection.execute(
        """INSERT INTO iam_audit_events
           (id, actor, action, resource_type, resource_id, details_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), str(actor or "Unattributed")[:160], action,
         resource_type, str(resource_id or "")[:160],
         json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"))),
    )


def initialize_rbac_database():
    """Idempotent additive schema and unassigned role-template seeding."""
    with _connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS cartman_rbac_roles (
                id TEXT PRIMARY KEY,
                role_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0,1)),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
                created_by TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cartman_rbac_role_permissions (
                id TEXT PRIMARY KEY,
                role_id TEXT NOT NULL REFERENCES cartman_rbac_roles(id) ON DELETE CASCADE,
                permission_key TEXT NOT NULL,
                access_level INTEGER NOT NULL CHECK (access_level BETWEEN 0 AND 3),
                scope_type TEXT NOT NULL DEFAULT 'global',
                scope_id TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(role_id, permission_key, scope_type, scope_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_role_permissions_key
                ON cartman_rbac_role_permissions(permission_key, scope_type, scope_id);
            CREATE TABLE IF NOT EXISTS cartman_rbac_user_roles (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES auth_accounts(id) ON DELETE CASCADE,
                role_id TEXT NOT NULL REFERENCES cartman_rbac_roles(id) ON DELETE CASCADE,
                scope_type TEXT NOT NULL DEFAULT 'global',
                scope_id TEXT NOT NULL DEFAULT '',
                assigned_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, role_id, scope_type, scope_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_user_roles_account
                ON cartman_rbac_user_roles(account_id);
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_user_roles_role
                ON cartman_rbac_user_roles(role_id);

            CREATE TABLE IF NOT EXISTS cartman_rbac_group_roles (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL REFERENCES iam_groups(id) ON DELETE CASCADE,
                role_id TEXT NOT NULL REFERENCES cartman_rbac_roles(id) ON DELETE CASCADE,
                assigned_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, role_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_group_roles_group
                ON cartman_rbac_group_roles(group_id);
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_group_roles_role
                ON cartman_rbac_group_roles(role_id);
            CREATE TABLE IF NOT EXISTS cartman_rbac_user_overrides (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES auth_accounts(id) ON DELETE CASCADE,
                permission_key TEXT NOT NULL,
                access_level INTEGER NOT NULL CHECK (access_level BETWEEN 0 AND 3),
                scope_type TEXT NOT NULL DEFAULT 'global',
                scope_id TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                assigned_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, permission_key, scope_type, scope_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_user_overrides_account
                ON cartman_rbac_user_overrides(account_id);
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_user_overrides_key
                ON cartman_rbac_user_overrides(permission_key, scope_type, scope_id);
        """)
        # CARTMAN_NAMED_SCOPE_BUILDER_V1
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS cartman_rbac_scopes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
                created_by TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cartman_rbac_scope_assignments (
                scope_id TEXT NOT NULL REFERENCES cartman_rbac_scopes(id) ON DELETE CASCADE,
                holder_type TEXT NOT NULL CHECK (holder_type IN ('user','group','department')),
                holder_id TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (scope_id, holder_type, holder_id)
            );
            CREATE TABLE IF NOT EXISTS cartman_rbac_scope_rules (
                scope_id TEXT NOT NULL REFERENCES cartman_rbac_scopes(id) ON DELETE CASCADE,
                field_key TEXT NOT NULL,
                access_level INTEGER NOT NULL CHECK (access_level BETWEEN 0 AND 3),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (scope_id, field_key)
            );
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_scope_assignments_holder
                ON cartman_rbac_scope_assignments(holder_type, holder_id);
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_scope_rules_field
                ON cartman_rbac_scope_rules(field_key, access_level);
        """)
        # END CARTMAN_NAMED_SCOPE_BUILDER_V1

        # CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2: groups included in each named Scope.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cartman_rbac_scope_groups (
                scope_id TEXT NOT NULL
                    REFERENCES cartman_rbac_scopes(id) ON DELETE CASCADE,
                group_id TEXT NOT NULL
                    REFERENCES iam_groups(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (scope_id, group_id)
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_scope_groups_group
            ON cartman_rbac_scope_groups(group_id)
        """)

        # CARTMAN_IDENTITY_POLICIES_V1
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS cartman_rbac_policies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                action TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                status TEXT NOT NULL DEFAULT 'Draft'
                    CHECK (status IN ('Draft','Enabled','Disabled')),
                conditions_json TEXT NOT NULL DEFAULT '[]',
                created_by TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cartman_rbac_policy_assignments (
                policy_id TEXT NOT NULL
                    REFERENCES cartman_rbac_policies(id) ON DELETE CASCADE,
                holder_type TEXT NOT NULL
                    CHECK (holder_type IN ('user','group','department')),
                holder_id TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (policy_id, holder_type, holder_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_policies_priority
                ON cartman_rbac_policies(status, priority, category);
            CREATE INDEX IF NOT EXISTS idx_cartman_rbac_policy_assignments_holder
                ON cartman_rbac_policy_assignments(holder_type, holder_id);
        """)
        # END CARTMAN_IDENTITY_POLICIES_V1

        # CARTMAN_RBAC_ROOT_OVERVIEW_V2: ROOT is a separate principal, not an RBAC role/permission.
        connection.execute("""CREATE TABLE IF NOT EXISTS cartman_root_principals (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            granted_at TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
        )""")
        root_account = connection.execute(
            "SELECT username FROM auth_accounts WHERE username=? COLLATE NOCASE AND is_active=1",
            ("benbenim",),
        ).fetchone()
        if root_account:
            previous_root = connection.execute(
                "SELECT enabled FROM cartman_root_principals WHERE username=? COLLATE NOCASE",
                (root_account["username"],),
            ).fetchone()
            connection.execute("""INSERT INTO cartman_root_principals
                (username, granted_at, granted_by, enabled) VALUES (?, CURRENT_TIMESTAMP, 'Cartman ROOT bootstrap', 1)
                ON CONFLICT(username) DO UPDATE SET enabled=1""", (root_account["username"],))
            if not previous_root or not int(previous_root["enabled"]):
                _audit(connection, "system:root-bootstrap", "iam.root.bootstrap_granted", "auth_account",
                       root_account["username"], {"source": "reserved Cartman bootstrap principal"})

        templates = rbac_catalog.get_role_templates()
        for template in templates:
            role_id = "system:" + template["key"]
            connection.execute(
                """INSERT OR IGNORE INTO cartman_rbac_roles
                   (id, role_key, name, description, is_system, is_active, created_by, updated_by)
                   VALUES (?, ?, ?, ?, 1, 1, 'system', 'system')""",
                (role_id, template["key"], template["name"], template["description"]),
            )
            role_row = connection.execute(
                "SELECT id FROM cartman_rbac_roles WHERE role_key=? COLLATE NOCASE",
                (template["key"],),
            ).fetchone()
            for grant in rbac_catalog.get_template_grants(template["key"]):
                grant_id = "seed:" + template["key"] + ":" + grant["permission_key"]
                connection.execute(
                    """INSERT OR IGNORE INTO cartman_rbac_role_permissions
                       (id, role_id, permission_key, access_level, scope_type, scope_id, updated_by)
                       VALUES (?, ?, ?, ?, ?, ?, 'system')""",
                    (grant_id, role_row["id"], grant["permission_key"], grant["access_level"],
                     grant["scope_type"], grant["scope_id"]),
                )
        # CARTMAN_RBAC_ROOT_OVERVIEW_V2: migrate prior template grants to the two-level Overview model.
        normalized_roles = connection.execute("""UPDATE cartman_rbac_role_permissions
            SET access_level=1, updated_by='system:overview-gate-v2', updated_at=CURRENT_TIMESTAMP
            WHERE permission_key='overview.page' AND access_level>1""").rowcount
        normalized_overrides = connection.execute("""UPDATE cartman_rbac_user_overrides
            SET access_level=1, assigned_by=CASE WHEN assigned_by='' THEN 'system:overview-gate-v2' ELSE assigned_by END,
                updated_at=CURRENT_TIMESTAMP
            WHERE permission_key='overview.page' AND access_level>1""").rowcount
        if normalized_roles or normalized_overrides:
            _audit(connection, "system:overview-gate-v2", "rbac.overview.levels_normalized", "permission",
                   "overview.page", {"role_grants": normalized_roles, "user_overrides": normalized_overrides, "new_level": 1})


def _actor(request):
    user = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authenticated session required.")
    if user.get("_cartman_api_key"):
        raise HTTPException(status_code=403, detail="API keys cannot manage RBAC.")
    return user


def _require_legacy_admin(request):
    user = _actor(request)
    if str(user.get("role") or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required during RBAC foundation phase.")
    return user


def _scope(scope_type, scope_id):
    kind = str(scope_type or "global").strip().lower()
    identifier = str(scope_id or "").strip()
    if kind not in rbac_catalog.SCOPE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported RBAC scope type.")
    if kind == "global" and identifier:
        raise HTTPException(status_code=422, detail="Global scope must not have a scope ID.")
    if kind != "global" and not identifier:
        raise HTTPException(status_code=422, detail="A scope ID is required for this scope type.")
    if len(identifier) > 200:
        raise HTTPException(status_code=422, detail="Scope ID is too long.")
    return kind, identifier


def _role_dict(row):
    item = dict(row)
    item["is_system"] = bool(item.get("is_system"))
    item["is_active"] = bool(item.get("is_active"))
    return item


def _is_root_username(connection, username):
    username = str(username or "").strip()
    if not username:
        return False
    try:
        row = connection.execute(
            "SELECT 1 FROM cartman_root_principals WHERE username=? COLLATE NOCASE AND enabled=1",
            (username,),
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def _root_user(user):
    if not user or (isinstance(user, dict) and user.get("_cartman_api_key")):
        return False
    username = user.get("username") or user.get("email") if isinstance(user, dict) else ""
    with _connection() as connection:
        return _is_root_username(connection, username)


def _require_root(request):
    user = _actor(request)
    if not _root_user(user):
        raise HTTPException(status_code=403, detail="This section can only be viewed and managed by a Cartman ROOT principal.")
    return user


def _overview_level(connection, account_id):
    override = connection.execute("""SELECT access_level FROM cartman_rbac_user_overrides
        WHERE account_id=? AND permission_key='overview.page' AND scope_type='global' AND scope_id=''""",
        (account_id,)).fetchone()
    if override is not None:
        return int(override["access_level"])
    row = connection.execute("""
        SELECT MAX(candidate.access_level) AS access_level
        FROM (
            SELECT rp.access_level
            FROM cartman_rbac_user_roles ur
            JOIN cartman_rbac_roles r
              ON r.id=ur.role_id AND r.is_active=1
            JOIN cartman_rbac_role_permissions rp ON rp.role_id=r.id
            WHERE ur.account_id=? AND ur.scope_type='global' AND ur.scope_id=''
              AND rp.permission_key='overview.page'
              AND rp.scope_type='global' AND rp.scope_id=''

            UNION ALL

            SELECT rp.access_level
            FROM auth_accounts a
            JOIN iam_users iu
              ON lower(trim(iu.username))=lower(trim(a.username))
            JOIN iam_group_members gm ON gm.user_id=iu.id
            JOIN iam_groups g
              ON g.id=gm.group_id AND lower(trim(g.status))='active'
            JOIN cartman_rbac_group_roles gr ON gr.group_id=g.id
            JOIN cartman_rbac_roles r
              ON r.id=gr.role_id AND r.is_active=1
            JOIN cartman_rbac_role_permissions rp ON rp.role_id=r.id
            WHERE a.id=? AND lower(trim(iu.status))='active'
              AND rp.permission_key='overview.page'
              AND rp.scope_type='global' AND rp.scope_id=''
        ) AS candidate
    """, (account_id, account_id)).fetchone()
    return int(row["access_level"] or 0) if row else 0


def platform_access_allowed(user):
    """ROOT bypasses the gate; all other sessions need a global overview.page grant."""
    if not user or (isinstance(user, dict) and user.get("_cartman_api_key") and not (user.get("username") or user.get("owner_username"))):
        return False
    username = (user.get("username") or user.get("owner_username") or user.get("email") or "").strip()
    account_id = str(user.get("id") or "").strip()
    with _connection() as connection:
        if _is_root_username(connection, username):
            return True
        if not account_id and username:
            row = connection.execute("SELECT id FROM auth_accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            account_id = str(row["id"]) if row else ""
        if not account_id:
            return False
        return _overview_level(connection, account_id) >= 1


def _is_platform_surface(path):
    return (
        path in {"/", "/static/index.html", "/docs", "/redoc",
                 "/openapi.json", "/docs/oauth2-redirect"}
        or path.startswith("/pages/")
        or path.startswith("/api/")
    )


def _is_auth_or_health_path(path):
    if path in {"/api/health", "/api/health/", "/api/auth/login", "/api/auth/logout",
                "/api/auth/session", "/api/auth/me", "/api/auth/change-password",
                "/api/auth/password/change", "/api/login", "/api/logout", "/login", "/logout"}:
        return True
    if path.startswith("/api/auth/") and any(token in path.lower() for token in ("login", "logout", "password", "session", "mfa", "csrf")):
        return True
    return False


async def _rbac_gate_after_auth(request, call_next):
    path = str(request.url.path or "/").split("?", 1)[0]
    user = getattr(request.state, "auth_user", None)
    if user and _is_platform_surface(path) and not _is_auth_or_health_path(path):
        try:
            allowed = platform_access_allowed(user)
        except Exception:
            # Fail closed if the authorization database cannot be checked.
            allowed = False
        if not allowed:
            message = "Cartman platform access is disabled. A role with Overview = Full Review is required."
            if path.startswith("/api/"):
                return JSONResponse(status_code=403, content={"detail": message, "code": "CARTMAN_PLATFORM_ACCESS_DENIED"})
            return HTMLResponse(
                "<!doctype html><html lang='en'><meta charset='utf-8'><title>Cartman access denied</title>"
                "<body style='font:14px system-ui;background:#0b1020;color:#e5e7eb;padding:48px;max-width:760px;margin:auto'>"
                "<h1>Cartman access denied</h1><p>Overview access is set to <b>No Access</b> or no access role is assigned. "
                "No Cartman page or API is available to this account.</p><p>Contact a Cartman ROOT administrator.</p>"
                "</body></html>", status_code=403
            )
    return await call_next(request)


def wrap_auth_middleware(legacy_auth_middleware):
    """Apply the RBAC platform gate only after legacy auth resolves auth_user."""
    async def wrapped(request, call_next):
        async def gated_call_next(authenticated_request):
            return await _rbac_gate_after_auth(authenticated_request, call_next)
        return await legacy_auth_middleware(request, gated_call_next)
    return wrapped


@router.get("/api/rbac/root/status")
def get_root_status(request: Request):
    user = _actor(request)
    return {"is_root": _root_user(user), "root_is_separate_from_rbac": True}


@router.get("/api/rbac/root/principals")
def list_root_principals(request: Request):
    _require_root(request)
    with _connection() as connection:
        rows = connection.execute("""SELECT rp.username, rp.granted_at, rp.granted_by, rp.enabled,
            a.display_name, a.is_active, a.role AS legacy_role
            FROM cartman_root_principals rp
            LEFT JOIN auth_accounts a ON lower(trim(a.username))=lower(trim(rp.username))
            ORDER BY lower(rp.username)""").fetchall()
    return {"items": [dict(row) for row in rows], "bootstrap_principal": "benbenim"}


@router.post("/api/rbac/root/principals", status_code=201)
def grant_root_principal(payload: Dict[str, Any], request: Request):
    actor = _require_root(request)
    target = str(payload.get("username") or "").strip()
    if not target or len(target) > 160:
        raise HTTPException(status_code=422, detail="Enter a valid existing Cartman administrator username.")
    actor_name = actor.get("username") or "unknown"
    with _connection() as connection:
        account = connection.execute("""SELECT username, role, is_active FROM auth_accounts
            WHERE username=? COLLATE NOCASE""", (target,)).fetchone()
        if not account or not int(account["is_active"] or 0):
            raise HTTPException(status_code=404, detail="Active authentication account not found.")
        legacy_role = str(account["role"] or "").strip().lower().replace("-", "_").replace(" ", "_")
        if legacy_role not in {"admin", "administrator"}:
            raise HTTPException(status_code=403, detail="ROOT may only be granted to an active legacy Administrator account during this migration phase.")
        current = connection.execute("SELECT enabled FROM cartman_root_principals WHERE username=? COLLATE NOCASE", (account["username"],)).fetchone()
        if current and int(current["enabled"]):
            raise HTTPException(status_code=409, detail="This account is already a ROOT principal.")
        connection.execute("""INSERT INTO cartman_root_principals
            (username, granted_at, granted_by, enabled) VALUES (?, CURRENT_TIMESTAMP, ?, 1)
            ON CONFLICT(username) DO UPDATE SET granted_at=CURRENT_TIMESTAMP, granted_by=excluded.granted_by, enabled=1""",
            (account["username"], actor_name))
        _audit(connection, actor_name, "iam.root.granted", "auth_account", account["username"],
               {"source": "Identity & Security ROOT management"})
    return {"granted": True, "username": account["username"]}


@router.delete("/api/rbac/root/principals/{username}")
def revoke_root_principal(username: str, request: Request):
    actor = _require_root(request)
    target = str(username or "").strip()
    if target.casefold() == "benbenim":
        raise HTTPException(status_code=403, detail="The reserved bootstrap ROOT principal benbenim cannot be revoked from the UI.")
    actor_name = actor.get("username") or "unknown"
    with _connection() as connection:
        current = connection.execute("SELECT enabled FROM cartman_root_principals WHERE username=? COLLATE NOCASE", (target,)).fetchone()
        if not current or not int(current["enabled"]):
            raise HTTPException(status_code=404, detail="Active ROOT principal not found.")
        count = connection.execute("SELECT COUNT(*) FROM cartman_root_principals WHERE enabled=1").fetchone()[0]
        if int(count) <= 1:
            raise HTTPException(status_code=409, detail="The last ROOT principal cannot be revoked.")
        connection.execute("UPDATE cartman_root_principals SET enabled=0 WHERE username=? COLLATE NOCASE", (target,))
        _audit(connection, actor_name, "iam.root.revoked", "auth_account", target,
               {"source": "Identity & Security ROOT management"})
    return {"revoked": True, "username": target}


@router.get("/api/rbac/catalog")
def get_rbac_catalog(request: Request):
    _require_legacy_admin(request)
    permissions = rbac_catalog.get_catalog()
    for item in permissions:
        if item["key"] == "overview.page":
            item["platform_gate"] = True
            item["allowed_levels"] = [0, 1]
            item["level_1_label"] = "Full Review"
            item["description"] = "Mandatory Cartman entry gate. No Access blocks every Cartman page and API; Full Review opens only the Overview page in read-only mode."
    return {"version": rbac_catalog.CATALOG_VERSION,
            "permissions": permissions,
            "scope_types": [{"key": key, "label": value} for key, value in rbac_catalog.SCOPE_TYPES.items()],
            "root_only_capabilities": sorted(rbac_catalog.ROOT_ONLY_CAPABILITIES),
            "platform_access_gate_enabled": True,
            "enforcement_enabled": False}


@router.get("/api/rbac/roles")
def list_rbac_roles(request: Request):
    _require_legacy_admin(request)
    with _connection() as connection:
        rows = connection.execute("""
            SELECT r.*,
                (SELECT COUNT(*) FROM cartman_rbac_role_permissions p
                 WHERE p.role_id=r.id) AS permission_count,
                (SELECT COUNT(*) FROM cartman_rbac_user_roles ur
                 WHERE ur.role_id=r.id) +
                (SELECT COUNT(*) FROM cartman_rbac_group_roles gr
                 WHERE gr.role_id=r.id) AS assignment_count
            FROM cartman_rbac_roles r
            ORDER BY r.is_system DESC, lower(r.name)
        """).fetchall()
    return {"items": [_role_dict(row) for row in rows], "enforcement_enabled": False}


@router.post("/api/rbac/roles", status_code=201)
def create_rbac_role(payload: Dict[str, Any], request: Request):
    user = _require_legacy_admin(request)
    key = str(payload.get("role_key") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if key == "root":
        raise HTTPException(status_code=403, detail="ROOT is a separate system principal, not a regular RBAC role.")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,79}", key):
        raise HTTPException(status_code=422, detail="Role key must use 3-80 lowercase letters, numbers or hyphens.")
    if not name or len(name) > 120 or len(description) > 1000:
        raise HTTPException(status_code=422, detail="Role name or description is invalid.")
    role_id = str(uuid.uuid4())
    actor = user.get("username") or "unknown"
    with _connection() as connection:
        try:
            connection.execute("""INSERT INTO cartman_rbac_roles
                (id, role_key, name, description, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (role_id, key, name, description, actor, actor))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Role key already exists.")
        _audit(connection, actor, "rbac.role.created", "rbac_role", role_id, {"role_key": key, "name": name})
        row = connection.execute("SELECT * FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
    return _role_dict(row)


@router.patch("/api/rbac/roles/{role_id}")
def update_rbac_role(role_id: str, payload: Dict[str, Any], request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    allowed = {"name", "description", "is_active"}
    if not payload or set(payload) - allowed:
        raise HTTPException(status_code=422, detail="Only name, description and is_active can be updated.")
    with _connection() as connection:
        row = connection.execute("SELECT * FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RBAC role not found.")
        name = str(payload.get("name", row["name"])).strip()
        description = str(payload.get("description", row["description"])).strip()
        is_active = payload.get("is_active", row["is_active"])
        if not name or len(name) > 120 or len(description) > 1000 or type(is_active) not in (bool, int) or int(is_active) not in (0, 1):
            raise HTTPException(status_code=422, detail="Invalid role values.")
        connection.execute("""UPDATE cartman_rbac_roles SET name=?, description=?, is_active=?,
            updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (name, description, int(is_active), actor, role_id))
        _audit(connection, actor, "rbac.role.updated", "rbac_role", role_id,
               {"name": name, "description": description, "is_active": int(is_active)})
        updated = connection.execute("SELECT * FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
    return _role_dict(updated)


@router.delete("/api/rbac/roles/{role_id}")
def delete_rbac_role(role_id: str, request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    with _connection() as connection:
        row = connection.execute("SELECT * FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RBAC role not found.")
        if row["is_system"]:
            raise HTTPException(status_code=403, detail="Built-in role templates cannot be deleted.")
        assigned_users = connection.execute(
            "SELECT COUNT(*) FROM cartman_rbac_user_roles WHERE role_id=?",
            (role_id,)
        ).fetchone()[0]
        assigned_groups = connection.execute(
            "SELECT COUNT(*) FROM cartman_rbac_group_roles WHERE role_id=?",
            (role_id,)
        ).fetchone()[0]
        if assigned_users or assigned_groups:
            raise HTTPException(
                status_code=409,
                detail="Role is assigned to users or groups; revoke assignments before deletion."
            )
        connection.execute("DELETE FROM cartman_rbac_roles WHERE id=?", (role_id,))
        _audit(connection, actor, "rbac.role.deleted", "rbac_role", role_id, {"role_key": row["role_key"], "name": row["name"]})
    return {"deleted": True, "id": role_id}


@router.get("/api/rbac/roles/{role_id}/permissions")
def list_role_permissions(role_id: str, request: Request):
    _require_legacy_admin(request)
    with _connection() as connection:
        role = connection.execute("SELECT id, role_key, name FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="RBAC role not found.")
        rows = connection.execute("""SELECT * FROM cartman_rbac_role_permissions
            WHERE role_id=? ORDER BY permission_key, scope_type, scope_id""", (role_id,)).fetchall()
    return {"role": dict(role), "permissions": [dict(row) for row in rows], "enforcement_enabled": False}


@router.put("/api/rbac/roles/{role_id}/permissions")
def replace_role_permissions(role_id: str, payload: Dict[str, Any], request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    grants = payload.get("permissions") if isinstance(payload, dict) else None
    if not isinstance(grants, list) or len(grants) > 2000:
        raise HTTPException(status_code=422, detail="permissions must be a list with at most 2000 entries.")
    normalized = []
    seen = set()
    for grant in grants:
        if not isinstance(grant, dict):
            raise HTTPException(status_code=422, detail="Each permission grant must be an object.")
        key = str(grant.get("permission_key") or "").strip()
        permission = rbac_catalog.get_permission(key)
        if not permission:
            raise HTTPException(status_code=422, detail="Unknown permission key: " + key)
        if permission["root_only"]:
            raise HTTPException(status_code=403, detail="ROOT-only capabilities cannot be granted through RBAC.")
        level = grant.get("access_level")
        if type(level) is not int or level not in (0, 1, 2, 3):
            raise HTTPException(status_code=422, detail="access_level must be an integer from 0 to 3.")
        if key == "overview.page" and level not in (0, 1):
            raise HTTPException(status_code=422, detail="Overview supports only No Access (0) or Full Review (1).")
        scope_type, scope_id = _scope(grant.get("scope_type", "global"), grant.get("scope_id", ""))
        if key == "overview.page" and (scope_type != "global" or scope_id):
            raise HTTPException(status_code=422, detail="Overview is a global platform gate and cannot be scoped to a department or resource.")
        identity = (key, scope_type, scope_id)
        if identity in seen:
            raise HTTPException(status_code=422, detail="Duplicate permission and scope grant.")
        seen.add(identity)
        normalized.append((key, level, scope_type, scope_id))
    with _connection() as connection:
        role = connection.execute("SELECT id, role_key FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="RBAC role not found.")
        connection.execute("DELETE FROM cartman_rbac_role_permissions WHERE role_id=?", (role_id,))
        for key, level, scope_type, scope_id in normalized:
            connection.execute("""INSERT INTO cartman_rbac_role_permissions
                (id, role_id, permission_key, access_level, scope_type, scope_id, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), role_id, key, level, scope_type, scope_id, actor))
        _audit(connection, actor, "rbac.role.permissions.replaced", "rbac_role", role_id,
               {"role_key": role["role_key"], "grant_count": len(normalized)})
    return {"saved": True, "role_id": role_id, "grant_count": len(normalized), "enforcement_enabled": False}


@router.get("/api/rbac/users")
def list_rbac_users(request: Request):
    _require_legacy_admin(request)
    with _connection() as connection:
        rows = connection.execute("""SELECT a.id AS account_id, a.username, a.display_name,
            a.role AS legacy_role, a.is_active, a.created_at, a.last_login_at,
            i.id AS iam_user_id, i.name AS iam_name, i.email AS iam_email,
            i.department AS department, i.status AS iam_status,
            (SELECT COUNT(*) FROM cartman_rbac_user_roles ur WHERE ur.account_id=a.id) AS assigned_role_count,
            (SELECT COUNT(*) FROM cartman_rbac_user_overrides uo WHERE uo.account_id=a.id) AS override_count,
            EXISTS(SELECT 1 FROM cartman_root_principals rp WHERE lower(trim(rp.username))=lower(trim(a.username)) AND rp.enabled=1) AS is_root
            FROM auth_accounts a
            LEFT JOIN iam_users i ON lower(trim(i.username))=lower(trim(a.username))
            ORDER BY lower(a.display_name), lower(a.username)""").fetchall()
    return {"items": [dict(row) for row in rows], "linking": "auth_accounts.id; IAM directory matched by case-insensitive username", "enforcement_enabled": False}


@router.get("/api/rbac/users/{account_id}/assignments")
def get_user_rbac_assignments(account_id: str, request: Request):
    _require_legacy_admin(request)
    with _connection() as connection:
        account = connection.execute("SELECT id, username, display_name, role FROM auth_accounts WHERE id=?", (account_id,)).fetchone()
        if not account:
            raise HTTPException(status_code=404, detail="Authentication account not found.")
        roles = connection.execute("""SELECT ur.*, r.role_key, r.name AS role_name
            FROM cartman_rbac_user_roles ur JOIN cartman_rbac_roles r ON r.id=ur.role_id
            WHERE ur.account_id=? ORDER BY lower(r.name)""", (account_id,)).fetchall()
        overrides = connection.execute("""SELECT * FROM cartman_rbac_user_overrides
            WHERE account_id=? ORDER BY permission_key, scope_type, scope_id""", (account_id,)).fetchall()
        root_state = _is_root_username(connection, account["username"])
        group_roles = connection.execute("""
            SELECT gr.id AS assignment_id, gr.group_id,
                   g.name AS group_name, g.status AS group_status,
                   r.id AS role_id, r.role_key, r.name AS role_name,
                   gr.assigned_by, gr.created_at
            FROM auth_accounts a
            JOIN iam_users iu
              ON lower(trim(iu.username))=lower(trim(a.username))
            JOIN iam_group_members gm ON gm.user_id=iu.id
            JOIN iam_groups g ON g.id=gm.group_id
            JOIN cartman_rbac_group_roles gr ON gr.group_id=g.id
            JOIN cartman_rbac_roles r ON r.id=gr.role_id
            WHERE a.id=?
            ORDER BY lower(g.name), lower(r.name)
        """, (account_id,)).fetchall()
    return {
        "account": dict(account),
        "is_root": root_state,
        "roles": [dict(row) for row in roles],
        "group_roles": [dict(row) for row in group_roles],
        "overrides": [dict(row) for row in overrides],
        "enforcement_enabled": False,
    }


@router.post("/api/rbac/user-roles", status_code=201)
def assign_rbac_role(payload: Dict[str, Any], request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    account_id = str(payload.get("account_id") or "").strip()
    role_id = str(payload.get("role_id") or "").strip()
    scope_type, scope_id = _scope(payload.get("scope_type", "global"), payload.get("scope_id", ""))
    assignment_id = str(uuid.uuid4())
    with _connection() as connection:
        account = connection.execute("SELECT username FROM auth_accounts WHERE id=? AND is_active=1", (account_id,)).fetchone()
        role = connection.execute("SELECT role_key, is_active FROM cartman_rbac_roles WHERE id=?", (role_id,)).fetchone()
        if not account:
            raise HTTPException(status_code=404, detail="Active authentication account not found.")
        if not role or not role["is_active"]:
            raise HTTPException(status_code=404, detail="Active RBAC role not found.")
        if str(role["role_key"]).strip().lower() == "root":
            raise HTTPException(status_code=403, detail="ROOT is not assignable through ordinary RBAC role assignments.")
        try:
            connection.execute("""INSERT INTO cartman_rbac_user_roles
                (id, account_id, role_id, scope_type, scope_id, assigned_by)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (assignment_id, account_id, role_id, scope_type, scope_id, actor))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="This role is already assigned at the selected scope.")
        _audit(connection, actor, "rbac.user_role.assigned", "auth_account", account_id,
               {"username": account["username"], "role_key": role["role_key"], "scope_type": scope_type, "scope_id": scope_id})
    return {"id": assignment_id, "account_id": account_id, "role_id": role_id, "scope_type": scope_type, "scope_id": scope_id, "enforcement_enabled": False}


@router.delete("/api/rbac/user-roles/{assignment_id}")
def revoke_rbac_role(assignment_id: str, request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    with _connection() as connection:
        row = connection.execute("""SELECT ur.*, a.username, r.role_key FROM cartman_rbac_user_roles ur
            JOIN auth_accounts a ON a.id=ur.account_id JOIN cartman_rbac_roles r ON r.id=ur.role_id
            WHERE ur.id=?""", (assignment_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Role assignment not found.")
        connection.execute("DELETE FROM cartman_rbac_user_roles WHERE id=?", (assignment_id,))
        _audit(connection, actor, "rbac.user_role.revoked", "auth_account", row["account_id"],
               {"username": row["username"], "role_key": row["role_key"], "scope_type": row["scope_type"], "scope_id": row["scope_id"]})
    return {"revoked": True, "id": assignment_id}


@router.get("/api/rbac/groups/{group_id}/assignments")
def get_group_rbac_assignments(group_id: str, request: Request):
    _require_legacy_admin(request)
    with _connection() as connection:
        group = connection.execute(
            "SELECT id, name, scope, description, status FROM iam_groups WHERE id=?",
            (group_id,)
        ).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="IAM group not found.")

        assignments = connection.execute("""
            SELECT gr.*, r.role_key, r.name AS role_name,
                   r.description AS role_description, r.is_active AS role_is_active
            FROM cartman_rbac_group_roles gr
            JOIN cartman_rbac_roles r ON r.id=gr.role_id
            WHERE gr.group_id=?
            ORDER BY lower(r.name)
        """, (group_id,)).fetchall()

    return {
        "group": dict(group),
        "assignments": [dict(row) for row in assignments],
        "inheritance": "Active group roles contribute to active members' global Overview access.",
    }


@router.post("/api/rbac/group-roles", status_code=201)
def assign_rbac_group_role(payload: Dict[str, Any], request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    group_id = str(payload.get("group_id") or "").strip()
    role_id = str(payload.get("role_id") or "").strip()

    if not group_id or not role_id:
        raise HTTPException(status_code=422, detail="group_id and role_id are required.")

    assignment_id = str(uuid.uuid4())
    with _connection() as connection:
        group = connection.execute(
            "SELECT id, name FROM iam_groups WHERE id=?",
            (group_id,)
        ).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="IAM group not found.")

        role = connection.execute(
            "SELECT id, role_key, name, is_active FROM cartman_rbac_roles WHERE id=?",
            (role_id,)
        ).fetchone()
        if not role or not int(role["is_active"]):
            raise HTTPException(status_code=404, detail="Active RBAC role not found.")
        if str(role["role_key"]).strip().lower() == "root":
            raise HTTPException(
                status_code=403,
                detail="ROOT is a separate system principal and cannot be assigned to groups."
            )

        try:
            connection.execute("""
                INSERT INTO cartman_rbac_group_roles
                    (id, group_id, role_id, assigned_by)
                VALUES (?, ?, ?, ?)
            """, (assignment_id, group_id, role_id, actor))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="This role is already assigned to the selected group."
            )

        _audit(
            connection, actor, "rbac.group_role.assigned",
            "iam_group", group_id,
            {"group_name": group["name"], "role_key": role["role_key"]}
        )

    return {
        "id": assignment_id,
        "group_id": group_id,
        "role_id": role_id,
        "role_key": role["role_key"],
        "role_name": role["name"],
    }


@router.delete("/api/rbac/group-roles/{assignment_id}")
def revoke_rbac_group_role(assignment_id: str, request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"

    with _connection() as connection:
        row = connection.execute("""
            SELECT gr.*, g.name AS group_name, r.role_key, r.name AS role_name
            FROM cartman_rbac_group_roles gr
            JOIN iam_groups g ON g.id=gr.group_id
            JOIN cartman_rbac_roles r ON r.id=gr.role_id
            WHERE gr.id=?
        """, (assignment_id,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Group role assignment not found.")

        connection.execute(
            "DELETE FROM cartman_rbac_group_roles WHERE id=?",
            (assignment_id,)
        )
        _audit(
            connection, actor, "rbac.group_role.revoked",
            "iam_group", row["group_id"],
            {"group_name": row["group_name"], "role_key": row["role_key"]}
        )

    return {"revoked": True, "id": assignment_id}


@router.post("/api/rbac/user-overrides", status_code=201)
def set_rbac_user_override(payload: Dict[str, Any], request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    account_id = str(payload.get("account_id") or "").strip()
    key = str(payload.get("permission_key") or "").strip()
    permission = rbac_catalog.get_permission(key)
    if not permission:
        raise HTTPException(status_code=422, detail="Unknown permission key.")
    if permission["root_only"]:
        raise HTTPException(status_code=403, detail="ROOT-only capabilities cannot be overridden through RBAC.")
    level = payload.get("access_level")
    if type(level) is not int or level not in (0, 1, 2, 3):
        raise HTTPException(status_code=422, detail="access_level must be an integer from 0 to 3.")
    if key == "overview.page" and level not in (0, 1):
        raise HTTPException(status_code=422, detail="Overview supports only No Access (0) or Full Review (1).")
    scope_type, scope_id = _scope(payload.get("scope_type", "global"), payload.get("scope_id", ""))
    if key == "overview.page" and (scope_type != "global" or scope_id):
        raise HTTPException(status_code=422, detail="Overview is a global platform gate and cannot be scoped to a department or resource.")
    reason = str(payload.get("reason") or "").strip()
    if len(reason) > 500:
        raise HTTPException(status_code=422, detail="Override reason is too long.")
    override_id = str(uuid.uuid4())
    with _connection() as connection:
        account = connection.execute("SELECT username FROM auth_accounts WHERE id=?", (account_id,)).fetchone()
        if not account:
            raise HTTPException(status_code=404, detail="Authentication account not found.")
        existing = connection.execute("""SELECT id FROM cartman_rbac_user_overrides
            WHERE account_id=? AND permission_key=? AND scope_type=? AND scope_id=?""",
            (account_id, key, scope_type, scope_id)).fetchone()
        if existing:
            override_id = existing["id"]
            connection.execute("""UPDATE cartman_rbac_user_overrides SET access_level=?, reason=?,
                assigned_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (level, reason, actor, override_id))
            audit_action = "rbac.user_override.updated"
        else:
            connection.execute("""INSERT INTO cartman_rbac_user_overrides
                (id, account_id, permission_key, access_level, scope_type, scope_id, reason, assigned_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (override_id, account_id, key, level, scope_type, scope_id, reason, actor))
            audit_action = "rbac.user_override.created"
        _audit(connection, actor, audit_action, "auth_account", account_id,
               {"username": account["username"], "permission_key": key, "access_level": level,
                "scope_type": scope_type, "scope_id": scope_id, "reason": reason})
    return {"id": override_id, "account_id": account_id, "permission_key": key, "access_level": level, "scope_type": scope_type, "scope_id": scope_id, "enforcement_enabled": False}


@router.delete("/api/rbac/user-overrides/{override_id}")
def remove_rbac_user_override(override_id: str, request: Request):
    user = _require_legacy_admin(request)
    actor = user.get("username") or "unknown"
    with _connection() as connection:
        row = connection.execute("""SELECT uo.*, a.username FROM cartman_rbac_user_overrides uo
            JOIN auth_accounts a ON a.id=uo.account_id WHERE uo.id=?""", (override_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User override not found.")
        connection.execute("DELETE FROM cartman_rbac_user_overrides WHERE id=?", (override_id,))
        _audit(connection, actor, "rbac.user_override.deleted", "auth_account", row["account_id"],
               {"username": row["username"], "permission_key": row["permission_key"],
                "access_level": row["access_level"], "scope_type": row["scope_type"], "scope_id": row["scope_id"]})
    return {"deleted": True, "id": override_id}


@router.get("/api/rbac/audit")
def list_rbac_audit(request: Request, limit: int = 100):
    _require_legacy_admin(request)
    limit = max(1, min(int(limit or 100), 500))
    with _connection() as connection:
        rows = connection.execute("""SELECT id, actor, action, resource_type, resource_id, details_json, occurred_at
            FROM iam_audit_events WHERE action LIKE 'rbac.%'
            ORDER BY occurred_at DESC, rowid DESC LIMIT ?""", (limit,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item.pop("details_json") or "{}")
        except (TypeError, ValueError):
            item["details"] = {}
        items.append(item)
    return {"items": items, "enforcement_enabled": False}

# CARTMAN_RBAC_ROOT_OVERVIEW_V2

# CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2
# A Scope is a named collection of existing IAM groups. Separate assignments
# attach that Scope to an existing user, group or department.
_SCOPE_ASSIGNABLE_TYPES = {
    "user": "iam_users",
    "group": "iam_groups",
    "department": "departments",
}


def _scope_v2_actor(request):
    _require_legacy_admin(request)
    return _actor(request)


def _scope_v2_actor_name(actor):
    return str(
        actor.get("username") or actor.get("name") or actor.get("id") or "unknown"
    )[:160]


def _scope_v2_normalize_payload(connection, payload):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="A JSON object is required.")

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Scope name is required.")
    if len(name) > 100:
        raise HTTPException(status_code=422, detail="Scope name is too long.")
    if len(description) > 1000:
        raise HTTPException(status_code=422, detail="Scope description is too long.")

    raw_group_ids = payload.get("group_ids", [])
    if raw_group_ids is None:
        raw_group_ids = []
    if not isinstance(raw_group_ids, list):
        raise HTTPException(status_code=422, detail="group_ids must be a list.")

    group_ids = []
    seen = set()
    for value in raw_group_ids:
        group_id = str(value or "").strip()
        if group_id and group_id not in seen:
            seen.add(group_id)
            group_ids.append(group_id)

    if group_ids:
        placeholders = ",".join("?" for _ in group_ids)
        found = connection.execute(
            f"SELECT id FROM iam_groups WHERE id IN ({placeholders})",
            tuple(group_ids),
        ).fetchall()
        found_ids = {str(row["id"]) for row in found}
        missing = [group_id for group_id in group_ids if group_id not in found_ids]
        if missing:
            raise HTTPException(
                status_code=422,
                detail="One or more selected IAM groups no longer exist.",
            )

    return {
        "name": name,
        "description": description,
        "group_ids": group_ids,
    }


def _scope_v2_dict(connection, row):
    scope_id = str(row["id"])
    groups = connection.execute("""
        SELECT g.id, g.name, g.scope, g.department_id
        FROM cartman_rbac_scope_groups sg
        JOIN iam_groups g ON g.id = sg.group_id
        WHERE sg.scope_id=?
        ORDER BY g.name COLLATE NOCASE
    """, (scope_id,)).fetchall()
    assignments = connection.execute("""
        SELECT holder_type, holder_id, created_by, created_at
        FROM cartman_rbac_scope_assignments
        WHERE scope_id=?
        ORDER BY holder_type, holder_id
    """, (scope_id,)).fetchall()
    group_list = [dict(item) for item in groups]
    return {
        "id": scope_id,
        "name": row["name"],
        "description": row["description"],
        "is_active": bool(row["is_active"]),
        "group_ids": [item["id"] for item in group_list],
        "groups": group_list,
        "assignments": [dict(item) for item in assignments],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _scope_v2_save_groups(connection, scope_id, group_ids):
    connection.execute(
        "DELETE FROM cartman_rbac_scope_groups WHERE scope_id=?", (scope_id,)
    )
    for group_id in group_ids:
        connection.execute("""
            INSERT INTO cartman_rbac_scope_groups (scope_id, group_id)
            VALUES (?, ?)
        """, (scope_id, group_id))


def _scope_v2_validate_holder(connection, holder_type, holder_id):
    table = _SCOPE_ASSIGNABLE_TYPES.get(str(holder_type or "").lower())
    if not table:
        raise HTTPException(status_code=422, detail="Invalid Scope assignment type.")
    holder_id = str(holder_id or "").strip()
    if not holder_id:
        raise HTTPException(status_code=422, detail="A holder ID is required.")
    row = connection.execute(
        f"SELECT id FROM {table} WHERE id=?", (holder_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="The selected user, group or department was not found.")
    return holder_id


@router.get("/api/rbac/scopes/catalog")
def get_named_scope_catalog_v2(request: Request):
    _scope_v2_actor(request)
    with _connection() as connection:
        rows = connection.execute("""
            SELECT id, name, scope, department_id
            FROM iam_groups
            ORDER BY name COLLATE NOCASE
        """).fetchall()
    return {
        "groups": [dict(row) for row in rows],
        "assignment_types": [
            {"key": "user", "label": "User"},
            {"key": "group", "label": "Group"},
            {"key": "department", "label": "Department"},
        ],
        "enforcement_enabled": False,
    }


@router.get("/api/rbac/scopes")
def list_named_scopes_v2(request: Request):
    _scope_v2_actor(request)
    with _connection() as connection:
        rows = connection.execute("""
            SELECT * FROM cartman_rbac_scopes
            ORDER BY name COLLATE NOCASE
        """).fetchall()
        items = [_scope_v2_dict(connection, row) for row in rows]
    return {"items": items, "enforcement_enabled": False}


@router.post("/api/rbac/scopes", status_code=201)
async def create_named_scope_v2(request: Request):
    actor = _scope_v2_actor(request)
    actor_name = _scope_v2_actor_name(actor)
    scope_id = __import__("uuid").uuid4().hex

    try:
        with _connection() as connection:
            payload = _scope_v2_normalize_payload(connection, await request.json())
            connection.execute("""
                INSERT INTO cartman_rbac_scopes
                    (id, name, description, target_type, target_id,
                     created_by, updated_by)
                VALUES (?, ?, ?, 'global', '', ?, ?)
            """, (
                scope_id, payload["name"], payload["description"],
                actor_name, actor_name,
            ))
            _scope_v2_save_groups(connection, scope_id, payload["group_ids"])
            _audit(connection, actor_name, "rbac.scope.created", "rbac_scope",
                   scope_id, {
                       "name": payload["name"],
                       "group_ids": payload["group_ids"],
                   })
            row = connection.execute(
                "SELECT * FROM cartman_rbac_scopes WHERE id=?", (scope_id,)
            ).fetchone()
            result = _scope_v2_dict(connection, row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A Scope with this name already exists.")
    return result


@router.put("/api/rbac/scopes/{scope_id}")
async def update_named_scope_v2(scope_id: str, request: Request):
    actor = _scope_v2_actor(request)
    actor_name = _scope_v2_actor_name(actor)

    try:
        with _connection() as connection:
            payload = _scope_v2_normalize_payload(connection, await request.json())
            existing = connection.execute(
                "SELECT id FROM cartman_rbac_scopes WHERE id=?", (scope_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Scope was not found.")

            connection.execute("""
                UPDATE cartman_rbac_scopes
                SET name=?, description=?, updated_by=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (payload["name"], payload["description"], actor_name, scope_id))
            _scope_v2_save_groups(connection, scope_id, payload["group_ids"])
            _audit(connection, actor_name, "rbac.scope.updated", "rbac_scope",
                   scope_id, {
                       "name": payload["name"],
                       "group_ids": payload["group_ids"],
                   })
            row = connection.execute(
                "SELECT * FROM cartman_rbac_scopes WHERE id=?", (scope_id,)
            ).fetchone()
            result = _scope_v2_dict(connection, row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A Scope with this name already exists.")
    return result


@router.delete("/api/rbac/scopes/{scope_id}")
def delete_named_scope_v2(scope_id: str, request: Request):
    actor = _scope_v2_actor(request)
    actor_name = _scope_v2_actor_name(actor)
    with _connection() as connection:
        existing = connection.execute(
            "SELECT id, name FROM cartman_rbac_scopes WHERE id=?", (scope_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Scope was not found.")

        # Retain explicit deletes too; this works even when SQLite FK checks
        # are disabled on a connection. Legacy field rules are cleaned up.
        connection.execute("DELETE FROM cartman_rbac_scope_groups WHERE scope_id=?", (scope_id,))
        connection.execute("DELETE FROM cartman_rbac_scope_assignments WHERE scope_id=?", (scope_id,))
        connection.execute("DELETE FROM cartman_rbac_scope_rules WHERE scope_id=?", (scope_id,))
        connection.execute("DELETE FROM cartman_rbac_scopes WHERE id=?", (scope_id,))
        _audit(connection, actor_name, "rbac.scope.deleted", "rbac_scope",
               scope_id, {"name": existing["name"]})
    return {"ok": True, "id": scope_id}


@router.get("/api/rbac/scope-assignments/{holder_type}/{holder_id}")
def get_entity_scope_assignments(holder_type: str, holder_id: str, request: Request):
    _scope_v2_actor(request)
    with _connection() as connection:
        holder_id = _scope_v2_validate_holder(connection, holder_type, holder_id)
        rows = connection.execute("""
            SELECT scope_id FROM cartman_rbac_scope_assignments
            WHERE holder_type=? AND holder_id=?
            ORDER BY scope_id
        """, (holder_type, holder_id)).fetchall()
    return {
        "holder_type": holder_type,
        "holder_id": holder_id,
        "scope_ids": [str(row["scope_id"]) for row in rows],
        "enforcement_enabled": False,
    }


@router.put("/api/rbac/scope-assignments/{holder_type}/{holder_id}")
async def update_entity_scope_assignments(holder_type: str, holder_id: str, request: Request):
    actor = _scope_v2_actor(request)
    actor_name = _scope_v2_actor_name(actor)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="A JSON object is required.")

    raw_ids = payload.get("scope_ids", [])
    if raw_ids is None:
        raw_ids = []
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=422, detail="scope_ids must be a list.")

    scope_ids = []
    seen = set()
    for value in raw_ids:
        scope_id = str(value or "").strip()
        if scope_id and scope_id not in seen:
            seen.add(scope_id)
            scope_ids.append(scope_id)

    with _connection() as connection:
        holder_id = _scope_v2_validate_holder(connection, holder_type, holder_id)

        if scope_ids:
            placeholders = ",".join("?" for _ in scope_ids)
            rows = connection.execute(
                f"SELECT id FROM cartman_rbac_scopes WHERE id IN ({placeholders})",
                tuple(scope_ids),
            ).fetchall()
            found = {str(row["id"]) for row in rows}
            if any(scope_id not in found for scope_id in scope_ids):
                raise HTTPException(status_code=422, detail="One or more selected Scopes no longer exist.")

        connection.execute("""
            DELETE FROM cartman_rbac_scope_assignments
            WHERE holder_type=? AND holder_id=?
        """, (holder_type, holder_id))
        for scope_id in scope_ids:
            connection.execute("""
                INSERT INTO cartman_rbac_scope_assignments
                    (scope_id, holder_type, holder_id, created_by)
                VALUES (?, ?, ?, ?)
            """, (scope_id, holder_type, holder_id, actor_name))

        _audit(connection, actor_name, "rbac.scope.assignments.updated",
               "iam_" + holder_type, holder_id, {"scope_ids": scope_ids})

    return {
        "holder_type": holder_type,
        "holder_id": holder_id,
        "scope_ids": scope_ids,
        "enforcement_enabled": False,
    }

# END CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2



# CARTMAN_IDENTITY_POLICIES_V1
# Policies are stored configuration only. No authentication, session, network,
# device-trust or privileged-action enforcement is claimed by these routes.

_POLICY_CATEGORIES = {
    "authentication": {
        "label": "Authentication Policies",
        "fields": [
            {"key": "event_type", "label": "Authentication event"},
            {"key": "mfa_status", "label": "MFA status"},
            {"key": "risk_level", "label": "Risk level"},
            {"key": "account_status", "label": "Account status"},
        ],
        "actions": [
            {"key": "allow", "label": "Allow (RBAC still required)"},
            {"key": "deny", "label": "Deny"},
            {"key": "require_mfa", "label": "Require MFA"},
            {"key": "force_reauth", "label": "Require re-authentication"},
        ],
    },
    "session": {
        "label": "Session Policies",
        "fields": [
            {"key": "idle_minutes", "label": "Idle time (minutes)"},
            {"key": "session_age_minutes", "label": "Session age (minutes)"},
            {"key": "concurrent_sessions", "label": "Concurrent sessions"},
            {"key": "device_type", "label": "Device type"},
        ],
        "actions": [
            {"key": "allow", "label": "Allow (RBAC still required)"},
            {"key": "deny", "label": "Deny"},
            {"key": "force_reauth", "label": "Require re-authentication"},
            {"key": "terminate_session", "label": "Terminate session"},
        ],
    },
    "network_access": {
        "label": "Network Access Policies",
        "fields": [
            {"key": "source_ip", "label": "Source IP address / CIDR"},
            {"key": "network_zone", "label": "Network zone"},
            {"key": "vpn_connected", "label": "Corporate VPN connected"},
        ],
        "actions": [
            {"key": "allow", "label": "Allow (RBAC still required)"},
            {"key": "deny", "label": "Deny"},
            {"key": "require_vpn", "label": "Require corporate VPN"},
        ],
    },
    "device_trust": {
        "label": "Device Trust Policies",
        "fields": [
            {"key": "managed", "label": "Device is managed"},
            {"key": "compliant", "label": "Device is compliant"},
            {"key": "os_family", "label": "Operating system family"},
            {"key": "device_status", "label": "Device status"},
        ],
        "actions": [
            {"key": "allow", "label": "Allow (RBAC still required)"},
            {"key": "deny", "label": "Deny"},
            {"key": "require_managed_device", "label": "Require managed device"},
            {"key": "require_compliant_device", "label": "Require compliant device"},
        ],
    },
    "privileged_access": {
        "label": "Privileged Access Policies",
        "fields": [
            {"key": "permission_key", "label": "RBAC permission key"},
            {"key": "action_name", "label": "Requested action"},
            {"key": "resource_type", "label": "Resource type"},
            {"key": "approval_status", "label": "Approval status"},
        ],
        "actions": [
            {"key": "allow", "label": "Allow (RBAC still required)"},
            {"key": "deny", "label": "Deny"},
            {"key": "require_mfa", "label": "Require MFA"},
            {"key": "require_approval", "label": "Require approval"},
            {"key": "force_reauth", "label": "Require re-authentication"},
        ],
    },
}
_POLICY_OPERATORS = [
    {"key": "equals", "label": "Equals"},
    {"key": "not_equals", "label": "Does not equal"},
    {"key": "contains", "label": "Contains"},
    {"key": "greater_than", "label": "Greater than"},
    {"key": "less_than", "label": "Less than"},
    {"key": "in_cidr", "label": "IP is in CIDR"},
]
_POLICY_HOLDER_TABLES = {
    "user": "iam_users",
    "group": "iam_groups",
    "department": "departments",
}
_POLICY_STATES = {"Draft", "Enabled", "Disabled"}


def _policy_require_admin(request):
    _require_legacy_admin(request)
    return _actor(request)


def _policy_actor_name(actor):
    return str(actor.get("username") or actor.get("name") or actor.get("id") or "unknown")[:160]


def _policy_dict(connection, row):
    assignments = connection.execute("""
        SELECT holder_type, holder_id, created_by, created_at
        FROM cartman_rbac_policy_assignments
        WHERE policy_id=?
        ORDER BY holder_type, holder_id
    """, (row["id"],)).fetchall()
    try:
        conditions = json.loads(row["conditions_json"] or "[]")
    except (TypeError, ValueError):
        conditions = []
    if not isinstance(conditions, list):
        conditions = []
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "action": row["action"],
        "priority": int(row["priority"]),
        "status": row["status"],
        "conditions": conditions,
        "assignments": [dict(item) for item in assignments],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "enforcement_status": "PENDING",
    }


def _policy_normalize(payload, connection):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="A JSON object is required.")

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    category = str(payload.get("category") or "").strip().lower()
    action = str(payload.get("action") or "").strip().lower()
    status = str(payload.get("status") or "Draft").strip().title()

    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail="Policy name is required and must be at most 120 characters.")
    if len(description) > 1200:
        raise HTTPException(status_code=422, detail="Description must be at most 1200 characters.")
    if category not in _POLICY_CATEGORIES:
        raise HTTPException(status_code=422, detail="Select a supported policy category.")
    allowed_actions = {item["key"] for item in _POLICY_CATEGORIES[category]["actions"]}
    if action not in allowed_actions:
        raise HTTPException(status_code=422, detail="The selected action is not supported for this category.")
    if status not in _POLICY_STATES:
        raise HTTPException(status_code=422, detail="Policy status must be Draft, Enabled or Disabled.")

    try:
        priority = int(payload.get("priority", 100))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Priority must be an integer.")
    if not 1 <= priority <= 100000:
        raise HTTPException(status_code=422, detail="Priority must be between 1 and 100000.")

    raw_holders = payload.get("holders", [])
    if not isinstance(raw_holders, list):
        raise HTTPException(status_code=422, detail="Policy assignments must be a list.")
    holders = []
    seen = set()
    for item in raw_holders:
        if not isinstance(item, dict):
            continue
        holder_type = str(item.get("holder_type") or "").strip().lower()
        holder_id = str(item.get("holder_id") or "").strip()
        if holder_type not in _POLICY_HOLDER_TABLES or not holder_id:
            continue
        identity = (holder_type, holder_id)
        if identity in seen:
            continue
        table = _POLICY_HOLDER_TABLES[holder_type]
        exists = connection.execute(
            f"SELECT 1 FROM {table} WHERE id=? LIMIT 1", (holder_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=422, detail=f"Selected {holder_type} no longer exists.")
        seen.add(identity)
        holders.append({"holder_type": holder_type, "holder_id": holder_id})

    if not holders:
        raise HTTPException(status_code=422, detail="Assign this policy to at least one user, group or department.")

    raw_conditions = payload.get("conditions", [])
    if not isinstance(raw_conditions, list) or len(raw_conditions) > 20:
        raise HTTPException(status_code=422, detail="Conditions must be a list containing no more than 20 entries.")
    allowed_fields = {item["key"] for item in _POLICY_CATEGORIES[category]["fields"]}
    allowed_operators = {item["key"] for item in _POLICY_OPERATORS}
    conditions = []
    for item in raw_conditions:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Each condition must be an object.")
        field = str(item.get("field") or "").strip()
        operator = str(item.get("operator") or "equals").strip().lower()
        value = str(item.get("value") if item.get("value") is not None else "").strip()
        if field not in allowed_fields:
            raise HTTPException(status_code=422, detail=f"Condition field is not valid for {category}.")
        if operator not in allowed_operators:
            raise HTTPException(status_code=422, detail="Unsupported condition operator.")
        if not value or len(value) > 500:
            raise HTTPException(status_code=422, detail="Condition values are required and limited to 500 characters.")
        if operator == "in_cidr":
            if field != "source_ip":
                raise HTTPException(status_code=422, detail="IP is in CIDR can only be used with Source IP.")
            try:
                import ipaddress
                ipaddress.ip_network(value, strict=False)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Enter a valid IPv4 or IPv6 CIDR range.") from exc
        conditions.append({"field": field, "operator": operator, "value": value})

    return {
        "name": name,
        "description": description,
        "category": category,
        "action": action,
        "priority": priority,
        "status": status,
        "conditions": conditions,
        "holders": holders,
    }


def _policy_save_children(connection, policy_id, payload, actor_name):
    connection.execute("DELETE FROM cartman_rbac_policy_assignments WHERE policy_id=?", (policy_id,))
    for holder in payload["holders"]:
        connection.execute("""
            INSERT INTO cartman_rbac_policy_assignments
                (policy_id, holder_type, holder_id, created_by)
            VALUES (?, ?, ?, ?)
        """, (policy_id, holder["holder_type"], holder["holder_id"], actor_name))


@router.get("/api/rbac/policies/catalog")
def get_policy_catalog(request: Request):
    _policy_require_admin(request)
    return {
        "categories": [
            {"key": key, "label": value["label"], "fields": value["fields"], "actions": value["actions"]}
            for key, value in _POLICY_CATEGORIES.items()
        ],
        "operators": _POLICY_OPERATORS,
        "holder_types": [
            {"key": "user", "label": "Users"},
            {"key": "group", "label": "Groups"},
            {"key": "department", "label": "Departments"},
        ],
        "states": ["Draft", "Enabled", "Disabled"],
        "enforcement_enabled": False,
        "evaluation_order": "Explicit Deny overrides Allow; otherwise lower priority number is evaluated first.",
    }


@router.get("/api/rbac/policies")
def list_policies(request: Request):
    _policy_require_admin(request)
    with _connection() as connection:
        rows = connection.execute("""
            SELECT * FROM cartman_rbac_policies
            ORDER BY CASE WHEN action='deny' THEN 0 ELSE 1 END,
                     priority ASC, name COLLATE NOCASE
        """).fetchall()
        items = [_policy_dict(connection, row) for row in rows]
    return {"items": items, "enforcement_enabled": False}


@router.post("/api/rbac/policies", status_code=201)
async def create_policy(request: Request):
    actor = _policy_require_admin(request)
    actor_name = _policy_actor_name(actor)
    with _connection() as connection:
        payload = _policy_normalize(await request.json(), connection)
        policy_id = __import__("uuid").uuid4().hex
        try:
            connection.execute("""
                INSERT INTO cartman_rbac_policies
                    (id, name, description, category, action, priority, status,
                     conditions_json, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                policy_id, payload["name"], payload["description"],
                payload["category"], payload["action"], payload["priority"],
                payload["status"], json.dumps(payload["conditions"], ensure_ascii=False),
                actor_name, actor_name,
            ))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="A policy with this name already exists.") from exc
        _policy_save_children(connection, policy_id, payload, actor_name)
        _audit(connection, actor_name, "rbac.policy.created", "rbac_policy", policy_id,
               {"name": payload["name"], "category": payload["category"], "status": payload["status"]})
        row = connection.execute("SELECT * FROM cartman_rbac_policies WHERE id=?", (policy_id,)).fetchone()
        result = _policy_dict(connection, row)
    return result


@router.put("/api/rbac/policies/{policy_id}")
async def update_policy(policy_id: str, request: Request):
    actor = _policy_require_admin(request)
    actor_name = _policy_actor_name(actor)
    with _connection() as connection:
        payload = _policy_normalize(await request.json(), connection)
        existing = connection.execute("SELECT id FROM cartman_rbac_policies WHERE id=?", (policy_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Policy was not found.")
        try:
            connection.execute("""
                UPDATE cartman_rbac_policies
                SET name=?, description=?, category=?, action=?, priority=?, status=?,
                    conditions_json=?, updated_by=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (
                payload["name"], payload["description"], payload["category"],
                payload["action"], payload["priority"], payload["status"],
                json.dumps(payload["conditions"], ensure_ascii=False), actor_name, policy_id,
            ))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="A policy with this name already exists.") from exc
        _policy_save_children(connection, policy_id, payload, actor_name)
        _audit(connection, actor_name, "rbac.policy.updated", "rbac_policy", policy_id,
               {"name": payload["name"], "category": payload["category"], "status": payload["status"]})
        row = connection.execute("SELECT * FROM cartman_rbac_policies WHERE id=?", (policy_id,)).fetchone()
        result = _policy_dict(connection, row)
    return result


@router.delete("/api/rbac/policies/{policy_id}")
def delete_policy(policy_id: str, request: Request):
    actor = _policy_require_admin(request)
    actor_name = _policy_actor_name(actor)
    with _connection() as connection:
        row = connection.execute("SELECT id, name FROM cartman_rbac_policies WHERE id=?", (policy_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Policy was not found.")
        connection.execute("DELETE FROM cartman_rbac_policy_assignments WHERE policy_id=?", (policy_id,))
        connection.execute("DELETE FROM cartman_rbac_policies WHERE id=?", (policy_id,))
        _audit(connection, actor_name, "rbac.policy.deleted", "rbac_policy", policy_id, {"name": row["name"]})
    return {"ok": True, "id": policy_id}

# END CARTMAN_IDENTITY_POLICIES_V1
