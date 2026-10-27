"""Versioned skill rules: what each credential requires, and the labels for levels and evidence.

`RULES_VERSION` is written into every skill credential, so a verifier can tell which
criteria it was issued under. Thresholds are exact fractions, never floats, so a
borderline shift cannot flip because of rounding.
"""
from __future__ import annotations

from typing import TypedDict

RULES_VERSION = "TUP-03/skills/2026-10-v1"
NSQF_SMO = "AMH/Q0301 (Sewing Machine Operator) — illustrative"

Fraction = tuple[int, int]
"""An exact ratio as (numerator, denominator)."""

LEVELS = ["I", "L", "U", "O"]  # ILUO skill matrix, lowest first
LEVEL_LABELS = {"I": "In training", "L": "Works with supervision", "U": "Works independently", "O": "Can train others"}
LEARNING_LEVEL = "L"  # what production records show before a credential is earned
INDEPENDENT_LEVELS = ("U", "O")  # levels that count as covering a skill

EMPLOYER_ATTESTED = 2
SYSTEM_EVIDENCED = 3
EVIDENCE_LABELS = {1: "Self-declared", EMPLOYER_ATTESTED: "Employer-attested", SYSTEM_EVIDENCED: "System-evidenced",
                   4: "Independently assessed"}
EVIDENCE_EXPLAIN = {
    1: "The worker said so; nobody has checked.",
    EMPLOYER_ATTESTED: "The employer's HR record says so (a supervisor vouched for it).",
    SYSTEM_EVIDENCED: "Computed from signed, tamper-evident production records on the shop floor.",
    4: "Tested by an outside assessor.",
}


class SkillRule(TypedDict):
    """Criteria a worker must meet on one skill to earn its credential."""

    label: str
    level: str
    evidence_level: int
    min_days: int
    min_efficiency: Fraction
    max_defect_rate: Fraction
    nsqf: str


class SafetySpec(TypedDict):
    """An expiring safety credential and how long it stays valid."""

    label: str
    valid_days: int


# Sewing operations share one bar: 5 shift days at >= 70% efficiency and <= 2.5% defects.
SEWING_MIN_DAYS = 5
SEWING_MIN_EFFICIENCY: Fraction = (70, 100)
SEWING_MAX_DEFECT_RATE: Fraction = (25, 1000)


def _sewing_rule(label: str) -> SkillRule:
    """Return the independent-operator rule for one sewing operation."""
    return SkillRule(label=label, level="U", evidence_level=SYSTEM_EVIDENCED, min_days=SEWING_MIN_DAYS,
                     min_efficiency=SEWING_MIN_EFFICIENCY, max_defect_rate=SEWING_MAX_DEFECT_RATE, nsqf=NSQF_SMO)


SKILL_RULES: dict[str, SkillRule] = {
    "overlock": _sewing_rule("Overlock"),
    "flatlock": _sewing_rule("Flatlock"),
    "lockstitch": _sewing_rule("Lockstitch"),
}

MACHINE_GUARDING = "machine_guarding_induction"
SAFETY_CREDENTIALS: dict[str, SafetySpec] = {
    MACHINE_GUARDING: SafetySpec(label="Machine guarding induction", valid_days=180),
}


def level_rank(level: str) -> int:
    """Return a level's position on the ILUO scale (0 = in training)."""
    return LEVELS.index(level)
