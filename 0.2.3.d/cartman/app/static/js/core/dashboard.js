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
        setStat(cards[0], number(total), "Registered in Cartman", 0);
        setStat(cards[1], number(online),
            `${number(warning)} warning · ${number(offline)} offline`, onlinePercent);

        const ring = $(".health-ring");
        if (ring) {
            ring.style.background = `conic-gradient(var(--green) ${onlinePercent}%, var(--border) ${onlinePercent}% 100%)`;
            const strong = $("strong", ring);
            const small = $("small", ring);
            if (strong) strong.textContent = `${Math.round(onlinePercent)}%`;
            if (small) small.textContent = "Online coverage";
        }

        const legend = $(".health-legend");
        if (legend) {
            legend.innerHTML = `
                <div><span class="legend-dot green-dot"></span><span>Online (live)</span><strong>${number(online)}</strong></div>
                <div><span class="legend-dot orange-dot"></span><span>Warning</span><strong>${number(warning)}</strong></div>
                <div><span class="legend-dot red-dot"></span><span>Offline (live)</span><strong>${number(offline)}</strong></div>`;
        }

        const panelSubtitle = $(".dashboard-grid .panel .panel-heading p");
        if (panelSubtitle) panelSubtitle.textContent = "Online state reflects approved live CartmanClient connections.";

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

    function renderMonitoring(data) {
        const monitoring = data.monitoring || {};
        const cards = $$(".stats-grid .stat-card");
        const openAlerts = Number(monitoring.open_alerts || 0);
        const metricSamples = Number(monitoring.metric_samples || 0);
        const serviceChecks = Number(monitoring.service_checks || 0);
        const availabilityChecks = Number(monitoring.availability_checks || 0);
        const alerts = Array.isArray(monitoring.alerts) ? monitoring.alerts : [];

        setStat(
            cards[2],
            number(openAlerts),
            openAlerts ? "Unresolved monitoring alerts" : "No unresolved alerts",
            0
        );
        setStat(
            cards[3],
            number(metricSamples),
            `${number(serviceChecks)} service · ${number(availabilityChecks)} availability checks`,
            0
        );

        const sampleCount = $("#overview-metric-samples");
        const serviceCount = $("#overview-service-checks");
        const availabilityCount = $("#overview-availability-checks");
        if (sampleCount) sampleCount.textContent = number(metricSamples);
        if (serviceCount) serviceCount.textContent = number(serviceChecks);
        if (availabilityCount) availabilityCount.textContent = number(availabilityChecks);

        const list = $("#overview-alert-list");
        if (!list) return;

        if (!alerts.length) {
            list.innerHTML = openAlerts
                ? `<div class="empty-state">${number(openAlerts)} open alert(s) exist, but no alert details were returned.</div>`
                : '<div class="empty-state">No unresolved monitoring alerts.</div>';
            return;
        }

        list.innerHTML = alerts.map((alert) => {
            const severity = String(alert.severity || "Unspecified");
            const severityLower = severity.toLowerCase();
            const priorityClass = /critical|high|fatal/.test(severityLower)
                ? "priority-high"
                : /medium|warning/.test(severityLower) ? "priority-medium" : "priority-low";
            const status = String(alert.status || "Open");
            const statusClass = /acknowledged|in.?progress|investigating/i.test(status)
                ? "progress-pill" : "warning-pill";
            const timestamp = alert.created_at ? String(alert.created_at) : "";
            const normalizedTimestamp = timestamp.replace(
                /^(\d{4}-\d{2}-\d{2})\s+/, "$1T"
            );
            const parsedDate = normalizedTimestamp ? new Date(normalizedTimestamp) : null;
            const displayTime = parsedDate && !Number.isNaN(parsedDate.getTime())
                ? parsedDate.toLocaleString() : timestamp;
            const metadata = [severity, alert.device_id, displayTime].filter(Boolean).join(" · ");
            const detail = alert.details ? String(alert.details) : metadata;

            return `<div class="ticket-row overview-alert-row">
                <span class="priority-dot ${priorityClass}"></span>
                <div><strong>${escapeHTML(alert.title || "Monitoring alert")}</strong>
                    <small>${escapeHTML(detail)}${detail !== metadata && metadata ? ` · ${escapeHTML(metadata)}` : ""}</small></div>
                <span class="status-pill ${statusClass}">${escapeHTML(status)}</span>
            </div>`;
        }).join("");

        if (openAlerts > alerts.length) {
            list.insertAdjacentHTML(
                "beforeend",
                `<div class="overview-alert-more">Showing ${alerts.length} latest alerts of ${number(openAlerts)} unresolved alerts.</div>`
            );
        }
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

    function renderOverviewError(error) {
        const cards = $$(".stats-grid .stat-card");
        cards.forEach((card) => setStat(card, "—", "API unavailable", 0));

        const ring = $(".health-ring");
        if (ring) {
            ring.style.background = "conic-gradient(var(--border) 0%, var(--border) 100%)";
            const strong = $("strong", ring);
            const small = $("small", ring);
            if (strong) strong.textContent = "—";
            if (small) small.textContent = "Unavailable";
        }

        const legend = $(".health-legend");
        if (legend) {
            legend.innerHTML = '<div class="overview-no-status">Live device status unavailable.</div>';
        }

        const devices = $(".device-list");
        if (devices) {
            devices.innerHTML = '<div class="empty-state">Could not load device inventory. Check your session and refresh.</div>';
        }
        const alerts = $("#overview-alert-list");
        if (alerts) {
            alerts.innerHTML = '<div class="empty-state">Monitoring data is unavailable. No sample alerts are shown.</div>';
        }
        const activity = $(".activity-list");
        if (activity) {
            activity.innerHTML = '<div class="empty-state">Could not load monitoring activity. Check your session and refresh.</div>';
        }

        ["#overview-metric-samples", "#overview-service-checks", "#overview-availability-checks"]
            .forEach((selector) => {
                const node = $(selector);
                if (node) node.textContent = "—";
            });

        const sectionHeading = $(".section-heading");
        let updated = $("#overview-last-updated");
        if (!updated && sectionHeading) {
            updated = document.createElement("small");
            updated.id = "overview-last-updated";
            updated.style.marginLeft = "12px";
            sectionHeading.appendChild(updated);
        }
        if (updated) {
            updated.textContent = "API unavailable";
            updated.title = String(error && error.message || "Overview API unavailable");
        }
    }

    async function refreshOverview() {
        const button = $("#refresh-dashboard");
        if (button) button.disabled = true;

        try {
            const response = await fetch("/api/overview", {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store"
            });
            if (!response.ok) throw new Error(`Overview API returned HTTP ${response.status}`);

            const data = await response.json();
            renderDevices(data);
            renderMonitoring(data);
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

            try {
                await window.checkApiStatus?.();
            } catch (statusError) {
                console.warn("Global API status check failed; Overview data loaded successfully:", statusError);
            }
        } catch (error) {
            console.error("Overview refresh failed:", error);
            renderOverviewError(error);
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
