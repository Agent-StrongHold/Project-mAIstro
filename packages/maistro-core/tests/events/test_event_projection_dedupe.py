"""Replay/concurrency trust tests for canonical-to-legacy Event projection (#1093)."""

from __future__ import annotations

import asyncio

import pytest

from maistro.events.bus import EventBus, Trigger
from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.events.publisher import CanonicalEventPublisher


def _legacy_bus(side_effects: list[str]) -> EventBus:
    bus = EventBus()

    async def capture(_trigger: Trigger, event) -> None:
        side_effects.append(event.event_id)

    bus.register_handler("capture", capture)
    bus.add_trigger(
        Trigger(
            name="capture canonical projection",
            event_types=["run.recovery_disposition"],
            action_type="capture",
            cooldown_seconds=0,
        )
    )
    return bus


def _event(event_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        type="run.recovery_disposition",
        workspace_id="workspace-replay",
        run_id="run-replay",
        provenance={"legacy_event_category": "system"},
        payload={"disposition": "recovered_and_parked"},
    )


@pytest.mark.asyncio
async def test_replaying_same_canonical_event_does_not_repeat_legacy_side_effect() -> None:
    store = InMemoryEventStore()
    side_effects: list[str] = []
    bus = _legacy_bus(side_effects)
    publisher = CanonicalEventPublisher(store, legacy_bus=bus)
    event = _event("stable-recovery-event")

    first = await publisher.emit(event)
    replay = await publisher.emit(event)

    assert replay == first
    assert side_effects == ["stable-recovery-event"]
    assert [item.event_id for item in bus.get_history()] == ["stable-recovery-event"]
    assert [item.event_id for item in await store.list_stream(event.stream_id)] == [
        "stable-recovery-event"
    ]


@pytest.mark.asyncio
async def test_new_publisher_replay_does_not_repeat_mutable_legacy_side_effect() -> None:
    """A restarted publisher must respect durable canonical idempotency."""
    store = InMemoryEventStore()
    side_effects: list[str] = []
    bus = _legacy_bus(side_effects)
    event = _event("restart-recovery-event")

    await CanonicalEventPublisher(store, legacy_bus=bus).emit(event)
    await CanonicalEventPublisher(store, legacy_bus=bus).emit(event)

    assert side_effects == ["restart-recovery-event"]
    assert len(bus.get_history()) == 1


@pytest.mark.asyncio
async def test_concurrent_publishers_converge_on_one_legacy_delivery() -> None:
    store = InMemoryEventStore()
    side_effects: list[str] = []
    bus = _legacy_bus(side_effects)
    left = CanonicalEventPublisher(store, legacy_bus=bus)
    right = CanonicalEventPublisher(store, legacy_bus=bus)
    event = _event("raced-recovery-event")

    first, second = await asyncio.gather(left.emit(event), right.emit(event))

    assert first == second
    assert first.sequence == 1
    assert side_effects == ["raced-recovery-event"]
    assert len(bus.get_history()) == 1


@pytest.mark.asyncio
async def test_distinct_canonical_ids_still_deliver_when_facts_match() -> None:
    store = InMemoryEventStore()
    side_effects: list[str] = []
    bus = _legacy_bus(side_effects)
    publisher = CanonicalEventPublisher(store, legacy_bus=bus)

    first = await publisher.emit(_event("recovery-event-one"))
    second = await publisher.emit(_event("recovery-event-two"))

    assert (first.sequence, second.sequence) == (1, 2)
    assert side_effects == ["recovery-event-one", "recovery-event-two"]
    assert [item.event_id for item in bus.get_history()] == [
        "recovery-event-one",
        "recovery-event-two",
    ]


def test_legacy_projection_rejects_store_without_atomic_append_disposition() -> None:
    class AppendOnlyStore:
        async def append(self, event: EventEnvelope) -> EventEnvelope:
            return event

        async def get(self, event_id: str) -> EventEnvelope | None:
            return None

        async def list_stream(
            self,
            stream_id: str,
            *,
            after_sequence: int = 0,
            limit: int = 100,
        ) -> list[EventEnvelope]:
            return []

    with pytest.raises(TypeError, match="atomic append disposition"):
        CanonicalEventPublisher(AppendOnlyStore(), legacy_bus=EventBus())
