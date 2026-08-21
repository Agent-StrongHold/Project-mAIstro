"""Test fixtures for the Turing backend.

Resets the state singleton per test and provides authed_client / admin_client
(auto login) plus a turing_service_client (service-key headers).

Imports are package-relative. The flat `from state import ...` form this
replaced could not be fixed by sys.path ordering: packages/maistro-core/tests/
has no __init__.py but its `state/` and `config/` subdirectories do, so
collecting them binds top-level `state` and `config` in sys.modules — and an
already-imported name beats any path precedence. maistro-core is collected
first, so the names were always poisoned before this file ran, producing 26
setup errors in the full suite while every test here passed in isolation.
"""

from __future__ import annotations

import os

import pytest

# The dev-stub login accounts (routes/auth.py) are gated off by default so a
# real deployment has no universal known admin login; tests opt in explicitly.
os.environ["TURING_ALLOW_DEV_AUTH"] = "1"


@pytest.fixture(autouse=True)
def _reset_state():
    from ..state import reset_state

    reset_state()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from ..main import app

    return TestClient(app)


@pytest.fixture
def authed_client():
    from fastapi.testclient import TestClient

    from ..main import app

    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert r.status_code == 200
    return c


@pytest.fixture
def admin_client():
    from fastapi.testclient import TestClient

    from ..main import app

    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": "testadmin", "password": "adminpass"})
    assert r.status_code == 200
    return c


@pytest.fixture
def turing_service_client():
    """Client that sends the Turing-internal service key header."""
    from fastapi.testclient import TestClient

    from ..config import turing_service_key
    from ..main import app

    c = TestClient(app, headers={"X-Service-Key": turing_service_key()})
    return c
