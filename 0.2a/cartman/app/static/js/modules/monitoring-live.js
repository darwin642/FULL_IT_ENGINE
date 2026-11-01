
(() => {
  "use strict";
  const root = document.querySelector("[data-monitor-live]");
  if (!root || root.dataset.initialized) return;
  root.dataset.initialized = "1";

  const slug = location.pathname.split("/").filter(Boolean).pop() || "monitoring";
  const configs = {
    monitoring: {title:"Monitoring Control Center",desc:"Host coverage, collector health and telemetry heartbeat."},
    "monitoring-overview": {title:"Infrastructure Health",desc:"Live-style overview of resource utilization and fleet health."},
    "metrics-performance": {title:"Metrics & Performance",desc:"Explore simulated telemetry across selectable time windows."},
    alerts: {title:"Alert Activity",desc:"Illustrative alert stream and threshold status; no real notifications are sent."},
    availability: {title:"Availability & SLA",desc:"Simulated uptime and response-time trends for monitored endpoints."},
    "service-monitoring": {title:"Service Health",desc:"Service checks, response latency and error-rate overview."}
  };
  const config = configs[slug] || configs.monitoring;
  const state = {period:"1h",metric:"CPU",tick:0,paused:false};
  const series = {CPU:[],RAM:[],Network:[],Disk:[],Latency:[],Errors:[]};
  const N = 48;
  const rand = (a,b) => a + Math.random()*(b-a);
  const clamp = (n,a,b) => Math.max(a,Math.min(b,n));
  const initial = {CPU:36,RAM:61,Network:42,Disk:27,Latency:48,Errors:1.1};
  Object.keys(series).forEach(k => {
    let v=initial[k];
    for(let i=0;i<N;i++){v=clamp(v+rand(-8,8),k==="Errors"?0:3,k==="Errors"?8:95);series[k].push(v);}
  });
  const current = k => series[k][series[k].length-1];
  const avg = k => series[k].reduce((a,b)=>a+b,0)/series[k].length;
  const fmt = (k,v) => k==="Network"?`${Math.round(v*1.7)} Mbps`:k==="Latency"?`${Math.round(v*2.2)} ms`:k==="Errors"?`${v.toFixed(1)}%`:`${Math.round(v)}%`;
  const colors = {CPU:"#55a7ff",RAM:"#9c8bff",Network:"#53d6bd",Disk:"#f6b75d",Latency:"#55a7ff",Errors:"#ff8290"};
  const timeLabel = () => new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"});
  const safe = s => String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  root.innerHTML = `
    <div class="ml-toolbar">
      <div><div class="ml-eyebrow">OBSERVABILITY / ${safe(slug.replaceAll("-"," ").toUpperCase())}</div>
      <div style="font-size:12px;color:#8799b4;margin-top:6px">${safe(config.desc)}</div></div>
      <div class="ml-live"><span class="ml-dot"></span><span data-ml-live-text>SIMULATED LIVE</span><span style="color:#8294ad">· Updated <time data-ml-time>—</time></span></div>
    </div>
    <div class="ml-grid" data-ml-metrics></div>
    <div class="ml-main-grid">
      <section class="ml-panel">
        <div class="ml-panel-head"><div><div class="ml-eyebrow">TIME SERIES</div><h2>${safe(config.title)}</h2><div class="ml-subtitle">Rolling sample data · values refresh every 2 seconds</div></div>
          <div class="ml-controls" data-ml-period>
            <button type="button" data-period="15m" aria-pressed="false">15m</button>
            <button type="button" data-period="1h" aria-pressed="true">1h</button>
            <button type="button" data-period="24h" aria-pressed="false">24h</button>
          </div>
        </div>
        <div class="ml-panel-head" style="margin-top:-3px;align-items:center">
          <div class="ml-controls"><select aria-label="Select metric" data-ml-metric><option>CPU</option><option>RAM</option><option>Network</option><option>Disk</option><option>Latency</option><option>Errors</option></select></div>
          <span class="ml-subtitle" data-ml-current>—</span>
        </div>
        <canvas class="ml-chart" data-ml-main-chart aria-label="Simulated metric time series"></canvas>
        <div class="ml-legend"><span><i class="ml-key"></i><span data-ml-legend>CPU usage</span></span><span><i class="ml-key warn"></i>Illustrative threshold</span></div>
      </section>
      <section class="ml-panel">
        <div class="ml-panel-head"><div><div class="ml-eyebrow">HEALTH SNAPSHOT</div><h2 data-ml-side-title>Collector status</h2></div><span class="ml-pill">DEMO</span></div>
        <div class="ml-side-list" data-ml-side-list></div>
        <p class="ml-demo-note" style="margin:14px 0 0">Demo telemetry is generated in this browser only. No host is contacted and no real monitoring data is collected.</p>
      </section>
    </div>
    <div class="ml-bottom-grid">
      <section class="ml-panel"><div class="ml-panel-head"><div><div class="ml-eyebrow">RESOURCE TRENDS</div><h2>Recent utilization</h2></div><span class="ml-subtitle">rolling window</span></div><div data-ml-trends></div></section>
      <section class="ml-panel"><div class="ml-panel-head"><div><div class="ml-eyebrow" data-ml-bottom-kicker>EVENT STREAM</div><h2 data-ml-bottom-title>Latest activity</h2></div><span class="ml-pill">SIMULATED</span></div><div data-ml-events></div></section>
    </div>`;

  const $ = s => root.querySelector(s);
  const metricCards = [
    ["CPU","CPU utilization","%"],["RAM","Memory used","%"],["Network","Network throughput","Mbps"],["Latency","Response latency","ms"]
  ];
  function draw(canvas, values, color, threshold) {
    if (!canvas) return;
    const rect=canvas.getBoundingClientRect();
    if(!rect.width || !rect.height) return;
    const dpr=window.devicePixelRatio||1;
    canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);
    const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);
    const w=rect.width,h=rect.height,p={l:30,r:8,t:12,b:22},cw=w-p.l-p.r,ch=h-p.t-p.b;
    ctx.clearRect(0,0,w,h);
    ctx.font="10px system-ui";ctx.fillStyle="#8193ad";ctx.strokeStyle="rgba(145,163,190,.14)";ctx.lineWidth=1;
    for(let i=0;i<=4;i++){const y=p.t+ch*i/4;ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(w-p.r,y);ctx.stroke();ctx.fillText(String(Math.round(100-i*25)),2,y+3);}
    const max=Math.max(100,...values,threshold||0),min=0;
    if(threshold){const y=p.t+ch*(1-threshold/max);ctx.setLineDash([4,4]);ctx.strokeStyle="#f6b75d88";ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(w-p.r,y);ctx.stroke();ctx.setLineDash([]);}
    const xy=(v,i)=>[p.l+cw*i/Math.max(1,values.length-1),p.t+ch*(1-(v-min)/(max-min))];
    ctx.beginPath();values.forEach((v,i)=>{const [x,y]=xy(v,i);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.lineTo(w-p.r,h-p.b);ctx.lineTo(p.l,h-p.b);ctx.closePath();
    const grad=ctx.createLinearGradient(0,p.t,0,h-p.b);grad.addColorStop(0,color+"44");grad.addColorStop(1,color+"00");ctx.fillStyle=grad;ctx.fill();
    ctx.beginPath();values.forEach((v,i)=>{const [x,y]=xy(v,i);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=color;ctx.lineWidth=2;ctx.lineJoin="round";ctx.stroke();
    const [lx,ly]=xy(values[values.length-1],values.length-1);ctx.beginPath();ctx.arc(lx,ly,3,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();
    ctx.fillStyle="#8193ad";ctx.fillText(state.period==="15m"?"-15m":state.period==="24h"?"-24h":"-1h",p.l,h-5);ctx.textAlign="right";ctx.fillText("now",w-p.r,h-5);ctx.textAlign="left";
  }
  function metricValue(k){return k==="Network"?`${Math.round(current(k)*1.7)} Mbps`:k==="Latency"?`${Math.round(current(k)*2.2)} ms`:k==="Errors"?`${current(k).toFixed(1)}%`:`${Math.round(current(k))}%`;}
  function renderCards(){
    const cards=metricCards.map(([k,label,unit])=>`
      <article class="ml-card"><div class="ml-card-top"><span>${label}</span><span style="color:${colors[k]}">●</span></div>
      <div class="ml-card-value" data-card-value="${k}">${metricValue(k)}</div>
      <div class="ml-card-foot"><span>${k==="Latency"?"Response time":"Current sample"}</span><span data-card-change="${k}">updating</span></div>
      <canvas class="ml-spark" data-spark="${k}" aria-label="${label} sparkline"></canvas></article>`).join("");
    $("[data-ml-metrics]").innerHTML=cards;
  }
  function renderSide(){
    const rows = slug==="alerts" ? [
      ["CPU threshold","Host demo-node-03 · above 80%","warn","Warning"],
      ["Memory pressure","Host demo-node-02 · sample event","crit","Critical"],
      ["Collector heartbeat","Browser-generated event","ok","Normal"]
    ] : slug==="availability" ? [
      ["API Gateway","Simulated endpoint check","ok","99.98%"],
      ["Identity Service","Simulated endpoint check","ok","99.95%"],
      ["Metrics Collector","Simulated endpoint check","warn","99.82%"],
      ["SLA target","Illustrative monthly objective","ok","99.90%"]
    ] : slug==="service-monitoring" ? [
      ["API Gateway","HTTP health check · demo","ok","Healthy"],
      ["Identity Service","Authentication check · demo","ok","Healthy"],
      ["Metrics Collector","Scrape simulation · demo","warn","Degraded"],
      ["Notification Worker","Queue check · demo","ok","Healthy"]
    ] : [
      ["Metrics collector","Browser-side simulation","ok","Running"],
      ["Last heartbeat","Updated with demo tick","ok","Just now"],
      ["Host coverage","Illustrative monitored nodes","ok","24 / 26"],
      ["Data source","No backend connection","warn","Demo only"]
    ];
    $("[data-ml-side-list]").innerHTML=rows.map(([name,desc,kind,val])=>`
      <div class="ml-side-row"><div><div class="ml-side-name">${safe(name)}</div><div class="ml-side-desc">${safe(desc)}</div></div><span class="ml-pill ${kind==="warn"?"warn":kind==="crit"?"crit":""}">${safe(val)}</span></div>`).join("");
    $("[data-ml-side-title]").textContent=slug==="alerts"?"Active conditions":slug==="availability"?"Endpoint availability":slug==="service-monitoring"?"Service checks":"Collector status";
  }
  function renderTrends(){
    $("[data-ml-trends]").innerHTML=["CPU","RAM","Network","Disk"].map(k=>{
      const val=current(k),pct=clamp(k==="Network"?val:val,0,100);
      return `<div style="padding:8px 0"><div style="display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#c7d3e5"><span>${k==="RAM"?"Memory":k==="Network"?"Network traffic":k==="Disk"?"Disk I/O":k}</span><strong>${metricValue(k)}</strong></div><div class="ml-bar"><span style="width:${pct}%;background:${colors[k]}"></span></div></div>`;
    }).join("");
  }
  function renderEvents(){
    const items = slug==="alerts" ? [
      ["crit","Critical","Memory pressure · demo-node-02","Sample event · just now"],
      ["warn","Warning","CPU usage crossed illustrative threshold","Sample event · 2m ago"],
      ["info","Info","Collector heartbeat received","Sample event · 5m ago"]
    ] : slug==="availability" ? [
      ["info","Check","API Gateway response check","Sample result · 42 ms"],
      ["info","Check","Identity Service response check","Sample result · 56 ms"],
      ["warn","Notice","Metrics Collector response variation","Sample result · 88 ms"]
    ] : slug==="service-monitoring" ? [
      ["info","Healthy","API Gateway health check passed","Sample check · just now"],
      ["info","Healthy","Identity Service health check passed","Sample check · 1m ago"],
      ["warn","Degraded","Metrics Collector latency elevated","Sample check · 2m ago"]
    ] : [
      ["info","Metric","CPU / memory samples refreshed","Browser demo · just now"],
      ["info","Heartbeat","Collector simulation tick","Browser demo · 2s ago"],
      ["warn","Notice","No external telemetry source connected","Demo environment"]
    ];
    $("[data-ml-events]").innerHTML=`<div>${items.map(([kind,title,desc,when])=>`
      <div class="ml-alert-item"><span class="ml-alert-dot ${kind}"></span><div><div class="ml-side-name">${safe(title)} · ${safe(desc)}</div><div class="ml-side-desc">${safe(when)}</div></div><span class="ml-subtitle">Demo</span></div>`).join("")}</div>`;
    $("[data-ml-bottom-kicker]").textContent=slug==="alerts"?"ALERT TIMELINE":slug==="availability"?"CHECK HISTORY":"RECENT ACTIVITY";
    $("[data-ml-bottom-title]").textContent=slug==="alerts"?"Recent alert events":slug==="availability"?"Recent availability checks":slug==="service-monitoring"?"Recent service checks":"Telemetry activity";
  }
  function renderChart(){
    const k=state.metric,vals=series[k];
    draw($("[data-ml-main-chart]"),vals,colors[k],k==="CPU"?80:k==="RAM"?85:k==="Errors"?5:null);
    $("[data-ml-current]").textContent=`Current: ${metricValue(k)}`;
    $("[data-ml-legend]").textContent=({CPU:"CPU utilization",RAM:"Memory utilization",Network:"Network throughput",Disk:"Disk I/O activity",Latency:"Response latency",Errors:"Error rate"})[k];
    $("[data-ml-metric]").value=k;
    root.querySelectorAll("[data-period]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.period===state.period)));
    root.querySelectorAll("[data-spark]").forEach(c=>draw(c,series[c.dataset.spark].slice(-20),colors[c.dataset.spark],null));
  }
  function render(){
    renderCards();renderSide();renderTrends();renderEvents();renderChart();
    $("[data-ml-time]").textContent=timeLabel();
  }
  function tick(){
    if(state.paused)return;
    state.tick++;
    Object.keys(series).forEach(k=>{
      const old=current(k),step=k==="Errors"?rand(-.45,.45):rand(-7,7);
      const lo=k==="Errors"?0:3,hi=k==="Errors"?8:96;
      series[k].push(Math.round(clamp(old+step,lo,hi)*10)/10);
      if(series[k].length>N)series[k].shift();
    });
    render();
  }
  $("[data-ml-period]").addEventListener("click",e=>{
    const b=e.target.closest("[data-period]");if(!b)return;
    state.period=b.dataset.period;renderChart();
  });
  $("[data-ml-metric]").addEventListener("change",e=>{state.metric=e.target.value;renderChart();});
  render();
  const timer=setInterval(tick,2000);
  document.addEventListener("visibilitychange",()=>{if(document.hidden)state.paused=true;else{state.paused=false;render();}});
  window.addEventListener("resize",renderChart);
  window.addEventListener("pagehide",()=>clearInterval(timer),{once:true});
})();
