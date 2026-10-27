"""Ingest: build and sign events as the box would, then validate, verify and append them to the ledger.

The box signs each event with its own Ed25519 key over canonical(body without sig).
Anything failing the privacy guard or the event shape is refused with 422; a bad or
unknown box signature with 401.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from .. import events, state
from ..crypto import KeyStore, canonical, verify_sig
from ..ledger import Event, now_ts
from .cameras import BOX_KEYS, DEMO_BOX, KINDS
from .privacy import PrivacyViolation, privacy_check

_ALLOWED_FIELDS = {"box_id", "camera", "zone", "kind", "count", "value", "ts", "sig"}
_REQUIRED_TEXT = ("box_id", "camera", "zone", "kind", "ts", "sig")
_NUMERIC = ("count", "value")


def make_event(keys: KeyStore, box_id: str = DEMO_BOX, **fields: Any) -> dict[str, Any]:
    """Build and sign an event as the box would. `keys` is a saakshi.crypto.KeyStore.

    On a real box the private key is generated on the device and never leaves it;
    the demo keeps it in the site DB so the simulator can sign.
    """
    body = {"box_id": box_id, "ts": fields.pop("ts", None) or now_ts(), **fields}
    body = {k: v for k, v in body.items() if v is not None}
    body["sig"] = keys.sign(BOX_KEYS.get(box_id, box_id), canonical(body))
    return body


def is_number(v: object) -> bool:
    """Return True for an int or float (JSON booleans are not numbers here)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate(body: dict[str, Any]) -> None:
    """Raise 422 unless the body passes the privacy guard and has the event shape."""
    try:
        privacy_check(body)
    except PrivacyViolation as e:
        raise HTTPException(422, f"privacy guard: {e}") from e
    extra = set(body) - _ALLOWED_FIELDS
    if extra:
        raise HTTPException(422, f"unknown fields: {sorted(extra)}")
    for f in _REQUIRED_TEXT:
        if not isinstance(body.get(f), str) or not body.get(f):
            raise HTTPException(422, f"'{f}' is required")
    if body["kind"] not in KINDS:
        raise HTTPException(422, f"unknown kind '{body['kind']}'; allowed: {sorted(KINDS)}")
    for f in _NUMERIC:
        if body.get(f) is not None and not is_number(body[f]):
            raise HTTPException(422, f"'{f}' must be a number")
    try:
        datetime.fromisoformat(body["ts"])
    except ValueError:
        raise HTTPException(422, "'ts' must be ISO 8601") from None


def verify_box(body: dict[str, Any]) -> None:
    """Raise 401 unless `box_id` is a registered box and `sig` is its signature over canonical(body without sig).

    Shared by every box-signed route (events, camera punches, heartbeats).
    """
    box_id, sig = body.get("box_id"), body.get("sig")
    if not isinstance(box_id, str) or box_id not in BOX_KEYS:
        raise HTTPException(401, f"unknown edge box '{box_id}'")
    unsigned = {k: v for k, v in body.items() if k != "sig"}
    if not isinstance(sig, str) or not verify_sig(state.get().keys.public_hex(BOX_KEYS[box_id]), canonical(unsigned), sig):
        raise HTTPException(401, "signature does not verify against the box key")


def ingest(body: dict[str, Any]) -> Event:
    """Validate, verify and record one event. Raises HTTPException (422 privacy/shape, 401 signature)."""
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    _validate(body)
    verify_box(body)
    st = state.get()
    payload = {"box_id": body["box_id"], "camera": body["camera"], "zone": body["zone"], "kind": body["kind"],
               "count": body.get("count"), "value": body.get("value"), "box_ts": body["ts"], "box_sig": body["sig"]}
    return st.ledger.append(events.EDGE_EVENT, payload, worker_id=None, ts=body["ts"], signer="site")
