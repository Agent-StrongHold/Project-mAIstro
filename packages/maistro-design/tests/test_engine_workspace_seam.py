"""The DesignEngine #777 seams: consume the canonical owners, never self-build.

#777's stop condition forbids a Design-Studio-private Agent runtime or
reconciliation loop. The engine therefore takes the persistent Workspace Agent
front door and the canonical physical-execution reconciler as *injected*
dependencies, and raises loudly when they are absent — a missing dependency
must fail, not silently turn into a private substitute.
"""

from __future__ import annotations

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import InMemoryRunStore
from maistro_design.engine import (
    DesignEngine,
    ReconcilerFactory,
    WorkspaceAgentResolver,
)


def _run_store() -> InMemoryRunStore:
    """A real in-memory run store, as ``maistro.runs.wiring`` composes one."""
    return InMemoryRunStore(project_store=InMemoryProjectScopeStore())


class _RosterRow:
    """Stand-in for the app layer's persistent Workspace Agent row.

    The real row type lives in the app layer (the reference Conductor's
    ``models.schemas.Agent``), which maistro-design cannot depend on; the seam
    deliberately passes it through untouched.
    """


class _RecordingResolver:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, workspace_id: str) -> _RosterRow:
        self.seen.append(workspace_id)
        return _RosterRow()


class _RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


def _canonical_factory(
    run_store: InMemoryRunStore, *, event_sink: _RecordingEventSink | None = None
) -> AttemptLifecycleReconciler:
    """Build the real ``maistro.runs`` reconciler, as production wiring would."""
    return AttemptLifecycleReconciler(run_store, events=event_sink)


class TestUnconfiguredSeamsFailLoudly:
    async def test_no_private_workspace_agent_is_built(self, engine) -> None:
        """Without an injected resolver the engine refuses, rather than
        materializing a Design-Studio-private agent."""
        with pytest.raises(RuntimeError, match="workspace_agent_resolver"):
            await engine.get_workspace_agent("ws-404")

    async def test_no_private_reconciler_is_built(self, engine) -> None:
        """Without an injected factory the engine refuses, rather than
        constructing its own reconciler over a guessed store."""
        with pytest.raises(RuntimeError, match="reconciler_factory"):
            engine.get_reconciler(_run_store())


class TestWorkspaceAgentSeam:
    async def test_resolves_whatever_the_canonical_front_door_returns(
        self, skill_registry, system_registry
    ) -> None:
        resolver = _RecordingResolver()
        engine = DesignEngine(
            skill_registry=skill_registry,
            system_registry=system_registry,
            workspace_agent_resolver=resolver,
        )

        agent = await engine.get_workspace_agent("ws-1")

        assert isinstance(agent, _RosterRow)
        assert resolver.seen == ["ws-1"]

    async def test_the_reference_front_door_satisfies_the_protocol(self) -> None:
        """The Conductor's ``resolve_workspace_agent`` is async and takes one
        workspace id, exactly the seam's shape (runtime-checkable protocol)."""

        async def resolve_workspace_agent(workspace_id: str) -> _RosterRow:
            return _RosterRow()

        assert isinstance(resolve_workspace_agent, WorkspaceAgentResolver)


class TestReconcilerSeam:
    async def test_builds_the_canonical_reconciler_over_the_callers_store(
        self, skill_registry, system_registry
    ) -> None:
        engine = DesignEngine(
            skill_registry=skill_registry,
            system_registry=system_registry,
            reconciler_factory=_canonical_factory,
        )
        run_store = _run_store()

        reconciler = engine.get_reconciler(run_store)

        assert isinstance(reconciler, AttemptLifecycleReconciler)

    async def test_event_sink_is_forwarded(self, skill_registry, system_registry) -> None:
        seen: dict[str, object] = {}

        def factory(
            run_store: InMemoryRunStore, *, event_sink: object | None = None
        ) -> AttemptLifecycleReconciler:
            seen["store"] = run_store
            seen["sink"] = event_sink
            return AttemptLifecycleReconciler(run_store, events=event_sink)

        engine = DesignEngine(
            skill_registry=skill_registry,
            system_registry=system_registry,
            reconciler_factory=factory,
        )
        run_store = _run_store()
        sink = _RecordingEventSink()

        engine.get_reconciler(run_store, event_sink=sink)

        assert seen["store"] is run_store
        assert seen["sink"] is sink

    def test_the_canonical_factory_shape_satisfies_the_protocol(self) -> None:
        """The production wiring shape — a plain callable taking the run store
        positionally and the event sink as a keyword — satisfies the seam."""
        assert isinstance(_canonical_factory, ReconcilerFactory)
        assert not isinstance(object(), ReconcilerFactory)  # not callable at all
