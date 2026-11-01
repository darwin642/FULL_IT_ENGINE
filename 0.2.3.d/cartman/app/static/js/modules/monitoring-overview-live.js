/* CARTMAN_MONITORING_OVERVIEW_REAL_API_V1
 * Monitoring Overview: only API-returned values; one selected device at a time.
 */
(() => {
  "use strict";
  const MARKER = "CARTMAN_MONITORING_OVERVIEW_REAL_API_V1";
  if (window.__cartmanMonitoringOverviewLive === MARKER) return;
  window.__cartmanMonitoringOverviewLive = MARKER;

  const API = {
    devices: "/api/devices",
    summary: "/api/monitoring/summary",
    metrics: "/api/monitoring/metrics",
    alerts: "/api/monitoring/alerts",
    services: "/api/monitoring/services"
  };
  // Filled by the installer from the actual FastAPI handler signature.
  const METRIC_FILTER_PARAMS = ["device_id"];
  const DEVICE_FILTER_NAMES = ["device_id", "device_uuid", "machine_id", "device_name", "device", "hostname", "host", "target_id", "target_name", "computer_name", "agent_id", "node_id", "asset_id"];
  const POLL_MS = 10000;
  let selectedDevice = null;
  let devices = [];
  let refreshInProgress = false;
  let metricsRequest = 0;
  let lastSuccessfulRefresh = null;
  let pollingHandle = null;
  let range = "7d";

  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const fmtTime = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
  };
  const dateLabel = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  };
  const isObj = v => !!v && typeof v === "object" && !Array.isArray(v);
  const unwrap = (v) => {
    if (Array.isArray(v)) return v;
    if (!isObj(v)) return [];
    for (const k of ["items", "devices", "results", "records", "data", "metrics", "alerts", "services", "events"])
      if (Array.isArray(v[k])) return v[k];
    if (isObj(v.data)) return unwrap(v.data);
    return [];
  };
  const normalizedKey = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
  const findKey = (obj, aliases) => {
    if (!isObj(obj)) return undefined;
    const keys = Object.keys(obj);
    for (const alias of aliases) {
      const k = keys.find(key => normalizedKey(key) === normalizedKey(alias));
      if (k !== undefined && obj[k] !== null && obj[k] !== "") return obj[k];
    }
    return undefined;
  };
  const findDeep = (obj, aliases, depth = 0) => {
    if (!isObj(obj) || depth > 3) return undefined;
    const direct = findKey(obj, aliases);
    if (direct !== undefined) return direct;
    for (const value of Object.values(obj)) {
      if (isObj(value)) {
        const found = findDeep(value, aliases, depth + 1);
        if (found !== undefined) return found;
      }
    }
    return undefined;
  };
  const asNumber = value => {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
      const m = value.replace(/,/g, ".").match(/-?\d+(?:\.\d+)?/);
      if (m) return Number(m[0]);
    }
    return null;
  };
  const displayNum = (value, suffix = "") => {
    const n = asNumber(value);
    return n === null ? (value === undefined || value === null || value === "" ? "—" : `${esc(value)}${suffix}`) : `${Number.isInteger(n) ? n : n.toFixed(1)}${suffix}`;
  };
  const apiFetch = async (url) => {
    const response = await fetch(url, {method:"GET", credentials:"same-origin", cache:"no-store", headers:{"Accept":"application/json"}});
    const raw = await response.text();
    let body;
    try { body = raw ? JSON.parse(raw) : {}; } catch { body = {message: raw.slice(0, 240)}; }
    if (!response.ok) {
      const detail = findDeep(body, ["detail", "message", "error"]) || `HTTP ${response.status}`;
      throw new Error(String(detail));
    }
    return body;
  };
  const statusOf = d => String(findKey(d, ["status", "state", "connection_status", "health_status"]) ?? "Unknown");
  const nameOf = d => String(findKey(d, ["name", "hostname", "device_name", "display_name", "computer_name", "host"]) ?? "Unnamed device");
  const idOf = d => findKey(d, ["id", "device_id", "uuid", "device_uuid", "key"]);
  const ipOf = d => findKey(d, ["ip", "ip_address", "private_ip", "address", "management_ip"]);
  const osOf = d => findKey(d, ["os", "operating_system", "platform", "os_version"]);
  const typeOf = d => findKey(d, ["type", "device_type", "category", "kind"]);
  const setStatus = (message, kind = "ok") => {
    const el = $("#mo-api-status");
    if (!el) return;
    el.className = `mo-source-status ${kind}`;
    el.innerHTML = `<span class="mo-dot"></span><span>${esc(message)}</span>`;
  };
  const setUpdated = (value) => {
    const el = $("#mo-last-updated");
    if (el) el.textContent = value ? fmtTime(value) : "—";
  };
  const setKpi = (id, value, fallback = "—") => {
    const el = $(`#${id}`);
    if (el) el.textContent = value === undefined || value === null || value === "" ? fallback : String(value);
  };
  const firstNumber = (obj, aliases) => asNumber(findDeep(obj, aliases));
  const metricLabel = m => String(findKey(m, ["label", "name", "metric", "metric_name", "key", "type", "title"]) ?? "Metric");
  const metricValue = m => findKey(m, ["value", "current", "latest_value", "measurement", "reading", "amount", "avg", "average"]);
  const metricUnit = m => String(findKey(m, ["unit", "units", "uom"]) ?? "");
  const metricTime = m => findKey(m, ["timestamp", "recorded_at", "collected_at", "created_at", "time", "observed_at", "last_seen"]);
  const metricSource = m => findKey(m, ["source", "collector", "agent", "origin"]);
  const statusForMetric = m => {
    const explicit = findKey(m, ["status", "state", "health", "severity"]);
    // Never invent a health threshold/status in the UI; preserve the API status or show Reported.
    return explicit !== undefined ? String(explicit) : "Reported";
  };
  const statusClass = status => {
    const s = String(status).toLowerCase();
    return /critical|offline|down|error|failed|unreachable/.test(s) ? "bad" : /warning|degraded|maintenance|pending/.test(s) ? "warn" : /online|healthy|normal|ok|success|reported|active/.test(s) ? "good" : "neutral";
  };
  const healthClass = statusClass;

  function mount() {
    const path = location.pathname.replace(/\/+$/, "").toLowerCase();
    if (!path.endsWith("/monitoring") && !path.endsWith("/monitoring-overview") && !path.endsWith("/overview")) return;
    const main = document.querySelector("main") || document.querySelector("[role=main]");
    if (!main || main.dataset.cartmanMonitoringOverview === MARKER) return;
    main.dataset.cartmanMonitoringOverview = MARKER;
    main.innerHTML = `
      <div class="mo-shell" id="cartman-monitoring-overview-live">
        <header class="mo-page-head">
          <div><div class="mo-eyebrow">MONITORING &amp; OBSERVABILITY</div><h1>Overview <span class="mo-live"><i></i> Live</span></h1><p>Infrastructure health from Cartman monitoring APIs. Select one machine to inspect its collected telemetry.</p></div>
          <div class="mo-head-actions"><div class="mo-updated">Updated <strong id="mo-last-updated">—</strong></div><button type="button" class="mo-btn" id="mo-refresh">↻ Refresh</button><select id="mo-range" class="mo-select" aria-label="Metric time range">
  <option value="1h">Last hour</option>
  <option value="24h">Last 24 hours</option>
  <option value="7d" selected>Last 7 days</option>
  <option value="30d">Last 30 days</option>
  <option value="custom">Custom dates</option>
</select>
<div class="mo-custom-range" id="mo-custom-range-controls" hidden>
  <label for="mo-date-from">From
    <input type="date" id="mo-date-from" class="mo-date-input">
  </label>
  <label for="mo-date-to">To
    <input type="date" id="mo-date-to" class="mo-date-input">
  </label>
  <button type="button" class="mo-btn primary" id="mo-apply-range">Apply dates</button>
</div></div>
        </header>
        <div id="mo-api-status" class="mo-source-status pending"><span class="mo-dot"></span><span>Connecting to Cartman Monitoring API…</span></div>
        <section class="mo-kpis" aria-label="Monitoring summary">
          <article class="mo-card mo-kpi"><div class="mo-kpi-top"><span>Devices in inventory</span><b class="mo-icon blue">▣</b></div><strong id="mo-kpi-devices">—</strong><small>From the Cartman device API</small></article>
          <article class="mo-card mo-kpi"><div class="mo-kpi-top"><span>Online devices</span><b class="mo-icon green">●</b></div><strong id="mo-kpi-online">—</strong><small id="mo-kpi-online-note">Actual reported device states</small></article>
          <article class="mo-card mo-kpi"><div class="mo-kpi-top"><span>Active alerts</span><b class="mo-icon red">!</b></div><strong id="mo-kpi-alerts">—</strong><small>From Monitoring alerts API</small></article>
          <article class="mo-card mo-kpi mo-kpi-alerts">
            <div class="mo-section-head"><div><h2>Recent alerts</h2><p>Current records from Monitoring</p></div><span id="mo-alert-count" class="mo-count">—</span></div>
            <div id="mo-alert-list" class="mo-alert-list"><div class="mo-muted">Loading alerts…</div></div>
          </article>
        </section>
        <section class="mo-grid">
          <article class="mo-card mo-selected-card">
            <div class="mo-section-head"><div><h2>Live machine monitoring</h2><p>Choose one device; no table is created for other machines.</p></div><span class="mo-tag">Single-target view</span></div>
            <div class="mo-device-picker"><label for="mo-device-select">Machine</label><select class="mo-select" id="mo-device-select"><option value="">Loading devices…</option></select><button type="button" class="mo-btn primary" id="mo-load-device">Load metrics</button></div>
            <div id="mo-selected-meta" class="mo-selected-meta" hidden></div>
            <div id="mo-no-device" class="mo-empty"><div class="mo-empty-icon">⌖</div><strong>Select a machine to begin</strong><span>The metrics table will be built only for the selected machine.</span></div>
            <div id="mo-device-view" hidden>
              <div class="mo-metric-cards" id="mo-metric-cards"></div>
              <section class="mo-charts-grid" id="mo-charts-grid" aria-label="Selected device history charts"></section>
              <div class="mo-table-wrap"><div class="mo-table-top"><div><strong>Live metrics table</strong><small id="mo-table-caption">Waiting for telemetry…</small></div><span class="mo-live"><i></i> API data</span></div>
                <div class="mo-table-scroll"><table><thead><tr><th>Metric</th><th>Latest value</th><th>State</th><th>Collected at</th><th>Source</th></tr></thead><tbody id="mo-metric-rows"><tr><td colspan="5" class="mo-table-message">Select a machine to load metrics.</td></tr></tbody></table></div>
                <div id="mo-telemetry-note" class="mo-telemetry-note">Values are read from the API response; unavailable values are not simulated.</div>
              </div>
            </div>
            <div id="mo-device-error" class="mo-inline-error" hidden></div>
          </article>
        </section>
        <section class="mo-card mo-status-card"><div class="mo-section-head"><div><h2>Selected machine details</h2><p>Identity and status from Cartman Devices API</p></div><span id="mo-device-status" class="mo-state neutral">No target selected</span></div><div class="mo-details-grid" id="mo-device-details"><div class="mo-detail"><small>Hostname</small><strong>—</strong></div><div class="mo-detail"><small>IP address</small><strong>—</strong></div><div class="mo-detail"><small>Operating system</small><strong>—</strong></div><div class="mo-detail"><small>Device type</small><strong>—</strong></div></div></section>
        <footer class="mo-footnote">Cartman Monitoring Overview · API-backed view · No placeholder telemetry is generated by this page.</footer>
      </div>`;

    $("#mo-refresh", main).addEventListener("click", () => refreshAll(true));
    $("#mo-load-device", main).addEventListener("click", () => chooseDevice($("#mo-device-select", main).value));
    $("#mo-device-select", main).addEventListener("change", e => chooseDevice(e.target.value));
    $("#mo-range", main).addEventListener("change", e => {
      range = e.target.value;
      const controls = $("#mo-custom-range-controls", main);
      if (controls) controls.hidden = range !== "custom";

      if (range === "custom") {
        const from = $("#mo-date-from", main);
        const to = $("#mo-date-to", main);
        const formatDate = d =>
          `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

        const today = new Date();
        const start = new Date(today);
        start.setDate(start.getDate() - 6);

        if (from && !from.value) from.value = formatDate(start);
        if (to && !to.value) to.value = formatDate(today);

        setStatus("Choose the start and end dates, then select Apply dates.", "pending");
        return;
      }

      if (selectedDevice) void loadDeviceMetrics(true);
    });

    $("#mo-apply-range", main).addEventListener("click", () => {
      const from = $("#mo-date-from", main)?.value || "";
      const to = $("#mo-date-to", main)?.value || "";

      if (!from || !to) {
        setStatus("Choose both a start date and an end date.", "warn");
        return;
      }
      if (from > to) {
        setStatus("The start date must not be after the end date.", "warn");
        return;
      }

      range = "custom";
      const select = $("#mo-range", main);
      if (select) select.value = "custom";

      if (!selectedDevice) {
        setStatus("Date range saved. Select a machine to view its metrics.", "pending");
        return;
      }

      void loadDeviceMetrics(true);
    });
    void initialize();
  }

  async function initialize() {
    setStatus("Loading device inventory and monitoring records…", "pending");
    const errors = [];
    try {
      await loadDevices();
    } catch (error) {
      errors.push(`Devices API: ${error.message}`);
      renderDeviceOptions();
    }
    const jobs = await Promise.allSettled([loadSummary(), loadAlerts()]);
    jobs.forEach((r, i) => { if (r.status === "rejected") errors.push(`${i === 0 ? "Summary API" : "Alerts API"}: ${r.reason.message}`); });
    const params = new URLSearchParams(location.search);
    const requested = params.get("device_id") || params.get("device");
    if (requested && devices.some(d => String(idOf(d)) === requested || nameOf(d) === requested)) {
      const match = devices.find(d => String(idOf(d)) === requested || nameOf(d) === requested);
      chooseDevice(String(idOf(match)));
    } else if (requested) {
      setStatus("The requested device was not found in the current inventory.", "warn");
    }
    if (errors.length) setStatus(errors.join(" · "), "error");
    else setStatus("Connected to Cartman APIs. Device telemetry is fetched only after a target is selected.", "ok");
    setUpdated(new Date());
    if (pollingHandle) clearInterval(pollingHandle);
    pollingHandle = setInterval(() => { if (!refreshInProgress) void refreshAll(false); }, POLL_MS);
  }

  async function loadDevices() {
    const payload = await apiFetch(API.devices);
    devices = unwrap(payload).filter(isObj).filter(d => idOf(d) !== undefined && idOf(d) !== null);
    renderDeviceOptions();
    setKpi("mo-kpi-devices", devices.length);
    const online = devices.filter(d => /online|healthy|connected|active|available/i.test(statusOf(d))).length;
    const stateReported = devices.some(d => findKey(d, ["status", "state", "connection_status", "health_status"]) !== undefined);
    setKpi("mo-kpi-online", stateReported ? online : "—");
    setKpi("mo-kpi-online-note", stateReported ? `${devices.length - online} not reported online` : "Device API does not provide status fields");
  }

  function renderDeviceOptions() {
    const select = $("#mo-device-select");
    if (!select) return;
    const prev = select.value;
    select.innerHTML = `<option value="">Select a machine…</option>` + devices.map(d => `<option value="${esc(idOf(d))}">${esc(nameOf(d))}${ipOf(d) ? ` · ${esc(ipOf(d))}` : ""}</option>`).join("");
    if (prev && devices.some(d => String(idOf(d)) === prev)) select.value = prev;
    if (!devices.length) select.innerHTML = `<option value="">No devices returned by API</option>`;
  }

  async function loadSummary() {
    const payload = await apiFetch(API.summary);
    const alertsCount = findDeep(payload, ["active_alerts", "alerts_active", "alert_count", "active_alert_count", "total_alerts", "alerts"]);
    if (alertsCount !== undefined && !Array.isArray(alertsCount) && !isObj(alertsCount)) setKpi("mo-kpi-alerts", alertsCount);
    const online = firstNumber(payload, ["online_devices", "devices_online", "online_count", "online"]);
    if (online !== null) setKpi("mo-kpi-online", online);
    const total = firstNumber(payload, ["total_devices", "device_count", "devices_total", "total"]);
    if (total !== null) setKpi("mo-kpi-devices", total);
  }

  async function loadAlerts() {
    const payload = await apiFetch(API.alerts);
    const alerts = unwrap(payload).filter(isObj);
    const activeCount = findDeep(payload, ["active_count", "active_alerts", "total", "count"]);
    setKpi("mo-kpi-alerts", typeof activeCount === "number" || typeof activeCount === "string" ? activeCount : alerts.length);
    const count = $("#mo-alert-count");
    if (count) count.textContent = alerts.length;
    const list = $("#mo-alert-list");
    if (!list) return;
    if (!alerts.length) {
      list.innerHTML = `<div class="mo-empty-small"><span class="mo-empty-icon">✓</span><strong>No alert records returned</strong><small>This is the current API response, not generated sample data.</small></div>`;
      return;
    }
    list.innerHTML = alerts.slice(0, 8).map(a => {
      const title = findKey(a, ["title", "name", "message", "summary", "rule_name", "alert_name"]) ?? "Monitoring alert";
      const detail = findKey(a, ["description", "details", "message", "device_name", "target", "source"]) ?? "";
      const severity = String(findKey(a, ["severity", "level", "priority", "status"]) ?? "Info");
      const when = findKey(a, ["created_at", "timestamp", "triggered_at", "updated_at", "time"]);
      return `<article class="mo-alert-row"><span class="mo-alert-pin ${statusClass(severity)}"></span><div class="mo-alert-body"><strong>${esc(title)}</strong><p>${esc(detail)}</p><small>${esc(severity)}${when ? ` · ${esc(dateLabel(when))}` : ""}</small></div></article>`;
    }).join("");
  }

  async function chooseDevice(id) {
    selectedDevice = devices.find(d => String(idOf(d)) === String(id)) || null;
    metricsRequest++;
    const select = $("#mo-device-select");
    if (select && selectedDevice) select.value = String(idOf(selectedDevice));
    const empty = $("#mo-no-device"), view = $("#mo-device-view"), meta = $("#mo-selected-meta"), err = $("#mo-device-error");
    if (err) { err.hidden = true; err.textContent = ""; }
    if (!selectedDevice) {
      if (empty) empty.hidden = false;
      if (view) view.hidden = true;
      if (meta) meta.hidden = true;
      setKpi("mo-kpi-target", "None");
      renderDeviceDetails(null);
      return;
    }
    if (empty) empty.hidden = true;
    if (view) view.hidden = false;
    if (meta) {
      meta.hidden = false;
      meta.innerHTML = `<span class="mo-chip ${statusClass(statusOf(selectedDevice))}">${esc(statusOf(selectedDevice))}</span><span class="mo-chip">${esc(nameOf(selectedDevice))}</span>${ipOf(selectedDevice) ? `<span class="mo-chip">IP ${esc(ipOf(selectedDevice))}</span>` : ""}`;
    }
    setKpi("mo-kpi-target", nameOf(selectedDevice));
    renderDeviceDetails(selectedDevice);
    $("#mo-table-caption").textContent = `${nameOf(selectedDevice)} · waiting for API response`;
    $("#mo-metric-rows").innerHTML = `<tr><td colspan="5" class="mo-table-message">Loading metrics for the selected device…</td></tr>`;
    $("#mo-metric-cards").innerHTML = "";
    const chartHost = $("#mo-charts-grid");
    if (chartHost) chartHost.innerHTML = `<div class="mo-chart-loading">Loading history for ${esc(nameOf(selectedDevice))}…</div>`;
    await loadDeviceMetrics(true);
  }

  function renderDeviceDetails(device) {
    const panel = $("#mo-device-details");
    const state = $("#mo-device-status");
    if (!panel || !state) return;
    if (!device) {
      state.className = "mo-state neutral";
      state.textContent = "No target selected";
      panel.innerHTML = [["Hostname","—"],["IP address","—"],["Operating system","—"],["Device type","—"]].map(([l,v]) => `<div class="mo-detail"><small>${l}</small><strong>${v}</strong></div>`).join("");
      return;
    }
    const status = statusOf(device);
    state.className = `mo-state ${statusClass(status)}`;
    state.textContent = status;
    panel.innerHTML = [["Hostname",nameOf(device)],["IP address",ipOf(device) ?? "—"],["Operating system",osOf(device) ?? "—"],["Device type",typeOf(device) ?? "—"]].map(([l,v]) => `<div class="mo-detail"><small>${esc(l)}</small><strong>${esc(v)}</strong></div>`).join("");
  }

  async function loadDeviceMetrics(showSpinner) {
    if (!selectedDevice) return;
    const thisRequest = ++metricsRequest;
    const device = selectedDevice;
    const id = idOf(device);
    const params = new URLSearchParams();
    const values = {device_id:String(id), device_uuid:String(id), machine_id:String(id), device_name:nameOf(device), device:nameOf(device), hostname:nameOf(device), host:nameOf(device), target_id:String(id), target_name:nameOf(device), computer_name:nameOf(device), agent_id:String(id), node_id:String(id), asset_id:String(id), range, time_range:range, period:range};
    for (const key of METRIC_FILTER_PARAMS) if (Object.prototype.hasOwnProperty.call(values, key)) params.set(key, values[key]);
    params.set("limit", "1000");
    const url = params.size ? `${API.metrics}?${params.toString()}` : API.metrics;
    const err = $("#mo-device-error");
    if (showSpinner && err) { err.hidden = true; err.textContent = ""; }
    try {
      const payload = await apiFetch(url);
      if (thisRequest !== metricsRequest || !selectedDevice || String(idOf(selectedDevice)) !== String(id)) return;
      const rawRecords = unwrap(payload).filter(isObj);
      const rawHasTarget = rawRecords.some(r => findKey(r, DEVICE_FILTER_NAMES) !== undefined);
      const payloadHasTarget = isObj(payload) && findKey(payload, DEVICE_FILTER_NAMES) !== undefined;
      const serverCanScope = METRIC_FILTER_PARAMS.some(k => DEVICE_FILTER_NAMES.includes(k));
      const all = extractMetricRows(payload, device);
      if (all.length && !rawHasTarget && !payloadHasTarget && !serverCanScope) {
        throw new Error("Metrics API does not expose a device filter and its records do not identify their target. Refusing to display potentially mixed-device telemetry.");
      }
      renderMetricData(payload, all, device);
      setUpdated(new Date());
      if (!all.length) {
        setStatus(`Monitoring API responded for ${nameOf(device)}, but returned no metric samples for this device.`, "warn");
      } else {
        setStatus(`Connected · ${nameOf(device)} · ${all.length} metric records from Cartman Monitoring API.`, "ok");
      }
    } catch (error) {
      if (thisRequest !== metricsRequest) return;
      if (err) { err.hidden = false; err.textContent = `Could not load metrics for ${nameOf(device)}: ${error.message}`; }
      $("#mo-metric-rows").innerHTML = `<tr><td colspan="5" class="mo-table-message">No telemetry available. The API returned an error; this page will not substitute demo values.</td></tr>`;
      $("#mo-metric-cards").innerHTML = ["CPU", "Memory", "Disk", "Network"].map(label => metricCard(label, null, "", "No API value")).join("");
      renderMetricCharts([]);
      setStatus(`Monitoring API error for ${nameOf(device)}: ${error.message}`, "error");
    }
  }

  function extractMetricRows(payload, device) {
    let rows = unwrap(payload).filter(isObj);
    if (isObj(payload) && !rows.length) {
      const metricsObj = findKey(payload, ["metrics", "latest", "measurements", "values", "telemetry"]);
      if (isObj(metricsObj)) rows = Object.entries(metricsObj).map(([name, value]) => isObj(value) ? {name, ...value} : {name, value});
      else {
        const excluded = new Set(["device", "target", "metadata", "summary", "status", "success", "message", "source"]);
        rows = Object.entries(payload).filter(([k,v]) => !excluded.has(normalizedKey(k)) && (typeof v === "number" || (isObj(v) && (findKey(v,["value","current","latest_value"]) !== undefined)))).map(([name,value]) => isObj(value) ? {name, ...value} : {name,value});
      }
    }
    const wanted = String(idOf(device));
    const deviceName = nameOf(device).toLowerCase();
    const tagged = rows.filter(r => {
      const rid = findKey(r, ["device_id", "target_id", "host_id"]);
      const rname = findKey(r, ["device_name", "hostname", "host", "target_name"]);
      if (rid !== undefined && String(rid) !== wanted) return false;
      if (rname !== undefined && String(rname).toLowerCase() !== deviceName) return false;
      return true;
    });
    return tagged.filter(r => metricValue(r) !== undefined || metricLabel(r) !== "Metric");
  }

  function findMetric(rows, aliases) {
    const normalizedAliases = aliases.map(normalizedKey);
    return rows.find(r => normalizedAliases.includes(normalizedKey(metricLabel(r))) || normalizedAliases.some(a => normalizedKey(metricLabel(r)).includes(a)));
  }
  function metricCard(label, value, unit, note) {
    const n = asNumber(value);
    const pct = unit === "%" && n !== null ? Math.max(0, Math.min(100,n)) : null;
    return `<article class="mo-metric-card"><div class="mo-metric-label">${esc(label)}</div><strong>${value === null || value === undefined ? "—" : displayNum(value, unit)}</strong>${pct !== null ? `<div class="mo-bar"><span style="width:${pct}%"></span></div>` : ""}<small>${esc(note || (value === null || value === undefined ? "Not reported by API" : "Latest API value"))}</small></article>`;
  }
  /* CARTMAN_MONITORING_DATE_RANGE_V1 */
  function parseMetricTimestamp(value) {
    if (!value) return NaN;
    const normalized = String(value).trim().replace(
      /^(\d{4}-\d{2}-\d{2})\s+/, "$1T"
    );
    return new Date(normalized).getTime();
  }

  function getSelectedRangeBounds() {
    const now = Date.now();

    if (range === "custom") {
      const from = $("#mo-date-from")?.value || "";
      const to = $("#mo-date-to")?.value || "";
      if (!from || !to || from > to) {
        return { start: NaN, end: NaN };
      }

      const start = new Date(`${from}T00:00:00`).getTime();
      const end = new Date(`${to}T23:59:59.999`).getTime();
      return { start, end };
    }

    const spans = {
      "1h": 60 * 60 * 1000,
      "24h": 24 * 60 * 60 * 1000,
      "7d": 7 * 24 * 60 * 60 * 1000,
      "30d": 30 * 24 * 60 * 60 * 1000
    };

    return { start: now - (spans[range] || spans["7d"]), end: now };
  }

  function getRangeLabel() {
    return ({
      "1h": "Last hour",
      "24h": "Last 24 hours",
      "7d": "Last 7 days",
      "30d": "Last 30 days",
      "custom": "Custom dates"
    })[range] || "Selected period";
  }

  function filterMetricRowsForSelectedRange(rows) {
    const bounds = getSelectedRangeBounds();
    return rows.filter(row => {
      const timestamp = parseMetricTimestamp(metricTime(row));
      return Number.isFinite(timestamp) &&
        timestamp >= bounds.start && timestamp <= bounds.end;
    });
  }

  function metricDateLabel(value) {
    const timestamp = parseMetricTimestamp(value);
    return Number.isFinite(timestamp)
      ? new Date(timestamp).toLocaleString()
      : dateLabel(value);
  }

  /* CARTMAN_MONITORING_UNIFIED_CHART_V1 */

  const moCombinedChartState = {
    yMax: 100,
    timeWindowPct: 100,
    centerRatio: 0.5,
    rangeKey: null,
    visible: {cpu: true, memory: true, disk: true, network: true},
    rows: []
  };

  /* CARTMAN_MONITORING_EXPLORER_LIVE_V1 */
  function renderMetricCharts(rows) {
    const host = $("#mo-charts-grid");
    if (!host) return;
    const explorer = window.CartmanMonitoringExplorer;
    if (!explorer || typeof explorer.render !== "function") {
      host.innerHTML = `<div class="mo-chart-loading">Monitoring chart module could not be loaded. Check the browser network panel.</div>`;
      return;
    }
    explorer.render(rows, {
      range,
      bounds: getSelectedRangeBounds(),
      rangeLabel: getRangeLabel(),
      metricLabel,
      metricTime,
      metricValue,
      metricUnit,
      metricSource,
      parseTimestamp: parseMetricTimestamp,
      asNumber,
      normalizeKey: normalizedKey,
      escapeHtml: esc
    });
  }

  function renderMetricData(payload, rows, device) {
    /* CARTMAN_PROCESS_USAGE_SELECTED_DEVICE_HOOK_V1 */
    try { window.dispatchEvent(new CustomEvent('cartman:monitoring-selected-device', { detail: { device, payload } })); } catch (_processUsageHookError) {}
    const targetLabel = nameOf(device);
    const displayedRows = filterMetricRowsForSelectedRange(rows);
    const stamp = findDeep(payload, ["collected_at", "timestamp", "updated_at", "last_updated", "generated_at"]);
    $("#mo-table-caption").textContent = `${targetLabel} · ${displayedRows.length} metric record${displayedRows.length === 1 ? "" : "s"} · ${getRangeLabel()}`;
    const cards = [
      {label:"CPU utilization", aliases:["cpu_percent","cpu_usage","cpu_utilization","cpu"], unit:"%"},
      {label:"Memory utilization", aliases:["memory_percent","memory_usage","ram_usage","memory_utilization","mem_used_percent"], unit:"%"},
      {label:"Disk utilization", aliases:["disk_percent","disk_usage","disk_utilization","volume_usage"], unit:"%"},
      {label:"Network throughput", aliases:["network_mbps","network_throughput","network_rate","network_io","bytes_per_sec","network"], unit:""}
    ];
    $("#mo-metric-cards").innerHTML = cards.map(c => {
      const m = findMetric(rows, c.aliases);
      const value = m ? metricValue(m) : null;
      const unit = m ? (metricUnit(m) || c.unit) : c.unit;
      const note = m ? `Source: ${metricSource(m) ?? "Monitoring API"}` : "Not reported by API";
      return metricCard(c.label, value, unit, note);
    }).join("");
    const tbody = $("#mo-metric-rows");
    renderMetricCharts(rows);
    if (!displayedRows.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="mo-table-message"><strong>No metrics returned.</strong><br>Device inventory exists, but the monitoring API has no telemetry sample for this machine yet.</td></tr>`;
      $("#mo-telemetry-note").textContent = "No sample data was returned for this selected target. Check whether an endpoint agent or monitoring collector is publishing metrics.";
      return;
    }
    tbody.innerHTML = displayedRows.slice(0, 250).map(m => {
      const label = metricLabel(m);
      const val = metricValue(m);
      const unit = metricUnit(m);
      const status = statusForMetric(m);
      const time = metricTime(m) || stamp;
      return `<tr><td><strong>${esc(label)}</strong></td><td>${esc(displayNum(val, unit ? ` ${unit}` : ""))}</td><td><span class="mo-state ${statusClass(status)}">${esc(status)}</span></td><td>${esc(metricDateLabel(time))}</td><td>${esc(metricSource(m) ?? findKey(m,["source_name","collector_name"]) ?? "Monitoring API")}</td></tr>`;
    }).join("");
    $("#mo-telemetry-note").textContent = `API returned ${displayedRows.length} metric records for ${targetLabel} within ${getRangeLabel()}. No client-side synthetic values are added.`;
  }

  async function refreshAll(manual) {
    if (refreshInProgress) return;
    refreshInProgress = true;
    const button = $("#mo-refresh");
    if (manual && button) { button.disabled = true; button.textContent = "↻ Refreshing…"; }
    const jobs = await Promise.allSettled([loadDevices(), loadSummary(), loadAlerts()]);
    const rejected = jobs.filter(r => r.status === "rejected");
    if (selectedDevice) {
      // Refresh the selection against latest inventory and avoid silently switching targets.
      const currentId = String(idOf(selectedDevice));
      const latest = devices.find(d => String(idOf(d)) === currentId);
      if (latest) selectedDevice = latest;
      await loadDeviceMetrics(false);
    }
    if (rejected.length) setStatus(`${rejected.length} Monitoring API request(s) failed during refresh. See the affected panels.`, "error");
    else if (!selectedDevice) setStatus("Connected · choose a machine to fetch its metrics.", "ok");
    setUpdated(new Date());
    refreshInProgress = false;
    if (manual && button) { button.disabled = false; button.textContent = "↻ Refresh"; }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once:true});
  else mount();
})();

/* CARTMAN_MONITORING_CHART_CONTROLS_V1 */
