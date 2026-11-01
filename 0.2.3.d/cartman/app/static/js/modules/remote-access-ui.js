(() => {
"use strict";

const root = document.querySelector("#admin-page-root[data-admin-page='remote-access']");
if (!root) return;

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
}[c]));

const tabs = [
  ["overview", "Overview"],
  ["ssh", "SSH Profiles"],
  ["rdp", "Windows RDP"],
  ["linux", "Linux SSH / VNC"],
  ["mac", "macOS Screen Sharing"],
  ["sessions", "Sessions"],
  ["activity", "Activity Log"]
];

const methods = {
  rdp: {name:"Windows RDP", title:"Windows Remote Desktop", port:3389, auth:"password", tab:"rdp", tags:["RDP","TCP 3389"]},
  vnc: {name:"Linux VNC", title:"Linux VNC", port:5900, auth:"password", tab:"linux", tags:["VNC / RFB","TCP 5900"]},
  screen_sharing: {name:"macOS Screen Sharing", title:"macOS Screen Sharing", port:5900, auth:"system", tab:"mac", tags:["Screen Sharing","SSH companion"]}
};

let activeTab = "overview";
let sshProfiles = [];
let genericProfiles = {rdp:[], vnc:[], screen_sharing:[]};
let auditItems = [];
let sessions = [];
let capabilities = [];
let dataLoaded = false;
let dataLoading = false;
let loadErrors = [];
let formOpen = false;
let formProtocol = "ssh";
let editingId = null;
let connectTarget = null;
let connectError = "";
let feedback = "";

function button(label, action, extra="", disabled=false) {
  return `<button type="button" class="admin-btn ${extra}" data-ra-action="${esc(action)}"
    ${disabled ? 'disabled title="Connection engine is not available in this build"' : ""}>${esc(label)}</button>`;
}
function pill(label, tone="neutral") {
  return `<span class="ra-pill ra-pill-${esc(tone)}">${esc(label)}</span>`;
}
function notice(text, tone="info") {
  return `<div class="ra-notice ra-notice-${esc(tone)}"><span class="ra-notice-mark"></span><div>${esc(text)}</div></div>`;
}
async function fetchJson(url, options={}) {
  const response = await fetch(url, {credentials:"same-origin", ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message || `Request failed (${response.status})`;
    const error = new Error(detail);
    error.status = response.status;
    error.code = data.detail?.code || "";
    throw error;
  }
  return data;
}
function countProfiles() {
  return sshProfiles.length + genericProfiles.rdp.length + genericProfiles.vnc.length + genericProfiles.screen_sharing.length;
}
function itemsFor(protocol) {
  return protocol === "ssh" ? sshProfiles : (genericProfiles[protocol] || []);
}
function protocolTab(protocol) {
  return protocol === "ssh" ? "ssh" : methods[protocol]?.tab || "overview";
}
function profilePayload(profile, protocol, enabled=profile.enabled) {
  if (protocol === "ssh") {
    return {
      name: profile.name, host: profile.host, port: Number(profile.port),
      username: profile.username, auth_method: profile.auth_method,
      host_key_fingerprint: profile.host_key_fingerprint || "",
      description: profile.description || "", enabled: Boolean(enabled)
    };
  }
  return {
    protocol, name: profile.name, host: profile.host, port: Number(profile.port),
    username: profile.username || "", auth_method: profile.auth_method || "password",
    description: profile.description || "", enabled: Boolean(enabled)
  };
}

function overviewPage() {
  const readiness = [
    ["SSH","SSH Profiles",sshProfiles.length,"Terminal access profile metadata","ssh"],
    ["RDP","Windows RDP",genericProfiles.rdp.length,"Windows graphical desktop profiles","rdp"],
    ["VNC","Linux SSH / VNC",genericProfiles.vnc.length,"Linux graphical desktop profiles","linux"],
    ["MAC","macOS Screen Sharing",genericProfiles.screen_sharing.length,"Mac graphical access profiles","mac"]
  ];
  const recent = auditItems.slice(0,6).map(item => `
    <tr><td>${esc(item.occurred_at)}</td><td>${esc(item.action)}</td>
      <td>${esc(String(item.protocol).toUpperCase())}</td>
      <td>${esc(item.profile_name)}</td><td>${esc(item.actor)}</td></tr>`).join("");

  return `
    <section class="ra-stat-grid">
      <article class="ra-stat-card"><span class="ra-stat-label">SAVED PROFILES</span>
        <strong class="ra-stat-value">${dataLoaded ? countProfiles() : "—"}</strong>
        <span class="ra-stat-foot">Across all supported protocols</span></article>
      <article class="ra-stat-card"><span class="ra-stat-label">CONFIGURED METHODS</span>
        <strong class="ra-stat-value">${dataLoaded ? [sshProfiles,genericProfiles.rdp,genericProfiles.vnc,genericProfiles.screen_sharing].filter(list=>list.length).length : "—"}<span class="ra-stat-total"> / 4</span></strong>
        <span class="ra-stat-foot">Methods with at least one saved profile</span></article>
      <article class="ra-stat-card"><span class="ra-stat-label">CONNECTION ENGINE</span>
        <strong class="ra-stat-value ra-stat-text">Not enabled</strong>
        <span class="ra-stat-foot">Engine integration is the next build</span></article>
      <article class="ra-stat-card"><span class="ra-stat-label">LIVE SESSIONS</span>
        <strong class="ra-stat-value">${dataLoaded ? sessions.length : "—"}</strong>
        <span class="ra-stat-foot">Only real engine sessions are counted</span></article>
    </section>

    <section class="ra-overview-grid">
      <article class="ra-panel">
        <div class="ra-panel-heading"><div><span class="ra-eyebrow">CONFIGURATION</span>
          <h3>Protocol readiness</h3><p>Open a section to manage its saved profiles.</p></div>${pill("Profile APIs","ready")}</div>
        <div class="ra-readiness-list">
          ${readiness.map(([short,label,count,sub,tab])=>`
            <button type="button" class="ra-readiness-row" data-ra-action="tab:${tab}">
              <span class="ra-readiness-icon">${short}</span>
              <span class="ra-readiness-main"><strong>${label}</strong><small>${sub}</small></span>
              <span class="ra-readiness-count">${dataLoaded?count:"—"} <small>profiles</small></span><span class="ra-readiness-arrow">›</span>
            </button>`).join("")}
        </div>
      </article>

      <article class="ra-panel">
        <div class="ra-panel-heading"><div><span class="ra-eyebrow">RUNTIME</span>
          <h3>Connection lifecycle</h3><p>API and execution engine are separate components.</p></div>${pill("Engine planned","planned")}</div>
        <div class="ra-engine-status"><div class="ra-engine-status-icon">↗</div>
          <div><strong>No remote connection has been started</strong>
            <p>Connect actions and session endpoints are defined. SSH terminal, RDP desktop, VNC control, Screen Sharing streaming and the CartmanClient agent are not included yet.</p></div>
        </div>
        <div class="ra-api-checks">
          <div><span>Profile CRUD APIs</span>${pill("Available","ready")}</div>
          <div><span>Capabilities and audit APIs</span>${pill("Available","ready")}</div>
          <div><span>Live session execution</span>${pill("Engine required","planned")}</div>
        </div>
        ${button("Open activity log","tab:activity","ra-btn-secondary")}
      </article>
    </section>

    <section class="ra-panel ra-recent-panel">
      <div class="ra-panel-heading"><div><span class="ra-eyebrow">AUDIT TRAIL</span>
        <h3>Recent profile activity</h3><p>Profile changes recorded by the API.</p></div>
        ${button("View all","tab:activity","ra-btn-secondary")}</div>
      <div class="ra-table-wrap"><table class="ra-table">
        <thead><tr><th>Time</th><th>Action</th><th>Protocol</th><th>Profile</th><th>Actor</th></tr></thead>
        <tbody>${recent || `<tr><td colspan="5" class="ra-table-empty">${dataLoaded?"No profile changes recorded yet.":"Loading activity…"}</td></tr>`}</tbody>
      </table></div>
    </section>`;
}

function profileForm(protocol) {
  if (!formOpen || formProtocol !== protocol) return "";
  const list = itemsFor(protocol);
  const item = editingId === null ? null : list.find(profile => String(profile.id) === String(editingId));

  if (protocol === "ssh") {
    return `
      <section class="ra-panel ra-form-panel">
        <div class="ra-panel-heading"><div><span class="ra-eyebrow">SSH PROFILE</span>
          <h3>${item?"Edit SSH profile":"Add SSH profile"}</h3>
          <p>Connection metadata only. Passwords and private-key contents are not stored.</p></div>${pill("SSH","neutral")}</div>
        <form id="ra-profile-form">
          <div class="ra-form-grid">
            <label>Profile name<input name="name" required maxlength="100" value="${esc(item?.name||"")}"></label>
            <label>Host or IP<input name="host" required maxlength="253" placeholder="server.example.com" value="${esc(item?.host||"")}"></label>
            <label>Port<input name="port" type="number" min="1" max="65535" required value="${esc(item?.port??22)}"></label>
            <label>Username<input name="username" required maxlength="128" value="${esc(item?.username||"")}"></label>
            <label>Authentication<select name="auth_method">
              <option value="private_key" ${(!item||item.auth_method==="private_key")?"selected":""}>Private key</option>
              <option value="password" ${item?.auth_method==="password"?"selected":""}>Password at connection time</option>
            </select></label>
            <label>Host-key fingerprint<input name="host_key_fingerprint" maxlength="256" placeholder="SHA256:..." value="${esc(item?.host_key_fingerprint||"")}"></label>
            <label class="ra-field-wide">Description<input name="description" maxlength="500" value="${esc(item?.description||"")}"></label>
            <label>Status<select name="enabled">
              <option value="true" ${(!item||item.enabled)?"selected":""}>Enabled</option>
              <option value="false" ${item&&!item.enabled?"selected":""}>Disabled</option>
            </select></label>
          </div>
          <div class="ra-form-actions"><button type="submit" class="admin-btn primary">${item?"Save changes":"Create profile"}</button>
            ${button("Cancel","cancel-form","ra-btn-secondary")}</div>
        </form>
      </section>`;
  }

  const detail = methods[protocol];
  return `
    <section class="ra-panel ra-form-panel">
      <div class="ra-panel-heading"><div><span class="ra-eyebrow">${detail.name.toUpperCase()}</span>
        <h3>${item?"Edit profile":"Add profile"}</h3><p>Metadata is stored; passwords and session secrets are not.</p></div>${pill(detail.tags[0],"neutral")}</div>
      <form id="ra-profile-form">
        <div class="ra-form-grid">
          <label>Profile name<input name="name" required maxlength="100" value="${esc(item?.name||"")}"></label>
          <label>Host or IP<input name="host" required maxlength="253" placeholder="host.example.com" value="${esc(item?.host||"")}"></label>
          <label>Port<input name="port" type="number" min="1" max="65535" required value="${esc(item?.port??detail.port)}"></label>
          <label>Username / account<input name="username" maxlength="128" value="${esc(item?.username||"")}"></label>
          <label>Authentication<select name="auth_method">
            <option value="password" ${(!item||item.auth_method==="password")?"selected":""}>Password at connection time</option>
            <option value="system" ${item?.auth_method==="system"?"selected":""}>System / existing account</option>
          </select></label>
          <label>Status<select name="enabled">
            <option value="true" ${(!item||item.enabled)?"selected":""}>Enabled</option>
            <option value="false" ${item&&!item.enabled?"selected":""}>Disabled</option>
          </select></label>
          <label class="ra-field-wide">Description<input name="description" maxlength="500" value="${esc(item?.description||"")}"></label>
        </div>
        <div class="ra-form-actions"><button type="submit" class="admin-btn primary">${item?"Save changes":"Create profile"}</button>
          ${button("Cancel","cancel-form","ra-btn-secondary")}</div>
      </form>
    </section>`;
}

function profileTable(protocol) {
  const items = itemsFor(protocol);
  const rows = items.map(item=>`
    <tr>
      <td><strong>${esc(item.name)}</strong><span class="ra-table-sub">${esc(item.description||"No description")}</span></td>
      <td>${esc(item.host)}<span class="ra-table-sub">Port ${esc(item.port)}</span></td>
      <td>${esc(item.username||"System account")}</td>
      <td>${esc(item.auth_method==="private_key"?"Private key":item.auth_method)}</td>
      <td>${item.enabled?pill("Enabled","ready"):pill("Disabled","neutral")}</td>
      <td><div class="ra-row-actions">
        ${button("Connect","connect:"+protocol+":"+item.id,"ra-btn-primary",!item.enabled)}
        ${button("Edit","edit:"+protocol+":"+item.id,"ra-btn-secondary")}
        ${button(item.enabled?"Disable":"Enable","toggle:"+protocol+":"+item.id,"ra-btn-secondary")}
        ${button("Delete","delete:"+protocol+":"+item.id,"ra-btn-danger")}
      </div></td>
    </tr>`).join("");

  return `<div class="ra-table-wrap"><table class="ra-table">
    <thead><tr><th>Profile</th><th>Endpoint</th><th>Username</th><th>Authentication</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>${rows||`<tr><td colspan="6" class="ra-table-empty">${dataLoaded?"No profiles saved yet. Create a profile to get started.":"Loading profiles…"}</td></tr>`}</tbody>
  </table></div>`;
}

function profilesPage(protocol) {
  const details = protocol==="ssh"
    ? {title:"SSH Profiles", name:"SSH", subtitle:"Linux, macOS and SSH-capable infrastructure endpoints."}
    : {...methods[protocol], subtitle:protocol==="rdp"
       ?"Maintain Windows Remote Desktop endpoint profiles."
       :protocol==="vnc"
         ?"Maintain Linux VNC profiles. Terminal-only SSH profiles are in SSH Profiles."
         :"Maintain macOS Screen Sharing profile metadata."};

  return `
    <div class="ra-section-toolbar"><div><span class="ra-eyebrow">PROFILE MANAGEMENT</span>
      <h3>${details.title}</h3><p>${details.subtitle}</p></div>
      <div class="ra-toolbar-actions">${button("＋ Add profile","new:"+protocol,"ra-btn-primary")}</div></div>
    ${profileForm(protocol)}
    <section class="ra-panel"><div class="ra-panel-heading"><div><h3>Saved profiles</h3>
      <p>Persistent profile records stored by the Cartman API.</p></div>${pill(`${itemsFor(protocol).length} profiles`,"neutral")}</div>
      ${profileTable(protocol)}</section>`;
}

function sessionsPage() {
  const rows = sessions.map(item=>`
    <tr><td><strong>${esc(item.profile_name)}</strong><span class="ra-table-sub">${esc(item.id)}</span></td>
      <td>${esc(item.host)}</td><td>${esc(String(item.protocol).toUpperCase())}</td>
      <td>${esc(item.username||"—")}</td><td>${pill(item.status,item.status==="active"?"ready":"neutral")}</td>
      <td>${esc(item.started_at||"—")}</td><td>${button("Disconnect","disconnect:"+item.id,"ra-btn-danger")}</td></tr>`).join("");

  return `<section class="ra-panel"><div class="ra-panel-heading"><div><span class="ra-eyebrow">SESSION CONTROL</span>
    <h3>Remote sessions</h3><p>Only sessions created by the live connection engine appear here.</p></div>${pill(`${sessions.length} sessions`,"neutral")}</div>
    <div class="ra-table-wrap"><table class="ra-table"><thead><tr><th>Session</th><th>Endpoint</th><th>Protocol</th><th>User</th><th>Status</th><th>Started</th><th>Actions</th></tr></thead>
    <tbody>${rows||`<tr><td colspan="7" class="ra-table-empty">${dataLoaded?"No live sessions. Connect requests cannot start until the engine is installed.":"Loading sessions…"}</td></tr>`}</tbody></table></div></section>
    ${notice("The session API is defined. No active or synthetic sessions are created in this build.","info")}`;
}

function activityPage() {
  const rows = auditItems.map(item=>`
    <tr><td>${esc(item.occurred_at)}</td><td>${esc(item.action)}</td>
    <td>${esc(String(item.protocol).toUpperCase())}</td><td>${esc(item.profile_name)}<span class="ra-table-sub">${esc(item.profile_id)}</span></td><td>${esc(item.actor)}</td></tr>`).join("");

  return `<section class="ra-panel"><div class="ra-panel-heading"><div><span class="ra-eyebrow">AUDIT TRAIL</span>
    <h3>Profile activity</h3><p>Profile creation, edits, enable/disable and deletions.</p></div>${pill(`${auditItems.length} events`,"neutral")}</div>
    <div class="ra-table-wrap"><table class="ra-table"><thead><tr><th>Time</th><th>Action</th><th>Protocol</th><th>Profile</th><th>Actor</th></tr></thead>
    <tbody>${rows||`<tr><td colspan="5" class="ra-table-empty">${dataLoaded?"No profile activity recorded yet.":"Loading audit log…"}</td></tr>`}</tbody></table></div></section>`;
}

function connectModal() {
  if (!connectTarget) return "";
  const requiresPassword = connectTarget.auth_method === "password";
  return `<div class="ra-modal-backdrop" role="presentation">
    <section class="ra-connect-modal" role="dialog" aria-modal="true" aria-labelledby="ra-connect-title">
      <div class="ra-modal-head"><div><span class="ra-eyebrow">NEW CONNECTION</span><h3 id="ra-connect-title">Connect to ${esc(connectTarget.name)}</h3>
        <p>${esc(String(connectTarget.protocol).toUpperCase())} · ${esc(connectTarget.host)}:${esc(connectTarget.port)}</p></div>
        <button type="button" class="ra-modal-close" data-ra-action="close-connect" aria-label="Close">×</button></div>
      ${notice("This build accepts the connection request contract but has no connection engine. No session will be started.","info")}
      <form id="ra-connect-form">
        <label>Username override<input name="username_override" maxlength="128" value="${esc(connectTarget.username||"")}"></label>
        ${requiresPassword?`<label>Password for this attempt<input name="password" type="password" autocomplete="current-password" required><small>Transient request field only; Cartman does not save this password.</small></label>`:""}
        <label>Credential reference (future vault)<input name="credential_ref" maxlength="256" placeholder="Optional credential ID"></label>
        ${connectError?notice(connectError,"error"):""}
        <div class="ra-form-actions"><button type="submit" class="admin-btn primary">Start connection</button>
          ${button("Cancel","close-connect","ra-btn-secondary")}</div>
      </form>
    </section>
  </div>`;
}

function render() {
  const content = activeTab==="overview" ? overviewPage()
    : activeTab==="ssh" ? profilesPage("ssh")
    : activeTab==="rdp" ? profilesPage("rdp")
    : activeTab==="linux" ? `${notice("Linux terminal-only SSH profiles are managed under SSH Profiles; this section is for graphical VNC profiles.","info")}${profilesPage("vnc")}`
    : activeTab==="mac" ? profilesPage("screen_sharing")
    : activeTab==="sessions" ? sessionsPage()
    : activityPage();

  root.innerHTML = `
    <section class="ra-workspace-toolbar"><div class="ra-section-intro">
      <span class="ra-eyebrow">ENDPOINT ACCESS</span><h2>Access overview</h2>
      <p>Manage remote connection profiles for Windows, Linux and macOS from one workspace.</p>
    </div><div class="ra-toolbar-actions">${button(dataLoading?"Refreshing…":"Refresh data","refresh","ra-btn-secondary",dataLoading)}</div></section>

    <div class="ra-build-banner"><span class="ra-build-dot"></span><div>
      <strong>PROFILE APIS READY · CONNECTION ENGINE NOT ENABLED</strong>
      <p>Profiles, lifecycle API contracts and audit logging are prepared. Real terminal, desktop streaming and CartmanClient are a later build.</p>
    </div></div>
    ${loadErrors.length?notice(loadErrors.join(" · "),"error"):""}
    ${feedback?notice(feedback,"success"):""}
    <div class="ra-tabs" role="tablist" aria-label="Remote Access sections">
      ${tabs.map(([id,label])=>`<button type="button" role="tab" class="ra-tab" data-ra-tab="${id}" aria-selected="${activeTab===id}">${label}</button>`).join("")}
    </div>
    ${content}${connectModal()}
    <div class="ra-footer-note"><span class="ra-footer-mark">C</span><span>Cartman Remote Access</span><span>Profile APIs · No live sessions until the engine is installed</span></div>`;

  if (!dataLoaded && !dataLoading) loadData();
}

async function loadData() {
  if (dataLoading) return;
  dataLoading = true;
  render();

  const jobs = [
    ["SSH profiles","/api/ssh/profiles",r=>{sshProfiles=r.items||[];}],
    ["RDP profiles","/api/remote-access/profiles?protocol=rdp",r=>{genericProfiles.rdp=r.items||[];}],
    ["VNC profiles","/api/remote-access/profiles?protocol=vnc",r=>{genericProfiles.vnc=r.items||[];}],
    ["macOS profiles","/api/remote-access/profiles?protocol=screen_sharing",r=>{genericProfiles.screen_sharing=r.items||[];}],
    ["Capabilities","/api/remote-access/capabilities",r=>{capabilities=r.items||[];}],
    ["Sessions","/api/remote-access/sessions",r=>{sessions=r.items||[];}],
    ["Audit log","/api/remote-access/audit",r=>{auditItems=r.items||[];}]
  ];
  const results = await Promise.allSettled(jobs.map(([,url])=>fetchJson(url)));
  loadErrors = [];
  results.forEach((result,index)=>{
    if (result.status==="fulfilled") jobs[index][2](result.value);
    else loadErrors.push(`${jobs[index][0]}: ${result.reason.message}`);
  });
  dataLoading = false;
  dataLoaded = true;
  render();
}

async function saveProfile(form, protocol) {
  const values = new FormData(form);
  const isSsh = protocol==="ssh";
  const payload = isSsh ? {
    name:String(values.get("name")||"").trim(),
    host:String(values.get("host")||"").trim(),
    port:Number(values.get("port")||22),
    username:String(values.get("username")||"").trim(),
    auth_method:String(values.get("auth_method")||"private_key"),
    host_key_fingerprint:String(values.get("host_key_fingerprint")||"").trim(),
    description:String(values.get("description")||"").trim(),
    enabled:String(values.get("enabled")||"true")==="true"
  } : {
    protocol,
    name:String(values.get("name")||"").trim(),
    host:String(values.get("host")||"").trim(),
    port:Number(values.get("port")||methods[protocol].port),
    username:String(values.get("username")||"").trim(),
    auth_method:String(values.get("auth_method")||"password"),
    description:String(values.get("description")||"").trim(),
    enabled:String(values.get("enabled")||"true")==="true"
  };

  const base = isSsh?"/api/ssh/profiles":"/api/remote-access/profiles";
  const url = editingId===null?base:`${base}/${encodeURIComponent(editingId)}`;
  try {
    await fetchJson(url,{method:editingId===null?"POST":"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    feedback = editingId===null?"Profile created.":"Profile updated.";
    formOpen=false; editingId=null; dataLoaded=false;
    await loadData();
  } catch(error) {
    feedback=`Could not save profile: ${error.message}`;
    render();
  }
}

root.addEventListener("submit", event=>{
  if (event.target.id==="ra-profile-form") {
    event.preventDefault();
    saveProfile(event.target,formProtocol);
    return;
  }
  if (event.target.id==="ra-connect-form") {
    event.preventDefault();
    const values = new FormData(event.target);
    const payload = {
      protocol:connectTarget.protocol,
      profile_id:connectTarget.id,
      username_override:String(values.get("username_override")||"").trim(),
      credential_ref:String(values.get("credential_ref")||"").trim()||null
    };
    const password=String(values.get("password")||"");
    if(password) payload.password=password;
    connectError="";
    fetchJson("/api/remote-access/sessions",{
      method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)
    }).then(result=>{
      connectTarget=null;
      feedback=`Session request accepted: ${result.id||"session"}`;
      activeTab="sessions"; dataLoaded=false; loadData();
    }).catch(error=>{
      connectError=error.message;
      render();
    });
  }
});

root.addEventListener("click", async event=>{
  const tab=event.target.closest("[data-ra-tab]");
  if(tab) {
    activeTab=tab.dataset.raTab;
    formOpen=false; editingId=null; connectTarget=null; connectError=""; feedback="";
    render(); return;
  }

  const control=event.target.closest("[data-ra-action]");
  if(!control) return;
  const action=control.dataset.raAction;

  if(action.startsWith("tab:")) {
    activeTab=action.slice(4); formOpen=false; editingId=null; connectTarget=null;
    feedback=""; render(); return;
  }
  if(action==="refresh") {
    dataLoaded=false; loadErrors=[]; loadData(); return;
  }
  if(action==="cancel-form") {
    formOpen=false; editingId=null; render(); return;
  }
  if(action==="close-connect") {
    connectTarget=null; connectError=""; render(); return;
  }
  if(action.startsWith("new:")) {
    formProtocol=action.slice(4); activeTab=protocolTab(formProtocol);
    editingId=null; formOpen=true; feedback=""; render(); return;
  }
  if(action.startsWith("edit:")) {
    const parts=action.split(":");
    formProtocol=parts[1]; activeTab=protocolTab(formProtocol);
    editingId=parts.slice(2).join(":"); formOpen=true; render(); return;
  }
  if(action.startsWith("connect:")) {
    const parts=action.split(":");
    const protocol=parts[1], id=parts.slice(2).join(":");
    const profile=itemsFor(protocol).find(item=>String(item.id)===String(id));
    if(!profile) { feedback="Profile not found. Refresh and try again."; render(); return; }
    if(!profile.enabled) { feedback="This profile is disabled."; render(); return; }
    connectTarget={...profile,protocol};
    connectError=""; render(); return;
  }

  if(action.startsWith("toggle:")) {
    const parts=action.split(":");
    const protocol=parts[1], id=parts.slice(2).join(":");
    const profile=itemsFor(protocol).find(item=>String(item.id)===String(id));
    if(!profile) return;
    const base=protocol==="ssh"?"/api/ssh/profiles":"/api/remote-access/profiles";
    try {
      await fetchJson(`${base}/${encodeURIComponent(id)}`,{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(profilePayload(profile,protocol,!profile.enabled))
      });
      feedback=profile.enabled?"Profile disabled.":"Profile enabled.";
      dataLoaded=false; await loadData();
    } catch(error) { feedback=`Could not change profile status: ${error.message}`; render(); }
    return;
  }

  if(action.startsWith("delete:")) {
    const parts=action.split(":");
    const protocol=parts[1], id=parts.slice(2).join(":");
    if(!confirm("Delete this connection profile?")) return;
    const base=protocol==="ssh"?"/api/ssh/profiles":"/api/remote-access/profiles";
    try {
      await fetchJson(`${base}/${encodeURIComponent(id)}`,{method:"DELETE"});
      feedback="Profile deleted.";
      dataLoaded=false; await loadData();
    } catch(error) { feedback=`Could not delete profile: ${error.message}`; render(); }
    return;
  }

  if(action.startsWith("disconnect:")) {
    const id=action.slice("disconnect:".length);
    if(!confirm("Disconnect this remote session?")) return;
    try {
      await fetchJson(`/api/remote-access/sessions/${encodeURIComponent(id)}`,{method:"DELETE"});
      feedback="Disconnect request completed.";
      dataLoaded=false; await loadData();
    } catch(error) { feedback=`Could not disconnect session: ${error.message}`; render(); }
  }
});

render();
})();