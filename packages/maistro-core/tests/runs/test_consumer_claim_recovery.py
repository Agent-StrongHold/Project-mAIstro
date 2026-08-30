"""Acceptance regressions for canonical admitted-Run claim recovery (#544)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import ClassVar

from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.runs.consumer_claim import ConsumerClaimLost, ConsumerClaimStore
from maistro.runs.consumption import SCHEDULE_EXECUTOR_ID
from maistro.runs.model import Attempt, AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig


class _In(BaseModel):
    value: str = "ok"


class _Out(BaseModel):
    value: str


class _EligibleNode(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.consumer.claim-recovery"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        del ctx
        type(self).calls += 1
        return _Out(value=inputs.value)


with contextlib.suppress(ValueError):
    register_node(_EligibleNode)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _admit(
    container: Container,
    *,
    workspace: str,
    source: str = SCHEDULE_SOURCE,
    nodes: int = 1,
) -> str:
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="consumer claim recovery",
        nodes=[Node(node_id=f"n{i}", node_type=_EligibleNode.kind) for i in range(nodes)],
    )
    run = await container.run_store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: source},
        initial_status=RunStatus.QUEUED,
    )
    return run.run_id


async def test_ineligible_head_rows_do_not_starve_eligible_work_behind_limit() -> None:
    """`limit` bounds executions, not how many oldest QUEUED rows may be inspected.

    This is the #544 regression: the old consumer asks the store for exactly
    `limit` oldest QUEUED rows and filters eligibility afterwards. Once those
    rows are permanently ineligible, every tick sees the same prefix forever.
    """
    _EligibleNode.calls = 0
    container = await _container()
    limit = 3

    foreign = [
        await _admit(container, workspace=f"foreign-{index}", source="task_queue")
        for index in range(limit)
    ]
    eligible = await _admit(container, workspace="eligible")

    executed = await container.execute_admitted_runs(limit=limit)

    assert executed == 1
    assert _EligibleNode.calls == 1
    eligible_run = await container.run_store.get_run(eligible)
    assert eligible_run is not None and eligible_run.status is RunStatus.COMPLETED
    for run_id in foreign:
        run = await container.run_store.get_run(run_id)
        assert run is not None and run.status is RunStatus.QUEUED


async def test_multinode_head_rows_do_not_starve_eligible_work() -> None:
    """Rows waiting for durable Graph traversal cannot starve schedules."""
    _EligibleNode.calls = 0
    container = await _container()
    limit = 2

    waiting = [
        await _admit(container, workspace=f"multi-{index}", nodes=2) for index in range(limit)
    ]
    eligible = await _admit(container, workspace="eligible-after-multi")

    assert await container.execute_admitted_runs(limit=limit) == 1
    assert _EligibleNode.calls == 1
    run = await container.run_store.get_run(eligible)
    assert run is not None and run.status is RunStatus.COMPLETED
    for run_id in waiting:
        parked = await container.run_store.get_run(run_id)
        assert parked is not None and parked.status is RunStatus.QUEUED


async def _claim(container: Container, run_id: str, *, ttl: timedelta) -> Attempt:
    run = await container.run_store.get_run(run_id)
    assert run is not None
    store = container.run_store
    assert isinstance(store, ConsumerClaimStore)
    node_id = run.graph.materialize().nodes[0].node_id
    claim = await store.claim_consumer_run(
        run_id,
        node_id=node_id,
        runtime_id="test-runtime",
        executor_id=SCHEDULE_EXECUTOR_ID,
        lease_ttl=ttl,
    )
    return claim.attempt


async def test_claim_is_run_node_and_leased_attempt_together() -> None:
    container = await _container()
    run_id = await _admit(container, workspace="leased-claim")
    attempt = await _claim(container, run_id, ttl=timedelta(seconds=30))
    run = await container.run_store.get_run(run_id)
    node_runs = await container.run_store.list_node_runs(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    assert len(node_runs) == 1 and node_runs[0].status is RunStatus.RUNNING
    assert attempt.status is AttemptStatus.CREATED
    assert attempt.execution_lease is not None


async def test_hard_death_after_claim_recovers_through_ordinary_tick() -> None:
    container = await _container()
    run_id = await _admit(container, workspace="claim-death")
    attempt = await _claim(container, run_id, ttl=timedelta(seconds=5))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    assert (
        await container.recover_abandoned_attempts(now=lease.expires_at + timedelta(microseconds=1))
        == 1
    )
    settled = await container.run_store.get_attempt(attempt.attempt_id)
    node_run = await container.run_store.get_node_run(attempt.node_run_id)
    run = await container.run_store.get_run(run_id)
    assert settled is not None and settled.status is AttemptStatus.CANCELLED
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


async def test_concurrent_claims_have_one_physical_winner() -> None:
    container = await _container()
    run_id = await _admit(container, workspace="claim-race")
    results = await asyncio.gather(
        _claim(container, run_id, ttl=timedelta(seconds=30)),
        _claim(container, run_id, ttl=timedelta(seconds=30)),
        return_exceptions=True,
    )
    assert sum(isinstance(item, Attempt) for item in results) == 1
    assert sum(isinstance(item, ConsumerClaimLost) for item in results) == 1
    node_runs = await container.run_store.list_node_runs(run_id)
    assert len(node_runs) == 1
    attempts = await container.run_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
