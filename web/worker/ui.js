// Worker app: shared HTML fragments (empty states, skeletons, evidence chips, event/topic icons). All text goes through esc().
import { esc, hm } from "/shared/api.js";
import { L } from "./state.js";
import { icon } from "./icons.js";

const TYPE_ICON = { "punch.in": "login", "punch.out": "logout", "punch.correction": "edit", "access.lookup": "eye",
  "ot.request": "clock", "ot.consent": "hand", "ot.cap_check": "clock", "pay.run": "rupee", "credential.issued": "badge",
  "credential.revoked": "badge", "production.count": "thread" };
const TOPIC_ICON = { water: "droplet", toilets: "users", toilet: "users", heat: "thermo", harassment: "stop", wages: "rupee",
  pay: "rupee", safety: "alert", food: "bowl", overtime: "clock", ot: "clock", fire: "flame", exits: "door", leave: "calendar",
  canteen: "bowl", other: "chat" };

/** SVG icon for a receipt (ledger event) type. */
export const typeIcon = (type) => icon(TYPE_ICON[type] || "receipt");
/** SVG icon for a Voice topic. */
export const topicIcon = (id) => icon(TOPIC_ICON[id] || "chat");

/** Card shown when an API is not reachable yet. */
export function unavailable(msg) {
  return `<div class="card empty">${icon("clock")} ${esc(msg || L("not_available"))}</div>`;
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
