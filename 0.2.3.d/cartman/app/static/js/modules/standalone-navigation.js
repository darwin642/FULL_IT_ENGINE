(() => {
    "use strict";

    // CARTMAN_GLOBAL_TOAST_BOOTSTRAP_V1
    // Fallback loader for standalone pages that use the shared navigation.
    (() => {
        if (window.CartmanToast && window.CartmanToast.__cartmanGlobalLiveToastsV1) return;
        if (document.querySelector('script[src*="/global-live-toasts.js"]')) return;
        const toastScript = document.createElement("script");
        toastScript.src = "/static/js/modules/global-live-toasts.js?v=cartman-global-live-toasts-v3-20261029";
        toastScript.async = true;
        (document.head || document.documentElement).appendChild(toastScript);
    })();


    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) =>
        Array.from(root.querySelectorAll(selector));

    const languageNames = {
        en: "English", tr: "Türkçe", de: "Deutsch", fr: "Français",
        es: "Español", nl: "Nederlands", pl: "Polski", it: "Italiano",
        "pt-BR": "Português", bcs: "Bosanski / Hrvatski / Srpski",
        sq: "Shqip", cs: "Čeština", lt: "Lietuvių", sv: "Svenska",
        no: "Norsk bokmål", da: "Dansk", fi: "Suomi",
        az: "Azərbaycanca", id: "Bahasa Indonesia", ms: "Bahasa Melayu",
        et: "Eesti", hu: "Magyar", ja: "日本語", ar: "العربية",
        "zh-CN": "简体中文", ru: "Русский", el: "Ελληνικά",
        he: "עברית", ko: "한국어"
    };

    async function initStandaloneNavigation() {
        if (location.pathname === "/") return;

        const response = await fetch("/static/index.html?standalone_nav=cartman-sidebar-monitoring-reports-v5-20261029", {
            cache: "no-store",
            credentials: "same-origin"
        });
        if (!response.ok) throw new Error("Dashboard source unavailable");

        const sourceDocument = new DOMParser().parseFromString(
            await response.text(), "text/html"
        );

        const dashboardHeader = $("header.topbar", sourceDocument);
        const dashboardSidebar = $("#sidebar", sourceDocument);

        if (!dashboardHeader || !dashboardSidebar) {
            throw new Error("Dashboard navigation markup not found");
        }

        // Dashboard toolbar tek kaynak. Modülün ana içeriğine dokunma.
        const currentHeader = $("header.topbar");
        if (!currentHeader) return;

        const header = dashboardHeader.cloneNode(true);
        currentHeader.replaceWith(header);

        const sidebar = dashboardSidebar.cloneNode(true);
        // CARTMAN_REPORTS_UNDER_MONITORING_RUNTIME_V2
        // Normalize Reports placement for every independent page, even if an older menu source is returned.
        const monitoringSubmenu = $("#nav-group-monitoring-observability", sidebar);
        const oldReportsHeading = sidebar.querySelector('[data-nav-group-toggle="nav-group-reports-analytics"]');
        const oldReportsSubmenu = $("#nav-group-reports-analytics", sidebar);
        if (monitoringSubmenu) {
            const reportLinks = sidebar.querySelectorAll('[data-page="Reports"]');
            const existingMonitoringLink = monitoringSubmenu.querySelector('[data-page="Reports"]');
            const oldGroupReportLink = oldReportsSubmenu?.querySelector('[data-page="Reports"]');
            const reportLink = existingMonitoringLink || oldGroupReportLink || reportLinks[0];
            for (const link of reportLinks) { if (link !== reportLink) link.remove(); }
            if (reportLink && reportLink.parentElement !== monitoringSubmenu) monitoringSubmenu.appendChild(reportLink);
        }
        oldReportsHeading?.remove();
        oldReportsSubmenu?.remove();
        // CARTMAN_FORCE_SIDEBAR_LAYOUT_V1
        // Normalize the canonical sidebar on every standalone page. This also repairs
        // older/cached index.html markup without touching page content or route keys.
        (() => {
            const one = selector => sidebar.querySelector(selector);
            const all = selector => Array.from(sidebar.querySelectorAll(selector));

            // Notifications live in the global topbar bell, never in the sidebar.
            all('.nav-link[data-page="Notifications"]').forEach(node => node.remove());
            // Keep Workflows inside the IT Operations submenu.
            const operations = one('#nav-group-it-operations');
            const workflowLinks = all('.nav-link[data-page="Workflows"]');
            let workflows = workflowLinks.shift() || null;
            workflowLinks.forEach(node => node.remove());
            if (operations && workflows) operations.appendChild(workflows);

            // CARTMAN_REPORTS_UNDER_MONITORING_FINAL_V1
            // Reports & Analytics belongs to Monitoring & Observability, not its own accordion.
            const monitoring = one('#nav-group-monitoring-observability');
            if (monitoring) {
                const reportLinks = all('.nav-link[data-page="Reports"]');
                let report = monitoring.querySelector('.nav-link[data-page="Reports"]')
                    || reportLinks[0]
                    || null;

                // Keep one route link only, preserving data-page="Reports" for navigation.
                reportLinks.forEach(node => { if (node !== report) node.remove(); });
                if (report) {
                    report.innerHTML = '<span>▥</span> Reports &amp; Analytics';
                    if (report.parentElement !== monitoring) monitoring.appendChild(report);
                }

                // Remove any legacy standalone Reports accordion after moving its link.
                all('[data-nav-group-toggle="nav-group-reports-analytics"]').forEach(node => node.remove());
                all('#nav-group-reports-analytics').forEach(node => node.remove());
            }
        })();
        // CARTMAN_STANDALONE_ACTIVE_PAGE_LINK_V1
        // Mark the current standalone destination, not the Dashboard's hard-coded Overview link.
        (() => {
            const pathSegments = location.pathname.split("/").filter(Boolean);
            const pagesIndex = pathSegments.lastIndexOf("pages");
            const currentSlug = pagesIndex >= 0
                ? decodeURIComponent(pathSegments[pagesIndex + 1] || "").toLowerCase()
                : "";
            if (!currentSlug) return;
            const pathMap = window.cartmanModulePaths || {};
            const currentPage = Object.entries(pathMap).find(([, value]) => {
                const mappedSlug = String(value || "").replace(/\/+$/g, "").split("/").pop().toLowerCase();
                return mappedSlug === currentSlug;
            })?.[0] || "";
            if (!currentPage) return;
            const links = Array.from(sidebar.querySelectorAll(".nav-link[data-page]"));
            for (const link of links) link.classList.toggle("active", link.dataset.page === currentPage);
            const activeLink = links.find(link => link.dataset.page === currentPage);
            const submenu = activeLink?.closest(".sidebar-submenu");
            if (submenu) {
                submenu.hidden = false;
                const groupToggle = sidebar.querySelector(`[data-nav-group-toggle="${submenu.id}"]`);
                if (groupToggle) groupToggle.setAttribute("aria-expanded", "true");
            }
        })();
        const existingSidebar = $("#sidebar");
        if (existingSidebar) existingSidebar.remove();
        sidebar.id = "sidebar";

        const existingBackdrop = $("#page-backdrop");
        if (existingBackdrop) existingBackdrop.remove();

        const backdrop = document.createElement("div");
        backdrop.id = "page-backdrop";
        backdrop.className = "page-backdrop";
        backdrop.setAttribute("aria-hidden", "true");

        document.body.insertBefore(backdrop, document.body.firstChild);
        header.insertAdjacentElement("afterend", sidebar);
        // CARTMAN_NOTIFICATION_BELL_LOADER_V1 — load after the shared dashboard header is cloned.
        if (!document.getElementById("cartman-notification-bell-loader")) {
            const bellScript = document.createElement("script");
            bellScript.id = "cartman-notification-bell-loader";
            bellScript.src = "/static/js/modules/global-notification-bell.js?v=cartman-notification-bell-v1";
            bellScript.async = true;
            (document.head || document.documentElement).appendChild(bellScript);
        }
        document.body.classList.add("has-standalone-sidebar");

        // Standalone sayfalar Dashboard başlığını kopyalar, ancak app.js
        // yüklemez. Bu nedenle ortak API durum göstergesini burada güncelle.
        const apiStatus = $("#api-status", sidebar);
        if (apiStatus) {
            apiStatus.textContent = "Checking...";
            apiStatus.style.color = "";
            apiStatus.setAttribute("aria-label", "Cartman API checking");

            fetch("/api/health", {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
                cache: "no-store"
            })
                .then(response => {
                    if (!response.ok) {
                        throw new Error("Health endpoint returned HTTP " + response.status);
                    }
                    return response.json();
                })
                .then(data => {
                    const online = data.status === "online";
                    const label = online ? "Online" : String(data.status || "Unknown");

                    apiStatus.textContent = label;
                    apiStatus.style.color = online ? "var(--green)" : "var(--red)";
                    apiStatus.setAttribute("aria-label", "Cartman API " + label);
                    apiStatus.title = "Cartman API health endpoint";
                })
                .catch(error => {
                    console.error("Standalone Cartman API health check failed:", error);
                    apiStatus.textContent = "Offline";
                    apiStatus.style.color = "var(--red)";
                    apiStatus.setAttribute("aria-label", "Cartman API Offline");
                    apiStatus.title = "Cartman API health check failed";
                });
        }

        // Dashboard terminali yalnızca güvenli yerel önizleme olarak paylaşılır.
        if (!$("#terminal-panel")) {
            const terminal = $("#terminal-panel", sourceDocument);
            if (terminal) document.body.appendChild(terminal.cloneNode(true));
        }

        const menuToggle = $("#menu-toggle", header);
        const search = $("#global-search", header);
        const languageToggle = $("#language-toggle", header);
        const languageMenu = $("#language-menu", header);
        const themeToggle = $("#theme-toggle", header);
        const themeLabel = $("#theme-label", header);
        const profileToggle = $("#profile-toggle", header);
        const profileMenu = $("#profile-menu", header);

// CARTMAN_REAL_PROFILE_AND_LOGOUT_V2
(() => {
    const menu = profileMenu;
    const toggle = profileToggle;

    if (!menu || menu.dataset.cartmanAuthBound === "1") return;
    menu.dataset.cartmanAuthBound = "1";

    const toggleName = toggle?.querySelector(".profile-info strong");
    const toggleRole = toggle?.querySelector(".profile-info small");
    const menuName = menu.querySelector("strong");
    const menuRole = menu.querySelector("small");
    const avatar = toggle?.querySelector(".avatar");

    const roleNames = {
        admin: "Administrator",
        network_admin: "Network Administrator",
        support_agent: "Support Agent",
        read_only: "Read-only"
    };

    async function refreshProfile() {
        try {
            const response = await fetch("/api/auth/me", {
                credentials: "same-origin",
                headers: { "Accept": "application/json" }
            });

            if (response.status === 401) {
                window.location.replace("/static/login.html");
                return;
            }
            if (!response.ok) return;

            const result = await response.json();
            const user = result?.user;
            if (!user) return;

            const name = user.display_name || user.username || "Cartman user";
            const role = roleNames[user.role] || user.role || "User";

            if (toggleName) toggleName.textContent = name;
            if (menuName) menuName.textContent = name;
            if (toggleRole) toggleRole.textContent = role;
            if (menuRole) menuRole.textContent = role;
            if (avatar) avatar.textContent = name.trim().charAt(0).toUpperCase() || "U";

            if (user.must_change_password) {
                window.location.replace("/static/change-password.html");
            }
        } catch (error) {
            console.error("Cartman profile could not be loaded:", error);
        }
    }

    menu.addEventListener("click", async event => {
        const button = event.target.closest("[data-auth-logout]");
        if (!button || !menu.contains(button)) return;

        event.preventDefault();
        event.stopPropagation();

        if (button.disabled) return;
        button.disabled = true;
        button.textContent = "Signing out…";

        try {
            const response = await fetch("/api/auth/logout", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Accept": "application/json" }
            });

            if (!response.ok && response.status !== 401) {
                let data = {};
                try { data = await response.json(); } catch (_) {}
                throw new Error(data.detail || "Sign out failed.");
            }

            window.location.replace("/static/login.html");
        } catch (error) {
            button.disabled = false;
            button.textContent = "Sign out";
            window.alert(error.message || "Could not sign out.");
        }
    });

    void refreshProfile();
})();

        const terminalToggle = $("#terminal-toggle", header);
        const terminalPanel = $("#terminal-panel");
        const terminalOutput = $("#terminal-output");
        const terminalForm = $("#terminal-form");
        const terminalInput = $("#terminal-command");

        const setMenu = open => {
            document.body.classList.toggle("menu-open", open);
            menuToggle?.setAttribute("aria-expanded", String(open));
        };

        const closeDropdowns = () => {
            for (const [menu, button] of [
                [languageMenu, languageToggle],
                [profileMenu, profileToggle]
            ]) {
                menu?.classList.add("hidden");
                button?.setAttribute("aria-expanded", "false");
            }
        };

        const toggleDropdown = (menu, button) => {
            if (!menu) return;
            const open = menu.classList.contains("hidden");
            closeDropdowns();
            menu.classList.toggle("hidden", !open);
            button?.setAttribute("aria-expanded", String(open));
        };

        menuToggle?.addEventListener("click", () => {
            setMenu(!document.body.classList.contains("menu-open"));
        });
        backdrop.addEventListener("click", () => setMenu(false));

        sidebar.addEventListener("click", event => {
            const group = event.target.closest("[data-nav-group-toggle]");
            if (group) {
                const submenu = document.getElementById(
                    group.dataset.navGroupToggle
                );
                if (!submenu || !sidebar.contains(submenu)) return;
                submenu.hidden = !submenu.hidden;
                group.setAttribute("aria-expanded", String(!submenu.hidden));
                return;
            }

            const item = event.target.closest("[data-page]");
            if (!item) return;

            event.preventDefault();
            navigate(item.dataset.page);
        });

        header.addEventListener("click", event => {
            const item = event.target.closest("[data-page]");
            if (item) {
                event.preventDefault();
                navigate(item.dataset.page);
            }
        });

        function navigate(name) {
            if (!name) return;
            if (name === "Home") {
                location.assign("/");
                return;
            }

            const paths = window.cartmanModulePaths || {};
            const definitions = window.moduleTranslationKeys || {};
            const slug = paths[name] || definitions[name];

            if (slug) location.assign(`/pages/${slug}/`);
            setMenu(false);
            closeDropdowns();
        }

        // Search: sidebar modüllerini filtreler; modül verisini değiştirmez.
        search?.addEventListener("input", () => {
            const query = search.value.trim().toLocaleLowerCase();
            $$(".nav-link, [data-nav-group]", sidebar).forEach(item => {
                const matches = !query ||
                    item.textContent.toLocaleLowerCase().includes(query);
                item.hidden = !matches;
            });

            $$(".nav-group", sidebar).forEach(group => {
                const visibleChild = $$(
                    ".nav-link:not([hidden])", group
                ).length > 0;
                if (query && !visibleChild) group.hidden = true;
                else group.hidden = false;
            });
        });

        // Tema tercihi Dashboard ile aynı anahtarı kullanır.
        const applyTheme = theme => {
            const light = theme === "light";
            document.body.classList.toggle("light-theme", light);
            if (themeLabel) themeLabel.textContent =
                light ? "Dark mode" : "Light mode";
            if (themeToggle) {
                themeToggle.setAttribute("aria-pressed", String(light));
                themeToggle.setAttribute(
                    "aria-label",
                    light ? "Switch to dark theme" : "Switch to light theme"
                );
            }
            try {
                localStorage.setItem("cartman-theme", light ? "light" : "dark");
            } catch (_) {}
        };

        try {
            applyTheme(localStorage.getItem("cartman-theme") || "dark");
        } catch (_) {
            applyTheme("dark");
        }

        themeToggle?.addEventListener("click", () => {
            applyTheme(document.body.classList.contains("light-theme")
                ? "dark" : "light");
        });

        // Dil seçimi ortak tercihi kaydeder; JSON yüklenemezse mevcut sayfa kalır.
        // Overview ile aynı bayrak dosyalarını kullan.
        const flagFiles = {
            en: "gb", tr: "tr", de: "de", fr: "fr", es: "es",
            nl: "nl", pl: "pl", it: "it", "pt-BR": "pt",
            bcs: "ba", sq: "al", cs: "cz", lt: "lt", sv: "se",
            no: "no", da: "dk", fi: "fi", az: "az", id: "id",
            ms: "my", et: "ee", hu: "hu", ja: "jp", ar: "sa",
            "zh-CN": "cn", ru: "ru", el: "gr", he: "il", ko: "kr"
        };

        const createFlagImage = language => {
            const file = flagFiles[language];
            if (!file) {
                return document.createTextNode(languageNames[language] || language);
            }

            const image = document.createElement("img");
            image.className = "language-flag";
            image.src = `/static/flags/${file}.svg`;
            image.alt = "";
            image.setAttribute("aria-hidden", "true");
            image.draggable = false;
            image.addEventListener("error", () => {
                image.hidden = true;
            }, { once: true });
            return image;
        };

        const renderLanguageFlags = () => {
            $$("#language-menu [data-language]", header).forEach(button => {
                const language = button.dataset.language;
                button.replaceChildren(createFlagImage(language));
                button.title = languageNames[language] || language;
                button.setAttribute(
                    "aria-label",
                    languageNames[language] || language
                );
            });
        };

        const updateLanguageLabel = language => {
            const label = $("#language-label", header);
            if (!label) return;
            label.replaceChildren(createFlagImage(language));
            label.title = languageNames[language] || language;
            label.setAttribute(
                "aria-label",
                languageNames[language] || language
            );

            $$("#language-menu [data-language]", header).forEach(button => {
                button.classList.toggle(
                    "selected",
                    button.dataset.language === language
                );
            });
        };

        let selectedLanguage = "en";
        try {
            selectedLanguage = localStorage.getItem("cartman-language") || "en";
        } catch (_) {}
        if (!languageNames[selectedLanguage]) selectedLanguage = "en";
        renderLanguageFlags();
        updateLanguageLabel(selectedLanguage);

        languageToggle?.addEventListener("click", () =>
            toggleDropdown(languageMenu, languageToggle)
        );

        languageMenu?.addEventListener("click", async event => {
            const button = event.target.closest("[data-language]");
            if (!button) return;

            const language = button.dataset.language;
            if (!languageNames[language]) return;

            try {
                const result = await fetch(
                    `/static/translations/${encodeURIComponent(language)}.json`,
                    { headers: { Accept: "application/json" } }
                );
                if (!result.ok) throw new Error("Translation unavailable");
                const data = await result.json();
                if (!data || typeof data !== "object" || Array.isArray(data)) {
                    throw new Error("Invalid translation data");
                }

                try {
                    localStorage.setItem("cartman-language", language);
                } catch (_) {}

                document.documentElement.lang = language;
                updateLanguageLabel(language);
                closeDropdowns();

                // Sayfa metinleri için çeviri altyapısı bulunmuyorsa
                // kullanıcıyı yanlış yönlendirmeden tercihi paylaş.
                document.dispatchEvent(new CustomEvent(
                    "cartman:language-changed",
                    { detail: { language, translations: data } }
                ));
            } catch (error) {
                console.error("Language selection failed:", error);
            }
        });

        profileToggle?.addEventListener("click", () =>
            toggleDropdown(profileMenu, profileToggle)
        );

        document.addEventListener("click", event => {
            if (!header.contains(event.target)) closeDropdowns();
        });

        // Terminal: help, clear, status ve version dışında komut çalıştırmaz.
        const setTerminal = open => {
            if (!terminalPanel) return;
            document.body.classList.toggle("terminal-open", open);
            terminalPanel.setAttribute("aria-hidden", String(!open));
            if (open) terminalInput?.focus();
        };

        terminalToggle?.addEventListener("click", () => {
            setTerminal(!document.body.classList.contains("terminal-open"));
        });
        $("#terminal-close")?.addEventListener("click", () => setTerminal(false));
        $("#terminal-clear")?.addEventListener("click", () => {
            if (terminalOutput) {
                terminalOutput.replaceChildren();
                appendTerminal("Output cleared.");
            }
        });

        function appendTerminal(message) {
            if (!terminalOutput) return;
            const line = document.createElement("p");
            line.textContent = message;
            terminalOutput.appendChild(line);
            terminalOutput.scrollTop = terminalOutput.scrollHeight;
        }

        terminalForm?.addEventListener("submit", event => {
            event.preventDefault();
            const command = terminalInput?.value.trim().toLowerCase();
            if (!command) return;
            appendTerminal(`cartman > ${command}`);
            if (terminalInput) terminalInput.value = "";

            const commands = {
                help: "Available preview commands: help, clear, status, version",
                status: "Standalone UI active. Backend and remote execution are not invoked.",
                version: "Cartman UI preview"
            };

            if (command === "clear") {
                terminalOutput?.replaceChildren();
            } else {
                appendTerminal(commands[command] ||
                    "Unsupported preview command. Type help.");
            }
        });

        document.addEventListener("keydown", event => {
            if ((event.ctrlKey || event.metaKey) &&
                event.key.toLowerCase() === "k") {
                event.preventDefault();
                search?.focus();
            }
            if (event.key === "Escape") {
                setMenu(false);
                setTerminal(false);
                closeDropdowns();
            }
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        initStandaloneNavigation().catch(error => {
            console.error("Cartman navigation initialization failed:", error);
        });
    });
})();

(() => {
  if (document.querySelector('script[data-cartman-user-metrics-tracker]')) return;
  const script = document.createElement('script');
  script.src = '/static/js/modules/user-metrics-tracker.js?v=cartman-user-metrics-live-20261030-v2';
  script.defer = true;
  script.dataset.cartmanUserMetricsTracker = '1';
  (document.head || document.documentElement).appendChild(script);
})();

/* CARTMAN_RBAC_IDENTITY_SECURITY_NAV_V1 */
(() => {
  "use strict";
  const normalize = value => String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
  const rowFor = element => element && (element.closest("li, .sidebar-item, .nav-item, .sidebar-nav-item, [data-sidebar-item]") || element);
  function moveRolesPermissions() {
    const sidebar = document.querySelector("#sidebar, .sidebar, .app-sidebar, .sidebar-nav, aside") || document;
    const nodes = Array.from(sidebar.querySelectorAll("a, button, [role='link']"));
    const roleLink = nodes.find(node => {
      const href = String(node.getAttribute("href") || "").toLowerCase();
      const page = normalize(node.getAttribute("data-page"));
      const label = normalize(node.textContent);
      return href.includes("/pages/roles-permissions") || page === "roles & permissions" || page === "roles-permissions" || label === "roles & permissions";
    });
    const identityLink = nodes.find(node => {
      const href = String(node.getAttribute("href") || "").toLowerCase();
      const page = normalize(node.getAttribute("data-page"));
      const label = normalize(node.textContent);
      return href.includes("/pages/identity/") || page === "identity" || label === "identity & access";
    });
    if (!roleLink || !identityLink) return;
    const roleRow = rowFor(roleLink);
    const identityRow = rowFor(identityLink);
    if (!roleRow || !identityRow || roleRow === identityRow) return;
    const targetList = identityRow.parentElement;
    if (!targetList) return;
    if (roleRow.parentElement === targetList && identityRow.nextElementSibling === roleRow) return;
    targetList.insertBefore(roleRow, identityRow.nextElementSibling);
    roleLink.setAttribute("aria-label", "Roles & Permissions");
  }
  let scheduled = false;
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    Promise.resolve().then(() => { scheduled = false; moveRolesPermissions(); });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", schedule, { once: true });
  else schedule();
  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
/* END CARTMAN_RBAC_IDENTITY_SECURITY_NAV_V1 */
