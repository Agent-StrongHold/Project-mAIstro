"""Tests for maistro.security.auth_static — StaticKeyAuthProvider."""

from __future__ import annotations

import pytest

from maistro.security._types import SYSTEM_AUTH, IdentityKind
from maistro.security.auth_static import StaticKeyAuthProvider


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_valid_key_returns_system_auth(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        result = await provider.authenticate("Bearer secret")
        assert result is SYSTEM_AUTH

    @pytest.mark.asyncio
    async def test_missing_authorization_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        with pytest.raises(ValueError, match="Missing Authorization header"):
            await provider.authenticate(None)

    @pytest.mark.asyncio
    async def test_empty_authorization_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        with pytest.raises(ValueError, match="Missing Authorization header"):
            await provider.authenticate("")

    @pytest.mark.asyncio
    async def test_non_bearer_format_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        with pytest.raises(ValueError, match="Invalid authorization format"):
            await provider.authenticate("Basic secret")

    @pytest.mark.asyncio
    async def test_wrong_key_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        with pytest.raises(ValueError, match="Invalid API key"):
            await provider.authenticate("Bearer wrong")

    @pytest.mark.asyncio
    async def test_token_is_stripped_of_whitespace(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        result = await provider.authenticate("Bearer secret  ")
        assert result is SYSTEM_AUTH

    @pytest.mark.asyncio
    async def test_read_only_returns_limited_system_identity(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret", read_only=True)
        result = await provider.authenticate("Bearer secret")
        assert result.user_id == "system"
        assert result.username == "system"
        assert result.roles == frozenset({"user"})
        assert result.kind == IdentityKind.SYSTEM
        assert result.auth_method == "api_key"
        assert result is not SYSTEM_AUTH

    @pytest.mark.asyncio
    async def test_headers_argument_is_ignored(self) -> None:
        provider = StaticKeyAuthProvider(api_key="secret")
        result = await provider.authenticate("Bearer secret", headers={"x-foo": "bar"})
        assert result is SYSTEM_AUTH
