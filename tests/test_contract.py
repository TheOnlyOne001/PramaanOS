"""API.md is the contract: every documented endpoint exists, every /api route is documented."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROW = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*([^|\s]+)\s*\|", re.M)

# /api routes deliberately left out of API.md, with the reason.
UNDOCUMENTED_OK = {
    ("GET", "/api/passport/coverage"): "internal feed for the console skills panel (single points of failure)",
    ("GET", "/api/passport/expiring"): "internal feed for the console skills panel (credentials expiring in 30 days)",
}


def _norm(path: str) -> str:
    path = path.split("?", 1)[0].rstrip("/") or "/"
    if not path.startswith("/api"):
        path = "/api" + path
    return re.sub(r"\{[^}]+\}", "{}", path)


def documented() -> set[tuple[str, str]]:
    text = (ROOT / "API.md").read_text(encoding="utf-8")
    return {(m, _norm(p)) for m, p in ROW.findall(text)}


def app_routes() -> set[tuple[str, str]]:
    from saakshi.app import app
    out = set()
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                out.add((method.upper(), _norm(path) if path.startswith("/api") else path))
    return out


def test_api_md_has_rows():
    assert len(documented()) >= 40


def test_openapi_schema_generates():
    from saakshi.app import app
    schema = app.openapi()
    assert schema["info"]["title"] == "Saakshi"
    assert schema["openapi"].startswith("3.")
    assert any(p.startswith("/api/ledger") for p in schema["paths"])


def test_openapi_json_endpoint(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/ledger/verify" in r.json()["paths"]


@pytest.mark.parametrize("method,path", sorted(documented()))
def test_documented_endpoint_exists(method, path):
    assert (method, path) in app_routes(), f"API.md documents {method} {path} but the app has no such route"


def test_every_api_route_documented_or_allowlisted():
    routes = {r for r in app_routes() if r[1].startswith("/api/")}
    allow = {(m, _norm(p)) for m, p in UNDOCUMENTED_OK}
    undocumented = sorted(routes - documented() - allow)
    print("\nUndocumented /api routes:", undocumented or "none")
    assert not undocumented, f"routes missing from API.md (document them or allowlist with a reason): {undocumented}"


def test_allowlist_is_not_stale():
    routes = app_routes()
    stale = [k for k in UNDOCUMENTED_OK if (k[0], _norm(k[1])) not in routes and not k[1].startswith("/api/auth/")]
    assert not stale, f"allowlisted routes no longer exist: {stale}"
