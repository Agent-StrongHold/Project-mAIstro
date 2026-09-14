"""Production reachability assertions for governed capability Invocation (#55).

The layer is no longer specification-only. `agent.spawn_harness`,
`llm.summarize`, and live control-plane model consumers resolve scoped Bindings
and cross the governed Invocation boundary before provider-specific physical
effects. These tests pin that reach and the durable capability stores selected
for configured Containers.
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
    def test_the_sqlite_store_documents_durable_container_composition(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "container selects" in doc and "durable" in doc

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_the_capability_store_is_distinct_from_handler_delivery(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "handler" in doc
        assert invocation_store.SqliteInvocationStore is not None
        assert invocation_store.PgInvocationStore is not None

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_the_capability_store_is_reachable_from_container_composition(self) -> None:
        source = (_REPO / "packages/maistro-core/src/maistro/container.py").read_text()
        assert "_wire_capability_effects" in source
        assert "PgInvocationStore" in source
        assert "SqliteInvocationStore" in source

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_it_documents_runtime_schema_bootstrap(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "rather than an alembic migration" in doc

    def test_the_claim_about_the_migration_is_true(self) -> None:
        creating = [
            path.name
            for path in sorted(_MIGRATIONS.glob("*.py"))
            if "capability_invocations" in path.read_text()
        ]
        assert creating == ["034_capability_invocations.py"]

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
