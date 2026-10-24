"use strict";

(() => {
    const $ = selector => document.querySelector(selector);
    const body = $("#software-table-body");
    const search = $("#software-search");
    const statusFilter = $("#software-status-filter");
    const modal = $("#software-modal");
    const form = $("#software-form");
    const formError = $("#software-form-error");
    const message = $("#software-message");
    const operatorInput = $("#software-operator");
    const historyModal = $("#software-history-modal");
    const historyContent = $("#software-history-content");

    if (!body || !form || !modal || !historyModal || !historyContent) return;

    let records = [];
    let editingId = null;
    let busy = false;

    function operatorName() {
        return (operatorInput.value || "").trim() || "Unidentified operator";
    }

    try {
        operatorInput.value = localStorage.getItem("cartman-operator-name") || "";
    } catch (_) {}

    operatorInput.addEventListener("change", () => {
        try {
            localStorage.setItem("cartman-operator-name", operatorInput.value.trim());
        } catch (_) {}
    });

    const fields = [
        "name", "publisher", "version", "target_os", "category",
        "package_type", "status", "source_url", "install_command",
        "uninstall_command", "notes"
    ];

    function say(text, isError = false) {
        message.textContent = text;
        message.style.color = isError ? "#fca5a5" : "";
    }

    function cell(row, value) {
        const td = document.createElement("td");
        td.textContent = value || "—";
        row.appendChild(td);
        return td;
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {
                "X-Operator": operatorName(),
                ...(options.body ? {"Content-Type": "application/json"} : {}),
                ...(options.headers || {})
            }
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = data.detail;
            throw new Error(typeof detail === "string" ? detail : "Request failed (" + response.status + ")");
        }
        return data;
    }

    function render() {
        const query = (search.value || "").trim().toLocaleLowerCase();
        const status = statusFilter.value;
        const filtered = records.filter(item => {
            const searchable = [
                item.name, item.publisher, item.version, item.target_os,
                item.category, item.package_type, item.status
            ].join(" ").toLocaleLowerCase();
            return searchable.includes(query) && (!status || item.status === status);
        });

        $("#software-total").textContent = String(records.length);
        $("#software-active").textContent = String(records.filter(x => x.status === "Active").length);
        $("#software-draft").textContent = String(records.filter(x => x.status === "Draft").length);
        $("#software-row-count").textContent = filtered.length + " package(s)";
        $("#software-empty").classList.toggle("hidden", filtered.length !== 0);
        body.replaceChildren();

        if (!filtered.length) {
            const row = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 11;
            td.textContent = records.length ? "No matching software found." : "No software added yet.";
            row.appendChild(td);
            body.appendChild(row);
            return;
        }

        for (const item of filtered) {
            const row = document.createElement("tr");
            cell(row, item.name);
            cell(row, item.publisher);
            cell(row, item.version);
            cell(row, item.target_os);
            cell(row, item.package_type);

            const statusCell = document.createElement("td");
            const badge = document.createElement("span");
            badge.className = "software-status";
            badge.dataset.status = item.status;
            badge.textContent = item.status;
            statusCell.appendChild(badge);
            row.appendChild(statusCell);

            cell(row, item.created_by);
            cell(row, item.created_at);
            cell(row, item.updated_by);
            cell(row, item.updated_at);

            const actions = document.createElement("td");
            const wrap = document.createElement("div");
            wrap.className = "software-actions";
            const historyButton = document.createElement("button");
            historyButton.type = "button";
            historyButton.className = "software-action";
            historyButton.textContent = "History";
            historyButton.addEventListener("click", () => openHistory(item));



            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "software-action";
            edit.textContent = "Edit";
            edit.addEventListener("click", () => openEditor(item));

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "software-action";
            remove.textContent = "Delete";
            remove.addEventListener("click", () => deleteRecord(item));

            wrap.append(historyButton, edit, remove);
            actions.appendChild(wrap);
            row.appendChild(actions);
            body.appendChild(row);
        }
    }

    function formatAuditDetails(entry) {
        const details = entry.details || {};

        if (details.changes && typeof details.changes === "object") {
            const lines = Object.entries(details.changes).map(([field, change]) => {
                const oldValue = JSON.stringify(change.old ?? null);
                const newValue = JSON.stringify(change.new ?? null);
                return `${field}: ${oldValue} → ${newValue}`;
            });
            return lines.join("\n") || "No field changes recorded.";
        }

        if (details.values && typeof details.values === "object") {
            const hiddenFields = new Set([
                "id", "created_at", "updated_at", "created_by", "updated_by"
            ]);
            const lines = Object.entries(details.values)
                .filter(([field]) => !hiddenFields.has(field))
                .map(([field, value]) => `${field}: ${JSON.stringify(value)}`);
            return lines.join("\n") || "No details recorded.";
        }

        return JSON.stringify(details, null, 2);
    }

    async function openHistory(item = null) {
        const title = $("#software-history-title");
        title.textContent = item
            ? `History — ${item.name || "Software"}`
            : "Software audit history";

        historyContent.replaceChildren();
        historyContent.textContent = "Loading history...";
        historyModal.hidden = false;

        const params = new URLSearchParams({limit: "200"});
        if (item) params.set("software_id", item.id);

        try {
            const entries = await api("/api/software-audit?" + params.toString());
            historyContent.replaceChildren();

            if (!entries.length) {
                historyContent.textContent = "No history entries found.";
                return;
            }

            const table = document.createElement("table");
            table.className = "software-history-table";
            const thead = document.createElement("thead");
            const headerRow = document.createElement("tr");

            for (const label of ["Time", "Performed By", "Action", "Software", "Details"]) {
                const th = document.createElement("th");
                th.textContent = label;
                headerRow.appendChild(th);
            }

            thead.appendChild(headerRow);
            table.appendChild(thead);

            const tbody = document.createElement("tbody");
            for (const entry of entries) {
                const row = document.createElement("tr");
                const values = [
                    entry.occurred_at,
                    entry.actor,
                    entry.action,
                    entry.software_name
                ];

                for (const value of values) {
                    const td = document.createElement("td");
                    td.textContent = value || "—";
                    row.appendChild(td);
                }

                const detailsCell = document.createElement("td");
                detailsCell.className = "software-history-details";
                detailsCell.textContent = formatAuditDetails(entry);
                row.appendChild(detailsCell);
                tbody.appendChild(row);
            }

            table.appendChild(tbody);
            historyContent.appendChild(table);
        } catch (error) {
            historyContent.replaceChildren();
            historyContent.textContent = "Could not load history: " + error.message;
        }
    }

    function closeHistory() {
        historyModal.hidden = true;
    }



    async function load() {
        body.innerHTML = '<tr><td colspan="11">Loading software catalog...</td></tr>';
        try {
            records = await api("/api/software");
            render();
            say("Catalog loaded from SQLite.");
        } catch (error) {
            body.replaceChildren();
            const row = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 11;
            td.textContent = "Could not load catalog: " + error.message;
            row.appendChild(td);
            body.appendChild(row);
            say("Catalog load failed. Check the API and server logs.", true);
        }
    }

    function openEditor(item = null) {
        editingId = item ? item.id : null;
        form.reset();
        formError.textContent = "";
        $("#software-modal-title").textContent = item ? "Edit software" : "Add software";
        $("#software-save").textContent = item ? "Save changes" : "Save software";

        if (item) {
            for (const name of fields) {
                if (form.elements[name]) form.elements[name].value = item[name] ?? "";
            }
        } else {
            form.elements.version.value = "Unknown";
            form.elements.target_os.value = "Any";
            form.elements.category.value = "General";
            form.elements.package_type.value = "Other";
            form.elements.status.value = "Active";
        }

        modal.hidden = false;
        form.elements.name.focus();
    }

    function closeEditor() {
        modal.hidden = true;
        editingId = null;
    }

    async function deleteRecord(item) {
        if (!window.confirm(`Delete "${item.name}" ${item.version}? This cannot be undone.`)) return;

        try {
            await api("/api/software/" + encodeURIComponent(item.id), {method: "DELETE"});
            say("Software record deleted.");
            await load();
        } catch (error) {
            say(error.message, true);
        }
    }

    $("#software-add").addEventListener("click", () => openEditor());
    $("#software-history").addEventListener("click", () => openHistory());
    $("#software-history-close").addEventListener("click", closeHistory);
    historyModal.addEventListener("click", event => {
        if (event.target === historyModal) closeHistory();
    });
    $("#software-cancel").addEventListener("click", closeEditor);
    modal.addEventListener("click", event => {
        if (event.target === modal) closeEditor();
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            if (!historyModal.hidden) closeHistory();
            else if (!modal.hidden) closeEditor();
        }
    });
    search.addEventListener("input", render);
    statusFilter.addEventListener("change", render);

    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (busy) return;

        const payload = {};
        for (const name of fields) {
            payload[name] = String(form.elements[name].value || "").trim();
        }

        busy = true;
        $("#software-save").disabled = true;
        formError.textContent = "";

        try {
            await api(
                editingId
                    ? "/api/software/" + encodeURIComponent(editingId)
                    : "/api/software",
                {
                    method: editingId ? "PUT" : "POST",
                    body: JSON.stringify(payload)
                }
            );

            closeEditor();
            say(editingId ? "Software record updated." : "Software record added.");
            await load();
        } catch (error) {
            formError.textContent = error.message;
        } finally {
            busy = false;
            $("#software-save").disabled = false;
        }
    });

    load();
})();
