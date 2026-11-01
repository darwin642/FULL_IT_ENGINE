"use strict";

(() => {
    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

    const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);

    const number = (value) => Number(value || 0).toLocaleString();

    function setStat(card, value, foot, percent = 0) {
        if (!card) return;
        const valueNode = $(".stat-value", card);
        const footNode = $(".stat-foot", card);
        const progress = $(".stat-progress span", card);

        if (valueNode) valueNode.textContent = value;
        if (footNode) footNode.textContent = foot;
        if (progress) progress.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    }

    function renderDevices(data) {
        const list = $(".device-list");
        const devices = data.devices?.items || [];
        const counts = data.devices?.status_counts || {};
        const total = data.devices?.total || 0;

        const online = Number(counts.Online || 0);
        const warning = Number(counts.Warning || 0);
        const offline = Number(counts.Offline || 0);
        const onlinePercent = total ? (online / total) * 100 : 0;

        const cards = $$(".stats-grid .stat-card");
        setStat(cards[0], number(total), "Registered devices", total ? 100 : 0);
        setStat(cards[1], `${number(online)} / ${number(total)}`,
            "Stored status: Online", onlinePercent);

        const ring = $(".health-ring");
        if (ring) {
            ring.style.background = `conic-gradient(var(--green) ${onlinePercent}%, var(--border) ${onlinePercent}% 100%)`;
            const strong = $("strong", ring);
            const small = $("small", ring);
            if (strong) strong.textContent = `${Math.round(onlinePercent)}%`;
            if (small) small.textContent = "Stored Online";
        }

        const legend = $(".health-legend");
        if (legend) {
            legend.innerHTML = `
                <div><span class="legend-dot green-dot"></span><span>Online (stored)</span><strong>${number(online)}</strong></div>
                <div><span class="legend-dot orange-dot"></span><span>Warning</span><strong>${number(warning)}</strong></div>
                <div><span class="legend-dot red-dot"></span><span>Offline (stored)</span><strong>${number(offline)}</strong></div>`;
        }

        const panelSubtitle = $(".dashboard-grid .panel .panel-heading p");
        if (panelSubtitle) panelSubtitle.textContent = "Stored device status; live checks shown separately.";

        if (!list) return;
        if (!devices.length) {
            list.innerHTML = '<div class="empty-state">No devices registered yet.</div>';
            return;
        }

        list.innerHTML = devices.map((device) => {
            const status = String(device.status || "Unknown");
            const statusClass = status.toLowerCase() === "online" ? "healthy"
                : status.toLowerCase() === "warning" ? "warning-pill" : "offline-pill";
            const symbol = String(device.os || "?").slice(0, 1).toUpperCase();
            const detail = [device.os, device.ip].filter(Boolean).map(escapeHTML).join(" · ") || "No OS/IP details";
            return `<div class="device-row">
                <span class="device-symbol blue">${escapeHTML(symbol)}</span>
                <div class="device-info"><strong>${escapeHTML(device.name)}</strong><small>${detail}</small></div>
                <span class="status-pill ${statusClass}">${escapeHTML(status)}</span>
            </div>`;
        }).join("");
    }

    function renderTickets(data) {
        const cards = $$(".stats-grid .stat-card");
        const summary = $(".ticket-summary");
        const list = $(".ticket-list");
        const heading = $(".ticket-summary")?.closest(".panel")?.querySelector(".panel-heading p");

        setStat(cards[2], "—", "Ticketing API not configured", 0);
        setStat(cards[3], "—", "Task API not configured", 0);

        if (heading) heading.textContent = "Ticketing backend is not configured.";
        if (summary) summary.innerHTML = `
            <div><strong>—</strong><span>Open</span></div>
            <div><strong>—</strong><span>In progress</span></div>
            <div><strong>—</strong><span>Resolved</span></div>`;
        if (list) list.innerHTML = '<div class="empty-state">No ticket API is connected. No sample tickets are shown.</div>';
    }

    function renderActivity(data) {
        const list = $(".activity-list");
        if (!list) return;
        const activities = data.activity || [];

        if (!activities.length) {
            list.innerHTML = '<div class="empty-state">No monitoring events or alerts recorded yet.</div>';
            return;
        }

        list.innerHTML = activities.map((item) => {
            const isAlert = item.kind === "alert";
            const iconClass = isAlert ? "activity-orange" : "activity-blue";
            const icon = isAlert ? "!" : "↻";
            const time = item.timestamp ? new Date(item.timestamp).toLocaleString() : "Time unavailable";
            return `<div class="activity-item">
                <span class="activity-icon ${iconClass}">${icon}</span>
                <div><strong>${escapeHTML(item.title)}</strong>
                <p>${escapeHTML(item.detail)}</p><small>${escapeHTML(time)}</small></div>
            </div>`;
        }).join("");
    }

    async function refreshOverview() {
        const button = $("#refresh-dashboard");
        if (button) button.disabled = true;

        try {
            const response = await fetch("/api/overview", {
                headers: { Accept: "application/json" },
                cache: "no-store"
            });
            if (!response.ok) throw new Error(`Overview API returned HTTP ${response.status}`);

            const data = await response.json();
            renderDevices(data);
            renderTickets(data);
            renderActivity(data);

            const sectionHeading = $(".section-heading");
            if (sectionHeading) {
                let updated = $("#overview-last-updated");
                if (!updated) {
                    updated = document.createElement("small");
                    updated.id = "overview-last-updated";
                    updated.style.marginLeft = "12px";
                    sectionHeading.appendChild(updated);
                }
                updated.textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString()}`;
                updated.title = "Dashboard data fetched from the Cartman API.";
            }

            const monitoring = data.monitoring || {};
            const alerts = Number(monitoring.open_alerts || 0);
            const alertFoot = alerts ? `${number(alerts)} unresolved alerts` : "No unresolved alerts";
            const cards = $$(".stats-grid .stat-card");
            if (cards[2]) setStat(cards[2], "—", alertFoot, 0);

            await window.checkApiStatus?.();
        } catch (error) {
            console.error("Overview refresh failed:", error);
            const list = $(".activity-list");
            if (list) list.innerHTML = '<div class="empty-state">Could not load live dashboard data. Check the API connection and refresh.</div>';
            const updated = $("#overview-last-updated");
            if (updated) updated.textContent = "Update failed";
        } finally {
            if (button) button.disabled = false;
        }
    }

    // Capture the click before the legacy demo-only refresh handler.
    $("#refresh-dashboard")?.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        void refreshOverview();
    }, true);

    window.addEventListener("cartman:devices-updated", () => {
        void refreshOverview();
    });

    window.refreshOverview = refreshOverview;
    void refreshOverview();
    window.setInterval(() => void refreshOverview(), 30000);
})();
