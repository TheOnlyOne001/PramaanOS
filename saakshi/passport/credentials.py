"""Issuing credentials: skill credentials from ledger evidence, and expiring safety credentials.

Each issue allocates a status-list bit, signs the VC, stores it and appends a
`credential.issued` ledger event (which drops a receipt in the worker's wallet).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any, TypedDict

from .. import config, events, state
from ..crypto import canonical, sha256_hex
from ..ledger import Event, now_ts
from ..state import State
from .evidence import assess, max_defect_rate, median_efficiency
from .rules import (
    EMPLOYER_ATTESTED,
    EVIDENCE_LABELS,
    LEVEL_LABELS,
    MACHINE_GUARDING,
    RULES_VERSION,
    SAFETY_CREDENTIALS,
    SKILL_RULES,
)
from .store import holds, next_status_index, worker_row
from .vc import VC_CONTEXT, VerifiableCredential, issuer, sign, status_entry, subject_id

END_OF_DAY = "T23:59:59"


class Issued(TypedDict):
    """A freshly issued credential and the ledger event announcing it."""

    credential: VerifiableCredential
    event: Event


def _new_vc(vc_type: str, valid_from: str, subject: dict[str, Any], idx: int,
            valid_until: str | None = None) -> VerifiableCredential:
    """Return an unsigned credential with the fields every Saakshi VC shares."""
    iss = issuer()
    vc: VerifiableCredential = {
        "@context": [VC_CONTEXT],
        "type": ["VerifiableCredential", vc_type],
        "id": f"urn:saakshi:cred:{uuid.uuid4()}",
        "issuer": {"id": iss["id"], "name": iss["name"]},
        "validFrom": valid_from,
    }
    if valid_until:
        vc["validUntil"] = valid_until
    vc["credentialSubject"] = subject
    vc["credentialStatus"] = status_entry(idx)
    return vc


def _store_and_announce(st: State, wid: str, vc: VerifiableCredential, kind: str, skill: str, level: str | None,
                        ts: str, valid_until: str | None, idx: int) -> Event:
    """Store a signed credential and append its `credential.issued` event; return the event."""
    vc_hash = sha256_hex(canonical(vc))
    st.conn.execute(
        "INSERT INTO passport_credentials(id, worker_id, kind, skill, level, vc, vc_hash, status_index, issued_at,"
        " valid_until) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (vc["id"], wid, kind, skill, level, json.dumps(vc, ensure_ascii=False), vc_hash, idx, ts, valid_until))
    payload: dict[str, Any] = {"credential_id": vc["id"], "skill": skill, "level": level, "vc_hash": vc_hash,
                               "kind": kind}
    if valid_until:
        payload["valid_until"] = valid_until
    ev = st.ledger.append(events.CREDENTIAL_ISSUED, payload, worker_id=wid, ts=ts)
    st.conn.execute("UPDATE passport_credentials SET seq=? WHERE id=?", (ev["seq"], vc["id"]))
    return ev


def issue_skill(wid: str, skill: str, ts: str | None = None) -> Issued:
    """Issue the skill credential from current ledger evidence. Caller checks `met` first."""
    st = state.get()
    w = worker_row(wid)
    rule = SKILL_RULES[skill]
    progress, q = assess(wid, skill)
    ts = ts or now_ts()
    subject = {
        "id": subject_id(wid), "name": w["name"], "skill": skill, "skillLabel": rule["label"],
        "level": rule["level"], "levelLabel": LEVEL_LABELS[rule["level"]],
        "evidenceLevel": rule["evidence_level"], "evidenceLabel": EVIDENCE_LABELS[rule["evidence_level"]],
        "nsqf": rule["nsqf"],
        "evidence": {
            "days": len(q),
            "medianEfficiency": f"{median_efficiency(q):.2f}",
            "maxDefectRate": f"{max_defect_rate(q):.3f}",
            "criteria": progress["criteria"]["text"],
            "rulesVersion": RULES_VERSION,
            "ledgerSeqs": [seq for d in q for seq in d["seqs"]],
        },
    }
    with st.lock:
        idx = next_status_index(st.conn)
        vc = sign(_new_vc("SkillCredential", ts, subject, idx), ts)
        ev = _store_and_announce(st, wid, vc, "skill", skill, rule["level"], ts, None, idx)
    return {"credential": vc, "event": ev}


def issue_safety(wid: str, cred: str = MACHINE_GUARDING, valid_from: str | None = None,
                 valid_until: str | None = None, ts: str | None = None) -> Issued:
    """Expiring safety credential (e.g. machine guarding induction).

    valid_from is the training date; ts is when it was recorded (e.g. imported from the training register).
    """
    st = state.get()
    w = worker_row(wid)
    spec = SAFETY_CREDENTIALS[cred]
    rec_ts = ts or now_ts()
    trained = valid_from or rec_ts
    valid_until = valid_until or (date.fromisoformat(trained[:10]) + timedelta(days=spec["valid_days"])).isoformat()
    subject = {"id": subject_id(wid), "name": w["name"], "skill": cred, "skillLabel": spec["label"],
               "evidenceLevel": EMPLOYER_ATTESTED, "evidenceLabel": EVIDENCE_LABELS[EMPLOYER_ATTESTED]}
    with st.lock:
        idx = next_status_index(st.conn)
        vc = _new_vc("SafetyTrainingCredential", trained, subject, idx,
                     valid_until=f"{valid_until}{END_OF_DAY}{config.TZ}")
        sign(vc, rec_ts)
        ev = _store_and_announce(st, wid, vc, "safety", cred, None, rec_ts, valid_until, idx)
    return {"credential": vc, "event": ev}


def check_and_issue(wid: str, skill: str, ts: str | None = None) -> VerifiableCredential | None:
    """Issue if the rule is met and the worker doesn't already hold it. Returns the VC or None."""
    if skill not in SKILL_RULES:
        return None
    with state.get().lock:
        if holds(wid, skill, SKILL_RULES[skill]["level"]):
            return None
        if not assess(wid, skill).progress["met"]:
            return None
        return issue_skill(wid, skill, ts=ts)["credential"]
