"use strict";

/* CARTMAN — THEME MANAGEMENT */

function applyTheme(theme) {
    state.theme = theme === "light" ? "light" : "dark";

    document.body.classList.toggle(
        "light-theme",
        state.theme === "light"
    );

    const label = $("#theme-label");
    const button = $("#theme-toggle");

    if (label) {
        label.textContent = state.theme === "light"
            ? translate("darkMode", "Dark mode")
            : translate("lightMode", "Light mode");
    }

    if (button) {
        if (button.firstChild?.nodeType === Node.TEXT_NODE) {
            button.firstChild.textContent =
                state.theme === "light" ? "☾ " : "☀ ";
        }

        button.setAttribute(
            "aria-label",
            state.theme === "light"
                ? translate("switchToDark", "Switch to dark theme")
                : translate("switchToLight", "Switch to light theme")
        );

        button.setAttribute(
            "aria-pressed",
            String(state.theme === "light")
        );
    }

    try {
        localStorage.setItem("cartman-theme", state.theme);
    } catch {
        // The theme still works for this session.
    }
}
