"""Proof of Hours: daily shifts built from signed punches, with corrections applied as new events."""
from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from .. import config, state
from ..ledger import Event, Ledger
from .records import accepted_ot_by_date
from .rules import BREAK_AFTER_HOURS, DEMO_PERIOD_START, RULES, round2

PUNCHES = ("punch.in", "punch.out")
SECONDS_PER_HOUR = 3600

# Functional form because "in" is a Python keyword.
PunchDay = TypedDict("PunchDay", {"day": str, "in": str | None, "out": str | None, "evidence": list[int], "corrected": bool})
"""One worker-day of punches: first punch-in, last punch-out and the event seqs behind them."""


class Shift(PunchDay):
    """A worker-day with the hours its punches prove, split by overtime consent."""
    worked_hours: float
    ot_hours: float
    consented_ot_hours: float
    unconsented_ot_hours: float
    complete: bool


def hours(wid: str, day_from: str = DEMO_PERIOD_START, day_to: str = config.DEMO_DAY) -> list[Shift]:
    """Shifts built from signed punches, with corrections applied as new events.

    Memoised until the next database write (any table, any connection), so the many hours() calls
    behind one console/fairness request read the punches once."""
    ledger = state.get().ledger
    return ledger.memo(("pay.hours", wid, day_from, day_to), lambda: _hours(ledger, wid, day_from, day_to))


def _corrected_times(evs: list[Event]) -> tuple[dict[int, str], set[int]]:
    """Return the effective timestamp of every punch by seq, and the seqs a correction replaced."""
    times = {e["seq"]: e["ts"] for e in evs if e["type"] in PUNCHES}
    corrected: set[int] = set()
    for e in evs:
        target = e["payload"].get("corrects_seq")
        if e["type"] == "punch.correction" and target in times:
            times[target] = e["payload"]["new_ts"]
            corrected.add(target)
    return times, corrected


def _punch_days(evs: list[Event], times: dict[int, str], corrected: set[int]) -> list[PunchDay]:
    """Group punches by day: the first punch-in, the last punch-out and every punch as evidence."""
    days: dict[str, PunchDay] = {}
    for e in evs:
        if e["type"] not in PUNCHES:
            continue
        d = days.setdefault(e["day"], {"day": e["day"], "in": None, "out": None, "evidence": [], "corrected": False})
        d["evidence"].append(e["seq"])
        d["corrected"] |= e["seq"] in corrected
        if e["type"] == "punch.out":
            d["out"] = times[e["seq"]]
        elif d["in"] is None:
            d["in"] = times[e["seq"]]
    return sorted(days.values(), key=lambda x: x["day"])


def _worked(t_in: str, t_out: str) -> float:
    """Return hours worked between two punches, less the break on a long span."""
    span = (datetime.fromisoformat(t_out) - datetime.fromisoformat(t_in)).total_seconds() / SECONDS_PER_HOUR
    return max(0.0, span - (RULES["break_hours"] if span > BREAK_AFTER_HOURS else 0))


def _hours(ledger: Ledger, wid: str, day_from: str, day_to: str) -> list[Shift]:
    evs = ledger.events(worker_id=wid, type_prefix="punch.", day_from=day_from, day_to=day_to)
    accepted = accepted_ot_by_date(wid)
    out: list[Shift] = []
    for d in _punch_days(evs, *_corrected_times(evs)):
        t_in, t_out = d["in"], d["out"]
        complete = bool(t_in and t_out)
        worked = _worked(t_in, t_out) if t_in and t_out else 0.0
        ot = max(0.0, worked - RULES["daily_hours"])
        consented = min(ot, accepted.get(d["day"], 0.0))
        out.append({**d, "worked_hours": round2(worked), "ot_hours": round2(ot),
                    "consented_ot_hours": round2(consented), "unconsented_ot_hours": round2(ot - consented),
                    "complete": complete})
    return out
