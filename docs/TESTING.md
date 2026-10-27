# Testing Saakshi

## Run

```bash
pip install -r requirements.txt           # includes pytest-cov, hypothesis (# dev)
python3 -m pytest                         # whole suite, ~20 s
python3 -m pytest --cov=saakshi --cov-report=term-missing   # with per-line coverage
python3 -m pytest tests/test_ledger_property.py             # just the property tests
python3 scripts/demo.py                   # the 3-minute demo, exits non-zero on any broken promise
```

CI (`.github/workflows/ci.yml`) runs ruff, then the suite with `--cov-fail-under=83`
(measured 88 % minus a 5-point margin), then the demo script.

Every test gets a fresh SQLite file (`st` fixture in `tests/conftest.py`: workers + keys,
no history; `client` is a FastAPI `TestClient` over it, auth off). `node` is needed for the
UI-string check; it skips without it.

## Test pyramid

| Layer | Suite | What it proves | Tests |
| --- | --- | --- | --- |
| Property | `test_ledger_property.py` | For random ledgers (hypothesis, 40 examples each): a clean ledger always verifies; **any** single direct-SQL edit of `ts`, `payload`, `type`, `worker_id`, `prev_hash`, `hash` or `sig`, deleting any row, or swapping two rows' `seq` is caught by `verify()`; every Merkle inclusion proof verifies against the published root and fails for a wrong leaf | 6 |
| Unit | `test_ledger.py` | Chain, signatures, roots, tamper modes (naive and rehash), receipt check | 10 |
| Unit | `test_pay.py` | State rules, OT cap, consent, payslip lines with evidence, fairness checks | 9 |
| Unit | `test_voice.py` | Blind-signature tokens, double-spend 409, k-anonymity threshold, scrubber | 10 |
| Unit | `test_passport.py` | Credential issue / verify / revoke, QR, job match | 8 |
| Unit | `test_edge.py` | Box signatures, refusal of image/face/identity fields, summaries | 17 |
| Unit | `test_i18n.py` | Every receipt template renders in en/ta/hi/or without falling back to English or the generic text, and carries the ref; every UI string in `web/shared/i18n.js` exists in ta/hi/or with the same `{placeholders}` | 44 |
| Contract | `test_contract.py` | Every endpoint in `API.md` exists in the app (path params normalised); every `/api` route is documented or allowlisted with a reason; OpenAPI schema generates | 54 |
| Integration | `test_console.py` | Seeded week: console exceptions sorted by severity, deposit shortfall flagged; after a DB tamper the first exception is critical integrity naming Meena; SDG 8 scorecard has 8.2, 8.3, 8.5, 8.6, 8.7, 8.8 with values; a failing module (pay, voice, edge, passport) never blanks the overview or scorecard | 10 |
| End to end | `test_e2e_demo.py` | `scripts/demo.py` runs in-process on a fresh DB and prints "All demo checks passed" | 1 |
| | **Total** | | **169** |

## Coverage (measured 2026-10-27, `pytest --cov=saakshi`)

| Module | Cover |
| --- | --- |
| `crypto.py` | 99 % |
| `passport/` | 97 % |
| `ledger.py` | 96 % |
| `console.py` | 95 % |
| `edge/` | 93 % |
| `voice/` | 93 % |
| `pay/` | 92 % |
| `voice_client.py` | 91 % |
| `i18n.py` | 90 % |
| `seed.py` | 89 % |
| `tamper.py` | 88 % |
| `app.py` | 86 % |
| `seed_history.py`, `state.py` | 83 % |
| `core_api.py` | 79 % |
| `auth.py` | 30 % (new; its tests were still being written when this was measured) |
| `config.py`, `db.py` | 100 % |
| **Total** | **88 %** |

## Known bugs (xfail)

None so far. The property, contract, console and i18n suites found no defect in the app code.
A bug found later gets a test marked
`@pytest.mark.xfail(reason="BUG: ...", strict=True)`, so CI turns red once someone fixes it and the marker has to come off.

## Allowlisted undocumented routes

`test_contract.py::UNDOCUMENTED_OK` lists `/api` routes that are deliberately missing from `API.md`, each with a reason:
`/api/passport/coverage` and `/api/passport/expiring` (internal console feeds), plus
`/api/auth/me` and `/api/auth/demo-login` (new auth layer, still to be documented).
