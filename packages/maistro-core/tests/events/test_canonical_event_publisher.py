"""Behavioral convergence evidence for canonical Event publication (#61)."""

from __future__ import annotations

from maistro.events.bus import EventBus, EventCategory, Trigger
from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.events.publisher import (
    CANONICAL_EVENT_METADATA,
    CanonicalEventPublisher,
    project_legacy_event,
)


async def test_real_publisher_path_persists_before_legacy_consumer() -> None:
    store = InMemoryEventStore()
    legacy_bus = EventBus()
    observed: list[tuple[str, int, str]] = []

    async def handler(_trigger: Trigger, event) -> None:
        persisted = await store.get(event.event_id)
        assert persisted is not None
        assert persisted.sequence is not None
        metadata = event.payload[CANONICAL_EVENT_METADATA]
        observed.append((event.event_id, metadata["sequence"], persisted.workspace_id))

    legacy_bus.register_handler("capture", handler)
    legacy_bus.add_trigger(
        Trigger(
            name="capture recovery",
            event_types=["run.recovery_disposition"],
            action_type="capture",
            cooldown_seconds=0,
        )
    )
    publisher = CanonicalEventPublisher(store, legacy_bus=legacy_bus)

    persisted = await publisher.emit(
        EventEnvelope(
            event_id="canonical-recovery-1",
            type="run.recovery_disposition",
            workspace_id="workspace-a",
            project_id="project-a",
            run_id="run-a",
            node_run_id="node-a",
            attempt_id="attempt-a",
            correlation_id="run-a",
            provenance={"legacy_event_category": "system"},
            payload={"disposition": "recovered_and_parked"},
        )
    )

    assert persisted.sequence == 1
    assert observed == [("canonical-recovery-1", 1, "workspace-a")]
    projected = legacy_bus.get_history()[-1]
    assert projected.event_id == persisted.event_id
    assert projected.timestamp == persisted.timestamp
    assert projected.correlation_id == persisted.correlation_id
    assert projected.payload[CANONICAL_EVENT_METADATA]["stream_id"] == "workspace:workspace-a"


async def test_publisher_uses_one_sequence_authority_per_workspace() -> None:
    store = InMemoryEventStore()
    publisher = CanonicalEventPublisher(store)
    first = await publisher.emit(
        EventEnvelope(event_id="a-1", type="one", workspace_id="workspace-a")
    )
    other = await publisher.emit(
        EventEnvelope(event_id="b-1", type="one", workspace_id="workspace-b")
    )
    second = await publisher.emit(
        EventEnvelope(event_id="a-2", type="two", workspace_id="workspace-a")
    )

    assert (first.sequence, second.sequence) == (1, 2)
    assert other.sequence == 1


async def test_legacy_projection_refuses_unpersisted_envelope() -> None:
    from maistro.events.publisher import project_legacy_event

    event = EventEnvelope(type="run.recovery_disposition", workspace_id="workspace-a")

    try:
        project_legacy_event(event)
    except ValueError as exc:
        assert "persisted canonical Event sequence" in str(exc)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("unpersisted Event was projected onto the legacy bus")


def test_the_publisher_exposes_its_single_sequence_authority() -> None:
    """There is exactly one durable sequencing authority per publisher."""
    store = InMemoryEventStore()

    assert CanonicalEventPublisher(store).store is store


def test_legacy_projection_carries_a_declared_category() -> None:
    persisted = EventEnvelope(
        event_id="canonical-trading-1",
        type="order.filled",
        workspace_id="workspace-a",
        sequence=1,
        provenance={"legacy_event_category": "trading"},
    )

    assert project_legacy_event(persisted).category is EventCategory.TRADING


def test_an_unknown_category_name_falls_back_to_system() -> None:
    persisted = EventEnvelope(
        event_id="canonical-odd-1",
        type="order.filled",
        workspace_id="workspace-a",
        sequence=1,
        provenance={"legacy_event_category": "galactic"},
    )

    projected = project_legacy_event(persisted)

    assert projected.category is EventCategory.SYSTEM
    assert projected.event_id == "canonical-odd-1"
