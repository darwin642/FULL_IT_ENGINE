/* CARTMAN_API_KEYS_LIVE_V1 */
(() => {
  "use strict";
  const root = document.querySelector("#admin-page-root[data-admin-page='api']");
  if (!root || root.dataset.apiKeysLive === "1") return;
  root.dataset.apiKeysLive = "1";
  const API = { keys: "/api/admin/api-keys", directory: "/api/admin/api-directory", logs: "/api/admin/api-key-logs" };
  const scopes = ["devices:read","devices:write","inventory:read","inventory:write","monitoring:read","monitoring:write","alerts:read","alerts:write","tickets:read","tickets:write","network:read","network:write","vpn:read","vpn:write","software:read","software:write"];
  const state = { tab: "keys", keys: [], directory: [], logs: [], query: "", method: "all", logQuery: "", loading: false, error: "", notice: "", modal: false, issuedToken: "", selectedKey: null };
  const $ = (s, el=root) => el.querySelector(s);
  const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const fmt = v => v ? new Date(v).toLocaleString() : "Never";
  async function request(url, options={}) {
    const response = await fetch(url, { credentials:"same-origin", cache:"no-store", headers:{Accept:"application/json", ...(options.body ? {"Content-Type":"application/json"} : {})}, ...options });
    const raw = await response.text(); let data={}; try { data=raw?JSON.parse(raw):{}; } catch (_) { data={detail:raw.slice(0,250)}; }
    if (!response.ok) { const error=new Error(data.detail || `${response.status} ${response.statusText}`); error.status=response.status; throw error; }
    return data;
  }
  const pill = (label, good=false) => `<span class="ac-pill ${good?"good":"muted"}">${esc(label)}</span>`;
  function topStats() {
    return `<div class="ac-kpis"><article><span>API keys</span><strong>${state.keys.length}</strong><small>Issued key records</small></article><article><span>Active keys</span><strong>${state.keys.filter(k=>k.status==="Active").length}</strong><small>Not revoked or expired</small></article><article><span>API endpoints</span><strong>${state.directory.length}</strong><small>Registered FastAPI routes</small></article><article><span>Key requests</span><strong>${state.logs.length}</strong><small>Recorded bearer-key requests</small></article></div>`;
  }
  function keysView() {
    const query=state.query.toLowerCase();
    const rows=state.keys.filter(k=>[k.name,k.key_prefix,k.owner_username,(k.scopes||[]).join(" "),k.status].join(" ").toLowerCase().includes(query));
    return `<section class="ac-card"><header class="ac-section-head"><div><h2>API keys</h2><p>Create scoped credentials for external applications calling Cartman.</p></div><button class="ac-btn primary" data-create-key>＋ Create API key</button></header>
      <div class="ac-filters"><label>Search<input type="search" data-key-search placeholder="Name, prefix, owner or scope" value="${esc(state.query)}"></label></div>
      <div class="ac-table-wrap"><table class="ac-table"><thead><tr><th>Name</th><th>Key prefix</th><th>Owner</th><th>Scopes</th><th>Created</th><th>Expires</th><th>Last used</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows.map(k=>`<tr><td><strong>${esc(k.name)}</strong></td><td><code>${esc(k.key_prefix)}••••••</code></td><td>${esc(k.owner_username)}</td><td><div class="ac-scope-list">${(k.scopes||[]).map(s=>`<span>${esc(s)}</span>`).join("")}</div></td><td>${esc(fmt(k.created_at))}</td><td>${esc(fmt(k.expires_at))}</td><td>${esc(fmt(k.last_used_at))}<small>${esc(k.last_used_ip||"")}</small></td><td>${pill(k.status,k.status==="Active")}</td><td>${k.status==="Active"?`<button class="ac-link danger" data-revoke-key="${esc(k.id)}">Revoke</button>`:"—"}</td></tr>`).join("")||`<tr><td colspan="9"><div class="ac-empty">${state.loading?"Loading API keys…":"No API keys found. Create a key for your first external application."}</div></td></tr>`}</tbody></table></div>
      <p class="ac-footnote">The full token is shown only once at creation. Cartman stores a SHA-256 token hash, not the usable secret.</p></section>`;
  }
  function directoryView() {
    const q=state.query.toLowerCase();
    const rows=state.directory.filter(x=>(state.method==="all"||x.method===state.method)&&[x.path,x.name,x.summary,x.scope].join(" ").toLowerCase().includes(q));
    return `<section class="ac-card"><header class="ac-section-head"><div><h2>API directory</h2><p>Generated from the FastAPI route registry. This is the API surface currently registered in this Cartman build.</p></div><span class="ac-count">${rows.length} endpoints</span></header><div class="ac-filters"><label>Search endpoint<input type="search" data-api-search placeholder="Path, name or scope" value="${esc(state.query)}"></label><label>HTTP method<select data-api-method><option value="all">All methods</option>${["GET","POST","PUT","PATCH","DELETE"].map(m=>`<option value="${m}" ${state.method===m?"selected":""}>${m}</option>`).join("")}</select></label></div>
      <div class="ac-table-wrap"><table class="ac-table"><thead><tr><th>Method</th><th>Endpoint</th><th>Handler</th><th>API key scope</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${pill(x.method,x.method==="GET")}</td><td><code>${esc(x.path)}</code></td><td><strong>${esc(x.name)}</strong><small>${esc(x.summary||"")}</small></td><td>${x.scope==="session-authenticated"?pill("Session only"):pill(x.scope,true)}</td></tr>`).join("")||`<tr><td colspan="4"><div class="ac-empty">No matching endpoints.</div></td></tr>`}</tbody></table></div><p class="ac-footnote">API-key bearer authentication is scoped to the supported resource families. Endpoints marked Session only require a Cartman user session and are not exposed to API keys.</p></section>`;
  }
  function logsView() {
    const q=state.logQuery.toLowerCase();
    const rows=state.logs.filter(x=>[x.api_key_name,x.method,x.path,x.client_ip,String(x.status_code||"")].join(" ").toLowerCase().includes(q));
    return `<section class="ac-card"><header class="ac-section-head"><div><h2>API activity</h2><p>Requests authenticated with Cartman bearer API keys. No synthetic usage metrics are displayed.</p></div><button class="ac-btn" data-refresh>Refresh logs</button></header><div class="ac-filters"><label>Search activity<input type="search" data-log-search placeholder="Key, endpoint, method or IP" value="${esc(state.logQuery)}"></label></div><div class="ac-table-wrap"><table class="ac-table"><thead><tr><th>Time</th><th>API key</th><th>Method</th><th>Endpoint</th><th>Client IP</th><th>HTTP status</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(fmt(x.created_at))}</td><td>${esc(x.api_key_name)}</td><td>${pill(x.method,x.method==="GET")}</td><td><code>${esc(x.path)}</code></td><td>${esc(x.client_ip)}</td><td>${x.status_code==null?pill("Pending"):pill(String(x.status_code),x.status_code<400)}</td></tr>`).join("")||`<tr><td colspan="6"><div class="ac-empty">No API-key requests have been recorded yet. Requests made with a valid Bearer token will appear here.</div></td></tr>`}</tbody></table></div></section>`;
  }
  function createModal() {
    if(!state.modal)return "";
    return `<div class="ac-backdrop" data-close-modal><section class="ac-modal" role="dialog" aria-modal="true" aria-labelledby="ac-key-title"><header><div><span class="ac-eyebrow">CREDENTIAL CREATION</span><h2 id="ac-key-title">Create API key</h2><p>Issue a new scoped credential for an external application.</p></div><button class="ac-btn" type="button" data-close-modal>Close</button></header><form data-key-form><label>Key name<input name="name" maxlength="120" required placeholder="e.g. Infrastructure reporting"></label><label>Expiration<select name="expires_in_days"><option value="30">30 days</option><option value="90" selected>90 days</option><option value="365">365 days</option><option value="0">Never expires</option></select></label><fieldset><legend>Permission scopes</legend><p>Select only the access this application requires.</p><div class="ac-scope-checks">${scopes.map(s=>`<label><input type="checkbox" name="scopes" value="${s}" > ${s}</label>`).join("")}</div></fieldset><div class="ac-warning">The secret is displayed once after creation. Copy it and store it in your application's secure configuration.</div><div class="ac-form-error" data-form-error hidden></div><footer><button class="ac-btn" type="button" data-close-modal>Cancel</button><button class="ac-btn primary" type="submit">Create API key</button></footer></form></section></div>`;
  }
  function tokenModal() {
    if(!state.issuedToken)return "";
    return `<div class="ac-backdrop"><section class="ac-modal" role="dialog" aria-modal="true"><header><div><span class="ac-eyebrow">COPY NOW</span><h2>API key created</h2><p>This is the only time Cartman will reveal the complete token.</p></div></header><div class="ac-warning">Keep this token private. Anyone who has it can use the selected scopes until it expires or is revoked.</div><label>Bearer token<div class="ac-token-row"><code>${esc(state.issuedToken)}</code><button class="ac-btn" type="button" data-copy-token>Copy</button></div></label><footer><button class="ac-btn primary" type="button" data-token-done>I've copied the key</button></footer></section></div>`;
  }
  function render() {
    const tabs=[["keys","API keys"],["directory","API directory"],["logs","API activity"]];
    root.innerHTML=`<div class="ac-app"><header class="ac-hero"><div><span class="ac-eyebrow">ADMINISTRATION / DEVELOPER ACCESS</span><h2>API Management</h2><p>Manage Cartman's inbound API access, issue scoped keys and inspect registered endpoints.</p></div><div class="ac-hero-tag">INBOUND API</div></header>${topStats()}${state.error?`<div class="ac-notice error">${esc(state.error)}</div>`:""}${state.notice?`<div class="ac-notice">${esc(state.notice)}</div>`:""}<nav class="ac-tabs">${tabs.map(([id,label])=>`<button data-tab="${id}" class="${state.tab===id?"active":""}">${label}</button>`).join("")}</nav>${state.tab==="keys"?keysView():state.tab==="directory"?directoryView():logsView()}<div class="ac-bottom-note">API key authentication uses Bearer tokens and explicit scopes. External request execution is limited to the endpoint families shown in the directory.</div>${createModal()}${tokenModal()}</div>`;
  }
  async function load() {
    state.loading=true; state.error=""; render();
    const results=await Promise.allSettled([request(API.keys),request(API.directory),request(API.logs)]);
    if(results[0].status==="fulfilled")state.keys=results[0].value.items||[]; else state.error=results[0].reason.message;
    if(results[1].status==="fulfilled")state.directory=results[1].value.items||[]; else state.error=state.error||results[1].reason.message;
    if(results[2].status==="fulfilled")state.logs=results[2].value.items||[]; else state.error=state.error||results[2].reason.message;
    state.loading=false; render();
  }
  root.addEventListener("click",async event=>{
    const tab=event.target.closest("[data-tab]"); if(tab){state.tab=tab.dataset.tab;render();return;}
    if(event.target.closest("[data-create-key]")){state.modal=true;render();return;}
    if(event.target.closest('button[data-close-modal]')||event.target.matches('.ac-backdrop[data-close-modal]')){state.modal=false;render();return;}
    if(event.target.closest("[data-refresh]")){await load();return;}
    const revoke=event.target.closest("[data-revoke-key]"); if(revoke){if(!confirm("Revoke this API key? Applications using it will immediately lose access."))return;try{await request(`${API.keys}/${encodeURIComponent(revoke.dataset.revokeKey)}/revoke`,{method:"POST"});state.notice="API key revoked.";await load();}catch(e){state.error=e.message;render();}return;}
    if(event.target.closest("[data-copy-token]")){try{await navigator.clipboard.writeText(state.issuedToken);state.notice="API key copied to clipboard.";render();}catch(e){state.error="Clipboard access was unavailable. Select and copy the token manually.";render();}return;}
    if(event.target.closest("[data-token-done]")){state.issuedToken="";state.notice="Key created. The full token will not be shown again.";render();return;}
  });
  root.addEventListener("input",event=>{if(event.target.matches("[data-key-search]")){state.query=event.target.value;render();const el=$("[data-key-search]");el?.focus();}if(event.target.matches("[data-api-search]")){state.query=event.target.value;render();const el=$("[data-api-search]");el?.focus();}if(event.target.matches("[data-log-search]")){state.logQuery=event.target.value;render();const el=$("[data-log-search]");el?.focus();}});
  root.addEventListener("change",event=>{if(event.target.matches("[data-api-method]")){state.method=event.target.value;render();}});
  root.addEventListener("submit",async event=>{
    const form=event.target.closest("[data-key-form]");if(!form)return;event.preventDefault();
    const data=new FormData(form);const payload={name:data.get("name"),expires_in_days:Number(data.get("expires_in_days")),scopes:data.getAll("scopes")};
    const button=form.querySelector('button[type="submit"]');if(button){button.disabled=true;button.textContent="Creating…";}
    try{const result=await request(API.keys,{method:"POST",body:JSON.stringify(payload)});state.modal=false;state.issuedToken=result.token;state.notice="API key metadata saved. Copy the one-time token now.";await load();state.issuedToken=result.token;render();}
    catch(e){const box=form.querySelector("[data-form-error]");if(box){box.hidden=false;box.textContent=e.message;}if(button){button.disabled=false;button.textContent="Create API key";}}
  });
  load();
})();
