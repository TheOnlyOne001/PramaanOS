# Security

Saakshi holds wage, hours and consent records that a worker may need against her own employer, so the
API is **deny by default**: every `/api` route needs a signed bearer token unless the policy table says
it is public on purpose.

## Authentication and authorization

- **Tokens** (`saakshi/auth.py`): `base64url(json{sub, role, wid?, exp}).base64url(HMAC-SHA256)`, 12 h expiry.
  The HMAC key is derived from 32 random bytes stored once in the `keys` table (row `auth-hmac`).
  Signatures are compared in constant time (`hmac.compare_digest`).
- **Roles**: `worker` (carries `wid`), `supervisor`, `hr`, `auditor`.
- **One middleware** (`AuthMiddleware`, wired in `saakshi/app.py`) evaluates the `POLICY` table in
  `saakshi/auth.py` before any handler runs. First matching rule wins; no rule means refused.
  `401` = missing / bad / expired token, `403` = valid token, wrong role or not your record.
- **Self rules**: a worker can only reach her own `{wid}` (receipts, access log, pay, hours, passport),
  only list her own overtime requests, only consent to an overtime request that belongs to her, and only
  ask the voice issuer for tokens in her own name.

| Route group | Who |
|---|---|
| `/site`, `/rules`, `/voice/topics`, passport issuers / status / credential + QR | public |
| `POST /relay/voice/reports` | public, **anonymous by design** (credentials and cookies are stripped before the handler) |
| `POST /edge/events` | public, authenticated by the camera box's Ed25519 signature |
| `/workers/{wid}/receipts*`, `/access-log` | that worker, auditor |
| `/pay/{wid}/*` | that worker, HR |
| `/hours/{wid}`, `/passport/{wid}` | that worker, supervisor, HR |
| `POST /ot/requests/{id}/consent` | only the worker the request is for |
| `POST /voice/issue` | only the worker named in the body |
| `POST /ot/requests`, `/punch`, `/punch/correction`, `/production` | supervisor (punch stands in for the gate device) |
| `POST /workers/{wid}/lookup` | supervisor, HR; the logged viewer is taken from the token, not the body |
| `POST /pay/run`, `/ledger/roots/publish`, credential revoke | HR |
| `GET /pay/fairness` | HR, auditor |
| console, edge feeds, voice themes, ledger events, passport coverage / expiring / match | supervisor, HR, auditor |
| `GET /ledger/verify`, `/ledger/roots` | every signed-in role (workers verify the chain too) |

## Threat model

| Asset | Threat | Control | Where |
|---|---|---|---|
| Overtime consent | Supervisor or co-worker "accepts" for a worker | Consent only with the owning worker's token; signed with her key | `auth.POLICY` (`consent_owner`), `pay/overtime.py` |
| Payslips, receipts, access log | Worker or staff browsing someone else's record | Worker-self rules; receipts readable only by the worker and the auditor | `auth.POLICY` (`self`) |
| Record look-ups | Staff hide who opened a record | Viewer and role are overwritten from the token before the handler | `AuthMiddleware` (lookup rewrite) |
| Payroll run, daily root publishing | Unauthorised run or premature publish | HR-only routes | `auth.POLICY` |
| Anonymous grievances | Employer links a report to a worker | Relay takes no token, strips `Authorization`/`Cookie`, stores no worker id; blind-signed tokens | `AuthMiddleware`, `voice/relay.py` |
| Bearer tokens | Forgery, role escalation, replay after expiry | HMAC-SHA256 over the whole payload, constant-time compare, `exp` checked | `auth.verify_token` |
| Edge events | Fake camera events | Ed25519 signature of the registered box | `edge/ingest.py`, `edge/privacy.py` |
| Ledger | Silent DB edits | Hash chain + Merkle roots, worker-held receipts | `ledger.py` |
| Browser | XSS, clickjacking, MIME sniffing, caching of personal data | Strict CSP (no inline script), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `Cache-Control: no-store` on `/api` | `app.py` |
| Unknown / new routes | Forgotten endpoint left open | Deny by default (`401`/`403` without a policy row) | `auth.match` |

## Demo-only parts

- `POST /api/auth/demo-login {role, worker_id?}` hands out a token for any role. It works **only** when
  `SAAKSHI_DEMO=1` (the default for the hackathon) and returns `404` otherwise.
  In production workers sign in with a phone OTP, or a PIN on a shared line phone; staff use company SSO.
  Those flows mint the same token, so the policy table does not change.
- The web apps fetch demo tokens automatically (`web/shared/api.js`, cached in `sessionStorage`). The worker
  app uses a supervisor token for its demo "punch" button, standing in for the gate device.
- `/api/demo/reset` and `/api/demo/tamper` are also gated by `SAAKSHI_DEMO`.
- Keys live in SQLite for the demo; production keys belong in an HSM or on the device.

## Deploying

```bash
SAAKSHI_DEMO=0 SAAKSHI_AUTH=1 SAAKSHI_DB=/var/lib/saakshi/saakshi.db \
  uvicorn saakshi.app:app --host 0.0.0.0 --port 8000 --no-access-log
```

- `SAAKSHI_DEMO=0` disables demo login, reset and tamper.
- `SAAKSHI_AUTH` is on unless set to `0`; never turn it off outside local tests.
- Serve behind TLS. Run the relay with access logging off (ideally operated by a union, NGO or auditor).

## Serverless deployment (Vercel)

Each serverless instance has its own `/tmp/saakshi.db`. Set `SAAKSHI_AUTH_SECRET` (32+ random
characters) in the project's environment variables so tokens verify across instances. The demo
data itself is per instance on serverless; a real deployment uses one shared database.
