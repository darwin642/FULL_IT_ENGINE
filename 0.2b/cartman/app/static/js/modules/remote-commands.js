/* CARTMAN_REMOTE_COMMANDS_V2 */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const $ = selector => document.querySelector(selector);
    const search = $("[data-rc-search]");
    const statusFilter = $("[data-rc-status]");
    const osFilter = $("[data-rc-os]");
    const rows = $("[data-rc-rows]");
    const empty = $("[data-rc-empty]");
    const count = $("[data-rc-count]");
    const footerCount = $("[data-rc-footer-count]");
    const actionSelect = $("[data-rc-template]");
    const targetSelect = $("#rc-target");
    const command = $("[data-rc-command]");
    const commandLabel = $("[data-rc-command-label]");
    const clearButton = $("[data-rc-clear]");
    const copyButton = $("[data-rc-copy]");
    const createTemplateButton = $("[data-rc-create-template]");
    const runButton = $("[data-rc-run]");
    const feedback = $("[data-rc-feedback]");
    const refreshButton = $("[data-rc-refresh]");
    const targetStatus = $("[data-rc-target-status]");
    const templateDescriptionDisplay = $("[data-rc-template-description-display]");
    const templateDetails = $("[data-rc-template-details]");
    const templateDetailName = $("[data-rc-template-detail-name]");
    const templateDetailOS = $("[data-rc-template-detail-os]");
    const templateDetailDescription = $("[data-rc-template-detail-description]");
    const liveOutput = $("[data-rc-live-output]");
    const liveOutputStatus = $("[data-rc-live-output-status]");
    const scheduleModal = $("[data-rc-schedule-modal]");
    const scheduleForm = $("[data-rc-schedule-form]");
    const scheduleTime = $("[data-rc-schedule-time]");
    const scheduleError = $("[data-rc-schedule-error]");
    const scheduleSubmit = $("[data-rc-schedule-submit]");
    const templateModal = $("[data-rc-template-modal]");
    const templateForm = $("[data-rc-template-form]");
    const templateName = $("[data-rc-template-name]");
    const templateOS = $("[data-rc-template-os]");
    const templateDescription = $("[data-rc-template-description]");
    const templateCommand = $("[data-rc-template-command]");
    const templateError = $("[data-rc-template-error]");
    const templateSave = $("[data-rc-template-save]");
    const storageKey = "cartman-remote-command-templates-v1";

    if (!search || !statusFilter || !osFilter || !rows || !empty ||
        !actionSelect || !targetSelect || !command || !runButton ||
        !templateModal || !templateForm || !templateName || !templateOS ||
        !templateDescription || !templateCommand || !templateError) return;

    let devices = [];
    let clients = [];
    let agents = [];
    let records = [];
    let templates = [];
    let loading = false;
    let submitting = false;
    let selectedTask = null;
    let latestTaskId = null;
    let latestCommandText = "";
    let latestTargetName = "";
    let latestScheduleText = "";

    async function api(url, options = {}) {
        let operator = "Cartman Operator";
        try {
            operator = localStorage.getItem("cartman-operator-name") || operator;
        } catch (_) {}

        const response = await fetch(url, {
            cache: "no-store",
            ...options,
            headers: {
                "Accept": "application/json",
                "X-Operator": operator,
                ...(options.body ? {"Content-Type": "application/json"} : {}),
                ...(options.headers || {})
            }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(typeof data.detail === "string"
                ? data.detail : `Request failed (HTTP ${response.status})`);
        }
        return data;
    }

    function osFamily(value) {
        const os = String(value || "").toLowerCase();
        if (os.includes("windows") || os.startsWith("win")) return "Windows";
        if (os.includes("mac") || os.includes("darwin")) return "macOS";
        if (os.includes("linux") || os.includes("ubuntu") || os.includes("debian")
            || os.includes("fedora") || os.includes("red hat")) return "Linux";
        return "Unknown";
    }

    function selectedSavedTemplate() {
        if (!actionSelect.value.startsWith("custom:")) return null;
        const id = actionSelect.value.slice(7);
        return templates.find(item => item.id === id) || null;
    }

    function isCustomAction() {
        // The command editor is always available; template selection is optional.
        return true;
    }

    function loadTemplates() {
        try {
            const value = JSON.parse(localStorage.getItem(storageKey) || "[]");
            templates = Array.isArray(value) ? value.filter(item =>
                item && typeof item.id === "string" &&
                typeof item.name === "string" &&
                typeof item.command === "string" &&
                ["Any", "Windows", "macOS", "Linux"].includes(item.target_os)
            ) : [];
        } catch (_) {
            templates = [];
        }
    }

    function renderTemplateOptions() {
        const previous = actionSelect.value;
        const group = actionSelect.querySelector('optgroup[data-rc-custom-group]');
        if (group) group.remove();

        if (templates.length) {
            const customGroup = document.createElement("optgroup");
            customGroup.label = "Custom templates";
            customGroup.dataset.rcCustomGroup = "true";
            for (const item of templates) {
                const option = document.createElement("option");
                option.value = "custom:" + item.id;
                option.textContent = `${item.name} · ${item.target_os}`;
                customGroup.appendChild(option);
            }
            actionSelect.appendChild(customGroup);
        }

        if ([...actionSelect.options].some(option => option.value === previous)) {
            actionSelect.value = previous;
        } else {
            actionSelect.value = "";
        }
    }

    function targetIsRegistered(deviceId) {
        return agents.some(agent => agent.device_id === deviceId);
    }

    function liveClient(deviceId) {
        return clients.find(client => client.device_id === deviceId &&
            client.connected === true && client.approval_status === "Approved");
    }

    function targetIsExecutionReady(deviceId) {
        const live = liveClient(deviceId);
        return Boolean(live && live.task_execution_enabled === true);
    }

    function populateTargets(targetOS = "Any") {
        const previous = targetSelect.value;
        const wantedOS = targetOS === "Any" ? "Any" : targetOS;

        targetSelect.replaceChildren(new Option("Choose a device...", ""));
        for (const device of devices) {
            if (wantedOS !== "Any" && osFamily(device.os) !== wantedOS) continue;

            const registered = targetIsRegistered(device.id);
            const live = liveClient(device.id);
            let availability;

            if (!registered) availability = "No agent enrolled";
            else if (live && live.task_execution_enabled === true) availability = "Online · Ready";
            else if (live) availability = "Connected · execution disabled";
            else availability = "Offline · queue on reconnect";

            targetSelect.add(new Option(
                `${device.name} · ${device.os || "Unknown OS"} · ${availability}`,
                device.id
            ));
        }

        if ([...targetSelect.options].some(option => option.value === previous)) {
            targetSelect.value = previous;
        } else {
            targetSelect.value = "";
        }
    }

    function updateTargetNotice() {
        if (!targetStatus) return;

        const device = devices.find(item => item.id === targetSelect.value);
        if (!device) {
            targetStatus.hidden = true;
            targetStatus.textContent = "";
            return;
        }

        targetStatus.hidden = false;
        const registered = targetIsRegistered(device.id);
        const live = liveClient(device.id);
        const ready = targetIsExecutionReady(device.id);

        if (!registered) {
            targetStatus.dataset.state = "error";
            targetStatus.textContent =
                "This device has no enrolled CartmanClient identity. Enroll and approve an agent before queueing tasks.";
        } else if (live && !ready) {
            targetStatus.dataset.state = "error";
            targetStatus.textContent =
                "CartmanClient is connected, but task execution is disabled. Restart it with --enable-task-execution.";
        } else if (!live) {
            targetStatus.dataset.state = "offline";
            targetStatus.textContent =
                "This device is offline. You can queue the task now; it will execute when the device comes online and its approved CartmanClient reconnects with task execution enabled.";
        } else {
            targetStatus.dataset.state = "ready";
            targetStatus.textContent =
                "Device is online and ready to receive tasks.";
        }
    }

    function updateComposer() {
        const saved = selectedSavedTemplate();

        command.readOnly = false;
        if (commandLabel) commandLabel.textContent = "Command";

        if (templateDescriptionDisplay) {
            templateDescriptionDisplay.textContent = saved?.description || "";
            templateDescriptionDisplay.hidden = !saved?.description;
        }

        if (templateDetails) {
            templateDetails.hidden = !saved;
            if (saved) {
                if (templateDetailName) templateDetailName.textContent = saved.name;
                if (templateDetailOS) templateDetailOS.textContent = "Target OS: " + saved.target_os;
                if (templateDetailDescription) {
                    templateDetailDescription.textContent = saved.description || "No description provided.";
                }
            }
        }

        if (copyButton) copyButton.disabled = !command.value.trim();

        populateTargets(saved ? saved.target_os : "Any");
        updateTargetNotice();

        const deviceId = targetSelect.value;
        const registered = deviceId && targetIsRegistered(deviceId);
        const live = deviceId && liveClient(deviceId);
        const ready = deviceId && targetIsExecutionReady(deviceId);

        let canQueue = Boolean(deviceId && registered && command.value.trim());
        if (live && !ready) canQueue = false;

        runButton.disabled = !canQueue || submitting;
        runButton.title = "Review and queue the command for the selected endpoint.";
        updateLiveOutput();
    }

    function normalizeStatus(value) {
        const status = String(value || "").toLowerCase();
        if (["succeeded", "completed", "success"].includes(status)) return "completed";
        if (["failed", "error"].includes(status)) return "failed";
        if (["running", "started"].includes(status)) return "running";
        return "pending";
    }

    function formatTime(value) {
        if (!value) return "—";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
    }

    function formatDuration(task) {
        const start = new Date(task.started_at || task.created_at || "");
        if (Number.isNaN(start.getTime())) return "—";
        if (!task.finished_at) return normalizeStatus(task.status) === "running" ? "Running" : "—";
        const end = new Date(task.finished_at);
        if (Number.isNaN(end.getTime())) return "—";
        const seconds = Math.max(0, Math.round((end - start) / 1000));
        return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    }

    function actionLabel(action) {
        return ({
            self_test: "Agent connection self-test",
            shutdown: "Device shutdown",
            remote_command: "Remote command",
            package_deployment: "Software deployment",
            network_disconnect: "Network disconnect",
            vpn_action: "VPN action"
        })[action] || action || "Unknown action";
    }

    function addCell(row, value) {
        const cell = document.createElement("td");
        cell.textContent = value == null || value === "" ? "—" : String(value);
        row.appendChild(cell);
        return cell;
    }

    function getTaskCommand(task) {
        const parse = value => {
            if (value && typeof value === "object") return value;
            if (typeof value === "string") {
                try {
                    const parsed = JSON.parse(value);
                    return parsed && typeof parsed === "object" ? parsed : {};
                } catch (_) {
                    return {};
                }
            }
            return {};
        };

        const payload = parse(task.payload ?? task.payload_json);
        const execution = parse(task.execution ?? task.execution_json);

        const candidates = [
            task.command,
            task.command_text,
            payload.command,
            execution.install_command,
            payload.install_command
        ];

        return candidates.find(value =>
            typeof value === "string" && value.trim()
        ) || "";
    }

    function showTaskPopup(task) {
        document.getElementById("rc-history-popup")?.remove();

        if (!document.getElementById("rc-history-popup-style")) {
            const style = document.createElement("style");
            style.id = "rc-history-popup-style";
            style.textContent = `
                #rc-history-popup {
                    position: fixed; inset: 0; z-index: 99999;
                    display: flex; align-items: center; justify-content: center;
                    padding: 20px; background: rgba(0,0,0,.68);
                }
                #rc-history-popup .rc-history-dialog {
                    box-sizing: border-box; width: min(760px, 100%);
                    max-height: calc(100vh - 40px); display: flex;
                    flex-direction: column; overflow: hidden;
                    color: var(--text-primary, #edf0f6);
                    background: var(--bg-secondary, #171c27);
                    border: 1px solid var(--border-color, #343b49);
                    border-radius: 16px;
                    box-shadow: 0 24px 80px rgba(0,0,0,.4);
                }
                #rc-history-popup .rc-history-header {
                    display: flex; align-items: center; justify-content: space-between;
                    gap: 16px; padding: 18px 22px;
                    border-bottom: 1px solid var(--border-color, #343b49);
                }
                #rc-history-popup .rc-history-heading {
                    margin: 0; font-size: 17px; font-weight: 650;
                }
                #rc-history-popup .rc-history-meta {
                    margin-top: 5px; font-size: 12px; opacity: .7;
                }
                #rc-history-popup .rc-history-close {
                    flex: 0 0 auto; width: 36px; height: 36px;
                    border: 1px solid var(--border-color, #343b49);
                    border-radius: 9px; cursor: pointer;
                    color: inherit; background: transparent; font-size: 22px;
                }
                #rc-history-popup .rc-history-content {
                    overflow-y: auto; padding: 18px 22px 22px;
                    display: grid; gap: 16px;
                }
                #rc-history-popup .rc-history-label {
                    margin-bottom: 8px; font-size: 12px; font-weight: 650;
                    letter-spacing: .04em; text-transform: uppercase; opacity: .7;
                }
                #rc-history-popup .rc-history-box {
                    box-sizing: border-box; margin: 0; padding: 14px;
                    max-height: 26vh; overflow: auto; white-space: pre-wrap;
                    overflow-wrap: anywhere; font: 12px/1.65 ui-monospace,
                    SFMono-Regular, Menlo, Consolas, monospace;
                    background: var(--bg-primary, rgba(0,0,0,.2));
                    border: 1px solid var(--border-color, #343b49);
                    border-radius: 10px;
                }
                #rc-history-popup .rc-history-status {
                    display: inline-block; margin-top: 9px; padding: 4px 9px;
                    border-radius: 999px; font-size: 11px;
                    background: var(--bg-primary, rgba(255,255,255,.08));
                }
                @media (max-width: 600px) {
                    #rc-history-popup { padding: 10px; }
                    #rc-history-popup .rc-history-header,
                    #rc-history-popup .rc-history-content { padding: 14px; }
                    #rc-history-popup .rc-history-box { max-height: 30vh; }
                }
            `;
            document.head.appendChild(style);
        }

        const overlay = document.createElement("div");
        overlay.id = "rc-history-popup";

        const dialog = document.createElement("section");
        dialog.className = "rc-history-dialog";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-label", "Command execution details");

        const header = document.createElement("div");
        header.className = "rc-history-header";

        const headingWrap = document.createElement("div");
        const heading = document.createElement("h2");
        heading.className = "rc-history-heading";
        heading.textContent = actionLabel(task.action);

        const meta = document.createElement("div");
        meta.className = "rc-history-meta";
        meta.textContent =
            `${task.device_name || "Unknown device"} · ` +
            `${task.device_os || "Unknown OS"} · ${formatTime(task.created_at)}`;

        const status = document.createElement("div");
        status.className = "rc-history-status";
        status.textContent = task.status || "Unknown";
        status.dataset.status = normalizeStatus(task.status);

        headingWrap.append(heading, meta, status);

        const closeButton = document.createElement("button");
        closeButton.className = "rc-history-close";
        closeButton.type = "button";
        closeButton.setAttribute("aria-label", "Close popup");
        closeButton.textContent = "×";
        header.append(headingWrap, closeButton);

        const content = document.createElement("div");
        content.className = "rc-history-content";

        function addBox(label, value) {
            const section = document.createElement("section");
            const title = document.createElement("div");
            title.className = "rc-history-label";
            title.textContent = label;

            const pre = document.createElement("pre");
            pre.className = "rc-history-box";
            pre.textContent = value;

            section.append(title, pre);
            content.appendChild(section);
        }

        const commandText = getTaskCommand(task);
        addBox(
            "Command",
            commandText || "This history record does not include the original command."
        );
        addBox("Output", task.result || "No result has been reported yet.");

        dialog.append(header, content);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        function closePopup() {
            overlay.remove();
            document.removeEventListener("keydown", onKeyDown);
        }

        function onKeyDown(event) {
            if (event.key === "Escape") closePopup();
        }

        closeButton.addEventListener("click", closePopup);
        overlay.addEventListener("click", event => {
            if (event.target === overlay) closePopup();
        });
        document.addEventListener("keydown", onKeyDown);
        closeButton.focus();
    }

    function selectHistoryTask(task) {
        document.querySelectorAll("[data-rc-task-id]").forEach(row => {
            row.classList.toggle(
                "rc-row-selected",
                row.dataset.rcTaskId === task.id
            );
        });
        showTaskPopup(task);
    }

    function showTaskDetails(task) {
        selectedTask = task;
        const panel = $(".rc-detail-panel");
        if (!panel) return;
        const pill = panel.querySelector(".rc-neutral-pill");
        const title = panel.querySelector(".rc-detail-empty strong");
        const description = panel.querySelector(".rc-detail-empty p");
        const output = panel.querySelector(".rc-output-placeholder pre");

        if (pill) {
            pill.textContent = task.status || "Unknown";
            pill.dataset.status = normalizeStatus(task.status);
        }
        if (title) title.textContent = actionLabel(task.action);
        if (description) {
            description.textContent =
                `${task.device_name || "Unknown device"} · ${task.device_os || "Unknown OS"} · Created ${formatTime(task.created_at)}`;
        }
        const parseTaskData = value => {
            if (value && typeof value === "object") return value;
            if (typeof value === "string") {
                try {
                    const parsed = JSON.parse(value);
                    return parsed && typeof parsed === "object" ? parsed : {};
                } catch (_) {
                    return {};
                }
            }
            return {};
        };

        const taskPayload = parseTaskData(task.payload ?? task.payload_json);
        const taskExecution = parseTaskData(task.execution ?? task.execution_json);

        const commandText =
            task.action === "remote_command" &&
            typeof taskPayload.command === "string"
                ? taskPayload.command
                : task.action === "package_deployment" &&
                  typeof taskExecution.install_command === "string"
                    ? taskExecution.install_command
                    : "";

        if (output) {
            const resultText = task.result || "No result has been reported yet.";
            output.textContent = commandText
                ? "Command:\\n" + commandText + "\\n\\nOutput:\\n" + resultText
                : resultText;
        }

        document.querySelectorAll("[data-rc-task-id]").forEach(row => {
            row.classList.toggle("rc-row-selected", row.dataset.rcTaskId === task.id);
        });
    }

    function updateLiveOutput() {
        if (!liveOutput) return;

        if (latestTaskId) {
            const task = records.find(item => item.id === latestTaskId);
            const status = task ? (task.status || "Queued") : "Queued";

            if (liveOutputStatus) {
                liveOutputStatus.textContent = String(status).toUpperCase();
            }

            // Output displays only the result returned by CartmanClient.
            liveOutput.textContent = task?.result || "";
            return;
        }

        if (liveOutputStatus) liveOutputStatus.textContent = "DRAFT";

        // Do not echo the command into the output panel before execution.
        liveOutput.textContent = "";
    }

    function renderHistory() {
        const query = search.value.trim().toLocaleLowerCase();
        const selectedStatus = statusFilter.value.toLowerCase();
        const selectedOS = osFilter.value.toLowerCase();

        const filtered = records.filter(task => {
            const status = normalizeStatus(task.status);
            const os = osFamily(task.device_os).toLowerCase();
            const searchable = [
                actionLabel(task.action), task.device_name, task.device_os,
                task.id, task.status, task.result
            ].join(" ").toLocaleLowerCase();

            return searchable.includes(query) &&
                (!selectedStatus || status === selectedStatus) &&
                (!selectedOS || os === selectedOS);
        });

        rows.replaceChildren();
        for (const task of filtered) {
            const row = document.createElement("tr");
            row.dataset.rcTaskId = task.id;
            row.tabIndex = 0;

            addCell(row, actionLabel(task.action));
            addCell(row, task.device_name);
            addCell(row, task.device_os);
            addCell(row, formatTime(task.started_at || task.created_at));
            addCell(row, formatDuration(task));

            const statusCell = addCell(row, "");
            const badge = document.createElement("span");
            badge.className = "rc-live-status";
            badge.dataset.status = normalizeStatus(task.status);
            badge.textContent = task.status || "Unknown";
            statusCell.appendChild(badge);

            row.addEventListener("click", () => selectHistoryTask(task));
            row.addEventListener("keydown", event => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectHistoryTask(task);
                }
            });
            rows.appendChild(row);
        }

        count.textContent = `${filtered.length} records`;
        if (footerCount) footerCount.textContent = `${filtered.length} records`;
        empty.style.display = filtered.length ? "none" : "grid";

        const title = empty.querySelector("h3");
        const note = empty.querySelector("p");
        if (title) title.textContent = records.length ? "No matching executions" : "No command executions yet";
        if (note) note.textContent = records.length
            ? "Try changing the search term or filters."
            : "Choose an enrolled device and queue a supported task.";

        const completed = records.filter(item => normalizeStatus(item.status) === "completed").length;
        const pending = records.filter(item => ["pending", "running"].includes(normalizeStatus(item.status))).length;
        const failed = records.filter(item => normalizeStatus(item.status) === "failed").length;
        $("#rc-stat-total").textContent = records.length;
        $("#rc-stat-completed").textContent = completed;
        $("#rc-stat-pending").textContent = pending;
        $("#rc-stat-failed").textContent = failed;
        updateLiveOutput();
    }

    async function load() {
        if (loading || submitting) return;
        loading = true;
        if (refreshButton) refreshButton.disabled = true;

        try {
            const [deviceData, clientData, agentData, listener] = await Promise.all([
                api("/api/devices"),
                api("/api/device-connection-clients"),
                api("/api/endpoint-agents"),
                api("/api/device-connection-listener/status")
            ]);

            devices = Array.isArray(deviceData) ? deviceData :
                (Array.isArray(deviceData.items) ? deviceData.items : []);
            clients = Array.isArray(clientData) ? clientData : [];
            agents = Array.isArray(agentData.items) ? agentData.items : [];

            const groups = await Promise.all(devices.map(async device => {
                try {
                    const values = await api("/api/devices/" + encodeURIComponent(device.id) + "/tasks");
                    return (Array.isArray(values) ? values : []).map(task => ({
                        ...task, device_name: device.name, device_os: device.os
                    }));
                } catch (_) {
                    return [];
                }
            }));

            records = groups.flat()
                .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
                .slice(0, 500);
            renderHistory();

            const ready = clients.filter(client => client.connected === true &&
                client.approval_status === "Approved" &&
                client.task_execution_enabled === true).length;

            const title = $("[data-rc-service-title]");
            const description = $("[data-rc-service-description]");
            const pill = $("[data-rc-service-pill]");
            const noticeIcon = $("[data-rc-service-icon]");
            const preview = $("[data-rc-preview-status]");

            if (title) title.textContent = ready
                ? "Remote execution is ready"
                : listener.running ? "Waiting for an approved agent"
                : "Agent listener is stopped";

            if (description) description.textContent = ready
                ? `${ready} approved connected agent${ready === 1 ? " is" : "s are"} ready to receive tasks.`
                : listener.running
                    ? "The listener is active. Waiting for a connected agent with task execution enabled."
                    : `Start the local listener on port ${listener.port} to accept CartmanClient connections.`;

            const connectionState = ready ? "ready" : listener.running ? "waiting" : "stopped";

            if (pill) {
                pill.textContent = ready ? "READY" : listener.running ? "WAITING FOR AGENT" : "STOPPED";
                pill.dataset.status = connectionState;
            }

            if (noticeIcon) {
                noticeIcon.textContent = ready ? "✓" : listener.running ? "…" : "×";
                noticeIcon.dataset.status = connectionState;
            }
            if (preview) preview.textContent = "Live task history";

            populateTargets(selectedSavedTemplate()?.target_os || "Any");
            updateTargetNotice();
            updateComposer();
        } catch (error) {
            const title = $("[data-rc-service-title]");
            const description = $("[data-rc-service-description]");
            if (title) title.textContent = "Remote task API unavailable";
            if (description) description.textContent = error.message;
            rows.replaceChildren();
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 6;
            cell.textContent = "Could not load devices or task history: " + error.message;
            row.appendChild(cell);
            rows.appendChild(row);
        } finally {
            loading = false;
            if (refreshButton) refreshButton.disabled = false;
        }
    }

    function openTemplateModal() {
        templateForm.reset();
        templateOS.value = "Any";
        templateError.textContent = "";
        templateModal.hidden = false;
        templateName.focus();
    }

    function closeTemplateModal() {
        templateModal.hidden = true;
        templateError.textContent = "";
    }

    function localDateTimeInputValue(date) {
        const pad = value => String(value).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function openScheduleModal() {
        scheduleError.textContent = "";
        scheduleForm.reset();
        const now = new Date();
        scheduleTime.min = localDateTimeInputValue(now);
        scheduleTime.disabled = true;
        scheduleModal.hidden = false;
    }

    function closeScheduleModal() {
        scheduleModal.hidden = true;
        scheduleError.textContent = "";
    }

    document.querySelectorAll("[data-rc-schedule-cancel]").forEach(button => {
        button.addEventListener("click", closeScheduleModal);
    });
    scheduleModal?.addEventListener("click", event => {
        if (event.target === scheduleModal) closeScheduleModal();
    });
    document.querySelectorAll("[data-rc-schedule-mode]").forEach(radio => {
        radio.addEventListener("change", () => {
            const scheduled = document.querySelector('[data-rc-schedule-mode]:checked')?.value === "scheduled";
            scheduleTime.disabled = !scheduled;
            scheduleTime.required = scheduled;
            if (scheduled && !scheduleTime.value) {
                const later = new Date(Date.now() + 5 * 60000);
                scheduleTime.value = localDateTimeInputValue(later);
            }
        });
    });

    createTemplateButton?.addEventListener("click", openTemplateModal);
    document.querySelectorAll("[data-rc-template-cancel]").forEach(button => {
        button.addEventListener("click", closeTemplateModal);
    });
    templateModal.addEventListener("click", event => {
        if (event.target === templateModal) closeTemplateModal();
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !templateModal.hidden) closeTemplateModal();
    });

    templateForm.addEventListener("submit", event => {
        event.preventDefault();
        templateError.textContent = "";
        const name = templateName.value.trim();
        const commandText = templateCommand.value.trim();
        if (!name || !commandText) {
            templateError.textContent = "Template name and command are required.";
            return;
        }
        if (commandText.length > 6000) {
            templateError.textContent = "Command must be 6,000 characters or fewer.";
            return;
        }

        const item = {
            id: (window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : String(Date.now()) + "-" + Math.random().toString(16).slice(2)),
            name,
            target_os: templateOS.value,
            description: templateDescription.value.trim(),
            command: commandText,
            created_at: new Date().toISOString()
        };

        templates.push(item);
        try {
            localStorage.setItem(storageKey, JSON.stringify(templates));
        } catch (_) {
            templates = templates.filter(template => template.id !== item.id);
            templateError.textContent = "Could not save the template in browser storage.";
            return;
        }

        renderTemplateOptions();
        actionSelect.value = "custom:" + item.id;
        closeTemplateModal();
        command.value = item.command;
        updateComposer();
        feedback.textContent = `Template "${item.name}" saved in this browser. Review the command before queueing.`;
    });

    actionSelect.addEventListener("change", () => {
        feedback.textContent = "";
        const saved = selectedSavedTemplate();
        if (saved) command.value = saved.command;
        updateComposer();
    });

    command.addEventListener("input", () => {
        if (!latestTaskId) updateLiveOutput();
        updateComposer();
    });

    targetSelect.addEventListener("change", () => {
        updateTargetNotice();
        updateComposer();
    });

    search.addEventListener("input", renderHistory);
    statusFilter.addEventListener("change", renderHistory);
    osFilter.addEventListener("change", renderHistory);
    clearButton?.addEventListener("click", () => {
        actionSelect.value = "";
        command.value = "";
        if (feedback) feedback.textContent = "";
        updateComposer();
    });
    refreshButton?.addEventListener("click", load);

    copyButton?.addEventListener("click", async () => {
        if (!command.value.trim()) return;
        try {
            await navigator.clipboard.writeText(command.value);
            feedback.textContent = "Command copied. It has not been executed.";
        } catch (_) {
            command.focus();
            command.select();
            feedback.textContent = "Clipboard unavailable. Command selected; copy it manually.";
        }
    });

    runButton.addEventListener("click", () => {
        if (submitting) return;

        const device = devices.find(item => item.id === targetSelect.value);
        if (!device) {
            feedback.textContent = "Choose a target device.";
            return;
        }
        if (!targetIsRegistered(device.id)) {
            feedback.textContent = "This device has no registered CartmanClient identity.";
            return;
        }
        if (!command.value.trim()) {
            feedback.textContent = "Enter a command before queueing.";
            command.focus();
            return;
        }
        const live = liveClient(device.id);
        if (live && !targetIsExecutionReady(device.id)) {
            feedback.textContent = "Task execution is disabled on this connected agent.";
            return;
        }
        openScheduleModal();
    });

    scheduleForm?.addEventListener("submit", async event => {
        event.preventDefault();
        scheduleError.textContent = "";

        const device = devices.find(item => item.id === targetSelect.value);
        const commandText = command.value.trim();

        if (!device || !targetIsRegistered(device.id) || !commandText) {
            scheduleError.textContent = "Choose an enrolled device and enter a command.";
            return;
        }

        const mode = document.querySelector('[data-rc-schedule-mode]:checked')?.value || "now";
        let scheduledAt = null;

        if (mode === "scheduled") {
            if (!scheduleTime.value) {
                scheduleError.textContent = "Choose a date and time.";
                return;
            }
            const parsed = new Date(scheduleTime.value);
            if (Number.isNaN(parsed.getTime()) || parsed.getTime() <= Date.now()) {
                scheduleError.textContent = "Scheduled time must be in the future.";
                return;
            }
            scheduledAt = parsed.toISOString();
        }

        const saved = selectedSavedTemplate();
        const deviceOS = osFamily(device.os);
        const targetOS = saved ? saved.target_os :
            (["Windows", "macOS", "Linux"].includes(deviceOS) ? deviceOS : "Any");

        submitting = true;
        scheduleSubmit.disabled = true;
        scheduleSubmit.textContent = "Queueing...";
        runButton.disabled = true;

        let reloadAfterQueue = false;
        try {
            const payload = {
                command: commandText,
                target_os: targetOS,
                description: saved?.description || "Custom command",
                confirmed: true
            };
            if (scheduledAt) payload.scheduled_at = scheduledAt;

            const result = await api(
                "/api/devices/" + encodeURIComponent(device.id) + "/tasks",
                {
                    method: "POST",
                    body: JSON.stringify({action: "remote_command", payload})
                }
            );

            latestTaskId = result.id;
            latestCommandText = commandText;
            latestTargetName = device.name;
            latestScheduleText = scheduledAt ? new Date(scheduledAt).toLocaleString() : "";
            closeScheduleModal();
            feedback.textContent = result.message ||
                `Task queued: ${result.id || "created"} · ${result.status || "Queued"}.`;
            updateLiveOutput();
            reloadAfterQueue = true;
        } catch (error) {
            scheduleError.textContent = error.message;
            feedback.textContent = "Task was not queued: " + error.message;
        } finally {
            submitting = false;
            scheduleSubmit.disabled = false;
            scheduleSubmit.textContent = "Confirm & Queue";
            updateComposer();
        }

        if (reloadAfterQueue) load();
    });

    loadTemplates();
    renderTemplateOptions();
    updateComposer();
    load();
    window.setInterval(load, 4000);
});
