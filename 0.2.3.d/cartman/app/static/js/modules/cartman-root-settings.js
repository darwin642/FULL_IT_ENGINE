/* CARTMAN_ROOT_SETTINGS_UI_V1 */
(() => {
  "use strict";
  const root = document.querySelector('#admin-page-root[data-admin-page="settings"]');
  if (!root || root.dataset.rootControls === "1") return;
  root.dataset.rootControls = "1";
  let rootGranted = false;
  function mountRootPanel() {
    if (!rootGranted || !root.isConnected || root.querySelector(".cartman-root-zone")) return;
    const panel = document.createElement("section");
    panel.className = "cartman-root-zone";
    panel.innerHTML = `
      <div class="cartman-root-zone-head">
        <div>
          <span class="cartman-root-zone-kicker">ROOT SECURITY</span>
          <h3>Kill Switch</h3>
          <p>Cartman project decommissioning controls. This build contains the protected information and acknowledgement page only; the Windows removal engine is planned for a later build.</p>
        </div>
        <a class="cartman-root-kill-btn" href="/pages/kill-switch/">Open Kill Switch</a>
      </div>`;
    root.appendChild(panel);
  }
  fetch("/api/admin/root-access", {
    credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }
  }).then(async response => {
    if (!response.ok) return null;
    return response.json();
  }).then(data => {
    rootGranted = !!data && data.is_root === true;
    mountRootPanel();
    if (rootGranted && root.isConnected) {
      const observer = new MutationObserver(() => mountRootPanel());
      observer.observe(root, { childList: true, subtree: true });
    }
  }).catch(() => {});
})();
