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

    scoped = await store.list_by_status(status, limit=10, project_id=project_id)
    assert [run.run_id for run in scoped[:2]] == [older.run_id, newer.run_id]
    assert await store.list_by_status(status, limit=10, project_id="project-elsewhere") == []
    with pytest.raises(ValueError):
        await store.list_by_status(status, limit=0)


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


# --- the tick's failure arms -------------------------------------------------


class _UnbuildableTickNode(BaseNode[_TickIn, _TickOut]):
    """Registered, so eligibility passes — but construction needs wiring the
    consumer does not have. Resolving it is the infrastructure failure that
    happens before any NodeRun exists."""

    kind: ClassVar[str] = "test.consumer.unbuildable"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _TickIn
    output_schema: ClassVar[type[BaseModel]] = _TickOut

    def __init__(self) -> None:
        raise RuntimeError("this kind needs wiring the consumer does not carry")

    async def _execute(self, inputs: _TickIn, ctx: NodeContext) -> _TickOut:
        raise AssertionError("never constructed")


class _RawOutTickNode(BaseNode[_TickIn, _TickOut]):
    """Hands back a plain-dict output — legal per NodeResult — so consumption
    must persist it as-is rather than assuming a model_dump."""

    kind: ClassVar[str] = "test.consumer.rawout"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _TickIn
    output_schema: ClassVar[type[BaseModel]] = _TickOut

    async def _execute(self, inputs: _TickIn, ctx: NodeContext) -> _TickOut:
        return _TickOut(text="ignored")

    async def run(self, inputs: Any, ctx: NodeContext) -> Any:
        result = await super().run(inputs, ctx)
        return result.model_copy(update={"output": {"text": "raw"}})


for _extra in (_UnbuildableTickNode, _RawOutTickNode):
    with contextlib.suppress(ValueError):
        register_node(_extra)


class _Proxy:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def test_a_lost_claim_is_skipped_rather_than_failed() -> None:
    """The QUEUED→RUNNING mutex race from the loser's side: skip, touch nothing."""
    container = await _container()
    run_id = await _admit_schedule_run(container)

    class _ClaimVeto(_Proxy):
        async def transition_run(self, run_id: str, target: RunStatus, **kwargs: Any) -> Any:
            if target is RunStatus.RUNNING:
                raise RuntimeError("claimed by a concurrent tick")
            return await self._inner.transition_run(run_id, target, **kwargs)

    container.run_store = _ClaimVeto(container.run_store)  # type: ignore[assignment]

    assert await container.execute_admitted_runs() == 0

    run = await container.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.QUEUED
    assert await container.run_store.list_node_runs(run_id) == []


async def test_infrastructure_failure_before_any_record_fails_the_claimed_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Execution dying before a NodeRun exists must not leave a RUNNING Run
    indistinguishable from a crashed process: it terminalizes as FAILED."""
    import logging

    container = await _container()
    run_id = await _admit_schedule_run(container, kind=_UnbuildableTickNode.kind)

    with caplog.at_level(logging.WARNING):
        executed = await container.execute_admitted_runs()

    assert executed == 1
    assert "failed during consumption" in caplog.text
    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error == "consumption_error"
    assert await container.run_store.list_node_runs(run_id) == []


async def test_settlement_respects_a_run_that_left_records() -> None:
    """With a NodeRun present, the parked/derived state is already the answer."""
    container = await _container()
    run_id = await _admit_schedule_run(container)
    assert await container.execute_admitted_runs() == 1

    await container._settle_unstarted_consumption(run_id)

    run = await container.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED


async def test_settlement_failure_is_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    container = await _container()

    class _BrokenList(_Proxy):
        async def list_node_runs(self, run_id: str) -> Any:
            raise RuntimeError("store down")

    container.run_store = _BrokenList(container.run_store)  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING):
        await container._settle_unstarted_consumption("run-x")

    assert "could not be settled" in caplog.text


# --- the executor's own guards ----------------------------------------------


async def test_a_nonpositive_timeout_is_refused() -> None:
    from maistro.runs.consumption import ScheduleAttemptExecutor

    container = await _container()
    with pytest.raises(ValueError):
        ScheduleAttemptExecutor(container.run_store, timeout_s=0)


async def test_multi_node_run_is_refused_by_the_executor() -> None:
    from maistro.runs.consumption import ScheduleAttemptExecutor
    from maistro.runs.store import RunIntegrityError

    container = await _container()
    run_id = await _admit_schedule_run(container, nodes=2, workspace="ws-direct-multi")
    run = await container.run_store.get_run(run_id)
    assert run is not None

    with pytest.raises(RunIntegrityError):
        await ScheduleAttemptExecutor(container.run_store).execute(run)


async def test_a_run_that_disappears_mid_consumption_is_an_integrity_error() -> None:
    """Purged or archived out from under the consumer between the node's work
    and the read-back: an integrity error, never an invented answer."""
    from maistro.runs.consumption import ScheduleAttemptExecutor
    from maistro.runs.model import TERMINAL_RUN_STATUSES
    from maistro.runs.store import RunIntegrityError

    container = await _container()
    run_id = await _admit_schedule_run(container, workspace="ws-vanish")
    claimed = await container.run_store.transition_run(run_id, RunStatus.RUNNING)

    class _Vanishing(_Proxy):
        async def get_run(self, run_id: str) -> Any:
            run = await self._inner.get_run(run_id)
            if run is not None and run.status in TERMINAL_RUN_STATUSES:
                return None
            return run

    with pytest.raises(RunIntegrityError):
        await ScheduleAttemptExecutor(_Vanishing(container.run_store)).execute(claimed)


async def test_plain_dict_output_is_persisted_as_given() -> None:
    container = await _container()
    run_id = await _admit_schedule_run(container, kind=_RawOutTickNode.kind)

    assert await container.execute_admitted_runs() == 1

    (node_run,) = await container.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.result == {"text": "raw"}


async def test_created_runs_are_ineligible_even_when_offered_directly() -> None:
    from maistro.runs.consumption import executable_by_consumer

    container = await _container()
    run_id = await _admit_schedule_run(
        container, status=RunStatus.CREATED, workspace="ws-direct-created"
    )
    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert executable_by_consumer(run) is False


# --- #251 criterion 2: owned work this process can never run must not sit ----


async def test_a_run_naming_an_unregistered_kind_fails_visibly() -> None:
    """#251's second criterion. Eligibility used to exclude an unresolvable
    kind *before* the claim, so the Run was never touched and sat QUEUED
    forever — durable state claiming work nobody would ever do, which is the
    defect the consumer exists to remove."""
    from maistro.runs.consumption import UNRESOLVABLE_NODE_KIND

    container = await _container()
    run_id = await _admit_schedule_run(
        container, kind="test.consumer.never_registered", workspace="ws-unresolvable"
    )

    executed = await container.execute_admitted_runs()

    assert executed == 0  # nothing ran; the Run was disposed of, not executed
    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error is not None
    assert UNRESOLVABLE_NODE_KIND in run.error
    assert "test.consumer.never_registered" in run.error


async def test_a_multi_node_run_still_waits_rather_than_failing() -> None:
    """ "Not yet" is not "never": traversal (#44/#34) will run this one, so
    failing it here would destroy work that is legitimately owed."""
    container = await _container()
    run_id = await _admit_schedule_run(container, nodes=2, workspace="ws-multi-waits")

    assert await container.execute_admitted_runs() == 0

    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.QUEUED


async def test_an_unowned_run_with_an_unregistered_kind_is_left_alone() -> None:
    """Disposal is only for Runs this consumer owns. A foreign admission
    source keeps its Run, unresolvable here or not."""
    container = await _container()
    run_id = await _admit_schedule_run(
        container,
        kind="test.consumer.never_registered",
        source="task_queue",
        workspace="ws-foreign-unresolvable",
    )

    assert await container.execute_admitted_runs() == 0

    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.QUEUED


async def test_two_ticks_do_not_both_dispose_of_one_unresolvable_run() -> None:
    """The claim is the mutex for disposal exactly as it is for execution."""
    container = await _container()
    run_id = await _admit_schedule_run(
        container, kind="test.consumer.never_registered", workspace="ws-unresolvable-race"
    )

    await asyncio.gather(
        container.execute_admitted_runs(),
        container.execute_admitted_runs(),
    )

    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED


async def test_a_disposal_that_loses_its_claim_is_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The concurrent-disposal case from the losing side.

    Two ticks can only race here when the second still sees the Run listed;
    once the first has disposed of it, the second's claim is refused by the
    lifecycle table. That refusal is normal, not an error to propagate — a
    tick that lost is finished, and the Run is already in the state it wanted.
    """
    import logging

    container = await _container()
    run_id = await _admit_schedule_run(
        container, kind="test.consumer.never_registered", workspace="ws-lost-disposal"
    )
    # Dispose of it, exactly as the winning tick would.
    await container._fail_unresolvable_run(run_id, "unresolvable_node_kind: x")

    with caplog.at_level(logging.WARNING):
        await container._fail_unresolvable_run(run_id, "unresolvable_node_kind: x")

    assert "could not be settled" in caplog.text
    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
