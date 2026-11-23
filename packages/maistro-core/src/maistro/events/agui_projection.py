"""Read-only AG-UI projection of canonical Workspace events.

This adapter is deliberately not an execution API. It emits AG-UI CUSTOM events
from an explicitly allowlisted canonical event vocabulary. It never treats
client-supplied state as authority, and does not implement replay or HITL writes.
The owning API must authorize Workspace access before calling this adapter.
"""

from __future__ import annotations

from typing import Any, Literal

from maistro.events.envelope import EventEnvelope

# Adding event types requires review of payload redaction and client visibility.
PUBLIC_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "run.started",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "node_run.started",
        "node_run.completed",
        "node_run.failed",
    }
)


def project_agui_event(event: EventEnvelope) -> dict[str, Any] | None:
    """Project a canonical event into an AG-UI CUSTOM event, or suppress it.

    Only stable identifiers and the lifecycle event name cross this boundary.
    Opaque canonical payload/provenance are intentionally excluded.
    """
    if event.type not in PUBLIC_EVENT_TYPES:
        return None
    if not event.workspace_id or not event.run_id or event.sequence is None:
        return None

    value: dict[str, str | int] = {
        "eventId": event.event_id,
        "workspaceId": event.workspace_id,
        "runId": event.run_id,
        "sequence": event.sequence,
        "lifecycle": event.type,
    }
    if event.node_run_id:
        value["nodeRunId"] = event.node_run_id
    if event.attempt_id:
        value["attemptId"] = event.attempt_id

    return {"type": "CUSTOM", "name": "maistro.lifecycle", "value": value}

# This is a protocol-versioned *projection*, not an AG-UI session/runtime.
# Version 1.0 requires a producer to declare its protocol on RUN_STARTED.
# A future SDK integration should take this value from the pinned SDK constant.
AGUI_PROTOCOL_VERSION = "1.0"


def project_agui_run_start(*, thread_id: str, run_id: str) -> dict[str, str]:
    """Start an AG-UI stream for an *authorized* canonical Run snapshot.

    The caller must obtain the Run from a principal-scoped canonical reader.
    An AG-UI thread is presentation identity; it is not a Workspace/Run store.
    """
    if not thread_id.strip() or not run_id.strip():
        raise ValueError("thread_id and run_id must be nonempty")
    return {
        "type": "RUN_STARTED",
        "threadId": thread_id,
        "runId": run_id,
        "protocolVersion": AGUI_PROTOCOL_VERSION,
    }


def project_agui_run_terminal(
    *, thread_id: str, run_id: str,
    status: Literal["completed", "failed", "cancelled", "timed_out", "created", "queued", "running", "waiting", "paused"],
) -> dict[str, Any] | None:
    """Only canonical terminal Run statuses can close the AG-UI run stream.

    A failed Run emits a generic error to avoid copying sensitive canonical
    exception text; cancelled is *not* successful completion. Nonterminal Runs
    must remain open for further observation rather than fabricate finality.
    """
    if not thread_id.strip() or not run_id.strip():
        raise ValueError("thread_id and run_id must be nonempty")
    if status == "completed":
        return {"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id}
    if status == "cancelled":
        return {
            "type": "RUN_FINISHED",
            "threadId": thread_id,
            "runId": run_id,
            "outcome": {"type": "cancelled"},
        }
    if status == "failed":
        return {
            "type": "RUN_ERROR",
            "message": "The run failed.",
            "code": "maistro.run.failed",
        }
    if status == "timed_out":
        return {"type": "RUN_ERROR", "message": "The run timed out.", "code": "maistro.run.timed_out"}
    if status in {"created", "queued", "running", "waiting", "paused"}:
        return None
    raise ValueError("unrecognized canonical run status")


def project_agui_run_events(
    events: list[EventEnvelope],
    *,
    workspace_id: str,
    run_id: str,
    after_sequence: int = 0,
) -> list[dict[str, Any]]:
    """Filter authorized persisted EventStore rows to one canonical Run.

    Does not read from the EventStore or perform authorization. Call only after
    Workspace membership and Run readability have been checked at the existing
    principal-scoped inspection boundary. Returns ordered, deduplicated CUSTOM
    events; unknown and cross-Run types never become client messages.
    """
    if not workspace_id.strip() or not run_id.strip() or after_sequence < 0:
        raise ValueError("invalid workspace/run/cursor")
    projected: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    for event in sorted(events, key=lambda item: item.sequence or 0):
        sequence = event.sequence
        if (event.workspace_id != workspace_id or event.run_id != run_id or
                sequence is None or sequence <= after_sequence or
                sequence in seen_sequences):
            continue
        seen_sequences.add(sequence)
        frame = project_agui_event(event)
        if frame is not None:
            projected.append(frame)
    return projected
