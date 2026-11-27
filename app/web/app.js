/* ==========================================================================
   N3 ROOT — control deck front-end
   Talks to window.pywebview.api (see API.md). Without a host, or with
   ?mock=1, a deterministic in-page mock backend is used instead.
   ========================================================================== */
"use strict";

/* ---------- Error capture (surfaced by `webapp.py --selftest`) ---------- */
window.__n3errors = [];
window.addEventListener("error", (e) => {
  window.__n3errors.push(`${e.message} @ ${e.filename || "?"}:${e.lineno || 0}`);
});
window.addEventListener("unhandledrejection", (e) => {
  window.__n3errors.push(`unhandled: ${(e.reason && e.reason.message) || e.reason}`);
});

/* ---------- Constants ---------- */
const X = "×";
// Fallback until live_resolutions() answers: these are the exact labels the
// backend's SCALE_BY_LABEL table expects, so the UI never invents one.
const FALLBACK_SCALES = [
  "160x90 (fast)", "240x135", "320x180", "480x270",
  "640x360", "960x540", "1920x1080 (slow)",
];
let LIVE_SCALES = FALLBACK_SCALES.map(scaleFromLabel);
let DEFAULT_SCALE = "640x360";
const STATUS_INTERVAL = 5000;
const LOG_INTERVAL = 3000;
const FRAME_INTERVAL = 90;
const LOG_LINE_LIMIT = 2000;
const HOST_WAIT = 1500;
// Screenshot/QA helper: ?motion=0 forces the reduced-motion path so captured
// pages never sit mid-animation.
const FORCE_REDUCE = new URLSearchParams(location.search).get("motion") === "0";

const PAGES = [
  { id: "connection", title: "Connection", group: "Device", icon: "plug", risk: "RISKY",
    subtitle: "USB link, root session, ADB and stock-UI recovery." },
  { id: "live", title: "E420Z", group: "Device", icon: "goggles", risk: "EXPERIMENTAL",
    subtitle: "Live mirror of the goggles display and on-demand screenshots." },
  { id: "sparrow", title: "Sparrow2", group: "Device", icon: "radio", risk: "SAFE",
    subtitle: "Read-only inspection of the radio subsystem." },
  { id: "pcstream", title: "PC Stream", group: "Device", icon: "monitor", risk: "EXPERIMENTAL",
    subtitle: "Stream this desktop into the goggles over the USB link." },
  { id: "shell", title: "Root Shell", group: "System", icon: "terminal", risk: "RISKY",
    subtitle: "Run commands on the goggles as uid 0. Nothing runs until you press Run." },
  { id: "mods", title: "Mods & UI", group: "System", icon: "layers", risk: "EXPERIMENTAL",
    subtitle: "Install and remove N3 mods. Writes only to /vendor and /data/local/tmp." },
  { id: "logs", title: "Logs", group: "System", icon: "list", risk: "SAFE",
    subtitle: "Tail device and app logs. Refreshes every 3 seconds while open." },
  { id: "settings", title: "Settings", group: "System", icon: "sliders", risk: "SAFE",
    subtitle: "Preferences, goggles theme and the safety reference." },
  { id: "gstream", title: "Goggles Stream", group: "Device", icon: "camera", risk: "EXPERIMENTAL",
    subtitle: "1080p60 H.264 from the goggles, straight to this PC." },
];

const RISK_INFO = {
  SAFE: { label: "Safe", text: "Read-only or fully reversible. Nothing on the goggles changes.",
    examples: "Stop root · screenshots · logs · Sparrow2 reports" },
  EXPERIMENTAL: { label: "Experimental", text: "Restarts the goggles UI or changes files in /vendor. Undo with Recover stock UI.",
    examples: "Enable ADB · patched UI · live preview · themes" },
  RISKY: { label: "Risky", text: "Runs as root or replaces running processes. Mistakes may need manual recovery.",
    examples: "Start root · recover stock UI · root shell · terminal" },
};

const ACTIONS = {
  find_n3: { label: "Find N3", risk: "SAFE", icon: "search",
    desc: "Match the goggles by USB VID/PID, then probe only their RNDIS subnet. Never scans Wi-Fi or LAN." },
  enable_adb: { label: "Enable ADB", risk: "EXPERIMENTAL", icon: "bug",
    desc: "Expose adbd over the USB composition. The device re-enumerates once.",
    confirm: "The goggles drop and re-enumerate their USB link. Live preview and the root shell may disconnect for a few seconds." },
  start_root: { label: "Start root", risk: "RISKY", icon: "root",
    desc: "Launch the uid 0 TCP shell that every advanced feature relies on.",
    confirm: "This starts a root shell on the goggles. Every write this deck performs goes through it." },
  stop_root: { label: "Stop root", risk: "SAFE", icon: "power",
    desc: "Close the root shell. Nothing on the device is changed." },
  start_ui: { label: "Start patched UI", risk: "EXPERIMENTAL", icon: "bolt",
    desc: "Restart the glasses UI with the patched /vendor binary.",
    confirm: "The goggles UI restarts into the patched binary. The headset screen goes dark for a few seconds." },
  recover_stock: { label: "Recover stock UI", risk: "RISKY", icon: "undo",
    desc: "Stop patched processes and bring back the stock glasses UI.",
    confirm: "Patched processes are killed and the stock UI is relaunched. Use this when the menu or display misbehaves." },
  open_terminal: { label: "Open terminal", risk: "RISKY", icon: "terminal",
    desc: "Open a Windows terminal attached to the root shell.",
    confirm: "Opens a terminal window with a uid 0 prompt on the goggles. Commands typed there run as root." },
};

const SPARROW = {
  sparrow_report: { label: "Radio report", format: (r) => JSON.stringify(r.data ?? {}, null, 2) },
  sparrow_tools: { label: "Tool inventory", format: (r) => r.text || "" },
  sparrow_console: { label: "Console help", format: (r) => r.text || "" },
};

const QUICK_COMMANDS = [
  ["id", "Effective user and groups"],
  ["uname -a", "Kernel and build"],
  ["ps -A", "Process list"],
  ["ls -la /vendor", "Vendor overlay contents"],
  ["mount", "Mount table"],
  ["df -h", "Free space per mount"],
  ["ls -la /data/local/tmp", "Scratch directory"],
  ["uptime", "Uptime and load"],
];

const ACCENTS = ["purple", "cyan", "amber", "rose"];
const PREF_NAMES = { accent: "Accent", motion: "Motion", density: "Density", live_scale: "Default live scale" };

const LINK_COPY = {
  usb: { on: "Connected", off: "Not detected",
    subOn: (s) => `${s.transport || "USB"} · ${s.serial || "serial masked"}`,
    subOff: () => "Connect the goggles with a USB-C data cable" },
  root: { on: "Open", off: "Closed",
    subOn: () => "uid 0 · TCP shell reachable",
    subOff: () => "Start root to unlock shell, live and mods" },
  adb: { on: "Online", off: "Offline",
    subOn: () => "adbd enumerated over USB",
    subOff: () => "Enable ADB once root is open" },
};

const STAGE_COPY = {
  idle: ["Live preview is off", "Start live to mirror the goggles display."],
  offline: ["Goggles not reachable", "Connect USB and start root, then start live."],
  loading: ["Starting stream…", "The goggles UI is restarting. The first frame follows in a few seconds."],
  waiting: ["Waiting for frames", "The stream is up but no frame has arrived yet."],
  error: ["Stream interrupted", "Frames stopped arriving. Stop and start live to retry."],
  live: ["", ""],
};

const THEME_SWATCH = {
  purple: "linear-gradient(135deg, #C77DFF, #5B21B6)",
  menuonly: "linear-gradient(135deg, #1D1828 0 55%, #B44BFF 55%)",
  stock: "linear-gradient(135deg, #3A3F4B, #111318)",
};

/* ---------- State ---------- */
const state = {
  mode: "pending",
  backend: null,
  status: null,
  statusError: false,
  page: null,
  prefs: { accent: "purple", motion: true, density: "comfortable", live_scale: DEFAULT_SCALE },
  mods: null,
  modsError: "",
  themes: [],
  selectedTheme: null,
  logs: {},
  logsError: "",
  logsUpdated: null,
  logTab: "natartos",
  logCleared: {},
  autoScroll: true,
  shellHistory: [],
  historyIndex: -1,
  shellAcknowledged: false,
  sparrowText: "",
  visitedLive: false,
  live: { running: false, scale: DEFAULT_SCALE, userScale: false, frames: 0, misses: 0, failures: 0, timer: 0, lastShot: null },
  mockPc: { running: new URLSearchParams(location.search).get("pclive") === "1",
            size: "1280x720", fps: 12, quality: 65, frames: 420 },
  webLog: [],
  busy: new Set(),
  timers: { status: 0, logs: 0, pc: 0 },
  pc: null,
  inFlight: { status: false, logs: false },
};

/* ---------- Small utilities ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name) => `<svg class="i" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const badge = (risk) => `<span class="badge" data-risk="${risk}">${RISK_INFO[risk].label}</span>`;
const isOk = (res) => Boolean(res) && res.ok !== false;
const errorText = (err) => (err && err.message) || String(err || "Unknown error");
const stamp = (d = new Date()) => d.toTimeString().slice(0, 8);
const fmtBytes = (n) => {
  const b = Number(n) || 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
};
const normTheme = (t) => String(t || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const motionOn = () => !FORCE_REDUCE && state.prefs.motion !== false && !matchMedia("(prefers-reduced-motion: reduce)").matches;

/** "1920x1080 (slow)" -> { value: "1920x1080 (slow)", name: "1920×1080", hint: "slow" } */
function scaleFromLabel(label) {
  const text = String(label || "").trim();
  const m = /^(.*?)\s*\(([^)]*)\)\s*$/.exec(text);
  return {
    value: text,
    name: (m ? m[1] : text).replace(/[x×]/i, X),
    hint: m ? m[2] : "",
  };
}

/** Pixel size of a scale label, for the mock frame renderer. */
function scaleDims(label) {
  const m = /(\d+)\s*[x×]\s*(\d+)/.exec(String(label || ""));
  return m ? [Number(m[1]), Number(m[2])] : [640, 360];
}

/**
 * Accepts an old "640×360" preference or a full backend label and returns a
 * value from the current list. Falls back to the default scale.
 */
function normScale(value) {
  const s = String(value || "").replace(/[×✕]/g, "x").replace(/\s+/g, " ").trim().toLowerCase();
  if (!s) return DEFAULT_SCALE;
  const hit = LIVE_SCALES.find((o) => o.value.toLowerCase() === s ||
    o.name.replace(X, "x").toLowerCase() === s);
  return hit ? hit.value : DEFAULT_SCALE;
}

/** Replaces the scale list with the backend's exact labels. */
function setResolutions(labels) {
  if (!Array.isArray(labels) || !labels.length) return false;
  LIVE_SCALES = labels.map(scaleFromLabel);
  if (!LIVE_SCALES.some((o) => o.value === DEFAULT_SCALE)) DEFAULT_SCALE = LIVE_SCALES[0].value;
  renderScaleOptions();
  return true;
}

function normRisk(mod) {
  const r = String(mod.risk || "").toUpperCase();
  if (RISK_INFO[r]) return r;
  return mod.experimental ? "EXPERIMENTAL" : "SAFE";
}

function themeLabel(t) {
  if (!t) return "—";
  const known = { stock: "Stock", purple: "Purple", menuonly: "Menu only" };
  return known[normTheme(t)] || cap(String(t).replace(/[-_]/g, " "));
}

function setHTML(el, html) {
  if (el && el._html !== html) { el.innerHTML = html; el._html = html; }
}

function setOn(el, on) {
  if (!el) return;
  const v = String(Boolean(on));
  el.dataset.on = v;
  const dot = el.classList.contains("dot") ? null : $(".dot", el);
  if (dot) dot.dataset.on = v;
}

function restartAnimation(el, cls = "swap") {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

function swapText(el, text) {
  if (!el || el.textContent === text) return;
  el.textContent = text;
  restartAnimation(el);
}

function countUp(el, to) {
  if (!el) return;
  cancelAnimationFrame(el._raf);
  if (!Number.isFinite(to)) { el.textContent = "—"; el.dataset.value = ""; return; }
  const from = Number(el.dataset.value) || 0;
  el.dataset.value = String(to);
  if (!motionOn() || from === to) { el.textContent = String(to); return; }
  const start = performance.now();
  const duration = 700;
  const step = (now) => {
    const p = Math.min(1, (now - start) / duration);
    el.textContent = String(Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3))));
    if (p < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}

function stagger(root) {
  $$(".stagger", root).concat(root.classList?.contains("stagger") ? [root] : []).forEach((group) => {
    Array.from(group.children).forEach((child, i) => child.style.setProperty("--i", String(Math.min(i, 12))));
  });
}

async function copyText(text, message = "Copied to clipboard") {
  if (!text) { toast("Nothing to copy yet", "info"); return; }
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast(message, "success");
}

/** Opens a repo doc in the desktop's default editor/browser. */
async function openDoc(path) {
  try {
    const res = await invoke("open_doc", path);
    if (res && res.ok === false) throw new Error(res.message || "cannot open");
    toast("Opened " + path, "success");
  } catch (err) {
    toast(errorText(err), "error", "Docs");
  }
}

/* ==========================================================================
   Backend: host or mock
   ========================================================================== */
function detectMode() {
  if (new URLSearchParams(location.search).get("mock") === "1") { setMode("mock"); return; }
  if (window.pywebview && window.pywebview.api) { setMode("host"); return; }
  window.addEventListener("pywebviewready", () => setMode("host"), { once: true });
  // Inside pywebview the bridge object exists before its API is ready: keep waiting.
  setTimeout(() => { if (state.mode === "pending" && !window.pywebview) setMode("mock"); }, HOST_WAIT);
}

function setMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  state.backend = mode === "mock" ? createMock() : window.pywebview.api;
  state.mods = null;
  document.body.dataset.mode = mode;
  $("#mockChip").hidden = mode !== "mock";
  $("#sideMock").hidden = mode !== "mock";
  $("#aboutMode").textContent = mode === "mock" ? "Mock data (browser preview)" : "pywebview host";
  logWeb(mode === "mock" ? "Mode: mock data — no pywebview host detected" : "Mode: pywebview host connected");
  if (mode === "host" && state.page === "gstream") {
    // The page may have mounted in the pending/mock window before the bridge
    // existed; remount so it polls the real backend instead of mock data.
    window.GogglesStream?.unmount();
    window.GogglesStream?.mount();
  }

  clearInterval(state.timers.status);
  state.timers.status = setInterval(refreshStatus, STATUS_INTERVAL);
  loadPrefs();
  loadResolutions();
  refreshStatus();
  loadMods();
  onPageEnter(state.page);
}

async function invoke(method, ...args) {
  const backend = state.backend;
  if (!backend) throw new Error("Backend is not ready yet");
  if (typeof backend[method] !== "function") throw new Error(`${method}() is not exposed by the backend`);
  return backend[method](...args);
}

/** Calls a backend method with busy state, web log entry and result toast. */
async function call(method, args = [], opts = {}) {
  const { key = method, label = method, quiet = false, refresh = true } = opts;
  if (state.busy.has(key)) return null;
  setBusy(key, true);
  logWeb(`→ ${method}(${args.map((a) => JSON.stringify(a)).join(", ")})`);
  try {
    const res = (await invoke(method, ...args)) || {};
    const ok = res.ok !== false;
    logWeb(`${ok ? "✓" : "✗"} ${method}${res.message ? ` — ${res.message}` : ""}`);
    if (!quiet || !ok) toast(res.message || (ok ? "Done" : "Request failed"), ok ? "success" : "error", label);
    return res;
  } catch (err) {
    logWeb(`✗ ${method} — ${errorText(err)}`);
    toast(errorText(err), "error", label);
    return null;
  } finally {
    setBusy(key, false);
    if (refresh) refreshStatus();
  }
}

function setBusy(key, on) {
  if (on) state.busy.add(key); else state.busy.delete(key);
  const k = CSS.escape(key);
  $$(`[data-action="${k}"], [data-busy-key="${k}"]`).forEach((el) => {
    el.disabled = on;
    el.classList.toggle("is-busy", on);
    el.setAttribute("aria-busy", String(on));
  });
  if (!on) syncControls();
}

/** Re-applies disabled states that depend on app state, after busy flags clear. */
function syncControls() {
  renderLiveControls();
  if (state.page === "settings") renderThemes();
}

function logWeb(text) {
  state.webLog.push(`${stamp()}.${String(Date.now() % 1000).padStart(3, "0")}  ${text}`);
  if (state.webLog.length > 500) state.webLog.shift();
  if (state.page === "logs" && state.logTab === "web") renderLogs();
}

/* ==========================================================================
   Status
   ========================================================================== */
async function refreshStatus({ manual = false } = {}) {
  if (!state.backend || state.inFlight.status) return;
  state.inFlight.status = true;
  if (manual) setBusy("status", true);
  try {
    state.status = (await invoke("status")) || {};
    if (state.statusError) toast("Host is responding again", "success", "Status");
    else if (manual) toast("Status refreshed", "info");
    state.statusError = false;
  } catch (err) {
    if (!state.statusError || manual) toast(errorText(err), "error", "Status unavailable");
    state.statusError = true;
    state.status = null;
  } finally {
    state.inFlight.status = false;
    if (manual) setBusy("status", false);
    renderStatus();
  }
}

function linkState(s) {
  const transport = String(s.transport || "");
  const usb = typeof s.usb === "boolean" ? s.usb : Boolean(s.root || s.adb || (transport && !/^(none|offline|-)$/i.test(transport)));
  return { usb, root: Boolean(s.root), adb: Boolean(s.adb) };
}

function renderStatus() {
  const s = state.status || {};
  const loaded = state.status !== null || state.statusError;
  const links = linkState(s);

  Object.keys(links).forEach((k) => {
    setOn($(`#pill-${k}`), links[k]);
    if (!loaded) return;
    const card = $(`#stat-${k}`);
    const copy = LINK_COPY[k];
    setOn(card, links[k]);
    swapText($('[data-field="value"]', card), links[k] ? copy.on : copy.off);
    swapText($('[data-field="sub"]', card), state.statusError ? "Host not responding" : links[k] ? copy.subOn(s) : copy.subOff(s));
  });
  if (!loaded) return;

  renderDevice(s, links);
  renderChecklist(links);
  renderSide(s, links);
  setOn($("#shellDot"), links.root);
  $("#aboutBackend").textContent = s.version || "—";

  const stage = $("#stage").dataset.state;
  if (!state.live.running && (stage === "idle" || stage === "offline")) setStage(links.root ? "idle" : "offline");
  if (state.page === "settings") renderThemes();
}

function renderDevice(s, links) {
  $("#devName").textContent = s.device || "DJI Goggles N3";
  $("#devSerial").textContent = s.serial ? `S/N ${s.serial}` : "Serial unavailable";
  $("#devVersion").textContent = s.version ? `v${String(s.version).replace(/^v/i, "")}` : "No version";
  countUp($("#mLinks"), Object.values(links).filter(Boolean).length);
  countUp($("#mPid"), parseInt(s.pid, 10));

  const flag = (on, yes, no) => ({ text: on ? yes : no, on: Boolean(on) });
  const rows = [
    ["Transport", { text: s.transport || "—" }],
    ["Theme", { text: themeLabel(s.theme) }],
    ["Background", flag(s.background, "Custom", "Stock")],
    ["Menu row", flag(s.menu, "Installed", "Not installed")],
    ["Patched UI", flag(s.patched, "Running", "Stopped")],
    ["UI process", flag(s.ui, "Alive", "Not running")],
  ];
  if (s.n3) {
    const n3text = {
      no_device: "No USB device",
      no_rndis: "USB, no RNDIS",
      no_shell: "N3 found, no shell",
      shell_up: "N3 found, shell open",
    }[s.n3.stage] || "Scanned";
    rows.push(["N3 link", { text: n3text + (s.n3.goggles_ip ? " · " + s.n3.goggles_ip : "") }]);
  }
  setHTML($("#devKv"), rows.map(([k, v]) => `
    <div class="kv-row"><dt>${esc(k)}</dt><dd>${"on" in v ? `<span class="dot" data-on="${v.on}"></span>` : ""}${esc(v.text)}</dd></div>`).join(""));
}

function renderChecklist(links) {
  const done = { usb: links.usb, root: links.root, adb: links.adb, live: state.visitedLive };
  const steps = $$("#steps .step");
  let current = null;
  let count = 0;
  steps.forEach((li, i) => {
    const d = Boolean(done[li.dataset.step]);
    if (d) count += 1; else if (!current) current = li;
    li.dataset.done = String(d);
    setHTML($(".step-mark", li), d ? icon("check") : String(i + 1));
  });
  steps.forEach((li) => { li.dataset.current = String(li === current); });
  $("#stepCount").textContent = `${count} of ${steps.length}`;
  $("#stepBar").style.setProperty("--p", `${(count / steps.length) * 100}%`);
}

function renderSide(s, links) {
  setOn($("#sideDot"), links.usb);
  let text = "Waiting for USB";
  if (state.statusError) text = "Host not responding";
  else if (links.usb) text = `${s.transport || "USB"} · ${links.root ? "root open" : "no root"}`;
  $("#sideSub").textContent = text;
}

/* ==========================================================================
   Navigation
   ========================================================================== */
function go(id, { instant = false } = {}) {
  const page = PAGES.find((p) => p.id === id);
  if (!page || state.page === id) return;
  const prev = state.page;
  state.page = id;

  $$(".page").forEach((el) => el.classList.toggle("is-active", el.id === `page-${id}`));
  $$(".nav-item").forEach((b) => {
    const on = b.dataset.go === id;
    b.classList.toggle("is-active", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  moveIndicator(instant);

  $("#crumbGroup").textContent = page.group;
  $("#crumbPage").textContent = page.title;
  $("#pageTitle").textContent = page.title;
  $("#pageSubtitle").textContent = page.subtitle;
  const risk = $("#pageRisk");
  risk.dataset.risk = page.risk;
  risk.textContent = RISK_INFO[page.risk].label;
  if (!instant) restartAnimation($("#pageHead"));

  $("#main").scrollTop = 0;
  document.title = `${page.title} · N3 ROOT`;
  try { history.replaceState(null, "", `#${id}`); } catch { /* file:// without history support */ }

  onPageLeave(prev);
  onPageEnter(id);
}

function moveIndicator(instant = false) {
  const active = $(".nav-item.is-active");
  const ind = $("#navIndicator");
  if (!active) return;
  ind.classList.toggle("no-anim", instant);
  ind.style.transform = `translateY(${active.offsetTop}px)`;
  ind.style.height = `${active.offsetHeight}px`;
  ind.style.opacity = "1";
}

function onPageEnter(id) {
  if (!id) return;
  if (id === "gstream" && state.backend) window.GogglesStream?.mount();
  if (!state.backend) return;
  if (id === "live") {
    state.visitedLive = true;
    renderStatus();
    if (state.live.running) frameLoop();
  }
  if (id === "mods") loadMods();
  if (id === "logs") startLogs();
  if (id === "settings") loadThemes();
  if (id === "pcstream") startPcStream();
}

function onPageLeave(id) {
  if (id === "logs") clearInterval(state.timers.logs);
  if (id === "live") clearTimeout(state.live.timer);
  if (id === "pcstream") clearInterval(state.timers.pc);
  if (id === "gstream") window.GogglesStream?.unmount();
}

/* ==========================================================================
   PC Stream
   ========================================================================== */
function pcSet(id, value) {
  const el = $(id);
  if (el) el.textContent = value == null || value === "" ? "—" : String(value);
}

function renderPcStream() {
  const p = state.pc;
  if (!p) return;
  const sender = p.sender || {};
  const dev = p.device || {};
  const running = Boolean(sender.running);

  const page = document.getElementById("page-pcstream");
  if (page) page.classList.toggle("is-live", running);

  state.pcHist = state.pcHist || { fps: [], kbps: [] };
  if (running) {
    state.pcHist.fps.push(Number(sender.fps) || 0);
    state.pcHist.kbps.push(Number(sender.kbps) || 0);
    if (state.pcHist.fps.length > 30) state.pcHist.fps.shift();
    if (state.pcHist.kbps.length > 30) state.pcHist.kbps.shift();
  } else {
    state.pcHist.fps.length = 0;
    state.pcHist.kbps.length = 0;
  }
  if (typeof window.pcSparkline === "function") {
    window.pcSparkline({ fps: state.pcHist.fps, kbps: state.pcHist.kbps });
  }

  setOn($("#pcPill"), running);
  pcSet("#pcPillText", running ? "Streaming" : "Idle");
  pcSet("#pcFps", sender.fps != null ? sender.fps : 0);
  pcSet("#pcKbps", sender.kbps != null ? sender.kbps : 0);
  pcSet("#pcFrames", sender.frames != null ? sender.frames : 0);
  pcSet("#pcSize", sender.size);
  pcSet("#pcTarget", sender.fps_target != null ? `${sender.fps_target} fps` : null);
  pcSet("#pcQuality", sender.quality != null ? `q${sender.quality}` : null);
  pcSet("#pcSlow", sender.slow != null ? sender.slow : 0);
  pcSet("#pcErrors", sender.errors != null ? sender.errors : 0);
  pcSet("#pcDecode", dev.decode_ms != null ? `${dev.decode_ms} ms` : null);
  pcSet("#pcBlit", dev.blit_ms != null ? `${dev.blit_ms} ms` : null);
  pcSet("#pcDropped", dev.dropped != null ? dev.dropped : 0);
  pcSet("#pcPid", dev.pid || (dev.adb ? "not running" : "no ADB"));
  pcSet("#pcHold", dev.flags ? (dev.flags.fb_hold ? "on" : "off") : null);
  pcSet("#pcOverride", dev.flags ? (dev.flags.fb_override ? "on" : "off") : null);

  const log = $("#pcLog");
  if (log && dev.log) log.textContent = dev.log;
  if (log && !dev.log) log.textContent = "No receiver log yet.";

  if ($("#pcStart")) $("#pcStart").disabled = running;
  if ($("#pcStop")) $("#pcStop").disabled = !running;

  const hint = $("#pcHint");
  if (hint) {
    if (!dev.adb) {
      hint.textContent = "Enable ADB on Connection first, then press Start.";
    } else if (!dev.hook) {
      hint.textContent = "Install the “Frame injection (PC stream)” mod on Mods & UI, then restart the UI.";
    } else if (running) {
      hint.textContent = "Streaming. The goggles may look a beat behind — that is the software decoder, not the link.";
    } else if (sender.last_error) {
      hint.textContent = `Last error: ${sender.last_error}`;
    } else {
      hint.textContent = "Idle. Start the root shell and enable ADB on Connection, then press Start.";
    }
  }
  if ($("#pcStart")) $("#pcStart").disabled = running || !dev.adb || !dev.hook;
}

function renderPcSizes(sizes, current) {
  const sel = $("#pcSizeSel");
  if (!sel) return;
  const list = Array.isArray(sizes) && sizes.length ? sizes : ["1280x720"];
  setHTML(sel, list.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join(""));
  sel.value = list.includes(current) ? current : list[0];
}

async function refreshPcStream(manual = false) {
  if (!state.backend) return;
  const res = await call("pcstream_info", [], { label: "PC stream", quiet: true, refresh: false });
  if (!isOk(res)) return;
  state.pc = res;
  renderPcSizes(res.sizes, res.settings && res.settings.size);
  renderPcStream();
  if (manual) toast("Stream status refreshed", "info", "PC stream");
}

function startPcStream() {
  if (!state.backend) return;
  clearInterval(state.timers.pc);
  refreshPcStream();
  state.timers.pc = setInterval(refreshPcStream, 2000);
}

async function pcToggle(start) {
  if (!state.backend) return;
  const res = start
    ? await call("pcstream_start",
        [$("#pcSizeSel").value, Number($("#pcFpsSel").value), Number($("#pcQualitySel").value)],
        { label: "Start PC stream", key: "pc_start" })
    : await call("pcstream_stop", [], { label: "Stop PC stream", key: "pc_stop" });
  if (res) toast(res.message || (start ? "Stream started" : "Stream stopped"),
                 res.ok === false ? "error" : "success", "PC stream");
  refreshPcStream();
}

async function pcSave() {
  if (!state.backend) return;
  const res = await call("pcstream_set",
    [$("#pcSizeSel").value, Number($("#pcFpsSel").value), Number($("#pcQualitySel").value)],
    { label: "Stream settings" });
  if (isOk(res)) toast("Stream settings saved", "success", "PC stream");
  refreshPcStream();
}

/* ==========================================================================
   Connection actions
   ========================================================================== */
async function runAction(id) {
  const a = ACTIONS[id];
  if (!a) return;
  if (a.risk !== "SAFE") {
    const ok = await confirmRisk({ title: `${a.label}?`, risk: a.risk, body: a.confirm, confirmLabel: a.label });
    if (!ok) return;
  }
  await call(id, [], { label: a.label });
}

function renderActionTiles() {
  const grid = $("#actionsGrid");
  grid.innerHTML = Object.entries(ACTIONS).map(([id, a]) => {
    const tone = { SAFE: "", EXPERIMENTAL: "btn-warn", RISKY: "btn-danger" }[a.risk];
    return `
      <article class="card lift action" data-risk="${a.risk}">
        <div class="action-head"><span class="tile-icon">${icon(a.icon)}</span>${badge(a.risk)}</div>
        <h3>${esc(a.label)}</h3>
        <p>${esc(a.desc)}</p>
        <button class="btn btn-sm ${tone}" data-action="${id}">${icon(a.icon)}${esc(a.label)}</button>
      </article>`;
  }).join("");
}

function renderSafetyKeys() {
  const risks = Object.keys(RISK_INFO);
  $$('[data-safety-key="cards"]').forEach((el) => {
    el.innerHTML = risks.map((r) => `
      <article class="card lift legend" data-risk="${r}">
        ${badge(r)}
        <p>${esc(RISK_INFO[r].text)}</p>
        <div class="legend-examples">${esc(RISK_INFO[r].examples)}</div>
      </article>`).join("");
  });
  $$('[data-safety-key="list"]').forEach((el) => {
    el.innerHTML = risks.map((r) => `
      <div class="safety-row">${badge(r)}<p>${esc(RISK_INFO[r].text)}</p></div>`).join("");
  });
}

/* ==========================================================================
   E420Z live preview
   ========================================================================== */
function renderScaleOptions() {
  $("#scaleGrid").innerHTML = LIVE_SCALES.map((o) => `
    <button class="scale-opt" role="radio" aria-checked="false" data-scale="${esc(o.value)}">
      <span class="mono">${esc(o.name)}</span>${o.hint ? `<span class="hint">${esc(o.hint)}</span>` : ""}
    </button>`).join("");
  $("#scaleSelect").innerHTML = LIVE_SCALES.map((o) =>
    `<option value="${esc(o.value)}">${esc(o.name)}${o.hint ? ` · ${esc(o.hint)}` : ""}</option>`).join("");
}

function renderLiveControls() {
  const { running, scale } = state.live;
  if (!state.busy.has("live_start")) $("#liveStart").disabled = running;
  if (!state.busy.has("live_stop")) $("#liveStop").disabled = !running;
  $$("#scaleGrid .scale-opt").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.scale === scale));
    b.disabled = running;
  });
  const chip = $("#chipLive");
  setOn(chip, running);
  chip.lastElementChild.textContent = running ? "LIVE" : "OFF";
}

function setStage(name) {
  const stage = $("#stage");
  if (stage.dataset.state === name) return;
  stage.dataset.state = name;
  const [title, text] = STAGE_COPY[name];
  if (title) {
    $("#stageTitle").textContent = title;
    $("#stageText").textContent = text;
  }
}

async function startLive() {
  if (state.live.running || state.busy.has("live_start")) return;
  const scale = state.live.scale;
  const ok = await confirmRisk({
    title: "Start live preview?",
    risk: "EXPERIMENTAL",
    body: `Streams the goggles display at ${scale}. Starting live restarts the goggles UI — the headset screen blanks for a few seconds.`,
    confirmLabel: "Start live",
  });
  if (!ok) return;
  setStage("loading");
  const res = await call("live_start", [scale], { label: "Start live" });
  if (isOk(res)) {
    Object.assign(state.live, { running: true, frames: 0, misses: 0, failures: 0 });
    $("#chipFrames").textContent = "0 frames";
    frameLoop();
  } else {
    setStage("idle");
  }
  renderLiveControls();
}

async function stopLive() {
  const res = await call("live_stop", [], { label: "Stop live" });
  if (isOk(res)) {
    state.live.running = false;
    clearTimeout(state.live.timer);
    setStage(linkState(state.status || {}).root ? "idle" : "offline");
    $("#chipFps").textContent = "— fps";
  }
  renderLiveControls();
}

function frameLoop() {
  clearTimeout(state.live.timer);
  if (!state.live.running || state.page !== "live") return;
  pullFrame().finally(() => {
    if (state.live.running && state.page === "live") state.live.timer = setTimeout(frameLoop, FRAME_INTERVAL);
  });
}

async function pullFrame() {
  const live = state.live;
  try {
    const f = await invoke("live_frame");
    live.failures = 0;
    if (isOk(f) && f.image) {
      live.misses = 0;
      await showFrame(f);
    } else if (++live.misses === 30) {
      setStage(live.frames ? "error" : "waiting");
    }
  } catch (err) {
    if (++live.failures === 8) {
      toast(errorText(err), "error", "Live preview");
      setStage("error");
    }
  }
}

async function showFrame(f) {
  const [a, b] = $$(".stage-frame");
  const back = a.classList.contains("is-front") ? b : a;
  const front = back === a ? b : a;
  back.src = f.image;
  try { await back.decode(); } catch { return; }
  if (!state.live.running) return;
  back.classList.add("is-front");
  back.alt = "Live goggles display";
  front.classList.remove("is-front");
  front.alt = "";
  state.live.frames += 1;
  setStage("live");
  $("#chipRes").textContent = f.width && f.height ? `${f.width}${X}${f.height}` : state.live.scale;
  $("#chipFps").textContent = `${Math.round(Number(f.fps) || 0)} fps`;
  $("#chipFrames").textContent = `${state.live.frames.toLocaleString()} frames`;
}

async function captureScreen() {
  const res = await call("capture_screen", [], { label: "Screenshot" });
  if (!isOk(res) || !res.image) return;
  state.live.lastShot = { image: res.image, path: res.path || "", time: stamp() };
  const img = $("#shotImg");
  img.src = res.image;
  img.alt = "Last goggles screenshot";
  img.hidden = false;
  restartAnimation(img, "swap");
  $("#shotEmpty").hidden = true;
  $("#shotThumb").disabled = false;
  $("#shotMeta").textContent = res.path ? `${res.path} · ${state.live.lastShot.time}` : `Captured ${state.live.lastShot.time}`;
  openShotModal();
}

function openShotModal() {
  const shot = state.live.lastShot;
  if (!shot) return;
  const wrap = document.createElement("div");
  wrap.className = "modal-shot";
  wrap.innerHTML = `
    <img src="${esc(shot.image)}" alt="Goggles screenshot">
    <div class="shot-caption">
      <span class="mono">${esc(shot.path || "Not saved to disk")}</span>
      <span>${esc(shot.time)}</span>
      ${shot.path ? `<button class="btn btn-sm" data-copy="${esc(shot.path)}">${icon("copy")}Copy path</button>` : ""}
    </div>`;
  openModal({ title: "Screenshot", body: wrap, wide: true, info: true, confirmLabel: "Done", iconName: "image" });
}

/* ==========================================================================
   Sparrow2
   ========================================================================== */
async function runSparrow(method) {
  const def = SPARROW[method];
  if (!def || state.busy.has(method)) return;
  const out = $("#sparrowOut");
  out.innerHTML = `<span class="skeleton" style="--w:60%"></span>\n<span class="skeleton" style="--w:42%"></span>\n<span class="skeleton" style="--w:52%"></span>`;
  const res = await call(method, [], { label: def.label, quiet: true, refresh: false });
  if (!res) {
    out.textContent = "Request failed. See the WEB log for details.";
    state.sparrowText = "";
    return;
  }
  const text = res.ok === false ? (res.message || "The backend refused the request.") : (def.format(res) || "(empty response)");
  state.sparrowText = text;
  out.textContent = text;
  restartAnimation(out);
  $("#sparrowSource").textContent = `${def.label} · ${stamp()}`;
  if (res.ok !== false) toast(`${def.label} loaded`, "success", "Sparrow2");
}

/* ==========================================================================
   Sparrow2 — S2 receiver capture
   ========================================================================== */
const S2_ACTIONS = {
  probe: { method: "s2_probe", label: "S2 probe", confirm: null,
    desc: "Read-only inventory of the S2 decoder, record tools, USB ids and wlm config." },
  capture: { method: "s2_capture", label: "Capture S2 video",
    confirm: "The vendor decoder opens the S2 USB video endpoints and writes the encoded stream to /data/local/tmp/s2cap. This is receive-only: the link is not started and nothing outside /data is written. Continue?",
    desc: "Dump the encoded H.265 liveview for a few seconds." },
  pull: { method: "s2_pull", label: "Pull capture", confirm: null,
    desc: "Copy the newest capture to the PC byte-for-byte." },
  stop: { method: "s2_stop", label: "Stop decoder", confirm: null,
    desc: "Kill the decoder process if it is still running." },
};

function s2Output(text, source) {
  const out = $("#sparrowOut");
  state.sparrowText = text;
  out.textContent = text;
  restartAnimation(out);
  $("#sparrowSource").textContent = `${source} · ${stamp()}`;
}

function renderS2Files(files) {
  const box = $("#s2Files");
  if (!box) return;
  if (!Array.isArray(files) || !files.length) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  box.innerHTML = files.slice(0, 8).map((f) => `
    <button data-s2file="${esc(f.name)}" title="Pull ${esc(f.name)}">${esc(f.name)} · ${fmtBytes(f.size)}</button>`).join("");
}

async function runS2(kind, name) {
  const def = S2_ACTIONS[kind];
  if (!def || state.busy.has(def.method)) return;
  if (def.confirm) {
    const ok = await confirmRisk({
      title: def.label + "?",
      risk: "EXPERIMENTAL",
      body: def.confirm,
      confirmLabel: "Continue",
    });
    if (!ok) return;
  }
  s2Output(`${def.label}…`, def.label);
  let args = [];
  if (kind === "capture") args = [$("#s2Iface").value, Number($("#s2Seconds").value)];
  if (kind === "pull") args = [name || ""];
  const res = await call(def.method, args, { label: def.label, quiet: true, refresh: false });
  if (!res) { s2Output("Request failed. See the WEB log for details.", def.label); return; }

  if (kind === "pull" && res.path) {
    s2Output(`${res.message}\nsaved: ${res.path}\nsize:  ${res.size} bytes\nhead:  ${res.head}`, def.label);
  } else if (res.text) {
    s2Output(res.text, def.label);
  } else {
    s2Output(res.message || "(no output)", def.label);
  }
  if (res.files) renderS2Files(res.files);
  if (kind === "stop") renderS2Files([]);
}

/* ==========================================================================
   Root shell
   ========================================================================== */
function renderQuickCommands() {
  $("#quickList").innerHTML = QUICK_COMMANDS.map(([cmd, hint]) => `
    <button class="quick" data-quick="${esc(cmd)}"><span class="mono">${esc(cmd)}</span><span class="hint">${esc(hint)}</span></button>`).join("");
}

function renderHistory() {
  const items = state.shellHistory.slice(-12).reverse();
  $("#historyList").innerHTML = items.length
    ? items.map((c) => `<button class="history-item" data-quick="${esc(c)}" title="${esc(c)}">${esc(c)}</button>`).join("")
    : `<div class="history-empty">Commands you run appear here.</div>`;
}

function shellWelcome() {
  const out = $("#shellOut");
  out.innerHTML = "";
  appendShell("N3 ROOT shell bridge — commands run as uid 0 on the goggles.", "note");
  appendShell("Blocked by the backend: /system writes, dm-verity, partitions, bootloader.", "note");
  appendShell("Pick a quick command or type your own. Nothing runs until you press Run.", "note");
}

function appendShell(text, kind = "out") {
  const out = $("#shellOut");
  const line = document.createElement("div");
  line.className = `term-line ${kind}`;
  line.textContent = text;
  out.append(line);
  out.scrollTop = out.scrollHeight;
  return line;
}

function insertCommand(cmd) {
  const input = $("#shellInput");
  input.value = cmd;
  input.focus();
  input.setSelectionRange(cmd.length, cmd.length);
}

async function runShell(cmd) {
  if (!cmd || state.busy.has("run_shell")) return;
  if (!state.shellAcknowledged) {
    const ok = await confirmRisk({
      title: "Run commands as root?",
      risk: "RISKY",
      body: "Commands run as uid 0 on the goggles. The backend blocks /system, dm-verity, partition and bootloader operations; anything else runs exactly as typed. You will not be asked again this session.",
      confirmLabel: "I understand, run",
    });
    if (!ok) return;
    state.shellAcknowledged = true;
  }
  if (state.shellHistory[state.shellHistory.length - 1] !== cmd) state.shellHistory.push(cmd);
  state.historyIndex = -1;
  renderHistory();
  $("#shellInput").value = "";

  appendShell(cmd, "cmd");
  const pending = appendShell("running…", "pending");
  const res = await call("run_shell", [cmd], { label: "Root shell", quiet: true });
  pending.remove();
  if (!res) { appendShell("Request failed — see the WEB log.", "err"); return; }
  if (res.ok === false) appendShell(res.message || "Command failed", "err");
  const output = String(res.output ?? "").replace(/\s+$/, "");
  if (output) appendShell(output, "out");
  else if (res.ok !== false) appendShell("(no output)", "note");
  $("#shellInput").focus();
}

function onShellKey(e) {
  const h = state.shellHistory;
  const input = e.currentTarget;
  if (e.key === "ArrowUp" && h.length) {
    e.preventDefault();
    state.historyIndex = state.historyIndex === -1 ? h.length - 1 : Math.max(0, state.historyIndex - 1);
    input.value = h[state.historyIndex];
  } else if (e.key === "ArrowDown" && state.historyIndex !== -1) {
    e.preventDefault();
    state.historyIndex += 1;
    if (state.historyIndex >= h.length) state.historyIndex = -1;
    input.value = state.historyIndex === -1 ? "" : h[state.historyIndex];
  } else {
    return;
  }
  requestAnimationFrame(() => input.setSelectionRange(input.value.length, input.value.length));
}

/* ==========================================================================
   Mods
   ========================================================================== */
async function loadMods(manual = false) {
  if (state.busy.has("mods_list")) return;
  if (!state.mods) renderModsSkeleton();
  const res = await call("mods_list", [], { label: "Mods", quiet: true, refresh: false });
  if (res && Array.isArray(res.mods)) {
    state.mods = res.mods;
    state.modsError = "";
    if (manual) toast(`${res.mods.length} mods loaded`, "success", "Mods");
  } else {
    state.modsError = res ? (res.message || "The backend returned no mod list.") : "Could not reach the backend.";
    if (!state.mods) state.mods = [];
  }
  renderMods();
}

function renderModsSkeleton() {
  const grid = $("#modsGrid");
  grid.hidden = false;
  $("#modsEmpty").hidden = true;
  grid.innerHTML = Array.from({ length: 3 }, () => `
    <div class="card skeleton-card">
      <span class="skeleton"></span><span class="skeleton" style="--w:55%"></span>
      <span class="skeleton" style="--w:90%"></span><span class="skeleton" style="--w:70%"></span>
    </div>`).join("");
  stagger(grid);
}

function renderMods() {
  const mods = state.mods || [];
  const installed = mods.filter((m) => m.installed).length;
  const grid = $("#modsGrid");
  $("#modsSummary").innerHTML = `<strong>${mods.length}</strong> mods · <strong>${installed}</strong> installed`;
  countUp($("#mMods"), installed);

  const empty = mods.length === 0;
  grid.hidden = empty;
  $("#modsEmpty").hidden = !empty;
  if (empty) {
    $("#modsEmptyTitle").textContent = state.modsError ? "Mods unavailable" : "No mods found";
    $("#modsEmptyText").textContent = state.modsError || "The backend reported an empty mod list. Connect the goggles and refresh.";
    return;
  }
  grid.innerHTML = mods.map(modCard).join("");
  stagger(grid);
}

function modCard(mod) {
  const id = String(mod.id);
  const risk = normRisk(mod);
  const key = `mod:${id}`;
  const busy = state.busy.has(key);
  const typeIcon = { service: "cpu", stream: "goggles", capture: "camera", ui: "sparkle", theme: "palette" }[String(mod.type).toLowerCase()] || "layers";
  const op = mod.installed ? "uninstall" : "install";
  const btnClass = mod.installed ? "" : "btn-primary";
  return `
    <article class="card lift mod" data-risk="${risk}">
      <header class="mod-head">
        <span class="tile-icon">${icon(typeIcon)}</span>
        <div class="mod-title">
          <h3 title="${esc(mod.name)}">${esc(mod.name || id)}</h3>
          <div class="mod-meta"><span class="mono">v${esc(String(mod.version || "?").replace(/^v/i, ""))}</span><span>·</span><span>${esc(mod.type || "mod")}</span></div>
        </div>
        ${badge(risk)}
      </header>
      <p class="mod-desc">${esc(mod.description || "No description provided.")}</p>
      ${mod.notes ? `<div class="mod-notes">${icon("info")}<span>${esc(mod.notes)}</span></div>` : ""}
      <footer class="mod-foot">
        <span class="state-tag" data-on="${Boolean(mod.installed)}"><span class="dot" data-on="${Boolean(mod.installed)}"></span>${mod.installed ? "Installed" : "Not installed"}</span>
        <button class="btn btn-sm ${btnClass}${busy ? " is-busy" : ""}" data-mod="${esc(id)}" data-op="${op}" data-busy-key="${esc(key)}"${busy ? " disabled" : ""}>
          ${icon(mod.installed ? "trash" : "arrow-down")}${mod.installed ? "Uninstall" : "Install"}
        </button>
      </footer>
    </article>`;
}

async function toggleMod(id, op) {
  const mod = (state.mods || []).find((m) => String(m.id) === id);
  if (!mod) return;
  const risk = normRisk(mod);
  const verb = op === "install" ? "Install" : "Uninstall";
  if (risk !== "SAFE" || mod.experimental) {
    const ok = await confirmRisk({
      title: `${verb} ${mod.name}?`,
      risk: risk === "SAFE" ? "EXPERIMENTAL" : risk,
      body: mod.notes || mod.description || `${verb} this mod on the goggles.`,
      confirmLabel: verb,
    });
    if (!ok) return;
  }
  const res = await call(op === "install" ? "install_mod" : "uninstall_mod", [mod.id], { key: `mod:${id}`, label: `${verb} ${mod.name}` });
  if (isOk(res)) loadMods();
}

/* ==========================================================================
   Logs
   ========================================================================== */
function startLogs() {
  clearInterval(state.timers.logs);
  pollLogs();
  state.timers.logs = setInterval(pollLogs, LOG_INTERVAL);
}

async function pollLogs() {
  if (!state.backend || state.inFlight.logs) return;
  state.inFlight.logs = true;
  try {
    state.logs = (await invoke("logs")) || {};
    state.logsError = "";
  } catch (err) {
    state.logsError = errorText(err);
  } finally {
    state.inFlight.logs = false;
    state.logsUpdated = new Date();
    renderLogs();
  }
}

function logLines(tab) {
  let raw;
  if (tab === "web") {
    // The session log includes the failures that never reach the backend, and
    // the host log carries Python-side notes, so show both.
    raw = state.webLog.join("\n");
    const host = String(state.logs.web || "").trim();
    if (host) raw += `\n--- python host ---\n${host}`;
  } else {
    raw = String(state.logs[tab] || "");
  }
  const lines = raw.split(/\r?\n/).filter((l) => l.length);
  const marker = state.logCleared[tab];
  if (!marker) return lines;
  const at = lines.lastIndexOf(marker);
  return at >= 0 ? lines.slice(at + 1) : lines;
}

function logLevel(line) {
  if (/\s[EF]\s|\b[EF]\/|\berror\b|\bfail(ed|ure)?\b|✗/i.test(line)) return "is-err";
  if (/\sW\s|\bW\/|\bwarn(ing)?\b/i.test(line)) return "is-warn";
  return "";
}

function highlight(line, q) {
  if (!q) return esc(line);
  const low = line.toLowerCase();
  let out = "";
  let i = 0;
  let at;
  while ((at = low.indexOf(q, i)) !== -1) {
    out += `${esc(line.slice(i, at))}<mark>${esc(line.slice(at, at + q.length))}</mark>`;
    i = at + q.length;
  }
  return out + esc(line.slice(i));
}

function renderLogs(force = false) {
  const tab = state.logTab;
  const q = $("#logFilter").value.trim().toLowerCase();
  const all = logLines(tab).slice(-LOG_LINE_LIMIT);
  const lines = q ? all.filter((l) => l.toLowerCase().includes(q)) : all;
  const offline = Boolean(state.logsError) && tab !== "web";

  $("#logCount").textContent = q ? `${lines.length} of ${all.length} lines` : `${all.length} lines`;
  $("#logUpdated").textContent = state.logsUpdated ? `Updated ${stamp(state.logsUpdated)}` : "Not updated yet";
  setOn($("#logDot"), !state.logsError && Boolean(state.logsUpdated));

  const key = `${tab}|${q}|${offline}|${lines.length}|${lines[lines.length - 1] || ""}`;
  const out = $("#logOut");
  if (!force && out._key === key) return;
  out._key = key;

  const empty = offline || lines.length === 0;
  $("#logEmpty").hidden = !empty;
  if (empty) {
    let title = "No log output yet";
    let text = "Lines appear here as soon as the backend reports them.";
    if (offline) { title = "Logs unavailable"; text = state.logsError; }
    else if (q) { title = "No matching lines"; text = `Nothing in ${tab.toUpperCase()} matches “${q}”.`; }
    else if (state.logCleared[tab]) { title = "View cleared"; text = "New lines will appear here. Clearing never touches the device."; }
    $("#logEmptyTitle").textContent = title;
    $("#logEmptyText").textContent = text;
  }
  out.innerHTML = lines.map((l) => `<div class="log-line ${logLevel(l)}">${highlight(l, q)}</div>`).join("");
  if (state.autoScroll) out.scrollTop = out.scrollHeight;
}

function selectLogTab(tab, focus = false) {
  state.logTab = tab;
  $$("#logTabs .tab").forEach((t) => {
    const on = t.dataset.log === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    if (on && focus) t.focus();
  });
  renderLogs(true);
}

function onLogTabKey(e) {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const tabs = $$("#logTabs .tab");
  const i = tabs.findIndex((t) => t.dataset.log === state.logTab);
  const next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
  e.preventDefault();
  selectLogTab(next.dataset.log, true);
}

function clearLogView() {
  const lines = logLines(state.logTab);
  if (!lines.length) return;
  state.logCleared[state.logTab] = lines[lines.length - 1];
  renderLogs(true);
  toast(`${state.logTab.toUpperCase()} view cleared (device logs untouched)`, "info");
}

function toggleAutoScroll() {
  state.autoScroll = !state.autoScroll;
  $("#autoScroll").setAttribute("aria-pressed", String(state.autoScroll));
  if (state.autoScroll) { const out = $("#logOut"); out.scrollTop = out.scrollHeight; }
}

/* ==========================================================================
   Settings
   ========================================================================== */
async function loadPrefs() {
  try {
    const p = await invoke("prefs");
    if (p && typeof p === "object") Object.assign(state.prefs, p);
  } catch (err) {
    logWeb(`✗ prefs — ${errorText(err)}`);
  }
  applyPrefs();
}

/** Loads the live-preview scale labels from the backend. */
async function loadResolutions() {
  try {
    const res = await invoke("live_resolutions");
    if (setResolutions(res && res.resolutions)) {
      if (!state.live.running && !state.live.userScale) state.live.scale = normScale(state.prefs.live_scale);
      applyPrefs();
    }
  } catch (err) {
    logWeb(`✗ live_resolutions — ${errorText(err)}`);
  }
}

function applyPrefs() {
  const p = state.prefs;
  const root = document.documentElement;
  root.dataset.accent = ACCENTS.includes(p.accent) ? p.accent : "purple";
  root.dataset.density = p.density === "compact" ? "compact" : "comfortable";
  root.classList.toggle("reduce-motion", p.motion === false || FORCE_REDUCE);

  $$("#accentGroup .swatch").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.accent === root.dataset.accent)));
  $("#motionSwitch").setAttribute("aria-checked", String(p.motion !== false));
  $$("#densityGroup [role=radio]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.density === root.dataset.density)));
  $("#scaleSelect").value = normScale(p.live_scale);
  if (!state.live.running && !state.live.userScale) state.live.scale = normScale(p.live_scale);
  renderLiveControls();
  requestAnimationFrame(() => moveIndicator(true));
}

async function setPref(key, value) {
  if (state.prefs[key] === value) return;
  state.prefs[key] = value;
  applyPrefs();
  const res = await call("set_pref", [key, value], { key: `pref:${key}`, label: "Preferences", quiet: true, refresh: false });
  if (isOk(res)) {
    const shown = typeof value === "boolean" ? (value ? "on" : "off") : cap(String(value).replace("_", " "));
    toast(`${PREF_NAMES[key]} set to ${shown}`, "success", "Saved");
  }
}

async function loadThemes(manual = false) {
  if (state.busy.has("themes")) return;
  const res = await call("themes", [], { label: "Themes", quiet: true, refresh: false });
  if (res && Array.isArray(res.themes)) {
    state.themes = res.themes;
    if (manual) toast(`${res.themes.length} themes available`, "success", "Themes");
  }
  renderThemes();
}

function renderThemes() {
  const active = normTheme(state.status && state.status.theme);
  const list = state.themes;
  if (!list.includes(state.selectedTheme)) state.selectedTheme = list.find((t) => normTheme(t) === active) || list[0] || null;

  setHTML($("#themeList"), list.length ? list.map((t) => {
    const isActive = normTheme(t) === active;
    return `
      <button class="theme-opt" role="radio" aria-checked="${t === state.selectedTheme}" data-theme="${esc(t)}">
        <span class="theme-swatch" style="--sw:${THEME_SWATCH[normTheme(t)] || "var(--accent)"}"></span>
        <span class="theme-name">${esc(t)}</span>
        ${isActive ? `<span class="tag">Active</span>` : ""}
        <span class="radio-dot"></span>
      </button>`;
  }).join("") : `<div class="hint">No themes reported by the backend.</div>`);

  if (!state.busy.has("apply_theme")) {
    $("#themeApply").disabled = !state.selectedTheme || normTheme(state.selectedTheme) === active;
  }
}

async function applyTheme() {
  const name = state.selectedTheme;
  if (!name) return;
  const ok = await confirmRisk({
    title: `Apply “${name}” theme?`,
    risk: "EXPERIMENTAL",
    body: "Theme assets are written to /vendor and the goggles UI restarts to load them. The headset screen blanks for a few seconds.",
    confirmLabel: "Apply and restart UI",
  });
  if (!ok) return;
  await call("apply_theme", [name], { label: "Theme" });
}

/* ==========================================================================
   Toasts
   ========================================================================== */
function toast(message, kind = "info", title = "") {
  const wrap = $("#toasts");
  const duration = kind === "error" ? 6500 : 4000;
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.style.setProperty("--dur", `${duration}ms`);
  el.innerHTML = `
    <span class="toast-icon">${icon(kind === "error" ? "alert" : kind === "success" ? "check" : "info")}</span>
    <div class="toast-text">${title ? `<strong>${esc(title)}</strong>` : ""}<span>${esc(message)}</span></div>
    <button class="toast-close" aria-label="Dismiss notification">${icon("x")}</button>
    <span class="toast-timer"></span>`;
  $(".toast-close", el).addEventListener("click", () => dismissToast(el));
  el.addEventListener("mouseenter", () => clearTimeout(el._timer));
  el.addEventListener("mouseleave", () => { el._timer = setTimeout(() => dismissToast(el), 1800); });
  wrap.append(el);
  const live = $$(".toast:not(.is-leaving)", wrap);
  if (live.length > 4) dismissToast(live[0]);
  el._timer = setTimeout(() => dismissToast(el), duration);
}

function dismissToast(el) {
  if (!el || el.classList.contains("is-leaving")) return;
  clearTimeout(el._timer);
  el.classList.add("is-leaving");
  const remove = () => el.remove();
  el.addEventListener("animationend", remove, { once: true });
  setTimeout(remove, 400);
}

/* ==========================================================================
   Overlays: modal + command palette
   ========================================================================== */
const isOpen = (sel) => $(sel).classList.contains("is-open");

function openOverlay(el) {
  el.classList.add("is-open");
  el.setAttribute("aria-hidden", "false");
}

function closeOverlay(el) {
  el.classList.remove("is-open");
  el.setAttribute("aria-hidden", "true");
}

function trapFocus(e, root) {
  const items = $$('button:not([disabled]), [href], input:not([disabled]), select, [tabindex]:not([tabindex="-1"])', root)
    .filter((el) => el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (!root.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/* ---------- Modal ---------- */
const modal = { resolve: null, returnFocus: null };

function openModal({ title, body, risk = "", confirmLabel = "Confirm", cancelLabel = "Cancel", wide = false, info = false, iconName = "" }) {
  if (modal.resolve) closeModal(false);
  const box = $("#modal");
  box.dataset.risk = risk;
  box.classList.toggle("is-wide", wide);
  $("#modalIcon").innerHTML = icon(iconName || (risk === "RISKY" || risk === "EXPERIMENTAL" ? "alert" : "info"));
  $("#modalTitle").textContent = title;
  const b = $("#modalBadge");
  b.hidden = !risk;
  if (risk) { b.dataset.risk = risk; b.textContent = RISK_INFO[risk].label; }
  const bodyEl = $("#modalBody");
  bodyEl.replaceChildren();
  if (typeof body === "string") { const p = document.createElement("p"); p.textContent = body; bodyEl.append(p); }
  else if (body) bodyEl.append(body);
  $("#modalConfirm").textContent = confirmLabel;
  $("#modalCancel").textContent = cancelLabel;
  $("#modalCancel").hidden = info;

  modal.returnFocus = document.activeElement;
  openOverlay($("#modalOverlay"));
  // Risky prompts default focus to Cancel so Enter never confirms by accident.
  requestAnimationFrame(() => (info || !risk || risk === "SAFE" ? $("#modalConfirm") : $("#modalCancel")).focus());
  return new Promise((resolve) => { modal.resolve = resolve; });
}

function closeModal(result) {
  if (!modal.resolve) return;
  const resolve = modal.resolve;
  modal.resolve = null;
  closeOverlay($("#modalOverlay"));
  if (modal.returnFocus && document.contains(modal.returnFocus)) modal.returnFocus.focus({ preventScroll: true });
  resolve(result);
}

function confirmRisk({ title, risk, body, confirmLabel }) {
  const node = document.createElement("div");
  node.innerHTML = `
    <p>${esc(body)}</p>
    <div class="risk-note" data-risk="${risk}">${icon(risk === "RISKY" ? "alert" : "info")}
      <span><strong>${RISK_INFO[risk].label}.</strong> ${esc(RISK_INFO[risk].text)}</span>
    </div>`;
  return openModal({ title, risk, body: node, confirmLabel });
}

/* ---------- Command palette ---------- */
const palette = { items: [], results: [], active: 0, returnFocus: null };

function paletteItems() {
  const pages = PAGES.map((p, i) => ({
    group: "Pages", label: p.title, hint: p.subtitle, icon: p.icon, kbd: `Alt ${i + 1}`, run: () => go(p.id),
  }));
  const actions = Object.entries(ACTIONS).map(([id, a]) => ({
    group: "Device actions", label: a.label, hint: a.desc, icon: a.icon, risk: a.risk, run: () => runAction(id),
  }));
  const live = [
    { label: "Start live preview", hint: "E420Z · restarts the goggles UI", icon: "play", risk: "EXPERIMENTAL", run: () => { go("live"); startLive(); } },
    { label: "Stop live preview", hint: "E420Z", icon: "stop", run: () => { go("live"); stopLive(); } },
    { label: "Capture screenshot", hint: "E420Z · saved on the goggles", icon: "camera", run: () => { go("live"); captureScreen(); } },
    { label: "Refresh status", hint: "Poll USB, root and ADB now", icon: "refresh", kbd: "Ctrl R", run: () => refreshStatus({ manual: true }) },
    { label: "Refresh mods", hint: "Mods & UI", icon: "layers", run: () => { go("mods"); loadMods(true); } },
  ].map((it) => ({ group: "Tools", ...it }));
  const sparrow = Object.entries(SPARROW).map(([m, d]) => ({
    group: "Sparrow2", label: `Sparrow2 ${d.label.toLowerCase()}`, hint: "Read-only", icon: "radio", run: () => { go("sparrow"); runSparrow(m); },
  }));
  const prefs = [
    { label: state.prefs.motion === false ? "Turn motion on" : "Turn motion off", hint: "Animations and transitions", icon: "sparkle",
      run: () => setPref("motion", state.prefs.motion === false) },
    { label: state.prefs.density === "compact" ? "Comfortable density" : "Compact density", hint: "Spacing of cards and controls", icon: "sliders",
      run: () => setPref("density", state.prefs.density === "compact" ? "comfortable" : "compact") },
    ...ACCENTS.map((a) => ({ label: `Accent: ${cap(a)}`, hint: "Highlight colour", icon: "palette", run: () => setPref("accent", a) })),
  ].map((it) => ({ group: "Preferences", ...it }));
  return [...pages, ...actions, ...live, ...sparrow, ...prefs];
}

function fuzzyScore(q, text) {
  const t = text.toLowerCase();
  const idx = t.indexOf(q);
  if (idx >= 0) return 100 - idx + (idx === 0 || t[idx - 1] === " " ? 25 : 0);
  let score = 0;
  let from = 0;
  let streak = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, from);
    if (found < 0) return 0;
    streak = found === from ? streak + 1 : 0;
    score += 1 + streak * 2 + (found === 0 || t[found - 1] === " " ? 3 : 0);
    from = found + 1;
  }
  return score;
}

function scoreItem(item, q) {
  const label = fuzzyScore(q, item.label) * 2;
  const meta = `${item.group} ${item.hint || ""}`.toLowerCase().includes(q) ? 12 : 0;
  return Math.max(label, meta);
}

function openPalette() {
  if (isOpen("#modalOverlay")) return;
  palette.returnFocus = document.activeElement;
  palette.items = paletteItems();
  $("#paletteInput").value = "";
  renderPalette();
  openOverlay($("#paletteOverlay"));
  requestAnimationFrame(() => $("#paletteInput").focus());
}

function closePalette() {
  if (!isOpen("#paletteOverlay")) return;
  closeOverlay($("#paletteOverlay"));
  if (palette.returnFocus && document.contains(palette.returnFocus)) palette.returnFocus.focus({ preventScroll: true });
}

function renderPalette() {
  const q = $("#paletteInput").value.trim().toLowerCase();
  palette.results = q
    ? palette.items.map((it) => ({ it, s: scoreItem(it, q) })).filter((r) => r.s > 0).sort((a, b) => b.s - a.s).map((r) => r.it)
    : palette.items.slice();

  let html = "";
  let group = "";
  palette.results.forEach((it, i) => {
    if (!q && it.group !== group) {
      group = it.group;
      html += `<li class="palette-group" role="presentation">${esc(group)}</li>`;
    }
    html += `
      <li class="palette-item" role="option" id="pal-${i}" data-index="${i}" aria-selected="false">
        <span class="pi-icon">${icon(it.icon)}</span>
        <span class="pi-text"><span class="pi-label">${esc(it.label)}</span><span class="pi-hint">${esc(it.hint || "")}</span></span>
        ${it.risk ? badge(it.risk) : ""}
        ${q ? `<span class="pi-group">${esc(it.group)}</span>` : ""}
        ${it.kbd ? `<kbd>${esc(it.kbd)}</kbd>` : ""}
      </li>`;
  });
  $("#paletteList").innerHTML = html || `<li class="palette-empty" role="presentation">No matches for “${esc(q)}”</li>`;
  setPaletteActive(0);
}

function setPaletteActive(i, scroll = true) {
  const n = palette.results.length;
  if (!n) { $("#paletteInput").removeAttribute("aria-activedescendant"); return; }
  palette.active = (i + n) % n;
  $$("#paletteList .palette-item").forEach((el) => {
    const on = Number(el.dataset.index) === palette.active;
    el.setAttribute("aria-selected", String(on));
    if (on && scroll) el.scrollIntoView({ block: "nearest" });
  });
  $("#paletteInput").setAttribute("aria-activedescendant", `pal-${palette.active}`);
}

function runPaletteItem(i) {
  const item = palette.results[i];
  if (!item) return;
  closePalette();
  item.run();
}

function onPaletteKey(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); setPaletteActive(palette.active + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setPaletteActive(palette.active - 1); }
  else if (e.key === "Enter") { e.preventDefault(); runPaletteItem(palette.active); }
}

/* ==========================================================================
   Events
   ========================================================================== */
function onDocumentClick(e) {
  const t = e.target.closest("[data-action], [data-go], [data-mod], [data-sparrow], [data-quick], [data-copy], [data-theme], [data-doc], [data-s2], [data-s2file]");
  if (!t || t.disabled) return;
  const d = t.dataset;
  if (d.action) runAction(d.action);
  else if (d.go) go(d.go);
  else if (d.mod) toggleMod(d.mod, d.op);
  else if (d.sparrow) runSparrow(d.sparrow);
  else if (d.quick) insertCommand(d.quick);
  else if (d.copy) copyText(d.copy, "Path copied");
  else if (d.doc) openDoc(d.doc);
  else if (d.s2) runS2(d.s2);
  else if (d.s2file) runS2("pull", d.s2file);
  else if (d.theme) { state.selectedTheme = d.theme; renderThemes(); }
}

function onKeydown(e) {
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  const modalOpen = isOpen("#modalOverlay");
  const palOpen = isOpen("#paletteOverlay");

  if (e.key === "Tab" && (modalOpen || palOpen)) { trapFocus(e, modalOpen ? $("#modal") : $(".palette")); return; }
  if (e.key === "Escape") {
    if (modalOpen) closeModal(false);
    else if (palOpen) closePalette();
    return;
  }
  if (modalOpen) return;
  if (mod && key === "k") { e.preventDefault(); if (palOpen) closePalette(); else openPalette(); return; }
  if ((mod && key === "r") || e.key === "F5") { e.preventDefault(); refreshStatus({ manual: true }); return; }
  if (e.altKey && !mod && /^Digit[1-7]$/.test(e.code)) {
    e.preventDefault();
    closePalette();
    go(PAGES[Number(e.code.slice(5)) - 1].id);
  }
}

function bindEvents() {
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onKeydown);
  window.addEventListener("resize", () => moveIndicator(true));
  $("#main").addEventListener("scroll", (e) => $("#topbar").classList.toggle("is-scrolled", e.currentTarget.scrollTop > 4), { passive: true });

  $("#openPalette").addEventListener("click", openPalette);
  $("#refreshBtn").addEventListener("click", () => refreshStatus({ manual: true }));

  $("#paletteInput").addEventListener("input", renderPalette);
  $("#paletteInput").addEventListener("keydown", onPaletteKey);
  $("#paletteList").addEventListener("click", (e) => {
    const li = e.target.closest(".palette-item");
    if (li) runPaletteItem(Number(li.dataset.index));
  });
  $("#paletteList").addEventListener("mousemove", (e) => {
    const li = e.target.closest(".palette-item");
    if (li && Number(li.dataset.index) !== palette.active) setPaletteActive(Number(li.dataset.index), false);
  });
  $("#paletteOverlay").addEventListener("mousedown", (e) => { if (e.target === e.currentTarget) closePalette(); });

  $("#modalConfirm").addEventListener("click", () => closeModal(true));
  $("#modalCancel").addEventListener("click", () => closeModal(false));
  $("#modalOverlay").addEventListener("mousedown", (e) => { if (e.target === e.currentTarget) closeModal(false); });

  $("#liveStart").addEventListener("click", startLive);
  $("#liveStop").addEventListener("click", stopLive);
  $("#pcStart").addEventListener("click", () => pcToggle(true));
  $("#pcStop").addEventListener("click", () => pcToggle(false));
  $("#pcRefresh").addEventListener("click", () => refreshPcStream(true));
  $("#pcSave").addEventListener("click", pcSave);
  $("#pcCopyLog").addEventListener("click", () => copyText($("#pcLog").textContent, "Receiver log copied"));
  $("#shotBtn").addEventListener("click", captureScreen);
  $("#shotThumb").addEventListener("click", openShotModal);
  $("#scaleGrid").addEventListener("click", (e) => {
    const b = e.target.closest(".scale-opt");
    if (!b || b.disabled) return;
    state.live.scale = b.dataset.scale;
    state.live.userScale = true;
    renderLiveControls();
  });

  $("#sparrowCopy").addEventListener("click", () => copyText(state.sparrowText, "Output copied"));

  $("#shellForm").addEventListener("submit", (e) => { e.preventDefault(); runShell($("#shellInput").value.trim()); });
  $("#shellInput").addEventListener("keydown", onShellKey);
  $("#shellCopy").addEventListener("click", () => copyText($("#shellOut").innerText.trim(), "Shell output copied"));
  $("#shellClear").addEventListener("click", () => { $("#shellOut").innerHTML = ""; appendShell("Output cleared.", "note"); });

  $("#modsRefresh").addEventListener("click", () => loadMods(true));
  $("#modsEmptyRefresh").addEventListener("click", () => loadMods(true));

  $("#logTabs").addEventListener("click", (e) => { const t = e.target.closest(".tab"); if (t) selectLogTab(t.dataset.log); });
  $("#logTabs").addEventListener("keydown", onLogTabKey);
  $("#logFilter").addEventListener("input", () => renderLogs(true));
  $("#autoScroll").addEventListener("click", toggleAutoScroll);
  $("#logCopy").addEventListener("click", () => {
    const text = $$("#logOut .log-line").map((l) => l.textContent).join("\n");
    copyText(text, "Visible lines copied");
  });
  $("#logClear").addEventListener("click", clearLogView);

  $("#accentGroup").addEventListener("click", (e) => { const b = e.target.closest(".swatch"); if (b) setPref("accent", b.dataset.accent); });
  $("#motionSwitch").addEventListener("click", () => setPref("motion", state.prefs.motion === false));
  $("#densityGroup").addEventListener("click", (e) => { const b = e.target.closest("[data-density]"); if (b) setPref("density", b.dataset.density); });
  $("#scaleSelect").addEventListener("change", (e) => setPref("live_scale", e.target.value));
  $("#themeApply").addEventListener("click", applyTheme);
  $("#themeReload").addEventListener("click", () => loadThemes(true));
}

/* ==========================================================================
   Mock backend — deterministic, browser-only preview data
   ========================================================================== */
function createMock() {
  const mockPc = state.mockPc;
  const st = {
    version: "1.4.2-mock", ui: true, patched: true, root: true, adb: true,
    theme: "purple", background: true, menu: true, pid: "1287",
    transport: "USB", serial: "N3••••••7Q2K", device: "DJI Goggles N3",
  };
  const prefs = { accent: "purple", motion: true, density: "comfortable", live_scale: `640${X}360` };
  const mods = [
    { id: "capture", name: "Screen Capture", version: "0.3.1", type: "capture", risk: "safe", installed: true, experimental: false,
      description: "Grabs the goggles framebuffer for screenshots and the live preview.",
      notes: "Writes only to /data/local/tmp/n3cap. Removing it disables E420Z." },
    { id: "n3live", name: "N3 Live", version: "0.2.0", type: "stream", risk: "experimental", installed: true, experimental: true,
      description: "Low-latency JPEG stream of the goggles display over USB.",
      notes: "Starting a stream restarts the glasses UI." },
    { id: "n3menu", name: "N3 Menu Row", version: "1.0.4", type: "ui", risk: "risky", installed: false, experimental: true,
      description: "Adds a custom row to the stock goggles menu with shortcuts to N3 ROOT tools.",
      notes: "Patches UI assets in /vendor. Use Recover stock UI if the menu fails to draw." },
  ];
  const baseLogs = {
    natartos: [
      "I natartos: boot complete, uptime 00:00:41",
      "I natartos: usb gadget bound (dji_blackbox)",
      "I natartos: root shell listening on 127.0.0.1",
      "W natartos: verity: enforcing — /system is read-only by design",
      "I natartos: /vendor overlay mounted rw",
    ],
    n3mods: [
      "I n3mods: loading manifest /vendor/n3mods/manifest.json",
      "I n3mods: capture 0.3.1 installed",
      "I n3mods: n3live 0.2.0 installed (experimental)",
      "I n3mods: n3menu 1.0.4 available, not installed",
    ],
    ui: [
      "I dji_glasses: starting patched build",
      "I dji_glasses: theme=purple background=custom",
      "I dji_glasses: menu row registered (3 entries)",
      "W dji_glasses: frame pacing 16.9 ms over 16.6 ms budget",
      "I dji_glasses: display on, 1920x1080@60",
    ],
    capture: [
      "I capture: framebuffer /dev/graphics/fb0 1920x1080 rgba8888",
      "I capture: ready, output dir /data/local/tmp/n3cap",
    ],
  };
  const shell = {
    "id": "uid=0(root) gid=0(root) groups=0(root) context=u:r:su:s0",
    "uname -a": "Linux n3 4.9.118 #1 SMP PREEMPT armv7l GNU/Linux (mock)",
    "ps -A": "USER     PID  PPID  NAME\nroot       1     0  init\nroot     412     1  natartos\nroot     538     1  dji_blackbox\nroot    1287     1  dji_glasses_patched\nroot    1301  1287  n3live\nroot    1340   412  sh",
    "ls -la /vendor": "drwxr-xr-x root root   bin\ndrwxr-xr-x root root   etc\ndrwxr-xr-x root root   n3mods\n-rwxr-xr-x root root   dji_glasses_patched\ndrwxr-xr-x root root   lib",
    "mount": "/dev/root on / type ext4 (ro)\n/dev/block/system on /system type ext4 (ro)\n/dev/block/vendor on /vendor type ext4 (rw)\n/dev/block/userdata on /data type ext4 (rw)",
    "df -h": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/root       512M  498M   14M  98% /\n/dev/vendor     256M  141M  115M  55% /vendor\n/dev/userdata   2.0G  612M  1.4G  31% /data",
    "ls -la /data/local/tmp": "drwxrwx--x root root   n3cap\n-rw-r--r-- root root   n3live.sock\n-rw-r--r-- root root   web.log",
    "uptime": " 09:21:44 up 7 min,  load average: 0.42, 0.38, 0.21",
  };
  const blocked = /\/system\b|verity|\bdd\b|mkfs|fastboot|bootloader|\/dev\/block|flash_image/i;
  let tick = 0;
  let shots = 0;
  let live = null;
  let frame = 0;
  const ok = (message, extra = {}) => ({ ok: true, message: `${message} (mock)`, ...extra });
  const fail = (message, extra = {}) => ({ ok: false, message, ...extra });
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  const ts = (n) => {
    const t = 9 * 3600 + 14 * 60 + 41 + n * 3;
    return `11-26 ${pad(Math.floor(t / 3600) % 24)}:${pad(Math.floor(t / 60) % 60)}:${pad(t % 60)}.${pad((n * 137) % 1000, 3)}`;
  };
  /** Base lines plus the last `keep` entries of a growing series; timestamps stay stable per entry. */
  const logText = (name, count, keep, fmt) => {
    const base = baseLogs[name].map((l, i) => `${ts(i)}  ${l}`);
    const start = Math.max(0, count - keep);
    const series = Array.from({ length: count - start }, (_, k) => `${ts(base.length + start + k)}  ${fmt(start + k)}`);
    return base.concat(series).join("\n");
  };

  return {
    async status() { await sleep(90); return { ...st }; },
    async enable_adb() { await sleep(900); st.adb = true; return ok("ADB enabled, device re-enumerated"); },
    async start_root() { await sleep(1000); st.root = true; return ok("Root shell listening"); },
    async stop_root() { await sleep(500); st.root = false; live = null; return ok("Root shell stopped"); },
    async start_ui() {
      await sleep(1300);
      if (!st.root) return fail("Root shell is not running");
      st.ui = true; st.patched = true; st.pid = String(1287 + (tick += 7));
      return ok(`Patched UI started · pid ${st.pid}`);
    },
    async recover_stock() {
      await sleep(1400);
      Object.assign(st, { patched: false, theme: "stock", background: false, menu: false, pid: "912" });
      live = null;
      return ok("Stock UI restored");
    },
    async open_terminal() { await sleep(400); return ok("Terminal requested — no window opens in browser preview"); },
    async open_doc(path) { await sleep(120); return ok(`Would open ${path} in the desktop app`); },
    async run_shell(cmd) {
      await sleep(350);
      if (!st.root) return fail("Root shell is not running", { output: "" });
      if (blocked.test(cmd)) return fail("Blocked by backend policy: /system, verity, partitions and bootloader are off-limits", { output: "" });
      const out = shell[cmd.trim()] ?? `sh: ${cmd.split(/\s+/)[0]}: no canned output in mock mode`;
      return { ok: true, message: "", output: out };
    },
    async mods_list() { await sleep(380); return { mods: mods.map((m) => ({ ...m })) }; },
    async install_mod(id) {
      await sleep(1100);
      const m = mods.find((x) => x.id === id);
      if (!m) return fail(`Unknown mod ${id}`);
      m.installed = true;
      if (id === "n3menu") st.menu = true;
      return ok(`${m.name} installed`);
    },
    async uninstall_mod(id) {
      await sleep(900);
      const m = mods.find((x) => x.id === id);
      if (!m) return fail(`Unknown mod ${id}`);
      m.installed = false;
      if (id === "n3menu") st.menu = false;
      return ok(`${m.name} removed`);
    },
    async themes() { await sleep(200); return { themes: ["Purple", "Menu only", "Stock"] }; },
    async apply_theme(name) {
      await sleep(1500);
      const t = normTheme(name);
      Object.assign(st, { theme: t === "menuonly" ? "menu-only" : t, background: t === "purple", menu: t !== "stock" });
      return ok(`Theme “${name}” applied, UI restarted`);
    },
    async logs() {
      await sleep(120);
      tick += 1;
      return {
        natartos: logText("natartos", tick, 200, (i) => `I natartos: heartbeat seq=${i + 1} usb=ok`),
        n3mods: logText("n3mods", Math.floor(tick / 7), 50, (i) => `E n3mods: watchdog #${i + 1}: n3menu not loaded (not installed)`),
        ui: logText("ui", Math.floor(tick / 2), 200, (i) => `I dji_glasses: vsync avg=16.${6 + (i % 3)}ms drops=${i % 5 === 4 ? 1 : 0}`),
        capture: logText("capture", shots, 50, (i) => `I capture: wrote /data/local/tmp/n3cap/shot-${pad(i + 1, 4)}.jpg`),
      };
    },
    async live_resolutions() {
      await sleep(40);
      return { resolutions: FALLBACK_SCALES.slice(), default: DEFAULT_SCALE };
    },
    async live_start(scale) {
      await sleep(1200);
      if (!st.root) return fail("Root shell is not running");
      live = normScale(scale); frame = 0;
      return ok(`Live started at ${live}, UI restarted`);
    },
    async live_stop() { await sleep(400); live = null; return ok("Live stopped"); },
    async live_frame() {
      await sleep(25);
      if (!live) return { ok: false, image: "", width: 0, height: 0, fps: 0 };
      frame += 1;
      const [w, h] = scaleDims(live);
      return { ok: true, image: mockFrame(w, h, frame), width: w, height: h, fps: 22 + (frame % 4) };
    },
    async capture_screen() {
      await sleep(700);
      if (!st.root) return fail("Root shell is not running", { image: "", path: "" });
      shots += 1;
      const path = `/data/local/tmp/n3cap/shot-${String(shots).padStart(4, "0")}.jpg`;
      return ok(`Saved ${path}`, { image: mockFrame(1280, 720, frame + shots * 40), path });
    },
    async pcstream_info() {
      await sleep(60);
      return {
        ok: true,
        sender: { running: mockPc.running, size: mockPc.size, fps_target: mockPc.fps,
                  quality: mockPc.quality, frames: mockPc.frames, slow: 3, errors: 0,
                  fps: mockPc.running ? 11.8 : 0, kbps: mockPc.running ? 452 : 0,
                  host: "192.168.60.2", port: 5570, last_error: "" },
        device: { adb: true, pid: mockPc.running ? "12104" : "", hook: true,
                  decode_ms: 57.3, blit_ms: 89.0, dropped: 44,
                  flags: { fb_override: mockPc.running, fb_hold: mockPc.running, fb_stop: false },
                  log: mockPc.running
                    ? "fb_override + fb_hold set\nclient connected\nfirst frame 1280x720 (39484 bytes)\nframes 30  decode 57.3 ms  blit 89.0 ms\n"
                    : "No receiver log yet." },
        settings: { size: mockPc.size, fps: mockPc.fps, quality: mockPc.quality },
        sizes: ["960x540", "1280x720", "1600x900", "1920x1080"],
        notes: ["Enable ADB first.", "1280x720 at 12 fps is the sweet spot."],
      };
    },
    async pcstream_start(size, fps, quality) {
      await sleep(700);
      mockPc.running = true;
      mockPc.size = size || mockPc.size;
      mockPc.fps = fps || mockPc.fps;
      mockPc.quality = quality || mockPc.quality;
      return ok("PC stream started (mock).");
    },
    async pcstream_stop() { await sleep(400); mockPc.running = false; return ok("PC stream stopped (mock)."); },
    async pcstream_set(size, fps, quality) {
      await sleep(150);
      mockPc.size = size || mockPc.size;
      mockPc.fps = fps || mockPc.fps;
      mockPc.quality = quality || mockPc.quality;
      return ok("Stream settings saved (mock).");
    },
    async s2_probe() {
      await sleep(500);
      return ok("S2 capture probe (read-only)", { text: "== decoder ==\n-rwxr-xr-x 1 root shell 183920 2026-08-14 11:02 /system/bin/test_wl_vdec\n== option letters found in the binary ==\n-C -F -b -d -e -h -p -t -w\n== record tools ==\n-rwxr-xr-x 1 root shell  41936 /system/bin/omx_recordtest\n-rwxr-xr-x 1 root shell   1088 /system/bin/record_test_script.sh\n== usb ids (looking for 2ca3:1020) ==\n  /sys/bus/usb/devices/1-1  2ca3:1020\n== wlm config ==\n  found /vendor/etc/wlm_cfg.json\n  test.liveview\n== blackbox recordings ==\ntotal 0\n== existing capture dir ==\n/data/local/tmp/s2cap: No such file or directory\n" });
    },
    async s2_capture(iface, seconds) {
      await sleep(1400);
      return ok(`Captured 1 file(s) at /data/local/tmp/s2cap`, {
        text: `capture: iface=${iface} ${iface === "secondary" ? "640x360" : "1920x1080"} ${seconds}s -> /data/local/tmp/s2cap\n== run.log ==\n[usb_vdec] opened iface 3 ep 0x84\n[usb_vdec] dump enabled\n== files ==\n-rw-r--r-- 1 root root 3145728 s2_main.h265\n-rw-r--r-- 1 root root     412 run.log`,
        files: [{ name: "s2_main.h265", size: 3145728 }],
      });
    },
    async s2_pull(name) {
      await sleep(700);
      return ok(`Pulled ${name || "s2_main.h265"} (3145728 bytes)`, {
        path: "app/state/s2capture/s2_main.h265", size: 3145728, head: "0000000140010c01",
      });
    },
    async s2_stop() { await sleep(260); return ok("S2 decoder stopped", { text: "idle" }); },
    async s2_liveview() {
      await sleep(120);
      return fail("Link start/stop is not enabled in this build. Capture works without it; the 006E0001/0000 frame still needs a bench run with the aircraft off.");
    },
    async sparrow_report() {
      await sleep(600);
      return { ok: true, data: {
        subsystem: "sparrow2", mode: "read-only", firmware: "02.01.07 (mock)",
        link: { state: "idle", band: "5.8 GHz", channel: "auto", bitrate_mbps: 0 },
        temperature_c: 47.5,
        interfaces: ["/dev/sparrow_ctrl (read)", "/sys/class/sparrow2/stats"],
        capabilities: { transmit: false, iq_capture: false, jamming: false },
      } };
    },
    async sparrow_tools() {
      await sleep(450);
      return { ok: true, text: "sparrow2 tool inventory (mock)\n\n  /vendor/bin/sparrow_stat      read   link + temperature counters\n  /vendor/bin/sparrow_info      read   firmware and board identifiers\n  /sys/class/sparrow2/stats     read   sysfs counters\n  /dev/sparrow_ctrl             read   opened O_RDONLY only\n\nWrite-capable tools are not listed and not callable from N3 ROOT." };
    },
    async sparrow_console() {
      await sleep(300);
      return { ok: true, text: "Sparrow2 read-only console (mock)\n\n  status        link state, band, channel\n  version       firmware and hardware revision\n  counters      packet and error counters\n  temp          radio temperature\n  help          this text\n\nTransmit, tuning, jamming and IQ commands are not available." };
    },
    async prefs() { await sleep(60); return { ...prefs }; },
    async set_pref(key, value) { await sleep(120); prefs[key] = value; return { ok: true }; },
  };
}

/** Renders a deterministic OSD-style test frame for the mock live preview. */
function mockFrame(w, h, t) {
  const c = mockFrame.canvas || (mockFrame.canvas = document.createElement("canvas"));
  c.width = w;
  c.height = h;
  const g = c.getContext("2d");
  const s = w / 640;
  const cy = h * 0.55;

  const sky = g.createLinearGradient(0, 0, 0, h);
  sky.addColorStop(0, "#1a0f2e");
  sky.addColorStop(0.54, "#4a2577");
  sky.addColorStop(0.55, "#150c22");
  sky.addColorStop(1, "#060409");
  g.fillStyle = sky;
  g.fillRect(0, 0, w, h);

  g.fillStyle = "rgba(255,255,255,.06)";
  for (let i = 0; i < 9; i++) {
    const x = ((i * 97 + t * 3) % (w + 80)) - 40;
    g.fillRect(x, cy + 6 * s + (i % 3) * 18 * s, 40 * s, 2 * s);
  }

  g.save();
  g.translate(w / 2, cy);
  g.rotate(Math.sin(t / 24) * 0.07);
  g.strokeStyle = "rgba(255,255,255,.75)";
  g.lineWidth = Math.max(1, 1.6 * s);
  g.beginPath();
  g.moveTo(-w * 0.2, 0); g.lineTo(-w * 0.05, 0);
  g.moveTo(w * 0.05, 0); g.lineTo(w * 0.2, 0);
  g.stroke();
  g.restore();

  g.strokeStyle = "rgba(255,255,255,.85)";
  g.beginPath();
  g.arc(w / 2, cy, 7 * s, 0, Math.PI * 2);
  g.stroke();

  g.fillStyle = "#fff";
  g.font = `600 ${Math.max(7, Math.round(13 * s))}px Cascadia Mono, Consolas, monospace`;
  g.textAlign = "left";
  g.fillText("MOCK FEED", 18 * s, 54 * s);
  g.fillText(`CH 3  ·  ${(12 + (t % 5) * 0.4).toFixed(1)} ms`, 18 * s, h - 20 * s);
  g.textAlign = "right";
  g.fillText(`${(24.6 + Math.sin(t / 15) * 0.4).toFixed(1)} V`, w - 18 * s, 54 * s);
  g.fillText(`F ${String(t).padStart(5, "0")}`, w - 18 * s, h - 20 * s);

  return c.toDataURL("image/jpeg", 0.82);
}

/* ==========================================================================
   Boot
   ========================================================================== */
function init() {
  renderActionTiles();
  renderSafetyKeys();
  renderScaleOptions();
  renderQuickCommands();
  renderHistory();
  shellWelcome();
  stagger(document.body);
  bindEvents();
  applyPrefs();

  // Deep link: #page for hash links, ?page= for screenshots and docs.
  detectMode();
  const wanted = new URLSearchParams(location.search).get("page") || location.hash.slice(1);
  go(PAGES.some((p) => p.id === wanted) ? wanted : "connection", { instant: true });
}

init();
