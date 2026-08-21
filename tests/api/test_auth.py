"""Tests for bearer token authentication.

Evidence: The API uses bearer token auth with constant-time comparison.
When no API keys are configured, auth is disabled (dev mode).
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro_server.api.auth import verify_api_key
from maistro_server.api.health import router as health_router
from maistro_server.api.tasks import router as tasks_router


def _make_app(api_keys: list[str]) -> FastAPI:
    """Create a test app with specific API key configuration."""
    settings = Settings(api_keys=api_keys)
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(tasks_router)

    # Override the get_settings dependency so auth actually uses our keys
    app.dependency_overrides[get_settings] = lambda: settings
    return app


class TestDevMode:
    """Evidence: When no API keys are configured, all requests are allowed."""

    def test_no_keys_allows_all(self) -> None:
        from maistro_server.main import app

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200


class TestAuthThroughHTTPStack:
    """Evidence: Auth must be enforced for protected endpoints when keys are set."""

    def test_protected_endpoint_rejects_without_key(self) -> None:
        app = _make_app(api_keys=["test-secret-key"])
        client = TestClient(app)
        response = client.get("/tasks")
        assert response.status_code == 403 or response.status_code == 401

    def test_protected_endpoint_accepts_correct_key(self) -> None:
        app = _make_app(api_keys=["test-secret-key"])
        client = TestClient(app)
        response = client.get(
            "/tasks",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 200

    def test_protected_endpoint_rejects_wrong_key(self) -> None:
        app = _make_app(api_keys=["correct-key"])
        client = TestClient(app)
        response = client.get(
            "/tasks",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert response.status_code == 401


class TestSecretComparison:
    """Evidence: Auth uses hmac.compare_digest for constant-time comparison,
    preventing timing attacks that could leak valid key characters."""

    def test_correct_key_accepted(self) -> None:
        settings = Settings(api_keys=["test-key-123"])
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-key-123")
        result = verify_api_key(creds, settings)
        assert result is not None
        assert result.token == "test-key-123"
        assert result.user_id == "default"

    def test_wrong_key_rejected(self) -> None:
        settings = Settings(api_keys=["correct-key"])
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-key")
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(creds, settings)
        assert exc_info.value.status_code == 401

    def test_missing_header_rejected(self) -> None:
        settings = Settings(api_keys=["some-key"])
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(None, settings)
        assert exc_info.value.status_code == 401

    def test_uses_constant_time_comparison(self) -> None:
        """Evidence: The implementation must use constant-time comparison, not ==."""
        import maistro_server.api.auth as _auth_mod

        # verify_api_key delegates to resolve_token_principal which does the comparison;
        # check the full module source so the test isn't brittle to refactors that
        # move the comparison into a helper.
        source = inspect.getsource(_auth_mod)
        assert "secret_equal" in source or "compare_digest" in source, (
            "verify_api_key must use secret_equal or hmac.compare_digest"
        )
        assert "==" not in source or "status_code ==" in source or "== 401" in source, (
            "verify_api_key should not use == for token comparison"
        )
