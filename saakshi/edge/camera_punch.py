"""Camera punches: the box reads a worker's rotating badge QR and posts it, signed with the box key.

Identity comes only from the badge (never from a face). The server verifies the box signature, then the
badge signature and expiry, burns the badge nonce, refuses a second punch within `MIN_GAP` seconds,
and toggles: the worker's last punch today was `punch.in` → append `punch.out`, else `punch.in`.
The event names the worker, so she gets a receipt in her language like any gate punch.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, TypedDict

from fastapi import HTTPException

from .. import events, state
from ..ledger import Receipt
from . import badge, clock
from .ingest import verify_box

MIN_GAP = 60  # seconds between two punches of one worker
_FIELDS = {"box_id", "camera", "badge", "ts", "sig"}
CAMERA_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class CameraPunch(TypedDict):
    """What the box (and the camera page) shows after a punch."""
    worker_id: str
    name: str
    kind: str
    seq: int
    ts: str
    receipt_text: str
    receipt_text_en: str


def check_box_body(body: object, fields: set[str], required: tuple[str, ...]) -> dict[str, Any]:
    """Return `body` if it is an object with only `fields`, the `required` ones non-empty strings, and a valid camera.

    Raises 422. No other field is ever accepted, so a box cannot ship an image or a face alongside.
    """
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    extra = set(body) - fields
    if extra:
        raise HTTPException(422, f"unknown fields: {sorted(extra)}")
    for f in required:
        if not isinstance(body.get(f), str) or not body[f]:
            raise HTTPException(422, f"'{f}' is required")
    if not CAMERA_ID.fullmatch(body["camera"]):
        raise HTTPException(422, "'camera' must be 1-40 letters, digits, '-' or '_'")
    try:
        datetime.fromisoformat(body["ts"])
    except ValueError:
        raise HTTPException(422, "'ts' must be ISO 8601") from None
    return body


def _last_punch_today(wid: str, day: str) -> tuple[str | None, float | None]:
    """(type, unix time) of the worker's latest punch.in/out on `day`, else (None, None)."""
    st = state.get()
    for ev in st.ledger.events(worker_id=wid, day=day, desc=True):
        if ev["type"] in (events.PUNCH_IN, events.PUNCH_OUT):
            return ev["type"], datetime.fromisoformat(ev["ts"]).timestamp()
    return None, None


def _last_punch_any(wid: str) -> float | None:
    """Unix time of the worker's most recent punch.in/out on any day (newest seq first)."""
    rows = state.get().conn.execute("SELECT ts FROM events WHERE worker_id=? AND type IN (?, ?) ORDER BY seq DESC LIMIT 1",
                           (wid, events.PUNCH_IN, events.PUNCH_OUT)).fetchall()
    return datetime.fromisoformat(rows[0]["ts"]).timestamp() if rows else None


def punch(body: object) -> CameraPunch:
    """Verify a box-signed badge scan and append the worker's punch.in or punch.out."""
    b = check_box_body(body, _FIELDS, ("box_id", "camera", "badge", "ts", "sig"))
    verify_box(b)
    claims = badge.verify(b["badge"])
    st = state.get()
    w = st.conn.execute("SELECT id, name FROM workers WHERE id=?", (claims["wid"],)).fetchone()
    if not w:
        raise HTTPException(422, "invalid badge: unknown worker")
    with st.lock:  # burn, gap check and append are one step: two boxes cannot double-punch a worker
        badge.burn(claims)
        t = clock.now()
        last_any = _last_punch_any(w["id"])
        if last_any is not None and abs(t - last_any) < MIN_GAP:
            raise HTTPException(409, "just punched")
        ts = clock.iso(t)
        last_type, _ = _last_punch_today(w["id"], ts[:10])
        kind = events.PUNCH_OUT if last_type == events.PUNCH_IN else events.PUNCH_IN
        ev = st.ledger.append(kind, {"device": b["camera"], "via": "badge"}, worker_id=w["id"], ts=ts)
    r: Receipt | None = ev.get("receipt")
    return {"worker_id": w["id"], "name": w["name"], "kind": "in" if kind == events.PUNCH_IN else "out",
            "seq": ev["seq"], "ts": ev["ts"], "receipt_text": r["text"] if r else "",
            "receipt_text_en": r["text_en"] if r else ""}
