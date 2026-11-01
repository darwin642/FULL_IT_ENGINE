#!/usr/bin/env python3
"""Install Cartman's named Scope policy builder.

Run from the Cartman project root:
    .venv/bin/python cartman_scope_builder_patch.py

The installer is additive, validates all source anchors before writing, makes
an automatic backup, and rolls back if any file replacement fails. Named Scope
policies are configuration only; resource API enforcement remains disabled.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import shutil
import sqlite3
import uuid

ROOT = Path.cwd()
MARKER = "CARTMAN_NAMED_SCOPE_BUILDER_V1"
FILES = {
    "catalog": ROOT / "app/rbac_catalog.py",
    "api": ROOT / "app/rbac_api.py",
    "ui": ROOT / "app/static/js/modules/iam-directory.js",
    "css": ROOT / "app/static/css/modules/identity-security.css",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError("ABORT: " + message)


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    require(count == 1, f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


require((ROOT / "app/main.py").is_file(), "run this installer from the Cartman project root")
original: dict[str, str] = {}
for name, path in FILES.items():
    require(path.is_file(), f"missing file: {path}")
    original[name] = path.read_text(encoding="utf-8")
    require(MARKER not in original[name], f"{name} already has this patch marker")

catalog = original["catalog"]
api = original["api"]
js = original["ui"]
css = original["css"]

# ---------------------------------------------------------------------------
# RBAC catalogue: data-field inventory associated with the existing permission
# catalogue. These are field policies, not new RBAC permissions or principals.
# ---------------------------------------------------------------------------
catalog = replace_once(
    catalog,
    "CATALOG_VERSION = 1",
    "CATALOG_VERSION = 2",
    "RBAC catalogue version",
)

field_catalog = r'''

# CARTMAN_NAMED_SCOPE_BUILDER_V1
# A named Scope is an additional data-field policy layer above existing RBAC.
SCOPE_DATA_FIELDS = [
    {"key": "user_activity.active_duration", "group": "User Activity", "label": "Active Duration", "permission_area": "Reports", "match_terms": ["report", "activity", "session"]},
    {"key": "user_activity.last_login", "group": "User Activity", "label": "Last Login", "permission_area": "IAM / Reports", "match_terms": ["iam", "user", "report", "audit"]},
    {"key": "user_activity.session_history", "group": "User Activity", "label": "Session History", "permission_area": "Reports / Audit", "match_terms": ["report", "session", "audit"]},
    {"key": "user_activity.failed_logins", "group": "User Activity", "label": "Failed Logins", "permission_area": "IAM / Audit", "match_terms": ["iam", "audit", "user"]},
    {"key": "user_activity.activity_timeline", "group": "User Activity", "label": "Activity Timeline", "permission_area": "Reports / Audit", "match_terms": ["report", "activity", "audit"]},

    {"key": "user_identity.display_name", "group": "User Identity", "label": "Display Name", "permission_area": "IAM", "match_terms": ["iam", "user"]},
    {"key": "user_identity.email", "group": "User Identity", "label": "Email", "permission_area": "IAM", "match_terms": ["iam", "user"]},
    {"key": "user_identity.department", "group": "User Identity", "label": "Department", "permission_area": "IAM", "match_terms": ["iam", "department"]},
    {"key": "user_identity.group_membership", "group": "User Identity", "label": "Group Membership", "permission_area": "IAM", "match_terms": ["iam", "group"]},

    # Aggregated department metrics are kept separate from per-device metrics.
    {"key": "department_analytics.active_user_count", "group": "Department Analytics", "label": "Active User Count", "permission_area": "Reports", "match_terms": ["report", "analytics", "user"]},
    {"key": "department_analytics.session_volume", "group": "Department Analytics", "label": "Session Volume", "permission_area": "Reports", "match_terms": ["report", "session", "analytics"]},
    {"key": "department_analytics.ticket_volume", "group": "Department Analytics", "label": "Ticket Volume", "permission_area": "Reports / Tickets", "match_terms": ["report", "ticket"]},
    {"key": "department_analytics.workload_summary", "group": "Department Analytics", "label": "Workload Summary", "permission_area": "Reports / Tasks", "match_terms": ["report", "task", "workflow"]},
    {"key": "department_analytics.service_availability", "group": "Department Analytics", "label": "Service Availability", "permission_area": "Monitoring / Reports", "match_terms": ["monitor", "service", "report"]},
    {"key": "department_analytics.average_resolution_time", "group": "Department Analytics", "label": "Average Resolution Time", "permission_area": "Reports / Tickets", "match_terms": ["report", "ticket"]},

    {"key": "device_metrics.cpu_usage", "group": "Device Metrics", "label": "CPU Usage", "permission_area": "Monitoring / Devices", "match_terms": ["monitor", "device", "endpoint"]},
    {"key": "device_metrics.memory_usage", "group": "Device Metrics", "label": "Memory Usage", "permission_area": "Monitoring / Devices", "match_terms": ["monitor", "device", "endpoint"]},
    {"key": "device_metrics.disk_usage", "group": "Device Metrics", "label": "Disk Usage", "permission_area": "Monitoring / Devices", "match_terms": ["monitor", "device", "endpoint"]},
    {"key": "device_metrics.device_status", "group": "Device Metrics", "label": "Device Status", "permission_area": "Devices / Monitoring", "match_terms": ["device", "endpoint", "monitor"]},
    {"key": "device_metrics.performance_history", "group": "Device Metrics", "label": "Performance History", "permission_area": "Monitoring", "match_terms": ["monitor", "performance"]},

    {"key": "device_identity.hostname", "group": "Device Identity", "label": "Hostname", "permission_area": "Devices", "match_terms": ["device", "endpoint"]},
    {"key": "device_identity.private_ip", "group": "Device Identity", "label": "Private IP", "permission_area": "Devices / Network", "match_terms": ["device", "network"]},
    {"key": "device_identity.public_ip", "group": "Device Identity", "label": "Public IP", "permission_area": "Devices / Network", "match_terms": ["device", "network"]},
    {"key": "device_identity.serial_number", "group": "Device Identity", "label": "Serial Number", "permission_area": "Devices / Inventory", "match_terms": ["device", "inventory"]},
    {"key": "device_identity.operating_system", "group": "Device Identity", "label": "Operating System", "permission_area": "Devices", "match_terms": ["device", "endpoint"]},

    {"key": "inventory.asset_name", "group": "Inventory Assets", "label": "Asset Name", "permission_area": "Inventory", "match_terms": ["inventory", "asset"]},
    {"key": "inventory.asset_type", "group": "Inventory Assets", "label": "Asset Type", "permission_area": "Inventory", "match_terms": ["inventory", "asset"]},
    {"key": "inventory.assigned_to", "group": "Inventory Assets", "label": "Assigned To", "permission_area": "Inventory / IAM", "match_terms": ["inventory", "iam", "user"]},
    {"key": "inventory.purchase_date", "group": "Inventory Assets", "label": "Purchase Date", "permission_area": "Inventory", "match_terms": ["inventory", "asset"]},
    {"key": "inventory.serial_number", "group": "Inventory Assets", "label": "Serial Number", "permission_area": "Inventory", "match_terms": ["inventory", "asset"]},
    {"key": "inventory.asset_department", "group": "Inventory Assets", "label": "Asset Department", "permission_area": "Inventory", "match_terms": ["inventory", "department", "asset"]},

    {"key": "monitoring.events", "group": "Monitoring", "label": "Events", "permission_area": "Monitoring", "match_terms": ["monitor", "event", "alert"]},
    {"key": "monitoring.availability", "group": "Monitoring", "label": "Availability", "permission_area": "Monitoring", "match_terms": ["monitor", "service"]},

    {"key": "tickets.title", "group": "Tickets", "label": "Title", "permission_area": "Tickets", "match_terms": ["ticket", "support"]},
    {"key": "tickets.description", "group": "Tickets", "label": "Description", "permission_area": "Tickets", "match_terms": ["ticket", "support"]},
    {"key": "tickets.priority", "group": "Tickets", "label": "Priority", "permission_area": "Tickets", "match_terms": ["ticket", "support"]},
    {"key": "tickets.assignee", "group": "Tickets", "label": "Assignee", "permission_area": "Tickets / IAM", "match_terms": ["ticket", "iam", "user"]},
    {"key": "tickets.comments", "group": "Tickets", "label": "Comments", "permission_area": "Tickets", "match_terms": ["ticket", "support"]},
    {"key": "tickets.attachments", "group": "Tickets", "label": "Attachments", "permission_area": "Tickets", "match_terms": ["ticket", "support"]},

    {"key": "network.topology", "group": "Network Resources", "label": "Topology", "permission_area": "Network", "match_terms": ["network", "topology"]},
    {"key": "network.ipam", "group": "Network Resources", "label": "IPAM", "permission_area": "Network", "match_terms": ["network", "ipam", "subnet"]},
    {"key": "network.dns", "group": "Network Resources", "label": "DNS", "permission_area": "Network", "match_terms": ["network", "dns"]},
    {"key": "network.device_details", "group": "Network Resources", "label": "Network Device Details", "permission_area": "Network", "match_terms": ["network", "device"]},
]


def get_scope_data_fields():
    """Return named-scope fields linked to matching existing RBAC entries."""
    permissions = get_catalog()
    result = []
    for source in SCOPE_DATA_FIELDS:
        item = dict(source)
        match_terms = item.pop("match_terms", [])
        linked = []
        for permission in permissions:
            if not isinstance(permission, dict) or permission.get("root_only"):
                continue
            permission_key = permission.get("key") or permission.get("permission_key")
            if not permission_key:
                continue
            searchable = " ".join(str(value) for value in permission.values()).lower()
            if any(term in searchable for term in match_terms):
                linked.append(str(permission_key))
        item["rbac_permission_keys"] = sorted(set(linked))
        result.append(item)
    return result
# END CARTMAN_NAMED_SCOPE_BUILDER_V1
'''
catalog = catalog.rstrip() + field_catalog + "\n"

# ---------------------------------------------------------------------------
# Scope policy tables. The existing IAM and department tables are reused only
# as references from the assignment records; no parallel directory is created.
# ---------------------------------------------------------------------------
schema = r'''        # CARTMAN_NAMED_SCOPE_BUILDER_V1
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

'''
api = replace_once(
    api,
    "        # CARTMAN_RBAC_ROOT_OVERVIEW_V2: ROOT is a separate principal, not an RBAC role/permission.",
    schema + "        # CARTMAN_RBAC_ROOT_OVERVIEW_V2: ROOT is a separate principal, not an RBAC role/permission.",
    "scope database schema insertion",
)

# ---------------------------------------------------------------------------
# Admin-only CRUD API. This stores policy definitions but deliberately does
# not claim to enforce them on device, monitoring, ticket or report endpoints.
# ---------------------------------------------------------------------------
routes = r'''

# CARTMAN_NAMED_SCOPE_BUILDER_V1
_SCOPE_TARGET_TYPES = {"global", "department", "group", "user", "device"}
_SCOPE_HOLDER_TYPES = {"user", "group", "department"}


def _named_scope_actor(request):
    _require_legacy_admin(request)
    return _actor(request)


def _named_scope_actor_name(actor):
    return str(actor.get("username") or actor.get("name") or actor.get("id") or "unknown")[:160]


def _named_scope_policy_dict(connection, row):
    scope_id = str(row["id"])
    assignments = connection.execute("""
        SELECT holder_type, holder_id, created_by, created_at
        FROM cartman_rbac_scope_assignments
        WHERE scope_id=? ORDER BY holder_type, holder_id
    """, (scope_id,)).fetchall()
    rules = connection.execute("""
        SELECT field_key, access_level, updated_at
        FROM cartman_rbac_scope_rules
        WHERE scope_id=? ORDER BY field_key
    """, (scope_id,)).fetchall()
    return {
        "id": scope_id,
        "name": row["name"],
        "description": row["description"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "is_active": bool(row["is_active"]),
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "assignments": [dict(item) for item in assignments],
        "rules": [dict(item) for item in rules],
    }


def _normalize_named_scope_payload(payload):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="A JSON object is required.")

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Scope name is required.")
    if len(name) > 100 or len(description) > 1000:
        raise HTTPException(status_code=422, detail="Scope name or description is too long.")

    target_type = str(payload.get("target_type") or "global").strip().lower()
    target_id = str(payload.get("target_id") or "").strip()
    if target_type not in _SCOPE_TARGET_TYPES:
        raise HTTPException(status_code=422, detail="Invalid resource target type.")
    if target_type == "global":
        target_id = ""
    elif not target_id:
        raise HTTPException(status_code=422, detail="Select or enter a resource target.")

    raw_holders = payload.get("holders")
    if not isinstance(raw_holders, list):
        raise HTTPException(status_code=422, detail="Scope holders are required.")
    holders = []
    seen_holders = set()
    for item in raw_holders:
        if not isinstance(item, dict):
            continue
        holder_type = str(item.get("holder_type") or "").strip().lower()
        holder_id = str(item.get("holder_id") or "").strip()
        if holder_type not in _SCOPE_HOLDER_TYPES or not holder_id:
            continue
        identity = (holder_type, holder_id)
        if identity not in seen_holders:
            seen_holders.add(identity)
            holders.append({"holder_type": holder_type, "holder_id": holder_id})
    if not holders:
        raise HTTPException(status_code=422, detail="Assign this scope to at least one user, group or department.")

    allowed_fields = {item["key"] for item in rbac_catalog.get_scope_data_fields()}
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise HTTPException(status_code=422, detail="At least one field-level rule is required.")
    rules = []
    seen_fields = set()
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        field_key = str(item.get("field_key") or "").strip()
        if field_key not in allowed_fields:
            raise HTTPException(status_code=422, detail=f"Unknown scope data field: {field_key or '(empty)'}")
        if field_key in seen_fields:
            raise HTTPException(status_code=422, detail=f"Duplicate scope data field: {field_key}")
        try:
            access_level = int(item.get("access_level", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"Invalid permission level for {field_key}.")
        if access_level not in (0, 1, 2, 3):
            raise HTTPException(status_code=422, detail=f"Permission level must be between 0 and 3: {field_key}")
        seen_fields.add(field_key)
        rules.append({"field_key": field_key, "access_level": access_level})

    return {
        "name": name,
        "description": description,
        "target_type": target_type,
        "target_id": target_id,
        "holders": holders,
        "rules": rules,
    }


def _save_named_scope_children(connection, scope_id, payload, actor_name):
    connection.execute("DELETE FROM cartman_rbac_scope_assignments WHERE scope_id=?", (scope_id,))
    connection.execute("DELETE FROM cartman_rbac_scope_rules WHERE scope_id=?", (scope_id,))
    for holder in payload["holders"]:
        connection.execute("""
            INSERT INTO cartman_rbac_scope_assignments
                (scope_id, holder_type, holder_id, created_by)
            VALUES (?, ?, ?, ?)
        """, (scope_id, holder["holder_type"], holder["holder_id"], actor_name))
    for rule in payload["rules"]:
        connection.execute("""
            INSERT INTO cartman_rbac_scope_rules (scope_id, field_key, access_level)
            VALUES (?, ?, ?)
        """, (scope_id, rule["field_key"], rule["access_level"]))


@router.get("/api/rbac/scopes/catalog")
def get_named_scope_catalog(request: Request):
    _named_scope_actor(request)
    return {
        "fields": rbac_catalog.get_scope_data_fields(),
        "target_types": [
            {"key": "global", "label": "All resources"},
            {"key": "department", "label": "Department"},
            {"key": "group", "label": "IAM Group"},
            {"key": "user", "label": "IAM User"},
            {"key": "device", "label": "Specific Device"},
        ],
        "holder_types": [
            {"key": "user", "label": "Users"},
            {"key": "group", "label": "Groups"},
            {"key": "department", "label": "Departments"},
        ],
        "permission_levels": [
            {"value": 0, "label": "No Access"},
            {"value": 1, "label": "View"},
            {"value": 2, "label": "Edit"},
            {"value": 3, "label": "Manage"},
        ],
        "enforcement_enabled": False,
    }


@router.get("/api/rbac/scopes")
def list_named_scopes(request: Request):
    _named_scope_actor(request)
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM cartman_rbac_scopes ORDER BY name COLLATE NOCASE").fetchall()
        items = [_named_scope_policy_dict(connection, row) for row in rows]
    return {"items": items, "enforcement_enabled": False}


@router.post("/api/rbac/scopes", status_code=201)
async def create_named_scope(request: Request):
    actor = _named_scope_actor(request)
    actor_name = _named_scope_actor_name(actor)
    payload = _normalize_named_scope_payload(await request.json())
    scope_id = __import__("uuid").uuid4().hex
    try:
        with _connection() as connection:
            connection.execute("""
                INSERT INTO cartman_rbac_scopes
                    (id, name, description, target_type, target_id, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (scope_id, payload["name"], payload["description"], payload["target_type"], payload["target_id"], actor_name, actor_name))
            _save_named_scope_children(connection, scope_id, payload, actor_name)
            _audit(connection, actor_name, "rbac.scope.created", "rbac_scope", scope_id, {
                "name": payload["name"], "target_type": payload["target_type"],
                "holder_count": len(payload["holders"]), "field_rule_count": len(payload["rules"]),
            })
            row = connection.execute("SELECT * FROM cartman_rbac_scopes WHERE id=?", (scope_id,)).fetchone()
            result = _named_scope_policy_dict(connection, row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A scope with this name already exists.")
    return result


@router.put("/api/rbac/scopes/{scope_id}")
async def update_named_scope(scope_id: str, request: Request):
    actor = _named_scope_actor(request)
    actor_name = _named_scope_actor_name(actor)
    payload = _normalize_named_scope_payload(await request.json())
    try:
        with _connection() as connection:
            existing = connection.execute("SELECT id FROM cartman_rbac_scopes WHERE id=?", (scope_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Scope was not found.")
            connection.execute("""
                UPDATE cartman_rbac_scopes
                SET name=?, description=?, target_type=?, target_id=?, updated_by=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (payload["name"], payload["description"], payload["target_type"], payload["target_id"], actor_name, scope_id))
            _save_named_scope_children(connection, scope_id, payload, actor_name)
            _audit(connection, actor_name, "rbac.scope.updated", "rbac_scope", scope_id, {
                "name": payload["name"], "target_type": payload["target_type"],
                "holder_count": len(payload["holders"]), "field_rule_count": len(payload["rules"]),
            })
            row = connection.execute("SELECT * FROM cartman_rbac_scopes WHERE id=?", (scope_id,)).fetchone()
            result = _named_scope_policy_dict(connection, row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A scope with this name already exists.")
    return result


@router.delete("/api/rbac/scopes/{scope_id}")
def delete_named_scope(scope_id: str, request: Request):
    actor = _named_scope_actor(request)
    actor_name = _named_scope_actor_name(actor)
    with _connection() as connection:
        existing = connection.execute("SELECT id, name FROM cartman_rbac_scopes WHERE id=?", (scope_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Scope was not found.")
        connection.execute("DELETE FROM cartman_rbac_scope_assignments WHERE scope_id=?", (scope_id,))
        connection.execute("DELETE FROM cartman_rbac_scope_rules WHERE scope_id=?", (scope_id,))
        connection.execute("DELETE FROM cartman_rbac_scopes WHERE id=?", (scope_id,))
        _audit(connection, actor_name, "rbac.scope.deleted", "rbac_scope", scope_id, {"name": existing["name"]})
    return {"ok": True, "id": scope_id}

# END CARTMAN_NAMED_SCOPE_BUILDER_V1
'''
api = api.rstrip() + routes + "\n"

# ---------------------------------------------------------------------------
# Users & Groups UI state, fourth tab, data loader and modal.
# ---------------------------------------------------------------------------
js = replace_once(js, "            toastTimer: null", "            toastTimer: null,\n            scopeItems: [],\n            scopeCatalog: { fields: [] },\n            scopeError: '',\n            scopeModal: null", "scope UI state")
js = replace_once(js, '            const isGroups = state.tab === "groups";', '            const isGroups = state.tab === "groups";\n            const isScopes = state.tab === "scopes";', "scope tab flag")

# Add tab adjacent to the existing Departments tab; anchor is exact and unique.
department_tab_anchor = '                                    aria-pressed="${state.tab === "departments"}">Departments</button>'
js = replace_once(
    js,
    department_tab_anchor,
    department_tab_anchor + '''
                                <button type="button"
                                    class="isec-btn ${isScopes ? "primary" : ""}"
                                    data-iam-action="tab-scopes"
                                    aria-pressed="${isScopes}">Scopes</button>''',
    "Scopes tab button",
)

js = replace_once(
    js,
    '                                <button type="button" class="isec-btn"\n                                    data-iam-action="refresh">↻ Refresh</button>',
    '''                                ${isScopes ? `
                                    <button type="button" class="isec-btn primary"
                                        data-iam-action="create-scope">+ Create scope</button>
                                ` : ""}
                                <button type="button" class="isec-btn"
                                    data-iam-action="refresh">↻ Refresh</button>''',
    "Create Scope toolbar action",
)

js = replace_once(
    js,
    "                        : renderDepartmentsContent();",
    "                        : isScopes ? renderScopesContent() : renderDepartmentsContent();",
    "Scopes content branch",
)
js = replace_once(js, "                    ${renderModal()}", "                    ${renderModal()}\n                    ${renderScopeModal()}", "Scope modal render")

# The previous patch failed because its regex expected exact indentation. Use
# stable start/end markers and slice the existing action block instead.
start_marker = '            if (action === "tab-users" ||'
end_marker = '            if (action === "refresh") {'
starts = [i for i in range(len(js)) if js.startswith(start_marker, i)]
require(len(starts) == 1, f"Scope tab action start: expected 1 match, found {len(starts)}")
start = starts[0]
end = js.find(end_marker, start)
require(end >= 0, "Scope tab action end: refresh action was not found")
new_tab_block = '''            if (action === "tab-users" ||
                action === "tab-groups" ||
                action === "tab-departments" ||
                action === "tab-scopes") {

                state.tab = action === "tab-users"
                    ? "users"
                    : action === "tab-groups"
                        ? "groups"
                        : action === "tab-departments"
                            ? "departments"
                            : "scopes";

                syncSelectedGroup();
                state.modal = null;
                state.scopeModal = null;

                if (state.tab === "scopes") {
                    await loadScopes();
                } else {
                    await loadSelection();
                }

                render();
                return;
            }

'''
js = js[:start] + new_tab_block + js[end:]

scope_actions = r'''            if (action === "create-scope") {
                state.error = "";
                state.scopeError = "";
                state.scopeModal = { scope: null };
                render();
                return;
            }

            if (action === "edit-scope") {
                const scope = state.scopeItems.find(item => item.id === button.dataset.scopeId);
                if (!scope) throw new Error("Scope was not found.");
                state.error = "";
                state.scopeModal = { scope };
                render();
                return;
            }

            if (action === "close-scope-modal") {
                state.scopeModal = null;
                render();
                return;
            }

            if (action === "delete-scope") {
                const scope = state.scopeItems.find(item => item.id === button.dataset.scopeId);
                if (!scope) throw new Error("Scope was not found.");
                if (!window.confirm(`Delete the scope "${scope.name}"? This also removes its holders and field rules.`)) return;
                state.saving = true;
                try {
                    await api(`/api/rbac/scopes/${encodeURIComponent(scope.id)}`, { method: "DELETE" });
                    await loadScopes();
                    state.saving = false;
                    notify("Scope deleted successfully.");
                } catch (error) {
                    state.saving = false;
                    throw error;
                }
                return;
            }

'''
js = replace_once(js, '            if (action === "refresh") {', scope_actions + '            if (action === "refresh") {', "scope action handlers")

scope_ui = r'''        // CARTMAN_NAMED_SCOPE_BUILDER_V1
        function scopeHolderName(type, id) {
            const source = type === "user" ? state.users
                : type === "group" ? state.allGroups : state.departments;
            const item = source.find(entry => String(entry.id) === String(id));
            if (!item) return String(id);
            return item.name || item.display_name || item.email || item.username || String(id);
        }

        function renderScopesContent() {
            const items = state.scopeItems || [];
            const targetLabels = {
                global: "All resources", department: "Department", group: "IAM Group",
                user: "IAM User", device: "Specific Device"
            };
            const cards = items.map(scope => {
                const holders = scope.assignments || [];
                const rules = scope.rules || [];
                const enabled = rules.filter(rule => Number(rule.access_level) > 0).length;
                const target = targetLabels[scope.target_type] || scope.target_type;
                const targetText = scope.target_type === "global" ? target : `${target} · ${scope.target_id}`;
                return `
                    <article class="scope-policy-card">
                        <div class="scope-policy-card-head">
                            <div><h3>${esc(scope.name)}</h3><p>${esc(scope.description || "No description provided.")}</p></div>
                            <span class="scope-policy-status">${scope.is_active ? "Active" : "Inactive"}</span>
                        </div>
                        <div class="scope-policy-meta">
                            <div><span>Resource Target</span><strong>${esc(targetText)}</strong></div>
                            <div><span>Access Holders</span><strong>${holders.length}</strong></div>
                            <div><span>Enabled Fields</span><strong>${enabled} / ${rules.length}</strong></div>
                        </div>
                        <div class="scope-policy-holders">
                            ${holders.map(holder => `<span class="scope-policy-chip">${esc(holder.holder_type)}: ${esc(scopeHolderName(holder.holder_type, holder.holder_id))}</span>`).join("") || `<span class="scope-policy-muted">No holders assigned</span>`}
                        </div>
                        <div class="scope-policy-actions">
                            <button type="button" class="isec-btn" data-iam-action="edit-scope" data-scope-id="${esc(scope.id)}">Edit</button>
                            <button type="button" class="isec-btn danger" data-iam-action="delete-scope" data-scope-id="${esc(scope.id)}">Delete</button>
                        </div>
                    </article>`;
            }).join("");

            return `
                <div class="scope-policy-workspace">
                    <div class="scope-policy-notice">
                        <strong>Enforcement Pending</strong>
                        <p>Scope policies can be configured and stored. Resource APIs do not yet filter returned data using these rules. Do not treat a saved policy as an active security boundary until API enforcement is implemented.</p>
                    </div>
                    ${state.scopeError ? `<div class="iam-dir-error" role="alert">${esc(state.scopeError)}</div>` : ""}
                    <div class="scope-policy-intro">
                        <div><h3>Named Scope Policies</h3><p>Assign a policy to existing users, groups or departments, then define its resource target and field-level access.</p></div>
                        <span>${items.length} configured</span>
                    </div>
                    ${items.length ? `<div class="scope-policy-list">${cards}</div>` : `<div class="iam-dir-empty"><strong>No scopes created yet</strong><p>Create a scope to define access holders, resource target and field-level permissions.</p></div>`}
                </div>`;
        }

        function renderScopeModal() {
            if (!state.scopeModal) return "";
            const scope = state.scopeModal.scope || null;
            const fields = state.scopeCatalog.fields || [];
            const oldHolders = new Set((scope?.assignments || []).map(item => `${item.holder_type}:${item.holder_id}`));
            const oldRules = new Map((scope?.rules || []).map(item => [item.field_key, Number(item.access_level)]));
            const targetType = scope?.target_type || "global";
            const targetValue = targetType === "global" ? "global:" : targetType === "device" ? "device:custom" : `${targetType}:${scope?.target_id || ""}`;
            const makeTarget = (type, id, label) => `<option value="${esc(`${type}:${id}`)}" ${targetValue === `${type}:${id}` ? "selected" : ""}>${esc(label)}</option>`;

            const targetOptions = [
                makeTarget("global", "", "Global · All resources"),
                ...state.departments.map(item => makeTarget("department", item.id, `Department · ${item.name}`)),
                ...state.allGroups.map(item => makeTarget("group", item.id, `IAM Group · ${item.name}`)),
                ...state.users.map(item => makeTarget("user", item.id, `IAM User · ${item.name || item.email || item.id}`)),
                makeTarget("device", "custom", "Specific Device · Enter device ID"),
            ].join("");

            const holderSets = [
                { type: "user", label: "Users", items: state.users },
                { type: "group", label: "Groups", items: state.allGroups },
                { type: "department", label: "Departments", items: state.departments },
            ];
            const holderHtml = holderSets.map(group => `
                <section class="scope-policy-holder-group"><h4>${esc(group.label)}</h4>
                    ${group.items.map(item => {
                        const key = `${group.type}:${item.id}`;
                        const label = item.name || item.display_name || item.email || item.username || item.id;
                        return `<label class="scope-policy-holder-option"><input type="checkbox" name="holders" value="${esc(key)}" ${oldHolders.has(key) ? "checked" : ""}><span><strong>${esc(label)}</strong>${item.email && item.name ? `<small>${esc(item.email)}</small>` : ""}</span></label>`;
                    }).join("") || `<p class="scope-policy-muted">No records available.</p>`}
                </section>`).join("");

            const levels = level => `
                <option value="0" ${level === 0 ? "selected" : ""}>No Access</option>
                <option value="1" ${level === 1 ? "selected" : ""}>View</option>
                <option value="2" ${level === 2 ? "selected" : ""}>Edit</option>
                <option value="3" ${level === 3 ? "selected" : ""}>Manage</option>`;
            const groupNames = [...new Set(fields.map(field => field.group || "Other"))];
            const fieldHtml = groupNames.map(groupName => `
                <section class="scope-policy-field-group"><h4>${esc(groupName)}</h4>
                    ${fields.filter(field => (field.group || "Other") === groupName).map(field => {
                        const level = oldRules.has(field.key) ? oldRules.get(field.key) : 0;
                        const link = (field.rbac_permission_keys || []).join(", ") || field.permission_area || "Existing RBAC permission catalogue";
                        return `<label class="scope-policy-field"><span><strong>${esc(field.label)}</strong><small>${esc(link)}</small></span><select name="field_${esc(field.key)}">${levels(level)}</select></label>`;
                    }).join("")}
                </section>`).join("");

            const oldDeviceId = targetType === "device" ? (scope?.target_id || "") : "";
            return `
                <div class="iam-dir-modal-backdrop scope-policy-backdrop">
                    <form class="iam-dir-modal scope-policy-modal" data-iam-form="save-scope" role="dialog" aria-modal="true" aria-labelledby="scope-policy-modal-title">
                        <div class="iam-dir-modal-header"><div><h2 id="scope-policy-modal-title">${scope ? "Edit Scope" : "Create Scope"}</h2><p class="iam-dir-modal-subtitle">Access Holder and Resource Target are separate policy dimensions.</p></div><button type="button" class="iam-dir-close" data-iam-action="close-scope-modal" aria-label="Close">×</button></div>
                        <div class="scope-policy-editor">
                            <section class="scope-policy-editor-section"><h3>1. Scope Details</h3>
                                <label class="iam-dir-field"><span>Scope Name</span><input name="name" maxlength="100" required value="${esc(scope?.name || "")}" placeholder="e.g. L2 Support - User Activity"></label>
                                <label class="iam-dir-field"><span>Description</span><textarea name="description" rows="2" maxlength="1000" placeholder="Describe the purpose of this policy">${esc(scope?.description || "")}</textarea></label>
                            </section>
                            <section class="scope-policy-editor-section"><h3>2. Access Holders</h3><p>Existing IAM users, groups or departments that receive this policy.</p><div class="scope-policy-holder-grid">${holderHtml}</div></section>
                            <section class="scope-policy-editor-section"><h3>3. Resource Target</h3><p>Whose resources or data the holders may access. This does not change the holder.</p>
                                <label class="iam-dir-field"><span>Target Resource</span><select class="isec-select" name="target" required>${targetOptions}</select></label>
                                <label class="iam-dir-field"><span>Device ID (only for Specific Device)</span><input name="device_id" value="${esc(oldDeviceId)}" placeholder="Enter an existing device ID"></label>
                            </section>
                            <section class="scope-policy-editor-section"><h3>4. Field-Level Permissions</h3><p>Every field defaults to No Access. Scope rules refine access allowed by the existing RBAC module permissions; they do not replace them.</p><div class="scope-policy-field-groups">${fieldHtml}</div></section>
                            <div class="scope-policy-editor-note"><strong>Enforcement Pending</strong><span>Saving this configuration does not yet filter resource API responses.</span></div>
                        </div>
                        <div class="iam-dir-modal-actions"><button type="button" class="isec-btn" data-iam-action="close-scope-modal">Cancel</button><button type="submit" class="isec-btn primary">${scope ? "Save Changes" : "Create Scope"}</button></div>
                    </form>
                </div>`;
        }

        async function loadScopes() {
            state.scopeError = "";
            try {
                const [catalog, response] = await Promise.all([
                    api("/api/rbac/scopes/catalog"),
                    api("/api/rbac/scopes")
                ]);
                state.scopeCatalog = catalog || { fields: [] };
                state.scopeItems = response.items || [];
            } catch (error) {
                state.scopeError = error.message || "Could not load named scope policies.";
                state.scopeItems = [];
            }
        }
        // END CARTMAN_NAMED_SCOPE_BUILDER_V1

'''
js = replace_once(js, "        function notify(message) {", scope_ui + "        function notify(message) {", "Scope render functions")

# Initial page load fetches policy data in addition to the existing directory.
load_start = js.find("async function load()")
require(load_start >= 0, "initial load function was not found")
selection_pos = js.find("await loadSelection();", load_start)
require(selection_pos >= 0, "loadSelection call inside load() was not found")
loading_pos = js.find("state.loading = false;", selection_pos)
require(loading_pos >= 0, "loading completion inside load() was not found")
selection_end = selection_pos + len("await loadSelection();")
line_start = js.rfind("\n", 0, selection_pos) + 1
indent = js[line_start:selection_pos]
js = js[:selection_end] + "\n" + indent + "await loadScopes();" + js[selection_end:]

scope_submit = r'''                if (formType === "save-scope") {
                    const formData = new FormData(form);
                    const selectedTarget = String(formData.get("target") || "global:");
                    const splitAt = selectedTarget.indexOf(":");
                    const targetType = splitAt < 0 ? "global" : selectedTarget.slice(0, splitAt);
                    let targetId = splitAt < 0 ? "" : selectedTarget.slice(splitAt + 1);
                    if (targetType === "device") targetId = String(formData.get("device_id") || "").trim();

                    const holders = Array.from(form.querySelectorAll('input[name="holders"]:checked')).map(input => {
                        const split = input.value.indexOf(":");
                        return { holder_type: input.value.slice(0, split), holder_id: input.value.slice(split + 1) };
                    });
                    if (!holders.length) throw new Error("Select at least one Access Holder.");
                    if (targetType !== "global" && !targetId) throw new Error("Select or enter a Resource Target.");

                    const rules = (state.scopeCatalog.fields || []).map(field => ({
                        field_key: field.key,
                        access_level: Number(formData.get(`field_${field.key}`) || 0)
                    }));
                    const payload = {
                        name: String(formData.get("name") || "").trim(),
                        description: String(formData.get("description") || "").trim(),
                        target_type: targetType,
                        target_id: targetId,
                        holders,
                        rules
                    };
                    const editing = state.scopeModal?.scope;
                    const endpoint = editing ? `/api/rbac/scopes/${encodeURIComponent(editing.id)}` : "/api/rbac/scopes";
                    await api(endpoint, {
                        method: editing ? "PUT" : "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });
                    state.scopeModal = null;
                    state.tab = "scopes";
                    await loadScopes();
                    state.saving = false;
                    notify(editing ? "Scope updated successfully." : "Scope created successfully.");
                    return;
                }

'''
js = replace_once(js, '                if (formType === "create-group") {', scope_submit + '                if (formType === "create-group") {', "Scope form submission")

# ---------------------------------------------------------------------------
# Scope styles. Keep all selectors inside the existing identity-security page.
# ---------------------------------------------------------------------------
scope_css = r'''

/* CARTMAN_NAMED_SCOPE_BUILDER_V1 */
.identity-security .scope-policy-workspace { display: grid; gap: 18px; }
.identity-security .scope-policy-notice,
.identity-security .scope-policy-editor-note {
    display: flex; flex-direction: column; gap: 5px; padding: 14px 16px;
    border: 1px solid var(--isec-line); border-radius: 12px;
    background: var(--isec-panel-soft, var(--isec-panel));
}
.identity-security .scope-policy-notice strong,
.identity-security .scope-policy-editor-note strong { color: var(--isec-text); font-size: 13px; }
.identity-security .scope-policy-notice p,
.identity-security .scope-policy-editor-note span { margin: 0; color: var(--isec-muted); font-size: 12px; line-height: 1.55; }
.identity-security .scope-policy-intro { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.identity-security .scope-policy-intro h3,
.identity-security .scope-policy-card h3 { margin: 0; color: var(--isec-text); font-size: 15px; }
.identity-security .scope-policy-intro p,
.identity-security .scope-policy-card-head p { margin: 5px 0 0; color: var(--isec-muted); font-size: 12px; line-height: 1.5; }
.identity-security .scope-policy-intro > span,
.identity-security .scope-policy-status { color: var(--isec-muted); font-size: 11px; white-space: nowrap; }
.identity-security .scope-policy-list { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; }
.identity-security .scope-policy-card { min-width: 0; padding: 16px; border: 1px solid var(--isec-line); border-radius: 13px; background: var(--isec-panel); }
.identity-security .scope-policy-card-head { display: flex; justify-content: space-between; gap: 12px; }
.identity-security .scope-policy-meta { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; margin-top: 16px; }
.identity-security .scope-policy-meta > div { display: grid; gap: 5px; min-width: 0; }
.identity-security .scope-policy-meta span { color: var(--isec-muted); font-size: 10px; }
.identity-security .scope-policy-meta strong { overflow-wrap: anywhere; color: var(--isec-text); font-size: 12px; }
.identity-security .scope-policy-holders { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.identity-security .scope-policy-chip { padding: 5px 8px; border: 1px solid var(--isec-line); border-radius: 7px; color: var(--isec-muted); font-size: 10px; }
.identity-security .scope-policy-muted { color: var(--isec-muted); font-size: 12px; }
.identity-security .scope-policy-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--isec-line); }
.identity-security .scope-policy-actions .danger { color: var(--isec-danger, #d45d65); }
.identity-security .scope-policy-backdrop { z-index: 1000; }
.identity-security .scope-policy-modal { width: min(900px,100%); max-height: calc(100vh - 40px); overflow: auto; }
.identity-security .scope-policy-editor { display: grid; gap: 20px; padding: 18px 0; }
.identity-security .scope-policy-editor-section { display: grid; gap: 12px; padding-bottom: 18px; border-bottom: 1px solid var(--isec-line); }
.identity-security .scope-policy-editor-section h3 { margin: 0; color: var(--isec-text); font-size: 14px; }
.identity-security .scope-policy-editor-section > p { margin: -5px 0 0; color: var(--isec-muted); font-size: 12px; line-height: 1.5; }
.identity-security .scope-policy-holder-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px; }
.identity-security .scope-policy-holder-group { display: grid; align-content: start; gap: 8px; min-width: 0; max-height: 220px; overflow: auto; padding: 10px; border: 1px solid var(--isec-line); border-radius: 10px; }
.identity-security .scope-policy-holder-group h4,
.identity-security .scope-policy-field-group h4 { margin: 0; color: var(--isec-text); font-size: 12px; }
.identity-security .scope-policy-holder-option { display: flex; align-items: flex-start; gap: 8px; min-width: 0; padding: 5px 0; color: var(--isec-text); font-size: 11px; }
.identity-security .scope-policy-holder-option input { flex: 0 0 auto; margin-top: 2px; }
.identity-security .scope-policy-holder-option span { display: grid; min-width: 0; gap: 3px; overflow-wrap: anywhere; }
.identity-security .scope-policy-holder-option small { color: var(--isec-muted); font-size: 10px; }
.identity-security .scope-policy-field-groups { display: grid; gap: 16px; }
.identity-security .scope-policy-field-group { display: grid; gap: 8px; }
.identity-security .scope-policy-field { display: grid; grid-template-columns: minmax(0,1fr) minmax(140px,190px); align-items: center; gap: 14px; padding: 9px 11px; border: 1px solid var(--isec-line); border-radius: 9px; }
.identity-security .scope-policy-field > span { display: grid; min-width: 0; gap: 4px; }
.identity-security .scope-policy-field strong { color: var(--isec-text); font-size: 12px; }
.identity-security .scope-policy-field small { overflow-wrap: anywhere; color: var(--isec-muted); font-size: 10px; }
.identity-security .scope-policy-field select { width: 100%; min-width: 0; }
@media (max-width: 760px) {
    .identity-security .scope-policy-list,
    .identity-security .scope-policy-holder-grid { grid-template-columns: minmax(0,1fr); }
    .identity-security .scope-policy-meta { grid-template-columns: repeat(2,minmax(0,1fr)); }
    .identity-security .scope-policy-field { grid-template-columns: minmax(0,1fr); }
}
/* END CARTMAN_NAMED_SCOPE_BUILDER_V1 */
'''
css = css.rstrip() + scope_css + "\n"

# ---------------------------------------------------------------------------
# Full preflight: syntax, patch markers, API paths and preserved existing tabs.
# ---------------------------------------------------------------------------
for filename, source in (("rbac_catalog.py", catalog), ("rbac_api.py", api)):
    compile(source, filename, "exec")

for name, source in (("catalog", catalog), ("api", api), ("ui", js), ("css", css)):
    require(MARKER in source, f"patch marker missing from {name}")

for marker in (
    'data-iam-action="tab-users"',
    'data-iam-action="tab-groups"',
    'data-iam-action="tab-departments"',
    'data-iam-action="tab-scopes"',
    'data-iam-action="create-scope"',
    "function renderScopesContent()",
    "function renderScopeModal()",
    "async function loadScopes()",
    'formType === "save-scope"',
    'if (formType === "create-group")',
    'if (action === "manage-members")',
    "Enforcement Pending",
    "/api/rbac/scopes/catalog",
):
    require(marker in js, f"required UI marker missing: {marker}")

for marker in (
    '@router.get("/api/rbac/scopes/catalog")',
    '@router.get("/api/rbac/scopes")',
    '@router.post("/api/rbac/scopes", status_code=201)',
    '@router.put("/api/rbac/scopes/{scope_id}")',
    '@router.delete("/api/rbac/scopes/{scope_id}")',
):
    require(marker in api, f"required API route missing: {marker}")

updated = {"catalog": catalog, "api": api, "ui": js, "css": css}

# Backup all original files only after all source checks pass.
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = ROOT / ".backups" / f"named-scope-builder-{stamp}"
backup_dir.mkdir(parents=True, exist_ok=False)
for name, path in FILES.items():
    shutil.copy2(path, backup_dir / path.name)

written: list[str] = []
temp_paths: list[Path] = []
try:
    for name, path in FILES.items():
        temp = path.with_name(path.name + ".scope-tmp")
        temp_paths.append(temp)
        temp.write_text(updated[name], encoding="utf-8")
        os.replace(temp, path)
        written.append(name)
except Exception:
    for name in written:
        shutil.copy2(backup_dir / FILES[name].name, FILES[name])
    raise
finally:
    for temp in temp_paths:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass

print("\nCARTMAN NAMED SCOPE BUILDER PATCH APPLIED")
print("Backup:", backup_dir)
for name, path in FILES.items():
    print(f"UPDATED {name}: {path}")
print("Python source compile preflight: PASSED")
print("Existing Users / Groups / Departments markers: PRESERVED")
print("Enforcement status: PENDING (configuration only)")
