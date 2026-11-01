/* =========================================================
   DEVICES — LOCAL DEMO INVENTORY
   ========================================================= */

const DEVICE_STORAGE_KEY = "cartman-devices-v1";
const DEVICE_GROUP_STORAGE_KEY = "cartman-device-groups-v1";
const DEVICE_TAG_STORAGE_KEY = "cartman-device-tags-v1";

const DEFAULT_DEVICE_TAGS = [
    "Server",
    "Workstation",
    "Laptop",
    "Network",
    "Virtual Machine",
    "Production",
    "Development",
    "Critical"
];

const DEVICE_STARTER_DATA = [
    {
        id: "device-001",
        name: "SRV-DC01",
        os: "Windows Server 2022",
        ip: "192.168.1.10",
        status: "Online",
        tags: ["Server", "Production", "Critical"]
    },
    {
        id: "device-002",
        name: "SRV-WEB01",
        os: "Ubuntu Server 24.04",
        ip: "192.168.1.20",
        status: "Online",
        tags: ["Server", "Virtual Machine", "Production"]
    },
    {
        id: "device-003",
        name: "WS-ADMIN01",
        os: "Windows 11",
        ip: "192.168.1.30",
        status: "Warning",
        tags: ["Workstation", "Critical"]
    },
    {
        id: "device-004",
        name: "MAC-MINI01",
        os: "macOS",
        ip: "192.168.1.40",
        status: "Online",
        tags: ["Workstation", "Development"]
    },
    {
        id: "device-005",
        name: "LNX-TOOLS01",
        os: "Ubuntu 24.04",
        ip: "192.168.1.50",
        status: "Offline",
        tags: ["Virtual Machine", "Development"]
    }
];

const deviceViewState = {
    filter: "All devices",
    search: "",
    editingId: null,
    sort: "newest",
    type: "all",
    os: "all",
    status: "all",
    selected: [],
    view: "devices",
    groupSearch: "",
    groupFormOpen: false,
    editingGroupId: null,
    selectedGroupId: null
};

function escapeDeviceHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);
}

let deviceRecords = [];
let deviceRecordsLoaded = false;
let deviceRecordsLoading = null;

const DEVICE_GROUP_MIGRATION_KEY = "cartman-device-groups-migrated-v1";
const DEVICE_GROUP_LEGACY_BACKUP_KEY = "cartman-device-groups-legacy-backup-v1";

let deviceGroupRecords = [];
let deviceGroupsLoaded = false;
let deviceGroupsLoading = null;


async function deviceApiRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            Accept: "application/json",
            ...(options.body ? { "Content-Type": "application/json" } : {}),
            ...(options.headers || {})
        },
        cache: "no-store"
    });

    let body = null;
    try {
        body = await response.json();
    } catch {
        // The server may return an empty response.
    }

    if (!response.ok) {
        const detail = typeof body?.detail === "string"
            ? body.detail
            : `HTTP ${response.status}`;
        throw new Error(detail);
    }

    return body;
}

async function loadDeviceDataFromAPI(force = false) {
    if (deviceRecordsLoading) return deviceRecordsLoading;
    if (deviceRecordsLoaded && !force) return deviceRecords;

    deviceRecordsLoading = deviceApiRequest("/api/devices")
        .then(records => {
            if (!Array.isArray(records)) {
                throw new Error("The Devices API returned an invalid response.");
            }

            deviceRecords = records.map(device => ({
                ...device,
                tags: Array.isArray(device.tags) ? device.tags : [],
                addedAt: device.created_at || null,
                lastSeen: null
            }));

            deviceRecordsLoaded = true;
            return deviceRecords;
        })
        .finally(() => {
            deviceRecordsLoading = null;
        });

    return deviceRecordsLoading;
}

function loadDeviceData() {
    return deviceRecords;
}
function saveDeviceData(devices) {
    try {
        localStorage.setItem(DEVICE_STORAGE_KEY, JSON.stringify(devices));
        return true;
    } catch (error) {
        console.error("Could not save Cartman demo devices:", error);
        notify("Could not save demo inventory in this browser.");
        return false;
    }
}

function loadDeviceTags() {
    try {
        const stored = localStorage.getItem(DEVICE_TAG_STORAGE_KEY);

        if (stored !== null) {
            const parsed = JSON.parse(stored);

            if (
                Array.isArray(parsed) &&
                parsed.every(tag => typeof tag === "string")
            ) {
                return [...new Set([...DEFAULT_DEVICE_TAGS, ...parsed])];
            }
        }
    } catch (error) {
        console.warn("Could not load Cartman demo tags:", error);
    }

    return [...DEFAULT_DEVICE_TAGS];
}

function saveDeviceTags(tags) {
    try {
        localStorage.setItem(
            DEVICE_TAG_STORAGE_KEY,
            JSON.stringify([...new Set(tags)])
        );
        return true;
    } catch (error) {
        console.error("Could not save Cartman demo tags:", error);
        notify("Could not save tags in this browser.");
        return false;
    }
}

function getDeviceData() {
    return deviceRecords;
}

/* Only display metadata actually supplied by the API. */
function getDeviceEnhancedData() {
    return getDeviceData().map(device => {
        const tags = Array.isArray(device.tags) ? device.tags : [];
        const type = device.type ||
            (tags.includes("Server") ? "Server" :
             tags.includes("Laptop") ? "Laptop" :
             tags.includes("Network") ? "Network" :
             tags.includes("Virtual Machine") ? "Virtual Machine" :
             "Workstation");

        return {
            ...device,
            type,
            assignedUser: device.assignedUser || null,
            manufacturer: device.manufacturer || null,
            model: device.model || null,
            cpu: device.cpu || null,
            gpu: device.gpu || null,
            ram: device.ram || null,
            disk: device.disk || null,
            addedAt: device.addedAt || device.created_at || null,
            lastSeen: device.lastSeen || null
        };
    });
}

function formatDeviceDate(value) {
    if (!value) return "Never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" :
        date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function exportSelectedDevicesJSON() {
    const selected = new Set((deviceViewState.selected || []).map(String));
    const devices = getDeviceEnhancedData().filter(device => selected.has(String(device.id)));
    if (!devices.length) {
        notify("Select at least one device first.");
        return;
    }
    const blob = new Blob([JSON.stringify({
        version: 1,
        exportedAt: new Date().toISOString(),
        devices
    }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "cartman-selected-devices.json";
    link.click();
    URL.revokeObjectURL(url);
    notify(`${devices.length} selected device(s) exported.`);
}



function exportDevicesJSON() {
    const payload = {
        version: 1,
        exportedAt: new Date().toISOString(),
        devices: getDeviceData()
    };

    const blob = new Blob(
        [JSON.stringify(payload, null, 2)],
        { type: "application/json" }
    );

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `cartman-devices-${new Date()
        .toISOString()
        .slice(0, 10)}.json`;

    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);

    notify("Device inventory exported.");
}

async function importDevicesJSON(file) {
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
        notify("JSON file must be smaller than 5 MB.");
        return;
    }

    let parsed;
    try {
        parsed = JSON.parse(await file.text());
    } catch {
        notify("Invalid JSON file.");
        return;
    }

    const imported = Array.isArray(parsed) ? parsed : parsed?.devices;
    if (!Array.isArray(imported) || imported.length > 5000) {
        notify("Invalid device list or too many devices (max 5000).");
        return;
    }

    const allowedStatuses = ["Online", "Warning", "Offline"];
    const valid = imported.every(device =>
        device &&
        typeof device === "object" &&
        !Array.isArray(device) &&
        typeof device.name === "string" &&
        device.name.trim().length > 0 &&
        device.name.trim().length <= 150 &&
        typeof device.os === "string" &&
        device.os.trim().length > 0 &&
        device.os.trim().length <= 150 &&
        (device.ip == null ||
            (typeof device.ip === "string" && device.ip.length <= 100)) &&
        (device.status == null || allowedStatuses.includes(device.status)) &&
        (device.tags == null ||
            (Array.isArray(device.tags) &&
             device.tags.length <= 100 &&
             device.tags.every(tag =>
                 typeof tag === "string" &&
                 tag.trim().length > 0 &&
                 tag.length <= 40
             )))
    );

    if (!valid) {
        notify("JSON contains invalid device data.");
        return;
    }

    if (!imported.length) {
        notify("The JSON file contains no devices.");
        return;
    }

    if (!window.confirm(
        `Import up to ${imported.length} device(s)? Existing devices will be kept.`
    )) return;

    const payload = imported.map(device => ({
        name: device.name.trim(),
        os: device.os.trim(),
        ip: typeof device.ip === "string" ? device.ip.trim() : "",
        status: device.status || "Online",
        tags: [...new Set((device.tags || []).map(tag => tag.trim()))]
    }));

    try {
        const result = await deviceApiRequest("/api/devices/import", {
            method: "POST",
            body: JSON.stringify(payload)
        });

        await loadDeviceDataFromAPI(true);

        const allTags = [
            ...getDeviceTags(),
            ...payload.flatMap(device => device.tags)
        ];
        saveDeviceTags(allTags);

        deviceViewState.filter = "All devices";
        deviceViewState.selected = [];
        renderDevicesModule();

        window.dispatchEvent(new CustomEvent("cartman:devices-updated", {
            detail: { action: "import" }
        }));

        notify(`Import complete: ${result.imported} added, ${result.skipped} skipped.`);
    } catch (error) {
        console.error("Device import failed:", error);
        notify(`Import failed: ${error.message}`);
    }
}

function getDeviceTags() {
    const tags = new Set(loadDeviceTags());

    getDeviceData().forEach(device => {
        device.tags.forEach(tag => tags.add(tag));
    });

    return [...tags].sort((a, b) => a.localeCompare(b));
}

function getDeviceStatusClass(status) {
    if (status === "Online") return "healthy";
    if (status === "Warning") return "warning-pill";
    return "gray";
}

function getDeviceSymbolClass(tags) {
    if (tags.includes("Server")) return "purple";
    if (tags.includes("Laptop")) return "cyan";
    if (tags.includes("Network")) return "orange";
    if (tags.includes("Virtual Machine")) return "blue";
    return "green";
}

function getDeviceSymbol(tags) {
    if (tags.includes("Server")) return "SV";
    if (tags.includes("Laptop")) return "LP";
    if (tags.includes("Network")) return "NW";
    if (tags.includes("Virtual Machine")) return "VM";
    return "DV";
}

function getDeviceFilteredData() {
    const query = deviceViewState.search.trim().toLowerCase();
    const devices = getDeviceEnhancedData().filter(device => {
        const matchesTag = deviceViewState.filter === "All devices" ||
            device.tags.includes(deviceViewState.filter);
        const matchesType = deviceViewState.type === "all" ||
            device.type === deviceViewState.type;
        const matchesOS = deviceViewState.os === "all" ||
            device.os === deviceViewState.os;
        const matchesStatus = deviceViewState.status === "all" ||
            device.status === deviceViewState.status;
        const user = device.assignedUser;
        const searchable = [
            device.name, device.os, device.ip, device.publicIp, device.status, device.type,
            device.cpu, device.ram, device.disk, user?.name, user?.username,
            ...device.tags
        ].join(" ").toLowerCase();
        return matchesTag && matchesType && matchesOS && matchesStatus &&
            (!query || searchable.includes(query));
    });

    const sorters = {
        newest: (a, b) => new Date(b.addedAt) - new Date(a.addedAt),
        oldest: (a, b) => new Date(a.addedAt) - new Date(b.addedAt),
        type: (a, b) => a.type.localeCompare(b.type),
        os: (a, b) => a.os.localeCompare(b.os),
        status: (a, b) => a.status.localeCompare(b.status)
    };
    return devices.sort(sorters[deviceViewState.sort] || sorters.newest);
}

function renderDeviceStats() {
    const devices = getDeviceData();

    const total = devices.length;
    const online = devices.filter(device => device.status === "Online").length;
    const warning = devices.filter(device => device.status === "Warning").length;
    const offline = devices.filter(device => device.status === "Offline").length;

    return `
        <div class="devices-stats">
            <div class="devices-stat">
                <div class="devices-stat-label">Total devices</div>
                <div class="devices-stat-value">${total}</div>
            </div>
            <div class="devices-stat">
                <div class="devices-stat-label">Online</div>
                <div class="devices-stat-value online">${online}</div>
            </div>
            <div class="devices-stat">
                <div class="devices-stat-label">Warning</div>
                <div class="devices-stat-value warning">${warning}</div>
            </div>
            <div class="devices-stat">
                <div class="devices-stat-label">Offline</div>
                <div class="devices-stat-value offline">${offline}</div>
            </div>
        </div>
    `;
}

function renderDeviceTags() { return ""; }

function renderDeviceRows() {
    const devices = getDeviceFilteredData();
    const selected = new Set((deviceViewState.selected || []).map(String));

    if (!devices.length) {
        return `<tr><td colspan="15"><div class="devices-empty">
            <strong>No devices found</strong>Try changing your search or filters.
        </div></td></tr>`;
    }

    return devices.map(device => {
        const symbolClass = getDeviceSymbolClass(device.tags);
        const symbol = getDeviceSymbol(device.tags);
        const user = device.assignedUser || { name: "Unassigned", username: "" };
        const tags = device.tags.length
            ? device.tags.map(tag => `<span class="device-row-tag">${escapeDeviceHTML(tag)}</span>`).join("")
            : `<span class="device-row-tag">Untagged</span>`;
        const status = device.status === "Online" ? "Active" :
            device.status === "Warning" ? "Unknown" : "Offline";

        return `<tr>
            <td><input class="device-select" type="checkbox" data-device-select="${escapeDeviceHTML(device.id)}" aria-label="Select ${escapeDeviceHTML(device.name)}" ${selected.has(String(device.id)) ? "checked" : ""}></td>
            <td><div class="device-name-cell">
                <div class="device-symbol ${symbolClass}">${symbol}</div>
                <div><strong>${escapeDeviceHTML(device.name)}</strong></div>
            </div></td>
            <td>${escapeDeviceHTML(device.manufacturer || "—")}</td>
            <td>${escapeDeviceHTML(device.model || "—")}</td>
            <td>${escapeDeviceHTML(device.ip || "—")}</td>
            <td>${escapeDeviceHTML(device.publicIp || "—")}</td>
            <td><div class="device-assigned-cell"><span class="device-user-avatar">${escapeDeviceHTML((user.name || "U").split(" ").map(part => part[0] || "").join("").slice(0, 2).toUpperCase())}</span><div><strong>${escapeDeviceHTML(user.name || "Unassigned")}</strong><small>${escapeDeviceHTML(user.username ? "@" + user.username : "No user assigned")}</small></div></div></td>
            <td><span class="device-type-label">${escapeDeviceHTML(device.type)}</span></td>
            <td>${escapeDeviceHTML(device.os)}</td>
            <td>${escapeDeviceHTML(device.cpu || "—")}</td>
            <td>${escapeDeviceHTML(device.gpu || "—")}</td>
            <td>${escapeDeviceHTML(device.ram || "—")}</td>
            <td>${escapeDeviceHTML(device.disk)}</td>
            <td>${formatDeviceDate(device.addedAt)}</td>
            <td>${formatDeviceDate(device.lastSeen)}</td>
            <td><span class="status-pill ${getDeviceStatusClass(device.status)}">${status}</span></td>
            <td><div class="device-row-tags">${tags}</div></td>
            <td><div class="device-actions">
                <button type="button" class="device-actions-trigger" data-device-new-action="more" data-device-id="${escapeDeviceHTML(device.id)}" aria-label="Device actions" title="Device actions" aria-haspopup="true" aria-expanded="false">⋯</button>
                <div class="device-actions-menu" data-device-menu hidden>
                    <button type="button" data-device-menu-action="edit" data-device-id="${escapeDeviceHTML(device.id)}">Edit device</button>
                    <button type="button" data-device-menu-action="package" data-device-id="${escapeDeviceHTML(device.id)}">Package deployment</button>
                    <button type="button" data-device-menu-action="shutdown" data-device-id="${escapeDeviceHTML(device.id)}">Shutdown</button>
                    <button type="button" data-device-menu-action="network" data-device-id="${escapeDeviceHTML(device.id)}">Kick from network</button>
                    <button type="button" data-device-menu-action="connect" data-device-id="${escapeDeviceHTML(device.id)}">Connect</button>
                    <button type="button" data-device-menu-action="monitor" data-device-id="${escapeDeviceHTML(device.id)}">Monitor</button>
                    <button type="button" data-device-menu-action="self-test" data-device-id="${escapeDeviceHTML(device.id)}">Agent self-test</button>
                    <button type="button" data-device-menu-action="vpn" data-device-id="${escapeDeviceHTML(device.id)}">VPN action</button>
                    <button type="button" class="device-actions-danger" data-device-menu-action="delete" data-device-id="${escapeDeviceHTML(device.id)}">Delete device</button>
                </div>
            </div></td>
        </tr>`;
    }).join("");
}


/* CARTMAN_DEVICE_GROUPS_FRONTEND_V1 */

function getDeviceGroups() {
    return deviceGroupRecords;
}

function buildDefaultDeviceGroups() {
    const inventory = getDeviceEnhancedData();

    const groups = [
        {
            id: "group-servers",
            name: "Servers",
            description: "Server endpoints",
            memberIds: inventory
                .filter(device => device.type === "Server")
                .map(device => String(device.id))
        },
        {
            id: "group-workstations",
            name: "Workstations",
            description: "User workstations and laptops",
            memberIds: inventory
                .filter(device => ["Workstation", "Laptop"].includes(device.type))
                .map(device => String(device.id))
        },
        {
            id: "group-development",
            name: "Development Lab",
            description: "Development and virtual machine endpoints",
            memberIds: inventory
                .filter(device =>
                    device.tags.includes("Development") ||
                    device.type === "Virtual Machine"
                )
                .map(device => String(device.id))
        }
    ].filter(group => group.memberIds.length > 0);

    return groups.length ? groups : [{
        id: "group-all-endpoints",
        name: "All Endpoints",
        description: "All inventory endpoints",
        memberIds: inventory.map(device => String(device.id))
    }];
}

function readLegacyDeviceGroups() {
    let raw = null;

    try {
        raw = localStorage.getItem(DEVICE_GROUP_STORAGE_KEY);
    } catch (error) {
        console.warn("Could not read legacy device groups:", error);
    }

    if (raw !== null) {
        try {
            const parsed = JSON.parse(raw);

            if (Array.isArray(parsed)) {
                return {
                    raw,
                    validArray: true,
                    groups: parsed.filter(group =>
                        group &&
                        typeof group.id === "string" &&
                        typeof group.name === "string" &&
                        typeof group.description === "string" &&
                        Array.isArray(group.memberIds) &&
                        group.memberIds.every(id => typeof id === "string")
                    )
                };
            }
        } catch (error) {
            console.warn("Legacy device groups could not be parsed:", error);
        }
    }

    return {
        raw,
        validArray: false,
        groups: buildDefaultDeviceGroups()
    };
}

function getLegacyDeviceNameById() {
    const names = new Map(
        DEVICE_STARTER_DATA.map(device => [
            String(device.id),
            String(device.name)
        ])
    );

    // Older versions may have stored additional demo devices locally.
    try {
        const raw = localStorage.getItem(DEVICE_STORAGE_KEY);
        if (raw) {
            const stored = JSON.parse(raw);
            if (Array.isArray(stored)) {
                stored.forEach(device => {
                    if (device && device.id != null && device.name) {
                        names.set(String(device.id), String(device.name));
                    }
                });
            }
        }
    } catch (error) {
        console.warn("Could not read legacy device inventory:", error);
    }

    return names;
}

function prepareDeviceGroupImport(candidates, existingGroups) {
    const inventory = getDeviceData();
    const realIds = new Set(inventory.map(device => String(device.id)));
    const realIdByName = new Map(
        inventory
            .filter(device => device.name)
            .map(device => [String(device.name).trim().toLowerCase(), String(device.id)])
    );
    const legacyNames = getLegacyDeviceNameById();

    const usedIds = new Set(existingGroups.map(group => String(group.id)));
    const usedNames = new Set(
        existingGroups.map(group => String(group.name).trim().toLowerCase())
    );

    const result = [];

    candidates.forEach((group, index) => {
        const id = String(group.id || `group-migrated-${index + 1}`).trim();
        const name = String(group.name || "").trim();
        const nameKey = name.toLowerCase();

        if (!id || !name || usedIds.has(id) || usedNames.has(nameKey)) {
            console.warn(
                "Skipping a legacy group that conflicts with existing group data:",
                group
            );
            return;
        }

        const members = [];
        const memberIds = Array.isArray(group.memberIds) ? group.memberIds : [];

        memberIds.forEach(memberId => {
            const oldId = String(memberId);
            let actualId = realIds.has(oldId) ? oldId : null;

            if (!actualId) {
                const legacyName = legacyNames.get(oldId);
                if (legacyName) {
                    actualId = realIdByName.get(legacyName.trim().toLowerCase()) || null;
                }
            }

            // Do not create broken memberships for devices that no longer exist.
            if (actualId && !members.includes(actualId)) {
                members.push(actualId);
            }
        });

        result.push({
            id,
            name,
            description: String(group.description || ""),
            memberIds: members
        });

        usedIds.add(id);
        usedNames.add(nameKey);
    });

    return result;
}

async function loadDeviceGroupsFromAPI(force = false) {
    if (deviceGroupsLoading) return deviceGroupsLoading;
    if (deviceGroupsLoaded && !force) return deviceGroupRecords;

    deviceGroupsLoading = (async () => {
        let groups = await deviceApiRequest("/api/device-groups");

        if (!Array.isArray(groups)) {
            throw new Error("The Device Groups API returned an invalid response.");
        }

        let migrationCompleted = false;
        try {
            migrationCompleted =
                localStorage.getItem(DEVICE_GROUP_MIGRATION_KEY) === "complete";
        } catch (error) {
            console.warn("Could not read group migration status:", error);
        }

        if (!migrationCompleted) {
            const legacy = readLegacyDeviceGroups();

            // If the server is empty, reproduce the previous view from its
            // saved groups, or seed the former default groups when no saved
            // local group list exists.
            // If the server already has groups, migrate only an actual saved
            // local array and skip conflicting IDs/names.
            const candidates = groups.length === 0
                ? legacy.groups
                : (legacy.validArray ? legacy.groups : []);

            const toImport = prepareDeviceGroupImport(candidates, groups);

            if (toImport.length) {
                const imported = await deviceApiRequest(
                    "/api/device-groups/import",
                    {
                        method: "POST",
                        body: JSON.stringify(toImport)
                    }
                );

                if (!Array.isArray(imported)) {
                    throw new Error("The group import API returned an invalid response.");
                }

                groups = imported;
            }

            // Keep a raw browser-side backup. The server is now authoritative.
            try {
                if (
                    legacy.raw !== null &&
                    localStorage.getItem(DEVICE_GROUP_LEGACY_BACKUP_KEY) === null
                ) {
                    localStorage.setItem(
                        DEVICE_GROUP_LEGACY_BACKUP_KEY,
                        legacy.raw
                    );
                }
                localStorage.setItem(DEVICE_GROUP_MIGRATION_KEY, "complete");
            } catch (error) {
                console.warn("Could not save legacy group migration marker:", error);
            }
        }

        deviceGroupRecords = groups.map(group => ({
            ...group,
            id: String(group.id),
            name: String(group.name),
            description: String(group.description || ""),
            memberIds: Array.isArray(group.memberIds)
                ? group.memberIds.map(String)
                : []
        }));

        deviceGroupsLoaded = true;
        return deviceGroupRecords;
    })().finally(() => {
        deviceGroupsLoading = null;
    });

    return deviceGroupsLoading;
}

async function deleteDeviceGroupFromAPI(groupId) {
    await deviceApiRequest(
        `/api/device-groups/${encodeURIComponent(groupId)}`,
        { method: "DELETE" }
    );

    await loadDeviceGroupsFromAPI(true);

    if (deviceViewState.selectedGroupId === groupId) {
        deviceViewState.selectedGroupId = null;
    }
    if (deviceViewState.editingGroupId === groupId) {
        deviceViewState.editingGroupId = null;
        deviceViewState.groupFormOpen = false;
    }

    renderDevicesModule();
    notify("Device group deleted.");
}

function renderDeviceTabs() {
    const groupsActive = deviceViewState.view === "groups";

    return `
        <nav class="devices-subnav" aria-label="Device sections" role="tablist">
            <button type="button" role="tab"
                aria-selected="${!groupsActive}"
                class="${!groupsActive ? "is-active" : ""}"
                data-device-view="devices">Devices</button>
            <button type="button" role="tab"
                aria-selected="${groupsActive}"
                class="${groupsActive ? "is-active" : ""}"
                data-device-view="groups">Device Groups</button>
        </nav>`;
}

function renderDeviceGroupCards() {
    const groups = getDeviceGroups();
    const query = deviceViewState.groupSearch.trim().toLowerCase();

    const filtered = groups.filter(group =>
        `${group.name} ${group.description}`.toLowerCase().includes(query)
    );

    if (!filtered.length) {
        return `<div class="device-groups-empty">
            No groups match your search. Create a new group or change the search.
        </div>`;
    }

    return filtered.map(group => {
        const selected = group.id === deviceViewState.selectedGroupId;
        const memberCount = group.memberIds.filter(id =>
            getDeviceData().some(device => device.id === id)
        ).length;

        return `
            <article class="device-group-card ${selected ? "is-selected" : ""}">
                <button type="button" class="device-group-card-main"
                    data-device-group-action="select"
                    data-device-group-id="${escapeDeviceHTML(group.id)}"
                    aria-pressed="${selected}">
                    <span class="device-group-card-icon" aria-hidden="true">▦</span>
                    <span class="device-group-card-copy">
                        <strong>${escapeDeviceHTML(group.name)}</strong>
                        <small>${escapeDeviceHTML(group.description || "No description")}</small>
                        <small>${memberCount} device${memberCount === 1 ? "" : "s"}</small>
                    </span>
                </button>
                <div class="device-group-card-actions">
                    <button type="button" class="secondary-button"
                        data-device-group-action="edit"
                        data-device-group-id="${escapeDeviceHTML(group.id)}">Edit</button>
                    <button type="button" class="secondary-button"
                        data-device-group-action="delete"
                        data-device-group-id="${escapeDeviceHTML(group.id)}">Delete</button>
                </div>
            </article>`;
    }).join("");
}

function renderDeviceGroupsView() {
    const groups = getDeviceGroups();
    const selectedGroup = groups.find(group =>
        group.id === deviceViewState.selectedGroupId
    );
    const editorGroup = deviceViewState.editingGroupId
        ? groups.find(group => group.id === deviceViewState.editingGroupId)
        : null;
    const devices = getDeviceEnhancedData();
    const selectedMemberIds = editorGroup?.memberIds || [];

    const editor = deviceViewState.groupFormOpen ? `
        <section class="device-group-editor">
            <div class="devices-panel-heading">
                <div>
                    <h2>${editorGroup ? "Edit group" : "Create device group"}</h2>
                    <p>Choose which inventory devices belong to this group.</p>
                </div>
                <button type="button" class="secondary-button"
                    data-device-group-action="cancel">Cancel</button>
            </div>
            <form id="device-group-form">
                <label class="device-group-field">
                    Group name
                    <input id="device-group-name" name="name" required maxlength="80"
                        value="${escapeDeviceHTML(editorGroup?.name || "")}"
                        placeholder="e.g. Production Servers">
                </label>
                <label class="device-group-field">
                    Description
                    <textarea id="device-group-description" name="description"
                        rows="2" maxlength="300"
                        placeholder="What is this group used for?">${escapeDeviceHTML(editorGroup?.description || "")}</textarea>
                </label>
                <div class="device-group-members-heading">
                    <h3>Group members</h3>
                    <span>${devices.length} available devices</span>
                </div>
                <div class="device-group-member-picker">
                    ${devices.length ? devices.map(device => `
                        <label class="device-group-member-option">
                            <input type="checkbox" name="device-group-members"
                                value="${escapeDeviceHTML(device.id)}"
                                ${selectedMemberIds.includes(device.id) ? "checked" : ""}>
                            <span>
                                <strong>${escapeDeviceHTML(device.name)}</strong>
                                <small>${escapeDeviceHTML(device.os)} · ${escapeDeviceHTML(device.status)}</small>
                            </span>
                        </label>`).join("") : `
                        <p class="device-groups-empty">No devices are available yet.</p>`}
                </div>
                <div class="device-group-form-actions">
                    <button type="button" class="secondary-button"
                        data-device-group-action="cancel">Cancel</button>
                    <button type="submit" class="primary-button">
                        ${editorGroup ? "Save changes" : "Create group"}
                    </button>
                </div>
            </form>
        </section>` : "";

    const selectedMembers = selectedGroup
        ? selectedGroup.memberIds.map(id =>
            devices.find(device => device.id === id)
        ).filter(Boolean)
        : [];

    const details = selectedGroup ? `
        <section class="device-group-details">
            <div class="devices-panel-heading">
                <div>
                    <h2>${escapeDeviceHTML(selectedGroup.name)}</h2>
                    <p>${escapeDeviceHTML(selectedGroup.description || "No description")}</p>
                </div>
                <span class="section-count">${selectedMembers.length} MEMBERS</span>
            </div>
            ${selectedMembers.length ? `
                <div class="device-group-member-list">
                    ${selectedMembers.map(device => `
                        <div class="device-group-member-row">
                            <span class="device-group-status ${escapeDeviceHTML(String(device.status).toLowerCase())}"></span>
                            <span><strong>${escapeDeviceHTML(device.name)}</strong>
                                <small>${escapeDeviceHTML(device.os)}</small></span>
                            <span class="device-group-member-state">${escapeDeviceHTML(device.status)}</span>
                        </div>`).join("")}
                </div>` : `
                <div class="device-groups-empty">
                    This group has no members. Edit the group to add devices.
                </div>`}
        </section>` : `
        <section class="device-group-details device-groups-empty">
            Select a group to inspect its members, or create a new group.
        </section>`;

    return `
        ${renderDeviceTabs()}
        <div class="device-groups-workspace">
            <div class="devices-redesign-heading">
                <div>
                    <h1>Device Groups</h1>
                    <p>Organize endpoints into manageable groups.</p>
                </div>
                <button type="button" class="primary-button"
                    data-device-group-action="new">＋ New group</button>
            </div>
            <div class="device-groups-summary">
                <div><span>Groups</span><strong>${groups.length}</strong></div>
                <div><span>Inventory devices</span><strong>${devices.length}</strong></div>
                <div><span>Selected group</span><strong>${selectedGroup ? escapeDeviceHTML(selectedGroup.name) : "—"}</strong></div>
            </div>
            <section class="device-groups-panel">
                <div class="devices-panel-heading">
                    <div><h2>Groups overview</h2><p>Connected to Cartman API</p></div>
                    <span class="section-count">${groups.length} GROUPS</span>
                </div>
                <label class="device-group-search">
                    <span aria-hidden="true">⌕</span>
                    <input type="search" id="device-group-search-input"
                        value="${escapeDeviceHTML(deviceViewState.groupSearch)}"
                        placeholder="Search groups..." aria-label="Search device groups">
                </label>
                <div class="device-groups-list">${renderDeviceGroupCards()}</div>
            </section>
            ${details}
            ${editor}
            <p class="devices-demo-note">
                Groups and memberships are stored in the Cartman database. This screen does not run endpoint commands.
            </p>
        </div>`;
}

async function saveDeviceGroupForm(event) {
    event.preventDefault();

    const form = event.target;
    if (!form.reportValidity()) return;

    const formData = new FormData(form);
    const name = String(formData.get("name") || "").trim();
    const description = String(formData.get("description") || "").trim();
    const editingId = deviceViewState.editingGroupId;
    const groups = getDeviceGroups();

    if (!name) {
        notify("Group name is required.");
        return;
    }

    if (groups.some(group =>
        group.name.toLowerCase() === name.toLowerCase() &&
        group.id !== editingId
    )) {
        notify("A group with that name already exists.");
        return;
    }

    const memberIds = [...form.querySelectorAll(
        'input[name="device-group-members"]:checked'
    )].map(input => String(input.value));

    try {
        const url = editingId
            ? `/api/device-groups/${encodeURIComponent(editingId)}`
            : "/api/device-groups";

        const saved = await deviceApiRequest(url, {
            method: editingId ? "PUT" : "POST",
            body: JSON.stringify({ name, description, memberIds })
        });

        await loadDeviceGroupsFromAPI(true);

        deviceViewState.selectedGroupId = String(saved.id);
        deviceViewState.editingGroupId = null;
        deviceViewState.groupFormOpen = false;

        renderDevicesModule();
        notify(editingId ? "Device group updated." : "Device group created.");
    } catch (error) {
        console.error("Device group save failed:", error);
        notify(`Could not save device group: ${error.message}`);
    }
}

function renderDevicesModule() {
    const moduleView = $("#module-view");
    if (!moduleView || state.module !== "Devices") return;
    setModulePlaceholderVisible(false);

    let workspace = $("#devices-workspace");
    if (!workspace) {
        workspace = document.createElement("div");
        workspace.id = "devices-workspace";
        workspace.className = "devices-workspace";
        moduleView.appendChild(workspace);
    }

    if (!deviceRecordsLoaded) {
        workspace.innerHTML = '<div class="empty-state">Loading devices from Cartman API…</div>';
        if (!deviceRecordsLoading) {
            loadDeviceDataFromAPI()
                .then(() => renderDevicesModule())
                .catch(error => {
                    console.error("Device API load failed:", error);
                    workspace.innerHTML = '<div class="empty-state">Could not load devices from the Cartman API. Check the server and refresh this page.</div>';
                    notify(`Could not load devices: ${error.message}`);
                });
        }
        return;
    }

    if (deviceViewState.view === "groups") {
        if (!deviceGroupsLoaded) {
            workspace.innerHTML =
                '<div class="empty-state">Loading device groups from Cartman API…</div>';

            if (!deviceGroupsLoading) {
                loadDeviceGroupsFromAPI()
                    .then(() => renderDevicesModule())
                    .catch(error => {
                        console.error("Device Groups API load failed:", error);
                        workspace.innerHTML =
                            '<div class="empty-state">Could not load device groups from the Cartman API. Check the server and refresh this page.</div>';
                        notify(`Could not load device groups: ${error.message}`);
                    });
            }
            return;
        }

        workspace.innerHTML = renderDeviceGroupsView();
        return;
    }


    const all = getDeviceEnhancedData();
    const osOptions = [...new Set(all.map(d => d.os))];
    const typeOptions = [...new Set(all.map(d => d.type))];
    const tagOptions = getDeviceTags();
    const selectedCount = deviceViewState.selected.length;

    workspace.innerHTML = `
        ${renderDeviceTabs()}
        <div class="devices-redesign-heading">
            <div><h1>Devices</h1><p>Manage and monitor your endpoint inventory.</p></div>
            <button type="button" class="primary-button" data-device-action="add">＋ Add device</button>
        </div>
        ${renderDeviceStats()}
        <section class="devices-controls">
            <label class="devices-search"><span aria-hidden="true">⌕</span>
                <input type="search" id="devices-search-input" placeholder="Search name, user, OS, CPU, RAM, disk or tag..." value="${escapeDeviceHTML(deviceViewState.search)}" aria-label="Search devices">
            </label>
            <div class="devices-filter-controls">
                <label>Sort
                    <select id="devices-sort">
                        <option value="newest" ${deviceViewState.sort === "newest" ? "selected" : ""}>Newest first</option>
                        <option value="oldest" ${deviceViewState.sort === "oldest" ? "selected" : ""}>Oldest first</option>
                        <option value="type" ${deviceViewState.sort === "type" ? "selected" : ""}>Device type</option>
                        <option value="os" ${deviceViewState.sort === "os" ? "selected" : ""}>Operating system</option>
                        <option value="status" ${deviceViewState.sort === "status" ? "selected" : ""}>Activity status</option>
                    </select>
                </label>
                <label>Type
                    <select id="devices-type-filter">
                        <option value="all">All types</option>
                        ${typeOptions.map(v => `<option value="${escapeDeviceHTML(v)}" ${deviceViewState.type === v ? "selected" : ""}>${escapeDeviceHTML(v)}</option>`).join("")}
                    </select>
                </label>
                <label>Operating system
                    <select id="devices-os-filter">
                        <option value="all">All systems</option>
                        ${osOptions.map(v => `<option value="${escapeDeviceHTML(v)}" ${deviceViewState.os === v ? "selected" : ""}>${escapeDeviceHTML(v)}</option>`).join("")}
                    </select>
                </label>
                <label>Status
                    <select id="devices-status-filter">
                        <option value="all">All statuses</option>
                        <option value="Online" ${deviceViewState.status === "Online" ? "selected" : ""}>Active</option>
                        <option value="Offline" ${deviceViewState.status === "Offline" ? "selected" : ""}>Offline</option>
                        <option value="Warning" ${deviceViewState.status === "Warning" ? "selected" : ""}>Unknown</option>
                    </select>
                </label>
                <label>Tags
                    <select id="devices-tag-filter">
                        <option value="All devices" ${deviceViewState.filter === "All devices" ? "selected" : ""}>All tags</option>
                        ${tagOptions.map(tag => `<option value="${escapeDeviceHTML(tag)}" ${deviceViewState.filter === tag ? "selected" : ""}>${escapeDeviceHTML(tag)}</option>`).join("")}
                    </select>
                </label>
            </div>
            <div class="devices-toolbar-right">
                <button type="button" class="secondary-button" id="devices-clear-filters">Clear Filters</button>
                <button type="button" class="secondary-button" data-device-action="import-json">Import JSON</button>
                <button type="button" class="secondary-button" data-device-action="export-json">Export JSON</button>
                <button type="button" class="secondary-button" data-device-action="inventory-info">Inventory info</button>
                <input type="file" id="devices-json-file" accept=".json,application/json" hidden>
            </div>
        </section>
        <section class="devices-table-panel">
            <div class="devices-panel-heading">
                <div><h2>Device inventory</h2><p>Cartman API inventory · ${all.length} devices registered</p></div>
                <div class="devices-inventory-heading-actions">
                    <span class="section-count">${getDeviceFilteredData().length} SHOWN</span>
                    <div class="devices-inventory-actions">
                        <button type="button" class="secondary-button devices-inventory-actions-trigger" data-device-new-action="inventory-more" aria-haspopup="true" aria-expanded="false">Actions <span aria-hidden="true">⌄</span></button>
                        <div class="device-actions-menu devices-inventory-actions-menu" data-device-menu hidden>
                            <div class="devices-inventory-selection-count">${selectedCount} selected</div>
                            <button type="button" data-device-new-action="package">Package deployment</button>
                            <button type="button" data-device-new-action="shutdown">Shutdown</button>
                            <button type="button" data-device-new-action="network">Kick from network</button>
                            <button type="button" data-device-new-action="export-selected">Export selected JSON</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="devices-table-wrap">
                <table class="devices-table devices-table-modern">
                    <thead><tr>
                        <th><input type="checkbox" id="devices-select-visible" aria-label="Select visible devices" ${getDeviceFilteredData().length && getDeviceFilteredData().every(d => deviceViewState.selected.includes(String(d.id))) ? "checked" : ""}></th>
                        <th>DEVICE</th><th>MANUFACTURER</th><th>MODEL</th><th>PRIVATE IP</th><th>PUBLIC IP</th><th>ASSIGNED TO</th><th>TYPE</th><th>OPERATING SYSTEM</th><th>CPU</th><th>GPU</th><th>RAM</th><th>DISK</th><th>ADDED</th><th>LAST SEEN</th><th>STATUS</th><th>TAGS</th><th>ACTIONS</th>
                    </tr></thead>
                    <tbody>${renderDeviceRows()}</tbody>
                </table>
            </div>
        </section>
        <p class="devices-demo-note">Inventory records are loaded from the Cartman API. Hardware specifications, user assignments and last-seen times are shown only when integrations provide them.</p>
    `;
}



async function deviceListenerRequest(url, options = {}) {
    const response = await fetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(body.detail || `${response.status} ${response.statusText}`);
    }
    return body;
}

async function refreshDeviceListenerStatus() {
    const panel = document.querySelector('[data-device-panel="auto"]');
    if (!panel) return;

    const modeSelect = panel.querySelector("#device-connect-ip-mode");
    const addressField = panel.querySelector("#device-connect-address");
    const statusField = panel.querySelector("#device-connect-status-value");
    const listenerButton = panel.querySelector('[data-device-action="toggle-device-listener"]');
    const notice = panel.querySelector(".device-connect-notice");

    try {
        const state = await deviceListenerRequest("/api/device-connection-listener/status");
        const mode = modeSelect?.value || "local";
        const ip = mode === "public" ? state.public_ip : state.local_ip;

        if (addressField) {
            addressField.textContent = ip
                ? `${ip}:${state.port}`
                : `Address unavailable · port ${state.port}`;
        }
        if (statusField) {
            if (state.running) {
                statusField.innerHTML =
                    `Listening at ${escapeDeviceHTML(state.listen_address)}:${Number(state.port) || 50101} ` +
                    '<span class="listener-dot-loader" aria-label="Listener active">' +
                    '<i></i><i></i><i></i></span>';
            } else {
                statusField.textContent = "Stopped";
            }
        }

        if (modeSelect) modeSelect.disabled = state.running;
        if (listenerButton) {
            listenerButton.hidden = false;
            listenerButton.disabled = false;
            listenerButton.classList.toggle("is-listening", state.running);
            listenerButton.dataset.listenerState = state.running ? "running" : "stopped";
            listenerButton.textContent = state.running ? "Stop Listening" : "Start Listening";
        }

        if (notice) {
            if (mode === "public") {
                notice.textContent =
                    "Public IP is shown for planning only. Public listening is disabled until authenticated, encrypted client connections are implemented. Router/NAT port forwarding would also be required.";
            } else if (state.running) {
                notice.textContent =
                    `Open CartmanClient on the device you want to connect. ` +
                    `Enter Server IP ${state.listen_address} and Port ${state.port}, ` +
                    `then select Connect. Keep this listener running while connecting.`;
            } else {
                notice.textContent =
                    "Stopped. The listener starts only when you press Start Listening.";
            }
        }
    } catch (error) {
        if (statusField) statusField.textContent = "Status unavailable";
        if (addressField) addressField.textContent = "Could not detect address";
        if (notice) notice.textContent = `Could not read listener status: ${error.message}`;
    }
}

async function decideDeviceConnectionRequest(requestId, decision, button) {
    if (!requestId || !["Approved", "Rejected"].includes(decision)) return;

    const card = button?.closest(".device-connect-request");
    const deviceName = card?.querySelector("strong")?.textContent || "this device";
    const verb = decision === "Approved" ? "allow" : "deny";

    if (!window.confirm(`Do you want to ${verb} ${deviceName}?`)) return;

    const actionButtons = card?.querySelectorAll("button") || [];
    actionButtons.forEach(item => { item.disabled = true; });

    try {
        const result = await deviceListenerRequest(
            `/api/device-connection-requests/${encodeURIComponent(requestId)}/decision`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ decision }),
            }
        );

        const notice = document.querySelector(
            '[data-device-panel="auto"] .device-connect-notice'
        );
        if (notice) notice.textContent = result.message;

        await refreshDeviceConnectionRequests();
        console.log("Cartman device decision:", result);
    } catch (error) {
        const message = `Could not ${verb} device: ${error.message}`;
        let errorNote = card?.querySelector(".device-connect-decision-error");

        if (card && !errorNote) {
            errorNote = document.createElement("p");
            errorNote.className = "device-connect-decision-error";
            errorNote.setAttribute("role", "alert");
            card.appendChild(errorNote);
        }
        if (errorNote) errorNote.textContent = message;
        else console.error(message);

        actionButtons.forEach(item => { item.disabled = false; });
    }
}

async function refreshDeviceConnectionRequests() {
    const panel = document.querySelector('[data-device-panel="auto"]');
    const list = panel?.querySelector(".device-connect-requests");
    if (!panel || !list) return;

    list.innerHTML = "<h3>Connection requests</h3><p>Loading pending requests...</p>";

    try {
        const requests = await deviceApiRequest("/api/device-connection-requests");

        if (!Array.isArray(requests) || requests.length === 0) {
            list.innerHTML = "<h3>Connection requests</h3><p>No pending requests.</p>";
            return;
        }

        const escape = value => escapeDeviceHTML(String(value ?? ""));
        list.innerHTML = `
            <h3>Connection requests (${requests.length})</h3>
            ${requests.map(request => `
                <article class="device-connect-request">
                    <strong>${escape(request.device_name)}</strong>
                    <p>OS: ${escape(request.os)}</p>
                    <p>Client IP: ${escape(request.client_ip || "Not provided")}</p>
                    <p>Username: ${escape(request.username || "Not provided")}</p>
                    <p>Status: ${escape(request.status)}</p>
                    <p>This device will not enter the inventory until you approve it.</p>
                    <div class="device-connect-request-actions"
                         style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
                        <button type="button" class="primary-button"
                            data-device-action="approve-device-request"
                            data-device-request-id="${escape(request.id)}">Allow</button>
                        <button type="button" class="secondary-button"
                            data-device-action="deny-device-request"
                            data-device-request-id="${escape(request.id)}">Deny</button>
                    </div>
                </article>
            `).join("")}
        `;
    } catch (error) {
        console.error("Could not load connection requests:", error);
        list.innerHTML = `
            <h3>Connection requests</h3>
            <p>Could not load requests: ${escapeDeviceHTML(error.message)}</p>
            <button type="button" class="secondary-button"
                data-device-action="refresh-device-requests">Retry</button>
        `;
    }
}

async function toggleDeviceConnectionListener() {
    const state = await deviceListenerRequest(
        "/api/device-connection-listener/status"
    );

    if (state.running) {
        await stopDeviceConnectionDiscovery();
    } else {
        await startDeviceConnectionDiscovery();
    }
}

async function startDeviceConnectionDiscovery() {
    const panel = document.querySelector('[data-device-panel="auto"]');
    if (!panel) return;

    const button = panel.querySelector('[data-device-action="toggle-device-listener"]');
    const notice = panel.querySelector(".device-connect-notice");
    const mode = panel.querySelector("#device-connect-ip-mode")?.value || "local";

    if (mode === "public") {
        if (notice) {
            notice.textContent =
                "Public listening is disabled until authenticated, encrypted client connections are implemented. Select Local IP to start listening on your LAN.";
        }
        return;
    }

    if (button) {
        button.disabled = true;
        button.innerHTML =
            'Starting <span class="listener-dot-loader" aria-label="Starting">' +
            '<i></i><i></i><i></i></span>';
    }

    try {
        const result = await deviceListenerRequest(
            "/api/device-connection-listener/start",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ address_mode: mode }),
            }
        );

        if (notice) {
            notice.textContent =
                `Listening at ${result.listen_address}:${result.port}. ` +
                "Waiting for CartmanClient metadata requests.";
        }
        await refreshDeviceListenerStatus();
        await refreshDeviceConnectionRequests();
    } catch (error) {
        if (notice) notice.textContent = `Could not start listener: ${error.message}`;
    } finally {
        await refreshDeviceListenerStatus();
    }
}

async function stopDeviceConnectionDiscovery() {
    const panel = document.querySelector('[data-device-panel="auto"]');
    const notice = panel?.querySelector(".device-connect-notice");
    const button = panel?.querySelector(
        '[data-device-action="toggle-device-listener"]'
    );

    if (button) {
        button.disabled = true;
        button.innerHTML =
            'Stopping <span class="listener-dot-loader" aria-label="Stopping">' +
            '<i></i><i></i><i></i></span>';
    }

    try {
        await deviceListenerRequest("/api/device-connection-listener/stop", {
            method: "POST",
        });
        if (notice) notice.textContent = "Listener stopped.";
    } catch (error) {
        if (notice) notice.textContent = `Could not stop listener: ${error.message}`;
    } finally {
        await refreshDeviceListenerStatus();
    }
}

document.addEventListener("change", event => {
    if (event.target.matches("#device-connect-ip-mode")) {
        void refreshDeviceListenerStatus();
    }
});


function openDeviceInventoryInfo() {
    document.getElementById("device-inventory-info-modal")?.remove();

    let devices = [];
    try {
        devices = typeof getDeviceData === "function"
            ? getDeviceData()
            : [];
        if (!Array.isArray(devices)) devices = [];
    } catch (error) {
        console.error("Could not read device inventory:", error);
    }

    const statusCount = status => devices.filter(device =>
        String(device.status || "").toLowerCase() === status
    ).length;

    const operatingSystems = new Map();
    devices.forEach(device => {
        const os = String(device.os || "Unknown").trim() || "Unknown";
        operatingSystems.set(os, (operatingSystems.get(os) || 0) + 1);
    });

    const escape = value => escapeDeviceHTML(String(value ?? ""));
    const osRows = [...operatingSystems.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([os, count]) => `
            <div style="display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--border-color,#30394d)">
                <span>${escape(os)}</span>
                <strong>${count}</strong>
            </div>
        `).join("");

    const backdrop = document.createElement("div");
    backdrop.id = "device-inventory-info-modal";
    backdrop.className = "devices-modal-backdrop";
    backdrop.innerHTML = `
        <section class="devices-modal" role="dialog"
                 aria-modal="true"
                 aria-labelledby="device-inventory-info-title">
            <header class="devices-modal-header">
                <div>
                    <h2 id="device-inventory-info-title">Inventory info</h2>
                    <p>Summary of the current Devices inventory.</p>
                </div>
                <button type="button" class="secondary-button"
                        data-device-action="close-inventory-info"
                        aria-label="Close inventory information">✕</button>
            </header>
            <div style="padding:22px">
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px">
                    <div style="padding:16px;border:1px solid var(--border-color,#30394d);border-radius:10px">
                        <div style="color:var(--text-muted,#9aa7bd);font-size:12px">Total devices</div>
                        <strong style="display:block;font-size:26px;margin-top:6px">${devices.length}</strong>
                    </div>
                    <div style="padding:16px;border:1px solid var(--border-color,#30394d);border-radius:10px">
                        <div style="color:var(--text-muted,#9aa7bd);font-size:12px">Online</div>
                        <strong style="display:block;font-size:26px;margin-top:6px">${statusCount("online")}</strong>
                    </div>
                    <div style="padding:16px;border:1px solid var(--border-color,#30394d);border-radius:10px">
                        <div style="color:var(--text-muted,#9aa7bd);font-size:12px">Warning</div>
                        <strong style="display:block;font-size:26px;margin-top:6px">${statusCount("warning")}</strong>
                    </div>
                    <div style="padding:16px;border:1px solid var(--border-color,#30394d);border-radius:10px">
                        <div style="color:var(--text-muted,#9aa7bd);font-size:12px">Offline</div>
                        <strong style="display:block;font-size:26px;margin-top:6px">${statusCount("offline")}</strong>
                    </div>
                </div>
                <h3 style="margin:24px 0 8px">Operating systems</h3>
                ${osRows || '<p>No device records available.</p>'}
                <p style="color:var(--text-muted,#9aa7bd);font-size:12px;margin-top:18px">
                    This summary uses the current Devices inventory records.
                </p>
            </div>
            <footer class="devices-modal-footer">
                <button type="button" class="primary-button"
                        data-device-action="close-inventory-info">Close</button>
            </footer>
        </section>
    `;

    document.body.appendChild(backdrop);
    backdrop.addEventListener("click", event => {
        if (event.target === backdrop) backdrop.remove();
    });
}


async function openDeviceActionModal(device, action) {
    const labels = {
        package: "Package deployment",
        shutdown: "Shutdown",
        network: "Kick from network",
        connect: "Connect",
        monitor: "Monitor",
        vpn: "VPN action",
        "self-test": "Agent self-test"
    };
    const actionNames = {
        package: "package_deployment",
        shutdown: "shutdown",
        network: "network_disconnect",
        vpn: "vpn_action",
        "self-test": "self_test"
    };

    if (!device || !device.id) {
        notify("A valid device must be selected.");
        return;
    }

    const oldModal = document.getElementById("device-action-modal-backdrop");
    if (oldModal) {
        if (oldModal._refreshTimer) clearInterval(oldModal._refreshTimer);
        oldModal.remove();
    }

    const esc = value => escapeDeviceHTML(String(value ?? ""));
    const modal = document.createElement("div");
    modal.id = "device-action-modal-backdrop";
    modal.className = "devices-modal-backdrop";
    modal.innerHTML = `
        <section class="devices-modal" role="dialog" aria-modal="true"
                 aria-labelledby="device-action-modal-title">
            <header class="devices-modal-header">
                <div>
                    <h2 id="device-action-modal-title">${esc(labels[action] || action)}</h2>
                    <p>${esc(device.name)} · ${esc(device.os || "Unknown OS")}</p>
                </div>
                <button type="button" class="secondary-button" data-close-device-action
                        aria-label="Close">✕</button>
            </header>
            <div class="device-action-modal-content" style="padding:22px">
                <p>Loading device information...</p>
            </div>
            <footer class="devices-modal-footer">
                <button type="button" class="secondary-button" data-close-device-action>Close</button>
            </footer>
        </section>
    `;
    document.body.appendChild(modal);

    const content = modal.querySelector(".device-action-modal-content");

    function closeModal() {
        if (modal._refreshTimer) clearInterval(modal._refreshTimer);
        document.removeEventListener("keydown", modal._escapeHandler);
        modal.remove();
    }

    modal._escapeHandler = event => {
        if (event.key === "Escape") closeModal();
    };
    document.addEventListener("keydown", modal._escapeHandler);

    modal.addEventListener("click", event => {
        if (event.target === modal || event.target.closest("[data-close-device-action]")) {
            closeModal();
            return;
        }
        if (event.target.closest("[data-refresh-device-info]")) {
            void refreshConnectionInfo();
        }
    });

    if (action === "connect" || action === "monitor") {
        async function refreshConnectionInfo() {
            content.innerHTML = "<p>Refreshing connection information...</p>";
            try {
                const clients = await deviceApiRequest("/api/device-connection-clients");
                const matching = Array.isArray(clients)
                    ? clients.filter(client =>
                        String(client.device_name || "").toLowerCase() ===
                        String(device.name || "").toLowerCase()
                    )
                    : [];
                matching.sort((a, b) =>
                    String(b.connected_at || "").localeCompare(String(a.connected_at || ""))
                );
                const client = matching[0];
                const online = Boolean(client && client.connected);

                content.innerHTML = `
                    <div style="display:grid;gap:12px">
                        <div>
                            <div style="color:var(--muted);font-size:12px">Connection</div>
                            <strong>${online ? "Connected" : "Not connected"}</strong>
                        </div>
                        <div>
                            <div style="color:var(--muted);font-size:12px">Device status</div>
                            <strong>${esc(device.status || "Unknown")}</strong>
                        </div>
                        <div>
                            <div style="color:var(--muted);font-size:12px">Client IP</div>
                            <code>${esc(client?.client_ip || device.local_ip || device.ip || "Unknown")}</code>
                        </div>
                        <div>
                            <div style="color:var(--muted);font-size:12px">Last heartbeat</div>
                            <span>${esc(client?.last_seen || "No heartbeat received")}</span>
                        </div>
                        <div>
                            <div style="color:var(--muted);font-size:12px">Client state</div>
                            <span>${esc(client?.state || "No active client session")}</span>
                        </div>
                        <button type="button" class="secondary-button"
                                data-refresh-device-info>Refresh status</button>
                        ${action === "connect"
                            ? '<p>Transport-level client connection is shown here. Interactive remote desktop/control is not implemented yet.</p>'
                            : '<p>Connection and heartbeat information refresh automatically while this panel is open.</p>'}
                    </div>
                `;
            } catch (error) {
                content.innerHTML = `
                    <p>Could not load connection information: ${esc(error.message)}</p>
                    <button type="button" class="secondary-button"
                            data-refresh-device-info>Retry</button>
                `;
            }
        }

        await refreshConnectionInfo();
        if (action === "monitor") {
            modal._refreshTimer = setInterval(() => {
                if (document.body.contains(modal)) void refreshConnectionInfo();
            }, 5000);
        }
        return;
    }

    function showTaskForm(packageOptions = "") {
        const forms = {
            package: `
                <p>Select an active package from the Software catalog.</p>
                <label class="device-form-field" style="display:grid;gap:8px">
                    <span class="device-form-label">Software package</span>
                    <select name="software_id" required style="padding:10px">
                        <option value="">Select a package</option>
                        ${packageOptions}
                    </select>
                </label>
            `,
            shutdown: `
                <p>Schedule shutdown on the selected device. The countdown starts when its CartmanClient receives the task.</p>
                <label class="device-form-field" style="display:grid;gap:8px;margin-top:14px">
                    <span class="device-form-label">Shutdown countdown (seconds)</span>
                    <input type="number" name="delay_seconds" min="1" max="86400"
                           step="1" value="10" required style="padding:10px">
                    <span style="color:var(--muted);font-size:12px">Allowed range: 1 second to 24 hours.</span>
                </label>
                <label style="display:flex;align-items:flex-start;gap:10px;margin-top:16px">
                    <input type="checkbox" name="confirmed" required>
                    <span>I confirm that this device may be shut down.</span>
                </label>
            `,
            network: `
                <p>This will queue a network-disconnect task. The selected interface/service will be disabled 15 seconds after the agent receives it. Remote access may be lost.</p>
                <label class="device-form-field" style="display:grid;gap:8px;margin-top:14px">
                    <span class="device-form-label">Exact network interface / service name</span>
                    <input name="interface_name" required maxlength="150"
                           placeholder="For macOS, e.g. Wi-Fi" style="padding:10px">
                </label>
                <label style="display:flex;align-items:flex-start;gap:10px;margin-top:16px">
                    <input type="checkbox" name="confirmed" required>
                    <span>I confirm that this network interface/service may be disabled.</span>
                </label>
            `,
            "self-test": `
                <p>This safe test verifies that Cartman can deliver a task to the agent and receive its result. It does not run shell commands or change device settings.</p>
            `,
            vpn: `
                <label class="device-form-field" style="display:grid;gap:8px;margin-bottom:14px">
                    <span class="device-form-label">Action</span>
                    <select name="mode" required style="padding:10px">
                        <option value="connect">Connect VPN</option>
                        <option value="disconnect">Disconnect VPN</option>
                    </select>
                </label>
                <label class="device-form-field" style="display:grid;gap:8px">
                    <span class="device-form-label">Configured VPN profile name</span>
                    <input name="profile_name" required maxlength="150"
                           placeholder="Enter an existing profile name" style="padding:10px">
                </label>
            `
        };

        content.innerHTML = `
            <form data-device-task-form style="margin-top:18px">
                ${forms[action] || ""}
                <p style="margin-top:18px;color:var(--muted);font-size:12px">
                    Tasks are sent to approved, connected CartmanClients only when task execution is enabled. This panel shows the task status and result.
                </p>
                <button type="submit" class="primary-button">Queue task</button>
            </form>
            <p data-device-task-result role="status" style="margin-top:12px"></p>
        `;

        const form = content.querySelector("[data-device-task-form]");
        form.addEventListener("submit", async event => {
            event.preventDefault();

            const resultBox = content.querySelector("[data-device-task-result]");
            const submit = form.querySelector('button[type="submit"]');
            if (!form.reportValidity()) return;

            const payload = {};
            if (action === "package") {
                payload.software_id = content.querySelector('[name="software_id"]').value;
            } else if (action === "shutdown") {
                payload.confirmed = content.querySelector('[name="confirmed"]').checked;
                payload.delay_seconds = Number(
                    content.querySelector('[name="delay_seconds"]').value
                );
            } else if (action === "network") {
                payload.confirmed = content.querySelector('[name="confirmed"]').checked;
                payload.interface_name = content.querySelector('[name="interface_name"]').value.trim();
            } else if (action === "vpn") {
                payload.mode = content.querySelector('[name="mode"]').value;
                payload.profile_name = content.querySelector('[name="profile_name"]').value.trim();
            }

            submit.disabled = true;
            resultBox.textContent = "Saving task...";
            try {
                const result = await deviceApiRequest(
                    `/api/devices/${encodeURIComponent(device.id)}/tasks`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            action: actionNames[action],
                            payload
                        })
                    }
                );

                resultBox.textContent = `Task ${result.status || "Queued"}: ${result.message || "Saved to queue."}`;
                submit.textContent = "Task queued";
                submit.disabled = true;

                let latestStatus = result.status || "Queued";
                for (let attempt = 0; attempt < 90; attempt++) {
                    if (!document.body.contains(modal)) break;
                    await new Promise(resolve => setTimeout(resolve, 2000));

                    try {
                        const taskList = await deviceApiRequest(
                            `/api/devices/${encodeURIComponent(device.id)}/tasks`
                        );
                        const current = Array.isArray(taskList)
                            ? taskList.find(item => item.id === result.id)
                            : null;

                        if (!current) continue;

                        latestStatus = current.status || latestStatus;
                        const detail = String(current.result || "").trim();

                        resultBox.textContent = detail
                            ? `Task ${latestStatus}: ${detail.slice(0, 1600)}`
                            : `Task ${latestStatus}${latestStatus === "Queued" || latestStatus === "Running" ? " — waiting for client result..." : ""}`;

                        if (["Succeeded", "Failed", "Cancelled"].includes(latestStatus)) {
                            break;
                        }
                    } catch (pollError) {
                        resultBox.textContent =
                            `Task was queued, but its status could not be refreshed: ${pollError.message}`;
                        break;
                    }
                }

                if (document.body.contains(modal) &&
                    ["Queued", "Running", "Dispatched"].includes(latestStatus)) {
                    resultBox.textContent += " Still processing; check again shortly.";
                }
            } catch (error) {
                resultBox.textContent = `Could not queue task: ${error.message}`;
                submit.disabled = false;
            }
        });
    }

    if (action === "package") {
        try {
            const catalog = await deviceApiRequest("/api/software");
            const packages = Array.isArray(catalog)
                ? catalog
                : (catalog.items || catalog.software || []);
            const activePackages = packages.filter(item =>
                String(item.status || "").toLowerCase() === "active"
            );
            const options = activePackages.map(item =>
                `<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.version || "Unknown version")}</option>`
            ).join("");

            showTaskForm(options);
            if (!activePackages.length) {
                content.insertAdjacentHTML(
                    "afterbegin",
                    "<p>No active software packages found. Add an active package with an install command to the Software catalog first.</p>"
                );
            }
        } catch (error) {
            content.innerHTML = `<p>Could not load Software catalog: ${esc(error.message)}</p>`;
        }
    } else {
        showTaskForm();
    }
}

function openDeviceModal(device = null) {
    const editing = Boolean(device);
    deviceViewState.editingId = device?.id || null;
    const currentAssignedUser = device ? (device.assignedUser || getDeviceEnhancedData().find(item => item.id === device.id)?.assignedUser) : null;

    $("#devices-modal-backdrop")?.remove();

    const selectedTags = new Set(device?.tags || []);
    const tags = getDeviceTags();

    const tagOptions = tags.map(tag => `
        <label class="device-tag-option">
            <input
                type="checkbox"
                name="device-tags"
                value="${escapeDeviceHTML(tag)}"
                ${selectedTags.has(tag) ? "checked" : ""}
            >
            <span>${escapeDeviceHTML(tag)}</span>
        </label>
    `).join("");

    const backdrop = document.createElement("div");
    backdrop.id = "devices-modal-backdrop";
    backdrop.className = "devices-modal-backdrop";

    backdrop.innerHTML = `
        <section
            class="devices-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="device-modal-title"
        >
            <header class="devices-modal-header">
                <div>
                    <h2 id="device-modal-title">${editing ? "Edit device" : "Add device"}</h2>
                    <p>Update the demo inventory entry.</p>
                </div>
                <button
                    type="button"
                    class="device-action-button"
                    data-device-action="close-modal"
                    aria-label="Close dialog"
                >×</button>
            </header>

            <form id="device-form">
                ${!editing ? `
                <div class="device-connect-tabs" role="tablist" aria-label="Device registration method">
                    <button type="button" class="device-connect-tab is-active" role="tab"
                        aria-selected="true" data-device-tab="manual">Manual</button>
                    <button type="button" class="device-connect-tab" role="tab"
                        aria-selected="false" data-device-tab="auto">Auto Connect</button>
                </div>
                <section class="device-connect-panel" data-device-panel="manual">
                ` : ""}
                <div class="devices-modal-body">
                    ${!editing ? `
                    <div class="device-form-field">
                        <label for="device-public-ip">Public IPv4</label>
                        <input id="device-public-ip" name="public_ip" maxlength="100"
                            placeholder="e.g. 203.0.113.20" value="">
                    </div>
                    <div class="device-form-field">
                        <label for="device-local-ip">Local IPv4</label>
                        <input id="device-local-ip" name="local_ip" maxlength="100"
                            placeholder="e.g. 192.168.1.60" value="">
                    </div>
                    <div class="device-form-field">
                        <label for="device-username">Username</label>
                        <input id="device-username" name="username" maxlength="150"
                            autocomplete="off" placeholder="e.g. kaan">
                    </div>
                    ` : ""}
                    <div class="device-form-field">
                        <label for="device-name">Device name *</label>
                        <input
                            id="device-name"
                            name="name"
                            required
                            maxlength="100"
                            autocomplete="off"
                            placeholder="e.g. SRV-APP01"
                            value="${escapeDeviceHTML(device?.name || "")}"
                        >
                    </div>

                    <div class="device-form-grid">
                        <div class="device-form-field">
                            <label for="device-os">Operating system *</label>
                            <input
                                id="device-os"
                                name="os"
                                required
                                maxlength="100"
                                placeholder="e.g. Ubuntu Server 24.04"
                                value="${escapeDeviceHTML(device?.os || "")}"
                            >
                        </div>

                        ${editing ? `
                        <div class="device-form-field">
                            <label for="device-ip">IP address</label>
                            <input
                                id="device-ip"
                                name="ip"
                                maxlength="100"
                                placeholder="e.g. 192.168.1.60"
                                value="${escapeDeviceHTML(device?.ip || "")}"
                            >
                        </div>
                        ` : ""}
                    </div>

                    <div class="device-form-field">
                        <label for="device-status">Status</label>
                        <select id="device-status" name="status">
                            ${["Online", "Warning", "Offline"].map(status => `
                                <option
                                    value="${status}"
                                    ${(device?.status || "Online") === status ? "selected" : ""}
                                >${status}</option>
                            `).join("")}
                        </select>
                    </div>
                    <div class="device-form-field">
                        <label for="device-assigned-user">Assigned to</label>
                        <select id="device-assigned-user" name="assignedUser">
                            <option value="" ${!currentAssignedUser || currentAssignedUser.name === "Unassigned" ? "selected" : ""}>Unassigned</option>
                            <option value="Alex Morgan|amorgan" ${currentAssignedUser?.name === "Alex Morgan" ? "selected" : ""}>Alex Morgan (@amorgan)</option>
                            <option value="Sarah Chen|schen" ${currentAssignedUser?.name === "Sarah Chen" ? "selected" : ""}>Sarah Chen (@schen)</option>
                            <option value="Jordan Lee|jlee" ${currentAssignedUser?.name === "Jordan Lee" ? "selected" : ""}>Jordan Lee (@jlee)</option>
                        </select>
                    </div>


                    <div class="device-form-field">
                        <span class="device-form-label">Tags</span>
                        <div class="device-form-tags" id="device-form-tags">
                            ${tagOptions}
                        </div>
                        <div class="device-custom-tag-row">
                            <input
                                id="device-new-tag"
                                maxlength="40"
                                placeholder="Create a custom tag..."
                            >
                            <button
                                type="button"
                                class="secondary-button"
                                data-device-action="add-tag-from-form"
                            >＋ Add tag</button>
                        </div>
                    </div>
                </div>
                ${!editing ? `
                </section>
                <section class="device-connect-panel device-connect-panel-auto" data-device-panel="auto" hidden>
                    <div class="device-connect-card">
                        <div class="device-connect-heading">Automatic device discovery</div>
                        <p>When you are ready, press Start Listening below. Then open CartmanClient on the device you want to connect, enter the Server IP and Port shown here, and select Connect.</p>
                        
                        <label class="device-connect-label" for="device-connect-ip-mode">Address to display</label>
                        <select id="device-connect-ip-mode">
                            <option value="local">Local IP</option>
                            <option value="public">Public IP (display only)</option>
                        </select>
                        <div class="device-connect-address-row">
                            <span>Connection address</span>
                            <code id="device-connect-address">Detecting address...</code>
                        </div>
                        <div class="device-connect-status-row">
                            <span>Listener status</span>
                            <strong id="device-connect-status-value">Stopped</strong>
                        </div>
                        <div class="device-connect-port">Port <strong>50101</strong></div>
                        <button type="button" class="secondary-button"
                            data-device-action="toggle-device-listener">Start Listening</button>
                        <p class="device-connect-notice">Stopped. Press Start Listening to accept CartmanClient connections.</p>

                    </div>
                    <div class="device-connect-requests">
                        <h3>Connection requests</h3>
                        <p>No pending requests.</p>
                    </div>
                </section>
                ` : ""}

                <footer class="devices-modal-footer">
                    <button
                        type="button"
                        class="secondary-button"
                        data-device-action="close-modal"
                    >Cancel</button>
                    <button type="submit" class="primary-button">
                        ${editing ? "Save changes" : "Add device"}
                    </button>
                </footer>
            </form>
        </section>
    `;

    document.body.appendChild(backdrop);
    void refreshDeviceListenerStatus();
    $("#device-name")?.focus();
}

function addCustomDeviceTag() {
    const input = $("#device-new-tag");
    if (!input) return;

    const tag = input.value.trim();

    if (!tag) {
        input.focus();
        return;
    }

    const tags = getDeviceTags();

    if (tags.some(existing => existing.toLowerCase() === tag.toLowerCase())) {
        notify("That tag already exists.");
        input.focus();
        return;
    }

    tags.push(tag);
    if (!saveDeviceTags(tags)) return;

    const container = $("#device-form-tags");

    if (container) {
        const label = document.createElement("label");
        label.className = "device-tag-option";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.name = "device-tags";
        checkbox.value = tag;
        checkbox.checked = true;

        const span = document.createElement("span");
        span.textContent = tag;

        label.append(checkbox, span);
        container.appendChild(label);
    }

    input.value = "";
    input.focus();
}

async function saveDeviceForm(event) {
    event.preventDefault();

    const form = $("#device-form");
    if (!form || !form.reportValidity()) return;

    const formData = new FormData(form);
    const name = String(formData.get("name") || "").trim();
    const os = String(formData.get("os") || "").trim();
    const ip = String(formData.get("ip") || "").trim();
    const public_ip = String(formData.get("public_ip") || "").trim();
    const local_ip = String(formData.get("local_ip") || "").trim();
    const username = String(formData.get("username") || "").trim();
    const status = String(formData.get("status") || "Online");
    const tags = $$('input[name="device-tags"]:checked', form)
        .map(input => input.value);

    if (!name || !os) {
        notify("Device name and operating system are required.");
        return;
    }

    const editingId = deviceViewState.editingId;
    const payload = { name, os, ip, public_ip, local_ip, username, status, tags };
    const submit = form.querySelector('[type="submit"]');
    if (submit) submit.disabled = true;

    try {
        await deviceApiRequest(
            editingId
                ? `/api/devices/${encodeURIComponent(editingId)}`
                : "/api/devices",
            {
                method: editingId ? "PUT" : "POST",
                body: JSON.stringify(payload)
            }
        );

        await loadDeviceDataFromAPI(true);
        $("#devices-modal-backdrop")?.remove();
        deviceViewState.editingId = null;
        renderDevicesModule();

        window.dispatchEvent(new CustomEvent("cartman:devices-updated", {
            detail: { action: editingId ? "update" : "create" }
        }));

        notify(editingId ? "Device updated." : "Device added.");
    } catch (error) {
        console.error("Device save failed:", error);
        notify(`Could not save device: ${error.message}`);
    } finally {
        if (submit?.isConnected) submit.disabled = false;
    }
}

async function deleteDevice(id) {
    const device = getDeviceData().find(item => item.id === id);
    if (!device) return;

    if (!window.confirm(`Delete "${device.name}" from Cartman inventory?`)) {
        return;
    }

    try {
        await deviceApiRequest(`/api/devices/${encodeURIComponent(id)}`, {
            method: "DELETE"
        });

        await loadDeviceDataFromAPI(true);
        deviceViewState.selected = deviceViewState.selected.map(String).filter(item => item !== String(id));
        renderDevicesModule();

        window.dispatchEvent(new CustomEvent("cartman:devices-updated", {
            detail: { action: "delete", id }
        }));

        notify("Device deleted from Cartman inventory.");
    } catch (error) {
        console.error("Device deletion failed:", error);
        notify(`Could not delete device: ${error.message}`);
    }
}

function resetDeviceDemoData() {
    notify("Demo reset is disabled for API-backed inventory. Delete or import devices explicitly.");
}

function openManageDeviceTags() {
    $("#devices-modal-backdrop")?.remove();

    const backdrop = document.createElement("div");
    backdrop.id = "devices-modal-backdrop";
    backdrop.className = "devices-modal-backdrop";

    backdrop.innerHTML = `
        <section
            class="devices-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="device-tags-title"
        >
            <header class="devices-modal-header">
                <div>
                    <h2 id="device-tags-title">Manage tags</h2>
                    <p>Organize devices by type, environment or priority.</p>
                </div>
                <button
                    type="button"
                    class="device-action-button"
                    data-device-action="close-modal"
                    aria-label="Close dialog"
                >×</button>
            </header>

            <div class="devices-modal-body">
                <div class="device-custom-tag-row">
                    <input
                        id="manage-new-device-tag"
                        maxlength="40"
                        placeholder="Enter a new tag..."
                    >
                    <button
                        type="button"
                        class="primary-button"
                        data-device-action="create-managed-tag"
                    >Add tag</button>
                </div>

                <div class="devices-manage-tags">
                    ${getDeviceTags().map(tag => {
                        const inUse = getDeviceData().some(device =>
                            device.tags.includes(tag)
                        );

                        return `
                            <div class="devices-manage-tag-row">
                                <span>${escapeDeviceHTML(tag)}</span>
                                <button
                                    type="button"
                                    class="device-action-button delete"
                                    data-device-action="delete-tag"
                                    data-device-tag="${escapeDeviceHTML(tag)}"
                                    ${inUse ? "disabled title='This tag is assigned to a device'" : ""}
                                    aria-label="Delete ${escapeDeviceHTML(tag)}"
                                >×</button>
                            </div>
                        `;
                    }).join("")}
                </div>
            </div>

            <footer class="devices-modal-footer">
                <button
                    type="button"
                    class="secondary-button"
                    data-device-action="close-modal"
                >Close</button>
            </footer>
        </section>
    `;

    document.body.appendChild(backdrop);
}

function createManagedDeviceTag() {
    const input = $("#manage-new-device-tag");
    if (!input) return;

    const tag = input.value.trim();

    if (!tag) {
        input.focus();
        return;
    }

    const tags = getDeviceTags();

    if (tags.some(existing => existing.toLowerCase() === tag.toLowerCase())) {
        notify("That tag already exists.");
        input.focus();
        return;
    }

    tags.push(tag);
    if (!saveDeviceTags(tags)) return;

    openManageDeviceTags();
    notify("Tag created.");
}

function deleteManagedDeviceTag(tag) {
    if (DEFAULT_DEVICE_TAGS.includes(tag)) {
        notify("Default tags cannot be deleted.");
        return;
    }

    if (getDeviceData().some(device => device.tags.includes(tag))) {
        notify("Remove this tag from its devices before deleting it.");
        return;
    }

    if (!saveDeviceTags(getDeviceTags().filter(item => item !== tag))) return;

    openManageDeviceTags();
    renderDevicesModule();
    notify("Tag deleted.");
}
