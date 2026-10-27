// Worker phone badge: a rotating signed token as a QR code. The edge camera reads it to punch in/out;
// faces are never used. Shows only the worker's name and id, and her latest receipt in her language.
import { api, esc, fmtDay, hm } from "/shared/api.js";
import qrcode from "./vendor/qrcode.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const WID = params.get("w") || "W001";

// This page's own small dictionary (the shared i18n catalogue belongs to the worker app).
const T = {
  en: { skip: "Skip to content", badge: "Work badge", show: "Show this to the camera to punch in/out",
    refresh: "New code in {n} s", every: "New code every 30 seconds", last: "Last punch", none: "No punch yet.",
    wake: "Keep the screen on and bright while you are at the gate.", wakeOn: "The screen will stay on while this page is open.",
    privacy: "The camera blurs faces. Only this code marks your attendance.", loading: "Getting your code…",
    unavailable: "Badge not available right now. Trying again…", qr: "Badge code for {name}. It changes every 30 seconds.",
    newPunch: "Done" },
  ta: { skip: "உள்ளடக்கத்திற்குச் செல்", badge: "வேலை அடையாள அட்டை", show: "வருகை / வெளியேற்றம் பதிய இதை கேமராவிடம் காட்டுங்கள்",
    refresh: "{n} வினாடியில் புதிய குறியீடு", every: "ஒவ்வொரு 30 வினாடிக்கும் புதிய குறியீடு", last: "கடைசி பதிவு",
    none: "இன்னும் பதிவு இல்லை.", wake: "வாயிலில் இருக்கும் வரை திரையை ஒளிர்வாக வைத்திருங்கள்.",
    wakeOn: "இந்தப் பக்கம் திறந்திருக்கும் வரை திரை அணையாது.",
    privacy: "கேமரா முகங்களை மங்கலாக்குகிறது. இந்தக் குறியீடு மட்டுமே உங்கள் வருகையைப் பதிகிறது.",
    loading: "உங்கள் குறியீடு வருகிறது…", unavailable: "அட்டை இப்போது கிடைக்கவில்லை. மீண்டும் முயல்கிறது…",
    qr: "{name} அவர்களின் அட்டைக் குறியீடு. ஒவ்வொரு 30 வினாடிக்கும் மாறும்.", newPunch: "பதிவானது" },
  hi: { skip: "सामग्री पर जाएँ", badge: "काम का बैज", show: "हाज़िरी (आना/जाना) लगाने के लिए इसे कैमरे को दिखाएँ",
    refresh: "{n} सेकंड में नया कोड", every: "हर 30 सेकंड में नया कोड", last: "पिछली हाज़िरी", none: "अभी तक कोई हाज़िरी नहीं।",
    wake: "गेट पर रहते समय स्क्रीन चालू और तेज़ रखें।", wakeOn: "यह पेज खुला रहने तक स्क्रीन चालू रहेगी।",
    privacy: "कैमरा चेहरों को धुंधला कर देता है। आपकी हाज़िरी सिर्फ़ इसी कोड से लगती है।", loading: "आपका कोड आ रहा है…",
    unavailable: "बैज अभी उपलब्ध नहीं है। फिर से कोशिश हो रही है…", qr: "{name} का बैज कोड। यह हर 30 सेकंड में बदलता है।",
    newPunch: "हो गया" },
  or: { skip: "ବିଷୟବସ୍ତୁକୁ ଯାଆନ୍ତୁ", badge: "କାମ ବ୍ୟାଜ୍", show: "ହାଜିରା (ଆସିବା/ଯିବା) ପାଇଁ ଏହାକୁ କ୍ୟାମେରାକୁ ଦେଖାନ୍ତୁ",
    refresh: "{n} ସେକେଣ୍ଡରେ ନୂଆ କୋଡ୍", every: "ପ୍ରତି 30 ସେକେଣ୍ଡରେ ନୂଆ କୋଡ୍", last: "ଶେଷ ହାଜିରା",
    none: "ଏପର୍ଯ୍ୟନ୍ତ କୌଣସି ହାଜିରା ନାହିଁ।", wake: "ଗେଟ୍‌ରେ ଥିବା ବେଳେ ସ୍କ୍ରିନ୍ ଚାଲୁ ଓ ଉଜ୍ଜ୍ୱଳ ରଖନ୍ତୁ।",
    wakeOn: "ଏହି ପୃଷ୍ଠା ଖୋଲା ଥିବା ପର୍ଯ୍ୟନ୍ତ ସ୍କ୍ରିନ୍ ଚାଲୁ ରହିବ।",
    privacy: "କ୍ୟାମେରା ମୁହଁକୁ ଅସ୍ପଷ୍ଟ କରେ। କେବଳ ଏହି କୋଡ୍ ଆପଣଙ୍କ ହାଜିରା ଦିଏ।", loading: "ଆପଣଙ୍କ କୋଡ୍ ଆସୁଛି…",
    unavailable: "ବ୍ୟାଜ୍ ବର୍ତ୍ତମାନ ମିଳୁନାହିଁ। ପୁଣି ଚେଷ୍ଟା ଚାଲିଛି…", qr: "{name}ଙ୍କ ବ୍ୟାଜ୍ କୋଡ୍। ଏହା ପ୍ରତି 30 ସେକେଣ୍ଡରେ ବଦଳେ।",
    newPunch: "ହୋଇଗଲା" },
};
let lang = "en";
let workerLang = "en";
const t = (k, vars = {}) => String((T[lang] && T[lang][k]) || T.en[k] || k).replace(/\{(\w+)\}/g, (_, v) => vars[v] ?? "");

function applyLang(l) {
  lang = T[l] ? l : "en";
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
}

// ---------- QR ----------
const C = 2 * Math.PI * 19;  // ring circumference (r=19)
const st = { token: null, exp: 0, ttl: 30, refreshT: null, name: "", lastSeq: null, failing: false };

function drawQR(text) {
  const q = qrcode(0, "M");
  q.addData(text, "Byte");
  q.make();
  const n = q.getModuleCount(), m = 4, size = n + 2 * m;
  let d = "";
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) d += `M${c + m} ${r + m}h1v1h-1z`;
  const box = $("qr");
  box.innerHTML = `<svg viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges" aria-hidden="true" focusable="false">` +
    `<rect width="${size}" height="${size}" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  box.classList.remove("stale", "flip");
  void box.offsetWidth;
  box.classList.add("flip");
  box.setAttribute("aria-label", t("qr", { name: st.name || WID }));
}

function parseExp(v, ttl) {
  const now = Date.now();
  let ms = NaN;
  if (typeof v === "number") ms = v < 1e12 ? v * 1000 : v;
  else if (typeof v === "string") ms = /^\d+(\.\d+)?$/.test(v) ? Number(v) * 1000 : Date.parse(v);
  // trust the server's expiry unless the phone's clock is clearly off; then count the ttl locally
  if (!isFinite(ms) || ms < now - 2000 || ms > now + (ttl + 10) * 1000) ms = now + ttl * 1000;
  return ms;
}

async function refresh() {
  clearTimeout(st.refreshT);
  const r = await api(`/workers/${encodeURIComponent(WID)}/badge`);
  if (!r.ok || !r.data || !r.data.token) {
    st.failing = true;
    $("err").textContent = t("unavailable");
    $("err").classList.remove("hidden");
    if (Date.now() > st.exp) $("qr").classList.add("stale");
    st.refreshT = setTimeout(refresh, 3000);
    return;
  }
  st.failing = false;
  $("err").classList.add("hidden");
  const b = r.data;
  st.ttl = Number(b.ttl) || 30;
  st.exp = parseExp(b.expires_at, st.ttl);
  if (b.name && !st.name) setName(b.name);
  if (b.token !== st.token) { st.token = b.token; drawQR(b.token); $("qr").dataset.token = b.token; }
  st.refreshT = setTimeout(refresh, Math.max(1000, st.exp - Date.now() - 3000));
  tick();
}

function tick() {
  if (!st.exp) return;
  const left = Math.max(0, st.exp - Date.now());
  const frac = Math.min(1, left / (st.ttl * 1000));
  const ring = $("ring");
  ring.style.strokeDashoffset = String(C * (1 - frac));
  ring.classList.toggle("low", left < 5000);
  const s = Math.ceil(left / 1000);
  $("secs").textContent = String(s);
  $("tlabel").textContent = t("refresh", { n: s });
  if (left === 0 && !st.failing) $("qr").classList.add("stale");
}

function setName(name) {
  st.name = name;
  $("name").textContent = name;
  document.title = `${name} · Saakshi badge`;
}

// ---------- last punch (her latest wallet receipt) ----------
let freshT = null;
async function pollReceipt() {
  const r = await api(`/workers/${encodeURIComponent(WID)}/receipts?limit=20`);
  if (!r.ok || !Array.isArray(r.data)) return;
  const rc = r.data.find((x) => String(x.type || "").startsWith("punch"));  // newest punch receipt
  if (!rc) { $("lastText").textContent = t("none"); st.lastSeq = 0; return; }
  const text = lang === workerLang ? rc.text || rc.text_en : rc.text_en || rc.text;
  const isNew = st.lastSeq !== null && rc.seq !== st.lastSeq;  // null: first poll, nothing to announce
  if (rc.seq !== st.lastSeq) {
    $("lastText").textContent = (isNew ? "✓ " : "") + text;
    // the site's own clock time, as written in the record (not the phone's time zone)
    $("lastTime").textContent = `${fmtDay(rc.ts, lang === "en" ? "en-IN" : lang + "-IN")} · ${hm(rc.ts)}`;
  }
  if (isNew) {
    const box = $("lastText").closest(".last");
    box.classList.add("fresh");
    clearTimeout(freshT);
    freshT = setTimeout(() => box.classList.remove("fresh"), 8000);
    refresh();  // a code that was just used is spent: show the next one straight away
  }
  st.lastSeq = rc.seq;
}

// ---------- keep the screen on where the browser allows it ----------
let lock = null;
async function wake() {
  try {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    lock = await navigator.wakeLock.request("screen");
    $("wake").classList.add("on");
    $("wakeText").dataset.t = "wakeOn";
    $("wakeText").textContent = t("wakeOn");
    lock.addEventListener("release", () => { $("wake").classList.remove("on"); $("wakeText").dataset.t = "wake"; $("wakeText").textContent = t("wake"); });
  } catch { /* not allowed: the hint stays */ }
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && !lock) wake(); else if (document.visibilityState === "visible" && lock && lock.released) wake(); });

// ---------- start ----------
async function start() {
  $("wid").textContent = WID;
  applyLang(params.get("lang") || "en");
  $("qr").innerHTML = `<span class="muted">${esc(t("loading"))}</span>`;
  const w = await api(`/workers/${encodeURIComponent(WID)}`);
  if (w.ok && w.data) {
    workerLang = w.data.lang || "en";
    if (!params.get("lang")) applyLang(workerLang);
    if (w.data.name) setName(w.data.name);
  }
  $("qr").innerHTML = `<span class="muted">${esc(t("loading"))}</span>`;
  await refresh();
  pollReceipt();
  setInterval(tick, 250);
  setInterval(pollReceipt, 3000);
  wake();
}
start();
