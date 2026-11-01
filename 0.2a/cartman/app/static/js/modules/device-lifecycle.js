/* Device Lifecycle — local UI interactions only; no backend/API calls. */
document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector(".dl-page");
    if (!root) return;

    const search = root.querySelector("[data-dl-search]");
    const stage = root.querySelector("[data-dl-stage]");
    const reset = root.querySelector("[data-dl-reset]");
    const rows = root.querySelector("[data-dl-rows]");
    const empty = root.querySelector("[data-dl-empty]");
    const count = root.querySelector("[data-dl-count]");
    const footerCount = root.querySelector("[data-dl-footer-count]");

    if (!search || !stage || !reset || !rows || !empty) return;

    const update = () => {
        const records = Array.from(rows.querySelectorAll("tr"));
        const query = search.value.trim().toLowerCase();
        const selectedStage = stage.value.toLowerCase();
        let visible = 0;

        records.forEach((row) => {
            const text = (row.dataset.searchText || row.textContent).toLowerCase();
            const rowStage = (row.dataset.lifecycleStage || "").toLowerCase();
            const matches = text.includes(query)
                && (!selectedStage || rowStage === selectedStage);
            row.hidden = !matches;
            if (matches) visible++;
        });

        empty.hidden = visible > 0;
        const heading = empty.querySelector("h3");
        const description = empty.querySelector("p");

        if (records.length && visible === 0) {
            heading.textContent = "No matching assets";
            description.textContent = "Try another search term or lifecycle stage.";
        } else {
            heading.textContent = "No lifecycle records available";
            description.textContent = "Connect an asset inventory source to populate devices, lifecycle stages, warranty dates and refresh actions.";
        }

        const label = `${visible} asset${visible === 1 ? "" : "s"}`;
        if (count) count.textContent = label;
        if (footerCount) footerCount.textContent = label;
    };

    search.addEventListener("input", update);
    stage.addEventListener("change", update);
    reset.addEventListener("click", () => {
        search.value = "";
        stage.value = "";
        update();
    });
    update();
});
