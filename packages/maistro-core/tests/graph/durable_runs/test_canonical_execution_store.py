"""The Attempt is the canonical store's too, guards and lifecycle included (#44).

`DurableRunExecutionStore.create_attempt` used to be a line-for-line copy of
`InMemoryRunStore.create_attempt` — same terminal-NodeRun guard, same
active-Attempt check, same `max(ordinal) + 1`, same lease construction. That
duplication is what a second system of record looks like from the inside, so
these cover the delegated path: the identity and the physical lifecycle are
the store's, while the aggregate keeps the preconditions only it can answer.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs.execution_store import DurableRunExecutionStore
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore, RunStatus
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.store import ActiveAttemptExists, RunIntegrityError, StaleExecutionFence


async def _bound_store() -> tuple[
    InMemoryDurableRunStore, InMemoryRunStore, DurableRunExecutionStore, DurableRunRecord, str
]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-exec")
    project = await projects.create(
        workspace_id="ws-exec", parent_project_id=root.project_id, name="Graphs"
    )
    run_store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-exec",
        project_id=project.project_id,
        name="Attempt boundary",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await run_store.create_run(graph)
    await run_store.transition_run(run.run_id, RunStatus.QUEUED)
    run = await run_store.transition_run(run.run_id, RunStatus.RUNNING)

    node_run = await run_store.create_node_run(run.run_id, node_id="node-1")
    await run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)

    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
        node_runs=(node_run,),
        version=1,
    )
    store = InMemoryDurableRunStore()
    await store.create(record)
    execution_store = DurableRunExecutionStore(store, run_id=run.run_id, run_store=run_store)
    return store, run_store, execution_store, record, node_run.node_run_id


async def test_the_attempt_is_created_once_in_the_store_and_mirrored_here() -> None:
    store, run_store, execution_store, record, node_run_id = await _bound_store()

    attempt = await execution_store.create_attempt(node_run_id, executor_id="graph.node")

    assert await run_store.get_attempt(attempt.attempt_id) is not None
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert [item.attempt_id for item in persisted.attempts] == [attempt.attempt_id]
    assert attempt.ordinal == 1


async def test_a_second_active_attempt_is_still_refused() -> None:
    """The guard survives the delegation: one physical execution per NodeRun
    at a time is the invariant, not an implementation detail of either store."""
    _store, _run_store, execution_store, _record, node_run_id = await _bound_store()
    await execution_store.create_attempt(node_run_id)

    with pytest.raises(ActiveAttemptExists):
        await execution_store.create_attempt(node_run_id)


async def test_the_records_own_precondition_still_fires_on_the_delegated_path() -> None:
    """The aggregate knows this Run is finished with the node before the
    canonical row does, so it is the one that has to refuse."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    settled = transition_node_run(record.node_runs[0], RunStatus.COMPLETED)
    await store.update(
        record.model_copy(update={"node_runs": (settled,), "version": record.version + 1})
    )
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.status is RunStatus.RUNNING

    with pytest.raises(RunIntegrityError, match="terminal NodeRun"):
        await execution_store.create_attempt(node_run_id)


async def test_a_lease_renewal_goes_to_the_store_that_holds_the_lease() -> None:
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    attempt = await execution_store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None

    renewed = await execution_store.renew_lease(
        attempt.attempt_id,
        fencing_token=attempt.execution_lease.fencing_token,
        ttl=timedelta(seconds=120),
    )

    assert renewed.execution_lease is not None
    assert renewed.execution_lease.expires_at > attempt.execution_lease.expires_at
    canonical = await run_store.get_attempt(attempt.attempt_id)
    assert canonical is not None and canonical.execution_lease is not None
    assert canonical.execution_lease.expires_at == renewed.execution_lease.expires_at
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert persisted.attempts[0].execution_lease is not None
    assert persisted.attempts[0].execution_lease.expires_at == renewed.execution_lease.expires_at


async def test_settling_an_attempt_the_record_never_saw_is_a_disagreement() -> None:
    """An Attempt created straight on the spine is not in this aggregate, and
    mirroring it in silently would make the record claim a physical history it
    has no ordinal for. Saying so is the point."""
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()
    stranger = await run_store.create_attempt(node_run_id)

    with pytest.raises(RunIntegrityError, match=stranger.attempt_id):
        await execution_store.transition_attempt(stranger.attempt_id, AttemptStatus.RUNNING)


async def test_an_attempt_under_a_node_run_this_record_does_not_have() -> None:
    _store, _run_store, execution_store, _record, _node_run_id = await _bound_store()

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await execution_store.create_attempt("no-such-node-run")


async def test_an_unmirrored_attempt_from_a_different_request_is_not_adopted() -> None:
    """Adoption is only safe while the unmirrored row is the one this call
    would have made. Another caller's physical work is not this retry's to
    take, and reporting it would describe an execution nobody asked for."""
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()
    await run_store.create_attempt(node_run_id, executor_id="somebody-else")

    with pytest.raises(RunIntegrityError, match="retried creation contract"):
        await execution_store.create_attempt(node_run_id, executor_id="graph.node")


async def test_an_unmirrored_attempt_that_already_settled_is_not_adopted() -> None:
    """A terminal row is history, not a continuation. Adopting it would let a
    retry inherit an outcome it never produced."""
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()
    stranger = await run_store.create_attempt(node_run_id)
    await run_store.transition_attempt(stranger.attempt_id, AttemptStatus.CANCELLED)

    with pytest.raises(RunIntegrityError, match="is already"):
        await execution_store.create_attempt(node_run_id)


async def test_more_than_one_unmirrored_attempt_is_a_disagreement() -> None:
    """Adoption repairs a single lost mirror write. Two of them means the two
    stores disagree about more than one thing, and guessing which to take
    would be inventing history."""
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()
    first = await run_store.create_attempt(node_run_id)
    await run_store.transition_attempt(first.attempt_id, AttemptStatus.CANCELLED)
    await run_store.create_attempt(node_run_id)

    with pytest.raises(RunIntegrityError, match="one-row continuation"):
        await execution_store.create_attempt(node_run_id)


async def test_reclaim_leaves_alone_an_attempt_whose_holder_renewed() -> None:
    """The projection can be stale by exactly one renewal. Cancelling on that
    evidence would terminalize demonstrably live work, which is the one thing
    the disposition table refuses outright."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    attempt = await execution_store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    stale_expiry = attempt.execution_lease.expires_at + timedelta(seconds=1)
    # Renewed on the spine only, so this view still believes the old expiry.
    await run_store.renew_lease(
        attempt.attempt_id,
        fencing_token=attempt.execution_lease.fencing_token,
        ttl=timedelta(hours=1),
    )

    assert await execution_store.reclaim_expired_attempts(now=stale_expiry) == []

    canonical = await run_store.get_attempt(attempt.attempt_id)
    assert canonical is not None and canonical.status is AttemptStatus.CREATED
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert persisted.attempts[0].execution_lease is not None
    assert persisted.attempts[0].execution_lease.expires_at > stale_expiry, (
        "the stale projection is repaired rather than the live work cancelled"
    )


async def test_reclaim_reports_an_attempt_something_else_already_settled() -> None:
    """Two recoveries can observe the same lapse. The second finds the row
    terminal and reports the state rather than rewriting it."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    attempt = await execution_store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=1)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)
    await run_store.reclaim_expired_attempts(now=after)

    reclaimed = await execution_store.reclaim_expired_attempts(now=after)

    assert [item.attempt_id for item in reclaimed] == [attempt.attempt_id]
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert persisted.attempts[0].status is AttemptStatus.CANCELLED


class _FenceRaceRunStore(InMemoryRunStore):
    """Settles the Attempt and then reports the fence, like a lost race does."""

    race_once = False

    async def transition_attempt(self, attempt_id: str, target: Any, **kwargs: Any) -> Any:
        if self.race_once:
            self.race_once = False
            await super().transition_attempt(attempt_id, target, **kwargs)
            raise StaleExecutionFence("another recovery settled this Attempt first")
        return await super().transition_attempt(attempt_id, target, **kwargs)


async def test_losing_the_settle_race_reports_the_winner_rather_than_raising() -> None:
    """Two recoveries observing one lapse is a normal event, not an error. The
    loser's job is to report what the Attempt now is, and only to raise if it
    is somehow still active — which would mean the fence refused for a reason
    that has nothing to do with a race."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-race")
    project = await projects.create(
        workspace_id="ws-race", parent_project_id=root.project_id, name="Race"
    )
    run_store = _FenceRaceRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-race",
        project_id=project.project_id,
        name="Attempt boundary",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await run_store.create_run(graph)
    await run_store.transition_run(run.run_id, RunStatus.QUEUED)
    run = await run_store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await run_store.create_node_run(run.run_id, node_id="node-1")
    await run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
        node_runs=(node_run,),
        version=1,
    )
    store = InMemoryDurableRunStore()
    await store.create(record)
    execution_store = DurableRunExecutionStore(store, run_id=run.run_id, run_store=run_store)
    attempt = await execution_store.create_attempt(
        node_run.node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=1)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)
    run_store.race_once = True

    reclaimed = await execution_store.reclaim_expired_attempts(now=after)

    assert [item.attempt_id for item in reclaimed] == [attempt.attempt_id]
    assert reclaimed[0].status is AttemptStatus.CANCELLED
