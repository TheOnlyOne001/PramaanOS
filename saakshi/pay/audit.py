"""Fairness audit across the line: nine checks over every payslip, PF deposits, pay gaps, overtime spread, fatigue."""
from __future__ import annotations

from typing import TypedDict

from .. import config, state
from .limits import fatigue
from .payslips import Payslip, check_passed, payslip
from .records import Worker, employer_of, pf_deposits, workers
from .rules import DEMO_PERIOD, round2
from .wages import pf_deducted

PAY_GAP_LIMIT = 0.05          # within-band gap in mean daily base pay that needs a written reason
OT_GINI_LIMIT = 0.4           # overtime concentration above this is reviewed
DEPOSIT_TOLERANCE_INR = 1     # rounding slack between PF deducted and PF deposited
GINI_DIGITS = 3

# (fairness check, the payslip check it summarises, detail when all pass, detail when some fail)
SLIP_CHECKS = (
    ("Ledger integrity", "Ledger integrity", "Every pay line traces to signed, unedited events",
     "Records edited after signing; pay held for these workers"),
    ("Minimum wage", "Minimum wage", "Everyone at or above the state minimum", "Below minimum; make-up pay added"),
    ("Overtime paid right", "Overtime consent", "All overtime at 2× with signed consent", "Overtime worked without signed consent"),
    ("Deduction cap", "Deduction cap", "Deductions within 50% of wages", "Deductions above 50%: pay run blocked"),
)


class FairnessCheck(TypedDict):
    """One line-wide fairness check and the workers it flags."""
    name: str
    ok: bool
    detail: str
    workers: list[str]


class FairnessReport(TypedDict):
    """Every fairness check for a period, plus the overtime Gini coefficient."""
    period: str
    checks: list[FairnessCheck]
    ot_gini: float


def _check(name: str, flagged: list[str], ok_detail: str, bad_detail: str) -> FairnessCheck:
    """A check that passes when it flags no worker."""
    return {"name": name, "ok": not flagged, "detail": bad_detail if flagged else ok_detail, "workers": flagged}


def gini(xs: list[float]) -> float:
    """Return the Gini coefficient of `xs` (0 = shared equally), rounded to 3 places; 0 for empty or all-zero input."""
    xs = sorted(xs)
    n, s = len(xs), sum(xs)
    if not n or not s:
        return 0.0
    return round(sum((2 * i - n + 1) * x for i, x in enumerate(xs)) / (n * s), GINI_DIGITS)


def _deposit_check(ws: dict[str, Worker], period: str) -> FairnessCheck:
    """Compare PF deducted (on wages up to each deposit's cut-off) with PF deposited, per employer."""
    deps = pf_deposits(period)
    deducted: dict[str, float] = {}
    for wid, w in ws.items():
        employer = employer_of(w)
        deducted[employer] = deducted.get(employer, 0) + pf_deducted(wid, period, deps.get(employer, {}).get("wages_upto"))
    short, detail = [], []
    for employer, ded in deducted.items():
        dep = deps.get(employer, {}).get("pf_deposited")
        if dep is not None and dep + DEPOSIT_TOLERANCE_INR < ded:
            short += [wid for wid, w in ws.items() if employer_of(w) == employer]
            detail.append(f"{employer}: PF deducted ₹{round2(ded):,.0f}, deposited ₹{dep:,.0f} (EPFO ECR)")
    return _check("Deposits match deductions", short, "PF deposited equals PF deducted", "; ".join(detail))


def pay_gaps(slips: dict[str, Payslip], ws: dict[str, Worker], attr: str) -> tuple[list[str], list[str]]:
    """Within each skill band, compare the mean daily base rate across groups of `attr`."""
    groups: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for wid, sl in slips.items():
        if sl["days_worked"]:
            daily = sl["lines"][0]["amount"] / sl["days_worked"]
            groups.setdefault(ws[wid]["skill_band"], {}).setdefault(ws[wid][attr] or "-", []).append((wid, daily))
    flagged: list[str] = []
    notes: list[str] = []
    for band, by in groups.items():
        if len(by) < 2:
            continue
        means = {g: sum(d for _, d in v) / len(v) for g, v in by.items()}
        hi, lo = max(means.values()), min(means.values())
        if hi and (hi - lo) / hi > PAY_GAP_LIMIT:
            flagged += [w for v in by.values() for w, _ in v]
            notes.append(f"{band}: " + ", ".join(f"{g} ₹{m:,.0f}/day" for g, m in means.items()))
    return flagged, notes


def fairness(period: str = DEMO_PERIOD) -> FairnessReport:
    """Memoised until the next database write: the console overview, the SDG scorecard and the
    fairness endpoint share one computation per state of the ledger."""
    return state.get().ledger.memo(("pay.fairness", period), lambda: _fairness(period))


def _fairness(period: str) -> FairnessReport:
    ws = workers()
    v = state.get().ledger.verify()  # once for every payslip below
    slips = {wid: payslip(wid, period, verification=v) for wid in ws}
    checks = [_check(name, [w for w, s in slips.items() if not check_passed(s, slip_check)], ok, bad)
              for name, slip_check, ok, bad in SLIP_CHECKS]
    checks.append(_deposit_check(ws, period))
    eq, eq_notes = pay_gaps(slips, ws, "gender")
    checks.append(_check("Equal pay", eq, "No within-band gender gap above 5% in daily base pay",
                         "; ".join(eq_notes) + " — review with written reasons"))
    cp, cp_notes = pay_gaps(slips, ws, "contract_type")
    checks.append(_check("Contract vs permanent", cp, "Same band, same daily base pay, whoever signs the contract", "; ".join(cp_notes)))
    g = gini([s["ot_hours"] for s in slips.values()])
    checks.append({"name": "Overtime spread", "ok": g <= OT_GINI_LIMIT,
                   "detail": f"Gini {g} across the line (review above {OT_GINI_LIMIT})", "workers": []})
    tired = [w for w in ws if fatigue(w, config.DEMO_DAY)]
    checks.append(_check("Fatigue", tired, "No overtime streaks past the limit", "Overtime streak past the limit; further overtime blocked"))
    return {"period": period, "checks": checks, "ot_gini": g}
