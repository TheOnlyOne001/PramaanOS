// Tiny fetch helper shared by the worker app and the console.
// Never throws: returns {ok, status, data, error} so screens can degrade to "not available yet".

export async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch("/api" + path, opts);
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
