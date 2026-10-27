"""HTTP routes for edge events, camera punches, zones and box status (`/api/edge/...`), plus worker badges."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from ..ledger import Event
from . import badge, camera_punch, heartbeat, zones
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


@router.get("/workers/{wid}/badge")
def get_badge(wid: str) -> badge.Badge:
    """Issue the worker's rotating 30-second badge (shown as a QR; identity at the camera comes only from it)."""
    return badge.issue(wid)


@router.post("/edge/punch")
def post_punch(body: dict[str, Any] = Body(...)) -> camera_punch.CameraPunch:
    """Record a punch from a box-signed badge scan, toggling in/out for the worker."""
    return camera_punch.punch(body)


@router.get("/edge/zones")
def get_zones(camera: str = "cam-01") -> zones.CameraZones:
    """Return the restricted zones drawn on a camera's frame (normalized polygon points)."""
    return zones.get(camera)


@router.put("/edge/zones")
def put_zones(body: zones.ZonesIn) -> zones.CameraZones:
    """Replace a camera's zone set and append a signed `edge.zones_set` event."""
    return zones.put(body)


@router.post("/edge/heartbeat")
def post_heartbeat(body: dict[str, Any] = Body(...)) -> heartbeat.CameraStatus:
    """Accept a box-signed heartbeat (kept in memory, not in the ledger)."""
    return heartbeat.beat(body)


@router.get("/edge/status")
def get_status() -> list[heartbeat.CameraStatus]:
    """Return the latest heartbeat per camera with an online flag."""
    return heartbeat.status()
