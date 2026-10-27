// Worker app: shared HTML fragments (empty states, evidence chips, icons). All text goes through esc().
import { esc, hm } from "/shared/api.js";
import { L } from "./state.js";

export const TYPE_ICON = { "punch.in": "🟢", "punch.out": "🏠", "punch.correction": "✏️", "access.lookup": "👁️",
  "ot.request": "⏱️", "ot.consent": "✋", "ot.cap_check": "⏱️", "pay.run": "💰", "credential.issued": "🎓",
  "credential.revoked": "🎓", "production.count": "🧵" };
export const TOPIC_ICON = { water: "💧", toilets: "🚻", toilet: "🚻", heat: "🌡️", harassment: "🛑", wages: "₹", pay: "₹",
  safety: "⚠️", food: "🍲", overtime: "⏱️", ot: "⏱️", fire: "🔥", exits: "🚪", leave: "📅", canteen: "🍲", other: "💬" };

/** Card shown when an API is not reachable yet. */
export function unavailable(msg) {
  return `<div class="card empty"><span aria-hidden="true">🕓</span> ${esc(msg || L("not_available"))}</div>`;
}

/** Skeleton placeholder shown while a screen loads. */
export function loading() {
  return `<div class="card skeleton" role="status"><span class="sr">${esc(L("loading"))}</span>
    <i class="sk-line w60"></i><i class="sk-line w90"></i><i class="sk-line w40"></i></div>`;
}

/** Link to one signed ledger event. */
export function refChip(seq, ref) {
  if (seq === undefined || seq === null) return "";
  const text = ref || `#${seq}`;
  return `<a class="ref" href="/api/ledger/events/${encodeURIComponent(seq)}" target="_blank" rel="noopener" title="Ledger event #${esc(seq)}">${esc(text)}</a>`;
}

/** Up to six evidence links, then "+N". */
export function evidenceChips(list) {
  if (!Array.isArray(list) || !list.length) return "";
  const shown = list.slice(0, 6).map((s) => refChip(s, `#${s}`)).join(" ");
  const more = list.length > 6 ? ` <span class="muted">+${list.length - 6}</span>` : "";
  return `<div class="evidence"><span class="muted">${esc(L("evidence"))}:</span> ${shown}${more}</div>`;
}

/** "HH:MM" from either an ISO timestamp or a bare time. */
export function hmOf(v) {
  if (!v) return "—";
  return String(v).length >= 16 ? hm(v) : String(v).slice(0, 5);
}
