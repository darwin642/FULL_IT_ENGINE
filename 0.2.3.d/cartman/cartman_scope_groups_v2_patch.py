#!/usr/bin/env python3
"""Migrate Cartman Named Scopes to group membership + entity assignments.

Run from ~/Documents/cartman:
    .venv/bin/python cartman_scope_groups_v2_patch.py

This is an additive UI/API migration. Existing scope records and the existing
scope_assignments rows are retained. Legacy target columns and scope_rules
storage are intentionally left in SQLite but are no longer used by the UI/API.
Resource API enforcement remains pending.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import re
import shutil

ROOT = Path.cwd()
PATCH_MARKER = "CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2"
OLD_MARKER = "CARTMAN_NAMED_SCOPE_BUILDER_V1"
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


def replace_marked_block(source: str, start_marker: str, end_marker: str,
                         replacement: str, label: str) -> str:
    starts = [m.start() for m in re.finditer(re.escape(start_marker), source)]
    require(len(starts) == 1,
            f"{label}: expected one start marker, found {len(starts)}")
    start = starts[0]
    end = source.find(end_marker, start + len(start_marker))
    require(end >= 0, f"{label}: end marker not found")
    end += len(end_marker)
    return source[:start] + replacement + source[end:]


require((ROOT / "app/main.py").is_file(),
        "run this installer from the Cartman project root")
original: dict[str, str] = {}
for name, path in FILES.items():
    require(path.is_file(), f"missing file: {path}")
    original[name] = path.read_text(encoding="utf-8")
    require(PATCH_MARKER not in original[name],
            f"{name} already contains {PATCH_MARKER}; refusing to reapply")

catalog = original["catalog"]
api = original["api"]
js = original["ui"]
css = original["css"]

# ---------------------------------------------------------------------------
# 1. Remove the field-level permission catalog. CATALOG_VERSION was only
# bumped for that catalog; restore the previous version. No RBAC permissions
# or role grants are changed.
# ---------------------------------------------------------------------------
catalog = replace_marked_block(
    catalog,
    "# CARTMAN_NAMED_SCOPE_BUILDER_V1",
    "# END CARTMAN_NAMED_SCOPE_BUILDER_V1",
    "",
    "remove legacy field-level Scope catalogue",
)
catalog = replace_once(
    catalog, "CATALOG_VERSION = 2", "CATALOG_VERSION = 1",
    "restore RBAC catalogue version",
)

# ---------------------------------------------------------------------------
# 2. Create a many-to-many relation between named Scopes and existing IAM
# groups. A Scope can contain any number of existing groups.
# ---------------------------------------------------------------------------
group_schema = '''        # CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2: groups included in each named Scope.
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

'''
root_init_anchor = (
    "        # CARTMAN_RBAC_ROOT_OVERVIEW_V2: ROOT is a separate principal, "
    "not an RBAC role/permission."
)
api = replace_once(
    api, root_init_anchor, group_schema + root_init_anchor,
    "initialize Scope-to-group relation table",
)

# Replace only the old named Scope route block; keep the schema already
# created by the previous patch and the ROOT bootstrap code untouched.
old_routes_start = "\n# CARTMAN_NAMED_SCOPE_BUILDER_V1\n_SCOPE_TARGET_TYPES"
old_routes_end = "# END CARTMAN_NAMED_SCOPE_BUILDER_V1"
api = replace_marked_block(
    api,
    old_routes_start,
    old_routes_end,
    "\n" + r'''# CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2
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

# END CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2''',
    "replace legacy named Scope API routes",
)

# ---------------------------------------------------------------------------
# 3. Update the Users & Groups page. The Scope tab edits group membership;
# Users, Groups and Departments each get their own Scope assignment panel.
# ---------------------------------------------------------------------------
state_old = """            scopeItems: [],
            scopeCatalog: { fields: [] },
            scopeError: '',
            scopeModal: null"""
state_new = """            scopeItems: [],
            scopeError: '',
            scopeModal: null,
            entityScopeIds: [],
            selectedDepartmentId: ''"""
js = replace_once(js, state_old, state_new, "replace field-permission Scope state")

# Place the independent entity assignment editor below the normal tab content.
require(js.count("${tabContent}") == 1,
        "expected one ${tabContent} slot in the Users & Groups render template")
js = js.replace(
    "${tabContent}",
    "${tabContent}\n                            ${renderEntityScopePanel()}",
    1,
)

# Rewrite all old field-level Scope renderers and the legacy catalog loader.
new_scope_ui = r'''        // CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2
        function scopeEntityName(type, id) {
            const source = type === "user" ? state.users
                : type === "group" ? state.allGroups
                : state.departments;
            const item = source.find(entry => String(entry.id) === String(id));
            if (!item) return String(id);
            return item.name || item.display_name || item.email || item.username || String(id);
        }

        function currentScopeHolder() {
            if (state.tab === "users") {
                const item = selectedUser();
                return item ? { type: "user", id: String(item.id), name: item.name || item.email } : null;
            }
            if (state.tab === "groups") {
                const item = selectedGroup();
                return item ? { type: "group", id: String(item.id), name: item.name } : null;
            }
            if (state.tab === "departments") {
                const item = state.departments.find(
                    department => String(department.id) === String(state.selectedDepartmentId)
                ) || state.departments[0];
                return item ? { type: "department", id: String(item.id), name: item.name } : null;
            }
            return null;
        }

        function renderEntityScopePanel() {
            if (state.loading || state.tab === "scopes") return "";
            const holder = currentScopeHolder();
            if (!holder) return "";

            const selected = new Set((state.entityScopeIds || []).map(String));
            const departmentSelector = state.tab === "departments" ? `
                <label class="iam-dir-selector scope-assignment-department-select">
                    <span>Department</span>
                    <select class="isec-select" data-iam-scope-department-select>
                        ${state.departments.map(item => `
                            <option value="${esc(item.id)}"
                                ${String(item.id) === String(holder.id) ? "selected" : ""}>
                                ${esc(item.name)}
                            </option>
                        `).join("")}
                    </select>
                </label>
            ` : "";

            const options = state.scopeItems.map(scope => `
                <label class="scope-assignment-option">
                    <input type="checkbox" name="scope_ids"
                        value="${esc(scope.id)}"
                        ${selected.has(String(scope.id)) ? "checked" : ""}>
                    <span>
                        <strong>${esc(scope.name)}</strong>
                        <small>${(scope.groups || []).length} included group(s)</small>
                    </span>
                </label>
            `).join("");

            return `
                <section class="iam-dir-detail-card scope-assignment-panel">
                    <form data-iam-form="save-entity-scopes"
                        data-holder-type="${esc(holder.type)}"
                        data-holder-id="${esc(holder.id)}">
                        <div class="iam-dir-section-heading">
                            <div>
                                <h3>Scope Assignments</h3>
                                <p>
                                    Choose which named Scopes are assigned to this
                                    ${esc(holder.type)}. This is separate from RBAC roles.
                                </p>
                            </div>
                            <span class="scope-assignment-count">${selected.size} assigned</span>
                        </div>
                        ${departmentSelector}
                        ${state.scopeError
                            ? `<div class="iam-dir-error" role="alert">${esc(state.scopeError)}</div>`
                            : ""}
                        ${state.scopeItems.length
                            ? `<div class="scope-assignment-options">${options}</div>`
                            : `<div class="iam-dir-empty-inline">No Scopes have been created yet. Create one in the Scopes tab first.</div>`}
                        <div class="scope-assignment-footer">
                            <span>Enforcement Pending · Configuration only</span>
                            <button type="submit" class="isec-btn primary"
                                ${state.saving || !state.scopeItems.length ? "disabled" : ""}>
                                Save Scope Assignments
                            </button>
                        </div>
                    </form>
                </section>
            `;
        }

        function renderScopesContent() {
            const items = state.scopeItems || [];
            const cards = items.map(scope => {
                const groups = scope.groups || [];
                const assignments = scope.assignments || [];
                const groupMarkup = groups.length
                    ? groups.map(group => `
                        <span class="scope-group-chip">${esc(group.name)}</span>
                    `).join("")
                    : `<span class="scope-policy-muted">No groups included. This Scope currently contains no group targets.</span>`;
                const assignedMarkup = assignments.length
                    ? assignments.map(item => `
                        <span class="scope-assigned-chip">
                            ${esc(item.holder_type)} · ${esc(scopeEntityName(item.holder_type, item.holder_id))}
                        </span>
                    `).join("")
                    : `<span class="scope-policy-muted">Not assigned to any user, group or department.</span>`;

                return `
                    <article class="scope-policy-card">
                        <div class="scope-policy-card-head">
                            <div>
                                <h3>${esc(scope.name)}</h3>
                                <p>${esc(scope.description || "No description provided.")}</p>
                            </div>
                            <span class="scope-policy-status">${groups.length} group(s)</span>
                        </div>
                        <div class="scope-v2-section">
                            <span>Groups included in this Scope</span>
                            <div class="scope-v2-chips">${groupMarkup}</div>
                        </div>
                        <div class="scope-v2-section">
                            <span>Assigned to</span>
                            <div class="scope-v2-chips">${assignedMarkup}</div>
                        </div>
                        <div class="scope-policy-actions">
                            <button type="button" class="isec-btn"
                                data-iam-action="edit-scope"
                                data-scope-id="${esc(scope.id)}">Manage Groups</button>
                            <button type="button" class="isec-btn danger"
                                data-iam-action="delete-scope"
                                data-scope-id="${esc(scope.id)}">Delete</button>
                        </div>
                    </article>
                `;
            }).join("");

            return `
                <div class="scope-policy-workspace">
                    <div class="scope-policy-notice">
                        <strong>Enforcement Pending</strong>
                        <p>
                            A Scope defines which existing IAM groups are included.
                            Assign the Scope to an individual user, group or department
                            from its respective tab. These settings are configuration
                            only until resource APIs enforce them.
                        </p>
                    </div>
                    <div class="scope-policy-intro">
                        <div>
                            <h3>Scopes</h3>
                            <p>Create a named collection of existing IAM groups. Add or remove groups individually.</p>
                        </div>
                        <span>${items.length} configured</span>
                    </div>
                    ${state.scopeError
                        ? `<div class="iam-dir-error" role="alert">${esc(state.scopeError)}</div>`
                        : ""}
                    ${items.length
                        ? `<div class="scope-policy-list">${cards}</div>`
                        : `<div class="iam-dir-empty"><strong>No Scopes created yet</strong><p>Create a Scope, then add the existing IAM groups it should contain.</p></div>`}
                </div>
            `;
        }

        function renderScopeModal() {
            if (!state.scopeModal) return "";
            const scope = state.scopeModal.scope || null;
            const selected = new Set((scope?.group_ids || []).map(String));
            const groups = (state.allGroups || []).map(group => `
                <label class="scope-v2-group-option">
                    <input type="checkbox" name="group_ids"
                        value="${esc(group.id)}"
                        ${selected.has(String(group.id)) ? "checked" : ""}>
                    <span>
                        <strong>${esc(group.name)}</strong>
                        <small>${Number(group.members || 0)} member(s)${group.department_name ? ` · ${esc(group.department_name)}` : ""}</small>
                    </span>
                </label>
            `).join("");

            return `
                <div class="iam-dir-modal-backdrop scope-policy-backdrop">
                    <form class="iam-dir-modal scope-policy-modal"
                        data-iam-form="save-scope" role="dialog" aria-modal="true"
                        aria-labelledby="scope-policy-modal-title">
                        <div class="iam-dir-modal-header">
                            <div>
                                <h2 id="scope-policy-modal-title">${scope ? "Manage Scope" : "Create Scope"}</h2>
                                <p class="iam-dir-modal-subtitle">
                                    A Scope is a named set of existing IAM groups.
                                    It does not define RBAC permissions.
                                </p>
                            </div>
                            <button type="button" class="iam-dir-close"
                                data-iam-action="close-scope-modal" aria-label="Close">×</button>
                        </div>
                        <div class="scope-v2-editor">
                            <label class="iam-dir-field">
                                <span>Scope Name</span>
                                <input name="name" maxlength="100" required
                                    value="${esc(scope?.name || "") }"
                                    placeholder="e.g. Support Scope">
                            </label>
                            <label class="iam-dir-field">
                                <span>Description</span>
                                <textarea name="description" rows="2" maxlength="1000"
                                    placeholder="Describe which teams this Scope groups together">${esc(scope?.description || "")}</textarea>
                            </label>
                            <section class="scope-v2-group-section">
                                <div>
                                    <h3>Groups included in this Scope</h3>
                                    <p>Add or remove existing IAM groups individually. No new groups are created here.</p>
                                </div>
                                <div class="scope-v2-group-list">
                                    ${groups || `<p class="scope-policy-muted">No IAM groups are available.</p>`}
                                </div>
                            </section>
                            <div class="scope-policy-notice">
                                <strong>Enforcement Pending</strong>
                                <p>These Scope relationships are saved as configuration. Resource API filtering is not active yet.</p>
                            </div>
                        </div>
                        <div class="iam-dir-modal-actions">
                            <button type="button" class="isec-btn"
                                data-iam-action="close-scope-modal">Cancel</button>
                            <button type="submit" class="isec-btn primary">
                                ${scope ? "Save Scope" : "Create Scope"}
                            </button>
                        </div>
                    </form>
                </div>
            `;
        }

        async function loadScopes() {
            state.scopeError = "";
            try {
                const response = await api("/api/rbac/scopes");
                state.scopeItems = response.items || [];
            } catch (error) {
                state.scopeItems = [];
                state.scopeError = error.message || "Could not load Scopes.";
            }
        }

        async function loadEntityScopes() {
            const holder = currentScopeHolder();
            if (!holder) {
                state.entityScopeIds = [];
                return;
            }
            try {
                const response = await api(
                    `/api/rbac/scope-assignments/${encodeURIComponent(holder.type)}/${encodeURIComponent(holder.id)}`
                );
                state.entityScopeIds = response.scope_ids || [];
            } catch (error) {
                state.entityScopeIds = [];
                state.scopeError = error.message || "Could not load Scope assignments.";
            }
        }
        // END CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2
'''
js = replace_marked_block(
    js,
    "// CARTMAN_NAMED_SCOPE_BUILDER_V1",
    "// END CARTMAN_NAMED_SCOPE_BUILDER_V1",
    new_scope_ui,
    "replace old field-permission Scope UI",
)

# Replace old Scope CRUD click actions while preserving the existing refresh
# and all other Users / Groups / Departments actions.
action_start = '            if (action === "create-scope") {'
action_end = '            if (action === "refresh") {'
action_positions = [m.start() for m in re.finditer(re.escape(action_start), js)]
require(len(action_positions) == 1,
        f"Scope action start: expected one match, found {len(action_positions)}")
action_pos = action_positions[0]
refresh_pos = js.find(action_end, action_pos)
require(refresh_pos >= 0, "Scope action block end (refresh) not found")
new_actions = r'''            if (action === "create-scope") {
                state.error = "";
                state.scopeError = "";
                state.scopeModal = { scope: null };
                render();
                return;
            }

            if (action === "edit-scope") {
                const scope = state.scopeItems.find(item => item.id === button.dataset.scopeId);
                if (!scope) throw new Error("Scope was not found.");
                state.scopeError = "";
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
                if (!window.confirm(`Delete the Scope "${scope.name}" and all of its assignments?`)) return;
                state.saving = true;
                try {
                    await api(`/api/rbac/scopes/${encodeURIComponent(scope.id)}`, { method: "DELETE" });
                    await loadScopes();
                    await loadEntityScopes();
                    state.saving = false;
                    notify("Scope deleted successfully.");
                } catch (error) {
                    state.saving = false;
                    throw error;
                }
                return;
            }

'''
js = js[:action_pos] + new_actions + js[refresh_pos:]

# The old field-permission form is replaced with name + group_ids only. Also
# add a distinct save handler for assigning named Scopes to the current entity.
save_start_marker = '                if (formType === "save-scope") {'
create_group_marker = '                if (formType === "create-group") {'
save_start_positions = [m.start() for m in re.finditer(re.escape(save_start_marker), js)]
require(len(save_start_positions) == 1,
        f"old Scope submit handler: expected one match, found {len(save_start_positions)}")
save_start = save_start_positions[0]
create_group_pos = js.find(create_group_marker, save_start)
require(create_group_pos >= 0, "create-group form handler after Scope handler not found")
new_submit = r'''                if (formType === "save-scope") {
                    const formData = new FormData(form);
                    const groupIds = Array.from(
                        form.querySelectorAll('input[name="group_ids"]:checked')
                    ).map(input => input.value);
                    const payload = {
                        name: String(formData.get("name") || "").trim(),
                        description: String(formData.get("description") || "").trim(),
                        group_ids: groupIds
                    };
                    if (!payload.name) throw new Error("Scope name is required.");

                    const editing = state.scopeModal?.scope;
                    const endpoint = editing
                        ? `/api/rbac/scopes/${encodeURIComponent(editing.id)}`
                        : "/api/rbac/scopes";
                    await api(endpoint, {
                        method: editing ? "PUT" : "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });
                    state.scopeModal = null;
                    await loadScopes();
                    state.saving = false;
                    notify(editing ? "Scope updated successfully." : "Scope created successfully.");
                    return;
                }

                if (formType === "save-entity-scopes") {
                    const holderType = form.dataset.holderType;
                    const holderId = form.dataset.holderId;
                    if (!holderType || !holderId) {
                        throw new Error("The selected user, group or department is missing.");
                    }
                    const scopeIds = Array.from(
                        form.querySelectorAll('input[name="scope_ids"]:checked')
                    ).map(input => input.value);
                    const response = await api(
                        `/api/rbac/scope-assignments/${encodeURIComponent(holderType)}/${encodeURIComponent(holderId)}`,
                        {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ scope_ids: scopeIds })
                        }
                    );
                    state.entityScopeIds = response.scope_ids || [];
                    await loadScopes();
                    state.saving = false;
                    notify("Scope assignments saved.");
                    return;
                }

'''
js = js[:save_start] + new_submit + js[create_group_pos:]

# The department picker is part of the assignment panel. Load its assignments
# whenever a different department is selected.
change_anchor = '            if (target.matches("[data-iam-user-select]")) {'
change_branch = r'''            if (target.matches("[data-iam-scope-department-select]")) {
                state.selectedDepartmentId = target.value;
                await loadEntityScopes();
                render();
                return;
            }

'''
js = replace_once(js, change_anchor, change_branch + change_anchor,
                   "department Scope assignment selector")

# loadSelection() serves both user and group selection changes. Append its
# entity-scope lookup before the next load() function.
load_marker = "        async function load() {"
require(js.count(load_marker) == 1,
        "expected exactly one main load() function")
close_pattern = "\n        }\n        async function load() {"
js = replace_once(
    js,
    close_pattern,
    "\n            await loadEntityScopes();\n        }\n        async function load() {",
    "load Scope assignments with selected user/group",
)

# Preserve the selected department across page renders and default to the
# first existing department when none has been selected.
js = replace_once(
    js,
    "                state.departments = departments;",
    """                state.departments = departments;
                if (!state.departments.some(item => String(item.id) === String(state.selectedDepartmentId))) {
                    state.selectedDepartmentId = state.departments[0]?.id || "";
                }""",
    "initialize selected department for Scope assignment",
)

# ---------------------------------------------------------------------------
# 4. Replace old Scope styles with styles for group membership and entity
# assignment panels. Other Identity & Security styles remain untouched.
# ---------------------------------------------------------------------------
new_scope_css = r'''/* CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2 */
.identity-security .scope-policy-workspace { display: grid; gap: 18px; }
.identity-security .scope-policy-notice {
    display: grid; gap: 5px; padding: 14px 16px;
    border: 1px solid var(--isec-line); border-radius: 12px;
    background: var(--isec-panel-soft, var(--isec-panel));
}
.identity-security .scope-policy-notice strong { color: var(--isec-text); font-size: 13px; }
.identity-security .scope-policy-notice p { margin: 0; color: var(--isec-muted); font-size: 12px; line-height: 1.55; }
.identity-security .scope-policy-intro { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.identity-security .scope-policy-intro h3,
.identity-security .scope-policy-card h3 { margin: 0; color: var(--isec-text); font-size: 15px; }
.identity-security .scope-policy-intro p,
.identity-security .scope-policy-card-head p { margin: 5px 0 0; color: var(--isec-muted); font-size: 12px; line-height: 1.5; }
.identity-security .scope-policy-intro > span,
.identity-security .scope-policy-status { color: var(--isec-muted); font-size: 11px; white-space: nowrap; }
.identity-security .scope-policy-list { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }
.identity-security .scope-policy-card { min-width: 0; padding: 16px; border: 1px solid var(--isec-line); border-radius: 13px; background: var(--isec-panel); }
.identity-security .scope-policy-card-head { display: flex; justify-content: space-between; gap: 12px; }
.identity-security .scope-v2-section { display: grid; gap: 8px; margin-top: 15px; }
.identity-security .scope-v2-section > span { color: var(--isec-muted); font-size: 11px; font-weight: 600; }
.identity-security .scope-v2-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.identity-security .scope-group-chip,
.identity-security .scope-assigned-chip { padding: 5px 8px; border: 1px solid var(--isec-line); border-radius: 7px; color: var(--isec-muted); font-size: 10px; }
.identity-security .scope-policy-muted { color: var(--isec-muted); font-size: 12px; }
.identity-security .scope-policy-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--isec-line); }
.identity-security .scope-policy-actions .danger { color: var(--isec-danger, #d45d65); }
.identity-security .scope-policy-backdrop { z-index: 1000; }
.identity-security .scope-policy-modal { width: min(760px,100%); max-height: calc(100vh - 40px); overflow: auto; }
.identity-security .scope-v2-editor { display: grid; gap: 18px; padding: 18px 0; }
.identity-security .scope-v2-group-section { display: grid; gap: 12px; }
.identity-security .scope-v2-group-section h3 { margin: 0; color: var(--isec-text); font-size: 14px; }
.identity-security .scope-v2-group-section p { margin: 5px 0 0; color: var(--isec-muted); font-size: 12px; line-height: 1.5; }
.identity-security .scope-v2-group-list { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; max-height: 340px; overflow: auto; padding: 10px; border: 1px solid var(--isec-line); border-radius: 10px; }
.identity-security .scope-v2-group-option,
.identity-security .scope-assignment-option { display: flex; align-items: flex-start; gap: 9px; min-width: 0; padding: 9px; border: 1px solid var(--isec-line); border-radius: 9px; color: var(--isec-text); font-size: 11px; }
.identity-security .scope-v2-group-option input,
.identity-security .scope-assignment-option input { flex: 0 0 auto; margin-top: 2px; }
.identity-security .scope-v2-group-option span,
.identity-security .scope-assignment-option span { display: grid; min-width: 0; gap: 4px; overflow-wrap: anywhere; }
.identity-security .scope-v2-group-option strong,
.identity-security .scope-assignment-option strong { color: var(--isec-text); font-size: 12px; }
.identity-security .scope-v2-group-option small,
.identity-security .scope-assignment-option small { color: var(--isec-muted); font-size: 10px; }
.identity-security .scope-assignment-panel { margin-top: 16px; }
.identity-security .scope-assignment-panel form { display: grid; gap: 14px; }
.identity-security .scope-assignment-panel .iam-dir-section-heading { align-items: center; }
.identity-security .scope-assignment-count { color: var(--isec-muted); font-size: 11px; white-space: nowrap; }
.identity-security .scope-assignment-options { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.identity-security .scope-assignment-department-select { max-width: 360px; }
.identity-security .scope-assignment-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 12px; border-top: 1px solid var(--isec-line); }
.identity-security .scope-assignment-footer > span { color: var(--isec-muted); font-size: 10px; }
@media (max-width: 760px) {
    .identity-security .scope-policy-list,
    .identity-security .scope-v2-group-list,
    .identity-security .scope-assignment-options { grid-template-columns: minmax(0,1fr); }
    .identity-security .scope-assignment-footer { align-items: stretch; flex-direction: column; }
}
/* END CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2 */'''
css = replace_marked_block(
    css,
    "/* CARTMAN_NAMED_SCOPE_BUILDER_V1 */",
    "/* END CARTMAN_NAMED_SCOPE_BUILDER_V1 */",
    new_scope_css,
    "replace field-permission Scope styles",
)

# ---------------------------------------------------------------------------
# 5. Preflight all modified content before writing any source file.
# ---------------------------------------------------------------------------
for label, source in (("rbac_catalog.py", catalog), ("rbac_api.py", api)):
    try:
        compile(source, label, "exec")
    except SyntaxError as exc:
        raise RuntimeError(f"ABORT: Python syntax error in {label}: {exc}")

for marker in (
    "cartman_rbac_scope_groups",
    "get_entity_scope_assignments",
    "update_entity_scope_assignments",
    "enforcement_enabled",
):
    require(marker in api, f"backend marker missing after migration: {marker}")

for marker in (
    'data-iam-action="tab-scopes"',
    "function renderScopesContent()",
    "function renderScopeModal()",
    "function renderEntityScopePanel()",
    "async function loadEntityScopes()",
    'formType === "save-entity-scopes"',
    'formType === "save-scope"',
    "/api/rbac/scope-assignments/",
    "group_ids: groupIds",
):
    require(marker in js, f"UI marker missing after migration: {marker}")

for forbidden in (
    "Field-Level Permissions",
    "scopeCatalog.fields",
    "field_${field.key}",
    "access_level: Number(formData.get(`field_",
):
    require(forbidden not in js,
            f"legacy permission UI text/code remains: {forbidden}")

for marker in (
    'data-iam-action="tab-users"',
    'data-iam-action="tab-groups"',
    'data-iam-action="tab-departments"',
    'if (formType === "create-group")',
    'if (formType === "manage-members")',
):
    require(marker in js, f"existing IAM feature marker missing: {marker}")

require(PATCH_MARKER in api and PATCH_MARKER in js and PATCH_MARKER in css,
        "new migration marker missing from one or more files")

updated = {
    "catalog": catalog,
    "api": api,
    "ui": js,
    "css": css,
}

# ---------------------------------------------------------------------------
# 6. Back up all four files, then atomically replace each one. If a write fails,
# restore every file already replaced from the backup.
# ---------------------------------------------------------------------------
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = ROOT / ".backups" / f"scope-groups-v2-{stamp}"
backup_dir.mkdir(parents=True, exist_ok=False)

for name, path in FILES.items():
    shutil.copy2(path, backup_dir / path.name)

written: list[str] = []
try:
    for name, path in FILES.items():
        temp_path = path.with_name(path.name + ".scope-v2-tmp")
        temp_path.write_text(updated[name], encoding="utf-8")
        os.replace(temp_path, path)
        written.append(name)
except Exception:
    for name in written:
        shutil.copy2(backup_dir / FILES[name].name, FILES[name])
    raise

print("\n====================================================")
print("CARTMAN SCOPE GROUP ASSIGNMENTS V2 APPLIED")
print("====================================================")
print("Backup:", backup_dir)
for name, path in FILES.items():
    print(f"UPDATED {name}: {path}")
print("\nScope definition: name + description + existing IAM group IDs")
print("Scope assignment: individual user / group / department")
print("Legacy scope_rules table: retained but unused (no data dropped)")
print("Resource API enforcement: PENDING (configuration only)")
print("Python source compilation: PASSED")
print("UI preflight checks: PASSED")
