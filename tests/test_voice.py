"""Voice: blind-signature tokens, unlinkability, double-spend, threshold, escalation, scrub, JS/Python FDH."""
import json
import math
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

from saakshi import voice
from saakshi.voice_client import VoiceClient, VoiceClientError, blind, fdh, to_hex, unblind, verify

ROOT = Path(__file__).resolve().parent.parent
MONTH = "2026-10"


def _key(topic="water"):
    return voice.key(MONTH, topic)


def test_blind_signature_round_trip(st):
    k = _key()
    m = secrets.token_bytes(32)
    b, r = blind(MONTH, "water", m, k["n"], k["e"])
    s = unblind(pow(b, k["d"], k["n"]), r, k["n"])
    assert verify(MONTH, "water", m, s, k["n"], k["e"])
    assert not verify(MONTH, "toilets", m, s, k["n"], k["e"])  # bound to the topic
    assert not verify(MONTH, "water", secrets.token_bytes(32), s, k["n"], k["e"])


def test_unlinkable(client, st):
    """Perfect blindness: with the issuer's private key, every pairing of issuance and redemption is consistent."""
    topic = "water"
    k = voice.key(MONTH, topic)
    n, e, d = k["n"], k["e"], k["d"]
    issued, redeemed = [], []
    for wid in ("W001", "W002"):
        m = secrets.token_bytes(32)
        b, r = blind(MONTH, topic, m, n, e)
        res = client.post("/api/voice/issue", json={"worker_id": wid, "month": MONTH, "blinded": {topic: to_hex(b)}})
        assert res.status_code == 200, res.text
        issued.append((wid, b, int(res.json()["signatures"][topic], 16)))
        redeemed.append((m, unblind(int(res.json()["signatures"][topic], 16), r, n)))
    for wid, b, s_blind in issued:
        for m, s in redeemed:
            r_prime = (s_blind * pow(s, -1, n)) % n          # the blinding factor this pairing would imply
            assert math.gcd(r_prime, n) == 1
            assert (fdh(MONTH, topic, m, n) * pow(r_prime, e, n)) % n == b  # ...and it is a valid one
    # The issuer kept no blinded values at all
    cols = [c[1] for c in st.conn.execute("PRAGMA table_info(voice_issuance)")]
    assert set(cols) == {"worker_id", "topic", "month"}


def test_report_flow_threshold_and_no_identity(client, st):
    phones = {w: VoiceClient(client) for w in ("W001", "W002", "W005")}
    for w, p in phones.items():
        assert "water" in p.get_tokens(w, topics=["water", "safety"])
    r1 = phones["W001"].report("water", "Drinking water runs out by 3 pm on our floor", "ta")
    assert r1["status"] == "waiting" and r1["corroborations"] == 1 and r1["threshold"] == 3
    assert r1["relay"] == "demo relay run by the Saakshi team"
    th = client.get("/api/voice/themes").json()
    assert th[0]["topic"] == "water" and th[0]["count"] == 1 and not th[0]["published"] and "reports" not in th[0]
    phones["W002"].report("water", "Same here, the can is empty after lunch")
    assert not voice.themes()[0]["published"]
    r3 = phones["W005"].report("water", "No water after 3")
    assert r3["status"] == "published" and r3["corroborations"] == 3
    t = voice.themes()[0]
    assert t["published"] and len(t["reports"]) == 3 and t["reports"][0]["ts"].endswith(":00:00+05:30")
    # case key follows the theme
    c = client.get(f"/api/voice/cases/{r1['case_key']}").json()
    assert c["status"] == "published" and c["corroborations"] == 3
    # no identity anywhere in the relay store or the ledger event
    cols = [c[1] for c in st.conn.execute("PRAGMA table_info(voice_reports)")]
    assert not {"worker_id", "ip", "user_agent", "ts"} & set(cols)
    rows = [dict(r) for r in st.conn.execute("SELECT * FROM voice_reports")]
    blob = json.dumps(rows)
    assert not any(w in blob for w in ("W001", "W002", "W005", "Meena", "Lakshmi", "Kavitha"))
    evs = st.ledger.events(type="voice.report")
    assert len(evs) == 3 and all(ev["worker_id"] is None for ev in evs)
    assert set(evs[0]["payload"]) == {"topic", "month", "nullifier", "text_hash"}
    assert "Drinking" not in json.dumps(evs)
    assert st.ledger.verify()["ok"]
    # respond -> board
    res = client.post("/api/voice/themes/water/respond", json={"text": "Second water can added at 2 pm", "by": "HR"})
    assert res.status_code == 200, res.text
    assert client.get(f"/api/voice/cases/{r1['case_key']}").json()["response"]["text"].startswith("Second")
    assert voice.board()[0]["we_did"] == "Second water can added at 2 pm"
    assert st.ledger.events(type="voice.response")


def test_double_spend_and_reissue(client):
    p = VoiceClient(client)
    p.get_tokens("W003", topics=["pay"])
    m, s = p.token("pay")
    body = {"topic": "pay", "month": MONTH, "token": m.hex(), "signature": to_hex(s), "text": "Pay slip missing"}
    assert client.post("/api/relay/voice/reports", json=body).status_code == 200
    again = client.post("/api/relay/voice/reports", json={**body, "text": "again"})
    assert again.status_code == 409 and "already spoken" in again.json()["detail"]
    with pytest.raises(VoiceClientError) as ei:
        VoiceClient(client).get_tokens("W003", topics=["pay"])
    assert ei.value.status_code == 409


def test_issue_rejects_non_workers_and_tampered_signatures(client):
    k = _key("food")
    b, _ = blind(MONTH, "food", secrets.token_bytes(32), k["n"], k["e"])
    for wid in ("S001", "X999"):
        res = client.post("/api/voice/issue", json={"worker_id": wid, "month": MONTH, "blinded": {"food": to_hex(b)}})
        assert 400 <= res.status_code < 500
    p = VoiceClient(client)
    p.get_tokens("W004", topics=["food"])
    m, s = p.token("food")
    bad = {"topic": "food", "month": MONTH, "token": m.hex(), "signature": to_hex(s + 1), "text": "Canteen rice is cold"}
    assert client.post("/api/relay/voice/reports", json=bad).status_code == 403
    wrong_topic = {**bad, "signature": to_hex(s), "topic": "water"}
    assert 400 <= client.post("/api/relay/voice/reports", json=wrong_topic).status_code < 500
    forged = {**bad, "token": secrets.token_bytes(32).hex(), "signature": to_hex(s)}
    assert client.post("/api/relay/voice/reports", json=forged).status_code == 403


def test_safety_escalates_on_first_report(client):
    p = VoiceClient(client)
    p.get_tokens("W006", topics=["safety", "harassment"])
    r = p.report("safety", "Fire exit behind line is blocked with cartons")
    assert r["status"] == "escalated" and r["route_to"]["to"] == "Safety officer"
    t = [x for x in voice.themes() if x["topic"] == "safety"][0]
    assert t["escalated"] and t["reports"][0]["text"].startswith("Fire exit")
    h = p.report("harassment", "Comments about women at the cutting table", "or")
    assert h["status"] == "escalated" and "POSH" in h["route_to"]["to"]
    assert "named complainant" in h["route_to"]["note"]


def test_group_size_guard(client, st):
    p = VoiceClient(client)
    p.get_tokens("W001", topics=["safety"])
    p.report("safety", "Needle guard missing")
    assert voice.themes()
    st.conn.execute("UPDATE workers SET active=0 WHERE id IN ('W004','W005','W006','W007')")
    assert voice.themes() == []


def test_scrub(client):
    res = client.post("/api/voice/scrub", json={
        "text": "I am the only woman on line 4 and my supervisor Murugan shouts. Meena Selvam saw it. Call 98765 43210, W001"})
    out = res.json()
    s = out["suggested"]
    for gone in ("only woman", "line 4", "Murugan", "Meena", "Selvam", "98765", "W001"):
        assert gone not in s, (gone, s)
    assert "[a worker]" in s and "[my line]" in s
    assert {f["reason"] for f in out["flags"]} >= {"describes a group of one", "names a line", "names a person"}
    assert client.post("/api/voice/scrub", json={"text": "Water runs out by 3 pm"}).json()["flags"] == []
    assert "[my line]" in voice.scrub("problem on line no 4")["suggested"]


def test_seed_demo_board(st):
    voice.seed_demo(st)
    b = voice.board()
    assert b and b[0]["topic"] == "toilets" and b[0]["month"] == "2026-09" and b[0]["count"] == 4
    assert b[0]["we_did"].startswith("Two more cleaning shifts")
    old = voice.themes("2026-09")[0]
    assert old["published"] and len(old["reports"]) == 4
    assert voice.themes() == []  # nothing for the current month
    # the seeded workers already got their September tokens; issuance stored no blinded values
    assert st.conn.execute("SELECT COUNT(*) FROM voice_issuance WHERE month='2026-09'").fetchone()[0] == 40
    assert st.ledger.verify()["ok"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_fdh_matches_python(st, tmp_path):
    k = _key()
    n, e, d = k["n"], k["e"], k["d"]
    m = bytes(range(32))
    r = 0x1234567890ABCDEF1234567890ABCDEF
    b_py = (fdh(MONTH, "water", m, n) * pow(r, e, n)) % n
    s_blind = pow(b_py, d, n)
    script = tmp_path / "fdh.js"
    script.write_text(f"""
globalThis.window = globalThis;
require({json.dumps(str(ROOT / "web" / "shared" / "voice-client.js"))});
const C = window.SaakshiVoice._crypto;
(async () => {{
  const [month, topic, mHex, nHex, e, rHex, sbHex] = process.argv.slice(2);
  const n = C.hexToBig(nHex), m = C.hexToBytes(mHex);
  const h = await C.fdh(month, topic, m, n);
  const b = await C.blind(month, topic, m, n, BigInt(e), C.hexToBig(rHex));
  const s = C.unblind(C.hexToBig(sbHex), C.hexToBig(rHex), n);
  const ok = await C.verify(month, topic, m, s, n, BigInt(e));
  console.log(JSON.stringify({{fdh: C.bigToHex(h), blinded: C.bigToHex(b.blinded), s: C.bigToHex(s), ok}}));
}})();
""")
    out = subprocess.run(["node", str(script), MONTH, "water", m.hex(), to_hex(n), str(e), to_hex(r), to_hex(s_blind)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    assert js["fdh"] == to_hex(fdh(MONTH, "water", m, n))
    assert js["blinded"] == to_hex(b_py)
    assert js["ok"] and verify(MONTH, "water", m, int(js["s"], 16), n, e)
