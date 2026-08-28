"""The canonical consumer executes admitted Runs nobody else drives (#251).

A schedule Run's admission is its submission; without the consumer tick it sat
QUEUED forever. These tests prove the tick executes exactly the eligible work:
QUEUED, allowlisted source, one registered node — and nothing else, because
CREATED is a legitimate resting state for Runs that must never execute here.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.runs.model import RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig


class _TickIn(BaseModel):
    greeting: str = "hello"


class _TickOut(BaseModel):
    text: str


class _TickNode(BaseNode[_TickIn, _TickOut]):
    kind: ClassVar[str] = "test.consumer.tick"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _TickIn
    output_schema: ClassVar[type[BaseModel]] = _TickOut
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _TickIn, ctx: NodeContext) -> _TickOut:
        type(self).calls += 1
        return _TickOut(text=inputs.greeting.upper())


class _BoomTickNode(BaseNode[_TickIn, _TickOut]):
    kind: ClassVar[str] = "test.consumer.boom"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _TickIn
    output_schema: ClassVar[type[BaseModel]] = _TickOut

    async def _execute(self, inputs: _TickIn, ctx: NodeContext) -> _TickOut:
        raise RuntimeError("scheduled work blew up")


for _cls in (_TickNode, _BoomTickNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _admit_schedule_run(
    container: Container,
    *,
    kind: str = _TickNode.kind,
    nodes: int = 1,
    source: str | None = SCHEDULE_SOURCE,
    status: RunStatus = RunStatus.QUEUED,
    inputs: dict[str, Any] | None = None,
    workspace: str = "consumer-ws",
) -> str:
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="scheduled work",
        nodes=[Node(node_id=f"n{i}", node_type=kind) for i in range(1, nodes + 1)],
    )
    provenance: dict[str, Any] = {}
    if source is not None:
        provenance[ADMISSION_SOURCE] = source
    if inputs is not None:
        provenance[SCHEDULE_INPUTS_KEY] = inputs
    run = await container.run_store.create_run(
        graph,
        provenance=provenance,
        initial_status=status,
    )
    return run.run_id


@pytest.mark.ac("ADR-082826-b601/AC-1")
async def test_admitted_schedule_run_executes_to_completion() -> None:
    """The whole point of #251: admitted work is executed, canonically."""
    _TickNode.calls = 0
    container = await _container()
    run_id = await _admit_schedule_run(container, inputs={"greeting": "scheduled"})

    executed = await container.execute_admitted_runs()

    assert executed == 1
    assert _TickNode.calls == 1
    run = await container.run_store.get_run(run_id)
    assert run is not None
    # Derived from the NodeRun (ADR-082526-237d), not asserted by the consumer.
    assert run.status is RunStatus.COMPLETED
    (node_run,) = await container.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.COMPLETED
    # The schedule's configured payload reached the node.
    assert node_run.result == {"text": "SCHEDULED"}
    (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
    assert attempt.status.value == "completed"


@pytest.mark.ac("ADR-082826-b601/AC-2")
async def test_ineligible_runs_are_never_claimed() -> None:
    """CREATED, foreign-source, and multi-node Runs stay exactly as admitted."""
    _TickNode.calls = 0
    container = await _container()
    created = await _admit_schedule_run(container, status=RunStatus.CREATED, workspace="ws-created")
    foreign = await _admit_schedule_run(container, source="task_queue", workspace="ws-foreign")
    unsourced = await _admit_schedule_run(container, source=None, workspace="ws-none")
    multi = await _admit_schedule_run(container, nodes=2, workspace="ws-multi")

    executed = await container.execute_admitted_runs()

    assert executed == 0
    assert _TickNode.calls == 0
    for run_id, expected in (
        (created, RunStatus.CREATED),
        (foreign, RunStatus.QUEUED),
        (unsourced, RunStatus.QUEUED),
        (multi, RunStatus.QUEUED),
    ):
        run = await container.run_store.get_run(run_id)
        assert run is not None
        assert run.status is expected
        assert await container.run_store.list_node_runs(run_id) == []


@pytest.mark.ac("ADR-082826-b601/AC-3")
async def test_failed_scheduled_work_parks_and_is_not_silently_retried() -> None:
    """A failed physical try is the recovery disposition's parked row."""
    container = await _container()
    run_id = await _admit_schedule_run(container, kind=_BoomTickNode.kind)

    assert await container.execute_admitted_runs() == 1

    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.WAITING
    (node_run,) = await container.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.WAITING
    (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
    assert attempt.status.value == "failed"

    # Parked is not QUEUED: the next tick must not invent a retry decision.
    assert await container.execute_admitted_runs() == 0
    assert len(await container.run_store.list_node_runs(run_id)) == 1


@pytest.mark.ac("ADR-082826-b601/AC-4")
async def test_concurrent_ticks_execute_each_run_once() -> None:
    """The QUEUED→RUNNING transition is the claim; the loser skips."""
    _TickNode.calls = 0
    container = await _container()
    run_id = await _admit_schedule_run(container)

    first, second = await asyncio.gather(
        container.execute_admitted_runs(),
        container.execute_admitted_runs(),
    )

    assert first + second == 1
    assert _TickNode.calls == 1
    assert len(await container.run_store.list_node_runs(run_id)) == 1


@pytest.mark.ac("ADR-082826-b601/AC-4")
async def test_the_tick_is_idempotent_once_the_backlog_is_drained() -> None:
    container = await _container()
    await _admit_schedule_run(container)
    assert await container.execute_admitted_runs() == 1
    assert await container.execute_admitted_runs() == 0


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.CREATED])
async def test_list_by_status_returns_only_that_status_oldest_first(
    spine: Any, status: RunStatus
) -> None:
    store, workspace_id, project_id = spine
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type=_TickNode.kind)],
    )
    older = await store.create_run(graph, initial_status=status)
    newer = await store.create_run(graph, initial_status=status)
    other_status = RunStatus.CREATED if status is RunStatus.QUEUED else RunStatus.QUEUED
    await store.create_run(graph, initial_status=other_status)

    listed = await store.list_by_status(status, limit=10)

    assert [run.run_id for run in listed[:2]] == [older.run_id, newer.run_id]
    assert all(run.status is status for run in listed)
    limited = await store.list_by_status(status, limit=1)
    assert [run.run_id for run in limited] == [older.run_id]


@pytest.mark.ac("ADR-082826-b601/AC-6")
async def test_list_by_status_conformance_on_the_reference_store(memory_spine: Any) -> None:
    """The AC evidence pin for the discovery surface; `spine` covers the durable
    backends above, but its postgres leg may skip and a skipped leg is no
    evidence, so the criterion is marked on the store with no environment gate."""
    store, workspace_id, project_id = memory_spine
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type=_TickNode.kind)],
    )
    older = await store.create_run(graph, initial_status=RunStatus.QUEUED)
    newer = await store.create_run(graph, initial_status=RunStatus.QUEUED)
    await store.create_run(graph, initial_status=RunStatus.CREATED)

    listed = await store.list_by_status(RunStatus.QUEUED, limit=10)
    assert [run.run_id for run in listed] == [older.run_id, newer.run_id]
    assert await store.list_by_status(RunStatus.QUEUED, limit=1) == listed[:1]
