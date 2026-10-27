"""Worker-side Voice client: blind RSA tokens (RFC 9474 style), then an anonymous report via the relay.

The math here is the client half of the protocol and is shared with the server
(`saakshi.voice` imports `fdh` and `verify`):

    FDH(m)   = int(MGF1-SHA256(b"saakshi-voice|" + month + "|" + topic + "|" + m, len(n))) mod n
    blind    b  = FDH(m) * r^e mod n          (client, r random unit mod n)
    sign     s' = b^d mod n                   (issuer, sees only b)
    unblind  s  = s' * r^-1 mod n             (client)
    verify   s^e == FDH(m) mod n              (relay)

`web/shared/voice-client.js` implements the same FDH byte for byte.

`VoiceClient` works against a FastAPI TestClient, an httpx.Client, or a base URL string.
"""
from __future__ import annotations

import hashlib
import math
import secrets

DOMAIN = b"saakshi-voice|"


# --- primitives ------------------------------------------------------------------

def mgf1_sha256(seed: bytes, length: int) -> bytes:
    """Return length bytes of MGF1 mask output using SHA-256."""
    out, counter = b"", 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def n_len(n: int) -> int:
    """Return the byte length of modulus n."""
    return (n.bit_length() + 7) // 8


def fdh(month: str, topic: str, m: bytes, n: int) -> int:
    """Full-domain hash of the token message into Z_n, bound to (month, topic)."""
    seed = DOMAIN + month.encode() + b"|" + topic.encode() + b"|" + m
    return int.from_bytes(mgf1_sha256(seed, n_len(n)), "big") % n


def random_unit(n: int) -> int:
    """Return a random blinding factor coprime to n."""
    while True:
        r = secrets.randbelow(n - 2) + 2
        if math.gcd(r, n) == 1:
            return r


def blind(month: str, topic: str, m: bytes, n: int, e: int, r: int | None = None) -> tuple[int, int]:
    """Returns (blinded, r)."""
    r = r or random_unit(n)
    return (fdh(month, topic, m, n) * pow(r, e, n)) % n, r


def unblind(blind_sig: int, r: int, n: int) -> int:
    """Remove blinding factor r from a blind signature."""
    return (blind_sig * pow(r, -1, n)) % n


def verify(month: str, topic: str, m: bytes, s: int, n: int, e: int) -> bool:
    """Return True if s is a valid RSA signature on the (month, topic) token."""
    if not (0 < s < n):
        return False
    return pow(s, e, n) == fdh(month, topic, m, n)


def nullifier(month: str, topic: str, m: bytes) -> str:
    """Same token -> same nullifier, so a token can be spent once; reveals nothing about who holds it."""
    return hashlib.sha256(month.encode() + b"|" + topic.encode() + b"|" + m).hexdigest()


def to_hex(x: int) -> str:
    """Return x as a lowercase hex string."""
    return format(x, "x")


# --- client ------------------------------------------------------------------------

class VoiceClientError(Exception):
    """Error raised when the voice server returns a failure status."""
    def __init__(self, status_code: int, detail):
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class VoiceClient:
    """One worker's phone. Tokens live only in memory here (localStorage in the browser)."""

    def __init__(self, http):
        if isinstance(http, str):
            import httpx
            http = httpx.Client(base_url=http.rstrip("/"), timeout=30)
        self.http = http
        self.month: str | None = None
        self.keys: dict[tuple[str, str], tuple[int, int]] = {}    # (month, topic) -> (n, e)
        self.tokens: dict[tuple[str, str], tuple[bytes, int]] = {}  # (month, topic) -> (m, s)
        self.issued: set[tuple[str, str]] = set()                  # (worker_id, month) already asked
        self.last_issue_request: dict | None = None                 # what the issuer saw (for tests)

    @staticmethod
    def _json(resp):
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        if resp.status_code >= 400:
            raise VoiceClientError(resp.status_code, body.get("detail") if isinstance(body, dict) else body)
        return body

    def topics(self, month: str | None = None) -> dict:
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
            m = secrets.token_bytes(32)
            b, r = blind(month, t["id"], m, n, e)
            pending[t["id"]] = (m, r)
            blinded[t["id"]] = to_hex(b)
        req = {"worker_id": worker_id, "month": month, "blinded": blinded}
        self.last_issue_request = req
        res = self._json(self.http.post("/api/voice/issue", json=req))
        self.issued.add((worker_id, month))
        got = []
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
        return (month or self.month, topic) in self.tokens

    def token(self, topic: str, month: str | None = None) -> tuple[bytes, int]:
        return self.tokens[(month or self.month, topic)]

    def report(self, topic: str, text: str, lang: str = "en", month: str | None = None) -> dict:
        """Spend this topic's token at the relay. The request carries no worker id."""
        month = month or self.month
        if (month, topic) not in self.tokens:
            raise VoiceClientError(400, f"no unspent token for {topic} in {month}")
        m, s = self.tokens[(month, topic)]
        body = {"topic": topic, "month": month, "token": m.hex(), "signature": to_hex(s), "text": text, "lang": lang}
        resp = self.http.post("/api/relay/voice/reports", json=body)
        if resp.status_code in (200, 409):  # 409 = already spent: either way it is gone
            self.tokens.pop((month, topic), None)
        return self._json(resp)

    def case(self, case_key: str) -> dict:
        return self._json(self.http.get(f"/api/voice/cases/{case_key}"))
