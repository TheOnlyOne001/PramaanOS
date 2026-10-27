// Today screen: shift summary, overtime requests with voice consent, receipt feed, who looked at my record.
import { api, esc, hm, fmtDay, rupees, num, toast } from "/shared/api.js";
import { matchAnswer } from "/shared/i18n.js";
import { S, L, $, DEMO_DAY, locale, day, nameOf, firstName } from "../state.js";
import { typeIcon, unavailable, refChip, hmOf } from "../ui.js";
import { icon } from "../icons.js";
import { keepReceipts } from "../store.js";
import { SR, listen } from "../speech.js";
import { renderShell } from "../shell.js";

export async function renderToday(el) {
  el.innerHTML = `
    <section id="shift" class="card shift" aria-busy="true"></section>
    <button type="button" class="hazard" id="hazard">${icon("stop")} ${esc(L("hazard"))}</button>
    <section id="ot"></section>
    <section class="card chat-card">
      <h2>${icon("receipt")} ${esc(L("receipts_title"))}</h2>
      <p class="muted small" data-say>${esc(L("receipts_sub"))}</p>
      <p class="copy-line" id="copyLine" role="status"></p>
      <div class="chat" id="chat" role="log" tabindex="0" aria-label="${esc(L("receipts_title"))}"></div>
    </section>
    <section class="card" id="access"></section>
    <details class="demo" id="demo">
      <summary>${icon("flask")} ${esc(L("demo_controls"))}</summary>
      <div class="demo-row">
        <input type="time" id="punchTime" aria-label="time">
        <button type="button" class="btn" data-punch="in">${icon("login")} ${esc(L("punch_in"))}</button>
        <button type="button" class="btn" data-punch="out">${icon("logout")} ${esc(L("punch_out"))}</button>
      </div>
      <div class="demo-row"><button type="button" class="btn" id="simYes">${icon("mic")} “ஆம்”</button>
        <button type="button" class="btn" id="simNo">${icon("mic")} “இல்லை”</button></div>
    </details>`;
  $("#hazard").onclick = () => toast(L("hazard_toast"), 4500);
  el.querySelectorAll("[data-punch]").forEach((b) => (b.onclick = () => doPunch(b.dataset.punch)));
  $("#simYes").onclick = () => S.pending[0] && consent(S.pending[0], "accept", "voice", "ஆம்");
  $("#simNo").onclick = () => S.pending[0] && consent(S.pending[0], "decline", "voice", "இல்லை");
  S.seenSeqs = null;
  renderCopyLine();
  await Promise.all([refreshReceipts().then(refreshShift), refreshPending(true), refreshAccess()]);
}

/** "42 receipts saved on this phone · Checked against the copy on your phone". */
export function renderCopyLine() {
  const el = $("#copyLine");
  if (!el) return;
  const parts = [L("my_copy_count", { n: S.held })];
  if (S.checkSource) parts.push(L(S.checkSource === "phone" ? "check_local" : "check_server"));
  if (S.checkSource && !S.mismatches.length && S.checked) parts.push(L("check_all_ok", { n: S.checked }));
  el.className = `copy-line ${S.mismatches.length ? "bad" : S.checkSource ? "ok" : ""}`;
  el.innerHTML = `${icon(S.mismatches.length ? "alert" : "shield")}<span>${parts.map(esc).join(" · ")}</span>`;
}

function stat(ic, label, value, extra = "", say = "", cls = "") {
  return `<div class="stat ${cls}" data-say="${esc(say)}"><span class="stat-icon">${icon(ic)}</span>
    <span class="stat-label">${esc(label)}</span>${value}${extra}</div>`;
}

async function refreshShift() {
  const el = $("#shift");
  if (!el) return;
  const r = await api(`/pay/${S.wid}/today?day=${DEMO_DAY}`);
  const d = r.ok ? r.data : null;
  // Fallback: today's punches from my own receipts.
  const todays = S.receipts.filter((x) => (x.ts || "").startsWith(DEMO_DAY));
  const inR = todays.filter((x) => x.type === "punch.in").sort((a, b) => a.seq - b.seq)[0];
  const outR = todays.filter((x) => x.type === "punch.out").sort((a, b) => b.seq - a.seq)[0];
  const inTs = d ? d.in : inR && inR.ts;
  const outTs = d ? d.out : outR && outR.ts;
  const worked = d ? d.worked_hours : null;
  const earned = d ? d.earned_today : null;
  const hours = (n) => `${esc(num(n))} ${esc(L("hours_unit"))}`;
  const head = `<div class="shift-head"><h2>${icon("sun")} ${esc(L("today_shift"))}</h2><span class="muted">${esc(fmtDay(DEMO_DAY, locale(), { weekday: "short", day: "numeric", month: "long" }))}</span></div>`;
  el.setAttribute("aria-busy", "false");
  if (!inTs) { el.innerHTML = `${head}<p class="big-empty" data-say>${esc(L("not_in_yet"))}</p>`; return; }
  const inStat = stat("login", L("in"), `<b class="stat-val">${esc(hmOf(inTs))}</b>`, inR ? refChip(inR.seq, inR.ref) : "", `${L("in")} ${hmOf(inTs)}`);
  const outStat = outTs
    ? stat("logout", L("out"), `<b class="stat-val">${esc(hmOf(outTs))}</b>`, outR ? refChip(outR.seq, outR.ref) : "", `${L("out")} ${hmOf(outTs)}`)
    : stat("hourglass", L("hours_so_far"), `<b class="stat-val">${worked !== null ? hours(worked) : "—"}</b>`, "", `${L("hours_so_far")} ${num(worked)}`);
  const money = earned !== null && earned !== undefined ? esc(rupees(earned, 2)) : `<small class="muted">${esc(L("not_available"))}</small>`;
  const extra = `${d && d.ot_hours ? `<span class="muted small inline-ic">${icon("clock")} ${esc(L("ot_short"))} ${hours(d.ot_hours)} · ${esc(rupees(d.ot_earned, 2))}</span>` : ""}
    ${outTs && worked !== null ? `<span class="muted small inline-ic">${icon("hourglass")} ${hours(worked)}</span>` : ""}`;
  el.innerHTML = `${head}<div class="stats">${inStat}${outStat}
    ${stat("rupee", L("earned_today"), `<b class="stat-val money">${money}</b>`, extra, `${L("earned_today")} ${earned !== null ? rupees(earned) : ""}`, "wide")}</div>`;
}

async function refreshReceipts() {
  const r = await api(`/workers/${S.wid}/receipts?limit=40`);
  if (!r.ok) { const c = $("#chat"); if (c && !c.childElementCount) c.innerHTML = unavailable(); return; }
  await keepReceipts(r.data);
  const prevSeen = S.seenSeqs;
  const changed = JSON.stringify(r.data.map((x) => x.seq)) !== JSON.stringify(S.receipts.map((x) => x.seq));
  S.receipts = r.data;
  const chat = $("#chat");
  if (!chat) return;
  if (!changed && chat.childElementCount && !S.mismatchChanged) return;
  S.mismatchChanged = false;
  const items = [...r.data].reverse().slice(-14);
  if (!items.length) { chat.innerHTML = `<p class="muted center">${esc(L("no_receipts"))}</p>`; return; }
  const bad = new Set(S.mismatches.map((m) => m.seq));
  const own = S.worker && S.lang === S.worker.lang;
  let lastDay = "";
  chat.innerHTML = items.map((x) => {
    const d = (x.ts || "").slice(0, 10);
    const sep = d !== lastDay ? `<div class="day-sep"><span>${esc(day(d))}</span></div>` : "";
    lastDay = d;
    const isNew = prevSeen && !prevSeen.has(x.seq);
    return `${sep}<div class="bubble ${bad.has(x.seq) ? "changed" : ""} ${isNew ? "new" : ""}">
      <div class="b-text">${typeIcon(x.type)} ${esc(own ? x.text : x.text_en)}</div>
      ${own && S.lang !== "en" ? `<div class="b-sub">${esc(x.text_en)}</div>` : ""}
      ${bad.has(x.seq) ? `<div class="b-flag">${icon("alert")} ${esc(L("integrity_title"))}</div>` : ""}
      <div class="b-meta"><span class="mono">#${esc(x.seq)} · ${esc(x.ref)}</span><span>${esc(hm(x.ts))}</span><span class="ticks">${icon("check")}</span></div>
    </div>`;
  }).join("");
  S.seenSeqs = new Set(r.data.map((x) => x.seq));
  chat.scrollTop = chat.scrollHeight;
  const newPunch = prevSeen && S.receipts.some((x) => !prevSeen.has(x.seq) && x.type.startsWith("punch."));
  if (newPunch) refreshShift();
}

async function refreshAccess() {
  const el = $("#access");
  if (!el) return;
  const r = await api(`/workers/${S.wid}/access-log`);
  const head = `<h2>${icon("eye")} ${esc(L("access_title"))}</h2>`;
  if (!r.ok) { el.innerHTML = head + unavailable(); return; }
  if (!r.data.length) { el.innerHTML = head + `<p class="muted" data-say>${esc(L("access_none"))}</p>`; return; }
  el.innerHTML = head + `<ul class="list">${r.data.slice(0, 6).map((a) => `
    <li data-say="${esc(nameOf(a.viewer))}: ${esc(a.reason)}"><span class="li-icon">${icon("eye")}</span>
      <div><b>${esc(nameOf(a.viewer))}</b> <span class="muted small">${esc(a.viewer_role || "")}</span>
      <div class="small">${esc(L("reason"))}: ${esc(a.reason)}</div></div>
      <span class="muted small right">${esc(day(a.ts))} ${esc(hm(a.ts))}</span></li>`).join("")}</ul>`;
}

const findPending = (id) => S.pending.find((p) => String(p.request_id) === String(id));

export async function refreshPending(force = false) {
  const r = await api(`/ot/requests?worker_id=${S.wid}&status=pending`);
  const list = r.ok && Array.isArray(r.data) ? r.data.filter((x) => x.status === "pending" || !x.status) : [];
  const changed = JSON.stringify(list.map((x) => x.request_id)) !== JSON.stringify(S.pending.map((x) => x.request_id));
  S.pending = list;
  if (changed) renderShell();
  const el = $("#ot");
  if (!el || S.listening) return;
  if (!changed && !force && !S.consentDirty) return;
  S.consentDirty = false;
  let html = "";
  if (S.consentResult) {
    const c = S.consentResult;
    html += `<div class="card consent-done ${c.decision}" data-say>
      <span class="big-icon">${icon(c.decision === "accept" ? "check" : "x")}</span>
      <p><b>${esc(L(c.decision === "accept" ? "accepted_msg" : "declined_msg", { ref: c.ref || "" }))}</b></p></div>`;
  }
  html += list.map(otCard).join("");
  el.innerHTML = html;
  el.querySelectorAll("[data-consent]").forEach((b) => {
    b.onclick = () => consent(findPending(b.dataset.req), b.dataset.consent, "tap");
  });
  el.querySelectorAll("[data-mic]").forEach((b) => (b.onclick = () => micConsent(b.dataset.req, b)));
}

function otCard(p) {
  const by = firstName(p.requested_by) || "Supervisor";
  const cap = p.cap || {};
  const pct = cap.cap ? Math.min(100, ((cap.used || 0) / cap.cap) * 100) : 0;
  const id = esc(p.request_id);
  return `<article class="card ot-card" aria-live="polite">
    <div class="ot-head"><span class="ot-icon">${icon("clock")}</span><h2>${esc(L("ot_req_title"))}</h2></div>
    <p class="ot-body" data-say>${esc(L("ot_req_body", { by, hours: num(p.hours), date: day(p.date) }))}</p>
    <div class="ot-facts">
      <span class="chip info">${icon("rupee")} ${esc(L("ot_paid_double"))} ×2</span>
      ${cap.cap ? `<span class="chip neutral">${icon("clock")} ${esc(L("cap_line", { used: num(cap.used), cap: num(cap.cap, 0) }))}</span>` : ""}
    </div>
    ${cap.cap ? `<div class="meter ${pct > 90 ? "crit" : pct > 75 ? "warn" : ""}" role="meter" aria-label="${esc(L("ot_req_title"))}" aria-valuemin="0" aria-valuenow="${cap.used}" aria-valuemax="${cap.cap}"><i style="width:${pct}%"></i></div>` : ""}
    <p class="ot-choice" data-say>${icon("hand")} ${esc(L("ot_choice"))}</p>
    <div class="mic-row">
      <button type="button" class="mic" data-mic data-req="${id}" aria-label="${esc(L("mic"))}">${icon("mic")}</button>
      <div class="mic-hint" id="mic-hint-${id}">${esc(SR ? L("say_answer") : L("mic_unavailable"))}</div>
    </div>
    <div class="answer-row">
      <button type="button" class="answer yes" data-consent="accept" data-req="${id}"><span class="a-icon">${icon("check")}</span>${esc(L("accept"))}</button>
      <button type="button" class="answer no" data-consent="decline" data-req="${id}"><span class="a-icon">${icon("x")}</span>${esc(L("decline"))}</button>
    </div>
  </article>`;
}

function micConsent(reqId, btn) {
  const hint = document.getElementById("mic-hint-" + reqId);
  const req = findPending(reqId);
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
  S.consentDirty = true;
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

/** Called by the poller while the Today tab is open. */
export const refreshToday = () => Promise.all([refreshReceipts(), refreshPending(), refreshAccess()]);
/** Re-draw the receipt feed (e.g. after a mismatch appears). */
export { refreshReceipts };
