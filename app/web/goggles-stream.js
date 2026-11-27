/* ==========================================================================
   Goggles Stream: viewer and monitor for the goggles → PC H.264 stream.
   Self-contained. Exposes window.GogglesStream = { mount, unmount, update }.

   Backend (window.pywebview.api):
     gstream_info()  -> { ok, state, message, stream_url, stats{}, device{}, ffmpeg{} }
     gstream_start() -> { ok, message }
     gstream_stop()  -> { ok, message }

   Without a pywebview host (browser preview, or app ?mock=1) it never polls
   the backend. It synthesizes a believable 1080p60 session instead.
   ========================================================================== */
(function () {
  "use strict";

  var POLL_MS = 1000;
  var SPARK_N = 60;                               // one sample per poll: 60 s of bitrate
  var MIME = 'video/mp4; codecs="avc1.640034"';   // H.264 High @ L5.2
  var LAG_MAX = 0.6;                              // seconds behind live edge before we jump
  var LAG_TARGET = 0.12;                          // where we land after a jump
  var BACK_BUFFER = 20;                           // seconds of played media kept in the SourceBuffer
  var QUEUE_MAX = 8 * 1024 * 1024;                // pending bytes before the player is rebuilt
  var STATES = ["idle", "starting", "live", "error"];

  var S = {
    mounted: false,
    bound: false,
    els: null,
    info: null,
    pollTimer: 0,
    inFlight: false,
    again: false,
    busy: "",
    hist: [],
    player: null,
    playerKey: "",
    mock: null,
    mockTimer: 0,
    mockStartTimer: 0,
    waitingHost: false,
    lastStatus: "",
  };

  /* ---------------------------------------------------------------- utils */
  function $(id) { return document.getElementById(id); }
  function noop() {}
  function num(v) { var n = Number(v); return v == null || v === "" || !isFinite(n) ? null : n; }
  function errText(err) { return (err && (err.message || String(err))) || "Unknown error"; }

  function api() {
    var pw = window.pywebview;
    return pw && pw.api ? pw.api : null;
  }
  function isMock() {
    var m = document.body && document.body.dataset.mode;
    if (m === "mock") return true;
    if (m === "host") return false;
    return !window.pywebview;
  }

  function toast(msg, kind, title) {
    try { if (typeof window.toast === "function") window.toast(msg, kind || "info", title || "Goggles stream"); } catch (e) { /* never throw */ }
  }
  function webLog(text) {
    try { if (typeof window.logWeb === "function") window.logWeb(text); } catch (e) { /* never throw */ }
  }

  function fmtInt(v) { v = num(v); return v == null ? "—" : Math.round(v).toLocaleString("en-US"); }
  function fmtFps(v) { v = num(v); return v == null ? "—" : v.toFixed(1); }
  function fmtMbps(kbps) { kbps = num(kbps); return kbps == null ? "—" : (kbps / 1000).toFixed(2); }
  function fmtBytes(b) {
    b = num(b);
    if (b == null) return "—";
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (b >= 1000 && i < u.length - 1) { b /= 1000; i++; }
    return (i ? b.toFixed(b < 10 ? 2 : 1) : String(Math.round(b))) + " " + u[i];
  }
  function fmtRes(w, h) { w = num(w); h = num(h); return w && h ? w + "×" + h : "—"; }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function fmtTc(frames, fps) {
    frames = num(frames);
    var base = Math.round(num(fps) || 0) || 60;
    if (frames == null) return "TC --:--:--:--";
    var f = Math.floor(frames), ff = f % base, s = Math.floor(f / base);
    return "TC " + pad2(Math.floor(s / 3600) % 100) + ":" + pad2(Math.floor(s / 60) % 60) + ":" + pad2(s % 60) + ":" + pad2(ff);
  }
  function fmtUptime(frames, fps) {
    frames = num(frames);
    var base = num(fps) || 60;
    if (!frames) return "";
    var s = Math.floor(frames / base);
    return pad2(Math.floor(s / 3600)) + ":" + pad2(Math.floor(s / 60) % 60) + ":" + pad2(s % 60);
  }

  function setText(el, value) {
    if (!el) return;
    var t = value == null || value === "" ? "—" : String(value);
    if (el.textContent !== t) el.textContent = t;
  }
  function setTone(el, tone) {
    if (!el) return;
    if (tone) el.dataset.tone = tone; else delete el.dataset.tone;
  }

  /* ------------------------------------------------------------- elements */
  function els() {
    if (S.els && S.els.page && S.els.page.isConnected) return S.els;
    var ids = ["page-gstream", "gsHero", "gsPill", "gsPillText", "gsHeroMeta", "gsRefresh", "gsFsBtn", "gsFsLabel",
      "gsStart", "gsStop", "gsStage", "gsVideo", "gsOverlay", "gsOverlayIcon", "gsOverlayTitle", "gsOverlayText",
      "gsPlay", "gsChipLive", "gsChipLiveText", "gsChipRes", "gsChipFps", "gsChipTc", "gsChipRate", "gsChipMock",
      "gsStageFs", "gsStatus", "gsStatusIcon", "gsUrl", "gsNote", "gsNoteTitle", "gsNoteText", "gsFps", "gsRate",
      "gsSpark", "gsRes", "gsFrames", "gsDropped", "gsLatency", "gsBytes", "gsFfmpeg", "gsPlayer", "gsMod", "gsFills",
      "gsSent", "gsDrops", "gsProps"];
    var e = {};
    ids.forEach(function (id) { e[id === "page-gstream" ? "page" : id] = $(id); });
    S.els = e.page ? e : null;
    return S.els;
  }

  /* ------------------------------------------------------------ normalise */
  function normalise(raw) {
    var r = raw && typeof raw === "object" ? raw : {};
    var state = STATES.indexOf(r.state) >= 0 ? r.state : (r.ok === false ? "error" : "idle");
    return {
      ok: r.ok !== false,
      state: state,
      message: typeof r.message === "string" ? r.message : "",
      stream_url: typeof r.stream_url === "string" ? r.stream_url : "",
      stats: r.stats && typeof r.stats === "object" ? r.stats : {},
      device: r.device && typeof r.device === "object" ? r.device : {},
      ffmpeg: r.ffmpeg && typeof r.ffmpeg === "object" ? r.ffmpeg : {},
    };
  }

  /* --------------------------------------------------------------- render */
  function render(raw) {
    var e = els();
    var info = normalise(raw);
    S.info = info;
    if (!e) return;

    var st = info.stats, dv = info.device, ff = info.ffmpeg;
    var state = info.state;
    var live = state === "live";
    var noFfmpeg = ff.available === false;
    var mock = Boolean(S.mock);

    // State on every container that styles from it
    e.page.dataset.state = state;
    e.gsHero.dataset.state = state;
    e.gsPill.dataset.state = state;
    e.gsStage.dataset.state = state;
    e.gsStage.dataset.mock = String(mock);
    e.gsChipLive.dataset.state = state;
    setText(e.gsPillText, { idle: "Idle", starting: "Starting", live: "Live", error: "Error" }[state]);
    setText(e.gsChipLiveText, live ? "LIVE" : state === "starting" ? "WAIT" : "OFF");
    e.gsChipMock.hidden = !mock;

    // History for the sparkline: bounded, cleared when not live
    if (live) {
      S.hist.push(num(st.kbps) || 0);
      if (S.hist.length > SPARK_N) S.hist.splice(0, S.hist.length - SPARK_N);
    } else {
      S.hist.length = 0;
    }
    drawSpark(e.gsSpark, S.hist);

    // Stream telemetry
    var res = fmtRes(st.width, st.height);
    setText(e.gsFps, live ? fmtFps(st.fps) : "—");
    setText(e.gsRate, live ? fmtMbps(st.kbps) : "—");
    setText(e.gsRes, res);
    setText(e.gsFrames, fmtInt(st.frames));
    var dropped = num(st.dropped), frames = num(st.frames);
    setText(e.gsDropped, dropped == null ? "—"
      : fmtInt(dropped) + (frames ? " · " + ((dropped / Math.max(frames, 1)) * 100).toFixed(2) + "%" : ""));
    setTone(e.gsDropped, dropped ? "warn" : null);
    var lat = num(st.latency_ms);
    if (lat === 0) lat = null;   // backend has no end-to-end clock; show "—"
    setText(e.gsLatency, lat == null ? "—" : Math.round(lat) + " ms");
    setTone(e.gsLatency, lat != null && lat > 250 ? "warn" : null);
    setText(e.gsBytes, fmtBytes(st.bytes));

    // HUD
    setText(e.gsChipRes, res === "—" ? "—" : res + (num(st.fps) ? "p" + Math.round(num(st.fps)) : ""));
    setText(e.gsChipFps, (live ? fmtFps(st.fps) : "—") + " fps");
    setText(e.gsChipTc, live ? fmtTc(st.frames, st.fps) : "TC --:--:--:--");
    setText(e.gsChipRate, (live ? fmtMbps(st.kbps) : "—") + " Mb/s");

    // Hero summary line
    var up = live ? fmtUptime(st.frames, st.fps) : "";
    setText(e.gsHeroMeta,
      live ? [res !== "—" ? res : null, num(st.fps) ? fmtFps(st.fps) + " fps" : null,
              num(st.kbps) != null ? fmtMbps(st.kbps) + " Mb/s" : null, up ? "up " + up : null]
              .filter(Boolean).join("  ·  ") || "Live"
      : state === "starting" ? "Opening reader on the goggles…"
      : state === "error" ? "Session stopped with an error"
      : "No active session");

    // Link
    if (ff.available === true) { setText(e.gsFfmpeg, "ffmpeg ✓"); setTone(e.gsFfmpeg, "ok"); }
    else if (noFfmpeg) { setText(e.gsFfmpeg, "ffmpeg missing"); setTone(e.gsFfmpeg, "bad"); }
    else { setText(e.gsFfmpeg, "—"); setTone(e.gsFfmpeg, null); }
    e.gsFfmpeg.title = ff.path || "";
    setText(e.gsUrl, mock ? "mock://gstream" : info.stream_url || "—");
    e.gsUrl.title = info.stream_url || "Stream URL";

    // Device
    if (dv.mod === true) { setText(e.gsMod, "installed"); setTone(e.gsMod, "ok"); }
    else if (dv.mod === false) { setText(e.gsMod, "not installed"); setTone(e.gsMod, "bad"); }
    else { setText(e.gsMod, "—"); setTone(e.gsMod, null); }
    setText(e.gsFills, fmtInt(dv.fills));
    setText(e.gsSent, fmtInt(dv.sent));
    setText(e.gsDrops, fmtInt(dv.drops));
    setTone(e.gsDrops, num(dv.drops) ? "warn" : null);
    if (dv.props === true) { setText(e.gsProps, "set"); setTone(e.gsProps, "ok"); }
    else if (dv.props === false) { setText(e.gsProps, "not set"); setTone(e.gsProps, "warn"); }
    else { setText(e.gsProps, "—"); setTone(e.gsProps, null); }

    // Controls
    syncButtons();

    // Playback follows state + url, and only ever runs while mounted
    if (!mock && S.mounted) syncPlayer(live && !noFfmpeg ? info.stream_url : "");
    renderPlayerInfo();
    renderOverlay();
  }

  function syncButtons() {
    var e = els(), info = S.info;
    if (!e || !info) return;
    var st = info.state;
    e.gsStart.disabled = Boolean(S.busy) || st === "starting" || st === "live";
    e.gsStop.disabled = Boolean(S.busy) || st === "idle";
  }

  /* Overlay, rail note and status line all read the same derived state */
  function renderOverlay() {
    var e = els(), info = S.info;
    if (!e || !info) return;
    var state = info.state, ff = info.ffmpeg, p = S.player, mock = Boolean(S.mock);
    var video = mock ? "playing" : !p ? "none" : p.failed ? "failed" : p.blocked ? "blocked" : p.ready ? "playing" : "waiting";
    e.gsStage.dataset.video = state === "live" ? video : "none";
    e.gsPlay.hidden = !(state === "live" && video === "blocked");

    var icon = "i-goggles", title = "Stream is off", text = "Press Start stream to watch the goggles' encoder output.";
    var status = "Idle. Press Start stream, then double-click the video or press F for fullscreen.", tone = "";
    var note = null;

    if (ff.available === false) {
      note = { tone: "risky", title: "ffmpeg not found",
        text: "The backend wraps H.264 into fMP4 with ffmpeg (stream copy, no re-encode). Install it or set its path, then press Refresh." +
              (ff.path ? " Looked for: " + ff.path : "") };
    }

    if (state === "starting") {
      icon = "i-radio"; title = "Connecting…";
      text = "Waiting for SPS/PPS and the first keyframe from 192.168.60.2:5571.";
      status = info.message || "Starting the MDC reader on the goggles…"; tone = "warn";
    } else if (state === "error" || (ff.available === false && state !== "idle")) {
      icon = "i-alert"; title = ff.available === false ? "ffmpeg not found" : "Stream error";
      text = info.message || "The stream stopped unexpectedly. Check the Logs page, then try Start again.";
      status = info.message || "Stream error."; tone = "error";
      if (!note) note = { tone: "risky", title: "Stream error", text: text + " Stop clears the session on the goggles." };
    } else if (state === "live") {
      tone = "live";
      if (video === "failed") {
        icon = "i-alert"; title = "Playback failed";
        text = (p && p.error) || "This WebView could not decode the stream.";
        status = "Live on the goggles, but the player could not open " + (info.stream_url || "the stream") + "."; tone = "error";
      } else if (video === "waiting") {
        icon = "i-goggles"; title = "Buffering…";
        text = "Waiting for the first keyframe. That can take up to one GOP.";
        status = info.message || "Live. Buffering the first keyframe…";
      } else if (video === "blocked") {
        status = "Autoplay was blocked by the WebView. Click the video to start playback.";
        tone = "warn";
      } else {
        status = info.message || (mock
          ? "Mock session. No goggles connected, so these numbers are synthesized."
          : "Live. Playback stays about 0.4 s behind the newest frame. Double-click the video or press F for fullscreen.");
      }
    } else if (info.message) {
      status = info.message;
    }

    if (e.gsOverlayIcon.getAttribute("href") !== "#" + icon) e.gsOverlayIcon.setAttribute("href", "#" + icon);
    setText(e.gsOverlayTitle, title);
    setText(e.gsOverlayText, text);

    var sIcon = tone === "error" ? "i-alert" : tone === "live" ? "i-check" : "i-info";
    if (e.gsStatusIcon.getAttribute("href") !== "#" + sIcon) e.gsStatusIcon.setAttribute("href", "#" + sIcon);
    e.gsStatus.parentNode.dataset.tone = tone;
    if (S.lastStatus !== status) { S.lastStatus = status; setText(e.gsStatus, status); e.gsStatus.title = status; }

    e.gsNote.hidden = !note;
    if (note) {
      e.gsNote.dataset.tone = note.tone;
      setText(e.gsNoteTitle, note.title);
      setText(e.gsNoteText, note.text);
    }
  }

  function renderPlayerInfo() {
    var e = els();
    if (!e) return;
    if (S.mock) { setText(e.gsPlayer, "mock"); setTone(e.gsPlayer, "muted"); return; }
    var p = S.player;
    if (!p) { setText(e.gsPlayer, "—"); setTone(e.gsPlayer, null); return; }
    if (p.failed) { setText(e.gsPlayer, "failed"); setTone(e.gsPlayer, "bad"); return; }
    var lag = bufferLag();
    setText(e.gsPlayer, (p.mode === "mse" ? "MSE" : "native") + (lag != null ? " · " + lag.toFixed(2) + " s buf" : ""));
    setTone(e.gsPlayer, lag != null && lag > LAG_MAX ? "warn" : null);
  }

  function drawSpark(svg, samples) {
    if (!svg) return;
    var line = svg.querySelector(".gs-spark-line"), area = svg.querySelector(".gs-spark-area");
    var W = 120, H = 28;
    if (!samples || samples.length < 2) { line.setAttribute("d", ""); area.setAttribute("d", ""); return; }
    var max = Math.max.apply(null, samples) * 1.15 || 1;
    var min = Math.min.apply(null, samples) * 0.85;
    var span = Math.max(max - min, max * 0.1, 1);
    var step = W / (SPARK_N - 1), x0 = W - (samples.length - 1) * step;   // newest on the right
    var d = samples.map(function (v, i) {
      return (i ? "L" : "M") + (x0 + i * step).toFixed(1) + " " + (H - 2 - ((v - min) / span) * (H - 5)).toFixed(1);
    }).join("");
    line.setAttribute("d", d);
    area.setAttribute("d", d + "L" + W + " " + H + "L" + x0.toFixed(1) + " " + H + "Z");
  }

  /* --------------------------------------------------------------- player */
  function syncPlayer(url) {
    if (url === S.playerKey) return;
    S.playerKey = url;
    stopPlayer();
    if (url) startPlayer(url);
  }

  function startPlayer(url) {
    var video = els() && els().gsVideo;
    if (!video) return;
    var p = { url: url, mode: "", dead: false, ready: false, blocked: false, failed: false, error: "",
              ms: null, sb: null, objectUrl: "", ctrl: null, reader: null, queue: [], queued: 0 };
    S.player = p;
    var mseOk = false;
    try { mseOk = Boolean(window.MediaSource && MediaSource.isTypeSupported(MIME) && window.fetch && window.ReadableStream && window.AbortController); }
    catch (e) { mseOk = false; }
    if (!mseOk) { fallback(p, "MSE unavailable"); return; }

    try {
      p.mode = "mse";
      p.ms = new MediaSource();
      p.objectUrl = URL.createObjectURL(p.ms);
      p.ms.addEventListener("sourceopen", function () { onSourceOpen(p); }, { once: true });
      video.src = p.objectUrl;
      tryPlay(p);
    } catch (err) {
      fallback(p, errText(err));
    }
  }

  function onSourceOpen(p) {
    if (p.dead) return;
    try {
      p.sb = p.ms.addSourceBuffer(MIME);
      p.sb.addEventListener("updateend", function () { onUpdateEnd(p); });
      p.sb.addEventListener("error", function () { if (!p.dead) fallback(p, "SourceBuffer error"); });
    } catch (err) {
      fallback(p, errText(err));
      return;
    }
    p.ctrl = new AbortController();
    fetch(p.url, { signal: p.ctrl.signal, cache: "no-store" })
      .then(function (res) {
        if (p.dead) return null;
        if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
        p.reader = res.body.getReader();
        return readLoop(p);
      })
      .catch(function (err) {
        if (p.dead || (err && err.name === "AbortError")) return;
        webLog("✗ gstream player — " + errText(err) + " (falling back to native <video>)");
        fallback(p, errText(err));
      });
  }

  function readLoop(p) {
    return p.reader.read().then(function (r) {
      if (p.dead) return null;
      if (r.done) { p.ended = true; return null; }
      if (r.value && r.value.byteLength) {
        p.queue.push(r.value);
        p.queued += r.value.byteLength;
        if (p.queued > QUEUE_MAX) { restartPlayer("player queue overflow"); return null; }
        pump(p);
      }
      return readLoop(p);
    });
  }

  function pump(p) {
    if (p.dead || !p.sb || p.sb.updating || !p.queue.length || !p.ms || p.ms.readyState !== "open") return;
    var chunk;
    if (p.queue.length === 1) chunk = p.queue[0];
    else {
      chunk = new Uint8Array(p.queued);
      var off = 0;
      p.queue.forEach(function (c) { chunk.set(c, off); off += c.byteLength; });
    }
    try {
      p.sb.appendBuffer(chunk);
      p.queue = [];
      p.queued = 0;
    } catch (err) {
      if (err && err.name === "QuotaExceededError") { evict(p, true); return; }  // retried on updateend
      fallback(p, errText(err));
    }
  }

  function evict(p, hard) {
    var video = els() && els().gsVideo;
    if (!video || !p.sb || p.sb.updating) return false;
    try {
      var b = p.sb.buffered;
      if (!b.length) return false;
      var keepFrom = video.currentTime - (hard ? 2 : BACK_BUFFER);
      if (keepFrom - b.start(0) > (hard ? 0.5 : 5)) { p.sb.remove(b.start(0), keepFrom); return true; }
    } catch (e) { /* ignore */ }
    return false;
  }

  function onUpdateEnd(p) {
    if (p.dead) return;
    var video = els() && els().gsVideo;
    try {
      var b = p.sb.buffered;
      if (video && b.length) {
        var end = b.end(b.length - 1);
        // Stay near the live edge
        if (end - video.currentTime > LAG_MAX) video.currentTime = Math.max(b.start(b.length - 1), end - LAG_TARGET);
        // A gap at the start (first fragment not at 0) would stall playback
        if (video.currentTime < b.start(0)) video.currentTime = b.start(0);
      }
    } catch (e) { /* ignore */ }
    if (evict(p, false)) return;   // pump on the next updateend
    pump(p);
  }

  function fallback(p, why) {
    if (p.dead || p.mode === "native") return;
    var video = els() && els().gsVideo;
    teardownMse(p);
    p.mode = "native";
    p.error = why || "";
    if (!video) return;
    try {
      video.src = p.url;
      tryPlay(p);
    } catch (err) {
      fail(p, errText(err));
    }
  }

  function fail(p, why) {
    if (p.dead) return;
    p.failed = true;
    p.error = why || "This WebView could not decode the stream.";
    webLog("✗ gstream player — " + p.error);
    renderOverlay();
    renderPlayerInfo();
  }

  function tryPlay(p) {
    var video = els() && els().gsVideo;
    if (!video || p.dead) return;
    var pr;
    try { pr = video.play(); } catch (e) { pr = null; }
    if (pr && typeof pr.then === "function") {
      pr.then(function () {
        if (p.dead) return;
        if (p.blocked) { p.blocked = false; renderOverlay(); }
      }, function (err) {
        if (p.dead) return;
        if (err && err.name === "NotAllowedError") { p.blocked = true; renderOverlay(); }
        // AbortError: src changed under us, which is expected on fallback/teardown
      });
    }
  }

  function teardownMse(p) {
    if (p.ctrl) { try { p.ctrl.abort(); } catch (e) { /* ignore */ } p.ctrl = null; }
    if (p.reader) { try { p.reader.cancel().catch(noop); } catch (e) { /* ignore */ } p.reader = null; }
    if (p.ms && p.ms.readyState === "open") { try { if (!p.sb || !p.sb.updating) p.ms.endOfStream(); } catch (e) { /* ignore */ } }
    if (p.objectUrl) { try { URL.revokeObjectURL(p.objectUrl); } catch (e) { /* ignore */ } p.objectUrl = ""; }
    p.sb = null;
    p.ms = null;
    p.queue = [];
    p.queued = 0;
  }

  function stopPlayer() {
    var p = S.player;
    S.player = null;
    if (!p) return;
    p.dead = true;
    teardownMse(p);
    var video = els() && els().gsVideo;
    if (video) {
      try { video.pause(); } catch (e) { /* ignore */ }
      video.removeAttribute("src");
      try { video.load(); } catch (e) { /* ignore */ }
    }
  }

  function restartPlayer(why) {
    var url = S.playerKey;
    webLog("· gstream player restart — " + why);
    S.playerKey = "";
    syncPlayer(url);
  }

  function bufferLag() {
    var video = els() && els().gsVideo, p = S.player;
    if (!video || !p || !p.ready) return null;
    try {
      var b = video.buffered;
      return b.length ? Math.max(0, b.end(b.length - 1) - video.currentTime) : null;
    } catch (e) { return null; }
  }

  // Video element events, bound once
  function onVideoReady() {
    var p = S.player;
    if (!p || p.dead || p.ready) return;
    p.ready = true;
    renderOverlay();
    renderPlayerInfo();
  }
  function onVideoError() {
    var p = S.player, video = els() && els().gsVideo;
    if (!p || p.dead || !video || !video.getAttribute("src")) return;
    var code = video.error ? video.error.code : 0;
    var why = { 1: "aborted", 2: "network error", 3: "decode error", 4: "source not supported" }[code] || "media error";
    if (p.mode === "mse") fallback(p, "MSE " + why);
    else fail(p, "Native playback: " + why + ".");
  }

  /* -------------------------------------------------------------- polling */
  function poll() {
    if (!S.mounted || S.mock) return;
    if (S.inFlight) { S.again = true; return; }
    var a = api();
    if (!a) { waitForHost(); return; }
    if (typeof a.gstream_info !== "function") {
      safeRender({ ok: false, state: "error", message: "gstream_info() is not exposed by this backend build." });
      return;
    }
    S.inFlight = true;
    var pr;
    try { pr = Promise.resolve(a.gstream_info()); } catch (err) { pr = Promise.reject(err); }
    pr.then(function (info) {
      if (S.mounted) safeRender(info);
    }, function (err) {
      if (S.mounted) safeRender({ ok: false, state: "error", message: "gstream_info() failed: " + errText(err) });
    }).then(done, done);
    function done() {
      S.inFlight = false;
      if (S.again && S.mounted) { S.again = false; poll(); }
    }
  }

  function safeRender(info) {
    try { render(info); } catch (err) { webLog("✗ GogglesStream render — " + errText(err)); }
  }

  function startPolling() {
    clearInterval(S.pollTimer);
    poll();
    S.pollTimer = setInterval(poll, POLL_MS);
  }

  function onHostReady() {
    S.waitingHost = false;
    if (S.mounted && !S.mock) startPolling();
  }
  function waitForHost() {
    if (S.waitingHost) return;
    S.waitingHost = true;
    window.addEventListener("pywebviewready", onHostReady, { once: true });
  }

  /* ---------------------------------------------------------------- start / stop */
  function setBusy(which) {
    var e = els();
    S.busy = which || "";
    if (!e) return;
    [["start", e.gsStart, "Start stream", "Starting…"], ["stop", e.gsStop, "Stop stream", "Stopping…"]].forEach(function (b) {
      var on = S.busy === b[0], label = b[1].querySelector("span");
      b[1].classList.toggle("is-busy", on);
      b[1].setAttribute("aria-busy", String(on));
      if (label) label.textContent = on ? b[3] : b[2];
    });
    syncButtons();
  }

  function control(which) {
    if (S.busy) return;
    if (S.mock) { mockControl(which); return; }
    var a = api(), method = which === "start" ? "gstream_start" : "gstream_stop";
    if (!a || typeof a[method] !== "function") {
      toast(method + "() is not exposed by the backend.", "error");
      return;
    }
    setBusy(which);
    webLog("→ " + method + "()");
    var pr;
    try { pr = Promise.resolve(a[method]()); } catch (err) { pr = Promise.reject(err); }
    pr.then(function (res) {
      var ok = !res || res.ok !== false;
      var msg = (res && res.message) || (which === "start" ? "Stream starting" : "Stream stopped");
      webLog((ok ? "✓ " : "✗ ") + method + " — " + msg);
      toast(msg, ok ? "success" : "error");
    }, function (err) {
      webLog("✗ " + method + " — " + errText(err));
      toast(errText(err), "error");
    }).then(function () {
      setBusy("");
      if (S.mounted) poll();
    }).catch(noop);
  }

  /* ----------------------------------------------------------------- mock */
  function mockNew(state) {
    return { state: state, frames: state === "live" ? 60 * 252 : 0, bytes: state === "live" ? 70.4e6 : 0,
             dropped: 0, fills: state === "live" ? 60 * 252 + 3 : 0, sent: state === "live" ? 60 * 252 : 0, phase: 0 };
  }

  function mockInfo() {
    var m = S.mock;
    var live = m.state === "live";
    if (live) {
      m.phase += 1;
      var fps = 60 - (Math.random() < 0.08 ? 0.1 + Math.random() * 0.3 : Math.random() * 0.04);
      var kbps = 2200 + Math.sin(m.phase / 7) * 140 + Math.sin(m.phase / 2.3) * 45 + (Math.random() - 0.5) * 60;
      m.frames += Math.round(fps);
      m.fills += Math.round(fps);
      m.sent += Math.round(fps);
      m.bytes += (kbps * 1000) / 8;
      if (Math.random() < 0.02) m.dropped += 1;
      m.fps = fps;
      m.kbps = kbps;
    }
    return {
      ok: true,
      state: m.state,
      message: m.state === "starting" ? "Mock: starting the reader…" : "",
      stream_url: "",
      stats: live
        ? { fps: m.fps, kbps: m.kbps, frames: m.frames, dropped: m.dropped, width: 1920, height: 1080,
            latency_ms: 72 + Math.round(Math.random() * 22), bytes: m.bytes }
        : m.state === "starting" ? { width: 1920, height: 1080 } : {},
      device: { mod: true, fills: m.fills || null, sent: m.sent || null, drops: live ? 0 : null, props: true },
      ffmpeg: { available: true, path: "ffmpeg (mock)" },
    };
  }

  function mockTick() { if (S.mounted && S.mock) safeRender(mockInfo()); }

  function mockControl(which) {
    clearTimeout(S.mockStartTimer);
    setBusy(which);
    S.mockStartTimer = setTimeout(function () {
      if (!S.mounted || !S.mock) { setBusy(""); return; }
      if (which === "start") {
        S.mock = mockNew("starting");
        S.mockStartTimer = setTimeout(function () {
          if (!S.mounted || !S.mock) return;
          S.mock = mockNew("live");
          S.mock.frames = 0; S.mock.bytes = 0; S.mock.fills = 0; S.mock.sent = 0;
          mockTick();
        }, 1400);
        toast("Stream starting (mock)", "success");
      } else {
        S.mock = mockNew("idle");
        toast("Stream stopped (mock)", "success");
      }
      setBusy("");
      mockTick();
    }, which === "start" ? 450 : 350);
  }

  /* ----------------------------------------------------------- fullscreen */
  function isFs() { var e = els(); return Boolean(e && document.fullscreenElement === e.gsStage); }

  function toggleFullscreen() {
    var e = els();
    if (!e) return;
    try {
      if (document.fullscreenElement) {
        var x = document.exitFullscreen && document.exitFullscreen();
        if (x && x.catch) x.catch(noop);
      } else if (e.gsStage.requestFullscreen) {
        var r = e.gsStage.requestFullscreen({ navigationUI: "hide" });
        if (r && r.catch) r.catch(function (err) { toast("Fullscreen unavailable: " + errText(err), "error"); });
      } else {
        toast("Fullscreen is not supported in this WebView.", "error");
      }
    } catch (err) {
      toast("Fullscreen unavailable: " + errText(err), "error");
    }
  }

  function onFsChange() {
    var e = els();
    if (!e) return;
    var on = isFs();
    e.gsFsBtn.dataset.fs = on ? "on" : "off";
    e.gsFsBtn.setAttribute("aria-pressed", String(on));
    setText(e.gsFsLabel, on ? "Exit fullscreen" : "Fullscreen");
    e.gsStageFs.title = on ? "Exit fullscreen (Esc)" : "Fullscreen (F)";
  }

  function onKey(ev) {
    if (!S.mounted || ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key !== "f" && ev.key !== "F") return;
    var t = ev.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
    if (document.querySelector(".overlay.is-open, .overlay[aria-hidden='false']")) return;
    ev.preventDefault();
    toggleFullscreen();
  }

  /* --------------------------------------------------------------- events */
  function bindOnce() {
    var e = els();
    if (!e || S.bound) return;
    S.bound = true;
    e.gsStart.addEventListener("click", function () { control("start"); });
    e.gsStop.addEventListener("click", function () { control("stop"); });
    e.gsRefresh.addEventListener("click", function () {
      if (S.mock) { mockTick(); toast("Stream info refreshed (mock)", "info"); return; }
      poll();
    });
    e.gsFsBtn.addEventListener("click", toggleFullscreen);
    e.gsStageFs.addEventListener("click", function (ev) { ev.stopPropagation(); toggleFullscreen(); });
    e.gsStage.addEventListener("dblclick", function (ev) {
      if (ev.target.closest("button")) return;
      toggleFullscreen();
    });
    e.gsPlay.addEventListener("click", function () { if (S.player) tryPlay(S.player); });
    e.gsVideo.addEventListener("loadeddata", onVideoReady);
    e.gsVideo.addEventListener("playing", onVideoReady);
    e.gsVideo.addEventListener("error", onVideoError);
  }

  /* ------------------------------------------------------------------ API */
  function mount() {
    if (!els()) return;
    bindOnce();
    if (S.mounted) { if (S.mock) mockTick(); else poll(); return; }
    S.mounted = true;
    document.addEventListener("fullscreenchange", onFsChange);
    document.addEventListener("keydown", onKey);
    onFsChange();

    if (isMock()) {
      S.mock = S.mock || mockNew("live");
      mockTick();
      clearInterval(S.mockTimer);
      S.mockTimer = setInterval(mockTick, POLL_MS);
      return;
    }
    S.mock = null;
    // Never resume playback from a stale snapshot; the first poll decides.
    render(S.info && S.info.state !== "live" ? S.info : { state: "idle" });
    if (api()) startPolling(); else waitForHost();
  }

  function unmount() {
    if (!S.mounted) return;
    S.mounted = false;
    clearInterval(S.pollTimer);
    clearInterval(S.mockTimer);
    clearTimeout(S.mockStartTimer);
    S.pollTimer = S.mockTimer = S.mockStartTimer = 0;
    S.again = false;
    if (S.waitingHost) { window.removeEventListener("pywebviewready", onHostReady); S.waitingHost = false; }
    document.removeEventListener("fullscreenchange", onFsChange);
    document.removeEventListener("keydown", onKey);
    if (isFs()) { try { var x = document.exitFullscreen(); if (x && x.catch) x.catch(noop); } catch (err) { /* ignore */ } }
    stopPlayer();
    S.playerKey = "";
    S.hist.length = 0;
    if (S.busy) setBusy("");
    S.lastStatus = "";
  }

  function update(info) {
    try {
      if (!els()) return;
      bindOnce();
      render(info);
    } catch (err) {
      webLog("✗ GogglesStream.update — " + errText(err));
    }
  }

  window.GogglesStream = {
    mount: function () { try { mount(); } catch (err) { webLog("✗ GogglesStream.mount — " + errText(err)); } },
    unmount: function () { try { unmount(); } catch (err) { webLog("✗ GogglesStream.unmount — " + errText(err)); } },
    update: update,
  };
})();
