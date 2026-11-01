(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const IMAGE_EXTENSIONS_BY_OS = Object.freeze({
    Windows: [".iso", ".wim", ".esd", ".swm"],
    Linux: [".iso", ".img", ".raw"],
    macOS: [".dmg", ".pkg", ".ipsw", ".zip"]
  });

  function isImageFileAllowed(filename, operatingSystem) {
    const match = String(filename || "").toLowerCase().match(/\.[^.]+$/);
    const extension = match ? match[0] : "";
    return (IMAGE_EXTENSIONS_BY_OS[operatingSystem] || []).includes(extension);
  }

  const state = { images: [], editingId: null };
  const el = {
    rows: $("#oi-rows"),
    empty: $("#oi-empty"),
    count: $("#oi-row-count"),
    search: $("#oi-search"),
    osFilter: $("#oi-os-filter"),
    modal: $("#oi-modal"),
    modalTitle: $("#oi-modal-title"),
    modalBody: $("#oi-modal-body"),
    modalActions: $("#oi-modal-actions"),
    toast: $("#oi-toast")
  };
  let toastTimer = null;

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));

  const operatorName = () => {
    const raw = ($(".profile-info strong")?.textContent || "").trim()
      || "Unidentified operator";

    // HTTP header values must not contain unsupported Unicode characters.
    const safe = raw.normalize("NFKD")
      .replace(/[\\u0300-\\u036f]/g, "")
      .replace(/[^\\x20-\\x7E]/g, "")
      .slice(0, 120)
      .trim();

    return safe || "Unidentified operator";
  };

  function notify(message) {
    if (!el.toast) return;
    el.toast.textContent = message;
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { el.toast.textContent = ""; }, 5000);
  }

  function safeHeaderValue(value) {
    return String(value || "Unidentified operator")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^\x20-\x7E]/g, "")
      .slice(0, 120)
      .trim() || "Unidentified operator";
  }

  async function uploadImageFile(imageId, file, operatingSystem) {
    const query = new URLSearchParams({
      filename: file.name,
      operating_system: operatingSystem
    });
    const response = await fetch(
      `/api/os-images/${encodeURIComponent(imageId)}/file?${query.toString()}`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Operator": safeHeaderValue(operatorName())
        },
        body: file
      }
    );

    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; }
    catch (_) { data = { detail: raw || response.statusText }; }

    if (!response.ok) {
      throw new Error(typeof data.detail === "string"
        ? data.detail
        : `Image upload failed: HTTP ${response.status}`);
    }
    return data;
  }

  async function api(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      "X-Operator": safeHeaderValue(operatorName()),
      ...(options.headers || {})
    };
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; }
    catch (_) { data = { detail: raw || response.statusText }; }

    if (!response.ok) {
      const error = new Error(
        typeof data.detail === "string"
          ? data.detail
          : `Request failed: HTTP ${response.status}`
      );
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function showModal(title, body, actions = []) {
    el.modalTitle.textContent = title;
    el.modalBody.innerHTML = body;
    el.modalActions.replaceChildren();
    for (const action of actions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `oi-btn ${action.primary ? "oi-primary" : ""} ${action.danger ? "oi-danger-outline" : ""}`;
      button.textContent = action.label;
      button.addEventListener("click", action.run);
      el.modalActions.append(button);
    }
    el.modal.hidden = false;
  }

  function closeModal() {
    el.modal.hidden = true;
    state.editingId = null;
  }

  function formatSize(size) {
    if (size === null || size === undefined || size === "") return "—";
    const number = Number(size);
    return Number.isFinite(number) ? `${number.toFixed(2)} GB` : "—";
  }

  function getVisibleImages() {
    const query = (el.search?.value || "").trim().toLowerCase();
    const os = el.osFilter?.value || "";
    return state.images
      .filter(image => (!os || image.operating_system === os))
      .filter(image => [
        image.name, image.operating_system, image.version, image.details, image.added_by
      ].some(value => String(value || "").toLowerCase().includes(query)))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }

  function closeRowMenus() {
    $$("[data-row-menu]").forEach(menu => {
      menu.hidden = true;
      menu.classList.remove("oi-menu-floating");
      menu.style.left = "";
      menu.style.top = "";
      menu.style.width = "";
      menu.style.maxHeight = "";
      if (menu._oiOriginalParent) {
        menu._oiOriginalParent.insertBefore(menu, menu._oiOriginalNext || null);
        delete menu._oiOriginalParent;
        delete menu._oiOriginalNext;
      }
    });
    $$("[data-menu]").forEach(button => button.setAttribute("aria-expanded", "false"));
  }

  function openRowMenu(button, menu) {
    closeRowMenus();
    menu._oiOriginalParent = menu.parentNode;
    menu._oiOriginalNext = menu.nextSibling;
    menu.hidden = false;
    menu.classList.add("oi-menu-floating");
    document.body.append(menu);
    button.setAttribute("aria-expanded", "true");

    const rect = button.getBoundingClientRect();
    const width = 205;
    const margin = 12;
    menu.style.width = `${width}px`;
    menu.style.left = `${Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin))}px`;
    menu.style.maxHeight = `${Math.max(120, window.innerHeight - 2 * margin)}px`;

    const height = menu.getBoundingClientRect().height;
    const below = window.innerHeight - rect.bottom - margin;
    menu.style.top = `${below >= height + 6
      ? rect.bottom + 6
      : Math.max(margin, rect.top - height - 6)}px`;
  }

  function render() {
    closeRowMenus();
    const images = getVisibleImages();
    el.rows.replaceChildren();

    for (const image of images) {
      const row = document.createElement("tr");
      const id = esc(image.id);
      row.innerHTML = `
        <td><div class="oi-image-name">${esc(image.name)}</div></td>
        <td>${esc(image.operating_system)}</td>
        <td>${esc(image.version)}</td>
        <td>${formatSize(image.size_gb)}</td>
        <td><span class="oi-stock ${image.stock ? "is-yes" : "is-no"}">${image.stock ? "Yes" : "No"}</span></td>
        <td>${esc(image.added_by || "Unknown")}</td>
        <td class="oi-action-cell">
          <button class="oi-dots" type="button" data-menu="${id}"
            aria-expanded="false" aria-label="Actions for ${esc(image.name)}">⋯</button>
          <div class="oi-row-menu" data-row-menu="${id}" hidden>
            <button type="button" data-action="details" data-id="${id}">◉ Details</button>
            <button type="button" data-action="edit" data-id="${id}">✎ Edit</button>
            <button type="button" data-action="deploy-pxe" data-id="${id}">➤ Deploy Image (PXE)</button>
            <button type="button" data-action="download" data-id="${id}" ${image.has_file ? "" : 'disabled title="No image file uploaded"'}>⇩ Download Image</button>
            <button type="button" class="oi-menu-delete" data-action="delete" data-id="${id}">♲ Delete</button>
          </div>
        </td>`;
      el.rows.append(row);
    }

    el.empty.hidden = images.length > 0;
    el.count.textContent = `${images.length} image${images.length === 1 ? "" : "s"} shown · ${state.images.length} total`;
  }

  async function loadImages() {
    try {
      const result = await api("/api/os-images");
      if (!Array.isArray(result)) throw new Error("OS image API returned an unexpected response.");
      state.images = result;
      render();
    } catch (error) {
      notify(`Could not load image catalog: ${error.message}`);
    }
  }

  function imageForm(image = null) {
    state.editingId = image?.id || null;
    const isEdit = Boolean(image);

    showModal(isEdit ? "Edit Image" : "Add Image", `
      <form class="oi-form" id="oi-image-form">
        <div class="oi-field full">
          <label for="oi-name">Name</label>
          <input id="oi-name" required maxlength="120" value="${esc(image?.name || "")}" placeholder="e.g. xp_fin1">
        </div>
        <div class="oi-field full">
          <label for="oi-file">Image file</label>
          <input id="oi-file" type="file" accept=".iso,.wim,.esd,.swm" ${isEdit ? "" : "required"}>
          <small id="oi-file-help">Choose an OS first. Supported extensions will match your Operating System. Max 32 GB.</small>
          ${isEdit && image.file_filename ? `<small>Current file: ${esc(image.file_filename)} · ${formatSize(image.size_gb)}</small>` : ""}
        </div>
        <div class="oi-field">
          <label for="oi-form-os">Operating System</label>
          <select id="oi-form-os" required>
            <option value="Windows" ${image?.operating_system === "Windows" ? "selected" : ""}>Windows</option>
            <option value="macOS" ${image?.operating_system === "macOS" ? "selected" : ""}>macOS</option>
            <option value="Linux" ${image?.operating_system === "Linux" ? "selected" : ""}>Linux</option>
          </select>
        </div>
        <div class="oi-field">
          <label for="oi-version">Version</label>
          <input id="oi-version" required maxlength="120" value="${esc(image?.version || "")}" placeholder="e.g. Windows XP / Debian 6.4">
        </div>
        <div class="oi-field">
          <label for="oi-size">Size (GB)</label>
          <input id="oi-size" type="number" min="0" max="1000000" step="0.01" value="${image?.size_gb ?? ""}" readonly>
          <small>Calculated from the selected file.</small>
        </div>
        <div class="oi-field">
          <label for="oi-stock">Stock</label>
          <select id="oi-stock">
            <option value="yes" ${!image || image.stock ? "selected" : ""}>Yes</option>
            <option value="no" ${image && !image.stock ? "selected" : ""}>No</option>
          </select>
        </div>
        <div class="oi-field full">
          <label for="oi-details">Details</label>
          <textarea id="oi-details" rows="4" maxlength="5000" placeholder="Optional notes about this image">${esc(image?.details || "")}</textarea>
        </div>
        <p class="oi-form-error" id="oi-form-error" hidden></p>
      </form>`, [
      { label: "Cancel", run: closeModal },
      { label: isEdit ? "Save changes" : "Add Image", primary: true, run: async () => {
        const form = $("#oi-image-form");
        if (!form.reportValidity()) return;

        const imageFile = $("#oi-file")?.files?.[0] || null;
        const selectedOS = $("#oi-form-os").value;
        const errorNode = $("#oi-form-error");

        if (!isEdit && !imageFile) {
          errorNode.textContent = "Select an image file before adding the record.";
          errorNode.hidden = false;
          return;
        }
        if (imageFile && !isImageFileAllowed(imageFile.name, selectedOS)) {
          errorNode.textContent =
            `${imageFile.name} is not supported for ${selectedOS}. Allowed: ${(IMAGE_EXTENSIONS_BY_OS[selectedOS] || []).join(", ")}.`;
          errorNode.hidden = false;
          return;
        }
        if (isEdit && !imageFile && image.file_filename &&
            !isImageFileAllowed(image.file_filename, selectedOS)) {
          errorNode.textContent =
            `The existing file is not supported for ${selectedOS}. Choose a compatible replacement file.`;
          errorNode.hidden = false;
          return;
        }

        const rawSize = $("#oi-size").value.trim();
        const payload = {
          name: $("#oi-name").value.trim(),
          operating_system: selectedOS,
          version: $("#oi-version").value.trim(),
          size_gb: imageFile
            ? Number((imageFile.size / (1024 ** 3)).toFixed(6))
            : (rawSize === "" ? null : Number(rawSize)),
          stock: $("#oi-stock").value === "yes",
          details: $("#oi-details").value.trim()
        };

        const saveButton = el.modalActions.querySelector(".oi-primary");
        if (saveButton) {
          saveButton.disabled = true;
          saveButton.textContent = imageFile ? "Uploading image…" : "Saving…";
        }

        let savedImage = null;
        try {
          if (isEdit) {
            if (imageFile) {
              await uploadImageFile(image.id, imageFile, selectedOS);
            }
            savedImage = await api(`/api/os-images/${encodeURIComponent(image.id)}`, {
              method: "PUT", body: JSON.stringify(payload)
            });
          } else {
            savedImage = await api("/api/os-images", {
              method: "POST", body: JSON.stringify(payload)
            });
            await uploadImageFile(savedImage.id, imageFile, selectedOS);
          }

          closeModal();
          await loadImages();
          notify(imageFile ? "Image record saved and file uploaded." : "Image metadata updated.");
        } catch (error) {
          if (!isEdit && savedImage?.id) {
            try {
              await api(`/api/os-images/${encodeURIComponent(savedImage.id)}`, { method: "DELETE" });
            } catch (_) {}
          }
          if (errorNode) {
            errorNode.textContent = error.message;
            errorNode.hidden = false;
          }
          if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = isEdit ? "Save changes" : "Add Image";
          }
        }
      }}
    ]);

    const fileInput = $("#oi-file");
    const sizeInput = $("#oi-size");
    const osInput = $("#oi-form-os");
    const help = $("#oi-file-help");
    const formError = $("#oi-form-error");

    function refreshFileTypes(clearIncompatible = true) {
      const os = osInput?.value || "Windows";
      const allowed = IMAGE_EXTENSIONS_BY_OS[os] || [];
      if (fileInput) fileInput.accept = allowed.join(",");
      if (help) help.textContent = `Allowed for ${os}: ${allowed.join(", ")}. Choose one image file. Max 32 GB.`;

      const chosen = fileInput?.files?.[0];
      if (clearIncompatible && chosen && !isImageFileAllowed(chosen.name, os)) {
        const badName = chosen.name;
        fileInput.value = "";
        if (sizeInput) sizeInput.value = image?.size_gb ?? "";
        if (formError) {
          formError.textContent = `${badName} is not supported for ${os}. Allowed: ${allowed.join(", ")}.`;
          formError.hidden = false;
        }
      }
    }

    fileInput?.addEventListener("change", () => {
      const file = fileInput.files?.[0];
      const os = osInput?.value || "Windows";
      if (formError) {
        formError.textContent = "";
        formError.hidden = true;
      }
      if (file && !isImageFileAllowed(file.name, os)) {
        const badName = file.name;
        fileInput.value = "";
        if (sizeInput) sizeInput.value = image?.size_gb ?? "";
        if (formError) {
          formError.textContent = `${badName} is not supported for ${os}. Allowed: ${(IMAGE_EXTENSIONS_BY_OS[os] || []).join(", ")}.`;
          formError.hidden = false;
        }
        return;
      }
      if (sizeInput) {
        sizeInput.value = file ? (file.size / (1024 ** 3)).toFixed(2) : (image?.size_gb ?? "");
      }
    });
    osInput?.addEventListener("change", () => refreshFileTypes(true));
    refreshFileTypes(false);
  }

  function showDetails(id) {
    const image = state.images.find(item => item.id === id);
    if (!image) return;

    showModal("Image Details", `
      <div class="oi-detail-grid">
        <div class="oi-detail"><span>Name</span><strong>${esc(image.name)}</strong></div>
        <div class="oi-detail"><span>Operating System</span><strong>${esc(image.operating_system)}</strong></div>
        <div class="oi-detail"><span>Version</span><strong>${esc(image.version)}</strong></div>
        <div class="oi-detail"><span>Size</span><strong>${formatSize(image.size_gb)}</strong></div>
        <div class="oi-detail"><span>Stock</span><strong>${image.stock ? "Yes" : "No"}</strong></div>
        <div class="oi-detail"><span>Added by</span><strong>${esc(image.added_by || "Unknown")}</strong></div>
        <div class="oi-detail"><span>Date added</span><strong>${esc(image.created_at || "—")}</strong></div>
        <div class="oi-detail"><span>Last updated</span><strong>${esc(image.updated_at || "—")}</strong></div>
        <div class="oi-detail oi-detail-wide"><span>Details</span><strong>${esc(image.details || "—")}</strong></div>
      </div>`, [
      { label: "Close", primary: true, run: closeModal }
    ]);
  }

  function confirmDelete(id) {
    const image = state.images.find(item => item.id === id);
    if (!image) return;

    showModal("Delete Image", `
      <div class="oi-warning">
        Delete <strong>${esc(image.name)}</strong> from the OS image catalog?
        This removes the metadata record. There is no image binary stored by this form.
      </div>`, [
      { label: "Cancel", run: closeModal },
      { label: "Delete Image", danger: true, run: async () => {
        const button = el.modalActions.querySelector(".oi-danger-outline");
        if (button) button.disabled = true;
        try {
          await api(`/api/os-images/${encodeURIComponent(id)}`, { method: "DELETE" });
          closeModal();
          await loadImages();
          notify("Image record deleted.");
        } catch (error) {
          closeModal();
          notify(`Delete failed: ${error.message}`);
        }
      }}
    ]);
  }

  function deployPxe(id) {
    const image = state.images.find(item => item.id === id);
    if (!image) return;

    if (image.operating_system === "macOS") {
      showModal("PXE Deployment Blocked", `
        <div class="oi-warning">
          <strong>Mac images cannot be installed via PXE.</strong>
          <p>PXE boot is not supported for Mac systems. No request was sent to the PXE API.</p>
        </div>`, [
        { label: "Close", primary: true, run: closeModal }
      ]);
      return;
    }

    showModal("Deploy Image (PXE)", `
      <p>Forward <strong>${esc(image.name)}</strong> to the configured PXE server API?</p>
      <div class="oi-detail-grid">
        <div class="oi-detail"><span>Operating System</span><strong>${esc(image.operating_system)}</strong></div>
        <div class="oi-detail"><span>Version</span><strong>${esc(image.version)}</strong></div>
      </div>
      <div class="oi-warning" style="margin-top:14px">
        This sends image metadata to Cartman's configured PXE API. Actual deployment status is provided by that PXE service.
      </div>`, [
      { label: "Cancel", run: closeModal },
      { label: "Send to PXE API", primary: true, run: async () => {
        const button = el.modalActions.querySelector(".oi-primary");
        if (button) {
          button.disabled = true;
          button.textContent = "Sending…";
        }
        try {
          const result = await api(`/api/os-images/${encodeURIComponent(id)}/deploy-pxe`, {
            method: "POST",
            body: JSON.stringify({})
          });
          showModal("PXE API Response", `
            <div class="oi-detail-grid">
              <div class="oi-detail"><span>Cartman status</span><strong>${esc(result.status || "forwarded")}</strong></div>
              <div class="oi-detail oi-detail-wide"><span>Message</span><strong>${esc(result.message || "PXE API accepted the request.")}</strong></div>
            </div>
            <pre class="oi-pxe-response">${esc(JSON.stringify(result.pxe_response ?? {}, null, 2))}</pre>`, [
            { label: "Close", primary: true, run: closeModal }
          ]);
        } catch (error) {
          showModal("PXE Request Not Sent", `
            <div class="oi-warning">
              <strong>${esc(error.message)}</strong>
              <p>No successful PXE request was confirmed.</p>
            </div>`, [
            { label: "Close", primary: true, run: closeModal }
          ]);
        }
      }}
    ]);
  }

  document.addEventListener("click", event => {
    const menuButton = event.target.closest("[data-menu]");
    if (menuButton) {
      event.preventDefault();
      event.stopPropagation();
      const menu = $(`[data-row-menu="${CSS.escape(menuButton.dataset.menu)}"]`);
      if (menu && menu.hidden) openRowMenu(menuButton, menu);
      else closeRowMenus();
      return;
    }

    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) return;
    event.preventDefault();
    const { action, id } = actionButton.dataset;
    closeRowMenus();

    if (action === "details") showDetails(id);
    else if (action === "edit") {
      const image = state.images.find(item => item.id === id);
      if (image) imageForm(image);
    } else if (action === "delete") confirmDelete(id);
    else if (action === "deploy-pxe") deployPxe(id);
    else if (action === "download") {
      const link = document.createElement("a");
      link.href = `/api/os-images/${encodeURIComponent(id)}/file`;
      link.download = "";
      document.body.append(link);
      link.click();
      link.remove();
    }
  });

  document.addEventListener("click", event => {
    if (!event.target.closest("[data-menu]") &&
        !event.target.closest("[data-row-menu]")) {
      closeRowMenus();
    }
  });

  $("#oi-add")?.addEventListener("click", () => imageForm());
  $("#oi-empty-add")?.addEventListener("click", () => imageForm());
  $("#oi-refresh")?.addEventListener("click", loadImages);
  el.search?.addEventListener("input", render);
  el.osFilter?.addEventListener("change", render);
  $("#oi-modal-close")?.addEventListener("click", closeModal);
  el.modal?.addEventListener("click", event => {
    if (event.target === el.modal) closeModal();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeRowMenus();
      if (el.modal && !el.modal.hidden) closeModal();
    }
  });

  loadImages();
})();
