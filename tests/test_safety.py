"""Safety reports: received → acknowledged → resolved, signed with receipts; idempotent; overdue; access control."""
from __future__ import annotations

from saakshi import events, safety
from saakshi.safety import reports as reports_mod


def _receipts(st, wid, type_):
    return [dict(r) for r in st.conn.execute("SELECT * FROM wallet_receipts WHERE worker_id=? AND type=?", (wid, type_))]


def test_report_ack_resolve_timeline_with_receipts(st, client):
    r = client.post("/api/safety/reports", json={"kind": "stop_work", "zone": "Press zone", "note": "Guard missing", "worker_id": "W003"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["report_id"].startswith("SAFE-") and rep["status"] == "received" and rep["worker_id"] == "W003"
    assert rep["acknowledged_at"] is None and rep["resolved_at"] is None and rep["overdue"] is False
    assert rep["ack_due"] > rep["received_at"]
    rid = rep["report_id"]
    a = client.post(f"/api/safety/reports/{rid}/ack", json={"note": "On my way"}).json()
    assert a["status"] == "acknowledged" and a["acknowledged_by"] and a["acknowledged_at"]
    z = client.post(f"/api/safety/reports/{rid}/resolve", json={"note": "Guard refitted"}).json()
    assert z["status"] == "resolved" and z["resolved_at"]
    assert [t["kind"] for t in z["timeline"]] == ["received", "acknowledged", "resolved"]
    seqs = [t["seq"] for t in z["timeline"]]
    assert seqs == sorted(seqs)
    assert [st.ledger.get(s)["type"] for s in seqs] == [events.SAFETY_REPORTED, events.SAFETY_ACKNOWLEDGED, events.SAFETY_RESOLVED]
    for t in (events.SAFETY_REPORTED, events.SAFETY_ACKNOWLEDGED, events.SAFETY_RESOLVED):
        rec = _receipts(st, "W003", t)
        assert len(rec) == 1 and rid in rec[0]["text_en"]
        assert rec[0]["text"] != rec[0]["text_en"]  # Sabita reads Odia
    assert st.ledger.verify()["ok"]
    assert client.post(f"/api/safety/reports/{rid}/resolve", json={"note": "again"}).status_code == 409


def test_ack_due_windows(st):
    s = safety.report("W001", "stop_work", "Press zone", ts="2026-10-27T10:00:00+05:30")
    h = safety.report("W001", "hazard", "Line 4", ts="2026-10-27T10:00:00+05:30")
    assert s["ack_due"] == "2026-10-27T10:15:00+05:30"
    assert h["ack_due"] == "2026-10-27T14:00:00+05:30"


def test_client_id_is_idempotent(st, client):
    body = {"kind": "hazard", "zone": "Line 4", "note": "Oil on floor", "client_id": "phone-123", "worker_id": "W001"}
    a = client.post("/api/safety/reports", json=body).json()
    n = st.ledger.count()
    b = client.post("/api/safety/reports", json=body).json()
    assert a["report_id"] == b["report_id"] and st.ledger.count() == n
    assert len(safety.list_reports("W001")) == 1


def test_overdue_when_ack_due_passed(st, monkeypatch):
    r = safety.report("W001", "stop_work", "Press zone", "Smoke", ts="2026-10-27T10:00:00+05:30")
    monkeypatch.setattr(reports_mod, "_now", lambda: "2026-10-27T10:10:00+05:30")
    assert safety.get_report(r["report_id"])["overdue"] is False
    monkeypatch.setattr(reports_mod, "_now", lambda: "2026-10-27T10:20:00+05:30")
    assert safety.get_report(r["report_id"])["overdue"] is True
    safety.acknowledge(r["report_id"])
    assert safety.get_report(r["report_id"])["overdue"] is False


def test_validation(client):
    assert client.post("/api/safety/reports", json={"kind": "fire", "zone": "X", "worker_id": "W001"}).status_code == 422
    assert client.post("/api/safety/reports", json={"kind": "hazard", "zone": "x" * 61, "worker_id": "W001"}).status_code == 422
    assert client.post("/api/safety/reports", json={"kind": "hazard", "zone": "X", "note": "n" * 301, "worker_id": "W001"}).status_code == 422
    assert client.post("/api/safety/reports/SAFE-9999/ack", json={}).status_code == 404


def _login(c, role, wid=None):
    tok = c.post("/api/auth/demo-login", json={"role": role, "worker_id": wid}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_worker_sees_only_own_and_ack_needs_supervisor_or_hr(auth_client):
    meena, ravi = _login(auth_client, "worker", "W001"), _login(auth_client, "worker", "W004")
    r = auth_client.post("/api/safety/reports", json={"kind": "hazard", "zone": "Line 4", "worker_id": "W004"}, headers=meena)
    assert r.status_code == 200 and r.json()["worker_id"] == "W001", "worker id comes from the token, not the body"
    rid = r.json()["report_id"]
    auth_client.post("/api/safety/reports", json={"kind": "hazard", "zone": "Cutting"}, headers=ravi)
    own = auth_client.get("/api/safety/reports?worker_id=W001", headers=meena)
    assert own.status_code == 200 and {x["worker_id"] for x in own.json()} == {"W001"}
    assert auth_client.get("/api/safety/reports?worker_id=W004", headers=meena).status_code == 403
    assert auth_client.get("/api/safety/reports", headers=meena).status_code == 403
    assert auth_client.post(f"/api/safety/reports/{rid}/ack", json={}, headers=meena).status_code == 403
    assert auth_client.post(f"/api/safety/reports/{rid}/ack", json={}, headers=_login(auth_client, "auditor")).status_code == 403
    sup = _login(auth_client, "supervisor")
    assert len(auth_client.get("/api/safety/reports", headers=sup).json()) == 2
    a = auth_client.post(f"/api/safety/reports/{rid}/ack", json={}, headers=sup)
    assert a.status_code == 200 and a.json()["acknowledged_by"] == "Murugan Pandi"
    z = auth_client.post(f"/api/safety/reports/{rid}/resolve", json={"note": "Fixed"}, headers=_login(auth_client, "hr"))
    assert z.status_code == 200 and z.json()["timeline"][-1]["by"] == "HR · H001"
    assert auth_client.post("/api/safety/reports", json={"kind": "hazard", "zone": "X"}, headers=sup).status_code == 403


def test_seed_has_one_acknowledged_past_hazard_and_nothing_open(st):
    from saakshi import seed
    seed.seed_all(st)
    rs = safety.list_reports("W001")
    assert len(rs) == 1 and rs[0]["status"] == "acknowledged" and rs[0]["kind"] == "hazard"
    assert rs[0]["received_at"] < "2026-10-27"
    assert not [r for r in safety.list_reports() if r["status"] == "received"]
