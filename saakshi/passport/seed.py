"""Demo seed: a week of production records and safety inductions that set up the scripted demo."""
from __future__ import annotations

from datetime import date, timedelta

from .. import config, events
from ..state import State
from .credentials import check_and_issue, issue_safety
from .rules import MACHINE_GUARDING, SAFETY_CREDENTIALS

SEED_DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]
SHIFT_MINUTES = 420

DayPlan = tuple[float, float] | None
"""(efficiency, defect_rate) for one seed day; None = absent."""

# Q = qualifies (eff >= .70 and defects <= 2.5%).
_SEED_PLAN: dict[str, tuple[str, list[DayPlan]]] = {
    # Meena: 4 qualifying days (20, 21, 23, 24). One more good shift today issues her credential live.
    "W001": ("overlock", [(0.66, 0.020), (0.74, 0.018), (0.78, 0.015), (0.72, 0.031), (0.81, 0.012),
                          (0.79, 0.016), (0.68, 0.019)]),
    # Lakshmi: 6 qualifying days -> credential issued during seed.
    "W002": ("overlock", [(0.84, 0.010), (0.86, 0.012), (0.82, 0.009), (0.88, 0.011), (0.85, 0.014),
                          (0.83, 0.010), (0.87, 0.008)]),
    # Anjali: 2 qualifying days.
    "W006": ("overlock", [(0.58, 0.030), (0.62, 0.028), (0.71, 0.022), (0.64, 0.027), (0.69, 0.024),
                          (0.73, 0.021), (0.66, 0.026)]),
    # Sabita: 3 qualifying days on flatlock.
    "W003": ("flatlock", [(0.72, 0.020), (0.68, 0.018), (0.75, 0.019), None, (0.66, 0.022), (0.74, 0.017),
                          (0.69, 0.020)]),
    # Fatima: lockstitch independent (issued) -> a single point of failure on lockstitch.
    "W008": ("lockstitch", [(0.80, 0.012), (0.82, 0.015), (0.79, 0.011), (0.84, 0.010), (0.81, 0.013),
                            (0.83, 0.009), (0.80, 0.012)]),
}
_SAM = {"overlock": 0.5, "flatlock": 0.6, "lockstitch": 0.75}
_INDUCTION_EXPIRY = {"W004": "2026-11-06", "W006": "2026-11-14"}  # due inside 3 weeks
DEFAULT_INDUCTION_EXPIRY = "2027-04-15"


def _at(day: str, clock: str) -> str:
    """Return an ISO timestamp on `day` at `clock` (HH:MM:SS) in site time."""
    return f"{day}T{clock}{config.TZ}"


def _shift_end(day: str, day_index: int, wid: str) -> str:
    """Clock-out time for a seeded shift, spread over 17:05-17:54 so workers don't all post at once."""
    minute = (day_index * 7 + int(wid[1:]) * 3) % 50 + 5
    return _at(day, f"17:{minute:02d}:00")


def _seed_production(st: State) -> None:
    for wid, (op, plan) in _SEED_PLAN.items():
        sam = _SAM[op]
        for i, (day, cell) in enumerate(zip(SEED_DAYS, plan, strict=False)):
            if cell is None:
                continue
            eff, dr = cell
            pieces = round(eff * SHIFT_MINUTES / sam)
            defects = int(dr * pieces)  # floor keeps the plan's side of the 2.5% line
            payload = {"operation": op, "pieces": pieces, "sam": sam, "minutes": SHIFT_MINUTES, "defects": defects}
            st.ledger.append(events.PRODUCTION_COUNT, payload, worker_id=wid, ts=_shift_end(day, i, wid))


def seed_demo(st: State) -> None:
    """Seed the ledger with demo production records and credentials."""
    _seed_production(st)
    last_day = SEED_DAYS[-1]
    for wid, (op, _plan) in _SEED_PLAN.items():
        check_and_issue(wid, op, ts=_at(last_day, "18:00:00"))
    valid_days = SAFETY_CREDENTIALS[MACHINE_GUARDING]["valid_days"]
    for r in st.conn.execute("SELECT id FROM workers WHERE is_supervisor=0 ORDER BY id").fetchall():
        until = _INDUCTION_EXPIRY.get(r["id"], DEFAULT_INDUCTION_EXPIRY)
        trained = (date.fromisoformat(until) - timedelta(days=valid_days)).isoformat()
        issue_safety(r["id"], MACHINE_GUARDING, valid_from=_at(trained, "10:00:00"),
                     valid_until=until, ts=_at(last_day, "18:10:00"))
