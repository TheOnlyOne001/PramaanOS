"""Employer console: exceptions first, sorted by severity; SDG 8 scorecard; one failing source never blanks it."""
from __future__ import annotations

import pytest

from saakshi import console, seed, tamper

SEV = console.SEV_ORDER


@pytest.fixture
def seeded(st):
    seed.seed_all(st)
    return st


def _sorted_by_severity(exc):
    ranks = [SEV.get(e["severity"], 9) for e in exc]
    return ranks == sorted(ranks)


def test_overview_shape_and_sorting(seeded, client):
    r = client.get("/api/console/overview")
    assert r.status_code == 200
    body = r.json()
    assert {"site", "integrity", "exceptions", "counts"} <= set(body)
    exc = body["exceptions"]
    assert exc, "seeded week should raise at least one exception"
    assert _sorted_by_severity(exc)
    for e in exc:
        assert {"severity", "kind", "title", "detail", "people", "action", "link"} <= set(e)
        assert e["severity"] in SEV
    assert sum(body["counts"].values()) == len(exc)
    assert body["integrity"]["ok"] is True


def test_overview_includes_deposit_shortfall(seeded, client):
    exc = client.get("/api/console/overview").json()["exceptions"]
    hits = [e for e in exc if "deposit" in (e["title"] + " " + e["detail"]).lower()]
    assert hits, [e["title"] for e in exc]
    assert hits[0]["severity"] == "high"
    assert hits[0]["kind"] == "pay"


def test_tamper_puts_critical_integrity_first_naming_meena(seeded, client):
    res = tamper.tamper_punch_out(seeded.conn, "W001")
    assert res["ok"]
    body = client.get("/api/console/overview").json()
    first = body["exceptions"][0]
    assert first["severity"] == "critical"
    assert first["kind"] == "integrity"
    assert "Meena" in first["title"]
    assert "W001" in first["people"]
    assert body["integrity"]["ok"] is False
    assert _sorted_by_severity(body["exceptions"])


def test_sdg8_scorecard_has_six_targets_with_values(seeded, client):
    r = client.get("/api/sdg8/scorecard")
    assert r.status_code == 200
    targets = r.json()["targets"]
    assert [t["target"] for t in targets] == ["8.2", "8.3", "8.5", "8.6", "8.7", "8.8"]
    for t in targets:
        assert {"label", "indicator", "value", "unit", "status"} <= set(t)
        assert t["value"] is not None, f"target {t['target']} has no value"
        assert t["status"] in ("ok", "watch")


@pytest.mark.parametrize("module,fn", [("pay", "fairness"), ("pay", "cap_status"), ("voice", "themes"),
                                       ("edge", "recent"), ("passport", "expiring")])
def test_failing_source_does_not_blank_overview(seeded, client, monkeypatch, module, fn):
    import importlib
    mod = importlib.import_module(f"saakshi.{module}")

    def boom(*a, **k):
        raise RuntimeError("source down")
    monkeypatch.setattr(mod, fn, boom)
    tamper.tamper_punch_out(seeded.conn, "W001")
    r = client.get("/api/console/overview")
    assert r.status_code == 200
    exc = r.json()["exceptions"]
    assert exc and exc[0]["kind"] == "integrity", "integrity must still surface when another source fails"


def test_failing_source_does_not_blank_scorecard(seeded, client, monkeypatch):
    from saakshi import pay

    def boom(*a, **k):
        raise RuntimeError("pay down")
    monkeypatch.setattr(pay, "fairness", boom)
    monkeypatch.setattr(pay, "hours", boom)
    targets = client.get("/api/sdg8/scorecard").json()["targets"]
    assert len(targets) == 6
