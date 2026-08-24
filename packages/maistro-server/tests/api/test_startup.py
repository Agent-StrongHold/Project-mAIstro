"""Tests for startup validation — CRIT-02."""

from __future__ import annotations

import pytest

from maistro.config.settings import Settings
from maistro_server.main import _validate_startup


@pytest.fixture(autouse=True)
def _router_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ROUTER_API_KEY for every case that is not about ROUTER_API_KEY (#142).

    The server builds a maistro-core Container so that chat turns reach the
    Conduit, and `create_container` refuses an empty one — so `_validate_startup`
    now checks it, and every other check here would otherwise trip over it first.
    """
    monkeypatch.setenv("ROUTER_API_KEY", "test-router-key")


class TestStartupValidation:
    """CRIT-02: App must refuse to start without API keys when require_auth=True."""

    def test_no_keys_require_auth_raises(self) -> None:
        settings = Settings(api_keys=[], require_auth=True)
        with pytest.raises(RuntimeError, match="No API keys configured"):
            _validate_startup(settings)

    def test_keys_present_passes(self) -> None:
        settings = Settings(api_keys=["test-key"], require_auth=True)
        _validate_startup(settings)  # Should not raise

    def test_require_auth_false_allows_no_keys(self) -> None:
        settings = Settings(api_keys=[], require_auth=False)
        _validate_startup(settings)  # Should not raise


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
class TestWebhookSecretValidation:
    """Review finding C5, boot-time half.

    The route-level fix turns an unconfigured receiver into a 503 per request.
    `REQUIRE_WEBHOOK_SECRETS=true` converts that into a boot failure instead, so
    a deployment that depends on webhooks fails loudly at start rather than
    silently rejecting every delivery until someone reads the logs.

    Off by default: a deployment that receives no webhooks should not be forced
    to invent secrets, and the routes are already fail-closed without it.
    """

    def test_default_is_off(self) -> None:
        assert Settings(require_auth=False).require_webhook_secrets is False

    def test_enabled_without_secrets_raises(self) -> None:
        settings = Settings(require_auth=False, require_webhook_secrets=True)
        with pytest.raises(RuntimeError, match="REQUIRE_WEBHOOK_SECRETS"):
            _validate_startup(settings)

    @pytest.mark.parametrize(
        ("github", "ci"),
        [("gh-secret", ""), ("", "ci-secret")],
    )
    def test_enabled_with_only_one_secret_raises(self, github: str, ci: str) -> None:
        """Both, or neither — one configured secret is a half-open deployment."""
        settings = Settings(
            require_auth=False,
            require_webhook_secrets=True,
            github_webhook_secret=github,
            ci_webhook_secret=ci,
        )
        with pytest.raises(RuntimeError, match="REQUIRE_WEBHOOK_SECRETS"):
            _validate_startup(settings)

    def test_enabled_with_both_secrets_passes(self) -> None:
        settings = Settings(
            require_auth=False,
            require_webhook_secrets=True,
            github_webhook_secret="gh-secret",
            ci_webhook_secret="ci-secret",
        )
        _validate_startup(settings)  # Should not raise

    def test_disabled_without_secrets_passes(self) -> None:
        settings = Settings(require_auth=False, require_webhook_secrets=False)
        _validate_startup(settings)  # Should not raise


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
class TestRouterApiKeyValidation:
    """#142: the server builds a Container, so it needs the key one requires.

    Checked here rather than left to surface from `create_container`, which
    raises a `ConfigError` several frames deep in lifespan — a stack trace that
    reads as a bug rather than as a missing setting.
    """

    def test_an_unset_router_api_key_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ROUTER_API_KEY"):
            _validate_startup(Settings(api_keys=["k"], require_auth=True))

    def test_a_whitespace_only_router_api_key_is_not_a_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shape a .env file produces from `ROUTER_API_KEY= `. Accepting it
        would move the failure back into container wiring, which is the thing
        this check exists to prevent."""
        monkeypatch.setenv("ROUTER_API_KEY", "   ")
        with pytest.raises(RuntimeError, match="ROUTER_API_KEY"):
            _validate_startup(Settings(api_keys=["k"], require_auth=True))
