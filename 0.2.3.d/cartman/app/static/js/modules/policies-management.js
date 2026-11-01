/* CARTMAN_IDENTITY_POLICIES_V1 */
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
