/* CARTMAN_ALERTS_INSPECT_DEVICE_V1 — select/open alert resource on Monitoring page */
(() => {
  "use strict";
  const params = new URLSearchParams(location.search);
  if (params.get("inspect_alert") !== "1" || window.__cartmanAlertsInspectDevice) return;
  window.__cartmanAlertsInspectDevice = true;
  const context = { alertId: params.get("alert_id") || "", alertCode: params.get("alert_code") || "", deviceId: params.get("device_id") || "", deviceName: params.get("device_name") || "", title: params.get("alert_title") || "" };
  const norm = value => String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
  const ids = [context.deviceId, context.deviceName].map(norm).filter(Boolean);
  const escText = value => String(value || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function banner() {
    if (document.getElementById("cartman-alert-inspect-context")) return;
    const el = document.createElement("aside"); el.id = "cartman-alert-inspect-context";
    el.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:10px 0;padding:12px 15px;border:1px solid var(--border,var(--border-color,rgba(130,150,180,.3)));border-left:3px solid var(--accent,var(--accent-color,#689cff));border-radius:10px;background:var(--surface,var(--panel-bg,var(--bg-secondary,transparent)));color:var(--text-primary,var(--text-color,var(--text,inherit)));font:inherit;";
    el.innerHTML = `<span><strong>${escText(context.alertCode || "Alert inspection")}</strong> · ${escText(context.deviceName || context.deviceId || "Affected device")}<small style="display:block;color:var(--text-secondary,var(--text-muted,#94a3b8));margin-top:3px">${escText(context.title)}</small></span><span id="cartman-alert-inspect-state" style="font-size:11px;color:var(--text-secondary,var(--text-muted,#94a3b8))">Finding device…</span>`;
    const main = document.querySelector('main,[role="main"],[data-page-content],#page-content,#pageContent,.main-content,.app-content') || document.body;
    main.insertBefore(el, main.firstChild);
  }
  function same(value) { const v=norm(value); return !!v && ids.some(id => v===id || v.includes(id) || id.includes(v) && v.length>3); }
  function updateState(message) { const el=document.getElementById("cartman-alert-inspect-state"); if(el)el.textContent=message; }
  function trySelect() {
    let selected=false;
    const deviceSearch = [...document.querySelectorAll('input[type="search"],input[placeholder]')].find(input => /device|host|machine|resource|endpoint/i.test([input.placeholder,input.getAttribute("aria-label"),input.dataset.filter,input.name,input.id].join(" ")));
    if (deviceSearch && !same(deviceSearch.value)) {
      deviceSearch.value = context.deviceName || context.deviceId;
      deviceSearch.dispatchEvent(new Event("input",{bubbles:true}));
      deviceSearch.dispatchEvent(new Event("change",{bubbles:true}));
      selected = true;
    }
    for (const select of document.querySelectorAll("select")) {
      const option=[...select.options].find(opt => same(opt.value) || same(opt.textContent));
      if (option && select.value!==option.value) { select.value=option.value; select.dispatchEvent(new Event("input",{bubbles:true})); select.dispatchEvent(new Event("change",{bubbles:true})); selected=true; }
      else if (option) selected=true;
    }
    if (!selected) {
      const direct=[...document.querySelectorAll("[data-device-id],[data-device],[data-device-name],[data-hostname],[data-host], [data-target-device]")].find(node => [node.getAttribute("data-device-id"),node.getAttribute("data-device"),node.getAttribute("data-device-name"),node.getAttribute("data-hostname"),node.getAttribute("data-host"),node.getAttribute("data-target-device")].some(same));
      if(direct){ const clickable=direct.matches("button,[role=button],a,tr")?direct:direct.querySelector("button,[role=button],a")||direct.closest("button,[role=button],a,tr"); if(clickable&&clickable!==document.body){clickable.click();selected=true;} }
    }
    if (!selected && ids.length) {
      const candidates=[...document.querySelectorAll("button,[role=option],[role=button],a,tr,.device-row,.device-card,[data-device-item]")];
      const node=candidates.find(el=>{const t=norm(el.innerText||el.textContent);return ids.some(id=>t===id||t.includes(id));});
      if(node){node.click();selected=true;}
    }
    if(selected){updateState("Device selected from alert context.");window.dispatchEvent(new CustomEvent("cartman:inspect-device",{detail:context}));return true;}
    return false;
  }
  function start() {
    banner(); window.cartmanPendingAlertInspection=context;
    window.dispatchEvent(new CustomEvent("cartman:inspect-device",{detail:context}));
    let tries=0; const timer=setInterval(()=>{tries++;if(trySelect()){clearInterval(timer);return;}if(tries>=40){clearInterval(timer);updateState("Alert context loaded. Device picker was not available; use the device filter to select this resource.");}},350);
    trySelect();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
