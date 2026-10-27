// Worker app shell: header (name, language, read aloud), bottom tabs and the integrity banner.
import { esc } from "/shared/api.js";
import { LANGS, LANG_NAMES } from "/shared/i18n.js";
import { S, L, $ } from "./state.js";
import { icon } from "./icons.js";

export const TABS = [
  { id: "today", icon: "sun" }, { id: "pay", icon: "rupee" }, { id: "hours", icon: "clock" },
  { id: "skills", icon: "badge" }, { id: "voice", icon: "megaphone" }, { id: "rights", icon: "scales" },
];

/** "My copy · 42": how many of her receipts this phone holds (icon + word + number). */
export function renderCopy() {
  const el = $("#myCopy");
  if (!el) return;
  el.innerHTML = `${icon("phone")}<span class="copy-word">${esc(L("my_copy"))}</span><b>${esc(S.held)}</b>`;
  el.title = L("my_copy_count", { n: S.held });
  el.setAttribute("aria-label", L("my_copy_count", { n: S.held }));
}
const TITLE = "Saakshi · சாட்சி";

export function renderShell() {
  document.documentElement.lang = S.lang;
  const w = S.worker || { name: S.wid };
  $("#avatar").textContent = (w.name || "?").slice(0, 1);
  $("#whoName").textContent = L("hello", { name: (w.name || "").split(" ")[0] });
  $("#whoSub").innerHTML = `<span class="mono">${esc(S.wid)}</span> · ${esc(w.role || "")}`;
  $("#speakLabel").textContent = L("read_aloud");
  $("#speakSub").textContent = L("bhashini");
  $("#langLabel").textContent = L("language");
  renderCopy();
  $("#lang").innerHTML = LANGS.map((l) => `<option value="${l}" ${l === S.lang ? "selected" : ""}>${LANG_NAMES[l]}</option>`).join("");
  $("#tabs").innerHTML = TABS.map((tb) => `
    <button type="button" class="tab ${tb.id === S.tab ? "active" : ""}" data-tab="${tb.id}" aria-current="${tb.id === S.tab ? "page" : "false"}">
      <span class="tab-icon">${icon(tb.icon)}</span><span class="tab-label">${esc(L("tab_" + tb.id))}</span>
      ${tb.id === "today" && S.pending.length ? `<span class="badge" aria-label="pending">${S.pending.length}</span>` : ""}
    </button>`).join("");
}

/** The red banner shown when one of her receipts no longer matches the employer's record. */
export function renderBanner() {
  const el = $("#banner");
  if (!S.mismatches.length) { el.innerHTML = ""; el.className = ""; document.title = TITLE; return; }
  const own = S.worker && S.lang === S.worker.lang;
  const seg = (s) => String(s || "").split(" · ")[0];
  const rows = S.mismatches.map((m) => {
    if (m.kind === "deleted") return `<p>${esc(L("integrity_deleted", { ref: m.ref || "#" + m.seq }))}</p>`;
    const mine = seg(own ? m.receipt_text : m.receipt_text_en);
    let theirs = seg(own ? m.current_text : m.current_text_en);
    // "Out 18:04" vs "Out 17:30": show only the time on the employer's side when the label matches.
    const a = mine.match(/^(.*?)(\d{1,2}:\d{2})$/), b = theirs.match(/^(.*?)(\d{1,2}:\d{2})$/);
    if (a && b && a[1] === b[1]) theirs = b[2];
    return `<p class="int-body">${esc(L("integrity_body", { mine, theirs }))}</p>
      <p class="int-note">${esc(L("integrity_note", { ref: m.ref || "#" + m.seq }))} <span class="mono">#${esc(m.seq)}</span></p>`;
  }).join("");
  const source = S.checkSource === "phone" ? L("check_local") : L("check_server");
  el.className = "integrity";
  el.innerHTML = `<div class="int-inner" data-say>
    <div class="int-head"><span class="int-icon">${icon("alert")}</span><b>${esc(L("integrity_title"))}</b></div>${rows}
    <p class="int-source">${icon("phone")}<span>${esc(source)}</span></p></div>`;
  document.title = "⚠ " + L("integrity_title");
}
