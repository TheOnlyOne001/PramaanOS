import pytest


@pytest.fixture
def st(tmp_path):
    """Fresh DB with the demo workers and keys (no history)."""
    from saakshi import app as _app  # noqa: F401  (registers module schemas)
    from saakshi import seed, state
    s = state.reset(str(tmp_path / "test.db"))
    seed.seed_workers(s)
    yield s
    s.close()


@pytest.fixture
def client(st):
    from fastapi.testclient import TestClient
    from saakshi.app import app
    return TestClient(app)
