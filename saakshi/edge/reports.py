"""Console views over `edge.event` ledger entries: recent events and the daily zone summary."""
from __future__ import annotations

from typing import Any, TypedDict

from .. import config, events, state
from ..ledger import Event
from .cameras import ALERT_KINDS, ZONES

RATE_DIGITS = 3


class EdgeRow(TypedDict):
    """An `edge.event` ledger entry flattened for the console."""

    seq: int
    ts: str
    box_id: str | None
    camera: str | None
    zone: str | None
    kind: str | None
    count: int | float | None
    value: int | float | None
    ref: str


def _row(ev: Event) -> EdgeRow:
    p = ev["payload"]
    return {"seq": ev["seq"], "ts": ev["ts"], "box_id": p.get("box_id"), "camera": p.get("camera"),
            "zone": p.get("zone"), "kind": p.get("kind"), "count": p.get("count"), "value": p.get("value"),
            "ref": ev["ref"]}


def recent(limit: int = 20, kind: str | None = None) -> list[EdgeRow]:
    """Return the most recent edge events, optionally filtered by kind."""
    evs = state.get().ledger.events(type=events.EDGE_EVENT, desc=True)
    rows = [_row(e) for e in evs if kind is None or e["payload"].get("kind") == kind]
    return rows[:limit]


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), RATE_DIGITS)


def _ppe_by_zone(rows: list[EdgeRow]) -> list[dict[str, Any]]:
    """Average PPE compliance per zone, overall and by hour of day."""
    ppe: dict[str, dict[str, list[float]]] = {}
    for e in rows:
        value = e["value"]
        if e["kind"] == "ppe_compliance_rate" and e["zone"] is not None and isinstance(value, (int, float)):
            ppe.setdefault(e["zone"], {}).setdefault(e["ts"][11:13], []).append(float(value))
    return [{"zone": zone, "rate": _mean([v for vs in hours.values() for v in vs]),
             "by_hour": [{"hour": h, "rate": _mean(v), "n": len(v)} for h, v in sorted(hours.items())]}
            for zone, hours in ppe.items()]


def summary(day: str | None = None) -> dict[str, Any]:
    """Summarise one day's edge events by zone, PPE compliance, alerts and peak queue."""
    st = state.get()
    if day is None:
        last = st.ledger.events(type=events.EDGE_EVENT, desc=True, limit=1)
        day = last[0]["day"] if last else config.DEMO_DAY
    rows = [_row(e) for e in st.ledger.events(type=events.EDGE_EVENT, day=day)]
    zones: dict[str | None, dict[str | None, int]] = {z: {} for z in ZONES}
    for e in rows:
        by_kind = zones.setdefault(e["zone"], {})
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    queues = [e for e in rows if e["kind"] == "queue_length"]
    return {
        "day": day,
        "zones": [{"zone": z, "events": k} for z, k in zones.items()],
        "ppe_compliance_by_zone": _ppe_by_zone(rows),
        "alerts": [e for e in rows if e["kind"] in ALERT_KINDS],
        "peak_queue": max(queues, key=lambda e: e["count"] or 0) if queues else None,
        "n_events": len(rows),
        "last_event": rows[-1] if rows else None,
    }
