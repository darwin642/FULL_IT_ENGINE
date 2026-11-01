/* CARTMAN_AUTOMATED_TRIGGERS_UI_V3 */
(() => {
  "use strict";
  if (window.__cartmanAutomatedTriggers === "CARTMAN_AUTOMATED_TRIGGERS_UI_V3") return;
  window.__cartmanAutomatedTriggers = "CARTMAN_AUTOMATED_TRIGGERS_UI_V3";
  const root = document.querySelector("#cartman-alerts-root");
  if (!root) { console.error("Automated Triggers: #cartman-alerts-root was not found. Ensure Alerts Management is installed first."); return; }
  const $ = (s, r=root) => r.querySelector(s);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[c]));
  const state = { meta:{devices:[],departments:[],groups:[],can_manage:false}, items:[], targetType:"computer", metrics:["CPU"], threshold:80, notifyGroup:false, emailEnabled:false, saving:false, loading:true, error:"", note:"", view:"list", editingId:null };
  const nav = $(".cam-tabs");
  if (!nav || nav.querySelector("[data-at-tab]")) return;
  const tab = document.createElement("button"); tab.type="button"; tab.dataset.atTab="1"; tab.innerHTML='Automated Triggers <span data-at-count>—</span>';
  nav.appendChild(tab);
  const panel = document.createElement("section"); panel.id="cam-automated-triggers"; panel.className="cat-root"; panel.hidden=true;
  panel.innerHTML = `
    <header class="cat-heading"><div><div class="cat-eyebrow"><span></span> RULE MANAGEMENT</div><h2>Automated Triggers</h2><p>Review and manage your saved rules. Use New Trigger to build a rule.</p></div><div class="cat-heading-actions"><button class="cam-btn" type="button" data-at-action="refresh">↻ Refresh</button><button class="cam-btn cam-btn-primary" type="button" data-at-action="new">＋ New Trigger</button></div></header>
    <div class="cat-note" role="status" data-at-note hidden></div><div class="cat-error" role="alert" data-at-error hidden></div>
    <section class="cat-list-view" data-at-view="list" aria-label="Saved automated triggers">
      <div class="cat-list-toolbar">
        <label class="cat-field cat-list-search"><span>Search rules</span><input type="search" data-at-rule-search placeholder="Rule name, device, metric or notification…"></label>
        <label class="cat-field"><span>Status</span><select data-at-rule-filter><option value="all">All rules</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></label>
        <label class="cat-field"><span>Sort by</span><select data-at-rule-sort><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="name">Name A–Z</option><option value="severity">Target / metric</option></select></label>
      </div>
      <section class="cat-saved-section"><div class="cat-saved-heading"><div><h3>Saved triggers</h3><p>Enable, disable or delete configured monitoring rules.</p></div><span class="cat-count" data-at-total>—</span></div><div class="cat-rule-list" data-at-list><div class="cat-empty">Loading saved trigger rules…</div></div></section>
    </section>
    <section class="cat-builder-view" data-at-view="builder" aria-label="New automated trigger" hidden>
      <header class="cat-builder-toolbar"><div><div class="cat-eyebrow"><span></span> <span data-at-builder-eyebrow>NEW RULE</span></div><h3 data-at-builder-title>Create automated trigger</h3><p>Complete each puzzle piece, review the result, then save the rule.</p></div><button type="button" class="cam-btn" data-at-action="cancel">← Back to triggers</button></header>
      <label class="cat-field cat-rule-name-field"><span>Trigger name</span><input type="text" data-at-name maxlength="120" placeholder="e.g. HL-DC01 High Resource Usage" autocomplete="off"></label>
      <section class="cat-puzzle-board" aria-label="Automated trigger rule builder">
        <div class="cat-step cat-step-target"><div class="cat-step-head"><span class="cat-step-number">01</span><div><h3>Target</h3><p>Choose one computer or an entire department.</p></div></div>
          <div class="cat-segment"><button type="button" data-at-target="computer" class="is-active">Computer</button><button type="button" data-at-target="department_computers">Department Computers</button></div>
          <label class="cat-field"><span data-at-target-label>Computer</span><select data-at-computer><option value="">Loading devices…</option></select></label>
          <label class="cat-field" data-at-department-wrap hidden><span>Department</span><select data-at-department><option value="">Choose a department…</option></select></label>
        </div>
        <div class="cat-step cat-step-metric"><div class="cat-step-head"><span class="cat-step-number">02</span><div><h3>Metric</h3><p>Select one or more usage metrics.</p></div></div>
          <div class="cat-metric-grid">${["CPU","RAM","DISK","NETWORK"].map(m=>`<label class="cat-metric"><input type="checkbox" data-at-metric="${m}" ${m==="CPU"?"checked":""}><span class="cat-metric-check"></span><span class="cat-metric-name">${m}</span></label>`).join("")}</div>
        </div>
        <div class="cat-step cat-step-value"><div class="cat-step-head"><span class="cat-step-number">03</span><div><h3>Value</h3><p>Percent threshold used by the condition.</p></div></div>
          <div class="cat-threshold-row"><span class="cat-comparator">Equal or more than</span><label class="cat-percent-field"><input type="number" data-at-threshold min="1" max="100" step="1" value="80" aria-label="Threshold percent"><span>%</span></label></div>
          <p class="cat-help">A rule matches when any selected metric reaches or exceeds this percentage.</p>
        </div>
        <div class="cat-step cat-step-method"><div class="cat-step-head"><span class="cat-step-number">04</span><div><h3>Alert method</h3><p>Choose one or both notification methods.</p></div></div>
          <label class="cat-method-option"><input type="checkbox" data-at-notify-group><span class="cat-method-box"><strong>Report to user / group</strong><small>Route to an IT group or support level.</small></span></label>
          <label class="cat-field" data-at-group-wrap hidden><span>IT group / support level</span><select data-at-group><option value="">Choose an IT group…</option></select></label>
          <label class="cat-method-option"><input type="checkbox" data-at-email-enabled><span class="cat-method-box"><strong>Send e-mail</strong><small>Send the notification to an e-mail address.</small></span></label>
          <label class="cat-field" data-at-email-wrap hidden><span>E-mail address</span><input type="email" data-at-email placeholder="name@company.com" maxlength="254" autocomplete="email"></label>
        </div>
      </section>
      <section class="cat-preview"><div class="cat-preview-head"><div><span class="cat-preview-icon">⌘</span><div><h3>Action Result Preview</h3><p>Updates as you change the puzzle pieces.</p></div></div><span class="cat-preview-badge">LIVE PREVIEW</span></div><code data-at-preview>IF Computer {…} has {CPU} usage ≥ {80%}</code><p class="cat-preview-caveat">This saves the rule definition. Monitoring must evaluate the saved rule before notifications can fire automatically.</p></section>
      <div class="cat-builder-footer"><span class="cat-save-status" data-at-save-status>Unsaved rule</span><div class="cat-builder-actions"><button type="button" class="cam-btn" data-at-action="cancel">Cancel</button><button type="button" class="cam-btn cam-btn-primary cat-save-button" data-at-action="save">＋ Save automated trigger</button></div></div>
    </section>`;
  nav.insertAdjacentElement("afterend", panel);
  // List is the default view. The puzzle builder only opens after New Trigger.
  function renderView() {
    panel.querySelectorAll("[data-at-view]").forEach(view => { view.hidden = view.dataset.atView !== state.view; });
  }
  function openBuilder(rule=null) {
    state.editingId = rule ? String(rule.id) : null;
    state.targetType = rule?.target_type || "computer";
    state.metrics = rule?.metrics?.length ? [...rule.metrics] : ["CPU"];
    state.threshold = Number(rule?.threshold_percent || 80);
    state.notifyGroup = !!(rule?.notify_group_id);
    state.emailEnabled = !!rule?.send_email;
    $(`[data-at-name]`).value = rule?.name || "";
    $(`[data-at-threshold]`).value = String(state.threshold);
    $(`[data-at-computer]`).value = rule?.target_type === "computer" ? String(rule.target_id) : "";
    $(`[data-at-department]`).value = rule?.target_type === "department_computers" ? String(rule.target_id) : "";
    $(`[data-at-group]`).value = rule?.notify_group_id ? String(rule.notify_group_id) : "";
    $(`[data-at-email]`).value = rule?.email || "";
    $(`[data-at-notify-group]`).checked = state.notifyGroup;
    $(`[data-at-email-enabled]`).checked = state.emailEnabled;
    root.querySelectorAll("[data-at-metric]").forEach(el => { el.checked = state.metrics.includes(el.dataset.atMetric); });
    $(`[data-at-group-wrap]`).hidden = !state.notifyGroup;
    $(`[data-at-email-wrap]`).hidden = !state.emailEnabled;
    $(`[data-at-builder-title]`).textContent = rule ? `Edit ${rule.trigger_code || `ALT${rule.id}`}` : "Create automated trigger";
    $(`[data-at-builder-eyebrow]`).textContent = rule ? "EDIT RULE" : "NEW RULE";
    $(`[data-at-action="save"]`).textContent = rule ? "Save changes" : "＋ Save automated trigger";
    state.view="builder"; showNote(""); setTargetType(state.targetType); renderView(); updatePreview();
  }
  function openList() { state.editingId=null; state.view="list"; showNote(""); renderView(); renderRules(); }
  // Keep the Alerts page's own CSS variables and use them throughout this panel.
  function setMode(on) {
    root.classList.toggle("cat-automated-active", on);
    panel.hidden = !on;
    if (on) renderView();
    nav.querySelectorAll("[data-view]").forEach(btn => btn.classList.toggle("is-active", !on && btn.dataset.view === (root.querySelector('[data-view="completed"].is-active') ? "completed" : "live")));
    tab.classList.toggle("is-active", on);
  }
  function showNote(message, isError=false) {
    const note=$("[data-at-note]"), error=$("[data-at-error]");
    note.hidden=isError || !message; error.hidden=!isError || !message;
    if(isError) error.textContent=message; else note.textContent=message;
  }
  async function api(url, options={}) {
    const response=await fetch(url,{credentials:"same-origin",...options,headers:{"Accept":"application/json",...(options.body?{"Content-Type":"application/json"}:{}),...(options.headers||{})}});
    let data={}; try{data=await response.json();}catch(_){}
    if(!response.ok) throw new Error(data.detail||data.message||`API request failed (${response.status})`);
    return data;
  }
  function chosenTarget() {
    if(state.targetType==="computer") return state.meta.devices.find(d=>String(d.id)===$("[data-at-computer]").value)||null;
    return state.meta.departments.find(d=>String(d.id)===$("[data-at-department]").value)||null;
  }
  function chosenGroup() { return state.meta.groups.find(g=>String(g.id)===$("[data-at-group]").value)||null; }
  function notifyNames() {
    const out=[]; if(state.notifyGroup){const g=chosenGroup();out.push(`Report to group {${g?g.name:"SELECT IT GROUP"}}`);} if(state.emailEnabled){out.push(`Mail {${$("[data-at-email]").value.trim()||"ENTER EMAIL"}}`);} return out;
  }
  function updatePreview() {
    const target=chosenTarget();
    const selected=[...root.querySelectorAll("[data-at-metric]:checked")].map(el=>el.dataset.atMetric);
    state.metrics=selected;
    state.threshold=Math.max(1,Math.min(100,Number.parseInt($("[data-at-threshold]").value||"80",10)||80));
    const targetName=target?.name||"select a target";
    const targetPhrase=state.targetType==="computer"?`computer ${targetName}`:`computers in department ${targetName}`;
    const metricText=selected.length?selected.join(", "):"no metric selected";
    const notify=[]; const group=chosenGroup();
    if(state.notifyGroup)notify.push(group?`notify group ${group.name}`:"notify the selected IT group");
    if(state.emailEnabled)notify.push($("[data-at-email]").value.trim()?`send an email to ${$("[data-at-email]").value.trim()}`:"send an email to the specified address");
    const methodText=notify.length?notify.join(" and "):"no notification method selected";
    const metricsPhrase=selected.length===1?`reports ${metricText}`:`reports any of the selected metrics (${metricText})`;
    $("[data-at-preview]").textContent=`If ${targetPhrase} ${metricsPhrase} at or above ${state.threshold}% usage, ${methodText}.`;
    const saveStatus=$("[data-at-save-status]");
    const canSave=!!target&&selected.length>0&&state.threshold>=1&&state.threshold<=100&&((!state.notifyGroup||!!chosenGroup())&&(!state.emailEnabled||/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test($("[data-at-email]").value.trim())))&&(state.notifyGroup||state.emailEnabled);
    saveStatus.textContent=canSave?"Rule is ready to save":"Complete the required puzzle pieces";
    $("[data-at-action=save]").disabled=!canSave||state.saving;
  }
  function renderOptions() {
    const device=$("[data-at-computer]"), dept=$("[data-at-department]"), group=$("[data-at-group]");
    const keepD=device.value, keepP=dept.value, keepG=group.value;
    device.innerHTML='<option value="">Choose a computer…</option>'+state.meta.devices.map(d=>`<option value="${esc(d.id)}">${esc(d.name)}${d.status?` · ${esc(d.status)}`:""}</option>`).join("");
    dept.innerHTML='<option value="">Choose a department…</option>'+state.meta.departments.map(d=>`<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
    group.innerHTML='<option value="">Choose an IT group / support level…</option>'+state.meta.groups.map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("");
    if(state.meta.devices.some(d=>String(d.id)===keepD))device.value=keepD;
    if(state.meta.departments.some(d=>String(d.id)===keepP))dept.value=keepP;
    if(state.meta.groups.some(g=>String(g.id)===keepG))group.value=keepG;
    if(!state.meta.departments.length){dept.innerHTML='<option value="">No departments configured</option>';}
    if(!state.meta.devices.length){device.innerHTML='<option value="">No devices available</option>';}
    if(!state.meta.groups.length){group.innerHTML='<option value="">No IT/IAM groups available</option>';}
    updatePreview();
  }
  function setTargetType(type) {
    state.targetType=type;
    root.querySelectorAll("[data-at-target]").forEach(btn=>btn.classList.toggle("is-active",btn.dataset.atTarget===type));
    $("[data-at-department-wrap]").hidden=type!=="department_computers";
    $("[data-at-computer]").closest(".cat-field").hidden=type!=="computer";
    $("[data-at-target-label]").textContent=type==="computer"?"Computer":"Department computers";
    updatePreview();
  }
  function renderRules() {
    const list=$("[data-at-list]");
    const count=$("[data-at-count]");
    if(count)count.textContent=String(state.items.length);
    const q=($("[data-at-rule-search]")?.value||"").trim().toLowerCase();
    const status=$("[data-at-rule-filter]")?.value||"all";
    const sort=$("[data-at-rule-sort]")?.value||"newest";
    const timestamp=item=>Date.parse(item.created_at||item.createdAt||item.updated_at||"")||Number(item.id)||0;
    let items=state.items.filter(item=>{
      if(status==="enabled"&&!item.enabled)return false;
      if(status==="disabled"&&item.enabled)return false;
      const targetType=item.target_type==="computer"?"Computer":"Department Computers";
      const methods=[item.notify_group_label,item.email].filter(Boolean).join(" ");
      const searchable=[item.name,item.target_label,targetType,(item.metrics||[]).join(" "),methods,item.threshold_percent].join(" ").toLowerCase();
      return !q||searchable.includes(q);
    });
    items.sort((a,b)=>{
      if(sort==="name")return String(a.name||"").localeCompare(String(b.name||""));
      if(sort==="severity")return String(a.target_label||"").localeCompare(String(b.target_label||""))||String((a.metrics||[]).join(",")).localeCompare(String((b.metrics||[]).join(",")));
      return sort==="oldest"?timestamp(a)-timestamp(b):timestamp(b)-timestamp(a);
    });
    $("[data-at-total]").textContent=items.length===state.items.length?String(state.items.length):`${items.length} / ${state.items.length}`;
    if(!state.items.length){list.innerHTML='<div class="cat-empty"><strong>No automated triggers yet</strong><p>Create your first rule using the New Trigger button.</p>'+(state.meta.can_manage?'<button type="button" class="cam-btn cam-btn-primary" data-at-action="new">＋ Create first trigger</button>':'')+'</div>';return;}
    if(!items.length){list.innerHTML='<div class="cat-empty"><strong>No matching rules</strong><p>Try a different search or filter.</p></div>';return;}
    list.innerHTML=items.map(item=>{
      const targetType=item.target_type==="computer"?"Computer":"Department Computers";
      const metrics=(item.metrics||[]).join(", ");
      const methods=[];if(item.notify_group_label)methods.push(`Group: ${esc(item.notify_group_label)}`);if(item.send_email)methods.push(`E-mail: ${esc(item.email)}`);
      const createdAt=item.created_at?new Date(item.created_at).toLocaleString():"Creation time unavailable";
      const code=item.trigger_code||`ALT${item.id}`;
      const editButton=state.meta.can_manage?`<button type="button" class="cam-btn cat-edit" data-at-edit="${esc(item.id)}" aria-label="Edit ${esc(code)}">Edit</button>`:"";
      const manageControls=state.meta.can_manage?`<label class="cat-toggle"><input type="checkbox" data-at-toggle="${esc(item.id)}" ${item.enabled?"checked":""}><span>Enabled</span></label>${editButton}<button type="button" class="cam-btn cat-delete" data-at-delete="${esc(item.id)}" aria-label="Delete trigger">Delete</button>`:`<span class="cat-readonly">View only</span>`;
      return `<article class="cat-rule" data-rule-id="${esc(item.id)}"><div class="cat-rule-puzzle"><span class="cat-rule-symbol">${esc(code)}</span></div><div class="cat-rule-main"><div class="cat-rule-titleline"><strong>${esc(item.name)}</strong><span class="cat-rule-status ${item.enabled?"is-enabled":"is-disabled"}">${item.enabled?"Enabled":"Disabled"}</span></div><p>${targetType} <b>${esc(item.target_label)}</b> · ${esc(metrics)} ≥ <b>${esc(item.threshold_percent)}%</b></p><small>${methods.join(" · ")||"No notification method"}</small><small class="cat-rule-meta">Created by ${esc(item.created_by||"Unknown")} · ${esc(createdAt)}</small><small class="cat-rule-execution">Configured · Waiting for Monitoring evaluator</small></div>${manageControls}</article>`;
    }).join("");
  }
  async function loadMeta() { const data=await api("/api/automated-triggers/meta"); state.meta={devices:data.devices||[],departments:data.departments||[],groups:data.groups||[],can_manage:!!data.can_manage}; root.querySelectorAll('[data-at-action="new"]').forEach(btn=>btn.hidden=!state.meta.can_manage); renderOptions(); }
  async function loadRules() { const data=await api("/api/automated-triggers"); state.items=data.items||[]; renderRules(); }
  async function refresh() { showNote(""); try { await Promise.all([loadMeta(),loadRules()]); } catch(error) { showNote(error.message,true); $("[data-at-list]").innerHTML=`<div class="cat-error">Could not load trigger rules: ${esc(error.message)}</div>`; } }
  async function saveRule() {
    const target=chosenTarget(), metrics=[...root.querySelectorAll("[data-at-metric]:checked")].map(el=>el.dataset.atMetric), group=chosenGroup(), email=$(`[data-at-email]`).value.trim(), name=$(`[data-at-name]`).value.trim(), threshold=Number($(`[data-at-threshold]`).value);
    if(!state.meta.can_manage){showNote("Your IAM role does not allow editing automated triggers.",true);return;}
    if(!name){showNote("Enter a name for this automated trigger.",true);return;}
    if(!target||!metrics.length||threshold<1||threshold>100||(!state.notifyGroup&&!state.emailEnabled)||(state.notifyGroup&&!group)||(state.emailEnabled&&!email)){showNote("Complete Target, Metric, Value and at least one Alert method first.",true);return;}
    state.saving=true; updatePreview();
    const payload={name,target_type:state.targetType,target_id:target.id,metrics,threshold_percent:threshold,notify_group_id:state.notifyGroup?group.id:"",send_email:state.emailEnabled,email:state.emailEnabled?email:""};
    try {
      if(state.editingId){await api(`/api/automated-triggers/${encodeURIComponent(state.editingId)}`,{method:"PATCH",body:JSON.stringify(payload)});showNote("Automated trigger updated.");}
      else {await api("/api/automated-triggers",{method:"POST",body:JSON.stringify(payload)});showNote("Trigger definition saved. Automatic firing still requires the Monitoring evaluator.");}
      await loadRules(); openList();
    } catch(error){showNote(error.message,true);}
    finally{state.saving=false;updatePreview();}
  }
  nav.addEventListener("click",event=>{
    const triggerTab=event.target.closest("[data-at-tab]");
    if(triggerTab){event.preventDefault();event.stopPropagation();setMode(true);refresh();return;}
    const regularTab=event.target.closest("[data-view]");if(regularTab)setMode(false);
  });
  panel.addEventListener("click",async event=>{
    const targetBtn=event.target.closest("[data-at-target]"); if(targetBtn){setTargetType(targetBtn.dataset.atTarget);return;}
    const action=event.target.closest("[data-at-action]"); if(action?.dataset.atAction==="refresh"){refresh();return;} if(action?.dataset.atAction==="new"){if(state.meta.can_manage)openBuilder();else showNote("Your IAM role is view-only for automated triggers.",true);return;} if(action?.dataset.atAction==="cancel"){openList();return;} if(action?.dataset.atAction==="save"){await saveRule();return;}
    const edit=event.target.closest("[data-at-edit]"); if(edit){if(!state.meta.can_manage){showNote("Your IAM role does not allow editing automated triggers.",true);return;} const rule=state.items.find(item=>String(item.id)===String(edit.dataset.atEdit)); if(rule)openBuilder(rule);return;}
    const del=event.target.closest("[data-at-delete]"); if(del){if(!window.confirm("Delete this saved trigger rule?"))return;try{await api(`/api/automated-triggers/${encodeURIComponent(del.dataset.atDelete)}`,{method:"DELETE"});showNote("Trigger rule deleted.");await loadRules();}catch(err){showNote(err.message,true);}return;}
  });
  panel.addEventListener("change",async event=>{
    const el=event.target;
    if(el.matches("[data-at-notify-group]")){state.notifyGroup=el.checked;$("[data-at-group-wrap]").hidden=!el.checked;updatePreview();return;}
    if(el.matches("[data-at-email-enabled]")){state.emailEnabled=el.checked;$("[data-at-email-wrap]").hidden=!el.checked;updatePreview();return;}
    if(el.matches("[data-at-toggle]")){try{await api(`/api/automated-triggers/${encodeURIComponent(el.dataset.atToggle)}`,{method:"PATCH",body:JSON.stringify({enabled:el.checked})});showNote("Trigger status updated.");await loadRules();}catch(err){showNote(err.message,true);el.checked=!el.checked;}return;}
    if(el.matches("[data-at-computer],[data-at-department],[data-at-group],[data-at-metric],[data-at-threshold],[data-at-email],[data-at-name]"))updatePreview();
  });
  panel.addEventListener("input",event=>{
    if(event.target.matches("[data-at-rule-search]")){renderRules();return;}
    if(event.target.matches("[data-at-threshold],[data-at-email],[data-at-name]"))updatePreview();
  });
  panel.addEventListener("change",event=>{if(event.target.matches("[data-at-rule-filter],[data-at-rule-sort]"))renderRules();});
  // Keep tab active if the parent Alerts module refreshes its live/completed list in the background.
  const observer=new MutationObserver(()=>{if(root.classList.contains("cat-automated-active")&&!tab.classList.contains("is-active"))tab.classList.add("is-active");});
  observer.observe(nav,{subtree:true,attributes:true,attributeFilter:["class"]});
  renderView(); setTargetType("computer"); refresh();
})();
