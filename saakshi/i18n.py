"""Receipt text in the worker's language.

Modules register templates per event type with `register(type, {lang: fn})`,
where fn(ctx) -> str and ctx holds the payload fields plus `hm` (HH:MM),
`date`, `ref` and `type`. Supported languages: en, ta, hi, or.
Translations here are short and hand-written; Bhashini would replace them.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import events

LANGS = ("en", "ta", "hi", "or")

Template = Callable[[dict[str, Any]], str]
"""Renders one receipt line from the context (payload fields plus hm, date, ref, type)."""

_templates: dict[str, dict[str, Template]] = {}


def register(event_type: str, by_lang: dict[str, Template]) -> None:
    """Register per-language receipt templates for an event type."""
    _templates[event_type] = by_lang


def has(event_type: str) -> bool:
    """Return True if templates exist for event_type."""
    return event_type in _templates


def render(event_type: str, ctx: dict[str, Any], lang: str) -> str:
    """Render the event's receipt text in lang, falling back to English."""
    t = _templates.get(event_type)
    if not t:
        return f"{event_type} · ref {ctx.get('ref', '')}"
    fn = t.get(lang) or t["en"]
    try:
        return fn(ctx)
    except (KeyError, ValueError, TypeError):
        return t["en"](ctx)


register(events.PUNCH_IN, {
    "en": lambda c: f"In {c['hm']} · ref {c['ref']}",
    "ta": lambda c: f"வருகை {c['hm']} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आगमन {c['hm']} · संदर्भ {c['ref']}",
    "or": lambda c: f"ପ୍ରବେଶ {c['hm']} · ସନ୍ଦର୍ଭ {c['ref']}",
})
register(events.PUNCH_OUT, {
    "en": lambda c: f"Out {c['hm']} · ref {c['ref']}",
    "ta": lambda c: f"வெளியேற்றம் {c['hm']} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"प्रस्थान {c['hm']} · संदर्भ {c['ref']}",
    "or": lambda c: f"ପ୍ରସ୍ଥାନ {c['hm']} · ସନ୍ଦର୍ଭ {c['ref']}",
})
register(events.PUNCH_CORRECTION, {
    "en": lambda c: f"Correction to your record: {c.get('reason', '')} · approved by {c.get('approver', '')} · ref {c['ref']}",
    "ta": lambda c: f"உங்கள் பதிவில் திருத்தம்: {c.get('reason', '')} · ஒப்புதல் {c.get('approver', '')} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आपके रिकॉर्ड में सुधार: {c.get('reason', '')} · स्वीकृत {c.get('approver', '')} · संदर्भ {c['ref']}",
    "or": lambda c: f"ଆପଣଙ୍କ ରେକର୍ଡରେ ସଂଶୋଧନ: {c.get('reason', '')} · ସନ୍ଦର୍ଭ {c['ref']}",
})
register(events.ACCESS_LOOKUP, {
    "en": lambda c: f"{c.get('viewer', 'Someone')} opened your record: {c.get('reason', '')} · ref {c['ref']}",
    "ta": lambda c: f"{c.get('viewer', 'ஒருவர்')} உங்கள் பதிவைத் திறந்தார்: {c.get('reason', '')} · குறிப்பு {c['ref']}",
    "hi": lambda c: f"{c.get('viewer', 'किसी')} ने आपका रिकॉर्ड खोला: {c.get('reason', '')} · संदर्भ {c['ref']}",
    "or": lambda c: f"{c.get('viewer', 'କେହି')} ଆପଣଙ୍କ ରେକର୍ଡ ଖୋଲିଲେ: {c.get('reason', '')} · ସନ୍ଦର୍ଭ {c['ref']}",
})
