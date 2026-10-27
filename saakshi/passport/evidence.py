"""Skill evidence: per-day efficiency and defect maths over signed `production.count` events.

Progress is computed from ledger events only (never from a side table), so anything
the passport claims can be traced to signed seqs. Evidence already used by a
credential revoked for fraud never counts again.
"""
from __future__ import annotations

import json
import statistics
from typing import NamedTuple, TypedDict

from .. import events, state
from ..ledger import Event
from .rules import LEVEL_LABELS, RULES_VERSION, SKILL_RULES, Fraction, SkillRule
from .store import revoked_vcs

EFFICIENCY_DIGITS = 3
DEFECT_RATE_DIGITS = 4
FLOAT_TOLERANCE = 1e-9  # efficiency is a float ratio of float minutes; allow for representation error
NO_PIECES_DEFECT_RATE = 1.0  # a day with no pieces can never pass on quality


class DayStats(TypedDict):
    """Unrounded totals for one worker, skill and shift day."""

    day: str
    pieces: int
    defects: int
    efficiency: float
    defect_rate: float
    seqs: list[int]


class DayProgress(TypedDict):
    """One shift day as shown in the passport (rounded for display)."""

    day: str
    efficiency: float
    defect_rate: float
    pieces: int
    defects: int
    qualifies: bool
    seqs: list[int]


class Criteria(TypedDict):
    """A skill rule's thresholds in display form."""

    min_days: int
    min_efficiency: float
    max_defect_rate: float
    text: str


class Current(TypedDict):
    """Where the worker stands against the criteria today."""

    days: int
    qualifying_days: list[str]
    median_efficiency: float | None
    max_defect_rate: float | None
    by_day: list[DayProgress]


class SkillProgress(TypedDict):
    """A worker's progress toward one skill credential."""

    skill: str
    label: str
    level: str
    level_label: str
    evidence_level: int
    rules_version: str
    criteria: Criteria
    current: Current
    met: bool
    days_needed: int
    days_met: int


class Assessment(NamedTuple):
    """Progress plus the unrounded qualifying days a credential is built from."""

    progress: SkillProgress
    qualifying: list[DayStats]


def day_stats(day: str, evs: list[Event]) -> DayStats:
    """Total one day's production events into pieces, defects, efficiency and defect rate."""
    pieces = sum(int(e["payload"]["pieces"]) for e in evs)
    std_minutes = sum(float(e["payload"]["pieces"]) * float(e["payload"]["sam"]) for e in evs)
    minutes = sum(float(e["payload"]["minutes"]) for e in evs)
    defects = sum(int(e["payload"]["defects"]) for e in evs)
    return {"day": day, "pieces": pieces, "defects": defects,
            "efficiency": std_minutes / minutes if minutes else 0.0,
            "defect_rate": defects / pieces if pieces else NO_PIECES_DEFECT_RATE,
            "seqs": [e["seq"] for e in evs]}


def qualifies(stats: DayStats, rule: SkillRule) -> bool:
    """Return True if a day meets the rule's efficiency and defect thresholds."""
    n, d = rule["min_efficiency"]
    max_n, max_d = rule["max_defect_rate"]
    # defects are compared exactly in integer arithmetic; efficiency within FLOAT_TOLERANCE
    return stats["efficiency"] * d >= n - FLOAT_TOLERANCE and stats["defects"] * max_d <= max_n * stats["pieces"]


def _ratio(f: Fraction) -> float:
    return f[0] / f[1]


def _percent(f: Fraction) -> str:
    return f"{100 * f[0] / f[1]:g}"


def criteria(rule: SkillRule) -> Criteria:
    """Return the rule's thresholds as numbers and as the sentence written into credentials."""
    return {"min_days": rule["min_days"], "min_efficiency": _ratio(rule["min_efficiency"]),
            "max_defect_rate": _ratio(rule["max_defect_rate"]),
            "text": f"{rule['min_days']} shift days at ≥{_percent(rule['min_efficiency'])}% efficiency"
                    f" and ≤{_percent(rule['max_defect_rate'])}% defects"}


def median_efficiency(days: list[DayStats]) -> float:
    """Return the median unrounded efficiency over the given days."""
    return statistics.median(d["efficiency"] for d in days)


def max_defect_rate(days: list[DayStats]) -> float:
    """Return the worst unrounded defect rate over the given days."""
    return max(d["defect_rate"] for d in days)


def excluded_seqs(wid: str, skill: str) -> set[int]:
    """Evidence already used by a credential revoked for fraud never counts again."""
    out: set[int] = set()
    for vc in revoked_vcs(wid, skill):
        out.update(json.loads(vc)["credentialSubject"].get("evidence", {}).get("ledgerSeqs", []))
    return out


def production_days(wid: str, skill: str) -> list[DayStats]:
    """Return per-day totals of the worker's countable production on `skill`, oldest first."""
    excluded = excluded_seqs(wid, skill)
    by_day: dict[str, list[Event]] = {}
    for e in state.get().ledger.events(worker_id=wid, type=events.PRODUCTION_COUNT):
        if e["payload"].get("operation") == skill and e["seq"] not in excluded:
            by_day.setdefault(e["day"], []).append(e)
    return [day_stats(day, by_day[day]) for day in sorted(by_day)]


def _display(s: DayStats, ok: bool) -> DayProgress:
    return {"day": s["day"], "efficiency": round(s["efficiency"], EFFICIENCY_DIGITS),
            "defect_rate": round(s["defect_rate"], DEFECT_RATE_DIGITS), "pieces": s["pieces"],
            "defects": s["defects"], "qualifies": ok, "seqs": s["seqs"]}


def assess(wid: str, skill: str) -> Assessment:
    """Evaluate a worker's ledger evidence against the rule for `skill`."""
    rule = SKILL_RULES[skill]
    days = production_days(wid, skill)
    judged = [(s, qualifies(s, rule)) for s in days]
    q = [s for s, ok in judged if ok]
    progress: SkillProgress = {
        "skill": skill, "label": rule["label"], "level": rule["level"], "level_label": LEVEL_LABELS[rule["level"]],
        "evidence_level": rule["evidence_level"], "rules_version": RULES_VERSION,
        "criteria": criteria(rule),
        "current": {"days": len(days), "qualifying_days": [s["day"] for s in q],
                    "median_efficiency": round(median_efficiency(q), EFFICIENCY_DIGITS) if q else None,
                    "max_defect_rate": round(max_defect_rate(q), DEFECT_RATE_DIGITS) if q else None,
                    "by_day": [_display(s, ok) for s, ok in judged]},
        "met": len(q) >= rule["min_days"], "days_needed": rule["min_days"], "days_met": len(q),
    }
    return Assessment(progress, q)


def skill_progress(wid: str, skill: str) -> SkillProgress:
    """Return a worker's progress toward the criteria for a skill credential."""
    return assess(wid, skill).progress
