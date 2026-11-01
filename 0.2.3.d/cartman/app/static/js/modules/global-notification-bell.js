
/* CARTMAN_NOTIFICATION_BELL_STYLES_V1 */
(() => {
  if (document.getElementById("cartman-notification-bell-style")) return;
  const style = document.createElement("style");
  style.id = "cartman-notification-bell-style";
  style.textContent = "\n/* CARTMAN_NOTIFICATION_BELL_V1 */\n#cartman-notification-bell{position:relative;display:inline-flex;align-items:center;flex:0 0 auto;z-index:1200}\n#cartman-notification-bell .cartman-notification-bell-button{position:relative;display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;padding:0;border-radius:10px}\n#cartman-notification-bell .cartman-notification-bell-button svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}\n#cartman-notification-bell .cartman-notification-badge{position:absolute;top:-4px;right:-5px;min-width:18px;height:18px;padding:0 5px;display:flex;align-items:center;justify-content:center;border:2px solid var(--bg-primary,#0b1020);border-radius:999px;background:#e35d70;color:#fff;font-size:9px;font-weight:800;line-height:1}\n#cartman-notification-bell .cartman-notification-badge[hidden]{display:none}\n#cartman-notification-bell .cartman-notification-popover{position:absolute;top:calc(100% + 12px);right:-8px;width:min(390px,calc(100vw - 24px));max-height:min(560px,calc(100vh - 100px));display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--border-color,rgba(130,150,190,.24));border-radius:15px;background:var(--card-bg,#151e31);color:var(--text-primary,#e8edf8);box-shadow:0 22px 65px rgba(0,0,0,.34);z-index:20000}\n#cartman-notification-bell .cartman-notification-popover[hidden]{display:none}\n#cartman-notification-bell .cnb-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 17px;border-bottom:1px solid var(--border-color,rgba(130,150,190,.15))}\n#cartman-notification-bell .cnb-heading strong{display:block;font-size:13px;font-weight:800}\n#cartman-notification-bell .cnb-heading small{display:block;margin-top:4px;font-size:10px;color:var(--text-secondary,#97a5c2)}\n#cartman-notification-bell .cnb-heading button{width:28px;height:28px;border:1px solid var(--border-color,rgba(130,150,190,.2));border-radius:7px;background:transparent;color:var(--text-secondary,#97a5c2);font-size:19px;cursor:pointer}\n#cartman-notification-bell .cnb-list{overflow:auto;overscroll-behavior:contain}\n#cartman-notification-bell .cnb-item{display:grid;grid-template-columns:9px minmax(0,1fr) 28px;gap:11px;align-items:start;padding:14px 15px;border-bottom:1px solid var(--border-color,rgba(130,150,190,.10))}\n#cartman-notification-bell .cnb-item:last-child{border-bottom:0}\n#cartman-notification-bell .cnb-item-mark{width:8px;height:8px;margin-top:5px;border-radius:50%;background:#8295bf;box-shadow:0 0 0 4px rgba(130,149,191,.10)}\n#cartman-notification-bell .cnb-item-mark.cnb-critical,#cartman-notification-bell .cnb-item-mark.cnb-error{background:#ef707c;box-shadow:0 0 0 4px rgba(239,112,124,.12)}\n#cartman-notification-bell .cnb-item-mark.cnb-warning{background:#e8b454;box-shadow:0 0 0 4px rgba(232,180,84,.12)}\n#cartman-notification-bell .cnb-item-mark.cnb-success{background:#42c99a;box-shadow:0 0 0 4px rgba(66,201,154,.12)}\n#cartman-notification-bell .cnb-item-body{min-width:0}\n#cartman-notification-bell .cnb-item-body>strong{display:block;font-size:11px;line-height:1.45;font-weight:750;overflow-wrap:anywhere}\n#cartman-notification-bell .cnb-item-body p{margin:4px 0 0;color:var(--text-secondary,#a0adc5);font-size:10px;line-height:1.5;overflow-wrap:anywhere}\n#cartman-notification-bell .cnb-item-meta{display:flex;justify-content:space-between;gap:8px;margin-top:7px;color:var(--text-secondary,#8292b2);font-size:9px}\n#cartman-notification-bell .cnb-item-meta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n#cartman-notification-bell .cnb-mark-read{width:27px;height:27px;border:1px solid var(--border-color,rgba(130,150,190,.18));border-radius:7px;background:transparent;color:#58c99d;font-size:14px;cursor:pointer}\n#cartman-notification-bell .cnb-mark-read:hover{background:rgba(66,201,154,.11);border-color:rgba(66,201,154,.42)}\n#cartman-notification-bell .cnb-empty{padding:27px 16px;text-align:center;color:var(--text-secondary,#9aa8c2);font-size:11px}\n#cartman-notification-bell .cnb-footer{margin-top:auto;padding:13px 16px;border-top:1px solid var(--border-color,rgba(130,150,190,.15));background:rgba(120,140,180,.035)}\n#cartman-notification-bell .cnb-footer a{display:flex;align-items:center;justify-content:center;gap:7px;color:#9eabff;font-size:11px;font-weight:750;text-decoration:none}\n#cartman-notification-bell .cnb-footer a:hover{color:#c0baff;text-decoration:underline;text-underline-offset:3px}\nbody.light-theme #cartman-notification-bell .cartman-notification-popover{background:#fff;border-color:rgba(45,62,98,.18);box-shadow:0 22px 55px rgba(29,45,78,.18)}\nbody.light-theme #cartman-notification-bell .cnb-item-body p{color:#596984}\nbody.light-theme #cartman-notification-bell .cnb-heading small,body.light-theme #cartman-notification-bell .cnb-item-meta,body.light-theme #cartman-notification-bell .cnb-empty{color:#687793}\nbody.light-theme #cartman-notification-bell .cnb-footer{background:#f7f8fc;border-color:rgba(45,62,98,.13)}\n@media(max-width:650px){#cartman-notification-bell .cartman-notification-popover{right:-64px;width:min(370px,calc(100vw - 20px))}}\n";
  (document.head || document.documentElement).appendChild(style);
})();
/* CARTMAN_NOTIFICATION_BELL_V1 */
(() => {
  "use strict";
  if (window.__cartmanNotificationBellV1) return;
  window.__cartmanNotificationBellV1 = true;

  const ROOT = document.getElementById("cartman-notification-bell");
  if (!ROOT) return;
  const button = ROOT.querySelector("[data-cnb-toggle]");
  const panel = ROOT.querySelector("[data-cnb-panel]");
  const list = ROOT.querySelector("[data-cnb-list]");
  const empty = ROOT.querySelector("[data-cnb-empty]");
  const badge = ROOT.querySelector("[data-cnb-badge]");
  const countLabel = ROOT.querySelector("[data-cnb-count]");
  const $ = (selector) => ROOT.querySelector(selector);
  let unreadCount = 0;
  let loaded = false;
  let loading = false;
  let refreshTimer = null;

  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const parseDate = value => {
    if (!value) return null;
    let text = String(value).trim();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) text = text.replace(" ", "T") + "Z";
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  };
  const relativeTime = value => {
    const date = parseDate(value);
    if (!date) return "Recently";
    const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return days < 7 ? `${days}d ago` : date.toLocaleDateString();
  };

  function setOpen(open) {
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    if (open) void refresh();
  }

  function render(items, count) {
    unreadCount = Number(count) || 0;
    badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
    badge.hidden = unreadCount < 1;
    countLabel.textContent = `${unreadCount} unread`;
    list.innerHTML = (Array.isArray(items) ? items : []).slice(0, 8).map(item => {
      const severity = String(item.severity || "info").toLowerCase();
      const severityClass = ["critical", "error", "warning", "success"].includes(severity) ? severity : "info";
      return `<article class="cnb-item" data-cnb-item="${Number(item.id) || 0}">
        <span class="cnb-item-mark cnb-${severityClass}" aria-hidden="true"></span>
        <div class="cnb-item-body">
          <strong>${esc(item.title || "Cartman notification")}</strong>
          ${item.message ? `<p>${esc(item.message)}</p>` : ""}
          <div class="cnb-item-meta"><span>${esc(item.source || "Cartman")}</span><time>${esc(relativeTime(item.created_at))}</time></div>
        </div>
        <button type="button" class="cnb-mark-read" data-cnb-read="${Number(item.id) || 0}" aria-label="Mark as read" title="Mark as read">✓</button>
      </article>`;
    }).join("");
    empty.hidden = list.children.length > 0;
    list.hidden = list.children.length === 0;
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch("/api/notifications/inbox?unread_only=1&limit=8", {
        credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }
      });
      if (!response.ok || response.redirected) throw new Error("Notifications unavailable");
      const data = await response.json();
      render(data.items || [], data.unread_count || 0);
      loaded = true;
    } catch (_) {
      if (!loaded) {
        list.innerHTML = "";
        list.hidden = true;
        empty.hidden = false;
        empty.textContent = "Notifications could not be loaded.";
        countLabel.textContent = "Unavailable";
      }
    } finally {
      loading = false;
    }
  }

  async function markRead(id) {
    if (!id) return;
    try {
      const response = await fetch("/api/notifications/inbox/read", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ id })
      });
      if (!response.ok) throw new Error("Could not update notification");
      await refresh();
      window.dispatchEvent(new CustomEvent("cartman:notification-inbox-updated"));
    } catch (_) {}
  }

  button.addEventListener("click", () => setOpen(panel.hidden));
  const closeButton = $("[data-cnb-close]");
  if (closeButton) closeButton.addEventListener("click", () => setOpen(false));
  ROOT.addEventListener("click", event => {
    const readButton = event.target.closest("[data-cnb-read]");
    if (readButton) { event.preventDefault(); event.stopPropagation(); void markRead(Number(readButton.dataset.cnbRead)); }
  });
  document.addEventListener("click", event => {
    if (!ROOT.contains(event.target)) setOpen(false);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !panel.hidden) { setOpen(false); button.focus(); }
  });
  window.addEventListener("focus", () => { if (loaded) void refresh(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && loaded) void refresh(); });
  window.addEventListener("cartman:notification-inbox-updated", () => { void refresh(); });
  refreshTimer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 45000);
  void refresh();
})();
