"""Face *detection only*, so faces can be blurred: YuNet if its ONNX model is present, else Haar.

No landmarks are kept, no embeddings are computed, no face is cropped, stored or compared.
The detectors return boxes; `privacy.privatize` destroys the pixels inside them.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .geometry import Box

MODELS_DIR = Path(__file__).resolve().parent / "models"
YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
DETECT_WIDTH = 640  # detect on a downscaled copy for speed; boxes are mapped back


class FaceDetector(Protocol):
    """Anything that returns face boxes (pixel coords of the given frame)."""

    backend: str

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Return face boxes in the frame."""
        ...


def _downscale(frame: np.ndarray, width: int = DETECT_WIDTH) -> tuple[np.ndarray, float]:
    """Return (resized frame, scale back to original) with the given max width."""
    h, w = frame.shape[:2]
    if w <= width:
        return frame, 1.0
    s = width / w
    return cv2.resize(frame, (width, max(1, int(h * s))), interpolation=cv2.INTER_AREA), 1 / s


class YuNetFaces:
    """OpenCV YuNet (cv2.FaceDetectorYN): fast, accurate CNN face detector, ~230 KB ONNX model."""

    backend = "yunet"

    def __init__(self, model_path: Path, score_threshold: float = 0.6) -> None:
        """Load the YuNet ONNX model."""
        self._det = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold, 0.3, 50)
        self._size: tuple[int, int] = (320, 320)

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Return face boxes found by YuNet."""
        small, back = _downscale(frame)
        h, w = small.shape[:2]
        if (w, h) != self._size:
            self._det.setInputSize((w, h))
            self._size = (w, h)
        _, faces = self._det.detect(small if small.ndim == 3 else cv2.cvtColor(small, cv2.COLOR_GRAY2BGR))
        if faces is None:
            return []
        return [Box(float(f[0]), float(f[1]), float(f[0] + f[2]), float(f[1] + f[3]), float(f[-1])).scaled(back)
                for f in faces]


class HaarFaces:
    """OpenCV Haar cascade (ships inside opencv-python, zero download). Frontal + profile."""

    backend = "haar"

    def __init__(self) -> None:
        """Load the bundled frontal and profile face cascades."""
        base = Path(cv2.data.haarcascades)
        self._cascades = [cv2.CascadeClassifier(str(base / n))
                          for n in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")]
        self._cascades = [c for c in self._cascades if not c.empty()]
        if not self._cascades:
            raise RuntimeError("no Haar face cascade found in cv2.data.haarcascades")

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Return face boxes found by the Haar cascades."""
        small, back = _downscale(frame, 480)
        gray = small if small.ndim == 2 else cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        out: list[Box] = []
        for c in self._cascades:
            for x, y, w, h in c.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(20, 20)):
                out.append(Box(float(x), float(y), float(x + w), float(y + h), 0.8).scaled(back))
        return out


def make_face_detector(models_dir: Path = MODELS_DIR) -> FaceDetector:
    """Best available detector: YuNet if the model file exists, else Haar. Refuses to run with neither.

    Running without a face detector would stream unblurred faces, so there is no "none" tier.
    """
    model = models_dir / YUNET_FILE
    if model.exists() and hasattr(cv2, "FaceDetectorYN"):
        try:
            return YuNetFaces(model)
        except cv2.error:
            pass
    if hasattr(cv2, "CascadeClassifier"):
        return HaarFaces()
    raise RuntimeError("no face detector available (need opencv-python<5 for Haar, or the YuNet model): "
                       "refusing to run without face blurring")


def download_models(models_dir: Path = MODELS_DIR, url: str = YUNET_URL) -> Path:
    """Fetch the YuNet face model into models_dir (skips if already present) and return its path."""
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / YUNET_FILE
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if not url.startswith("https://"):
        raise ValueError("model URL must be https")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=60) as r, tmp.open("wb") as f:  # noqa: S310 - fixed https URL
        f.write(r.read())
    tmp.replace(dest)
    return dest
