"""The worker's view: their passport (credentials, status, progress) and the skills they hold."""
from __future__ import annotations

import json
from typing import Any, NotRequired, TypedDict

from .. import events, state
from .evidence import skill_progress
from .rules import SKILL_RULES, SYSTEM_EVIDENCED, level_rank
from .store import credential_rows, row_status, worker_row
from .vc import subject_id


class HeldSkill(TypedDict):
    """A level a worker holds on one skill, and the evidence behind it."""

    level: str
    evidence_level: int
    credential_id: str | None
    progress: NotRequired[str]


def passport(wid: str) -> dict[str, Any]:
    """Return a worker's skill passport with credentials and skill progress."""
    w = worker_row(wid)
    rows = credential_rows(wid)
    worked = {e["payload"].get("operation") for e in state.get().ledger.events(worker_id=wid, type=events.PRODUCTION_COUNT)}
    skills = set(SKILL_RULES) & ({w["operation"]} | worked)
    return {
        "worker_id": wid, "name": w["name"], "subject_id": subject_id(wid),
        "credentials": [json.loads(r["vc"]) for r in rows],
        "credential_status": {r["id"]: row_status(r) for r in rows},
        "progress": [skill_progress(wid, s) for s in SKILL_RULES if s in skills],
    }


def held_skills(wid: str) -> dict[str, HeldSkill]:
    """Return skill -> highest live (not revoked, not expired) skill credential the worker holds."""
    out: dict[str, HeldSkill] = {}
    for r in credential_rows(wid):
        s = row_status(r)
        if r["kind"] != "skill" or s["revoked"] or s["expired"]:
            continue
        cur = out.get(r["skill"])
        if not cur or level_rank(r["level"]) > level_rank(cur["level"]):
            out[r["skill"]] = {"level": r["level"], "evidence_level": SYSTEM_EVIDENCED, "credential_id": r["id"]}
    return out
