/* CARTMAN_PROCESS_USAGE_UI_V1 — real per-process telemetry only */
(() => {
  "use strict";
  if (window.__cartmanProcessUsageV1) return;
  window.__cartmanProcessUsageV1 = true;

  const $ = (s, r=document) => r.querySelector(s);
  const esc = v => String(v ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const bytes = v => {
    const n = Number(v); if (!Number.isFinite(n) || n < 0) return "—";
    if (n < 1024) return `${n.toFixed(0)} B`;
    const units = ["KB","MB","GB","TB"]; let value=n/1024, i=0;
    while(value>=1024 && i<units.length-1){value/=1024;i++;}
    return `${value.toFixed(value>=100?0:1)} ${units[i]}`;
  };
  const rate = v => { const n=Number(v); if(!Number.isFinite(n)||n<0)return "—"; return `${bytes(n)}/s`; };
  const pct = v => { const n=Number(v); return Number.isFinite(n) ? `${n.toFixed(1)}%` : "—"; };
  const timeLabel = value => { if(!value)return "Time unavailable"; const d=new Date(value); return Number.isNaN(d.getTime())?String(value):d.toLocaleString(); };
  const state = {device:null, rows:[], sort:"cpu_percent", search:"", timer:null, requestId:0, root:null, error:"", latest:null};

  function getDeviceId(device) {
    if (!device || typeof device !== "object") return "";
    const candidates = [device.id, device.device_id, device.deviceId, device.uuid, device.key];
    for (const value of candidates) if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
    return "";
  }
  function getDeviceName(device) {
    return String(device?.name || device?.hostname || device?.device_name || device?.display_name || getDeviceId(device) || "Selected device");
  }
  function findAnchor() {
    const chart = $("#mo-charts-grid");
    if (chart) return chart.closest(".mo-live-chart-card, .mo-chart-card, .mo-panel, .chart-card, section, article") || chart;
    const headings = [...document.querySelectorAll("h1,h2,h3,h4")];
    const heading = headings.find(el => /live machine monitoring/i.test(el.textContent || ""));
    return heading?.closest("section,article,.panel,.card") || heading || null;
  }
  function ensureRoot() {
    if (state.root?.isConnected) return state.root;
    const anchor = findAnchor();
    if (!anchor) return null;
    let root = $("#cartman-process-usage-root");
    if (!root) {
      root = document.createElement("section");
      root.id = "cartman-process-usage-root";
      root.className = "cpu-process-panel";
      anchor.insertAdjacentElement("afterend", root);
    }
    state.root = root;
    return root;
  }
  function renderLoading() {
    const root = ensureRoot(); if (!root) return;
    root.innerHTML = `<header class="cpu-process-head"><div><span class="cpu-process-kicker">LIVE MACHINE MONITORING</span><h2>Process resource usage</h2><p>Per-application CPU, RAM, disk I/O and network I/O for the selected computer.</p></div><span class="cpu-process-badge">Loading</span></header><div class="cpu-process-empty">Loading process telemetry…</div>`;
  }
  function renderError() {
    const root = ensureRoot(); if (!root) return;
    root.innerHTML = `<header class="cpu-process-head"><div><span class="cpu-process-kicker">LIVE MACHINE MONITORING</span><h2>Process resource usage</h2><p>${esc(getDeviceName(state.device))}</p></div><span class="cpu-process-badge is-error">API unavailable</span></header><div class="cpu-process-empty is-error">${esc(state.error || "Could not load process telemetry.")} <button class="cpu-process-btn" data-cpu-retry>Retry</button></div>`;
    $("[data-cpu-retry]", root)?.addEventListener("click", () => void load());
  }
  function getSortedFiltered() {
    const q=state.search.trim().toLowerCase();
    return state.rows.filter(row => `${row.process_name||""} ${row.pid??""}`.toLowerCase().includes(q))
      .sort((a,b) => (Number(b[state.sort])||0) - (Number(a[state.sort])||0));
  }
  function renderTable() {
    const root=ensureRoot(); if(!root)return;
    const rows=getSortedFiltered();
    const maxCpu=Math.max(1,...rows.map(r=>Number(r.cpu_percent)||0));
    const maxMem=Math.max(1,...rows.map(r=>Number(r.memory_percent)||0));
    const sortOptions=[ ["cpu_percent","CPU"],["memory_bytes","RAM"],["disk_read_bytes_per_sec","Disk read"],["network_rx_bytes_per_sec","Network RX"] ];
    const sortLabel=(v)=>sortOptions.find(x=>x[0]===v)?.[1]||"CPU";
    const cols=`<div class="cpu-process-table-wrap"><table class="cpu-process-table"><thead><tr><th>Program / PID</th><th>CPU</th><th>RAM</th><th>Disk I/O</th><th>Network I/O</th></tr></thead><tbody>${rows.map(r=>{
      const cpu=Number(r.cpu_percent), mem=Number(r.memory_percent);
      const cpuWidth=Number.isFinite(cpu)?Math.max(0,Math.min(100,cpu/maxCpu*100)):0;
      const memWidth=Number.isFinite(mem)?Math.max(0,Math.min(100,mem/maxMem*100)):0;
      return `<tr><td><div class="cpu-process-name">${esc(r.process_name||"Unknown process")}</div><small class="cpu-process-pid">PID ${esc(r.pid??"—")}</small></td><td><strong>${pct(r.cpu_percent)}</strong><span class="cpu-process-bar"><i style="width:${cpuWidth}%"></i></span></td><td><strong>${r.memory_bytes==null?"—":bytes(r.memory_bytes)}</strong><small class="cpu-process-sub">${pct(r.memory_percent)}</small><span class="cpu-process-bar ram"><i style="width:${memWidth}%"></i></span></td><td><strong>R ${rate(r.disk_read_bytes_per_sec)}</strong><small class="cpu-process-sub">W ${rate(r.disk_write_bytes_per_sec)}</small></td><td><strong>↓ ${rate(r.network_rx_bytes_per_sec)}</strong><small class="cpu-process-sub">↑ ${rate(r.network_tx_bytes_per_sec)}</small></td></tr>`;
    }).join("")}</tbody></table></div>`;
    root.innerHTML=`<header class="cpu-process-head"><div><span class="cpu-process-kicker">LIVE MACHINE MONITORING</span><h2>Process resource usage</h2><p><strong>${esc(getDeviceName(state.device))}</strong> · Latest process snapshot: ${esc(timeLabel(state.latest))}</p></div><span class="cpu-process-badge ${state.rows.length?"is-live":""}">${state.rows.length?`${state.rows.length} processes`:"No telemetry"}</span></header>
      <div class="cpu-process-toolbar"><label class="cpu-process-search"><span>Search processes</span><input type="search" data-cpu-search value="${esc(state.search)}" placeholder="Program name or PID"></label><label class="cpu-process-sort"><span>Sort by</span><select data-cpu-sort>${sortOptions.map(([v,l])=>`<option value="${v}" ${v===state.sort?"selected":""}>${l}</option>`).join("")}</select></label><span class="cpu-process-updated">Auto refresh · 15s</span></div>
      ${rows.length?cols:`<div class="cpu-process-empty"><strong>No process telemetry reported</strong><p>Cartman received no process-level sample for this computer in the last hour. CPU/RAM/disk/network values are not invented. A compatible CartmanClient process collector must report snapshots to the process telemetry API.</p><button class="cpu-process-btn" data-cpu-retry>Refresh now</button></div>`}
      <footer class="cpu-process-foot"><span>Disk and network rates require OS-provided per-process counters; unsupported values are shown as —.</span><span>${state.rows.length?`Last sample: ${esc(timeLabel(state.latest))}`:"Waiting for agent data"}</span></footer>`;
    $("[data-cpu-search]",root)?.addEventListener("input",e=>{state.search=e.target.value;renderTable();const input=$("[data-cpu-search]",state.root);if(input){input.focus();input.setSelectionRange(input.value.length,input.value.length);}});
    $("[data-cpu-sort]",root)?.addEventListener("change",e=>{state.sort=e.target.value;renderTable();});
    $("[data-cpu-retry]",root)?.addEventListener("click",()=>void load());
  }
  async function load() {
    const deviceId=getDeviceId(state.device);
    if(!deviceId){renderEmptySelection();return;}
    const requestId=++state.requestId;
    try {
      const url=`/api/monitoring/processes?device_id=${encodeURIComponent(deviceId)}&limit=50&minutes=60`;
      const response=await fetch(url,{credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}});
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(body.detail||`${response.status} ${response.statusText}`);
      if(requestId!==state.requestId)return;
      state.rows=Array.isArray(body.items)?body.items:[];state.latest=body.collected_at||null;state.error="";renderTable();
    } catch(err) { if(requestId!==state.requestId)return; state.error=err?.message||"Process telemetry API unavailable.";renderError(); }
  }
  function renderEmptySelection() {
    const root=ensureRoot(); if(!root)return;
    root.innerHTML=`<header class="cpu-process-head"><div><span class="cpu-process-kicker">LIVE MACHINE MONITORING</span><h2>Process resource usage</h2><p>Select a computer above to inspect its applications.</p></div><span class="cpu-process-badge">Waiting for selection</span></header><div class="cpu-process-empty">Choose a machine in Live machine monitoring to load per-process usage.</div>`;
  }
  function setDevice(device) {
    const id=getDeviceId(device);
    if (!id) { state.device=null; state.rows=[]; state.latest=null; renderEmptySelection(); return; }
    const old=getDeviceId(state.device);
    state.device={...device};
    if(id!==old){state.rows=[];state.latest=null;state.search="";}
    renderLoading();void load();
    clearInterval(state.timer);
    state.timer=setInterval(()=>{if(document.visibilityState!=="hidden")void load();},15000);
  }
  window.addEventListener("cartman:monitoring-selected-device", event => setDevice(event.detail?.device));
  // MutationObserver helps mount the panel once the monitoring UI creates its chart host.
  const observer=new MutationObserver(()=>{ if(state.device) { if(!state.root?.isConnected)renderTable(); } else ensureRoot(); });
  observer.observe(document.documentElement,{childList:true,subtree:true});
  window.CartmanProcessUsage={setDevice,load};
  setTimeout(()=>{ if(!state.device) renderEmptySelection(); },800);
})();
