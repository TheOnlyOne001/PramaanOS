"""HTTP routes for edge events (`/api/edge/...`)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from ..ledger import Event
from .cameras import CAMERAS, Camera
from .ingest import ingest
from .reports import EdgeRow, recent, summary

router = APIRouter(prefix="/api")


@router.post("/edge/events")
def post_event(body: dict[str, Any] = Body(...)) -> Event:
    """Ingest an edge event posted over HTTP."""
    return ingest(body)


@router.get("/edge/events")
def get_events(limit: int = 50, kind: str | None = None) -> list[EdgeRow]:
    """Return recent edge events over HTTP."""
    return recent(limit, kind)


@router.get("/edge/summary")
def get_summary(day: str | None = None) -> dict[str, Any]:
    """Return the daily edge summary over HTTP."""
    return summary(day)


@router.get("/edge/cameras")
def get_cameras() -> list[Camera]:
    """Return the configured edge cameras."""
    return CAMERAS
