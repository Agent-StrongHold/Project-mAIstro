"""Acceptance regressions for canonical admitted-Run claim recovery (#544)."""

from __future__ import annotations

import contextlib
from typing import ClassVar

from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.runs.model import RunStatus
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


async def test_ineligible_head_rows_do_not_starve_eligible_work_behind_limit(
) -> None:
    """`limit` bounds executions, not how many oldest QUEUED rows may be inspected.

    This is the #544 regression: the old consumer asks the store for exactly
    `limit` oldest QUEUED rows and filters eligibility afterwards. Once those
    rows are permanently ineligible, every tick sees the same prefix forever.
    """
    _EligibleNode.calls = 0
    container = await _container()
    limit = 3

    # Fill the oldest bounded window with work this consumer deliberately does
    # not own. These rows must remain QUEUED, but they must not form a wall.
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
    """Rows intentionally waiting for durable Graph traversal cannot starve schedules."""
    _EligibleNode.calls = 0
    container = await _container()
    limit = 2

    waiting = [
        await _admit(container, workspace=f"multi-{index}", nodes=2)
        for index in range(limit)
    ]
    eligible = await _admit(container, workspace="eligible-after-multi")

    assert await container.execute_admitted_runs(limit=limit) == 1
    assert _EligibleNode.calls == 1
    run = await container.run_store.get_run(eligible)
    assert run is not None and run.status is RunStatus.COMPLETED
    for run_id in waiting:
        parked = await container.run_store.get_run(run_id)
        assert parked is not None and parked.status is RunStatus.QUEUED
