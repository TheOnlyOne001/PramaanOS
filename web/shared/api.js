// Tiny fetch helper shared by the worker app and the console.
// Never throws: returns {ok, status, data, error} so screens can degrade to "not available yet".
//
// Auth: every call carries `Authorization: Bearer <token>` (policy in saakshi/auth.py).
// Demo: tokens come from POST /api/auth/demo-login (works only with SAAKSHI_DEMO=1). In production the
// worker signs in with phone OTP / a PIN on a shared phone and staff via SSO; the header is the same.

// Page roles: /console/ and the live edge camera page (/camera/) act as the supervisor; the worker app and
// the worker's phone badge (/badge/?w=W001) act as the worker named by ?w=.
const PAGE = /^\/(console|camera)(\/|$)/.test(location.pathname) ? "console" : "worker";
const WID = (() => {
  try { return new URLSearchParams(location.search).get("w") || "W001"; } catch { return "W001"; }
})();
const SUBJECT = { worker: WID, supervisor: "S001", hr: "H001", auditor: "A001" };
const PUBLIC = /^\/(relay\/voice\/reports|demo\/|auth\/demo-login)/;
const _tokens = {};
const _pending = {};

function _store(role, tok) {
  _tokens[role] = tok;
  try { if (tok) sessionStorage.setItem(`saakshi.tok.${role}.${SUBJECT[role]}`, tok); else sessionStorage.removeItem(`saakshi.tok.${role}.${SUBJECT[role]}`); } catch { /* storage off */ }
}

function _cached(role) {
  if (_tokens[role]) return _tokens[role];
  try {
    const t = sessionStorage.getItem(`saakshi.tok.${role}.${SUBJECT[role]}`);
    if (t) {
      const exp = JSON.parse(atob(t.split(".")[0].replace(/-/g, "+").replace(/_/g, "/"))).exp;
      if (exp * 1000 > Date.now() + 60000) return (_tokens[role] = t);
    }
  } catch { /* ignore */ }
  return null;
}

async function _login(role) {
  if (!_pending[role]) {
    _pending[role] = (async () => {
      const body = role === "worker" ? { role, worker_id: WID } : { role };
      const res = await fetch("/api/auth/demo-login", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      });
      if (!res.ok) return null;
      const tok = (await res.json()).token || null;
      _store(role, tok);
      return tok;
    })().catch(() => null).finally(() => { delete _pending[role]; });
  }
  return _pending[role];
}

// Which role this page acts as for a call. The worker app is the worker; the console is a supervisor,
// switching to HR for payroll, fairness, root publishing and payslips.
function roleFor(path, method) {
  const p = path.split("?")[0];
  if (PAGE === "worker") {
    if (p === "/punch" && method === "POST") return "supervisor";  // demo kiosk: stands in for the gate device
    return "worker";
  }
  if (/^\/(pay\/run|pay\/fairness|ledger\/roots\/publish)$/.test(p) || /^\/pay\/[^/]+\/payslip$/.test(p)) return "hr";
  return "supervisor";
}

async function token(role) {
  role = role || (PAGE === "console" ? "supervisor" : "worker");
  return _cached(role) || (await _login(role));
}

async function header(role) {
  const t = await token(role);
  return t ? { Authorization: "Bearer " + t } : {};
}

if (typeof window !== "undefined") window.SaakshiAuth = { header, token };

export async function api(path, { method = "GET", body } = {}) {
  const role = PUBLIC.test(path) ? null : roleFor(path, method);
  const build = async () => {
    const opts = { method, headers: role ? await header(role) : {} };
    if (body !== undefined) {
      opts.headers["content-type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return opts;
  };
  try {
    let res = await fetch("/api" + path, await build());
    if (res.status === 401 && role) {  // expired, or keys rotated by a demo reset: sign in again once
      _store(role, null);
      res = await fetch("/api" + path, await build());
    }
    if (path.startsWith("/demo/reset") && res.ok) Object.keys(SUBJECT).forEach((r) => _store(r, null));
    const ct = res.headers.get("content-type") || "";
    let data = null;
    if (ct.includes("json")) data = await res.json().catch(() => null);
    else data = await res.text().catch(() => "");
    if (!res.ok) {
      let error = `HTTP ${res.status}`;
      if (data && data.detail) error = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      return { ok: false, status: res.status, data, error };
    }
    return { ok: true, status: res.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: null, error: String((e && e.message) || e) };
  }
}

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const hm = (ts) => (ts && ts.length >= 16 ? ts.slice(11, 16) : "—");

export function fmtDay(day, locale = "en-IN", opts = { day: "numeric", month: "short" }) {
  if (!day) return "—";
  try { return new Intl.DateTimeFormat(locale, opts).format(new Date(day.slice(0, 10) + "T12:00:00")); }
  catch { return day; }
}

export function rupees(n, dp = 0) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return "₹" + Number(n).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: 2 });
}

export const num = (n, dp = 1) => (n === null || n === undefined || isNaN(n) ? "—" :
  Number(n).toLocaleString("en-IN", { maximumFractionDigits: dp }));

export function toast(msg, ms = 3200) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast"; el.className = "toast"; el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), ms);
}
