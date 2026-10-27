"""Issuance (identified): blind-sign at most one token per worker, topic and month.

The issuer checks the worker is real, active and not a supervisor, then signs each blinded value with that
(month, topic) key. It records only (worker_id, topic, month): never the blinded value, and no time.
"""
from __future__ import annotations

from typing import TypedDict

from fastapi import HTTPException

from ..state import State
from .blind import sign_blinded, to_hex
from .keys import key
from .store import resolve
from .topics import check_month, check_topic


class Issuance(TypedDict):
    """Blind signatures for one worker's month, keyed by topic id (hex)."""

    month: str
    signatures: dict[str, str]


def _check_worker(worker_id: str, st: State) -> None:
    w = st.conn.execute("SELECT active, is_supervisor FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not w:
        raise HTTPException(404, f"unknown worker {worker_id}")
    if not w["active"]:
        raise HTTPException(403, "worker is not active")
    if w["is_supervisor"]:
        raise HTTPException(403, "supervisors and managers do not get voice tokens")


def _parse_blinded(blinded: dict[str, str]) -> dict[str, int]:
    if not blinded:
        raise HTTPException(422, "blinded must hold at least one topic")
    parsed: dict[str, int] = {}
    for tid, hx in blinded.items():
        check_topic(tid)
        try:
            parsed[tid] = int(hx, 16)
        except (TypeError, ValueError):
            raise HTTPException(422, f"blinded[{tid}] is not hex") from None
    return parsed


def _already_issued(worker_id: str, month: str, topics: list[str], st: State) -> list[str]:
    marks = ",".join("?" * len(topics))
    rows = st.conn.execute(f"SELECT topic FROM voice_issuance WHERE worker_id=? AND month=? AND topic IN ({marks})",
                           (worker_id, month, *topics)).fetchall()
    return [r["topic"] for r in rows]


def issue(worker_id: str, month: str, blinded: dict[str, str], st: State | None = None) -> Issuance:
    """Blind-sign one voice token per topic for an active non-supervisor worker; 409 if already issued this month."""
    s = resolve(st)
    _check_worker(worker_id, s)
    check_month(month)
    parsed = _parse_blinded(blinded)
    with s.lock:
        done = _already_issued(worker_id, month, list(parsed), s)
        if done:
            raise HTTPException(409, f"tokens already issued this month for: {', '.join(sorted(done))}")
        sigs: dict[str, str] = {}
        for tid, b in parsed.items():
            k = key(month, tid, st=s)
            if not (1 < b < k["n"]):
                raise HTTPException(422, f"blinded[{tid}] out of range")
            sigs[tid] = to_hex(sign_blinded(b, k["d"], k["n"]))
        s.conn.executemany("INSERT INTO voice_issuance(worker_id, topic, month) VALUES (?,?,?)",
                           [(worker_id, tid, month) for tid in parsed])
    return {"month": month, "signatures": sigs}
