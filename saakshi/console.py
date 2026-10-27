"""Employer console aggregation: exceptions first, the action queue, plus the SDG 8 scorecard.

Reads every module through its plain Python functions. Each source is wrapped so
one module failing never blanks the console.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, TypedDict, TypeVar

from fastapi import APIRouter

from . import config, events, state
from .ledger import VerifyResult, now_ts

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


# --- Action queue -------------------------------------------------------------
# One row per thing someone must do: specific issue, who is affected, owner, deadline, next action.

SUMMARY_LABELS = {"urgent_safety": "Urgent safety", "pay_discrepancies": "Pay discrepancies",
                  "pending_approvals": "Pending approvals", "overdue": "Overdue"}
EDGE_SEV = {"fire_smoke": "critical", "person_down": "critical", "blocked_exit": "critical",
            "restricted_zone_entry": "high", "near_miss": "high", "heat_wbgt": "medium", "queue_length": "medium"}
EDGE_ISSUE = {"fire_smoke": "Fire or smoke — {zone}", "person_down": "Person down — {zone}", "blocked_exit": "Blocked exit — {zone}",
              "restricted_zone_entry": "Restricted-zone entry — {zone}", "near_miss": "Near miss — {zone}",
              "heat_wbgt": "Heat stress — {zone}", "queue_length": "{zone} crowding"}
CRITICAL_RESPONSE = timedelta(minutes=15)
EVENT_LABEL = {events.PUNCH_IN: "punch-in", events.PUNCH_OUT: "punch-out", events.PUNCH_CORRECTION: "punch correction"}
_DEPOSIT = re.compile(r"(?P<emp>[^:;]+): PF deducted ₹(?P<ded>[\d,.]+), deposited ₹(?P<dep>[\d,.]+)")


class NextAction(TypedDict):
    """The one specific thing to do next and what it opens."""
    label: str
    kind: str
    target: str


class Item(TypedDict):
    """One action-queue row."""
    id: str
    category: str
    summary_key: str | None
    severity: str
    issue: str
    impact: str
    owner: str
    deadline: str | None
    overdue: bool
    next_action: NextAction
    count: int
    window: str | None
    events: list[int]
    people: list[str]


class Summary(TypedDict):
    """A headline count above the queue."""
    key: str
    label: str
    count: int


def _now() -> str:
    """Current time; tests monkeypatch this to move the clock."""
    return now_ts()


def _item(id_: str, category: str, severity: str, issue: str, impact: str, owner: str, action: tuple[str, str, str], *,
          summary_key: str | None = None, deadline: str | None = None, count: int = 1, window: str | None = None,
          evs: list[int] | None = None, people: list[str] | None = None) -> Item:
    if deadline and len(deadline) == 10:  # a bare date is due by the end of that day
        deadline = f"{deadline}T23:59:59{config.TZ}"
    overdue = bool(deadline) and datetime.fromisoformat(str(deadline)) < datetime.fromisoformat(_now())
    return {"id": id_, "category": category, "summary_key": summary_key, "severity": severity, "issue": issue, "impact": impact,
            "owner": owner, "deadline": deadline, "overdue": overdue,
            "next_action": {"label": action[0], "kind": action[1], "target": action[2]},
            "count": count, "window": window, "events": evs or [], "people": people or []}


def _supervisor() -> str:
    r = state.get().conn.execute("SELECT name FROM workers WHERE is_supervisor=1 ORDER BY id LIMIT 1").fetchone()
    return f"Line supervisor · {r['name'].split()[0]}" if r else "Line supervisor"


def _day_label(ts: str) -> str:
    try:
        d = datetime.fromisoformat(ts)
    except ValueError:
        return ts[:10]
    return f"{d.day} {d.strftime('%b')}"


def _window(first: str, last: str) -> str:
    mins = round((datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() / 60)
    if mins < 60:
        return f"{mins} minutes"
    h, m = divmod(mins, 60)
    return f"{h} h {m} min" if m else f"{h} h"


def _q_integrity(v: VerifyResult) -> list[Item]:
    names = _names()
    out: list[Item] = []
    by_seq: dict[int, list[Any]] = {}
    for p in v["problems"]:
        if p["kind"] != "root_mismatch" and p.get("seq") is not None:
            by_seq.setdefault(int(p["seq"] or 0), []).append(p)
    for seq, ps in sorted(by_seq.items()):
        p = ps[0]
        wid = p.get("worker_id")
        who = (names.get(wid) if wid else None) or "site record"
        what = EVENT_LABEL.get(p.get("type", ""), str(p.get("type", "event")))
        impact = f"{who} · pay held until the signed record is restored" if wid else "Site record · daily root will not match"
        out.append(_item(f"integrity:{seq}", "integrity", "critical",
                         f"Record edited after signing — {who}, {what} {_day_label(str(p.get('ts', '')))}",
                         f"{impact} · {'; '.join(x['detail'] for x in ps)}", "HR · records desk",
                         ("Compare records", "open_evidence", str(seq)), evs=[seq], people=[wid] if wid else []))
    out.extend(_item(f"integrity:root:{r['day']}", "integrity", "critical", f"Published daily root no longer matches — {_day_label(r['day'])}",
                     f"{r['n_events']} events that day · worker copies decide which version is true", "Auditor",
                     ("Compare records", "open_roots", r["day"]))
               for r in v["roots"] if not r["ok"])
    return out


def _q_safety() -> list[Item]:
    from . import safety
    names = _names()
    out: list[Item] = []
    for r in safety.list_reports():
        if r["status"] == "resolved":
            continue
        who = names.get(r["worker_id"], r["worker_id"])
        label = "Stop-work call" if r["kind"] == "stop_work" else "Hazard report"
        seqs = [t["seq"] for t in r["timeline"]]
        if r["status"] == "received":
            sev = "critical" if r["kind"] == "stop_work" else "high"
            out.append(_item(f"safety:{r['report_id']}", "safety", sev, f"{label} — {r['zone']}",
                             f"Raised by {who}" + (f" · {r['note']}" if r["note"] else "") + " · waiting for acknowledgement",
                             "Safety officer", ("Acknowledge report", "ack_safety", r["report_id"]), summary_key="urgent_safety",
                             deadline=r["ack_due"], evs=seqs, people=[r["worker_id"]]))
        else:
            out.append(_item(f"safety:{r['report_id']}", "safety", "medium", f"{label} — {r['zone']} · acknowledged, fix pending",
                             f"Raised by {who}" + (f" · {r['note']}" if r["note"] else "") + f" · acknowledged by {r['acknowledged_by']}",
                             "Safety officer", ("Assign responder", "go_section", "safety"), evs=seqs, people=[r["worker_id"]]))
    return out


def _q_edge() -> list[Item]:
    from . import edge
    groups: dict[tuple[str, str, str], list[Any]] = {}
    for e in edge.recent(limit=500):
        kind, ts = str(e.get("kind") or ""), str(e.get("ts") or "")
        if kind in EDGE_SEV and ts.startswith(config.DEMO_DAY):
            groups.setdefault((ts[:10], str(e.get("zone") or "Site"), kind), []).append(e)
    out: list[Item] = []
    for (day, zone, kind), rows in groups.items():
        rows.sort(key=lambda e: (e["ts"], e["seq"]))
        first, last, n = rows[0]["ts"], rows[-1]["ts"], len(rows)
        sev = EDGE_SEV[kind]
        window = _window(first, last) if n > 1 else None
        issue = EDGE_ISSUE[kind].format(zone=zone)
        issue = issue[0].upper() + issue[1:]
        if n > 1:
            issue += f" · {n} detections · {window}"
        span = f"{first[11:16]}–{last[11:16]}" if n > 1 else f"at {first[11:16]}"
        if kind == "queue_length":
            impact = f"Peak {max(int(e.get('count') or 0) for e in rows)} people waiting {span} · event counts only, no video or faces"
        elif kind == "heat_wbgt":
            impact = f"WBGT up to {max(float(e.get('value') or 0) for e in rows):g} °C {span} · water and rest breaks due"
        else:
            impact = f"{zone} · {n} detection{'s' if n > 1 else ''} {span} · event counts only, no video or faces"
        owner = "Safety officer" if sev in ("critical", "high") or kind == "heat_wbgt" else "Facilities · admin"
        if zone.lower().startswith("line") and sev != "critical":
            owner = _supervisor()
        deadline = (datetime.fromisoformat(first) + CRITICAL_RESPONSE).isoformat() if sev == "critical" else None
        action = ("Assign responder", "open_evidence", str(rows[0]["seq"])) if sev == "critical" else (
            "Schedule assessment", "open_evidence", str(rows[0]["seq"]))
        slug = re.sub(r"[^a-z0-9]+", "-", zone.lower()).strip("-")
        out.append(_item(f"edge:{day}:{slug}:{kind}", "safety", sev, issue, impact, owner, action,
                         summary_key="urgent_safety" if sev in ("critical", "high") else None, deadline=deadline,
                         count=n, window=window, evs=[e["seq"] for e in rows]))
    return out


def _q_disputes() -> list[Item]:
    try:
        from .pay import disputes  # type: ignore[attr-defined, unused-ignore]
    except ImportError:
        return []  # disputes not installed yet: the rest of the queue still renders
    names = _names()
    out: list[Item] = []
    cases: list[dict[str, Any]] = [dict(x) for x in disputes.list_cases()]
    for c in cases:
        if c.get("status") not in ("open", "assigned"):
            continue
        wid = str(c.get("worker_id") or "")
        who = str(c.get("worker_name") or names.get(wid, wid or "worker"))
        what = c.get("line") or c.get("summary") or c.get("title") or "payslip line"
        amount = c.get("amount_questioned", c.get("amount"))
        impact = f"{who}" + (f" · ₹{float(amount):,.0f} in question" if isinstance(amount, (int, float)) else "") + (
            f" · period {c['period']}" if c.get("period") else "")
        evs = [int(t["seq"]) for t in (c.get("timeline") or []) if isinstance(t, dict) and isinstance(t.get("seq"), int)]
        out.append(_item(f"dispute:{c.get('case_id')}", "pay", "high", f"Pay dispute — {who}, {what}", impact,
                         str(c.get("owner") or "HR · payroll desk"), ("Resolve case", "open_dispute", str(c.get("case_id"))),
                         summary_key="pay_discrepancies", deadline=c.get("due"), evs=evs, people=[wid] if wid else []))
    return out


def _pf_due(period: str) -> str:
    """EPF deposits are due by the 15th of the month after the wage period."""
    y, m = int(period[:4]), int(period[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-15T23:59:59{config.TZ}"


def _q_pay() -> list[Item]:
    from . import pay
    st = state.get()
    names = _names()
    workers = {r["id"]: dict(r) for r in st.conn.execute("SELECT id, contractor, contract_type FROM workers")}
    out: list[Item] = []
    for c in pay.fairness(PERIOD).get("checks", []):
        if c.get("ok"):
            continue
        name, flagged = c.get("name", ""), list(c.get("workers") or [])
        who = ", ".join(names.get(w, w) for w in flagged)
        if name == "Deposits match deductions":
            for m in _DEPOSIT.finditer(c.get("detail", "")):
                emp = m["emp"].strip()
                short = float(m["ded"].replace(",", "")) - float(m["dep"].replace(",", ""))
                ppl = [w for w in flagged if (workers.get(w) or {}).get("contractor") == emp] or flagged
                kind = "contract workers" if any((workers.get(w) or {}).get("contract_type") == "contract" for w in ppl) else "workers"
                dep = [e["seq"] for e in st.ledger.events(type=events.PF_DEPOSIT)
                       if (e["payload"].get("contractor") or "") == emp and e["payload"].get("period") == PERIOD]
                out.append(_item(f"pay:pf:{re.sub(r'[^a-z0-9]+', '-', emp.lower()).strip('-')}:{PERIOD}", "pay", "high",
                                 f"PF deposit shortfall — {emp}",
                                 f"{len(ppl)} {kind} · ₹{short:,.0f} not deposited (deducted ₹{m['ded']}, deposited ₹{m['dep']})",
                                 "HR · payroll desk", ("Review discrepancy", "open_evidence" if dep else "go_section", str(dep[-1]) if dep else "pay"),
                                 summary_key="pay_discrepancies", deadline=_pf_due(PERIOD), evs=dep, people=ppl))
            continue
        spec = {"Overtime paid right": ("Overtime without signed consent", "high", "Review discrepancy", "pay_discrepancies"),
                "Minimum wage": ("Minimum-wage shortfall", "high", "Review discrepancy", "pay_discrepancies"),
                "Deduction cap": ("Deductions above the 50% cap", "high", "Review discrepancy", "pay_discrepancies"),
                "Equal pay": ("Pay gap within band", "medium", "Review discrepancy", "pay_discrepancies"),
                "Contract vs permanent": ("Pay gap within band — contract vs permanent", "medium", "Review discrepancy", "pay_discrepancies"),
                "Overtime spread": ("Overtime concentrated on a few workers", "medium", "Rebalance overtime", None),
                "Fatigue": ("Overtime streak past the fatigue limit", "high", "Rebalance overtime", None)}.get(name)
        if spec is None:
            continue  # "Ledger integrity" is already a critical integrity row
        issue, sev, label, key = spec
        detail = c.get("detail", "")
        if name == "Overtime paid right":
            hrs = sum(s.get("unconsented_ot_hours", 0) or 0 for w in flagged for s in pay.hours(w, f"{PERIOD}-01", config.DEMO_DAY))
            impact = f"{len(flagged)} worker{'s' if len(flagged) != 1 else ''} · {hrs:g} h overtime without consent · {who}"
        else:
            impact = (f"{len(flagged)} worker{'s' if len(flagged) != 1 else ''} · " if flagged else "") + detail
        target = flagged[0] if flagged and label == "Review discrepancy" else ("hours" if label == "Rebalance overtime" else "pay")
        out.append(_item(f"pay:{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}:{PERIOD}", "pay", sev, issue, impact,
                         "HR · payroll desk" if key else _supervisor(),
                         (label, "open_lookup" if target in flagged else "go_section", target), summary_key=key, people=flagged))
    return out


def _q_overtime() -> list[Item]:
    from . import pay
    out: list[Item] = []
    near = [r for r in pay.cap_status(config.DEMO_DAY) if r.get("status") in ("near", "over")]
    if near:
        sev = "high" if any(r["status"] == "over" for r in near) else "medium"
        out.append(_item("ot:cap", "approval", sev, "Near the quarterly overtime cap — " + ", ".join(r["name"] for r in near),
                         " · ".join(f"{r['name'].split()[0]} {r['used']:g}/{r['cap']:g} h" for r in near), _supervisor(),
                         ("Rebalance overtime", "go_section", "hours"), people=[r["worker_id"] for r in near]))
    names = _names()
    for r in pay.list_requests(status="pending"):
        wid = r["worker_id"]
        out.append(_item(f"ot:request:{r['request_id']}", "approval", "low",
                         f"Overtime awaiting consent — {names.get(wid, wid)}, {r['hours']:g} h on {_day_label(r['date'])}",
                         "Nothing is scheduled until the worker accepts; declining costs nothing", f"Worker · {names.get(wid, wid)}",
                         ("View request", "go_section", "hours"), summary_key="pending_approvals",
                         evs=[int(x) for x in r.get("events") or [] if isinstance(x, int)], people=[wid]))
    return out


def _q_voice() -> list[Item]:
    from . import voice
    out: list[Item] = []
    for t in voice.themes():
        label = t.get("label")
        label = label.get("en") if isinstance(label, dict) else (label or t.get("topic"))
        topic = str(t.get("topic"))
        if t.get("escalated") or (t.get("safety_critical") and t.get("count", 0) > 0 and not t.get("published")):
            out.append(_item(f"voice:{topic}", "voice", "critical", f"Safety-critical anonymous report — {label}",
                             "Sent straight to the safety officer · no identity attached", "Safety officer",
                             ("Assign responder", "go_section", "voice"), summary_key="urgent_safety"))
        elif t.get("published") and not t.get("response"):
            texts = "; ".join(r.get("text", "") for r in (t.get("reports") or [])[:2])
            out.append(_item(f"voice:{topic}", "voice", "high", f"Workers say: {label} · {t.get('count')} independent reports",
                             texts or "Published on the board · waiting for management's answer", "HR · grievance desk",
                             ("Answer on the board", "go_section", "voice"), count=int(t.get("count") or 1)))
    return out


def _q_skills() -> list[Item]:
    from . import passport
    out: list[Item] = []
    for c in passport.expiring(days=30):
        until = str(c.get("valid_until") or "")
        out.append(_item(f"skills:{c.get('credential_id')}", "skills", "medium",
                         f"Credential expiring — {c.get('name') or c.get('worker_id')}, {c.get('label') or c.get('skill')}",
                         f"Valid until {until} ({c.get('days_left')} days) · the roster blocks the machine after expiry",
                         "HR · training", ("Book training", "open_lookup", str(c.get("worker_id"))),
                         deadline=f"{until}T23:59:59{config.TZ}" if until else None,
                         people=[c["worker_id"]] if c.get("worker_id") else []))
    return out


def _sort_key(i: Item) -> tuple[int, int, float, str]:
    dl = datetime.fromisoformat(i["deadline"]).timestamp() if i["deadline"] else float("inf")
    return (SEV_ORDER.get(i["severity"], 9), 0 if i["category"] == "integrity" else 1, dl, i["id"])


def queue() -> dict[str, Any]:
    """The employer's action queue: headline counts plus one specific, owned, dated row per thing to do."""
    items: list[Item] = _safe(lambda: _q_integrity(state.get().ledger.verify()), list[Item]())
    for src in (_q_safety, _q_edge, _q_disputes, _q_pay, _q_overtime, _q_voice, _q_skills):
        items += _safe(src, list[Item]())
    items.sort(key=_sort_key)
    summaries: list[Summary] = [{"key": k, "label": lbl,
                                 "count": len([i for i in items if (i["overdue"] if k == "overdue" else i["summary_key"] == k)])}
                                for k, lbl in SUMMARY_LABELS.items()]
    return {"summaries": summaries, "items": items}


@router.get("/console/queue")
def queue_route() -> dict[str, Any]:
    """Return the action queue (see `queue`)."""
    return queue()


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
