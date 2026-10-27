// Saakshi worker app: one worker's own copy of her work record.
// Entry point: wires the shell, routes between screens (screens/*.js) and polls for integrity changes.
import { api } from "/shared/api.js";
import { LANGS } from "/shared/i18n.js";
import { S, L, $, qs, POLL_MS } from "./state.js";
import { unavailable, loading } from "./ui.js";
import { speak, screenSpeech } from "./speech.js";
import { TABS, renderShell, renderBanner } from "./shell.js";
import { renderToday, refreshToday, refreshPending, refreshReceipts } from "./screens/today.js";
import { renderPay } from "./screens/pay.js";
import { renderHours } from "./screens/hours.js";
import { renderSkills } from "./screens/skills.js";
import { renderVoice, loadCases, pollCases } from "./screens/voice.js";
import { renderRights } from "./screens/rights.js";

const SCREENS = { today: renderToday, pay: renderPay, hours: renderHours, skills: renderSkills, voice: renderVoice, rights: renderRights };

async function renderScreen() {
  const el = $("#screen");
  el.setAttribute("aria-busy", "true");
  el.innerHTML = loading();
  try { await SCREENS[S.tab](el); } catch (e) { console.error(e); el.innerHTML = unavailable(L("error")); }
  el.setAttribute("aria-busy", "false");
}

function setTab(id, push = true) {
  S.tab = TABS.some((x) => x.id === id) ? id : "today";
  if (push) history.replaceState(null, "", `?w=${S.wid}${qs.get("lang") ? "&lang=" + qs.get("lang") : ""}#${S.tab}`);
  renderShell();
  renderScreen();
  window.scrollTo(0, 0);
}

/** Compare her receipts with the employer's current record; redraw what depends on it when that changes. */
async function pollIntegrity() {
  const r = await api(`/workers/${S.wid}/receipts/check`, { method: "POST", body: {} });
  if (!r.ok) return;
  const next = r.data.mismatches || [];
  const sig = (list) => JSON.stringify(list.map((m) => m.seq + m.current_hash));
  if (sig(next) === sig(S.mismatches)) return;
  S.mismatches = next;
  S.mismatchChanged = true;
  renderBanner();
  if (S.tab === "pay") renderScreen();
  if (S.tab === "today") refreshReceipts();
}

let polling = false;
async function tick() {
  if (polling) return;
  polling = true;
  try {
    await pollIntegrity();
    if (S.tab === "today") await refreshToday();
    else await refreshPending();
    if (S.tab === "voice") await pollCases();
  } finally { polling = false; }
}

function pickLanguage() {
  let saved = null;
  try { saved = localStorage.getItem("saakshi-lang-" + S.wid); } catch { /* storage off */ }
  const q = qs.get("lang");
  return [q, saved, S.worker.lang].find((l) => LANGS.includes(l)) || "en";
}

async function boot() {
  const [w, all] = await Promise.all([api(`/workers/${S.wid}`), api("/workers")]);
  if (all.ok) all.data.forEach((x) => (S.names[x.id] = x.name));
  S.worker = w.ok ? w.data : { id: S.wid, name: S.wid, lang: "en" };
  S.lang = pickLanguage();
  loadCases();
  $("#lang").onchange = (e) => {
    S.lang = e.target.value;
    try { localStorage.setItem("saakshi-lang-" + S.wid, S.lang); } catch { /* storage off */ }
    renderShell(); renderBanner(); renderScreen();
  };
  $("#tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) setTab(b.dataset.tab); };
  $("#speak").onclick = () => speak(screenSpeech());
  window.addEventListener("hashchange", () => setTab(location.hash.slice(1), false));
  setTab((location.hash || "#today").slice(1), false);
  await pollIntegrity();
  setInterval(tick, POLL_MS);
}

boot();
