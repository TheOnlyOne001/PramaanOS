// Voice screen: anonymous, corroborated reports (blind-signature tokens via window.SaakshiVoice),
// a scrub step that removes identifying details, case keys she keeps, and the "You said, we did" board.
import { api, esc, toast } from "/shared/api.js";
import { S, L, $, day } from "../state.js";
import { TOPIC_ICON, unavailable } from "../ui.js";
import { SR, listen } from "../speech.js";

const casesKey = () => "saakshi-cases-" + S.wid;

export function loadCases() {
  try { S.voice.cases = JSON.parse(localStorage.getItem(casesKey()) || "[]"); } catch { S.voice.cases = []; }
}
function saveCases() {
  try { localStorage.setItem(casesKey(), JSON.stringify(S.voice.cases.slice(0, 10))); } catch { /* storage off */ }
}

function topicButton(tp) {
  const V = S.voice;
  const label = (tp.label && (tp.label[S.lang] || tp.label.en)) || tp.id;
  return `<button type="button" class="topic ${V.topic === tp.id ? "sel" : ""}" data-topic="${esc(tp.id)}" aria-pressed="${V.topic === tp.id}">
    <span class="t-icon" aria-hidden="true">${TOPIC_ICON[tp.id] || "💬"}</span><span>${esc(label)}</span>
    ${tp.safety_critical ? `<span class="chip warn">⚠️</span>` : ""}</button>`;
}

function boardCard(board) {
  if (!board.ok) return unavailable();
  if (!board.data.length) return `<p class="muted">${esc(L("board_empty"))}</p>`;
  return `<ul class="board">${board.data.map((b) => `<li data-say="${esc(L("you_said"))}: ${esc(b.you_said)}. ${esc(L("we_did"))}: ${esc(b.we_did)}">
    <div class="said"><span class="muted small">${TOPIC_ICON[b.topic] || "💬"} ${esc(L("you_said"))}</span><p>${esc(b.you_said)}</p></div>
    <div class="did"><span class="small">✅ ${esc(L("we_did"))}</span><p><b>${esc(b.we_did)}</b></p><span class="muted small">${esc(b.by || "")} · ${esc(day(b.ts))}</span></div></li>`).join("")}</ul>`;
}

export async function renderVoice(el) {
  const [topics, board] = await Promise.all([api("/voice/topics"), api("/voice/board")]);
  const V = S.voice;
  let html = `<h1 class="screen-title">📣 ${esc(L("voice_title"))}</h1>
    <section class="card anon" data-say><span class="big-icon" aria-hidden="true">🔒</span><p><b>${esc(L("voice_anon"))}</b></p></section>`;
  if (!topics.ok) html += unavailable(L("voice_unavailable"));
  else {
    html += `<section class="card"><h2>${esc(L("step_topic"))}</h2><div class="topics">${(topics.data.topics || []).map(topicButton).join("")}</div></section>
    <section class="card"><h2>${esc(L("step_text"))}</h2>
      <div class="dictate"><textarea id="vtext" rows="3" placeholder="${esc(L("placeholder"))}">${esc(V.text)}</textarea>
      <button type="button" class="mic small-mic" id="vmic" aria-label="${esc(L("mic"))}">🎤</button></div>
      <button type="button" class="btn primary wide-btn" id="scrubBtn">🧹 ${esc(L("scrub_btn"))}</button>
    </section>
    <section class="card ${V.scrub ? "" : "hidden"}" id="scrubCard"></section>
    <section id="caseCard"></section>`;
  }
  html += `<section class="card"><h2>🤝 ${esc(L("board_title"))}</h2>${boardCard(board)}</section>`;
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
    <textarea id="vfinal" rows="3" aria-label="${esc(L("step_check"))}">${esc(V.scrub.suggested ?? V.text)}</textarea>
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

function responseText(r) {
  return typeof r === "string" ? r : r.text || r.we_did || "";
}

function renderCases() {
  const el = $("#caseCard");
  if (!el) return;
  el.innerHTML = S.voice.cases.slice(0, 3).map((c, i) => `<div class="card case ${i === 0 ? "fresh" : ""}">
    <span class="muted small">${TOPIC_ICON[c.topic] || "💬"} ${esc(L("case_key"))}</span>
    <div class="case-key mono">${esc(c.case_key)}</div>
    <p class="small muted">${esc(L("case_key_note"))}</p>
    <p class="case-status" data-say>${esc(statusText(c))}</p>
    ${c.response ? `<p>✅ <b>${esc(responseText(c.response))}</b></p>` : ""}
  </div>`).join("");
}

/** Refresh the status of her last three cases (called by the poller on this tab). */
export async function pollCases() {
  let changed = false;
  for (const c of S.voice.cases.slice(0, 3)) {
    const r = await api(`/voice/cases/${encodeURIComponent(c.case_key)}`);
    if (r.ok && (r.data.status !== c.status || r.data.corroborations !== c.corroborations || JSON.stringify(r.data.response) !== JSON.stringify(c.response))) {
      Object.assign(c, r.data); changed = true;
    }
  }
  if (changed) { saveCases(); renderCases(); }
}
