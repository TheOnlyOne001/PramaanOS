"""Lightweight IoU + centroid tracker: stable anonymous ids ("person 3") across frames, no identity.

Track ids are local counters that never leave the box (the server's privacy guard would refuse them).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import Box, iou


@dataclass(slots=True)
class Track:
    """One anonymous person track."""

    id: int
    box: Box
    hits: int = 1
    missed: int = 0

    @property
    def label(self) -> str:
        """Display label, e.g. "person 3"."""
        return f"person {self.id}"


class Tracker:
    """Greedy IoU matching with a centroid-distance fallback and EMA box smoothing."""

    def __init__(self, iou_min: float = 0.25, max_missed: int = 12, min_hits: int = 2, smooth: float = 0.6) -> None:
        """Create a tracker; tracks unseen for `max_missed` frames are dropped."""
        self.iou_min = iou_min
        self.max_missed = max_missed
        self.min_hits = min_hits
        self.smooth = smooth
        self.tracks: list[Track] = []
        self._next = 1

    def _blend(self, old: Box, new: Box) -> Box:
        a = self.smooth
        return Box(a * new.x1 + (1 - a) * old.x1, a * new.y1 + (1 - a) * old.y1,
                   a * new.x2 + (1 - a) * old.x2, a * new.y2 + (1 - a) * old.y2, new.score)

    def update(self, boxes: list[Box]) -> list[Track]:
        """Match detections to tracks; return confirmed tracks seen this frame."""
        pairs: list[tuple[float, int, int]] = []
        for ti, t in enumerate(self.tracks):
            tcx, tcy = t.box.center
            diag = math.hypot(t.box.w, t.box.h) or 1.0
            for di, d in enumerate(boxes):
                ov = iou(t.box, d)
                if ov >= self.iou_min:
                    pairs.append((ov + 1.0, ti, di))
                else:
                    dcx, dcy = d.center
                    dist = math.hypot(dcx - tcx, dcy - tcy) / diag
                    if dist < 0.5:
                        pairs.append((1.0 - dist, ti, di))
        pairs.sort(reverse=True)
        used_t: set[int] = set()
        used_d: set[int] = set()
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            t = self.tracks[ti]
            t.box = self._blend(t.box, boxes[di])
            t.hits += 1
            t.missed = 0
            used_t.add(ti)
            used_d.add(di)
        for ti, t in enumerate(self.tracks):
            if ti not in used_t:
                t.missed += 1
        for di, d in enumerate(boxes):
            if di not in used_d:
                self.tracks.append(Track(self._next, d))
                self._next += 1
        self.tracks = [t for t in self.tracks if t.missed <= self.max_missed]
        return self.visible()

    def visible(self) -> list[Track]:
        """Confirmed tracks matched in the latest frame."""
        return [t for t in self.tracks if t.missed == 0 and t.hits >= self.min_hits]
