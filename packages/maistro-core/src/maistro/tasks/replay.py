"""Pure checkpoint-replay fold for task resume (SPEC-256 / ADR-056)."""

from __future__ import annotations

from dataclasses import dataclass

from maistro.tasks.checkpoint import CheckpointKind, TaskCheckpoint


@dataclass(frozen=True)
class ResumeState:
    open_tool_calls: frozenset[str]
    wave_status: dict[str, str]
    cumulative_spend: float
    pending_approval_gates: frozenset[str]


_WAVE_STATUS_BY_KIND = {
    CheckpointKind.WAVE_FAN_OUT: "running",
    CheckpointKind.WAVE_COMPLETED: "completed",
    CheckpointKind.WAVE_FAILED: "failed",
}


def _apply(
    checkpoint: TaskCheckpoint,
    *,
    open_tool_calls: set[str],
    wave_status: dict[str, str],
    pending_approval_gates: set[str],
) -> float:
    payload = checkpoint.payload
    if checkpoint.kind is CheckpointKind.TOOL_CALL_ABOUT_TO_FIRE:
        open_tool_calls.add(payload["call_id"])
    elif checkpoint.kind is CheckpointKind.TOOL_CALL_DONE:
        open_tool_calls.discard(payload["call_id"])
    elif checkpoint.kind in _WAVE_STATUS_BY_KIND:
        # A `state` key marks the ensemble's *task-level* fan-out and completion
        # markers, which describe the whole task and carry `wave_ids`, plural.
        # Both halves of ADR-056 shipped without being run against each other,
        # so folding the checkpoints the ensemble actually writes raised
        # KeyError on `wave_id` (#624). A task-level marker contributes no
        # per-wave status; the per-wave records beside it carry that, and one
        # with neither key is still malformed and still raises.
        if "state" not in payload:
            wave_status[payload["wave_id"]] = _WAVE_STATUS_BY_KIND[checkpoint.kind]
    elif checkpoint.kind is CheckpointKind.APPROVAL_GATE_RAISED:
        pending_approval_gates.add(payload["gate_id"])
    elif checkpoint.kind is CheckpointKind.APPROVAL_GATE_ANSWERED:
        pending_approval_gates.discard(payload["gate_id"])
    elif checkpoint.kind is CheckpointKind.SPEND_UPDATE:
        return float(payload["delta"])
    return 0.0


def replay(checkpoints: tuple[TaskCheckpoint, ...]) -> ResumeState:
    open_tool_calls: set[str] = set()
    wave_status: dict[str, str] = {}
    cumulative_spend = 0.0
    pending_approval_gates: set[str] = set()

    for checkpoint in sorted(checkpoints, key=lambda c: c.sequence):
        cumulative_spend += _apply(
            checkpoint,
            open_tool_calls=open_tool_calls,
            wave_status=wave_status,
            pending_approval_gates=pending_approval_gates,
        )

    return ResumeState(
        open_tool_calls=frozenset(open_tool_calls),
        wave_status=wave_status,
        cumulative_spend=cumulative_spend,
        pending_approval_gates=frozenset(pending_approval_gates),
    )
