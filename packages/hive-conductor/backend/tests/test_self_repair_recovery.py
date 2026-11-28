"""Recovery ownership of self-repair approval Runs (#2405, audit 2).

An *answered* self-repair approval Run is queued by the canonical HITL door,
and a Run claimed but killed before its first durable checkpoint is stranded
QUEUED with only its launch snapshot. Nothing may stay queued forever: the
shipped recovery cadence must own the ``self_repair`` admission source through
the canonical Graph recovery seams — and only that source. These tests pin
both halves:

- the wiring hands the canonical seams the right stores, the canonical
  recovery Event sink, the ``self_repair`` prefilter, and an ownership
  predicate that accepts exactly the self-repair admissions (executor None is
  the pre-restart admission shape, ``durable_graph`` what admission stamps);
- a stranded crash-window Run is actually recovered end-to-end through the
  shipped tick, while a foreign-sourced QUEUED Run is left for its own owner.

The ownership predicate is a mutation oracle: deleting recovery source
ownership (``_owned`` → ``False``) must fail these tests, or an approved
Run's recovery could be silently dropped and nothing would notice.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.events.envelope import InMemoryEventStore
from maistro.events.publisher import CanonicalEventPublisher
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    durable_graph_launch_provenance,
)
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.runs.model import RunStatus
from maistro.runs.recovery_events import CanonicalRecoveryEventSink
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


class _StepIn(BaseModel):
    marker: str = "m"


class _StepOut(BaseModel):
    text: str


class _StepNode(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.selfrepair_recovery.step"
    kind_category: ClassVar = "transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut
    executed: ClassVar[list[str]] = []

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        type(self).executed.append(ctx.run_id)
        return _StepOut(text="done")


register_node(_StepNode)


def _graph(workspace_id: str, project_id: str, *, source: str) -> Graph:
    return Graph(
        graph_id=f"recovery-fixture:{source}",
        workspace_id=workspace_id,
        project_id=project_id,
        name="self-repair recovery fixture",
        nodes=[
            Node(
                node_id="step",
                node_type=_StepNode.kind,
                inputs={"marker": "m"},
                parameters={},
                metadata={},
            )
        ],
        edges=[],
        metadata={},
    )


def _self_repair_provenance() -> dict[str, Any]:
    return {
        "admission_source": "self_repair",
        "executor": "durable_graph",
        **durable_graph_launch_provenance(inputs={"marker": "m"}),
    }


@pytest.fixture()
async def container(monkeypatch: pytest.MonkeyPatch) -> Any:
    import services.engine as engine_module

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-srr")
    run_store = InMemoryRunStore(project_store=projects)
    providers = InMemoryProviderRegistry()
    built = SimpleNamespace(
        projects=projects,
        run_store=run_store,
        graph_run_store=CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore()),
        event_bus=None,
        canonical_event_publisher=CanonicalEventPublisher(InMemoryEventStore()),
        a2a_delegator=None,
        guest_peers=None,
        capability_effects=None,
        harness_adapters={},
        provider_registry=providers,
        llm_router=CostAwareRouter(providers),
        project_id=root.project_id,
        discovery_context=None,
    )
    port = SimpleNamespace(container=built)
    monkeypatch.setattr(engine_module, "get_engine", lambda: SimpleNamespace(_agent_port=port))
    return built


async def _stranded_run(
    container: Any,
    *,
    provenance: dict[str, Any] | None = None,
) -> str:
    """A canonical Run claimed, then killed before its first durable checkpoint."""
    run = await container.run_store.create_run(
        _graph("ws-srr", container.project_id, source="srr"),
        initial_status=RunStatus.QUEUED,
        actor_principal_id="test-user",
        provenance=provenance if provenance is not None else _self_repair_provenance(),
    )
    return run.run_id


async def test_recovery_owns_self_repair_and_refuses_foreign_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tick hands the canonical seams the self_repair prefilter and predicate."""
    import services.self_repair_recovery as srr

    graph_store = object()
    canonical_run_store = object()
    canonical_events = CanonicalEventPublisher(InMemoryEventStore())
    fake = SimpleNamespace(
        graph_run_store=graph_store,
        run_store=canonical_run_store,
        canonical_event_publisher=canonical_events,
    )
    captured: dict[str, Any] = {}

    async def _recover(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 3

    monkeypatch.setattr(srr, "_container", lambda: fake)
    monkeypatch.setattr(srr, "recover_queued_graph_runs", _recover)
    monkeypatch.setattr(srr, "resume_due_graph_runs", _recover)

    assert await srr.recover_stranded_self_repair_runs(limit=7) == 3
    assert captured["store"] is graph_store
    assert captured["run_store"] is canonical_run_store
    assert captured["limit"] == 7
    assert captured["admission_source"] == "self_repair"
    assert isinstance(captured["events"], CanonicalRecoveryEventSink)
    assert captured["scan"] is not None
    assert captured["node_resolver_factory"] is srr._resolver
    eligible = captured["eligible"]

    captured.clear()
    assert await srr.wake_due_self_repair_runs(limit=5) == 3
    assert captured["store"] is graph_store
    assert captured["run_store"] is canonical_run_store
    assert captured["limit"] == 5
    # The wake seam owns through the predicate alone (no durable prefilter):
    # its timer/lease scan is shared, and `_owned` is the policy check.
    assert "admission_source" not in captured
    assert isinstance(captured["events"], CanonicalRecoveryEventSink)
    assert captured["scan"] is not None

    # The ownership predicate: exactly the self-repair admissions, in both
    # shipped executor shapes, and nothing else.
    def _run_with(provenance: dict[str, Any]) -> Any:
        graph = _graph("ws-srr", "project-srr", source="ownership")
        return SimpleNamespace(
            run_id="r",
            provenance=provenance,
            graph=SimpleNamespace(materialize=lambda: graph),
        )

    assert eligible(_run_with({"admission_source": "self_repair"})) is True
    assert eligible(_run_with({"admission_source": "self_repair", "executor": "durable_graph"}))
    assert eligible(_run_with({"admission_source": "schedule"})) is False
    assert eligible(_run_with({"admission_source": "hive_legacy_dag"})) is False
    assert eligible(_run_with({"admission_source": "evolve"})) is False
    assert eligible(_run_with({})) is False
    assert (
        eligible(_run_with({"admission_source": "self_repair", "executor": "someone_else"}))
        is False
    )


async def test_stranded_self_repair_run_is_recovered_and_foreign_run_is_not(
    container: Any,
) -> None:
    """The shipped tick resumes the stranded crash-window Run; nobody else's."""
    owned = await _stranded_run(container)
    foreign = await _stranded_run(
        container,
        provenance={"admission_source": "schedule", "executor": "durable_graph"},
    )
    _StepNode.executed.clear()

    from services.self_repair_recovery import recover_stranded_self_repair_runs

    recovered = await recover_stranded_self_repair_runs()
    assert recovered == 1

    status = await container.run_store.get_run(owned)
    assert status is not None
    assert status.status is RunStatus.COMPLETED
    assert _StepNode.executed == [owned]

    # A foreign-sourced QUEUED Run stays QUEUED: its owner must recover it.
    untouched = await container.run_store.get_run(foreign)
    assert untouched is not None
    assert untouched.status is RunStatus.QUEUED

    # The recovery is idempotent: a second tick recovers nothing further.
    assert await recover_stranded_self_repair_runs() == 0
