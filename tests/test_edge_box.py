"""Edge camera box: privacy gate, zones, tracker, badges, signing, overlay, preview server, end to end."""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
qrcode = pytest.importorskip("qrcode")

from edge_box.badge import BadgeReader  # noqa: E402
from edge_box.client import ApiResult, BoxSigner  # noqa: E402
from edge_box.geometry import Box, foot_point, point_in_polygon  # noqa: E402
from edge_box.overlay import Overlay, Scene  # noqa: E402
from edge_box.pipeline import EdgePipeline, run_file  # noqa: E402
from edge_box.privacy import FACE_PAD, PrivateFrame, encode_jpeg, privatize  # noqa: E402
from edge_box.server import FrameBuffer, PreviewServer  # noqa: E402
from edge_box.tracker import Track, Tracker  # noqa: E402
from edge_box.zones import Zone, ZoneMonitor  # noqa: E402

RIGHT_HALF = Zone("z1", "Press zone", ((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)))


def qr_image(text: str, box: int = 6) -> Any:
    """A BGR numpy image of a QR code."""
    q = qrcode.QRCode(box_size=box, border=4)
    q.add_data(text)
    q.make(fit=True)
    img = np.array(q.make_image(fill_color="black", back_color="white").convert("RGB"), dtype=np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


class FakeClient:
    """Records every call the pipeline makes to the server."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def post_event(self, zone: str, count: int, kind: str = "restricted_zone_entry") -> ApiResult:
        self.calls.append(("event", {"zone": zone, "count": count, "kind": kind}))
        return ApiResult(200, {"seq": 312})

    def punch(self, badge: str) -> ApiResult:
        self.calls.append(("punch", badge))
        return ApiResult(200, {"worker_id": "W001", "name": "Meena Selvam", "kind": "in", "seq": 313, "receipt_text": "ok"})

    def heartbeat(self, stats: dict[str, Any]) -> ApiResult:
        self.calls.append(("heartbeat", stats))
        return ApiResult(200, {})

    def zones(self) -> list[Zone] | None:
        return None


class FixedFaces:
    backend = "haar"

    def __init__(self, boxes: list[Box]) -> None:
        self.boxes = boxes

    def detect(self, frame: Any) -> list[Box]:
        return list(self.boxes)


class RedPersons:
    """A 'person detector' that finds saturated red rectangles (stands in for YOLO on synthetic video)."""

    backend = "hog"
    device = "cpu"
    device_name = "CPU"

    def detect(self, frame: Any) -> list[Box]:
        b, g, r = frame[..., 0].astype(int), frame[..., 1].astype(int), frame[..., 2].astype(int)
        mask = ((r > 150) & (g < 90) & (b < 90)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        return [Box(float(x), float(y), float(x + w), float(y + h), 0.9)
                for x, y, w, h, area in stats[1:n] if area > 200]


# --- privacy gate -------------------------------------------------------------

def test_privatize_changes_every_pixel_in_padded_face_and_nothing_outside() -> None:
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    face = Box(100, 60, 160, 120)
    pf = privatize(frame, [face])
    out = pf.image
    pad = face.padded(FACE_PAD, 320, 240)
    assert (pad.x1, pad.y1, pad.x2, pad.y2) == (85, 45, 175, 135)
    x1, y1, x2, y2 = pad.int_coords()
    inside = np.zeros((240, 320), bool)
    inside[y1:y2, x1:x2] = True
    changed = np.any(out != frame, axis=-1)
    assert changed[inside].all(), "every pixel inside the padded face box must change"
    assert not changed[~inside].any(), "nothing outside the face boxes may change"
    # a uniform face region (where blur alone would change nothing) is still changed
    flat = np.full((100, 100, 3), 128, np.uint8)
    assert np.any(privatize(flat, [Box(20, 20, 60, 60)]).image[25:55, 25:55] != 128, axis=-1).all()
    assert not np.shares_memory(out, frame)


def test_encoder_and_buffer_refuse_unprivatized_frames() -> None:
    raw = np.zeros((90, 160, 3), np.uint8)
    with pytest.raises(TypeError):
        encode_jpeg(raw)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FrameBuffer().publish(raw)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PrivateFrame(raw, [])
    pf = privatize(raw, [])
    assert encode_jpeg(pf)[:2] == b"\xff\xd8"
    assert not pf.image.flags.writeable
    derived = pf.derive(lambda img: cv2.line(img, (0, 0), (50, 50), (255, 255, 255), 2))
    assert isinstance(derived, PrivateFrame) and derived.shape == pf.shape


# --- geometry, zones, tracker ---------------------------------------------------

def test_point_in_polygon_and_foot_point() -> None:
    sq = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    assert point_in_polygon(0.5, 0.5, sq)
    assert not point_in_polygon(0.9, 0.5, sq)
    assert not point_in_polygon(0.5, 0.1, sq)
    tri = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    assert point_in_polygon(0.2, 0.2, tri) and not point_in_polygon(0.8, 0.8, tri)
    assert foot_point(Box(100, 100, 300, 700), 1280, 720) == (200 / 1280, 700 / 720)


def test_zone_entry_fires_once_then_again_after_cooldown() -> None:
    zm = ZoneMonitor([RIGHT_HALF], cooldown_s=10)
    inside, outside = Box(900, 100, 1000, 600), Box(100, 100, 200, 600)
    t = Track(3, inside)
    first = zm.update([t], 1280, 720, now=0.0)
    assert len(first) == 1 and first[0].zone.name == "Press zone" and first[0].count == 1
    assert zm.update([t], 1280, 720, now=1.0) == []  # staying inside: no spam
    t.box = outside
    assert zm.update([t], 1280, 720, now=2.0) == [] and zm.occupancy["z1"] == 0
    t.box = inside
    assert zm.update([t], 1280, 720, now=5.0) == []  # re-entry inside the cooldown is suppressed
    t.box = outside
    zm.update([t], 1280, 720, now=6.0)
    t.box = inside
    again = zm.update([t], 1280, 720, now=11.0)  # re-entry after the cooldown fires again
    assert len(again) == 1 and zm.tracks_in_zones() == {3}


def test_tracker_keeps_ids_across_small_motion() -> None:
    tr = Tracker(min_hits=2)
    a, b = Box(100, 100, 200, 400), Box(600, 120, 700, 420)
    assert tr.update([a, b]) == []  # not confirmed yet
    ids = None
    for i in range(1, 15):
        tracks = tr.update([Box(a.x1 + 6 * i, a.y1 + 2 * i, a.x2 + 6 * i, a.y2 + 2 * i), Box(b.x1 - 5 * i, b.y1, b.x2 - 5 * i, b.y2)])
        now = sorted((round(t.box.x1), t.id) for t in tracks)
        if ids is None:
            ids = [i for _, i in now]
        assert [i for _, i in now] == ids
    assert ids == [1, 2] and tr.tracks[0].label == "person 1"


# --- badges, signing ------------------------------------------------------------

def test_badge_decoded_and_deduplicated() -> None:
    frame = np.full((720, 1280, 3), 255, np.uint8)
    q = qr_image("SKB1.test")
    frame[200:200 + q.shape[0], 400:400 + q.shape[1]] = q
    r = BadgeReader()
    hits = r.process(frame, frame_idx=0, now=0.0)
    assert [h.text for h in hits] == ["SKB1.test"] and len(hits[0].quad) == 4
    assert r.process(frame, frame_idx=1, now=0.1) == []  # only every 3rd frame
    assert r.process(frame, frame_idx=3, now=5.0) == []  # de-duplicated for 20 s
    assert [h.text for h in r.process(frame, frame_idx=6, now=21.0)] == ["SKB1.test"]
    other = np.full((720, 1280, 3), 255, np.uint8)
    q2 = qr_image("https://example.com/not-a-badge")
    other[100:100 + q2.shape[0], 100:100 + q2.shape[1]] = q2
    assert BadgeReader().process(other, 0, 0.0) == []


def test_signed_body_verifies_with_box_public_key(tmp_path: Path) -> None:
    from saakshi import db
    from saakshi.crypto import canonical, verify_sig

    conn = db.connect(str(tmp_path / "s.db"))
    db.init_schema(conn)
    signer = BoxSigner.from_db(str(tmp_path / "s.db"))
    body = signer.sign_body({"camera": "cam-01", "zone": "Press zone", "kind": "restricted_zone_entry", "count": 1})
    assert body["box_id"] == "edge-box-1" and body["ts"].endswith("+05:30")
    unsigned = {k: v for k, v in body.items() if k != "sig"}
    assert verify_sig(signer.public_hex(), canonical(unsigned), body["sig"])
    assert not verify_sig(signer.public_hex(), canonical({**unsigned, "count": 2}), body["sig"])
    try:
        from saakshi.edge import privacy_check
    except ImportError:
        return
    privacy_check(body)  # an edge event carries zone/kind/count/time only


# --- overlay, server -----------------------------------------------------------

def test_overlay_runs_on_blank_frame_and_keeps_shape() -> None:
    pf = privatize(np.zeros((720, 1280, 3), np.uint8), [Box(500, 100, 560, 170)])
    ov = Overlay()
    ov.push("19:42:05 Press zone - restricted entry - event signed #312")
    ov.push("08:02:11 Meena Selvam - IN - receipt sent")
    ov.flash("Meena Selvam - punched IN", (0, 200, 0), now=0.0)
    scene = Scene(fps=27, backend_label="YOLO11n on CUDA (GTX 1650)", faces_blurred_total=1204,
                  tracks=[Track(3, Box(800, 200, 950, 650, 0.91), hits=5)], zones=[RIGHT_HALF], occupancy={"z1": 1},
                  in_zone_ids={3}, badge_quads=[((10.0, 10.0), (60.0, 10.0), (60.0, 60.0), (10.0, 60.0))], now=0.5)
    out = ov.render(pf, scene)
    assert isinstance(out, PrivateFrame) and out.shape == (720, 1280, 3)
    assert out.image.any()
    small = ov.render(privatize(np.zeros((240, 320, 3), np.uint8), []), Scene())
    assert small.shape == (240, 320, 3)


def test_preview_server_serves_private_frames_with_cors() -> None:
    buf = FrameBuffer()
    buf.publish(privatize(np.zeros((120, 160, 3), np.uint8), []))
    srv = PreviewServer(buf, lambda: {"ok": True}, port=0, allow_origin="http://127.0.0.1:8000")
    srv.start()
    try:
        base = f"http://127.0.0.1:{srv.port}"
        with urllib.request.urlopen(base + "/health", timeout=5) as r:
            assert json.loads(r.read()) == {"ok": True}
            assert r.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8000"
            assert "no-store" in r.headers["Cache-Control"]
        with urllib.request.urlopen(base + "/frame.jpg", timeout=5) as r:
            assert r.headers["Content-Type"] == "image/jpeg" and r.read()[:2] == b"\xff\xd8"
        with urllib.request.urlopen(base + "/stream.mjpg", timeout=5) as r:
            assert r.headers["Content-Type"].startswith("multipart/x-mixed-replace")
            chunk = r.read(200)
            assert b"--saakshiframe" in chunk and b"image/jpeg" in chunk
    finally:
        srv.close()


# --- end to end ----------------------------------------------------------------

def write_video(path: Path, n: int = 36, w: int = 640, h: int = 360) -> None:
    """A red 'person' walks left→right into the right-half zone while a SKB1 badge QR is shown."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 15, (w, h))
    assert vw.isOpened()
    q = qr_image("SKB1.test", box=4)
    for i in range(n):
        f = np.full((h, w, 3), 235, np.uint8)
        x = 40 + i * 14
        cv2.rectangle(f, (x, 100), (x + 60, 300), (30, 30, 220), -1)
        f[20:20 + q.shape[0], 20:20 + q.shape[1]] = q
        vw.write(f)
    vw.release()


def test_end_to_end_dry_run_on_synthetic_video(tmp_path: Path) -> None:
    video = tmp_path / "walk.avi"
    write_video(video)
    client = FakeClient()
    pipe = EdgePipeline(FixedFaces([Box(300, 40, 340, 80)]), RedPersons(), client, zones=[RIGHT_HALF])
    buf = FrameBuffer()
    n = run_file(str(video), pipe, max_frames=30, buffer=buf)
    assert n == 30 and pipe.frames == 30
    events = [c for c in client.calls if c[0] == "event"]
    punches = [c for c in client.calls if c[0] == "punch"]
    assert events == [("event", {"zone": "Press zone", "count": 1, "kind": "restricted_zone_entry"})]
    assert punches == [("punch", "SKB1.test")]
    assert pipe.faces_blurred_total == 30
    assert any("event signed #312" in t for t, _ in pipe.overlay.ticker)
    assert any("Meena Selvam - IN - receipt sent" in t for t, _ in pipe.overlay.ticker)
    got = buf.jpeg(timeout=1)
    assert got is not None and got[1][:2] == b"\xff\xd8"
    hb = pipe.heartbeat_stats("http://127.0.0.1:8765/stream.mjpg")
    assert hb["backend"] == "hog" and hb["face_backend"] == "haar" and hb["faces_blurred_total"] == 30
    assert hb["persons_now"] == 1 and hb["in_zone_now"] == 1


def test_cli_dry_run_with_real_opencv_detectors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from edge_box.__main__ import main

    video = tmp_path / "walk.avi"
    write_video(video, n=12)
    done = threading.Event()

    def go() -> None:
        assert main(["run", "--source", str(video), "--dry-run", "--device", "cpu", "--preview-port", "0",
                     "--demo-zone", "--max-frames", "12"]) == 0
        done.set()

    t = threading.Thread(target=go)
    t.start()
    t.join(timeout=60)
    assert done.is_set()
    out = capsys.readouterr().out
    assert "faces are blurred on device" in out and "stopped after" in out
    assert "[dry-run] punch" in out
