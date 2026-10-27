"""Voice topics: the fixed topic list, labels, safety flags, thresholds, routes, worker-facing messages, validation."""
from __future__ import annotations

import re
from typing import Literal, NamedTuple, TypedDict

from fastapi import HTTPException

from .. import config

THRESHOLD = 3
"""Distinct tokens a theme needs before it reaches the employer."""
MIN_GROUP = 5
"""Fewest enrolled workers a site needs before any theme is shown (group-size guard)."""
MAX_REPORT_CHARS = 2000
"""Longest report text the relay accepts."""
RELAY_NOTE = "demo relay run by the Saakshi team"

Labels = dict[str, str]
"""Language code -> label."""
Status = Literal["none", "waiting", "published", "escalated"]


class Topic(NamedTuple):
    """One voice topic: id, whether it escalates on the first report, and its labels."""

    id: str
    safety_critical: bool
    labels: Labels


class Route(TypedDict):
    """Who a safety-critical topic escalates to, and why."""

    to: str
    note: str


TOPICS: list[Topic] = [
    Topic("water", False, {"en": "Drinking water", "ta": "குடிநீர்", "hi": "पीने का पानी", "or": "ପିଇବା ପାଣି"}),
    Topic("toilets", False, {"en": "Toilets", "ta": "கழிப்பறை", "hi": "शौचालय", "or": "ଶୌଚାଳୟ"}),
    Topic("heat", True, {"en": "Heat", "ta": "வெப்பம்", "hi": "गर्मी", "or": "ଗରମ"}),
    Topic("overtime", False, {"en": "Overtime", "ta": "கூடுதல் நேர வேலை", "hi": "ओवरटाइम", "or": "ଅତିରିକ୍ତ ସମୟ କାମ"}),
    Topic("pay", False, {"en": "Pay", "ta": "சம்பளம்", "hi": "वेतन", "or": "ଦରମା"}),
    Topic("harassment", True, {"en": "Harassment", "ta": "துன்புறுத்தல்", "hi": "उत्पीड़न", "or": "ଉତ୍ପୀଡ଼ନ"}),
    Topic("safety", True, {"en": "Safety", "ta": "பாதுகாப்பு", "hi": "सुरक्षा", "or": "ସୁରକ୍ଷା"}),
    Topic("food", False, {"en": "Food and canteen", "ta": "உணவு", "hi": "भोजन", "or": "ଖାଦ୍ୟ"}),
    Topic("transport", False, {"en": "Transport", "ta": "போக்குவரத்து", "hi": "परिवहन", "or": "ପରିବହନ"}),
    Topic("other", False, {"en": "Something else", "ta": "மற்றவை", "hi": "अन्य", "or": "ଅନ୍ୟ"}),
]
TOPIC_IDS: list[str] = [t.id for t in TOPICS]
LABELS: dict[str, Labels] = {t.id: t.labels for t in TOPICS}
SAFETY: set[str] = {t.id for t in TOPICS if t.safety_critical}

ROUTES: dict[str, Route] = {
    "safety": {"to": "Safety officer", "note": "Safety reports skip the threshold and go straight to the safety officer."},
    "heat": {"to": "Safety officer", "note": "Heat stress is a safety issue: escalated on the first report."},
    "harassment": {
        "to": "Internal Committee (IC) under the POSH Act, 2013",
        "note": ("An anonymous report alerts the IC to act on a pattern, but it is not a formal complaint: a POSH "
                 "complaint needs a named complainant (in writing, within 3 months). The worker can approach the IC "
                 "directly, or the Local Committee at the District Officer."),
    },
}

MESSAGES: dict[str, Labels] = {
    "waiting": {
        "en": "Received. It stays hidden until at least 3 workers raise the same issue this month.",
        "ta": "பெறப்பட்டது. இந்த மாதம் குறைந்தது 3 பேர் இதே பிரச்சினையைச் சொல்லும் வரை இது மறைவாக இருக்கும்.",
        "hi": "मिल गया। इस महीने कम से कम 3 कामगार यही बात कहें, तब तक यह छिपा रहेगा।",
        "or": "ମିଳିଲା। ଏହି ମାସରେ ଅନ୍ତତଃ 3 ଜଣ ଶ୍ରମିକ ସମାନ କଥା କହିବା ପର୍ଯ୍ୟନ୍ତ ଏହା ଲୁଚି ରହିବ।",
    },
    "published": {
        "en": "Received. Enough workers raised this, so it now reaches management as a group issue, never with your name.",
        "ta": "பெறப்பட்டது. போதுமான பேர் இதைச் சொன்னதால், இது இப்போது குழு பிரச்சினையாக நிர்வாகத்திடம் செல்கிறது — உங்கள் பெயர் இல்லாமல்.",
        "hi": "मिल गया। काफ़ी कामगारों ने यह बताया, इसलिए अब यह समूह की बात के रूप में प्रबंधन तक जाता है — आपके नाम के बिना।",
        "or": "ମିଳିଲା। ଯଥେଷ୍ଟ ଶ୍ରମିକ ଏହା କହିଥିବାରୁ ଏହା ଏବେ ଦଳଗତ ସମସ୍ୟା ଭାବେ ପରିଚାଳନା ପାଖକୁ ଯାଉଛି — ଆପଣଙ୍କ ନାମ ବିନା।",
    },
    "escalated": {
        "en": "Received. Safety reports go straight to the safety officer, without waiting for others.",
        "ta": "பெறப்பட்டது. பாதுகாப்பு புகார்கள் மற்றவர்களுக்காகக் காத்திருக்காமல் நேரடியாகப் பாதுகாப்பு அலுவலருக்குச் செல்லும்.",
        "hi": "मिल गया। सुरक्षा की शिकायत दूसरों का इंतज़ार किए बिना सीधे सुरक्षा अधिकारी को जाती है।",
        "or": "ମିଳିଲା। ସୁରକ୍ଷା ଅଭିଯୋଗ ଅନ୍ୟମାନଙ୍କୁ ଅପେକ୍ଷା ନକରି ସିଧା ସୁରକ୍ଷା ଅଧିକାରୀଙ୍କ ପାଖକୁ ଯାଏ।",
    },
    "harassment": {
        "en": ("Received. This goes straight to the Internal Committee (POSH Act). An anonymous report alerts the "
               "committee, but a formal complaint needs your name: you can approach the committee directly when you are ready."),
        "ta": ("பெறப்பட்டது. இது நேரடியாக உள் குழுவிற்கு (POSH சட்டம்) செல்கிறது. பெயரில்லா புகார் குழுவை எச்சரிக்கும்; "
               "முறையான புகாருக்கு உங்கள் பெயர் தேவை — நீங்கள் தயாரானதும் குழுவை நேரடியாக அணுகலாம்."),
        "hi": ("मिल गया। यह सीधे आंतरिक समिति (POSH क़ानून) को जाता है। गुमनाम रिपोर्ट समिति को सचेत करती है, पर औपचारिक "
               "शिकायत के लिए आपका नाम चाहिए — जब तैयार हों, आप सीधे समिति से मिल सकती हैं।"),
        "or": ("ମିଳିଲା। ଏହା ସିଧା ଆଭ୍ୟନ୍ତରୀଣ କମିଟି (POSH ଆଇନ) ପାଖକୁ ଯାଏ। ଅଜ୍ଞାତ ରିପୋର୍ଟ କମିଟିକୁ ସତର୍କ କରେ, କିନ୍ତୁ ଆନୁଷ୍ଠାନିକ "
               "ଅଭିଯୋଗ ପାଇଁ ଆପଣଙ୍କ ନାମ ଦରକାର — ପ୍ରସ୍ତୁତ ହେଲେ ସିଧା କମିଟିକୁ ଯାଇପାରିବେ।"),
    },
}

_MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def current_month() -> str:
    """Return the demo's current month as YYYY-MM."""
    return config.DEMO_DAY[:7]


def check_topic(topic: str) -> None:
    """Raise 422 unless topic is one of TOPIC_IDS."""
    if topic not in LABELS:
        raise HTTPException(422, f"unknown topic {topic!r}; topics are {', '.join(TOPIC_IDS)}")


def check_month(month: str | None) -> None:
    """Raise 422 unless month looks like YYYY-MM."""
    if not _MONTH_RE.fullmatch(month or ""):
        raise HTTPException(422, "month must look like 2026-10")


def status(topic: str, count: int) -> Status:
    """Theme status for count reports: safety topics escalate at once, others publish at THRESHOLD."""
    if count == 0:
        return "none"
    if topic in SAFETY:
        return "escalated"
    return "published" if count >= THRESHOLD else "waiting"


def message(topic: str, report_status: Status, lang: str) -> tuple[str, str]:
    """Return the (localised, English) acknowledgement a worker sees after reporting."""
    msgs = MESSAGES["harassment" if topic == "harassment" else report_status]
    return msgs.get(lang, msgs["en"]), msgs["en"]
