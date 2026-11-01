"use strict";

/* Network & Infrastructure batch: local search only; no network probes or API calls. */
document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector(".nx-page");
  if (!root) return;

  const search = root.querySelector("[data-nx-search]");
  const content = root.querySelector("[data-nx-content]");
  const empty = root.querySelector("[data-nx-empty]");
  if (!search || !content || !empty) return;

  const panels = Array.from(content.querySelectorAll(".nx-panel"));
  const update = () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;

    panels.forEach(panel => {
      const matches = !query || panel.textContent.toLocaleLowerCase().includes(query);
      panel.dataset.nxSectionHidden = String(!matches);
      if (matches) visible++;
    });

    empty.hidden = visible > 0;
  };

  search.addEventListener("input", update);
  update();
});
