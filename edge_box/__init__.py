"""Saakshi edge camera box: on-device detection that sends counts and badge punches, never video.

Pipeline per frame (see `pipeline.EdgePipeline.process`):

1. `faces` finds faces in the raw frame, only so they can be blurred;
2. `privacy.privatize` pixelates them; the raw frame is never used again;
3. `persons` + `tracker` count anonymous people ("person 3"), `zones` fires
   restricted-zone entries, `badge` reads a worker's rotating QR badge;
4. `overlay` draws the HUD on the private frame, `server` streams it to 127.0.0.1 only;
5. `client` signs each event with the box's Ed25519 key and posts it to Saakshi.
"""
from __future__ import annotations

__version__ = "0.1.0"
BOX_ID = "edge-box-1"
CAMERA_ID = "cam-01"
