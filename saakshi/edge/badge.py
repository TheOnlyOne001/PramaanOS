"""Rotating worker badges: a short, site-signed token shown as a QR on the worker's phone.

Identity at the camera comes only from this badge, never from a face. A token is
`"SKB1." + b64url(canonical({wid, exp, n})) + "." + b64url(Ed25519 "site" signature over those bytes)`,
valid for `TTL` seconds, single use (its random nonce `n` is burned on first punch).
"""
from __future__ import annotations

import base64
import json
import secrets
import sqlite3
from typing import Any, TypedDict

from fastapi import HTTPException

from .. import db, state
from ..crypto import canonical
from . import clock

PREFIX = "SKB1"
TTL = 30          # seconds a badge is valid
SKEW = 5          # seconds of clock skew allowed between the box, the phone and the server
SIGNER = "site"

SCHEMA = """
CREATE TABLE IF NOT EXISTS edge_badge_nonces(
  nonce TEXT PRIMARY KEY, worker_id TEXT NOT NULL, exp INTEGER NOT NULL, used_at TEXT NOT NULL);
"""
db.register_schema(SCHEMA)


class Badge(TypedDict):
    """A freshly issued badge for the worker's phone to show as a QR code."""
    token: str
    expires_at: str
    ttl: int
    worker_id: str
    name: str


class BadgeClaims(TypedDict):
    """The verified contents of a badge token."""
    wid: str
    exp: int
    n: str


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _worker(wid: str) -> dict[str, Any]:
    r = state.get().conn.execute("SELECT id, name, lang FROM workers WHERE id=?", (wid,)).fetchone()
    if not r:
        raise HTTPException(404, f"unknown worker {wid}")
    return dict(r)


def issue(wid: str) -> Badge:
    """Issue a 30-second badge for worker `wid` (404 if unknown)."""
    w = _worker(wid)
    exp = int(clock.now()) + TTL
    body = canonical({"wid": wid, "exp": exp, "n": secrets.token_hex(8)})
    sig = state.get().keys.get(SIGNER).sign(body).signature
    return {"token": f"{PREFIX}.{_b64(body)}.{_b64(sig)}", "expires_at": clock.iso(exp), "ttl": TTL,
            "worker_id": wid, "name": w["name"]}


def verify(token: object) -> BadgeClaims:
    """Return the claims of a genuine, unexpired badge. Raises 422 (forged or malformed) or 409 (expired)."""
    try:
        if not isinstance(token, str) or len(token) > 400:
            raise ValueError("not a badge")
        prefix, body_b64, sig_b64 = token.split(".")
        if prefix != PREFIX:
            raise ValueError("wrong prefix")
        body, sig = _unb64(body_b64), _unb64(sig_b64)
        state.get().keys.get(SIGNER).verify_key.verify(body, sig)
        claims = json.loads(body)
        if not isinstance(claims, dict) or set(claims) != {"wid", "exp", "n"} or canonical(claims) != body:
            raise ValueError("bad claims")
        wid, exp, n = claims["wid"], claims["exp"], claims["n"]
        if not (isinstance(wid, str) and isinstance(n, str) and isinstance(exp, int) and not isinstance(exp, bool)):
            raise ValueError("bad claim types")
    except Exception:  # any forged, tampered or malformed badge is simply "not a badge"
        raise HTTPException(422, "invalid badge: signature does not verify") from None
    t = clock.now()
    if exp + SKEW < t:
        raise HTTPException(409, "badge expired")
    if exp > t + TTL + SKEW:
        raise HTTPException(422, "invalid badge: lifetime is too long")
    return {"wid": wid, "exp": exp, "n": n}


def burn(claims: BadgeClaims) -> None:
    """Mark a badge's nonce used; raise 409 if it already was. Forgets nonces that can no longer verify."""
    st = state.get()
    with st.lock:
        st.conn.execute("DELETE FROM edge_badge_nonces WHERE exp < ?", (int(clock.now()) - TTL - 2 * SKEW,))
        try:
            st.conn.execute("INSERT INTO edge_badge_nonces(nonce, worker_id, exp, used_at) VALUES (?,?,?,?)",
                            (claims["n"], claims["wid"], claims["exp"], clock.iso()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "badge already used") from None
