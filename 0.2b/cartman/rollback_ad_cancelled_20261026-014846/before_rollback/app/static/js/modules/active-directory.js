"use strict";

(() => {
  const API = "/api/network/ad";
  const $ = (selector, root = document) => root.querySelector(selector);
  const state = {
    targets: [],
    selectedId: "",
    report: null,
    inFlight: false,
    error: "",
    pullPreview: null,
    pullProgress: "",
    lastPull: null
  };

  const operations = [
    ["read_domain", "Read domain", "Domain and forest information"],
    ["read_ous", "Read OUs", "Organizational units"],
    ["read_users", "Read users", "User accounts and account state"],
    ["read_groups", "Read groups", "Directory groups"],
    ["read_computers", "Read computers", "Computer accounts"]
  ];
  const pending = ["Queued", "Running", "Dispatched"];

  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);

  const label = value => String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers
    });
    const type = response.headers.get("content-type") || "";
    const result = type.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error("Your Cartman session has expired. Sign in again.");
      }
      throw new Error(result && result.detail ? result.detail : `Request failed (${response.status}).`);
    }
    return result;
  }

  function note(message, kind = "") {
    const element = $("[data-ad-message]");
    if (!element) return;
    element.className = `nx-inline-note ${kind}`;
    element.textContent = message || "";
    element.hidden = !message;
  }

  function setConnection(text, connected) {
    const element = $(".nx-connection");
    if (!element) return;
    element.innerHTML = `<i></i> ${esc(text)}`;
    element.classList.toggle("is-connected", !!connected);
  }

  function setStats(targets) {
    const ready = targets.filter(target => target.ready).length;
    const online = targets.filter(target => target.status === "Online").length;
    const stats = [
      ["Windows targets", targets.length, "Registered Windows devices"],
      ["Ready", ready, "Approved clients with AD capability"],
      ["Online", online, "Connected Windows clients"],
      ["Read operations", "5", "Allowlisted, read-only queries"]
    ];

    const container = $(".nx-stats");
    if (!container) return;
    container.innerHTML = stats.map(([title, value, foot]) =>
      `<article class="nx-stat"><div class="nx-stat-label">${esc(title)}</div><strong>${esc(value)}</strong><span class="nx-stat-foot">${esc(foot)}</span></article>`
    ).join("");
  }

  function statusPill(value) {
    const safe = String(value || "Unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
    return `<span class="nx-status nx-status-${esc(safe)}">${esc(value || "Unknown")}</span>`;
  }

  function table(headers, rows, emptyMessage) {
    return `<div class="nx-table-wrap"><table class="nx-live-table"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${
      rows.length
        ? rows.map(row => `<tr>${row.map(cell => `<td>${cell == null ? "—" : cell}</td>`).join("")}</tr>`).join("")
        : `<tr><td class="nx-table-empty" colspan="${headers.length}">${esc(emptyMessage)}</td></tr>`
    }</tbody></table></div>`;
  }

  function panel(title, description, content, full = true) {
    return `<section class="nx-panel ${full ? "nx-full" : ""}">
      <div class="nx-panel-heading"><div><div class="nx-kicker">ACTIVE DIRECTORY</div>
      <h2>${esc(title)}</h2><p>${esc(description)}</p></div><span class="nx-pill">LIVE API</span></div>
      ${content}</section>`;
  }

  function renderTargets() {
    const targets = state.targets;
    const selected = targets.find(target => String(target.id) === String(state.selectedId));
    const ready = !!(selected && selected.ready);

    const targetRows = targets.map(target => [
      `<strong>${esc(target.name)}</strong>`,
      esc(target.ip || "—"),
      target.agent_registered ? statusPill("Registered") : statusPill("Unregistered"),
      statusPill(target.status),
      target.ad_management_enabled ? statusPill("Enabled") : statusPill("Disabled"),
      target.ready ? statusPill("Ready") : statusPill("Not ready")
    ]);

    const options = targets.map(target =>
      `<option value="${esc(target.id)}" ${String(target.id) === String(state.selectedId) ? "selected" : ""}>${esc(target.name)} · ${esc(target.ip || "No IP")}${target.ready ? " · Ready" : " · Not ready"}</option>`
    ).join("");

    const buttons = operations.map(([operation, title, description]) =>
      `<button type="button" class="nx-secondary" data-ad-read="${esc(operation)}" ${(!ready || state.inFlight) ? "disabled" : ""} title="${esc(description)}">${
        state.inFlight && state.report && state.report.operation === operation ? "Reading…" : esc(title)
      }</button>`
    ).join("");
    const pullButton = `<button type="button" class="nx-primary" data-ad-pull ${(!ready || state.inFlight || state.pullPreview) ? "disabled" : ""}>${state.inFlight && state.pullProgress ? "Pulling from AD…" : "Pull from AD"}</button>`;

    const currentTarget = selected
      ? `<div class="nx-inline-note ${ready ? "nx-good-note" : ""}">${
          ready
            ? "Selected Windows client is connected, approved, and has the dedicated AD capability enabled."
            : "This target is not ready. Its CartmanClient must be approved, online, and started with --enable-windows-ad-management."
        }</div>`
      : `<div class="nx-inline-note">No Windows target is registered yet.</div>`;

    const source = $(".nx-source-label");
    if (source) source.textContent = ready ? "AD CONNECTOR READY" : "WAITING FOR AD CONNECTOR";
    setConnection(ready ? "Active Directory client ready" : "Waiting for Windows AD client", ready);

    return panel(
      "Windows domain controller",
      "Choose a registered Windows CartmanClient. General remote task execution is not required.",
      `<div class="nx-form-grid"><label class="nx-field"><span>Windows target</span>
        <select data-ad-target ${targets.length ? "" : "disabled"}>${options || '<option value="">No Windows targets found</option>'}</select></label></div>
       <div class="nx-form-actions">${buttons}${pullButton}</div>${currentTarget}
       <div data-ad-message class="nx-inline-note" role="status" aria-live="polite" hidden></div>`
    ) + panel(
      "Windows targets",
      "Only approved and connected clients with the dedicated AD capability can run queries.",
      table(["Server", "IP", "Agent identity", "Connection", "AD capability", "Ready"], targetRows, "No Windows devices found.")
    ) + panel(
      "Read-only directory queries",
      "Queries use fixed, allowlisted PowerShell operations. No AD objects will be created, modified, or deleted.",
      `<div class="nx-capability-list">${operations.map(([operation, title, description], index) =>
        `<div class="nx-capability"><span class="nx-capability-mark">${String(index + 1).padStart(2, "0")}</span><span>${esc(title)}<small style="display:block;opacity:.7">${esc(description)}</small></span><span class="nx-capability-state">Read-only</span></div>`
      ).join("")}</div>`
    );
  }

  function renderReport() {
    const report = state.report;
    if (!report) {
      return panel(
        "Query results",
        "Results from the selected Windows Active Directory server appear here.",
        `<div class="nx-empty-state">Select a ready target and run a query. The connector returns a bounded sample, not a full directory export.</div>`
      );
    }

    const result = report.result && typeof report.result === "object" ? report.result : {};
    const data = result.data && typeof result.data === "object" ? result.data : {};
    const operation = report.operation || result.operation || "AD query";

    if (pending.includes(report.status)) {
      return panel(
        "Query running",
        `${operation} · ${report.device_name || "Windows target"}`,
        `<div class="nx-inline-note">Task ${esc(report.task_id || "—")} is ${esc(report.status)}. Keep the Windows CartmanClient online.</div>`
      );
    }

    if (report.status !== "Succeeded" || result.status !== "Succeeded") {
      return panel(
        "Query failed",
        `${operation} · ${report.device_name || "Windows target"}`,
        `<div class="nx-inline-note">${esc(result.error || report.error || report.result_text || "The server did not return a successful structured result.")}</div>`
      );
    }

    let content = "";
    const scalarKeys = [
      "domain", "domain_dn", "netbios_name", "forest", "domain_mode", "forest_mode"
    ];
    if (operation === "read_domain") {
      const scalarRows = scalarKeys
        .filter(key => data[key] !== undefined)
        .map(key => [esc(label(key)), esc(data[key] ?? "—")]);
      content += panel(
        "Domain and forest",
        "Metadata read from the Windows domain controller.",
        table(["Property", "Value"], scalarRows, "No domain metadata returned.")
      );

      const controllers = Array.isArray(data.domain_controllers) ? data.domain_controllers : [];
      const keys = [
        ["hostname", "Hostname"], ["site", "Site"], ["ipv4", "IPv4"],
        ["global_catalog", "Global catalog"], ["read_only", "Read-only"]
      ];
      content += panel(
        "Domain controllers",
        data.controllers_truncated ? "Bounded sample; additional controllers were omitted." : "Controllers returned by Active Directory.",
        table(keys.map(item => item[1]), controllers.map(item =>
          keys.map(([key]) => esc(item[key] ?? "—"))
        ), "No domain controllers returned.")
      );
    } else {
      const items = Array.isArray(data.items) ? data.items : [];
      const keys = {
        read_ous: ["name", "distinguished_name", "protected_from_deletion"],
        read_users: ["username", "display_name", "upn", "enabled", "department", "title", "distinguished_name"],
        read_groups: ["name", "sam_account_name", "category", "scope", "description", "distinguished_name"],
        read_computers: ["name", "dns_hostname", "operating_system", "ipv4_address", "enabled", "last_logon", "distinguished_name"]
      }[operation] || (items[0] ? Object.keys(items[0]) : []);

      content += panel(
        label(operation),
        `${items.length} record(s) returned${data.truncated ? " · more records omitted" : ""}.`,
        table(
          keys.map(label),
          items.map(item => keys.map(key => esc(item[key] ?? "—"))),
          "No records returned."
        )
      );
    }

    if (data.truncated || data.controllers_truncated) {
      content += `<div class="nx-inline-note">This is a bounded sample. Additional directory records were omitted.</div>`;
    }

    return panel(
      "Query result",
      `${operation} · ${report.device_name || "Windows target"}`,
      `<div class="nx-form-actions">${statusPill(result.status)}<span class="nx-source-label">Read-only · verified: ${esc(result.verified ? "Yes" : "No")}</span></div>${content}`
    );
  }


  function renderPullPanel() {
    if (state.inFlight && state.pullProgress) {
      return panel(
        "Pull from AD in progress",
        "Reading the full domain directory in bounded pages.",
        `<div class="nx-inline-note">${esc(state.pullProgress)}</div><div class="nx-inline-note">No Cartman directory data is changed until you review and confirm the pull.</div>`
      );
    }

    if (state.pullPreview) {
      const preview = state.pullPreview;
      const rows = Object.entries(preview.counts).map(([kind, count]) => [
        esc(label(kind)), esc(count)
      ]);
      return panel(
        "Review Pull from AD",
        `${preview.domain} · ${preview.records.length} object(s) collected`,
        `${table(["Object type", "Records to import"], rows, "No records collected.")}
         <div class="nx-inline-note">Confirming will insert new objects and update matching objectGUIDs in Cartman's separate AD mirror. It will not modify Active Directory, Cartman's native IAM users/groups, or delete objects missing from this pull.</div>
         <div class="nx-form-actions"><button type="button" class="nx-primary" data-ad-confirm-pull>Confirm Pull</button><button type="button" class="nx-secondary" data-ad-cancel-pull>Cancel</button></div>`
      );
    }

    if (state.lastPull) {
      const result = state.lastPull;
      const counts = result.counts_by_type || {};
      const rows = Object.entries(counts).map(([kind, value]) => [
        esc(label(kind)), esc(value.new || 0), esc(value.updated || 0), esc(value.total || 0)
      ]);
      return panel(
        "Pull completed",
        `${result.domain_dns} · ${result.total} object(s) synchronized`,
        `${table(["Object type", "New", "Updated", "Total"], rows, "No records returned.")}
         <div class="nx-inline-note nx-good-note">${esc(result.new)} new · ${esc(result.updated)} updated · 0 deletions. The AD mirror is separate from Cartman's native IAM directory.</div>
         <div class="nx-inline-note">${esc(result.note || "Objects not present in this pull were not deleted.")}</div>`
      );
    }

    return "";
  }

  async function readPullTask(operation, offset = 0) {
    const selected = state.targets.find(target => String(target.id) === String(state.selectedId));
    if (!selected || !selected.ready) throw new Error("Select a ready Windows AD target first.");
    const body = { device_id: selected.id, operation };
    if (operation.startsWith("pull_") && operation.endsWith("_page")) body.offset = offset;
    let task = await api(`${API}/connector/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    for (let attempt = 0; attempt < 45 && pending.includes(task.status); attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      task = await api(`${API}/connector/tasks/${encodeURIComponent(task.task_id)}`);
    }
    if (pending.includes(task.status)) {
      throw new Error(`${operation} is still pending. Keep HL-DC01 online and retry Pull from AD.`);
    }
    if (task.status !== "Succeeded" || task.result?.status !== "Succeeded") {
      throw new Error(task.result?.error || task.error || `${operation} failed.`);
    }
    return task.result;
  }

  async function runPullFromAD() {
    if (state.inFlight) return;
    const selected = state.targets.find(target => String(target.id) === String(state.selectedId));
    if (!selected || !selected.ready) {
      state.error = "Select a ready Windows AD target first.";
      render();
      return;
    }

    state.inFlight = true;
    state.error = "";
    state.pullProgress = "Reading domain and forest metadata…";
    state.pullPreview = null;
    state.lastPull = null;
    render();

    try {
      const domainResult = await readPullTask("read_domain");
      const domain = domainResult.data || {};
      if (!domain.domain) throw new Error("AD did not return the domain DNS name; pull cancelled.");

      const records = [];
      const counts = { ou: 0, user: 0, group: 0, computer: 0 };
      const jobs = [
        { operation: "pull_ous_page", type: "ou", title: "organizational units" },
        { operation: "pull_users_page", type: "user", title: "users" },
        { operation: "pull_groups_page", type: "group", title: "groups" },
        { operation: "pull_computers_page", type: "computer", title: "computers" }
      ];

      for (const job of jobs) {
        let offset = 0;
        let pageCount = 0;
        while (true) {
          state.pullProgress = `Reading ${job.title}: ${counts[job.type]} collected…`;
          render();
          const result = await readPullTask(job.operation, offset);
          const data = result.data || {};

          if (data.truncated) {
            throw new Error(
              `The ${job.title} page exceeded the client transport limit. ` +
              "Pull was not saved. Adjust the page size before retrying."
            );
          }

          const items = Array.isArray(data.items) ? data.items : [];
          if (!items.length && data.has_more) {
            throw new Error(`AD returned an empty page with more ${job.title} remaining. Pull was not saved.`);
          }
          for (const item of items) records.push({ ...item, object_type: job.type });
          counts[job.type] += items.length;
          if (records.length > 5000) {
            throw new Error("This first Pull implementation is limited to 5,000 objects per run; no records have been saved.");
          }
          if (!data.has_more) break;
          offset += items.length;
          pageCount += 1;
          if (pageCount > 1000 || !items.length) {
            throw new Error(`Pagination safety limit reached while reading ${job.title}. Pull was not saved.`);
          }
        }
      }

      if (!records.length) throw new Error("No OUs, users, groups, or computers were returned; nothing to import.");
      state.pullPreview = {
        device_id: selected.id,
        device_name: selected.name,
        domain: String(domain.domain),
        domain_metadata: {
          domain: domain.domain,
          domain_dn: domain.domain_dn || "",
          netbios_name: domain.netbios_name || "",
          forest: domain.forest || "",
          domain_mode: domain.domain_mode || "",
          forest_mode: domain.forest_mode || "",
          domain_controllers: Array.isArray(domain.domain_controllers) ? domain.domain_controllers : [],
          controllers_truncated: !!domain.controllers_truncated
        },
        records,
        counts
      };
      state.pullProgress = "";
    } catch (error) {
      state.error = error.message || String(error);
      state.pullProgress = "";
      state.pullPreview = null;
    } finally {
      state.inFlight = false;
      render();
    }
  }

  async function confirmPullFromAD() {
    if (state.inFlight || !state.pullPreview) return;
    const preview = state.pullPreview;
    state.inFlight = true;
    state.pullProgress = "Saving the reviewed snapshot to Cartman's AD mirror…";
    state.error = "";
    render();
    try {
      const result = await api(`${API}/sync/pull/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: preview.device_id,
          domain_metadata: preview.domain_metadata,
          records: preview.records
        })
      });
      state.lastPull = result;
      state.pullPreview = null;
      state.pullProgress = "";
    } catch (error) {
      state.error = error.message || String(error);
      state.pullProgress = "";
    } finally {
      state.inFlight = false;
      render();
    }
  }

  function cancelPullFromAD() {
    state.pullPreview = null;
    state.pullProgress = "";
    state.error = "";
    render();
  }

  function render() {
    const content = $("[data-nx-content]");
    if (!content) return;
    content.innerHTML = renderTargets() + renderReport() + renderPullPanel();
    if (state.error) note(state.error, "");
    const query = $("[data-nx-search]")?.value.trim().toLowerCase() || "";
    if (query) {
      content.querySelectorAll("tbody tr").forEach(row => {
        row.hidden = !row.textContent.toLowerCase().includes(query);
      });
    }
  }

  async function loadTargets() {
    try {
      state.targets = await api(`${API}/targets`);
      if (!state.targets.some(target => String(target.id) === String(state.selectedId))) {
        state.selectedId = (state.targets.find(target => target.ready) || state.targets[0] || {}).id || "";
      }
      state.error = "";
      setStats(state.targets);
      render();
    } catch (error) {
      state.error = error.message || String(error);
      setConnection("API connection error", false);
      const content = $("[data-nx-content]");
      if (content) {
        content.innerHTML = panel(
          "Could not load Active Directory targets",
          "The Cartman API returned an error.",
          `<div class="nx-inline-note">${esc(state.error)}</div><button type="button" class="nx-primary" data-ad-refresh>Retry</button>`
        );
      }
    }
  }

  async function runRead(operation) {
    if (state.inFlight) return;
    const selected = state.targets.find(target => String(target.id) === String(state.selectedId));
    if (!selected || !selected.ready) {
      state.error = "Select a ready Windows AD target first.";
      note(state.error);
      return;
    }

    state.inFlight = true;
    state.error = "";
    render();

    try {
      let task = state.report;
      if (!task || String(task.device_id) !== String(selected.id)
          || task.operation !== operation || !pending.includes(task.status)) {
        task = await api(`${API}/connector/read`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ device_id: selected.id, operation })
        });
        state.report = task;
      }

      render();
      for (let attempt = 0; attempt < 45 && pending.includes(task.status); attempt++) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        task = await api(`${API}/connector/tasks/${encodeURIComponent(task.task_id)}`);
        state.report = task;
        render();
      }

      if (pending.includes(task.status)) {
        note("Task is still pending. Press the same query again to resume it without creating a duplicate.", "");
      } else if (task.status === "Succeeded" && task.result?.status === "Succeeded") {
        note(`${operation} completed on ${task.device_name}. Directory data was read only.`, "nx-good-note");
      } else {
        note(task.result?.error || task.error || "Active Directory query failed.", "");
      }
    } catch (error) {
      state.error = error.message || String(error);
      if (/session has expired/i.test(state.error)) {
        window.location.assign("/static/login.html");
        return;
      }
      note(state.error);
    } finally {
      state.inFlight = false;
      render();
      if (state.error) note(state.error);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const heroKicker = $(".nx-hero .nx-kicker");
    if (heroKicker) heroKicker.innerHTML = '<span class="nx-hero-icon">♙</span>IDENTITY SERVICES / ACTIVE DIRECTORY';

    const heroTags = $(".nx-hero-tags");
    if (heroTags) {
      heroTags.innerHTML = "<span><i></i> Live connector</span><span>Read-only queries</span><span>Windows Server</span>";
    }

    const search = $("[data-nx-search]");
    if (search) search.addEventListener("input", () => render());

    document.addEventListener("change", event => {
      const target = event.target.closest("[data-ad-target]");
      if (!target) return;
      state.selectedId = target.value;
      state.report = null;
      render();
    });

    document.addEventListener("click", async event => {
      const read = event.target.closest("[data-ad-read]");
      if (read) {
        event.preventDefault();
        await runRead(read.dataset.adRead);
        return;
      }
      if (event.target.closest("[data-ad-pull]")) {
        event.preventDefault();
        await runPullFromAD();
        return;
      }
      if (event.target.closest("[data-ad-confirm-pull]")) {
        event.preventDefault();
        await confirmPullFromAD();
        return;
      }
      if (event.target.closest("[data-ad-cancel-pull]")) {
        event.preventDefault();
        cancelPullFromAD();
        return;
      }
      if (event.target.closest("[data-ad-refresh]")) {
        await loadTargets();
      }
    });

    loadTargets();
  });
})();
