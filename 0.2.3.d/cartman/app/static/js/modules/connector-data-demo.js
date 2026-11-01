(() => {
"use strict";

const root = document.querySelector("#admin-page-root[data-admin-page='connectors']");
if (!root) return;

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;"
}[c]));

const users = [
  {name:"Alex Morgan", username:"alex.morgan", upn:"alex.morgan@example.test", department:"IT Operations", title:"Systems Administrator", status:"Enabled", groups:"IT-Operations; VPN-Users; Server-Admins", lastSignIn:"2026-10-23 09:31"},
  {name:"Sarah Jones", username:"sarah.jones", upn:"sarah.jones@example.test", department:"Finance", title:"Financial Analyst", status:"Enabled", groups:"Finance; VPN-Users", lastSignIn:"2026-10-23 08:54"},
  {name:"Emily Brown", username:"emily.brown", upn:"emily.brown@example.test", department:"Human Resources", title:"HR Specialist", status:"Enabled", groups:"HR; Microsoft-365-Users", lastSignIn:"2026-10-22 17:42"},
  {name:"Liam Taylor", username:"liam.taylor", upn:"liam.taylor@example.test", department:"People", title:"People Coordinator", status:"Disabled", groups:"People", lastSignIn:"Never"},
  {name:"Maya Chen", username:"maya.chen", upn:"maya.chen@example.test", department:"IT Operations", title:"Service Desk Engineer", status:"Enabled", groups:"IT-Operations; ServiceDesk; VPN-Users", lastSignIn:"2026-10-23 09:12"},
  {name:"Oliver White", username:"oliver.white", upn:"oliver.white@example.test", department:"Operations", title:"Operations Associate", status:"Enabled", groups:"Operations; VPN-Users", lastSignIn:"2026-10-22 15:16"},
  {name:"Mia Clark", username:"mia.clark", upn:"mia.clark@example.test", department:"Legal", title:"Legal Counsel", status:"Enabled", groups:"Legal; Microsoft-365-Users", lastSignIn:"2026-10-23 08:05"}
];

const historyKey = "cartman-connector-demo-history";
const stateKey = "cartman-connector-demo-state";

const getHistory = () => {
  try { return JSON.parse(localStorage.getItem(historyKey)) || []; }
  catch { return []; }
};

const saveHistory = items => {
  try { localStorage.setItem(historyKey, JSON.stringify(items.slice(0, 40))); }
  catch {}
};

const getState = () => {
  try { return JSON.parse(localStorage.getItem(stateKey)) || {}; }
  catch { return {}; }
};

const saveState = value => {
  try { localStorage.setItem(stateKey, JSON.stringify(value)); }
  catch {}
};

let activeTab = "catalog";
let searchTerm = "";
let stateFilter = "All";
let selectedUserName = null;
let feedback = "";

function pill(label, good=false) {
  return `<span class="admin-pill ${good ? "ok" : "warn"}">${esc(label)}</span>`;
}

function button(label, action, extra="") {
  return `<button type="button" class="admin-btn ${extra}" data-demo-action="${esc(action)}">${esc(label)}</button>`;
}

function notice(text) {
  return `<div class="admin-notice">${esc(text)}</div>`;
}

function shell(title, subtitle, content) {
  root.innerHTML = `
    <div class="admin-hero">
      <div>
        <h2>${esc(title)}</h2>
        <div class="admin-muted">${esc(subtitle)}</div>
      </div>
      <div class="admin-actions">
        ${button("Simulate directory sync", "sync-ad", "primary")}
      </div>
    </div>

    <div class="admin-grid">
      <article class="admin-card">
        <div class="admin-muted">Demo integrations</div>
        <div class="admin-kpi">1</div>
        <p>Active Directory</p>
      </article>
      <article class="admin-card">
        <div class="admin-muted">Sample directory users</div>
        <div class="admin-kpi">${users.length}</div>
        <p>Fictional directory objects</p>
      </article>
    </div>

    <div class="admin-tabs" role="tablist" aria-label="Connector sections">
      <button class="admin-tab" data-demo-tab="catalog" aria-selected="${activeTab==="catalog"}">Catalog</button>
      <button class="admin-tab" data-demo-tab="explorer" aria-selected="${activeTab==="explorer"}">Data Explorer</button>
      <button class="admin-tab" data-demo-tab="mapping" aria-selected="${activeTab==="mapping"}">Sync &amp; Mapping</button>
      <button class="admin-tab" data-demo-tab="history" aria-selected="${activeTab==="history"}">Sync history</button>
    </div>

    ${content}

    ${notice("DEMO MODE — Directory entries are synthetic examples. No Active Directory, LDAP server, or external API is contacted.")}
    <div class="admin-feedback" role="status" aria-live="polite">${esc(feedback)}</div>`;
}

function catalog() {
  const state = getState();
  const last = state["active-directory"]?.last || "Not run";

  const content = `
    <div class="admin-grid">
      <article class="admin-card admin-connector">
        <div class="admin-connector-top">
          <div class="admin-connector-name">
            <div class="admin-connector-icon">AD</div>
            <div><strong>Active Directory</strong><small>Identity</small></div>
          </div>
          ${pill(last === "Not run" ? "Demo ready" : "Demo synced", true)}
        </div>
        <p>Sample users, UPNs, departments, account states and group memberships.</p>
        <div class="admin-muted">Sample records: ${users.length} · Last demo sync: ${esc(last)}</div>
        <div class="admin-actions">
          ${button("View sample data", "view-users")}
          ${button("Test connection", "test-ad")}
          ${button("Sync now", "sync-ad", "primary")}
        </div>
      </article>
    </div>`;

  shell("Connectors", "Manage external system integrations and connection health.", content);
}

function explorer() {
  const filtered = users.filter(user => {
    const haystack = Object.values(user).join(" ").toLowerCase();
    if (searchTerm && !haystack.includes(searchTerm.toLowerCase())) return false;
    if (stateFilter !== "All" && user.status !== stateFilter) return false;
    return true;
  });

  const controls = `
    <article class="admin-card">
      <div class="admin-actions" style="margin-bottom:14px">
        ${button("Active Directory users", "view-users", "primary")}
      </div>
      <label class="admin-label" for="demo-search">Search directory users</label>
      <input class="admin-field" id="demo-search" type="search"
        placeholder="Name, username, email, department or group"
        value="${esc(searchTerm)}">
      <div style="margin-top:14px">
        <label class="admin-label" for="demo-state">Account status</label>
        <select class="admin-field" id="demo-state">
          ${["All","Enabled","Disabled"].map(value =>
            `<option ${stateFilter===value ? "selected" : ""}>${value}</option>`
          ).join("")}
        </select>
      </div>
      <div class="admin-muted" style="margin-top:12px">${filtered.length} of ${users.length} sample records</div>
    </article>`;

  const rows = filtered.map(user => `
    <tr>
      <td>${esc(user.name)}</td>
      <td>${esc(user.username)}</td>
      <td>${esc(user.department)}</td>
      <td>${esc(user.title)}</td>
      <td>${pill(user.status, user.status === "Enabled")}</td>
      <td>${esc(user.lastSignIn)}</td>
      <td>${button("Details", "detail:" + user.username)}</td>
    </tr>`).join("");

  const table = `
    <article class="admin-card">
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr>
            <th>Display name</th><th>Username</th><th>Department</th>
            <th>Title</th><th>Status</th><th>Last sign-in</th><th>Action</th>
          </tr></thead>
          <tbody>${rows || '<tr><td colspan="7" class="admin-empty">No matching directory users.</td></tr>'}</tbody>
        </table>
      </div>
    </article>`;

  let detail = "";
  const selected = users.find(user => user.username === selectedUserName);

  if (selected) {
    detail = `
      <article class="admin-card" style="margin-top:14px">
        <div class="admin-hero">
          <div><h3>Directory user details</h3><p>${esc(selected.username)}</p></div>
          ${button("Close details", "close-detail")}
        </div>
        <div class="admin-table-wrap">
          <table class="admin-table"><tbody>
            ${Object.entries(selected).map(([key, value]) =>
              `<tr><th>${esc(key)}</th><td style="white-space:normal">${esc(value)}</td></tr>`
            ).join("")}
          </tbody></table>
        </div>
      </article>`;
  }

  shell("Data Explorer", "Search and inspect synthetic Active Directory records.", controls + table + detail);
}

function mapping() {
  const content = `
    <article class="admin-card">
      <h3>Active Directory → Cartman</h3>
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr><th>Source field</th><th>Cartman field</th><th>Mode</th></tr></thead>
          <tbody>
            <tr><td><code>displayName</code></td><td><code>display_name</code></td><td>Direct</td></tr>
            <tr><td><code>userPrincipalName</code></td><td><code>email</code></td><td>Direct</td></tr>
            <tr><td><code>department</code></td><td><code>department</code></td><td>Direct</td></tr>
            <tr><td><code>memberOf</code></td><td><code>groups</code></td><td>Normalize</td></tr>
          </tbody>
        </table>
      </div>
    </article>`;

  shell("Sync & Mapping", "Illustrative Active Directory field mappings.", content);
}

function history() {
  // Show only the retained Active Directory history in this connector screen.
  const items = getHistory().filter(item => item && item.name === "Active Directory");
  const rows = items.map(item => `
    <tr>
      <td>${esc(item.time)}</td>
      <td>${esc(item.name)}</td>
      <td>${esc(item.action)}</td>
      <td>${esc(item.records)}</td>
      <td>${pill("Simulated", true)}</td>
    </tr>`).join("");

  const content = `
    <article class="admin-card">
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr><th>Time</th><th>Integration</th><th>Action</th><th>Sample records</th><th>Result</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5" class="admin-empty">No directory demo activity yet.</td></tr>'}</tbody>
        </table>
      </div>
    </article>`;

  shell("Sync history", "Locally stored Active Directory demo activity.", content);
}

function render() {
  if (activeTab === "catalog") catalog();
  else if (activeTab === "explorer") explorer();
  else if (activeTab === "mapping") mapping();
  else history();
}

function recordAction(action) {
  const items = getHistory();
  items.unshift({
    time: new Date().toLocaleString(),
    name: "Active Directory",
    action,
    records: users.length
  });
  saveHistory(items);

  if (action === "Sync") {
    const state = getState();
    state["active-directory"] = {
      ...(state["active-directory"] || {}),
      last: new Date().toLocaleString()
    };
    saveState(state);
  }

  feedback = `Active Directory: ${action} completed in demo mode. No external system was contacted.`;
}

root.addEventListener("click", event => {
  const tab = event.target.closest("[data-demo-tab]");
  if (tab) {
    activeTab = tab.dataset.demoTab;
    selectedUserName = null;
    feedback = "";
    render();
    return;
  }

  const buttonEl = event.target.closest("[data-demo-action]");
  if (!buttonEl) return;
  const action = buttonEl.dataset.demoAction;

  if (action === "view-users") {
    activeTab = "explorer";
    selectedUserName = null;
    searchTerm = "";
    stateFilter = "All";
    render();
    return;
  }

  if (action === "test-ad") {
    recordAction("Connection test");
    render();
    return;
  }

  if (action === "sync-ad") {
    recordAction("Sync");
    render();
    return;
  }

  if (action.startsWith("detail:")) {
    selectedUserName = action.slice("detail:".length);
    explorer();
    return;
  }

  if (action === "close-detail") {
    selectedUserName = null;
    explorer();
  }
});

root.addEventListener("change", event => {
  if (event.target.id === "demo-state") {
    stateFilter = event.target.value;
    selectedUserName = null;
    explorer();
  }
});

root.addEventListener("input", event => {
  if (event.target.id !== "demo-search") return;

  const position = event.target.selectionStart;
  searchTerm = event.target.value;
  explorer();

  const input = root.querySelector("#demo-search");
  if (input) {
    input.focus();
    input.setSelectionRange(position, position);
  }
});

render();
})();