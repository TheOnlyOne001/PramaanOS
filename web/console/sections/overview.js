// Overview: the console opens on exceptions ranked by legal risk, not on charts.
// Uses the server's /console/overview, or composes exceptions from the engines if that is unavailable.
import { api, esc, num } from "/shared/api.js";
import { S, DEMO_DAY, PERIOD, SECTIONS } from "../state.js";
import { na, ev, chip, SEV, KIND, zoneName, label } from "../ui.js";
import { problemsText } from "../integrity.js";
import { askReason, showEvent, showRoots } from "../modals.js";
import { go, focusHeading } from "../router.js";
import { edgeCard } from "./safety.js";

const ORDER = { critical: 0, high: 1, medium: 2 };
const URGENT_EDGE = ["fire_smoke", "person_down", "blocked_exit"];

async function exceptions() {
  const o = await api("/console/overview");
  if (o.ok && Array.isArray(o.data.exceptions)) return o.data.exceptions;
  const [cap, fair, themes, edge] = await Promise.all([api(`/ot/cap?date=${DEMO_DAY}`), api(`/pay/fairness?period=${PERIOD}`), api("/voice/themes"), api("/edge/events?limit=10")]);
  const out = [];
  const v = S.verify;
  if (v && !v.ok) for (const p of v.problems) out.push({ severity: "critical", kind: "integrity", title: problemsText({ problems: [p] }), detail: p.detail, people: p.worker_name ? [p.worker_name] : [], action: p.worker_id ? "Open record" : "See ledger", link: p.worker_id ? "worker:" + p.worker_id : "#overview" });
  if (cap.ok) for (const c of cap.data.filter((x) => x.status !== "ok")) out.push({ severity: c.status === "over" ? "critical" : "high", kind: "ot_cap", title: `${c.name} ${c.status === "over" ? "over" : "near"} the quarterly overtime cap · ${num(c.used)}/${num(c.cap, 0)} h`, people: [c.name], action: "Review hours", link: "#hours" });
  if (fair.ok) for (const c of (fair.data.checks || []).filter((x) => !x.ok)) out.push({ severity: "high", kind: "pay", title: c.name, detail: c.detail, people: (c.workers || []).map((w) => S.names[w] || w), action: "Review pay", link: "#pay" });
  if (themes.ok) for (const t of themes.data.filter((x) => x.published && !x.response)) out.push({ severity: t.safety_critical ? "high" : "medium", kind: "voice", title: `Voice: ${label(t.label)} · ${t.count} independent reports`, detail: "No names attached", people: [], action: "Respond", link: "#voice" });
  if (edge.ok) for (const e of edge.data.filter((x) => x.kind !== "ppe_compliance_rate" && x.kind !== "queue_length").slice(0, 3)) out.push({ severity: URGENT_EDGE.includes(e.kind) ? "critical" : "high", kind: "edge", title: `${zoneName(e.zone)} · ${KIND[e.kind] || e.kind} · ${e.camera}`, detail: "No video or face left the box", people: [], action: "View camera feed", link: "#safety", seq: e.seq });
  return out;
}

/** Follow an exception's action link: a worker record, an evidence modal, or another section. */
function act(link) {
  if (!link) return;
  if (link.startsWith("worker:")) return askReason(link.slice(7));
  if (link.startsWith("/api/ledger/events/")) return showEvent(link.slice("/api/ledger/events/".length).split(/[/?#]/)[0]);
  if (link.startsWith("/api/ledger/roots")) return showRoots();
  if (link.startsWith("/api/workers/")) return askReason(link.split("/")[3]);
  const h = link.includes("#") ? link.slice(link.indexOf("#") + 1) : link;
  if (SECTIONS.some((s) => s[0] === h)) { go(h); setTimeout(focusHeading, 400); }
}

function people(e) {
  const list = Array.isArray(e.people) ? e.people : [e.people];
  return `<div class="small people"><span aria-hidden="true">👥</span><span class="sr">People:</span> ${list.map((p) => S.names[p]
    ? `<button type="button" class="linkish" data-open="${esc(p)}" aria-label="Open ${esc(S.names[p])}'s record (${esc(p)})">${esc(S.names[p])} <span class="mono small">${esc(p)}</span></button>`
    : esc(p)).join(", ")}</div>`;
}

function exceptionItem(e, i) {
  const [c, ic, w] = SEV[e.severity] || SEV.medium;
  const ppl = Array.isArray(e.people) ? e.people.join(", ") : e.people;
  return `<li>${chip(c, ic, w)}<div class="exc-main"><b>${esc(e.title)}</b>${e.detail ? `<div class="muted small">${esc(e.detail)}</div>` : ""}
    ${ppl ? people(e) : ""}${e.seq != null ? ev(e.seq) : ""}</div>
    ${e.action ? `<button type="button" class="btn" data-act="${i}" aria-label="${esc(e.action)}: ${esc(e.title)}">${esc(e.action)} <span aria-hidden="true">→</span></button>` : ""}</li>`;
}

export async function renderOverview(m) {
  const [ex, edge] = await Promise.all([exceptions(), api("/edge/events?limit=3")]);
  ex.sort((a, b) => (ORDER[a.severity] ?? 3) - (ORDER[b.severity] ?? 3));
  m.innerHTML = `<h1>Exceptions <span class="muted small">${ex.length} need attention</span></h1>
    <p class="muted">The console opens on what needs action, not on charts. Every individual look-up is shown to the worker.</p>
    <div class="card"><ul class="exc">${ex.length ? ex.map(exceptionItem).join("") : `<li class="muted">✓ Nothing needs attention right now.</li>`}</ul></div>
    <h2>Latest camera events</h2><div class="feed">${edge.ok ? edge.data.map(edgeCard).join("") || `<p class="muted">No events yet.</p>` : na()}</div>`;
  m.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => act(ex[+b.dataset.act].link)));
}

