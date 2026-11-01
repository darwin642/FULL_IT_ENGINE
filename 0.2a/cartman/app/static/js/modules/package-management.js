"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const form = $("#aps-form");
  if (!form) return;

  const panels = $$("[data-aps-panel]");
  const steps = $$("[data-aps-tab]");
  const titles = {
    identity: ["STEP 01 / IDENTITY", "Package identity", "Describe the application and its source installer."],
    commands: ["STEP 02 / COMMANDS", "Install & uninstall", "Define command metadata and expected exit codes."],
    detection: ["STEP 03 / DETECTION", "Detection rules", "Describe how a future agent can verify installation."],
    dependencies: ["STEP 04 / REQUIREMENTS", "Dependencies & transforms", "Document prerequisites, transforms and constraints."],
    review: ["STEP 05 / REVIEW", "Validate & export", "Run local configuration checks and export the manifest."]
  };
  const order = Object.keys(titles);
  let current = "identity";
  let drafts = [];
  let validated = false;

  function values() {
    const data = {};
    for (const [key, value] of new FormData(form).entries()) data[key] = String(value).trim();
    return data;
  }

  function manifest() {
    const v = values();
    return {
      schema: "cartman.package-manifest",
      schema_version: 1,
      package: {
        id: v.package_id || null,
        name: v.name || null,
        publisher: v.publisher || null,
        version: v.version || null,
        revision: Number(v.revision || 1),
        architecture: v.architecture,
        target_os: v.target_os,
        category: v.category,
        description: v.description || null
      },
      source: {
        installer_type: v.installer_type,
        path_reference: v.source_path || null,
        file_uploaded: false
      },
      installation: {
        install_command: v.install_command || null,
        uninstall_command: v.uninstall_command || null,
        execution_context: v.context,
        restart_behavior: v.restart_behavior,
        success_exit_codes: parseCodes(v.success_codes),
        reboot_required_exit_codes: parseCodes(v.reboot_codes),
        notes: v.command_notes || null
      },
      detection: {
        method: v.detection_method,
        target: v.detection_target || null,
        operator: v.detection_operator,
        expected_value: v.detection_value || null,
        registry_hive: v.registry_hive || null,
        notes: v.detection_notes || null
      },
      requirements: {
        dependencies: (v.dependencies || "").split(/\r?\n/).map(x => x.trim()).filter(Boolean),
        mst_path_reference: v.mst_path || null,
        minimum_disk_space_mb: v.disk_mb === "" ? null : Number(v.disk_mb),
        constraints: v.requirements || null
      },
      metadata: {
        created_by: "local-browser-session",
        build_status: "not_built",
        signature_status: "not_checked",
        runtime_test_status: "not_performed"
      }
    };
  }

  function parseCodes(raw) {
    return String(raw || "").split(",").map(x => x.trim()).filter(Boolean).map(x => {
      const n = Number(x);
      return Number.isInteger(n) ? n : x;
    });
  }

  function setTab(tab) {
    if (!titles[tab]) return;
    current = tab;
    panels.forEach(p => p.classList.toggle("active", p.dataset.apsPanel === tab));
    steps.forEach(s => {
      s.classList.toggle("active", s.dataset.apsTab === tab);
      s.setAttribute("aria-current", s.dataset.apsTab === tab ? "step" : "false");
    });
    const t = titles[tab];
    $("#aps-section-kicker").textContent = t[0];
    $("#aps-section-title").textContent = t[1];
    $("#aps-section-description").textContent = t[2];
    $("#aps-back").disabled = order.indexOf(tab) === 0;
    $("#aps-next").textContent = tab === "review" ? "Export manifest JSON" : "Next step";
    if (tab === "review") renderPreview();
  }

  function say(message, error = false) {
    $("#aps-feedback").textContent = message;
    $("#aps-feedback").style.color = error ? "#fca5a5" : "";
  }

  function validate() {
    const v = values();
    const checks = [];
    const add = (ok, title, detail, warn = false) => checks.push({ok, title, detail, warn});
    add(!!v.name, "Application name", v.name ? "Name is provided." : "Enter an application name.", !v.name);
    add(!!v.version, "Version", v.version ? "Version is provided." : "Enter a version.", !v.version);
    add(!!v.source_path, "Source reference", v.source_path ? "A source path/reference is recorded; the file itself was not inspected." : "No source installer reference is provided.", !v.source_path);
    add(!!v.install_command, "Install command", v.install_command ? "Command metadata is present; it has not been executed." : "Install command is not configured.", !v.install_command);
    add(!!v.uninstall_command, "Uninstall command", v.uninstall_command ? "Uninstall metadata is present." : "Uninstall command is not configured.", !v.uninstall_command);
    add(!!v.detection_target, "Detection target", v.detection_target ? "Detection target is recorded." : "Detection target is missing.", !v.detection_target);
    add(v.success_codes.split(",").every(x => x.trim() === "" || /^-?\d+$/.test(x.trim())), "Exit code format", "Success exit codes must be comma-separated integers.");
    add(v.reboot_codes.split(",").every(x => x.trim() === "" || /^-?\d+$/.test(x.trim())), "Reboot exit code format", "Reboot-required exit codes must be comma-separated integers.");
    add(v.installer_type !== "MSI" || !v.mst_path || v.mst_path.toLowerCase().endsWith(".mst"), "MSI transform reference", "If provided for MSI, the transform reference should end in .mst.", !!v.mst_path && v.installer_type === "MSI" && !v.mst_path.toLowerCase().endsWith(".mst"));
    add(true, "Binary and signature checks", "Not performed: a packaging engine is not connected.");
    const container = $("#aps-validation-results");
    container.replaceChildren();
    for (const item of checks) {
      const row = document.createElement("div");
      row.className = "aps-validation-item " + (item.ok ? "ok" : "warn");
      const mark = document.createElement("span");
      mark.textContent = item.ok ? (item.warn ? "!" : "✓") : "!";
      const body = document.createElement("div");
      const title = document.createElement("b");
      title.textContent = item.title;
      const detail = document.createElement("p");
      detail.textContent = item.detail;
      body.append(title, detail);
      row.append(mark, body);
      container.appendChild(row);
    }
    validated = true;
    const hardErrors = checks.filter(x => !x.ok).length;
    $("#aps-validation").textContent = hardErrors ? "Review needed" : "Checked";
    $("#aps-manifest-preview").textContent = JSON.stringify(manifest(), null, 2);
    say(hardErrors ? `${hardErrors} validation issue(s) need attention.` : "Local checks complete. Binary validation was not performed.", hardErrors > 0);
    return hardErrors === 0;
  }

  function renderPreview() {
    $("#aps-manifest-preview").textContent = JSON.stringify(manifest(), null, 2);
  }

  function saveDraft() {
    const v = values();
    if (!v.name || !v.version) {
      say("Application name and version are required to save a draft.", true);
      setTab(!v.name ? "identity" : "identity");
      form.elements.namedItem(!v.name ? "name" : "version").focus();
      return;
    }
    const data = manifest();
    const id = v.package_id || [v.name, v.version, Date.now()].join("-");
    const existing = drafts.findIndex(x => x.id === id);
    const entry = {id, name: v.name, version: v.version, data};
    if (existing >= 0) drafts[existing] = entry;
    else drafts.push(entry);
    $("#aps-count").textContent = String(drafts.length);
    $("#aps-current").textContent = "Draft saved";
    renderDrafts();
    say("Draft saved in this page session.");
  }

  function renderDrafts() {
    const list = $("#aps-saved-list");
    list.replaceChildren();
    if (!drafts.length) {
      const empty = document.createElement("div");
      empty.className = "aps-saved-empty";
      empty.textContent = "No manifests saved in this session.";
      list.appendChild(empty);
      return;
    }
    for (const draft of drafts) {
      const row = document.createElement("div");
      row.className = "aps-saved-item";
      const info = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = draft.name;
      const meta = document.createElement("small");
      meta.textContent = `Version ${draft.version} · Manifest only`;
      info.append(name, meta);
      const actions = document.createElement("div");
      actions.className = "aps-saved-actions";
      const load = document.createElement("button");
      load.type = "button";
      load.textContent = "Load";
      load.addEventListener("click", () => loadDraft(draft));
      const download = document.createElement("button");
      download.type = "button";
      download.textContent = "Export JSON";
      download.addEventListener("click", () => downloadManifest(draft.data, draft.name, draft.version));
      actions.append(load, download);
      row.append(info, actions);
      list.appendChild(row);
    }
  }

  function loadDraft(draft) {
    const d = draft.data;
    const p = d.package || {}, s = d.source || {}, i = d.installation || {}, det = d.detection || {}, r = d.requirements || {};
    const mapped = {
      package_id:p.id, name:p.name, publisher:p.publisher, version:p.version, revision:p.revision,
      architecture:p.architecture, target_os:p.target_os, category:p.category, description:p.description,
      installer_type:s.installer_type, source_path:s.path_reference,
      install_command:i.install_command, uninstall_command:i.uninstall_command, context:i.execution_context,
      restart_behavior:i.restart_behavior, success_codes:(i.success_exit_codes || []).join(", "),
      reboot_codes:(i.reboot_required_exit_codes || []).join(", "), command_notes:i.notes,
      detection_method:det.method, detection_target:det.target, detection_operator:det.operator,
      detection_value:det.expected_value, registry_hive:det.registry_hive, detection_notes:det.notes,
      dependencies:(r.dependencies || []).join("\n"), mst_path:r.mst_path_reference,
      disk_mb:r.minimum_disk_space_mb, requirements:r.constraints
    };
    for (const [key, value] of Object.entries(mapped)) {
      const field = form.elements.namedItem(key);
      if (field && value !== null && value !== undefined) field.value = String(value);
    }
    validated = false;
    $("#aps-current").textContent = "Draft loaded";
    setTab("identity");
    say("Draft loaded into the editor.");
  }

  function downloadManifest(data, name, version) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${String(name || "package").replace(/[^a-z0-9._-]+/gi, "-")}-${String(version || "0").replace(/[^a-z0-9._-]+/gi, "-")}.manifest.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    say("Manifest JSON exported. This is not an installer binary.");
  }

  steps.forEach(s => s.addEventListener("click", () => setTab(s.dataset.apsTab)));
  $("#aps-back").addEventListener("click", () => setTab(order[Math.max(0, order.indexOf(current) - 1)]));
  $("#aps-next").addEventListener("click", () => {
    if (current !== "review") {
      setTab(order[Math.min(order.length - 1, order.indexOf(current) + 1)]);
      return;
    }
    if (!validate()) return;
    if (!$("#aps-review-ack").checked) {
      say("Please confirm you understand this export is a manifest, not a built installer.", true);
      return;
    }
    downloadManifest(manifest(), values().name || "package", values().version || "0");
  });
  $("#aps-save").addEventListener("click", saveDraft);
  $("#aps-clear").addEventListener("click", () => {
    drafts = [];
    $("#aps-count").textContent = "0";
    $("#aps-current").textContent = "Draft";
    renderDrafts();
    say("Session drafts cleared.");
  });
  form.addEventListener("input", () => {
    validated = false;
    $("#aps-current").textContent = "Unsaved changes";
    if (current === "review") renderPreview();
  });
  form.addEventListener("submit", event => event.preventDefault());

  renderDrafts();
  setTab("identity");
})();
