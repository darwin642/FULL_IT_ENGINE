/* CARTMAN_GLOBAL_LIVE_TOASTS_V1 */
(() => {
  "use strict";

  if (window.CartmanToast && window.CartmanToast.__cartmanGlobalLiveToastsV1) return;

  const STYLE_ID = "cartman-global-live-toasts-style";
  const ROOT_ID = "cartman-global-live-toasts";
  const CHANNEL_NAME = "cartman-live-notifications-v1";
  const STORAGE_KEY = "cartman-live-notification-event-v1";
  const MAX_TOASTS = 3;
  const DEFAULT_DURATION = 10000;
  const MAX_DURATION = 10000;
  const timers = new WeakMap();
  let channel = null;

  const icons = {
    critical: "!",
    error: "!",
    warning: "△",
    success: "✓",
    info: "♧"
  };

  function addStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      @keyframes cartman-live-toast-enter {
        from { opacity: 0; transform: translate3d(calc(-100% - 24px),0,0); }
        to   { opacity: 1; transform: translate3d(0,0,0); }
      }
      @keyframes cartman-live-toast-leave {
        to { opacity: 0; transform: translate3d(calc(-100% - 24px),0,0); }
      }
      @keyframes cartman-live-toast-progress {
        from { transform: scaleX(1); }
        to { transform: scaleX(0); }
      }
      #${ROOT_ID} {
        position: fixed;
        z-index: 2147483000;
        top: calc(var(--topbar-height, 64px) + 12px);
        left: 14px;
        width: min(360px, calc(100vw - 28px));
        display: flex;
        flex-direction: column;
        gap: 9px;
        pointer-events: none;
        contain: layout style;
      }
      #${ROOT_ID} .cartman-live-toast {
        position: relative;
        display: grid;
        grid-template-columns: 30px minmax(0,1fr) 28px;
        align-items: start;
        gap: 10px;
        overflow: hidden;
        box-sizing: border-box;
        width: 100%;
        padding: 13px 12px 15px;
        color: #eef2ff;
        background: #171e2d;
        border: 1px solid rgba(148,163,184,.28);
        border-left: 3px solid #7c9cff;
        border-radius: 11px;
        box-shadow: 0 12px 34px rgba(0,0,0,.28);
        pointer-events: auto;
        animation: cartman-live-toast-enter .26s cubic-bezier(.2,.8,.2,1) both;
        font-family: inherit;
      }
      #${ROOT_ID} .cartman-live-toast[data-severity="critical"],
      #${ROOT_ID} .cartman-live-toast[data-severity="error"] { border-left-color: #f06b72; }
      #${ROOT_ID} .cartman-live-toast[data-severity="warning"] { border-left-color: #e8b454; }
      #${ROOT_ID} .cartman-live-toast[data-severity="success"] { border-left-color: #42c99a; }
      #${ROOT_ID} .cartman-live-toast-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 29px;
        height: 29px;
        border-radius: 8px;
        background: rgba(148,163,184,.13);
        color: #dbe5ff;
        font-size: 15px;
        font-weight: 800;
      }
      #${ROOT_ID} .cartman-live-toast[data-severity="critical"] .cartman-live-toast-icon,
      #${ROOT_ID} .cartman-live-toast[data-severity="error"] .cartman-live-toast-icon { color: #ff9da3; background: rgba(240,107,114,.12); }
      #${ROOT_ID} .cartman-live-toast[data-severity="warning"] .cartman-live-toast-icon { color: #f1c774; background: rgba(232,180,84,.12); }
      #${ROOT_ID} .cartman-live-toast[data-severity="success"] .cartman-live-toast-icon { color: #65ddb1; background: rgba(66,201,154,.12); }
      #${ROOT_ID} .cartman-live-toast-body { min-width: 0; }
      #${ROOT_ID} .cartman-live-toast-title {
        display: block;
        margin: 1px 0 3px;
        color: inherit;
        font-size: 12px;
        line-height: 1.4;
        font-weight: 750;
        overflow-wrap: anywhere;
      }
      #${ROOT_ID} .cartman-live-toast-message {
        margin: 0;
        color: #b8c2d6;
        font-size: 11px;
        line-height: 1.5;
        overflow-wrap: anywhere;
      }
      #${ROOT_ID} .cartman-live-toast-source {
        display: block;
        margin-top: 6px;
        color: #91a0ba;
        font-size: 10px;
        line-height: 1.35;
      }
      #${ROOT_ID} .cartman-live-toast-close {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 27px;
        height: 27px;
        margin: -3px -2px 0 0;
        padding: 0;
        border: 1px solid rgba(148,163,184,.22);
        border-radius: 7px;
        background: rgba(148,163,184,.07);
        color: #c5cede;
        font: inherit;
        font-size: 17px;
        line-height: 1;
        cursor: pointer;
      }
      #${ROOT_ID} .cartman-live-toast-close:hover { background: rgba(148,163,184,.17); color: #fff; }
      #${ROOT_ID} .cartman-live-toast-close:focus-visible { outline: 2px solid #8eaaff; outline-offset: 2px; }
      #${ROOT_ID} .cartman-live-toast-action {
        display: inline-flex;
        margin-top: 8px;
        padding: 0;
        border: 0;
        background: transparent;
        color: #a8c0ff;
        font: inherit;
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 2px;
      }
      #${ROOT_ID} .cartman-live-toast-progress-track {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 2px;
        background: rgba(148,163,184,.12);
      }
      #${ROOT_ID} .cartman-live-toast-progress {
        display: block;
        width: 100%;
        height: 100%;
        background: #7c9cff;
        transform-origin: left center;
        animation: cartman-live-toast-progress var(--cartman-toast-duration, 10000ms) linear forwards;
      }
      #${ROOT_ID} .cartman-live-toast[data-severity="critical"] .cartman-live-toast-progress,
      #${ROOT_ID} .cartman-live-toast[data-severity="error"] .cartman-live-toast-progress { background: #f06b72; }
      #${ROOT_ID} .cartman-live-toast[data-severity="warning"] .cartman-live-toast-progress { background: #e8b454; }
      #${ROOT_ID} .cartman-live-toast[data-severity="success"] .cartman-live-toast-progress { background: #42c99a; }
      #${ROOT_ID} .cartman-live-toast.is-leaving { animation: cartman-live-toast-leave .18s ease-in both; }
      body.light-theme #${ROOT_ID} .cartman-live-toast {
        color: #182235;
        background: #fff;
        border-color: rgba(15,23,42,.14);
        border-left-width: 3px;
        box-shadow: 0 12px 32px rgba(15,23,42,.16);
      }
      body.light-theme #${ROOT_ID} .cartman-live-toast-message { color: #526078; }
      body.light-theme #${ROOT_ID} .cartman-live-toast-source { color: #687792; }
      body.light-theme #${ROOT_ID} .cartman-live-toast-icon { color: #455a83; }
      body.light-theme #${ROOT_ID} .cartman-live-toast-close { color: #526078; border-color: rgba(15,23,42,.13); background: #f5f7fb; }
      body.light-theme #${ROOT_ID} .cartman-live-toast-close:hover { color: #172033; background: #e9edf5; }
      body.light-theme #${ROOT_ID} .cartman-live-toast-action { color: #315fc2; }
      @media (max-width: 600px) {
        #${ROOT_ID} { left: 10px; top: calc(var(--topbar-height, 58px) + 8px); width: calc(100vw - 20px); }
      }
      @media (prefers-reduced-motion: reduce) {
        #${ROOT_ID} .cartman-live-toast { animation-duration: .01ms; }
        #${ROOT_ID} .cartman-live-toast-progress { animation-duration: var(--cartman-toast-duration, 10000ms); }
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function rootNode() {
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.setAttribute("aria-live", "polite");
      root.setAttribute("aria-relevant", "additions");
      root.setAttribute("aria-label", "Cartman live notifications");
      (document.body || document.documentElement).appendChild(root);
    }
    return root;
  }

  function normalize(input) {
    const data = typeof input === "string" ? { message: input } : (input && typeof input === "object" ? input : {});
    const severityRaw = String(data.severity || data.level || data.type || "info").toLowerCase();
    const severity = ["critical", "error", "warning", "success"].includes(severityRaw) ? severityRaw : "info";
    const title = String(data.title || data.heading || (severity === "critical" ? "Critical notification" : severity === "warning" ? "Warning" : severity === "success" ? "Completed" : "Cartman notification")).slice(0, 180);
    const message = String(data.message || data.body || data.description || "").slice(0, 1200);
    const source = String(data.source || data.category || "").slice(0, 100);
    const durationValue = Number(data.duration);
    const duration = Number.isFinite(durationValue) && durationValue > 0
      ? Math.min(MAX_DURATION, Math.max(1000, durationValue))
      : DEFAULT_DURATION;
    const actionLabel = String(data.actionLabel || data.action_label || "").slice(0, 60);
    let actionUrl = "";
    const candidateUrl = String(data.actionUrl || data.href || "");
    if (candidateUrl.startsWith("/") && !candidateUrl.startsWith("//")) actionUrl = candidateUrl;
    return { title, message, source, severity, duration, actionLabel, actionUrl, id: String(data.id || "") };
  }

  function dismiss(toast) {
    if (!toast || !toast.isConnected || toast.dataset.closing === "1") return;
    toast.dataset.closing = "1";
    const timer = timers.get(toast);
    if (timer) clearTimeout(timer);
    toast.classList.add("is-leaving");
    window.setTimeout(() => toast.remove(), 210);
  }

  function display(input) {
    const data = normalize(input);
    if (!data.title && !data.message) return null;
    addStyles();
    const root = rootNode();
    const toast = document.createElement("article");
    toast.className = "cartman-live-toast";
    toast.dataset.severity = data.severity;
    toast.setAttribute("role", data.severity === "critical" || data.severity === "error" ? "alert" : "status");
    toast.style.setProperty("--cartman-toast-duration", `${data.duration}ms`);

    const icon = document.createElement("span");
    icon.className = "cartman-live-toast-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = icons[data.severity] || icons.info;

    const body = document.createElement("div");
    body.className = "cartman-live-toast-body";
    const title = document.createElement("strong");
    title.className = "cartman-live-toast-title";
    title.textContent = data.title;
    body.appendChild(title);
    if (data.message) {
      const message = document.createElement("p");
      message.className = "cartman-live-toast-message";
      message.textContent = data.message;
      body.appendChild(message);
    }
    if (data.source) {
      const source = document.createElement("small");
      source.className = "cartman-live-toast-source";
      source.textContent = data.source;
      body.appendChild(source);
    }
    if (data.actionLabel && data.actionUrl) {
      const action = document.createElement("button");
      action.type = "button";
      action.className = "cartman-live-toast-action";
      action.textContent = data.actionLabel;
      action.addEventListener("click", () => {
        const target = new URL(data.actionUrl, window.location.origin);
        if (target.origin === window.location.origin) window.location.assign(target.href);
        dismiss(toast);
      });
      body.appendChild(action);
    }

    const close = document.createElement("button");
    close.type = "button";
    close.className = "cartman-live-toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.title = "Dismiss notification";
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(toast));

    const progressTrack = document.createElement("span");
    progressTrack.className = "cartman-live-toast-progress-track";
    progressTrack.setAttribute("aria-hidden", "true");
    const progress = document.createElement("span");
    progress.className = "cartman-live-toast-progress";
    progressTrack.appendChild(progress);

    toast.append(icon, body, close, progressTrack);
    root.prepend(toast);
    while (root.children.length > MAX_TOASTS) dismiss(root.lastElementChild);
    const timer = window.setTimeout(() => dismiss(toast), data.duration);
    timers.set(toast, timer);
    return toast;
  }

  function minimalCrossTabPayload(input) {
    const data = normalize(input);
    return { title: data.title, message: data.message, source: data.source, severity: data.severity, duration: data.duration, actionLabel: data.actionLabel, actionUrl: data.actionUrl, id: data.id, _cartmanBroadcast: true };
  }

  function notify(input) {
    const toast = display(input);
    const data = minimalCrossTabPayload(input);
    // Persist real Cartman events in the signed-in user's notification inbox.
    if (!(data.source === "Toast preview" || data.title === "Cartman notification test")) {
      try { fetch("/api/notifications/inbox", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ event_key: data.id || "", title: data.title, message: data.message, severity: data.severity, source: data.source, action_url: data.actionUrl })
      }).then(response => { if (response.ok) window.dispatchEvent(new CustomEvent("cartman:notification-inbox-updated")); }).catch(() => {}); } catch (_) {}
    }
    // Use one cross-tab transport only; sending through both would duplicate each toast.
    if (channel) {
      try { channel.postMessage(data); } catch (_) {}
    } else {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ nonce: `${Date.now()}-${Math.random().toString(16).slice(2)}`, payload: data }));
      } catch (_) {}
    }
    return toast;
  }

  function receive(input) {
    if (input && input._cartmanBroadcast) display(input);
    else display(input);
  }

  try {
    if (typeof BroadcastChannel === "function") {
      channel = new BroadcastChannel(CHANNEL_NAME);
      channel.addEventListener("message", event => receive(event.data));
    }
  } catch (_) { channel = null; }

  window.addEventListener("storage", event => {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try {
      const message = JSON.parse(event.newValue);
      if (message && message.payload) receive(message.payload);
    } catch (_) {}
  });

  // App modules can dispatch one of these events from any screen; notify() also
  // fans it out to other open Cartman tabs when the browser supports it.
  window.addEventListener("cartman:notification", event => notify(event.detail));
  window.addEventListener("cartman:toast", event => notify(event.detail));
  window.addEventListener("cartman:notify", event => notify(event.detail));

  window.CartmanToast = Object.freeze({
    __cartmanGlobalLiveToastsV1: true,
    notify,
    dismissAll() {
      const root = document.getElementById(ROOT_ID);
      if (root) [...root.children].forEach(dismiss);
    },
    test() {
      return notify({ title: "Cartman notification test", message: "Global popup is working on this page.", severity: "success", source: "Toast preview" });
    }
  });
  // CARTMAN_GLOBAL_NOTIFICATION_EVENT_POLLING_LOADER_V1
  // Poll authorized Cartman APIs for fresh events; the poller uses a per-origin lease
  // so only one open tab polls while CartmanToast broadcasts notifications to other tabs.
  try {
    if (!document.getElementById("cartman-global-notification-events-loader")) {
      const eventPoller = document.createElement("script");
      eventPoller.id = "cartman-global-notification-events-loader";
      eventPoller.src = "/static/js/modules/global-notification-events.js?v=cartman-live-events-workflows-v2";
      eventPoller.async = true;
      (document.head || document.documentElement).appendChild(eventPoller);
    }
  } catch (error) {
    console.warn("Cartman live notification event polling could not be loaded:", error);
  }

})();
