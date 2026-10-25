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
from maistro.runs import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    InMemoryRunStore,
    NodeRun,
    RunStatus,
)
from maistro.runs.lifecycle import InvalidLifecycleTransition, transition_node_run
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import ActiveAttemptExists, RunIntegrityError, StaleExecutionFence
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


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
    run = await run_store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
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


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_the_attempt_is_created_once_in_the_store_and_mirrored_here() -> None:
    store, run_store, execution_store, record, node_run_id = await _bound_store()

    attempt = await execution_store.create_attempt(node_run_id, executor_id="graph.node")

    assert await run_store.get_attempt(attempt.attempt_id) is not None
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert [item.attempt_id for item in persisted.attempts] == [attempt.attempt_id]
    assert attempt.ordinal == 1


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_a_second_active_attempt_is_still_refused() -> None:
    """The guard survives the delegation: one physical execution per NodeRun
    at a time is the invariant, not an implementation detail of either store."""
    _store, _run_store, execution_store, _record, node_run_id = await _bound_store()
    await execution_store.create_attempt(node_run_id)

    with pytest.raises(ActiveAttemptExists):
        await execution_store.create_attempt(node_run_id)


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_the_records_own_precondition_still_fires_on_the_delegated_path() -> None:
    """The aggregate knows this Run is finished with the node before the
    canonical row does, so it is the one that has to refuse."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    attempt = await execution_store.create_attempt(node_run_id)
    await execution_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    terminal = await execution_store.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED)
    current = await store.get(record.run_id)
    assert current is not None
    record = current
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id, attempt_result=AttemptResult.from_attempt(terminal)
    )
    settled = transition_node_run(
        record.node_runs[0], RunStatus.COMPLETED, accepted_outcome=outcome
    )
    await store.update(
        record.model_copy(update={"node_runs": (settled,), "version": record.version + 1})
    )
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.status is RunStatus.RUNNING

    with pytest.raises(RunIntegrityError, match="terminal NodeRun"):
        await execution_store.create_attempt(node_run_id)


@pytest.mark.ac("ADR-082826-d9f5/AC-3")
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


@pytest.mark.ac("ADR-082826-d9f5/AC-3")
async def test_settling_an_attempt_the_record_never_saw_is_a_disagreement() -> None:
    """An Attempt created straight on the spine is not in this aggregate, and
    mirroring it in silently would make the record claim a physical history it
    has no ordinal for. Saying so is the point."""
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()
    stranger = await run_store.create_attempt(node_run_id)

    with pytest.raises(RunIntegrityError, match=stranger.attempt_id):
        await execution_store.transition_attempt(stranger.attempt_id, AttemptStatus.RUNNING)


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
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
    run = await run_store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
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


# --- run and node-run transitions through the canonical store --------------


async def test_a_run_transition_goes_to_the_canonical_store_and_mirrors_back() -> None:
    _store, run_store, execution_store, _record, _node_run_id = await _bound_store()
    run_id = _record.run.run_id

    updated = await execution_store.transition_run(run_id, RunStatus.COMPLETED, result="done")

    assert updated.status is RunStatus.COMPLETED
    assert updated.result == "done"
    canonical = await run_store.get_run(run_id)
    assert canonical is not None
    assert canonical.status is RunStatus.COMPLETED
    mirrored = await execution_store.get_run(run_id)
    assert mirrored is not None
    assert mirrored.status is RunStatus.COMPLETED


async def test_a_run_transition_to_the_status_the_store_already_holds_is_idempotent() -> None:
    _store, run_store, execution_store, record, _node_run_id = await _bound_store()
    run_id = record.run.run_id

    first = await execution_store.transition_run(run_id, RunStatus.CANCELLED)
    second = await execution_store.transition_run(run_id, RunStatus.CANCELLED)

    assert first.status is RunStatus.CANCELLED
    assert second.status is RunStatus.CANCELLED
    canonical = await run_store.get_run(run_id)
    assert canonical is not None
    assert canonical.status is RunStatus.CANCELLED


async def test_a_run_the_canonical_store_never_saw_is_an_integrity_error() -> None:
    store, _run_store, _execution_store, record, _node_run_id = await _bound_store()
    orphan_projects = InMemoryProjectScopeStore()
    orphan_run_store = InMemoryRunStore(project_store=orphan_projects)
    execution_store = DurableRunExecutionStore(
        store, run_id=record.run.run_id, run_store=orphan_run_store
    )

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await execution_store.transition_run(record.run.run_id, RunStatus.CANCELLED)


async def test_a_node_run_transition_goes_to_the_canonical_store_and_mirrors_back() -> None:
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()

    updated = await execution_store.transition_node_run(node_run_id, RunStatus.CANCELLED)

    assert updated.status is RunStatus.CANCELLED
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None
    assert canonical.status is RunStatus.CANCELLED
    mirrored = await execution_store.get_node_run(node_run_id)
    assert mirrored is not None
    assert mirrored.status is RunStatus.CANCELLED


async def test_a_node_run_transition_to_the_status_it_already_holds_is_idempotent() -> None:
    _store, run_store, execution_store, _record, node_run_id = await _bound_store()

    first = await execution_store.transition_node_run(node_run_id, RunStatus.CANCELLED)
    second = await execution_store.transition_node_run(node_run_id, RunStatus.CANCELLED)

    assert first.status is RunStatus.CANCELLED
    assert second.status is RunStatus.CANCELLED
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None
    assert canonical.status is RunStatus.CANCELLED


async def test_a_node_run_the_canonical_store_never_saw_is_an_integrity_error() -> None:
    _store, run_store, execution_store, record, _node_run_id = await _bound_store()
    orphan = record.node_runs[0].model_copy(
        update={"node_run_id": "node-run-never-in-store", "node_id": "node-2", "ordinal": 2}
    )
    orphan_store = InMemoryDurableRunStore()
    await orphan_store.create(record.model_copy(update={"node_runs": (*record.node_runs, orphan)}))
    execution_store = DurableRunExecutionStore(
        orphan_store, run_id=record.run.run_id, run_store=run_store
    )

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await execution_store.transition_node_run("node-run-never-in-store", RunStatus.CANCELLED)


async def test_a_record_that_loses_its_node_run_under_the_transition_is_an_error() -> None:
    """A record rewritten underneath the transition is torn state, not a pass.

    The canonical store transitioned the NodeRun, but by the time the record
    mirror is written the aggregate no longer contains that NodeRun at all.
    Silently inserting it would invent history, so the disagreement surfaces.
    """
    _store, run_store, _execution_store, record, node_run_id = await _bound_store()

    class _LosingRecordStore(InMemoryDurableRunStore):
        def __init__(self) -> None:
            super().__init__()
            self.drop_node_run_id: str | None = None

        async def get(self, run_id: str) -> DurableRunRecord | None:
            found = await super().get(run_id)
            if found is None or self.drop_node_run_id is None:
                return found
            return found.model_copy(
                update={
                    "node_runs": tuple(
                        item
                        for item in found.node_runs
                        if item.node_run_id != self.drop_node_run_id
                    )
                }
            )

    torn = _LosingRecordStore()
    await torn.create(record)
    execution_store = DurableRunExecutionStore(torn, run_id=record.run.run_id, run_store=run_store)
    torn.drop_node_run_id = node_run_id

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await execution_store.transition_node_run(node_run_id, RunStatus.CANCELLED)


# ── legacy evidence migration across the delegated transition (#1334) ──


async def _complete_one_attempt(
    execution_store: DurableRunExecutionStore, node_run_id: str
) -> tuple[Attempt, Attempt]:
    """Drive one Attempt to physical completion through the delegated path."""
    attempt = await execution_store.create_attempt(node_run_id, executor_id="graph.node")
    await execution_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    terminal = await execution_store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"answer": "ok"}
    )
    return attempt, terminal


async def _load_legacy_node_shape(
    store: InMemoryDurableRunStore,
    run_store: InMemoryRunStore,
    record: DurableRunRecord,
    node_run_id: str,
    terminal: Attempt,
) -> NodeRun:
    """Rewind one completed NodeRun to its pre-acceptance shape, in both stores.

    Writes after acceptance became structural can no longer produce a
    completed row without evidence, so the strip below is the historical
    repair fixture — the same one ``tests/runs/test_spine_conformance.py``
    loads against the store directly — mirrored into the canonical row and
    the record's projection alike.
    """
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        result=terminal.result,
    )
    completed = await run_store.transition_node_run(
        node_run_id,
        RunStatus.COMPLETED,
        result=outcome.result,
        accepted_outcome=outcome,
    )
    legacy = completed.model_copy(update={"accepted_outcome": None}, deep=True)
    run_store._node_runs[node_run_id] = legacy
    current = await store.get(record.run_id)
    assert current is not None
    await store.update(
        current.model_copy(
            update={
                "node_runs": tuple(
                    legacy if item.node_run_id == node_run_id else item
                    for item in current.node_runs
                ),
                "version": current.version + 1,
            }
        )
    )
    return legacy


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_reconciling_a_legacy_completed_node_run_installs_evidence_in_both_stores() -> None:
    """#1334 regression: the adapter skipped the canonical write whenever the
    row already held the target status, so a canonical-backed reconciler could
    not perform the COMPLETED→COMPLETED legacy migration — the accepted
    outcome vanished from the canonical row, and the projection was then
    overwritten with that same pre-migration row."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    _attempt, terminal = await _complete_one_attempt(execution_store, node_run_id)
    legacy = await _load_legacy_node_shape(store, run_store, record, node_run_id, terminal)

    settled = await AttemptLifecycleReconciler(execution_store).reconcile(terminal)

    physical = AttemptResult.from_attempt(terminal)
    assert settled.status is RunStatus.COMPLETED
    assert settled.accepted_outcome is not None
    assert settled.accepted_outcome.attempt_result == physical
    assert settled.finished_at == legacy.finished_at
    assert settled.result == legacy.result
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.accepted_outcome is not None
    assert canonical.accepted_outcome.attempt_result == physical
    assert canonical.finished_at == legacy.finished_at
    mirrored = await execution_store.get_node_run(node_run_id)
    assert mirrored is not None and mirrored.accepted_outcome is not None
    assert mirrored.accepted_outcome.attempt_result == physical


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_a_same_status_transition_attaching_legacy_evidence_reaches_the_store() -> None:
    """The delegated transition itself, without the reconciler around it: a
    COMPLETED→COMPLETED call that carries an outcome the canonical row lacks
    must still be routed to the store that owns the row."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    _attempt, terminal = await _complete_one_attempt(execution_store, node_run_id)
    legacy = await _load_legacy_node_shape(store, run_store, record, node_run_id, terminal)
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        result=terminal.result,
    )

    migrated = await execution_store.transition_node_run(
        node_run_id,
        RunStatus.COMPLETED,
        result=legacy.result,
        error=legacy.error,
        accepted_outcome=outcome,
    )

    assert migrated.accepted_outcome == outcome
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.accepted_outcome == outcome
    assert canonical.finished_at == legacy.finished_at
    mirrored = await execution_store.get_node_run(node_run_id)
    assert mirrored is not None and mirrored.accepted_outcome == outcome


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_a_same_status_transition_with_already_attached_evidence_stays_a_no_op() -> None:
    """Replays stay no-ops: the store's validator refuses completed→completed
    outright, so routing a call whose evidence the row already holds would
    turn every idempotent replay into a failure. The acceptance clock is what
    a replay cannot reproduce, so it must not count as disagreement."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    _attempt, terminal = await _complete_one_attempt(execution_store, node_run_id)
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        result=terminal.result,
    )
    completed = await run_store.transition_node_run(
        node_run_id,
        RunStatus.COMPLETED,
        result=terminal.result,
        accepted_outcome=outcome,
    )
    current = await store.get(record.run_id)
    assert current is not None
    await store.update(
        current.model_copy(
            update={
                "node_runs": tuple(
                    completed if item.node_run_id == node_run_id else item
                    for item in current.node_runs
                ),
                "version": current.version + 1,
            }
        )
    )
    replay = outcome.model_copy(update={"accepted_at": outcome.accepted_at + timedelta(seconds=1)})

    replayed = await execution_store.transition_node_run(
        node_run_id,
        RunStatus.COMPLETED,
        result=terminal.result,
        accepted_outcome=replay,
    )

    assert replayed.accepted_outcome is not None
    assert replayed.accepted_outcome.accepted_at == outcome.accepted_at
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.accepted_outcome == outcome


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_a_same_status_transition_with_conflicting_evidence_surfaces_the_disagreement() -> (
    None
):
    """The store's migration validator, not the adapter, adjudicates legacy
    evidence: an outcome that disagrees with what the row recorded raises,
    and neither store is left half-written."""
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    _attempt, terminal = await _complete_one_attempt(execution_store, node_run_id)
    legacy = await _load_legacy_node_shape(store, run_store, record, node_run_id, terminal)
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        result=terminal.result,
    )
    conflicting = outcome.model_copy(update={"result": {"different": True}})

    with pytest.raises(InvalidLifecycleTransition, match="legacy completed NodeRun"):
        await execution_store.transition_node_run(
            node_run_id,
            RunStatus.COMPLETED,
            result=legacy.result,
            error=legacy.error,
            accepted_outcome=conflicting,
        )

    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.accepted_outcome is None
    mirrored = await execution_store.get_node_run(node_run_id)
    assert mirrored is not None and mirrored.accepted_outcome is None


@pytest.mark.ac("ADR-082826-d9f5/AC-2")
async def test_a_cancellation_replay_over_the_cascade_settled_row_converges() -> None:
    """A same-status CANCELLED replay carrying a different error text is a no-op.

    `RunExecutionService.cancel_run` fences the Run through the canonical
    store, whose cascade settles every open NodeRun with the cascade's own
    error narrative. The walk's registered executor then replays the
    cancellation through this adapter (`_cancel_settled_node_runs`) over a
    projection that still reads running and with the caller's error text. The
    store refuses to rewrite a closed Run's history -- so routing the replay
    there cannot repair anything, only abort a cancellation that already
    happened (#1332's end-to-end regression drives exactly this path).
    """
    store, run_store, execution_store, record, node_run_id = await _bound_store()
    attempt = await execution_store.create_attempt(node_run_id, executor_id="graph.node")
    await execution_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)

    # The route's fence: the raw canonical store terminalizes the Run and the
    # cascade settles the node. The durable record is a separate store and
    # stays stale until the replay converges it.
    await run_store.transition_run(record.run_id, RunStatus.CANCELLED, error="execution cancelled")
    canonical = await run_store.get_node_run(node_run_id)
    assert canonical is not None and canonical.status is RunStatus.CANCELLED
    assert canonical.error == "cancelled because its Run terminalized as cancelled"
    stale = await execution_store.get_node_run(node_run_id)
    assert stale is not None and stale.status is RunStatus.RUNNING

    replayed = await execution_store.transition_node_run(
        node_run_id, RunStatus.CANCELLED, error="execution cancelled"
    )

    # Converged, not raised: canonical truth wins, including its narrative.
    assert replayed.status is RunStatus.CANCELLED
    assert replayed.error == canonical.error
    reread = await run_store.get_node_run(node_run_id)
    assert reread is not None and reread.error == canonical.error
    persisted = await store.get(record.run_id)
    assert persisted is not None
    projected = next(item for item in persisted.node_runs if item.node_run_id == node_run_id)
    assert projected.status is RunStatus.CANCELLED
    assert projected.error == canonical.error
