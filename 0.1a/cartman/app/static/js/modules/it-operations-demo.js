
(() => {
"use strict";
const $ = (s, r=document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const path = location.pathname.toLowerCase();
const slug = ["ticketing","knowledge","tasks","workflows","notifications","reports"].find(x => path.includes("/pages/"+x+"/")) || "ticketing";
const root = $(".workspace-module");
if (!root) return;

const tickets = [
 {id:"INC-1048",title:"Production API latency spike",type:"Incident",priority:"Critical",status:"In progress",owner:"Alex Morgan",team:"Infrastructure",time:"4 min ago",desc:"API response times are above the agreed threshold. Review recent deployment and upstream dependencies.",sla:"12 min"},
 {id:"INC-1047",title:"File server disk usage at 92%",type:"Incident",priority:"High",status:"Open",owner:"Sam Rivera",team:"Systems",time:"18 min ago",desc:"Volume D: is nearing capacity. Identify large files and check retention policies.",sla:"38 min"},
 {id:"REQ-0832",title:"New starter workstation setup",type:"Request",priority:"Normal",status:"Pending",owner:"Jordan Lee",team:"Service Desk",time:"42 min ago",desc:"Prepare endpoint, install approved software and validate access.",sla:"6 hours"},
 {id:"INC-1046",title:"VPN authentication failures",type:"Incident",priority:"High",status:"In progress",owner:"Taylor Kim",team:"Network",time:"1 hour ago",desc:"Several users report intermittent VPN sign-in failures.",sla:"55 min"},
 {id:"REQ-0831",title:"Shared folder access request",type:"Request",priority:"Low",status:"Resolved",owner:"Sam Rivera",team:"Service Desk",time:"Yesterday",desc:"Access request completed and verified with requester.",sla:"Met"}
];
const articles = [
 {id:"KB-001",cat:"Networking",title:"Troubleshoot VPN authentication failures",desc:"A practical checklist for client, gateway, DNS and identity-provider issues.",time:"6 min read",tag:"VPN",steps:["Confirm the user account is active and not locked.","Check device time and certificate validity.","Resolve the VPN gateway hostname and verify connectivity.","Review authentication logs and MFA challenges.","Capture timestamps and escalate with relevant logs if unresolved."]},
 {id:"KB-002",cat:"Windows",title:"Investigate high disk usage on Windows servers",desc:"Find large directories, inspect event logs and reduce disk pressure safely.",time:"8 min read",tag:"Storage",steps:["Confirm the affected volume and current free space.","Use approved tools to identify large directories and files.","Check application logs, temporary files and retention settings.","Do not delete system or application data without owner approval.","Document the cleanup and monitor free space."]},
 {id:"KB-003",cat:"Networking",title:"DNS resolution troubleshooting",desc:"Check resolver configuration, records, cache and network reachability.",time:"5 min read",tag:"DNS",steps:["Verify the configured DNS servers.","Query the hostname against the configured resolver.","Compare with an authoritative or known-good resolver.","Check record TTL, suffix search list and client cache.","Record the failing hostname, resolver and timestamps."]},
 {id:"KB-004",cat:"Identity",title:"Account lockout investigation",desc:"Trace repeated lockouts across endpoints, services and saved credentials.",time:"7 min read",tag:"Identity",steps:["Confirm the account and lockout timestamp.","Review identity-provider or domain controller security logs.","Check scheduled tasks, services and stored credentials.","Validate the user's active sessions and enrolled devices.","Document the source before resetting credentials."]},
 {id:"KB-005",cat:"Linux",title:"Diagnose a Linux service that will not start",desc:"A systemd-focused checklist for failed units and dependency issues.",time:"6 min read",tag:"systemd",steps:["Inspect the unit state and recent journal entries.","Check configuration syntax and file permissions.","Verify required ports, paths and dependent services.","Apply the smallest safe correction and restart the unit.","Confirm service health and capture the root cause."]}
];
let tasks = [
 {id:"TSK-021",title:"Review server patch compliance",project:"Infrastructure",owner:"Alex Morgan",due:"Today",status:"In progress",priority:"High"},
 {id:"TSK-022",title:"Validate backup restore procedure",project:"Resilience",owner:"Sam Rivera",due:"Tomorrow",status:"To do",priority:"High"},
 {id:"TSK-023",title:"Update VPN troubleshooting runbook",project:"Knowledge",owner:"Jordan Lee",due:"Oct 26",status:"To do",priority:"Normal"},
 {id:"TSK-024",title:"Audit inactive endpoint agents",project:"Endpoints",owner:"Taylor Kim",due:"Oct 27",status:"Review",priority:"Normal"},
 {id:"TSK-025",title:"Document DNS change window",project:"Network",owner:"Alex Morgan",due:"Oct 24",status:"Done",priority:"Low"},
 {id:"TSK-026",title:"Check disk alerts on file servers",project:"Infrastructure",owner:"Sam Rivera",due:"Today",status:"In progress",priority:"High"}
];
let workflows = [
 {id:"WF-001",name:"Critical alert triage",trigger:"Critical monitoring alert",condition:"Severity = Critical",action:"Create incident + notify on-call",runs:128,success:98,enabled:true},
 {id:"WF-002",name:"New starter onboarding",trigger:"Approved access request",condition:"Request category = Onboarding",action:"Create setup tasks",runs:42,success:100,enabled:true},
 {id:"WF-003",name:"Disk capacity escalation",trigger:"Volume usage threshold",condition:"Usage > 90%",action:"Open ticket + notify Systems",runs:67,success:94,enabled:true},
 {id:"WF-004",name:"Weekly compliance summary",trigger:"Schedule · Monday 09:00",condition:"All managed endpoints",action:"Generate report",runs:18,success:100,enabled:false}
];
let notices = [
 {id:1,type:"Critical",title:"Critical alert: API latency",body:"Production API latency exceeded the configured threshold.",time:"2 min ago",read:false,source:"Monitoring"},
 {id:2,type:"Ticket",title:"Ticket INC-1048 assigned to you",body:"Production API latency spike · Infrastructure queue.",time:"8 min ago",read:false,source:"Ticketing"},
 {id:3,type:"Workflow",title:"Critical alert triage completed",body:"Workflow WF-001 completed successfully.",time:"24 min ago",read:false,source:"Automation"},
 {id:4,type:"Warning",title:"File server storage nearing limit",body:"Volume D: is reporting 92% utilization.",time:"41 min ago",read:true,source:"Monitoring"},
 {id:5,type:"System",title:"Nightly inventory sync completed",body:"Demo summary: 248 endpoints checked.",time:"Yesterday",read:true,source:"Inventory"}
];
let activeFilter = "All";
const badge = (text, cls="") => `<span class="io-badge ${cls}">${esc(text)}</span>`;
const btn = (text, action, extra="") => `<button type="button" class="io-btn ${extra}" data-action="${action}">${text}</button>`;
const stat = (label,value,note,cls="") => `<article class="io-stat"><span>${esc(label)}</span><strong class="${cls}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
const shell = (eyebrow,title,desc,actions="") => `<div class="io-head"><div><div class="io-eyebrow">${eyebrow}</div><h2>${title}</h2><p>${desc}</p></div><div class="io-head-actions">${actions}</div></div>`;
const search = (placeholder="Search...") => `<input class="io-search" type="search" placeholder="${esc(placeholder)}" aria-label="${esc(placeholder)}" data-search>`;
const tabs = (values, selected) => `<div class="io-tabs">${values.map(v=>`<button type="button" class="io-tab ${v===selected?"active":""}" data-filter="${esc(v)}">${esc(v)}</button>`).join("")}</div>`;
const panel = (title,sub,content,actions="") => `<section class="io-panel"><div class="io-panel-head"><div><h3>${title}</h3>${sub?`<p>${sub}</p>`:""}</div>${actions}</div>${content}</section>`;
const empty = `<div class="io-empty">No matching items. Try another search or filter.</div>`;
const priorityClass = p => p==="Critical"?"critical":p==="High"?"high":p==="Normal"?"normal":"low";
const statusClass = s => s==="Resolved"||s==="Done"||s==="Enabled"?"good":s==="In progress"||s==="Review"?"info":s==="Pending"?"warn":"";
const set = html => { root.classList.add("itops-redesigned"); root.innerHTML = html; };
function renderTicketing(){
 const filtered=tickets.filter(t=>(activeFilter==="All"||t.priority===activeFilter||t.status===activeFilter)&&(`${t.id} ${t.title} ${t.owner} ${t.team} ${t.type} ${t.status} ${t.priority}`).toLowerCase().includes(($("[data-search]")?.value||"").toLowerCase()));
 set(shell("SERVICE OPERATIONS / TICKETING","Ticket queue","Track incidents, service requests and SLA exposure.",btn("+ New ticket","new-ticket","primary"))+
 `<div class="io-stats">${stat("Open tickets",tickets.filter(t=>t.status!=="Resolved").length,"Across all queues")}${stat("Critical",tickets.filter(t=>t.priority==="Critical").length,"Needs immediate attention","io-red")}${stat("SLA at risk",2,"Demo estimate","io-amber")}${stat("Resolved today",14,"Illustrative activity","io-green")}</div>`+
 `<div class="io-toolbar">${search("Search ID, title, owner...")}${tabs(["All","Critical","High","Normal","Open","In progress","Resolved"],activeFilter)}</div>`+
 panel("Incident & request queue",`${filtered.length} tickets shown`,`<div class="io-table-wrap"><table class="io-table"><thead><tr><th>Ticket</th><th>Priority</th><th>Owner / team</th><th>Status</th><th>SLA remaining</th><th></th></tr></thead><tbody>${filtered.map(t=>`<tr><td><strong>${esc(t.id)}</strong><div class="io-main-cell">${esc(t.title)}</div><small>${esc(t.type)} · ${esc(t.time)}</small></td><td>${badge(t.priority,priorityClass(t.priority))}</td><td>${esc(t.owner)}<small>${esc(t.team)}</small></td><td>${badge(t.status,statusClass(t.status))}</td><td>${esc(t.sla)}</td><td><button class="io-link" data-action="ticket-detail" data-id="${t.id}">View details →</button></td></tr>`).join("")||`<tr><td colspan="6">${empty}</td></tr>`}</tbody></table></div>`) +
 `<div class="io-note">Demo workspace · Ticket changes remain in this page session and are not sent to a server.</div>`);
}
function renderKnowledge(){
 const cats=["All","Networking","Windows","Identity","Linux"];
 const q=($("[data-search]")?.value||"").toLowerCase();
 const filtered=articles.filter(a=>(activeFilter==="All"||a.cat===activeFilter)&&(`${a.title} ${a.desc} ${a.cat} ${a.tag}`).toLowerCase().includes(q));
 set(shell("DOCUMENTATION / KNOWLEDGE BASE","Knowledge base","Practical runbooks for common infrastructure incidents.",btn("+ Add article","new-article","primary"))+
 `<div class="io-stats">${stat("Published articles",articles.length,"Local demo library")}${stat("Categories",4,"Organized for discovery")}${stat("Most used","VPN","Illustrative topic")}${stat("Review due",2,"Demo editorial queue","io-amber")}</div>`+
 `<div class="io-toolbar">${search("Search runbooks, symptoms, categories...")}${tabs(cats,activeFilter)}</div>`+
 `<div class="io-article-grid">${filtered.map(a=>`<article class="io-article"><div class="io-article-top">${badge(a.cat,"info")}<span class="io-muted">${esc(a.time)}</span></div><h3>${esc(a.title)}</h3><p>${esc(a.desc)}</p><div class="io-article-foot"><span class="io-muted">${esc(a.id)} · ${esc(a.tag)}</span><button class="io-link" data-action="read-article" data-id="${a.id}">Read guide →</button></div></article>`).join("")||empty}</div>`+
 `<div class="io-note">Guides are illustrative demo content. Follow your organization's change and access policies when troubleshooting production systems.</div>`);
}
function renderTasks(){
 const q=($("[data-search]")?.value||"").toLowerCase();
 const statuses=["To do","In progress","Review","Done"];
 const filtered=tasks.filter(t=>`${t.id} ${t.title} ${t.owner} ${t.project} ${t.priority}`.toLowerCase().includes(q));
 set(shell("WORK MANAGEMENT / TASKS & AUTOMATION","Task board","Make operational work visible from backlog to completion.",btn("+ New task","new-task","primary"))+
 `<div class="io-stats">${stat("Total tasks",tasks.length,"Across all workstreams")}${stat("In progress",tasks.filter(t=>t.status==="In progress").length,"Currently being worked")}${stat("Awaiting review",tasks.filter(t=>t.status==="Review").length,"Needs validation","io-amber")}${stat("Completed",tasks.filter(t=>t.status==="Done").length,"Marked done","io-green")}</div>`+
 `<div class="io-toolbar">${search("Search tasks, owner, project...")}<span class="io-muted">Move tasks using the controls on each card</span></div>`+
 `<div class="io-kanban">${statuses.map(s=>{const rows=filtered.filter(t=>t.status===s);return `<section class="io-column"><div class="io-column-head"><h3>${s}</h3>${badge(rows.length,"info")}</div>${rows.map(t=>`<article class="io-task"><div class="io-task-meta"><span>${esc(t.id)}</span>${badge(t.priority,priorityClass(t.priority))}</div><h4>${esc(t.title)}</h4><p>${esc(t.project)}</p><div class="io-task-owner"><span class="io-avatar">${esc(t.owner.split(" ").map(x=>x[0]).join(""))}</span><span>${esc(t.owner)}</span><span class="io-muted">· ${esc(t.due)}</span></div><label class="io-small-label">Move to<select data-task-status="${t.id}">${statuses.map(x=>`<option ${x===t.status?"selected":""}>${x}</option>`).join("")}</select></label></article>`).join("")||`<div class="io-column-empty">No tasks here</div>`}</section>`}).join("")}</div>`+
 `<div class="io-note">Board actions update only the local demo state; no jobs or automation are executed.</div>`);
}
function renderWorkflows(){
 set(shell("AUTOMATION / WORKFLOWS","Workflow designer","Understand triggers, conditions and actions before automating operations.",btn("+ New workflow","new-workflow","primary"))+
 `<div class="io-stats">${stat("Workflows",workflows.length,"Defined in demo")}${stat("Enabled",workflows.filter(w=>w.enabled).length,"Ready in preview","io-green")}${stat("Runs this month",255,"Illustrative total")}${stat("Success rate","97.8%","Illustrative aggregate","io-green")}</div>`+
 panel("Automation library","Select a workflow to inspect its logic",`<div class="io-workflow-list">${workflows.map(w=>`<article class="io-workflow"><div class="io-workflow-title"><div><span class="io-workflow-id">${w.id}</span><h3>${esc(w.name)}</h3></div><label class="io-switch"><input type="checkbox" data-workflow-toggle="${w.id}" ${w.enabled?"checked":""}><span></span><em>${w.enabled?"Enabled":"Disabled"}</em></label></div><div class="io-flow"><div class="io-flow-step"><span>01 · TRIGGER</span><strong>${esc(w.trigger)}</strong></div><div class="io-flow-arrow">→</div><div class="io-flow-step"><span>02 · CONDITION</span><strong>${esc(w.condition)}</strong></div><div class="io-flow-arrow">→</div><div class="io-flow-step"><span>03 · ACTION</span><strong>${esc(w.action)}</strong></div></div><div class="io-workflow-foot"><span class="io-muted">${w.runs} demo runs · ${w.success}% success</span>${btn("Simulate run","simulate","")}<input type="hidden" data-workflow-id value="${w.id}"></div></article>`).join("")}</div>`)+
 `<div class="io-note">Simulate run displays a local confirmation only. It does not trigger real infrastructure changes, messages or jobs.</div>`);
}
function renderNotifications(){
 const q=($("[data-search]")?.value||"").toLowerCase();
 const filtered=notices.filter(n=>(activeFilter==="All"||n.type===activeFilter)&&(`${n.title} ${n.body} ${n.source} ${n.type}`).toLowerCase().includes(q));
 set(shell("ACTIVITY CENTER / NOTIFICATIONS","Notifications","A single feed for incidents, automation and platform events.",btn("Mark all read","read-all"))+
 `<div class="io-stats">${stat("Total notifications",notices.length,"In this demo feed")}${stat("Unread",notices.filter(n=>!n.read).length,"Awaiting attention",notices.some(n=>!n.read)?"io-amber":"")}${stat("Critical",notices.filter(n=>n.type==="Critical").length,"High-priority signals","io-red")}${stat("Sources",5,"Illustrative integrations")}</div>`+
 `<div class="io-toolbar">${search("Search notifications...")}${tabs(["All","Critical","Warning","Ticket","Workflow","System"],activeFilter)}</div>`+
 panel("Recent activity",`${filtered.length} notifications`,`${filtered.map(n=>`<article class="io-notice ${n.read?"is-read":"is-unread"}"><div class="io-notice-icon ${priorityClass(n.type)}">${n.type==="Critical"?"!":n.type==="Ticket"?"#":n.type==="Workflow"?"↻":n.type==="Warning"?"△":"•"}</div><div class="io-notice-content"><div class="io-notice-top">${badge(n.type,priorityClass(n.type))}<span class="io-muted">${esc(n.time)}</span>${n.read?"":badge("UNREAD","unread")}</div><h3>${esc(n.title)}</h3><p>${esc(n.body)}</p><small>${esc(n.source)}</small></div><div class="io-notice-actions">${btn(n.read?"Read":"Mark read","toggle-read")}<input type="hidden" data-notice-id value="${n.id}"></div></article>`).join("")||empty}`)+
 `<div class="io-note">Read/unread changes are stored in the current page session only.</div>`);
}
function renderReports(){
 const days=$("[data-period]")?.value||"7";
 const bars=days==="30"?[42,55,48,68,58,76,62,85,73,91,78,66]:days==="90"?[36,45,41,58,50,64,55,70,63,81,72,88]:[35,48,40,63,52,72,59];
 const labels=days==="30"?["W1","W2","W3","W4","W5","W6","W7","W8","W9","W10","W11","W12"]:days==="90"?["W1","W2","W3","W4","W5","W6","W7","W8","W9","W10","W11","W12"]:["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
 set(shell("ANALYTICS / REPORTS","Operations overview","Review illustrative service performance and export the displayed summary.",`<select class="io-select" data-period aria-label="Report period"><option value="7" ${days==="7"?"selected":""}>Last 7 days</option><option value="30" ${days==="30"?"selected":""}>Last 30 days</option><option value="90" ${days==="90"?"selected":""}>Last 90 days</option></select>${btn("Export CSV","export-csv","primary")}`)+
 `<div class="io-stats">${stat("Tickets resolved","184","Illustrative period total","io-green")}${stat("SLA attainment","96.4%","Illustrative performance","io-green")}${stat("Mean resolution","3h 42m","Illustrative average")}${stat("Backlog change","−12.8%","Versus previous period","io-green")}</div>`+
 `<div class="io-report-grid">${panel("Ticket volume",`Illustrative ticket activity · ${days} days`,`<div class="io-chart">${bars.map((v,i)=>`<div class="io-bar-group"><span>${v}</span><div class="io-bar" style="height:${v}%"></div><small>${labels[i]}</small></div>`).join("")}</div><div class="io-legend"><span><i></i> Tickets created (sample data)</span></div>`)}${panel("SLA performance","Illustrative service-level distribution",`<div class="io-sla-row"><div><span>Within SLA</span><strong>96.4%</strong></div><div class="io-progress"><i style="width:96.4%"></i></div></div><div class="io-sla-row"><div><span>At risk</span><strong>2.1%</strong></div><div class="io-progress warning"><i style="width:2.1%"></i></div></div><div class="io-sla-row"><div><span>Breached</span><strong>1.5%</strong></div><div class="io-progress danger"><i style="width:1.5%"></i></div></div><div class="io-report-foot"><span>Target</span><strong>≥ 95% within SLA</strong></div>`)}${panel("Team workload","Illustrative open-ticket distribution",`<div class="io-team-row"><span>Infrastructure</span><div class="io-progress"><i style="width:78%"></i></div><strong>24</strong></div><div class="io-team-row"><span>Service Desk</span><div class="io-progress"><i style="width:58%"></i></div><strong>18</strong></div><div class="io-team-row"><span>Network</span><div class="io-progress"><i style="width:42%"></i></div><strong>13</strong></div><div class="io-team-row"><span>Systems</span><div class="io-progress"><i style="width:31%"></i></div><strong>9</strong></div>`)}${panel("Report details","Exportable summary",`<div class="io-detail-list"><div><span>Report ID</span><strong>RPT-OPS-001</strong></div><div><span>Reporting window</span><strong>${days} days</strong></div><div><span>Data classification</span><strong>Sample / demo</strong></div><div><span>Generated</span><strong>On demand</strong></div></div>`)}</div>`+
 `<div class="io-note">All figures and charts on this page are illustrative, not measured from your environment. CSV export contains demo summary figures.</div>`);
}
function render(){ if(slug==="ticketing")renderTicketing();else if(slug==="knowledge")renderKnowledge();else if(slug==="tasks")renderTasks();else if(slug==="workflows")renderWorkflows();else if(slug==="notifications")renderNotifications();else renderReports(); }
function rerenderKeepSearch(){const q=$("[data-search]")?.value||"";render();const s=$("[data-search]");if(s){s.value=q;s.focus();s.setSelectionRange(q.length,q.length);}}
root.addEventListener("input",e=>{if(e.target.matches("[data-search]"))rerenderKeepSearch();});
root.addEventListener("change",e=>{
 const el=e.target;
 if(el.matches("[data-task-status]")){const t=tasks.find(x=>x.id===el.dataset.taskStatus);if(t)t.status=el.value;renderTasks();}
 if(el.matches("[data-workflow-toggle]")){const w=workflows.find(x=>x.id===el.dataset.workflowToggle);if(w)w.enabled=el.checked;renderWorkflows();}
 if(el.matches("[data-period]"))renderReports();
});
root.addEventListener("click",e=>{
 const f=e.target.closest("[data-filter]");
 if(f){activeFilter=f.dataset.filter;render();return;}
 const b=e.target.closest("[data-action]");if(!b)return;
 const action=b.dataset.action;
 if(action==="ticket-detail"){const t=tickets.find(x=>x.id===b.dataset.id);if(t)alert(`${t.id} — ${t.title}\n\n${t.desc}\n\nOwner: ${t.owner}\nStatus: ${t.status}\nSLA remaining: ${t.sla}`);}
 if(action==="new-ticket"){const title=prompt("Ticket title:");if(title&&title.trim()){tickets.unshift({id:"INC-"+(1049+tickets.length),title:title.trim(),type:"Incident",priority:"Normal",status:"Open",owner:"Unassigned",team:"Service Desk",time:"Just now",desc:"Created in local demo.",sla:"4 hours"});activeFilter="All";renderTicketing();}}
 if(action==="read-article"){const a=articles.find(x=>x.id===b.dataset.id);if(a)alert(`${a.title}\n\n${a.desc}\n\n${a.steps.map((x,i)=>`${i+1}. ${x}`).join("\n")}`);}
 if(action==="new-article"){const title=prompt("Article title:");if(title&&title.trim()){articles.unshift({id:"KB-"+String(articles.length+1).padStart(3,"0"),cat:"General",title:title.trim(),desc:"New local demo article. Edit this content in the demo workflow.",time:"2 min read",tag:"New",steps:["Define the symptom.","Collect relevant logs.","Validate the fix.","Document the result."]});activeFilter="All";renderKnowledge();}}
 if(action==="new-task"){const title=prompt("Task title:");if(title&&title.trim()){tasks.unshift({id:"TSK-"+String(27+tasks.length-6).padStart(3,"0"),title:title.trim(),project:"Operations",owner:"Unassigned",due:"Unscheduled",status:"To do",priority:"Normal"});renderTasks();}}
 if(action==="new-workflow"){const name=prompt("Workflow name:");if(name&&name.trim()){workflows.push({id:"WF-"+String(workflows.length+1).padStart(3,"0"),name:name.trim(),trigger:"Manual trigger",condition:"No conditions configured",action:"Review required",runs:0,success:100,enabled:false});renderWorkflows();}}
 if(action==="simulate"){const card=b.closest(".io-workflow");const id=card?.querySelector("[data-workflow-id]")?.value;const w=workflows.find(x=>x.id===id);if(w)alert(w.enabled?`Demo simulation complete: ${w.name}\n\nNo external actions were executed.`:`${w.name} is disabled. Enable it before simulating a run.`);}
 if(action==="read-all"){notices.forEach(n=>n.read=true);renderNotifications();}
 if(action==="toggle-read"){const id=Number(b.parentElement.querySelector("[data-notice-id]")?.value);const n=notices.find(x=>x.id===id);if(n)n.read=!n.read;renderNotifications();}
 if(action==="export-csv"){const csv=[["Metric","Value","Note"],["Tickets resolved","184","Illustrative demo value"],["SLA attainment","96.4%","Illustrative demo value"],["Mean resolution","3h 42m","Illustrative demo value"],["Backlog change","-12.8%","Illustrative demo value"],["Reporting window",($("[data-period]")?.value||"7")+" days","Selected period"]].map(r=>r.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(",")).join("\r\n");const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8;"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="cartman-operations-demo-report.csv";a.click();URL.revokeObjectURL(url);}
});
render();
})();
