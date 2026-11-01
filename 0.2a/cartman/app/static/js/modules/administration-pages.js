(() => {
"use strict";
const root = document.querySelector("#admin-page-root");
if (!root) return;

const page = root.dataset.adminPage;
const read = (key, fallback) => {
    try {
        const value = JSON.parse(localStorage.getItem("cartman-admin-" + key));
        return value ?? fallback;
    } catch { return fallback; }
};
const save = (key, value) => {
    try { localStorage.setItem("cartman-admin-" + key, JSON.stringify(value)); }
    catch {}
};
const esc = value => String(value).replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
}[c]));
const btn = (label, action, extra="") =>
    `<button class="admin-btn ${extra}" data-action="${action}">${label}</button>`;
const pill = (label, ok=false) =>
    `<span class="admin-pill ${ok ? "ok" : "warn"}">${label}</span>`;
const notice = text => `<div class="admin-notice">${text}</div>`;
let feedback = "";

function shell(title, subtitle, content, actions="") {
    root.innerHTML = `
      <div class="admin-hero">
        <div><h2>${title}</h2><div class="admin-muted">${subtitle}</div></div>
        <div class="admin-actions">${actions}</div>
      </div>
      ${content}
      <div class="admin-feedback" role="status" aria-live="polite">${esc(feedback)}</div>`;
}
function settingsPage() {
    const defaults = {
        maintenance:false, sessionTimeout:true, mfa:true,
        notifications:true, telemetry:false
    };
    const values = {...defaults, ...read("settings", {})};
    const rows = [
        ["maintenance","Maintenance mode","Show a maintenance banner in the demo interface."],
        ["sessionTimeout","Session timeout","Require re-authentication after an idle period."],
        ["mfa","Multi-factor authentication","Set MFA as the preferred sign-in policy."],
        ["notifications","Admin notifications","Enable notifications for important system events."],
        ["telemetry","Usage analytics","Allow anonymous product-usage analytics in this demo."]
    ];
    shell("System settings","Manage workspace preferences and security defaults.",
      `<div class="admin-grid">
        <article class="admin-card"><div class="admin-muted">Configuration</div><div class="admin-kpi">${Object.keys(values).length}</div><p>Available preferences</p></article>
        <article class="admin-card"><div class="admin-muted">Enabled options</div><div class="admin-kpi">${Object.values(values).filter(Boolean).length}</div><p>Current local demo state</p></article>
        <article class="admin-card"><div class="admin-muted">Configuration scope</div><div class="admin-kpi" style="font-size:20px">This browser</div><p>Changes are not sent to a server.</p></article>
      </div>
      <article class="admin-card"><h3>General & security</h3><p>Toggle a preference to update this local preview.</p>
        ${rows.map(([key,name,desc])=>`<div class="admin-setting"><div><strong>${name}</strong><div class="admin-muted">${desc}</div></div><input class="admin-switch" type="checkbox" data-setting="${key}" aria-label="${name}" ${values[key]?"checked":""}></div>`).join("")}
      </article>
      ${notice("Demo only: preferences are stored in this browser using local storage. They do not configure authentication, sessions, or server security.")}`);
}
const defaultKeys = [
    {id:"key-demo-01",name:"Monitoring dashboard",scope:"metrics:read",created:"2026-10-12",status:"Active"},
    {id:"key-demo-02",name:"Inventory sync preview",scope:"inventory:read",created:"2026-10-18",status:"Active"},
    {id:"key-demo-03",name:"Legacy integration sample",scope:"assets:read",created:"2026-09-30",status:"Revoked"}
];
function apiPage() {
    const keys = read("keys", defaultKeys);
    shell("API & API Keys","Review API access metadata, permissions and example usage.",
      `<div class="admin-grid">
        <article class="admin-card"><div class="admin-muted">Demo keys</div><div class="admin-kpi">${keys.length}</div><p>Metadata records in this browser</p></article>
        <article class="admin-card"><div class="admin-muted">Active</div><div class="admin-kpi">${keys.filter(k=>k.status==="Active").length}</div><p>Active demo records</p></article>
        <article class="admin-card"><div class="admin-muted">API availability</div><div class="admin-kpi" style="font-size:20px">Preview only</div><p>No live API calls are made.</p></article>
      </div>
      <div class="admin-tabs" role="tablist"><button class="admin-tab" data-tab="keys" aria-selected="true">API keys</button><button class="admin-tab" data-tab="usage" aria-selected="false">Usage overview</button><button class="admin-tab" data-tab="docs" aria-selected="false">API reference</button></div>
      <section class="admin-card" id="api-panel"><div class="admin-hero"><div><h3>Key inventory</h3><p>Example metadata only; no real credentials are stored or displayed.</p></div>${btn("＋ Add demo key","add-key","primary")}</div>
        <div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Name</th><th>Key ID</th><th>Permission scope</th><th>Created</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>${keys.map(k=>`<tr><td>${esc(k.name)}</td><td><code>${esc(k.id)}</code></td><td>${esc(k.scope)}</td><td>${esc(k.created)}</td><td>${pill(k.status,k.status==="Active")}</td><td>${k.status==="Active"?btn("Revoke","revoke:"+esc(k.id)):"—"}</td></tr>`).join("") || '<tr><td colspan="6">No demo keys yet.</td></tr>'}</tbody></table></div>
      </section>
      ${notice("Security note: the Add demo key action creates a fictional record ID only. It does not generate a usable API token or call a backend.")}`);
}
const defaultConnectors = [
    {id:"directory",name:"Active Directory / LDAP",type:"Identity",desc:"Directory users and groups",enabled:true,last:"Never"},
    {id:"entra",name:"Microsoft Entra ID",type:"Identity",desc:"Cloud identity inventory",enabled:false,last:"Never"},
    {id:"snmp",name:"SNMP",type:"Infrastructure",desc:"Network device inventory",enabled:true,last:"Never"},
    {id:"vmware",name:"VMware vSphere",type:"Virtualization",desc:"Virtual machines and hosts",enabled:false,last:"Never"},
    {id:"monitoring",name:"Prometheus",type:"Monitoring",desc:"Metrics source integration",enabled:true,last:"Never"},
    {id:"itsm",name:"ServiceNow",type:"ITSM",desc:"Incidents and configuration items",enabled:false,last:"Never"}
];
function connectorsPage(tab="catalog") {
    const connectors = read("connectors", defaultConnectors);
    const tabs = `<div class="admin-tabs" role="tablist">
      <button class="admin-tab" data-tab="catalog" aria-selected="${tab==="catalog"}">Catalog</button>
      <button class="admin-tab" data-tab="mapping" aria-selected="${tab==="mapping"}">Sync & Mapping</button>
      <button class="admin-tab" data-tab="history" aria-selected="${tab==="history"}">Sync history</button></div>`;
    let content = "";
    if (tab==="catalog") {
        content = `<div class="admin-grid">${connectors.map(c=>`<article class="admin-card admin-connector">
          <div class="admin-connector-top"><div class="admin-connector-name"><div class="admin-connector-icon">${esc(c.name.slice(0,1))}</div><div><strong>${esc(c.name)}</strong><small>${esc(c.type)}</small></div></div>${pill(c.enabled?"Enabled":"Disabled",c.enabled)}</div>
          <p>${esc(c.desc)}</p><div class="admin-muted">Last sync: ${esc(c.last)}</div>
          <div class="admin-actions">${btn(c.enabled?"Disable":"Enable","toggle:"+esc(c.id))}${btn("Simulate sync","sync:"+esc(c.id))}</div></article>`).join("")}</div>
          ${notice("Connector actions are simulated locally. No directory, cloud account, network device or external service is contacted.")}`;
    } else if (tab==="mapping") {
        content = `<article class="admin-card"><h3>Example field mapping</h3><p>Source fields mapped to Cartman fields. These examples are not connected to a live directory.</p><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Source</th><th>Source field</th><th>Cartman field</th><th>Mode</th></tr></thead><tbody>
        <tr><td>AD / LDAP</td><td><code>userPrincipalName</code></td><td><code>email</code></td><td>Direct</td></tr>
        <tr><td>AD / LDAP</td><td><code>displayName</code></td><td><code>display_name</code></td><td>Direct</td></tr>
        <tr><td>SNMP</td><td><code>sysName</code></td><td><code>device_name</code></td><td>Direct</td></tr>
        <tr><td>Prometheus</td><td><code>instance</code></td><td><code>endpoint</code></td><td>Normalize</td></tr>
        </tbody></table></div></article>${notice("Mapping preview only. Field mappings are examples and are not applied to external data.")}`;
    } else {
        content = `<article class="admin-card"><h3>Recent sync activity</h3><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Connector</th><th>Last run</th><th>Result</th></tr></thead><tbody>
        ${connectors.filter(c=>c.last!=="Never").map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.last)}</td><td>${pill("Simulated",true)}</td></tr>`).join("") || '<tr><td colspan="3" class="admin-empty">No sync simulations yet. Use Simulate sync in Catalog.</td></tr>'}
        </tbody></table></div></article>`;
    }
    shell("Connectors","Manage integration metadata, field mapping and simulated sync runs.",tabs+content);
}
function render() {
    if (page==="settings") settingsPage();
    else if (page==="api") apiPage();
    else if (page==="connectors") connectorsPage();
}
root.addEventListener("change", event => {
    const input = event.target.closest("[data-setting]");
    if (!input) return;
    const values = read("settings", {maintenance:false,sessionTimeout:true,mfa:true,notifications:true,telemetry:false});
    values[input.dataset.setting] = input.checked;
    save("settings", values);
    feedback = "Demo preference saved in this browser.";
    settingsPage();
});
root.addEventListener("click", event => {
    const button = event.target.closest("[data-action],[data-tab]");
    if (!button) return;
    if (button.dataset.tab) {
        if (page==="api") {
            const tab = button.dataset.tab;
            if (tab==="keys") apiPage();
            else if (tab==="usage") shell("API usage overview","Illustrative metrics; not sourced from a live API.",
              `<div class="admin-grid"><article class="admin-card"><div class="admin-muted">Requests today</div><div class="admin-kpi">1,284</div><p>Illustrative sample</p></article><article class="admin-card"><div class="admin-muted">Success rate</div><div class="admin-kpi">99.2%</div><p>Illustrative sample</p></article><article class="admin-card"><div class="admin-muted">Average latency</div><div class="admin-kpi">84 ms</div><p>Illustrative sample</p></article></div><div class="admin-actions">${btn("Back to API keys","back-keys")}</div>${notice("Usage figures are fictional examples, not measurements.")}`);
            else shell("API reference","Example endpoint catalogue.",
              `<article class="admin-card"><h3>Example endpoints</h3><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr></thead><tbody><tr><td>GET</td><td><code>/api/devices</code></td><td>List devices</td></tr><tr><td>GET</td><td><code>/api/inventory</code></td><td>Read inventory</td></tr><tr><td>GET</td><td><code>/api/health</code></td><td>Health status</td></tr></tbody></table></div></article>${notice("Illustrative reference only; availability and authentication are not verified here.")}`);
        } else if (page==="connectors") connectorsPage(button.dataset.tab);
        return;
    }
    const action = button.dataset.action;
    if (action==="back-keys") { apiPage(); return; }
    if (action==="add-key") {
        const keys = read("keys", defaultKeys);
        const n = keys.length + 1;
        keys.unshift({id:`key-demo-${String(n).padStart(2,"0")}`,name:`Demo integration ${n}`,scope:"read-only",created:new Date().toISOString().slice(0,10),status:"Active"});
        save("keys", keys); feedback="Fictional demo key record added."; apiPage(); return;
    }
    if (action.startsWith("revoke:")) {
        const id=action.slice(7);
        const keys=read("keys",defaultKeys).map(k=>k.id===id?{...k,status:"Revoked"}:k);
        save("keys",keys); feedback="Demo record revoked locally."; apiPage(); return;
    }
    if (action.startsWith("toggle:")) {
        const id=action.slice(7);
        const cs=read("connectors",defaultConnectors).map(c=>c.id===id?{...c,enabled:!c.enabled}:c);
        save("connectors",cs); feedback="Connector demo state updated."; connectorsPage(); return;
    }
    if (action.startsWith("sync:")) {
        const id=action.slice(5);
        const cs=read("connectors",defaultConnectors).map(c=>c.id===id?{...c,last:new Date().toLocaleString()}:c);
        save("connectors",cs); feedback="Simulated sync recorded locally; no external connection was made."; connectorsPage(); return;
    }
});
render();
})();
