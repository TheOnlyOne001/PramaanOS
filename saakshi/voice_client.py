"""Worker-side Voice client: blind RSA tokens (RFC 9474 style), then an anonymous report via the relay.

The blind-signature maths lives once, in `saakshi.voice.blind`, and is re-exported here so client code
and tests can keep importing `blind`, `unblind`, `verify`, `fdh` and friends from this module.
`web/shared/voice-client.js` implements the same FDH byte for byte.

`VoiceClient` works against a FastAPI TestClient, an httpx.Client, or a base URL string.
"""
from __future__ import annotations

import secrets
from typing import Any, Protocol

from .voice.blind import (
    DOMAIN,
    TOKEN_BYTES,
    blind,
    fdh,
    mgf1_sha256,
    n_len,
    nullifier,
    random_unit,
    to_hex,
    unblind,
    verify,
)

HTTP_CLIENT_TIMEOUT_S = 30
"""Timeout for the httpx client built when VoiceClient is given a base URL."""
_HTTP_ERROR = 400  # first HTTP status code that is an error


class _Response(Protocol):
    """The slice of an httpx / TestClient response the client reads."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class _Http(Protocol):
    """The slice of an httpx.Client / TestClient the client calls."""

    def get(self, url: str, *, params: dict[str, str] | None = ...) -> _Response: ...

    def post(self, url: str, *, json: Any = ...) -> _Response: ...


# --- client ------------------------------------------------------------------------

def _connect(base_url: str) -> _Http:
    """An httpx client for a running server at base_url."""
    import httpx
    return httpx.Client(base_url=base_url.rstrip("/"), timeout=HTTP_CLIENT_TIMEOUT_S)


class VoiceClientError(Exception):
    """Error raised when the voice server returns a failure status."""

    def __init__(self, status_code: int, detail: Any):
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class VoiceClient:
    """One worker's phone. Tokens live only in memory here (localStorage in the browser)."""

    def __init__(self, http: _Http | str):
        self.http: _Http = _connect(http) if isinstance(http, str) else http
        self.month: str | None = None
        self.keys: dict[tuple[str, str], tuple[int, int]] = {}      # (month, topic) -> (n, e)
        self.tokens: dict[tuple[str, str], tuple[bytes, int]] = {}  # (month, topic) -> (m, s)
        self.issued: set[tuple[str, str]] = set()                   # (worker_id, month) already asked
        self.last_issue_request: dict[str, Any] | None = None      # what the issuer saw (for tests)

    @staticmethod
    def _json(resp: _Response) -> Any:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        if resp.status_code >= _HTTP_ERROR:
            raise VoiceClientError(resp.status_code, body.get("detail") if isinstance(body, dict) else body)
        return body

    def topics(self, month: str | None = None) -> dict[str, Any]:
        """Fetch the topic list and the (month, topic) public keys."""
        params = {"month": month} if month else None
        return self._json(self.http.get("/api/voice/topics", params=params))

    def get_tokens(self, worker_id: str, month: str | None = None, topics: list[str] | None = None) -> list[str]:
        """Blind one fresh message per topic, ask the issuer to sign all at once, unblind and verify.

        Asking for every topic at once means issuance says nothing about which issue a worker cares about.
        Returns the topic ids for which a valid token is now held.
        """
        info = self.topics(month)
        month = info["month"]
        self.month = month
        pending: dict[str, tuple[bytes, int]] = {}
        blinded: dict[str, str] = {}
        for t in info["topics"]:
            if topics and t["id"] not in topics:
                continue
            if not t.get("key"):
                continue
            n, e = int(t["key"]["n_hex"], 16), int(t["key"]["e"])
            self.keys[(month, t["id"])] = (n, e)
            m = secrets.token_bytes(TOKEN_BYTES)
            b, r = blind(month, t["id"], m, n, e)
            pending[t["id"]] = (m, r)
            blinded[t["id"]] = to_hex(b)
        req: dict[str, Any] = {"worker_id": worker_id, "month": month, "blinded": blinded}
        self.last_issue_request = req
        res = self._json(self.http.post("/api/voice/issue", json=req))
        self.issued.add((worker_id, month))
        got: list[str] = []
        for tid, sig_hex in res["signatures"].items():
            m, r = pending[tid]
            n, e = self.keys[(month, tid)]
            s = unblind(int(sig_hex, 16), r, n)
            if not verify(month, tid, m, s, n, e):
                raise VoiceClientError(500, f"issuer returned a bad signature for {tid}")
            self.tokens[(month, tid)] = (m, s)
            got.append(tid)
        return got

    def has_token(self, topic: str, month: str | None = None) -> bool:
        """True if an unspent token for topic is held."""
        return (month or self.month, topic) in self.tokens

    def token(self, topic: str, month: str | None = None) -> tuple[bytes, int]:
        """The held (m, s) token for topic; KeyError if none."""
        month = month or self.month
        if month is None:
            raise KeyError((month, topic))
        return self.tokens[(month, topic)]

    def report(self, topic: str, text: str, lang: str = "en", month: str | None = None) -> dict[str, Any]:
        """Spend this topic's token at the relay. The request carries no worker id."""
        month = month or self.month
        if month is None or (month, topic) not in self.tokens:
            raise VoiceClientError(400, f"no unspent token for {topic} in {month}")
        m, s = self.tokens[(month, topic)]
        body = {"topic": topic, "month": month, "token": m.hex(), "signature": to_hex(s), "text": text, "lang": lang}
        resp = self.http.post("/api/relay/voice/reports", json=body)
        if resp.status_code in (200, 409):  # 409 = already spent: either way it is gone
            self.tokens.pop((month, topic), None)
        return self._json(resp)

    def case(self, case_key: str) -> dict[str, Any]:
        """Follow a report by its case key."""
        return self._json(self.http.get(f"/api/voice/cases/{case_key}"))


__all__ = [
    "DOMAIN",
    "TOKEN_BYTES",
    "VoiceClient",
    "VoiceClientError",
    "blind",
    "fdh",
    "mgf1_sha256",
    "n_len",
    "nullifier",
    "random_unit",
    "to_hex",
    "unblind",
    "verify",
]
