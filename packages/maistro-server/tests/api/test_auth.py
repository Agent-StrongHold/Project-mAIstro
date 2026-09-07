"""Tests for bearer token authentication.

Evidence: The API uses bearer token auth with constant-time comparison.
When no API keys are configured, auth is disabled (dev mode).

#843: every accepted key must resolve to one explicit canonical principal.
Plain secret-only keys (the legacy form that invented user ``default``) are
rejected — at startup, and fail-closed at resolve time even if the startup
gate is bypassed.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro_server.api.auth import (
    invalid_api_key_entries,
    resolve_token_principal,
    verify_api_key,
)
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
        app = _make_app(api_keys=["ops:test-secret-key"])
        client = TestClient(app)
        response = client.get("/tasks")
        assert response.status_code == 403 or response.status_code == 401

    def test_protected_endpoint_accepts_correct_key(self) -> None:
        app = _make_app(api_keys=["ops:test-secret-key"])
        client = TestClient(app)
        response = client.get(
            "/tasks",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 200

    def test_protected_endpoint_rejects_wrong_key(self) -> None:
        app = _make_app(api_keys=["ops:correct-key"])
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
        settings = Settings(api_keys=["ops:test-key-123"])
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-key-123")
        result = verify_api_key(creds, settings)
        # verify_api_key returns an AuthenticatedPrincipal (not the raw key).
        assert result is not None
        assert result.token == "test-key-123"

    def test_wrong_key_rejected(self) -> None:
        settings = Settings(api_keys=["ops:correct-key"])
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-key")
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(creds, settings)
        assert exc_info.value.status_code == 401

    def test_missing_header_rejected(self) -> None:
        settings = Settings(api_keys=["ops:some-key"])
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(None, settings)
        assert exc_info.value.status_code == 401

    def test_uses_constant_time_comparison(self) -> None:
        """Evidence: token comparison must be constant-time, not ==.
        The comparison lives in resolve_token_principal (verify_api_key delegates
        to it), so inspect that function's source."""
        source = inspect.getsource(resolve_token_principal)
        assert "secret_equal" in source or "compare_digest" in source, (
            "resolve_token_principal must use secret_equal or hmac.compare_digest"
        )
        assert "token ==" not in source and "== token" not in source, (
            "resolve_token_principal must not use == for token comparison"
        )


class TestExplicitPrincipalContract:
    """#843: every accepted long-lived API key resolves to one explicit
    stable canonical principal; the parser never invents ``default``."""

    def test_legacy_plain_key_never_authenticates(self) -> None:
        """The exact secret material of a legacy plain key must resolve to
        nothing — fail closed, not to an invented ``default`` user."""
        settings = Settings(api_keys=["legacy-plain-secret"])
        assert resolve_token_principal("legacy-plain-secret", settings) is None

    def test_legacy_plain_key_rejected_over_http(self) -> None:
        app = _make_app(api_keys=["legacy-plain-secret"])
        client = TestClient(app)
        response = client.get(
            "/tasks",
            headers={"Authorization": "Bearer legacy-plain-secret"},
        )
        assert response.status_code == 401

    def test_migration_prefix_preserves_access(self) -> None:
        """The #843 migration: rewrite ``<secret>`` as ``principal:<secret>``.
        The same bare secret keeps authenticating — clients never change —
        but now it is attributed to the named principal."""
        settings = Settings(api_keys=["ops:same-secret"])
        principal = resolve_token_principal("same-secret", settings)
        assert principal is not None
        assert principal.user_id == "ops"

    def test_full_configured_entry_also_authenticates(self) -> None:
        """The whole ``principal:secret`` pair remains a valid bearer (the
        pre-#843 alias), still resolving to the explicit principal."""
        settings = Settings(api_keys=["ops:same-secret"])
        principal = resolve_token_principal("ops:same-secret", settings)
        assert principal is not None
        assert principal.user_id == "ops"

    def test_rotation_two_keys_one_principal(self) -> None:
        """Rotation overlap: two secrets may intentionally serve one
        principal — the relationship is explicit, durable configuration."""
        settings = Settings(api_keys=["alice:key-one", "alice:key-two"])
        first = resolve_token_principal("key-one", settings)
        second = resolve_token_principal("key-two", settings)
        assert first is not None and second is not None
        assert first.user_id == "alice"
        assert second.user_id == "alice"

    def test_two_principals_never_collapse(self) -> None:
        """Different principals cannot authenticate through keys that
        collapse onto the same user id."""
        settings = Settings(api_keys=["alice:secret-a", "bob:secret-b"])
        for secret, expected in (("secret-a", "alice"), ("secret-b", "bob")):
            principal = resolve_token_principal(secret, settings)
            assert principal is not None
            assert principal.user_id == expected

    def test_admin_role_form(self) -> None:
        """``principal:admin:secret`` grants the admin role (the old parser's
        ``:admin`` branch was unreachable; it is live under #843's parser)."""
        settings = Settings(api_keys=["alice:admin:s3cr3t"])
        principal = resolve_token_principal("s3cr3t", settings)
        assert principal is not None
        assert principal.user_id == "alice"
        assert principal.is_admin

    def test_malformed_entries_fail_closed(self) -> None:
        """Empty entries, a missing principal, a missing secret, and
        ``sk-``-prefixed (secret-shaped) keys must not authenticate."""
        settings = Settings(api_keys=["", "   ", ":secret", "alice:", "sk-plain"])
        for attempt in ("", "secret", "alice:", "sk-plain", ":secret"):
            assert resolve_token_principal(attempt, settings) is None

    def test_revoked_key_no_longer_authenticates(self) -> None:
        """Revocation is removing the entry: the secret that once resolved
        to alice must resolve to nothing once her entry is gone."""
        before = resolve_token_principal("old-secret", Settings(api_keys=["alice:old-secret"]))
        assert before is not None
        after = resolve_token_principal("old-secret", Settings(api_keys=["alice:new-secret"]))
        assert after is None

    def test_secret_material_is_not_the_principal_id(self) -> None:
        settings = Settings(api_keys=["ops:secret-material-xyz"])
        principal = resolve_token_principal("secret-material-xyz", settings)
        assert principal is not None
        assert principal.user_id == "ops"
        assert principal.user_id != principal.token
        assert "secret-material-xyz" not in principal.user_id

    def test_colon_containing_secret_keeps_working(self) -> None:
        """First-colon split: everything after the principal is the secret,
        so secrets containing colons are unchanged by the new contract."""
        settings = Settings(api_keys=["ops:weird:secret"])
        assert resolve_token_principal("weird:secret", settings) is not None


class TestInvalidEntryDescriptions:
    """The startup gate's evidence: which entries are bad and why, without
    ever echoing key material."""

    def test_valid_configuration_yields_no_problems(self) -> None:
        settings = Settings(api_keys=["ops:secret-a", "alice:admin:secret-b", "bob:weird:secret"])
        assert invalid_api_key_entries(settings) == []

    def test_plain_and_malformed_entries_are_described(self) -> None:
        settings = Settings(api_keys=["plain-secret", "sk-shaped", ":no-user", "bob:", " "])
        problems = invalid_api_key_entries(settings)
        assert len(problems) == 5
        assert "plain secret-only key" in problems[0]
        assert "no principal prefix" in problems[1]
        assert "missing principal" in problems[2]
        assert "missing secret" in problems[3]
        assert "empty" in problems[4]

    def test_descriptions_never_echo_key_material(self) -> None:
        secret = "super-secret-material-9f2c"
        settings = Settings(api_keys=[secret])
        for problem in invalid_api_key_entries(settings):
            assert secret not in problem
