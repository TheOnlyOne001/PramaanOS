"""Wallet receipt texts for passport events, in every language the wallet speaks (en, ta, hi, or).

Importing this module registers the templates with `saakshi.i18n` (once, on first import).
"""
from __future__ import annotations

from functools import partial
from typing import Any

from .. import events, i18n

Ctx = dict[str, Any]

_SKILL_NAMES = {
    "overlock": {"en": "overlock", "ta": "ஓவர்லாக்", "ta_loc": "ஓவர்லாக்கில்", "hi": "ओवरलॉक", "or": "ଓଭରଲକ"},
    "flatlock": {"en": "flatlock", "ta": "ஃபிளாட்லாக்", "ta_loc": "ஃபிளாட்லாக்கில்", "hi": "फ्लैटलॉक", "or": "ଫ୍ଲାଟଲକ"},
    "lockstitch": {"en": "lockstitch", "ta": "லாக்ஸ்டிட்ச்", "ta_loc": "லாக்ஸ்டிட்ச்சில்", "hi": "लॉकस्टिच", "or": "ଲକଷ୍ଟିଚ"},
}
_REF = {"en": "ref", "ta": "குறிப்பு", "hi": "संदर्भ", "or": "ସନ୍ଦର୍ଭ"}
# Tamil puts the skill in the locative case ("on overlock") in the skill-issued sentence.
_ISSUED_SKILL_FORM = {"en": "en", "ta": "ta_loc", "hi": "hi", "or": "or"}

_SKILL_ISSUED = {
    "en": "Independent on {skill}; pay band up next month",
    "ta": "{skill} சுயமாக வேலை செய்யும் நிலை; அடுத்த மாதம் ஊதிய நிலை உயரும்",
    "hi": "{skill} पर स्वतंत्र रूप से काम करने का स्तर; अगले महीने वेतन श्रेणी बढ़ेगी",
    "or": "{skill}ରେ ସ୍ୱାଧୀନ ଭାବେ କାମ କରିବା ସ୍ତର; ଆସନ୍ତା ମାସରେ ବେତନ ଶ୍ରେଣୀ ବଢ଼ିବ",
}
_SAFETY_ISSUED = {
    "en": "Machine guarding induction recorded; valid until {until}",
    "ta": "இயந்திரப் பாதுகாப்புப் பயிற்சி பதிவு; {until} வரை செல்லும்",
    "hi": "मशीन गार्डिंग प्रशिक्षण दर्ज; {until} तक मान्य",
    "or": "ମେସିନ ଗାର୍ଡିଂ ପ୍ରଶିକ୍ଷଣ ରେକର୍ଡ ହେଲା; {until} ପର୍ଯ୍ୟନ୍ତ ବୈଧ",
}
_REVOKED = {
    "en": "Your {skill} credential was withdrawn: {reason}. You can dispute this",
    "ta": "உங்கள் {skill} சான்று திரும்பப் பெறப்பட்டது: {reason}. நீங்கள் மறுப்பு தெரிவிக்கலாம்",
    "hi": "आपका {skill} प्रमाणपत्र वापस लिया गया: {reason}। आप आपत्ति कर सकते हैं",
    "or": "ଆପଣଙ୍କ {skill} ପ୍ରମାଣପତ୍ର ପ୍ରତ୍ୟାହାର ହେଲା: {reason}। ଆପଣ ଆପତ୍ତି କରିପାରିବେ",
}
_PRODUCTION = {
    "en": "{skill}: {pieces} pieces, {defects} defects",
    "ta": "{skill}: {pieces} துண்டுகள், {defects} குறைகள்",
    "hi": "{skill}: {pieces} पीस, {defects} खराब",
    "or": "{skill}: {pieces} ଖଣ୍ଡ, {defects} ତ୍ରୁଟି",
}


def skill_name(skill: str, form: str) -> str:
    """Return the skill's name in a language (or grammatical form), falling back to its key."""
    return _SKILL_NAMES.get(skill, {}).get(form) or skill


def _with_ref(lang: str, text: str, c: Ctx) -> str:
    return f"{text} · {_REF[lang]} {c['ref']}"


def issued_text(lang: str, c: Ctx) -> str:
    """Receipt for `credential.issued`: a skill level reached, or a safety induction recorded."""
    if c.get("kind") == "safety":
        text = _SAFETY_ISSUED[lang].format(until=c.get("valid_until", ""))
    else:
        text = _SKILL_ISSUED[lang].format(skill=skill_name(c.get("skill", ""), _ISSUED_SKILL_FORM[lang]))
    return _with_ref(lang, text, c)


def revoked_text(lang: str, c: Ctx) -> str:
    """Receipt for `credential.revoked`, with the reason and the right to dispute."""
    text = _REVOKED[lang].format(skill=skill_name(c.get("skill", ""), lang), reason=c.get("reason", ""))
    return _with_ref(lang, text, c)


def production_text(lang: str, c: Ctx) -> str:
    """Receipt for `production.count`: pieces and defects on an operation."""
    text = _PRODUCTION[lang].format(skill=skill_name(c.get("operation", ""), lang), pieces=c.get("pieces"),
                                    defects=c.get("defects"))
    return _with_ref(lang, text, c)


for _event, _render in ((events.CREDENTIAL_ISSUED, issued_text), (events.CREDENTIAL_REVOKED, revoked_text),
                        (events.PRODUCTION_COUNT, production_text)):
    i18n.register(_event, {lang: partial(_render, lang) for lang in i18n.LANGS})
