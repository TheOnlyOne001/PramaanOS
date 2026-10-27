// Hours screen: quarterly overtime cap and day-by-day signed hours, flagging overtime without consent.
import { api, esc, fmtDay, num } from "/shared/api.js";
import { S, L, DEMO_DAY, HOURS_FROM, locale, day } from "../state.js";
import { unavailable, evidenceChips, hmOf } from "../ui.js";

const CAP_STATE = { over: ["crit", "⛔"], near: ["warn", "⚠️"] };

function capCard(row) {
  const pct = Math.min(100, (row.used / (row.cap || 144)) * 100);
  const [cls, icon] = CAP_STATE[row.status] || ["ok", "✓"];
  const line = L("cap_line", { used: num(row.used), cap: num(row.cap, 0) });
  return `<section class="card" data-say="${esc(L("cap_title"))}: ${esc(line)}">
    <h2>📊 ${esc(L("cap_title"))}</h2>
    <div class="cap-big"><b>${esc(num(row.used))}</b><span>/ ${esc(num(row.cap, 0))} ${esc(L("hours_unit"))}</span>
      <span class="chip ${cls}">${icon} ${esc(Math.round(pct))}%</span></div>
    <div class="meter ${cls === "ok" ? "" : cls}"><i style="width:${pct}%"></i></div>
    <p class="small">${esc(L("cap_left", { remaining: num(row.remaining), cap: num(row.cap, 0) }))}</p>
    <p class="muted small">${esc(L("cap_note"))}</p></section>`;
}

function dayRow(d) {
  return `<li class="card day-row ${d.unconsented_ot_hours > 0 ? "flag" : ""}" data-say="${esc(day(d.day))}: ${esc(L("worked"))} ${esc(num(d.worked_hours))}">
    <div class="day-date"><b>${esc(fmtDay(d.day, locale(), { day: "numeric" }))}</b><span>${esc(fmtDay(d.day, locale(), { weekday: "short" }))}</span></div>
    <div class="day-main">
      <div class="day-times">🟢 ${esc(hmOf(d.in))} → 🏠 ${esc(hmOf(d.out))} ${d.corrected ? `<span class="chip warn">✏️ ${esc(L("corrected"))}</span>` : ""}</div>
      <div class="day-nums"><span>⏳ ${esc(L("worked"))} <b>${esc(num(d.worked_hours))}</b> ${esc(L("hours_unit"))}</span>
        ${d.consented_ot_hours ? `<span>✋ ${esc(L("ot_yes"))} <b>${esc(num(d.consented_ot_hours))}</b></span>` : ""}
        ${d.unconsented_ot_hours > 0 ? `<span class="chip crit">⚠️ ${esc(L("ot_no"))} ${esc(num(d.unconsented_ot_hours))} ${esc(L("hours_unit"))}</span>` : ""}</div>
      ${evidenceChips(d.evidence)}
    </div></li>`;
}

export async function renderHours(el) {
  const [h, cap] = await Promise.all([api(`/hours/${S.wid}?from=${HOURS_FROM}&to=${DEMO_DAY}`), api(`/ot/cap?date=${DEMO_DAY}`)]);
  let html = `<h1 class="screen-title">⏱️ ${esc(L("hours_title"))}</h1>
    <p class="muted">${esc(L("hours_range", { from: day(HOURS_FROM), to: day(DEMO_DAY) }))}</p>`;
  const row = cap.ok && Array.isArray(cap.data) ? cap.data.find((x) => x.worker_id === S.wid) : null;
  html += row ? capCard(row) : unavailable();
  if (!h.ok) { el.innerHTML = html + unavailable(); return; }
  const days = [...h.data].sort((a, b) => (a.day < b.day ? 1 : -1));
  html += days.length ? `<ul class="days">${days.map(dayRow).join("")}</ul>` : `<div class="card empty">${esc(L("no_hours"))}</div>`;
  el.innerHTML = html;
}
