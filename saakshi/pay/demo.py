"""Demo history for Fair Pay: opening balances, a week of punches and consented overtime, and PF deposits."""
from __future__ import annotations

from .. import ledger as _ledger
from ..state import State
from .overtime import Consent, OTRequest, consent, create_requests
from .records import DIRECT, employer_of, workers
from .wages import pf_deducted

OPENING = {"W001": 70, "W002": 128, "W003": 133, "W004": 40, "W005": 20, "W006": 100, "W007": 30, "W008": 60}
WEEK_OT = {"W001": {"2026-10-21": 2, "2026-10-23": 2}, "W002": {"2026-10-20": 2, "2026-10-22": 2, "2026-10-24": 2, "2026-10-26": 2},
           "W003": {"2026-10-21": 2, "2026-10-23": 2, "2026-10-26": 2}, "W006": {"2026-10-22": 2}}
PAST = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]
PERIOD, QUARTER, WAGES_UPTO = "2026-10", "2026-Q4", "2026-10-26"
OPENING_TS = "2026-10-19T07:30:00+05:30"
OPENING_SOURCE = "Muster register 1–17 Oct, imported at install"
OPENING_DAYS_WORKED = 14
AGENCY_DEPOSIT_SHARE = 0.7      # the agency deposited only ~70% of the PF it deducted
RECEIPT_WORKER = "W001"         # the demo worker whose phone receives punch receipts
GATE_DEVICE = "bio-gate-1"


def _seed_opening_balances(ledger: _ledger.Ledger, wids: list[str]) -> None:
    for wid in wids:
        ledger.append("attendance.opening_balance", {"period": PERIOD, "days_worked": OPENING_DAYS_WORKED, "ot_hours": OPENING[wid],
                                                     "source": OPENING_SOURCE}, worker_id=wid, ts=OPENING_TS, receipt=False)
        ledger.append("ot.opening_balance", {"quarter": QUARTER, "hours": OPENING[wid], "source": OPENING_SOURCE},
                      worker_id=wid, ts=OPENING_TS, receipt=False)


def _seed_day(ledger: _ledger.Ledger, day: str, wids: list[str]) -> None:
    """One past day: consented overtime first, then a 9 h span (8 h work + 1 h break) plus that overtime."""
    for i, wid in enumerate(wids):
        ot = WEEK_OT.get(wid, {}).get(day, 0)
        if ot:
            body = OTRequest(worker_ids=[wid], date=day, hours=ot, requested_by="S001", reason="Shipment", ts=f"{day}T16:30:00+05:30")
            rid = create_requests(body)["requests"][0]["request_id"]
            consent(rid, Consent(decision="accept", channel="whatsapp", ts=f"{day}T16:40:00+05:30"))
        minute = 55 + i % 5
        ledger.append("punch.in", {"device": GATE_DEVICE}, worker_id=wid, ts=f"{day}T07:{minute:02d}:00+05:30", receipt=wid == RECEIPT_WORKER)
        ledger.append("punch.out", {"device": GATE_DEVICE}, worker_id=wid, ts=f"{day}T{16 + ot:02d}:{minute:02d}:00+05:30", receipt=wid == RECEIPT_WORKER)


def seed_demo(st: State) -> None:
    """Seed the ledger with demo opening balances and recent overtime history for every worker."""
    ledger = st.ledger
    ws = workers()
    wids = list(ws)
    _seed_opening_balances(ledger, wids)
    for day in PAST:
        _seed_day(ledger, day, wids)
    for i, wid in enumerate(wids):  # today: everyone but the demo worker is already clocked in
        if wid != RECEIPT_WORKER:
            ledger.append("punch.in", {"device": GATE_DEVICE}, worker_id=wid, ts=f"2026-10-27T07:{58 + i % 2:02d}:00+05:30", receipt=False)
    pf = {DIRECT: 0.0, "Sri Balaji Manpower": 0.0}
    for wid, w in ws.items():
        pf[employer_of(w)] += pf_deducted(wid, PERIOD, upto=WAGES_UPTO)
    for employer, amt in pf.items():
        dep = amt if employer == DIRECT else round(amt * AGENCY_DEPOSIT_SHARE, 2)
        ledger.append("pf.deposit", {"contractor": None if employer == DIRECT else employer, "period": PERIOD, "pf_deposited": dep,
                                     "wages_upto": WAGES_UPTO, "source": "EPFO ECR"}, ts="2026-10-26T18:00:00+05:30")
