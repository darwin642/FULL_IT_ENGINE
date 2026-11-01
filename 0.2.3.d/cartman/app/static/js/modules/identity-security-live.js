/* CARTMAN_IDENTITY_SECURITY_LIVE_V1 */
(() => {
  "use strict";
  const roots = document.querySelectorAll('.workspace-module.identity-security[data-identity-security]');
  if (!roots.length) return;

  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const date = value => {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
  };
  const badge = (label, kind = "neutral") => `<span class="isl-badge isl-${esc(kind)}">${esc(label)}</span>`;
  const table = (headers, rows, empty = "No records found.") => `<div class="isl-table-wrap"><table class="isl-table"><thead><tr>${headers.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="isl-empty-cell">${esc(empty)}</td></tr>`}</tbody></table></div>`;
  const panel = (title, subtitle, body, action = "") => `<section class="isl-panel"><header class="isl-panel-head"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div>${action}</header>${body}</section>`;
  const button = (label, action, id, kind = "") => `<button type="button" class="isl-btn ${esc(kind)}" data-isl-action="${esc(action)}" data-isl-id="${esc(id || "")}">${esc(label)}</button>`;

  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      ...options
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = { detail: raw.slice(0, 300) }; }
    if (!response.ok) throw new Error(data.detail || `${response.status} ${response.statusText}`);
    return data;
  }

  const state = { busy: false, error: "", notice: "", user: null, audit: [], keys: [], keyLogs: [], auditError: "", keysError: "", logsError: "" };

  function shell(title, description, body, meta = "SERVER DATA") {
    return `<div class="isl-app"><section class="isl-hero"><div><div class="isl-eyebrow">CARTMAN / IDENTITY &amp; SECURITY</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div><span class="isl-source">${esc(meta)}</span></section>${state.error ? `<div class="isl-alert error">${esc(state.error)}</div>` : ""}${state.notice ? `<div class="isl-alert success">${esc(state.notice)}</div>` : ""}${body}</div>`;
  }
  function metrics(items) {
    return `<div class="isl-metrics">${items.map(item => `<article class="isl-metric"><span>${esc(item.label)}</span><strong>${esc(item.value)}</strong><small>${esc(item.note || "")}</small></article>`).join("")}</div>`;
  }
  function errorBox(message) { return `<div class="isl-inline-error">${esc(message || "This data is not available for your account.")}</div>`; }

  function renderIdentity() {
    const user = state.user || {};
    const events = state.audit.slice(0, 6).map(item => `<tr><td>${esc(date(item.occurred_at))}</td><td>${esc(item.actor || "—")}</td><td><code>${esc(item.action || "—")}</code></td><td>${esc(item.resource_type || "—")} · ${esc(item.resource_id || "—")}</td></tr>`).join("");
    const keyTotal = state.keys.length ? state.keys.length : "0";
    const auditCount = state.audit.length;
    const cards = `<div class="isl-shortcuts"><a href="/pages/roles-permissions/">Roles &amp; Permissions <span>View enforced role model →</span></a><a href="/pages/policies/">Policies <span>Security control status →</span></a><a href="/pages/audit/">Audit Logs <span>Review recorded actions →</span></a><a href="/pages/credentials-secrets/">Credentials &amp; Secrets <span>API key inventory →</span></a></div>`;
    const body = `${metrics([
      {label:"SIGNED-IN ACCOUNT",value:user.display_name || user.username || "Unknown",note:"Current authenticated account"},
      {label:"BACKEND ROLE",value:user.role || "—",note:"Role used by authorization middleware"},
      {label:"IAM AUDIT EVENTS",value:state.auditError ? "—" : auditCount,note:state.auditError ? "Audit endpoint unavailable" : "Latest events returned by Cartman"},
      {label:"API KEYS",value:state.keysError ? "—" : keyTotal,note:state.keysError ? "Key inventory unavailable" : "Visible to authorized administrators"}
    ])}${panel("Current account", "Identity is read from the authenticated Cartman session.", `<div class="isl-details"><div><span>Display name</span><strong>${esc(user.display_name || "—")}</strong></div><div><span>Username</span><strong>${esc(user.username || "—")}</strong></div><div><span>Role</span><strong>${esc(user.role || "—")}</strong></div><div><span>Password change required</span><strong>${user.must_change_password ? badge("Required", "warning") : badge("No", "success")}</strong></div></div>`)}${panel("Recent identity activity", "Recent records from the existing IAM audit log.", state.auditError ? errorBox(state.auditError) : table(["When", "Actor", "Action", "Resource"], events, "No IAM audit events have been recorded."), `<a class="isl-link" href="/pages/audit/">Open audit logs →</a>`)}${panel("Security administration", "Open the relevant area without duplicating user or group administration.", cards)}`;
    return shell("Identity & Access", "Review the current authenticated identity, effective backend role and recent security activity.", body);
  }

  function renderProviders() {
    const providers = [
      {name:"SAML 2.0",desc:"Enterprise federation for an external identity provider.",detail:"Requires metadata exchange, signing certificates and an ACS/login flow.",status:"Not configured"},
      {name:"OpenID Connect",desc:"Modern sign-in federation using an authorization-code flow.",detail:"Requires issuer discovery, client registration, redirect URI and token validation.",status:"Not configured"},
      {name:"LDAP / Active Directory",desc:"Directory connectivity for enterprise identity lookup.",detail:"Requires a secure directory connection, bind identity and mapping rules.",status:"Not configured"}
    ];
    const rows = providers.map(p => `<article class="isl-provider"><div class="isl-provider-top"><div class="isl-provider-icon">${p.name === "SAML 2.0" ? "S" : p.name === "OpenID Connect" ? "O" : "D"}</div>${badge(p.status, "muted")}</div><h3>${esc(p.name)}</h3><p>${esc(p.desc)}</p><div class="isl-provider-detail">${esc(p.detail)}</div></article>`).join("");
    const body = `<div class="isl-provider-grid">${rows}</div>${panel("Federation readiness", "No SAML, OIDC or LDAP authentication provider is currently connected by the application routes inspected for this build.", `<div class="isl-readiness"><div>${badge("Local Cartman authentication", "success")}<span>Current sign-in remains handled by Cartman's built-in authentication.</span></div><div>${badge("External SSO", "muted")}<span>No live provider configuration or federation callback is active.</span></div><div>${badge("Directory sync", "muted")}<span>No provider synchronization job is active.</span></div></div>`)}<div class="isl-note">Provider cards are a capability/readiness inventory, not working connection controls. No credentials or metadata are stored on this page.</div>`;
    return shell("Identity Providers", "Review supported federation patterns and the current connection state.", body, "CONFIGURATION STATUS");
  }

  function renderPolicies() {
    const policies = [
      {name:"Password change requirements",scope:"Authenticated accounts",status:"Enforced",kind:"success",detail:"New passwords require at least 14 characters in the current password-change model."},
      {name:"API key scopes and revocation",scope:"API key authentication",status:"Enforced",kind:"success",detail:"API keys are scoped, stored as hashes and can be revoked through the existing API."},
      {name:"IAM audit recording",scope:"Supported IAM actions",status:"Active",kind:"success",detail:"IAM and API-key administrative actions write audit events where implemented."},
      {name:"Multi-factor authentication enforcement",scope:"Account sign-in",status:"Not active",kind:"warning",detail:"No active MFA enforcement flow is exposed by the current settings and authentication UI."},
      {name:"Idle-session policy enforcement",scope:"Authenticated sessions",status:"Not active",kind:"warning",detail:"An idle-session enforcement policy is not activated by the current configuration values."},
      {name:"External identity federation",scope:"SAML / OIDC / LDAP",status:"Not configured",kind:"muted",detail:"No live identity provider integration is configured in this build."}
    ];
    const rows = policies.map(p => `<tr><td><strong>${esc(p.name)}</strong><small class="isl-subcell">${esc(p.scope)}</small></td><td>${badge(p.status,p.kind)}</td><td>${esc(p.detail)}</td></tr>`).join("");
    const body = `${panel("Security control status", "This page distinguishes controls that are active from configuration ideas that are not enforced.", table(["Control", "Status", "Current behavior"], rows))}<div class="isl-note"><strong>Important:</strong> this build presents the current security posture. It does not create or activate new enforcement rules. A future policy engine must be connected to the authentication and authorization middleware before a policy can be marked enforced.</div>`;
    return shell("Policies", "Review the security controls that currently affect Cartman authentication and access.", body, "CONTROL STATUS");
  }

  function renderAudit() {
    const rows = state.audit.map(item => `<tr data-isl-audit-row><td>${esc(date(item.occurred_at))}</td><td>${esc(item.actor || "—")}</td><td><code>${esc(item.action || "—")}</code></td><td>${esc(item.resource_type || "—")}</td><td>${esc(item.resource_id || "—")}</td><td><span class="isl-detail-text">${esc(JSON.stringify(item.details || {}))}</span></td></tr>`).join("");
    const body = `${metrics([{label:"RETURNED EVENTS",value:state.audit.length,note:"Maximum 200 newest IAM events"},{label:"SOURCE",value:"iam_audit_events",note:"Existing Cartman audit store"},{label:"FILTER",value:"Searchable",note:"Filter loaded records locally"},{label:"MODE",value:"Read-only",note:"Audit records are not editable here"}])}${panel("IAM audit events", "Recorded identity and access changes from the existing audit API.", `<div class="isl-toolbar"><input class="isl-input" type="search" data-isl-audit-search placeholder="Search actor, action, resource or details…" aria-label="Search audit events"><button type="button" class="isl-btn primary" data-isl-action="audit-export">Export CSV</button><button type="button" class="isl-btn" data-isl-action="refresh">Refresh</button></div>${state.auditError ? errorBox(state.auditError) : table(["Timestamp", "Actor", "Action", "Resource type", "Resource ID", "Details"], rows, "No audit records found.")}`)}<div class="isl-note">This view uses `/api/iam/audit`. It does not merge unrelated monitoring, VPN or software audit tables into the IAM log.</div>`;
    return shell("Audit Logs", "Search and export the existing identity and access audit trail.", body);
  }

  function normalizeScopes(item) {
    let value = item.scopes || item.scopes_json || [];
    if (typeof value === "string") { try { value = JSON.parse(value); } catch (_) { value = [value]; } }
    return Array.isArray(value) ? value : [];
  }
  function renderCredentials() {
    const rows = state.keys.map(item => {
      const scopes = normalizeScopes(item);
      const active = String(item.status || "").toLowerCase() === "active";
      return `<tr><td><strong>${esc(item.name || "Unnamed key")}</strong><small class="isl-subcell">${esc(item.id || "")}</small></td><td><code>${esc(item.key_prefix || "—")}••••</code></td><td>${scopes.map(s => `<span class="isl-scope">${esc(s)}</span>`).join(" ") || "—"}</td><td>${badge(item.status || "Unknown", active ? "success" : "muted")}</td><td>${esc(date(item.expires_at))}</td><td>${esc(date(item.last_used_at))}</td><td>${active ? button("Revoke", "key-revoke", item.id, "danger") : "—"}</td></tr>`;
    }).join("");
    const logRows = state.keyLogs.slice(0, 30).map(item => `<tr><td>${esc(date(item.created_at))}</td><td>${esc(item.api_key_name || "—")}</td><td><code>${esc(item.method || "—")} ${esc(item.path || "")}</code></td><td>${esc(item.client_ip || "—")}</td><td>${esc(item.status_code || item.response_status || "—")}</td></tr>`).join("");
    const body = `${metrics([{label:"API KEYS",value:state.keys.length,note:"Existing server-side key records"},{label:"ACTIVE",value:state.keys.filter(x => String(x.status).toLowerCase() === "active").length,note:"Eligible until revoked or expired"},{label:"REVOKED",value:state.keys.filter(x => String(x.status).toLowerCase() === "revoked").length,note:"Revocation status from Cartman"},{label:"ACCESS LOGS",value:state.keyLogs.length,note:"Recent API key request records"}])}${panel("API key inventory", "Keys are stored as hashes. The full token cannot be retrieved after creation.", `${state.keysError ? errorBox(state.keysError) : table(["Name", "Key prefix", "Scopes", "Status", "Expires", "Last used", "Action"], rows, "No API keys have been created.")}`, `<a class="isl-btn primary" href="/pages/api-api-keys/">Create / manage API keys →</a>`)}${panel("API key activity", "Recent requests recorded by the existing API key access log.", state.logsError ? errorBox(state.logsError) : table(["Time", "Key", "Request", "Client IP", "Status"], logRows, "No API key access events found."))}<div class="isl-note"><strong>Secrets vault:</strong> a general encrypted credentials vault is not configured in this build. This page does not accept or store plaintext passwords, private keys or arbitrary secrets. Use the existing API key workflow for API tokens.</div>`;
    return shell("Credentials & Secrets", "Review API key inventory and access history without exposing stored token material.", body);
  }

  function render(root) {
    const slug = root.dataset.identitySecurity;
    const renderer = { "identity":renderIdentity, "identity-providers":renderProviders, "policies":renderPolicies, "audit":renderAudit, "credentials-secrets":renderCredentials }[slug];
    root.innerHTML = renderer ? renderer() : `<div class="isl-app"><div class="isl-alert error">Unsupported Identity &amp; Security page.</div></div>`;
  }

  async function loadRoot(root) {
    const slug = root.dataset.identitySecurity;
    root.innerHTML = `<div class="isl-loading">Loading Cartman security data…</div>`;
    if (slug === "identity") {
      const [me,audit,keys] = await Promise.allSettled([request("/api/auth/me"),request("/api/iam/audit?limit=100"),request("/api/admin/api-keys")]);
      if (me.status === "fulfilled") state.user = me.value.user || me.value;
      else state.error = `Account information could not be loaded: ${me.reason.message}`;
      if (audit.status === "fulfilled") state.audit = Array.isArray(audit.value) ? audit.value : (audit.value.items || []);
      else state.auditError = audit.reason.message;
      if (keys.status === "fulfilled") state.keys = keys.value.items || [];
      else state.keysError = keys.reason.message;
    } else if (slug === "audit") {
      try { const data = await request("/api/iam/audit?limit=200"); state.audit = Array.isArray(data) ? data : (data.items || []); }
      catch (error) { state.auditError = error.message; }
    } else if (slug === "credentials-secrets") {
      const [keys,logs] = await Promise.allSettled([request("/api/admin/api-keys"),request("/api/admin/api-key-logs?limit=100")]);
      if (keys.status === "fulfilled") state.keys = keys.value.items || [];
      else state.keysError = keys.reason.message;
      if (logs.status === "fulfilled") state.keyLogs = logs.value.items || [];
      else state.logsError = logs.reason.message;
    }
    render(root);
  }

  function exportAudit() {
    const fields = ["occurred_at","actor","action","resource_type","resource_id","details"];
    const cell = value => `"${String(value == null ? "" : typeof value === "object" ? JSON.stringify(value) : value).replace(/"/g,'""')}"`;
    const csv = [fields.join(","), ...state.audit.map(item => fields.map(key => cell(item[key])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF",csv], {type:"text/csv;charset=utf-8;"}));
    const a = document.createElement("a"); a.href = url; a.download = "cartman-iam-audit.csv"; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  roots.forEach(root => {
    loadRoot(root);
    root.addEventListener("click", async event => {
      const action = event.target.closest("[data-isl-action]");
      if (!action) return;
      const name = action.dataset.islAction;
      if (name === "refresh") { state.auditError = state.keysError = state.logsError = state.error = ""; await loadRoot(root); return; }
      if (name === "audit-export") { exportAudit(); return; }
      if (name === "key-revoke") {
        const id = action.dataset.islId;
        if (!id || !window.confirm("Revoke this API key? Requests using it will no longer authenticate.")) return;
        action.disabled = true;
        try {
          await request(`/api/admin/api-keys/${encodeURIComponent(id)}/revoke`, {method:"POST"});
          state.notice = "API key revoked."; state.keys = (await request("/api/admin/api-keys")).items || [];
          state.keyLogs = state.keyLogs || [];
          render(root);
        } catch (error) { state.error = `Could not revoke API key: ${error.message}`; render(root); }
      }
    });
    root.addEventListener("input", event => {
      if (event.target.matches("[data-isl-audit-search]")) {
        const term = event.target.value.trim().toLowerCase();
        root.querySelectorAll("[data-isl-audit-row]").forEach(row => {
          row.hidden = !row.textContent.toLowerCase().includes(term);
        });
      }
    });
  });
})();
