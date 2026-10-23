(() => {
  "use strict";
  if (window.__cartmanMonitoringDemoV2) return;
  window.__cartmanMonitoringDemoV2 = true;

  const $ = (s, r = document) => r.querySelector(s);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  })[c]);

  const devices = [
    {name:"CORE-DC01", os:"Windows Server 2022", ip:"10.10.0.10", status:"Healthy", cpu:24, ram:58, disk:42, group:"Core Infrastructure"},
    {name:"CORE-DC02", os:"Windows Server 2022", ip:"10.10.0.11", status:"Healthy", cpu:19, ram:51, disk:39, group:"Core Infrastructure"},
    {name:"APP-SRV01", os:"Windows Server 2022", ip:"10.10.1.21", status:"Warning", cpu:86, ram:82, disk:74, group:"Application Servers"},
    {name:"APP-SRV02", os:"Ubuntu 24.04", ip:"10.10.1.22", status:"Healthy", cpu:37, ram:64, disk:48, group:"Application Servers"},
    {name:"DB-PROD01", os:"Ubuntu 22.04", ip:"10.10.2.30", status:"Critical", cpu:93, ram:91, disk:88, group:"Database"},
    {name:"FILE-SRV01", os:"Windows Server 2019", ip:"10.10.3.15", status:"Healthy", cpu:21, ram:47, disk:67, group:"File Services"},
    {name:"EDGE-GW01", os:"Linux", ip:"10.10.0.1", status:"Healthy", cpu:14, ram:32, disk:26, group:"Network"},
    {name:"BACKUP01", os:"Windows Server 2022", ip:"10.10.4.12", status:"Warning", cpu:62, ram:70, disk:84, group:"Backup"},
  ];

  const alerts = [
    {id:"ALT-2048", severity:"Critical", status:"Open", title:"Database CPU above threshold", device:"DB-PROD01", time:"2 min ago", detail:"CPU sustained above 90% for 12 minutes.", owner:"Unassigned"},
    {id:"ALT-2047", severity:"Warning", status:"Open", title:"Application memory pressure", device:"APP-SRV01", time:"8 min ago", detail:"Memory utilization reached 82%.", owner:"Infrastructure"},
    {id:"ALT-2046", severity:"Warning", status:"Acknowledged", title:"Backup volume nearing capacity", device:"BACKUP01", time:"24 min ago", detail:"Disk utilization reached 84%.", owner:"IT Operations"},
    {id:"ALT-2045", severity:"Info", status:"Resolved", title:"Scheduled maintenance completed", device:"CORE-DC02", time:"1 hr ago", detail:"Maintenance window completed successfully.", owner:"IT Operations"},
    {id:"ALT-2044", severity:"Critical", status:"Acknowledged", title:"Database memory utilization high", device:"DB-PROD01", time:"1 hr ago", detail:"Memory utilization reached 91%.", owner:"Database Team"},
  ];

  const services = [
    {name:"Active Directory", host:"CORE-DC01", group:"Identity", status:"Operational", latency:18, uptime:"99.98%", port:389, detail:"Directory authentication and LDAP"},
    {name:"DNS Resolver", host:"CORE-DC02", group:"Identity", status:"Operational", latency:12, uptime:"99.99%", port:53, detail:"Internal name resolution"},
    {name:"Customer Portal", host:"APP-SRV01", group:"Applications", status:"Degraded", latency:842, uptime:"99.72%", port:443, detail:"External-facing web application"},
    {name:"API Gateway", host:"APP-SRV02", group:"Applications", status:"Operational", latency:64, uptime:"99.95%", port:8443, detail:"Internal API routing"},
    {name:"Production Database", host:"DB-PROD01", group:"Database", status:"Degraded", latency:426, uptime:"99.61%", port:5432, detail:"Primary production database"},
    {name:"File Shares", host:"FILE-SRV01", group:"Storage", status:"Operational", latency:31, uptime:"99.97%", port:445, detail:"Departmental file storage"},
    {name:"Backup Scheduler", host:"BACKUP01", group:"Backup", status:"Warning", latency:174, uptime:"99.83%", port:0, detail:"Scheduled backup jobs"},
  ];

  const events = [
    ["14:42:08","Critical","DB-PROD01","CPU threshold exceeded"],
    ["14:37:51","Warning","APP-SRV01","Memory pressure detected"],
    ["14:24:03","Info","CORE-DC02","Maintenance completed"],
    ["14:18:29","Warning","BACKUP01","Storage capacity above 80%"],
    ["14:05:12","Info","APP-SRV02","Configuration audit completed"],
  ];

  const metrics = {
    CPU:  [28,31,26,34,39,32,41,38,45,52,48,61,58,72,68,64,79,73,86,81,76,69,74,63],
    Memory:[54,55,55,56,57,58,57,59,61,60,62,63,64,65,64,67,68,69,71,70,72,73,72,74],
    Disk: [39,39,40,40,41,41,42,42,43,43,44,44,45,45,46,46,47,47,48,48,49,49,50,51],
    Network:[22,28,25,34,41,36,29,44,51,38,57,62,49,42,67,73,55,48,81,64,58,74,69,61],
  };

  const state = {range:"24h", metric:"CPU", alertSeverity:"All", alertStatus:"All", selectedService:"Customer Portal"};
  const configs = {
    monitoring:["Monitoring Control Center","Infrastructure health at a glance","monitoring"],
    "monitoring-overview":["Infrastructure Overview","Estate composition, distribution and device posture","overview"],
    "metrics-performance":["Metrics & Performance","Performance trends and resource saturation","metrics"],
    alerts:["Alert Management","Triage incidents, assign ownership and track resolution","alerts"],
    availability:["Availability & SLA","Uptime posture, service objectives and incident history","availability"],
    "service-monitoring":["Service Monitoring","Application and infrastructure service health","services"]
  };

  const badge = status => {
    const s = String(status).toLowerCase();
    const cls = /critical|down|failed/.test(s) ? "critical" :
      /warning|degraded|open/.test(s) ? "warning" :
      /resolved|healthy|operational|acknowledged/.test(s) ? "healthy" : "neutral";
    return `<span class="mon-badge ${cls}"><i></i>${esc(status)}</span>`;
  };

  const kpi = (label, value, note, kind="") =>
    `<article class="mon-kpi ${kind}"><div class="mon-kpi-top"><span>${esc(label)}</span><span class="mon-kpi-mark"></span></div><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`;

  const panel = (title, subtitle, body, extra="") =>
    `<section class="mon-panel ${extra}"><header class="mon-panel-head"><div><h3>${title}</h3><p>${subtitle}</p></div></header>${body}</section>`;

  function chart(values, color="blue", unit="") {
    const w=640,h=190,p=14;
    const max=Math.max(...values)*1.12, min=Math.min(0,...values);
    const pts=values.map((v,i)=>`${p+i*(w-2*p)/(values.length-1)},${h-p-(v-min)/(max-min||1)*(h-2*p)}`);
    const path="M"+pts.join(" L");
    const area=path+` L${w-p},${h-p} L${p},${h-p} Z`;
    return `<div class="mon-chart-wrap">
      <div class="mon-chart-y"><span>${Math.round(max)}${unit}</span><span>${Math.round(max*.66)}${unit}</span><span>${Math.round(max*.33)}${unit}</span><span>0${unit}</span></div>
      <svg class="mon-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Demo trend chart">
        <defs><linearGradient id="mon-fill-${color}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--mon-${color})" stop-opacity=".27"/><stop offset="100%" stop-color="var(--mon-${color})" stop-opacity="0"/></linearGradient></defs>
        ${[.25,.5,.75,1].map(t=>`<line x1="${p}" y1="${p+(h-2*p)*t}" x2="${w-p}" y2="${p+(h-2*p)*t}" class="mon-gridline"/>`).join("")}
        <path d="${area}" fill="url(#mon-fill-${color})"/><path d="${path}" fill="none" stroke="var(--mon-${color})" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="${pts[pts.length-1].split(",")[0]}" cy="${pts[pts.length-1].split(",")[1]}" r="4" fill="var(--mon-${color})" stroke="var(--mon-panel)" stroke-width="2"/>
      </svg></div><div class="mon-chart-x"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>Now</span></div>`;
  }

  function bars(items) {
    return `<div class="mon-bars">${items.map(([name,value,color="blue"])=>`<div class="mon-bar-row"><div><span>${esc(name)}</span><strong>${value}%</strong></div><div class="mon-bar-track"><i class="${color}" style="width:${value}%"></i></div></div>`).join("")}</div>`;
  }

  function table(headers, rows, empty="No demo records.") {
    return `<div class="mon-table-wrap"><table class="mon-table"><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="mon-empty">${empty}</td></tr>`}</tbody></table></div>`;
  }

  function deviceRows(list) {
    return list.map(d=>`<tr data-searchable="${esc((d.name+" "+d.os+" "+d.ip+" "+d.group).toLowerCase())}">
      <td><div class="mon-device"><span class="mon-device-icon">▣</span><span><strong>${esc(d.name)}</strong><small>${esc(d.group)}</small></span></div></td>
      <td>${esc(d.os)}</td><td class="mon-mono">${esc(d.ip)}</td><td>${badge(d.status)}</td>
      <td><div class="mon-mini-meter"><i style="width:${d.cpu}%"></i></div><small>${d.cpu}%</small></td>
      <td>${d.ram}%</td><td>${d.disk}%</td>
    </tr>`).join("");
  }

  function shell(title, sub, content) {
    return `<div class="mon-app">
      <div class="mon-page-heading"><div><div class="mon-overline">CARTMAN / OPERATIONS</div><h2>${title}</h2><p>${sub}</p></div>
        <div class="mon-page-actions"><span class="mon-demo-label"><i></i> DEMO ENVIRONMENT</span><button class="mon-button" data-action="export">Export CSV ↗</button></div>
      </div>${content}
      <footer class="mon-footer"><span>Cartman Operations Console</span><span>Illustrative sample data · Not live telemetry</span></footer>
    </div>`;
  }

  function toolbar() {
    return `<div class="mon-toolbar"><label class="mon-select-label">Scope <select data-filter="scope"><option value="all">All systems</option><option>Core Infrastructure</option><option>Application Servers</option><option>Database</option><option>Network</option></select></label>
      <div class="mon-range" role="group" aria-label="Time range">${["1h","6h","24h","7d"].map(r=>`<button data-range="${r}" class="${state.range===r?"active":""}">${r}</button>`).join("")}</div>
      <button class="mon-button subtle" data-action="reset">↻ Reset view</button></div>`;
  }

  function monitoringPage() {
    const critical=devices.filter(d=>d.status==="Critical").length;
    const warnings=devices.filter(d=>d.status==="Warning").length;
    const healthy=devices.filter(d=>d.status==="Healthy").length;
    return shell("Monitoring Control Center","A consolidated view of infrastructure health and operational signals.",`
      ${toolbar()}
      <div class="mon-kpis">${kpi("Monitored assets",devices.length,"Across 5 infrastructure groups")}${kpi("Healthy systems",healthy,"Operating normally","positive")}${kpi("Needs attention",warnings+critical,`${critical} critical · ${warnings} warning`,"negative")}${kpi("Service availability","99.94%","Illustrative 30-day average","positive")}</div>
      <div class="mon-grid two">
        ${panel("Resource utilization","Illustrative system load · last 24 hours",`<div class="mon-chart-legend"><span><i class="blue"></i>CPU utilization</span><span><i class="purple"></i>Memory utilization</span><b>Peak CPU 93%</b></div>${chart(metrics.CPU,"blue","%")}`)}
        ${panel("Infrastructure posture","Current sample distribution",`${bars([["Healthy",healthy*100/devices.length,"green"],["Warning",warnings*100/devices.length,"amber"],["Critical",critical*100/devices.length,"red"]])}<div class="mon-insight"><span>!</span><div><strong>Attention required</strong><p>DB-PROD01 and APP-SRV01 are the highest-priority sample systems.</p></div></div>`)}
      </div>
      <div class="mon-grid two">
        ${panel("Systems requiring attention","Prioritized sample inventory",table(["System","Group","CPU","Memory","Status"],devices.filter(d=>d.status!=="Healthy").map(d=>`<tr><td><strong>${d.name}</strong></td><td>${d.group}</td><td>${d.cpu}%</td><td>${d.ram}%</td><td>${badge(d.status)}</td></tr>`).join("")))}
        ${panel("Recent operational activity","Illustrative event timeline",`<div class="mon-timeline">${events.slice(0,4).map(e=>`<div><i class="${e[1].toLowerCase()}"></i><span><strong>${esc(e[3])}</strong><small>${esc(e[2])} · ${esc(e[0])}</small></span>${badge(e[1])}</div>`).join("")}</div>`)}
      </div>
      ${panel("Infrastructure inventory","Search and review the sample estate",`<div class="mon-inline-filter"><input data-local-search placeholder="Search hostname, IP, OS…" aria-label="Search devices"><span>${devices.length} systems</span></div>${table(["System","Operating system","IP address","Status","CPU","RAM","Disk"],deviceRows(devices))}`)}
    `);
  }

  function overviewPage() {
    const osCounts = {};
    devices.forEach(d=>{const key=d.os.startsWith("Windows")?"Windows Server":d.os.startsWith("Ubuntu")?"Ubuntu Linux":"Linux";osCounts[key]=(osCounts[key]||0)+1;});
    return shell("Infrastructure Overview","Understand the shape of the estate, operating systems and system health.",`
      ${toolbar()}
      <div class="mon-kpis">${kpi("Total assets",devices.length,"Sample managed inventory")}${kpi("Infrastructure groups",5,"Core, app, DB, network, backup")}${kpi("Windows systems",4,"Server operating systems")}${kpi("Linux systems",4,"Ubuntu and Linux hosts")}</div>
      <div class="mon-grid two">
        ${panel("Operating system distribution","Asset count by platform",`<div class="mon-os-list">${Object.entries(osCounts).map(([name,count])=>`<div class="mon-os-item"><span class="mon-os-icon">${name.includes("Windows")?"⊞":"⌘"}</span><div><strong>${name}</strong><small>${count} assets · ${Math.round(count/devices.length*100)}% of estate</small><div class="mon-bar-track"><i style="width:${count/devices.length*100}%"></i></div></div><b>${count}</b></div>`).join("")}</div>`)}
        ${panel("Health by infrastructure group","Quickly identify where risk is concentrated",`<div class="mon-group-list">${["Core Infrastructure","Application Servers","Database","File Services","Network","Backup"].map(g=>{const ds=devices.filter(d=>d.group===g);const bad=ds.filter(d=>d.status!=="Healthy").length;return `<div><span><strong>${g}</strong><small>${ds.length} assets</small></span>${badge(bad?`${bad} need attention`:"Healthy")}<b>${ds.length?Math.round((ds.length-bad)/ds.length*100):0}%</b></div>`}).join("")}</div>`)}
      </div>
      ${panel("All managed assets","Inventory posture with resource context",table(["System","Operating system","IP address","Status","CPU","RAM","Disk"],deviceRows(devices)))}
      <div class="mon-note"><strong>Demo note</strong><span>Distribution and health figures are derived from the sample dataset bundled with this UI.</span></div>
    `);
  }

  function metricsPage() {
    const values=metrics[state.metric];
    const avg=Math.round(values.reduce((a,b)=>a+b,0)/values.length);
    const peak=Math.max(...values);
    const color=state.metric==="Memory"?"purple":state.metric==="Disk"?"amber":state.metric==="Network"?"green":"blue";
    return shell("Metrics & Performance","Inspect utilization patterns, compare resource pressure and spot potential bottlenecks.",`
      ${toolbar()}
      <div class="mon-kpis">${kpi(`${state.metric} average`,`${avg}%`,"Illustrative sample period")}${kpi("Peak utilization",`${peak}%`,"Highest sample reading",peak>80?"negative":"")}${kpi("Systems above 80%",devices.filter(d=>d[state.metric.toLowerCase()]>80).length,"Current sample snapshot")}${kpi("Sample interval","1 hour","Illustrative aggregation")}</div>
      ${panel("Performance trend","Select a metric to update the trend chart",`<div class="mon-metric-switch">${["CPU","Memory","Disk","Network"].map(m=>`<button data-metric="${m}" class="${state.metric===m?"active":""}">${m}</button>`).join("")}</div><div class="mon-chart-legend"><span><i class="${color}"></i>${state.metric} utilization</span><b>Latest sample ${values[values.length-1]}%</b></div>${chart(values,color,"%")}<div class="mon-chart-x"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>Now</span></div>`)}
      ${panel("Resource pressure by system","Highest CPU utilization in the sample inventory",table(["System","Group","CPU","Memory","Disk","Assessment"],[...devices].sort((a,b)=>b.cpu-a.cpu).map(d=>`<tr><td><strong>${d.name}</strong><small>${d.ip}</small></td><td>${d.group}</td><td><div class="mon-mini-meter"><i class="${d.cpu>80?"red":d.cpu>60?"amber":""}" style="width:${d.cpu}%"></i></div>${d.cpu}%</td><td>${d.ram}%</td><td>${d.disk}%</td><td>${badge(d.cpu>80?"High pressure":d.cpu>60?"Elevated":"Normal")}</td></tr>`).join("")))}
      <div class="mon-note"><strong>Interpretation</strong><span>All values are illustrative demo metrics; no host telemetry is being collected.</span></div>
    `);
  }

  function alertsPage() {
    const list=alerts.filter(a=>(state.alertSeverity==="All"||a.severity===state.alertSeverity)&&(state.alertStatus==="All"||a.status===state.alertStatus));
    return shell("Alert Management","Triage sample incidents, review impact and track response status.",`
      <div class="mon-kpis">${kpi("Open alerts",alerts.filter(a=>a.status==="Open").length,"Require triage","negative")}${kpi("Critical",alerts.filter(a=>a.severity==="Critical"&&a.status!=="Resolved").length,"Priority incidents","negative")}${kpi("Acknowledged",alerts.filter(a=>a.status==="Acknowledged").length,"Assigned for investigation")}${kpi("Resolved",alerts.filter(a=>a.status==="Resolved").length,"Closed sample incidents","positive")}</div>
      <div class="mon-alert-toolbar"><div class="mon-filter-group"><label>Severity <select data-alert-severity><option>All</option><option>Critical</option><option>Warning</option><option>Info</option></select></label><label>Status <select data-alert-status><option>All</option><option>Open</option><option>Acknowledged</option><option>Resolved</option></select></label></div><span>${list.length} incidents shown</span></div>
      ${panel("Incident queue","Select an action to update the local demo incident state",table(["Incident","Severity","Affected system","Created","Owner","Status","Actions"],list.map(a=>`<tr><td><strong>${a.id}</strong><small>${esc(a.title)}</small></td><td>${badge(a.severity)}</td><td>${esc(a.device)}</td><td>${esc(a.time)}</td><td>${esc(a.owner)}</td><td>${badge(a.status)}</td><td><div class="mon-row-actions">${a.status==="Open"?`<button data-alert-action="ack" data-alert-id="${a.id}">Acknowledge</button>`:""}${a.status!=="Resolved"?`<button data-alert-action="resolve" data-alert-id="${a.id}">Resolve</button>`:""}</div></td></tr>`).join(""),"No incidents match these filters."))}
      <div class="mon-grid two">${panel("Response workflow","Suggested operational sequence",`<div class="mon-steps"><div><b>01</b><span><strong>Review severity</strong><small>Start with critical incidents and service impact.</small></span></div><div><b>02</b><span><strong>Acknowledge</strong><small>Record that the team has picked up the incident.</small></span></div><div><b>03</b><span><strong>Resolve</strong><small>Close the demo incident when remediation is complete.</small></span></div></div>`)}${panel("Severity guide","Sample incident prioritization",`<div class="mon-severity-guide"><div>${badge("Critical")}<span>Immediate investigation</span></div><div>${badge("Warning")}<span>Investigate soon</span></div><div>${badge("Info")}<span>Awareness or routine event</span></div></div>`)}</div>
    `);
  }

  function availabilityPage() {
    const days=Array.from({length:35},(_,i)=>i<5?96+i%3:i===22?83:97+(i*7%4));
    return shell("Availability & SLA","Review illustrative uptime objectives, daily posture and recent interruptions.",`
      <div class="mon-kpis">${kpi("Overall availability","99.94%","Sample 30-day aggregate","positive")}${kpi("SLA objective","99.90%","Illustrative service target")}${kpi("Error budget","74% remaining","Illustrative monthly budget","positive")}${kpi("Incidents this month","3","Sample incident history","negative")}</div>
      <div class="mon-grid two">${panel("Availability objective","Sample SLA target versus illustrative outcome",`<div class="mon-sla-score"><div class="mon-sla-ring"><strong>99.94<small>%</small></strong><span>Availability</span></div><div class="mon-sla-stats"><div><span>Target</span><strong>99.90%</strong></div><div><span>Margin above target</span><strong class="mon-good">+0.04%</strong></div><div><span>Equivalent downtime / 30d</span><strong>~26 min</strong></div></div></div>`)}${panel("Availability by service","Illustrative service-level view",`<div class="mon-avail-list">${services.slice(0,5).map(s=>`<div><span><strong>${s.name}</strong><small>${s.host}</small></span><div class="mon-avail-meter"><i class="${s.status==="Degraded"?"amber":""}" style="width:${parseFloat(s.uptime)}%"></i></div><b>${s.uptime}</b></div>`).join("")}</div>`)}</div>
      ${panel("Daily availability history","Illustrative daily posture over a rolling sample window",`<div class="mon-heatmap">${days.map((v,i)=>`<div title="Day ${i+1}: ${v}%" class="${v<90?"bad":v<97?"warn":"good"}"></div>`).join("")}</div><div class="mon-heatmap-legend"><span><i class="good"></i>Within objective</span><span><i class="warn"></i>Degraded</span><span><i class="bad"></i>Interruption</span><span>Sample window · 35 days</span></div>`)}
      ${panel("Incident history","Illustrative service interruptions",table(["Incident","Service","Start","Duration","Impact","Status"],[
        ["INC-308","Customer Portal","Today · 09:42","8 min","Elevated latency",badge("Resolved")],
        ["INC-302","Production Database","Yesterday · 16:18","14 min","Database degradation",badge("Resolved")],
        ["INC-291","Backup Scheduler","Oct 14 · 02:10","21 min","Scheduled job delay",badge("Resolved")],
      ].map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join("")}</tr>`).join("")))}
      <div class="mon-note"><strong>SLA disclaimer</strong><span>Uptime, downtime and error-budget figures are mock values for interface demonstration, not measured service commitments.</span></div>
    `);
  }

  function servicesPage() {
    const selected=services.find(s=>s.name===state.selectedService)||services[0];
    return shell("Service Monitoring","Inspect service status, response latency and supporting infrastructure.",`
      <div class="mon-kpis">${kpi("Defined services",services.length,"Sample service catalog")}${kpi("Operational",services.filter(s=>s.status==="Operational").length,"Normal sample status","positive")}${kpi("Degraded",services.filter(s=>s.status!=="Operational").length,"Needs review","negative")}${kpi("Median latency","64 ms","Illustrative sample readings")}</div>
      ${panel("Service catalog","Choose a service to inspect its summary",`<div class="mon-service-layout"><div class="mon-service-list">${services.map(s=>`<button class="mon-service-item ${selected.name===s.name?"active":""}" data-service="${esc(s.name)}"><span class="mon-service-symbol">${s.status==="Operational"?"✓":"!"}</span><span><strong>${esc(s.name)}</strong><small>${esc(s.group)} · ${esc(s.host)}</small></span><span>${badge(s.status)}</span></button>`).join("")}</div><div class="mon-service-detail"><div class="mon-detail-head"><span class="mon-detail-icon">◈</span><div><div class="mon-overline">SERVICE DETAILS</div><h3>${esc(selected.name)}</h3><p>${esc(selected.detail)}</p></div>${badge(selected.status)}</div><div class="mon-detail-kpis"><div><span>Response time</span><strong>${selected.latency} <small>ms</small></strong></div><div><span>Availability</span><strong>${selected.uptime}</strong></div><div><span>Endpoint port</span><strong>${selected.port||"N/A"}</strong></div></div><div class="mon-detail-section"><h4>Dependency</h4><div class="mon-dependency"><span>▣</span><div><strong>${esc(selected.host)}</strong><small>Hosting system · sample dependency</small></div>${badge(devices.find(d=>d.name===selected.host)?.status||"Unknown")}</div></div><div class="mon-detail-section"><h4>Recent checks</h4><div class="mon-checks"><div><span>Response time</span><strong>${selected.latency} ms</strong>${badge(selected.latency>300?"Degraded":"Passed")}</div><div><span>Availability sample</span><strong>${selected.uptime}</strong>${badge(selected.status)}</div></div></div></div></div>`)}
      <div class="mon-note"><strong>Demo mode</strong><span>Service status, response times and dependencies are illustrative records. No service probes are running.</span></div>
    `);
  }

  function render(host) {
    const page=host.dataset.monitorDashboard;
    const renderers={
      monitoring:monitoringPage,
      "monitoring-overview":overviewPage,
      "metrics-performance":metricsPage,
      alerts:alertsPage,
      availability:availabilityPage,
      "service-monitoring":servicesPage
    };
    host.innerHTML=(renderers[page]||monitoringPage)();
    const module=host.closest(".workspace-module");
    module?.classList.add("monitoring-redesigned");
    module?.querySelector(".workspace-stats")?.remove();
    module?.querySelector(".workspace-table-panel")?.remove();
    const label=module?.querySelector(".workspace-demo-label");
    if(label) label.textContent="DEMO DATA · LOCAL PREVIEW";
    const live=module?.querySelector("[data-monitor-live]");
    if(live) live.remove();
    bind(host);
  }

  function bind(host) {
    host.querySelectorAll("[data-range]").forEach(b=>b.addEventListener("click",()=>{
      state.range=b.dataset.range;render(host);
    }));
    host.querySelectorAll("[data-metric]").forEach(b=>b.addEventListener("click",()=>{
      state.metric=b.dataset.metric;render(host);
    }));
    host.querySelectorAll("[data-alert-severity],[data-alert-status]").forEach(s=>s.addEventListener("change",()=>{
      if(s.matches("[data-alert-severity]")) state.alertSeverity=s.value;
      if(s.matches("[data-alert-status]")) state.alertStatus=s.value;
      render(host);
      const sev=host.querySelector("[data-alert-severity]");
      const sta=host.querySelector("[data-alert-status]");
      if(sev)sev.value=state.alertSeverity;
      if(sta)sta.value=state.alertStatus;
    }));
    host.querySelectorAll("[data-alert-action]").forEach(b=>b.addEventListener("click",()=>{
      const a=alerts.find(x=>x.id===b.dataset.alertId);
      if(!a)return;
      a.status=b.dataset.alertAction==="ack"?"Acknowledged":"Resolved";
      render(host);
      const sev=host.querySelector("[data-alert-severity]");
      const sta=host.querySelector("[data-alert-status]");
      if(sev)sev.value=state.alertSeverity;
      if(sta)sta.value=state.alertStatus;
    }));
    host.querySelectorAll("[data-service]").forEach(b=>b.addEventListener("click",()=>{
      state.selectedService=b.dataset.service;render(host);
    }));
    host.querySelectorAll("[data-action=reset]").forEach(b=>b.addEventListener("click",()=>{
      state.range="24h";state.metric="CPU";state.alertSeverity="All";state.alertStatus="All";
      render(host);
    }));
    host.querySelectorAll("[data-action=export]").forEach(b=>b.addEventListener("click",()=>{
      const rows=[["System","OS","IP","Status","CPU","Memory","Disk"],...devices.map(d=>[d.name,d.os,d.ip,d.status,d.cpu,d.ram,d.disk])];
      const csv=rows.map(r=>r.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(",")).join("\r\n");
      const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
      const a=document.createElement("a");a.href=url;a.download="cartman-demo-inventory.csv";a.click();URL.revokeObjectURL(url);
    }));
    host.querySelectorAll("[data-local-search]").forEach(input=>input.addEventListener("input",()=>{
      const q=input.value.toLowerCase();
      host.querySelectorAll("tr[data-searchable]").forEach(tr=>tr.hidden=!tr.dataset.searchable.includes(q));
    }));
    host.querySelectorAll("[data-filter=scope]").forEach(select=>select.addEventListener("change",()=>{
      const value=select.value;
      host.querySelectorAll("tr[data-searchable]").forEach(tr=>{
        const device=devices.find(d=>tr.dataset.searchable.includes(d.name.toLowerCase()));
        tr.hidden=value!=="all"&&device?.group!==value;
      });
    }));
  }

  function init() {
    document.querySelectorAll("[data-monitor-dashboard]").forEach(host=>{
      if(host.dataset.monitorDemoReady)return;
      host.dataset.monitorDemoReady="1";
      render(host);
    });
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);
  else init();
})();