"""Demo seed: one hazard Meena raised last week, acknowledged by the line supervisor; nothing open today."""
from __future__ import annotations

from .. import config
from ..state import State
from .reports import acknowledge, report


def seed_demo(st: State) -> None:
    """Seed one acknowledged past hazard report for W001."""
    if st.conn.execute("SELECT 1 FROM events WHERE type LIKE 'safety.%' LIMIT 1").fetchone():
        return
    r = report("W001", "hazard", "Line 4", "Guard on overlock machine 12 is loose", client_id="seed-W001-1",
               ts=f"2026-10-24T10:15:00{config.TZ}")
    acknowledge(r["report_id"], by="S001", role="supervisor", note="Machine stopped; maintenance called",
                ts=f"2026-10-24T10:41:00{config.TZ}")
