// SDG 8 scorecard: decent-work indicators (targets 8.2 to 8.8) computed from the signed ledger.
import { api, esc, num } from "/shared/api.js";
import { na, chip } from "../ui.js";

const statusChip = (s) => /on|ok|good|met|green/i.test(s) ? ["ok", "✓"] : /risk|warn|watch|amber/i.test(s) ? ["warn", "⚠"] : /off|bad|red|fail/i.test(s) ? ["crit", "✗"] : ["neutral", "•"];

function targetCard(t) {
  const [c, i] = statusChip(String(t.status));
  return `<article class="card sdg-card"><span class="mono">Target ${esc(t.target)}</span><h2>${esc(t.label)}</h2>
    <div class="sdg-val">${esc(typeof t.value === "number" ? num(t.value, 2) : t.value)} <small>${esc(t.unit || "")}</small></div><p class="small muted">${esc(t.indicator)}</p>${chip(c, i, String(t.status).replace(/_/g, " "))}</article>`;
}

export async function renderSdg(m) {
  const r = await api("/sdg8/scorecard");
  m.innerHTML = `<h1>SDG 8 scorecard</h1><p class="muted">Decent work and economic growth, computed from the signed ledger.</p>
    ${r.ok ? `<div class="sdg">${(r.data.targets || []).map(targetCard).join("")}</div>` : na("SDG 8 scorecard not available yet")}`;
}
