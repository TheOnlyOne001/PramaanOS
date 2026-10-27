"""Vercel serverless entry point: puts the repo root on sys.path and exposes the FastAPI app."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from saakshi.app import app  # noqa: E402  (sys.path must be set first)

__all__ = ["app"]
