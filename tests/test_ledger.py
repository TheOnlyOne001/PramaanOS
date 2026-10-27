"""The signed hash chain: every kind of direct database edit must be caught."""
import json

from saakshi.crypto import merkle_root, verify_merkle_proof
from saakshi.tamper import tamper_punch_out

DAY = "2026-10-27"


def _shift(ledger, wid="W001"):
    a = ledger.append("punch.in", {"device": "bio-gate-1"}, worker_id=wid, ts=f"{DAY}T08:02:00+05:30")
    b = ledger.append("punch.out", {"device": "bio-gate-1"}, worker_id=wid, ts=f"{DAY}T19:41:00+05:30")
    return a, b


def test_clean_ledger_verifies(st):
    _shift(st.ledger)
    st.ledger.publish_root(DAY)
    v = st.ledger.verify()
    assert v["ok"], v["problems"]
    assert v["n_events"] == 2
    assert all(r["ok"] for r in v["roots"])


def test_chain_links_and_signatures(st):
    a, b = _shift(st.ledger)
    assert b["prev_hash"] == a["hash"]
    assert st.keys.verify("site", bytes.fromhex(a["hash"]), a["sig"])


def test_receipt_in_workers_language(st):
    a, _ = _shift(st.ledger)
    r = a["receipt"]
    assert r["lang"] == "ta"
    assert r["text"] == f"வருகை 08:02 · குறிப்பு {a['ref']}"
    assert r["text_en"] == f"In 08:02 · ref {a['ref']}"


def test_naive_edit_is_caught(st):
    _shift(st.ledger)
    st.ledger.publish_root(DAY)
    t = tamper_punch_out(st.conn, "W001")
    assert t["new_ts"].endswith("T18:00:00+05:30")
    v = st.ledger.verify()
    kinds = {p["kind"] for p in v["problems"]}
    assert not v["ok"]
    assert "content_edited" in kinds and "root_mismatch" in kinds
    assert any(p["seq"] == t["seq"] and p["worker_id"] == "W001" for p in v["problems"])


def test_rehash_edit_is_still_caught(st):
    """An attacker who also recomputes the hash cannot re-sign it, and breaks the next link."""
    _shift(st.ledger)
    st.ledger.append("punch.in", {"device": "bio-gate-1"}, worker_id="W002", ts=f"{DAY}T19:50:00+05:30")
    st.ledger.publish_root(DAY)
    tamper_punch_out(st.conn, "W001", mode="rehash")
    kinds = {p["kind"] for p in st.ledger.verify()["problems"]}
    assert {"bad_signature", "broken_link", "root_mismatch"} <= kinds


def test_payload_edit_and_deletion_caught(st):
    _shift(st.ledger)
    e3 = st.ledger.append("punch.in", {"device": "bio-gate-1"}, worker_id="W002", ts=f"{DAY}T08:00:00+05:30")
    st.conn.execute("UPDATE events SET payload=? WHERE seq=1", (json.dumps({"device": "manual"}),))
    st.conn.execute("DELETE FROM events WHERE seq=2")
    kinds = {p["kind"] for p in st.ledger.verify()["problems"]}
    assert {"content_edited", "missing_events", "broken_link"} <= kinds
    assert e3["seq"] == 3


def test_worker_receipts_detect_edit(client, st):
    a = client.post("/api/punch", json={"worker_id": "W001", "kind": "in", "ts": f"{DAY}T08:02:00+05:30"}).json()
    b = client.post("/api/punch", json={"worker_id": "W001", "kind": "out", "ts": f"{DAY}T19:41:00+05:30"}).json()
    assert client.post("/api/workers/W001/receipts/check", json={}).json()["ok"]
    client.post("/api/demo/tamper", json={"worker_id": "W001"})
    res = client.post("/api/workers/W001/receipts/check", json={}).json()
    assert not res["ok"]
    m = res["mismatches"][0]
    assert m["seq"] == b["seq"] and m["kind"] == "edited"
    assert "19:41" in m["receipt_text_en"] and "18:00" in m["current_text_en"]
    # The worker's own copy of receipts can also be sent from the phone
    res2 = client.post("/api/workers/W001/receipts/check",
                       json={"receipts": [{"seq": a["seq"], "hash": a["hash"]}, {"seq": b["seq"], "hash": b["hash"]}]}).json()
    assert [x["seq"] for x in res2["mismatches"]] == [b["seq"]]


def test_correction_is_a_new_event(client, st):
    b = client.post("/api/punch", json={"worker_id": "W001", "kind": "out", "ts": f"{DAY}T19:41:00+05:30"}).json()
    c = client.post("/api/punch/correction", json={"worker_id": "W001", "corrects_seq": b["seq"],
                                                   "new_ts": f"{DAY}T19:45:00+05:30", "reason": "Gate device clock drift",
                                                   "approver": "S001"}).json()
    assert c["seq"] == b["seq"] + 1 and c["type"] == "punch.correction"
    assert st.ledger.verify()["ok"]
    assert st.ledger.get(b["seq"])["ts"].endswith("19:41:00+05:30")


def test_lookup_needs_reason_and_is_visible(client):
    assert client.post("/api/workers/W001/lookup", json={"viewer": "HR", "reason": ""}).status_code == 422
    r = client.post("/api/workers/W001/lookup", json={"viewer": "HR Priya", "reason": "Pay query"})
    assert r.status_code == 200
    log = client.get("/api/workers/W001/access-log").json()
    assert log[0]["viewer"] == "HR Priya" and log[0]["reason"] == "Pay query"
    receipts = client.get("/api/workers/W001/receipts").json()
    assert receipts[0]["type"] == "access.lookup"


def test_merkle_inclusion_proof(st):
    for i in range(5):
        st.ledger.append("punch.in", {"device": "g"}, worker_id="W00" + str(i + 1), ts=f"{DAY}T08:0{i}:00+05:30")
    p = st.ledger.inclusion_proof(3)
    assert verify_merkle_proof(p["hash"], p["proof"], p["root"])
    hashes = [e["hash"] for e in st.ledger.events(day=DAY)]
    assert p["root"] == merkle_root(hashes)
    assert not verify_merkle_proof("00" * 32, p["proof"], p["root"])
