"""Restricted zones drawn in the Saakshi camera page: normalised polygons, foot-point entry, cooldown."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .geometry import foot_point, point_in_polygon
from .tracker import Track

COOLDOWN_S = 10.0


@dataclass(frozen=True, slots=True)
class Zone:
    """A zone polygon in normalised [0..1] frame coordinates."""

    id: str
    name: str
    points: tuple[tuple[float, float], ...]
    kind: str = "restricted"

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Zone:
        """Build from a GET /api/edge/zones item; coordinates are clamped to [0..1]."""
        pts = tuple((min(1.0, max(0.0, float(p[0]))), min(1.0, max(0.0, float(p[1])))) for p in d.get("points", []))
        return cls(id=str(d.get("id", d.get("name", "zone"))), name=str(d.get("name", "Zone")), points=pts,
                   kind=str(d.get("kind", "restricted")))

    def contains(self, x: float, y: float) -> bool:
        """True if the normalised point is inside the polygon."""
        return point_in_polygon(x, y, list(self.points))


@dataclass(frozen=True, slots=True)
class ZoneEntry:
    """A track's foot point crossed into a zone (and the cooldown allowed reporting it)."""

    zone: Zone
    track_id: int
    count: int  # people in the zone at that moment


@dataclass(slots=True)
class ZoneMonitor:
    """Per-(track, zone) enter/exit state with a cooldown so one person loitering at the edge is one event."""

    zones: list[Zone] = field(default_factory=list)
    cooldown_s: float = COOLDOWN_S
    _inside: set[tuple[int, str]] = field(default_factory=set)
    _last_fired: dict[tuple[int, str], float] = field(default_factory=dict)
    occupancy: dict[str, int] = field(default_factory=dict)

    def set_zones(self, zones: list[Zone]) -> None:
        """Replace the zone list (from the 2 s poll), dropping state for removed zones."""
        ids = {z.id for z in zones}
        self.zones = list(zones)
        self._inside = {k for k in self._inside if k[1] in ids}
        self._last_fired = {k: v for k, v in self._last_fired.items() if k[1] in ids}

    def update(self, tracks: list[Track], width: int, height: int, now: float) -> list[ZoneEntry]:
        """Update occupancy from track foot points; return entries that should be reported now."""
        inside_now: set[tuple[int, str]] = set()
        for t in tracks:
            fx, fy = foot_point(t.box, width, height)
            for z in self.zones:
                if z.contains(fx, fy):
                    inside_now.add((t.id, z.id))
        self.occupancy = {z.id: sum(1 for k in inside_now if k[1] == z.id) for z in self.zones}
        entries: list[ZoneEntry] = []
        by_id = {z.id: z for z in self.zones}
        for key in sorted(inside_now - self._inside):
            if now - self._last_fired.get(key, -math.inf) >= self.cooldown_s:
                self._last_fired[key] = now
                entries.append(ZoneEntry(by_id[key[1]], key[0], self.occupancy[key[1]]))
        self._inside = inside_now
        return entries

    def tracks_in_zones(self) -> set[int]:
        """Ids of tracks currently inside any zone."""
        return {k[0] for k in self._inside}
