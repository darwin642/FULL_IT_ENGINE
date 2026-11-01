/* CARTMAN_IAM_ROLE_ASSIGNMENT_V1 */
(() => {
    "use strict";

    const roots = document.querySelectorAll(
        '.workspace-module.identity-security[data-identity-security="users-groups"]'
    );

    roots.forEach(init);

    function init(root) {
        const state = {
            users: [],
            groups: [],
            allGroups: [],
            departments: [],
            roles: [],
            modal: null,
            accounts: [],
            tab: "users",
            selectedUserId: "",
            selectedGroupId: "",
            groupFilterMode: "user",
            userAssignments: [],
            userInheritedRoles: [],
            groupAssignments: [],
            loading: true,
            saving: false,
            connected: false,
            error: "",
            warning: null,
            toast: "",
            toastTimer: null,
            scopeItems: [],
            scopeError: '',
            scopeModal: null,
            entityScopeIds: [],
            selectedDepartmentId: ''
        };

        function availableScopes() {
            const values = new Set(["General"]);
            const groups = Array.isArray(state.allGroups)
                ? state.allGroups
                : (state.groups || []);
        
            groups.forEach(group => {
                const value = String(group.scope || "").trim();
                if (value) values.add(value);
            });
        
            return [
                "General",
                ...Array.from(values)
                    .filter(value => value !== "General")
                    .sort((a, b) => a.localeCompare(b))
            ];
        }


        const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[c]);

        const $ = (selector, base = root) => base.querySelector(selector);

        async function api(url, options = {}) {
            const response = await fetch(url, {
                cache: "no-store",
                ...options,
                headers: {
                    Accept: "application/json",
                    ...(options.headers || {})
                }
            });

            const body = await response.text();
            let data = null;

            try {
                data = body ? JSON.parse(body) : null;
            } catch {
                data = null;
            }

            if (!response.ok) {
                const detail = data?.detail;
                const message = typeof detail === "string"
                    ? detail
                    : detail?.message || data?.message ||
                      `Request failed (${response.status})`;

                const error = new Error(message);
                error.detail = detail;
                error.status = response.status;
                throw error;
            }

            return data;
        }

        const badge = (value, kind = "") =>
            `<span class="isec-badge ${esc(kind)}">${esc(value)}</span>`;

        const statusKind = value => ({
            Active: "good",
            Invited: "warn",
            Suspended: "bad",
            Disabled: "bad",
            Review: "warn"
        }[value] || "");

        const selectedUser = () =>
            state.users.find(item => item.id === state.selectedUserId) || null;

        // The IT system group remains in the database and in allGroups.
        // It is hidden only from the normal Groups tab list.
        const selectedGroup = () =>
            state.allGroups.find(item => item.id === state.selectedGroupId) ||
            state.groups.find(item => item.id === state.selectedGroupId) ||
            null;

        function groupsForSelection() {
            const source = state.tab === "departments"
                ? state.allGroups
                : state.groups;

            if (state.groupFilterMode === "all") {
                return source;
            }

            const user = selectedUser();
            if (!user) return [];

            return source.filter(group =>
                Array.isArray(group.memberIds) &&
                group.memberIds.includes(user.id)
            );
        }

        function syncSelectedGroup() {
            const available = groupsForSelection();

            if (!available.some(group => group.id === state.selectedGroupId)) {
                state.selectedGroupId = available[0]?.id || "";
            }
        }
        function accountFor(user) {
            if (!user) return null;

            return state.accounts.find(account =>
                account.iam_user_id === user.id
            ) || state.accounts.find(account =>
                String(account.username || "").trim().toLowerCase() ===
                String(user.username || "").trim().toLowerCase()
            ) || null;
        }

        function metric(label, value, foot) {
            return `
                <article class="isec-metric">
                    <span class="isec-metric-label">${esc(label)}</span>
                    <div class="isec-metric-value">${esc(value)}</div>
                    <span class="isec-metric-foot">${esc(foot)}</span>
                </article>`;
        }

        function readOnlyField(label, value) {
            return `
                <div class="iam-dir-detail-field">
                    <span>${esc(label)}</span>
                    <strong>${esc(value || "—")}</strong>
                </div>`;
        }

        function assignmentRows(assignments, kind, canRemove) {
            if (!assignments.length) {
                return `<div class="iam-dir-empty-inline">
                    No roles assigned yet.
                </div>`;
            }

            return assignments.map(item => {
                const assignmentId = item.id || item.assignment_id;
                const scope = item.scope_type === "global"
                    ? "Global"
                    : `${item.scope_type || "Scope"} · ${item.scope_id || "—"}`;

                return `
                    <div class="iam-dir-assignment-row">
                        <div class="iam-dir-assignment-copy">
                            <strong>${esc(item.role_name || item.role_key)}</strong>
                            <span>${esc(item.role_key || "")}</span>
                            <small>
                                ${esc(scope)}
                                · Assigned by ${esc(item.assigned_by || "—")}
                            </small>
                        </div>
                        <div class="iam-dir-assignment-action">
                            ${badge("Assigned", "good")}
                            ${canRemove ? `
                                <button type="button" class="isec-btn danger"
                                    data-iam-action="remove-role"
                                    data-kind="${esc(kind)}"
                                    data-assignment-id="${esc(assignmentId)}">
                                    Remove
                                </button>` : ""}
                        </div>
                    </div>`;
            }).join("");
        }

        function rolePanel(kind, assignments, canAdd, canRemove, note = "") {
            const assignedGlobal = new Set(assignments
                .filter(item => kind === "group" ||
                    (item.scope_type === "global" && !item.scope_id))
                .map(item => item.role_id));

            const available = state.roles.filter(role =>
                !assignedGlobal.has(role.id)
            );

            const assignmentControls = canAdd ? `
                <div class="iam-dir-role-controls">
                    <label>
                        <span>Available RBAC roles</span>
                        <select class="isec-select"
                            data-iam-role-select="${kind}"
                            ${available.length ? "" : "disabled"}>
                            <option value="">Select a role…</option>
                            ${available.map(role => `
                                <option value="${esc(role.id)}">
                                    ${esc(role.name)}
                                    ${role.is_system ? " · Built-in" : ""}
                                </option>`).join("")}
                        </select>
                    </label>
                    <button type="button" class="isec-btn primary"
                        data-iam-action="assign-role" data-kind="${kind}"
                        ${available.length ? "" : "disabled"}>
                        Assign &amp; Save
                    </button>
                </div>` : "";

            return `
                <section class="iam-dir-role-section">
                    <div class="iam-dir-role-heading">
                        <div>
                            <h3>Assigned Roles</h3>
                            <p>Roles defined in Identity &amp; Security → Roles &amp; Permissions.</p>
                        </div>
                        ${badge(`${assignments.length} assigned`)}
                    </div>

                    ${note ? `<div class="iam-dir-role-note">${esc(note)}</div>` : ""}

                    ${assignmentControls}

                    ${!state.roles.length
                        ? `<div class="iam-dir-empty-inline">
                            No active RBAC roles exist. Create roles in
                            Roles &amp; Permissions first.
                           </div>`
                        : ""}

                    <div class="iam-dir-assignment-list">
                        ${assignmentRows(assignments, kind, canRemove)}
                    </div>
                </section>`;
        }

        function inheritedRoleRows() {
            if (!state.userInheritedRoles.length) {
                return `<div class="iam-dir-empty-inline">
                    No group-inherited roles.
                </div>`;
            }

            return state.userInheritedRoles.map(item => {
                const active = item.group_status === "Active";

                return `
                    <div class="iam-dir-assignment-row">
                        <div class="iam-dir-assignment-copy">
                            <strong>${esc(item.role_name)}</strong>
                            <span>${esc(item.role_key)}</span>
                            <small>Inherited from group: ${esc(item.group_name)}</small>
                        </div>
                        ${badge(
                            active ? "Active group" : "Inactive group",
                            active ? "good" : "warn"
                        )}
                    </div>`;
            }).join("");
        }

        function renderUserContent() {
            const user = selectedUser();

            if (!user) {
                return `<div class="iam-dir-empty">
                    <strong>No IAM users available</strong>
                    <p>There are no existing IAM users to select.</p>
                </div>`;
            }

            const account = accountFor(user);
            const isRoot = Boolean(Number(account?.is_root));
            const accountActive = Boolean(Number(account?.is_active));

            const details = `
                <div class="iam-dir-detail-grid">
                    ${readOnlyField("Display name", user.name)}
                    ${readOnlyField("Email address", user.email)}
                    ${readOnlyField("Username", user.username)}
                    ${readOnlyField("Department", user.department)}
                    <div class="iam-dir-detail-field">
                        <span>IAM account status</span>
                        <strong>${badge(user.status, statusKind(user.status))}</strong>
                    </div>
                    <div class="iam-dir-detail-field">
                        <span>Cartman login</span>
                        <strong>${account
                            ? badge(accountActive ? "Active" : "Disabled",
                                accountActive ? "good" : "bad")
                            : badge("Not linked", "warn")}</strong>
                    </div>
                </div>`;

            let roleContent;

            if (!account) {
                roleContent = `
                    <section class="iam-dir-role-section">
                        <h3>Assigned Roles</h3>
                        <div class="iam-dir-role-note">
                            This IAM identity is not linked to a Cartman
                            authentication account. An existing login is
                            required before roles can be assigned.
                        </div>
                    </section>`;
            } else if (isRoot) {
                roleContent = `
                    <section class="iam-dir-role-section">
                        <h3>Assigned Roles</h3>
                        <div class="iam-dir-role-note">
                            This account is a separate Cartman ROOT principal.
                            ROOT access is managed through ROOT Access Management,
                            not ordinary RBAC role assignments.
                        </div>
                        <div class="iam-dir-assignment-list">
                            ${assignmentRows(state.userAssignments, "user", false)}
                        </div>
                    </section>`;
            } else {
                roleContent = rolePanel(
                    "user",
                    state.userAssignments,
                    accountActive,
                    true,
                    accountActive
                        ? "Direct assignments apply to this account. Group-inherited roles are shown separately."
                        : "This Cartman login is disabled. New role assignments are unavailable."
                );
            }

            return `
                <section class="iam-dir-detail-card">
                    <div class="iam-dir-section-heading">
                        <div>
                            <h3>User details</h3>
                            <p>Identity data is read-only in this workspace.</p>
                        </div>
                        ${isRoot ? badge("ROOT PRINCIPAL", "bad") : ""}
                    </div>
                    ${details}
                </section>

                ${roleContent}

                ${!isRoot && account ? `
                    <section class="iam-dir-role-section">
                        <div class="iam-dir-role-heading">
                            <div>
                                <h3>Inherited Roles</h3>
                                <p>Roles assigned to groups this user belongs to.</p>
                            </div>
                            ${badge(`${state.userInheritedRoles.length} inherited`)}
                        </div>
                        <div class="iam-dir-assignment-list">
                            ${inheritedRoleRows()}
                        </div>
                        <div class="iam-dir-role-note">
                            Group role assignments are managed from the Groups tab.
                            A user's direct Overview override takes precedence over
                            inherited group roles.
                        </div>
                    </section>` : ""}
            `;
        }

        function renderGroupContent() {
            const group = selectedGroup();

            if (!group) {
                return `
                    <div class="iam-dir-empty">
                        <strong>No visible IAM groups</strong>
                        <p>Create a group to organize people and assign RBAC roles.</p>
                        <button type="button" class="isec-btn primary"
                            data-iam-action="create-group">Create group</button>
                    </div>`;
            }

            const members = group.memberNames || [];

            return `
                <section class="iam-dir-detail-card">
                    <div class="iam-dir-section-heading">
                        <div>
                            <h3>Group details</h3>
                            <p>Manage membership and RBAC assignments for this team.</p>
                        </div>
                        ${badge(group.status, statusKind(group.status))}
                    </div>

                    <div class="iam-dir-detail-grid">
                        ${readOnlyField("Group name", group.name)}
                        ${readOnlyField("Scope", group.scope)}
                        ${readOnlyField("Description", group.description)}
                        ${readOnlyField("Department", group.department_name || "Unassigned")}
                        ${readOnlyField("Member count", group.members)}
                        ${readOnlyField("Created", group.created_at)}
                    </div>

                    <div class="iam-dir-members-readonly">
                        <span>Group members · ${members.length}</span>
                        ${members.length
                            ? members.map(name =>
                                `<span class="iam-dir-member-chip">${esc(name)}</span>`
                              ).join("")
                            : `<span class="iam-dir-empty-inline">No members yet</span>`}
                    </div>

                    <div class="iam-dir-group-actions">
                        <button type="button" class="isec-btn"
                            data-iam-action="manage-members">
                            Manage members
                        </button>
                        <button type="button" class="isec-btn primary"
                            data-iam-action="create-group">
                            Create group
                        </button>
                        <button type="button" class="isec-btn danger"
                            data-iam-action="delete-group"
                            data-group-id="${esc(group.id)}">
                            Delete group
                        </button>
                    </div>

                    <div class="iam-dir-role-note">
                        Remove all members and assigned RBAC roles before deleting this group.
                    </div>
                </section>

                ${rolePanel(
                    "group",
                    state.groupAssignments,
                    true,
                    true,
                    "Roles assigned here are inherited by active IAM members of this group. Membership is managed separately above."
                )}
            `;
        }
        function renderSelectedGroupDepartment() {
            const group = selectedGroup();

            if (!group) {
                return `
                    <section class="iam-dir-detail-card">
                        <h3>No group selected</h3>
                        <p>
                            Select a user and one of their groups above.
                            Use All groups to view groups outside that user's memberships.
                        </p>
                    </section>`;
            }

            const department = state.departments.find(item =>
                item.id === group.department_id
            );

            return `
                <section class="iam-dir-detail-card">
                    <div class="iam-dir-section-heading">
                        <div>
                            <h3>Selected group's department</h3>
                            <p>${esc(group.name)} · Department relationship</p>
                        </div>
                        ${badge(
                            department ? department.name : "Unassigned",
                            department ? "good" : "warn"
                        )}
                    </div>

                    <div class="iam-dir-detail-grid">
                        ${readOnlyField("Selected user", selectedUser()?.name || "—")}
                        ${readOnlyField("Selected group", group.name)}
                        ${readOnlyField("Current department", department?.name || "Unassigned")}
                        ${readOnlyField("Group members", group.members || 0)}
                    </div>

                    <div class="iam-dir-department-attach">
                        <label>
                            <span>Assign or move this group to a department</span>
                            <select class="isec-select"
                                data-iam-group-department-select>
                                <option value="">Unassigned</option>
                                ${state.departments.map(item => `
                                    <option value="${esc(item.id)}"
                                        ${item.id === group.department_id ? "selected" : ""}>
                                        ${esc(item.name)}
                                    </option>
                                `).join("")}
                            </select>
                        </label>

                        <button type="button" class="isec-btn primary"
                            data-iam-action="save-selected-group-department">
                            Save department
                        </button>
                    </div>

                    <div class="iam-dir-role-note">
                        This assignment changes only the selected IAM group.
                        Inventory devices keep their own direct Department assignments.
                    </div>
                </section>`;
        }

        function renderDepartmentsContent() {
            const catalog = state.departments.length
                ? state.departments.map(department => {
                    const linkedCount = Number(
                        department.group_count ??
                        state.allGroups.filter(group =>
                            group.department_id === department.id
                        ).length
                    );

                    return `
                        <article class="iam-dir-department-card">
                            <div class="iam-dir-department-heading">
                                <div>
                                    <h3>${esc(department.name)}</h3>
                                    <span>${linkedCount} connected group(s)</span>
                                </div>

                                <div class="iam-dir-department-header-actions">
                                    ${badge("Department")}
                                    <button type="button"
                                        class="isec-btn danger"
                                        data-iam-action="delete-department"
                                        data-department-id="${esc(department.id)}"
                                        data-department-name="${esc(department.name)}"
                                        ${linkedCount > 0 ? "disabled" : ""}>
                                        Delete
                                    </button>
                                </div>
                            </div>
                        </article>`;
                }).join("")
                : `<div class="iam-dir-empty-inline">
                    No departments exist yet. Add a department to get started.
                   </div>`;

            return `
                ${renderSelectedGroupDepartment()}

                <div class="iam-dir-department-intro">
                    Department catalog shared with Inventory.
                    Select a group above to view or change its department.
                    Device assignments are independent of IAM group membership.
                </div>

                <div class="iam-dir-department-grid">
                    ${catalog}
                </div>`;
        }
        function renderModal() {
            if (!state.modal) return "";

            const modal = state.modal;

            if (modal.type === "create-group") {
                return `
                    <div class="iam-dir-modal-backdrop">
                        <form class="iam-dir-modal" data-iam-form="create-group"
                            role="dialog" aria-modal="true"
                            aria-labelledby="iam-dir-modal-title">
                            <div class="iam-dir-modal-header">
                                <div>
                                    <h2 id="iam-dir-modal-title">Create group</h2>
                                    <p class="iam-dir-modal-subtitle">
                                        Create a team and optionally connect it to a department.
                                    </p>
                                </div>
                                <button type="button" class="iam-dir-close"
                                    data-iam-action="close-modal" aria-label="Close">×</button>
                            </div>

                            <div class="iam-dir-form-grid">
                                <label class="iam-dir-field">
                                    <span>Group name</span>
                                    <input name="name" maxlength="160" required
                                        placeholder="e.g. Help Desk">
                                </label>

                                <label class="iam-dir-field">
                                    <span>Scope</span>
                                    <select name="scope" class="isec-select">
                                        ${availableScopes().map(scope => `
                                            <option value="${esc(scope)}"
                                                ${scope === "General" ? "selected" : ""}>
                                                ${esc(scope)}
                                            </option>
                                        `).join("")}
                                    </select>
                                    <small class="iam-dir-field-hint">
                                        Choose an existing group scope. New groups default to General.
                                    </small>
                                </label>

                                <label class="iam-dir-field">
                                    <span>Department</span>
                                    <select name="department_id" class="isec-select">
                                        <option value="">Unassigned</option>
                                        ${state.departments.map(department => `
                                            <option value="${esc(department.id)}">
                                                ${esc(department.name)}
                                            </option>
                                        `).join("")}
                                    </select>
                                </label>

                                <label class="iam-dir-field">
                                    <span>Description</span>
                                    <textarea name="description" maxlength="1000"
                                        rows="3" placeholder="What does this team do?"></textarea>
                                </label>
                            </div>

                            <div class="iam-dir-modal-actions">
                                <button type="button" class="isec-btn"
                                    data-iam-action="close-modal">Cancel</button>
                                <button type="submit" class="isec-btn primary">
                                    Create group
                                </button>
                            </div>
                        </form>
                    </div>`;
            }

            if (modal.type === "manage-members") {
                const group = state.allGroups.find(item =>
                    item.id === modal.groupId
                );

                if (!group) return "";

                const selected = new Set(group.memberIds || []);

                return `
                    <div class="iam-dir-modal-backdrop">
                        <form class="iam-dir-modal" data-iam-form="manage-members"
                            data-group-id="${esc(group.id)}"
                            role="dialog" aria-modal="true"
                            aria-labelledby="iam-dir-modal-title">
                            <div class="iam-dir-modal-header">
                                <div>
                                    <h2 id="iam-dir-modal-title">Manage group members</h2>
                                    <p class="iam-dir-modal-subtitle">
                                        ${esc(group.name)} · Select the IAM users who belong to this group.
                                    </p>
                                </div>
                                <button type="button" class="iam-dir-close"
                                    data-iam-action="close-modal" aria-label="Close">×</button>
                            </div>

                            <div class="iam-dir-member-list">
                                ${state.users.length
                                    ? state.users.map(user => `
                                        <label class="iam-dir-member">
                                            <input type="checkbox" name="userIds"
                                                value="${esc(user.id)}"
                                                ${selected.has(user.id) ? "checked" : ""}>
                                            <span>
                                                <strong>${esc(user.name)}</strong>
                                                <small>
                                                    ${esc(user.email)}
                                                    ${user.username ? ` · ${esc(user.username)}` : ""}
                                                </small>
                                            </span>
                                        </label>
                                    `).join("")
                                    : `<div class="iam-dir-empty-inline">
                                        No existing IAM users are available.
                                       </div>`}
                            </div>

                            <div class="iam-dir-modal-actions">
                                <button type="button" class="isec-btn"
                                    data-iam-action="close-modal">Cancel</button>
                                <button type="submit" class="isec-btn primary">
                                    Save membership
                                </button>
                            </div>
                        </form>
                    </div>`;
            }

            if (modal.type === "create-department") {
                return `
                    <div class="iam-dir-modal-backdrop">
                        <form class="iam-dir-modal" data-iam-form="create-department"
                            role="dialog" aria-modal="true"
                            aria-labelledby="iam-dir-modal-title">
                            <div class="iam-dir-modal-header">
                                <div>
                                    <h2 id="iam-dir-modal-title">Add department</h2>
                                    <p class="iam-dir-modal-subtitle">
                                        This department will also be available in Inventory.
                                    </p>
                                </div>
                                <button type="button" class="iam-dir-close"
                                    data-iam-action="close-modal" aria-label="Close">×</button>
                            </div>

                            <div class="iam-dir-form-grid">
                                <label class="iam-dir-field">
                                    <span>Department name</span>
                                    <input name="name" maxlength="120" required
                                        placeholder="e.g. Human Resources">
                                </label>
                            </div>

                            <div class="iam-dir-modal-actions">
                                <button type="button" class="isec-btn"
                                    data-iam-action="close-modal">Cancel</button>
                                <button type="submit" class="isec-btn primary">
                                    Add department
                                </button>
                            </div>
                        </form>
                    </div>`;
            }

            return "";
        }

        function renderDepartmentWarning() {
            const warning = state.warning;
            if (!warning) return "";

            const assets = Array.isArray(warning.assets)
                ? warning.assets
                : [];

            const groups = Array.isArray(warning.groups)
                ? warning.groups
                : [];

            return `
                <section class="iam-dir-warning" role="alert">
                    <div class="iam-dir-warning-heading">
                        <div>
                            <strong>Department cannot be deleted</strong>
                            <p>${esc(warning.message || "This department is still in use.")}</p>
                        </div>
                        <button type="button"
                            class="iam-dir-warning-close"
                            data-iam-action="dismiss-warning"
                            aria-label="Dismiss warning">×</button>
                    </div>

                    ${assets.length ? `
                        <div class="iam-dir-warning-list">
                            <strong>Inventory Assets · ${assets.length}</strong>
                            <ul>
                                ${assets.map(asset => {
                                    const metadata = [
                                        asset.type,
                                        asset.brand,
                                        asset.serial_no ? `Serial: ${asset.serial_no}` : "",
                                        asset.assigned_to ? `Assigned to: ${asset.assigned_to}` : ""
                                    ].filter(Boolean).join(" · ");

                                    return `
                                        <li>
                                            <strong>${esc(asset.name || "Unnamed asset")}</strong>
                                            ${metadata
                                                ? `<small>${esc(metadata)}</small>`
                                                : ""}
                                            <small>Department: ${esc(asset.department || warning.department || "")}</small>
                                        </li>`;
                                }).join("")}
                            </ul>
                        </div>
                    ` : ""}

                    ${groups.length ? `
                        <div class="iam-dir-warning-list">
                            <strong>Connected IAM Groups · ${groups.length}</strong>
                            <ul>
                                ${groups.map(group => `
                                    <li>
                                        <strong>${esc(group.name)}</strong>
                                        <small>Status: ${esc(group.status || "Unknown")}</small>
                                    </li>
                                `).join("")}
                            </ul>
                        </div>
                    ` : ""}

                    <p class="iam-dir-warning-foot">
                        Remove or reassign these relationships before deleting the department.
                        No records have been deleted.
                    </p>
                </section>`;
        }

        function render() {
            const isUsers = state.tab === "users";
            const isGroups = state.tab === "groups";
            const isScopes = state.tab === "scopes";

            const userSelector = `
                <label class="iam-dir-selector">
                    <span>Select IAM user</span>
                    <select class="isec-select" data-iam-user-select
                        ${state.users.length ? "" : "disabled"}>
                        ${state.users.map(item => `
                            <option value="${esc(item.id)}"
                                ${item.id === state.selectedUserId ? "selected" : ""}>
                                ${esc(item.name)} · ${esc(item.email)}
                            </option>
                        `).join("")}
                    </select>
                </label>`;

            const groupOptions = groupsForSelection();

            let selector = userSelector;

            if (!isUsers) {
                selector = `
                    <div class="iam-dir-filter-chain">
                        ${userSelector}

                        <label class="iam-dir-selector">
                            <span>Group filter</span>
                            <select class="isec-select" data-iam-group-filter>
                                <option value="user"
                                    ${state.groupFilterMode === "user" ? "selected" : ""}>
                                    Selected user's groups
                                </option>
                                <option value="all"
                                    ${state.groupFilterMode === "all" ? "selected" : ""}>
                                    All groups
                                </option>
                            </select>
                        </label>

                        <label class="iam-dir-selector">
                            <span>Select group</span>
                            <select class="isec-select" data-iam-group-select
                                ${groupOptions.length ? "" : "disabled"}>
                                <option value="">Select a group…</option>
                                ${groupOptions.map(item => `
                                    <option value="${esc(item.id)}"
                                        ${item.id === state.selectedGroupId ? "selected" : ""}>
                                        ${esc(item.name)} · ${Number(item.members || 0)} members
                                    </option>
                                `).join("")}
                            </select>
                        </label>
                    </div>`;
            }
            const tabContent = state.loading
                ? `<div class="iam-dir-empty">Loading identity records…</div>`
                : isUsers
                    ? renderUserContent()
                    : isGroups
                        ? renderGroupContent()
                        : isScopes ? renderScopesContent() : renderDepartmentsContent();

            root.innerHTML = `
                <div class="isec-app iam-dir">
                    <div class="isec-banner">
                        <div>
                            <strong>Identity, groups &amp; departments</strong>
                            <p>Manage existing identities, team membership, department structure and Cartman RBAC assignments.</p>
                        </div>
                        <span class="isec-demo ${state.connected ? "iam-dir-connected" : ""}">
                            <span class="isec-dot"></span>
                            ${state.loading ? "LOADING…" :
                                state.connected ? "IAM API CONNECTED" : "API UNAVAILABLE"}
                        </span>
                    </div>

                    ${state.error
                        ? `<div class="iam-dir-error" role="alert">${esc(state.error)}</div>`
                        : ""}
                    ${renderDepartmentWarning()}

                    <div class="isec-metrics">
                        ${metric("IAM USERS", state.users.length, "Existing directory identities")}
                        ${metric("VISIBLE GROUPS", state.groups.length, "IT system group hidden in Groups view")}
                        ${metric("DEPARTMENTS", state.departments.length, "Shared with Inventory")}
                        ${metric("ACTIVE RBAC ROLES", state.roles.length, "Roles from Roles & Permissions")}
                    </div>

                    <section class="isec-panel">
                        <div class="isec-panel-head">
                            <div>
                                <h2>Users &amp; Groups</h2>
                                <p>
                                    Users are read-only. Groups manage team membership and RBAC roles.
                                    Departments organize existing groups.
                                </p>
                            </div>

                            <div class="isec-actions">
                                <button type="button"
                                    class="isec-btn ${isUsers ? "primary" : ""}"
                                    data-iam-action="tab-users"
                                    aria-pressed="${isUsers}">Users</button>

                                <button type="button"
                                    class="isec-btn ${isGroups ? "primary" : ""}"
                                    data-iam-action="tab-groups"
                                    aria-pressed="${isGroups}">Groups</button>

                                <button type="button"
                                    class="isec-btn ${state.tab === "departments" ? "primary" : ""}"
                                    data-iam-action="tab-departments"
                                    aria-pressed="${state.tab === "departments"}">Departments</button>
                                <button type="button"
                                    class="isec-btn ${isScopes ? "primary" : ""}"
                                    data-iam-action="tab-scopes"
                                    aria-pressed="${isScopes}">Scopes</button>

                                ${isGroups ? `
                                    <button type="button" class="isec-btn"
                                        data-iam-action="create-group">+ Create group</button>
                                ` : ""}

                                ${state.tab === "departments" ? `
                                    <button type="button" class="isec-btn"
                                        data-iam-action="create-department">+ Add department</button>
                                ` : ""}

                                ${isScopes ? `
                                    <button type="button" class="isec-btn primary"
                                        data-iam-action="create-scope">+ Create scope</button>
                                ` : ""}
                                <button type="button" class="isec-btn"
                                    data-iam-action="refresh">↻ Refresh</button>
                            </div>
                        </div>

                        <div class="isec-panel-body iam-dir-workspace">
                            ${selector}
                            ${tabContent}
                            ${renderEntityScopePanel()}
                        </div>

                        <div class="iam-dir-table-footer">
                            <span>${isUsers
                                ? `${state.users.length} IAM users`
                                : isGroups
                                    ? `${state.groups.length} visible IAM groups`
                                    : `${state.departments.length} departments · ${state.allGroups.length} total IAM groups`}</span>
                            <span>Cartman IAM · RBAC assignments</span>
                        </div>
                    </section>

                    ${state.toast
                        ? `<div class="isec-toast" role="status" aria-live="polite">${esc(state.toast)}</div>`
                        : ""}

                    ${renderModal()}
                    ${renderScopeModal()}
                </div>`;
        }
                // CARTMAN_SCOPE_GROUP_ASSIGNMENTS_V2
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


        function notify(message) {
            state.toast = message;
            render();

            if (state.toastTimer) clearTimeout(state.toastTimer);

            state.toastTimer = setTimeout(() => {
                state.toast = "";
                render();
            }, 4000);
        }

        async function loadSelection() {
            state.userAssignments = [];
            state.userInheritedRoles = [];
            state.groupAssignments = [];

            if (state.tab === "users") {
                const user = selectedUser();
                const account = accountFor(user);

                if (account) {
                    const data = await api(
                        `/api/rbac/users/${encodeURIComponent(account.account_id)}/assignments`
                    );

                    state.userAssignments = data.roles || [];
                    state.userInheritedRoles = data.group_roles || [];
                }
            } else if (state.tab === "groups") {
                const group = selectedGroup();

                if (group) {
                    const data = await api(
                        `/api/rbac/groups/${encodeURIComponent(group.id)}/assignments`
                    );

                    state.groupAssignments = data.assignments || [];
                }
            }
            await loadEntityScopes();
        }
        async function load() {
            state.loading = true;
            state.error = "";
            state.warning = null;
            render();

            try {
                const [users, groups, roles, accounts, departments] = await Promise.all([
                    api("/api/iam/users"),
                    api("/api/iam/groups"),
                    api("/api/rbac/roles"),
                    api("/api/rbac/users"),
                    api("/api/departments")
                ]);

                if (!Array.isArray(users) ||
                    !Array.isArray(groups) ||
                    !Array.isArray(departments)) {
                    throw new Error("Unexpected IAM or department API response.");
                }

                state.users = users;
                state.allGroups = groups;

                // Hide the existing IT IAM group in the Groups tab only.
                // Its database row, members and RBAC assignments remain untouched.
                state.groups = groups.filter(group =>
                    String(group.name || "").trim().toLowerCase() !== "it"
                );

                state.departments = departments;
                if (!state.departments.some(item => String(item.id) === String(state.selectedDepartmentId))) {
                    state.selectedDepartmentId = state.departments[0]?.id || "";
                }

                state.roles = (roles.items || []).filter(role =>
                    role.is_active &&
                    String(role.role_key || "").toLowerCase() !== "root"
                );

                state.accounts = accounts.items || [];

                if (!state.users.some(item => item.id === state.selectedUserId)) {
                    state.selectedUserId = state.users[0]?.id || "";
                }

                syncSelectedGroup();

                state.connected = true;
                await loadSelection();
                await loadScopes();

                state.loading = false;
                render();
            } catch (error) {
                state.loading = false;
                state.connected = false;
                state.error = error.message || "Could not load IAM workspace data.";
                render();
            }
        }
        async function assignRole(kind) {
            if (state.saving) return;

            const selector = $(`[data-iam-role-select="${kind}"]`);
            const roleId = selector?.value;

            if (!roleId) {
                throw new Error("Select an RBAC role first.");
            }

            state.saving = true;

            try {
                if (kind === "user") {
                    const user = selectedUser();
                    const account = accountFor(user);

                    if (!account || Number(account.is_active) !== 1) {
                        throw new Error("An active Cartman login is required.");
                    }

                    if (Number(account.is_root) === 1) {
                        throw new Error("ROOT principals are managed separately.");
                    }

                    await api("/api/rbac/user-roles", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            account_id: account.account_id,
                            role_id: roleId,
                            scope_type: "global",
                            scope_id: ""
                        })
                    });
                } else {
                    const group = selectedGroup();
                    if (!group) throw new Error("Select a group first.");

                    await api("/api/rbac/group-roles", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            group_id: group.id,
                            role_id: roleId
                        })
                    });
                }

                await loadSelection();
                state.saving = false;
                notify("RBAC role assigned and saved.");
            } catch (error) {
                state.saving = false;
                throw error;
            }
        }

        async function removeRole(kind, assignmentId) {
            if (state.saving || !assignmentId) return;
            if (!window.confirm("Remove this RBAC role assignment?")) return;

            state.saving = true;

            try {
                const endpoint = kind === "user"
                    ? `/api/rbac/user-roles/${encodeURIComponent(assignmentId)}`
                    : `/api/rbac/group-roles/${encodeURIComponent(assignmentId)}`;

                await api(endpoint, { method: "DELETE" });
                await loadSelection();
                state.saving = false;
                notify("RBAC role assignment removed.");
            } catch (error) {
                state.saving = false;
                throw error;
            }
        }

        async function handleAction(button) {
            const action = button.dataset.iamAction;

            if (action === "dismiss-warning") {
                state.warning = null;
                render();
                return;
            }


            if (action === "tab-users" ||
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

            if (action === "create-scope") {
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

            if (action === "refresh") {
                await load();
                return;
            }

            if (action === "create-group") {
                state.error = "";
                state.modal = { type: "create-group" };
                render();
                return;
            }

            if (action === "manage-members") {
                const group = selectedGroup();

                if (!group) {
                    throw new Error("Select a group first.");
                }

                state.error = "";
                state.modal = {
                    type: "manage-members",
                    groupId: group.id
                };

                render();
                return;
            }

            if (action === "create-department") {
                state.error = "";
                state.modal = { type: "create-department" };
                render();
                return;
            }

            if (action === "delete-group") {
                const groupId = button.dataset.groupId;
                const group = state.allGroups.find(item => item.id === groupId);

                if (!group) throw new Error("Group was not found.");

                const memberCount = Number(
                    group.members || (group.memberIds || []).length
                );

                if (memberCount > 0) {
                    throw new Error(
                        `Remove all ${memberCount} member(s) from "${group.name}" before deleting it.`
                    );
                }

                if (state.groupAssignments.length > 0) {
                    throw new Error(
                        "Remove all RBAC role assignments from this group before deleting it."
                    );
                }

                if (!window.confirm(
                    `Delete group "${group.name}"? This action cannot be undone.`
                )) return;

                state.saving = true;

                try {
                    await api(
                        `/api/iam/groups/${encodeURIComponent(groupId)}`,
                        { method: "DELETE" }
                    );

                    state.selectedGroupId = "";
                    await load();
                    state.saving = false;
                    notify(`Group "${group.name}" deleted.`);
                } catch (error) {
                    state.saving = false;
                    throw error;
                }

                return;
            }

            if (action === "delete-department") {
                const departmentId = button.dataset.departmentId;
                const department = state.departments.find(item =>
                    item.id === departmentId
                );

                if (!department) {
                    throw new Error("Department was not found.");
                }

                const connectedGroups = state.allGroups.filter(group =>
                    group.department_id === departmentId
                );

                if (connectedGroups.length > 0) {
                    throw new Error(
                        `Disconnect ${connectedGroups.length} group(s) from "${department.name}" before deleting this department.`
                    );
                }

                if (!window.confirm(
                    `Delete department "${department.name}"? Departments used by Inventory assets cannot be deleted.`
                )) {
                    return;
                }

                state.saving = true;
                state.warning = null;

                try {
                    await api(
                        `/api/departments/${encodeURIComponent(departmentId)}`,
                        { method: "DELETE" }
                    );

                    await load();
                    state.saving = false;
                    notify(`Department "${department.name}" deleted.`);
                } catch (error) {
                    state.saving = false;

                    if (error.detail?.code === "department_in_use") {
                        state.warning = error.detail;
                        state.error = "";
                        render();
                        return;
                    }

                    throw error;
                }

                return;
            }
            if (action === "close-modal") {
                state.modal = null;
                render();
                return;
            }

            if (action === "save-selected-group-department") {
                const group = selectedGroup();

                if (!group) {
                    throw new Error("Select a group first.");
                }

                const selector = $("[data-iam-group-department-select]");

                if (!selector) {
                    throw new Error("Department selector was not found.");
                }

                const departmentId = selector.value || null;

                if (
                    group.department_id &&
                    departmentId &&
                    group.department_id !== departmentId &&
                    !window.confirm("Move this group to the selected department?")
                ) {
                    return;
                }

                state.saving = true;

                try {
                    await api(
                        `/api/iam/groups/${encodeURIComponent(group.id)}/department`,
                        {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                department_id: departmentId
                            })
                        }
                    );

                    await load();
                    state.saving = false;

                    notify(
                        departmentId
                            ? "Selected group connected to department."
                            : "Selected group disconnected from department."
                    );
                } catch (error) {
                    state.saving = false;
                    throw error;
                }

                return;
            }

            if (action === "attach-group") {
                const departmentId = button.dataset.departmentId;

                const selector = Array.from(root.querySelectorAll(
                    "[data-iam-department-group-select]"
                )).find(item =>
                    item.dataset.iamDepartmentGroupSelect === departmentId
                );

                const groupId = selector?.value;

                if (!groupId) {
                    throw new Error("Select a group first.");
                }

                const group = state.allGroups.find(item => item.id === groupId);

                if (!group) {
                    throw new Error("Selected group was not found.");
                }

                const department = state.departments.find(item =>
                    item.id === departmentId
                );

                if (!department) {
                    throw new Error("Department was not found.");
                }

                if (group.department_id &&
                    group.department_id !== departmentId &&
                    !window.confirm(
                        `Move "${group.name}" from "${group.department_name}" to "${department.name}"?`
                    )) {
                    return;
                }

                state.saving = true;

                try {
                    await api(
                        `/api/iam/groups/${encodeURIComponent(groupId)}/department`,
                        {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ department_id: departmentId })
                        }
                    );

                    await load();
                    state.saving = false;
                    notify(`Group connected to ${department.name}.`);
                } catch (error) {
                    state.saving = false;
                    throw error;
                }

                return;
            }

            if (action === "detach-group") {
                const groupId = button.dataset.groupId;

                const group = state.allGroups.find(item =>
                    item.id === groupId
                );

                if (!group) {
                    throw new Error("Group was not found.");
                }

                if (!window.confirm(
                    `Remove "${group.name}" from "${button.dataset.departmentName}"?`
                )) {
                    return;
                }

                state.saving = true;

                try {
                    await api(
                        `/api/iam/groups/${encodeURIComponent(groupId)}/department`,
                        {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ department_id: null })
                        }
                    );

                    await load();
                    state.saving = false;
                    notify("Group disconnected from department.");
                } catch (error) {
                    state.saving = false;
                    throw error;
                }

                return;
            }

            if (action === "assign-role") {
                await assignRole(button.dataset.kind);
                return;
            }

            if (action === "remove-role") {
                await removeRole(
                    button.dataset.kind,
                    button.dataset.assignmentId
                );
            }
        }
        root.addEventListener("click", async event => {
            const button = event.target.closest("[data-iam-action]");
            if (!button || !root.contains(button) || state.saving) return;

            try {
                await handleAction(button);
            } catch (error) {
                state.error = error.message || "The requested operation failed.";
                render();
            }
        });

        root.addEventListener("change", async event => {
            const target = event.target;

            if (target.matches("[data-iam-scope-department-select]")) {
                state.selectedDepartmentId = target.value;
                await loadEntityScopes();
                render();
                return;
            }

            if (target.matches("[data-iam-user-select]")) {
                state.selectedUserId = target.value;
                syncSelectedGroup();

                try {
                    await loadSelection();
                    state.error = "";
                } catch (error) {
                    state.error = error.message;
                }

                render();
                return;
            }

            if (target.matches("[data-iam-group-filter]")) {
                state.groupFilterMode =
                    target.value === "all" ? "all" : "user";

                syncSelectedGroup();

                try {
                    await loadSelection();
                    state.error = "";
                } catch (error) {
                    state.error = error.message;
                }

                render();
                return;
            }

            if (target.matches("[data-iam-group-select]")) {
                state.selectedGroupId = target.value;

                try {
                    await loadSelection();
                    state.error = "";
                } catch (error) {
                    state.error = error.message;
                }

                render();
            }
        });
        root.addEventListener("submit", async event => {
            const form = event.target.closest("[data-iam-form]");

            if (!form || !root.contains(form)) return;

            event.preventDefault();

            if (state.saving) return;

            const formType = form.dataset.iamForm;

            state.saving = true;
            state.error = "";

            try {
                if (formType === "save-scope") {
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

                if (formType === "create-group") {
                    const formData = new FormData(form);

                    const payload = {
                        name: String(formData.get("name") || "").trim(),
                        scope: String(formData.get("scope") || "General").trim() || "General",
                        description: String(formData.get("description") || "").trim(),
                        department_id: String(formData.get("department_id") || "").trim() || null,
                        status: "Active"
                    };

                    const created = await api("/api/iam/groups", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    state.selectedGroupId = created.id;
                    state.tab = "groups";
                    state.groupFilterMode = "all";
                    state.modal = null;

                    await load();

                    state.saving = false;
                    notify("Group created successfully.");
                    return;
                }

                if (formType === "manage-members") {
                    const groupId = form.dataset.groupId;

                    const userIds = Array.from(
                        form.querySelectorAll('input[name="userIds"]:checked')
                    ).map(input => input.value);

                    await api(
                        `/api/iam/groups/${encodeURIComponent(groupId)}/members`,
                        {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ userIds })
                        }
                    );

                    state.selectedGroupId = groupId;
                    state.modal = null;

                    await load();

                    state.saving = false;
                    notify("Group membership saved.");
                    return;
                }

                if (formType === "create-department") {
                    const formData = new FormData(form);

                    const payload = {
                        name: String(formData.get("name") || "").trim()
                    };

                    await api("/api/departments", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    state.tab = "departments";
                    state.modal = null;

                    await load();

                    state.saving = false;
                    notify("Department created successfully.");
                    return;
                }

                state.saving = false;

            } catch (error) {
                state.saving = false;
                state.error = error.message || "Could not save the requested change.";
                render();
            }
        });

        load();
    }
})();
