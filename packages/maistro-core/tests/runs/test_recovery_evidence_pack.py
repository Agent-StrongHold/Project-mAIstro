"""Adversarial kill-recovery evidence pack (#1611).

Async tests follow the suite's auto mode. Do not add pytest.mark.asyncio;
that closes the shared loop and fails the rest of the job.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

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
from maistro.runs.store import StaleExecutionFence
from maistro.testing.runs import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

LEDGER = Path(__file__).resolve().parents[4] / "docs" / "testing" / "recovery-evidence-ledger.json"


class _RecordingCanonicalSink:
    """Records canonical envelopes emitted by the recovery adapter."""

    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def emit(self, event: EventEnvelope) -> EventEnvelope:
        self.events.append(event)
        return event


async def _workspace() -> tuple[InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-evidence-pack")
    project = await projects.create(
        workspace_id="ws-evidence-pack", parent_project_id=root.project_id, name="Evidence"
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-evidence-pack",
        project_id=project.project_id,
        name="evidence",
        nodes=[Node(node_id="step", node_type="agent")],
    )
    run = await store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    return store, run.run_id


async def _running_node(store: InMemoryRunStore, run_id: str) -> str:
    run = await store.transition_run(run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="step")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return node_run.node_run_id


def test_ledger_names_the_five_pack_scenarios() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ids = [row["id"] for row in ledger["scenarios"]]
    assert ids == [
        "kill-mid-attempt",
        "dual-worker-fence",
        "version-skew-resume",
        "mixed-queue-restart",
        "crash-loop-replay",
    ]
    assert ledger["event_type"] == RECOVERY_EVENT_TYPE


async def test_kill_mid_attempt_parks_and_emits_recovery_event() -> None:
    store, run_id = await _workspace()
    node_run_id = await _running_node(store, run_id)
    attempt = await store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)
    recorded = _RecordingCanonicalSink()
    sink = CanonicalRecoveryEventSink(store, recorded)

    reclaimed = await store.reclaim_expired_attempts(now=after)
    assert len(reclaimed) == 1
    await AttemptLifecycleReconciler(
        store, events=sink, source="evidence.kill-mid-attempt"
    ).reconcile(reclaimed[0])

    assert recorded.events[0].payload["disposition"] == "recovered_and_parked"
    assert recorded.events[0].type == RECOVERY_EVENT_TYPE
    assert recorded.events[0].run_id == run_id
    parked = await store.get_attempt(reclaimed[0].attempt_id)
    assert parked is not None
    assert parked.status is AttemptStatus.CANCELLED


async def test_stale_worker_cannot_rewrite_after_fence_rotation() -> None:
    store, _run_id = await _workspace()
    node_run_id = await _running_node(store, _run_id)
    attempt = await store.create_attempt(
        node_run_id, lease_holder="worker-old", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    stale_token = attempt.execution_lease.fencing_token
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)
    reclaimed = await store.reclaim_expired_attempts(now=after)
    assert len(reclaimed) == 1

    # A newer Attempt now owns the NodeRun. Its fence is not the dead worker's.
    successor = await store.create_attempt(node_run_id, lease_holder="worker-new")
    assert successor.execution_lease is not None
    assert successor.execution_lease.lease_epoch != attempt.execution_lease.lease_epoch

    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            successor.attempt_id,
            AttemptStatus.COMPLETED,
            result={"text": "stale success"},
            fencing_token=stale_token,
        )

    current = await store.get_attempt(attempt.attempt_id)
    assert current is not None
    assert current.status is not AttemptStatus.COMPLETED
    assert current.result != {"text": "stale success"}
    owned = await store.get_attempt(successor.attempt_id)
    assert owned is not None
    assert owned.status is not AttemptStatus.COMPLETED
    assert owned.result != {"text": "stale success"}


async def test_replayed_recovery_fact_keeps_one_event_id() -> None:
    store, run_id = await _workspace()
    run = await store.get_run(run_id)
    assert run is not None
    recorded = _RecordingCanonicalSink()
    sink = CanonicalRecoveryEventSink(store, recorded)
    fact = RecoveryDispositionEvent(
        run_id=run_id,
        node_run_id="nr-replay",
        attempt_id="att-replay",
        attempt_status="cancelled",
        node_run_status="waiting",
        cancellation_cause="recovered",
        disposition="recovered_and_parked",
        error="killed",
        source="evidence.replay",
    )
    first = await sink.emit(fact)
    second = await sink.emit(fact)
    assert first.event_id == second.event_id
    assert first.event_id.startswith("recovery-")


async def test_mixed_queue_restart_does_not_silently_complete() -> None:
    store, running_id = await _workspace()
    queued = await store.get_run(running_id)
    assert queued is not None
    assert queued.status is RunStatus.QUEUED

    node_run_id = await _running_node(store, running_id)
    attempt = await store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=5)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)
    reclaimed = await store.reclaim_expired_attempts(now=after)
    recorded = _RecordingCanonicalSink()
    sink = CanonicalRecoveryEventSink(store, recorded)
    await AttemptLifecycleReconciler(store, events=sink).reconcile(
        reclaimed[0], cancellation=CancellationCause.RECOVERED
    )

    run = await store.get_run(running_id)
    assert run is not None
    assert run.status is not RunStatus.COMPLETED
    assert recorded.events[0].payload["disposition"] != "accepted"


async def test_second_reconcile_does_not_rewrite_attempt_history() -> None:
    store, run_id = await _workspace()
    node_run_id = await _running_node(store, run_id)
    attempt = await store.create_attempt(node_run_id, executor_id="worker-1")
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.CANCELLED, error="process lost"
    )
    recorded = _RecordingCanonicalSink()
    sink = CanonicalRecoveryEventSink(store, recorded)
    reconciler = AttemptLifecycleReconciler(store, events=sink, source="evidence.crash-loop")
    first = await reconciler.reconcile(attempt, cancellation=CancellationCause.RECOVERED)
    second = await reconciler.reconcile(attempt, cancellation=CancellationCause.RECOVERED)
    again = await store.get_attempt(attempt.attempt_id)
    assert again is not None
    assert again.error == "process lost"
    assert first.status == second.status
    assert recorded.events[0].event_id == recorded.events[1].event_id
