from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauthenticated_v1_rejected(client):
    r = client.get("/v1/state/snapshot")
    assert r.status_code == 401


def test_login_and_whoami(authed_client):
    r = authed_client.get("/v1/auth/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["role"] == "user"


def test_bad_credentials(client):
    r = client.post("/v1/auth/login", json={"username": "testuser", "password": "wrong"})
    assert r.status_code == 401


def test_service_key_authenticates(turing_service_client):
    # Service key is not a human session, so whoami reports unauthenticated user
    # but the request itself is not 401 (it carries a valid service identity).
    r = turing_service_client.get("/v1/auth/whoami")
    assert r.status_code == 200
    assert r.json()["authenticated"] is False


def test_authenticated_undeclared_v1_path_is_default_deny(authed_client):
    response = authed_client.get("/v1/undeclared-future-route")
    assert response.status_code == 403
    assert response.json()["detail"] == "Route authorization declaration required"


def test_authenticated_undeclared_non_versioned_path_is_default_deny(authed_client):
    response = authed_client.get("/future-admin-route")
    assert response.status_code == 403
    assert response.json()["detail"] == "Route authorization declaration required"


def test_service_scope_uses_canonical_route_permission(turing_service_client):
    response = turing_service_client.get("/v1/feed")
    assert response.status_code == 200


def test_service_without_route_scope_is_denied_by_live_middleware():
    """A valid service identity still needs the declaration's exact scope."""
    from maistro.auth import ServiceKeyRegistry

    from ..middleware.auth import TuringAuthMiddleware

    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            "chat-only": {
                "key": "chat-only-key",
                "scopes": ["turing:chat"],
            }
        }
    )
    app = FastAPI()
    app.add_middleware(TuringAuthMiddleware, registry=registry)

    @app.get("/v1/feed")
    def feed_fixture() -> dict[str, bool]:
        return {"reached": True}

    response = TestClient(app, headers={"X-Service-Key": "chat-only-key"}).get("/v1/feed")

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission 'turing.vault_read' required"


def test_service_suffix_lookalike_is_not_authorized_by_feed_declaration():
    """A matching-looking sibling must not inherit /v1/feed's permission."""
    from maistro.auth import ServiceKeyRegistry

    from ..middleware.auth import TuringAuthMiddleware

    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            "chat-only": {
                "key": "chat-only-key",
                "scopes": ["turing:chat"],
            }
        }
    )
    app = FastAPI()
    app.add_middleware(TuringAuthMiddleware, registry=registry)

    @app.get("/v1/feed-history")
    def feed_history_fixture() -> dict[str, bool]:
        return {"reached": True}

    response = TestClient(app, headers={"X-Service-Key": "chat-only-key"}).get("/v1/feed-history")

    assert response.status_code == 403
    assert response.json()["detail"] == "Route authorization declaration required"


def test_backend_startup_requires_service_key(monkeypatch):
    """An unset key must fail startup instead of enabling a public credential."""
    from ..config import build_registry
    from ..main import create_app

    monkeypatch.delenv("TURING_SERVICE_KEY", raising=False)
    build_registry.cache_clear()

    with pytest.raises(RuntimeError, match="TURING_SERVICE_KEY must be set"):
        create_app()
