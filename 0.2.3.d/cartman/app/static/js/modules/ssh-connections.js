(() => {
"use strict";

const root = document.querySelector("#admin-page-root[data-admin-page='ssh-connections']");
if (!root) return;

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;"
}[c]));

let profiles = [];
let loaded = false;
let loading = false;
let formOpen = false;
let editingId = null;
let feedback = "";

function pill(label, good=false) {
  return `<span class="admin-pill ${good ? "ok" : "warn"}">${esc(label)}</span>`;
}

function button(label, action, extra="") {
  return `<button type="button" class="admin-btn ${extra}" data-ssh-action="${esc(action)}">${esc(label)}</button>`;
}

function notice(text) {
  return `<div class="admin-notice">${esc(text)}</div>`;
}

function showFeedback(message) {
  feedback = message;
  const element = root.querySelector(".admin-feedback");
  if (element) element.textContent = message;
  else render();
}

function render() {
  const shouldLoad = !loaded && !loading;
  if (shouldLoad) loading = true;

  const editing = editingId !== null
    ? profiles.find(profile => String(profile.id) === String(editingId))
    : null;

  const rows = profiles.map(profile => `
    <tr>
      <td>${esc(profile.name)}</td>
      <td>${esc(profile.host)}</td>
      <td>${esc(profile.port)}</td>
      <td>${esc(profile.username)}</td>
      <td>${esc(profile.auth_method === "private_key" ? "Private key" : "Password")}</td>
      <td>${profile.host_key_fingerprint ? pill("Configured", true) : pill("Not pinned", false)}</td>
      <td>${profile.enabled ? pill("Enabled", true) : pill("Disabled", false)}</td>
      <td><div class="admin-actions">
        ${button("Edit", "edit:" + profile.id)}
        ${button("Delete", "delete:" + profile.id)}
      </div></td>
    </tr>`).join("");

  const form = formOpen ? `
    <article class="admin-card">
      <h3>${editing ? "Edit SSH profile" : "Add SSH profile"}</h3>
      <p>Connection metadata only. Credentials are not saved here.</p>
      <form id="ssh-profile-form">
        <div class="admin-grid">
          <label class="admin-field">Profile name
            <input name="name" required maxlength="100" value="${esc(editing?.name || "")}">
          </label>
          <label class="admin-field">Host or IP
            <input name="host" required maxlength="253" value="${esc(editing?.host || "")}" placeholder="server.example.com">
          </label>
          <label class="admin-field">Port
            <input name="port" type="number" min="1" max="65535" required value="${esc(editing?.port ?? 22)}">
          </label>
          <label class="admin-field">Username
            <input name="username" required maxlength="128" value="${esc(editing?.username || "")}">
          </label>
          <label class="admin-field">Authentication method
            <select name="auth_method" class="admin-field">
              <option value="private_key" ${(!editing || editing.auth_method === "private_key") ? "selected" : ""}>Private key</option>
              <option value="password" ${editing?.auth_method === "password" ? "selected" : ""}>Password</option>
            </select>
          </label>
          <label class="admin-field">Host key fingerprint
            <input name="host_key_fingerprint" maxlength="256" value="${esc(editing?.host_key_fingerprint || "")}" placeholder="SHA256:...">
          </label>
          <label class="admin-field">Description
            <input name="description" maxlength="500" value="${esc(editing?.description || "")}">
          </label>
        </div>
        <div class="admin-actions">
          <button class="admin-btn primary" type="submit">${editing ? "Save changes" : "Create profile"}</button>
          ${button("Cancel", "cancel")}
        </div>
      </form>
    </article>` : "";

  const tableBody = !loaded
    ? '<tr><td colspan="8" class="admin-empty">Loading SSH profiles…</td></tr>'
    : rows || '<tr><td colspan="8" class="admin-empty">No SSH profiles yet. Add a profile to get started.</td></tr>';

  root.innerHTML = `
    <div class="admin-hero">
      <div>
        <h2>SSH Connections</h2>
        <div class="admin-muted">Manage SSH connection profiles for infrastructure hosts.</div>
      </div>
      <div class="admin-actions">
        ${button("＋ Add profile", "new", "primary")}
        ${button("Refresh", "refresh")}
      </div>
    </div>

    ${feedback ? `<div class="admin-feedback" role="status" aria-live="polite">${esc(feedback)}</div>` : '<div class="admin-feedback" role="status" aria-live="polite"></div>'}
    ${form}

    <article class="admin-card">
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr>
            <th>Name</th><th>Host</th><th>Port</th><th>Username</th>
            <th>Authentication</th><th>Host key</th><th>Status</th><th>Actions</th>
          </tr></thead>
          <tbody>${tableBody}</tbody>
        </table>
      </div>
    </article>

    ${notice("SSH profiles store connection metadata only. No password or private key is stored, and no remote commands are executed.")}`;

  if (shouldLoad) {
    fetch("/api/ssh/profiles", { credentials: "same-origin" })
      .then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Request failed (${response.status})`);
        }
        profiles = Array.isArray(data.items) ? data.items : [];
      })
      .catch(error => {
        feedback = `Could not load SSH profiles: ${error.message}`;
      })
      .finally(() => {
        loading = false;
        loaded = true;
        render();
      });
  }
}

root.addEventListener("submit", async event => {
  if (event.target.id !== "ssh-profile-form") return;
  event.preventDefault();

  const values = new FormData(event.target);
  const payload = {
    name: String(values.get("name") || "").trim(),
    host: String(values.get("host") || "").trim(),
    port: Number(values.get("port") || 22),
    username: String(values.get("username") || "").trim(),
    auth_method: String(values.get("auth_method") || "private_key"),
    host_key_fingerprint: String(values.get("host_key_fingerprint") || "").trim(),
    description: String(values.get("description") || "").trim()
  };

  const isEditing = editingId !== null;
  const url = isEditing
    ? `/api/ssh/profiles/${encodeURIComponent(editingId)}`
    : "/api/ssh/profiles";

  try {
    const response = await fetch(url, {
      method: isEditing ? "PUT" : "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `Request failed (${response.status})`);
    }

    feedback = isEditing ? "SSH profile updated." : "SSH profile created.";
    formOpen = false;
    editingId = null;
    loaded = false;
    render();
  } catch (error) {
    showFeedback(`Could not save profile: ${error.message}`);
  }
});

root.addEventListener("click", async event => {
  const buttonEl = event.target.closest("[data-ssh-action]");
  if (!buttonEl) return;

  const action = buttonEl.dataset.sshAction;

  if (action === "new") {
    editingId = null;
    formOpen = true;
    feedback = "";
    render();
    return;
  }

  if (action === "cancel") {
    editingId = null;
    formOpen = false;
    feedback = "";
    render();
    return;
  }

  if (action === "refresh") {
    feedback = "";
    loaded = false;
    render();
    return;
  }

  if (action.startsWith("edit:")) {
    editingId = action.slice("edit:".length);
    formOpen = true;
    feedback = "";
    render();
    return;
  }

  if (action.startsWith("delete:")) {
    const id = action.slice("delete:".length);
    if (!confirm("Delete this SSH profile?")) return;

    try {
      const response = await fetch(`/api/ssh/profiles/${encodeURIComponent(id)}`, {
        method: "DELETE",
        credentials: "same-origin"
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || `Request failed (${response.status})`);
      }

      feedback = "SSH profile deleted.";
      loaded = false;
      render();
    } catch (error) {
      showFeedback(`Could not delete profile: ${error.message}`);
    }
  }
});

render();
})();