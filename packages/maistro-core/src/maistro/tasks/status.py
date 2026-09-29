"""Task state machine — valid transitions and phase tracking."""

from __future__ import annotations

from maistro.tasks.models import TaskStatus

# Valid state transitions
TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    # QUEUED -> FAILED is legal (#849): a dispatch can fail before the receipt
    # ever reaches PLANNING — the claim refused, the Run refused, the worker
    # died between dequeue and its first phase write. When FAILED was reachable
    # only from PLANNING onward, such a failure left the receipt QUEUED
    # forever: the gauge never decremented and terminal pruning never saw it.
    # The transition is task-driven and still goes through `update_status`, so
    # the Run behind it (when there is one) is advanced or the refusal is
    # honoured — this row only makes the receipt's own failure legal.
    TaskStatus.QUEUED: {TaskStatus.PLANNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
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
