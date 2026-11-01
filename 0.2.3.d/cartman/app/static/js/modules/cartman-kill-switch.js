/* CARTMAN_KILL_SWITCH_UI_ONLY_V1 */
(() => {
  "use strict";
  const root = document.getElementById("cartman-kill-switch-root");
  if (!root || root.dataset.initialized === "1") return;
  root.dataset.initialized = "1";
  const ACK = "anlıyorum ne yaptığımın farkındayım, bütün dosyaların yok edileceğini biliyorum ve sorumluluğu kabul ediyorum";
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function gate() {
    root.innerHTML = `
      <section class="ck-card ck-danger">
        <div class="ck-kicker">ROOT ONLY · EXTREME DANGER</div>
        <h1 class="ck-title">Cartman Kill Switch</h1>
        <div class="ck-warning">
          <strong>STOP. READ THIS BEFORE CONTINUING.</strong><br>
          If there is no severe cyberattack or an equally serious emergency, leave this page immediately.<br>
          This page is planned to permanently decommission the Cartman application and its own installation files. It is not a PC wipe and must never target Windows, personal files, or other applications.<br>
          Do not proceed unless you understand exactly what the future operation is intended to do. Do not enter this page without a verified backup stored outside the Cartman installation folder.<br>
          <strong>The Kill Switch execution engine is NOT installed in this build. No deletion or shutdown action is available here.</strong>
        </div>
        <p class="ck-copy">To reveal the protected preview, type the following acknowledgement exactly. Typing it does not execute any operation.</p>
        <form id="ck-gate-form" class="ck-form">
          <label class="ck-field">Required acknowledgement
            <input name="ack" autocomplete="off" spellcheck="false" placeholder="Type the full acknowledgement">
          </label>
          <button class="ck-btn ck-btn-danger" type="submit" disabled>Unlock Kill Switch preview</button>
          <div class="ck-error" role="status" aria-live="polite"></div>
        </form>
      </section>`;
    const form = root.querySelector("#ck-gate-form");
    const input = form.elements.ack;
    const button = form.querySelector("button");
    input.addEventListener("input", () => { button.disabled = input.value !== ACK; });
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (input.value !== ACK) return;
      showPreview();
    });
  }
  function showPreview() {
    root.innerHTML = `
      <section class="ck-card ck-danger">
        <div class="ck-kicker">ROOT ONLY · PROTECTED PREVIEW</div>
        <h1 class="ck-title">Kill Switch — execution unavailable</h1>
        <div class="ck-status">
          <strong>Current build status: UI and authorization only.</strong><br>
          The Windows-specific Kill Switch engine is planned for a later build. This page cannot stop services, remove files, uninstall Cartman, or modify the host operating system.
        </div>
        <p class="ck-copy">Planned safeguards for the Windows production build:</p>
        <ul class="ck-note">
          <li>Resolve the exact Cartman installation directory selected during first-run setup.</li>
          <li>Require a verified encrypted Full System backup outside that directory.</li>
          <li>Confirm Windows service state, Administrator elevation, installation identity and target boundaries.</li>
          <li>Require a separate final confirmation before any Cartman-only decommissioning action.</li>
        </ul>
        <p class="ck-note">No destructive API endpoint is registered in this build. Return to Settings; there is nothing to execute here.</p>
        <button class="ck-btn" type="button" id="ck-return">Return to Settings</button>
      </section>`;
    root.querySelector("#ck-return")?.addEventListener("click", () => { window.location.href = "/pages/settings/"; });
  }
  gate();
})();
