"""Persist-first publication for the one canonical Event envelope (#61).

The legacy ``EventBus`` remains useful as a trigger/notification adapter while
product families migrate. It is not an identity or ordering authority here:
the canonical store assigns the Workspace sequence first, and the bus receives
a projection carrying that already-persisted identity and sequence.
"""

from __future__ import annotations

from typing import Any

from maistro.events.bus import Event, EventBus, EventCategory
from maistro.events.envelope import EventEnvelope, EventStore

CANONICAL_EVENT_METADATA = "_canonical_event"


class CanonicalEventPublisher:
    """Persist a canonical envelope, then notify compatibility consumers."""

    def __init__(self, store: EventStore, *, legacy_bus: EventBus | None = None) -> None:
        self._store = store
        self._legacy_bus = legacy_bus

    @property
    def store(self) -> EventStore:
        """The single durable sequencing authority used by this publisher."""
        return self._store

    async def emit(self, event: EventEnvelope) -> EventEnvelope:
        """Persist ``event`` before any compatibility consumer can observe it."""
        persisted = await self._store.append(event)
        if self._legacy_bus is not None:
            await self._legacy_bus.emit(project_legacy_event(persisted))
        return persisted


def project_legacy_event(event: EventEnvelope) -> Event:
    """Project a persisted canonical envelope onto the pre-#61 reactor bus.

    The legacy object deliberately reuses the canonical ``event_id`` and
    timestamp. Its payload receives the canonical stream cursor as metadata so
    old consumers can bridge back to the authoritative record. The integer id
    later assigned by ``LoggedEvent`` is therefore only the legacy reactor's
    delivery cursor, not a second universal event identity.
    """
    if event.sequence is None:
        raise ValueError("legacy projection requires a persisted canonical Event sequence")

    category_name = str(event.provenance.get("legacy_event_category", "system"))
    try:
        category = EventCategory(category_name)
    except ValueError:
        category = EventCategory.SYSTEM

    payload: dict[str, Any] = dict(event.payload)
    payload[CANONICAL_EVENT_METADATA] = {
        "event_id": event.event_id,
        "stream_id": event.stream_id,
        "sequence": event.sequence,
        "workspace_id": event.workspace_id,
        "project_id": event.project_id,
        "run_id": event.run_id,
        "node_run_id": event.node_run_id,
        "attempt_id": event.attempt_id,
        "invocation_id": event.invocation_id,
        "session_id": event.session_id,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
    }
    return Event(
        event_id=event.event_id,
        category=category,
        event_type=event.type,
        source=event.source,
        payload=payload,
        timestamp=event.timestamp,
        correlation_id=event.correlation_id,
    )


__all__ = [
    "CANONICAL_EVENT_METADATA",
    "CanonicalEventPublisher",
    "project_legacy_event",
]
