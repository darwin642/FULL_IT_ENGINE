/* CARTMAN_MONITORING_OVERVIEW_COMMAND_CENTER_V2
 * Dedicated, API-backed command center for /pages/monitoring-overview/.
 * No sample devices, fabricated telemetry, or synthetic SLA values.
 */
(() => {
  "use strict";
  const MARKER = "CARTMAN_MONITORING_OVERVIEW_COMMAND_CENTER_V2";
  if (window.__cartmanMonitoringOverviewCommandCenter === MARKER) return;
  window.__cartmanMonitoringOverviewCommandCenter = MARKER;

  const API = { overview: "/api/overview", devices: "/api/devices" };
  const POLL_MS = 30000;
  const state = {
    host: null, module: null, overview: null, devices: [], search: "",
    filter: "all", expanded: false, busy: false, loaded: false,
    error: "", lastUpdated: null, timer: null
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = value => String(value ?? "—").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  const fmtNum = value => Number(value || 0).toLocaleString();
  const isObject = value => !!value && typeof value === "object" && !Array.isArray(value);
  const first = (item, fields, fallback = "") => {
    for (const key of fields) {
      const value = item?.[key];
      if (value !== undefined && value !== null && value !== "") return value;
    }
    return fallback;
  };
  function timeDate(value) {
    if (!value) return null;
    const normalized = String(value).trim().replace(/^(\d{4}-\d{2}-\d{2})\s+/, "$1T");
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  function when(value) {
    const date = timeDate(value);
    return date ? date.toLocaleString() : (value ? String(value) : "Time unavailable");
  }
  function relative(value) {
    const date = timeDate(value);
    if (!date) return "time unavailable";
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
  function deviceName(device) { return String(first(device, ["name", "hostname", "device_name", "display_name"], "Unnamed device")); }
  function deviceOS(device) { return String(first(device, ["os", "operating_system", "platform", "os_name"], "Unknown OS")); }
  function deviceIP(device) { return String(first(device, ["ip", "private_ip", "local_ip", "ip_address", "public_ip"], "—")); }
  function deviceId(device) { return String(first(device, ["id", "device_id"], "")); }
  function rawStatus(device) { return String(first(device, ["status", "connection_status", "state"], "Unknown")); }
  function canonicalStatus(value) {
    const status = String(value || "unknown").toLowerCase();
    if (/offline|critical|down|failed|unreachable|error/.test(status)) return "offline";
    if (/warning|degraded|maintenance|pending/.test(status)) return "warning";
    if (/online|healthy|operational|normal|active|connected|ok/.test(status)) return "online";
    return "unknown";
  }
  function severityKind(value) {
    const s = String(value || "").toLowerCase();
    if (/critical|emergency|fatal|offline|down|failed|error/.test(s)) return "bad";
    if (/warning|warn|degraded|medium|moderate/.test(s)) return "warn";
    if (/info|notice|low/.test(s)) return "info";
    if (/online|healthy|resolved|closed|success|normal|ok/.test(s)) return "good";
    return "neutral";
  }
  function stateCounts(devices) {
    const counts = { online: 0, warning: 0, offline: 0, unknown: 0 };
    devices.forEach(device => counts[canonicalStatus(rawStatus(device))]++);
    return counts;
  }
  function percent(value, total) { return total > 0 ? Math.round(value / total * 100) : 0; }
  function statusPill(value) {
    const canonical = canonicalStatus(value);
    const label = canonical === "unknown" ? (value || "Unknown") : canonical[0].toUpperCase() + canonical.slice(1);
    return `<span class="moc-pill ${canonical}"><i></i>${esc(label)}</span>`;
  }
  function apiList(payload, keys) {
    if (Array.isArray(payload)) return payload;
    if (!isObject(payload)) return [];
    for (const key of keys) if (Array.isArray(payload[key])) return payload[key];
    for (const key of ["data", "result", "response"]) {
      if (isObject(payload[key])) {
        const items = apiList(payload[key], keys);
        if (items.length) return items;
      }
    }
    return [];
  }
  async function getJSON(url) {
    const response = await fetch(url, {
      method: "GET", credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json" }
    });
    const body = await response.text();
    let data = {};
    if (body) { try { data = JSON.parse(body); } catch (_) { data = { detail: body.slice(0, 180) }; } }
    if (!response.ok) {
      const error = new Error(String(data?.detail || data?.message || `${response.status} ${response.statusText}`));
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function alertItems() {
    const items = state.overview?.monitoring?.alerts;
    return Array.isArray(items) ? items : [];
  }
  function openAlertCount() {
    const raw = state.overview?.monitoring?.open_alerts;
    return raw === undefined || raw === null ? alertItems().length : Number(raw) || 0;
  }
  function deviceAttentionItems() {
    return state.devices.filter(device => ["offline", "warning"].includes(canonicalStatus(rawStatus(device))));
  }
  function priorityItems() {
    const devices = deviceAttentionItems().map(device => {
      const status = canonicalStatus(rawStatus(device));
      return {
        kind: "device", rank: status === "offline" ? 0 : 2,
        title: deviceName(device), detail: `${deviceOS(device)} · ${deviceIP(device)}`,
        status: status === "offline" ? "Offline" : "Warning",
        time: first(device, ["last_seen", "updated_at", "created_at"], ""),
        href: "/pages/devices/", action: "Open device inventory"
      };
    });
    const alerts = alertItems().map(alert => {
      const severity = String(first(alert, ["severity", "level"], "Alert"));
      const rank = /critical|emergency|fatal/i.test(severity) ? 1 : /warning|high|error/i.test(severity) ? 3 : 4;
      const target = first(alert, ["device_name", "hostname", "device_id"], "Target not specified");
      return {
        kind: "alert", rank, title: String(first(alert, ["title", "message", "name"], "Monitoring alert")),
        detail: `${target}${first(alert, ["details", "detail", "description"], "") ? " · " + first(alert, ["details", "detail", "description"], "") : ""}`,
        status: severity, time: first(alert, ["created_at", "occurred_at", "timestamp"], ""),
        href: "/pages/alerts/", action: "Open alert management"
      };
    });
    return [...devices, ...alerts].sort((a, b) => a.rank - b.rank || (timeDate(b.time)?.getTime() || 0) - (timeDate(a.time)?.getTime() || 0)).slice(0, 7);
  }
  function filteredDevices() {
    const query = state.search.trim().toLowerCase();
    return state.devices.filter(device => {
      const status = canonicalStatus(rawStatus(device));
      const searchable = [deviceName(device), deviceOS(device), deviceIP(device), rawStatus(device), deviceId(device),
        ...(Array.isArray(device.tags) ? device.tags : [])].join(" ").toLowerCase();
      const matchesFilter = state.filter === "all" || state.filter === status || (state.filter === "attention" && ["offline", "warning"].includes(status));
      return matchesFilter && (!query || searchable.includes(query));
    }).sort((a, b) => {
      const order = { offline: 0, warning: 1, unknown: 2, online: 3 };
      return order[canonicalStatus(rawStatus(a))] - order[canonicalStatus(rawStatus(b))] || deviceName(a).localeCompare(deviceName(b));
    });
  }
  function kpi(label, value, sub, tone, filter, href) {
    const tag = href ? "a" : "button";
    const attrs = href ? `href="${href}"` : `type="button" data-moc-kpi-filter="${filter}"`;
    return `<${tag} class="moc-kpi ${tone}" ${attrs}><span class="moc-kpi-top"><span>${esc(label)}</span><span class="moc-kpi-symbol">${tone === "red" ? "!" : tone === "amber" ? "◷" : tone === "green" ? "✓" : "▦"}</span></span><strong>${esc(value)}</strong><small>${esc(sub)}</small></${tag}>`;
  }
  function renderFleet(counts, total) {
    const rows = [
      ["online", "Online", counts.online], ["warning", "Warning", counts.warning],
      ["offline", "Offline", counts.offline], ["unknown", "Unknown", counts.unknown]
    ];
    const bar = rows.map(([key, _label, n]) => `<i class="${key}" style="width:${percent(n, total)}%" title="${_label}: ${n}"></i>`).join("");
    return `<div class="moc-fleet-summary"><div class="moc-fleet-total"><strong>${fmtNum(total)}</strong><span>registered devices</span></div><div class="moc-stacked-bar" role="img" aria-label="Fleet status distribution">${bar}</div><div class="moc-fleet-legend">${rows.map(([key, label, count]) => `<button type="button" class="moc-legend-item" data-moc-filter="${key}"><i class="${key}"></i><span>${label}</span><strong>${fmtNum(count)}</strong></button>`).join("")}</div><button type="button" class="moc-link-button" data-moc-filter="all">View all device states <span>→</span></button></div>`;
  }
  function renderPriority() {
    const items = priorityItems();
    if (!items.length) {
      const count = openAlertCount() + deviceAttentionItems().length;
      if (!count) return `<div class="moc-quiet-state"><span class="moc-quiet-check">✓</span><div><strong>No active issues returned</strong><p>The current API snapshot contains no warning/offline devices or open-alert records in the returned list.</p></div></div>`;
      return `<div class="moc-quiet-state"><span class="moc-quiet-symbol">!</span><div><strong>${fmtNum(count)} issue record(s) need review</strong><p>The API's total alert count is higher than the alert details returned in this snapshot. Open Alerts to investigate.</p><a href="/pages/alerts/">Open Alerts →</a></div></div>`;
    }
    return `<div class="moc-priority-list">${items.map(item => `<a class="moc-priority-item ${item.kind}" href="${item.href}" title="${esc(item.action)}"><span class="moc-priority-symbol ${severityKind(item.status)}">${item.kind === "alert" ? "!" : item.status === "Offline" ? "×" : "↗"}</span><span class="moc-priority-copy"><span class="moc-priority-title">${esc(item.title)}</span><span class="moc-priority-detail">${esc(item.detail)}</span><span class="moc-priority-meta">${esc(item.kind === "alert" ? "Alert" : "Device")} · ${esc(relative(item.time))}</span></span><span class="moc-priority-state">${statusPill(item.status)}</span><span class="moc-priority-arrow">↗</span></a>`).join("")}</div><div class="moc-panel-foot"><span>Prioritized by status and severity · up to 7 items</span><a href="/pages/alerts/">Manage alerts →</a></div>`;
  }
  function renderActivity() {
    const activities = Array.isArray(state.overview?.activity) ? state.overview.activity.slice(0, 6) : [];
    if (!activities.length) return `<div class="moc-empty">No recent monitoring activity was returned by the API.</div>`;
    return `<div class="moc-activity-list">${activities.map(item => {
      const kind = item.kind === "alert" ? "alert" : "event";
      return `<article class="moc-activity-item"><span class="moc-activity-marker ${kind}">${kind === "alert" ? "!" : "↻"}</span><div class="moc-activity-main"><strong>${esc(first(item, ["title"], kind === "alert" ? "Alert" : "Monitoring event"))}</strong><p>${esc(first(item, ["detail"], ""))}</p></div><time title="${esc(when(item.timestamp))}">${esc(relative(item.timestamp))}</time></article>`;
    }).join("")}</div>`;
  }
  function renderSignals() {
    const monitoring = state.overview?.monitoring || {};
    const items = [
      ["Metric samples", monitoring.metric_samples, "/pages/metrics-performance/"],
      ["Service checks", monitoring.service_checks, "/pages/service-monitoring/"],
    ];
    return `<div class="moc-signals">${items.map(([label, value, href]) => `<a class="moc-signal" href="${href}"><span>${esc(label)}</span><strong>${fmtNum(value)}</strong><small>stored records · view details ↗</small></a>`).join("")}<div class="moc-signal moc-signal-static"><span>Monitoring events</span><strong>${fmtNum(monitoring.events_total)}</strong><small>stored event records</small></div></div>`;
  }
  function renderDeviceRows(devices) {
    const visible = state.expanded || state.search || state.filter !== "all" ? devices : devices.slice(0, 8);
    if (!visible.length) return `<tr><td colspan="5"><div class="moc-empty">No devices match this filter. Try another status or search term.</div></td></tr>`;
    return visible.map(device => {
      const os = deviceOS(device), status = rawStatus(device), lastSeen = first(device, ["last_seen", "last_seen_at", "updated_at", "created_at"], "");
      const initial = os.toLowerCase().includes("windows") ? "⊞" : os.toLowerCase().includes("mac") ? "⌘" : os.toLowerCase().includes("linux") ? "◈" : "▦";
      return `<tr><td><div class="moc-device-cell"><span class="moc-device-avatar">${initial}</span><span class="moc-device-name"><strong>${esc(deviceName(device))}</strong><small>${esc(deviceId(device) || "Device ID unavailable")}</small></span></div></td><td><span class="moc-os-name">${esc(os)}</span></td><td class="moc-ip">${esc(deviceIP(device))}</td><td>${statusPill(status)}</td><td><span class="moc-seen" title="${esc(when(lastSeen))}">${esc(relative(lastSeen))}</span></td></tr>`;
    }).join("");
  }
  function renderDeviceArea() {
    const devices = filteredDevices();
    const visibleCount = state.expanded || state.search || state.filter !== "all" ? devices.length : Math.min(8, devices.length);
    return `<section class="moc-panel moc-devices-panel"><header class="moc-panel-head"><div><div class="moc-section-kicker">DEVICE ESTATE</div><h2>Device health</h2><p>Unhealthy devices are listed first so you can focus on what needs attention.</p></div><a class="moc-outline-link" href="/pages/devices/">Open Devices <span>↗</span></a></header><div class="moc-device-tools"><label class="moc-search"><span>⌕</span><input type="search" data-moc-search placeholder="Search device, OS, IP or ID…" value="${esc(state.search)}" aria-label="Search devices"></label><div class="moc-filter-tabs" role="group" aria-label="Filter device status">${[["all","All"],["attention","Needs attention"],["offline","Offline"],["warning","Warning"],["online","Online"]].map(([key,label]) => `<button type="button" class="${state.filter === key ? "active" : ""}" data-moc-filter="${key}">${label}${key === "all" ? ` <span>${fmtNum(state.devices.length)}</span>` : key === "attention" ? ` <span>${fmtNum(deviceAttentionItems().length)}</span>` : key === "offline" ? ` <span>${fmtNum(stateCounts(state.devices).offline)}</span>` : key === "warning" ? ` <span>${fmtNum(stateCounts(state.devices).warning)}</span>` : ""}</button>`).join("")}</div></div><div class="moc-table-wrap"><table class="moc-table"><thead><tr><th>Device</th><th>Operating system</th><th>IP address</th><th>Status</th><th>Last seen / updated</th></tr></thead><tbody data-moc-rows>${renderDeviceRows(devices)}</tbody></table></div><footer class="moc-device-foot"><span>Showing ${fmtNum(visibleCount)} of ${fmtNum(devices.length)} matching · ${fmtNum(state.devices.length)} total</span>${!state.expanded && !state.search && state.filter === "all" && devices.length > 8 ? `<button type="button" class="moc-link-button" data-moc-expand>Show ${fmtNum(devices.length - 8)} more <span>↓</span></button>` : state.expanded && devices.length > 8 && !state.search && state.filter === "all" ? `<button type="button" class="moc-link-button" data-moc-collapse>Show less <span>↑</span></button>` : `<a href="/pages/devices/">Manage device inventory <span>→</span></a>`}</footer></section>`;
  }
  function render() {
    if (!state.host) return;
    if (!state.loaded && state.error) {
      state.host.innerHTML = `<div class="moc-app"><header class="moc-heading"><div><div class="moc-eyebrow">CARTMAN / MONITORING & OBSERVABILITY</div><h2>Monitoring Overview</h2><p>Infrastructure status and operational priorities.</p></div><button class="moc-button primary" data-moc-refresh ${state.busy ? "disabled" : ""}>${state.busy ? "Retrying…" : "↻ Retry connection"}</button></header><div class="moc-connection error"><span class="moc-connection-dot"></span><div><strong>Live data unavailable</strong><p>${esc(state.error)}</p></div></div><section class="moc-panel moc-empty-panel"><span class="moc-empty-icon">⌁</span><h3>Can't load Monitoring Overview</h3><p>No sample values are displayed. Sign in to Cartman or check API access, then retry.</p></section></div>`;
      bindCommon();
      return;
    }
    const overview = state.overview || {};
    const monitoring = overview.monitoring || {};
    const counts = stateCounts(state.devices);
    const total = Number(overview.devices?.total ?? state.devices.length);
    const warnings = counts.warning;
    const offline = counts.offline;
    const attention = warnings + offline;
    const alertCount = openAlertCount();
    const staleWarning = !!state.error;
    const lastText = state.lastUpdated ? `Updated ${state.lastUpdated.toLocaleTimeString()}` : "Waiting for first update";
    state.host.innerHTML = `<div class="moc-app">
      <header class="moc-heading"><div><div class="moc-eyebrow">CARTMAN / MONITORING & OBSERVABILITY</div><h2>Monitoring Overview</h2><p>Know what needs attention first, then jump straight to the relevant tool.</p></div><div class="moc-header-actions"><div class="moc-data-state ${staleWarning ? "warn" : "live"}"><i></i><span>${staleWarning ? "STALE DATA" : "LIVE DATA"}</span><small>${esc(lastText)}</small></div><button class="moc-button primary" data-moc-refresh ${state.busy ? "disabled" : ""}>${state.busy ? "Refreshing…" : "↻ Refresh"}</button></div></header>
      ${staleWarning ? `<div class="moc-connection warn"><span class="moc-connection-dot"></span><div><strong>Refresh failed — showing last successful snapshot</strong><p>${esc(state.error)}</p></div><button class="moc-link-button" data-moc-refresh>Retry →</button></div>` : ""}
      <section class="moc-kpis" aria-label="Current infrastructure state">
        ${kpi("Registered devices", fmtNum(total), "Records in Cartman Devices", "blue", "all")}
        ${kpi("Offline devices", fmtNum(offline), attention ? `${fmtNum(attention)} device(s) need attention` : "No offline devices in current response", offline ? "red" : "green", "offline")}
        ${kpi("Warning state", fmtNum(warnings), warnings ? "Review device health" : "No warning devices in current response", warnings ? "amber" : "green", "warning")}
        ${kpi("Open alerts", fmtNum(alertCount), "Unresolved alerts reported by API", alertCount ? "red" : "green", "all", "/pages/alerts/")}
      </section>
      <section class="moc-primary-grid"><section class="moc-panel moc-priority-panel"><header class="moc-panel-head"><div><div class="moc-section-kicker">ACTION FIRST</div><h2>Needs attention</h2><p>Offline and warning devices, plus recent unresolved alerts.</p></div><span class="moc-count-chip ${attention || alertCount ? "attention" : "clear"}">${fmtNum(attention + alertCount)} reported</span></header>${renderPriority()}</section><section class="moc-panel moc-fleet-panel"><header class="moc-panel-head"><div><div class="moc-section-kicker">FLEET HEALTH</div><h2>Device status</h2><p>Distribution from the current device records.</p></div></header>${renderFleet(counts, state.devices.length)}</section></section>
      ${renderDeviceArea()}
      <section class="moc-secondary-grid"><section class="moc-panel"><header class="moc-panel-head"><div><div class="moc-section-kicker">RECENT CHANGES</div><h2>Monitoring activity</h2><p>Latest stored events and alerts returned by the API.</p></div><a class="moc-outline-link" href="/pages/alerts/">View alerts <span>↗</span></a></header>${renderActivity()}<div class="moc-panel-foot"><span>Source: persisted Monitoring records</span><a href="/pages/alerts/">Open alert management →</a></div></section><section class="moc-panel"><header class="moc-panel-head"><div><div class="moc-section-kicker">DATA COVERAGE</div><h2>Monitoring signals</h2><p>Counts of persisted records — not fabricated performance readings.</p></div></header>${renderSignals()}<div class="moc-panel-foot"><span>Values reflect stored records, not guaranteed active collectors.</span></div></section></section>
      <footer class="moc-foot"><span>Cartman Monitoring Overview</span><span>Authenticated Cartman APIs · automatic refresh every 30 seconds</span></footer>
    </div>`;
    bindCommon();
    bindDeviceTools();
  }
  function bindCommon() {
    state.host.querySelectorAll("[data-moc-refresh]").forEach(button => button.addEventListener("click", () => void refresh()));
    state.host.querySelectorAll("[data-moc-kpi-filter]").forEach(button => button.addEventListener("click", () => {
      state.filter = button.dataset.mocKpiFilter || "all";
      state.expanded = true;
      render();
      state.host.querySelector(".moc-devices-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  }
  function updateDeviceTable() {
    const tbody = state.host?.querySelector("[data-moc-rows]");
    const foot = state.host?.querySelector(".moc-device-foot");
    const devices = filteredDevices();
    if (tbody) tbody.innerHTML = renderDeviceRows(devices);
    if (foot) {
      const visibleCount = state.expanded || state.search || state.filter !== "all" ? devices.length : Math.min(8, devices.length);
      foot.innerHTML = `<span>Showing ${fmtNum(visibleCount)} of ${fmtNum(devices.length)} matching · ${fmtNum(state.devices.length)} total</span>${!state.expanded && !state.search && state.filter === "all" && devices.length > 8 ? `<button type="button" class="moc-link-button" data-moc-expand>Show ${fmtNum(devices.length - 8)} more <span>↓</span></button>` : state.expanded && devices.length > 8 && !state.search && state.filter === "all" ? `<button type="button" class="moc-link-button" data-moc-collapse>Show less <span>↑</span></button>` : `<a href="/pages/devices/">Manage device inventory <span>→</span></a>`}`;
      foot.querySelector("[data-moc-expand]")?.addEventListener("click", () => { state.expanded = true; updateDeviceTable(); });
      foot.querySelector("[data-moc-collapse]")?.addEventListener("click", () => { state.expanded = false; updateDeviceTable(); });
    }
    state.host.querySelectorAll("[data-moc-filter]").forEach(button => button.classList.toggle("active", button.dataset.mocFilter === state.filter));
    state.host.querySelectorAll("[data-moc-filter]").forEach(button => {
      if (button.dataset.mocBound === "1") return;
      button.dataset.mocBound = "1";
      button.addEventListener("click", () => { state.filter = button.dataset.mocFilter || "all"; state.expanded = true; updateDeviceTable(); });
    });
  }
  function bindDeviceTools() {
    const search = state.host.querySelector("[data-moc-search]");
    search?.addEventListener("input", event => { state.search = event.target.value; updateDeviceTable(); });
    state.host.querySelectorAll("[data-moc-filter]").forEach(button => {
      if (button.dataset.mocBound === "1") return;
      button.dataset.mocBound = "1";
      button.addEventListener("click", () => {
        state.filter = button.dataset.mocFilter || "all";
        state.expanded = true;
        updateDeviceTable();
      });
    });
    state.host.querySelector("[data-moc-expand]")?.addEventListener("click", () => { state.expanded = true; updateDeviceTable(); });
  }
  function renderLoading() {
    state.host.innerHTML = `<div class="moc-app"><header class="moc-heading"><div><div class="moc-eyebrow">CARTMAN / MONITORING & OBSERVABILITY</div><h2>Monitoring Overview</h2><p>Loading live infrastructure state and operational priorities.</p></div><span class="moc-data-state loading"><i></i><span>CONNECTING</span></span></header><section class="moc-panel moc-loading-panel"><span class="moc-spinner"></span><div><strong>Connecting to Cartman</strong><p>Retrieving authenticated device and Monitoring API data. No sample data will be shown.</p></div></section></div>`;
  }
  async function refresh() {
    if (state.busy) return;
    state.busy = true;
    if (!state.loaded) renderLoading();
    else {
      state.host?.querySelectorAll("[data-moc-refresh]").forEach(button => { button.disabled = true; button.textContent = "Refreshing…"; });
    }
    try {
      const [overview, devicePayload] = await Promise.all([getJSON(API.overview), getJSON(API.devices)]);
      if (!isObject(overview)) throw new Error("Overview API returned an unexpected response.");
      const devices = apiList(devicePayload, ["items", "devices", "results", "records"]);
      if (!Array.isArray(devices)) throw new Error("Devices API did not return a device list.");
      state.overview = overview;
      state.devices = devices.filter(isObject);
      state.loaded = true;
      state.error = "";
      state.lastUpdated = new Date();
    } catch (error) {
      state.error = error.status === 401 ? "Authentication required. Sign in to Cartman and retry." : error.status === 403 ? "Your Cartman role does not permit access to this data." : `Could not load live API data: ${error.message}`;
    } finally {
      state.busy = false;
      render();
    }
  }
  function mount() {
    if (!location.pathname.replace(/\/+$/, "").toLowerCase().endsWith("/monitoring-overview")) return;
    const host = document.querySelector('[data-monitor-dashboard="monitoring-overview"]');
    if (!host || host.dataset.monitoringOverviewCommandCenter === "1") return;
    host.dataset.monitoringOverviewCommandCenter = "1";
    state.host = host;
    state.module = host.closest(".workspace-module");
    state.module?.querySelector(".workspace-eyebrow")?.remove();
    state.module?.querySelector(".workspace-toolbar")?.remove();
    state.module?.querySelector(".workspace-stats")?.remove();
    state.module?.querySelector(".workspace-table-panel")?.remove();
    state.module?.classList.add("moc-live-mode");
    renderLoading();
    void refresh();
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(() => void refresh(), POLL_MS);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, { once: true });
  else mount();
})();
