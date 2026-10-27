// Skills coverage: who holds which verified skill, from /passport/coverage or each worker's passport.
import { api, esc } from "/shared/api.js";
import { S } from "../state.js";
import { na, chip } from "../ui.js";

function genericTable(rows) {
  return `<div class="table-wrap"><table><thead><tr>${Object.keys(rows[0]).map((k) => `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>${rows.map((x) => `<tr>${Object.values(x).map((v) => `<td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function credChip(c) {
  const s = (c.vc || c).credentialSubject || {};
  const skill = typeof s.skill === "string" ? s.skill : (s.skill && s.skill.name) || c.skill;
  return chip("ok", "✓", [s.level || c.level, skill].filter(Boolean).join(" · ") || "credential");
}

async function perWorkerTable() {
  const ps = await Promise.all(S.workers.filter((w) => !w.is_supervisor).map(async (w) => [w, await api(`/passport/${w.id}`)]));
  if (!ps.some(([, p]) => p.ok)) return na("Skills coverage not available yet");
  return `<div class="table-wrap"><table><thead><tr><th>Worker</th><th>Verified skills</th><th>In progress</th></tr></thead><tbody>${ps.map(([w, p]) => `<tr><td>${esc(w.name)}</td>
    <td>${p.ok ? (p.data.credentials || []).map(credChip).join(" ") : "—"}</td>
    <td class="small">${p.ok ? (p.data.progress || []).map((g) => `${esc(g.skill)} ${esc(g.level)} ${esc(g.days_met ?? 0)}/${esc(g.days_needed ?? "?")} d`).join(" · ") : "—"}</td></tr>`).join("")}</tbody></table></div>`;
}

export async function renderSkills(m) {
  const r = await api("/passport/coverage");
  let body;
  if (r.ok) {
    const rows = Array.isArray(r.data) ? r.data : r.data.skills || r.data.coverage || [];
    body = Array.isArray(rows) && rows.length ? genericTable(rows) : `<pre class="mono small">${esc(JSON.stringify(r.data, null, 1))}</pre>`;
  } else body = await perWorkerTable();
  m.innerHTML = `<h1>Skills coverage</h1><section class="card">${body}</section>`;
}
