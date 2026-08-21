"""Shared API response schemas used across all endpoints."""

from __future__ import annotations

from pydantic import BaseModel

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
    task: TaskResponse


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
