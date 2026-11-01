/* CARTMAN_BACKUP_FLOW_V6_REQUESTED_FLOW */
/* CARTMAN_BACKUP_V6_REPAIR_HOTFIX */
(() => {
  "use strict";
  const root = document.getElementById("backup-recovery-root");
  if (!root || root.dataset.backupFlowV6 === "1") return;
  root.dataset.backupFlowV6 = "1";

  const API = "/api/admin/backups/v3";
  const state = {
    tab: "overview", items: [], catalog: [], pending: null,
    storageBytes: 0, legacyCount: 0, repository: "app/.cartman-backups",
    loading: true, busy: false, error: "", notice: "",
    mode: "full", selective: new Set(), localFile: null,
    localPassword: "", unlockId: "", unlockPurpose: "details", unlockError: "",
    detail: null, restoreId: "", restoreManifest: null, restorePassword: ""
  };

  const toText = value => {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (typeof value === "object") return String(value.message || value.detail || value.name || JSON.stringify(value));
    return String(value);
  };
  const esc = value => toText(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const fmtSize = bytes => {
    let n = Math.max(0, Number(bytes) || 0), i = 0;
    const units = ["B", "KB", "MB", "GB", "TB"];
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
  };
  const fmtDate = value => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
  };
  const shortId = value => toText(value).slice(0, 8).toUpperCase();
  const badge = (label, tone = "neutral") => `<span class="bk4-badge ${tone}">${esc(label)}</span>`;
  const button = (label, action, id = "", tone = "") => `<button type="button" class="bk4-btn ${tone}" data-action="${esc(action)}" ${id ? `data-id="${esc(id)}"` : ""} ${state.busy ? "disabled" : ""}>${esc(label)}</button>`;
  const notice = (message, tone = "info") => `<div class="bk4-notice ${tone}" role="status">${esc(message)}</div>`;

  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(options.body && typeof options.body === "string" ? { "Content-Type": "application/json" } : {}) },
      ...options
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = { detail: raw.slice(0, 300) }; }
    if (!response.ok) throw new Error(toText(data.detail) || `${response.status} ${response.statusText}`);
    return data;
  }

  const tabs = () => {
    const items = [["overview", "Overview"], ["create", "New Backup"], ["history", "Backup History"], ["recovery", "Recovery Center"]];
    return `<nav class="bk4-tabs" aria-label="Backup sections">${items.map(([id, label]) => `<button type="button" data-tab="${id}" class="bk4-tab ${state.tab === id ? "active" : ""}">${label}</button>`).join("")}</nav>`;
  };
  const empty = (title, description) => `<div class="bk4-empty"><span>▤</span><strong>${esc(title)}</strong><p>${esc(description)}</p></div>`;
  const available = () => state.catalog.filter(x => x.available);
  const dbModules = () => available().filter(x => x.section === "Database" && x.id !== "db:all");
  const fileModules = () => available().filter(x => x.section === "Files & Data");
  const fullSystemIds = () => {
    const db = dbModules().map(x => x.id);
    const other = available().filter(x => x.section !== "Database").map(x => x.id);
    return [...(db.length ? db : (available().some(x => x.id === "db:all") ? ["db:all"] : [])), ...other];
  };
  const selectiveMap = () => ({
    "data-files": [...dbModules().map(x => x.id), ...fileModules().map(x => x.id)],
    "database-only": available().some(x => x.id === "db:all") ? ["db:all"] : dbModules().map(x => x.id),
    "tickets-attachments": ["db:tickets", "files:tickets"],
    "settings-policies": ["db:settings"],
    "application-config": available().filter(x => x.section === "Application" || x.section === "Configuration" || x.section === "Security").map(x => x.id)
  });
  const optionDefs = [
    ["data-files", "Data + Files", "Cartman records, database modules and detected file storage"],
    ["database-only", "Database only", "All SQLite tables and Cartman records"],
    ["tickets-attachments", "Tickets + Attachments", "Ticket records, comments and related attachments"],
    ["settings-policies", "Settings + Policies", "System settings and policy records"],
    ["application-config", "Application + Config", "Backend, frontend, scripts, dependencies, configuration and security files"]
  ];
  function selectedComponents() {
    if (state.mode === "full") return fullSystemIds();
    const mapping = selectiveMap();
    return [...new Set([...state.selective].flatMap(key => mapping[key] || []).filter(id => available().some(x => x.id === id)))];
  }
  function componentSourceBytes(item) {
    if (!item) return 0;
    const direct = Math.max(0, Number(item.bytes || item.estimated_bytes) || 0);
    if (direct > 0) return direct;
    if (item.section === "Database") {
      const fullDb = state.catalog.find(x => x.id === "db:all");
      const totalBytes = Math.max(0, Number(fullDb && (fullDb.bytes || fullDb.estimated_bytes)) || 0);
      const totalTables = Math.max(0, Number(fullDb && (fullDb.table_total || (fullDb.tables || []).length)) || 0);
      const itemTables = Math.max(0, Number(item.table_total || (item.tables || []).length || item.table_count) || 0);
      if (totalBytes > 0 && totalTables > 0 && itemTables > 0) {
        return Math.max(1, Math.round(totalBytes * itemTables / totalTables));
      }
    }
    return 0;
  }
  function estimateBytes(ids) {
    const unique = [...new Set(ids)];
    const source = unique.reduce((sum, id) => {
      return sum + componentSourceBytes(state.catalog.find(x => x.id === id));
    }, 0);
    if (!source) return 0;
    return Math.max(64 * 1024, Math.round(source * 0.82) + 64 * 1024);
  }
  function estimatePanel(ids) {
    const selected = [...new Set(ids)];
    const sourceBytes = selected.reduce((sum, id) => {
      const item = state.catalog.find(x => x.id === id);
      return sum + (Number(item?.bytes) || 0);
    }, 0);
    const estimate = estimateBytes(selected);
    return `<div class="bk5-estimate"><div><span>Estimated backup size</span><strong>${selected.length ? `~${fmtSize(estimate)}` : "Select backup contents"}</strong></div><small>Estimate uses the current SQLite database size and detected file sizes. The final encrypted archive can differ because of compression and encryption metadata.</small><div class="bk5-estimate-meta">${selected.length} data groups · ${fmtSize(sourceBytes)} estimated source data</div></div>`;
  }
  function rowSummary(item) {
    const components = Object.values(item.components || {});
    const groups = components.length;
    const files = components.reduce((n, x) => n + Number(x.file_count || 0), 0);
    const tables = components.reduce((n, x) => n + Number(x.table_count || 0), 0);
    return `${groups} selections · ${tables} tables · ${files} files`;
  }
  function backupRows(items) {
    if (!items.length) return empty("No encrypted backups yet", "Create a Full Backup or Selective Backup and save the encrypted .cartmanbackup file to your chosen location.");
    return `<div class="bk4-table-wrap"><table class="bk4-table"><thead><tr><th>Backup</th><th>Created</th><th>Encrypted size</th><th>Protection</th><th>Contents</th><th>Actions</th></tr></thead><tbody>${items.map(item => `<tr><td><strong>${esc(item.filename || shortId(item.id))}</strong><small>${esc(item.id || "")}</small></td><td>${esc(fmtDate(item.created_at))}</td><td>${fmtSize(item.bytes)}</td><td>${badge("AES-256-GCM", "good")} ${badge("Locked")}</td><td>${esc(rowSummary(item))}</td><td><div class="bk4-row-actions">${button("Unlock details", "unlock", item.id)}${button("Download backup", "download", item.id)}</div></td></tr>`).join("")}</tbody></table></div>`;
  }

  function overview() {
    const latest = state.items[0];
    const dbCount = state.catalog.filter(x => x.section === "Database" && x.id !== "db:all" && x.available).reduce((n, x) => n + Number(x.table_total || 0), 0);
    const availableCount = available().length;
    return `<section class="bk4-stats">
      <article><span>Encrypted backups</span><strong>${state.items.length}</strong><small>Private recovery catalog</small></article>
      <article><span>Repository usage</span><strong>${fmtSize(state.storageBytes)}</strong><small>Encrypted archive copies</small></article>
      <article><span>Detected database tables</span><strong>${dbCount}</strong><small>Available in this Cartman instance</small></article>
      <article><span>Backup components</span><strong>${availableCount}</strong><small>Detected data and file groups</small></article>
    </section>
    <section class="bk4-main-grid">
      <article class="bk4-panel"><div class="bk4-kicker">LATEST BACKUP</div>${latest ? `<h2>${esc(latest.filename || shortId(latest.id))}</h2><p>${esc(fmtDate(latest.created_at))}</p><div class="bk4-kv"><span>Archive size</span><strong>${fmtSize(latest.bytes)}</strong></div><div class="bk4-kv"><span>Encryption</span><strong>AES-256-GCM</strong></div><div class="bk4-kv"><span>Inspection</span><strong>Password required</strong></div>${button("Unlock details", "unlock", latest.id)}` : empty("No backup yet", "Create a new backup to protect your Cartman data.")}</article>
      <article class="bk4-panel"><div class="bk4-kicker">PROTECTION STATUS</div><h2>Backup security</h2><div class="bk4-kv"><span>Encryption</span><strong>AES-256-GCM</strong></div><div class="bk4-kv"><span>Password derivation</span><strong>Scrypt</strong></div><div class="bk4-kv"><span>Integrity verification</span><strong>SHA-256</strong></div><div class="bk4-kv"><span>Recovery source</span><strong>Local .cartmanbackup file</strong></div><p class="bk4-muted">Backups are created as encrypted files and can be restored from a file on your computer.</p></article>
    </section>
    <section class="bk4-panel"><div class="bk4-panel-head"><div><div class="bk4-kicker">RECENT ACTIVITY</div><h2>Recent backups</h2></div><button type="button" class="bk4-link" data-tab="history">View history →</button></div>${backupRows(state.items.slice(0, 5))}</section>`;
  }

  function createView() {
    const mapping = selectiveMap();
    const options = optionDefs.map(([id, label, description]) => {
      const ids = [...new Set(mapping[id] || [])].filter(componentId => available().some(x => x.id === componentId));
      const checked = state.selective.has(id);
      const optionSize = estimateBytes(ids);
      const found = ids.length > 0;
      return `<label class="bk5-option ${checked ? "selected" : ""}"><input type="checkbox" data-selective-option="${id}" ${checked ? "checked" : ""}><span class="bk5-check" aria-hidden="true">✓</span><span class="bk5-option-copy"><strong>${label}</strong><small>${description}</small><small>${found ? `Estimated source: ${fmtSize(optionSize)}` : "No matching data detected on this Cartman server"}</small></span>${badge(found ? "Detected" : "Not detected", found ? "good" : "neutral")}</label>`;
    }).join("");
    const ids = selectedComponents();
    return `<section class="bk4-panel">
      <div class="bk4-panel-head"><div><div class="bk4-kicker">NEW BACKUP</div><h2>Create a backup</h2><p>Name your backup, choose a backup mode and save the encrypted file to your computer.</p></div>${badge("Password required", "good")}</div>
      <form id="bk5-create-form" class="bk4-form">
        <label class="bk4-field"><span>Backup name</span><input name="name" maxlength="120" required placeholder="e.g. Cartman pre-upgrade backup" value=""></label>
        <div class="bk4-section-head"><div><h3>Backup mode</h3><p>Choose one of the two backup modes.</p></div></div>
        <div class="bk5-mode-toggle">
          <button type="button" data-mode="full" class="bk5-mode ${state.mode === "full" ? "active" : ""}"><strong>Full Backup</strong><small>All detected Cartman data, files, application and configuration</small></button>
          <button type="button" data-mode="selective" class="bk5-mode ${state.mode === "selective" ? "active" : ""}"><strong>Selective Backup</strong><small>Choose individual backup groups</small></button>
        </div>
        ${state.mode === "selective" ? `<section class="bk5-selective"><div class="bk4-section-head"><div><h3>Choose what to include</h3><p>Select one or more groups. Database only is exclusive with the other groups.</p></div></div><div class="bk5-options">${options}</div></section>` : ""}
        ${estimatePanel(ids)}
        <div class="bk4-password-grid"><label class="bk4-field"><span>Backup password</span><input name="password" type="password" minlength="12" maxlength="1024" autocomplete="new-password" required placeholder="At least 12 characters"></label><label class="bk4-field"><span>Confirm password</span><input name="confirm_password" type="password" minlength="12" maxlength="1024" autocomplete="new-password" required placeholder="Repeat password"></label></div>
        <div class="bk4-security"><strong>Mandatory encryption</strong><p>AES-256-GCM encryption · Scrypt password derivation · SHA-256 integrity verification. Cartman does not store your password. Keep it safe; a lost password cannot be reset.</p></div>
        <div class="bk4-form-error" data-create-error hidden></div>
        <div class="bk4-actions"><button type="submit" class="bk4-btn primary" ${state.busy ? "disabled" : ""}>${state.busy ? "Creating backup…" : "Start Backup"}</button><button type="button" class="bk4-btn" data-tab="overview">Cancel</button></div>
      </form>
    </section>`;
  }

  function history() {
    return `<section class="bk4-panel"><div class="bk4-panel-head"><div><div class="bk4-kicker">BACKUP HISTORY</div><h2>Encrypted backups</h2><p>Encrypted backups indexed by Cartman. Save a copy to your computer or unlock the details.</p></div>${button("Refresh", "refresh")}</div>${backupRows(state.items)}</section>`;
  }

  function pendingPanel() {
    if (!state.pending) return empty("No restore is staged", "Choose a .cartmanbackup file from this computer, enter its password and prepare a restore.");
    return `<div class="bk4-pending"><div class="bk4-kicker">RESTORE PREPARED · OFFLINE APPLY REQUIRED</div><h3>${esc(shortId(state.pending.backup_id))}</h3><p>Selected items: ${esc((state.pending.components || []).join(", "))}</p><p>Prepared: ${esc(fmtDate(state.pending.prepared_at))} · By: ${esc(state.pending.prepared_by || "Unknown")}</p><div class="bk4-command"><code>${esc(state.pending.command)}</code>${button("Copy command", "copy-command")}</div><ol><li>Stop Cartman / Uvicorn completely.</li><li>Run the command from the project root.</li><li>Enter the backup password when prompted.</li><li>Restart Cartman and verify its health.</li></ol>${button("Cancel staged restore", "cancel-pending", "", "danger")}</div>`;
  }
  function recovery() {
    return `<section class="bk4-panel"><div class="bk4-panel-head"><div><div class="bk4-kicker">RECOVERY CENTER</div><h2>Restore from a backup file</h2><p>Select a .cartmanbackup file from this computer. Cartman will ask for its password immediately after selection.</p></div>${badge(state.pending ? "Restore staged" : "Ready", state.pending ? "warning" : "good")}</div>
      <div class="bk5-recovery-picker"><input id="bk5-local-file" type="file" accept=".cartmanbackup,application/octet-stream" hidden><div class="bk5-file-drop"><span class="bk5-file-icon">↥</span><strong>${state.localFile ? esc(state.localFile.name) : "Choose a Cartman backup file"}</strong><small>${state.localFile ? `${fmtSize(state.localFile.size)} · ${esc(state.localFile.type || "Encrypted backup")}` : "Select a .cartmanbackup file from this computer"}</small><button type="button" class="bk4-btn" data-action="choose-file">${state.localFile ? "Choose a different backup" : "Choose backup file"}</button></div>
      ${state.localFile ? `<form id="bk5-local-unlock-form" class="bk5-local-unlock"><label class="bk4-field"><span>Backup password</span><input name="password" type="password" minlength="12" maxlength="1024" required autocomplete="current-password" placeholder="Enter the password for this backup"></label><p class="bk4-muted">The selected encrypted file is verified with its password, AES-GCM authentication and SHA-256 checks before it is added to the private recovery catalog. The file remains encrypted during transfer and storage.</p><div class="bk4-form-error" data-local-unlock-error hidden></div><div class="bk4-actions"><button type="submit" class="bk4-btn primary">Unlock &amp; inspect backup</button><button type="button" class="bk4-btn" data-action="clear-file">Clear selection</button></div></form>` : ""}</div>
    </section>
    <section class="bk4-panel"><div class="bk4-panel-head"><div><div class="bk4-kicker">STAGED RESTORE</div><h2>Restore operations</h2><p>A staged restore can only be applied after Cartman is stopped.</p></div></div>${pendingPanel()}</section>
    <div class="bk4-security"><strong>Restore safety</strong><p>Cartman verifies the password, AES-GCM authentication, archive SHA-256 and every file checksum before showing backup contents. It then creates a new full-system encrypted safety backup. Selected database tables are merged transactionally; file restore overlays files and does not delete unrelated files absent from the backup. The server must be stopped before applying the staged restore.</p></div>`;
  }

  function unlockModal() {
    if (!state.unlockId) return "";
    return `<div class="bk4-modal-backdrop" data-close-unlock><section class="bk4-modal" role="dialog" aria-modal="true"><header><div><div class="bk4-kicker">UNLOCK BACKUP</div><h2>Enter backup password</h2><p>Cartman verifies the encrypted archive and all SHA-256 records before showing its contents.</p></div><button type="button" class="bk4-btn" data-action="close-unlock">Close</button></header><form id="bk5-unlock-form"><label class="bk4-field"><span>Backup password</span><input type="password" name="password" minlength="12" maxlength="1024" required autocomplete="current-password"></label><div class="bk4-form-error" ${state.unlockError ? "" : "hidden"}>${esc(state.unlockError)}</div><div class="bk4-actions"><button type="submit" class="bk4-btn primary">Decrypt &amp; verify</button></div></form></section></div>`;
  }
  function detailModal() {
    if (!state.detail) return "";
    const manifest = state.detail.manifest || {}, backup = state.detail.backup || {};
    const components = Object.entries(manifest.components || {}), entries = manifest.entries || [];
    return `<div class="bk4-modal-backdrop" data-close-detail><section class="bk4-modal wide" role="dialog" aria-modal="true"><header><div><div class="bk4-kicker">VERIFIED BACKUP DETAILS</div><h2>${esc(manifest.name || shortId(backup.id))}</h2><p>${esc(backup.id || "")}</p></div><button type="button" class="bk4-btn" data-action="close-detail">Close</button></header>
      <div class="bk4-detail-stats"><div><span>Created</span><strong>${esc(fmtDate(backup.created_at))}</strong></div><div><span>Created by</span><strong>${esc(manifest.created_by || "Unknown")}</strong></div><div><span>Encrypted size</span><strong>${fmtSize(backup.bytes)}</strong></div><div><span>Encryption</span><strong>AES-256-GCM</strong></div><div><span>Integrity</span><strong>${esc(backup.integrity || "Verified")}</strong></div></div>
      <div class="bk4-kv"><span>Encrypted archive SHA-256</span><code>${esc(backup.sha256 || "Verified by archive footer")}</code></div><h3>Selected contents</h3><div class="bk4-detail-components">${components.map(([id, info]) => `<article><strong>${esc(info.name || id)}</strong><span>${esc(info.section || "")}</span><small>${Number(info.table_count || 0)} tables · ${Number(info.file_count || 0)} files · ${fmtSize(info.bytes || 0)}</small>${info.tables?.length ? `<small>Tables: ${esc(info.tables.map(t => `${t} (${info.table_rows?.[t] ?? "?"} rows)`).join(", "))}</small>` : ""}${info.directories?.length ? `<small>Directories: ${esc(info.directories.join(", "))}</small>` : ""}</article>`).join("")}</div>
      <div class="bk4-table-wrap bk4-contents"><h3>Exact backup contents (${entries.length} entries)</h3><table class="bk4-table"><thead><tr><th>Selection</th><th>Path / Snapshot</th><th>Size</th><th>SHA-256</th></tr></thead><tbody>${entries.slice(0, 1000).map(x => `<tr><td>${esc((manifest.components[x.component] || {}).name || x.component)}</td><td><code>${esc(x.path)}</code></td><td>${fmtSize(x.size)}</td><td><code>${esc(x.sha256)}</code></td></tr>`).join("")}</tbody></table>${entries.length > 1000 ? `<p>Showing first 1,000 of ${entries.length} entries.</p>` : ""}</div>
      <div class="bk4-actions">${button("Prepare restore", "open-restore", backup.id, "danger")}</div></section></div>`;
  }
  function restoreModal() {
    if (!state.restoreId || !state.restoreManifest) return "";
    const components = Object.entries(state.restoreManifest.components || {});
    return `<div class="bk4-modal-backdrop" data-close-restore><section class="bk4-modal wide" role="dialog" aria-modal="true"><header><div><div class="bk4-kicker">RESTORE PLAN</div><h2>Select what to restore</h2><p>${esc(state.restoreManifest.name || shortId(state.restoreId))}</p></div><button type="button" class="bk4-btn" data-action="close-restore">Close</button></header><form id="bk5-restore-form"><p class="bk4-muted">Only checked components will be restored. A full encrypted safety backup is created before the restore is staged.</p><div class="bk4-notice error"><strong>IRREVERSIBLE OVERWRITE WARNING</strong><br>If a selected backup contains a file at a path that already exists in Cartman, the existing file at that same path will be replaced by the backup copy. That individual replacement cannot be undone in place. Cartman creates a separate encrypted pre-restore safety backup first. Files that are not present in the backup are not deleted.</div><div class="bk4-restore-checks">${components.map(([id, info]) => `<label><input type="checkbox" name="components" value="${esc(id)}" checked><span><strong>${esc(info.name || id)}</strong><small>${Number(info.table_count || 0)} tables · ${Number(info.file_count || 0)} files · ${fmtSize(info.bytes || 0)}</small></span></label>`).join("")}</div><label class="bk4-confirm"><input type="checkbox" name="confirm" required> I understand that selected database tables and files will be restored into Cartman.</label><div class="bk4-form-error" data-restore-error hidden></div><div class="bk4-actions"><button type="submit" class="bk4-btn danger">Verify &amp; prepare restore</button></div></form></section></div>`;
  }

  function render() {
    let content = state.tab === "create" ? createView() : state.tab === "history" ? history() : state.tab === "recovery" ? recovery() : overview();
    root.innerHTML = `<div class="bk4-shell"><header class="bk4-hero"><div><div class="bk4-kicker">CARTMAN / DATA PROTECTION</div><h1>Backup &amp; Recovery</h1><p>Create password-protected Cartman backup files and restore them from a backup file.</p><div class="bk4-hero-tags">${badge("AES-256-GCM", "good")}${badge("SHA-256 integrity")}${badge("Password required")}</div></div><div class="bk4-hero-actions"><span class="bk4-server-state">ENCRYPTED BACKUP FILES · LOCAL SAVE</span>${button("Refresh", "refresh")}${button("＋ New Backup", "create", "", "primary")}</div></header>${state.error ? notice(state.error, "error") : ""}${state.notice ? notice(state.notice, "success") : ""}${tabs()}${content}<footer class="bk4-footer"><span>${state.items.length} encrypted backups in recovery catalog</span><span>${state.legacyCount} legacy ZIP archives preserved</span><span>${esc(state.repository)}</span></footer>${state.loading ? `<div class="bk4-loading">Loading backup catalog…</div>` : ""}${unlockModal()}${detailModal()}${restoreModal()}</div>`;
  }

  async function load() {
    state.loading = true; state.error = ""; render();
    try {
      const [list, catalog, pending] = await Promise.all([request(API), request(API + "/catalog"), request(API + "/restore-pending")]);
      state.items = list.items || [];
      state.legacyCount = Number(list.legacy_unencrypted_count) || 0;
      state.storageBytes = Number(list.storage_bytes) || 0;
      state.repository = list.repository || "app/.cartman-backups";
      state.catalog = catalog.components || [];
      state.pending = pending.pending ? pending.restore : null;
    } catch (error) { state.error = toText(error.message || error) || "Could not load backup catalog."; }
    finally { state.loading = false; render(); }
  }

  function safeFilename(name) {
    const cleaned = toText(name).trim().replace(/[\\/:*?"<>|\x00-\x1F]/g, "-").replace(/\s+/g, "-").replace(/-+/g, "-").replace(/^[-.]+|[-.]+$/g, "").slice(0, 100);
    const base = (cleaned || "Cartman-Backup").replace(/\.cartmanbackup$/i, "");
    return base + ".cartmanbackup";
  }
  async function chooseSaveHandle(name) {
    if (typeof window.showSaveFilePicker !== "function") return null;
    return window.showSaveFilePicker({
      suggestedName: safeFilename(name),
      types: [{ description: "Cartman encrypted backup", accept: { "application/octet-stream": [".cartmanbackup"] } }],
      excludeAcceptAllOption: false
    });
  }
  async function saveBackupToMac(id, name, existingHandle = null) {
    let handle = existingHandle;
    if (!handle && typeof window.showSaveFilePicker === "function") handle = await chooseSaveHandle(name || `Cartman-${shortId(id)}`);
    const response = await fetch(`${API}/${encodeURIComponent(id)}/download`, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try { const obj = await response.json(); detail = obj.detail || detail; } catch (_) {}
      throw new Error(toText(detail));
    }
    const blob = await response.blob();
    if (handle) {
      const writable = await handle.createWritable();
      try { await writable.write(blob); await writable.close(); }
      catch (error) { try { await writable.abort(); } catch (_) {} throw error; }
      return handle.name;
    }
    const url = URL.createObjectURL(blob), anchor = document.createElement("a");
    anchor.href = url; anchor.download = safeFilename(name || `Cartman-${shortId(id)}`);
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
    return anchor.download;
  }
  async function importAndUnlock(file, password) {
    const response = await fetch(`${API}/import-file`, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/octet-stream", "X-Cartman-Backup-Password": password, "X-Cartman-Backup-Filename": safeFilename(file.name).slice(0, 120) },
      body: file
    });
    const raw = await response.text(); let result = {};
    try { result = raw ? JSON.parse(raw) : {}; } catch (_) { result = { detail: raw.slice(0, 300) }; }
    if (!response.ok) throw new Error(toText(result.detail) || `${response.status} ${response.statusText}`);
    return result;
  }

  function startCreate(form) {
    if (state.busy) return;
    const data = new FormData(form);
    const name = String(data.get("name") || "").trim();
    const password = String(data.get("password") || "");
    const confirmation = String(data.get("confirm_password") || "");
    const error = form.querySelector("[data-create-error]");
    const components = selectedComponents();
    if (!name) { error.hidden = false; error.textContent = "Enter a backup name."; return; }
    if (!components.length) { error.hidden = false; error.textContent = "The selected backup type contains no detected data on this Cartman instance."; return; }
    if (password.length < 12) { error.hidden = false; error.textContent = "Use a password with at least 12 characters."; return; }
    if (password !== confirmation) { error.hidden = false; error.textContent = "Backup passwords do not match."; return; }
    // showSaveFilePicker must be invoked directly from the Start button gesture, before network work begins.
    const pickerPromise = typeof window.showSaveFilePicker === "function" ? chooseSaveHandle(name) : Promise.resolve(null);
    state.busy = true; render();
    (async () => {
      try {
        const handle = await pickerPromise;
        const result = await request(API, { method: "POST", body: JSON.stringify({ name, components, password, confirm_password: confirmation, bundle_type: state.mode === "full" ? "full" : "selective" }) });
        const item = result.item || {};
        const savedName = await saveBackupToMac(item.id, name, handle);
        state.notice = `Backup created and saved to the selected location as ${savedName}. Encrypted size: ${fmtSize(item.bytes)}.`;
        state.error = ""; state.tab = "history";
        await load();
      } catch (e) {
        if (e && e.name === "AbortError") state.notice = "Save location selection cancelled. No backup was created.";
        else state.error = toText(e.message || e) || "Backup creation or local save failed.";
      } finally { state.busy = false; render(); }
    })();
  }

  root.addEventListener("click", async event => {
    if (event.target.matches("[data-close-detail]")) { state.detail = null; render(); return; }
    if (event.target.matches("[data-close-unlock]")) { state.unlockId = ""; state.unlockError = ""; render(); return; }
    if (event.target.matches("[data-close-restore]")) { state.restoreId = ""; state.restoreManifest = null; render(); return; }
    const tab = event.target.closest("[data-tab]");
    if (tab && root.contains(tab)) { state.tab = tab.dataset.tab; state.error = ""; render(); return; }
    const mode = event.target.closest("[data-mode]");
    if (mode && root.contains(mode)) { state.mode = mode.dataset.mode; render(); return; }
    const button = event.target.closest("[data-action]");
    if (!button || !root.contains(button) || button.disabled) return;
    const action = button.dataset.action, id = button.dataset.id || "";
    if (action === "create") { state.mode = "full"; state.selective.clear(); state.tab = "create"; state.error = ""; state.notice = ""; render(); return; }
    if (action === "refresh") { await load(); return; }
    if (action === "choose-file") { root.querySelector("#bk5-local-file")?.click(); return; }
    if (action === "clear-file") { state.localFile = null; state.localPassword = ""; state.restorePassword = ""; render(); return; }
    if (action === "unlock") { state.unlockId = id; state.unlockPurpose = "details"; state.unlockError = ""; render(); return; }
    if (action === "close-unlock") { state.unlockId = ""; state.unlockError = ""; render(); return; }
    if (action === "close-detail") { state.detail = null; render(); return; }
    if (action === "download") {
      try { state.busy = true; render(); const name = await saveBackupToMac(id, `Cartman-${shortId(id)}`); state.notice = `Backup saved to the selected location as ${name}.`; }
      catch (e) { if (e.name !== "AbortError") state.error = toText(e.message || e); }
      finally { state.busy = false; render(); }
      return;
    }
    if (action === "open-restore") { state.restoreId = id; state.restoreManifest = state.detail?.manifest || null; render(); return; }
    if (action === "close-restore") { state.restoreId = ""; state.restoreManifest = null; render(); return; }
    if (action === "copy-command") {
      if (state.pending?.command && navigator.clipboard?.writeText) {
        try { await navigator.clipboard.writeText(state.pending.command); state.notice = "Restore command copied."; }
        catch (_) { state.error = "Clipboard unavailable. Copy the command manually."; }
      }
      render(); return;
    }
    if (action === "cancel-pending") {
      if (!window.confirm("Cancel the staged restore? Existing encrypted backups will remain untouched.")) return;
      try { await request(API + "/restore-pending", { method: "DELETE" }); state.notice = "Staged restore cancelled."; await load(); }
      catch (e) { state.error = toText(e.message || e); render(); }
    }
  });

  root.addEventListener("change", event => {
    const input = event.target;
    if (input.matches("[data-selective-option]")) {
      const id = input.dataset.selectiveOption;
      if (id === "database-only" && input.checked) state.selective = new Set(["database-only"]);
      else if (id === "database-only") state.selective.delete("database-only");
      else if (input.checked) { state.selective.delete("database-only"); state.selective.add(id); }
      else state.selective.delete(id);
      render(); return;
    }
    if (input.matches("#bk5-local-file")) {
      const file = input.files && input.files[0];
      state.localFile = file || null; state.localPassword = ""; state.error = "";
      if (file && !file.name.toLowerCase().endsWith(".cartmanbackup")) state.error = "Choose a .cartmanbackup file.";
      render(); return;
    }
  });

  root.addEventListener("input", event => {
    if (event.target.matches('#bk5-local-unlock-form input[name="password"]')) state.localPassword = event.target.value;
  });

  root.addEventListener("submit", async event => {
    if (event.target.id === "bk5-create-form") { event.preventDefault(); startCreate(event.target); return; }
    if (event.target.id === "bk5-local-unlock-form") {
      event.preventDefault();
      if (!state.localFile) return;
      const form = event.target, password = String(new FormData(form).get("password") || ""), error = form.querySelector("[data-local-unlock-error]");
      if (password.length < 12) { error.hidden = false; error.textContent = "Enter the backup password (at least 12 characters)."; return; }
      state.busy = true; render();
      try {
        const result = await importAndUnlock(state.localFile, password);
        state.detail = { backup: result.backup, manifest: result.manifest };
        state.restorePassword = password;
        state.localFile = null; state.localPassword = "";
        state.notice = "Backup unlocked. Password, AES-GCM, archive SHA-256 and per-file checksums passed.";
        await load(); state.tab = "recovery"; render();
      } catch (e) {
        state.error = toText(e.message || e) || "The file could not be unlocked.";
        state.busy = false; render();
      } finally { state.busy = false; }
      return;
    }
    if (event.target.id === "bk5-unlock-form") {
      event.preventDefault();
      const password = String(new FormData(event.target).get("password") || ""), id = state.unlockId;
      const submit = event.target.querySelector('button[type="submit"]');
      if (submit) { submit.disabled = true; submit.textContent = "Decrypting and verifying…"; }
      try {
        const result = await request(`${API}/${encodeURIComponent(id)}/unlock`, { method: "POST", body: JSON.stringify({ password }) });
        state.detail = result; state.restorePassword = password; state.unlockId = ""; state.unlockError = "";
        state.notice = "Backup unlocked. All integrity checks passed."; render();
      } catch (e) { state.unlockError = toText(e.message || e); render(); }
      return;
    }
    if (event.target.id === "bk5-restore-form") {
      event.preventDefault();
      const form = event.target, data = new FormData(form), components = data.getAll("components"), error = form.querySelector("[data-restore-error]");
      if (!components.length || !data.get("confirm") || !state.restorePassword) { error.hidden = false; error.textContent = "Select at least one item and confirm the restore warning."; return; }
      const db = components.filter(x => x.startsWith("db:"));
      if (db.includes("db:all") && db.length > 1) { error.hidden = false; error.textContent = "Full Database cannot be combined with individual database modules."; return; }
      const submit = form.querySelector('button[type="submit"]');
      if (submit) { submit.disabled = true; submit.textContent = "Verifying restore plan…"; }
      try {
        const result = await request(`${API}/${encodeURIComponent(state.restoreId)}/restore-prepare`, { method: "POST", body: JSON.stringify({ password: state.restorePassword || "", components }) });
        state.restoreId = ""; state.restoreManifest = null; state.detail = null; state.restorePassword = "";
        state.notice = result.message || "Restore prepared. Stop Cartman before applying the offline restore command.";
        state.tab = "recovery"; await load();
      } catch (e) { error.hidden = false; error.textContent = toText(e.message || e); if (submit) { submit.disabled = false; submit.textContent = "Verify & prepare restore"; } }
      render();
    }
  });

  // Store the unlock password only in memory while a restore modal is being prepared.
  const originalDetailModal = detailModal;
  const _unused = originalDetailModal;
  // Restore password is collected explicitly inside the restore dialog, not persisted by the server UI.
  load();
})();

/* CARTMAN_ROOT_UI_API_V1 */
