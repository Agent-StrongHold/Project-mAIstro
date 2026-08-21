"""Tests for maistro.security.auth_jwt — JWTAuthProvider (IdP-agnostic JWT auth)."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from maistro.security._types import IdentityKind
from maistro.security.auth_composite import AuthError, CredentialNotApplicable
from maistro.security.auth_jwt import JWTAuthProvider


def make_provider(**overrides: Any) -> JWTAuthProvider:
    kwargs: dict[str, Any] = {
        "jwks_url": "",
        "issuer": "https://idp.example.com",
        "audience": "maistro",
    }
    kwargs.update(overrides)
    return JWTAuthProvider(**kwargs)


class FakeLock:
    def __init__(self, locked: bool = False, on_enter: Any = None) -> None:
        self._locked = locked
        self.entered = False
        self._on_enter = on_enter

    def locked(self) -> bool:
        return self._locked

    async def __aenter__(self) -> FakeLock:
        self.entered = True
        if self._on_enter is not None:
            self._on_enter()
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_missing_header_raises_not_applicable(self) -> None:
        provider = make_provider()
        with pytest.raises(CredentialNotApplicable):
            await provider.authenticate(None)

    @pytest.mark.asyncio
    async def test_non_bearer_raises_not_applicable(self) -> None:
        provider = make_provider()
        with pytest.raises(CredentialNotApplicable):
            await provider.authenticate("Basic abc123")

    @pytest.mark.asyncio
    async def test_empty_token_raises_not_applicable(self) -> None:
        provider = make_provider()
        with pytest.raises(CredentialNotApplicable):
            await provider.authenticate("Bearer    ")

    @pytest.mark.asyncio
    async def test_success_uses_preferred_username(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {"sub": "u1", "preferred_username": "alice"}

        provider = make_provider(jwt_decode=decode)
        ctx = await provider.authenticate("Bearer tok")
        assert ctx.user_id == "u1"
        assert ctx.username == "alice"
        assert ctx.kind == IdentityKind.USER
        assert ctx.auth_method == "jwt"

    @pytest.mark.asyncio
    async def test_username_falls_back_to_name_then_sub(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {"sub": "u1", "name": "Alice Name"}

        provider = make_provider(jwt_decode=decode)
        ctx = await provider.authenticate("Bearer tok")
        assert ctx.username == "Alice Name"

        def decode2(_token: str) -> dict[str, Any]:
            return {"sub": "u2"}

        provider2 = make_provider(jwt_decode=decode2)
        ctx2 = await provider2.authenticate("Bearer tok")
        assert ctx2.username == "u2"

    @pytest.mark.asyncio
    async def test_extracts_roles_from_nested_claim(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {"sub": "u1", "realm_access": {"roles": ["admin", "user"]}}

        provider = make_provider(jwt_decode=decode)
        ctx = await provider.authenticate("Bearer tok")
        assert ctx.roles == frozenset({"admin", "user"})

    @pytest.mark.asyncio
    async def test_service_account_kind(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {"sub": "svc1", "kind": "service_account"}

        provider = make_provider(jwt_decode=decode)
        ctx = await provider.authenticate("Bearer tok")
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT

    @pytest.mark.asyncio
    async def test_interactive_agent_kind_and_on_behalf_of(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {"sub": "agent1", "kind": "interactive_agent", "on_behalf_of": "user42"}

        provider = make_provider(jwt_decode=decode)
        ctx = await provider.authenticate("Bearer tok")
        assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
        assert ctx.on_behalf_of == "user42"

    @pytest.mark.asyncio
    async def test_interactive_agent_without_on_behalf_of_defaults_empty(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {"sub": "agent1", "kind": "interactive_agent"}

        provider = make_provider(jwt_decode=decode)
        ctx = await provider.authenticate("Bearer tok")
        assert ctx.on_behalf_of == ""

    @pytest.mark.asyncio
    async def test_missing_sub_raises_auth_error(self) -> None:
        def decode(_token: str) -> dict[str, Any]:
            return {}

        provider = make_provider(jwt_decode=decode)
        with pytest.raises(AuthError, match="missing 'sub'"):
            await provider.authenticate("Bearer tok")


class TestDecodeToken:
    @pytest.mark.asyncio
    async def test_jwt_decode_seam_forbidden_with_jwks_url(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks", jwt_decode=lambda t: {})
        with pytest.raises(RuntimeError, match="forbidden"):
            await provider._decode_token("tok")

    @pytest.mark.asyncio
    async def test_jwt_decode_seam_used_without_jwks_url(self) -> None:
        provider = make_provider(jwt_decode=lambda t: {"sub": "x", "tok": t})
        result = await provider._decode_token("abc")
        assert result == {"sub": "x", "tok": "abc"}

    @pytest.mark.asyncio
    async def test_import_error_when_pyjwt_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "jwt", None)
        provider = make_provider(jwks_url="https://idp.example.com/jwks")
        with pytest.raises(ImportError, match="PyJWT"):
            await provider._decode_token("tok")

    @pytest.mark.asyncio
    async def test_decode_success_via_jwks_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")

        class FakeSigningKey:
            key = "the-key"

        class FakePyJWKClient:
            def __init__(self, url: str) -> None:
                self.url = url

            def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
                return FakeSigningKey()

        fake_jwt = ModuleType("jwt")
        fake_jwt.decode = lambda token, key, algorithms, issuer, audience: {  # type: ignore[attr-defined]
            "sub": "u1",
            "key_used": key,
        }
        fake_jwt.PyJWKClient = FakePyJWKClient  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "jwt", fake_jwt)

        result = await provider._decode_token("abc.def.ghi")
        assert result == {"sub": "u1", "key_used": "the-key"}

    @pytest.mark.asyncio
    async def test_decode_failure_wraps_in_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")

        class FakePyJWKClient:
            def __init__(self, url: str) -> None:
                pass

            def get_signing_key_from_jwt(self, token: str) -> Any:
                raise ValueError("bad sig")

        fake_jwt = ModuleType("jwt")
        fake_jwt.decode = lambda *a, **k: {}  # type: ignore[attr-defined]
        fake_jwt.PyJWKClient = FakePyJWKClient  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "jwt", fake_jwt)

        with pytest.raises(AuthError, match="JWT validation failed"):
            await provider._decode_token("abc.def.ghi")


class TestGetJwksClient:
    @pytest.mark.asyncio
    async def test_returns_fresh_cache_without_lock(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")
        provider._jwks_cache = "cached-client"
        provider._jwks_cache_at = __import__("time").monotonic()
        result = await provider._get_jwks_client(None, object)
        assert result == "cached-client"

    @pytest.mark.asyncio
    async def test_lock_locked_with_existing_cache_returns_stale(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")
        provider._jwks_cache = "stale-client"
        provider._jwks_cache_at = 0.0
        provider._jwks_cache_ttl = 0
        provider._cache_lock = FakeLock(locked=True)  # type: ignore[assignment]
        result = await provider._get_jwks_client(None, object)
        assert result == "stale-client"

    @pytest.mark.asyncio
    async def test_lock_locked_no_cache_constructs_client(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")
        provider._cache_lock = FakeLock(locked=True)  # type: ignore[assignment]

        class FakeClient:
            def __init__(self, url: str) -> None:
                self.url = url

        result = await provider._get_jwks_client(None, FakeClient)
        assert isinstance(result, FakeClient)
        assert result.url == "https://idp.example.com/jwks"

    @pytest.mark.asyncio
    async def test_refreshes_and_caches_client(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")

        class FakeClient:
            def __init__(self, url: str) -> None:
                self.url = url

        result = await provider._get_jwks_client(None, FakeClient)
        assert isinstance(result, FakeClient)
        assert provider._jwks_cache is result

    @pytest.mark.asyncio
    async def test_double_check_inside_lock_returns_cache_if_still_fresh(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")
        provider._jwks_cache = "fresh-inside-lock"
        provider._jwks_cache_at = __import__("time").monotonic()

        class ShouldNotBeCalled:
            def __init__(self, url: str) -> None:
                raise AssertionError("should not construct a new client")

        result = await provider._get_jwks_client(None, ShouldNotBeCalled)
        assert result == "fresh-inside-lock"

    @pytest.mark.asyncio
    async def test_lock_acquired_finds_concurrently_refreshed_cache(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")

        def fill_cache() -> None:
            provider._jwks_cache = "concurrently-filled"
            provider._jwks_cache_at = __import__("time").monotonic()

        provider._cache_lock = FakeLock(locked=False, on_enter=fill_cache)  # type: ignore[assignment]

        class ShouldNotBeCalled:
            def __init__(self, url: str) -> None:
                raise AssertionError("should not construct a new client")

        result = await provider._get_jwks_client(None, ShouldNotBeCalled)
        assert result == "concurrently-filled"

    @pytest.mark.asyncio
    async def test_refresh_failure_serves_stale_within_bound(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks", jwks_cache_ttl=10)
        provider._jwks_cache = "old-client"
        provider._jwks_cache_at = __import__("time").monotonic() - 20  # stale but within 5x TTL

        class FailingClient:
            def __init__(self, url: str) -> None:
                raise RuntimeError("jwks endpoint down")

        result = await provider._get_jwks_client(None, FailingClient)
        assert result == "old-client"

    @pytest.mark.asyncio
    async def test_refresh_failure_with_no_cache_raises(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks")

        class FailingClient:
            def __init__(self, url: str) -> None:
                raise RuntimeError("jwks endpoint down")

        with pytest.raises(RuntimeError, match="jwks endpoint down"):
            await provider._get_jwks_client(None, FailingClient)

    @pytest.mark.asyncio
    async def test_refresh_failure_beyond_max_stale_raises(self) -> None:
        provider = make_provider(jwks_url="https://idp.example.com/jwks", jwks_cache_ttl=1)
        provider._jwks_cache = "ancient-client"
        provider._jwks_cache_at = __import__("time").monotonic() - 100  # way beyond 5x TTL=5s

        class FailingClient:
            def __init__(self, url: str) -> None:
                raise RuntimeError("jwks endpoint down")

        with pytest.raises(RuntimeError, match="jwks endpoint down"):
            await provider._get_jwks_client(None, FailingClient)


class TestExtractRoles:
    def test_list_value_returns_str_list(self) -> None:
        provider = make_provider()
        roles = provider._extract_roles({"realm_access": {"roles": ["a", "b"]}})
        assert roles == ["a", "b"]

    def test_string_value_returns_single_item_list(self) -> None:
        provider = make_provider(role_claim="role")
        roles = provider._extract_roles({"role": "admin"})
        assert roles == ["admin"]

    def test_missing_or_other_type_returns_empty_list(self) -> None:
        provider = make_provider(role_claim="role")
        assert provider._extract_roles({}) == []
        assert provider._extract_roles({"role": 123}) == []


class TestExtractNested:
    def test_empty_path_returns_none(self) -> None:
        assert JWTAuthProvider._extract_nested({"a": 1}, "") is None

    def test_no_dot_does_flat_lookup(self) -> None:
        assert JWTAuthProvider._extract_nested({"kind": "user"}, "kind") == "user"

    def test_dotted_path_traverses_nested_dicts(self) -> None:
        claims = {"realm_access": {"roles": ["x"]}}
        assert JWTAuthProvider._extract_nested(claims, "realm_access.roles") == ["x"]

    def test_dotted_path_returns_none_when_intermediate_not_dict(self) -> None:
        claims = {"realm_access": "not-a-dict"}
        assert JWTAuthProvider._extract_nested(claims, "realm_access.roles") is None

    def test_dotted_path_returns_none_when_missing(self) -> None:
        assert JWTAuthProvider._extract_nested({}, "a.b.c") is None
