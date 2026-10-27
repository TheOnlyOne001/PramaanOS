// Employer console: shared HTML fragments. All server text goes through esc() before reaching the DOM.
import { esc } from "/shared/api.js";

export const SEV = { critical: ["crit", "⛔", "Critical"], high: ["warn", "⚠", "High"], medium: ["info", "ℹ", "Medium"] };
export const KIND = { restricted_zone_entry: "restricted entry", ppe_noncompliance: "PPE missing", ppe_compliance_rate: "PPE compliance",
  fire_smoke: "fire / smoke", blocked_exit: "blocked exit", person_down: "person down", queue_length: "queue length", near_miss: "near miss", heat_wbgt: "heat (WBGT)" };

/** Empty / unavailable state card. */
export const na = (what) => `<div class="card empty">🕓 ${esc(what || "Not available yet")}</div>`;

/** Skeleton shown while a section loads. */
export const loading = () => `<div class="card skeleton" role="status"><span class="sr">Loading…</span>
  <i class="sk-line w40"></i><i class="sk-line w90"></i><i class="sk-line w60"></i></div>`;

/** Link to a signed ledger event; opens the evidence modal. */
export const ev = (seq, ref) => seq == null ? "" : `<a class="ref" href="/api/ledger/events/${encodeURIComponent(seq)}" data-event="${esc(seq)}" aria-label="Evidence: ledger event ${esc(seq)}${ref ? " " + esc(ref) : ""}">#${esc(seq)}${ref ? " · " + esc(ref) : ""}</a>`;
export const evList = (l) => Array.isArray(l) && l.length ? `<span class="evid">${l.slice(0, 5).map((s) => ev(s)).join(" ")}${l.length > 5 ? ` +${l.length - 5}` : ""}</span>` : "";

export const short = (h, n = 16) => { const x = String(h || ""); return x.length > n ? x.slice(0, n) + "…" : x || "—"; };
/** Status chip: always icon + word, never colour alone. */
export const chip = (cls, icon, word) => `<span class="chip ${cls}"><span aria-hidden="true">${icon}</span> ${esc(word)}</span>`;
export const capChip = (s) => s === "over" ? chip("crit", "⛔", "Over cap") : s === "near" ? chip("warn", "⚠", "Near cap") : chip("ok", "✓", "OK");
export const meterCls = (s) => (s === "over" ? "crit" : s === "near" ? "warn" : "");
export const zoneName = (z) => { const s = String(z || "").replace(/[_-]/g, " "); return s.charAt(0).toUpperCase() + s.slice(1) + (/zone/i.test(s) ? "" : " zone"); };
/** English label from a {lang: text} object or a plain string. */
export const label = (l) => (l && typeof l === "object" ? l.en || Object.values(l)[0] : l) || "";
export const responseText = (r) => (typeof r === "string" ? r : r.text || r.we_did);

/** Replace innerHTML only when it changed, keeping focus on the same control across re-renders. */
export function setHTML(el, html) {
  if (el._html === html) return;
  el._html = html;
  const a = document.activeElement;
  const had = el.contains(a) && a.dataset;
  const key = had && (a.dataset.roots !== undefined ? "[data-roots]" : a.dataset.open ? `[data-open="${a.dataset.open}"]` : null);
  el.innerHTML = html;
  if (key) { const n = el.querySelector(key); if (n) n.focus(); }
}

/** Give each body cell a data-label from its column header (used by the stacked-card layout on phones). */
export function labelTables(root) {
  root.querySelectorAll("table:not([data-labelled])").forEach((t) => {
    const heads = [...t.querySelectorAll("thead th")].map((th) => th.textContent.trim());
    if (!heads.length) { t.dataset.labelled = "kv"; return; }
    t.querySelectorAll("tbody tr").forEach((tr) => [...tr.children].forEach((td, i) => { if (heads[i]) td.dataset.label = heads[i]; }));
    t.dataset.labelled = "1";
    t.classList.add("stack");
  });
}
