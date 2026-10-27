"""HTTP routes for the skill passport (`/api/production`, `/api/passport/...`) and their request bodies."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..ledger import now_ts
from .coverage import DEFAULT_EXPIRY_HORIZON_DAYS, coverage, expiring
from .holder import passport
from .matching import match
from .production import Production, record_production
from .status import revoke as revoke_credential
from .status import status_list
from .store import get_credential
from .vc import DEFAULT_VERIFY_BASE, STATUS_LIST_PATH, issuer, qr_svg, verification_method, verify_url

router = APIRouter(prefix="/api")


class MatchReq(BaseModel):
    """Job match request body."""

    worker_id: str
    job_description: str


class Revoke(BaseModel):
    """Credential revocation request body."""

    reason: str
    by: str = "site-issuer"


def _stored_vc(cid: str) -> dict[str, Any]:
    """Return a stored credential's VC JSON, or raise 404."""
    r = get_credential(cid)
    if not r:
        raise HTTPException(404, "no such credential")
    vc: dict[str, Any] = json.loads(r["vc"])
    return vc


@router.post("/production")
def production(p: Production) -> dict[str, Any]:
    """Record a production count over HTTP."""
    return record_production(p)


@router.get("/passport/issuers")
def issuers() -> dict[str, Any]:
    """Return the trusted issuer list and status list location."""
    iss = issuer()
    return {"issuers": [{**iss, "verificationMethod": verification_method(iss)}],
            "status_list": STATUS_LIST_PATH, "updated": now_ts()}


@router.get("/passport/status")
def passport_status() -> dict[str, Any]:
    """Return the revocation status list over HTTP."""
    return status_list()


@router.get("/passport/coverage")
def passport_coverage() -> dict[str, Any]:
    """Return credential coverage over HTTP."""
    return coverage()


@router.get("/passport/expiring")
def passport_expiring(days: int = DEFAULT_EXPIRY_HORIZON_DAYS) -> list[dict[str, Any]]:
    """Return credentials expiring within the given number of days."""
    return expiring(days)


@router.post("/passport/match")
def passport_match(m: MatchReq) -> dict[str, Any]:
    """Match a worker to a job description over HTTP."""
    return match(m.worker_id, m.job_description)


@router.get("/passport/credentials/{cid}")
def credential(cid: str) -> dict[str, Any]:
    """Return a credential's verifiable credential JSON or 404."""
    return _stored_vc(cid)


@router.get("/passport/credentials/{cid}/qr")
def credential_qr(cid: str, base: str = Query(DEFAULT_VERIFY_BASE)) -> Response:
    """Return an SVG QR code linking to the credential's verification URL."""
    return Response(qr_svg(verify_url(_stored_vc(cid), base)), media_type="image/svg+xml")


@router.post("/passport/credentials/{cid}/revoke")
def revoke(cid: str, body: Revoke) -> dict[str, Any]:
    """Revoke a credential for fraud and record the revocation in the ledger."""
    return revoke_credential(cid, body.reason, body.by)


@router.get("/passport/{wid}")
def passport_get(wid: str) -> dict[str, Any]:
    """Return a worker's skill passport over HTTP."""
    return passport(wid)
