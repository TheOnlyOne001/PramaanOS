"""Revocation: the BitstringStatusList and the fraud-only revocation rule.

A credential is revoked only for fraud (e.g. falsified production records). A skill
does not lapse because someone left, disputed pay or was absent.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from .. import events, state
from ..ledger import now_ts
from .store import credential_rows, get_credential
from .vc import issuer, status_list_id

FRAUD_REASON = re.compile(r"fraud|falsif|forg|fake|fabricat", re.I)
REVOCATION_POLICY = "Credentials are revoked only for fraud. Skills do not expire when a worker leaves or disputes."
NOT_FRAUD_DETAIL = ("Credentials are revoked only for fraud (e.g. falsified production records). "
                    "A skill does not lapse because someone left, disputed pay or was absent.")


def status_list() -> dict[str, Any]:
    """Return the revocation status list bitmap for issued credentials."""
    rows = credential_rows()
    n = (max(r["status_index"] for r in rows) + 1) if rows else 0
    bits = [0] * n
    for r in rows:
        if r["revoked"]:
            bits[r["status_index"]] = 1
    return {"id": status_list_id(), "type": "BitstringStatusList", "statusPurpose": "revocation",
            "issuer": issuer()["id"], "updated": now_ts(), "length": n, "bitmap": bits,
            "revoked": [i for i, b in enumerate(bits) if b], "policy": REVOCATION_POLICY}


def revoke(cid: str, reason: str, by: str) -> dict[str, Any]:
    """Revoke a credential for fraud and record the revocation in the ledger.

    Raises HTTPException: 422 if the reason is not fraud, 404 if unknown, 409 if already revoked.
    """
    if not FRAUD_REASON.search(reason):
        raise HTTPException(422, NOT_FRAUD_DETAIL)
    st = state.get()
    with st.lock:
        r = get_credential(cid)
        if not r:
            raise HTTPException(404, "no such credential")
        if r["revoked"]:
            raise HTTPException(409, "already revoked")
        ts = now_ts()
        st.conn.execute("UPDATE passport_credentials SET revoked=1, revoked_reason=?, revoked_at=? WHERE id=?",
                        (reason, ts, r["id"]))
        payload = {"credential_id": r["id"], "skill": r["skill"], "level": r["level"], "reason": reason, "by": by,
                   "status_index": r["status_index"]}
        ev = st.ledger.append(events.CREDENTIAL_REVOKED, payload, worker_id=r["worker_id"], ts=ts)
    return {"credential_id": r["id"], "revoked": True, "status_index": r["status_index"], "event": ev}
