"""Receipt text in the worker's language.

Modules register templates per event type with `register(type, {lang: fn})`,
where fn(ctx) -> str and ctx holds the payload fields plus `hm` (HH:MM),
`date`, `ref` and `type`. Supported languages: en, ta, hi, or.
Translations here are short and hand-written; Bhashini would replace them.
"""
from __future__ import annotations

from typing import Callable

LANGS = ("en", "ta", "hi", "or")

_templates: dict[str, dict[str, Callable[[dict], str]]] = {}


def register(event_type: str, by_lang: dict[str, Callable[[dict], str]]) -> None:
    _templates[event_type] = by_lang


def has(event_type: str) -> bool:
    return event_type in _templates


def render(event_type: str, ctx: dict, lang: str) -> str:
    t = _templates.get(event_type)
    if not t:
        return f"{event_type} · ref {ctx.get('ref', '')}"
    fn = t.get(lang) or t["en"]
    try:
        return fn(ctx)
    except (KeyError, ValueError, TypeError):
        return t["en"](ctx)


register("punch.in", {
    "en": lambda c: f"In {c['hm']} · ref {c['ref']}",
    "ta": lambda c: f"வருகை {c['hm']} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आगमन {c['hm']} · संदर्भ {c['ref']}",
    "or": lambda c: f"ପ୍ରବେଶ {c['hm']} · ସନ୍ଦର୍ଭ {c['ref']}",
})
register("punch.out", {
    "en": lambda c: f"Out {c['hm']} · ref {c['ref']}",
    "ta": lambda c: f"வெளியேற்றம் {c['hm']} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"प्रस्थान {c['hm']} · संदर्भ {c['ref']}",
    "or": lambda c: f"ପ୍ରସ୍ଥାନ {c['hm']} · ସନ୍ଦର୍ଭ {c['ref']}",
})
register("punch.correction", {
    "en": lambda c: f"Correction to your record: {c.get('reason', '')} · approved by {c.get('approver', '')} · ref {c['ref']}",
    "ta": lambda c: f"உங்கள் பதிவில் திருத்தம்: {c.get('reason', '')} · ஒப்புதல் {c.get('approver', '')} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आपके रिकॉर्ड में सुधार: {c.get('reason', '')} · स्वीकृत {c.get('approver', '')} · संदर्भ {c['ref']}",
    "or": lambda c: f"ଆପଣଙ୍କ ରେକର୍ଡରେ ସଂଶୋଧନ: {c.get('reason', '')} · ସନ୍ଦର୍ଭ {c['ref']}",
})
register("access.lookup", {
    "en": lambda c: f"{c.get('viewer', 'Someone')} opened your record: {c.get('reason', '')} · ref {c['ref']}",
    "ta": lambda c: f"{c.get('viewer', 'ஒருவர்')} உங்கள் பதிவைத் திறந்தார்: {c.get('reason', '')} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"{c.get('viewer', 'किसी')} ने आपका रिकॉर्ड खोला: {c.get('reason', '')} · संदर्भ {c['ref']}",
    "or": lambda c: f"{c.get('viewer', 'କେହି')} ଆପଣଙ୍କ ରେକର୍ଡ ଖୋଲିଲେ: {c.get('reason', '')} · ସନ୍ଦର୍ଭ {c['ref']}",
})
