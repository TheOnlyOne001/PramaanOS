"""Action queue: grouped detections, specific pay rows, integrity first after tamper, honest summaries, no blanking."""
from __future__ import annotations

import pytest

from saakshi import console, safety, seed, tamper

SEV = console.SEV_ORDER


@pytest.fixture
def seeded(st):
    seed.seed_all(st)
    return st


def _q(client):
    r = client.get("/api/console/queue")
    assert r.status_code == 200
    return r.json()


def _check_shape_and_summaries(body):
    items = body["items"]
    for i in items:
        assert {"id", "category", "summary_key", "severity", "issue", "impact", "owner", "deadline", "overdue",
                "next_action", "count", "window", "events", "people"} <= set(i)
        assert i["category"] in ("integrity", "safety", "pay", "approval", "skills", "voice")
        assert i["severity"] in SEV and i["summary_key"] in (None, "urgent_safety", "pay_discrepancies", "pending_approvals", "overdue")
        assert {"label", "kind", "target"} <= set(i["next_action"])
    ranks = [SEV[i["severity"]] for i in items]
    assert ranks == sorted(ranks)
    assert len({i["id"] for i in items}) == len(items)
    counts = {s["key"]: s["count"] for s in body["summaries"]}
    assert set(counts) == {"urgent_safety", "pay_discrepancies", "pending_approvals", "overdue"}
    for k in ("urgent_safety", "pay_discrepancies", "pending_approvals"):
        assert counts[k] == sum(1 for i in items if i["summary_key"] == k)
    assert counts["overdue"] == sum(1 for i in items if i["overdue"])


def test_water_point_detections_grouped(seeded, client):
    body = _q(client)
    _check_shape_and_summaries(body)
    water = [i for i in body["items"] if "Water point" in i["issue"]]
    assert len(water) == 1, [i["issue"] for i in body["items"]]
    w = water[0]
    assert w["count"] >= 2 and w["window"] and len(w["events"]) == w["count"]
    assert f"{w['count']} detections" in w["issue"] and w["window"] in w["issue"]


def test_pf_shortfall_names_contractor_and_amount(seeded, client):
    items = _q(client)["items"]
    pf = [i for i in items if i["issue"].startswith("PF deposit shortfall")]
    assert len(pf) == 1
    assert "Sri Balaji Manpower" in pf[0]["issue"]
    assert "₹1,064" in pf[0]["impact"] and "3 contract workers" in pf[0]["impact"]
    assert pf[0]["summary_key"] == "pay_discrepancies" and pf[0]["deadline"]
    assert set(pf[0]["people"]) == {"W003", "W004", "W006"}


def test_tamper_puts_critical_integrity_first_naming_meena(seeded, client):
    assert tamper.tamper_punch_out(seeded.conn, "W001")["ok"]
    body = _q(client)
    _check_shape_and_summaries(body)
    first = body["items"][0]
    assert first["severity"] == "critical" and first["category"] == "integrity"
    assert "Meena" in first["issue"] and "W001" in first["people"]
    assert first["next_action"]["kind"] in ("open_evidence", "open_roots")
    assert first["next_action"]["target"] == str(first["events"][0])


def test_overdue_stop_work_counts_in_urgent_and_overdue(seeded, client, monkeypatch):
    from saakshi.safety import reports as reports_mod
    r = safety.report("W002", "stop_work", "Press zone", "Smoke near press", ts="2026-10-27T09:00:00+05:30")
    monkeypatch.setattr(reports_mod, "_now", lambda: "2026-10-27T09:30:00+05:30")
    monkeypatch.setattr(console, "_now", lambda: "2026-10-27T09:30:00+05:30")
    body = _q(client)
    _check_shape_and_summaries(body)
    it = next(i for i in body["items"] if i["id"] == f"safety:{r['report_id']}")
    assert it["issue"] == "Stop-work call — Press zone" and it["severity"] == "critical" and it["overdue"]
    assert it["next_action"] == {"label": "Acknowledge report", "kind": "ack_safety", "target": r["report_id"]}
    counts = {s["key"]: s["count"] for s in body["summaries"]}
    assert counts["overdue"] >= 1 and counts["urgent_safety"] >= 1
    safety.acknowledge(r["report_id"])
    assert all(i["id"] != f"safety:{r['report_id']}" or i["severity"] == "medium" for i in _q(client)["items"])


@pytest.mark.parametrize("module,fn", [("pay", "fairness"), ("pay", "cap_status"), ("voice", "themes"),
                                       ("edge", "recent"), ("passport", "expiring"), ("safety", "list_reports")])
def test_failing_source_does_not_blank_queue(seeded, client, monkeypatch, module, fn):
    import importlib
    mod = importlib.import_module(f"saakshi.{module}")

    def boom(*a, **k):
        raise RuntimeError("source down")
    monkeypatch.setattr(mod, fn, boom)
    tamper.tamper_punch_out(seeded.conn, "W001")
    body = _q(client)
    assert body["items"] and body["items"][0]["category"] == "integrity"
    assert len(body["items"]) > 1, "other sources still contribute rows"


def test_plain_function_matches_route(seeded, client):
    assert console.queue()["summaries"] == _q(client)["summaries"]
