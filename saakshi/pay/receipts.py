"""Receipt texts for overtime and pay events, in en, ta, hi and or (registered with i18n on import)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import i18n

Template = Callable[[dict[str, Any]], str]


def _accepted(c: dict[str, Any], yes: str, no: str) -> str:
    return yes if c["decision"] == "accept" else no


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
}


def register() -> None:
    """Register every template with i18n (re-registering replaces, so repeat calls are harmless)."""
    for event_type, by_lang in TEMPLATES.items():
        i18n.register(event_type, by_lang)


register()
