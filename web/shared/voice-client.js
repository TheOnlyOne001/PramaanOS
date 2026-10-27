/* Saakshi Voice — browser client for anonymous, verifiable reports (blind RSA, RFC 9474 style).
 *
 *   await SaakshiVoice.getTokens("W001")         // once a month: blind one token per topic, issuer signs all
 *   SaakshiVoice.hasToken("water")               // unspent token for this month?
 *   await SaakshiVoice.report("water", "Drinking water runs out by 3 pm on our floor", "ta")
 *
 * The issuer sees the worker id and blinded numbers only; the relay sees a token and text but no worker id.
 * FDH must match saakshi/voice/blind.py byte for byte:
 *   FDH(m) = int(MGF1-SHA256("saakshi-voice|" + month + "|" + topic + "|" + m, len(n))) mod n
 * Unspent tokens are kept in localStorage per worker and month (falls back to memory).
 */
(function (root) {
  "use strict";
  const enc = new TextEncoder();
  const subtle = (root.crypto || globalThis.crypto).subtle;
  const rand = (n) => (root.crypto || globalThis.crypto).getRandomValues(new Uint8Array(n));

  // --- BigInt helpers ---------------------------------------------------------------------
  const hexToBig = (h) => BigInt("0x" + (h || "0"));
  const bigToHex = (x) => x.toString(16);
  const bytesToHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  const hexToBytes = (h) => {
    if (h.length % 2) h = "0" + h;
    const out = new Uint8Array(h.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
    return out;
  };
  const bytesToBig = (b) => (b.length ? hexToBig(bytesToHex(b)) : 0n);
  const mod = (a, n) => ((a % n) + n) % n;
  function modPow(base, exp, n) {
    let r = 1n, b = mod(base, n), e = exp;
    while (e > 0n) {
      if (e & 1n) r = (r * b) % n;
      b = (b * b) % n;
      e >>= 1n;
    }
    return r;
  }
  function egcd(a, b) {
    let [oldR, r] = [a, b], [oldS, s] = [1n, 0n];
    while (r !== 0n) {
      const q = oldR / r;
      [oldR, r] = [r, oldR - q * r];
      [oldS, s] = [s, oldS - q * s];
    }
    return [oldR, oldS];
  }
  function modInv(a, n) {
    const [g, x] = egcd(mod(a, n), n);
    if (g !== 1n) throw new Error("not invertible");
    return mod(x, n);
  }
  const byteLen = (n) => Math.ceil(n.toString(2).length / 8);
  const concat = (...parts) => {
    const out = new Uint8Array(parts.reduce((k, p) => k + p.length, 0));
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  };

  // --- protocol ---------------------------------------------------------------------------
  async function mgf1(seed, length) {
    const chunks = [];
    let have = 0;
    for (let c = 0; have < length; c++) {
      const ctr = new Uint8Array([(c >>> 24) & 255, (c >>> 16) & 255, (c >>> 8) & 255, c & 255]);
      const h = new Uint8Array(await subtle.digest("SHA-256", concat(seed, ctr)));
      chunks.push(h);
      have += h.length;
    }
    return concat(...chunks).slice(0, length);
  }

  async function fdh(month, topic, m, n) {
    const seed = concat(enc.encode("saakshi-voice|" + month + "|" + topic + "|"), m);
    return mod(bytesToBig(await mgf1(seed, byteLen(n))), n);
  }

  function randomUnit(n) {
    for (;;) {
      const r = mod(bytesToBig(rand(byteLen(n) + 8)), n);
      if (r > 1n && egcd(r, n)[0] === 1n) return r;
    }
  }

  async function blind(month, topic, m, n, e, r) {
    r = r || randomUnit(n);
    return { blinded: mod((await fdh(month, topic, m, n)) * modPow(r, e, n), n), r };
  }
  const unblind = (blindSig, r, n) => mod(blindSig * modInv(r, n), n);
  async function verify(month, topic, m, s, n, e) {
    return s > 0n && s < n && modPow(s, e, n) === (await fdh(month, topic, m, n));
  }

  // --- storage ----------------------------------------------------------------------------
  const mem = {};
  const storeKey = (wid, month) => "saakshi.voice.v1." + wid + "." + month;
  function load(wid, month) {
    const k = storeKey(wid, month);
    try {
      const raw = root.localStorage && root.localStorage.getItem(k);
      if (raw) return JSON.parse(raw);
    } catch (e) { /* private mode, blocked storage */ }
    return mem[k] || null;
  }
  function save(wid, month, data) {
    const k = storeKey(wid, month);
    mem[k] = data;
    try { if (root.localStorage) root.localStorage.setItem(k, JSON.stringify(data)); } catch (e) { /* memory only */ }
  }

  const state = { workerId: null, month: null, topics: null };
  try { state.workerId = root.localStorage && root.localStorage.getItem("saakshi.voice.v1.worker"); } catch (e) {}

  async function api(path, opts) {
    const headers = { "Content-Type": "application/json" };
    // Only the issuer learns who is asking (it must, to give one token per worker per month), so only
    // /api/voice/issue carries the worker's sign-in token. The relay call stays tokenless and anonymous.
    if (path === "/api/voice/issue" && root.SaakshiAuth) Object.assign(headers, await root.SaakshiAuth.header("worker"));
    const res = await fetch(path, Object.assign({}, opts || {}, { headers }));
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    if (!res.ok) {
      const err = new Error((body && body.detail) || ("HTTP " + res.status));
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  async function topics() {
    if (!state.topics) state.topics = await api("/api/voice/topics");
    state.month = state.topics.month;
    return state.topics;
  }

  async function getTokens(workerId) {
    workerId = workerId || state.workerId;
    if (!workerId) throw new Error("workerId needed");
    state.workerId = workerId;
    try { if (root.localStorage) root.localStorage.setItem("saakshi.voice.v1.worker", workerId); } catch (e) {}
    const info = await topics();
    const month = info.month;
    const have = load(workerId, month);
    if (have && have.issued) return { month, topics: Object.keys(have.tokens), alreadyIssued: true };

    const pending = {}, blinded = {};
    for (const t of info.topics) {
      if (!t.key) continue;
      const n = hexToBig(t.key.n_hex), e = BigInt(t.key.e);
      const m = rand(32);
      const b = await blind(month, t.id, m, n, e);
      pending[t.id] = { m, r: b.r, n, e };
      blinded[t.id] = bigToHex(b.blinded);
    }
    let res;
    try {
      res = await api("/api/voice/issue", { method: "POST", body: JSON.stringify({ worker_id: workerId, month, blinded }) });
    } catch (err) {
      if (err.status === 409) {  // already issued this month (tokens lost on this phone)
        save(workerId, month, { issued: true, tokens: (have && have.tokens) || {} });
        return { month, topics: Object.keys((have && have.tokens) || {}), alreadyIssued: true };
      }
      throw err;
    }
    const tokens = {};
    for (const [tid, sigHex] of Object.entries(res.signatures)) {
      const p = pending[tid];
      const s = unblind(hexToBig(sigHex), p.r, p.n);
      if (!(await verify(month, tid, p.m, s, p.n, p.e))) throw new Error("issuer returned a bad signature for " + tid);
      tokens[tid] = { m: bytesToHex(p.m), s: bigToHex(s) };
    }
    save(workerId, month, { issued: true, tokens });
    return { month, topics: Object.keys(tokens), alreadyIssued: false };
  }

  function hasToken(topic, workerId) {
    const wid = workerId || state.workerId;
    const month = state.month || (state.topics && state.topics.month);
    if (!wid || !month) return false;
    const d = load(wid, month);
    return !!(d && d.tokens && d.tokens[topic]);
  }

  async function report(topic, text, lang, workerId) {
    const wid = workerId || state.workerId;
    const month = (await topics()).month;
    const d = wid && load(wid, month);
    const tok = d && d.tokens && d.tokens[topic];
    if (!tok) {
      const err = new Error("no unspent token for " + topic + " this month");
      err.status = 400;
      throw err;
    }
    // No worker id in this request: the relay only sees a valid, unlinkable token.
    const body = { topic, month, token: tok.m, signature: tok.s, text, lang: lang || "en" };
    const spend = () => { delete d.tokens[topic]; save(wid, month, d); };
    try {
      const res = await api("/api/relay/voice/reports", { method: "POST", body: JSON.stringify(body) });
      spend();
      return res;
    } catch (err) {
      if (err.status === 409) spend();
      throw err;
    }
  }

  const scrub = (text) => api("/api/voice/scrub", { method: "POST", body: JSON.stringify({ text }) });
  const caseStatus = (caseKey) => api("/api/voice/cases/" + encodeURIComponent(caseKey));

  root.SaakshiVoice = {
    getTokens, report, hasToken, scrub, caseStatus, topics,
    // exposed for tests and the curious
    _crypto: { fdh, blind, unblind, verify, modPow, modInv, hexToBig, bigToHex, hexToBytes, bytesToHex },
  };
})(typeof window !== "undefined" ? window : globalThis);
