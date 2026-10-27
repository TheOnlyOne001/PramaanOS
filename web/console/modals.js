// Console dialogs: ledger evidence with Merkle proof, published daily roots, and opening a worker's record
// (which needs a reason that she sees). Focus is trapped while open and returned to the trigger on close.
import { api, esc, hm, fmtDay, toast } from "/shared/api.js";
import { S, $ } from "./state.js";
import { na, ev, short, chip } from "./ui.js";
import { focusHeading } from "./router.js";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
const CLOSE_ROW = `<div class="rowb"><span></span><button type="button" class="btn primary" data-close>Close</button></div>`;
let lastFocus = null;

const card = () => $("#modalCard");
const problemsFor = (seq) => ((S.verify && S.verify.problems) || []).filter((q) => q.seq === seq);

function focusFirst() {
  setTimeout(() => { const i = $("#modalCard input:checked, #modalCard input, #modalCard [data-close], #modalCard button"); (i || card()).focus(); }, 30);
}

export function openModal() {
  const m = $("#modal");
  if (m.classList.contains("hidden")) lastFocus = document.activeElement;
  m.classList.remove("hidden");
  document.querySelectorAll("body > :not(#modal):not(script)").forEach((n) => n.setAttribute("inert", ""));
  focusFirst();
}

export function closeModal() {
  const m = $("#modal");
  if (m.classList.contains("hidden")) return;
  m.classList.add("hidden");
  document.querySelectorAll("[inert]").forEach((n) => n.removeAttribute("inert"));
  // The evidence link may have been re-rendered while the dialog was open: find its replacement.
  if (lastFocus && !document.contains(lastFocus) && lastFocus.dataset && lastFocus.dataset.event) lastFocus = document.querySelector(`a[data-event="${lastFocus.dataset.event}"]`);
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  else focusHeading();
  lastFocus = null;
}

export const isModalOpen = () => !$("#modal").classList.contains("hidden");

/** Keep Tab / Shift+Tab inside the open dialog. */
export function trapTab(e) {
  if (e.key !== "Tab" || !isModalOpen()) return;
  const f = [...card().querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
  if (!f.length) { e.preventDefault(); return; }
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function proofBlock(p, err) {
  if (!p) return na(`Proof not available (${err})`);
  const proof = p.proof || [];
  const sib = (s) => (typeof s === "string" ? s : `${s.side || s.position || s.dir || ""} ${s.hash || s.sibling || JSON.stringify(s)}`);
  return `<p class="small">Day <b>${esc(p.day)}</b> · root <span class="mono">${esc(short(p.root, 24))}</span> · ${esc(proof.length)} sibling hash${proof.length === 1 ? "" : "es"}</p>
    ${proof.length ? `<ol class="proof mono small">${proof.map((s) => `<li>${esc(sib(s))}</li>`).join("")}</ol>` : `<p class="muted small">Only event that day: its hash is the root.</p>`}`;
}

/** Evidence dialog: one ledger event, its signature status and its Merkle inclusion proof. */
export async function showEvent(seq) {
  const title = `<h2 id="modalTitle">Ledger event #${esc(seq)}</h2>`;
  card().innerHTML = `${title}<p class="muted" role="status">Loading evidence…</p>`;
  openModal();
  const id = encodeURIComponent(seq);
  const [e, pr] = await Promise.all([api(`/ledger/events/${id}`), api(`/ledger/events/${id}/proof`)]);
  if (!e.ok) { card().innerHTML = `${title}${na(`Event not available (${e.error})`)}${CLOSE_ROW}`; focusFirst(); return; }
  const x = e.data;
  const bad = problemsFor(x.seq);
  const row = (k, v, mono = true) => `<tr><th scope="row">${esc(k)}</th><td class="${mono ? "mono small brk" : ""}">${v}</td></tr>`;
  card().innerHTML = `<h2 id="modalTitle">Ledger event #${esc(x.seq)} <span class="mono small">${esc(x.ref || "")}</span></h2>
    ${bad.length ? `<p class="warnline" role="alert">⚠ ${esc(bad.map((q) => String(q.kind).replace(/_/g, " ")).join(", "))} — this row no longer matches its signature.</p>` : `<p>${chip("ok", "✓", "Signature and chain check passed")}</p>`}
    <div class="table-wrap"><table class="kv"><caption class="sr">Event fields</caption><tbody>
      ${row("Type", esc(x.type), false)}
      ${row("Worker", x.worker_id ? `${esc(S.names[x.worker_id] || x.worker_id)} <span class="mono small">${esc(x.worker_id)}</span>` : "Site", false)}
      ${row("Time", `${esc(fmtDay(x.day || x.ts))} ${esc(hm(x.ts))} <span class="mono small">${esc(x.ts)}</span>`, false)}
      ${row("Hash", esc(x.hash))}
      ${row("Previous hash", esc(x.prev_hash))}
      ${row("Signature", esc(x.sig))}
      ${row("Signer", esc(x.signer || "site"), false)}
      ${row("Payload", `<code>${esc(JSON.stringify(x.payload))}</code>`)}
    </tbody></table></div>
    <h3>Merkle inclusion proof</h3>
    ${proofBlock(pr.ok ? pr.data : null, pr.error)}
    <div class="rowb"><a class="btn" href="/api/ledger/events/${encodeURIComponent(x.seq)}" target="_blank" rel="noopener">Raw JSON <span class="sr">(opens in a new tab)</span></a><button type="button" class="btn primary" data-close>Close</button></div>`;
  focusFirst();
}

/** Published versus recomputed Merkle root for each day. */
export async function showRoots() {
  const title = `<h2 id="modalTitle">Published daily roots</h2>`;
  card().innerHTML = `${title}<p class="muted" role="status">Loading…</p>`;
  openModal();
  const r = await api("/ledger/roots");
  const rows = r.ok ? (Array.isArray(r.data) ? r.data : r.data.roots || []) : [];
  card().innerHTML = `${title}
    <p class="small muted">Each day's Merkle root is published. If anyone edits a signed row, the recomputed root stops matching.</p>
    ${r.ok ? `<div class="table-wrap"><table><caption class="sr">Published versus current Merkle roots per day</caption><thead><tr><th scope="col">Day</th><th scope="col">Events</th><th scope="col">Published</th><th scope="col">Current</th><th scope="col">Status</th></tr></thead><tbody>
      ${[...rows].reverse().map((x) => `<tr class="${x.ok ? "" : "badrow"}"><td>${esc(fmtDay(x.day))}</td><td>${esc(x.n_events ?? "—")}</td><td class="mono small">${esc(short(x.published))}</td><td class="mono small">${esc(short(x.current))}</td><td>${x.ok ? chip("ok", "✓", "OK") : chip("crit", "✗", "Mismatch")}</td></tr>`).join("")}</tbody></table></div>` : na(`Roots not available (${r.error})`)}
    ${CLOSE_ROW}`;
  focusFirst();
}

/** Opening one worker's record needs a reason; the look-up is logged and shown in her app. */
export function askReason(wid) {
  const name = S.names[wid] || wid, first = name.split(" ")[0];
  card().innerHTML = `<h2 id="modalTitle">Open ${esc(name)}'s record</h2><p>Opening an individual record needs a reason.</p>
    <form id="reasonForm"><fieldset><legend>Reason</legend>${["Pay query", "Skill review", "Safety incident"].map((r, i) => `<label class="radio"><input type="radio" name="reason" value="${r}" ${i === 0 ? "checked" : ""}> ${r}</label>`).join("")}</fieldset>
    <p class="notice">👁 ${esc(first)} will see that you opened this, and why.</p>
    <div class="rowb"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">Open record</button></div></form>`;
  openModal();
  $("#reasonForm").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api(`/workers/${wid}/lookup`, { method: "POST", body: { viewer: "Murugan Pandi (S001)", viewer_role: "supervisor", reason: new FormData(e.target).get("reason") } });
    if (!r.ok) { toast(r.error); return; }
    const bad = new Set(((S.verify && S.verify.problems) || []).map((p) => p.seq));
    const w = r.data.worker;
    card().innerHTML = `<h2 id="modalTitle">${esc(w.name)} <span class="mono small">${esc(w.id)}</span></h2>
      <p class="small">${esc(w.role)} · ${esc(w.line)} · ${esc(w.skill_band)} · ${esc(w.contract_type)}${w.contractor ? " via " + esc(w.contractor) : ""}</p>
      <p class="notice">👁 Logged: “${esc(r.data.access.reason)}” at ${esc(hm(r.data.access.ts))}. ${esc(first)} sees this in her app.</p>
      <div class="table-wrap"><table><thead><tr><th>Evidence</th><th>Time</th><th>Event</th></tr></thead><tbody>${(r.data.recent_events || []).map((x) => `<tr class="${bad.has(x.seq) ? "badrow" : ""}"><td>${ev(x.seq, x.ref)}</td><td>${esc(fmtDay(x.day || x.ts))} ${esc(hm(x.ts))}</td><td>${bad.has(x.seq) ? chip("crit", "⚠", "Edited after signing") + " " : ""}${esc(x.type)}</td></tr>`).join("")}</tbody></table></div>
      ${CLOSE_ROW}`;
    card().querySelector("[data-close]").focus();
  };
}
