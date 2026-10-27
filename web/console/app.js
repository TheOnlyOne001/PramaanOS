// Saakshi employer console. Opens on exceptions. All server text goes through esc() before reaching the DOM.
import { api, esc, hm, fmtDay, rupees, num, toast } from "/shared/api.js";

const DEMO_DAY = "2026-10-27", PERIOD = "2026-10";
const $ = (s) => document.querySelector(s);
const S = { sec: "overview", workers: [], names: {}, verify: null, wasBad: false, cap: [], lastResults: null, payRun: null, pending: null };
const SECTIONS = [
  ["overview", "⚑", "Overview"], ["hours", "⏱", "Hours & overtime"], ["pay", "₹", "Pay fairness"],
  ["skills", "🎓", "Skills coverage"], ["safety", "📷", "Safety & cameras"], ["voice", "📣", "Voice"], ["sdg8", "◎", "SDG 8"],
];
const SEV = { critical: ["crit", "⛔", "Critical"], high: ["warn", "⚠", "High"], medium: ["info", "ℹ", "Medium"] };
const KIND = { restricted_zone_entry: "restricted entry", ppe_noncompliance: "PPE missing", ppe_compliance_rate: "PPE compliance",
  fire_smoke: "fire / smoke", blocked_exit: "blocked exit", person_down: "person down", queue_length: "queue length", near_miss: "near miss", heat_wbgt: "heat (WBGT)" };
const na = (what) => `<div class="card empty">🕓 ${esc(what || "Not available yet")}</div>`;
const ev = (seq, ref) => seq == null ? "" : `<a class="ref" href="/api/ledger/events/${encodeURIComponent(seq)}" target="_blank" rel="noopener" title="Evidence: ledger event #${esc(seq)}">#${esc(seq)}${ref ? " · " + esc(ref) : ""}</a>`;
const evList = (l) => Array.isArray(l) && l.length ? `<span class="evid">${l.slice(0, 5).map((s) => ev(s)).join(" ")}${l.length > 5 ? ` +${l.length - 5}` : ""}</span>` : "";
const chip = (cls, icon, word) => `<span class="chip ${cls}"><span aria-hidden="true">${icon}</span> ${esc(word)}</span>`;
const capChip = (s) => s === "over" ? chip("crit", "⛔", "Over cap") : s === "near" ? chip("warn", "⚠", "Near cap") : chip("ok", "✓", "OK");
const zoneName = (z) => { const s = String(z || "").replace(/[_-]/g, " "); return s.charAt(0).toUpperCase() + s.slice(1) + (/zone/i.test(s) ? "" : " zone"); };
const label = (l) => (l && typeof l === "object" ? l.en || Object.values(l)[0] : l) || "";

// --- Integrity banner -------------------------------------------------------------
function problemsText(v) {
  const parts = [];
  for (const p of v.problems || []) {
    if (p.kind === "root_mismatch") parts.push(`published root for ${fmtDay(p.ts || DEMO_DAY)} no longer matches`);
    else if (p.kind === "content_edited") parts.push(`${p.worker_name || p.worker_id || "Site"} · ${p.type} #${p.seq} edited after signing`);
    else parts.push(`${p.worker_name ? p.worker_name + " · " : ""}${p.type || ""}${p.seq != null ? " #" + p.seq : ""} ${String(p.kind).replace(/_/g, " ")}`);
  }
  return parts.join(" · ");
}
async function pollVerify() {
  const r = await api("/ledger/verify");
  const el = $("#integrity");
  if (!r.ok) { el.className = "integrity checking"; el.innerHTML = `<div class="int-row"><span class="int-icon" aria-hidden="true">…</span><div class="int-text"><b>Ledger check unavailable</b> <span>${esc(r.error)}</span></div></div>`; return; }
  const v = r.data; S.verify = v;
  if (v.ok) {
    const today = (v.roots || []).find((x) => x.day === DEMO_DAY);
    const pub = today && today.published;
    el.className = "integrity ok";
    el.innerHTML = `<div class="int-row"><span class="int-icon" aria-hidden="true">✓</span><div class="int-text"><b>Ledger verified</b> · ${esc(num(v.n_events, 0))} events · ${pub ? "today's root published" : "today's root not yet published"}
      <span class="mono small">head ${esc(String(v.head || "").slice(0, 12))} · checked ${esc(hm(v.checked_at))}</span></div></div>`;
    S.wasBad = false; document.title = "Saakshi Console";
    return;
  }
  const first = (v.problems || []).find((p) => p.worker_id);
  el.className = "integrity bad" + (S.wasBad ? "" : " flash");
  el.innerHTML = `<div class="int-row"><span class="int-icon" aria-hidden="true">⚠</span><div class="int-text">
      <b class="int-title">Integrity alert</b><div class="int-detail">${esc(problemsText(v))}</div>
      <span class="small">Detected ${esc(hm(v.checked_at))} · payroll for affected workers is blocked · ${esc(v.n_events)} events checked</span></div>
      ${first ? `<button type="button" class="btn light" data-open="${esc(first.worker_id)}">Open ${esc(first.worker_name || first.worker_id)}'s record</button>` : ""}</div>
    <details class="int-hashes"><summary>Show hashes</summary>${(v.problems || []).map((p) => `<div class="mono small">#${esc(p.seq ?? "root")} ${esc(p.kind)} · stored ${esc(String(p.stored_hash || "").slice(0, 16))} · now ${esc(String(p.recomputed_hash || "").slice(0, 16))}</div>`).join("")}</details>`;
  if (!S.wasBad) { document.body.classList.add("alarm"); setTimeout(() => document.body.classList.remove("alarm"), 1600); }
  S.wasBad = true; document.title = "⚠ Integrity alert · Saakshi";
}

// --- Exceptions ----------------------------------------------------------------------
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
  if (edge.ok) for (const e of edge.data.filter((x) => x.kind !== "ppe_compliance_rate" && x.kind !== "queue_length").slice(0, 3)) out.push({ severity: ["fire_smoke", "person_down", "blocked_exit"].includes(e.kind) ? "critical" : "high", kind: "edge", title: `${zoneName(e.zone)} · ${KIND[e.kind] || e.kind} · ${e.camera}`, detail: "No video or face left the box", people: [], action: "View camera feed", link: "#safety", seq: e.seq });
  return out;
}
function act(link) {
  if (!link) return;
  if (link.startsWith("worker:")) return askReason(link.slice(7));
  const h = link.includes("#") ? link.slice(link.indexOf("#") + 1) : link;
  if (SECTIONS.some((s) => s[0] === h)) go(h);
}

// --- Sections ------------------------------------------------------------------------
async function renderOverview(m) {
  const [ex, edge] = await Promise.all([exceptions(), api("/edge/events?limit=3")]);
  const order = { critical: 0, high: 1, medium: 2 };
  ex.sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3));
  m.innerHTML = `<h1>Exceptions <span class="muted small">${ex.length} need attention</span></h1>
    <p class="muted">The console opens on what needs action, not on charts. Every individual look-up is shown to the worker.</p>
    <div class="card"><ul class="exc">${ex.length ? ex.map((e, i) => { const [c, ic, w] = SEV[e.severity] || SEV.medium; const ppl = Array.isArray(e.people) ? e.people.join(", ") : e.people;
      return `<li>${chip(c, ic, w)}<div class="exc-main"><b>${esc(e.title)}</b>${e.detail ? `<div class="muted small">${esc(e.detail)}</div>` : ""}
        ${ppl ? `<div class="small">👥 ${esc(ppl)}</div>` : ""}${e.seq != null ? ev(e.seq) : ""}</div>
        ${e.action ? `<button type="button" class="btn" data-act="${i}">${esc(e.action)} →</button>` : ""}</li>`; }).join("") : `<li class="muted">✓ Nothing needs attention right now.</li>`}</ul></div>
    <h2>Latest camera events</h2><div class="feed">${edge.ok ? edge.data.map(edgeCard).join("") || `<p class="muted">No events yet.</p>` : na()}</div>`;
  m.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => act(ex[+b.dataset.act].link)));
}

async function renderHours(m) {
  const cap = await api(`/ot/cap?date=${DEMO_DAY}`);
  S.cap = cap.ok ? cap.data : [];
  const people = S.workers.filter((w) => !w.is_supervisor);
  m.innerHTML = `<h1>Hours &amp; overtime</h1>
    <div class="grid2">
    <section class="card"><h2>Request overtime</h2>
      <form id="otForm"><fieldset><legend>Workers</legend><div class="pick">${people.map((w) => { const c = S.cap.find((x) => x.worker_id === w.id);
        return `<label class="pick-item"><input type="checkbox" name="w" value="${esc(w.id)}" ${["W001", "W002", "W003"].includes(w.id) ? "checked" : ""}>
        <span>${esc(w.name)} ${c ? `<small class="mono">${esc(num(c.used))}/${esc(num(c.cap, 0))} h</small> ${c.status !== "ok" ? capChip(c.status) : ""}` : ""}</span></label>`; }).join("")}</div></fieldset>
        <div class="row"><label>Date <input type="date" name="date" value="${DEMO_DAY}"></label><label>Hours <input type="number" name="hours" value="2" min="0.5" max="4" step="0.5"></label></div>
        <label>Reason <input type="text" name="reason" value="Export shipment due Friday"></label>
        <p class="muted small">Requested by Murugan Pandi (S001). Each worker answers privately on their phone. Saying no costs them nothing.</p>
        <button type="submit" class="btn primary">Send request</button></form>
      <div id="otResults" aria-live="polite">${S.lastResults || ""}</div></section>
    <section class="card"><h2>Requests and consent <span class="muted small">live</span></h2><div id="reqs">${na("Loading…")}</div></section></div>
    <section class="card"><h2>Quarterly overtime cap (144 h)</h2>${cap.ok ? `<div class="table-wrap"><table><thead><tr><th>Worker</th><th>Used / cap</th><th>Remaining</th><th>Status</th></tr></thead><tbody>
      ${S.cap.map((c) => { const pct = Math.min(100, c.pct ?? (c.used / c.cap) * 100); return `<tr><td><button type="button" class="linkish" data-open="${esc(c.worker_id)}">${esc(c.name)}</button> <span class="mono small">${esc(c.worker_id)}</span></td>
        <td><div class="meter ${c.status === "over" ? "crit" : c.status === "near" ? "warn" : ""}" role="meter" aria-label="${esc(c.name)} overtime" aria-valuenow="${esc(c.used)}" aria-valuemax="${esc(c.cap)}"><i style="width:${pct}%"></i></div><span class="small">${esc(num(c.used))} / ${esc(num(c.cap, 0))} h</span></td>
        <td>${esc(num(c.remaining))} h</td><td>${capChip(c.status)}</td></tr>`; }).join("")}</tbody></table></div>` : na("Overtime cap not available yet")}</section>`;
  $("#otForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { worker_ids: f.getAll("w"), date: f.get("date"), hours: +f.get("hours"), reason: f.get("reason"), requested_by: "S001" };
    if (!body.worker_ids.length) return toast("Pick at least one worker");
    const r = await api("/ot/requests", { method: "POST", body });
    if (!r.ok) { $("#otResults").innerHTML = na(`Overtime requests not available yet (${r.error})`); return; }
    S.lastResults = `<h3>Sent</h3><ul class="results">${(r.data.requests || []).map((q) => `<li>${q.status === "blocked" ? chip("crit", "⛔", "Blocked") : chip("info", "⏳", "Pending")} <b>${esc(q.name)}</b>
      ${q.cap ? `<span class="small mono">${esc(num(q.cap.used))} → ${esc(num(q.cap.after))} / ${esc(num(q.cap.cap, 0))} h</span>` : ""}
      ${(q.warnings || []).map((w) => `<div class="warnline">⚠ ${esc(w)}</div>`).join("")} ${evList(q.events)}</li>`).join("")}</ul>`;
    $("#otResults").innerHTML = S.lastResults;
    refreshReqs();
  };
  refreshReqs();
}
async function refreshReqs() {
  const el = $("#reqs"); if (!el) return;
  const r = await api("/ot/requests");
  if (!r.ok) { el.innerHTML = na("Overtime requests not available yet"); return; }
  const st = { pending: ["info", "⏳", "Waiting"], accepted: ["ok", "✓", "Accepted"], declined: ["neutral", "✗", "Declined"], blocked: ["crit", "⛔", "Blocked"] };
  const list = [...r.data].reverse().slice(0, 12);
  el.innerHTML = list.length ? `<ul class="results">${list.map((q) => { const [c, i, w] = st[q.status] || st.pending;
    return `<li>${chip(c, i, w)} <b>${esc(q.name || S.names[q.worker_id] || q.worker_id)}</b> <span class="small">${esc(num(q.hours))} h · ${esc(fmtDay(q.date))}</span>
      ${q.channel ? `<span class="small muted">via ${esc(q.channel)}${q.transcript ? ` “${esc(q.transcript)}”` : ""}</span>` : ""} ${evList(q.events)}</li>`; }).join("")}</ul>` : `<p class="muted">No requests yet.</p>`;
}

async function renderPay(m) {
  const r = await api(`/pay/fairness?period=${PERIOD}`);
  m.innerHTML = `<h1>Pay fairness · October 2026</h1>
    <section class="card"><div class="rowb"><h2>Fairness checks</h2><button type="button" class="btn primary" id="runPay">▶ Run payroll</button></div>
    ${r.ok ? `<ul class="checks">${(r.data.checks || []).map((c) => `<li>${c.ok ? chip("ok", "✓", "Pass") : chip("crit", "✗", "Fail")} <div><b>${esc(c.name)}</b><div class="small muted">${esc(c.detail || "")}</div>
      ${(c.workers || []).length ? `<div class="small">👥 ${esc(c.workers.map((w) => S.names[w] || w).join(", "))}</div>` : ""}</div></li>`).join("")}</ul>
      ${r.data.ot_gini != null ? `<p class="small">Overtime spread (Gini): <b>${esc(num(r.data.ot_gini, 2))}</b></p>` : ""}` : na("Pay fairness not available yet")}</section>
    <section class="card" id="payRun" aria-live="polite">${S.payRun || ""}</section>`;
  $("#runPay").onclick = async () => {
    const x = await api(`/pay/run?period=${PERIOD}`, { method: "POST" });
    S.payRun = !x.ok ? na(`Payroll not available yet (${x.error})`) : `<h2>Payroll run ${x.data.blocked ? chip("crit", "⛔", "Blocked") : chip("ok", "✓", "Completed")}</h2>
      <div class="table-wrap"><table><thead><tr><th>Worker</th><th>Gross</th><th>Net</th><th>Status</th><th>Failed checks</th></tr></thead><tbody>${(x.data.results || []).map((w) => `<tr><td>${esc(w.name)}</td><td>${esc(rupees(w.gross, 2))}</td><td>${esc(rupees(w.net, 2))}</td>
      <td>${w.blocked ? chip("crit", "⛔", "Blocked") : chip("ok", "✓", "OK")}</td><td class="small">${esc((w.failed_checks || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>`;
    $("#payRun").innerHTML = S.payRun;
  };
}

async function renderSkills(m) {
  const r = await api("/passport/coverage");
  let body = "";
  if (r.ok) {
    const rows = Array.isArray(r.data) ? r.data : r.data.skills || r.data.coverage || [];
    body = Array.isArray(rows) && rows.length ? `<div class="table-wrap"><table><thead><tr>${Object.keys(rows[0]).map((k) => `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>${rows.map((x) => `<tr>${Object.values(x).map((v) => `<td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<pre class="mono small">${esc(JSON.stringify(r.data, null, 1))}</pre>`;
  } else {
    const ps = await Promise.all(S.workers.filter((w) => !w.is_supervisor).map(async (w) => [w, await api(`/passport/${w.id}`)]));
    body = ps.some(([, p]) => p.ok) ? `<div class="table-wrap"><table><thead><tr><th>Worker</th><th>Verified skills</th><th>In progress</th></tr></thead><tbody>${ps.map(([w, p]) => `<tr><td>${esc(w.name)}</td>
      <td>${p.ok ? (p.data.credentials || []).map((c) => { const s = (c.vc || c).credentialSubject || {}; return chip("ok", "✓", [s.level || c.level, typeof s.skill === "string" ? s.skill : (s.skill && s.skill.name) || c.skill].filter(Boolean).join(" · ") || "credential"); }).join(" ") : "—"}</td>
      <td class="small">${p.ok ? (p.data.progress || []).map((g) => `${esc(g.skill)} ${esc(g.level)} ${esc(g.days_met ?? 0)}/${esc(g.days_needed ?? "?")} d`).join(" · ") : "—"}</td></tr>`).join("")}</tbody></table></div>` : na("Skills coverage not available yet");
  }
  m.innerHTML = `<h1>Skills coverage</h1><section class="card">${body}</section>`;
}

function edgeCard(e) {
  return `<article class="edge-card"><div><b>${esc(zoneName(e.zone))} · ${esc(KIND[e.kind] || e.kind)} · ${esc(e.camera)}</b>
    ${e.count != null ? `<span class="small"> · count ${esc(e.count)}</span>` : ""}${e.value != null ? `<span class="small"> · value ${esc(num(e.value, 2))}</span>` : ""}</div>
    <div class="small muted">🔒 no video or face left the box · ${esc(hm(e.ts))} ${ev(e.seq)}</div></article>`;
}
async function renderSafety(m) {
  const [sum, cams] = await Promise.all([api(`/edge/summary?day=${DEMO_DAY}`), api("/edge/cameras")]);
  m.innerHTML = `<h1>Safety &amp; cameras</h1><p class="notice">🔒 Video never leaves the site. Only events and counts.</p>
    <div class="grid2"><section class="card"><h2>Live events <span class="muted small">live</span></h2><div class="feed" id="feed">${na("Loading…")}</div></section>
    <section class="card"><h2>Today by zone</h2>${sum.ok ? `<ul class="checks">${(sum.data.zones || []).map((z) => `<li><b>${esc(zoneName(z.zone))}</b> <span class="small">${esc(Object.entries(z.events || {}).map(([k, n]) => `${KIND[k] || k}: ${n}`).join(" · "))}</span></li>`).join("")}</ul>` : na("Edge summary not available yet")}</section></div>
    <section class="card"><h2>Camera register</h2>${cams.ok ? `<div class="table-wrap"><table><thead><tr><th>Camera</th><th>Zone</th><th>Purpose</th><th>Owner</th><th>Retention</th></tr></thead><tbody>${cams.data.map((c) => `<tr><td class="mono">${esc(c.camera)}</td><td>${esc(c.zone)}</td><td>${esc(c.purpose)}</td><td>${esc(c.owner)}</td><td>${esc(c.retention_hours)} h</td></tr>`).join("")}</tbody></table></div>` : na("Camera register not available yet")}</section>`;
  refreshFeed();
}
async function refreshFeed() {
  const el = $("#feed"); if (!el) return;
  const r = await api("/edge/events?limit=20");
  el.innerHTML = r.ok ? r.data.map(edgeCard).join("") || `<p class="muted">No events yet.</p>` : na("Edge events not available yet");
}

async function renderVoice(m) {
  const [th, board] = await Promise.all([api("/voice/themes"), api("/voice/board")]);
  m.innerHTML = `<h1>Voice <span class="muted small">anonymous, corroborated</span></h1>
    <p class="muted">A theme appears only once enough independent workers report it. No names, no IDs, ever.</p>
    <div id="themes">${th.ok ? th.data.map((t, i) => `<section class="card theme"><div class="rowb"><h2>${esc(label(t.label) || t.topic)}</h2>
      ${t.published ? chip("ok", "✓", `${t.count} independent reports · no names`) : chip("neutral", "⏳", `waiting for corroboration (${t.count} of ${t.threshold})`)}${t.safety_critical ? chip("warn", "⚠", "Safety") : ""}</div>
      ${t.published ? `<ul class="quotes">${(t.reports || []).map((x) => `<li>“${esc(x.text)}” <span class="muted small">${esc(hm(x.ts))}</span></li>`).join("")}</ul>
        ${t.response ? `<p>✅ <b>${esc(typeof t.response === "string" ? t.response : t.response.text || t.response.we_did)}</b></p>` : `<form class="respond" data-topic="${esc(t.topic)}"><label>Response (“we did”) <input type="text" name="text" required placeholder="e.g. Second water cooler installed on Line 4"></label><button class="btn primary" type="submit">Publish response</button></form>`}` : `<p class="muted small">Report text stays hidden until corroborated.</p>`}</section>`).join("") || na("No themes yet") : na("Voice themes not available yet")}</div>
    <section class="card"><h2>You said, we did</h2>${board.ok ? board.data.map((b) => `<div class="board-row"><span class="muted small">You said</span> ${esc(b.you_said)}<br><span class="small">✅ We did</span> <b>${esc(b.we_did)}</b> <span class="muted small">${esc(b.by || "")}</span></div>`).join("") || `<p class="muted">Nothing yet.</p>` : na()}</section>`;
  m.querySelectorAll("form.respond").forEach((f) => (f.onsubmit = async (e) => {
    e.preventDefault();
    const r = await api(`/voice/themes/${encodeURIComponent(f.dataset.topic)}/respond`, { method: "POST", body: { text: new FormData(f).get("text"), by: "Management" } });
    toast(r.ok ? "Response published to the board" : `Not available yet (${r.error})`); if (r.ok) renderVoice(m);
  }));
}

async function renderSdg(m) {
  const r = await api("/sdg8/scorecard");
  const cls = (s) => /on|ok|good|met|green/i.test(s) ? ["ok", "✓"] : /risk|warn|watch|amber/i.test(s) ? ["warn", "⚠"] : /off|bad|red|fail/i.test(s) ? ["crit", "✗"] : ["neutral", "•"];
  m.innerHTML = `<h1>SDG 8 scorecard</h1><p class="muted">Decent work and economic growth, computed from the signed ledger.</p>
    ${r.ok ? `<div class="sdg">${(r.data.targets || []).map((t) => { const [c, i] = cls(String(t.status)); return `<article class="card sdg-card"><span class="mono">Target ${esc(t.target)}</span><h2>${esc(t.label)}</h2>
      <div class="sdg-val">${esc(typeof t.value === "number" ? num(t.value, 2) : t.value)} <small>${esc(t.unit || "")}</small></div><p class="small muted">${esc(t.indicator)}</p>${chip(c, i, String(t.status).replace(/_/g, " "))}</article>`; }).join("")}</div>` : na("SDG 8 scorecard not available yet")}`;
}

// --- Worker record: needs a reason ------------------------------------------------------
function askReason(wid) {
  const name = S.names[wid] || wid, first = name.split(" ")[0];
  $("#modalCard").innerHTML = `<h2 id="modalTitle">Open ${esc(name)}'s record</h2><p>Opening an individual record needs a reason.</p>
    <form id="reasonForm"><fieldset><legend>Reason</legend>${["Pay query", "Skill review", "Safety incident"].map((r, i) => `<label class="radio"><input type="radio" name="reason" value="${r}" ${i === 0 ? "checked" : ""}> ${r}</label>`).join("")}</fieldset>
    <p class="notice">👁 ${esc(first)} will see that you opened this, and why.</p>
    <div class="rowb"><button type="button" class="btn" id="cancelM">Cancel</button><button type="submit" class="btn primary">Open record</button></div></form>`;
  openModal();
  $("#cancelM").onclick = closeModal;
  $("#reasonForm").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api(`/workers/${wid}/lookup`, { method: "POST", body: { viewer: "Murugan Pandi (S001)", viewer_role: "supervisor", reason: new FormData(e.target).get("reason") } });
    if (!r.ok) { toast(r.error); return; }
    const bad = new Set(((S.verify && S.verify.problems) || []).map((p) => p.seq));
    const w = r.data.worker;
    $("#modalCard").innerHTML = `<h2 id="modalTitle">${esc(w.name)} <span class="mono small">${esc(w.id)}</span></h2>
      <p class="small">${esc(w.role)} · ${esc(w.line)} · ${esc(w.skill_band)} · ${esc(w.contract_type)}${w.contractor ? " via " + esc(w.contractor) : ""}</p>
      <p class="notice">👁 Logged: “${esc(r.data.access.reason)}” at ${esc(hm(r.data.access.ts))}. ${esc(first)} sees this in her app.</p>
      <div class="table-wrap"><table><thead><tr><th>Evidence</th><th>Time</th><th>Event</th></tr></thead><tbody>${(r.data.recent_events || []).map((x) => `<tr class="${bad.has(x.seq) ? "badrow" : ""}"><td>${ev(x.seq, x.ref)}</td><td>${esc(fmtDay(x.day || x.ts))} ${esc(hm(x.ts))}</td><td>${bad.has(x.seq) ? chip("crit", "⚠", "Edited after signing") + " " : ""}${esc(x.type)}</td></tr>`).join("")}</tbody></table></div>
      <div class="rowb"><span></span><button type="button" class="btn primary" id="cancelM">Close</button></div>`;
    $("#cancelM").onclick = closeModal; $("#cancelM").focus();
  };
}
function openModal() { $("#modal").classList.remove("hidden"); setTimeout(() => { const i = $("#modalCard input, #modalCard button"); if (i) i.focus(); }, 30); }
function closeModal() { $("#modal").classList.add("hidden"); }

// --- Shell -------------------------------------------------------------------------------
const RENDER = { overview: renderOverview, hours: renderHours, pay: renderPay, skills: renderSkills, safety: renderSafety, voice: renderVoice, sdg8: renderSdg };
function go(sec, push = true) {
  S.sec = RENDER[sec] ? sec : "overview";
  if (push) history.replaceState(null, "", "#" + S.sec);
  $("#nav").innerHTML = SECTIONS.map(([id, ic, name]) => `<button type="button" class="nav-item ${id === S.sec ? "active" : ""}" data-sec="${id}" aria-current="${id === S.sec ? "page" : "false"}"><span aria-hidden="true">${ic}</span> ${esc(name)}</button>`).join("");
  const m = $("#main");
  m.innerHTML = na("Loading…");
  RENDER[S.sec](m).catch((e) => { console.error(e); m.innerHTML = na("Something went wrong loading this section"); });
}
async function tick() {
  await pollVerify();
  if (S.sec === "hours") refreshReqs();
  if (S.sec === "safety") refreshFeed();
  if (S.sec === "overview" && !document.querySelector("#main :focus")) { const m = $("#main"); renderOverview(m).catch(() => {}); }
  if (S.sec === "voice" && !document.querySelector("#main :focus")) renderVoice($("#main")).catch(() => {});
}
async function boot() {
  const [site, w] = await Promise.all([api("/site"), api("/workers")]);
  if (site.ok) $("#site").textContent = `${site.data.name} · ${site.data.site_id} · ${site.data.state} · ${fmtDay(site.data.demo_day, "en-IN", { day: "numeric", month: "short", year: "numeric" })}`;
  if (w.ok) { S.workers = w.data; w.data.forEach((x) => (S.names[x.id] = x.name)); }
  $("#nav").onclick = (e) => { const b = e.target.closest("[data-sec]"); if (b) go(b.dataset.sec); };
  document.body.addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) askReason(b.dataset.open); });
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  $("#demoToggle").onclick = () => { const p = $("#demoPanel"); p.classList.toggle("hidden"); $("#demoToggle").setAttribute("aria-expanded", !p.classList.contains("hidden")); };
  $("#demoPanel").onclick = async (e) => {
    const b = e.target.closest("[data-demo]"); if (!b) return;
    const d = b.dataset.demo;
    const r = d === "reset" ? await api("/demo/reset", { method: "POST" }) : d === "tamper" ? await api("/demo/tamper", { method: "POST", body: {} }) : await api(`/ledger/roots/publish?day=${DEMO_DAY}`, { method: "POST" });
    toast(!r.ok ? `Failed: ${r.error}` : d === "reset" ? `Demo reset · ${r.data.n_events} events` : d === "tamper" ? (r.data.ok ? `Edited #${r.data.seq} in SQL: ${hm(r.data.old_ts)} → ${hm(r.data.new_ts)}` : r.data.error) : `Root published for ${r.data.day} · ${r.data.n_events} events`);
    S.lastResults = null; S.payRun = null;
    await pollVerify(); go(S.sec, false);
  };
  window.addEventListener("hashchange", () => go(location.hash.slice(1), false));
  await pollVerify();
  go((location.hash || "#overview").slice(1), false);
  setInterval(tick, 3000);
}
boot();
