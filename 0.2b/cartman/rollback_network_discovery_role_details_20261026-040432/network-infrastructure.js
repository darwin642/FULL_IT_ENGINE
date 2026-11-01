"use strict";

/* Cartman Network & Infrastructure: live, SQLite-backed workspaces. */
(() => {
  const API = "/api/network";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const state = { slug: "", data: null, error: "", selectedDiscoveryId: "", discoveryDetails: {}, lastLoadedAt: null, dhcpConnectorReport: null, selectedDhcpTargetId: "", dhcpChangePlan: null, dhcpChangeTask: null, dhcpReadInFlight: "", dhcpConnectorSubsystem: "" };

  const pages = {
    network: { title: "Network", stats: [["Network devices", "—", "Inventory records"], ["Online devices", "—", "Reported online"], ["IP subnets", "—", "Managed address spaces"], ["Discovery jobs", "—", "Saved discovery history"]] },
    "network-devices": { title: "Network Devices", stats: [["Total devices", "—", "Network inventory"], ["Online", "—", "Reported online"], ["Needs review", "—", "Warning or unknown status"], ["Last seen", "—", "Last recorded online status"]] },
    "network-discovery": { title: "Network Discovery", stats: [["Discovery jobs", "—", "Saved jobs"], ["Hosts found", "—", "Responsive hosts only"], ["Ranges scanned", "—", "Unique CIDR ranges"], ["Last scan", "—", "Most recent job"]] },
    "network-topology": { title: "Network Topology", stats: [["Devices", "—", "Network inventory"], ["Links", "—", "Recorded connections"], ["Up links", "—", "Reported as up"], ["Planned links", "—", "Not yet confirmed"]] },
    "ip-address-management": { title: "IP Address Management", stats: [["Subnets", "—", "Managed networks"], ["IP records", "—", "Recorded addresses"], ["Assigned", "—", "Addresses in use"], ["Available", "—", "Explicitly marked available"]] },
    "dns-dhcp": { title: "DNS & DHCP", stats: [["DNS records", "—", "Cartman registry"], ["Active DNS", "—", "Enabled records"], ["DHCP scopes", "—", "Managed scope records"], ["Leases", "—", "Recorded leases"]] },
    "network-diagnostics": { title: "Network Diagnostics", stats: [["Tests run", "—", "Saved test history"], ["Succeeded", "—", "Successful tests"], ["Failed", "—", "Failed tests"], ["Average latency", "—", "Recorded test duration"]] },
    infrastructure: { title: "Infrastructure", stats: [["Server profiles", "—", "Profiles on existing devices"], ["Network devices", "—", "Managed network equipment"], ["Topology links", "—", "Recorded connections"], ["Capacity records", "—", "Stored readings"]] },
    "servers-infrastructure": { title: "Servers & Infrastructure", stats: [["Server profiles", "—", "Linked to Cartman devices"], ["Critical", "—", "Marked critical"], ["Online", "—", "Source device status"], ["Dependencies", "—", "Recorded relationships"]] },
    "capacity-management": { title: "Capacity Management", stats: [["Metric records", "—", "Telemetry + manual readings"], ["Live telemetry", "—", "Existing monitoring metrics"], ["Manual entries", "—", "Clearly labelled manual data"], ["Plans", "—", "Capacity planning items"]] }
  };

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const val = (obj, key, fallback = "—") => obj && obj[key] !== undefined && obj[key] !== null && obj[key] !== "" ? obj[key] : fallback;
  const fmtDate = value => value ? String(value).replace("T", " ").replace(/\.\d+.*$/, "").slice(0, 19) : "—";
  const short = value => {
    if (!value) return "—";
    const text = String(value);
    return text.length > 38 ? `${text.slice(0, 35)}…` : text;
  };
  const opt = (value, label, selected = false) => `<option value="${esc(value)}" ${selected ? "selected" : ""}>${esc(label)}</option>`;
  const options = (items, valueKey, labelFn, chosen = "") => items.map(item => opt(item[valueKey], labelFn(item), item[valueKey] === chosen)).join("");

  function panel(title, description, content, full = false, kicker = "LIVE WORKSPACE") {
    return `<section class="nx-panel ${full ? "nx-full" : ""}"><div class="nx-panel-heading"><div><div class="nx-kicker">${esc(kicker)}</div><h2>${esc(title)}</h2><p>${esc(description)}</p></div><span class="nx-pill">LIVE API</span></div>${content}</section>`;
  }

  function field(label, name, placeholder = "", type = "text", extra = "") {
    return `<label class="nx-field"><span>${esc(label)}</span><input name="${esc(name)}" type="${esc(type)}" placeholder="${esc(placeholder)}" ${extra}></label>`;
  }
  function selectField(label, name, optionHtml, extra = "") {
    return `<label class="nx-field"><span>${esc(label)}</span><select name="${esc(name)}" ${extra}>${optionHtml}</select></label>`;
  }
  function areaField(label, name, placeholder = "", rows = 2) {
    return `<label class="nx-field nx-field-wide"><span>${esc(label)}</span><textarea name="${esc(name)}" rows="${rows}" placeholder="${esc(placeholder)}"></textarea></label>`;
  }
  function hiddenId() { return `<input type="hidden" name="id" value="">`; }
  function submitRow(label = "Save record") { return `<div class="nx-form-actions"><button class="nx-primary" type="submit">${esc(label)}</button><button class="nx-secondary" type="reset">Clear</button></div>`; }
  function formPanel(title, description, name, fieldsHtml, submitLabel) {
    return panel(title, description, `<form class="nx-live-form" data-form="${esc(name)}">${hiddenId()}<div class="nx-form-grid">${fieldsHtml}</div>${submitRow(submitLabel)}</form>`);
  }
  function actions(id, edit, remove, label = "record") {
    let html = `<div class="nx-row-actions">`;
    if (edit) html += `<button type="button" class="nx-text-button" data-edit="${esc(edit)}" data-id="${esc(id)}">Edit</button>`;
    if (remove) html += `<button type="button" class="nx-text-button nx-danger-button" data-delete="${esc(remove)}" data-id="${esc(id)}" data-label="${esc(label)}">Delete</button>`;
    return html + `</div>`;
  }
  function table(headers, rows, emptyMessage = "No records yet.", full = true) {
    const head = headers.map(h => `<th>${esc(h)}</th>`).join("");
    const body = rows.length ? rows.map(row => `<tr>${row.map(cell => `<td>${cell === null || cell === undefined ? "—" : cell}</td>`).join("")}</tr>`).join("") : `<tr><td class="nx-table-empty" colspan="${headers.length}">${esc(emptyMessage)}</td></tr>`;
    return `<div class="nx-table-wrap"><table class="nx-live-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }
  function statCard(label, value, foot) { return { label, value: value ?? "—", foot: foot || "Current API data" }; }
  function setStats(items) {
    const cards = $$(".nx-stat");
    items.slice(0, cards.length).forEach((item, i) => {
      const card = cards[i];
      const label = $(".nx-stat-label", card);
      const strong = $("strong", card);
      const foot = $(".nx-stat-foot", card);
      if (label) label.textContent = item.label;
      if (strong) strong.textContent = item.value === null || item.value === undefined ? "—" : String(item.value);
      if (foot) foot.textContent = item.foot || "Current API data";
    });
  }
  function setConnection(connected) {
    const connection = $(".nx-connection");
    const source = $(".nx-source-label");
    if (connection) {
      connection.innerHTML = `<i class="${connected ? "nx-live-dot" : "nx-dead-dot"}"></i>${connected ? "Cartman API connected" : "API connection failed"}`;
    }
    if (source) {
      source.innerHTML = `<i class="${connected ? "nx-live-dot" : "nx-dead-dot"}"></i>${connected ? "CARTMAN API LIVE" : "API UNAVAILABLE"}`;
    }
    const tags = $(".nx-hero-tags");
    if (tags && connected) tags.innerHTML = `<span><i class="nx-live-dot"></i> Live Cartman API</span><span>SQLite-backed records</span><span>External provider connector may be required</span>`;
    const footer = $(".nx-footer");
    if (footer && connected) footer.innerHTML = `<span><b>C</b> Cartman Infrastructure Management</span><span>API connected <i class="nx-live-dot"></i> Changes persist to SQLite</span>`;
  }
  function notify(message, kind = "info") {
    let box = $("[data-nx-feedback]");
    if (!box) {
      box = document.createElement("div");
      box.className = "nx-feedback";
      box.dataset.nxFeedback = "";
      box.setAttribute("role", "status");
      const toolbar = $(".nx-toolbar");
      if (toolbar) toolbar.insertAdjacentElement("afterend", box);
    }
    box.className = `nx-feedback nx-feedback-${kind}`;
    box.textContent = message;
    box.hidden = false;
  }
  function notifyClear() {
    const box = $("[data-nx-feedback]");
    if (box) box.hidden = true;
  }

  async function api(path, options = {}) {
    const init = { method: options.method || "GET", headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) } };
    if (options.body) init.body = JSON.stringify(options.body);
    const response = await fetch(path, init);
    let result;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) result = await response.json();
    else result = await response.text();
    if (!response.ok) {
      const detail = result && typeof result === "object" ? result.detail : result;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return result;
  }

  function statsForPage(data) {
    const slug = state.slug;
    if (slug === "network") {
      const d = data.devices || {}, i = data.ipam || {}, ds = data.discovery || {};
      return [statCard("Network devices", d.total, "Inventory records"), statCard("Online devices", d.online, "Reported online"), statCard("IP subnets", i.subnets, "Managed address spaces"), statCard("Discovery jobs", ds.jobs, `${ds.running || 0} currently queued/running`)];
    }
    if (slug === "network-devices") {
      const list = data || [];
      return [statCard("Total devices", list.length, "Network inventory"), statCard("Online", list.filter(x => x.status === "Online").length, "Reported online"), statCard("Needs review", list.filter(x => ["Warning", "Unknown"].includes(x.status)).length, "Warning or unknown status"), statCard("Last seen", fmtDate(list.map(x => x.last_seen).filter(Boolean).sort().reverse()[0]), "Most recent recorded online status")];
    }
    if (slug === "network-discovery") {
      const list = data || [];
      return [statCard("Discovery jobs", list.length, "Saved job history"), statCard("Hosts found", list.reduce((n, x) => n + Number(x.hosts_found || 0), 0), "Responsive common TCP services"), statCard("Ranges scanned", new Set(list.map(x => x.cidr)).size, "Unique CIDR ranges"), statCard("Last scan", fmtDate(list[0]?.completed_at || list[0]?.created_at), "Most recent job")];
    }
    if (slug === "network-topology") {
      const links = data.links || [];
      return [statCard("Devices", (data.devices || []).length, "Network inventory"), statCard("Links", links.length, "Recorded connections"), statCard("Up links", links.filter(x => x.status === "Up").length, "Reported as up"), statCard("Planned links", links.filter(x => x.status === "Planned").length, "Not yet confirmed")];
    }
    if (slug === "ip-address-management") {
      const subnets = data.subnets || [], addresses = data.addresses || [];
      return [statCard("Subnets", subnets.length, "Managed networks"), statCard("IP records", addresses.length, "Recorded addresses"), statCard("Assigned", addresses.filter(x => x.status === "Assigned").length, "Addresses in use"), statCard("Available", addresses.filter(x => x.status === "Available").length, "Explicitly marked available")];
    }
    if (slug === "dns-dhcp") {
      const d = data.dns || [], s = data.scopes || [], l = data.leases || [];
      return [statCard("DNS records", d.length, "Cartman registry"), statCard("Active DNS", d.filter(x => x.status === "Active").length, "Enabled records"), statCard("DHCP scopes", s.length, "Managed scope records"), statCard("Leases", l.length, "Recorded leases")];
    }
    if (slug === "network-diagnostics") {
      const list = data || [], succeeded = list.filter(x => x.status === "Succeeded").length;
      const times = list.map(x => Number(x.response_ms)).filter(Number.isFinite);
      return [statCard("Tests run", list.length, "Saved test history"), statCard("Succeeded", succeeded, "Successful tests"), statCard("Failed", list.filter(x => x.status === "Failed").length, "Failed tests"), statCard("Average latency", times.length ? `${Math.round(times.reduce((a, b) => a + b, 0) / times.length)} ms` : "—", "Recorded test duration")];
    }
    if (slug === "infrastructure") {
      const o = data.overview || {};
      const cap = data.capacity || {};
      const devices = data.cartmanDevices || [];
      const assets = data.inventoryAssets || [];
      return [
        statCard("Managed devices", devices.length, "Existing Cartman Devices API"),
        statCard("Inventory assets", assets.length, "Existing Cartman Inventory API"),
        statCard("Network equipment", (o.devices || {}).total ?? 0, "Dedicated network inventory"),
        statCard("Capacity records", cap.record_count ?? 0, "Telemetry + manual readings")
      ];
    }
    if (slug === "servers-infrastructure") {
      const servers = data.servers || [], deps = data.dependencies || [];
      return [statCard("Server profiles", servers.length, "Linked to Cartman devices"), statCard("Critical", servers.filter(x => x.criticality === "Critical").length, "Marked critical"), statCard("Online", servers.filter(x => x.status === "Online").length, "Source device status"), statCard("Dependencies", deps.length, "Recorded relationships")];
    }
    if (slug === "capacity-management") {
      return [statCard("Metric records", data.record_count, "Telemetry + manual readings"), statCard("Live telemetry", data.telemetry_count, "Existing monitoring metrics"), statCard("Manual entries", data.manual_count, "Clearly labelled manual data"), statCard("Plans", (data.plans || []).length, "Capacity planning items")];
    }
    return [];
  }

  async function loadData() {
    switch (state.slug) {
      case "network": return api(`${API}/overview`);
      case "network-devices": return api(`${API}/devices`);
      case "network-discovery": return api(`${API}/discovery/jobs`);
      case "network-topology": return api(`${API}/topology/links`);
      case "ip-address-management": return api(`${API}/ipam`);
      case "dns-dhcp": {
        const [dns, scopes, leases, connectorTargets] = await Promise.all([
          api(`${API}/dns/records`),
          api(`${API}/dhcp/scopes`),
          api(`${API}/dhcp/leases`),
          api("/api/network/dns-dhcp/targets")
        ]);
        return { dns, scopes, leases, connectorTargets };
      }
      case "network-diagnostics": return api(`${API}/diagnostics/history`);
      case "infrastructure": {
        const [overview, servers, capacity, cartmanDevices, inventoryAssets] = await Promise.all([
          api(`${API}/overview`),
          api(`${API}/servers`),
          api(`${API}/capacity`),
          api("/api/devices"),
          api("/api/inventory")
        ]);
        return { overview, servers, capacity, cartmanDevices, inventoryAssets };
      }
      case "servers-infrastructure": return api(`${API}/servers`);
      case "capacity-management": {
        const [capacity, devices] = await Promise.all([api(`${API}/capacity`), api("/api/devices").catch(() => [])]);
        capacity.devices = devices;
        return capacity;
      }
      default: throw new Error(`Unknown Network & Infrastructure page: ${state.slug}`);
    }
  }

  function tableActionButtons(kind, id, edit = true, del = true, label = "record") {
    return actions(id, edit ? kind : "", del ? kind : "", label);
  }
  function statusPill(status) {
    const cls = String(status || "Unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
    return `<span class="nx-status nx-status-${esc(cls)}">${esc(status || "Unknown")}</span>`;
  }

  function renderNetwork(data) {
    const d = data.devices || {}, ipam = data.ipam || {}, dd = data.dns_dhcp || {}, disc = data.discovery || {}, diag = data.diagnostics || {}, infra = data.infrastructure || {};
    const summary = [
      ["Network inventory", d.total || 0, `${d.online || 0} devices online`],
      ["IP address space", ipam.subnets || 0, `${ipam.addresses || 0} IP records`],
      ["DNS & DHCP", dd.dns_records || 0, `${dd.dhcp_scopes || 0} active scope records`],
      ["Discovery & diagnostics", disc.jobs || 0, `${diag.runs || 0} diagnostic tests recorded`],
      ["Topology", data.topology?.links || 0, "Saved device-to-device links"],
      ["Infrastructure", infra.server_profiles || 0, `${infra.capacity_telemetry_count || 0} telemetry · ${infra.capacity_manual_count || 0} manual entries`]
    ].map(([label, value, note]) => `<div class="nx-summary-tile"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join("");
    const devices = (d.items || []).map(x => [esc(x.hostname), esc(x.device_type), esc(x.management_ip || "—"), esc(x.vendor || "—"), statusPill(x.status), esc(fmtDate(x.last_seen))]);
    const jobs = (disc.recent || []).map(x => [esc(x.cidr), statusPill(x.status), esc(x.hosts_found), esc(fmtDate(x.created_at))]);
    return panel("Network workspace", "Live summary across network inventory, IPAM, DNS/DHCP, discovery, topology, and capacity.", `<div class="nx-summary-grid">${summary}</div>`, true)
      + panel("Recent network devices", "Records stored in Cartman's network inventory.", table(["Hostname", "Type", "Management IP", "Vendor", "Status", "Last seen"], devices, "No network devices have been registered yet."), true)
      + panel("Recent discovery jobs", "Discovery only probes confirmed private IPv4 ranges using common TCP ports.", table(["CIDR", "Status", "Responsive hosts", "Created"], jobs, "No discovery jobs yet. Run a confirmed discovery from Network Discovery."), true);
  }

  function renderNetworkDevices(data) {
    const list = data || [];
    const fields = field("Hostname *", "hostname", "sw-core-01", "text", "required")
      + selectField("Device type", "device_type", ["Unclassified", "Switch", "Router", "Firewall", "Wireless Access Point", "Controller", "Load Balancer", "Other"].map(x => opt(x, x, x === "Switch")).join(""))
      + field("Management IP", "management_ip", "192.168.1.2", "text")
      + field("Vendor", "vendor", "Cisco, Juniper, Ubiquiti…")
      + field("Model", "model", "Model / SKU")
      + field("Firmware", "firmware", "Version")
      + field("Serial number", "serial_number", "Serial number")
      + field("Location", "location", "Site / rack / room")
      + selectField("Status", "status", ["Unknown", "Online", "Warning", "Offline"].map(x => opt(x, x, x === "Unknown")).join(""))
      + areaField("Notes", "notes", "Optional maintenance or inventory notes");
    const rows = list.map(x => [
      `<strong>${esc(x.hostname)}</strong><small class="nx-cell-sub">${esc(x.model || x.vendor || "Network device")}</small>`,
      esc(x.device_type), esc(x.management_ip || "—"), esc(x.vendor || "—"), statusPill(x.status), esc(fmtDate(x.last_seen)), actions(x.id, "network-device", "network-device", "network device")
    ]);
    return formPanel("Add or edit a network device", "Inventory metadata is stored in Cartman's SQLite database. It does not automatically configure the physical device.", "network-device", fields, "Save device")
      + panel("Network device inventory", "Search, edit, and remove network inventory records. A record is not proof that the device is reachable.", table(["Hostname", "Type", "Management IP", "Vendor", "Status", "Last seen", "Actions"], rows, "No network devices yet. Add the first device above."), true);
  }

  function renderDiscovery(data) {
    const jobs = data || [];
    const rows = jobs.map(x => [esc(x.cidr), statusPill(x.status), esc(x.hosts_found), esc(fmtDate(x.created_at)), esc(fmtDate(x.completed_at)), x.status === "Running" || x.status === "Pending" ? "<span class=\"nx-muted\">Running…</span>" : `<button class="nx-text-button" type="button" data-view-discovery="${esc(x.id)}">View results</button>`]);
    const formFields = field("Private IPv4 CIDR *", "cidr", "192.168.1.0/24", "text", "required pattern=\"[0-9./]+\"")
      + `<label class="nx-confirm-field nx-field-wide"><input type="checkbox" name="confirm_authorized" value="true" required><span>I confirm I am authorized to scan this private network range.</span></label>`;
    let resultPanel = "";
    if (state.selectedDiscoveryId) {
      const job = (state.data || []).find(x => x.id === state.selectedDiscoveryId);
      const discoveryDetail = state.discoveryDetails[state.selectedDiscoveryId] || job || {};
      const resultRows = (discoveryDetail.results || []).map(x => {
        const match = x.inventory_match;
        const category = ["network_device", "endpoint", "unknown"].includes(x.classification)
          ? x.classification : "unknown";
        const marker = `<span hidden data-discovery-classification="${esc(category)}"></span>`;
        const methods = Array.isArray(x.methods) && x.methods.length ? x.methods : ["TCP"];
        const hostnameCell = `${esc(x.hostname || "—")}<small class="nx-cell-sub">Detected via ${esc(methods.join(" · "))}</small>`;
        const classificationCell = `<span class="nx-discovery-class nx-discovery-${esc(category)}">${esc(x.classification_label || "Unknown device")}</span><small class="nx-cell-sub">${esc((x.classification_confidence || "low").toUpperCase())} confidence · ${esc(x.classification_reason || "No classification evidence")}</small>`;

        let action;
        if (match) {
          action = `<span class="nx-muted">Already in Cartman · ${esc(match.name || "existing device")} · ${match.kind === "endpoint" ? "Endpoint inventory" : "Network inventory"}</span>`;
        } else if (category === "network_device") {
          action = `<button class="nx-text-button" type="button" data-import-discovery-ip="${esc(x.ip)}" data-discovery-job="${esc(state.selectedDiscoveryId)}">Add network device</button>`;
        } else if (category === "endpoint") {
          action = `<span class="nx-muted">Endpoint · use Devices</span>`;
        } else {
          action = `<span class="nx-muted">Review type manually</span>`;
        }

        return [
          `${esc(x.ip)}${marker}`,
          hostnameCell,
          classificationCell,
          esc((x.open_ports || []).join(", ") || "—"),
          statusPill(x.status),
          action
        ];
      });
      const filterMarkup = `<div class="nx-discovery-filter"><label class="nx-field"><span>Show devices</span><select data-discovery-filter><option value="all">All detected hosts</option><option value="network_device">Network device candidates</option><option value="endpoint">Endpoints / clients</option><option value="unknown">Unknown devices</option></select></label><p>Only network-device candidates can be imported here. Endpoint and unknown devices stay out of Network Devices.</p></div>`;
      resultPanel = panel("Discovery results", `Results for ${discoveryDetail.cidr || "selected job"}. Hosts responding to ICMP or tested TCP ports may appear. Devices blocking both may remain undetected.`, filterMarkup + table(["IP address", "Hostname / detection method", "Classification", "Open common ports", "Result", "Action"], resultRows, "No responsive hosts with the tested TCP ports were found. This does not prove that the hosts are offline."), true);
    }
    return formPanel("Start a discovery job", "Runs bounded ICMP and TCP probes against a confirmed private IPv4 range. Maximum range size is 256 addresses; silent hosts may still be missed.", "network-discovery", formFields, "Start discovery")
      + panel("Discovery jobs", "Jobs and results are stored in the database and update while a job is running.", table(["CIDR", "Status", "Responsive hosts", "Created", "Completed", "Results"], rows, "No discovery jobs yet."), true)
      + resultPanel;
  }

  function renderTopology(data) {
    const devices = data.devices || [], links = data.links || [];
    const deviceOptions = opt("", "Select device", true) + options(devices, "id", x => `${x.hostname}${x.management_ip ? ` — ${x.management_ip}` : ""}`);
    const fields = selectField("Source device *", "source_device_id", deviceOptions, "required")
      + selectField("Target device *", "target_device_id", deviceOptions, "required")
      + field("Source interface", "source_interface", "Gi1/0/1")
      + field("Target interface", "target_interface", "Gi1/0/2")
      + selectField("Link type", "link_type", ["Ethernet", "Fiber", "Wireless", "VPN", "Logical", "Other"].map(x => opt(x, x, x === "Ethernet")).join(""))
      + selectField("Status", "status", ["Unknown", "Up", "Down", "Planned"].map(x => opt(x, x, x === "Unknown")).join(""))
      + areaField("Notes", "notes", "Optional connection details");
    const rows = links.map(x => [`<strong>${esc(x.source_hostname)}</strong><small class="nx-cell-sub">${esc(x.source_interface || x.source_ip || "")}</small>`, `<strong>${esc(x.target_hostname)}</strong><small class="nx-cell-sub">${esc(x.target_interface || x.target_ip || "")}</small>`, esc(x.link_type), statusPill(x.status), actions(x.id, "network-link", "topology-link", "topology link")]);
    return formPanel("Record a topology link", "Create an explicit relationship between two registered network devices. These records form the topology canvas data source.", "network-link", fields, "Save link")
      + panel("Topology links", "Connections are registered data, not automatically inferred physical wiring.", table(["Source", "Target", "Link type", "Status", "Actions"], rows, "No links recorded. Add network devices first, then connect them here."), true)
      + panel("Topology canvas", "The link table is the initial graph model. Automatic LLDP/CDP collection can be added through a supported connector later.", `<div class="nx-topology-canvas">${links.length ? links.map(x => `<div class="nx-topology-edge"><span>${esc(x.source_hostname)}</span><i>⟷</i><span>${esc(x.target_hostname)}</span><small>${esc(x.link_type)} · ${esc(x.status)}</small></div>`).join("") : `<div class="nx-empty-state">No graph edges yet. Add a few links above to build the live topology view.</div>`}</div>`, true);
  }

  function renderIPAM(data) {
    const subnets = data.subnets || [], addresses = data.addresses || [];
    const subnetSelect = opt("", "Choose subnet", true) + options(subnets, "id", x => `${x.name} · ${x.cidr}`);
    const subnetFields = field("Subnet name *", "name", "Office LAN", "text", "required") + field("CIDR *", "cidr", "192.168.10.0/24", "text", "required")
      + field("VLAN ID", "vlan", "10", "number", "min=1 max=4094") + field("Gateway", "gateway", "192.168.10.1")
      + field("DNS servers", "dns_servers_text", "192.168.10.2, 1.1.1.1")
      + selectField("Status", "status", ["Active", "Planned", "Retired"].map(x => opt(x, x, x === "Active")).join(""))
      + areaField("Description", "description", "Purpose, location, owner");
    const deviceSelect = opt("", "No linked network device", true) + options(data.devices || [], "id", x => `${x.hostname}${x.management_ip ? ` · ${x.management_ip}` : ""}`);
    const addressFields = selectField("Subnet *", "subnet_id", subnetSelect, "required") + field("IP address *", "address", "192.168.10.45", "text", "required")
      + selectField("Linked network device", "device_id", deviceSelect)
      + field("Hostname", "hostname", "printer-01") + field("MAC address", "mac_address", "aa:bb:cc:dd:ee:ff")
      + selectField("Assignment", "assignment_type", ["Static", "DHCP", "Reservation", "Infrastructure", "Unknown"].map(x => opt(x, x, x === "Static")).join(""))
      + selectField("Status", "status", ["Assigned", "Available", "Reserved", "Excluded", "Conflict"].map(x => opt(x, x, x === "Assigned")).join(""))
      + areaField("Notes", "notes", "Optional address notes");
    const subnetRows = subnets.map(x => [esc(x.name), `<strong>${esc(x.cidr)}</strong>`, esc(x.vlan ?? "—"), esc(x.gateway || "—"), esc(x.address_count ?? 0), statusPill(x.status), actions(x.id, "network-subnet", "network-subnet", "subnet")]);
    const addressRows = addresses.map(x => [`<strong>${esc(x.address)}</strong>`, esc(x.subnet_name), esc(x.hostname || "—"), esc(x.device_hostname || "—"), esc(x.mac_address || "—"), esc(x.assignment_type), statusPill(x.status), actions(x.id, "network-address", "network-address", "IP address record")]);
    return formPanel("Subnet inventory", "Track IPv4 and IPv6 address spaces, VLANs, gateways, and DNS server references.", "network-subnet", subnetFields, "Save subnet")
      + formPanel("Address allocation", "Add an explicit IP record and assign it to a subnet. This does not configure a router or DHCP server.", "network-address", addressFields, "Save IP record")
      + panel("Subnets", "Subnet address counts reflect stored IP records, not automatic scanning of every address.", table(["Name", "CIDR", "VLAN", "Gateway", "IP records", "Status", "Actions"], subnetRows, "No subnets recorded."), true)
      + panel("IP address records", "Address-level allocation and reservations.", table(["Address", "Subnet", "Hostname", "Linked device", "MAC", "Assignment", "Status", "Actions"], addressRows, "No IP address records yet."), true);
  }

  function renderLiveReadPanel(targets) {
    const selected = state.selectedDhcpTargetId || "";
    const targetOptions = opt("", "Choose Windows server", !selected)
      + options(targets, "id", x => `${x.name} · ${x.status}${x.dns_dhcp_management_enabled ? " · DNS/DHCP enabled" : " · capability off"}`, selected);
    const target = targets.find(x => x.id === selected) || null;
    const report = state.dhcpConnectorReport;
    const reportText = report ? (report.result || report.result_text || report) : {
      message: "Choose an online Windows CartmanClient with the dedicated DNS/DHCP capability. Reads do not change configuration."
    };
    return panel(
      "Live Windows DNS & DHCP",
      "Read the actual Windows Server scopes, options, zones, and DNS records.",
      `<div class="nx-live-form"><div class="nx-form-grid">
        ${selectField("Windows server *", "live_device_id", targetOptions, "required data-dhcp-target")}
        <div class="nx-field"><span>Connection state</span><div class="nx-connection-note">${esc(target ? target.status + " · " + (target.ready ? "Dedicated connector ready" : "Agent or capability not ready") : "Select a Windows server")}</div></div>
      </div><div class="nx-form-grid">
        <label class="nx-field"><span>Scope ID for detailed DHCP reads</span><input type="text" data-dhcp-read-scope placeholder="e.g. 192.168.1.0" autocomplete="off"></label>
        <label class="nx-field"><span>Start row (offset)</span><input type="number" data-dhcp-read-offset min="0" max="100000" step="8" value="0"></label>
      </div><div class="nx-inline-note">Detail reads return up to 8 rows. For the next page, set offset to 8, 16, 24, and so on. All these actions are read-only.</div><div class="nx-form-actions"><button class="nx-primary" type="button" data-dhcp-live-read="dhcp" ${state.dhcpReadInFlight ? "disabled" : ""}>${state.dhcpReadInFlight === "dhcp" ? "Reading DHCP..." : "Read DHCP scopes"}</button><button class="nx-secondary" type="button" data-dhcp-live-read="dns" ${state.dhcpReadInFlight ? "disabled" : ""}>${state.dhcpReadInFlight === "dns" ? "Reading DNS..." : "Read DNS zones and records"}</button><button class="nx-secondary" type="button" data-dhcp-live-read="dhcp-leases" ${state.dhcpReadInFlight ? "disabled" : ""}>${state.dhcpReadInFlight === "dhcp-leases" ? "Reading leases..." : "Read DHCP leases"}</button><button class="nx-secondary" type="button" data-dhcp-live-read="dhcp-reservations" ${state.dhcpReadInFlight ? "disabled" : ""}>${state.dhcpReadInFlight === "dhcp-reservations" ? "Reading reservations..." : "Read DHCP reservations"}</button><button class="nx-secondary" type="button" data-dhcp-live-read="dhcp-exclusions" ${state.dhcpReadInFlight ? "disabled" : ""}>${state.dhcpReadInFlight === "dhcp-exclusions" ? "Reading exclusions..." : "Read DHCP exclusions"}</button></div>
      <pre class="nx-live-result">${esc(JSON.stringify(reportText, null, 2))}</pre></div>`,
      true,
      "READ-ONLY CONNECTOR"
    );
  }

  function renderLiveWritePanel(targets) {
    const selected = state.selectedDhcpTargetId || "";
    const targetOptions = opt("", "Choose Windows server", !selected)
      + options(targets, "id", x => `${x.name} · ${x.status}${x.dns_dhcp_management_enabled ? " · DNS/DHCP enabled" : " · capability off"}`, selected);
    const targetField = selectField("Windows server *", "device_id", targetOptions, "required data-dhcp-target");

    const dhcpOptionsForm = `<form class="nx-live-form" data-live-change="dhcp-options">
      <div class="nx-form-grid">${targetField}
        ${field("DHCP Scope ID *", "scope_id", "192.168.1.0", "text", "required")}
        ${field("Default gateway (optional)", "router", "192.168.1.1")}
        ${field("DNS servers (comma separated)", "dns_servers_text", "192.168.1.10, 1.1.1.1")}
        ${field("DHCP DNS domain", "dns_domain", "corp.example.local")}
      </div><div class="nx-inline-note">Only non-empty fields are changed. Blank fields keep their current value.</div>${submitRow("Preview DHCP option change")}</form>`;

    const dhcpLeaseForm = `<form class="nx-live-form" data-live-change="dhcp-lease">
      <div class="nx-form-grid">${targetField}
        ${field("DHCP Scope ID *", "scope_id", "192.168.1.0", "text", "required")}
        ${field("Lease duration (hours) *", "lease_hours", "8", "number", "required min=1 max=8760")}
      </div>${submitRow("Preview lease change")}</form>`;

    const reservationForm = `<form class="nx-live-form" data-live-change="dhcp-reservation">
      <div class="nx-form-grid">${targetField}
        ${selectField("Action", "operation", [opt("dhcp_reservation_add", "Add reservation", true),opt("dhcp_reservation_delete", "Delete exact reservation")].join(""))}
        ${field("DHCP Scope ID *", "scope_id", "192.168.1.0", "text", "required")}
        ${field("Reservation IP *", "ip_address", "192.168.1.50", "text", "required")}
        ${field("Client MAC (required)", "mac_address", "00-11-22-33-44-55", "text", "required")}
        ${field("Reservation name", "reservation_name", "lab-device-01")}
      </div><div class="nx-inline-note">Delete checks the exact scope, IP, and MAC. Add rejects out-of-range and already-used addresses.</div>${submitRow("Preview reservation change")}</form>`;

    const exclusionForm = `<form class="nx-live-form" data-live-change="dhcp-exclusion">
      <div class="nx-form-grid">${targetField}
        ${selectField("Action", "operation", [opt("dhcp_exclusion_add", "Add exclusion", true), opt("dhcp_exclusion_delete", "Delete exact exclusion")].join(""))}
        ${field("DHCP Scope ID *", "scope_id", "192.168.1.0", "text", "required")}
        ${field("Start IP *", "start_ip", "192.168.1.50", "text", "required")}
        ${field("End IP *", "end_ip", "192.168.1.50", "text", "required")}
      </div><div class="nx-inline-note">An exclusion prevents DHCP from allocating the range. Add checks the scope bounds and rejects overlapping exclusions, leases, or reservations. Delete requires the exact existing start and end IPs.</div>${submitRow("Preview exclusion change")}</form>`;

    const dnsZoneForm = `<form class="nx-live-form" data-live-change="dns-zone">
      <div class="nx-form-grid">${targetField}
        ${field("DNS zone *", "zone", "benbenim.com", "text", "required")}
      </div><div class="nx-inline-note">Creates a standard primary zone on the selected Windows DNS server. Warning: this local zone becomes authoritative for the entire domain here and can hide public DNS records with the same name for clients using this DNS server.</div>${submitRow("Preview DNS zone creation")}</form>`;

    const dnsForm = `<form class="nx-live-form" data-live-change="dns">
      <div class="nx-form-grid">${targetField}
        ${selectField("Action", "record_action", [opt("create", "Create record", true),opt("update", "Update record"),opt("delete", "Delete exact record")].join(""))}
        ${selectField("Record type", "record_type", [opt("A", "A · IPv4 address", true),opt("CNAME", "CNAME · alias")].join(""))}
        ${field("DNS zone *", "zone", "corp.example.local", "text", "required")}
        ${field("Record name *", "record_name", "intranet or @ for zone root", "text", "required")}
        ${field("Current value (update/delete)", "old_value", "192.168.1.20 or old.target.local")}
        ${field("New value (create/update)", "new_value", "192.168.1.21 or new.target.local")}
        ${field("TTL (seconds)", "ttl", "3600", "number", "min=30 max=604800")}
      </div><div class="nx-inline-note">Use @ for the zone root (e.g. benbenim.com). Only A and CNAME records are writable in this version.</div>${submitRow("Preview DNS change")}</form>`;

    let planHtml = `<div class="nx-inline-note">No pending change. Review a preview, then type its exact confirmation phrase. Preview never changes the server.</div>`;
    if (state.dhcpChangePlan) {
      const plan = state.dhcpChangePlan;
      planHtml = `<div class="nx-change-plan"><div class="nx-kicker">CHANGE PREVIEW · NOT APPLIED</div><h3>${esc(plan.target)}</h3><p>${esc(plan.summary)}</p><pre class="nx-live-result">${esc(JSON.stringify(plan.changes, null, 2))}</pre><p>${esc(plan.warning || "No server configuration has changed.")}</p><form class="nx-live-form" data-live-apply><input type="hidden" name="plan_id" value="${esc(plan.plan_id)}"><div class="nx-form-grid"><label class="nx-field nx-field-wide"><span>Type exactly: ${esc(plan.confirmation_phrase)}</span><input name="confirmation" required autocomplete="off" placeholder="${esc(plan.confirmation_phrase)}"></label></div>${submitRow("Confirm and queue change")}</form><small>Expires: ${esc(plan.expires_at)}</small></div>`;
    }

    let taskHtml = "";
    if (state.dhcpChangeTask) {
      const task = state.dhcpChangeTask;
      taskHtml = `<div class="nx-change-plan"><div class="nx-kicker">LIVE AGENT RESULT</div><p><strong>${esc(task.status)}</strong> · ${esc(task.device_name || "Windows server")}</p><pre class="nx-live-result">${esc(JSON.stringify(task.result || task.result_text || task, null, 2))}</pre></div>`;
    }

    return panel(
      "Live Windows DNS/DHCP changes",
      "Changes use allowlisted operations. General remote command execution is not required.",
      `<div class="nx-live-write-grid"><div><h3>DHCP options</h3>${dhcpOptionsForm}<h3>DHCP lease duration</h3>${dhcpLeaseForm}<h3>DHCP reservations</h3>${reservationForm}<h3>DHCP exclusions</h3>${exclusionForm}</div><div><h3>DNS zones</h3>${dnsZoneForm}<h3>DNS records</h3>${dnsForm}</div></div>${planHtml}${taskHtml}`,
      true,
      "PREVIEW · CONFIRM · VERIFY"
    );
  }

  function renderDnsDhcp(data) {
    const dns = data.dns || [], scopes = data.scopes || [], leases = data.leases || [];
    const connectorTargets = data.connectorTargets || [];
    const selectedTargetId = state.selectedDhcpTargetId || "";
    const selectedTarget = connectorTargets.find(x => x.id === selectedTargetId) || null;
    const report = state.dhcpConnectorReport || null;
    const reportOutput = report ? (report.result || report) : {
      message: "No live read requested. Read action does not modify DHCP."
    };
    const dnsFields = field("Zone *", "zone", "example.local", "text", "required") + field("Record name *", "name", "router", "text", "required")
      + selectField("Record type", "record_type", ["A", "AAAA", "CNAME", "MX", "TXT", "PTR", "NS", "SRV"].map(x => opt(x, x, x === "A")).join(""))
      + field("Value *", "value", "192.168.10.1", "text", "required") + field("TTL (seconds)", "ttl", "3600", "number", "min=30 max=604800 required")
      + selectField("Status", "status", ["Active", "Disabled"].map(x => opt(x, x, x === "Active")).join("")) + areaField("Notes", "notes", "Optional DNS record context");
    const dhcpFields = field("Scope name *", "name", "Office DHCP", "text", "required") + field("CIDR *", "cidr", "192.168.10.0/24", "text", "required")
      + field("Range start *", "start_ip", "192.168.10.50", "text", "required") + field("Range end *", "end_ip", "192.168.10.200", "text", "required")
      + field("Gateway", "gateway", "192.168.10.1") + field("DNS servers", "dns_servers_text", "192.168.10.2, 1.1.1.1")
      + field("Lease duration (seconds)", "lease_duration", "86400", "number", "min=60 max=31536000 required")
      + selectField("Status", "status", ["Active", "Disabled", "Planned"].map(x => opt(x, x, x === "Active")).join("")) + areaField("Notes", "notes", "Optional scope notes");
    const leaseFields = selectField("DHCP scope *", "scope_id", opt("", "Choose scope", true) + options(scopes, "id", x => `${x.name} · ${x.cidr}`), "required")
      + field("Lease IP *", "address", "192.168.10.55", "text", "required") + field("MAC address", "mac_address", "aa:bb:cc:dd:ee:ff")
      + field("Hostname", "hostname", "workstation-05") + field("Expires at", "expires_at", "ISO timestamp or date/time")
      + selectField("Status", "status", ["Active", "Reserved", "Expired", "Declined"].map(x => opt(x, x, x === "Active")).join(""));
    const dnsRows = dns.map(x => [esc(x.zone), `<strong>${esc(x.name)}</strong>`, `<span class="nx-type-tag">${esc(x.record_type)}</span>`, esc(x.value), esc(x.ttl), statusPill(x.status), actions(x.id, "dns-record", "dns-record", "DNS record")]);
    const scopeRows = scopes.map(x => [esc(x.name), esc(x.cidr), `<span>${esc(x.start_ip)} – ${esc(x.end_ip)}</span>`, esc(x.gateway || "—"), esc(x.lease_count ?? 0), statusPill(x.status), actions(x.id, "dhcp-scope", "dhcp-scope", "DHCP scope")]);
    const leaseRows = leases.map(x => [esc(x.scope_name), `<strong>${esc(x.address)}</strong>`, esc(x.hostname || "—"), esc(x.mac_address || "—"), esc(x.expires_at || "—"), statusPill(x.status), actions(x.id, "", "dhcp-lease", "DHCP lease")]);
    const connectorOptions = opt("", "Select Windows DHCP server", !selectedTargetId)
      + options(connectorTargets, "id",
        x => `${x.name} · ${x.status}${x.ready ? " · Ready" : " · Not ready"}`,
        selectedTargetId);

    const connectorPanel = panel(
      "Live Windows DHCP connector",
      "Read current scopes and common options from an approved Windows CartmanClient. This is read-only and never changes DHCP configuration.",
      `<div class="nx-form-grid">
        <label class="nx-field"><span>Windows server</span>
          <select data-dhcp-live-target>${connectorOptions}</select>
        </label>
        <div class="nx-field"><span>Agent state</span>
          <div class="nx-inline-note">${
            selectedTarget
              ? `${esc(selectedTarget.os)} · ${esc(selectedTarget.ip || "No IP")} · ${selectedTarget.agent_registered ? "Agent registered" : "No registered agent"} · ${selectedTarget.task_execution_enabled ? "Task execution enabled" : "Task execution not ready"}`
              : "Select an existing Windows device. No device record will be created."
          }</div>
        </div>
      </div>
      <div class="nx-form-actions">
        <button type="button" class="nx-primary" data-dhcp-live-read ${
          selectedTarget && selectedTarget.ready ? "" : "disabled"
        }>Read live DHCP configuration</button>
        <span class="nx-muted">Read-only · no changes</span>
      </div>
      <pre class="nx-live-result">${esc(JSON.stringify(reportOutput, null, 2))}</pre>`,
      true,
      "READ-ONLY CONNECTOR"
    );

    return renderLiveReadPanel(data.connectorTargets || [])
      + renderLiveWritePanel(data.connectorTargets || [])
      + formPanel("DNS record registry", "Manage Cartman's DNS record inventory. These local records do not change an external DNS service.", "dns-record", dnsFields, "Save DNS record")
      + formPanel("DHCP scope registry", "Cartman-managed DHCP metadata only; this does not configure an external DHCP server.", "dhcp-scope", dhcpFields, "Save DHCP scope")
      + panel("DNS records", "Cartman-managed DNS inventory.", table(["Zone", "Name", "Type", "Value", "TTL", "Status", "Actions"], dnsRows, "No DNS records saved yet."), true)
      + panel("DHCP scopes", "Cartman-managed scope metadata.", table(["Scope", "CIDR", "Lease range", "Gateway", "Leases", "Status", "Actions"], scopeRows, "No DHCP scopes saved yet."), true)
      + formPanel("Record a lease or reservation", "Cartman-managed lease metadata; external sync uses the live connector.", "dhcp-lease", leaseFields, "Save lease")
      + panel("DHCP leases", "Cartman-managed lease records.", table(["Scope", "Address", "Hostname", "MAC", "Expires", "Status", "Actions"], leaseRows, "No leases recorded yet."), true);
  }

  function renderDiagnostics(data) {
    const rows = (data || []).map(x => [esc(fmtDate(x.created_at)), `<strong>${esc(x.target)}</strong>`, esc(x.test_type), esc(x.port || "—"), statusPill(x.status), esc(x.response_ms === null ? "—" : `${x.response_ms} ms`), esc((x.resolved_addresses || []).join(", ") || "—"), esc(x.result_message)]);
    const fields = field("Target host or IP *", "target", "server.example.local or 192.168.10.20", "text", "required")
      + selectField("Test type", "test_type", [opt("dns", "DNS resolution", true), opt("tcp", "Single TCP connection")])
      + field("TCP port", "port", "443", "number", "min=1 max=65535")
      + `<div class="nx-inline-note nx-field-wide">DNS test resolves the supplied hostname. TCP test attempts one connection to the supplied port with a 2-second timeout. No shell commands are used.</div>`;
    return formPanel("Run a diagnostic test", "Run one explicitly requested DNS resolution or TCP reachability test from the Cartman server.", "diagnostic", fields, "Run test")
      + panel("Diagnostic history", "Each result is stored with the target, test type, response duration, and result message.", table(["Time", "Target", "Test", "Port", "Result", "Duration", "Resolved addresses", "Message"], rows, "No diagnostic tests yet."), true);
  }

  function renderInfrastructure(data) {
    const o = data.overview || {};
    const d = o.devices || {};
    const i = o.ipam || {};
    const dd = o.dns_dhcp || {};
    const disc = o.discovery || {};
    const diag = o.diagnostics || {};
    const infra = o.infrastructure || {};
    const servers = data.servers || {};
    const capacity = data.capacity || {};
    const devices = data.cartmanDevices || [];
    const assets = data.inventoryAssets || [];

    const serverRows = (servers.servers || []).slice(0, 12).map(x => [
      esc(x.name), esc(x.os), esc(x.ip || "—"), esc(x.server_role),
      esc(x.environment), statusPill(x.status), statusPill(x.criticality)
    ]);

    const deviceRows = devices.map(x => [
      `<strong>${esc(x.name)}</strong>`,
      esc(x.device_type || x.type || "—"),
      esc(x.os || "—"),
      esc(x.ip || x.local_ip || "—"),
      statusPill(x.status),
      esc(x.cpu || "—"),
      esc(x.ram || "—"),
      esc(x.disk || "—")
    ]);

    const assetRows = assets.map(x => [
      `<strong>${esc(x.name)}</strong>`,
      esc(x.type || "—"),
      esc(x.brand || "—"),
      esc(x.serialNo || "—"),
      esc(x.department || "—"),
      esc(x.assignedTo || "—"),
      x.sourceDeviceId
        ? `<span class="nx-pill">Linked to device</span>`
        : `<span class="nx-pill">Standalone asset</span>`
    ]);

    const tiles = [
      ["Managed Cartman devices", devices.length, "Existing Devices API"],
      ["Inventory assets", assets.length, "Existing Inventory API"],
      ["Server profiles", (servers.servers || []).length, "Explicit server classifications"],
      ["Network equipment", d.total || 0, `${d.online || 0} marked online`],
      ["IP subnets", i.subnets || 0, `${i.addresses || 0} saved address records`],
      ["DNS records", dd.dns_records || 0, `${dd.dhcp_scopes || 0} DHCP scope records`],
      ["Discovery jobs", disc.jobs || 0, `${disc.running || 0} currently running`],
      ["Failed diagnostics", diag.failed || 0, `${diag.runs || 0} tests stored`],
      ["Topology links", o.topology?.links || 0, "Explicitly registered links"],
      ["Capacity records", capacity.record_count || 0, "Telemetry and manual entries"]
    ].map(([label, value, note]) =>
      `<div class="nx-summary-tile"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`
    ).join("");

    return panel(
      "Infrastructure overview",
      "Live summary from Cartman Devices, Inventory, network records, and Monitoring metrics. Existing records are displayed without duplicating them.",
      `<div class="nx-summary-grid">${tiles}</div>`,
      true
    )
      + panel(
        "Managed Cartman devices",
        "Current device records from /api/devices; device identity and status remain owned by the Devices module.",
        table(["Device", "Type", "OS", "IP", "Status", "CPU", "RAM", "Disk"], deviceRows, "No devices exist in Cartman Devices."),
        true
      )
      + panel(
        "Inventory assets",
        "Existing asset records from /api/inventory. Linked devices are referenced, not copied into another device inventory.",
        table(["Asset", "Type", "Brand", "Serial", "Department", "Assigned to", "Relationship"], assetRows, "No Inventory assets exist."),
        true
      )
      + panel(
        "Server profiles",
        "Server-specific metadata attached to existing Cartman devices.",
        table(["Device", "OS", "IP", "Role", "Environment", "Status", "Criticality"], serverRows, "No server profiles yet. Open Servers & Infrastructure to classify an existing device."),
        true
      )
      + panel(
        "Module boundaries",
        "Network Devices owns network-equipment records; Devices owns managed endpoints and servers; Inventory owns asset details; Monitoring owns telemetry.",
        `<div class="nx-boundary-grid"><a href="/pages/network-devices/">Network Devices <span>→</span></a><a href="/pages/ip-address-management/">IP Address Management <span>→</span></a><a href="/pages/dns-dhcp/">DNS &amp; DHCP <span>→</span></a><a href="/pages/servers-infrastructure/">Servers &amp; Infrastructure <span>→</span></a><a href="/pages/capacity-management/">Capacity Management <span>→</span></a><a href="/pages/network-discovery/">Network Discovery <span>→</span></a></div>`,
        true
      );
  }

  function renderServers(data) {
    const servers = data.servers || [], candidates = data.candidates || [], dependencies = data.dependencies || [];
    const profileFields = selectField("Existing Cartman device *", "device_id", opt("", "Select existing device", true) + options(candidates, "id", x => `${x.name} · ${x.os}${x.ip ? ` · ${x.ip}` : ""}`), "required")
      + field("Server role", "server_role", "Application server", "text", "required")
      + selectField("Environment", "environment", ["Unspecified", "Production", "Development", "Test", "Staging", "Lab", "Disaster recovery"].map(x => opt(x, x, x === "Unspecified")).join(""))
      + selectField("Criticality", "criticality", ["Low", "Medium", "High", "Critical"].map(x => opt(x, x, x === "Medium")).join(""))
      + field("Location", "location", "Site / rack / cloud region") + areaField("Notes", "notes", "Server-specific metadata");
    const depFields = selectField("Source server/device *", "source_device_id", opt("", "Select source", true) + options(candidates, "id", x => x.name), "required")
      + selectField("Depends on *", "target_device_id", opt("", "Select dependency", true) + options(candidates, "id", x => x.name), "required")
      + selectField("Relationship", "relationship", ["Depends on", "Hosts", "Connected to", "Replicates to", "Backs up to", "Authenticates against"].map(x => opt(x, x, x === "Depends on")).join(""))
      + areaField("Notes", "notes", "Optional dependency details");
    const srows = servers.map(x => [`<strong>${esc(x.name)}</strong><small class="nx-cell-sub">${esc(x.os)} · ${esc(x.ip || "No IP")}</small>`, esc(x.server_role), esc(x.environment), statusPill(x.status), statusPill(x.criticality), esc(x.location || "—"), actions(x.profile_id, "network-server", "network-server", "server profile")]);
    const drows = dependencies.map(x => [esc(x.source_name), esc(x.relationship), esc(x.target_name), esc(x.notes || "—"), actions(x.id, "", "server-dependency", "dependency")]);
    return formPanel("Classify an existing device as a server", "This adds server metadata to a device that already exists in Cartman. It does not create a duplicate device record.", "network-server", profileFields, "Save server profile")
      + panel("Server inventory", "The identity, OS, IP, and live state come from the existing Devices API; this page adds server-specific classification.", table(["Device", "Role", "Environment", "Device status", "Criticality", "Location", "Actions"], srows, "No server profiles. Select an existing Cartman device above."), true)
      + formPanel("Record an infrastructure dependency", "Capture a relationship between existing devices. This is metadata; it does not change service configuration.", "server-dependency", depFields, "Save dependency")
      + panel("Dependencies", "Explicitly recorded relationships between devices.", table(["Source", "Relationship", "Target", "Notes", "Actions"], drows, "No dependency relationships recorded."), true);
  }

  function renderCapacity(data) {
    const records = data.records || [], plans = data.plans || [];
    const deviceFields = field("Metric name", "metric_name", "cpu_percent", "text", "required")
      + selectField("Device", "device_id", opt("", "No device / system-wide", true) + options(data.devices || [], "id", x => `${x.name}${x.ip ? ` · ${x.ip}` : ""}`))
      + field("Value *", "value", "72.5", "number", "required step=any min=0")
      + field("Unit", "unit", "%, GB, Mbps…") + areaField("Notes", "notes", "Manual entry context");
    const planFields = field("Plan title *", "title", "Increase storage for app servers", "text", "required")
      + selectField("Resource type", "resource_type", ["CPU", "Memory", "Storage", "Network", "IP addresses", "Other"].map(x => opt(x, x, x === "Storage")).join(""))
      + field("Current value", "current_value", "70", "number", "min=0 step=any") + field("Target value *", "target_value", "85", "number", "required min=0 step=any")
      + field("Unit", "unit", "%, GB, cores…") + field("Target date", "target_date", "2026-12-31", "date")
      + field("Owner", "owner", "Infrastructure team")
      + selectField("Status", "status", ["Planned", "In progress", "Completed", "On hold"].map(x => opt(x, x, x === "Planned")).join(""))
      + areaField("Notes", "notes", "Rationale / next step");
    const rrows = records.map(x => [esc(fmtDate(x.collected_at)), `<strong>${esc(x.device_name || "System-wide")}</strong>`, esc(x.metric_name), esc(x.value), esc(x.unit), `<span class="nx-source-chip nx-source-${esc(String(x.source || "unknown").replace(/[^a-z0-9_-]/gi, "-").toLowerCase())}">${esc(x.source || "unknown")}</span>`, esc(x.notes || "—")]);
    const prows = plans.map(x => [esc(x.title), esc(x.resource_type), esc(`${x.current_value} → ${x.target_value} ${x.unit}`), esc(x.target_date || "—"), esc(x.owner || "—"), statusPill(x.status), actions(x.id, "capacity-plan", "capacity-plan", "capacity plan")]);
    const telemetryInfo = data.telemetry_available ? `<div class="nx-inline-note nx-good-note">Existing Monitoring telemetry is available and included below.</div>` : `<div class="nx-inline-note">No Monitoring telemetry samples have been collected yet. The readings table will show manual records, clearly labelled; no utilisation is fabricated.</div>`;
    return formPanel("Record a capacity reading", "Use this form only for an explicitly known measurement. Saved entries are labelled manual-entry and are not live telemetry.", "capacity-record", deviceFields, "Save reading")
      + panel("Telemetry source", "Capacity calculations should use actual values collected by Cartman agents or supported monitoring connectors.", telemetryInfo, false)
      + panel("Capacity records", "Combines existing monitoring_metrics with recorded manual entries, newest first.", table(["Time", "Device", "Metric", "Value", "Unit", "Source", "Notes"], rrows, "No capacity records or monitoring metrics yet."), true)
      + formPanel("Capacity planning", "Track intended capacity changes separately from current measurements.", "capacity-plan", planFields, "Save plan")
      + panel("Capacity plans", "Stored planning items; no forecast is calculated until enough real time-series telemetry exists.", table(["Plan", "Resource", "Current → target", "Target date", "Owner", "Status", "Actions"], prows, "No capacity plans yet."), true);
  }

  function renderPage(data) {
    const root = $("[data-nx-content]");
    if (!root) return;
    switch (state.slug) {
      case "network": root.innerHTML = renderNetwork(data); break;
      case "network-devices": root.innerHTML = renderNetworkDevices(data); break;
      case "network-discovery": root.innerHTML = renderDiscovery(data); break;
      case "network-topology": root.innerHTML = renderTopology(data); break;
      case "ip-address-management": root.innerHTML = renderIPAM(data); break;
      case "dns-dhcp": root.innerHTML = renderDnsDhcp(data); break;
      case "network-diagnostics": root.innerHTML = renderDiagnostics(data); break;
      case "infrastructure": root.innerHTML = renderInfrastructure(data); break;
      case "servers-infrastructure": root.innerHTML = renderServers(data); break;
      case "capacity-management": root.innerHTML = renderCapacity(data); break;
      default: root.innerHTML = panel("Module unavailable", "This path is not part of the Network & Infrastructure batch.", `<div class="nx-empty-state">No live page renderer is registered.</div>`, true);
    }
    const empty = $("[data-nx-empty]");
    if (empty) empty.hidden = true;
    setStats(statsForPage(data));
    const searchValue = $("[data-nx-search]")?.value || "";
    if (searchValue) filterRows(searchValue);
  }

  function filterRows(query) {
    const needle = query.trim().toLocaleLowerCase();
    const content = $("[data-nx-content]");
    if (!content) return;
    $$("tbody tr", content).forEach(row => {
      row.hidden = !!needle && !row.textContent.toLocaleLowerCase().includes(needle);
    });
    $$(".nx-summary-tile", content).forEach(tile => {
      tile.hidden = !!needle && !tile.textContent.toLocaleLowerCase().includes(needle);
    });
    $$(".nx-panel", content).forEach(panel => {
      const rows = $("tbody", panel);
      if (rows) panel.dataset.nxSectionHidden = String(!!needle && !Array.from(rows.querySelectorAll("tr")).some(row => !row.hidden));
    });
  }

  function formValues(form) {
    const values = {};
    $$('[name]', form).forEach(control => {
      if (control.type === "checkbox") values[control.name] = control.checked;
      else values[control.name] = control.value;
    });
    return values;
  }
  function restoreForms(snapshot) {
    Object.entries(snapshot || {}).forEach(([key, values]) => {
      const form = $(`form[data-form="${CSS.escape(key)}"]`);
      if (!form) return;
      Object.entries(values).forEach(([name, value]) => {
        const control = $(`[name="${CSS.escape(name)}"]`, form);
        if (!control) return;
        if (control.type === "checkbox") control.checked = !!value;
        else control.value = value;
      });
    });
  }
  function snapshotForms() {
    const result = {};
    $$('form[data-form]').forEach(form => { result[form.dataset.form] = formValues(form); });
    return result;
  }
  function populateForm(form, record) {
    Object.entries(record || {}).forEach(([key, value]) => {
      let control = $(`[name="${CSS.escape(key)}"]`, form);
      if (!control && key.endsWith("_json")) control = $(`[name="${CSS.escape(key.replace(/_json$/, "_text"))}"]`, form);
      if (!control && key === "dns_servers") control = $('[name="dns_servers_text"]', form);
      if (!control) return;
      if (control.type === "checkbox") control.checked = !!value;
      else if (Array.isArray(value)) control.value = value.join(", ");
      else if (value !== null && value !== undefined) control.value = value;
    });
  }

  async function refreshPage(preserveForms = true) {
    const snapshot = preserveForms ? snapshotForms() : {};
    try {
      const data = await loadData();
      state.data = data;
      state.error = "";
      state.lastLoadedAt = new Date();
      setConnection(true);
      renderPage(data);
      restoreForms(snapshot);
      notifyClear();
    } catch (error) {
      state.error = error.message || "API request failed";
      setConnection(false);
      const root = $("[data-nx-content]");
      if (root) root.innerHTML = panel("Could not load live data", `The Cartman API returned an error: ${state.error}`, `<div class="nx-empty-state">Check that the Cartman API is running, then use the refresh action to retry.</div><button type="button" class="nx-primary" data-refresh>Retry connection</button>`, true, "CONNECTION ERROR");
      notify(`API error: ${state.error}`, "error");
    }
  }

  function payloadFor(form) {
    const data = formValues(form);
    delete data.id;
    if (data.dns_servers_text !== undefined) {
      data.dns_servers = data.dns_servers_text.split(",").map(x => x.trim()).filter(Boolean);
      delete data.dns_servers_text;
    }
    if (data.confirm_authorized !== undefined) {
      data.confirm_authorized = data.confirm_authorized === true || data.confirm_authorized === "true";
    }
    ["vlan", "ttl", "lease_duration", "port", "current_value", "target_value", "value"].forEach(key => {
      if (data[key] !== undefined && data[key] !== "") data[key] = Number(data[key]);
      else if (data[key] === "") delete data[key];
    });
    return data;
  }

  async function handleSubmit(form) {
    const kind = form.dataset.form;
    let payload = payloadFor(form);
    const id = form.querySelector('[name="id"]')?.value || "";
    let url = "", method = id ? "PUT" : "POST";
    const routes = {
      "network-device": `${API}/devices`,
      "network-subnet": `${API}/ipam/subnets`,
      "network-address": `${API}/ipam/addresses`,
      "dns-record": `${API}/dns/records`,
      "dhcp-scope": `${API}/dhcp/scopes`,
      "dhcp-lease": `${API}/dhcp/leases`,
      "network-link": `${API}/topology/links`,
      "network-server": `${API}/servers`,
      "server-dependency": `${API}/servers/dependencies`,
      "capacity-record": `${API}/capacity/records`,
      "capacity-plan": `${API}/capacity/plans`,
      "network-discovery": `${API}/discovery/jobs`,
      "diagnostic": `${API}/diagnostics/run`
    };
    url = routes[kind];
    if (!url) throw new Error(`Unknown form type: ${kind}`);
    if (kind === "network-discovery") {
      method = "POST";
      // The browser checkbox is checked into a boolean by formValues.
      payload.confirm_authorized = !!payload.confirm_authorized;
    }
    if (kind === "diagnostic") {
      method = "POST";
      if (payload.test_type === "dns") delete payload.port;
      else if (!payload.port) throw new Error("Enter a TCP port for a TCP test.");
    }
    if (id) url += `/${encodeURIComponent(id)}`;
    if (kind === "capacity-record" && payload.device_id === "") payload.device_id = "";
    const response = await api(url, { method, body: payload });
    if (kind === "network-discovery") {
      state.selectedDiscoveryId = response.id;
      notify(`Discovery job queued for ${response.cidr}. ${response.message}`, "success");
    } else if (kind === "diagnostic") {
      notify(`${response.test_type} test ${response.status.toLowerCase()}: ${response.result_message}`, response.status === "Succeeded" ? "success" : "error");
    } else {
      notify(id ? "Record updated." : "Record saved.", "success");
    }
    form.reset();
    const hidden = form.querySelector('[name="id"]');
    if (hidden) hidden.value = "";
    const button = $("button[type=submit]", form);
    if (button) button.textContent = kind === "network-device" ? "Save device" : kind === "network-subnet" ? "Save subnet" : kind === "network-address" ? "Save IP record" : kind === "dns-record" ? "Save DNS record" : kind === "dhcp-scope" ? "Save DHCP scope" : kind === "network-server" ? "Save server profile" : kind === "capacity-plan" ? "Save plan" : kind === "network-link" ? "Save link" : kind === "diagnostic" ? "Run test" : kind === "network-discovery" ? "Start discovery" : kind === "capacity-record" ? "Save reading" : kind === "dhcp-lease" ? "Save lease" : "Save record";
    await refreshPage(false);
  }

  function recordForEdit(kind, id) {
    const d = state.data;
    if (!d) return null;
    if (kind === "network-device") return (Array.isArray(d) ? d : []).find(x => x.id === id);
    if (kind === "network-subnet") return (d.subnets || []).find(x => x.id === id);
    if (kind === "network-link") return (d.links || []).find(x => x.id === id);
    if (kind === "network-address") return (d.addresses || []).find(x => x.id === id);
    if (kind === "dns-record") return (d.dns || []).find(x => x.id === id);
    if (kind === "dhcp-scope") return (d.scopes || []).find(x => x.id === id);
    if (kind === "network-server") return (d.servers || []).find(x => x.profile_id === id);
    if (kind === "capacity-plan") return (d.plans || []).find(x => x.id === id);
    return null;
  }

  const deleteRoutes = {
    "network-device": id => `${API}/devices/${encodeURIComponent(id)}`,
    "network-subnet": id => `${API}/ipam/subnets/${encodeURIComponent(id)}`,
    "network-address": id => `${API}/ipam/addresses/${encodeURIComponent(id)}`,
    "dns-record": id => `${API}/dns/records/${encodeURIComponent(id)}`,
    "dhcp-scope": id => `${API}/dhcp/scopes/${encodeURIComponent(id)}`,
    "dhcp-lease": id => `${API}/dhcp/leases/${encodeURIComponent(id)}`,
    "topology-link": id => `${API}/topology/links/${encodeURIComponent(id)}`,
    "network-server": id => `${API}/servers/${encodeURIComponent(id)}`,
    "server-dependency": id => `${API}/servers/dependencies/${encodeURIComponent(id)}`,
    "capacity-plan": id => `${API}/capacity/plans/${encodeURIComponent(id)}`
  };

  async function handleClick(event) {
    const readButton = event.target.closest("[data-dhcp-live-read]");
    if (readButton) {
      if (state.dhcpReadInFlight) {
        notify("A live read is already in progress. Wait for it to finish.", "info");
        return;
      }

      const selector = $("[data-dhcp-target]");
      const deviceId = (selector && selector.value) || state.selectedDhcpTargetId;
      if (!deviceId) return notify("Choose a Windows server first.", "error");

      state.selectedDhcpTargetId = deviceId;
      const subsystem = readButton.dataset.dhcpLiveRead;
      const readPayload = { device_id: deviceId, subsystem };
      if (["dhcp-leases", "dhcp-reservations", "dhcp-exclusions"].includes(subsystem)) {
        const scopeInput = $("[data-dhcp-read-scope]");
        const offsetInput = $("[data-dhcp-read-offset]");
        const scopeId = scopeInput ? scopeInput.value.trim() : "";
        const offsetRaw = offsetInput ? offsetInput.value : "0";
        const offset = Number(offsetRaw || 0);
        if (!scopeId) return notify("Enter a DHCP scope ID before reading leases, reservations, or exclusions.", "error");
        if (!Number.isInteger(offset) || offset < 0 || offset > 100000) {
          return notify("Offset must be a whole number between 0 and 100000.", "error");
        }
        readPayload.scope_id = scopeId;
        readPayload.offset = offset;
      }
      state.dhcpReadInFlight = subsystem;
      if (state.data) renderPage(state.data);

      try {
        let task;
        const previous = state.dhcpConnectorReport;
        const pendingStatuses = ["Queued", "Running", "Dispatched"];

        const canResume = previous
          && previous.task_id
          && String(previous.device_id) === String(deviceId)
          && state.dhcpConnectorSubsystem === subsystem
          && pendingStatuses.includes(previous.status);

        if (canResume) {
          task = previous;
          notify(`Resuming existing ${subsystem.toUpperCase()} task ${task.task_id}; no duplicate task created.`, "info");
        } else {
          task = await api("/api/network/dns-dhcp/connector/read", {
            method: "POST",
            body: readPayload
          });

          state.dhcpConnectorSubsystem = subsystem;
          state.dhcpConnectorReport = task;
        }

        if (state.data) renderPage(state.data);
        notify(`${subsystem.toUpperCase()} read task ${task.task_id} is being monitored. No configuration will be changed.`, "info");

        for (let attempt = 0; attempt < 45; attempt++) {
          if (!pendingStatuses.includes(task.status)) break;

          await new Promise(resolve => setTimeout(resolve, 2000));

          task = await api(
            `/api/network/dns-dhcp/connector/tasks/${encodeURIComponent(task.task_id)}`
          );

          state.dhcpConnectorReport = task;
          if (state.data) renderPage(state.data);

          if (!pendingStatuses.includes(task.status)) break;
        }

        if (task.status === "Succeeded" && task.result && task.result.status === "Succeeded") {
          notify(`${subsystem.toUpperCase()} read completed from ${task.device_name}.`, "success");
        } else if (pendingStatuses.includes(task.status)) {
          notify(`Task ${task.task_id} is still pending. Press Read again only to resume this task; do not repeatedly start new reads.`, "info");
        } else {
          notify((task.result && task.result.error) || task.result_text || `Live ${subsystem.toUpperCase()} read failed.`, "error");
        }
      } catch (error) {
        state.dhcpConnectorReport = {
          ...(state.dhcpConnectorReport || {}),
          status: "Failed",
          error: error.message || String(error)
        };

        if (state.data) renderPage(state.data);
        notify(error.message || "Could not read live Windows configuration.", "error");
      } finally {
        state.dhcpReadInFlight = "";
        if (state.data) renderPage(state.data);
      }

      return;
    }

    const refresh = event.target.closest("[data-refresh]");
    if (refresh) return refreshPage(true);
    const viewJob = event.target.closest("[data-view-discovery]");
    if (viewJob) {
      try {
        const job = await api(`${API}/discovery/jobs/${encodeURIComponent(viewJob.dataset.viewDiscovery)}`);
        state.selectedDiscoveryId = job.id;
        state.discoveryDetails[job.id] = job;
        const existing = (state.data || []).find(x => x.id === job.id);
        if (existing) Object.assign(existing, { results: job.results || [], status: job.status, hosts_found: job.hosts_found, error: job.error });
        else state.data.unshift(job);
        renderPage(state.data);
        notify(`Loaded results for ${job.cidr}.`, "info");
      } catch (error) { notify(error.message, "error"); }
      return;
    }
    const importResult = event.target.closest("[data-import-discovery-ip]");
    if (importResult) {
      try {
        const result = await api(`${API}/discovery/jobs/${encodeURIComponent(importResult.dataset.discoveryJob)}/import`, {
          method: "POST", body: { addresses: [importResult.dataset.importDiscoveryIp] }
        });
        const jobId = importResult.dataset.discoveryJob;
        const discoveredIp = importResult.dataset.importDiscoveryIp;
        const detail = state.discoveryDetails[jobId];
        const detailItem = detail && (detail.results || []).find(item => item.ip === discoveredIp);
        const importedDevice = (result.imported || [])[0];
        const skippedDevice = (result.skipped || [])[0];

        if (detailItem && importedDevice) {
          detailItem.inventory_match = {
            kind: "network", id: importedDevice.id,
            name: importedDevice.hostname, status: importedDevice.status
          };
        } else if (detailItem && skippedDevice && skippedDevice.existing_id) {
          detailItem.inventory_match = {
            kind: skippedDevice.kind || "network",
            id: skippedDevice.existing_id,
            name: skippedDevice.existing_name || "Existing device",
            status: skippedDevice.status || "Unknown"
          };
        }

        const outcome = result.imported_count
          ? `Added ${result.imported[0].hostname} (${result.imported[0].management_ip}) to Network Devices.`
          : `No new device added. ${skippedDevice?.reason || result.not_found?.[0] || "Result was not imported."}`;
        notify(outcome, result.imported_count ? "success" : "info");
        await refreshPage(true);
      } catch (error) { notify(error.message || "Could not import discovery result.", "error"); }
      return;
    }
    const edit = event.target.closest("[data-edit]");
    if (edit) {
      const form = $(`form[data-form="${CSS.escape(edit.dataset.edit)}"]`);
      const record = recordForEdit(edit.dataset.edit, edit.dataset.id);
      if (!form || !record) return notify("Could not find the record to edit.", "error");
      form.reset();
      populateForm(form, record);
      const idInput = form.querySelector('[name="id"]');
      if (idInput) idInput.value = edit.dataset.id;
      const button = $("button[type=submit]", form);
      if (button) button.textContent = "Update record";
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      notify("Editing selected record. Save to apply the update.", "info");
      return;
    }
    const del = event.target.closest("[data-delete]");
    if (del) {
      const urlFactory = deleteRoutes[del.dataset.delete];
      if (!urlFactory) return;
      const label = del.dataset.label || "record";
      if (!window.confirm(`Delete this ${label}? This cannot be undone.`)) return;
      try {
        await api(urlFactory(del.dataset.id), { method: "DELETE" });
        if (state.slug === "network-discovery") state.selectedDiscoveryId = "";
        notify(`${label} deleted.`, "success");
        await refreshPage(false);
      } catch (error) { notify(error.message || "Delete failed.", "error"); }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const match = window.location.pathname.match(/^\/pages\/([a-z0-9-]+)\/?$/);
    if (!match) return;
    state.slug = match[1];
    if (!pages[state.slug]) return;
    const search = $("[data-nx-search]");
    if (search) search.addEventListener("input", () => filterRows(search.value));
    const toolbar = $(".nx-toolbar");
    if (toolbar && !$("[data-nx-refresh]", toolbar)) {
      const refreshButton = document.createElement("button");
      refreshButton.type = "button";
      refreshButton.className = "nx-secondary nx-refresh-button";
      refreshButton.dataset.nxRefresh = "";
      refreshButton.textContent = "Refresh data";
      toolbar.appendChild(refreshButton);
      refreshButton.addEventListener("click", () => refreshPage(true));
    }
    const liveFormDrafts = new Map();
    let liveFormFocus = null;
    let liveDraftPageSlug = String(state.slug || "");

    function resetLiveDraftsOnNavigation() {
      const currentSlug = String(state.slug || "");
      if (currentSlug !== liveDraftPageSlug) {
        liveFormDrafts.clear();
        liveFormFocus = null;
        liveDraftPageSlug = currentSlug;
      }
    }

    function liveDraftKey(form) {
      if (form.matches("form[data-live-change]")) {
        return "change:" + form.dataset.liveChange;
      }
      if (form.matches("form[data-live-apply]")) {
        const id = form.querySelector('[name="plan_id"]');
        return "apply:" + (id ? id.value : "");
      }
      return "";
    }

    function saveLiveFormDraft(form) {
      if (!form) return;
      const key = liveDraftKey(form);
      if (!key) return;

      const counts = Object.create(null);
      const fields = Array.from(form.querySelectorAll("[name]")).map(control => {
        const name = control.name;
        const index = counts[name] || 0;
        counts[name] = index + 1;
        return {
          name,
          index,
          value: control.value,
          checked: ["checkbox", "radio"].includes(control.type)
            ? control.checked : null
        };
      });

      liveFormDrafts.set(key, fields);
    }

    function rememberLiveFormFocus(control) {
      const form = control && control.closest
        ? control.closest("form[data-live-change], form[data-live-apply]")
        : null;

      if (!form || !control.name) {
        liveFormFocus = null;
        return;
      }

      saveLiveFormDraft(form);
      const peers = Array.from(form.querySelectorAll("[name]"))
        .filter(node => node.name === control.name);

      liveFormFocus = {
        key: liveDraftKey(form),
        name: control.name,
        index: peers.indexOf(control),
        start: typeof control.selectionStart === "number"
          ? control.selectionStart : null,
        end: typeof control.selectionEnd === "number"
          ? control.selectionEnd : null
      };
    }

    function restoreLiveFormDrafts() {
      resetLiveDraftsOnNavigation();

      const forms = Array.from(document.querySelectorAll(
        "form[data-live-change], form[data-live-apply]"
      ));

      forms.forEach(form => {
        const saved = liveFormDrafts.get(liveDraftKey(form));
        if (!saved) return;

        saved.forEach(item => {
          const peers = Array.from(form.querySelectorAll("[name]"))
            .filter(node => node.name === item.name);
          const control = peers[item.index];
          if (!control) return;

          control.value = item.value;
          if (item.checked !== null) control.checked = item.checked;
        });
      });

      if (!liveFormFocus) return;

      const form = forms.find(item => liveDraftKey(item) === liveFormFocus.key);
      if (!form) return;

      const control = Array.from(form.querySelectorAll("[name]"))
        .filter(node => node.name === liveFormFocus.name)[liveFormFocus.index];

      if (!control) return;

      try {
        control.focus({ preventScroll: true });
      } catch (_) {
        control.focus();
      }

      if (liveFormFocus.start !== null &&
          liveFormFocus.end !== null &&
          typeof control.setSelectionRange === "function") {
        try {
          control.setSelectionRange(liveFormFocus.start, liveFormFocus.end);
        } catch (_) {}
      }
    }

    document.addEventListener("input", event => {
      resetLiveDraftsOnNavigation();
      const control = event.target;
      const form = control.closest
        ? control.closest("form[data-live-change], form[data-live-apply]")
        : null;

      if (!form || !control.name) return;
      saveLiveFormDraft(form);
      rememberLiveFormFocus(control);
    }, true);

    document.addEventListener("change", event => {
      resetLiveDraftsOnNavigation();
      const control = event.target;
      const form = control.closest
        ? control.closest("form[data-live-change], form[data-live-apply]")
        : null;

      if (!form || !control.name) return;
      saveLiveFormDraft(form);
      rememberLiveFormFocus(control);
    }, true);

    document.addEventListener("focusin", event => {
      const control = event.target;
      if (control && control.matches &&
          control.matches("input[name], textarea[name], select[name]")) {
        const form = control.closest("form[data-live-change], form[data-live-apply]");
        if (form) {
          rememberLiveFormFocus(control);
          return;
        }
      }
      liveFormFocus = null;
    }, true);

    function subtreeHasLiveForm(node) {
      if (!node || !node.querySelector) return false;

      if (node.nodeType === 1 &&
          node.matches("form[data-live-change], form[data-live-apply]")) {
        return true;
      }

      return !!node.querySelector("form[data-live-change], form[data-live-apply]");
    }

    const liveFormObserver = new MutationObserver(records => {
      const formsWereRebuilt = records.some(record =>
        [...record.addedNodes, ...record.removedNodes].some(subtreeHasLiveForm)
      );

      if (formsWereRebuilt) {
        requestAnimationFrame(restoreLiveFormDrafts);
      }
    });

    liveFormObserver.observe(document.body, {
      childList: true,
      subtree: true
    });

    document.addEventListener("submit", async event => {
      const changeForm = event.target.closest("form[data-live-change]");
      const applyForm = event.target.closest("form[data-live-apply]");
      if (!changeForm && !applyForm) return;
      event.preventDefault();
      try {
        if (changeForm) {
          const payload = formValues(changeForm);
          if (changeForm.dataset.liveChange === "dhcp-options") payload.operation = "dhcp_scope_options";
          if (changeForm.dataset.liveChange === "dhcp-lease") payload.operation = "dhcp_scope_lease";
          if (changeForm.dataset.liveChange === "dns-zone") payload.operation = "dns_zone_create";
          if (changeForm.dataset.liveChange === "dns") {
            payload.operation = `dns_${String(payload.record_type || "A").toLowerCase()}_${payload.record_action}`;
            delete payload.record_type;
            delete payload.record_action;
          }
          if (payload.dns_servers_text !== undefined) {
            payload.dns_servers = payload.dns_servers_text.split(",").map(x => x.trim()).filter(Boolean);
            delete payload.dns_servers_text;
          }
          ["lease_hours", "ttl"].forEach(key => {
            if (payload[key] !== "" && payload[key] !== undefined) payload[key] = Number(payload[key]);
            else delete payload[key];
          });
          if (changeForm.dataset.liveChange === "dhcp-options") {
            const report = state.dhcpConnectorReport;
            const live = report && report.result;

            if (
              !report ||
              report.status !== "Succeeded" ||
              !live ||
              live.status !== "Succeeded" ||
              live.operation !== "read_dhcp"
            ) {
              throw new Error("Read live DHCP scopes successfully before previewing this change.");
            }

            if (String(report.device_id) !== String(payload.device_id)) {
              throw new Error("The live DHCP read belongs to a different Windows server. Read the selected server again.");
            }

            const timestamp = String(report.finished_at || report.created_at || "");
            const isoTimestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp)
              ? timestamp
              : timestamp.replace(" ", "T") + "Z";
            const readTime = Date.parse(isoTimestamp);

            if (!Number.isFinite(readTime) || Date.now() - readTime > 5 * 60 * 1000 || readTime > Date.now() + 30000) {
              throw new Error("The live DHCP read is older than five minutes. Read DHCP scopes again.");
            }

            const scope = (Array.isArray(live.scopes) ? live.scopes : [])
              .find(item => String(item.scope_id) === String(payload.scope_id));

            if (!scope) {
              throw new Error("The requested scope was not present in the live DHCP read. Read the configuration again.");
            }

            const asList = value => {
              if (Array.isArray(value)) return value.map(String).map(x => x.trim()).filter(Boolean);
              if (value === null || value === undefined || value === "") return [];
              return [String(value).trim()].filter(Boolean);
            };

            payload.expected_before = {
              router: asList(scope.gateway),
              dns_servers: asList(scope.dns_servers),
              dns_domain: asList(scope.dns_domain)
            };
          }

          const plan = await api("/api/network/dns-dhcp/changes/preview", { method: "POST", body: payload });
          state.dhcpChangePlan = plan;
          state.dhcpChangeTask = null;
          state.selectedDhcpTargetId = payload.device_id;
          await refreshPage(true);
          notify("Preview created. No Windows DNS/DHCP change has been applied.", "info");
          return;
        }

        const values = formValues(applyForm);
        const queued = await api(`/api/network/dns-dhcp/changes/${encodeURIComponent(values.plan_id)}/apply`, {
          method: "POST", body: { confirmation: values.confirmation }
        });
        state.dhcpChangePlan = null;
        state.dhcpChangeTask = queued;
        await refreshPage(true);
        notify("Confirmed operation queued to the dedicated Windows DNS/DHCP capability.", "info");

        let result = queued;
        for (let attempt = 0; attempt < 60; attempt++) {
          await new Promise(resolve => setTimeout(resolve, 2000));
          result = await api(`/api/network/dns-dhcp/connector/tasks/${encodeURIComponent(queued.task_id)}`);
          state.dhcpChangeTask = result;
          if (state.data) renderPage(state.data);
          if (!["Queued", "Running", "Dispatched"].includes(result.status)) break;
        }

        if (result.status === "Succeeded" && result.result && result.result.status === "Succeeded" && result.result.verified === true) {
          notify("Windows Server read-back verified the change.", "success");
        } else if (["Queued", "Running", "Dispatched"].includes(result.status)) {
          notify("Task is still pending. Keep the Windows CartmanClient online.", "info");
        } else {
          notify((result.result && result.result.error) || result.result_text || `DNS/DHCP operation ${String(result.status).toLowerCase()}.`, "error");
        }
      } catch (error) {
        notify(error.message || "DNS/DHCP operation failed.", "error");
      }
    });

    document.addEventListener("submit", async event => {
      const form = event.target.closest("form[data-form]");
      if (!form) return;
      event.preventDefault();
      notifyClear();
      const submit = $("button[type=submit]", form);
      if (submit) submit.disabled = true;
      try { await handleSubmit(form); }
      catch (error) { notify(error.message || "Request failed.", "error"); }
      finally { if (submit && submit.isConnected) submit.disabled = false; }
    });
    document.addEventListener("change", event => {
      const dhcpTarget = event.target.closest("[data-dhcp-live-target]");
      if (!dhcpTarget) return;
      state.selectedDhcpTargetId = dhcpTarget.value;
      if (state.data) renderPage(state.data);
    });
    document.addEventListener("change", event => {
      const target = event.target.closest("[data-dhcp-target]");
      if (!target) return;
      state.selectedDhcpTargetId = target.value;
      $$('[data-dhcp-target]').forEach(other => {
        if (other !== target) other.value = target.value;
      });
    });
    document.addEventListener("change", event => {
      const filter = event.target.closest("[data-discovery-filter]");
      if (!filter) return;
      const resultPanel = filter.closest(".nx-panel");
      if (!resultPanel) return;
      $$("tbody tr", resultPanel).forEach(row => {
        const marker = row.querySelector("[data-discovery-classification]");
        const category = marker ? marker.dataset.discoveryClassification : "unknown";
        const visible = filter.value === "all" || category === filter.value;
        row.hidden = !visible;
        row.style.display = visible ? "" : "none";
      });
    });
    document.addEventListener("click", handleClick);
    refreshPage(false);
    window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      // Discovery jobs are polled more often while pending/running; the form stays populated.
      if (state.slug === "network-discovery") {
        if ((state.data || []).some(x => ["Pending", "Running"].includes(x.status))) refreshPage(true);
        else refreshPage(true);
      } else {
        refreshPage(true);
      }
    }, state.slug === "network-discovery" ? 2500 : 15000);
  });
})();
