"""Tests for maistro.auth.registry — loading, validation, authentication."""

from __future__ import annotations

import os
import tempfile

from maistro.auth._types import Scope
from maistro.auth.registry import ServiceKeyRegistry


def _make_registry() -> ServiceKeyRegistry:
    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            "conductor-router": {
                "key": "sk-svc-conductor-test-key",
                "scopes": ["llm:*", "events:*", "trading:read"],
            },
            "coinswarm": {
                "key": "sk-svc-coinswarm-test-key",
                "scopes": ["trading:*", "events:emit", "llm:chat_completions"],
            },
            "turing": {
                "key": "sk-svc-turing-test-key",
                "scopes": ["turing:*", "events:*", "memory:read"],
            },
        }
    )
    return registry


class TestLoadDict:
    def test_loads_services(self) -> None:
        registry = _make_registry()
        assert len(registry.services) == 3

    def test_scopes_expanded(self) -> None:
        registry = _make_registry()
        conductor = registry.services["conductor-router"]
        assert Scope.CHAT_COMPLETIONS in conductor.scopes
        assert Scope.EVENTS_EMIT in conductor.scopes
        assert Scope.TRADING_READ in conductor.scopes

    def test_skips_no_key(self) -> None:
        registry = ServiceKeyRegistry()
        registry.load_dict({"bad-service": {"scopes": ["llm:*"]}})
        assert len(registry.services) == 0

    def test_authenticate_valid_key(self) -> None:
        registry = _make_registry()
        identity = registry.authenticate("sk-svc-conductor-test-key")
        assert identity is not None
        assert identity.name == "conductor-router"

    def test_authenticate_invalid_key(self) -> None:
        registry = _make_registry()
        identity = registry.authenticate("sk-svc-nonexistent")
        assert identity is None


class TestLoadYaml:
    def test_loads_from_file(self) -> None:
        yaml_content = """
services:
  test-svc:
    key: sk-svc-test-123
    scopes:
      - "llm:chat_completions"
      - "events:*"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            registry = ServiceKeyRegistry()
            registry.load_yaml(f.name)
            assert len(registry.services) == 1
            identity = registry.authenticate("sk-svc-test-123")
            assert identity is not None
            assert identity.name == "test-svc"
            assert Scope.CHAT_COMPLETIONS in identity.scopes
            assert Scope.EVENTS_EMIT in identity.scopes
        os.unlink(f.name)

    def test_missing_file_graceful(self) -> None:
        registry = ServiceKeyRegistry()
        registry.load_yaml("/nonexistent/path.yaml")
        assert len(registry.services) == 0

    def test_empty_yaml_graceful(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            registry = ServiceKeyRegistry()
            registry.load_yaml(f.name)
            assert len(registry.services) == 0
        os.unlink(f.name)


class TestLoadEnv:
    def test_loads_from_env(self) -> None:
        os.environ["SERVICE_KEY_CONDUCTOR"] = "sk-svc-env-test"
        os.environ["SERVICE_SCOPES_CONDUCTOR"] = "llm:chat_completions,events:*"
        try:
            registry = ServiceKeyRegistry()
            registry.load_env()
            assert len(registry.services) >= 1
            identity = registry.authenticate("sk-svc-env-test")
            assert identity is not None
            assert identity.name == "conductor"
            assert Scope.CHAT_COMPLETIONS in identity.scopes
            assert Scope.EVENTS_EMIT in identity.scopes
        finally:
            del os.environ["SERVICE_KEY_CONDUCTOR"]
            if "SERVICE_SCOPES_CONDUCTOR" in os.environ:
                del os.environ["SERVICE_SCOPES_CONDUCTOR"]

    def test_env_no_scopes(self) -> None:
        os.environ["SERVICE_KEY_BARE"] = "sk-svc-bare-test"
        try:
            registry = ServiceKeyRegistry()
            registry.load_env()
            identity = registry.authenticate("sk-svc-bare-test")
            assert identity is not None
            assert len(identity.scopes) == 0
        finally:
            del os.environ["SERVICE_KEY_BARE"]


class TestValidation:
    def test_no_issues(self) -> None:
        registry = _make_registry()
        issues = registry.validate()
        assert len(issues) == 0

    def test_detects_no_scopes(self) -> None:
        registry = ServiceKeyRegistry()
        registry.load_dict({"empty-svc": {"key": "sk-svc-empty", "scopes": []}})
        issues = registry.validate()
        assert any("no scopes" in i for i in issues)

    def test_detects_duplicate_keys(self) -> None:
        registry = ServiceKeyRegistry()
        registry.load_dict(
            {
                "svc-a": {"key": "sk-svc-same-key", "scopes": ["llm:*"]},
                "svc-b": {"key": "sk-svc-same-key", "scopes": ["events:*"]},
            }
        )
        issues = registry.validate()
        assert any("Duplicate" in i for i in issues)
