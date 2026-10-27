"""Fair Pay and overtime: deterministic pay from signed hours, consent-based overtime, fairness checks.

Rule values are illustrative Tamil Nadu figures; verify before real use.
Money is computed only here, by plain arithmetic; an LLM never touches it.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import config, i18n, state
from .crypto import canonical
from .db import register_schema

router = APIRouter(prefix="/api")

RULES = {
    "state": "TN", "version": "TN-2026-10-illustrative", "note": "Illustrative values, verify before use",
    "min_wage_monthly": {"unskilled": 11800, "semi-skilled": 12400, "skilled": 13100, "highly-skilled": 13900},
    "days_payable": 26, "daily_hours": 8, "break_hours": 1, "ot_multiplier": 2, "ot_cap_quarter": 144,
    "near_cap_pct": 0.9, "fatigue_week_ot": 14, "fatigue_streak_days": 6, "ot_grace_hours": 0.75,
    "pf_rate": 0.12, "pf_wage_ceiling": 15000, "esi_rate": 0.0075, "esi_gross_ceiling": 21000, "deduction_cap": 0.5,
}

register_schema("""
CREATE TABLE IF NOT EXISTS ot_requests(
  request_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, date TEXT NOT NULL, hours REAL NOT NULL,
  status TEXT NOT NULL, requested_by TEXT, reason TEXT, request_seq INTEGER, consent_seq INTEGER);
""")

i18n.register("ot.request", {
    "en": lambda c: f"Overtime request: {c['hours']:g} h on {c['date']}. Reply YES or NO. Saying no costs you nothing · ref {c['ref']}",
    "ta": lambda c: f"கூடுதல் நேர கோரிக்கை: {c['date']} அன்று {c['hours']:g} மணி. ஆம் / இல்லை. மறுத்தால் பாதிப்பு இல்லை · குறிப்பு {c['ref']}",
    "hi": lambda c: f"ओवरटाइम अनुरोध: {c['date']} को {c['hours']:g} घंटे। हाँ या ना। मना करने पर कोई नुकसान नहीं · संदर्भ {c['ref']}",
    "or": lambda c: f"ଅତିରିକ୍ତ ସମୟ ଅନୁରୋଧ: {c['date']} ରେ {c['hours']:g} ଘଣ୍ଟା। ହଁ କିମ୍ବା ନା · ସନ୍ଦର୍ଭ {c['ref']}",
})
i18n.register("ot.consent", {
    "en": lambda c: f"You {'accepted' if c['decision'] == 'accept' else 'declined'} {c['hours']:g} h overtime at double pay · ref {c['ref']}",
    "ta": lambda c: f"{c['hours']:g} மணி கூடுதல் நேரத்தை (இரட்டை ஊதியம்) {'ஏற்றீர்கள்' if c['decision'] == 'accept' else 'மறுத்தீர்கள்'} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आपने {c['hours']:g} घंटे ओवरटाइम (दोगुना वेतन) {'स्वीकार' if c['decision'] == 'accept' else 'अस्वीकार'} किया · संदर्भ {c['ref']}",
    "or": lambda c: f"ଆପଣ {c['hours']:g} ଘଣ୍ଟା ଅତିରିକ୍ତ ସମୟ {'ଗ୍ରହଣ' if c['decision'] == 'accept' else 'ମନା'} କଲେ · ସନ୍ଦର୍ଭ {c['ref']}",
})
i18n.register("pay.run", {
    "en": lambda c: f"Payslip {c['period']}: net ₹{c['net']:,.2f} · ref {c['ref']}",
    "ta": lambda c: f"{c['period']} ஊதியச் சீட்டு: நிகர ₹{c['net']:,.2f} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"{c['period']} वेतन पर्ची: शुद्ध ₹{c['net']:,.2f} · संदर्भ {c['ref']}",
    "or": lambda c: f"{c['period']} ଦରମା ପତ୍ର: ନିଟ୍ ₹{c['net']:,.2f} · ସନ୍ଦର୍ଭ {c['ref']}",
})


def _r(x: float) -> float:
    return round(x + 1e-9, 2)


def _workers() -> dict:
    return {r["id"]: dict(r) for r in state.get().conn.execute("SELECT * FROM workers WHERE is_supervisor=0")}


def _worker(wid: str) -> dict:
    w = _workers().get(wid)
    if not w:
        raise HTTPException(404, f"unknown worker {wid}")
    return w


def hourly_rate(band: str) -> float:
    """Return the minimum-wage hourly rate in INR for a skill band (monthly wage / payable days / daily hours)."""
    return RULES["min_wage_monthly"][band] / RULES["days_payable"] / RULES["daily_hours"]


def _quarter(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day)
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}", date(d.year, 3 * q - 2, 1).isoformat()


def _accepted_by_date(wid: str) -> dict:
    out: dict[str, float] = {}
    for r in state.get().conn.execute("SELECT date, hours FROM ot_requests WHERE worker_id=? AND status='accepted'", (wid,)):
        out[r["date"]] = out.get(r["date"], 0) + r["hours"]
    return out


# --- Proof of Hours ------------------------------------------------------------

def hours(wid: str, day_from: str = "2026-10-01", day_to: str = config.DEMO_DAY) -> list[dict]:
    """Shifts built from signed punches, with corrections applied as new events.

    Memoised until the next database write (any table, any connection), so the many hours() calls
    behind one console/fairness request read the punches once."""
    L = state.get().ledger
    return L.memo(("pay.hours", wid, day_from, day_to), lambda: _hours(L, wid, day_from, day_to))


def _hours(L, wid: str, day_from: str, day_to: str) -> list[dict]:
    evs = L.events(worker_id=wid, type_prefix="punch.", day_from=day_from, day_to=day_to)
    times = {e["seq"]: e["ts"] for e in evs if e["type"] in ("punch.in", "punch.out")}
    corrected = set()
    for e in evs:
        if e["type"] == "punch.correction" and e["payload"].get("corrects_seq") in times:
            times[e["payload"]["corrects_seq"]] = e["payload"]["new_ts"]
            corrected.add(e["payload"]["corrects_seq"])
    days: dict[str, dict] = {}
    for e in evs:
        if e["type"] not in ("punch.in", "punch.out"):
            continue
        d = days.setdefault(e["day"], {"day": e["day"], "in": None, "out": None, "evidence": [], "corrected": False})
        d["evidence"].append(e["seq"])
        d["corrected"] |= e["seq"] in corrected
        key = "in" if e["type"] == "punch.in" else "out"
        if (key == "in" and d["in"] is None) or key == "out":
            d[key] = times[e["seq"]]
    accepted = _accepted_by_date(wid)
    out = []
    for d in sorted(days.values(), key=lambda x: x["day"]):
        worked = ot = 0.0
        if d["in"] and d["out"]:
            span = (datetime.fromisoformat(d["out"]) - datetime.fromisoformat(d["in"])).total_seconds() / 3600
            worked = max(0.0, span - (RULES["break_hours"] if span > 5 else 0))
            ot = max(0.0, worked - RULES["daily_hours"])
        cons = min(ot, accepted.get(d["day"], 0.0))
        out.append({**d, "worked_hours": _r(worked), "ot_hours": _r(ot), "consented_ot_hours": _r(cons),
                    "unconsented_ot_hours": _r(ot - cons), "complete": bool(d["in"] and d["out"])})
    return out


def _opening(wid: str, type_: str, key: str, value: str) -> list[dict]:
    return [e for e in state.get().ledger.events(worker_id=wid, type=type_) if e["payload"].get(key) == value]


def quarter_used(wid: str, day: str) -> float:
    """Return overtime hours a worker has used in the quarter up to `day`, incl. opening balance and accepted requests."""
    q, start = _quarter(day)
    used = sum(e["payload"]["hours"] for e in _opening(wid, "ot.opening_balance", "quarter", q))
    shifts = hours(wid, start, day)
    used += sum(s["ot_hours"] for s in shifts)
    done = {s["day"] for s in shifts if s["complete"]}
    used += sum(h for d, h in _accepted_by_date(wid).items() if d >= start and d not in done)
    return _r(used)


def cap_status(date_: str | None = None) -> list[dict]:
    """Return each worker's quarterly overtime usage vs. cap with an ok/near/over status (defaults to the demo day)."""
    day = date_ or config.DEMO_DAY
    cap = RULES["ot_cap_quarter"]
    out = []
    for wid, w in _workers().items():
        used = quarter_used(wid, day)
        status = "over" if used > cap else "near" if used >= RULES["near_cap_pct"] * cap else "ok"
        out.append({"worker_id": wid, "name": w["name"], "used": used, "cap": cap, "remaining": _r(max(0, cap - used)),
                    "pct": _r(100 * used / cap), "status": status})
    return out


def _fatigue(wid: str, day: str) -> str | None:
    d = date.fromisoformat(day)
    shifts = {s["day"]: s for s in hours(wid, (d - timedelta(days=7)).isoformat(), day)}
    week = sum(s["ot_hours"] for s in shifts.values())
    if week > RULES["fatigue_week_ot"]:
        return f"{week:g} h overtime in the last 7 days (limit {RULES['fatigue_week_ot']})"
    streak = 0
    for i in range(1, 8):
        s = shifts.get((d - timedelta(days=i)).isoformat())
        if not s or s["ot_hours"] <= 0:
            break
        streak += 1
    if streak >= RULES["fatigue_streak_days"]:
        return f"overtime on {streak} days in a row"
    return None


# --- Overtime requests and consent ----------------------------------------------

class OTRequest(BaseModel):
    """Request body for asking one or more workers to do overtime (0–4 h) on a date."""
    worker_ids: list[str] = Field(min_length=1, max_length=200)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hours: float = Field(gt=0, le=4)
    requested_by: str = Field(max_length=40)
    reason: str = Field(default="", max_length=200)
    ts: str | None = None


def create_requests(body: OTRequest) -> dict:
    """Create and ledger an OT request per worker, blocking any that breach the quarterly cap or fatigue limits."""
    st = state.get()
    ws = _workers()
    cap = RULES["ot_cap_quarter"]
    results = []
    for wid in body.worker_ids:
        if wid not in ws:
            raise HTTPException(404, f"unknown worker {wid}")
        used = quarter_used(wid, body.date)
        after = _r(used + body.hours)
        warnings, blocked = [], False
        if after > cap:
            blocked = True
            warnings.append(f"Would breach the {cap} h quarterly cap ({after:g} h)")
        elif after >= RULES["near_cap_pct"] * cap:
            warnings.append(f"Near the quarterly cap: {_r(cap - after):g} h left after this")
        fat = _fatigue(wid, body.date)
        if fat:
            blocked = True
            warnings.append(f"Fatigue limit: {fat}")
        rid = "OT-" + uuid.uuid4().hex[:8].upper()
        ev1 = st.ledger.append("ot.request", {"request_id": rid, "date": body.date, "hours": body.hours,
                                              "requested_by": body.requested_by, "reason": body.reason},
                               worker_id=wid, ts=body.ts, receipt=not blocked)
        ev2 = st.ledger.append("ot.cap_check", {"request_id": rid, "used": used, "after": after, "cap": cap,
                                                "ok": not blocked, "warnings": warnings},
                               worker_id=wid, ts=body.ts, receipt=False)
        status = "blocked" if blocked else "pending"
        st.conn.execute("INSERT INTO ot_requests VALUES (?,?,?,?,?,?,?,?,NULL)",
                        (rid, wid, body.date, body.hours, status, body.requested_by, body.reason, ev1["seq"]))
        results.append({"request_id": rid, "worker_id": wid, "name": ws[wid]["name"], "date": body.date,
                        "hours": body.hours, "status": status,
                        "cap": {"used": used, "cap": cap, "remaining": _r(max(0, cap - used)), "after": after},
                        "warnings": warnings, "events": [ev1["seq"], ev2["seq"]]})
    return {"requests": results}


def list_requests(worker_id: str | None = None, status: str | None = None) -> list[dict]:
    """Return OT requests with worker names, newest first, optionally filtered by worker and status."""
    q, args = "SELECT r.*, w.name FROM ot_requests r JOIN workers w ON w.id=r.worker_id WHERE 1=1", []
    if worker_id:
        q += " AND r.worker_id=?"
        args.append(worker_id)
    if status:
        q += " AND r.status=?"
        args.append(status)
    return [dict(r) for r in state.get().conn.execute(q + " ORDER BY r.request_seq DESC", args)]


class Consent(BaseModel):
    """Request body for a worker accepting or declining an OT request via voice, tap or WhatsApp."""
    decision: str = Field(pattern="^(accept|decline)$")
    channel: str = Field(default="tap", pattern="^(voice|tap|whatsapp)$")
    transcript: str | None = Field(default=None, max_length=200)
    ts: str | None = None


def consent(request_id: str, body: Consent) -> dict:
    """Record a worker-signed accept/decline on a pending OT request; 404 if unknown, 409 if not pending."""
    st = state.get()
    r = st.conn.execute("SELECT * FROM ot_requests WHERE request_id=?", (request_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such request")
    if r["status"] != "pending":
        raise HTTPException(409, f"request is {r['status']}")
    msg = canonical({"request_id": request_id, "decision": body.decision, "worker_id": r["worker_id"]})
    worker_sig = st.keys.sign(f"worker:{r['worker_id']}", msg)
    ev = st.ledger.append("ot.consent", {"request_id": request_id, "decision": body.decision, "hours": r["hours"],
                                         "channel": body.channel, "transcript": body.transcript,
                                         "worker_sig": worker_sig}, worker_id=r["worker_id"], ts=body.ts)
    status = "accepted" if body.decision == "accept" else "declined"
    st.conn.execute("UPDATE ot_requests SET status=?, consent_seq=? WHERE request_id=?", (status, ev["seq"], request_id))
    req = {**dict(r), "status": status, "consent_seq": ev["seq"]}
    return {"request": req, "event": ev, "receipt": ev["receipt"]}


# --- Pay ----------------------------------------------------------------------------

def today(wid: str, day: str | None = None) -> dict:
    """Return a worker's hours and INR earnings for one day (defaults to the demo day); 0 worked while still clocked in."""
    w = _worker(wid)
    day = day or config.DEMO_DAY
    s = next((x for x in hours(wid, day, day)), None)
    rate = hourly_rate(w["skill_band"])
    worked = 0.0 if s and not s["complete"] and s["in"] else s["worked_hours"] if s else 0.0
    ot = s["ot_hours"] if s else 0.0
    normal = min(worked, RULES["daily_hours"])
    return {"day": day, "in": s and s["in"], "out": s and s["out"], "worked_hours": worked, "ot_hours": ot,
            "earned_today": _r(normal * rate + ot * rate * RULES["ot_multiplier"]),
            "ot_earned": _r(ot * rate * RULES["ot_multiplier"]), "hourly_rate": _r(rate), "currency": "INR"}


def _deposits(period: str) -> dict:
    return {e["payload"].get("contractor") or "direct": e["payload"]
            for e in state.get().ledger.events(type="pf.deposit") if e["payload"].get("period") == period}


def payslip(wid: str, period: str = config.DEMO_DAY[:7], upto: str | None = None,
            verification: dict | None = None) -> dict:
    """Pay for `period` from signed events; `upto` limits it to wages earned up to that day.

    `verification`: a Ledger.verify() result to reuse (callers looping over workers verify once)."""
    st = state.get()
    w = _worker(wid)
    band = w["skill_band"]
    monthly = RULES["min_wage_monthly"][band]
    rate = hourly_rate(band)
    y, m = map(int, period.split("-"))
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
    if upto:
        last = min(last, upto)
    shifts = [s for s in hours(wid, f"{period}-01", last) if s["complete"]]
    opening = _opening(wid, "attendance.opening_balance", "period", period)
    open_days = sum(e["payload"].get("days_worked", 0) for e in opening)
    open_ot = sum(e["payload"].get("ot_hours", 0) for e in opening)
    days = len(shifts) + open_days
    ot_h = _r(sum(s["ot_hours"] for s in shifts) + open_ot)
    uncons = _r(sum(s["unconsented_ot_hours"] for s in shifts))
    # Minutes past the approved overtime (gate queues, finishing a bundle) are paid at 2x and shown;
    # only a day beyond the grace counts as overtime without consent.
    beyond = _r(sum(s["unconsented_ot_hours"] for s in shifts if s["unconsented_ot_hours"] > RULES["ot_grace_hours"]))
    basic = _r(min(monthly, monthly * days / RULES["days_payable"]))
    ot_pay = _r(ot_h * rate * RULES["ot_multiplier"])
    gross = _r(basic + ot_pay)
    pf = _r(RULES["pf_rate"] * min(basic, RULES["pf_wage_ceiling"]))
    esi = _r(RULES["esi_rate"] * gross) if gross <= RULES["esi_gross_ceiling"] else 0.0
    total_ded = _r(pf + esi)
    evidence = [seq for s in shifts for seq in s["evidence"]] + [e["seq"] for e in opening]
    v = verification if verification is not None else st.ledger.verify()
    bad = [p for p in v["problems"] if p.get("worker_id") == wid or p["kind"] == "root_mismatch"]
    checks = [
        {"name": "Ledger integrity", "ok": not bad,
         "detail": "All hours trace to signed, unedited events" if not bad else
         "; ".join(f"{p.get('type')} #{p.get('seq')}: {p['detail']}" for p in bad)},
        {"name": "Minimum wage", "ok": days == 0 or basic / max(days, 1) >= monthly / RULES["days_payable"] - 0.01,
         "detail": f"₹{_r(monthly / RULES['days_payable'])}/day minimum for {band}"},
        {"name": "Overtime paid at 2×", "ok": True, "detail": f"{ot_h:g} h × ₹{_r(rate)} × 2"},
        {"name": "Overtime consent", "ok": beyond == 0,
         "detail": ("Every overtime hour has signed consent" + (f"; {uncons:g} h past approval within the grace, paid at 2×" if uncons else ""))
         if beyond == 0 else f"{beyond:g} h worked without signed consent (still paid at 2×)"},
        {"name": "Deduction cap", "ok": total_ded <= RULES["deduction_cap"] * gross, "detail": f"₹{total_ded} of ₹{gross} (max 50%)"},
    ]
    blocked = not checks[0]["ok"] or not checks[4]["ok"]
    net = _r(gross - total_ded)
    expl = {
        "en": f"You worked {days} days and {ot_h:g} overtime hours. Overtime is paid at double rate: ₹{_r(2 * rate)} an hour. "
              f"After PF and ESI, you get ₹{net:,.2f}.",
        "ta": f"நீங்கள் {days} நாட்கள் மற்றும் {ot_h:g} கூடுதல் மணி நேரம் வேலை செய்தீர்கள். கூடுதல் நேரத்திற்கு இரட்டை ஊதியம்: "
              f"மணிக்கு ₹{_r(2 * rate)}. PF, ESI பிடித்தம் போக, உங்களுக்கு ₹{net:,.2f}.",
        "hi": f"आपने {days} दिन और {ot_h:g} घंटे ओवरटाइम काम किया। ओवरटाइम दोगुनी दर पर: ₹{_r(2 * rate)} प्रति घंटा। "
              f"PF और ESI के बाद आपको ₹{net:,.2f} मिलेंगे।",
        "or": f"ଆପଣ {days} ଦିନ ଏବଂ {ot_h:g} ଘଣ୍ଟା ଅତିରିକ୍ତ କାମ କଲେ। ଅତିରିକ୍ତ ସମୟ ଦୁଇଗୁଣ ହାରରେ: ଘଣ୍ଟା ପିଛା ₹{_r(2 * rate)}। "
              f"PF ଓ ESI ପରେ ଆପଣ ₹{net:,.2f} ପାଇବେ।",
    }
    if blocked:
        for k in expl:
            expl[k] = {"en": "Your payslip is on hold: a record of your hours was changed after it was signed. "
                             "Your receipts prove what really happened.",
                       "ta": "உங்கள் ஊதியச் சீட்டு நிறுத்தப்பட்டுள்ளது: கையொப்பமிட்ட பின் உங்கள் நேரப் பதிவு மாற்றப்பட்டது. "
                             "உங்கள் ரசீதுகள் உண்மையை நிரூபிக்கும்.",
                       "hi": "आपकी वेतन पर्ची रोकी गई है: हस्ताक्षर के बाद आपके घंटों का रिकॉर्ड बदला गया। आपकी रसीदें सच साबित करती हैं।",
                       "or": "ଆପଣଙ୍କ ଦରମା ପତ୍ର ରୋକାଯାଇଛି: ସ୍ୱାକ୍ଷର ପରେ ଆପଣଙ୍କ ସମୟ ରେକର୍ଡ ବଦଳାଯାଇଛି।"}[k]
    return {"period": period, "worker": w, "days_worked": days, "ot_hours": ot_h, "unconsented_ot_hours": uncons,
            "lines": [{"label": "Basic + DA", "amount": basic, "formula": f"₹{monthly} × {days}/{RULES['days_payable']} days",
                       "evidence": evidence[:40]},
                      {"label": "Overtime (2×)", "amount": ot_pay, "formula": f"{ot_h:g} h × ₹{_r(rate)} × 2",
                       "evidence": [s for x in shifts if x["ot_hours"] for s in x["evidence"]]}],
            "gross": gross,
            "deductions": [{"label": "PF 12%", "amount": pf, "formula": f"12% × min(₹{basic}, ₹15,000)"},
                           {"label": "ESI 0.75%", "amount": esi, "formula": "0.75% × gross (gross ≤ ₹21,000)"}],
            "total_deductions": total_ded, "net": net, "checks": checks, "blocked": blocked,
            "integrity": {"ok": not bad, "problems": bad}, "explanation": expl, "rules_version": RULES["version"]}


def _gini(xs: list[float]) -> float:
    xs = sorted(xs)
    n, s = len(xs), sum(xs)
    if not n or not s:
        return 0.0
    return round(sum((2 * i - n + 1) * x for i, x in enumerate(xs)) / (n * s), 3)


def fairness(period: str = config.DEMO_DAY[:7]) -> dict:
    """Memoised until the next database write: the console overview, the SDG scorecard and the
    fairness endpoint share one computation per state of the ledger."""
    L = state.get().ledger
    return L.memo(("pay.fairness", period), lambda: _fairness(period))


def _fairness(period: str) -> dict:
    ws = _workers()
    v = state.get().ledger.verify()  # once for every payslip below
    slips = {wid: payslip(wid, period, verification=v) for wid in ws}
    deps = _deposits(period)
    checks = []

    def add(name, bad, ok_detail, bad_detail):
        checks.append({"name": name, "ok": not bad, "detail": ok_detail if not bad else bad_detail, "workers": bad})

    add("Ledger integrity", [w for w, s in slips.items() if not s["integrity"]["ok"]],
        "Every pay line traces to signed, unedited events", "Records edited after signing; pay held for these workers")
    add("Minimum wage", [w for w, s in slips.items() if not s["checks"][1]["ok"]], "Everyone at or above the state minimum",
        "Below minimum; make-up pay added")
    add("Overtime paid right", [w for w, s in slips.items() if not s["checks"][3]["ok"]],
        "All overtime at 2× with signed consent", "Overtime worked without signed consent")
    add("Deduction cap", [w for w, s in slips.items() if not s["checks"][4]["ok"]], "Deductions within 50% of wages",
        "Deductions above 50%: pay run blocked")
    short = []
    by_con: dict[str, float] = {}
    for wid, s in slips.items():
        c = ws[wid]["contractor"] or "direct"
        upto = deps.get(c, {}).get("wages_upto")
        pf_upto = (payslip(wid, period, upto=upto, verification=v)["deductions"][0]["amount"] if upto
                   else s["deductions"][0]["amount"])
        by_con[c] = by_con.get(c, 0) + pf_upto
    detail = []
    for c, ded in by_con.items():
        dep = deps.get(c, {}).get("pf_deposited")
        if dep is not None and dep + 1 < ded:
            short += [w for w in ws if (ws[w]["contractor"] or "direct") == c]
            detail.append(f"{c}: PF deducted ₹{_r(ded):,.0f}, deposited ₹{dep:,.0f} (EPFO ECR)")
    add("Deposits match deductions", short, "PF deposited equals PF deducted", "; ".join(detail))
    def gaps(attr: str) -> tuple[list[str], list[str]]:
        """Within each skill band, compare the mean daily base rate across groups of `attr`."""
        groups: dict[str, dict[str, list[tuple[str, float]]]] = {}
        for wid, sl in slips.items():
            if sl["days_worked"]:
                daily = sl["lines"][0]["amount"] / sl["days_worked"]
                groups.setdefault(ws[wid]["skill_band"], {}).setdefault(ws[wid][attr] or "-", []).append((wid, daily))
        flagged, notes = [], []
        for band, by in groups.items():
            if len(by) < 2:
                continue
            means = {g: sum(d for _, d in v) / len(v) for g, v in by.items()}
            hi, lo = max(means.values()), min(means.values())
            if hi and (hi - lo) / hi > 0.05:
                flagged += [w for v in by.values() for w, _ in v]
                notes.append(f"{band}: " + ", ".join(f"{g} ₹{m:,.0f}/day" for g, m in means.items()))
        return flagged, notes

    eq, eq_notes = gaps("gender")
    add("Equal pay", eq, "No within-band gender gap above 5% in daily base pay", "; ".join(eq_notes) + " — review with written reasons")
    cp, cp_notes = gaps("contract_type")
    add("Contract vs permanent", cp, "Same band, same daily base pay, whoever signs the contract", "; ".join(cp_notes))
    ots = [s["ot_hours"] for s in slips.values()]
    g = _gini(ots)
    checks.append({"name": "Overtime spread", "ok": g <= 0.4, "detail": f"Gini {g} across the line (review above 0.4)", "workers": []})
    tired = [w for w in ws if _fatigue(w, config.DEMO_DAY)]
    add("Fatigue", tired, "No overtime streaks past the limit", "Overtime streak past the limit; further overtime blocked")
    return {"period": period, "checks": checks, "ot_gini": g}


def run(period: str) -> dict:
    """Run payroll for a period, ledgering pay for each unblocked worker and reporting failed checks."""
    st = state.get()
    results = []
    v = st.ledger.verify()  # once per run; pay.run events appended below are signed by this ledger
    for wid, w in _workers().items():
        s = payslip(wid, period, verification=v)
        failed = [c["name"] for c in s["checks"] if not c["ok"]]
        if not s["blocked"]:
            st.ledger.append("pay.run", {"period": period, "gross": s["gross"], "net": s["net"]}, worker_id=wid)
        results.append({"worker_id": wid, "name": w["name"], "gross": s["gross"], "net": s["net"], "blocked": s["blocked"],
                        "failed_checks": failed})
    return {"period": period, "blocked": any(r["blocked"] for r in results), "results": results}


# --- HTTP ------------------------------------------------------------------------------

@router.get("/rules")
def get_rules():
    """Return the wage and overtime rules in force."""
    return RULES


@router.get("/hours/{wid}")
def get_hours(wid: str, day_from: str = "2026-10-01", day_to: str = config.DEMO_DAY):
    """Return a worker's daily shifts between two ISO dates (inclusive); 404 if the worker is unknown."""
    _worker(wid)
    return hours(wid, day_from, day_to)


@router.get("/ot/cap")
def get_cap(date: str | None = None):
    """Return every worker's quarterly overtime cap status as of a date."""
    return cap_status(date)


@router.post("/ot/requests")
def post_requests(body: OTRequest):
    """Create overtime requests for the given workers."""
    return create_requests(body)


@router.get("/ot/requests")
def get_requests(worker_id: str | None = None, status: str | None = None):
    """List overtime requests, optionally filtered by worker and status."""
    return list_requests(worker_id, status)


@router.post("/ot/requests/{request_id}/consent")
def post_consent(request_id: str, body: Consent):
    """Record a worker's accept/decline on an overtime request."""
    return consent(request_id, body)


@router.get("/pay/fairness")
def get_fairness(period: str = config.DEMO_DAY[:7]):
    """Return the pay fairness report for a YYYY-MM period."""
    return fairness(period)


@router.post("/pay/run")
def post_run(period: str = config.DEMO_DAY[:7]):
    """Run payroll for a YYYY-MM period."""
    return run(period)


@router.get("/pay/{wid}/today")
def get_today(wid: str, day: str | None = None):
    """Return a worker's hours and earnings for one day."""
    return today(wid, day)


@router.get("/pay/{wid}/payslip")
def get_payslip(wid: str, period: str = config.DEMO_DAY[:7]):
    """Return a worker's payslip for a YYYY-MM period."""
    return payslip(wid, period)


# --- Demo history ----------------------------------------------------------------------

OPENING = {"W001": 70, "W002": 128, "W003": 133, "W004": 40, "W005": 20, "W006": 100, "W007": 30, "W008": 60}
WEEK_OT = {"W001": {"2026-10-21": 2, "2026-10-23": 2}, "W002": {"2026-10-20": 2, "2026-10-22": 2, "2026-10-24": 2, "2026-10-26": 2},
           "W003": {"2026-10-21": 2, "2026-10-23": 2, "2026-10-26": 2}, "W006": {"2026-10-22": 2}}
PAST = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]


def seed_demo(st) -> None:
    """Seed the ledger with demo opening balances and recent overtime history for every worker."""
    L = st.ledger
    ws = _workers()
    for wid in ws:
        t0 = "2026-10-19T07:30:00+05:30"
        src = "Muster register 1–17 Oct, imported at install"
        L.append("attendance.opening_balance", {"period": "2026-10", "days_worked": 14, "ot_hours": OPENING[wid], "source": src},
                 worker_id=wid, ts=t0, receipt=False)
        L.append("ot.opening_balance", {"quarter": "2026-Q4", "hours": OPENING[wid], "source": src},
                 worker_id=wid, ts=t0, receipt=False)
    for day in PAST:
        for i, wid in enumerate(ws):
            ot = WEEK_OT.get(wid, {}).get(day, 0)
            if ot:
                body = OTRequest(worker_ids=[wid], date=day, hours=ot, requested_by="S001", reason="Shipment", ts=f"{day}T16:30:00+05:30")
                rid = create_requests(body)["requests"][0]["request_id"]
                consent(rid, Consent(decision="accept", channel="whatsapp", ts=f"{day}T16:40:00+05:30"))
            L.append("punch.in", {"device": "bio-gate-1"}, worker_id=wid, ts=f"{day}T07:{55 + i % 5:02d}:00+05:30", receipt=wid == "W001")
            # 9 h span (8 h work + 1 h break) plus the approved overtime, to the minute.
            L.append("punch.out", {"device": "bio-gate-1"}, worker_id=wid, ts=f"{day}T{16 + ot:02d}:{55 + i % 5:02d}:00+05:30",
                     receipt=wid == "W001")
    for i, wid in enumerate(ws):
        if wid != "W001":
            L.append("punch.in", {"device": "bio-gate-1"}, worker_id=wid, ts=f"2026-10-27T07:{58 + i % 2:02d}:00+05:30", receipt=False)
    # PF deposits per employer for October: the agency deposited only ~70% of what it deducted.
    pf = {"direct": 0.0, "Sri Balaji Manpower": 0.0}
    for wid, w in ws.items():
        pf[w["contractor"] or "direct"] += payslip(wid, "2026-10", upto="2026-10-26")["deductions"][0]["amount"]
    for c, amt in pf.items():
        dep = amt if c == "direct" else round(amt * 0.7, 2)
        L.append("pf.deposit", {"contractor": None if c == "direct" else c, "period": "2026-10", "pf_deposited": dep,
                                "wages_upto": "2026-10-26", "source": "EPFO ECR"}, ts="2026-10-26T18:00:00+05:30")
