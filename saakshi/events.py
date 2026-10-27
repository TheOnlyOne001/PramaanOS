"""Ledger event types: the single list of every `type` string the system appends.

Each constant is the exact string stored in `events.type`, hashed into the signed body and used to
pick the receipt template in `saakshi/i18n.py`, so values must never change once events exist.
Import the constant instead of typing the string, e.g. `ledger.append(events.PUNCH_IN, ...)`.
"""
from __future__ import annotations

from typing import Final

# --- Proof of hours -----------------------------------------------------------------------------
PUNCH_IN: Final = "punch.in"
"""Worker entered the site at a gate device (payload: `device`)."""

PUNCH_OUT: Final = "punch.out"
"""Worker left the site at a gate device (payload: `device`)."""

PUNCH_CORRECTION: Final = "punch.correction"
"""Correction to an earlier punch: a new event, never an edit (payload: `corrects_seq, new_ts, reason, approver`)."""

ATTENDANCE_OPENING_BALANCE: Final = "attendance.opening_balance"
"""Days and overtime worked this pay period before the ledger started, imported from the muster register."""

PRODUCTION_COUNT: Final = "production.count"
"""Pieces produced on a line in a time slot (payload: `pieces, sam, minutes`), used for line efficiency."""

# --- Privacy ------------------------------------------------------------------------------------
ACCESS_LOOKUP: Final = "access.lookup"
"""Someone opened one worker's individual record; the worker gets a receipt naming viewer and reason."""

# --- Overtime -----------------------------------------------------------------------------------
OT_REQUEST: Final = "ot.request"
"""Supervisor asked a worker to work overtime; nothing is scheduled until the worker consents."""

OT_CAP_CHECK: Final = "ot.cap_check"
"""Quarterly overtime cap evaluated for a request (`used, after, cap, ok`), so a breach cannot be hidden later."""

OT_CONSENT: Final = "ot.consent"
"""Worker accepted or declined an overtime request; the payload carries the worker's own signature."""

OT_OPENING_BALANCE: Final = "ot.opening_balance"
"""Overtime hours already worked this quarter before the ledger started."""

# --- Pay ----------------------------------------------------------------------------------------
PAY_RUN: Final = "pay.run"
"""Payroll computed deterministically for a period; the payslip is derived from signed hours only."""

PF_DEPOSIT: Final = "pf.deposit"
"""Provident-fund deposit for a period (per contractor or direct), matched against PF deducted from wages."""

PAY_PAID: Final = "pay.paid"
"""Wages for a period were paid out to a worker after the pay run (payload: `period, net`)."""

PAY_ADJUSTMENT: Final = "pay.adjustment"
"""A correction added to a worker's pay for a period, e.g. from a resolved dispute (`period, amount, label, case_id`)."""

# --- Pay disputes -------------------------------------------------------------------------------
DISPUTE_OPENED: Final = "dispute.opened"
"""Worker questioned a payslip line (payload: `case_id, period, line, amount_questioned, note, due, by`)."""

DISPUTE_ASSIGNED: Final = "dispute.assigned"
"""A pay dispute was given to an owner to resolve (payload: `case_id, owner, by`)."""

DISPUTE_RESOLVED: Final = "dispute.resolved"
"""A pay dispute was closed as corrected or explained (payload: `case_id, period, outcome, note, correction_amount, by`)."""

# --- Skills passport ----------------------------------------------------------------------------
CREDENTIAL_ISSUED: Final = "credential.issued"
"""A signed skill credential was issued to a worker."""

CREDENTIAL_REVOKED: Final = "credential.revoked"
"""A skill credential was revoked; verifiers see the revocation through the public status list."""

# --- Edge camera box ----------------------------------------------------------------------------
EDGE_EVENT: Final = "edge.event"
"""Safety event counted on the on-site camera box (no video or faces leave the box)."""

EDGE_ZONES_SET: Final = "edge.zones_set"
"""Supervisor or HR redrew a camera's restricted zones (payload: `camera, zones:[{id, name, kind, points, updated_at}]`)."""

# --- Voice --------------------------------------------------------------------------------------
VOICE_REPORT: Final = "voice.report"
"""Anonymous worker report accepted by the relay; carries no identity."""

VOICE_RESPONSE: Final = "voice.response"
"""Management's public answer to a published voice theme, posted on the notice board."""

# --- Safety reports -----------------------------------------------------------------------------
SAFETY_REPORTED: Final = "safety.reported"
"""Worker raised a hazard or stop-work call from the phone (payload: `report_id, kind, zone, note, client_id, ack_due`)."""

SAFETY_ACKNOWLEDGED: Final = "safety.acknowledged"
"""Supervisor or HR acknowledged a safety report (payload: `report_id, by, by_role, by_name, note`)."""

SAFETY_RESOLVED: Final = "safety.resolved"
"""Supervisor or HR closed a safety report with what was done (payload: `report_id, by, by_role, by_name, note`)."""

ALL: Final[frozenset[str]] = frozenset({
    SAFETY_REPORTED, SAFETY_ACKNOWLEDGED, SAFETY_RESOLVED,
    PUNCH_IN, PUNCH_OUT, PUNCH_CORRECTION, ATTENDANCE_OPENING_BALANCE, PRODUCTION_COUNT, ACCESS_LOOKUP,
    OT_REQUEST, OT_CAP_CHECK, OT_CONSENT, OT_OPENING_BALANCE, PAY_RUN, PF_DEPOSIT, PAY_PAID, PAY_ADJUSTMENT,
    DISPUTE_OPENED, DISPUTE_ASSIGNED, DISPUTE_RESOLVED,
    CREDENTIAL_ISSUED, CREDENTIAL_REVOKED, EDGE_EVENT, EDGE_ZONES_SET, VOICE_REPORT, VOICE_RESPONSE,
})
"""Every known event type, for validation and tests."""
