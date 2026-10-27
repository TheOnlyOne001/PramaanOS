// Saakshi worker app service worker (scope /worker/).
// App shell: cache-first, so the app opens with no network. Her record (GET /api/... she reads):
// network-first, falling back to the last copy saved here. POSTs and sign-in are never cached.
// Runs as a classic worker script; uses only self, caches and fetch (all browser globals).

const VERSION = "saakshi-worker-v3";
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

const SHELL = [
  "/worker/", "/worker/index.html", "/worker/style.css", "/worker/manifest.webmanifest",
  "/worker/app.js", "/worker/state.js", "/worker/ui.js", "/worker/shell.js", "/worker/speech.js",
  "/worker/icons.js", "/worker/store.js", "/worker/net.js",
  "/worker/screens/today.js", "/worker/screens/pay.js", "/worker/screens/hours.js",
  "/worker/screens/skills.js", "/worker/screens/voice.js", "/worker/screens/rights.js",
  "/worker/icons/icon.svg", "/worker/icons/icon-192.png", "/worker/icons/icon-512.png", "/worker/icons/apple-touch-icon.png",
  "/shared/api.js", "/shared/i18n.js", "/shared/tokens.css", "/shared/voice-client.js",
];

// GET endpoints the worker screens need to render offline.
const DATA = [
  /^\/api\/workers(\/[^/]+)?$/, /^\/api\/workers\/[^/]+\/(receipts|access-log)$/,
  /^\/api\/pay\/[^/]+\/(today|payslip)$/, /^\/api\/hours\/[^/]+$/, /^\/api\/ot\/(cap|requests)$/,
  /^\/api\/passport\//, /^\/api\/rules$/, /^\/api\/voice\/(topics|board)$/,
];
const NEVER = /^\/api\/(auth|demo)\//;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL_CACHE)
    .then((c) => Promise.all(SHELL.map((u) => c.add(new Request(u, { cache: "reload" })).catch(() => null))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("saakshi-worker-") && !k.startsWith(VERSION)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function cacheFirst(req) {
  const hit = await caches.match(req, { ignoreSearch: req.mode === "navigate" });
  if (hit) {
    fetch(req).then((res) => res.ok && caches.open(SHELL_CACHE).then((c) => c.put(req, res))).catch(() => null);
    return hit;
  }
  const res = await fetch(req);
  if (res.ok) { const copy = res.clone(); caches.open(SHELL_CACHE).then((c) => c.put(req, copy)); }
  return res;
}

/** Tell the page whether its last read came from the network or from the copy saved on this phone. */
async function notify(clientId, offline) {
  const c = clientId && (await self.clients.get(clientId));
  if (c) c.postMessage({ type: "saakshi-net", offline });
}

async function networkFirst(req, clientId) {
  try {
    const res = await fetch(req);
    if (res.ok) { const copy = res.clone(); caches.open(DATA_CACHE).then((c) => c.put(req, copy)); }
    notify(clientId, false);
    return res;
  } catch (err) {
    notify(clientId, true);
    const hit = await caches.match(req, { ignoreVary: true, cacheName: DATA_CACHE });
    if (!hit) throw err;
    const headers = new Headers(hit.headers);
    headers.set("X-Saakshi-Offline", "1");
    return new Response(await hit.blob(), { status: hit.status, statusText: hit.statusText, headers });
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;  // consent, punches, reports, checks: always live, never replayed
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) {
    if (NEVER.test(url.pathname) || !DATA.some((re) => re.test(url.pathname))) return;
    e.respondWith(networkFirst(req, e.clientId));
    return;
  }
  if (url.pathname.startsWith("/worker/") || url.pathname.startsWith("/shared/")) e.respondWith(cacheFirst(req));
});
