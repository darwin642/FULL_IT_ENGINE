from pathlib import Path
from datetime import datetime
import shutil
import os
import re

ROOT = Path.cwd()
MARKER = "CARTMAN_IDENTITY_POLICIES_V1"

PATHS = {
    "sidebar": ROOT / "app/static/index.html",
    "modules": ROOT / "app/static/js/core/module-definitions.js",
    "identity_live": ROOT / "app/static/js/modules/identity-security-live.js",
    "policies_page": ROOT / "app/static/pages/policies/index.html",
    "rbac_api": ROOT / "app/rbac_api.py",
}
NEW_PATHS = {
    "policy_js": ROOT / "app/static/js/modules/policies-management.js",
    "policy_css": ROOT / "app/static/css/modules/policies-management.css",
}
PROVIDER_PAGE = ROOT / "app/static/pages/identity-providers/index.html"

for name, path in {**PATHS, **NEW_PATHS}.items():
    if not path.is_file() and name not in NEW_PATHS:
        raise SystemExit(f"ABORT: required file missing: {path}")

for name, path in NEW_PATHS.items():
    if path.exists():
        raise SystemExit(f"ABORT: refusing to overwrite existing {name}: {path}")

original = {name: path.read_text(encoding="utf-8") for name, path in PATHS.items()}
for name, source in original.items():
    if MARKER in source:
        raise SystemExit(f"ABORT: {name} already contains {MARKER}")


def replace_exact(source, old, new, label, count=1):
    found = source.count(old)
    if found != count:
        raise RuntimeError(f"ABORT {label}: expected {count} match(es), found {found}")
    return source.replace(old, new, count)


# ---------------------------------------------------------------------------
# 1) Remove Identity Providers from the active navigation and live shortcuts.
#    Keep its page in the backup; do not touch authentication/provider backends.
# ---------------------------------------------------------------------------
sidebar = original["sidebar"]
provider_nav = re.compile(
    r"^[ \t]*<button\b(?=[^>]*\bdata-page=\"Identity Providers\")[^>]*>.*?</button>[ \t]*\n?",
    re.M | re.S,
)
sidebar, nav_count = provider_nav.subn("", sidebar)
if nav_count != 1:
    raise RuntimeError(f"ABORT Identity Providers sidebar removal: expected 1, found {nav_count}")

modules = original["modules"]
modules = replace_exact(
    modules,
    '    "Identity Providers": "◈",\n',
    "",
    "Identity Providers icon mapping",
)
modules = replace_exact(
    modules,
    '    "Identity Providers": "identity-providers",\n',
    "",
    "Identity Providers route mapping",
)

identity_live = original["identity_live"]
provider_shortcut = '<a href="/pages/identity-providers/">Identity Providers <span>Federation readiness →</span></a>'
identity_live = replace_exact(
    identity_live,
    provider_shortcut,
    "",
    "Identity Providers shortcut",
)

provider_renderer = re.compile(
    r"\n[ \t]*function renderProviders\(\) \{.*?\n[ \t]*\}\n(?=[ \t]*function renderPolicies\(\))",
    re.S,
)
identity_live, renderer_count = provider_renderer.subn("\n", identity_live)
if renderer_count != 1:
    raise RuntimeError(f"ABORT Identity Providers renderer removal: expected 1, found {renderer_count}")
identity_live = replace_exact(
    identity_live,
    '"identity-providers":renderProviders, ',
    "",
    "Identity Providers renderer map",
)


# ---------------------------------------------------------------------------
# 2) Add persistent Policy configuration tables to the existing RBAC DB.
# ---------------------------------------------------------------------------
rbac_api = original["rbac_api"]
schema_anchor = "        # CARTMAN_RBAC_ROOT_OVERVIEW_V2: ROOT is a separate principal, not an RBAC role/permission."
policy_schema = r'''        # CARTMAN_IDENTITY_POLICIES_V1
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

'''
rbac_api = replace_exact(rbac_api, schema_anchor, policy_schema + schema_anchor,
                          "Policy database schema insertion")


# ---------------------------------------------------------------------------
# 3) Policy catalogue, validation, CRUD and audit routes.
# ---------------------------------------------------------------------------
policy_routes = r'''

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
'''
# The original RBAC API was checked for this marker before any edits.
rbac_api = rbac_api.rstrip() + "\n\n" + policy_routes


# ---------------------------------------------------------------------------
# 4) Replace the existing static Policies page with a dedicated live UI.
# ---------------------------------------------------------------------------
policies_page = original["policies_page"]
old_live_script = '<script src="/static/js/modules/identity-security-live.js?v=cartman-identity-live-v1-20261030" defer></script>'
policies_page = replace_exact(
    policies_page,
    old_live_script,
    '<link rel="stylesheet" href="/static/css/modules/policies-management.css?v=cartman-policies-v1">\n    <script src="/static/js/modules/policies-management.js?v=cartman-policies-v1" defer></script>',
    "Policies page dedicated asset loading",
)
policies_page = replace_exact(
    policies_page,
    '<title>Cartman | Cartman | Policies</title>',
    '<title>Cartman | Policies</title>',
    "Policies page title",
)
policies_page = replace_exact(
    policies_page,
    '<section class="workspace-module identity-security" data-identity-security="policies" aria-label="Policies workspace"><div class="isec-loading" role="status">Loading local preview…</div></section>',
    '<section class="workspace-module identity-security" data-policies-workspace aria-label="Conditional access policy management"><div class="isl-loading" role="status">Loading policy configuration…</div></section>',
    "Policies workspace root",
)
policies_page = replace_exact(
    policies_page,
    '<span>Local UI preview · No live data or remote actions</span>',
    '<span>Policy configuration · Enforcement pending</span>',
    "Policies footer status",
)


# ---------------------------------------------------------------------------
# 5) Dedicated policy UI. Uses existing IAM Users, Groups and Departments.
# ---------------------------------------------------------------------------
policy_js = r'''/* CARTMAN_IDENTITY_POLICIES_V1 */
(() => {
    "use strict";

    const root = document.querySelector("[data-policies-workspace]");
    if (!root) return;

    const state = {
        busy: false,
        error: "",
        notice: "",
        policies: [],
        users: [],
        groups: [],
        departments: [],
        catalog: { categories: [], operators: [], states: [] },
        modal: null,
    };

    const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);

    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            cache: "no-store",
            ...options,
            headers: {
                Accept: "application/json",
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(options.headers || {}),
            },
        });
        const raw = await response.text();
        let data = {};
        try { data = raw ? JSON.parse(raw) : {}; }
        catch (_) { data = { detail: raw.slice(0, 300) }; }
        if (!response.ok) {
            const detail = typeof data.detail === "string"
                ? data.detail
                : JSON.stringify(data.detail || data);
            throw new Error(detail || `${response.status} ${response.statusText}`);
        }
        return data;
    }

    const category = key => (state.catalog.categories || []).find(item => item.key === key);
    const operatorLabel = key => (state.catalog.operators || []).find(item => item.key === key)?.label || key;

    function holderCollection(type) {
        if (type === "user") return state.users;
        if (type === "group") return state.groups;
        return state.departments;
    }

    function holderName(type, id) {
        const item = holderCollection(type).find(entry => String(entry.id) === String(id));
        if (!item) return `${type}: ${id}`;
        return item.name || item.display_name || item.email || item.username || String(id);
    }

    function policyHolders(policy) {
        return (policy.assignments || []).map(item =>
            `${item.holder_type}: ${holderName(item.holder_type, item.holder_id)}`
        );
    }

    function badge(text, kind = "neutral") {
        return `<span class="pol-badge ${kind}">${esc(text)}</span>`;
    }

    function metrics() {
        const enabled = state.policies.filter(item => item.status === "Enabled").length;
        const drafts = state.policies.filter(item => item.status === "Draft").length;
        const disabled = state.policies.filter(item => item.status === "Disabled").length;
        return `
            <div class="pol-metrics">
                <article><span>TOTAL POLICIES</span><strong>${state.policies.length}</strong><small>Saved configurations</small></article>
                <article><span>ENABLED</span><strong>${enabled}</strong><small>Configuration enabled · not enforced</small></article>
                <article><span>DRAFTS</span><strong>${drafts}</strong><small>Awaiting activation</small></article>
                <article><span>DISABLED</span><strong>${disabled}</strong><small>Inactive configurations</small></article>
            </div>`;
    }

    function renderRows() {
        if (!state.policies.length) {
            return `<div class="pol-empty"><strong>No policies configured</strong><p>Create a conditional access policy to define its audience, conditions and required action.</p></div>`;
        }
        return state.policies.map(item => {
            const cat = category(item.category);
            const holders = policyHolders(item);
            const conditions = (item.conditions || []).map(rule =>
                `${rule.field} ${operatorLabel(rule.operator)} ${rule.value}`
            );
            const stateKind = item.status === "Enabled" ? "good" : item.status === "Draft" ? "warning" : "muted";
            const actionLabel = (cat?.actions || []).find(action => action.key === item.action)?.label || item.action;
            return `
                <article class="pol-card" data-policy-card data-search="${esc([item.name, item.description, cat?.label, actionLabel, holders.join(" "), conditions.join(" ")].join(" ").toLowerCase())}">
                    <div class="pol-card-head">
                        <div class="pol-card-title"><h3>${esc(item.name)}</h3><p>${esc(item.description || "No description provided.")}</p></div>
                        ${badge(item.status, stateKind)}
                    </div>
                    <div class="pol-meta-grid">
                        <div><span>CATEGORY</span><strong>${esc(cat?.label || item.category)}</strong></div>
                        <div><span>ACTION</span><strong>${esc(actionLabel)}</strong></div>
                        <div><span>PRIORITY</span><strong class="pol-priority">${Number(item.priority)}</strong></div>
                        <div><span>ASSIGNED TO</span><strong>${holders.length} holder(s)</strong></div>
                    </div>
                    <div class="pol-card-detail">
                        <div><span>Applies To</span><div class="pol-chips">${holders.map(value => `<span>${esc(value)}</span>`).join("") || "—"}</div></div>
                        <div><span>Conditions</span><p>${conditions.length ? esc(conditions.join(" · ")) : "No additional conditions · Applies to selected holders"}</p></div>
                    </div>
                    <div class="pol-card-actions">
                        <button type="button" class="pol-btn" data-policy-action="edit" data-policy-id="${esc(item.id)}">Edit</button>
                        <button type="button" class="pol-btn" data-policy-action="toggle" data-policy-id="${esc(item.id)}" ${item.status === "Draft" ? "disabled title=\"Move the policy to Enabled or Disabled in Edit first\"" : ""}>${item.status === "Enabled" ? "Disable" : "Enable"}</button>
                        <button type="button" class="pol-btn danger" data-policy-action="delete" data-policy-id="${esc(item.id)}">Delete</button>
                    </div>
                    <div class="pol-pending-line">${badge("ENFORCEMENT PENDING", "warning")} <span>Configuration is saved; runtime checks are not connected.</span></div>
                </article>`;
        }).join("");
    }

    function renderEditor() {
        if (!state.modal) return "";
        const draft = state.modal;
        const editing = Boolean(draft.id);
        const cat = category(draft.category) || state.catalog.categories[0];
        if (!cat) return "";
        const selectedHolders = new Set(draft.holders.map(item => `${item.holder_type}:${item.holder_id}`));
        const actionOptions = cat.actions.map(item => `<option value="${esc(item.key)}" ${draft.action === item.key ? "selected" : ""}>${esc(item.label)}</option>`).join("");
        const categoryOptions = state.catalog.categories.map(item => `<option value="${esc(item.key)}" ${draft.category === item.key ? "selected" : ""}>${esc(item.label)}</option>`).join("");
        const statusOptions = (state.catalog.states || ["Draft", "Enabled", "Disabled"]).map(value => `<option value="${esc(value)}" ${draft.status === value ? "selected" : ""}>${esc(value)}</option>`).join("");
        const holderGroups = [
            { type: "user", label: "Users", items: state.users },
            { type: "group", label: "Groups", items: state.groups },
            { type: "department", label: "Departments", items: state.departments },
        ];
        const holdersHtml = holderGroups.map(group => `
            <section class="pol-holder-group"><h4>${group.label}</h4>
                ${group.items.length ? group.items.map(item => {
                    const id = String(item.id);
                    const value = `${group.type}:${id}`;
                    const label = item.name || item.display_name || item.email || item.username || id;
                    const sub = item.email && item.name ? `<small>${esc(item.email)}</small>` : "";
                    return `<label class="pol-holder-option"><input type="checkbox" name="policy_holder" value="${esc(value)}" ${selectedHolders.has(value) ? "checked" : ""}><span><strong>${esc(label)}</strong>${sub}</span></label>`;
                }).join("") : `<p class="pol-muted">No records available.</p>`}
            </section>`).join("");
        const conditionsHtml = (draft.conditions || []).map((rule, index) => `
            <div class="pol-condition-row" data-condition-row>
                <select name="condition_field" aria-label="Condition field">
                    ${cat.fields.map(field => `<option value="${esc(field.key)}" ${rule.field === field.key ? "selected" : ""}>${esc(field.label)}</option>`).join("")}
                </select>
                <select name="condition_operator" aria-label="Condition operator">
                    ${(state.catalog.operators || []).map(operator => `<option value="${esc(operator.key)}" ${rule.operator === operator.key ? "selected" : ""}>${esc(operator.label)}</option>`).join("")}
                </select>
                <input name="condition_value" value="${esc(rule.value || "")}" maxlength="500" placeholder="Condition value" aria-label="Condition value">
                <button type="button" class="pol-remove-condition" data-policy-action="condition-remove" data-condition-index="${index}" aria-label="Remove condition">×</button>
            </div>`).join("");

        return `
            <div class="pol-overlay">
                <form class="pol-dialog" data-policy-form role="dialog" aria-modal="true" aria-labelledby="pol-editor-title">
                    <header class="pol-dialog-head"><div><h2 id="pol-editor-title">${editing ? "Edit Policy" : "Create Policy"}</h2><p>Define the policy audience, matching conditions and the action to require.</p></div><button type="button" class="pol-close" data-policy-action="close" aria-label="Close">×</button></header>
                    <div class="pol-editor-body">
                        <section class="pol-editor-section"><h3>1. Policy Details</h3>
                            <label class="pol-field"><span>Policy Name</span><input name="name" maxlength="120" required value="${esc(draft.name)}" placeholder="e.g. L2 Support Secure Remote Access"></label>
                            <label class="pol-field"><span>Description</span><textarea name="description" rows="2" maxlength="1200" placeholder="Describe the policy purpose">${esc(draft.description)}</textarea></label>
                            <div class="pol-two-col">
                                <label class="pol-field"><span>Category</span><select name="category">${categoryOptions}</select></label>
                                <label class="pol-field"><span>Policy State</span><select name="status">${statusOptions}</select></label>
                            </div>
                            <div class="pol-two-col">
                                <label class="pol-field"><span>Action</span><select name="action">${actionOptions}</select></label>
                                <label class="pol-field"><span>Priority</span><input name="priority" type="number" min="1" max="100000" required value="${Number(draft.priority) || 100}"></label>
                            </div>
                        </section>
                        <section class="pol-editor-section"><h3>2. Applies To</h3><p>Select existing IAM users, groups and/or departments. This assigns the policy; it does not create new identities.</p><div class="pol-holder-grid">${holdersHtml}</div></section>
                        <section class="pol-editor-section"><div class="pol-condition-heading"><div><h3>3. Conditions</h3><p>All listed conditions must match. Leave empty to apply to the selected holders without an additional condition.</p></div><button type="button" class="pol-btn" data-policy-action="condition-add">+ Add condition</button></div>
                            <div class="pol-condition-list">${conditionsHtml || `<div class="pol-no-conditions">No conditions added.</div>`}</div>
                        </section>
                        <div class="pol-enforcement-note"><strong>Enforcement Pending</strong><span>This policy will be stored as configuration only. It does not currently change login, session, VPN, device or privileged-action behavior.</span></div>
                    </div>
                    <footer class="pol-dialog-actions"><button type="button" class="pol-btn" data-policy-action="close">Cancel</button><button type="submit" class="pol-btn primary" ${state.busy ? "disabled" : ""}>${editing ? "Save Changes" : "Create Policy"}</button></footer>
                </form>
            </div>`;
    }

    function render() {
        const enabled = state.policies.filter(item => item.status === "Enabled").length;
        root.innerHTML = `
            <div class="isl-app pol-app">
                <section class="isl-hero"><div><div class="isl-eyebrow">CARTMAN / IDENTITY &amp; SECURITY</div><h1>Policies</h1><p>Configure conditional access requirements for existing users, groups and departments.</p></div><span class="pol-hero-state">CONFIGURATION · NOT ENFORCED</span></section>
                ${state.error ? `<div class="isl-alert error">${esc(state.error)}</div>` : ""}
                ${state.notice ? `<div class="isl-alert success">${esc(state.notice)}</div>` : ""}
                <div class="pol-enforcement-banner"><strong>Enforcement Pending</strong><p>Policies can be created, assigned and enabled as configuration. Runtime enforcement is not yet connected to Cartman authentication, sessions, network access, device trust or privileged operations.</p></div>
                ${metrics()}
                <section class="isl-panel"><header class="isl-panel-head"><div><h2>Conditional Access Policies</h2><p>Lower priority numbers are evaluated first; an explicit Deny takes precedence over Allow in the planned evaluator.</p></div><button type="button" class="pol-btn primary" data-policy-action="create">+ Create Policy</button></header>
                    <div class="pol-toolbar"><input type="search" class="pol-search" data-policy-search placeholder="Search policies, holders, categories or actions…"><button type="button" class="pol-btn" data-policy-action="refresh">Refresh</button></div>
                    <div class="pol-list" data-policy-list>${renderRows()}</div>
                </section>
                <div class="pol-footer-note">RBAC remains the permission gate. A policy cannot grant a permission the user's effective RBAC role does not provide. Policy enforcement: PENDING.</div>
                ${renderEditor()}
            </div>`;
    }

    async function load() {
        state.error = "";
        try {
            const [catalog, policies, users, groups, departments] = await Promise.all([
                api("/api/rbac/policies/catalog"),
                api("/api/rbac/policies"),
                api("/api/iam/users"),
                api("/api/iam/groups"),
                api("/api/departments"),
            ]);
            state.catalog = catalog;
            state.policies = policies.items || [];
            state.users = Array.isArray(users) ? users : [];
            state.groups = Array.isArray(groups) ? groups : [];
            state.departments = Array.isArray(departments) ? departments : [];
        } catch (error) {
            state.error = error.message || "Could not load policy management data.";
        }
        render();
    }

    function defaultDraft(policy = null) {
        const cat = category(policy?.category) || state.catalog.categories[0];
        return {
            id: policy?.id || "",
            name: policy?.name || "",
            description: policy?.description || "",
            category: cat?.key || "authentication",
            action: policy?.action || cat?.actions?.[0]?.key || "deny",
            priority: policy?.priority ?? 100,
            status: policy?.status || "Draft",
            holders: (policy?.assignments || []).map(item => ({
                holder_type: item.holder_type,
                holder_id: item.holder_id,
            })),
            conditions: (policy?.conditions || []).map(item => ({ ...item })),
        };
    }

    function collectConditions(form) {
        return Array.from(form.querySelectorAll("[data-condition-row]")).map(row => ({
            field: row.querySelector('[name="condition_field"]').value,
            operator: row.querySelector('[name="condition_operator"]').value,
            value: row.querySelector('[name="condition_value"]').value.trim(),
        }));
    }

    function syncDraft(form) {
        if (!state.modal || !form) return;
        const data = new FormData(form);
        state.modal.name = String(data.get("name") || "");
        state.modal.description = String(data.get("description") || "");
        state.modal.category = String(data.get("category") || state.modal.category);
        state.modal.action = String(data.get("action") || state.modal.action);
        state.modal.priority = Number(data.get("priority")) || 100;
        state.modal.status = String(data.get("status") || "Draft");
        state.modal.holders = Array.from(form.querySelectorAll('[name="policy_holder"]:checked')).map(input => {
            const at = input.value.indexOf(":");
            return { holder_type: input.value.slice(0, at), holder_id: input.value.slice(at + 1) };
        });
        state.modal.conditions = collectConditions(form);
    }

    async function save(form) {
        const data = new FormData(form);
        const holders = Array.from(form.querySelectorAll('[name="policy_holder"]:checked')).map(input => {
            const at = input.value.indexOf(":");
            return { holder_type: input.value.slice(0, at), holder_id: input.value.slice(at + 1) };
        });
        const payload = {
            name: String(data.get("name") || "").trim(),
            description: String(data.get("description") || "").trim(),
            category: String(data.get("category") || ""),
            action: String(data.get("action") || ""),
            priority: Number(data.get("priority")),
            status: String(data.get("status") || "Draft"),
            holders,
            conditions: collectConditions(form),
        };
        if (!holders.length) throw new Error("Select at least one User, Group or Department.");
        if (!payload.name) throw new Error("Policy name is required.");
        if (!Number.isInteger(payload.priority) || payload.priority < 1 || payload.priority > 100000) {
            throw new Error("Priority must be between 1 and 100000.");
        }
        const editing = Boolean(state.modal?.id);
        const url = editing ? `/api/rbac/policies/${encodeURIComponent(state.modal.id)}` : "/api/rbac/policies";
        await api(url, {
            method: editing ? "PUT" : "POST",
            body: JSON.stringify(payload),
        });
        state.modal = null;
        state.notice = editing ? "Policy updated." : "Policy created.";
        await load();
    }

    root.addEventListener("click", async event => {
        const button = event.target.closest("[data-policy-action]");
        if (!button || !root.contains(button) || state.busy) return;
        const action = button.dataset.policyAction;
        try {
            if (action === "create") {
                state.error = "";
                state.modal = defaultDraft();
                render();
            } else if (action === "edit") {
                const item = state.policies.find(policy => policy.id === button.dataset.policyId);
                if (!item) throw new Error("Policy was not found.");
                state.modal = defaultDraft(item);
                render();
            } else if (action === "close") {
                state.modal = null;
                render();
            } else if (action === "refresh") {
                await load();
            } else if (action === "condition-add" || action === "condition-remove") {
                const form = root.querySelector("[data-policy-form]");
                syncDraft(form);
                if (action === "condition-add") {
                    const cat = category(state.modal.category);
                    if (state.modal.conditions.length >= 20) throw new Error("A policy can contain at most 20 conditions.");
                    state.modal.conditions.push({ field: cat.fields[0]?.key || "", operator: "equals", value: "" });
                } else {
                    state.modal.conditions.splice(Number(button.dataset.conditionIndex), 1);
                }
                render();
            } else if (action === "delete") {
                const item = state.policies.find(policy => policy.id === button.dataset.policyId);
                if (!item) throw new Error("Policy was not found.");
                if (!window.confirm(`Delete policy "${item.name}"?`)) return;
                state.busy = true;
                await api(`/api/rbac/policies/${encodeURIComponent(item.id)}`, { method: "DELETE" });
                state.busy = false;
                state.notice = "Policy deleted.";
                await load();
            } else if (action === "toggle") {
                const item = state.policies.find(policy => policy.id === button.dataset.policyId);
                if (!item) throw new Error("Policy was not found.");
                const payload = {
                    name: item.name,
                    description: item.description,
                    category: item.category,
                    action: item.action,
                    priority: item.priority,
                    status: item.status === "Enabled" ? "Disabled" : "Enabled",
                    holders: item.assignments.map(entry => ({ holder_type: entry.holder_type, holder_id: entry.holder_id })),
                    conditions: item.conditions || [],
                };
                state.busy = true;
                await api(`/api/rbac/policies/${encodeURIComponent(item.id)}`, { method: "PUT", body: JSON.stringify(payload) });
                state.busy = false;
                state.notice = `Policy ${payload.status.toLowerCase()} (configuration only).`;
                await load();
            }
        } catch (error) {
            state.busy = false;
            state.error = error.message || "The requested policy operation failed.";
            render();
        }
    });

    root.addEventListener("change", event => {
        const target = event.target;
        if (!target.matches('[data-policy-form] [name="category"]')) return;
        const form = target.form;
        syncDraft(form);
        state.modal.category = target.value;
        const cat = category(target.value);
        if (!cat.actions.some(item => item.key === state.modal.action)) {
            state.modal.action = cat.actions[0]?.key || "deny";
        }
        const allowed = new Set(cat.fields.map(item => item.key));
        state.modal.conditions = state.modal.conditions.map(item => ({
            field: allowed.has(item.field) ? item.field : (cat.fields[0]?.key || ""),
            operator: item.operator,
            value: item.value,
        }));
        render();
    });

    root.addEventListener("submit", async event => {
        const form = event.target.closest("[data-policy-form]");
        if (!form || !root.contains(form)) return;
        event.preventDefault();
        if (state.busy) return;
        state.busy = true;
        state.error = "";
        try {
            await save(form);
        } catch (error) {
            state.error = error.message || "Could not save the policy.";
        }
        state.busy = false;
        render();
    });

    root.addEventListener("input", event => {
        if (!event.target.matches("[data-policy-search]")) return;
        const query = event.target.value.trim().toLowerCase();
        root.querySelectorAll("[data-policy-card]").forEach(card => {
            card.hidden = !String(card.dataset.search || "").includes(query);
        });
    });

    load();
})();
'''

policy_css = r'''/* CARTMAN_IDENTITY_POLICIES_V1 */
.identity-security .pol-app { display:grid; gap:16px; min-width:0; }
.identity-security .pol-hero-state { padding:7px 10px; border:1px solid rgba(251,191,36,.24); border-radius:999px; color:#fbbf24; background:rgba(251,191,36,.07); font-size:9px; font-weight:800; letter-spacing:.5px; }
.identity-security .pol-enforcement-banner { padding:13px 15px; border:1px solid rgba(251,191,36,.22); border-radius:11px; background:rgba(251,191,36,.045); }
.identity-security .pol-enforcement-banner strong { color:#fbbf24; font-size:12px; }
.identity-security .pol-enforcement-banner p { margin:5px 0 0; color:var(--text-muted,#94a3b8); font-size:11px; line-height:1.6; }
.identity-security .pol-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:11px; }
.identity-security .pol-metrics article { min-width:0; padding:14px 16px; border:1px solid var(--border-color,rgba(148,163,184,.18)); border-radius:12px; background:var(--card-bg,#111827); }
.identity-security .pol-metrics span,.identity-security .pol-metrics small { display:block; color:var(--text-muted,#94a3b8); font-size:9px; }
.identity-security .pol-metrics strong { display:block; margin:7px 0 4px; color:var(--text-color,#e5e7eb); font-size:22px; }
.identity-security .pol-toolbar { display:flex; align-items:center; gap:9px; padding:13px 14px; }
.identity-security .pol-search { flex:1 1 250px; min-width:160px; padding:9px 11px; border:1px solid var(--border-color,rgba(148,163,184,.2)); border-radius:8px; background:rgba(148,163,184,.045); color:var(--text-color,#e5e7eb); font:inherit; font-size:11px; }
.identity-security .pol-btn { display:inline-flex; align-items:center; justify-content:center; min-height:33px; padding:7px 11px; border:1px solid var(--border-color,rgba(148,163,184,.2)); border-radius:8px; background:rgba(148,163,184,.055); color:var(--text-color,#e5e7eb); font:inherit; font-size:10px; font-weight:750; cursor:pointer; }
.identity-security .pol-btn.primary { color:#fff; background:#6d5ce8; border-color:#6d5ce8; }
.identity-security .pol-btn.danger { color:#fb7185; border-color:rgba(251,113,133,.25); }
.identity-security .pol-btn:disabled { opacity:.45; cursor:not-allowed; }
.identity-security .pol-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; padding:0 14px 15px; }
.identity-security .pol-card { min-width:0; padding:15px; border:1px solid var(--border-color,rgba(148,163,184,.16)); border-radius:12px; background:var(--card-bg,#111827); }
.identity-security .pol-card[hidden] { display:none; }
.identity-security .pol-card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.identity-security .pol-card-title { min-width:0; }
.identity-security .pol-card-title h3 { margin:0; color:var(--text-color,#e5e7eb); font-size:13px; overflow-wrap:anywhere; }
.identity-security .pol-card-title p { margin:5px 0 0; color:var(--text-muted,#94a3b8); font-size:10px; line-height:1.5; }
.identity-security .pol-badge { display:inline-flex; flex:0 0 auto; padding:5px 8px; border:1px solid transparent; border-radius:999px; font-size:9px; font-weight:800; white-space:nowrap; }
.identity-security .pol-badge.good { color:#34d399; border-color:rgba(52,211,153,.2); background:rgba(52,211,153,.07); }
.identity-security .pol-badge.warning { color:#fbbf24; border-color:rgba(251,191,36,.2); background:rgba(251,191,36,.06); }
.identity-security .pol-badge.muted { color:var(--text-muted,#94a3b8); border-color:var(--border-color,rgba(148,163,184,.16)); background:rgba(148,163,184,.05); }
.identity-security .pol-meta-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:15px; }
.identity-security .pol-meta-grid div { min-width:0; display:grid; gap:4px; }
.identity-security .pol-meta-grid span,.identity-security .pol-card-detail > div > span { color:var(--text-muted,#94a3b8); font-size:9px; text-transform:uppercase; letter-spacing:.04em; }
.identity-security .pol-meta-grid strong { color:var(--text-color,#e5e7eb); font-size:11px; overflow-wrap:anywhere; }
.identity-security .pol-card-detail { display:grid; gap:10px; margin-top:14px; padding-top:12px; border-top:1px solid var(--border-color,rgba(148,163,184,.12)); }
.identity-security .pol-card-detail p { margin:5px 0 0; color:var(--text-muted,#94a3b8); font-size:10px; line-height:1.5; overflow-wrap:anywhere; }
.identity-security .pol-chips { display:flex; flex-wrap:wrap; gap:5px; margin-top:5px; }
.identity-security .pol-chips span { padding:4px 7px; border:1px solid var(--border-color,rgba(148,163,184,.15)); border-radius:6px; color:var(--text-muted,#94a3b8); font-size:9px; }
.identity-security .pol-card-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:7px; margin-top:13px; }
.identity-security .pol-pending-line { display:flex; align-items:center; flex-wrap:wrap; gap:7px; margin-top:12px; }
.identity-security .pol-pending-line > span:last-child { color:var(--text-muted,#94a3b8); font-size:9px; }
.identity-security .pol-footer-note { color:var(--text-muted,#94a3b8); font-size:10px; line-height:1.6; }
.identity-security .pol-empty { padding:30px 18px; text-align:center; }
.identity-security .pol-empty strong { color:var(--text-color,#e5e7eb); font-size:13px; }
.identity-security .pol-empty p { margin:6px 0 0; color:var(--text-muted,#94a3b8); font-size:11px; }
.identity-security .pol-overlay { position:fixed; z-index:1200; inset:0; display:grid; place-items:center; padding:18px; background:rgba(2,6,23,.76); backdrop-filter:blur(5px); }
.identity-security .pol-dialog { display:grid; grid-template-rows:auto minmax(0,1fr) auto; width:min(900px,100%); max-height:calc(100vh - 36px); border:1px solid var(--border-color,rgba(148,163,184,.2)); border-radius:15px; background:var(--card-bg,#111827); color:var(--text-color,#e5e7eb); box-shadow:0 24px 70px rgba(0,0,0,.38); overflow:hidden; }
.identity-security .pol-dialog-head { display:flex; justify-content:space-between; gap:12px; padding:17px 19px; border-bottom:1px solid var(--border-color,rgba(148,163,184,.15)); }
.identity-security .pol-dialog-head h2 { margin:0; font-size:16px; }
.identity-security .pol-dialog-head p { margin:5px 0 0; color:var(--text-muted,#94a3b8); font-size:10px; }
.identity-security .pol-close,.identity-security .pol-remove-condition { width:30px; height:30px; border:1px solid var(--border-color,rgba(148,163,184,.2)); border-radius:8px; background:transparent; color:var(--text-color,#e5e7eb); font-size:18px; cursor:pointer; }
.identity-security .pol-editor-body { display:grid; gap:18px; padding:18px 19px; overflow:auto; }
.identity-security .pol-editor-section { display:grid; gap:11px; padding-bottom:17px; border-bottom:1px solid var(--border-color,rgba(148,163,184,.13)); }
.identity-security .pol-editor-section h3 { margin:0; font-size:13px; }
.identity-security .pol-editor-section > p,.identity-security .pol-condition-heading p { margin:-5px 0 0; color:var(--text-muted,#94a3b8); font-size:10px; line-height:1.55; }
.identity-security .pol-field { display:grid; gap:6px; min-width:0; }
.identity-security .pol-field > span { color:var(--text-muted,#94a3b8); font-size:10px; font-weight:700; }
.identity-security .pol-field input,.identity-security .pol-field textarea,.identity-security .pol-field select,.identity-security .pol-condition-row select,.identity-security .pol-condition-row input { width:100%; min-width:0; padding:9px 10px; border:1px solid var(--border-color,rgba(148,163,184,.2)); border-radius:8px; background:rgba(148,163,184,.045); color:var(--text-color,#e5e7eb); font:inherit; font-size:11px; }
.identity-security .pol-field textarea { resize:vertical; }
.identity-security .pol-field select option,.identity-security .pol-condition-row select option { color:#111827; }
.identity-security .pol-two-col { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.identity-security .pol-holder-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.identity-security .pol-holder-group { display:grid; align-content:start; gap:7px; max-height:190px; overflow:auto; padding:10px; border:1px solid var(--border-color,rgba(148,163,184,.16)); border-radius:9px; }
.identity-security .pol-holder-group h4 { margin:0 0 3px; font-size:11px; }
.identity-security .pol-holder-option { display:flex; align-items:flex-start; gap:7px; min-width:0; padding:4px 0; }
.identity-security .pol-holder-option input { flex:0 0 auto; margin-top:2px; }
.identity-security .pol-holder-option span { display:grid; min-width:0; gap:2px; overflow-wrap:anywhere; }
.identity-security .pol-holder-option strong { font-size:10px; font-weight:600; }
.identity-security .pol-holder-option small,.identity-security .pol-muted { color:var(--text-muted,#94a3b8); font-size:9px; }
.identity-security .pol-condition-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.identity-security .pol-condition-list { display:grid; gap:8px; }
.identity-security .pol-condition-row { display:grid; grid-template-columns:1fr 1fr 1fr 30px; gap:7px; align-items:center; }
.identity-security .pol-no-conditions { padding:13px; border:1px dashed var(--border-color,rgba(148,163,184,.2)); border-radius:8px; color:var(--text-muted,#94a3b8); font-size:10px; text-align:center; }
.identity-security .pol-enforcement-note { display:grid; gap:5px; padding:12px 14px; border:1px solid rgba(251,191,36,.2); border-radius:9px; background:rgba(251,191,36,.045); }
.identity-security .pol-enforcement-note strong { color:#fbbf24; font-size:11px; }
.identity-security .pol-enforcement-note span { color:var(--text-muted,#94a3b8); font-size:10px; line-height:1.5; }
.identity-security .pol-dialog-actions { display:flex; justify-content:flex-end; gap:8px; padding:13px 19px; border-top:1px solid var(--border-color,rgba(148,163,184,.15)); }
@media(max-width:780px) { .identity-security .pol-list { grid-template-columns:1fr; } .identity-security .pol-holder-grid { grid-template-columns:1fr; } .identity-security .pol-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:560px) { .identity-security .pol-two-col,.identity-security .pol-condition-row { grid-template-columns:1fr; } .identity-security .pol-condition-row .pol-remove-condition { justify-self:end; } .identity-security .pol-dialog { max-height:calc(100vh - 16px); } .identity-security .pol-overlay { padding:8px; } .identity-security .pol-dialog-head,.identity-security .pol-editor-body,.identity-security .pol-dialog-actions { padding-left:13px; padding-right:13px; } }
/* END CARTMAN_IDENTITY_POLICIES_V1 */
'''


# ---------------------------------------------------------------------------
# 6) Preflight checks before backup and writes.
# ---------------------------------------------------------------------------
for label, source in (("rbac_api.py", rbac_api),):
    try:
        compile(source, label, "exec")
    except SyntaxError as exc:
        raise RuntimeError(f"ABORT: Python syntax error in {label}: {exc}")

for marker, source, label in [
    ('data-policy-action="create"', policy_js, "policy JS actions"),
    ('data-policy-form', policy_js, "policy JS form"),
    ('/api/rbac/policies/catalog', policy_js, "policy API client"),
    ('Enforcement Pending', policy_js, "pending enforcement disclosure"),
    ('data-policies-workspace', policies_page, "policy page root"),
    ('cartman_rbac_policies', rbac_api, "policy database schema"),
    ('@router.post("/api/rbac/policies", status_code=201)', rbac_api, "policy create route"),
]:
    if marker not in source:
        raise RuntimeError(f"ABORT: {label} marker missing")

if 'Identity Providers' in sidebar or 'identity-providers' in modules or '/pages/identity-providers/' in identity_live:
    raise RuntimeError("ABORT: active Identity Providers references remain in a patched file")

if 'data-identity-security="policies"' in policies_page:
    raise RuntimeError("ABORT: old Policies renderer root still present")

# New asset marker guard
for content in (policy_js, policy_css):
    if MARKER not in content:
        raise RuntimeError("ABORT: generated policy asset missing marker")

updated = {
    PATHS["sidebar"]: sidebar,
    PATHS["modules"]: modules,
    PATHS["identity_live"]: identity_live,
    PATHS["policies_page"]: policies_page,
    PATHS["rbac_api"]: rbac_api,
    NEW_PATHS["policy_js"]: policy_js,
    NEW_PATHS["policy_css"]: policy_css,
}

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = ROOT / ".backups" / f"identity-policies-v1-{stamp}"
backup.mkdir(parents=True, exist_ok=False)

for path in PATHS.values():
    backup_path = backup / path.relative_to(ROOT)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
if PROVIDER_PAGE.exists():
    provider_backup = backup / "retired-identity-providers" / "index.html"
    provider_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROVIDER_PAGE, provider_backup)

written = []
try:
    for path, content in updated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".policy-tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, path)
        written.append(path)

    if PROVIDER_PAGE.exists():
        PROVIDER_PAGE.unlink()
        try:
            PROVIDER_PAGE.parent.rmdir()
        except OSError:
            pass
except Exception:
    for path in written:
        backup_file = backup / path.relative_to(ROOT)
        if backup_file.exists():
            shutil.copy2(backup_file, path)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    provider_backup = backup / "retired-identity-providers" / "index.html"
    if not PROVIDER_PAGE.exists() and provider_backup.exists():
        PROVIDER_PAGE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(provider_backup, PROVIDER_PAGE)
    raise

print("\n====================================================")
print("CARTMAN IDENTITY POLICIES V1 PATCH APPLIED")
print("====================================================")
print("Backup:", backup)
for path in updated:
    print("UPDATED:", path)
print("REMOVED active page:", PROVIDER_PAGE if not PROVIDER_PAGE.exists() else "not removed")
print("Policy enforcement: PENDING (configuration only)")
print("\nNext: run py_compile and restart Uvicorn.")
