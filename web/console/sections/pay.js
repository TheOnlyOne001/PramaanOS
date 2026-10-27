// Pay fairness: the nine fairness checks for the period and a payroll run that holds workers with failed checks.
import { api, esc, rupees, num } from "/shared/api.js";
import { S, $, PERIOD } from "../state.js";
import { na, chip } from "../ui.js";

function payRunTable(x) {
  if (!x.ok) return na(`Payroll not available yet (${x.error})`);
  return `<h2>Payroll run ${x.data.blocked ? chip("crit", "⛔", "Blocked") : chip("ok", "✓", "Completed")}</h2>
    <div class="table-wrap"><table><thead><tr><th>Worker</th><th>Gross</th><th>Net</th><th>Status</th><th>Failed checks</th></tr></thead><tbody>${(x.data.results || []).map((w) => `<tr><td>${esc(w.name)}</td><td>${esc(rupees(w.gross, 2))}</td><td>${esc(rupees(w.net, 2))}</td>
    <td>${w.blocked ? chip("crit", "⛔", "Blocked") : chip("ok", "✓", "OK")}</td><td class="small">${esc((w.failed_checks || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>`;
}

export async function renderPay(m) {
  const r = await api(`/pay/fairness?period=${PERIOD}`);
  m.innerHTML = `<h1>Pay fairness · October 2026</h1>
    <section class="card"><div class="rowb"><h2>Fairness checks</h2><button type="button" class="btn primary" id="runPay">▶ Run payroll</button></div>
    ${r.ok ? `<ul class="checks">${(r.data.checks || []).map((c) => `<li>${c.ok ? chip("ok", "✓", "Pass") : chip("crit", "✗", "Fail")} <div><b>${esc(c.name)}</b><div class="small muted">${esc(c.detail || "")}</div>
      ${(c.workers || []).length ? `<div class="small">👥 ${esc(c.workers.map((w) => S.names[w] || w).join(", "))}</div>` : ""}</div></li>`).join("")}</ul>
      ${r.data.ot_gini != null ? `<p class="small">Overtime spread (Gini): <b>${esc(num(r.data.ot_gini, 2))}</b></p>` : ""}` : na("Pay fairness not available yet")}</section>
    <section class="card" id="payRun" aria-live="polite">${S.payRun || ""}</section>`;
  $("#runPay").onclick = async () => {
    S.payRun = payRunTable(await api(`/pay/run?period=${PERIOD}`, { method: "POST" }));
    $("#payRun").innerHTML = S.payRun;
  };
}
