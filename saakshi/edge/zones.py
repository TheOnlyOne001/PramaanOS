"""Restricted zones drawn on a camera's frame: polygons in normalized (0..1) frame coordinates.

Zone shapes are not personal data, so anyone (the box included) may read them. Supervisors and HR set them;
each change is a signed `edge.zones_set` ledger event, and the latest set per camera is kept in `edge_zones`.
The box reports `restricted_zone_entry` events with `zone` set to one of these names.
"""
from __future__ import annotations

import copy
import json
from typing import Annotated, Literal, TypedDict

from fastapi import HTTPException
from pydantic import BaseModel, Field, StringConstraints

from .. import db, events, state
from . import clock
from .privacy import PrivacyViolation, privacy_check

MIN_POINTS, MAX_POINTS, MAX_ZONES = 3, 20, 10
MIN_AREA = 0.001  # share of the frame; anything thinner is a line, not a zone

SCHEMA = """
CREATE TABLE IF NOT EXISTS edge_zones(
  camera TEXT PRIMARY KEY, zones TEXT NOT NULL, updated_at TEXT NOT NULL, seq INTEGER);
"""
db.register_schema(SCHEMA)


class Zone(TypedDict):
    """A stored zone: id, name, kind, polygon points and when it was last set."""
    id: str
    name: str
    kind: str
    points: list[list[float]]
    updated_at: str


class CameraZones(TypedDict):
    """Every zone configured on one camera."""
    camera: str
    zones: list[Zone]


DEFAULT_UPDATED_AT = "2026-10-27T08:00:00+05:30"
DEFAULTS: dict[str, list[Zone]] = {
    # The press occupies roughly the right third of the demo webcam's frame.
    "cam-01": [{"id": "press", "name": "Press zone", "kind": "restricted",
                "points": [[0.66, 0.05], [0.98, 0.05], [0.98, 0.95], [0.66, 0.95]], "updated_at": DEFAULT_UPDATED_AT}],
}


class ZoneIn(BaseModel):
    """One zone in a PUT body."""
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")] | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    kind: Literal["restricted"] = "restricted"
    points: list[list[float]] = Field(min_length=MIN_POINTS, max_length=MAX_POINTS)


class ZonesIn(BaseModel):
    """PUT /api/edge/zones body: the full zone set for one camera (replaces the previous set)."""
    camera: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
    zones: list[ZoneIn] = Field(max_length=MAX_ZONES)


def area(points: list[list[float]]) -> float:
    """Absolute polygon area by the shoelace formula (normalized units, so 1.0 is the whole frame)."""
    s = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _check(z: ZoneIn, i: int) -> None:
    """Raise 422 unless the zone's points are [x, y] pairs in [0, 1] enclosing a real area and its name is clean."""
    where = f"zones[{i}]"
    for j, p in enumerate(z.points):
        if len(p) != 2:
            raise HTTPException(422, f"{where}.points[{j}] must be [x, y]")
        if not all(0.0 <= v <= 1.0 for v in p):  # also refuses NaN
            raise HTTPException(422, f"{where}.points[{j}] must lie within [0, 1] (normalized frame coordinates)")
    if area(z.points) <= MIN_AREA:
        raise HTTPException(422, f"{where} is degenerate: its area must exceed {MIN_AREA} of the frame")
    try:
        privacy_check({"zone": z.name})
    except PrivacyViolation as e:
        raise HTTPException(422, f"{where}.name: privacy guard: {e}") from e


def get(camera: str) -> CameraZones:
    """The latest zone set for `camera` (the built-in default when none has been set; [] if neither)."""
    r = state.get().conn.execute("SELECT zones FROM edge_zones WHERE camera=?", (camera,)).fetchone()
    zones: list[Zone] = json.loads(r["zones"]) if r else copy.deepcopy(DEFAULTS.get(camera, []))
    return {"camera": camera, "zones": zones}


def put(body: ZonesIn) -> CameraZones:
    """Validate and store the zone set for a camera, and append a signed `edge.zones_set` event."""
    for i, z in enumerate(body.zones):
        _check(z, i)
    ts = clock.iso()
    zones: list[Zone] = []
    for i, z in enumerate(body.zones):
        zones.append({"id": z.id or f"zone-{i + 1}", "name": z.name, "kind": z.kind,
                      "points": [[float(x), float(y)] for x, y in z.points], "updated_at": ts})
    if len({z["id"] for z in zones}) != len(zones):
        raise HTTPException(422, "zone ids must be unique on a camera")
    if len({z["name"].lower() for z in zones}) != len(zones):
        raise HTTPException(422, "zone names must be unique on a camera")
    st = state.get()
    with st.lock:
        ev = st.ledger.append(events.EDGE_ZONES_SET, {"camera": body.camera, "zones": zones}, worker_id=None, ts=ts)
        st.conn.execute("INSERT INTO edge_zones(camera, zones, updated_at, seq) VALUES (?,?,?,?) "
                        "ON CONFLICT(camera) DO UPDATE SET zones=excluded.zones, updated_at=excluded.updated_at, seq=excluded.seq",
                        (body.camera, json.dumps(zones), ts, ev["seq"]))
    return {"camera": body.camera, "zones": zones}
