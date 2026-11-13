"""Read-only AG-UI projection of canonical Workspace events.

This adapter is deliberately not an execution API. It emits AG-UI CUSTOM events
from an explicitly allowlisted canonical event vocabulary. It never treats
client-supplied state as authority, and does not implement replay or HITL writes.
The owning API must authorize Workspace access before calling this adapter.
"""

from __future__ import annotations

from typing import Any, Mapping

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
