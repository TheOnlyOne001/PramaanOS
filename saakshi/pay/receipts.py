"""Receipt texts for overtime, pay and pay-dispute events, in en, ta, hi and or (registered with i18n on import)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import i18n

Template = Callable[[dict[str, Any]], str]


def _accepted(c: dict[str, Any], yes: str, no: str) -> str:
    return yes if c["decision"] == "accept" else no


def _corrected(c: dict[str, Any]) -> bool:
    return c["outcome"] == "corrected"


TEMPLATES: dict[str, dict[str, Template]] = {
    "ot.request": {
        "en": lambda c: f"Overtime request: {c['hours']:g} h on {c['date']}. Reply YES or NO. Saying no costs you nothing · ref {c['ref']}",
        "ta": lambda c: f"கூடுதல் நேர கோரிக்கை: {c['date']} அன்று {c['hours']:g} மணி. ஆம் / இல்லை. மறுத்தால் பாதிப்பு இல்லை · குறிப்பு {c['ref']}",
        "hi": lambda c: f"ओवरटाइम अनुरोध: {c['date']} को {c['hours']:g} घंटे। हाँ या ना। मना करने पर कोई नुकसान नहीं · संदर्भ {c['ref']}",
        "or": lambda c: f"ଅତିରିକ୍ତ ସମୟ ଅନୁରୋଧ: {c['date']} ରେ {c['hours']:g} ଘଣ୍ଟା। ହଁ କିମ୍ବା ନା · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "ot.consent": {
        "en": lambda c: f"You {_accepted(c, 'accepted', 'declined')} {c['hours']:g} h overtime at double pay · ref {c['ref']}",
        "ta": lambda c: f"{c['hours']:g} மணி கூடுதல் நேரத்தை (இரட்டை ஊதியம்) {_accepted(c, 'ஏற்றீர்கள்', 'மறுத்தீர்கள்')} · குறிப்பு {c['ref']}",
        "hi": lambda c: f"आपने {c['hours']:g} घंटे ओवरटाइम (दोगुना वेतन) {_accepted(c, 'स्वीकार', 'अस्वीकार')} किया · संदर्भ {c['ref']}",
        "or": lambda c: f"ଆପଣ {c['hours']:g} ଘଣ୍ଟା ଅତିରିକ୍ତ ସମୟ {_accepted(c, 'ଗ୍ରହଣ', 'ମନା')} କଲେ · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "pay.run": {
        "en": lambda c: f"Payslip {c['period']}: net ₹{c['net']:,.2f} · ref {c['ref']}",
        "ta": lambda c: f"{c['period']} ஊதியச் சீட்டு: நிகர ₹{c['net']:,.2f} · குறிப்பு {c['ref']}",
        "hi": lambda c: f"{c['period']} वेतन पर्ची: शुद्ध ₹{c['net']:,.2f} · संदर्भ {c['ref']}",
        "or": lambda c: f"{c['period']} ଦରମା ପତ୍ର: ନିଟ୍ ₹{c['net']:,.2f} · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "pay.paid": {
        "en": lambda c: f"Paid: ₹{c['net']:,.2f} for {c['period']} · ref {c['ref']}",
        "ta": lambda c: f"{c['period']} ஊதியம் செலுத்தப்பட்டது: ₹{c['net']:,.2f} · குறிப்பு {c['ref']}",
        "hi": lambda c: f"{c['period']} का वेतन भुगतान: ₹{c['net']:,.2f} · संदर्भ {c['ref']}",
        "or": lambda c: f"{c['period']} ଦରମା ପଇଠ: ₹{c['net']:,.2f} · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "pay.adjustment": {
        "en": lambda c: f"Correction on your {c['period']} payslip (case {c['case_id']}): ₹{c['amount']:,.2f} · ref {c['ref']}",
        "ta": lambda c: f"உங்கள் {c['period']} ஊதியச் சீட்டில் திருத்தம் (வழக்கு {c['case_id']}): ₹{c['amount']:,.2f} · குறிப்பு {c['ref']}",
        "hi": lambda c: f"आपकी {c['period']} वेतन पर्ची में सुधार (मामला {c['case_id']}): ₹{c['amount']:,.2f} · संदर्भ {c['ref']}",
        "or": lambda c: f"ଆପଣଙ୍କ {c['period']} ଦରମା ପତ୍ରରେ ସଂଶୋଧନ (ମାମଲା {c['case_id']}): ₹{c['amount']:,.2f} · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "dispute.opened": {
        "en": lambda c: f"Case {c['case_id']} opened: you questioned {c['line']} for {c['period']}. Answer due by {c['due']} · ref {c['ref']}",
        "ta": lambda c: f"வழக்கு {c['case_id']} திறக்கப்பட்டது: {c['period']} இன் {c['line']} குறித்து கேட்டீர்கள். {c['due']} க்குள் பதில் · குறிப்பு {c['ref']}",
        "hi": lambda c: f"मामला {c['case_id']} खुला: आपने {c['period']} की {c['line']} पर सवाल किया। जवाब {c['due']} तक · संदर्भ {c['ref']}",
        "or": lambda c: f"ମାମଲା {c['case_id']} ଖୋଲାଗଲା: ଆପଣ {c['period']} ର {c['line']} ବିଷୟରେ ପଚାରିଲେ। {c['due']} ସୁଦ୍ଧା ଉତ୍ତର · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "dispute.assigned": {
        "en": lambda c: f"Case {c['case_id']}: {c['owner']} is looking into it · ref {c['ref']}",
        "ta": lambda c: f"வழக்கு {c['case_id']}: {c['owner']} பரிசீலிக்கிறார் · குறிப்பு {c['ref']}",
        "hi": lambda c: f"मामला {c['case_id']}: {c['owner']} देख रहे हैं · संदर्भ {c['ref']}",
        "or": lambda c: f"ମାମଲା {c['case_id']}: {c['owner']} ଦେଖୁଛନ୍ତି · ସନ୍ଦର୍ଭ {c['ref']}",
    },
    "dispute.resolved": {
        "en": lambda c: (f"Case {c['case_id']} resolved: corrected, ₹{c['correction_amount']:,.2f} on your {c['period']} pay · ref {c['ref']}"
                         if _corrected(c) else f"Case {c['case_id']} resolved: explained — {c['note']} · ref {c['ref']}"),
        "ta": lambda c: (f"வழக்கு {c['case_id']} தீர்க்கப்பட்டது: திருத்தம், உங்கள் {c['period']} ஊதியத்தில் ₹{c['correction_amount']:,.2f} · குறிப்பு {c['ref']}"
                         if _corrected(c) else f"வழக்கு {c['case_id']} தீர்க்கப்பட்டது: விளக்கம் — {c['note']} · குறிப்பு {c['ref']}"),
        "hi": lambda c: (f"मामला {c['case_id']} सुलझा: सुधार, आपके {c['period']} वेतन में ₹{c['correction_amount']:,.2f} · संदर्भ {c['ref']}"
                         if _corrected(c) else f"मामला {c['case_id']} सुलझा: स्पष्टीकरण — {c['note']} · संदर्भ {c['ref']}"),
        "or": lambda c: (f"ମାମଲା {c['case_id']} ସମାଧାନ: ସଂଶୋଧନ, ଆପଣଙ୍କ {c['period']} ଦରମାରେ ₹{c['correction_amount']:,.2f} · ସନ୍ଦର୍ଭ {c['ref']}"
                         if _corrected(c) else f"ମାମଲା {c['case_id']} ସମାଧାନ: ବ୍ୟାଖ୍ୟା — {c['note']} · ସନ୍ଦର୍ଭ {c['ref']}"),
    },
}


def register() -> None:
    """Register every template with i18n (re-registering replaces, so repeat calls are harmless)."""
    for event_type, by_lang in TEMPLATES.items():
        i18n.register(event_type, by_lang)


register()
