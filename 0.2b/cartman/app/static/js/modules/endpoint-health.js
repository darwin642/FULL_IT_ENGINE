/* Cartman Endpoint Health: live inventory and agent readiness, no fake metrics. */
(() => {
    "use strict";

    const $ = selector => document.querySelector(selector);
    const rows = $("[data-eh-rows]");
    if (!rows || window.__cartmanEndpointHealthLiveV1) return;
    window.__cartmanEndpointHealthLiveV1 = true;

    const state = {
        devices: [],
        clients: [],
        agents: [],
        endpoints: [],
        errors: [],
        loading: false
    };

    const normalize = value => String(value ?? "").trim().toLowerCase();

    function collection(data) {
        if (Array.isArray(data)) return data;
        if (!data || typeof data !== "object") return [];
        for (const key of ["items", "devices", "clients", "agents", "results"]) {
            if (Array.isArray(data[key])) return data[key];
        }
        return [];
    }

    async function fetchData(url) {
        const response = await fetch(url, {
            cache: "no-store",
            headers: { "Accept": "application/json" }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || `${url} returned HTTP ${response.status}`);
        }
        return data;
    }

    async function safeList(url, label) {
        try {
            return {items: collection(await fetchData(url)), error: null};
        } catch (error) {
            return {items: [], error: `${label}: ${error.message || error}`};
        }
    }

    function deviceId(device) {
        return String(device.id ?? device.device_id ?? device.deviceId ?? "");
    }

    function deviceName(device) {
        return String(
            device.name ?? device.hostname ?? device.device_name ??
            device.deviceName ?? "Unnamed endpoint"
        );
    }

    function deviceOS(device) {
        return String(device.os ?? device.operating_system ?? device.platform ?? "Unknown");
    }

    function deviceIP(device) {
        return String(
            device.ip ?? device.private_ip ?? device.privateIp ??
            device.ip_address ?? device.ipAddress ?? ""
        );
    }

    function matchesDevice(record, device) {
        const deviceIds = [
            device.id, device.device_id, device.deviceId
        ].filter(value => value !== undefined && value !== null && String(value) !== "")
            .map(String);

        const recordIds = [
            record.device_id, record.deviceId, record.endpoint_id, record.endpointId
        ].filter(value => value !== undefined && value !== null && String(value) !== "")
            .map(String);

        if (deviceIds.length && recordIds.length) {
            return deviceIds.some(id => recordIds.includes(id));
        }

        const name = normalize(deviceName(device));
        const recordNames = [
            record.device_name, record.deviceName, record.hostname,
            record.device_hostname, record.client_name, record.name
        ].map(normalize).filter(Boolean);

        return Boolean(name && recordNames.includes(name));
    }

    function connected(record) {
        if (
            record.connected === true ||
            record.is_connected === true ||
            record.isConnected === true ||
            record.online === true
        ) return true;

        return ["connected", "online", "ready"].includes(
            normalize(record.connection_status ?? record.connectionStatus ??
                record.status ?? record.state)
        );
    }

    function approvalOf(records) {
        for (const record of records) {
            const value = record.approval_status ?? record.approvalStatus ??
                record.approval_state ?? record.approval;
            if (value !== undefined && value !== null && String(value).trim()) {
                return String(value);
            }
        }
        return records.length ? "Not reported" : "No agent record";
    }

    function executionEnabled(records) {
        const values = records
            .map(record => record.task_execution_enabled ??
                record.taskExecutionEnabled ?? record.execution_enabled)
            .filter(value => typeof value === "boolean");

        if (values.includes(true)) return true;
        if (values.includes(false)) return false;
        return null;
    }

    function latestSeen(records, device) {
        const values = records.map(record =>
            record.last_seen ?? record.lastSeen ?? record.credential_last_seen ??
            record.heartbeat_at ?? record.heartbeatAt
        ).filter(Boolean);

        const deviceSeen = device.last_seen ?? device.lastSeen;
        if (deviceSeen) values.push(deviceSeen);
        values.sort((a, b) => (Date.parse(b) || 0) - (Date.parse(a) || 0));
        return values[0] || "";
    }

    function buildEndpoint(device) {
        const matchedClients = state.clients.filter(item => matchesDevice(item, device));
        const matchedAgents = state.agents.filter(item => matchesDevice(item, device));
        const related = [...matchedClients, ...matchedAgents];
        const isConnected = related.some(connected);
        const approval = approvalOf(related);
        const execution = executionEnabled(related);
        const approvalState = normalize(approval);

        let connection = "No agent";
        if (related.length) connection = isConnected ? "Connected" : "Offline";

        const approvalProblem =
            !/approved/.test(approvalState) ||
            /pending|reject|denied|revoked|blocked/.test(approvalState);

        const attention =
            connection !== "Connected" ||
            approvalProblem ||
            execution === false;

        return {
            id: deviceId(device),
            name: deviceName(device),
            os: deviceOS(device),
            ip: deviceIP(device),
            connection,
            approval,
            execution,
            attention,
            lastSeen: latestSeen(related, device)
        };
    }

    function formatTime(value) {
        if (!value) return "Never reported";
        const date = new Date(value);
        return Number.isNaN(date.getTime())
            ? String(value)
            : date.toLocaleString([], {
                year: "numeric", month: "short", day: "numeric",
                hour: "2-digit", minute: "2-digit"
            });
    }

    function makeCell(text, className = "") {
        const cell = document.createElement("td");
        if (className) cell.className = className;
        cell.textContent = text || "—";
        return cell;
    }

    function badge(text, stateName) {
        const element = document.createElement("span");
        element.className = `eh-health-badge ${stateName}`;
        element.textContent = text;
        return element;
    }

    function connectionClass(endpoint) {
        return endpoint.connection === "Connected" ? "good" :
            endpoint.connection === "Offline" ? "warning" : "critical";
    }

    function approvalClass(endpoint) {
        if (/reject|denied|revoked|blocked/i.test(endpoint.approval)) return "critical";
        if (/pending|awaiting|requested|not reported|no agent/i.test(endpoint.approval)) return "warning";
        if (/approved/i.test(endpoint.approval)) return "good";
        return "unknown";
    }

    function monitoringHref(endpoint) {
        const params = new URLSearchParams();
        if (endpoint.id) params.set("endpoint_id", endpoint.id);
        params.set("endpoint_name", endpoint.name);
        return `/pages/monitoring/?${params.toString()}`;
    }

    function applyFilter() {
        const query = normalize($("[data-eh-search]")?.value);
        const selected = normalize($("[data-eh-status]")?.value);
        const platform = normalize($("[data-eh-platform]")?.value);

        const filtered = state.endpoints.filter(endpoint => {
            const searchable = normalize([
                endpoint.name, endpoint.os, endpoint.ip, endpoint.id,
                endpoint.connection, endpoint.approval
            ].join(" "));

            const matchesQuery = searchable.includes(query);
            let matchesStatus = true;

            if (selected === "connected") {
                matchesStatus = endpoint.connection === "Connected";
            } else if (selected === "offline") {
                matchesStatus = endpoint.connection === "Offline";
            } else if (selected === "missing") {
                matchesStatus = endpoint.connection === "No agent";
            } else if (selected === "attention") {
                matchesStatus = endpoint.attention;
            }

            const os = normalize(endpoint.os);
            const matchesPlatform = !platform ||
                (platform === "windows" && os.includes("windows")) ||
                (platform === "linux" && os.includes("linux")) ||
                (platform === "macos" && (
                    os.includes("mac") || os.includes("darwin") || os.includes("apple")
                ));

            return matchesQuery && matchesStatus && matchesPlatform;
        });

        rows.replaceChildren();

        const empty = $("[data-eh-empty]");
        if (!filtered.length) {
            if (empty) {
                empty.hidden = false;
                const heading = empty.querySelector("h3");
                const note = empty.querySelector("p");

                if (state.errors.length) {
                    if (heading) heading.textContent = "Endpoint data is unavailable";
                    if (note) note.textContent = state.errors.join(" · ");
                } else if (state.endpoints.length) {
                    if (heading) heading.textContent = "No matching endpoints";
                    if (note) note.textContent = "Try changing the search term or filters.";
                } else {
                    if (heading) heading.textContent = "No device records yet";
                    if (note) note.textContent = "Add or import devices in Cartman inventory to see them here.";
                }
            }
        } else if (empty) {
            empty.hidden = true;
        }

        for (const endpoint of filtered) {
            const row = document.createElement("tr");

            const nameCell = document.createElement("td");
            const name = document.createElement("strong");
            name.className = "eh-endpoint-name";
            name.textContent = endpoint.name;

            const sub = document.createElement("small");
            sub.className = "eh-endpoint-sub";
            sub.textContent = endpoint.ip || endpoint.id || "Address not recorded";

            nameCell.append(name, sub);
            row.appendChild(nameCell);

            row.appendChild(makeCell(endpoint.os));

            const connectionCell = document.createElement("td");
            connectionCell.appendChild(badge(
                endpoint.connection,
                connectionClass(endpoint)
            ));
            row.appendChild(connectionCell);

            const readinessCell = document.createElement("td");
            const readinessText = endpoint.execution === false
                ? `${endpoint.approval} · Execution disabled`
                : endpoint.approval;
            const readinessClass = endpoint.execution === false
                ? "warning" : approvalClass(endpoint);
            readinessCell.appendChild(badge(readinessText, readinessClass));
            row.appendChild(readinessCell);

            row.appendChild(makeCell(formatTime(endpoint.lastSeen), "eh-last-seen"));

            const actionCell = document.createElement("td");
            const link = document.createElement("a");
            link.className = "eh-table-action";
            link.href = monitoringHref(endpoint);
            link.textContent = "Open Monitoring ↗";
            link.title = "Pass this endpoint name to Monitoring";
            actionCell.appendChild(link);
            row.appendChild(actionCell);

            rows.appendChild(row);
        }

        const label = `${filtered.length} of ${state.endpoints.length} endpoints`;
        const count = $("[data-eh-count]");
        const footerCount = $("[data-eh-footer-count]");
        if (count) count.textContent = label;
        if (footerCount) footerCount.textContent = label;
    }

    function renderSummary() {
        const total = state.endpoints.length;
        const online = state.endpoints.filter(e => e.connection === "Connected").length;
        const offline = state.endpoints.filter(e => e.connection === "Offline").length;
        const attention = state.endpoints.filter(e => e.attention).length;

        $("[data-eh-total]").textContent = total;
        $("[data-eh-connected]").textContent = online;
        $("[data-eh-offline]").textContent = offline;
        $("[data-eh-attention]").textContent = attention;

        const banner = $(".eh-banner");
        const title = $("[data-eh-banner-title]");
        const description = $("[data-eh-banner-description]");
        const icon = $("[data-eh-banner-icon]");
        const source = $("[data-eh-source-status]");

        let stateName = "neutral";
        let heading = "No endpoints in inventory";
        let detail = "Add devices to Cartman inventory and enroll agents to track connection readiness.";
        let sourceText = "No agents";
        let iconText = "i";

        if (state.errors.length) {
            stateName = "warning";
            heading = "Some endpoint data could not be loaded";
            detail = state.errors.join(" · ");
            sourceText = "Partial data";
            iconText = "!";
        } else if (total && attention === 0) {
            stateName = "healthy";
            heading = "All listed endpoints are ready";
            detail = `${online} connected endpoint(s); no connection or execution-readiness issues detected.`;
            sourceText = `${online} connected`;
            iconText = "✓";
        } else if (total) {
            stateName = "warning";
            heading = `${attention} endpoint(s) need attention`;
            detail = `${online} connected · ${offline} offline · ${state.endpoints.filter(e => e.connection === "No agent").length} without an agent record.`;
            sourceText = `${online} connected`;
            iconText = "!";
        }

        if (banner) banner.dataset.state = stateName;
        if (title) title.textContent = heading;
        if (description) description.textContent = detail;
        if (icon) icon.textContent = iconText;

        if (source) {
            const dot = source.querySelector("i");
            source.replaceChildren();
            if (dot) source.appendChild(dot);
            source.appendChild(document.createTextNode(sourceText));
            source.dataset.state = stateName;
        }

        const note = $("[data-eh-table-note]");
        if (note) {
            note.textContent = state.errors.length
                ? "Partial API data. Review the message above."
                : "Connection and approval state from Cartman APIs; resource metrics are intentionally left to Monitoring.";
        }

        const checkCount = $("[data-eh-check-count]");
        if (checkCount) checkCount.textContent = `${online}/${total} connected`;

        const checkConnection = $("[data-eh-check-connection]");
        if (checkConnection) checkConnection.textContent = `${online} connected`;

        const checkApproval = $("[data-eh-check-approval]");
        if (checkApproval) {
            const approved = state.endpoints.filter(e => /approved/i.test(e.approval)).length;
            checkApproval.textContent = `${approved} approved`;
        }

        const checkExecution = $("[data-eh-check-execution]");
        if (checkExecution) {
            const enabled = state.endpoints.filter(e => e.execution === true).length;
            checkExecution.textContent = `${enabled} enabled`;
        }
    }

    async function load() {
        if (state.loading) return;
        state.loading = true;

        const refresh = $("[data-eh-refresh]");
        if (refresh) {
            refresh.disabled = true;
            refresh.textContent = "Refreshing…";
        }

        try {
            const [devicesResult, clientsResult, agentsResult] = await Promise.all([
                safeList("/api/devices", "Device inventory"),
                safeList("/api/device-connection-clients", "Connection status"),
                safeList("/api/endpoint-agents", "Endpoint agents")
            ]);

            state.devices = devicesResult.items;
            state.clients = clientsResult.items;
            state.agents = agentsResult.items;
            state.errors = [
                devicesResult.error, clientsResult.error, agentsResult.error
            ].filter(Boolean);

            state.endpoints = state.devices.map(buildEndpoint);
            renderSummary();
            applyFilter();

            const updated = $("[data-eh-updated]");
            if (updated) {
                updated.textContent = "Updated " + new Date().toLocaleTimeString([], {
                    hour: "2-digit", minute: "2-digit", second: "2-digit"
                });
            }
        } catch (error) {
            state.errors = [`Unexpected error: ${error.message || error}`];
            renderSummary();
            applyFilter();
        } finally {
            state.loading = false;
            if (refresh) {
                refresh.disabled = false;
                refresh.textContent = "↻ Refresh";
            }
        }
    }

    $("[data-eh-search]")?.addEventListener("input", applyFilter);
    $("[data-eh-status]")?.addEventListener("change", applyFilter);
    $("[data-eh-platform]")?.addEventListener("change", applyFilter);
    $("[data-eh-refresh]")?.addEventListener("click", load);

    const clear = document.querySelector("[data-eh-clear]");
    clear?.addEventListener("click", () => {
        const search = $("[data-eh-search]");
        const status = $("[data-eh-status]");
        const platform = $("[data-eh-platform]");
        if (search) search.value = "";
        if (status) status.value = "";
        if (platform) platform.value = "";
        applyFilter();
    });

    load();
    const timer = window.setInterval(() => {
        if (!document.hidden) load();
    }, 30000);

    window.addEventListener("pagehide", () => window.clearInterval(timer), {once: true});
})();