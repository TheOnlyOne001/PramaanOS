// Hours & overtime: request overtime (caps checked before sending), live consent status, quarterly cap table.
import { api, esc, fmtDay, num, toast } from "/shared/api.js";
import { S, $, DEMO_DAY } from "../state.js";
import { na, chip, capChip, evList, meterCls } from "../ui.js";

const REQ_STATE = { pending: ["info", "⏳", "Waiting"], accepted: ["ok", "✓", "Accepted"], declined: ["neutral", "✗", "Declined"], blocked: ["crit", "⛔", "Blocked"] };
const DEFAULT_PICK = ["W001", "W002", "W003"];

function pickItem(w) {
  const c = S.cap.find((x) => x.worker_id === w.id);
  return `<label class="pick-item"><input type="checkbox" name="w" value="${esc(w.id)}" ${DEFAULT_PICK.includes(w.id) ? "checked" : ""}>
    <span>${esc(w.name)} ${c ? `<small class="mono">${esc(num(c.used))}/${esc(num(c.cap, 0))} h</small> ${c.status !== "ok" ? capChip(c.status) : ""}` : ""}</span></label>`;
}

function capRow(c) {
  const pct = Math.min(100, c.pct ?? (c.used / c.cap) * 100);
  return `<tr><td><button type="button" class="linkish" data-open="${esc(c.worker_id)}">${esc(c.name)}</button> <span class="mono small">${esc(c.worker_id)}</span></td>
    <td><div class="meter ${meterCls(c.status)}" role="meter" aria-label="${esc(c.name)} overtime" aria-valuemin="0" aria-valuenow="${esc(c.used)}" aria-valuemax="${esc(c.cap)}"><i style="width:${pct}%"></i></div><span class="small">${esc(num(c.used))} / ${esc(num(c.cap, 0))} h</span></td>
    <td>${esc(num(c.remaining))} h</td><td>${capChip(c.status)}</td></tr>`;
}

function sentList(requests) {
  return `<h3>Sent</h3><ul class="results">${requests.map((q) => `<li>${q.status === "blocked" ? chip("crit", "⛔", "Blocked") : chip("info", "⏳", "Pending")} <b>${esc(q.name)}</b>
    ${q.cap ? `<span class="small mono">${esc(num(q.cap.used))} → ${esc(num(q.cap.after))} / ${esc(num(q.cap.cap, 0))} h</span>` : ""}
    ${(q.warnings || []).map((w) => `<div class="warnline">⚠ ${esc(w)}</div>`).join("")} ${evList(q.events)}</li>`).join("")}</ul>`;
}

export async function renderHours(m) {
  const cap = await api(`/ot/cap?date=${DEMO_DAY}`);
  S.cap = cap.ok ? cap.data : [];
  const people = S.workers.filter((w) => !w.is_supervisor);
  m.innerHTML = `<h1>Hours &amp; overtime</h1>
    <div class="grid2">
    <section class="card"><h2>Request overtime</h2>
      <form id="otForm"><fieldset><legend>Workers</legend><div class="pick">${people.map(pickItem).join("")}</div></fieldset>
        <div class="row"><label>Date <input type="date" name="date" value="${DEMO_DAY}"></label><label>Hours <input type="number" name="hours" value="2" min="0.5" max="4" step="0.5"></label></div>
        <label>Reason <input type="text" name="reason" value="Export shipment due Friday"></label>
        <p class="muted small">Requested by Murugan Pandi (S001). Each worker answers privately on their phone. Saying no costs them nothing.</p>
        <button type="submit" class="btn primary">Send request</button></form>
      <div id="otResults" aria-live="polite">${S.lastResults || ""}</div></section>
    <section class="card"><h2>Requests and consent <span class="muted small">live</span></h2><div id="reqs">${na("Loading…")}</div></section></div>
    <section class="card"><h2>Quarterly overtime cap (144 h)</h2>${cap.ok ? `<div class="table-wrap"><table><thead><tr><th>Worker</th><th>Used / cap</th><th>Remaining</th><th>Status</th></tr></thead><tbody>
      ${S.cap.map(capRow).join("")}</tbody></table></div>` : na("Overtime cap not available yet")}</section>`;
  $("#otForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { worker_ids: f.getAll("w"), date: f.get("date"), hours: +f.get("hours"), reason: f.get("reason"), requested_by: "S001" };
    if (!body.worker_ids.length) { toast("Pick at least one worker"); return; }
    const r = await api("/ot/requests", { method: "POST", body });
    if (!r.ok) { $("#otResults").innerHTML = na(`Overtime requests not available yet (${r.error})`); return; }
    S.lastResults = sentList(r.data.requests || []);
    $("#otResults").innerHTML = S.lastResults;
    refreshReqs();
  };
  refreshReqs();
}

/** Live list of overtime requests and how each worker answered. */
export async function refreshReqs() {
  const el = $("#reqs"); if (!el) return;
  const r = await api("/ot/requests");
  if (!r.ok) { el.innerHTML = na("Overtime requests not available yet"); return; }
  const list = [...r.data].reverse().slice(0, 12);
  el.innerHTML = list.length ? `<ul class="results">${list.map((q) => { const [c, i, w] = REQ_STATE[q.status] || REQ_STATE.pending;
    return `<li>${chip(c, i, w)} <b>${esc(q.name || S.names[q.worker_id] || q.worker_id)}</b> <span class="small">${esc(num(q.hours))} h · ${esc(fmtDay(q.date))}</span>
      ${q.channel ? `<span class="small muted">via ${esc(q.channel)}${q.transcript ? ` “${esc(q.transcript)}”` : ""}</span>` : ""} ${evList(q.events)}</li>`; }).join("")}</ul>` : `<p class="muted">No requests yet.</p>`;
}
