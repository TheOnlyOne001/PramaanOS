"""HTTP routes for safety reports (`/api/safety/...`). Who acts is taken from the token, never the body."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import auth
from .reports import CLIENT_ID_MAX, NOTE_MAX, ZONE_MAX, Report, acknowledge, list_reports, report, resolve

router = APIRouter(prefix="/api")


class ReportReq(BaseModel):
    """A hazard or stop-work call from the worker's phone. `worker_id` is used only when auth is off."""
    kind: Literal["hazard", "stop_work"]
    zone: str = Field(min_length=1, max_length=ZONE_MAX)
    note: str = Field(default="", max_length=NOTE_MAX)
    client_id: str | None = Field(default=None, max_length=CLIENT_ID_MAX)
    worker_id: str | None = None


class AckReq(BaseModel):
    """Optional note when acknowledging."""
    note: str = Field(default="", max_length=NOTE_MAX)


class ResolveReq(BaseModel):
    """What was done to fix the hazard."""
    note: str = Field(min_length=1, max_length=NOTE_MAX)


def _actor() -> tuple[str, str]:
    p = auth.current()
    return (p["sub"], p["role"]) if p else ("S001", "supervisor")


@router.post("/safety/reports")
def post_report(req: ReportReq) -> Report:
    """File a report as the signed-in worker; a repeat `client_id` returns the same report."""
    p = auth.current()
    wid = p.get("wid") if p else req.worker_id
    if not wid:
        raise HTTPException(422, "worker_id is required")
    return report(wid, req.kind, req.zone, req.note, req.client_id)


@router.get("/safety/reports")
def get_reports(worker_id: str | None = None) -> list[Report]:
    """Reports newest first. A worker only ever sees their own."""
    p = auth.current()
    if p and p["role"] == "worker":
        worker_id = p.get("wid")
    return list_reports(worker_id)


@router.post("/safety/reports/{report_id}/ack")
def post_ack(report_id: str, req: AckReq | None = None) -> Report:
    """Acknowledge a report (supervisor or HR)."""
    by, role = _actor()
    return acknowledge(report_id, by=by, role=role, note=req.note if req else "")


@router.post("/safety/reports/{report_id}/resolve")
def post_resolve(report_id: str, req: ResolveReq) -> Report:
    """Resolve a report with what was done (supervisor or HR)."""
    by, role = _actor()
    return resolve(report_id, req.note, by=by, role=role)
