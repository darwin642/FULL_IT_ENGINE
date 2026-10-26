"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const records = [
    {id:"DPL-2026-0142",name:"Microsoft 365 Apps — Ring 1",type:"Software",version:"2509 · 16.0.19231",target:"IT Workstations",devices:48,updated:"2 min ago",time:Date.now()-120000,status:"Running",owner:"Kaan Y.",progress:72,description:"Pilot rollout for Microsoft 365 Apps across the IT workstation group."},
    {id:"DPL-2026-0141",name:"Windows Security Cumulative Update",type:"Patch",version:"KB5066128",target:"Corporate Laptops",devices:126,updated:"18 min ago",time:Date.now()-1080000,status:"Completed",owner:"System Admin",progress:100,description:"Monthly security update rollout for corporate laptop endpoints."},
    {id:"DPL-2026-0140",name:"Google Chrome Enterprise",type:"Software",version:"141.0.7390.55",target:"Managed Windows",devices:214,updated:"42 min ago",time:Date.now()-2520000,status:"Completed",owner:"Endpoint Team",progress:100,description:"Enterprise browser update distributed to managed Windows devices."},
    {id:"DPL-2026-0139",name:"Windows 11 24H2 — Pilot",type:"OS Image",version:"24H2 · Build 26100",target:"Pilot Devices",devices:12,updated:"1 hr ago",time:Date.now()-3600000,status:"Failed",owner:"Kaan Y.",progress:33,description:"Pilot operating system rollout. Some demo targets reported a simulated failure."},
    {id:"DPL-2026-0138",name:"7-Zip Enterprise Package",type:"Package",version:"24.09 · x64",target:"Engineering",devices:36,updated:"2 hrs ago",time:Date.now()-7200000,status:"Queued",owner:"Package Admin",progress:0,description:"Packaged utility rollout waiting in the simulated execution queue."},
    {id:"DPL-2026-0137",name:"Microsoft Edge Security Update",type:"Patch",version:"141.0.3537.57",target:"Shared Devices",devices:83,updated:"3 hrs ago",time:Date.now()-10800000,status:"Completed",owner:"Endpoint Team",progress:100,description:"Browser security patch rollout for shared endpoint devices."},
    {id:"DPL-2026-0136",name:"Standard Workstation Image",type:"OS Image",version:"WIN11-STD-06",target:"New Starters",devices:8,updated:"Yesterday",time:Date.now()-86400000,status:"Draft",owner:"IT Operations",progress:0,description:"Draft deployment plan for newly provisioned employee workstations."},
    {id:"DPL-2026-0135",name:"7-Zip Version Alignment",type:"Package",version:"24.09 · x64",target:"Finance Devices",devices:24,updated:"Yesterday",time:Date.now()-90000000,status:"Failed",owner:"Package Admin",progress:58,description:"Package version alignment. The demo job is marked as failed for review."},
    {id:"DPL-2026-0134",name:"Visual Studio Code",type:"Software",version:"1.105.1",target:"Developer Workstations",devices:31,updated:"2 days ago",time:Date.now()-172800000,status:"Completed",owner:"Dev Tools Team",progress:100,description:"Developer tool rollout across the engineering workstation group."}
  ];

  const sharedStore = window.CartmanDeploymentDemo;
  if (sharedStore) {
    const merged = sharedStore.merge(records);
    records.splice(0, records.length, ...merged);
  }

  const state = {query:"",status:"all",type:"all",sort:"updated",direction:"desc",menuId:null,toastTimer:null,activeRecord:null};
  const iconFor = type => ({Software:"▤","OS Image":"▣",Patch:"↻",Package:"◇"}[type] || "▤");
  const slug = status => status.toLowerCase().replace(/\s+/g,"-");
  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const visibleRecords = () => records.filter(r => {
    const haystack = [r.id,r.name,r.type,r.version,r.target,r.owner,r.status].join(" ").toLocaleLowerCase();
    return haystack.includes(state.query) && (state.status === "all" || r.status === state.status) && (state.type === "all" || r.type === state.type);
  }).sort((a,b) => {
    let av = a[state.sort], bv = b[state.sort];
    if (state.sort === "updated") { av = a.time; bv = b.time; }
    const cmp = typeof av === "number" && typeof bv === "number" ? av-bv : String(av).localeCompare(String(bv));
    return cmp * (state.direction === "asc" ? 1 : -1);
  });

  function toast(message) {
    const node = $("#dc-toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { node.hidden = true; }, 2600);
  }

  function renderMetrics() {
    const total = records.length;
    const success = records.filter(r => r.status === "Completed").length;
    const running = records.filter(r => r.status === "Running").length;
    const failed = records.filter(r => r.status === "Failed").length;
    const rate = total ? Math.round(success / total * 100) : 0;
    $("#dc-total").textContent = total;
    $("#dc-success").textContent = success;
    $("#dc-running").textContent = running;
    $("#dc-attention").textContent = failed;
    $("#dc-success-rate").textContent = `${rate}%`;
    $("#dc-health-percent").textContent = `${rate}%`;
    $("#dc-legend-success").textContent = success;
    $("#dc-legend-running").textContent = running;
    $("#dc-legend-failed").textContent = failed;
    $("#dc-progress-success").style.width = `${success/Math.max(total,1)*100}%`;
    $("#dc-progress-running").style.width = `${running/Math.max(total,1)*100}%`;
    $("#dc-progress-failed").style.width = `${failed/Math.max(total,1)*100}%`;
    $("#dc-ring").style.background = `conic-gradient(#36c99a ${rate*3.6}deg, #36c99a16 0deg)`;
    $("#dc-ring").style.border = "5px solid var(--surface-color, #111a29)";
  }

  function renderRows() {
    const rows = visibleRecords();
    $("#dc-rows").innerHTML = rows.map(r => `
      <tr data-id="${escapeHTML(r.id)}">
        <td><div class="dc-name-cell"><span class="dc-type-icon ${slug(r.type)}">${iconFor(r.type)}</span><span class="dc-name-stack"><strong>${escapeHTML(r.name)}</strong><small>${escapeHTML(r.id)}</small></span></div></td>
        <td><span class="dc-type-text">${escapeHTML(r.type)}</span></td>
        <td><span class="dc-targets">${r.devices} devices</span><br><span style="font-size:9px;color:var(--text-muted,#7f8ba0)">${escapeHTML(r.target)}</span></td>
        <td><span class="dc-date"><strong>${escapeHTML(r.updated)}</strong><small>by ${escapeHTML(r.owner)}</small></span></td>
        <td><span class="dc-status ${slug(r.status)}">${escapeHTML(r.status)}</span></td>
        <td><button class="dc-row-menu" data-menu="${escapeHTML(r.id)}" aria-label="Actions for ${escapeHTML(r.name)}" aria-expanded="false">⋯</button></td>
      </tr>`).join("");
    $("#dc-count").textContent = `Showing ${rows.length} of ${records.length} deployments`;
    $("#dc-empty").hidden = rows.length !== 0;
    $(".dc-table-wrap").hidden = rows.length === 0;
    $(".dc-table-bottom").hidden = rows.length === 0;
    $$("[data-sort]").forEach(button => {
      const marker = button.querySelector("span");
      if (marker) marker.textContent = state.sort === button.dataset.sort ? (state.direction === "asc" ? "↑" : "↓") : "↕";
    });
  }

  function render() { renderMetrics(); renderRows(); }

  function hideMenu() {
    $("#dc-menu").hidden = true;
    $$("[data-menu]").forEach(b => b.setAttribute("aria-expanded","false"));
    state.menuId = null;
  }

  function openMenu(button) {
    const menu = $("#dc-menu");
    const id = button.dataset.menu;
    if (state.menuId === id && !menu.hidden) { hideMenu(); return; }
    hideMenu();
    state.menuId = id;
    button.setAttribute("aria-expanded","true");
    menu.hidden = false;
    const rect = button.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.right-menuRect.width, window.innerWidth-menuRect.width-8));
    let top = rect.bottom + 5;
    if (top + menuRect.height > window.innerHeight-8) top = rect.top-menuRect.height-5;
    menu.style.left = `${left}px`;
    menu.style.top = `${Math.max(8,top)}px`;
  }

  function showDetails(record) {
    if (!record) return;
    state.activeRecord = record;
    $("#dc-detail-title").textContent = record.name;
    $("#dc-detail-body").innerHTML = `<div class="dc-detail-grid">
      <div class="dc-detail-item"><label>Deployment ID</label><strong>${escapeHTML(record.id)}</strong></div>
      <div class="dc-detail-item"><label>Status</label><strong><span class="dc-status ${slug(record.status)}">${escapeHTML(record.status)}</span></strong></div>
      <div class="dc-detail-item"><label>Type</label><strong>${escapeHTML(record.type)}</strong></div>
      <div class="dc-detail-item"><label>Version / release</label><strong>${escapeHTML(record.version)}</strong></div>
      <div class="dc-detail-item"><label>Target group</label><strong>${escapeHTML(record.target)}</strong></div>
      <div class="dc-detail-item"><label>Target devices</label><strong>${record.devices}</strong></div>
      <div class="dc-detail-item"><label>Initiated by</label><strong>${escapeHTML(record.owner)}</strong></div>
      <div class="dc-detail-item"><label>Progress</label><strong>${record.progress}%</strong></div>
      <div class="dc-detail-item dc-detail-wide"><label>Description</label><strong>${escapeHTML(record.description)}</strong></div>
      <div class="dc-detail-item dc-detail-wide"><label>Preview note</label><strong style="color:var(--text-muted,#9aa6ba);font-weight:400">This is a local demonstration record. No real deployment was started.</strong></div>
    </div>`;
    $("#dc-detail-backdrop").hidden = false;
  }

  function closeModal(which) {
    const backdrop = $(`#dc-${which}-backdrop`);
    if (backdrop) backdrop.hidden = true;
  }

  $("#dc-search").addEventListener("input", event => { state.query = event.target.value.trim().toLocaleLowerCase(); hideMenu(); renderRows(); });
  $("#dc-status").addEventListener("change", event => { state.status = event.target.value; hideMenu(); renderRows(); });
  $("#dc-type").addEventListener("change", event => { state.type = event.target.value; hideMenu(); renderRows(); });
  $("#dc-reset").addEventListener("click", resetFilters);
  $("#dc-empty-reset").addEventListener("click", resetFilters);

  function resetFilters() {
    state.query = ""; state.status = "all"; state.type = "all";
    $("#dc-search").value = ""; $("#dc-status").value = "all"; $("#dc-type").value = "all";
    hideMenu(); renderRows();
  }

  $$("[data-sort]").forEach(button => button.addEventListener("click", () => {
    if (state.sort === button.dataset.sort) state.direction = state.direction === "asc" ? "desc" : "asc";
    else { state.sort = button.dataset.sort; state.direction = "asc"; }
    renderRows();
  }));

  $("#dc-rows").addEventListener("click", event => {
    const button = event.target.closest("[data-menu]");
    if (button) openMenu(button);
  });

  $("#dc-menu").addEventListener("click", async event => {
    const button = event.target.closest("[data-action]");
    if (!button || !state.menuId) return;
    const record = records.find(r => r.id === state.menuId);
    const action = button.dataset.action;
    hideMenu();
    if (!record) return;
    if (action === "details") showDetails(record);
    if (action === "copy") {
      try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(record.id);
        else {
          const input = document.createElement("textarea");
          input.value = record.id; input.style.position = "fixed"; input.style.opacity = "0";
          document.body.appendChild(input); input.select();
          const copied = document.execCommand("copy"); input.remove();
          if (!copied) throw new Error("Clipboard unavailable");
        }
        toast(`Copied ${record.id}`);
      } catch { toast(`Deployment ID: ${record.id}`); }
    }
    if (action === "review") toast(`Demo record ${record.id} reviewed for this session.`);
  });

  document.addEventListener("click", event => {
    if (!event.target.closest("#dc-menu") && !event.target.closest("[data-menu]")) hideMenu();
  });
  window.addEventListener("resize", hideMenu);
  window.addEventListener("scroll", hideMenu, true);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      hideMenu(); closeModal("detail"); closeModal("add");
    }
  });
  $$("[data-close]").forEach(button => button.addEventListener("click", () => closeModal(button.dataset.close)));
  ["dc-detail-backdrop","dc-add-backdrop"].forEach(id => {
    $(`#${id}`).addEventListener("click", event => {
      if (event.target.id === id) $(`#${id}`).hidden = true;
    });
  });

  $("#dc-add").addEventListener("click", () => { $("#dc-add-backdrop").hidden = false; $("#dc-add-form").elements.name.focus(); });
  $("#dc-add-form").addEventListener("submit", event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") || "").trim();
    const target = String(form.get("target") || "").trim();
    if (!name || !target) return;
    const type = String(form.get("type") || "Software");
    const record = {
      id:`DPL-DEMO-${String(Date.now()).slice(-6)}`, name, type,
      version:String(form.get("version") || "Unspecified").trim() || "Unspecified",
      target, devices:0, updated:"Just now", time:Date.now(), status:"Draft",
      owner:"Current session", progress:0,
      description:"A draft created in the local demo session. No installation or remote execution takes place."
    };
    records.unshift(record);
    if (sharedStore) sharedStore.upsert(record);
    state.sort = "updated"; state.direction = "desc";
    closeModal("add"); event.currentTarget.reset(); resetFilters(); render();
    toast("Demo draft created for this session.");
  });

  $("#dc-export").addEventListener("click", () => {
    const rows = visibleRecords();
    const header = ["ID","Name","Type","Version","Target","Devices","Status","Updated","Owner"];
    const csv = [header,...rows.map(r => [r.id,r.name,r.type,r.version,r.target,r.devices,r.status,r.updated,r.owner])]
      .map(row => row.map(value => `"${String(value).replace(/"/g,'""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF",csv],{type:"text/csv;charset=utf-8"}));
    const link = document.createElement("a");
    link.href = url; link.download = "cartman-deployment-demo.csv";
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    toast("Current deployment view exported as CSV.");
  });

  render();
})();
