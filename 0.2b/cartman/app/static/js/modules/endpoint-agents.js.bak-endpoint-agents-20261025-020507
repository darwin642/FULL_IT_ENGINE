/* Endpoint Agents module bootstrap.
   The inventory API does not exist yet; do not fabricate agent records. */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const search = document.querySelector("[data-ea-search]");
    const status = document.querySelector("[data-ea-status]");
    const rows = document.querySelector("[data-ea-rows]");
    const count = document.querySelector("[data-ea-count]");

    if (!search || !status || !rows || !count) return;

    // Enable inventory controls when a real inventory data source is added.
    // Until then, keep them disabled to avoid implying that filtering live
    // endpoint data is available.
    search.disabled = true;
    status.disabled = true;
    count.textContent = `${rows.querySelectorAll("tr").length} records`;
});
