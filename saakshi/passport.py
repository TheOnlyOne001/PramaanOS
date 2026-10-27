"""Skill passport: credentials earned from signed production records.

Progress is computed from `production.count` ledger events only (never from
a side table), so anything the passport claims can be traced to signed seqs.
When the rules below are met, the site issuer signs a W3C-VC-2.0-shaped
credential (Ed25519 over canonical JSON of the VC without `proof`).

No floats anywhere in a VC: numbers are ints or strings, so the browser's
canonical JSON is byte-identical to Python's and the verify page works offline.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import statistics
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from . import config, db, i18n, state
from .crypto import canonical, sha256_hex, verify_sig
from .ledger import now_ts

router = APIRouter(prefix="/api")

# --- Rules table (versioned) ---------------------------------------------------

RULES_VERSION = "TUP-03/skills/2026-10-v1"
NSQF_SMO = "AMH/Q0301 (Sewing Machine Operator) — illustrative"

LEVELS = ["I", "L", "U", "O"]  # ILUO skill matrix
LEVEL_LABELS = {"I": "In training", "L": "Works with supervision", "U": "Works independently", "O": "Can train others"}
EVIDENCE_LABELS = {1: "Self-declared", 2: "Employer-attested", 3: "System-evidenced", 4: "Independently assessed"}
EVIDENCE_EXPLAIN = {
    1: "The worker said so; nobody has checked.",
    2: "The employer's HR record says so (a supervisor vouched for it).",
    3: "Computed from signed, tamper-evident production records on the shop floor.",
    4: "Tested by an outside assessor.",
}

# skill -> rule. Efficiency and defect thresholds are exact fractions (no float drift).
SKILL_RULES = {
    "overlock": {"label": "Overlock", "level": "U", "evidence_level": 3, "min_days": 5,
                 "min_efficiency": (70, 100), "max_defect_rate": (25, 1000), "nsqf": NSQF_SMO},
    "flatlock": {"label": "Flatlock", "level": "U", "evidence_level": 3, "min_days": 5,
                 "min_efficiency": (70, 100), "max_defect_rate": (25, 1000), "nsqf": NSQF_SMO},
    "lockstitch": {"label": "Lockstitch", "level": "U", "evidence_level": 3, "min_days": 5,
                   "min_efficiency": (70, 100), "max_defect_rate": (25, 1000), "nsqf": NSQF_SMO},
}

SAFETY_CREDENTIALS = {
    "machine_guarding_induction": {"label": "Machine guarding induction", "valid_days": 180},
}

ISSUER_KEY = "site-issuer"
VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"

db.register_schema("""
CREATE TABLE IF NOT EXISTS passport_credentials(
  id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, kind TEXT NOT NULL, skill TEXT NOT NULL, level TEXT,
  vc TEXT NOT NULL, vc_hash TEXT NOT NULL, status_index INTEGER NOT NULL UNIQUE,
  issued_at TEXT NOT NULL, valid_until TEXT, seq INTEGER,
  revoked INTEGER NOT NULL DEFAULT 0, revoked_reason TEXT, revoked_at TEXT);
CREATE INDEX IF NOT EXISTS ix_passport_worker ON passport_credentials(worker_id);
""")

# --- Receipts --------------------------------------------------------------------

_SKILL_NAMES = {
    "overlock": {"en": "overlock", "ta": "ஓவர்லாக்", "ta_loc": "ஓவர்லாக்கில்", "hi": "ओवरलॉक", "or": "ଓଭରଲକ"},
    "flatlock": {"en": "flatlock", "ta": "ஃபிளாட்லாக்", "ta_loc": "ஃபிளாட்லாக்கில்", "hi": "फ्लैटलॉक", "or": "ଫ୍ଲାଟଲକ"},
    "lockstitch": {"en": "lockstitch", "ta": "லாக்ஸ்டிட்ச்", "ta_loc": "லாக்ஸ்டிட்ச்சில்", "hi": "लॉकस्टिच", "or": "ଲକଷ୍ଟିଚ"},
}


def _sn(skill: str, lang: str) -> str:
    return _SKILL_NAMES.get(skill, {}).get(lang) or skill


def _issued(lang: str):
    def fn(c: dict) -> str:
        ref, skill = c["ref"], c.get("skill", "")
        if c.get("kind") == "safety":
            until = c.get("valid_until", "")
            return {
                "en": f"Machine guarding induction recorded; valid until {until} · ref {ref}",
                "ta": f"இயந்திரப் பாதுகாப்புப் பயிற்சி பதிவு; {until} வரை செல்லும் · குறிப்பு {ref}",
                "hi": f"मशीन गार्डिंग प्रशिक्षण दर्ज; {until} तक मान्य · संदर्भ {ref}",
                "or": f"ମେସିନ ଗାର୍ଡିଂ ପ୍ରଶିକ୍ଷଣ ରେକର୍ଡ ହେଲା; {until} ପର୍ଯ୍ୟନ୍ତ ବୈଧ · ସନ୍ଦର୍ଭ {ref}",
            }[lang]
        return {
            "en": f"Independent on {_sn(skill, 'en')}; pay band up next month · ref {ref}",
            "ta": f"{_SKILL_NAMES.get(skill, {}).get('ta_loc', skill)} சுயமாக வேலை செய்யும் நிலை; "
                  f"அடுத்த மாதம் ஊதிய நிலை உயரும் · குறிப்பு {ref}",
            "hi": f"{_sn(skill, 'hi')} पर स्वतंत्र रूप से काम करने का स्तर; अगले महीने वेतन श्रेणी बढ़ेगी · संदर्भ {ref}",
            "or": f"{_sn(skill, 'or')}ରେ ସ୍ୱାଧୀନ ଭାବେ କାମ କରିବା ସ୍ତର; ଆସନ୍ତା ମାସରେ ବେତନ ଶ୍ରେଣୀ ବଢ଼ିବ · ସନ୍ଦର୍ଭ {ref}",
        }[lang]
    return fn


i18n.register("credential.issued", {lang: _issued(lang) for lang in i18n.LANGS})
i18n.register("credential.revoked", {
    "en": lambda c: f"Your {_sn(c.get('skill', ''), 'en')} credential was withdrawn: {c.get('reason', '')}. "
                    f"You can dispute this · ref {c['ref']}",
    "ta": lambda c: f"உங்கள் {_sn(c.get('skill', ''), 'ta')} சான்று திரும்பப் பெறப்பட்டது: {c.get('reason', '')}. "
                    f"நீங்கள் மறுப்பு தெரிவிக்கலாம் · குறிப்பு {c['ref']}",
    "hi": lambda c: f"आपका {_sn(c.get('skill', ''), 'hi')} प्रमाणपत्र वापस लिया गया: {c.get('reason', '')}। "
                    f"आप आपत्ति कर सकते हैं · संदर्भ {c['ref']}",
    "or": lambda c: f"ଆପଣଙ୍କ {_sn(c.get('skill', ''), 'or')} ପ୍ରମାଣପତ୍ର ପ୍ରତ୍ୟାହାର ହେଲା: {c.get('reason', '')}। "
                    f"ଆପଣ ଆପତ୍ତି କରିପାରିବେ · ସନ୍ଦର୍ଭ {c['ref']}",
})
i18n.register("production.count", {
    "en": lambda c: f"{_sn(c.get('operation', ''), 'en')}: {c.get('pieces')} pieces, {c.get('defects')} defects · ref {c['ref']}",
    "ta": lambda c: f"{_sn(c.get('operation', ''), 'ta')}: {c.get('pieces')} துண்டுகள், {c.get('defects')} குறைகள் · குறிப்பு {c['ref']}",
    "hi": lambda c: f"{_sn(c.get('operation', ''), 'hi')}: {c.get('pieces')} पीस, {c.get('defects')} खराब · संदर्भ {c['ref']}",
    "or": lambda c: f"{_sn(c.get('operation', ''), 'or')}: {c.get('pieces')} ଖଣ୍ଡ, {c.get('defects')} ତ୍ରୁଟି · ସନ୍ଦର୍ଭ {c['ref']}",
})

# --- Helpers ---------------------------------------------------------------------


def _worker(wid: str) -> dict:
    r = state.get().conn.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone()
    if not r:
        raise HTTPException(404, f"unknown worker {wid}")
    return dict(r)


def subject_id(wid: str) -> str:
    """Pseudonymous, stable per site: the employer ID never appears in the VC."""
    return "urn:saakshi:worker:" + hashlib.sha256(f"{config.SITE_ID}|{wid}".encode()).hexdigest()[:16]


def issuer() -> dict:
    """Return the site issuer's id, name and public key."""
    pub = state.get().keys.public_hex(ISSUER_KEY)
    return {"id": f"did:key:site-issuer:{pub[:16]}", "name": config.SITE_NAME, "public_key_hex": pub}


def b64url(data: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    """Decode unpadded URL-safe base64 to bytes."""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def vc_signing_bytes(vc: dict) -> bytes:
    """Return the canonical bytes of a credential, excluding its proof, for signing."""
    return canonical({k: v for k, v in vc.items() if k != "proof"})


def verify_vc(vc: dict, public_key_hex: str | None = None) -> bool:
    """Python reference verifier (the browser does the same in web/verify/verify.js)."""
    pub = public_key_hex or issuer()["public_key_hex"]
    proof = vc.get("proof") or {}
    return verify_sig(pub, vc_signing_bytes(vc), proof.get("proofValue", ""))


def _day_stats(evs: list[dict]) -> dict:
    pieces = sum(int(e["payload"]["pieces"]) for e in evs)
    std_minutes = sum(float(e["payload"]["pieces"]) * float(e["payload"]["sam"]) for e in evs)
    minutes = sum(float(e["payload"]["minutes"]) for e in evs)
    defects = sum(int(e["payload"]["defects"]) for e in evs)
    eff = std_minutes / minutes if minutes else 0.0
    dr = defects / pieces if pieces else 1.0
    return {"pieces": pieces, "defects": defects, "efficiency": eff, "defect_rate": dr,
            "seqs": [e["seq"] for e in evs]}


def _qualifies(stats: dict, rule: dict) -> bool:
    n, d = rule["min_efficiency"]
    mn, md = rule["max_defect_rate"]
    # exact comparisons in integer arithmetic where possible
    return stats["efficiency"] * d >= n - 1e-9 and stats["defects"] * md <= mn * stats["pieces"]


def _excluded_seqs(wid: str, skill: str) -> set[int]:
    """Evidence already used by a credential revoked for fraud never counts again."""
    out: set[int] = set()
    for r in state.get().conn.execute(
            "SELECT vc FROM passport_credentials WHERE worker_id=? AND skill=? AND revoked=1", (wid, skill)):
        out.update(json.loads(r["vc"])["credentialSubject"].get("evidence", {}).get("ledgerSeqs", []))
    return out


def skill_progress(wid: str, skill: str) -> dict:
    """Return a worker's progress toward the criteria for a skill credential."""
    rule = SKILL_RULES[skill]
    excluded = _excluded_seqs(wid, skill)
    evs = [e for e in state.get().ledger.events(worker_id=wid, type="production.count")
           if e["payload"].get("operation") == skill and e["seq"] not in excluded]
    by_day: dict[str, list[dict]] = {}
    for e in evs:
        by_day.setdefault(e["day"], []).append(e)
    days = []
    for day in sorted(by_day):
        s = _day_stats(by_day[day])
        days.append({"day": day, "efficiency": round(s["efficiency"], 3), "defect_rate": round(s["defect_rate"], 4),
                     "pieces": s["pieces"], "defects": s["defects"], "qualifies": _qualifies(s, rule),
                     "seqs": s["seqs"], "_s": s})
    q = [d for d in days if d["qualifies"]]
    out_days = [{k: v for k, v in d.items() if k != "_s"} for d in days]
    return {
        "skill": skill, "label": rule["label"], "level": rule["level"], "level_label": LEVEL_LABELS[rule["level"]],
        "evidence_level": rule["evidence_level"], "rules_version": RULES_VERSION,
        "criteria": {"min_days": rule["min_days"],
                     "min_efficiency": rule["min_efficiency"][0] / rule["min_efficiency"][1],
                     "max_defect_rate": rule["max_defect_rate"][0] / rule["max_defect_rate"][1],
                     "text": f"{rule['min_days']} shift days at ≥{rule['min_efficiency'][0]}% efficiency"
                             f" and ≤{rule['max_defect_rate'][0] / 10:g}% defects"},
        "current": {"days": len(days), "qualifying_days": [d["day"] for d in q],
                    "median_efficiency": round(statistics.median([d["_s"]["efficiency"] for d in q]), 3) if q else None,
                    "max_defect_rate": round(max(d["_s"]["defect_rate"] for d in q), 4) if q else None,
                    "by_day": out_days},
        "met": len(q) >= rule["min_days"], "days_needed": rule["min_days"], "days_met": len(q),
        "_qualifying": q,
    }


def _clean(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _next_status_index(conn) -> int:
    r = conn.execute("SELECT MAX(status_index) FROM passport_credentials").fetchone()[0]
    return 0 if r is None else r + 1


def _status_entry(idx: int) -> dict:
    return {"id": f"urn:saakshi:status:{config.SITE_ID}#{idx}", "type": "BitstringStatusListEntry",
            "statusPurpose": "revocation", "statusListIndex": str(idx),
            "statusListCredential": "/api/passport/status"}


def _store_and_announce(st, wid: str, vc: dict, kind: str, skill: str, level: str | None, ts: str,
                        valid_until: str | None, idx: int) -> dict:
    vc_hash = sha256_hex(canonical(vc))
    st.conn.execute(
        "INSERT INTO passport_credentials(id, worker_id, kind, skill, level, vc, vc_hash, status_index, issued_at,"
        " valid_until) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (vc["id"], wid, kind, skill, level, json.dumps(vc, ensure_ascii=False), vc_hash, idx, ts, valid_until))
    payload = {"credential_id": vc["id"], "skill": skill, "level": level, "vc_hash": vc_hash, "kind": kind}
    if valid_until:
        payload["valid_until"] = valid_until
    ev = st.ledger.append("credential.issued", payload, worker_id=wid, ts=ts)
    st.conn.execute("UPDATE passport_credentials SET seq=? WHERE id=?", (ev["seq"], vc["id"]))
    return ev


def _sign(vc: dict, ts: str) -> dict:
    st = state.get()
    iss = issuer()
    sig = st.keys.sign(ISSUER_KEY, vc_signing_bytes(vc))
    vc["proof"] = {"type": "Ed25519Signature2020", "verificationMethod": f"{iss['id']}#key-1", "created": ts,
                   "proofPurpose": "assertionMethod", "proofValue": sig}
    return vc


def issue_skill(wid: str, skill: str, ts: str | None = None) -> dict:
    """Issue the skill credential from current ledger evidence. Caller checks `met` first."""
    st = state.get()
    w = _worker(wid)
    rule = SKILL_RULES[skill]
    prog = skill_progress(wid, skill)
    q = prog["_qualifying"]
    ts = ts or now_ts()
    iss = issuer()
    with st.lock:
        idx = _next_status_index(st.conn)
        vc = {
            "@context": [VC_CONTEXT],
            "type": ["VerifiableCredential", "SkillCredential"],
            "id": f"urn:saakshi:cred:{uuid.uuid4()}",
            "issuer": {"id": iss["id"], "name": iss["name"]},
            "validFrom": ts,
            "credentialSubject": {
                "id": subject_id(wid), "name": w["name"], "skill": skill, "skillLabel": rule["label"],
                "level": rule["level"], "levelLabel": LEVEL_LABELS[rule["level"]],
                "evidenceLevel": rule["evidence_level"], "evidenceLabel": EVIDENCE_LABELS[rule["evidence_level"]],
                "nsqf": rule["nsqf"],
                "evidence": {
                    "days": len(q),
                    "medianEfficiency": f"{statistics.median(d['_s']['efficiency'] for d in q):.2f}",
                    "maxDefectRate": f"{max(d['_s']['defect_rate'] for d in q):.3f}",
                    "criteria": prog["criteria"]["text"],
                    "rulesVersion": RULES_VERSION,
                    "ledgerSeqs": [s for d in q for s in d["seqs"]],
                },
            },
            "credentialStatus": _status_entry(idx),
        }
        _sign(vc, ts)
        ev = _store_and_announce(st, wid, vc, "skill", skill, rule["level"], ts, None, idx)
    return {"credential": vc, "event": ev}


def issue_safety(wid: str, cred: str = "machine_guarding_induction", valid_from: str | None = None,
                 valid_until: str | None = None, ts: str | None = None) -> dict:
    """Expiring safety credential (e.g. machine guarding induction).

    valid_from is the training date; ts is when it was recorded (e.g. imported from the training register).
    """
    st = state.get()
    w = _worker(wid)
    spec = SAFETY_CREDENTIALS[cred]
    rec_ts = ts or now_ts()
    ts = valid_from or rec_ts
    valid_until = valid_until or (date.fromisoformat(ts[:10]) + timedelta(days=spec["valid_days"])).isoformat()
    iss = issuer()
    with st.lock:
        idx = _next_status_index(st.conn)
        vc = {
            "@context": [VC_CONTEXT],
            "type": ["VerifiableCredential", "SafetyTrainingCredential"],
            "id": f"urn:saakshi:cred:{uuid.uuid4()}",
            "issuer": {"id": iss["id"], "name": iss["name"]},
            "validFrom": ts,
            "validUntil": f"{valid_until}T23:59:59{config.TZ}",
            "credentialSubject": {
                "id": subject_id(wid), "name": w["name"], "skill": cred, "skillLabel": spec["label"],
                "evidenceLevel": 2, "evidenceLabel": EVIDENCE_LABELS[2],
            },
            "credentialStatus": _status_entry(idx),
        }
        _sign(vc, rec_ts)
        ev = _store_and_announce(st, wid, vc, "safety", cred, None, rec_ts, valid_until, idx)
    return {"credential": vc, "event": ev}


def _holds(wid: str, skill: str, level: str) -> bool:
    rows = state.get().conn.execute(
        "SELECT level FROM passport_credentials WHERE worker_id=? AND skill=? AND revoked=0", (wid, skill)).fetchall()
    return any(r["level"] and LEVELS.index(r["level"]) >= LEVELS.index(level) for r in rows)


def check_and_issue(wid: str, skill: str, ts: str | None = None) -> dict | None:
    """Issue if the rule is met and the worker doesn't already hold it. Returns the VC or None."""
    if skill not in SKILL_RULES:
        return None
    st = state.get()
    with st.lock:
        if _holds(wid, skill, SKILL_RULES[skill]["level"]):
            return None
        if not skill_progress(wid, skill)["met"]:
            return None
        return issue_skill(wid, skill, ts=ts)["credential"]


def _cred_rows(wid: str | None = None):
    q, a = "SELECT * FROM passport_credentials", []
    if wid:
        q += " WHERE worker_id=?"
        a.append(wid)
    return state.get().conn.execute(q + " ORDER BY status_index", a).fetchall()


def _today() -> str:
    return config.DEMO_DAY


def _status_of(r) -> dict:
    expired = bool(r["valid_until"] and r["valid_until"] < _today())
    return {"revoked": bool(r["revoked"]), "revoked_reason": r["revoked_reason"], "expired": expired,
            "valid_until": r["valid_until"], "status_index": r["status_index"], "seq": r["seq"]}


def get_credential(cid: str) -> dict | None:
    """Return the credential row by id or id suffix, or None if not found."""
    conn = state.get().conn
    r = conn.execute("SELECT * FROM passport_credentials WHERE id=?", (cid,)).fetchone()
    if not r:
        r = conn.execute("SELECT * FROM passport_credentials WHERE id LIKE ?", ("%" + cid,)).fetchone()
    return r


# --- Console-facing functions ----------------------------------------------------


def passport(wid: str) -> dict:
    """Return a worker's skill passport with credentials and skill progress."""
    w = _worker(wid)
    rows = _cred_rows(wid)
    skills = set(SKILL_RULES) & ({w["operation"]} | {
        e["payload"].get("operation") for e in state.get().ledger.events(worker_id=wid, type="production.count")})
    return {
        "worker_id": wid, "name": w["name"], "subject_id": subject_id(wid),
        "credentials": [json.loads(r["vc"]) for r in rows],
        "credential_status": {r["id"]: _status_of(r) for r in rows},
        "progress": [_clean(skill_progress(wid, s)) for s in SKILL_RULES if s in skills],
    }


def _held(wid: str) -> dict:
    """skill -> {level, evidence_level, credential_id} for live (not revoked/expired) skill credentials."""
    out = {}
    for r in _cred_rows(wid):
        s = _status_of(r)
        if r["kind"] != "skill" or s["revoked"] or s["expired"]:
            continue
        cur = out.get(r["skill"])
        if not cur or LEVELS.index(r["level"]) > LEVELS.index(cur["level"]):
            out[r["skill"]] = {"level": r["level"], "evidence_level": 3, "credential_id": r["id"]}
    return out


def coverage() -> dict:
    """Skills x workers matrix, with single points of failure (a skill only one person holds at U/O)."""
    conn = state.get().conn
    workers = [dict(r) for r in conn.execute("SELECT id, name, operation FROM workers WHERE is_supervisor=0 ORDER BY id")]
    skills = list(SKILL_RULES)
    matrix = {}
    for w in workers:
        held = _held(w["id"])
        row = {}
        for s in skills:
            if s in held:
                row[s] = held[s]
            else:
                p = skill_progress(w["id"], s)
                if p["current"]["days"]:
                    row[s] = {"level": "L", "evidence_level": 3, "credential_id": None,
                              "progress": f"{p['days_met']}/{p['days_needed']} days"}
        matrix[w["id"]] = row
    spof, uncovered, holders = [], [], {}
    for s in skills:
        hs = [w for w in workers if matrix[w["id"]].get(s, {}).get("level") in ("U", "O")]
        holders[s] = [w["id"] for w in hs]
        if len(hs) == 1:
            spof.append({"skill": s, "label": SKILL_RULES[s]["label"], "worker_id": hs[0]["id"], "name": hs[0]["name"],
                         "detail": f"Only {hs[0]['name']} works independently on {SKILL_RULES[s]['label'].lower()}"})
        elif not hs:
            uncovered.append({"skill": s, "label": SKILL_RULES[s]["label"]})
    return {"skills": [{"skill": s, "label": SKILL_RULES[s]["label"]} for s in skills],
            "workers": [{"id": w["id"], "name": w["name"]} for w in workers],
            "matrix": matrix, "holders": holders, "single_points_of_failure": spof, "uncovered": uncovered}


def expiring(days: int = 30, on: str | None = None) -> list:
    """Live credentials whose validUntil falls within `days` of `on` (default the demo day)."""
    on = on or _today()
    horizon = (date.fromisoformat(on) + timedelta(days=days)).isoformat()
    names = {r["id"]: r["name"] for r in state.get().conn.execute("SELECT id, name FROM workers")}
    out = []
    for r in _cred_rows():
        if r["valid_until"] and not r["revoked"] and on <= r["valid_until"] <= horizon:
            label = SAFETY_CREDENTIALS.get(r["skill"], {}).get("label") or r["skill"]
            out.append({"credential_id": r["id"], "worker_id": r["worker_id"], "name": names.get(r["worker_id"]),
                        "skill": r["skill"], "label": label, "valid_until": r["valid_until"],
                        "days_left": (date.fromisoformat(r["valid_until"]) - date.fromisoformat(on)).days})
    return sorted(out, key=lambda x: x["valid_until"])


def status_list() -> dict:
    """Return the revocation status list bitmap for issued credentials."""
    rows = _cred_rows()
    n = (max(r["status_index"] for r in rows) + 1) if rows else 0
    bits = [0] * n
    for r in rows:
        if r["revoked"]:
            bits[r["status_index"]] = 1
    iss = issuer()
    return {"id": f"urn:saakshi:status:{config.SITE_ID}", "type": "BitstringStatusList", "statusPurpose": "revocation",
            "issuer": iss["id"], "updated": now_ts(), "length": n, "bitmap": bits,
            "revoked": [i for i, b in enumerate(bits) if b],
            "policy": "Credentials are revoked only for fraud. Skills do not expire when a worker leaves or disputes."}


# --- Job match (keyword parser, no LLM) -----------------------------------------

_SKILL_WORDS = [
    (r"over\s?-?lock|overlocker|serger", "overlock"),
    (r"flat\s?-?lock|cover\s?stitch", "flatlock"),
    (r"lock\s?-?stitch|single[\s-]needle|\bsnls\b|\bsnl\b", "lockstitch"),
    (r"check(ing|er)?\b|quality|\bqc\b|inspect", "checking"),
    (r"cutt(ing|er)|\bcut\b", "cutting"),
    (r"iron(ing)?|pack(ing|er)?\b|press(ing|man)\b|fold(ing)?", "packing"),
]
_LEVEL_WORDS = [
    (r"can train|train(s|ing)? others|\blead\b|leader|trainer|mentor|senior", "O"),
    (r"independent(ly)?|experienced|skilled|\bexpert\b|without supervision", "U"),
    (r"trainee|fresher|learner|apprentice|helper|beginner", "I"),
]
SKILL_LABELS = {**{s: r["label"] for s, r in SKILL_RULES.items()},
                "checking": "Quality checking", "cutting": "Cutting", "packing": "Ironing & packing"}
TRAININGS = {
    "overlock": {"title": "Overlock threading & seam quality", "days": 3,
                 "how": "On-line coaching by a level-O operator; Samarth/ATDC short module (illustrative)"},
    "flatlock": {"title": "Flatlock cover-stitch basics", "days": 3,
                 "how": "On-line coaching by a level-O operator (illustrative)"},
    "lockstitch": {"title": "Single-needle lockstitch: topstitch & label attach", "days": 4,
                   "how": "Training-room machine + 2 days on line (illustrative)"},
    "checking": {"title": "Inline & end-line checking (AQL 2.5 basics)", "days": 2,
                 "how": "With the QC lead; buyer spec sheet walkthrough (illustrative)"},
    "cutting": {"title": "Cutting room: spreading, marker reading, safe straight-knife use", "days": 3,
                "how": "Requires machine guarding induction first (illustrative)"},
    "packing": {"title": "Ironing, folding & packing to buyer spec", "days": 1,
                "how": "With the finishing supervisor (illustrative)"},
}
_BAND_LEVEL = {"unskilled": "L", "semi-skilled": "U", "skilled": "U", "highly-skilled": "O"}


def parse_job(text: str) -> list[dict]:
    """Parse a job description into required skills and levels by keyword."""
    t = text.lower()
    level = "U"
    for pat, lv in _LEVEL_WORDS:
        if re.search(pat, t):
            level = lv
            break
    seen = []
    for pat, skill in _SKILL_WORDS:
        if re.search(pat, t) and skill not in seen:
            seen.append(skill)
    return [{"skill": s, "label": SKILL_LABELS[s], "level": level} for s in seen]


def match(wid: str, job_description: str) -> dict:
    """Score a worker's fit for a job description and list matches, gaps and training."""
    w = _worker(wid)
    required = parse_job(job_description)
    held = _held(wid)
    matched, gaps, training, scores = [], [], [], []
    for req in required:
        s, need = req["skill"], req["level"]
        h = held.get(s)
        source = "credential"
        if not h and s in SKILL_RULES:
            p = skill_progress(wid, s)
            if p["current"]["days"]:
                h = {"level": "L", "evidence_level": 3, "credential_id": None}
                source = f"production records ({p['days_met']}/{p['days_needed']} qualifying days)"
        if not h and w["operation"] == s:
            h = {"level": _BAND_LEVEL.get(w["skill_band"] or "", "L"), "evidence_level": 2, "credential_id": None}
            source = "employer HR record"
        if h:
            gap = LEVELS.index(need) - LEVELS.index(h["level"])
            entry = {"skill": s, "label": req["label"], "required_level": need, "level": h["level"],
                     "level_label": LEVEL_LABELS[h["level"]], "evidence_level": h["evidence_level"],
                     "evidence_label": EVIDENCE_LABELS[h["evidence_level"]], "credential_id": h["credential_id"],
                     "source": source}
            if gap <= 0:
                matched.append(entry)
                scores.append(1.0 if h["evidence_level"] >= 3 else 0.8)
                continue
            scores.append(0.5 if gap == 1 else 0.2)
            gaps.append({**entry, "reason": f"Needs level {need} ({LEVEL_LABELS[need]}); has {h['level']}"})
        else:
            scores.append(0.0)
            gaps.append({"skill": s, "label": req["label"], "required_level": need, "level": None,
                         "reason": f"No record of {req['label'].lower()}"})
        training.append({"skill": s, **TRAININGS[s]})
    fit = round(100 * sum(scores) / len(scores)) if scores else 0
    return {"worker_id": wid, "name": w["name"], "fit": fit, "required": required, "matched": matched,
            "gaps": gaps, "training": training,
            "note": None if required else "No known skills found in the job description"}


# --- HTTP --------------------------------------------------------------------------


class Production(BaseModel):
    """Production count record submitted for a worker."""
    worker_id: str
    operation: str
    pieces: int
    sam: float
    minutes: float
    defects: int = 0
    ts: str | None = None


def record_production(p: Production | dict) -> dict:
    """Validate and record a production count, issuing any newly earned credentials."""
    p = p if isinstance(p, Production) else Production(**p)
    _worker(p.worker_id)
    if p.pieces <= 0 or p.minutes <= 0 or p.sam <= 0 or p.defects < 0 or p.defects > p.pieces:
        raise HTTPException(422, "pieces, sam and minutes must be positive; 0 <= defects <= pieces")
    st = state.get()
    payload = {"operation": p.operation, "pieces": p.pieces, "sam": p.sam, "minutes": p.minutes, "defects": p.defects}
    ev = st.ledger.append("production.count", payload, worker_id=p.worker_id, ts=p.ts)
    issued = check_and_issue(p.worker_id, p.operation, ts=None if p.ts is None else ev["ts"])
    return {"event": ev, "efficiency": round(p.pieces * p.sam / p.minutes, 3),
            "defect_rate": round(p.defects / p.pieces, 4), "issued": issued}


@router.post("/production")
def production(p: Production):
    """Record a production count over HTTP."""
    return record_production(p)


@router.get("/passport/issuers")
def issuers():
    """Return the trusted issuer list and status list location."""
    iss = issuer()
    return {"issuers": [{**iss, "verificationMethod": f"{iss['id']}#key-1"}],
            "status_list": "/api/passport/status", "updated": now_ts()}


@router.get("/passport/status")
def passport_status():
    """Return the revocation status list over HTTP."""
    return status_list()


@router.get("/passport/coverage")
def passport_coverage():
    """Return credential coverage over HTTP."""
    return coverage()


@router.get("/passport/expiring")
def passport_expiring(days: int = 30):
    """Return credentials expiring within the given number of days."""
    return expiring(days)


class MatchReq(BaseModel):
    """Job match request body."""
    worker_id: str
    job_description: str


@router.post("/passport/match")
def passport_match(m: MatchReq):
    """Match a worker to a job description over HTTP."""
    return match(m.worker_id, m.job_description)


@router.get("/passport/credentials/{cid}")
def credential(cid: str):
    """Return a credential's verifiable credential JSON or 404."""
    r = get_credential(cid)
    if not r:
        raise HTTPException(404, "no such credential")
    return json.loads(r["vc"])


def verify_url(vc: dict, base: str = "http://localhost:8000") -> str:
    """Return the browser verification URL embedding the credential."""
    return base.rstrip("/") + "/verify/#" + b64url(canonical(vc))


@router.get("/passport/credentials/{cid}/qr")
def credential_qr(cid: str, base: str = Query("http://localhost:8000")):
    """Return an SVG QR code linking to the credential's verification URL."""
    import qrcode
    from qrcode.image.svg import SvgPathImage
    r = get_credential(cid)
    if not r:
        raise HTTPException(404, "no such credential")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=2, image_factory=SvgPathImage)
    qr.add_data(verify_url(json.loads(r["vc"]), base))
    qr.make(fit=True)
    return Response(qr.make_image().to_string(encoding="unicode"), media_type="image/svg+xml")


class Revoke(BaseModel):
    """Credential revocation request body."""
    reason: str
    by: str = "site-issuer"


@router.post("/passport/credentials/{cid}/revoke")
def revoke(cid: str, body: Revoke):
    """Revoke a credential for fraud and record the revocation in the ledger."""
    if not re.search(r"fraud|falsif|forg|fake|fabricat", body.reason, re.I):
        raise HTTPException(422, "Credentials are revoked only for fraud (e.g. falsified production records). "
                                 "A skill does not lapse because someone left, disputed pay or was absent.")
    st = state.get()
    with st.lock:
        r = get_credential(cid)
        if not r:
            raise HTTPException(404, "no such credential")
        if r["revoked"]:
            raise HTTPException(409, "already revoked")
        ts = now_ts()
        st.conn.execute("UPDATE passport_credentials SET revoked=1, revoked_reason=?, revoked_at=? WHERE id=?",
                        (body.reason, ts, r["id"]))
        ev = st.ledger.append("credential.revoked", {"credential_id": r["id"], "skill": r["skill"], "level": r["level"],
                                                     "reason": body.reason, "by": body.by,
                                                     "status_index": r["status_index"]},
                              worker_id=r["worker_id"], ts=ts)
    return {"credential_id": r["id"], "revoked": True, "status_index": r["status_index"], "event": ev}


@router.get("/passport/{wid}")
def passport_get(wid: str):
    """Return a worker's skill passport over HTTP."""
    return passport(wid)


# --- Demo seed ------------------------------------------------------------------------

SEED_DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]
# (efficiency, defect_rate) per seed day; None = absent. Q = qualifies (eff >= .70 and defects <= 2.5%).
_SEED_PLAN = {
    # Meena: 4 qualifying days (20, 21, 23, 24). One more good shift today issues her credential live.
    "W001": ("overlock", [(0.66, 0.020), (0.74, 0.018), (0.78, 0.015), (0.72, 0.031), (0.81, 0.012),
                          (0.79, 0.016), (0.68, 0.019)]),
    # Lakshmi: 6 qualifying days -> credential issued during seed.
    "W002": ("overlock", [(0.84, 0.010), (0.86, 0.012), (0.82, 0.009), (0.88, 0.011), (0.85, 0.014),
                          (0.83, 0.010), (0.87, 0.008)]),
    # Anjali: 2 qualifying days.
    "W006": ("overlock", [(0.58, 0.030), (0.62, 0.028), (0.71, 0.022), (0.64, 0.027), (0.69, 0.024),
                          (0.73, 0.021), (0.66, 0.026)]),
    # Sabita: 3 qualifying days on flatlock.
    "W003": ("flatlock", [(0.72, 0.020), (0.68, 0.018), (0.75, 0.019), None, (0.66, 0.022), (0.74, 0.017),
                          (0.69, 0.020)]),
    # Fatima: lockstitch independent (issued) -> a single point of failure on lockstitch.
    "W008": ("lockstitch", [(0.80, 0.012), (0.82, 0.015), (0.79, 0.011), (0.84, 0.010), (0.81, 0.013),
                            (0.83, 0.009), (0.80, 0.012)]),
}
_SAM = {"overlock": 0.5, "flatlock": 0.6, "lockstitch": 0.75}
_INDUCTION_EXPIRY = {"W004": "2026-11-06", "W006": "2026-11-14"}  # due inside 3 weeks


def seed_demo(st) -> None:
    """Seed the ledger with demo production records and credentials."""
    minutes = 420
    for wid, (op, plan) in _SEED_PLAN.items():
        sam = _SAM[op]
        for i, (day, cell) in enumerate(zip(SEED_DAYS, plan, strict=False)):
            if cell is None:
                continue
            eff, dr = cell
            pieces = round(eff * minutes / sam)
            defects = int(dr * pieces)  # floor keeps the plan's side of the 2.5% line
            ts = f"{day}T17:{(i * 7 + int(wid[1:]) * 3) % 50 + 5:02d}:00{config.TZ}"
            st.ledger.append("production.count", {"operation": op, "pieces": pieces, "sam": sam,
                                                  "minutes": minutes, "defects": defects},
                             worker_id=wid, ts=ts)
    for wid, (op, _plan) in _SEED_PLAN.items():
        check_and_issue(wid, op, ts=f"{SEED_DAYS[-1]}T18:00:00{config.TZ}")
    rows = st.conn.execute("SELECT id, joined FROM workers WHERE is_supervisor=0 ORDER BY id").fetchall()
    for r in rows:
        until = _INDUCTION_EXPIRY.get(r["id"], "2027-04-15")
        vf = (date.fromisoformat(until) - timedelta(days=180)).isoformat()
        issue_safety(r["id"], "machine_guarding_induction", valid_from=f"{vf}T10:00:00{config.TZ}",
                     valid_until=until, ts=f"{SEED_DAYS[-1]}T18:10:00{config.TZ}")
