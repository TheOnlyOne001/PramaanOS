// Live edge camera: blurred MJPEG preview from the edge box, restricted-zone editor, box status and a live
// feed of badge punches and zone events. Polls only; the page never sees an un-blurred frame.
import { api, esc, hm } from "/shared/api.js";
import { createZoneEditor } from "./zones.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const CAMERA = params.get("camera") || "cam-01";
const FALLBACK_STREAM = "http://127.0.0.1:8765/stream.mjpg";
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");

const stage = $("stage"), img = $("feed"), offline = $("offline");
$("camId").textContent = CAMERA;

// ---------- theme (dark first; the choice is remembered on this device) ----------
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  $("themeText").textContent = t === "dark" ? "Dark" : "Light";
  $("themeBtn").setAttribute("aria-pressed", String(t === "dark"));
  $("themeBtn").setAttribute("aria-label", `Dark mode ${t === "dark" ? "on" : "off"}`);
}
try { applyTheme(localStorage.getItem("saakshi.camera.theme") || "dark"); } catch { applyTheme("dark"); }
$("themeBtn").addEventListener("click", () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(t);
  try { localStorage.setItem("saakshi.camera.theme", t); } catch { /* storage off */ }
});

// ---------- zone editor ----------
const editor = createZoneEditor({ camera: CAMERA, stage, img, svg: $("overlay") });
editor.load();

// ---------- stream with auto-reconnect ----------
const stream = { url: FALLBACK_STREAM, live: false, retry: null, lastOnline: null, switching: false };

function setLive(on) {
  stream.live = on;
  offline.classList.toggle("hidden", on);
  stage.classList.toggle("is-off", !on);
  img.classList.toggle("off", !on);
  $("liveBadge").textContent = on ? "LIVE" : "NO SIGNAL";
  $("liveBadge").classList.toggle("idle", !on);
  if (on) editor.layout();
}

// Re-request the same URL (no cache-busting query: the box serves exactly /stream.mjpg).
function connect() {
  clearTimeout(stream.retry);
  stream.switching = true;
  img.removeAttribute("src");
  setTimeout(() => { stream.switching = false; img.src = stream.url || FALLBACK_STREAM; }, 30);
}
function scheduleRetry() {
  clearTimeout(stream.retry);
  stream.retry = setTimeout(connect, 3000);
}
img.addEventListener("load", () => { if (img.naturalWidth > 0) setLive(true); });
img.addEventListener("error", () => { if (stream.switching) return; setLive(false); scheduleRetry(); });
// Chromium may not fire `load` for every MJPEG part; poll the decoded size as well.
setInterval(() => { if (!stream.live && img.naturalWidth > 0 && img.complete !== false) setLive(true); }, 1000);
setLive(false);

// ---------- status ----------
const shown = { blurred: null };
function countTo(el, from, to) {
  if (from == null || REDUCED.matches || Math.abs(to - from) < 2) { el.textContent = to.toLocaleString("en-IN"); return; }
  const t0 = performance.now(), dur = 900;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = Math.round(from + (to - from) * e).toLocaleString("en-IN");
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

const BACKEND = { yolo11n: "YOLO11n", hog: "HOG" };
const DEVICE = { cuda: "CUDA", cpu: "CPU" };
const FACE = { yunet: "YuNet", haar: "Haar cascade" };

function ago(ts) {
  if (!ts) return "never";
  const t = typeof ts === "number" ? ts * (ts < 1e12 ? 1000 : 1) : Date.parse(ts);
  if (!isFinite(t)) return String(ts);
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return new Date(t).toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" });
}

function chip(cls, text, title) {
  return `<span class="chip ${cls}"${title ? ` title="${esc(title)}"` : ""}>${text}</span>`;
}

function renderStatus(box, err) {
  const top = $("topStatus"), topText = $("topStatusText");
  if (!box) {
    top.className = "chip neutral"; topText.textContent = err ? "Status unavailable" : "No edge box yet";
    $("chips").innerHTML = chip("neutral", err ? "Status unavailable" : "Waiting for the first heartbeat");
    ["tPersons", "tZone", "tBlurred"].forEach((id) => { $(id).textContent = "—"; });
    return;
  }
  const on = !!box.online;
  top.className = "chip " + (on ? "ok" : "crit");
  topText.textContent = on ? `Box online · ${box.box_id || ""}`.trim() : "Box offline";
  const b = BACKEND[box.backend] || box.backend || "Detector", d = DEVICE[box.device] || box.device || "?";
  $("chips").innerHTML = [
    chip(on ? "ok" : "crit", `<span class="dot" aria-hidden="true"></span>${on ? "Online" : "Offline"} · seen ${esc(ago(box.last_seen))}`),
    box.fps != null ? chip("info", `${esc(Number(box.fps).toFixed(0))} fps`) : "",
    chip(box.device === "cuda" ? "ok" : "neutral", `${esc(b)} on ${esc(d)}`, "Person detector"),
    chip("neutral", `Face blur: ${esc(FACE[box.face_backend] || box.face_backend || "?")}`),
  ].join("");
  $("tPersons").textContent = box.persons_now != null ? box.persons_now : "—";
  const z = box.in_zone_now;
  $("tZone").textContent = z != null ? z : "—";
  $("tZone").parentElement.classList.toggle("hot", z > 0);
  if (box.faces_blurred_total != null) {
    const to = Number(box.faces_blurred_total);
    if (shown.blurred !== to) { countTo($("tBlurred"), shown.blurred, to); shown.blurred = to; }
  }
}

async function pollStatus() {
  const r = await api("/edge/status");
  let box = null;
  if (r.ok && Array.isArray(r.data)) box = r.data.find((b) => b.camera === CAMERA) || r.data[0] || null;
  renderStatus(box, !r.ok);
  if (box) {
    const url = box.preview_url || FALLBACK_STREAM;
    if (url !== stream.url) { stream.url = url; connect(); }
    // the box went away while the image still shows its last frame: drop it and start retrying
    if (stream.lastOnline === true && !box.online) { setLive(false); connect(); }
    stream.lastOnline = !!box.online;
    $("offKicker").textContent = box.online ? "Connecting to the preview…" : `Edge box offline · last seen ${ago(box.last_seen)}`;
  } else {
    $("offKicker").textContent = "Edge box offline";
  }
}

// ---------- live feed: badge punches + zone events ----------
const seen = new Set();
let primed = false;
let names = {};
const KIND = {
  restricted_zone_entry: "Restricted zone entry", zone_entry: "Restricted zone entry", ppe_compliance_rate: "PPE compliance",
  queue_length: "Queue length", near_miss: "Near miss", heat_wbgt: "Heat (WBGT)", person_count: "People counted",
};
const isZoneEntry = (k) => /zone_entry|restricted/.test(k || "");

async function loadNames() {
  const r = await api("/workers");
  if (r.ok && Array.isArray(r.data)) names = Object.fromEntries(r.data.map((w) => [w.id, w.name]));
}

function itemFor(e) {
  if (e.src === "punch") {
    const isIn = e.type === "punch.in";
    const who = names[e.worker_id] || e.worker_id || "Worker";
    const via = e.payload && e.payload.via === "badge" ? "Badge at camera" : (e.payload && e.payload.device) || "Gate";
    return { key: "p" + e.seq, ts: e.ts, ico: isIn ? "in" : "out", icoText: isIn ? "IN" : "OUT",
      what: `${who} · ${isIn ? "IN" : "OUT"}`, sub: `${via} · <span class="rc">✓ receipt sent</span>`,
      flash: { cls: "", ico: isIn ? "→" : "←", main: `${who} punched ${isIn ? "IN" : "OUT"}`, sub: `${hm(e.ts)} · ${via} · receipt sent to her phone` } };
  }
  const label = KIND[e.kind] || String(e.kind || "Event").replace(/_/g, " ");
  const zone = isZoneEntry(e.kind);
  const n = e.count != null ? `${e.count} ${e.count === 1 ? "person" : "people"}` : e.value != null ? String(e.value) : "";
  return { key: "e" + e.seq, ts: e.ts, ico: zone ? "zone" : "info", icoText: zone ? "!" : "i",
    what: `${label}${e.zone ? " · " + e.zone : ""}`, sub: [e.camera, n].filter(Boolean).join(" · "),
    flash: zone ? { cls: "zone", ico: "⚠", main: `Restricted zone entry · ${e.zone || ""}`, sub: `${hm(e.ts)} · ${n || "1 person"} · ${e.camera || ""}` } : null };
}

let flashT = null;
function flash(f) {
  const el = $("flash");
  el.className = "flash " + (f.cls || "");
  el.innerHTML = `<span class="f-ico" aria-hidden="true">${esc(f.ico)}</span><span><span class="f-main">${esc(f.main)}</span><br><span class="f-sub">${esc(f.sub)}</span></span>`;
  requestAnimationFrame(() => el.classList.add("show"));
  clearTimeout(flashT);
  flashT = setTimeout(() => el.classList.remove("show"), 4200);
}

function renderFeed(items, fresh) {
  const list = $("feed-list");
  list.innerHTML = items.slice(0, 30).map((it) => `<li class="${fresh.has(it.key) ? "new" : ""}">
    <span class="ico ${it.ico}" aria-hidden="true">${it.icoText}</span>
    <span><span class="what">${esc(it.what)}</span><br><span class="sub">${it.sub.includes("<span") ? it.sub : esc(it.sub)}</span></span>
    <time datetime="${esc(it.ts)}">${esc(hm(it.ts))}</time></li>`).join("");
  $("feedEmpty").classList.toggle("hidden", items.length > 0);
}

let feedItems = [];
async function pollFeed() {
  const [ev, pu] = await Promise.all([api("/edge/events?limit=20"), api("/ledger/events?type_prefix=punch&limit=10")]);
  const rows = [];
  // this camera's events, plus restricted-zone entries from any camera
  if (ev.ok && Array.isArray(ev.data)) rows.push(...ev.data.filter((e) => e.camera === CAMERA || isZoneEntry(e.kind)).map((e) => ({ ...e, src: "edge" })));
  if (pu.ok && Array.isArray(pu.data)) rows.push(...pu.data.map((e) => ({ ...e, src: "punch" })));
  const items = rows.map(itemFor);
  const fresh = new Set();
  let newest = null;
  for (const it of items) {
    if (seen.has(it.key)) continue;
    seen.add(it.key);
    if (primed) { fresh.add(it.key); if (it.flash && (!newest || it.ts >= newest.ts)) newest = it; }
  }
  if (!fresh.size && primed) return;
  const byKey = new Map(feedItems.map((i) => [i.key, i]));
  items.forEach((i) => byKey.set(i.key, i));
  feedItems = [...byKey.values()].sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : b.key.localeCompare(a.key))).slice(0, 40);
  renderFeed(feedItems, fresh);
  if (newest) flash(newest.flash);
  primed = true;
}

// ---------- fullscreen ----------
const fsBtn = $("fsBtn");
if (!stage.requestFullscreen) fsBtn.classList.add("hidden");
fsBtn.addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else stage.requestFullscreen().catch(() => { /* refused */ });
});
document.addEventListener("fullscreenchange", () => {
  fsBtn.setAttribute("aria-label", document.fullscreenElement ? "Exit full screen" : "Full screen");
  setTimeout(() => editor.layout(), 50);
});

$("copyCmd").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("startCmd").textContent); $("copyCmd").textContent = "Copied"; }
  catch { $("copyCmd").textContent = "Select and copy"; }
  setTimeout(() => { $("copyCmd").textContent = "Copy"; }, 2000);
});

window.addEventListener("beforeunload", (ev) => { if (editor.isDirty()) { ev.preventDefault(); ev.returnValue = ""; } });

// ---------- loops ----------
connect();
loadNames().then(pollFeed);
pollStatus();
setInterval(pollStatus, 2000);
setInterval(pollFeed, 2500);
