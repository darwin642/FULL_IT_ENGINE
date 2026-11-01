/* CARTMAN_SETTINGS_LIVE_V1 */
(() => {
  "use strict";
  const root = document.querySelector("#admin-page-root[data-admin-page='settings']");
  if (!root || root.dataset.settingsLive === "1") return;
  root.dataset.settingsLive = "1";
  const API = "/api/admin/system-settings";
  const defaults = {
    workspace_name: "Cartman", timezone: "Europe/Istanbul", default_refresh_seconds: 30,
    maintenance_mode: false,  usage_analytics: false, audit_retention_days: 365
  };

  function normalizeWorkspaceSettings(raw) {
    const value = { ...defaults, ...(raw || {}) };
    delete value.admin_notifications;
    return value;
  }
  const state = { settings: { ...defaults }, loading: true, saving: false, error: "", notice: "", updatedAt: null, updatedBy: null, passwordSaving: false, passwordError: "", passwordNotice: "" , notificationPreferences: { critical: true, warning: true, info: true, success: true }, notificationLoading: true, notificationSaving: false, notificationDirty: false, notificationError: "", notificationNotice: "" };
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      ...options
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = { detail: raw.slice(0, 250) }; }
    if (!response.ok) throw new Error(data.detail || `${response.status} ${response.statusText}`);
    return data;
  }
  const field = (label, description, control) => `<div class="admin-setting"><div><strong>${label}</strong><div class="admin-muted">${description}</div></div>${control}</div>`;
  const toggle = (key, label, description) => field(label, description,
    `<input class="admin-switch" type="checkbox" data-setting="${key}" aria-label="${label}" ${state.settings[key] ? "checked" : ""}>`);

  const timezoneCityLabels = {
    "Asia/Ho_Chi_Minh": "Ho Chi Minh City",
    "Asia/Kolkata": "Kolkata / New Delhi",
    "Asia/Kathmandu": "Kathmandu",
    "Europe/Istanbul": "Istanbul",
    "Europe/Minsk": "Minsk",
    "Europe/Moscow": "Moscow",
    "America/New_York": "New York",
    "America/Los_Angeles": "Los Angeles",
    "America/Toronto": "Toronto",
    "America/Vancouver": "Vancouver",
    "Australia/Sydney": "Sydney",
    "Pacific/Auckland": "Auckland",
    "UTC": "UTC"
  };
  function timezoneOffsetMinutes(zone, date) {
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: zone, timeZoneName: "longOffset"
      }).formatToParts(date);
      const label = parts.find(part => part.type === "timeZoneName")?.value || "GMT";
      const match = label.match(/(?:GMT|UTC)([+-])(\d{2}):(\d{2})/);
      if (!match) return 0;
      const value = Number(match[2]) * 60 + Number(match[3]);
      return match[1] === "+" ? value : -value;
    } catch (_) {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
      }).formatToParts(date);
      const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
      const localAsUtc = Date.UTC(Number(values.year), Number(values.month) - 1,
        Number(values.day), Number(values.hour), Number(values.minute), Number(values.second));
      return Math.round((localAsUtc - date.getTime()) / 60000);
    }
  }
  function timezoneOffsetLabel(minutes) {
    const sign = minutes < 0 ? "−" : "+";
    const absolute = Math.abs(minutes);
    return `UTC${sign}${String(Math.floor(absolute / 60)).padStart(2, "0")}:${String(absolute % 60).padStart(2, "0")}`;
  }
  function timezoneCityName(zone) {
    if (timezoneCityLabels[zone]) return timezoneCityLabels[zone];
    if (/^Etc\/GMT(?:[+-]\d+)?$/.test(zone)) return "Fixed UTC offset";
    const part = String(zone).split("/").pop() || zone;
    return part.replace(/_/g, " ").replace(/\bSt\b/g, "St.");
  }
  function timezoneOptionsMarkup(selectedZone) {
    let zones = [];
    try {
      zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
    } catch (_) {}
    const fixedOffsetZones = ["Etc/GMT"];
    for (let hour = 1; hour <= 12; hour += 1) fixedOffsetZones.push(`Etc/GMT+${hour}`);
    for (let hour = 1; hour <= 14; hour += 1) fixedOffsetZones.push(`Etc/GMT-${hour}`);
    ["UTC", "Europe/Istanbul", "Europe/Minsk", "Asia/Ho_Chi_Minh", selectedZone, ...fixedOffsetZones].forEach(zone => {
      if (zone && !zones.includes(zone)) zones.push(zone);
    });
    zones = [...new Set(zones)].filter(Boolean);
    const year = new Date().getUTCFullYear();
    const winter = new Date(Date.UTC(year, 0, 15, 12));
    const summer = new Date(Date.UTC(year, 6, 15, 12));
    const groups = new Map();
    zones.forEach(zone => {
      let offset = Math.min(timezoneOffsetMinutes(zone, winter), timezoneOffsetMinutes(zone, summer));
      if (zone === "UTC") offset = 0;
      if (!groups.has(offset)) groups.set(offset, []);
      groups.get(offset).push(zone);
    });
    return [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([offset, groupZones]) => {
      const options = groupZones.sort((a, b) => timezoneCityName(a).localeCompare(timezoneCityName(b)))
        .map(zone => `<option value="${esc(zone)}" ${zone === selectedZone ? "selected" : ""}>${esc(timezoneCityName(zone))} · ${esc(zone)}</option>`).join("");
      return `<optgroup label="(${timezoneOffsetLabel(offset)})">${options}</optgroup>`;
    }).join("");
  }

  function normalizeNotificationPreferences(raw) {
    const source = raw && raw.preferences ? raw.preferences : (raw || {});
    return {
      critical: source.critical !== false,
      warning: source.warning !== false,
      info: source.info !== false,
      success: source.success !== false
    };
  }
  function notificationPreferencesMarkup() {
    const prefs = state.notificationPreferences;
    const allEnabled = prefs.critical && prefs.warning && prefs.info && prefs.success;
    const allDisabled = !prefs.critical && !prefs.warning && !prefs.info && !prefs.success;
    const masterLabel = allEnabled ? "All on · Turn off" : (allDisabled ? "All off · Turn on" : "Mixed · Turn all off");
    const chip = (key, label, detail) => `
      <button type="button" class="cartman-notification-chip ${prefs[key] ? "is-active" : "is-inactive"}"
        data-notification-toggle="${key}" aria-pressed="${prefs[key] ? "true" : "false"}">
        <span class="cartman-notification-chip-top"><strong>${label}</strong><span class="cartman-notification-state">${prefs[key] ? "ON" : "OFF"}</span></span>
        <span class="cartman-notification-chip-detail">${detail}</span>
      </button>`;
    return `
      <article class="admin-card cartman-notification-preferences">
        <div class="cartman-notification-heading">
          <div><h3>Notification preferences</h3><p>Choose which notifications you receive on this account. These settings do not affect other users.</p></div>
          <span class="cartman-notification-personal">Personal settings</span>
        </div>
        ${state.notificationError ? `<div class="admin-notice cartman-notification-error">${esc(state.notificationError)}</div>` : ""}
        ${state.notificationNotice ? `<div class="admin-notice cartman-notification-success">${esc(state.notificationNotice)}</div>` : ""}
        <div class="cartman-notification-all-row">
          <div><strong>All notifications</strong><small>Turn every category on or off together.</small></div>
          <button type="button" class="cartman-notification-master ${allEnabled ? "is-active" : "is-inactive"}"
            data-notification-toggle="all" aria-pressed="${allEnabled ? "true" : "false"}">${masterLabel}</button>
        </div>
        <div class="cartman-notification-grid">
          ${chip("critical", "Critical", "Critical alerts and errors")}
          ${chip("warning", "Warning", "Warnings and attention needed")}
          ${chip("info", "Information", "Informational updates")}
          ${chip("success", "Success", "Completed actions and success updates")}
        </div>
        <div class="cartman-notification-footer">
          <span>${state.notificationLoading ? "Loading your preferences…" : "Your choices are saved to your Cartman account."} Existing notification history is not deleted.</span>
          <button type="button" class="admin-btn primary" data-notification-save ${state.notificationLoading || state.notificationSaving || !state.notificationDirty ? "disabled" : ""}>${state.notificationSaving ? "Saving…" : "Save preferences"}</button>
        </div>
      </article>`;
  }

  function render() {
    const s = state.settings;
    root.innerHTML = `
      <div class="admin-hero"><div><h2>System settings</h2><div class="admin-muted">Server-managed Cartman workspace configuration.</div></div>
        <div class="admin-actions"><button class="admin-btn" data-refresh ${state.loading || state.saving ? "disabled" : ""}>Refresh</button>
        <button class="admin-btn primary" data-save ${state.loading || state.saving || (Boolean(state.error) && !state.updatedAt) ? "disabled" : ""}>${state.saving ? "Saving…" : "Save settings"}</button></div>
      </div>
      ${state.error ? `<div class="admin-notice">${esc(state.error)}</div>` : ""}
      ${state.notice ? `<div class="admin-notice">${esc(state.notice)}</div>` : ""}
      <div class="admin-grid">
        <article class="admin-card"><div class="admin-muted">Configuration items</div><div class="admin-kpi">${Object.keys(defaults).length}</div><p>Persisted in Cartman's database</p></article>
        <article class="admin-card"><div class="admin-muted">Last updated</div><div class="admin-kpi" style="font-size:16px">${esc(state.updatedAt ? new Date(state.updatedAt).toLocaleString() : "—")}</div><p>${esc(state.updatedBy || "No saved changes")}</p></article>
        <article class="admin-card"><div class="admin-muted">Storage scope</div><div class="admin-kpi" style="font-size:18px">Server-wide</div><p>Workspace-wide configuration shared by authorized administrators</p></article>
      </div>
      <article class="admin-card"><h3>Workspace</h3><p>General display and refresh preferences.</p>
        <div class="admin-setting"><div><strong>Workspace name</strong><div class="admin-muted">Name displayed in this configuration.</div></div><input class="admin-text-input" data-setting="workspace_name" maxlength="80" value="${esc(s.workspace_name)}"></div>
        <div class="admin-setting cartman-timezone-setting"><div><strong>Timezone</strong><div class="admin-muted">Preferred timezone for future server-generated schedules and reports.</div></div><select data-setting="timezone" aria-label="Workspace timezone">${timezoneOptionsMarkup(s.timezone)}</select></div>
        <div class="admin-setting"><div><strong>Automatic page refresh</strong><div class="admin-muted">How often supported pages refresh their data automatically.</div></div><select data-setting="default_refresh_seconds"><option value="15" ${s.default_refresh_seconds === 15 ? "selected" : ""}>15 seconds</option><option value="30" ${s.default_refresh_seconds === 30 ? "selected" : ""}>30 seconds</option><option value="60" ${s.default_refresh_seconds === 60 ? "selected" : ""}>60 seconds</option><option value="120" ${s.default_refresh_seconds === 120 ? "selected" : ""}>120 seconds</option></select></div>
      </article>
      <article class="admin-card"><h3>Operations preferences</h3><p>Values are saved centrally. A preference does not imply that a runtime policy engine is already enforcing it.</p>
        ${toggle("maintenance_mode", "Maintenance mode", "Marks the workspace as under maintenance. Access restrictions and maintenance banners are not active in this build.")}
        <div class="admin-setting"><div><strong>Audit log retention</strong><div class="admin-muted">How long audit records should be retained. Automatic cleanup is not active yet.</div></div><select data-setting="audit_retention_days"><option value="30" ${s.audit_retention_days === 30 ? "selected" : ""}>30 days</option><option value="90" ${s.audit_retention_days === 90 ? "selected" : ""}>90 days</option><option value="180" ${s.audit_retention_days === 180 ? "selected" : ""}>180 days</option><option value="365" ${s.audit_retention_days === 365 ? "selected" : ""}>365 days</option><option value="730" ${s.audit_retention_days === 730 ? "selected" : ""}>730 days</option></select></div>
      </article>
      <article class="admin-card"><h3>Data preferences</h3>
        ${toggle("usage_analytics", "Usage analytics", "Controls a future usage analytics collector. Data collection is not active yet.")}
      </article>

      ${notificationPreferencesMarkup()}
      <article class="admin-card cartman-account-security">
        <div class="cartman-account-security-heading">
          <div>
            <h3>Account Security</h3>
            <p>Change the password for your currently signed-in Cartman account.</p>
          </div>
          <span class="cartman-security-tag">PBKDF2-SHA256</span>
        </div>
        ${state.passwordError ? `<div class="admin-notice cartman-password-error">${esc(state.passwordError)}</div>` : ""}
        ${state.passwordNotice ? `<div class="admin-notice cartman-password-success">${esc(state.passwordNotice)}</div>` : ""}
        <form data-password-form autocomplete="off">
          <div class="cartman-password-grid">
            <div class="cartman-password-field">
              <label for="cartman-current-password">Current password</label>
              <div class="cartman-password-control">
                <input class="admin-text-input" id="cartman-current-password" name="current_password" type="password" autocomplete="current-password" required maxlength="1024" ${state.passwordSaving ? "disabled" : ""}>
                <button class="admin-btn cartman-password-toggle" type="button" data-password-toggle="cartman-current-password">Show</button>
              </div>
            </div>
            <div class="cartman-password-field">
              <label for="cartman-new-password">New password</label>
              <div class="cartman-password-control">
                <input class="admin-text-input" id="cartman-new-password" name="new_password" type="password" autocomplete="new-password" required minlength="14" maxlength="128" ${state.passwordSaving ? "disabled" : ""}>
                <button class="admin-btn cartman-password-toggle" type="button" data-password-toggle="cartman-new-password">Show</button>
              </div>
              <small>Use at least 14 characters.</small>
            </div>
            <div class="cartman-password-field">
              <label for="cartman-confirm-password">Confirm new password</label>
              <div class="cartman-password-control">
                <input class="admin-text-input" id="cartman-confirm-password" name="confirm_password" type="password" autocomplete="new-password" required minlength="14" maxlength="128" ${state.passwordSaving ? "disabled" : ""}>
                <button class="admin-btn cartman-password-toggle" type="button" data-password-toggle="cartman-confirm-password">Show</button>
              </div>
            </div>
          </div>
          <div class="cartman-password-footnote">Your current password is verified before the change. Passwords are stored as PBKDF2-SHA256 hashes. Other active sessions are revoked; this session remains active.</div>
          <div class="admin-actions cartman-password-actions">
            <button class="admin-btn primary" type="submit" ${state.passwordSaving ? "disabled" : ""}>${state.passwordSaving ? "Changing password…" : "Change password"}</button>
          </div>
        </form>
      </article>

      <div class="admin-notice">Workspace settings are stored in SQLite and audited. MFA enforcement, idle-session policy enforcement and automated audit cleanup are not active in this build.</div>
      ${state.loading ? `<div class="admin-muted">Loading settings from Cartman…</div>` : ""}`;
  }
  function collect() {
    const result = { ...state.settings };
    root.querySelectorAll("[data-setting]").forEach(control => {
      const key = control.dataset.setting;
      if (control.type === "checkbox") result[key] = control.checked;
      else if (key === "default_refresh_seconds" || key === "audit_retention_days") result[key] = Number(control.value);
      else result[key] = control.value;
    });
    return result;
  }
  async function load() {
    state.loading = true; state.error = ""; render();
    try {
      const data = await request(API);
      state.settings = normalizeWorkspaceSettings(data.settings);
      state.updatedAt = data.updated_at || null;
      state.updatedBy = data.updated_by || null;
    } catch (error) { state.error = error.message; }
    finally { state.loading = false; render(); }
  }

  async function loadNotificationPreferences() {
    state.notificationLoading = true;
    try {
      const data = await request("/api/auth/notification-preferences");
      state.notificationPreferences = normalizeNotificationPreferences(data);
      state.notificationDirty = false;
      window.CartmanNotificationPreferences = { ...state.notificationPreferences };
      state.notificationError = "";
    } catch (error) {
      state.notificationError = error.message || "Notification preferences could not be loaded.";
    } finally {
      state.settings = collect();
      state.notificationLoading = false;
      render();
    }
  }

  async function saveNotificationPreferences() {
    if (state.notificationSaving || state.notificationLoading || !state.notificationDirty) return;
    state.settings = collect();
    state.notificationSaving = true;
    state.notificationError = "";
    state.notificationNotice = "";
    render();
    try {
      const data = await request("/api/auth/notification-preferences", {
        method: "PUT", body: JSON.stringify(state.notificationPreferences)
      });
      state.notificationPreferences = normalizeNotificationPreferences(data);
      state.notificationDirty = false;
      window.CartmanNotificationPreferences = { ...state.notificationPreferences };
      state.notificationNotice = "Your notification preferences have been saved.";
    } catch (error) {
      state.notificationError = error.message || "Notification preferences could not be saved.";
    } finally {
      state.notificationSaving = false;
      render();
    }
  }

  root.addEventListener("click", async event => {

    const notificationToggle = event.target.closest("[data-notification-toggle]");
    if (notificationToggle && !state.notificationLoading && !state.notificationSaving) {
      state.settings = collect();
      const key = notificationToggle.dataset.notificationToggle;
      if (key === "all") {
        const prefs = state.notificationPreferences;
        const allDisabled = !prefs.critical && !prefs.warning && !prefs.info && !prefs.success;
        const next = allDisabled;
        state.notificationPreferences = { critical: next, warning: next, info: next, success: next };
      } else if (Object.prototype.hasOwnProperty.call(state.notificationPreferences, key)) {
        state.notificationPreferences[key] = !state.notificationPreferences[key];
      }
      state.notificationDirty = true;
      render();
      return;
    }
    if (event.target.closest("[data-notification-save]")) {
      state.settings = collect();
      await saveNotificationPreferences();
      return;
    }
    const passwordToggle = event.target.closest("[data-password-toggle]");
    if (passwordToggle) {
      const input = root.querySelector("#" + passwordToggle.dataset.passwordToggle);
      if (input) {
        const reveal = input.type === "password";
        input.type = reveal ? "text" : "password";
        passwordToggle.textContent = reveal ? "Hide" : "Show";
      }
      return;
    }
    if (event.target.closest("[data-refresh]")) { await load(); return; }
    if (!event.target.closest("[data-save]") || state.saving) return;
    const settings = collect();
    state.saving = true; state.error = ""; state.notice = ""; render();
    try {
      const data = await request(API, { method: "PUT", body: JSON.stringify({ settings }) });
      state.settings = normalizeWorkspaceSettings(data.settings || settings);
      state.updatedAt = data.updated_at || null; state.updatedBy = data.updated_by || null;
      state.notice = "Settings saved to the Cartman server and recorded in the audit log.";
    } catch (error) { state.error = error.message; }
    finally { state.saving = false; render(); }
  });
  root.addEventListener("submit", async event => {
    const form = event.target.closest("[data-password-form]");
    if (!form) return;
    event.preventDefault();
    if (state.passwordSaving) return;

    const data = new FormData(form);
    const currentPassword = String(data.get("current_password") || "");
    const newPassword = String(data.get("new_password") || "");
    const confirmPassword = String(data.get("confirm_password") || "");
    if (newPassword.length < 14) {
      state.passwordError = "The new password must contain at least 14 characters.";
      state.passwordNotice = "";
      render();
      return;
    }
    if (newPassword !== confirmPassword) {
      state.passwordError = "The new passwords do not match.";
      state.passwordNotice = "";
      render();
      return;
    }
    if (currentPassword === newPassword) {
      state.passwordError = "Choose a password different from your current password.";
      state.passwordNotice = "";
      render();
      return;
    }

    state.passwordSaving = true;
    state.passwordError = "";
    state.passwordNotice = "";
    render();
    try {
      const result = await request("/api/auth/password/change", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword
        })
      });
      state.passwordNotice = "Password changed successfully. " + Number(result.other_sessions_revoked || 0) + " other session(s) signed out.";
    } catch (error) {
      state.passwordError = error.message || "Password could not be changed.";
    } finally {
      state.passwordSaving = false;
      render();
    }
  });

  load();
  loadNotificationPreferences();
})();