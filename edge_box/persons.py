"""Person detection: Ultralytics YOLO11n (CUDA, half precision) if installed, else OpenCV HOG on CPU.

Only the `person` class is detected. Boxes are anonymous; identity comes only from QR badges.
"""
from __future__ import annotations

from typing import Any, Protocol

import cv2
import numpy as np

from .geometry import Box, iou

PERSON_CONF = 0.4


class PersonDetector(Protocol):
    """Anything that returns person boxes and names its backend and device."""

    backend: str
    device: str
    device_name: str

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Return person boxes in the frame."""
        ...


def _nms(boxes: list[Box], thresh: float = 0.45) -> list[Box]:
    """Greedy non-maximum suppression by score."""
    keep: list[Box] = []
    for b in sorted(boxes, key=lambda b: -b.score):
        if all(iou(b, k) < thresh for k in keep):
            keep.append(b)
    return keep


def resolve_device(pref: str = "auto") -> tuple[str, str]:
    """Return (device, human name): "cuda" if requested/auto and torch sees a GPU, else "cpu"."""
    if pref == "cpu":
        return "cpu", "CPU"
    try:
        import torch
    except ImportError:
        return "cpu", "CPU"
    if torch.cuda.is_available():
        name = str(torch.cuda.get_device_name(0)).replace("NVIDIA ", "").replace("GeForce ", "")
        return "cuda", name
    return "cpu", "CPU"


class YoloPersons:
    """Ultralytics YOLO11n, person class only, imgsz 640, FP16 on CUDA."""

    backend = "yolo11n"

    def __init__(self, device: str = "auto", weights: str = "yolo11n.pt", imgsz: int = 640, half: bool = True) -> None:
        """Load YOLO weights (auto-downloaded by ultralytics on first use) onto the chosen device."""
        from ultralytics import YOLO

        self.device, self.device_name = resolve_device(device)
        self.imgsz = imgsz
        self.half = half and self.device == "cuda"
        self._model: Any = YOLO(weights)
        self._model.predict(np.zeros((imgsz, imgsz, 3), np.uint8), imgsz=imgsz, classes=[0], device=self.device,
                            half=self.half, verbose=False)  # warm-up so the first real frame is not slow

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Return person boxes found by YOLO."""
        res = self._model.predict(np.ascontiguousarray(frame).copy(), imgsz=self.imgsz, classes=[0], conf=PERSON_CONF,
                                  device=self.device, half=self.half, verbose=False)
        if not res:
            return []
        b = res[0].boxes
        xyxy = b.xyxy.cpu().numpy()
        conf = b.conf.cpu().numpy()
        return [Box(float(x1), float(y1), float(x2), float(y2), float(c)) for (x1, y1, x2, y2), c in zip(xyxy, conf, strict=False)]


class HogPersons:
    """OpenCV HOG + linear SVM people detector: no download, CPU only, slower and less accurate."""

    backend = "hog"
    device = "cpu"
    device_name = "CPU"

    def __init__(self, width: int = 640) -> None:
        """Create the default OpenCV people detector."""
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self._width = width

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Return person boxes found by HOG (non-max suppressed)."""
        h, w = frame.shape[:2]
        s = min(1.0, self._width / w)
        small = cv2.resize(frame, (int(w * s), int(h * s))) if s < 1 else frame
        rects, weights = self._hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        boxes = [Box(float(x), float(y), float(x + bw), float(y + bh), float(min(1.0, max(0.0, float(wt) / 2))))
                 .scaled(1 / s) for (x, y, bw, bh), wt in zip(rects, np.ravel(weights), strict=False) if float(wt) > 0.3]
        return _nms(boxes)


def make_person_detector(device: str = "auto", imgsz: int = 640, half: bool = True) -> PersonDetector:
    """YOLO11n if ultralytics is importable (and loads), else HOG on CPU."""
    try:
        return YoloPersons(device=device, imgsz=imgsz, half=half)
    except Exception as e:  # ultralytics/torch missing or failed to load: fall back, never crash the box
        print(f"[edge_box] YOLO unavailable ({type(e).__name__}: {e}); using OpenCV HOG on CPU")
        return HogPersons()
