"""What recovery says happened, on the canonical Event stream (#462).

The disposition table (ADR-082826-08f0) decides what becomes of interrupted
work. Until now the decision left no trace of its own: a parked NodeRun looks
identical whether recovery parked it or a person paused it, and the reason
survives only inside an Attempt's error string. The Run model stays the record
of *state*; this is the record of *decision*.

The sink is a protocol rather than the `EventBus` itself so the spine keeps
depending on an interface (the repo's DI rule), and so a caller with no bus
wired reconciles exactly as it did -- an unobservable recovery is bad, but a
recovery that refuses to run because nothing is listening would be worse.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from maistro.events.bus import Event, EventCategory
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, NodeRun

#: One event type, because one table decides all of these. The disposition is
#: a payload field rather than a family of event types so a subscriber cannot
#: accidentally listen to some dispositions and not others.
RECOVERY_EVENT_TYPE = "run.recovery_disposition"


@runtime_checkable
class RecoveryEventSink(Protocol):
    """Anything that accepts a canonical Event. `EventBus` satisfies it."""

    async def emit(self, event: Event) -> Any: ...


def disposition_of(attempt: Attempt, cancellation: CancellationCause) -> str:
    """Name the row of the table this Attempt's reconciliation took.

    Derived from the persisted Attempt and the cause, not passed in, so the
    name cannot drift from the transition that was actually applied.
    """
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
) -> Event:
    """Build the event for one applied disposition.

    `correlation_id` is the Run, because that is what someone asking "what
    happened to this Run" already has in hand; the NodeRun and Attempt ids are
    in the payload so the answer can be taken back to the spine and read there.
    """
    return Event(
        category=EventCategory.SYSTEM,
        event_type=RECOVERY_EVENT_TYPE,
        source=source,
        correlation_id=node_run.run_id,
        payload={
            "run_id": node_run.run_id,
            "node_run_id": node_run.node_run_id,
            "attempt_id": attempt.attempt_id,
            "attempt_status": attempt.status.value,
            "node_run_status": node_run.status.value,
            "cancellation_cause": cancellation.value,
            "disposition": disposition_of(attempt, cancellation),
            "error": attempt.error,
        },
    )


__all__ = [
    "RECOVERY_EVENT_TYPE",
    "RecoveryEventSink",
    "disposition_of",
    "recovery_event",
]
