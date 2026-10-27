"""Wage arithmetic from signed hours: today's earnings, a period's attendance tally and its rupee amounts.

Money is computed only in this package, by plain arithmetic; an LLM never touches it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .. import config
from ..ledger import Event
from .records import opening_events, require_worker
from .rules import RULES, hourly_rate, ot_amount, period_last_day, round2
from .shifts import Shift, hours

TodayPay = TypedDict("TodayPay", {
    "day": str, "in": str | None, "out": str | None, "worked_hours": float, "ot_hours": float,
    "earned_today": float, "ot_earned": float, "hourly_rate": float, "currency": str,
})
"""One worker-day of earnings (functional form because "in" is a Python keyword)."""


@dataclass(frozen=True)
class Attendance:
    """What a period's signed hours add up to (complete shifts plus the imported opening balance)."""
    shifts: list[Shift]
    opening: list[Event]
    days: int
    ot_hours: float
    unconsented_ot_hours: float
    beyond_grace_hours: float


@dataclass(frozen=True)
class Earnings:
    """Rupee amounts for one period, each rounded to paise."""
    monthly: int
    rate: float
    basic: float
    ot_pay: float
    gross: float
    pf: float
    esi: float
    total_deductions: float
    net: float


def today(wid: str, day: str | None = None) -> TodayPay:
    """Return a worker's hours and INR earnings for one day (defaults to the demo day); 0 worked while still clocked in."""
    w = require_worker(wid)
    day = day or config.DEMO_DAY
    s = next(iter(hours(wid, day, day)), None)
    rate = hourly_rate(w["skill_band"])
    worked = s["worked_hours"] if s else 0.0   # an open shift (in, no out yet) has 0 worked hours
    ot = s["ot_hours"] if s else 0.0
    normal = min(worked, RULES["daily_hours"])
    return {"day": day, "in": s["in"] if s else None, "out": s["out"] if s else None, "worked_hours": worked, "ot_hours": ot,
            "earned_today": round2(normal * rate + ot_amount(ot, rate)),
            "ot_earned": round2(ot_amount(ot, rate)), "hourly_rate": round2(rate), "currency": "INR"}


def attendance(wid: str, period: str, upto: str | None = None) -> Attendance:
    """Tally a worker's complete shifts and opening balance for `period`, up to `upto` if given."""
    shifts = [s for s in hours(wid, f"{period}-01", period_last_day(period, upto)) if s["complete"]]
    opening = opening_events(wid, "attendance.opening_balance", "period", period)
    unconsented = [s["unconsented_ot_hours"] for s in shifts]
    return Attendance(
        shifts=shifts, opening=opening,
        days=len(shifts) + sum(e["payload"].get("days_worked", 0) for e in opening),
        ot_hours=round2(sum(s["ot_hours"] for s in shifts) + sum(e["payload"].get("ot_hours", 0) for e in opening)),
        unconsented_ot_hours=round2(sum(unconsented)),
        # Minutes past the approved overtime (gate queues, finishing a bundle) are paid at 2x and shown;
        # only a day beyond the grace counts as overtime without consent.
        beyond_grace_hours=round2(sum(h for h in unconsented if h > RULES["ot_grace_hours"])),
    )


def earnings(band: str, att: Attendance) -> Earnings:
    """Price an attendance tally: pro-rata basic, overtime at the multiple, PF and ESI."""
    monthly = RULES["min_wage_monthly"][band]
    rate = hourly_rate(band)
    basic = round2(min(monthly, monthly * att.days / RULES["days_payable"]))
    ot_pay = round2(ot_amount(att.ot_hours, rate))
    gross = round2(basic + ot_pay)
    pf = round2(RULES["pf_rate"] * min(basic, RULES["pf_wage_ceiling"]))
    esi = round2(RULES["esi_rate"] * gross) if gross <= RULES["esi_gross_ceiling"] else 0.0
    total = round2(pf + esi)
    return Earnings(monthly=monthly, rate=rate, basic=basic, ot_pay=ot_pay, gross=gross, pf=pf, esi=esi,
                    total_deductions=total, net=round2(gross - total))


def pf_deducted(wid: str, period: str, upto: str | None = None) -> float:
    """Return the PF deducted from a worker's wages for `period`, earned up to `upto` if given."""
    w = require_worker(wid)
    return earnings(w["skill_band"], attendance(wid, period, upto)).pf
