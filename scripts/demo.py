"""The three-minute Saakshi demo, scripted end to end.

In-process (no server needed, fresh temp DB):
    python3 scripts/demo.py

Against a running server, so both dashboards update live on screen:
    uvicorn saakshi.app:app --port 8000          # in another terminal
    python3 scripts/demo.py --base http://localhost:8000 --db data/saakshi.db --pause

--pause waits for Enter between steps (for a presenter). Exits non-zero if any
step does not behave as the demo promises, so it doubles as an end-to-end test.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DAY = "2026-10-27"
T = lambda hm: f"{DAY}T{hm}:00+05:30"  # noqa: E731

BOLD, DIM, RED, GREEN, AMBER, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"
failures: list[str] = []


def say(msg):
    print(msg, flush=True)


def step(n, title, pause):
    if pause:
        input(f"\n{DIM}[Enter] for step {n}{RESET}")
    say(f"\n{BOLD}{n}. {title}{RESET}")


def check(cond, what):
    if cond:
        say(f"   {GREEN}✓{RESET} {what}")
    else:
        say(f"   {RED}✗ {what}{RESET}")
        failures.append(what)


def ok(r, *codes):
    codes = codes or (200,)
    if r.status_code not in codes:
        raise SystemExit(f"{RED}{r.request.method} {r.request.url} → {r.status_code}: {r.text[:400]}{RESET}")
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="URL of a running server; omit to run in-process")
    ap.add_argument("--db", help="SQLite path the server uses (needed with --base for the DB edit and the camera box key)")
    ap.add_argument("--pause", action="store_true")
    a = ap.parse_args()

    if a.base:
        import httpx
        http = httpx.Client(base_url=a.base, timeout=30)
        db_path = a.db or str(ROOT / "data" / "saakshi.db")
    else:
        db_path = os.path.join(tempfile.mkdtemp(), "demo.db")
        os.environ["SAAKSHI_DB"] = db_path
        from fastapi.testclient import TestClient
        from saakshi.app import app
        http = TestClient(app)

    ok(http.post("/api/demo/reset"))
    site = ok(http.get("/api/site"))
    say(f"{DIM}{site['name']} · {site['n_events']} signed events of history · DB {db_path}{RESET}")

    # 1 ---------------------------------------------------------------------
    step(1, "Meena punches in and gets a receipt in Tamil", a.pause)
    ev = ok(http.post("/api/punch", json={"worker_id": "W001", "kind": "in", "ts": T("08:02")}))
    say(f"   📱 WhatsApp → Meena: {BOLD}{ev['receipt']['text']}{RESET}   {DIM}({ev['receipt']['text_en']}){RESET}")
    check(ev["receipt"]["lang"] == "ta" and "08:02" in ev["receipt"]["text"], "receipt in Tamil with the punch time and ref")

    # 2 ---------------------------------------------------------------------
    step(2, "Supervisor asks for 2 h overtime; console warns about the cap; Meena accepts by voice", a.pause)
    res = ok(http.post("/api/ot/requests", json={"worker_ids": ["W001", "W002", "W003"], "date": DAY, "hours": 2,
                                                 "requested_by": "S001", "reason": "Export shipment for buyer, 28 Oct",
                                                 "ts": T("17:30")}))
    for r in res["requests"]:
        cap = r.get("cap", {})
        warn = ("  " + AMBER + "; ".join(r.get("warnings", [])) + RESET) if r.get("warnings") else ""
        say(f"   {r.get('name', r['worker_id']):16} {r['status']:8} cap {cap.get('used')}→{cap.get('after')}/{cap.get('cap')} h{warn}")
    warned = [r for r in res["requests"] if r.get("warnings")]
    check(len(warned) >= 2, "console warns that two co-workers are near the cap")
    meena_req = next(r for r in res["requests"] if r["worker_id"] == "W001")
    c = ok(http.post(f"/api/ot/requests/{meena_req['request_id']}/consent",
                     json={"decision": "accept", "channel": "voice", "transcript": "ஆம், சரி", "ts": T("17:34")}))
    rc = c.get("receipt") or (c.get("event") or {}).get("receipt") or {}
    say(f"   🎙  Meena: “ஆம், சரி” → consent signed with her key. 📱 {rc.get('text', '')}")
    check((c.get("request") or {}).get("status") == "accepted", "consent recorded as a signed event")
    out = ok(http.post("/api/punch", json={"worker_id": "W001", "kind": "out", "ts": T("19:41")}))
    say(f"   📱 {out['receipt']['text']}   {DIM}({out['receipt']['text_en']}){RESET}")
    today = ok(http.get("/api/pay/W001/today", params={"day": DAY}))
    say(f"   Today: {today.get('worked_hours')} h worked, {today.get('ot_hours')} h overtime, ₹{today.get('earned_today')} earned")
    root = ok(http.post("/api/ledger/roots/publish", params={"day": DAY}))
    say(f"   Daily root for {DAY} published to workers: {DIM}{root['root'][:24]}…{RESET}")
    slip = ok(http.get("/api/pay/W001/payslip", params={"period": "2026-10"}))
    say(f"   October payslip: gross ₹{slip.get('gross')}, net ₹{slip.get('net')}, blocked={slip.get('blocked')}")
    check(not slip.get("blocked"), "payslip computes from the ledger alone")

    # 3 ---------------------------------------------------------------------
    step(3, "LIVE TAMPER TEST: someone edits her punch-out directly in the database", a.pause)
    if a.base:
        from saakshi.tamper import tamper_punch_out
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        t = tamper_punch_out(conn, "W001")
        conn.close()
    else:
        t = ok(http.post("/api/demo/tamper", json={"worker_id": "W001"}))
    say(f"   {RED}UPDATE events SET ts='{t['new_ts']}' WHERE seq={t['seq']}   -- was {t['old_ts']}{RESET}")
    v = ok(http.get("/api/ledger/verify"))
    for p in v["problems"]:
        say(f"   🚨 console: {p['kind']}: {p.get('worker_name') or ''} {p.get('type')} #{p.get('seq')} — {p['detail']}")
    check(not v["ok"] and any(p["kind"] == "content_edited" for p in v["problems"]), "employer console flags the edited event")
    check(any(p["kind"] == "root_mismatch" for p in v["problems"]), "published daily root no longer matches")
    rcheck = ok(http.post("/api/workers/W001/receipts/check", json={}))
    for m in rcheck["mismatches"]:
        say(f"   📱 worker app: your receipt says “{m['receipt_text']}” · employer record now says “{m.get('current_text')}”")
    check(not rcheck["ok"], "Meena's own receipts expose the edit")
    slip = ok(http.get("/api/pay/W001/payslip", params={"period": "2026-10"}))
    check(bool(slip.get("blocked")), "payslip refuses to compute on an edited record")

    # 4 ---------------------------------------------------------------------
    step(4, "Meena reports anonymously that drinking water runs out by 3 pm; two others corroborate", a.pause)
    from saakshi.voice_client import VoiceClient
    text = "Drinking water runs out by 3 pm on Line 4. I'm the only woman near the water point after lunch."
    scrub = ok(http.post("/api/voice/scrub", json={"text": text}))
    say(f"   scrub suggests: {scrub.get('suggested')}")
    statuses = []
    for wid, msg in (("W001", scrub.get("suggested") or text), ("W004", "No water in the can after 3 pm"),
                     ("W006", "Water finishes in the afternoon, we wait till evening")):
        vc = VoiceClient(http)
        vc.get_tokens(wid, topics=["water"])
        r = vc.report("water", msg, "en")
        statuses.append(r.get("status"))
        say(f"   report via relay → case {str(r.get('case_key'))[:10]}…  status={r.get('status')}  "
            f"{r.get('corroborations')}/{r.get('threshold')}")
    themes = ok(http.get("/api/voice/themes"))
    water = next((t for t in themes if t.get("topic") == "water"), {})
    check(water.get("published") is True, "theme reaches the console after 3 independent reports")
    check("W001" not in json.dumps(water) and "Meena" not in json.dumps(water), "no identity attached to the theme")
    from saakshi.voice_client import VoiceClientError
    vc2 = VoiceClient(http)
    vc2.get_tokens("W005", topics=["water"])
    vc2.report("water", "Water finishes by afternoon", "en")
    try:
        vc2.report("water", "Saying it twice", "en")
        check(False, "one voice per topic per month")
    except VoiceClientError as err:
        check(err.status_code in (403, 409), f"one voice per topic per month (second report refused: {err.status_code})")

    # 5 ---------------------------------------------------------------------
    step(5, "A person steps into the press zone in front of the camera", a.pause)
    from saakshi.crypto import KeyStore
    import threading
    kconn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    kconn.row_factory = sqlite3.Row
    box_keys = KeyStore(kconn, threading.RLock())
    from saakshi.edge import make_event
    e = make_event(box_keys, box_id="edge-box-1", camera="cam-07", zone="Press zone",
                   kind="restricted_zone_entry", count=1, ts=T("19:50"))
    r = ok(http.post("/api/edge/events", json=e))
    say(f"   edge box → {json.dumps({k: e[k] for k in e if k != 'sig'}, ensure_ascii=False)}")
    check(r.get("type") == "edge.event" or "seq" in r, "event signed by the box and appended to the ledger")
    bad = dict(e, face="base64-crop…")
    rb = http.post("/api/edge/events", json=bad)
    check(rb.status_code == 422, "an event carrying a face crop is refused (no video or face leaves the box)")
    kconn.close()

    # 6 ---------------------------------------------------------------------
    step(6, "Her quality data issues an 'independent on overlock' credential; a recruiter verifies it offline", a.pause)
    pr = ok(http.post("/api/production", json={"worker_id": "W001", "operation": "overlock", "pieces": 420, "sam": 0.9,
                                               "minutes": 480, "defects": 6, "ts": T("19:30")}))
    cred = pr.get("issued")
    check(bool(cred), "credential issued automatically when the threshold is met")
    if cred:
        vc_id = cred.get("id") or cred.get("credential_id")
        vcj = ok(http.get(f"/api/passport/credentials/{vc_id}")) if not cred.get("proof") else cred
        subj = vcj.get("credentialSubject", {})
        say(f"   🎓 {subj.get('name')}: {subj.get('skill')} · {subj.get('levelLabel')} · evidence: {subj.get('evidenceLabel')}")
        from saakshi.crypto import canonical, verify_sig
        issuers = ok(http.get("/api/passport/issuers"))["issuers"]
        body = {k: vcj[k] for k in vcj if k != "proof"}
        good = any(verify_sig(i["public_key_hex"], canonical(body), vcj["proof"]["proofValue"]) for i in issuers)
        check(good, "recruiter verifies the signature against the cached issuer key, no call to the issuer")
        qr = http.get(f"/api/passport/credentials/{vc_id}/qr")
        check(qr.status_code == 200 and "svg" in qr.headers.get("content-type", ""), "QR code ready to scan")
        b64 = base64.urlsafe_b64encode(canonical(vcj)).decode().rstrip("=")
        say(f"   verify link: /verify/#{b64[:40]}…")

    # 7 ---------------------------------------------------------------------
    step(7, "Close on the SDG 8 scorecard", a.pause)
    sc = ok(http.get("/api/sdg8/scorecard"))
    for t in sc["targets"]:
        val = t.get("value")
        say(f"   SDG {t['target']:4} {t['label']:32} {t['indicator'][:58]:58} {val if val is not None else '—'} {t.get('unit', '')}")
    check(len(sc["targets"]) == 6, "six SDG 8 targets tracked")
    ov = ok(http.get("/api/console/overview"))
    say(f"\n   Console exceptions: {ov['counts']}")
    for x in ov["exceptions"][:8]:
        say(f"   [{x['severity']:8}] {x['title']}")

    say("")
    if failures:
        say(f"{RED}{BOLD}{len(failures)} demo checks failed:{RESET}")
        for f in failures:
            say(f"  - {f}")
        sys.exit(1)
    say(f"{GREEN}{BOLD}All demo checks passed.{RESET}")


if __name__ == "__main__":
    main()
