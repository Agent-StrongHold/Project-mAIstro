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


def test_public_family_admits_only_the_methods_the_registry_declares(client):
    """POST /docs is inside the middleware's public prefix table but outside
    the registry's GET declaration, so it is refused rather than served."""
    r = client.post("/docs")
    assert r.status_code == 403
    assert r.json()["detail"] == "Route authorization declaration required"


def _turing_middleware_from(app: FastAPI) -> object:
    """Find the live TuringAuthMiddleware instance inside the built stack."""
    from ..middleware.auth import TuringAuthMiddleware

    layer = app.middleware_stack
    while layer is not None:
        if isinstance(layer, TuringAuthMiddleware):
            return layer
        layer = getattr(layer, "app", None)
    raise AssertionError("TuringAuthMiddleware is not part of the built stack")


def test_a_registry_non_public_entry_on_a_public_table_path_is_refused():
    """The hardcoded public tables cannot outrank the reviewed registry: a
    path the registry classifies exempt is refused instead of served."""
    from maistro.auth import ServiceKeyRegistry

    from ..middleware.auth import TuringAuthMiddleware

    registry = ServiceKeyRegistry()
    registry.load_dict({"svc": {"key": "svc-key", "scopes": ["turing:chat"]}})
    app = FastAPI()
    app.add_middleware(TuringAuthMiddleware, registry=registry)

    @app.get("/health")
    def health_fixture() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    middleware = _turing_middleware_from(app)
    declared_exempt = (
        {
            "methods": ["GET"],
            "path": "/health",
            "kind": "exact",
            "access": "exempt",
            "owner": "@test",
            "reason": "fixture",
            "expires": "2027-01-31",
        },
    )
    object.__setattr__(middleware, "_route_policy", declared_exempt)

    response = client.get("/health")

    assert response.status_code == 403
    assert response.json()["detail"] == "Route authorization declaration required"


def test_a_permission_entry_missing_its_permission_name_denies():
    """A malformed table entry cannot mean allow: a permission declaration
    without a usable permission name is default-deny, not a crash or a pass."""
    from maistro.auth import ServiceKeyRegistry

    from ..middleware.auth import TuringAuthMiddleware

    registry = ServiceKeyRegistry()
    registry.load_dict({"svc": {"key": "svc-key", "scopes": ["turing:chat"]}})
    app = FastAPI()
    app.add_middleware(TuringAuthMiddleware, registry=registry)

    @app.get("/v1/malformed")
    def malformed_fixture() -> dict[str, bool]:
        return {"reached": True}

    client = TestClient(app)
    assert client.get("/v1/malformed").status_code == 401
    middleware = _turing_middleware_from(app)
    malformed = (
        {
            "methods": ["GET"],
            "path": "/v1/malformed",
            "kind": "exact",
            "access": "permission",
        },
    )
    object.__setattr__(middleware, "_route_policy", malformed)

    response = client.get("/v1/malformed", headers={"X-Service-Key": "svc-key"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission 'None' required"


def test_permission_and_principal_checks_deny_without_a_principal():
    """An absent permission mapping or an absent principal can never mean
    allow: the decision helpers deny when there is nothing to authorize."""
    from starlette.requests import Request

    from ..middleware.auth import TuringAuthMiddleware

    middleware = TuringAuthMiddleware(app=FastAPI(), registry=ServiceKeyRegistryStub())
    request = Request({"type": "http", "state": {}})

    assert middleware._has_permission("turing.chat", request) is False
    assert middleware._has_permission(None, request) is False
    assert TuringAuthMiddleware._principal(request) is None


class ServiceKeyRegistryStub:
    """Minimal registry stand-in; no key is ever presented to it."""

    def load_dict(self, _entries: dict) -> None:
        return None


def test_backend_startup_requires_service_key(monkeypatch):
    """An unset key must fail startup instead of enabling a public credential."""
    from ..config import build_registry
    from ..main import create_app

    monkeypatch.delenv("TURING_SERVICE_KEY", raising=False)
    build_registry.cache_clear()

    with pytest.raises(RuntimeError, match="TURING_SERVICE_KEY must be set"):
        create_app()
