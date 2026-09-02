"""Recovery says what it decided, on the canonical Event stream (#462, #61)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from maistro.events.envelope import EventEnvelope
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, CancellationCause, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.recovery_events import (
    RECOVERY_EVENT_TYPE,
    CanonicalRecoveryEventSink,
    RecoveryDispositionEvent,
)


class _RecordingCanonicalSink:
    """Records the canonical envelopes emitted by the recovery adapter."""

    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def emit(self, event: EventEnvelope) -> EventEnvelope:
        self.events.append(event)
        return event


class _UnknownRunLookup:
    """RunLookup double answering "no such Run": scope must not be invented."""

    async def get_run(self, run_id: str) -> Any:
        return None


async def _running_node() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-recovery-events")
    project = await projects.create(
        workspace_id="ws-recovery-events", parent_project_id=root.project_id, name="Recovery"
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-recovery-events",
        project_id=project.project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type="agent")],
    )
    run = await store.create_run(graph, initial_status=RunStatus.QUEUED)
    run = await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="step")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return store, run.run_id, node_run.node_run_id


def _canonical_recovery_sink(
    store: InMemoryRunStore,
) -> tuple[CanonicalRecoveryEventSink, _RecordingCanonicalSink]:
    recorded = _RecordingCanonicalSink()
    return CanonicalRecoveryEventSink(store, recorded), recorded


async def _cancelled_attempt(store: InMemoryRunStore, node_run_id: str) -> Any:
    attempt = await store.create_attempt(node_run_id, executor_id="worker-1")
    return await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.CANCELLED,
        error="orphaned physical Attempt recovered after process loss",
    )


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_recovered_cancellation_says_so_on_the_canonical_event_stream() -> None:
    """Recovery must name canonical scope and execution identity, not just payload ids."""
    store, run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)
    sink, recorded = _canonical_recovery_sink(store)

    await AttemptLifecycleReconciler(store, events=sink).reconcile(
        attempt, cancellation=CancellationCause.RECOVERED
    )

    assert len(recorded.events) == 1
    event = recorded.events[0]
    assert event.type == RECOVERY_EVENT_TYPE
    assert event.workspace_id == "ws-recovery-events"
    assert event.project_id
    assert event.run_id == run_id
    assert event.node_run_id == node_run_id
    assert event.attempt_id == attempt.attempt_id
    assert event.correlation_id == run_id
    assert event.provenance["legacy_event_category"] == "system"
    assert event.payload["disposition"] == "recovered_and_parked"
    assert event.payload["cancellation_cause"] == "recovered"
    assert event.payload["node_run_status"] == RunStatus.WAITING.value


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_requested_cancellation_is_a_different_disposition() -> None:
    store, _run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)
    sink, recorded = _canonical_recovery_sink(store)

    await AttemptLifecycleReconciler(store, events=sink).reconcile(
        attempt, cancellation=CancellationCause.REQUESTED
    )

    assert recorded.events[0].payload["disposition"] == "terminalized"
    assert recorded.events[0].payload["node_run_status"] == RunStatus.CANCELLED.value


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_the_envelope_ids_take_the_reader_back_to_the_spine() -> None:
    store, run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)
    sink, recorded = _canonical_recovery_sink(store)

    await AttemptLifecycleReconciler(store, events=sink).reconcile(attempt)

    event = recorded.events[0]
    assert event.run_id == run_id
    assert event.node_run_id == node_run_id
    assert event.attempt_id == attempt.attempt_id
    assert await store.get_run(event.run_id) is not None
    assert await store.get_attempt(event.attempt_id) is not None


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_an_accepted_outcome_is_announced_as_accepted() -> None:
    store, _run_id, node_run_id = await _running_node()
    attempt = await store.create_attempt(node_run_id, executor_id="worker-1")
    attempt = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"text": "done"}
    )
    sink, recorded = _canonical_recovery_sink(store)

    await AttemptLifecycleReconciler(store, events=sink).reconcile(attempt)

    assert recorded.events[0].payload["disposition"] == "accepted"
    assert recorded.events[0].payload["node_run_status"] == RunStatus.COMPLETED.value


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_without_a_sink_recovery_still_happens() -> None:
    store, _run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)

    parked = await AttemptLifecycleReconciler(store).reconcile(attempt)

    assert parked.status is RunStatus.WAITING


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_the_lease_sweep_announces_what_it_reclaimed() -> None:
    store, run_id, node_run_id = await _running_node()
    attempt = await store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)
    sink, recorded = _canonical_recovery_sink(store)

    reclaimed = await store.reclaim_expired_attempts(now=after)
    assert len(reclaimed) == 1
    await AttemptLifecycleReconciler(
        store, events=sink, source="maistro.container.recover_abandoned_attempts"
    ).reconcile(reclaimed[0])

    assert [event.payload["disposition"] for event in recorded.events] == ["recovered_and_parked"]
    assert recorded.events[0].source == "maistro.container.recover_abandoned_attempts"
    assert recorded.events[0].run_id == run_id
    assert recorded.events[0].workspace_id == "ws-recovery-events"


async def test_a_recovery_fact_for_an_unknown_run_is_refused() -> None:
    """Recovery may not mint Workspace scope for a Run that does not exist."""
    recorded = _RecordingCanonicalSink()
    sink = CanonicalRecoveryEventSink(_UnknownRunLookup(), recorded)
    fact = RecoveryDispositionEvent(
        run_id="run-does-not-exist",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        attempt_status="failed",
        node_run_status="waiting",
        cancellation_cause="recovered",
        disposition="parked",
        error="worker exited",
        source="recovery-test",
    )

    with pytest.raises(ValueError) as exc:
        await sink.emit(fact)

    assert "unknown Run 'run-does-not-exist'" in str(exc.value)
    assert recorded.events == []


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_failed_attempt_parks_and_says_it_parked() -> None:
    store, _run_id, node_run_id = await _running_node()
    attempt = await store.create_attempt(node_run_id, executor_id="worker-1")
    attempt = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.FAILED, error="node raised"
    )
    sink, recorded = _canonical_recovery_sink(store)

    parked = await AttemptLifecycleReconciler(store, events=sink).reconcile(attempt)

    assert parked.status is RunStatus.WAITING
    assert recorded.events[0].payload["disposition"] == "parked"
    assert recorded.events[0].payload["attempt_status"] == AttemptStatus.FAILED.value
    assert recorded.events[0].payload["error"] == "node raised"
