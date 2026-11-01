/* Cartman IAM — persistent Users & Groups UI */
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
            tab: "users",
            query: "",
            connected: false,
            error: "",
            toast: "",
            loading: false,
            toastTimer: null
        };

        const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[c]);

        const $ = (selector, base = root) => base.querySelector(selector);

        const badge = (value, kind = "") =>
            `<span class="isec-badge ${esc(kind)}">${esc(value)}</span>`;

        const statusKind = (value) => ({
            Active: "good",
            Invited: "warn",
            Suspended: "bad",
            Review: "warn",
            Disabled: "bad",
            "Not configured": "warn"
        }[value] || "");

        async function api(url, options = {}) {
            const response = await fetch(url, {
                cache: "no-store",
                ...options,
                headers: {
                    Accept: "application/json",
                    ...(options.headers || {})
                }
            });

            const text = await response.text();
            let data = null;

            try {
                data = text ? JSON.parse(text) : null;
            } catch {
                data = null;
            }

            if (!response.ok) {
                const detail = data && (data.detail || data.message);
                throw new Error(
                    detail ? String(detail) : `Request failed (${response.status})`
                );
            }

            return data;
        }

        function setToast(message) {
            state.toast = message;
            render();

            if (state.toastTimer) clearTimeout(state.toastTimer);

            state.toastTimer = setTimeout(() => {
                state.toast = "";
                render();
            }, 4000);
        }

        function userRows() {
            return state.users.map((user) => {
                const groups = user.groupNames || [];
                const searchText = [
                    user.name, user.email, user.username,
                    user.department, user.status, ...groups
                ].join(" ").toLowerCase();

                return `
                    <tr data-iam-row data-search="${esc(searchText)}">
                        <td>
                            <div class="isec-primary-text">${esc(user.name)}</div>
                            <div class="isec-secondary-text">${esc(user.id)}</div>
                        </td>
                        <td>${esc(user.email)}</td>
                        <td>${esc(user.username || "—")}</td>
                        <td>${esc(user.department || "Unassigned")}</td>
                        <td>${badge(user.status, statusKind(user.status))}</td>
                        <td>
                            <div class="iam-dir-group-names">
                                ${groups.length
                                    ? esc(groups.join(", "))
                                    : '<span class="isec-secondary-text">Unassigned</span>'}
                            </div>
                        </td>
                        <td>
                            <div class="isec-actions">
                                <button type="button" class="isec-btn"
                                    data-iam-action="edit-user" data-id="${esc(user.id)}">Edit</button>
                                <button type="button" class="isec-btn danger"
                                    data-iam-action="delete-user" data-id="${esc(user.id)}">Delete</button>
                            </div>
                        </td>
                    </tr>`;
            }).join("");
        }

        function groupRows() {
            return state.groups.map((group) => {
                const members = group.memberNames || [];
                const searchText = [
                    group.name, group.scope, group.description,
                    group.status, ...members
                ].join(" ").toLowerCase();

                return `
                    <tr data-iam-row data-search="${esc(searchText)}">
                        <td>
                            <div class="isec-primary-text">${esc(group.name)}</div>
                            <div class="isec-secondary-text">${esc(group.id)}</div>
                            ${group.description
                                ? `<div class="isec-secondary-text">${esc(group.description)}</div>`
                                : ""}
                        </td>
                        <td>${esc(group.scope || "General")}</td>
                        <td>
                            ${badge(`${group.members || 0} member${group.members === 1 ? "" : "s"}`)}
                            ${members.length
                                ? `<div class="isec-secondary-text">${esc(members.join(", "))}</div>`
                                : ""}
                        </td>
                        <td>${badge(group.status, statusKind(group.status))}</td>
                        <td>
                            <div class="isec-actions">
                                <button type="button" class="isec-btn primary"
                                    data-iam-action="members" data-id="${esc(group.id)}">Members</button>
                                <button type="button" class="isec-btn"
                                    data-iam-action="edit-group" data-id="${esc(group.id)}">Edit</button>
                                <button type="button" class="isec-btn danger"
                                    data-iam-action="delete-group" data-id="${esc(group.id)}">Delete</button>
                            </div>
                        </td>
                    </tr>`;
            }).join("");
        }

        function metric(label, value, foot) {
            return `
                <article class="isec-metric">
                    <span class="isec-metric-label">${esc(label)}</span>
                    <div class="isec-metric-value">${esc(value)}</div>
                    <span class="isec-metric-foot">${esc(foot)}</span>
                </article>`;
        }

        function render() {
            const isUsers = state.tab === "users";
            const activeUsers = state.users.filter((u) => u.status === "Active").length;
            const invitedUsers = state.users.filter((u) => u.status === "Invited").length;
            const activeGroups = state.groups.filter((g) => g.status === "Active").length;

            const tableContent = isUsers
                ? `
                    <table class="isec-table">
                        <thead><tr>
                            <th>User</th><th>Email</th><th>Username</th>
                            <th>Department</th><th>Status</th><th>Groups</th><th>Actions</th>
                        </tr></thead>
                        <tbody>${userRows()}</tbody>
                    </table>`
                : `
                    <table class="isec-table">
                        <thead><tr>
                            <th>Group</th><th>Scope</th><th>Members</th>
                            <th>Status</th><th>Actions</th>
                        </tr></thead>
                        <tbody>${groupRows()}</tbody>
                    </table>`;

            const recordCount = isUsers ? state.users.length : state.groups.length;

            root.innerHTML = `
                <div class="isec-app iam-dir">
                    <div class="isec-banner">
                        <div>
                            <strong>IAM directory management</strong>
                            <p>Manage persistent user accounts, groups and group membership in Cartman.</p>
                        </div>
                        <span class="isec-demo ${state.connected ? "iam-dir-connected" : ""}">
                            <span class="isec-dot"></span>
                            ${state.loading ? "CONNECTING…" : state.connected ? "IAM API CONNECTED" : "API UNAVAILABLE"}
                        </span>
                    </div>

                    <div class="isec-notice">
                        <strong>Development security boundary:</strong>
                        IAM directory endpoints are not yet protected by authenticated administrator sessions.
                        Keep Cartman on a trusted local development network until authentication and
                        server-side authorization are implemented.
                    </div>

                    ${state.error
                        ? `<div class="iam-dir-error" role="alert">${esc(state.error)}</div>`
                        : ""}

                    <div class="isec-metrics">
                        ${metric("TOTAL USERS", state.users.length, "Persistent IAM accounts")}
                        ${metric("ACTIVE USERS", activeUsers, `${invitedUsers} invited`)}
                        ${metric("GROUPS", state.groups.length, "Persistent IAM groups")}
                        ${metric("ACTIVE GROUPS", activeGroups, "Enabled directory groups")}
                    </div>

                    <section class="isec-panel">
                        <div class="isec-panel-head">
                            <div>
                                <h2>Users & Groups</h2>
                                <p>${isUsers
                                    ? "Manage account identity, department and status."
                                    : "Manage group details and explicit user membership."}</p>
                            </div>
                            <div class="isec-actions">
                                <button type="button" class="isec-btn ${isUsers ? "primary" : ""}"
                                    data-iam-action="tab-users" aria-pressed="${isUsers}">Users</button>
                                <button type="button" class="isec-btn ${!isUsers ? "primary" : ""}"
                                    data-iam-action="tab-groups" aria-pressed="${!isUsers}">Groups</button>
                            </div>
                        </div>

                        <div class="isec-panel-body">
                            <div class="isec-toolbar iam-dir-toolbar">
                                <input class="isec-input isec-search" type="search"
                                    data-iam-search value="${esc(state.query)}"
                                    placeholder="${isUsers
                                        ? "Search name, email, username or group…"
                                        : "Search groups, scope or members…"}"
                                    aria-label="Search IAM directory">
                                <button type="button" class="isec-btn primary"
                                    data-iam-action="${isUsers ? "add-user" : "add-group"}">
                                    ${isUsers ? "Add user" : "Add group"}
                                </button>
                                <button type="button" class="isec-btn"
                                    data-iam-action="refresh">↻ Refresh</button>
                            </div>
                        </div>

                        <div class="isec-table-wrap iam-dir-table-wrap">
                            ${tableContent}
                        </div>

                        <div class="iam-dir-empty" data-iam-empty ${recordCount ? "hidden" : ""}>
                            <strong data-iam-empty-title>
                                ${recordCount ? "No matching records" : isUsers ? "No IAM users yet" : "No IAM groups yet"}
                            </strong>
                            <p data-iam-empty-copy>
                                ${recordCount
                                    ? "Try another search term."
                                    : isUsers
                                        ? "Add a user to create the first persistent IAM account."
                                        : "Create a group to start organizing IAM users."}
                            </p>
                        </div>

                        <div class="iam-dir-table-footer">
                            <span data-iam-visible-count>${recordCount} ${isUsers ? "users" : "groups"}</span>
                            <span>Cartman SQLite · IAM API</span>
                        </div>
                    </section>

                    ${state.toast
                        ? `<div class="isec-toast" role="status" aria-live="polite">${esc(state.toast)}</div>`
                        : ""}

                    <div class="iam-dir-modal-backdrop" data-iam-modal hidden>
                        <section class="iam-dir-modal" role="dialog" aria-modal="true"
                            aria-labelledby="iam-dir-modal-title">
                            <div class="iam-dir-modal-header">
                                <div>
                                    <div class="isec-metric-label">CARTMAN IAM</div>
                                    <h2 id="iam-dir-modal-title">Manage directory record</h2>
                                </div>
                                <button type="button" class="iam-dir-close"
                                    data-iam-close aria-label="Close">×</button>
                            </div>
                            <div data-iam-modal-body></div>
                        </section>
                    </div>
                </div>`;

            applyFilter();
        }

        function applyFilter() {
            const query = state.query.trim().toLowerCase();
            const allRows = [...root.querySelectorAll("[data-iam-row]")];
            let visible = 0;

            allRows.forEach((row) => {
                const match = (row.dataset.search || "").includes(query);
                row.hidden = !match;
                if (match) visible++;
            });

            const empty = $("[data-iam-empty]");
            const title = $("[data-iam-empty-title]");
            const copy = $("[data-iam-empty-copy]");
            const isUsers = state.tab === "users";

            if (empty) empty.hidden = visible > 0;

            if (title && copy && query && visible === 0) {
                title.textContent = "No matching records";
                copy.textContent = "Try another search term.";
            } else if (title && copy && visible === 0) {
                title.textContent = isUsers ? "No IAM users yet" : "No IAM groups yet";
                copy.textContent = isUsers
                    ? "Add a user to create the first persistent IAM account."
                    : "Create a group to start organizing IAM users.";
            }

            const count = $("[data-iam-visible-count]");
            if (count) {
                count.textContent = `${visible} ${isUsers ? "users" : "groups"}`;
            }
        }

        function field(label, name, value = "", type = "text", required = false, maxLength = 160) {
            return `
                <label class="iam-dir-field">
                    <span>${esc(label)}</span>
                    <input name="${esc(name)}" type="${esc(type)}"
                        value="${esc(value)}" maxlength="${maxLength}"
                        ${required ? "required" : ""}>
                </label>`;
        }

        function selectField(label, name, value, options) {
            return `
                <label class="iam-dir-field">
                    <span>${esc(label)}</span>
                    <select name="${esc(name)}" required>
                        ${options.map((option) => `
                            <option value="${esc(option)}" ${option === value ? "selected" : ""}>
                                ${esc(option)}
                            </option>`).join("")}
                    </select>
                </label>`;
        }

        function modalBody(title, subtitle, formHtml, kind, mode, id = "") {
            const modal = $("[data-iam-modal]");
            if (!modal) return;

            $("#iam-dir-modal-title", modal).textContent = title;

            $("[data-iam-modal-body]", modal).innerHTML = `
                <p class="iam-dir-modal-subtitle">${esc(subtitle)}</p>
                <form data-iam-form="${esc(kind)}" data-mode="${esc(mode)}" data-id="${esc(id)}">
                    <div class="iam-dir-form-grid">${formHtml}</div>
                    <p class="iam-dir-form-error" data-iam-form-error hidden></p>
                    <div class="iam-dir-modal-actions">
                        <button type="button" class="isec-btn" data-iam-close>Cancel</button>
                        <button type="submit" class="isec-btn primary">Save changes</button>
                    </div>
                </form>`;

            modal.hidden = false;
            const first = $("input, select", modal);
            if (first) first.focus();
        }

        function openUserForm(id = "") {
            const user = state.users.find((item) => item.id === id);
            const mode = user ? "edit" : "create";

            modalBody(
                user ? "Edit IAM user" : "Add IAM user",
                user ? user.email : "Create a persistent IAM directory record. This does not send an invitation or create login credentials.",
                field("Display name", "name", user?.name || "", "text", true, 160) +
                field("Email address", "email", user?.email || "", "email", true, 254) +
                field("Username", "username", user?.username || "", "text", false, 120) +
                field("Department", "department", user?.department || "", "text", false, 120) +
                selectField("Account status", "status", user?.status || "Invited",
                    ["Invited", "Active", "Suspended"]),
                "user", mode, id
            );
        }

        function openGroupForm(id = "") {
            const group = state.groups.find((item) => item.id === id);
            const mode = group ? "edit" : "create";

            modalBody(
                group ? "Edit IAM group" : "Add IAM group",
                group ? group.name : "Create a persistent IAM group. Group membership does not grant application permissions yet.",
                field("Group name", "name", group?.name || "", "text", true, 160) +
                field("Scope", "scope", group?.scope || "General", "text", false, 120) +
                field("Description", "description", group?.description || "", "text", false, 1000) +
                selectField("Group status", "status", group?.status || "Active",
                    ["Active", "Review", "Disabled"]),
                "group", mode, id
            );
        }

        function openMembersForm(id) {
            const group = state.groups.find((item) => item.id === id);
            if (!group) return;

            const selected = new Set(group.memberIds || []);
            const choices = state.users.map((user) => `
                <label class="iam-dir-member">
                    <input type="checkbox" name="userIds" value="${esc(user.id)}"
                        ${selected.has(user.id) ? "checked" : ""}>
                    <span>
                        <strong>${esc(user.name)}</strong>
                        <small>${esc(user.email)} · ${esc(user.status)}</small>
                    </span>
                </label>`).join("");

            modalBody(
                "Manage group members",
                `Select the complete membership for ${group.name}. Saving replaces the current member list.`,
                choices || '<p class="iam-dir-modal-subtitle">Create IAM users before adding group members.</p>',
                "members", "edit", id
            );
        }

        async function load() {
            state.loading = true;
            state.error = "";
            render();

            try {
                const [users, groups] = await Promise.all([
                    api("/api/iam/users"),
                    api("/api/iam/groups")
                ]);

                if (!Array.isArray(users) || !Array.isArray(groups)) {
                    throw new Error("Unexpected response from the IAM directory API.");
                }

                state.users = users;
                state.groups = groups;
                state.connected = true;
                state.loading = false;
                render();
            } catch (error) {
                state.connected = false;
                state.loading = false;
                state.error = error.message || "Could not load the IAM directory.";
                render();
            }
        }

        async function handleAction(action, id) {
            try {
                if (action === "tab-users" || action === "tab-groups") {
                    state.tab = action === "tab-users" ? "users" : "groups";
                    state.query = "";
                    render();
                    return;
                }

                if (action === "refresh") {
                    await load();
                    return;
                }

                if (action === "add-user") {
                    openUserForm();
                    return;
                }

                if (action === "edit-user") {
                    openUserForm(id);
                    return;
                }

                if (action === "add-group") {
                    openGroupForm();
                    return;
                }

                if (action === "edit-group") {
                    openGroupForm(id);
                    return;
                }

                if (action === "members") {
                    openMembersForm(id);
                    return;
                }

                if (action === "delete-user") {
                    const user = state.users.find((item) => item.id === id);
                    if (!user || !window.confirm(
                        `Delete IAM user "${user.name}"? This also removes the user's group memberships.`
                    )) return;

                    await api(`/api/iam/users/${encodeURIComponent(id)}`, {
                        method: "DELETE"
                    });

                    state.toast = `Deleted IAM user ${user.name}.`;
                    await load();
                    return;
                }

                if (action === "delete-group") {
                    const group = state.groups.find((item) => item.id === id);
                    if (!group || !window.confirm(`Delete IAM group "${group.name}"?`)) return;

                    await api(`/api/iam/groups/${encodeURIComponent(id)}`, {
                        method: "DELETE"
                    });

                    state.toast = `Deleted IAM group ${group.name}.`;
                    await load();
                }
            } catch (error) {
                setToast(error.message || "The requested operation failed.");
            }
        }

        root.addEventListener("click", (event) => {
            if (event.target.closest("[data-iam-close]")) {
                const modal = $("[data-iam-modal]");
                if (modal) modal.hidden = true;
                return;
            }

            if (event.target.matches("[data-iam-modal]")) {
                event.target.hidden = true;
                return;
            }

            const button = event.target.closest("[data-iam-action]");
            if (!button || !root.contains(button)) return;

            handleAction(button.dataset.iamAction, button.dataset.id || "");
        });

        root.addEventListener("input", (event) => {
            if (!event.target.matches("[data-iam-search]")) return;
            state.query = event.target.value;
            applyFilter();
        });

        root.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                const modal = $("[data-iam-modal]");
                if (modal) modal.hidden = true;
            }
        });

        root.addEventListener("submit", async (event) => {
            const form = event.target.closest("[data-iam-form]");
            if (!form) return;

            event.preventDefault();

            const saveButton = $('button[type="submit"]', form);
            const errorBox = $("[data-iam-form-error]", form);
            const modal = $("[data-iam-modal]");

            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            errorBox.hidden = true;

            try {
                const kind = form.dataset.iamForm;
                const mode = form.dataset.mode;
                const id = form.dataset.id;

                if (kind === "user") {
                    const payload = {
                        name: form.elements.name.value.trim(),
                        email: form.elements.email.value.trim(),
                        username: form.elements.username.value.trim(),
                        department: form.elements.department.value.trim(),
                        status: form.elements.status.value
                    };

                    const url = mode === "edit"
                        ? `/api/iam/users/${encodeURIComponent(id)}`
                        : "/api/iam/users";

                    await api(url, {
                        method: mode === "edit" ? "PUT" : "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    state.toast = mode === "edit"
                        ? "IAM user updated."
                        : "IAM user created.";
                    state.tab = "users";
                } else if (kind === "group") {
                    const payload = {
                        name: form.elements.name.value.trim(),
                        scope: form.elements.scope.value.trim(),
                        description: form.elements.description.value.trim(),
                        status: form.elements.status.value
                    };

                    const url = mode === "edit"
                        ? `/api/iam/groups/${encodeURIComponent(id)}`
                        : "/api/iam/groups";

                    await api(url, {
                        method: mode === "edit" ? "PUT" : "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    state.toast = mode === "edit"
                        ? "IAM group updated."
                        : "IAM group created.";
                    state.tab = "groups";
                } else if (kind === "members") {
                    const userIds = [...form.querySelectorAll('input[name="userIds"]:checked')]
                        .map((input) => input.value);

                    await api(`/api/iam/groups/${encodeURIComponent(id)}/members`, {
                        method: "PUT",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ userIds })
                    });

                    state.toast = `Group membership saved (${userIds.length} member${userIds.length === 1 ? "" : "s"}).`;
                    state.tab = "groups";
                }

                if (modal) modal.hidden = true;
                state.query = "";
                await load();
            } catch (error) {
                errorBox.textContent = error.message || "Save failed.";
                errorBox.hidden = false;
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = "Save changes";
            }
        });

        load();
    }
})();
