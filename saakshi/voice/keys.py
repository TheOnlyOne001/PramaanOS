"""Issuer keys: one RSA key per (month, topic), generated lazily and persisted in voice_keys."""
from __future__ import annotations

from typing import Literal, TypedDict, overload

from ..state import State
from .blind import to_hex
from .store import resolve

KEY_BITS = 2048
PUBLIC_EXPONENT = 65537


class IssuerKey(TypedDict):
    """RSA key numbers for one (month, topic): modulus n, public exponent e, private exponent d."""

    n: int
    e: int
    d: int


class PublicKey(TypedDict):
    """The public half of an issuer key as the worker app receives it."""

    n_hex: str
    e: int


_KEYGEN_CACHE: dict[tuple[str, str], IssuerKey] = {}  # process cache: RSA keygen is slow-ish


def _generate(month: str, topic: str) -> IssuerKey:
    if (month, topic) not in _KEYGEN_CACHE:
        from cryptography.hazmat.primitives.asymmetric import rsa
        nums = rsa.generate_private_key(public_exponent=PUBLIC_EXPONENT, key_size=KEY_BITS).private_numbers()
        _KEYGEN_CACHE[(month, topic)] = {"n": nums.public_numbers.n, "e": nums.public_numbers.e, "d": nums.d}
    return _KEYGEN_CACHE[(month, topic)]


@overload
def key(month: str, topic: str, create: Literal[True] = True, st: State | None = None) -> IssuerKey: ...
@overload
def key(month: str, topic: str, create: bool, st: State | None = None) -> IssuerKey | None: ...


def key(month: str, topic: str, create: bool = True, st: State | None = None) -> IssuerKey | None:
    """{n, e, d} for (month, topic); generated lazily and persisted. With create=False, None if absent."""
    s = resolve(st)
    with s.lock:
        r = s.conn.execute("SELECT * FROM voice_keys WHERE month=? AND topic=?", (month, topic)).fetchone()
        if r:
            return {"n": int(r["n_hex"], 16), "e": r["e"], "d": int(r["d_hex"], 16)}
        if not create:
            return None
        k = _generate(month, topic)
        s.conn.execute("INSERT INTO voice_keys(month, topic, n_hex, e, d_hex) VALUES (?,?,?,?,?)",
                       (month, topic, to_hex(k["n"]), k["e"], to_hex(k["d"])))
        return k.copy()  # callers must not mutate the process cache


def public(k: IssuerKey) -> PublicKey:
    """The public part of k, hex-encoded for JSON."""
    return {"n_hex": to_hex(k["n"]), "e": k["e"]}
