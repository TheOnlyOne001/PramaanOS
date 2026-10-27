"""One wall clock for badges, camera punches and heartbeats (tests move it by patching `time.time`)."""
from __future__ import annotations

import time
from datetime import datetime

from ..ledger import IST


def now() -> float:
    """Current Unix time in seconds."""
    return time.time()


def iso(t: float | None = None) -> str:
    """Unix time `t` (default: now) as ISO 8601 in IST with second precision, like ledger timestamps."""
    return datetime.fromtimestamp(int(now() if t is None else t), IST).isoformat()
