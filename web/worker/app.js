// Saakshi worker app: one worker's own copy of her work record.
import { api, esc, hm, fmtDay, rupees, num, toast } from "/shared/api.js";
import { t, term, LANGS, LANG_NAMES, SPEECH_LANG, LOCALE, matchAnswer } from "/shared/i18n.js";

const DEMO_DAY = "2026-10-27";
const PERIOD = "2026-10";
const HOURS_FROM = "2026-10-19";
const POLL_MS = 3000;

const qs = new URLSearchParams(location.search);
const S = {
  wid: (qs.get("w") || "W001").toUpperCase(),
  worker: null, lang: "en", tab: "today", names: {},
  mismatches: [], receipts: [], seenSeqs: null, pending: [], consentResult: null, listening: false,
  voice: { topic: null, text: "", scrub: null, busy: false, cases: [] },
  rules: null,
};
const L = (k, v) => t(S.lang, k, v);
const $ = (s, root = document) => root.querySelector(s);
const locale = () => LOCALE[S.lang] || "en-IN";
const day = (d) => fmtDay(d, locale());
const nameOf = (id) => S.names[id] || id || "";
const firstName = (id) => (nameOf(id) || "").split(" ")[0];

const TABS = [
  { id: "today", icon: "☀️" }, { id: "pay", icon: "💰" }, { id: "hours", icon: "⏱️" },
  { id: "skills", icon: "🎓" }, { id: "voice", icon: "📣" }, { id: "rights", icon: "⚖️" },
];
const TYPE_ICON = { "punch.in": "🟢", "punch.out": "🏠", "punch.correction": "✏️", "access.lookup": "👁️",
  "ot.request": "⏱️", "ot.consent": "✋", "ot.cap_check": "⏱️", "pay.run": "💰", "credential.issued": "🎓",
  "credential.revoked": "🎓", "production.count": "🧵" };
const TOPIC_ICON = { water: "💧", toilets: "🚻", toilet: "🚻", heat: "🌡️", harassment: "🛑", wages: "₹", pay: "₹",
  safety: "⚠️", food: "🍲", overtime: "⏱️", ot: "⏱️", fire: "🔥", exits: "🚪", leave: "📅", canteen: "🍲", other: "💬" };

function unavailable(msg) {
  return `<div class="card empty"><span aria-hidden="true">🕓</span> ${esc(msg || L("not_available"))}</div>`;
}
function refChip(seq, ref) {
  if (seq === undefined || seq === null) return "";
  const label = ref ? `${ref}` : `#${seq}`;
  return `<a class="ref" href="/api/ledger/events/${encodeURIComponent(seq)}" target="_blank" rel="noopener" title="Ledger event #${esc(seq)}">${esc(label)}</a>`;
}
function evidenceChips(list) {
  if (!Array.isArray(list) || !list.length) return "";
  const shown = list.slice(0, 6).map((s) => refChip(s, `#${s}`)).join(" ");
  const more = list.length > 6 ? ` <span class="muted">+${list.length - 6}</span>` : "";
  return `<div class="evidence"><span class="muted">${esc(L("evidence"))}:</span> ${shown}${more}</div>`;
}
function hmOf(v) { if (!v) return "—"; return String(v).length >= 16 ? hm(v) : String(v).slice(0, 5); }

// --- Read aloud -----------------------------------------------------------------
function speak(text) {
  if (!("speechSynthesis" in window)) { toast(L("not_available")); return; }
  const synth = window.speechSynthesis;
  if (synth.speaking) { synth.cancel(); $("#speak").classList.remove("on"); return; }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = SPEECH_LANG[S.lang] || "en-IN";
  const v = synth.getVoices().find((x) => x.lang && x.lang.replace("_", "-").toLowerCase().startsWith(u.lang.slice(0, 2).toLowerCase()));
  if (v) u.voice = v;
  u.rate = 0.92;
  u.onend = u.onerror = () => $("#speak").classList.remove("on");
  $("#speak").classList.add("on");
  synth.speak(u);
}
function screenSpeech() {
  const parts = [];
  const b = $("#banner [data-say]");
  if (b) parts.push(b.innerText);
  document.querySelectorAll("#screen [data-say]").forEach((el) => parts.push(el.getAttribute("data-say") || el.innerText));
  return parts.join(". ").replace(/\s+/g, " ").trim();
}

// --- Speech recognition -----------------------------------------------------------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function listen(onResult, onEnd) {
  if (!SR) return null;
  try {
    const r = new SR();
    r.lang = SPEECH_LANG[S.lang] || "ta-IN";
    r.interimResults = false;
    r.maxAlternatives = 4;
    r.onresult = (e) => onResult([...e.results[0]].map((a) => a.transcript));
    r.onerror = (e) => onEnd(e.error || "error");
    r.onend = () => onEnd();
    r.start();
    return r;
  } catch (e) { onEnd(String(e)); return null; }
}

// --- Shell ---------------------------------------------------------------------------
function renderShell() {
  document.documentElement.lang = S.lang;
  const w = S.worker || { name: S.wid };
  $("#avatar").textContent = (w.name || "?").slice(0, 1);
  $("#whoName").textContent = L("hello", { name: (w.name || "").split(" ")[0] });
  $("#whoSub").innerHTML = `<span class="mono">${esc(S.wid)}</span> · ${esc(w.role || "")}`;
  $("#speakLabel").textContent = L("read_aloud");
  $("#speakSub").textContent = L("bhashini");
  $("#langLabel").textContent = L("language");
  const sel = $("#lang");
  sel.innerHTML = LANGS.map((l) => `<option value="${l}" ${l === S.lang ? "selected" : ""}>${LANG_NAMES[l]}</option>`).join("");
  $("#tabs").innerHTML = TABS.map((tb) => `
    <button type="button" class="tab ${tb.id === S.tab ? "active" : ""}" data-tab="${tb.id}" aria-current="${tb.id === S.tab ? "page" : "false"}">
      <span class="tab-icon" aria-hidden="true">${tb.icon}</span><span class="tab-label">${esc(L("tab_" + tb.id))}</span>
      ${tb.id === "today" && S.pending.length ? `<span class="badge" aria-label="pending">${S.pending.length}</span>` : ""}
    </button>`).join("");
}

function renderBanner() {
  const el = $("#banner");
  if (!S.mismatches.length) { el.innerHTML = ""; el.className = ""; document.title = "Saakshi · சாட்சி"; return; }
  const own = S.worker && S.lang === S.worker.lang;
  const seg = (s) => String(s || "").split(" · ")[0];
  const rows = S.mismatches.map((m) => {
    if (m.kind === "deleted") {
      return `<p>${esc(L("integrity_deleted", { ref: m.ref || "#" + m.seq }))}</p>`;
    }
    const mine = seg(own || S.lang !== "en" ? (own ? m.receipt_text : m.receipt_text_en) : m.receipt_text_en);
    let theirs = seg(own ? m.current_text : m.current_text_en);
    const a = mine.match(/^(.*?)(\d{1,2}:\d{2})$/), b = theirs.match(/^(.*?)(\d{1,2}:\d{2})$/);
    if (a && b && a[1] === b[1]) theirs = b[2];
    return `<p class="int-body">${esc(L("integrity_body", { mine, theirs }))}</p>
      <p class="int-note">${esc(L("integrity_note", { ref: m.ref || "#" + m.seq }))} <span class="mono">#${esc(m.seq)}</span></p>`;
  }).join("");
  el.className = "integrity";
  el.innerHTML = `<div class="int-inner" data-say>
    <div class="int-head"><span class="int-icon" aria-hidden="true">⚠️</span><b>${esc(L("integrity_title"))}</b></div>${rows}</div>`;
  document.title = "⚠ " + L("integrity_title");
}

function setTab(id, push = true) {
  S.tab = TABS.some((x) => x.id === id) ? id : "today";
  if (push) history.replaceState(null, "", `?w=${S.wid}${qs.get("lang") ? "&lang=" + qs.get("lang") : ""}#${S.tab}`);
  renderShell();
  renderScreen();
  window.scrollTo(0, 0);
}

async function renderScreen() {
  const el = $("#screen");
  const fn = { today: renderToday, pay: renderPay, hours: renderHours, skills: renderSkills, voice: renderVoice, rights: renderRights }[S.tab];
  el.innerHTML = `<div class="card empty">${esc(L("loading"))}</div>`;
  try { await fn(el); } catch (e) { console.error(e); el.innerHTML = unavailable(L("error")); }
}

// --- Today ---------------------------------------------------------------------------
async function renderToday(el) {
  el.innerHTML = `
    <section id="shift" class="card shift"></section>
    <button type="button" class="hazard" id="hazard"><span aria-hidden="true">🛑</span> ${esc(L("hazard"))}</button>
    <section id="ot"></section>
    <section class="card chat-card">
      <h2><span aria-hidden="true">💬</span> ${esc(L("receipts_title"))}</h2>
      <p class="muted small" data-say>${esc(L("receipts_sub"))}</p>
      <div class="chat" id="chat" role="log" tabindex="0" aria-label="${esc(L("receipts_title"))}"></div>
    </section>
    <section class="card" id="access"></section>
    <details class="demo" id="demo">
      <summary>🧪 ${esc(L("demo_controls"))}</summary>
      <div class="demo-row">
        <input type="time" id="punchTime" aria-label="time">
        <button type="button" class="btn" data-punch="in">🟢 ${esc(L("punch_in"))}</button>
        <button type="button" class="btn" data-punch="out">🏠 ${esc(L("punch_out"))}</button>
      </div>
      <div class="demo-row"><button type="button" class="btn" id="simYes">🎤 “ஆம்”</button>
        <button type="button" class="btn" id="simNo">🎤 “இல்லை”</button></div>
    </details>`;
  $("#hazard").onclick = () => toast(L("hazard_toast"), 4500);
  el.querySelectorAll("[data-punch]").forEach((b) => (b.onclick = () => doPunch(b.dataset.punch)));
  $("#simYes").onclick = () => S.pending[0] && consent(S.pending[0], "accept", "voice", "ஆம்");
  $("#simNo").onclick = () => S.pending[0] && consent(S.pending[0], "decline", "voice", "இல்லை");
  S.seenSeqs = null;
  await Promise.all([refreshReceipts().then(refreshShift), refreshPending(true), refreshAccess()]);
}

async function refreshShift() {
  const el = $("#shift");
  if (!el) return;
  const r = await api(`/pay/${S.wid}/today?day=${DEMO_DAY}`);
  let d = r.ok ? r.data : null;
  // Fallback: today's punches from my own receipts.
  const todays = S.receipts.filter((x) => (x.ts || "").startsWith(DEMO_DAY));
  const inR = todays.filter((x) => x.type === "punch.in").sort((a, b) => a.seq - b.seq)[0];
  const outR = todays.filter((x) => x.type === "punch.out").sort((a, b) => b.seq - a.seq)[0];
  const inTs = d ? d.in : inR && inR.ts;
  const outTs = d ? d.out : outR && outR.ts;
  const worked = d ? d.worked_hours : null;
  const earned = d ? d.earned_today : null;
  const head = `<div class="shift-head"><h2>☀️ ${esc(L("today_shift"))}</h2><span class="muted">${esc(fmtDay(DEMO_DAY, locale(), { weekday: "short", day: "numeric", month: "long" }))}</span></div>`;
  if (!inTs) {
    el.innerHTML = `${head}<p class="big-empty" data-say>${esc(L("not_in_yet"))}</p>`;
    return;
  }
  el.innerHTML = `${head}
    <div class="stats">
      <div class="stat" data-say="${esc(L("in"))} ${esc(hmOf(inTs))}"><span class="stat-icon" aria-hidden="true">🟢</span><span class="stat-label">${esc(L("in"))}</span>
        <b class="stat-val">${esc(hmOf(inTs))}</b>${inR ? refChip(inR.seq, inR.ref) : ""}</div>
      <div class="stat" data-say="${esc(outTs ? L("out") + " " + hmOf(outTs) : L("hours_so_far") + " " + num(worked))}">
        ${outTs ? `<span class="stat-icon" aria-hidden="true">🏠</span><span class="stat-label">${esc(L("out"))}</span><b class="stat-val">${esc(hmOf(outTs))}</b>${outR ? refChip(outR.seq, outR.ref) : ""}`
          : `<span class="stat-icon" aria-hidden="true">⏳</span><span class="stat-label">${esc(L("hours_so_far"))}</span><b class="stat-val">${worked !== null ? esc(num(worked)) + " " + esc(L("hours_unit")) : "—"}</b>`}
      </div>
      <div class="stat wide" data-say="${esc(L("earned_today"))} ${earned !== null ? esc(rupees(earned)) : ""}"><span class="stat-icon" aria-hidden="true">💰</span><span class="stat-label">${esc(L("earned_today"))}</span>
        <b class="stat-val money">${earned !== null && earned !== undefined ? esc(rupees(earned, 2)) : `<small class="muted">${esc(L("not_available"))}</small>`}</b>
        ${d && d.ot_hours ? `<span class="muted small">⏱️ ${esc(L("ot_short"))} ${esc(num(d.ot_hours))} ${esc(L("hours_unit"))} · ${esc(rupees(d.ot_earned, 2))}</span>` : ""}
        ${outTs && worked !== null ? `<span class="muted small">⏳ ${esc(num(worked))} ${esc(L("hours_unit"))}</span>` : ""}
      </div>
    </div>`;
}

async function refreshReceipts() {
  const r = await api(`/workers/${S.wid}/receipts?limit=40`);
  if (!r.ok) { const c = $("#chat"); if (c) c.innerHTML = unavailable(); return; }
  const prevSeen = S.seenSeqs;
  const changed = JSON.stringify(r.data.map((x) => x.seq)) !== JSON.stringify(S.receipts.map((x) => x.seq));
  S.receipts = r.data;
  const chat = $("#chat");
  if (!chat) return;
  if (!changed && chat.childElementCount && !S._mismatchChanged) return;
  S._mismatchChanged = false;
  const items = [...r.data].reverse().slice(-14);
  if (!items.length) { chat.innerHTML = `<p class="muted center">${esc(L("no_receipts"))}</p>`; return; }
  const bad = new Set(S.mismatches.map((m) => m.seq));
  const own = S.worker && S.lang === S.worker.lang;
  let lastDay = "";
  chat.innerHTML = items.map((x) => {
    const d = (x.ts || "").slice(0, 10);
    const sep = d !== lastDay ? `<div class="day-sep"><span>${esc(day(d))}</span></div>` : "";
    lastDay = d;
    const main = own ? x.text : x.text_en;
    const isNew = prevSeen && !prevSeen.has(x.seq);
    return `${sep}<div class="bubble ${bad.has(x.seq) ? "changed" : ""} ${isNew ? "new" : ""}">
      <div class="b-text"><span aria-hidden="true">${TYPE_ICON[x.type] || "🧾"}</span> ${esc(main)}</div>
      ${own && S.lang !== "en" ? `<div class="b-sub">${esc(x.text_en)}</div>` : ""}
      ${bad.has(x.seq) ? `<div class="b-flag">⚠️ ${esc(L("integrity_title"))}</div>` : ""}
      <div class="b-meta"><span class="mono">#${esc(x.seq)} · ${esc(x.ref)}</span><span>${esc(hm(x.ts))}</span><span class="ticks" aria-hidden="true">✓✓</span></div>
    </div>`;
  }).join("");
  S.seenSeqs = new Set(r.data.map((x) => x.seq));
  if (prevSeen === null) S.seenSeqs = new Set(r.data.map((x) => x.seq));
  chat.scrollTop = chat.scrollHeight;
  if (isTodayChanged(prevSeen)) refreshShift();
}
function isTodayChanged(prev) { return prev && S.receipts.some((x) => !prev.has(x.seq) && x.type.startsWith("punch.")); }

async function refreshAccess() {
  const el = $("#access");
  if (!el) return;
  const r = await api(`/workers/${S.wid}/access-log`);
  const head = `<h2><span aria-hidden="true">👁️</span> ${esc(L("access_title"))}</h2>`;
  if (!r.ok) { el.innerHTML = head + unavailable(); return; }
  if (!r.data.length) { el.innerHTML = head + `<p class="muted" data-say>${esc(L("access_none"))}</p>`; return; }
  el.innerHTML = head + `<ul class="list">${r.data.slice(0, 6).map((a) => `
    <li data-say="${esc(nameOf(a.viewer))}: ${esc(a.reason)}"><span class="li-icon" aria-hidden="true">👁️</span>
      <div><b>${esc(nameOf(a.viewer))}</b> <span class="muted small">${esc(a.viewer_role || "")}</span>
      <div class="small">${esc(L("reason"))}: ${esc(a.reason)}</div></div>
      <span class="muted small right">${esc(day(a.ts))} ${esc(hm(a.ts))}</span></li>`).join("")}</ul>`;
}

async function refreshPending(force = false) {
  const r = await api(`/ot/requests?worker_id=${S.wid}&status=pending`);
  const list = r.ok && Array.isArray(r.data) ? r.data.filter((x) => x.status === "pending" || !x.status) : [];
  const changed = JSON.stringify(list.map((x) => x.request_id)) !== JSON.stringify(S.pending.map((x) => x.request_id));
  S.pending = list;
  if (changed) renderShell();
  const el = $("#ot");
  if (!el || S.listening) return;
  if (!changed && !force && !S._consentDirty) return;
  S._consentDirty = false;
  let html = "";
  if (S.consentResult) {
    const c = S.consentResult;
    html += `<div class="card consent-done ${c.decision}" data-say>
      <span class="big-icon" aria-hidden="true">${c.decision === "accept" ? "✓" : "✗"}</span>
      <p><b>${esc(L(c.decision === "accept" ? "accepted_msg" : "declined_msg", { ref: c.ref || "" }))}</b></p></div>`;
  }
  html += list.map(otCard).join("");
  el.innerHTML = html;
  el.querySelectorAll("[data-consent]").forEach((b) => {
    b.onclick = () => consent(S.pending.find((p) => p.request_id == b.dataset.req), b.dataset.consent, "tap");
  });
  el.querySelectorAll("[data-mic]").forEach((b) => (b.onclick = () => micConsent(b.dataset.req, b)));
}

function otCard(p) {
  const by = firstName(p.requested_by) || "Supervisor";
  const cap = p.cap || {};
  const pct = cap.cap ? Math.min(100, ((cap.used || 0) / cap.cap) * 100) : 0;
  return `<article class="card ot-card" aria-live="polite">
    <div class="ot-head"><span class="ot-icon" aria-hidden="true">⏱️</span><h2>${esc(L("ot_req_title"))}</h2></div>
    <p class="ot-body" data-say>${esc(L("ot_req_body", { by, hours: num(p.hours), date: day(p.date) }))}</p>
    <div class="ot-facts">
      <span class="chip info">💰 ${esc(L("ot_paid_double"))} ×2</span>
      ${cap.cap ? `<span class="chip neutral">⏱️ ${esc(L("cap_line", { used: num(cap.used), cap: num(cap.cap, 0) }))}</span>` : ""}
    </div>
    ${cap.cap ? `<div class="meter ${pct > 90 ? "crit" : pct > 75 ? "warn" : ""}" role="meter" aria-label="${esc(L("ot_req_title"))}" aria-valuemin="0" aria-valuenow="${cap.used}" aria-valuemax="${cap.cap}"><i style="width:${pct}%"></i></div>` : ""}
    <p class="ot-choice" data-say>🤝 ${esc(L("ot_choice"))}</p>
    <div class="mic-row">
      <button type="button" class="mic" data-mic data-req="${esc(p.request_id)}" aria-label="${esc(L("mic"))}"><span aria-hidden="true">🎤</span></button>
      <div class="mic-hint" id="mic-hint-${esc(p.request_id)}">${esc(SR ? L("say_answer") : L("mic_unavailable"))}</div>
    </div>
    <div class="answer-row">
      <button type="button" class="answer yes" data-consent="accept" data-req="${esc(p.request_id)}"><span class="a-icon" aria-hidden="true">✓</span>${esc(L("accept"))}</button>
      <button type="button" class="answer no" data-consent="decline" data-req="${esc(p.request_id)}"><span class="a-icon" aria-hidden="true">✗</span>${esc(L("decline"))}</button>
    </div>
  </article>`;
}

function micConsent(reqId, btn) {
  const hint = document.getElementById("mic-hint-" + reqId);
  const req = S.pending.find((p) => p.request_id == reqId);
  if (!SR) { hint.textContent = L("mic_unavailable"); return; }
  S.listening = true;
  btn.classList.add("on");
  hint.textContent = L("listening");
  listen((alts) => {
    const decision = alts.map(matchAnswer).find(Boolean);
    hint.textContent = L("heard", { text: alts[0] || "" });
    if (decision && req) consent(req, decision, "voice", alts[0]);
    else setTimeout(() => (hint.textContent = L("not_understood")), 900);
  }, (err) => {
    S.listening = false;
    btn.classList.remove("on");
    if (err && err !== "no-speech" && err !== "aborted") hint.textContent = L("mic_unavailable");
  });
}

async function consent(req, decision, channel, transcript) {
  if (!req) return;
  const r = await api(`/ot/requests/${encodeURIComponent(req.request_id)}/consent`, {
    method: "POST", body: { decision, channel, transcript: transcript || null },
  });
  if (!r.ok) { toast(`${L("error")}: ${r.error}`); return; }
  const ref = (r.data.receipt && r.data.receipt.ref) || (r.data.event && r.data.event.ref) || "";
  S.consentResult = { decision, ref };
  S._consentDirty = true;
  toast(L(decision === "accept" ? "accepted_msg" : "declined_msg", { ref }), 4500);
  await refreshPending(true);
  refreshReceipts();
}

async function doPunch(kind) {
  const tm = $("#punchTime") && $("#punchTime").value;
  const body = { worker_id: S.wid, kind };
  if (tm) body.ts = `${DEMO_DAY}T${tm}:00+05:30`;
  const r = await api("/punch", { method: "POST", body });
  if (!r.ok) { toast(`${L("error")}: ${r.error}`); return; }
  toast(L("punched", { ref: r.data.ref }));
  await refreshReceipts();
  refreshShift();
}

// --- Pay -------------------------------------------------------------------------------
async function renderPay(el) {
  const r = await api(`/pay/${S.wid}/payslip?period=${PERIOD}`);
  const period = fmtDay(PERIOD + "-01", locale(), { month: "long", year: "numeric" });
  const tampered = S.mismatches.length > 0;
  const head = `<h1 class="screen-title">💰 ${esc(L("payslip_title", { period }))}</h1>`;
  const blockedCard = `<section class="card blocked" data-say>
      <div class="blocked-head"><span aria-hidden="true">⛔</span><b>${esc(L("blocked_title"))}</b></div>
      <p>${esc(L("blocked_body"))}</p>
      ${S.mismatches.map((m) => `<p class="small"><span class="mono">#${esc(m.seq)} · ${esc(m.ref || "")}</span> ${esc((m.receipt_text || "").split(" · ")[0])} → ${esc((m.current_text || "").split(" · ")[0])}</p>`).join("")}
    </section>`;
  if (!r.ok) {
    el.innerHTML = head + (tampered ? blockedCard : "") + unavailable();
    return;
  }
  const p = r.data;
  const blocked = p.blocked || tampered;
  const expl = (p.explanation && (p.explanation[S.lang] || p.explanation.en)) || "";
  el.innerHTML = `${head}
    ${blocked ? blockedCard : ""}
    <section class="card net ${blocked ? "is-blocked" : ""}" data-say="${esc(L("net_pay"))} ${esc(rupees(p.net))}">
      <span class="muted">${esc(L("net_pay"))}</span>
      <div class="net-val">${esc(rupees(p.net, 2))}</div>
      ${blocked ? `<span class="chip crit">⛔ ${esc(L("blocked_title"))}</span>` : `<span class="chip ok">✓ ${esc(L("check_ok"))}</span>`}
      <div class="muted small">📅 ${esc(L("days_worked", { n: p.days_worked ?? "—" }))}</div>
    </section>
    ${expl ? `<section class="card explain"><div class="row-between"><h2>💡 ${esc(L("explain_title"))}</h2>
      <button type="button" class="btn small-btn" id="sayExpl">🔊 ${esc(L("read_aloud"))}</button></div><p data-say>${esc(expl)}</p></section>` : ""}
    <section class="card">
      <h2>➕ ${esc(L("gross"))} <span class="right">${esc(rupees(p.gross, 2))}</span></h2>
      <ul class="lines">${(p.lines || []).map((ln) => `<li><div class="row-between"><span>${esc(ln.label)}</span><b>${esc(rupees(ln.amount, 2))}</b></div>
        ${ln.formula ? `<div class="formula mono">${esc(ln.formula)}</div>` : ""}${evidenceChips(ln.evidence)}</li>`).join("")}</ul>
    </section>
    <section class="card">
      <h2>➖ ${esc(L("deductions"))} <span class="right">${esc(rupees(p.total_deductions, 2))}</span></h2>
      <ul class="lines">${(p.deductions || []).map((ln) => `<li><div class="row-between"><span>${esc(ln.label)}</span><b>− ${esc(rupees(ln.amount, 2))}</b></div>
        ${ln.formula ? `<div class="formula mono">${esc(ln.formula)}</div>` : ""}</li>`).join("") || `<li class="muted">—</li>`}</ul>
    </section>
    <section class="card">
      <h2>🔍 ${esc(L("checks_title"))}</h2>
      <ul class="checks">${(p.checks || []).map((c) => `<li class="${c.ok ? "ok" : "bad"}"><span class="ck" aria-hidden="true">${c.ok ? "✓" : "✗"}</span>
        <div><b>${esc(c.name)}</b> <span class="chip ${c.ok ? "ok" : "crit"}">${c.ok ? "✓ " + esc(L("check_ok")) : "✗ " + esc(L("check_fail"))}</span>
        ${c.detail ? `<div class="small muted">${esc(c.detail)}</div>` : ""}</div></li>`).join("")}</ul>
    </section>`;
  const b = $("#sayExpl");
  if (b) b.onclick = () => speak(expl);
}

// --- Hours -------------------------------------------------------------------------------
async function renderHours(el) {
  const [h, cap] = await Promise.all([api(`/hours/${S.wid}?from=${HOURS_FROM}&to=${DEMO_DAY}`), api(`/ot/cap?date=${DEMO_DAY}`)]);
  let html = `<h1 class="screen-title">⏱️ ${esc(L("hours_title"))}</h1>
    <p class="muted">${esc(L("hours_range", { from: day(HOURS_FROM), to: day(DEMO_DAY) }))}</p>`;
  const row = cap.ok && Array.isArray(cap.data) ? cap.data.find((x) => x.worker_id === S.wid) : null;
  if (row) {
    const pct = Math.min(100, (row.used / (row.cap || 144)) * 100);
    html += `<section class="card" data-say="${esc(L("cap_title"))}: ${esc(L("cap_line", { used: num(row.used), cap: num(row.cap, 0) }))}">
      <h2>📊 ${esc(L("cap_title"))}</h2>
      <div class="cap-big"><b>${esc(num(row.used))}</b><span>/ ${esc(num(row.cap, 0))} ${esc(L("hours_unit"))}</span>
        <span class="chip ${row.status === "over" ? "crit" : row.status === "near" ? "warn" : "ok"}">${row.status === "over" ? "⛔" : row.status === "near" ? "⚠️" : "✓"} ${esc(Math.round(pct))}%</span></div>
      <div class="meter ${row.status === "over" ? "crit" : row.status === "near" ? "warn" : ""}"><i style="width:${pct}%"></i></div>
      <p class="small">${esc(L("cap_left", { remaining: num(row.remaining), cap: num(row.cap, 0) }))}</p>
      <p class="muted small">${esc(L("cap_note"))}</p></section>`;
  } else html += unavailable();
  if (!h.ok) { el.innerHTML = html + unavailable(); return; }
  const days = [...h.data].sort((a, b) => (a.day < b.day ? 1 : -1));
  html += days.length ? `<ul class="days">${days.map((d) => `
    <li class="card day-row ${d.unconsented_ot_hours > 0 ? "flag" : ""}" data-say="${esc(day(d.day))}: ${esc(L("worked"))} ${esc(num(d.worked_hours))}">
      <div class="day-date"><b>${esc(fmtDay(d.day, locale(), { day: "numeric" }))}</b><span>${esc(fmtDay(d.day, locale(), { weekday: "short" }))}</span></div>
      <div class="day-main">
        <div class="day-times">🟢 ${esc(hmOf(d.in))} → 🏠 ${esc(hmOf(d.out))} ${d.corrected ? `<span class="chip warn">✏️ ${esc(L("corrected"))}</span>` : ""}</div>
        <div class="day-nums"><span>⏳ ${esc(L("worked"))} <b>${esc(num(d.worked_hours))}</b> ${esc(L("hours_unit"))}</span>
          ${d.consented_ot_hours ? `<span>✋ ${esc(L("ot_yes"))} <b>${esc(num(d.consented_ot_hours))}</b></span>` : ""}
          ${d.unconsented_ot_hours > 0 ? `<span class="chip crit">⚠️ ${esc(L("ot_no"))} ${esc(num(d.unconsented_ot_hours))} ${esc(L("hours_unit"))}</span>` : ""}</div>
        ${evidenceChips(d.evidence)}
      </div></li>`).join("")}</ul>` : `<div class="card empty">${esc(L("no_hours"))}</div>`;
  el.innerHTML = html;
}

// --- Skills ------------------------------------------------------------------------------
function credParts(c) {
  const vc = c.vc || c.credential || c;
  const sub = vc.credentialSubject || vc.subject || {};
  const skillObj = typeof sub.skill === "object" && sub.skill ? sub.skill : {};
  const skill = skillObj.name || skillObj.skill || (typeof sub.skill === "string" ? sub.skill : "") || sub.operation || c.skill || "";
  const level = skillObj.level || sub.level || c.level || "";
  const id = c.credential_id || c.id || vc.id || "";
  const issued = vc.validFrom || vc.issuanceDate || c.issued_at || c.ts || "";
  return { vc, skill, level, id, issued };
}
async function renderSkills(el) {
  const r = await api(`/passport/${S.wid}`);
  let html = `<h1 class="screen-title">🎓 ${esc(L("skills_title"))}</h1>`;
  if (!r.ok) { el.innerHTML = html + unavailable(); return; }
  const creds = r.data.credentials || [];
  html += creds.length ? creds.map((c) => {
    const { skill, level, id, issued } = credParts(c);
    // Safety inductions carry no ILUO level: show the credential's own label instead.
    const title = level
      ? L("cred_title", { level: term(S.lang, "lv_", level), skill: term(S.lang, "sk_", skill) })
      : ((c.credentialSubject && c.credentialSubject.skillLabel) || String(skill || "").replace(/_/g, " "));
    return `<section class="card cred" data-say="${esc(L("verified_skill"))}: ${esc(title)}">
      <span class="chip ok">✓ ${esc(L("verified_skill"))}</span>
      <h2 class="cred-title">${esc(title)}</h2>
      ${issued ? `<p class="muted small">${esc(L("issued", { date: day(issued) }))}</p>` : ""}
      <img class="qr" alt="${esc(L("verified_skill"))}: ${esc(title)} — QR" width="180" height="180" src="/api/passport/credentials/${encodeURIComponent(id)}/qr">
      <p class="small">${esc(L("scan_note"))}</p>
      <p class="mono small id-line">${esc(id)}</p>
      <a class="btn link-btn" href="/verify/" target="_blank" rel="noopener">🔎 ${esc(L("open_verify"))}</a>
    </section>`;
  }).join("") : `<div class="card empty">${esc(L("no_creds"))}</div>`;
  const prog = r.data.progress || [];
  if (prog.length) {
    html += `<section class="card"><h2>📈 ${esc(L("next_skills"))}</h2><ul class="progress">${prog.map((p) => {
      const needed = p.days_needed || 0, met = p.days_met || 0;
      const pct = needed ? Math.min(100, (met / needed) * 100) : p.met ? 100 : 0;
      const band = p.pay_band || p.band || p.skill_band;
      const title = L("cred_title", { level: term(S.lang, "lv_", p.level), skill: term(S.lang, "sk_", p.skill) });
      return `<li data-say="${esc(title)}: ${esc(L("days_progress", { met, needed }))}">
        <div class="row-between"><b>${p.met ? "✓ " : ""}${esc(title)}</b><span class="small">${esc(L("days_progress", { met, needed }))}</span></div>
        <div class="meter" role="progressbar" aria-label="${esc(title)}" aria-valuemin="0" aria-valuemax="${esc(needed || 100)}" aria-valuenow="${esc(needed ? met : Math.round(pct))}"><i style="width:${pct}%"></i></div>
        ${band || p.pay ? `<div class="small">💰 ${esc(L("pay_band", { band: band ? term(S.lang, "band_", band) : "" }))}${p.pay ? " · " + esc(rupees(p.pay)) : ""}${p.min_wage ? " · " + esc(rupees(p.min_wage)) : ""}</div>` : ""}
        ${p.criteria ? `<div class="small muted">${esc(typeof p.criteria === "string" ? p.criteria : Object.entries(p.criteria).map(([k, v]) => `${k} ${v}`).join(" · "))}${p.current ? ` · now ${esc(typeof p.current === "string" ? p.current : Object.entries(p.current).map(([k, v]) => `${k} ${typeof v === "number" ? num(v, 2) : v}`).join(" · "))}` : ""}</div>` : ""}
      </li>`;
    }).join("")}</ul></section>`;
  }
  el.innerHTML = html;
  el.querySelectorAll("img.qr").forEach((img) => img.addEventListener("error", () => { const d = document.createElement("div"); d.className = "qr qr-missing"; d.textContent = "QR"; d.setAttribute("role", "img"); d.setAttribute("aria-label", img.alt); img.replaceWith(d); }, { once: true }));
}

// --- Voice -------------------------------------------------------------------------------
function loadCases() {
  try { S.voice.cases = JSON.parse(localStorage.getItem("saakshi-cases-" + S.wid) || "[]"); } catch { S.voice.cases = []; }
}
function saveCases() { try { localStorage.setItem("saakshi-cases-" + S.wid, JSON.stringify(S.voice.cases.slice(0, 10))); } catch {} }

async function renderVoice(el) {
  const [topics, board] = await Promise.all([api("/voice/topics"), api("/voice/board")]);
  const V = S.voice;
  const tl = topics.ok ? topics.data.topics || [] : [];
  let html = `<h1 class="screen-title">📣 ${esc(L("voice_title"))}</h1>
    <section class="card anon" data-say><span class="big-icon" aria-hidden="true">🔒</span><p><b>${esc(L("voice_anon"))}</b></p></section>`;
  if (!topics.ok) html += unavailable(L("voice_unavailable"));
  else {
    html += `<section class="card"><h2>${esc(L("step_topic"))}</h2><div class="topics">${tl.map((tp) => {
      const label = (tp.label && (tp.label[S.lang] || tp.label.en)) || tp.id;
      return `<button type="button" class="topic ${V.topic === tp.id ? "sel" : ""}" data-topic="${esc(tp.id)}" aria-pressed="${V.topic === tp.id}">
        <span class="t-icon" aria-hidden="true">${TOPIC_ICON[tp.id] || "💬"}</span><span>${esc(label)}</span>
        ${tp.safety_critical ? `<span class="chip warn">⚠️</span>` : ""}</button>`;
    }).join("")}</div></section>
    <section class="card"><h2>${esc(L("step_text"))}</h2>
      <div class="dictate"><textarea id="vtext" rows="3" placeholder="${esc(L("placeholder"))}">${esc(V.text)}</textarea>
      <button type="button" class="mic small-mic" id="vmic" aria-label="${esc(L("mic"))}">🎤</button></div>
      <button type="button" class="btn primary wide-btn" id="scrubBtn">🧹 ${esc(L("scrub_btn"))}</button>
    </section>
    <section class="card ${V.scrub ? "" : "hidden"}" id="scrubCard"></section>
    <section id="caseCard"></section>`;
  }
  html += `<section class="card"><h2>🤝 ${esc(L("board_title"))}</h2>${!board.ok ? unavailable() :
    board.data.length ? `<ul class="board">${board.data.map((b) => `<li data-say="${esc(L("you_said"))}: ${esc(b.you_said)}. ${esc(L("we_did"))}: ${esc(b.we_did)}">
      <div class="said"><span class="muted small">${TOPIC_ICON[b.topic] || "💬"} ${esc(L("you_said"))}</span><p>${esc(b.you_said)}</p></div>
      <div class="did"><span class="small">✅ ${esc(L("we_did"))}</span><p><b>${esc(b.we_did)}</b></p><span class="muted small">${esc(b.by || "")} · ${esc(day(b.ts))}</span></div></li>`).join("")}</ul>`
      : `<p class="muted">${esc(L("board_empty"))}</p>`}</section>`;
  el.innerHTML = html;
  if (!topics.ok) return;
  el.querySelectorAll("[data-topic]").forEach((b) => (b.onclick = () => {
    V.topic = b.dataset.topic;
    el.querySelectorAll("[data-topic]").forEach((x) => { x.classList.toggle("sel", x === b); x.setAttribute("aria-pressed", x === b); });
  }));
  const ta = $("#vtext");
  ta.oninput = () => { V.text = ta.value; V.scrub = null; $("#scrubCard").classList.add("hidden"); };
  $("#vmic").onclick = () => {
    const btn = $("#vmic");
    if (!SR) { toast(L("mic_unavailable")); return; }
    btn.classList.add("on");
    listen((alts) => { ta.value = (ta.value ? ta.value + " " : "") + alts[0]; V.text = ta.value; }, () => btn.classList.remove("on"));
  };
  $("#scrubBtn").onclick = doScrub;
  if (V.scrub) renderScrub();
  renderCases();
}

async function doScrub() {
  const V = S.voice;
  V.text = $("#vtext").value.trim();
  if (!V.text) { toast(L("write_something")); return; }
  const r = await api("/voice/scrub", { method: "POST", body: { text: V.text } });
  V.scrub = r.ok ? r.data : { suggested: V.text, flags: [], unavailable: true };
  renderScrub();
}
function renderScrub() {
  const V = S.voice, card = $("#scrubCard");
  card.classList.remove("hidden");
  const flags = V.scrub.flags || [];
  card.innerHTML = `<h2>${esc(L("step_check"))}</h2>
    <p class="small">${esc(flags.length ? L("scrub_hint") : L("scrub_clean"))}</p>
    ${flags.length ? `<ul class="flags">${flags.map((f) => `<li><s>${esc(f.span)}</s> <span class="chip warn">⚠️ ${esc(f.reason)}</span></li>`).join("")}</ul>` : ""}
    <textarea id="vfinal" rows="3">${esc(V.scrub.suggested ?? V.text)}</textarea>
    <p class="anon-line small">🔒 ${esc(L("voice_anon"))}</p>
    <button type="button" class="btn primary wide-btn" id="sendBtn">📨 ${esc(L("approve_send"))}</button>`;
  $("#sendBtn").onclick = sendReport;
}
async function sendReport() {
  const V = S.voice;
  if (!V.topic) { toast(L("pick_topic")); return; }
  const text = $("#vfinal").value.trim();
  if (!text) { toast(L("write_something")); return; }
  const SV = window.SaakshiVoice;
  if (!SV || typeof SV.report !== "function") { toast(L("voice_unavailable"), 4000); return; }
  const btn = $("#sendBtn");
  btn.disabled = true;
  try {
    if (typeof SV.hasToken === "function" && !SV.hasToken(V.topic)) {
      btn.textContent = L("getting_tokens");
      await SV.getTokens(S.wid);
    }
    const res = await SV.report(V.topic, text, S.lang);
    if (!res || !res.case_key) throw new Error((res && (res.detail || res.error)) || "no case key");
    V.cases.unshift({ ...res, topic: V.topic, text, at: Date.now() });
    saveCases();
    V.text = ""; V.scrub = null;
    $("#vtext").value = "";
    $("#scrubCard").classList.add("hidden");
    renderCases();
    toast(`${L("case_key")}: ${res.case_key}`, 5000);
  } catch (e) {
    const msg = String((e && e.message) || e);
    toast(/409|spent|already/i.test(msg) ? L("already_sent") : `${L("error")}: ${msg}`, 4500);
    btn.disabled = false;
    btn.textContent = "📨 " + L("approve_send");
  }
}
function statusText(c) {
  if (c.status === "published") return `✅ ${L("st_published", { n: c.corroborations })}`;
  if (c.status === "escalated") return `🚨 ${L("st_escalated")}`;
  return `⏳ ${L("st_waiting", { n: c.corroborations ?? 1, t: c.threshold ?? 3 })}`;
}
function renderCases() {
  const el = $("#caseCard");
  if (!el) return;
  const cs = S.voice.cases.slice(0, 3);
  el.innerHTML = cs.map((c, i) => `<div class="card case ${i === 0 ? "fresh" : ""}">
    <span class="muted small">${TOPIC_ICON[c.topic] || "💬"} ${esc(L("case_key"))}</span>
    <div class="case-key mono">${esc(c.case_key)}</div>
    <p class="small muted">${esc(L("case_key_note"))}</p>
    <p class="case-status" data-say>${esc(statusText(c))}</p>
    ${c.response ? `<p>✅ <b>${esc(typeof c.response === "string" ? c.response : c.response.text || c.response.we_did || "")}</b></p>` : ""}
  </div>`).join("");
}
async function pollCases() {
  const cs = S.voice.cases.slice(0, 3);
  let changed = false;
  for (const c of cs) {
    const r = await api(`/voice/cases/${encodeURIComponent(c.case_key)}`);
    if (r.ok && (r.data.status !== c.status || r.data.corroborations !== c.corroborations || JSON.stringify(r.data.response) !== JSON.stringify(c.response))) {
      Object.assign(c, r.data); changed = true;
    }
  }
  if (changed) { saveCases(); renderCases(); }
}

// --- Rights ------------------------------------------------------------------------------
async function renderRights(el) {
  if (!S.rules) { const r = await api("/rules"); if (r.ok) S.rules = r.data; }
  const band = S.worker ? S.worker.skill_band : "";
  const mw = S.rules && S.rules.min_wage_monthly ? S.rules.min_wage_monthly[band] : null;
  const items = [
    ["💰", mw ? L("r_min_wage", { band: term(S.lang, "band_", band), amount: rupees(mw) }) : L("r_min_wage", { band: term(S.lang, "band_", band), amount: "—" })],
    ["✋", L("r_ot")], ["⏱️", L("r_cap")], ["➖", L("r_deduct")], ["🏁", L("r_fnf")], ["🧾", L("r_receipt")], ["📢", L("r_grievance")],
  ];
  el.innerHTML = `<h1 class="screen-title">⚖️ ${esc(L("rights_title"))}</h1>
    <ul class="rights">${items.map(([i, s]) => `<li class="card" data-say><span class="r-icon" aria-hidden="true">${i}</span><p>${esc(s)}</p></li>`).join("")}</ul>
    ${S.rules ? `<p class="muted small center mono">${esc(S.rules.state || "")} · ${esc(S.rules.version || "")}</p>` : ""}`;
}

// --- Polling -------------------------------------------------------------------------------
async function pollIntegrity() {
  const r = await api(`/workers/${S.wid}/receipts/check`, { method: "POST", body: {} });
  if (!r.ok) return;
  const next = r.data.mismatches || [];
  if (JSON.stringify(next.map((m) => m.seq + m.current_hash)) !== JSON.stringify(S.mismatches.map((m) => m.seq + m.current_hash))) {
    S.mismatches = next;
    S._mismatchChanged = true;
    renderBanner();
    if (S.tab === "pay") renderScreen();
    if (S.tab === "today") refreshReceipts();
  }
}
let polling = false;
async function tick() {
  if (polling) return;
  polling = true;
  try {
    await pollIntegrity();
    if (S.tab === "today") await Promise.all([refreshReceipts(), refreshPending(), refreshAccess()]);
    else await refreshPending();
    if (S.tab === "voice") await pollCases();
  } finally { polling = false; }
}

// --- Boot ----------------------------------------------------------------------------------
async function boot() {
  const [w, all] = await Promise.all([api(`/workers/${S.wid}`), api("/workers")]);
  if (all.ok) all.data.forEach((x) => (S.names[x.id] = x.name));
  S.worker = w.ok ? w.data : { id: S.wid, name: S.wid, lang: "en" };
  let saved = null;
  try { saved = localStorage.getItem("saakshi-lang-" + S.wid); } catch {}
  const q = qs.get("lang");
  S.lang = LANGS.includes(q) ? q : LANGS.includes(saved) ? saved : LANGS.includes(S.worker.lang) ? S.worker.lang : "en";
  loadCases();
  $("#lang").onchange = (e) => {
    S.lang = e.target.value;
    try { localStorage.setItem("saakshi-lang-" + S.wid, S.lang); } catch {}
    renderShell(); renderBanner(); renderScreen();
  };
  $("#tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) setTab(b.dataset.tab); };
  $("#speak").onclick = () => speak(screenSpeech());
  window.addEventListener("hashchange", () => setTab(location.hash.slice(1), false));
  setTab((location.hash || "#today").slice(1), false);
  await pollIntegrity();
  setInterval(tick, POLL_MS);
}
boot();
