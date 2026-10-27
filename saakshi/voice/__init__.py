"""Voice: anonymous but verifiable worker feedback.

Blind RSA signatures in the style of Privacy Pass / RFC 9474 (the design doc's fallback to Semaphore):

1. Issue (identified, `issuer`). Each month the worker app blinds one random 32-byte message per topic and
   sends all of them at once to POST /api/voice/issue with the worker id. The issuer checks the worker is
   real, active and not a supervisor, and signs at most ONE blinded message per worker per topic per month
   with that (month, topic) RSA key (`keys`). It records only (worker_id, topic, month): never the blinded value.
2. Report (anonymous, `relay`). The app unblinds the signature and later sends (topic, month, token,
   signature, text) to POST /api/relay/voice/reports with no worker id. The relay verifies the signature,
   derives nullifier = sha256(month|topic|m) and refuses a second use of the same token. Because the
   signature was blind (`blind`), nobody — the issuer included, even with its private key — can link a
   report to an issuance (see tests/test_voice.py::test_unlinkable).
3. Threshold (`publication`). A theme (topic, month) reaches the employer only once >= THRESHOLD distinct
   tokens were spent on it, and never on a site with fewer than MIN_GROUP enrolled workers. Safety-critical
   topics (safety, heat, harassment) escalate on the first report: safety officer, or the Internal
   Committee under the POSH Act for harassment.

Audio never reaches the server: speech is transcribed on the phone and only text is sent. `scrubber`
suggests rewrites that drop identifying details; `seed` builds the demo's previous month; `api` holds the
routes. The worker-side client is `saakshi.voice_client`.
"""
from __future__ import annotations

from .. import db
from .api import router
from .blind import blind, fdh, nullifier, to_hex, unblind, verify
from .issuer import issue
from .keys import KEY_BITS, PUBLIC_EXPONENT, IssuerKey, key
from .publication import board, case_status, respond, themes
from .relay import submit_report
from .scrubber import scrub
from .seed import seed_demo
from .store import SCHEMA
from .topics import LABELS, MIN_GROUP, RELAY_NOTE, ROUTES, SAFETY, THRESHOLD, TOPIC_IDS, TOPICS, current_month

db.register_schema(SCHEMA)

__all__ = [
    "KEY_BITS",
    "LABELS",
    "MIN_GROUP",
    "PUBLIC_EXPONENT",
    "RELAY_NOTE",
    "ROUTES",
    "SAFETY",
    "THRESHOLD",
    "TOPICS",
    "TOPIC_IDS",
    "IssuerKey",
    "blind",
    "board",
    "case_status",
    "current_month",
    "fdh",
    "issue",
    "key",
    "nullifier",
    "respond",
    "router",
    "scrub",
    "seed_demo",
    "submit_report",
    "themes",
    "to_hex",
    "unblind",
    "verify",
]
