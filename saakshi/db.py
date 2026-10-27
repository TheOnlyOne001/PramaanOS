"""SQLite connection and schema registry.

Core tables live here. Each module adds its own tables by calling
`register_schema(sql)` at import time; `init_schema` runs them all.
"""
import sqlite3
from pathlib import Path

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
    if sql and sql not in _module_schemas:
        _module_schemas.append(sql)


def connect(path: str) -> sqlite3.Connection:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(CORE_SCHEMA)
    for sql in _module_schemas:
        conn.executescript(sql)
