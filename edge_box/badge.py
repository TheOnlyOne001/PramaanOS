"""Worker identity comes only from their rotating QR badge ("SKB1.…") shown to the camera.

The box decodes the QR every few frames and forwards the opaque string to Saakshi, which
checks its signature, rotation window and replay; the box never learns who is behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

BADGE_PREFIX = "SKB1."
DEDUP_S = 20.0


@dataclass(frozen=True, slots=True)
class BadgeHit:
    """A newly seen badge string and the QR's corner points (pixels) for the overlay."""

    text: str
    quad: tuple[tuple[float, float], ...]


@dataclass(slots=True)
class BadgeReader:
    """Decode QR badges every `every` frames; accept only SKB1. strings; de-duplicate each for `dedup_s`."""

    every: int = 3
    dedup_s: float = DEDUP_S
    prefix: str = BADGE_PREFIX
    last_quads: list[tuple[tuple[float, float], ...]] = field(default_factory=list)
    _seen: dict[str, float] = field(default_factory=dict)
    _det: cv2.QRCodeDetector = field(default_factory=cv2.QRCodeDetector)

    def _decode(self, frame: np.ndarray) -> list[tuple[str, tuple[tuple[float, float], ...]]]:
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found: list[tuple[str, tuple[tuple[float, float], ...]]] = []
        try:
            ok, texts, points, _ = self._det.detectAndDecodeMulti(gray)
            if ok and points is not None:
                found = [(str(t), tuple((float(p[0]), float(p[1])) for p in q)) for t, q in zip(texts, points, strict=False) if t]
        except cv2.error:
            found = []
        if not found:
            text, pts, _ = self._det.detectAndDecode(gray)
            if text and pts is not None:
                found = [(str(text), tuple((float(p[0]), float(p[1])) for p in np.reshape(pts, (-1, 2))))]
        return found

    def process(self, frame: np.ndarray, frame_idx: int, now: float) -> list[BadgeHit]:
        """Return badges not seen in the last `dedup_s` seconds (only on every `every`-th frame)."""
        if frame_idx % self.every:
            return []
        self._seen = {k: v for k, v in self._seen.items() if now - v < self.dedup_s}
        hits: list[BadgeHit] = []
        quads = []
        for text, quad in self._decode(frame):
            if not text.startswith(self.prefix) or len(text) > 2048:
                continue
            quads.append(quad)
            if text not in self._seen:
                self._seen[text] = now
                hits.append(BadgeHit(text, quad))
        self.last_quads = quads
        return hits
