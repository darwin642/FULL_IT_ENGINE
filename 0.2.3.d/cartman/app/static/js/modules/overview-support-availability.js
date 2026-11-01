/* CARTMAN_OVERVIEW_SUPPORT_AVAILABILITY_V1 */
(() => {
  "use strict";
  const API = "/api/iam/me/support-availability";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

  async function request(path, options = {}) {
    const init = {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const response = await fetch(path, init);
    const raw = response.status === 204 ? "" : await response.text();
    let data = null;
    if (raw) {
      try { data = JSON.parse(raw); }
      catch (_) { data = { detail: raw }; }
    }
    if (!response.ok) {
      const error = new Error(data?.detail || `${response.status} ${response.statusText}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function chooseMountPoint() {
    const candidates = [
      ...document.querySelectorAll("h1, h2, h3, [role='heading']")
    ];
    const welcome = candidates.find(node => /^welcome back\b/i.test((node.textContent || "").trim()));
    if (welcome) {
      return welcome.closest(".dashboard-welcome, .welcome-section, .dashboard-header, .page-header")
        || welcome.parentElement?.parentElement
        || welcome.parentElement;
    }
    return document.querySelector("main") || document.body;
  }

  function init() {
    if (location.pathname !== "/" && location.pathname !== "/static/index.html") return;
    if (document.querySelector("#overview-support-availability")) return;
    const mount = chooseMountPoint();
    if (!mount) return;

    const card = document.createElement("section");
    card.id = "overview-support-availability";
    card.className = "osa-card";
    card.setAttribute("aria-labelledby", "osa-title");
    card.innerHTML = `
      <div class="osa-copy">
        <span class="osa-kicker">YOUR WORKSPACE / SUPPORT STATUS</span>
        <h2 id="osa-title">Support availability</h2>
        <p data-osa-description>Checking your Cartman support profile…</p>
        <div class="osa-meta"><span data-osa-tier>Support tier · —</span><span data-osa-account>Checking account link…</span></div>
        <p class="osa-message" data-osa-message role="status" aria-live="polite"></p>
      </div>
      <label class="osa-toggle" for="osa-online">
        <span class="osa-toggle-copy"><strong class="osa-state" data-osa-state>Loading status</strong><small>Control whether new tickets can be assigned to you</small></span>
        <input id="osa-online" type="checkbox" data-osa-online disabled>
        <span class="osa-track" aria-hidden="true"><span></span></span>
      </label>`;

    // Put the control directly below the dashboard welcome/hero. If the project
    // changes the hero markup, use the main content's first dashboard section.
    if (mount.matches("main")) mount.insertBefore(card, mount.firstElementChild);
    else mount.insertAdjacentElement("afterend", card);

    const toggle = card.querySelector("[data-osa-online]");
    const state = card.querySelector("[data-osa-state]");
    const desc = card.querySelector("[data-osa-description]");
    const tier = card.querySelector("[data-osa-tier]");
    const account = card.querySelector("[data-osa-account]");
    const message = card.querySelector("[data-osa-message]");
    let current = null;
    let saving = false;

    function render(profile) {
      current = profile;
      const eligible = Boolean(profile?.eligible);
      const online = Boolean(profile?.support_online);
      toggle.checked = online;
      toggle.disabled = !eligible || saving;
      state.textContent = eligible ? (online ? "Online · accepting tickets" : "Offline · not accepting new tickets") : "Not configured for ticket routing";
      state.classList.toggle("is-online", eligible && online);
      state.classList.toggle("is-offline", !online || !eligible);
      tier.textContent = `Support tier · ${profile?.support_level || "Not configured"}`;
      account.textContent = profile?.account_linked ? "Cartman account linked" : "Account not linked";
      desc.textContent = eligible
        ? "Set yourself Online while you are available for support work. Switching Offline stops new assignments; existing tickets remain assigned to you."
        : "Your account must be linked to an active IAM user with an L1, L2 or L3 support tier before you can go Online.";
    }

    async function load() {
      toggle.disabled = true;
      message.textContent = "";
      message.classList.remove("is-error");
      try {
        const profile = await request(API);
        render(profile);
      } catch (error) {
        current = null;
        toggle.checked = false;
        toggle.disabled = true;
        state.textContent = error.status === 404 ? "Support profile not configured" : "Status unavailable";
        tier.textContent = "Support tier · —";
        account.textContent = "Not linked";
        desc.textContent = error.status === 404
          ? "Ask a Cartman administrator to create or link your IAM user and assign your support tier."
          : "Could not load your support status. Refresh Overview and try again.";
        if (error.status !== 404) {
          message.textContent = error.message;
          message.classList.add("is-error");
        }
      }
    }

    toggle.addEventListener("change", async () => {
      if (!current?.eligible || saving) {
        await load();
        return;
      }
      const requested = Boolean(toggle.checked);
      saving = true;
      toggle.disabled = true;
      message.textContent = "Saving availability…";
      message.classList.remove("is-error");
      try {
        const result = await request(API, {
          method: "PUT",
          body: { support_online: requested }
        });
        message.textContent = result.support_online
          ? "You are Online. Eligible queued tickets can now be assigned to you."
          : "You are Offline. No new tickets will be assigned to you.";
        render({ ...current, ...result, eligible: true });
      } catch (error) {
        message.textContent = `Could not update status: ${error.message}`;
        message.classList.add("is-error");
        await load();
      } finally {
        saving = false;
        toggle.disabled = !current?.eligible;
      }
    });

    void load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
