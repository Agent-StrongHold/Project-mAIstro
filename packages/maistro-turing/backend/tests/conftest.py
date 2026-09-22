"""Test fixtures for the Turing backend.

Resets the state singleton per test and provides authed_client / admin_client
(auto login) plus a turing_service_client (service-key headers).

Imports use the explicit `maistro_turing_backend` namespace. The former
flat `state` and `config` names collided with similarly named test packages
when the full monorepo suite was collected, even though this suite passed in
isolation.
"""

from __future__ import annotations

import os

import pytest

# This suite drives the app over plain HTTP through Starlette's TestClient, so
# it is a local-development context in the sense #369 defines one: a `Secure`
# cookie is never sent back over `http://`, and every test that needs a
# logged-in session would fail with no session rather than a useful error.
#
# Declared here with the same flag a developer running the service locally
# sets, rather than weakening the production default to suit the tests — which
# is the arrangement #369 exists to undo. `test_session_cookie.py` asserts the
# production shape directly, without this environment.
os.environ.setdefault("TURING_ALLOW_INSECURE_TRANSPORT", "1")

# The dev-stub login accounts (routes/auth.py) are gated off by default so a
# real deployment has no universal known admin login; tests opt in explicitly.
os.environ["TURING_ALLOW_DEV_AUTH"] = "1"

# Production refuses to start without an explicitly configured service key. The
# suite supplies a test-only value rather than relying on a production fallback.
os.environ.setdefault("TURING_SERVICE_KEY", "test-turing-service-key")


@pytest.fixture(autouse=True)
def _reset_state():
    from maistro_turing_backend.execution import reset_execution_plane
    from maistro_turing_backend.state import reset_state

    reset_state()
    reset_execution_plane()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from maistro_turing_backend.main import app

    return TestClient(app)


@pytest.fixture
def authed_client():
    from fastapi.testclient import TestClient
    from maistro_turing_backend.main import app

    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert r.status_code == 200
    return c


@pytest.fixture
def admin_client():
    from fastapi.testclient import TestClient
    from maistro_turing_backend.main import app

    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": "testadmin", "password": "adminpass"})
    assert r.status_code == 200
    return c


@pytest.fixture
def turing_service_client():
    """Client that sends the Turing-internal service key header."""
    from fastapi.testclient import TestClient
    from maistro_turing_backend.config import turing_service_key
    from maistro_turing_backend.main import app

    c = TestClient(app, headers={"X-Service-Key": turing_service_key()})
    return c
