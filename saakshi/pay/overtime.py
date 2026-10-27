"""Overtime requests and worker consent: cap and fatigue checks up front, consent signed by the worker's key."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .. import state
from ..crypto import canonical
from ..ledger import Event
from .limits import fatigue, is_near_cap, quarter_used, remaining
from .records import require_worker, workers
from .rules import RULES, round2

MAX_OT_HOURS_PER_REQUEST = 4
REQUEST_ID_HEX_CHARS = 8


class OTRequest(BaseModel):
    """Request body for asking one or more workers to do overtime (0–4 h) on a date."""
    worker_ids: list[str] = Field(min_length=1, max_length=200)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hours: float = Field(gt=0, le=MAX_OT_HOURS_PER_REQUEST)
    requested_by: str = Field(max_length=40)
    reason: str = Field(default="", max_length=200)
    ts: str | None = None


class Consent(BaseModel):
    """Request body for a worker accepting or declining an OT request via voice, tap or WhatsApp."""
    decision: str = Field(pattern="^(accept|decline)$")
    channel: str = Field(default="tap", pattern="^(voice|tap|whatsapp)$")
    transcript: str | None = Field(default=None, max_length=200)
    ts: str | None = None


@dataclass
class CapCheck:
    """Outcome of checking one proposed request against the quarterly cap and the fatigue rule."""
    used: float
    after: float
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False


def check_request(wid: str, day: str, hours: float) -> CapCheck:
    """Check `hours` more overtime for a worker on `day`: over the cap or fatigue blocks; near the cap warns."""
    cap = RULES["ot_cap_quarter"]
    used = quarter_used(wid, day)
    chk = CapCheck(used=used, after=round2(used + hours))
    if chk.after > cap:
        chk.blocked = True
        chk.warnings.append(f"Would breach the {cap} h quarterly cap ({chk.after:g} h)")
    elif is_near_cap(chk.after):
        chk.warnings.append(f"Near the quarterly cap: {round2(cap - chk.after):g} h left after this")
    tired = fatigue(wid, day)
    if tired:
        chk.blocked = True
        chk.warnings.append(f"Fatigue limit: {tired}")
    return chk


def _file_request(wid: str, body: OTRequest, chk: CapCheck) -> tuple[str, Event, Event]:
    """Ledger the request and its cap check, and store the request row; return its id and both events."""
    st = state.get()
    rid = "OT-" + uuid.uuid4().hex[:REQUEST_ID_HEX_CHARS].upper()
    ev_req = st.ledger.append("ot.request", {"request_id": rid, "date": body.date, "hours": body.hours,
                                             "requested_by": body.requested_by, "reason": body.reason},
                              worker_id=wid, ts=body.ts, receipt=not chk.blocked)
    ev_chk = st.ledger.append("ot.cap_check", {"request_id": rid, "used": chk.used, "after": chk.after,
                                               "cap": RULES["ot_cap_quarter"], "ok": not chk.blocked,
                                               "warnings": chk.warnings},
                              worker_id=wid, ts=body.ts, receipt=False)
    st.conn.execute("INSERT INTO ot_requests VALUES (?,?,?,?,?,?,?,?,NULL)",
                    (rid, wid, body.date, body.hours, _status(chk), body.requested_by, body.reason, ev_req["seq"]))
    return rid, ev_req, ev_chk


def _status(chk: CapCheck) -> str:
    return "blocked" if chk.blocked else "pending"


def create_requests(body: OTRequest) -> dict[str, list[dict[str, Any]]]:
    """Create and ledger an OT request per worker, blocking any that breach the quarterly cap or fatigue limits."""
    ws = workers()
    results = []
    for wid in body.worker_ids:
        w = require_worker(wid, ws)
        chk = check_request(wid, body.date, body.hours)
        rid, ev_req, ev_chk = _file_request(wid, body, chk)
        results.append({"request_id": rid, "worker_id": wid, "name": w["name"], "date": body.date,
                        "hours": body.hours, "status": _status(chk),
                        "cap": {"used": chk.used, "cap": RULES["ot_cap_quarter"], "remaining": remaining(chk.used),
                                "after": chk.after},
                        "warnings": chk.warnings, "events": [ev_req["seq"], ev_chk["seq"]]})
    return {"requests": results}


def list_requests(worker_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    """Return OT requests with worker names, newest first, optionally filtered by worker and status."""
    q, args = "SELECT r.*, w.name FROM ot_requests r JOIN workers w ON w.id=r.worker_id WHERE 1=1", []
    if worker_id:
        q += " AND r.worker_id=?"
        args.append(worker_id)
    if status:
        q += " AND r.status=?"
        args.append(status)
    return [dict(r) for r in state.get().conn.execute(q + " ORDER BY r.request_seq DESC", args)]


def consent(request_id: str, body: Consent) -> dict[str, Any]:
    """Record a worker-signed accept/decline on a pending OT request; 404 if unknown, 409 if not pending."""
    st = state.get()
    r = st.conn.execute("SELECT * FROM ot_requests WHERE request_id=?", (request_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such request")
    if r["status"] != "pending":
        raise HTTPException(409, f"request is {r['status']}")
    wid = r["worker_id"]
    worker_sig = st.keys.sign(f"worker:{wid}", canonical({"request_id": request_id, "decision": body.decision, "worker_id": wid}))
    ev = st.ledger.append("ot.consent", {"request_id": request_id, "decision": body.decision, "hours": r["hours"],
                                         "channel": body.channel, "transcript": body.transcript,
                                         "worker_sig": worker_sig}, worker_id=wid, ts=body.ts)
    status = "accepted" if body.decision == "accept" else "declined"
    st.conn.execute("UPDATE ot_requests SET status=?, consent_seq=? WHERE request_id=?", (status, ev["seq"], request_id))
    return {"request": {**dict(r), "status": status, "consent_seq": ev["seq"]}, "event": ev, "receipt": ev.get("receipt")}
