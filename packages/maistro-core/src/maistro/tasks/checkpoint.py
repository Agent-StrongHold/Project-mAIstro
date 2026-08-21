"""Task checkpoint types for crash recovery (SPEC-256 / ADR-056)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class CheckpointKind(StrEnum):
    TOOL_CALL_ABOUT_TO_FIRE = "tool_call.about_to_fire"
    TOOL_CALL_DONE = "tool_call.done"
    WAVE_FAN_OUT = "wave.fan_out"
    WAVE_COMPLETED = "wave.completed"
    WAVE_FAILED = "wave.failed"
    APPROVAL_GATE_RAISED = "approval.gate.raised"
    APPROVAL_GATE_ANSWERED = "approval.gate.answered"
    SPEND_UPDATE = "spend.update"
    MEMORY_PROMOTE = "memory.promote"


@dataclass(frozen=True)
class TaskCheckpoint:
    task_id: str
    sequence: int
    kind: CheckpointKind
    payload: dict[str, Any]
    recipe_version: str
    code_registry_version: str
    created_at: datetime
