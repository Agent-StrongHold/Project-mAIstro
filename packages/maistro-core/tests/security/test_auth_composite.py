"""Tests for maistro.security.auth_composite — composite multi-provider auth."""

from __future__ import annotations

import pytest

from maistro.security._types import SYSTEM_AUTH, AuthContext
from maistro.security.auth_composite import (
    AuthError,
    CompositeAuthProvider,
    CredentialNotApplicable,
)


class _FakeProvider:
    def __init__(self, behavior: str, result: object = "ctx") -> None:
        self.behavior = behavior
        self.result = result
        self.calls: list[tuple[str | None, dict[str, str] | None]] = []

    async def authenticate(self, authorization: str | None, headers: dict[str, str] | None = None):
        self.calls.append((authorization, headers))
        if self.behavior == "success":
            return self.result
        if self.behavior == "not_applicable":
            raise CredentialNotApplicable("not my format")
        if self.behavior == "auth_error":
            raise AuthError("rejected")
        if self.behavior == "value_error":
            raise ValueError("unclassified provider failure")
        if self.behavior == "boom":
            raise RuntimeError("boom")
        raise AssertionError("unreachable")


class TestCompositeAuthProvider:
    @pytest.mark.asyncio
    async def test_first_provider_success_returns_result(self) -> None:
        provider = _FakeProvider("success", result="ctx1")
        composite = CompositeAuthProvider([provider])
        result = await composite.authenticate("Bearer abc", headers={"x": "y"})
        assert result == "ctx1"
        assert provider.calls == [("Bearer abc", {"x": "y"})]

    @pytest.mark.asyncio
    async def test_not_applicable_falls_through_to_next_provider(self) -> None:
        first = _FakeProvider("not_applicable")
        second = _FakeProvider("success", result="ctx2")
        composite = CompositeAuthProvider([first, second])
        result = await composite.authenticate("token")
        assert result == "ctx2"

    @pytest.mark.asyncio
    async def test_auth_error_aborts_immediately(self) -> None:
        first = _FakeProvider("auth_error")
        second = _FakeProvider("success")
        composite = CompositeAuthProvider([first, second])
        with pytest.raises(AuthError, match="rejected"):
            await composite.authenticate("token")
        assert second.calls == []

    @pytest.mark.asyncio
    async def test_unclassified_value_error_does_not_fall_through(self) -> None:
        first = _FakeProvider("value_error")
        second = _FakeProvider("success", result="ctx3")
        composite = CompositeAuthProvider([first, second])
        with pytest.raises(AuthError, match="infrastructure failure: ValueError"):
            await composite.authenticate("token")
        assert second.calls == []

    @pytest.mark.asyncio
    async def test_unexpected_exception_aborts_and_wraps_as_autherror(self) -> None:
        first = _FakeProvider("boom")
        second = _FakeProvider("success")
        composite = CompositeAuthProvider([first, second])
        with pytest.raises(AuthError, match="Authentication infrastructure failure: RuntimeError"):
            await composite.authenticate("token")
        assert second.calls == []

    @pytest.mark.asyncio
    async def test_all_providers_not_applicable_raises_autherror(self) -> None:
        composite = CompositeAuthProvider(
            [_FakeProvider("not_applicable"), _FakeProvider("not_applicable")]
        )
        with pytest.raises(AuthError, match="No authentication provider accepted"):
            await composite.authenticate("token")

    @pytest.mark.asyncio
    async def test_empty_provider_list_raises_autherror(self) -> None:
        composite = CompositeAuthProvider([])
        with pytest.raises(AuthError, match="No authentication provider accepted"):
            await composite.authenticate("token")

    @pytest.mark.asyncio
    async def test_none_authorization_passed_through(self) -> None:
        provider = _FakeProvider("success", result="ctx")
        composite = CompositeAuthProvider([provider])
        await composite.authenticate(None)
        assert provider.calls == [(None, None)]

    @pytest.mark.asyncio
    async def test_provider_order_is_first_success(self) -> None:
        first = _FakeProvider("success", result="first")
        second = _FakeProvider("success", result="second")
        result = await CompositeAuthProvider([first, second]).authenticate("token")
        assert result == "first"
        assert second.calls == []

    @pytest.mark.asyncio
    async def test_static_key_rejection_is_terminal_for_ambiguous_bearer_shape(self) -> None:
        from maistro.security.auth_static import StaticKeyAuthProvider

        later = _FakeProvider("success", result=SYSTEM_AUTH)
        composite = CompositeAuthProvider([StaticKeyAuthProvider("static-secret"), later])
        with pytest.raises(AuthError, match="Invalid API key"):
            await composite.authenticate("Bearer another-credential")
        assert later.calls == []

    @pytest.mark.asyncio
    async def test_unknown_shape_reaches_a_later_provider(self) -> None:
        from maistro.security.auth_static import StaticKeyAuthProvider

        later = _FakeProvider("success", result="later-context")
        composite = CompositeAuthProvider([StaticKeyAuthProvider("static-secret"), later])
        result = await composite.authenticate("Basic later-credential")
        assert result == "later-context"

    @pytest.mark.asyncio
    async def test_valid_cookie_credential_reaches_later_provider(self) -> None:
        from maistro.security.auth_cookie import CookieAuthProvider
        from maistro.security.auth_static import StaticKeyAuthProvider

        class _ValidJWT:
            async def authenticate(
                self, authorization: str | None, headers: dict[str, str] | None = None
            ) -> AuthContext:
                assert authorization == "Bearer valid-session-token"
                return AuthContext(user_id="cookie-user")

        composite = CompositeAuthProvider(
            [
                StaticKeyAuthProvider("static-secret"),
                CookieAuthProvider(jwt_provider=_ValidJWT()),  # type: ignore[arg-type]
            ]
        )
        result = await composite.authenticate(
            None, headers={"cookie": "maistro_session=valid-session-token"}
        )
        assert result.user_id == "cookie-user"

    @pytest.mark.asyncio
    async def test_rejection_audit_names_scheme_without_credential(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from maistro.security.auth_static import StaticKeyAuthProvider

        secret = "static-secret"
        composite = CompositeAuthProvider([StaticKeyAuthProvider(secret)])
        with caplog.at_level("INFO", logger="maistro.auth.composite"), pytest.raises(AuthError):
            await composite.authenticate(f"Bearer {secret}-wrong")
        messages = [record.getMessage() for record in caplog.records]
        assert any("scheme=static_api_key" in message for message in messages)
        assert any("auth_provider_rejected" in message for message in messages)
        assert all(secret not in message for message in messages)
