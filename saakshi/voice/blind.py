"""RSA blind-signature primitives (RFC 9474 style): the single implementation shared by issuer, relay and client.

    FDH(m)   = int(MGF1-SHA256(b"saakshi-voice|" + month + "|" + topic + "|" + m, len(n))) mod n
    blind    b  = FDH(m) * r^e mod n          (client, r random unit mod n)
    sign     s' = b^d mod n                   (issuer, sees only b)
    unblind  s  = s' * r^-1 mod n             (client)
    verify   s^e == FDH(m) mod n              (relay)

`web/shared/voice-client.js` implements the same FDH byte for byte (tests/test_voice.py checks it with node).
Everything here is pure arithmetic on ints and bytes: no I/O, no app state.
"""
from __future__ import annotations

import hashlib
import math
import secrets

DOMAIN = b"saakshi-voice|"
"""Domain-separation prefix for the full-domain hash."""
TOKEN_BYTES = 32
"""Length of the random token message m the client blinds."""
_COUNTER_BYTES = 4  # MGF1 counter width (RFC 8017 §B.2.1)
_MIN_UNIT = 2       # smallest blinding factor worth drawing: 0 and 1 do not blind


def mgf1_sha256(seed: bytes, length: int) -> bytes:
    """Return length bytes of MGF1 mask output using SHA-256."""
    out, counter = b"", 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(_COUNTER_BYTES, "big")).digest()
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
        r = secrets.randbelow(n - _MIN_UNIT) + _MIN_UNIT
        if math.gcd(r, n) == 1:
            return r


def blind(month: str, topic: str, m: bytes, n: int, e: int, r: int | None = None) -> tuple[int, int]:
    """Blind FDH(m) with factor r (random when omitted); return (blinded, r)."""
    r = r or random_unit(n)
    return (fdh(month, topic, m, n) * pow(r, e, n)) % n, r


def sign_blinded(blinded: int, d: int, n: int) -> int:
    """Issuer side: raw RSA signature on a blinded value (the issuer never sees m)."""
    return pow(blinded, d, n)


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


__all__ = ["DOMAIN", "TOKEN_BYTES", "blind", "fdh", "mgf1_sha256", "n_len", "nullifier", "random_unit",
           "sign_blinded", "to_hex", "unblind", "verify"]
