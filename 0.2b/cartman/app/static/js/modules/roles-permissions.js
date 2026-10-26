/* Cartman IAM role assignment prototype.
 * UI-only demo: no API calls and no real access enforcement.
 */
(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector("[data-rp-root]");
        if (!root) return;

        const users = [
            { id: "usr-jordan", name: "Jordan Lee", email: "jordan.lee@example.test", department: "IT" },
            { id: "usr-mina", name: "Mina Patel", email: "mina.patel@example.test", department: "IT Operations" },
            { id: "usr-alex", name: "Alex Morgan", email: "alex.morgan@example.test", department: "Security" },
            { id: "usr-taylor", name: "Taylor Reed", email: "taylor.reed@example.test", department: "IT Support" }
        ];

        const groups = [
            { id: "grp-endpoint", name: "Endpoint Support", description: "Endpoint support team" },
            { id: "grp-security", name: "Security Analysts", description: "Security operations team" },
            { id: "grp-platform", name: "Platform Operations", description: "Infrastructure and platform team" }
        ];

        const ROLE_KEYS = [
            "cartman_iam_view",
            "cartman_iam_contributor",
            "cartman_iam_owner"
        ];

        const roles = {
            cartman_iam_view: {
                name: "cartman_iam_view",
                title: "Reader / View",
                icon: "◉",
                description: "Can view assigned resources and permitted information. Cannot create, edit or delete.",
                short: "View only"
            },
            cartman_iam_contributor: {
                name: "cartman_iam_contributor",
                title: "Contributor",
                icon: "✎",
                description: "Can view, create and edit resources within scope. Cannot delete resources or manage role assignments.",
                short: "View + create + edit"
            },
            cartman_iam_owner: {
                name: "cartman_iam_owner",
                title: "Owner",
                icon: "✦",
                description: "Can view, create, edit and delete resources, and manage role assignments within scope.",
                short: "Full control within scope"
            }
        };

        // Illustrative assignments only; they exist in this page's memory.
        // Each entity may have exactly one role, or no role (No access).
        const assignments = {
            "user:usr-jordan": {
                cartman_iam_view: false,
                cartman_iam_contributor: false,
                cartman_iam_owner: true
            },
            "user:usr-mina": {
                cartman_iam_view: true,
                cartman_iam_contributor: false,
                cartman_iam_owner: false
            },
            "user:usr-alex": {
                cartman_iam_view: false,
                cartman_iam_contributor: false,
                cartman_iam_owner: false
            },
            "user:usr-taylor": {
                cartman_iam_view: false,
                cartman_iam_contributor: false,
                cartman_iam_owner: false
            },
            "group:grp-endpoint": {
                cartman_iam_view: false,
                cartman_iam_contributor: true,
                cartman_iam_owner: false
            },
            "group:grp-security": {
                cartman_iam_view: false,
                cartman_iam_contributor: false,
                cartman_iam_owner: false
            },
            "group:grp-platform": {
                cartman_iam_view: false,
                cartman_iam_contributor: false,
                cartman_iam_owner: true
            }
        };

        let entityType = "user";
        let selectedEntityKey = "";
        let draft = emptyAssignment();
        let toast = "";
        let toastTimer = null;

        function emptyAssignment() {
            return {
                cartman_iam_view: false,
                cartman_iam_contributor: false,
                cartman_iam_owner: false
            };
        }

        const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        }[c]));

        function findEntity(key) {
            if (!key) return null;
            const [type, id] = key.split(":");
            const entity = (type === "user" ? users : groups).find(item => item.id === id);
            return entity ? { ...entity, type, key } : null;
        }

        function savedAssignment(key) {
            return { ...emptyAssignment(), ...(assignments[key] || {}) };
        }

        function selectedRoleCount(value) {
            return ROLE_KEYS.filter(key => Boolean(value[key])).length;
        }

        function currentAccess(value) {
            if (selectedRoleCount(value) > 1) return "invalid";
            if (value.cartman_iam_owner) return "owner";
            if (value.cartman_iam_contributor) return "contributor";
            if (value.cartman_iam_view) return "view";
            return "none";
        }

        function roleDisplay(access) {
            return ({
                owner: "Owner",
                contributor: "Contributor",
                view: "Reader / View",
                none: "No access",
                invalid: "Invalid assignment"
            })[access] || "No access";
        }

        function styleAccess(access) {
            return ({
                owner: "full",
                contributor: "contributor",
                view: "view",
                none: "none",
                invalid: "invalid"
            })[access] || "none";
        }

        function notify(message) {
            toast = message;
            render();
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => {
                toast = "";
                render();
            }, 3500);
        }

        function principalCard(item, type) {
            const key = `${type}:${item.id}`;
            const isSelected = key === selectedEntityKey;
            const access = currentAccess(savedAssignment(key));
            const subtitle = type === "user"
                ? `${item.email} · Department: ${item.department || "Unassigned"}`
                : item.description;

            return `
                <button type="button"
                    class="rp-principal ${isSelected ? "is-selected" : ""}"
                    data-rp-select="${esc(key)}"
                    aria-pressed="${isSelected}">
                    <span class="rp-principal-icon">${type === "user" ? "♙" : "♧"}</span>
                    <span class="rp-principal-info">
                        <strong>${esc(item.name)}</strong>
                        <small>${esc(subtitle || "")}</small>
                    </span>
                    <span class="rp-principal-status rp-status-${styleAccess(access)}">
                        ${roleDisplay(access)}
                    </span>
                </button>`;
        }

        function roleCheck(roleKey) {
            const role = roles[roleKey];
            const checked = Boolean(draft[roleKey]);
            const style = roleKey === "cartman_iam_owner" ? "full" :
                roleKey === "cartman_iam_contributor" ? "contributor" : "view";

            return `
                <label class="rp-role-option rp-role-${style} ${checked ? "is-checked" : ""}">
                    <input type="checkbox"
                        data-rp-role-check="${roleKey}"
                        ${checked ? "checked" : ""}>
                    <span class="rp-role-checkmark">${checked ? "✓" : ""}</span>
                    <span class="rp-role-option-icon">${role.icon}</span>
                    <span class="rp-role-option-copy">
                        <strong>${role.name}</strong>
                        <span>${role.title}</span>
                        <small>${role.description}</small>
                    </span>
                    <span class="rp-role-option-state">${checked ? "Selected" : "Not assigned"}</span>
                </label>`;
        }

        function permissionPreview(access) {
            const canView = ["view", "contributor", "owner"].includes(access);
            const canEdit = ["contributor", "owner"].includes(access);
            const canDelete = access === "owner";
            const canManageAccess = access === "owner";

            const rows = [
                ["Enter and view permitted information", canView],
                ["Create records", canEdit],
                ["Edit existing records", canEdit],
                ["Delete resources", canDelete],
                ["Manage role assignments", canManageAccess]
            ];

            return `
                <div class="rp-capability-list">
                    ${rows.map(([label, allowed]) => `
                        <div class="rp-capability">
                            <span>${esc(label)}</span>
                            <strong class="${allowed ? "is-allowed" : "is-denied"}">
                                ${allowed ? "✓ Allowed" : "— Denied"}
                            </strong>
                        </div>
                    `).join("")}
                </div>`;
        }

        function selectedPanel() {
            const entity = findEntity(selectedEntityKey);

            if (!entity) {
                return `
                    <section class="rp-panel rp-unselected">
                        <div class="rp-unselected-icon">♙</div>
                        <h2>Select a user or group above</h2>
                        <p>Choose an entity to view and edit its three mutually exclusive role assignments.</p>
                    </section>`;
            }

            const access = currentAccess(draft);
            const invalid = access === "invalid";

            let message;
            let kind;

            if (invalid) {
                message = "Conflict: only one IAM role can be assigned to an entity. Clear the other selected roles before saving.";
                kind = "error";
            } else if (access === "none") {
                message = "No role selected. This entity has no access under this demo's role model.";
                kind = "warning";
            } else if (access === "view") {
                message = "Reader / View selected. The entity can view permitted resources but cannot change them.";
                kind = "success";
            } else if (access === "contributor") {
                message = "Contributor selected. The entity can create and edit permitted resources, but cannot delete resources or manage role assignments.";
                kind = "success";
            } else {
                message = "Owner selected. The entity can perform supported actions and manage assignments within its eventual scope.";
                kind = "success";
            }

            return `
                <section class="rp-panel">
                    <div class="rp-panel-header">
                        <div>
                            <div class="rp-eyebrow">SELECTED ENTITY</div>
                            <h2>${esc(entity.name)}</h2>
                            <p>${entity.type === "user" ? "User account" : "IAM group"} · ${esc(entity.id)}</p>
                        </div>
                        <span class="rp-access-summary rp-access-${styleAccess(access)}">
                            ${roleDisplay(access)}
                        </span>
                    </div>

                    <div class="rp-panel-body">
                        <div class="rp-role-section-title">
                            <div>
                                <h3>Role assignment</h3>
                                <p>Select exactly one role. Multiple roles cannot be saved together.</p>
                            </div>
                            <span class="rp-demo-label">DEMO ASSIGNMENT</span>
                        </div>

                        <div class="rp-role-options">
                            ${ROLE_KEYS.map(roleCheck).join("")}
                        </div>

                        <div class="rp-validation rp-validation-${kind}"
                            role="${invalid ? "alert" : "status"}">
                            <span class="rp-validation-icon">${invalid ? "!" : access === "none" ? "○" : "✓"}</span>
                            <span>${esc(message)}</span>
                        </div>

                        <div class="rp-save-row">
                            <div class="rp-unsaved-hint">
                                No role means No access. Changes remain a draft until saved.
                            </div>
                            <div class="rp-save-actions">
                                <button type="button" class="rp-btn" data-rp-reset>Reset</button>
                                <button type="button" class="rp-btn rp-btn-primary"
                                    data-rp-save ${invalid ? "disabled" : ""}>
                                    Save demo assignment
                                </button>
                            </div>
                        </div>
                    </div>
                </section>

                <section class="rp-panel">
                    <div class="rp-panel-header">
                        <div>
                            <h2>Access preview</h2>
                            <p>Illustrative capabilities for the selected role.</p>
                        </div>
                        <span class="rp-preview-state rp-preview-${styleAccess(access)}">
                            ${roleDisplay(access)}
                        </span>
                    </div>
                    <div class="rp-panel-body">
                        ${permissionPreview(access)}
                        <div class="rp-no-access-note">
                            <strong>Scope:</strong> these permissions would apply only to resources covered by the assignment.
                            This prototype does not enforce access in Cartman or its APIs.
                        </div>
                    </div>
                </section>`;
        }

        function render() {
            const userAccessCount = Object.entries(assignments).filter(([key, value]) =>
                key.startsWith("user:") && currentAccess(value) !== "none"
            ).length;

            const groupAccessCount = Object.entries(assignments).filter(([key, value]) =>
                key.startsWith("group:") && currentAccess(value) !== "none"
            ).length;

            const selected = findEntity(selectedEntityKey);

            root.innerHTML = `
                <section class="rp-banner">
                    <div>
                        <h2>Role assignment</h2>
                        <p>Choose a user or group and assign one role. Role defines what they can do; Scope defines where those permissions apply.</p>
                    </div>
                    <span class="rp-banner-tag">LOCAL DEMO · NOT ENFORCED</span>
                </section>

                <section class="rp-stats" aria-label="Demo assignment summary">
                    <article class="rp-stat">
                        <span class="rp-stat-label">ACCESS ROLES</span>
                        <strong class="rp-stat-value">3</strong>
                        <span class="rp-stat-foot">Reader · Contributor · Owner</span>
                    </article>
                    <article class="rp-stat">
                        <span class="rp-stat-label">SAMPLE USERS</span>
                        <strong class="rp-stat-value">${users.length}</strong>
                        <span class="rp-stat-foot">Demo identities</span>
                    </article>
                    <article class="rp-stat">
                        <span class="rp-stat-label">SAMPLE GROUPS</span>
                        <strong class="rp-stat-value">${groups.length}</strong>
                        <span class="rp-stat-foot">Demo IAM groups</span>
                    </article>
                    <article class="rp-stat">
                        <span class="rp-stat-label">WITH ACCESS</span>
                        <strong class="rp-stat-value">${userAccessCount + groupAccessCount}</strong>
                        <span class="rp-stat-foot">${userAccessCount} users · ${groupAccessCount} groups</span>
                    </article>
                </section>

                <section class="rp-panel">
                    <div class="rp-panel-header">
                        <div>
                            <div class="rp-eyebrow">SELECT</div>
                            <h2>Select a user or group</h2>
                            <p>Select an entity to inspect and change its role.</p>
                        </div>
                        ${selected ? `<span class="rp-selected-label">Selected: ${esc(selected.name)}</span>` : ""}
                    </div>

                    <div class="rp-entity-type-select" role="group" aria-label="Choose Users or Groups">
                        <button type="button"
                            class="rp-entity-type-card ${entityType === "user" ? "is-selected" : ""}"
                            data-rp-entity-type="user"
                            aria-pressed="${entityType === "user"}">
                            <span class="rp-group-icon">♙</span>
                            <span class="rp-entity-type-copy">
                                <strong>Users</strong>
                                <small>Individual accounts</small>
                            </span>
                            <span class="rp-group-count">${users.length}</span>
                        </button>

                        <button type="button"
                            class="rp-entity-type-card ${entityType === "group" ? "is-selected" : ""}"
                            data-rp-entity-type="group"
                            aria-pressed="${entityType === "group"}">
                            <span class="rp-group-icon">♧</span>
                            <span class="rp-entity-type-copy">
                                <strong>Groups</strong>
                                <small>Group-based assignments</small>
                            </span>
                            <span class="rp-group-count">${groups.length}</span>
                        </button>
                    </div>

                    <section class="rp-principal-group rp-principal-group-single">
                        <div class="rp-principal-group-heading">
                            <span class="rp-group-icon">${entityType === "user" ? "♙" : "♧"}</span>
                            <div>
                                <h3>${entityType === "user" ? "Users" : "Groups"}</h3>
                                <p>${entityType === "user" ? "Select an individual account" : "Select an IAM group"}</p>
                            </div>
                            <span class="rp-group-count">${entityType === "user" ? users.length : groups.length}</span>
                        </div>
                        <div class="rp-principal-list">
                            ${entityType === "user"
                                ? users.map(user => principalCard(user, "user")).join("")
                                : groups.map(group => principalCard(group, "group")).join("")}
                        </div>
                    </section>
                </section>

                ${selectedPanel()}

                <div class="rp-demo-footnote">
                    <strong>Demo boundary:</strong> all identities and assignments are sample data held in browser memory.
                    No real permission is granted, revoked or enforced by this prototype.
                </div>

                ${toast ? `<div class="rp-toast" role="status" aria-live="polite">${esc(toast)}</div>` : ""}`;
        }

        root.addEventListener("click", (event) => {
            const typeButton = event.target.closest("[data-rp-entity-type]");
            if (typeButton) {
                entityType = typeButton.dataset.rpEntityType === "group" ? "group" : "user";
                selectedEntityKey = "";
                draft = emptyAssignment();
                render();
                return;
            }

            const entityButton = event.target.closest("[data-rp-select]");
            if (entityButton) {
                selectedEntityKey = entityButton.dataset.rpSelect;
                draft = savedAssignment(selectedEntityKey);
                render();
                return;
            }

            if (event.target.closest("[data-rp-reset]")) {
                draft = savedAssignment(selectedEntityKey);
                render();
                return;
            }

            if (event.target.closest("[data-rp-save]")) {
                if (!selectedEntityKey) return;

                if (selectedRoleCount(draft) > 1) {
                    notify("Cannot save: choose only one of Reader, Contributor or Owner.");
                    return;
                }

                assignments[selectedEntityKey] = { ...draft };
                const access = currentAccess(draft);

                notify(access === "none"
                    ? "Demo assignment saved: No access."
                    : `Demo assignment saved: ${roleDisplay(access)}.`);
            }
        });

        root.addEventListener("change", (event) => {
            const checkbox = event.target.closest("[data-rp-role-check]");
            if (!checkbox) return;

            draft[checkbox.dataset.rpRoleCheck] = checkbox.checked;
            render();

            // Restore keyboard focus after rerender.
            const next = root.querySelector(
                `[data-rp-role-check="${checkbox.dataset.rpRoleCheck}"]`
            );
            if (next) next.focus();
        });

        function notify(message) {
            toast = message;
            render();
            if (toastTimer) clearTimeout(toastTimer);

            toastTimer = setTimeout(() => {
                toast = "";
                render();
            }, 3500);
        }

        render();
    });
})();
