# PramaanOS · Saakshi (சாட்சி, "witness")

Shared, tamper-evident, privacy-preserving work records that **workers and employers both hold**.
Built for SDG 8 (decent work) in India's labour-intensive workplaces; the demo site is an export
garment unit in Tiruppur, Tamil Nadu.

> Rights without records are wishes. The labour codes in force since 21 Nov 2025 promise
> consent-based overtime at 2×, timely wages and grievance channels. What's missing is a record
> both sides trust. Saakshi signs every record where it is created and gives the worker a copy.

## Run it

```bash
pip install -r requirements.txt
uvicorn saakshi.app:app --port 8000        # seeds a week of signed history on first start
```

- Worker app (Meena, Tamil): http://localhost:8000/worker/?w=W001
- Employer console: http://localhost:8000/console/
- Offline credential verifier: http://localhost:8000/verify/
- API docs: http://localhost:8000/docs · contract: [API.md](API.md)

Tests and the scripted demo:

```bash
python3 -m pytest                       # ledger, pay maths, voice unlinkability, passport, edge
python3 scripts/demo.py                 # the 3-minute demo, in-process, with pass/fail checks
python3 scripts/demo.py --base http://localhost:8000 --db data/saakshi.db --pause   # live, with both UIs open
python3 scripts/tamper.py               # the live tamper: edit Meena's punch-out straight in SQLite
python3 scripts/edge_sim.py --scenario press_zone   # the edge camera box
```

## The 3-minute demo

1. Meena punches in and gets a receipt in Tamil: `வருகை 08:02 · குறிப்பு 7F3A`.
2. Her supervisor asks for 2 h overtime. The console warns that two co-workers are near the
   144 h quarterly cap; Meena accepts by voice and her consent is signed with her key.
3. **Live tamper test.** Someone edits her punch-out in the database. The recomputed hash no longer
   matches the signature, the published daily root no longer matches, her own receipts disagree,
   and the payslip refuses to compute. Both dashboards flag it within seconds.
4. She reports anonymously that drinking water runs out by 3 pm. Two more reports corroborate it;
   the theme reaches the console with no identity attached.
5. A person steps into the press zone in front of the camera. An event appears; no video or face
   leaves the box (an event carrying a face crop is rejected).
6. Her quality data issues an "independent on overlock" credential; a recruiter verifies the QR
   offline against a cached issuer key.
7. Close on the SDG 8 scorecard.

## How it works

```
 existing devices ──► connectors / edge box ──► TRUST LAYER ──► engines ──► two front-ends
 biometric gate        punch, production,       Ed25519 per      Proof of Hours  Worker app (PWA,
 CCTV (edge box)       camera events            event, hash      Fair Pay        voice-first, ta/hi/or/en)
 payroll exports                                chain per site,  Skill Passport  Employer console
                                                daily Merkle     Voice           (exceptions first)
                                                root, worker     Safety/Edge
                                                receipts         SDG 8
```

| Piece | File | What's real |
| --- | --- | --- |
| Signed ledger | `saakshi/ledger.py` | Ed25519 signature per event, SHA-256 hash chain, daily Merkle root with inclusion proofs. `verify()` catches content edits, re-hash attacks, deletions and root mismatches. Corrections are new signed events, never overwrites |
| Worker receipts | `saakshi/core_api.py`, `saakshi/i18n.py` | Every event naming a worker drops a receipt in their language; the worker's copy is checked against the employer's record |
| Access log | `saakshi/core_api.py` | Opening one worker's record needs a reason, and the worker sees who looked |
| Fair Pay | `saakshi/pay.py` | Deterministic pay from signed hours: OT at 2× of (Basic+DA)/26/8, 144 h/quarter cap, fatigue limits, signed consent, 50% deduction cap, PF/ESI, eight fairness checks, explanation in the worker's language |
| Voice | `saakshi/voice.py` | Blind RSA signature tokens (RFC 9474 style), one issuer key per topic per month, nullifier per topic, relay that stores no identity, publish at 3 corroborating reports, safety topics escalate at once |
| Skill passport | `saakshi/passport.py`, `web/verify/` | W3C-VC-shaped credential signed with Ed25519, issued automatically from production data, QR, offline browser verification, revocation list, JD matching |
| Edge events | `saakshi/edge.py`, `scripts/edge_sim.py` | Box-signed events; a privacy guard rejects any image, face, video or identity field |
| Console + SDG 8 | `saakshi/console.py` | Exceptions sorted by legal risk; scorecard for targets 8.2, 8.3, 8.5, 8.6, 8.7, 8.8 |

**Stubbed for the hackathon:** the biometric device (replayed punches), WhatsApp/SMS (receipts
are stored in a wallet table that stands in for the worker's phone), Bhashini (browser speech
APIs stand in), the Jetson vision pipeline (`edge_sim.py` emits the events it would), the voice
relay (run by our team and labelled as such), and all keys live in SQLite rather than an HSM or
the worker's phone.

**Change from the design doc:** anonymous voice uses blind-signature tokens instead of Semaphore.
Same unlinkability for this use, no large circuit files to download at demo time. The doc names
this as the fallback.

**Red lines (not built, on purpose):** face recognition for discipline, emotion recognition,
toilet-break tracking, keystroke logging, individual leaderboards, union-activity monitoring.

## Caveats

- Wage tables, the 144 h cap and PF/ESI rates are illustrative Tamil Nadu values from secondary
  sources; state caps conflict across sources. Verify before any real use.
- The design rests on a research dossier whose labour-code details come from law-firm and payroll
  summaries (the government PDFs returned 403), and some citations are from memory.
