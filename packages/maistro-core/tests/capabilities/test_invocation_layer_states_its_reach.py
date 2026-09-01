"""Production reachability assertions for governed capability Invocation (#55).

The layer is no longer specification-only. `agent.spawn_harness` is the first
canonical Run consumer that resolves a scoped Binding and crosses the governed
Invocation boundary before a provider-specific physical effect. These tests
pin that reach while continuing to state the narrower truth that the standalone
SQLite capability-Invocation store has not yet been wired or migrated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.capabilities import invocation_store
from maistro.capabilities.binding_store import BindingStore, InMemoryBindingStore
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    default_effect_context,
)
from maistro.capabilities.governed_invocation import GovernedInvocationExecutionService

pytestmark = [pytest.mark.contract("behavioral")]

_REPO = Path(__file__).resolve().parents[4]
_MIGRATIONS = _REPO / "alembic" / "versions"
_SPAWN_NODE = (
    _REPO
    / "packages"
    / "maistro-core"
    / "src"
    / "maistro"
    / "graph"
    / "nodes"
    / "agent_spawn_harness.py"
)


class TestTheInvocationLayerStatesItsReach:
    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_production_composition_constructs_the_governed_service(self) -> None:
        effects = default_effect_context()
        assert isinstance(effects, CapabilityEffectContext)
        assert isinstance(effects.invocations, GovernedInvocationExecutionService)

    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_production_composition_owns_one_canonical_binding_store(self) -> None:
        effects = default_effect_context()
        assert isinstance(effects.bindings, BindingStore)
        assert isinstance(effects.bindings, InMemoryBindingStore)

    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_reachable_agent_harness_node_calls_governed_invocation(self) -> None:
        text = _SPAWN_NODE.read_text()
        assert "self._effects.invocations.invoke(" in text

    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_reachable_agent_harness_node_resolves_binding_authority(self) -> None:
        text = _SPAWN_NODE.read_text()
        assert "await self._effects.bindings.resolve(" in text
        assert "await provider.adapter.dispatch(" in text


class TestTheStoreStatesItsReachAndItsTable:
    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_the_sqlite_store_still_says_nothing_wires_it(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "unreached" in doc or "nothing constructs" in doc

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_it_disambiguates_itself_from_the_store_the_container_does_wire(self) -> None:
        assert "maistro.events.invocations" in (invocation_store.__doc__ or "")

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_it_says_its_table_has_no_migration(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "no migration" in doc

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_the_claim_about_the_migration_is_true(self) -> None:
        creating = [
            path.name
            for path in sorted(_MIGRATIONS.glob("*.py"))
            if "capability_invocations" in path.read_text()
        ]
        assert creating == []

    def test_the_migration_scan_has_a_corpus(self) -> None:
        assert len(list(_MIGRATIONS.glob("*.py"))) > 10


class TestTheReachIsWhatTheStatementSays:
    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_a_production_module_calls_the_governed_seam(self) -> None:
        callers = sorted(
            str(path.relative_to(_REPO))
            for path in _REPO.glob("packages/*/src/**/*.py")
            if _calls_governed_seam(path.read_text())
        )
        assert "packages/maistro-core/src/maistro/graph/nodes/agent_spawn_harness.py" in callers

    def test_the_caller_scan_finds_calls_not_definitions(self) -> None:
        assert _calls_governed_seam("    await self._effects.invocations.invoke(binding=binding)")
        assert not _calls_governed_seam("    async def invoke(")
        assert not _calls_governed_seam("GovernedInvocationExecutionService owns invoke")


def _calls_governed_seam(text: str) -> bool:
    return any(
        ".invocations.invoke(" in line and not line.lstrip().startswith(("async def", "def"))
        for line in text.splitlines()
    )
