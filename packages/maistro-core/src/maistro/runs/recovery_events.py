"""What recovery says happened, on the canonical Event stream (#462, #61).

The disposition table (ADR-082826-08f0) decides what becomes of interrupted
work. The Run model stays the record of *state*; this is the record of the
*decision*. Universal identity and Workspace ordering belong to the canonical
Event envelope. Recovery-specific facts remain domain payload.

The sink is a protocol rather than a concrete publisher so the execution spine
keeps depending on an interface. A caller with no event sink still reconciles;
missing observability must never prevent lifecycle repair.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from maistro.events.envelope import EventEnvelope
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, NodeRun, Run

#: One event type, because one table decides all of these. The disposition is
#: a payload field rather than a family of event types so a subscriber cannot
#: accidentally listen to some dispositions and not others.
RECOVERY_EVENT_TYPE = "run.recovery_disposition"


@runtime_checkable
class RecoveryEventSink(Protocol):
    """Anything that accepts a canonical :class:`EventEnvelope`."""

    async def emit(self, event: EventEnvelope) -> Any: ...


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
    run: Run,
    attempt: Attempt,
    node_run: NodeRun,
    cancellation: CancellationCause,
    source: str,
) -> EventEnvelope:
    """Build the canonical envelope for one applied disposition.

    Scope and execution identity live on the envelope. The legacy event
    category is compatibility metadata only; the adapter may use it when
    projecting this canonical event onto the pre-#61 in-memory EventBus.
    """
    return EventEnvelope(
        type=RECOVERY_EVENT_TYPE,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        correlation_id=run.run_id,
        source=source,
        provenance={"legacy_event_category": "system"},
        payload={
            # Retained for compatibility with domain consumers that historically
            # read these ids from the payload. They are projections only; the
            # envelope fields above are the universal identity authority.
            "run_id": run.run_id,
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
