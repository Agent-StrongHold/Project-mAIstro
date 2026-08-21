"""I27: Cookie Auth Provider — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.security._types import AuthContext
from maistro.security.auth_cookie import CookieAuthProvider


class MockJWTProvider:
    async def authenticate(self, authorization, headers=None):
        if not authorization or not authorization.startswith("Bearer "):
            raise ValueError("bad")
        token = authorization.removeprefix("Bearer ")
        if not token:
            raise ValueError("bad")
        return AuthContext(user_id="cookie_user")


def _make_cookie_provider(cookie_name="maistro_session"):
    return CookieAuthProvider(jwt_provider=MockJWTProvider(), cookie_name=cookie_name)


_ASCII = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class CookieAuthMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.provider = _make_cookie_provider()

    @rule(
        token_value=st.text(min_size=1, max_size=30, alphabet=st.sampled_from(_ASCII)),
    )
    def try_valid_cookie(self, token_value):
        headers = {"cookie": f"maistro_session={token_value}"}
        ctx = asyncio.run(self.provider.authenticate(None, headers=headers))
        assert ctx.user_id == "cookie_user"

    @rule(
        extra_cookies=st.text(min_size=0, max_size=20, alphabet=st.sampled_from(_ASCII)),
    )
    def try_multiple_cookies(self, extra_cookies):
        headers = {"cookie": f"other=abc; maistro_session=jwttoken; sid={extra_cookies}"}
        ctx = asyncio.run(self.provider.authenticate(None, headers=headers))
        assert ctx.user_id == "cookie_user"

    @invariant()
    def no_headers_raises(self):
        try:
            asyncio.run(self.provider.authenticate(None))
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass

    @invariant()
    def empty_cookie_header_raises(self):
        try:
            asyncio.run(self.provider.authenticate(None, headers={"cookie": ""}))
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass


TestCookieAuthMachine = CookieAuthMachine.TestCase


def test_no_headers_raises():
    provider = _make_cookie_provider()
    try:
        asyncio.run(provider.authenticate(None))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_no_cookie_header_raises():
    provider = _make_cookie_provider()
    try:
        asyncio.run(provider.authenticate(None, headers={}))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_missing_cookie_by_name_raises():
    provider = _make_cookie_provider()
    try:
        asyncio.run(provider.authenticate(None, headers={"cookie": "other=value"}))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_valid_cookie_delegates():
    provider = _make_cookie_provider()
    headers = {"cookie": "maistro_session=validjwt123"}
    ctx = asyncio.run(provider.authenticate(None, headers=headers))
    assert ctx.user_id == "cookie_user"


def test_cookie_handles_multiple():
    provider = _make_cookie_provider()
    headers = {"cookie": "a=1; maistro_session=jwt456; b=2"}
    ctx = asyncio.run(provider.authenticate(None, headers=headers))
    assert ctx.user_id == "cookie_user"


def test_malformed_cookie_header_raises():
    provider = _make_cookie_provider()
    try:
        asyncio.run(provider.authenticate(None, headers={"cookie": ";;;==@@@;"}))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_cookie_value_passed_as_bearer():
    received = {}

    class CaptureJWT:
        async def authenticate(self, authorization, headers=None):
            received["auth"] = authorization
            return AuthContext(user_id="cap")

    provider = CookieAuthProvider(jwt_provider=CaptureJWT(), cookie_name="sid")
    asyncio.run(provider.authenticate(None, headers={"cookie": "sid=mytoken"}))
    assert received["auth"] == "Bearer mytoken"


@given(token=st.text(min_size=1, max_size=40, alphabet=st.sampled_from(_ASCII)))
@settings(max_examples=30)
def test_various_tokens_work(token):
    provider = _make_cookie_provider()
    headers = {"cookie": f"maistro_session={token}"}
    ctx = asyncio.run(provider.authenticate(None, headers=headers))
    assert ctx.user_id == "cookie_user"
