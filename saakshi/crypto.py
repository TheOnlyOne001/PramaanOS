"""Hashing, canonical JSON, Merkle trees and Ed25519 keys."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime

from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


def canonical(obj) -> bytes:
    """Deterministic JSON bytes: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    """Return the hex SHA-256 digest of data."""
    return hashlib.sha256(data).hexdigest()


# --- Merkle tree (RFC 6962 style domain separation) -------------------------

def _leaf(h: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(h)).digest()


def _node(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + a + b).digest()


def merkle_root(hashes: list[str]) -> str:
    """Return the hex Merkle root of the given leaf hashes."""
    if not hashes:
        return sha256_hex(b"")
    level = [_leaf(h) for h in hashes]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(hashes: list[str], index: int) -> list[dict]:
    """Inclusion proof for hashes[index]: list of {sibling, side}."""
    level = [_leaf(h) for h in hashes]
    proof = []
    i = index
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sib = i ^ 1
        proof.append({"sibling": level[sib].hex(), "side": "L" if sib < i else "R"})
        level = [_node(level[j], level[j + 1]) for j in range(0, len(level), 2)]
        i //= 2
    return proof


def verify_merkle_proof(leaf_hash: str, proof: list[dict], root: str) -> bool:
    """Return True if the proof links leaf_hash to root."""
    cur = _leaf(leaf_hash)
    for step in proof:
        sib = bytes.fromhex(step["sibling"])
        cur = _node(sib, cur) if step["side"] == "L" else _node(cur, sib)
    return cur.hex() == root


# --- Ed25519 ----------------------------------------------------------------

def verify_sig(public_hex: str, message: bytes, sig_hex: str) -> bool:
    """Return True if sig_hex is a valid Ed25519 signature of message."""
    try:
        VerifyKey(public_hex, encoder=HexEncoder).verify(message, bytes.fromhex(sig_hex))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


class KeyStore:
    """Named Ed25519 keys, persisted in the `keys` table.

    Names in use: "site" (ledger signer), "site-issuer" (credentials),
    "edge-box-1" (camera box), "worker:<id>" (simulates the worker's phone key).
    Demo only: production keys live in an HSM / on the device.
    """

    def __init__(self, conn, lock: threading.RLock):
        self.conn = conn
        self.lock = lock
        self._cache: dict[str, SigningKey] = {}

    def get(self, name: str) -> SigningKey:
        if name in self._cache:
            return self._cache[name]
        with self.lock:
            row = self.conn.execute("SELECT seed_hex FROM keys WHERE name=?", (name,)).fetchone()
            if row:
                sk = SigningKey(row[0], encoder=HexEncoder)
            else:
                sk = SigningKey.generate()
                self.conn.execute(
                    "INSERT INTO keys(name, seed_hex, public_hex, created) VALUES (?,?,?,?)",
                    (name, sk.encode(HexEncoder).decode(), sk.verify_key.encode(HexEncoder).decode(),
                     datetime.now(UTC).isoformat()),
                )
        self._cache[name] = sk
        return sk

    def public_hex(self, name: str) -> str:
        return self.get(name).verify_key.encode(HexEncoder).decode()

    def sign(self, name: str, message: bytes) -> str:
        return self.get(name).sign(message).signature.hex()

    def verify(self, name: str, message: bytes, sig_hex: str) -> bool:
        return verify_sig(self.public_hex(name), message, sig_hex)
