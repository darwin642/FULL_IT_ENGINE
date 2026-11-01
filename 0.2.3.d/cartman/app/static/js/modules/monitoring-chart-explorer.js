/* CARTMAN_MONITORING_EXPLORER_LIVE_V1 */
(() => {
  "use strict";

  const DEFINITIONS = [
    {key:"cpu", label:"CPU", title:"CPU utilization", aliases:["cpu_percent","cpu_usage","cpu_utilization","cpu"], unit:"%", color:"#49a4ff", kind:"percent"},
    {key:"memory", label:"Memory", title:"Memory utilization", aliases:["memory_percent","memory_usage","ram_usage","memory_utilization","mem_used_percent"], unit:"%", color:"#c084fc", kind:"percent"},
    {key:"disk", label:"Disk", title:"Disk utilization", aliases:["disk_percent","disk_usage","disk_utilization","volume_usage"], unit:"%", color:"#35d6b0", kind:"percent"},
    // Raw RX/TX byte counters are intentionally excluded: counters are not throughput rates.
    {key:"network", label:"Network", title:"Network throughput", aliases:["network_mbps","network_throughput","network_rate","network_io","bytes_per_sec","network_rx_bytes_per_sec","network_tx_bytes_per_sec","network_rx_mbps","network_tx_mbps","network_bytes_per_second"], unit:"", color:"#ffbd67", kind:"network"}
  ];

  const W = 1200, H = 560, L = 82, T = 38, B = 82;
  const BASE_R = 30, NETWORK_R = 88;
  const $ = (selector, root=document) => root.querySelector(selector);
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  const fmtTime = (value, full=false, span=0) => {
    const date = new Date(value);
    if (full) return date.toLocaleString([], {year:"numeric", month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit"});
    if (span <= 2*86400000) return date.toLocaleString([], {hour:"2-digit", minute:"2-digit"});
    if (span <= 10*86400000) return date.toLocaleString([], {month:"short", day:"2-digit", hour:"2-digit"});
    return date.toLocaleString([], {month:"short", day:"2-digit"});
  };
  const formatNumber = value => {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n/1e9).toFixed(2) + "B";
    if (abs >= 1e6) return (n/1e6).toFixed(2) + "M";
    if (abs >= 1e3) return (n/1e3).toFixed(2) + "k";
    return String(Number(n.toFixed(2)));
  };
  const unitKey = unit => String(unit || "").trim().toLowerCase().replace(/\s+/g, " ");

  function render(rows, options) {
    const host = $("#mo-charts-grid");
    if (!host) return;

    const opts = options || {};
    const rawRows = Array.isArray(rows) ? rows : [];
    const normal = typeof opts.normalizeKey === "function"
      ? opts.normalizeKey
      : value => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_");
    const escape = typeof opts.escapeHtml === "function"
      ? opts.escapeHtml
      : value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    const number = typeof opts.asNumber === "function"
      ? opts.asNumber
      : value => value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
    const timestamp = typeof opts.parseTimestamp === "function"
      ? opts.parseTimestamp
      : value => {
          if (!value) return NaN;
          const normalized = String(value).trim().replace(/^(\d{4}-\d{2}-\d{2})\s+/, "$1T");
          return new Date(normalized).getTime();
        };

    const rangeKey = `${opts.range || ""}|${$("#mo-date-from")?.value || ""}|${$("#mo-date-to")?.value || ""}`;
    const bounds = opts.bounds || {};
    let fullStart = Number(bounds.start);
    let fullEnd = Number(bounds.end);
    const now = Date.now();
    if (!Number.isFinite(fullStart) || !Number.isFinite(fullEnd) || fullEnd <= fullStart) {
      fullEnd = now;
      fullStart = now - 24 * 60 * 60 * 1000;
    }

    let state = host.__cartmanExplorerState;
    if (!state) {
      state = {
        rangeKey: null,
        fullStart,
        fullEnd,
        viewStart: fullStart,
        viewEnd: fullEnd,
        zoomed: false,
        visible: {cpu:true, memory:true, disk:true, network:true},
        yMax:60,
        autoY:true,
        netMax:1,
        autoNetY:true,
        granularity:"auto",
        modal:null
      };
      host.__cartmanExplorerState = state;
    }

    const rangeChanged = state.rangeKey !== rangeKey;
    state.fullStart = fullStart;
    state.fullEnd = fullEnd;
    if (rangeChanged) {
      state.rangeKey = rangeKey;
      state.viewStart = fullStart;
      state.viewEnd = fullEnd;
      state.zoomed = false;
      state.autoY = true;
      state.autoNetY = true;
    } else if (!state.zoomed) {
      state.viewStart = fullStart;
      state.viewEnd = fullEnd;
    } else {
      const span = clamp(state.viewEnd-state.viewStart, 1, fullEnd-fullStart);
      state.viewStart = clamp(state.viewStart, fullStart, fullEnd-span);
      state.viewEnd = state.viewStart + span;
    }

    function getLabel(row) { return String(opts.metricLabel?.(row) ?? row.metric_name ?? row.name ?? row.metric ?? "Metric"); }
    function getTime(row) { return opts.metricTime?.(row) ?? row.collected_at ?? row.timestamp ?? row.recorded_at ?? row.time; }
    function getValue(row) { return number(opts.metricValue?.(row) ?? row.value ?? row.current ?? row.latest_value); }
    function getUnit(row) { return String(opts.metricUnit?.(row) ?? row.unit ?? "").trim(); }
    function getSource(row) { return String(opts.metricSource?.(row) ?? row.source ?? "Monitoring API"); }

    const sourceSeries = DEFINITIONS.map(def => {
      const aliases = def.aliases.map(normal);
      let points = rawRows.filter(row => {
        const key = normal(getLabel(row));
        return aliases.some(alias => key === alias || key.includes(alias));
      }).map(row => {
        const label = normal(getLabel(row));
        let unit = getUnit(row) || def.unit;
        if (def.kind === "network" && !unit) {
          if (label.includes("mbps")) unit = "Mbps";
          else if (label.includes("bytes_per_sec") || label.includes("bytes_per_second")) unit = "B/s";
          else unit = "reported units";
        }
        return {
          time: timestamp(getTime(row)),
          value: getValue(row),
          unit,
          source: getSource(row),
          label
        };
      }).filter(point => Number.isFinite(point.time) && point.value !== null && point.time >= fullStart && point.time <= fullEnd)
        .sort((a,b) => a.time-b.time);

      if (def.kind === "percent") {
        points = points.map(point => ({...point, unit:"%"}));
      } else if (points.length) {
        // Keep one compatible network unit per series; never put unlike units on one axis.
        const latest = points[points.length-1];
        const chosenUnit = unitKey(latest.unit);
        points = points.filter(point => unitKey(point.unit) === chosenUnit);
      }

      return {...def, points, unit: points.length ? points[points.length-1].unit : def.unit};
    });

    const dataPercent = sourceSeries.filter(series => series.kind === "percent").flatMap(series => series.points);
    if (state.autoY && dataPercent.length) {
      const maxValue = Math.max(1, ...dataPercent.map(point => point.value));
      state.yMax = clamp(Math.ceil((maxValue * 1.2) / 10) * 10, 10, 100);
    }

    function duration() { return Math.max(1, state.viewEnd-state.viewStart); }
    function getViewPoints(series) {
      let points = series.points.filter(point => point.time >= state.viewStart && point.time <= state.viewEnd);
      const span = duration();
      let bucketMs = 0;
      if (state.granularity === "15m") bucketMs = 15*60*1000;
      else if (state.granularity === "1h") bucketMs = 60*60*1000;
      else if (state.granularity === "6h") bucketMs = 6*60*60*1000;
      else if (state.granularity === "1d") bucketMs = 24*60*60*1000;
      else bucketMs = span <= 2*86400000 ? 0 : span <= 9*86400000 ? 60*60*1000 : 6*60*60*1000;
      if (!bucketMs || bucketMs <= 15*60*1000 || points.length < 3) return points;
      const buckets = new Map();
      for (const point of points) {
        const key = Math.floor(point.time/bucketMs)*bucketMs;
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(point);
      }
      return [...buckets.entries()].sort((a,b)=>a[0]-b[0]).map(([time, entries]) => ({
        time,
        value: entries.reduce((sum, item) => sum+item.value, 0)/entries.length,
        unit: entries[entries.length-1].unit,
        source: entries[entries.length-1].source
      }));
    }

    const renderedSeries = sourceSeries.map(series => ({...series, viewPoints:getViewPoints(series)}));
    const hasPercent = renderedSeries.some(series => series.kind === "percent" && state.visible[series.key] && series.points.length);
    const networkSeries = renderedSeries.find(series => series.key === "network");
    const hasNetwork = Boolean(networkSeries && state.visible.network && networkSeries.points.length);
    const visiblePointCount = renderedSeries.filter(series => state.visible[series.key]).reduce((sum, series) => sum+series.viewPoints.length, 0);
    const currentRangeLabel = opts.rangeLabel || "Selected period";

    if (state.autoNetY && hasNetwork) {
      const netPts = networkSeries.viewPoints.length ? networkSeries.viewPoints : networkSeries.points;
      const maxValue = Math.max(0.01, ...netPts.map(point=>point.value));
      const minValue = Math.min(...netPts.map(point=>point.value));
      const padding = Math.max(maxValue*0.15, (maxValue-minValue)*0.2, 0.01);
      state.netMax = Math.max(0.1, Math.ceil((maxValue+padding)*100)/100);
    }

    const R = hasNetwork ? NETWORK_R : BASE_R;
    const PW = W-L-R, PH = H-T-B;
    const yPercent = value => T+PH-(value/state.yMax)*PH;
    const yNetwork = value => T+PH-(value/Math.max(0.1,state.netMax))*PH;
    const xTime = time => L + ((time-state.viewStart)/duration())*PW;

    const latestLabel = series => {
      const point = series.points[series.points.length-1];
      if (!point) return "No data";
      const value = formatNumber(point.value);
      if (series.kind === "percent") return value + "%";
      return value + (point.unit && point.unit !== "reported units" ? " " + point.unit : "");
    };

    const legend = renderedSeries.map(series => {
      const latest = latestLabel(series);
      const disabled = !series.points.length;
      const enabled = state.visible[series.key];
      return `<button type="button" class="mo-live-series${enabled ? "" : " is-off"}" data-live-series="${series.key}" aria-pressed="${enabled}" ${disabled ? "disabled" : ""} title="${series.points.length} real samples">
        <i class="mo-live-swatch" style="--live-series:${series.color}"></i>
        <span class="mo-live-series-name">${escape(series.label)}</span>
        <strong class="mo-live-series-value">${escape(latest)}</strong>
        <small>${series.points.length}</small>
      </button>`;
    }).join("");

    const viewStart = state.viewStart, viewEnd = state.viewEnd;
    const span = duration();
    const rangeDuration = Math.max(1, state.fullEnd-state.fullStart);
    const zoomPercent = Math.max(1, Math.round(span/rangeDuration*100));

    host.innerHTML = `<article class="mo-live-chart-card">
      <header class="mo-live-chart-head">
        <div><h3>Performance history</h3><p>${escape(currentRangeLabel)} · ${visiblePointCount} real plotted samples. Use the axes to scale/pan; drag inside the plot to zoom.</p></div>
        <div class="mo-live-chart-actions">
          <label class="mo-live-granularity">Resolution
            <select data-live-granularity aria-label="Chart data resolution">
              <option value="auto" ${state.granularity==="auto"?"selected":""}>Auto</option>
              <option value="15m" ${state.granularity==="15m"?"selected":""}>15 min</option>
              <option value="1h" ${state.granularity==="1h"?"selected":""}>1 hour</option>
              <option value="6h" ${state.granularity==="6h"?"selected":""}>6 hours</option>
              <option value="1d" ${state.granularity==="1d"?"selected":""}>1 day</option>
            </select>
          </label>
          <button type="button" class="mo-live-btn" data-live-prev ${state.viewStart<=state.fullStart+1000?"disabled":""} title="Previous time window">‹</button>
          <button type="button" class="mo-live-btn" data-live-next ${state.viewEnd>=state.fullEnd-1000?"disabled":""} title="Next time window">›</button>
          <button type="button" class="mo-live-btn" data-live-reset>Reset view</button>
          <button type="button" class="mo-live-btn primary" data-live-expand>${state.modal?"Close ✕":"Expand ↗"}</button>
        </div>
      </header>
      <div class="mo-live-legend">${legend}</div>
      <div class="mo-live-plot-wrap">
        <svg data-live-svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cartman device metrics history">
          <defs><clipPath id="mo-live-clip" data-live-clip><rect x="${L}" y="${T}" width="${PW}" height="${PH}"/></clipPath></defs>
          <g data-live-chart-content></g>
          <g data-live-interaction><line data-live-crosshair class="mo-live-crosshair" x1="${L}" x2="${L}" y1="${T}" y2="${T+PH}" visibility="hidden"/><rect data-live-brush class="mo-live-brush" x="${L}" y="${T}" width="0" height="${PH}" visibility="hidden"/></g>
        </svg>
        <div class="mo-live-tooltip" hidden></div>
        ${visiblePointCount ? "" : `<div class="mo-live-empty"><strong>No historical data</strong><p>No real samples were returned for the selected period. No demo values are generated.</p></div>`}
      </div>
      <footer class="mo-live-chart-footer"><span data-live-view-label>${escape(fmtTime(viewStart,true))} – ${escape(fmtTime(viewEnd,true))} · ${zoomPercent}% of selected period</span><span>Left axis: utilization (%) · Right axis: network ${hasNetwork ? "("+escape(networkSeries.unit || "reported units")+")" : "(not available)"}</span></footer>
    </article>`;

    const chartCard = host.querySelector(".mo-live-chart-card");
    const svg = host.querySelector("[data-live-svg]");
    const content = host.querySelector("[data-live-chart-content]");
    const crosshair = host.querySelector("[data-live-crosshair]");
    const brush = host.querySelector("[data-live-brush]");
    const tooltip = host.querySelector(".mo-live-tooltip");

    function drawChart() {
      // Recompute points for the current window so pointer-driven panning updates the lines continuously.
      for (const series of renderedSeries) series.viewPoints = getViewPoints(series);
      const currentPercentPoints = renderedSeries.filter(series => series.kind === "percent" && state.visible[series.key]).flatMap(series => series.viewPoints);
      if (state.autoY && currentPercentPoints.length) {
        const maxValue = Math.max(1, ...currentPercentPoints.map(point => point.value));
        state.yMax = clamp(Math.ceil((maxValue * 1.2) / 10) * 10, 10, 100);
      }
      if (state.autoNetY && networkSeries && state.visible.network && networkSeries.viewPoints.length) {
        const values = networkSeries.viewPoints.map(point => point.value);
        const maxValue = Math.max(0.01, ...values);
        const minValue = Math.min(...values);
        const padding = Math.max(maxValue * 0.15, (maxValue - minValue) * 0.2, 0.01);
        state.netMax = Math.max(0.1, Math.ceil((maxValue + padding) * 100) / 100);
      }
      const currentR = (state.visible.network && networkSeries.points.length) ? NETWORK_R : BASE_R;
      const plotWidth = W-L-currentR;
      const plotHeight = PH;
      const px = time => L+((time-state.viewStart)/Math.max(1,state.viewEnd-state.viewStart))*plotWidth;
      const pyPercent = value => T+plotHeight-(value/state.yMax)*plotHeight;
      const pyNetwork = value => T+plotHeight-(value/Math.max(0.1,state.netMax))*plotHeight;
      const showPercent = renderedSeries.some(series => series.kind==="percent" && state.visible[series.key] && series.points.length);
      const showNetwork = Boolean(state.visible.network && networkSeries.points.length);
      let markup = `<rect class="mo-live-plot-bg" x="${L}" y="${T}" width="${plotWidth}" height="${plotHeight}" rx="4"/>`;

      for (let i=0; i<=5; i++) {
        const y = T+plotHeight*(1-i/5);
        markup += `<line class="mo-live-gridline" x1="${L}" x2="${W-currentR}" y1="${y}" y2="${y}"/>`;
        if (showPercent) {
          markup += `<text class="mo-live-axis-label mo-live-y-percent" x="${L-12}" y="${y+4}" text-anchor="end">${Math.round(state.yMax*i/5)}%</text>`;
        }
        if (showNetwork) {
          const v=state.netMax*i/5, yy=pyNetwork(v);
          markup += `<text class="mo-live-axis-label mo-live-y-network" x="${W-currentR+12}" y="${yy+4}" text-anchor="start">${escape(formatNumber(v))}</text>`;
        }
      }
      if (showPercent) markup += `<text class="mo-live-axis-title" x="${L}" y="19">UTILIZATION (%)</text>`;
      if (showNetwork) markup += `<text class="mo-live-axis-title" x="${W-currentR}" y="19" text-anchor="end">NETWORK (${escape(networkSeries.unit || "reported units")})</text>`;

      for (let i=0;i<=6;i++) {
        const time=state.viewStart+(state.viewEnd-state.viewStart)*i/6;
        const x=L+plotWidth*i/6;
        const anchor=i===0?"start":i===6?"end":"middle";
        markup += `<line class="mo-live-tick" x1="${x}" x2="${x}" y1="${T+plotHeight}" y2="${T+plotHeight+6}"/><text class="mo-live-axis-label mo-live-x-label" x="${x}" y="${H-42}" text-anchor="${anchor}">${escape(fmtTime(time,false,state.viewEnd-state.viewStart))}</text>`;
      }

      for (const series of renderedSeries) {
        if (!state.visible[series.key] || !series.points.length) continue;
        const points=series.viewPoints.filter(p=>p.time>=state.viewStart && p.time<=state.viewEnd);
        if (!points.length) continue;
        const yFunc=series.kind==="network"?pyNetwork:pyPercent;
        const coords=points.length>600?Array.from({length:600},(_,i)=>points[Math.round(i*(points.length-1)/599)]):points;
        const path=coords.map((p,i)=>(i?"L":"M")+px(p.time).toFixed(2)+","+yFunc(p.value).toFixed(2)).join(" ");
        if (coords.length>1) markup += `<path d="${path}" fill="none" stroke="${series.color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" clip-path="url(#mo-live-clip)"/>`;
        const last=points[points.length-1];
        markup += `<circle cx="${px(last.time)}" cy="${yFunc(last.value)}" r="4" fill="${series.color}" stroke="#071522" stroke-width="2"><title>${escape(series.label)}: ${escape(latestLabel(series))}</title></circle>`;
      }
      markup += `<text class="mo-live-axis-label" x="${L}" y="${H-13}">← Earlier</text><text class="mo-live-axis-label" x="${W-currentR}" y="${H-13}" text-anchor="end">Later →</text>`;
      content.innerHTML = markup;
      const clipRect=svg.querySelector("[data-live-clip] rect");
      if (clipRect) { clipRect.setAttribute("x",String(L));clipRect.setAttribute("y",String(T));clipRect.setAttribute("width",String(plotWidth));clipRect.setAttribute("height",String(plotHeight)); }
      const crosshairLine=svg.querySelector("[data-live-crosshair]");
      if(crosshairLine){crosshairLine.setAttribute("y1",String(T));crosshairLine.setAttribute("y2",String(T+plotHeight));}
      const brushRect=svg.querySelector("[data-live-brush]");
      if(brushRect){brushRect.setAttribute("x",String(L));brushRect.setAttribute("y",String(T));brushRect.setAttribute("height",String(plotHeight));}
      const footer=host.querySelector("[data-live-view-label]");
      if(footer)footer.textContent=`${fmtTime(state.viewStart,true)} – ${fmtTime(state.viewEnd,true)} · ${Math.round((state.viewEnd-state.viewStart)/rangeDuration*100)}% of selected period`;
      const prev=host.querySelector("[data-live-prev]"), next=host.querySelector("[data-live-next]");
      if(prev)prev.disabled=state.viewStart<=state.fullStart+1000;
      if(next)next.disabled=state.viewEnd>=state.fullEnd-1000;
    }

    function redraw() { drawChart(); }
    const granularity = host.querySelector("[data-live-granularity]");
    if(granularity) granularity.addEventListener("change",()=>{state.granularity=granularity.value; render(rawRows,opts);});
    host.querySelectorAll("[data-live-series]").forEach(button=>button.addEventListener("click",()=>{state.visible[button.dataset.liveSeries]=!state.visible[button.dataset.liveSeries];render(rawRows,opts);}));
    const reset=host.querySelector("[data-live-reset]");
    if(reset)reset.addEventListener("click",()=>{state.viewStart=state.fullStart;state.viewEnd=state.fullEnd;state.zoomed=false;state.autoY=true;state.autoNetY=true;state.yMax=60;render(rawRows,opts);});
    const prev=host.querySelector("[data-live-prev]");
    if(prev)prev.addEventListener("click",()=>shiftWindow(-1));
    const next=host.querySelector("[data-live-next]");
    if(next)next.addEventListener("click",()=>shiftWindow(1));

    function shiftWindow(direction) {
      const span=state.viewEnd-state.viewStart;
      const shift=span*.5;
      const start=clamp(state.viewStart+direction*shift,state.fullStart,Math.max(state.fullStart,state.fullEnd-span));
      state.viewStart=start;state.viewEnd=start+span;state.zoomed=span<(state.fullEnd-state.fullStart)*.999;render(rawRows,opts);
    }

    function closeModal() {
      if(!state.modal)return;
      const modal=state.modal;
      if(modal.placeholder.parentNode)modal.placeholder.parentNode.insertBefore(host,modal.placeholder);
      modal.placeholder.remove();modal.overlay.remove();document.removeEventListener("keydown",modal.keyHandler);
      host.classList.remove("mo-live-chart-modal-host");state.modal=null;
    }
    function openModal() {
      if(state.modal){closeModal();return;}
      const parent=host.parentNode;if(!parent)return;
      const placeholder=document.createComment("Cartman chart location");
      parent.insertBefore(placeholder,host);
      const overlay=document.createElement("div");overlay.className="mo-live-chart-modal";overlay.setAttribute("role","dialog");overlay.setAttribute("aria-modal","true");overlay.setAttribute("aria-label","Expanded performance history");
      const panel=document.createElement("div");panel.className="mo-live-chart-modal-panel";
      const topbar=document.createElement("div");topbar.className="mo-live-chart-modal-top";
      const title=document.createElement("strong");title.textContent="Performance history";
      const close=document.createElement("button");close.type="button";close.className="mo-live-btn";close.textContent="Close ✕";close.setAttribute("aria-label","Close expanded chart");
      topbar.append(title,close);panel.append(topbar,host);overlay.append(panel);
      const keyHandler=event=>{if(event.key==="Escape")closeModal();};
      close.addEventListener("click",closeModal);overlay.addEventListener("click",event=>{if(event.target===overlay)closeModal();});
      host.classList.add("mo-live-chart-modal-host");state.modal={placeholder,overlay,keyHandler};document.body.append(overlay);document.addEventListener("keydown",keyHandler);close.focus();
    }
    const expand=host.querySelector("[data-live-expand]");
    if(expand)expand.addEventListener("click",openModal);

    if(svg) {
      let drag=null;
      const pointFromEvent=event=>{const rect=svg.getBoundingClientRect();return {x:(event.clientX-rect.left)/Math.max(1,rect.width)*W,y:(event.clientY-rect.top)/Math.max(1,rect.height)*H};};
      const percentAvailable=renderedSeries.some(s=>s.kind==="percent"&&state.visible[s.key]&&s.points.length);
      const networkAvailable=Boolean(state.visible.network&&networkSeries.points.length);
      svg.addEventListener("pointerdown",event=>{
        if(event.button!==undefined&&event.button!==0)return;
        const p=pointFromEvent(event), currentR=(state.visible.network&&networkSeries.points.length)?NETWORK_R:BASE_R;
        if(p.x>=0&&p.x<L&&p.y>=T&&p.y<=T+PH&&percentAvailable){drag={mode:"y",startY:p.y,startMax:state.yMax};svg.classList.add("mo-live-drag-y");}
        else if(p.x>=W-currentR&&p.x<=W&&p.y>=T&&p.y<=T+PH&&networkAvailable){drag={mode:"network",startY:p.y,startMax:state.netMax};state.autoNetY=false;svg.classList.add("mo-live-drag-y");}
        else if(p.x>=L&&p.x<=W-currentR&&p.y>T+PH+1&&p.y<=H-2){drag={mode:"pan",startX:p.x,startStart:state.viewStart,startEnd:state.viewEnd};svg.classList.add("mo-live-drag-x");}
        else if(p.x>=L&&p.x<=W-currentR&&p.y>=T&&p.y<=T+PH){drag={mode:"zoom",startX:p.x,currentX:p.x};const br=svg.querySelector("[data-live-brush]");br.setAttribute("x",String(p.x));br.setAttribute("width","0");br.setAttribute("visibility","visible");svg.classList.add("mo-live-drag-zoom");}
        else return;
        try{svg.setPointerCapture(event.pointerId);}catch(_){}
        event.preventDefault();
      });
      svg.addEventListener("pointermove",event=>{
        const p=pointFromEvent(event),currentR=(state.visible.network&&networkSeries.points.length)?NETWORK_R:BASE_R;
        if(drag?.mode==="y"){
          state.autoY=false;state.yMax=clamp(drag.startMax+(p.y-drag.startY)*.35,10,100);state.yMax=Number(state.yMax.toFixed(1));redraw();return;
        }
        if(drag?.mode==="network"){
          state.autoNetY=false;state.netMax=clamp(drag.startMax*Math.exp((p.y-drag.startY)/125),.01,1e12);redraw();return;
        }
        if(drag?.mode==="pan"){
          const span=drag.startEnd-drag.startStart,dx=p.x-drag.startX;
          const shift=-(dx/Math.max(1,W-L-currentR))*span;
          state.viewStart=clamp(drag.startStart+shift,state.fullStart,Math.max(state.fullStart,state.fullEnd-span));state.viewEnd=state.viewStart+span;state.zoomed=span<(state.fullEnd-state.fullStart)*.999;redraw();return;
        }
        if(drag?.mode==="zoom"){
          drag.currentX=clamp(p.x,L,W-currentR);const br=svg.querySelector("[data-live-brush]");br.setAttribute("x",String(Math.min(drag.startX,drag.currentX)));br.setAttribute("width",String(Math.abs(drag.currentX-drag.startX)));return;
        }
        if(p.x<L||p.x>W-currentR||p.y<T||p.y>T+PH){tooltip.hidden=true;crosshair.setAttribute("visibility","hidden");return;}
        const time=state.viewStart+((p.x-L)/Math.max(1,W-L-currentR))*(state.viewEnd-state.viewStart);
        crosshair.setAttribute("x1",String(p.x));crosshair.setAttribute("x2",String(p.x));crosshair.setAttribute("visibility","visible");
        const nearest=points=>{if(!points.length)return null;let result=points[0];for(const item of points)if(Math.abs(item.time-time)<Math.abs(result.time-time))result=item;return result;};
        let html=`<strong class="mo-live-tooltip-time">${escape(fmtTime(time,true))}</strong>`;
        for(const series of renderedSeries){if(!state.visible[series.key])continue;const item=nearest(series.viewPoints);if(!item)continue;const unit=series.kind==="percent"?"%":item.unit;html+=`<div class="mo-live-tooltip-row"><span><i style="--live-series:${series.color}"></i>${escape(series.label)}</span><strong>${escape(formatNumber(item.value))}${unit==="%"?"%":unit&&unit!=="reported units"?" "+escape(unit):""}</strong></div>`;}
        tooltip.innerHTML=html;tooltip.hidden=false;const tooltipRect=tooltip.getBoundingClientRect();const tooltipWidth=tooltipRect.width||228;const tooltipHeight=tooltipRect.height||120;tooltip.style.left=clamp(event.clientX+14,8,Math.max(8,window.innerWidth-tooltipWidth-8))+"px";tooltip.style.top=clamp(event.clientY+14,8,Math.max(8,window.innerHeight-tooltipHeight-8))+"px";
      });
      function finishDrag(){
        if(!drag)return;const current=drag;drag=null;svg.classList.remove("mo-live-drag-y","mo-live-drag-x","mo-live-drag-zoom");const br=svg.querySelector("[data-live-brush]");br.setAttribute("visibility","hidden");
        if(current.mode==="y"||current.mode==="network"){render(rawRows,opts);return;}
        if(current.mode==="pan"){render(rawRows,opts);return;}
        if(current.mode==="zoom"){
          const currentR=(state.visible.network&&networkSeries.points.length)?NETWORK_R:BASE_R;
          const x1=clamp(Math.min(current.startX,current.currentX??current.startX),L,W-currentR),x2=clamp(Math.max(current.startX,current.currentX??current.startX),L,W-currentR);
          if(x2-x1<15)return;
          const previousStart=state.viewStart,previousSpan=state.viewEnd-state.viewStart;
          const a=previousStart+(x1-L)/Math.max(1,W-L-currentR)*previousSpan;
          const b=previousStart+(x2-L)/Math.max(1,W-L-currentR)*previousSpan;
          if(b-a<1000)return;
          state.viewStart=a;state.viewEnd=b;state.zoomed=true;render(rawRows,opts);
        }
      }
      svg.addEventListener("pointerup",finishDrag);svg.addEventListener("pointercancel",finishDrag);
      svg.addEventListener("pointerleave",()=>{if(!drag){tooltip.hidden=true;crosshair.setAttribute("visibility","hidden");}});
      // No wheel handler: the user's wheel continues to scroll the page normally.
    }

    if (state.modal) {
      // The host may be rerendered by telemetry refresh while expanded; keep it inside the modal.
    }
    drawChart();
  }

  window.CartmanMonitoringExplorer = {render};
})();

/* CARTMAN_MONITORING_TOOLTIP_OVERLAY_FIX_V1 */
