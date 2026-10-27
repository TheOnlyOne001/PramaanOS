"""The monthly payslip (lines with formulas and evidence, five checks, explanations) and the pay run."""
from __future__ import annotations

from typing import Any, TypedDict

from .. import state
from ..ledger import Problem, VerifyResult
from .explain import explanation
from .records import Worker, require_worker, workers
from .rules import DEMO_PERIOD, RULES, round2
from .wages import Attendance, Earnings, attendance, earnings

MIN_WAGE_TOLERANCE_INR = 0.01   # per-day rounding slack in the minimum-wage check
MAX_LINE_EVIDENCE = 40          # event seqs listed under the basic-pay line
BLOCKING_CHECKS = ("Ledger integrity", "Deduction cap")
"""A failed check of these holds the payslip; the others are flagged but pay still goes out."""


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
    return [{"label": "Basic + DA", "amount": pay.basic, "formula": f"₹{pay.monthly} × {att.days}/{RULES['days_payable']} days",
             "evidence": evidence[:MAX_LINE_EVIDENCE]},
            {"label": "Overtime (2×)", "amount": pay.ot_pay,
             "formula": f"{att.ot_hours:g} h × ₹{round2(pay.rate)} × {RULES['ot_multiplier']}",
             "evidence": [seq for s in att.shifts if s["ot_hours"] for seq in s["evidence"]]}]


def _deductions(pay: Earnings) -> list[dict[str, Any]]:
    """Statutory deduction lines with their formulas."""
    return [{"label": "PF 12%", "amount": pay.pf, "formula": f"12% × min(₹{pay.basic}, ₹15,000)"},
            {"label": "ESI 0.75%", "amount": pay.esi, "formula": "0.75% × gross (gross ≤ ₹21,000)"}]


def payslip(wid: str, period: str = DEMO_PERIOD, upto: str | None = None,
            verification: VerifyResult | None = None) -> Payslip:
    """Pay for `period` from signed events; `upto` limits it to wages earned up to that day.

    `verification`: a Ledger.verify() result to reuse (callers looping over workers verify once)."""
    w = require_worker(wid)
    att = attendance(wid, period, upto)
    pay = earnings(w["skill_band"], att)
    bad = _integrity_problems(wid, verification)
    checks = _checks(w["skill_band"], att, pay, bad)
    blocked = any(not c["ok"] for c in checks if c["name"] in BLOCKING_CHECKS)
    return {"period": period, "worker": w, "days_worked": att.days, "ot_hours": att.ot_hours,
            "unconsented_ot_hours": att.unconsented_ot_hours, "lines": _lines(att, pay), "gross": pay.gross,
            "deductions": _deductions(pay), "total_deductions": pay.total_deductions, "net": pay.net,
            "checks": checks, "blocked": blocked, "integrity": {"ok": not bad, "problems": bad},
            "explanation": explanation(att.days, att.ot_hours, round2(RULES["ot_multiplier"] * pay.rate), pay.net, blocked),
            "rules_version": RULES["version"]}


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
