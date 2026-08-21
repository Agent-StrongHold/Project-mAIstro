"""Agent type definitions — roles, task specs, and structured outputs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class LLMProviderError(Exception):
    """Raised when the LLM provider fails after exhausting retries."""


class AgentRole(StrEnum):
    CONDUCTOR = "conductor"
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    SCOUT = "scout"


class SubTask(BaseModel):
    """A single subtask produced by the planner."""

    title: str
    description: str
    file_paths: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    """Structured output from the planning phase."""

    summary: str
    subtasks: list[SubTask]
    estimated_files: list[str] = Field(default_factory=list)


class CodeOutput(BaseModel):
    """Structured output from the coding phase."""

    files_changed: list[str]
    description: str
    tests_added: bool = False


class ReviewOutput(BaseModel):
    """Structured output from the review phase."""

    approved: bool
    score: float = Field(ge=0, le=10)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ConductorOutput(BaseModel):
    """Top-level output from the conductor — wraps the full pipeline result."""

    plan: PlanOutput | None = None
    code: CodeOutput | None = None
    review: ReviewOutput | None = None
    final_answer: str = ""
    success: bool = True
