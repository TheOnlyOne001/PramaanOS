"""Relay (anonymous): verify a token, spend its nullifier once, store the report with no identity.

The relay is meant to be run by a third party (a union, NGO or auditor) so the employer never sees network
metadata. For the demo it is run by the Saakshi team in this same app. It takes no Request object, so it
reads no IP or user agent; run it with access logging off. It stores no worker id and only the hour.
Remaining leak, documented: the ledger's seq order puts the report between other events.
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException

from ..ledger import now_ts
from ..state import State
from .blind import TOKEN_BYTES, nullifier, to_hex, verify
from .keys import key
from .store import report_count, resolve, sha256_hex
from .topics import MAX_REPORT_CHARS, RELAY_NOTE, ROUTES, THRESHOLD, check_month, check_topic, message, status

CASE_KEY_BYTES = 16
"""Entropy of the case key the worker keeps to follow a report."""
_HOUR_PREFIX = len("2026-10-27T14")   # date and hour of an ISO 8601 timestamp
_OFFSET_START = len("2026-10-27T14:05:09")  # where the UTC offset begins


def round_to_hour(ts: str) -> str:
    """Round an ISO timestamp down to the hour (keeps the offset)."""
    return ts[:_HOUR_PREFIX] + ":00:00" + ts[_OFFSET_START:]


def _clean_text(text: str | None) -> str:
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "text is empty")
    if len(text) > MAX_REPORT_CHARS:
        raise HTTPException(422, f"text is too long ({MAX_REPORT_CHARS} characters max)")
    return text


def _parse_token(token_hex: str, signature_hex: str) -> tuple[bytes, int]:
    try:
        m = bytes.fromhex(token_hex)
        sig = int(signature_hex, 16)
    except (TypeError, ValueError):
        raise HTTPException(422, "token and signature must be hex") from None
    if len(m) != TOKEN_BYTES:
        raise HTTPException(422, f"token must be {TOKEN_BYTES} bytes")
    return m, sig


def submit_report(topic: str, month: str, token_hex: str, signature_hex: str, text: str, lang: str = "en",
                  ts: str | None = None, st: State | None = None) -> dict[str, Any]:
    """Store an anonymous report after verifying its token (≤2000 chars, one per token) and return its case key and status."""
    s = resolve(st)
    check_topic(topic)
    check_month(month)
    text = _clean_text(text)
    m, sig = _parse_token(token_hex, signature_hex)
    k = key(month, topic, create=False, st=s)
    if not k or not verify(month, topic, m, sig, k["n"], k["e"]):
        raise HTTPException(403, "token signature does not verify for this topic and month")
    nf = nullifier(month, topic, m)
    case_key = secrets.token_urlsafe(CASE_KEY_BYTES)
    hour = round_to_hour(ts or now_ts())
    with s.lock:
        if s.conn.execute("SELECT 1 FROM voice_reports WHERE nullifier=?", (nf,)).fetchone():
            raise HTTPException(409, "already spoken on this topic this month")
        s.conn.execute(
            "INSERT INTO voice_reports(nullifier, topic, month, text, lang, hour, case_key_hash, token_hex, sig_hex)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (nf, topic, month, text, lang, hour, sha256_hex(case_key), m.hex(), to_hex(sig)))
        # The ledger gets the fact, not the words: text may be identifying, the hash still pins it.
        ev = s.ledger.append("voice.report", {"topic": topic, "month": month, "nullifier": nf, "text_hash": sha256_hex(text)},
                             worker_id=None, ts=hour, receipt=False)
        count = report_count(month, topic, s)
    report_status = status(topic, count)
    msg, msg_en = message(topic, report_status, lang)
    out: dict[str, Any] = {
        "case_key": case_key, "topic": topic, "month": month, "status": report_status, "corroborations": count,
        "threshold": THRESHOLD, "nullifier": nf, "seq": ev["seq"], "relay": RELAY_NOTE,
        "message": msg, "message_en": msg_en}
    if topic in ROUTES:
        out["route_to"] = ROUTES[topic]
    return out
