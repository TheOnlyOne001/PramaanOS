"""Signed calls to the Saakshi server: edge events, badge punches, heartbeats and the zone list.

Every POST body carries `box_id` and `ts` (ISO 8601, +05:30) and a `sig`: the box's Ed25519
signature (hex) over `saakshi.crypto.canonical(body without sig)`. Bodies carry zone / kind /
count / time (and, for a punch, the opaque badge string) only: never images, faces or track ids.

Demo shortcut: the box key "edge-box-1" is read from the Saakshi SQLite DB on the same laptop.
A real box generates its key in a TPM / secure element and only the public key is enrolled.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from saakshi.crypto import KeyStore, canonical

from . import BOX_ID, CAMERA_ID
from .zones import Zone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ts() -> str:
    """Current time in IST, ISO 8601 with offset, second precision (same format as the ledger)."""
    return datetime.now(IST).replace(microsecond=0).isoformat()


class Signer(Protocol):
    """Signs canonical bytes with the box key."""

    box_id: str

    def sign_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return body with box_id, ts and sig added."""
        ...


class BoxSigner:
    """Ed25519 signer backed by a saakshi.crypto.KeyStore entry (default key name "edge-box-1")."""

    def __init__(self, keys: KeyStore, box_id: str = BOX_ID, key_name: str | None = None) -> None:
        """Use `keys[key_name or box_id]` to sign as `box_id`."""
        self.keys = keys
        self.box_id = box_id
        self.key_name = key_name or box_id

    @classmethod
    def from_db(cls, db_path: str, box_id: str = BOX_ID) -> BoxSigner:
        """Open the Saakshi DB read for the box key (start the Saakshi server once so it seeds the key)."""
        from saakshi import db

        if not Path(db_path).exists():
            raise SystemExit(f"no Saakshi database at {db_path}: start the server once (it seeds keys) or pass --db")
        conn = db.connect(db_path)
        return cls(KeyStore(conn, threading.RLock()), box_id)

    def public_hex(self) -> str:
        """The box's public key (hex), as enrolled on the server."""
        return self.keys.public_hex(self.key_name)

    def sign_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Add box_id and ts (unless given), drop None values, then sign canonical(body) into body["sig"]."""
        out = {"box_id": self.box_id, "ts": body.get("ts") or now_ts(), **{k: v for k, v in body.items() if k != "sig"}}
        out = {k: v for k, v in out.items() if v is not None}
        out["sig"] = self.keys.sign(self.key_name, canonical(out))
        return out


@dataclass(slots=True)
class ApiResult:
    """HTTP status and decoded JSON body (status 0 = could not reach the server)."""

    status: int
    body: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True for a 2xx response."""
        return 200 <= self.status < 300

    @property
    def detail(self) -> str:
        """Error detail for display."""
        return str(self.body.get("detail", "")) or f"HTTP {self.status}"


class SaakshiClient(Protocol):
    """What the pipeline needs from the server (a FakeClient implements this in tests)."""

    def post_event(self, zone: str, count: int, kind: str = "restricted_zone_entry") -> ApiResult:
        """POST /api/edge/events."""
        ...

    def punch(self, badge: str) -> ApiResult:
        """POST /api/edge/punch."""
        ...

    def heartbeat(self, stats: dict[str, Any]) -> ApiResult:
        """POST /api/edge/heartbeat."""
        ...

    def zones(self) -> list[Zone] | None:
        """GET /api/edge/zones (None if unreachable, so the last known zones are kept)."""
        ...


class HttpSaakshiClient:
    """httpx client for the Saakshi contract; never raises on network errors (returns status 0)."""

    def __init__(self, base: str, signer: Signer, camera: str = CAMERA_ID, timeout: float = 4.0) -> None:
        """Create a client for `base` (e.g. http://127.0.0.1:8000)."""
        self.base = base.rstrip("/")
        self.signer = signer
        self.camera = camera
        self._http = httpx.Client(base_url=self.base, timeout=timeout)

    def _post(self, path: str, body: dict[str, Any]) -> ApiResult:
        signed = self.signer.sign_body(body)
        try:
            r = self._http.post(path, json=signed)
        except httpx.HTTPError as e:
            return ApiResult(0, {"detail": f"server unreachable: {type(e).__name__}"})
        try:
            data = r.json()
        except ValueError:
            data = {"detail": r.text[:200]}
        return ApiResult(r.status_code, data if isinstance(data, dict) else {"data": data})

    def post_event(self, zone: str, count: int, kind: str = "restricted_zone_entry") -> ApiResult:
        """Send a signed zone event: camera, zone, kind, count, ts only."""
        return self._post("/api/edge/events", {"camera": self.camera, "zone": zone, "kind": kind, "count": int(count)})

    def punch(self, badge: str) -> ApiResult:
        """Forward an opaque SKB1. badge string; the server resolves and checks it."""
        return self._post("/api/edge/punch", {"camera": self.camera, "badge": badge})

    def heartbeat(self, stats: dict[str, Any]) -> ApiResult:
        """Send box health (fps, backends, counters, preview URL)."""
        return self._post("/api/edge/heartbeat", {"camera": self.camera, **stats})

    def zones(self) -> list[Zone] | None:
        """Fetch this camera's zones (public read)."""
        try:
            r = self._http.get("/api/edge/zones", params={"camera": self.camera})
            if r.status_code != 200:
                return None
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return None
        items = data.get("zones", []) if isinstance(data, dict) else []
        return [Zone.from_api(z) for z in items if isinstance(z, dict)]

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._http.close()
