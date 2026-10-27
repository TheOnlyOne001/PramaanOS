// Voice: anonymous themes that reach management only once corroborated, and the "You said, we did" board.
import { api, esc, hm, toast } from "/shared/api.js";
import { na, chip, label, responseText } from "../ui.js";

function themeCard(t) {
  const status = t.published ? chip("ok", "✓", `${t.count} independent reports · no names`) : chip("neutral", "⏳", `waiting for corroboration (${t.count} of ${t.threshold})`);
  const respond = t.response
    ? `<p>✅ <b>${esc(responseText(t.response))}</b></p>`
    : `<form class="respond" data-topic="${esc(t.topic)}"><label>Response (“we did”) <input type="text" name="text" required placeholder="e.g. Second water cooler installed on Line 4"></label><button class="btn primary" type="submit">Publish response</button></form>`;
  return `<section class="card theme"><div class="rowb"><h2>${esc(label(t.label) || t.topic)}</h2>${status}${t.safety_critical ? chip("warn", "⚠", "Safety") : ""}</div>
    ${t.published ? `<ul class="quotes">${(t.reports || []).map((x) => `<li>“${esc(x.text)}” <span class="muted small">${esc(hm(x.ts))}</span></li>`).join("")}</ul>${respond}` : `<p class="muted small">Report text stays hidden until corroborated.</p>`}</section>`;
}

export async function renderVoice(m) {
  const [th, board] = await Promise.all([api("/voice/themes"), api("/voice/board")]);
  m.innerHTML = `<h1>Voice <span class="muted small">anonymous, corroborated</span></h1>
    <p class="muted">A theme appears only once enough independent workers report it. No names, no IDs, ever.</p>
    <div id="themes">${th.ok ? th.data.map(themeCard).join("") || na("No themes yet") : na("Voice themes not available yet")}</div>
    <section class="card"><h2>You said, we did</h2>${board.ok ? board.data.map((b) => `<div class="board-row"><span class="muted small">You said</span> ${esc(b.you_said)}<br><span class="small">✅ We did</span> <b>${esc(b.we_did)}</b> <span class="muted small">${esc(b.by || "")}</span></div>`).join("") || `<p class="muted">Nothing yet.</p>` : na()}</section>`;
  m.querySelectorAll("form.respond").forEach((f) => (f.onsubmit = async (e) => {
    e.preventDefault();
    const r = await api(`/voice/themes/${encodeURIComponent(f.dataset.topic)}/respond`, { method: "POST", body: { text: new FormData(f).get("text"), by: "Management" } });
    toast(r.ok ? "Response published to the board" : `Not available yet (${r.error})`);
    if (r.ok) renderVoice(m);
  }));
}
