"""Local preview server (127.0.0.1 by default): MJPEG of the privatized, annotated frame, plus health.

    GET /stream.mjpg   multipart/x-mixed-replace MJPEG, ~15-25 fps, JPEG quality 75
    GET /frame.jpg     latest privatized frame
    GET /health        JSON status (backend, device, fps, counters)

Only `PrivateFrame`s can be published (`FrameBuffer.publish` refuses raw arrays), so the stream
cannot carry an un-blurred frame. Frames are encoded lazily, once per frame, only while watched.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .privacy import JPEG_QUALITY, PrivateFrame, encode_jpeg

BOUNDARY = "saakshiframe"
MAX_STREAM_FPS = 25.0


class FrameBuffer:
    """Latest-frame slot shared by the processing thread (writer) and HTTP clients (readers)."""

    def __init__(self, quality: int = JPEG_QUALITY) -> None:
        """Create an empty buffer."""
        self._cond = threading.Condition()
        self._frame: PrivateFrame | None = None
        self._seq = 0
        self._jpeg: tuple[int, bytes] | None = None
        self.quality = quality

    def publish(self, frame: PrivateFrame) -> int:
        """Store the newest frame; only PrivateFrame is accepted. Returns its sequence number."""
        if not isinstance(frame, PrivateFrame):
            raise TypeError("FrameBuffer only accepts privatized frames")
        with self._cond:
            self._frame = frame
            self._seq += 1
            self._cond.notify_all()
            return self._seq

    @property
    def seq(self) -> int:
        """Sequence number of the newest frame (0 before the first)."""
        return self._seq

    def latest(self) -> PrivateFrame | None:
        """The newest private frame, if any."""
        return self._frame

    def jpeg(self, after: int = -1, timeout: float = 1.0) -> tuple[int, bytes] | None:
        """Wait for a frame newer than `after`, return (seq, JPEG bytes), encoding at most once per frame."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._frame is not None and self._seq > after, timeout):
                return None
            if self._jpeg is not None and self._jpeg[0] == self._seq:
                return self._jpeg
            seq, frame = self._seq, self._frame
        assert frame is not None
        data = encode_jpeg(frame, self.quality)
        with self._cond:
            if self._jpeg is None or self._jpeg[0] < seq:
                self._jpeg = (seq, data)
        return seq, data


def make_handler(buf: FrameBuffer, health: Callable[[], dict[str, Any]], allow_origin: str,
                 stop: threading.Event, max_fps: float = MAX_STREAM_FPS) -> type[BaseHTTPRequestHandler]:
    """Build a request handler class bound to this buffer, health callback and CORS origin."""

    class Handler(BaseHTTPRequestHandler):
        """Serves /stream.mjpg, /frame.jpg, /health and a tiny viewer at /."""

        server_version = "SaakshiEdge/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            """Silence per-request logging (the stream would flood the console)."""

        def _common(self) -> None:
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
            self.send_header("X-Content-Type-Options", "nosniff")

        def _bytes(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self._common()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            """CORS pre-flight."""
            self.send_response(204)
            self._common()
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            """Route GET requests."""
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._bytes(200, "application/json", json.dumps(health()).encode())
            elif path == "/frame.jpg":
                got = buf.jpeg(after=-1, timeout=2.0)
                if got is None:
                    self._bytes(503, "application/json", b'{"detail":"no frame yet"}')
                else:
                    self._bytes(200, "image/jpeg", got[1])
            elif path == "/stream.mjpg":
                self._stream()
            elif path == "/":
                self._bytes(200, "text/html; charset=utf-8",
                            b"<!doctype html><title>Saakshi edge preview</title><body style='margin:0;background:#111'>"
                            b"<img src='/stream.mjpg' style='width:100%;height:auto' alt='privatized preview'></body>")
            else:
                self._bytes(404, "application/json", b'{"detail":"not found"}')

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self._common()
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            seq, min_gap, last = -1, 1.0 / max_fps, 0.0
            try:
                while not stop.is_set():
                    got = buf.jpeg(after=seq, timeout=1.0)
                    if got is None:
                        continue
                    seq, data = got
                    gap = time.monotonic() - last
                    if gap < min_gap:
                        time.sleep(min_gap - gap)
                    last = time.monotonic()
                    head = f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n\r\n".encode()
                    self.wfile.write(head + data + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

    return Handler


class PreviewServer:
    """Threaded stdlib HTTP server for the preview; `start()` runs it on a daemon thread."""

    def __init__(self, buf: FrameBuffer, health: Callable[[], dict[str, Any]], host: str = "127.0.0.1",
                 port: int = 8765, allow_origin: str = "http://127.0.0.1:8000") -> None:
        """Bind the server (port 0 picks a free port)."""
        self.stop_event = threading.Event()
        handler = make_handler(buf, health, allow_origin, self.stop_event)
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port."""
        return int(self.httpd.server_address[1])

    def start(self) -> None:
        """Serve forever on a daemon thread."""
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="preview-http", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop streams and the server."""
        self.stop_event.set()
        self.httpd.shutdown()
        self.httpd.server_close()
