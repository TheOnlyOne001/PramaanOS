"""The monthly payslip (lines with formulas and evidence, five checks, explanations, status) and the pay run."""
from __future__ import annotations

from typing import Any, TypedDict

from fastapi import HTTPException

from .. import events, state
from ..ledger import Event, Problem, VerifyResult
from .breakdown import BASIC, ESI, OVERTIME, PF, explain_items
from .disputes import open_case_ids
from .explain import explanation
from .records import Worker, require_worker, workers
from .rules import DEMO_PERIOD, RULES, round2
from .wages import Attendance, Earnings, attendance, earnings

MIN_WAGE_TOLERANCE_INR = 0.01   # per-day rounding slack in the minimum-wage check
MAX_LINE_EVIDENCE = 40          # event seqs listed under the basic-pay line
BLOCKING_CHECKS = ("Ledger integrity", "Deduction cap")
"""A failed check of these holds the payslip; the others are flagged but pay still goes out."""

STATUS_LABELS = {
    "estimated": {"en": "Estimated", "ta": "மதிப்பீடு", "hi": "अनुमानित", "or": "ଆନୁମାନିକ"},
    "approved": {"en": "Approved", "ta": "அங்கீகரிக்கப்பட்டது", "hi": "स्वीकृत", "or": "ଅନୁମୋଦିତ"},
    "paid": {"en": "Paid", "ta": "செலுத்தப்பட்டது", "hi": "भुगतान हुआ", "or": "ପଇଠ ହୋଇଛି"},
    "under_review": {"en": "Under review", "ta": "பரிசீலனையில்", "hi": "समीक्षा में", "or": "ସମୀକ୍ଷାଧୀନ"},
}
"""Short words for each payslip status: estimated (no pay run), approved (pay run), paid, under_review (open dispute)."""


class Check(TypedDict):
    """One named payslip check and why it passed or failed."""
    name: str
    ok: bool
    detail: str


class Payslip(TypedDict):
    """A worker's pay for a period: lines with formulas and evidence, deductions, checks and explanations."""
    period: str
    worker: Worker
    days_worked: int
    ot_hours: float
    unconsented_ot_hours: float
    lines: list[dict[str, Any]]
    gross: float
    deductions: list[dict[str, Any]]
    total_deductions: float
    net: float
    checks: list[Check]
    blocked: bool
    integrity: dict[str, Any]
    explanation: dict[str, str]
    rules_version: str
    status: str
    status_label: dict[str, str]
    open_disputes: list[str]


def check_passed(slip: Payslip, name: str) -> bool:
    """Return whether the payslip check called `name` passed."""
    return next(c["ok"] for c in slip["checks"] if c["name"] == name)


def _integrity_problems(wid: str, verification: VerifyResult | None) -> list[Problem]:
    """Ledger problems that touch this worker's records (or the whole chain's roots)."""
    v = verification if verification is not None else state.get().ledger.verify()
    return [p for p in v["problems"] if p.get("worker_id") == wid or p["kind"] == "root_mismatch"]


def _consent_detail(att: Attendance) -> str:
    if att.beyond_grace_hours:
        return f"{att.beyond_grace_hours:g} h worked without signed consent (still paid at 2×)"
    grace = f"; {att.unconsented_ot_hours:g} h past approval within the grace, paid at 2×" if att.unconsented_ot_hours else ""
    return "Every overtime hour has signed consent" + grace


def _checks(band: str, att: Attendance, pay: Earnings, bad: list[Problem]) -> list[Check]:
    """The five payslip checks, in display order."""
    per_day_min = pay.monthly / RULES["days_payable"]
    return [
        {"name": "Ledger integrity", "ok": not bad,
         "detail": "; ".join(f"{p.get('type')} #{p.get('seq')}: {p['detail']}" for p in bad) if bad else
         "All hours trace to signed, unedited events"},
        {"name": "Minimum wage", "ok": att.days == 0 or pay.basic / max(att.days, 1) >= per_day_min - MIN_WAGE_TOLERANCE_INR,
         "detail": f"₹{round2(per_day_min)}/day minimum for {band}"},
        {"name": "Overtime paid at 2×", "ok": True, "detail": f"{att.ot_hours:g} h × ₹{round2(pay.rate)} × {RULES['ot_multiplier']}"},
        {"name": "Overtime consent", "ok": att.beyond_grace_hours == 0, "detail": _consent_detail(att)},
        {"name": "Deduction cap", "ok": pay.total_deductions <= RULES["deduction_cap"] * pay.gross,
         "detail": f"₹{pay.total_deductions} of ₹{pay.gross} (max {RULES['deduction_cap']:.0%})"},
    ]


def _lines(att: Attendance, pay: Earnings) -> list[dict[str, Any]]:
    """Earnings lines, each with its formula and the event seqs that prove it."""
    evidence = [seq for s in att.shifts for seq in s["evidence"]] + [e["seq"] for e in att.opening]
    return [{"label": BASIC, "amount": pay.basic, "formula": f"₹{pay.monthly} × {att.days}/{RULES['days_payable']} days",
             "evidence": evidence[:MAX_LINE_EVIDENCE]},
            {"label": OVERTIME, "amount": pay.ot_pay,
             "formula": f"{att.ot_hours:g} h × ₹{round2(pay.rate)} × {RULES['ot_multiplier']}",
             "evidence": [seq for s in att.shifts if s["ot_hours"] for seq in s["evidence"]]}]


def _deductions(pay: Earnings) -> list[dict[str, Any]]:
    """Statutory deduction lines with their formulas."""
    return [{"label": PF, "amount": pay.pf, "formula": f"12% × min(₹{pay.basic}, ₹15,000)"},
            {"label": ESI, "amount": pay.esi, "formula": "0.75% × gross (gross ≤ ₹21,000)"}]


def _period_events(wid: str, type_: str, period: str) -> list[Event]:
    """A worker's `type_` events whose payload names `period`."""
    return [e for e in state.get().ledger.events(worker_id=wid, type=type_) if e["payload"].get("period") == period]


def _adjustment_lines(adjustments: list[Event]) -> list[dict[str, Any]]:
    """Signed corrections (e.g. from a resolved dispute), each its own earnings line, paid in full."""
    return [{"label": e["payload"]["label"], "amount": round2(e["payload"]["amount"]),
             "formula": f"Settled on case {e['payload'].get('case_id', '')}; PF and ESI not recomputed", "evidence": [e["seq"]]}
            for e in adjustments]


def status_of(wid: str, period: str, open_disputes: list[str]) -> str:
    """Payslip status: under_review (open dispute) > paid (pay.paid) > approved (pay.run) > estimated."""
    if open_disputes:
        return "under_review"
    if _period_events(wid, events.PAY_PAID, period):
        return "paid"
    if _period_events(wid, events.PAY_RUN, period):
        return "approved"
    return "estimated"


def payslip(wid: str, period: str = DEMO_PERIOD, upto: str | None = None,
            verification: VerifyResult | None = None) -> Payslip:
    """Pay for `period` from signed events; `upto` limits it to wages earned up to that day.

    Signed `pay.adjustment` corrections for the period are added as their own lines, on top of the
    computed net. `verification`: a Ledger.verify() result to reuse (callers looping over workers verify once)."""
    w = require_worker(wid)
    att = attendance(wid, period, upto)
    pay = earnings(w["skill_band"], att)
    bad = _integrity_problems(wid, verification)
    checks = _checks(w["skill_band"], att, pay, bad)
    blocked = any(not c["ok"] for c in checks if c["name"] in BLOCKING_CHECKS)
    adjustments = _period_events(wid, events.PAY_ADJUSTMENT, period)
    adj_lines = _adjustment_lines(adjustments)
    lines = _lines(att, pay) + adj_lines
    deductions = _deductions(pay)
    explain = explain_items(wid, period, upto, att, pay, adjustments)
    for item in lines + deductions:
        item["explain"] = explain[item["label"]]
    adjusted = round2(sum(a["amount"] for a in adj_lines))
    gross, net = round2(pay.gross + adjusted), round2(pay.net + adjusted)
    disputes = open_case_ids(wid, period)
    status = status_of(wid, period, disputes)
    return {"period": period, "worker": w, "days_worked": att.days, "ot_hours": att.ot_hours,
            "unconsented_ot_hours": att.unconsented_ot_hours, "lines": lines, "gross": gross,
            "deductions": deductions, "total_deductions": pay.total_deductions, "net": net,
            "checks": checks, "blocked": blocked, "integrity": {"ok": not bad, "problems": bad},
            "explanation": explanation(att.days, att.ot_hours, round2(RULES["ot_multiplier"] * pay.rate), net, blocked),
            "rules_version": RULES["version"], "status": status, "status_label": dict(STATUS_LABELS[status]),
            "open_disputes": disputes}


def run(period: str) -> dict[str, Any]:
    """Run payroll for a period, ledgering pay for each unblocked worker and reporting failed checks."""
    st = state.get()
    results = []
    v = st.ledger.verify()  # once per run; pay.run events appended below are signed by this ledger
    for wid, w in workers().items():
        s = payslip(wid, period, verification=v)
        if not s["blocked"]:
            st.ledger.append("pay.run", {"period": period, "gross": s["gross"], "net": s["net"]}, worker_id=wid)
        results.append({"worker_id": wid, "name": w["name"], "gross": s["gross"], "net": s["net"], "blocked": s["blocked"],
                        "failed_checks": [c["name"] for c in s["checks"] if not c["ok"]]})
    return {"period": period, "blocked": any(r["blocked"] for r in results), "results": results}


def mark_paid(period: str) -> dict[str, Any]:
    """Record wages for a period as paid: one `pay.paid` event per worker whose pay run went through.

    Workers held at the run (no `pay.run`) or already paid are listed under `skipped`; 409 if the period was never run."""
    st = state.get()
    paid, skipped = [], []
    with st.lock:
        runs = {e["worker_id"]: e for e in st.ledger.events(type=events.PAY_RUN) if e["payload"].get("period") == period}
        if not runs:
            raise HTTPException(409, f"no pay run for {period}: run payroll first")
        done = {e["worker_id"] for e in st.ledger.events(type=events.PAY_PAID) if e["payload"].get("period") == period}
        for wid, w in workers().items():
            run_ev = runs.get(wid)
            if run_ev is None or wid in done:
                skipped.append({"worker_id": wid, "name": w["name"], "reason": "already paid" if wid in done else "held at the pay run"})
                continue
            ev = st.ledger.append(events.PAY_PAID, {"period": period, "net": run_ev["payload"]["net"], "run_seq": run_ev["seq"]},
                                  worker_id=wid)
            paid.append({"worker_id": wid, "name": w["name"], "net": run_ev["payload"]["net"], "seq": ev["seq"]})
    return {"period": period, "paid": paid, "skipped": skipped}
