"""Storage for Fair Pay: the ot_requests table and the reads every pay module shares."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .. import state
from ..db import register_schema
from ..ledger import Event

Worker = dict[str, Any]
"""A row of the workers table, as a plain dict."""

DIRECT = "direct"
"""Employer key for workers on the company's own rolls (no contractor)."""

register_schema("""
CREATE TABLE IF NOT EXISTS ot_requests(
  request_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, date TEXT NOT NULL, hours REAL NOT NULL,
  status TEXT NOT NULL, requested_by TEXT, reason TEXT, request_seq INTEGER, consent_seq INTEGER);
""")


def workers() -> dict[str, Worker]:
    """Return every payroll worker (supervisors excluded) keyed by id, in table order."""
    return {r["id"]: dict(r) for r in state.get().conn.execute("SELECT * FROM workers WHERE is_supervisor=0")}


def require_worker(wid: str, known: dict[str, Worker] | None = None) -> Worker:
    """Return worker `wid` (from `known` if given); raise HTTP 404 if there is no such payroll worker."""
    w = (workers() if known is None else known).get(wid)
    if not w:
        raise HTTPException(404, f"unknown worker {wid}")
    return w


def employer_of(w: Worker) -> str:
    """Return the contractor a worker is supplied by, or DIRECT."""
    return w["contractor"] or DIRECT


def accepted_ot_by_date(wid: str) -> dict[str, float]:
    """Return the overtime hours a worker has accepted, summed per date."""
    out: dict[str, float] = {}
    for r in state.get().conn.execute("SELECT date, hours FROM ot_requests WHERE worker_id=? AND status='accepted'", (wid,)):
        out[r["date"]] = out.get(r["date"], 0) + r["hours"]
    return out


def opening_events(wid: str, type_: str, key: str, value: str) -> list[Event]:
    """Return a worker's `type_` events whose payload[key] equals `value` (opening balances by period/quarter)."""
    return [e for e in state.get().ledger.events(worker_id=wid, type=type_) if e["payload"].get(key) == value]


def pf_deposits(period: str) -> dict[str, dict[str, Any]]:
    """Return the latest PF deposit payload for `period`, keyed by employer."""
    return {e["payload"].get("contractor") or DIRECT: e["payload"]
            for e in state.get().ledger.events(type="pf.deposit") if e["payload"].get("period") == period}
