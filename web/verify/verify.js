/* Saakshi credential verifier.
 *
 * Verifies an Ed25519-signed, W3C-VC-shaped skill credential entirely in the
 * browser, against an issuer registry fetched once and cached. The core
 * functions are DOM-free and also run under Node (used by the Python tests):
 *   const V = require('./verify.js'); V.verifyVC(vc, registry, nacl)
 *
 * Canonical JSON = recursive key sort + JSON.stringify, which matches Python's
 * json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False) byte for
 * byte as long as there are no floats (Saakshi VCs use ints and strings only).
 */
(function (root) {
  'use strict';

  var LEVELS = { I: 'In training', L: 'Works with supervision', U: 'Works independently', O: 'Can train others' };
  var EVIDENCE = {
    1: ['Self-declared', 'The worker said so; nobody has checked.'],
    2: ['Employer-attested', 'The employer’s record says so (a supervisor vouched for it).'],
    3: ['System-evidenced', 'Computed from signed, tamper-evident production records on the shop floor — not from anyone’s opinion.'],
    4: ['Independently assessed', 'Tested by an outside assessor.']
  };

  function hasFloat(v) {
    if (typeof v === 'number') return !Number.isInteger(v);
    if (Array.isArray(v)) return v.some(hasFloat);
    if (v && typeof v === 'object') return Object.keys(v).some(function (k) { return hasFloat(v[k]); });
    return false;
  }

  function canonicalize(v) {
    if (v === null || typeof v !== 'object') return JSON.stringify(v);
    if (Array.isArray(v)) return '[' + v.map(canonicalize).join(',') + ']';
    return '{' + Object.keys(v).filter(function (k) { return v[k] !== undefined; }).sort().map(function (k) {
      return JSON.stringify(k) + ':' + canonicalize(v[k]);
    }).join(',') + '}';
  }

  function utf8(s) { return new TextEncoder().encode(s); }

  function b64urlToBytes(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/').replace(/\s+/g, '');
    while (s.length % 4) s += '=';
    var bin = atob(s), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64url(b) {
    var s = '';
    for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function hexToBytes(h) {
    if (typeof h !== 'string' || h.length % 2 || /[^0-9a-f]/i.test(h)) throw new Error('not hex');
    var out = new Uint8Array(h.length / 2);
    for (var i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
    return out;
  }

  /* Accepts raw JSON, base64url(JSON), or a full verify URL with #<base64url>. */
  function decodeVC(input) {
    var s = String(input || '').trim();
    if (!s) throw new Error('Nothing to verify');
    if (s.charAt(0) === '{') return JSON.parse(s);
    var hash = s.indexOf('#');
    if (hash >= 0) s = s.slice(hash + 1);
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(b64urlToBytes(s)));
  }

  function encodeVC(vc) { return bytesToB64url(utf8(canonicalize(vc))); }

  function signingString(vc) {
    var copy = {};
    Object.keys(vc).forEach(function (k) { if (k !== 'proof') copy[k] = vc[k]; });
    return canonicalize(copy);
  }

  function findIssuer(registry, id) {
    var list = (registry && registry.issuers) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  /* Returns {valid, signatureOk, expired, notYetValid, reason, issuer, checks:[{name, ok, detail}]} */
  function verifyVC(vc, registry, nacl, now) {
    nacl = nacl || root.nacl;
    now = now ? new Date(now) : new Date();
    var checks = [], res = { valid: false, signatureOk: false, expired: false, notYetValid: false, reason: '', issuer: null, checks: checks };
    function fail(name, detail) { checks.push({ name: name, ok: false, detail: detail }); res.reason = detail; return res; }
    function pass(name, detail) { checks.push({ name: name, ok: true, detail: detail }); }

    if (!vc || typeof vc !== 'object') return fail('format', 'Not a credential');
    var proof = vc.proof;
    if (!proof || proof.type !== 'Ed25519Signature2020' || typeof proof.proofValue !== 'string')
      return fail('format', 'No Ed25519 proof attached');
    if (hasFloat(vc)) return fail('format', 'Contains decimal numbers, so it cannot be checked byte-for-byte');
    pass('format', 'W3C-style credential with an Ed25519 proof');

    var issuerId = vc.issuer && (typeof vc.issuer === 'string' ? vc.issuer : vc.issuer.id);
    var iss = findIssuer(registry, issuerId);
    if (!iss) return fail('issuer', 'Issuer ' + (issuerId || '?') + ' is not in the trusted issuer list');
    res.issuer = iss;
    var tail = String(issuerId).split(':').pop();
    if (iss.public_key_hex.slice(0, tail.length) !== tail) return fail('issuer', 'Issuer ID does not match its key');
    if (proof.verificationMethod && proof.verificationMethod.indexOf(issuerId) !== 0)
      return fail('issuer', 'Signed with a key that does not belong to the issuer');
    pass('issuer', 'Issued by ' + iss.name);

    var ok = false;
    try {
      ok = nacl.sign.detached.verify(utf8(signingString(vc)), hexToBytes(proof.proofValue), hexToBytes(iss.public_key_hex));
    } catch (e) { ok = false; }
    if (!ok) return fail('signature', 'Signature does not match: the credential was changed after it was signed, or forged');
    res.signatureOk = true;
    pass('signature', 'Signature verified offline with the issuer’s public key');

    if (vc.validFrom && new Date(vc.validFrom) > now) {
      res.notYetValid = true;
      return fail('dates', 'Not valid until ' + vc.validFrom);
    }
    if (vc.validUntil && new Date(vc.validUntil) < now) {
      res.expired = true;
      return fail('dates', 'Expired on ' + vc.validUntil.slice(0, 10));
    }
    pass('dates', vc.validUntil ? 'Valid until ' + vc.validUntil.slice(0, 10) : 'Skill credentials do not expire');
    res.valid = true;
    res.reason = 'Genuine and unchanged';
    return res;
  }

  /* status = {bitmap:[0|1]} from /api/passport/status. Returns true/false/null (unknown). */
  function isRevoked(vc, status) {
    var cs = vc && vc.credentialStatus;
    if (!cs || !status || !status.bitmap) return null;
    var i = parseInt(cs.statusListIndex, 10);
    if (isNaN(i) || i >= status.bitmap.length) return null;
    return status.bitmap[i] === 1;
  }

  var api = {
    canonicalize: canonicalize, signingString: signingString, decodeVC: decodeVC, encodeVC: encodeVC,
    verifyVC: verifyVC, isRevoked: isRevoked, b64urlToBytes: b64urlToBytes, bytesToB64url: bytesToB64url,
    hexToBytes: hexToBytes, LEVELS: LEVELS, EVIDENCE: EVIDENCE
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SaakshiVerify = api;

  /* ---------------------------------------------------------------- UI --- */
  if (typeof document === 'undefined') return;

  var REG_KEY = 'saakshi.issuers.v1';
  var $ = function (id) { return document.getElementById(id); };

  function store(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }
  function load(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { return null; } }

  function fetchJSON(url, ms) {
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctl) ctl.abort(); }, ms || 4000);
    return fetch(url, { cache: 'no-store', signal: ctl && ctl.signal }).then(function (r) {
      clearTimeout(t);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function apiURL(path) {
    return location.protocol.indexOf('http') === 0 ? new URL(path, location.origin).toString() : null;
  }

  function getRegistry() {
    var url = apiURL('/api/passport/issuers');
    var cached = load(REG_KEY);
    if (!url) return Promise.resolve({ registry: cached, source: cached ? 'cached' : 'none' });
    return fetchJSON(url).then(function (reg) {
      reg.cached_at = new Date().toISOString();
      store(REG_KEY, reg);
      return { registry: reg, source: 'online' };
    }).catch(function () {
      return { registry: cached, source: cached ? 'cached' : 'none' };
    });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function row(label, value, hint) {
    return '<div class="row"><dt>' + esc(label) + '</dt><dd>' + value + (hint ? '<small>' + esc(hint) + '</small>' : '') + '</dd></div>';
  }

  function setVerdict(kind, title, detail) {
    var v = $('verdict');
    v.className = 'verdict ' + kind;
    v.hidden = false;
    $('verdict-icon').textContent = kind === 'ok' ? '✓' : kind === 'warn' ? '!' : '✕';
    $('verdict-title').textContent = title;
    $('verdict-detail').textContent = detail;
  }

  function render(vc, res, regInfo) {
    var s = vc.credentialSubject || {};
    var ev = s.evidence || {};
    var html = '';
    html += row('Worker', esc(s.name || '—'), s.id ? 'Pseudonymous ID ' + s.id.split(':').pop() : '');
    if (s.level) {
      html += row('Skill', '<b>' + esc(s.skillLabel || s.skill) + '</b> · level <span class="pill">' + esc(s.level) + '</span> ' + esc(LEVELS[s.level] || s.levelLabel || ''),
        'ILUO scale: I in training → L with supervision → U independent → O can train others');
    } else {
      html += row('Credential', '<b>' + esc(s.skillLabel || s.skill) + '</b>');
    }
    if (s.evidenceLevel) {
      var e = EVIDENCE[s.evidenceLevel] || [s.evidenceLabel || '', ''];
      html += row('Evidence', 'Level ' + esc(s.evidenceLevel) + ' of 4 · <b>' + esc(e[0]) + '</b>', e[1]);
    }
    if (ev.days) {
      html += row('Proof of work', esc(ev.days) + ' qualifying shift days · median efficiency ' +
        esc(Math.round(parseFloat(ev.medianEfficiency) * 100)) + '% · worst defect rate ' +
        esc((parseFloat(ev.maxDefectRate) * 100).toFixed(1)) + '%',
        (ev.criteria ? 'Rule: ' + ev.criteria + '. ' : '') + (ev.ledgerSeqs ? 'Backed by ' + ev.ledgerSeqs.length + ' signed ledger entries.' : ''));
    }
    if (s.nsqf) html += row('Maps to', esc(s.nsqf));
    var issName = (vc.issuer && vc.issuer.name) || (res.issuer && res.issuer.name) || '';
    html += row('Issued by', esc(issName), vc.issuer && vc.issuer.id);
    html += row('Valid', esc((vc.validFrom || '').slice(0, 10)) + (vc.validUntil ? ' → ' + esc(vc.validUntil.slice(0, 10)) : ' → no expiry'));
    html += '<div class="row"><dt>Revocation</dt><dd id="revocation">Checking…</dd></div>';
    html += row('Credential ID', '<code>' + esc(vc.id) + '</code>');
    $('details').innerHTML = html;
    $('details').hidden = false;

    $('checks').innerHTML = res.checks.map(function (c) {
      return '<li class="' + (c.ok ? 'ok' : 'bad') + '">' + (c.ok ? '✓ ' : '✕ ') + esc(c.detail) + '</li>';
    }).join('') + '<li class="muted">Issuer list: ' + esc(regInfo.source === 'online' ? 'fetched just now' :
      regInfo.source === 'cached' ? 'cached copy from ' + ((regInfo.registry && regInfo.registry.cached_at) || '').slice(0, 16).replace('T', ' ') + ' (offline)' : 'not available') + '</li>';
    $('how').hidden = false;
  }

  function checkRevocation(vc, res) {
    var el = $('revocation');
    var cs = vc.credentialStatus;
    if (!cs) { el.textContent = 'No status list'; return; }
    var url = apiURL(cs.statusListCredential || '/api/passport/status');
    if (!url) { el.textContent = 'Unknown (offline) — signature check still holds'; return; }
    fetchJSON(url).then(function (status) {
      var r = isRevoked(vc, status);
      if (r === true) {
        el.innerHTML = '<b class="bad">Revoked by the issuer</b>';
        if (res.valid) setVerdict('bad', 'Revoked', 'The signature is genuine, but the issuer withdrew this credential (fraud found).');
      } else if (r === false) {
        el.innerHTML = '<span class="ok">Not revoked</span> <small>checked online just now</small>';
      } else el.textContent = 'Unknown';
    }).catch(function () { el.textContent = 'Unknown (offline) — signature check still holds'; });
  }

  function run(input) {
    var vc;
    $('details').hidden = true; $('how').hidden = true;
    try { vc = decodeVC(input); } catch (e) {
      setVerdict('bad', 'Could not read this credential', 'The link or text is damaged or incomplete.');
      return;
    }
    getRegistry().then(function (regInfo) {
      if (!regInfo.registry) {
        setVerdict('warn', 'Cannot check yet', 'Open this page once while online so it can save the list of trusted issuers.');
        return;
      }
      var res = verifyVC(vc, regInfo.registry, root.nacl);
      if (res.valid) setVerdict('ok', 'Genuine credential', 'Signed by ' + res.issuer.name + ' and unchanged since.');
      else if (res.expired) setVerdict('warn', 'Expired', res.reason);
      else setVerdict('bad', 'Not valid', res.reason);
      render(vc, res, regInfo);
      checkRevocation(vc, res);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    getRegistry(); // warm the cache for later offline use
    $('paste-form').addEventListener('submit', function (e) {
      e.preventDefault();
      run($('paste').value);
    });
    var h = location.hash.replace(/^#/, '');
    if (h) { $('paste-box').open = false; run(h); }
    else { $('paste-box').open = true; }
    window.addEventListener('hashchange', function () { var x = location.hash.slice(1); if (x) run(x); });
  });
})(typeof self !== 'undefined' ? self : this);
