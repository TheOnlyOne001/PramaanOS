// Worker-held receipts: her own copy of every receipt the app has seen, kept on this phone.
// IndexedDB when available, localStorage otherwise, an in-memory map as the last resort.
// Every storage call is wrapped: a private window or a full disk must never break the app.
import { S } from "./state.js";
import { api } from "/shared/api.js";

const DB_NAME = "saakshi-wallet";
const STORE = "receipts";
const LS_PREFIX = "saakshi-receipts-";
const KEY_PREFIX = "saakshi-site-key-";  // site signing key the held copies were issued under
const FIELDS = ["seq", "ref", "hash", "ts", "type", "text", "text_en"];

let dbPromise = null;
const memory = new Map();

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      if (!("indexedDB" in window)) { resolve(null); return; }
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const os = req.result.createObjectStore(STORE, { keyPath: ["wid", "seq"] });
        os.createIndex("wid", "wid");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch { resolve(null); }
  });
  return dbPromise;
}

const pick = (r) => Object.fromEntries(FIELDS.map((k) => [k, r[k] ?? null]));

function lsRead(wid) {
  try { return JSON.parse(localStorage.getItem(LS_PREFIX + wid) || "[]"); } catch { return memory.get(wid) || []; }
}
function lsWrite(wid, list) {
  memory.set(wid, list);
  try { localStorage.setItem(LS_PREFIX + wid, JSON.stringify(list)); } catch { /* storage full or off: memory copy only */ }
}

function idbTx(db, mode, fn) {
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(STORE, mode);
      const out = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(out && "result" in out ? out.result : true);
      tx.onerror = tx.onabort = () => resolve(null);
    } catch { resolve(null); }
  });
}

/** All receipts held on this phone for worker `wid`, oldest first. */
export async function allReceipts(wid) {
  const db = await openDb();
  if (!db) return [...lsRead(wid)].sort((a, b) => a.seq - b.seq);
  const rows = await idbTx(db, "readonly", (os) => os.index("wid").getAll(wid));
  return (rows || lsRead(wid)).map(pick).sort((a, b) => a.seq - b.seq);
}

/** The site's public signing key (public endpoint), fetched once; null when offline. */
let siteKeyPromise = null;
function currentSiteKey() {
  if (!siteKeyPromise) {
    siteKeyPromise = api("/site").then((r) => (r.ok && r.data && r.data.public_keys ? r.data.public_keys.site : null))
      .catch(() => null);
  }
  return siteKeyPromise;
}
function heldKey(wid) {
  try { return localStorage.getItem(KEY_PREFIX + wid); } catch { return null; }
}
function rememberKey(wid, key) {
  if (!key) return;
  try { localStorage.setItem(KEY_PREFIX + wid, key); } catch { /* best effort */ }
}

/**
 * Keep every receipt she has been sent. A receipt already held is never overwritten: her copy is the proof,
 * and the integrity check compares it with the employer's ledger, so a rewritten server copy is caught.
 * Held copies are discarded only when the site's public signing key itself has changed (a new ledger with a
 * new identity, e.g. a demo reset). A different receipt under the same key never replaces hers.
 * Returns the number of receipts now held.
 */
export async function saveReceipts(wid, incoming) {
  const fresh = (incoming || []).filter((r) => r && Number.isInteger(r.seq) && r.hash).map(pick);
  const held = await allReceipts(wid);
  const siteKey = await currentSiteKey();
  const before = heldKey(wid);
  const rebuilt = Boolean(siteKey && before && siteKey !== before);
  rememberKey(wid, siteKey);
  const bySeq = new Map(rebuilt ? [] : held.map((r) => [r.seq, r]));
  const added = fresh.filter((r) => !bySeq.has(r.seq));
  if (!added.length && !rebuilt) return held.length;
  added.forEach((r) => bySeq.set(r.seq, r));
  const db = await openDb();
  if (!db) { lsWrite(wid, [...bySeq.values()]); return bySeq.size; }
  const ok = await idbTx(db, "readwrite", (os) => {
    if (rebuilt) held.forEach((r) => os.delete([wid, r.seq]));
    (rebuilt ? [...bySeq.values()] : added).forEach((r) => os.put({ ...r, wid }));
  });
  if (!ok) lsWrite(wid, [...bySeq.values()]);
  return bySeq.size;
}

/** Keep every receipt she is sent on this phone, then tell the screens how many she now holds. */
export async function keepReceipts(list) {
  const n = await saveReceipts(S.wid, list);
  if (n !== S.held) { S.held = n; document.dispatchEvent(new CustomEvent("saakshi:copy")); }
  return n;
}
