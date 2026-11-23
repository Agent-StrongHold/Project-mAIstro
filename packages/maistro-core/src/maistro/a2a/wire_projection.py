"""Read-only A2A v1 Task status projection over the canonical Run identity.

This is a deliberate, status-only compatibility *slice*. It is not an A2A
HTTP endpoint, message adapter, artifact serializer, or independent task store.
Callers MUST obtain a Run through the principal-scoped reader first; never
accept caller-supplied Run objects or status values from transport JSON.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from maistro.runs.model import Run, RunStatus


class A2AProjectionError(ValueError):
    """A Run cannot be safely represented as an A2A Task snapshot."""


# Exact public A2A protobuf enumeration names (v1 a2a.proto TaskState).
# WAITING/PAUSED do not imply a human needs input. Only a verified canonical
# HITL pause can be projected as INPUT_REQUIRED, in a separate reviewed seam.
_TASK_STATE: dict[RunStatus, str] = {
    RunStatus.CREATED: "TASK_STATE_SUBMITTED",
    RunStatus.QUEUED: "TASK_STATE_SUBMITTED",
    RunStatus.RUNNING: "TASK_STATE_WORKING",
    RunStatus.WAITING: "TASK_STATE_WORKING",
    RunStatus.PAUSED: "TASK_STATE_WORKING",
    RunStatus.COMPLETED: "TASK_STATE_COMPLETED",
    RunStatus.FAILED: "TASK_STATE_FAILED",
    RunStatus.CANCELLED: "TASK_STATE_CANCELED",
    RunStatus.TIMED_OUT: "TASK_STATE_FAILED",
}


def project_a2a_task_status(run: Run, *, context_id: str) -> dict[str, Any]:
    """Produce a bounded A2A JSON Task status snapshot.

    The caller provides an already-established, nonsecret A2A context identity
    that is durably linked to this Run. No Workspace, principal, provenance,
    prompt, error, result, or private Graph data are serialized.

    A completed Task's artifacts and streaming history are intentionally NOT
    projected. The upcoming A2A edge API must use explicit, governed output
    projection rather than sending arbitrary Run.result across the boundary.
    """
    if not run.run_id.strip() or not context_id.strip():
        raise A2AProjectionError("run_id and context_id must be nonempty")
    status = _TASK_STATE.get(run.status)
    if status is None:
        raise A2AProjectionError("unsupported canonical Run status")
    if run.updated_at.tzinfo is None:
        raise A2AProjectionError("canonical timestamp must include timezone")
    timestamp = run.updated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "id": run.run_id,
        "contextId": context_id,
        "status": {"state": status, "timestamp": timestamp},
    }
