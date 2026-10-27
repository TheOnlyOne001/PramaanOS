// Console integrity banner: re-verifies the ledger every poll and raises an alert the moment a signed row changes.
import { api, esc, hm, fmtDay, num } from "/shared/api.js";
import { S, $, DEMO_DAY } from "./state.js";
import { setHTML } from "./ui.js";

/** One readable line per verification problem. */
export function problemsText(v) {
  return (v.problems || []).map((p) => {
    if (p.kind === "root_mismatch") return `published root for ${fmtDay(p.ts || DEMO_DAY)} no longer matches`;
    if (p.kind === "content_edited") return `${p.worker_name || p.worker_id || "Site"} · ${p.type} #${p.seq} edited after signing`;
    return `${p.worker_name ? p.worker_name + " · " : ""}${p.type || ""}${p.seq != null ? " #" + p.seq : ""} ${String(p.kind).replace(/_/g, " ")}`;
  }).join(" · ");
}

export async function pollVerify() {
  const r = await api("/ledger/verify");
  const el = $("#integrity");
  if (!r.ok) {
    el.className = "integrity checking";
    el.innerHTML = `<div class="int-row"><span class="int-icon" aria-hidden="true">…</span><div class="int-text"><b>Ledger check unavailable</b> <span>${esc(r.error)}</span></div></div>`;
    return;
  }
  const v = r.data; S.verify = v; S.lastPoll = Date.now();
  if (v.ok) {
    const today = (v.roots || []).find((x) => x.day === DEMO_DAY);
    const pub = today && today.published;
    el.className = "integrity ok";
    setHTML(el, `<div class="int-row"><span class="int-icon" aria-hidden="true">✓</span><div class="int-text"><b>Ledger verified</b> · ${esc(num(v.n_events, 0))} events · ${pub ? "today's root published" : "today's root not yet published"}
      <span class="mono small">head ${esc(String(v.head || "").slice(0, 12))} · checked ${esc(hm(v.checked_at))}</span></div><button type="button" class="btn light" data-roots>Daily roots</button></div>`);
    S.wasBad = false; S.lastOkAt = v.checked_at; S.detected = {}; S.flip = null; document.title = "Saakshi Console";
    return;
  }
  // Remember when each problem was first seen, so the evidence dialog can show a timeline.
  for (const p of v.problems || []) { const k = p.seq ?? "root:" + p.ts; if (!S.detected[k]) S.detected[k] = v.checked_at; }
  const first = (v.problems || []).find((p) => p.worker_id);
  if (!S.wasBad && S.lastOkAt) S.flip = { okAt: S.lastOkAt, badAt: v.checked_at }; // verified → edited while watching
  el.className = "integrity bad" + (S.wasBad && !el.classList.contains("flash") ? "" : " flash");
  setHTML(el, `<div class="int-row"><span class="int-icon" aria-hidden="true">⚠</span><div class="int-text">
      <b class="int-title">Integrity alert</b><div class="int-detail">${esc(problemsText(v))}</div>
      ${S.flip ? `<span class="int-flip"><span class="chip ok">✓ Verified at ${esc(hm(S.flip.okAt))}</span> <span aria-hidden="true">→</span> <span class="chip crit">⚠ Edit caught at ${esc(hm(S.flip.badAt))}</span></span>` : ""}
      <span class="small">Detected ${esc(hm(S.detected[first ? first.seq : ""] || v.checked_at))} · payroll for affected workers is blocked · ${esc(v.n_events)} events checked</span></div>
      <div class="int-actions">${first ? `<button type="button" class="btn light" data-open="${esc(first.worker_id)}">Open ${esc(first.worker_name || first.worker_id)}'s record</button>` : ""}<button type="button" class="btn light" data-roots>Daily roots</button></div></div>
    <details class="int-hashes"><summary>Show hashes</summary>${(v.problems || []).map((p) => `<div class="mono small">#${esc(p.seq ?? "root")} ${esc(p.kind)} · stored ${esc(String(p.stored_hash || "").slice(0, 16))} · now ${esc(String(p.recomputed_hash || "").slice(0, 16))}</div>`).join("")}</details>`);
  if (!S.wasBad) {
    document.body.classList.add("alarm");
    setTimeout(() => { document.body.classList.remove("alarm"); el.classList.remove("flash"); }, 1600);
  }
  S.wasBad = true; document.title = "⚠ Integrity alert · Saakshi";
}
