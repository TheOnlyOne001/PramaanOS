"""Process-wide state: one SQLite connection, key store and ledger.

Use `state.get()` anywhere. Tests call `state.reset(path)` for a fresh DB.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading

from . import config, db
from .crypto import KeyStore
from .ledger import Ledger


class State:
    """Shared app state: DB connection, lock, keys and ledger."""
    def __init__(self, path: str) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.conn = db.connect(path, self.lock)
        db.init_schema(self.conn)
        self.keys = KeyStore(self.conn, self.lock)
        self.ledger = Ledger(self.conn, self.keys, self.lock)

    def close(self) -> None:
        """Close the database connection, ignoring an already-closed one."""
        with contextlib.suppress(sqlite3.Error):
            self.conn.close()


_state: State | None = None


def get() -> State:
    """Return the process-wide State, creating it on first use."""
    global _state
    if _state is None:
        _state = State(config.DB_PATH)
    return _state


def reset(path: str | None = None, wipe: bool = False) -> State:
    """Reopen state on `path`. With wipe=True, delete the DB file first."""
    global _state
    if _state is not None:
        _state.close()
    path = path or config.DB_PATH
    if wipe:
        from pathlib import Path
        for suffix in ("", "-wal", "-shm"):
            p = Path(path + suffix)
            if p.exists():
                p.unlink()
    _state = State(path)
    return _state
