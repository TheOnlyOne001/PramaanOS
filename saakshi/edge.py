"""Edge camera events: counts and alerts from an on-site box, never images or identities.

The box (e.g. a Jetson running detection locally) signs each event with its
own Ed25519 key over canonical(body without sig). We verify the signature,
refuse anything that smells of imagery or person identity, and append an
`edge.event` to the ledger (worker_id None: these are about places, not people).
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException

from . import config, state
from .crypto import canonical, verify_sig
from .ledger import now_ts

router = APIRouter(prefix="/api")

BOX_KEYS = {"edge-box-1": "edge-box-1"}  # box_id -> KeyStore key name

KINDS = {
    "restricted_zone_entry": "Someone entered a restricted zone",
    "ppe_noncompliance": "PPE missing",
    "ppe_compliance_rate": "Share of people seen wearing required PPE (0-1)",
    "fire_smoke": "Smoke or fire detected",
    "blocked_exit": "Exit or aisle blocked",
    "person_down": "Person down (possible fall or collapse)",
    "queue_length": "People waiting in a queue",
    "near_miss": "Near miss between a person and a machine or vehicle",
    "heat_wbgt": "Heat stress index (WBGT, °C)",
}
ALERT_KINDS = {"restricted_zone_entry", "fire_smoke", "blocked_exit", "person_down", "near_miss", "ppe_noncompliance"}

SIGNAGE = ["ta", "hi", "or", "en"]
OWNER = "EHS officer, TUP-03 (reviewed by the safety committee)"
CAMERAS = [
    {"camera": "cam-01", "zone": "Gate", "purpose": "Exit kept clear; crowding at shift change",
     "kinds": ["blocked_exit", "queue_length"]},
    {"camera": "cam-04", "zone": "Line 4", "purpose": "PPE (needle guards, masks) and near misses on the line",
     "kinds": ["ppe_compliance_rate", "ppe_noncompliance", "near_miss", "person_down"]},
    {"camera": "cam-07", "zone": "Press zone", "purpose": "Keep people out of the press area while it runs; heat",
     "kinds": ["restricted_zone_entry", "ppe_compliance_rate", "heat_wbgt"]},
    {"camera": "cam-09", "zone": "Canteen", "purpose": "Smoke near the kitchen; lunch queue",
     "kinds": ["fire_smoke", "queue_length"]},
    {"camera": "cam-11", "zone": "Water point", "purpose": "Queue at the drinking water point",
     "kinds": ["queue_length"]},
    {"camera": "cam-12", "zone": "Store", "purpose": "Smoke in the fabric store; blocked aisles",
     "kinds": ["fire_smoke", "blocked_exit"]},
]
for _c in CAMERAS:
    _c.update({"owner": OWNER, "retention_hours": 24, "signage_languages": SIGNAGE, "box_id": "edge-box-1",
               "stores_images": False, "processing": "on device; only counts and alerts leave the box"})
ZONES = [c["zone"] for c in CAMERAS]

# --- Privacy guard -------------------------------------------------------------

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
    (re.compile(r"^[A-Za-z0-9+/=_-]{200,}$"), "an encoded blob"),
]


class PrivacyViolation(ValueError):
    pass


def _key_bad(key: str) -> bool:
    k = key.lower()
    tokens = set(re.split(r"[^a-z0-9]+", k))
    return bool(tokens & _FORBIDDEN_TOKENS) or any(s in k for s in _FORBIDDEN_SUBSTR)


def privacy_check(obj, path: str = "") -> None:
    """Raise PrivacyViolation if any key or value hints at imagery or a person's identity."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if _key_bad(str(k)):
                raise PrivacyViolation(f"field '{p}' is not allowed: edge events carry counts and alerts only,"
                                       " never images, faces, video, embeddings or person identity")
            privacy_check(v, p)
    elif isinstance(obj, list):
        if len(obj) > 16 and all(isinstance(x, (int, float)) for x in obj):
            raise PrivacyViolation(f"field '{path}' looks like an embedding vector; not allowed")
        for i, v in enumerate(obj):
            privacy_check(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        for pat, what in _VALUE_PATTERNS:
            if pat.search(obj):
                raise PrivacyViolation(f"field '{path}' looks like {what}; edge events must not carry imagery or"
                                       " person identity")


# --- Ingest ----------------------------------------------------------------------

_ALLOWED_FIELDS = {"box_id", "camera", "zone", "kind", "count", "value", "ts", "sig"}


def make_event(keys, box_id: str = "edge-box-1", **fields) -> dict:
    """Build and sign an event as the box would. `keys` is a saakshi.crypto.KeyStore.

    On a real box the private key is generated on the device and never leaves it;
    the demo keeps it in the site DB so the simulator can sign.
    """
    body = {"box_id": box_id, "ts": fields.pop("ts", None) or now_ts(), **fields}
    body = {k: v for k, v in body.items() if v is not None}
    body["sig"] = keys.sign(BOX_KEYS.get(box_id, box_id), canonical(body))
    return body


def ingest(body: dict) -> dict:
    """Validate, verify and record one event. Raises HTTPException (422 privacy/shape, 401 signature)."""
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    try:
        privacy_check(body)
    except PrivacyViolation as e:
        raise HTTPException(422, f"privacy guard: {e}")
    extra = set(body) - _ALLOWED_FIELDS
    if extra:
        raise HTTPException(422, f"unknown fields: {sorted(extra)}")
    for f in ("box_id", "camera", "zone", "kind", "ts", "sig"):
        if not isinstance(body.get(f), str) or not body.get(f):
            raise HTTPException(422, f"'{f}' is required")
    if body["kind"] not in KINDS:
        raise HTTPException(422, f"unknown kind '{body['kind']}'; allowed: {sorted(KINDS)}")
    for f in ("count", "value"):
        if f in body and body[f] is not None and (isinstance(body[f], bool) or not isinstance(body[f], (int, float))):
            raise HTTPException(422, f"'{f}' must be a number")
    try:
        datetime.fromisoformat(body["ts"])
    except ValueError:
        raise HTTPException(422, "'ts' must be ISO 8601")
    if body["box_id"] not in BOX_KEYS:
        raise HTTPException(401, f"unknown edge box '{body['box_id']}'")
    st = state.get()
    unsigned = {k: v for k, v in body.items() if k != "sig"}
    if not verify_sig(st.keys.public_hex(BOX_KEYS[body["box_id"]]), canonical(unsigned), body["sig"]):
        raise HTTPException(401, "signature does not verify against the box key")
    payload = {"box_id": body["box_id"], "camera": body["camera"], "zone": body["zone"], "kind": body["kind"],
               "count": body.get("count"), "value": body.get("value"), "box_ts": body["ts"], "box_sig": body["sig"]}
    return st.ledger.append("edge.event", payload, worker_id=None, ts=body["ts"], signer="site")


def _row(ev: dict) -> dict:
    p = ev["payload"]
    return {"seq": ev["seq"], "ts": ev["ts"], "box_id": p.get("box_id"), "camera": p.get("camera"),
            "zone": p.get("zone"), "kind": p.get("kind"), "count": p.get("count"), "value": p.get("value"),
            "ref": ev["ref"]}


# --- Console-facing functions --------------------------------------------------------


def recent(limit: int = 20, kind: str | None = None) -> list[dict]:
    evs = state.get().ledger.events(type="edge.event", desc=True)
    rows = [_row(e) for e in evs if kind is None or e["payload"].get("kind") == kind]
    return rows[:limit]


def summary(day: str | None = None) -> dict:
    st = state.get()
    if day is None:
        last = st.ledger.events(type="edge.event", desc=True, limit=1)
        day = last[0]["day"] if last else config.DEMO_DAY
    evs = [_row(e) for e in st.ledger.events(type="edge.event", day=day)]
    zones = {z: {} for z in ZONES}
    ppe: dict[str, dict[str, list[float]]] = {}
    for e in evs:
        zones.setdefault(e["zone"], {})
        zones[e["zone"]][e["kind"]] = zones[e["zone"]].get(e["kind"], 0) + 1
        if e["kind"] == "ppe_compliance_rate" and isinstance(e["value"], (int, float)):
            ppe.setdefault(e["zone"], {}).setdefault(e["ts"][11:13], []).append(float(e["value"]))
    ppe_out = []
    for zone, hours in ppe.items():
        allv = [v for vs in hours.values() for v in vs]
        ppe_out.append({"zone": zone, "rate": round(sum(allv) / len(allv), 3),
                        "by_hour": [{"hour": h, "rate": round(sum(v) / len(v), 3), "n": len(v)}
                                    for h, v in sorted(hours.items())]})
    queues = [e for e in evs if e["kind"] == "queue_length"]
    peak_q = max(queues, key=lambda e: e["count"] or 0) if queues else None
    return {
        "day": day,
        "zones": [{"zone": z, "events": k} for z, k in zones.items()],
        "ppe_compliance_by_zone": ppe_out,
        "alerts": [e for e in evs if e["kind"] in ALERT_KINDS],
        "peak_queue": peak_q,
        "n_events": len(evs),
        "last_event": evs[-1] if evs else None,
    }


# --- HTTP ---------------------------------------------------------------------------


@router.post("/edge/events")
def post_event(body: dict = Body(...)):
    return ingest(body)


@router.get("/edge/events")
def get_events(limit: int = 50, kind: str | None = None):
    return recent(limit, kind)


@router.get("/edge/summary")
def get_summary(day: str | None = None):
    return summary(day)


@router.get("/edge/cameras")
def get_cameras():
    return CAMERAS


# --- Demo seed ------------------------------------------------------------------------


def seed_demo(st) -> None:
    keys = st.keys
    tz = config.TZ
    out = []

    def ev(ts, camera, zone, kind, count=None, value=None):
        out.append(make_event(keys, camera=camera, zone=zone, kind=kind, count=count, value=value, ts=ts + tz))

    past = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-26"]
    for i, d in enumerate(past):
        ev(f"{d}T11:00:00", "cam-04", "Line 4", "ppe_compliance_rate", value=[0.86, 0.88, 0.84, 0.9, 0.87, 0.89][i])
        ev(f"{d}T11:00:00", "cam-07", "Press zone", "ppe_compliance_rate", value=[0.78, 0.81, 0.76, 0.8, 0.79, 0.82][i])
        ev(f"{d}T15:05:00", "cam-11", "Water point", "queue_length", count=[6, 7, 8, 6, 9, 8][i])
    ev("2026-10-22T10:42:00", "cam-07", "Press zone", "restricted_zone_entry", count=1)
    ev("2026-10-23T16:18:00", "cam-04", "Line 4", "near_miss", count=1)
    ev("2026-10-24T14:00:00", "cam-07", "Press zone", "heat_wbgt", value=30.5)
    # today
    d = config.DEMO_DAY
    for h, (l4, pz) in zip(range(9, 14), [(0.91, 0.84), (0.89, 0.8), (0.86, 0.77), (0.9, 0.79), (0.88, 0.75)]):
        ev(f"{d}T{h:02d}:00:00", "cam-04", "Line 4", "ppe_compliance_rate", value=l4)
        ev(f"{d}T{h:02d}:00:00", "cam-07", "Press zone", "ppe_compliance_rate", value=pz)
    ev(f"{d}T11:20:00", "cam-04", "Line 4", "near_miss", count=1)
    ev(f"{d}T12:30:00", "cam-09", "Canteen", "queue_length", count=14)
    ev(f"{d}T13:00:00", "cam-07", "Press zone", "heat_wbgt", value=31.0)
    ev(f"{d}T14:45:00", "cam-11", "Water point", "queue_length", count=7)
    ev(f"{d}T15:00:00", "cam-11", "Water point", "queue_length", count=11)
    ev(f"{d}T15:10:00", "cam-11", "Water point", "queue_length", count=9)
    for body in sorted(out, key=lambda b: b["ts"]):
        ingest(body)
