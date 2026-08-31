"""Recovery disposition facts and their canonical Event adapter (#462, #61).

The Run model remains the record of execution state. Recovery owns only the
domain fact describing which disposition was applied. It deliberately owns no
event id, timestamp, sequence, correlation id, or stream identity: those are
universal Event concerns and belong exclusively to :class:`EventEnvelope`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from maistro.events.envelope import EventEnvelope
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, NodeRun, Run

RECOVERY_EVENT_TYPE = "run.recovery_disposition"


@dataclass(frozen=True, slots=True)
class RecoveryDispositionEvent:
    """Package-local recovery fact, not a second universal event envelope."""

    run_id: str
    node_run_id: str
    attempt_id: str
    attempt_status: str
    node_run_status: str
    cancellation_cause: str
    disposition: str
    error: str | None
    source: str

    def payload(self) -> dict[str, Any]:
        """Project the recovery-specific fact into a canonical Event payload."""
        return {
            "run_id": self.run_id,
            "node_run_id": self.node_run_id,
            "attempt_id": self.attempt_id,
            "attempt_status": self.attempt_status,
            "node_run_status": self.node_run_status,
            "cancellation_cause": self.cancellation_cause,
            "disposition": self.disposition,
            "error": self.error,
        }

    def to_legacy_event(self) -> Any:
        """Project onto the pre-#61 trigger bus without owning canonical identity.

        The compatibility ``Event`` minted here is a delivery projection only.
        Its short id and timestamp are not persisted canonical Event identity or
        Workspace ordering; migrated paths use :class:`CanonicalRecoveryEventSink`
        and :class:`CanonicalEventPublisher` before this projection is observed.
        """
        from maistro.events.bus import Event, EventCategory

        return Event(
            category=EventCategory.SYSTEM,
            event_type=RECOVERY_EVENT_TYPE,
            source=self.source,
            correlation_id=self.run_id,
            payload=self.payload(),
        )


@runtime_checkable
class RecoveryEventSink(Protocol):
    """Anything that accepts one recovery-domain fact."""

    async def emit(self, event: RecoveryDispositionEvent) -> Any: ...


@runtime_checkable
class RunLookup(Protocol):
    """The canonical scope lookup needed to envelope a recovery fact."""

    async def get_run(self, run_id: str) -> Run | None: ...


@runtime_checkable
class CanonicalEventSink(Protocol):
    """Publisher/store seam for the one canonical Event envelope."""

    async def emit(self, event: EventEnvelope) -> Any: ...


class CanonicalRecoveryEventSink:
    """Adapt recovery-domain facts onto the canonical Event envelope."""

    def __init__(self, runs: RunLookup, events: CanonicalEventSink) -> None:
        self._runs = runs
        self._events = events

    async def emit(self, event: RecoveryDispositionEvent) -> Any:
        run = await self._runs.get_run(event.run_id)
        if run is None:
            raise ValueError(f"recovery event references unknown Run {event.run_id!r}")
        envelope = EventEnvelope(
            type=RECOVERY_EVENT_TYPE,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            run_id=run.run_id,
            node_run_id=event.node_run_id,
            attempt_id=event.attempt_id,
            correlation_id=run.run_id,
            source=event.source,
            provenance={"legacy_event_category": "system"},
            payload=event.payload(),
        )
        return await self._events.emit(envelope)


def disposition_of(attempt: Attempt, cancellation: CancellationCause) -> str:
    """Name the recovery table row actually applied to ``attempt``."""
    if attempt.status is AttemptStatus.COMPLETED:
        return "accepted"
    if attempt.status is AttemptStatus.CANCELLED:
        return (
            "terminalized"
            if cancellation is CancellationCause.REQUESTED
            else "recovered_and_parked"
        )
    return "parked"


def recovery_event(
    *,
    attempt: Attempt,
    node_run: NodeRun,
    cancellation: CancellationCause,
    source: str,
) -> RecoveryDispositionEvent:
    """Build one recovery-domain fact after the disposition is persisted."""
    return RecoveryDispositionEvent(
        run_id=node_run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        attempt_status=attempt.status.value,
        node_run_status=node_run.status.value,
        cancellation_cause=cancellation.value,
        disposition=disposition_of(attempt, cancellation),
        error=attempt.error,
        source=source,
    )


__all__ = [
    "CanonicalRecoveryEventSink",
    "RECOVERY_EVENT_TYPE",
    "RecoveryDispositionEvent",
    "RecoveryEventSink",
    "disposition_of",
    "recovery_event",
]
