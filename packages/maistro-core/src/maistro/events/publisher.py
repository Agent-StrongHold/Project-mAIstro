"""Persist-first publication for the one canonical Event envelope (#61).

The legacy ``EventBus`` remains useful as a trigger/notification adapter while
product families migrate. It is not an identity or ordering authority here:
the canonical store assigns the Workspace sequence first, and the bus receives
a projection carrying that already-persisted identity and sequence.
"""

from __future__ import annotations

import copy
from typing import Any

from maistro.events.bus import Event, EventBus, EventCategory
from maistro.events.envelope import (
    EventAppendDispositionStore,
    EventEnvelope,
    EventStore,
)

CANONICAL_EVENT_METADATA = "_canonical_event"


class CanonicalEventPublisher:
    """Persist a canonical envelope, then notify compatibility consumers.

    Compatibility delivery is intentionally at-most-once with respect to one
    canonical ``event_id``: only the append call that actually inserts the Event
    projects it. A process loss after persistence but before legacy delivery can
    therefore lose that compatibility notification; the legacy bus is not made
    into a second durable delivery authority to close that crash window.
    """

    def __init__(self, store: EventStore, *, legacy_bus: EventBus | None = None) -> None:
        if legacy_bus is not None and not isinstance(store, EventAppendDispositionStore):
            raise TypeError(
                "legacy EventBus projection requires an EventStore with atomic "
                "append disposition"
            )
        self._store = store
        self._legacy_bus = legacy_bus

    @property
    def store(self) -> EventStore:
        """The single durable sequencing authority used by this publisher."""
        return self._store

    async def emit(self, event: EventEnvelope) -> EventEnvelope:
        """Persist ``event`` before any compatibility consumer can observe it."""
        if self._legacy_bus is None:
            return await self._store.append(event)

        # __init__ proves this structural capability before the publisher can be
        # used. Keep the local check for static narrowing and fail closed if an
        # exotic mutable proxy changes shape after construction.
        if not isinstance(self._store, EventAppendDispositionStore):
            raise TypeError(
                "legacy EventBus projection requires an EventStore with atomic "
                "append disposition"
            )
        outcome = await self._store.append_with_disposition(event)
        if outcome.inserted:
            await self._legacy_bus.emit(project_legacy_event(outcome.event))
        return outcome.event


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

    # Compatibility consumers are deliberately mutable. Never expose nested
    # objects shared with the persisted canonical envelope: one old handler
    # must not be able to rewrite historical Event facts in an in-memory store.
    payload: dict[str, Any] = copy.deepcopy(event.payload)
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
