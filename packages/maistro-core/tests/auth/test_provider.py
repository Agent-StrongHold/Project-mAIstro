"""Tests for maistro.auth.provider — ServiceKeyAuthProvider."""

from __future__ import annotations

from typing import ClassVar

import pytest

from maistro.auth._types import Scope
from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry


def _make_provider() -> ServiceKeyAuthProvider:
    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            "conductor-router": {
                "key": "sk-svc-conductor-test-key",
                "scopes": ["llm:*", "events:*"],
            },
        }
    )
    return ServiceKeyAuthProvider(registry)


class TestServiceKeyAuthProvider:
    def test_valid_x_service_key(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({"x-service-key": "sk-svc-conductor-test-key"})
        assert identity is not None
        assert identity.name == "conductor-router"

    def test_valid_bearer_with_svc_prefix(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({"authorization": "Bearer sk-svc-conductor-test-key"})
        assert identity is not None
        assert identity.name == "conductor-router"

    def test_bearer_without_svc_prefix_ignored(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({"authorization": "Bearer sk-user-regular-token"})
        assert identity is None

    def test_no_headers(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({})
        assert identity is None

    def test_invalid_key(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({"x-service-key": "sk-svc-wrong"})
        assert identity is None

    def test_empty_x_service_key(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({"x-service-key": ""})
        assert identity is None

    def test_scopes_present(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate({"x-service-key": "sk-svc-conductor-test-key"})
        assert identity is not None
        assert Scope.CHAT_COMPLETIONS in identity.scopes
        assert Scope.EVENTS_EMIT in identity.scopes

    def test_x_service_key_takes_priority(self) -> None:
        provider = _make_provider()
        identity = provider.authenticate(
            {
                "x-service-key": "sk-svc-conductor-test-key",
                "authorization": "Bearer sk-svc-something-else",
            }
        )
        assert identity is not None
        assert identity.name == "conductor-router"


class TestAuthProviderAdversarialProbes:
    """Hostile header shapes — must never authenticate a non-matching key or crash.

    Modeled on guardrail_probes.py's must-always-block pattern.
    """

    PROBES: ClassVar = [
        {
            "id": "ap1",
            "desc": "Uppercase header name",
            "headers": {"X-Service-Key": "sk-svc-conductor-test-key"},
        },
        {
            "id": "ap2",
            "desc": "Mixed-case header name",
            "headers": {"X-sErViCe-KeY": "sk-svc-conductor-test-key"},
        },
        {
            "id": "ap3",
            "desc": "Bearer lowercase scheme",
            "headers": {"authorization": "bearer sk-svc-conductor-test-key"},
        },
        {
            "id": "ap4",
            "desc": "Bearer no space",
            "headers": {"authorization": "Bearersk-svc-conductor-test-key"},
        },
        {"id": "ap6", "desc": "Bearer empty token", "headers": {"authorization": "Bearer "}},
        {
            "id": "ap7",
            "desc": "Bearer bare prefix no key",
            "headers": {"authorization": "Bearer sk-svc-"},
        },
        {
            "id": "ap8",
            "desc": "NUL byte in key value",
            "headers": {"x-service-key": "sk-svc-conductor-test-key\x00"},
        },
        {
            "id": "ap9",
            "desc": "NUL byte prefix in key value",
            "headers": {"x-service-key": "\x00sk-svc-conductor-test-key"},
        },
        {
            "id": "ap10",
            "desc": "Oversized key value",
            "headers": {"x-service-key": "sk-svc-conductor-test-key" + "A" * 100_000},
        },
        {
            "id": "ap11",
            "desc": "Whitespace-padded key",
            "headers": {"x-service-key": "  sk-svc-conductor-test-key  "},
        },
        {
            "id": "ap12",
            "desc": "Substring of valid key",
            "headers": {"x-service-key": "sk-svc-conductor-test-ke"},
        },
        {
            "id": "ap13",
            "desc": "Valid key plus trailing char",
            "headers": {"x-service-key": "sk-svc-conductor-test-keyX"},
        },
        {
            "id": "ap14",
            "desc": "Authorization without Bearer scheme",
            "headers": {"authorization": "sk-svc-conductor-test-key"},
        },
        {
            "id": "ap15",
            "desc": "Basic auth scheme",
            "headers": {"authorization": "Basic sk-svc-conductor-test-key"},
        },
        {
            "id": "ap16",
            "desc": "Unicode lookalike key",
            "headers": {"x-service-key": "sk-svc-conductоr-test-key"},  # noqa: RUF001 - cyrillic 'o' lookalike
        },
    ]

    @pytest.mark.parametrize("probe", PROBES, ids=[p["id"] for p in PROBES])
    def test_probe_never_authenticates(self, probe: dict) -> None:
        provider = _make_provider()
        identity = provider.authenticate(probe["headers"])  # must not raise either
        assert identity is None, f"probe {probe['id']} ({probe['desc']}) unexpectedly authenticated"

    def test_all_probes_run(self) -> None:
        assert len(self.PROBES) >= 10
