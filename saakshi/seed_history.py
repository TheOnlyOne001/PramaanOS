"""Demo history: each module seeds its own signed events, then daily roots are published."""
from __future__ import annotations

import logging

from .state import State

log = logging.getLogger("saakshi.seed")

PAST_DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]


def seed_history(st: State) -> None:
    from . import edge, passport, pay, voice
    for mod in (pay, passport, edge, voice):
        fn = getattr(mod, "seed_demo", None)
        if fn is None:
            continue
        try:
            fn(st)
        except Exception:  # keep the app usable even if one module's seed breaks
            log.exception("seed_demo failed for %s", mod.__name__)
    # Publish a root for every past day that has events ("midnight, daily root").
    days = [r[0] for r in st.conn.execute("SELECT DISTINCT day FROM events WHERE day < '2026-10-27' ORDER BY day")]
    for d in days:
        st.ledger.publish_root(d)
