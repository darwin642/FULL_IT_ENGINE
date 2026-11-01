/* CARTMAN_REPORTS_LIVE_V1 */
"use strict";

(() => {
    const root = document.querySelector(".reports-workspace");
    if (!root) return;

    const $ = (selector) => root.querySelector(selector);
    const $$ = (selector) => [...root.querySelectorAll(selector)];
    const state = { meta: null, summary: null, pdfUrl: "", activePreset: "week", activeReportTab: "create" };

    const palette = ["#7773f1", "#23a69d", "#e2a64a", "#e36d77", "#5688d8", "#9270d3"];

    function esc(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[ch]));
    }

    function localDateTime(date) {
        const pad = value => String(value).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function rangeFor(preset) {
        const now = new Date();
        const start = new Date(now);
        if (preset === "day") start.setHours(0, 0, 0, 0);
        else if (preset === "week") {
            const day = (start.getDay() + 6) % 7;
            start.setDate(start.getDate() - day);
            start.setHours(0, 0, 0, 0);
        } else if (preset === "month") {
            start.setDate(1);
            start.setHours(0, 0, 0, 0);
        } else if (preset === "year") {
            start.setMonth(0, 1);
            start.setHours(0, 0, 0, 0);
        }
        $("[data-rp-start]").value = localDateTime(start);
        $("[data-rp-end]").value = localDateTime(now);
        state.activePreset = preset;
        $$('[data-rp-preset]').forEach(button => button.classList.toggle("is-active", button.dataset.rpPreset === preset));
    }

    function getFilters() {
        const startRaw = $("[data-rp-start]").value;
        const endRaw = $("[data-rp-end]").value;
        if (!startRaw || !endRaw) throw new Error("Choose both a start and end date/time.");
        const startDate = new Date(startRaw);
        const endDate = new Date(endRaw);
        if (!Number.isFinite(startDate.getTime()) || !Number.isFinite(endDate.getTime()) || endDate <= startDate) {
            throw new Error("End date/time must be later than start date/time.");
        }
        return {
            start: startDate.toISOString(),
            end: endDate.toISOString(),
            department_id: $("[data-rp-department]").value || "",
            team: $("[data-rp-team]").value || ""
        };
    }

    function alertMessage(message, isError = false) {
        const node = $("[data-rp-alert]");
        node.textContent = message;
        node.classList.toggle("is-error", isError);
        node.classList.remove("hidden");
    }

    function clearAlert() {
        $("[data-rp-alert]").classList.add("hidden");
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            headers: { "Accept": "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
            ...options
        });
        const contentType = response.headers.get("content-type") || "";
        const body = contentType.includes("application/json") ? await response.json() : await response.text();
        if (!response.ok) {
            const message = body && typeof body === "object" ? (body.detail || body.message) : body;
            throw new Error(message || `Request failed (${response.status}).`);
        }
        return body;
    }

    function fillSelect(select, items, label, value = "") {
        const current = select.value;
        select.innerHTML = `<option value="">${esc(label)}</option>` + items.map(item => {
            const itemValue = typeof item === "string" ? item : item.id;
            const itemLabel = typeof item === "string" ? item : item.name;
            return `<option value="${esc(itemValue)}">${esc(itemLabel)}</option>`;
        }).join("");
        if ([...select.options].some(option => option.value === current)) select.value = current;
        else select.value = value;
    }

    function metricCard(label, value, note = "") {
        const displayValue = value == null ? "—" : (value.toLocaleString ? value.toLocaleString() : value);
        return `<article class="io-stat"><span>${esc(label)}</span><strong>${esc(displayValue)}</strong>${note ? `<small>${esc(note)}</small>` : ""}</article>`;
    }

    function miniMetric(label, value, note = "") {
        return `<div class="rp-mini-metric"><span>${esc(label)}</span><strong>${value == null ? "—" : esc(value)}</strong>${note ? `<span>${esc(note)}</span>` : ""}</div>`;
    }

    function renderChart(name, rows, unit = "") {
        const target = $(`[data-rp-chart="${name}"]`);
        if (!target) return;
        if (!Array.isArray(rows) || !rows.length) {
            target.innerHTML = `<div class="rp-empty">No records were collected for this chart in the selected range.</div>`;
            return;
        }

        // Reuse the original demo's tall column-chart component, now fed by live API rows.
        const chartRows = rows.slice(0, 10);
        const max = Math.max(1, ...chartRows.map(row => Number(row.value) || 0));
        target.innerHTML = chartRows.map((row, index) => {
            const value = Number(row.value) || 0;
            const height = value > 0 ? Math.max(3, Math.min(100, value / max * 100)) : 0;
            const color = palette[index % palette.length];
            const label = row.label || "Unspecified";
            const displayValue = value.toLocaleString ? value.toLocaleString() : value;
            return `<div class="io-bar-group" title="${esc(label)}: ${esc(displayValue)}${esc(unit)}"><span>${esc(displayValue)}${esc(unit)}</span><div class="io-bar" style="height:${height}%;background:linear-gradient(180deg,${color},${color}cc);box-shadow:0 0 15px ${color}33"></div><small>${esc(label)}</small></div>`;
        }).join("");
    }

    function renderSource(key, object) {
        const node = $(`[data-rp-source="${key}"]`);
        if (!node) return;
        const available = !!(object && object.available);
        node.textContent = available ? "LIVE DATABASE" : "SOURCE UNAVAILABLE";
        node.classList.toggle("is-available", available);
        node.classList.toggle("is-unavailable", !available);
    }

    function renderSummary(data) {
        state.summary = data;
        const sourceState = $("[data-rp-source-state]");
        sourceState.textContent = "Live database connected";
        sourceState.parentElement.classList.add("is-live");

        const kpis = data.kpis || [];
        $("[data-rp-kpis]").innerHTML = kpis.map(item => metricCard(item.label, item.value, item.value == null ? "Source not available" : "From stored Cartman records")).join("");

        const ticket = data.tickets || {};
        renderSource("tickets", ticket);
        if (ticket.available) {
            renderChart("ticket-teams", ticket.by_team);
            renderChart("ticket-status", ticket.by_status);
            renderChart("ticket-priority", ticket.by_priority);
            renderChart("ticket-type", ticket.by_type);
            renderChart("ticket-escalation", ticket.by_escalation);
            $("[data-rp-ticket-timing]").innerHTML = [
                miniMetric("Tickets created", ticket.created),
                miniMetric("Resolved in period", ticket.resolved_in_period),
                miniMetric("Average first response", ticket.average_first_response_hours == null ? "Not measured" : `${ticket.average_first_response_hours} h`, `${ticket.first_response_samples || 0} measured tickets`),
                miniMetric("Average resolution", ticket.average_resolution_hours == null ? "Not measured" : `${ticket.average_resolution_hours} h`, `${ticket.resolved_time_samples || 0} resolved tickets`)
            ].join("");
            $("[data-rp-sla-note]").textContent = `${ticket.sla_note || "No formal SLA policy data is configured."} 24h windows started: ${ticket.requester_24h_windows_started == null ? "not tracked" : ticket.requester_24h_windows_started}; automatic timeout reopens: ${ticket.requester_24h_timeouts == null ? "not tracked" : ticket.requester_24h_timeouts}.`;
            const ticketScope = $("[data-rp-ticket-scope-note]");
            if (ticketScope) ticketScope.textContent = ticket.scope_note || "Ticket department grouping is based on the department of the linked assigned IAM user. Team distribution uses the stored ticket team field.";
        } else {
            ["ticket-teams", "ticket-status", "ticket-priority", "ticket-type", "ticket-escalation"].forEach(key => renderChart(key, []));
            $("[data-rp-ticket-timing]").innerHTML = `<div class="rp-empty">${esc(ticket.reason || "Ticket source unavailable.")}</div>`;
        }

        const workload = data.workload || {};
        renderSource("workload", workload);
        if (workload.available) {
            $("[data-rp-work-kpis]").innerHTML = [
                metricCard("Created in period", workload.created_in_period),
                metricCard("Completed in period", workload.completed_in_period),
                metricCard("Current open", workload.current_open),
                metricCard("In progress", workload.current_in_progress),
                metricCard("In review", workload.current_review)
            ].join("");
            renderChart("work-status", workload.by_status);
            renderChart("work-owner", workload.by_owner);
            renderChart("work-department", workload.by_department);
            renderChart("work-project", workload.by_project);
            renderChart("work-priority", workload.by_priority);
            $("[data-rp-work-note]").textContent = workload.overdue_note || "";
            const workScope = $("[data-rp-work-scope-note]");
            if (workScope) workScope.textContent = workload.scope_note || "Work items are grouped by stored assignment and project relationships.";
        } else {
            $("[data-rp-work-kpis]").innerHTML = metricCard("Work items", null, workload.reason || "Unavailable");
            ["work-status", "work-owner", "work-department", "work-project", "work-priority"].forEach(key => renderChart(key, []));
        }

        const devices = data.devices || {};
        renderSource("devices", devices);
        if (devices.available) {
            renderChart("device-status", devices.by_status);
            renderChart("device-os", devices.by_os);
            renderChart("device-type", devices.by_type);
            $("[data-rp-device-note]").textContent = `${devices.registered_in_period == null ? "New registrations were not timestamped." : `${devices.registered_in_period} devices registered in this period.`} ${devices.snapshot_note || ""}`;
        } else {
            ["device-status", "device-os", "device-type"].forEach(key => renderChart(key, []));
            $("[data-rp-device-note]").textContent = devices.reason || "Device source unavailable.";
        }
        const inventory = data.inventory || {};
        renderChart("inventory-type", inventory.available ? inventory.by_type : []);
        const inventoryScope = $("[data-rp-inventory-scope-note]");
        if (inventoryScope) inventoryScope.textContent = inventory.available ? (inventory.scope_note || "Inventory assets use the actual department name stored on each asset.") : (inventory.reason || "Inventory source unavailable.");

        const monitoring = data.monitoring || {};
        renderSource("monitoring", monitoring);
        if (monitoring.available) {
            renderChart("alert-severity", monitoring.alerts_by_severity);
            renderChart("event-severity", monitoring.events_by_severity);
            renderChart("metric-averages", (monitoring.metric_averages || []).map(row => ({ label: `${row.label} (${row.unit || "value"})`, value: row.value })));
            const checks = [];
            if (monitoring.availability) checks.push(miniMetric("Availability check success", monitoring.availability.success_rate_percent == null ? "Not measured" : `${monitoring.availability.success_rate_percent}%`, `${monitoring.availability.checks} stored checks`));
            if (monitoring.availability) checks.push(miniMetric("Average response", monitoring.availability.average_response_ms == null ? "Not measured" : `${monitoring.availability.average_response_ms} ms`));
            if (monitoring.service_checks) checks.push(miniMetric("Service checks", monitoring.service_checks.checks));
            if (monitoring.service_checks) checks.push(miniMetric("Service-check success", monitoring.service_checks.success_rate_percent == null ? "Not measured" : `${monitoring.service_checks.success_rate_percent}%`));
            if (monitoring.alerts_created != null) checks.push(miniMetric("Alerts created", monitoring.alerts_created));
            if (monitoring.alerts_resolved != null) checks.push(miniMetric("Alerts resolved", monitoring.alerts_resolved));
            if (monitoring.average_alert_resolution_hours != null) checks.push(miniMetric("Average alert resolution", `${monitoring.average_alert_resolution_hours} h`, `${monitoring.alert_resolution_samples || 0} measured alerts`));
            $("[data-rp-check-metrics]").innerHTML = checks.length ? checks.join("") : `<div class="rp-empty">No check or alert records were collected for this period.</div>`;
            const monitoringNote = $("[data-rp-monitoring-note]");
            if (monitoringNote) monitoringNote.textContent = monitoring.scope_note || "Department filtering is applied to monitoring records when they have a matching device_id relationship.";
        } else {
            ["alert-severity", "event-severity", "metric-averages"].forEach(key => renderChart(key, []));
            $("[data-rp-check-metrics]").innerHTML = `<div class="rp-empty">${esc(monitoring.reason || "Monitoring source unavailable.")}</div>`;
        }

        const network = data.network_vpn || {};
        renderSource("network_vpn", network);
        const records = [];
        Object.entries(network.network_inventory || {}).forEach(([key, value]) => records.push(`<div class="rp-record"><span>${esc(key.replace(/_/g, " "))}</span><strong>${esc(value)}</strong></div>`));
        Object.entries(network.vpn || {}).forEach(([key, value]) => {
            if (typeof value === "number") records.push(`<div class="rp-record"><span>${esc(key.replace(/_/g, " "))}</span><strong>${esc(value)}</strong></div>`);
        });
        $("[data-rp-network-records]").innerHTML = records.length ? records.join("") : `<div class="rp-empty">No network/VPN records are available in the current database.</div>`;
        renderChart("vpn-events", network.vpn && network.vpn.events_by_type);
        const networkNote = $("[data-rp-network-note]");
        if (networkNote) networkNote.textContent = network.scope_note || "Network infrastructure records do not currently have a department link; these configuration totals remain organization-wide.";

        const deployment = data.deployment || {};
        renderSource("deployment", deployment);
        renderChart("task-actions", deployment.available ? deployment.by_action : []);
        renderChart("task-status", deployment.available ? deployment.by_status : []);
        const deploymentNote = $("[data-rp-deployment-note]");
        if (deploymentNote) deploymentNote.textContent = deployment.scope_note || "Endpoint task department filtering follows the linked device department.";

        const automation = data.automation || {};
        renderSource("automation", automation);
        renderChart("automation-status", automation.available && automation.by_status ? automation.by_status : []);
        renderChart("workflow-status", automation.workflow_runs && automation.workflow_runs.available ? automation.workflow_runs.by_status : []);
        $("[data-rp-automation-total]").textContent = automation.executions == null ? "No automation execution data" : `${automation.executions} executions`;
        $("[data-rp-workflow-total]").textContent = !automation.workflow_runs || !automation.workflow_runs.available ? "No workflow run data" : `${automation.workflow_runs.runs} runs`;
        const automationNote = $("[data-rp-automation-note]");
        if (automationNote) automationNote.textContent = automation.scope_note || "Automation data is grouped organization-wide because the current execution records do not store department assignments.";

        const software = data.software || {};
        renderSource("software", software);
        renderChart("software-actions", software.available ? software.changes_by_action : []);
        renderChart("software-status", software.available ? software.catalog_by_status : []);
        renderChart("software-os", software.available ? software.catalog_by_os : []);
        const softwareTotal = $("[data-rp-software-total]");
        if (softwareTotal) softwareTotal.textContent = software.changes_in_period == null ? "Change history unavailable" : `${software.changes_in_period} recorded changes`;
        const softwareNote = $("[data-rp-software-note]");
        if (softwareNote) softwareNote.textContent = software.scope_note || "Software catalogue counts are current snapshots; audit changes are counted within the selected period.";

        const platform = data.platform_activity || {};
        renderSource("platform_activity", platform);
        renderChart("platform-sources", platform.available ? platform.by_source : []);
        renderChart("platform-device-requests", platform.available ? platform.device_requests_by_status : []);
        const platformNote = $("[data-rp-platform-note]");
        if (platformNote) platformNote.textContent = platform.scope_note || "Platform audit data is shown for the organization because the source records do not share a department link.";

        const systemMetrics = data.system_metrics || {};
        renderSource("system_metrics", systemMetrics);
        renderChart("system-averages", systemMetrics.available ? systemMetrics.averages : []);
        const systemNote = $("[data-rp-system-note]");
        if (systemNote) systemNote.textContent = systemMetrics.reason || `${systemMetrics.samples || 0} stored process metric samples. These are averages of collected records, not live readings.`;

        const activity = data.activity || {};
        renderSource("activity", activity);
        const activityItems = [];
        [["Active users", activity.active_users], ["In-app activity time", activity.active_seconds == null ? null : `${(activity.active_seconds / 3600).toFixed(2)} h`], ["Activity samples", activity.activity_samples], ["Login attempts", activity.login_attempts], ["Successful logins", activity.successful_logins], ["Failed logins", activity.failed_logins], ["Sessions created", activity.sessions_created]].forEach(([label, value]) => {
            if (value != null) activityItems.push(miniMetric(label, value));
        });
        $("[data-rp-activity-metrics]").innerHTML = activityItems.length ? activityItems.join("") : `<div class="rp-empty">${esc(activity.reason || "No activity records in this period.")}</div>`;

        const activityNote = $("[data-rp-activity-note]");
        if (activityNote) activityNote.textContent = activity.scope_note || "Department grouping uses the department recorded on linked IAM directory users.";

        const remote = data.remote_access || {};
        renderSource("remote_access", remote);
        renderChart("remote-status", remote.available ? remote.by_status : []);
        $("[data-rp-remote-metrics]").innerHTML = remote.available ? [miniMetric("Sessions", remote.sessions), miniMetric("Average duration", remote.average_duration_minutes == null ? "Not measured" : `${remote.average_duration_minutes} min`, `${remote.duration_samples || 0} completed sessions`)].join("") : `<div class="rp-empty">${esc(remote.reason || "No remote access history.")}</div>`;
        const remoteNote = $("[data-rp-remote-note]");
        if (remoteNote) remoteNote.textContent = remote.scope_note || "No department or support-team relation is stored on remote-access sessions; this section remains organization-wide.";

        const dept = data.filters && data.filters.department || "All departments";
        const team = data.filters && data.filters.team || "All support teams";
        $("[data-rp-filter-note]").textContent = `${dept} · ${team} · ${new Date(data.period.start).toLocaleString()} — ${new Date(data.period.end).toLocaleString()}`;
    }

    function setReportTab(tab) {
        state.activeReportTab = tab;
        $$('[data-rp-tab]').forEach(button => {
            const active = button.dataset.rpTab === tab;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        $$('[data-rp-pane]').forEach(pane => pane.classList.toggle("hidden", pane.dataset.rpPane !== tab));
        if (tab === "history") loadHistory();
    }

    function updateScopeTargets() {
        const type = $("[data-rp-scope-type]").value;
        const target = $("[data-rp-scope-target]");
        const note = $("[data-rp-scope-note]");
        const config = {
            user: { items: state.meta && state.meta.users || [], placeholder: "Choose a user", empty: "No active IAM users found", note: "The report includes records reliably linked to the selected IAM user." },
            group: { items: state.meta && state.meta.groups || [], placeholder: "Choose a group", empty: "No active IAM groups found", note: "The report includes records linked to active members of the selected IAM group. Sources without a reliable member relationship are omitted." },
            department: { items: state.meta && state.meta.departments || [], placeholder: "Choose a department", empty: "No departments found", note: "The report uses Cartman's existing department relationships. Sources without a department relationship are identified in the PDF." }
        }[type];
        if (!config) {
            target.innerHTML = '<option value="">Choose target type first</option>';
            target.disabled = true;
            note.textContent = "Select whether this PDF is for one IAM user, an existing IAM group, or a department.";
            return;
        }
        fillSelect(target, config.items, config.items.length ? config.placeholder : config.empty);
        target.disabled = !config.items.length;
        note.textContent = config.note;
    }

    function getReportScope() {
        const type = $("[data-rp-scope-type]").value;
        const id = $("[data-rp-scope-target]").value;
        if (!["user", "group", "department"].includes(type) || !id) {
            throw new Error("Choose a User, Group, or Department and select its target before creating the PDF.");
        }
        return { type, id };
    }

    function formatDate(value) {
        if (!value) return "—";
        const date = new Date(String(value).replace(" ", "T") + (String(value).endsWith("Z") ? "" : "Z"));
        return Number.isFinite(date.getTime()) ? date.toLocaleString() : String(value);
    }

    async function loadHistory() {
        const list = $("[data-rp-history-list]");
        if (!list) return;
        list.innerHTML = '<div class="rp-history-empty">Loading report history…</div>';
        try {
            const result = await api("/api/reports/history?limit=200");
            const items = Array.isArray(result.items) ? result.items : [];
            if (!items.length) {
                list.innerHTML = '<div class="rp-history-empty">No PDF reports have been generated yet.</div>';
                return;
            }
            const scopeLabel = item => {
                const scope = item.report_scope || {};
                const type = ({ user: "User", group: "Group", department: "Department", organization: "Organization" })[scope.type] || "Report";
                return `${type} · ${scope.name || "Unknown target"}`;
            };
            list.innerHTML = items.map(item => `<article class="rp-history-item">
                <div class="rp-history-file-icon">PDF</div>
                <div class="rp-history-details"><strong>${esc(item.filename)}</strong><span>${esc(scopeLabel(item))}</span><small>Generated ${esc(formatDate(item.created_at))} · By ${esc(item.created_by_username || "Unknown")} · ${esc(formatDate(item.period_start))} — ${esc(formatDate(item.period_end))}</small></div>
                <div class="rp-history-actions"><a class="io-btn rp-history-view" href="${esc(item.view_url)}" target="_blank" rel="noopener">View</a><a class="io-btn" href="${esc(item.download_url)}">Download</a></div>
            </article>`).join("");
        } catch (error) {
            list.innerHTML = `<div class="rp-history-empty is-error">Could not load PDF history: ${esc(error.message || "Unknown error")}</div>`;
        }
    }

    async function loadMeta() {

        const meta = await api("/api/reports/meta");
        state.meta = meta;
        fillSelect($("[data-rp-department]"), meta.departments || [], "All departments");
        fillSelect($("[data-rp-team]"), meta.teams || [], "All support teams");
        updateScopeTargets();

        const department = $("[data-rp-department]");
        const team = $("[data-rp-team]");
        if (!meta.departments || !meta.departments.length) department.options[0].textContent = "No departments recorded";
        if (!meta.teams || !meta.teams.length) team.options[0].textContent = "No support teams recorded";
        const sourceCount = Object.values(meta.sources || {}).filter(Boolean).length;
        $("[data-rp-source-state]").textContent = `${sourceCount} live data sources detected`;
        $("[data-rp-source-state]").parentElement.classList.add("is-live");
    }

    async function loadSummary() {
        clearAlert();
        const applyButton = $("[data-rp-apply]");
        applyButton.disabled = true;
        try {
            const filters = getFilters();
            const qs = new URLSearchParams(filters);
            const result = await api(`/api/reports/summary?${qs.toString()}`);
            renderSummary(result);
        } catch (error) {
            alertMessage(error.message || "Could not load reports.", true);
        } finally {
            applyButton.disabled = false;
        }
    }

    async function createPdf() {
        clearAlert();
        const button = $("[data-rp-create-pdf]");
        const status = $("[data-rp-pdf-status]");
        const sections = $$('[data-rp-pdf-section]:checked').map(input => input.dataset.rpPdfSection);
        if (!sections.length) {
            status.textContent = "Select at least one report section.";
            return;
        }
        button.disabled = true;
        button.textContent = "Generating PDF…";
        status.textContent = "Collecting selected metrics and building the PDF…";
        $("[data-rp-view-pdf]").classList.add("hidden");
        try {
            const reportScope = getReportScope();
            const result = await api("/api/reports/pdf", {

                method: "POST",

                body: JSON.stringify({ ...getFilters(), sections, report_scope: reportScope })

            });

            state.pdfUrl = result.view_url;
            status.textContent = `PDF generation complete · ${result.filename}`;
            $("[data-rp-view-pdf]").classList.remove("hidden");
            loadHistory();

        } catch (error) {
            status.textContent = `PDF could not be generated: ${error.message || "Unknown error"}`;
            alertMessage(error.message || "PDF generation failed.", true);
        } finally {
            button.disabled = false;
            button.textContent = "Create PDF";

        }
    }

    $$('[data-rp-preset]').forEach(button => button.addEventListener("click", () => {
        const preset = button.dataset.rpPreset;
        if (preset !== "custom") rangeFor(preset);
        else {
            state.activePreset = "custom";
            $$('[data-rp-preset]').forEach(item => item.classList.toggle("is-active", item === button));
        }
    }));
    ["[data-rp-start]", "[data-rp-end]"].forEach(selector => $(selector).addEventListener("change", () => {
        state.activePreset = "custom";
        $$('[data-rp-preset]').forEach(button => button.classList.toggle("is-active", button.dataset.rpPreset === "custom"));
    }));
    $("[data-rp-apply]").addEventListener("click", loadSummary);
    $("[data-rp-create-pdf]").addEventListener("click", createPdf);
    $$("[data-rp-tab]").forEach(button => button.addEventListener("click", () => setReportTab(button.dataset.rpTab)));
    $("[data-rp-scope-type]").addEventListener("change", updateScopeTargets);
    $("[data-rp-refresh-history]").addEventListener("click", loadHistory);

    $("[data-rp-view-pdf]").addEventListener("click", () => {
        if (state.pdfUrl) window.open(state.pdfUrl, "_blank", "noopener");
    });

    (async () => {
        rangeFor("week");
        try {
            await loadMeta();
            await loadSummary();
        } catch (error) {
            $("[data-rp-source-state]").textContent = "Live data unavailable";
            alertMessage(error.message || "Reports API is unavailable. Check administrator access and the Cartman API server.", true);
            $("[data-rp-kpis]").innerHTML = metricCard("Reporting API", "Unavailable", "No demo values are shown");
        }
    })();
})();
