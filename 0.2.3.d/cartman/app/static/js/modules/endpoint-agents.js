/* CARTMAN_ENDPOINT_AGENTS_API_V1 */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const $ = selector => document.querySelector(selector);
    const search = $("[data-ea-search]");
    const statusFilter = $("[data-ea-status]");
    const rows = $("[data-ea-rows]");
    const count = $("[data-ea-count]");
    const empty = $("[data-ea-empty]");
    const pendingRows = $("[data-ea-pending-rows]");
    const pendingEmpty = $("[data-ea-pending-empty]");
    const pendingCount = $("[data-ea-pending-count]");
    const banRows = $("[data-ea-ban-rows]");
    const banCount = $("[data-ea-ban-count]");
    const banEmpty = $("[data-ea-ban-empty]");
    const refreshButton = $("[data-ea-refresh]");
    const startButton = $("[data-ea-start-listener]");

    if (!search || !statusFilter || !rows || !count) return;

    let agents = [];
    let pending = [];
    let bans = [];
    let busy = false;

    async function api(url, options = {}) {
        const response = await fetch(url, {
            cache: "no-store",
            ...options,
            headers: {
                "Accept": "application/json",
                ...(options.body ? {"Content-Type": "application/json"} : {}),
                ...(options.headers || {})
            }
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : `Request failed (HTTP ${response.status})`
            );
        }
        return data;
    }

    function setText(selector, value) {
        const element = $(selector);
        if (element) element.textContent = String(value ?? "—");
    }

    function addCell(row, value) {
        const td = document.createElement("td");
        td.textContent = value == null || value === "" ? "—" : String(value);
        row.appendChild(td);
        return td;
    }

    function formatTime(value) {
        if (!value) return "Never";
        const date = new Date(value);
        return Number.isNaN(date.getTime())
            ? String(value)
            : date.toLocaleString();
    }

    function statusBadge(value) {
        const badge = document.createElement("span");
        badge.className = "ea-status-badge";
        badge.dataset.status = String(value || "Unknown").toLowerCase();
        badge.textContent = value || "Unknown";
        return badge;
    }

    function allRows() {
        const waiting = pending.map(item => ({
            agent_id: item.id,
            device_name: item.device_name,
            device_os: item.os,
            status: "Pending",
            last_seen: null,
            client_ip: item.client_ip,
            username: item.username,
            agent_version: "Pending approval",
            collectors: "Awaiting approval",
            request_id: item.id,
            is_pending: true
        }));
        return [...agents, ...waiting];
    }

    function renderAgents() {
        const query = search.value.trim().toLocaleLowerCase();
        const selectedStatus = statusFilter.value;

        const filtered = allRows().filter(item => {
            const searchable = [
                item.device_name,
                item.device_os,
                item.agent_id,
                item.client_ip,
                item.username,
                item.status
            ].join(" ").toLocaleLowerCase();

            return searchable.includes(query)
                && (
                    selectedStatus === "all"
                    || item.status.toLowerCase() === selectedStatus
                );
        });

        count.textContent = `${filtered.length} record(s)`;
        rows.replaceChildren();

        for (const item of filtered) {
            const row = document.createElement("tr");

            const endpointCell = document.createElement("td");
            const endpointName = document.createElement("strong");
            endpointName.textContent = item.device_name || "Unknown device";
            const endpointId = document.createElement("small");
            endpointId.className = "ea-agent-id";
            endpointId.textContent = item.agent_id
                ? String(item.agent_id).slice(0, 18)
                : "ID unavailable";
            endpointCell.append(endpointName, endpointId);
            row.appendChild(endpointCell);

            addCell(row, item.device_os);
            addCell(row, item.agent_version || "Unknown");
            addCell(row, formatTime(item.last_seen));
            addCell(row, item.collectors || "Not reported");

            const stateCell = document.createElement("td");
            stateCell.appendChild(statusBadge(item.status));
            row.appendChild(stateCell);

            const actionCell = document.createElement("td");
            if (!item.is_pending && item.agent_id) {
                const revokeButton = document.createElement("button");
                revokeButton.type = "button";
                revokeButton.className = "ea-decision-button ea-reject";
                revokeButton.textContent = "Revoke";
                revokeButton.title =
                    "Revoke this agent identity and close active connections";
                revokeButton.addEventListener("click", () => {
                    const confirmed = window.confirm(
                        `Revoke the CartmanClient identity for "${item.device_name}"? `
                        + "The agent will be disconnected and cannot reconnect "
                        + "with this identity."
                    );
                    if (confirmed) revokeAgent(item, revokeButton);
                });
                actionCell.appendChild(revokeButton);

                const banButton = document.createElement("button");
                banButton.type = "button";
                banButton.className = "ea-decision-button ea-ban";
                banButton.textContent = "Ban HWID";
                banButton.title =
                    "Create a hardware-identity ban and disconnect matching sessions";
                banButton.addEventListener("click", () => banAgent(item, banButton));
                actionCell.appendChild(banButton);
            } else {
                actionCell.textContent = "—";
            }
            row.appendChild(actionCell);
            rows.appendChild(row);
        }

        empty.hidden = filtered.length !== 0;
        if (empty.hidden) empty.style.display = "none";
        else empty.style.display = "";

        if (!filtered.length) {
            const message = empty.querySelector("p");
            if (message) {
                message.textContent = allRows().length
                    ? "No agents match the selected search or status filter."
                    : "No registered agents yet. Start the local listener and connect a CartmanClient.";
            }
        }
    }

    async function decide(request, decision, button) {
        if (busy) return;
        busy = true;
        button.disabled = true;

        try {
            await api(
                "/api/device-connection-requests/"
                    + encodeURIComponent(request.id) + "/decision",
                {
                    method: "POST",
                    body: JSON.stringify({decision})
                }
            );
            await load();
        } catch (error) {
            window.alert(`${decision} failed: ${error.message}`);
        } finally {
            busy = false;
            button.disabled = false;
        }
    }

    async function revokeAgent(item, button) {
        if (busy) return;
        busy = true;
        button.disabled = true;

        try {
            await api(
                "/api/endpoint-agents/"
                    + encodeURIComponent(item.agent_id) + "/revoke",
                { method: "POST" }
            );
            await load();
            window.alert(
                "Agent identity revoked. Any active connection was asked to disconnect."
            );
        } catch (error) {
            window.alert(`Agent revocation failed: ${error.message}`);
        } finally {
            busy = false;
            button.disabled = false;
        }
    }


    async function banAgent(item, button) {
        if (busy) return;

        const reason = window.prompt(
            `Reason for banning "${item.device_name}"?`,
            "Policy violation"
        );
        if (reason === null) return;

        if (!reason.trim()) {
            window.alert("Enter a reason for the ban.");
            return;
        }

        const identity = item.hardware_identity || {};
        const hasHardwareFingerprint = [
            "system_uuid_hash",
            "board_serial_hash",
            "product_serial_hash",
            "fingerprint"
        ].some(key => /^[0-9a-f]{64}$/i.test(identity[key] || ""));

        if (!hasHardwareFingerprint) {
            const confirmed = window.confirm(
                "This agent has not reported a usable HWID yet. "
                + "Cartman can block its registered agent identity, but it "
                + "cannot reliably match a replacement identity for this device. "
                + "Continue with an identity-only ban?"
            );
            if (!confirmed) return;
        }

        if (!window.confirm(
            `Create an active ban for "${item.device_name}"? `
            + "Matching connections will be disconnected."
        )) return;

        busy = true;
        button.disabled = true;
        let succeeded = false;
        let result = null;

        try {
            result = await api("/api/hwid-bans", {
                method: "POST",
                body: JSON.stringify({
                    device_name: item.device_name || "Unknown endpoint",
                    username: item.username || "",
                    os: item.device_os || "Unknown",
                    client_ip: item.client_ip || "",
                    manufacturer: item.manufacturer || "",
                    model: item.model || "",
                    device_type: item.device_type || "",
                    client_instance: item.agent_id || "",
                    device_id: item.device_id || "",
                    hardware_identity: identity,
                    reason: reason.trim()
                })
            });
            succeeded = true;
        } catch (error) {
            window.alert("HWID ban failed: " + error.message);
        } finally {
            busy = false;
            button.disabled = false;
        }

        if (succeeded) {
            await load();
            window.alert(
                `Ban created for ${item.device_name}. `
                + `Active connections closed: ${result.active_connections_closed ?? 0}.`
            );
        }
    }

    async function revokeHwidBan(item, button) {
        if (busy) return;

        busy = true;
        button.disabled = true;
        let succeeded = false;

        try {
            await api(
                "/api/hwid-bans/" + encodeURIComponent(item.id) + "/revoke",
                {method: "POST"}
            );
            succeeded = true;
        } catch (error) {
            window.alert("Could not lift ban: " + error.message);
        } finally {
            busy = false;
            button.disabled = false;
        }

        if (succeeded) await load();
    }

    function renderBans() {
        if (!banRows) return;

        banRows.replaceChildren();

        for (const item of bans) {
            const row = document.createElement("tr");
            addCell(row, item.device_name);
            addCell(row, item.username);
            addCell(row, item.os);
            addCell(row, item.client_ip);
            addCell(row, item.model);

            const identity = item.hardware_identity || {};
            const hasHardwareFingerprint = [
                "system_uuid_hash",
                "board_serial_hash",
                "product_serial_hash",
                "fingerprint"
            ].some(key => /^[0-9a-f]{64}$/i.test(identity[key] || ""));

            addCell(row, hasHardwareFingerprint ? "HWID hash" : "Agent identity");
            addCell(row, item.reason);
            addCell(row, item.actor);
            addCell(row, formatTime(item.created_at));

            const stateCell = document.createElement("td");
            stateCell.appendChild(statusBadge(item.status));
            row.appendChild(stateCell);

            const actionCell = addCell(row, "");
            if (item.status === "Active") {
                const liftButton = document.createElement("button");
                liftButton.type = "button";
                liftButton.className = "ea-decision-button ea-approve";
                liftButton.textContent = "Lift ban";
                liftButton.addEventListener("click", () => {
                    if (window.confirm(
                        `Lift the ban for "${item.device_name}"?`
                    )) {
                        revokeHwidBan(item, liftButton);
                    }
                });
                actionCell.appendChild(liftButton);
            } else {
                actionCell.textContent = "—";
            }

            banRows.appendChild(row);
        }

        if (banCount) {
            const activeCount = bans.filter(item => item.status === "Active").length;
            banCount.textContent = `${activeCount} active / ${bans.length} record(s)`;
        }

        if (banEmpty) {
            banEmpty.hidden = bans.length !== 0;
            banEmpty.style.display = banEmpty.hidden ? "none" : "";
        }
    }

    async function loadBans() {
        if (!banRows) return;

        try {
            const data = await api("/api/hwid-bans");
            bans = Array.isArray(data.items) ? data.items : [];
            renderBans();
        } catch (error) {
            bans = [];
            banRows.replaceChildren();

            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 11;
            cell.className = "ea-load-error";
            cell.textContent = "Could not load HWID bans: " + error.message;
            row.appendChild(cell);
            banRows.appendChild(row);

            if (banCount) banCount.textContent = "Unavailable";
            if (banEmpty) banEmpty.hidden = true;
        }
    }

    function renderPending() {
        if (!pendingRows) return;
        pendingRows.replaceChildren();

        for (const item of pending) {
            const row = document.createElement("tr");
            addCell(row, item.device_name);
            addCell(row, item.os);
            addCell(row, item.client_ip);
            addCell(row, item.username);
            addCell(row, formatTime(item.created_at));

            const actionCell = addCell(row, "");
            const actions = document.createElement("div");
            actions.className = "ea-row-actions";

            for (const [label, decision, className] of [
                ["Approve", "Approved", "ea-approve"],
                ["Reject", "Rejected", "ea-reject"]
            ]) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `ea-decision-button ${className}`;
                button.textContent = label;
                button.addEventListener("click", () => {
                    const promptText = decision === "Approved"
                        ? `Approve enrollment for "${item.device_name}"?`
                        : `Reject enrollment for "${item.device_name}"?`;
                    if (window.confirm(promptText)) {
                        decide(item, decision, button);
                    }
                });
                actions.appendChild(button);
            }

            actionCell.appendChild(actions);
            pendingRows.appendChild(row);
        }

        if (pendingEmpty) pendingEmpty.hidden = pending.length !== 0;
        if (pendingCount) {
            pendingCount.textContent = `${pending.length} pending`;
        }
    }

    async function loadListenerStatus() {
        try {
            const data = await api("/api/device-connection-listener/status");
            const title = $("[data-ea-service-title]");
            const description = $("[data-ea-service-description]");
            const tag = $("[data-ea-service-tag]");
            const indicator = $("[data-ea-service-indicator]");

            if (title) {
                title.textContent = data.running
                    ? "Local agent listener running"
                    : "Local agent listener stopped";
            }
            if (description) {
                description.textContent = data.running
                    ? `Listening on ${data.listen_address}:${data.port}. Public listening is disabled.`
                    : `No agents can connect until the local listener starts. Port ${data.port}; public listening is disabled.`;
            }
            if (tag) {
                tag.textContent = data.running ? "RUNNING" : "STOPPED";
                tag.dataset.state = data.running ? "online" : "offline";
            }
            if (indicator) {
                indicator.dataset.state = data.running ? "online" : "offline";
            }
            if (startButton) {
                startButton.hidden = Boolean(data.running);
                startButton.disabled = false;
                startButton.textContent = "Start local listener";
            }
        } catch (error) {
            const title = $("[data-ea-service-title]");
            const description = $("[data-ea-service-description]");
            if (title) title.textContent = "Listener status unavailable";
            if (description) description.textContent = error.message;
            if (startButton) startButton.hidden = false;
        }
    }

    async function load() {
        if (busy) return;
        if (refreshButton) refreshButton.disabled = true;

        try {
            const [agentData, pendingData] = await Promise.all([
                api("/api/endpoint-agents"),
                api("/api/device-connection-requests")
            ]);

            agents = Array.isArray(agentData.items) ? agentData.items : [];
            pending = Array.isArray(pendingData) ? pendingData : [];

            setText("[data-ea-total]", agentData.stats?.total ?? agents.length);
            setText("[data-ea-online]", agentData.stats?.online ?? 0);
            setText("[data-ea-offline]", agentData.stats?.offline ?? 0);
            setText("[data-ea-pending]", pending.length);

            renderAgents();
            renderPending();
        } catch (error) {
            rows.replaceChildren();
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 6;
            cell.className = "ea-load-error";
            cell.textContent = "Could not load agent data: " + error.message;
            row.appendChild(cell);
            rows.appendChild(row);
            count.textContent = "Unavailable";
        }

        await loadListenerStatus();
        await loadBans();
        if (refreshButton) refreshButton.disabled = false;
    }

    if (startButton) {
        startButton.addEventListener("click", async () => {
            startButton.disabled = true;
            try {
                await api("/api/device-connection-listener/start", {
                    method: "POST",
                    body: JSON.stringify({address_mode: "local"})
                });
                await load();
            } catch (error) {
                window.alert("Listener could not start: " + error.message);
                startButton.disabled = false;
            }
        });
    }

    search.disabled = false;
    statusFilter.disabled = false;
    search.addEventListener("input", renderAgents);
    statusFilter.addEventListener("change", renderAgents);
    if (refreshButton) refreshButton.addEventListener("click", load);

    load();
    window.setInterval(load, 15000);
});
