"""Credential storage: the `passport_credentials` table and the lookups built on it.

The table is an index over signed ledger events (`credential.issued` /
`credential.revoked`); the VC JSON stored here is exactly what was signed.
"""
from __future__ import annotations

import sqlite3
from typing import Any, TypedDict

from fastapi import HTTPException

from .. import config, db, state
from .rules import level_rank

db.register_schema("""
CREATE TABLE IF NOT EXISTS passport_credentials(
  id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, kind TEXT NOT NULL, skill TEXT NOT NULL, level TEXT,
  vc TEXT NOT NULL, vc_hash TEXT NOT NULL, status_index INTEGER NOT NULL UNIQUE,
  issued_at TEXT NOT NULL, valid_until TEXT, seq INTEGER,
  revoked INTEGER NOT NULL DEFAULT 0, revoked_reason TEXT, revoked_at TEXT);
CREATE INDEX IF NOT EXISTS ix_passport_worker ON passport_credentials(worker_id);
""")


class RowStatus(TypedDict):
    """Revocation and expiry status of one stored credential."""

    revoked: bool
    revoked_reason: str | None
    expired: bool
    valid_until: str | None
    status_index: int
    seq: int | None


def worker_row(wid: str) -> dict[str, Any]:
    """Return the worker's row, or raise 404 if the worker is unknown."""
    r = state.get().conn.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone()
    if not r:
        raise HTTPException(404, f"unknown worker {wid}")
    return dict(r)


def worker_names() -> dict[str, str]:
    """Return worker id -> name for every worker."""
    return {r["id"]: r["name"] for r in state.get().conn.execute("SELECT id, name FROM workers")}


def credential_rows(wid: str | None = None) -> list[sqlite3.Row]:
    """Return stored credentials (optionally one worker's) in status-list order."""
    q, args = "SELECT * FROM passport_credentials", []
    if wid:
        q += " WHERE worker_id=?"
        args.append(wid)
    return state.get().conn.execute(q + " ORDER BY status_index", args).fetchall()


def get_credential(cid: str) -> sqlite3.Row | None:
    """Return the credential row by id or id suffix, or None if not found."""
    conn = state.get().conn
    r = conn.execute("SELECT * FROM passport_credentials WHERE id=?", (cid,)).fetchone()
    if not r:
        r = conn.execute("SELECT * FROM passport_credentials WHERE id LIKE ?", ("%" + cid,)).fetchone()
    return r


def next_status_index(conn: sqlite3.Connection) -> int:
    """Return the next free bit in the revocation status list."""
    r = conn.execute("SELECT MAX(status_index) FROM passport_credentials").fetchone()[0]
    return 0 if r is None else r + 1


def today() -> str:
    """Return the day expiry is judged against (the demo's "today")."""
    return config.DEMO_DAY


def row_status(r: sqlite3.Row) -> RowStatus:
    """Return whether a stored credential is revoked or past its validUntil day."""
    expired = bool(r["valid_until"] and r["valid_until"] < today())
    return {"revoked": bool(r["revoked"]), "revoked_reason": r["revoked_reason"], "expired": expired,
            "valid_until": r["valid_until"], "status_index": r["status_index"], "seq": r["seq"]}


def holds(wid: str, skill: str, level: str) -> bool:
    """Return True if the worker holds an unrevoked credential for `skill` at `level` or above."""
    rows = state.get().conn.execute(
        "SELECT level FROM passport_credentials WHERE worker_id=? AND skill=? AND revoked=0", (wid, skill)).fetchall()
    return any(r["level"] and level_rank(r["level"]) >= level_rank(level) for r in rows)


def revoked_vcs(wid: str, skill: str) -> list[str]:
    """Return the stored VC JSON of the worker's revoked credentials for `skill`."""
    rows = state.get().conn.execute(
        "SELECT vc FROM passport_credentials WHERE worker_id=? AND skill=? AND revoked=1", (wid, skill))
    return [r["vc"] for r in rows]
