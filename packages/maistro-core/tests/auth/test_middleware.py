"""Coverage for maistro.auth.middleware: service-key extraction + scope enforcement."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from maistro.auth._types import Scope, ServiceIdentity
from maistro.auth.middleware import (
    extract_service_identity,
    require_any_scope,
    require_scope,
    setup_service_auth,
)
from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "headers": raw_headers,
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


def make_registry(
    name: str = "svc", key: str = "sk-svc-abc123", scopes: list[str] | None = None
) -> ServiceKeyRegistry:
    registry = ServiceKeyRegistry()
    registry.load_dict({name: {"key": key, "scopes": scopes or ["llm:chat_completions"]}})
    return registry


class TestSetupServiceAuth:
    def test_returns_configured_provider(self) -> None:
        registry = make_registry()
        provider = setup_service_auth(registry)
        assert isinstance(provider, ServiceKeyAuthProvider)

    def test_logs_registry_issues(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = ServiceKeyRegistry()
        registry.load_dict({"no-scopes-svc": {"key": "sk-svc-x"}})
        with caplog.at_level("WARNING", logger="maistro.auth.middleware"):
            setup_service_auth(registry)
        assert any("no-scopes-svc" in r.message for r in caplog.records)


class TestExtractServiceIdentity:
    async def test_returns_none_when_provider_is_none(self) -> None:
        request = make_request()
        result = await extract_service_identity(request, provider=None)
        assert result is None

    async def test_returns_identity_for_valid_key_and_sets_request_state(self) -> None:
        registry = make_registry()
        provider = ServiceKeyAuthProvider(registry)
        request = make_request({"x-service-key": "sk-svc-abc123"})
        result = await extract_service_identity(request, provider=provider)
        assert result is not None
        assert result.name == "svc"
        assert request.state.service_identity is result

    async def test_returns_none_when_no_service_key_present(self) -> None:
        registry = make_registry()
        provider = ServiceKeyAuthProvider(registry)
        request = make_request({})
        result = await extract_service_identity(request, provider=provider)
        assert result is None

    async def test_raises_401_for_invalid_x_service_key(self) -> None:
        registry = make_registry()
        provider = ServiceKeyAuthProvider(registry)
        request = make_request({"x-service-key": "sk-svc-wrong"})
        with pytest.raises(HTTPException) as exc_info:
            await extract_service_identity(request, provider=provider)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid service key"

    async def test_raises_401_for_invalid_bearer_service_key(self) -> None:
        registry = make_registry()
        provider = ServiceKeyAuthProvider(registry)
        request = make_request({"authorization": "Bearer sk-svc-wrong"})
        with pytest.raises(HTTPException) as exc_info:
            await extract_service_identity(request, provider=provider)
        assert exc_info.value.status_code == 401

    async def test_non_service_bearer_token_returns_none(self) -> None:
        registry = make_registry()
        provider = ServiceKeyAuthProvider(registry)
        request = make_request({"authorization": "Bearer regular-user-jwt"})
        result = await extract_service_identity(request, provider=provider)
        assert result is None

    async def test_valid_bearer_service_key_returns_identity(self) -> None:
        registry = make_registry()
        provider = ServiceKeyAuthProvider(registry)
        request = make_request({"authorization": "Bearer sk-svc-abc123"})
        result = await extract_service_identity(request, provider=provider)
        assert result is not None
        assert result.name == "svc"


class TestRequireScope:
    async def test_raises_403_when_no_identity_on_request_state(self) -> None:
        request = make_request()
        check = require_scope(Scope.CHAT_COMPLETIONS)
        with pytest.raises(HTTPException) as exc_info:
            await check(request)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Service authentication required"

    async def test_passes_when_identity_has_required_scope(self) -> None:
        request = make_request()
        identity = ServiceIdentity(name="svc", scopes=frozenset({Scope.CHAT_COMPLETIONS}))
        request.state.service_identity = identity
        check = require_scope(Scope.CHAT_COMPLETIONS)
        result = await check(request)
        assert result is identity

    async def test_raises_403_with_missing_scopes_when_one_scope_absent(self) -> None:
        request = make_request()
        identity = ServiceIdentity(name="svc", scopes=frozenset({Scope.CHAT_COMPLETIONS}))
        request.state.service_identity = identity
        check = require_scope(Scope.CHAT_COMPLETIONS, Scope.MEMORY_WRITE)
        with pytest.raises(HTTPException) as exc_info:
            await check(request)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Missing scopes: memory:write"

    async def test_requires_all_scopes_not_just_any(self) -> None:
        request = make_request()
        identity = ServiceIdentity(name="svc", scopes=frozenset({Scope.CHAT_COMPLETIONS}))
        request.state.service_identity = identity
        check = require_scope(Scope.MEMORY_WRITE, Scope.MEMORY_READ)
        with pytest.raises(HTTPException) as exc_info:
            await check(request)
        assert exc_info.value.detail == "Missing scopes: memory:write, memory:read"


class TestRequireAnyScope:
    async def test_raises_403_when_no_identity_on_request_state(self) -> None:
        request = make_request()
        check = require_any_scope(Scope.CHAT_COMPLETIONS)
        with pytest.raises(HTTPException) as exc_info:
            await check(request)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Service authentication required"

    async def test_passes_when_identity_has_at_least_one_scope(self) -> None:
        request = make_request()
        identity = ServiceIdentity(name="svc", scopes=frozenset({Scope.MEMORY_READ}))
        request.state.service_identity = identity
        check = require_any_scope(Scope.CHAT_COMPLETIONS, Scope.MEMORY_READ)
        result = await check(request)
        assert result is identity

    async def test_raises_403_when_identity_has_none_of_the_scopes(self) -> None:
        request = make_request()
        identity = ServiceIdentity(name="svc", scopes=frozenset({Scope.TASKS_READ}))
        request.state.service_identity = identity
        check = require_any_scope(Scope.CHAT_COMPLETIONS, Scope.MEMORY_READ)
        with pytest.raises(HTTPException) as exc_info:
            await check(request)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Requires one of: llm:chat_completions, memory:read"
