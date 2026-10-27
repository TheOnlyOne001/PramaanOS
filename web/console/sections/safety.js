// Safety & cameras: live edge events (no video ever leaves the site), today's events by zone, camera register.
import { api, esc, hm, num } from "/shared/api.js";
import { $, DEMO_DAY } from "../state.js";
import { na, ev, KIND, zoneName } from "../ui.js";

/** One camera event card (also used on the overview). */
export function edgeCard(e) {
  return `<article class="edge-card"><div><b>${esc(zoneName(e.zone))} · ${esc(KIND[e.kind] || e.kind)} · ${esc(e.camera)}</b>
    ${e.count != null ? `<span class="small"> · count ${esc(e.count)}</span>` : ""}${e.value != null ? `<span class="small"> · value ${esc(num(e.value, 2))}</span>` : ""}</div>
    <div class="small muted">🔒 no video or face left the box · ${esc(hm(e.ts))} ${ev(e.seq)}</div></article>`;
}

export async function renderSafety(m) {
  const [sum, cams] = await Promise.all([api(`/edge/summary?day=${DEMO_DAY}`), api("/edge/cameras")]);
  m.innerHTML = `<h1>Safety &amp; cameras</h1><p class="notice">🔒 Video never leaves the site. Only events and counts.</p>
    <div class="grid2"><section class="card"><h2>Live events <span class="muted small">live</span></h2><div class="feed" id="feed">${na("Loading…")}</div></section>
    <section class="card"><h2>Today by zone</h2>${sum.ok ? `<ul class="checks">${(sum.data.zones || []).map((z) => `<li><b>${esc(zoneName(z.zone))}</b> <span class="small">${esc(Object.entries(z.events || {}).map(([k, n]) => `${KIND[k] || k}: ${n}`).join(" · "))}</span></li>`).join("")}</ul>` : na("Edge summary not available yet")}</section></div>
    <section class="card"><h2>Camera register</h2>${cams.ok ? `<div class="table-wrap"><table><thead><tr><th>Camera</th><th>Zone</th><th>Purpose</th><th>Owner</th><th>Retention</th></tr></thead><tbody>${cams.data.map((c) => `<tr><td class="mono">${esc(c.camera)}</td><td>${esc(c.zone)}</td><td>${esc(c.purpose)}</td><td>${esc(c.owner)}</td><td>${esc(c.retention_hours)} h</td></tr>`).join("")}</tbody></table></div>` : na("Camera register not available yet")}</section>`;
  refreshFeed();
}

export async function refreshFeed() {
  const el = $("#feed"); if (!el) return;
  const r = await api("/edge/events?limit=20");
  el.innerHTML = r.ok ? r.data.map(edgeCard).join("") || `<p class="muted">No events yet.</p>` : na("Edge events not available yet");
}
