"""P4b: reconciler uses persisted cancellation_cause authority (#232).

Unknown CANCELLED refuses; conflicting caller cause refuses; typed RECOVERED
delegates to ``apply_recovered_attempt_disposition``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, CancellationCause, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


async def _running() -> tuple[InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-p4b")
    project = await projects.create(
        workspace_id="ws-p4b", parent_project_id=root.project_id, name="p4b"
    )
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(
        Graph(
            workspace_id="ws-p4b",
            project_id=project.project_id,
            name="p4b",
            nodes=[Node(node_id="node-1", node_type="agent")],
        ),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return store, node_run.node_run_id


async def test_unknown_cancelled_refuses_even_with_caller_recovered() -> None:
    store, node_run_id = await _running()
    attempt = await store.create_attempt(node_run_id)
    cancelled = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.CANCELLED, error="orphan text"
    )
    assert cancelled.cancellation_cause is None

    with pytest.raises(RunIntegrityError, match="unknown cancellation_cause"):
        await AttemptLifecycleReconciler(store).reconcile(
            cancelled, cancellation=CancellationCause.RECOVERED
        )

    with pytest.raises(RunIntegrityError, match="unknown cancellation_cause"):
        await AttemptLifecycleReconciler(store).reconcile(cancelled)


async def test_unknown_cancelled_with_explicit_requested_still_terminalizes() -> None:
    """Transitional until P3c stamps REQUESTED on the CANCELLED write."""
    store, node_run_id = await _running()
    attempt = await store.create_attempt(node_run_id)
    cancelled = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.CANCELLED, error="user stop"
    )
    assert cancelled.cancellation_cause is None

    terminal = await AttemptLifecycleReconciler(store).reconcile(
        cancelled, cancellation=CancellationCause.REQUESTED
    )

    assert terminal.status is RunStatus.CANCELLED


async def test_conflicting_caller_cause_refuses() -> None:
    store, node_run_id = await _running()
    attempt = await store.create_attempt(
        node_run_id, lease_holder="w", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    lease = running.execution_lease
    assert lease is not None and lease.expires_at is not None
    reclaimed = await store.reclaim_expired_attempt(
        running.attempt_id, now=lease.expires_at + timedelta(seconds=1)
    )
    assert reclaimed is not None
    assert reclaimed.cancellation_cause is CancellationCause.RECOVERED

    with pytest.raises(RunIntegrityError, match="conflicts with persisted"):
        await AttemptLifecycleReconciler(store).reconcile(
            reclaimed, cancellation=CancellationCause.REQUESTED
        )


async def test_typed_recovered_delegates_to_disposition() -> None:
    store, node_run_id = await _running()
    attempt = await store.create_attempt(
        node_run_id, lease_holder="w", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    lease = running.execution_lease
    assert lease is not None and lease.expires_at is not None
    reclaimed = await store.reclaim_expired_attempt(
        running.attempt_id, now=lease.expires_at + timedelta(seconds=1)
    )
    assert reclaimed is not None

    parked = await AttemptLifecycleReconciler(store).reconcile(reclaimed)

    assert parked.status is RunStatus.WAITING
    run = await store.get_run(parked.run_id)
    assert run is not None and run.status is RunStatus.WAITING


async def test_typed_requested_terminalizes() -> None:
    store, node_run_id = await _running()
    attempt = await store.create_attempt(node_run_id)
    cancelled = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.CANCELLED, error="user stop"
    )
    # Inject REQUESTED until P3c stamps it on the generic transition.
    requested = cancelled.model_copy(update={"cancellation_cause": CancellationCause.REQUESTED})
    store._attempts[cancelled.attempt_id] = requested

    terminal = await AttemptLifecycleReconciler(store).reconcile(requested)

    assert terminal.status is RunStatus.CANCELLED
