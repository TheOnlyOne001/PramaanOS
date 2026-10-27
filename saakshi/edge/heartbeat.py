"""Box heartbeats: liveness and counters per camera, kept in memory only (never in the ledger).

A heartbeat says the box is up, how fast it runs, which detector backends it uses and how many faces it has
blurred so far. It carries no imagery and no identity. `preview_url` may only point at the box's own local
MJPEG preview (http(s)://127.0.0.1 or localhost); any other URL is refused rather than echoed to the console.
"""
from __future__ import annotations

import re
import weakref
from typing import Any, TypedDict

from fastapi import HTTPException

from .. import state
from . import clock
from .camera_punch import check_box_body
from .ingest import is_number, verify_box

ONLINE_WITHIN = 10  # seconds since the last heartbeat for a camera to count as online
_TEXT = ("device", "backend", "face_backend")
_COUNTS = ("faces_blurred_total", "persons_now", "in_zone_now")
_FIELDS = {"box_id", "camera", "ts", "fps", "preview_url", "sig", *_TEXT, *_COUNTS}
PREVIEW_URL = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d{1,5})?(/[A-Za-z0-9._~/?&=%+-]*)?$")


class CameraStatus(TypedDict):
    """The latest heartbeat of one camera, as the console shows it."""
    camera: str
    box_id: str
    last_seen: str
    online: bool
    fps: float | None
    device: str | None
    backend: str | None
    face_backend: str | None
    faces_blurred_total: int | None
    persons_now: int | None
    in_zone_now: int | None
    preview_url: str | None


# Per State (so a test's fresh state starts empty): camera -> (unix time seen, latest status).
_beats: weakref.WeakKeyDictionary[state.State, dict[str, tuple[float, CameraStatus]]] = weakref.WeakKeyDictionary()


def _store() -> dict[str, tuple[float, CameraStatus]]:
    return _beats.setdefault(state.get(), {})


def _validate(b: dict[str, Any]) -> None:
    if b.get("fps") is not None and (not is_number(b["fps"]) or not 0 <= b["fps"] <= 1000):
        raise HTTPException(422, "'fps' must be a number between 0 and 1000")
    for f in _TEXT:
        if b.get(f) is not None and (not isinstance(b[f], str) or len(b[f]) > 40):
            raise HTTPException(422, f"'{f}' must be a string of at most 40 characters")
    for f in _COUNTS:
        v = b.get(f)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            raise HTTPException(422, f"'{f}' must be a non-negative integer")
    url = b.get("preview_url")
    if url not in (None, "") and (not isinstance(url, str) or len(url) > 200 or not PREVIEW_URL.fullmatch(url)):
        raise HTTPException(422, "'preview_url' must be http(s)://127.0.0.1 or http(s)://localhost (any port)")


def beat(body: object) -> CameraStatus:
    """Verify a box-signed heartbeat and keep it as the camera's latest status."""
    b = check_box_body(body, _FIELDS, ("box_id", "camera", "ts", "sig"))
    _validate(b)
    verify_box(b)
    t = clock.now()
    fps = b.get("fps")
    s: CameraStatus = {
        "camera": b["camera"], "box_id": b["box_id"], "last_seen": clock.iso(t), "online": True,
        "fps": float(fps) if fps is not None else None,
        "device": b.get("device"), "backend": b.get("backend"), "face_backend": b.get("face_backend"),
        "faces_blurred_total": b.get("faces_blurred_total"), "persons_now": b.get("persons_now"),
        "in_zone_now": b.get("in_zone_now"), "preview_url": b.get("preview_url") or None,
    }
    _store()[b["camera"]] = (t, s)
    return s


def status() -> list[CameraStatus]:
    """Latest heartbeat per camera, sorted by camera; `online` if seen within `ONLINE_WITHIN` seconds."""
    t = clock.now()
    out: list[CameraStatus] = []
    for _, (seen, s) in sorted(_store().items(), key=lambda kv: kv[0]):
        row = s.copy()
        row["online"] = t - seen <= ONLINE_WITHIN
        out.append(row)
    return out
