"""Task domain models — Pydantic schemas for the task API."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from maistro.tasks.lanes import Lane


class TaskStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    """Request body for POST /tasks."""

    description: str
    # The string "/tmp/maistro-workspace" is the API contract for the
    # workspace mount root (see ALLOWED_HOST_ROOTS in tools/sandbox/
    # workspace.py). It is validated before any fs op; bandit's B108 sees
    # the literal but cannot see the validator gate.
    workspace: str = "/tmp/maistro-workspace"  # nosec B108 — gated by validate_workspace_path
    tier: int | None = None
    branch: str | None = None
    constraints: list[str] = Field(default_factory=list)
    # ADR-010 scheduling lane. Defaults to BACKGROUND so existing callers are
    # unchanged; the chat path tags LIVE to claim the reserved fast-lane slots.
    lane: Lane = Lane.BACKGROUND
    # ADR-070426-b5e9 six-tier label. Orders waiters within a lane. P2 is
    # "user-missions", the normal default for a submitted task.
    priority_tier: Literal["P0", "P1", "P2", "P3", "P4", "P5"] = "P2"
    task_type: str | None = None
    agent_id: str | None = None
    capability: str | None = None
    program_context: dict[str, Any] | None = None
    session_id: str | None = None
    # Set by API from auth — ignored if sent by client
    user_id: str | None = None


class TaskProgress(BaseModel):
    subtasks: int = 0
    completed: int = 0
    current: str = ""


class TaskResult(BaseModel):
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: int | None = None
    tests_failed: int | None = None
    review_score: float | None = None
    branch: str | None = None
    commit: str | None = None
    error: str | None = None


class TaskResponse(BaseModel):
    """Response body for GET /tasks/:id."""

    task_id: str
    status: TaskStatus
    description: str
    workspace: str
    user_id: str = ""
    task_type: str | None = None
    agent_id: str | None = None
    capability: str | None = None
    program_context: dict[str, Any] | None = None
    tier: int
    # Carried through from TaskCreate so the dispatcher can admit on them.
    # Without these on the stored task the lane/tier labels are accepted at
    # the API boundary and silently dropped before scheduling ever sees them.
    lane: Lane = Lane.BACKGROUND
    priority_tier: Literal["P0", "P1", "P2", "P3", "P4", "P5"] = "P2"
    phase: str | None = None
    progress: TaskProgress = Field(default_factory=TaskProgress)
    result: TaskResult | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]
