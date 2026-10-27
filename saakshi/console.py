"""Employer console aggregation: exceptions first, plus the SDG 8 scorecard.

Reads every module through its plain Python functions. Each source is wrapped so
one module failing never blanks the console.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypedDict, TypeVar

from fastapi import APIRouter

from . import config, events, state
from .ledger import VerifyResult

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

PERIOD = config.DEMO_DAY[:7]
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
T = TypeVar("T")


class Alert(TypedDict):
    """One console exception: what needs attention, who it concerns and where to act."""
    severity: str
    kind: str
    title: str
    detail: str
    people: list[str]
    action: str
    link: str


class Target(TypedDict, total=False):
    """One SDG 8 scorecard row."""
    target: str
    label: str
    indicator: str
    value: float | int | str | None
    unit: str
    detail: str
    status: str
    un: str


def _safe(fn: Callable[[], T], default: T) -> T:
    """Run one console source; on failure log it and return `default` so the console still renders."""
    try:
        return fn()
    except Exception:
        log.exception("console source %s failed", getattr(fn, "__name__", fn))
        return default


def _names() -> dict[str, str]:
    return {r["id"]: r["name"] for r in state.get().conn.execute("SELECT id, name FROM workers")}


def _integrity_exceptions(v: VerifyResult) -> list[Alert]:
    out: list[Alert] = []
    edited = [p for p in v["problems"] if p["kind"] != "root_mismatch"]
    roots = [p for p in v["problems"] if p["kind"] == "root_mismatch"]
    names = _names()
    for p in edited:
        wid = p["worker_id"]
        who = (names.get(wid) if wid else None) or "site record"
        out.append({"severity": "critical", "kind": "integrity",
                    "title": f"Record edited after signing: {who} · {p.get('type')} #{p.get('seq')}",
                    "detail": p["detail"], "people": [wid] if wid else [],
                    "action": "Open evidence", "link": f"/api/ledger/events/{p.get('seq')}"})
    out.extend({"severity": "critical", "kind": "integrity", "title": "Published daily root no longer matches",
                "detail": p["detail"], "people": [], "action": "Compare with worker copies",
                "link": "/api/ledger/roots"} for p in roots)
    return out


def _ot_exceptions() -> list[Alert]:
    from . import pay
    rows = pay.cap_status(config.DEMO_DAY)
    out: list[Alert] = []
    near = [r for r in rows if r.get("status") in ("near", "over")]
    if near:
        names = ", ".join(f"{r['name']} ({r['used']:g}/{r['cap']:g} h)" for r in near)
        sev = "high" if any(r["status"] == "over" for r in near) else "medium"
        out.append({"severity": sev, "kind": "overtime", "title": f"{len(near)} workers near the quarterly overtime cap",
                    "detail": names, "people": [r["worker_id"] for r in near],
                    "action": "Rebalance overtime", "link": "#hours"})
    pend = pay.list_requests(status="pending")
    if pend:
        out.append({"severity": "low", "kind": "overtime", "title": f"{len(pend)} overtime requests awaiting worker consent",
                    "detail": "Declining costs the worker nothing; refusals are watched for retaliation.",
                    "people": [r["worker_id"] for r in pend], "action": "View requests", "link": "#hours"})
    return out


def _pay_exceptions() -> list[Alert]:
    from . import pay
    f = pay.fairness(PERIOD)
    out: list[Alert] = []
    for c in f.get("checks", []):
        if c.get("ok"):
            continue
        name = c.get("name", "Pay check")
        sev = "high" if any(k in name.lower() for k in ("deposit", "minimum", "overtime", "deduction", "integrity")) else "medium"
        out.append({"severity": sev, "kind": "pay", "title": f"Pay fairness: {name}",
                    "detail": c.get("detail", ""), "people": c.get("workers", []),
                    "action": "Review before payroll", "link": "#pay"})
    return out


def _voice_exceptions() -> list[Alert]:
    from . import voice
    out: list[Alert] = []
    for t in voice.themes():
        label = t.get("label")
        label = label.get("en") if isinstance(label, dict) else (label or t.get("topic"))
        if t.get("escalated") or (t.get("safety_critical") and t.get("count", 0) > 0 and not t.get("published")):
            out.append({"severity": "critical", "kind": "voice", "title": f"Safety-critical anonymous report: {label}",
                        "detail": "Sent straight to the safety officer. No identity attached.", "people": [],
                        "action": "Respond", "link": "#voice"})
        elif t.get("published") and not t.get("response"):
            out.append({"severity": "high", "kind": "voice",
                        "title": f"Workers say: {label} ({t.get('count')} independent reports)",
                        "detail": "; ".join(r.get("text", "") for r in (t.get("reports") or [])[:2]),
                        "people": [], "action": "Answer on the board", "link": "#voice"})
    return out


def _edge_exceptions() -> list[Alert]:
    from . import edge
    out: list[Alert] = []
    for e in edge.recent(limit=20):
        if not str(e.get("ts", "")).startswith(config.DEMO_DAY):
            continue
        kind = str(e.get("kind", ""))
        sev = {"fire_smoke": "critical", "person_down": "critical", "blocked_exit": "critical",
               "restricted_zone_entry": "high", "near_miss": "high", "heat_wbgt": "medium",
               "queue_length": "medium"}.get(kind)
        if not sev:
            continue
        out.append({"severity": sev, "kind": "safety",
                    "title": f"{e.get('zone')}: {kind.replace('_', ' ')}",
                    "detail": f"{e.get('camera')} at {str(e.get('ts'))[11:16]} · event only, no video or face left the box",
                    "people": [], "action": "Fix the cause, not the person", "link": "#safety"})
    return out


def _skills_exceptions() -> list[Alert]:
    from . import passport
    out: list[Alert] = [{"severity": "medium", "kind": "skills",
            "title": f"Credential expiring: {c.get('name') or c.get('worker_id')} · {c.get('skill') or c.get('title')}",
            "detail": f"Valid until {c.get('valid_until') or c.get('validUntil')}. The roster will block the machine after expiry.",
            "people": [c["worker_id"]] if c.get("worker_id") else [], "action": "Book training", "link": "#skills"}
           for c in passport.expiring(days=30)]
    cov = passport.coverage()
    for s in cov.get("single_points_of_failure", []) if isinstance(cov, dict) else []:
        label = s if isinstance(s, str) else (s.get("skill") or str(s))
        out.append({"severity": "low", "kind": "skills", "title": f"Single point of failure: {label}",
                    "detail": "Only one worker holds this skill independently.", "people": [],
                    "action": "Cross-train", "link": "#skills"})
    return out


@router.get("/console/overview")
def overview() -> dict[str, Any]:
    """Return the console overview: ledger integrity status and exceptions from all modules."""
    st = state.get()
    v = st.ledger.verify()
    exceptions = _integrity_exceptions(v)
    for src in (_voice_exceptions, _edge_exceptions, _pay_exceptions, _ot_exceptions, _skills_exceptions):
        exceptions += _safe(src, [])
    exceptions.sort(key=lambda e: (SEV_ORDER.get(e["severity"], 9), -len(e.get("people") or [])))
    counts = {s: sum(1 for e in exceptions if e["severity"] == s) for s in SEV_ORDER}
    return {"site": {"id": config.SITE_ID, "name": config.SITE_NAME, "day": config.DEMO_DAY},
            "integrity": {"ok": v["ok"], "n_events": v["n_events"], "problems": len(v["problems"]),
                          "roots": v["roots"][-3:]},
            "exceptions": exceptions, "counts": counts}


# --- SDG 8 scorecard ----------------------------------------------------------

def _pct(n: float, d: float) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def _scorecard() -> list[Target]:
    st = state.get()
    workers = [dict(r) for r in st.conn.execute("SELECT * FROM workers WHERE is_supervisor=0")]
    wids = [w["id"] for w in workers]
    out: list[Target] = []

    # 8.2 productivity: efficiency against standard minutes at line level
    def prod() -> float | None:
        evs = st.ledger.events(type=events.PRODUCTION_COUNT)
        mins = sum(e["payload"].get("minutes", 0) for e in evs)
        earned = sum(e["payload"].get("pieces", 0) * e["payload"].get("sam", 0) for e in evs)
        return round(100 * earned / mins, 1) if mins else None
    eff = _safe(prod, None)
    out.append({"target": "8.2", "label": "Productivity through upgrading", "indicator": "Line efficiency against standard minutes, constant quality",
                "value": eff, "unit": "%", "status": "ok" if (eff or 0) >= 65 else "watch", "un": "8.2.1"})

    # 8.3 formalisation: workers holding their own signed record
    holders = {r[0] for r in st.conn.execute("SELECT DISTINCT worker_id FROM wallet_receipts")}
    v83 = _pct(len([w for w in wids if w in holders]), len(wids))
    out.append({"target": "8.3", "label": "Formalise work", "indicator": "Workers holding a signed copy of their own hours and pay",
                "value": v83, "unit": "%", "status": "ok" if (v83 or 0) >= 90 else "watch", "un": "8.3.1"})

    # 8.5 decent work, equal pay
    def pay85() -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        from . import pay
        f = pay.fairness(PERIOD)
        checks = {c["name"]: c for c in f.get("checks", [])}
        mw = next((c for n, c in checks.items() if "minimum" in n.lower()), None)
        eq = next((c for n, c in checks.items() if "equal" in n.lower()), None)
        return mw, eq
    no_checks: tuple[Mapping[str, Any] | None, Mapping[str, Any] | None] = (None, None)
    mw, eq = _safe(pay85, no_checks)
    out.append({"target": "8.5", "label": "Decent work and equal pay", "indicator": "Paid at or above minimum wage · within-band gender gap",
                "value": ("✓" if mw and mw.get("ok") else "✗") if mw else None, "unit": "",
                "detail": "; ".join(x.get("detail", "") for x in (mw, eq) if x),
                "status": "ok" if (mw and mw.get("ok") and (not eq or eq.get("ok"))) else "watch", "un": "8.5.1"})

    # 8.6 skills: credentials earned per worker-year (annualised from this month)
    n_creds = len(st.ledger.events(type=events.CREDENTIAL_ISSUED))
    v86 = round(n_creds / max(len(wids), 1) * 12, 1)
    out.append({"target": "8.6", "label": "Skills for young workers", "indicator": "Skill credentials earned per worker-year (annualised)",
                "value": v86, "unit": "per worker-year", "status": "ok" if v86 >= 1 else "watch", "un": "8.6.1"})

    # 8.7 forced labour: overtime with consent; deposits matching deductions
    def ot87() -> float | None:
        from . import pay
        tot = cons = 0.0
        for wid in wids:
            for s in pay.hours(wid, "2026-10-01", config.DEMO_DAY):
                tot += s.get("ot_hours", 0) or 0
                cons += s.get("consented_ot_hours", 0) or 0
        return _pct(cons, tot) if tot else 100.0
    v87 = _safe(ot87, None)
    out.append({"target": "8.7", "label": "End forced labour", "indicator": "Overtime hours with signed worker consent",
                "value": v87, "unit": "%", "status": "ok" if (v87 or 0) >= 99 else "watch", "un": "8.7.1"})

    # 8.8 labour rights and safe work: near-miss reporting, voice response
    near = len([e for e in st.ledger.events(type=events.EDGE_EVENT)
                if e["payload"].get("kind") in ("near_miss", "restricted_zone_entry")])
    responses = len(st.ledger.events(type=events.VOICE_RESPONSE))
    reports = len(st.ledger.events(type=events.VOICE_REPORT))
    out.append({"target": "8.8", "label": "Labour rights and safe work", "indicator": "Near-miss events logged · anonymous reports answered",
                "value": near, "unit": "near-misses", "detail": f"{reports} anonymous reports, {responses} answered on the board",
                "status": "ok", "un": "8.8.1 / 8.8.2"})
    return out


@router.get("/sdg8/scorecard")
def scorecard() -> dict[str, Any]:
    """Return the site's SDG 8 scorecard targets for the reporting period."""
    targets: list[Target] = _safe(_scorecard, [])
    return {"site": config.SITE_NAME, "period": PERIOD, "targets": targets}
