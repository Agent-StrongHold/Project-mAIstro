"""The session cookie's shape, and what happens when it would be unsafe (#369).

`session_cookie_secure` defaulted to **False**. The reason given was real — the
documented dev loop is `http://localhost:8101`, where a `Secure` cookie is
silently dropped and login looks like it does nothing — and it is an argument
for a local-development escape, not for the default.

A default is the shape every deployment that did not think about it takes, and
"every deployment that did not think about it sends its session cookie in the
clear" is the wrong way round. These tests read `Settings()` and the policy
helper **directly**, not through `tests/conftest.py`'s environment, precisely
because that conftest declares this suite a local-development context.
"""

from __future__ import annotations

import pytest

from maistro.security.transport import (
    InsecureTransportError,
    assert_session_transport_is_safe,
)


def _fresh_settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Settings built from a named environment, ignoring the developer's own.

    `Settings` reads `.env` files as well as the process environment, so a
    machine that happens to have `SESSION_COOKIE_SECURE=false` sitting in a
    `.env` would make a test about the *default* pass or fail for a reason that
    has nothing to do with the code.
    """
    from config import Settings

    for key in ("SESSION_COOKIE_SECURE", "ALLOW_INSECURE_TRANSPORT", "TRUSTED_PROXY_IPS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


class TestTheDefaultIsSecure:
    def test_the_session_cookie_is_secure_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The change #369 is about. This assertion is the opposite of what
        `develop` produces."""
        assert _fresh_settings(monkeypatch).session_cookie_secure is True

    def test_insecure_transport_is_not_allowed_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _fresh_settings(monkeypatch).allow_insecure_transport is False

    def test_no_proxy_is_trusted_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A deployment that forgets to name its proxy loses HSTS rather than
        gaining a header any caller can forge."""
        assert _fresh_settings(monkeypatch).trusted_proxy_ips == ""

    def test_samesite_defaults_to_lax(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`lax` is what makes an emailed link to a Conductor page work.
        `strict` would break it; `none` is only meaningful with Secure and is
        not offered as a default."""
        assert _fresh_settings(monkeypatch).session_cookie_samesite == "lax"


class TestStartupRefusesAPlaintextSession:
    """`lifespan` calls this before anything else, and deliberately outside the
    try/except every other start-up step sits in. A Conductor without a design
    service is a degraded Conductor; a Conductor that will send its session
    cookie over plaintext is one whose sessions any network in the path can
    lift."""

    def test_the_default_configuration_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _fresh_settings(monkeypatch)
        assert_session_transport_is_safe(
            cookie_secure=settings.session_cookie_secure,
            allow_insecure_transport=settings.allow_insecure_transport,
        )

    def test_turning_secure_off_alone_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _fresh_settings(monkeypatch, SESSION_COOKIE_SECURE="false")
        with pytest.raises(InsecureTransportError):
            assert_session_transport_is_safe(
                cookie_secure=settings.session_cookie_secure,
                allow_insecure_transport=settings.allow_insecure_transport,
            )

    def test_the_development_escape_has_to_be_stated_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two settings, on purpose. Turning off a security control and
        declaring a development run are different statements, and collapsing
        them into one is how the first becomes invisible inside the second."""
        settings = _fresh_settings(
            monkeypatch, SESSION_COOKIE_SECURE="false", ALLOW_INSECURE_TRANSPORT="true"
        )
        assert_session_transport_is_safe(
            cookie_secure=settings.session_cookie_secure,
            allow_insecure_transport=settings.allow_insecure_transport,
        )

    def test_the_escape_alone_does_not_weaken_a_secure_deployment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting the dev flag on a TLS deployment must not turn the cookie
        insecure — it only waives the refusal."""
        settings = _fresh_settings(monkeypatch, ALLOW_INSECURE_TRANSPORT="true")
        assert settings.session_cookie_secure is True

    def test_lifespan_calls_the_check_outside_a_try(self) -> None:
        """A refusal that a broad `except Exception` swallowed would be a
        warning again. Read from the source because the property is about where
        the call sits, not what it returns."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        start = source.index("async def lifespan(")
        call = source.index("assert_session_transport_is_safe(", start)
        before = source[start:call]

        assert "try:" not in before.split("_settings = get_settings()")[-1]


class TestTheCookieCarriesThePolicy:
    """The settings have to reach `set_cookie`, or they are configuration that
    describes nothing."""

    def test_login_marks_the_cookie_secure_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import get_settings

        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        get_settings.cache_clear()
        try:
            from routes.auth import _cookie_secure

            assert _cookie_secure() is True
        finally:
            get_settings.cache_clear()

    def test_samesite_reaches_the_cookie(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It was hardcoded `"lax"`, so a deployment that wanted `strict` had
        no way to ask."""
        from config import get_settings

        monkeypatch.setenv("SESSION_COOKIE_SAMESITE", "strict")
        get_settings.cache_clear()
        try:
            from routes.auth import _cookie_samesite

            assert _cookie_samesite() == "strict"
        finally:
            get_settings.cache_clear()

    def test_both_are_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read per call rather than captured at import, so a deployment's
        settings apply without re-importing the module — and so these tests
        mean what they say."""
        from config import get_settings
        from routes.auth import _cookie_secure

        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
        get_settings.cache_clear()
        assert _cookie_secure() is False

        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        get_settings.cache_clear()
        try:
            assert _cookie_secure() is True
        finally:
            get_settings.cache_clear()

    def test_logout_clears_with_the_same_attributes_it_set(self) -> None:
        """A cookie is only cleared when the delete matches the attributes it
        was set with, so `delete_cookie` has to read the same helpers."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "routes" / "auth.py").read_text(
            encoding="utf-8"
        )
        start = source.index("response.delete_cookie(")
        # Balanced-paren scan rather than `index(")")`, which stops inside
        # `_cookie_samesite()` — the very call this is checking for.
        depth, end = 0, start
        for index in range(start, len(source)):
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        delete = source[start : end + 1]

        assert "_cookie_secure()" in delete
        assert "_cookie_samesite()" in delete
        assert 'path="/"' in delete
