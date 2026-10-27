"""Camera / video capture: OpenCV VideoCapture (DirectShow on Windows) into a 1-slot latest-frame buffer.

Frames live only in memory and are replaced as soon as a newer one arrives: nothing is recorded.
"""
from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np


def open_capture(camera: int = 0, source: str | None = None, width: int = 1280, height: int = 720) -> cv2.VideoCapture:
    """Open a webcam (CAP_DSHOW on Windows for fast start-up and exact resolution) or a video file."""
    if source:
        cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if sys.platform == "win32":
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # most USB webcams: 30 fps at 720p only in MJPG
    if not cap.isOpened():
        what = source or f"camera index {camera}"
        raise RuntimeError(f"could not open {what}; try another --camera index or close apps using the webcam")
    return cap


class CaptureThread(threading.Thread):
    """Reads frames continuously; `latest()` hands the processing thread only the newest one."""

    def __init__(self, cap: cv2.VideoCapture, stop: threading.Event, loop: bool = False, pace: bool = True) -> None:
        """Wrap an opened capture. For files, `pace` plays at file fps and `loop` restarts at the end."""
        super().__init__(name="capture", daemon=True)
        self.cap = cap
        self.stop = stop
        self.loop = loop
        self.pace = pace
        self.ended = threading.Event()
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._seq = 0
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        self._is_file = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) > 0
        self._gap = 1.0 / fps if self._is_file and fps > 0 else 0.0

    def run(self) -> None:
        """Capture loop."""
        fails = 0
        while not self.stop.is_set():
            t0 = time.monotonic()
            ok, frame = self.cap.read()
            if not ok or frame is None:
                if self._is_file and self.loop:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                fails += 1
                if self._is_file or fails > 50:
                    break
                time.sleep(0.02)
                continue
            fails = 0
            with self._cond:
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()
            if self.pace and self._gap:
                time.sleep(max(0.0, self._gap - (time.monotonic() - t0)))
        self.ended.set()
        with self._cond:
            self._cond.notify_all()
        self.cap.release()

    def latest(self, after: int, timeout: float = 1.0) -> tuple[int, np.ndarray] | None:
        """Wait for a frame newer than `after`; return (seq, frame) or None on timeout/end."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after or self.ended.is_set(), timeout)
            if self._frame is None or self._seq <= after:
                return None
            return self._seq, self._frame
