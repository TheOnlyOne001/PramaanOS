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

# --- Skills passport ----------------------------------------------------------------------------
CREDENTIAL_ISSUED: Final = "credential.issued"
"""A signed skill credential was issued to a worker."""

CREDENTIAL_REVOKED: Final = "credential.revoked"
"""A skill credential was revoked; verifiers see the revocation through the public status list."""

# --- Edge camera box ----------------------------------------------------------------------------
EDGE_EVENT: Final = "edge.event"
"""Safety event counted on the on-site camera box (no video or faces leave the box)."""

# --- Voice --------------------------------------------------------------------------------------
VOICE_REPORT: Final = "voice.report"
"""Anonymous worker report accepted by the relay; carries no identity."""

VOICE_RESPONSE: Final = "voice.response"
"""Management's public answer to a published voice theme, posted on the notice board."""

ALL: Final[frozenset[str]] = frozenset({
    PUNCH_IN, PUNCH_OUT, PUNCH_CORRECTION, ATTENDANCE_OPENING_BALANCE, PRODUCTION_COUNT, ACCESS_LOOKUP,
    OT_REQUEST, OT_CAP_CHECK, OT_CONSENT, OT_OPENING_BALANCE, PAY_RUN, PF_DEPOSIT,
    CREDENTIAL_ISSUED, CREDENTIAL_REVOKED, EDGE_EVENT, VOICE_REPORT, VOICE_RESPONSE,
})
"""Every known event type, for validation and tests."""
