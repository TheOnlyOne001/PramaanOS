"""Access control: deny by default, 401 vs 403, worker-self rules, anonymous relay, token integrity."""
import base64
import json

import pytest

from saakshi import auth, config

DAY = config.DEMO_DAY


def login(c, role, wid=None):
    r = c.post("/api/auth/demo-login", json={"role": role, "worker_id": wid})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_deny_by_default_and_401_vs_403(auth_client):
    c = auth_client
    assert c.get("/api/console/overview").status_code == 401
    assert c.get("/api/console/overview").headers.get("www-authenticate") == "Bearer"
    assert c.get("/api/no-such-route").status_code == 401           # unknown /api path: denied
    w = login(c, "worker", "W001")
    assert c.get("/api/console/overview", headers=w).status_code == 403  # authenticated, wrong role
    assert c.post("/api/pay/run", headers=login(c, "supervisor")).status_code == 403
    assert c.get("/api/console/overview", headers=login(c, "supervisor")).status_code == 200


def test_public_routes_need_no_token(auth_client):
    for path in ("/api/site", "/api/rules", "/api/voice/topics", "/api/passport/issuers", "/"):
        assert auth_client.get(path).status_code == 200, path


def test_worker_cannot_read_another_workers_records(auth_client):
    c = auth_client
    meena = login(c, "worker", "W001")
    assert c.get("/api/pay/W001/payslip", headers=meena).status_code == 200
    assert c.get("/api/pay/W002/payslip", headers=meena).status_code == 403
    assert c.get("/api/workers/W001/receipts", headers=meena).status_code == 200
    assert c.get("/api/workers/W002/receipts", headers=meena).status_code == 403
    assert c.get("/api/workers/W002/access-log", headers=meena).status_code == 403
    assert c.get("/api/ot/requests?worker_id=W002", headers=meena).status_code == 403
    # A supervisor cannot read receipts meant for the worker and her auditor.
    assert c.get("/api/workers/W001/receipts", headers=login(c, "supervisor")).status_code == 403


def test_worker_cannot_accept_someone_elses_overtime(auth_client):
    c = auth_client
    sup = login(c, "supervisor")
    r = c.post("/api/ot/requests", headers=sup, json={"worker_ids": ["W001", "W002"], "date": DAY, "hours": 2,
                                                       "reason": "export order", "requested_by": "S001"})
    assert r.status_code == 200, r.text
    reqs = {x["worker_id"]: x["request_id"] for x in r.json()["requests"]}
    meena, ravi = login(c, "worker", "W001"), login(c, "worker", "W002")
    body = {"decision": "accept", "channel": "tap"}
    assert c.post(f"/api/ot/requests/{reqs['W002']}/consent", headers=meena, json=body).status_code == 403
    assert c.post(f"/api/ot/requests/{reqs['W001']}/consent", headers=sup, json=body).status_code == 403
    assert c.post(f"/api/ot/requests/{reqs['W002']}/consent", headers=ravi, json=body).status_code not in (401, 403)
    # Workers cannot create overtime requests.
    assert c.post("/api/ot/requests", headers=meena, json={"worker_ids": ["W001"], "date": DAY, "hours": 2,
                                                           "reason": "x", "requested_by": "S001"}).status_code == 403


def test_voice_issue_only_for_own_worker_id(auth_client):
    c = auth_client
    meena = login(c, "worker", "W001")
    r = c.post("/api/voice/issue", headers=meena, json={"worker_id": "W002", "blinded": {}})
    assert r.status_code == 403
    assert c.post("/api/voice/issue", json={"worker_id": "W001", "blinded": {}}).status_code == 401


def test_relay_needs_no_token_and_strips_identity(auth_client):
    tok = login(auth_client, "worker", "W001")
    body = {"topic": "water", "month": DAY[:7], "token": "00", "sig": "00", "text": "hi"}
    assert auth_client.post("/api/relay/voice/reports", json=body).status_code not in (401, 403)
    # Even if a phone sends its sign-in token or a cookie, the relay handler never receives them.
    seen = {}

    async def inner(scope, receive, send):
        seen.update(dict(scope["headers"]))
    import asyncio
    mw = auth.AuthMiddleware(inner)
    scope = {"type": "http", "method": "POST", "path": "/api/relay/voice/reports", "query_string": b"",
             "headers": [(b"authorization", tok["Authorization"].encode()), (b"cookie", b"sid=1"),
                         (b"content-type", b"application/json")]}
    asyncio.run(mw(scope, None, None))
    assert b"authorization" not in seen and b"cookie" not in seen and b"content-type" in seen
    # The relay's tables hold no worker id.
    from saakshi import state
    st = state.get()
    for (name,) in st.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%report%'"):
        cols = [r[1] for r in st.conn.execute(f"PRAGMA table_info({name})")]
        assert "worker_id" not in cols, name


def test_demo_login_disabled_outside_demo_mode(auth_client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert auth_client.post("/api/auth/demo-login", json={"role": "hr"}).status_code == 404


def test_demo_login_validates_role_and_worker(auth_client):
    assert auth_client.post("/api/auth/demo-login", json={"role": "root"}).status_code == 422
    assert auth_client.post("/api/auth/demo-login", json={"role": "worker", "worker_id": "W999"}).status_code == 404


def test_tampered_and_expired_tokens_rejected(auth_client):
    c = auth_client
    good = login(c, "worker", "W001")["Authorization"].split(" ")[1]
    body, sig = good.split(".")
    p = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    p["role"] = "hr"
    forged = base64.urlsafe_b64encode(json.dumps(p).encode()).rstrip(b"=").decode() + "." + sig
    assert c.get("/api/pay/fairness", headers={"Authorization": "Bearer " + forged}).status_code == 401
    expired = auth.issue_token("hr", ttl=-1)
    assert c.get("/api/pay/fairness", headers={"Authorization": "Bearer " + expired}).status_code == 401
    assert c.get("/api/pay/fairness", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert c.get("/api/pay/fairness", headers={"Authorization": "Bearer " + auth.issue_token("hr")}).status_code == 200


def test_security_headers_present(auth_client):
    for path in ("/api/site", "/api/console/overview", "/worker/"):
        r = auth_client.get(path)
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
    assert auth_client.get("/api/site").headers["cache-control"] == "no-store"


def test_lookup_viewer_comes_from_token(auth_client):
    c = auth_client
    sup = login(c, "supervisor")
    r = c.post("/api/workers/W001/lookup", headers=sup,
               json={"viewer": "Someone Else", "viewer_role": "auditor", "reason": "wage query"})
    assert r.status_code == 200, r.text
    assert r.json()["access"]["viewer"] == "S001"
    log = c.get("/api/workers/W001/access-log", headers=login(c, "worker", "W001")).json()
    assert log[0]["viewer"] == "S001"
    assert c.post("/api/workers/W001/lookup", headers=login(c, "worker", "W002"),
                  json={"viewer": "x", "reason": "nosy"}).status_code == 403


@pytest.mark.parametrize("role", ["supervisor", "hr", "auditor", "worker"])
def test_every_role_can_verify_the_chain(auth_client, role):
    h = login(auth_client, role, "W001" if role == "worker" else None)
    assert auth_client.get("/api/ledger/verify", headers=h).status_code == 200
