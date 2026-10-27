import pytest


@pytest.fixture
def st(tmp_path, monkeypatch):
    """Fresh DB with the demo workers and keys (no history)."""
    from saakshi import app as _app  # noqa: F401  (registers module schemas)
    from saakshi import config, seed, state
    # Functional tests exercise behaviour, not access control (tests/test_security.py covers that).
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    s = state.reset(str(tmp_path / "test.db"))
    seed.seed_workers(s)
    yield s
    s.close()


@pytest.fixture
def client(st):
    from fastapi.testclient import TestClient

    from saakshi.app import app
    return TestClient(app)


@pytest.fixture
def auth_client(st, monkeypatch):
    """Client with authentication ON (the production default)."""
    from fastapi.testclient import TestClient

    from saakshi import config
    from saakshi.app import app
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    return TestClient(app)
