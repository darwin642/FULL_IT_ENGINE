/* CARTMAN_WORKFLOWS_LIVE_UI_V1 */
(() => {
  "use strict";
  if (window.__cartmanWorkflowsLiveUiV1) return;
  window.__cartmanWorkflowsLiveUiV1 = true;

  const state = { user: null, items: [], loading: true, error: "", notice: "", query: "", filter: "all", triggerFilter: "all", modal: false, editing: null, draft: null, runsFor: null, runs: [], runsLoading: false, saving: false };
  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const asDate = value => { if (!value) return "Not run yet"; const d = new Date(String(value).replace(" ", "T") + (String(value).endsWith("Z") ? "" : "Z")); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString(); };
  const dateSort = value => { const d = new Date(String(value || "").replace(" ", "T") + (String(value || "").endsWith("Z") ? "" : "Z")); return Number.isNaN(d.getTime()) ? 0 : d.getTime(); };
  const button = (label, action, variant = "", extra = "") => `<button type="button" class="wfl-btn ${variant} ${extra}" data-wfl-action="${action}">${label}</button>`;
  const badge = status => { const key = String(status || "Disabled").toLowerCase(); const cls = key === "succeeded" || key === "enabled" ? "succeeded" : key === "failed" ? "failed" : key === "skipped" ? "skipped" : "disabled"; return `<span class="wfl-status ${cls}">${esc(status || "Disabled")}</span>`; };
  let root = null;

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) }, ...options, body: options.body ? JSON.stringify(options.body) : undefined });
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    const data = contentType.includes("application/json") ? await response.json() : null;
    if (response.redirected || response.status === 401) throw new Error("Your session has expired. Sign in again.");
    if (!response.ok) throw new Error(data?.detail || `Request failed (HTTP ${response.status}).`);
    return data;
  }

  function defaultStep(type = "create_task") {
    if (type === "condition") return { type, field: "alert.severity", operator: "equals", value: "critical" };
    if (type === "notify_user") return { type, recipient_username: "", title: "Workflow notification", message: "A workflow action requires your attention.", severity: "info", action_url: "/pages/notifications/" };
    return { type: "create_task", title: "Investigate monitoring alert", description: "Review the alert and record findings.", project: "Infrastructure", priority: "High", due: "Unscheduled", assigned_username: "" };
  }

  async function load() {
    state.loading = true; state.error = ""; render();
    try {
      const [session, result] = await Promise.all([api("/api/auth/me"), api("/api/workflows")]);
      state.user = session?.user || null;
      state.items = Array.isArray(result?.items) ? result.items : [];
      state.canManage = Boolean(result?.can_manage && state.user?.role === "admin");
      state.loading = false; render();
    } catch (error) {
      state.loading = false; state.error = error.message || "Could not load workflows from Cartman API."; render();
    }
  }

  function filteredItems() {
    const q = state.query.trim().toLocaleLowerCase();
    return state.items.filter(item => {
      const haystack = [item.name, item.description, item.id, item.trigger_type, item.trigger_event, ...(item.steps || []).map(step => [step.type, step.title, step.message, step.recipient_username, step.assigned_username].join(" "))].join(" ").toLocaleLowerCase();
      return (!q || haystack.includes(q)) && (state.filter === "all" || (state.filter === "enabled" ? item.enabled : !item.enabled)) && (state.triggerFilter === "all" || item.trigger_type === state.triggerFilter);
    });
  }

  function triggerLabel(item) {
    if (item.trigger_type === "interval") return `Every ${Number(item.interval_minutes) || 60} minutes`;
    if (item.trigger_type === "event") return item.trigger_event === "monitoring.critical_alert" ? "Critical Monitoring alert" : "New Monitoring alert";
    return "Manual run";
  }

  function workflowCard(item) {
    const runOpen = String(state.runsFor) === String(item.id);
    const latest = item.last_run_status || "Never run";
    const isAdmin = state.canManage;
    return `<article class="wfl-card" data-wfl-card data-id="${item.id}" data-search="${esc([item.name,item.description,item.trigger_type,item.trigger_event].join(" ").toLowerCase())}" data-enabled="${item.enabled ? "enabled" : "disabled"}" data-trigger="${esc(item.trigger_type)}">
      <div class="wfl-card-main"><div class="wfl-title-area"><span class="wfl-flow-icon" aria-hidden="true">⇢</span><div class="wfl-title-copy"><span class="wfl-id">WFL-${String(item.id).padStart(4,"0")} · ${Number(item.steps?.length || 0)} step(s)</span><div class="wfl-title">${esc(item.name)}</div><div class="wfl-description">${esc(item.description || "No description provided.")}</div></div></div>
      <div class="wfl-trigger">${esc(triggerLabel(item))}<small>${item.trigger_type === "event" ? "Event-driven" : item.trigger_type === "interval" ? "Scheduled trigger" : "Operator initiated"}</small></div>
      <div class="wfl-last-run">${badge(latest)}<small>${esc(asDate(item.last_run_at))}</small></div>
      <div class="wfl-card-actions">${isAdmin ? `<label class="wfl-toggle"><input type="checkbox" data-wfl-toggle="${item.id}" ${item.enabled ? "checked" : ""}> Enabled</label>${button("Run now","run","small primary")}${button("Edit","edit","small")}${button(runOpen ? "Hide history" : "History","history","small")}${button("Archive","archive","small danger")}` : button(runOpen ? "Hide history" : "History","history","small")}</div></div>
      ${runOpen ? renderRunsPanel() : ""}</article>`;
  }

  function renderRunsPanel() {
    if (state.runsLoading) return `<div class="wfl-runs-panel"><div class="wfl-empty">Loading execution history…</div></div>`;
    if (!state.runs.length) return `<div class="wfl-runs-panel"><div class="wfl-empty">No execution runs recorded yet.</div></div>`;
    return `<div class="wfl-runs-panel"><div class="wfl-runs-head"><strong>Execution history · ${state.runs.length} most recent run(s)</strong>${button("Refresh","history-refresh","small")}</div>${state.runs.map(run => `<div class="wfl-run-row"><span class="wfl-run-time">${esc(asDate(run.started_at))}</span><span>${badge(run.status)}<small style="display:block;color:var(--wfl-muted);margin-top:4px">${esc(run.trigger_source)} · #${run.id}</small></span><div class="wfl-run-summary"><strong>${esc(run.summary || "No summary")}</strong>${run.error_message ? `<div class="wfl-form-error">${esc(run.error_message)}</div>` : ""}<div class="wfl-step-results">${(run.steps || []).map(step => `<div class="wfl-step-result"><strong>${Number(step.index) || ""}. ${esc(step.type)} — ${esc(step.status)}</strong>${step.error ? ` · ${esc(step.error)}` : step.result?.message ? ` · ${esc(step.result.message)}` : step.result?.task_key ? ` · Created ${esc(step.result.task_key)}` : step.result?.notification_id ? ` · Notification #${esc(step.result.notification_id)}` : ""}</div>`).join("")}</div></div></div>`).join("")}</div>`;
  }

  function render() {
    if (!root) return;
    const items = filteredItems();
    const enabled = state.items.filter(item => item.enabled).length;
    const runs24h = state.items.reduce((sum,item)=>sum+Number(item.runs_24h||0),0);
    const failures24h = state.items.reduce((sum,item)=>sum+Number(item.failures_24h||0),0);
    root.innerHTML = `<div class="wfl-root">
      <header class="wfl-hero"><div><div class="wfl-kicker">Automation engine / orchestration</div><h1>Workflows</h1><p>Build reliable, auditable processes by connecting events, conditions, operational tasks and targeted notifications. Workflow definitions and execution history are stored in Cartman’s database.</p></div><div class="wfl-actions">${button("↻ Refresh","refresh")}${state.canManage ? button("＋ Create workflow","new","primary") : ""}</div></header>
      <div class="wfl-banner"><span class="wfl-banner-dot"></span><div><strong>Live API connected</strong><br>Definitions, enablement, scheduled runs and execution logs are backed by the Cartman API. Actions are allow-listed; workflow steps do not execute arbitrary code.</div></div>
      ${state.error ? `<div class="wfl-banner" role="alert"><span style="color:var(--danger,#d45b62);font-size:17px">!</span><div><strong>Workflow API error</strong><br>${esc(state.error)}</div>${button("Retry","refresh","small")}</div>` : ""}
      ${state.notice ? `<div class="wfl-banner"><span class="wfl-banner-dot"></span><div>${esc(state.notice)}</div><button class="wfl-btn small" data-wfl-action="dismiss-notice" type="button">×</button></div>` : ""}
      <div class="wfl-metrics"><article class="wfl-metric"><span class="wfl-metric-label">▤ Total workflows</span><strong class="wfl-metric-value">${state.loading ? "—" : state.items.length}</strong><small class="wfl-metric-hint">Saved in database</small></article><article class="wfl-metric"><span class="wfl-metric-label">● Enabled</span><strong class="wfl-metric-value">${state.loading ? "—" : enabled}</strong><small class="wfl-metric-hint">Schedules and event triggers active</small></article><article class="wfl-metric"><span class="wfl-metric-label">↻ Runs · 24 hours</span><strong class="wfl-metric-value">${state.loading ? "—" : runs24h}</strong><small class="wfl-metric-hint">Actual executions recorded</small></article><article class="wfl-metric"><span class="wfl-metric-label">! Failures · 24 hours</span><strong class="wfl-metric-value">${state.loading ? "—" : failures24h}</strong><small class="wfl-metric-hint">Requires investigation</small></article></div>
      <div class="wfl-toolbar"><label class="wfl-field grow">Search workflows<input data-wfl-search type="search" placeholder="Name, trigger, description or step…" value="${esc(state.query)}"></label><label class="wfl-field">State<select data-wfl-filter><option value="all" ${state.filter==="all"?"selected":""}>All states</option><option value="enabled" ${state.filter==="enabled"?"selected":""}>Enabled</option><option value="disabled" ${state.filter==="disabled"?"selected":""}>Disabled</option></select></label><label class="wfl-field">Trigger<select data-wfl-trigger-filter><option value="all" ${state.triggerFilter==="all"?"selected":""}>All triggers</option><option value="manual" ${state.triggerFilter==="manual"?"selected":""}>Manual</option><option value="interval" ${state.triggerFilter==="interval"?"selected":""}>Schedule</option><option value="event" ${state.triggerFilter==="event"?"selected":""}>Monitoring event</option></select></label><span class="wfl-filter-count">${items.length} of ${state.items.length} workflow(s)</span></div>
      <div class="wfl-list">${state.loading ? `<div class="wfl-empty">Loading workflow definitions from Cartman API…</div>` : items.length ? items.map(workflowCard).join("") : `<div class="wfl-empty"><strong>${state.items.length ? "No workflows match these filters" : "Your workflow library is empty"}</strong>${state.items.length ? "Try a different search or filter." : (state.canManage ? "Create a workflow to start automating a repeatable operational process." : "An administrator has not created any workflows yet.")}</div>`}</div>
      <div class="wfl-banner" style="margin-top:14px"><span>ⓘ</span><div><strong>Execution safety</strong><br>Scheduled and event-driven workflows run on the Cartman server. Current actions create an operational task, send a persistent notification to an active Cartman account, or evaluate a condition. Network/device commands are intentionally not available as workflow actions in this version.</div></div>
    </div>${state.modal ? editorMarkup() : ""}`;
  }

  function field(label, name, value, options = {}) {
    const type = options.type || "text";
    const cls = options.full ? "wfl-field full" : "wfl-field";
    if (options.select) return `<label class="${cls}">${label}<select data-wfl-field="${name}">${options.select.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(value)?"selected":""}>${esc(t)}</option>`).join("")}</select></label>`;
    if (type === "textarea") return `<label class="${cls}">${label}<textarea data-wfl-field="${name}" rows="${options.rows || 2}" maxlength="${options.maxlength || 1200}" placeholder="${esc(options.placeholder || "")}">${esc(value || "")}</textarea></label>`;
    return `<label class="${cls}">${label}<input data-wfl-field="${name}" type="${type}" value="${esc(value || "")}" maxlength="${options.maxlength || 300}" placeholder="${esc(options.placeholder || "")}" ${options.required ? "required" : ""} ${options.min != null ? `min="${options.min}"` : ""} ${options.max != null ? `max="${options.max}"` : ""}></label>`;
  }

  function stepMarkup(step, index) {
    const typeOptions = [["condition","Condition · continue only if matched"],["create_task","Create operational task"],["notify_user","Send Cartman notification"]];
    let specific = "";
    if (step.type === "condition") {
      specific = field("Input field path", "field", step.field || "alert.severity", {placeholder:"alert.severity",required:true}) + field("Operator", "operator", step.operator || "equals", {select:[["equals","Equals"],["not_equals","Does not equal"],["contains","Contains"],["greater_than","Greater than"],["less_than","Less than"],["exists","Exists"]]}) + field("Expected value", "value", step.value || "critical", {required:false}) + `<div class="wfl-step-help">Use event fields such as <code>alert.severity</code>, <code>alert.status</code> or <code>alert.title</code>. If this condition fails, remaining steps are skipped.</div>`;
    } else if (step.type === "notify_user") {
      specific = field("Recipient username", "recipient_username", step.recipient_username || "", {required:true,placeholder:"e.g. benbendeilim"}) + field("Severity", "severity", step.severity || "info", {select:[["info","Information"],["success","Success"],["warning","Warning"],["critical","Critical"]]}) + field("Notification title", "title", step.title || "Workflow notification", {full:true,required:true,maxlength:180}) + field("Message", "message", step.message || "", {type:"textarea",full:true,rows:3,maxlength:1200,required:true}) + field("Action URL", "action_url", step.action_url || "/pages/notifications/", {full:true,placeholder:"/pages/notifications/"}) + `<div class="wfl-step-help">The recipient must be an active Cartman account. The notification is persisted on the server and delivered through the global toast polling channel. Message templates support tokens such as {{alert.title}}, {{alert.device_id}} and {{alert.severity}}.</div>`;
    } else {
      specific = field("Task title", "title", step.title || "", {full:true,required:true,maxlength:200,placeholder:"Investigate alert on server"}) + field("Project / workstream", "project", step.project || "Infrastructure", {required:true,maxlength:80}) + field("Priority", "priority", step.priority || "High", {select:[["Critical","Critical"],["High","High"],["Normal","Normal"],["Low","Low"]]}) + field("Due date", "due", step.due === "Unscheduled" ? "" : (step.due || ""), {type:"date"}) + field("Assign to username (optional)", "assigned_username", step.assigned_username || "", {placeholder:"Leave blank for Unassigned"}) + field("Description / instructions", "description", step.description || "", {type:"textarea",full:true,rows:3,maxlength:5000});
    }
    return `<section class="wfl-step" data-wfl-step data-step-index="${index}"><div class="wfl-step-head"><span class="wfl-step-number">${String(index+1).padStart(2,"0")}</span><select class="wfl-select" data-wfl-step-type aria-label="Step ${index+1} type">${typeOptions.map(([v,t])=>`<option value="${v}" ${v===step.type?"selected":""}>${t}</option>`).join("")}</select>${button("Remove","remove-step","small danger")}</div><div class="wfl-step-fields">${specific}</div></section>`;
  }

  function editorMarkup() {
    const draft = state.draft || {};
    const editing = Boolean(state.editing);
    const steps = Array.isArray(draft.steps) && draft.steps.length ? draft.steps : [defaultStep()];
    const triggers = [["manual","Manual · operator starts the workflow"],["interval","Scheduled · repeat every N minutes"],["event","Monitoring · on a new alert"]];
    const eventOptions = [["monitoring.new_alert","Any new Monitoring alert"],["monitoring.critical_alert","Critical / error alert only"],["monitoring.device_offline","Device offline / unreachable alert"]];
    return `<div class="wfl-overlay" data-wfl-overlay><section class="wfl-modal" role="dialog" aria-modal="true" aria-labelledby="wfl-editor-title"><form data-wfl-form><header class="wfl-modal-head"><div><div class="wfl-kicker">Workflow designer / database-backed</div><h2 id="wfl-editor-title">${editing ? "Edit workflow" : "Create workflow"}</h2><p>Configure the trigger, then order conditions and actions. Saved steps are executed and audited by the Cartman API.</p></div><button type="button" class="wfl-btn" data-wfl-action="close-editor" aria-label="Close">×</button></header><div class="wfl-modal-body">
      ${state.formError ? `<div class="wfl-form-error" role="alert">${esc(state.formError)}</div>` : ""}
      <div class="wfl-form-grid">${field("Workflow name","name",draft.name || "",{required:true,maxlength:120,full:true,placeholder:"e.g. Critical server alert response"})}${field("Description","description",draft.description || "",{type:"textarea",full:true,rows:2,maxlength:2000,placeholder:"What operational process does this workflow coordinate?"})}${field("Trigger","trigger_type",draft.trigger_type || "manual",{select:triggers})}${draft.trigger_type === "interval" ? field("Repeat every (minutes)","interval_minutes",draft.interval_minutes || 60,{type:"number",min:1,max:10080,required:true}) : draft.trigger_type === "event" ? field("Monitoring event","trigger_event",draft.trigger_event || "monitoring.critical_alert",{select:eventOptions}) : `<div class="wfl-field"><span>Execution mode</span><div class="wfl-banner" style="margin:0">Manual run from this page. The workflow may be tested before enabling it.</div></div>`}</div>
      <div class="wfl-section-title"><div><h3>Workflow steps</h3><p>Steps run in order. A failed step stops the run and records the error.</p></div>${button("＋ Add step","add-step","small")}</div><div class="wfl-step-list" data-wfl-step-list>${steps.map(stepMarkup).join("")}</div>
      <label class="wfl-enable-choice"><input type="checkbox" data-wfl-enabled ${draft.enabled ? "checked" : ""}><span><strong>Enable after saving</strong><br>Scheduled and Monitoring event triggers start running only when enabled. Scheduled workflows first run after the selected interval.</span></label>
      <div class="wfl-form-error" data-wfl-form-error></div></div><footer class="wfl-modal-foot"><span style="font-size:10px;color:var(--wfl-muted)">API validation is authoritative; invalid steps will not be saved.</span><div class="wfl-actions"><button type="button" class="wfl-btn" data-wfl-action="close-editor">Cancel</button><button type="submit" class="wfl-btn primary" ${state.saving?"disabled":""}>${state.saving ? "Saving…" : editing ? "Save workflow" : "Create workflow"}</button></div></footer></form></section></div>`;
  }

  function readStepsFromForm() {
    return [...root.querySelectorAll("[data-wfl-step]")].map(card => {
      const step = { type: card.querySelector("[data-wfl-step-type]")?.value || "create_task" };
      card.querySelectorAll("[data-wfl-field]").forEach(input => { step[input.dataset.wflField] = input.value; });
      if (step.type === "create_task" && !step.due) step.due = "Unscheduled";
      return step;
    });
  }
  function readDraftFromForm() {
    const form = root.querySelector("[data-wfl-form]");
    if (!form) return state.draft || {};
    return { name: form.querySelector('[data-wfl-field="name"]')?.value || "", description: form.querySelector('[data-wfl-field="description"]')?.value || "", trigger_type: form.querySelector('[data-wfl-field="trigger_type"]')?.value || "manual", trigger_event: form.querySelector('[data-wfl-field="trigger_event"]')?.value || "monitoring.critical_alert", interval_minutes: Number(form.querySelector('[data-wfl-field="interval_minutes"]')?.value || 60), enabled: Boolean(form.querySelector("[data-wfl-enabled]")?.checked), steps: readStepsFromForm() };
  }
  function showEditor(item) {
    state.editing = item ? item.id : null;
    state.draft = item ? { name:item.name, description:item.description, trigger_type:item.trigger_type, trigger_event:item.trigger_event, interval_minutes:item.interval_minutes, enabled:item.enabled, steps:(item.steps||[]).map(step=>({...step})) } : { name:"", description:"", trigger_type:"manual", trigger_event:"monitoring.critical_alert", interval_minutes:60, enabled:false, steps:[defaultStep()] };
    state.modal = true; state.formError = ""; render();
    root.querySelector('[data-wfl-field="name"]')?.focus();
  }
  async function loadRuns(id) {
    state.runsFor = id; state.runsLoading = true; state.runs = []; render();
    try { const result = await api(`/api/workflows/${id}/runs?limit=30`); state.runs = result.items || []; }
    catch (error) { state.error = error.message || "Could not load workflow history."; }
    finally { state.runsLoading = false; render(); }
  }
  function toast(title, message, severity = "success") { if (window.CartmanToast?.notify) window.CartmanToast.notify({title,message,severity,source:"Workflows",duration:7000}); }

  async function onClick(event) {
    const buttonNode = event.target.closest("[data-wfl-action]");
    if (!buttonNode) return;
    const action = buttonNode.dataset.wflAction;
    const card = buttonNode.closest("[data-wfl-card]");
    const id = Number(card?.dataset.id || 0);
    try {
      if (action === "new") { showEditor(null); return; }
      if (action === "refresh") { await load(); return; }
      if (action === "dismiss-notice") { state.notice = ""; render(); return; }
      if (action === "close-editor") { state.modal = false; state.formError = ""; render(); return; }
      if (action === "add-step" || action === "remove-step") {
        const draft = readDraftFromForm();
        if (action === "add-step") { if (draft.steps.length >= 20) { state.formError = "A workflow supports up to 20 steps."; } else draft.steps.push(defaultStep()); }
        else { const index = Number(buttonNode.closest("[data-wfl-step]")?.dataset.stepIndex); if (draft.steps.length <= 1) state.formError = "Keep at least one step in the workflow."; else draft.steps.splice(index,1); }
        state.draft = draft; render(); return;
      }
      if (action === "edit") { if (!state.canManage) return; showEditor(state.items.find(item=>item.id===id)); return; }
      if (action === "history" || action === "history-refresh") { if (action === "history" && String(state.runsFor)===String(id)) { state.runsFor=null; state.runs=[]; render(); } else await loadRuns(id); return; }
      if (action === "run") {
        if (!state.canManage) return;
        buttonNode.disabled = true; buttonNode.textContent = "Running…";
        const result = await api(`/api/workflows/${id}/run`, {method:"POST", body:{input:{operator_initiated:true}}});
        state.notice = `Run #${result.id} finished: ${result.status}. ${result.summary || ""}`;
        toast(`Workflow ${result.status.toLowerCase()}`, result.summary || `Run #${result.id} completed.`, result.status === "Failed" ? "error" : "success");
        await load(); await loadRuns(id); return;
      }
      if (action === "archive") {
        if (!state.canManage) return;
        const item = state.items.find(value=>value.id===id);
        if (!window.confirm(`Archive workflow “${item?.name || id}”? Execution history will be preserved.`)) return;
        await api(`/api/workflows/${id}`, {method:"DELETE"}); state.notice = "Workflow archived. Execution history was preserved."; await load(); return;
      }
    } catch (error) {
      state.error = error.message || "Workflow operation failed.";
      if (state.modal) state.formError = state.error;
      render();
    }
  }

  async function onChange(event) {
    const target = event.target;
    if (target.matches("[data-wfl-filter]")) { state.filter = target.value; render(); return; }
    if (target.matches("[data-wfl-trigger-filter]")) { state.triggerFilter = target.value; render(); return; }
    if (target.matches("[data-wfl-toggle]")) {
      const id = Number(target.dataset.wflToggle);
      target.disabled = true;
      try { await api(`/api/workflows/${id}/toggle`, {method:"POST", body:{enabled:target.checked}}); state.notice = target.checked ? "Workflow enabled." : "Workflow disabled."; await load(); }
      catch (error) { state.error = error.message; await load(); }
      return;
    }
    if (target.matches("[data-wfl-step-type]")) {
      const draft = readDraftFromForm();
      const index = Number(target.closest("[data-wfl-step]")?.dataset.stepIndex);
      draft.steps[index] = {...defaultStep(target.value), type:target.value};
      state.draft = draft; render(); return;
    }
    if (target.matches('[data-wfl-field="trigger_type"]')) {
      state.draft = readDraftFromForm(); state.draft.trigger_type = target.value; render(); return;
    }
  }

  async function onSubmit(event) {
    if (!event.target.matches("[data-wfl-form]")) return;
    event.preventDefault();
    const draft = readDraftFromForm();
    state.saving = true; state.draft = draft; state.formError = ""; render();
    try {
      const result = await api(state.editing ? `/api/workflows/${state.editing}` : "/api/workflows", {method:state.editing ? "PUT" : "POST", body:draft});
      state.modal = false; state.editing = null; state.notice = `Workflow “${result.name}” saved to the Cartman database.`; state.saving = false;
      toast("Workflow saved", result.name, "success"); await load();
    } catch (error) {
      state.saving = false; state.formError = error.message || "Could not save workflow."; state.draft = draft; render();
    }
  }

  function mount() {
    const main = document.querySelector("main");
    if (!main || !location.pathname.replace(/\/+$/, "").endsWith("/workflows")) return;
    main.innerHTML = `<div class="module-header"><span class="category-icon purple">⇢</span><div><div class="eyebrow">CARTMAN WORKSPACE / AUTOMATION ENGINE</div><h1>Workflows</h1><p>Design, run and audit multi-step operational processes.</p></div></div><section id="cartman-workflows-live-root" aria-label="Live Workflows designer"></section><footer class="app-footer cartman-version-footer"><span>Cartman v0.2.3d pre-alpha-0111260212</span></footer>`;
    root = $("#cartman-workflows-live-root", main);
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    root.addEventListener("submit", onSubmit);
    root.addEventListener("input", event => {
      if (event.target.matches("[data-wfl-search]")) { state.query = event.target.value; const position = event.target.selectionStart; render(); const next = root.querySelector("[data-wfl-search]"); if (next) { next.focus(); next.setSelectionRange(position, position); } }
      if (event.target.matches("[data-wfl-field]") && state.modal) { state.draft = readDraftFromForm(); }
    });
    document.addEventListener("keydown", event => { if (event.key === "Escape" && state.modal) { state.modal=false; render(); } });
    void load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once:true}); else mount();
})();
