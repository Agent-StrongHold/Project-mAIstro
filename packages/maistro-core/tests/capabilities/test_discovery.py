from __future__ import annotations

import logging

import pytest

from maistro.capabilities.discovery import discover_into
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.capabilities.types import FallbackPolicy, SlotSpec


class _FakeEP:
    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        return self._obj


def _factory():
    return FakeProvider("plugin_search", "search")


def test_discover_registers_inactive():
    reg = CapabilityRegistry()
    reg.define(SlotSpec(name="search", fallback_policy=FallbackPolicy.SAFE_NOOP))
    n = discover_into(reg, entry_points=[_FakeEP("plugin_search", _factory)])
    assert n == 1
    assert "plugin_search" in reg.installed("search")
    assert reg.active_name("search") is None


def test_discover_skips_unknown_slot_gracefully():
    reg = CapabilityRegistry()  # no slots defined
    n = discover_into(reg, entry_points=[_FakeEP("plugin_search", _factory)])
    assert n == 0


class _RaisingLoadEP:
    """Entry point whose .load() itself raises (e.g. a broken module reference)."""

    name = "broken_import"

    def load(self) -> object:
        raise ImportError("no module named broken_provider_pkg")


class _NonCallableFactoryEP:
    """.load() succeeds but returns something that isn't a zero-arg factory."""

    name = "not_a_factory"

    def load(self) -> object:
        return "this is a string, not a callable"


class _RaisingFactoryEP:
    """.load() returns a callable factory, but calling it raises."""

    name = "factory_blows_up"

    def load(self) -> object:
        def _boom():
            raise RuntimeError("factory exploded during construction")

        return _boom


class _MalformedProviderEP:
    """Factory returns an object missing the .slot/.name shape register() needs."""

    name = "malformed_provider"

    def load(self) -> object:
        return lambda: object()


class TestDiscoverIntoAdversarialEntryPoints:
    """discover_into must never raise on a bad entry point — it logs + skips,
    and one bad entry point must never block registration of the others."""

    def _registry(self) -> CapabilityRegistry:
        reg = CapabilityRegistry()
        reg.define(SlotSpec(name="search", fallback_policy=FallbackPolicy.SAFE_NOOP))
        return reg

    @pytest.mark.parametrize(
        "bad_ep",
        [
            _RaisingLoadEP(),
            _NonCallableFactoryEP(),
            _RaisingFactoryEP(),
            _MalformedProviderEP(),
        ],
        ids=["load_raises", "non_callable_factory", "factory_raises", "malformed_provider"],
    )
    def test_each_failure_shape_is_skipped_not_raised(self, bad_ep: object) -> None:
        reg = self._registry()
        n = discover_into(reg, entry_points=[bad_ep])  # must not raise
        assert n == 0
        assert reg.installed("search") == []

    def test_one_bad_entry_point_does_not_block_the_rest(self) -> None:
        reg = self._registry()
        eps = [
            _RaisingLoadEP(),
            _FakeEP("plugin_search", _factory),
            _NonCallableFactoryEP(),
            _RaisingFactoryEP(),
            _MalformedProviderEP(),
        ]
        n = discover_into(reg, entry_points=eps)
        assert n == 1
        assert reg.installed("search") == ["plugin_search"]

    def test_bad_entry_point_does_not_partially_register(self) -> None:
        """A failure mid-construction must leave no trace in the registry —
        register() is never reached for a factory that raised."""
        reg = self._registry()
        discover_into(reg, entry_points=[_RaisingFactoryEP()])
        assert reg.installed("search") == []
        assert reg.active_name("search") is None

    def test_failures_are_logged_not_silent(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = self._registry()
        with caplog.at_level(logging.WARNING, logger="maistro.capabilities.discovery"):
            discover_into(reg, entry_points=[_RaisingLoadEP()])
        assert any("broken_import" in record.message for record in caplog.records)

    def test_empty_entry_points_returns_zero(self) -> None:
        reg = self._registry()
        assert discover_into(reg, entry_points=[]) == 0
