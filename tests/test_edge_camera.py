"""Webcam edge box: rotating badges, camera punches, restricted zones, heartbeats/status and the preview CSP."""
import base64
import json
import time

import pytest

from saakshi import config, events

T0 = 1_793_076_000.0  # 2026-10-27T10:10:00+05:30


@pytest.fixture
def clock(monkeypatch):
    """A movable wall clock: clock.at(seconds after T0)."""
    class Clock:
        t = T0

        def at(self, dt):
            self.t = T0 + dt

    c = Clock()
    monkeypatch.setattr(time, "time", lambda: c.t)
    return c


@pytest.fixture
def box(st):
    from saakshi.edge import make_event

    def _sign(**fields):
        fields.setdefault("camera", "cam-01")
        return make_event(st.keys, **fields)
    return _sign


def badge_of(c, wid="W001", headers=None):
    r = c.get(f"/api/workers/{wid}/badge", headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def login(c, role, wid=None):
    r = c.post("/api/auth/demo-login", json={"role": role, "worker_id": wid})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --- badges and punches ------------------------------------------------------------------------

def test_badge_shape_and_signature(client, st, clock):
    b = badge_of(client)
    assert b["ttl"] == 30 and b["worker_id"] == "W001" and b["name"].startswith("Meena")
    prefix, body, sig = b["token"].split(".")
    assert prefix == "SKB1" and len(b["token"]) < 200  # short enough for a scannable QR
    claims = json.loads(_unb64(body))
    assert set(claims) == {"wid", "exp", "n"} and claims["wid"] == "W001" and claims["exp"] == int(T0) + 30
    assert len(claims["n"]) == 16
    assert st.keys.verify("site", _unb64(body), _unb64(sig).hex())
    assert b["expires_at"] == "2026-10-27T10:10:30+05:30"
    assert badge_of(client)["token"] != b["token"]  # a fresh nonce every time
    assert client.get("/api/workers/W999/badge").status_code == 404


def test_badge_round_trip_punch_in_then_out(client, st, clock, box):
    r = client.post("/api/edge/punch", json=box(badge=badge_of(client)["token"]))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["worker_id"] == "W001" and p["name"].startswith("Meena") and p["kind"] == "in"
    assert p["ts"] == "2026-10-27T10:10:00+05:30"
    assert p["receipt_text"].startswith("வருகை 10:10") and p["receipt_text_en"].startswith("In 10:10")
    ev = st.ledger.get(p["seq"])
    assert ev["type"] == events.PUNCH_IN and ev["worker_id"] == "W001"
    assert ev["payload"] == {"device": "cam-01", "via": "badge"}

    clock.at(61)
    r = client.post("/api/edge/punch", json=box(badge=badge_of(client)["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "out" and r.json()["receipt_text"].startswith("வெளியேற்றம்")
    assert st.ledger.get(r.json()["seq"])["type"] == events.PUNCH_OUT

    clock.at(200)  # out → in again
    assert client.post("/api/edge/punch", json=box(badge=badge_of(client)["token"])).json()["kind"] == "in"

    receipts = client.get("/api/workers/W001/receipts").json()
    assert [r["type"] for r in receipts[:3]] == [events.PUNCH_IN, events.PUNCH_OUT, events.PUNCH_IN]
    assert all(r["text"] != r["text_en"] for r in receipts[:3])  # Tamil for Meena, English alongside
    assert st.ledger.verify()["ok"]


def test_receipt_in_each_workers_language(client, clock, box):
    for wid, word in (("W003", "ପ୍ରବେଶ"), ("W004", "आगमन")):
        r = client.post("/api/edge/punch", json=box(badge=badge_of(client, wid)["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["receipt_text"].startswith(word)


def test_reused_badge_rejected(client, clock, box):
    tok = badge_of(client)["token"]
    assert client.post("/api/edge/punch", json=box(badge=tok)).status_code == 200
    clock.at(2)
    r = client.post("/api/edge/punch", json=box(badge=tok))
    assert r.status_code == 409 and r.json()["detail"] == "badge already used"


def test_expired_badge_rejected(client, clock, box):
    tok = badge_of(client)["token"]
    clock.at(36)  # 30 s TTL + 5 s skew has passed
    r = client.post("/api/edge/punch", json=box(badge=tok))
    assert r.status_code == 409 and r.json()["detail"] == "badge expired"


def test_badge_within_clock_skew_accepted(client, clock, box):
    tok = badge_of(client)["token"]
    clock.at(34)
    assert client.post("/api/edge/punch", json=box(badge=tok)).status_code == 200


def test_second_punch_within_60s_rejected(client, st, clock, box):
    assert client.post("/api/edge/punch", json=box(badge=badge_of(client)["token"])).status_code == 200
    clock.at(45)
    r = client.post("/api/edge/punch", json=box(badge=badge_of(client)["token"]))
    assert r.status_code == 409 and r.json()["detail"] == "just punched"
    assert len(st.ledger.events(worker_id="W001", type=events.PUNCH_IN)) == 1


def test_bad_box_signature_rejected(client, clock, box):
    body = box(badge=badge_of(client)["token"])
    body["camera"] = "cam-02"  # changed after the box signed
    assert client.post("/api/edge/punch", json=body).status_code == 401
    body = box(badge=badge_of(client)["token"])
    body["sig"] = "00" * 64
    assert client.post("/api/edge/punch", json=body).status_code == 401
    assert client.post("/api/edge/punch", json=box(box_id="rogue-box", badge=badge_of(client)["token"])).status_code == 401


def test_tampered_or_forged_badge_rejected(client, st, clock, box):
    prefix, body, sig = badge_of(client)["token"].split(".")
    claims = json.loads(_unb64(body))
    claims["wid"] = "W002"  # someone else's punch with Meena's signature
    forged = ".".join((prefix, _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()), sig))
    for bad in (forged, "SKB1.abc.def", "not-a-badge", "SKB2." + body + "." + sig, prefix + "." + body + "." + _b64(b"\0" * 64)):
        r = client.post("/api/edge/punch", json=box(badge=bad))
        assert 400 <= r.status_code < 500 and r.status_code != 401, (bad, r.text)
    # A badge signed by another key (the box's own) is not a site badge.
    raw = json.dumps({"exp": int(T0) + 30, "n": "00" * 8, "wid": "W001"}, separators=(",", ":"), sort_keys=True).encode()
    other = "SKB1." + _b64(raw) + "." + _b64(st.keys.get("edge-box-1").sign(raw).signature)
    assert client.post("/api/edge/punch", json=box(badge=other)).status_code == 422
    assert not st.ledger.events(type=events.PUNCH_IN)


def test_punch_refuses_extra_fields(client, clock, box):
    r = client.post("/api/edge/punch", json=box(badge=badge_of(client)["token"], face="base64..."))
    assert r.status_code == 422 and "unknown fields" in r.json()["detail"]


# --- zones -------------------------------------------------------------------------------------

def test_default_zone_for_cam_01(client):
    z = client.get("/api/edge/zones", params={"camera": "cam-01"}).json()
    assert z["camera"] == "cam-01"
    (press,) = z["zones"]
    assert press["name"] == "Press zone" and press["kind"] == "restricted"
    assert all(x >= 0.6 for x, _ in press["points"]) and 3 <= len(press["points"]) <= 20
    assert client.get("/api/edge/zones", params={"camera": "cam-99"}).json() == {"camera": "cam-99", "zones": []}


SQUARE = [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5], [0.1, 0.5]]


@pytest.mark.parametrize("zone", [
    {"name": "Out of range", "kind": "restricted", "points": [[0.1, 0.1], [1.2, 0.1], [0.5, 0.6]]},
    {"name": "Negative", "kind": "restricted", "points": [[-0.1, 0.1], [0.5, 0.1], [0.5, 0.6]]},
    {"name": "Too few", "kind": "restricted", "points": [[0.1, 0.1], [0.5, 0.5]]},
    {"name": "Too many", "kind": "restricted", "points": [[0.5, 0.5]] * 21},
    {"name": "Degenerate", "kind": "restricted", "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]]},
    {"name": "Sliver", "kind": "restricted", "points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.101]]},
    {"name": "Not a pair", "kind": "restricted", "points": [[0.1, 0.1, 0.1], [0.5, 0.1], [0.5, 0.6]]},
    {"name": "Wrong kind", "kind": "allowed", "points": SQUARE},
    {"name": "", "kind": "restricted", "points": SQUARE},
    {"name": "x" * 41, "kind": "restricted", "points": SQUARE},
    {"name": "W001", "kind": "restricted", "points": SQUARE},  # privacy guard: zone names never name a person
])
def test_zone_validation(client, st, zone):
    n = st.ledger.count()
    r = client.put("/api/edge/zones", json={"camera": "cam-01", "zones": [zone]})
    assert r.status_code == 422, r.text
    assert st.ledger.count() == n


def test_zones_put_stores_and_appends_signed_event(client, st, clock, box):
    zs = [{"name": "Loading bay", "kind": "restricted", "points": SQUARE},
          {"id": "press", "name": "Press zone", "kind": "restricted", "points": [[0.7, 0.1], [0.95, 0.1], [0.95, 0.9]]}]
    r = client.put("/api/edge/zones", json={"camera": "cam-01", "zones": zs})
    assert r.status_code == 200, r.text
    out = r.json()["zones"]
    assert [z["id"] for z in out] == ["zone-1", "press"]
    assert all(z["updated_at"] == "2026-10-27T10:10:00+05:30" for z in out)
    assert client.get("/api/edge/zones", params={"camera": "cam-01"}).json()["zones"] == out
    (ev,) = st.ledger.events(type=events.EDGE_ZONES_SET)
    assert ev["worker_id"] is None and ev["payload"] == {"camera": "cam-01", "zones": out}
    assert ev["type"] == "edge.zones_set" and events.EDGE_ZONES_SET in events.ALL
    # The box reports entries into a configured zone through the existing event route.
    e = client.post("/api/edge/events", json=box(zone="Loading bay", kind="restricted_zone_entry", count=1))
    assert e.status_code == 200, e.text
    assert st.ledger.verify()["ok"]


def test_zones_put_rejects_duplicates(client):
    zs = [{"id": "a", "name": "One", "points": SQUARE}, {"id": "a", "name": "Two", "points": SQUARE}]
    assert client.put("/api/edge/zones", json={"camera": "cam-01", "zones": zs}).status_code == 422


# --- heartbeat and status ----------------------------------------------------------------------

def beat(box, **kw):
    body = {"fps": 14.5, "device": "cpu", "backend": "yolov8n", "face_backend": "yunet", "faces_blurred_total": 12,
            "persons_now": 2, "in_zone_now": 1, "preview_url": "http://127.0.0.1:8765/stream.mjpg"}
    body.update(kw)
    return box(**body)


def test_heartbeat_then_status_online_then_offline(client, clock, box):
    assert client.get("/api/edge/status").json() == []
    r = client.post("/api/edge/heartbeat", json=beat(box))
    assert r.status_code == 200, r.text
    (s,) = client.get("/api/edge/status").json()
    assert s == {"camera": "cam-01", "box_id": "edge-box-1", "last_seen": "2026-10-27T10:10:00+05:30", "online": True,
                 "fps": 14.5, "device": "cpu", "backend": "yolov8n", "face_backend": "yunet", "faces_blurred_total": 12,
                 "persons_now": 2, "in_zone_now": 1, "preview_url": "http://127.0.0.1:8765/stream.mjpg"}
    clock.at(10)
    assert client.get("/api/edge/status").json()[0]["online"] is True
    clock.at(11)
    assert client.get("/api/edge/status").json()[0]["online"] is False
    n = len(client.get("/api/ledger/events").json())
    client.post("/api/edge/heartbeat", json=beat(box, persons_now=0))
    assert client.get("/api/edge/status").json()[0]["online"] is True
    assert len(client.get("/api/ledger/events").json()) == n  # heartbeats never reach the ledger


@pytest.mark.parametrize("url", ["http://evil.example:8765/x", "http://127.0.0.1.evil.example/", "javascript:alert(1)",
                                 "ftp://127.0.0.1/", "http://user@127.0.0.1/", "http://localhost/\"><script>",
                                 "http://192.168.1.5:8765/"])
def test_preview_url_must_be_local(client, box, url):
    r = client.post("/api/edge/heartbeat", json=beat(box, preview_url=url))
    assert r.status_code == 422, url
    assert client.get("/api/edge/status").json() == []


def test_preview_url_local_variants_accepted(client, box):
    for url in ("http://localhost:9000/", "https://127.0.0.1:8765/stream.mjpg", None):
        assert client.post("/api/edge/heartbeat", json=beat(box, preview_url=url)).status_code == 200, url


def test_heartbeat_validation_and_signature(client, box):
    assert client.post("/api/edge/heartbeat", json=beat(box, fps="fast")).status_code == 422
    assert client.post("/api/edge/heartbeat", json=beat(box, persons_now=-1)).status_code == 422
    assert client.post("/api/edge/heartbeat", json=beat(box, frame="x")).status_code == 422
    body = beat(box)
    body["persons_now"] = 9
    assert client.post("/api/edge/heartbeat", json=body).status_code == 401


# --- CSP ---------------------------------------------------------------------------------------

def test_csp_img_src_includes_preview_origin(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    img = next(d for d in csp.split("; ") if d.startswith("img-src "))
    assert img.split()[1:4] == ["'self'", "data:", "blob:"]
    for origin in config.EDGE_PREVIEW_ORIGINS:
        assert origin in img.split()
    assert "http://127.0.0.1:8765" in config.EDGE_PREVIEW_ORIGINS
    assert "frame-ancestors 'none'" in csp and "script-src 'self';" in csp


def test_preview_origins_parsing():
    assert config.preview_origins("http://127.0.0.1:9000, http://localhost:9000") == ("http://127.0.0.1:9000",
                                                                                       "http://localhost:9000")
    assert config.preview_origins("http://x;script-src * https://ok:1 'unsafe-inline' http://a/b") == ("https://ok:1",)


# --- access policy (auth on) -------------------------------------------------------------------

def test_policy(auth_client, clock, box):
    c = auth_client
    meena = login(c, "worker", "W001")
    assert c.get("/api/workers/W001/badge").status_code == 401
    assert c.get("/api/workers/W002/badge", headers=meena).status_code == 403
    tok = badge_of(c, "W001", meena)["token"]
    assert badge_of(c, "W002", login(c, "supervisor"))["worker_id"] == "W002"
    assert c.get("/api/workers/W001/badge", headers=login(c, "hr")).status_code == 403
    # The box needs no bearer token: its signature (and the worker's badge) authenticate the punch.
    assert c.post("/api/edge/punch", json=box(badge=tok)).status_code == 200
    assert c.post("/api/edge/heartbeat", json=beat(box)).status_code == 200
    assert c.get("/api/edge/zones").status_code == 200
    zs = {"camera": "cam-01", "zones": [{"name": "Bay", "points": SQUARE}]}
    assert c.put("/api/edge/zones", json=zs).status_code == 401
    assert c.put("/api/edge/zones", json=zs, headers=meena).status_code == 403
    assert c.put("/api/edge/zones", json=zs, headers=login(c, "auditor")).status_code == 403
    assert c.put("/api/edge/zones", json=zs, headers=login(c, "hr")).status_code == 200
    assert c.put("/api/edge/zones", json=zs, headers=login(c, "supervisor")).status_code == 200
    assert c.get("/api/edge/status").status_code == 401
    assert c.get("/api/edge/status", headers=meena).status_code == 403
    for role in ("supervisor", "hr", "auditor"):
        assert c.get("/api/edge/status", headers=login(c, role)).json()[0]["online"] is True
    assert c.get("/api/ledger/verify", headers=meena).json()["ok"]
