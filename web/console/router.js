// Console router: shows one section at a time. Sections register here so they can navigate without import cycles.
import { esc } from "/shared/api.js";
import { S, $, SECTIONS } from "./state.js";
import { na, loading } from "./ui.js";

const RENDER = {};

/** Register the section renderers: {id: async (mainEl) => void}. */
export function registerSections(map) { Object.assign(RENDER, map); }

export function go(sec, push = true) {
  S.sec = RENDER[sec] ? sec : "overview";
  if (push) history.replaceState(null, "", "#" + S.sec);
  $("#nav").innerHTML = SECTIONS.map(([id, ic, name]) => `<button type="button" class="nav-item ${id === S.sec ? "active" : ""}" data-sec="${id}" ${id === S.sec ? 'aria-current="page"' : ""}><span aria-hidden="true">${ic}</span> ${esc(name)}</button>`).join("");
  const m = $("#main");
  m.setAttribute("aria-busy", "true");
  m.innerHTML = loading();
  RENDER[S.sec](m)
    .catch((e) => { console.error(e); m.innerHTML = na("Something went wrong loading this section"); })
    .finally(() => m.setAttribute("aria-busy", "false"));
}

/** Move focus to the section heading (after navigation or closing a dialog). */
export function focusHeading() {
  const h = $("#main h1") || $("#main");
  if (h) { h.setAttribute("tabindex", "-1"); h.focus(); }
}
