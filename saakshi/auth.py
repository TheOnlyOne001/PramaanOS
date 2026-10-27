"""Who may call what: signed bearer tokens + one deny-by-default policy table.

Token format (compact, stdlib only):  base64url(json{sub, role, wid?, exp}) "." base64url(HMAC-SHA256)
The HMAC key is derived from 32 random bytes stored once in the `keys` table (row "auth-hmac").
Tokens expire after 12 h. Signatures are compared in constant time (hmac.compare_digest).

Roles: worker (carries wid), supervisor, hr, auditor.
Demo: POST /api/auth/demo-login issues a token for any role, ONLY when config.DEMO_MODE.
Production: workers sign in with phone OTP, or a PIN on a shared line phone; employer staff via the
company SSO. Those flows mint the same token, so this policy table does not change.

Enforcement is a single ASGI middleware (AuthMiddleware) that reads POLICY top to bottom; the first
rule whose method and path match decides. A path under /api with no rule is refused (deny by default).
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import JSONResponse

from . import config, state

ROLES = ("worker", "supervisor", "hr", "auditor")
TTL_SECONDS = 12 * 3600
DEFAULT_SUB = {"supervisor": "S001", "hr": "H001", "auditor": "A001"}

# --- policy ---------------------------------------------------------------------------------------
# Allowed values: "public" (no token needed), a role name, or one of these "self" rules for workers:
#   "self"          {wid} in the path equals the token's wid
#   "query_self"    ?worker_id= in the query equals the token's wid
#   "body_self"     "worker_id" in the JSON body equals the token's wid
#   "consent_owner" the overtime request {rid} belongs to the token's wid
PUBLIC = ("public",)
ANY = ROLES
EMPLOYER = ("supervisor", "hr", "auditor")
W = r"(?P<wid>[A-Za-z0-9_-]+)"

POLICY: list[tuple[str, str, tuple[str, ...]]] = [
    # Public: site info, rules, recruiters verifying a credential, signed edge box, anonymous relay.
    ("GET", r"/site", PUBLIC),
    ("GET", r"/rules", PUBLIC),
    ("GET", r"/voice/topics", PUBLIC),
    ("POST", r"/relay/voice/reports", PUBLIC),       # anonymous BY DESIGN: identity is stripped, never read
    ("GET", r"/passport/issuers", PUBLIC),
    ("GET", r"/passport/status", PUBLIC),
    ("GET", r"/passport/credentials/[^/]+(/qr)?", PUBLIC),
    ("POST", r"/edge/events", PUBLIC),                # authenticated by the box's Ed25519 signature
    ("POST", r"/auth/demo-login", PUBLIC),            # refuses unless DEMO_MODE
    ("*", r"/demo/.+", PUBLIC),                       # each handler refuses unless DEMO_MODE
    # A worker's own record.
    ("GET", r"/workers", ANY),
    ("GET", rf"/workers/{W}", ("self", "supervisor", "hr", "auditor")),
    ("GET", rf"/workers/{W}/receipts", ("self", "auditor")),
    ("POST", rf"/workers/{W}/receipts/check", ("self", "auditor")),
    ("GET", rf"/workers/{W}/access-log", ("self", "auditor")),
    ("POST", rf"/workers/{W}/lookup", ("supervisor", "hr")),   # viewer is taken from the token
    ("GET", r"/pay/fairness", ("hr", "auditor")),
    ("POST", r"/pay/run", ("hr",)),
    ("GET", rf"/pay/{W}/(today|payslip)", ("self", "hr")),
    ("GET", rf"/hours/{W}", ("self", "supervisor", "hr")),
    # Overtime.
    ("GET", r"/ot/cap", ANY),
    ("POST", r"/ot/requests", ("supervisor",)),
    ("GET", r"/ot/requests", ("query_self", "supervisor", "hr", "auditor")),
    ("POST", r"/ot/requests/(?P<rid>[^/]+)/consent", ("consent_owner",)),
    # Voice: issuer sees the worker, relay (above) never does.
    ("POST", r"/voice/issue", ("body_self",)),
    ("POST", r"/voice/scrub", ANY),
    ("GET", r"/voice/cases/[^/]+", ANY),
    ("GET", r"/voice/board", ANY),                   # the public notice board of published themes
    ("GET", r"/voice/themes", EMPLOYER),
    ("POST", r"/voice/themes/[^/]+/respond", ("supervisor", "hr")),
    # Skills passport.
    ("GET", r"/passport/(coverage|expiring)", EMPLOYER),
    ("POST", r"/passport/match", EMPLOYER),
    ("POST", r"/passport/credentials/[^/]+/revoke", ("hr",)),
    ("GET", rf"/passport/{W}", ("self", "supervisor", "hr")),
    # Employer console, edge, ledger.
    ("GET", r"/console/overview", EMPLOYER),
    ("GET", r"/sdg8/scorecard", EMPLOYER),
    ("GET", r"/edge/(events|summary|cameras)", EMPLOYER),
    ("GET", r"/ledger/verify", ANY),                 # workers must be able to verify the chain
    ("GET", r"/ledger/roots", ANY),
    ("GET", r"/ledger/events(/\d+(/proof)?)?", EMPLOYER),
    ("POST", r"/ledger/roots/publish", ("hr",)),
    ("POST", r"/punch", ("supervisor",)),            # stands in for the gate device
    ("POST", r"/punch/correction", ("supervisor",)),
    ("POST", r"/production", ("supervisor",)),
]
_COMPILED = [(m, re.compile(p + r"/?"), roles) for m, p, roles in POLICY]

_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("saakshi_principal", default=None)


def current() -> dict | None:
    """The verified principal for this request (None when auth is off or the route is public)."""
    return _current.get()


# --- tokens ---------------------------------------------------------------------------------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key() -> bytes:
    # Serverless hosts run several instances with separate /tmp databases: set SAAKSHI_AUTH_SECRET
    # there so a token issued by one instance verifies on another.
    env = os.environ.get("SAAKSHI_AUTH_SECRET")
    if env:
        return hashlib.sha256(b"saakshi-auth-v1|" + env.encode()).digest()
    st = state.get()
    with st.lock:  # the middleware runs on the event loop; share the DB lock with handler threads
        seed = st.keys.get("auth-hmac").encode()  # 32 random bytes, stored once in `keys`
    return hashlib.sha256(b"saakshi-auth-v1|" + seed).digest()


def issue_token(role: str, sub: str | None = None, wid: str | None = None, ttl: int = TTL_SECONDS) -> str:
    if role not in ROLES:
        raise ValueError("unknown role")
    payload = {"sub": sub or wid or DEFAULT_SUB[role], "role": role, "exp": int(time.time()) + ttl}
    if role == "worker":
        if not wid:
            raise ValueError("worker token needs a wid")
        payload["wid"] = wid
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
        expected = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected.encode(), sig.encode()):
            return None
        p = json.loads(_unb64(body))
        if not isinstance(p, dict) or p.get("role") not in ROLES or int(p.get("exp", 0)) <= time.time():
            return None
        if p["role"] == "worker" and not p.get("wid"):
            return None
        return p
    except Exception:  # noqa: BLE001 - any malformed token is simply "not authenticated"
        return None


# --- policy evaluation ----------------------------------------------------------------------------
def match(method: str, path: str):
    method = "GET" if method == "HEAD" else method
    for m, rx, roles in _COMPILED:
        mm = rx.fullmatch(path)
        if mm and m in ("*", method):
            return roles, mm
    return None, None


def _owns_request(rid: str, wid: str) -> bool:
    from . import pay
    with state.get().lock:
        return any(r.get("request_id") == rid for r in pay.list_requests(worker_id=wid))


def allowed(roles, mm, p: dict, query: dict, body: dict | None) -> bool:
    role, wid = p["role"], p.get("wid")
    if role in roles:
        return True
    if role != "worker":
        return False
    g = mm.groupdict()
    if "self" in roles and g.get("wid") == wid:
        return True
    if "query_self" in roles and query.get("worker_id", [None])[0] == wid:
        return True
    if "body_self" in roles and isinstance(body, dict) and body.get("worker_id") == wid:
        return True
    if "consent_owner" in roles and g.get("rid") and _owns_request(g["rid"], wid):
        return True
    return False


_BODY_RULES = {"body_self"}


class AuthMiddleware:
    """Pure ASGI middleware: authenticates the bearer token and applies POLICY before any handler."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not config.AUTH_ENABLED or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        path = scope["path"][4:]
        roles, mm = match(scope["method"], path)
        if roles == PUBLIC:
            if path.rstrip("/") == "/relay/voice/reports":
                # The relay must never see who is calling: drop credentials and cookies before the handler.
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in scope["headers"] if k not in (b"authorization", b"cookie")]
            return await self.app(scope, receive, send)

        auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        p = verify_token(auth[7:].strip()) if auth[:7].lower() == "bearer " else None
        if p is None:
            return await JSONResponse({"detail": "authentication required"}, 401,
                                      headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        if roles is None:
            return await JSONResponse({"detail": "no access policy for this route"}, 403)(scope, receive, send)

        is_lookup = scope["method"] == "POST" and path.rstrip("/").endswith("/lookup")
        body_bytes, body = None, None
        if is_lookup or (_BODY_RULES & set(roles) and p["role"] == "worker"):
            body_bytes = await _read_body(receive)
            try:
                body = json.loads(body_bytes or b"null")
            except ValueError:
                body = None

        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        if not allowed(roles, mm, p, query, body):
            return await JSONResponse({"detail": f"role '{p['role']}' may not do this"}, 403)(scope, receive, send)

        if is_lookup and isinstance(body, dict):
            # Who opened the record is taken from the token, never from what the client claims.
            body["viewer"], body["viewer_role"] = p["sub"], p["role"]
            body_bytes = json.dumps(body).encode()
            scope = dict(scope)
            scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"content-length"] + [
                (b"content-length", str(len(body_bytes)).encode())]

        if body_bytes is not None:
            receive = _replay(body_bytes, receive)
        tok = _current.set(p)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(tok)


async def _read_body(receive) -> bytes:
    chunks = []
    while True:
        msg = await receive()
        if msg["type"] == "http.request":
            chunks.append(msg.get("body", b""))
            if not msg.get("more_body"):
                break
        else:
            break
    return b"".join(chunks)


def _replay(data: bytes, receive):
    sent = False

    async def _receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": data, "more_body": False}
        return await receive()
    return _receive


# --- demo login -----------------------------------------------------------------------------------
router = APIRouter(prefix="/api")


class DemoLogin(BaseModel):
    role: str
    worker_id: str | None = None


@router.post("/auth/demo-login")  # demo-only; see SECURITY.md
def demo_login(body: DemoLogin):
    """Demo only. Production: phone OTP or a PIN on a shared line phone (workers), SSO (staff)."""
    if not config.DEMO_MODE:
        raise HTTPException(404, "demo login is disabled (SAAKSHI_DEMO=0); use the production sign-in")
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
    wid = None
    if body.role == "worker":
        wid = body.worker_id or ""
        if not state.get().conn.execute("SELECT 1 FROM workers WHERE id=?", (wid,)).fetchone():
            raise HTTPException(404, "unknown worker")
    p = {"role": body.role, "wid": wid}
    return {"token": issue_token(body.role, wid=wid), **{k: v for k, v in p.items() if v},
            "sub": wid or DEFAULT_SUB[body.role], "expires_in": TTL_SECONDS}
