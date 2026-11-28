"""Persist-first publication for the one canonical Event envelope (#61).

The legacy ``EventBus`` remains useful as a trigger/notification adapter while
product families migrate. It is not an identity or ordering authority here:
the canonical store assigns the Workspace sequence first, and the bus receives
a projection carrying that already-persisted identity and sequence.
"""

from __future__ import annotations

import copy
from typing import Any, Protocol

from maistro.events.bus import CANONICAL_EVENT_METADATA, Event, EventBus, EventCategory
from maistro.events.durable_log import append_from_bus_event
from maistro.events.envelope import (
    EventAppendDispositionStore,
    EventEnvelope,
    EventStore,
)


class ProjectionStreamRegistry(Protocol):
    """Durable registrar of the streams the canonical-log projector must scan (#2506).

    The publisher registers a stream BEFORE its canonical append: a stream
    registered at its current high-water sequence guarantees every sequence
    that append allocates lands above the projector's starting position. A
    bridge append that fails after the canonical commit therefore leaves the
    event inside a tracked, scan-reachable range instead of outside it — that
    ordering is what makes the projection replayable rather than lossy.
    """

    async def register_stream(self, stream_id: str) -> None: ...


class CanonicalEventPublisher:
    """Persist a canonical envelope, then notify compatibility consumers.

    Compatibility delivery is intentionally at-most-once with respect to one
    canonical ``event_id``: only the append call that actually inserts the Event
    projects it. A process loss after persistence but before legacy delivery can
    therefore lose that compatibility notification; the legacy bus is not made
    into a second durable delivery authority to close that crash window.

    The durable trigger ingress is separate (#2506): with a
    ``projection_registry``, the publisher durably registers each event's stream
    before appending, so the replayable canonical-Envelope -> ADR-086 log
    projector can heal any bridge-append failure from canonical authority —
    the registry write failing fails the emit before anything commits, rather
    than committing an Event no durable ingress will ever scan.
    """

    def __init__(
        self,
        store: EventStore,
        *,
        legacy_bus: EventBus | None = None,
        projection_registry: ProjectionStreamRegistry | None = None,
    ) -> None:
        if legacy_bus is not None and not isinstance(store, EventAppendDispositionStore):
            raise TypeError(
                "legacy EventBus projection requires an EventStore with atomic append disposition"
            )
        self._store = store
        self._legacy_bus = legacy_bus
        self._projection_registry = projection_registry

    @property
    def store(self) -> EventStore:
        """The single durable sequencing authority used by this publisher."""
        return self._store

    async def emit(self, event: EventEnvelope) -> EventEnvelope:
        """Persist ``event`` before any compatibility consumer can observe it."""
        if self._projection_registry is not None:
            # Before the append, not after: the registry places new streams at
            # the current canonical watermark, so a crash after this write but
            # before the append costs an empty tracked range, while a crash or
            # bridge failure after the append still leaves the committed Event
            # scan-reachable (#2506). Failing here commits nothing — an Event
            # that cannot be durably tracked must not silently become durable.
            await self._projection_registry.register_stream(event.stream_id)

        if self._legacy_bus is None:
            return await self._store.append(event)

        # __init__ proves this structural capability before the publisher can be
        # used. Keep the local check for static narrowing and fail closed if an
        # exotic mutable proxy changes shape after construction.
        if not isinstance(self._store, EventAppendDispositionStore):
            raise TypeError(
                "legacy EventBus projection requires an EventStore with atomic append disposition"
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


def canonical_log_append_kwargs(event: EventEnvelope) -> dict[str, Any]:
    """The durable-log append kwargs for one persisted canonical Event (#2506).

    Deliberately routes through the same legacy projection the live bridge
    uses (:func:`project_legacy_event` -> :func:`append_from_bus_event`), so a
    projector-healed row is indistinguishable from a bridge-appended row:
    same event-type mapping, same canonical-identity payload metadata, and
    ``source_event_id`` naming the canonical ``event_id`` the log dedupes on.
    Requires a persisted sequence — the projector only ever sees
    store-assigned Events.
    """
    kwargs = append_from_bus_event(project_legacy_event(event))
    kwargs["source_event_id"] = event.event_id
    return kwargs


__all__ = [
    "CANONICAL_EVENT_METADATA",
    "CanonicalEventPublisher",
    "canonical_log_append_kwargs",
    "project_legacy_event",
]
