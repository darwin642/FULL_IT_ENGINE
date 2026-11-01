/* CARTMAN_GLOBAL_NOTIFICATION_EVENTS_V1 */
// CARTMAN_WORKFLOW_NOTIFICATION_POLLING_V1
(() => {
  "use strict";

  if (window.__cartmanGlobalNotificationEventsV1) return;
  window.__cartmanGlobalNotificationEventsV1 = true;

  const POLL_INTERVAL_MS = 20000;
  const HEARTBEAT_INTERVAL_MS = 5000;
  const LEASE_TTL_MS = 18000;
  const FRESH_EVENT_MS = 10 * 60 * 1000;
  const LEASE_KEY = "cartman-live-notification-poller-lease-v1";
  const STATE_PREFIX = "cartman-live-notification-state-v1:";
  let notificationPreferencesReady = false;
  let notificationPreferences = { critical: true, warning: true, info: true, success: true };
  const pendingNotificationEvents = new Map();
  const notificationPreferencesRequest = fetch("/api/auth/notification-preferences", {
    credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }
  }).then(response => {
    if (!response.ok) throw new Error("Notification preferences unavailable");
    return response.json();
  }).then(data => {
    const value = data.preferences || data;
    notificationPreferences = {
      critical: value.critical !== false,
      warning: value.warning !== false,
      info: value.info !== false,
      success: value.success !== false
    };
    window.CartmanNotificationPreferences = { ...notificationPreferences };
  }).catch(() => {
    notificationPreferences = { critical: true, warning: true, info: true, success: true };
  }).finally(() => {
    notificationPreferencesReady = true;
    pendingNotificationEvents.forEach((payload, dedupeKey) => emitOnce(dedupeKey, payload));
    pendingNotificationEvents.clear();
  });

  function cartmanNotificationPreferenceAllows(payload) {
    if (!notificationPreferencesReady && !window.CartmanNotificationPreferences) return false;
    const value = window.CartmanNotificationPreferences || notificationPreferences;
    const severity = String(payload?.severity || payload?.level || payload?.priority || payload?.type || "info").toLowerCase();
    const category = /critical|fatal|emergency|error|failure|failed|high/.test(severity)
      ? "critical"
      : /warning|warn|medium|degraded/.test(severity)
        ? "warning"
        : /success|completed|resolved|done/.test(severity)
          ? "success" : "info";
    return value[category] !== false;
  }

  const OWNER_ID = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const IMPORTANT_AUDIT = /role|permission|policy|credential|secret|identity.provider|access.denied|login.failed|auth.failed|member.*replaced|user.deleted|user.deactivated|account.disabled|mfa|security|group.deleted|user.disabled/i;
  const OUTAGE_TEXT = /\b(outage|offline|unreachable|service down|service unavailable|not responding|connection lost|host down|endpoint down|device down|failed health check)\b/i;
  const BAD_STATUS = /^(down|offline|critical|failed|failure|unavailable|timeout|unhealthy|stopped|error|unreachable|not running|degraded)$/i;

  let currentUser = null;
  let state = null;
  let stateKey = "";
  let inFlight = false;
  let lastPollAt = 0;
  let intervalHandle = null;

  function parseJson(value, fallback = null) {
    try { return JSON.parse(value); } catch (_) { return fallback; }
  }

  function readStorage(key, fallback = null) {
    try { return parseJson(localStorage.getItem(key), fallback); } catch (_) { return fallback; }
  }

  function writeStorage(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; }
  }

  function claimLease() {
    try {
      const now = Date.now();
      const existing = parseJson(localStorage.getItem(LEASE_KEY), null);
      if (existing && existing.expiresAt > now && existing.owner !== OWNER_ID) return false;
      localStorage.setItem(LEASE_KEY, JSON.stringify({ owner: OWNER_ID, expiresAt: now + LEASE_TTL_MS }));
      const verified = parseJson(localStorage.getItem(LEASE_KEY), null);
      return !!verified && verified.owner === OWNER_ID;
    } catch (_) {
      // Without shared browser storage, don't poll from every tab and spam duplicate toasts.
      return false;
    }
  }

  function releaseLease() {
    try {
      const current = parseJson(localStorage.getItem(LEASE_KEY), null);
      if (current && current.owner === OWNER_ID) localStorage.removeItem(LEASE_KEY);
    } catch (_) {}
  }

  function parseTimestamp(value) {
    if (value == null || value === "") return NaN;
    let valueString = String(value).trim();
    // SQLite CURRENT_TIMESTAMP values are UTC without an explicit timezone.
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(valueString)) {
      valueString = valueString.replace(" ", "T") + "Z";
    }
    return Date.parse(valueString);
  }

  function isFresh(value) {
    const timestamp = parseTimestamp(value);
    if (!Number.isFinite(timestamp)) return true;
    const age = Date.now() - timestamp;
    return age >= -60000 && age <= FRESH_EVENT_MS;
  }

  function text(value, max = 500) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, max);
  }

  function normalized(value) {
    return text(value, 300).toLocaleLowerCase().replace(/\s+/g, " ");
  }

  async function getJson(url) {
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      if (!response.ok || response.redirected) return null;
      if (!(response.headers.get("content-type") || "").toLowerCase().includes("application/json")) return null;
      return await response.json();
    } catch (_) {
      return null;
    }
  }

  async function getList(url) {
    const data = await getJson(url);
    if (data == null) return null;
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data.items)) return data.items;
    return null;
  }

  function createState() {
    return {
      version: 1,
      sources: {
        alerts: null,
        events: null,
        services: null,
        availability: null,
        tasks: null,
        audit: null,
        workflowNotifications: null
      },
      recentToasts: []
    };
  }

  function loadState(username) {
    const key = STATE_PREFIX + encodeURIComponent(normalized(username));
    const existing = readStorage(key, null);
    if (existing && existing.version === 1 && existing.sources) {
      stateKey = key;
      return existing;
    }
    stateKey = key;
    return createState();
  }

  function saveState() {
    if (stateKey && state) writeStorage(stateKey, state);
  }

  function emitOnce(dedupeKey, payload) {
    if (!notificationPreferencesReady && !window.CartmanNotificationPreferences) { pendingNotificationEvents.set(String(dedupeKey), payload || {}); return; }
    if (!cartmanNotificationPreferenceAllows(payload || {})) return;
    if (!state) return false;
    const now = Date.now();
    const key = normalized(dedupeKey || payload.id || `${payload.source}:${payload.title}:${payload.message}`);
    state.recentToasts = (Array.isArray(state.recentToasts) ? state.recentToasts : [])
      .filter(entry => entry && Number(entry.at) > now - 10 * 60 * 1000)
      .slice(-100);
    if (state.recentToasts.some(entry => entry.key === key && now - Number(entry.at) < 3 * 60 * 1000)) return false;
    state.recentToasts.push({ key, at: now });
    state.recentToasts = state.recentToasts.slice(-100);
    const api = window.CartmanToast;
    if (!api || typeof api.notify !== "function") return false;
    api.notify(payload);
    return true;
  }

  function listSnapshot(oldSnapshot, rows, keyFn, onNew) {
    const oldIds = new Set(oldSnapshot && Array.isArray(oldSnapshot.ids) ? oldSnapshot.ids.map(String) : []);
    const firstForSource = !oldSnapshot || !Array.isArray(oldSnapshot.ids);
    for (const row of rows) {
      const id = keyFn(row);
      if (!id || firstForSource || oldIds.has(String(id))) continue;
      onNew(row);
    }
    const currentIds = rows.map(keyFn).filter(v => v != null && v !== "").map(String);
    const currentSet = new Set(currentIds);
    const combined = [...currentIds, ...(oldSnapshot && Array.isArray(oldSnapshot.ids) ? oldSnapshot.ids.map(String).filter(id => !currentSet.has(id)) : [])];
    return { ids: [...new Set(combined)].slice(0, 800) };
  }

  function monitoringSeverity(row) {
    const severity = normalized(row.severity || row.level || "");
    const details = typeof row.details === "string" ? row.details : JSON.stringify(row.details || row.details_json || "");
    const allText = `${row.title || ""} ${row.event_type || ""} ${row.message || ""} ${details || ""}`;
    if (/(critical|fatal|emergency)/i.test(severity)) return "critical";
    if (/(^|\b)(error|failure|failed|high)(\b|$)/i.test(severity)) return "error";
    if (OUTAGE_TEXT.test(allText)) return "warning";
    return "";
  }

  function processAlerts(rows) {
    state.sources.alerts = listSnapshot(state.sources.alerts, rows, row => row.id ?? row.alert_id, row => {
      const severity = monitoringSeverity(row);
      const status = normalized(row.status);
      if (!severity || /^(resolved|closed|cleared|acknowledged)$/.test(status)) return;
      if (!isFresh(row.created_at)) return;
      const device = text(row.device_name || row.hostname || row.device_id || "Infrastructure device", 120);
      const title = text(row.title || "Monitoring alert", 180);
      emitOnce(`monitor:${row.device_id || device}:${normalized(title)}`, {
        id: `monitor-alert-${row.id ?? row.alert_id}`,
        title: severity === "critical" ? "Critical monitoring alert" : severity === "error" ? "Monitoring error" : "Service availability warning",
        message: `${title} · ${device}`,
        severity,
        source: "Monitoring",
        actionLabel: "View alerts",
        actionUrl: "/pages/alerts/"
      });
    });
  }

  function processEvents(rows) {
    state.sources.events = listSnapshot(state.sources.events, rows, row => row.id ?? row.event_id, row => {
      const severity = monitoringSeverity(row);
      if (!severity || !isFresh(row.occurred_at)) return;
      const message = text(row.message || row.event_type || "Monitoring event", 180);
      const device = text(row.device_name || row.hostname || row.device_id || "Infrastructure device", 120);
      emitOnce(`monitor:${row.device_id || device}:${normalized(message)}`, {
        id: `monitor-event-${row.id ?? row.event_id}`,
        title: severity === "critical" ? "Critical monitoring event" : severity === "error" ? "Monitoring event requires attention" : "Service outage detected",
        message: `${message} · ${device}`,
        severity,
        source: "Monitoring",
        actionLabel: "View monitoring",
        actionUrl: "/pages/monitoring/"
      });
    });
  }

  function latestStatuses(rows, keyFields, timeField) {
    const latest = Object.create(null);
    for (const row of rows) {
      const key = keyFields.map(field => text(row[field], 160)).join("::");
      if (!key.replace(/:/g, "")) continue;
      const incomingTime = parseTimestamp(row[timeField]);
      const currentTime = latest[key] ? parseTimestamp(latest[key][timeField]) : NaN;
      if (!latest[key] || (Number.isFinite(incomingTime) && (!Number.isFinite(currentTime) || incomingTime > currentTime))) latest[key] = row;
    }
    return latest;
  }

  function processStatusTransitions(sourceName, rows, oldSnapshot, keyFields, statusField, timeField, labelFn) {
    const latest = latestStatuses(rows, keyFields, timeField);
    const previous = oldSnapshot && oldSnapshot.statuses && typeof oldSnapshot.statuses === "object" ? oldSnapshot.statuses : null;
    const current = Object.create(null);
    for (const [key, row] of Object.entries(latest)) {
      const status = text(row[statusField], 80);
      current[key] = { status, at: text(row[timeField], 100), label: text(labelFn(row), 180) };
      if (!previous || !Object.prototype.hasOwnProperty.call(previous, key)) continue;
      const before = text(previous[key] && previous[key].status, 80);
      if (!status || !BAD_STATUS.test(status) || BAD_STATUS.test(before) || !isFresh(row[timeField])) continue;
      const label = current[key].label || "Infrastructure endpoint";
      emitOnce(`outage:${sourceName}:${key}:${normalized(status)}`, {
        id: `outage-${sourceName}-${key}-${normalized(status)}`,
        title: sourceName === "service" ? "Service outage detected" : "Endpoint unavailable",
        message: `${label} is ${status}.`,
        severity: /critical|failed|error|unavailable/i.test(status) ? "critical" : "warning",
        source: "Monitoring",
        actionLabel: "View monitoring",
        actionUrl: "/pages/monitoring/"
      });
    }
    return { statuses: Object.fromEntries(Object.entries(current).slice(0, 600)) };
  }

  function currentUserAliases(user) {
    return new Set([user && user.username, user && user.display_name, user && user.name]
      .map(normalized).filter(Boolean));
  }

  function assignedToCurrentUser(item, user, role) {
    // The support-agent endpoint is already filtered server-side to concrete assignments.
    if (role === "support_agent") return true;
    const aliases = currentUserAliases(user);
    const values = [item.owner, item.target_name, item.assigned_to, item.assigned_to_username, item.assigned_username, item.assignee, item.assignee_username]
      .map(normalized).filter(Boolean);
    return values.some(value => aliases.has(value));
  }

  function processTasks(rows, user, role) {
    const oldSnapshot = state.sources.tasks;
    const oldItems = oldSnapshot && oldSnapshot.items && typeof oldSnapshot.items === "object" ? oldSnapshot.items : null;
    const firstForSource = !oldItems;
    const currentItems = Object.create(null);
    const seenNow = new Set();

    for (const item of rows) {
      const id = text(item.task_key || item.id, 120);
      if (!id) continue;
      seenNow.add(id);
      const status = text(item.status, 80);
      const assigned = assignedToCurrentUser(item, user, role);
      const previous = oldItems ? oldItems[id] : null;
      const presentBefore = !!(previous && previous.present !== false);
      const title = text(item.title || id, 180);
      const displayId = text(item.display_key || item.task_key || item.id, 80);

      if (!firstForSource && assigned && status !== "Done" && (!presentBefore || !previous.assignedToMe) && isFresh(item.updated_at || item.created_at)) {
        emitOnce(`task-assigned:${id}:${normalized(user.username)}`, {
          id: `task-assigned-${id}-${normalized(user.username)}`,
          title: "New task assigned to you",
          message: `${displayId} · ${title}`,
          severity: "info",
          source: "Tasks & Automation",
          actionLabel: "Open task",
          actionUrl: "/pages/tasks/"
        });
      }

      if (!firstForSource && previous && presentBefore && normalized(previous.status) !== "done" && normalized(status) === "done" && isFresh(item.completed_at || item.updated_at)) {
        // CARTMAN_TASK_COMPLETION_CONTEXT_V1
        const assignedTo = text(item.target_name || item.owner || item.assigned_to || item.assigned_to_username || "", 120);
        const completedByRaw = text(item.completed_by_display_name || item.completed_by_username || item.completed_by || "", 120);
        const completedBy = normalized(completedByRaw) === normalized(user.username)
          ? text(user.display_name || user.username, 120)
          : completedByRaw;
        const completionContext = [
          assignedTo && !/^unassigned$/i.test(assignedTo) ? `Assigned to: ${assignedTo}` : "",
          completedBy ? `Completed by: ${completedBy}` : ""
        ].filter(Boolean).join(" · ");
        emitOnce(`task-completed:${id}:${text(item.completed_at || item.updated_at, 100)}`, {
          id: `task-completed-${id}-${text(item.completed_at || item.updated_at, 100)}`,
          title: "Task completed",
          message: `${displayId} · ${title}${completionContext ? ` · ${completionContext}` : ""}`,
          severity: "success",
          source: "Tasks & Automation",
          actionLabel: "View tasks",
          actionUrl: "/pages/tasks/"
        });
      }

      currentItems[id] = {
        status,
        assignedToMe: assigned,
        present: true,
        title,
        updatedAt: text(item.updated_at || item.created_at, 100)
      };
    }

    if (oldItems) {
      for (const [id, previous] of Object.entries(oldItems)) {
        if (!seenNow.has(id)) currentItems[id] = { ...previous, present: false };
      }
    }
    state.sources.tasks = { items: Object.fromEntries(Object.entries(currentItems).slice(-800)) };
  }

  function isImportantAudit(row) {
    const action = text(row.action, 240);
    const details = row.details && typeof row.details === "object" ? JSON.stringify(row.details) : text(row.details_json, 1000);
    if (IMPORTANT_AUDIT.test(action)) return true;
    return /(user|group|membership).*(updated|changed|replaced|deleted|disabled|deactivated)/i.test(action)
      && /(role|permission|policy|status|active|member|access|credential|security)/i.test(details || "");
  }

  function processAudit(rows) {
    state.sources.audit = listSnapshot(state.sources.audit, rows, row => row.id ?? row.event_id, row => {
      if (!isImportantAudit(row) || !isFresh(row.occurred_at)) return;
      const action = text(row.action || "Identity change", 180);
      const actor = text(row.actor || "Unknown actor", 100);
      const resource = text([row.resource_type, row.resource_id].filter(Boolean).join(" · "), 140);
      emitOnce(`iam-audit:${row.id ?? row.event_id}`, {
        id: `iam-audit-${row.id ?? row.event_id}`,
        title: "Identity & Security change",
        message: `${actor}: ${action}${resource ? ` · ${resource}` : ""}`,
        severity: "warning",
        source: "Identity & Security",
        actionLabel: "View audit log",
        actionUrl: "/pages/audit/"
      });
    });
  }

  function processWorkflowNotifications(rows, user) {
    state.sources.workflowNotifications = listSnapshot(state.sources.workflowNotifications, rows, row => row.id, row => {
      if (!isFresh(row.created_at)) return;
      const recipient = normalized(row.recipient_username);
      if (recipient && recipient !== normalized(user.username)) return;
      emitOnce(`workflow-notification:${row.id}`, {
        id: `workflow-notification:${row.id}`,
        title: text(row.title || "Workflow notification", 180),
        message: text(row.message || "", 1200),
        severity: text(row.severity || "info", 20),
        source: text(row.source || "Workflows", 100),
        actionLabel: "View notifications",
        actionUrl: text(row.action_url || "/pages/notifications/", 300)
      });
    });
  }

  async function pollOnce() {
    if (inFlight) return;
    inFlight = true;
    try {
      const auth = await getJson("/api/auth/me");
      const user = auth && auth.user;
      if (!user || !user.username) return;
      const role = normalized(user.role);
      if (!currentUser || normalized(currentUser.username) !== normalized(user.username)) {
        currentUser = user;
        state = loadState(user.username);
      } else {
        currentUser = user;
      }

      const requests = {};
      if (["admin", "network_admin", "support_agent", "read_only"].includes(role)) requests.workflowNotifications = getList("/api/workflow-notifications?limit=100");
      if (["admin", "network_admin"].includes(role)) {
        requests.alerts = getList("/api/monitoring/alerts?limit=100");
        requests.events = getList("/api/monitoring/events?limit=100");
        requests.services = getList("/api/monitoring/services?limit=200");
        requests.availability = getList("/api/monitoring/availability?limit=200");
      }
      if (["admin", "support_agent"].includes(role)) requests.tasks = getList("/api/work-items?limit=500");
      if (role === "admin") requests.audit = getList("/api/iam/audit?limit=200");

      const results = await Promise.all(Object.entries(requests).map(async ([key, promise]) => [key, await promise]));
      for (const [key, rows] of results) {
        if (!Array.isArray(rows)) continue;
        if (key === "workflowNotifications") processWorkflowNotifications(rows, user);
        else if (key === "alerts") processAlerts(rows);
        else if (key === "events") processEvents(rows);
        else if (key === "services") state.sources.services = processStatusTransitions(
          "service", rows, state.sources.services, ["device_id", "service_name"], "status", "checked_at",
          row => `${row.service_name || "Service"} · ${row.device_id || "Unknown device"}`
        );
        else if (key === "availability") state.sources.availability = processStatusTransitions(
          "availability", rows, state.sources.availability, ["device_id", "target"], "status", "checked_at",
          row => `${row.target || "Endpoint"} · ${row.device_id || "Unknown device"}`
        );
        else if (key === "tasks") processTasks(rows, user, role);
        else if (key === "audit") processAudit(rows);
      }
      saveState();
    } catch (error) {
      console.warn("Cartman live notification poll failed:", error);
    } finally {
      inFlight = false;
    }
  }

  async function heartbeat() {
    if (!claimLease()) return;
    if (Date.now() - lastPollAt < POLL_INTERVAL_MS) return;
    lastPollAt = Date.now();
    await pollOnce();
  }

  function start() {
    if (intervalHandle) return;
    void heartbeat();
    intervalHandle = window.setInterval(() => { void heartbeat(); }, HEARTBEAT_INTERVAL_MS);
    window.addEventListener("pagehide", () => {
      if (intervalHandle) window.clearInterval(intervalHandle);
      intervalHandle = null;
      releaseLease();
    }, { once: true });
  }

  if (window.CartmanToast && typeof window.CartmanToast.notify === "function") start();
  else document.addEventListener("cartman:toast-ready", start, { once: true });
})();
