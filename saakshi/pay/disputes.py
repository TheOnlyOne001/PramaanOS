"""Pay disputes: a worker questions a payslip line, HR or a supervisor owns the case, HR resolves it.

Every step is a signed ledger event naming the worker, so the worker gets a receipt for each one.
The pay_disputes table only holds working state (status, owner, due date); the case timeline is read
back from the ledger, so the worker app and the employer console show the same signed history.
A correction is paid through a `pay.adjustment` event that the payslip shows as its own line.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal, TypedDict

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .. import auth, events, state
from ..db import register_schema
from ..ledger import Event, now_ts
from .records import require_worker
from .rules import round2

DEFAULT_OWNER = "HR · payroll desk"
DUE_WORKING_DAYS = 3            # an answer is due 3 working days (Mon–Sat) after the case opens
SUNDAY = 6                      # date.weekday() of the weekly off
STATUSES = ("open", "assigned", "resolved")
ACTIVE = ("open", "assigned")   # a case in these holds its payslip "under review"
MAX_AMOUNT_INR = 10_000_000
CASE_PREFIX = "PAY-"

register_schema("""
CREATE TABLE IF NOT EXISTS pay_disputes(
  case_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, period TEXT NOT NULL, line TEXT NOT NULL,
  amount_questioned REAL NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL,
  due TEXT NOT NULL, created TEXT NOT NULL, resolved_at TEXT, outcome TEXT, correction_amount REAL,
  opened_seq INTEGER NOT NULL, resolved_seq INTEGER, adjustment_seq INTEGER);
CREATE INDEX IF NOT EXISTS ix_pay_disputes_worker ON pay_disputes(worker_id, period, status);
""")


class DisputeOpen(BaseModel):
    """Request body for a worker questioning one payslip line or deduction."""
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    line: str = Field(min_length=1, max_length=80)
    amount_questioned: float = Field(ge=0, le=MAX_AMOUNT_INR)
    note: str = Field(default="", max_length=300)
    ts: str | None = None


class DisputeAssign(BaseModel):
    """Request body for giving a case to an owner."""
    owner: str = Field(min_length=1, max_length=80)
    ts: str | None = None


class DisputeResolve(BaseModel):
    """Request body for closing a case; `correction_amount` (non-zero) is required when corrected."""
    outcome: Literal["corrected", "explained"]
    note: str = Field(max_length=300)
    correction_amount: float | None = Field(default=None, ge=-MAX_AMOUNT_INR, le=MAX_AMOUNT_INR)
    ts: str | None = None


class TimelineEntry(TypedDict):
    """One signed step of a case, read from the ledger."""
    ts: str
    kind: str
    by: str
    text: str
    seq: int


class Case(TypedDict):
    """A pay dispute with its signed timeline."""
    case_id: str
    worker_id: str
    worker_name: str
    period: str
    line: str
    amount_questioned: float
    note: str
    status: str
    owner: str
    due: str
    created: str
    resolved_at: str | None
    outcome: str | None
    correction_amount: float | None
    timeline: list[TimelineEntry]


def due_date(created: str, working_days: int = DUE_WORKING_DAYS) -> str:
    """Return the ISO date `working_days` working days (Mon–Sat, Sundays skipped) after `created`."""
    d = date.fromisoformat(created[:10])
    left = working_days
    while left:
        d += timedelta(days=1)
        if d.weekday() != SUNDAY:
            left -= 1
    return d.isoformat()


def correction_label(case_id: str) -> str:
    """Return the payslip line label for a correction paid on a case."""
    return f"Correction (case {case_id})"


def _actor(fallback: str) -> str:
    """Who is acting: the signed-in principal (by name when known), else `fallback` (auth off)."""
    p = auth.current()
    if not p:
        return fallback
    r = state.get().conn.execute("SELECT name FROM workers WHERE id=?", (p["sub"],)).fetchone()
    return f"{r['name']} ({p['sub']})" if r else f"{p['role'].upper()} {p['sub']}"


def _text(e: Event) -> str:
    """The timeline sentence for one dispute event (English; receipts carry the worker's language)."""
    p = e["payload"]
    if e["type"] == events.DISPUTE_OPENED:
        note = f" — {p['note']}" if p.get("note") else ""
        return f"Questioned {p['line']} for {p['period']}: ₹{p['amount_questioned']:,.2f}{note}"
    if e["type"] == events.DISPUTE_ASSIGNED:
        return f"Assigned to {p['owner']}"
    note = f" — {p['note']}" if p.get("note") else ""
    if p.get("outcome") == "corrected":
        amt = p["correction_amount"]
        verb = "added to" if amt >= 0 else "recovered from"
        return f"Corrected: ₹{abs(amt):,.2f} {verb} {p['period']} pay{note}"
    return f"Explained{note}"


def _timelines(worker_id: str | None = None) -> dict[str, list[TimelineEntry]]:
    """Every case's timeline from the signed dispute events, in ledger order."""
    out: dict[str, list[TimelineEntry]] = {}
    for e in state.get().ledger.events(worker_id=worker_id, type_prefix="dispute."):
        cid = e["payload"].get("case_id")
        if cid:
            out.setdefault(cid, []).append({"ts": e["ts"], "kind": e["type"].split(".", 1)[1], "by": e["payload"].get("by", ""),
                                            "text": _text(e), "seq": e["seq"]})
    return out


def _case(r: Any, timeline: list[TimelineEntry]) -> Case:
    return {"case_id": r["case_id"], "worker_id": r["worker_id"], "worker_name": r["worker_name"], "period": r["period"],
            "line": r["line"], "amount_questioned": r["amount_questioned"], "note": r["note"], "status": r["status"],
            "owner": r["owner"], "due": r["due"], "created": r["created"], "resolved_at": r["resolved_at"],
            "outcome": r["outcome"], "correction_amount": r["correction_amount"], "timeline": timeline}


_SELECT = "SELECT d.*, w.name AS worker_name FROM pay_disputes d JOIN workers w ON w.id=d.worker_id"


def _rows(where: str = "", args: tuple[Any, ...] = ()) -> list[Any]:
    return list(state.get().conn.execute(f"{_SELECT} {where} ORDER BY d.opened_seq DESC", args))


def _row(case_id: str) -> Any:
    rows = _rows("WHERE d.case_id=?", (case_id,))
    if not rows:
        raise HTTPException(404, f"no such case {case_id}")
    return rows[0]


def list_cases(status: str | None = None) -> list[Case]:
    """Return every case (with `worker_name`), newest first, optionally only those in `status`."""
    if status is not None and status not in STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(STATUSES)}")
    rows = _rows("WHERE d.status=?", (status,)) if status else _rows()
    tl = _timelines()
    return [_case(r, tl.get(r["case_id"], [])) for r in rows]


def worker_cases(wid: str) -> list[Case]:
    """Return one worker's cases, newest first; 404 if the worker is unknown."""
    require_worker(wid)
    tl = _timelines(wid)
    return [_case(r, tl.get(r["case_id"], [])) for r in _rows("WHERE d.worker_id=?", (wid,))]


def case(case_id: str) -> Case:
    """Return one case with its timeline; 404 if there is no such case."""
    r = _row(case_id)
    return _case(r, _timelines(r["worker_id"]).get(case_id, []))


def open_case_ids(wid: str, period: str) -> list[str]:
    """Return the ids of a worker's open or assigned cases on `period`, oldest first."""
    q = "SELECT case_id FROM pay_disputes WHERE worker_id=? AND period=? AND status IN (?, ?) ORDER BY opened_seq"
    return [r["case_id"] for r in state.get().conn.execute(q, (wid, period, *ACTIVE))]


def _next_id() -> str:
    n = state.get().conn.execute("SELECT COUNT(*) AS n FROM pay_disputes").fetchone()["n"]
    return f"{CASE_PREFIX}{n + 1:04d}"


def open_case(wid: str, body: DisputeOpen) -> Case:
    """Open a case on a worker's payslip line: one `dispute.opened` event (the worker gets a receipt)."""
    w = require_worker(wid)
    st = state.get()
    with st.lock:  # id, event and row are written as one step
        cid = _next_id()
        ts = body.ts or now_ts()
        due = due_date(ts)
        ev = st.ledger.append(events.DISPUTE_OPENED, {
            "case_id": cid, "period": body.period, "line": body.line, "amount_questioned": round2(body.amount_questioned),
            "note": body.note, "due": due, "by": _actor(f"{w['name']} ({wid})")}, worker_id=wid, ts=ts)
        st.conn.execute(
            "INSERT INTO pay_disputes(case_id, worker_id, period, line, amount_questioned, note, status, owner, due, created,"
            " opened_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, wid, body.period, body.line, round2(body.amount_questioned), body.note, "open", DEFAULT_OWNER, due,
             ev["ts"], ev["seq"]))
    return case(cid)


def assign(case_id: str, body: DisputeAssign) -> Case:
    """Give a case to an owner (re-assigning is allowed): one `dispute.assigned` event; 409 once resolved."""
    st = state.get()
    with st.lock:
        r = _row(case_id)
        if r["status"] == "resolved":
            raise HTTPException(409, f"case {case_id} is already resolved")
        st.ledger.append(events.DISPUTE_ASSIGNED, {"case_id": case_id, "owner": body.owner, "by": _actor(DEFAULT_OWNER)},
                         worker_id=r["worker_id"], ts=body.ts)
        st.conn.execute("UPDATE pay_disputes SET status='assigned', owner=? WHERE case_id=?", (body.owner, case_id))
    return case(case_id)


def resolve(case_id: str, body: DisputeResolve) -> Case:
    """Close a case as corrected or explained: a `dispute.resolved` event, plus a `pay.adjustment` when corrected.

    422 if a correction has no (or a zero) amount; 409 if the case is already resolved."""
    corrected = body.outcome == "corrected"
    if corrected and not body.correction_amount:
        raise HTTPException(422, "correction_amount (non-zero) is required when the outcome is corrected")
    amount = round2(body.correction_amount) if corrected and body.correction_amount is not None else None
    st = state.get()
    with st.lock:
        r = _row(case_id)
        if r["status"] == "resolved":
            raise HTTPException(409, f"case {case_id} is already resolved")
        wid, period, by = r["worker_id"], r["period"], _actor(DEFAULT_OWNER)
        ev = st.ledger.append(events.DISPUTE_RESOLVED, {"case_id": case_id, "period": period, "outcome": body.outcome,
                                                        "note": body.note, "correction_amount": amount, "by": by},
                              worker_id=wid, ts=body.ts)
        adj_seq = None
        if amount is not None:
            adj = st.ledger.append(events.PAY_ADJUSTMENT, {"period": period, "amount": amount, "label": correction_label(case_id),
                                                           "case_id": case_id, "resolved_seq": ev["seq"], "approver": by},
                                   worker_id=wid, ts=ev["ts"])
            adj_seq = adj["seq"]
        st.conn.execute("UPDATE pay_disputes SET status='resolved', resolved_at=?, outcome=?, correction_amount=?, resolved_seq=?,"
                        " adjustment_seq=? WHERE case_id=?", (ev["ts"], body.outcome, amount, ev["seq"], adj_seq, case_id))
    return case(case_id)
