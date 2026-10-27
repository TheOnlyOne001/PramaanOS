// Worker app: offline support. Registers the service worker and shows "Offline — showing your saved copy"
// whenever the network is gone (browser says so, a read was served from the phone's copy, or a call failed).
import { esc } from "/shared/api.js";
import { S, L, $ } from "./state.js";
import { icon } from "./icons.js";

let offline = !navigator.onLine;
let onRecover = () => {};

/** Show or clear the offline banner in the current language. */
export function renderNet() {
  const el = $("#net");
  if (!el) return;
  document.documentElement.classList.toggle("is-offline", offline);
  el.innerHTML = offline ? `<div class="net-inner">${icon("wifiOff")}<span>${esc(L("offline"))}</span></div>` : "";
}

/** Record what the last network attempt told us; recovering from offline refreshes the screen. */
export function markNet(isOffline) {
  if (isOffline === offline) return;
  offline = isOffline;
  renderNet();
  if (!offline) onRecover();
}

export const isOffline = () => offline;

/** Register the service worker (feature-detected) and listen for connectivity changes. */
export function initNet(recover) {
  onRecover = recover || onRecover;
  window.addEventListener("offline", () => markNet(true));
  window.addEventListener("online", () => markNet(false));
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (e) => {
      if (e.data && e.data.type === "saakshi-net") markNet(Boolean(e.data.offline) || !navigator.onLine);
    });
    navigator.serviceWorker.register("/worker/sw.js", { scope: "/worker/" }).catch((err) => {
      console.warn("Saakshi: offline copy unavailable", err && err.message);
    });
  }
  S.offline = offline;
  renderNet();
}
