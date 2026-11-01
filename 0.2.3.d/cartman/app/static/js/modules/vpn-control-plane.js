(() => {
  "use strict";

  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  })[ch]);

  const shortId = (prefix, id) =>
    `${prefix}-${String(id || "").slice(-6).toUpperCase()}`;

  const statusClass = value => {
    const v = String(value || "").toLowerCase();
    if (/blocked|denied|failed|offline|disconnected|error/.test(v)) return "is-offline";
    if (/pending|quarantin|not installed|not applied|not enforced|draft|review/.test(v)) return "is-pending";
    if (/connected|online|healthy|succeeded|success/.test(v)) return "is-online";
    return "is-neutral";
  };

  const pill = value =>
    `<span class="vpn-status ${statusClass(value)}">${esc(value || "Unknown")}</span>`;

  async function api(url, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";

    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      ...options,
      headers
    });

    const raw = await response.text();
    let data = null;
    if (raw) {
      try { data = JSON.parse(raw); } catch { data = raw; }
    }

    if (!response.ok) {
      const detail = data && typeof data === "object"
        ? data.detail || data.message
        : data;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return data;
  }

  function mount(root) {
    if (root.dataset.vpnControlMounted === "true") return true;
    root.dataset.vpnControlMounted = "true";

    const page = root.dataset.vpnPage;
    const $ = selector => root.querySelector(selector);
    const $$ = selector => [...root.querySelectorAll(selector)];

    const tbody = $("[data-vpn-tbody]");
    const count = $("[data-vpn-count]");
    const empty = $("[data-vpn-empty]");
    const stats = $("[data-vpn-stats]");
    const search = $("[data-vpn-search]");
    const filter = $("[data-vpn-filter]");

    let modalHost = $("[data-vpn-modal-host]");
    if (!modalHost) {
      modalHost = document.createElement("div");
      modalHost.dataset.vpnModalHost = "";
      root.appendChild(modalHost);
    }

    let records = [];
    let gateways = [];
    let peers = [];
    let networks = [];
    let policies = [];
    let audit = [];
    let overview = null;
    let busy = false;

    function notice(message, error = false) {
      let node = $("[data-vpn-control-notice]");
      if (!node) {
        node = document.createElement("div");
        node.dataset.vpnControlNotice = "";
        node.setAttribute("role", "status");
        node.style.cssText =
          "padding:12px 14px;border:1px solid var(--border,#293449);" +
          "border-radius:9px;margin:12px 0 16px;font-size:12px;line-height:1.6;" +
          "background:var(--surface,#111827);overflow-wrap:anywhere;";
        const anchor = stats || root.querySelector(".vpn-shortcuts") || null;
        if (anchor) root.insertBefore(node, anchor);
        else root.appendChild(node);
      }
      node.textContent = message;
      node.style.borderColor = error ? "var(--red,#dc2626)" : "var(--border,#293449)";
      node.style.color = error ? "var(--red,#dc2626)" : "var(--text-muted,#aab4c5)";
    }

    function toast(message, error = false) {
      root.querySelector(".vpn-toast")?.remove();
      const node = document.createElement("div");
      node.className = "vpn-toast";
      node.setAttribute("role", error ? "alert" : "status");
      node.textContent = message;
      root.appendChild(node);
      window.setTimeout(() => node.remove(), 4500);
    }

    function closeModal() {
      modalHost.replaceChildren();
    }

    function updateHeaders() {
      const row = root.querySelector("table thead tr");
      if (!row) return;

      const heads = {
        "vpn-overview": ["Peer / ID", "User / device", "VPN IP / network", "Gateway", "Last seen", "Authorization", "Details"],
        gateways: ["Gateway / ID", "Endpoint / region", "Protocol", "Assigned peers", "Latency", "Engine state", "Details"],
        "peers-clients": ["Peer / device", "Assigned user", "Platform", "VPN IP", "Gateway", "Authorization", "Details"],
        "access-policies": ["Policy", "Source → destination", "Requested services", "Priority", "Subject", "State", "Details"],
        "vpn-audit-logs": ["Timestamp", "Actor", "Event", "Target", "Source IP", "Outcome", "Details"],
        remote: ["Session", "User / device", "Source network", "Gateway", "Last activity", "Session state", "Details"]
      };

      if (heads[page]) {
        row.innerHTML = heads[page].map(h => `<th>${esc(h)}</th>`).join("");
      }
    }

    function renderNetworkPools() {
      const body = $("[data-vpn-networks-tbody]");
      const total = $("[data-vpn-networks-count]");
      if (!body) return;

      if (total) {
        total.textContent = `${networks.length} network${networks.length === 1 ? "" : "s"}`;
      }

      if (!networks.length) {
        body.innerHTML = `
          <tr>
            <td colspan="7" style="padding:20px 10px;font-size:12px;color:var(--text-muted,#9aa7bb);">
              No network pools configured. Add the customer's own network ranges; Cartman will not choose a subnet automatically.
            </td>
          </tr>`;
        return;
      }

      body.innerHTML = networks.map(network => {
        const enabled = network.enabled === true || network.enabled === 1;
        const quarantine = network.network_type === "Quarantine";
        const hasGatewayIp = Boolean(String(network.gateway_ip || "").trim());
        const state = !enabled
          ? "Disabled"
          : (!hasGatewayIp ? "Enabled · Gateway IP needed" : "Enabled · Engine not implemented");
        const stateStyle = !enabled
          ? "color:var(--text-muted,#9aa7bb)"
          : (!hasGatewayIp ? "color:var(--warning,#f59e0b)" : "color:var(--success,#22c55e)");

        return `<tr>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);">
            <div style="font-size:12px;font-weight:600;color:var(--text-primary,#eef2ff);">${esc(network.name || "Unnamed network")}</div>
            ${network.description ? `<div style="margin-top:4px;font-size:10px;color:var(--text-muted,#9aa7bb);">${esc(network.description)}</div>` : ""}
          </td>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);font-family:monospace;font-size:12px;">${esc(network.cidr || "—")}</td>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);font-family:monospace;font-size:12px;${hasGatewayIp ? "" : "color:var(--warning,#f59e0b)"}">${esc(network.gateway_ip || "Not configured")}</td>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);font-size:12px;">${esc(network.network_type || "—")}${quarantine ? `<div style="margin-top:4px;font-size:10px;color:var(--text-muted,#9aa7bb);">Onboarding pool</div>` : ""}</td>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);font-size:12px;">${esc(network.department || "—")}</td>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);font-size:12px;${stateStyle}">${esc(state)}</td>
          <td style="padding:13px 10px;border-bottom:1px solid var(--border,#293449);">
            <button class="vpn-btn" type="button" data-vpn-network-edit="${esc(network.id)}">Configure</button>
          </td>
        </tr>`;
      }).join("");
    }

    function renderStats() {
      const values = overview?.counts || {};
      // A stored status is not proof of live connectivity.
      // Until the engine reports availability, no gateway is counted as live.
      const engineAvailable = overview?.engine?.available === true;
      const activeGateways = engineAvailable
        ? gateways.filter(g =>
            String(g.status || "").toLowerCase() === "online"
          ).length
        : 0;
      const unverifiedGateways = gateways.length - activeGateways;

      let result;
      switch (page) {
        case "vpn-overview":
          result = [
            engineAvailable ? (values.connected_tunnels ?? 0) : "—",
            values.gateways ?? gateways.length,
            values.enabled_policies ?? policies.filter(
              p => p.enabled === true || p.enabled === 1
            ).length,
            (values.quarantined || 0) + (values.pending || 0)
          ];
          break;
        case "gateways":
          result = [gateways.length, activeGateways, unverifiedGateways, "—"];
          break;
        case "peers-clients":
          result = [peers.length, 0, peers.filter(p => p.authorization_status === "Blocked").length,
                    peers.filter(p => ["Pending", "Quarantined"].includes(p.authorization_status)).length];
          break;
        case "access-policies":
          result = [
            policies.length,
            policies.filter(p => p.enabled === true || p.enabled === 1).length,
            policies.filter(p => String(p.action || "").toLowerCase() === "allow").length,
            policies.filter(p => String(p.action || "").toLowerCase() === "deny").length
          ];
          break;
        case "vpn-audit-logs":
          result = [audit.length,
                    audit.filter(a => /success/i.test(a.outcome || "")).length,
                    audit.filter(a => /warning/i.test(a.severity || "")).length,
                    audit.filter(a => /denied|blocked|failed/i.test((a.outcome || "") + " " + (a.event || ""))).length];
          break;
        case "remote":
          result = [
            engineAvailable ? (values.connected_tunnels ?? 0) : "—",
            peers.length,
            peers.filter(p => ["Pending", "Quarantined"].includes(p.authorization_status)).length,
            gateways.length
          ];
          break;
        default:
          result = [0, 0, 0, 0];
      }

      $$(".vpn-metric-value").forEach((node, i) => {
        node.textContent = String(result[i] ?? "—");
      });
    }

    function filteredRows() {
      const q = (search?.value || "").trim().toLowerCase();
      const f = filter?.value || "all";

      return records.filter(row => {
        const values = Object.entries(row)
          .filter(([key]) => !key.startsWith("_"))
          .map(([, value]) => value);
        const text = values.join(" ").toLowerCase();
        const state = String(row.status || row.outcome || "").toLowerCase();

        const matchesQuery = !q || text.includes(q);
        const matchesFilter = f === "all" ||
          (f === "active" && /connected|online|healthy|success/.test(state)) ||
          (f === "attention" && /pending|quarantin|warning|review|not installed|not enforced/.test(state)) ||
          (f === "offline" && /offline|disconnected|blocked|denied|failed/.test(state)) ||
          state.includes(f);

        return matchesQuery && matchesFilter;
      });
    }

    function cell(row, key) {
      const value = row[key] ?? "—";

      if (key === "status" || key === "outcome") return pill(value);

      if (key === "id") {
        return `<span class="vpn-primary-cell">${esc(value)}</span>` +
          `<span class="vpn-secondary-cell">${esc(row.sub || row.name || row._id || "")}</span>`;
      }

      if (key === "name" || key === "user" || key === "actor" || key === "time" ||
          key === "event" || key === "endpoint" || key === "path") {
        const sub = key === "endpoint" ? (row.region || "") :
          key === "path" ? (row.sub || "") :
          key === "time" ? (row.id || "") :
          key === "name" ? (row.sub || "") : "";

        return `<span class="vpn-primary-cell">${esc(value)}</span>` +
          (sub ? `<span class="vpn-secondary-cell">${esc(sub)}</span>` : "");
      }

      return esc(value);
    }

    function render() {
      if (!tbody) return;
      const visible = filteredRows();
      const columns = (root.dataset.vpnColumns || "").split("|").filter(Boolean);

      tbody.innerHTML = visible.map(row =>
        `<tr>${columns.map(key => `<td>${cell(row, key)}</td>`).join("")}` +
        `<td><button class="vpn-row-action" type="button" data-vpn-detail="${esc(row._id || "")}">Details ↗</button></td></tr>`
      ).join("");

      if (count) count.textContent = `${visible.length} of ${records.length} records`;
      if (empty) {
        empty.hidden = visible.length > 0;
        if (visible.length === 0) {
          empty.textContent = search?.value || (filter?.value && filter.value !== "all")
            ? "No records match the current filters."
            : page === "remote"
              ? "No live VPN session service is connected. Example sessions are intentionally not shown."
              : "No saved records yet. Create a configuration or refresh the page.";
        }
      }
      renderStats();
    }

    function mapPeer(p) {
      const network = networks.find(n => n.id === p.assigned_network_id);
      return {
        id: shortId("PEER", p.id),
        _id: p.id,
        _raw: p,
        name: p.device_name || "Unnamed device",
        sub: p.username || p.cartman_id || p.id,
        user: p.username || p.cartman_id || "Unassigned",
        platform: p.device_os || "Unknown",
        ip: p.assigned_ip || "Unassigned",
        source: (p.assigned_ip || "No VPN IP") + (network ? ` · ${network.cidr}` : ""),
        gateway: p.gateway_name || "Unassigned",
        activity: p.last_seen_at || "Never reported",
        status: p.authorization_status || "Quarantined",
        detail: p.notes || "No notes.",
        extra: `VPN tunnel: ${p.tunnel_status || "Not installed"}; enforcement: ${p.enforcement_state || "Not applied"}. Network: ${network?.name || p.network_name || "Unknown"}.`
      };
    }

    async function loadData() {
      if (busy) return;
      busy = true;
      try {
        const results = await Promise.all([
          api("/api/vpn/overview"),
          api("/api/vpn/gateways"),
          api("/api/vpn/peers"),
          api("/api/vpn/networks"),
          api("/api/vpn/access-policies"),
          api("/api/vpn/audit-logs?limit=200")
        ]);

        [overview, gateways, peers, networks, policies, audit] = results;
        overview = overview || { counts: {} };
        gateways = Array.isArray(gateways) ? gateways : [];
        peers = Array.isArray(peers) ? peers : [];
        networks = Array.isArray(networks) ? networks : [];
        policies = Array.isArray(policies) ? policies : [];
        audit = Array.isArray(audit) ? audit : [];

        if (page === "gateways") {
          records = gateways.map(g => ({
            id: shortId("GW", g.id),
            _id: g.id,
            _raw: g,
            name: g.name,
            sub: g.region || "Gateway record",
            endpoint: g.endpoint || "Not configured",
            region: g.region || "",
            protocol: g.protocol || "Cartman VPN",
            peers: String(peers.filter(p => p.gateway_id === g.id).length),
            latency: "—",
            status: g.status || "Not installed",
            detail: g.description || "No description.",
            extra: "Configuration is stored. The Cartman VPN engine and live gateway health checks are not implemented."
          }));
        } else if (page === "peers-clients") {
          records = peers.map(mapPeer);
        } else if (page === "vpn-overview") {
          records = peers.map(p => ({
            ...mapPeer(p),
            source: (p.assigned_ip || "No VPN IP") +
              (p.network_cidr ? ` · ${p.network_cidr}` : ""),
            activity: p.last_seen_at || "Never reported"
          }));
        } else if (page === "access-policies") {
          records = policies.map(p => ({
            id: shortId("POL", p.id),
            _id: p.id,
            _raw: p,
            name: p.name,
            sub: p.description || "Stored policy",
            path: `${p.source_network_name || p.source_network_cidr || "Any source"} → ${p.destination || "Unspecified destination"}`,
            services: `${p.protocol || "Any"}${p.ports ? " · " + p.ports : ""} · ${p.action || "Deny"}`,
            priority: p.priority,
            assigned: `${p.subject_type || "All"}${p.subject_value ? " · " + p.subject_value : ""}`,
            status: p.enabled ? "Enabled · Not enforced" : "Disabled · Not enforced",
            detail: p.description || "No description.",
            extra: "This is a saved rule definition only. The VPN engine is not installed, so this policy does not filter network traffic."
          }));
        } else if (page === "vpn-audit-logs") {
          records = audit.map(a => ({
            id: shortId("AUD", a.id),
            _id: a.id,
            _raw: a,
            time: a.created_at || "—",
            actor: a.actor || "Unknown",
            event: a.event || "Event",
            target: `${a.target_type || ""}${a.target_id ? " · " + a.target_id : ""}`,
            ip: a.source_ip || "—",
            outcome: a.outcome || "Recorded",
            detail: a.severity || "Info",
            extra: typeof a.details === "object" ? JSON.stringify(a.details) : String(a.details || "")
          }));
        } else {
          // The control plane intentionally has no fake remote sessions.
          records = [];
        }

        render();
        renderNetworkPools();
        const pools = networks.map(n => `${n.name} ${n.cidr}`).join(" · ") || "No network pools";
        notice(
          `Control plane connected · ${pools}. Cartman VPN engine: not implemented. ` +
          "Saved configuration is not yet enforcing tunnels or firewall rules."
        );
      } catch (error) {
        records = [];
        render();
        notice(`VPN API unavailable: ${error.message}. No demo records are being shown.`, true);
      } finally {
        busy = false;
      }
    }

    function closeDialog() {
      modalHost.replaceChildren();
    }

    function openDetail(id) {
      const row = records.find(item => item._id === id);
      if (!row) return;

      const fields = Object.entries(row)
        .filter(([key]) => !key.startsWith("_"))
        .map(([key, value]) =>
          `<div class="vpn-field ${String(value).length > 38 ? "vpn-field-full" : ""}">` +
          `<label>${esc(key.replace(/([A-Z])/g, " $1").replace(/^./, c => c.toUpperCase()))}</label>` +
          `<div style="font-size:12px;line-height:1.65;overflow-wrap:anywhere;color:var(--text-primary,#eef2ff)">${esc(value)}</div></div>`
        ).join("");

      let decisionControls = "";
      if (page === "peers-clients") {
        const options = networks
          .filter(n => n.network_type === "Department" && n.enabled)
          .map(n => `<option value="${esc(n.id)}">${esc(n.name)} · ${esc(n.cidr)}</option>`)
          .join("");

        decisionControls = `
          <div class="vpn-field-full" style="padding:12px;border:1px solid var(--border,#293449);border-radius:8px">
            <strong>Authorization decision</strong>
            <p style="font-size:11px;line-height:1.6;color:var(--text-muted,#aab4c5)">
              These actions save the control-plane decision only. They do not disconnect a live tunnel or enforce firewall isolation until the VPN engine is integrated.
            </p>
            <label for="vpn-approve-network">Department network for approval</label>
            <select id="vpn-approve-network" data-vpn-approval-network>
              <option value="">Choose network…</option>${options}
            </select>
            ${options ? "" : `<small>No enabled Department network exists yet. Use “Add network” on Gateways first.</small>`}
            <div class="vpn-modal-actions">
              <button class="vpn-btn vpn-btn-primary" type="button" data-vpn-decision="approve" data-peer-id="${esc(row._id)}" ${options ? "" : "disabled"}>Approve & assign</button>
              <button class="vpn-btn" type="button" data-vpn-decision="quarantine" data-peer-id="${esc(row._id)}">Quarantine</button>
              <button class="vpn-btn" type="button" data-vpn-decision="block" data-peer-id="${esc(row._id)}">Block</button>
            </div>
          </div>`;
      }

      modalHost.innerHTML = `
        <div class="vpn-modal-backdrop" data-vpn-dismiss>
          <section class="vpn-modal" role="dialog" aria-modal="true" aria-labelledby="vpn-modal-title">
            <div class="vpn-modal-head">
              <div><h3 id="vpn-modal-title">${esc(row.name || row.id || "Record details")}</h3>
                <p>${esc(row.detail || "Saved VPN configuration")}</p></div>
              <button class="vpn-modal-close" type="button" data-vpn-close aria-label="Close dialog">×</button>
            </div>
            <div class="vpn-form">${fields}${decisionControls}
              <div class="vpn-field-full" style="font-size:10px;line-height:1.6;color:var(--text-muted,#8b98ad)">
                Control-plane record only. Live tunnel status is not available until the VPN engine is installed and connected.
              </div>
              <div class="vpn-modal-actions"><button class="vpn-btn" type="button" data-vpn-close>Close</button></div>
            </div>
          </section>
        </div>`;
    }

    function fieldMarkup(field) {
      const required = field.required ? " required" : "";
      const full = field.full ? " vpn-field-full" : "";
      let input;

      if (field.type === "select") {
        input = `<select id="vpn-field-${esc(field.name)}" name="${esc(field.name)}"${required}>` +
          field.options.map(option => `<option value="${esc(option.value)}" ${option.value === field.value ? "selected" : ""}>${esc(option.label)}</option>`).join("") +
          `</select>`;
      } else if (field.type === "checkbox") {
        input = `<input id="vpn-field-${esc(field.name)}" name="${esc(field.name)}" type="checkbox" ${field.checked ? "checked" : ""}>`;
      } else {
        input = `<input id="vpn-field-${esc(field.name)}" name="${esc(field.name)}" type="${esc(field.type || "text")}" value="${esc(field.value || "")}"${required}${field.min ? ` min="${esc(field.min)}"` : ""}${field.max ? ` max="${esc(field.max)}"` : ""} ${field.placeholder ? `placeholder="${esc(field.placeholder)}"` : ""}>`;
      }

      return `<div class="vpn-field${full}"><label for="vpn-field-${esc(field.name)}">${esc(field.label)}</label>${input}</div>`;
    }

    function openCreate(mode = "") {
      if (page === "vpn-overview") {
        void loadData();
        return;
      }
      if (page === "vpn-audit-logs") {
        exportCsv();
        return;
      }
      if (page === "remote") {
        toast("Live remote sessions are unavailable until the VPN engine is installed.");
        return;
      }

      let title = "";
      let formKind = "";
      let fields = [];

      if (page === "gateways" && mode === "network") {
        title = "Add network pool";
        formKind = "network";
        fields = [
          {name:"name",label:"Network name",required:true},
          {name:"cidr",label:"IPv4 CIDR",required:true},
          {name:"gateway_ip",label:"VPN gateway/interface IP (optional until peer assignment)",placeholder:"Unused host IP inside this CIDR"},
          {name:"network_type",label:"Network type",type:"select",value:"Department",options:[
            {value:"Department",label:"Department"},
            {value:"Quarantine",label:"Quarantine"},
            {value:"Site-to-Site",label:"Site-to-Site"}
          ]},
          {name:"department",label:"Department / owner"},
          {name:"description",label:"Description",full:true}
        ];
      } else if (page === "gateways") {
        title = "Register gateway";
        formKind = "gateway";
        fields = [
          {name:"name",label:"Gateway name",required:true},
          {name:"endpoint",label:"Public endpoint / hostname",placeholder:"vpn.example.com"},
          {name:"region",label:"Location / region"},
          {name:"listen_port",label:"Listen port (optional; protocol design pending)",type:"number",value:"",min:1,max:65535,placeholder:"Not configured"},
          {name:"public_key",label:"Gateway public key (optional)",full:true},
          {name:"description",label:"Description",full:true}
        ];
      } else if (page === "peers-clients") {
        title = "Register peer / client";
        formKind = "peer";
        fields = [
          {name:"device_name",label:"Device name",required:true},
          {name:"cartman_id",label:"Cartman ID / email",placeholder:"user@cartman.com"},
          {name:"username",label:"Username"},
          {name:"device_os",label:"Operating system",type:"select",value:"Windows",options:[
            {value:"Windows",label:"Windows"},
            {value:"Linux",label:"Linux"},
            {value:"Unknown",label:"Unknown"}
          ]},
          {name:"source_ip",label:"Observed source IP (optional)",placeholder:"192.168.1.50"},
          {name:"gateway_id",label:"Gateway (optional)",type:"select",value:"",options:[
            {value:"",label:"Unassigned"},
            ...gateways.map(g => ({value:g.id,label:`${g.name} (${g.status || "Not installed"})`}))
          ]},
          {name:"notes",label:"Notes",full:true}
        ];
      } else if (page === "access-policies") {
        title = "Create access policy";
        formKind = "policy";
        fields = [
          {name:"name",label:"Policy name",required:true},
          {name:"subject_type",label:"Subject type",type:"select",value:"All",options:[
            ...["All","User","Device","Department","Group"].map(v => ({value:v,label:v}))
          ]},
          {name:"subject_value",label:"Subject / group"},
          {name:"source_network_id",label:"Source network",type:"select",value:"",options:[
            {value:"",label:"Any source network"},
            ...networks.filter(n => n.enabled).map(n => ({value:n.id,label:`${n.name} · ${n.cidr}`}))
          ]},
          {name:"destination",label:"Destination CIDR / host / service",placeholder:"10.0.2.0/24"},
          {name:"protocol",label:"Protocol",type:"select",value:"Any",options:[
            ...["Any","TCP","UDP","ICMP"].map(v => ({value:v,label:v}))
          ]},
          {name:"ports",label:"Ports (optional)",placeholder:"443 or 80,443"},
          {name:"action",label:"Action",type:"select",value:"Deny",options:[
            {value:"Deny",label:"Deny (default)"},
            {value:"Allow",label:"Allow"}
          ]},
          {name:"priority",label:"Priority (lower runs first)",type:"number",value:"100",min:1,max:100000,required:true},
          {name:"enabled",label:"Enable rule definition (not enforced yet)",type:"checkbox",checked:false},
          {name:"description",label:"Description",full:true}
        ];
      } else {
        toast("This page does not yet support creating this record.");
        return;
      }

      modalHost.innerHTML = `
        <div class="vpn-modal-backdrop" data-vpn-dismiss>
          <section class="vpn-modal" role="dialog" aria-modal="true" aria-labelledby="vpn-modal-title">
            <div class="vpn-modal-head">
              <div><h3 id="vpn-modal-title">${esc(title)}</h3>
                <p>Saved to Cartman's VPN control-plane database. This does not install or configure a live tunnel.</p></div>
              <button class="vpn-modal-close" type="button" data-vpn-close aria-label="Close dialog">×</button>
            </div>
            <form class="vpn-form" data-vpn-create="${esc(formKind)}">
              ${fields.map(fieldMarkup).join("")}
              <div class="vpn-field-full" style="font-size:10px;line-height:1.6;color:var(--text-muted,#8b98ad)">
                The VPN engine is not implemented. Peer assignment requires an enabled Quarantine pool and its configured gateway/interface IP.
              </div>
              <div class="vpn-modal-actions">
                <button class="vpn-btn" type="button" data-vpn-close>Cancel</button>
                <button class="vpn-btn vpn-btn-primary" type="submit">Save record</button>
              </div>
            </form>
          </section>
        </div>`;

      modalHost.querySelector("input,select")?.focus();
    }

    function openNetworkEdit(networkId) {
      const network = networks.find(item => String(item.id) === String(networkId));
      if (!network) {
        toast("Network record not found. Refresh and try again.", true);
        return;
      }

      const enabled = network.enabled === true || network.enabled === 1;
      const fields = [
        {name:"name",label:"Network name",value:network.name || "",required:true},
        {name:"cidr",label:"IPv4 CIDR",value:network.cidr || "",required:true},
        {name:"gateway_ip",label:"VPN gateway/interface IP",value:network.gateway_ip || "",placeholder:"Unused host IP inside the CIDR"},
        {name:"department",label:"Department / owner",value:network.department || ""},
        {name:"description",label:"Description",value:network.description || "",full:true},
        {name:"enabled",label:"Enable this network",type:"checkbox",checked:enabled,full:true}
      ];

      modalHost.innerHTML = `
        <div class="vpn-modal-backdrop" data-vpn-dismiss>
          <section class="vpn-modal" role="dialog" aria-modal="true" aria-labelledby="vpn-modal-title">
            <div class="vpn-modal-head">
              <div><h3 id="vpn-modal-title">Configure network</h3>
                <p>Changes are validated and saved to Cartman's control-plane database.</p></div>
              <button class="vpn-modal-close" type="button" data-vpn-close aria-label="Close dialog">×</button>
            </div>
            <form class="vpn-form" data-vpn-network-update="${esc(network.id)}">
              <div class="vpn-field-full" style="font-size:11px;line-height:1.6;color:var(--text-muted,#9aa7bb)">
                Type: ${esc(network.network_type || "—")}. Changing a CIDR with assigned peers is blocked. The gateway IP must be a usable host address inside the configured CIDR.
              </div>
              ${fields.map(fieldMarkup).join("")}
              <div class="vpn-field-full" style="font-size:10px;line-height:1.6;color:var(--text-muted,#9aa7bb)">
                Saving this configuration does not install a tunnel or apply firewall rules.
              </div>
              <div class="vpn-modal-actions">
                <button class="vpn-btn" type="button" data-vpn-close>Cancel</button>
                <button class="vpn-btn vpn-btn-primary" type="submit">Save configuration</button>
              </div>
            </form>
          </section>
        </div>`;

      modalHost.querySelector("input,select")?.focus();
    }

    async function submitNetworkUpdate(form) {
      const networkId = form.dataset.vpnNetworkUpdate;
      const data = Object.fromEntries(new FormData(form).entries());
      data.gateway_ip = String(data.gateway_ip || "").trim();
      data.enabled = Boolean(form.querySelector('[name="enabled"]')?.checked);

      const submit = form.querySelector('button[type="submit"]');
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Saving…";
      }

      try {
        await api(`/api/vpn/networks/${encodeURIComponent(networkId)}`, {
          method:"PUT",
          body:JSON.stringify(data)
        });
        closeDialog();
        await loadData();
        toast("Network configuration saved.");
      } catch (error) {
        toast(`Could not save network: ${error.message}`, true);
        if (submit) {
          submit.disabled = false;
          submit.textContent = "Save configuration";
        }
      }
    }

    function exportCsv() {
      const visible = filteredRows();
      if (!visible.length) {
        toast("No actual records match the current view.");
        return;
      }

      const keys = [...new Set(visible.flatMap(row =>
        Object.keys(row).filter(key => !key.startsWith("_"))
      ))];
      const quote = value => `"${String(value ?? "").replace(/"/g, '""')}"`;
      const csv = [
        keys.map(quote).join(","),
        ...visible.map(row => keys.map(key => quote(row[key] ?? "")).join(","))
      ].join("\r\n");

      const url = URL.createObjectURL(new Blob(["\ufeff", csv], {
        type:"text/csv;charset=utf-8"
      }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `cartman-${page}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast("CSV exported from the saved API records.");
    }

    async function submitCreate(form) {
      const kind = form.dataset.vpnCreate;
      const data = Object.fromEntries(new FormData(form).entries());

      form.querySelectorAll('input[type="checkbox"]').forEach(input => {
        data[input.name] = input.checked;
      });

      if (kind === "gateway") {
        data.listen_port = Number(data.listen_port || 0);
      }
      if (kind === "policy") {
        data.priority = Number(data.priority || 100);
        data.enabled = Boolean(data.enabled);
        data.source_network_id = data.source_network_id || null;
      }
      if (kind === "peer") {
        data.gateway_id = data.gateway_id || null;
      }

      const endpoints = {
        network: ["/api/vpn/networks", "POST"],
        gateway: ["/api/vpn/gateways", "POST"],
        peer: ["/api/vpn/peers", "POST"],
        policy: ["/api/vpn/access-policies", "POST"]
      };
      const endpoint = endpoints[kind];
      if (!endpoint) return;

      const submit = form.querySelector('button[type="submit"]');
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Saving…";
      }

      try {
        const result = await api(endpoint[0], {
          method:endpoint[1],
          body:JSON.stringify(data)
        });
        closeDialog();
        await loadData();
        toast(result?.message || "Record saved.");
      } catch (error) {
        toast(`Could not save: ${error.message}`, true);
        if (submit) {
          submit.disabled = false;
          submit.textContent = "Save record";
        }
      }
    }

    async function decidePeer(button) {
      const peerId = button.dataset.peerId;
      const decision = button.dataset.vpnDecision;
      const payload = { decision };

      if (decision === "approve") {
        const select = modalHost.querySelector("[data-vpn-approval-network]");
        if (!select?.value) {
          toast("Select an enabled Department network before approving.", true);
          return;
        }
        payload.network_id = select.value;
      }

      button.disabled = true;
      try {
        const result = await api(`/api/vpn/peers/${encodeURIComponent(peerId)}/decision`, {
          method:"POST",
          body:JSON.stringify(payload)
        });
        closeDialog();
        await loadData();
        toast(result?.message || "Authorization decision saved.");
      } catch (error) {
        toast(`Decision was not saved: ${error.message}`, true);
        button.disabled = false;
      }
    }

    root.addEventListener("click", event => {
      const networkEdit = event.target.closest("[data-vpn-network-edit]");
      if (networkEdit) {
        openNetworkEdit(networkEdit.dataset.vpnNetworkEdit);
        return;
      }

      const detail = event.target.closest("[data-vpn-detail]");
      if (detail) {
        openDetail(detail.dataset.vpnDetail);
        return;
      }

      if (event.target.closest("[data-vpn-close]")) {
        closeDialog();
        return;
      }

      const dismiss = event.target.closest("[data-vpn-dismiss]");
      if (dismiss && event.target === dismiss) {
        closeDialog();
        return;
      }

      const decision = event.target.closest("[data-vpn-decision]");
      if (decision) {
        void decidePeer(decision);
        return;
      }

      const action = event.target.closest("button[data-vpn-action]");
      if (action) {
        void openCreate(action.dataset.vpnAction || "");
        return;
      }

      if (event.target.closest("[data-vpn-export]")) {
        exportCsv();
        return;
      }

      if (event.target.closest("[data-vpn-refresh]")) {
        void loadData();
      }
    });

    root.addEventListener("submit", event => {
      const networkForm = event.target.closest("[data-vpn-network-update]");
      if (networkForm) {
        event.preventDefault();
        void submitNetworkUpdate(networkForm);
        return;
      }

      const form = event.target.closest("[data-vpn-create]");
      if (!form) return;
      event.preventDefault();
      void submitCreate(form);
    });

    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && modalHost.childElementCount) closeDialog();
    });

    search?.addEventListener("input", render);
    filter?.addEventListener("change", render);
    updateHeaders();

    notice("Connecting to Cartman VPN control plane…");
    void loadData();
    return true;
  }

  window.CartmanVpnControlPlane = { mount };
})();
