# Saakshi edge camera box

`edge_box/` turns a laptop + USB webcam into the on-site camera box from the Saakshi demo.
It detects people, restricted-zone entries and workers' rotating QR badges **on the device**,
and sends Saakshi only signed facts: *zone, kind, count, time* (and, for a punch, the opaque badge
string). Faces are found only so they can be blurred; no video or image ever leaves the laptop.

```
webcam ─▶ capture thread ─▶ processing thread ─────────────────────────────▶ latest-frame buffer ─▶ MJPEG 127.0.0.1:8765
                             1 faces  → privatize() (pixelate + blur, FIRST)              ▲ only PrivateFrame accepted
                             2 people → tracker ("person 3") → zones → signed event ──▶ POST /api/edge/events
                             3 QR "SKB1.…" badge  ─────────────────────────────────────▶ POST /api/edge/punch
                             4 overlay HUD drawn on the private frame
           heartbeat thread (2 s) ─▶ POST /api/edge/heartbeat      zone poll (2 s) ◀─ GET /api/edge/zones?camera=cam-01
```

## Windows quick start

```powershell
cd PramaanOS
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt          # Saakshi server
pip install -r requirements-edge.txt     # the box (OpenCV, httpx, ...)

# optional, for YOLO11n on the GTX 1650 (otherwise OpenCV HOG on CPU is used):
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install "ultralytics>=8.3"
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# optional, better face detector (YuNet, ~230 KB) into edge_box\models\ (else Haar is used):
python -m edge_box download-models

# terminal 1: Saakshi (seeds data\saakshi.db, including the box key "edge-box-1")
uvicorn saakshi.app:app --port 8000

# terminal 2: the box
python -m edge_box run --saakshi http://127.0.0.1:8000 --db data/saakshi.db --camera 0 --window
```

Then open **http://127.0.0.1:8000/camera/** (the live, privatized preview is
`http://127.0.0.1:8765/stream.mjpg`; `/frame.jpg` and `/health` also exist).

Useful flags: `--device auto|cuda|cpu`, `--imgsz 480` (faster YOLO), `--no-half` (disable FP16),
`--source clip.mp4 --loop` (test without a webcam), `--demo-zone` (a demo "Press zone" until the
server sends zones), `--dry-run` (no server: prints what would be sent), `--width/--height`,
`--preview-port`, `--camera-id cam-01`.

Without a webcam or server at all:

```bash
python -m edge_box run --source some_video.mp4 --loop --dry-run --demo-zone --window
```

## Drawing a restricted zone

Open `/camera/` in Saakshi, draw a polygon over the preview and save it. Points are normalised
(`[0..1]` of frame width/height) so they survive resolution changes. The box polls
`GET /api/edge/zones?camera=cam-01` every 2 s and starts using new zones on the next frame.
A person is "in" a zone when the **bottom-centre of their box (foot point)** is inside the polygon.
Each (person track, zone) fires at most once per **10 s**, so someone hovering at the edge is one
event, not fifty. The event is `{box_id, camera, zone, kind:"restricted_zone_entry", count, ts, sig}`
with `count` = people in that zone at that moment.

## How a worker punches in with their badge

1. On their phone the worker opens `http://<laptop>:8000/badge/?w=W001` — a QR that rotates.
2. They hold it up to the camera. The box decodes it (every 3rd frame), ignores anything that
   does not start with `SKB1.`, de-duplicates the same string for 20 s, and posts
   `{box_id, camera, badge, ts, sig}` to `/api/edge/punch`.
3. Saakshi verifies the box signature and the badge (rotation window, replay, 60 s since last punch),
   records an IN/OUT punch and returns the receipt. The HUD flashes "Meena Selvam - punched IN" and
   the ticker shows `08:02:11 Meena Selvam - IN - receipt sent`. A replayed or expired badge gets a 409
   and shows "badge refused".

The box never learns identity from a face: the name on screen comes back from Saakshi for the badge.

## Privacy guarantees (and where they are enforced)

| Guarantee | Where |
| --- | --- |
| Faces are detected **only** to blur them; no embeddings, landmarks kept, crops or face matching | `edge_box/faces.py` returns boxes only |
| Blur happens in memory **before** anything draws, encodes or streams a frame | `privacy.privatize()` is the first step of `EdgePipeline.process`; the raw frame is not used after it |
| An un-blurred frame cannot be encoded or streamed | `PrivateFrame` can only be created by `privatize()`; `encode_jpeg()` and `FrameBuffer.publish()` raise `TypeError` for anything else; the overlay draws via `PrivateFrame.derive` (tested) |
| Every pixel in each (25 %-padded) face box is changed, nothing else is | pixelation + Gaussian blur, plus a bit-flip on any pixel the blur left unchanged (tested) |
| If no face detector loads, the box refuses to start | `faces.make_face_detector()` |
| Preview is local only | MJPEG server binds `127.0.0.1` by default, `Cache-Control: no-store`, CORS only for the Saakshi origin |
| No video is recorded | frames live in a 1-slot buffer and are overwritten |
| Identity only from the worker's QR badge | `edge_box/badge.py`; person tracks are anonymous counters that never leave the box |
| Events carry zone / kind / count / time only | `edge_box/client.py`; the server's privacy guard rejects identity/image fields anyway |
| Every POST is signed by the box key (Ed25519 over canonical JSON) | `client.BoxSigner` |

**Demo shortcut:** the box key `edge-box-1` is read from the Saakshi SQLite DB on the same laptop via
`saakshi.crypto.KeyStore`. A real box generates its key inside a TPM / secure element; only the public
key is enrolled with the server and the private key never leaves the device.

## Troubleshooting

- **"could not open camera index 0"** – another app (Teams, Zoom, browser tab) holds the webcam, or the
  laptop's IR/virtual camera is index 0: try `--camera 1` / `--camera 2`. On Windows the box uses
  DirectShow (`cv2.CAP_DSHOW`) and MJPG, which most USB webcams need for 720p at 30 fps.
- **Black frames / slow start** – unplug/replug the USB camera; try `--width 640 --height 480`.
- **Low fps** – check the HUD says `YOLO11n on CUDA (GTX 1650)`. If it says `on CPU`, torch is the CPU
  build: reinstall with the `cu121` index URL above. Still slow: `--imgsz 480`. GPU trouble or
  garbage detections with FP16: `--no-half`. No GPU at all: `--device cpu` (HOG, ~8–15 fps).
- **"YOLO unavailable … using OpenCV HOG"** – ultralytics not installed or weights could not download
  (first run needs internet for `yolo11n.pt`).
- **HUD says `haar`** – run `python -m edge_box download-models` for YuNet (fewer missed faces).
- **Preview not showing in /camera/** – is the box running and `http://127.0.0.1:8765/health` reachable?
  Use `127.0.0.1` consistently (not `localhost`) or pass `--saakshi` with the exact origin you browse.
- **Windows Firewall prompt** – the preview binds to 127.0.0.1 only, so "Cancel"/private network is fine.
  Only allow it if you deliberately pass `--preview-host 0.0.0.0`.
- **401 from Saakshi** – the box key in `--db` is not the one the server uses: point `--db` at the same
  `data/saakshi.db` the server opened.
- **409 on a punch** – the badge QR expired, was replayed, or the worker punched under 60 s ago.

## Tests

```bash
pip install opencv-python-headless qrcode   # in CI / a headless sandbox
python -m pytest tests/test_edge_box.py -q
```

They run without a camera or GPU: frames, detectors and the Saakshi client are injected, and an
end-to-end test plays a synthetic video (a moving "person" and a `SKB1.test` QR) through the full
pipeline and through `python -m edge_box run --dry-run`.
