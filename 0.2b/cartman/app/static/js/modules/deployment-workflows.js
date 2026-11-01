
"use strict";
(() => {
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => [...r.querySelectorAll(s)];
  const store = window.CartmanDeploymentDemo;
  if (!store) return;
  const page = document.body.dataset.deploymentPage;
  const state = {query:"",status:"all",sort:"time",dir:"desc",selected:null,step:1};
  const esc = v => String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const slug = v => String(v||"").toLowerCase().replace(/\s+/g,"-");
  const icon = type => ({Software:"▤",Patch:"↻",Package:"◇","OS Image":"▣"}[type]||"▤");
  function toast(message) {
    const n=$("#dw-toast"); if(!n)return;
    n.textContent=message;n.hidden=false;
    clearTimeout(toast.timer);toast.timer=setTimeout(()=>n.hidden=true,2600);
  }
  function records() {
    let all=store.list();
    if(page==="history") all=all.filter(r=>["Completed","Failed","Running","Queued"].includes(r.status));
    return all;
  }
  function filtered() {
    return records().filter(r=>{
      const q=state.query;
      return [r.id,r.name,r.type,r.version,r.target,r.owner,r.status].join(" ").toLocaleLowerCase().includes(q)
        && (state.status==="all"||r.status===state.status);
    }).sort((a,b)=>{
      let x=a[state.sort],y=b[state.sort];
      if(state.sort==="time"){x=a.time||0;y=b.time||0;}
      const c=typeof x==="number"&&typeof y==="number"?x-y:String(x??"").localeCompare(String(y??""));
      return c*(state.dir==="asc"?1:-1);
    });
  }
  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit"
    });
  }
  function requestedAt(r) {
    return r.requestedAt || r.time || null;
  }
  function updateStats() {
    const all=records();
    const set=(id,value)=>{const n=$("#"+id);if(n)n.textContent=value;};
    set("dw-total",all.length);
    set("dw-running",all.filter(r=>r.status==="Running").length);
    set("dw-queued",all.filter(r=>r.status==="Queued").length);
    set("dw-failed",all.filter(r=>r.status==="Failed").length);
    set("dw-completed",all.filter(r=>r.status==="Completed").length);
    set("dw-drafts",all.filter(r=>r.status==="Draft").length);
  }
  function renderRows() {
    const body=$("#dw-rows"); if(!body)return;
    const list=filtered();
    body.innerHTML=list.map(r=>`
      <tr>
        <td><div class="dw-name"><span class="dw-type-icon">${icon(r.type)}</span><span><strong>${esc(r.name)}</strong><small>${esc(r.id)} · ${esc(r.type)}</small></span></div></td>
        <td>${esc(r.target)}</td>
        <td>${esc(r.version||"—")}</td>
        <td><div class="dw-progress"><span class="dw-progress-track"><span style="width:${Math.max(0,Math.min(100,Number(r.progress)||0))}%"></span></span><span>${Math.max(0,Math.min(100,Number(r.progress)||0))}%</span></div></td>
        <td><span class="dw-status" data-status="${esc(r.status)}">${esc(r.status)}</span></td>
        <td><div class="dw-row-actions"><button class="dw-icon-btn" data-detail="${esc(r.id)}" title="View details" aria-label="View details">↗</button>${page==="jobs"?`<button class="dw-icon-btn" data-job-action="complete" data-id="${esc(r.id)}" title="Simulate completion" aria-label="Simulate completion">✓</button>`:""}</div></td>
      </tr>`).join("");
    $("#dw-count").textContent=`Showing ${list.length} of ${records().length} records`;
    $("#dw-table-wrap").hidden=!list.length;
    $("#dw-empty").hidden=!!list.length;
    updateStats();
  }
  function render(){renderRows();}
  function openDetails(id) {
    const r=store.list().find(x=>x.id===id);if(!r)return;
    state.selected=id;
    $("#dw-detail-title").textContent=r.name;
    $("#dw-detail-body").innerHTML=`<div class="dw-review">
      ${[["Deployment ID",r.id],["Status",r.status],["Type",r.type],["Version",r.version],["Target group",r.target],["Devices",r.devices],["Progress",r.progress+"%"],["Owner",r.owner],["İstek Tarihi",formatDate(requestedAt(r))],["Başlama Tarihi",formatDate(r.startedAt)],["Bitiş Tarihi",formatDate(r.finishedAt)],["Updated",r.updated],["Description",r.description||"Demo record"]]
      .map(([k,v])=>`<div class="dw-review-item"><small>${esc(k)}</small><strong>${esc(v)}</strong></div>`).join("")}
      </div><p style="font-size:11px;color:var(--muted,#8b95a7);margin-top:16px">Session-only demonstration record. No real endpoint actions were performed.</p>`;
    $("#dw-detail-modal").hidden=false;
  }
  const search=$("#dw-search"), status=$("#dw-status");
  if(search)search.addEventListener("input",()=>{state.query=search.value.trim().toLocaleLowerCase();renderRows();});
  if(status)status.addEventListener("change",()=>{state.status=status.value;renderRows();});
  $$("[data-dw-sort]").forEach(b=>b.addEventListener("click",()=>{
    if(state.sort===b.dataset.dwSort)state.dir=state.dir==="asc"?"desc":"asc";
    else{state.sort=b.dataset.dwSort;state.dir="asc";}
    renderRows();
  }));
  $("#dw-reset")?.addEventListener("click",()=>{
    state.query="";state.status="all";
    if(search)search.value="";
    if(status)status.value="all";
    renderRows();
  });
  $("#dw-rows")?.addEventListener("click",e=>{
    const detail=e.target.closest("[data-detail]");
    if(detail){openDetails(detail.dataset.detail);return;}
    const action=e.target.closest("[data-job-action]");
    if(action){
      const r=store.list().find(x=>x.id===action.dataset.id);if(!r)return;
      const finishedAt=Date.now();
      store.upsert({...r,status:"Completed",progress:100,updated:"Just now",finishedAt,startedAt:r.startedAt||r.requestedAt||r.time,time:finishedAt});
      toast("Demo job marked completed. No device was contacted.");
      renderRows();
    }
  });
  $$("[data-dw-close]").forEach(b=>b.addEventListener("click",()=>$("#"+b.dataset.dwClose).hidden=true));
  $("#dw-detail-modal")?.addEventListener("click",e=>{if(e.target.id==="dw-detail-modal")e.currentTarget.hidden=true;});
  document.addEventListener("keydown",e=>{if(e.key==="Escape")$$(".dw-modal-backdrop").forEach(n=>n.hidden=true);});

  // New Deployment: configure -> review -> create a session-only job.
  const form=$("#dw-deploy-form");
  if(form) {
    const steps=$$(".dw-wizard-step",form);
    const indicators=$$(".dw-step");
    function showStep(n) {
      state.step=n;
      steps.forEach((s,i)=>s.hidden=i!==n-1);
      indicators.forEach((s,i)=>s.classList.toggle("active",i===n-1));
      $("#dw-back").hidden=n===1;
      $("#dw-next").hidden=n===2;
      $("#dw-create").hidden=n!==2;
    }
    $("#dw-new")?.addEventListener("click",()=>{$("#dw-deploy-modal").hidden=false;showStep(1);});
    $("#dw-next")?.addEventListener("click",()=>{
      if(!form.reportValidity())return;
      const d=new FormData(form);
      const vals={
        name:String(d.get("name")||"").trim(),
        type:String(d.get("type")||"Software"),
        version:String(d.get("version")||"").trim()||"Latest",
        target:String(d.get("target")||"").trim(),
        devices:Math.max(1,Number(d.get("devices"))||1),
        schedule:String(d.get("schedule")||"Now"),
        policy:String(d.get("policy")||"Standard")
      };
      $("#dw-review").innerHTML=Object.entries({
        "Deployment name":vals.name,"Package type":vals.type,"Version":vals.version,
        "Target group":vals.target,"Target devices":vals.devices,
        "Schedule":vals.schedule,"Rollout policy":vals.policy
      }).map(([k,v])=>`<div class="dw-review-item"><small>${esc(k)}</small><strong>${esc(v)}</strong></div>`).join("");
      showStep(2);
    });
    $("#dw-back")?.addEventListener("click",()=>showStep(1));
    $("#dw-create")?.addEventListener("click",()=>{
      if(!form.reportValidity())return;
      const d=new FormData(form), now=Date.now();
      const record={
        id:"DPL-DEMO-"+String(now).slice(-7),
        name:String(d.get("name")||"").trim(),
        type:String(d.get("type")||"Software"),
        version:String(d.get("version")||"").trim()||"Latest",
        target:String(d.get("target")||"").trim(),
        devices:Math.max(1,Number(d.get("devices"))||1),
        updated:"Just now",time:now,requestedAt:now,startedAt:null,finishedAt:null,status:"Queued",owner:"Current session",
        progress:0,description:"Created through the local demo deployment wizard. Schedule: "+String(d.get("schedule")||"Now")+". Policy: "+String(d.get("policy")||"Standard")+"."
      };
      store.upsert(record);
      $("#dw-deploy-modal").hidden=true;form.reset();showStep(1);
      toast("Demo deployment created. Open Deployment Jobs to review it.");
      renderRows();
    });
    $("#dw-cancel")?.addEventListener("click",()=>$("#dw-deploy-modal").hidden=true);
  }
  $("#dw-export")?.addEventListener("click",()=>{
    const rows=filtered(), cols=["id","name","type","version","target","devices","status","progress","owner","updated"];
    const csv=[cols,...rows.map(r=>cols.map(k=>r[k]??""))].map(row=>row.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(",")).join("\r\n");
    const url=URL.createObjectURL(new Blob(["\uFEFF",csv],{type:"text/csv;charset=utf-8"}));
    const a=document.createElement("a");a.href=url;a.download=`cartman-${page}-demo.csv`;a.click();URL.revokeObjectURL(url);
    toast("Filtered demo records exported as CSV.");
  });
  window.addEventListener("cartman:deployment-change",render);
  render();
})();
