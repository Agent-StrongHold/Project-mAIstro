"""Coverage for live Sentinel permission sources (#1165, ADR-072726-0d6b).

These pin the reconciliation with canonical capability state and the
runtime-revoke path: a decision-time source, a disabled slot denying without
restart, and a broken/unavailable source failing closed.
"""

from __future__ import annotations

from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.types import FallbackPolicy, SlotSpec
from maistro.security.sentinel.permission_source import (
    CapabilityPermissionSource,
    PermissionSource,
    StaticPermissionSource,
    resolve_live_table,
)


def _registry_with(slot: str) -> CapabilityRegistry:
    registry = default_capability_registry()
    if slot not in registry.slots():
        registry.define(SlotSpec(name=slot, fallback_policy=FallbackPolicy.SAFE_NOOP))
    return registry


# ─── StaticPermissionSource ────────────────────────────────────────────────


async def test_static_source_returns_its_table_by_reference():
    table = {"exec": frozenset({"admin"})}
    assert await StaticPermissionSource(table).current_table() is table


# ─── CapabilityPermissionSource: live canonical reconciliation ─────────────


async def test_capability_source_disabled_slot_denies_without_restart():
    """The runtime-revoke criterion (#1165): disabling a canonical capability
    slot removes the matching tool's authorization at the next resolution."""
    registry = _registry_with("deploy")
    base = {"deploy": frozenset({"admin"}), "exec": frozenset({"admin"})}
    source = CapabilityPermissionSource(base=base, capabilities=registry)

    assert (await source.current_table())["deploy"] == frozenset({"admin"})

    registry.set_enabled("deploy", False)  # the runtime disable gesture

    after = await source.current_table()
    assert "deploy" not in after  # miss -> deny, no restart involved
    assert after["exec"] == frozenset({"admin"})  # non-slot tools unaffected

    registry.set_enabled("deploy", True)
    restored = await source.current_table()
    assert restored["deploy"] == frozenset({"admin"})  # restore == base, never more


async def test_capability_source_never_grants_what_the_base_table_denies():
    """The adapter can only REMOVE authority: an enabled slot does not grant a
    tool the deployment table does not name, and an explicit hard deny
    (empty role set) stays a hard deny."""
    registry = default_capability_registry()  # defines the canonical slots
    source = CapabilityPermissionSource(base={"approval": frozenset()}, capabilities=registry)
    table = await source.current_table()
    assert table["approval"] == frozenset()  # denies everyone, slot enabled or not
    assert "infra_action" not in table  # never named by the deployment table


async def test_capability_source_unknown_tool_is_a_plain_miss():
    """A tool that is neither a slot nor a base entry cannot appear."""
    registry = default_capability_registry()
    source = CapabilityPermissionSource(base={}, capabilities=registry)
    table = await source.current_table()
    assert "never_configured_tool" not in table
    assert "read_file" not in table


async def test_capability_source_source_of_truth_is_the_registry_itself():
    """No hand-maintained mapping: the gated names come from registry.slots()."""
    registry = default_capability_registry()
    source = CapabilityPermissionSource(base={}, capabilities=registry)
    table = await source.current_table()
    for slot in registry.slots():
        assert slot not in table  # empty base: slots gated, not granted


# ─── resolve_live_table: fail-closed collapse ───────────────────────────────


class _BrokenSource:
    async def current_table(self):
        raise RuntimeError("policy store down")


class _UnavailableSource:
    async def current_table(self):
        return None


async def test_resolve_live_table_collapses_failure_to_none():
    assert await resolve_live_table(_BrokenSource()) is None  # type: ignore[arg-type]


async def test_resolve_live_table_collapses_none_return_to_none():
    assert await resolve_live_table(_UnavailableSource()) is None  # type: ignore[arg-type]


async def test_resolve_live_table_passes_a_real_table_through():
    table = {"deploy": frozenset({"admin"})}
    assert await resolve_live_table(StaticPermissionSource(table)) is table


# ─── The seam ────────────────────────────────────────────────────────────────


def test_both_adapters_satisfy_the_permission_source_protocol():
    registry = default_capability_registry()
    assert isinstance(StaticPermissionSource({}), PermissionSource)
    assert isinstance(CapabilityPermissionSource({}, registry), PermissionSource)
