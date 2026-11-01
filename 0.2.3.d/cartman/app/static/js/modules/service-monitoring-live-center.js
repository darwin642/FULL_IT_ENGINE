/* CARTMAN_SERVICE_MONITORING_LIVE_CENTER_V1
 * Dedicated controller for /pages/service-monitoring/.
 * Reads actual recorded service checks; it does not fabricate telemetry or run remote service actions.
 */
(() => {
  "use strict";
  const MARKER = "CARTMAN_SERVICE_MONITORING_LIVE_CENTER_V1";
  // CARTMAN_SERVICE_MONITORING_AUDIT_LOG_V1
  if (window.__cartmanServiceMonitoringLiveCenter === MARKER) return;
  window.__cartmanServiceMonitoringLiveCenter = MARKER;

  const API = {
    services: "/api/monitoring/services?limit=500",
    devices: "/api/devices",
    events: "/api/monitoring/events?limit=300",
    alerts: "/api/monitoring/alerts?limit=200",
    definitionBase: "/api/monitoring/service-check-definitions",
    definitions: "/api/monitoring/service-check-definitions?limit=500",
    audit: "/api/monitoring/service-check-audit?limit=500"
  };
  const REFRESH_MS = 30000;
  const PAGE_SIZE = 10;
  const state = {
    host: null, module: null, services: [], devices: [], events: [], alerts: [], definitions: [],
    currentUser: null, canManageChecks: false, modalOpen: false, editingDefinition: null, savingDefinition: false,
    definitionError: "", definitionNotice: "",
    query: "", status: "all", os: "all", device: "all", sort: "latest",
    selected: "", page: 1, loading: false, error: "", updatedAt: null, timer: null,
    servicesLoaded: false,
    auditLogs: [], auditLoaded: false, auditError: "", auditQuery: "", auditActor: "all",
    auditAction: "all", auditDevice: "all", auditFrom: "", auditTo: "", auditSort: "newest",
    auditSelected: "", auditPage: 1
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const isObj = value => !!value && typeof value === "object" && !Array.isArray(value);
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
  const compact = value => Number(value || 0).toLocaleString();

  function listOf(data, keys = ["items", "results", "records", "checks", "services", "events", "alerts", "devices"]) {
    if (Array.isArray(data)) return data;
    if (!isObj(data)) return [];
    for (const key of keys) if (Array.isArray(data[key])) return data[key];
    for (const key of ["data", "result", "response"]) {
      if (isObj(data[key])) {
        const nested = listOf(data[key], keys);
        if (nested.length) return nested;
      }
    }
    return [];
  }

  async function getJSON(url) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json" }
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; }
    catch (_) { data = { detail: raw.slice(0, 240) }; }
    if (!response.ok) {
      const error = new Error(data.detail || data.message || `${response.status} ${response.statusText}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function pick(row, keys, fallback = "") {
    for (const key of keys) {
      if (row && row[key] !== null && row[key] !== undefined && row[key] !== "") return row[key];
    }
    return fallback;
  }

  function timestamp(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "number") return new Date(value > 100000000000 ? value : value * 1000);
    let source = String(value).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(source)) source = source.replace(" ", "T") + "Z";
    const parsed = new Date(source);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function timeValue(row) {
    return pick(row, ["checked_at", "last_checked_at", "observed_at", "recorded_at", "timestamp", "created_at", "updated_at"], null);
  }

  function timeText(value) {
    const date = timestamp(value);
    return date ? date.toLocaleString([], { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Not recorded";
  }

  function relativeTime(value) {
    const date = timestamp(value);
    if (!date) return "No timestamp";
    const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  function serviceName(row) {
    return String(pick(row, ["service_name", "display_name", "service", "name", "label", "service_id"], "Unnamed service"));
  }

  function deviceId(row) {
    return String(pick(row, ["device_id", "deviceId", "computer_id", "asset_id", "host_id", "node_id"], ""));
  }

  function deviceLabel(row) {
    return String(pick(row, ["device_name", "hostname", "host_name", "computer_name", "host", "target_name"], ""));
  }

  function serviceStatus(row) {
    return String(pick(row, ["status", "service_status", "state", "result", "check_status", "health"], "Unknown")).trim();
  }

  function statusKind(status) {
    const value = String(status || "").toLowerCase();
    if (/(warning|degraded|slow|partial|unstable|delayed)/.test(value)) return "warning";
    if (/(stopped|down|offline|failed|failure|critical|unavailable|timeout|error|crashed|not running)/.test(value)) return "problem";
    if (/(running|healthy|success|passed|operational|available|active|started|^ok$|^up$)/.test(value)) return "healthy";
    return "unknown";
  }

  function responseMs(row) {
    const value = pick(row, ["response_ms", "latency_ms", "duration_ms", "response_time_ms", "response_time", "duration"], null);
    if (value === null) return null;
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return null;
    const secondsLike = row.response_time === value && row.response_ms === undefined && row.response_time_ms === undefined && row.latency_ms === undefined;
    return secondsLike ? number * 1000 : number;
  }

  function serviceKey(row) {
    const sid = pick(row, ["service_id", "service_key"], "");
    const device = deviceId(row) || deviceLabel(row);
    return `${device.toLowerCase()}::${String(sid || serviceName(row)).toLowerCase()}`;
  }

  function deviceMap() {
    const map = new Map();
    for (const device of state.devices) {
      const id = String(pick(device, ["id", "device_id", "asset_id"], ""));
      if (id) map.set(id, device);
      const name = String(pick(device, ["name", "hostname", "device_name"], ""));
      if (name) map.set(name.toLowerCase(), device);
    }
    return map;
  }

  function deviceInfo(row) {
    const map = deviceMap();
    const id = deviceId(row);
    const label = deviceLabel(row);
    const found = (id && map.get(id)) || (label && map.get(label.toLowerCase())) || null;
    return {
      id,
      name: label || (found && pick(found, ["name", "hostname", "device_name"], "")) || id || "Unassigned device",
      os: String(pick(row, ["os", "operating_system", "platform"], found ? pick(found, ["os", "operating_system", "platform"], "Unknown OS") : "Unknown OS")),
      status: found ? String(pick(found, ["status", "connection_status"], "")) : ""
    };
  }

  function groupedServices() {
    const groups = new Map();
    const sorted = [...state.services].sort((a, b) => (timestamp(timeValue(b))?.getTime() || 0) - (timestamp(timeValue(a))?.getTime() || 0));
    for (const row of sorted) {
      const key = serviceKey(row);
      if (!groups.has(key)) groups.set(key, { key, name: serviceName(row), latest: row, history: [] });
      const group = groups.get(key);
      group.history.push(row);
      const newDate = timestamp(timeValue(row));
      const oldDate = timestamp(timeValue(group.latest));
      if (newDate && (!oldDate || newDate > oldDate)) group.latest = row;
    }
    return Array.from(groups.values()).map(group => {
      group.name = serviceName(group.latest) || group.name;
      group.device = deviceInfo(group.latest);
      group.status = serviceStatus(group.latest);
      group.kind = statusKind(group.status);
      group.checkedAt = timeValue(group.latest);
      group.response = responseMs(group.latest);
      group.startup = String(pick(group.latest, ["startup_type", "start_type", "service_start_type", "start_mode"], "Not reported"));
      group.pid = pick(group.latest, ["pid", "process_id", "service_pid"], null);
      group.message = String(pick(group.latest, ["message", "detail", "error", "reason", "description", "output"], ""));
      group.history.sort((a, b) => (timestamp(timeValue(b))?.getTime() || 0) - (timestamp(timeValue(a))?.getTime() || 0));
      group.events = relatedRows(state.events, group, false).slice(0, 5);
      group.alerts = relatedRows(state.alerts, group, true).slice(0, 5);
      return group;
    });
  }

  function rowText(row) {
    return String(pick(row, ["title", "event_type", "type", "source", "category", "service_name", "message", "detail", "description", "name"], ""));
  }

  function relatedRows(rows, group, alertMode) {
    const needle = group.name.toLowerCase();
    const device = group.device.id;
    return rows.filter(row => {
      const text = [rowText(row), pick(row, ["message", "detail", "description", "summary"], "")].join(" ").toLowerCase();
      const rowDevice = String(pick(row, ["device_id", "deviceId", "asset_id", "host_id"], ""));
      const hasService = text.includes(needle) || String(pick(row, ["service_name", "service_id"], "")).toLowerCase() === needle;
      const sameDevice = device && rowDevice && device === rowDevice;
      if (alertMode) return hasService || sameDevice;
      return (hasService || sameDevice) && /(service|process|daemon|systemd|windows service|restart|stopped|started|check)/i.test(text);
    }).sort((a, b) => (timestamp(pick(b, ["occurred_at", "created_at", "timestamp", "event_time", "recorded_at"], null))?.getTime() || 0) - (timestamp(pick(a, ["occurred_at", "created_at", "timestamp", "event_time", "recorded_at"], null))?.getTime() || 0));
  }

  function badge(status, kind) {
    const tone = kind || statusKind(status);
    return `<span class="svc-badge ${esc(tone)}"><i></i>${esc(status || "Unknown")}</span>`;
  }

  function kpi(label, value, note, symbol, tone) {
    return `<article class="svc-kpi ${tone || ""}"><div class="svc-kpi-head"><span>${esc(label)}</span><span class="svc-kpi-symbol">${symbol}</span></div><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`;
  }

  function stateBar(groups) {
    const counts = [
      { key: "healthy", label: "Healthy", count: groups.filter(group => group.kind === "healthy").length },
      { key: "warning", label: "Warning", count: groups.filter(group => group.kind === "warning").length },
      { key: "problem", label: "Stopped / failed", count: groups.filter(group => group.kind === "problem").length },
      { key: "unknown", label: "Unknown", count: groups.filter(group => group.kind === "unknown").length }
    ];
    const total = groups.length || 1;
    return `<div class="svc-state-stack">${counts.map(item => `<span class="${item.key}" style="width:${item.count / total * 100}%" title="${esc(item.label)}: ${item.count}"></span>`).join("")}</div><div class="svc-state-legend">${counts.map(item => `<span><i class="${item.key}"></i>${esc(item.label)} <strong>${item.count}</strong></span>`).join("")}</div>`;
  }

  function recentEvents() {
    const rows = state.events.filter(row => /(service|daemon|systemd|process|started|stopped|restart)/i.test(rowText(row))).sort((a, b) => (timestamp(pick(b, ["occurred_at", "created_at", "timestamp", "event_time", "recorded_at"], null))?.getTime() || 0) - (timestamp(pick(a, ["occurred_at", "created_at", "timestamp", "event_time", "recorded_at"], null))?.getTime() || 0)).slice(0, 6);
    if (!rows.length) return `<div class="svc-empty compact"><strong>No service-related events recorded</strong><span>Service events will appear when Cartman receives event records related to service state changes.</span></div>`;
    return `<div class="svc-event-list">${rows.map(row => {
      const title = pick(row, ["title", "event_type", "type", "service_name"], "Service event");
      const text = pick(row, ["message", "detail", "description", "summary"], "");
      const when = pick(row, ["occurred_at", "created_at", "timestamp", "event_time", "recorded_at"], null);
      const who = pick(row, ["device_name", "hostname", "device_id"], "");
      return `<article class="svc-event"><span class="svc-event-dot"></span><div class="svc-event-copy"><strong>${esc(title)}</strong><p>${esc(text || who || "Recorded service event")}</p><small>${esc(who)}${who ? " | " : ""}${esc(relativeTime(when))}</small></div></article>`;
    }).join("")}</div>`;
  }

  function filteredGroups(groups) {
    const query = state.query.trim().toLowerCase();
    let output = groups.filter(group => {
      const blob = [group.name, group.device.name, group.device.id, group.device.os, group.status, group.message].join(" ").toLowerCase();
      return (!query || blob.includes(query)) &&
        (state.status === "all" || group.kind === state.status) &&
        (state.os === "all" || group.device.os === state.os) &&
        (state.device === "all" || group.device.id === state.device || group.device.name === state.device);
    });
    if (state.sort === "name") output.sort((a, b) => a.name.localeCompare(b.name));
    else if (state.sort === "status") output.sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name));
    else if (state.sort === "device") output.sort((a, b) => a.device.name.localeCompare(b.device.name) || a.name.localeCompare(b.name));
    else output.sort((a, b) => (timestamp(timeValue(b.latest))?.getTime() || 0) - (timestamp(timeValue(a.latest))?.getTime() || 0));
    return output;
  }

  function renderTable(groups) {
    const totalPages = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
    state.page = Math.min(state.page, totalPages);
    const start = (state.page - 1) * PAGE_SIZE;
    const visible = groups.slice(start, start + PAGE_SIZE);
    const body = visible.map(group => `<tr tabindex="0" data-svc-select="${esc(group.key)}" class="${state.selected === group.key ? "selected" : ""}">
      <td><div class="svc-name"><span class="svc-service-icon">&#9678;</span><span><strong>${esc(group.name)}</strong><small>${esc(group.startup)}</small></span></div></td>
      <td><strong>${esc(group.device.name)}</strong><small class="svc-sub">${esc(group.device.os)}</small></td>
      <td>${badge(group.status, group.kind)}</td>
      <td>${group.response === null ? "Not reported" : `${Math.round(group.response)} ms`}</td>
      <td><span title="${esc(timeText(group.checkedAt))}">${esc(relativeTime(group.checkedAt))}</span><small class="svc-sub">${esc(timeText(group.checkedAt))}</small></td>
      <td><button class="svc-link-button" data-svc-open="${esc(group.key)}">Details</button></td>
    </tr>`).join("");
    return `<div class="svc-table-wrap"><table class="svc-table"><thead><tr><th>Service</th><th>Device / OS</th><th>Current state</th><th>Response</th><th>Last check</th><th></th></tr></thead><tbody>${body || `<tr><td colspan="6"><div class="svc-empty"><strong>No matching service records</strong><span>Try changing the search or filters. The page does not insert sample services.</span></div></td></tr>`}</tbody></table></div>
      <div class="svc-table-foot"><span>Showing ${groups.length ? start + 1 : 0}-${Math.min(start + PAGE_SIZE, groups.length)} of ${groups.length} services</span><div><button class="svc-btn secondary" data-svc-page="prev" ${state.page <= 1 ? "disabled" : ""}>Previous</button><span>Page ${state.page} / ${totalPages}</span><button class="svc-btn secondary" data-svc-page="next" ${state.page >= totalPages ? "disabled" : ""}>Next</button></div></div>`;
  }

  function renderDetail(groups) {
    const group = groups.find(item => item.key === state.selected) || groups[0];
    if (group && state.selected !== group.key) state.selected = group.key;
    if (!group) return `<section class="svc-panel svc-detail"><div class="svc-empty"><strong>Select a service to inspect</strong><span>Recorded check details and related events will appear here.</span></div></section>`;
    const history = group.history.slice(0, 8);
    const historyRows = history.map(row => `<div class="svc-history-row"><span class="svc-history-dot ${statusKind(serviceStatus(row))}"></span><span>${esc(serviceStatus(row))}</span><span>${responseMs(row) === null ? "--" : `${Math.round(responseMs(row))} ms`}</span><time title="${esc(timeText(timeValue(row)))}">${esc(timeText(timeValue(row)))}</time></div>`).join("");
    const notes = group.message ? `<div class="svc-note"><strong>Last reported detail</strong><p>${esc(group.message)}</p></div>` : `<div class="svc-note"><strong>Last reported detail</strong><p>No additional detail was included in the latest service record.</p></div>`;
    const eventRows = group.events.length ? group.events.map(row => `<div class="svc-related-row"><strong>${esc(pick(row, ["title", "event_type", "type", "service_name"], "Service event"))}</strong><span>${esc(pick(row, ["message", "detail", "description", "summary"], "Recorded event"))}</span><time>${esc(timeText(pick(row, ["occurred_at", "created_at", "timestamp", "event_time", "recorded_at"], null)))}</time></div>`).join("") : `<div class="svc-empty compact"><span>No related service events returned for this device and service.</span></div>`;
    const alertRows = group.alerts.length ? group.alerts.map(row => `<div class="svc-related-row"><strong>${esc(pick(row, ["title", "name", "alert_code", "id"], "Monitoring alert"))}</strong><span>${esc(pick(row, ["message", "detail", "description", "summary"], "Recorded alert"))}</span><time>${esc(timeText(pick(row, ["occurred_at", "created_at", "timestamp", "opened_at", "updated_at"], null)))}</time></div>`).join("") : `<div class="svc-empty compact"><span>No related alerts returned for this device and service.</span></div>`;
    const monitorHref = group.device.id ? `/pages/monitoring/?device_id=${encodeURIComponent(group.device.id)}` : "/pages/monitoring/";
    return `<section class="svc-panel svc-detail" id="svc-detail"><header class="svc-panel-head"><div><div class="svc-eyebrow">SELECTED SERVICE</div><h2>${esc(group.name)}</h2><p>${esc(group.device.name)} | ${esc(group.device.os)}</p></div><div>${badge(group.status, group.kind)}</div></header>
      <div class="svc-detail-grid"><div><span>Last check</span><strong>${esc(timeText(group.checkedAt))}</strong></div><div><span>Check records</span><strong>${compact(group.history.length)}</strong></div><div><span>Startup type</span><strong>${esc(group.startup)}</strong></div><div><span>Process ID</span><strong>${group.pid == null ? "Not reported" : esc(group.pid)}</strong></div></div>
      ${notes}
      <div class="svc-detail-columns"><section><h3>Recorded check history</h3><div class="svc-history">${historyRows || `<div class="svc-empty compact">No check history was returned.</div>`}</div></section><section><h3>Related events</h3><div class="svc-related-list">${eventRows}</div><h3 class="svc-subhead">Related alerts</h3><div class="svc-related-list">${alertRows}</div></section></div>
      <div class="svc-detail-actions"><a class="svc-btn secondary" href="${monitorHref}">Open device in Monitoring &rarr;</a><span>Read-only view. Service control actions are not enabled in this build.</span></div>
    </section>`;
  }

/* CARTMAN_SERVICE_CHECK_DEFINITIONS_UI_V1 */
  async function sendJSON(url, method, body) {
    const response = await fetch(url, {method, credentials:"same-origin", cache:"no-store", headers:{Accept:"application/json", "Content-Type":"application/json"}, body:body === undefined ? undefined : JSON.stringify(body)});
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = {detail:raw.slice(0,240)}; }
    if (!response.ok) { const error = new Error(data.detail || data.message || `${response.status} ${response.statusText}`); error.status=response.status; throw error; }
    return data;
  }

  function renderConfiguredChecks() {
    const rows = state.definitions || [];
    const body = rows.length ? rows.map(row => `<tr>
      <td><strong>${esc(row.service_name)}</strong><small class="svc-sub">${row.check_type === "dns_query" ? esc(row.dns_record_type || "A") + " · " + esc(row.service_identifier) + " · via " + esc(row.dns_server || "DNS server") : esc(row.service_identifier)}</small></td>
      <td><strong>${esc(row.device_name || row.device_id)}</strong><small class="svc-sub">${esc(row.device_os || row.platform)}</small></td>
      <td>${esc(({windows_service:"Windows service",http:"HTTP / HTTPS",tcp:"TCP port",dns_query:"DNS query"})[row.check_type] || row.check_type)}</td>
      <td>${esc(String(row.interval_seconds))} sec</td>
      <td><span class="svc-badge ${row.enabled ? "warning" : "unknown"}"><i></i>${row.enabled ? "Configured" : "Disabled"}</span><small class="svc-sub">${row.enabled ? "Awaiting collector" : "Not scheduled"}</small></td>
      <td><div class="svc-config-actions"><button class="svc-link-button" data-svc-config-edit="${esc(row.id)}">Edit</button><button class="svc-link-button" data-svc-config-toggle="${esc(row.id)}" data-enabled="${row.enabled ? "1" : "0"}">${row.enabled ? "Disable" : "Enable"}</button><button class="svc-link-button danger" data-svc-config-delete="${esc(row.id)}">Delete</button></div></td>
    </tr>`).join("") : `<tr><td colspan="6"><div class="svc-empty"><strong>No service checks configured</strong><span>Add a check to save which service should be monitored on a device. Live results will appear after a collector is connected.</span></div></td></tr>`;
    const roleNote = state.canManageChecks ? "Configuration only; the remote collector is not connected in this build." : "Read-only view. An administrator or network administrator can configure service checks.";
    return `<section class="svc-panel svc-config-panel"><header class="svc-panel-head"><div><h2>Configured service checks</h2><p>Saved service-monitoring definitions, separate from recorded check results.</p></div><div class="svc-config-head-actions"><span class="svc-count">${rows.length} configured</span>${state.canManageChecks ? `<button class="svc-btn primary" data-svc-new-check>+ Add Service Check</button>` : ""}</div></header>
      ${state.definitionError ? `<div class="svc-banner error"><strong>Configuration API unavailable.</strong><span>${esc(state.definitionError)}</span><button type="button" class="svc-btn secondary" data-svc-config-refresh>Retry</button></div>` : ""}
      ${state.definitionNotice ? `<div class="svc-banner"><span class="svc-live-dot"></span><span>${esc(state.definitionNotice)}</span></div>` : ""}
      <div class="svc-table-wrap"><table class="svc-table svc-config-table"><thead><tr><th>Service</th><th>Computer</th><th>Check type</th><th>Interval</th><th>Configuration</th><th>Actions</th></tr></thead><tbody>${body}</tbody></table></div>
      <div class="svc-config-note">${esc(roleNote)} Saved definitions do not claim a service is healthy until actual check results are reported.</div></section>`;
  }

  function isWindowsServerDevice(device) {
    const os = String(pick(device, ["os", "operating_system", "operatingSystem"], "")).trim().toLowerCase();
    if (!os.includes("windows")) return false;
    if (os.includes("server")) return true;

    let tags = pick(device, ["tags", "device_tags"], []);
    if (typeof tags === "string") {
      try {
        const parsed = JSON.parse(tags);
        tags = Array.isArray(parsed) ? parsed : [tags];
      } catch (_) {
        tags = tags.split(/[;,|]/);
      }
    }
    if (!Array.isArray(tags)) tags = [tags];
    return tags.some(tag => {
      const name = isObj(tag) ? pick(tag, ["name", "label", "value"], "") : tag;
      return ["server", "windows server"].includes(String(name || "").trim().toLowerCase());
    });
  }

  function updateCheckMethodFields(form) {
    if (!form) return;
    const method = form.querySelector('select[name="check_type"]');
    const isDns = !!method && method.value === "dns_query";
    const platform = form.querySelector('select[name="platform"]');
    if (platform) {
      for (const option of platform.options) option.disabled = isDns && option.value !== "Windows";
      if (isDns) platform.value = "Windows";
    }
    const device = form.querySelector('select[name="device_id"]');
    if (device) {
      for (const option of device.options) {
        if (!option.value) continue;
        option.disabled = isDns && !/windows/i.test(option.dataset.os || "");
      }
      if (isDns && device.selectedOptions.length && device.selectedOptions[0].disabled) device.value = "";
    }
    const label = form.querySelector("[data-svc-identifier-label]");
    const input = form.querySelector('input[name="service_identifier"]');
    const help = form.querySelector("[data-svc-identifier-help]");
    if (label) label.textContent = isDns ? "DNS query name *" : "Service identifier / endpoint *";
    if (input) input.placeholder = isDns ? "_ldap._tcp.dc._msdcs.ad.example.com" : "Dnscache, nginx.service, https://host/health or host:443";
    if (help) help.textContent = isDns
      ? "Enter the DNS record name to query. For AD, use the real domain in the SRV query name."
      : "Use a Windows service name, systemd unit, URL or host:port according to check method.";

    for (const field of form.querySelectorAll("[data-svc-dns-field]")) {
      field.style.display = isDns ? "" : "none";
      const control = field.querySelector("input,select");
      if (control) control.required = isDns && control.dataset.svcDnsRequired === "true";
    }
    const dnsServer = form.querySelector('input[name="dns_server"]');
    const selected = device && device.selectedOptions.length ? device.selectedOptions[0] : null;
    if (isDns && dnsServer && selected) {
      const autoValue = dnsServer.dataset.autoValue || "";
      if ((!dnsServer.value.trim() || (autoValue && dnsServer.value === autoValue)) && selected.dataset.ip) {
        dnsServer.value = selected.dataset.ip;
        dnsServer.dataset.autoValue = dnsServer.value;
      }
    }
  }

  function renderCheckModal() {
    if (!state.modalOpen) return "";
    const row = state.editingDefinition || {};
    const devices = [...(state.devices || [])].filter(isWindowsServerDevice).sort((a,b)=>String(pick(a,["name","hostname"],"")).localeCompare(String(pick(b,["name","hostname"],""))));
    const checkType = String(row.check_type || "windows_service");
    const selectedDevice = devices.find(device => String(pick(device,["id","device_id","asset_id"],"")) === String(row.device_id || ""));
    const initialDnsServer = String(row.dns_server || pick(selectedDevice,["ip","private_ip","ip_address"],""));
    const deviceOptions = devices.map(device => {
      const id = String(pick(device,["id","device_id","asset_id"],""));
      const name = String(pick(device,["name","hostname","device_name"],id));
      const os = String(pick(device,["os"],""));
      const ip = String(pick(device,["ip","private_ip","ip_address"],""));
      const disabled = checkType === "dns_query" && !/windows/i.test(os) ? "disabled" : "";
      return `<option value="${esc(id)}" data-os="${esc(os)}" data-ip="${esc(ip)}" ${disabled} ${String(row.device_id || "")===id?"selected":""}>${esc(name)}${os?" - "+esc(os):""}</option>`;
    }).join("");
    const isDns = checkType === "dns_query";
    return `<div class="svc-modal-backdrop" data-svc-modal-backdrop><section class="svc-modal" role="dialog" aria-modal="true" aria-labelledby="svc-check-modal-title"><header class="svc-modal-head"><div><div class="svc-eyebrow">SERVICE CONFIGURATION</div><h2 id="svc-check-modal-title">${row.id ? "Edit Service Check" : "Add Service Check"}</h2><p>Define a check target and its failure policy.</p></div><button type="button" class="svc-btn secondary" data-svc-close-modal aria-label="Close dialog">Close</button></header>
      <form data-svc-config-form data-definition-id="${esc(row.id || "")}"><div class="svc-form-grid">
      <label class="wide"><span>Windows Server *</span><select name="device_id" required><option value="">Select a Windows Server</option>${deviceOptions}</select><small>Only devices identified as Windows Server (OS label or Server tag) are available in this build.</small></label>
      <label><span>Display name *</span><input name="service_name" maxlength="120" required value="${esc(row.service_name || "")}" placeholder="DNS Server"></label>
      <label><span>Platform *</span><select name="platform" required><option value="Windows" selected>Windows</option></select></label>
      <label><span>Check method *</span><select name="check_type" required><option value="windows_service" ${checkType==="windows_service"?"selected":""}>Windows service</option><option value="http" ${checkType==="http"?"selected":""}>HTTP / HTTPS endpoint</option><option value="tcp" ${checkType==="tcp"?"selected":""}>TCP port</option><option value="dns_query" ${isDns?"selected":""}>DNS query</option></select></label>
      <label class="wide"><span data-svc-identifier-label>${isDns?"DNS query name *":"Service identifier / endpoint *"}</span><input data-svc-identifier-input name="service_identifier" maxlength="300" required value="${esc(row.service_identifier || "")}" placeholder="${isDns?"_ldap._tcp.dc._msdcs.ad.example.com":"Dnscache, nginx.service, https://host/health or host:443"}"><small data-svc-identifier-help>${isDns?"Enter the DNS record name to query. For AD, use the real domain in the SRV query name.":"Use a Windows service name, systemd unit, URL or host:port according to check method."}</small></label>
      <label class="wide" data-svc-dns-field style="${isDns?"":"display:none"}"><span>DNS server address *</span><input name="dns_server" maxlength="253" value="${esc(initialDnsServer)}" placeholder="192.168.1.10 or dns01.ad.example.com" data-svc-dns-required="true" data-auto-value="${esc(row.dns_server ? "" : initialDnsServer)}" ${isDns?"required":""}><small>Resolver to query; the selected Windows device IP is suggested when available.</small></label>
      <label data-svc-dns-field style="${isDns?"":"display:none"}"><span>DNS record type *</span><select name="dns_record_type" data-svc-dns-required="true" ${isDns?"required":""}><option value="A" ${String(row.dns_record_type || "A")==="A"?"selected":""}>A — IPv4 address</option><option value="AAAA" ${row.dns_record_type==="AAAA"?"selected":""}>AAAA — IPv6 address</option><option value="CNAME" ${row.dns_record_type==="CNAME"?"selected":""}>CNAME — alias</option><option value="MX" ${row.dns_record_type==="MX"?"selected":""}>MX — mail exchanger</option><option value="SRV" ${row.dns_record_type==="SRV"?"selected":""}>SRV — service record</option></select></label>
      <label class="wide" data-svc-dns-field style="${isDns?"":"display:none"}"><span>Expected answer (optional)</span><input name="dns_expected_answer" maxlength="512" value="${esc(row.dns_expected_answer || "")}" placeholder="192.168.1.25 or a matching DNS target"></label>
      <label data-svc-dns-field style="${isDns?"":"display:none"}"><span>Query timeout</span><select name="dns_timeout_seconds"><option value="1" ${Number(row.dns_timeout_seconds || 3)===1?"selected":""}>1 second</option><option value="2" ${Number(row.dns_timeout_seconds || 3)===2?"selected":""}>2 seconds</option><option value="3" ${Number(row.dns_timeout_seconds || 3)===3?"selected":""}>3 seconds</option><option value="5" ${Number(row.dns_timeout_seconds || 3)===5?"selected":""}>5 seconds</option><option value="10" ${Number(row.dns_timeout_seconds || 3)===10?"selected":""}>10 seconds</option></select></label>
      <label><span>Check interval</span><select name="interval_seconds"><option value="30" ${Number(row.interval_seconds || 60)===30?"selected":""}>30 seconds</option><option value="60" ${Number(row.interval_seconds || 60)===60?"selected":""}>1 minute</option><option value="300" ${Number(row.interval_seconds || 60)===300?"selected":""}>5 minutes</option><option value="900" ${Number(row.interval_seconds || 60)===900?"selected":""}>15 minutes</option></select></label>
      <label><span>Failure threshold</span><select name="failure_threshold">${[1,2,3,5,10].map(value=>`<option value="${value}" ${Number(row.failure_threshold || 3)===value?"selected":""}>${value} consecutive failure(s)</option>`).join("")}</select></label>
      <label class="wide"><span>Notes</span><textarea name="notes" rows="2" maxlength="1000" placeholder="Optional operational context">${esc(row.notes || "")}</textarea></label>
      <label class="svc-check-option"><input type="checkbox" name="alert_on_failure" ${row.alert_on_failure === false ? "" : "checked"}> Create an alert after the failure threshold</label>
      <label class="svc-check-option"><input type="checkbox" name="enabled" ${row.enabled === false ? "" : "checked"}> Enable this definition</label>
      </div><div class="svc-form-error" data-svc-form-error hidden></div><footer class="svc-modal-foot"><button type="button" class="svc-btn secondary" data-svc-close-modal>Cancel</button><button type="submit" class="svc-btn primary">${row.id ? "Save changes" : "Save Service Check"}</button></footer></form></section></div>`;
  }

  async function refreshDefinitions() {
    state.definitionError = "";
    try {
      const result = await getJSON(API.definitions);
      state.definitions = listOf(result, ["items","records","definitions"]).filter(isObj);
      state.definitionError = "";
    } catch (error) {
      state.definitionError = error.status === 401 ? "Sign in to view saved service checks." : error.status === 403 ? "Your IAM role cannot view service-check definitions." : error.message;
    }
  }

  async function saveDefinition(form) {
    if (state.savingDefinition) return;
    state.savingDefinition = true;
    const errorBox = $("[data-svc-form-error]", form);
    const button = $("button[type=submit]", form);
    if (button) { button.disabled = true; button.textContent = "Saving..."; }
    if (errorBox) { errorBox.hidden = true; errorBox.textContent = ""; }
    const fd = new FormData(form);
    const payload = {
      device_id: fd.get("device_id"), service_name: fd.get("service_name"), platform: fd.get("platform"),
      check_type: fd.get("check_type"), service_identifier: fd.get("service_identifier"),
      dns_server: fd.get("dns_server") || "", dns_record_type: fd.get("dns_record_type") || "A",
      dns_expected_answer: fd.get("dns_expected_answer") || "", dns_timeout_seconds: Number(fd.get("dns_timeout_seconds") || 3),
      interval_seconds: Number(fd.get("interval_seconds")), failure_threshold: Number(fd.get("failure_threshold")),
      alert_on_failure: fd.has("alert_on_failure"), enabled: fd.has("enabled"), notes: fd.get("notes") || ""
    };
    const id = form.dataset.definitionId;
    try {
      await sendJSON(id ? `${API.definitionBase}/${encodeURIComponent(id)}` : API.definitionBase, id ? "PUT" : "POST", payload);
      state.modalOpen = false;
      state.editingDefinition = null;
      state.definitionNotice = id ? "Service-check definition updated. Live execution still requires a collector." : "Service-check definition saved. Live execution still requires a collector.";
      await refreshDefinitions();
      await refreshAudit();
      render();
    } catch (error) {
      if (errorBox) { errorBox.hidden = false; errorBox.textContent = error.status === 403 ? "Your IAM role cannot edit service-check definitions." : error.message; }
      if (button) { button.disabled = false; button.textContent = id ? "Save changes" : "Save Service Check"; }
    } finally { state.savingDefinition = false; }
  }

  async function toggleDefinition(id, enabled) {
    const row = state.definitions.find(item => String(item.id) === String(id));
    if (!row) return;
    try {
      await sendJSON(`${API.definitionBase}/${encodeURIComponent(id)}`, "PUT", {enabled});
      state.definitionNotice = enabled ? "Definition enabled; it will run when the collector is connected." : "Definition disabled.";
      await refreshDefinitions(); await refreshAudit(); render();
    } catch (error) { state.definitionError = error.message; render(); }
  }

  async function deleteDefinition(id) {
    if (!window.confirm("Delete this saved service-check definition?")) return;
    try {
      await sendJSON(`${API.definitionBase}/${encodeURIComponent(id)}`, "DELETE");
      state.definitionNotice = "Service-check definition deleted.";
      await refreshDefinitions(); await refreshAudit(); render();
    } catch (error) { state.definitionError = error.message; render(); }
  }


  async function refreshAudit() {
    try {
      const result = await getJSON(API.audit);
      state.auditLogs = listOf(result, ["items", "records", "results"]).filter(isObj);
      state.auditLoaded = true;
      state.auditError = "";
    } catch (error) {
      state.auditLoaded = true;
      state.auditError = error.message || "Service activity log could not be loaded.";
    }
  }

  function auditActionLabel(action) {
    return ({created:"Created", updated:"Updated", enabled:"Enabled", disabled:"Disabled", deleted:"Deleted"})[String(action || "").toLowerCase()] || String(action || "Unknown");
  }

  function auditValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Enabled" : "Disabled";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function auditDetailMarkup(item) {
    if (!item) return "";
    const details = isObj(item.details) ? item.details : {};
    const before = isObj(details.before) ? details.before : {};
    const after = isObj(details.after) ? details.after : {};
    const fields = [
      ["service_name", "Display name"], ["device_name", "Computer"], ["platform", "Platform"],
      ["check_type", "Check method"], ["service_identifier", "Service identifier / query"],
      ["dns_server", "DNS server"], ["dns_record_type", "DNS record type"],
      ["dns_expected_answer", "Expected DNS answer"], ["dns_timeout_seconds", "DNS timeout"],
      ["interval_seconds", "Check interval"], ["failure_threshold", "Failure threshold"],
      ["alert_on_failure", "Alert on failure"], ["enabled", "Enabled"], ["notes", "Notes"]
    ];
    const changes = fields.filter(([key]) => before[key] !== after[key] || (!details.before && after[key] !== undefined) || (!details.after && before[key] !== undefined));
    const changeRows = changes.map(([key, label]) => `<tr><td>${esc(label)}</td><td>${esc(auditValue(before[key]))}</td><td>${esc(auditValue(after[key]))}</td></tr>`).join("");
    const heading = `${auditActionLabel(item.action)} · ${details.service_name || item.resource_id || "Service check"}`;
    return `<section class="svc-audit-detail"><header class="svc-panel-head"><div><div class="svc-eyebrow">AUDIT EVENT DETAILS</div><h3>${esc(heading)}</h3><p>${esc(item.actor || "Unknown user")} · ${esc(timeText(item.occurred_at))}</p></div><button type="button" class="svc-btn secondary" data-svc-audit-close>Close details</button></header>
      <div class="svc-audit-detail-meta"><span><small>Computer</small><strong>${esc(details.device_name || "Unknown device")}</strong></span><span><small>Action</small><strong>${esc(auditActionLabel(item.action))}</strong></span><span><small>Record ID</small><strong>${esc(item.resource_id || "—")}</strong></span></div>
      <div class="svc-table-wrap"><table class="svc-table svc-audit-change-table"><thead><tr><th>Setting</th><th>Previous value</th><th>New value</th></tr></thead><tbody>${changeRows || `<tr><td colspan="3">No field-level difference was recorded.</td></tr>`}</tbody></table></div>
      <details class="svc-audit-raw"><summary>View complete audit payload</summary><pre>${esc(JSON.stringify(details, null, 2))}</pre></details></section>`;
  }

  function renderAuditLog() {
    const source = Array.isArray(state.auditLogs) ? state.auditLogs.slice() : [];
    const actors = [...new Set(source.map(item => String(item.actor || "").trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
    const devices = [...new Set(source.map(item => String((item.details || {}).device_name || "").trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
    const query = state.auditQuery.trim().toLowerCase();
    let rows = source.filter(item => {
      const details = isObj(item.details) ? item.details : {};
      const haystack = [item.actor, item.action, item.resource_id, details.service_name, details.device_name, details.service_identifier, details.dns_server, details.dns_expected_answer].join(" ").toLowerCase();
      const day = String(item.occurred_at || "").slice(0, 10);
      return (!query || haystack.includes(query))
        && (state.auditActor === "all" || String(item.actor || "") === state.auditActor)
        && (state.auditAction === "all" || String(item.action || "") === state.auditAction)
        && (state.auditDevice === "all" || String(details.device_name || "") === state.auditDevice)
        && (!state.auditFrom || day >= state.auditFrom)
        && (!state.auditTo || day <= state.auditTo);
    });
    rows.sort((a,b) => {
      const av = timestamp(a.occurred_at);
      const bv = timestamp(b.occurred_at);
      const delta = (av ? av.getTime() : 0) - (bv ? bv.getTime() : 0);
      return state.auditSort === "oldest" ? delta : -delta;
    });
    const pageSize = 10;
    const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
    state.auditPage = Math.min(Math.max(1, state.auditPage), pageCount);
    const start = (state.auditPage - 1) * pageSize;
    const pageRows = rows.slice(start, start + pageSize);
    const tableRows = pageRows.map(item => {
      const details = isObj(item.details) ? item.details : {};
      const action = String(item.action || "").toLowerCase();
      const kind = action === "created" || action === "enabled" ? "success" : action === "deleted" ? "danger" : action === "disabled" ? "warning" : "info";
      return `<tr><td><time>${esc(timeText(item.occurred_at))}</time></td><td><strong>${esc(item.actor || "Unknown")}</strong></td><td><span class="svc-audit-action ${kind}">${esc(auditActionLabel(action))}</span></td><td><strong>${esc(details.service_name || item.resource_id || "Service check")}</strong><small class="svc-sub">${esc(details.service_identifier || "")}</small></td><td>${esc(details.device_name || "—")}</td><td><button type="button" class="svc-link-button" data-svc-audit-detail="${esc(item.id)}">View details</button></td></tr>`;
    }).join("");
    const selected = source.find(item => String(item.id) === String(state.auditSelected));
    const empty = state.auditError
      ? `<div class="svc-banner error"><strong>Audit log unavailable.</strong><span>${esc(state.auditError)}</span><button type="button" class="svc-btn secondary" data-svc-audit-refresh>Retry</button></div>`
      : !state.auditLoaded
        ? `<div class="svc-empty compact">Loading service activity...</div>`
        : `<div class="svc-empty compact"><strong>No matching service activity</strong><span>Configuration actions performed after audit logging was enabled will appear here.</span></div>`;
    return `<section class="svc-panel svc-audit-panel"><header class="svc-panel-head"><div><div class="svc-eyebrow">SERVICE MONITORING / AUDIT TRAIL</div><h2>Service Activity Log</h2><p>Who changed a service-check definition, what changed and when. Entries are retained independently of the current configuration.</p></div><div class="svc-audit-head-actions"><span class="svc-count">${rows.length} matching events</span><button type="button" class="svc-btn secondary" data-svc-audit-refresh>Refresh log</button></div></header>
      <div class="svc-audit-filters"><label class="svc-search"><span>Search</span><input type="search" data-svc-audit-search value="${esc(state.auditQuery)}" placeholder="User, service, device or record ID"></label>
      <label><span>User</span><select data-svc-audit-actor><option value="all">All users</option>${actors.map(value=>`<option value="${esc(value)}" ${state.auditActor===value?"selected":""}>${esc(value)}</option>`).join("")}</select></label>
      <label><span>Action</span><select data-svc-audit-action><option value="all">All actions</option><option value="created" ${state.auditAction==="created"?"selected":""}>Created</option><option value="updated" ${state.auditAction==="updated"?"selected":""}>Updated</option><option value="enabled" ${state.auditAction==="enabled"?"selected":""}>Enabled</option><option value="disabled" ${state.auditAction==="disabled"?"selected":""}>Disabled</option><option value="deleted" ${state.auditAction==="deleted"?"selected":""}>Deleted</option></select></label>
      <label><span>Computer</span><select data-svc-audit-device><option value="all">All devices</option>${devices.map(value=>`<option value="${esc(value)}" ${state.auditDevice===value?"selected":""}>${esc(value)}</option>`).join("")}</select></label>
      <label><span>From</span><input type="date" data-svc-audit-from value="${esc(state.auditFrom)}"></label><label><span>To</span><input type="date" data-svc-audit-to value="${esc(state.auditTo)}"></label>
      <label><span>Sort by</span><select data-svc-audit-sort><option value="newest" ${state.auditSort==="newest"?"selected":""}>Newest first</option><option value="oldest" ${state.auditSort==="oldest"?"selected":""}>Oldest first</option></select></label>
      </div>
      ${rows.length ? `<div class="svc-table-wrap"><table class="svc-table svc-audit-table"><thead><tr><th>Date &amp; time</th><th>User</th><th>Action</th><th>Service check</th><th>Computer</th><th>Details</th></tr></thead><tbody>${tableRows}</tbody></table></div><div class="svc-audit-pagination"><span>Showing ${start+1}–${Math.min(start+pageSize,rows.length)} of ${rows.length}</span><div><button type="button" class="svc-btn secondary" data-svc-audit-page="prev" ${state.auditPage<=1?"disabled":""}>Previous</button><span>Page ${state.auditPage} / ${pageCount}</span><button type="button" class="svc-btn secondary" data-svc-audit-page="next" ${state.auditPage>=pageCount?"disabled":""}>Next</button></div></div>` : empty}
      ${selected ? auditDetailMarkup(selected) : ""}
      <div class="svc-config-note">Source: authenticated Service Check configuration events in the shared IAM audit database. Historical actions from before this audit feature was installed are not reconstructed.</div></section>`;
  }

  function renderPreservingAuditFocus(input) {
    const position = input.selectionStart;
    render();
    const replacement = $("[data-svc-audit-search]");
    if (replacement) {
      replacement.focus();
      try { replacement.setSelectionRange(position, position); } catch (_) {}
    }
  }

  function render() {
    if (!state.host) return;
    const groups = groupedServices();
    if (!state.selected && groups.length) state.selected = groups[0].key;
    const filtered = filteredGroups(groups);
    const healthy = groups.filter(group => group.kind === "healthy").length;
    const warning = groups.filter(group => group.kind === "warning").length;
    const problem = groups.filter(group => group.kind === "problem").length;
    const unknown = groups.filter(group => group.kind === "unknown").length;
    const known = groups.filter(group => group.kind !== "unknown").length;
    const latest = groups.map(group => timestamp(group.checkedAt)).filter(Boolean).sort((a, b) => b - a)[0] || null;
    const osValues = [...new Set(groups.map(group => group.device.os).filter(os => os && os !== "Unknown OS"))].sort();
    const deviceValues = [...new Set(groups.map(group => ({id:group.device.id || group.device.name, name:group.device.name})).filter(device => device.id))].sort((a, b) => a.name.localeCompare(b.name));

    state.host.innerHTML = `<div class="svc-app">
      <header class="svc-header"><div><div class="svc-eyebrow">MONITORING / OBSERVABILITY</div><h1>Service Monitoring</h1><p>Service state, recorded checks, related events and alerts across managed devices.</p></div><div class="svc-header-actions"><span class="svc-data-state"><i></i> RECORDED SERVICE DATA</span><button class="svc-btn primary" data-svc-refresh ${state.loading ? "disabled" : ""}>${state.loading ? "Refreshing..." : "Refresh data"}</button></div></header>
      ${state.error ? `<div class="svc-banner error"><strong>Could not refresh service data.</strong><span>${esc(state.error)}</span><button class="svc-btn secondary" data-svc-refresh>Retry</button></div>` : `<div class="svc-banner"><span class="svc-live-dot"></span><span>Values come from existing Cartman service-check records. This page does not invent service states or run Start/Stop/Restart commands.</span><small>${state.updatedAt ? `Updated ${esc(state.updatedAt.toLocaleTimeString())}` : "Waiting for API response"}</small></div>`}
      ${renderConfiguredChecks()}
      <div class="svc-kpis">${kpi("Monitored services", state.servicesLoaded ? compact(groups.length) : "--", "Unique device + service records", "S", "blue")}${kpi("Healthy", state.servicesLoaded ? compact(healthy) : "--", "Latest recorded state", "OK", "green")}${kpi("Warning / stopped", state.servicesLoaded ? compact(warning + problem) : "--", "Needs review", "!", "red")}${kpi("Unknown state", state.servicesLoaded ? compact(unknown) : "--", "No recognized status", "?", "purple")}</div>
      <div class="svc-top-grid"><section class="svc-panel"><header class="svc-panel-head"><div><h2>Service health distribution</h2><p>Based on each service's latest recorded check.</p></div><span class="svc-panel-meta">${compact(known)} known / ${compact(groups.length)} total</span></header>${state.servicesLoaded ? stateBar(groups) : `<div class="svc-empty compact">Loading service records...</div>`}<div class="svc-muted-note">Latest check sample: <strong>${latest ? esc(timeText(latest)) : "No recorded check time"}</strong></div></section><section class="svc-panel"><header class="svc-panel-head"><div><h2>Recent service events</h2><p>Only event records returned by the Events API.</p></div><a class="svc-text-link" href="/pages/monitoring/">Monitoring &rarr;</a></header>${recentEvents()}</section></div>
      <section class="svc-panel"><header class="svc-panel-head"><div><h2>Service inventory</h2><p>Search and filter saved service-check records. Select a row to inspect recorded history.</p></div><span class="svc-count">${filtered.length} services</span></header>
      <div class="svc-filters"><label class="svc-search"><span>Search</span><input type="search" data-svc-search value="${esc(state.query)}" placeholder="Service, device, OS or status"></label><label><span>Status</span><select data-svc-status><option value="all">All states</option><option value="healthy" ${state.status === "healthy" ? "selected" : ""}>Healthy</option><option value="warning" ${state.status === "warning" ? "selected" : ""}>Warning</option><option value="problem" ${state.status === "problem" ? "selected" : ""}>Stopped / failed</option><option value="unknown" ${state.status === "unknown" ? "selected" : ""}>Unknown</option></select></label><label><span>Operating system</span><select data-svc-os><option value="all">All OS</option>${osValues.map(os => `<option value="${esc(os)}" ${state.os === os ? "selected" : ""}>${esc(os)}</option>`).join("")}</select></label><label><span>Device</span><select data-svc-device><option value="all">All devices</option>${deviceValues.map(device => `<option value="${esc(device.id)}" ${state.device === device.id ? "selected" : ""}>${esc(device.name)}</option>`).join("")}</select></label><label><span>Sort by</span><select data-svc-sort><option value="latest" ${state.sort === "latest" ? "selected" : ""}>Latest check</option><option value="name" ${state.sort === "name" ? "selected" : ""}>Service name</option><option value="status" ${state.sort === "status" ? "selected" : ""}>Status</option><option value="device" ${state.sort === "device" ? "selected" : ""}>Device name</option></select></label></div>
      ${renderTable(filtered)}</section>
      ${renderDetail(filtered)}
      ${renderAuditLog()}
      <footer class="svc-footer"><span>Source: Cartman Service Checks, Devices, Events and Alerts APIs</span><span>${state.updatedAt ? `Last successful service refresh: ${esc(state.updatedAt.toLocaleString())}` : "No successful service API refresh yet"} | Auto-refresh every 30 seconds</span></footer>
      ${renderCheckModal()}
    </div>`;
  }

  function renderPreservingFocus(input) {
    const position = input.selectionStart;
    render();
    const replacement = $('[data-svc-search]');
    if (replacement) {
      replacement.focus();
      try { replacement.setSelectionRange(position, position); } catch (_) {}
    }
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    state.error = "";
    if (!state.modalOpen) render();
    const requests = await Promise.allSettled([
      getJSON(API.services), getJSON(API.devices), getJSON(API.events), getJSON(API.alerts), getJSON(API.definitions), getJSON("/api/auth/me"), getJSON(API.audit)
    ]);
    try {
      const serviceResult = requests[0];
      if (serviceResult.status !== "fulfilled") throw serviceResult.reason;
      state.services = listOf(serviceResult.value, ["items", "results", "records", "checks", "services"]).filter(isObj);
      state.servicesLoaded = true;
      if (requests[1].status === "fulfilled") state.devices = listOf(requests[1].value, ["items", "results", "records", "devices"]).filter(isObj);
      if (requests[2].status === "fulfilled") state.events = listOf(requests[2].value, ["items", "results", "records", "events"]).filter(isObj);
      if (requests[3].status === "fulfilled") state.alerts = listOf(requests[3].value, ["items", "results", "records", "alerts"]).filter(isObj);
      if (requests[4].status === "fulfilled") { state.definitions = listOf(requests[4].value, ["items", "results", "records"]).filter(isObj); state.definitionError = ""; }
      else { state.definitionError = requests[4].reason && requests[4].reason.message ? requests[4].reason.message : "Service-check configuration could not be loaded."; }
      if (requests[5].status === "fulfilled") { const auth = requests[5].value || {}; state.currentUser = auth.user || auth.current_user || auth; const role = String((state.currentUser && (state.currentUser.role || state.currentUser.role_name)) || "").toLowerCase().replace(/[ -]/g, "_"); state.canManageChecks = ["admin","administrator","network_admin","it_admin","it_administrator"].includes(role); }
      if (requests[6].status === "fulfilled") { const auditResult = requests[6].value || {}; state.auditLogs = listOf(auditResult, ["items","records","results"]).filter(isObj); state.auditLoaded = true; state.auditError = ""; }
      else { state.auditLoaded = true; state.auditError = requests[6].reason && requests[6].reason.message ? requests[6].reason.message : "Service activity log could not be loaded."; }
      state.updatedAt = new Date();
      state.error = "";
    } catch (error) {
      state.error = error.status === 401
        ? "Authentication required. Sign in to Cartman and retry."
        : error.status === 403
          ? "Your Cartman role does not have permission to view service-check records."
          : `Service API error: ${error.message}`;
    } finally {
      state.loading = false;
      if (!state.modalOpen) render();
    }
  }

  function mount() {
    if (!location.pathname.replace(/\/+$/, "").toLowerCase().endsWith("/service-monitoring")) return;
    const host = $('[data-monitor-dashboard="service-monitoring"]');
    if (!host || host.dataset.serviceLive === "1") return;
    host.dataset.serviceLive = "1";
    state.host = host;
    state.module = host.closest(".workspace-module");
    state.module?.classList.add("svc-live-mode");
    state.module?.querySelector(".workspace-eyebrow")?.remove();
    state.module?.querySelector(".workspace-toolbar")?.remove();
    state.module?.querySelector(".workspace-stats")?.remove();
    state.module?.querySelector(".workspace-table-panel")?.remove();
    render();
    void refresh();
    state.timer = window.setInterval(() => { void refresh(); }, REFRESH_MS);

    document.addEventListener("input", event => {
      if (event.target.matches("[data-svc-search]")) {
        state.query = event.target.value;
        state.page = 1;
        renderPreservingFocus(event.target);
      }
      else if (event.target.matches("[data-svc-audit-search]")) {
        state.auditQuery = event.target.value;
        state.auditPage = 1;
        renderPreservingAuditFocus(event.target);
      }
    });
    document.addEventListener("change", event => {
      const target = event.target;
      if (target.matches("[data-svc-audit-actor]")) { state.auditActor = target.value; state.auditPage = 1; render(); return; }
      if (target.matches("[data-svc-audit-action]")) { state.auditAction = target.value; state.auditPage = 1; render(); return; }
      if (target.matches("[data-svc-audit-device]")) { state.auditDevice = target.value; state.auditPage = 1; render(); return; }
      if (target.matches("[data-svc-audit-from]")) { state.auditFrom = target.value; state.auditPage = 1; render(); return; }
      if (target.matches("[data-svc-audit-to]")) { state.auditTo = target.value; state.auditPage = 1; render(); return; }
      if (target.matches("[data-svc-audit-sort]")) { state.auditSort = target.value; state.auditPage = 1; render(); return; }
      if (target.matches('select[name="check_type"]')) { updateCheckMethodFields(target.closest("[data-svc-config-form]")); return; }
      if (target.matches('select[name="device_id"]')) { updateCheckMethodFields(target.closest("[data-svc-config-form]")); return; }
      if (target.matches("[data-svc-status]")) { state.status = target.value; state.page = 1; render(); }
      else if (target.matches("[data-svc-os]")) { state.os = target.value; state.page = 1; render(); }
      else if (target.matches("[data-svc-device]")) { state.device = target.value; state.page = 1; render(); }
      else if (target.matches("[data-svc-sort]")) { state.sort = target.value; state.page = 1; render(); }
    });
    document.addEventListener("click", async event => {
      if (event.target.closest("[data-svc-audit-refresh]")) { await refreshAudit(); render(); return; }
      const auditDetailButton = event.target.closest("[data-svc-audit-detail]");
      if (auditDetailButton) { state.auditSelected = auditDetailButton.dataset.svcAuditDetail; render(); return; }
      if (event.target.closest("[data-svc-audit-close]")) { state.auditSelected = ""; render(); return; }
      const auditPageButton = event.target.closest("[data-svc-audit-page]");
      if (auditPageButton) { state.auditPage = Math.max(1, state.auditPage + (auditPageButton.dataset.svcAuditPage === "next" ? 1 : -1)); render(); return; }
      if (event.target.closest("[data-svc-refresh]")) { void refresh(); return; }
      if (event.target.closest("[data-svc-config-refresh]")) { await refreshDefinitions(); render(); return; }
      if (event.target.closest("[data-svc-new-check]")) { state.editingDefinition = null; state.modalOpen = true; render(); return; }
      if (event.target.closest("[data-svc-close-modal]")) { state.modalOpen = false; state.editingDefinition = null; render(); return; }
      const editConfig = event.target.closest("[data-svc-config-edit]");
      if (editConfig) { const row = state.definitions.find(item => String(item.id) === editConfig.dataset.svcConfigEdit); if (row) { state.editingDefinition = row; state.modalOpen = true; render(); } return; }
      const toggleConfig = event.target.closest("[data-svc-config-toggle]");
      if (toggleConfig) { await toggleDefinition(toggleConfig.dataset.svcConfigToggle, toggleConfig.dataset.enabled !== "1"); return; }
      const deleteConfig = event.target.closest("[data-svc-config-delete]");
      if (deleteConfig) { await deleteDefinition(deleteConfig.dataset.svcConfigDelete); return; }
      const page = event.target.closest("[data-svc-page]");
      if (page) {
        state.page = Math.max(1, state.page + (page.dataset.svcPage === "next" ? 1 : -1));
        render();
        return;
      }
      const row = event.target.closest("[data-svc-select]");
      const detailButton = event.target.closest("[data-svc-open]");
      if (detailButton) { state.selected = detailButton.dataset.svcOpen; render(); return; }
      if (row) { state.selected = row.dataset.svcSelect; render(); }
    });
    document.addEventListener("submit", event => {
      const form = event.target.closest("[data-svc-config-form]");
      if (!form) return;
      event.preventDefault();
      void saveDefinition(form);
    });
    document.addEventListener("click", event => {
      if (event.target.matches("[data-svc-modal-backdrop]")) { state.modalOpen = false; state.editingDefinition = null; render(); }
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && state.modalOpen) { state.modalOpen = false; state.editingDefinition = null; render(); return; }
      const row = event.target.closest && event.target.closest("[data-svc-select]");
      if (row && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault(); state.selected = row.dataset.svcSelect; render();
      }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, { once: true });
  else mount();
})();
