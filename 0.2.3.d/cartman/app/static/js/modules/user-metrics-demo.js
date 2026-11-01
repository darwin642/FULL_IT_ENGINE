/* CARTMAN_USER_METRICS_LIVE_UI_V2 — real API-backed User Metrics page */
/* CARTMAN_USER_METRICS_TIME_FILTER_V1 */
/* CARTMAN_USER_METRICS_DATETIME_RANGE_V1 */
/* CARTMAN_USER_METRICS_SELECTED_CHART_UI_V1 */
/* CARTMAN_USER_METRICS_WORK_TIMELINE_UI_V1 */
(() => {
  "use strict";
  const MARKER = "CARTMAN_USER_METRICS_LIVE_UI_V2";
  if (window.__cartmanUserMetricsLive === MARKER) return;
  window.__cartmanUserMetricsLive = MARKER;
  const state = { range: "7d", customRangeActive: false, customStart: "", customEnd: "", query: "", status: "all", selected: null, summary: null, tracking: {}, trend: [], users: [], detail: null, workActivity: null, error: "", loading: true, generatedAt: null };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const $ = (selector, root=document) => root.querySelector(selector);
  const fmtDate = value => { if (!value) return "Not recorded"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, {dateStyle:"medium", timeStyle:"short"}).format(date); };
  const relativeTime = value => { if (!value) return "No recorded activity"; const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime())/1000)); if (!Number.isFinite(seconds)) return fmtDate(value); if(seconds<60)return "Just now"; if(seconds<3600)return `${Math.floor(seconds/60)} min ago`; if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`; return fmtDate(value); };
  const num = value => value === null || value === undefined ? "—" : new Intl.NumberFormat().format(value);
  const fmtDuration = value => { if (value === null || value === undefined) return "—"; const seconds=Math.max(0,Math.floor(Number(value)||0)); if(seconds<60)return `${seconds}s`; if(seconds<3600)return `${Math.floor(seconds/60)}m`; return `${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m`; };
  const statusClass = value => ({Active:"active",Idle:"idle",Offline:"offline",Disabled:"disabled"}[value] || "offline");
  const statusLabel = value => ({Active:"Active",Idle:"Idle",Offline:"Offline",Disabled:"Disabled"}[value] || value || "Unknown");
  function findHost() {
    const candidates = [...document.querySelectorAll("h1,h2,h3,[data-page-title],.page-title,.module-title")];
    const titleNode = candidates.find(node => /metrics\s*(?:&|and)\s*performance|user\s+metrics/i.test(node.textContent || ""));
    if (titleNode) {
      const main = titleNode.closest('main,[role="main"]'); if (main) return main;
      const container = titleNode.closest('.page-content,.page-main,.main-content,.workspace-content,.content-area,.page-wrapper,.module-content,[data-page-content]'); if (container) return container;
      let node = titleNode; for(let i=0; node && i<5; i++,node=node.parentElement) if(node.parentElement && node.parentElement.children.length>1 && /metrics-performance/.test(location.pathname)) return node.parentElement;
    }
    return document.querySelector('main,[role="main"],[data-page-content],#page-content,#pageContent,.main-content,.app-content');
  }
  function markup() {
    return `<div id="cartman-user-metrics-root" class="umx">
      <header class="umx-header"><div class="umx-heading"><div class="umx-eyebrow"><span></span> IDENTITY & USAGE ANALYTICS</div><h1>User Metrics</h1><p>Review real Cartman account activity, authenticated sessions and recorded audit events.</p></div><div class="umx-actions"><span class="umx-live-pill"><i></i> LIVE API</span><button class="umx-button" data-umx-refresh type="button">↻ <span>Refresh</span></button><button class="umx-button umx-button-primary" data-umx-export type="button">↓ <span>Export CSV</span></button></div></header>
      <section class="umx-toolbar"><div class="umx-toolbar-title"><strong>Reporting period</strong><span>Based on available Cartman records</span></div><div class="umx-ranges" role="group" aria-label="Reporting period"><button data-umx-range="24h" type="button">1 day</button><button data-umx-range="7d" type="button" class="is-active">7 days</button><button data-umx-range="15d" type="button">15 days</button><button data-umx-range="30d" type="button">30 days</button></div>${customDateControls("top")}<div class="umx-updated" id="umx-updated">Connecting to Cartman API…</div></section>
      <div class="umx-error" id="umx-error" hidden role="alert"></div>
      <section class="umx-kpis" aria-label="User metrics summary">
        <article class="umx-kpi"><div class="umx-kpi-top"><span>Active users now</span><span class="umx-kpi-icon">◉</span></div><strong id="umx-active-users">—</strong><small id="umx-active-foot">From recent authenticated sessions</small></article>
        <article class="umx-kpi"><div class="umx-kpi-top"><span>Active sessions</span><span class="umx-kpi-icon">⌁</span></div><strong id="umx-live-sessions">—</strong><small id="umx-sessions-foot">Valid, recently used sessions</small></article>
        <article class="umx-kpi"><div class="umx-kpi-top"><span>Total active time</span><span class="umx-kpi-icon">◷</span></div><strong id="umx-total-active-time">—</strong><small id="umx-active-time-foot">Waiting for measured Cartman usage</small></article>
        <article class="umx-kpi"><div class="umx-kpi-top"><span>Failed sign-ins</span><span class="umx-kpi-icon">!</span></div><strong id="umx-failed-signins">—</strong><small id="umx-failed-foot">Shown only when recorded by Cartman</small></article>
      </section>
      <section class="umx-panel umx-trend-panel"><div class="umx-panel-heading"><div><h2>Activity trend</h2><p id="umx-trend-subtitle">Unique users with recorded Cartman audit activity</p></div><span class="umx-source-pill" id="umx-audit-source">Checking audit source…</span></div><div id="umx-trend" class="umx-trend"><div class="umx-loading">Loading activity data…</div></div></section>
      <section class="umx-panel umx-users-panel"><div class="umx-panel-heading"><div><h2>Users</h2><p>Search Cartman accounts and inspect real sessions and audit records.</p></div><span class="umx-count" id="umx-user-count">—</span></div><div class="umx-user-tools"><label class="umx-search"><span>⌕</span><input id="umx-search" type="search" placeholder="Search name, username, email or department…" autocomplete="off"></label><div class="umx-filters" role="group" aria-label="Filter users"><button data-umx-status="all" type="button" class="is-active">All</button><button data-umx-status="Active" type="button">Active</button><button data-umx-status="Idle" type="button">Idle</button><button data-umx-status="Offline" type="button">Offline</button><button data-umx-status="Disabled" type="button">Disabled</button></div></div><div class="umx-table-wrap"><table class="umx-table"><thead><tr><th>User</th><th>Department</th><th>Last activity</th><th>Live sessions</th><th>Devices</th><th>Status</th><th></th></tr></thead><tbody id="umx-user-rows"><tr><td colspan="7" class="umx-empty">Loading Cartman identities…</td></tr></tbody></table></div><div class="umx-mobile-list" id="umx-mobile-users"></div><div class="umx-table-foot"><span id="umx-table-caption">Loading real user records…</span><span>Choose a user to inspect recorded data</span></div></section>
      <section class="umx-panel umx-detail-panel"><div id="umx-detail"><div class="umx-empty-state"><strong>Select a user</strong><span>Real activity and session details will appear here.</span></div></div></section>
      <footer class="umx-footnote"><span>i</span><p>Metrics describe activity within Cartman only. Active use is approximated from visible pages when recent interaction was observed (5-minute idle cutoff); key contents and desktop-wide activity are not collected. Organization-wide analytics are administrator-only.</p></footer>
    </div>`;
  }
  async function api(path) {
    const response = await fetch(path, {method:"GET", credentials:"same-origin", cache:"no-store", headers:{"Accept":"application/json"}});
    let data; try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) { const error = new Error(data.detail || `Cartman API returned HTTP ${response.status}`); error.status = response.status; throw error; }
    return data;
  }
  function dateTimeLocalValue(date) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }
  const customNow = Date.now();
  state.customStart = dateTimeLocalValue(new Date(customNow - 86400000));
  state.customEnd = dateTimeLocalValue(new Date(customNow));
  function customDateControls(location) {
    return `<div class="umx-custom-datetime" data-umx-range-panel="${location}" aria-label="Custom date and time range"><div class="umx-custom-presets" role="group" aria-label="Quick reporting period"><button type="button" data-umx-range="24h" aria-pressed="false">1 day</button><button type="button" data-umx-range="7d" aria-pressed="true">7 days</button><button type="button" data-umx-range="15d" aria-pressed="false">15 days</button><button type="button" data-umx-range="30d" aria-pressed="false">30 days</button></div><label><span>From date &amp; time</span><input type="datetime-local" data-umx-custom-start value="${esc(state.customStart)}"></label><label><span>To date &amp; time</span><input type="datetime-local" data-umx-custom-end value="${esc(state.customEnd)}"></label><div class="umx-custom-datetime-actions"><button type="button" data-umx-custom-apply>Apply range</button><button type="button" data-umx-custom-clear>Reset</button></div><span class="umx-custom-datetime-error" data-umx-custom-error hidden></span></div>`;
  }
  function syncCustomDateControls() {
    const root = document.getElementById("cartman-user-metrics-root"); if(!root)return;
    root.querySelectorAll("[data-umx-custom-start]").forEach(input=>{if(input.value!==state.customStart)input.value=state.customStart;});
    root.querySelectorAll("[data-umx-custom-end]").forEach(input=>{if(input.value!==state.customEnd)input.value=state.customEnd;});
    root.querySelectorAll("[data-umx-custom-apply]").forEach(button=>button.classList.toggle("is-active",Boolean(state.customRangeActive)));
    root.querySelectorAll("[data-umx-range]").forEach(button=>{const active=!state.customRangeActive && button.dataset.umxRange===state.range;button.classList.toggle("is-active",active);button.setAttribute("aria-pressed",String(active));});
  }
  function queryString() {
    const params = new URLSearchParams();
    params.set("range", state.range || "7d");
    const startDate = state.customRangeActive ? new Date(state.customStart) : null;
    const endDate = state.customRangeActive ? new Date(state.customEnd) : null;
    if (startDate && endDate && Number.isFinite(startDate.getTime()) && Number.isFinite(endDate.getTime()) && endDate > startDate) {
      params.set("start", startDate.toISOString());
      params.set("end", endDate.toISOString());
    }
    return params.toString();
  }
  async function loadData(preserveSelection=true) {
    const root = $("#cartman-user-metrics-root"); if (!root) return;
    state.loading = true; state.error = ""; const errorBox = $("#umx-error", root); if (errorBox) errorBox.hidden = true;
    try {
      const [summary, users] = await Promise.all([api(`/api/user-metrics/summary?${queryString()}`), api(`/api/user-metrics/users?${queryString()}&limit=1000`)]);
      state.summary = summary.summary || {}; state.tracking = summary.tracking || users.tracking || {}; state.trend = Array.isArray(summary.trend) ? summary.trend : []; state.users = Array.isArray(users.items) ? users.items : []; state.generatedAt = summary.generated_at || users.generated_at;
      if (!preserveSelection || !state.selected || !state.users.some(user => user.user_key === state.selected)) state.selected = state.users[0]?.user_key || null;
      state.detail = null;
      if (state.selected) { state.detail = await api(`/api/user-metrics/users/${encodeURIComponent(state.selected)}?${queryString()}`); state.workActivity = await api(`/api/user-metrics/users/${encodeURIComponent(state.selected)}/work-timeline?${queryString()}`).catch(() => null); state.chartTimeline = await api(`/api/user-metrics/users/${encodeURIComponent(state.selected)}/chart-timeline?${queryString()}`).catch(() => null); }
      state.loading = false; renderAll();
    } catch (error) {
      state.loading = false; state.error = error.message || "Could not load User Metrics.";
      renderError(state.error, error.status); renderSummary(); renderUsers(); renderTrend(); renderDetail();
    }
  }
  function renderError(message, status) {
    const box = $("#umx-error"); if (!box) return;
    box.hidden = false;
    const reason = status === 401 ? "Your Cartman session has expired. Sign in and retry." : status === 403 ? "Administrator access is required to view User Metrics." : message;
    box.innerHTML = `<div><strong>Unable to load live User Metrics</strong><span>${esc(reason)}</span></div><button type="button" data-umx-refresh>Retry</button>`;
  }
  function statusBadge(status) { return `<span class="umx-status ${statusClass(status)}"><i></i>${esc(statusLabel(status))}</span>`; }
  function renderSummary() {
    const s = state.summary || {}; const tracking = state.tracking || {};
    const set = (id, value) => { const node = $("#"+id); if(node) node.textContent = value; };
    set("umx-active-users", num(s.active_users_now)); set("umx-live-sessions", num(s.live_sessions));
    set("umx-total-active-time", tracking.active_time ? (Number(tracking.usage_samples || 0) > 0 ? fmtDuration(s.total_active_seconds) : "—") : "Not tracked");
    set("umx-failed-signins", tracking.failed_sign_ins ? num(s.failed_sign_ins) : "—");
    set("umx-active-foot", tracking.sessions ? "Authenticated sessions used in the last 5 minutes" : "Authentication session data is unavailable");
    set("umx-sessions-foot", tracking.sessions ? "Not revoked and recently used" : "Authentication session data is unavailable");
    set("umx-active-time-foot", tracking.active_time ? (Number(tracking.usage_samples || 0) > 0 ? `${num(s.users_with_usage)} user(s) with observed activity` : "No active-use samples yet; tracker starts on visible Cartman pages") : "Active-use table is unavailable");
    set("umx-failed-foot", tracking.failed_sign_ins ? "Recorded failed authentication events" : "Not recorded by an available source");
    set("umx-updated", state.generatedAt ? `Updated ${fmtDate(state.generatedAt)}` : "Live data not loaded");
    document.title = "Cartman | User Metrics";
    rootNavRename();
  }
  function rootNavRename() {
    const nav = document.querySelector("#sidebar, .sidebar, nav[aria-label], [data-sidebar], .app-sidebar");
    if (!nav) return;
    nav.querySelectorAll('a[href*="metrics-performance"], [data-page*="Metrics"], [data-module="metrics-performance"]').forEach(link => {
      [...link.querySelectorAll("span,.nav-label,.sidebar-label,.menu-label,.item-label")].forEach(span => { if (/^Metrics\s*&\s*Performance$/i.test(span.textContent.trim())) span.textContent = "User Metrics"; });
      if (/^Metrics\s*&\s*Performance$/i.test(link.textContent.trim())) { const walker=document.createTreeWalker(link,NodeFilter.SHOW_TEXT); let n; while((n=walker.nextNode())) if(/Metrics\s*&\s*Performance/.test(n.nodeValue)) n.nodeValue=n.nodeValue.replace(/Metrics\s*&\s*Performance/g,"User Metrics"); }
      if (link.getAttribute("aria-label") === "Metrics & Performance") link.setAttribute("aria-label", "User Metrics");
      if (link.getAttribute("title") === "Metrics & Performance") link.setAttribute("title", "User Metrics");
    });
  }
  function renderTrend() {
    const target = $("#umx-trend"); if (!target) return;
    const tracking = state.tracking || {}; const data = state.trend || [];
    const source = tracking.trend_source || "none";
    const pill = $("#umx-audit-source"); if(pill) pill.textContent = source === "usage" ? "Measured Cartman usage" : source === "audit" ? "Audit records connected" : "No history available";
    if (!tracking.trend || !data.length) { target.innerHTML = `<div class="umx-empty-state"><span class="umx-empty-icon">⌁</span><strong>No historical activity data available</strong><span>${esc(tracking.active_time ? "Usage history appears after people use visible Cartman pages." : "No compatible usage or audit history is available. Live session status is still shown above.")}</span></div>`; return; }
    const width=940, height=210, left=34, right=16, top=16, bottom=33; const values=data.map(d=>Number(d.active_users||0)); const max=Math.max(1,...values); const x=i=>left+(data.length<=1?0:i*(width-left-right)/(data.length-1)); const y=v=>top+(max-v)*((height-top-bottom)/max);
    const points=values.map((v,i)=>`${x(i)},${y(v)}`).join(" "); const area=`${left},${height-bottom} ${points} ${x(data.length-1)},${height-bottom}`;
    const labels=data.map((d,i)=>((i===0)||(i===data.length-1)||(data.length<=8)||(i%Math.ceil(data.length/6)===0))?`<text x="${x(i)}" y="${height-9}" text-anchor="${i===0?"start":i===data.length-1?"end":"middle"}" class="umx-axis-label">${esc(d.label)}</text>`:"").join("");
    const grids=[0,Math.round(max/2),max].filter((v,i,a)=>a.indexOf(v)===i).map(v=>`<line x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}" class="umx-gridline"/><text x="${left-9}" y="${y(v)+4}" text-anchor="end" class="umx-axis-label">${v}</text>`).join("");
    target.innerHTML=`<div class="umx-chart-summary"><span><i></i> ${source === "usage" ? "Users with tracked Cartman activity" : "Unique users with recorded audit activity"}</span><span>${source === "usage" ? `${num((state.tracking||{}).usage_samples)} measured minute(s)` : `${num(state.summary?.audit_events_in_period)} audit events`}</span></div><svg class="umx-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${source === "usage" ? "Cartman active users from measured activity intervals" : "Active users based on recorded audit events"}">${grids}<polygon points="${area}" class="umx-area"/><polyline points="${points}" class="umx-line"/>${values.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="3.2" class="umx-point"><title>${esc(data[i].label)}: ${v} user(s), ${Number(data[i].events||0)} event(s)</title></circle>`).join("")}${labels}</svg>`;
  }
  function filteredUsers() {
    const query=state.query.trim().toLowerCase();
    return state.users.filter(user => (!query || [user.name,user.username,user.email,user.department].some(v=>String(v||"").toLowerCase().includes(query))) && (state.status==="all" || user.status===state.status));
  }
  function userRow(user, mobile=false) {
    const selected = user.user_key===state.selected; const detail = `${user.department || "No department"} · ${relativeTime(user.last_activity_at)}`;
    if (mobile) return `<button type="button" class="umx-mobile-row ${selected?"is-selected":""}" data-umx-user="${esc(user.user_key)}"><span class="umx-avatar">${esc(user.initials)}</span><span class="umx-user-primary"><strong>${esc(user.name)}</strong><small>${esc(user.username)} · ${esc(detail)}</small></span>${statusBadge(user.status)}<span class="umx-chevron">›</span></button>`;
    return `<tr data-umx-user="${esc(user.user_key)}" tabindex="0" role="button" aria-label="View ${esc(user.name)}" class="${selected?"is-selected":""}"><td><div class="umx-user-cell"><span class="umx-avatar">${esc(user.initials)}</span><span class="umx-user-primary"><strong>${esc(user.name)}</strong><small>${esc(user.username)}${user.email?` · ${esc(user.email)}`:""}</small></span></div></td><td>${esc(user.department || "—")}</td><td>${esc(relativeTime(user.last_activity_at))}</td><td class="umx-number">${num(user.live_sessions)}</td><td class="umx-number">${user.assigned_devices===null || user.assigned_devices===undefined?"—":num(user.assigned_devices)}</td><td>${statusBadge(user.status)}</td><td><span class="umx-chevron">›</span></td></tr>`;
  }
  function renderUsers() {
    const rows=$("#umx-user-rows"), mobile=$("#umx-mobile-users"); if(!rows||!mobile)return;
    const users=filteredUsers();
    rows.innerHTML=users.length?users.map(user=>userRow(user)).join(""):`<tr><td colspan="7" class="umx-empty">${state.error?"Live users could not be loaded.":"No users match these filters."}</td></tr>`;
    mobile.innerHTML=users.length?users.map(user=>userRow(user,true)).join(""):`<div class="umx-empty">No users match these filters.</div>`;
    const count=$("#umx-user-count"); if(count)count.textContent=`${users.length} / ${state.users.length}`;
    const caption=$("#umx-table-caption"); if(caption)caption.textContent=state.tracking.iam?`Showing ${users.length} Cartman identity record(s)`:"IAM identity source unavailable";
    $("#cartman-user-metrics-root")?.querySelectorAll("[data-umx-status]").forEach(button=>button.classList.toggle("is-active",button.dataset.umxStatus===state.status));
  }
  function renderDetail() {
    const target = $("#umx-detail"); if(!target)return;
    const detail = state.detail; const user = detail?.user;
    if(!user){ target.innerHTML=`<div class="umx-empty-state"><span class="umx-empty-icon">◎</span><strong>${state.users.length?"Select a user to inspect details":"No user selected"}</strong><span>Activity, ticket history and task completions appear here when recorded data exists.</span></div>`; return; }
    const activity = Array.isArray(detail.activity)?detail.activity:[];
    const sessions = Array.isArray(detail.sessions)?detail.sessions:[];
    const work = state.workActivity || {};
    const tickets = Array.isArray(work.tickets)?work.tickets:[];
    const tasks = Array.isArray(work.tasks)?work.tasks:[];
    const chartTimeline = state.chartTimeline || {};
    const tab = state.detailTab || "activity";
    const expanded = target.dataset.umxExpandedTab === tab;
    const limit = expanded ? 100 : 8;
    const showDate = value => value ? fmtDate(value) : "Not recorded";
    const epoch = value => { const t = value ? new Date(value).getTime() : NaN; return Number.isFinite(t) ? t : null; };
    const timeRange = state.range || "7d";
    const customFrom = state.customRangeActive ? new Date(state.customStart).getTime() : NaN;
    const customTo = state.customRangeActive ? new Date(state.customEnd).getTime() : NaN;
    const isCustomRange = Boolean(state.customRangeActive && Number.isFinite(customFrom) && Number.isFinite(customTo) && customTo > customFrom);
    const timeRangeHours = /^(\d{1,3})h$/.test(timeRange) ? Number(timeRange.slice(0,-1)) : timeRange === "24h" ? 24 : timeRange === "15d" ? 360 : timeRange === "30d" ? 720 : 168;
    const end = isCustomRange ? customTo : Date.now();
    const start = isCustomRange ? customFrom : end - timeRangeHours * 3600000;
    const spanMs = Math.max(1, end - start);
    const count = isCustomRange ? Math.max(1, Math.min(48, Math.ceil(spanMs / (spanMs <= 48*3600000 ? 3600000 : 86400000)))) : timeRange === "24h" ? 24 : timeRange === "15d" ? 15 : timeRange === "30d" ? 30 : /h$/.test(timeRange) ? Math.max(1, Math.min(timeRangeHours,48)) : 7;
    const bucketMs = spanMs / count;
    const bins = Array.from({length:count},(_,i)=>({start:start+i*bucketMs,end:start+(i+1)*bucketMs,value:0}));
    let chartTitle = "Recorded activity";
    let chartUnit = "events";
    let chartSource = "audit";
    let sourceAvailable = Boolean(state.tracking.audit || activity.length);
    let chartEvents = [];
    let chartValues = [];
    let chartColorClass = "activity";
    if(tab === "activity") {
      chartTitle = "Cartman active time";
      chartUnit = "minutes";
      chartSource = "usage";
      chartColorClass = "activity";
      const usageRows = Array.isArray(chartTimeline.usage)?chartTimeline.usage:[];
      if(chartTimeline.usage_available && usageRows.length) {
        sourceAvailable = true;
        chartValues = usageRows.map(row=>({at:epoch(row.bucket_start),value:Math.max(0,Number(row.active_seconds)||0)/60})).filter(item=>item.at!==null);
      } else {
        chartTitle = "Recorded Cartman activity";
        chartUnit = "events";
        chartSource = "audit";
        sourceAvailable = Boolean(state.tracking.audit || activity.length);
        chartEvents = activity.map(row=>({at:epoch(row.occurred_at),title:row.action||"Activity"})).filter(item=>item.at!==null);
      }
    } else if(tab === "tickets") {
      chartTitle = "Ticket events"; chartUnit = "events"; chartSource = "tickets"; chartColorClass = "tickets";
      sourceAvailable = Boolean(work.ticket_tracking?.available || tickets.length);
      tickets.forEach(ticket=>{
        if(ticket.event_action && ticket.created_at) chartEvents.push({at:epoch(ticket.created_at),title:ticket.event_action});
        else [["Created",ticket.created_at],["Updated",ticket.updated_at],["Resolved",ticket.resolved_at],["Closed",ticket.closed_at]].forEach(([label,value])=>{if(value)chartEvents.push({at:epoch(value),title:label});});
      });
      chartEvents=chartEvents.filter(item=>item.at!==null);
    } else if(tab === "tasks") {
      chartTitle = "Task completions"; chartUnit = "completed tasks"; chartSource = "tasks"; chartColorClass = "tasks";
      sourceAvailable = Boolean(work.task_tracking?.available || tasks.length);
      chartEvents=tasks.filter(task=>task.completed_at && task.completed_at_in_range !== false).map(task=>({at:epoch(task.completed_at),title:task.title||task.key||"Task completed"})).filter(item=>item.at!==null);
    } else {
      chartTitle = "Session activity"; chartUnit = "session records"; chartSource = "sessions"; chartColorClass = "sessions";
      sourceAvailable = Boolean(sessions.length || state.tracking.sessions);
      chartEvents=sessions.map(session=>({at:epoch(session.last_seen_at),title:"Session last seen"})).filter(item=>item.at!==null);
    }
    const cutoff = start;
    if(chartSource !== "usage") chartValues = chartEvents.map(item=>({at:item.at,value:1}));
    chartValues.forEach(item=>{ if(item.at < cutoff || item.at > end) return; const index=Math.min(count-1,Math.max(0,Math.floor((item.at-start)/bucketMs))); if(bins[index])bins[index].value += item.value; });
    const total = bins.reduce((sum,bin)=>sum+bin.value,0);
    const available = sourceAvailable;
    const hasSourceData = chartValues.some(item=>item.at>=cutoff && item.at<=end);
    function renderChart() {
      if(!available) return `<div class="umx-selected-chart-empty"><strong>Metric source unavailable</strong><span>This Cartman record source is not available, so no synthetic data is shown.</span></div>`;
      if(!hasSourceData) return `<div class="umx-selected-chart-empty"><strong>No measurements in this period</strong><span>${chartSource==="usage"?"Active-time collection starts after tracking is installed and the user interacts with Cartman.":"No timestamped records were found in the selected period."}</span></div>`;
      const width=760,height=204,left=34,right=12,top=16,bottom=29,plotW=width-left-right,plotH=height-top-bottom;
      const max=Math.max(1,...bins.map(bin=>bin.value));
      const power=Math.pow(10,Math.max(0,Math.floor(Math.log10(max)-1))); const roundedMax=max<=4?Math.ceil(max):Math.ceil(max/power)*power;
      const x=i=>left+(count===1?0:i/(count-1))*plotW;
      const y=v=>top+plotH-(v/roundedMax)*plotH;
      const grid=[0,0.333333,0.666667,1].map(f=>{const v=roundedMax*f, yy=y(v);return `<line x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}" class="umx-user-chart-grid"/><text x="${left-8}" y="${yy+3}" text-anchor="end" class="umx-user-chart-axis">${Math.round(v)}</text>`;}).join("");
      const points=bins.map((bin,i)=>`${x(i).toFixed(1)},${y(bin.value).toFixed(1)}`).join(" ");
      const area=`${left},${top+plotH} ${points} ${width-right},${top+plotH}`;
      const stride=Math.max(1,Math.ceil(count/7));
      const labels=bins.map((bin,i)=>{if(i%stride!==0 && i!==count-1)return ""; const date=new Date(bin.start); const label=(isCustomRange && spanMs<=48*3600000) || (!isCustomRange && timeRange==="24h")?date.toLocaleTimeString(undefined,{month:spanMs>86400000?"short":undefined,day:spanMs>86400000?"numeric":undefined,hour:"2-digit",minute:"2-digit"}):date.toLocaleDateString(undefined,{month:"short",day:"numeric"});return `<text x="${x(i)}" y="${height-7}" text-anchor="middle" class="umx-user-chart-axis">${esc(label)}</text>`;}).join("");
      const dots=bins.map((bin,i)=>`<circle cx="${x(i)}" cy="${y(bin.value)}" r="${bin.value===0?1.8:3}" class="umx-user-chart-point"><title>${esc(new Date(bin.start).toLocaleString())}: ${Number(bin.value.toFixed(2))} ${esc(chartUnit)}</title></circle>`).join("");
      return `<div class="umx-selected-chart-summary"><span><i class="umx-selected-chart-key"></i>${esc(chartTitle)}</span><strong>${esc(total.toFixed(chartUnit==="minutes"?1:0))} ${esc(chartUnit)}</strong></div><svg class="umx-user-chart-svg ${chartColorClass}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(chartTitle)} over ${esc(timeRange)}">${grid}<polygon points="${area}" class="umx-user-chart-area"/><polyline points="${points}" class="umx-user-chart-line"/>${dots}${labels}</svg>`;
    }
    function limited(items) { return items.slice(0,limit); }
    function moreButton(total) { return total>8 ? `<div class="umx-compact-table-foot"><span>Showing ${Math.min(limit,total)} of ${total} records</span><button type="button" data-umx-expand="${tab}">${expanded?"Show fewer":"Show all"}</button></div>` : `<div class="umx-compact-table-foot"><span>${total} record(s)</span></div>`; }
    function renderTable(headers, rows, emptyTitle, emptyText, totalRows) {
      if(!rows.length) return `<div class="umx-empty-state compact"><strong>${esc(emptyTitle)}</strong><span>${esc(emptyText)}</span></div>`;
      return `<div class="umx-compact-table-wrap"><table class="umx-compact-table"><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>${moreButton(totalRows)}`;
    }
    let content = "";
    if(tab === "sessions") {
      const rows=sessions.slice().sort((a,b)=>(epoch(b.last_seen_at)||0)-(epoch(a.last_seen_at)||0));
      content=renderTable(["Session","Last seen","Expires","State"],limited(rows).map(session=>`<tr><td class="umx-session-label">${esc(session.label||"Session")}</td><td>${esc(showDate(session.last_seen_at))}</td><td>${esc(showDate(session.expires_at))}</td><td><span class="umx-session-state ${session.state==="Active"?"is-active":""}">${esc(session.state||"Unknown")}</span></td></tr>`),"No session records","No readable auth_sessions entries were found for this account.",rows.length);
    } else if(tab === "tickets") {
      const rows=[];
      tickets.forEach(ticket=>{
        if(ticket.event_action && ticket.created_at) rows.push({key:ticket.key||"Ticket",title:ticket.title||ticket.event_action,action:ticket.event_action,at:ticket.created_at,status:ticket.status||"Recorded"});
        else [["Created",ticket.created_at],["Updated",ticket.updated_at],["Resolved",ticket.resolved_at],["Closed",ticket.closed_at]].forEach(([action,at])=>{if(at)rows.push({key:ticket.key||"Ticket",title:ticket.title||"Ticket",action,at,status:ticket.status||"Recorded"});});
      });
      const uniq=new Map(); rows.forEach(row=>uniq.set([row.key,row.action,row.at].join("|"),row));
      const all=[...uniq.values()].filter(row=>{const stamp=epoch(row.at);return stamp!==null && stamp>=start && stamp<=end;}).sort((a,b)=>(epoch(b.at)||0)-(epoch(a.at)||0));
      content=renderTable(["Ticket","Event","Status","Time"],limited(all).map(row=>`<tr><td><strong>${esc(row.key)}</strong><small class="umx-compact-subtitle">${esc(row.title)}</small></td><td>${esc(row.action)}</td><td>${esc(row.status)}</td><td>${esc(showDate(row.at))}</td></tr>`),work.ticket_tracking?.available?"No ticket events in this period":"Ticket source unavailable",work.ticket_tracking?.available?"No recorded ticket timestamps are linked to this user for the selected range.":"No compatible ticket or ticket-audit source was discovered.",all.length);
    } else if(tab === "tasks") {
      const rows=tasks.filter(task=>task.completed_at && task.completed_at_in_range !== false).sort((a,b)=>(epoch(b.completed_at)||0)-(epoch(a.completed_at)||0));
      content=renderTable(["Task","Status","Completed at","Attribution"],limited(rows).map(task=>`<tr><td><strong>${esc(task.key||"Task")}</strong><small class="umx-compact-subtitle">${esc(task.title||"Untitled task")}</small></td><td>${esc(task.status||"Unknown")}</td><td>${esc(showDate(task.completed_at))}</td><td>${task.completed_by_user?"Completed by user":task.assigned_to_user?"Assigned to user":"Created by user"}</td></tr>`),work.task_tracking?.available?"No recorded task completions":"Task source unavailable",work.task_tracking?.available?"Task history exists, but no explicit completed_at timestamp was recorded in this period.":"The work_items table was not found in the current database.",rows.length);
    } else {
      const rows=activity.slice().sort((a,b)=>(epoch(b.occurred_at)||0)-(epoch(a.occurred_at)||0));
      content=renderTable(["Activity","Details","Time"],limited(rows).map(event=>`<tr><td><strong>${esc(event.action||"Activity")}</strong></td><td>${esc(event.details||event.source||"Recorded Cartman audit event")}</td><td>${esc(showDate(event.occurred_at))}</td></tr>`),state.tracking.audit?"No recorded activity":"Audit source unavailable",state.tracking.audit?"No matching audit events were recorded for this user in the selected period.":"No compatible Cartman audit history source is available.",rows.length);
    }
    const ticketCount=work.ticket_tracking?.available?tickets.length:null;
    const completedCount=work.task_tracking?.available?tasks.filter(task=>Boolean(task.completed_at && task.completed_at_in_range !== false)).length:null;
    const chartMarkup=`<section class="umx-selected-chart" data-metric="${esc(tab)}"><div class="umx-selected-chart-heading"><div><h3>${esc(chartTitle)}</h3><p>${isCustomRange?"Custom date/time range":timeRange==="24h"?"Hourly measurements":timeRange==="15d"?"Daily measurements · last 15 days":timeRange==="30d"?"Daily measurements · last 30 days":"Daily measurements · last 7 days"}</p></div><span class="umx-chart-range">${esc(isCustomRange?"CUSTOM":timeRange==="24h"?"24H":timeRange.toUpperCase())}</span></div>${customDateControls("detail")}${renderChart()}</section>`;
    target.innerHTML = `<div class="umx-detail-header"><span class="umx-avatar umx-avatar-large">${esc(user.initials)}</span><div class="umx-detail-identity"><h2>${esc(user.name)}</h2><p>${esc(user.email||user.username)}</p><div class="umx-detail-meta"><span>@${esc(user.username)}</span><span>·</span><span>${esc(user.department||"No department")}</span><span>·</span><span>${user.assigned_devices===null?"Device assignment unavailable":`${num(user.assigned_devices)} assigned device(s)`}</span></div></div>${statusBadge(user.status)}</div><div class="umx-detail-kpis"><div><span>Measured active time</span><strong>${state.tracking.active_time?fmtDuration(user.active_seconds):"Not measured"}</strong></div><div><span>Valid sessions</span><strong>${num(user.valid_sessions)}</strong></div><div><span>Ticket records</span><strong>${ticketCount===null?"Unavailable":num(ticketCount)}</strong></div><div><span>Tasks completed</span><strong>${completedCount===null?"Unavailable":num(completedCount)}</strong></div></div><div class="umx-detail-tabs"><button type="button" data-umx-tab="activity" class="${tab==="activity"?"is-active":""}">Activity timeline</button><button type="button" data-umx-tab="tickets" class="${tab==="tickets"?"is-active":""}">Ticket timeline</button><button type="button" data-umx-tab="tasks" class="${tab==="tasks"?"is-active":""}">Task completions</button><button type="button" data-umx-tab="sessions" class="${tab==="sessions"?"is-active":""}">Sessions</button></div>${chartMarkup}<div class="umx-detail-content">${content}</div><div class="umx-detail-note">${esc(work.notes?.task||state.tracking.duration_note||"Only recorded timestamps are shown. Missing timestamps are not inferred.")}</div>`;
  }
  const _umxOriginalRenderDetail = renderDetail;
  renderDetail = function() { _umxOriginalRenderDetail(); syncCustomDateControls(); };
  function renderAll() { renderSummary(); renderTrend(); renderUsers(); renderDetail(); syncCustomDateControls(); }
  function exportCSV() {
    const users=filteredUsers(); const fields=["name","username","email","department","status","last_activity_at","active_seconds","live_sessions","valid_sessions","assigned_devices","audit_events_in_period"];
    const lines=[fields.join(","),...users.map(user=>fields.map(field=>{const value=user[field]??"";return `"${String(value).replace(/"/g,'""')}"`;}).join(","))];
    const blob=new Blob(["\ufeff"+lines.join("\r\n")],{type:"text/csv;charset=utf-8;"}); const url=URL.createObjectURL(blob); const a=document.createElement("a");a.href=url;a.download=`cartman-user-metrics-${state.range}.csv`;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  }
  async function selectUser(key) { state.selected=key; const detailRoot=$("#umx-detail");if(detailRoot)detailRoot.dataset.umxExpandedTab=""; state.detail=null; state.workActivity=null; renderUsers(); renderDetail(); try { state.detail=await api(`/api/user-metrics/users/${encodeURIComponent(key)}?${queryString()}`); state.workActivity=await api(`/api/user-metrics/users/${encodeURIComponent(key)}/work-timeline?${queryString()}`).catch(()=>null); state.chartTimeline=await api(`/api/user-metrics/users/${encodeURIComponent(key)}/chart-timeline?${queryString()}`).catch(() => null); renderDetail(); } catch(error) { state.error=error.message; renderError(error.message,error.status); } }
  function wire(root) {
    root.addEventListener("input", event=>{
      if(event.target.id==="umx-search"){state.query=event.target.value;renderUsers();return;}
      if(event.target.matches("[data-umx-custom-start]")){state.customStart=event.target.value;state.customRangeActive=false;root.querySelectorAll("[data-umx-custom-start]").forEach(input=>{if(input!==event.target)input.value=state.customStart;});syncCustomDateControls();return;}
      if(event.target.matches("[data-umx-custom-end]")){state.customEnd=event.target.value;state.customRangeActive=false;root.querySelectorAll("[data-umx-custom-end]").forEach(input=>{if(input!==event.target)input.value=state.customEnd;});syncCustomDateControls();return;}
    });
    root.addEventListener("click", event=>{
      const customApply=event.target.closest("[data-umx-custom-apply]");if(customApply){const startValue=state.customStart;const endValue=state.customEnd;const startMs=new Date(startValue).getTime();const endMs=new Date(endValue).getTime();const error=root.querySelectorAll("[data-umx-custom-error]");if(!startValue||!endValue||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs){error.forEach(node=>{node.hidden=false;node.textContent="End date/time must be later than start date/time.";});return;}error.forEach(node=>{node.hidden=true;node.textContent="";});state.customRangeActive=true;state.error="";syncCustomDateControls();loadData(true);return;}
      const clearCustom=event.target.closest("[data-umx-custom-clear]");if(clearCustom){state.customRangeActive=false;state.range="7d";state.error="";syncCustomDateControls();loadData(true);return;}
      const range=event.target.closest("[data-umx-range]"); if(range){state.range=range.dataset.umxRange;state.customRangeActive=false;root.querySelectorAll("[data-umx-custom-error]").forEach(node=>{node.hidden=true;node.textContent="";});syncCustomDateControls();loadData(true);return;}
      const status=event.target.closest("[data-umx-status]");if(status){state.status=status.dataset.umxStatus;renderUsers();return;}
      const user=event.target.closest("[data-umx-user]");if(user){state.detailTab="activity";selectUser(user.dataset.umxUser);return;}
      const expand=event.target.closest("[data-umx-expand]");if(expand){const detailRoot=$("#umx-detail");if(detailRoot)detailRoot.dataset.umxExpandedTab=detailRoot.dataset.umxExpandedTab===expand.dataset.umxExpand?"":expand.dataset.umxExpand;renderDetail();return;}
      const tab=event.target.closest("[data-umx-tab]");if(tab){state.detailTab=tab.dataset.umxTab;const detailRoot=$("#umx-detail");if(detailRoot)detailRoot.dataset.umxExpandedTab="";renderDetail();return;}
      if(event.target.closest("[data-umx-refresh]")){loadData(true);return;}
      if(event.target.closest("[data-umx-export]")){exportCSV();return;}
    });
    root.addEventListener("keydown", event=>{if((event.key==="Enter"||event.key===" ")&&event.target.matches("tr[data-umx-user]")){event.preventDefault();state.detailTab="activity";selectUser(event.target.dataset.umxUser);}});
  }
  function mount() {
    if(document.getElementById("cartman-user-metrics-root")) return;
    const host=findHost(); if(!host){console.error("Cartman User Metrics: could not locate this page's content host.");return;}
    host.innerHTML=markup(); const root=$("#cartman-user-metrics-root"); wire(root); rootNavRename(); loadData(false);
    document.documentElement.dataset.cartmanPage="user-metrics";
    window.setInterval(()=>{if(document.visibilityState==="visible")loadData(true);},60000);
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount,{once:true});else mount();
})();

/* CARTMAN_USER_METRICS_CUSTOM_RANGE_PRESETS_V1 */
