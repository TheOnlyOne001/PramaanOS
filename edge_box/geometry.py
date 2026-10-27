"""Axis-aligned boxes and small geometry helpers shared by detectors, tracker, zones and overlay."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Box:
    """A detection box in pixel coordinates (x1, y1) top-left to (x2, y2) bottom-right, with a score."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float = 1.0

    @property
    def w(self) -> float:
        """Box width in pixels."""
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        """Box height in pixels."""
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        """Box area in square pixels."""
        return self.w * self.h

    @property
    def center(self) -> tuple[float, float]:
        """Centre point in pixels."""
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def padded(self, frac: float, width: int, height: int) -> Box:
        """Grow the box by `frac` of its size on every side, clipped to a width x height frame."""
        dx, dy = self.w * frac, self.h * frac
        return Box(max(0.0, self.x1 - dx), max(0.0, self.y1 - dy), min(float(width), self.x2 + dx),
                   min(float(height), self.y2 + dy), self.score)

    def int_coords(self) -> tuple[int, int, int, int]:
        """Integer pixel coordinates (x1, y1, x2, y2), rounded outwards."""
        return int(self.x1), int(self.y1), math.ceil(self.x2), math.ceil(self.y2)

    def scaled(self, s: float) -> Box:
        """Box with every coordinate multiplied by s (to map detections back from a resized frame)."""
        return Box(self.x1 * s, self.y1 * s, self.x2 * s, self.y2 * s, self.score)


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two boxes (0 when disjoint)."""
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def foot_point(box: Box, width: int, height: int) -> tuple[float, float]:
    """Bottom-centre of a person box, in normalised [0..1] frame coordinates."""
    return ((box.x1 + box.x2) / 2 / width, box.y2 / height)


def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (any consistent coordinate space, e.g. normalised)."""
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside
