/* CARTMAN_USER_METRICS_TRACKER_V1
   Approximate first-party Cartman usage only. No key contents, form values or desktop-wide activity. */
(() => {
  "use strict";
  if (window.__cartmanUserMetricsTracker === "CARTMAN_USER_METRICS_TRACKER_V1") return;
  window.__cartmanUserMetricsTracker = "CARTMAN_USER_METRICS_TRACKER_V1";
  let lastInteraction = 0;
  let lastTick = Date.now();
  const perMinuteSeconds = new Map();
  const IDLE_CUTOFF_MS = 5 * 60 * 1000;
  const MAX_BUCKETS = 3;
  const noteInteraction = () => { lastInteraction = Date.now(); };
  const trackedEvents = ["pointerdown", "keydown", "scroll", "touchstart", "click", "input", "change", "focus"];
  trackedEvents.forEach(type => document.addEventListener(type, noteInteraction, {capture:true, passive:true}));
  let lastPointerMove = 0;
  document.addEventListener("pointermove", () => {
    const now = Date.now();
    if (now - lastPointerMove > 15000) { lastPointerMove = now; noteInteraction(); }
  }, {capture:true, passive:true});
  async function sendBucket(bucket, seconds) {
    try {
      await fetch("/api/user-metrics/heartbeat", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type":"application/json", "Accept":"application/json"},
        body: JSON.stringify({bucket_start: bucket, active_seconds: seconds, page_path: location.pathname})
      });
    } catch (_) { /* Usage tracking must never interrupt Cartman. */ }
  }
  function tick() {
    const now = Date.now();
    const previousTick = lastTick;
    lastTick = now;
    const activeStart = Math.max(previousTick, lastInteraction);
    const elapsed = Math.max(0, Math.min(15, Math.floor((now - activeStart) / 1000)));
    const active = document.visibilityState === "visible" && lastInteraction > 0 && (now - lastInteraction) <= IDLE_CUTOFF_MS;
    if (!active || elapsed < 1) return;
    const bucket = Math.floor(now / 60000) * 60;
    const accumulated = Math.min(60, (perMinuteSeconds.get(bucket) || 0) + elapsed);
    perMinuteSeconds.set(bucket, accumulated);
    sendBucket(bucket, accumulated);
    for (const key of perMinuteSeconds.keys()) if (key < bucket - MAX_BUCKETS * 60) perMinuteSeconds.delete(key);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") lastTick = Date.now();
  });
  window.setInterval(tick, 15000);
})();
