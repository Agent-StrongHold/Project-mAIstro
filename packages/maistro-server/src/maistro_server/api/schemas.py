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


class AttemptSummary(BaseModel):
    """One physical try under a NodeRun, and the agent it dispatched to.

    `Attempt.result` and `Attempt.error` are left out on purpose: they can carry
    raw provider or exception text, which must not reach whoever holds a run_id
    (see `maistro.runs.chat_admission`).
    """

    attempt_id: str
    ordinal: int
    status: str
    executor_id: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: The agent a chat turn dispatched to (ADR-082526-7f02); null where the
    #: Attempt recorded none, as for a task.
    agent: str | None = None


class NodeRunSummary(BaseModel):
    """Per-node execution state under a Run."""

    node_run_id: str
    node_id: str
    status: str
    created_at: datetime
    finished_at: datetime | None = None
    attempts: list[AttemptSummary] = Field(default_factory=list)


class TaskCancelledResponse(BaseModel):
    """Response for DELETE /tasks/{task_id}.

    `cancelled` means the cancellation was accepted and the canonical Run is
    durably fenced. It has never meant "the provider stopped", and #1242 makes
    that explicit rather than implied: `disposition` / `stop_confirmed` carry
    the physical evidence, which is a different fact whenever the work is
    running under a worker this replica cannot signal.
    """

    cancelled: bool
    #: `stop_confirmed` | `stop_pending` | `uncertain` | `completion_won`.
    #: Required, with no default: a producer that has not established physical
    #: evidence must say so explicitly rather than inherit "confirmed".
    disposition: str
    #: True only when every physical try the cancellation observed is durably
    #: terminal, or no physical try existed.
    stop_confirmed: bool
    diagnosis: str
    #: The canonical Run behind the receipt, when there is one.
    run_id: str | None = None


class AttemptCancellationSummary(BaseModel):
    """One physical try's cancellation evidence (#1242).

    `Attempt.result`/`error` are left out for the same reason `AttemptSummary`
    leaves them out: they can carry raw provider or exception text that must
    not reach whoever holds a run_id.
    """

    attempt_id: str
    node_run_id: str
    status: str
    disposition: str
    #: The lease holder that would have to stop this try, per the durable row.
    owner: str | None = None
    runtime_id: str | None = None
    diagnosis: str


class RunCancellationResponse(RunSummary):
    """A cancellation answer: the canonical fence plus provable physical stop.

    The inherited `status` is the canonical Run status — `cancelled` when this
    request won the durable fence that refuses a late provider success. That is
    a *logical* fact. `stop_confirmed` is the physical one, and it is False
    whenever a try is still live under a worker this replica cannot signal:
    before #1242 the response could express only the first, and every caller
    read it as both.
    """

    #: `stop_confirmed` | `stop_pending` | `uncertain` | `completion_won`.
    disposition: str
    #: The durable CANCELLED fence is written on this Run.
    fenced: bool
    #: True only when every physical try observed is durably terminal.
    stop_confirmed: bool
    #: Why the work was stopped — `requested` for a caller-driven cancellation.
    cause: str
    diagnosis: str
    attempts: list[AttemptCancellationSummary] = Field(default_factory=list)


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
