"""Verifiable credential shape, the site issuer, canonical signing and offline verification.

A credential is W3C-VC-2.0-shaped and signed with Ed25519 over the canonical JSON
of the VC without `proof`. No floats anywhere in a VC: numbers are ints or strings,
so the browser's canonical JSON (web/verify/verify.js) is byte-identical to Python's.
"""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import Any, TypedDict

from .. import config, state
from ..crypto import canonical, verify_sig

ISSUER_KEY = "site-issuer"
VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
PROOF_TYPE = "Ed25519Signature2020"
STATUS_LIST_PATH = "/api/passport/status"
DEFAULT_VERIFY_BASE = "http://localhost:8000"
ID_HEX_CHARS = 16  # hex digits kept from a hash or key in subject and issuer ids


class Issuer(TypedDict):
    """The site issuer's identity and public key."""

    id: str
    name: str
    public_key_hex: str


class Proof(TypedDict):
    """An Ed25519 signature over the credential's canonical bytes."""

    type: str
    verificationMethod: str
    created: str
    proofPurpose: str
    proofValue: str


class StatusEntry(TypedDict):
    """A credential's pointer into the revocation status list."""

    id: str
    type: str
    statusPurpose: str
    statusListIndex: str
    statusListCredential: str


VerifiableCredential = TypedDict("VerifiableCredential", {
    "@context": list[str],
    "type": list[str],
    "id": str,
    "issuer": dict[str, str],
    "validFrom": str,
    "validUntil": str,
    "credentialSubject": dict[str, Any],
    "credentialStatus": StatusEntry,
    "proof": Proof,
}, total=False)
"""The credential document exactly as signed and served."""


def subject_id(wid: str) -> str:
    """Pseudonymous, stable per site: the employer ID never appears in the VC."""
    digest = hashlib.sha256(f"{config.SITE_ID}|{wid}".encode()).hexdigest()
    return "urn:saakshi:worker:" + digest[:ID_HEX_CHARS]


def issuer() -> Issuer:
    """Return the site issuer's id, name and public key."""
    pub = state.get().keys.public_hex(ISSUER_KEY)
    return {"id": f"did:key:site-issuer:{pub[:ID_HEX_CHARS]}", "name": config.SITE_NAME, "public_key_hex": pub}


def verification_method(iss: Issuer) -> str:
    """Return the key reference a proof names for this issuer."""
    return f"{iss['id']}#key-1"


def status_list_id() -> str:
    """Return the id of this site's revocation status list."""
    return f"urn:saakshi:status:{config.SITE_ID}"


def status_entry(idx: int) -> StatusEntry:
    """Return the credentialStatus block pointing at bit `idx` of the status list."""
    return {"id": f"{status_list_id()}#{idx}", "type": "BitstringStatusListEntry",
            "statusPurpose": "revocation", "statusListIndex": str(idx),
            "statusListCredential": STATUS_LIST_PATH}


def b64url(data: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    """Decode unpadded URL-safe base64 to bytes."""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def vc_signing_bytes(vc: Mapping[str, Any]) -> bytes:
    """Return the canonical bytes of a credential, excluding its proof, for signing."""
    return canonical({k: v for k, v in vc.items() if k != "proof"})


def sign(vc: VerifiableCredential, ts: str) -> VerifiableCredential:
    """Attach the site issuer's proof to `vc` (in place) and return it."""
    sig = state.get().keys.sign(ISSUER_KEY, vc_signing_bytes(vc))
    vc["proof"] = {"type": PROOF_TYPE, "verificationMethod": verification_method(issuer()), "created": ts,
                   "proofPurpose": "assertionMethod", "proofValue": sig}
    return vc


def verify_vc(vc: Mapping[str, Any], public_key_hex: str | None = None) -> bool:
    """Python reference verifier (the browser does the same in web/verify/verify.js)."""
    pub = public_key_hex or issuer()["public_key_hex"]
    proof = vc.get("proof") or {}
    return verify_sig(pub, vc_signing_bytes(vc), proof.get("proofValue", ""))


def verify_url(vc: Mapping[str, Any], base: str = DEFAULT_VERIFY_BASE) -> str:
    """Return the browser verification URL embedding the credential."""
    return base.rstrip("/") + "/verify/#" + b64url(canonical(vc))


def qr_svg(url: str) -> str:
    """Render `url` as an SVG QR code (low error correction keeps a full VC scannable)."""
    import qrcode
    from qrcode.image.svg import SvgPathImage
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=2, image_factory=SvgPathImage)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image().to_string(encoding="unicode")
