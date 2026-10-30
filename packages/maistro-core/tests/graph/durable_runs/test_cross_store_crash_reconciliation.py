"""A crash between the continuation write and the canonical mirror (#1151).

`CanonicalDurableRunStore.update` writes the Graph continuation first and then
mirrors its lifecycle onto the spine. A process that dies in between leaves the
continuation terminal (or, at the resume claim, QUEUED) while the canonical Run
still reads RUNNING -- a Run nothing else will ever settle or resume, because
the due index only sees continuations whose own status is recoverable. These
drive the real executor into each window and assert the reconcile the due and
queued ticks already run repairs it from durable facts alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
import pytest
from pydantic import BaseModel

from maistro.graph import Edge, Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
    recover_queued_graph_runs,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.durable_runs import canonical_store as canonical_store_module
from maistro.graph.durable_runs.canonical_store import TERMINAL_SETTLE_QUIET_PERIOD
from maistro.graph.durable_runs.continuation import GraphContinuation, GraphContinuationStore
from maistro.graph.durable_runs.spine import mirror_node_run
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.graph.nodes.base import PAUSE_AWAITING_HARNESS, now_utc, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.lifecycle import transition_run
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import RunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = [pytest.mark.contract("behavioral")]

_WORKSPACE = "ws-cross-store-crash"
_UNPERSISTED = "original error not persisted"


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Step(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.cross_store_crash.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out()


class _Fails(_Step):
    kind: ClassVar[str] = "test.cross_store_crash.fails"

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        raise ValueError("domain failure")


class _InjectedCrash(BaseException):
    """Not an `Exception`, so no executor boundary can absorb the crash."""


def _settling_now(
    run_store: RunStore, continuations: GraphContinuationStore
) -> CanonicalDurableRunStore:
    """A store whose quiet period has already elapsed for every crash below."""
    return CanonicalDurableRunStore(
        run_store, continuations, terminal_settle_quiet_period=timedelta(0)
    )


@dataclass
class _Spine:
    run_store: RunStore
    continuations: GraphContinuationStore
    store: CanonicalDurableRunStore
    project_id: str


#: Room for the 300-Run backlog one case seeds ahead of a stranded Run; the
#: governed root-Run ceiling (#1182) is not what these cases test.
_BACKLOG_LIMITS = RunConcurrencyLimits(per_workspace=512)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def spine(
    request: pytest.FixtureRequest, tmp_path: Path, pg_pool: Any
) -> AsyncIterator[_Spine]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Crash windows"
    )
    if request.param == "sqlite":
        from maistro.runs.sqlite_store import SqliteRunStore

        async with aiosqlite.connect(tmp_path / "spine.db") as conn:
            sqlite_runs = SqliteRunStore(
                conn, project_store=projects, concurrency_limits=_BACKLOG_LIMITS
            )
            await sqlite_runs.ensure_schema()
            sqlite_continuations = SqliteGraphContinuationStore(conn)
            await sqlite_continuations.ensure_schema()
            yield _Spine(
                sqlite_runs,
                sqlite_continuations,
                _settling_now(sqlite_runs, sqlite_continuations),
                project.project_id,
            )
        return
    continuations: GraphContinuationStore
    if request.param == "memory":
        continuations = InMemoryGraphContinuationStore()
    else:
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore

        continuations = PgGraphContinuationStore(pg_pool)
    run_store = InMemoryRunStore(project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
    yield _Spine(
        run_store,
        continuations,
        _settling_now(run_store, continuations),
        project.project_id,
    )


def _graph(spine: _Spine, node: BaseNode[Any, Any], name: str = "crash window") -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=spine.project_id,
        name=name,
        nodes=[Node(node_id="step", node_type=node.kind, policies={"max_attempts": 1})],
    )


_Rewrite = Callable[[DurableRunRecord], Awaitable[DurableRunRecord]]


async def _crash_at_terminal_write(
    spine: _Spine,
    node: BaseNode[Any, Any],
    *,
    rewrite: _Rewrite | None = None,
    mirror_node_runs: bool = False,
) -> str:
    """Run a graph to its terminal checkpoint and die after the continuation write.

    ``mirror_node_runs`` places the crash one step later, between the NodeRun
    mirror and the Run mirror -- the two halves of `mirror_lifecycle`.
    """
    graph = _graph(spine, node)
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    real_update = spine.store.update

    async def crashing_update(record: DurableRunRecord) -> DurableRunRecord:
        if record.run.status not in TERMINAL_RUN_STATUSES:
            return await real_update(record)
        written = record if rewrite is None else await rewrite(record)
        await spine.continuations.update(GraphContinuation.of(written))
        if mirror_node_runs:
            for node_run in written.node_runs:
                await mirror_node_run(node_run, run_store=spine.run_store)
        raise _InjectedCrash

    spine.store.update = crashing_update  # type: ignore[method-assign]
    try:
        with pytest.raises(_InjectedCrash):
            await run_durable_graph(
                graph,
                store=spine.store,
                node_resolver=lambda node_id, current: node,
                run_id=admitted.run_id,
                run_store=spine.run_store,
                actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            )
    finally:
        spine.store.update = real_update  # type: ignore[method-assign]
    stranded = await spine.run_store.get_run(admitted.run_id)
    assert stranded is not None and stranded.status is RunStatus.RUNNING
    return admitted.run_id


async def _assert_settled(spine: _Spine, run_id: str, status: RunStatus) -> DurableRunRecord:
    assert await spine.store.reconcile_persistence() == 1
    record = await spine.store.get(run_id)
    assert record is not None
    assert record.run.status is status
    assert record.node_runs
    assert all(item.status in TERMINAL_RUN_STATUSES for item in record.node_runs)
    assert await spine.store.reconcile_persistence() == 0
    return record


@pytest.mark.parametrize("publication_fails", [False, True])
async def test_checkpoint_repair_emits_a_replayable_canonical_event(
    spine: _Spine, publication_fails: bool
) -> None:
    from maistro.events.envelope import InMemoryEventStore
    from maistro.runs.recovery_events import CanonicalEventStoreSink, CanonicalRecoveryEventSink

    # Older terminal history must not hide a pending append on a later Run.
    for _ in range(3):
        graph = _graph(spine, _Step())
        admitted = await spine.run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        await run_durable_graph(
            graph,
            store=spine.store,
            run_store=spine.run_store,
            run_id=admitted.run_id,
            node_resolver=lambda *_: _Step(),
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
    run_id = await _crash_at_terminal_write(spine, _Step())
    event_store = InMemoryEventStore()
    canonical = CanonicalRecoveryEventSink(spine.run_store, CanonicalEventStoreSink(event_store))

    class _Sink:
        async def emit(self, event: Any) -> Any:
            # Publication is never allowed to claim a repair before it committed.
            assert (await spine.run_store.get_run(run_id)).status is RunStatus.COMPLETED
            if publication_fails:
                raise RuntimeError("event store offline")
            return await canonical.emit(event)

    recovering = CanonicalDurableRunStore(
        spine.run_store,
        spine.continuations,
        terminal_settle_quiet_period=timedelta(0),
        events=_Sink(),
    )
    if publication_fails:
        with pytest.raises(RuntimeError, match="event store offline"):
            await recovering.reconcile_run(run_id)
        assert (await spine.run_store.get_run(run_id)).status is RunStatus.COMPLETED
    else:
        assert await recovering.reconcile_run(run_id)
        events = await event_store.list_stream(f"workspace:{_WORKSPACE}")
        assert len(events) == 1
    # Fresh store: a failed emit cannot disappear with the repairing process.
    restarted = CanonicalDurableRunStore(spine.run_store, spine.continuations, events=canonical)
    for _ in range(10):
        assert await restarted.reconcile_persistence(limit=1) == 0
    events = await event_store.list_stream(f"workspace:{_WORKSPACE}")
    assert len(events) == 1
    assert events[0].sequence == 1
    assert events[0].run_id == run_id
    assert events[0].type == "run.recovery_disposition"
    assert "terminal_graph" in events[0].payload["disposition"]


async def _parked_on_a_person(spine: _Spine) -> str:
    """A canonical PAUSED Run with no waker: the sweep's permanent prefix."""
    graph = _graph(spine, _Step(), name="parked on a person")
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await spine.store.create(
        DurableRunRecord(
            run=admitted,
            graph_state=GraphExecutionState(
                run_id=admitted.run_id,
                active_node_ids=("step",),
                metadata={"initial_inputs": {}, "hitl_answers": {}},
            ),
        )
    )
    await spine.run_store.transition_run(admitted.run_id, RunStatus.RUNNING)
    await spine.run_store.transition_run(admitted.run_id, RunStatus.PAUSED)
    return admitted.run_id


@pytest.mark.asyncio
async def test_a_persistent_paused_run_cannot_starve_terminal_event_discovery(
    spine: _Spine,
) -> None:
    """A Run parked forever must not consume every tick's budget.

    The failed publication leaves re-publishable residue behind a settled
    spine. A canonical PAUSED Run never leaves the store, so a from-the-top
    paused scan re-offers it on every tick and -- at limit=1 -- the
    continuation-status buckets that carry the retry discovery never run.
    The paused page must rotate its turn like the RUNNING page does.
    """
    from maistro.events.envelope import InMemoryEventStore
    from maistro.runs.recovery_events import CanonicalEventStoreSink, CanonicalRecoveryEventSink

    run_id = await _crash_at_terminal_write(spine, _Step())
    person = await _parked_on_a_person(spine)
    events = InMemoryEventStore()
    canonical = CanonicalRecoveryEventSink(spine.run_store, CanonicalEventStoreSink(events))

    class _Sink:
        async def emit(self, event: Any) -> Any:
            raise RuntimeError("event store offline")

    recovering = CanonicalDurableRunStore(
        spine.run_store,
        spine.continuations,
        terminal_settle_quiet_period=timedelta(0),
        events=_Sink(),
    )
    with pytest.raises(RuntimeError, match="event store offline"):
        await recovering.reconcile_run(run_id)
    assert (await spine.run_store.get_run(run_id)).status is RunStatus.COMPLETED

    # Fresh store: the residue must stay discoverable behind parked work.
    restarted = CanonicalDurableRunStore(spine.run_store, spine.continuations, events=canonical)
    for _ in range(10):
        await restarted.reconcile_persistence(limit=1)
    record = await restarted.get(run_id)
    assert record is not None and record.run.status is RunStatus.COMPLETED
    parked = await spine.run_store.get_run(person)
    assert parked is not None and parked.status is RunStatus.PAUSED
    published = await events.list_stream(f"workspace:{_WORKSPACE}")
    assert len(published) == 1
    assert published[0].run_id == run_id
    assert published[0].type == "run.recovery_disposition"


async def test_checkpoint_repair_intent_cannot_publish_before_the_spine_commits(
    spine: _Spine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.events.envelope import InMemoryEventStore
    from maistro.runs.recovery_events import CanonicalEventStoreSink, CanonicalRecoveryEventSink

    run_id = await _crash_at_terminal_write(spine, _Step())
    events = InMemoryEventStore()
    sink = CanonicalRecoveryEventSink(spine.run_store, CanonicalEventStoreSink(events))
    recovering = CanonicalDurableRunStore(
        spine.run_store,
        spine.continuations,
        terminal_settle_quiet_period=timedelta(0),
        events=sink,
    )
    real_mirror = canonical_store_module.mirror_lifecycle

    async def crash_before_spine(*args: Any, **kwargs: Any) -> None:
        raise _InjectedCrash

    monkeypatch.setattr(canonical_store_module, "mirror_lifecycle", crash_before_spine)
    with pytest.raises(_InjectedCrash):
        await recovering.reconcile_run(run_id)
    assert (await spine.run_store.get_run(run_id)).status is RunStatus.RUNNING
    assert await events.list_stream(f"workspace:{_WORKSPACE}") == []
    monkeypatch.setattr(canonical_store_module, "mirror_lifecycle", real_mirror)
    assert await recovering.reconcile_run(run_id)
    assert len(await events.list_stream(f"workspace:{_WORKSPACE}")) == 1


async def test_a_completed_continuation_settles_its_running_run_with_the_node_result(
    spine: _Spine,
) -> None:
    run_id = await _crash_at_terminal_write(spine, _Step())

    record = await _assert_settled(spine, run_id, RunStatus.COMPLETED)

    assert record.run.result == {"text": "done"}
    assert record.run.error is None
    assert [item.status for item in record.node_runs] == [RunStatus.COMPLETED]


async def test_a_failed_continuation_whose_error_was_lost_settles_with_a_truthful_error(
    spine: _Spine,
) -> None:
    """The crash beat every mirror: the node's error lived only in the lost write."""
    run_id = await _crash_at_terminal_write(spine, _Fails())

    record = await _assert_settled(spine, run_id, RunStatus.FAILED)

    assert record.run.error is not None
    assert "settled failed before canonical settlement" in record.run.error
    assert _UNPERSISTED in record.run.error
    [node_run] = record.node_runs
    assert node_run.status is RunStatus.CANCELLED


async def test_a_mirrored_node_error_is_not_passed_off_as_the_runs_lost_cause(
    spine: _Spine,
) -> None:
    """The NodeRuns were mirrored, the Run was not, and its cause was the Run's own.

    A halt, an exhausted step budget or a cancellation is written only on the
    Run, and `first_exhausted_failure` need not pick the NodeRun a re-derivation
    would. The node's error is evidence about the node, so it stays there and
    the Run says its own error was lost.
    """

    async def halted(record: DurableRunRecord) -> DurableRunRecord:
        running = await spine.run_store.get_run(record.run_id)
        assert running is not None
        run = transition_run(running, RunStatus.FAILED, error="HaltRequested: operator stop")
        return record.model_copy(update={"run": run})

    run_id = await _crash_at_terminal_write(spine, _Fails(), rewrite=halted, mirror_node_runs=True)

    record = await _assert_settled(spine, run_id, RunStatus.FAILED)

    assert record.run.error is not None
    assert "settled failed before canonical settlement" in record.run.error
    assert _UNPERSISTED in record.run.error
    [node_run] = record.node_runs
    assert node_run.status is RunStatus.FAILED
    assert node_run.error == "ValueError: domain failure"


async def test_a_terminal_write_newer_than_a_quiet_spine_waits_out_the_period(
    spine: _Spine,
) -> None:
    """A spine can look quiet while its walker has only just written terminal.

    A node that ran past the quiet period and then raised leaves nothing on the
    spine newer than its Attempt's start. Only a terminal version this store has
    seen unchanged for the whole period is treated as crash residue.
    """
    run_id = await _crash_at_terminal_write(spine, _Fails(), mirror_node_runs=True)
    patient = CanonicalDurableRunStore(spine.run_store, spine.continuations)
    quiet = datetime.now(UTC) + TERMINAL_SETTLE_QUIET_PERIOD * 2

    assert await patient.reconcile_persistence(now=quiet) == 0
    assert await patient.reconcile_persistence(now=quiet + timedelta(seconds=59)) == 0
    still = await spine.run_store.get_run(run_id)
    assert still is not None and still.status is RunStatus.RUNNING

    assert await patient.reconcile_persistence(now=quiet + TERMINAL_SETTLE_QUIET_PERIOD) == 1
    settled = await spine.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.FAILED


async def test_a_new_terminal_version_restarts_the_observation(spine: _Spine) -> None:
    """The period is per version: a rewrite means a writer is still active."""
    run_id = await _crash_at_terminal_write(spine, _Fails(), mirror_node_runs=True)
    patient = CanonicalDurableRunStore(spine.run_store, spine.continuations)
    quiet = datetime.now(UTC) + TERMINAL_SETTLE_QUIET_PERIOD * 2

    assert await patient.reconcile_persistence(now=quiet) == 0
    continuation = await spine.continuations.get(run_id)
    assert continuation is not None
    await spine.continuations.update(
        continuation.model_copy(update={"version": continuation.version + 1})
    )
    later = quiet + TERMINAL_SETTLE_QUIET_PERIOD
    assert await patient.reconcile_persistence(now=later) == 0
    assert await patient.reconcile_persistence(now=later + TERMINAL_SETTLE_QUIET_PERIOD) == 1


async def test_a_cancelled_continuation_without_hitl_evidence_settles_its_running_run(
    spine: _Spine,
) -> None:
    async def cancelled(record: DurableRunRecord) -> DurableRunRecord:
        running = await spine.run_store.get_run(record.run_id)
        assert running is not None
        return record.model_copy(update={"run": transition_run(running, RunStatus.CANCELLED)})

    run_id = await _crash_at_terminal_write(spine, _Step(), rewrite=cancelled)

    record = await _assert_settled(spine, run_id, RunStatus.CANCELLED)

    assert record.run.error is not None
    assert "settled cancelled before canonical settlement" in record.run.error


async def test_a_lost_race_to_the_same_repair_is_already_repaired(spine: _Spine) -> None:
    """Another replica mirrored first: this tick's terminal hop is refused."""
    run_id = await _crash_at_terminal_write(spine, _Step())
    real_transition = spine.run_store.transition_run

    async def racing_transition(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        await real_transition(run_id, target, **kwargs)
        return await real_transition(run_id, target, **kwargs)

    spine.run_store.transition_run = racing_transition  # type: ignore[method-assign]
    try:
        assert await spine.store.reconcile_persistence() == 0
    finally:
        spine.run_store.transition_run = real_transition  # type: ignore[method-assign]
    settled = await spine.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED


async def _claimed_but_not_running(spine: _Spine, *, claim_until: datetime) -> str:
    """The resume claim persisted QUEUED; the spine then stepped to RUNNING and died."""
    graph = _graph(spine, _Step(), name="claim window")
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await spine.store.create(
        DurableRunRecord(
            run=admitted,
            graph_state=GraphExecutionState(
                run_id=admitted.run_id,
                active_node_ids=("step",),
                metadata={"initial_inputs": {}, "hitl_answers": {}},
            ),
        )
    )
    record = await spine.store.get(admitted.run_id)
    assert record is not None
    claimed = record.model_copy(update={"resume_at": claim_until, "version": record.version + 1})
    await spine.continuations.update(GraphContinuation.of(claimed))
    await spine.run_store.transition_run(admitted.run_id, RunStatus.RUNNING)
    return admitted.run_id


async def test_a_queued_continuation_under_a_running_run_is_resumed_once_its_claim_elapses(
    spine: _Spine,
) -> None:
    now = datetime.now(UTC)
    run_id = await _claimed_but_not_running(spine, claim_until=now - timedelta(minutes=1))

    assert await spine.store.reconcile_persistence() == 1
    continuation = await spine.continuations.get(run_id)
    assert continuation is not None
    assert continuation.status is RunStatus.RUNNING
    assert continuation.resume_at == now - timedelta(minutes=1)
    assert await spine.store.reconcile_persistence() == 0

    resumed = await resume_due_graph_runs(
        store=spine.store,
        run_store=spine.run_store,
        node_resolver=lambda node_id, graph: _Step(),
        now=datetime.now(UTC),
    )

    assert resumed == 1
    finished = await spine.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED


async def test_the_due_tick_alone_recovers_a_queued_continuation_under_a_running_run(
    spine: _Spine,
) -> None:
    """The production tick reconciles before it scans, so nothing else is needed."""
    run_id = await _claimed_but_not_running(
        spine, claim_until=datetime.now(UTC) - timedelta(minutes=1)
    )

    resumed = await resume_due_graph_runs(
        store=spine.store,
        run_store=spine.run_store,
        node_resolver=lambda node_id, graph: _Step(),
        now=datetime.now(UTC),
    )

    assert resumed == 1
    finished = await spine.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED


async def test_a_claim_elapsed_in_the_ticks_own_time_is_resumed_by_that_tick(
    spine: _Spine,
) -> None:
    """Reconciliation judges the claim by the moment the due scan uses.

    Judged by the wall clock instead, a claim already elapsed for the tick
    would stay QUEUED, outside the due index the same tick then reads.
    """
    now = datetime.now(UTC)
    run_id = await _claimed_but_not_running(spine, claim_until=now + timedelta(minutes=5))

    resumed = await resume_due_graph_runs(
        store=spine.store,
        run_store=spine.run_store,
        node_resolver=lambda node_id, graph: _Step(),
        now=now + timedelta(minutes=10),
    )

    assert resumed == 1
    finished = await spine.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED


async def test_a_live_claim_on_a_queued_continuation_is_left_to_its_walker(
    spine: _Spine,
) -> None:
    run_id = await _claimed_but_not_running(
        spine, claim_until=datetime.now(UTC) + timedelta(minutes=5)
    )
    before = await spine.continuations.get(run_id)
    assert before is not None

    assert await spine.store.reconcile_persistence() == 0

    after = await spine.continuations.get(run_id)
    assert after is not None
    assert (after.status, after.version) == (RunStatus.QUEUED, before.version)
    running = await spine.run_store.get_run(run_id)
    assert running is not None and running.status is RunStatus.RUNNING


async def test_a_stranded_run_behind_many_running_runs_is_reached_within_bounded_calls(
    spine: _Spine,
) -> None:
    """Neither scan may re-read one fixed prefix forever.

    150 RUNNING Runs with no continuation sit ahead of the stranded Run on the
    spine, and 150 consistent QUEUED continuations fill the continuation-status
    buckets the per-status loop reads first. Only a cursor that advances across
    calls reaches the stranded Run.
    """
    filler = _graph(spine, _Step(), name="not graph work")
    for index in range(150):
        other = await spine.run_store.create_run(
            filler,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=f"filler-principal-{index}",
        )
        await spine.run_store.transition_run(other.run_id, RunStatus.RUNNING)
    for index in range(150):
        queued = await spine.run_store.create_run(
            filler,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=f"queued-principal-{index}",
        )
        await spine.continuations.create(
            GraphContinuation(
                run_id=queued.run_id,
                graph_state=GraphExecutionState(run_id=queued.run_id, active_node_ids=("step",)),
                status=RunStatus.QUEUED,
                project_id=spine.project_id,
                created_at=queued.created_at,
            )
        )
    run_id = await _crash_at_terminal_write(spine, _Step())

    for _ in range(3):
        await spine.store.reconcile_persistence(limit=100)
        settled = await spine.run_store.get_run(run_id)
        assert settled is not None
        if settled.status is RunStatus.COMPLETED:
            break
    assert settled.status is RunStatus.COMPLETED


async def test_a_terminal_write_still_being_mirrored_is_left_to_its_walker(
    spine: _Spine,
) -> None:
    """Fresh spine activity means the walker may be between its two writes.

    Settling then would stamp "original error not persisted" over the error the
    walker is about to mirror and cancel the NodeRun it is about to fail.
    """
    run_id = await _crash_at_terminal_write(spine, _Fails())
    patient = CanonicalDurableRunStore(spine.run_store, spine.continuations)

    assert await patient.reconcile_persistence() == 0

    untouched = await spine.run_store.get_run(run_id)
    assert untouched is not None and untouched.status is RunStatus.RUNNING
    [node_run] = await spine.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.RUNNING


async def test_a_refused_repair_does_not_stop_the_rest_of_the_tick(
    spine: _Spine, caplog: pytest.LogCaptureFixture
) -> None:
    """A COMPLETED continuation over a mirrored FAILED node cannot be earned.

    The spine refuses that completion. The refusal is that Run's alone: it is
    logged and the stranded Run beside it is still settled in the same call,
    because this sweep heads every due and queued tick.
    """

    async def completed_over_failure(record: DurableRunRecord) -> DurableRunRecord:
        running = await spine.run_store.get_run(record.run_id)
        assert running is not None
        return record.model_copy(update={"run": transition_run(running, RunStatus.COMPLETED)})

    refused = await _crash_at_terminal_write(
        spine, _Fails(), rewrite=completed_over_failure, mirror_node_runs=True
    )
    stranded = await _crash_at_terminal_write(spine, _Step())

    with caplog.at_level("WARNING", logger="maistro.graph.durable_runs.canonical_store"):
        assert await spine.store.reconcile_persistence() == 1

    settled = await spine.run_store.get_run(stranded)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    still = await spine.run_store.get_run(refused)
    assert still is not None and still.status is RunStatus.RUNNING
    assert any(refused in record.getMessage() for record in caplog.records)


async def test_a_waiting_run_under_a_completed_continuation_does_not_abort_the_tick(
    spine: _Spine,
) -> None:
    """No lifecycle edge leads from WAITING straight to COMPLETED; skip, do not raise."""
    graph = _graph(spine, _Step(), name="waiting")
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await spine.run_store.transition_run(admitted.run_id, RunStatus.RUNNING)
    waiting = await spine.run_store.transition_run(admitted.run_id, RunStatus.WAITING)
    await spine.continuations.create(
        GraphContinuation(
            run_id=admitted.run_id,
            graph_state=GraphExecutionState(run_id=admitted.run_id),
            status=RunStatus.COMPLETED,
            project_id=spine.project_id,
            created_at=waiting.created_at,
        )
    )

    assert await spine.store.reconcile_persistence() == 0
    unchanged = await spine.run_store.get_run(admitted.run_id)
    assert unchanged is not None and unchanged.status is RunStatus.WAITING


async def test_a_claim_advanced_by_another_writer_first_is_left_to_that_writer(
    spine: _Spine, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await _claimed_but_not_running(
        spine, claim_until=datetime.now(UTC) - timedelta(minutes=1)
    )

    async def lost_race(continuation: GraphContinuation) -> GraphContinuation:
        raise ValueError("version regression")

    monkeypatch.setattr(spine.continuations, "update", lost_race)

    assert await spine.store.reconcile_persistence() == 0
    still = await spine.continuations.get(run_id)
    assert still is not None and still.status is RunStatus.QUEUED


async def test_a_cancelled_continuation_with_hitl_evidence_is_not_settled_as_graph_residue(
    spine: _Spine,
) -> None:
    """HITL cancellation belongs to the HITL repair, which knows its node and moment."""

    async def hitl_cancelled(record: DurableRunRecord) -> DurableRunRecord:
        running = await spine.run_store.get_run(record.run_id)
        assert running is not None
        metadata = {
            **record.graph_state.metadata,
            "hitl_settlements": {"step": {"outcome": "cancelled"}},
        }
        return record.model_copy(
            update={
                "run": transition_run(running, RunStatus.CANCELLED),
                "graph_state": record.graph_state.model_copy(update={"metadata": metadata}),
            }
        )

    run_id = await _crash_at_terminal_write(spine, _Step(), rewrite=hitl_cancelled)

    assert await spine.store.reconcile_persistence() == 0
    untouched = await spine.run_store.get_run(run_id)
    assert untouched is not None and untouched.status is RunStatus.RUNNING


async def test_the_running_sweep_does_not_spend_the_per_status_budget(spine: _Spine) -> None:
    """A full page of RUNNING Runs must not starve the continuation-status repairs."""
    filler = _graph(spine, _Step(), name="not graph work")
    for _ in range(5):
        other = await spine.run_store.create_run(
            filler,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        await spine.run_store.transition_run(other.run_id, RunStatus.RUNNING)
    await spine.continuations.create(
        GraphContinuation(
            run_id="orphaned-continuation",
            graph_state=GraphExecutionState(run_id="orphaned-continuation"),
            status=RunStatus.WAITING,
        )
    )

    assert await spine.store.reconcile_persistence(limit=5) == 1
    assert await spine.continuations.get("orphaned-continuation") is None


class _ExternalWait(_Step):
    """Parks WAITING on a system-owned pause; consumes the delivered answer on re-entry."""

    kind: ClassVar[str] = "test.cross_store_crash.external_wait"

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        if isinstance(answers, Mapping) and answers.get(ctx.node_id):
            return _Out(text="answered")
        # Immediately due, so the resumed visit re-enters this body instead of
        # replaying the parked Attempt until its poll timer elapses.
        pause_until(PAUSE_AWAITING_HARNESS, resume_at=now_utc(), metadata={"handle_id": "h-1"})


class _RemoteWait(_Step):
    kind: ClassVar[str] = "test.cross_store_crash.remote_wait"

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        pause_until(
            "awaiting_remote_delegation",
            resume_at=now_utc() + timedelta(minutes=1),
            metadata={"task_id": "remote-1", "peer_name": "hub"},
        )


async def test_external_poll_pages_canonical_runs_without_continuations(spine: _Spine) -> None:
    """An empty assembled page is progress, not the end of parked work."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from maistro.a2a.guest_peers import DelegationResult
    from maistro.graph.durable_runs import ScanContinuation, poll_external_results

    node = _RemoteWait()
    graph = _graph(spine, node)
    for _ in range(3):
        unrelated = await spine.run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        await spine.run_store.transition_run(unrelated.run_id, RunStatus.RUNNING)
        await spine.run_store.transition_run(unrelated.run_id, RunStatus.WAITING)
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await run_durable_graph(
        graph,
        store=spine.store,
        run_store=spine.run_store,
        run_id=admitted.run_id,
        node_resolver=lambda *_: node,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    peers = SimpleNamespace(
        poll_result=AsyncMock(
            return_value=DelegationResult(
                task_id="remote-1",
                peer_name="hub",
                status="completed",
                result="done",
            )
        )
    )
    scan = ScanContinuation()
    counts = [
        await poll_external_results(
            store=spine.store,
            guest_peers=peers,
            harness_adapters={},
            limit=1,
            max_inspected=2,
            scan=scan,
        )
        for _ in range(5)
    ]
    assert sum(counts) == 1
    assert (await spine.store.get(admitted.run_id)).run.status is RunStatus.QUEUED
    peers.poll_result.assert_awaited_once_with("hub", "remote-1")
    page = await spine.store.scan_status_page(RunStatus.WAITING, limit=0)
    assert page.items == [] and page.inspected == 0


@pytest.mark.parametrize("remote", [True, False])
async def test_external_receipts_are_correlated_before_any_canonical_write(
    spine: _Spine, remote: bool
) -> None:
    """Exercise the real completion bridge and store, not a mocked rejection."""
    from types import SimpleNamespace

    from maistro.container import Container

    node = _RemoteWait() if remote else _ExternalWait()
    graph = _graph(spine, node)
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await run_durable_graph(
        graph,
        store=spine.store,
        run_store=spine.run_store,
        run_id=admitted.run_id,
        node_resolver=lambda *_: node,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    before = await spine.store.get(admitted.run_id)
    container = Container.__new__(Container)
    container.graph_run_store = spine.store
    if remote:
        await container.wake_external_graph_result(
            SimpleNamespace(
                metadata={"parent_run_id": admitted.run_id, "parent_node_id": "step"},
                status=SimpleNamespace(value="completed"),
                id="foreign-old-task",
                result="foreign",
                error=None,
            )
        )
    else:
        with pytest.raises(ValueError, match="receipt"):
            await spine.store.submit_external_result(
                admitted.run_id, "step", {"status": "completed", "handle_id": "foreign-handle"}
            )
    assert await spine.store.get(admitted.run_id) == before
    with pytest.raises(ValueError, match="receipt"):
        await spine.store.submit_external_result(admitted.run_id, "step", {"status": "completed"})
    assert await spine.store.get(admitted.run_id) == before
    key, identity = ("task_id", "remote-1") if remote else ("handle_id", "h-1")
    result = {"status": "completed", key: identity, "result": "done"}
    delivered = await spine.store.submit_external_result(admitted.run_id, "step", result)
    assert delivered.run.status is RunStatus.QUEUED
    assert delivered.hitl_answers["step"][key] == identity
    assert (await spine.store.submit_external_result(admitted.run_id, "step", result)) == delivered


async def test_an_external_result_mirror_lost_to_a_crash_is_requeued_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``submit_external_result`` window: WAITING spine, QUEUED continuation.

    The external-result seam writes the continuation (QUEUED, with the answer
    evidence) and only then mirrors the lifecycle onto the spine. A process
    that dies in between leaves a Run the queued tick cannot see (it pages the
    spine, which still reads WAITING) and the due index never lists (it
    excludes QUEUED continuations) -- stranded forever unless the reconcile
    sweep rebuilds the interrupted mirror from the committed answer evidence.
    This is the SQLite close/reopen shape: the recovery half shares no
    connection or cached object with the interrupted writer, the way a
    restarted process would.
    """
    db = tmp_path / "external-window.db"
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="External window"
    )

    # ---- walker process: park, deliver the result, die at the mirror ----
    conn = await aiosqlite.connect(db)
    try:
        run_store = SqliteRunStore(conn, project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
        await run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        store = CanonicalDurableRunStore(run_store, continuations)

        graph = Graph(
            workspace_id=_WORKSPACE,
            project_id=project.project_id,
            name="external window",
            nodes=[Node(node_id="work", node_type=_ExternalWait.kind)],
        )
        admitted = await run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        parked = await run_durable_graph(
            graph,
            store=store,
            node_resolver=lambda node_id, current: _ExternalWait(),
            run_id=admitted.run_id,
            run_store=run_store,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        assert parked.status is RunStatus.WAITING

        async def crashing_mirror(record: DurableRunRecord, *, run_store: RunStore) -> None:
            raise _InjectedCrash

        monkeypatch.setattr(canonical_store_module, "mirror_lifecycle", crashing_mirror)
        with pytest.raises(_InjectedCrash):
            await store.submit_external_result(
                admitted.run_id,
                "work",
                {"status": "completed", "handle_id": "h-1", "result": "done"},
            )
        monkeypatch.undo()

        # Exactly the window: the answer is committed on the continuation,
        # the spine never heard about it.
        stranded = await run_store.get_run(admitted.run_id)
        assert stranded is not None and stranded.status is RunStatus.WAITING
        residue = await continuations.get(admitted.run_id)
        assert residue is not None and residue.status is RunStatus.QUEUED
    finally:
        await conn.close()

    # ---- restarted process: fresh connection, fresh stores ----
    conn = await aiosqlite.connect(db)
    try:
        run_store = SqliteRunStore(conn, project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
        await run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        store = CanonicalDurableRunStore(run_store, continuations)

        # The reconcile sweep rebuilds the lost mirror from the committed
        # answer evidence, and a second pass finds nothing left to repair.
        assert await store.reconcile_persistence() == 1
        repaired = await run_store.get_run(admitted.run_id)
        assert repaired is not None and repaired.status is RunStatus.QUEUED
        node_runs = await run_store.list_node_runs(admitted.run_id)
        assert [node.status for node in node_runs] == [RunStatus.QUEUED]
        assert await store.reconcile_persistence() == 0

        # The queued tick now sees the Run and the walker finishes it with
        # the delivered answer.
        recovered = await recover_queued_graph_runs(
            store=store,
            run_store=run_store,
            node_resolver_factory=lambda run: lambda node_id, current: _ExternalWait(),
            eligible=lambda run: True,
        )
        assert recovered == 1
        settled = await store.get(admitted.run_id)
        assert settled is not None and settled.run.status is RunStatus.COMPLETED
        assert all(node.status is RunStatus.COMPLETED for node in settled.node_runs)
        assert settled.hitl_answers["work"]["result"] == "done"
    finally:
        await conn.close()


async def test_a_delivered_external_result_returns_the_persisted_run_and_replays(
    tmp_path: Path,
) -> None:
    """The canonical external-result seam returns the store's persisted state,
    replays an identical receipt as a no-op, and refuses unknown runs."""
    db = tmp_path / "external-return.db"
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="External return"
    )
    conn = await aiosqlite.connect(db)
    try:
        run_store = SqliteRunStore(conn, project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
        await run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        store = CanonicalDurableRunStore(run_store, continuations)

        with pytest.raises(KeyError, match="no such run"):
            await store.submit_external_result("missing", "work", {"status": "completed"})

        graph = Graph(
            workspace_id=_WORKSPACE,
            project_id=project.project_id,
            name="external return",
            nodes=[Node(node_id="work", node_type=_ExternalWait.kind)],
        )
        admitted = await run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        parked = await run_durable_graph(
            graph,
            store=store,
            node_resolver=lambda node_id, current: _ExternalWait(),
            run_id=admitted.run_id,
            run_store=run_store,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        assert parked.status is RunStatus.WAITING

        result = {"status": "completed", "handle_id": "h-1", "result": "done"}
        delivered = await store.submit_external_result(admitted.run_id, "work", result)
        assert delivered.run.status is RunStatus.QUEUED
        persisted = await store.get(admitted.run_id)
        assert persisted is not None and persisted.version == delivered.version

        # An at-least-once redelivery of the same receipt advances nothing.
        replayed = await store.submit_external_result(admitted.run_id, "work", result)
        assert replayed.version == delivered.version
    finally:
        await conn.close()


# --- A walker that died between frontiers -------------------------------------
#
# A walker's recovery claim is written once, when it takes the Run, and the
# first frontier checkpoint clears it (`resume_at=None`); no later frontier
# writes another. So a walker that dies anywhere after its first frontier leaves
# a RUNNING Run under a RUNNING continuation the due index never lists (#1151
# windows 1 and 2, and any crash inside a later node).
#
# End-to-end acceptance cases: they drive the real executor into that state and
# hold the shipped reconcile to its contract -- the stranded continuation is
# made due (an elapsed claim, version+1) and `resume_due_graph_runs` finishes
# the walk from the persisted frontier without re-running committed nodes. The
# RUNNING/RUNNING unclaimed state itself is owned by the stalled-active-frontier
# repair; the per-version-observation repair this branch originally added was
# superseded by that reviewed design (#1942, #1861) and removed during the
# develop merge -- it was unreachable behind the frontier repair, and its
# restarted-replica and lease-less stanzas contradicted the landed quiet-period
# oracle in `test_live_walker_final_checkpoint.py`.


class _Counted(_Step):
    kind: ClassVar[str] = "test.cross_store_crash.counted"
    executions: ClassVar[list[str]] = []

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        _Counted.executions.append(ctx.node_id)
        return _Out(text=f"ran {ctx.node_id}")


def _two_step_graph(spine: _Spine) -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=spine.project_id,
        name="stalled walk",
        nodes=[
            Node(node_id="first", node_type=_Counted.kind, policies={"max_attempts": 1}),
            Node(node_id="second", node_type=_Counted.kind, policies={"max_attempts": 1}),
        ],
        edges=[Edge(edge_id="first-second", from_node="first", to_node="second")],
    )


async def _die_after_frontier_checkpoint(spine: _Spine, graph: Graph) -> str:
    """Walk until the first frontier checkpoint is durable, then die."""
    _Counted.executions.clear()
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    real_update = spine.store.update

    async def crashing_update(record: DurableRunRecord) -> DurableRunRecord:
        written = await real_update(record)
        if record.traversal_commits and record.run.status is RunStatus.RUNNING:
            raise _InjectedCrash
        return written

    spine.store.update = crashing_update  # type: ignore[method-assign]
    try:
        with pytest.raises(_InjectedCrash):
            await run_durable_graph(
                graph,
                store=spine.store,
                node_resolver=lambda node_id, current: _Counted(),
                run_id=admitted.run_id,
                run_store=spine.run_store,
            )
    finally:
        spine.store.update = real_update  # type: ignore[method-assign]
    stranded = await spine.store.get(admitted.run_id)
    assert stranded is not None
    assert stranded.run.status is RunStatus.RUNNING
    assert stranded.resume_at is None
    return admitted.run_id


async def _resume_due(spine: _Spine, *, now: datetime | None = None) -> int:
    return await resume_due_graph_runs(
        store=spine.store,
        run_store=spine.run_store,
        node_resolver=lambda node_id, graph: _Counted(),
        now=now if now is not None else datetime.now(UTC),
    )


async def test_a_run_whose_last_node_settled_before_the_walker_died_is_completed(
    spine: _Spine,
) -> None:
    """Window 1: the only NodeRun is terminal, the Run never settled."""
    run_id = await _die_after_frontier_checkpoint(spine, _graph(spine, _Counted()))
    assert _Counted.executions == ["step"]

    assert await _resume_due(spine) == 1

    finished = await spine.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED
    assert finished.result == {"text": "ran step"}
    assert _Counted.executions == ["step"], "a settled node must not run again"


async def test_a_walk_that_died_mid_graph_continues_from_its_frontier(spine: _Spine) -> None:
    """The first node committed and routed; the walker died before the second."""
    run_id = await _die_after_frontier_checkpoint(spine, _two_step_graph(spine))
    assert _Counted.executions == ["first"]

    assert await _resume_due(spine) == 1

    finished = await spine.store.get(run_id)
    assert finished is not None and finished.run.status is RunStatus.COMPLETED
    assert _Counted.executions == ["first", "second"]
    assert sorted(item.node_id for item in finished.node_runs) == ["first", "second"]


async def test_the_repair_gives_an_elapsed_claim_and_is_idempotent(spine: _Spine) -> None:
    run_id = await _die_after_frontier_checkpoint(spine, _two_step_graph(spine))
    before = await spine.continuations.get(run_id)
    assert before is not None
    moment = datetime.now(UTC)

    assert await spine.store.reconcile_persistence(now=moment) == 1
    after = await spine.continuations.get(run_id)
    assert after is not None
    assert after.status is RunStatus.RUNNING
    assert after.resume_at == moment
    assert after.version == before.version + 1
    assert await spine.store.reconcile_persistence(now=moment) == 0


async def test_a_walk_whose_spine_just_moved_is_left_to_its_walker(spine: _Spine) -> None:
    """The stranded continuation is not claimed while the spine is inside the quiet period."""
    run_id = await _die_after_frontier_checkpoint(spine, _two_step_graph(spine))
    patient = CanonicalDurableRunStore(spine.run_store, spine.continuations)
    now = datetime.now(UTC)
    # Ticks before the period, and while the spine moved within it, must not
    # claim the continuation out from under a possibly-live walker.
    assert await patient.reconcile_persistence(now=now - TERMINAL_SETTLE_QUIET_PERIOD * 2) == 0

    assert await patient.reconcile_persistence(now=now + timedelta(seconds=30)) == 0
    unclaimed = await spine.continuations.get(run_id)
    assert unclaimed is not None and unclaimed.resume_at is None

    assert await patient.reconcile_persistence(now=now + TERMINAL_SETTLE_QUIET_PERIOD) == 1


class _DiesOnSecond(_Counted):
    kind: ClassVar[str] = "test.cross_store_crash.dies_on_second"

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        if ctx.node_id == "second":
            _Counted.executions.append(ctx.node_id)
            raise _InjectedCrash
        return await super()._execute(inputs, ctx)


async def test_a_walker_that_died_inside_a_later_node_is_recovered_once_its_lease_lapses(
    spine: _Spine,
) -> None:
    """The second node's Attempt is open under a lease its dead process no longer renews.

    Until that lease lapses, a live walker could still hold the Attempt, so the
    sweep leaves the Run alone; after it, the Run is made due.
    """
    _Counted.executions.clear()
    graph = _two_step_graph(spine)
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    with pytest.raises(_InjectedCrash):
        await run_durable_graph(
            graph,
            store=spine.store,
            node_resolver=lambda node_id, current: _DiesOnSecond(),
            run_id=admitted.run_id,
            run_store=spine.run_store,
        )
    assert _Counted.executions == ["first", "second"]
    stranded = await spine.store.get(admitted.run_id)
    assert stranded is not None
    assert stranded.run.status is RunStatus.RUNNING
    assert stranded.resume_at is None
    [open_attempt] = [a for a in stranded.attempts if a.status not in TERMINAL_ATTEMPT_STATUSES]
    lease = open_attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    before_lapse = lease.expires_at - timedelta(seconds=1)
    assert await spine.store.reconcile_persistence(now=before_lapse) == 0
    held = await spine.continuations.get(admitted.run_id)
    assert held is not None and held.resume_at is None

    lapsed = lease.expires_at + timedelta(seconds=1)
    assert await spine.store.reconcile_persistence(now=lapsed) == 1
    due = await spine.continuations.get(admitted.run_id)
    assert due is not None and due.resume_at == lapsed


async def test_a_claimed_walk_is_not_reclaimed(spine: _Spine) -> None:
    """A recovering walker's claim is its own; the due index sees it when it lapses."""
    run_id = await _die_after_frontier_checkpoint(spine, _two_step_graph(spine))
    record = await spine.store.get(run_id)
    assert record is not None
    claim = datetime.now(UTC) + timedelta(minutes=5)
    await spine.continuations.update(
        GraphContinuation.of(
            record.model_copy(update={"resume_at": claim, "version": record.version + 1})
        )
    )

    assert await spine.store.reconcile_persistence() == 0
    held = await spine.continuations.get(run_id)
    assert held is not None and held.resume_at == claim
