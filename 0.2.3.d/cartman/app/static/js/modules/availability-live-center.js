/* CARTMAN_AVAILABILITY_LIVE_CENTER_V1
 * Dedicated controller for /pages/availability/.
 * Reads saved Cartman availability results; does not claim to run a fresh network probe.
 */
(() => {
  "use strict";
  const MARKER = "CARTMAN_AVAILABILITY_LIVE_CENTER_V1";
  if (window.__cartmanAvailabilityLiveCenter === MARKER) return;
  window.__cartmanAvailabilityLiveCenter = MARKER;
  const API = {
    availability: "/api/monitoring/availability?limit=1000",
    services: "/api/monitoring/services?limit=300",
    devices: "/api/devices"
  };
  const REFRESH_MS = 30000;
  const state = {host:null, module:null, checks:[], services:[], devices:[], query:"", status:"all", sort:"latest", range:"7d", from:"", to:"", selected:"", page:1, loading:false, error:"", updatedAt:null, timer:null};
  const $ = (sel, root=document) => root.querySelector(sel);
  const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const nfmt = v => Number(v || 0).toLocaleString();
  const isObj = v => !!v && typeof v === "object" && !Array.isArray(v);
  function listOf(data, keys=["items","results","records","checks","availability","services","devices"]) {
    if (Array.isArray(data)) return data;
    if (!isObj(data)) return [];
    for (const key of keys) if (Array.isArray(data[key])) return data[key];
    for (const key of ["data","result","response"]) if (isObj(data[key])) {
      const nested = listOf(data[key], keys); if (nested.length) return nested;
    }
    return [];
  }
  async function getJSON(url) {
    const res = await fetch(url, {credentials:"same-origin", cache:"no-store", headers:{Accept:"application/json"}});
    const raw = await res.text(); let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = {detail:raw.slice(0,200)}; }
    if (!res.ok) { const e = new Error(data.detail || data.message || `${res.status} ${res.statusText}`); e.status=res.status; throw e; }
    return data;
  }
  function pick(r, keys, fallback="") { for (const k of keys) if (r && r[k] !== null && r[k] !== undefined && r[k] !== "") return r[k]; return fallback; }
  function stamp(v) {
    if (v == null || v === "") return null;
    if (typeof v === "number") return new Date(v > 100000000000 ? v : v*1000);
    let s=String(v).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(s)) s=s.replace(" ","T")+"Z";
    const d=new Date(s); return Number.isNaN(d.getTime()) ? null : d;
  }
  function timeText(v) { const d=stamp(v); return d ? d.toLocaleString([], {year:"numeric",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit"}) : "Not recorded"; }
  function ago(v) { const d=stamp(v); if (!d) return "No timestamp"; const sec=Math.max(0,Math.round((Date.now()-d.getTime())/1000)); if (sec<60) return `${sec}s ago`; if (sec<3600) return `${Math.floor(sec/60)}m ago`; if (sec<86400) return `${Math.floor(sec/3600)}h ago`; return `${Math.floor(sec/86400)}d ago`; }
  function statusOf(r) { return String(pick(r,["status","state","result","check_status","availability_status"],"Unknown")).trim(); }
  function kind(status) { const s=String(status||"").toLowerCase(); if (/up|online|reachable|success|healthy|operational|available|ok/.test(s) && !/unavailable/.test(s)) return "up"; if (/down|offline|unreachable|failed|failure|critical|unavailable|timeout|error/.test(s)) return "down"; if (/warning|degraded|slow|partial/.test(s)) return "warn"; return "unknown"; }
  function targetOf(r) { return String(pick(r,["target","target_name","url","hostname","host","address","name","service_name"],"Unnamed target")); }
  function deviceIdOf(r) { return String(pick(r,["device_id","deviceId","asset_id","computer_id"],"")); }
  function typeOf(r) { return String(pick(r,["check_type","method","protocol","type","target_type","kind"],"Availability")); }
  function checkedAt(r) { return pick(r,["checked_at","last_checked_at","checkedAt","observed_at","recorded_at","timestamp","created_at","updated_at"],null); }
  function responseMs(r) { const v=pick(r,["response_ms","latency_ms","duration_ms","response_time_ms","latency","response_time"],null); if (v===null) return null; const n=Number(v); if (!Number.isFinite(n) || n<0) return null; const hasSeconds = r.response_time !== undefined && r.response_time === v && r.response_time_ms === undefined && r.latency_ms === undefined && r.duration_ms === undefined; return hasSeconds ? n*1000 : n; }
  function keyOf(r) { return [deviceIdOf(r).toLowerCase(),targetOf(r).toLowerCase(),typeOf(r).toLowerCase()].join("::"); }
  function rangeBounds() {
    const now=Date.now();
    if (state.range === "all") {
      const recorded = state.checks.map(r => stamp(checkedAt(r))).filter(Boolean).map(d => d.getTime());
      return {start: recorded.length ? Math.min(...recorded) : now-7*86400000, end: now};
    }
    if (state.range === "custom" && state.from && state.to) { const a=new Date(state.from).getTime(), b=new Date(state.to).getTime(); if (Number.isFinite(a)&&Number.isFinite(b)&&b>=a) return {start:a,end:b}; }
    const span=state.range==="1d"?86400000:state.range==="15d"?15*86400000:state.range==="30d"?30*86400000:7*86400000;
    return {start:now-span,end:now};
  }
  function withinRange(r) { const t=stamp(checkedAt(r)); if (state.range === "all") return true; if (!t) return state.range !== "custom"; const b=rangeBounds(); return t.getTime()>=b.start && t.getTime()<=b.end; }
  function deviceName(id) { const d=state.devices.find(x=>String(pick(x,["id","device_id"],""))===String(id)); return d ? String(pick(d,["name","hostname","device_name"],id)) : (id || "—"); }
  function groupedChecks() {
    const map=new Map();
    for (const r of state.checks) {
      const key=keyOf(r); const prev=map.get(key);
      if (!prev) map.set(key,{key,latest:r,history:[r]});
      else { prev.history.push(r); const a=stamp(checkedAt(r)), b=stamp(checkedAt(prev.latest)); if (a && (!b || a>b)) prev.latest=r; }
    }
    return Array.from(map.values()).map(g=>{
      g.history.sort((a,b)=>(stamp(checkedAt(b))?.getTime()||0)-(stamp(checkedAt(a))?.getTime()||0));
      g.filteredHistory=g.history.filter(withinRange);
      g.status=statusOf(g.latest); g.statusKind=kind(g.status); g.target=targetOf(g.latest); g.deviceId=deviceIdOf(g.latest); g.type=typeOf(g.latest); g.checked=checkedAt(g.latest); g.response=responseMs(g.latest);
      const observations=g.filteredHistory.filter(r=>kind(statusOf(r))!=="unknown");
      g.rate=observations.length ? Math.round(observations.filter(r=>kind(statusOf(r))==="up").length/observations.length*100) : null;
      return g;
    });
  }
  function fmtMs(ms) { return ms==null ? "—" : ms<1000 ? `${Math.round(ms)} ms` : `${(ms/1000).toFixed(2)} s`; }
  function badge(status) { const k=kind(status); return `<span class="avl-badge ${k}"><i></i>${esc(status||"Unknown")}</span>`; }
  function kpi(label,value,note,icon,tone) { return `<article class="avl-kpi ${tone||""}"><div class="avl-kpi-top"><span>${esc(label)}</span><span class="avl-kpi-icon">${icon}</span></div><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`; }
  function renderTrend(groups) {
    const samples=state.checks.filter(withinRange).filter(r=>stamp(checkedAt(r))&&kind(statusOf(r))!=="unknown");
    if (!samples.length) return `<div class="avl-empty"><strong>No historical check samples</strong><span>Uptime and trend charts will appear when timestamped availability results exist.</span></div>`;
    const {start,end}=rangeBounds(); const count=state.range==="1d"?12:state.range==="30d"?10:state.range==="15d"?10:7; const span=(end-start)/count; const buckets=Array.from({length:count},(_,i)=>({start:start+i*span,end:start+(i+1)*span,up:0,down:0,total:0}));
    for (const r of samples) { const t=stamp(checkedAt(r)).getTime(); const idx=Math.min(count-1,Math.max(0,Math.floor((t-start)/span))); const b=buckets[idx]; b.total++; if(kind(statusOf(r))==="up")b.up++; else b.down++; }
    const max=Math.max(1,...buckets.map(b=>b.total));
    return `<div class="avl-trend" role="img" aria-label="Observed successful and failed availability checks">${buckets.map(b=>{const height=b.total?Math.max(8,b.total/max*100):0;const success=b.total?b.up/b.total*100:0;const label=new Date(b.start).toLocaleString([],state.range==="1d"?{hour:"2-digit",minute:"2-digit"}:{month:"short",day:"numeric"});return `<div class="avl-trend-col"><div class="avl-bar-area"><div class="avl-bar" style="height:${height}%" title="${b.total} checks · ${b.up} success · ${b.down} failed"><span class="up" style="height:${success}%"></span><span class="down" style="height:${100-success}%"></span></div></div><small>${esc(label)}</small><em>${b.total?`${Math.round(success)}%`:"—"}</em></div>`;}).join("")}</div><div class="avl-legend"><span><i class="up"></i>Successful checks</span><span><i class="down"></i>Failed checks</span><small>Observed check results, not a guarantee of end-to-end uptime.</small></div>`;
  }
  function filteredGroups() {
    const q=state.query.trim().toLowerCase(); let groups=groupedChecks().filter(g=>!q||[g.target,g.deviceId,deviceName(g.deviceId),g.type,g.status].join(" ").toLowerCase().includes(q));
    if(state.status!=="all") groups=groups.filter(g=>g.statusKind===state.status);
    if(state.sort==="target") groups.sort((a,b)=>a.target.localeCompare(b.target)); else if(state.sort==="status") groups.sort((a,b)=>a.statusKind.localeCompare(b.statusKind)); else if(state.sort==="response") groups.sort((a,b)=>(b.response??-1)-(a.response??-1)); else groups.sort((a,b)=>(stamp(checkedAt(b.latest))?.getTime()||0)-(stamp(checkedAt(a.latest))?.getTime()||0));
    return groups;
  }
  function renderTable(groups) {
    const pages=Math.max(1,Math.ceil(groups.length/10)); state.page=Math.min(state.page,pages); const start=(state.page-1)*10; const shown=groups.slice(start,start+10);
    const body=shown.map(g=>`<tr class="${state.selected===g.key?"selected":""}" tabindex="0" data-avl-select="${esc(g.key)}"><td><div class="avl-target"><span class="avl-target-icon">${g.type.toLowerCase().includes("http")?"↗":"◎"}</span><span><strong>${esc(g.target)}</strong><small>${esc(g.deviceId?deviceName(g.deviceId):g.type)}</small></span></div></td><td>${esc(g.type)}</td><td>${badge(g.status)}</td><td>${fmtMs(g.response)}</td><td><span class="avl-time">${esc(ago(g.checked))}</span><small class="avl-date">${esc(timeText(g.checked))}</small></td><td>${g.rate===null?"—":`${g.rate}%`}<small class="avl-date">${g.filteredHistory.length} samples</small></td></tr>`).join("");
    return `<div class="avl-table-wrap"><table class="avl-table"><thead><tr><th>Target</th><th>Check type</th><th>Current status</th><th>Response time</th><th>Last check</th><th>Observed success</th></tr></thead><tbody>${body||`<tr><td colspan="6"><div class="avl-empty"><strong>No matching availability records</strong><span>Try another filter or wait for check results to be reported.</span></div></td></tr>`}</tbody></table></div><div class="avl-table-foot"><span>Showing ${groups.length?start+1:0}–${Math.min(start+10,groups.length)} of ${groups.length}</span><div><button class="avl-btn secondary" data-avl-page="prev" ${state.page<=1?"disabled":""}>Previous</button><span>Page ${state.page} / ${pages}</span><button class="avl-btn secondary" data-avl-page="next" ${state.page>=pages?"disabled":""}>Next</button></div></div>`;
  }
  function renderDetail(groups) {
    const g=groups.find(x=>x.key===state.selected) || groups[0]; if(g) state.selected=g.key;
    if(!g) return `<div class="avl-panel"><div class="avl-empty"><strong>Select an availability target</strong><span>Target details and recent check results will appear here.</span></div></div>`;
    const history=g.history.slice(0,8);
    return `<section class="avl-panel avl-detail"><header class="avl-panel-head"><div><p class="avl-eyebrow">SELECTED TARGET</p><h2>${esc(g.target)}</h2><p>${esc(g.deviceId?deviceName(g.deviceId):g.type)} · ${esc(g.type)}</p></div><div>${badge(g.status)}</div></header><div class="avl-detail-grid"><div><span>Last result</span><strong>${esc(timeText(g.checked))}</strong></div><div><span>Response time</span><strong>${fmtMs(g.response)}</strong></div><div><span>Checks in range</span><strong>${g.filteredHistory.length}</strong></div><div><span>Observed success</span><strong>${g.rate===null?"—":`${g.rate}%`}</strong></div></div><h3>Recent check history</h3><div class="avl-history">${history.map(r=>`<div class="avl-history-row"><span class="avl-history-dot ${kind(statusOf(r))}"></span><span class="avl-history-status">${esc(statusOf(r))}</span><span>${fmtMs(responseMs(r))}</span><time>${esc(timeText(checkedAt(r)))}</time></div>`).join("")||`<div class="avl-empty">No saved check history.</div>`}</div>${g.deviceId?`<a class="avl-btn secondary" href="/pages/monitoring/?device_id=${encodeURIComponent(g.deviceId)}">Open device in Monitoring ↗</a>`:""}</section>`;
  }
  function render() {
    if(!state.host)return;
    const groups=filteredGroups(); const latest=groupedChecks(); const inRange=state.checks.filter(withinRange); const known=latest.filter(g=>g.statusKind!=="unknown"); const up=latest.filter(g=>g.statusKind==="up").length; const down=latest.filter(g=>g.statusKind==="down").length; const warn=latest.filter(g=>g.statusKind==="warn").length; const activeOutages=latest.filter(g=>g.statusKind==="down").length; const valid=inRange.filter(r=>kind(statusOf(r))!=="unknown"); const successes=valid.filter(r=>kind(statusOf(r))==="up").length; const successRate=valid.length?`${Math.round(successes/valid.length*100)}%`:"—"; const latencies=inRange.map(responseMs).filter(x=>x!==null); const avg=latencies.length?fmtMs(latencies.reduce((a,b)=>a+b,0)/latencies.length):"—";
    state.host.innerHTML=`<div class="avl-app"><header class="avl-header"><div><div class="avl-eyebrow">MONITORING / AVAILABILITY</div><h1>Availability</h1><p>Reachability checks, response times and outage history for monitored targets.</p></div><div class="avl-header-actions"><span class="avl-live"><i></i> SAVED CHECK DATA</span><button class="avl-btn primary" data-avl-refresh ${state.loading?"disabled":""}>${state.loading?"Refreshing…":"Refresh data"}</button></div></header>${state.error?`<div class="avl-banner error">${esc(state.error)} <button class="avl-btn secondary" data-avl-refresh>Retry</button></div>`:`<div class="avl-banner"><span class="avl-live-dot"></span><span>Reading existing availability records. This page does not claim to launch a new network probe.</span><small>${state.updatedAt?`Updated ${esc(state.updatedAt.toLocaleTimeString())}`:"Waiting for first response"}</small></div>`}<div class="avl-kpis">${kpi("Monitored targets",latest.length,"Unique target / device / check combinations","◎","blue")}${kpi("Reachable",up,"Latest recorded status","✓","green")}${kpi("Active outages",activeOutages,"Targets whose latest result is down","!","red")}${kpi("Observed success",successRate,`${nfmt(valid.length)} recorded results in range`,"↗","purple")}</div><div class="avl-grid"><section class="avl-panel"><header class="avl-panel-head"><div><h2>Availability trend</h2><p>Observed successful and failed checks over the selected period.</p></div><select class="avl-range" data-avl-range><option value="1d" ${state.range==="1d"?"selected":""}>Last 24 hours</option><option value="7d" ${state.range==="7d"?"selected":""}>Last 7 days</option><option value="15d" ${state.range==="15d"?"selected":""}>Last 15 days</option><option value="30d" ${state.range==="30d"?"selected":""}>Last 30 days</option><option value="all" ${state.range==="all"?"selected":""}>All history</option></select></header>${renderTrend(groups)}</section><section class="avl-panel"><header class="avl-panel-head"><div><h2>Current status</h2><p>Latest known result for each monitored target.</p></div></header><div class="avl-status-list"><div><span class="avl-dot up"></span><span>Reachable</span><strong>${up}</strong></div><div><span class="avl-dot warn"></span><span>Warning / degraded</span><strong>${warn}</strong></div><div><span class="avl-dot down"></span><span>Unavailable</span><strong>${down}</strong></div><div><span class="avl-dot unknown"></span><span>Unknown</span><strong>${latest.length-known.length}</strong></div></div><div class="avl-stat-note">Average recorded response time: <strong>${avg}</strong><br>Recorded samples in range: <strong>${nfmt(inRange.length)}</strong></div></section></div><section class="avl-panel"><header class="avl-panel-head"><div><h2>Availability targets</h2><p>Search, filter and sort existing target records.</p></div><span class="avl-count">${groups.length} targets</span></header><div class="avl-filters"><input type="search" data-avl-search value="${esc(state.query)}" placeholder="Search target, device, URL or check type"><select data-avl-status><option value="all" ${state.status==="all"?"selected":""}>All statuses</option><option value="up" ${state.status==="up"?"selected":""}>Reachable</option><option value="warn" ${state.status==="warn"?"selected":""}>Warning</option><option value="down" ${state.status==="down"?"selected":""}>Unavailable</option><option value="unknown" ${state.status==="unknown"?"selected":""}>Unknown</option></select><select data-avl-sort><option value="latest" ${state.sort==="latest"?"selected":""}>Latest check</option><option value="target" ${state.sort==="target"?"selected":""}>Target name</option><option value="status" ${state.sort==="status"?"selected":""}>Status</option><option value="response" ${state.sort==="response"?"selected":""}>Slowest response</option></select></div>${renderTable(groups)}</section>${renderDetail(groups)}<footer class="avl-footer"><span>Source: Cartman availability and service APIs</span><span>${state.updatedAt?`Last refreshed ${esc(state.updatedAt.toLocaleString())}`:"No successful refresh yet"}</span></footer></div>`;
  }
  async function refresh() {
    if(state.loading)return; state.loading=true; state.error=""; render();
    try {
      const results=await Promise.allSettled([getJSON(API.availability),getJSON(API.services),getJSON(API.devices)]);
      if(results[0].status!=="fulfilled") throw results[0].reason;
      state.checks=listOf(results[0].value,["items","results","records","checks","availability"]).filter(isObj);
      state.services=results[1].status==="fulfilled"?listOf(results[1].value,["items","results","records","services"]).filter(isObj):[];
      state.devices=results[2].status==="fulfilled"?listOf(results[2].value,["items","results","records","devices"]).filter(isObj):[];
      // Only use service rows as availability-like data when there are no dedicated availability rows;
      // preserve their service type and timestamps so the UI never fabricates a probe result.
      if(!state.checks.length && state.services.length) state.checks=state.services.map(s=>({...s,target:pick(s,["target","service_name","name"],"Service"),check_type:pick(s,["check_type","protocol"],"Service check"),checked_at:pick(s,["checked_at","last_checked_at","updated_at","created_at"],null)}));
      state.updatedAt=new Date();
    } catch(error) {
      state.error=error.status===401?"Authentication required. Sign in to Cartman and retry.":error.status===403?"Your Cartman role does not have permission to view availability records.":`Unable to load availability data: ${error.message}`;
    } finally {state.loading=false; render();}
  }
  function mount() {
    if(!location.pathname.replace(/\/+$/,'').toLowerCase().endsWith('/availability')) return;
    const host=document.querySelector('[data-monitor-dashboard="availability"]'); if(!host)return;
    if(host.dataset.availabilityLive==='1')return; host.dataset.availabilityLive='1'; state.host=host; state.module=host.closest('.workspace-module'); state.module?.classList.add('avl-live-mode');
    state.module?.querySelector('.workspace-eyebrow')?.remove(); state.module?.querySelector('.workspace-toolbar')?.remove(); state.module?.querySelector('.workspace-stats')?.remove(); state.module?.querySelector('.workspace-table-panel')?.remove();
    render(); void refresh(); state.timer=window.setInterval(()=>void refresh(),REFRESH_MS);
    document.addEventListener('input',e=>{if(e.target.matches('[data-avl-search]')){state.query=e.target.value;state.page=1;renderPreservingFocus(e.target);}});
    document.addEventListener('change',e=>{if(e.target.matches('[data-avl-status]')){state.status=e.target.value;state.page=1;render();}else if(e.target.matches('[data-avl-sort]')){state.sort=e.target.value;state.page=1;render();}else if(e.target.matches('[data-avl-range]')){state.range=e.target.value;render();}});
    document.addEventListener('click',e=>{const refreshButton=e.target.closest('[data-avl-refresh]');if(refreshButton){void refresh();return;}const row=e.target.closest('[data-avl-select]');if(row){state.selected=row.dataset.avlSelect;render();return;}const p=e.target.closest('[data-avl-page]');if(p){state.page=Math.max(1,state.page+(p.dataset.avlPage==='next'?1:-1));render();}});
    document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-avl-select]')){e.preventDefault();state.selected=e.target.dataset.avlSelect;render();}});
  }
  function renderPreservingFocus(input){const value=input.value; const start=input.selectionStart; const end=input.selectionEnd; render(); const newInput=$('[data-avl-search]'); if(newInput){newInput.focus();try{newInput.setSelectionRange(start,end);}catch(_){}}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
