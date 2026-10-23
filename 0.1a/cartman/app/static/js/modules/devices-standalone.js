"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
    module: "Devices",
    theme: "dark"
};

function setModulePlaceholderVisible() {}

function notify(message) {
    let container = $("#cartman-toast-container");

    if (!container) {
        container = document.createElement("div");
        container.id = "cartman-toast-container";
        container.setAttribute("role", "status");
        container.setAttribute("aria-live", "polite");
        container.style.cssText =
            "position:fixed;right:24px;bottom:24px;z-index:99999;" +
            "display:grid;gap:8px;max-width:min(420px,calc(100vw - 32px));";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.textContent = String(message);
    toast.style.cssText =
        "padding:12px 16px;border:1px solid #475569;border-radius:10px;" +
        "background:#111827;color:#f8fafc;box-shadow:0 8px 28px #0003;";
    container.appendChild(toast);
    window.setTimeout(() => toast.remove(), 4000);
}

try {
    if (localStorage.getItem("cartman-theme") === "light") {
        document.body.classList.add("light-theme");
        state.theme = "light";
    }
} catch {
    // Theme preference is optional.
}
