# Contributing

1. `make install`, then `make check` (lint, tests with coverage, scripted demo) must pass.
2. Every state change is a signed ledger event via `state.get().ledger.append(...)`; never `UPDATE`
   the `events` table. A correction is a new event with a reason and an approver.
3. New endpoints go in [API.md](API.md) (the contract test fails otherwise) and in the policy
   table in `saakshi/auth.py` (unknown routes are denied by default).
4. Money is computed only by deterministic code in `saakshi/pay/`, never by an LLM.
5. New UI strings go in `web/shared/i18n.js` for all of en, ta, hi and or (the i18n test checks).
6. Never add the red-line features listed in the README.
