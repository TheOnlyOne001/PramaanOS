// Saakshi employer console. Opens on exceptions. All server text goes through esc() before reaching the DOM.
// Entry point: registers sections (sections/*.js), wires global handlers and the demo panel, polls every 3 s.
import { api, hm, fmtDay, toast } from "/shared/api.js";
import { S, $, DEMO_DAY } from "./state.js";
import { registerSections, go } from "./router.js";
import { pollVerify } from "./integrity.js";
import { askReason, showEvent, showRoots, showHelp, closeModal, trapTab, isModalOpen } from "./modals.js";
import { onShortcut, shortcutList } from "./shortcuts.js";
import { labelTables } from "./ui.js";
import { renderOverview } from "./sections/overview.js";
import { renderHours, refreshReqs } from "./sections/hours.js";
import { renderPay } from "./sections/pay.js";
import { renderSkills } from "./sections/skills.js";
import { renderSafety, refreshFeed } from "./sections/safety.js";
import { renderVoice } from "./sections/voice.js";
import { renderSdg } from "./sections/sdg8.js";

registerSections({ overview: renderOverview, hours: renderHours, pay: renderPay, skills: renderSkills, safety: renderSafety, voice: renderVoice, sdg8: renderSdg });

const mainIdle = () => !document.querySelector("#main :focus");

async function tick() {
  await pollVerify();
  if (isModalOpen()) return; // keep the modal's trigger in the DOM so focus can return to it
  if (S.sec === "hours") refreshReqs();
  if (S.sec === "safety") refreshFeed();
  if (S.sec === "overview" && mainIdle()) renderOverview($("#main")).catch(() => {});
  if (S.sec === "voice" && mainIdle()) renderVoice($("#main")).catch(() => {});
}

async function runDemo(action) {
  if (action === "reset") S.tamper = {};
  if (action === "reset") return [await api("/demo/reset", { method: "POST" }), (d) => `Demo reset · ${d.n_events} events`];
  if (action === "tamper") {
    const r = await api("/demo/tamper", { method: "POST", body: {} });
    if (r.ok && r.data.ok) S.tamper[r.data.seq] = { ...r.data, at: new Date().toISOString() };
    return [r, (d) => (d.ok ? `Edited #${d.seq} in SQL: ${hm(d.old_ts)} → ${hm(d.new_ts)}` : d.error)];
  }
  return [await api(`/ledger/roots/publish?day=${DEMO_DAY}`, { method: "POST" }), (d) => `Root published for ${d.day} · ${d.n_events} events`];
}

function wireHandlers() {
  $("#nav").onclick = (e) => {
    const b = e.target.closest("[data-sec]");
    if (!b) return;
    go(b.dataset.sec);
    setTimeout(() => { const n = $(`#nav [data-sec="${b.dataset.sec}"]`); if (n) n.focus(); }, 0);
  };
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); trapTab(e); onShortcut(e); });
  $("#helpBtn").onclick = () => showHelp(shortcutList());
  document.body.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-event]");
    if (a && !e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); showEvent(a.dataset.event); return; }
    const o = e.target.closest("[data-open]");
    if (o) askReason(o.dataset.open);
    if (e.target.closest("[data-close]")) closeModal();
    if (e.target.closest("[data-roots]")) showRoots();
  });
  $("#demoToggle").onclick = () => {
    const p = $("#demoPanel");
    p.classList.toggle("hidden");
    $("#demoToggle").setAttribute("aria-expanded", !p.classList.contains("hidden"));
  };
  $("#demoPanel").onclick = async (e) => {
    const b = e.target.closest("[data-demo]");
    if (!b) return;
    const [r, msg] = await runDemo(b.dataset.demo);
    toast(r.ok ? msg(r.data) : `Failed: ${r.error}`);
    S.lastResults = null; S.payRun = null;
    await pollVerify(); go(S.sec, false);
  };
  window.addEventListener("hashchange", () => go(location.hash.slice(1), false));
}

/** "updated 2 s ago" next to the live status, so a stalled poll is visible. */
function tickAge() {
  const el = $("#updated");
  if (!el || !S.lastPoll) return;
  const s = Math.max(0, Math.round((Date.now() - S.lastPoll) / 1000));
  el.textContent = s < 2 ? "updated just now" : s < 120 ? `updated ${s} s ago` : `updated ${Math.round(s / 60)} min ago`;
  el.classList.toggle("stale", s > 10);
}

async function boot() {
  const [site, w] = await Promise.all([api("/site"), api("/workers")]);
  if (site.ok) $("#site").textContent = `${site.data.name} · ${site.data.site_id} · ${site.data.state} · ${fmtDay(site.data.demo_day, "en-IN", { day: "numeric", month: "short", year: "numeric" })}`;
  if (w.ok) { S.workers = w.data; w.data.forEach((x) => (S.names[x.id] = x.name)); }
  wireHandlers();
  await pollVerify();
  go((location.hash || "#overview").slice(1), false);
  setInterval(tick, 3000);
  setInterval(tickAge, 1000);
  // Small screens show tables as stacked cards: each cell carries its column name.
  new MutationObserver(() => labelTables(document)).observe(document.body, { childList: true, subtree: true });
  labelTables(document);
}

boot();
