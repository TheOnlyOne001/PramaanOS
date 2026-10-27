"""The privacy gate: faces are blurred in memory before anything draws, encodes or streams a frame.

`privatize(frame, faces)` is the only way to make a `PrivateFrame`. The overlay draws on a
`PrivateFrame`, the JPEG encoder (`encode_jpeg`) and the preview buffer accept nothing else,
so an un-blurred frame cannot reach the MJPEG stream, a snapshot or the window by construction.

What this module never does: compute face embeddings, crop or keep faces, or identify anyone.
Faces are found only to be destroyed (pixelated, then Gaussian-blurred).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeAlias

import cv2
import numpy as np

from .geometry import Box

FACE_PAD = 0.25  # grow every face box by 25% on each side before blurring
PIXEL_BLOCK = 14  # pixelation block size in pixels (at least 6 blocks across the face)
JPEG_QUALITY = 75

Image: TypeAlias = np.ndarray
_TOKEN = object()


class PrivateFrame:
    """A frame whose faces have already been blurred. Only `privatize` (and `derive`) can create one."""

    __slots__ = ("_image", "faces")

    def __init__(self, image: Image, faces: Sequence[Box], *, _token: object = None) -> None:
        """Wrap an already-privatized image. Raises TypeError unless called from this module."""
        if _token is not _TOKEN:
            raise TypeError("PrivateFrame can only be created by privatize()")
        image.flags.writeable = False
        self._image = image
        self.faces: tuple[Box, ...] = tuple(faces)

    @property
    def image(self) -> Image:
        """The privatized pixels, read-only (detectors may read them; nobody may write raw pixels back)."""
        return self._image

    @property
    def shape(self) -> tuple[int, ...]:
        """Shape of the image array (height, width, channels)."""
        return tuple(self._image.shape)

    def derive(self, draw: Callable[[Image], Image | None]) -> PrivateFrame:
        """Return a new PrivateFrame drawn on a copy of this one (e.g. the overlay).

        Drawing on top of blurred pixels cannot un-blur them, so the result stays private.
        """
        canvas = self._image.copy()
        out = draw(canvas)
        result = canvas if out is None else out
        if result.shape != self._image.shape:
            raise ValueError("overlay must keep the frame shape")
        return PrivateFrame(result, self.faces, _token=_TOKEN)


def _destroy(roi: Image) -> Image:
    """Pixelate then Gaussian-blur a region so no facial detail survives; every pixel is changed."""
    h, w = roi.shape[:2]
    block = max(2, min(PIXEL_BLOCK, max(1, min(w, h) // 6)))
    small = cv2.resize(roi, (max(1, w // block), max(1, h // block)), interpolation=cv2.INTER_AREA)
    pix = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    k = max(3, (min(w, h) // 4) | 1)
    out = cv2.GaussianBlur(pix, (k, k), 0)
    same = np.all(out == roi, axis=-1) if out.ndim == 3 else out == roi
    if same.any():  # guarantee: no pixel inside the box keeps its original value
        out[same] ^= 0x10
    return out


def face_regions(faces: Sequence[Box], width: int, height: int) -> list[Box]:
    """The padded, frame-clipped regions that `privatize` will blur."""
    return [f.padded(FACE_PAD, width, height) for f in faces]


def privatize(frame: Image, faces: Sequence[Box]) -> PrivateFrame:
    """Blur every (25%-padded) face box in a copy of `frame` and return it as a PrivateFrame.

    This is the first thing done to a captured frame; nothing downstream sees the raw pixels.
    """
    if not isinstance(frame, np.ndarray) or frame.ndim not in (2, 3):
        raise TypeError("privatize expects an image array")
    h, w = frame.shape[:2]
    out = frame.copy()
    regions = face_regions(faces, w, h)
    for r in regions:
        x1, y1, x2, y2 = r.int_coords()
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 >= 1 and y2 - y1 >= 1:
            out[y1:y2, x1:x2] = _destroy(out[y1:y2, x1:x2])
    return PrivateFrame(out, regions, _token=_TOKEN)


def encode_jpeg(frame: PrivateFrame, quality: int = JPEG_QUALITY) -> bytes:
    """JPEG-encode a privatized frame. Refuses (TypeError) anything that did not pass `privatize`."""
    if not isinstance(frame, PrivateFrame):
        raise TypeError("refusing to encode an un-privatized frame: call privatize() first")
    ok, buf = cv2.imencode(".jpg", frame.image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return bytes(buf.tobytes())
