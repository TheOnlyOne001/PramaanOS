"""Overtime limits: hours used against the quarterly cap, and the fatigue rule."""
from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict

from .. import config
from .records import accepted_ot_by_date, opening_events, workers
from .rules import RULES, quarter_of, round2
from .shifts import hours

FATIGUE_WINDOW_DAYS = 7


class CapStatus(TypedDict):
    """One worker's quarterly overtime usage against the cap."""
    worker_id: str
    name: str
    used: float
    cap: int
    remaining: float
    pct: float
    status: str


def quarter_used(wid: str, day: str) -> float:
    """Return overtime hours a worker has used in the quarter up to `day`, incl. opening balance and accepted requests."""
    q, start = quarter_of(day)
    used = sum(e["payload"]["hours"] for e in opening_events(wid, "ot.opening_balance", "quarter", q))
    shifts = hours(wid, start, day)
    used += sum(s["ot_hours"] for s in shifts)
    done = {s["day"] for s in shifts if s["complete"]}
    used += sum(h for d, h in accepted_ot_by_date(wid).items() if d >= start and d not in done)
    return round2(used)


def remaining(used: float) -> float:
    """Return the overtime hours left under the quarterly cap (never negative)."""
    return round2(max(0, RULES["ot_cap_quarter"] - used))


def is_near_cap(hours_used: float) -> bool:
    """True once usage reaches the near-cap warning share of the quarterly cap."""
    return hours_used >= RULES["near_cap_pct"] * RULES["ot_cap_quarter"]


def cap_status(date_: str | None = None) -> list[CapStatus]:
    """Return each worker's quarterly overtime usage vs. cap with an ok/near/over status (defaults to the demo day)."""
    day = date_ or config.DEMO_DAY
    cap = RULES["ot_cap_quarter"]
    out: list[CapStatus] = []
    for wid, w in workers().items():
        used = quarter_used(wid, day)
        status = "over" if used > cap else "near" if is_near_cap(used) else "ok"
        out.append({"worker_id": wid, "name": w["name"], "used": used, "cap": cap, "remaining": remaining(used),
                    "pct": round2(100 * used / cap), "status": status})
    return out


def fatigue(wid: str, day: str) -> str | None:
    """Return why more overtime on `day` would breach the fatigue rule, or None if it would not."""
    d = date.fromisoformat(day)
    shifts = {s["day"]: s for s in hours(wid, (d - timedelta(days=FATIGUE_WINDOW_DAYS)).isoformat(), day)}
    week = sum(s["ot_hours"] for s in shifts.values())
    if week > RULES["fatigue_week_ot"]:
        return f"{week:g} h overtime in the last 7 days (limit {RULES['fatigue_week_ot']})"
    streak = 0
    for i in range(1, FATIGUE_WINDOW_DAYS + 1):
        s = shifts.get((d - timedelta(days=i)).isoformat())
        if not s or s["ot_hours"] <= 0:
            break
        streak += 1
    if streak >= RULES["fatigue_streak_days"]:
        return f"overtime on {streak} days in a row"
    return None
