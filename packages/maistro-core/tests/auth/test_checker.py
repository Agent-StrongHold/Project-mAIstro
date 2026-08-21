"""Tests for maistro.auth.checker — ServiceKeyChecker."""

from __future__ import annotations

import pytest

from maistro.auth._types import Scope
from maistro.auth.checker import ServiceKeyChecker
from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry


def _make_checker(scopes: list[str] | None = None) -> ServiceKeyChecker:
    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            "conductor-router": {
                "key": "sk-svc-conductor-test-key",
                "scopes": scopes if scopes is not None else ["llm:*", "events:*"],
            },
        }
    )
    provider = ServiceKeyAuthProvider(registry)
    return ServiceKeyChecker(provider, registry)


class TestCheck:
    def test_valid_key_returns_identity(self) -> None:
        checker = _make_checker()
        identity = checker.check({"x-service-key": "sk-svc-conductor-test-key"})
        assert identity is not None
        assert identity.name == "conductor-router"

    def test_invalid_key_returns_none(self) -> None:
        checker = _make_checker()
        identity = checker.check({"x-service-key": "sk-svc-wrong"})
        assert identity is None


class TestRequireScope:
    def test_no_identity_raises_value_error(self) -> None:
        checker = _make_checker()
        with pytest.raises(ValueError, match="Service key required"):
            checker.require_scope({}, Scope.CHAT_COMPLETIONS)

    def test_missing_scopes_raises_value_error(self) -> None:
        checker = _make_checker(scopes=["events:*"])
        with pytest.raises(ValueError, match="Missing scopes"):
            checker.require_scope(
                {"x-service-key": "sk-svc-conductor-test-key"}, Scope.CHAT_COMPLETIONS
            )

    def test_sufficient_scopes_returns_identity(self) -> None:
        checker = _make_checker(scopes=["llm:*"])
        identity = checker.require_scope(
            {"x-service-key": "sk-svc-conductor-test-key"}, Scope.CHAT_COMPLETIONS
        )
        assert identity.name == "conductor-router"

    def test_no_required_scopes_returns_identity(self) -> None:
        checker = _make_checker(scopes=[])
        identity = checker.require_scope({"x-service-key": "sk-svc-conductor-test-key"})
        assert identity.name == "conductor-router"


class TestIsServiceRequest:
    def test_x_service_key_header_present(self) -> None:
        checker = _make_checker()
        assert checker.is_service_request({"x-service-key": "anything"}) is True

    def test_bearer_svc_prefix_present(self) -> None:
        checker = _make_checker()
        assert checker.is_service_request({"authorization": "Bearer sk-svc-whatever"}) is True

    def test_bearer_without_svc_prefix_is_false(self) -> None:
        checker = _make_checker()
        assert checker.is_service_request({"authorization": "Bearer sk-user-token"}) is False

    def test_no_relevant_headers_is_false(self) -> None:
        checker = _make_checker()
        assert checker.is_service_request({}) is False


class TestFromEnv:
    def test_loads_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_KEY_CONDUCTOR", "sk-svc-env-test-key")
        monkeypatch.setenv("SERVICE_SCOPES_CONDUCTOR", "llm:*")
        monkeypatch.delenv("SERVICE_KEYS_FILE", raising=False)

        checker = ServiceKeyChecker.from_env()
        identity = checker.check({"x-service-key": "sk-svc-env-test-key"})

        assert identity is not None
        assert identity.name == "conductor"

    def test_logs_validation_issues(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("SERVICE_KEY_NOSCOPE", "sk-svc-noscope-key")
        monkeypatch.delenv("SERVICE_SCOPES_NOSCOPE", raising=False)
        monkeypatch.delenv("SERVICE_KEYS_FILE", raising=False)

        with caplog.at_level("WARNING"):
            ServiceKeyChecker.from_env()

        assert "has no scopes" in caplog.text
