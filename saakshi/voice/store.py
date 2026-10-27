"""Voice tables and the small queries shared by issuer, relay and themes.

The relay store has no worker id, IP, user agent or exact time (hour only), and the issuance table records
who got a token but never which blinded value, so the database itself cannot link a report to a worker.
"""
from __future__ import annotations

import hashlib
from typing import TypedDict

from .. import state
from ..state import State

SCHEMA = """
-- One RSA issuer key per (month, topic).
CREATE TABLE IF NOT EXISTS voice_keys(
  month TEXT NOT NULL, topic TEXT NOT NULL, n_hex TEXT NOT NULL, e INTEGER NOT NULL, d_hex TEXT NOT NULL,
  PRIMARY KEY(month, topic));
-- Issuance: who got a token, never which blinded value (and no time, to avoid timing links).
CREATE TABLE IF NOT EXISTS voice_issuance(
  worker_id TEXT NOT NULL, topic TEXT NOT NULL, month TEXT NOT NULL, PRIMARY KEY(worker_id, topic, month));
-- Relay store: no worker id, IP, user agent or exact time (hour only).
CREATE TABLE IF NOT EXISTS voice_reports(
  nullifier TEXT PRIMARY KEY, topic TEXT NOT NULL, month TEXT NOT NULL, text TEXT NOT NULL, lang TEXT,
  hour TEXT NOT NULL, case_key_hash TEXT NOT NULL UNIQUE, token_hex TEXT NOT NULL, sig_hex TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_voice_reports_theme ON voice_reports(month, topic);
-- "You said, we did".
CREATE TABLE IF NOT EXISTS voice_responses(
  id INTEGER PRIMARY KEY, topic TEXT NOT NULL, month TEXT NOT NULL, text TEXT NOT NULL, by TEXT NOT NULL,
  ts TEXT NOT NULL, seq INTEGER);
"""


class Response(TypedDict):
    """The latest management answer to a theme."""

    text: str
    by: str
    ts: str
    seq: int | None


def resolve(st: State | None) -> State:
    """Return st, or the process-wide state when st is None."""
    return st or state.get()


def sha256_hex(s: str) -> str:
    """Hex SHA-256 of a UTF-8 string (case keys and report texts are stored only as hashes)."""
    return hashlib.sha256(s.encode()).hexdigest()


def report_count(month: str, topic: str, st: State) -> int:
    """Number of tokens spent on (month, topic)."""
    row = st.conn.execute("SELECT COUNT(*) FROM voice_reports WHERE month=? AND topic=?", (month, topic)).fetchone()
    return int(row[0])


def enrolled(st: State) -> int:
    """Active non-supervisor workers on the site."""
    return int(st.conn.execute("SELECT COUNT(*) FROM workers WHERE active=1 AND is_supervisor=0").fetchone()[0])


def latest_response(month: str, topic: str, st: State) -> Response | None:
    """The newest management response for (month, topic), if any."""
    r = st.conn.execute("SELECT * FROM voice_responses WHERE month=? AND topic=? ORDER BY id DESC LIMIT 1",
                        (month, topic)).fetchone()
    return {"text": r["text"], "by": r["by"], "ts": r["ts"], "seq": r["seq"]} if r else None
