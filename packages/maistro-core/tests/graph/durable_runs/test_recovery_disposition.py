"""Recovery dispositions for interrupted durable Graph work (#462).

The canonical policy: liveness is proven, not assumed. A resume finding an
active Attempt asks the execution lease — a live lease means a demonstrably
live worker owns the work and recovery is refused; a lapsed lease, or no lease
at all under an explicit resume, means the Attempt is orphaned and is recovered
through the canonical seam (cancelled with the RECOVERED cause, NodeRun parked,
fresh Attempt dispatched). Repeated recovery is idempotent, and the restart
survives a durable store reopen with the documented disposition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, GraphExecutionState, Node
from maistro.graph.durable_runs import (
    DurableRunRecord,
    InMemoryDurableRunStore,
    RunStatus,
    SqliteDurableRunStore,
    attempt_executor,
    resume_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.runs import Attempt, AttemptStatus, GraphSnapshot, NodeRun, Run
from maistro.runs.model import ExecutionLease


class _Empty(BaseModel):
    pass


class _Seed(BaseModel):
    seed: str


class _Work(BaseNode[_Empty, _Seed]):
    kind: ClassVar[str] = "test.recovery.work"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Seed
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Seed:
        type(self).calls += 1
        return _Seed(seed="recovered")


def _resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    return _Work()


def _crashed_record(
    run_id: str,
    *,
    lease_expires_in: timedelta | None = None,
) -> DurableRunRecord:
    """A Run persisted mid-Attempt by a process that then disappeared."""
    graph = Graph(
        workspace_id="ws-recovery",
        project_id="project-recovery",
        name="Recovery disposition",
        nodes=[Node(node_id="work", node_type=_Work.kind)],
        metadata={"entry_node": "work"},
    )
    run = Run(
        run_id=run_id,
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
    )
    node_run = NodeRun(
        node_run_id=f"{run_id}-node",
        run_id=run.run_id,
        node_id="work",
        ordinal=1,
        status=RunStatus.RUNNING,
    )
    values: dict[str, object] = {
        "attempt_id": f"{run_id}-attempt",
        "node_run_id": node_run.node_run_id,
        "ordinal": 1,
        "status": AttemptStatus.RUNNING,
        "started_at": run.created_at,
    }
    if lease_expires_in is not None:
        issued = datetime.now(UTC)
        values["execution_lease"] = ExecutionLease(
            node_run_id=node_run.node_run_id,
            attempt_id=str(values["attempt_id"]),
            lease_epoch=1,
            holder="worker-live",
            issued_at=issued,
            expires_at=issued + lease_expires_in,
        )
    attempt = Attempt.model_validate(values)
    state = GraphExecutionState(run_id=run.run_id, active_node_ids=("work",))
    return DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=(node_run,),
        attempts=(attempt,),
        version=1,
    )


@pytest.mark.asyncio
async def test_resume_refuses_a_demonstrably_live_attempt() -> None:
    """Live-worker evidence prevents another process from stealing active work.

    Cancelling past the lease would dispatch a duplicate physical execution:
    the fence stops the stale worker's *write*, not the double *execution*.
    """
    _Work.calls = 0
    store = InMemoryDurableRunStore()
    await store.create(_crashed_record("live-run", lease_expires_in=timedelta(minutes=5)))

    with pytest.raises(ValueError, match="live execution lease"):
        await resume_durable_graph("live-run", store=store, node_resolver=_resolver)

    untouched = await store.get("live-run")
    assert untouched is not None
    assert untouched.attempts[0].status is AttemptStatus.RUNNING
    assert untouched.node_runs[0].status is RunStatus.RUNNING
    assert _Work.calls == 0


@pytest.mark.asyncio
async def test_resume_recovers_an_attempt_whose_lease_lapsed() -> None:
    """A lapsed lease is the proof of death the recovery disposition requires."""
    _Work.calls = 0
    store = InMemoryDurableRunStore()
    record = _crashed_record("lapsed-run", lease_expires_in=timedelta(milliseconds=1))
    lease = record.attempts[0].execution_lease
    assert lease is not None and lease.expires_at is not None
    await store.create(record)
    while datetime.now(UTC) <= lease.expires_at:
        pass

    recovered = await resume_durable_graph("lapsed-run", store=store, node_resolver=_resolver)

    assert recovered.status is RunStatus.COMPLETED
    assert [attempt.status for attempt in recovered.attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
    assert _Work.calls == 1


@pytest.mark.asyncio
async def test_repeated_orphan_reconciliation_is_idempotent() -> None:
    """Recovery run twice reaches the same state and duplicates no Attempt."""
    store = InMemoryDurableRunStore()
    await store.create(_crashed_record("twice-run"))

    for _ in range(2):
        record = await store.get("twice-run")
        assert record is not None
        await attempt_executor._reconcile_orphaned_attempts(record, store=store)

    settled = await store.get("twice-run")
    assert settled is not None
    assert len(settled.attempts) == 1
    assert settled.attempts[0].status is AttemptStatus.CANCELLED
    assert settled.node_runs[0].status is RunStatus.WAITING
    assert settled.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_mid_attempt_restart_on_sqlite_produces_the_documented_disposition(
    tmp_path: Any,
) -> None:
    """The disposition holds against a durable store across a real reopen.

    The interrupted Attempt's history is preserved (CANCELLED, naming the
    recovery), a fresh chronological Attempt does the work, and the Run reaches
    COMPLETED — never a duplicate Attempt, never a rewritten outcome.
    """
    _Work.calls = 0
    db = tmp_path / "recovery.db"
    before_crash = SqliteDurableRunStore(db)
    await before_crash.create(_crashed_record("sqlite-run"))

    after_restart = SqliteDurableRunStore(db)
    recovered = await resume_durable_graph(
        "sqlite-run", store=after_restart, node_resolver=_resolver
    )

    assert recovered.status is RunStatus.COMPLETED
    assert [attempt.status for attempt in recovered.attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
    assert [attempt.ordinal for attempt in recovered.attempts] == [1, 2]
    assert "orphaned" in (recovered.attempts[0].error or "")
    assert recovered.node_runs[0].status is RunStatus.COMPLETED
    assert _Work.calls == 1

    persisted = await SqliteDurableRunStore(db).get("sqlite-run")
    assert persisted is not None
    assert persisted.status is RunStatus.COMPLETED
    assert [attempt.status for attempt in persisted.attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
