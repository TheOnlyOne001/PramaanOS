"""The on-device HUD drawn over the *privatized* frame: zones, anonymous people, blurred faces, events.

Everything here draws on a `PrivateFrame` via `PrivateFrame.derive`, so the overlay can never see
or produce un-blurred pixels. Blending is done per region of interest to stay fast at 1280x720.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from .privacy import PrivateFrame
from .tracker import Track
from .zones import Zone

FONT = cv2.FONT_HERSHEY_SIMPLEX
AA = cv2.LINE_AA
AMBER = (0, 176, 255)
RED = (48, 48, 232)
GREEN = (96, 200, 64)
CYAN = (255, 208, 64)
WHITE = (245, 245, 245)
GREY = (170, 170, 170)
INK = (18, 18, 18)
TICKER_LINES = 3
FLASH_S = 1.5

Quad = tuple[tuple[float, float], ...]


@dataclass(slots=True)
class Scene:
    """What to draw on one frame."""

    camera: str = "cam-01"
    fps: float = 0.0
    backend_label: str = "HOG on CPU"
    faces_blurred_total: int = 0
    tracks: list[Track] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    occupancy: dict[str, int] = field(default_factory=dict)
    in_zone_ids: set[int] = field(default_factory=set)
    badge_quads: list[Quad] = field(default_factory=list)
    now: float = 0.0


def _blend_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int], alpha: float) -> None:
    """Alpha-blend a solid colour over img[y1:y2, x1:x2] in place."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    cv2.addWeighted(np.full_like(roi, color), alpha, roi, 1 - alpha, 0, dst=roi)


def _blend_poly(img: np.ndarray, pts: np.ndarray, color: tuple[int, int, int], alpha: float) -> None:
    """Alpha-blend a filled polygon over img, touching only its bounding box."""
    h, w = img.shape[:2]
    x, y, bw, bh = cv2.boundingRect(pts)
    x1, y1, x2, y2 = max(0, x), max(0, y), min(w, x + bw), min(h, y + bh)
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    layer = roi.copy()
    cv2.fillPoly(layer, [pts - np.array([x1, y1], np.int32)], color, AA)
    cv2.addWeighted(layer, alpha, roi, 1 - alpha, 0, dst=roi)


def _text(img: np.ndarray, s: str, org: tuple[int, int], scale: float, color: tuple[int, int, int], thick: int = 1) -> int:
    """Draw text with a soft dark shadow; return its width in pixels."""
    cv2.putText(img, s, (org[0] + 1, org[1] + 1), FONT, scale, INK, thick + 1, AA)
    cv2.putText(img, s, org, FONT, scale, color, thick, AA)
    return int(cv2.getTextSize(s, FONT, scale, thick)[0][0])


def _label(img: np.ndarray, s: str, x: int, y: int, scale: float, fg: tuple[int, int, int], bg: tuple[int, int, int]) -> None:
    """Draw a filled tag with text whose bottom-left is at (x, y)."""
    (tw, th), base = cv2.getTextSize(s, FONT, scale, 1)
    pad = max(2, int(4 * scale / 0.5))
    y = max(th + 2 * pad, y)
    cv2.rectangle(img, (x, y - th - 2 * pad), (x + tw + 2 * pad, y + base - pad), bg, -1)
    cv2.putText(img, s, (x + pad, y - pad), FONT, scale, fg, 1, AA)


def _brackets(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int], t: int) -> None:
    """Corner brackets around a box (reads as "tracked", lighter than a full rectangle)."""
    L = max(8, int(0.22 * min(x2 - x1, y2 - y1)))
    for cx, cy, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        cv2.line(img, (cx, cy), (cx + dx * L, cy), color, t, AA)
        cv2.line(img, (cx, cy), (cx, cy + dy * L), color, t, AA)


class Overlay:
    """Stateful HUD renderer: holds the recent-events ticker and the flash banner (thread-safe)."""

    def __init__(self, ticker_lines: int = TICKER_LINES, flash_s: float = FLASH_S) -> None:
        """Create an overlay with an empty ticker."""
        self._lock = threading.Lock()
        self.ticker: deque[tuple[str, tuple[int, int, int]]] = deque(maxlen=ticker_lines)
        self.flash_s = flash_s
        self._flash: tuple[str, tuple[int, int, int], float] | None = None

    def push(self, text: str, color: tuple[int, int, int] = WHITE) -> None:
        """Add a line to the bottom ticker (newest last)."""
        with self._lock:
            self.ticker.append((text, color))

    def flash(self, text: str, color: tuple[int, int, int], now: float | None = None) -> None:
        """Show a banner for `flash_s` seconds (badge punch accepted, zone entry fired)."""
        with self._lock:
            self._flash = (text, color, (time.monotonic() if now is None else now) + self.flash_s)

    def render(self, pf: PrivateFrame, scene: Scene) -> PrivateFrame:
        """Draw the HUD on a copy of the private frame; returns a new PrivateFrame of the same shape."""
        with self._lock:
            ticker = list(self.ticker)
            flash = self._flash
        return pf.derive(lambda img: self._draw(img, pf, scene, ticker, flash))

    def _draw(self, img: np.ndarray, pf: PrivateFrame, sc: Scene, ticker: list[tuple[str, tuple[int, int, int]]],
              flash: tuple[str, tuple[int, int, int], float] | None) -> None:
        h, w = img.shape[:2]
        s = max(0.35, w / 1280)  # UI scale
        fs = 0.5 * s
        t = max(1, round(2 * s))
        pulse = 0.5 + 0.5 * math.sin(sc.now * 2 * math.pi * 1.2)

        # zones: amber idle, pulsing red while occupied
        for z in sc.zones:
            if len(z.points) < 3:
                continue
            pts = np.array([[int(x * w), int(y * h)] for x, y in z.points], np.int32)
            occ = sc.occupancy.get(z.id, 0)
            color = RED if occ else AMBER
            _blend_poly(img, pts, color, 0.22 + 0.22 * pulse if occ else 0.16)
            cv2.polylines(img, [pts], True, color, t, AA)
            top = pts[np.argmin(pts[:, 1])]
            tag = f"{z.name} - restricted" + (f" - {occ} inside" if occ else "")
            _label(img, tag, int(top[0]), int(top[1]) - 4, fs, WHITE if occ else INK, color)

        # blurred faces: a thin outline and tag so viewers can see the privacy step happened
        for f in pf.faces:
            x1, y1, x2, y2 = f.int_coords()
            cv2.rectangle(img, (x1, y1), (x2, y2), GREEN, 1, AA)
            _label(img, "blurred on device", x1, y1 - 2, 0.38 * s, INK, GREEN)

        # anonymous people
        for tr in sc.tracks:
            b = tr.box
            x1, y1, x2, y2 = int(b.x1), int(b.y1), int(b.x2), int(b.y2)
            color = RED if tr.id in sc.in_zone_ids else CYAN
            _brackets(img, x1, y1, x2, y2, color, t)
            _label(img, f"{tr.label}  {b.score:.2f}", x1, y1 - 4, fs, INK, color)
            fx, fy = (x1 + x2) // 2, y2
            cv2.circle(img, (fx, fy), max(3, int(5 * s)), color, -1, AA)
            cv2.circle(img, (fx, fy), max(5, int(9 * s)), color, 1, AA)

        for q in sc.badge_quads:
            cv2.polylines(img, [np.array(q, np.int32).reshape(-1, 1, 2)], True, GREEN, t + 1, AA)

        # top HUD bar
        bar = int(34 * s)
        _blend_rect(img, 0, 0, w, bar, INK, 0.62)
        segs: list[tuple[str, tuple[int, int, int]]] = [
            ("SAAKSHI EDGE", AMBER), (sc.camera, WHITE), (f"{sc.fps:.0f} fps", WHITE), (sc.backend_label, WHITE),
            (f"faces blurred: {sc.faces_blurred_total:,}", GREEN), ("no video leaves this device", GREEN)]
        x, y = int(12 * s), int(bar * 0.68)
        for i, (txt, col) in enumerate(segs):
            if i:
                cv2.circle(img, (x + int(7 * s), y - int(5 * s)), max(1, int(2 * s)), GREY, -1, AA)
                x += int(16 * s)
            x += _text(img, txt, (x, y), fs, col, 2 if i == 0 else 1)
        rec = (w - int(16 * s), int(bar / 2))
        cv2.circle(img, rec, max(3, int(5 * s)), RED if pulse > 0.5 else (30, 30, 140), -1, AA)

        # bottom ticker of recent signed events
        if ticker:
            lh = int(24 * s)
            top = h - lh * len(ticker) - int(10 * s)
            _blend_rect(img, 0, top, w, h, INK, 0.55)
            for i, (txt, col) in enumerate(ticker):
                _text(img, txt, (int(12 * s), top + lh * (i + 1) - int(5 * s)), fs, col)

        # flash banner (fades out over FLASH_S)
        if flash is not None:
            text, col, until = flash
            left = until - sc.now
            if left > 0:
                a = min(1.0, left / self.flash_s) * 0.85
                bh = int(64 * s)
                by = int(h * 0.16)
                _blend_rect(img, 0, by, w, by + bh, col, a)
                big = 1.0 * s
                (tw, th), _ = cv2.getTextSize(text, FONT, big, 2)
                _text(img, text, ((w - tw) // 2, by + (bh + th) // 2), big, WHITE, 2)
