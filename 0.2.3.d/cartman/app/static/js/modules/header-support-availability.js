/* CARTMAN_HEADER_SUPPORT_AVAILABILITY_V1 */
(() => {
  "use strict";
  const API = "/api/iam/me/support-availability";

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

  function findActions() {
    return document.querySelector(
      ".topbar .top-actions, header .top-actions, .topbar .header-actions, header .header-actions, .top-actions"
    );
  }

  function mountInHeader(host, actions) {
    const profile = actions.querySelector([
      "[data-profile-menu-toggle]", "[data-profile-toggle]", "[data-user-menu-toggle]",
      "[aria-label*='profile' i]", "[aria-label*='account' i]", "[title*='profile' i]",
      "[title*='account' i]", ".profile-menu", ".profile-trigger", ".user-menu", ".account-menu"
    ].join(","));

    if (profile && profile !== host) {
      const anchor = profile.parentElement === actions
        ? profile
        : (profile.parentElement && profile.parentElement.parentElement === actions ? profile.parentElement : null);
      if (anchor) {
        actions.insertBefore(host, anchor);
        return;
      }
    }

    // Some Cartman header versions do not expose a profile selector. Place the
    // switch at the far right of the existing action group in that case.
    actions.appendChild(host);
  }

  function init() {
    // This script is loaded by the dashboard and all standalone pages that
    // expose a Cartman top bar. Mount wherever a supported top-actions region exists.
    if (document.querySelector("#cartman-header-support-availability")) return;
    const actions = findActions();
    if (!actions) return;

    const host = document.createElement("div");
    host.id = "cartman-header-support-availability";
    host.className = "cha-wrap";
    host.setAttribute("role", "group");
    host.setAttribute("aria-label", "Support availability");
    host.innerHTML = `
      <span class="cha-dot" aria-hidden="true"></span>
      <span class="cha-state" data-cha-state>Offline</span>
      <label class="cha-switch" title="Control whether new support tickets can be assigned to you">
        <input type="checkbox" data-cha-toggle aria-label="Accept new support tickets" disabled>
        <span class="cha-track" aria-hidden="true"><span></span></span>
      </label>
      <span class="cha-sr-only" data-cha-message role="status" aria-live="polite"></span>`;
    mountInHeader(host, actions);

    const toggle = host.querySelector("[data-cha-toggle]");
    const state = host.querySelector("[data-cha-state]");
    const message = host.querySelector("[data-cha-message]");
    let current = null;
    let saving = false;

    function render(profile) {
      current = profile;
      const eligible = Boolean(profile?.eligible);
      const online = Boolean(profile?.support_online);
      toggle.checked = online;
      toggle.disabled = !eligible || saving;
      host.classList.toggle("is-online", eligible && online);
      host.classList.toggle("is-offline", !eligible || !online);
      state.textContent = !eligible ? "Not on queue" : (online ? "Online" : "Offline");
      const tier = profile?.support_level || "Not configured";
      host.title = eligible
        ? `${tier} support · ${online ? "Accepting new tickets" : "Not accepting new tickets"}. Toggle to change your availability.`
        : `Support status unavailable. Link your login to an Active IAM user with an L1, L2 or L3 tier. Current tier: ${tier}.`;
    }

    async function load() {
      toggle.disabled = true;
      try {
        const profile = await request(API);
        render(profile);
      } catch (error) {
        current = null;
        toggle.checked = false;
        toggle.disabled = true;
        host.classList.remove("is-online");
        host.classList.add("is-offline");
        state.textContent = error.status === 404 ? "Not linked" : "Unavailable";
        host.title = error.status === 404
          ? "Your login is not linked to an IAM user. Ask an administrator to create the directory record and assign your L1/L2/L3 tier."
          : `Could not load support availability: ${error.message}`;
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
      host.classList.add("is-saving");
      message.textContent = "Saving support availability";
      try {
        const result = await request(API, {
          method: "PUT",
          body: { support_online: requested }
        });
        render({ ...current, ...result, eligible: true });
        message.textContent = result.support_online
          ? "You are Online and can receive new ticket assignments."
          : "You are Offline and will not receive new ticket assignments.";
      } catch (error) {
        message.textContent = `Could not update status: ${error.message}`;
        await load();
      } finally {
        saving = false;
        host.classList.remove("is-saving");
        toggle.disabled = !current?.eligible;
      }
    });

    void load();
  }

  // Keep the observer active because standalone navigation can replace
  // the header after the initial page load.
  let mountObserver = null;

  function tryInit() {
    const actions = findActions();
    if (!actions) return;

    let host = document.querySelector("#cartman-header-support-availability");

    if (host) {
      // Reattach the existing switch if the header container was replaced.
      // Keeping the node preserves its event listeners.
      if (!actions.contains(host)) {
        mountInHeader(host, actions);
      }
      return;
    }

    init();
  }

  if (document.documentElement && typeof MutationObserver !== "undefined") {
    mountObserver = new MutationObserver(() => {
      tryInit();
    });

    mountObserver.observe(document.documentElement, {
      childList: true,
      subtree: true
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryInit);
  } else {
    tryInit();
  }

})();
