"""A graph retry consults the canonical effect contract before re-dispatching (#42, #1194).

A graph retry budget is a promise about *logical* visits, not about *physical*
work. When a node's external effect dies ambiguously — the dispatch landed but
the outcome was never observed — the durable executor must still mint fresh,
chronological NodeRun/Attempt identities for each visit, and the physical
dispatch must be arbitrated by the one canonical idempotency/effect contract
(``InvocationExecutionService``) keyed by the node's stable logical effect
scope. An ambiguous effect is not blindly re-executed: later visits are
refused with ``UnsafeEffectRetry`` until reconciliation supplies evidence, and
the Run fails truthfully instead of charging the customer twice.

The stable ``effect_scope`` is what makes the contract span NodeRun visits;
the per-visit identities (``node_run_id``, ``attempt_id``) stay chronological
so the persisted Invocation records *which* visit physically dispatched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, RunStatus


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="ws-effect",
        project_id="project-effect",
        node_id="charge",
        capability="external_write",
        provider_name="",
        config={},
        credential_refs=(),
        policy_refs=(),
    )


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _AmbiguousCharge(BaseNode[_In, _Out]):
    """Charges through the canonical contract; the provider dies after dispatch."""

    kind: ClassVar[str] = "test.durable.ambiguous_charge"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(self, service: InvocationExecutionService) -> None:
        self.service = service
        self.dispatches = 0
        self.blocked_visits = 0
        self.dispatch_node_run_id = ""
        self.dispatch_attempt_id = ""

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        async def ambiguous(_provider: _Provider, _request: Any) -> dict[str, Any]:
            self.dispatches += 1
            if not self.dispatch_node_run_id:
                self.dispatch_node_run_id = ctx.node_run_id
                self.dispatch_attempt_id = ctx.attempt_id
            raise ConnectionError("connection lost after dispatch")

        try:
            await self.service.invoke(
                binding=_binding(),
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key="charge:customer-42",
                effect_scope=f"{ctx.run_id}:charge:customer-42",
                request={"amount": 10},
                resolver=_resolver,
                executor=ambiguous,
            )
        except UnsafeEffectRetry:
            self.blocked_visits += 1
            raise
        raise AssertionError("the ambiguous provider never succeeds")


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-effect")
    project = await projects.create(
        workspace_id="ws-effect", parent_project_id=root.project_id, name="Effects"
    )
    return InMemoryRunStore(project_store=projects), "ws-effect", project.project_id


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="ambiguous effect",
        nodes=[
            Node(
                node_id="charge",
                node_type=_AmbiguousCharge.kind,
                policies={"max_attempts": 3},
            )
        ],
        metadata={"entry_node": "charge"},
    )


@pytest.mark.asyncio
async def test_an_ambiguous_effect_is_never_physically_re_dispatched_by_a_graph_retry() -> None:
    run_store, workspace_id, project_id = await _spine()
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    node = _AmbiguousCharge(service)
    graph = _graph(workspace_id, project_id)

    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda _node_id, _graph: node,
        run_id=admitted.run_id,
        run_store=run_store,
    )

    # The graph retry budget produced three chronological visits, each with its
    # own Attempt, and the Run failed truthfully rather than claiming success.
    assert record.status is RunStatus.FAILED
    assert node.dispatches == 1, "the ambiguous external effect ran at most once"
    assert node.blocked_visits == 2, "later visits were refused by the effect contract"
    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.ordinal for item in node_runs] == [1, 2, 3]
    assert [item.status for item in node_runs] == [
        RunStatus.FAILED,
        RunStatus.FAILED,
        RunStatus.FAILED,
    ]
    for node_run in node_runs:
        attempts = await run_store.list_attempts(node_run.node_run_id)
        assert [item.status for item in attempts] == [AttemptStatus.COMPLETED], (
            "each visit is one physically complete try; only the logical outcome differed"
        )

    # The single physical dispatch is recorded once, in UNKNOWN state, under
    # the *first* visit's identities, retrievable through the stable scope.
    history = await store.list_effect(
        run_id=record.run_id,
        node_run_id=node.dispatch_node_run_id,
        binding_id="binding-1",
        effect_key="charge:customer-42",
        effect_scope=f"{record.run_id}:charge:customer-42",
    )
    assert len(history) == 1
    invocation = history[0]
    assert invocation.status is InvocationStatus.UNKNOWN
    assert invocation.node_run_id == node.dispatch_node_run_id
    assert invocation.attempt_id == node.dispatch_attempt_id
    assert invocation.run_id == record.run_id
    assert invocation.effect_scope == f"{record.run_id}:charge:customer-42"
