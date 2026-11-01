/* CARTMAN_NOTIFICATION_CENTER_LIVE_V1 */
(() => {
  "use strict";
  const start = () => {
    const root = document.querySelector("[data-notification-center]");
    if (!root || root.dataset.liveInitialized === "1") return;
    root.dataset.liveInitialized = "1";
    const $ = selector => root.querySelector(selector);
    const $$ = selector => Array.from(root.querySelectorAll(selector));
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
    const rank = {critical:4,error:4,warning:3,info:2,success:1};
    let records = [];
    let filter = "all";
    let expandedId = "";
    let search = "";
    let sort = "newest";

    const stamp = value => {
      if (!value) return null;
      let text = String(value).trim();
      if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) text = text.replace(" ", "T") + "Z";
      const date = new Date(text);
      return Number.isNaN(date.getTime()) ? null : date;
    };
    const relativeTime = value => {
      const date = stamp(value);
      if (!date) return "Unknown time";
      const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
      if (minutes < 1) return "Just now";
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      const days = Math.floor(hours / 24);
      return days < 7 ? `${days}d ago` : date.toLocaleString();
    };
    const isUnread = item => !item.read_at;
    const categoryFor = item => {
      const source = String(item.source || "System");
      if (/monitor/i.test(source)) return "Monitoring";
      if (/task|work management/i.test(source)) return "Tasks";
      if (/identity|security|access/i.test(source)) return "Access";
      if (/workflow/i.test(source)) return "Workflows";
      if (/report/i.test(source)) return "Reports";
      return source;
    };
    const severityClass = severity => ["critical", "error"].includes(String(severity).toLowerCase()) ? "nc-tag-critical" : String(severity).toLowerCase() === "warning" ? "nc-tag-warning" : "";
    const iconFor = severity => ({critical:"!",error:"!",warning:"△",success:"✓",info:"•"})[String(severity || "info").toLowerCase()] || "•";

    function visibleRecords() {
      let result = records.filter(item => {
        const unread = isUnread(item);
        const severity = String(item.severity || "info").toLowerCase();
        const matchesFilter = filter === "all" || (filter === "unread" && unread) || (filter === "read" && !unread) || (filter === "critical" && ["critical","error"].includes(severity)) || categoryFor(item) === filter;
        const haystack = [item.id,item.title,item.message,item.source,item.severity].join(" ").toLowerCase();
        return matchesFilter && (!search || haystack.includes(search));
      });
      result.sort((a,b) => {
        const at = stamp(a.created_at)?.getTime() || 0;
        const bt = stamp(b.created_at)?.getTime() || 0;
        if (sort === "oldest") return at - bt;
        if (sort === "severity") return (rank[String(b.severity).toLowerCase()] || 0) - (rank[String(a.severity).toLowerCase()] || 0) || bt - at;
        return bt - at;
      });
      return result;
    }

    function render() {
      const unread = records.filter(isUnread).length;
      const critical = records.filter(item => ["critical","error"].includes(String(item.severity).toLowerCase())).length;
      const todayStart = new Date(); todayStart.setHours(0,0,0,0);
      const today = records.filter(item => { const date = stamp(item.created_at); return date && date >= todayStart; }).length;
      const sources = new Set(records.map(item => item.source).filter(Boolean)).size;
      for (const [key,value] of Object.entries({unread,critical,today,sources})) {
        const node = $(`[data-nc-stat="${key}"]`); if (node) node.textContent = String(value);
      }
      const filterCounts = {
        all: records.length,
        unread,
        critical,
        Monitoring: records.filter(item => categoryFor(item) === "Monitoring").length,
        Tasks: records.filter(item => categoryFor(item) === "Tasks").length,
        Access: records.filter(item => categoryFor(item) === "Access").length,
        Workflows: records.filter(item => categoryFor(item) === "Workflows").length,
        Reports: records.filter(item => categoryFor(item) === "Reports").length
      };
      Object.entries(filterCounts).forEach(([key,value]) => {
        const node = $(`[data-nc-count="${key}"]`); if (node) node.textContent = String(value);
      });
      const visible = visibleRecords();
      const list = $("[data-nc-list]");
      list.innerHTML = visible.map(item => {
        const id = Number(item.id);
        const expanded = expandedId === String(id);
        const severity = String(item.severity || "info");
        const date = stamp(item.created_at);
        return `<article class="nc-item ${isUnread(item) ? "is-unread" : ""}" data-nc-item="${id}">
          <span class="nc-kind-icon" aria-hidden="true">${iconFor(severity)}</span>
          <div class="nc-item-body"><h3 class="nc-item-title">${esc(item.title)}</h3><p class="nc-item-message">${esc(item.message || "")}</p>
            <div class="nc-item-tags"><span class="nc-tag ${severityClass(severity)}">${esc(severity)}</span><span class="nc-tag">${esc(item.source || "Cartman")}</span><span class="nc-tag">#${id}</span>${isUnread(item) ? '<span class="nc-tag nc-tag-warning">UNREAD</span>' : '<span class="nc-tag">READ</span>'}</div></div>
          <div class="nc-item-side"><time class="nc-item-time" datetime="${date ? date.toISOString() : ""}">${esc(relativeTime(item.created_at))}</time><div class="nc-item-actions">${expanded ? "" : `<button class="nc-item-action" type="button" data-nc-action="details" data-nc-id="${id}">Details</button>`}${isUnread(item) ? `<button class="nc-item-action" type="button" data-nc-action="read" data-nc-id="${id}">Mark read</button>` : ""}</div></div>
          ${expanded ? `<div class="nc-item-details"><strong>Notification details</strong><br>${esc(item.message || "No additional details.")}<br><strong>Source:</strong> ${esc(item.source || "Cartman")}<br><strong>Received:</strong> ${esc(date ? date.toLocaleString() : "Unknown")}</div>` : ""}
        </article>`;
      }).join("");
      const empty = $("[data-nc-empty]");
      empty.hidden = visible.length !== 0;
      list.hidden = visible.length === 0;
      const emptyTitle = empty.querySelector("strong");
      const emptyText = empty.querySelector("p");
      if (emptyTitle) emptyTitle.textContent = records.length ? "No notifications match" : "There are no notifications yet";
      if (emptyText) emptyText.textContent = records.length ? "Try another filter or search term." : "New Cartman notifications will appear here.";
      const count = $("[data-nc-visible-count]"); if (count) count.textContent = `${visible.length} ${visible.length === 1 ? "event" : "events"}`;
      const caption = $("[data-nc-list-caption]"); if (caption) caption.textContent = filter === "all" ? "Your Cartman notification history" : `Filtered by ${filter}`;
      const markAll = $('[data-nc-action="mark-all"]'); if (markAll) markAll.disabled = unread === 0;
      $$('[data-nc-filter]').forEach(button => {
        const selected = button.dataset.ncFilter === filter;
        button.classList.toggle("is-active", selected);
        button.setAttribute("aria-pressed", String(selected));
      });
    }

    async function load() {
      const caption = $("[data-nc-list-caption]");
      if (caption) caption.textContent = "Loading your Cartman notifications…";
      try {
        const response = await fetch("/api/notifications/inbox?limit=200", {credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}});
        if (!response.ok || response.redirected) throw new Error("Notification history is unavailable.");
        const data = await response.json();
        records = Array.isArray(data.items) ? data.items : [];
        const banner = $("[data-nc-live-banner]");
        if (banner) {
          const strong = banner.querySelector("strong"); const text = banner.querySelector("span:not(.nc-preview-dot)"); const tag = banner.querySelector(".nc-preview-tag");
          if (strong) strong.textContent = "Live notification inbox";
          if (text) text.textContent = "Notifications generated by Cartman are stored for your signed-in account.";
          if (tag) tag.textContent = "LIVE DATABASE";
        }
        render();
      } catch (error) {
        records = [];
        render();
        const captionNode = $("[data-nc-list-caption]"); if (captionNode) captionNode.textContent = error.message || "Notifications could not be loaded.";
      }
    }

    async function markRead(id, all = false) {
      try {
        const response = await fetch("/api/notifications/inbox/read", {
          method:"POST", credentials:"same-origin", cache:"no-store",
          headers:{"Content-Type":"application/json",Accept:"application/json"},
          body:JSON.stringify(all ? {all:true} : {id:Number(id)})
        });
        if (!response.ok) throw new Error("Could not update notifications.");
        await load();
        window.dispatchEvent(new CustomEvent("cartman:notification-inbox-updated"));
      } catch (error) {
        const caption = $("[data-nc-list-caption]"); if (caption) caption.textContent = error.message;
      }
    }

    root.addEventListener("input", event => {
      if (event.target.matches("[data-nc-search]")) { search = event.target.value.trim().toLowerCase(); render(); }
    });
    root.addEventListener("change", event => {
      if (event.target.matches("[data-nc-sort]")) { sort = event.target.value; render(); }
    });
    root.addEventListener("click", event => {
      const filterButton = event.target.closest("[data-nc-filter]");
      if (filterButton) { filter = filterButton.dataset.ncFilter; expandedId = ""; render(); return; }
      const action = event.target.closest("[data-nc-action]");
      if (!action) return;
      const kind = action.dataset.ncAction;
      if (kind === "mark-all") { void markRead(null, true); return; }
      if (kind === "clear-filters") { filter = "all"; search = ""; const input = $("[data-nc-search]"); if (input) input.value = ""; render(); return; }
      const id = action.dataset.ncId;
      if (kind === "read") { void markRead(id); return; }
      if (kind === "details") { expandedId = expandedId === id ? "" : id; render(); }
    });
    window.addEventListener("cartman:notification-inbox-updated", () => { void load(); });
    root.addEventListener("click", event => { if (event.target.closest('[data-nc-action="refresh"]')) void load(); });
    const banner = $("[data-nc-live-banner]");
    if (banner) banner.hidden = false;
    void load();
    window.setInterval(() => { if (!document.hidden) void load(); }, 60000);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
