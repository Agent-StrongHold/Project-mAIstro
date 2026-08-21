"""Coverage for CookieAuthProvider: HttpOnly session-cookie auth (BFF pattern)."""

from __future__ import annotations

import pytest

from maistro.security._types import AuthContext
from maistro.security.auth_cookie import CookieAuthProvider


class _StubJWTProvider:
    def __init__(self, ctx: AuthContext | None = None, error: Exception | None = None) -> None:
        self._ctx = ctx
        self._error = error
        self.calls: list[tuple[str | None, dict[str, str] | None]] = []

    async def authenticate(
        self, authorization: str | None, headers: dict[str, str] | None = None
    ) -> AuthContext:
        self.calls.append((authorization, headers))
        if self._error:
            raise self._error
        assert self._ctx is not None
        return self._ctx


def make_ctx(user_id: str = "u1") -> AuthContext:
    return AuthContext(user_id=user_id)


async def test_authenticate_raises_when_no_headers_provided() -> None:
    provider = CookieAuthProvider(jwt_provider=_StubJWTProvider())
    with pytest.raises(ValueError, match="No headers provided"):
        await provider.authenticate(None, headers=None)


async def test_authenticate_raises_when_headers_empty_dict() -> None:
    provider = CookieAuthProvider(jwt_provider=_StubJWTProvider())
    with pytest.raises(ValueError, match="No headers provided"):
        await provider.authenticate(None, headers={})


async def test_authenticate_raises_when_no_cookie_header() -> None:
    provider = CookieAuthProvider(jwt_provider=_StubJWTProvider())
    with pytest.raises(ValueError, match="No cookie header present"):
        await provider.authenticate(None, headers={"other": "value"})


async def test_authenticate_raises_when_named_cookie_missing() -> None:
    provider = CookieAuthProvider(jwt_provider=_StubJWTProvider())
    with pytest.raises(ValueError, match="Cookie 'maistro_session' not found"):
        await provider.authenticate(None, headers={"cookie": "other_cookie=abc"})


async def test_authenticate_uses_custom_cookie_name() -> None:
    provider = CookieAuthProvider(jwt_provider=_StubJWTProvider(), cookie_name="custom_session")
    with pytest.raises(ValueError, match="Cookie 'custom_session' not found"):
        await provider.authenticate(None, headers={"cookie": "maistro_session=abc"})


async def test_authenticate_extracts_token_and_delegates_to_jwt_provider() -> None:
    ctx = make_ctx("u42")
    jwt_provider = _StubJWTProvider(ctx=ctx)
    provider = CookieAuthProvider(jwt_provider=jwt_provider)
    result = await provider.authenticate(None, headers={"cookie": "maistro_session=my-jwt-token"})
    assert result is ctx
    assert jwt_provider.calls == [
        ("Bearer my-jwt-token", {"cookie": "maistro_session=my-jwt-token"})
    ]


async def test_authenticate_extracts_token_among_multiple_cookies() -> None:
    ctx = make_ctx()
    jwt_provider = _StubJWTProvider(ctx=ctx)
    provider = CookieAuthProvider(jwt_provider=jwt_provider)
    headers = {"cookie": "other=1; maistro_session=abc123; another=2"}
    await provider.authenticate(None, headers=headers)
    assert jwt_provider.calls[0][0] == "Bearer abc123"


async def test_authenticate_swallows_cookie_parse_error_and_treats_as_not_found() -> None:
    provider = CookieAuthProvider(jwt_provider=_StubJWTProvider())
    with pytest.raises(ValueError, match="Cookie 'maistro_session' not found"):
        await provider.authenticate(None, headers={"cookie": "====="})


async def test_authenticate_propagates_jwt_provider_errors() -> None:
    jwt_provider = _StubJWTProvider(error=RuntimeError("jwks fetch failed"))
    provider = CookieAuthProvider(jwt_provider=jwt_provider)
    with pytest.raises(RuntimeError, match="jwks fetch failed"):
        await provider.authenticate(None, headers={"cookie": "maistro_session=abc"})
