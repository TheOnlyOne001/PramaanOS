"""HTTP routes for Fair Pay. Handlers only delegate; responses are the plain dicts the functions return.

`response_model=None` keeps FastAPI from re-validating those dicts against the TypedDict return hints.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import config
from .audit import FairnessReport, fairness
from .limits import CapStatus, cap_status
from .overtime import Consent, OTRequest, consent, create_requests, list_requests
from .payslips import Payslip, payslip, run
from .records import require_worker
from .rules import DEMO_PERIOD, DEMO_PERIOD_START, RULES, Rules
from .shifts import Shift, hours
from .wages import TodayPay, today

router = APIRouter(prefix="/api")


@router.get("/rules", response_model=None)
def get_rules() -> Rules:
    """Return the wage and overtime rules in force."""
    return RULES


@router.get("/hours/{wid}", response_model=None)
def get_hours(wid: str, day_from: str = DEMO_PERIOD_START, day_to: str = config.DEMO_DAY) -> list[Shift]:
    """Return a worker's daily shifts between two ISO dates (inclusive); 404 if the worker is unknown."""
    require_worker(wid)
    return hours(wid, day_from, day_to)


@router.get("/ot/cap", response_model=None)
def get_cap(date: str | None = None) -> list[CapStatus]:
    """Return every worker's quarterly overtime cap status as of a date."""
    return cap_status(date)


@router.post("/ot/requests", response_model=None)
def post_requests(body: OTRequest) -> dict[str, list[dict[str, Any]]]:
    """Create overtime requests for the given workers."""
    return create_requests(body)


@router.get("/ot/requests", response_model=None)
def get_requests(worker_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    """List overtime requests, optionally filtered by worker and status."""
    return list_requests(worker_id, status)


@router.post("/ot/requests/{request_id}/consent", response_model=None)
def post_consent(request_id: str, body: Consent) -> dict[str, Any]:
    """Record a worker's accept/decline on an overtime request."""
    return consent(request_id, body)


@router.get("/pay/fairness", response_model=None)
def get_fairness(period: str = DEMO_PERIOD) -> FairnessReport:
    """Return the pay fairness report for a YYYY-MM period."""
    return fairness(period)


@router.post("/pay/run", response_model=None)
def post_run(period: str = DEMO_PERIOD) -> dict[str, Any]:
    """Run payroll for a YYYY-MM period."""
    return run(period)


@router.get("/pay/{wid}/today", response_model=None)
def get_today(wid: str, day: str | None = None) -> TodayPay:
    """Return a worker's hours and earnings for one day."""
    return today(wid, day)


@router.get("/pay/{wid}/payslip", response_model=None)
def get_payslip(wid: str, period: str = DEMO_PERIOD) -> Payslip:
    """Return a worker's payslip for a YYYY-MM period."""
    return payslip(wid, period)
