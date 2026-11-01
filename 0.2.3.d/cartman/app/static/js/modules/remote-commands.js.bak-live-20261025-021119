/* Remote Commands UI preview. No remote execution or live API calls. */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const search = document.querySelector("[data-rc-search]");
    const status = document.querySelector("[data-rc-status]");
    const os = document.querySelector("[data-rc-os]");
    const rows = document.querySelector("[data-rc-rows]");
    const empty = document.querySelector("[data-rc-empty]");
    const count = document.querySelector("[data-rc-count]");
    const footerCount = document.querySelector("[data-rc-footer-count]");
    const template = document.querySelector("[data-rc-template]");
    const command = document.querySelector("[data-rc-command]");
    const charCount = document.querySelector("[data-rc-char-count]");
    const copyButton = document.querySelector("[data-rc-copy]");
    const clearButton = document.querySelector("[data-rc-clear]");
    const feedback = document.querySelector("[data-rc-feedback]");

    if (!search || !status || !os || !rows || !empty) return;

    const updateHistory = () => {
        const records = Array.from(rows.querySelectorAll("tr"));
        const query = search.value.trim().toLowerCase();
        const selectedStatus = status.value.toLowerCase();
        const selectedOS = os.value.toLowerCase();
        let visible = 0;

        records.forEach((row) => {
            const text = (row.dataset.searchText || row.textContent).toLowerCase();
            const rowStatus = (row.dataset.status || "").toLowerCase();
            const rowOS = (row.dataset.os || "").toLowerCase();
            const matches = text.includes(query)
                && (!selectedStatus || rowStatus === selectedStatus)
                && (!selectedOS || rowOS === selectedOS);
            row.hidden = !matches;
            if (matches) visible++;
        });

        empty.hidden = visible > 0;
        if (records.length > 0 && visible === 0) {
            empty.querySelector("h3").textContent = "No matching commands";
            empty.querySelector("p").textContent = "Try changing the search term or filters.";
        } else {
            empty.querySelector("h3").textContent = "No command executions yet";
            empty.querySelector("p").textContent = "Execution history will appear here when a command service is connected.";
        }
        if (count) count.textContent = `${visible} records`;
        if (footerCount) footerCount.textContent = `${visible} records`;
    };

    const templates = {
        "win-info": "Get-ComputerInfo | Select-Object CsName, WindowsProductName, OsVersion",
        "win-disk": "Get-Volume | Select-Object DriveLetter, FileSystemLabel, SizeRemaining, Size",
        "linux-info": "hostnamectl",
        "linux-disk": "df -h",
        "mac-info": "sw_vers && uname -a"
    };

    const updateEditor = () => {
        if (charCount) charCount.textContent = `${command.value.length} characters`;
        if (copyButton) copyButton.disabled = command.value.trim().length === 0;
    };

    search.addEventListener("input", updateHistory);
    status.addEventListener("change", updateHistory);
    os.addEventListener("change", updateHistory);

    template.addEventListener("change", () => {
        if (templates[template.value]) {
            command.value = templates[template.value];
            feedback.textContent = "Template loaded for review. Nothing was executed.";
        } else {
            command.value = "";
            feedback.textContent = "";
        }
        updateEditor();
    });

    command.addEventListener("input", () => {
        feedback.textContent = "";
        updateEditor();
    });

    clearButton.addEventListener("click", () => {
        command.value = "";
        template.value = "";
        feedback.textContent = "";
        updateEditor();
    });

    copyButton.addEventListener("click", async () => {
        const value = command.value;
        if (!value.trim()) return;
        try {
            await navigator.clipboard.writeText(value);
            feedback.textContent = "Command copied to clipboard. It was not executed.";
        } catch {
            command.focus();
            command.select();
            feedback.textContent = "Clipboard access unavailable. Command selected; copy it manually.";
        }
    });

    updateHistory();
    updateEditor();
});
