"""Cartman authentication, server-side sessions and API access policy."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter()

# Injected by main.py when the module is integrated.
get_connection = None

COOKIE_NAME = "cartman_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
PASSWORD_HASH_ROUNDS = 600_000
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_FAILURE_LIMIT = 10

ROLES = {"admin", "network_admin", "read_only", "support_agent"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

PUBLIC_API = {
    ("/api/auth/login", "POST"),
    ("/api/health", "GET"),
}

SENSITIVE_READ_PREFIXES = (
    "/api/iam/",
    "/api/software-audit",
    "/api/network/dns-dhcp/",
    "/api/network/dhcp/connector/",
    "/api/endpoint-agents",
    "/api/device-connection-clients",
    "/api/device-connection-requests",
    "/api/device-connection-listener/",
)

PAGE_LOGIN_PATH = "/static/login.html"
PAGE_PASSWORD_CHANGE_PATH = "/static/change-password.html"


class LoginInput(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=1, max_length=1024)


class PasswordChangeInput(BaseModel):
    # Optional for backwards compatibility with the forced first-login change flow.
    # The normal Settings flow requires it in change_password().
    current_password: str = Field("", max_length=1024)
    new_password: str = Field(..., min_length=14, max_length=128)
    confirm_password: str = Field(..., min_length=14, max_length=128)




class NotificationPreferencesInput(BaseModel):
    critical: bool = True
    warning: bool = True
    info: bool = True
    success: bool = True

def _db():
    if not callable(get_connection):
        raise RuntimeError("Cartman authentication database provider is not configured.")
    return get_connection()



# CARTMAN_SUPPORT_AGENT_ROLE_V1
def _migrate_auth_accounts_support_agent_role(connection):
    schema = connection.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name='auth_accounts'
    """).fetchone()

    if not schema:
        raise RuntimeError("auth_accounts table was not found.")
    if "support_agent" in str(schema["sql"] or "").lower():
        return

    account_columns = (
        "id", "username", "display_name", "password_hash", "role",
        "is_active", "created_at", "updated_at", "last_login_at",
        "must_change_password",
    )
    session_columns = (
        "id", "token_hash", "account_id", "created_at",
        "expires_at", "last_seen", "revoked",
    )

    actual = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(auth_accounts)")
    }
    missing = set(account_columns) - actual
    if missing:
        raise RuntimeError(
            "Missing auth_accounts columns: " + ", ".join(sorted(missing))
        )

    accounts = [
        dict(row)
        for row in connection.execute("SELECT * FROM auth_accounts").fetchall()
    ]
    sessions = [
        dict(row)
        for row in connection.execute("SELECT * FROM auth_sessions").fetchall()
    ]

    connection.execute("DROP TABLE auth_sessions")
    connection.execute("DROP TABLE auth_accounts")

    connection.execute("""
        CREATE TABLE auth_accounts (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (
                role IN ('admin', 'network_admin', 'read_only', 'support_agent')
            ),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TEXT,
            must_change_password INTEGER NOT NULL DEFAULT 0
                CHECK (must_change_password IN (0, 1))
        )
    """)

    connection.executemany(
        "INSERT INTO auth_accounts (" + ",".join(account_columns) +
        ") VALUES (" + ",".join("?" for _ in account_columns) + ")",
        [tuple(item[c] for c in account_columns) for item in accounts],
    )

    connection.execute("""
        CREATE TABLE auth_sessions (
            id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            account_id TEXT NOT NULL
                REFERENCES auth_accounts(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
        )
    """)

    connection.executemany(
        "INSERT INTO auth_sessions (" + ",".join(session_columns) +
        ") VALUES (" + ",".join("?" for _ in session_columns) + ")",
        [tuple(item[c] for c in session_columns) for item in sessions],
    )

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_account
        ON auth_sessions(account_id, revoked)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
        ON auth_sessions(expires_at)
    """)


def initialize_auth_database():
    """Create authentication tables without modifying existing IAM records."""
    with _db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS auth_accounts (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK (role IN ('admin', 'network_admin', 'read_only', 'support_agent')),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT,
                must_change_password INTEGER NOT NULL DEFAULT 0
                    CHECK (must_change_password IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                account_id TEXT NOT NULL
                    REFERENCES auth_accounts(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
                    CHECK (revoked IN (0, 1))
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_account
                ON auth_sessions(account_id, revoked);

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
                ON auth_sessions(expires_at);

            CREATE TABLE IF NOT EXISTS auth_login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username_norm TEXT NOT NULL,
                client_ip TEXT NOT NULL DEFAULT '',
                succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1)),
                attempted_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_auth_attempts_time
                ON auth_login_attempts(attempted_at);

            CREATE INDEX IF NOT EXISTS idx_auth_attempts_ip
                ON auth_login_attempts(client_ip, attempted_at);

            CREATE INDEX IF NOT EXISTS idx_auth_attempts_username
                ON auth_login_attempts(username_norm, attempted_at);
        """)

        # Safe additive migration for existing Cartman login accounts.
        account_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(auth_accounts)").fetchall()
        }
        if "must_change_password" not in account_columns:
            connection.execute(
                "ALTER TABLE auth_accounts ADD COLUMN "
                "must_change_password INTEGER NOT NULL DEFAULT 0 "
                "CHECK (must_change_password IN (0, 1))"
            )

        _migrate_auth_accounts_support_agent_role(connection)


def _password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ROUNDS,
        dklen=32,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_HASH_ROUNDS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _verify_password(password, encoded):
    try:
        algorithm, rounds_text, salt_text, digest_text = encoded.split("$", 3)
        rounds = int(rounds_text)

        if algorithm != "pbkdf2_sha256" or not 300_000 <= rounds <= 1_000_000:
            return False

        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)

        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, rounds, dklen=32
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def _public_account(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


def _write_audit(connection, actor, action, resource_type, resource_id="", details=None):
    """Use the existing IAM audit table; never log passwords or session tokens."""
    connection.execute("""
        INSERT INTO iam_audit_events
            (id, actor, action, resource_type, resource_id, details_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(uuid.uuid4()),
        actor or "Unattributed",
        action,
        resource_type,
        str(resource_id or ""),
        json.dumps(details or {}, ensure_ascii=False),
    ))


def create_account_local(username, display_name, password, role="admin",
                         require_empty=False):
    """Create an account from the trusted local CLI, not from a public endpoint."""
    username = str(username or "").strip()
    display_name = str(display_name or "").strip()

    if not re.fullmatch(r"[A-Za-z0-9._@+-]{3,80}", username):
        raise ValueError(
            "Username must be 3-80 characters using letters, numbers, . _ @ + or -."
        )
    if not display_name or len(display_name) > 120:
        raise ValueError("Display name must be 1-120 characters.")
    if any(ord(char) < 32 for char in display_name):
        raise ValueError("Display name contains invalid control characters.")
    if role not in ROLES:
        raise ValueError("Unknown role.")
    if not isinstance(password, str) or len(password) < 14 or len(password) > 128:
        raise ValueError("Password must be 14-128 characters.")

    account_id = str(uuid.uuid4())
    encoded = _password_hash(password)

    with _db() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS total FROM auth_accounts"
        ).fetchone()["total"]

        if require_empty and count:
            raise RuntimeError(
                "An authentication account already exists; initial setup is closed."
            )

        connection.execute("""
            INSERT INTO auth_accounts
                (id, username, display_name, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
        """, (account_id, username, display_name, encoded, role))

        _write_audit(
            connection, username, "auth.account.created",
            "auth_account", account_id, {"role": role}
        )

    return {"id": account_id, "username": username, "role": role}


def _resolve_session(token):
    if not token:
        return None

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = int(time.time())

    with _db() as connection:
        row = connection.execute("""
            SELECT
                s.id AS session_id, s.expires_at, s.last_seen, s.revoked,
                a.id, a.username, a.display_name, a.role, a.is_active,
                a.must_change_password
            FROM auth_sessions s
            JOIN auth_accounts a ON a.id = s.account_id
            WHERE s.token_hash = ?
        """, (token_hash,)).fetchone()

        if row is None:
            return None

        if row["revoked"] or row["expires_at"] <= now or not row["is_active"]:
            if not row["revoked"]:
                connection.execute(
                    "UPDATE auth_sessions SET revoked = 1 WHERE id = ?",
                    (row["session_id"],),
                )
            return None

        if now - row["last_seen"] >= 60:
            connection.execute(
                "UPDATE auth_sessions SET last_seen = ? WHERE id = ?",
                (now, row["session_id"]),
            )

        return {
            "session_id": row["session_id"],
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "must_change_password": bool(row["must_change_password"]),
        }


def _same_origin(request):
    origin = request.headers.get("origin")
    if not origin:
        return True

    try:
        parsed = urlsplit(origin)
        host = request.headers.get("host", "")
        return (
            parsed.scheme.lower() == request.url.scheme.lower()
            and parsed.netloc.lower() == host.lower()
        )
    except (TypeError, ValueError):
        return False




# CARTMAN_BEARER_API_KEY_AUTH_V1
import hashlib as _cartman_bearer_hashlib
import json as _cartman_bearer_json
import os as _cartman_bearer_os
import sqlite3 as _cartman_bearer_sqlite3
import uuid as _cartman_bearer_uuid
from datetime import datetime as _cartman_bearer_datetime, timezone as _cartman_bearer_timezone


def _cartman_bearer_api_key_user(request):
    header = str(request.headers.get("authorization") or "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    if not token.startswith("cm_live_") or len(token) < 30:
        return None
    digest = _cartman_bearer_hashlib.sha256(token.encode("utf-8")).hexdigest()
    db_path = _cartman_bearer_os.path.join(_cartman_bearer_os.path.dirname(_cartman_bearer_os.path.abspath(__file__)), "cartman.db")
    connection = _cartman_bearer_sqlite3.connect(db_path)
    connection.row_factory = _cartman_bearer_sqlite3.Row
    try:
        try:
            row = connection.execute("SELECT * FROM cartman_api_keys WHERE token_hash=?", (digest,)).fetchone()
        except _cartman_bearer_sqlite3.OperationalError:
            return None
        if not row or row["status"] != "Active":
            return None
        expires = row["expires_at"]
        if expires:
            try:
                value = _cartman_bearer_datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                if value <= _cartman_bearer_datetime.now(_cartman_bearer_timezone.utc):
                    return None
            except ValueError:
                return None
        try:
            scopes = _cartman_bearer_json.loads(row["scopes_json"] or "[]")
        except Exception:
            scopes = []
        request_id = str(_cartman_bearer_uuid.uuid4())
        ip = request.client.host if request.client else ""
        now = _cartman_bearer_datetime.now(_cartman_bearer_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        connection.execute("UPDATE cartman_api_keys SET last_used_at=?,last_used_ip=? WHERE id=?", (now,ip,row["id"]))
        try:
            connection.execute("INSERT INTO cartman_api_key_access_logs (id,api_key_id,api_key_name,method,path,client_ip,status_code,created_at) VALUES (?,?,?,?,?,?,NULL,?)", (request_id,row["id"],row["name"],request.method,request.url.path,ip,now))
        except _cartman_bearer_sqlite3.OperationalError:
            request_id = ""
        connection.commit()
        return {"id":row["owner_username"],"username":row["owner_username"],"role":"api_key","session_id":"","_cartman_api_key":True,"_cartman_api_key_id":row["id"],"_cartman_api_key_scopes":scopes,"_cartman_api_key_log_id":request_id}
    finally:
        connection.close()


def _cartman_bearer_api_key_scope_allows(user, path, method):
    clean_path = str(path or "").split("?",1)[0]
    parts = [part for part in clean_path.strip("/").split("/") if part]
    if len(parts) < 2 or parts[0] != "api":
        return False
    category = {
        "devices":"devices", "inventory":"inventory", "monitoring":"monitoring",
        "alerts":"alerts", "alerts-management":"alerts", "tickets":"tickets",
        "network":"network", "vpn":"vpn", "software":"software",
    }.get(parts[1])
    if not category:
        return False
    permission = "read" if str(method or "GET").upper() in {"GET","HEAD","OPTIONS"} else "write"
    scopes = user.get("_cartman_api_key_scopes") or []
    return category + ":" + permission in scopes


def _cartman_bearer_api_key_finish(user, status_code):
    log_id = (user or {}).get("_cartman_api_key_log_id")
    if not log_id:
        return
    db_path = _cartman_bearer_os.path.join(_cartman_bearer_os.path.dirname(_cartman_bearer_os.path.abspath(__file__)), "cartman.db")
    connection = _cartman_bearer_sqlite3.connect(db_path)
    try:
        connection.execute("UPDATE cartman_api_key_access_logs SET status_code=? WHERE id=?", (int(status_code),log_id))
        connection.commit()
    except _cartman_bearer_sqlite3.Error:
        pass
    finally:
        connection.close()
# END CARTMAN_BEARER_API_KEY_AUTH_V1


def _role_allows(role, path, method):
    _cartman_admin_path = str(path or "").split("?", 1)[0]
    _cartman_admin_role = str(role or "").strip().lower().replace("-", "_").replace(" ", "_")
    if _cartman_admin_path == "/api/admin/api-directory" or _cartman_admin_path.startswith("/api/admin/api-keys") or _cartman_admin_path == "/api/connectors" or _cartman_admin_path.startswith("/api/connectors/"):
        if _cartman_admin_role in {"admin", "administrator", "network_admin", "it_admin", "it_administrator"}:
            return True
        if str(method or "GET").upper() == "GET" and _cartman_admin_role in {"read_only", "support_agent", "viewer", "analyst"}:
            return True
        return False
    # CARTMAN_SERVICE_CHECK_DEFINITIONS_AUTHZ_V1
    _scd_path = str(path or "").split("?", 1)[0].rstrip("/")
    _scd_root = "/api/monitoring/service-check-definitions"
    _scd_method = str(method or "GET").upper()
    _scd_role = str(role or "").strip().lower().replace("-", "_").replace(" ", "_")
    if _scd_path == _scd_root or _scd_path.startswith(_scd_root + "/"):
        if _scd_role in {"admin", "administrator", "network_admin", "it_admin", "it_administrator"}:
            return True
        if _scd_method == "GET" and _scd_role in {"support_agent", "read_only", "viewer", "analyst"}:
            return True
        return False

    # CARTMAN_RBAC_FOUNDATION_AUTHZ_V1
    # Foundation management is restricted to the existing legacy admin until the
    # dedicated RBAC management permission is migrated and tested.
    _cartman_rbac_path = str(path or "").split("?", 1)[0].rstrip("/")
    if _cartman_rbac_path == "/api/rbac" or _cartman_rbac_path.startswith("/api/rbac/"):
        return _cartman_admin_role == "admin"

    # CARTMAN_NOTIFICATION_INBOX_AUTHZ_V1
    _cartman_ni_path = str(path or "").split("?", 1)[0].rstrip("/")
    _cartman_ni_method = str(method or "GET").upper()
    _cartman_ni_role = str(role or "").strip().lower().replace("-", "_").replace(" ", "_")
    if _cartman_ni_path in {"/api/notifications/inbox", "/api/notifications/inbox/read"}:
        # Users may read their own inbox, persist events generated in their session,
        # and mark only their own notifications as read. API keys are not accepted.
        return _cartman_ni_role in {"admin", "network_admin", "support_agent", "read_only"} and _cartman_ni_method in {"GET", "POST"}

    # CARTMAN_WORKFLOW_API_AUTHZ_V1
    # Workflow definitions are readable to authenticated operations roles; writes are admin-only.
    _cartman_wf_path = str(path or "").split("?", 1)[0]
    _cartman_wf_method = str(method or "").upper()
    _cartman_wf_role = str(role or "").strip().lower()
    _cartman_wf_parts = [part for part in _cartman_wf_path.strip("/").split("/") if part]
    _cartman_wf_route = (_cartman_wf_path == "/api/workflows" or _cartman_wf_path == "/api/workflow-notifications" or
                         (len(_cartman_wf_parts) >= 3 and _cartman_wf_parts[:2] == ["api", "workflows"] and
                          _cartman_wf_parts[2].isdigit() and len(_cartman_wf_parts) in (3, 4) and
                          (len(_cartman_wf_parts) == 3 or _cartman_wf_parts[3] in {"runs", "run", "toggle"})))
    if _cartman_wf_route:
        if _cartman_wf_role == "admin":
            return True
        if _cartman_wf_method == "GET" and _cartman_wf_role in {"network_admin", "support_agent", "read_only"}:
            return True
        return False
    method = method.upper()

    if path.startswith("/api/auth/"):
        return (path, method) in {
            ("/api/auth/me", "GET"),
            ("/api/auth/logout", "POST"),
            ("/api/auth/password/change", "POST"),
            ("/api/auth/notification-preferences", "GET"),
            ("/api/auth/notification-preferences", "PUT"),
        }

    # CARTMAN_ATTACHMENT_AUTHZ_FIX_V1: permit read routes at middleware level;
    # attachment handlers still enforce access to the parent ticket/article.
    if role in {"network_admin", "support_agent"} and method in SAFE_METHODS:
        if (
            path == "/api/knowledge/articles"
            or re.fullmatch(r"/api/knowledge/articles/[^/]+", path)
            or (method == "GET" and path == "/api/attachments")
            or (method == "GET" and re.fullmatch(r"/api/attachments/file/\d+", path))
            or path == "/api/operations/automations"
            or path == "/api/operations/projects"
            or re.fullmatch(r"/api/operations/automations/[^/]+", path)
            or path == "/api/operations/executions"
            or path == "/api/operations/automation-targets"
            or path == "/api/work-items"
            or re.fullmatch(r"/api/work-items/[^/]+", path)
        ):
            return True

    if role == "admin":
        return True

    if role == "network_admin":
        if path.startswith("/api/network/"):
            return True

        if method in SAFE_METHODS:
            if path in {
                "/api/health",
                "/api/overview",
                "/api/monitoring/summary",
                "/api/devices",
            }:
                return True
            if path.startswith("/api/monitoring/"):
                return True
            if re.fullmatch(r"/api/devices/[^/]+", path):
                return True

        return False

    # CARTMAN_SUPPORT_AGENT_ROLE_V1
    if role == "support_agent":
        # Completion endpoint performs its own assignment and status checks.
        if re.fullmatch(r"/api/work-items/[^/]+/complete", path) and str(method).upper() == "POST":
            return True
        # Upload/delete are additionally restricted by attachment ownership and
        # parent-record checks in app/main.py.
        if path == "/api/attachments" and method == "POST":
            return True
        if re.fullmatch(r"/api/attachments/\d+", path) and method == "DELETE":
            return True
        if path == "/api/work-items" and method == "POST":
            return True
        if re.fullmatch(r"/api/work-items/[^/]+", path) and method == "PUT":
            return True
        if re.fullmatch(r"/api/operations/automations/[^/]+/run", path) and method == "POST":
            return True
        if path == "/api/tickets" and method in {"GET", "POST"}:
            return True
        if re.fullmatch(r"/api/tickets/[^/]+", path) and method in {"GET", "PUT"}:
            return True
        if re.fullmatch(r"/api/tickets/[^/]+/comments", path) and method == "POST":
            return True
        return False
    
    if role == "read_only":
        if method not in SAFE_METHODS:
            return False
        if any(path.startswith(prefix) for prefix in SENSITIVE_READ_PREFIXES):
            return False
        if "/tasks" in path:
            return False
        return True

    return False



# CARTMAN_ROOT_UI_API_V1: explicit Cartman ROOT principal check.
def _cartman_root_is_principal(user):
    if not user or (isinstance(user, dict) and user.get("_cartman_api_key")):
        return False
    try:
        if not isinstance(user, dict):
            user = dict(user)
    except Exception:
        return False
    username = str(user.get("username") or user.get("email") or "").strip()
    if not username:
        return False
    db_path = _cartman_bearer_os.path.join(
        _cartman_bearer_os.path.dirname(_cartman_bearer_os.path.abspath(__file__)), "cartman.db"
    )
    connection = _cartman_bearer_sqlite3.connect(db_path, timeout=3)
    try:
        row = connection.execute(
            "SELECT 1 FROM cartman_root_principals WHERE username=? COLLATE NOCASE AND enabled=1",
            (username,),
        ).fetchone()
        return bool(row)
    except _cartman_bearer_sqlite3.Error:
        return False
    finally:
        connection.close()

async def auth_middleware(request, call_next):
    # CARTMAN_URL_PATH_FRAGMENT_FIX_V1
    # Use the ASGI-decoded path; URL parsing can treat # as a fragment.
    path = request.scope.get("path") or request.url.path
    method = request.method.upper()

    # Same-origin protection for browser state-changing requests.
    if method not in SAFE_METHODS and not _same_origin(request):
        return JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin requests are not allowed."},
        )

    if (path, method) in PUBLIC_API:
        return await call_next(request)

    if path == PAGE_LOGIN_PATH:
        return await call_next(request)

    token = request.cookies.get(COOKIE_NAME)
    user = _resolve_session(token)
    if user is None and request.url.path.startswith("/api/"):
        user = _cartman_bearer_api_key_user(request)
    # CARTMAN_ROOT_UI_API_V1: root-only surfaces are gated server-side, not only hidden in the UI.
    _cartman_root_page = path.startswith("/pages/backup-recovery") or path.startswith("/pages/kill-switch")
    _cartman_root_api = path.startswith("/api/admin/backups")
    if _cartman_root_page or _cartman_root_api:
        if user is None:
            if _cartman_root_page:
                return RedirectResponse(PAGE_LOGIN_PATH, status_code=303)
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        if not _cartman_root_is_principal(user):
            if user.get("_cartman_api_key"):
                _cartman_bearer_api_key_finish(user, 403)
            if _cartman_root_page:
                return RedirectResponse("/", status_code=303)
            return JSONResponse(status_code=403, content={"detail": "A separately granted Cartman ROOT principal is required."})

    # Protect application HTML pages while leaving CSS, JS and images public.
    is_application_page = (
        path == "/"
        or path == "/static/index.html"
        or path in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
        or path.startswith("/pages/")
        or (path.endswith(".html") and path != PAGE_LOGIN_PATH)
    )
    must_change_password = bool(
        user and user.get("must_change_password")
    )

    if must_change_password:
        request.state.auth_user = user
        request.state.auth_session_id = user["session_id"]

        if path == PAGE_PASSWORD_CHANGE_PATH:
            return await call_next(request)

        if path in {
            "/api/auth/password/change",
            "/api/auth/me",
            "/api/auth/logout",
        }:
            return await call_next(request)

        # Allow static resources required to render the password page.
        if path.startswith("/static/") and not path.endswith(".html"):
            return await call_next(request)

        if is_application_page:
            return RedirectResponse(
                PAGE_PASSWORD_CHANGE_PATH, status_code=303
            )

        if path.startswith("/api/"):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Password change required before using Cartman."
                    )
                },
            )

    if path == PAGE_PASSWORD_CHANGE_PATH:
        if user is None:
            return RedirectResponse(PAGE_LOGIN_PATH, status_code=303)
        return RedirectResponse("/", status_code=303)

    if is_application_page:
        if user is None:
            return RedirectResponse(PAGE_LOGIN_PATH, status_code=303)
        request.state.auth_user = user
        request.state.auth_session_id = user["session_id"]
        return await call_next(request)

    # API endpoints are protected by default. New endpoints inherit this rule.
    if path.startswith("/api/"):
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
            )

        self_availability_endpoint = (
            path == "/api/iam/me/support-availability" and method in {"GET", "PUT"}
        )
        allowed = self_availability_endpoint or (
            _cartman_bearer_api_key_scope_allows(user, path, method)
            if user.get("_cartman_api_key") else _role_allows(user["role"], path, method)
        )
        if not allowed:
            if user.get("_cartman_api_key"):
                _cartman_bearer_api_key_finish(user, 403)
            # CARTMAN_AUTHZ_DIAGNOSTIC_V1
            print("[CARTMAN AUTHZ DEBUG] role={!r} method={!r} path={!r} allowed={!r}".format(user.get("role"), method, path, allowed), flush=True)
            return JSONResponse(
                status_code=403,
                content={"detail": "Your role does not permit this operation."},
            )

        request.state.auth_user = user
        request.state.auth_session_id = user.get("session_id", "")
    response = await call_next(request)
    if user and user.get("_cartman_api_key"):
        _cartman_bearer_api_key_finish(user, response.status_code)
    return response


@router.post("/api/auth/login")
def login(payload: LoginInput, request: Request):
    username = payload.username.strip()
    username_norm = username.lower()
    password = payload.password
    client_ip = request.client.host if request.client else ""
    now = int(time.time())

    with _db() as connection:
        connection.execute(
            "DELETE FROM auth_login_attempts WHERE attempted_at < ?",
            (now - 30 * 24 * 60 * 60,),
        )
        failures = connection.execute("""
            SELECT COUNT(*) AS total
            FROM auth_login_attempts
            WHERE attempted_at >= ?
              AND succeeded = 0
              AND (client_ip = ? OR username_norm = ?)
        """, (
            now - LOGIN_WINDOW_SECONDS, client_ip, username_norm
        )).fetchone()["total"]

        if failures >= LOGIN_FAILURE_LIMIT:
            _write_audit(
                connection, "Unattributed", "auth.login.rate_limited",
                "auth_account", username_norm, {"client_ip": client_ip}
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many failed attempts. Try again later."},
            )

        account = connection.execute("""
            SELECT id, username, display_name, password_hash, role, is_active,
                   must_change_password
            FROM auth_accounts
            WHERE username = ? COLLATE NOCASE
        """, (username,)).fetchone()

        password_ok = (
            _verify_password(password, account["password_hash"])
            if account is not None
            else False
        )

        if account is None:
            hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                b"cartman-invalid-login-salt", PASSWORD_HASH_ROUNDS, dklen=32
            )

        if account is None or not password_ok or not account["is_active"]:
            connection.execute("""
                INSERT INTO auth_login_attempts
                    (username_norm, client_ip, succeeded, attempted_at)
                VALUES (?, ?, 0, ?)
            """, (username_norm, client_ip, now))

            _write_audit(
                connection, "Unattributed", "auth.login.failed",
                "auth_account", username_norm, {"client_ip": client_ip}
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid username or password."},
            )

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        session_id = str(uuid.uuid4())
        expiry = now + SESSION_TTL_SECONDS

        connection.execute("""
            INSERT INTO auth_sessions
                (id, token_hash, account_id, created_at, expires_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, token_hash, account["id"], now, expiry, now))

        connection.execute("""
            UPDATE auth_accounts
            SET last_login_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (account["id"],))

        connection.execute("""
            INSERT INTO auth_login_attempts
                (username_norm, client_ip, succeeded, attempted_at)
            VALUES (?, ?, 1, ?)
        """, (username_norm, client_ip, now))

        _write_audit(
            connection, account["username"], "auth.login.succeeded",
            "auth_account", account["id"], {"client_ip": client_ip}
        )

        public_user = _public_account(account)

    response = JSONResponse({
        "authenticated": True,
        "user": public_user,
        "expires_in": SESSION_TTL_SECONDS,
        "must_change_password": bool(account["must_change_password"]),
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=(request.url.scheme.lower() == "https"),
        samesite="strict",
        path="/",
    )
    return response


@router.post("/api/auth/password/change")
def change_password(payload: PasswordChangeInput, request: Request):
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("_cartman_api_key"):
        raise HTTPException(status_code=403, detail="API keys cannot change account passwords.")
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=422, detail="The new passwords do not match.")

    session_id = getattr(request.state, "auth_session_id", None) or user.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="An authenticated user session is required.")

    with _db() as connection:
        account = connection.execute(
            "SELECT password_hash, must_change_password FROM auth_accounts WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if account is None:
            raise HTTPException(status_code=401, detail="Account not found.")

        forced = bool(account["must_change_password"])
        if not forced:
            if not payload.current_password:
                raise HTTPException(status_code=422, detail="Enter your current password.")
            if not _verify_password(payload.current_password, account["password_hash"]):
                raise HTTPException(status_code=403, detail="The current password is incorrect.")
            if _verify_password(payload.new_password, account["password_hash"]):
                raise HTTPException(status_code=422, detail="Choose a password different from your current password.")

        connection.execute(
            """
            UPDATE auth_accounts
            SET password_hash = ?,
                must_change_password = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (_password_hash(payload.new_password), user["id"]),
        )

        # Keep the current session alive; revoke all other sessions for this account.
        revoked = connection.execute(
            "UPDATE auth_sessions SET revoked = 1 WHERE account_id = ? AND revoked = 0 AND id <> ?",
            (user["id"], session_id),
        ).rowcount

        _write_audit(
            connection,
            user["username"],
            "auth.password.changed",
            "auth_account",
            user["id"],
            {"forced": forced, "other_sessions_revoked": int(revoked or 0)},
        )

    return {
        "changed": True,
        "must_change_password": False,
        "other_sessions_revoked": int(revoked or 0),
    }




def _cartman_ensure_user_notification_preferences(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_user_notification_preferences (
            account_id TEXT PRIMARY KEY,
            critical INTEGER NOT NULL DEFAULT 1,
            warning INTEGER NOT NULL DEFAULT 1,
            info INTEGER NOT NULL DEFAULT 1,
            success INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _cartman_notification_preferences_dict(row):
    return {
        "critical": bool(row["critical"]),
        "warning": bool(row["warning"]),
        "info": bool(row["info"]),
        "success": bool(row["success"]),
        "updated_at": row["updated_at"],
    }


@router.get("/api/auth/notification-preferences")
def get_notification_preferences(request: Request):
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("_cartman_api_key"):
        raise HTTPException(status_code=403, detail="API keys cannot manage user notification preferences.")

    account_id = str(user["id"])
    with _db() as connection:
        _cartman_ensure_user_notification_preferences(connection)
        connection.execute(
            "INSERT OR IGNORE INTO cartman_user_notification_preferences (account_id) VALUES (?)",
            (account_id,),
        )
        row = connection.execute(
            "SELECT critical, warning, info, success, updated_at "
            "FROM cartman_user_notification_preferences WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return {"preferences": _cartman_notification_preferences_dict(row)}


@router.put("/api/auth/notification-preferences")
def update_notification_preferences(payload: NotificationPreferencesInput, request: Request):
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("_cartman_api_key"):
        raise HTTPException(status_code=403, detail="API keys cannot manage user notification preferences.")

    account_id = str(user["id"])
    values = {
        "critical": int(bool(payload.critical)),
        "warning": int(bool(payload.warning)),
        "info": int(bool(payload.info)),
        "success": int(bool(payload.success)),
    }
    with _db() as connection:
        _cartman_ensure_user_notification_preferences(connection)
        connection.execute(
            """INSERT INTO cartman_user_notification_preferences
                (account_id, critical, warning, info, success, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(account_id) DO UPDATE SET
                 critical=excluded.critical,
                 warning=excluded.warning,
                 info=excluded.info,
                 success=excluded.success,
                 updated_at=CURRENT_TIMESTAMP""",
            (account_id, values["critical"], values["warning"], values["info"], values["success"]),
        )
        _write_audit(
            connection,
            user["username"],
            "auth.notification_preferences.updated",
            "auth_account",
            user["id"],
            {"critical": bool(values["critical"]), "warning": bool(values["warning"]),
             "info": bool(values["info"]), "success": bool(values["success"])},
        )
        row = connection.execute(
            "SELECT critical, warning, info, success, updated_at "
            "FROM cartman_user_notification_preferences WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return {"preferences": _cartman_notification_preferences_dict(row), "saved": True}


@router.get("/api/auth/me")
def current_user(request: Request):
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})

    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "must_change_password": bool(user.get("must_change_password")),
        },
    }


@router.post("/api/auth/logout")
def logout(request: Request):
    user = request.state.auth_user
    session_id = request.state.auth_session_id

    with _db() as connection:
        connection.execute(
            "UPDATE auth_sessions SET revoked = 1 WHERE id = ?",
            (session_id,),
        )
        _write_audit(
            connection, user["username"], "auth.logout",
            "auth_account", user["id"], {}
        )

    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=(request.url.scheme.lower() == "https"),
        samesite="strict",
    )
    return response
