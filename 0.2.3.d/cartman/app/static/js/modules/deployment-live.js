(() => {
    "use strict";

    const PAGE = document.body.dataset.deploymentPage || "dashboard";
    const $ = (selector) => document.querySelector(selector);

    let tasks = [];
    let packages = [];
    let devices = [];
    let visibleTasks = [];

    const finalStatuses = new Set(["Succeeded", "Failed", "Cancelled"]);

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[char]);
    }

    async function api(url, options = {}) {
        const headers = { ...(options.headers || {}) };
        if (options.body !== undefined) {
            headers["Content-Type"] = "application/json";
        }

        const response = await fetch(url, {
            cache: "no-store",
            credentials: "same-origin",
            ...options,
            headers
        });

        const raw = await response.text();
        let data = null;

        if (raw) {
            try {
                data = JSON.parse(raw);
            } catch {
                data = raw;
            }
        }

        if (!response.ok) {
            const detail = data && typeof data === "object"
                ? (data.detail || data.message)
                : data;

            throw new Error(
                detail ? String(detail) : `HTTP ${response.status} ${response.statusText}`
            );
        }

        return data;
    }

    function showNotice(title, message, isError = false) {
        const notice = $("#dw-notice");
        const titleNode = $("#dw-notice-title");
        const messageNode = $("#dw-notice-message");

        if (titleNode) titleNode.textContent = title;
        if (messageNode) messageNode.textContent = message;

        if (notice) {
            notice.classList.toggle("dw-notice-error", Boolean(isError));
        }
    }

    function setApiStatus(text, isError = false) {
        const node = $("#dw-api-status");
        if (!node) return;
        node.textContent = text;
        node.setAttribute("aria-label", text);
        node.classList.toggle("dw-notice-error", Boolean(isError));
    }

    async function refreshGlobalApiStatus() {
        let label = "Offline";
        let online = false;

        try {
            const response = await fetch("/api/health", {
                cache: "no-store",
                credentials: "same-origin",
                headers: { Accept: "application/json" }
            });

            if (!response.ok) {
                throw new Error("API health request failed");
            }

            const data = await response.json();
            online = String(data.status || "").toLowerCase() === "online";
            label = online ? "Online" : String(data.status || "Offline");
        } catch (error) {
            console.error("Cartman API status check failed:", error);
        }

        const applyStatus = () => {
            const status = $("#api-status");
            if (!status) return false;

            status.textContent = label;
            status.style.color = online ? "var(--green)" : "var(--red)";
            status.setAttribute("aria-label", "Cartman API " + label);
            return true;
        };

        // If navigation has not injected the status element yet, wait for it.
        if (applyStatus()) return;

        const observer = new MutationObserver(() => {
            if (applyStatus()) observer.disconnect();
        });

        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });

        window.setTimeout(() => observer.disconnect(), 10000);
    }

    // Deferred scripts can run before DOMContentLoaded while navigation
    // is still building the shared header/sidebar.
    if (document.readyState === "complete") {
        void refreshGlobalApiStatus();
    } else {
        document.addEventListener(
            "DOMContentLoaded",
            () => void refreshGlobalApiStatus(),
            { once: true }
        );
    }

    function formatDate(value) {
        if (!value) return "—";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);

        return new Intl.DateTimeFormat(undefined, {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }).format(date);
    }

    function statusClass(status) {
        return String(status || "")
            .toLowerCase()
            .replace(/[^a-z0-9_-]/g, "-");
    }

    function statusMarkup(status) {
        const safe = escapeHtml(status || "Unknown");
        return `<span class="dw-status dw-status-${statusClass(status)}">${safe}</span>`;
    }

    function getTaskName(task) {
        return task.software_name || "Package deployment";
    }

    function setStats() {
        const count = (status) =>
            tasks.filter((item) => item.status === status).length;

        if (PAGE === "history") {
            const outcomes = tasks.filter((item) =>
                finalStatuses.has(item.status)
            ).length;

            const cards = document.querySelectorAll(".dw-stat");
            const values = [
                {
                    label: "Total outcomes",
                    value: outcomes,
                    hint: "Succeeded, failed or cancelled tasks"
                },
                {
                    label: "Succeeded",
                    value: count("Succeeded"),
                    hint: "Reported successful deployments"
                },
                {
                    label: "Failed",
                    value: count("Failed"),
                    hint: "Reported deployment failures"
                },
                {
                    label: "Cancelled",
                    value: count("Cancelled"),
                    hint: "Cancelled deployments"
                }
            ];

            cards.forEach((card, index) => {
                const item = values[index];
                if (!item) return;

                const label = card.querySelector(".dw-stat-label");
                const value = card.querySelector("strong");
                const hint = card.querySelector("small");

                if (label) label.textContent = item.label;
                if (value) value.textContent = String(item.value);
                if (hint) hint.textContent = item.hint;
            });

            return;
        }

        const total = tasks.length;
        const running = count("Running");
        const queued = tasks.filter((item) =>
            item.status === "Queued" || item.status === "Dispatched"
        ).length;
        const failed = count("Failed");

        if ($("#dw-total")) $("#dw-total").textContent = String(total);
        if ($("#dw-running")) $("#dw-running").textContent = String(running);
        if ($("#dw-queued")) $("#dw-queued").textContent = String(queued);
        if ($("#dw-failed")) $("#dw-failed").textContent = String(failed);
    }

    function getFilteredTasks() {
        let rows = PAGE === "history"
            ? tasks.filter((task) => finalStatuses.has(task.status))
            : tasks.slice();

        const search = ($("#dw-search")?.value || "").trim().toLowerCase();
        const status = $("#dw-status")?.value || "all";

        if (status !== "all") {
            rows = rows.filter((task) => task.status === status);
        }

        if (search) {
            rows = rows.filter((task) => [
                task.id,
                task.device_name,
                task.device_os,
                task.software_name,
                task.software_version,
                task.status
            ].some((value) => String(value ?? "").toLowerCase().includes(search)));
        }

        return rows;
    }

    function renderRows() {
        const body = $("#dw-rows");
        if (!body) return;

        visibleTasks = getFilteredTasks();

        body.innerHTML = visibleTasks.map((task) => {
            const id = escapeHtml(task.id);
            const name = escapeHtml(getTaskName(task));
            const device = escapeHtml(task.device_name || task.device_id || "Unknown device");
            const version = escapeHtml(task.software_version || "Unknown");
            const requested = formatDate(task.created_at);
            const started = formatDate(task.started_at);
            const finished = formatDate(task.finished_at);
            const status = statusMarkup(task.status);

            let cells;

            if (PAGE === "history") {
                cells = `
                    <td><strong>${name}</strong><small>${id}</small></td>
                    <td>${device}<small>${escapeHtml(task.device_os || "")}</small></td>
                    <td>${version}</td>
                    <td>${started}</td>
                    <td>${finished}</td>
                    <td>${status}</td>
                    <td><button type="button" class="dw-btn" data-detail="${id}">Details</button></td>`;
            } else if (PAGE === "jobs") {
                cells = `
                    <td><strong>${name}</strong><small>${id}</small></td>
                    <td>${device}<small>${escapeHtml(task.device_os || "")}</small></td>
                    <td>${version}</td>
                    <td>${requested}</td>
                    <td>${started}</td>
                    <td>${status}</td>
                    <td><button type="button" class="dw-btn" data-detail="${id}">Details</button></td>`;
            } else {
                const updated = task.finished_at || task.started_at || task.created_at;
                cells = `
                    <td><strong>${name}</strong><small>${id}</small></td>
                    <td>${device}<small>${escapeHtml(task.device_os || "")}</small></td>
                    <td>${version}</td>
                    <td>${formatDate(updated)}</td>
                    <td>${status}</td>
                    <td><button type="button" class="dw-btn" data-detail="${id}">Details</button></td>`;
            }

            return `<tr>${cells}</tr>`;
        }).join("");

        const count = $("#dw-count");
        if (count) {
            count.textContent = `${visibleTasks.length} record${visibleTasks.length === 1 ? "" : "s"}`;
        }

        const empty = $("#dw-empty");
        if (empty) empty.hidden = visibleTasks.length !== 0;
    }

    async function loadTasks(silent = false) {
        try {
            const result = await api("/api/deployment-jobs");
            if (!Array.isArray(result)) {
                throw new Error("The deployment API returned an unexpected response.");
            }

            tasks = result;
            setApiStatus("Cartman API · Connected");
            setStats();
            renderRows();

            if (!silent) {
                showNotice(
                    "Live deployment data",
                    "Records are loaded from Cartman's persisted package-deployment task queue. Statuses reflect the server/agent records."
                );
            }
        } catch (error) {
            setApiStatus("Cartman API · Unavailable", true);
            showNotice("Could not load deployment data", error.message, true);
            const body = $("#dw-rows");
            if (body) body.innerHTML = "";
            const empty = $("#dw-empty");
            if (empty) empty.hidden = false;
            const count = $("#dw-count");
            if (count) count.textContent = "API unavailable";
        }
    }

    function normalizeOSFamily(value) {
        const os = String(value || "").trim().toLowerCase();

        if (!os || os === "unknown") return "Unknown";
        if (os === "any" || os === "all") return "Any";

        if (/(windows|win32|win64)/.test(os)) return "Windows";
        if (/(macos|mac os|darwin|os x|macintosh)/.test(os)) return "macOS";
        if (/(linux|ubuntu|debian|fedora|red hat|centos|rocky|almalinux|suse|mint|arch)/.test(os)) {
            return "Linux";
        }

        return "Unknown";
    }

    function isDeviceCompatible(pkg, device) {
        const target = normalizeOSFamily(pkg?.target_os);
        const actual = normalizeOSFamily(device?.os);

        if (target === "Any") return true;
        return target !== "Unknown" && target === actual;
    }

    function setInlineFeedback(selector, message, isError = false) {
        const node = $(selector);
        if (!node) return;

        node.textContent = message || "";
        node.hidden = !message;
        node.classList.toggle("dw-feedback-error", Boolean(message && isError));
        node.classList.toggle("dw-feedback-success", Boolean(message && !isError));
        node.setAttribute("role", isError ? "alert" : "status");
    }


    // Live status monitor for the Package Deployment wizard.
    let activePackageDeploymentWatch = null;

    function renderPackageDeploymentStatus(task) {
        const status = String(task.status || "Unknown");
        const taskId = String(task.id || "");
        let result = String(task.result || "").trim();

        // Some historical results are JSON-encoded objects.
        try {
            const parsed = JSON.parse(result);
            if (parsed && typeof parsed.message === "string") {
                result = parsed.message;
            }
        } catch (_) {}

        let message;
        if (status === "Queued" || status === "Dispatched") {
            message = `QUEUED · ${taskId} — Görev kuyrukta; Mac mini istemcisinin alması bekleniyor.`;
        } else if (status === "Running") {
            message = `RUNNING · ${taskId} — Kurulum devam ediyor; sonuç bekleniyor.`;
        } else if (status === "Succeeded") {
            message = `SUCCEEDED · ${taskId} — İstemci işlemin başarılı tamamlandığını bildirdi.`;
            if (result) message += ` Detay: ${result}`;
        } else if (status === "Cancelled") {
            message = `CANCELLED · ${taskId} — Görev iptal edildi; kurulum tamamlanmadı.`;
            if (result) message += ` Detay: ${result}`;
        } else if (status === "Failed") {
            message = `FAILED · ${taskId} — Kurulum başarısız oldu.`;
            if (result) message += ` Hata: ${result}`;
        } else {
            message = `${status} · ${taskId} — Görev durumu güncelleniyor.`;
            if (result) message += ` Detay: ${result}`;
        }

        const isError = status === "Failed" || status === "Cancelled";
        setInlineFeedback("#dw-confirm-feedback", message, isError);

        const node = $("#dw-confirm-feedback");
        if (!node) return;

        node.classList.remove(
            "dw-feedback-success",
            "dw-feedback-error",
            "dw-live-pending",
            "dw-live-running"
        );

        if (status === "Succeeded") {
            node.classList.add("dw-feedback-success");
        } else if (isError) {
            node.classList.add("dw-feedback-error");
        } else if (status === "Running") {
            node.classList.add("dw-live-running");
        } else {
            node.classList.add("dw-live-pending");
        }

        node.setAttribute("role", isError ? "alert" : "status");
    }

    async function watchPackageDeployment(taskId) {
        if (!taskId) return;

        activePackageDeploymentWatch = taskId;
        const terminalStatuses = new Set(["Succeeded", "Failed", "Cancelled"]);

        while (activePackageDeploymentWatch === taskId) {
            try {
                const jobs = await api("/api/deployment-jobs");
                if (!Array.isArray(jobs)) {
                    throw new Error("Deployment API beklenmeyen bir yanıt döndürdü.");
                }

                const task = jobs.find((item) => item.id === taskId);
                if (task) {
                    renderPackageDeploymentStatus(task);

                    if (terminalStatuses.has(task.status)) {
                        return;
                    }
                }
            } catch (error) {
                console.warn("Package Deployment status poll failed:", error);
                // Keep the last known task status visible; retry on the next poll.
            }

            await new Promise((resolve) => window.setTimeout(resolve, 3000));
        }
    }

    function renderPackageInfo() {
        const selectedId = $("#dw-package")?.value;
        const pkg = packages.find((item) => String(item.id) === String(selectedId));
        const target = $("#dw-package-info");

        if (!target) return;

        if (!pkg) {
            target.textContent = "Paket seçildiğinde sürüm, işletim sistemi ve kurulum kaynağı burada gösterilir.";
            return;
        }

        const uploaded = Boolean(pkg.package_filename);
        const sourceText = uploaded
            ? `Yüklenmiş dosya: ${pkg.package_filename} · ${(Number(pkg.package_size || 0) / (1024 * 1024)).toFixed(2)} MiB`
            : "Kurulum kaynağı: yapılandırılmış paket yöneticisi komutu";

        const argsText = String(pkg.package_type || "").toUpperCase() === "EXE"
            ? ` · Sessiz kurulum parametreleri: ${pkg.install_args || "Tanımlanmamış"}`
            : "";

        target.textContent =
            `${pkg.name} · Sürüm ${pkg.version || "Unknown"} · Hedef OS: ${pkg.target_os || "Any"} · ${sourceText}${argsText}`;
    }

    function renderCompatibleDevices() {
        const packageId = $("#dw-package")?.value;
        const pkg = packages.find((item) => String(item.id) === String(packageId));
        const select = $("#dw-device");
        const hint = $("#dw-device-hint");

        if (!select) return;

        // Never preserve a device selection when the package changes.
        select.innerHTML = "";

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = pkg
            ? "Uyumlu bir cihaz seçin"
            : "Önce bir yazılım paketi seçin";
        select.appendChild(placeholder);

        if (!pkg) {
            select.disabled = true;
            if (hint) {
                hint.textContent = "Önce paket seçin; yalnızca uyumlu işletim sistemleri listelenecek.";
            }
            return;
        }

        const compatible = devices.filter((device) => isDeviceCompatible(pkg, device));

        for (const device of compatible) {
            const option = document.createElement("option");
            option.value = String(device.id);
            option.textContent =
                `${device.name} · ${device.os || "Unknown OS"} · ${device.status || "Unknown status"}`;
            select.appendChild(option);
        }

        select.disabled = compatible.length === 0;

        if (hint) {
            if (compatible.length) {
                hint.textContent =
                    `${compatible.length} uyumlu cihaz bulundu. İşletim sistemi uyuşmayan cihazlar bu listede gösterilmez.`;
            } else {
                hint.textContent =
                    `Bu paket ${pkg.target_os || "Unknown"} hedefliyor; kayıtlı cihazlar arasında uyumlu bir hedef bulunamadı. Başka paket seçin veya uygun cihaz kaydedin.`;
            }
        }
    }

    async function loadWizardResources() {
        try {
            const [softwareResult, deviceResult] = await Promise.all([
                api("/api/software"),
                api("/api/devices")
            ]);

            if (!Array.isArray(softwareResult) || !Array.isArray(deviceResult)) {
                throw new Error("The software or device API returned an unexpected response.");
            }

            packages = softwareResult.filter((item) => {
                if (item.status !== "Active") return false;

                const hasUploadedMetadata = Boolean(
                    item.package_filename ||
                    Number(item.package_size) > 0 ||
                    item.package_sha256
                );

                const hasUploadedInstaller = Boolean(
                    item.package_filename &&
                    Number(item.package_size) > 0 &&
                    /^[a-f0-9]{64}$/i.test(String(item.package_sha256 || ""))
                );

                if (hasUploadedMetadata) {
                    if (!hasUploadedInstaller) return false;

                    if (
                        String(item.package_type || "").toUpperCase() === "EXE" &&
                        !String(item.install_args || "").trim()
                    ) {
                        return false;
                    }

                    return true;
                }

                return (
                    typeof item.install_command === "string" &&
                    item.install_command.trim().length > 0
                );
            });

            devices = deviceResult.filter((item) => item.id && item.name);

            const packageSelect = $("#dw-package");
            if (packageSelect) {
                packageSelect.innerHTML = [
                    '<option value="">Yazılım paketi seçin</option>',
                    ...packages.map((pkg) => {
                        const sourceLabel = pkg.package_filename
                            ? `Dosya: ${pkg.package_filename}`
                            : "Paket yöneticisi";
                        return `<option value="${escapeHtml(pkg.id)}">${escapeHtml(pkg.name)} · ${escapeHtml(pkg.version || "Unknown")} · ${escapeHtml(sourceLabel)}</option>`;
                    })
                ].join("");
                packageSelect.disabled = packages.length === 0;
            }

            renderPackageInfo();
            renderCompatibleDevices();
            setApiStatus("Cartman API · Connected");

            if (!packages.length) {
                showNotice(
                    "Dağıtıma hazır paket yok",
                    "Aktif ve yapılandırması tamamlanmış bir paket seçin. Yüklenmiş dosyalarda dosya adı, boyut ve SHA-256; EXE için de kurulum parametreleri gerekir.",
                    true
                );
            } else if (!devices.length) {
                showNotice(
                    "Hedef cihaz yok",
                    "Dağıtım için önce Cartman'a en az bir cihaz kaydedin.",
                    true
                );
            } else {
                showNotice(
                    "Dağıtım hazır",
                    "Paket ve cihazlar Cartman API'den yüklendi. Yalnızca uyumlu işletim sistemleri hedef olarak sunulur."
                );
            }
        } catch (error) {
            setApiStatus("Cartman API · Unavailable", true);
            showNotice("Paketler veya cihazlar yüklenemedi", error.message, true);
        }
    }

    function bindWizard() {
        const form = $("#dw-deploy-form");
        if (!form) return;

        const reviewPanel = $("#dw-review-panel");
        const confirmButton = $("#dw-confirm");

        function resetReview() {
            if (reviewPanel) reviewPanel.hidden = true;
            if ($("#dw-confirm-check")) $("#dw-confirm-check").checked = false;
            setInlineFeedback("#dw-confirm-feedback", "");
            setInlineFeedback("#dw-form-feedback", "");

            if (confirmButton) {
                confirmButton.disabled = false;
                confirmButton.textContent = "Confirm and queue task";
            }
        }

        $("#dw-package")?.addEventListener("change", () => {
            resetReview();
            renderPackageInfo();
            renderCompatibleDevices();
        });

        $("#dw-device")?.addEventListener("change", resetReview);

        form.addEventListener("submit", (event) => {
            event.preventDefault();

            const packageId = $("#dw-package")?.value;
            const deviceId = $("#dw-device")?.value;
            const pkg = packages.find((item) => String(item.id) === String(packageId));
            const device = devices.find((item) => String(item.id) === String(deviceId));

            if (!pkg) {
                setInlineFeedback("#dw-form-feedback", "Önce dağıtıma hazır bir yazılım paketi seçin.", true);
                return;
            }

            if (!device || !isDeviceCompatible(pkg, device)) {
                setInlineFeedback(
                    "#dw-form-feedback",
                    "Bu paket için uyumlu bir hedef cihaz seçin. Uyumlu olmayan cihazlar seçim listesinden çıkarılır.",
                    true
                );
                renderCompatibleDevices();
                return;
            }

            const isUploadedFile = Boolean(pkg.package_filename);
            const offline = /offline/i.test(String(device.status || ""));

            $("#dw-review").innerHTML = `
                <div class="dw-review-grid">
                    <article class="dw-review-card">
                        <span class="dw-review-kicker">YAZILIM PAKETİ</span>
                        <h3>${escapeHtml(pkg.name)}</h3>
                        <p class="dw-review-version">Sürüm ${escapeHtml(pkg.version || "Unknown")}</p>
                        <div class="dw-review-facts">
                            <div><span>Paket türü</span><strong>${escapeHtml(pkg.package_type || "Other")}</strong></div>
                            <div><span>Hedef işletim sistemi</span><strong>${escapeHtml(pkg.target_os || "Any")}</strong></div>
                            <div><span>Kurulum kaynağı</span><strong>${isUploadedFile ? "Sunucu paketi" : "Paket yöneticisi"}</strong></div>
                        </div>
                        <p class="dw-review-file">${escapeHtml(
                            isUploadedFile
                                ? `${pkg.package_filename} · ${(Number(pkg.package_size || 0) / (1024 * 1024)).toFixed(2)} MiB`
                                : "Katalogda yapılandırılmış kurulum komutu"
                        )}</p>
                    </article>
                    <article class="dw-review-card">
                        <span class="dw-review-kicker">HEDEF CİHAZ</span>
                        <h3>${escapeHtml(device.name)}</h3>
                        <p class="dw-review-version">${escapeHtml(device.os || "Unknown OS")}</p>
                        <div class="dw-review-facts">
                            <div><span>İşletim sistemi uyumu</span><strong class="dw-compatibility-ok">Uyumlu</strong></div>
                            <div><span>Bağlantı durumu</span><strong>${escapeHtml(device.status || "Unknown")}</strong></div>
                            <div><span>Görev davranışı</span><strong>${offline ? "Bağlantı bekleyebilir" : "Kuyruğa alınacak"}</strong></div>
                        </div>
                        <p class="dw-review-file">${offline
                            ? "Cihaz çevrimdışı görünüyor. Görev, onaylı CartmanClient yeniden bağlanana kadar bekleyebilir."
                            : "Kurulum yalnızca bu cihazdaki onaylı CartmanClient tarafından yürütülür."
                        }</p>
                    </article>
                </div>
                <div class="dw-review-note">
                    <strong>Ne olacak?</strong>
                    <span>Onay, yalnızca dağıtım görevini kuyruğa alır. Kurulumun tamamlandığı ancak CartmanClient gerçek sonucu bildirdiğinde gösterilir.</span>
                </div>
            `;

            resetReview();
            if (reviewPanel) reviewPanel.hidden = false;
            setInlineFeedback("#dw-form-feedback", "");
            setInlineFeedback("#dw-confirm-feedback", "");
        });

        $("#dw-cancel-review")?.addEventListener("click", resetReview);

        confirmButton?.addEventListener("click", async () => {
            const packageId = $("#dw-package")?.value;
            const deviceId = $("#dw-device")?.value;
            const pkg = packages.find((item) => String(item.id) === String(packageId));
            const device = devices.find((item) => String(item.id) === String(deviceId));
            const check = $("#dw-confirm-check");

            if (!pkg || !device || !isDeviceCompatible(pkg, device)) {
                setInlineFeedback(
                    "#dw-confirm-feedback",
                    "Paket veya hedef cihaz seçimi geçersiz. Lütfen seçimleri yeniden kontrol edin.",
                    true
                );
                return;
            }

            if (!check?.checked) {
                setInlineFeedback(
                    "#dw-confirm-feedback",
                    "Görevi kuyruğa göndermek için önce aşağıdaki onay kutusunu işaretleyin.",
                    true
                );
                return;
            }

            confirmButton.disabled = true;
            confirmButton.textContent = "Görev kuyruğa alınıyor…";
            setInlineFeedback("#dw-confirm-feedback", "");

            try {
                const created = await api(
                    `/api/devices/${encodeURIComponent(device.id)}/tasks`,
                    {
                        method: "POST",
                        body: JSON.stringify({
                            action: "package_deployment",
                            payload: {
                                software_id: pkg.id,
                                confirmed: true
                            }
                        })
                    }
                );

                await loadTasks(true);

                setInlineFeedback(
                    "#dw-confirm-feedback",
                    `Görev kuyruğa alındı · ${created.id || "Task created"}. ${created.message || "Kurulum sonucu CartmanClient tarafından bildirilecek."}`,
                    false
                );

                        // Follow this task directly in the Package Deployment page.
                        if (created.id) {
                            watchPackageDeployment(created.id);
                        }
                confirmButton.textContent = "Görev kuyruğa alındı";
                if (check) check.checked = false;
                setInlineFeedback("#dw-form-feedback", "");
            } catch (error) {
                setInlineFeedback("#dw-confirm-feedback", error.message, true);
                confirmButton.disabled = false;
                confirmButton.textContent = "Confirm and queue task";
            }
        });
    }

    function openDetails(id) {
        const task = tasks.find((item) => String(item.id) === String(id));
        if (!task) return;

        const result = task.result === null || task.result === undefined
            ? "No result has been reported yet."
            : typeof task.result === "string"
                ? task.result
                : JSON.stringify(task.result, null, 2);

        const body = $("#dw-detail-body");
        if (body) {
            body.innerHTML = `
                <dl>
                    <dt>Task ID</dt><dd>${escapeHtml(task.id)}</dd>
                    <dt>Status</dt><dd>${statusMarkup(task.status)}</dd>
                    <dt>Software</dt><dd>${escapeHtml(task.software_name)}</dd>
                    <dt>Version</dt><dd>${escapeHtml(task.software_version)}</dd>
                    <dt>Target device</dt><dd>${escapeHtml(task.device_name)}</dd>
                    <dt>Operating system</dt><dd>${escapeHtml(task.device_os)}</dd>
                    <dt>Requested</dt><dd>${escapeHtml(formatDate(task.created_at))}</dd>
                    <dt>Started</dt><dd>${escapeHtml(formatDate(task.started_at))}</dd>
                    <dt>Finished</dt><dd>${escapeHtml(formatDate(task.finished_at))}</dd>
                    <dt>Scheduled</dt><dd>${escapeHtml(formatDate(task.scheduled_at))}</dd>
                    <dt>Result</dt><dd><pre>${escapeHtml(result)}</pre></dd>
                </dl>
            `;
        }

        const modal = $("#dw-detail-modal");
        if (modal) modal.hidden = false;
    }

    function exportCsv() {
        const rows = [
            ["Task ID", "Software", "Version", "Device", "OS", "Status", "Requested", "Started", "Finished"],
            ...visibleTasks.map((task) => [
                task.id,
                task.software_name,
                task.software_version,
                task.device_name,
                task.device_os,
                task.status,
                task.created_at,
                task.started_at,
                task.finished_at
            ])
        ];

        const csv = rows.map((row) => row.map((value) =>
            `"${String(value ?? "").replace(/"/g, '""')}"`
        ).join(",")).join("\r\n");

        const url = URL.createObjectURL(new Blob(["\uFEFF", csv], {
            type: "text/csv;charset=utf-8"
        }));

        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `cartman-deployment-${PAGE}-${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
    }

    $("#dw-refresh")?.addEventListener("click", () => loadTasks());
    $("#dw-search")?.addEventListener("input", renderRows);
    $("#dw-status")?.addEventListener("change", renderRows);
    $("#dw-reset")?.addEventListener("click", () => {
        if ($("#dw-search")) $("#dw-search").value = "";
        if ($("#dw-status")) $("#dw-status").value = "all";
        renderRows();
    });
    $("#dw-export")?.addEventListener("click", exportCsv);

    document.addEventListener("click", (event) => {
        const detailButton = event.target.closest("[data-detail]");
        if (detailButton) openDetails(detailButton.dataset.detail);

        const closeButton = event.target.closest("[data-dw-close]");
        if (closeButton) {
            const modal = document.getElementById(closeButton.dataset.dwClose);
            if (modal) modal.hidden = true;
        }

        if (event.target.id === "dw-detail-modal") {
            event.target.hidden = true;
        }
    });

    if (PAGE === "software-deployment") {
        bindWizard();
        loadWizardResources();
    } else {
        loadTasks();

        // Keep Jobs and History synchronized with the server.
        let taskRefreshBusy = false;

        const refreshTasksIfVisible = async () => {
            if (document.hidden || taskRefreshBusy) return;

            taskRefreshBusy = true;
            try {
                await loadTasks(true);
            } finally {
                taskRefreshBusy = false;
            }
        };

        window.setInterval(refreshTasksIfVisible, 3000);

        // Refresh immediately when the user returns to this tab.
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) refreshTasksIfVisible();
        });
    }
})();
