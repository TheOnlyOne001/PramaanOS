// Pay screen: this month's payslip, explained in her language, held if any of her records fails verification.
import { api, esc, fmtDay, rupees } from "/shared/api.js";
import { S, L, $, PERIOD, locale } from "../state.js";
import { unavailable, evidenceChips } from "../ui.js";
import { speak } from "../speech.js";

const firstSeg = (s) => String(s || "").split(" · ")[0];

function blockedCard() {
  return `<section class="card blocked" data-say>
    <div class="blocked-head"><span aria-hidden="true">⛔</span><b>${esc(L("blocked_title"))}</b></div>
    <p>${esc(L("blocked_body"))}</p>
    ${S.mismatches.map((m) => `<p class="small"><span class="mono">#${esc(m.seq)} · ${esc(m.ref || "")}</span> ${esc(firstSeg(m.receipt_text))} → ${esc(firstSeg(m.current_text))}</p>`).join("")}
  </section>`;
}

function lineList(lines, sign = "") {
  return lines.map((ln) => `<li><div class="row-between"><span>${esc(ln.label)}</span><b>${sign}${esc(rupees(ln.amount, 2))}</b></div>
    ${ln.formula ? `<div class="formula mono">${esc(ln.formula)}</div>` : ""}${evidenceChips(ln.evidence)}</li>`).join("");
}

export async function renderPay(el) {
  const r = await api(`/pay/${S.wid}/payslip?period=${PERIOD}`);
  const period = fmtDay(PERIOD + "-01", locale(), { month: "long", year: "numeric" });
  const tampered = S.mismatches.length > 0;
  const head = `<h1 class="screen-title">💰 ${esc(L("payslip_title", { period }))}</h1>`;
  if (!r.ok) { el.innerHTML = head + (tampered ? blockedCard() : "") + unavailable(); return; }
  const p = r.data;
  const blocked = p.blocked || tampered;
  const expl = (p.explanation && (p.explanation[S.lang] || p.explanation.en)) || "";
  el.innerHTML = `${head}
    ${blocked ? blockedCard() : ""}
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
      <ul class="lines">${lineList(p.lines || [])}</ul>
    </section>
    <section class="card">
      <h2>➖ ${esc(L("deductions"))} <span class="right">${esc(rupees(p.total_deductions, 2))}</span></h2>
      <ul class="lines">${lineList(p.deductions || [], "− ") || `<li class="muted">—</li>`}</ul>
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
