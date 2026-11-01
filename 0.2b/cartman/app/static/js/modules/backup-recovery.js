
(() => {
  "use strict";
  const root = document.getElementById("backup-recovery-root");
  if (!root || root.dataset.initialized === "true") return;
  root.dataset.initialized = "true";

  const STORAGE = "cartman.backupRecovery.demo.v1";
  const defaults = {
    profile: {
      name: "Cartman Full System Backup",
      enabled: true,
      scope: "full",
      frequency: "daily",
      time: "02:00",
      retention: 30,
      target: "backup-repository",
      verify: true
    },
    jobs: [],
    activeTab: "overview"
  };
  const clone = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  })[ch]);
  const fmtDate = value => value ? new Date(value).toLocaleString() : "—";
  const fmtSize = bytes => {
    if (!bytes) return "0 B";
    const units = ["B","KB","MB","GB","TB"];
    let n = bytes, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
  };
  const readState = () => {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE) || "null");
      if (!parsed || typeof parsed !== "object") return clone(defaults);
      return {
        ...clone(defaults), ...parsed,
        profile: {...clone(defaults.profile), ...(parsed.profile || {})},
        jobs: Array.isArray(parsed.jobs) ? parsed.jobs : []
      };
    } catch (_) { return clone(defaults); }
  };
  let state = readState();
  let notice = "";
  let noticeType = "info";

  function persist() {
    try {
      localStorage.setItem(STORAGE, JSON.stringify(state));
      return true;
    } catch (_) {
      setNotice("Tarayıcı depolamasına kaydedilemedi. Depolama alanını kontrol et.", "warn");
      return false;
    }
  }
  function setNotice(message, type = "info") {
    notice = message;
    noticeType = type;
  }
  function badge(text, type = "") {
    return `<span class="br-badge ${type ? "br-badge-" + type : ""}">${esc(text)}</span>`;
  }
  function stat(icon, label, value, foot) {
    return `<article class="br-card">
      <div class="br-stat-head"><span>${label}</span><span class="br-stat-icon">${icon}</span></div>
      <div class="br-stat-value">${value}</div><div class="br-stat-foot">${foot}</div>
    </article>`;
  }
  function empty(icon, title, description) {
    return `<div class="br-empty"><div class="br-empty-icon">${icon}</div>
      <div class="br-empty-title">${title}</div><div class="br-muted">${description}</div></div>`;
  }
  function statusBadge(status) {
    const type = status === "Completed" ? "ok" : status === "Failed" ? "warn" : "";
    return badge(status, type);
  }
  function shell(content) {
    root.innerHTML = `<div class="br-wrap">
      <header class="br-hero">
        <div>
          <div class="br-eyebrow">IT OPERATIONS / RESILIENCE</div>
          <h1 class="br-title">Backup &amp; Recovery</h1>
          <p class="br-subtitle">Cartman uygulaması için yedekleme planları, otomasyon, iş geçmişi ve kurtarma akışları.</p>
          <div class="br-badges"><span class="br-demo"><span class="br-dot"></span> DEMO MODE · GERÇEK YEDEK ALINMAZ</span></div>
        </div>
        <div class="br-actions">
          <button class="br-btn" data-action="export">⇩ Export demo data</button>
          <button class="br-btn br-btn-primary" data-action="run">▶ Run demo backup</button>
        </div>
      </header>
      <div class="br-notice br-notice-warn">
        <strong>Demo ortamı:</strong> İşlemler simüle edilir. Gerçek dosyalar, sunucular veya veritabanları yedeklenmez; restore işlemi gerçek verileri değiştirmez.
      </div>
      <div class="br-toast" role="status" aria-live="polite">${esc(notice)}</div>
      ${content}
    </div>`;
    const toast = root.querySelector(".br-toast");
    if (toast && notice) {
      toast.className = `br-toast br-notice-${noticeType === "warn" ? "warn" : "info"}`;
    }
  }

  function navTabs() {
    const tabs = [
      ["overview","Overview"],["automation","Automation"],["history","Backup history"],["recovery","Recovery"]
    ];
    return `<nav class="br-tabs" aria-label="Backup sections">
      ${tabs.map(([id,label]) => `<button class="br-tab" data-tab="${id}" aria-selected="${state.activeTab === id}">${label}</button>`).join("")}
    </nav>`;
  }

  function overview() {
    const completed = state.jobs.filter(j => j.status === "Completed").length;
    const failed = state.jobs.filter(j => j.status === "Failed").length;
    const latest = state.jobs[0];
    const total = state.jobs.filter(j => j.status === "Completed").reduce((sum,j) => sum + (j.bytes || 0), 0);
    const p = state.profile;
    return `${navTabs()}
      <section class="br-grid">
        ${stat("▣","Backup jobs",state.jobs.length,"Bu tarayıcıda kayıtlı demo işleri")}
        ${stat("✓","Successful",completed,"Simüle edilmiş tamamlanan işler")}
        ${stat("⚠","Failed",failed,"Simüle edilmiş başarısız işler")}
        ${stat("◫","Reported data",fmtSize(total),"Gerçek disk kullanımını göstermez")}
      </section>
      <section class="br-split">
        <article class="br-panel">
          <div class="br-panel-head"><div><h2 class="br-section-title">Automation profile</h2><div class="br-muted">Aktif demo yedekleme planı</div></div>
            ${badge(p.enabled ? "Enabled" : "Disabled", p.enabled ? "ok" : "warn")}</div>
          <div class="br-panel-body">
            <div class="br-profile"><div class="br-profile-icon">▤</div><div>
              <div class="br-profile-name">${esc(p.name)}</div>
              <div class="br-muted">Full backup · Her çalıştırmada tam yedek simülasyonu</div>
              <div class="br-badges">${badge(p.frequency === "custom" ? "Custom schedule" : p.frequency === "twice" ? "Twice daily" : "Daily")} ${badge(`${p.retention} day retention`)} ${badge("Single destination")}</div>
            </div></div>
            <div style="margin-top:20px" class="br-actions">
              <button class="br-btn br-btn-primary" data-action="run" ${p.enabled ? "" : "disabled"}>▶ Run demo backup</button>
              <button class="br-btn" data-tab="automation">Edit automation</button>
              <button class="br-btn" data-action="toggle">${p.enabled ? "Disable profile" : "Enable profile"}</button>
            </div>
          </div>
        </article>
        <article class="br-panel">
          <div class="br-panel-head"><h2 class="br-section-title">Repository status</h2>${badge("Demo repository")}</div>
          <div class="br-panel-body">
            <div class="br-kv"><span>Destination</span><strong>${esc(p.target || "Not configured")}</strong></div>
            <div class="br-kv"><span>Last run</span><strong>${latest ? esc(fmtDate(latest.finishedAt)) : "No runs yet"}</strong></div>
            <div class="br-kv"><span>Last result</span><strong>${latest ? statusBadge(latest.status) : "—"}</strong></div>
            <div class="br-kv"><span>Integrity verification</span><strong>${p.verify ? "Enabled (simulated)" : "Disabled"}</strong></div>
            <div class="br-progress"><span style="width:${state.jobs.length ? 100 : 0}%"></span></div>
            <div class="br-muted">Repository health and capacity are illustrative only; no real storage is inspected.</div>
          </div>
        </article>
      </section>
      <section class="br-section">
        <div class="br-section-head"><h2 class="br-section-title">Recent activity</h2><button class="br-btn" data-tab="history">View all</button></div>
        <div class="br-panel">${state.jobs.length ? jobsTable(state.jobs.slice(0,5)) : empty("◷","No backup jobs yet","Run a demo backup to create the first history entry.")}</div>
      </section>`;
  }

  function automation() {
    const p = state.profile;
    return `${navTabs()}
      <section class="br-panel">
        <div class="br-panel-head"><div><h2 class="br-section-title">Backup automation</h2><div class="br-muted">Ayarlar bu tarayıcıda demo olarak saklanır.</div></div>${badge("Full backup")}</div>
        <form id="br-profile-form" class="br-panel-body">
          <div class="br-form-grid">
            <div class="br-field"><label for="br-name">Profile name</label><input id="br-name" name="name" maxlength="80" required value="${esc(p.name)}"></div>
            <div class="br-field"><label for="br-scope">Backup scope</label><select id="br-scope" name="scope"><option value="full" selected>Full Cartman system (demo)</option></select><small>Her çalıştırmada tam yedek işlemi simüle edilir.</small></div>
            <div class="br-field"><label for="br-frequency">Schedule frequency</label><select id="br-frequency" name="frequency">
              <option value="daily" ${p.frequency==="daily"?"selected":""}>Daily</option>
              <option value="twice" ${p.frequency==="twice"?"selected":""}>Twice daily</option>
              <option value="custom" ${p.frequency==="custom"?"selected":""}>Custom schedule</option>
            </select></div>
            <div class="br-field"><label for="br-time">Preferred start time</label><input id="br-time" name="time" type="time" value="${esc(p.time)}" required><small>Demo sürümünde otomatik zamanlayıcı çalışmaz.</small></div>
            <div class="br-field"><label for="br-retention">Retention (days)</label><input id="br-retention" name="retention" type="number" min="1" max="3650" required value="${Number(p.retention) || 30}"><small>Yalnızca demo profil ayarıdır; otomatik silme yapılmaz.</small></div>
            <div class="br-field"><label for="br-target">Repository label</label><input id="br-target" name="target" maxlength="120" value="${esc(p.target)}"><small>Gerçek bir dosya yolu veya bağlantı değildir.</small></div>
          </div>
          <div style="margin-top:18px">
            <div class="br-toggle-row"><div><strong style="font-size:13px">Enable profile</strong><div class="br-muted">Demo profili manuel çalıştırma için etkin tut.</div></div><input class="br-toggle" type="checkbox" name="enabled" ${p.enabled?"checked":""} aria-label="Enable profile"></div>
            <div class="br-toggle-row"><div><strong style="font-size:13px">Integrity verification</strong><div class="br-muted">Demo işine doğrulama sonucu ekle.</div></div><input class="br-toggle" type="checkbox" name="verify" ${p.verify?"checked":""} aria-label="Integrity verification"></div>
          </div>
          <div class="br-actions" style="margin-top:18px">
            <button class="br-btn br-btn-primary" type="submit">Save demo settings</button>
            <button class="br-btn" type="button" data-action="reset">Reset defaults</button>
          </div>
        </form>
      </section>
      <div class="br-notice br-notice-info"><strong>Production notu:</strong> Gerçek otomasyon için backend scheduler/worker, kalıcı sunucu veritabanı, güvenli kimlik bilgisi yönetimi ve erişilebilir bir yedek hedefi gerekir. Bu demo bunları çalıştırmaz.</div>`;
  }

  function jobsTable(jobs) {
    return `<div class="br-table-wrap"><table class="br-table">
      <thead><tr><th>Job ID</th><th>Started</th><th>Type</th><th>Reported size</th><th>Verification</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>${jobs.map(j => `<tr>
        <td><strong>${esc(j.id)}</strong></td><td>${esc(fmtDate(j.startedAt))}</td><td>Full backup</td>
        <td>${esc(fmtSize(j.bytes || 0))}</td><td>${j.verified ? badge("Passed","ok") : badge("N/A")}</td>
        <td>${statusBadge(j.status)}</td><td><button class="br-btn" data-action="details" data-id="${esc(j.id)}">Details</button></td>
      </tr>`).join("")}</tbody>
    </table></div>`;
  }

  function history() {
    return `${navTabs()}
      <section class="br-section">
        <div class="br-section-head"><div><h2 class="br-section-title">Backup history</h2><div class="br-muted">Bu liste yalnızca simüle edilmiş demo işlerini içerir.</div></div>
          <button class="br-btn" data-action="export">⇩ Export demo data</button></div>
        <div class="br-panel">${state.jobs.length ? jobsTable(state.jobs) : empty("◷","No history available","Run demo backup to populate this table.")}</div>
      </section>`;
  }

  function recovery() {
    const completed = state.jobs.filter(j => j.status === "Completed");
    return `${navTabs()}
      <section class="br-notice br-notice-warn"><strong>Restore safety:</strong> Bu sayfa gerçek bir yedeği geri yüklemez ve hiçbir dosyanın üzerine yazmaz. Aşağıdaki akış yalnızca demo davranışını gösterir.</section>
      <section class="br-panel">
        <div class="br-panel-head"><div><h2 class="br-section-title">Recovery points</h2><div class="br-muted">Başarılı demo işlerinden oluşturulan temsili kurtarma noktaları.</div></div>${badge(`${completed.length} available`)}</div>
        ${completed.length ? `<div class="br-table-wrap"><table class="br-table"><thead><tr><th>Recovery point</th><th>Created</th><th>Reported size</th><th>Integrity</th><th>Action</th></tr></thead><tbody>
        ${completed.map(j => `<tr><td><strong>${esc(j.id)}</strong></td><td>${esc(fmtDate(j.finishedAt))}</td><td>${esc(fmtSize(j.bytes || 0))}</td><td>${j.verified ? badge("Passed","ok") : badge("Not verified","warn")}</td><td><button class="br-btn" data-action="restore" data-id="${esc(j.id)}">Simulate restore</button></td></tr>`).join("")}
        </tbody></table></div>` : empty("↶","No recovery points","Complete a demo backup first.") }
      </section>
      <section class="br-panel"><div class="br-panel-head"><h2 class="br-section-title">Recovery readiness</h2></div><div class="br-panel-body">
        <div class="br-kv"><span>Backup artifact</span><strong>Simulated</strong></div>
        <div class="br-kv"><span>Restore destination</span><strong>Not configured</strong></div>
        <div class="br-kv"><span>Actual restore test</span><strong>Not performed</strong></div>
        <div class="br-kv"><span>Recovery runbook</span><strong>Demo preview only</strong></div>
      </div></section>`;
  }

  function render() {
    const content = state.activeTab === "automation" ? automation()
      : state.activeTab === "history" ? history()
      : state.activeTab === "recovery" ? recovery() : overview();
    shell(content);
  }

  function runDemo() {
    if (!state.profile.enabled) {
      setNotice("Profil devre dışı. Önce Automation sekmesinden etkinleştir.", "warn");
      render(); return;
    }
    const now = new Date();
    const id = "DEMO-" + now.toISOString().replace(/[-:TZ.]/g,"").slice(0,14) + "-" + Math.random().toString(36).slice(2,6).toUpperCase();
    const fail = Math.random() < 0.08;
    const job = {
      id, status: fail ? "Failed" : "Completed",
      startedAt: now.toISOString(),
      finishedAt: new Date(now.getTime() + 1200 + Math.floor(Math.random()*3500)).toISOString(),
      bytes: fail ? 0 : 180000000 + Math.floor(Math.random()*2100000000),
      verified: !fail && Boolean(state.profile.verify),
      type: "full-demo",
      message: fail ? "Simulated failure; no real backup was attempted." : "Simulated completion; no real files were read."
    };
    state.jobs.unshift(job);
    state.jobs = state.jobs.slice(0,100);
    state.activeTab = "history";
    persist();
    setNotice(fail ? "Demo işi başarısız olarak kaydedildi; gerçek sistem etkilenmedi." : "Demo backup tamamlandı olarak kaydedildi. Gerçek dosya yedeği alınmadı.", fail ? "warn" : "info");
    render();
  }

  function exportData() {
    const payload = JSON.stringify({
      exportedAt: new Date().toISOString(),
      demoOnly: true,
      profile: state.profile,
      jobs: state.jobs
    }, null, 2);
    const blob = new Blob([payload], {type:"application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "cartman-backup-demo-data.json";
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    setNotice("Demo verileri JSON olarak dışa aktarıldı; bu bir sistem yedeği değildir.");
    render();
  }

  root.addEventListener("click", event => {
    const button = event.target.closest("[data-action],[data-tab]");
    if (!button || !root.contains(button) || button.disabled) return;
    if (button.dataset.tab) {
      state.activeTab = button.dataset.tab;
      persist(); render(); return;
    }
    switch (button.dataset.action) {
      case "run": runDemo(); break;
      case "toggle":
        state.profile.enabled = !state.profile.enabled;
        persist(); setNotice(`Demo profili ${state.profile.enabled ? "etkinleştirildi" : "devre dışı bırakıldı"}.`);
        render(); break;
      case "reset":
        state.profile = clone(defaults.profile);
        persist(); setNotice("Varsayılan demo ayarları geri yüklendi."); render(); break;
      case "export": exportData(); break;
      case "details": {
        const job = state.jobs.find(j => j.id === button.dataset.id);
        if (job) {
          setNotice(`${job.id}: ${job.message || "Demo job"} · Status: ${job.status} · Reported size: ${fmtSize(job.bytes || 0)}`);
          render();
        }
        break;
      }
      case "restore": {
        const job = state.jobs.find(j => j.id === button.dataset.id);
        if (job) {
          setNotice(`DEMO RESTORE: ${job.id} için kurtarma akışı simüle edildi. Gerçek dosyalar değiştirilmedi.`, "info");
          render();
        }
        break;
      }
    }
  });

  root.addEventListener("submit", event => {
    if (event.target.id !== "br-profile-form") return;
    event.preventDefault();
    const form = event.target;
    const data = new FormData(form);
    state.profile = {
      name: String(data.get("name") || "").trim().slice(0,80) || defaults.profile.name,
      scope: "full",
      frequency: ["daily","twice","custom"].includes(data.get("frequency")) ? data.get("frequency") : "daily",
      time: /^\d{2}:\d{2}$/.test(data.get("time")) ? data.get("time") : "02:00",
      retention: Math.max(1,Math.min(3650,Number(data.get("retention")) || 30)),
      target: String(data.get("target") || "").trim().slice(0,120),
      enabled: form.elements.enabled.checked,
      verify: form.elements.verify.checked
    };
    persist();
    state.activeTab = "automation";
    setNotice("Demo otomasyon ayarları bu tarayıcıya kaydedildi. Sunucuda gerçek otomasyon başlatılmadı.");
    render();
  });

  render();
})();
