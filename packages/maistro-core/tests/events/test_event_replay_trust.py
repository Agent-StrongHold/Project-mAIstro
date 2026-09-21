"""Adversarial trust evidence for canonical Event replay and compatibility mutation."""

from __future__ import annotations

from types import SimpleNamespace

from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.events.publisher import CanonicalEventPublisher, project_legacy_event
from maistro.runs.recovery_events import CanonicalRecoveryEventSink, RecoveryDispositionEvent


class _RunLookup:
    async def get_run(self, run_id: str):
        if run_id != "run-replay":
            return None
        return SimpleNamespace(
            run_id="run-replay",
            workspace_id="workspace-replay",
            project_id="project-replay",
        )


async def test_replayed_recovery_fact_reuses_one_canonical_event_identity() -> None:
    """At-least-once recovery delivery must not become two canonical facts."""
    store = InMemoryEventStore()
    publisher = CanonicalEventPublisher(store)
    sink = CanonicalRecoveryEventSink(_RunLookup(), publisher)
    fact = RecoveryDispositionEvent(
        run_id="run-replay",
        node_run_id="node-replay",
        attempt_id="attempt-replay",
        attempt_status="cancelled",
        node_run_status="waiting",
        cancellation_cause="recovered",
        disposition="recovered_and_parked",
        error="worker exited",
        source="trust-test",
    )

    first = await sink.emit(fact)
    replay = await sink.emit(fact)

    assert replay.event_id == first.event_id
    assert replay.sequence == first.sequence == 1
    persisted = await store.list_stream("workspace:workspace-replay")
    assert [event.event_id for event in persisted] == [first.event_id]


def test_legacy_projection_cannot_mutate_nested_canonical_payload() -> None:
    """A mutable compatibility consumer must not rewrite persisted Event facts."""
    canonical = EventEnvelope(
        event_id="nested-event",
        type="trust.nested",
        workspace_id="workspace-replay",
        sequence=1,
        payload={"nested": {"values": ["original"]}},
    )

    projected = project_legacy_event(canonical)
    projected.payload["nested"]["values"].append("legacy-mutation")

    assert canonical.payload == {"nested": {"values": ["original"]}}
