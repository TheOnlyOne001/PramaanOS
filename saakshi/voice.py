"""Voice: anonymous but verifiable worker feedback.

Blind RSA signatures in the style of Privacy Pass / RFC 9474 (the design doc's fallback to Semaphore):

1. Issue (identified). Each month the worker app blinds one random 32-byte message per topic and sends all
   of them at once to POST /api/voice/issue with the worker id. The issuer checks the worker is real,
   active and not a supervisor, and signs at most ONE blinded message per worker per topic per month with
   that (month, topic) RSA key. It records only (worker_id, topic, month): never the blinded value.
2. Report (anonymous). The app unblinds the signature and later sends (topic, month, token, signature, text)
   to the relay (POST /api/relay/voice/reports) with no worker id. The relay verifies the signature,
   derives nullifier = sha256(month|topic|m) and refuses a second use of the same token. Because the
   signature was blind, nobody — the issuer included, even with its private key — can link a report to an
   issuance (see tests/test_voice.py::test_unlinkable).
3. Threshold. A theme (topic, month) reaches the employer only once >= THRESHOLD distinct tokens were spent
   on it, and never on a site with fewer than MIN_GROUP enrolled workers. Safety-critical topics (safety,
   heat, harassment) escalate on the first report: safety officer, or the Internal Committee under the
   POSH Act for harassment.

Audio never reaches the server: speech is transcribed on the phone and only text is sent.
"""
from __future__ import annotations

import hashlib
import re
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config, db, state
from .ledger import now_ts
from .voice_client import blind, fdh, nullifier, to_hex, unblind, verify

router = APIRouter(prefix="/api")

THRESHOLD = 3
MIN_GROUP = 5
KEY_BITS = 2048
E = 65537
RELAY_NOTE = "demo relay run by the Saakshi team"

# id, safety_critical, labels
TOPICS: list[tuple[str, bool, dict]] = [
    ("water", False, {"en": "Drinking water", "ta": "குடிநீர்", "hi": "पीने का पानी", "or": "ପିଇବା ପାଣି"}),
    ("toilets", False, {"en": "Toilets", "ta": "கழிப்பறை", "hi": "शौचालय", "or": "ଶୌଚାଳୟ"}),
    ("heat", True, {"en": "Heat", "ta": "வெப்பம்", "hi": "गर्मी", "or": "ଗରମ"}),
    ("overtime", False, {"en": "Overtime", "ta": "கூடுதல் நேர வேலை", "hi": "ओवरटाइम", "or": "ଅତିରିକ୍ତ ସମୟ କାମ"}),
    ("pay", False, {"en": "Pay", "ta": "சம்பளம்", "hi": "वेतन", "or": "ଦରମା"}),
    ("harassment", True, {"en": "Harassment", "ta": "துன்புறுத்தல்", "hi": "उत्पीड़न", "or": "ଉତ୍ପୀଡ଼ନ"}),
    ("safety", True, {"en": "Safety", "ta": "பாதுகாப்பு", "hi": "सुरक्षा", "or": "ସୁରକ୍ଷା"}),
    ("food", False, {"en": "Food and canteen", "ta": "உணவு", "hi": "भोजन", "or": "ଖାଦ୍ୟ"}),
    ("transport", False, {"en": "Transport", "ta": "போக்குவரத்து", "hi": "परिवहन", "or": "ପରିବହନ"}),
    ("other", False, {"en": "Something else", "ta": "மற்றவை", "hi": "अन्य", "or": "ଅନ୍ୟ"}),
]
TOPIC_IDS = [t[0] for t in TOPICS]
LABELS = {t[0]: t[2] for t in TOPICS}
SAFETY = {t[0] for t in TOPICS if t[1]}

ROUTES = {
    "safety": {"to": "Safety officer", "note": "Safety reports skip the threshold and go straight to the safety officer."},
    "heat": {"to": "Safety officer", "note": "Heat stress is a safety issue: escalated on the first report."},
    "harassment": {
        "to": "Internal Committee (IC) under the POSH Act, 2013",
        "note": ("An anonymous report alerts the IC to act on a pattern, but it is not a formal complaint: a POSH "
                 "complaint needs a named complainant (in writing, within 3 months). The worker can approach the IC "
                 "directly, or the Local Committee at the District Officer."),
    },
}

MESSAGES = {
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

db.register_schema("""
-- One RSA issuer key per (month, topic).
CREATE TABLE IF NOT EXISTS voice_keys(
  month TEXT NOT NULL, topic TEXT NOT NULL, n_hex TEXT NOT NULL, e INTEGER NOT NULL, d_hex TEXT NOT NULL,
  PRIMARY KEY(month, topic));
-- Issuance: who got a token, never which blinded value (and no time, to avoid timing links).
CREATE TABLE IF NOT EXISTS voice_issuance(
  worker_id TEXT NOT NULL, topic TEXT NOT NULL, month TEXT NOT NULL, PRIMARY KEY(worker_id, topic, month));
-- Relay store: no worker id, IP, user agent or exact time (hour only).
CREATE TABLE IF NOT EXISTS voice_reports(
  nullifier TEXT PRIMARY KEY, topic TEXT NOT NULL, month TEXT NOT NULL, text TEXT NOT NULL, lang TEXT,
  hour TEXT NOT NULL, case_key_hash TEXT NOT NULL UNIQUE, token_hex TEXT NOT NULL, sig_hex TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_voice_reports_theme ON voice_reports(month, topic);
-- "You said, we did".
CREATE TABLE IF NOT EXISTS voice_responses(
  id INTEGER PRIMARY KEY, topic TEXT NOT NULL, month TEXT NOT NULL, text TEXT NOT NULL, by TEXT NOT NULL,
  ts TEXT NOT NULL, seq INTEGER);
""")


def current_month() -> str:
    return config.DEMO_DAY[:7]


def _hour(ts: str) -> str:
    """Round an ISO timestamp down to the hour (keeps the offset)."""
    return ts[:13] + ":00:00" + ts[19:]


def _st(st=None):
    return st or state.get()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# --- issuer keys ----------------------------------------------------------------------

_KEYGEN_CACHE: dict[tuple[str, str], tuple[int, int, int]] = {}  # process cache: RSA keygen is slow-ish


def _generate(month: str, topic: str) -> tuple[int, int, int]:
    if (month, topic) not in _KEYGEN_CACHE:
        from cryptography.hazmat.primitives.asymmetric import rsa
        k = rsa.generate_private_key(public_exponent=E, key_size=KEY_BITS)
        nums = k.private_numbers()
        _KEYGEN_CACHE[(month, topic)] = (nums.public_numbers.n, nums.public_numbers.e, nums.d)
    return _KEYGEN_CACHE[(month, topic)]


def key(month: str, topic: str, create: bool = True, st=None) -> dict | None:
    """{n, e, d} for (month, topic); generated lazily and persisted."""
    s = _st(st)
    with s.lock:
        r = s.conn.execute("SELECT * FROM voice_keys WHERE month=? AND topic=?", (month, topic)).fetchone()
        if r:
            return {"n": int(r["n_hex"], 16), "e": r["e"], "d": int(r["d_hex"], 16)}
        if not create:
            return None
        n, e, d = _generate(month, topic)
        s.conn.execute("INSERT INTO voice_keys(month, topic, n_hex, e, d_hex) VALUES (?,?,?,?,?)",
                       (month, topic, to_hex(n), e, to_hex(d)))
        return {"n": n, "e": e, "d": d}


def _check_topic(topic: str) -> None:
    if topic not in LABELS:
        raise HTTPException(422, f"unknown topic {topic!r}; topics are {', '.join(TOPIC_IDS)}")


def _check_month(month: str) -> None:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "month must look like 2026-10")


@router.get("/voice/topics")
def topics(month: str | None = None):
    month = month or current_month()
    _check_month(month)
    create = month == current_month()  # never mint keys for arbitrary months
    out = []
    for tid, safety, labels in TOPICS:
        k = key(month, tid, create=create)
        out.append({"id": tid, "label": labels, "safety_critical": safety,
                    "key": {"n_hex": to_hex(k["n"]), "e": k["e"]} if k else None})
    return {"month": month, "threshold": THRESHOLD, "min_group": MIN_GROUP, "topics": out}


# --- issue (identified) ------------------------------------------------------------------

def issue(worker_id: str, month: str, blinded: dict[str, str], st=None) -> dict:
    s = _st(st)
    w = s.conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not w:
        raise HTTPException(404, f"unknown worker {worker_id}")
    if not w["active"]:
        raise HTTPException(403, "worker is not active")
    if w["is_supervisor"]:
        raise HTTPException(403, "supervisors and managers do not get voice tokens")
    _check_month(month)
    if not blinded:
        raise HTTPException(422, "blinded must hold at least one topic")
    parsed = {}
    for tid, hx in blinded.items():
        _check_topic(tid)
        try:
            parsed[tid] = int(hx, 16)
        except (TypeError, ValueError):
            raise HTTPException(422, f"blinded[{tid}] is not hex")
    with s.lock:
        done = [r["topic"] for r in s.conn.execute(
            f"SELECT topic FROM voice_issuance WHERE worker_id=? AND month=? AND topic IN ({','.join('?' * len(parsed))})",
            (worker_id, month, *parsed)).fetchall()]
        if done:
            raise HTTPException(409, f"tokens already issued this month for: {', '.join(sorted(done))}")
        sigs = {}
        for tid, b in parsed.items():
            k = key(month, tid, st=s)
            if not (1 < b < k["n"]):
                raise HTTPException(422, f"blinded[{tid}] out of range")
            sigs[tid] = to_hex(pow(b, k["d"], k["n"]))
        s.conn.executemany("INSERT INTO voice_issuance(worker_id, topic, month) VALUES (?,?,?)",
                           [(worker_id, tid, month) for tid in parsed])
    return {"month": month, "signatures": sigs}


class IssueReq(BaseModel):
    worker_id: str
    month: str | None = None
    blinded: dict[str, str]


@router.post("/voice/issue")
def issue_route(req: IssueReq):
    month = req.month or current_month()
    if month != current_month():
        raise HTTPException(422, f"tokens are issued only for the current month ({current_month()})")
    return issue(req.worker_id, month, req.blinded)


# --- relay (anonymous) ---------------------------------------------------------------------
# The relay is meant to be run by a third party (a union, NGO or auditor) so the employer never sees
# network metadata. For the demo it is run by the Saakshi team in this same app. It takes no Request
# object, so it reads no IP or user agent; run it with access logging off. It stores no worker id and only
# the hour. Remaining leak, documented: the ledger's seq order puts the report between other events.

def _count(month: str, topic: str, s) -> int:
    return s.conn.execute("SELECT COUNT(*) FROM voice_reports WHERE month=? AND topic=?", (month, topic)).fetchone()[0]


def _status(topic: str, count: int) -> str:
    if count == 0:
        return "none"
    if topic in SAFETY:
        return "escalated"
    return "published" if count >= THRESHOLD else "waiting"


def _latest_response(month: str, topic: str, s) -> dict | None:
    r = s.conn.execute("SELECT * FROM voice_responses WHERE month=? AND topic=? ORDER BY id DESC LIMIT 1",
                       (month, topic)).fetchone()
    return {"text": r["text"], "by": r["by"], "ts": r["ts"], "seq": r["seq"]} if r else None


def submit_report(topic: str, month: str, token_hex: str, signature_hex: str, text: str, lang: str = "en",
                  ts: str | None = None, st=None) -> dict:
    s = _st(st)
    _check_topic(topic)
    _check_month(month)
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "text is empty")
    if len(text) > 2000:
        raise HTTPException(422, "text is too long (2000 characters max)")
    try:
        m = bytes.fromhex(token_hex)
        sig = int(signature_hex, 16)
    except (TypeError, ValueError):
        raise HTTPException(422, "token and signature must be hex")
    if len(m) != 32:
        raise HTTPException(422, "token must be 32 bytes")
    k = key(month, topic, create=False, st=s)
    if not k or not verify(month, topic, m, sig, k["n"], k["e"]):
        raise HTTPException(403, "token signature does not verify for this topic and month")
    nf = nullifier(month, topic, m)
    case_key = secrets.token_urlsafe(16)
    hour = _hour(ts or now_ts())
    with s.lock:
        if s.conn.execute("SELECT 1 FROM voice_reports WHERE nullifier=?", (nf,)).fetchone():
            raise HTTPException(409, "already spoken on this topic this month")
        s.conn.execute(
            "INSERT INTO voice_reports(nullifier, topic, month, text, lang, hour, case_key_hash, token_hex, sig_hex)"
            " VALUES (?,?,?,?,?,?,?,?,?)", (nf, topic, month, text, lang, hour, _sha(case_key), m.hex(), to_hex(sig)))
        # The ledger gets the fact, not the words: text may be identifying, the hash still pins it.
        ev = s.ledger.append("voice.report", {"topic": topic, "month": month, "nullifier": nf,
                                              "text_hash": _sha(text)},
                             worker_id=None, ts=hour, receipt=False)
        count = _count(month, topic, s)
    status = _status(topic, count)
    msg_key = "harassment" if topic == "harassment" else status
    msgs = MESSAGES[msg_key]
    out = {"case_key": case_key, "topic": topic, "month": month, "status": status, "corroborations": count,
           "threshold": THRESHOLD, "nullifier": nf, "seq": ev["seq"], "relay": RELAY_NOTE,
           "message": msgs.get(lang, msgs["en"]), "message_en": msgs["en"]}
    if topic in ROUTES:
        out["route_to"] = ROUTES[topic]
    return out


class ReportReq(BaseModel):
    topic: str
    month: str
    token: str
    signature: str
    text: str
    lang: str | None = "en"


@router.post("/relay/voice/reports")
def relay_report(req: ReportReq):
    return submit_report(req.topic, req.month, req.token, req.signature, req.text, req.lang or "en")


# --- scrub: suggestions that remove identifying details (no LLM) -------------------------------------

_WORDS = r"(?:woman|women|lady|ladies|girl|man|men|boy|female|male|one|person|worker|operator|checker|helper|" \
         r"tailor|[a-z]+\s+speaker|[a-z]+\s+(?:woman|man|girl|boy|worker))"
_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(?:i\s+am\s+|i'm\s+)?(?:the\s+)?only\s+" + _WORDS + r"\b", "[a worker]", "describes a group of one"),
    (r"\b(?i:(?:my\s+)?(?:supervisor|manager|in-?charge|boss|maistry|mestri)\s+(?:sir\s+|madam\s+)?)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
     "[a supervisor]", "names a supervisor"),
    (r"\b(?:my\s+|our\s+)?line\s*(?:no\.?|number|num|#)?\s*\d+\b", "[my line]", "names a line"),
    (r"\b(?:machine|table|seat|m/c)\s*(?:no\.?|number|#)?\s*\d+\b", "[my machine]", "names a machine"),
    (r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b", "[phone]", "phone number"),
    (r"\b\d{10}\b", "[phone]", "phone number"),
    (r"\b[WS]\d{3,}\b", "[id]", "employee id"),
    (r"\b(?:emp(?:loyee)?|staff|token|badge)\s*(?:id|no\.?|number|#)\s*[:#]?\s*\w+", "[id]", "employee id"),
]


def _name_patterns(s) -> list[tuple[str, str, str]]:
    out = []
    rows = s.conn.execute("SELECT name, is_supervisor, contractor FROM workers").fetchall()
    fulls, parts, contractors = [], [], set()
    for r in rows:
        repl = "[a supervisor]" if r["is_supervisor"] else "[a worker]"
        fulls.append((r["name"], repl))
        parts.extend((p, repl) for p in r["name"].split() if len(p) >= 3)
        if r["contractor"]:
            contractors.add(r["contractor"])
    for c in sorted(contractors, key=len, reverse=True):
        out.append((r"\b" + re.escape(c) + r"\b", "[a contractor]", "names a contractor"))
    for name, repl in sorted(fulls, key=lambda x: -len(x[0])) + parts:
        out.append((r"\b" + re.escape(name) + r"\b", repl, "names a person"))
    return out


def scrub(text: str, st=None) -> dict:
    s = _st(st)
    text = text or ""
    found = []  # (start, end, repl, reason)
    for pat, repl, reason in _PATTERNS + _name_patterns(s):
        flags = 0 if "[A-Z]" in pat else re.IGNORECASE
        for mt in re.finditer(pat, text, flags):
            if mt.end() > mt.start():
                found.append((mt.start(), mt.end(), repl, reason))
    # keep earliest, then longest; drop overlaps
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    chosen, last_end = [], -1
    for f in found:
        if f[0] >= last_end:
            chosen.append(f)
            last_end = f[1]
    pieces, pos = [], 0
    for a, b, repl, _ in chosen:
        pieces += [text[pos:a], repl]
        pos = b
    pieces.append(text[pos:])
    suggested = re.sub(r"\s{2,}", " ", "".join(pieces)).strip()
    return {"suggested": suggested, "changed": bool(chosen),
            "flags": [{"span": text[a:b], "start": a, "end": b, "reason": reason, "replacement": repl}
                      for a, b, repl, reason in chosen]}


class ScrubReq(BaseModel):
    text: str


@router.post("/voice/scrub")
def scrub_route(req: ScrubReq):
    """Stateless: nothing is stored or logged."""
    return scrub(req.text)


# --- themes, cases, responses ----------------------------------------------------------------------

def _enrolled(s) -> int:
    return s.conn.execute("SELECT COUNT(*) FROM workers WHERE active=1 AND is_supervisor=0").fetchone()[0]


def _theme(month: str, topic: str, s) -> dict:
    count = _count(month, topic, s)
    status = _status(topic, count)
    published = count >= THRESHOLD
    escalated = topic in SAFETY and count > 0
    t = {"topic": topic, "month": month, "label": LABELS[topic], "count": count, "threshold": THRESHOLD,
         "published": published, "escalated": escalated, "status": status, "safety_critical": topic in SAFETY,
         "response": _latest_response(month, topic, s)}
    if topic in ROUTES:
        t["route_to"] = ROUTES[topic]
    if published or escalated:
        t["reports"] = [{"text": r["text"], "ts": r["hour"], "lang": r["lang"]} for r in s.conn.execute(
            "SELECT text, hour, lang FROM voice_reports WHERE month=? AND topic=? ORDER BY hour, rowid",
            (month, topic)).fetchall()]
    else:
        t["note"] = "waiting for corroboration"
    return t


def themes(month: str | None = None, st=None) -> list[dict]:
    """Console view. Topics with at least one report this month; texts only once published or escalated."""
    s = _st(st)
    month = month or current_month()
    if _enrolled(s) < MIN_GROUP:
        return []  # group-size guard: too few workers to stay anonymous
    used = {r[0] for r in s.conn.execute("SELECT DISTINCT topic FROM voice_reports WHERE month=?", (month,))}
    return [_theme(month, tid, s) for tid in TOPIC_IDS if tid in used]


@router.get("/voice/themes")
def themes_route(month: str | None = None):
    if month:
        _check_month(month)
    return themes(month)


@router.get("/voice/cases/{case_key}")
def case(case_key: str):
    s = state.get()
    r = s.conn.execute("SELECT topic, month FROM voice_reports WHERE case_key_hash=?", (_sha(case_key),)).fetchone()
    if not r:
        raise HTTPException(404, "unknown case key")
    count = _count(r["month"], r["topic"], s)
    out = {"case_key": case_key, "topic": r["topic"], "month": r["month"], "label": LABELS[r["topic"]],
           "status": _status(r["topic"], count), "corroborations": count, "threshold": THRESHOLD,
           "response": _latest_response(r["month"], r["topic"], s)}
    if r["topic"] in ROUTES:
        out["route_to"] = ROUTES[r["topic"]]
    return out


def _board_entry(row, s) -> dict:
    first = s.conn.execute("SELECT text FROM voice_reports WHERE month=? AND topic=? ORDER BY hour, rowid LIMIT 1",
                           (row["month"], row["topic"])).fetchone()
    return {"topic": row["topic"], "month": row["month"], "label": LABELS[row["topic"]],
            "count": _count(row["month"], row["topic"], s),
            "you_said": first["text"] if first else LABELS[row["topic"]]["en"],
            "we_did": row["text"], "by": row["by"], "ts": row["ts"], "seq": row["seq"]}


def respond(topic: str, text: str, by: str, month: str | None = None, ts: str | None = None, st=None) -> dict:
    s = _st(st)
    _check_topic(topic)
    month = month or current_month()
    text, by = (text or "").strip(), (by or "").strip()
    if not text or not by:
        raise HTTPException(422, "text and by are required")
    with s.lock:
        th = _theme(month, topic, s)
        if not (th["published"] or th["escalated"]):
            raise HTTPException(409, "this theme has not reached management yet")
        ts = ts or now_ts()
        ev = s.ledger.append("voice.response", {"topic": topic, "month": month, "text": text, "by": by},
                             worker_id=None, ts=ts, receipt=False)
        cur = s.conn.execute("INSERT INTO voice_responses(topic, month, text, by, ts, seq) VALUES (?,?,?,?,?,?)",
                             (topic, month, text, by, ts, ev["seq"]))
        row = s.conn.execute("SELECT * FROM voice_responses WHERE id=?", (cur.lastrowid,)).fetchone()
        return _board_entry(row, s)


class RespondReq(BaseModel):
    text: str
    by: str


@router.post("/voice/themes/{topic}/respond")
def respond_route(topic: str, req: RespondReq):
    return respond(topic, req.text, req.by)


def board(st=None) -> list[dict]:
    """"You said, we did": newest first."""
    s = _st(st)
    rows = s.conn.execute("SELECT * FROM voice_responses ORDER BY ts DESC, id DESC").fetchall()
    return [_board_entry(r, s) for r in rows]


@router.get("/voice/board")
def board_route():
    return board()


# --- demo seed -----------------------------------------------------------------------------------

SEED_MONTH = "2026-09"
SEED_REPORTS = [
    ("W002", "Toilets on our floor are not cleaned after the lunch break", "ta", "2026-09-08T14:00:00+05:30"),
    ("W005", "No water or soap in the ladies toilet by the afternoon", "ta", "2026-09-09T16:00:00+05:30"),
    ("W007", "Toilet near the packing area is dirty for the whole second shift", "ta", "2026-09-11T17:00:00+05:30"),
    ("W008", "Ladies toilet not cleaned for two days, we hold it till we go home", "hi", "2026-09-12T13:00:00+05:30"),
]
SEED_RESPONSE = ("Two more cleaning shifts added; cleaning log posted at the door", "HR and Admin Manager",
                 "2026-09-19T11:00:00+05:30")


def seed_demo(st) -> None:
    """Previous month: a published "toilets" theme with 4 reports and a management answer, made with the real
    blind-issue / unblind / relay flow. Nothing for the current month (the live demo creates "water")."""
    if st.conn.execute("SELECT 1 FROM voice_responses LIMIT 1").fetchone():
        return
    month = SEED_MONTH
    for wid, text, lang, ts in SEED_REPORTS:
        held, blinded = {}, {}
        for tid in TOPIC_IDS:  # every topic at once, as the app does
            k = key(month, tid, st=st)
            m = secrets.token_bytes(32)
            b, r = blind(month, tid, m, k["n"], k["e"])
            held[tid], blinded[tid] = (m, r), to_hex(b)
        sigs = issue(wid, month, blinded, st=st)["signatures"]
        k = key(month, "toilets", st=st)
        m, r = held["toilets"]
        s = unblind(int(sigs["toilets"], 16), r, k["n"])
        submit_report("toilets", month, m.hex(), to_hex(s), text, lang, ts=ts, st=st)
    respond("toilets", SEED_RESPONSE[0], SEED_RESPONSE[1], month=month, ts=SEED_RESPONSE[2], st=st)


__all__ = ["router", "themes", "board", "seed_demo", "scrub", "issue", "submit_report", "respond", "key",
           "fdh", "TOPIC_IDS", "THRESHOLD"]
