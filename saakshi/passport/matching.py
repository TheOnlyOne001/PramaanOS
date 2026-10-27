"""Job matching: a keyword parser (no LLM) that turns a job description into skills and levels.

A worker is scored per required skill on the best evidence available: a live
credential, then their own production records, then the employer's HR record.
Every gap comes with a suggested training.
"""
from __future__ import annotations

import re
from typing import Any, TypedDict

from .evidence import skill_progress
from .holder import HeldSkill, held_skills
from .rules import EMPLOYER_ATTESTED, EVIDENCE_LABELS, LEARNING_LEVEL, LEVEL_LABELS, SKILL_RULES, SYSTEM_EVIDENCED, level_rank
from .store import worker_row

_SKILL_WORDS = [
    (r"over\s?-?lock|overlocker|serger", "overlock"),
    (r"flat\s?-?lock|cover\s?stitch", "flatlock"),
    (r"lock\s?-?stitch|single[\s-]needle|\bsnls\b|\bsnl\b", "lockstitch"),
    (r"check(ing|er)?\b|quality|\bqc\b|inspect", "checking"),
    (r"cutt(ing|er)|\bcut\b", "cutting"),
    (r"iron(ing)?|pack(ing|er)?\b|press(ing|man)\b|fold(ing)?", "packing"),
]
_LEVEL_WORDS = [
    (r"can train|train(s|ing)? others|\blead\b|leader|trainer|mentor|senior", "O"),
    (r"independent(ly)?|experienced|skilled|\bexpert\b|without supervision", "U"),
    (r"trainee|fresher|learner|apprentice|helper|beginner", "I"),
]
DEFAULT_REQUIRED_LEVEL = "U"
SKILL_LABELS = {**{s: r["label"] for s, r in SKILL_RULES.items()},
                "checking": "Quality checking", "cutting": "Cutting", "packing": "Ironing & packing"}
TRAININGS = {
    "overlock": {"title": "Overlock threading & seam quality", "days": 3,
                 "how": "On-line coaching by a level-O operator; Samarth/ATDC short module (illustrative)"},
    "flatlock": {"title": "Flatlock cover-stitch basics", "days": 3,
                 "how": "On-line coaching by a level-O operator (illustrative)"},
    "lockstitch": {"title": "Single-needle lockstitch: topstitch & label attach", "days": 4,
                   "how": "Training-room machine + 2 days on line (illustrative)"},
    "checking": {"title": "Inline & end-line checking (AQL 2.5 basics)", "days": 2,
                 "how": "With the QC lead; buyer spec sheet walkthrough (illustrative)"},
    "cutting": {"title": "Cutting room: spreading, marker reading, safe straight-knife use", "days": 3,
                "how": "Requires machine guarding induction first (illustrative)"},
    "packing": {"title": "Ironing, folding & packing to buyer spec", "days": 1,
                "how": "With the finishing supervisor (illustrative)"},
}
_BAND_LEVEL = {"unskilled": "L", "semi-skilled": "U", "skilled": "U", "highly-skilled": "O"}

# Per-skill fit score: full marks for a met level, discounted when it rests on weaker evidence or falls short.
SCORE_MET_EVIDENCED = 1.0
SCORE_MET_ATTESTED = 0.8
SCORE_ONE_LEVEL_SHORT = 0.5
SCORE_FURTHER_SHORT = 0.2
SCORE_NO_RECORD = 0.0


class Requirement(TypedDict):
    """One skill a job description asks for, at a level."""

    skill: str
    label: str
    level: str


def parse_job(text: str) -> list[Requirement]:
    """Parse a job description into required skills and levels by keyword."""
    t = text.lower()
    level = next((lv for pat, lv in _LEVEL_WORDS if re.search(pat, t)), DEFAULT_REQUIRED_LEVEL)
    seen: list[str] = []
    for pat, skill in _SKILL_WORDS:
        if re.search(pat, t) and skill not in seen:
            seen.append(skill)
    return [{"skill": s, "label": SKILL_LABELS[s], "level": level} for s in seen]


def _best_evidence(wid: str, w: dict[str, Any], skill: str, held: dict[str, HeldSkill]) -> tuple[HeldSkill | None, str]:
    """Return the strongest record of `skill` for the worker, and where it came from."""
    if skill in held:
        return held[skill], "credential"
    if skill in SKILL_RULES:
        p = skill_progress(wid, skill)
        if p["current"]["days"]:
            return ({"level": LEARNING_LEVEL, "evidence_level": SYSTEM_EVIDENCED, "credential_id": None},
                    f"production records ({p['days_met']}/{p['days_needed']} qualifying days)")
    if w["operation"] == skill:
        return ({"level": _BAND_LEVEL.get(w["skill_band"] or "", LEARNING_LEVEL), "evidence_level": EMPLOYER_ATTESTED,
                 "credential_id": None}, "employer HR record")
    return None, "credential"


def match(wid: str, job_description: str) -> dict[str, Any]:
    """Score a worker's fit for a job description and list matches, gaps and training."""
    w = worker_row(wid)
    required = parse_job(job_description)
    held = held_skills(wid)
    matched: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    training: list[dict[str, Any]] = []
    scores: list[float] = []
    for req in required:
        s, need = req["skill"], req["level"]
        h, source = _best_evidence(wid, w, s, held)
        if h:
            gap = level_rank(need) - level_rank(h["level"])
            entry = {"skill": s, "label": req["label"], "required_level": need, "level": h["level"],
                     "level_label": LEVEL_LABELS[h["level"]], "evidence_level": h["evidence_level"],
                     "evidence_label": EVIDENCE_LABELS[h["evidence_level"]], "credential_id": h["credential_id"],
                     "source": source}
            if gap <= 0:
                matched.append(entry)
                scores.append(SCORE_MET_EVIDENCED if h["evidence_level"] >= SYSTEM_EVIDENCED else SCORE_MET_ATTESTED)
                continue
            scores.append(SCORE_ONE_LEVEL_SHORT if gap == 1 else SCORE_FURTHER_SHORT)
            gaps.append({**entry, "reason": f"Needs level {need} ({LEVEL_LABELS[need]}); has {h['level']}"})
        else:
            scores.append(SCORE_NO_RECORD)
            gaps.append({"skill": s, "label": req["label"], "required_level": need, "level": None,
                         "reason": f"No record of {req['label'].lower()}"})
        training.append({"skill": s, **TRAININGS[s]})
    fit = round(100 * sum(scores) / len(scores)) if scores else 0
    return {"worker_id": wid, "name": w["name"], "fit": fit, "required": required, "matched": matched,
            "gaps": gaps, "training": training,
            "note": None if required else "No known skills found in the job description"}
