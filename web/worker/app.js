// Saakshi worker app: one worker's own copy of her work record.
// Entry point: wires the shell, routes between screens (screens/*.js), keeps her receipts on the phone
// (store.js), checks them against the employer's record, and works offline (net.js + sw.js).
import { api } from "/shared/api.js";
import { LANGS } from "/shared/i18n.js";
import { S, L, $, qs, POLL_MS } from "./state.js";
import { unavailable, loading } from "./ui.js";
import { speak, screenSpeech } from "./speech.js";
import { TABS, renderShell, renderBanner, renderCopy } from "./shell.js";
import { allReceipts, keepReceipts } from "./store.js";
import { initNet, markNet, renderNet } from "./net.js";
import { renderToday, refreshToday, refreshPending, refreshReceipts, renderCopyLine } from "./screens/today.js";
import { renderPay } from "./screens/pay.js";
import { renderHours } from "./screens/hours.js";
import { renderSkills } from "./screens/skills.js";
import { renderVoice, loadCases, pollCases } from "./screens/voice.js";
import { renderRights } from "./screens/rights.js";

const SCREENS = { today: renderToday, pay: renderPay, hours: renderHours, skills: renderSkills, voice: renderVoice, rights: renderRights };

async function renderScreen() {
  const el = $("#screen");
  el.setAttribute("aria-busy", "true");
  el.classList.remove("enter");
  el.innerHTML = loading();
  try { await SCREENS[S.tab](el); } catch (e) { console.error(e); el.innerHTML = unavailable(L("error")); }
  el.setAttribute("aria-busy", "false");
  void el.offsetWidth;  // restart the (reduced-motion-aware) enter transition
  el.classList.add("enter");
}

function setTab(id, push = true) {
  S.tab = TABS.some((x) => x.id === id) ? id : "today";
  if (push) history.replaceState(null, "", `?w=${S.wid}${qs.get("lang") ? "&lang=" + qs.get("lang") : ""}#${S.tab}`);
  renderShell();
  renderScreen();
  window.scrollTo(0, 0);
}

/**
 * Compare HER copy (the receipts held on this phone) with the employer's current record. Only when this
 * phone holds nothing yet does the server fall back to the copy it delivered. Mismatch texts come from her
 * copy, so the banner quotes what she was sent, not what the server says it sent.
 */
async function pollIntegrity() {
  const held = await allReceipts(S.wid);
  S.held = held.length;
  const body = held.length ? { receipts: held.map((x) => ({ seq: x.seq, hash: x.hash })) } : {};
  const r = await api(`/workers/${S.wid}/receipts/check`, { method: "POST", body });
  if (!r.ok) { if (r.status === 0) markNet(true); return; }
  markNet(false);
  const mine = new Map(held.map((x) => [x.seq, x]));
  const next = (r.data.mismatches || []).map((m) => {
    const h = mine.get(m.seq);
    return h ? { ...m, ref: m.ref || h.ref, receipt_text: m.receipt_text || h.text, receipt_text_en: m.receipt_text_en || h.text_en } : m;
  });
  const source = held.length ? "phone" : "server";
  const sourceChanged = source !== S.checkSource || r.data.checked !== S.checked;
  S.checkSource = source;
  S.checked = r.data.checked || 0;
  if (sourceChanged) document.dispatchEvent(new CustomEvent("saakshi:copy"));
  const sig = (list) => JSON.stringify(list.map((m) => m.seq + m.current_hash));
  if (sig(next) === sig(S.mismatches)) return;
  S.mismatches = next;
  S.mismatchChanged = true;
  renderBanner();
  renderCopyLine();
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
    else { await syncReceipts(); await refreshPending(); }
    if (S.tab === "voice") await pollCases();
  } finally { polling = false; }
}

/** Pull the receipts delivered to her (e.g. while another tab was open) onto the phone. */
async function syncReceipts(limit = 40) {
  const r = await api(`/workers/${S.wid}/receipts?limit=${limit}`);
  if (r.ok) await keepReceipts(r.data);
}

function pickLanguage() {
  let saved = null;
  try { saved = localStorage.getItem("saakshi-lang-" + S.wid); } catch { /* storage off */ }
  const q = qs.get("lang");
  return [q, saved, S.worker.lang].find((l) => LANGS.includes(l)) || "en";
}

async function boot() {
  initNet(() => { renderScreen(); pollIntegrity(); });
  document.addEventListener("saakshi:copy", () => { renderCopy(); renderCopyLine(); if (S.mismatches.length) renderBanner(); });
  const [w, all] = await Promise.all([api(`/workers/${S.wid}`), api("/workers")]);
  if (all.ok) all.data.forEach((x) => (S.names[x.id] = x.name));
  S.worker = w.ok ? w.data : { id: S.wid, name: S.wid, lang: "en" };
  S.lang = pickLanguage();
  renderNet();
  loadCases();
  $("#lang").onchange = (e) => {
    S.lang = e.target.value;
    try { localStorage.setItem("saakshi-lang-" + S.wid, S.lang); } catch { /* storage off */ }
    renderShell(); renderBanner(); renderNet(); renderScreen();
  };
  $("#tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) setTab(b.dataset.tab); };
  $("#speak").onclick = () => speak(screenSpeech());
  window.addEventListener("hashchange", () => setTab(location.hash.slice(1), false));
  await syncReceipts(500);  // her whole delivered history onto the phone before the first check
  setTab((location.hash || "#today").slice(1), false);
  await pollIntegrity();
  setInterval(tick, POLL_MS);
}

boot();
