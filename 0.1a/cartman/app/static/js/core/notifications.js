"use strict";

/* CARTMAN — NOTIFICATIONS */
function notify(message) {
    const container = $("#toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    container.appendChild(toast);

    window.setTimeout(() => toast.remove(), 3200);
}
