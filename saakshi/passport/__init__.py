"""Skill passport: credentials earned from signed production records.

Progress is computed from `production.count` ledger events only (never from a side
table), so anything the passport claims can be traced to signed seqs. When the rules
are met, the site issuer signs a W3C-VC-2.0-shaped credential (Ed25519 over canonical
JSON of the VC without `proof`) that verifies offline in web/verify/.

Modules, by responsibility:

- `rules`: versioned skill criteria and level/evidence labels
- `store`: the credentials table (schema registered once, on import)
- `evidence`: per-day efficiency/defect maths and progress from the ledger
- `vc`: credential shape, issuer, canonical signing, verification, verify URL and QR
- `credentials`: issuing skill and safety credentials
- `status`: revocation status list and fraud-only revocation
- `holder`, `coverage`, `matching`: worker, employer and job-match views
- `production`: recording production counts (auto-issues credentials)
- `receipts`: wallet receipt texts (registered with i18n once, on import)
- `seed`: demo data; `api`: HTTP routes
"""
from __future__ import annotations

from . import receipts as receipts  # registers the receipt templates with i18n
from .api import MatchReq, Revoke, credential, credential_qr, issuers, revoke, router
from .coverage import coverage, expiring
from .credentials import Issued, check_and_issue, issue_safety, issue_skill
from .evidence import SkillProgress, assess, skill_progress
from .holder import HeldSkill, held_skills, passport
from .matching import SKILL_LABELS, TRAININGS, match, parse_job
from .production import Production, record_production
from .rules import (
    EVIDENCE_EXPLAIN,
    EVIDENCE_LABELS,
    LEVEL_LABELS,
    LEVELS,
    NSQF_SMO,
    RULES_VERSION,
    SAFETY_CREDENTIALS,
    SKILL_RULES,
)
from .seed import SEED_DAYS, seed_demo
from .status import status_list
from .store import get_credential
from .vc import (
    ISSUER_KEY,
    VC_CONTEXT,
    VerifiableCredential,
    b64url,
    b64url_decode,
    issuer,
    subject_id,
    vc_signing_bytes,
    verify_url,
    verify_vc,
)

__all__ = [
    "EVIDENCE_EXPLAIN",
    "EVIDENCE_LABELS",
    "ISSUER_KEY",
    "LEVELS",
    "LEVEL_LABELS",
    "NSQF_SMO",
    "RULES_VERSION",
    "SAFETY_CREDENTIALS",
    "SEED_DAYS",
    "SKILL_LABELS",
    "SKILL_RULES",
    "TRAININGS",
    "VC_CONTEXT",
    "HeldSkill",
    "Issued",
    "MatchReq",
    "Production",
    "Revoke",
    "SkillProgress",
    "VerifiableCredential",
    "assess",
    "b64url",
    "b64url_decode",
    "check_and_issue",
    "coverage",
    "credential",
    "credential_qr",
    "expiring",
    "get_credential",
    "held_skills",
    "issue_safety",
    "issue_skill",
    "issuer",
    "issuers",
    "match",
    "parse_job",
    "passport",
    "record_production",
    "revoke",
    "router",
    "seed_demo",
    "skill_progress",
    "status_list",
    "subject_id",
    "vc_signing_bytes",
    "verify_url",
    "verify_vc",
]
