"""Privacy guard for edge events: refuse anything that smells of imagery or a person's identity.

Edge boxes may send counts and alerts about places, never images, video, faces,
embeddings or person/worker/track identifiers. The guard walks every key and value
of an event and raises `PrivacyViolation` on the first thing that looks like one.
"""
from __future__ import annotations

import re
from typing import Any

EMBEDDING_MIN_LEN = 16  # a longer all-numeric list is treated as a feature vector
ENCODED_BLOB_MIN_LEN = 200  # a longer base64-ish string is treated as an encoded image or vector

_FORBIDDEN_TOKENS = {"image", "images", "img", "frame", "frames", "jpeg", "jpg", "png", "video", "clip", "clips",
                     "face", "faces", "embedding", "embeddings", "name", "names", "photo", "snapshot", "thumbnail",
                     "crop", "biometric", "plate"}
_FORBIDDEN_SUBSTR = ("person_id", "worker_id", "track_id", "face", "embedding", "image", "jpeg", "video",
                     "personid", "workerid", "trackid", "employee")
_VALUE_PATTERNS = [
    (re.compile(r"^data:", re.I), "a data: URI"),
    (re.compile(r"\.(jpe?g|png|gif|bmp|webp|mp4|avi|mkv|mov|h264)\b", re.I), "an image or video file"),
    (re.compile(r"\b(image|frame|jpeg|png|video|clip|face|faces|embedding|snapshot)\b", re.I), "imagery"),
    (re.compile(r"\b(person_id|worker_id|track_id)\b", re.I), "a person identifier"),
    (re.compile(r"^[WS]\d{3}$"), "a worker ID"),
    (re.compile(rf"^[A-Za-z0-9+/=_-]{{{ENCODED_BLOB_MIN_LEN},}}$"), "an encoded blob"),
]


class PrivacyViolation(ValueError):
    """Raised when an edge event carries identifying or disallowed data."""


def _key_bad(key: str) -> bool:
    """Return True if a field name names imagery or identity, as a word or inside a compound."""
    k = key.lower()
    tokens = set(re.split(r"[^a-z0-9]+", k))
    return bool(tokens & _FORBIDDEN_TOKENS) or any(s in k for s in _FORBIDDEN_SUBSTR)


def _looks_like_vector(items: list[Any]) -> bool:
    return len(items) > EMBEDDING_MIN_LEN and all(isinstance(x, (int, float)) for x in items)


def privacy_check(obj: Any, path: str = "") -> None:
    """Raise PrivacyViolation if any key or value hints at imagery or a person's identity."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if _key_bad(str(k)):
                raise PrivacyViolation(f"field '{p}' is not allowed: edge events carry counts and alerts only,"
                                       " never images, faces, video, embeddings or person identity")
            privacy_check(v, p)
    elif isinstance(obj, list):
        if _looks_like_vector(obj):
            raise PrivacyViolation(f"field '{path}' looks like an embedding vector; not allowed")
        for i, v in enumerate(obj):
            privacy_check(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        for pat, what in _VALUE_PATTERNS:
            if pat.search(obj):
                raise PrivacyViolation(f"field '{path}' looks like {what}; edge events must not carry imagery or"
                                       " person identity")
