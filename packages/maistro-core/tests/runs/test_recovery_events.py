"""Recovery says what it decided, on the canonical Event stream (#462).

The disposition table (ADR-082826-08f0) decides what becomes of interrupted
work, and until now the decision left no trace of its own. A parked NodeRun
looks the same whether recovery parked it or a person paused it; the reason
survived only inside an Attempt's error string. The Run model stays the record
of state — this is the record of the decision.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from maistro.events.bus import Event, EventCategory
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, CancellationCause, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.recovery_events import RECOVERY_EVENT_TYPE


class _RecordingSink:
    """Stands in for the EventBus, which it structurally satisfies."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> list[Any]:
        self.events.append(event)
        return []


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


async def _cancelled_attempt(store: InMemoryRunStore, node_run_id: str) -> Any:
    attempt = await store.create_attempt(node_run_id, executor_id="worker-1")
    return await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.CANCELLED,
        error="orphaned physical Attempt recovered after process loss",
    )


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_recovered_cancellation_says_so_on_the_event_stream() -> None:
    """The disposition, not just the resulting state: a parked NodeRun is
    indistinguishable from a paused one without it."""
    store, run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)
    sink = _RecordingSink()
    reconciler = AttemptLifecycleReconciler(store, events=sink)

    await reconciler.reconcile(attempt, cancellation=CancellationCause.RECOVERED)

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.event_type == RECOVERY_EVENT_TYPE
    assert event.category is EventCategory.SYSTEM
    assert event.correlation_id == run_id
    assert event.payload["disposition"] == "recovered_and_parked"
    assert event.payload["cancellation_cause"] == "recovered"
    assert event.payload["node_run_status"] == RunStatus.WAITING.value


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_requested_cancellation_is_a_different_disposition() -> None:
    """The two meanings of a CANCELLED Attempt reach opposite rows of the
    table, so an event that could not tell them apart would be useless."""
    store, _run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)
    sink = _RecordingSink()
    reconciler = AttemptLifecycleReconciler(store, events=sink)

    await reconciler.reconcile(attempt, cancellation=CancellationCause.REQUESTED)

    assert sink.events[0].payload["disposition"] == "terminalized"
    assert sink.events[0].payload["node_run_status"] == RunStatus.CANCELLED.value


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_the_ids_take_the_reader_back_to_the_spine() -> None:
    """Inspectable through the same Run model is half the criterion; the event
    has to carry enough to get there."""
    store, run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)
    sink = _RecordingSink()

    await AttemptLifecycleReconciler(store, events=sink).reconcile(attempt)

    payload = sink.events[0].payload
    assert payload["run_id"] == run_id
    assert payload["node_run_id"] == node_run_id
    assert payload["attempt_id"] == attempt.attempt_id
    assert await store.get_run(payload["run_id"]) is not None
    assert await store.get_attempt(payload["attempt_id"]) is not None


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_an_accepted_outcome_is_announced_as_accepted() -> None:
    """Not every reconciliation is a recovery. Replaying a completed Attempt
    after a crash between acceptance and settlement is the same seam, and
    reporting it as a recovery would misdescribe it."""
    store, _run_id, node_run_id = await _running_node()
    attempt = await store.create_attempt(node_run_id, executor_id="worker-1")
    attempt = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"text": "done"}
    )
    sink = _RecordingSink()

    await AttemptLifecycleReconciler(store, events=sink).reconcile(attempt)

    assert sink.events[0].payload["disposition"] == "accepted"
    assert sink.events[0].payload["node_run_status"] == RunStatus.COMPLETED.value


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_without_a_sink_recovery_still_happens() -> None:
    """An unobservable recovery is the gap this closes. A recovery that
    refused to run because nothing was listening would be a worse one."""
    store, _run_id, node_run_id = await _running_node()
    attempt = await _cancelled_attempt(store, node_run_id)

    parked = await AttemptLifecycleReconciler(store).reconcile(attempt)

    assert parked.status is RunStatus.WAITING


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_the_lease_sweep_announces_what_it_reclaimed() -> None:
    """The producer path #462 names: the sweep decides a disposition for work
    whose owner went quiet, and nothing was recording that it had."""
    from maistro.events.bus import EventBus

    store, run_id, node_run_id = await _running_node()
    attempt = await store.create_attempt(
        node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)

    bus = EventBus()
    seen: list[Event] = []
    original = bus.emit

    async def _capture(event: Event) -> Any:
        seen.append(event)
        return await original(event)

    bus.emit = _capture  # type: ignore[method-assign]
    reclaimed = await store.reclaim_expired_attempts(now=after)
    assert len(reclaimed) == 1
    await AttemptLifecycleReconciler(
        store, events=bus, source="maistro.container.recover_abandoned_attempts"
    ).reconcile(reclaimed[0])

    assert [event.payload["disposition"] for event in seen] == ["recovered_and_parked"]
    assert seen[0].source == "maistro.container.recover_abandoned_attempts"
    assert seen[0].payload["run_id"] == run_id
