"""Live tamper test: edit Meena's latest punch-out straight in SQLite, bypassing the app.

    python3 scripts/tamper.py                 # set punch-out to 18:00
    python3 scripts/tamper.py --mode rehash   # also recompute the row's hash
    python3 scripts/tamper.py --db data/saakshi.db --worker W001 --ts 2026-10-27T18:00:00+05:30
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saakshi import config
from saakshi.tamper import tamper_punch_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--worker", default="W001")
    ap.add_argument("--ts", default=None)
    ap.add_argument("--mode", default="naive", choices=["naive", "rehash"])
    a = ap.parse_args()
    conn = sqlite3.connect(a.db, isolation_level=None)
    conn.row_factory = sqlite3.Row
    print(tamper_punch_out(conn, worker_id=a.worker, new_ts=a.ts, mode=a.mode))


if __name__ == "__main__":
    main()
