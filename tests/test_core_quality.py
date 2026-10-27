"""Core robustness: health probe, JSON 500s with a request id, landing page headers, event constants."""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_healthz_is_public_and_counts_events(auth_client, st):
    st.ledger.append("punch.in", {"device": "bio-gate-1"}, worker_id="W001")
    r = auth_client.get("/api/healthz")  # no Authorization header
    assert r.status_code == 200
    assert r.json() == {"ok": True, "events": st.ledger.count(), "ledger_ok": True}
    assert r.headers["Cache-Control"] == "no-store"


def test_healthz_reports_a_broken_ledger(auth_client, st):
    st.ledger.append("punch.out", {"device": "bio-gate-1"}, worker_id="W001")
    st.conn.execute("UPDATE events SET ts='2026-10-27T18:00:00+05:30' WHERE seq=1")
    body = auth_client.get("/api/healthz").json()
    assert body["ok"] is True and body["ledger_ok"] is False and body["events"] == 1


def test_healthz_is_in_the_public_policy():
    from saakshi import auth
    roles, _ = auth.match("GET", "/healthz")
    assert roles == auth.PUBLIC


def test_unhandled_exception_returns_json_500_with_request_id(st, monkeypatch, caplog):
    from saakshi.app import app

    def boom() -> int:
        raise RuntimeError("secret internals: /var/db/saakshi.db")

    monkeypatch.setattr(st.ledger, "count", boom)
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="saakshi.errors"):
        r = client.get("/api/site")
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error" and len(body["request_id"]) >= 8
    assert set(body) == {"error", "request_id"}
    assert r.headers["X-Request-ID"] == body["request_id"]
    assert "Traceback" not in r.text and "secret internals" not in r.text
    record = next(rec for rec in caplog.records if rec.name == "saakshi.errors")
    assert body["request_id"] in record.getMessage() and record.exc_info is not None


@pytest.mark.parametrize("supplied,reused", [("req-12345678", True), ("bad id\nINJECT", False), ("short", False)])
def test_request_id_header_reused_only_when_safe(supplied, reused):
    from saakshi import errors
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def _boom() -> None:
        raise ValueError("nope")

    r = TestClient(app, raise_server_exceptions=False).get("/boom", headers={"X-Request-ID": supplied})
    assert r.status_code == 500
    assert (r.json()["request_id"] == supplied) is reused


def test_http_errors_keep_their_own_shape(client):
    r = client.get("/api/workers/W999")
    assert r.status_code == 404 and r.json() == {"detail": "unknown worker W999"}


def _assert_secure_html(r):
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"


def test_landing_page_is_html_with_csp(client):
    r = client.get("/")
    _assert_secure_html(r)
    assert "<html" in r.text.lower()


def test_landing_page_assets_are_served(client):
    from saakshi import config
    for path in ("/landing/landing.css", "/landing/landing.js"):
        if (config.WEB / path.lstrip("/")).is_file():
            r = client.get(path)
            assert r.status_code == 200 and "Content-Security-Policy" in r.headers, path


def test_landing_page_serves_web_index_when_present(client, tmp_path, monkeypatch):
    from saakshi import app as app_module
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><html><title>From file</title></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "INDEX_HTML", page)
    r = client.get("/")
    _assert_secure_html(r)
    assert "From file" in r.text


def test_landing_page_falls_back_to_builtin(client, tmp_path, monkeypatch):
    from saakshi import app as app_module
    monkeypatch.setattr(app_module, "INDEX_HTML", tmp_path / "missing.html")
    r = client.get("/")
    _assert_secure_html(r)
    assert r.text == app_module.FALLBACK_INDEX


def _event_constants() -> dict[str, object]:
    from saakshi import events
    return {k: v for k, v in vars(events).items() if k.isupper() and k != "ALL"}


def test_event_constants_are_unique_non_empty_strings():
    consts = _event_constants()
    assert len(consts) >= 17
    for name, value in consts.items():
        assert isinstance(value, str) and value, name
        assert value == value.strip().lower() and "." in value, name
    assert len(set(consts.values())) == len(consts), "two constants share one event type"


def test_event_all_matches_constants():
    from saakshi import events
    assert set(_event_constants().values()) == events.ALL


def test_core_receipt_templates_use_known_event_types():
    from saakshi import events, i18n
    for t in (events.PUNCH_IN, events.PUNCH_OUT, events.PUNCH_CORRECTION, events.ACCESS_LOOKUP):
        assert i18n.has(t)
