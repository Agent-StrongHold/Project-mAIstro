"""Coverage for DemoCookieAuthProvider: HS256 demo-JWT auth via header or cookie."""

from __future__ import annotations

import jwt as pyjwt
import pytest

from maistro.security._types import IdentityKind
from maistro.security.auth_demo_cookie import DemoCookieAuthProvider

_KEY = "x" * 32


def make_token(
    *,
    key: str = _KEY,
    sub: str = "u1",
    preferred_username: str = "alice",
    roles: list[str] | None = None,
    team_id: str = "",
    audience: str = "maistro",
    issuer: str = "maistro-demo",
) -> str:
    claims: dict[str, object] = {"sub": sub, "preferred_username": preferred_username}
    if roles is not None:
        claims["roles"] = roles
    if team_id:
        claims["team_id"] = team_id
    claims["aud"] = audience
    claims["iss"] = issuer
    return pyjwt.encode(claims, key, algorithm="HS256")


async def test_authenticate_via_authorization_header_prefix() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = make_token(roles=["admin", "user"], team_id="t1")
    ctx = await provider.authenticate(f"Bearer demo-jwt:{token}")
    assert ctx.user_id == "u1"
    assert ctx.username == "alice"
    assert ctx.roles == frozenset({"admin", "user"})
    assert ctx.team_id == "t1"
    assert ctx.kind == IdentityKind.USER
    assert ctx.auth_method == "demo_cookie"


async def test_authenticate_via_cookie_when_no_header_token() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = make_token(sub="u2")
    ctx = await provider.authenticate(None, headers={"cookie": f"maistro_session={token}"})
    assert ctx.user_id == "u2"


async def test_authenticate_prefers_header_token_over_cookie() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    header_token = make_token(sub="header-user")
    cookie_token = make_token(sub="cookie-user")
    ctx = await provider.authenticate(
        f"Bearer demo-jwt:{header_token}",
        headers={"cookie": f"maistro_session={cookie_token}"},
    )
    assert ctx.user_id == "header-user"


async def test_authenticate_uses_custom_cookie_name() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY, cookie_name="custom")
    token = make_token(sub="u3")
    ctx = await provider.authenticate(None, headers={"cookie": f"custom={token}"})
    assert ctx.user_id == "u3"


async def test_authenticate_raises_when_no_token_anywhere() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    with pytest.raises(ValueError, match="No demo session token"):
        await provider.authenticate(None, headers=None)


async def test_authenticate_raises_when_authorization_has_wrong_prefix() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    with pytest.raises(ValueError, match="No demo session token"):
        await provider.authenticate("Bearer plain-jwt", headers=None)


async def test_authenticate_raises_when_cookie_present_but_named_cookie_missing() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    with pytest.raises(ValueError, match="No demo session token"):
        await provider.authenticate(None, headers={"cookie": "other=abc"})


async def test_authenticate_swallows_cookie_parse_error_and_treats_as_no_token() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    with pytest.raises(ValueError, match="No demo session token"):
        await provider.authenticate(None, headers={"cookie": "====="})


async def test_authenticate_raises_for_invalid_signature() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = make_token(key="wrong-key-that-is-32-bytes-long!")
    with pytest.raises(ValueError, match="Invalid demo session"):
        await provider.authenticate(f"Bearer demo-jwt:{token}")


async def test_authenticate_raises_for_wrong_audience() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = make_token(audience="wrong-aud")
    with pytest.raises(ValueError, match="Invalid demo session"):
        await provider.authenticate(f"Bearer demo-jwt:{token}")


async def test_authenticate_raises_for_wrong_issuer() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = make_token(issuer="wrong-iss")
    with pytest.raises(ValueError, match="Invalid demo session"):
        await provider.authenticate(f"Bearer demo-jwt:{token}")


async def test_authenticate_defaults_roles_to_empty_frozenset_when_missing() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = make_token(roles=None)
    ctx = await provider.authenticate(f"Bearer demo-jwt:{token}")
    assert ctx.roles == frozenset()


async def test_authenticate_defaults_roles_to_empty_frozenset_when_not_a_list() -> None:
    provider = DemoCookieAuthProvider(api_key=_KEY)
    token = pyjwt.encode(
        {"sub": "u1", "roles": "not-a-list", "aud": "maistro", "iss": "maistro-demo"},
        _KEY,
        algorithm="HS256",
    )
    ctx = await provider.authenticate(f"Bearer demo-jwt:{token}")
    assert ctx.roles == frozenset()


async def test_short_api_key_logs_warning_but_still_constructs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="maistro.auth.demo_cookie"):
        provider = DemoCookieAuthProvider(api_key="short-key")
    assert any("minimum recommended" in r.message for r in caplog.records)
    assert provider._key == "short-key"
