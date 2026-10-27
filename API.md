# Saakshi API contract

All JSON. Base `/api`. Times are ISO 8601 with `+05:30`. Money in rupees (float, 2 dp).
Demo "today" is `2026-10-27` (`config.DEMO_DAY`). Site `TUP-03`, state `TN`.
Workers: `W001` Meena (ta), `W002` Lakshmi (ta), `W003` Sabita (or, contract), `W004` Ravi (hi, contract),
`W005` Kavitha (ta), `W006` Anjali (or, contract), `W007` Suresh (ta), `W008` Fatima (hi), `S001` Murugan (supervisor).

Every state change is a signed ledger event (`state.get().ledger.append(type, payload, worker_id=, ts=)`).
An event naming a worker drops a receipt in that worker's wallet, rendered in their language by
`saakshi/i18n.py` templates (`i18n.register(type, {"en": fn, "ta": fn, "hi": fn, "or": fn})`).
An event dict looks like:
`{seq, site, ts, day, type, worker_id, payload, prev_hash, hash, sig, signer, ref, receipt}`
where `ref` is the first 4 hex chars of the hash, upper case, and `receipt` is
`{worker_id, seq, ref, ts, type, hash, text, text_en, lang, channel}` or null.
These shapes are typed in `saakshi/ledger.py` (`Event`, `Receipt`, `VerifyResult`), and every `type`
string is a constant in `saakshi/events.py` (`events.PUNCH_IN == "punch.in"`, …): import it, don't retype it.

Errors: `HTTPException`s return `{detail}` with their status. Anything unhandled returns
`500 {"error": "internal_error", "request_id"}` (also sent as the `X-Request-ID` header) and is logged
with that id; no stack trace ever reaches the client. Send your own `X-Request-ID` (8–64 chars of
`A-Za-z0-9._-`) to have it reused.

## Authentication — `saakshi/auth.py`

Every `/api` route needs `Authorization: Bearer <token>` unless it is public. Policy, roles and
the threat model are in [SECURITY.md](SECURITY.md). 401 = missing, bad or expired token;
403 = wrong role or someone else's record. Anything not in the policy table is refused.

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /auth/demo-login | `{role:"worker"\|"supervisor"\|"hr"\|"auditor", worker_id?}` | `{token, role, sub, wid?, exp}` — demo only (404 when `SAAKSHI_DEMO=0`); production uses phone OTP or a PIN on a shared phone |

Public (no token): `GET /healthz`, `GET /site`, `GET /rules`, `GET /voice/topics`, `POST /relay/voice/reports`
(anonymous by design), `GET /passport/issuers`, `GET /passport/status`,
`GET /passport/credentials/{id}` and `/qr`, `POST /edge/events` (box-signed), `/demo/*` (demo mode only).

## Core — `saakshi/core_api.py`

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | /healthz | | `{ok:true, events, ledger_ok}` — public liveness probe; `ledger_ok` is the cached `/ledger/verify` result, no worker data |
| GET | /site | | `{site_id, name, state, demo_day, now, n_events, public_keys:{site, site-issuer, edge-box-1}}` |
| GET | /workers | | `[worker]` where worker = `{id, name, lang, role, line, operation, skill_band, gender, contract_type, contractor, joined, active, is_supervisor}` |
| GET | /workers/{id} | | worker |
| POST | /punch | `{worker_id, kind:"in"\|"out", ts?, device?}` | event (with receipt) |
| POST | /punch/correction | `{worker_id, corrects_seq, new_ts, reason, approver, ts?}` | event |
| GET | /ledger/events | `worker_id, type, type_prefix, day, since_seq, limit=200, desc=true` | `[event]` |
| GET | /ledger/events/{seq} | | event |
| GET | /ledger/events/{seq}/proof | | `{seq, hash, day, root, proof:[{sibling, side}]}` |
| GET | /ledger/verify | | `{ok, n_events, head, checked_at, problems:[{seq, kind, detail, worker_id, worker_name, type, ts}], roots:[{day, published, current, ok, n_events, published_at}]}`. kinds: `content_edited`, `bad_signature`, `broken_link`, `missing_events`, `root_mismatch`, `unreadable` |
| GET | /ledger/roots | | roots status list |
| POST | /ledger/roots/publish?day= | | `{day, root, n_events, last_seq, published_at, sig, site_public_key}` |
| GET | /workers/{id}/receipts | `limit` | `[{id, worker_id, seq, ref, ts, type, hash, text, text_en, channel, created}]` newest first |
| POST | /workers/{id}/receipts/check | `{receipts?:[{seq, hash}]}` (omit → use wallet) | `{worker_id, checked, ok, mismatches:[{seq, kind:"edited"\|"deleted", type, ref, receipt_hash, current_hash, receipt_text, receipt_text_en, current_text, current_text_en}]}` |
| POST | /workers/{id}/lookup | `{viewer, reason, viewer_role?, what?}` | `{worker, access, recent_events}`; logs access + `access.lookup` event (worker sees it) |
| GET | /workers/{id}/access-log | | `[{id, ts, viewer, viewer_role, worker_id, reason, what}]` |
| POST | /demo/reset | | wipes and re-seeds with history |
| POST | /demo/tamper | `{worker_id?="W001", seq?, new_ts?, mode:"naive"\|"rehash"}` | `{ok, seq, old_ts, new_ts}` — direct SQL edit of the latest punch-out |

Python helper for modules: `from saakshi.core_api import log_access` → `log_access(worker_id, viewer, reason, what)`.

## Pay and overtime — `saakshi/pay/`

Event types: `ot.request`, `ot.cap_check`, `ot.consent`, `pay.run`, `pay.paid` (`{period, net, run_seq}`), `pay.adjustment` (`{period, amount, label, case_id, resolved_seq, approver}`), `ot.opening_balance`
(payload `{quarter:"2026-Q4", hours, source}` — quarter-to-date OT imported at install).

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | /rules | | state rule table: `{state, version, min_wage_monthly:{band: amount}, ot_multiplier:2, ot_cap_quarter:144, daily_hours:8, ...}` |
| GET | /hours/{wid} | `from, to` (days) | `[{day, in, out, worked_hours, ot_hours, consented_ot_hours, unconsented_ot_hours, corrected:bool, evidence:[seq]}]` |
| GET | /ot/cap | `date?` | `[{worker_id, name, used, cap, remaining, pct, status:"ok"\|"near"\|"over"}]` quarter to date |
| POST | /ot/requests | `{worker_ids:[..], date, hours, requested_by, reason, ts?}` | `{requests:[{request_id, worker_id, name, date, hours, status:"pending"\|"blocked", cap:{used, cap, remaining, after}, warnings:[str], events:[seq]}]}` |
| GET | /ot/requests | `worker_id?, status?` | `[request]` with `status` in pending/accepted/declined/blocked |
| POST | /ot/requests/{request_id}/consent | `{decision:"accept"\|"decline", channel:"voice"\|"tap"\|"whatsapp", transcript?, ts?}` | `{request, event, receipt}` — consent signed with `worker:<id>` key |
| GET | /pay/{wid}/today | `day?` | `{day, in, out, worked_hours, ot_hours, earned_today, ot_earned, currency:"INR"}` |
| GET | /pay/{wid}/payslip | `period=2026-10` | `{period, worker, days_worked, lines:[{label, amount, formula, evidence:[seq], explain}], gross, deductions:[{label, amount, formula, explain}], total_deductions, net, checks:[{name, ok, detail}], blocked:bool, integrity:{ok, problems}, explanation:{en, ta, hi, or}, status:"estimated"\|"approved"\|"paid"\|"under_review", status_label:{en, ta, hi, or}, open_disputes:[case_id]}` — see *Payslip status and explain* below |
| POST | /pay/run | `?period=2026-10` | `{period, blocked, results:[{worker_id, name, gross, net, blocked, failed_checks:[str]}]}` appends `pay.run` per worker |
| POST | /pay/run/{period}/paid | | `{period, paid:[{worker_id, name, net, seq}], skipped:[{worker_id, name, reason}]}` appends `pay.paid` per worker whose `pay.run` went through (skips held or already-paid workers); 409 if the period was never run |
| GET | /pay/fairness | `period` | `{period, checks:[{name, ok, detail, workers:[wid]}], ot_gini}` — the 8 fairness checks |

### Payslip status and explain

`status`: `under_review` (an open or assigned dispute on the period; takes precedence) > `paid` (a `pay.paid`
event for the period) > `approved` (a `pay.run` event) > `estimated`. `status_label` gives short words for it.

Every item in `lines` and `deductions` carries
`explain:{summary:{en, ta, hi, or}, days_worked:int|null, hours:float|null, rate:float|null, rate_label:str,
sources:[{seq, ts, type}] (first 20 signed source events), corrections:[{seq, ts, reason, approver}] (punch.correction
events affecting the period), checks:[name of each payslip check that concerns the item]}`.
A resolved-and-corrected dispute adds the line `Correction (case PAY-0001)` (from a `pay.adjustment` event); it is
added to `gross` and `net` in full (PF and ESI are not recomputed).

## Pay disputes — `saakshi/pay/disputes.py`

A worker questions a payslip line; HR or a supervisor owns the case; HR resolves it. Each step is a signed
ledger event naming the worker (`dispute.opened`, `dispute.assigned`, `dispute.resolved`, plus `pay.adjustment` when
corrected), so the worker gets a receipt for each, and the `timeline` is read back from those events: the worker app
and the console show the same history.

Case = `{case_id:"PAY-0001", worker_id, worker_name, period, line, amount_questioned, note, status:"open"|"assigned"|"resolved",
owner (default "HR · payroll desk"), due:"YYYY-MM-DD" (created + 3 working days, Mon–Sat), created, resolved_at|null,
outcome:null|"corrected"|"explained", correction_amount|null, timeline:[{ts, kind:"opened"|"assigned"|"resolved", by, text, seq}]}`.

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /pay/{wid}/disputes | `{period:"2026-10", line, amount_questioned>=0, note<=300, ts?}` | Case — the worker only (self) |
| GET | /pay/{wid}/disputes | | `[Case]` newest first — self, hr, supervisor, auditor |
| GET | /disputes | `status?=open\|assigned\|resolved` | `[Case]` newest first — hr, supervisor, auditor |
| POST | /disputes/{case_id}/assign | `{owner, ts?}` | Case, status `assigned` (re-assigning allowed; 409 once resolved) — hr, supervisor |
| POST | /disputes/{case_id}/resolve | `{outcome:"corrected"\|"explained", note, correction_amount?, ts?}` | Case, status `resolved`; corrected needs a non-zero `correction_amount` (422 otherwise) and appends `pay.adjustment`; 409 if already resolved — hr only |

Python helpers for the console: `from saakshi.pay import disputes` → `disputes.list_cases(status=None)`, `disputes.case(case_id)`.

## Voice: anonymous, verifiable feedback — `saakshi/voice/`

Blind RSA signatures, one issuer key per topic per month. Unlinkable by construction.

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | /voice/topics | | `{month, threshold, topics:[{id, label:{en,ta,hi,or}, safety_critical, key:{n_hex, e}}]}` |
| POST | /voice/issue | `{worker_id, month, blinded:{topic_id: hex}}` | `{month, signatures:{topic_id: hex}}` — once per worker per topic per month |
| POST | /relay/voice/reports | `{topic, month, token:hex, signature:hex, text, lang?}` | `{case_key, status:"waiting"\|"published"\|"escalated", corroborations, threshold}` — the relay strips identity; 409 if token already spent |
| POST | /voice/scrub | `{text}` | `{suggested, flags:[{span, reason}]}` |
| GET | /voice/themes | | `[{topic, label, count, threshold, published, safety_critical, reports:[{text, ts}] (only if published), response?}]` |
| GET | /voice/cases/{case_key} | | `{case_key, topic, status, corroborations, threshold, response?}` |
| POST | /voice/themes/{topic}/respond | `{text, by}` | "You said, we did" entry |
| GET | /voice/board | | `[{topic, label, you_said, we_did, by, ts}]` |

JS client for the worker app: `web/shared/voice-client.js` exposes
`window.SaakshiVoice = { getTokens(workerId), report(topic, text, lang) }`.

## Skill passport — `saakshi/passport/`

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /production | `{worker_id, operation, pieces, sam, minutes, defects, ts?}` | `{event, efficiency, defect_rate, issued?: credential}` — auto-issues when criteria met |
| GET | /passport/{wid} | | `{worker_id, credentials:[vc], progress:[{skill, level, criteria, current, met, days_needed, days_met}]}` |
| GET | /passport/credentials/{id} | | W3C-VC-shaped JSON with `proof:{type:"Ed25519Signature2020", verificationMethod, proofValue}` |
| GET | /passport/credentials/{id}/qr | | `image/svg+xml` QR of `/verify/#<base64url(vc)>` |
| GET | /passport/issuers | | `{issuers:[{id, name, public_key_hex}]}` |
| GET | /passport/status | | revocation status list |
| POST | /passport/credentials/{id}/revoke | `{reason}` | |
| POST | /passport/match | `{worker_id, job_description}` | `{fit, required:[{skill, level}], matched:[..], gaps:[..], training:[..]}` |

Event types: `production.count`, `credential.issued`, `credential.revoked`.

## Edge camera events — `saakshi/edge/`

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /edge/events | `{box_id, camera, zone, kind, count?, value?, ts, sig}` signed by the box key | ledger event; 422 if any field carries image, face, video, embedding or person identity |
| GET | /edge/events | `limit, kind?` | `[{seq, ts, camera, zone, kind, count, value}]` |
| GET | /edge/summary | `day?` | `{zones:[{zone, events:{kind: n}}], ppe_compliance_by_zone, last_event}` |
| GET | /edge/cameras | | camera register: `[{camera, zone, purpose, owner, retention_hours}]` |

kinds: `restricted_zone_entry`, `ppe_noncompliance`, `ppe_compliance_rate`, `fire_smoke`, `blocked_exit`, `person_down`, `queue_length`, `near_miss`, `heat_wbgt`.

## Safety reports — `saakshi/safety/`

A worker's hazard or stop-work call with delivery states. Event types `safety.reported`, `safety.acknowledged`,
`safety.resolved` (each names the reporting worker, who gets a receipt in their language). State is replayed from
those events; nothing is updated in place. Acknowledgement is due 15 min after a `stop_work` call, 4 h after a `hazard`.
Python: `saakshi.safety.list_reports(worker_id=None)`, `report(...)`, `acknowledge(...)`, `resolve(...)`, `get_report(id)`.

Report = `{report_id:"SAFE-0001", worker_id, kind:"hazard"|"stop_work", zone, note, status:"received"|"acknowledged"|"resolved",
received_at, ack_due, acknowledged_at|null, acknowledged_by|null, resolved_at|null, overdue:bool (still "received" after ack_due),
timeline:[{ts, kind:"received"|"acknowledged"|"resolved", by, text, seq}]}`

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /safety/reports | `{kind:"hazard"\|"stop_work", zone (≤60), note? (≤300), client_id? (≤64)}` — worker role; the worker comes from the token (`worker_id` in the body only when auth is off) | Report; a repeat `client_id` from the same worker returns the first report, no new event |
| GET | /safety/reports | `worker_id?` — a worker must pass their own id and only ever sees their own | `[Report]` newest first |
| POST | /safety/reports/{report_id}/ack | `{note?}` — supervisor or HR (actor from the token) | Report, status `acknowledged` (repeat ack is a no-op; 409 once resolved) |
| POST | /safety/reports/{report_id}/resolve | `{note}` (required: what was done) — supervisor or HR | Report, status `resolved` (409 if already resolved) |

## Console and SDG 8 — `saakshi/console.py` (integration)

| Method | Path | Returns |
| --- | --- | --- |
| GET | /console/overview | `{site, integrity, exceptions:[{severity:"critical"\|"high"\|"medium", kind, title, detail, people, action, link}], counts}` |
| GET | /console/queue | `{summaries:[{key:"urgent_safety"\|"pay_discrepancies"\|"pending_approvals"\|"overdue", label, count}], items:[{id, category:"integrity"\|"safety"\|"pay"\|"approval"\|"skills"\|"voice", summary_key|null, severity:"critical"\|"high"\|"medium"\|"low", issue, impact, owner, deadline|null, overdue, next_action:{label, kind:"open_evidence"\|"open_roots"\|"ack_safety"\|"open_dispute"\|"go_section"\|"open_lookup", target}, count, window|null, events:[seq], people:[wid]}]}` — supervisor/hr/auditor. Sorted by severity, then integrity first, then deadline (null last). Repeated edge detections of one zone+kind on one day are one row (`count`, `window`). Summary counts: items with that `summary_key`; `overdue` counts items with `overdue:true` (an overdue safety ack counts in both `urgent_safety` and `overdue`). Python: `saakshi.console.queue()` |
| GET | /sdg8/scorecard | `{targets:[{target, label, indicator, value, unit, status}]}` |
