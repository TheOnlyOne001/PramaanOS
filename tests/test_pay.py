"""Fair Pay: overtime at 2x, caps, consent, deduction limit and refusal to pay on edited records."""
import pytest

from saakshi import pay
from saakshi.crypto import canonical
from saakshi.tamper import tamper_punch_out

DAY = "2026-10-27"


def punch(st, wid, day, t_in, t_out=None):
    st.ledger.append("punch.in", {"device": "t"}, worker_id=wid, ts=f"{day}T{t_in}:00+05:30")
    if t_out:
        return st.ledger.append("punch.out", {"device": "t"}, worker_id=wid, ts=f"{day}T{t_out}:00+05:30")


def request(client, wids, hours=2, day=DAY):
    r = client.post("/api/ot/requests", json={"worker_ids": wids, "date": day, "hours": hours,
                                              "requested_by": "S001", "reason": "shipment"})
    assert r.status_code == 200, r.text
    return r.json()["requests"]


def test_hours_break_rule_and_correction(st, client):
    punch(st, "W001", "2026-10-05", "08:00", "12:00")        # 4 h span: no break
    punch(st, "W001", "2026-10-06", "08:00", "17:00")        # 9 h span - 1 h break = 8
    out = punch(st, "W001", "2026-10-07", "08:00", "17:30")  # 8.5 h -> 0.5 OT
    rows = {r["day"]: r for r in pay.hours("W001", "2026-10-01", "2026-10-31")}
    assert rows["2026-10-05"]["worked_hours"] == 4
    assert rows["2026-10-06"]["worked_hours"] == 8 and rows["2026-10-06"]["ot_hours"] == 0
    assert rows["2026-10-07"]["ot_hours"] == 0.5
    client.post("/api/punch/correction", json={"worker_id": "W001", "corrects_seq": out["seq"],
                                               "new_ts": "2026-10-07T17:00:00+05:30", "reason": "clock drift", "approver": "S001"})
    row = {r["day"]: r for r in pay.hours("W001", "2026-10-01", "2026-10-31")}["2026-10-07"]
    assert row["ot_hours"] == 0 and row["corrected"]


def test_ot_priced_at_exactly_2x(st, client):
    rid = request(client, ["W001"])[0]["request_id"]
    client.post(f"/api/ot/requests/{rid}/consent", json={"decision": "accept"})
    punch(st, "W001", DAY, "08:00", "19:00")  # 11 h span - 1 h break = 10 h -> 2 h OT
    t = client.get("/api/pay/W001/today", params={"day": DAY}).json()
    rate = 12400 / 26 / 8
    assert t["ot_hours"] == 2
    assert t["ot_earned"] == pytest.approx(round(2 * 2 * rate, 2))
    assert t["earned_today"] == pytest.approx(round(8 * rate + 2 * 2 * rate, 2))


def test_cap_near_warning_and_blocking(st, client):
    for wid, h in (("W002", 136), ("W003", 143)):
        st.ledger.append("ot.opening_balance", {"quarter": "2026-Q4", "hours": h, "source": "test"}, worker_id=wid, receipt=False)
    res = {r["worker_id"]: r for r in request(client, ["W001", "W002", "W003"])}
    assert res["W001"]["status"] == "pending" and not res["W001"]["warnings"]
    assert res["W002"]["status"] == "pending" and "Near the quarterly cap" in res["W002"]["warnings"][0]
    assert res["W003"]["status"] == "blocked" and "breach" in res["W003"]["warnings"][0]
    r = client.post(f"/api/ot/requests/{res['W003']['request_id']}/consent", json={"decision": "accept"})
    assert r.status_code == 409  # a blocked request cannot be accepted


def test_consent_signed_by_worker_key(st, client):
    rid = request(client, ["W001"])[0]["request_id"]
    body = client.post(f"/api/ot/requests/{rid}/consent",
                       json={"decision": "accept", "channel": "voice", "transcript": "ஆம்"}).json()
    ev = body["event"]
    assert body["request"]["status"] == "accepted"
    msg = canonical({"request_id": rid, "decision": "accept", "worker_id": "W001"})
    assert st.keys.verify("worker:W001", msg, ev["payload"]["worker_sig"])
    assert not st.keys.verify("worker:W002", msg, ev["payload"]["worker_sig"])
    assert "ஏற்றீர்கள்" in body["receipt"]["text"]
    assert client.post(f"/api/ot/requests/{rid}/consent", json={"decision": "decline"}).status_code == 409


def test_decline_then_unconsented_ot_flagged_but_paid(st, client):
    rid = request(client, ["W001"])[0]["request_id"]
    client.post(f"/api/ot/requests/{rid}/consent", json={"decision": "decline"})
    punch(st, "W001", DAY, "08:00", "19:00")
    row = pay.hours("W001", DAY, DAY)[0]
    assert row["ot_hours"] == 2 and row["unconsented_ot_hours"] == 2
    slip = pay.payslip("W001", "2026-10")
    check = next(c for c in slip["checks"] if c["name"] == "Overtime consent")
    assert not check["ok"] and "without signed consent" in check["detail"]
    assert slip["lines"][1]["amount"] > 0  # still paid at 2x


def test_fatigue_blocks_more_than_14h_in_7_days(st, client):
    for d in ("2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"):
        punch(st, "W001", d, "07:00", "20:00")  # 12 h worked -> 4 h OT each
    req = request(client, ["W001"])[0]
    assert req["status"] == "blocked" and "Fatigue" in req["warnings"][-1]


def test_deduction_cap_blocks(st, monkeypatch):
    punch(st, "W001", "2026-10-05", "08:00", "17:00")
    monkeypatch.setitem(pay.RULES, "pf_rate", 0.9)  # an absurd deduction must be refused
    slip = pay.payslip("W001", "2026-10")
    assert slip["blocked"] and not next(c for c in slip["checks"] if c["name"] == "Deduction cap")["ok"]


def test_payslip_blocked_after_direct_db_edit(st):
    punch(st, "W001", "2026-10-05", "08:00", "19:41")
    assert not pay.payslip("W001", "2026-10")["blocked"]
    tamper_punch_out(st.conn, "W001")
    slip = pay.payslip("W001", "2026-10")
    assert slip["blocked"] and not slip["integrity"]["ok"]
    assert "edited after signing" in slip["checks"][0]["detail"]
    assert "hold" in slip["explanation"]["en"]


def test_seed_demo_state(st, client):
    pay.seed_demo(st)
    used = {r["worker_id"]: r for r in pay.cap_status(DAY)}
    assert used["W002"]["status"] == "near" and used["W003"]["status"] == "near"
    res = {r["worker_id"]: r for r in request(client, ["W001", "W002", "W003"])}
    assert all(r["status"] == "pending" for r in res.values())
    assert not res["W001"]["warnings"] and res["W002"]["warnings"] and res["W003"]["warnings"]
    f = {c["name"]: c for c in pay.fairness("2026-10")["checks"]}
    assert not f["Deposits match deductions"]["ok"]
    assert set(f["Deposits match deductions"]["workers"]) == {"W003", "W004", "W006"}
    assert all(c["ok"] for n, c in f.items() if n != "Deposits match deductions"), f
