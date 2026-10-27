"""The attack for the live tamper test: edit a punch-out straight in SQLite.

This deliberately bypasses the ledger API, the way a DB admin or a payroll
clerk with a SQL client could. Used by /api/demo/tamper and scripts/tamper.py.
"""
from __future__ import annotations

import json
import sqlite3

from .crypto import canonical, sha256_hex


def tamper_punch_out(conn: sqlite3.Connection, worker_id: str = "W001", seq: int | None = None,
                     new_ts: str | None = None, mode: str = "naive") -> dict:
    """Edit a punch-out timestamp directly in the DB (demo tamper) and return what changed."""
    if seq is None:
        row = conn.execute("SELECT * FROM events WHERE worker_id=? AND type='punch.out' ORDER BY seq DESC LIMIT 1",
                           (worker_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM events WHERE seq=?", (seq,)).fetchone()
    if not row:
        return {"ok": False, "error": "no punch-out to edit"}
    old_ts = row["ts"]
    new_ts = new_ts or (old_ts[:11] + "18:00:00" + old_ts[19:])
    conn.execute("UPDATE events SET ts=? WHERE seq=?", (new_ts, row["seq"]))
    if mode == "rehash":
        body = {"seq": row["seq"], "site": row["site"], "ts": new_ts, "type": row["type"],
                "worker_id": row["worker_id"], "payload": json.loads(row["payload"]), "prev_hash": row["prev_hash"]}
        conn.execute("UPDATE events SET hash=? WHERE seq=?", (sha256_hex(canonical(body)), row["seq"]))
    return {"ok": True, "seq": row["seq"], "worker_id": row["worker_id"], "old_ts": old_ts, "new_ts": new_ts,
            "mode": mode}
