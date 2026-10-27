"""Safety reports derived from signed ledger events: received → acknowledged → resolved.

There is no mutable table: a report's state is replayed from its `safety.*` events, so every change
is signed, carries who made it, and drops a receipt in the reporting worker's wallet.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, TypedDict

from fastapi import HTTPException

from .. import events, state
from ..ledger import Event, now_ts
from .receipts import KIND_LABEL

Kind = Literal["hazard", "stop_work"]
KINDS: tuple[str, ...] = ("hazard", "stop_work")
ACK_WINDOW = {"stop_work": timedelta(minutes=15), "hazard": timedelta(hours=4)}
ZONE_MAX, NOTE_MAX, CLIENT_ID_MAX = 60, 300, 64


class TimelineEntry(TypedDict):
    """One step in a report's life, backed by the ledger event `seq`."""
    ts: str
    kind: str
    by: str
    text: str
    seq: int


class Report(TypedDict):
    """A worker's hazard or stop-work report and its delivery state."""
    report_id: str
    worker_id: str
    kind: str
    zone: str
    note: str
    status: str
    received_at: str
    ack_due: str
    acknowledged_at: str | None
    acknowledged_by: str | None
    resolved_at: str | None
    overdue: bool
    timeline: list[TimelineEntry]


def _now() -> str:
    """Current time; tests monkeypatch this to move the clock."""
    return now_ts()


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _name(wid: str | None) -> str:
    if not wid:
        return ""
    r = state.get().conn.execute("SELECT name FROM workers WHERE id=?", (wid,)).fetchone()
    return r["name"] if r else wid


def actor_name(sub: str, role: str) -> str:
    """Display name for whoever acted: the person's name if known, else role and id (e.g. "HR · H001")."""
    known = _name(sub)
    if known and known != sub:
        return known
    return f"{'HR' if role == 'hr' else role.title()} · {sub}"


def _replay(evs: list[Event], now: str) -> dict[str, Report]:
    out: dict[str, Report] = {}
    for e in evs:
        p = e["payload"]
        rid = str(p.get("report_id", ""))
        if e["type"] == events.SAFETY_REPORTED:
            kind = str(p.get("kind"))
            label = KIND_LABEL.get(kind, KIND_LABEL["hazard"])["en"]
            out[rid] = {"report_id": rid, "worker_id": e["worker_id"] or "", "kind": kind, "zone": p.get("zone", ""),
                        "note": p.get("note", ""), "status": "received", "received_at": e["ts"],
                        "ack_due": p.get("ack_due", e["ts"]), "acknowledged_at": None, "acknowledged_by": None,
                        "resolved_at": None, "overdue": False,
                        "timeline": [{"ts": e["ts"], "kind": "received", "by": _name(e["worker_id"]), "seq": e["seq"],
                                      "text": f"{label} reported — {p.get('zone', '')}" + (f": {p['note']}" if p.get("note") else "")}]}
            continue
        r = out.get(rid)
        if r is None:
            continue
        by = str(p.get("by_name") or p.get("by") or "")
        note = str(p.get("note") or "")
        if e["type"] == events.SAFETY_ACKNOWLEDGED:
            r["status"] = "acknowledged" if r["status"] == "received" else r["status"]
            r["acknowledged_at"], r["acknowledged_by"] = e["ts"], by
            r["timeline"].append({"ts": e["ts"], "kind": "acknowledged", "by": by, "seq": e["seq"],
                                  "text": f"Acknowledged by {by}" + (f": {note}" if note else "")})
        elif e["type"] == events.SAFETY_RESOLVED:
            r["status"], r["resolved_at"] = "resolved", e["ts"]
            r["timeline"].append({"ts": e["ts"], "kind": "resolved", "by": by, "seq": e["seq"], "text": f"Resolved by {by}: {note}"})
    n = _dt(now)
    for r in out.values():
        r["overdue"] = r["status"] == "received" and n > _dt(r["ack_due"])
    return out


def _all() -> dict[str, Report]:
    return _replay(state.get().ledger.events(type_prefix="safety."), _now())


def list_reports(worker_id: str | None = None) -> list[Report]:
    """Every safety report (or one worker's), newest first."""
    rows = [r for r in _all().values() if worker_id is None or r["worker_id"] == worker_id]
    return sorted(rows, key=lambda r: (_dt(r["received_at"]), r["timeline"][0]["seq"]), reverse=True)


def get_report(report_id: str) -> Report:
    """One report by id; 404 if unknown."""
    r = _all().get(report_id)
    if r is None:
        raise HTTPException(404, "unknown safety report")
    return r


def report(worker_id: str, kind: str, zone: str, note: str = "", client_id: str | None = None, ts: str | None = None) -> Report:
    """File a report for `worker_id`. A repeat with the same `client_id` from the same worker returns the first report."""
    zone, note = zone.strip(), note.strip()
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    if not zone or len(zone) > ZONE_MAX or len(note) > NOTE_MAX or (client_id is not None and len(client_id) > CLIENT_ID_MAX):
        raise HTTPException(422, f"zone is required (≤{ZONE_MAX} chars); note ≤{NOTE_MAX}; client_id ≤{CLIENT_ID_MAX}")
    st = state.get()
    with st.lock:
        if not st.conn.execute("SELECT 1 FROM workers WHERE id=?", (worker_id,)).fetchone():
            raise HTTPException(404, "unknown worker")
        evs = st.ledger.events(type=events.SAFETY_REPORTED)
        if client_id:
            for e in evs:
                if e["worker_id"] == worker_id and e["payload"].get("client_id") == client_id:
                    return get_report(str(e["payload"]["report_id"]))
        ts = ts or _now()
        rid = f"SAFE-{len(evs) + 1:04d}"
        due = (_dt(ts) + ACK_WINDOW[kind]).isoformat()
        st.ledger.append(events.SAFETY_REPORTED, {"report_id": rid, "kind": kind, "zone": zone, "note": note,
                                                  "client_id": client_id, "ack_due": due}, worker_id=worker_id, ts=ts)
        return get_report(rid)


def _transition(report_id: str, type_: str, by: str, role: str, note: str, ts: str | None) -> Report:
    st = state.get()
    with st.lock:
        r = get_report(report_id)
        if r["status"] == "resolved":
            raise HTTPException(409, "report is already resolved")
        if type_ == events.SAFETY_ACKNOWLEDGED and r["status"] == "acknowledged":
            return r  # acknowledging twice changes nothing
        st.ledger.append(type_, {"report_id": report_id, "by": by, "by_role": role, "by_name": actor_name(by, role), "note": note},
                         worker_id=r["worker_id"], ts=ts or _now())
        return get_report(report_id)


def acknowledge(report_id: str, by: str = "S001", role: str = "supervisor", note: str = "", ts: str | None = None) -> Report:
    """Mark a report acknowledged; the reporting worker gets a receipt naming who acknowledged it."""
    if len(note) > NOTE_MAX:
        raise HTTPException(422, f"note ≤{NOTE_MAX} chars")
    return _transition(report_id, events.SAFETY_ACKNOWLEDGED, by, role, note.strip(), ts)


def resolve(report_id: str, note: str, by: str = "S001", role: str = "supervisor", ts: str | None = None) -> Report:
    """Close a report with what was done (required); the reporting worker gets a receipt with the note."""
    note = note.strip()
    if not note or len(note) > NOTE_MAX:
        raise HTTPException(422, f"say what was done (1–{NOTE_MAX} chars)")
    return _transition(report_id, events.SAFETY_RESOLVED, by, role, note, ts)
