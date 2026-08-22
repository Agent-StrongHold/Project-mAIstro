"""Shared API response schemas used across all endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from maistro.tasks.models import TaskResponse

# --- Error envelope (Item 30) ---


class ErrorDetail(BaseModel):
    type: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# --- Task API response models (Item 29, 35) ---


class TaskCreatedResponse(BaseModel):
    """Response for POST /tasks — returns full task with status."""

    task_id: str
    status: str
    # Canonical execution identity (#41). Surfaced beside task_id because it is
    # what a caller polls the Run spine with; None only where this build admits
    # tasks without a Run.
    run_id: str | None = None
    task: TaskResponse


class RunSummary(BaseModel):
    """The canonical execution state a `run_id` resolves to."""

    run_id: str
    status: str
    workspace_id: str
    project_id: str
    graph_id: str
    #: How the Run entered the system, and what receipt it correlates to —
    #: `admission_source`, `task_id`, `session_id`, `user_id`.
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None


class NodeRunSummary(BaseModel):
    """Per-node execution state under a Run."""

    node_run_id: str
    node_id: str
    status: str
    created_at: datetime
    finished_at: datetime | None = None


class TaskCancelledResponse(BaseModel):
    """Response for DELETE /tasks/{task_id}."""

    cancelled: bool


class PaginatedTasks(BaseModel):
    """Paginated task list response (Item 32)."""

    items: list[TaskResponse]
    next_cursor: str | None = None
    count: int


# --- Webhook response models (Item 29) ---


class WebhookAccepted(BaseModel):
    """Webhook accepted and task queued."""

    task_id: str
    action: str


class WebhookIgnored(BaseModel):
    """Webhook received but no action taken."""

    status: str = "ignored"
    event: str = ""
    action: str = ""


class CIWebhookIgnored(BaseModel):
    """CI webhook received but not a failure."""

    status: str = "ignored"
    ci_status: str = ""


# --- Health response (Item 36) ---


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    service: str
    version: str
