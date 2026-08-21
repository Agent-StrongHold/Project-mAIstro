"""Task state machine — valid transitions and phase tracking."""

from __future__ import annotations

from maistro.tasks.models import TaskStatus

# Valid state transitions
TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {TaskStatus.CODING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.CODING: {
        TaskStatus.REVIEWING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.REVIEWING: {
        TaskStatus.TESTING,
        TaskStatus.CODING,  # reviewer rejects → back to coding
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.TESTING: {
        TaskStatus.COMPLETED,
        TaskStatus.CODING,  # tests fail → back to coding
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}

# Map status to human-readable phase
STATUS_PHASE: dict[TaskStatus, str] = {
    TaskStatus.QUEUED: "queued",
    TaskStatus.PLANNING: "planning",
    TaskStatus.CODING: "coding",
    TaskStatus.REVIEWING: "reviewing",
    TaskStatus.TESTING: "testing",
    TaskStatus.COMPLETED: "completed",
    TaskStatus.FAILED: "failed",
    TaskStatus.CANCELLED: "cancelled",
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in TRANSITIONS.get(current, set())
