"""Per-line payslip explanations: a plain sentence, the rate, the signed source events, corrections and checks.

Every number here is copied from the deterministic wage arithmetic in `wages`; nothing is re-priced.
"""
from __future__ import annotations

from typing import Any, TypedDict

from .. import events, state
from ..ledger import Event
from .rules import RULES, period_last_day, round2
from .wages import Attendance, Earnings

MAX_SOURCES = 20
BASIC, OVERTIME, PF, ESI = "Basic + DA", "Overtime (2×)", "PF 12%", "ESI 0.75%"
"""Payslip line labels (the payslip uses these exact strings)."""

CHECKS = {
    BASIC: ["Ledger integrity", "Minimum wage"],
    OVERTIME: ["Ledger integrity", "Overtime paid at 2×", "Overtime consent"],
    PF: ["Deduction cap"],
    ESI: ["Deduction cap"],
}
"""The payslip checks that concern each line."""


class Source(TypedDict):
    """A signed event a line is computed from."""
    seq: int
    ts: str
    type: str


class CorrectionRef(TypedDict):
    """A signed punch correction that changed hours in the period."""
    seq: int
    ts: str
    reason: str
    approver: str


class Explain(TypedDict):
    """Why one payslip line has its amount."""
    summary: dict[str, str]
    days_worked: int | None
    hours: float | None
    rate: float | None
    rate_label: str
    sources: list[Source]
    corrections: list[CorrectionRef]
    checks: list[str]


def _sources(evs: list[Event]) -> list[Source]:
    seen: dict[int, Source] = {}
    for e in sorted(evs, key=lambda x: x["seq"]):
        seen.setdefault(e["seq"], {"seq": e["seq"], "ts": e["ts"], "type": e["type"]})
    return list(seen.values())[:MAX_SOURCES]


def _corrections(wid: str, period: str, punch_seqs: set[int]) -> list[CorrectionRef]:
    """Punch corrections that move a punch into the period or correct one of its punches."""
    out: list[CorrectionRef] = []
    for e in state.get().ledger.events(worker_id=wid, type=events.PUNCH_CORRECTION):
        p = e["payload"]
        if str(p.get("new_ts", ""))[:7] == period or p.get("corrects_seq") in punch_seqs:
            out.append({"seq": e["seq"], "ts": e["ts"], "reason": p.get("reason", ""), "approver": p.get("approver", "")})
    return out


def _ex(summary: dict[str, str], rate: float | None, rate_label: str, sources: list[Event], corrections: list[CorrectionRef],
        checks: list[str], days: int | None = None, hours: float | None = None) -> Explain:
    return {"summary": summary, "days_worked": days, "hours": hours, "rate": rate, "rate_label": rate_label,
            "sources": _sources(sources), "corrections": corrections, "checks": checks}


def explain_items(wid: str, period: str, upto: str | None, att: Attendance, pay: Earnings,
                  adjustments: list[Event]) -> dict[str, Explain]:
    """Return the explanation of every payslip line and deduction, keyed by its label."""
    ledger = state.get().ledger
    in_period = {e["seq"]: e for e in ledger.events(worker_id=wid, day_from=f"{period}-01", day_to=period_last_day(period, upto))}
    punches = [in_period[s] for sh in att.shifts for s in sh["evidence"] if s in in_period]
    ot_punches = [in_period[s] for sh in att.shifts if sh["ot_hours"] for s in sh["evidence"] if s in in_period]
    consents = [e for e in in_period.values() if e["type"] == events.OT_CONSENT and e["payload"].get("decision") == "accept"]
    ot_opening = [e for e in att.opening if e["payload"].get("ot_hours")]
    corr = _corrections(wid, period, {e["seq"] for e in punches})
    basic_src = att.opening + punches
    ot_src = (ot_opening + ot_punches + consents) or basic_src  # no overtime: the punches prove it

    paid_days = min(att.days, RULES["days_payable"])
    per_day = round2(pay.monthly / RULES["days_payable"])
    ot_rate = round2(RULES["ot_multiplier"] * pay.rate)
    rate = round2(pay.rate)
    h = att.ot_hours
    pf_base = round2(min(pay.basic, RULES["pf_wage_ceiling"]))
    pf_pct, esi_pct = f"{RULES['pf_rate']:.0%}", f"{RULES['esi_rate']:.2%}"
    ceiling = f"₹{RULES['esi_gross_ceiling']:,}"

    out: dict[str, Explain] = {
        BASIC: _ex({"en": f"{paid_days} days at ₹{per_day:,.2f} a day",
                    "ta": f"{paid_days} நாட்கள், நாளுக்கு ₹{per_day:,.2f}",
                    "hi": f"{paid_days} दिन, ₹{per_day:,.2f} प्रति दिन",
                    "or": f"{paid_days} ଦିନ, ଦିନକୁ ₹{per_day:,.2f}"},
                   per_day, f"₹{per_day:,.2f} a day (₹{pay.monthly:,} a month ÷ {RULES['days_payable']})", basic_src, corr,
                   CHECKS[BASIC], days=att.days),
        OVERTIME: _ex({"en": f"{h:g} overtime hours at ₹{ot_rate:,.2f} an hour (double the ₹{rate:,.2f} rate)",
                       "ta": f"{h:g} கூடுதல் மணி நேரம், மணிக்கு ₹{ot_rate:,.2f} (₹{rate:,.2f} இன் இரு மடங்கு)",
                       "hi": f"{h:g} घंटे ओवरटाइम, ₹{ot_rate:,.2f} प्रति घंटा (₹{rate:,.2f} का दोगुना)",
                       "or": f"{h:g} ଘଣ୍ଟା ଅତିରିକ୍ତ ସମୟ, ଘଣ୍ଟାକୁ ₹{ot_rate:,.2f} (₹{rate:,.2f} ର ଦୁଇଗୁଣ)"},
                      ot_rate, f"₹{ot_rate:,.2f} an hour ({RULES['ot_multiplier']} × ₹{rate:,.2f})", ot_src,
                      corr, CHECKS[OVERTIME], hours=h),
        PF: _ex({"en": f"{pf_pct} of your basic pay ₹{pf_base:,.2f}, saved in your provident fund",
                 "ta": f"உங்கள் அடிப்படை ஊதியம் ₹{pf_base:,.2f} இல் {pf_pct}, உங்கள் வருங்கால வைப்பு நிதியில் சேமிப்பு",
                 "hi": f"आपके मूल वेतन ₹{pf_base:,.2f} का {pf_pct}, आपके भविष्य निधि में जमा",
                 "or": f"ଆପଣଙ୍କ ମୂଳ ଦରମା ₹{pf_base:,.2f} ର {pf_pct}, ଆପଣଙ୍କ ଭବିଷ୍ୟ ନିଧିରେ ଜମା"},
                RULES["pf_rate"], f"{pf_pct} of basic, up to ₹{RULES['pf_wage_ceiling']:,}", basic_src, corr, CHECKS[PF]),
        ESI: _ex({"en": f"{esi_pct} of your gross pay ₹{pay.gross:,.2f}, for health insurance",
                  "ta": f"உங்கள் மொத்த ஊதியம் ₹{pay.gross:,.2f} இல் {esi_pct}, மருத்துவக் காப்பீட்டுக்கு",
                  "hi": f"आपके कुल वेतन ₹{pay.gross:,.2f} का {esi_pct}, स्वास्थ्य बीमा के लिए",
                  "or": f"ଆପଣଙ୍କ ମୋଟ ଦରମା ₹{pay.gross:,.2f} ର {esi_pct}, ସ୍ୱାସ୍ଥ୍ୟ ବୀମା ପାଇଁ"} if pay.esi else
                 {"en": f"No ESI: gross pay is above {ceiling}",
                  "ta": f"ESI இல்லை: மொத்த ஊதியம் {ceiling} க்கு மேல்",
                  "hi": f"ESI नहीं: कुल वेतन {ceiling} से अधिक",
                  "or": f"ESI ନାହିଁ: ମୋଟ ଦରମା {ceiling} ରୁ ଅଧିକ"},
                 RULES["esi_rate"], f"{esi_pct} of gross, if gross ≤ {ceiling}", basic_src + ot_punches, corr, CHECKS[ESI]),
    }
    for e in adjustments:
        out[e["payload"]["label"]] = _adjustment(e)
    return out


def _adjustment(e: Event) -> Explain:
    p: dict[str, Any] = e["payload"]
    cid, amt = p.get("case_id", ""), round2(p["amount"])
    src = [e]
    resolved = state.get().ledger.get(p["resolved_seq"]) if p.get("resolved_seq") else None
    if resolved:
        src.append(resolved)
    return _ex({"en": f"Correction from case {cid}: ₹{amt:,.2f}",
                "ta": f"வழக்கு {cid} இன் திருத்தம்: ₹{amt:,.2f}",
                "hi": f"मामला {cid} से सुधार: ₹{amt:,.2f}",
                "or": f"ମାମଲା {cid} ରୁ ସଂଶୋଧନ: ₹{amt:,.2f}"},
               None, f"Settled in full on case {cid}", src, [], [])
