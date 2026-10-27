// Rights screen: her rights under the labour codes, with the minimum wage for her skill band.
import { api, esc, rupees } from "/shared/api.js";
import { term } from "/shared/i18n.js";
import { S, L } from "../state.js";

export async function renderRights(el) {
  if (!S.rules) { const r = await api("/rules"); if (r.ok) S.rules = r.data; }
  const band = S.worker ? S.worker.skill_band : "";
  const mw = S.rules && S.rules.min_wage_monthly ? S.rules.min_wage_monthly[band] : null;
  const items = [
    ["💰", L("r_min_wage", { band: term(S.lang, "band_", band), amount: mw ? rupees(mw) : "—" })],
    ["✋", L("r_ot")], ["⏱️", L("r_cap")], ["➖", L("r_deduct")], ["🏁", L("r_fnf")], ["🧾", L("r_receipt")], ["📢", L("r_grievance")],
  ];
  el.innerHTML = `<h1 class="screen-title">⚖️ ${esc(L("rights_title"))}</h1>
    <ul class="rights">${items.map(([i, s]) => `<li class="card" data-say><span class="r-icon" aria-hidden="true">${i}</span><p>${esc(s)}</p></li>`).join("")}</ul>
    ${S.rules ? `<p class="muted small center mono">${esc(S.rules.state || "")} · ${esc(S.rules.version || "")}</p>` : ""}`;
}
