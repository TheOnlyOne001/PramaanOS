"""Fair Pay and overtime: deterministic pay from signed hours, consent-based overtime, fairness checks.

Rule values are illustrative Tamil Nadu figures; verify before real use.
Money is computed only in this package, by plain arithmetic; an LLM never touches it.

Modules, in dependency order:
  rules     the rule table and pure helpers (rounding, hourly rate, quarters, periods)
  records   the ot_requests table and shared reads (workers, accepted overtime, opening balances, PF deposits)
  receipts  receipt texts for ot.request, ot.consent and pay.run, registered with i18n on import
  shifts    Proof of Hours: shifts from signed punches and corrections
  limits    quarterly cap usage and the fatigue rule
  overtime  overtime requests (cap and fatigue checked up front) and worker-signed consent
  wages     today's earnings, a period's attendance tally and its rupee amounts
  payslips  the payslip with its checks and explanations, and the pay run
  audit     the line-wide fairness checks
  demo      demo history
  api       the HTTP router

Importing the package registers the ot_requests schema and the receipt templates once.
"""
from __future__ import annotations

from . import receipts as receipts
from .api import router
from .audit import FairnessCheck, FairnessReport, fairness, gini
from .demo import OPENING, PAST, WEEK_OT, seed_demo
from .limits import CapStatus, cap_status, fatigue, quarter_used
from .overtime import Consent, OTRequest, consent, create_requests, list_requests
from .payslips import Check, Payslip, payslip, run
from .rules import RULES, Rules, hourly_rate
from .shifts import Shift, hours
from .wages import TodayPay, pf_deducted, today

__all__ = [
    "OPENING", "PAST", "RULES", "WEEK_OT", "CapStatus", "Check", "Consent", "FairnessCheck", "FairnessReport",
    "OTRequest", "Payslip", "Rules", "Shift", "TodayPay", "cap_status", "consent", "create_requests", "fairness",
    "fatigue", "gini", "hourly_rate", "hours", "list_requests", "payslip", "pf_deducted", "quarter_used",
    "router", "run", "seed_demo", "today",
]
