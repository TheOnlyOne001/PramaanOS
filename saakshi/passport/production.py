"""Recording production counts: validate, append a signed `production.count`, auto-issue credentials."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from .. import events, state
from .credentials import check_and_issue
from .evidence import DEFECT_RATE_DIGITS, EFFICIENCY_DIGITS
from .store import worker_row


class Production(BaseModel):
    """Production count record submitted for a worker."""

    worker_id: str
    operation: str
    pieces: int
    sam: float
    minutes: float
    defects: int = 0
    ts: str | None = None


def record_production(p: Production | dict[str, Any]) -> dict[str, Any]:
    """Validate and record a production count, issuing any newly earned credentials."""
    p = p if isinstance(p, Production) else Production(**p)
    worker_row(p.worker_id)
    if p.pieces <= 0 or p.minutes <= 0 or p.sam <= 0 or p.defects < 0 or p.defects > p.pieces:
        raise HTTPException(422, "pieces, sam and minutes must be positive; 0 <= defects <= pieces")
    payload = {"operation": p.operation, "pieces": p.pieces, "sam": p.sam, "minutes": p.minutes, "defects": p.defects}
    ev = state.get().ledger.append(events.PRODUCTION_COUNT, payload, worker_id=p.worker_id, ts=p.ts)
    # a back-dated record issues at its own time; a live one at "now"
    issued = check_and_issue(p.worker_id, p.operation, ts=None if p.ts is None else ev["ts"])
    return {"event": ev, "efficiency": round(p.pieces * p.sam / p.minutes, EFFICIENCY_DIGITS),
            "defect_rate": round(p.defects / p.pieces, DEFECT_RATE_DIGITS), "issued": issued}
