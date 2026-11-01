"use strict";

try {
    if (localStorage.getItem("cartman-theme") === "light") {
        document.body.classList.add("light-theme");
    }
} catch {
    // Theme preference is optional.
}

const pageSearch = document.querySelector("[data-page-search]");
const pageTableBody = document.querySelector(".workspace-table tbody");
const pageRowCount = document.querySelector("[data-row-count]");
const pageEmptyState = document.querySelector("[data-empty-state]");

if (pageSearch && pageTableBody && pageRowCount && pageEmptyState) {
    const rows = [...pageTableBody.querySelectorAll("tr")];

    pageSearch.addEventListener("input", () => {
        const query = pageSearch.value.trim().toLocaleLowerCase();
        let visible = 0;

        rows.forEach(row => {
            const text = (
                row.dataset.searchText || row.textContent || ""
            ).toLocaleLowerCase();

            const matches = text.includes(query);
            row.classList.toggle("hidden", !matches);

            if (matches) visible++;
        });

        pageRowCount.textContent = `${visible} row(s)`;
        pageEmptyState.classList.toggle("hidden", visible > 0);
    });
}
