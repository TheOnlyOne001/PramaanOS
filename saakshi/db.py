"""SQLite connection and schema registry.

Core tables live here. Each module adds its own tables by calling
`register_schema(sql)` at import time; `init_schema` runs them all.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS keys(
  name TEXT PRIMARY KEY, seed_hex TEXT NOT NULL, public_hex TEXT NOT NULL, created TEXT);

CREATE TABLE IF NOT EXISTS workers(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, lang TEXT NOT NULL, role TEXT NOT NULL,
  line TEXT, operation TEXT, skill_band TEXT, gender TEXT, contract_type TEXT,
  contractor TEXT, joined TEXT, active INTEGER DEFAULT 1, is_supervisor INTEGER DEFAULT 0);

-- The signed hash chain. One row per event; never updated by the app.
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY, site TEXT NOT NULL, ts TEXT NOT NULL, day TEXT NOT NULL,
  type TEXT NOT NULL, worker_id TEXT, payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL, sig TEXT NOT NULL, signer TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events_worker ON events(worker_id, type);
CREATE INDEX IF NOT EXISTS ix_events_day ON events(day);
CREATE INDEX IF NOT EXISTS ix_events_type ON events(type);

-- Daily Merkle roots, published to workers.
CREATE TABLE IF NOT EXISTS daily_roots(
  day TEXT PRIMARY KEY, root TEXT NOT NULL, n_events INTEGER NOT NULL,
  last_seq INTEGER NOT NULL, published_at TEXT NOT NULL, sig TEXT NOT NULL);

-- Simulates what sits on the worker's phone (WhatsApp/SMS receipts).
-- Written once when the event is created; the tamper demo never touches it.
CREATE TABLE IF NOT EXISTS wallet_receipts(
  id INTEGER PRIMARY KEY, worker_id TEXT NOT NULL, seq INTEGER NOT NULL, ref TEXT NOT NULL,
  ts TEXT NOT NULL, type TEXT NOT NULL, hash TEXT NOT NULL, text TEXT NOT NULL,
  text_en TEXT NOT NULL, channel TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_wallet_worker ON wallet_receipts(worker_id);

-- Every look-up of one worker's record, shown back to that worker.
CREATE TABLE IF NOT EXISTS access_log(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, viewer TEXT NOT NULL, viewer_role TEXT,
  worker_id TEXT NOT NULL, reason TEXT NOT NULL, what TEXT);
"""

_module_schemas: list[str] = []


def register_schema(sql: str) -> None:
    """Register extra module schema SQL to run in init_schema."""
    if sql and sql not in _module_schemas:
        _module_schemas.append(sql)


class Rows:
    """Rows already fetched under the connection lock; quacks like a finished sqlite3 cursor."""

    def __init__(self, rows: list[Any], lastrowid: int | None, rowcount: int) -> None:
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        """Return the first row, or None when there are no rows."""
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        """Return every row."""
        return list(self._rows)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._rows)


class SerializedConnection(sqlite3.Connection):
    """A connection that runs and fully fetches each statement while holding one re-entrant lock.

    FastAPI serves requests from a thread pool that shares this connection. SQLite forbids two
    threads stepping statements on one connection at the same time ("bad parameter or other API
    misuse"), so every statement is executed and drained inside the lock.
    """

    lock: threading.RLock

    def execute(self, sql: str, parameters: Any = (), /) -> Any:
        """Execute one statement and return its rows, fetched under the lock."""
        with self.lock:
            cur = super().execute(sql, parameters)
            return Rows(cur.fetchall() if cur.description else [], cur.lastrowid, cur.rowcount)

    def executemany(self, sql: str, parameters: Any, /) -> Any:
        """Execute a statement for each parameter set under the lock."""
        with self.lock:
            cur = super().executemany(sql, parameters)
            return Rows([], cur.lastrowid, cur.rowcount)

    def executescript(self, sql_script: str, /) -> Any:
        """Run a multi-statement script under the lock."""
        with self.lock:
            return super().executescript(sql_script)

    def close(self) -> None:
        """Close once no other thread is mid-statement."""
        with self.lock:
            super().close()


def connect(path: str, lock: threading.RLock | None = None) -> SerializedConnection:
    """Open a WAL-mode SQLite connection at path, creating its directory.

    All statements on the returned connection are serialised on `lock` (shared with the app's
    state lock so ledger appends and reads never interleave).
    """
    with contextlib.suppress(OSError):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, factory=SerializedConnection)
    conn.lock = lock or threading.RLock()
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the core and registered module schemas on conn."""
    conn.executescript(CORE_SCHEMA)
    for sql in _module_schemas:
        conn.executescript(sql)
