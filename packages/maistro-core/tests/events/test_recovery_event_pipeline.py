"""Real recovery producer -> canonical durable Event -> compatibility consumer (#61)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from maistro.events.bus import EventBus, Trigger
from maistro.events.envelope import SqliteEventStore
from maistro.events.publisher import CANONICAL_EVENT_METADATA, CanonicalEventPublisher
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.recovery_events import CanonicalRecoveryEventSink, RECOVERY_EVENT_TYPE


async def _running_attempt() -> tuple[InMemoryRunStore, str, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-recovery-pipeline")
    project = await projects.create(
        workspace_id="workspace-recovery-pipeline",
        parent_project_id=root.project_id,
        name="Recovery pipeline",
    )
    runs = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="workspace-recovery-pipeline",
        project_id=project.project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type="agent")],
    )
    run = await runs.create_run(graph, initial_status=RunStatus.QUEUED)
    run = await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(run.run_id, node_id="step")
    await runs.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await runs.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await runs.create_attempt(node_run.node_run_id, executor_id="worker-1")
    attempt = await runs.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.FAILED,
        error="worker exited",
    )
    return runs, run.run_id, node_run.node_run_id, attempt.attempt_id


async def test_recovery_producer_persists_before_trigger_and_survives_restart(
    tmp_path: Path,
) -> None:
    """The real reconciler emits one canonical identity before legacy notification."""
    database = tmp_path / "events.db"
    conn = await aiosqlite.connect(database)
    event_store = SqliteEventStore(conn)
    await event_store.ensure_schema()
    legacy_bus = EventBus()
    observed: list[tuple[str, int, str]] = []

    async def consume(_trigger: Trigger, event) -> None:
        canonical = await event_store.get(event.event_id)
        assert canonical is not None
        assert canonical.sequence is not None
        metadata = event.payload[CANONICAL_EVENT_METADATA]
        observed.append((canonical.event_id, metadata["sequence"], canonical.run_id))

    legacy_bus.register_handler("capture", consume)
    legacy_bus.add_trigger(
        Trigger(
            name="capture recovery",
            event_types=[RECOVERY_EVENT_TYPE],
            action_type="capture",
            cooldown_seconds=0,
        )
    )
    publisher = CanonicalEventPublisher(event_store, legacy_bus=legacy_bus)
    runs, run_id, node_run_id, attempt_id = await _running_attempt()
    attempt = await runs.get_attempt(attempt_id)
    assert attempt is not None

    sink = CanonicalRecoveryEventSink(runs, publisher)
    await AttemptLifecycleReconciler(runs, events=sink).reconcile(attempt)

    assert len(observed) == 1
    event_id, sequence, observed_run_id = observed[0]
    assert sequence == 1
    assert observed_run_id == run_id
    persisted = await event_store.get(event_id)
    assert persisted is not None
    assert persisted.workspace_id == "workspace-recovery-pipeline"
    assert persisted.run_id == run_id
    assert persisted.node_run_id == node_run_id
    assert persisted.attempt_id == attempt_id
    assert persisted.payload["disposition"] == "parked"
    projected = legacy_bus.get_history()[-1]
    assert projected.event_id == event_id
    assert projected.payload[CANONICAL_EVENT_METADATA]["sequence"] == 1

    await conn.close()

    restarted = await aiosqlite.connect(database)
    restarted_store = SqliteEventStore(restarted)
    await restarted_store.ensure_schema()
    try:
        history = await restarted_store.list_stream("workspace:workspace-recovery-pipeline")
        assert [(event.event_id, event.sequence) for event in history] == [(event_id, 1)]
    finally:
        await restarted.close()
