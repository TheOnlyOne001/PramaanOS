"""Core HTTP API: site, workers, punches, ledger integrity, receipts, access log, demo tools."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from . import config, state
from .ledger import now_ts

router = APIRouter(prefix="/api")

WorkerId = Annotated[str, StringConstraints(pattern=r"^[A-Z]\d{3}$")]
Ts = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")]
Text = Annotated[str, StringConstraints(max_length=200)]


def _demo_only():
    if not config.DEMO_MODE:
        raise HTTPException(404, "demo tools are disabled (SAAKSHI_DEMO=0)")


def _worker(wid: str) -> dict:
    r = state.get().conn.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone()
    if not r:
        raise HTTPException(404, f"unknown worker {wid}")
    return dict(r)


@router.get("/site")
def site():
    """Return site metadata, the ledger event count and the public keys."""
    st = state.get()
    return {"site_id": config.SITE_ID, "name": config.SITE_NAME, "state": config.STATE,
            "demo_day": config.DEMO_DAY, "now": now_ts(), "n_events": st.ledger.count(),
            "public_keys": {k: st.keys.public_hex(k) for k in ("site", "site-issuer", "edge-box-1")}}


@router.get("/workers")
def workers():
    """List all workers ordered by ID."""
    rows = state.get().conn.execute("SELECT * FROM workers ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@router.get("/workers/{wid}")
def worker(wid: str):
    """Return one worker's record."""
    return _worker(wid)


# --- Proof of Hours: punches ------------------------------------------------

class Punch(BaseModel):
    """Request body for a punch-in or punch-out event."""
    worker_id: WorkerId
    kind: str  # "in" | "out"
    ts: Ts | None = None
    device: Text = "bio-gate-1"


@router.post("/punch")
def punch(p: Punch):
    """Append a punch-in or punch-out event for a worker to the ledger."""
    _worker(p.worker_id)
    if p.kind not in ("in", "out"):
        raise HTTPException(422, "kind must be 'in' or 'out'")
    return state.get().ledger.append(f"punch.{p.kind}", {"device": p.device}, worker_id=p.worker_id, ts=p.ts)


class Correction(BaseModel):
    """Request body for correcting an earlier punch event."""
    worker_id: WorkerId
    corrects_seq: int = Field(ge=1)
    new_ts: Ts
    reason: Text
    approver: Text
    ts: Ts | None = None


@router.post("/punch/correction")
def punch_correction(c: Correction):
    """The only legitimate way to change a punch: a new signed event with a reason and an approver."""
    st = state.get()
    orig = st.ledger.get(c.corrects_seq)
    if not orig or orig["worker_id"] != c.worker_id or not orig["type"].startswith("punch."):
        raise HTTPException(422, "corrects_seq must be a punch event of this worker")
    return st.ledger.append("punch.correction", {"corrects_seq": c.corrects_seq, "new_ts": c.new_ts,
                                                 "reason": c.reason, "approver": c.approver},
                            worker_id=c.worker_id, ts=c.ts)


# --- Ledger -------------------------------------------------------------------

@router.get("/ledger/events")
def ledger_events(worker_id: str | None = None, type: str | None = None, type_prefix: str | None = None,
                  day: str | None = None, since_seq: int | None = None, limit: int = 200, desc: bool = True):
    """List ledger events matching the given filters (limit capped at 1000)."""
    limit = max(1, min(limit, 1000))
    return state.get().ledger.events(worker_id=worker_id, type=type, type_prefix=type_prefix, day=day,
                                     since_seq=since_seq, limit=limit, desc=desc)


@router.get("/ledger/events/{seq}")
def ledger_event(seq: int):
    """Return one ledger event by sequence number, or 404."""
    ev = state.get().ledger.get(seq)
    if not ev:
        raise HTTPException(404, "no such event")
    return ev


@router.get("/ledger/events/{seq}/proof")
def ledger_proof(seq: int):
    """Return the inclusion proof for a ledger event, or 404."""
    p = state.get().ledger.inclusion_proof(seq)
    if not p:
        raise HTTPException(404, "no such event")
    return p


@router.get("/ledger/verify")
def ledger_verify():
    """Verify the ledger and return the result, adding worker names to problems."""
    st = state.get()
    res = st.ledger.verify()
    names = {r["id"]: r["name"] for r in st.conn.execute("SELECT id, name FROM workers")}
    for p in res["problems"]:
        p["worker_name"] = names.get(p.get("worker_id"))
    return res


@router.get("/ledger/roots")
def ledger_roots():
    """Return the status of the ledger's daily roots."""
    return state.get().ledger.roots_status()


@router.post("/ledger/roots/publish")
def ledger_publish(day: str | None = None):
    """Publish the ledger root for a day (default: the demo day)."""
    return state.get().ledger.publish_root(day or config.DEMO_DAY)


# --- Worker wallet: receipts --------------------------------------------------

@router.get("/workers/{wid}/receipts")
def receipts(wid: str, limit: int = 100):
    """List a worker's wallet receipts, newest first (limit capped at 500)."""
    _worker(wid)
    limit = max(1, min(limit, 500))
    rows = state.get().conn.execute(
        "SELECT * FROM wallet_receipts WHERE worker_id=? ORDER BY seq DESC LIMIT ?", (wid, limit)).fetchall()
    return [dict(r) for r in rows]


class ReceiptRef(BaseModel):
    """A worker-held receipt: event sequence number and content hash."""
    seq: int
    hash: str


class ReceiptCheck(BaseModel):
    """Request body with optional worker-held receipts to check against the ledger."""
    receipts: list[ReceiptRef] | None = Field(default=None, max_length=5000)


@router.post("/workers/{wid}/receipts/check")
def receipts_check(wid: str, body: ReceiptCheck | None = None):
    """Compare the worker's copy (receipts) with what the employer's ledger says now."""
    from . import i18n
    from .ledger import receipt_ctx
    st = state.get()
    w = _worker(wid)
    if body and body.receipts:
        held = [r.model_dump() for r in body.receipts]
        texts = {}
    else:
        rows = st.conn.execute("SELECT * FROM wallet_receipts WHERE worker_id=?", (wid,)).fetchall()
        held = [{"seq": r["seq"], "hash": r["hash"]} for r in rows]
        texts = {r["seq"]: (r["text"], r["text_en"], r["ref"]) for r in rows}
    mismatches = []
    for h in held:
        ev = st.ledger.get(h["seq"])
        if ev is None:
            mismatches.append({"seq": h["seq"], "kind": "deleted", "receipt_hash": h["hash"],
                               "receipt_text": texts.get(h["seq"], ("", "", ""))[0],
                               "receipt_text_en": texts.get(h["seq"], ("", "", ""))[1]})
            continue
        current = st.ledger.content_hash(ev)
        if current != h["hash"]:
            ctx = receipt_ctx({**ev, "ref": texts.get(h["seq"], ("", "", ev["ref"]))[2] or ev["ref"]})
            mismatches.append({
                "seq": h["seq"], "kind": "edited", "type": ev["type"], "ref": ctx["ref"],
                "receipt_hash": h["hash"], "current_hash": current,
                "receipt_text": texts.get(h["seq"], ("", "", ""))[0],
                "receipt_text_en": texts.get(h["seq"], ("", "", ""))[1],
                "current_text": i18n.render(ev["type"], ctx, w["lang"]),
                "current_text_en": i18n.render(ev["type"], ctx, "en"),
            })
    return {"worker_id": wid, "checked": len(held), "ok": not mismatches, "mismatches": mismatches}


# --- Access log: every individual look-up is visible to the worker -------------

def log_access(worker_id: str, viewer: str, reason: str, what: str = "record", viewer_role: str = "employer") -> dict:
    """Call this from any endpoint that shows one worker's data to someone else."""
    st = state.get()
    ts = now_ts()
    st.conn.execute("INSERT INTO access_log(ts, viewer, viewer_role, worker_id, reason, what) VALUES (?,?,?,?,?,?)",
                    (ts, viewer, viewer_role, worker_id, reason, what))
    st.ledger.append("access.lookup", {"viewer": viewer, "viewer_role": viewer_role, "reason": reason, "what": what},
                     worker_id=worker_id)
    return {"ts": ts, "viewer": viewer, "reason": reason, "what": what}


class Lookup(BaseModel):
    """Request body for opening a worker's record: viewer, reason, role and scope."""
    viewer: Text
    reason: Text
    viewer_role: Text = "employer"
    what: Text = "record"


@router.post("/workers/{wid}/lookup")
def lookup(wid: str, body: Lookup):
    """Open one worker's record. Needs a reason; the worker sees it."""
    w = _worker(wid)
    if len(body.reason.strip()) < 3:
        raise HTTPException(422, "a reason is required to open an individual record")
    entry = log_access(wid, body.viewer, body.reason, body.what, body.viewer_role)
    st = state.get()
    return {"worker": w, "access": entry,
            "recent_events": st.ledger.events(worker_id=wid, limit=30, desc=True)}


@router.get("/workers/{wid}/access-log")
def access_log(wid: str):
    """List the access-log entries for a worker's record, newest first."""
    _worker(wid)
    rows = state.get().conn.execute("SELECT * FROM access_log WHERE worker_id=? ORDER BY id DESC", (wid,)).fetchall()
    return [dict(r) for r in rows]


# --- Demo tools ---------------------------------------------------------------

@router.post("/demo/reset")
def demo_reset():
    """Wipe and reseed the demo state, returning the new event count."""
    _demo_only()
    from . import seed
    st = state.reset(wipe=True)
    seed.seed_all(st)
    return {"ok": True, "n_events": st.ledger.count()}


class Tamper(BaseModel):
    """Request body for the demo tamper simulation."""
    seq: int | None = None
    worker_id: WorkerId = "W001"
    new_ts: Ts | None = None
    mode: str = "naive"  # "naive": edit the row. "rehash": edit and recompute its hash too.


@router.post("/demo/tamper")
def demo_tamper(t: Tamper):
    """Simulates someone with database access editing a punch-out, bypassing the app."""
    _demo_only()
    from .tamper import tamper_punch_out
    return tamper_punch_out(state.get().conn, worker_id=t.worker_id, seq=t.seq, new_ts=t.new_ts, mode=t.mode)
