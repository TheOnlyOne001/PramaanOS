"""Edge camera events: counts and alerts from an on-site box, never images or identities.

The box (e.g. a Jetson running detection locally) signs each event with its own
Ed25519 key over canonical(body without sig). We verify the signature, refuse
anything that smells of imagery or person identity, and append an `edge.event`
to the ledger (worker_id None: these are about places, not people).

Modules: `cameras` (kinds and camera notices), `privacy` (the guard), `ingest`
(sign/verify/append), `reports` (recent events, daily summary), `seed` (demo data),
`api` (HTTP routes).
"""
from __future__ import annotations

from .api import get_cameras, get_events, get_summary, post_event, router
from .cameras import ALERT_KINDS, BOX_KEYS, CAMERAS, DEMO_BOX, KINDS, ZONES, Camera
from .ingest import ingest, make_event
from .privacy import PrivacyViolation, privacy_check
from .reports import EdgeRow, recent, summary
from .seed import seed_demo

__all__ = [
    "ALERT_KINDS",
    "BOX_KEYS",
    "CAMERAS",
    "DEMO_BOX",
    "KINDS",
    "ZONES",
    "Camera",
    "EdgeRow",
    "PrivacyViolation",
    "get_cameras",
    "get_events",
    "get_summary",
    "ingest",
    "make_event",
    "post_event",
    "privacy_check",
    "recent",
    "router",
    "seed_demo",
    "summary",
]
