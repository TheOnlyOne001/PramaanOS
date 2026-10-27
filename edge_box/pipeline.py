"""The per-frame pipeline and the threaded runner (capture → processing → preview buffer).

`EdgePipeline.process(frame)` is one frame end to end and is what the tests drive with
injected frames, detectors and a fake client. `EdgeBox` wires it to threads for the real box.
"""
from __future__ import annotations

import contextlib
import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import cv2
import numpy as np

from . import CAMERA_ID
from .badge import BadgeReader
from .capture import CaptureThread, open_capture
from .client import IST, ApiResult, SaakshiClient
from .faces import FaceDetector
from .overlay import AMBER, GREEN, RED, Overlay, Scene
from .persons import PersonDetector
from .privacy import PrivateFrame, privatize
from .server import FrameBuffer
from .tracker import Tracker
from .zones import Zone, ZoneEntry, ZoneMonitor


def clock() -> str:
    """Local wall-clock time HH:MM:SS (IST) for the ticker."""
    return datetime.now(IST).strftime("%H:%M:%S")


class Dispatcher:
    """Runs server calls off the frame loop on one worker thread (or inline when `sync`)."""

    def __init__(self, sync: bool = False) -> None:
        """Create a dispatcher; call `start()` unless sync."""
        self.sync = sync
        self._q: queue.Queue[Callable[[], None] | None] = queue.Queue(maxsize=256)
        self._t = threading.Thread(target=self._run, name="dispatch", daemon=True)

    def start(self) -> None:
        """Start the worker thread (no-op when sync)."""
        if not self.sync:
            self._t.start()

    def submit(self, job: Callable[[], None]) -> None:
        """Run `job` now (sync) or queue it (dropping it if the queue is full)."""
        if self.sync:
            job()
            return
        with contextlib.suppress(queue.Full):  # drop rather than stall the frame loop
            self._q.put_nowait(job)

    def _run(self) -> None:
        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                job()
            except Exception as e:  # a failing call must never kill the box
                print(f"[edge_box] dispatch error: {type(e).__name__}: {e}")

    def stop(self) -> None:
        """Ask the worker to exit after queued jobs."""
        if not self.sync:
            self._q.put(None)


class EdgePipeline:
    """Face blur → people → tracks → zones → badges → overlay, for one frame at a time."""

    def __init__(self, faces: FaceDetector, persons: PersonDetector, client: SaakshiClient, camera: str = CAMERA_ID,
                 zones: list[Zone] | None = None, dispatcher: Dispatcher | None = None,
                 clock_fn: Callable[[], float] = time.monotonic) -> None:
        """Wire detectors and client; `clock_fn` is injectable so tests control cooldowns."""
        self.faces = faces
        self.persons = persons
        self.client = client
        self.camera = camera
        self.tracker = Tracker()
        self.zones = ZoneMonitor(list(zones or []))
        self.badges = BadgeReader()
        self.overlay = Overlay()
        self.dispatcher = dispatcher or Dispatcher(sync=True)
        self.clock = clock_fn
        self.frames = 0
        self.faces_blurred_total = 0
        self.persons_now = 0
        self.in_zone_now = 0
        self.fps = 0.0
        self._last_t: float | None = None
        self._pending_zones: list[Zone] | None = None

    @property
    def backend_label(self) -> str:
        """HUD text such as "YOLO11n on CUDA (GTX 1650)" or "HOG on CPU"."""
        name = {"yolo11n": "YOLO11n", "hog": "HOG"}.get(self.persons.backend, self.persons.backend)
        if self.persons.device == "cuda":
            return f"{name} on CUDA ({self.persons.device_name})"
        return f"{name} on CPU"

    def set_zones(self, zones: list[Zone]) -> None:
        """Replace zones (thread-safe: applied at the start of the next frame)."""
        self._pending_zones = list(zones)

    def process(self, frame: np.ndarray) -> PrivateFrame:
        """Run one frame; returns the privatized + annotated frame (the only thing that may be shown)."""
        now = self.clock()
        if self._pending_zones is not None:
            self.zones.set_zones(self._pending_zones)
            self._pending_zones = None
        # 1. privacy first: find faces only to blur them, then never touch the raw frame again
        pf = privatize(frame, self.faces.detect(frame))
        del frame
        self.faces_blurred_total += len(pf.faces)
        img = pf.image
        h, w = img.shape[:2]
        # 2. anonymous people and zones
        tracks = self.tracker.update(self.persons.detect(img))
        entries = self.zones.update(tracks, w, h, now)
        in_zone = self.zones.tracks_in_zones()
        self.persons_now, self.in_zone_now = len(tracks), len(in_zone)
        for e in entries:
            self._on_entry(e, now)
        # 3. identity only from a QR badge
        for hit in self.badges.process(img, self.frames, now):
            self.dispatcher.submit(self._punch_job(hit.text))
        # 4. stats + overlay
        if self._last_t is not None:
            dt = max(1e-6, now - self._last_t)
            self.fps = 1 / dt if self.fps == 0 else 0.9 * self.fps + 0.1 / dt
        self._last_t = now
        self.frames += 1
        scene = Scene(camera=self.camera, fps=self.fps, backend_label=self.backend_label,
                      faces_blurred_total=self.faces_blurred_total, tracks=tracks, zones=self.zones.zones,
                      occupancy=self.zones.occupancy, in_zone_ids=in_zone, badge_quads=self.badges.last_quads, now=now)
        return self.overlay.render(pf, scene)

    def _on_entry(self, e: ZoneEntry, now: float) -> None:
        self.overlay.flash(f"RESTRICTED ZONE ENTRY - {e.zone.name}", RED, now)
        stamp = clock()

        def send() -> None:
            r = self.client.post_event(e.zone.name, e.count)
            if r.ok:
                self.overlay.push(f"{stamp} {e.zone.name} - restricted entry - event signed #{r.body.get('seq', '?')}", AMBER)
            else:
                self.overlay.push(f"{stamp} {e.zone.name} - restricted entry - not recorded ({r.detail})", RED)

        self.dispatcher.submit(send)

    def _punch_job(self, badge: str) -> Callable[[], None]:
        return lambda: self._punch(badge)

    def _punch(self, badge: str) -> None:
        stamp = clock()
        r: ApiResult = self.client.punch(badge)
        if r.ok:
            name = str(r.body.get("name", "worker"))
            kind = str(r.body.get("kind", "in")).upper()
            self.overlay.push(f"{stamp} {name} - {kind} - receipt sent", GREEN)
            self.overlay.flash(f"{name} - punched {kind}", GREEN, self.clock())
        elif r.status == 409:
            self.overlay.push(f"{stamp} badge refused - {r.detail}", AMBER)
        else:
            self.overlay.push(f"{stamp} badge not accepted - {r.detail}", RED)

    def heartbeat_stats(self, preview_url: str) -> dict[str, Any]:
        """Heartbeat fields per the contract (counts and backend names only)."""
        return {"fps": round(self.fps, 1), "device": self.persons.device, "backend": self.persons.backend,
                "face_backend": self.faces.backend, "faces_blurred_total": self.faces_blurred_total,
                "persons_now": self.persons_now, "in_zone_now": self.in_zone_now, "preview_url": preview_url}

    def health(self) -> dict[str, Any]:
        """Local /health JSON."""
        return {"ok": True, "camera": self.camera, "frames": self.frames, "backend_label": self.backend_label,
                "zones": [z.name for z in self.zones.zones], **self.heartbeat_stats("")}


def run_file(source: str, pipeline: EdgePipeline, max_frames: int | None = None,
             buffer: FrameBuffer | None = None) -> int:
    """Process a video file frame by frame, as fast as possible (tests / dry runs). Returns frames processed."""
    cap = open_capture(source=source)
    n = 0
    try:
        while max_frames is None or n < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            out = pipeline.process(frame)
            if buffer is not None:
                buffer.publish(out)
            n += 1
    finally:
        cap.release()
    return n


class EdgeBox:
    """Threads: capture → processing → FrameBuffer (→ MJPEG server), heartbeat every 2 s, zone poll every 2 s."""

    def __init__(self, pipeline: EdgePipeline, capture: CaptureThread, buffer: FrameBuffer, preview_url: str,
                 heartbeat_s: float = 2.0, zone_poll_s: float = 2.0) -> None:
        """Wire the pipeline to a started-later capture thread and a frame buffer."""
        self.pipeline = pipeline
        self.capture = capture
        self.buffer = buffer
        self.preview_url = preview_url
        self.heartbeat_s = heartbeat_s
        self.zone_poll_s = zone_poll_s
        self.stop = capture.stop

    def _processing(self, max_frames: int | None) -> None:
        seq = 0
        while not self.stop.is_set():
            got = self.capture.latest(seq, timeout=0.5)
            if got is None:
                if self.capture.ended.is_set():
                    break
                continue
            seq, frame = got
            self.buffer.publish(self.pipeline.process(frame))
            if max_frames is not None and self.pipeline.frames >= max_frames:
                break
        self.stop.set()

    def _every(self, period: float, fn: Callable[[], None]) -> None:
        while not self.stop.wait(period):
            try:
                fn()
            except Exception as e:  # keep the box alive if the server is down or restarting
                print(f"[edge_box] background error: {type(e).__name__}: {e}")

    def _heartbeat(self) -> None:
        self.pipeline.client.heartbeat(self.pipeline.heartbeat_stats(self.preview_url))

    def _poll_zones(self) -> None:
        zones = self.pipeline.client.zones()
        if zones is not None:
            self.pipeline.set_zones(zones)

    def run(self, window: bool = False, max_frames: int | None = None) -> None:
        """Run until Ctrl+C, 'q' in the window, end of file, or max_frames."""
        self._poll_zones()
        self.pipeline.dispatcher.start()
        self.capture.start()
        threads = [threading.Thread(target=self._processing, args=(max_frames,), name="process", daemon=True),
                   threading.Thread(target=self._every, args=(self.heartbeat_s, self._heartbeat), name="heartbeat", daemon=True),
                   threading.Thread(target=self._every, args=(self.zone_poll_s, self._poll_zones), name="zones", daemon=True)]
        for t in threads:
            t.start()
        try:
            shown = 0
            while not self.stop.is_set():
                if not window:
                    self.stop.wait(0.5)
                    continue
                pf = self.buffer.latest()  # the window, like the stream, only ever shows private frames
                if pf is not None and self.buffer.seq != shown:
                    shown = self.buffer.seq
                    cv2.imshow("Saakshi edge (faces blurred on device) - q to quit", pf.image)
                if (cv2.waitKey(15) & 0xFF) in (ord("q"), 27):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            self.pipeline.dispatcher.stop()
            threads[0].join(timeout=3)
            if window:
                cv2.destroyAllWindows()
