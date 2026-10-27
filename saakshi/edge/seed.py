"""Demo seed: a week of box-signed PPE, queue and near-miss events, plus today's run-up to the demo."""
from __future__ import annotations

from typing import Any

from .. import config
from ..state import State
from .ingest import ingest, make_event

_SEED_PAST_DAYS = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]
_SEED_PAST_PPE = {"Line 4": [0.86, 0.88, 0.84, 0.9, 0.87, 0.89], "Press zone": [0.78, 0.81, 0.76, 0.8, 0.79, 0.82]}
_SEED_PAST_WATER_QUEUE = [6, 7, 8, 6, 9, 8]
_SEED_TODAY_PPE = [(0.91, 0.84), (0.89, 0.8), (0.86, 0.77), (0.9, 0.79), (0.88, 0.75)]  # (Line 4, Press zone), 09-13h
_SEED_TODAY_FIRST_HOUR = 9


def seed_demo(st: State) -> None:
    """Seed the ledger with demo edge events."""
    out: list[dict[str, Any]] = []

    def ev(ts: str, camera: str, zone: str, kind: str, count: int | None = None, value: float | None = None) -> None:
        out.append(make_event(st.keys, camera=camera, zone=zone, kind=kind, count=count, value=value, ts=ts + config.TZ))

    for i, d in enumerate(_SEED_PAST_DAYS):
        ev(f"{d}T11:00:00", "cam-04", "Line 4", "ppe_compliance_rate", value=_SEED_PAST_PPE["Line 4"][i])
        ev(f"{d}T11:00:00", "cam-07", "Press zone", "ppe_compliance_rate", value=_SEED_PAST_PPE["Press zone"][i])
        ev(f"{d}T15:05:00", "cam-11", "Water point", "queue_length", count=_SEED_PAST_WATER_QUEUE[i])
    ev("2026-10-22T10:42:00", "cam-07", "Press zone", "restricted_zone_entry", count=1)
    ev("2026-10-23T16:18:00", "cam-04", "Line 4", "near_miss", count=1)
    ev("2026-10-24T14:00:00", "cam-07", "Press zone", "heat_wbgt", value=30.5)
    d = config.DEMO_DAY
    for h, (line4, press) in enumerate(_SEED_TODAY_PPE, start=_SEED_TODAY_FIRST_HOUR):
        ev(f"{d}T{h:02d}:00:00", "cam-04", "Line 4", "ppe_compliance_rate", value=line4)
        ev(f"{d}T{h:02d}:00:00", "cam-07", "Press zone", "ppe_compliance_rate", value=press)
    ev(f"{d}T11:20:00", "cam-04", "Line 4", "near_miss", count=1)
    ev(f"{d}T12:30:00", "cam-09", "Canteen", "queue_length", count=8)
    ev(f"{d}T13:00:00", "cam-07", "Press zone", "heat_wbgt", value=31.0)
    ev(f"{d}T14:45:00", "cam-11", "Water point", "queue_length", count=7)
    ev(f"{d}T15:00:00", "cam-11", "Water point", "queue_length", count=11)
    ev(f"{d}T15:10:00", "cam-11", "Water point", "queue_length", count=9)
    for body in sorted(out, key=lambda b: b["ts"]):
        ingest(body)
