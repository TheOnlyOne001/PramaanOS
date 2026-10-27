import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VERIFY_JS = ROOT / "web" / "verify" / "verify.js"
NACL_JS = ROOT / "web" / "verify" / "vendor" / "nacl-fast.min.js"

GOOD = {"operation": "overlock", "pieces": 640, "sam": 0.5, "minutes": 420, "defects": 9}  # eff .76, dr .014
BAD_EFF = {"operation": "overlock", "pieces": 500, "sam": 0.5, "minutes": 420, "defects": 5}  # eff .595


def _post_day(client, wid, day, body=GOOD):
    r = client.post("/api/production", json={"worker_id": wid, **body, "ts": f"{day}T17:00:00+05:30"})
    assert r.status_code == 200, r.text
    return r.json()


def _issue(client, wid="W001"):
    out = None
    for d in ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"):
        out = _post_day(client, wid, d)
    assert out["issued"]
    return out["issued"]


def test_auto_issue_exactly_at_threshold_and_not_twice(client, st):
    days = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"]
    for d in days:
        r = _post_day(client, "W001", d)
        assert r["issued"] is None
    # a bad day does not count
    assert _post_day(client, "W001", "2026-10-23", BAD_EFF)["issued"] is None
    p = client.get("/api/passport/W001").json()
    ov = next(x for x in p["progress"] if x["skill"] == "overlock")
    assert ov["days_met"] == 4 and not ov["met"] and ov["days_needed"] == 5
    r = _post_day(client, "W001", "2026-10-24")
    vc = r["issued"]
    assert vc and vc["credentialSubject"]["skill"] == "overlock" and vc["credentialSubject"]["level"] == "U"
    assert vc["credentialSubject"]["evidence"]["days"] == 5
    assert vc["credentialSubject"]["evidenceLevel"] == 3
    assert r["efficiency"] == pytest.approx(0.762, abs=1e-3)
    # not twice
    assert _post_day(client, "W001", "2026-10-26")["issued"] is None
    p = client.get("/api/passport/W001").json()
    assert len(p["credentials"]) == 1
    # ledger has a credential.issued event with a Tamil receipt
    evs = st.ledger.events(worker_id="W001", type="credential.issued")
    assert len(evs) == 1 and evs[0]["payload"]["credential_id"] == vc["id"]
    rc = st.conn.execute("SELECT text, text_en FROM wallet_receipts WHERE seq=?", (evs[0]["seq"],)).fetchone()
    assert "ஓவர்லாக்கில் சுயமாக" in rc["text"] and rc["text_en"].startswith("Independent on overlock")


def test_progress_from_ledger_events_written_directly(client, st):
    for d in ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"):
        st.ledger.append("production.count", GOOD, worker_id="W006", ts=f"{d}T17:00:00+05:30")
    p = client.get("/api/passport/W006").json()
    assert p["progress"][0]["met"] is True and p["credentials"] == []


def test_vc_shape_and_python_signature(client, st):
    from saakshi import passport
    from saakshi.crypto import canonical
    vc = _issue(client)
    assert vc["@context"] == ["https://www.w3.org/ns/credentials/v2"]
    assert vc["type"] == ["VerifiableCredential", "SkillCredential"]
    assert vc["id"].startswith("urn:saakshi:cred:")
    assert vc["issuer"]["id"].startswith("did:key:site-issuer:")
    assert vc["credentialSubject"]["id"].startswith("urn:saakshi:worker:") and "W001" not in json.dumps(vc)
    assert vc["proof"]["type"] == "Ed25519Signature2020"
    assert passport.verify_vc(vc)
    # stored copy == served copy
    assert client.get(f"/api/passport/credentials/{vc['id']}").json() == vc
    bad = copy.deepcopy(vc)
    bad["credentialSubject"]["level"] = "O"
    assert not passport.verify_vc(bad)

    def no_floats(v):
        if isinstance(v, float):
            return False
        if isinstance(v, dict):
            return all(no_floats(x) for x in v.values())
        if isinstance(v, list):
            return all(no_floats(x) for x in v)
        return True
    assert no_floats(vc)
    # QR payload round-trips
    url = passport.verify_url(vc)
    assert url.startswith("http://localhost:8000/verify/#")
    assert json.loads(passport.b64url_decode(url.split("#", 1)[1])) == vc
    assert canonical(json.loads(passport.b64url_decode(url.split("#", 1)[1]))) == canonical(vc)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_vc_verifies_in_node_and_tampered_fails(client, tmp_path):
    from saakshi import passport
    from saakshi.crypto import canonical
    vc = _issue(client)
    reg = client.get("/api/passport/issuers").json()
    tampered = copy.deepcopy(vc)
    tampered["credentialSubject"]["name"] = "Someone Else"
    (tmp_path / "vc.json").write_text(json.dumps(vc, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "bad.json").write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "reg.json").write_text(json.dumps(reg), encoding="utf-8")
    b64 = passport.b64url(canonical(vc))
    script = f"""
const fs = require('fs');
const V = require({json.dumps(str(VERIFY_JS))});
const nacl = require({json.dumps(str(NACL_JS))});
const vc = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'vc.json'))}, 'utf8'));
const bad = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'bad.json'))}, 'utf8'));
const reg = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'reg.json'))}, 'utf8'));
const fromHash = V.decodeVC('http://x/verify/#' + {json.dumps(b64)});
process.stdout.write(JSON.stringify({{
  signing: V.signingString(vc),
  full: V.canonicalize(vc),
  ok: V.verifyVC(vc, reg, nacl).valid,
  okHash: V.verifyVC(fromHash, reg, nacl).valid,
  bad: V.verifyVC(bad, reg, nacl),
  unknownIssuer: V.verifyVC(vc, {{issuers: []}}, nacl).valid,
  revoked: V.isRevoked(vc, {{bitmap: [1]}}),
}}));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout)
    # byte-for-byte canonical match with Python
    assert res["signing"].encode() == passport.vc_signing_bytes(vc)
    assert res["full"].encode() == canonical(vc)
    assert res["ok"] is True and res["okHash"] is True
    assert res["bad"]["valid"] is False and "Signature" in res["bad"]["reason"]
    assert res["unknownIssuer"] is False
    assert res["revoked"] is (vc["credentialStatus"]["statusListIndex"] == "0")


def test_revocation_shows_in_status(client, st):
    vc = _issue(client)
    idx = int(vc["credentialStatus"]["statusListIndex"])
    s = client.get("/api/passport/status").json()
    assert s["bitmap"][idx] == 0
    r = client.post(f"/api/passport/credentials/{vc['id']}/revoke", json={"reason": "left the company"})
    assert r.status_code == 422  # only for fraud
    r = client.post(f"/api/passport/credentials/{vc['id']}/revoke",
                    json={"reason": "Fraud: production counts were falsified"})
    assert r.status_code == 200, r.text
    s = client.get("/api/passport/status").json()
    assert s["bitmap"][idx] == 1 and idx in s["revoked"]
    p = client.get("/api/passport/W001").json()
    assert p["credential_status"][vc["id"]]["revoked"] is True
    assert st.ledger.events(worker_id="W001", type="credential.revoked")
    # fraudulent evidence does not re-issue on the next production post
    assert _post_day(client, "W001", "2026-10-26")["issued"] is None


def test_match_returns_gaps_and_training(client):
    _issue(client, "W001")
    r = client.post("/api/passport/match", json={"worker_id": "W001",
                                                 "job_description": "Experienced overlock and flatlock operator; quality checking"})
    assert r.status_code == 200
    m = r.json()
    skills = {x["skill"] for x in m["required"]}
    assert skills == {"overlock", "flatlock", "checking"}
    assert all(x["level"] == "U" for x in m["required"])
    assert [x["skill"] for x in m["matched"]] == ["overlock"] and m["matched"][0]["evidence_level"] == 3
    assert {g["skill"] for g in m["gaps"]} == {"flatlock", "checking"}
    assert {t["skill"] for t in m["training"]} == {"flatlock", "checking"}
    assert 0 < m["fit"] < 100
    m2 = client.post("/api/passport/match", json={"worker_id": "W001",
                                                  "job_description": "Overlock operator who can train new joiners"}).json()
    assert m2["required"][0]["level"] == "O" and m2["gaps"]
    m3 = client.post("/api/passport/match", json={"worker_id": "W001", "job_description": "overlock trainee"}).json()
    assert m3["required"][0]["level"] == "I" and m3["fit"] == 100


def test_qr_endpoint_returns_svg(client):
    vc = _issue(client)
    r = client.get(f"/api/passport/credentials/{vc['id']}/qr", params={"base": "http://192.168.1.5:8000"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text and "<path" in r.text
    assert client.get("/api/passport/credentials/urn:saakshi:cred:nope/qr").status_code == 404


def test_issuers_coverage_expiring_and_seed(st):
    from saakshi import passport
    passport.seed_demo(st)
    p1 = passport.passport("W001")
    ov = next(x for x in p1["progress"] if x["skill"] == "overlock")
    assert ov["days_met"] == 4 and not ov["met"]
    assert not [c for c in p1["credentials"] if "SkillCredential" in c["type"]]
    p2 = passport.passport("W002")
    assert [c for c in p2["credentials"] if "SkillCredential" in c["type"]]
    a = next(x for x in passport.passport("W006")["progress"] if x["skill"] == "overlock")
    assert a["days_met"] == 2
    cov = passport.coverage()
    assert {s["skill"] for s in cov["single_points_of_failure"]} >= {"overlock"}
    assert next(s for s in cov["single_points_of_failure"] if s["skill"] == "overlock")["worker_id"] == "W002"
    exp = passport.expiring(21)
    assert exp and all(e["days_left"] <= 21 for e in exp)
    assert st.ledger.verify()["ok"]
    # one more good shift for Meena today issues it live
    out = passport.record_production({"worker_id": "W001", **GOOD, "ts": "2026-10-27T17:00:00+05:30"})
    assert out["issued"] and out["issued"]["credentialSubject"]["name"] == "Meena Selvam"
    assert not [s for s in passport.coverage()["single_points_of_failure"] if s["skill"] == "overlock"]
