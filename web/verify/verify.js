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

  // copy into this realm's Uint8Array (tweetnacl checks instanceof)
  function utf8(s) { return new Uint8Array(new TextEncoder().encode(s)); }

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
  var EVIDENCE_LADDER = ['None', 'Self-declared', 'Employer-attested', 'System-evidenced', 'Independently assessed'];
  var ILUO = ['I', 'L', 'U', 'O'];
  var LEVEL_PLAIN = {
    I: 'Is still learning this operation and needs close help.',
    L: 'Can do the work when a supervisor checks it.',
    U: 'Does the work to standard on their own, without supervision.',
    O: 'Does the work to standard and can teach it to others.'
  };
  var current = null; // {vc, res} of the last check, for copy-link

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

  function day(s) {
    if (!s) return '';
    var d = new Date(s);
    if (isNaN(d)) return esc(String(s).slice(0, 10));
    return esc(d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }));
  }

  function fact(label, value, hint) {
    return '<div class="fact"><dt>' + esc(label) + '</dt><dd>' + value + (hint ? '<small>' + esc(hint) + '</small>' : '') + '</dd></div>';
  }

  /* A ladder of steps with the achieved one filled and announced. */
  function ladder(steps, at, cls, label) {
    return '<ol class="ladder ' + cls + '" aria-label="' + esc(label) + '">' + steps.map(function (st, i) {
      var state = i === at ? 'here' : i < at ? 'below' : '';
      return '<li class="' + state + '"' + (i === at ? ' aria-current="step"' : '') + '><b>' + esc(st[0]) + '</b>' + esc(st[1]) + '</li>';
    }).join('') + '</ol>';
  }

  function announce(text) { var l = $('live'); l.textContent = ''; setTimeout(function () { l.textContent = text; }, 30); }

  function setVerdict(kind, title, detail, badges) {
    var v = $('verdict');
    v.className = 'card verdict ' + kind;
    v.hidden = false;
    $('verdict-icon').textContent = kind === 'ok' ? '✓' : kind === 'warn' ? '!' : '✕';
    $('verdict-title').textContent = title;
    $('verdict-detail').textContent = detail;
    $('verdict-badges').innerHTML = badges || '';
    $('copy-link').hidden = !current;
    void v.offsetWidth; // restart the reveal animation
    v.classList.add('reveal');
    announce(title + '. ' + detail);
  }

  function offlineBadge(res) {
    if (!res.signatureOk || !res.issuer) return '';
    var key = String(res.issuer.public_key_hex || '').slice(0, 16);
    return '<span class="badge ok"><span aria-hidden="true">⛨</span> Verified offline · issuer key <code>' + esc(key) + '…</code></span>';
  }

  function render(vc, res, regInfo) {
    var s = vc.credentialSubject || {};
    var ev = s.evidence || {};
    var html = '';
    var issName = (vc.issuer && vc.issuer.name) || (res.issuer && res.issuer.name) || '';
    html += fact('Worker', '<span class="lead">' + esc(s.name || '—') + '</span>', s.id ? 'Pseudonymous ID ' + s.id.split(':').pop() : '');
    if (s.level) {
      var lv = ILUO.indexOf(s.level);
      html += fact('Skill', '<span class="lead">' + esc(s.skillLabel || s.skill) + '</span> · level <span class="pill">' + esc(s.level) + '</span> ' +
        esc(LEVELS[s.level] || s.levelLabel || '') + '<span class="hint">' + esc(LEVEL_PLAIN[s.level] || '') + '</span>' +
        ladder(ILUO.map(function (k) { return [k, LEVELS[k]]; }), lv, 'cols-4', 'Skill level on the ILUO scale: ' + s.level + ' of I, L, U, O'));
    } else {
      html += fact('Credential', '<span class="lead">' + esc(s.skillLabel || s.skill) + '</span>');
    }
    if (s.evidenceLevel != null) {
      var e = EVIDENCE[s.evidenceLevel] || [s.evidenceLabel || '', ''];
      html += fact('Evidence', 'Level ' + esc(s.evidenceLevel) + ' of 4 · <b>' + esc(e[0]) + '</b><span class="hint">' + esc(e[1]) + '</span>' +
        ladder(EVIDENCE_LADDER.map(function (n, i) { return [String(i), n]; }), +s.evidenceLevel, 'cols-5', 'Evidence level ' + s.evidenceLevel + ' of 4'));
    }
    if (ev.days) {
      html += fact('Proof of work', esc(ev.days) + ' qualifying shift days · median efficiency ' +
        esc(Math.round(parseFloat(ev.medianEfficiency) * 100)) + '% · worst defect rate ' +
        esc((parseFloat(ev.maxDefectRate) * 100).toFixed(1)) + '%',
        (ev.criteria ? 'Rule: ' + ev.criteria + '. ' : '') + (ev.ledgerSeqs ? 'Backed by ' + ev.ledgerSeqs.length + ' signed ledger entries.' : ''));
    }
    if (s.nsqf) html += fact('Maps to', esc(s.nsqf));
    html += fact('Issued by', '<b>' + esc(issName) + '</b>', vc.issuer && vc.issuer.id);
    html += fact('Valid', 'From ' + day(vc.validFrom) + (vc.validUntil ? ' until ' + day(vc.validUntil) : ' · no expiry'),
      vc.validUntil ? '' : 'Skill credentials do not expire; the issuer can only revoke one for fraud.');
    html += '<div class="fact"><dt>Revocation</dt><dd id="revocation">Checking…</dd></div>';
    html += fact('Credential ID', '<code>' + esc(vc.id) + '</code>');
    $('details').innerHTML = html;
    $('details-card').hidden = false;

    $('checks').innerHTML = res.checks.map(function (c) {
      return '<li><span class="' + (c.ok ? 'ok' : 'bad') + '" aria-hidden="true">' + (c.ok ? '✓' : '✕') + '</span><span><span class="sr">' +
        (c.ok ? 'Passed: ' : 'Failed: ') + '</span>' + esc(c.detail) + '</span></li>';
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
        el.innerHTML = '<span class="bad-text">✕ Revoked by the issuer</span>';
        if (res.valid) setVerdict('bad', '✗ Revoked', 'The signature is genuine, but the issuer withdrew this credential (fraud found).', offlineBadge(res));
      } else if (r === false) {
        el.innerHTML = '<span class="ok-text">✓ Not revoked</span> <small>checked online just now</small>';
      } else el.textContent = 'Unknown';
    }).catch(function () { el.textContent = 'Unknown (offline) — signature check still holds'; });
  }

  function focusVerdict() { var h = $('verdict-title'); if (h) h.focus(); }

  function run(input) {
    var vc;
    current = null;
    $('details-card').hidden = true; $('how').hidden = true;
    try { vc = decodeVC(input); } catch (e) {
      setVerdict('bad', '✗ Could not read this credential', 'The link or text is damaged or incomplete. Ask for the QR code again.');
      focusVerdict();
      return Promise.resolve();
    }
    return getRegistry().then(function (regInfo) {
      if (!regInfo.registry) {
        setVerdict('warn', 'Cannot check yet', 'Open this page once while online so it can save the list of trusted issuers.');
        focusVerdict();
        return;
      }
      var res = verifyVC(vc, regInfo.registry, root.nacl);
      current = { vc: vc, res: res };
      if (res.valid) setVerdict('ok', '✓ Verified', 'Genuine and unchanged since ' + (res.issuer.name || 'the issuer') + ' signed it.', offlineBadge(res));
      else if (res.expired) setVerdict('warn', 'Expired', res.reason, offlineBadge(res));
      else setVerdict('bad', '✗ Not valid', res.reason, '<span class="badge crit"><span aria-hidden="true">✕</span> Do not rely on this credential</span>');
      render(vc, res, regInfo);
      checkRevocation(vc, res);
      $('input-title').textContent = 'Check another credential';
      $('empty-steps').hidden = true;
      $('paste-box').open = false;
      focusVerdict();
    });
  }

  function verifyLink(vc) { return location.origin + location.pathname + '#' + encodeVC(vc); }

  function copyLink() {
    if (!current) return;
    var link = verifyLink(current.vc);
    var done = function () { announce('Verify link copied'); $('copy-link').lastChild.textContent = ' Copied'; };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(link).then(done, function () { $('paste').value = link; });
    else { $('paste').value = link; $('paste-box').open = true; $('paste').select(); }
  }

  /* ---- QR scanning (scan.js); hidden unless BarcodeDetector and a camera exist ---- */
  var Scan = root.SaakshiScan;

  function onScanned(raw) {
    var code = Scan.extract(raw);
    closeScanner(false);
    if (location.hash.slice(1) !== code) history.replaceState(null, '', '#' + code);
    run(code);
  }

  function openScanner() {
    $('scanner').hidden = false;
    $('scan-btn').setAttribute('aria-expanded', 'true');
    $('scan-status').textContent = 'Starting camera…';
    Scan.start($('video'), onScanned).then(function () {
      $('scan-status').textContent = 'Point the camera at the QR code. Frames stay on this device.';
      $('scan-stop').focus();
    }).catch(function (e) {
      $('scan-status').textContent = e && e.name === 'NotAllowedError' ? 'Camera permission was refused. You can paste the link instead.' : 'Could not open a camera. You can paste the link instead.';
      $('scan-stop').focus();
    });
  }

  function closeScanner(refocus) {
    Scan.stop();
    $('video').srcObject = null;
    $('scanner').hidden = true;
    $('scan-btn').setAttribute('aria-expanded', 'false');
    if (refocus) $('scan-btn').focus();
  }

  function readFile(file) {
    if (!file) return;
    if (/^image\//.test(file.type) && Scan) {
      Scan.fromFile(file).then(function (raw) {
        if (raw) onScanned(raw);
        else { setVerdict('bad', '✗ No QR code found', 'That image has no readable QR code. Try a sharper photo, or paste the link.'); focusVerdict(); }
      }).catch(function () { setVerdict('bad', '✗ Could not read that image', 'Try another photo, or paste the link.'); focusVerdict(); });
      return;
    }
    file.text().then(function (t) { run(t); });
  }

  function wireScanner() {
    if (!Scan) return;
    Scan.support().then(function (can) {
      if (can.camera) { $('scan-btn').hidden = false; $('scan-btn').setAttribute('aria-controls', 'scanner'); $('scan-btn').setAttribute('aria-expanded', 'false'); }
      if (can.image) {
        $('file').setAttribute('accept', 'image/*,.json,.txt,application/json,text/plain');
        $('file-label').textContent = can.camera ? 'Choose a QR image' : 'Choose a QR image or file';
      }
      $('scan-note').hidden = !(can.camera || can.image);
    });
    $('scan-btn').addEventListener('click', openScanner);
    $('scan-stop').addEventListener('click', function () { closeScanner(true); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !$('scanner').hidden) closeScanner(true); });
    window.addEventListener('pagehide', function () { Scan.stop(); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    getRegistry(); // warm the cache for later offline use
    $('scan-note').hidden = true;
    wireScanner();
    $('paste-form').addEventListener('submit', function (e) {
      e.preventDefault();
      run($('paste').value);
    });
    $('file').addEventListener('change', function (e) { readFile(e.target.files && e.target.files[0]); e.target.value = ''; });
    $('copy-link').addEventListener('click', copyLink);
    $('print').addEventListener('click', function () { window.print(); });
    $('again').addEventListener('click', function () {
      history.replaceState(null, '', location.pathname);
      current = null;
      ['verdict', 'details-card', 'how'].forEach(function (id) { $(id).hidden = true; });
      $('input-title').textContent = 'Check a credential';
      $('empty-steps').hidden = false;
      $('paste').value = '';
      $('paste-box').open = true;
      $('copy-link').lastChild.textContent = ' Copy link';
      ($('scan-btn').hidden ? $('paste') : $('scan-btn')).focus();
    });
    var h = location.hash.replace(/^#/, '');
    if (h) run(h);
    else $('paste-box').open = true;
    window.addEventListener('hashchange', function () { var x = location.hash.slice(1); if (x) run(x); });
  });
})(typeof self !== 'undefined' ? self : this);
