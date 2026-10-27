import pytest


@pytest.fixture
def make(st):
    from saakshi.edge import make_event

    def _make(**kw):
        base = dict(camera="cam-07", zone="Press zone", kind="restricted_zone_entry", count=1,
                    ts="2026-10-27T10:15:00+05:30")
        base.update(kw)
        return make_event(st.keys, **base)
    return _make


def test_signed_event_accepted(client, st, make):
    r = client.post("/api/edge/events", json=make())
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["type"] == "edge.event" and ev["worker_id"] is None and ev["signer"] == "site"
    assert ev["payload"]["box_id"] == "edge-box-1" and ev["payload"]["box_sig"]
    assert ev["receipt"] is None
    rows = client.get("/api/edge/events").json()
    assert rows[0]["kind"] == "restricted_zone_entry" and rows[0]["zone"] == "Press zone"
    assert st.ledger.verify()["ok"]


def test_bad_signature_rejected(client, make):
    body = make()
    body["count"] = 5  # changed after signing
    assert client.post("/api/edge/events", json=body).status_code == 401
    body = make()
    body["sig"] = "00" * 64
    assert client.post("/api/edge/events", json=body).status_code == 401
    body = make()
    body["box_id"] = "rogue-box"
    assert client.post("/api/edge/events", json=body).status_code == 401


@pytest.mark.parametrize("extra", [
    {"face": "base64..."},
    {"image": "x"},
    {"frame_jpeg": "abc"},
    {"meta": {"person_id": "p-17"}},
    {"track_id": 42},
    {"name": "Meena"},
    {"embedding": [0.1] * 128},
])
def test_privacy_guard_rejects_identity_and_imagery(client, make, extra):
    body = make(**extra)  # signed correctly: the guard must still refuse
    r = client.post("/api/edge/events", json=body)
    assert r.status_code == 422
    assert "privacy guard" in r.json()["detail"]


@pytest.mark.parametrize("field,value", [("camera", "snapshot_0012.jpg"), ("zone", "W001"),
                                         ("camera", "data:image/png;base64,iVBOR")])
def test_privacy_guard_checks_values(client, make, field, value):
    r = client.post("/api/edge/events", json=make(**{field: value}))
    assert r.status_code == 422


def test_unknown_kind_rejected(client, make):
    r = client.post("/api/edge/events", json=make(kind="face_match"))
    assert r.status_code == 422
    r = client.post("/api/edge/events", json=make(kind="loitering"))
    assert r.status_code == 422 and "unknown kind" in r.json()["detail"]


def test_summary_counts(client, make):
    for body in [make(), make(ts="2026-10-27T11:00:00+05:30"),
                 make(camera="cam-04", zone="Line 4", kind="ppe_compliance_rate", count=None, value=0.9,
                      ts="2026-10-27T09:00:00+05:30"),
                 make(camera="cam-04", zone="Line 4", kind="ppe_compliance_rate", count=None, value=0.8,
                      ts="2026-10-27T09:30:00+05:30"),
                 make(camera="cam-11", zone="Water point", kind="queue_length", count=11,
                      ts="2026-10-27T15:00:00+05:30"),
                 make(ts="2026-10-26T10:00:00+05:30")]:
        assert client.post("/api/edge/events", json=body).status_code == 200
    s = client.get("/api/edge/summary", params={"day": "2026-10-27"}).json()
    zones = {z["zone"]: z["events"] for z in s["zones"]}
    assert zones["Press zone"] == {"restricted_zone_entry": 2}
    assert zones["Line 4"] == {"ppe_compliance_rate": 2}
    assert zones["Water point"] == {"queue_length": 1}
    ppe = {p["zone"]: p for p in s["ppe_compliance_by_zone"]}
    assert ppe["Line 4"]["rate"] == pytest.approx(0.85)
    assert ppe["Line 4"]["by_hour"] == [{"hour": "09", "rate": 0.85, "n": 2}]
    assert s["last_event"]["kind"] == "queue_length"
    assert s["peak_queue"]["count"] == 11
    assert len(s["alerts"]) == 2
    assert client.get("/api/edge/events", params={"kind": "queue_length"}).json()[0]["count"] == 11


def test_cameras_register(client):
    cams = client.get("/api/edge/cameras").json()
    zones = {c["zone"] for c in cams}
    assert zones == {"Press zone", "Line 4", "Gate", "Canteen", "Water point", "Store"}
    assert all(c["retention_hours"] == 24 and c["owner"] and c["purpose"] and c["signage_languages"] for c in cams)


def test_seed_and_console_functions(st):
    from saakshi import edge
    edge.seed_demo(st)
    s = edge.summary()
    assert s["day"] == "2026-10-27"
    assert s["peak_queue"]["zone"] == "Water point" and s["peak_queue"]["ts"][11:13] == "15"
    assert len(edge.recent(5)) == 5
    assert st.ledger.verify()["ok"]


def test_sim_script_scenarios(st):
    import importlib.util
    from pathlib import Path
    from saakshi.edge import ingest
    p = Path(__file__).resolve().parent.parent / "scripts" / "edge_sim.py"
    spec = importlib.util.spec_from_file_location("edge_sim", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for f in mod.scenario_events("all"):
        ingest(mod.make_event(st.keys, **f))
    kinds = {e["kind"] for e in __import__("saakshi.edge", fromlist=["recent"]).recent(50)}
    assert {"restricted_zone_entry", "ppe_compliance_rate", "queue_length", "fire_smoke"} <= kinds
