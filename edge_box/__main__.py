"""Command line: `python -m edge_box run ...` and `python -m edge_box download-models`."""
from __future__ import annotations

import argparse
import sys
import threading
from typing import Any

from . import BOX_ID, CAMERA_ID
from .client import ApiResult, BoxSigner, HttpSaakshiClient
from .zones import Zone

DEMO_ZONE = Zone("demo", "Press zone", ((0.55, 0.35), (0.97, 0.35), (0.97, 0.97), (0.55, 0.97)))


class DryRunClient:
    """Offline client for --dry-run: prints what would be sent, never touches the network."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._seq = 0

    def _ok(self, name: str, body: dict[str, Any]) -> ApiResult:
        self.calls.append((name, body))
        self._seq += 1
        print(f"[dry-run] {name}: {body}")
        return ApiResult(200, {"seq": self._seq, "name": "Badge holder", "kind": "in"})

    def post_event(self, zone: str, count: int, kind: str = "restricted_zone_entry") -> ApiResult:
        """Record an edge event."""
        return self._ok("event", {"zone": zone, "count": count, "kind": kind})

    def punch(self, badge: str) -> ApiResult:
        """Record a punch."""
        return self._ok("punch", {"badge": badge[:16] + "..."})

    def heartbeat(self, stats: dict[str, Any]) -> ApiResult:
        """Record a heartbeat (not printed)."""
        self.calls.append(("heartbeat", stats))
        return ApiResult(200, {})

    def zones(self) -> list[Zone] | None:
        """No server: keep the current zones."""
        return None


def build_parser() -> argparse.ArgumentParser:
    """CLI definition."""
    ap = argparse.ArgumentParser(prog="python -m edge_box", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the edge box")
    r.add_argument("--saakshi", default="http://127.0.0.1:8000", help="Saakshi server base URL (also the CORS origin)")
    r.add_argument("--db", default=None, help="Saakshi SQLite DB holding the demo box key (default: saakshi.config.DB_PATH)")
    r.add_argument("--camera", type=int, default=0, help="webcam index (try 1 or 2 if 0 is the wrong camera)")
    r.add_argument("--source", default=None, help="video file instead of a webcam (testing)")
    r.add_argument("--loop", action="store_true", help="loop the --source file")
    r.add_argument("--width", type=int, default=1280)
    r.add_argument("--height", type=int, default=720)
    r.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    r.add_argument("--imgsz", type=int, default=640, help="YOLO input size (smaller = faster, e.g. 480)")
    r.add_argument("--no-half", action="store_true", help="disable FP16 on CUDA")
    r.add_argument("--window", action="store_true", help="also show the privatized overlay in a window (q quits)")
    r.add_argument("--preview-host", default="127.0.0.1")
    r.add_argument("--preview-port", type=int, default=8765)
    r.add_argument("--camera-id", default=CAMERA_ID)
    r.add_argument("--box-id", default=BOX_ID)
    r.add_argument("--demo-zone", action="store_true", help="start with a demo 'Press zone' until the server sends zones")
    r.add_argument("--dry-run", action="store_true", help="no server: print events instead of sending them")
    r.add_argument("--max-frames", type=int, default=None)
    d = sub.add_parser("download-models", help="fetch the YuNet face model into edge_box/models/")
    d.add_argument("--dir", default=None)
    return ap


def _run(a: argparse.Namespace) -> int:
    from .capture import CaptureThread, open_capture
    from .faces import make_face_detector
    from .persons import make_person_detector
    from .pipeline import Dispatcher, EdgeBox, EdgePipeline
    from .server import FrameBuffer, PreviewServer

    client: Any
    if a.dry_run:
        client = DryRunClient()
    else:
        db_path = a.db
        if db_path is None:
            from saakshi import config

            db_path = config.DB_PATH
        client = HttpSaakshiClient(a.saakshi, BoxSigner.from_db(db_path, a.box_id), camera=a.camera_id)
    faces = make_face_detector()
    persons = make_person_detector(a.device, imgsz=a.imgsz, half=not a.no_half)
    pipe = EdgePipeline(faces, persons, client, camera=a.camera_id, zones=[DEMO_ZONE] if a.demo_zone else None,
                        dispatcher=Dispatcher())
    buf = FrameBuffer()
    server = PreviewServer(buf, pipe.health, a.preview_host, a.preview_port, allow_origin=a.saakshi.rstrip("/"))
    server.start()
    preview_url = f"http://{a.preview_host}:{server.port}/stream.mjpg"
    print(f"[edge_box] faces: {faces.backend} | persons: {pipe.backend_label} | preview: {preview_url}")
    print("[edge_box] faces are blurred on device before anything is drawn or streamed; no video leaves this machine")
    stop = threading.Event()
    cap = CaptureThread(open_capture(a.camera, a.source, a.width, a.height), stop, loop=a.loop)
    try:
        EdgeBox(pipe, cap, buf, preview_url).run(window=a.window, max_frames=a.max_frames)
    finally:
        server.close()
    print(f"[edge_box] stopped after {pipe.frames} frames; faces blurred: {pipe.faces_blurred_total}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    a = build_parser().parse_args(argv)
    if a.cmd == "download-models":
        from pathlib import Path

        from .faces import MODELS_DIR, download_models

        path = download_models(Path(a.dir) if a.dir else MODELS_DIR)
        print(f"YuNet face model ready: {path}")
        return 0
    return _run(a)


if __name__ == "__main__":
    sys.exit(main())
