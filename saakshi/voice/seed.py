"""Demo seed: last month's published "toilets" theme, made with the real blind-issue / unblind / relay flow."""
from __future__ import annotations

import secrets

from ..state import State
from .blind import TOKEN_BYTES, blind, to_hex, unblind
from .issuer import issue
from .keys import key
from .publication import respond
from .relay import submit_report
from .topics import TOPIC_IDS

SEED_MONTH = "2026-09"
SEED_TOPIC = "toilets"
SEED_REPORTS: list[tuple[str, str, str, str]] = [  # worker id, text, lang, time
    ("W002", "Toilets on our floor are not cleaned after the lunch break", "ta", "2026-09-08T14:00:00+05:30"),
    ("W005", "No water or soap in the ladies toilet by the afternoon", "ta", "2026-09-09T16:00:00+05:30"),
    ("W007", "Toilet near the packing area is dirty for the whole second shift", "ta", "2026-09-11T17:00:00+05:30"),
    ("W008", "Ladies toilet not cleaned for two days, we hold it till we go home", "hi", "2026-09-12T13:00:00+05:30"),
]
SEED_RESPONSE: tuple[str, str, str] = (  # text, by, time
    "Two more cleaning shifts added; cleaning log posted at the door", "HR and Admin Manager", "2026-09-19T11:00:00+05:30")


def _report_as(worker_id: str, text: str, lang: str, ts: str, st: State) -> None:
    """Do what one worker's phone does: blind every topic at once, get signatures, spend the seed topic's token."""
    held: dict[str, tuple[bytes, int]] = {}
    blinded: dict[str, str] = {}
    for tid in TOPIC_IDS:  # every topic at once, as the app does
        k = key(SEED_MONTH, tid, st=st)
        m = secrets.token_bytes(TOKEN_BYTES)
        b, r = blind(SEED_MONTH, tid, m, k["n"], k["e"])
        held[tid], blinded[tid] = (m, r), to_hex(b)
    sigs = issue(worker_id, SEED_MONTH, blinded, st=st)["signatures"]
    k = key(SEED_MONTH, SEED_TOPIC, st=st)
    m, r = held[SEED_TOPIC]
    s = unblind(int(sigs[SEED_TOPIC], 16), r, k["n"])
    submit_report(SEED_TOPIC, SEED_MONTH, m.hex(), to_hex(s), text, lang, ts=ts, st=st)


def seed_demo(st: State) -> None:
    """Previous month: a published "toilets" theme with 4 reports and a management answer, made with the real
    blind-issue / unblind / relay flow. Nothing for the current month (the live demo creates "water")."""
    if st.conn.execute("SELECT 1 FROM voice_responses LIMIT 1").fetchone():
        return
    for wid, text, lang, ts in SEED_REPORTS:
        _report_as(wid, text, lang, ts, st)
    text, by, ts = SEED_RESPONSE
    respond(SEED_TOPIC, text, by, month=SEED_MONTH, ts=ts, st=st)
