"""Wage and overtime rules, and the small pure helpers every pay calculation shares.

Rule values are illustrative Tamil Nadu figures; verify before real use.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict

from .. import config


class Rules(TypedDict):
    """The rule table served at /api/rules; every number in pay is derived from it."""
    state: str
    version: str
    note: str
    min_wage_monthly: dict[str, int]
    days_payable: int
    daily_hours: int
    break_hours: int
    ot_multiplier: int
    ot_cap_quarter: int
    near_cap_pct: float
    fatigue_week_ot: int
    fatigue_streak_days: int
    ot_grace_hours: float
    pf_rate: float
    pf_wage_ceiling: int
    esi_rate: float
    esi_gross_ceiling: int
    deduction_cap: float


RULES: Rules = {
    "state": "TN", "version": "TN-2026-10-illustrative", "note": "Illustrative values, verify before use",
    "min_wage_monthly": {"unskilled": 11800, "semi-skilled": 12400, "skilled": 13100, "highly-skilled": 13900},
    "days_payable": 26, "daily_hours": 8, "break_hours": 1, "ot_multiplier": 2, "ot_cap_quarter": 144,
    "near_cap_pct": 0.9, "fatigue_week_ot": 14, "fatigue_streak_days": 6, "ot_grace_hours": 0.75,
    "pf_rate": 0.12, "pf_wage_ceiling": 15000, "esi_rate": 0.0075, "esi_gross_ceiling": 21000, "deduction_cap": 0.5,
}

DEMO_PERIOD = config.DEMO_DAY[:7]       # the YYYY-MM period the demo runs in
DEMO_PERIOD_START = f"{DEMO_PERIOD}-01"
BREAK_AFTER_HOURS = 5           # a span longer than this includes the unpaid break
ROUNDING_EPSILON = 1e-9         # nudges x.xx5 float artefacts up before rounding to paise
MONTHS_PER_QUARTER = 3


def round2(x: float) -> float:
    """Round hours or rupees to 2 decimals, half-up despite binary float artefacts."""
    return round(x + ROUNDING_EPSILON, 2)


def hourly_rate(band: str) -> float:
    """Return the minimum-wage hourly rate in INR for a skill band (monthly wage / payable days / daily hours)."""
    return RULES["min_wage_monthly"][band] / RULES["days_payable"] / RULES["daily_hours"]


def ot_amount(hours: float, rate: float) -> float:
    """Return the unrounded overtime pay for `hours` at the overtime multiple of `rate`."""
    return hours * rate * RULES["ot_multiplier"]


def quarter_of(day: str) -> tuple[str, str]:
    """Return the quarter label ("2026-Q4") and its first day for an ISO date."""
    d = date.fromisoformat(day)
    q = (d.month - 1) // MONTHS_PER_QUARTER + 1
    return f"{d.year}-Q{q}", date(d.year, MONTHS_PER_QUARTER * q - 2, 1).isoformat()


def period_last_day(period: str, upto: str | None = None) -> str:
    """Return the last day of a YYYY-MM period as an ISO date, or `upto` if that is earlier."""
    y, m = map(int, period.split("-"))
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
    return min(last, upto) if upto else last
