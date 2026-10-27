#!/usr/bin/env python3
"""Simulate the on-site edge box (e.g. a Jetson running detection on the camera feeds).

The box sends only counts and alerts, each signed with its own Ed25519 key.

    python3 scripts/edge_sim.py --base http://localhost:8000 --scenario press_zone
    python3 scripts/edge_sim.py --scenario all

Scenarios: press_zone, ppe, queue, fire, all.

Demo shortcut: the simulator reads the box's private key ("edge-box-1") from the
site's SQLite DB (--db, default saakshi.config.DB_PATH) via saakshi.crypto.KeyStore.
On a real box the key is generated on the device and never leaves it; the server
only ever holds the public key.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saakshi import config, db  # noqa: E402
from saakshi.crypto import KeyStore  # noqa: E402
from saakshi.edge import make_event  # noqa: E402,F401  (re-exported for demo scripts)
from saakshi.ledger import now_ts  # noqa: E402


def scenario_events(name: str) -> list[dict]:
    """Unsigned event fields for a scenario (ts defaults to now)."""
    s = {
        "press_zone": [dict(camera="cam-07", zone="Press zone", kind="restricted_zone_entry", count=1)],
        "ppe": [dict(camera="cam-04", zone="Line 4", kind="ppe_compliance_rate", value=0.87),
                dict(camera="cam-07", zone="Press zone", kind="ppe_compliance_rate", value=0.71),
                dict(camera="cam-07", zone="Press zone", kind="ppe_noncompliance", count=2)],
        "queue": [dict(camera="cam-11", zone="Water point", kind="queue_length", count=12)],
        "fire": [dict(camera="cam-12", zone="Store", kind="fire_smoke", count=1)],
    }
    if name == "all":
        return [e for k in ("press_zone", "ppe", "queue", "fire") for e in s[k]]
    if name not in s:
        raise SystemExit(f"unknown scenario {name!r}; choose from {sorted(s) + ['all']}")
    return s[name]


def open_keys(db_path: str) -> KeyStore:
    if not Path(db_path).exists():
        raise SystemExit(f"no database at {db_path}; start the server once (it seeds) or pass --db")
    conn = db.connect(db_path)
    return KeyStore(conn, threading.RLock())


def post(base: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(base.rstrip("/") + "/api/edge/events", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--scenario", default="press_zone")
    ap.add_argument("--box", default="edge-box-1")
    ap.add_argument("--ts", default=None, help="override event time (ISO 8601 with +05:30)")
    a = ap.parse_args(argv)
    keys = open_keys(a.db)
    rc = 0
    for fields in scenario_events(a.scenario):
        body = make_event(keys, box_id=a.box, ts=a.ts or now_ts(), **fields)
        code, res = post(a.base, body)
        if code == 200:
            print(f"✓ {fields['kind']:<22} {fields['zone']:<12} → ledger seq {res['seq']} ref {res['ref']}")
        else:
            rc = 1
            print(f"✕ {fields['kind']}: HTTP {code} {res.get('detail')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
