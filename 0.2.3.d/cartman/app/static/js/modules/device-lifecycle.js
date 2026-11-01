/* Cartman Device Lifecycle — inventory-backed UI. */
(() => {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector(".dl-page");
        if (!root) return;

        const $ = (selector, base = root) => base.querySelector(selector);
        const $$ = (selector, base = root) => [...base.querySelectorAll(selector)];

        const rows = $("[data-dl-rows]");
        const search = $("[data-dl-search]");
        const stageFilter = $("[data-dl-stage]");
        const reset = $("[data-dl-reset]");
        const refresh = $("[data-dl-refresh]");
        const empty = $("[data-dl-empty]");

        if (!rows || !search || !stageFilter || !reset || !empty) return;

        const API = "/api/device-lifecycle";
        const STAGES = ["Unspecified", "Planning", "Deployment", "Active", "Refresh", "Retired"];
        let records = [];
        let busy = false;

        const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        }[char]));

        const dateValue = (value) => {
            const match = String(value || "").match(/^\d{4}-\d{2}-\d{2}/);
            return match ? match[0] : "";
        };

        const formatDate = (value) => {
            const date = dateValue(value);
            if (!date) return "Not set";
            const [year, month, day] = date.split("-");
            return `${day}.${month}.${year}`;
        };

        const daysFromToday = (value) => {
            const date = dateValue(value);
            if (!date) return null;
            const target = new Date(`${date}T00:00:00`);
            const now = new Date();
            now.setHours(0, 0, 0, 0);
            return Math.round((target - now) / 86400000);
        };

        const stageName = (record) => {
            const value = String(record.lifecycleStage || record.stage || "Unspecified");
            return STAGES.includes(value) ? value : "Unspecified";
        };

        const setConnection = (connected, message) => {
            const connection = $("[data-dl-connection]");
            if (connection) {
                connection.innerHTML = `<span></span> ${escapeHtml(message)}`;
                connection.classList.toggle("is-online", connected);
                connection.classList.toggle("is-offline", !connected);
            }

            const hero = $("[data-dl-hero-status]");
            if (hero) {
                hero.innerHTML = `<i class="dl-dot"></i> ${connected
                    ? "Lifecycle data connected" : "Lifecycle data unavailable"}`;
            }

            const source = $("[data-dl-hero-source]");
            if (source) {
                source.textContent = connected
                    ? "Connected to Cartman inventory"
                    : "Check the API and try refreshing";
            }

            const note = $("[data-dl-connection-note]");
            if (note) {
                note.innerHTML = `<i></i> ${connected
                    ? "Inventory API connected" : "Unable to load lifecycle data"}`;
            }

            const footer = $("[data-dl-footer-status]");
            if (footer) {
                footer.textContent = connected
                    ? "Connected to Cartman inventory API"
                    : "API unavailable — retry with Refresh";
            }
        };

        async function request(url, options = {}) {
            const response = await fetch(url, {
                cache: "no-store",
                ...options,
                headers: {
                    Accept: "application/json",
                    ...(options.headers || {})
                }
            });

            const text = await response.text();
            let data = null;

            try {
                data = text ? JSON.parse(text) : null;
            } catch {
                data = null;
            }

            if (!response.ok) {
                const detail = data && (data.detail || data.message);
                throw new Error(detail ? String(detail) : `Request failed (${response.status})`);
            }

            return data;
        }

        const warrantyLabel = (record) => {
            const days = daysFromToday(record.warrantyEndDate);

            if (days === null) return { label: "Not set", style: "neutral" };
            if (days < 0) return { label: `Expired ${Math.abs(days)}d`, style: "danger" };
            if (days <= 90) {
                return {
                    label: days === 0 ? "Expires today" : `Expires in ${days}d`,
                    style: "warning"
                };
            }

            return {
                label: `Until ${formatDate(record.warrantyEndDate)}`,
                style: "success"
            };
        };

        const nextAction = (record) => {
            const stage = stageName(record);

            if (stage === "Retired") {
                return record.retirementDate
                    ? `Retired ${formatDate(record.retirementDate)}`
                    : "Retired · date not set";
            }

            if (record.refreshDueDate) {
                const days = daysFromToday(record.refreshDueDate);
                if (days !== null && days < 0) {
                    return `Refresh overdue · ${formatDate(record.refreshDueDate)}`;
                }
                return `Refresh · ${formatDate(record.refreshDueDate)}`;
            }

            if (record.retirementDate) {
                return `Retirement · ${formatDate(record.retirementDate)}`;
            }

            return "No action scheduled";
        };

        const rowHtml = (record) => {
            const id = String(record.id || "");
            const name = record.name || "Unnamed asset";
            const type = record.type || "Device";
            const brand = record.brand || "";
            const owner = record.assignedTo || "Unassigned";
            const serial = record.serialNo || "";
            const stage = stageName(record);
            const warranty = warrantyLabel(record);

            const searchText = [
                name, type, brand, owner, serial,
                record.department || "", stage,
                record.warrantyEndDate || "", record.refreshDueDate || ""
            ].join(" ");

            return `
                <tr data-asset-id="${escapeHtml(id)}"
                    data-lifecycle-stage="${escapeHtml(stage.toLowerCase())}"
                    data-search-text="${escapeHtml(searchText)}">
                    <td>
                        <div class="dl-asset-name">${escapeHtml(name)}</div>
                        <div class="dl-cell-muted">${escapeHtml(
                            serial ? `S/N ${serial}` : record.department || "No serial number"
                        )}</div>
                    </td>
                    <td>
                        <div>${escapeHtml([brand, type].filter(Boolean).join(" · "))}</div>
                        <div class="dl-cell-muted">${escapeHtml(owner)}</div>
                    </td>
                    <td>
                        <span class="dl-stage-chip dl-stage-${escapeHtml(stage.toLowerCase())}">
                            ${escapeHtml(stage)}
                        </span>
                    </td>
                    <td>
                        <span class="dl-date-chip dl-date-${warranty.style}">
                            ${escapeHtml(warranty.label)}
                        </span>
                    </td>
                    <td>
                        <div class="dl-next-action">${escapeHtml(nextAction(record))}</div>
                        <button type="button" class="dl-edit-button"
                            data-dl-edit="${escapeHtml(id)}">Edit</button>
                    </td>
                </tr>`;
        };

        function updateSummary() {
            const total = records.length;
            const active = records.filter((r) => stageName(r) === "Active").length;
            const refreshDue = records.filter((r) => {
                const days = daysFromToday(r.refreshDueDate);
                return days !== null && days <= 90;
            }).length;
            const warrantyWatch = records.filter((r) => {
                const days = daysFromToday(r.warrantyEndDate);
                return days !== null && days <= 90;
            }).length;

            [
                ["[data-dl-total]", total],
                ["[data-dl-active]", active],
                ["[data-dl-refresh-count]", refreshDue],
                ["[data-dl-warranty-count]", warrantyWatch]
            ].forEach(([selector, value]) => {
                const node = $(selector);
                if (node) node.textContent = String(value);
            });

            const counts = {};
            STAGES.forEach((name) => {
                counts[name] = records.filter((r) => stageName(r) === name).length;
            });

            $$(".dl-stage").forEach((card) => {
                const heading = $("h3", card);
                const state = $(".dl-stage-state", card);
                if (!heading || !state) return;

                const amount = counts[heading.textContent.trim()] || 0;
                state.textContent = `${amount} asset${amount === 1 ? "" : "s"}`;
                state.classList.toggle("is-populated", amount > 0);
            });

            const summary = $("[data-dl-stage-summary]");
            if (summary) {
                const unspecified = counts.Unspecified || 0;
                summary.textContent = unspecified
                    ? `${total} assets · ${unspecified} need classification`
                    : `${total} assets · Lifecycle tracked`;
            }

            const feet = $$(".dl-stat-foot");
            if (feet[0]) feet[0].textContent = "From Cartman inventory";
            if (feet[1]) feet[1].textContent = "Stage: Active";
            if (feet[2]) feet[2].textContent = "Refresh date due within 90 days";
            if (feet[3]) feet[3].textContent = "Warranty expired or ends within 90 days";
        }

        function updateFilter() {
            const query = search.value.trim().toLowerCase();
            const selectedStage = stageFilter.value.toLowerCase();
            let visible = 0;

            [...rows.querySelectorAll("tr")].forEach((row) => {
                const text = (row.dataset.searchText || row.textContent).toLowerCase();
                const rowStage = (row.dataset.lifecycleStage || "").toLowerCase();
                const matches = text.includes(query)
                    && (!selectedStage || rowStage === selectedStage);

                row.hidden = !matches;
                if (matches) visible++;
            });

            empty.hidden = visible > 0;

            const heading = $("h3", empty);
            const description = $("p", empty);
            const hint = $(".dl-empty-hint", empty);

            if (records.length > 0 && visible === 0) {
                if (heading) heading.textContent = "No matching assets";
                if (description) description.textContent =
                    "Try another search term or lifecycle stage.";
                if (hint) hint.textContent = "Reset filters to show all inventory records.";
            } else if (records.length === 0) {
                if (heading) heading.textContent = "No lifecycle records available";
                if (description) description.textContent =
                    "The API returned no inventory records.";
                if (hint) hint.textContent = "Add assets in Inventory and refresh this page.";
            }

            const label = `${visible} asset${visible === 1 ? "" : "s"}`;
            const count = $("[data-dl-count]");
            const footer = $("[data-dl-footer-count]");
            if (count) count.textContent = label;
            if (footer) footer.textContent = label;
        }

        function render() {
            rows.innerHTML = records.map(rowHtml).join("");
            updateSummary();
            updateFilter();
        }

        async function loadData() {
            if (busy) return;
            busy = true;
            if (refresh) refresh.disabled = true;

            try {
                const data = await request(API);
                if (!Array.isArray(data)) {
                    throw new Error("Unexpected inventory response format.");
                }

                records = data;
                setConnection(true, "Inventory API connected");
                render();
            } catch (error) {
                setConnection(false, "Lifecycle data unavailable");

                empty.hidden = false;
                const heading = $("h3", empty);
                const description = $("p", empty);
                const hint = $(".dl-empty-hint", empty);

                if (heading) heading.textContent = "Unable to load lifecycle inventory";
                if (description) description.textContent = error.message || "The API request failed.";
                if (hint) hint.textContent = "Check that Cartman is running, then select Refresh.";

                if (rows.querySelectorAll("tr").length === 0) {
                    records = [];
                    updateSummary();
                    updateFilter();
                }
            } finally {
                busy = false;
                if (refresh) refresh.disabled = false;
            }
        }

        function ensureModal() {
            if ($("[data-dl-modal]")) return;

            const backdrop = document.createElement("div");
            backdrop.className = "dl-modal-backdrop";
            backdrop.dataset.dlModal = "";
            backdrop.hidden = true;

            backdrop.innerHTML = `
                <section class="dl-modal" role="dialog" aria-modal="true"
                    aria-labelledby="dl-modal-title">
                    <div class="dl-modal-header">
                        <div>
                            <div class="dl-section-kicker">ASSET LIFECYCLE</div>
                            <h2 id="dl-modal-title">Edit lifecycle record</h2>
                            <p data-dl-modal-asset></p>
                        </div>
                        <button type="button" class="dl-modal-close"
                            data-dl-modal-close aria-label="Close">×</button>
                    </div>
                    <form data-dl-modal-form>
                        <div class="dl-form-grid">
                            <label>Lifecycle stage
                                <select name="stage" required>
                                    ${STAGES.map((s) =>
                                        `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`
                                    ).join("")}
                                </select>
                            </label>
                            <label>Warranty end date
                                <input name="warrantyEndDate" type="date">
                            </label>
                            <label>Refresh due date
                                <input name="refreshDueDate" type="date">
                            </label>
                            <label>Retirement date
                                <input name="retirementDate" type="date">
                            </label>
                            <label class="dl-form-notes">Lifecycle notes
                                <textarea name="lifecycleNotes" rows="3" maxlength="2000"
                                    placeholder="Warranty details, replacement plan, disposal notes..."></textarea>
                            </label>
                        </div>
                        <p class="dl-modal-error" data-dl-modal-error hidden></p>
                        <div class="dl-modal-actions">
                            <button type="button" class="dl-reset-button"
                                data-dl-modal-close>Cancel</button>
                            <button type="submit" class="dl-save-button">Save changes</button>
                        </div>
                    </form>
                </section>`;

            root.appendChild(backdrop);
        }

        function closeModal() {
            const modal = $("[data-dl-modal]");
            if (modal) modal.hidden = true;
        }

        function openModal(id) {
            ensureModal();

            const record = records.find((item) => String(item.id) === String(id));
            const modal = $("[data-dl-modal]");
            if (!record || !modal) return;

            const form = $("[data-dl-modal-form]", modal);
            form.elements.stage.value = stageName(record);
            form.elements.warrantyEndDate.value = dateValue(record.warrantyEndDate);
            form.elements.refreshDueDate.value = dateValue(record.refreshDueDate);
            form.elements.retirementDate.value = dateValue(record.retirementDate);
            form.elements.lifecycleNotes.value = record.lifecycleNotes || "";

            $("[data-dl-modal-asset]", modal).textContent =
                `${record.name || "Unnamed asset"} · ${record.type || "Device"}`;
            $("[data-dl-modal-error]", modal).hidden = true;

            form.dataset.assetId = String(record.id);
            modal.hidden = false;
            form.elements.stage.focus();
        }

        rows.addEventListener("click", (event) => {
            const button = event.target.closest("[data-dl-edit]");
            if (button) openModal(button.dataset.dlEdit);
        });

        root.addEventListener("click", (event) => {
            if (event.target.closest("[data-dl-modal-close]")) {
                closeModal();
                return;
            }
            if (event.target.matches("[data-dl-modal]")) closeModal();
        });

        root.addEventListener("keydown", (event) => {
            if (event.key === "Escape") closeModal();
        });

        root.addEventListener("submit", async (event) => {
            const form = event.target.closest("[data-dl-modal-form]");
            if (!form) return;

            event.preventDefault();

            const modal = $("[data-dl-modal]");
            const errorBox = $("[data-dl-modal-error]", modal);
            const saveButton = $('button[type="submit"]', form);

            const stage = form.elements.stage.value;
            const warranty = form.elements.warrantyEndDate.value;
            const refreshDue = form.elements.refreshDueDate.value;
            const retirement = form.elements.retirementDate.value;
            const notes = form.elements.lifecycleNotes.value.trim();

            const payload = {
                stage,
                lifecycleStage: stage,
                warranty_end_date: warranty,
                warrantyEndDate: warranty,
                refresh_due_date: refreshDue,
                refreshDueDate: refreshDue,
                retirement_date: retirement,
                retirementDate: retirement,
                lifecycle_notes: notes,
                lifecycleNotes: notes
            };

            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            errorBox.hidden = true;

            try {
                await request(`${API}/${encodeURIComponent(form.dataset.assetId)}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                closeModal();
                await loadData();
            } catch (error) {
                errorBox.textContent = `Save failed: ${error.message}`;
                errorBox.hidden = false;
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = "Save changes";
            }
        });

        search.addEventListener("input", updateFilter);
        stageFilter.addEventListener("change", updateFilter);

        reset.addEventListener("click", () => {
            search.value = "";
            stageFilter.value = "";
            updateFilter();
        });

        if (refresh) refresh.addEventListener("click", loadData);

        ensureModal();
        setConnection(false, "Connecting to inventory API");
        loadData();
    });
})();
