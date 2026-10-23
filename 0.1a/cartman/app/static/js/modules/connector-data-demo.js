(() => {
"use strict";

const root = document.querySelector("#admin-page-root[data-admin-page='connectors']");
if (!root) return;

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
}[c]));

const tickets = [
  {id:"INC1001042", title:"VPN authentication failing", priority:"High", state:"In Progress", assignee:"Maya Chen", user:"alex.morgan", department:"IT Operations", updated:"2026-10-23 09:42", description:"Users report intermittent VPN authentication failures after a client update.", category:"Network"},
  {id:"INC1001039", title:"Laptop cannot access shared drive", priority:"Medium", state:"Open", assignee:"James Wilson", user:"sarah.jones", department:"Finance", updated:"2026-10-23 09:18", description:"Mapped drive returns an access denied message after sign-in.", category:"Access"},
  {id:"INC1001027", title:"Outlook profile repeatedly prompts for password", priority:"Medium", state:"Pending", assignee:"Noah Patel", user:"emily.brown", department:"Human Resources", updated:"2026-10-22 16:05", description:"The desktop mail client requests credentials several times a day.", category:"Software"},
  {id:"INC1001018", title:"New starter account provisioning", priority:"Low", state:"Resolved", assignee:"Olivia Martin", user:"liam.taylor", department:"People", updated:"2026-10-22 14:30", description:"Example request to provision a new employee account and baseline access.", category:"Identity"},
  {id:"INC1001006", title:"Shared printer unavailable", priority:"High", state:"In Progress", assignee:"Ethan Davis", user:"oliver.white", department:"Operations", updated:"2026-10-21 11:12", description:"Several users cannot print to the second-floor shared printer.", category:"Hardware"},
  {id:"INC1000991", title:"Request for application access", priority:"Low", state:"Open", assignee:"Ava Robinson", user:"mia.clark", department:"Legal", updated:"2026-10-21 10:08", description:"A user requests access to an internal business application.", category:"Access"}
];

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
  try { localStorage.setItem(historyKey, JSON.stringify(items.slice(0, 40))); } catch {}
};
const getState = () => {
  try { return JSON.parse(localStorage.getItem(stateKey)) || {}; }
  catch { return {}; }
};
const saveState = value => {
  try { localStorage.setItem(stateKey, JSON.stringify(value)); } catch {}
};

let activeTab = "catalog";
let kind = "tickets";
let searchTerm = "";
let stateFilter = "All";
let priorityFilter = "All";
let selectedRecord = null;
let feedback = "";

function pill(label, good=false) {
  return `<span class="admin-pill ${good ? "ok" : "warn"}">${esc(label)}</span>`;
}
function button(label, action, extra="") {
  return `<button class="admin-btn ${extra}" data-demo-action="${esc(action)}">${esc(label)}</button>`;
}
function notice(text) {
  return `<div class="admin-notice">${esc(text)}</div>`;
}
function shell(title, subtitle, content) {
  root.innerHTML = `
    <div class="admin-hero">
      <div><h2>${title}</h2><div class="admin-muted">${subtitle}</div></div>
      <div class="admin-actions">${button("Simulate all syncs","sync-all","primary")}</div>
    </div>
    <div class="admin-grid">
      <article class="admin-card"><div class="admin-muted">Demo integrations</div><div class="admin-kpi">2</div><p>ServiceNow and Active Directory</p></article>
      <article class="admin-card"><div class="admin-muted">Sample tickets</div><div class="admin-kpi">${tickets.length}</div><p>Fictional ITSM incidents</p></article>
      <article class="admin-card"><div class="admin-muted">Sample directory users</div><div class="admin-kpi">${users.length}</div><p>Fictional directory objects</p></article>
    </div>
    <div class="admin-tabs" role="tablist" aria-label="Connector sections">
      <button class="admin-tab" data-demo-tab="catalog" aria-selected="${activeTab==="catalog"}">Catalog</button>
      <button class="admin-tab" data-demo-tab="explorer" aria-selected="${activeTab==="explorer"}">Data Explorer</button>
      <button class="admin-tab" data-demo-tab="mapping" aria-selected="${activeTab==="mapping"}">Sync & Mapping</button>
      <button class="admin-tab" data-demo-tab="history" aria-selected="${activeTab==="history"}">Sync history</button>
    </div>
    ${content}
    ${notice("DEMO MODE — All records are synthetic examples. No ServiceNow instance, Active Directory, LDAP server, or external API is contacted. Changes remain in this browser only.")}
    <div class="admin-feedback" role="status" aria-live="polite">${esc(feedback)}</div>`;
}

function catalog() {
  const items = [
    {id:"servicenow",name:"ServiceNow",type:"ITSM",desc:"Incidents, ticket status, priority, assignees and configuration items.",count:tickets.length},
    {id:"active-directory",name:"Active Directory",type:"Identity",desc:"Sample users, UPNs, departments, account states and group memberships.",count:users.length}
  ];
  const content = `<div class="admin-grid">${items.map(item => {
    const st = getState()[item.id] || {};
    return `<article class="admin-card admin-connector">
      <div class="admin-connector-top"><div class="admin-connector-name"><div class="admin-connector-icon">${item.id==="servicenow"?"SN":"AD"}</div><div><strong>${item.name}</strong><small>${item.type}</small></div></div>${pill(st.last?"Demo synced":"Demo ready",true)}</div>
      <p>${item.desc}</p>
      <div class="admin-muted">Sample records: ${item.count} · Last demo sync: ${esc(st.last || "Not run")}</div>
      <div class="admin-actions">${button("View sample data","view:"+item.id)}${button("Test connection","test:"+item.id)}${button("Sync now","sync:"+item.id,"primary")}</div>
    </article>`;
  }).join("")}</div>`;
  shell("Connectors","Explore simulated integrations and their sample data.",content);
}

function explorer() {
  const data = kind==="tickets" ? tickets : users;
  const filtered = data.filter(item => {
    const haystack = Object.values(item).join(" ").toLowerCase();
    if (searchTerm && !haystack.includes(searchTerm.toLowerCase())) return false;
    if (kind==="tickets" && stateFilter!=="All" && item.state!==stateFilter) return false;
    if (kind==="tickets" && priorityFilter!=="All" && item.priority!==priorityFilter) return false;
    if (kind==="users" && stateFilter!=="All" && item.status!==stateFilter) return false;
    return true;
  });

  const controls = `<article class="admin-card">
    <div class="admin-actions" style="margin-bottom:14px">
      <button class="admin-btn ${kind==="tickets"?"primary":""}" data-demo-action="kind:tickets">ServiceNow tickets</button>
      <button class="admin-btn ${kind==="users"?"primary":""}" data-demo-action="kind:users">AD users</button>
    </div>
    <label class="admin-label" for="demo-search">Search records</label>
    <input class="admin-field" id="demo-search" type="search" placeholder="${kind==="tickets"?"Ticket, title, assignee or user":"Name, username, email, department or group"}" value="${esc(searchTerm)}">
    <div class="admin-grid" style="margin-top:14px">
      <div><label class="admin-label" for="demo-state"> ${kind==="tickets"?"State":"Account status"}</label>
        <select class="admin-field" id="demo-state">${(kind==="tickets"?["All","Open","In Progress","Pending","Resolved"]:["All","Enabled","Disabled"]).map(x=>`<option ${stateFilter===x?"selected":""}>${x}</option>`).join("")}</select></div>
      ${kind==="tickets"?`<div><label class="admin-label" for="demo-priority">Priority</label><select class="admin-field" id="demo-priority">${["All","High","Medium","Low"].map(x=>`<option ${priorityFilter===x?"selected":""}>${x}</option>`).join("")}</select></div>`:""}
    </div>
    <div class="admin-muted" style="margin-top:12px">${filtered.length} of ${data.length} sample records</div>
  </article>`;

  const headers = kind==="tickets"
    ? ["Ticket","Title","Priority","State","Assignee","Updated"]
    : ["Display name","Username","Department","Title","Status","Last sign-in"];
  const rows = filtered.map((item,index) => {
    const id = kind==="tickets" ? item.id : item.username;
    const values = kind==="tickets"
      ? [item.id,item.title,pill(item.priority,item.priority==="Low"),pill(item.state,item.state==="Resolved"),item.assignee,item.updated]
      : [item.name,item.username,item.department,item.title,pill(item.status,item.status==="Enabled"),item.lastSignIn];
    return `<tr>${values.map((v,i)=>`<td>${i===2 && kind==="tickets" ? v : i===(kind==="tickets"?3:4) && kind==="users" ? v : esc(v)}</td>`).join("")}<td>${button("Details","detail:"+kind+":"+index)}</td></tr>`;
  }).join("");

  let detail = "";
  if (selectedRecord && selectedRecord.kind===kind) {
    const item = data.find(x => (kind==="tickets"?x.id:x.username)===selectedRecord.id);
    if (item) {
      detail = `<article class="admin-card" style="margin-top:14px"><div class="admin-hero"><div><h3>Record details</h3><p>${esc(kind==="tickets"?item.id:item.username)}</p></div>${button("Close details","close-detail")}</div>
      <div class="admin-table-wrap"><table class="admin-table"><tbody>${Object.entries(item).map(([key,value])=>`<tr><th>${esc(key)}</th><td style="white-space:normal">${esc(value)}</td></tr>`).join("")}</tbody></table></div></article>`;
    }
  }
  const table = `<article class="admin-card"><div class="admin-table-wrap"><table class="admin-table"><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}<th>Action</th></tr></thead><tbody>${rows || `<tr><td colspan="${headers.length+1}" class="admin-empty">No matching demo records.</td></tr>`}</tbody></table></div></article>`;
  shell("Data Explorer","Search and inspect synthetic records from simulated integrations.",controls+table+detail);
}

function mapping() {
  shell("Sync & Mapping","Illustrative source-to-Cartman field mappings.",
    `<article class="admin-card"><h3>ServiceNow → Cartman</h3><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Source field</th><th>Cartman field</th><th>Mode</th></tr></thead><tbody>
    <tr><td><code>number</code></td><td><code>external_ticket_id</code></td><td>Direct</td></tr>
    <tr><td><code>short_description</code></td><td><code>title</code></td><td>Direct</td></tr>
    <tr><td><code>priority</code></td><td><code>priority</code></td><td>Normalize</td></tr>
    <tr><td><code>assigned_to</code></td><td><code>assignee</code></td><td>Normalize</td></tr>
    </tbody></table></div><h3 style="margin-top:20px">Active Directory → Cartman</h3><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Source field</th><th>Cartman field</th><th>Mode</th></tr></thead><tbody>
    <tr><td><code>displayName</code></td><td><code>display_name</code></td><td>Direct</td></tr>
    <tr><td><code>userPrincipalName</code></td><td><code>email</code></td><td>Direct</td></tr>
    <tr><td><code>department</code></td><td><code>department</code></td><td>Direct</td></tr>
    <tr><td><code>memberOf</code></td><td><code>groups</code></td><td>Normalize</td></tr>
    </tbody></table></div></article>`);
}

function history() {
  const items = getHistory();
  const rows = items.map(item=>`<tr><td>${esc(item.time)}</td><td>${esc(item.name)}</td><td>${esc(item.action)}</td><td>${esc(item.records)}</td><td>${pill("Simulated",true)}</td></tr>`).join("");
  shell("Sync history","Locally stored demo activity; not a record of external API calls.",
    `<article class="admin-card"><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Time</th><th>Integration</th><th>Action</th><th>Sample records</th><th>Result</th></tr></thead><tbody>${rows||'<tr><td colspan="5" class="admin-empty">No demo activity yet. Run a simulated sync from Catalog.</td></tr>'}</tbody></table></div></article>`);
}

function render() {
  if (activeTab==="catalog") catalog();
  else if (activeTab==="explorer") explorer();
  else if (activeTab==="mapping") mapping();
  else history();
}

function recordAction(id, action, records) {
  const names = {"servicenow":"ServiceNow","active-directory":"Active Directory"};
  const history = getHistory();
  history.unshift({time:new Date().toLocaleString(),name:names[id]||"Demo integrations",action,records});
  saveHistory(history);
  const state = getState();
  if (action==="Sync") {
    state[id] = {...(state[id]||{}),last:new Date().toLocaleString()};
    saveState(state);
  }
  feedback = `${names[id]||"Demo integrations"}: ${action} completed in demo mode. No external system was contacted.`;
}

root.addEventListener("click", event => {
  const tab = event.target.closest("[data-demo-tab]");
  if (tab) {
    activeTab = tab.dataset.demoTab;
    selectedRecord = null;
    feedback = "";
    render();
    return;
  }
  const btn = event.target.closest("[data-demo-action]");
  if (!btn) return;
  const action = btn.dataset.demoAction;

  if (action.startsWith("kind:")) {
    kind = action.slice(5); searchTerm=""; stateFilter="All"; priorityFilter="All"; selectedRecord=null; explorer(); return;
  }
  if (action==="close-detail") { selectedRecord=null; explorer(); return; }
  if (action.startsWith("detail:")) {
    const [,type,index] = action.split(":");
    const data = type==="tickets"?tickets:users;
    const item = data[Number(index)];
    if (item) selectedRecord={kind:type,id:type==="tickets"?item.id:item.username};
    explorer(); return;
  }
  if (action.startsWith("view:")) {
    activeTab="explorer"; kind=action.endsWith("servicenow")?"tickets":"users";
    searchTerm="";stateFilter="All";priorityFilter="All";selectedRecord=null;explorer();return;
  }
  if (action.startsWith("test:")) {
    const id=action.slice(5);
    recordAction(id,"Connection test",id==="servicenow"?tickets.length:users.length);
    render();return;
  }
  if (action.startsWith("sync:")) {
    const id=action.slice(5);
    recordAction(id,"Sync",id==="servicenow"?tickets.length:users.length);
    render();return;
  }
  if (action==="sync-all") {
    recordAction("servicenow","Sync",tickets.length);
    recordAction("active-directory","Sync",users.length);
    feedback="Both demo integrations simulated successfully. No external systems were contacted.";
    render();
  }
});

root.addEventListener("change", event => {
  if (event.target.id==="demo-state") {
    stateFilter=event.target.value; selectedRecord=null; explorer();
  } else if (event.target.id==="demo-priority") {
    priorityFilter=event.target.value; selectedRecord=null; explorer();
  }
});
root.addEventListener("input", event => {
  if (event.target.id==="demo-search") {
    const pos=event.target.selectionStart;
    searchTerm=event.target.value;
    explorer();
    const input=root.querySelector("#demo-search");
    if(input){input.focus();input.setSelectionRange(pos,pos);}
  }
});

render();
})();