/* CARTMAN_RBAC_MANAGEMENT_UI_V1 */
(() => {
  "use strict";
  const root = document.querySelector("[data-rp-root]");
  if (!root || root.dataset.rbacManagementUi === "1") return;
  root.dataset.rbacManagementUi = "1";

  const API = "/api/rbac";
  const LEVELS = [
    { value: 0, label: "No Access" },
    { value: 1, label: "Read Only" },
    { value: 2, label: "Contributor" },
    { value: 3, label: "Admin" }
  ];
  const state = {
    tab: "roles", catalog: [], scopes: [], roles: [], users: [], audit: [],
    selectedRoleId: "", selectedUserId: "", roleGrants: [], userAssignments: [], userOverrides: [],
    permissionDraft: {}, permissionScopeType: "global", permissionScopeId: "",
    permissionQuery: "", permissionModule: "all", modal: null,
    loading: true, busy: false, error: "", notice: "", enforcementEnabled: false,
    platformGateEnabled: false, isRoot: false, rootPrincipals: []
  };

  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
  const fmt = value => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  };
  const slugTitle = value => String(value || "").replace(/[_-]+/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const currentRole = () => state.roles.find(role => role.id === state.selectedRoleId) || null;
  const currentUser = () => state.users.find(user => user.account_id === state.selectedUserId) || null;
  const scopeIdentity = (type, id) => `${type || "global"}::${type === "global" ? "" : (id || "")}`;
  const scopeLabel = row => row.scope_type === "global" ? "Global" : `${slugTitle(row.scope_type)} · ${row.scope_id || "(no ID)"}`;
  const permissionByKey = key => state.catalog.find(item => item.key === key);
  const permissionLabel = key => {
    const item = permissionByKey(key);
    return item ? `${item.page || slugTitle(item.module)} · ${item.label}` : key;
  };

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      ...options
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = { detail: raw.slice(0, 300) }; }
    if (!response.ok) {
      const error = new Error(data.detail || `${response.status} ${response.statusText}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function scopeOptions(selected) {
    return state.scopes.map(scope => `<option value="${esc(scope.key)}" ${selected === scope.key ? "selected" : ""}>${esc(scope.label)}</option>`).join("");
  }
  function levelOptions(selected, permissionKey = "") {
    const choices = permissionKey === "overview.page"
      ? [{ value: 0, label: "No Access" }, { value: 1, label: "Full Review" }]
      : LEVELS;
    return choices.map(level => `<option value="${level.value}" ${Number(selected) === level.value ? "selected" : ""}>${esc(level.label)}</option>`).join("");
  }
  function permissionOptions(selected) {
    const usable = state.catalog.filter(item => !item.root_only);
    const groups = new Map();
    usable.forEach(item => {
      const group = item.page || slugTitle(item.module);
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(item);
    });
    return [...groups.entries()].map(([group, items]) => `<optgroup label="${esc(group)}">${items.map(item => `<option value="${esc(item.key)}" ${selected === item.key ? "selected" : ""}>${esc(item.label)} · ${esc(item.key)}</option>`).join("")}</optgroup>`).join("");
  }
  function noticeBox(text, kind = "success") {
    if (!text) return "";
    return `<div class="rpl-alert ${kind}" role="status">${esc(text)}</div>`;
  }
  function panel(title, description, body, right = "") {
    return `<section class="rpl-panel"><header class="rpl-panel-head"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div>${right}</header>${body}</section>`;
  }
  function badge(label, kind = "muted") { return `<span class="rpl-badge ${kind}">${esc(label)}</span>`; }
  function button(label, action, kind = "", disabled = false, extra = "") {
    return `<button type="button" class="rpl-btn ${kind}" data-rp-action="${esc(action)}" ${disabled ? "disabled" : ""} ${extra}>${label}</button>`;
  }
  function metric(label, value, hint) {
    return `<article class="rpl-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(hint || "")}</small></article>`;
  }
  function scopeFields(prefix, scopeType = "global", scopeId = "") {
    return `<label>Scope type<select name="${prefix}_scope_type" data-rp-scope-select="${prefix}">${scopeOptions(scopeType)}</select></label>
      <label class="rpl-scope-id" data-rp-scope-id-wrap="${prefix}" ${scopeType === "global" ? "hidden" : ""}>Scope ID<input name="${prefix}_scope_id" value="${esc(scopeId)}" maxlength="200" placeholder="Enter the exact resource ID" ${scopeType === "global" ? "disabled" : "required"}></label>`;
  }

  async function reloadContext() {
    state.loading = true;
    state.error = "";
    state.auditError = "";
    render();
    try {
      const [catalog, roles, users, rootStatus] = await Promise.all([
        request(`${API}/catalog`), request(`${API}/roles`), request(`${API}/users`), request(`${API}/root/status`)
      ]);
      state.catalog = catalog.permissions || [];
      state.scopes = catalog.scope_types || [{ key: "global", label: "All resources in Cartman" }];
      state.roles = roles.items || [];
      state.users = users.items || [];
      state.enforcementEnabled = Boolean(catalog.enforcement_enabled);
      state.platformGateEnabled = Boolean(catalog.platform_access_gate_enabled);
      state.isRoot = Boolean(rootStatus.is_root);
      if (!state.selectedRoleId || !state.roles.some(r => r.id === state.selectedRoleId)) {
        state.selectedRoleId = state.roles[0]?.id || "";
      }
      if (!state.selectedUserId || !state.users.some(u => u.account_id === state.selectedUserId)) {
        state.selectedUserId = state.users.find(u => Number(u.is_active) === 1)?.account_id || state.users[0]?.account_id || "";
      }
      await Promise.all([loadSelectedRole(), loadSelectedUser()]);
      try { state.audit = (await request(`${API}/audit?limit=100`)).items || []; }
      catch (error) { state.auditError = error.message; state.audit = []; }
      state.loading = false;
      render();
    } catch (error) {
      state.loading = false;
      state.error = error.status === 403
        ? "Bu ekranı yönetmek için mevcut Cartman Administrator hesabıyla giriş yapmalısın."
        : `RBAC API bağlantısı kurulamadı: ${error.message}. Foundation kurulumu tamamlanmış mı?`;
      render();
    }
  }

  function isOverviewGateClosed() {
    if (state.permissionScopeType === "global") {
      return Number(state.permissionDraft["overview.page"] || 0) < 1;
    }
    const globalOverview = state.roleGrants.find(grant =>
      grant.permission_key === "overview.page" &&
      grant.scope_type === "global" &&
      String(grant.scope_id || "") === ""
    );
    return Number(globalOverview?.access_level || 0) < 1;
  }

  function applyPermissionDraftForScope() {
    state.permissionDraft = {};
    const identity = scopeIdentity(state.permissionScopeType, state.permissionScopeId);
    state.roleGrants.forEach(grant => {
      if (scopeIdentity(grant.scope_type, grant.scope_id) === identity) {
        state.permissionDraft[grant.permission_key] = Number(grant.access_level);
      }
    });
    // Keep the matrix in sync while editing a resource ID without replacing the focused input.
    const overviewBlocked = isOverviewGateClosed();
    root.querySelectorAll("[data-rp-permission-level]").forEach(select => {
      const key = select.dataset.rpPermissionLevel;
      const lockedByOverview = key !== "overview.page" && overviewBlocked;
      select.value = String(lockedByOverview ? 0 : (state.permissionDraft[key] || 0));
      select.disabled = lockedByOverview || (key === "overview.page" && state.permissionScopeType !== "global");
    });
  }

  async function loadSelectedRole() {
    state.roleGrants = [];
    state.permissionDraft = {};
    if (!state.selectedRoleId) return;
    const data = await request(`${API}/roles/${encodeURIComponent(state.selectedRoleId)}/permissions`);
    state.roleGrants = data.permissions || [];
    applyPermissionDraftForScope();
  }

  async function loadSelectedUser() {
    state.userAssignments = [];
    state.userOverrides = [];
    if (!state.selectedUserId) return;
    const data = await request(`${API}/users/${encodeURIComponent(state.selectedUserId)}/assignments`);
    state.userAssignments = data.roles || [];
    state.userOverrides = data.overrides || [];
  }

  function header() {
    const activeUsers = state.users.filter(user => Number(user.is_active) === 1).length;
    const assignmentCount = state.users.reduce((sum, user) => sum + Number(user.assigned_role_count || 0), 0);
    const customRoles = state.roles.filter(role => !role.is_system).length;
    return `<div class="rpl-app">
      <section class="rpl-hero"><div><div class="rpl-eyebrow">CARTMAN / IDENTITY &amp; SECURITY</div><h1>Roles &amp; Permissions</h1><p>Build role bundles, assign access to accounts and define resource-level exceptions.</p></div>
        <div class="rpl-hero-meta"><span class="rpl-foundation">RBAC MANAGEMENT</span><span class="rpl-status">${state.platformGateEnabled ? "PLATFORM ACCESS GATE ON · MODULE ENFORCEMENT PENDING" : (state.enforcementEnabled ? "ENFORCEMENT ENABLED" : "CONFIGURATION MODE")}</span></div></section>
      ${noticeBox(state.error, "error")}${noticeBox(state.notice, "success")}
      <section class="rpl-metrics">${metric("RBAC ROLES", state.roles.length, `${customRoles} custom roles`)}${metric("ACTIVE ACCOUNTS", activeUsers, "Authentication accounts available for assignment")}${metric("ROLE ASSIGNMENTS", assignmentCount, "Saved account-to-role links")}${metric("PERMISSION CATALOG", state.catalog.length, "Registered permission definitions")}</section>
      <nav class="rpl-tabs" aria-label="RBAC management sections">
        <button type="button" data-rp-tab="roles" class="${state.tab === "roles" ? "active" : ""}">Role Management</button>
        <button type="button" data-rp-tab="users" class="${state.tab === "users" ? "active" : ""}">User Assignments</button>
        <button type="button" data-rp-tab="overrides" class="${state.tab === "overrides" ? "active" : ""}">User Overrides</button>
        <button type="button" data-rp-tab="audit" class="${state.tab === "audit" ? "active" : ""}">RBAC Audit</button>
        <button type="button" data-rp-tab="root" class="${state.tab === "root" ? "active" : ""}">ROOT Access <span class="rpl-root-tab-lock">▣</span></button>
      </nav>`;
  }

  function roleList() {
    return `<aside class="rpl-role-rail"><div class="rpl-rail-head"><div><h2>Roles</h2><p>Reusable permission bundles</p></div>${button("＋ New role", "new-role", "primary")}</div>
      <div class="rpl-role-items">${state.roles.map(role => `<button type="button" class="rpl-role-item ${role.id === state.selectedRoleId ? "selected" : ""}" data-rp-select-role="${esc(role.id)}">
        <span class="rpl-role-avatar">${esc((role.name || "R").slice(0, 1).toUpperCase())}</span><span class="rpl-role-copy"><strong>${esc(role.name)}</strong><small>${esc(role.role_key)} · ${Number(role.permission_count || 0)} grants</small></span><span class="rpl-role-count">${Number(role.assignment_count || 0)}</span></button>`).join("") || `<div class="rpl-empty">No roles have been created yet.</div>`}</div>
      <div class="rpl-rail-foot">System templates are protected from deletion. Custom roles can be removed after all assignments are revoked.</div></aside>`;
  }

  function permissionGroups() {
    const query = state.permissionQuery.trim().toLowerCase();
    const scopeKey = scopeIdentity(state.permissionScopeType, state.permissionScopeId);
    const items = state.catalog.filter(item => !item.root_only)
      .filter(item => state.permissionModule === "all" || item.module === state.permissionModule)
      .filter(item => !query || [item.key, item.label, item.description, item.page, item.module, item.action].join(" ").toLowerCase().includes(query));
    const byPage = new Map();
    items.forEach(item => {
      const key = item.page || slugTitle(item.module);
      if (!byPage.has(key)) byPage.set(key, []);
      byPage.get(key).push(item);
    });
    if (!items.length) return `<div class="rpl-empty rpl-empty-large">No permissions match this filter.</div>`;
      const overviewBlocked = isOverviewGateClosed();
    return [...byPage.entries()].map(([page, rows]) => `<section class="rpl-permission-group"><header><div><h3>${esc(page)}</h3><small>${rows.length} permission${rows.length === 1 ? "" : "s"}</small></div><span>${esc(slugTitle(rows[0]?.module || ""))}</span></header>
      <div class="rpl-table-wrap"><table class="rpl-table rpl-permission-table"><thead><tr><th>Permission</th><th>Action</th><th>Key</th><th>Access level</th></tr></thead><tbody>${rows.map(item => {
        const level = item.key !== "overview.page" && overviewBlocked
          ? 0
          : Number(state.permissionDraft[item.key] || 0);
        const disabled = (item.key === "overview.page" && state.permissionScopeType !== "global") || (item.key !== "overview.page" && overviewBlocked);
        return `<tr><td><strong>${esc(item.label)}</strong><small>${esc(item.description || "")}</small></td><td>${badge(slugTitle(item.action), "neutral")}</td><td><code>${esc(item.key)}</code></td><td><select class="rpl-level-select" data-rp-permission-level="${esc(item.key)}" ${disabled ? "disabled" : ""}>${levelOptions(level, item.key)}</select></td></tr>`;
      }).join("")}</tbody></table></div></section>`).join("");
  }

  function roleView() {
    const role = currentRole();
    const modules = [...new Set(state.catalog.filter(item => !item.root_only).map(item => item.module))].sort();
    const overviewBlocked = isOverviewGateClosed();
    const grantCount = overviewBlocked ? 0 : Object.values(state.permissionDraft).filter(value => Number(value) > 0).length;
    const scopeIdDisabled = state.permissionScopeType === "global";
    const scopePicker = `<div class="rpl-scope-picker"><label>Permission scope<select data-rp-permission-scope>${scopeOptions(state.permissionScopeType)}</select></label><label class="rpl-scope-id" ${scopeIdDisabled ? "hidden" : ""}>Scope ID<input data-rp-permission-scope-id value="${esc(state.permissionScopeId)}" placeholder="Exact resource ID" maxlength="200" ${scopeIdDisabled ? "disabled" : ""}></label><small>Other scopes already saved on this role are preserved when you save this scope.</small></div>`;
    const detail = role ? `<div class="rpl-role-detail-head"><div><div class="rpl-role-kicker">${role.is_system ? "BUILT-IN TEMPLATE" : "CUSTOM ROLE"} · ${role.is_active ? "ACTIVE" : "DISABLED"}</div><h2>${esc(role.name)}</h2><p>${esc(role.description || "No description provided.")}</p></div><div class="rpl-role-actions">${button("Edit role", "edit-role", "secondary")}${button("Delete", "delete-role", "danger", Boolean(role.is_system) || Number(role.assignment_count || 0) > 0)}</div></div>
      <div class="rpl-role-stats"><span><strong>${grantCount}</strong> active grants in selected scope</span><span><strong>${Number(role.assignment_count || 0)}</strong> account assignments</span><span><strong>${Number(role.permission_count || 0)}</strong> stored grants total</span></div>
      <div class="rpl-permission-tools"><div><h3>Permission matrix</h3><p>Choose the access level for every listed permission. Overview is a global gate: No Access blocks all Cartman pages and APIs; Full Review admits the account to the read-only dashboard.</p></div><div class="rpl-filter-row"><input type="search" data-rp-permission-search value="${esc(state.permissionQuery)}" placeholder="Search permission or action…"><select data-rp-module-filter><option value="all">All modules</option>${modules.map(module => `<option value="${esc(module)}" ${state.permissionModule === module ? "selected" : ""}>${esc(slugTitle(module))}</option>`).join("")}</select></div></div>
      ${scopePicker}<div class="rpl-permission-scroll">${permissionGroups()}</div>
      <div class="rpl-save-row"><span>Overview admission is enforced immediately. Other module and action permissions remain configuration until their enforcement rollout.</span>${button(state.busy ? "Saving…" : "Save permission set", "save-permissions", "primary", state.busy)}</div>`
      : `<div class="rpl-empty rpl-empty-large">Select a role or create a new role to start configuring permissions.</div>`;
    return `<div class="rpl-role-layout">${roleList()}<section class="rpl-role-workspace">${detail}</section></div>`;
  }

  function assignmentRows() {
    return state.userAssignments.map(row => `<tr><td><strong>${esc(row.role_name)}</strong><small>${esc(row.role_key)}</small></td><td>${badge(scopeLabel(row), "neutral")}</td><td>${esc(row.assigned_by || "—")}</td><td>${esc(fmt(row.created_at))}</td><td>${button("Revoke", "revoke-assignment", "danger-link", state.busy, `data-rp-id="${esc(row.id)}"`)}</td></tr>`).join("");
  }
  function userView() {
    const user = currentUser();
    const activeRoles = state.roles.filter(role => role.is_active);
    const activeAccounts = state.users.filter(item => Number(item.is_active) === 1);
    const userOptionHtml = state.users.map(item => `<option value="${esc(item.account_id)}" ${item.account_id === state.selectedUserId ? "selected" : ""}>${esc(item.display_name || item.username)} · ${esc(item.username)}${Number(item.is_active) !== 1 ? " (Inactive)" : ""}</option>`).join("");
    const activeAccountOptions = activeAccounts.map(item => `<option value="${esc(item.account_id)}" ${item.account_id === state.selectedUserId ? "selected" : ""}>${esc(item.display_name || item.username)} · ${esc(item.username)}${item.is_root ? " · ROOT" : ""}</option>`).join("");
    const selectedUserHeader = user ? `<div class="rpl-selected-user"><div class="rpl-user-avatar">${esc((user.display_name || user.username || "U").slice(0, 1).toUpperCase())}</div><div><strong>${esc(user.display_name || user.username)}</strong><span>${esc(user.username)} · ${esc(user.department || "No department")}</span></div><div class="rpl-user-link-status">${user.is_root ? badge("ROOT · FULL ACCESS", "danger") : (user.iam_user_id ? badge("IAM linked", "success") : badge("Not linked to IAM directory", "warning"))}</div></div>` : `<div class="rpl-empty">No authentication accounts available.</div>`;
    const assignForm = `<form class="rpl-form-grid" data-rp-assign-form><label>Account<select name="account_id" required>${activeAccountOptions}</select></label><label>Role<select name="role_id" required>${activeRoles.filter(role => role.role_key !== "root").map(role => `<option value="${esc(role.id)}">${esc(role.name)}</option>`).join("")}</select></label>${scopeFields("assign")}<div class="rpl-form-submit"><button type="submit" class="rpl-btn primary" ${!activeAccounts.length || !activeRoles.length ? "disabled" : ""}>Assign role</button></div></form>`;
    const assignments = `<div class="rpl-table-wrap"><table class="rpl-table"><thead><tr><th>Role</th><th>Scope</th><th>Assigned by</th><th>Assigned at</th><th>Action</th></tr></thead><tbody>${assignmentRows() || `<tr><td colspan="5" class="rpl-empty-cell">No RBAC roles assigned to this account.</td></tr>`}</tbody></table></div>`;
    return `<div class="rpl-stack">${panel("Assign a role", "Choose an authentication account, a role bundle and the resource scope for this assignment.", assignForm)}
      ${panel("Account role assignments", "Revoke an assignment to remove that RBAC role link from the selected account.", `<div class="rpl-account-picker"><label>Selected account<select data-rp-user-select>${userOptionHtml}</select></label>${selectedUserHeader}</div>${assignments}`)}
      <div class="rpl-footnote"><strong>ROOT note:</strong> ROOT principals are shown with a separate badge and are never assigned or revoked using this normal role form. <strong>Account linking:</strong> assignments attach to the real <code>auth_accounts.id</code>. The optional IAM directory match is informational and uses the account username; the Users &amp; Groups page is not modified.</div></div>`;
  }

  function overrideRows() {
    return state.userOverrides.map(row => `<tr><td><strong>${esc(permissionLabel(row.permission_key))}</strong><small><code>${esc(row.permission_key)}</code></small></td><td>${badge(row.permission_key === "overview.page" && Number(row.access_level) === 1 ? "Full Review" : (LEVELS[Number(row.access_level)]?.label || row.access_level), Number(row.access_level) === 0 ? "danger" : "neutral")}</td><td>${badge(scopeLabel(row), "neutral")}</td><td>${esc(row.reason || "—")}</td><td>${esc(row.assigned_by || "—")}</td><td>${button("Remove", "remove-override", "danger-link", state.busy, `data-rp-id="${esc(row.id)}"`)}</td></tr>`).join("");
  }
  function overridesView() {
    const user = currentUser();
    const userOptionHtml = state.users.map(item => `<option value="${esc(item.account_id)}" ${item.account_id === state.selectedUserId ? "selected" : ""}>${esc(item.display_name || item.username)} · ${esc(item.username)}${item.is_root ? " · ROOT" : ""}</option>`).join("");
    const form = `<div class="rpl-account-picker"><label>Target account<select data-rp-user-select>${userOptionHtml}</select></label>${user ? `<div class="rpl-user-inline"><strong>${esc(user.display_name || user.username)}</strong><span>${esc(user.username)}</span></div>` : ""}</div>
      <form class="rpl-form-grid rpl-override-form" data-rp-override-form><label>Permission<select name="permission_key" required>${permissionOptions("")}</select></label><label>Access level<select name="access_level" required>${levelOptions(1, "")}</select></label>${scopeFields("override")}<label class="rpl-field-full">Reason<input name="reason" maxlength="500" placeholder="Why is this account receiving a different access level?"></label><div class="rpl-form-submit"><button type="submit" class="rpl-btn primary" ${!user ? "disabled" : ""}>Save user override</button></div></form>`;
    const table = `<div class="rpl-table-wrap"><table class="rpl-table"><thead><tr><th>Permission</th><th>Override</th><th>Scope</th><th>Reason</th><th>Changed by</th><th>Action</th></tr></thead><tbody>${overrideRows() || `<tr><td colspan="6" class="rpl-empty-cell">No user-specific overrides for this account.</td></tr>`}</tbody></table></div>`;
    return `<div class="rpl-stack">${panel("User-specific permission override", "Overrides are stored independently from role bundles. No Access is an explicit user-level denial.", form)}${panel("Current overrides", "Remove an override to return that permission to role-derived evaluation.", table)}
      <div class="rpl-root-lock"><span class="rpl-lock-icon">▣</span><span><strong>ROOT-only capabilities remain unavailable</strong><small>These cannot be assigned or overridden from this screen.</small></span></div></div>`;
  }

  function rootView() {
    if (!state.isRoot) {
      return `<section class="rpl-root-restricted"><div class="rpl-root-alert-kicker">RESTRICTED SYSTEM AREA</div><h2>ROOT Access Management</h2><p>Bu bölüm yalnızca ROOT tarafından görüntülenebilir ve yönetilebilir. Normal Administrator, Network Administrator veya başka bir RBAC rolü bu alana erişemez.</p><div class="rpl-root-alert-note">ROOT, normal bir RBAC rolü veya permission değildir. Cartman'ın ayrıcalıklı sistem sahipliği kaydıdır.</div></section>`;
    }
    const rows = state.rootPrincipals.map(item => `<tr><td><strong>${esc(item.display_name || item.username)}</strong><small>${esc(item.username)}</small></td><td>${badge(Number(item.enabled) === 1 ? "ROOT active" : "Disabled", Number(item.enabled) === 1 ? "danger" : "muted")}</td><td>${esc(item.granted_by || "—")}</td><td>${esc(fmt(item.granted_at))}</td><td>${item.username.toLowerCase() === "benbenim" ? badge("Bootstrap owner", "warning") : (Number(item.enabled) === 1 ? button("Revoke ROOT", "revoke-root", "danger-link", state.busy, `data-rp-username="${esc(item.username)}"`) : "—")}</td></tr>`).join("");
    const candidates = state.users.filter(item => Number(item.is_active) === 1 && String(item.legacy_role || "").toLowerCase() === "admin" && !item.is_root);
    return `<div class="rpl-stack">
      ${panel("ROOT system ownership", "Unrestricted Cartman access. This is separate from the ordinary RBAC role and permission model.", `<div class="rpl-root-alert-note"><strong>CRITICAL PRIVILEGE</strong><br>ROOT bypasses every Cartman page, API and action permission, including the Overview platform gate. Only an existing ROOT principal can manage this list. The reserved bootstrap owner <code>benbenim</code> is protected against accidental revocation.</div><div class="rpl-root-principal-summary">${badge("ROOT ACTIVE", "danger")}<span>${state.rootPrincipals.filter(item => Number(item.enabled) === 1).length} active ROOT principal(s)</span></div>`)}
      ${panel("Grant ROOT to an administrator", "Only active legacy Administrator accounts are eligible during this migration phase. Every change is written to IAM Audit.", `<form class="rpl-form-grid rpl-root-grant-form" data-rp-root-form><label>Existing Administrator account<select name="username" required>${candidates.map(item => `<option value="${esc(item.username)}">${esc(item.display_name || item.username)} · ${esc(item.username)}</option>`).join("")}</select></label><div class="rpl-form-submit"><button type="submit" class="rpl-btn primary" ${!candidates.length || state.busy ? "disabled" : ""}>Grant ROOT access</button></div></form>`)}
      ${panel("ROOT principals", "ROOT is not shown in the normal role assignment list and cannot be assigned from the regular role selector.", `<div class="rpl-table-wrap"><table class="rpl-table"><thead><tr><th>Principal</th><th>Status</th><th>Granted by</th><th>Granted at</th><th>Action</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="rpl-empty-cell">No ROOT principals found.</td></tr>`}</tbody></table></div>`, button("Refresh ROOT list", "refresh-root", "secondary", state.busy))}
      <div class="rpl-footnote"><strong>Permanent bootstrap owner:</strong> <code>benbenim</code> is automatically registered as ROOT at startup and cannot be revoked from this screen. ROOT API operations are server-side protected; hiding the UI is not the security boundary.</div>
    </div>`;
  }

  function auditView() {
    const rows = state.audit.map(item => {
      const details = item.details && typeof item.details === "object" ? JSON.stringify(item.details) : String(item.details || "");
      return `<tr><td>${esc(fmt(item.occurred_at))}</td><td><strong>${esc(item.actor || "—")}</strong></td><td><code>${esc(item.action || "—")}</code></td><td>${esc(item.resource_type || "—")}<small>${esc(item.resource_id || "")}</small></td><td><span class="rpl-audit-details" title="${esc(details)}">${esc(details || "—")}</span></td></tr>`;
    }).join("");
    return `${panel("RBAC change history", "Role, permission, assignment and override changes recorded in the existing IAM audit store.", `<div class="rpl-table-wrap"><table class="rpl-table"><thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Resource</th><th>Details</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="rpl-empty-cell">${state.auditError ? esc(state.auditError) : "No RBAC audit events have been recorded yet."}</td></tr>`}</tbody></table></div>`, button("Refresh", "refresh", "secondary"))}<div class="rpl-footnote">Audit data comes from <code>iam_audit_events</code>; this page does not edit or delete audit records.</div>`;
  }

  function roleModal() {
    if (!state.modal || state.modal.kind !== "role") return "";
    const role = state.modal.roleId ? state.roles.find(item => item.id === state.modal.roleId) : null;
    return `<div class="rpl-modal-backdrop" data-rp-close-modal><section class="rpl-modal" role="dialog" aria-modal="true" aria-labelledby="rpl-role-modal-title"><header><div><span class="rpl-eyebrow">ROLE CONFIGURATION</span><h2 id="rpl-role-modal-title">${role ? "Edit role" : "Create custom role"}</h2><p>Role records are stored as RBAC bundles and do not change the legacy login role.</p></div>${button("×", "close-modal", "icon")}</header><form data-rp-role-form>
      <label>Role name<input name="name" required maxlength="120" value="${esc(role?.name || "")}" placeholder="e.g. Helpdesk Tier 2"></label>
      <label>Role key<input name="role_key" required minlength="3" maxlength="80" pattern="[a-z][a-z0-9-]{2,79}" value="${esc(role?.role_key || "")}" placeholder="helpdesk-tier-2" ${role ? "disabled" : ""}><small>Lowercase letters, numbers and hyphens. The key cannot be changed after creation.</small></label>
      <label>Description<textarea name="description" rows="3" maxlength="1000" placeholder="Describe the purpose and access boundaries of this role.">${esc(role?.description || "")}</textarea></label>
      ${role ? `<label class="rpl-check"><input type="checkbox" name="is_active" ${role.is_active ? "checked" : ""}> Role is active and available for assignment</label>` : ""}
      <div class="rpl-modal-error" data-rp-form-error hidden></div><footer>${button("Cancel", "close-modal", "secondary")}<button type="submit" class="rpl-btn primary">${role ? "Save changes" : "Create role"}</button></footer></form></section></div>`;
  }

  function render() {
    if (state.loading && !state.catalog.length) {
      root.innerHTML = `<div class="rpl-app"><div class="rpl-loading">Loading RBAC management data…</div></div>`;
      return;
    }
    const body = state.tab === "roles" ? roleView() : state.tab === "users" ? userView() : state.tab === "overrides" ? overridesView() : state.tab === "root" ? rootView() : auditView();
    root.innerHTML = `${header()}<main class="rpl-content">${body}</main>${roleModal()}</div>`;
    syncScopeInputs();
  }

  function syncScopeInputs() {
    root.querySelectorAll("[data-rp-scope-select]").forEach(select => {
      const prefix = select.dataset.rpScopeSelect;
      const wrap = root.querySelector(`[data-rp-scope-id-wrap="${prefix}"]`);
      const input = wrap?.querySelector("input");
      const global = select.value === "global";
      if (wrap) wrap.hidden = global;
      if (input) { input.disabled = global; input.required = !global; }
    });
  }

  async function withBusy(action, successMessage, after) {
    if (state.busy) return;
    state.busy = true; state.error = ""; state.notice = ""; render();
    try {
      await action();
      if (after) await after();
      state.notice = successMessage;
    } catch (error) {
      state.error = error.message || "The requested RBAC operation failed.";
    } finally {
      state.busy = false;
      render();
    }
  }

  async function saveRolePermissions() {
    const role = currentRole();
    if (!role) return;
    const currentScope = scopeIdentity(state.permissionScopeType, state.permissionScopeId);
    const preserved = state.roleGrants.filter(grant => scopeIdentity(grant.scope_type, grant.scope_id) !== currentScope);
    const edits = Object.entries(state.permissionDraft)
      .filter(([, level]) => Number(level) > 0)
      .filter(([key]) => { const item = permissionByKey(key); return item && !item.root_only; })
      .map(([key, level]) => ({ permission_key: key, access_level: Number(level), scope_type: state.permissionScopeType, scope_id: state.permissionScopeType === "global" ? "" : state.permissionScopeId.trim() }));
    if (state.permissionScopeType !== "global" && !state.permissionScopeId.trim()) {
      throw new Error("Bu scope türünde Scope ID girmelisin.");
    }
    await request(`${API}/roles/${encodeURIComponent(role.id)}/permissions`, { method: "PUT", body: JSON.stringify({ permissions: preserved.concat(edits) }) });
    await loadSelectedRole();
    await refreshRoles();
  }

  async function refreshRoles() {
    state.roles = (await request(`${API}/roles`)).items || [];
  }
  async function refreshUserData() {
    await loadSelectedUser();
    state.users = (await request(`${API}/users`)).items || [];
    await refreshRoles();
  }

  root.addEventListener("click", async event => {
    if (event.target.matches("[data-rp-close-modal]")) { state.modal = null; render(); return; }
    const tab = event.target.closest("[data-rp-tab]");
    if (tab) {
      const nextTab = tab.dataset.rpTab;
      state.error = ""; state.notice = "";
      if (nextTab === "root") {
        if (!state.isRoot) {
          window.alert("UYARI: Bu bölüm yalnızca ROOT tarafından görüntülenebilir ve yönetilebilir. ROOT yetkin yoksa bu alana erişemezsin.");
          state.tab = "root"; render(); return;
        }
        const confirmed = window.confirm("ROOT WARNING\n\nYou are entering Cartman's unrestricted system ownership area. ROOT bypasses all RBAC permissions and can grant or revoke ROOT principals. Only ROOT may view or manage this section. Continue?");
        if (!confirmed) return;
        try { state.rootPrincipals = (await request(`${API}/root/principals`)).items || []; }
        catch (error) { state.error = error.message; }
      }
      state.tab = nextTab; render(); return;
    }
    const roleButton = event.target.closest("[data-rp-select-role]");
    if (roleButton) {
      state.selectedRoleId = roleButton.dataset.rpSelectRole;
      state.permissionQuery = ""; state.permissionModule = "all";
      try { await loadSelectedRole(); } catch (error) { state.error = error.message; }
      render(); return;
    }
    const actionButton = event.target.closest("[data-rp-action]");
    if (!actionButton || actionButton.disabled) return;
    const action = actionButton.dataset.rpAction;
    if (action === "new-role") { state.modal = { kind: "role", roleId: "" }; render(); return; }
    if (action === "edit-role") { state.modal = { kind: "role", roleId: state.selectedRoleId }; render(); return; }
    if (action === "close-modal") { state.modal = null; render(); return; }
    if (action === "refresh") { await reloadContext(); return; }
    if (action === "refresh-root") {
      await withBusy(async () => { state.rootPrincipals = (await request(`${API}/root/principals`)).items || []; }, "ROOT principal list refreshed.");
      return;
    }
    if (action === "revoke-root") {
      const username = actionButton.dataset.rpUsername;
      if (!username || username.toLowerCase() === "benbenim") return;
      if (!window.confirm(`Revoke unrestricted ROOT access from ${username}? This account will return to ordinary RBAC and legacy authorization.`)) return;
      await withBusy(async () => { await request(`${API}/root/principals/${encodeURIComponent(username)}`, { method: "DELETE" }); state.rootPrincipals = (await request(`${API}/root/principals`)).items || []; state.users = (await request(`${API}/users`)).items || []; }, "ROOT access revoked.");
      return;
    }
    if (action === "save-permissions") {
      await withBusy(saveRolePermissions, "Role permissions saved. Overview No Access is enforced as a global Cartman lockout; other module/action enforcement remains a separate rollout.");
      return;
    }
    if (action === "delete-role") {
      const role = currentRole();
      if (!role || role.is_system || Number(role.assignment_count || 0) > 0) return;
      if (!window.confirm(`Delete the custom role “${role.name}”? This cannot be undone.`)) return;
      await withBusy(async () => {
        await request(`${API}/roles/${encodeURIComponent(role.id)}`, { method: "DELETE" });
        state.selectedRoleId = "";
        await refreshRoles();
        state.selectedRoleId = state.roles[0]?.id || "";
        await loadSelectedRole();
      }, "Custom role deleted.");
      return;
    }
    if (action === "revoke-assignment") {
      const id = actionButton.dataset.rpId;
      if (!id || !window.confirm("Revoke this role assignment from the selected account?")) return;
      await withBusy(async () => {
        await request(`${API}/user-roles/${encodeURIComponent(id)}`, { method: "DELETE" });
        await refreshUserData();
      }, "Role assignment revoked.");
      return;
    }
    if (action === "remove-override") {
      const id = actionButton.dataset.rpId;
      if (!id || !window.confirm("Remove this user-specific override? The account will return to role-derived evaluation for this permission.")) return;
      await withBusy(async () => {
        await request(`${API}/user-overrides/${encodeURIComponent(id)}`, { method: "DELETE" });
        await refreshUserData();
      }, "User override removed.");
    }
  });

  root.addEventListener("change", async event => {
    const level = event.target.closest("[data-rp-permission-level]");
    if (level) {
      const key = level.dataset.rpPermissionLevel;
      if (key !== "overview.page" && isOverviewGateClosed()) {
        level.value = "0";
        return;
      }
      state.permissionDraft[key] = Number(level.value);
      if (key === "overview.page") render();
      return;
    }
    if (event.target.matches("[data-rp-user-select]")) {
      state.selectedUserId = event.target.value;
      try { await loadSelectedUser(); state.error = ""; } catch (error) { state.error = error.message; }
      render(); return;
    }
    if (event.target.matches("[data-rp-permission-scope]")) {
      state.permissionScopeType = event.target.value;
      state.permissionScopeId = "";
      try { await loadSelectedRole(); state.error = ""; } catch (error) { state.error = error.message; }
      render(); return;
    }
    if (event.target.matches("[data-rp-module-filter]")) {
      state.permissionModule = event.target.value;
      render(); return;
    }
    if (event.target.matches("[data-rp-scope-select]")) syncScopeInputs();
    if (event.target.matches("select[name='permission_key']")) {
      const levelSelect = event.target.form?.querySelector("select[name='access_level']");
      if (levelSelect) levelSelect.innerHTML = levelOptions(Number(levelSelect.value), event.target.value);
    }
  });

  root.addEventListener("input", event => {
    if (event.target.matches("[data-rp-permission-search]")) {
      state.permissionQuery = event.target.value;
      const query = state.permissionQuery.toLowerCase();
      root.querySelectorAll(".rpl-permission-table tbody tr").forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
      root.querySelectorAll(".rpl-permission-group").forEach(group => { group.hidden = !group.querySelector("tbody tr:not([hidden])"); });
    }
    if (event.target.matches("[data-rp-permission-scope-id]")) {
      state.permissionScopeId = event.target.value;
      applyPermissionDraftForScope();
      const count = Object.values(state.permissionDraft).filter(value => Number(value) > 0).length;
      const firstStat = root.querySelector(".rpl-role-stats span strong");
      if (firstStat) firstStat.textContent = String(count);
    }
  });

  root.addEventListener("submit", async event => {
    const form = event.target;
    if (form.matches("[data-rp-root-form]")) {
      event.preventDefault();
      if (state.busy || !state.isRoot) return;
      const fd = new FormData(form);
      const username = String(fd.get("username") || "").trim();
      if (!username || !window.confirm(`Grant unrestricted Cartman ROOT access to ${username}? This account will bypass every RBAC page/action permission.`)) return;
      await withBusy(async () => {
        await request(`${API}/root/principals`, { method: "POST", body: JSON.stringify({ username }) });
        state.rootPrincipals = (await request(`${API}/root/principals`)).items || [];
        state.users = (await request(`${API}/users`)).items || [];
      }, `ROOT access granted to ${username}.`);
      return;
    }
    if (form.matches("[data-rp-role-form]")) {
      event.preventDefault();
      if (state.busy) return;
      const fd = new FormData(form);
      const editing = Boolean(state.modal?.roleId);
      const payload = { name: String(fd.get("name") || "").trim(), description: String(fd.get("description") || "").trim() };
      if (!editing) payload.role_key = String(fd.get("role_key") || "").trim().toLowerCase();
      else payload.is_active = fd.has("is_active");
      const submit = form.querySelector('button[type="submit"]');
      if (submit) { submit.disabled = true; submit.textContent = "Saving…"; }
      const errorBox = form.querySelector("[data-rp-form-error]");
      try {
        const result = editing
          ? await request(`${API}/roles/${encodeURIComponent(state.modal.roleId)}`, { method: "PATCH", body: JSON.stringify(payload) })
          : await request(`${API}/roles`, { method: "POST", body: JSON.stringify(payload) });
        state.modal = null;
        await refreshRoles();
        state.selectedRoleId = result.id || state.selectedRoleId;
        await loadSelectedRole();
        state.notice = editing ? "Role updated." : "Custom role created. Configure its permission matrix next.";
        render();
      } catch (error) {
        if (errorBox) { errorBox.hidden = false; errorBox.textContent = error.message; }
        if (submit) { submit.disabled = false; submit.textContent = editing ? "Save changes" : "Create role"; }
      }
      return;
    }
    if (form.matches("[data-rp-assign-form]")) {
      event.preventDefault();
      if (state.busy) return;
      const fd = new FormData(form);
      const scopeType = String(fd.get("assign_scope_type") || "global");
      const scopeId = scopeType === "global" ? "" : String(fd.get("assign_scope_id") || "").trim();
      if (scopeType !== "global" && !scopeId) { state.error = "Bu scope için Scope ID girmelisin."; render(); return; }
      await withBusy(async () => {
        await request(`${API}/user-roles`, { method: "POST", body: JSON.stringify({ account_id: String(fd.get("account_id")), role_id: String(fd.get("role_id")), scope_type: scopeType, scope_id: scopeId }) });
        state.selectedUserId = String(fd.get("account_id"));
        await refreshUserData();
      }, "Role assigned to the account.");
      return;
    }
    if (form.matches("[data-rp-override-form]")) {
      event.preventDefault();
      if (state.busy || !state.selectedUserId) return;
      const fd = new FormData(form);
      const scopeType = String(fd.get("override_scope_type") || "global");
      const scopeId = scopeType === "global" ? "" : String(fd.get("override_scope_id") || "").trim();
      if (scopeType !== "global" && !scopeId) { state.error = "Bu scope için Scope ID girmelisin."; render(); return; }
      await withBusy(async () => {
        await request(`${API}/user-overrides`, { method: "POST", body: JSON.stringify({ account_id: state.selectedUserId, permission_key: String(fd.get("permission_key")), access_level: Number(fd.get("access_level")), scope_type: scopeType, scope_id: scopeId, reason: String(fd.get("reason") || "").trim() }) });
        await refreshUserData();
      }, "User-specific permission override saved.");
    }
  });

  reloadContext();
})();
