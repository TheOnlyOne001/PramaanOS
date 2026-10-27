"""Safety reports: a worker's hazard or stop-work call with real delivery states.

received → acknowledged → resolved, each a signed ledger event (`safety.*`) with a receipt in the
reporting worker's language. A stop-work call must be acknowledged within 15 minutes, a hazard within
4 hours; past that the report is `overdue` and tops the employer's action queue.

Modules: `receipts` (i18n templates, registered on import), `reports` (replay and transitions),
`seed` (demo data), `api` (HTTP routes).
"""
from __future__ import annotations

from . import receipts as receipts
from .api import router
from .reports import ACK_WINDOW, KINDS, Report, TimelineEntry, acknowledge, get_report, list_reports, report, resolve
from .seed import seed_demo

__all__ = [
    "ACK_WINDOW", "KINDS", "Report", "TimelineEntry", "acknowledge", "get_report", "list_reports", "report",
    "resolve", "router", "seed_demo",
]
