"""Pay disputes: open → assign → resolve as signed events, the payslip status, correction line and per-line explain."""
import pytest

from saakshi.pay import disputes

PERIOD = "2026-10"


def punch(st, wid, day, t_in, t_out):
    st.ledger.append("punch.in", {"device": "t"}, worker_id=wid, ts=f"{day}T{t_in}:00+05:30")
    return st.ledger.append("punch.out", {"device": "t"}, worker_id=wid, ts=f"{day}T{t_out}:00+05:30")


@pytest.fixture
def worked(st):
    """W001 worked three days in October, one with 30 minutes past the 8 h day."""
    punch(st, "W001", "2026-10-05", "08:00", "17:00")
    punch(st, "W001", "2026-10-06", "08:00", "17:00")
    return punch(st, "W001", "2026-10-07", "08:00", "17:30")


def slip(client, wid="W001"):
    r = client.get(f"/api/pay/{wid}/payslip", params={"period": PERIOD})
    assert r.status_code == 200, r.text
    return r.json()


def open_case(client, wid="W001", **kw):
    body = {"period": PERIOD, "line": "Overtime (2×)", "amount_questioned": 250, "note": "I stayed late on the 7th", **kw}
    r = client.post(f"/api/pay/{wid}/disputes", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow_correction_changes_net_and_status(st, client, worked):
    before = slip(client)
    assert before["status"] == "estimated" and before["status_label"]["en"] == "Estimated"
    assert before["open_disputes"] == []

    c = open_case(client)
    assert c["case_id"] == "PAY-0001" and c["status"] == "open" and c["owner"] == disputes.DEFAULT_OWNER
    assert c["outcome"] is None and c["resolved_at"] is None and c["correction_amount"] is None
    s = slip(client)
    assert s["status"] == "under_review" and s["open_disputes"] == ["PAY-0001"]
    assert set(s["status_label"]) == {"en", "ta", "hi", "or"}

    r = client.post("/api/disputes/PAY-0001/assign", json={"owner": "Priya, payroll"})
    assert r.status_code == 200 and r.json()["status"] == "assigned" and r.json()["owner"] == "Priya, payroll"
    assert slip(client)["status"] == "under_review"

    r = client.post("/api/disputes/PAY-0001/resolve", json={"outcome": "corrected", "note": "OT on the 7th missed", "correction_amount": 59.62})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "resolved" and c["outcome"] == "corrected" and c["correction_amount"] == 59.62 and c["resolved_at"]

    after = slip(client)
    assert after["net"] == pytest.approx(before["net"] + 59.62)
    assert after["gross"] == pytest.approx(before["gross"] + 59.62)
    line = next(li for li in after["lines"] if li["label"] == "Correction (case PAY-0001)")
    assert line["amount"] == 59.62 and line["explain"]["sources"]
    assert after["status"] == "estimated" and after["open_disputes"] == []

    # Timeline: three signed steps, each with a ledger seq and a worker receipt.
    tl = c["timeline"]
    assert [t["kind"] for t in tl] == ["opened", "assigned", "resolved"]
    seqs = [t["seq"] for t in tl]
    assert seqs == sorted(seqs)
    for t, kind in zip(tl, ("dispute.opened", "dispute.assigned", "dispute.resolved"), strict=True):
        ev = st.ledger.get(t["seq"])
        assert ev["type"] == kind and ev["worker_id"] == "W001" and ev["payload"]["case_id"] == "PAY-0001"
        assert t["ts"] and t["by"] and t["text"]
    receipts = {r["seq"]: r["type"] for r in st.conn.execute("SELECT seq, type FROM wallet_receipts WHERE worker_id='W001'")}
    assert all(s in receipts for s in seqs)
    assert "pay.adjustment" in receipts.values()

    # The worker's view and the console's view are the same case.
    mine = client.get("/api/pay/W001/disputes").json()
    console = client.get("/api/disputes", params={"status": "resolved"}).json()
    assert mine[0]["timeline"] == console[0]["timeline"] == disputes.case("PAY-0001")["timeline"]
    assert console[0]["worker_name"].startswith("Meena")
    assert client.get("/api/disputes", params={"status": "open"}).json() == []
    assert disputes.list_cases()[0]["case_id"] == "PAY-0001"

    # Approved after a pay run, then paid.
    run = client.post("/api/pay/run", params={"period": PERIOD}).json()
    w1 = next(r for r in run["results"] if r["worker_id"] == "W001")
    assert w1["net"] == pytest.approx(after["net"])
    assert slip(client)["status"] == "approved"
    r = client.post(f"/api/pay/run/{PERIOD}/paid")
    assert r.status_code == 200, r.text
    assert any(p["worker_id"] == "W001" for p in r.json()["paid"])
    paid = slip(client)
    assert paid["status"] == "paid" and paid["status_label"]["en"] == "Paid"
    again = client.post(f"/api/pay/run/{PERIOD}/paid").json()
    assert not again["paid"] and all(s["reason"] == "already paid" for s in again["skipped"])

    # Re-resolving is refused, and the chain still verifies after the whole flow.
    assert client.post("/api/disputes/PAY-0001/resolve", json={"outcome": "explained", "note": "x"}).status_code == 409
    assert client.post("/api/disputes/PAY-0001/assign", json={"owner": "x"}).status_code == 409
    assert st.ledger.verify(full=True)["ok"]


def test_explained_outcome_adds_no_line(st, client, worked):
    before = slip(client)
    open_case(client)
    r = client.post("/api/disputes/PAY-0001/resolve", json={"outcome": "explained", "note": "Paid in the next cycle"})
    assert r.status_code == 200 and r.json()["outcome"] == "explained" and r.json()["correction_amount"] is None
    after = slip(client)
    assert after["net"] == before["net"] and len(after["lines"]) == len(before["lines"])
    assert r.json()["timeline"][-1]["text"].startswith("Explained")


def test_corrected_needs_an_amount_and_paid_needs_a_run(client, worked):
    open_case(client)
    r = client.post("/api/disputes/PAY-0001/resolve", json={"outcome": "corrected", "note": "x"})
    assert r.status_code == 422
    assert client.post("/api/disputes/PAY-9999/assign", json={"owner": "x"}).status_code == 404
    assert client.get("/api/disputes", params={"status": "nope"}).status_code == 422
    assert client.post("/api/pay/W001/disputes", json={"period": PERIOD, "line": "x", "amount_questioned": -1}).status_code == 422
    assert client.post("/api/pay/W001/disputes", json={"period": PERIOD, "line": "x", "amount_questioned": 1,
                                                       "note": "n" * 301}).status_code == 422
    assert client.post("/api/pay/run/2026-10/paid").status_code == 409


def test_due_date_skips_sundays(client, worked):
    assert disputes.due_date("2026-10-29") == "2026-11-02"   # Thu → Fri, Sat, (Sun), Mon
    assert disputes.due_date("2026-10-24") == "2026-10-28"   # Sat → (Sun), Mon, Tue, Wed
    assert disputes.due_date("2026-10-25") == "2026-10-28"   # opened on a Sunday
    assert disputes.due_date("2026-10-26") == "2026-10-29"   # Mon → Tue, Wed, Thu
    c = open_case(client, ts="2026-10-29T10:00:00+05:30")
    assert c["due"] == "2026-11-02" and c["created"].startswith("2026-10-29")


def test_explain_on_every_line_with_sources(st, client, worked):
    st.ledger.append("punch.correction", {"corrects_seq": worked["seq"], "new_ts": "2026-10-07T17:00:00+05:30",
                                          "reason": "clock drift", "approver": "S001"}, worker_id="W001")
    s = slip(client)
    for item in s["lines"] + s["deductions"]:
        ex = item["explain"]
        assert set(ex) == {"summary", "days_worked", "hours", "rate", "rate_label", "sources", "corrections", "checks"}
        assert set(ex["summary"]) == {"en", "ta", "hi", "or"} and all(ex["summary"].values())
        assert ex["sources"] and len(ex["sources"]) <= 20
        assert all(set(src) == {"seq", "ts", "type"} for src in ex["sources"])
        assert ex["corrections"] and ex["corrections"][0]["reason"] == "clock drift"
    basic, ot = s["lines"][0], s["lines"][1]
    assert basic["explain"]["days_worked"] == 3 and basic["explain"]["summary"]["en"].startswith("3 days at ₹")
    assert "Overtime consent" in ot["explain"]["checks"]
    assert "Deduction cap" in s["deductions"][0]["explain"]["checks"]


def _token(c, role, wid=None):
    r = c.post("/api/auth/demo-login", json={"role": role, "worker_id": wid})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_policy_worker_opens_own_only_hr_resolves(auth_client):
    w1, hr, sup, aud = (_token(auth_client, "worker", "W001"), _token(auth_client, "hr"),
                        _token(auth_client, "supervisor"), _token(auth_client, "auditor"))
    body = {"period": PERIOD, "line": "Basic + DA", "amount_questioned": 100, "note": "one day missing"}
    assert auth_client.post("/api/pay/W002/disputes", json=body, headers=w1).status_code == 403
    assert auth_client.post("/api/pay/W001/disputes", json=body, headers=hr).status_code == 403
    r = auth_client.post("/api/pay/W001/disputes", json=body, headers=w1)
    assert r.status_code == 200, r.text
    cid = r.json()["case_id"]
    assert r.json()["timeline"][0]["by"].endswith("(W001)")
    assert auth_client.get("/api/pay/W001/disputes", headers=w1).status_code == 200
    assert auth_client.get("/api/pay/W002/disputes", headers=w1).status_code == 403
    assert auth_client.get("/api/disputes", headers=w1).status_code == 403
    assert auth_client.get("/api/disputes", headers=aud).status_code == 200
    assert auth_client.post(f"/api/disputes/{cid}/assign", json={"owner": "x"}, headers=w1).status_code == 403
    assert auth_client.post(f"/api/disputes/{cid}/assign", json={"owner": "x"}, headers=aud).status_code == 403
    assert auth_client.post(f"/api/disputes/{cid}/assign", json={"owner": "Murugan"}, headers=sup).status_code == 200
    res = {"outcome": "corrected", "note": "fixed", "correction_amount": 476.92}
    assert auth_client.post(f"/api/disputes/{cid}/resolve", json=res, headers=w1).status_code == 403
    assert auth_client.post(f"/api/disputes/{cid}/resolve", json=res, headers=sup).status_code == 403
    r = auth_client.post(f"/api/disputes/{cid}/resolve", json=res, headers=hr)
    assert r.status_code == 200, r.text
    assert r.json()["timeline"][-1]["by"] == "HR H001"
    assert auth_client.post(f"/api/pay/run/{PERIOD}/paid", headers=sup).status_code == 403
    assert auth_client.post(f"/api/pay/run/{PERIOD}/paid", headers=w1).status_code == 403
