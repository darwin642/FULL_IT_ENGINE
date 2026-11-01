(() => {
  "use strict";
  const api = async (path, options = {}) => {
    const init = { method: options.method || "GET", credentials: "same-origin", headers: { Accept: "application/json" } };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const response = await fetch(path, init);
    const text = response.status === 204 ? "" : await response.text();
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch { data = { detail: text }; } }
    if (!response.ok) throw new Error(data?.detail || `${response.status} ${response.statusText}`);
    return data;
  };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const levelOptions = selected => ["None", "L1", "L2", "L3"].map(level => `<option value="${level}" ${level === selected ? "selected" : ""}>${level === "None" ? "Not a support agent" : level}</option>`).join("");

  function init() {
    const host = document.querySelector('[data-identity-security="users-groups"]');
    if (!host || document.querySelector("#iam-support-routing-panel")) return;
    const panel = document.createElement("section");
    panel.id = "iam-support-routing-panel";
    panel.className = "workspace-module iam-support-routing";
    panel.innerHTML = `
      <div class="isr-head">
        <div><span class="isr-eyebrow">SERVICE OPERATIONS / STAFFING</span><h2>Support routing</h2>
        <p>Admins configure support tiers here. Each staff member manages their own Online / Offline status from the Cartman top bar.</p></div>
        <button class="io-btn" type="button" data-isr-refresh>↻ Refresh</button>
      </div>
      <div class="isr-summary" data-isr-summary></div>
      <div class="isr-alert" data-isr-alert hidden role="status"></div>
      <div class="isr-table-wrap"><table class="isr-table"><thead><tr><th>Person</th><th>Support tier</th><th>Availability · status</th><th>Account link</th></tr></thead><tbody data-isr-rows><tr><td colspan="4">Loading IAM support users…</td></tr></tbody></table></div>
      <p class="isr-footnote">A ticket is assigned only if the IAM user is Active, linked to an active Cartman login (matching username), configured for a support tier, and Online. New assignments use least-active-ticket balancing. Existing assignments are not automatically moved when someone goes Offline.</p>`;
    host.insertAdjacentElement("afterend", panel);

    const rows = panel.querySelector("[data-isr-rows]");
    const summary = panel.querySelector("[data-isr-summary]");
    const alert = panel.querySelector("[data-isr-alert]");
    let items = [];
    let saving = false;

    const notify = (message, bad = false) => {
      alert.hidden = !message;
      alert.textContent = message || "";
      alert.classList.toggle("is-error", Boolean(bad));
    };

    function render() {
      const eligible = items.filter(item => item.status === "Active" && item.account_linked && item.support_level !== "None" && item.support_online);
      summary.innerHTML = `
        <div><span>IAM users</span><strong>${items.length}</strong></div>
        <div><span>Online support agents</span><strong>${eligible.length}</strong></div>
        <div><span>L1 online</span><strong>${eligible.filter(item => item.support_level === "L1").length}</strong></div>
        <div><span>L2 / L3 online</span><strong>${eligible.filter(item => ["L2", "L3"].includes(item.support_level)).length}</strong></div>`;
      if (!items.length) {
        rows.innerHTML = `<tr><td colspan="4">No IAM users found. Add users in the directory first.</td></tr>`;
        return;
      }
      rows.innerHTML = items.map(item => {
        const enabled = item.status === "Active" && item.account_linked && item.support_level !== "None";
        const on = Boolean(item.support_online);
        return `<tr data-isr-user="${esc(item.id)}">
          <td><strong>${esc(item.name)}</strong><small>${esc(item.username || "No username")} · ${esc(item.department || "No department")}</small><small>${esc(item.email)}</small></td>
          <td><select data-isr-level aria-label="Support tier for ${esc(item.name)}" ${saving ? "disabled" : ""}>${levelOptions(item.support_level || "None")}</select></td>
          <td><span class="isr-status ${on && item.account_linked && item.status === "Active" && item.support_level !== "None" ? "is-online" : "is-offline"}">${on && item.account_linked && item.status === "Active" && item.support_level !== "None" ? "● Online" : "● Offline"}</span></td>
          <td>${item.account_linked ? `<span class="isr-linked">● Linked</span>` : `<span class="isr-unlinked">Not linked</span><small>Username must match an active Cartman login.</small>`}${item.status !== "Active" ? `<small>IAM status: ${esc(item.status)}; activate this user first.</small>` : ""}</td>
        </tr>`;
      }).join("");
    }



    async function load() {
      rows.innerHTML = `<tr><td colspan="4">Loading IAM support users…</td></tr>`;
      notify("");
      try {
        const response = await api("/api/iam/support-routing");
        items = Array.isArray(response?.items) ? response.items : [];
        render();
      } catch (error) {
        rows.innerHTML = `<tr><td colspan="4">Could not load routing settings.</td></tr>`;
        notify(`Could not load IAM routing settings: ${error.message}`, true);
      }
    }

    async function save(row) {
      if (saving) return;
      const item = items.find(candidate => candidate.id === row.dataset.isrUser);
      if (!item) return;
      const level = row.querySelector("[data-isr-level]").value;
      saving = true;
      render();
      try {
        const result = await api(`/api/iam/users/${encodeURIComponent(item.id)}/support-routing`, {
          method: "PUT", body: { support_level: level }
        });
        const index = items.findIndex(candidate => candidate.id === result.id);
        if (index >= 0) items[index] = { ...items[index], ...result };
        notify(`${result.name}: ${result.support_level === "None" ? "not in a support queue" : result.support_level} · ${result.support_online ? "Online" : "Offline"}.`);
        render();
      } catch (error) {
        notify(`Could not save ${item.name}: ${error.message}`, true);
        await load();
      } finally {
        saving = false;
        render();
      }
    }

    panel.addEventListener("change", event => {
      const row = event.target.closest("[data-isr-user]");
      if (row && event.target.matches("[data-isr-level]")) void save(row);
    });

    panel.addEventListener("click", event => {
      if (event.target.closest("[data-isr-refresh]")) void load();
    });
    void load();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
