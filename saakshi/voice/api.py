"""HTTP routes for Voice: topics and keys, issuance, the anonymous relay, scrub, themes, cases and the board.

Access rules for each path live in saakshi/auth.py; the relay route takes no Request object, so it never
reads an IP address or user agent.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .issuer import Issuance, issue
from .keys import key, public
from .publication import BoardEntry, board, case_status, respond, themes
from .relay import submit_report
from .scrubber import Scrubbed, scrub
from .topics import MIN_GROUP, THRESHOLD, TOPICS, check_month, current_month

router = APIRouter(prefix="/api")
# Handlers return plain JSON-ready dicts; response_model=None keeps FastAPI from re-validating them.


class IssueReq(BaseModel):
    """Blinded messages for one worker's month, keyed by topic id (hex)."""

    worker_id: str
    month: str | None = None
    blinded: dict[str, str]


class ReportReq(BaseModel):
    """An anonymous report: the unblinded token and signature, and the text. No worker id."""

    topic: str
    month: str
    token: str
    signature: str
    text: str
    lang: str | None = "en"


class ScrubReq(BaseModel):
    """Text to check for identifying details."""

    text: str


class RespondReq(BaseModel):
    """A management response to a theme."""

    text: str
    by: str


@router.get("/voice/topics", response_model=None)
def topics_route(month: str | None = None) -> dict[str, Any]:
    """Topics with labels and each (month, topic) public key; keys are minted only for the current month."""
    month = month or current_month()
    check_month(month)
    create = month == current_month()  # never mint keys for arbitrary months
    out = []
    for t in TOPICS:
        k = key(month, t.id, create=create)
        out.append({"id": t.id, "label": t.labels, "safety_critical": t.safety_critical,
                    "key": public(k) if k else None})
    return {"month": month, "threshold": THRESHOLD, "min_group": MIN_GROUP, "topics": out}


@router.post("/voice/issue", response_model=None)
def issue_route(req: IssueReq) -> Issuance:
    """Blind-sign the worker's tokens; only for the current month."""
    month = req.month or current_month()
    if month != current_month():
        raise HTTPException(422, f"tokens are issued only for the current month ({current_month()})")
    return issue(req.worker_id, month, req.blinded)


@router.post("/relay/voice/reports", response_model=None)
def relay_report(req: ReportReq) -> dict[str, Any]:
    """Spend a token on an anonymous report."""
    return submit_report(req.topic, req.month, req.token, req.signature, req.text, req.lang or "en")


@router.post("/voice/scrub", response_model=None)
def scrub_route(req: ScrubReq) -> Scrubbed:
    """Stateless: nothing is stored or logged."""
    return scrub(req.text)


@router.get("/voice/themes", response_model=None)
def themes_route(month: str | None = None) -> list[dict[str, Any]]:
    """Themes for the console (employer roles only, see auth.py)."""
    if month:
        check_month(month)
    return themes(month)


@router.get("/voice/cases/{case_key}", response_model=None)
def case(case_key: str) -> dict[str, Any]:
    """Status of the theme a case key belongs to."""
    return case_status(case_key)


@router.post("/voice/themes/{topic}/respond", response_model=None)
def respond_route(topic: str, req: RespondReq) -> BoardEntry:
    """Answer a published or escalated theme."""
    return respond(topic, req.text, req.by)


@router.get("/voice/board", response_model=None)
def board_route() -> list[BoardEntry]:
    """The public "You said, we did" board."""
    return board()
