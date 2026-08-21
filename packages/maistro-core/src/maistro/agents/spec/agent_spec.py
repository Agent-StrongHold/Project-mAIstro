"""Agent Spec envelopes — typed spawn/result contracts (ADR-004)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Lane(StrEnum):
    LIVE = "live-chat"
    BACKGROUND = "background-task"


class AgentRole(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    SCOUT = "scout"
    ARCHITECT = "architect"
    EXTRACTOR = "extractor"
    VALIDATOR = "validator"
    INTENT_ROUTER = "intent_router"
    ARTIFACT = "artifact"
    CONVERSATION = "conversation"


class ErrorType(StrEnum):
    # Recoverable
    TIMEOUT = "timeout"
    PARSE_FAILURE = "parse_failure"
    MODEL_ERROR = "model_error"
    LOW_SCORE = "low_score"
    # Non-recoverable
    SAFETY_VIOLATION = "safety_violation"
    TOOL_VIOLATION = "tool_violation"
    DEPENDENCY_FAILED = "dependency_failed"


RECOVERABLE_ERRORS: frozenset[ErrorType] = frozenset(
    {
        ErrorType.TIMEOUT,
        ErrorType.PARSE_FAILURE,
        ErrorType.MODEL_ERROR,
        ErrorType.LOW_SCORE,
    }
)

DEFAULT_TOOLS: dict[AgentRole, list[str]] = {
    AgentRole.PLANNER: ["file_ops.read", "file_ops.list", "shell.run_read_only"],
    AgentRole.CODER: ["file_ops.read", "file_ops.write", "file_ops.list", "shell.run"],
    AgentRole.REVIEWER: ["file_ops.read", "file_ops.list"],
    AgentRole.SCOUT: [
        "file_ops.read",
        "file_ops.list",
        "shell.run_read_only",
        "git.log",
        "git.diff",
    ],
    AgentRole.ARCHITECT: ["file_ops.read", "file_ops.list"],
    AgentRole.EXTRACTOR: ["file_ops.read", "file_ops.write", "file_ops.list"],
    AgentRole.VALIDATOR: ["file_ops.read", "file_ops.list", "shell.run_read_only"],
    AgentRole.INTENT_ROUTER: [],
    AgentRole.ARTIFACT: ["file_ops.read", "file_ops.write"],
    AgentRole.CONVERSATION: [],
}

_PROMPT_NAME_MAP: dict[AgentRole, str] = {
    AgentRole.PLANNER: "planner.decompose",
    AgentRole.CODER: "coder.generate",
    AgentRole.REVIEWER: "reviewer.score",
    AgentRole.SCOUT: "scout.analyze",
    AgentRole.ARCHITECT: "architect.design",
    AgentRole.EXTRACTOR: "extractor.transform",
    AgentRole.VALIDATOR: "validator.check",
}


class AgentSpec(BaseModel):
    """What the conductor sends to a spawned agent."""

    # Identity
    agent_id: str = Field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    role: AgentRole
    parent_agent_id: str | None = None
    tenant_id: str = "default"

    # Task
    task_id: str
    subtask_id: str
    description: str
    attempt: int = 1

    # Context
    context: dict[str, str] = Field(default_factory=dict)
    upstream_outputs: dict[str, str] = Field(default_factory=dict)

    # Model config
    tier: int = 2
    model_override: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    # Prompt
    prompt_name: str | None = None
    prompt_label: str = "production"
    prompt_variables: dict[str, str] = Field(default_factory=dict)

    # Recipe-driven
    recipe_name: str | None = None
    result_type: str | None = None

    # Security
    tools_allowed: list[str] = Field(default_factory=list)
    write_scopes: list[str] = Field(default_factory=list)

    # Scheduling
    lane: Lane = Lane.BACKGROUND

    # Tracing
    langfuse_trace_id: str | None = None
    langfuse_parent_span_id: str | None = None

    def with_defaults(self) -> AgentSpec:
        """Fill role-derived defaults without overwriting explicit values."""
        if not self.tools_allowed:
            self.tools_allowed = list(DEFAULT_TOOLS.get(self.role, []))
        if self.prompt_name is None:
            self.prompt_name = _PROMPT_NAME_MAP.get(self.role)
        return self


class AgentOutput(BaseModel):
    """What a spawned agent returns to the conductor."""

    # Identity (echoed from spec)
    agent_id: str
    role: AgentRole
    task_id: str
    subtask_id: str
    attempt: int = 1

    # Result
    success: bool = True
    output: str = ""
    output_parsed: dict[str, Any] | None = None

    # Error handling
    error: str | None = None
    error_type: ErrorType | None = None
    recoverable: bool = True
    escalation_reason: str | None = None

    # Metadata
    variant_used: str | None = None
    model_used: str | None = None
    tier_used: int | None = None
    tokens_used: dict[str, int] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    langfuse_span_id: str | None = None

    def mark_complete(self) -> None:
        self.completed_at = datetime.now(UTC)
        self.duration_ms = (self.completed_at - self.started_at).total_seconds() * 1000

    def mark_error(
        self,
        error: str,
        error_type: ErrorType,
        *,
        escalation_reason: str | None = None,
    ) -> None:
        self.success = False
        self.error = error
        self.error_type = error_type
        self.recoverable = error_type in RECOVERABLE_ERRORS
        self.escalation_reason = escalation_reason
        self.mark_complete()
