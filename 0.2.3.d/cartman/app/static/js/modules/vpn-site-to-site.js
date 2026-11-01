(() => {
  "use strict";

  const root = document.querySelector("[data-site-to-site]");
  if (!root || root.dataset.initialized === "true") return;
  root.dataset.initialized = "true";

  const $ = (selector, scope = root) => scope.querySelector(selector);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  const tbody = $("[data-site-tbody]");
  const search = $("[data-site-search]");
  const stateNode = $("[data-site-api-state]");
  const countNode = $("[data-site-count]");
  const configuredNode = $("[data-site-configured]");
  const activeNode = $("[data-site-active]");
  const draftNode = $("[data-site-draft]");
  const emptyNode = $("[data-site-empty]");
  const noticeNode = $("[data-site-notice]");
  const modalHost = $("[data-site-modal-host]");
  const createButton = $("[data-site-create]");

  let records = [];
  let gateways = [];
  let loading = false;

  async function api(url, options = {}) {
    const headers = {
      Accept: "application/json",
      ...(options.headers || {})
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers
    });

    const raw = await response.text();
    let data = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch {
      data = raw;
    }

    if (!response.ok) {
      const detail = data && typeof data === "object"
        ? data.detail || data.message
        : data;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return data;
  }

  function notify(message, error = false) {
    if (!noticeNode) return;
    noticeNode.textContent = message;
    noticeNode.style.color = error
      ? "var(--red,#dc2626)"
      : "var(--text-muted,#9aa7bb)";
    noticeNode.setAttribute("role", error ? "alert" : "status");
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

  function visibleRecords() {
    const query = (search?.value || "").trim().toLocaleLowerCase();
    return records.filter(record => {
      const text = [
        record.name, record.id,
        record.gateway_a_name, record.gateway_b_name,
        record.local_subnet, record.remote_subnet,
        record.status, record.description
      ].join(" ").toLocaleLowerCase();
      return !query || text.includes(query);
    });
  }

  function render() {
    if (!tbody) return;

    const visible = visibleRecords();

    if (countNode) {
      countNode.textContent = `${visible.length} of ${records.length} definitions`;
    }
    if (configuredNode) {
      configuredNode.textContent = String(records.length);
    }
    if (activeNode) {
      activeNode.textContent = "0";
    }
    if (draftNode) {
      draftNode.textContent = String(records.filter(
        record => String(record.status || "Draft").toLowerCase() === "draft"
      ).length);
    }

    if (!visible.length) {
      tbody.innerHTML = "";
      if (emptyNode) {
        emptyNode.hidden = false;
        emptyNode.innerHTML = search?.value
          ? "No definitions match this search."
          : gateways.length < 2
            ? 'No saved definitions. Configure at least two gateway records first in <a href="/pages/gateways/">Gateways</a>.'
            : "No site-to-site definitions are saved yet. Create a definition to get started.";
      }
      return;
    }

    if (emptyNode) emptyNode.hidden = true;

    tbody.innerHTML = visible.map(record => `
      <tr>
        <td class="site-s2s-connection-cell">
          <div class="site-s2s-connection-name">${esc(record.name || "Unnamed definition")}</div>
          <div class="site-s2s-connection-id">${esc(record.id || "")}</div>
        </td>
        <td>${esc(record.gateway_a_name || "Gateway unavailable")}</td>
        <td>${esc(record.gateway_b_name || "Gateway unavailable")}</td>
        <td><span class="vpn-primary-cell">${esc(record.local_subnet || "—")}</span></td>
        <td><span class="vpn-primary-cell">${esc(record.remote_subnet || "—")}</span></td>
        <td class="site-s2s-status-cell">
          <div class="site-s2s-status-stack">
            <span class="vpn-status is-pending">${esc(record.status || "Draft")}</span>
            <span class="site-s2s-status-note">Tunnel not established</span>
          </div>
        </td>
        <td>
          <div class="site-s2s-row-actions">
            <button class="vpn-btn" type="button" data-site-edit="${esc(record.id)}">Configure</button>
            <button class="vpn-btn" type="button" data-site-delete="${esc(record.id)}">Delete</button>
          </div>
        </td>
      </tr>
    `).join("");
  }

  async function load() {
    if (loading) return;
    loading = true;
    if (stateNode) stateNode.textContent = "Connecting to Cartman API…";
    if (tbody) {
      tbody.innerHTML = '<tr><td colspan="7">Loading saved definitions…</td></tr>';
    }

    try {
      const [linkData, gatewayData] = await Promise.all([
        api("/api/vpn/site-to-site"),
        api("/api/vpn/gateways")
      ]);

      if (!Array.isArray(linkData) || !Array.isArray(gatewayData)) {
        throw new Error("Unexpected API response format.");
      }

      records = linkData;
      gateways = gatewayData;

      if (stateNode) {
        stateNode.textContent = "Cartman API · Online";
        stateNode.style.color = "var(--green,#16a34a)";
      }

      if (createButton) {
        createButton.disabled = gateways.length < 2;
        createButton.title = gateways.length < 2
          ? "Configure two gateway records before creating a site-to-site definition."
          : "Create a site-to-site definition";
      }

      render();
      notify(
        `Loaded ${records.length} saved definition(s) and ${gateways.length} gateway record(s). ` +
        "Cartman VPN engine is not implemented; no live tunnel or firewall change is applied."
      );
    } catch (error) {
      records = [];
      gateways = [];
      if (stateNode) {
        stateNode.textContent = "Cartman API · Unavailable";
        stateNode.style.color = "var(--red,#dc2626)";
      }
      if (createButton) createButton.disabled = true;
      render();
      notify(`Could not load Site-to-Site data: ${error.message}`, true);
    } finally {
      loading = false;
    }
  }

  function field(name, label, value = "", type = "text", required = false) {
    return `
      <div class="vpn-field">
        <label for="site-field-${esc(name)}">${esc(label)}</label>
        <input
          id="site-field-${esc(name)}"
          name="${esc(name)}"
          type="${esc(type)}"
          value="${esc(value)}"
          ${required ? "required" : ""}
          ${type === "text" && (name === "local_subnet" || name === "remote_subnet")
            ? 'placeholder="Enter the site network CIDR"' : ""}
        >
      </div>`;
  }

  function gatewaySelect(name, label, selectedId = "") {
    const options = gateways.map(gateway => `
      <option value="${esc(gateway.id)}"
        ${String(gateway.id) === String(selectedId) ? "selected" : ""}>
        ${esc(gateway.name)} · ${esc(gateway.status || "Not verified")}
      </option>
    `).join("");

    return `
      <div class="vpn-field">
        <label for="site-field-${esc(name)}">${esc(label)}</label>
        <select id="site-field-${esc(name)}" name="${esc(name)}" required>
          <option value="">Choose a gateway…</option>
          ${options}
        </select>
      </div>`;
  }

  function openForm(record = null) {
    if (gateways.length < 2) {
      toast("Configure at least two gateway records before creating a Site-to-Site definition.", true);
      return;
    }

    const editing = Boolean(record);
    const title = editing ? "Configure Site-to-Site definition" : "Create Site-to-Site definition";

    modalHost.innerHTML = `
      <div class="vpn-modal-backdrop" data-site-dismiss>
        <section class="vpn-modal" role="dialog" aria-modal="true" aria-labelledby="site-modal-title">
          <div class="vpn-modal-head">
            <div>
              <h3 id="site-modal-title">${esc(title)}</h3>
              <p>Save a connection definition between two gateway records.</p>
            </div>
            <button class="vpn-modal-close" type="button" data-site-close aria-label="Close">×</button>
          </div>
          <form class="vpn-form" data-site-form="${editing ? "edit" : "create"}"
            ${editing ? `data-site-id="${esc(record.id)}"` : ""}>
            ${field("name", "Connection name", record?.name || "", "text", true)}
            ${gatewaySelect("gateway_a_id", "Gateway A", record?.gateway_a_id || "")}
            ${gatewaySelect("gateway_b_id", "Gateway B", record?.gateway_b_id || "")}
            ${field("local_subnet", "Local subnet (CIDR)", record?.local_subnet || "", "text", true)}
            ${field("remote_subnet", "Remote subnet (CIDR)", record?.remote_subnet || "", "text", true)}
            ${field("description", "Description", record?.description || "")}
            <div class="vpn-field-full" style="font-size:11px;line-height:1.6;color:var(--text-muted,#9aa7bb)">
              The API validates CIDR format, ensures the two gateways differ, and rejects overlapping local and remote subnets.
              Saving a definition does not establish a VPN tunnel.
            </div>
            <div class="vpn-modal-actions">
              <button class="vpn-btn" type="button" data-site-close>Cancel</button>
              <button class="vpn-btn vpn-btn-primary" type="submit">Save definition</button>
            </div>
          </form>
        </section>
      </div>`;

    const form = $("[data-site-form]", modalHost);
    const gatewayA = form.elements.gateway_a_id;
    const gatewayB = form.elements.gateway_b_id;

    function keepGatewaysDistinct() {
      [...gatewayB.options].forEach(option => {
        option.disabled = Boolean(option.value && option.value === gatewayA.value);
      });
      if (gatewayA.value && gatewayA.value === gatewayB.value) gatewayB.value = "";
    }

    gatewayA.addEventListener("change", keepGatewaysDistinct);
    gatewayB.addEventListener("change", keepGatewaysDistinct);
    keepGatewaysDistinct();
    form.querySelector("input")?.focus();
  }

  async function submitForm(form) {
    const mode = form.dataset.siteForm;
    const id = form.dataset.siteId;
    const data = Object.fromEntries(new FormData(form).entries());

    if (!data.gateway_a_id || !data.gateway_b_id ||
        data.gateway_a_id === data.gateway_b_id) {
      toast("Choose two different gateways.", true);
      return;
    }

    const submit = form.querySelector('button[type="submit"]');
    if (submit) {
      submit.disabled = true;
      submit.textContent = "Saving…";
    }

    try {
      const url = mode === "edit"
        ? `/api/vpn/site-to-site/${encodeURIComponent(id)}`
        : "/api/vpn/site-to-site";
      const result = await api(url, {
        method: mode === "edit" ? "PUT" : "POST",
        body: JSON.stringify(data)
      });

      closeModal();
      await load();
      toast(result?.message || "Definition saved as Draft.");
    } catch (error) {
      toast(`Could not save definition: ${error.message}`, true);
      if (submit) {
        submit.disabled = false;
        submit.textContent = "Save definition";
      }
    }
  }

  async function deleteRecord(id) {
    const record = records.find(item => String(item.id) === String(id));
    if (!record) return;

    if (!window.confirm(
      `Delete the saved definition "${record.name}"?\n\nThis removes the definition record only; it does not change a live tunnel.`
    )) return;

    try {
      const result = await api(`/api/vpn/site-to-site/${encodeURIComponent(id)}`, {
        method: "DELETE"
      });
      await load();
      toast(result?.message || "Definition deleted.");
    } catch (error) {
      toast(`Could not delete definition: ${error.message}`, true);
    }
  }

  document.addEventListener("click", event => {
    if (event.target.closest("[data-site-refresh]")) {
      void load();
      return;
    }
    if (event.target.closest("[data-site-create]")) {
      openForm();
      return;
    }

    const editButton = event.target.closest("[data-site-edit]");
    if (editButton) {
      const record = records.find(item => String(item.id) === editButton.dataset.siteEdit);
      if (record) openForm(record);
      return;
    }

    const deleteButton = event.target.closest("[data-site-delete]");
    if (deleteButton) {
      void deleteRecord(deleteButton.dataset.siteDelete);
      return;
    }

    if (event.target.closest("[data-site-close]")) {
      closeModal();
      return;
    }

    const backdrop = event.target.closest("[data-site-dismiss]");
    if (backdrop && event.target === backdrop) closeModal();
  });

  document.addEventListener("submit", event => {
    const form = event.target.closest("[data-site-form]");
    if (!form) return;
    event.preventDefault();
    void submitForm(form);
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && modalHost.childElementCount) closeModal();
  });

  search?.addEventListener("input", render);
  void load();
})();
