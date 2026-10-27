// Skills screen: verified skill credentials (QR, verifiable offline) and progress towards the next level.
import { api, esc, rupees, num } from "/shared/api.js";
import { term } from "/shared/i18n.js";
import { S, L, day } from "../state.js";
import { unavailable } from "../ui.js";

/** Normalise the credential shapes the API may return. */
function credParts(c) {
  const vc = c.vc || c.credential || c;
  const sub = vc.credentialSubject || vc.subject || {};
  const skillObj = typeof sub.skill === "object" && sub.skill ? sub.skill : {};
  const skill = skillObj.name || skillObj.skill || (typeof sub.skill === "string" ? sub.skill : "") || sub.operation || c.skill || "";
  const level = skillObj.level || sub.level || c.level || "";
  const id = c.credential_id || c.id || vc.id || "";
  const issued = vc.validFrom || vc.issuanceDate || c.issued_at || c.ts || "";
  return { skill, level, id, issued };
}

const pairs = (o, fmt = (v) => v) => (typeof o === "string" ? o : Object.entries(o).map(([k, v]) => `${k} ${fmt(v)}`).join(" · "));

function credCard(c) {
  const { skill, level, id, issued } = credParts(c);
  // Safety inductions carry no ILUO level: show the credential's own label instead.
  const title = level
    ? L("cred_title", { level: term(S.lang, "lv_", level), skill: term(S.lang, "sk_", skill) })
    : ((c.credentialSubject && c.credentialSubject.skillLabel) || String(skill || "").replace(/_/g, " "));
  return `<section class="card cred" data-say="${esc(L("verified_skill"))}: ${esc(title)}">
    <span class="chip ok">✓ ${esc(L("verified_skill"))}</span>
    <h2 class="cred-title">${esc(title)}</h2>
    ${issued ? `<p class="muted small">${esc(L("issued", { date: day(issued) }))}</p>` : ""}
    <img class="qr" alt="${esc(L("verified_skill"))}: ${esc(title)} — QR" width="180" height="180" src="/api/passport/credentials/${encodeURIComponent(id)}/qr">
    <p class="small">${esc(L("scan_note"))}</p>
    <p class="mono small id-line">${esc(id)}</p>
    <a class="btn link-btn" href="/verify/" target="_blank" rel="noopener">🔎 ${esc(L("open_verify"))}</a>
  </section>`;
}

function progressItem(p) {
  const needed = p.days_needed || 0, met = p.days_met || 0;
  const pct = needed ? Math.min(100, (met / needed) * 100) : p.met ? 100 : 0;
  const band = p.pay_band || p.band || p.skill_band;
  const title = L("cred_title", { level: term(S.lang, "lv_", p.level), skill: term(S.lang, "sk_", p.skill) });
  const days = L("days_progress", { met, needed });
  return `<li data-say="${esc(title)}: ${esc(days)}">
    <div class="row-between"><b>${p.met ? "✓ " : ""}${esc(title)}</b><span class="small">${esc(days)}</span></div>
    <div class="meter" role="progressbar" aria-label="${esc(title)}" aria-valuemin="0" aria-valuemax="${esc(needed || 100)}" aria-valuenow="${esc(needed ? met : Math.round(pct))}"><i style="width:${pct}%"></i></div>
    ${band || p.pay ? `<div class="small">💰 ${esc(L("pay_band", { band: band ? term(S.lang, "band_", band) : "" }))}${p.pay ? " · " + esc(rupees(p.pay)) : ""}${p.min_wage ? " · " + esc(rupees(p.min_wage)) : ""}</div>` : ""}
    ${p.criteria ? `<div class="small muted">${esc(pairs(p.criteria))}${p.current ? ` · now ${esc(pairs(p.current, (v) => (typeof v === "number" ? num(v, 2) : v)))}` : ""}</div>` : ""}
  </li>`;
}

export async function renderSkills(el) {
  const r = await api(`/passport/${S.wid}`);
  let html = `<h1 class="screen-title">🎓 ${esc(L("skills_title"))}</h1>`;
  if (!r.ok) { el.innerHTML = html + unavailable(); return; }
  const creds = r.data.credentials || [];
  html += creds.length ? creds.map(credCard).join("") : `<div class="card empty">${esc(L("no_creds"))}</div>`;
  const prog = r.data.progress || [];
  if (prog.length) html += `<section class="card"><h2>📈 ${esc(L("next_skills"))}</h2><ul class="progress">${prog.map(progressItem).join("")}</ul></section>`;
  el.innerHTML = html;
  // A missing QR image degrades to a labelled placeholder instead of a broken-image icon.
  el.querySelectorAll("img.qr").forEach((img) => img.addEventListener("error", () => {
    const d = document.createElement("div");
    d.className = "qr qr-missing"; d.textContent = "QR"; d.setAttribute("role", "img"); d.setAttribute("aria-label", img.alt);
    img.replaceWith(d);
  }, { once: true }));
}
