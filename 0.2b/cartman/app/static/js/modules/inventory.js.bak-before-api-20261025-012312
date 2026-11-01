"use strict";

/* CARTMAN INVENTORY — browser-local asset management */
const INVENTORY_STORAGE_KEY = "cartman-inventory-assets-v1";

try {
    if (localStorage.getItem("cartman-theme") === "light") {
        document.body.classList.add("light-theme");
    }
} catch (_) {}

const inventorySearch = document.getElementById("inventory-search");
const inventoryBody = document.getElementById("inventory-table-body");
const inventoryCount = document.getElementById("inventory-row-count");
const inventoryEmpty = document.getElementById("inventory-empty");
const inventoryModal = document.getElementById("inventory-modal-backdrop");
const inventoryForm = document.getElementById("inventory-asset-form");
const inventoryFile = document.getElementById("inventory-json-file");
const inventorySortBy = document.getElementById("inventory-sort-by");

const inventoryFilterDepartment = document.getElementById("inventory-filter-department");
const inventoryFilterType = document.getElementById("inventory-filter-type");
const inventoryFilterAssigned = document.getElementById("inventory-filter-assigned");
const inventoryFilterDateFrom = document.getElementById("inventory-filter-date-from");
const inventoryFilterDateTo = document.getElementById("inventory-filter-date-to");
const inventoryClearFilters = document.getElementById("inventory-clear-filters");

let editingAssetId = null;
let inventorySelectedIds = new Set();

function inventoryEscape(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;"
    })[character]);
}

function inventoryLoad() {
    try {
        const value = localStorage.getItem(INVENTORY_STORAGE_KEY);
        if (value === null) return [];
        const parsed = JSON.parse(value);
        if (!Array.isArray(parsed)) throw new Error("Expected an array of assets");
        return parsed.filter(asset =>
            asset && typeof asset.id === "string" &&
            typeof asset.name === "string"
        ).map(asset => ({
            id: asset.id,
            name: String(asset.name || ""),
            type: String(asset.type || ""),
            brand: String(asset.brand || ""),
            purchaseDate: String(asset.purchaseDate || ""),
            serialNo: String(asset.serialNo || ""),
            department: String(asset.department || ""),
            assignedTo: String(asset.assignedTo || ""),
            tags: Array.isArray(asset.tags)
                ? asset.tags.map(String)
                : String(asset.tags || "").split(",").map(tag => tag.trim()).filter(Boolean),
            specialNotes: String(asset.specialNotes || "")
        }));
    } catch (error) {
        console.error("Could not load Inventory assets:", error);
        alert("Inventory data could not be read. Your stored data has not been overwritten.");
        return [];
    }
}

function inventorySave(assets) {
    try {
        localStorage.setItem(INVENTORY_STORAGE_KEY, JSON.stringify(assets));
        return true;
    } catch (error) {
        console.error("Could not save Inventory assets:", error);
        alert("Assets could not be saved in this browser. Check available storage.");
        return false;
    }
}

function inventoryAssetIcon(type) {
    const value = String(type || "").toLocaleLowerCase();

    if (/server|workstation|desktop|laptop|computer/.test(value)) return "🖥️";
    if (/monitor|display|screen/.test(value)) return "🖥️";
    if (/printer|scanner|projector/.test(value)) return "🖨️";
    if (/switch|router|firewall|access point|network|load balancer/.test(value)) return "🌐";
    if (/keyboard/.test(value)) return "⌨️";
    if (/mouse/.test(value)) return "🖱️";
    if (/headset|headphone|speaker/.test(value)) return "🎧";
    if (/ups|pdu|power supply/.test(value)) return "🔋";
    if (/nas|san|storage|ssd|hdd|drive/.test(value)) return "💾";
    if (/ram|memory|cpu|processor|motherboard|graphics|component/.test(value)) return "🔧";
    if (/rack|kvm/.test(value)) return "🗄️";
    if (/camera|security|cctv/.test(value)) return "📷";
    if (/cable|adapter|transceiver|spare/.test(value)) return "🔌";
    if (/webcam/.test(value)) return "📹";
    return "📦";
}

function inventoryUpdateSelect(select, values, placeholder, includeUnassigned = false) {
    if (!select) return;

    const current = select.value;
    const unique = [...new Set(values.map(value => String(value || "").trim()).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }));

    select.replaceChildren();

    const first = document.createElement("option");
    first.value = "";
    first.textContent = placeholder;
    select.appendChild(first);

    if (includeUnassigned) {
        const unassigned = document.createElement("option");
        unassigned.value = "__unassigned__";
        unassigned.textContent = "Unassigned";
        select.appendChild(unassigned);
    }

    unique.forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
    });

    select.value = current;
}

function inventoryRender() {
    if (!inventoryBody) return;

    const assets = inventoryLoad();

    inventoryUpdateSelect(
        inventoryFilterDepartment,
        assets.map(asset => asset.department),
        "All departments"
    );
    inventoryUpdateSelect(
        inventoryFilterType,
        assets.map(asset => asset.type),
        "All types"
    );
    inventoryUpdateSelect(
        inventoryFilterAssigned,
        assets.map(asset => asset.assignedTo),
        "All assignees",
        true
    );

    const query = (inventorySearch?.value || "").trim().toLocaleLowerCase();
    const department = inventoryFilterDepartment?.value || "";
    const type = inventoryFilterType?.value || "";
    const assigned = inventoryFilterAssigned?.value || "";
    const dateFrom = inventoryFilterDateFrom?.value || "";
    const dateTo = inventoryFilterDateTo?.value || "";

    const searched = assets.filter(asset => [
        asset.name, asset.type, asset.brand, asset.purchaseDate,
        asset.serialNo, asset.department, asset.assignedTo,
        asset.tags.join(" "), asset.specialNotes
    ].join(" ").toLocaleLowerCase().includes(query));

    const filtered = searched.filter(asset => {
        if (department && asset.department !== department) return false;
        if (type && asset.type !== type) return false;

        if (assigned === "__unassigned__" && asset.assignedTo.trim()) return false;
        if (assigned && assigned !== "__unassigned__" && asset.assignedTo !== assigned) return false;

        if (dateFrom && (!asset.purchaseDate || asset.purchaseDate < dateFrom)) return false;
        if (dateTo && (!asset.purchaseDate || asset.purchaseDate > dateTo)) return false;

        return true;
    });

    const compareText = (a, b, key) =>
        String(a[key] || "").localeCompare(String(b[key] || ""), undefined, {
            sensitivity: "base",
            numeric: true
        });

    const sorters = {
        newest: (a, b) => compareText(b, a, "purchaseDate"),
        oldest: (a, b) => compareText(a, b, "purchaseDate"),
        department: (a, b) => compareText(a, b, "department"),
        type: (a, b) => compareText(a, b, "type"),
        serialNo: (a, b) => compareText(a, b, "serialNo")
    };

    filtered.sort(sorters[inventorySortBy?.value] || sorters.newest);

    inventorySelectedIds = new Set([...inventorySelectedIds].filter(id =>
        assets.some(asset => asset.id === id)
    ));

    const selectAll = document.getElementById("inventory-select-visible");
    if (selectAll) {
        selectAll.checked = filtered.length > 0 &&
            filtered.every(asset => inventorySelectedIds.has(asset.id));
        selectAll.indeterminate = filtered.some(asset => inventorySelectedIds.has(asset.id)) &&
            !selectAll.checked;
    }

    const selectedCount = document.getElementById("inventory-selected-count");
    if (selectedCount) selectedCount.textContent = `${inventorySelectedIds.size} selected`;

    const deleteSelected = document.getElementById("inventory-delete-selected");
    const exportSelected = document.getElementById("inventory-export-selected");
    if (deleteSelected) deleteSelected.disabled = inventorySelectedIds.size === 0;
    if (exportSelected) exportSelected.disabled = inventorySelectedIds.size === 0;

    inventoryBody.innerHTML = filtered.map(asset => `
        <tr>
            <td><input type="checkbox" class="inventory-select" data-inventory-select="${inventoryEscape(asset.id)}" aria-label="Select ${inventoryEscape(asset.name)}" ${inventorySelectedIds.has(asset.id) ? "checked" : ""}></td>
            <td>
                <div class="inventory-asset-cell">
                    <span class="inventory-asset-icon" aria-hidden="true">${inventoryAssetIcon(asset.type)}</span>
                    <span class="inventory-asset-name">${inventoryEscape(asset.name)}</span>
                </div>
            </td>
            <td>${inventoryEscape(asset.type || "—")}</td>
            <td>${inventoryEscape(asset.brand || "—")}</td>
            <td>${inventoryEscape(asset.purchaseDate || "—")}</td>
            <td>${inventoryEscape(asset.serialNo || "—")}</td>
            <td>${inventoryEscape(asset.department || "—")}</td>
            <td>${inventoryEscape(asset.assignedTo || "Unassigned")}</td>
            <td><div class="inventory-tags">${asset.tags.length
                ? asset.tags.map(tag => `<span class="inventory-tag">${inventoryEscape(tag)}</span>`).join("")
                : '<span class="inventory-muted">—</span>'}</div></td>
            <td>${inventoryEscape(asset.specialNotes || "—")}</td>
            <td>
                <div class="inventory-row-actions">
                    <button type="button" class="inventory-action-btn"
                            data-inventory-edit="${inventoryEscape(asset.id)}">Edit</button>
                    <button type="button" class="inventory-action-btn danger"
                            data-inventory-delete="${inventoryEscape(asset.id)}">Delete</button>
                </div>
            </td>
        </tr>
    `).join("");

    inventoryCount.textContent = `Showing ${filtered.length} of ${assets.length} asset(s)`;

    inventoryEmpty.classList.toggle("inventory-hidden", filtered.length > 0);
    inventoryEmpty.textContent = assets.length === 0
        ? "No assets yet. Select Add Asset to register equipment."
        : filtered.length === 0
            ? "No assets match your search or filters."
            : "";
}
function inventoryOpenModal(asset = null) {
    editingAssetId = asset?.id || null;
    inventoryForm.reset();

    document.getElementById("inventory-modal-title").textContent =
        asset ? "Edit Asset" : "Add Asset";

    const fields = {
        name: "asset-name",
        type: "asset-type",
        brand: "asset-brand",
        purchaseDate: "asset-purchase-date",
        serialNo: "asset-serial",
        department: "asset-department",
        assignedTo: "asset-assigned-to",
        specialNotes: "asset-notes"
    };

    if (asset) {
        Object.entries(fields).forEach(([key, id]) => {
            document.getElementById(id).value = asset[key] || "";
        });
        document.getElementById("asset-tags").value = asset.tags.join(", ");
    }

    inventoryModal.classList.remove("inventory-hidden");
    document.getElementById("asset-name").focus();
}

function inventoryCloseModal() {
    inventoryModal.classList.add("inventory-hidden");
    editingAssetId = null;
    inventoryForm.reset();
}

document.getElementById("inventory-add-btn").addEventListener("click", () => {
    inventoryOpenModal();
});

document.getElementById("inventory-close-x").addEventListener("click", inventoryCloseModal);
document.getElementById("inventory-cancel-btn").addEventListener("click", inventoryCloseModal);

inventoryModal.addEventListener("click", event => {
    if (event.target === inventoryModal) inventoryCloseModal();
});

inventorySearch.addEventListener("input", inventoryRender);

[
    inventorySortBy,
    inventoryFilterDepartment,
    inventoryFilterType,
    inventoryFilterAssigned,
    inventoryFilterDateFrom,
    inventoryFilterDateTo
].forEach(control => control?.addEventListener("change", inventoryRender));

inventoryClearFilters.addEventListener("click", () => {
    inventorySearch.value = "";
    inventorySortBy.value = "newest";
    inventoryFilterDepartment.value = "";
    inventoryFilterType.value = "";
    inventoryFilterAssigned.value = "";
    inventoryFilterDateFrom.value = "";
    inventoryFilterDateTo.value = "";
    inventoryRender();
});

inventoryForm.addEventListener("submit", event => {
    event.preventDefault();

    const name = document.getElementById("asset-name").value.trim();
    const type = document.getElementById("asset-type").value;
    if (!name || !type) {
        alert("Name and Type are required.");
        return;
    }

    const assets = inventoryLoad();
    const serialNo = document.getElementById("asset-serial").value.trim();

    if (serialNo && assets.some(asset =>
        asset.serialNo.toLocaleLowerCase() === serialNo.toLocaleLowerCase() &&
        asset.id !== editingAssetId
    )) {
        alert("An asset with this serial number already exists.");
        return;
    }

    const asset = {
        id: editingAssetId || (crypto.randomUUID
            ? crypto.randomUUID()
            : `asset-${Date.now()}-${Math.random().toString(16).slice(2)}`),
        name,
        type,
        brand: document.getElementById("asset-brand").value.trim(),
        purchaseDate: document.getElementById("asset-purchase-date").value,
        serialNo,
        department: document.getElementById("asset-department").value.trim(),
        assignedTo: document.getElementById("asset-assigned-to").value.trim(),
        tags: [...new Set(document.getElementById("asset-tags").value
            .split(",").map(tag => tag.trim()).filter(Boolean))],
        specialNotes: document.getElementById("asset-notes").value.trim()
    };

    const index = assets.findIndex(item => item.id === editingAssetId);
    if (index >= 0) assets[index] = asset;
    else assets.unshift(asset);

    if (!inventorySave(assets)) return;
    inventoryCloseModal();
    inventoryRender();
});

document.getElementById("inventory-select-visible").addEventListener("change", event => {
    const visibleRows = [...inventoryBody.querySelectorAll("[data-inventory-select]")];
    visibleRows.forEach(input => {
        const id = input.dataset.inventorySelect;
        if (event.target.checked) inventorySelectedIds.add(id);
        else inventorySelectedIds.delete(id);
    });
    inventoryRender();
});

inventoryBody.addEventListener("change", event => {
    const input = event.target.closest("[data-inventory-select]");
    if (!input) return;
    if (input.checked) inventorySelectedIds.add(input.dataset.inventorySelect);
    else inventorySelectedIds.delete(input.dataset.inventorySelect);
    inventoryRender();
});

document.getElementById("inventory-delete-selected").addEventListener("click", () => {
    const ids = new Set(inventorySelectedIds);
    if (!ids.size) return;
    if (!confirm(`Delete ${ids.size} selected asset(s)? This cannot be undone.`)) return;

    const assets = inventoryLoad();
    const remaining = assets.filter(asset => !ids.has(asset.id));
    if (inventorySave(remaining)) {
        inventorySelectedIds.clear();
        inventoryRender();
    }
});

document.getElementById("inventory-export-selected").addEventListener("click", () => {
    const selected = inventoryLoad().filter(asset => inventorySelectedIds.has(asset.id));
    if (!selected.length) return;
    const blob = new Blob([JSON.stringify({
        version: 1,
        exportedAt: new Date().toISOString(),
        assets: selected
    }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "cartman-selected-assets.json";
    link.click();
    URL.revokeObjectURL(url);
});

inventoryBody.addEventListener("click", event => {
    const editButton = event.target.closest("[data-inventory-edit]");
    const deleteButton = event.target.closest("[data-inventory-delete]");

    if (editButton) {
        const asset = inventoryLoad().find(item => item.id === editButton.dataset.inventoryEdit);
        if (asset) inventoryOpenModal(asset);
        return;
    }

    if (deleteButton) {
        const id = deleteButton.dataset.inventoryDelete;
        const asset = inventoryLoad().find(item => item.id === id);
        if (!asset) return;
        if (!confirm(`Delete "${asset.name}"? This cannot be undone.`)) return;
        const assets = inventoryLoad().filter(item => item.id !== id);
        if (inventorySave(assets)) inventoryRender();
    }
});

document.getElementById("inventory-export-btn").addEventListener("click", () => {
    const payload = {
        version: 1,
        exportedAt: new Date().toISOString(),
        assets: inventoryLoad()
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json"
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "cartman-inventory.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
});

document.getElementById("inventory-import-btn").addEventListener("click", () => {
    inventoryFile.click();
});

inventoryFile.addEventListener("change", async () => {
    const file = inventoryFile.files?.[0];
    if (!file) return;

    try {
        const parsed = JSON.parse(await file.text());
        const imported = Array.isArray(parsed) ? parsed : parsed.assets;

        if (!Array.isArray(imported)) {
            throw new Error('JSON must contain an array or an "assets" array.');
        }

        if (imported.length > 5000) {
            throw new Error("Maximum 5000 assets per import.");
        }

        const normalized = imported.map((asset, index) => {
            if (!asset || typeof asset !== "object" ||
                typeof asset.name !== "string" || !asset.name.trim()) {
                throw new Error(`Asset ${index + 1} has no valid name.`);
            }

            const tags = Array.isArray(asset.tags)
                ? asset.tags.map(String)
                : String(asset.tags || "").split(",").map(tag => tag.trim()).filter(Boolean);

            return {
                id: typeof asset.id === "string" && asset.id
                    ? asset.id
                    : `asset-${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,
                name: asset.name.trim(),
                type: String(asset.type || "Other"),
                brand: String(asset.brand || ""),
                purchaseDate: String(asset.purchaseDate || ""),
                serialNo: String(asset.serialNo || ""),
                department: String(asset.department || ""),
                assignedTo: String(asset.assignedTo || ""),
                tags,
                specialNotes: String(asset.specialNotes || "")
            };
        });

        const existing = inventoryLoad();
        const replace = confirm(
            "OK: Replace the current Inventory with the imported assets.\n" +
            "Cancel: Merge imported assets with the current Inventory."
        );

        const result = replace ? normalized : [...existing];
        if (!replace) {
            const knownIds = new Set(result.map(asset => asset.id));
            const knownSerials = new Set(result.map(asset => asset.serialNo)
                .filter(Boolean).map(value => value.toLocaleLowerCase()));

            normalized.forEach(asset => {
                if (knownIds.has(asset.id)) {
                    asset.id = `asset-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                }
                if (asset.serialNo && knownSerials.has(asset.serialNo.toLocaleLowerCase())) {
                    throw new Error(`Duplicate serial number in import: ${asset.serialNo}`);
                }
                knownIds.add(asset.id);
                if (asset.serialNo) knownSerials.add(asset.serialNo.toLocaleLowerCase());
                result.push(asset);
            });
        }

        if (inventorySave(result)) {
            inventoryRender();
            alert(`${normalized.length} asset(s) imported.`);
        }
    } catch (error) {
        console.error("Inventory import failed:", error);
        alert(`Import failed: ${error.message}`);
    } finally {
        inventoryFile.value = "";
    }
});

document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !inventoryModal.classList.contains("inventory-hidden")) {
        inventoryCloseModal();
    }
});

inventoryRender();
