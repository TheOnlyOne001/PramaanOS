"""Receipt texts for safety reports, in en/ta/hi/or, registered with i18n on import.

The reporting worker gets one receipt per state change, so a stop-work call that nobody
acknowledges is visible on the worker's own phone as "received, acknowledgement due by …".
"""
from __future__ import annotations

from typing import Any

from .. import events, i18n

KIND_LABEL: dict[str, dict[str, str]] = {
    "hazard": {"en": "Hazard", "ta": "ஆபத்து", "hi": "खतरा", "or": "ବିପଦ"},
    "stop_work": {"en": "Stop-work call", "ta": "வேலை நிறுத்த அழைப்பு", "hi": "काम रोकने की सूचना", "or": "କାମ ବନ୍ଦ ଡାକରା"},
}


def _kind(c: dict[str, Any], lang: str) -> str:
    labels = KIND_LABEL.get(str(c.get("kind")), KIND_LABEL["hazard"])
    return labels.get(lang, labels["en"])


def _due(c: dict[str, Any]) -> str:
    return str(c.get("ack_due", ""))[11:16]


i18n.register(events.SAFETY_REPORTED, {
    "en": lambda c: f"{_kind(c, 'en')} report {c.get('report_id', '')} received · {c.get('zone', '')} · "
                    f"acknowledgement due by {_due(c)} · ref {c['ref']}",
    "ta": lambda c: f"{_kind(c, 'ta')} புகார் {c.get('report_id', '')} பெறப்பட்டது · {c.get('zone', '')} · "
                    f"{_due(c)} க்குள் ஒப்புதல் · குறிப்பு {c['ref']}",
    "hi": lambda c: f"{_kind(c, 'hi')} रिपोर्ट {c.get('report_id', '')} मिली · {c.get('zone', '')} · "
                    f"{_due(c)} तक पावती · संदर्भ {c['ref']}",
    "or": lambda c: f"{_kind(c, 'or')} ରିପୋର୍ଟ {c.get('report_id', '')} ମିଳିଲା · {c.get('zone', '')} · "
                    f"{_due(c)} ସୁଦ୍ଧା ସ୍ୱୀକୃତି · ସନ୍ଦର୍ଭ {c['ref']}",
})
i18n.register(events.SAFETY_ACKNOWLEDGED, {
    "en": lambda c: f"Your safety report {c.get('report_id', '')} was acknowledged by {c.get('by_name', '')} at {c['hm']} · ref {c['ref']}",
    "ta": lambda c: f"உங்கள் பாதுகாப்பு புகார் {c.get('report_id', '')} ஐ {c.get('by_name', '')} {c['hm']} மணிக்கு ஏற்றுக்கொண்டார் · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आपकी सुरक्षा रिपोर्ट {c.get('report_id', '')} को {c.get('by_name', '')} ने {c['hm']} बजे स्वीकार किया · संदर्भ {c['ref']}",
    "or": lambda c: f"ଆପଣଙ୍କ ସୁରକ୍ଷା ରିପୋର୍ଟ {c.get('report_id', '')} କୁ {c.get('by_name', '')} {c['hm']} ରେ ସ୍ୱୀକାର କଲେ · ସନ୍ଦର୍ଭ {c['ref']}",
})
i18n.register(events.SAFETY_RESOLVED, {
    "en": lambda c: f"Your safety report {c.get('report_id', '')} is resolved: {c.get('note', '')} · ref {c['ref']}",
    "ta": lambda c: f"உங்கள் பாதுகாப்பு புகார் {c.get('report_id', '')} தீர்க்கப்பட்டது: {c.get('note', '')} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आपकी सुरक्षा रिपोर्ट {c.get('report_id', '')} का समाधान हुआ: {c.get('note', '')} · संदर्भ {c['ref']}",
    "or": lambda c: f"ଆପଣଙ୍କ ସୁରକ୍ଷା ରିପୋର୍ଟ {c.get('report_id', '')} ର ସମାଧାନ ହେଲା: {c.get('note', '')} · ସନ୍ଦର୍ଭ {c['ref']}",
})
