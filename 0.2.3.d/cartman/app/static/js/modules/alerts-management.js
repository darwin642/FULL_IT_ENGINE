/* CARTMAN_ALERTS_MANAGEMENT_UI_V1 — API-backed live/completed alert workflow */
(() => {
  "use strict";
  if (window.__cartmanAlertsManagement === "CARTMAN_ALERTS_MANAGEMENT_UI_V1") return;
  window.__cartmanAlertsManagement = "CARTMAN_ALERTS_MANAGEMENT_UI_V1";
  const $ = (s, r=document) => r.querySelector(s);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const fmtDate = value => { if (!value) return "Not recorded"; const d=new Date(value); return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat(undefined,{year:"numeric",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit"}).format(d); };
  const since = value => { if (!value) return "—"; const d=new Date(value), s=Math.max(0,Math.floor((Date.now()-d.getTime())/1000)); if(!Number.isFinite(s)) return "—"; if(s<60)return `${s}s`; if(s<3600)return `${Math.floor(s/60)}m`; if(s<86400)return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`; return `${Math.floor(s/86400)}d ${Math.floor((s%86400)/3600)}h`; };
  const titleOf = item => item.title || "Monitoring alert";
  const sevLabel = s => ({critical:"Critical",error:"Error",high:"High",warning:"Warning",medium:"Medium",low:"Low",info:"Info"}[String(s||"").toLowerCase()] || s || "Warning");
  const state = {view:"live", q:"", severity:"all", status:"all", sortBy:"created_at", sortDir:"desc", page:0, limit:8, items:[], selectedId:null, counts:{live:0,completed:0}, canComplete:false, loading:true, error:"", modal:false, submitting:false, success:""};

  function findHost() {
    const main = document.querySelector('main,[role="main"],[data-page-content],#page-content,#pageContent,.main-content,.app-content');
    if (main) return main;
    const heading = [...document.querySelectorAll("h1,h2,.page-title,[data-page-title]")].find(n => /\balerts\b/i.test(n.textContent||""));
    return heading?.closest(".page-content,.page-main,.workspace-content,.content-area,.module-content") || document.body;
  }
  const host = findHost();
  if (!host) return;
  host.innerHTML = `<div id="cartman-alerts-root" class="cam-root">
    <header class="cam-header"><div><div class="cam-eyebrow"><span></span> MONITORING & RESPONSE</div><h1>Alerts</h1><p>Review live alerts, inspect affected devices and record resolutions.</p></div><div class="cam-header-actions"><span class="cam-live-pill"><i></i> LIVE API</span><button type="button" class="cam-btn" data-action="refresh">↻ Refresh</button></div></header>
    <nav class="cam-tabs" aria-label="Alert views"><button type="button" data-view="live" class="is-active">Live Alerts <span data-count-live>—</span></button><button type="button" data-view="completed">Completed Alerts <span data-count-completed>—</span></button></nav>
    <section class="cam-summary" id="cam-summary"><div class="cam-stat"><span>Open alerts</span><strong>—</strong><small>Awaiting resolution</small></div><div class="cam-stat"><span>Completed alerts</span><strong>—</strong><small>Resolution records</small></div><div class="cam-stat"><span>Critical / error</span><strong>—</strong><small>Current open alerts</small></div></section>
    <div class="cam-notice" id="cam-notice" role="status" hidden></div><div class="cam-error" id="cam-error" role="alert" hidden></div>
    <section class="cam-filters"><label class="cam-search"><span>Search alerts</span><input type="search" data-filter="q" placeholder="Code, title, device or details…" autocomplete="off"></label><label><span>Severity</span><select data-filter="severity"><option value="all">All severities</option><option value="critical">Critical</option><option value="error">Error</option><option value="high">High</option><option value="warning">Warning</option><option value="medium">Medium</option><option value="low">Low</option><option value="info">Info</option></select></label><label><span>Status</span><select data-filter="status"><option value="all">All statuses</option><option value="open">Open</option><option value="acknowledged">Acknowledged</option></select></label><label><span>Sort by</span><select data-filter="sortBy"><option value="created_at">Created time</option><option value="severity">Severity</option><option value="device_name">Device</option><option value="title">Alert title</option><option value="alert_code">Alert code</option></select></label><button type="button" class="cam-btn cam-sort-dir" data-action="sort-dir" title="Toggle sort order">↓ Newest</button></section>
    <section class="cam-content"><div class="cam-list-panel"><div class="cam-panel-heading"><div><h2 data-list-heading>Live alerts</h2><p data-list-subtitle>Each alert can be inspected individually.</p></div><span class="cam-result-count" data-result-count>—</span></div><div id="cam-list" class="cam-list"><div class="cam-loading">Connecting to the authenticated Cartman Alerts API…</div></div><div class="cam-pagination"><button type="button" class="cam-btn" data-action="prev" disabled>← Previous</button><span data-page-label>Page 1</span><button type="button" class="cam-btn" data-action="next" disabled>Next →</button></div></div><aside id="cam-detail" class="cam-detail"><div class="cam-detail-empty"><span class="cam-empty-icon">◎</span><strong>Select an alert</strong><p>Choose an alert from the list to inspect its details and available actions.</p></div></aside></section>
    <div class="cam-modal-backdrop" id="cam-modal" hidden><section class="cam-modal" role="dialog" aria-modal="true" aria-labelledby="cam-modal-title"><button type="button" class="cam-modal-close" data-action="modal-close" aria-label="Close">×</button><div class="cam-modal-icon">✓</div><h2 id="cam-modal-title">Complete alert</h2><p class="cam-modal-intro">Explain how the problem was resolved. This explanation is saved with the alert and completion time.</p><label><span>Resolution explanation <b>*</b></span><textarea id="cam-completion-explanation" rows="5" maxlength="4000" placeholder="Describe the investigation, fix and validation…"></textarea></label><div class="cam-modal-foot"><span id="cam-char-count">0 / 4000</span><div><button type="button" class="cam-btn" data-action="modal-close">Cancel</button><button type="button" class="cam-btn cam-btn-primary" data-action="confirm-complete">Complete alert</button></div></div><div id="cam-modal-error" class="cam-error" hidden role="alert"></div></section></div>
  </div>`;
  const root = $("#cartman-alerts-root");

  async function api(url, options={}) {
    const response = await fetch(url, {credentials:"same-origin", ...options, headers:{"Accept":"application/json", ...(options.body?{"Content-Type":"application/json"}:{}), ...(options.headers||{})}});
    let data; try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data.detail || data.message || `Cartman API returned HTTP ${response.status}`);
    return data;
  }
  function params() { const p=new URLSearchParams({view:state.view,q:state.q,severity:state.severity,status:state.view==="live"?state.status:"all",sort_by:state.sortBy,sort_dir:state.sortDir,limit:String(state.limit),offset:String(state.page*state.limit)}); return p.toString(); }
  function selected() { return state.items.find(item=>String(item.id)===String(state.selectedId)) || null; }
  function showError(message) { const el=$("#cam-error",root); el.hidden=!message; el.textContent=message||""; }
  function showNotice(message) { const el=$("#cam-notice",root); el.hidden=!message; el.textContent=message||""; if(message) setTimeout(()=>{if(el.textContent===message){el.hidden=true;el.textContent="";}},4500); }
  function renderSummary() {
    const live=state.counts.live||0, completed=state.counts.completed||0, critical=state.counts.critical_open ?? state.items.filter(i=>!i.is_completed&&["critical","error","high"].includes(String(i.severity).toLowerCase())).length;
    $("#cam-summary",root).innerHTML=`<div class="cam-stat"><span>Live alerts</span><strong>${live}</strong><small>Not yet completed</small></div><div class="cam-stat"><span>Completed alerts</span><strong>${completed}</strong><small>Recorded resolutions</small></div><div class="cam-stat"><span>Critical / high / error</span><strong>${critical}</strong><small>On this page and filter</small></div>`;
    $("[data-count-live]",root).textContent=live; $("[data-count-completed]",root).textContent=completed;
  }
  function card(item) {
    const sel=String(item.id)===String(state.selectedId);
    return `<button type="button" class="cam-alert-card ${sel?"is-selected":""}" data-select-alert="${esc(item.id)}"><span class="cam-card-top"><span class="cam-code">${esc(item.alert_code)}</span><span class="cam-severity sev-${esc(item.severity)}">${esc(sevLabel(item.severity))}</span><span class="cam-status ${item.is_completed?"is-completed":""}">${item.is_completed?"Completed":esc(item.status)}</span></span><strong class="cam-card-title">${esc(titleOf(item))}</strong><span class="cam-card-resource"><span>▣</span> ${esc(item.device_name||"Unknown device")}${item.device_id?` <small>· ${esc(item.device_id)}</small>`:""}</span>${item.details?`<span class="cam-card-details">${esc(item.details)}</span>`:""}<span class="cam-card-bottom"><span>Created ${esc(fmtDate(item.created_at))}</span><span>${item.is_completed?`Completed ${esc(fmtDate(item.completed_at))}`:`Open ${esc(since(item.created_at))}`}</span></span></button>`;
  }
  function renderList(data) {
    $("[data-list-heading]",root).textContent=state.view==="live"?"Live alerts":"Completed alerts";
    $("[data-list-subtitle]",root).textContent=state.view==="live"?"Select an alert to inspect or complete it.":"Resolution records, completion explanations and timestamps.";
    $("[data-result-count]",root).textContent=`${data.total} result${data.total===1?"":"s"}`;
    const list=$("#cam-list",root);
    list.innerHTML=state.items.length?state.items.map(card).join(""):`<div class="cam-empty"><span class="cam-empty-icon">${state.view==="live"?"✓":"◷"}</span><strong>${state.view==="live"?"No live alerts":"No completed alerts"}</strong><p>${state.view==="live"?"There are no alerts matching the selected filters.":"No completed alert records match the selected filters."}</p></div>`;
    const pages=Math.max(1,Math.ceil(data.total/state.limit));
    $("[data-page-label]",root).textContent=`Page ${state.page+1} of ${pages}`;
    $("[data-action=prev]",root).disabled=state.page<=0;
    $("[data-action=next]",root).disabled=state.page+1>=pages;
    root.querySelectorAll("[data-view]").forEach(button=>button.classList.toggle("is-active",button.dataset.view===state.view));
    root.querySelectorAll('[data-filter="status"]').forEach(el=>{el.disabled=state.view==="completed";});
  }
  function inspectURL(item) {
    const url=new URL("/pages/monitoring/",location.origin);
    url.searchParams.set("inspect_alert","1"); url.searchParams.set("alert_id",String(item.id)); url.searchParams.set("alert_code",String(item.alert_code||""));
    if(item.device_id!==null&&item.device_id!==undefined&&item.device_id!=="")url.searchParams.set("device_id",String(item.device_id));
    if(item.device_name)url.searchParams.set("device_name",String(item.device_name));
    if(item.title)url.searchParams.set("alert_title",String(item.title));
    location.href=url.pathname+url.search;
  }
  function renderDetail() {
    const item=selected(), panel=$("#cam-detail",root);
    if(!item) { panel.innerHTML=`<div class="cam-detail-empty"><span class="cam-empty-icon">◎</span><strong>Select an alert</strong><p>Choose an alert from the list to inspect its details and available actions.</p></div>`; return; }
    panel.innerHTML=`<div class="cam-detail-head"><div><span class="cam-detail-code">${esc(item.alert_code)}</span><span class="cam-severity sev-${esc(item.severity)}">${esc(sevLabel(item.severity))}</span></div><span class="cam-status ${item.is_completed?"is-completed":""}">${item.is_completed?"Completed":esc(item.status)}</span></div><h2>${esc(titleOf(item))}</h2><p class="cam-detail-resource">${esc(item.device_name||"Unknown device")}${item.device_id?` · Device ID ${esc(item.device_id)}`:""}</p><div class="cam-detail-grid"><div><span>First seen</span><strong>${esc(fmtDate(item.created_at))}</strong></div><div><span>${item.is_completed?"Completed at":"Duration"}</span><strong>${esc(item.is_completed?fmtDate(item.completed_at):since(item.created_at))}</strong></div><div><span>Source record</span><strong>Monitoring</strong></div><div><span>Alert ID</span><strong>${esc(item.id)}</strong></div></div><section class="cam-detail-section"><h3>Alert details</h3><p>${esc(item.details||"No additional details were recorded for this alert.")}</p></section>${item.is_completed?`<section class="cam-resolution"><h3>Resolution explanation</h3><p>${esc(item.completion_note||"No completion explanation was recorded for this historic alert.")}</p><small>Completed by ${esc(item.completed_by||"Not recorded")} · ${esc(fmtDate(item.completed_at))}</small></section>`:""}<div class="cam-detail-actions"><button type="button" class="cam-btn" data-action="inspect">↗ Inspect in Monitor</button>${!item.is_completed&&state.canComplete?`<button type="button" class="cam-btn cam-btn-primary" data-action="complete-open">✓ Complete</button>`:""}</div>${!state.canComplete&&!item.is_completed?`<p class="cam-permission-note">Your role can view alerts but cannot complete them.</p>`:""}`;
  }
  async function refresh({keepSelection=true}={}) {
    state.loading=true; showError("");
    if(!state.items.length) $("#cam-list",root).innerHTML=`<div class="cam-loading">Loading alerts from Cartman…</div>`;
    try {
      const data=await api(`/api/alerts-management?${params()}`);
      state.items=Array.isArray(data.items)?data.items:[]; state.counts=data.counts||{live:0,completed:0}; state.canComplete=Boolean(data.can_complete); state.total=Number(data.total||0);
      if(!keepSelection || !state.items.some(i=>String(i.id)===String(state.selectedId)))state.selectedId=state.items.length?state.items[0].id:null;
      state.success=""; renderSummary(); renderList(data); renderDetail();
    } catch(err) { showError(`${err.message}. Check that Cartman is signed in and the Alerts API is available.`); $("#cam-list",root).innerHTML=`<div class="cam-empty"><strong>Alerts could not be loaded</strong><p>${esc(err.message)}</p><button type="button" class="cam-btn" data-action="refresh">Retry</button></div>`; }
    finally { state.loading=false; }
  }
  function openModal() { const item=selected(); if(!item||item.is_completed||!state.canComplete)return; state.modal=true; $("#cam-modal",root).hidden=false; $("#cam-modal-error",root).hidden=true; $("#cam-completion-explanation",root).value=""; $("#cam-char-count",root).textContent="0 / 4000"; setTimeout(()=>$("#cam-completion-explanation",root).focus(),20); }
  function closeModal() { state.modal=false; $("#cam-modal",root).hidden=true; }
  async function completeSelected() {
    const item=selected(), box=$("#cam-completion-explanation",root), explanation=String(box.value||"").trim();
    const err=$("#cam-modal-error",root); err.hidden=true; err.textContent="";
    if(!item)return;
    if(explanation.length<5) {err.hidden=false;err.textContent="Please enter at least 5 characters explaining how the issue was resolved.";box.focus();return;}
    if(state.submitting)return; state.submitting=true;
    const button=$("[data-action=confirm-complete]",root); button.disabled=true; button.textContent="Saving…";
    try { const data=await api(`/api/alerts-management/${encodeURIComponent(item.id)}/complete`,{method:"POST",body:JSON.stringify({explanation})}); closeModal(); state.view="completed"; state.page=0; state.selectedId=data.item?.id ?? item.id; state.success=`${item.alert_code} marked as completed.`; await refresh({keepSelection:false}); showNotice(state.success); }
    catch(error) {err.hidden=false;err.textContent=error.message;}
    finally {state.submitting=false;button.disabled=false;button.textContent="Complete alert";}
  }
  root.addEventListener("click", event => {
    const target=event.target.closest("[data-action],[data-view],[data-select-alert]"); if(!target)return;
    if(target.hasAttribute("data-view")) { const view=target.dataset.view; if(view!==state.view){state.view=view;state.page=0;state.selectedId=null;refresh({keepSelection:false});} return; }
    if(target.hasAttribute("data-select-alert")) {state.selectedId=target.dataset.selectAlert;renderList({total:state.total||state.items.length});renderDetail();return;}
    switch(target.dataset.action){case "refresh":refresh();break;case "prev":if(state.page>0){state.page--;refresh({keepSelection:false});}break;case "next":if((state.page+1)*state.limit<(state.total||0)){state.page++;refresh({keepSelection:false});}break;case "sort-dir":state.sortDir=state.sortDir==="desc"?"asc":"desc";target.textContent=state.sortDir==="desc"?"↓ Newest":"↑ Oldest";state.page=0;refresh({keepSelection:false});break;case "inspect":{const item=selected();if(item)inspectURL(item);break;}case "complete-open":openModal();break;case "modal-close":closeModal();break;case "confirm-complete":completeSelected();break;}
  });
  let searchTimer=null;
  root.addEventListener("input",event=>{if(event.target.id==="cam-completion-explanation"){$("#cam-char-count",root).textContent=`${event.target.value.length} / 4000`;return;}if(event.target.matches('[data-filter="q"]')){state.q=event.target.value;state.page=0;clearTimeout(searchTimer);searchTimer=setTimeout(()=>refresh({keepSelection:false}),250);}});
  root.addEventListener("change",event=>{const el=event.target;if(!el.matches("[data-filter]"))return;const key=el.dataset.filter;state[key]=el.value;state.page=0;refresh({keepSelection:false});});
  root.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("#cam-modal",root).hidden)closeModal();if(event.key==="Enter"&&event.target.matches(".cam-alert-card")){event.target.click();}});
  $("#cam-modal",root).addEventListener("click",event=>{if(event.target.id==="cam-modal")closeModal();});
  refresh({keepSelection:false}); setInterval(()=>{if(!document.hidden&&!state.modal&&!state.loading)refresh({keepSelection:true});},30000);
})();
