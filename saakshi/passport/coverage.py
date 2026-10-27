"""Employer views: the skills x workers coverage matrix, single points of failure and expiring credentials."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .. import state
from .evidence import skill_progress
from .holder import HeldSkill, held_skills
from .rules import INDEPENDENT_LEVELS, LEARNING_LEVEL, SAFETY_CREDENTIALS, SKILL_RULES, SYSTEM_EVIDENCED
from .store import credential_rows, today, worker_names

DEFAULT_EXPIRY_HORIZON_DAYS = 30


def _cell(wid: str, skill: str, held: dict[str, HeldSkill]) -> HeldSkill | None:
    """Return what the matrix shows for one worker and skill: a credential, progress, or nothing."""
    if skill in held:
        return held[skill]
    p = skill_progress(wid, skill)
    if not p["current"]["days"]:
        return None
    return {"level": LEARNING_LEVEL, "evidence_level": SYSTEM_EVIDENCED, "credential_id": None,
            "progress": f"{p['days_met']}/{p['days_needed']} days"}


def coverage() -> dict[str, Any]:
    """Skills x workers matrix, with single points of failure (a skill only one person holds at U/O)."""
    conn = state.get().conn
    workers = [dict(r) for r in conn.execute("SELECT id, name, operation FROM workers WHERE is_supervisor=0 ORDER BY id")]
    skills = list(SKILL_RULES)
    matrix: dict[str, dict[str, HeldSkill]] = {}
    for w in workers:
        held = held_skills(w["id"])
        cells = {s: _cell(w["id"], s, held) for s in skills}
        matrix[w["id"]] = {s: c for s, c in cells.items() if c is not None}
    spof: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    holders: dict[str, list[str]] = {}
    for s in skills:
        label = SKILL_RULES[s]["label"]
        hs = [w for w in workers if s in matrix[w["id"]] and matrix[w["id"]][s]["level"] in INDEPENDENT_LEVELS]
        holders[s] = [w["id"] for w in hs]
        if len(hs) == 1:
            spof.append({"skill": s, "label": label, "worker_id": hs[0]["id"], "name": hs[0]["name"],
                         "detail": f"Only {hs[0]['name']} works independently on {label.lower()}"})
        elif not hs:
            uncovered.append({"skill": s, "label": label})
    return {"skills": [{"skill": s, "label": SKILL_RULES[s]["label"]} for s in skills],
            "workers": [{"id": w["id"], "name": w["name"]} for w in workers],
            "matrix": matrix, "holders": holders, "single_points_of_failure": spof, "uncovered": uncovered}


def expiring(days: int = DEFAULT_EXPIRY_HORIZON_DAYS, on: str | None = None) -> list[dict[str, Any]]:
    """Live credentials whose validUntil falls within `days` of `on` (default the demo day)."""
    on = on or today()
    start = date.fromisoformat(on)
    horizon = (start + timedelta(days=days)).isoformat()
    names = worker_names()
    out = []
    for r in credential_rows():
        if r["valid_until"] and not r["revoked"] and on <= r["valid_until"] <= horizon:
            spec = SAFETY_CREDENTIALS.get(r["skill"])
            out.append({"credential_id": r["id"], "worker_id": r["worker_id"], "name": names.get(r["worker_id"]),
                        "skill": r["skill"], "label": spec["label"] if spec else r["skill"],
                        "valid_until": r["valid_until"],
                        "days_left": (date.fromisoformat(r["valid_until"]) - start).days})
    return sorted(out, key=lambda x: x["valid_until"])
