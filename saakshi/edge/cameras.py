"""What the edge box may report: event kinds, which of them are alerts, and each camera's public notice.

Every camera publishes its zone, purpose, owner, retention and signage languages,
and processes on device: only counts and alerts ever leave the box.
"""
from __future__ import annotations

from typing import TypedDict

DEMO_BOX = "edge-box-1"
BOX_KEYS = {DEMO_BOX: DEMO_BOX}  # box_id -> KeyStore key name

KINDS = {
    "restricted_zone_entry": "Someone entered a restricted zone",
    "ppe_noncompliance": "PPE missing",
    "ppe_compliance_rate": "Share of people seen wearing required PPE (0-1)",
    "fire_smoke": "Smoke or fire detected",
    "blocked_exit": "Exit or aisle blocked",
    "person_down": "Person down (possible fall or collapse)",
    "queue_length": "People waiting in a queue",
    "near_miss": "Near miss between a person and a machine or vehicle",
    "heat_wbgt": "Heat stress index (WBGT, °C)",
}
ALERT_KINDS = {"restricted_zone_entry", "fire_smoke", "blocked_exit", "person_down", "near_miss", "ppe_noncompliance"}

SIGNAGE = ["ta", "hi", "or", "en"]
OWNER = "EHS officer, TUP-03 (reviewed by the safety committee)"
RETENTION_HOURS = 24


class Camera(TypedDict):
    """A camera's published notice: where it looks, why, who owns it and what leaves the box."""

    camera: str
    zone: str
    purpose: str
    kinds: list[str]
    owner: str
    retention_hours: int
    signage_languages: list[str]
    box_id: str
    stores_images: bool
    processing: str






def _camera(camera: str, zone: str, purpose: str, kinds: list[str]) -> Camera:
    """Return a camera notice with the site-wide owner, retention and on-device processing terms."""
    return {"camera": camera, "zone": zone, "purpose": purpose, "kinds": kinds, "owner": OWNER,
            "retention_hours": RETENTION_HOURS, "signage_languages": SIGNAGE, "box_id": DEMO_BOX,
            "stores_images": False, "processing": "on device; only counts and alerts leave the box"}


CAMERAS = [
    _camera("cam-01", "Gate", "Exit kept clear; crowding at shift change", ["blocked_exit", "queue_length"]),
    _camera("cam-04", "Line 4", "PPE (needle guards, masks) and near misses on the line",
            ["ppe_compliance_rate", "ppe_noncompliance", "near_miss", "person_down"]),
    _camera("cam-07", "Press zone", "Keep people out of the press area while it runs; heat",
            ["restricted_zone_entry", "ppe_compliance_rate", "heat_wbgt"]),
    _camera("cam-09", "Canteen", "Smoke near the kitchen; lunch queue", ["fire_smoke", "queue_length"]),
    _camera("cam-11", "Water point", "Queue at the drinking water point", ["queue_length"]),
    _camera("cam-12", "Store", "Smoke in the fabric store; blocked aisles", ["fire_smoke", "blocked_exit"]),
]
ZONES = [c["zone"] for c in CAMERAS]
