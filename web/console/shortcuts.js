// Console keyboard shortcuts: "?" opens help, "g" then a letter jumps to a section, Esc closes dialogs.
// Ignored while typing in a field or when a modifier key is held, so they never steal text input.
import { go, focusHeading } from "./router.js";
import { showHelp, isModalOpen } from "./modals.js";
import { SECTIONS } from "./state.js";

/** [key, section id] pairs for "g <key>". */
const JUMPS = [["o", "overview"], ["h", "hours"], ["p", "pay"], ["s", "skills"], ["c", "safety"], ["v", "voice"], ["8", "sdg8"]];
const CHORD_MS = 1200;
let pendingG = 0;

const typing = (t) => t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
const nameOf = (id) => (SECTIONS.find((s) => s[0] === id) || [id, "", id])[2];

/** Rows for the help dialog: [key, section name]. */
export const shortcutList = () => JUMPS.map(([k, id]) => [k, nameOf(id)]);

export function onShortcut(e) {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
  if (e.key === "?") { e.preventDefault(); if (!isModalOpen()) showHelp(shortcutList()); return; }
  if (isModalOpen()) return;
  const now = Date.now();
  if (pendingG && now - pendingG < CHORD_MS) {
    pendingG = 0;
    const hit = JUMPS.find(([k]) => k === e.key.toLowerCase());
    if (hit) { e.preventDefault(); go(hit[1]); setTimeout(focusHeading, 350); }
    return;
  }
  pendingG = e.key === "g" ? now : 0;
}
