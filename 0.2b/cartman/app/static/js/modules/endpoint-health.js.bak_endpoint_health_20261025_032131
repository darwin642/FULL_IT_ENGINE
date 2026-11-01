/* Endpoint Health UI preview. No live telemetry or fabricated endpoints. */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const search = document.querySelector("[data-eh-search]");
    const status = document.querySelector("[data-eh-status]");
    const platform = document.querySelector("[data-eh-platform]");
    const rows = document.querySelector("[data-eh-rows]");
    const empty = document.querySelector("[data-eh-empty]");
    const count = document.querySelector("[data-eh-count]");
    const footerCount = document.querySelector("[data-eh-footer-count]");

    if (!search || !status || !platform || !rows || !empty) return;

    const update = () => {
        const records = Array.from(rows.querySelectorAll("tr"));
        const query = search.value.trim().toLowerCase();
        const selectedStatus = status.value.toLowerCase();
        const selectedPlatform = platform.value.toLowerCase();
        let visible = 0;

        records.forEach((row) => {
            const text = (row.dataset.searchText || row.textContent).toLowerCase();
            const rowStatus = (row.dataset.health || "").toLowerCase();
            const rowPlatform = (row.dataset.platform || "").toLowerCase();
            const matches = text.includes(query)
                && (!selectedStatus || rowStatus === selectedStatus)
                && (!selectedPlatform || rowPlatform === selectedPlatform);
            row.hidden = !matches;
            if (matches) visible++;
        });

        empty.hidden = visible > 0;
        if (records.length && visible === 0) {
            empty.querySelector("h3").textContent = "No matching endpoints";
            empty.querySelector("p").textContent = "Try changing the search term or filters.";
        } else {
            empty.querySelector("h3").textContent = "No endpoint health data";
            empty.querySelector("p").textContent = "Endpoints will appear here when health telemetry is connected.";
        }

        const label = `${visible} endpoint${visible === 1 ? "" : "s"}`;
        if (count) count.textContent = label;
        if (footerCount) footerCount.textContent = label;
    };

    search.addEventListener("input", update);
    status.addEventListener("change", update);
    platform.addEventListener("change", update);
    update();
});
